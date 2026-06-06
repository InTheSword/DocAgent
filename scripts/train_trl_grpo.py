from __future__ import annotations

import argparse
import inspect
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.rewards.combined import docqa_reward
from docagent.utils.jsonl import read_jsonl


def progress(message: str) -> None:
    rank = os.environ.get("RANK", "0")
    local_rank = os.environ.get("LOCAL_RANK", "0")
    world_size = os.environ.get("WORLD_SIZE", "1")
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(
        f"[docagent-grpo {timestamp} rank={rank}/{world_size} local_rank={local_rank}] {message}",
        flush=True,
    )


def set_grpo_config_arg_if_supported(config_kwargs: dict[str, Any], config_cls: type, name: str, value: Any) -> bool:
    if value is None:
        return False
    try:
        parameters = inspect.signature(config_cls).parameters
    except (TypeError, ValueError):
        return False
    if name not in parameters:
        return False
    config_kwargs[name] = value
    return True


def prompt_messages(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(message) for message in record["messages"] if message.get("role") != "assistant"]


def build_prompt(tokenizer: Any, record: dict[str, Any], max_prompt_tokens: int | None) -> str:
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
        prompt = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
    except TypeError:
        try:
            prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        except Exception:
            prompt = fallback_prompt(messages)
    except Exception:
        prompt = fallback_prompt(messages)

    if max_prompt_tokens is None or max_prompt_tokens <= 0:
        return prompt
    ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    if len(ids) <= max_prompt_tokens:
        return prompt
    keep = ids[-max_prompt_tokens:]
    return tokenizer.decode(keep, skip_special_tokens=True)


def fallback_prompt(messages: list[dict[str, Any]]) -> str:
    parts = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
    parts.append("<|im_start|>assistant\n")
    return "\n".join(parts)


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


def completion_text(completion: Any) -> str:
    if isinstance(completion, str):
        return completion
    if isinstance(completion, list):
        parts = []
        for item in completion:
            if isinstance(item, dict):
                parts.append(str(item.get("content", "")))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    if isinstance(completion, dict):
        return str(completion.get("content", completion))
    return str(completion)


def json_loads_maybe(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def build_reward_func():
    def reward_func(prompts: list[Any], completions: list[Any], **kwargs: Any) -> list[float]:
        rewards: list[float] = []
        gold_answers = kwargs.get("gold_answer", [])
        gold_locations = kwargs.get("gold_location", [])
        answer_types = kwargs.get("answer_type", [])
        for index, completion in enumerate(completions):
            prediction = extract_json_object(completion_text(completion))
            if prediction is None:
                rewards.append(0.0)
                continue
            gold_answer = json_loads_maybe(gold_answers[index], "") if index < len(gold_answers) else ""
            gold_location = json_loads_maybe(gold_locations[index], {}) if index < len(gold_locations) else {}
            answer_type = str(answer_types[index] if index < len(answer_types) else "extractive")
            rewards.append(float(docqa_reward(prediction, gold_answer, gold_location, answer_type)))
        return rewards

    return reward_func


def build_dataset(tokenizer: Any, input_path: Path, limit: int | None, max_prompt_tokens: int | None):
    from datasets import Dataset

    progress(f"building dataset from {input_path} limit={limit}")
    records = read_jsonl(input_path)
    if limit is not None:
        records = records[:limit]
    rows = []
    for record in records:
        rows.append(
            {
                "prompt": build_prompt(tokenizer, record, max_prompt_tokens),
                "gold_answer": json.dumps(record.get("gold_answer", ""), ensure_ascii=False),
                "gold_location": json.dumps(record.get("gold_location") or {}, ensure_ascii=False),
                "answer_type": str(record.get("answer_type") or "extractive"),
                "sample_id": str(record.get("id") or ""),
            }
        )
    dataset = Dataset.from_list(rows)
    progress(f"built dataset rows={len(dataset)}")
    return dataset


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="/root/autodl-tmp/models/Qwen3-1.7B")
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--dataset", default="data/benchmark/tatqa_train_grpo_1000_v2.jsonl")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--limit", type=int, default=64)
    parser.add_argument("--max-steps", type=int, default=1)
    parser.add_argument("--num-generations", type=int, default=2)
    parser.add_argument("--per-device-train-batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=2)
    parser.add_argument("--learning-rate", type=float, default=5e-6)
    parser.add_argument("--max-prompt-tokens", type=int, default=768)
    parser.add_argument("--max-completion-length", type=int, default=64)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--summary-output")
    parser.add_argument("--allow-cpu", action="store_true")
    args = parser.parse_args()

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from trl import GRPOConfig, GRPOTrainer

    local_rank = int(os.environ.get("LOCAL_RANK", "0"))
    if torch.cuda.is_available():
        torch.cuda.set_device(local_rank)
        device = torch.device("cuda", local_rank)
        progress(
            "cuda ready "
            f"device={device} name={torch.cuda.get_device_name(device)} "
            f"bf16={torch.cuda.is_bf16_supported()}"
        )
    else:
        device = torch.device("cpu")
        message = (
            "CUDA is unavailable. Refusing to run GRPO on CPU because it is too slow for this project. "
            "Check GPU mode, driver/runtime compatibility, and torch CUDA build."
        )
        if not args.allow_cpu:
            raise RuntimeError(message)
        progress(f"{message} --allow-cpu was set, continuing on CPU")

    model_path = Path(args.model)
    adapter_path = Path(args.adapter)
    output_dir = ROOT / args.output_dir
    if not (model_path / "config.json").is_file():
        raise FileNotFoundError(f"local model is missing config.json: {model_path}")
    if not (adapter_path / "adapter_model.safetensors").is_file():
        raise FileNotFoundError(f"adapter checkpoint is missing adapter_model.safetensors: {adapter_path}")

    progress(f"loading tokenizer from {model_path}")
    tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True, trust_remote_code=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    train_dataset = build_dataset(tokenizer, ROOT / args.dataset, args.limit, args.max_prompt_tokens)

    dtype = torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else torch.float32
    progress(f"loading base model dtype={dtype}")
    base_model = AutoModelForCausalLM.from_pretrained(
        str(model_path),
        torch_dtype=dtype,
        local_files_only=True,
        trust_remote_code=True,
    )
    progress(f"loading trainable adapter from {adapter_path}")
    model = PeftModel.from_pretrained(base_model, str(adapter_path), is_trainable=True)
    model.config.use_cache = False
    if hasattr(model, "enable_input_require_grads"):
        model.enable_input_require_grads()
    if device.type == "cuda":
        progress(f"moving model to {device}")
        model = model.to(device)

    progress(
        "building GRPO trainer "
        f"steps={args.max_steps} num_generations={args.num_generations} "
        f"per_device_batch={args.per_device_train_batch_size}"
    )
    config_kwargs = {
        "output_dir": str(output_dir),
        "max_steps": args.max_steps,
        "per_device_train_batch_size": args.per_device_train_batch_size,
        "gradient_accumulation_steps": args.gradient_accumulation_steps,
        "learning_rate": args.learning_rate,
        "bf16": torch.cuda.is_available() and torch.cuda.is_bf16_supported(),
        "gradient_checkpointing": True,
        "max_completion_length": args.max_completion_length,
        "num_generations": args.num_generations,
        "generation_batch_size": args.num_generations,
        "temperature": args.temperature,
        "top_p": args.top_p,
        "use_vllm": False,
        "beta": 0.0,
        "save_steps": args.max_steps,
        "save_total_limit": 1,
        "save_only_model": True,
        "logging_steps": 1,
        "report_to": "none",
        "dataloader_num_workers": 0,
        "remove_unused_columns": False,
        "seed": args.seed,
    }
    max_prompt_length = args.max_prompt_tokens if args.max_prompt_tokens and args.max_prompt_tokens > 0 else None
    if not set_grpo_config_arg_if_supported(config_kwargs, GRPOConfig, "max_prompt_length", max_prompt_length):
        if max_prompt_length is not None:
            progress(
                "GRPOConfig does not support max_prompt_length; "
                f"using pre-rendered prompt cap only max_prompt_tokens={max_prompt_length}"
            )
    training_args = GRPOConfig(**config_kwargs)
    trainer = GRPOTrainer(
        model=model,
        reward_funcs=build_reward_func(),
        args=training_args,
        train_dataset=train_dataset,
        processing_class=tokenizer,
    )
    progress("trainer.train start")
    trainer.train()
    progress("trainer.train done")
    if hasattr(trainer, "accelerator"):
        trainer.accelerator.wait_for_everyone()
    if int(os.environ.get("RANK", "0")) == 0:
        progress(f"saving adapter to {output_dir}")
        trainer.save_model(str(output_dir))
        tokenizer.save_pretrained(str(output_dir))

        summary = {
            "model": str(model_path),
            "start_adapter": str(adapter_path),
            "dataset": args.dataset,
            "output_dir": args.output_dir,
            "limit": args.limit,
            "max_steps": args.max_steps,
            "num_generations": args.num_generations,
            "log_history": trainer.state.log_history,
        }
        summary_output = ROOT / (args.summary_output or str(output_dir / "trl_grpo_summary.json"))
        summary_output.parent.mkdir(parents=True, exist_ok=True)
        summary_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"output_dir": args.output_dir, "summary_output": str(summary_output)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
