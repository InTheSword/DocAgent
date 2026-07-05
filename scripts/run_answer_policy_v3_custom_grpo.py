from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.rewards.combined import docqa_v3_reward_breakdown
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.run_answer_policy_v3_sft_warmup import (
    assistant_target,
    extract_allowed_refs,
    load_valid_records,
    safe_relpath,
    select_records,
    sha256_file,
    validation_path_markers,
)


SCRIPT_VERSION = "answer-policy-v3-custom-grpo-v1"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "training" / "answer_policy_v3_custom_grpo"


def repo_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def artifact_entry(path: Path) -> dict[str, Any]:
    return {"path": safe_relpath(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def prompt_messages(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(message) for message in record["messages"] if message.get("role") != "assistant"]


def to_grpo_record(record: dict[str, Any]) -> dict[str, Any] | None:
    target = assistant_target(record)
    if not isinstance(target, dict):
        return None
    support_status = str(target.get("support_status") or "")
    supporting_refs = [str(ref) for ref in target.get("supporting_refs") or [] if str(ref or "").strip()]
    allowed_refs = extract_allowed_refs(record)
    if any(ref not in allowed_refs for ref in supporting_refs):
        return None
    insufficient_expected = support_status == "insufficient"
    positive_refs = [] if insufficient_expected else supporting_refs
    gold_answer = "" if insufficient_expected else str(target.get("answer") or "")
    if not insufficient_expected and not gold_answer:
        return None
    return {
        "id": str(record.get("id") or ""),
        "source": str(record.get("source") or ""),
        "bucket": str(record.get("bucket") or ""),
        "messages": prompt_messages(record),
        "gold_answer": gold_answer,
        "positive_refs": positive_refs,
        "allowed_refs": sorted(allowed_refs),
        "answer_type": str(record.get("answer_type") or "extractive"),
        "insufficient_expected": insufficient_expected,
        "target_answer": str(target.get("answer") or ""),
        "target_support_status": support_status,
        "target_supporting_refs": supporting_refs,
    }


def load_grpo_records(paths: list[Path], *, max_records: int, seed: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    merged, audit = load_valid_records(paths)
    selected = select_records(merged, max_records=max_records, seed=seed)
    records: list[dict[str, Any]] = []
    skipped = 0
    skipped_reasons: dict[str, int] = {}
    for record in selected:
        converted = to_grpo_record(record)
        if converted is None:
            skipped += 1
            skipped_reasons["conversion_failed"] = skipped_reasons.get("conversion_failed", 0) + 1
            continue
        records.append(converted)
    audit = dict(audit)
    audit.update(
        {
            "selected_sft_record_count": len(selected),
            "converted_grpo_record_count": len(records),
            "skipped_grpo_record_count": skipped,
            "skipped_reason_counts": skipped_reasons,
        }
    )
    return records, audit


def build_prompt(tokenizer: Any, record: dict[str, Any], *, max_prompt_tokens: int | None = None) -> str:
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

    if not max_prompt_tokens or max_prompt_tokens <= 0:
        return prompt
    ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    if len(ids) <= max_prompt_tokens:
        return prompt
    return tokenizer.decode(ids[-max_prompt_tokens:], skip_special_tokens=True)


def fallback_prompt(messages: list[dict[str, Any]]) -> str:
    parts = [f"<|im_start|>{message.get('role', 'user')}\n{message.get('content', '')}<|im_end|>" for message in messages]
    parts.append("<|im_start|>assistant\n")
    return "\n".join(parts)


def extract_json_object(text: str) -> dict[str, Any] | None:
    text = str(text or "").strip()
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


def reward_prediction(prediction: dict[str, Any] | None, record: dict[str, Any]) -> dict[str, Any]:
    if prediction is None:
        return {
            "reward": 0.0,
            "format_score": 0.0,
            "schema_error": "parsed output is not an object",
            "answer_score": 0.0,
            "support_status_score": 0.0,
            "positive_ref_score": 0.0,
            "invalid_ref_penalty": 0.0,
            "insufficient_refusal_score": None,
        }
    return docqa_v3_reward_breakdown(
        prediction,
        record.get("gold_answer", ""),
        positive_refs=[str(ref) for ref in record.get("positive_refs") or []],
        answer_type=str(record.get("answer_type") or "extractive"),
        insufficient_expected=bool(record.get("insufficient_expected")),
    )


def normalize_advantages(rewards: list[float]) -> list[float]:
    if not rewards:
        return []
    mean = sum(rewards) / len(rewards)
    variance = sum((reward - mean) ** 2 for reward in rewards) / len(rewards)
    std = math.sqrt(variance)
    if std < 1e-6:
        return [reward - mean for reward in rewards]
    return [(reward - mean) / (std + 1e-6) for reward in rewards]


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


def run_custom_grpo_training(
    *,
    records: list[dict[str, Any]],
    base_model_path: Path,
    adapter_path: Path,
    output_dir: Path,
    max_steps: int,
    num_generations: int,
    max_prompt_tokens: int,
    max_new_tokens: int,
    temperature: float,
    top_p: float,
    learning_rate: float,
    seed: int,
    max_grad_norm: float,
    allow_cpu: bool,
) -> dict[str, Any]:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if not torch.cuda.is_available() and not allow_cpu:
        return {"status": "blocked", "blocker": "cuda_unavailable", "allow_cpu": allow_cpu}
    if not (base_model_path / "config.json").is_file():
        return {"status": "blocked", "blocker": "missing_base_model_config", "base_model_path": str(base_model_path)}
    if not (adapter_path / "adapter_config.json").is_file():
        return {"status": "blocked", "blocker": "missing_adapter_config", "adapter_path": safe_relpath(adapter_path)}

    random.seed(seed)
    torch.manual_seed(seed)
    tokenizer = AutoTokenizer.from_pretrained(str(base_model_path), local_files_only=True, trust_remote_code=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    dtype = torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else torch.float32
    base_model = AutoModelForCausalLM.from_pretrained(
        str(base_model_path),
        torch_dtype=dtype,
        local_files_only=True,
        trust_remote_code=True,
    )
    model = PeftModel.from_pretrained(base_model, str(adapter_path), is_trainable=True)
    model.config.use_cache = False
    if hasattr(model, "enable_input_require_grads"):
        model.enable_input_require_grads()
    if torch.cuda.is_available():
        model = model.to("cuda")
    model.train()
    optimizer = torch.optim.AdamW((param for param in model.parameters() if param.requires_grad), lr=learning_rate)

    started = time.time()
    step_summaries: list[dict[str, Any]] = []
    for step in range(max_steps):
        record = records[step % len(records)]
        prompt = build_prompt(tokenizer, record, max_prompt_tokens=max_prompt_tokens)
        prompt_inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=max_prompt_tokens)
        prompt_inputs = {key: value.to(model.device) for key, value in prompt_inputs.items()}
        prompt_len = int(prompt_inputs["input_ids"].shape[-1])

        model.eval()
        with torch.inference_mode():
            outputs = model.generate(
                **prompt_inputs,
                do_sample=True,
                temperature=temperature,
                top_p=top_p,
                num_return_sequences=num_generations,
                max_new_tokens=max_new_tokens,
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
            reward = reward_prediction(prediction, record)
            completions.append(
                {
                    "text_preview": text[:500],
                    "prediction": prediction,
                    "reward": reward["reward"],
                    "reward_components": reward,
                }
            )
            rewards.append(float(reward["reward"]))
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
            torch.nn.utils.clip_grad_norm_((param for param in model.parameters() if param.requires_grad), max_grad_norm)
            optimizer.step()
            loss_value = float(loss.detach().cpu())
        else:
            loss_value = 0.0

        reward_std = math.sqrt(sum((reward - (sum(rewards) / len(rewards))) ** 2 for reward in rewards) / len(rewards)) if rewards else 0.0
        step_summaries.append(
            {
                "step": step + 1,
                "id": record.get("id"),
                "source": record.get("source"),
                "insufficient_expected": bool(record.get("insufficient_expected")),
                "rewards": rewards,
                "reward_mean": sum(rewards) / len(rewards) if rewards else 0.0,
                "reward_max": max(rewards) if rewards else 0.0,
                "reward_std": reward_std,
                "advantages": advantages,
                "loss": loss_value,
                "best_completion": max(completions, key=lambda item: item["reward"]) if completions else None,
            }
        )
        print(json.dumps(step_summaries[-1], ensure_ascii=False), flush=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    return {
        "status": "success",
        "output_dir": safe_relpath(output_dir),
        "max_steps": max_steps,
        "num_generations": num_generations,
        "nonzero_reward_std_steps": sum(1 for item in step_summaries if float(item.get("reward_std") or 0.0) > 1e-6),
        "reward_mean_first": step_summaries[0]["reward_mean"] if step_summaries else None,
        "reward_mean_last": step_summaries[-1]["reward_mean"] if step_summaries else None,
        "steps": step_summaries,
        "duration_seconds": round(time.time() - started, 3),
    }


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    training = summary.get("training") or {}
    lines = [
        "# AnswerPolicy v3 Custom GRPO",
        "",
        f"- status: `{summary['status']}`",
        f"- run_id: `{summary['run_id']}`",
        f"- selected_record_count: `{summary['selected_record_count']}`",
        f"- execute: `{str(summary['execute']).lower()}`",
        f"- used_training: `{str(summary['used_training']).lower()}`",
        f"- validation_subset_used_for_training: `{str(summary['validation_subset_used_for_training']).lower()}`",
        f"- formal_benchmark_acceptance: `{str(summary['formal_benchmark_acceptance']).lower()}`",
    ]
    if training:
        lines.extend(["", "## Training"])
        for key in ("status", "blocker", "output_dir", "max_steps", "num_generations", "nonzero_reward_std_steps", "duration_seconds"):
            if key in training:
                lines.append(f"- {key}: `{training[key]}`")
    if summary.get("block_reasons"):
        lines.extend(["", "## Block Reasons"])
        lines.extend(f"- `{reason}`" for reason in summary["block_reasons"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_custom_grpo(
    *,
    sft_inputs: list[str | Path],
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    run_id: str = "answer_policy_v3_custom_grpo",
    base_model_path: str | Path = "/root/autodl-tmp/models/Qwen3-1.7B",
    adapter_path: str | Path,
    max_records: int = 128,
    max_steps: int = 16,
    num_generations: int = 4,
    max_prompt_tokens: int = 1536,
    max_new_tokens: int = 160,
    temperature: float = 0.9,
    top_p: float = 0.9,
    learning_rate: float = 1e-6,
    seed: int = 17,
    max_grad_norm: float = 1.0,
    execute: bool = False,
    allow_cpu: bool = False,
    allow_validation_like_input: bool = False,
    sync_output_dir: str | Path | None = None,
) -> dict[str, Any]:
    artifact_dir = repo_path(output_root) / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    grpo_train_path = artifact_dir / "grpo_train.jsonl"
    summary_path = artifact_dir / "summary.json"
    summary_md_path = artifact_dir / "summary.md"
    result_path = artifact_dir / "result.json"
    preview_path = artifact_dir / "preview.json"
    manifest_path = artifact_dir / "manifest.json"
    adapter = repo_path(adapter_path)
    grpo_output_dir = artifact_dir / "adapter"

    input_paths = [repo_path(path) for path in sft_inputs]
    block_reasons: list[str] = []
    for path in input_paths:
        if not path.is_file():
            block_reasons.append(f"missing_sft_input:{safe_relpath(path)}")
        if not allow_validation_like_input:
            markers = validation_path_markers(path)
            if markers:
                block_reasons.append(f"validation_like_input_path:{','.join(markers)}")
    if not adapter.is_dir():
        block_reasons.append(f"missing_adapter_path:{safe_relpath(adapter)}")
    elif not (adapter / "adapter_config.json").is_file():
        block_reasons.append(f"missing_adapter_config:{safe_relpath(adapter)}")

    records: list[dict[str, Any]] = []
    audit: dict[str, Any] = {}
    if not block_reasons:
        records, audit = load_grpo_records(input_paths, max_records=max_records, seed=seed)
        if not records:
            block_reasons.append("no_valid_grpo_records")

    write_jsonl(grpo_train_path, records)
    write_json(preview_path, {"records": records[:3]})

    training: dict[str, Any] = {"status": "skipped_not_executed"}
    used_training = False
    training_started = False
    status = "blocked" if block_reasons else "success"
    if execute and not block_reasons:
        training = run_custom_grpo_training(
            records=records,
            base_model_path=repo_path(base_model_path),
            adapter_path=adapter,
            output_dir=grpo_output_dir,
            max_steps=max_steps,
            num_generations=num_generations,
            max_prompt_tokens=max_prompt_tokens,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=top_p,
            learning_rate=learning_rate,
            seed=seed,
            max_grad_norm=max_grad_norm,
            allow_cpu=allow_cpu,
        )
        used_training = training.get("status") == "success"
        training_started = used_training
        status = "success" if used_training else "blocked"
        if training.get("status") != "success":
            block_reasons.append(str(training.get("blocker") or "training_not_success"))

    summary = {
        "command": "run_answer_policy_v3_custom_grpo",
        "status": status,
        "script_version": SCRIPT_VERSION,
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "base_model_path": str(base_model_path),
        "adapter_path": safe_relpath(adapter),
        "sft_inputs": [safe_relpath(path) for path in input_paths],
        "selected_record_count": len(records),
        "max_records": max_records,
        "max_steps": max_steps,
        "num_generations": num_generations,
        "max_prompt_tokens": max_prompt_tokens,
        "max_new_tokens": max_new_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "learning_rate": learning_rate,
        "execute": execute,
        "allow_cpu": allow_cpu,
        "audit": audit,
        "training": training,
        "block_reasons": block_reasons,
        "used_training": used_training,
        "training_started": training_started,
        "used_qwen": used_training,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "grpo_train_path": safe_relpath(grpo_train_path),
    }
    write_json(summary_path, summary)
    write_json(result_path, summary)
    write_summary_markdown(summary_md_path, summary)
    artifact_paths = [grpo_train_path, preview_path, result_path, summary_path, summary_md_path]
    manifest = {
        "status": status,
        "run_id": run_id,
        "script_version": SCRIPT_VERSION,
        "artifacts": [artifact_entry(path) for path in artifact_paths if path.is_file()],
        "used_training": used_training,
        "training_started": training_started,
        "used_qwen": used_training,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
    }
    write_json(manifest_path, manifest)
    summary["manifest_path"] = safe_relpath(manifest_path)
    summary["artifact_paths"] = [safe_relpath(path) for path in [*artifact_paths, manifest_path] if path.is_file()]
    if sync_output_dir:
        bundle = repo_path(sync_output_dir) / run_id
        bundle.mkdir(parents=True, exist_ok=True)
        for path in [result_path, summary_path, summary_md_path, preview_path, manifest_path]:
            if path.is_file():
                (bundle / path.name).write_bytes(path.read_bytes())
        summary["sync_bundle_path"] = safe_relpath(bundle)
    write_json(summary_path, summary)
    write_json(result_path, summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare or run a small AnswerPolicy v3 custom GRPO smoke.")
    parser.add_argument("--sft-input", action="append", required=True)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id", default="answer_policy_v3_custom_grpo")
    parser.add_argument("--base-model-path", default="/root/autodl-tmp/models/Qwen3-1.7B")
    parser.add_argument("--adapter-path", required=True)
    parser.add_argument("--max-records", type=int, default=128)
    parser.add_argument("--max-steps", type=int, default=16)
    parser.add_argument("--num-generations", type=int, default=4)
    parser.add_argument("--max-prompt-tokens", type=int, default=1536)
    parser.add_argument("--max-new-tokens", type=int, default=160)
    parser.add_argument("--temperature", type=float, default=0.9)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--learning-rate", type=float, default=1e-6)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--max-grad-norm", type=float, default=1.0)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-cpu", action="store_true")
    parser.add_argument("--allow-validation-like-input", action="store_true")
    parser.add_argument("--sync-output-dir")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        result = run_custom_grpo(
            sft_inputs=args.sft_input,
            output_root=args.output_root,
            run_id=args.run_id,
            base_model_path=args.base_model_path,
            adapter_path=args.adapter_path,
            max_records=args.max_records,
            max_steps=args.max_steps,
            num_generations=args.num_generations,
            max_prompt_tokens=args.max_prompt_tokens,
            max_new_tokens=args.max_new_tokens,
            temperature=args.temperature,
            top_p=args.top_p,
            learning_rate=args.learning_rate,
            seed=args.seed,
            max_grad_norm=args.max_grad_norm,
            execute=bool(args.execute),
            allow_cpu=bool(args.allow_cpu),
            allow_validation_like_input=bool(args.allow_validation_like_input),
            sync_output_dir=args.sync_output_dir,
        )
    except Exception as exc:
        result = {
            "command": "run_answer_policy_v3_custom_grpo",
            "status": "failed",
            "exception": f"{type(exc).__name__}: {exc}",
            "used_training": False,
            "training_started": False,
            "formal_benchmark_acceptance": False,
            "validation_subset_used_for_training": False,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
