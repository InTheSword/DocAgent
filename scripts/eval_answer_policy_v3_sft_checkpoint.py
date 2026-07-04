from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.eval.answer_metrics import exact_match
from docagent.models.output_parser import has_thinking_text
from docagent.utils.jsonl import read_jsonl, write_jsonl
from docagent.workflow.answer_contract import normalize_supporting_refs, validate_model_output_v3
from scripts.run_answer_policy_v3_sft_warmup import (
    assistant_target,
    extract_allowed_refs,
    render_messages,
    safe_relpath,
    sha256_file,
    validate_sft_record,
    validation_path_markers,
)


SCRIPT_VERSION = "answer-policy-v3-checkpoint-eval-v1"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "training_eval" / "answer_policy_v3_sft_checkpoint"


def repo_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def decode_first_json_object(text: str) -> dict[str, Any] | None:
    stripped = (text or "").strip()
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def score_prediction(record: dict[str, Any], prediction: dict[str, Any] | None, raw_text: str) -> dict[str, Any]:
    target = assistant_target(record) or {}
    allowed_refs = extract_allowed_refs(record)
    json_ok = prediction is not None
    schema_ok, schema_error = validate_model_output_v3(prediction, allowed_refs=allowed_refs) if prediction else (False, "no_json")
    target_refs = set(normalize_supporting_refs(target))
    pred_refs = set(normalize_supporting_refs(prediction or {}))
    return {
        "json_ok": json_ok,
        "schema_ok": schema_ok,
        "schema_error": schema_error,
        "answer_exact": exact_match(str((prediction or {}).get("answer") or ""), str(target.get("answer") or "")) if prediction else False,
        "support_status_match": prediction is not None and prediction.get("support_status") == target.get("support_status"),
        "supporting_refs_subset": bool(pred_refs) and pred_refs.issubset(allowed_refs) if prediction else False,
        "positive_ref_hit": bool(pred_refs & target_refs) if prediction else False,
        "has_thinking": has_thinking_text(raw_text),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "evaluated_count": 0,
            "json_valid_rate": 0.0,
            "schema_valid_rate": 0.0,
            "answer_exact_rate": 0.0,
            "support_status_match_rate": 0.0,
            "supporting_refs_subset_rate": 0.0,
            "positive_ref_hit_rate": 0.0,
            "thinking_rate": 0.0,
            "schema_error_counts": {},
        }
    total = len(rows)
    metrics = [row["metrics"] for row in rows]
    return {
        "evaluated_count": total,
        "json_valid_rate": sum(item["json_ok"] for item in metrics) / total,
        "schema_valid_rate": sum(item["schema_ok"] for item in metrics) / total,
        "answer_exact_rate": sum(item["answer_exact"] for item in metrics) / total,
        "support_status_match_rate": sum(item["support_status_match"] for item in metrics) / total,
        "supporting_refs_subset_rate": sum(item["supporting_refs_subset"] for item in metrics) / total,
        "positive_ref_hit_rate": sum(item["positive_ref_hit"] for item in metrics) / total,
        "thinking_rate": sum(item["has_thinking"] for item in metrics) / total,
        "schema_error_counts": dict(sorted(Counter(str(item.get("schema_error") or "") for item in metrics if item.get("schema_error")).items())),
    }


def load_eval_records(path: Path, *, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = read_jsonl(path)
    valid: list[dict[str, Any]] = []
    invalid = Counter()
    for row in rows:
        ok, reason = validate_sft_record(row)
        if ok:
            valid.append(row)
        else:
            invalid[reason] += 1
    if limit > 0:
        valid = valid[:limit]
    return valid, {
        "input_record_count": len(rows),
        "valid_record_count": len(valid),
        "invalid_reason_counts": dict(sorted(invalid.items())),
    }


def evaluate_with_model(
    *,
    records: list[dict[str, Any]],
    base_model_path: Path,
    adapter_path: Path | None,
    max_new_tokens: int,
    device: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if not (base_model_path / "config.json").is_file():
        return [], {"status": "blocked", "blocker": "missing_base_model_config"}
    if adapter_path is not None:
        if not (adapter_path / "adapter_config.json").is_file():
            return [], {"status": "blocked", "blocker": "missing_adapter_config"}
        if not any((adapter_path / name).is_file() for name in ("adapter_model.safetensors", "adapter_model.bin")):
            return [], {"status": "blocked", "blocker": "missing_adapter_weights"}
    if device == "cuda" and not torch.cuda.is_available():
        return [], {"status": "blocked", "blocker": "cuda_unavailable"}

    started = time.time()
    tokenizer = AutoTokenizer.from_pretrained(str(base_model_path), local_files_only=True, trust_remote_code=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    base = AutoModelForCausalLM.from_pretrained(
        str(base_model_path),
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        local_files_only=True,
        trust_remote_code=True,
    )
    if adapter_path is not None:
        from peft import PeftModel

        model = PeftModel.from_pretrained(base, str(adapter_path), is_trainable=False)
        model_mode = "peft_adapter"
    else:
        model = base
        model_mode = "base_only"
    if device == "cuda":
        model = model.to("cuda")
    elif device not in {"auto", "none"}:
        model = model.to(device)
    model.eval()

    rows: list[dict[str, Any]] = []
    with torch.inference_mode():
        for record in records:
            prompt = render_messages(tokenizer, record["messages"], include_assistant=False)
            inputs = tokenizer(prompt, return_tensors="pt")
            inputs = {key: value.to(model.device) for key, value in inputs.items()}
            output_ids = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
            )
            generated_ids = output_ids[0, inputs["input_ids"].shape[-1] :]
            raw_text = tokenizer.decode(generated_ids, skip_special_tokens=True)
            prediction = decode_first_json_object(raw_text)
            rows.append(
                {
                    "id": record.get("id"),
                    "source": record.get("source"),
                    "target": assistant_target(record),
                    "prediction": prediction,
                    "raw_text_preview": raw_text[:500],
                    "metrics": score_prediction(record, prediction, raw_text),
                }
            )
    return rows, {"status": "success", "duration_seconds": round(time.time() - started, 3), "model_mode": model_mode}


def artifact_entry(path: Path) -> dict[str, Any]:
    return {"path": safe_relpath(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    metrics = summary.get("metrics") or {}
    lines = [
        "# AnswerPolicy v3 Checkpoint Diagnostic",
        "",
        f"- status: `{summary['status']}`",
        f"- run_id: `{summary['run_id']}`",
        f"- evaluated_count: `{metrics.get('evaluated_count', 0)}`",
        f"- json_valid_rate: `{metrics.get('json_valid_rate', 0.0)}`",
        f"- schema_valid_rate: `{metrics.get('schema_valid_rate', 0.0)}`",
        f"- positive_ref_hit_rate: `{metrics.get('positive_ref_hit_rate', 0.0)}`",
        f"- used_training: `{str(summary['used_training']).lower()}`",
        f"- formal_benchmark_acceptance: `{str(summary['formal_benchmark_acceptance']).lower()}`",
    ]
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


def run_eval(
    *,
    sft_input: str | Path,
    adapter_path: str | Path | None = None,
    base_model_path: str | Path = "/root/autodl-tmp/models/Qwen3-1.7B",
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    run_id: str = "answer_policy_v3_checkpoint_eval",
    limit: int = 8,
    max_new_tokens: int = 256,
    device: str = "cuda",
    dry_run: bool = False,
    allow_validation_like_input: bool = False,
    sync_output_dir: str | Path | None = None,
) -> dict[str, Any]:
    artifact_dir = repo_path(output_root) / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    input_path = repo_path(sft_input)
    adapter = repo_path(adapter_path) if adapter_path else None
    base_model = Path(base_model_path)
    rows_path = artifact_dir / "rows.jsonl"
    result_path = artifact_dir / "result.json"
    summary_path = artifact_dir / "summary.json"
    summary_md_path = artifact_dir / "summary.md"
    preview_path = artifact_dir / "preview.json"
    manifest_path = artifact_dir / "manifest.json"

    block_reasons: list[str] = []
    if not input_path.is_file():
        block_reasons.append(f"missing_sft_input:{safe_relpath(input_path)}")
    if adapter is not None and not adapter.is_dir():
        block_reasons.append(f"missing_adapter_path:{safe_relpath(adapter)}")
    if not allow_validation_like_input:
        markers = validation_path_markers(input_path)
        if markers:
            block_reasons.append(f"validation_like_input_path:{','.join(markers)}")

    records: list[dict[str, Any]] = []
    audit: dict[str, Any] = {}
    if not block_reasons:
        records, audit = load_eval_records(input_path, limit=limit)
        if not records:
            block_reasons.append("no_valid_eval_records")

    generation = {"status": "skipped_dry_run"} if dry_run else {}
    rows: list[dict[str, Any]] = []
    status = "blocked" if block_reasons else "success"
    if not block_reasons and not dry_run:
        rows, generation = evaluate_with_model(
            records=records,
            base_model_path=base_model,
            adapter_path=adapter,
            max_new_tokens=max_new_tokens,
            device=device,
        )
        status = "success" if generation.get("status") == "success" else "blocked"
        if generation.get("status") != "success":
            block_reasons.append(str(generation.get("blocker") or "generation_not_success"))

    metrics = summarize(rows)
    write_jsonl(rows_path, rows)
    write_json(preview_path, {"rows": rows[:3]})
    summary = {
        "command": "eval_answer_policy_v3_sft_checkpoint",
        "status": status,
        "script_version": SCRIPT_VERSION,
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "sft_input": safe_relpath(input_path),
        "adapter_path": safe_relpath(adapter) if adapter is not None else "",
        "model_mode": generation.get("model_mode") or ("base_only" if adapter is None else "peft_adapter"),
        "base_model_path": str(base_model_path),
        "limit": limit,
        "dry_run": dry_run,
        "audit": audit,
        "generation": generation,
        "metrics": metrics,
        "block_reasons": block_reasons,
        "used_training": False,
        "training_started": False,
        "used_qwen": not dry_run and generation.get("status") == "success",
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
    }
    write_json(summary_path, summary)
    write_json(result_path, summary)
    write_summary_markdown(summary_md_path, summary)
    artifacts = [rows_path, preview_path, result_path, summary_path, summary_md_path]
    manifest = {
        "status": status,
        "run_id": run_id,
        "script_version": SCRIPT_VERSION,
        "artifacts": [artifact_entry(path) for path in artifacts if path.is_file()],
        "used_training": False,
        "training_started": False,
        "used_qwen": summary["used_qwen"],
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
    }
    write_json(manifest_path, manifest)
    summary["manifest_path"] = safe_relpath(manifest_path)
    summary["artifact_paths"] = [safe_relpath(path) for path in [*artifacts, manifest_path] if path.is_file()]
    if sync_output_dir:
        bundle = sync_bundle(artifact_dir, repo_path(sync_output_dir), run_id, [result_path, summary_path, summary_md_path, preview_path, manifest_path])
        summary["sync_bundle_path"] = safe_relpath(bundle)
    write_json(summary_path, summary)
    write_json(result_path, summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate a small AnswerPolicy v3 SFT checkpoint diagnostic.")
    parser.add_argument("--sft-input", required=True)
    parser.add_argument("--adapter-path")
    parser.add_argument("--base-model-path", default="/root/autodl-tmp/models/Qwen3-1.7B")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id", default="answer_policy_v3_checkpoint_eval")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-validation-like-input", action="store_true")
    parser.add_argument("--sync-output-dir")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        result = run_eval(
            sft_input=args.sft_input,
            adapter_path=args.adapter_path,
            base_model_path=args.base_model_path,
            output_root=args.output_root,
            run_id=args.run_id,
            limit=args.limit,
            max_new_tokens=args.max_new_tokens,
            device=args.device,
            dry_run=bool(args.dry_run),
            allow_validation_like_input=bool(args.allow_validation_like_input),
            sync_output_dir=args.sync_output_dir,
        )
    except Exception as exc:
        result = {
            "command": "eval_answer_policy_v3_sft_checkpoint",
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
