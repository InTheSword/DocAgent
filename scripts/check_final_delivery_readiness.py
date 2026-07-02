from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.workflow.answer_contract import citation_from_block, evidence_used_from_blocks
from scripts import docagent_cli


REQUIRED_FILES = (
    "README.md",
    "AGENTS.md",
    "CURRENT_STATUS.md",
    "docs/ACTIVE_PLAN.md",
    "docs/FINAL_DELIVERY_CLI.md",
    "docs/FINAL_DELIVERY_REPORT.md",
    "docs/SERVER_SETUP.md",
    "docs/DATASETS.md",
    "scripts/docagent_cli.py",
    "scripts/run_final_raw_pdf_smoke.py",
    "scripts/prepare_mpdocvqa_evidence.py",
    "scripts/run_mpdocvqa_full_workflow_diagnostic.py",
)
REMOVED_FILES = ("docs/PROJECT_HANDOFF_PM.md",)
REQUIRED_OUTPUT_FIELDS = (
    "answer",
    "reasoning_summary",
    "evidence_used",
    "citations",
    "tools_used",
    "trace_path",
)
REQUIRED_CLI_OPTIONS = (
    "--file",
    "--doc-id",
    "--question",
    "--parser",
    "--live-api",
    "--mineru-env-file",
    "--retriever-mode",
    "--full-model-path",
    "--answer-policy",
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    failures: list[str]
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "failures": self.failures,
            "details": self.details,
        }


def _now_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"final_delivery_readiness_{stamp}_{uuid.uuid4().hex[:8]}"


def _json_default(value: Any) -> str:
    return str(value)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def _read_text(root: Path, relative_path: str) -> str:
    return (root / relative_path).read_text(encoding="utf-8")


def _check_files(root: Path) -> CheckResult:
    missing = [path for path in REQUIRED_FILES if not (root / path).is_file()]
    present_removed = [path for path in REMOVED_FILES if (root / path).exists()]
    failures = [f"missing_required_file:{path}" for path in missing]
    failures.extend(f"deprecated_file_present:{path}" for path in present_removed)
    return CheckResult(
        name="required_files",
        status="passed" if not failures else "failed",
        failures=failures,
        details={
            "required_file_count": len(REQUIRED_FILES),
            "missing": missing,
            "deprecated_present": present_removed,
        },
    )


def _check_cli_parser() -> CheckResult:
    parser = docagent_cli.build_parser()
    option_actions: dict[str, argparse.Action] = {}
    for action in parser._actions:
        for option in action.option_strings:
            option_actions[option] = action

    missing = [option for option in REQUIRED_CLI_OPTIONS if option not in option_actions]
    failures = [f"missing_cli_option:{option}" for option in missing]

    parser_choices = set(option_actions.get("--parser").choices or []) if "--parser" in option_actions else set()
    retriever_choices = set(option_actions.get("--retriever-mode").choices or []) if "--retriever-mode" in option_actions else set()
    answer_policy_choices = set(option_actions.get("--answer-policy").choices or []) if "--answer-policy" in option_actions else set()
    for choice in ("mineru_existing", "mineru_api"):
        if choice not in parser_choices:
            failures.append(f"missing_parser_choice:{choice}")
    if "hybrid_rerank" not in retriever_choices:
        failures.append("missing_retriever_choice:hybrid_rerank")
    for choice in ("heuristic", "base", "sft", "grpo"):
        if choice not in answer_policy_choices:
            failures.append(f"missing_answer_policy_choice:{choice}")

    return CheckResult(
        name="cli_parser",
        status="passed" if not failures else "failed",
        failures=failures,
        details={
            "required_options": list(REQUIRED_CLI_OPTIONS),
            "parser_choices": sorted(parser_choices),
            "retriever_choices": sorted(retriever_choices),
            "answer_policy_choices": sorted(answer_policy_choices),
        },
    )


def _check_cli_output_contract() -> CheckResult:
    payload = docagent_cli._base_result(mode="qa", run_id="readiness", doc_id="doc1")
    missing = [field for field in REQUIRED_OUTPUT_FIELDS if field not in payload]
    wrong_types: list[str] = []
    for field in ("evidence_used", "citations", "tools_used"):
        if field in payload and not isinstance(payload[field], list):
            wrong_types.append(field)
    for field in ("answer", "reasoning_summary", "trace_path"):
        if field in payload and not isinstance(payload[field], str):
            wrong_types.append(field)
    failures = [f"missing_output_field:{field}" for field in missing]
    failures.extend(f"wrong_output_field_type:{field}" for field in wrong_types)
    return CheckResult(
        name="cli_output_contract",
        status="passed" if not failures else "failed",
        failures=failures,
        details={"required_output_fields": list(REQUIRED_OUTPUT_FIELDS)},
    )


def _sample_evidence_blocks() -> list[EvidenceBlock]:
    return [
        EvidenceBlock(
            doc_id="doc1",
            block_id="text1",
            block_type="text",
            text="The budget estimate is $100,000.",
            page_id=1,
            location=EvidenceLocation(page=1, block_id="text1"),
        ),
        EvidenceBlock(
            doc_id="doc1",
            block_id="table1",
            block_type="table",
            table_html="<table><tr><td>Budget Estimate</td><td>$100,000</td></tr></table>",
            page_id=2,
            image_path="mineru/tables/table1.jpg",
            location=EvidenceLocation(page=2, block_id="table1", table_id="t1"),
            metadata={"table_caption": ["Budget estimate table"]},
        ),
        EvidenceBlock(
            doc_id="doc1",
            block_id="image1",
            block_type="image",
            visual_summary="Revenue chart.",
            page_id=3,
            image_path="mineru/images/image1.jpg",
            location=EvidenceLocation(page=3, block_id="image1", image_id="i1"),
            metadata={"image_caption": "Revenue chart", "nearby_text": ["FY2020 revenue was $100,000"]},
        ),
    ]


def _check_citation_evidence_contract() -> CheckResult:
    blocks = _sample_evidence_blocks()
    citations = [citation_from_block(block) for block in blocks]
    evidence_used = evidence_used_from_blocks(blocks)
    required_fields = ("doc_id", "page", "block_id", "block_type", "text_preview")
    failures: list[str] = []
    for collection_name, records in (("citations", citations), ("evidence_used", evidence_used)):
        by_id = {str(record.get("block_id") or ""): record for record in records}
        for block in blocks:
            record = by_id.get(block.block_id)
            if record is None:
                failures.append(f"{collection_name}_missing_block:{block.block_id}")
                continue
            for field in required_fields:
                if record.get(field) in {None, ""}:
                    failures.append(f"{collection_name}_missing_field:{block.block_id}:{field}")
            if block.block_type == "table":
                for field in ("table_caption", "image_path"):
                    if record.get(field) in {None, ""}:
                        failures.append(f"{collection_name}_missing_field:{block.block_id}:{field}")
            if block.block_type == "image":
                for field in ("image_caption", "nearby_text", "image_path"):
                    if record.get(field) in {None, ""}:
                        failures.append(f"{collection_name}_missing_field:{block.block_id}:{field}")
    return CheckResult(
        name="citation_evidence_contract",
        status="passed" if not failures else "failed",
        failures=failures,
        details={
            "sample_block_types": [block.block_type for block in blocks],
            "required_location_fields": list(required_fields),
        },
    )


def _check_documentation(root: Path) -> CheckResult:
    snippets = {
        "README.md": [
            "docs/FINAL_DELIVERY_CLI.md",
            "docs/FINAL_DELIVERY_REPORT.md",
            '"answer"',
            '"reasoning_summary"',
            '"evidence_used"',
            '"citations"',
            '"tools_used"',
            '"trace_path"',
            "raw PDF MinerU API ingestion",
        ],
        "docs/FINAL_DELIVERY_CLI.md": [
            "CLI-only delivery surface",
            "MinerU API ingestion",
            "*_content_list_v2.json",
            "table HTML",
            "image metadata",
            "no pixel-level VLM interpretation",
            "accepted MP-DocVQA/TAT-QA final answer benchmark",
            "new SFT/GRPO training",
        ],
        "docs/FINAL_DELIVERY_REPORT.md": [
            "Final answer quality benchmark",
            "not_started",
            "validation subsets are used for diagnostics only",
            "used as training data",
            "real_model_verified",
            "accepted",
        ],
        "AGENTS.md": [
            "keep work anchored to the current delivery and functional goal",
            "make case-specific repairs",
            "use validation subsets as training data",
        ],
        "docs/SERVER_SETUP.md": [
            "preserve the interactive terminal",
            "Do not use `set -e`, shell `exit`",
        ],
    }
    failures: list[str] = []
    checked: dict[str, int] = {}
    for relative_path, required_snippets in snippets.items():
        try:
            text = _read_text(root, relative_path)
        except OSError:
            failures.append(f"documentation_file_unreadable:{relative_path}")
            continue
        checked[relative_path] = len(required_snippets)
        for snippet in required_snippets:
            if snippet not in text:
                failures.append(f"documentation_snippet_missing:{relative_path}:{snippet}")
    return CheckResult(
        name="documentation_contract",
        status="passed" if not failures else "failed",
        failures=failures,
        details={"checked_snippet_counts": checked},
    )


def run_readiness_check(*, root: Path = ROOT, output_dir: Path | None = None, run_id: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    run_id = run_id or _now_run_id()
    artifact_dir = (output_dir or (root / "outputs" / "final_delivery_readiness")) / run_id
    checks = [
        _check_files(root),
        _check_cli_parser(),
        _check_cli_output_contract(),
        _check_citation_evidence_contract(),
        _check_documentation(root),
    ]
    failures = [failure for check in checks for failure in check.failures]
    status = "success" if not failures else "failed"
    summary: dict[str, Any] = {
        "command": "check_final_delivery_readiness",
        "status": status,
        "quality_status": "readiness_check_only",
        "run_id": run_id,
        "artifact_dir": artifact_dir.as_posix(),
        "check_count": len(checks),
        "passed_check_count": sum(1 for check in checks if check.status == "passed"),
        "failed_check_count": sum(1 for check in checks if check.status != "passed"),
        "failures": failures,
        "checks": [check.to_dict() for check in checks],
        "used_qwen": False,
        "used_vlm": False,
        "used_training": False,
        "used_online_mineru_ocr": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
    }
    summary_path = artifact_dir / "summary.json"
    result_path = artifact_dir / "result.json"
    manifest_path = artifact_dir / "manifest.json"
    _write_json(summary_path, summary)
    _write_json(result_path, summary)
    _write_json(
        manifest_path,
        {
            "run_id": run_id,
            "summary_path": summary_path.as_posix(),
            "result_path": result_path.as_posix(),
            "formal_benchmark_acceptance": False,
        },
    )
    summary["artifact_paths"] = [result_path.as_posix(), summary_path.as_posix(), manifest_path.as_posix()]
    _write_json(summary_path, summary)
    _write_json(result_path, summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check local final-delivery CLI/readiness contract without models or datasets.")
    parser.add_argument("--run-id")
    parser.add_argument("--output-dir", default=str(ROOT / "outputs" / "final_delivery_readiness"))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = run_readiness_check(output_dir=Path(args.output_dir), run_id=args.run_id)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
