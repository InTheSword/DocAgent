from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docagent.schemas import DocAgentSample, EvidenceBlock
from docagent.utils.jsonl import read_jsonl, write_jsonl
from docagent.workflow.prompts import compile_answer_prompt
from scripts.build_sft_dataset import build_assistant_target, normalize_answer, ordered_evidence_blocks, select_gold_block
from scripts.run_final_answer_policy_baseline import DEFAULT_TATQA_MANIFEST, DEFAULT_TATQA_SAMPLES


SCRIPT_VERSION = "answer-policy-sft-candidates-v1"
EVALUATION_SCOPE = "answer_policy_failure_sft_candidate_design_not_training"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "answer_policy_sft_candidates"


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
    return f"answer_policy_sft_candidates_{stamp}"


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_rows(run_dir: Path) -> tuple[list[dict[str, Any]], str, str]:
    results_path = run_dir / "results.jsonl"
    if results_path.is_file():
        return [row for row in read_jsonl(results_path) if isinstance(row, dict)], "full_results", safe_relpath(results_path)
    failures_path = run_dir / "failures_sample.jsonl"
    if failures_path.is_file():
        return [row for row in read_jsonl(failures_path) if isinstance(row, dict)], "failure_sample_only", safe_relpath(failures_path)
    return [], "summary_only", ""


def load_samples(path: Path) -> dict[str, DocAgentSample]:
    if not path.is_file():
        return {}
    return {
        sample.qid: sample
        for sample in (DocAgentSample.from_dict(row) for row in read_jsonl(path))
    }


def load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    return {str(row.get("sample_id") or row.get("qid") or ""): row for row in read_jsonl(path) if isinstance(row, dict)}


def should_build_candidate(row: dict[str, Any]) -> tuple[bool, str]:
    if str(row.get("dataset") or "") != "tatqa":
        return False, "non_tatqa_row"
    if row.get("pass_fail") != "failed":
        return False, "not_failed"
    if row.get("tool_executed") and row.get("tool_status") not in {"", "success"}:
        return False, "tool_execution_failed"
    if row.get("evaluation_mode") not in {"answer_policy_generation", "answer_policy_with_tool_results"}:
        return False, "not_answer_policy_generation"
    if row.get("answer_evaluated") is False and row.get("citation_evaluated") is False:
        return False, "not_evaluated"
    return True, ""


def order_evidence_for_row(sample: DocAgentSample, row: dict[str, Any], max_evidence_blocks: int) -> list[EvidenceBlock]:
    by_id = {block.block_id: block for block in sample.evidence}
    ordered_ids = [str(item) for item in row.get("selected_block_ids") or row.get("retrieved_block_ids") or []]
    ordered = [by_id[block_id] for block_id in ordered_ids if block_id in by_id]
    remaining = [block for block in sample.evidence if block.block_id not in {item.block_id for item in ordered}]
    if not ordered:
        ordered = ordered_evidence_blocks(sample, gold_first=True)
        remaining = []
    return [*ordered, *remaining][:max_evidence_blocks]


def tool_results_for_row(row: dict[str, Any]) -> list[dict[str, Any]]:
    compact = row.get("tool_results_compact")
    if isinstance(compact, list):
        return [item for item in compact if isinstance(item, dict)]
    if not row.get("tool_executed") or row.get("tool_status") != "success":
        return []
    citation_ids = [str(item) for item in row.get("tool_citation_block_ids") or [] if item]
    return [
        {
            key: value
            for key, value in {
                "status": row.get("tool_status"),
                "answer": row.get("tool_answer"),
                "citations": [{"block_id": block_id} for block_id in citation_ids],
                "warnings": row.get("tool_warnings") or [],
            }.items()
            if value not in (None, "", [], {})
        }
    ]


def build_candidate_record(
    *,
    sample: DocAgentSample,
    row: dict[str, Any],
    manifest: dict[str, Any],
    source_run_id: str,
    max_evidence_blocks: int,
    max_block_chars: int,
) -> dict[str, Any]:
    gold_block = select_gold_block(sample)
    gold_answer = normalize_answer(sample.answer)
    evidence_blocks = order_evidence_for_row(sample, row, max_evidence_blocks)
    tool_results = tool_results_for_row(row)
    bundle = compile_answer_prompt(
        question=sample.question,
        evidence_blocks=evidence_blocks,
        tool_results=tool_results,
        answer_type=sample.answer_type,
        append_no_think=False,
        max_chars_per_block=max_block_chars,
        answer=gold_answer,
        gold_block_id=gold_block.block_id if gold_block else None,
    )
    return {
        "id": f"{source_run_id}__{sample.qid}",
        "source": "answer_policy_baseline_sft_candidate",
        "messages": [
            *bundle.messages,
            {"role": "assistant", "content": json.dumps(build_assistant_target(sample), ensure_ascii=False)},
        ],
        "prompt_version": bundle.prompt_version,
        "evidence_context_hash": bundle.evidence_context["evidence_context_hash"],
        "metadata": {
            "source_run_id": source_run_id,
            "source_sample_id": sample.qid,
            "doc_id": sample.doc_id,
            "dataset": row.get("dataset") or sample.source,
            "evaluation_mode": row.get("evaluation_mode"),
            "failure_stage": row.get("failure_stage"),
            "failure_reasons": row.get("failure_reasons") or [],
            "prediction_answer": row.get("prediction_answer") or "",
            "expected_tools": row.get("expected_tools") or manifest.get("expected_tools") or [],
            "gold_block_ids": [block.block_id for block in [gold_block] if block is not None],
            "tool_results_attached": len(tool_results),
            "selected_block_ids": bundle.evidence_context["selected_block_ids"],
            "dropped_block_ids": bundle.evidence_context["dropped_block_ids"],
        },
    }


def blocked_result(
    *,
    run_id: str,
    artifact_dir: Path,
    source_run_id: str,
    source_run_dir: Path,
    reason: str,
    rows_scope: str,
    rows_path: str,
) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "command": "build_answer_policy_sft_candidates",
        "status": "blocked",
        "script_version": SCRIPT_VERSION,
        "evaluation_scope": EVALUATION_SCOPE,
        "quality_status": "diagnostic_only",
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "source_run_id": source_run_id,
        "source_run_dir": safe_relpath(source_run_dir),
        "rows_scope": rows_scope,
        "rows_path": rows_path,
        "record_count": 0,
        "block_reason": reason,
        "used_training": False,
        "formal_benchmark_acceptance": False,
    }
    return write_outputs(artifact_dir=artifact_dir, summary=summary, records=[])


def build_answer_policy_sft_candidates(
    *,
    baseline_run_dir: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
    tatqa_samples: Path = DEFAULT_TATQA_SAMPLES,
    tatqa_manifest: Path = DEFAULT_TATQA_MANIFEST,
    max_records: int | None = None,
    max_evidence_blocks: int = 5,
    max_block_chars: int = 1200,
) -> dict[str, Any]:
    baseline_run_dir = baseline_run_dir.resolve()
    summary = load_json(baseline_run_dir / "summary.json")
    result = load_json(baseline_run_dir / "result.json")
    rows, rows_scope, rows_path = load_rows(baseline_run_dir)
    source_run_id = str(summary.get("run_id") or result.get("run_id") or baseline_run_dir.name)
    run_id = run_id or f"sft_candidates_{source_run_id or now_run_id()}"
    artifact_dir = output_root / run_id

    if not summary and not result:
        return blocked_result(
            run_id=run_id,
            artifact_dir=artifact_dir,
            source_run_id=source_run_id,
            source_run_dir=baseline_run_dir,
            reason="missing_baseline_summary_or_result",
            rows_scope=rows_scope,
            rows_path=rows_path,
        )
    if str(summary.get("status") or result.get("status") or "") != "success":
        return blocked_result(
            run_id=run_id,
            artifact_dir=artifact_dir,
            source_run_id=source_run_id,
            source_run_dir=baseline_run_dir,
            reason="baseline_not_success",
            rows_scope=rows_scope,
            rows_path=rows_path,
        )
    if not bool(summary.get("used_qwen", result.get("used_qwen", False))):
        return blocked_result(
            run_id=run_id,
            artifact_dir=artifact_dir,
            source_run_id=source_run_id,
            source_run_dir=baseline_run_dir,
            reason="real_qwen_baseline_required",
            rows_scope=rows_scope,
            rows_path=rows_path,
        )

    samples = load_samples(tatqa_samples)
    manifest_by_id = load_manifest(tatqa_manifest)
    skip_reasons: Counter[str] = Counter()
    failure_reasons: Counter[str] = Counter()
    records: list[dict[str, Any]] = []
    for row in rows:
        keep, skip_reason = should_build_candidate(row)
        if not keep:
            skip_reasons[skip_reason] += 1
            continue
        sample_id = str(row.get("sample_id") or "")
        sample = samples.get(sample_id)
        if sample is None:
            skip_reasons["sample_not_found"] += 1
            continue
        records.append(
            build_candidate_record(
                sample=sample,
                row=row,
                manifest=manifest_by_id.get(sample_id, {}),
                source_run_id=source_run_id,
                max_evidence_blocks=max_evidence_blocks,
                max_block_chars=max_block_chars,
            )
        )
        failure_reasons.update(str(reason) for reason in row.get("failure_reasons") or [])
        if max_records is not None and len(records) >= max_records:
            break

    summary_payload = {
        "command": "build_answer_policy_sft_candidates",
        "status": "success",
        "script_version": SCRIPT_VERSION,
        "evaluation_scope": EVALUATION_SCOPE,
        "quality_status": "diagnostic_only",
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "source_run_id": source_run_id,
        "source_run_dir": safe_relpath(baseline_run_dir),
        "rows_scope": rows_scope,
        "rows_path": rows_path,
        "record_count": len(records),
        "rows_read_count": len(rows),
        "skip_reason_distribution": dict(sorted(skip_reasons.items())),
        "candidate_failure_reason_distribution": dict(sorted(failure_reasons.items())),
        "tatqa_samples_path": safe_relpath(tatqa_samples),
        "tatqa_manifest_path": safe_relpath(tatqa_manifest),
        "max_evidence_blocks": max_evidence_blocks,
        "max_block_chars": max_block_chars,
        "used_training": False,
        "formal_benchmark_acceptance": False,
    }
    return write_outputs(artifact_dir=artifact_dir, summary=summary_payload, records=records)


def write_outputs(*, artifact_dir: Path, summary: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "result": artifact_dir / "result.json",
        "records": artifact_dir / "sft_candidates.jsonl",
        "summary": artifact_dir / "summary.json",
        "summary_md": artifact_dir / "summary.md",
        "preview": artifact_dir / "preview.json",
        "manifest": artifact_dir / "manifest.json",
    }
    summary.update(
        {
            "records_path": safe_relpath(paths["records"]),
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
        "record_count": summary["record_count"],
        "used_training": False,
        "formal_benchmark_acceptance": False,
        "artifact_paths": [safe_relpath(path) for path in paths.values()],
    }
    write_jsonl(paths["records"], records)
    write_json(paths["summary"], summary)
    write_summary_markdown(paths["summary_md"], summary)
    write_json(paths["preview"], {"summary": summary, "records": records[:5]})
    write_json(paths["result"], result)
    write_manifest(paths["manifest"], summary=summary, artifact_paths=list(paths.values()))
    return {**result, **summary, "artifact_paths": [safe_relpath(path) for path in paths.values()]}


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# AnswerPolicy SFT Candidate Data",
        "",
        f"- status: `{summary.get('status')}`",
        f"- quality_status: `{summary.get('quality_status')}`",
        f"- source_run_id: `{summary.get('source_run_id')}`",
        f"- rows_scope: `{summary.get('rows_scope')}`",
        f"- record_count: {summary.get('record_count')}",
        f"- used_training: `{str(summary.get('used_training')).lower()}`",
        f"- formal_benchmark_acceptance: `{str(summary.get('formal_benchmark_acceptance')).lower()}`",
    ]
    if summary.get("block_reason"):
        lines.append(f"- block_reason: `{summary.get('block_reason')}`")
    lines.extend(["", "## Candidate Failure Reasons", ""])
    lines.extend(markdown_distribution(summary.get("candidate_failure_reason_distribution") or {}))
    lines.extend(["", "## Skipped Rows", ""])
    lines.extend(markdown_distribution(summary.get("skip_reason_distribution") or {}))
    lines.extend(["", "This artifact is candidate SFT data design only. It does not start training or claim model quality."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def markdown_distribution(distribution: dict[str, Any]) -> list[str]:
    if not distribution:
        return ["- none"]
    return [f"- {key}: {value}" for key, value in sorted(distribution.items())]


def write_manifest(path: Path, *, summary: dict[str, Any], artifact_paths: list[Path]) -> None:
    payload = {
        "run_id": summary.get("run_id"),
        "script_version": SCRIPT_VERSION,
        "artifact_dir": summary.get("artifact_dir"),
        "source_run_id": summary.get("source_run_id"),
        "record_count": summary.get("record_count"),
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build diagnostic SFT candidate records from AnswerPolicy baseline failures.")
    parser.add_argument("--baseline-run-dir", required=True)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id")
    parser.add_argument("--tatqa-samples", default=str(DEFAULT_TATQA_SAMPLES))
    parser.add_argument("--tatqa-manifest", default=str(DEFAULT_TATQA_MANIFEST))
    parser.add_argument("--max-records", type=int)
    parser.add_argument("--max-evidence-blocks", type=int, default=5)
    parser.add_argument("--max-block-chars", type=int, default=1200)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = build_answer_policy_sft_candidates(
        baseline_run_dir=repo_path(args.baseline_run_dir) or Path(args.baseline_run_dir),
        output_root=repo_path(args.output_dir) or DEFAULT_OUTPUT_ROOT,
        run_id=args.run_id,
        tatqa_samples=repo_path(args.tatqa_samples) or DEFAULT_TATQA_SAMPLES,
        tatqa_manifest=repo_path(args.tatqa_manifest) or DEFAULT_TATQA_MANIFEST,
        max_records=args.max_records,
        max_evidence_blocks=args.max_evidence_blocks,
        max_block_chars=args.max_block_chars,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
