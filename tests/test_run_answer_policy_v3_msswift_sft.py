from __future__ import annotations

import json
from pathlib import Path

from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.run_answer_policy_v3_msswift_sft import run_msswift_sft


def _record(record_id: str, *, source: str = "tatqa", answer: str = "March 12, 2020") -> dict:
    target = {
        "answer": answer,
        "supporting_refs": ["E1"],
        "support_status": "supported",
        "reasoning_summary": "The selected evidence contains the answer.",
    }
    return {
        "id": record_id,
        "source": source,
        "bucket": "evidence_extractive_supported",
        "messages": [
            {
                "role": "system",
                "content": "Return exactly one valid JSON object with answer, supporting_refs, support_status, and reasoning_summary.",
            },
            {
                "role": "user",
                "content": "## Question\nWhat is the invoice date?\n\n## Evidence Candidates\n[E1] Invoice Date: March 12, 2020",
            },
            {"role": "assistant", "content": json.dumps(target)},
        ],
    }


def test_answer_policy_v3_msswift_dry_run_writes_swift_artifacts(tmp_path: Path) -> None:
    tatqa_path = tmp_path / "train" / "tatqa_sft.jsonl"
    mpdocvqa_path = tmp_path / "train" / "mpdocvqa_sft.jsonl"
    write_jsonl(tatqa_path, [_record("t1"), _record("t2")])
    write_jsonl(mpdocvqa_path, [_record("m1", source="mp_docvqa")])

    result = run_msswift_sft(
        sft_inputs=[tatqa_path, mpdocvqa_path],
        output_root=tmp_path / "out",
        run_id="swift",
        max_records=3,
    )

    artifact_dir = tmp_path / "out" / "swift"
    records = read_jsonl(artifact_dir / "swift_train.jsonl")
    command = json.loads((artifact_dir / "swift_command.json").read_text(encoding="utf-8"))["command"]
    assert result["status"] == "success"
    assert result["execute"] is False
    assert result["used_training"] is False
    assert result["training_started"] is False
    assert result["validation_subset_used_for_training"] is False
    assert result["formal_benchmark_acceptance"] is False
    assert [record["id"] for record in records] == ["t1", "m1", "t2"]
    assert records[0]["messages"][-1]["role"] == "assistant"
    assert "sft" in command
    assert "--dataset" in command
    assert str(artifact_dir / "swift_train.jsonl") in command
    assert "--tuner_type" in command
    assert "--train_type" not in command
    assert (artifact_dir / "result.json").is_file()
    assert (artifact_dir / "summary.json").is_file()
    assert (artifact_dir / "summary.md").is_file()
    assert (artifact_dir / "manifest.json").is_file()


def test_answer_policy_v3_msswift_dry_run_can_load_existing_adapter(tmp_path: Path) -> None:
    source_path = tmp_path / "train" / "sft_train.jsonl"
    adapter_path = tmp_path / "adapter"
    adapter_path.mkdir()
    (adapter_path / "adapter_config.json").write_text("{}", encoding="utf-8")
    write_jsonl(source_path, [_record("ok")])

    result = run_msswift_sft(
        sft_inputs=[source_path],
        output_root=tmp_path / "out",
        run_id="adapter",
        adapter_path=adapter_path,
    )

    command = json.loads((tmp_path / "out" / "adapter" / "swift_command.json").read_text(encoding="utf-8"))["command"]
    assert result["status"] == "success"
    assert result["adapter_path"] == adapter_path.as_posix()
    assert "--adapters" in command
    assert str(adapter_path) in command


def test_answer_policy_v3_msswift_blocks_validation_like_inputs(tmp_path: Path) -> None:
    source_path = tmp_path / "final_eval" / "sft_train.jsonl"
    write_jsonl(source_path, [_record("bad")])

    result = run_msswift_sft(
        sft_inputs=[source_path],
        output_root=tmp_path / "out",
        run_id="blocked",
    )

    assert result["status"] == "blocked"
    assert result["selected_record_count"] == 0
    assert result["block_reasons"] == ["validation_like_input_path:final_eval"]
    assert read_jsonl(tmp_path / "out" / "blocked" / "swift_train.jsonl") == []


def test_answer_policy_v3_msswift_blocks_missing_adapter(tmp_path: Path) -> None:
    source_path = tmp_path / "train" / "sft_train.jsonl"
    write_jsonl(source_path, [_record("ok")])

    result = run_msswift_sft(
        sft_inputs=[source_path],
        output_root=tmp_path / "out",
        run_id="missing_adapter",
        adapter_path=tmp_path / "missing_adapter",
    )

    assert result["status"] == "blocked"
    assert result["selected_record_count"] == 0
    assert result["block_reasons"] == [f"missing_adapter_path:{(tmp_path / 'missing_adapter').as_posix()}"]


def test_answer_policy_v3_msswift_execute_blocks_when_executable_missing(tmp_path: Path) -> None:
    source_path = tmp_path / "train" / "sft_train.jsonl"
    missing_swift = tmp_path / "missing-swift"
    write_jsonl(source_path, [_record("ok")])

    result = run_msswift_sft(
        sft_inputs=[source_path],
        output_root=tmp_path / "out",
        run_id="missing",
        swift_executable=str(missing_swift),
        execute=True,
    )

    assert result["status"] == "blocked"
    assert result["used_training"] is False
    assert result["training_started"] is False
    assert result["block_reasons"] == ["msswift_executable_not_found"]
