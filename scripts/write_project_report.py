from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def compact_audit(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "num_records": report.get("num_records"),
        "clean_records": report.get("clean_records"),
        "clean_rate": report.get("clean_rate"),
        "issue_counts": report.get("issue_counts", {}),
        "by_answer_type": report.get("by_answer_type", {}),
    }


def compact_retrieval(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "input": report.get("input"),
        "num_samples": report.get("num_samples"),
        "num_blocks": report.get("num_blocks"),
        "top_k": report.get("top_k"),
        "candidate_scope": report.get("candidate_scope"),
        "recall_at_k": report.get("recall_at_k"),
        "mrr_at_k": report.get("mrr_at_k"),
        "num_misses": report.get("num_misses"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="reports/docagent_project_report.json")
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()

    root = Path(args.repo_root)
    report = {
        "data_quality": {
            "mp_docvqa_train_sft_clean": compact_audit(
                load_json(root / "outputs/eval/mp_docvqa_train_sft_clean_audit.json")
            ),
            "mp_docvqa_dev_sft_clean": compact_audit(
                load_json(root / "outputs/eval/mp_docvqa_dev_sft_clean_audit.json")
            ),
            "mp_docvqa_train_grpo": compact_audit(load_json(root / "outputs/eval/mp_docvqa_train_grpo_audit.json")),
        },
        "retrieval": {
            "mp_docvqa_dev_same_doc_bm25": compact_retrieval(
                load_json(root / "outputs/eval/mp_docvqa_dev_retrieval_same_doc.json")
            ),
            "mp_docvqa_test_same_doc_bm25": compact_retrieval(
                load_json(root / "outputs/eval/mp_docvqa_test_retrieval_same_doc.json")
            ),
        },
    }

    output = root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "sections": list(report)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
