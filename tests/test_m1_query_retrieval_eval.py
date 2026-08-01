from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from docagent.schemas import Chunk, EvidenceLocation
from scripts.eval_m1_query_retrieval import (
    _generic_retrieval_samples,
    _policy_selected_retrieval_metrics,
    _query_prediction,
    _query_metric_group,
    _reranker_ablation,
    _retrieval_metric_group,
    finalize_outputs,
    map_gold_evidence,
    parse_args,
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


def _detail(
    sample_id: str,
    intent: str,
    mode: str,
    *,
    hit: bool,
    reciprocal_rank: float,
    latency_ms: float,
) -> dict:
    covered = 1 if hit else 0
    return {
        "sample_id": sample_id,
        "document_file": "sample.pdf",
        "language": "en",
        "intent": intent,
        "query_variant": "planned",
        "retriever_mode": mode,
        "group_count": 1,
        "mapped_group_count": 1,
        "covered_group_count_at_5": covered,
        "covered_mapped_group_count_at_5": covered,
        "reciprocal_rank_at_10": reciprocal_rank,
        "hit_at_5": hit,
        "planned_routes_all_executed": True,
        "planned_route_count": 2,
        "executed_planned_route_count": 2,
        "latency_ms": latency_ms,
    }


def test_validate_samples_rejects_duplicate_ids() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        validate_samples([_sample(), _sample()])


def test_v3_cli_defaults_do_not_target_historical_baseline(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["eval_m1_query_retrieval.py"])

    args = parse_args()

    assert args.run_id == "m1_f2_f3_workflow_eval_20260801"
    assert args.output_dir == "outputs/m1_f2_f3_workflow_eval_20260801"
    assert args.sync_dir == "outputs/sync/m1_f2_f3_workflow_eval_20260801"


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


def test_query_prediction_reports_retry_and_retriever_policy_contract() -> None:
    prediction = _query_prediction(
        _sample(),
        {
            "query_decision": {
                "intent": "semantic_fact",
                "task_type": "fact_lookup",
                "evidence_types": ["text"],
                "multi_step": False,
                "requires_retrieval": True,
                "source": "llm",
            },
            "query_plan": {
                "actions": ["none"],
                "retrieval_queries": ["What is the value?"],
                "preserved_terms": [],
                "retrieval_routes": ["dense", "sparse"],
                "retriever_mode": "hybrid_rerank",
                "transformation_source": "llm",
            },
            "trace": {
                "intent_router": {
                    "status": "used_after_retry",
                    "attempt_count": 2,
                    "validation_errors": ["extra field"],
                },
                "query_transformer": {
                    "status": "used",
                    "attempt_count": 1,
                    "validation_errors": [],
                },
            },
        },
        elapsed_ms=1.0,
    )

    assert prediction["expected_retriever_mode"] == "hybrid_rerank"
    assert prediction["predicted_retriever_mode"] == "hybrid_rerank"
    assert prediction["retriever_mode_match"] is True
    assert prediction["single_transform_strategy_legal"] is True
    assert prediction["router_status"] == "used_after_retry"
    assert prediction["router_attempt_count"] == 2
    assert prediction["router_validation_error_count"] == 1


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
                "retriever_mode_match": True,
                "single_transform_strategy_legal": True,
                "router_status": "used_after_retry",
                "router_attempt_count": 2,
                "router_validation_error_count": 1,
                "transformer_status": "used",
                "transformer_attempt_count": 1,
                "transformer_validation_error_count": 0,
            }
        ]
    )

    assert metrics["transform_action_exact_match"] == 1.0
    assert metrics["legacy_action_exact_match"] == 0.0
    assert metrics["legacy_action_set_exact_match"] == 1.0
    assert metrics["legacy_route_micro_recall"] == 1.0
    assert metrics["retriever_mode_accuracy"] == 1.0
    assert metrics["single_transform_strategy_legal_rate"] == 1.0
    assert metrics["router_statuses"] == {"used_after_retry": 1}
    assert metrics["router_retry_count"] == 1
    assert metrics["router_validation_error_count"] == 1
    assert metrics["router_fallback_count"] == 0
    assert metrics["transformer_fallback_count"] == 0
    assert metrics["transformer_not_needed_count"] == 0


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


def test_policy_selected_metrics_use_each_predictions_planned_mode() -> None:
    details = [
        _detail("fact", "semantic_fact", "hybrid", hit=False, reciprocal_rank=0.0, latency_ms=5),
        _detail("fact", "semantic_fact", "hybrid_rerank", hit=True, reciprocal_rank=1.0, latency_ms=9),
        _detail("nav", "navigation", "bm25", hit=True, reciprocal_rank=0.5, latency_ms=2),
        _detail("nav", "navigation", "hybrid_rerank", hit=False, reciprocal_rank=0.0, latency_ms=9),
    ]
    predictions = [
        {"sample_id": "fact", "query_plan": {"retriever_mode": "hybrid_rerank"}},
        {"sample_id": "nav", "query_plan": {"retriever_mode": "bm25"}},
    ]

    metrics = _policy_selected_retrieval_metrics(details, predictions)

    assert metrics["eligible_sample_count"] == 2
    assert metrics["selected_sample_count"] == 2
    assert metrics["mode_counts"] == {"bm25": 1, "hybrid_rerank": 1}
    assert metrics["overall"]["recall_at_5_end_to_end"] == 1.0
    assert metrics["by_intent"]["semantic_fact"]["mrr_at_10"] == 1.0


def test_reranker_ablation_reports_hit_and_rank_transitions_by_intent() -> None:
    details = [
        _detail("fact", "semantic_fact", "hybrid", hit=False, reciprocal_rank=0.0, latency_ms=5),
        _detail("fact", "semantic_fact", "hybrid_rerank", hit=True, reciprocal_rank=0.5, latency_ms=9),
        _detail("complex", "complex_analysis", "hybrid", hit=True, reciprocal_rank=1.0, latency_ms=6),
        _detail("complex", "complex_analysis", "hybrid_rerank", hit=False, reciprocal_rank=0.0, latency_ms=10),
    ]

    report = _reranker_ablation(details)

    assert report["overall"]["sample_count"] == 2
    assert report["overall"]["hit_transitions"] == {
        "gained": 1,
        "lost": 1,
        "unchanged_hit": 0,
        "unchanged_miss": 0,
    }
    assert report["overall"]["rank_transitions"] == {
        "improved": 1,
        "equal": 0,
        "worsened": 1,
    }
    assert report["by_intent"]["semantic_fact"]["recall_at_5_delta"] == 1.0
    assert report["by_intent"]["complex_analysis"]["recall_at_5_delta"] == -1.0


def test_finalize_outputs_writes_v3_policy_and_ablation_contract(tmp_path) -> None:
    sample = _sample()
    prediction = _query_prediction(
        sample,
        {
            "query_decision": {
                "intent": "semantic_fact",
                "task_type": "fact_lookup",
                "evidence_types": ["text"],
                "multi_step": False,
                "requires_retrieval": True,
                "source": "llm",
            },
            "query_plan": {
                "actions": ["none"],
                "retrieval_queries": [sample["question"]],
                "preserved_terms": [],
                "retrieval_routes": ["dense", "sparse"],
                "retriever_mode": "hybrid_rerank",
                "transformation_source": "llm",
            },
            "trace": {
                "intent_router": {"status": "used", "attempt_count": 1},
                "query_transformer": {"status": "used", "attempt_count": 1},
            },
        },
        elapsed_ms=1.0,
    )
    mapping = {
        "sample_id": "S1",
        "groups": [{"group_id": "G1", "mapped_block_ids": ["gold"]}],
    }
    output_dir = tmp_path / "output"
    sync_dir = tmp_path / "sync"
    output_dir.mkdir()
    for name in ("query_predictions.jsonl", "gold_chunk_mapping.jsonl", "retrieval_details.jsonl"):
        (output_dir / name).write_text("\n", encoding="utf-8")
    args = SimpleNamespace(
        run_id="test-v3",
        router_model="router-model",
        dense_model_path="dense-model",
        reranker_model_path="reranker-model",
        top_k=10,
        sync_dir=str(sync_dir),
    )

    result = finalize_outputs(
        args=args,
        samples=[sample],
        predictions=[prediction],
        mappings=[mapping],
        details=[
            _detail("S1", "semantic_fact", "hybrid", hit=False, reciprocal_rank=0.0, latency_ms=5),
            _detail("S1", "semantic_fact", "hybrid_rerank", hit=True, reciprocal_rank=1.0, latency_ms=9),
        ],
        output_dir=output_dir,
    )

    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert result["status"] == "success"
    assert summary["runner_version"] == "m1-query-retrieval-eval-v3"
    assert summary["git_commit"]
    assert result["git_commit"] == summary["git_commit"]
    assert summary["metrics"]["policy_selected_retrieval"]["selected_sample_count"] == 1
    assert summary["metrics"]["reranker_ablation"]["overall"]["hit_transitions"]["gained"] == 1
    full_manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    sync_manifest = json.loads((sync_dir / "manifest.json").read_text(encoding="utf-8"))
    assert full_manifest["git_commit"] == summary["git_commit"]
    assert sync_manifest["git_commit"] == summary["git_commit"]
