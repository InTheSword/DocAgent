from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import read_jsonl, write_jsonl
from docagent.workflow.answer_contract import validate_model_output_v3
from scripts.eval_answer_policy_v3_sft_checkpoint import decode_first_json_object
from scripts.run_answer_policy_v3_sft_warmup import (
    assistant_target,
    extract_allowed_refs,
    render_messages,
    safe_relpath,
    sha256_file,
    validate_sft_record,
    validation_path_markers,
)


SCRIPT_VERSION = "answer-policy-v3-candidate-generation-v1"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "training_prep" / "answer_policy_v3_candidates"


def repo_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def artifact_entry(path: Path) -> dict[str, Any]:
    return {"path": safe_relpath(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def load_records(paths: list[Path], *, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    invalid = Counter()
    duplicate_count = 0
    audit = {
        "input_paths": [safe_relpath(path) for path in paths],
        "input_record_counts": {},
        "valid_record_count": 0,
        "duplicate_record_count": 0,
        "invalid_reason_counts": {},
    }
    for path in paths:
        rows = read_jsonl(path)
        audit["input_record_counts"][safe_relpath(path)] = len(rows)
        for row in rows:
            ok, reason = validate_sft_record(row)
            if not ok:
                invalid[reason] += 1
                continue
            record_id = str(row.get("id") or "")
            if record_id in seen:
                duplicate_count += 1
                continue
            seen.add(record_id)
            records.append(row)
    if limit > 0:
        records = records[:limit]
    audit["valid_record_count"] = len(records)
    audit["duplicate_record_count"] = duplicate_count
    audit["invalid_reason_counts"] = dict(sorted(invalid.items()))
    return records, audit


def candidate_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = 0
    parsed = 0
    schema_ok = 0
    source_counts = Counter()
    schema_errors = Counter()
    for row in rows:
        for candidate in row.get("candidates") or []:
            total += 1
            source_counts[str(candidate.get("candidate_source") or "")] += 1
            if candidate.get("raw_json_ok"):
                parsed += 1
            if candidate.get("schema_ok"):
                schema_ok += 1
            error = str(candidate.get("schema_error") or "")
            if error:
                schema_errors[error] += 1
    return {
        "record_count": len(rows),
        "candidate_count": total,
        "candidate_source_counts": dict(sorted(source_counts.items())),
        "raw_json_ok_count": parsed,
        "raw_json_ok_rate": parsed / total if total else 0.0,
        "schema_ok_count": schema_ok,
        "schema_ok_rate": schema_ok / total if total else 0.0,
        "schema_error_counts": dict(sorted(schema_errors.items())),
    }


def make_candidate(
    *,
    record: dict[str, Any],
    candidate_id: str,
    candidate_source: str,
    raw_text: str,
    prediction: dict[str, Any] | None,
    generation_index: int,
) -> dict[str, Any]:
    allowed_refs = extract_allowed_refs(record)
    schema_ok, schema_error = validate_model_output_v3(prediction, allowed_refs=allowed_refs) if prediction else (False, "no_json")
    return {
        "candidate_id": candidate_id,
        "candidate_source": candidate_source,
        "generation_index": generation_index,
        "prediction": prediction or {},
        "raw_text": raw_text,
        "raw_text_preview": raw_text[:500],
        "raw_json_ok": prediction is not None,
        "schema_ok": schema_ok,
        "schema_error": schema_error,
    }


def synthetic_dry_run_candidates(records: list[dict[str, Any]], *, num_candidates: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        target = assistant_target(record) or {}
        candidates = []
        for index in range(num_candidates):
            raw_text = json.dumps(target, ensure_ascii=False)
            candidates.append(
                make_candidate(
                    record=record,
                    candidate_id=f"{record.get('id')}:dryrun:{index}",
                    candidate_source="synthetic_dry_run",
                    raw_text=raw_text,
                    prediction=target,
                    generation_index=index,
                )
            )
        rows.append(
            {
                "id": record.get("id"),
                "source": record.get("source"),
                "target": target,
                "candidates": candidates,
            }
        )
    return rows, {"status": "skipped_dry_run", "candidate_source": "synthetic_dry_run"}


def generate_with_model(
    *,
    records: list[dict[str, Any]],
    base_model_path: Path,
    adapter_path: Path | None,
    num_candidates: int,
    max_new_tokens: int,
    temperature: float,
    top_p: float,
    seed: int,
    device: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if not (base_model_path / "config.json").is_file():
        return [], {"status": "blocked", "blocker": "missing_base_model_config", "base_model_path": str(base_model_path)}
    if adapter_path is not None and not (adapter_path / "adapter_config.json").is_file():
        return [], {"status": "blocked", "blocker": "missing_adapter_config", "adapter_path": str(adapter_path)}
    if device == "cuda" and not torch.cuda.is_available():
        return [], {"status": "blocked", "blocker": "cuda_unavailable"}

    started = time.time()
    tokenizer = AutoTokenizer.from_pretrained(str(base_model_path), local_files_only=True, trust_remote_code=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        str(base_model_path),
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        local_files_only=True,
        trust_remote_code=True,
    )
    loaded_adapter = False
    if adapter_path is not None:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, str(adapter_path), is_trainable=False)
        loaded_adapter = True
    if device == "cuda":
        model = model.to("cuda")
    elif device not in {"auto", "none"}:
        model = model.to(device)
    model.eval()

    rows: list[dict[str, Any]] = []
    do_sample = num_candidates > 1 or temperature > 0.0
    generation_kwargs: dict[str, Any] = {
        "max_new_tokens": max_new_tokens,
        "do_sample": do_sample,
        "pad_token_id": tokenizer.eos_token_id,
    }
    if do_sample:
        generation_kwargs.update({"temperature": max(temperature, 1e-5), "top_p": top_p})
    with torch.inference_mode():
        for record in records:
            prompt = render_messages(tokenizer, record["messages"], include_assistant=False)
            inputs = tokenizer(prompt, return_tensors="pt")
            inputs = {key: value.to(model.device) for key, value in inputs.items()}
            candidates: list[dict[str, Any]] = []
            for index in range(num_candidates):
                torch.manual_seed(seed + index)
                if torch.cuda.is_available():
                    torch.cuda.manual_seed_all(seed + index)
                output_ids = model.generate(**inputs, **generation_kwargs)
                generated_ids = output_ids[0, inputs["input_ids"].shape[-1] :]
                raw_text = tokenizer.decode(generated_ids, skip_special_tokens=True)
                prediction = decode_first_json_object(raw_text)
                candidates.append(
                    make_candidate(
                        record=record,
                        candidate_id=f"{record.get('id')}:model:{index}",
                        candidate_source="model_generation",
                        raw_text=raw_text,
                        prediction=prediction,
                        generation_index=index,
                    )
                )
            rows.append(
                {
                    "id": record.get("id"),
                    "source": record.get("source"),
                    "target": assistant_target(record),
                    "candidates": candidates,
                }
            )
    return rows, {
        "status": "success",
        "duration_seconds": round(time.time() - started, 3),
        "loaded_adapter": loaded_adapter,
        "num_candidates": num_candidates,
        "max_new_tokens": max_new_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "seed": seed,
    }


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    metrics = summary.get("metrics") or {}
    lines = [
        "# AnswerPolicy v3 Candidate Generation",
        "",
        f"- status: `{summary['status']}`",
        f"- run_id: `{summary['run_id']}`",
        f"- record_count: `{metrics.get('record_count', 0)}`",
        f"- candidate_count: `{metrics.get('candidate_count', 0)}`",
        f"- schema_ok_rate: `{metrics.get('schema_ok_rate', 0.0)}`",
        f"- used_qwen: `{str(summary['used_qwen']).lower()}`",
        f"- used_training: `{str(summary['used_training']).lower()}`",
        f"- validation_subset_used_for_training: `{str(summary['validation_subset_used_for_training']).lower()}`",
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


def generate_candidates(
    *,
    sft_inputs: list[str | Path],
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    run_id: str = "answer_policy_v3_candidates",
    base_model_path: str | Path = "/root/autodl-tmp/models/Qwen3-1.7B",
    adapter_path: str | Path | None = None,
    limit: int = 16,
    num_candidates: int = 4,
    max_new_tokens: int = 256,
    temperature: float = 0.7,
    top_p: float = 0.9,
    seed: int = 17,
    device: str = "cuda",
    dry_run: bool = False,
    allow_validation_like_input: bool = False,
    sync_output_dir: str | Path | None = None,
) -> dict[str, Any]:
    artifact_dir = repo_path(output_root) / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    candidates_path = artifact_dir / "candidates.jsonl"
    result_path = artifact_dir / "result.json"
    summary_path = artifact_dir / "summary.json"
    summary_md_path = artifact_dir / "summary.md"
    preview_path = artifact_dir / "preview.json"
    manifest_path = artifact_dir / "manifest.json"

    input_paths = [repo_path(path) for path in sft_inputs]
    block_reasons: list[str] = []
    for path in input_paths:
        if not path.is_file():
            block_reasons.append(f"missing_sft_input:{safe_relpath(path)}")
        if not allow_validation_like_input:
            markers = validation_path_markers(path)
            if markers:
                block_reasons.append(f"validation_like_input_path:{safe_relpath(path)}:{','.join(markers)}")
    if not input_paths:
        block_reasons.append("no_sft_inputs")
    if num_candidates <= 0:
        block_reasons.append("num_candidates_must_be_positive")

    records: list[dict[str, Any]] = []
    audit: dict[str, Any] = {}
    if not block_reasons:
        records, audit = load_records(input_paths, limit=limit)
        if not records:
            block_reasons.append("no_valid_sft_records")

    generation = {"status": "skipped_blocked"} if block_reasons else {}
    rows: list[dict[str, Any]] = []
    status = "blocked" if block_reasons else "success"
    if not block_reasons:
        if dry_run:
            rows, generation = synthetic_dry_run_candidates(records, num_candidates=num_candidates)
        else:
            rows, generation = generate_with_model(
                records=records,
                base_model_path=Path(base_model_path),
                adapter_path=Path(adapter_path) if adapter_path else None,
                num_candidates=num_candidates,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                seed=seed,
                device=device,
            )
            status = "success" if generation.get("status") == "success" else "blocked"
            if generation.get("status") != "success":
                block_reasons.append(str(generation.get("blocker") or "generation_not_success"))

    metrics = candidate_metrics(rows)
    write_jsonl(candidates_path, rows)
    write_json(preview_path, {"rows": rows[:3]})
    recommendation = {
        "next_action": "rank_candidates_with_rejection_sampling_artifact_builder"
        if rows and not dry_run and generation.get("status") == "success"
        else "run_real_model_candidate_generation_before_rejection_sampling",
        "do_not_train_yet": True,
        "reason": (
            "This script only generates AnswerPolicy v3 candidate outputs from train-only records. "
            "It does not start training, use validation data, or approve DPO/GRPO."
        ),
    }
    summary = {
        "command": "generate_answer_policy_v3_candidates",
        "status": status,
        "script_version": SCRIPT_VERSION,
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "sft_inputs": [safe_relpath(path) for path in input_paths],
        "base_model_path": str(base_model_path),
        "adapter_path": str(adapter_path or ""),
        "limit": limit,
        "num_candidates": num_candidates,
        "dry_run": dry_run,
        "audit": audit,
        "generation": generation,
        "metrics": metrics,
        "block_reasons": block_reasons,
        "recommendation": recommendation,
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
    artifacts = [candidates_path, preview_path, result_path, summary_path, summary_md_path]
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
    summary["candidate_path"] = safe_relpath(candidates_path)
    summary["manifest_path"] = safe_relpath(manifest_path)
    summary["artifact_paths"] = [safe_relpath(path) for path in [*artifacts, manifest_path] if path.is_file()]
    if sync_output_dir:
        bundle = sync_bundle(artifact_dir, repo_path(sync_output_dir), run_id, [result_path, summary_path, summary_md_path, preview_path, manifest_path])
        summary["sync_bundle_path"] = safe_relpath(bundle)
    write_json(summary_path, summary)
    write_json(result_path, summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate AnswerPolicy v3 candidate outputs for rejection sampling.")
    parser.add_argument("--sft-input", action="append", required=True)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id", default="answer_policy_v3_candidates")
    parser.add_argument("--base-model-path", default="/root/autodl-tmp/models/Qwen3-1.7B")
    parser.add_argument("--adapter-path")
    parser.add_argument("--limit", type=int, default=16)
    parser.add_argument("--num-candidates", type=int, default=4)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-validation-like-input", action="store_true")
    parser.add_argument("--sync-output-dir")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        result = generate_candidates(
            sft_inputs=args.sft_input,
            output_root=args.output_root,
            run_id=args.run_id,
            base_model_path=args.base_model_path,
            adapter_path=args.adapter_path,
            limit=args.limit,
            num_candidates=args.num_candidates,
            max_new_tokens=args.max_new_tokens,
            temperature=args.temperature,
            top_p=args.top_p,
            seed=args.seed,
            device=args.device,
            dry_run=bool(args.dry_run),
            allow_validation_like_input=bool(args.allow_validation_like_input),
            sync_output_dir=args.sync_output_dir,
        )
    except Exception as exc:
        result = {
            "command": "generate_answer_policy_v3_candidates",
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
