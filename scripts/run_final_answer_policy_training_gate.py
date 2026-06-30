from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docagent.models.base import AnswerPolicy
from scripts.build_answer_policy_sft_candidates import (
    DEFAULT_OUTPUT_ROOT as DEFAULT_SFT_CANDIDATE_OUTPUT_ROOT,
    build_answer_policy_sft_candidates,
)
from scripts.review_answer_policy_baseline import (
    DEFAULT_OUTPUT_ROOT as DEFAULT_REVIEW_OUTPUT_ROOT,
    review_answer_policy_baseline,
)
from scripts.run_final_answer_policy_baseline import (
    DEFAULT_MPDOCVQA_DB_PATH,
    DEFAULT_MPDOCVQA_EVIDENCE_MANIFEST,
    DEFAULT_MPDOCVQA_MANIFEST,
    DEFAULT_OUTPUT_ROOT as DEFAULT_BASELINE_OUTPUT_ROOT,
    DEFAULT_QWEN_BASE_MODEL_PATH,
    DEFAULT_TATQA_MANIFEST,
    DEFAULT_TATQA_SAMPLES,
    run_final_answer_policy_baseline,
)


SCRIPT_VERSION = "final-answer-policy-training-gate-v1"
EVALUATION_SCOPE = "answer_policy_baseline_review_sft_candidate_orchestration"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "answer_policy_training_gate"


def repo_path(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def safe_relpath(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def now_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"answer_policy_training_gate_{stamp}"


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compact_baseline(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": result.get("status"),
        "run_id": result.get("run_id"),
        "artifact_dir": result.get("artifact_dir"),
        "answer_policy_mode": result.get("answer_policy_mode"),
        "used_qwen": result.get("used_qwen"),
        "case_count": result.get("case_count"),
        "evaluated_count": result.get("evaluated_count"),
        "pass_rate": result.get("pass_rate"),
        "format_valid_rate": result.get("format_valid_rate"),
        "answer_hit_rate": result.get("answer_hit_rate"),
        "citation_block_hit_rate": result.get("citation_block_hit_rate"),
        "citation_page_hit_rate": result.get("citation_page_hit_rate"),
        "failure_reason_distribution": result.get("failure_reason_distribution") or {},
    }


def compact_review(result: dict[str, Any]) -> dict[str, Any]:
    gate = result.get("training_gate") if isinstance(result.get("training_gate"), dict) else {}
    return {
        "status": result.get("status"),
        "run_id": result.get("run_id"),
        "artifact_dir": result.get("artifact_dir"),
        "sample_scope": result.get("sample_scope"),
        "recommendation": gate.get("recommendation"),
        "sft_gate": gate.get("sft_gate"),
        "grpo_gate": gate.get("grpo_gate"),
        "next_action": gate.get("next_action"),
        "reasons": gate.get("reasons") or [],
    }


def compact_candidates(result: dict[str, Any] | None, *, skipped_reason: str = "") -> dict[str, Any]:
    if result is None:
        return {"status": "skipped", "skip_reason": skipped_reason, "record_count": 0}
    return {
        "status": result.get("status"),
        "run_id": result.get("run_id"),
        "artifact_dir": result.get("artifact_dir"),
        "record_count": result.get("record_count"),
        "block_reason": result.get("block_reason", ""),
        "records_path": result.get("records_path", ""),
    }


def overall_status(baseline: dict[str, Any], review: dict[str, Any], candidates: dict[str, Any] | None) -> str:
    if baseline.get("status") != "success":
        return "blocked"
    if review.get("status") != "success":
        return "blocked"
    if candidates is not None and candidates.get("status") not in {"success", None}:
        return "blocked"
    return "success"


def run_final_answer_policy_training_gate(
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
    baseline_output_root: Path = DEFAULT_BASELINE_OUTPUT_ROOT,
    review_output_root: Path = DEFAULT_REVIEW_OUTPUT_ROOT,
    sft_candidate_output_root: Path = DEFAULT_SFT_CANDIDATE_OUTPUT_ROOT,
    tatqa_samples: Path | None = DEFAULT_TATQA_SAMPLES,
    tatqa_manifest: Path | None = DEFAULT_TATQA_MANIFEST,
    mpdocvqa_manifest: Path | None = DEFAULT_MPDOCVQA_MANIFEST,
    mpdocvqa_evidence_manifest: Path | None = DEFAULT_MPDOCVQA_EVIDENCE_MANIFEST,
    mpdocvqa_db_path: Path | None = DEFAULT_MPDOCVQA_DB_PATH,
    max_samples: int | None = None,
    answer_policy_mode: str = "base",
    base_model_path: str = DEFAULT_QWEN_BASE_MODEL_PATH,
    adapter_path: str | None = None,
    device: str = "cuda",
    torch_dtype: str = "bfloat16",
    max_prompt_tokens: int | None = 4096,
    max_new_tokens: int = 1024,
    top_k: int = 5,
    preserve_input_order: bool = False,
    answer_policy: AnswerPolicy | None = None,
    max_sft_records: int | None = None,
    max_evidence_blocks: int = 5,
    max_block_chars: int = 1200,
    sync_output_root: Path | None = None,
) -> dict[str, Any]:
    run_id = run_id or now_run_id()
    artifact_dir = output_root / run_id
    baseline_run_id = f"{run_id}_baseline"
    review_run_id = f"{run_id}_review"
    sft_candidate_run_id = f"{run_id}_sft_candidates"

    baseline = run_final_answer_policy_baseline(
        output_root=baseline_output_root,
        run_id=baseline_run_id,
        tatqa_samples=tatqa_samples,
        tatqa_manifest=tatqa_manifest,
        mpdocvqa_manifest=mpdocvqa_manifest,
        mpdocvqa_evidence_manifest=mpdocvqa_evidence_manifest,
        mpdocvqa_db_path=mpdocvqa_db_path,
        max_samples=max_samples,
        answer_policy_mode=answer_policy_mode,
        base_model_path=base_model_path,
        adapter_path=adapter_path,
        device=device,
        torch_dtype=torch_dtype,
        max_prompt_tokens=max_prompt_tokens,
        max_new_tokens=max_new_tokens,
        top_k=top_k,
        preserve_input_order=preserve_input_order,
        answer_policy=answer_policy,
    )
    baseline_run_dir = baseline_output_root / baseline_run_id
    review = review_answer_policy_baseline(
        run_dir=baseline_run_dir,
        output_root=review_output_root,
        run_id=review_run_id,
    )
    gate = review.get("training_gate") if isinstance(review.get("training_gate"), dict) else {}
    recommendation = str(gate.get("recommendation") or "")
    candidates: dict[str, Any] | None = None
    candidate_skip_reason = recommendation or "review_gate_missing"
    if baseline.get("status") == "success" and review.get("status") == "success" and recommendation == "sft_data_design_candidate":
        candidates = build_answer_policy_sft_candidates(
            baseline_run_dir=baseline_run_dir,
            output_root=sft_candidate_output_root,
            run_id=sft_candidate_run_id,
            tatqa_samples=tatqa_samples or DEFAULT_TATQA_SAMPLES,
            tatqa_manifest=tatqa_manifest or DEFAULT_TATQA_MANIFEST,
            max_records=max_sft_records,
            max_evidence_blocks=max_evidence_blocks,
            max_block_chars=max_block_chars,
        )
        candidate_skip_reason = ""

    summary = {
        "command": "run_final_answer_policy_training_gate",
        "status": overall_status(baseline, review, candidates),
        "script_version": SCRIPT_VERSION,
        "evaluation_scope": EVALUATION_SCOPE,
        "quality_status": "diagnostic_only",
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "baseline": compact_baseline(baseline),
        "review": compact_review(review),
        "sft_candidates": compact_candidates(candidates, skipped_reason=candidate_skip_reason),
        "used_qwen": bool(baseline.get("used_qwen", False)),
        "used_training": False,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "real_qwen_acceptance": False,
        "next_action": gate.get("next_action") or "",
    }
    result = write_outputs(artifact_dir=artifact_dir, summary=summary)
    if sync_output_root is not None:
        sync_dir, sync_paths = create_sync_bundle(
            sync_root=sync_output_root,
            run_id=run_id,
            summary_paths=[artifact_dir / "result.json", artifact_dir / "summary.json", artifact_dir / "summary.md", artifact_dir / "preview.json"],
            nested_paths=nested_sync_paths(baseline, review, candidates),
        )
        result["sync_bundle_path"] = safe_relpath(sync_dir)
        result["sync_artifact_paths"] = [safe_relpath(path) for path in sync_paths]
    return result


def nested_sync_paths(
    baseline: dict[str, Any],
    review: dict[str, Any],
    candidates: dict[str, Any] | None,
) -> list[tuple[str, Path]]:
    paths: list[tuple[str, Path]] = []
    for prefix, payload in [("baseline", baseline), ("review", review), ("sft_candidates", candidates or {})]:
        artifact_dir = payload.get("artifact_dir")
        if not artifact_dir:
            continue
        root = repo_path(str(artifact_dir))
        if root is None:
            continue
        for name in ("result.json", "summary.json", "summary.md", "review.json", "review.md", "preview.json"):
            source = root / name
            if source.is_file():
                target_name = name if prefix == "review" and name.startswith("review.") else f"{prefix}_{name}"
                paths.append((target_name, source))
    return paths


def write_outputs(*, artifact_dir: Path, summary: dict[str, Any]) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "result": artifact_dir / "result.json",
        "summary": artifact_dir / "summary.json",
        "summary_md": artifact_dir / "summary.md",
        "preview": artifact_dir / "preview.json",
        "manifest": artifact_dir / "manifest.json",
    }
    summary.update(
        {
            "result_path": safe_relpath(paths["result"]),
            "summary_path": safe_relpath(paths["summary"]),
            "summary_markdown_path": safe_relpath(paths["summary_md"]),
            "preview_path": safe_relpath(paths["preview"]),
            "manifest_path": safe_relpath(paths["manifest"]),
        }
    )
    result = {
        "command": summary["command"],
        "status": summary["status"],
        "run_id": summary["run_id"],
        "artifact_dir": summary["artifact_dir"],
        "quality_status": summary["quality_status"],
        "used_qwen": summary["used_qwen"],
        "used_training": False,
        "formal_benchmark_acceptance": False,
        "baseline": summary["baseline"],
        "review": summary["review"],
        "sft_candidates": summary["sft_candidates"],
        "artifact_paths": [safe_relpath(path) for path in paths.values()],
    }
    write_json(paths["summary"], summary)
    write_summary_markdown(paths["summary_md"], summary)
    write_json(paths["preview"], {"summary": summary})
    write_json(paths["result"], result)
    write_manifest(paths["manifest"], run_id=str(summary["run_id"]), artifact_paths=list(paths.values()))
    return {**result, **summary, "artifact_paths": [safe_relpath(path) for path in paths.values()]}


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    baseline = summary.get("baseline") or {}
    review = summary.get("review") or {}
    candidates = summary.get("sft_candidates") or {}
    lines = [
        "# Final AnswerPolicy Training Gate",
        "",
        f"- status: `{summary.get('status')}`",
        f"- quality_status: `{summary.get('quality_status')}`",
        f"- used_qwen: `{str(summary.get('used_qwen')).lower()}`",
        f"- used_training: `{str(summary.get('used_training')).lower()}`",
        f"- formal_benchmark_acceptance: `{str(summary.get('formal_benchmark_acceptance')).lower()}`",
        "",
        "## Baseline",
        "",
        f"- status: `{baseline.get('status')}`",
        f"- answer_policy_mode: `{baseline.get('answer_policy_mode')}`",
        f"- evaluated_count: {baseline.get('evaluated_count')}",
        f"- answer_hit_rate: {baseline.get('answer_hit_rate')}",
        f"- citation_block_hit_rate: {baseline.get('citation_block_hit_rate')}",
        "",
        "## Review",
        "",
        f"- recommendation: `{review.get('recommendation')}`",
        f"- sft_gate: `{review.get('sft_gate')}`",
        f"- grpo_gate: `{review.get('grpo_gate')}`",
        f"- next_action: `{review.get('next_action')}`",
        "",
        "## SFT Candidates",
        "",
        f"- status: `{candidates.get('status')}`",
        f"- record_count: {candidates.get('record_count')}",
        f"- skip_reason: `{candidates.get('skip_reason', '')}`",
        "",
        "This orchestration is diagnostic only. It does not start SFT, start GRPO, or mark benchmark acceptance.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_manifest(path: Path, *, run_id: str, artifact_paths: list[Path]) -> None:
    payload = {
        "run_id": run_id,
        "script_version": SCRIPT_VERSION,
        "files": [
            {
                "path": safe_relpath(item),
                "byte_size": item.stat().st_size,
                "sha256": sha256_file(item),
            }
            for item in artifact_paths
            if item.is_file() and item != path
        ],
    }
    write_json(path, payload)


def create_sync_bundle(
    *,
    sync_root: Path,
    run_id: str,
    summary_paths: list[Path],
    nested_paths: list[tuple[str, Path]],
) -> tuple[Path, list[Path]]:
    sync_dir = sync_root / run_id
    sync_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for source in summary_paths:
        if not source.is_file():
            continue
        target = sync_dir / source.name
        target.write_bytes(source.read_bytes())
        copied.append(target)
    for target_name, source in nested_paths:
        if not source.is_file():
            continue
        target = sync_dir / target_name
        target.write_bytes(source.read_bytes())
        copied.append(target)
    write_manifest(sync_dir / "manifest.json", run_id=run_id, artifact_paths=copied)
    copied.append(sync_dir / "manifest.json")
    return sync_dir, copied


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run AnswerPolicy baseline, review it, and optionally build SFT candidate records.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id")
    parser.add_argument("--baseline-output-dir", default=str(DEFAULT_BASELINE_OUTPUT_ROOT))
    parser.add_argument("--review-output-dir", default=str(DEFAULT_REVIEW_OUTPUT_ROOT))
    parser.add_argument("--sft-candidate-output-dir", default=str(DEFAULT_SFT_CANDIDATE_OUTPUT_ROOT))
    parser.add_argument("--tatqa-samples", default=str(DEFAULT_TATQA_SAMPLES))
    parser.add_argument("--tatqa-manifest", default=str(DEFAULT_TATQA_MANIFEST))
    parser.add_argument("--mpdocvqa-manifest", default=str(DEFAULT_MPDOCVQA_MANIFEST))
    parser.add_argument("--mpdocvqa-evidence-manifest", default=str(DEFAULT_MPDOCVQA_EVIDENCE_MANIFEST))
    parser.add_argument("--mpdocvqa-db-path", default=str(DEFAULT_MPDOCVQA_DB_PATH))
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--answer-policy", choices=["heuristic", "base", "sft", "grpo"], default="base")
    parser.add_argument("--base-model-path", default=DEFAULT_QWEN_BASE_MODEL_PATH)
    parser.add_argument("--adapter-path")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--torch-dtype", default="bfloat16")
    parser.add_argument("--max-prompt-tokens", type=int, default=4096)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--preserve-input-order", action="store_true")
    parser.add_argument("--max-sft-records", type=int)
    parser.add_argument("--max-evidence-blocks", type=int, default=5)
    parser.add_argument("--max-block-chars", type=int, default=1200)
    parser.add_argument("--sync-output-dir")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_final_answer_policy_training_gate(
        output_root=repo_path(args.output_dir) or DEFAULT_OUTPUT_ROOT,
        run_id=args.run_id,
        baseline_output_root=repo_path(args.baseline_output_dir) or DEFAULT_BASELINE_OUTPUT_ROOT,
        review_output_root=repo_path(args.review_output_dir) or DEFAULT_REVIEW_OUTPUT_ROOT,
        sft_candidate_output_root=repo_path(args.sft_candidate_output_dir) or DEFAULT_SFT_CANDIDATE_OUTPUT_ROOT,
        tatqa_samples=repo_path(args.tatqa_samples),
        tatqa_manifest=repo_path(args.tatqa_manifest),
        mpdocvqa_manifest=repo_path(args.mpdocvqa_manifest),
        mpdocvqa_evidence_manifest=repo_path(args.mpdocvqa_evidence_manifest),
        mpdocvqa_db_path=repo_path(args.mpdocvqa_db_path),
        max_samples=args.max_samples,
        answer_policy_mode=str(args.answer_policy),
        base_model_path=str(args.base_model_path),
        adapter_path=str(args.adapter_path) if args.adapter_path else None,
        device=str(args.device),
        torch_dtype=str(args.torch_dtype),
        max_prompt_tokens=args.max_prompt_tokens,
        max_new_tokens=int(args.max_new_tokens),
        top_k=int(args.top_k),
        preserve_input_order=bool(args.preserve_input_order),
        max_sft_records=args.max_sft_records,
        max_evidence_blocks=int(args.max_evidence_blocks),
        max_block_chars=int(args.max_block_chars),
        sync_output_root=repo_path(args.sync_output_dir),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
