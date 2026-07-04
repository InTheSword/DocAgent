from __future__ import annotations

import json
from pathlib import Path

from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.compare_phase5i_answer_quality_runs import compare_phase5i_answer_quality_runs


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def report(case_id: str, *, passed: bool, reason: str = "", answer: str = "answer") -> dict:
    return {
        "case_id": case_id,
        "passed": passed,
        "failure_reasons": [reason] if reason else [],
        "answer_preview": answer,
        "citation_pages": [1],
    }


def write_run(run_dir: Path, *, run_id: str, mode: str, reports: list[dict]) -> None:
    passed_count = sum(1 for item in reports if item["passed"])
    write_json(
        run_dir / "phase5i_summary.json",
        {
            "run_id": run_id,
            "status": "success",
            "answer_policy_mode": mode,
            "answer_output_contract": "v3_refs",
            "case_count": len(reports),
            "passed_count": passed_count,
            "failed_count": len(reports) - passed_count,
            "json_valid_count": len(reports),
            "citation_page_hit_count": len(reports),
            "answer_keyword_hit_count": passed_count,
            "evidence_keyword_hit_count": len(reports),
            "used_qwen_answer_policy_count": len(reports),
            "used_llm_query_rewriter_count": len(reports),
            "failure_reason_distribution": {},
            "used_training": False,
            "formal_benchmark_acceptance": False,
            "validation_subset_used_for_training": False,
        },
    )
    write_json(
        run_dir / "metrics.json",
        {
            "answer_correct_rate": round(passed_count / len(reports), 4),
            "format_valid_rate": 1.0,
            "citation_valid_rate": 1.0,
            "location_valid_rate": 1.0,
        },
    )
    write_jsonl(run_dir / "case_reports.jsonl", reports)


def test_compare_phase5i_answer_quality_runs_detects_candidate_regression(tmp_path: Path) -> None:
    base_dir = tmp_path / "base"
    candidate_dir = tmp_path / "candidate"
    write_run(
        base_dir,
        run_id="base_run",
        mode="base",
        reports=[report("case1", passed=True), report("case2", passed=True), report("case3", passed=True)],
    )
    write_run(
        candidate_dir,
        run_id="candidate_run",
        mode="sft",
        reports=[
            report("case1", passed=True),
            report("case2", passed=False, reason="answer_keyword_missing"),
            report("case3", passed=False, reason="evidence_keyword_missing"),
        ],
    )

    result = compare_phase5i_answer_quality_runs(
        base_run_dir=base_dir,
        candidate_run_dir=candidate_dir,
        output_root=tmp_path / "compare",
        run_id="compare",
        base_label="base",
        candidate_label="adapter480",
        sync_output_root=tmp_path / "sync",
    )

    assert result["status"] == "success"
    assert result["quality_status"] == "diagnostic_only"
    assert result["base"]["passed_count"] == 3
    assert result["candidate"]["passed_count"] == 1
    assert result["case_change_counts"] == {"both_passed": 1, "candidate_regressed": 2}
    assert result["interpretation"]["contract_result"] == "candidate_underperformed_base_on_clean_contract"
    assert "judge whether the training objective improved" in result["interpretation"]["boundary"]
    assert result["promotion_gate"]["gate_scope"] == "default_checkpoint_deployment_guard"
    assert result["promotion_gate"]["decision"] == "blocked"
    assert result["promotion_gate"]["candidate_promotable_from_this_artifact"] is False
    assert result["promotion_gate"]["training_effectiveness_judged"] is False
    assert "candidate_regressed_cases_present" in result["promotion_gate"]["reasons"]
    assert result["used_training"] is False
    assert result["formal_benchmark_acceptance"] is False
    assert (tmp_path / "sync" / "compare" / "summary.json").is_file()

    rows = read_jsonl(tmp_path / "compare" / "compare" / "rows.jsonl")
    assert rows[1]["change"] == "candidate_regressed"
    assert rows[1]["candidate_failure_reasons"] == ["answer_keyword_missing"]


def test_compare_phase5i_answer_quality_runs_handles_candidate_improvement(tmp_path: Path) -> None:
    base_dir = tmp_path / "base"
    candidate_dir = tmp_path / "candidate"
    write_run(base_dir, run_id="base_run", mode="base", reports=[report("case1", passed=False, reason="miss")])
    write_run(candidate_dir, run_id="candidate_run", mode="sft", reports=[report("case1", passed=True)])

    result = compare_phase5i_answer_quality_runs(
        base_run_dir=base_dir,
        candidate_run_dir=candidate_dir,
        output_root=tmp_path / "compare",
        run_id="compare",
    )

    assert result["case_change_counts"] == {"candidate_improved": 1}
    assert result["interpretation"]["contract_result"] == "candidate_outperformed_base_on_clean_contract"
    assert result["promotion_gate"]["decision"] == "requires_broader_eval"
    assert result["promotion_gate"]["broader_eval_recommended"] is True
    assert result["promotion_gate"]["candidate_promotable_from_this_artifact"] is False
    assert result["promotion_gate"]["training_effectiveness_judged"] is False


def test_compare_phase5i_answer_quality_runs_blocks_missing_artifacts(tmp_path: Path) -> None:
    base_dir = tmp_path / "base"
    candidate_dir = tmp_path / "candidate"
    write_run(base_dir, run_id="base_run", mode="base", reports=[report("case1", passed=True)])
    candidate_dir.mkdir()

    result = compare_phase5i_answer_quality_runs(
        base_run_dir=base_dir,
        candidate_run_dir=candidate_dir,
        output_root=tmp_path / "compare",
        run_id="blocked",
    )

    assert result["status"] == "failed"
    assert result["used_training"] is False
    assert any("phase5i_summary.json" in item for item in result["missing"])
