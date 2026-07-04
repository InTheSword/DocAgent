from __future__ import annotations

import json
from pathlib import Path

from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.compare_answer_policy_v3_checkpoint_evals import compare_checkpoint_evals


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run_dir(root: Path, name: str, *, rows: list[dict], metrics: dict) -> Path:
    run_dir = root / name
    run_dir.mkdir(parents=True)
    write_jsonl(run_dir / "rows.jsonl", rows)
    _write_json(
        run_dir / "summary.json",
        {
            "status": "success",
            "run_id": name,
            "model_mode": "base_only" if name == "base" else "peft_adapter",
            "metrics": metrics,
            "used_qwen": True,
            "used_training": False,
            "formal_benchmark_acceptance": False,
            "validation_subset_used_for_training": False,
        },
    )
    return run_dir


def _row(row_id: str, *, answer_exact: bool, schema_ok: bool = True, positive_ref_hit: bool = True) -> dict:
    return {
        "id": row_id,
        "source": "tatqa",
        "target": {"answer": "42"},
        "prediction": {"answer": "42" if answer_exact else "41"},
        "metrics": {
            "answer_exact": answer_exact,
            "schema_ok": schema_ok,
            "positive_ref_hit": positive_ref_hit,
        },
    }


def test_compare_answer_policy_v3_checkpoint_evals_writes_delta_and_breakdown(tmp_path: Path) -> None:
    base_dir = _run_dir(
        tmp_path,
        "base",
        rows=[_row("calc", answer_exact=False, schema_ok=False), _row("table", answer_exact=True)],
        metrics={
            "evaluated_count": 2,
            "schema_valid_rate": 0.5,
            "answer_exact_rate": 0.5,
            "positive_ref_hit_rate": 1.0,
        },
    )
    candidate_dir = _run_dir(
        tmp_path,
        "candidate",
        rows=[_row("calc", answer_exact=True), _row("table", answer_exact=True)],
        metrics={
            "evaluated_count": 2,
            "schema_valid_rate": 1.0,
            "answer_exact_rate": 1.0,
            "positive_ref_hit_rate": 1.0,
        },
    )
    metadata_path = tmp_path / "metadata.jsonl"
    write_jsonl(
        metadata_path,
        [
            {"id": "calc", "category": "calculation_supported", "target_kinds": ["calculation_result"]},
            {"id": "table", "category": "table_value_supported", "target_kinds": ["table"]},
        ],
    )

    result = compare_checkpoint_evals(
        base_run_dir=base_dir,
        candidate_run_dir=candidate_dir,
        output_root=tmp_path / "out",
        run_id="compare",
        metadata_rows_path=metadata_path,
    )

    artifact_dir = tmp_path / "out" / "compare"
    rows = read_jsonl(artifact_dir / "rows.jsonl")
    assert result["status"] == "success"
    assert result["metric_deltas"]["answer_exact_rate"] == 0.5
    assert result["metric_deltas"]["schema_valid_rate"] == 0.5
    assert result["row_summary"]["candidate_improved_count"] == 1
    assert result["row_summary"]["both_answer_exact_count"] == 1
    assert result["category_breakdown"]["calculation_supported"]["candidate_improved_count"] == 1
    assert result["category_breakdown"]["table_value_supported"]["both_answer_exact_count"] == 1
    assert {row["movement"] for row in rows} == {"candidate_improved", "both_answer_exact"}
    assert result["used_qwen"] is True
    assert result["used_training"] is False
    assert result["formal_benchmark_acceptance"] is False
    assert (artifact_dir / "summary.md").is_file()
    assert (artifact_dir / "manifest.json").is_file()


def test_compare_answer_policy_v3_checkpoint_evals_blocks_missing_inputs(tmp_path: Path) -> None:
    base_dir = tmp_path / "missing_base"
    candidate_dir = _run_dir(
        tmp_path,
        "candidate",
        rows=[_row("r1", answer_exact=True)],
        metrics={"evaluated_count": 1},
    )

    result = compare_checkpoint_evals(
        base_run_dir=base_dir,
        candidate_run_dir=candidate_dir,
        output_root=tmp_path / "out",
        run_id="blocked",
    )

    assert result["status"] == "blocked"
    assert any("missing_base" in item for item in result["missing"])
    assert read_jsonl(tmp_path / "out" / "blocked" / "rows.jsonl") == []
