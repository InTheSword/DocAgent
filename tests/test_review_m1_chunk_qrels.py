from __future__ import annotations

import json

import pytest

from scripts.review_m1_chunk_qrels import QrelsReviewError, review_queue_item


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
