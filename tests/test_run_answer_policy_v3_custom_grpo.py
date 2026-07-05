from __future__ import annotations

import json
from pathlib import Path

import pytest

from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.run_answer_policy_v3_custom_grpo import reward_prediction, run_custom_grpo, to_grpo_record


def _target(answer: str = "March 12, 2020", *, insufficient: bool = False) -> dict:
    if insufficient:
        return {
            "answer": "Insufficient evidence.",
            "supporting_refs": [],
            "support_status": "insufficient",
            "reasoning_summary": "No evidence candidate contains the answer.",
        }
    return {
        "answer": answer,
        "supporting_refs": ["E1"],
        "support_status": "supported",
        "reasoning_summary": "E1 contains the answer.",
    }


def _record(record_id: str, *, insufficient: bool = False) -> dict:
    return {
        "id": record_id,
        "source": "tatqa",
        "bucket": "insufficient_confirmed" if insufficient else "evidence_extractive_supported",
        "messages": [
            {"role": "system", "content": "Return v3 JSON."},
            {
                "role": "user",
                "content": "## Question\nWhat is the date?\n\n## Evidence Candidates\n[E1] Date: March 12, 2020",
            },
            {"role": "assistant", "content": json.dumps(_target(insufficient=insufficient))},
        ],
    }


def _adapter(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "adapter_config.json").write_text("{}", encoding="utf-8")
    return path


def test_to_grpo_record_strips_assistant_and_sets_v3_reward_metadata() -> None:
    converted = to_grpo_record(_record("q1"))

    assert converted is not None
    assert [message["role"] for message in converted["messages"]] == ["system", "user"]
    assert converted["gold_answer"] == "March 12, 2020"
    assert converted["positive_refs"] == ["E1"]
    assert converted["insufficient_expected"] is False
    assert "assistant" not in {message["role"] for message in converted["messages"]}
    assert "supporting_refs" not in json.dumps(converted["messages"], ensure_ascii=False)


def test_to_grpo_record_handles_insufficient_records() -> None:
    converted = to_grpo_record(_record("q2", insufficient=True))

    assert converted is not None
    assert converted["gold_answer"] == ""
    assert converted["positive_refs"] == []
    assert converted["insufficient_expected"] is True
    assert reward_prediction(_target(insufficient=True), converted)["reward"] == pytest.approx(1.0)


def test_custom_grpo_dry_run_writes_train_artifacts(tmp_path: Path) -> None:
    source_path = tmp_path / "train" / "sft_train.jsonl"
    adapter_path = _adapter(tmp_path / "adapter")
    write_jsonl(source_path, [_record("q1"), _record("q2", insufficient=True)])

    result = run_custom_grpo(
        sft_inputs=[source_path],
        output_root=tmp_path / "out",
        run_id="grpo",
        adapter_path=adapter_path,
        max_records=2,
    )

    artifact_dir = tmp_path / "out" / "grpo"
    records = read_jsonl(artifact_dir / "grpo_train.jsonl")
    assert result["status"] == "success"
    assert result["execute"] is False
    assert result["used_training"] is False
    assert result["training_started"] is False
    assert result["selected_record_count"] == 2
    assert records[0]["positive_refs"] == ["E1"]
    assert records[1]["insufficient_expected"] is True
    assert (artifact_dir / "result.json").is_file()
    assert (artifact_dir / "summary.json").is_file()
    assert (artifact_dir / "summary.md").is_file()
    assert (artifact_dir / "manifest.json").is_file()


def test_custom_grpo_blocks_validation_like_input(tmp_path: Path) -> None:
    source_path = tmp_path / "final_eval" / "sft_train.jsonl"
    adapter_path = _adapter(tmp_path / "adapter")
    write_jsonl(source_path, [_record("bad")])

    result = run_custom_grpo(
        sft_inputs=[source_path],
        output_root=tmp_path / "out",
        run_id="blocked",
        adapter_path=adapter_path,
    )

    assert result["status"] == "blocked"
    assert result["selected_record_count"] == 0
    assert result["block_reasons"] == ["validation_like_input_path:final_eval"]
    assert read_jsonl(tmp_path / "out" / "blocked" / "grpo_train.jsonl") == []


def test_custom_grpo_execute_blocks_missing_adapter(tmp_path: Path) -> None:
    source_path = tmp_path / "train" / "sft_train.jsonl"
    write_jsonl(source_path, [_record("ok")])

    result = run_custom_grpo(
        sft_inputs=[source_path],
        output_root=tmp_path / "out",
        run_id="missing_adapter",
        adapter_path=tmp_path / "missing_adapter",
        execute=True,
    )

    assert result["status"] == "blocked"
    assert result["used_training"] is False
    assert result["training_started"] is False
    assert result["block_reasons"] == [f"missing_adapter_path:{(tmp_path / 'missing_adapter').as_posix()}"]


def test_custom_grpo_execute_keeps_training_started_false_when_cuda_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_path = tmp_path / "train" / "sft_train.jsonl"
    adapter_path = _adapter(tmp_path / "adapter")
    write_jsonl(source_path, [_record("ok")])

    def blocked_training(**_: object) -> dict:
        return {"status": "blocked", "blocker": "cuda_unavailable"}

    monkeypatch.setattr("scripts.run_answer_policy_v3_custom_grpo.run_custom_grpo_training", blocked_training)

    result = run_custom_grpo(
        sft_inputs=[source_path],
        output_root=tmp_path / "out",
        run_id="cuda_block",
        adapter_path=adapter_path,
        execute=True,
    )

    assert result["status"] == "blocked"
    assert result["used_training"] is False
    assert result["training_started"] is False
    assert result["block_reasons"] == ["cuda_unavailable"]
