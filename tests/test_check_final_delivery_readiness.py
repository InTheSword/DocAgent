from __future__ import annotations

import json
import shutil
from pathlib import Path

from scripts.check_final_delivery_readiness import run_readiness_check


ROOT = Path(__file__).resolve().parents[1]


def test_final_delivery_readiness_passes_current_repo(tmp_path: Path) -> None:
    result = run_readiness_check(output_dir=tmp_path / "readiness", run_id="repo_readiness")

    assert result["status"] == "success"
    assert result["passed_check_count"] == result["check_count"]
    assert result["used_qwen"] is False
    assert result["used_training"] is False
    assert result["formal_benchmark_acceptance"] is False
    for path in result["artifact_paths"]:
        assert Path(path).is_file()


def test_final_delivery_readiness_reports_documentation_gap(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    for relative_path in (
        "README.md",
        "AGENTS.md",
        "CURRENT_STATUS.md",
        "docs/ACTIVE_PLAN.md",
        "docs/FINAL_DELIVERY_CLI.md",
        "docs/SERVER_SETUP.md",
        "docs/DATASETS.md",
        "scripts/docagent_cli.py",
        "scripts/run_final_raw_pdf_smoke.py",
        "scripts/prepare_mpdocvqa_evidence.py",
        "scripts/run_mpdocvqa_full_workflow_diagnostic.py",
    ):
        source = ROOT / relative_path
        target = repo / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    (repo / "docs" / "FINAL_DELIVERY_CLI.md").write_text("incomplete guide\n", encoding="utf-8")

    result = run_readiness_check(root=repo, output_dir=tmp_path / "readiness", run_id="doc_gap")

    assert result["status"] == "failed"
    assert any("documentation_snippet_missing:docs/FINAL_DELIVERY_CLI.md" in item for item in result["failures"])
    summary = json.loads((tmp_path / "readiness" / "doc_gap" / "summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "failed"
