from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.rewards.combined import docqa_reward
from docagent.utils.jsonl import read_jsonl


def extract_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if "</think>" in text:
        text = text.rsplit("</think>", maxsplit=1)[-1].strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def prompt_messages(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(message) for message in record["messages"] if message.get("role") != "assistant"]


def build_prompt(tokenizer: Any, record: dict[str, Any]) -> str:
    messages = prompt_messages(record)
    for message in messages:
        if message.get("role") == "system":
            message["content"] = (
                f"{message.get('content', '')} "
                "Do not include analysis, chain-of-thought, markdown, or <think> tags. "
                "Return only one valid JSON object."
            )
        elif message.get("role") == "user":
            message["content"] = (
                f"{message.get('content', '')}\n\n/no_think\n"
                "Return only one valid JSON object. Start with { and end with }."
            )

    try:
        return tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
    except TypeError:
        try:
            return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        except Exception:
            pass
    except Exception:
        pass

    parts = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
    parts.append("<|im_start|>assistant\n")
    return "\n".join(parts)


def sequence_logprob(model: Any, input_ids: Any, prompt_len: int) -> Any:
    import torch

    labels = input_ids.clone()
    labels[:, :prompt_len] = -100
    outputs = model(input_ids=input_ids, attention_mask=torch.ones_like(input_ids))
    logits = outputs.logits[:, :-1, :]
    shifted_labels = labels[:, 1:]
    mask = shifted_labels.ne(-100)
    if not mask.any():
        return None
    safe_labels = shifted_labels.masked_fill(~mask, 0)
    token_logprobs = torch.log_softmax(logits, dim=-1).gather(-1, safe_labels.unsqueeze(-1)).squeeze(-1)
    return token_logprobs.masked_select(mask).mean()


def normalize_advantages(rewards: list[float]) -> list[float]:
    if not rewards:
        return []
    mean = sum(rewards) / len(rewards)
    variance = sum((reward - mean) ** 2 for reward in rewards) / len(rewards)
    std = math.sqrt(variance)
    if std < 1e-6:
        return [reward - mean for reward in rewards]
    return [(reward - mean) / (std + 1e-6) for reward in rewards]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="/root/autodl-tmp/models/Qwen3-1.7B")
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--dataset", default="data/benchmark/tatqa_train_grpo_1000_v2.jsonl")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-steps", type=int, default=1)
    parser.add_argument("--num-generations", type=int, default=2)
    parser.add_argument("--max-length", type=int, default=768)
    parser.add_argument("--max-new-tokens", type=int, default=64)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--learning-rate", type=float, default=5e-6)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--summary-output", default=None)
    args = parser.parse_args()

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    random.seed(args.seed)
    torch.manual_seed(args.seed)

    model_path = Path(args.model)
    adapter_path = Path(args.adapter)
    dataset_path = ROOT / args.dataset
    output_dir = ROOT / args.output_dir
    if not (model_path / "config.json").is_file():
        raise FileNotFoundError(f"local model is missing config.json: {model_path}")
    if not (adapter_path / "adapter_model.safetensors").is_file():
        raise FileNotFoundError(f"adapter checkpoint is missing adapter_model.safetensors: {adapter_path}")

    records = read_jsonl(dataset_path)
    if not records:
        raise ValueError(f"empty GRPO dataset: {dataset_path}")

    tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True, trust_remote_code=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
    base_model = AutoModelForCausalLM.from_pretrained(
        str(model_path),
        torch_dtype=dtype,
        local_files_only=True,
        trust_remote_code=True,
    )
    model = PeftModel.from_pretrained(base_model, str(adapter_path), is_trainable=True)
    model.config.use_cache = False
    if hasattr(model, "enable_input_require_grads"):
        model.enable_input_require_grads()
    if args.device == "cuda" and torch.cuda.is_available():
        model = model.to("cuda")
    model.train()

    optimizer = torch.optim.AdamW((param for param in model.parameters() if param.requires_grad), lr=args.learning_rate)
    step_summaries: list[dict[str, Any]] = []

    for step in range(args.max_steps):
        record = records[step % len(records)]
        prompt = build_prompt(tokenizer, record)
        prompt_inputs = tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=args.max_length,
        )
        prompt_inputs = {key: value.to(model.device) for key, value in prompt_inputs.items()}
        prompt_len = int(prompt_inputs["input_ids"].shape[-1])

        model.eval()
        with torch.inference_mode():
            outputs = model.generate(
                **prompt_inputs,
                do_sample=True,
                temperature=args.temperature,
                top_p=args.top_p,
                num_return_sequences=args.num_generations,
                max_new_tokens=args.max_new_tokens,
                pad_token_id=tokenizer.eos_token_id,
            )
        model.train()

        completions: list[dict[str, Any]] = []
        rewards: list[float] = []
        full_sequences = []
        for output_ids in outputs:
            completion_ids = output_ids[prompt_len:]
            text = tokenizer.decode(completion_ids, skip_special_tokens=True)
            prediction = extract_json_object(text)
            reward = 0.0
            if prediction is not None:
                reward = float(
                    docqa_reward(
                        prediction,
                        record.get("gold_answer", ""),
                        record.get("gold_location") or {},
                        str(record.get("answer_type") or "extractive"),
                    )
                )
            completions.append({"text": text, "prediction": prediction, "reward": reward})
            rewards.append(reward)
            full_sequences.append(output_ids.unsqueeze(0).to(model.device))

        advantages = normalize_advantages(rewards)
        loss_terms = []
        for sequence, advantage in zip(full_sequences, advantages):
            logprob = sequence_logprob(model, sequence, prompt_len)
            if logprob is None:
                continue
            loss_terms.append(-float(advantage) * logprob)

        optimizer.zero_grad(set_to_none=True)
        if loss_terms:
            loss = torch.stack(loss_terms).mean()
            loss.backward()
            torch.nn.utils.clip_grad_norm_((param for param in model.parameters() if param.requires_grad), 1.0)
            optimizer.step()
            loss_value = float(loss.detach().cpu())
        else:
            loss_value = 0.0

        step_summaries.append(
            {
                "step": step + 1,
                "id": record.get("id"),
                "rewards": rewards,
                "advantages": advantages,
                "mean_reward": sum(rewards) / len(rewards) if rewards else 0.0,
                "max_reward": max(rewards) if rewards else 0.0,
                "loss": loss_value,
                "best_completion": max(completions, key=lambda item: item["reward"]) if completions else None,
            }
        )
        print(json.dumps(step_summaries[-1], ensure_ascii=False), flush=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)

    summary = {
        "model": str(model_path),
        "start_adapter": str(adapter_path),
        "dataset": args.dataset,
        "output_dir": args.output_dir,
        "max_steps": args.max_steps,
        "num_generations": args.num_generations,
        "steps": step_summaries,
    }
    summary_output = ROOT / (args.summary_output or str(output_dir / "custom_grpo_summary.json"))
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output_dir": args.output_dir, "summary_output": str(summary_output), "num_steps": len(step_summaries)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
