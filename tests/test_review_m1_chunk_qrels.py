from __future__ import annotations

import argparse
import json

import pytest

from scripts.review_m1_chunk_qrels import QrelsReviewError, review_queue_item, run


def _item() -> dict:
    return {
        "sample_id": "S1",
        "group_id": "g1",
        "question": "What is the value?",
        "source_evidence": {"verbatim_content": "The value is 42."},
        "candidate_class": "exact_single",
        "candidates": [
            {
                "chunk_ids": ["c1"],
                "chunk_content_hashes": {"c1": "hash-c1"},
                "pages": [1],
                "block_types": ["text"],
                "match_method": "normalized_contains",
                "match_score": 1.0,
                "preview": "[c1 p1] The value is 42.",
            }
        ],
    }


class FakeClient:
    def __init__(self, outputs: list[dict]):
        self.outputs = outputs
        self.calls = []

    def complete(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return json.dumps(self.outputs.pop(0))


class TransientFailureClient(FakeClient):
    def complete(self, **kwargs) -> str:
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise RuntimeError("HTTP Error 429: Too Many Requests")
        return json.dumps(self.outputs.pop(0))


def test_review_queue_item_accepts_a_complete_candidate() -> None:
    client = FakeClient(
        [
            {
                "decision": "accept_candidate",
                "selected_candidate_indexes": [0],
                "rationale": "The candidate contains the complete source evidence.",
            }
        ]
    )

    result, retried = review_queue_item(_item(), llm_client=client)

    assert result["selected_candidate_indexes"] == [0]
    assert retried is False
    assert "selected_candidate_indexes" in client.calls[0]["system_prompt"]


def test_review_queue_item_retries_invalid_output_once() -> None:
    client = FakeClient(
        [
            {"decision": "accept_candidate", "selected_candidate_indexes": [], "rationale": "invalid"},
            {"decision": "exclude", "selected_candidate_indexes": [], "rationale": "No candidate is sufficient."},
        ]
    )

    result, retried = review_queue_item(_item(), llm_client=client)

    assert result["decision"] == "exclude"
    assert retried is True
    assert "correction" in client.calls[1]["user_payload"]


def test_review_queue_item_fails_closed_after_two_invalid_outputs() -> None:
    client = FakeClient(
        [
            {"decision": "accept_candidate", "selected_candidate_indexes": [2], "rationale": "invalid"},
            {"decision": "exclude", "selected_candidate_indexes": [0], "rationale": "invalid"},
        ]
    )

    with pytest.raises(QrelsReviewError):
        review_queue_item(_item(), llm_client=client)


def test_review_queue_item_retries_transient_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.review_m1_chunk_qrels.time.sleep", lambda _seconds: None)
    client = TransientFailureClient(
        [
            {
                "decision": "accept_candidate",
                "selected_candidate_indexes": [0],
                "rationale": "The candidate contains the complete source evidence.",
            }
        ]
    )

    result, retried = review_queue_item(_item(), llm_client=client)

    assert result["decision"] == "accept_candidate"
    assert retried is False
    assert len(client.calls) == 2


def test_run_freezes_when_partial_already_covers_remaining_queue(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate_dir = tmp_path / "candidates"
    output_dir = tmp_path / "output"
    candidate_dir.mkdir()
    output_dir.mkdir()
    item = _item()
    template = {"sample_id": "S1", "group_id": "g1"}
    partial = {
        **template,
        "decision": "accept_candidate",
        "selected_chunk_sets": [["c1"]],
        "selected_chunk_hashes": {"c1": "hash-c1"},
    }
    for name, rows in (
        ("chunk_qrels_candidates.jsonl", [{"sample_id": "S1"}]),
        ("qrels_review_queue.jsonl", [item]),
        ("review_decisions.template.jsonl", [template]),
    ):
        (candidate_dir / name).write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
    human_path = tmp_path / "human.jsonl"
    human_path.write_text("", encoding="utf-8")
    (output_dir / "ai_review_decisions.partial.jsonl").write_text(
        json.dumps(partial) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr("scripts.review_m1_chunk_qrels._load_corpus", lambda _path: ({}, {}, {}))
    monkeypatch.setattr(
        "scripts.review_m1_chunk_qrels.freeze_qrels",
        lambda *_args, **_kwargs: [{"evaluation_eligible": True}],
    )
    client = FakeClient([])
    args = argparse.Namespace(
        candidate_dir=candidate_dir,
        corpus_manifest=tmp_path / "corpus.json",
        human_decisions=human_path,
        env_file=tmp_path / "unused.env",
        output_dir=output_dir,
        sync_dir="",
        run_id="resume-complete",
        max_workers=1,
    )

    result = run(args, llm_client=client, model_name="test-model")

    assert result["status"] == "success"
    assert result["metrics"]["independent_ai_reviewed_group_count"] == 1
    assert result["metrics"]["reviewer_counts"] == {"unknown": 1}
    assert client.calls == []
