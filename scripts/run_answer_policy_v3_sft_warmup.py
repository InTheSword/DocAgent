from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import read_jsonl, write_jsonl
from docagent.workflow.answer_contract import validate_model_output_v3


SCRIPT_VERSION = "answer-policy-v3-sft-warmup-v1"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "training" / "answer_policy_v3_sft_warmup"
VALIDATION_PATH_MARKERS = {"dev", "val", "valid", "validation", "test", "final_eval"}


def repo_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def safe_relpath(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validation_path_markers(path: Path) -> list[str]:
    markers: list[str] = []
    for part in path.parts:
        normalized = part.lower().replace("-", "_")
        if normalized in VALIDATION_PATH_MARKERS:
            markers.append(part)
    return markers


def extract_allowed_refs(record: dict[str, Any]) -> set[str]:
    messages = record.get("messages") if isinstance(record.get("messages"), list) else []
    user_text = "\n".join(str(message.get("content") or "") for message in messages if message.get("role") == "user")
    return set(re.findall(r"\[(E\d+)\]", user_text))


def assistant_target(record: dict[str, Any]) -> dict[str, Any] | None:
    messages = record.get("messages") if isinstance(record.get("messages"), list) else []
    if not messages or messages[-1].get("role") != "assistant":
        return None
    try:
        target = json.loads(str(messages[-1].get("content") or "{}"))
    except json.JSONDecodeError:
        return None
    return target if isinstance(target, dict) else None


def validate_sft_record(record: dict[str, Any]) -> tuple[bool, str]:
    messages = record.get("messages")
    if not isinstance(messages, list) or len(messages) < 3:
        return False, "missing_messages"
    if [message.get("role") for message in messages[-3:]] != ["system", "user", "assistant"]:
        return False, "messages_must_end_system_user_assistant"
    target = assistant_target(record)
    if target is None:
        return False, "invalid_assistant_json"
    ok, error = validate_model_output_v3(target, allowed_refs=extract_allowed_refs(record))
    if not ok:
        return False, f"invalid_v3_target:{error}"
    return True, ""


def load_valid_records(paths: list[Path]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records_by_path: list[list[dict[str, Any]]] = []
    audit = {
        "input_count": len(paths),
        "input_paths": [safe_relpath(path) for path in paths],
        "input_record_counts": {},
        "invalid_record_counts": {},
        "invalid_reason_counts": {},
        "source_counts": {},
    }
    invalid_reasons = Counter()
    source_counts = Counter()
    for path in paths:
        rows = read_jsonl(path)
        valid_rows: list[dict[str, Any]] = []
        invalid_count = 0
        for row in rows:
            ok, reason = validate_sft_record(row)
            if not ok:
                invalid_count += 1
                invalid_reasons[reason] += 1
                continue
            valid_rows.append(row)
            source_counts[str(row.get("source") or "unknown")] += 1
        records_by_path.append(valid_rows)
        audit["input_record_counts"][safe_relpath(path)] = len(rows)
        audit["invalid_record_counts"][safe_relpath(path)] = invalid_count
    audit["invalid_reason_counts"] = dict(sorted(invalid_reasons.items()))
    audit["source_counts"] = dict(sorted(source_counts.items()))
    merged = round_robin(records_by_path)
    return merged, audit


def round_robin(groups: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    max_len = max((len(group) for group in groups), default=0)
    for index in range(max_len):
        for group in groups:
            if index < len(group):
                merged.append(group[index])
    return merged


def select_records(records: list[dict[str, Any]], *, max_records: int, seed: int) -> list[dict[str, Any]]:
    if max_records <= 0 or len(records) <= max_records:
        return list(records)
    return records[:max_records]


def render_messages(tokenizer: Any, messages: list[dict[str, Any]], *, include_assistant: bool) -> str:
    selected = messages if include_assistant else messages[:-1]
    try:
        return tokenizer.apply_chat_template(
            selected,
            tokenize=False,
            add_generation_prompt=not include_assistant,
            enable_thinking=False,
        )
    except TypeError:
        try:
            return tokenizer.apply_chat_template(selected, tokenize=False, add_generation_prompt=not include_assistant)
        except Exception:
            pass
    except Exception:
        pass
    text = "\n".join(f"{message.get('role')}: {message.get('content')}" for message in selected)
    return f"{text}\nassistant:" if not include_assistant else text


@dataclass
class EncodedExample:
    input_ids: list[int]
    labels: list[int]


def encode_record(tokenizer: Any, record: dict[str, Any], *, max_length: int) -> EncodedExample | None:
    messages = record["messages"]
    prompt_text = render_messages(tokenizer, messages, include_assistant=False)
    full_text = render_messages(tokenizer, messages, include_assistant=True)
    prompt_ids = tokenizer(prompt_text, add_special_tokens=False)["input_ids"]
    full_ids = tokenizer(full_text, add_special_tokens=False)["input_ids"]
    if len(full_ids) <= len(prompt_ids):
        assistant_ids = tokenizer(str(messages[-1].get("content") or ""), add_special_tokens=False)["input_ids"]
        full_ids = [*prompt_ids, *assistant_ids]
    labels = [-100] * min(len(prompt_ids), len(full_ids)) + full_ids[min(len(prompt_ids), len(full_ids)) :]
    if len(full_ids) > max_length:
        overflow = len(full_ids) - max_length
        full_ids = full_ids[overflow:]
        labels = labels[overflow:]
    if not any(label != -100 for label in labels):
        return None
    return EncodedExample(input_ids=full_ids, labels=labels)


def train_lora(
    *,
    records: list[dict[str, Any]],
    base_model_path: Path,
    adapter_output_dir: Path,
    max_steps: int,
    max_length: int,
    learning_rate: float,
    batch_size: int,
    gradient_accumulation_steps: int,
    lora_rank: int,
    lora_alpha: int,
    seed: int,
    allow_cpu: bool,
) -> dict[str, Any]:
    import torch
    from peft import LoraConfig, get_peft_model
    from torch.utils.data import DataLoader
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if not (base_model_path / "config.json").is_file():
        return {"status": "blocked", "blocker": "missing_base_model_config", "base_model_path": str(base_model_path)}
    cuda_available = bool(torch.cuda.is_available())
    if not cuda_available and not allow_cpu:
        return {"status": "blocked", "blocker": "cuda_unavailable", "allow_cpu": allow_cpu}

    random.seed(seed)
    torch.manual_seed(seed)
    tokenizer = AutoTokenizer.from_pretrained(str(base_model_path), local_files_only=True, trust_remote_code=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    encoded = [item for item in (encode_record(tokenizer, record, max_length=max_length) for record in records) if item is not None]
    if not encoded:
        return {"status": "blocked", "blocker": "no_trainable_encoded_records"}

    dtype = torch.bfloat16 if cuda_available else torch.float32
    model = AutoModelForCausalLM.from_pretrained(
        str(base_model_path),
        torch_dtype=dtype,
        local_files_only=True,
        trust_remote_code=True,
    )
    model.config.use_cache = False
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
    lora_config = LoraConfig(
        r=lora_rank,
        lora_alpha=lora_alpha,
        target_modules=target_modules,
        lora_dropout=0.0,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)
    if cuda_available:
        model = model.to("cuda")
    model.train()

    def collate(batch: list[EncodedExample]) -> dict[str, Any]:
        max_len = max(len(item.input_ids) for item in batch)
        input_ids = []
        labels = []
        attention_mask = []
        pad_id = tokenizer.pad_token_id
        for item in batch:
            pad_count = max_len - len(item.input_ids)
            input_ids.append(item.input_ids + [pad_id] * pad_count)
            labels.append(item.labels + [-100] * pad_count)
            attention_mask.append([1] * len(item.input_ids) + [0] * pad_count)
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "attention_mask": torch.tensor(attention_mask, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
        }

    loader = DataLoader(encoded, batch_size=batch_size, shuffle=True, collate_fn=collate)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate)
    losses: list[float] = []
    step = 0
    optimizer.zero_grad(set_to_none=True)
    started = time.time()
    while step < max_steps:
        for batch_index, batch in enumerate(loader, start=1):
            batch = {key: value.to(model.device) for key, value in batch.items()}
            output = model(**batch)
            loss = output.loss / gradient_accumulation_steps
            loss.backward()
            losses.append(float(output.loss.detach().cpu()))
            if batch_index % gradient_accumulation_steps == 0:
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
                step += 1
                if step >= max_steps:
                    break
        if len(loader) < gradient_accumulation_steps and step == 0:
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
            step += 1
        if step >= max_steps:
            break

    adapter_output_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(adapter_output_dir))
    tokenizer.save_pretrained(str(adapter_output_dir))
    trainable_params = sum(param.numel() for param in model.parameters() if param.requires_grad)
    total_params = sum(param.numel() for param in model.parameters())
    return {
        "status": "success",
        "adapter_path": safe_relpath(adapter_output_dir),
        "encoded_record_count": len(encoded),
        "steps_completed": step,
        "max_steps": max_steps,
        "loss_first": losses[0] if losses else None,
        "loss_last": losses[-1] if losses else None,
        "loss_mean": sum(losses) / len(losses) if losses else None,
        "trainable_params": trainable_params,
        "total_params": total_params,
        "trainable_param_ratio": trainable_params / total_params if total_params else 0.0,
        "cuda_available": cuda_available,
        "duration_seconds": round(time.time() - started, 3),
    }


def artifact_entry(path: Path) -> dict[str, Any]:
    return {"path": safe_relpath(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# AnswerPolicy v3 SFT Warmup",
        "",
        f"- status: `{summary['status']}`",
        f"- run_id: `{summary['run_id']}`",
        f"- selected_record_count: `{summary['selected_record_count']}`",
        f"- used_training: `{str(summary['used_training']).lower()}`",
        f"- validation_subset_used_for_training: `{str(summary['validation_subset_used_for_training']).lower()}`",
        f"- formal_benchmark_acceptance: `{str(summary['formal_benchmark_acceptance']).lower()}`",
    ]
    train = summary.get("training") or {}
    if train:
        lines.extend(["", "## Training"])
        for key in ("status", "adapter_path", "steps_completed", "loss_first", "loss_last", "cuda_available"):
            if key in train:
                lines.append(f"- {key}: `{train[key]}`")
    if summary.get("block_reasons"):
        lines.extend(["", "## Block Reasons"])
        lines.extend(f"- `{reason}`" for reason in summary["block_reasons"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sync_bundle(artifact_dir: Path, sync_output_dir: Path, run_id: str, paths: list[Path]) -> Path:
    bundle = sync_output_dir / run_id
    bundle.mkdir(parents=True, exist_ok=True)
    for path in paths:
        if path.is_file():
            shutil.copy2(path, bundle / path.name)
    return bundle


def run_warmup(
    *,
    sft_inputs: list[str | Path],
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    run_id: str = "answer_policy_v3_sft_warmup",
    base_model_path: str | Path = "/root/autodl-tmp/models/Qwen3-1.7B",
    max_records: int = 64,
    max_steps: int = 3,
    max_length: int = 2048,
    learning_rate: float = 1e-4,
    batch_size: int = 1,
    gradient_accumulation_steps: int = 4,
    lora_rank: int = 8,
    lora_alpha: int = 16,
    seed: int = 17,
    dry_run: bool = False,
    allow_cpu: bool = False,
    allow_validation_like_input: bool = False,
    sync_output_dir: str | Path | None = None,
) -> dict[str, Any]:
    artifact_dir = repo_path(output_root) / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    warmup_train_path = artifact_dir / "warmup_train.jsonl"
    result_path = artifact_dir / "result.json"
    summary_path = artifact_dir / "summary.json"
    summary_md_path = artifact_dir / "summary.md"
    preview_path = artifact_dir / "preview.json"
    manifest_path = artifact_dir / "manifest.json"
    adapter_dir = artifact_dir / "adapter"

    input_paths = [repo_path(path) for path in sft_inputs]
    block_reasons: list[str] = []
    for path in input_paths:
        if not path.is_file():
            block_reasons.append(f"missing_sft_input:{safe_relpath(path)}")
        if not allow_validation_like_input:
            markers = validation_path_markers(path)
            if markers:
                block_reasons.append(f"validation_like_input_path:{','.join(markers)}")

    audit: dict[str, Any] = {}
    selected: list[dict[str, Any]] = []
    if not block_reasons:
        merged, audit = load_valid_records(input_paths)
        selected = select_records(merged, max_records=max_records, seed=seed)
        if not selected:
            block_reasons.append("no_valid_sft_records")

    write_jsonl(warmup_train_path, selected)
    write_json(preview_path, {"records": selected[:3]})
    training = {"status": "skipped_dry_run"} if dry_run else {}
    status = "blocked" if block_reasons else "success"
    used_training = False
    if not block_reasons and not dry_run:
        training = train_lora(
            records=selected,
            base_model_path=Path(base_model_path),
            adapter_output_dir=adapter_dir,
            max_steps=max_steps,
            max_length=max_length,
            learning_rate=learning_rate,
            batch_size=batch_size,
            gradient_accumulation_steps=gradient_accumulation_steps,
            lora_rank=lora_rank,
            lora_alpha=lora_alpha,
            seed=seed,
            allow_cpu=allow_cpu,
        )
        used_training = training.get("status") == "success"
        status = "success" if training.get("status") == "success" else "blocked"
        if training.get("status") != "success":
            block_reasons.append(str(training.get("blocker") or "training_not_success"))

    summary = {
        "command": "run_answer_policy_v3_sft_warmup",
        "status": status,
        "script_version": SCRIPT_VERSION,
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "base_model_path": str(base_model_path),
        "sft_inputs": [safe_relpath(path) for path in input_paths],
        "selected_record_count": len(selected),
        "max_records": max_records,
        "max_steps": max_steps,
        "dry_run": dry_run,
        "audit": audit,
        "training": training,
        "block_reasons": block_reasons,
        "used_training": used_training,
        "training_started": used_training,
        "used_qwen": used_training,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "warmup_train_path": safe_relpath(warmup_train_path),
        "adapter_path": training.get("adapter_path") if isinstance(training, dict) else "",
    }
    write_json(summary_path, summary)
    write_json(result_path, summary)
    write_summary_markdown(summary_md_path, summary)
    artifact_paths = [warmup_train_path, preview_path, result_path, summary_path, summary_md_path]
    manifest = {
        "status": status,
        "run_id": run_id,
        "script_version": SCRIPT_VERSION,
        "artifacts": [artifact_entry(path) for path in artifact_paths if path.is_file()],
        "used_training": used_training,
        "training_started": used_training,
        "used_qwen": used_training,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
    }
    write_json(manifest_path, manifest)
    summary["manifest_path"] = safe_relpath(manifest_path)
    summary["artifact_paths"] = [safe_relpath(path) for path in [*artifact_paths, manifest_path] if path.is_file()]
    if sync_output_dir:
        bundle = sync_bundle(artifact_dir, repo_path(sync_output_dir), run_id, [result_path, summary_path, summary_md_path, preview_path, manifest_path])
        summary["sync_bundle_path"] = safe_relpath(bundle)
    write_json(summary_path, summary)
    write_json(result_path, summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a small AnswerPolicy v3 LoRA SFT warmup.")
    parser.add_argument("--sft-input", action="append", required=True)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id", default="answer_policy_v3_sft_warmup")
    parser.add_argument("--base-model-path", default="/root/autodl-tmp/models/Qwen3-1.7B")
    parser.add_argument("--max-records", type=int, default=64)
    parser.add_argument("--max-steps", type=int, default=3)
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=4)
    parser.add_argument("--lora-rank", type=int, default=8)
    parser.add_argument("--lora-alpha", type=int, default=16)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-cpu", action="store_true")
    parser.add_argument("--allow-validation-like-input", action="store_true")
    parser.add_argument("--sync-output-dir")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        result = run_warmup(
            sft_inputs=args.sft_input,
            output_root=args.output_root,
            run_id=args.run_id,
            base_model_path=args.base_model_path,
            max_records=args.max_records,
            max_steps=args.max_steps,
            max_length=args.max_length,
            learning_rate=args.learning_rate,
            batch_size=args.batch_size,
            gradient_accumulation_steps=args.gradient_accumulation_steps,
            lora_rank=args.lora_rank,
            lora_alpha=args.lora_alpha,
            seed=args.seed,
            dry_run=bool(args.dry_run),
            allow_cpu=bool(args.allow_cpu),
            allow_validation_like_input=bool(args.allow_validation_like_input),
            sync_output_dir=args.sync_output_dir,
        )
    except Exception as exc:
        result = {
            "command": "run_answer_policy_v3_sft_warmup",
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
