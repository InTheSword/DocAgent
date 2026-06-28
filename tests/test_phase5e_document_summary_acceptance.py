from __future__ import annotations

import json
from pathlib import Path

from scripts.run_phase5e_document_summary_acceptance import BOUNDARY, run_acceptance


def test_phase5e_acceptance_runner_writes_report(tmp_path: Path) -> None:
    output_dir = tmp_path / "acceptance"

    report = run_acceptance(output_dir=output_dir)

    assert report["phase"] == "5E-A"
    assert report["task"] == "document_summary_acceptance_pack"
    assert report["status"] == "passed"
    assert report["case_count"] == 1
    assert report["passed_count"] == 1
    assert report["failed_count"] == 0
    assert report["json_valid_count"] == 4
    assert report["artifact_write_count"] == 4
    assert report["citation_valid_count"] == 1
    assert report["unsupported_count"] == 0
    assert report["boundary"] == BOUNDARY

    case = report["cases"][0]
    assert case["case_id"] == "txt_ingestion_summary"
    assert case["status"] == "passed"
    assert case["task_type"] == "document_summary"
    assert case["tools_used"] == ["document_summary"]
    assert case["citations_valid"] is True
    assert case["validation_errors"] == []

    for name in ("result", "summary", "router_plan", "trace"):
        artifact_path = Path(case["artifact_paths"][name])
        assert artifact_path.is_file()
        json.loads(artifact_path.read_text(encoding="utf-8"))

    result = json.loads(Path(case["artifact_paths"]["result"]).read_text(encoding="utf-8"))
    assert result["tools_used"] == ["document_summary"]
    assert result["structured_result"]["status"] == "completed"

    report_path = output_dir / "acceptance_report.json"
    assert report_path.is_file()
    assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "passed"
