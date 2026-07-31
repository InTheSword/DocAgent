from __future__ import annotations

import pytest

from docagent.schemas import Chunk, EvidenceLocation
from scripts.eval_m1_query_retrieval import (
    _generic_retrieval_samples,
    _query_prediction,
    _query_metric_group,
    _retrieval_metric_group,
    map_gold_evidence,
    validate_samples,
)


def _chunk(block_id: str, text: str, *, page: int = 2, content_type: str = "body") -> Chunk:
    return Chunk(
        doc_id="doc",
        block_id=block_id,
        block_type="table" if content_type == "table" else "text",
        text=text,
        page_id=page,
        location=EvidenceLocation(page=page, block_id=block_id),
        metadata={
            "content_type": content_type,
            "source_page_numbers": [page],
            "exclude_from_retrieval": False,
        },
    )


def _sample() -> dict:
    return {
        "sample_id": "S1",
        "document_file": "sample.pdf",
        "language": "en",
        "question": "What is the value?",
        "intent": "semantic_fact",
        "query_actions": ["none"],
        "expected_routes": ["dense", "sparse"],
        "must_preserve": [],
        "gold_evidence_groups": [
            {
                "group_id": "G1",
                "evidence_type": "text",
                "physical_pages": [2],
                "source_locator": "p2",
                "verbatim_content": "The reported value was 42.",
            }
        ],
    }


def test_validate_samples_rejects_duplicate_ids() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        validate_samples([_sample(), _sample()])


def test_gold_mapping_uses_page_and_verbatim_content() -> None:
    rows = map_gold_evidence(
        [_sample()],
        {"sample.pdf": {"doc_id": "doc"}},
        {
            "doc": [
                _chunk("wrong-page", "The reported value was 42.", page=1),
                _chunk("gold", "Context. The reported value was 42. More context.", page=2),
            ]
        },
    )

    assert rows[0]["all_groups_mapped"] is True
    assert rows[0]["groups"][0]["mapped_block_ids"] == ["gold"]
    assert rows[0]["groups"][0]["match_method"] == "normalized_contains"
    assert rows[0]["groups"][0]["qrel_candidate_status"] == "unreviewed"
    assert rows[0]["qrels_reviewed"] is False


def test_query_prediction_separates_transform_action_from_preservation_constraint() -> None:
    sample = _sample()
    sample["query_actions"] = ["none", "preserve_terms"]
    sample["must_preserve"] = ["42"]
    prediction = _query_prediction(
        sample,
        {
            "query_decision": {"intent": "semantic_fact", "source": "llm"},
            "query_plan": {
                "actions": ["none"],
                "retrieval_queries": ["What is the value 42?"],
                "preserved_terms": ["42"],
                "retrieval_routes": ["dense", "sparse"],
                "transformation_source": "llm",
            },
            "trace": {},
        },
        elapsed_ms=1.0,
    )

    assert prediction["transform_action_exact_match"] is True
    assert prediction["legacy_action_exact_match"] is False
    assert prediction["must_preserve_all"] is True
    assert prediction["workflow_match"] is True


def test_generic_retrieval_scope_excludes_workflows_with_dedicated_execution_paths() -> None:
    samples = [
        {"sample_id": "text", "document_file": "a.pdf", "intent": "semantic_fact"},
        {"sample_id": "complex", "document_file": "a.pdf", "intent": "complex_analysis"},
        {"sample_id": "table", "document_file": "a.pdf", "intent": "table_lookup"},
        {"sample_id": "visual", "document_file": "a.pdf", "intent": "visual_lookup"},
        {"sample_id": "summary", "document_file": "a.pdf", "intent": "document_summary"},
        {"sample_id": "general", "document_file": None, "intent": "no_retrieval"},
    ]

    assert [row["sample_id"] for row in _generic_retrieval_samples(samples)] == ["text", "complex"]


def test_query_metrics_keep_ordered_and_set_action_em_separate() -> None:
    metrics = _query_metric_group(
        [
            {
                "intent_match": True,
                "workflow_match": True,
                "transform_action_exact_match": True,
                "transform_action_set_match": True,
                "legacy_action_exact_match": False,
                "legacy_action_set_match": True,
                "required_routes_hit": True,
                "expected_routes": ["dense", "sparse"],
                "route_hit_count": 2,
                "must_preserve_all": True,
                "must_preserve_count": 1,
                "preserved_count": 1,
                "decision_source": "llm",
                "transformation_source": "llm",
            }
        ]
    )

    assert metrics["transform_action_exact_match"] == 1.0
    assert metrics["legacy_action_exact_match"] == 0.0
    assert metrics["legacy_action_set_exact_match"] == 1.0
    assert metrics["legacy_route_micro_recall"] == 1.0


def test_retrieval_metrics_keep_unmapped_groups_in_e2e_denominator() -> None:
    metrics = _retrieval_metric_group(
        [
            {
                "group_count": 2,
                "mapped_group_count": 1,
                "covered_group_count_at_5": 1,
                "covered_mapped_group_count_at_5": 1,
                "reciprocal_rank_at_10": 0.5,
                "hit_at_5": True,
                "latency_ms": 10.0,
            }
        ]
    )

    assert metrics["gold_mapping_rate"] == 0.5
    assert metrics["recall_at_5_end_to_end"] == 0.5
    assert metrics["recall_at_5_mapped_only"] == 1.0
    assert metrics["mrr_at_10"] == 0.5
