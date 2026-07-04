from __future__ import annotations

import argparse
import importlib.metadata
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import write_jsonl
from scripts.run_answer_policy_v3_sft_warmup import (
    load_valid_records,
    safe_relpath,
    select_records,
    sha256_file,
    validation_path_markers,
)


SCRIPT_VERSION = "answer-policy-v3-msswift-sft-v1"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "training" / "answer_policy_v3_msswift_sft"


def repo_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def artifact_entry(path: Path) -> dict[str, Any]:
    return {"path": safe_relpath(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def to_swift_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "messages": record["messages"],
        "id": record.get("id", ""),
        "source": record.get("source", ""),
        "bucket": record.get("bucket", ""),
    }


def build_swift_command(
    *,
    swift_executable: str,
    model_path: str | Path,
    dataset_path: Path,
    output_dir: Path,
    max_steps: int,
    max_length: int,
    batch_size: int,
    gradient_accumulation_steps: int,
    learning_rate: float,
    tuner_type: str,
    torch_dtype: str,
    lora_rank: int,
    lora_alpha: int,
) -> list[str]:
    return [
        swift_executable,
        "sft",
        "--model",
        str(model_path),
        "--dataset",
        str(dataset_path),
        "--tuner_type",
        tuner_type,
        "--output_dir",
        str(output_dir),
        "--max_steps",
        str(max_steps),
        "--max_length",
        str(max_length),
        "--per_device_train_batch_size",
        str(batch_size),
        "--gradient_accumulation_steps",
        str(gradient_accumulation_steps),
        "--learning_rate",
        str(learning_rate),
        "--logging_steps",
        "1",
        "--save_steps",
        str(max(1, max_steps)),
        "--save_total_limit",
        "1",
        "--torch_dtype",
        torch_dtype,
        "--lora_rank",
        str(lora_rank),
        "--lora_alpha",
        str(lora_alpha),
    ]


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# AnswerPolicy v3 ms-swift SFT",
        "",
        f"- status: `{summary['status']}`",
        f"- run_id: `{summary['run_id']}`",
        f"- selected_record_count: `{summary['selected_record_count']}`",
        f"- execute: `{str(summary['execute']).lower()}`",
        f"- used_training: `{str(summary['used_training']).lower()}`",
        f"- validation_subset_used_for_training: `{str(summary['validation_subset_used_for_training']).lower()}`",
        f"- formal_benchmark_acceptance: `{str(summary['formal_benchmark_acceptance']).lower()}`",
    ]
    swift = summary.get("swift") or {}
    if swift:
        lines.extend(["", "## Swift"])
        for key in ("available", "executable", "ms_swift_version"):
            if key in swift:
                lines.append(f"- {key}: `{swift[key]}`")
    training = summary.get("training") or {}
    if training:
        lines.extend(["", "## Training"])
        for key in ("status", "returncode", "duration_seconds", "output_dir"):
            if key in training:
                lines.append(f"- {key}: `{training[key]}`")
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


def run_msswift_sft(
    *,
    sft_inputs: list[str | Path],
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    run_id: str = "answer_policy_v3_msswift_sft",
    base_model_path: str | Path = "/root/autodl-tmp/models/Qwen3-1.7B",
    max_records: int = 64,
    max_steps: int = 3,
    max_length: int = 2048,
    learning_rate: float = 1e-4,
    batch_size: int = 1,
    gradient_accumulation_steps: int = 4,
    tuner_type: str = "lora",
    torch_dtype: str = "bfloat16",
    lora_rank: int = 8,
    lora_alpha: int = 16,
    seed: int = 17,
    execute: bool = False,
    swift_executable: str | None = None,
    allow_validation_like_input: bool = False,
    sync_output_dir: str | Path | None = None,
) -> dict[str, Any]:
    artifact_dir = repo_path(output_root) / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    swift_train_path = artifact_dir / "swift_train.jsonl"
    swift_output_dir = artifact_dir / "swift_output"
    command_path = artifact_dir / "swift_command.json"
    stdout_path = artifact_dir / "swift.stdout.log"
    stderr_path = artifact_dir / "swift.stderr.log"
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
                block_reasons.append(f"validation_like_input_path:{','.join(markers)}")

    audit: dict[str, Any] = {}
    selected: list[dict[str, Any]] = []
    if not block_reasons:
        merged, audit = load_valid_records(input_paths)
        selected = select_records(merged, max_records=max_records, seed=seed)
        if not selected:
            block_reasons.append("no_valid_sft_records")

    swift_records = [to_swift_record(record) for record in selected]
    write_jsonl(swift_train_path, swift_records)
    write_json(preview_path, {"records": swift_records[:3]})

    swift_path = swift_executable or shutil.which("swift") or "swift"
    swift_available = bool(shutil.which(swift_path) or Path(swift_path).is_file())
    swift_info = {
        "available": swift_available,
        "executable": swift_path,
        "ms_swift_version": package_version("ms-swift"),
        "modelscope_version": package_version("modelscope"),
    }
    command = build_swift_command(
        swift_executable=swift_path,
        model_path=base_model_path,
        dataset_path=swift_train_path,
        output_dir=swift_output_dir,
        max_steps=max_steps,
        max_length=max_length,
        batch_size=batch_size,
        gradient_accumulation_steps=gradient_accumulation_steps,
        learning_rate=learning_rate,
        tuner_type=tuner_type,
        torch_dtype=torch_dtype,
        lora_rank=lora_rank,
        lora_alpha=lora_alpha,
    )
    write_json(command_path, {"command": command})

    training: dict[str, Any] = {"status": "skipped_not_executed"}
    used_training = False
    training_started = False
    status = "blocked" if block_reasons else "success"
    if execute and not swift_available:
        block_reasons.append("msswift_executable_not_found")
        status = "blocked"
        training = {"status": "blocked", "blocker": "msswift_executable_not_found"}
    elif execute and not block_reasons:
        started = time.time()
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        training_started = True
        with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open("w", encoding="utf-8") as stderr_handle:
            proc = subprocess.run(command, text=True, stdout=stdout_handle, stderr=stderr_handle, check=False)
        duration = round(time.time() - started, 3)
        training = {
            "status": "success" if proc.returncode == 0 else "failed",
            "returncode": proc.returncode,
            "duration_seconds": duration,
            "output_dir": safe_relpath(swift_output_dir),
            "stdout_path": safe_relpath(stdout_path),
            "stderr_path": safe_relpath(stderr_path),
        }
        used_training = proc.returncode == 0
        status = "success" if proc.returncode == 0 else "failed"
        if proc.returncode != 0:
            block_reasons.append("msswift_training_returncode_nonzero")

    summary = {
        "command": "run_answer_policy_v3_msswift_sft",
        "status": status,
        "script_version": SCRIPT_VERSION,
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "base_model_path": str(base_model_path),
        "sft_inputs": [safe_relpath(path) for path in input_paths],
        "selected_record_count": len(selected),
        "max_records": max_records,
        "max_steps": max_steps,
        "execute": execute,
        "audit": audit,
        "swift": swift_info,
        "training": training,
        "block_reasons": block_reasons,
        "used_training": used_training,
        "training_started": training_started,
        "used_qwen": used_training,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "swift_train_path": safe_relpath(swift_train_path),
        "swift_command_path": safe_relpath(command_path),
    }
    write_json(summary_path, summary)
    write_json(result_path, summary)
    write_summary_markdown(summary_md_path, summary)
    artifact_paths = [swift_train_path, command_path, preview_path, result_path, summary_path, summary_md_path]
    if stdout_path.is_file():
        artifact_paths.append(stdout_path)
    if stderr_path.is_file():
        artifact_paths.append(stderr_path)
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
        bundle = sync_bundle(artifact_dir, repo_path(sync_output_dir), run_id, [result_path, summary_path, summary_md_path, preview_path, command_path, manifest_path])
        summary["sync_bundle_path"] = safe_relpath(bundle)
    write_json(summary_path, summary)
    write_json(result_path, summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare or run an AnswerPolicy v3 ms-swift SFT smoke.")
    parser.add_argument("--sft-input", action="append", required=True)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id", default="answer_policy_v3_msswift_sft")
    parser.add_argument("--base-model-path", default="/root/autodl-tmp/models/Qwen3-1.7B")
    parser.add_argument("--max-records", type=int, default=64)
    parser.add_argument("--max-steps", type=int, default=3)
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=4)
    parser.add_argument("--tuner-type", default="lora")
    parser.add_argument("--torch-dtype", default="bfloat16")
    parser.add_argument("--lora-rank", type=int, default=8)
    parser.add_argument("--lora-alpha", type=int, default=16)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--execute", action="store_true", help="Actually invoke `swift sft`; omitted means artifact-only dry run.")
    parser.add_argument("--swift-executable")
    parser.add_argument("--allow-validation-like-input", action="store_true")
    parser.add_argument("--sync-output-dir")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        result = run_msswift_sft(
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
            tuner_type=args.tuner_type,
            torch_dtype=args.torch_dtype,
            lora_rank=args.lora_rank,
            lora_alpha=args.lora_alpha,
            seed=args.seed,
            execute=bool(args.execute),
            swift_executable=args.swift_executable,
            allow_validation_like_input=bool(args.allow_validation_like_input),
            sync_output_dir=args.sync_output_dir,
        )
    except Exception as exc:
        result = {
            "command": "run_answer_policy_v3_msswift_sft",
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
