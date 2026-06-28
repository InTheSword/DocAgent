from __future__ import annotations

import json
from pathlib import Path

from scripts.run_phase5i_b_model_answer_quality import run_phase5i_b_model_answer_quality


ROOT = Path(__file__).resolve().parents[1]
SCENARIO_PATH = ROOT / "data" / "scenario_sets" / "phase5i_b" / "phase5i_b_cases.jsonl"


def test_runner_with_fake_policy_writes_artifacts_but_not_real_model_backed(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    report = run_phase5i_b_model_answer_quality(
        scenario_path=SCENARIO_PATH,
        db_path=tmp_path / "docagent.db",
        output_dir=output_dir,
        document_root=tmp_path / "documents",
        answer_policy_provider="fake",
        enable_query_planning=True,
        query_planner_mode="rule",
    )

    assert report["status"] == "completed"
    assert report["acceptance_state"] == "mock_verified"
    assert report["used_model_answer_generation"] is False
    assert report["used_fake_policy"] is True
    assert report["final_answer_quality_evaluated"] is True

    metrics = json.loads((output_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["case_count"] == 14
    assert metrics["completed_count"] >= 8
    assert metrics["used_fake_policy"] is True
    assert (output_dir / "predictions.jsonl").is_file()
    assert (output_dir / "case_reports.jsonl").is_file()
    assert (output_dir / "failure_analysis.md").is_file()
    assert (output_dir / "training_candidates_raw.jsonl").is_file()
    assert (output_dir / "acceptance_report.json").is_file()

    first_prediction = json.loads((output_dir / "predictions.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert "answer_correct" in first_prediction
    assert "citation_valid" in first_prediction
    assert "location_correct" in first_prediction
    assert first_prediction["used_model_answer_generation"] is False


def test_runner_missing_api_config_skips_without_fake_pass(tmp_path: Path) -> None:
    output_dir = tmp_path / "missing_api"
    report = run_phase5i_b_model_answer_quality(
        scenario_path=SCENARIO_PATH,
        db_path=tmp_path / "docagent.db",
        output_dir=output_dir,
        document_root=tmp_path / "documents",
        answer_policy_provider="openai_compatible",
        allow_external_api=True,
        answer_policy_env_file=tmp_path / "missing.env",
    )

    assert report["status"] == "skipped_api_missing"
    assert report["acceptance_state"] == "skipped_api_missing"
    assert report["used_model_answer_generation"] is False
    assert report["used_fake_policy"] is False
    assert report["final_answer_quality_evaluated"] is False
    assert "answer_policy_env_file_missing" in report["notes"]

    metrics = json.loads((output_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["skipped_count"] == 14
    assert metrics["used_fake_policy"] is False
    assert json.loads((output_dir / "model_config_masked.json").read_text(encoding="utf-8"))["api_key_logged"] is False
