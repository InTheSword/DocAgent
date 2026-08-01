from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docagent.query.pipeline import run_query_pipeline
from docagent.query.schemas import QueryPlan
from docagent.retrieval.dense_encoder import DenseEncoder, DenseEncoderConfig
from docagent.retrieval.dense_index import DenseIndex
from docagent.retrieval.hybrid_retriever import HybridRetriever
from docagent.retrieval.reranker import CrossEncoderReranker, CrossEncoderRerankerConfig
from docagent.router.llm_client import OpenAICompatibleRouterClient, load_router_llm_config
from docagent.schemas import Chunk
from docagent.utils.jsonl import read_jsonl, write_jsonl


RUNNER_VERSION = "m1-query-retrieval-eval-v3"
RETRIEVAL_MODES = ("bm25", "dense", "hybrid", "hybrid_rerank")
QUERY_VARIANTS = ("original", "planned")
TRANSFORM_ACTIONS = frozenset(
    {"none", "rewrite", "expand", "decompose", "request_clarification"}
)
GENERIC_RETRIEVAL_INTENTS = frozenset(
    {"semantic_fact", "navigation", "complex_analysis"}
)
INTENT_WORKFLOWS = {
    "semantic_fact": "text_retrieval",
    "navigation": "text_retrieval",
    "complex_analysis": "complex_text_retrieval",
    "table_lookup": "table_retrieval",
    "table_analysis": "table_retrieval",
    "visual_lookup": "visual_retrieval",
    "document_summary": "document_summary",
    "no_retrieval": "no_retrieval",
    "clarification_required": "clarification",
}
INTENT_RETRIEVER_MODES = {
    "semantic_fact": "hybrid_rerank",
    "navigation": "bm25",
    "complex_analysis": "hybrid_rerank",
    "table_lookup": "bm25",
    "table_analysis": "bm25",
    "visual_lookup": "hybrid",
    "document_summary": "none",
    "no_retrieval": "none",
    "clarification_required": "none",
}
REQUIRED_SAMPLE_FIELDS = {
    "sample_id",
    "document_file",
    "language",
    "question",
    "intent",
    "query_actions",
    "expected_routes",
    "must_preserve",
    "gold_evidence_groups",
}
EVIDENCE_TYPE_COMPATIBILITY = {
    "table": {"table"},
    "figure": {"image", "figure", "chart"},
    "heading": {"heading", "title"},
    "text": {"body", "text", "paragraph", "list_item", "caption", "reference"},
}


def load_samples(path: Path) -> list[dict[str, Any]]:
    samples = [dict(item) for item in read_jsonl(path)]
    validate_samples(samples)
    return samples


def validate_samples(samples: list[dict[str, Any]]) -> None:
    if not samples:
        raise ValueError("frozen sample file is empty")
    seen: set[str] = set()
    for row_number, sample in enumerate(samples, start=1):
        missing = REQUIRED_SAMPLE_FIELDS - set(sample)
        if missing:
            raise ValueError(f"sample row {row_number} missing fields: {sorted(missing)}")
        sample_id = str(sample["sample_id"])
        if not sample_id or sample_id in seen:
            raise ValueError(f"duplicate or empty sample_id: {sample_id!r}")
        seen.add(sample_id)
        for field_name in ("query_actions", "expected_routes", "must_preserve", "gold_evidence_groups"):
            if not isinstance(sample[field_name], list):
                raise ValueError(f"{sample_id}.{field_name} must be a list")
        document_file = sample.get("document_file")
        groups = sample["gold_evidence_groups"]
        if document_file and not groups:
            raise ValueError(f"{sample_id} is document-bound but has no gold evidence groups")
        if not document_file and groups:
            raise ValueError(f"{sample_id} has gold evidence without a document")
        for group in groups:
            if not isinstance(group, dict):
                raise ValueError(f"{sample_id}.gold_evidence_groups must contain objects")
            if not str(group.get("group_id") or "") or not str(group.get("verbatim_content") or ""):
                raise ValueError(f"{sample_id} contains an incomplete gold evidence group")
            pages = group.get("physical_pages")
            if not isinstance(pages, list) or any(
                isinstance(page, bool) or not isinstance(page, int) or page < 1
                for page in pages
            ):
                raise ValueError(f"{sample_id} contains invalid physical_pages")


def _transform_actions(actions: Iterable[object]) -> list[str]:
    normalized = [str(action) for action in actions if str(action) in TRANSFORM_ACTIONS]
    return normalized or ["none"]


def _workflow_for_intent(intent: object) -> str:
    return INTENT_WORKFLOWS.get(str(intent), "unknown")


def _retriever_mode_for_intent(intent: object) -> str:
    return INTENT_RETRIEVER_MODES.get(str(intent), "unknown")


def _generic_retrieval_samples(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        sample
        for sample in samples
        if sample.get("document_file") and sample.get("intent") in GENERIC_RETRIEVAL_INTENTS
    ]


def _workflow_coverage(samples: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    counts = Counter(
        _workflow_for_intent(sample.get("intent"))
        for sample in samples
        if sample.get("document_file")
    )
    return {
        workflow: {
            "sample_count": count,
            "evaluated_by_generic_retrieval_runner": workflow
            in {"text_retrieval", "complex_text_retrieval"},
        }
        for workflow, count in sorted(counts.items())
    }


def load_corpus(
    manifest_path: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[Chunk]]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = list(manifest.get("documents") or [])
    by_file: dict[str, dict[str, Any]] = {}
    blocks_by_doc: dict[str, list[Chunk]] = {}
    for document in documents:
        name = str(document.get("document_file") or "")
        doc_id = str(document.get("doc_id") or "")
        document_dir = _repo_path(str(document.get("document_dir") or ""))
        if not name or not doc_id or document_dir is None:
            raise ValueError("corpus manifest contains an incomplete document")
        chunks_path = document_dir / "evidence_blocks.jsonl"
        chunks = [Chunk.from_dict(item) for item in read_jsonl(chunks_path)]
        if not chunks:
            raise ValueError(f"document has no chunks: {name}")
        by_file[name] = {**document, "document_dir": str(document_dir)}
        blocks_by_doc[doc_id] = chunks
    return by_file, blocks_by_doc


def document_profile(chunks: list[Chunk]) -> dict[str, Any]:
    sample_text = " ".join(
        chunk.text
        for chunk in sorted(chunks, key=lambda item: (item.page_id or 0, item.block_id))[:20]
        if chunk.text
    )
    cjk = len(re.findall(r"[\u4e00-\u9fff]", sample_text))
    latin = len(re.findall(r"[A-Za-z]", sample_text))
    language = "unknown" if not cjk and not latin else "zh" if cjk * 2 >= latin else "en"
    return {
        "dominant_language": language,
        "has_tables": any(chunk.block_type == "table" for chunk in chunks),
        "has_images": any(chunk.block_type in {"image", "figure"} for chunk in chunks),
    }


def map_gold_evidence(
    samples: list[dict[str, Any]],
    documents_by_file: dict[str, dict[str, Any]],
    blocks_by_doc: dict[str, list[Chunk]],
) -> list[dict[str, Any]]:
    mapped_rows: list[dict[str, Any]] = []
    for sample in samples:
        document_file = sample.get("document_file")
        if not document_file:
            mapped_rows.append(
                {
                    "sample_id": sample["sample_id"],
                    "document_file": None,
                    "doc_id": None,
                    "groups": [],
                    "mapped_group_count": 0,
                    "group_count": 0,
                    "all_groups_mapped": True,
                    "qrels_reviewed": False,
                }
            )
            continue
        document = documents_by_file.get(str(document_file))
        if document is None:
            raise ValueError(f"sample document is absent from corpus manifest: {document_file}")
        doc_id = str(document["doc_id"])
        chunks = blocks_by_doc[doc_id]
        groups = [_map_one_group(group, chunks) for group in sample["gold_evidence_groups"]]
        mapped_count = sum(bool(group["mapped_block_ids"]) for group in groups)
        mapped_rows.append(
            {
                "sample_id": sample["sample_id"],
                "document_file": document_file,
                "doc_id": doc_id,
                "groups": groups,
                "mapped_group_count": mapped_count,
                "group_count": len(groups),
                "all_groups_mapped": mapped_count == len(groups),
                "qrels_reviewed": False,
            }
        )
    return mapped_rows


def _map_one_group(group: dict[str, Any], chunks: list[Chunk]) -> dict[str, Any]:
    evidence_type = str(group.get("evidence_type") or "").casefold()
    physical_pages = tuple(int(page) for page in group.get("physical_pages") or [])
    candidates = [
        chunk
        for chunk in chunks
        if chunk.is_indexable
        and _page_compatible(chunk, physical_pages)
        and _type_compatible(chunk, evidence_type)
    ]
    needle = _normalized_text(str(group["verbatim_content"]))
    compact_needle = _compact_text(str(group["verbatim_content"]))
    exact: list[str] = []
    compact: list[str] = []
    for chunk in candidates:
        haystack = _normalized_text(_chunk_match_text(chunk))
        compact_haystack = _compact_text(_chunk_match_text(chunk))
        if needle and (needle in haystack or (len(haystack) >= 24 and haystack in needle)):
            exact.append(chunk.block_id)
        elif (
            len(compact_needle) >= 16
            and (
                compact_needle in compact_haystack
                or (len(compact_haystack) >= 16 and compact_haystack in compact_needle)
            )
        ):
            compact.append(chunk.block_id)
    if exact:
        return _mapped_group(group, exact, "normalized_contains", 1.0)
    if compact:
        return _mapped_group(group, compact, "compact_contains", 0.95)

    best_chunk: Chunk | None = None
    best_score = 0.0
    for chunk in candidates:
        compact_haystack = _compact_text(_chunk_match_text(chunk))
        score = _character_coverage(compact_needle, compact_haystack)
        if score > best_score:
            best_chunk = chunk
            best_score = score
    if best_chunk is not None and best_score >= 0.65:
        return _mapped_group(group, [best_chunk.block_id], "page_type_character_coverage", best_score)
    return _mapped_group(group, [], "unmapped", best_score)


def _mapped_group(
    group: dict[str, Any],
    block_ids: list[str],
    method: str,
    score: float,
) -> dict[str, Any]:
    return {
        "group_id": str(group.get("group_id") or ""),
        "evidence_type": str(group.get("evidence_type") or ""),
        "physical_pages": list(group.get("physical_pages") or []),
        "source_locator": str(group.get("source_locator") or ""),
        "mapped_block_ids": sorted(set(block_ids)),
        "match_method": method,
        "match_score": round(float(score), 4),
        "qrel_candidate_status": "unreviewed" if block_ids else "unmapped",
        "mapping_origin": "automatic_source_alignment",
    }


def _page_compatible(chunk: Chunk, pages: tuple[int, ...]) -> bool:
    if not pages:
        return True
    source_pages = {
        int(page)
        for page in chunk.metadata.get("source_page_numbers") or []
        if isinstance(page, int) and not isinstance(page, bool)
    }
    if chunk.page_id is not None:
        source_pages.add(int(chunk.page_id))
    return bool(source_pages.intersection(pages))


def _type_compatible(chunk: Chunk, evidence_type: str) -> bool:
    allowed = EVIDENCE_TYPE_COMPATIBILITY.get(evidence_type)
    if not allowed:
        return True
    content_type = str(chunk.metadata.get("content_type") or chunk.block_type).casefold()
    block_type = str(chunk.block_type).casefold()
    if evidence_type == "text" and block_type == "text":
        return True
    if evidence_type == "heading" and (
        block_type == "heading" or content_type == "heading" or chunk.metadata.get("heading_role")
    ):
        return True
    return block_type in allowed or content_type in allowed


def _chunk_match_text(chunk: Chunk) -> str:
    metadata = chunk.metadata
    parts = [
        chunk.text,
        chunk.retrieval_text,
        chunk.visual_summary or "",
        str(metadata.get("table_markdown") or ""),
        str(metadata.get("table_context") or ""),
        str(metadata.get("table_caption") or ""),
        str(metadata.get("image_caption") or ""),
        str(metadata.get("summary") or ""),
    ]
    return "\n".join(part for part in parts if part)


def _normalized_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = normalized.translate(str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "—": "-", "–": "-"}))
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _compact_text(value: str) -> str:
    normalized = _normalized_text(value)
    return "".join(re.findall(r"[0-9a-z\u4e00-\u9fff]+", normalized))


def _character_coverage(needle: str, haystack: str) -> float:
    if not needle or not haystack:
        return 0.0
    match = SequenceMatcher(None, needle, haystack, autojunk=False).find_longest_match()
    return match.size / len(needle)


def run_query_stage(
    *,
    samples: list[dict[str, Any]],
    documents_by_file: dict[str, dict[str, Any]],
    blocks_by_doc: dict[str, list[Chunk]],
    env_file: Path,
    output_path: Path,
    resume: bool,
) -> list[dict[str, Any]]:
    config, warnings = load_router_llm_config(env_file=env_file, env={})
    if config is None:
        raise RuntimeError(f"router LLM is not configured: {warnings}")
    client = OpenAICompatibleRouterClient(config)
    existing = {
        str(item["sample_id"]): item
        for item in read_jsonl(output_path)
    } if resume and output_path.is_file() else {}
    predictions = dict(existing)
    for index, sample in enumerate(samples, start=1):
        sample_id = str(sample["sample_id"])
        if sample_id in predictions:
            continue
        document_file = sample.get("document_file")
        profile: dict[str, Any] = {}
        if document_file:
            document = documents_by_file[str(document_file)]
            profile = document_profile(blocks_by_doc[str(document["doc_id"])])
        started = time.perf_counter()
        output = run_query_pipeline(
            question=str(sample["question"]),
            document_profile=profile,
            llm_client=client,
            model_override=config.model,
            use_llm=True,
        )
        prediction = _query_prediction(sample, output.to_dict(), elapsed_ms=(time.perf_counter() - started) * 1000)
        predictions[sample_id] = prediction
        write_jsonl(output_path, [predictions[key] for key in sorted(predictions)])
        print(
            json.dumps(
                {
                    "event": "query_sample_finished",
                    "completed": len(predictions),
                    "total": len(samples),
                    "sample_id": sample_id,
                    "intent_match": prediction["intent_match"],
                    "transform_action_exact_match": prediction["transform_action_exact_match"],
                    "workflow_match": prediction["workflow_match"],
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
            flush=True,
        )
    return [predictions[str(sample["sample_id"])] for sample in samples]


def _query_prediction(
    sample: dict[str, Any],
    output: dict[str, Any],
    *,
    elapsed_ms: float,
) -> dict[str, Any]:
    decision = dict(output["query_decision"])
    plan = dict(output["query_plan"])
    expected_actions = list(sample["query_actions"])
    predicted_actions = list(plan["actions"])
    expected_transform_actions = _transform_actions(expected_actions)
    predicted_transform_actions = _transform_actions(predicted_actions)
    expected_routes = list(sample["expected_routes"])
    predicted_routes = list(plan["retrieval_routes"])
    expected_workflow = _workflow_for_intent(sample["intent"])
    predicted_workflow = _workflow_for_intent(decision["intent"])
    expected_retriever_mode = _retriever_mode_for_intent(sample["intent"])
    predicted_retriever_mode = str(plan.get("retriever_mode") or "unknown")
    strategy_actions = [
        str(action) for action in predicted_actions if str(action) in TRANSFORM_ACTIONS
    ]
    if decision.get("intent") == "no_retrieval":
        single_strategy_legal = not predicted_actions
    elif decision.get("intent") == "clarification_required":
        single_strategy_legal = strategy_actions == ["request_clarification"]
    else:
        single_strategy_legal = (
            len(strategy_actions) == 1 and len(strategy_actions) == len(predicted_actions)
        )
    trace = dict(output.get("trace") or {})
    router_trace = dict(trace.get("intent_router") or {})
    transformer_trace = dict(trace.get("query_transformer") or {})
    query_text = " ".join([*plan.get("retrieval_queries", []), *plan.get("preserved_terms", [])])
    preserved = [
        term
        for term in sample["must_preserve"]
        if _normalized_text(str(term)) in _normalized_text(query_text)
    ]
    return {
        "sample_id": sample["sample_id"],
        "document_file": sample.get("document_file"),
        "language": sample["language"],
        "expected_intent": sample["intent"],
        "predicted_intent": decision["intent"],
        "expected_actions": expected_actions,
        "predicted_actions": predicted_actions,
        "expected_transform_actions": expected_transform_actions,
        "predicted_transform_actions": predicted_transform_actions,
        "expected_routes": expected_routes,
        "predicted_routes": predicted_routes,
        "expected_workflow": expected_workflow,
        "predicted_workflow": predicted_workflow,
        "expected_retriever_mode": expected_retriever_mode,
        "predicted_retriever_mode": predicted_retriever_mode,
        "must_preserve_count": len(sample["must_preserve"]),
        "preserved_count": len(preserved),
        "intent_match": decision["intent"] == sample["intent"],
        "transform_action_exact_match": predicted_transform_actions == expected_transform_actions,
        "transform_action_set_match": set(predicted_transform_actions) == set(expected_transform_actions),
        "legacy_action_exact_match": predicted_actions == expected_actions,
        "legacy_action_set_match": set(predicted_actions) == set(expected_actions),
        "workflow_match": predicted_workflow == expected_workflow,
        "retriever_mode_match": predicted_retriever_mode == expected_retriever_mode,
        "single_transform_strategy_legal": single_strategy_legal,
        "required_routes_hit": set(expected_routes).issubset(predicted_routes),
        "route_hit_count": len(set(expected_routes).intersection(predicted_routes)),
        "must_preserve_all": len(preserved) == len(sample["must_preserve"]),
        "decision_source": decision.get("source"),
        "transformation_source": plan.get("transformation_source"),
        "router_status": str(router_trace.get("status") or "unknown"),
        "router_attempt_count": int(router_trace.get("attempt_count") or 0),
        "router_validation_error_count": len(router_trace.get("validation_errors") or []),
        "transformer_status": str(transformer_trace.get("status") or "unknown"),
        "transformer_attempt_count": int(transformer_trace.get("attempt_count") or 0),
        "transformer_validation_error_count": len(
            transformer_trace.get("validation_errors") or []
        ),
        "query_decision": decision,
        "query_plan": plan,
        "trace": output["trace"],
        "elapsed_ms": round(elapsed_ms, 3),
    }


def query_metrics(predictions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "overall": _query_metric_group(predictions),
        "by_language": _group_metrics(predictions, "language", _query_metric_group),
        "by_intent": _group_metrics(predictions, "expected_intent", _query_metric_group),
        "by_document": _group_metrics(predictions, "document_file", _query_metric_group),
    }


def _query_metric_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    expected_route_count = sum(len(set(row["expected_routes"])) for row in rows)
    must_preserve_count = sum(int(row["must_preserve_count"]) for row in rows)
    return {
        "sample_count": len(rows),
        "intent_accuracy": _rate(sum(bool(row["intent_match"]) for row in rows), len(rows)),
        "workflow_accuracy": _rate(sum(bool(row["workflow_match"]) for row in rows), len(rows)),
        "retriever_mode_accuracy": _rate(
            sum(bool(row.get("retriever_mode_match")) for row in rows), len(rows)
        ),
        "single_transform_strategy_legal_rate": _rate(
            sum(bool(row.get("single_transform_strategy_legal")) for row in rows), len(rows)
        ),
        "transform_action_exact_match": _rate(
            sum(bool(row["transform_action_exact_match"]) for row in rows), len(rows)
        ),
        "transform_action_set_exact_match": _rate(
            sum(bool(row["transform_action_set_match"]) for row in rows), len(rows)
        ),
        "legacy_action_exact_match": _rate(
            sum(bool(row["legacy_action_exact_match"]) for row in rows), len(rows)
        ),
        "legacy_action_set_exact_match": _rate(
            sum(bool(row["legacy_action_set_match"]) for row in rows), len(rows)
        ),
        "legacy_required_routes_all_hit_rate": _rate(
            sum(bool(row["required_routes_hit"]) for row in rows), len(rows)
        ),
        "legacy_route_micro_recall": _rate(
            sum(int(row["route_hit_count"]) for row in rows), expected_route_count
        ),
        "must_preserve_all_rate": _rate(sum(bool(row["must_preserve_all"]) for row in rows), len(rows)),
        "must_preserve_micro_recall": _rate(sum(int(row["preserved_count"]) for row in rows), must_preserve_count),
        "decision_sources": dict(sorted(Counter(str(row["decision_source"]) for row in rows).items())),
        "transformation_sources": dict(
            sorted(Counter(str(row["transformation_source"]) for row in rows).items())
        ),
        "router_statuses": dict(
            sorted(Counter(str(row.get("router_status") or "unknown") for row in rows).items())
        ),
        "transformer_statuses": dict(
            sorted(
                Counter(str(row.get("transformer_status") or "unknown") for row in rows).items()
            )
        ),
        "router_retry_count": sum(int(row.get("router_attempt_count") or 0) > 1 for row in rows),
        "transformer_retry_count": sum(
            int(row.get("transformer_attempt_count") or 0) > 1 for row in rows
        ),
        "router_validation_error_count": sum(
            int(row.get("router_validation_error_count") or 0) for row in rows
        ),
        "transformer_validation_error_count": sum(
            int(row.get("transformer_validation_error_count") or 0) for row in rows
        ),
        "mean_router_attempt_count": _mean(
            int(row.get("router_attempt_count") or 0) for row in rows
        ),
        "mean_transformer_attempt_count": _mean(
            int(row.get("transformer_attempt_count") or 0) for row in rows
        ),
    }


def run_retrieval_stage(
    *,
    samples: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    mappings: list[dict[str, Any]],
    documents_by_file: dict[str, dict[str, Any]],
    blocks_by_doc: dict[str, list[Chunk]],
    dense_model_path: Path,
    reranker_model_path: Path,
    device: str,
    top_k: int,
    output_path: Path,
) -> list[dict[str, Any]]:
    if top_k < 10:
        raise ValueError("top_k must be at least 10 for MRR@10")
    dense_encoder = DenseEncoder(
        DenseEncoderConfig(
            model_path=str(dense_model_path),
            device=device,
            use_fp16=device.startswith("cuda"),
            batch_size=8,
            max_length=1024,
        )
    )
    reranker = CrossEncoderReranker(
        CrossEncoderRerankerConfig(
            model_path=str(reranker_model_path),
            device=device,
            use_fp16=device.startswith("cuda"),
            batch_size=8,
            max_length=1024,
        )
    )
    prediction_by_id = {str(item["sample_id"]): item for item in predictions}
    mapping_by_id = {str(item["sample_id"]): item for item in mappings}
    document_samples = _generic_retrieval_samples(samples)
    query_texts: list[str] = []
    for sample in document_samples:
        prediction = prediction_by_id[str(sample["sample_id"])]
        query_texts.append(str(sample["question"]))
        query_texts.extend(str(item) for item in prediction["query_plan"].get("retrieval_queries") or [])
    unique_queries = list(dict.fromkeys(query_texts))
    vectors = dense_encoder.encode_queries(unique_queries)
    vector_by_query = {query: vectors[index] for index, query in enumerate(unique_queries)}

    retrievers: dict[tuple[str, str], HybridRetriever] = {}
    for doc_id, chunks in blocks_by_doc.items():
        indexable = [chunk for chunk in chunks if chunk.is_indexable]
        document_dir = Path(documents_by_file[_document_name_for_id(documents_by_file, doc_id)]["document_dir"])
        dense_index = DenseIndex.load(index_dir=document_dir, blocks=indexable)
        for mode in RETRIEVAL_MODES:
            retrievers[(doc_id, mode)] = HybridRetriever(
                chunks,
                dense_index=dense_index if mode != "bm25" else None,
                reranker=reranker if mode == "hybrid_rerank" else None,
                mode=mode,
                bm25_top_n=20,
                dense_top_n=20,
                fusion_top_n=20,
                rrf_k=60,
            )

    details: list[dict[str, Any]] = []
    for sample_index, sample in enumerate(document_samples, start=1):
        sample_id = str(sample["sample_id"])
        prediction = prediction_by_id[sample_id]
        mapping = mapping_by_id[sample_id]
        plan = QueryPlan.from_mapping(prediction["query_plan"])
        filters = plan.metadata_filter.to_retrieval_filter()
        query_intent = "table" if plan.intent in {"table_lookup", "table_analysis"} else None
        doc_id = str(mapping["doc_id"])
        for mode in RETRIEVAL_MODES:
            for variant in QUERY_VARIANTS:
                if variant == "original":
                    query_plan = None
                    query_embeddings = np.asarray([vector_by_query[str(sample["question"])]])
                else:
                    query_plan = plan if plan.retrieval_queries else None
                    query_embeddings = np.asarray(
                        [vector_by_query[query] for query in plan.retrieval_queries]
                    ) if plan.retrieval_queries else None
                started = time.perf_counter()
                if variant == "planned" and not plan.retrieval_queries:
                    ranking: list[str] = []
                    ranking_pages: list[int | None] = []
                    executed_routes: list[str] = []
                else:
                    result = retrievers[(doc_id, mode)].retrieve_result(
                        doc_id=doc_id,
                        question=str(sample["question"]),
                        top_k=top_k,
                        query_embedding=query_embeddings if mode != "bm25" else None,
                        query_plan=query_plan,
                        filters=filters,
                        query_intent=query_intent,
                        enable_query_rewrite=False,
                    )
                    ranking = [candidate.block.block_id for candidate in result.candidates]
                    ranking_pages = [candidate.block.page_id for candidate in result.candidates]
                    executed_routes = list(result.metadata.get("executed_routes") or [])
                detail = retrieval_detail(
                    sample=sample,
                    mapping=mapping,
                    mode=mode,
                    variant=variant,
                    ranking=ranking,
                    ranking_pages=ranking_pages,
                    planned_routes=list(plan.retrieval_routes) if variant == "planned" else [],
                    executed_routes=executed_routes,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
                details.append(detail)
        if sample_index % 5 == 0 or sample_index == len(document_samples):
            write_jsonl(output_path, details)
            print(
                json.dumps(
                    {
                        "event": "retrieval_progress",
                        "completed_samples": sample_index,
                        "total_samples": len(document_samples),
                        "detail_count": len(details),
                    }
                ),
                file=sys.stderr,
                flush=True,
            )
    write_jsonl(output_path, details)
    return details


def retrieval_detail(
    *,
    sample: dict[str, Any],
    mapping: dict[str, Any],
    mode: str,
    variant: str,
    ranking: list[str],
    ranking_pages: list[int | None],
    planned_routes: list[str],
    executed_routes: list[str],
    latency_ms: float,
) -> dict[str, Any]:
    groups = list(mapping["groups"])
    mapped_groups = [group for group in groups if group["mapped_block_ids"]]
    top5 = set(ranking[:5])
    covered_groups = [
        group
        for group in groups
        if set(group["mapped_block_ids"]).intersection(top5)
    ]
    covered_mapped_groups = [
        group
        for group in mapped_groups
        if set(group["mapped_block_ids"]).intersection(top5)
    ]
    all_gold_ids = {
        block_id
        for group in mapped_groups
        for block_id in group["mapped_block_ids"]
    }
    first_rank = next(
        (rank for rank, block_id in enumerate(ranking[:10], start=1) if block_id in all_gold_ids),
        None,
    )
    return {
        "sample_id": sample["sample_id"],
        "document_file": sample["document_file"],
        "doc_id": mapping["doc_id"],
        "language": sample["language"],
        "intent": sample["intent"],
        "workflow": _workflow_for_intent(sample["intent"]),
        "query_variant": variant,
        "retriever_mode": mode,
        "planned_routes": planned_routes,
        "executed_routes": executed_routes,
        "planned_routes_all_executed": set(planned_routes).issubset(executed_routes),
        "planned_route_count": len(set(planned_routes)),
        "executed_planned_route_count": len(set(planned_routes).intersection(executed_routes)),
        "ranking": ranking,
        "ranking_pages": ranking_pages,
        "group_count": len(groups),
        "mapped_group_count": len(mapped_groups),
        "covered_group_count_at_5": len(covered_groups),
        "covered_mapped_group_count_at_5": len(covered_mapped_groups),
        "recall_at_5_end_to_end": _rate(len(covered_groups), len(groups)),
        "recall_at_5_mapped_only": _rate(len(covered_mapped_groups), len(mapped_groups)),
        "reciprocal_rank_at_10": 1.0 / first_rank if first_rank else 0.0,
        "hit_at_5": bool(covered_groups),
        "all_groups_mapped": mapping["all_groups_mapped"],
        "latency_ms": round(latency_ms, 3),
    }


def retrieval_metrics(details: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"overall": {}}
    for variant in QUERY_VARIANTS:
        result["overall"][variant] = {}
        for mode in RETRIEVAL_MODES:
            rows = [
                row
                for row in details
                if row["query_variant"] == variant and row["retriever_mode"] == mode
            ]
            result["overall"][variant][mode] = _retrieval_metric_group(rows)
    for output_key, field_name in (
        ("by_language", "language"),
        ("by_intent", "intent"),
        ("by_document", "document_file"),
    ):
        grouped: dict[str, Any] = {}
        values = sorted({str(row[field_name]) for row in details})
        for value in values:
            grouped[value] = {}
            for variant in QUERY_VARIANTS:
                grouped[value][variant] = {}
                for mode in RETRIEVAL_MODES:
                    rows = [
                        row
                        for row in details
                        if str(row[field_name]) == value
                        and row["query_variant"] == variant
                        and row["retriever_mode"] == mode
                    ]
                    grouped[value][variant][mode] = _retrieval_metric_group(rows)
        result[output_key] = grouped
    return result


def _retrieval_metric_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    group_count = sum(int(row["group_count"]) for row in rows)
    mapped_count = sum(int(row["mapped_group_count"]) for row in rows)
    covered_count = sum(int(row["covered_group_count_at_5"]) for row in rows)
    covered_mapped_count = sum(int(row["covered_mapped_group_count_at_5"]) for row in rows)
    route_rows = [row for row in rows if int(row.get("planned_route_count") or 0) > 0]
    planned_route_count = sum(int(row["planned_route_count"]) for row in route_rows)
    latencies = sorted(float(row["latency_ms"]) for row in rows)
    return {
        "sample_count": len(rows),
        "gold_group_count": group_count,
        "mapped_gold_group_count": mapped_count,
        "gold_mapping_rate": _rate(mapped_count, group_count),
        "recall_at_5_end_to_end": _rate(covered_count, group_count),
        "recall_at_5_mapped_only": _rate(covered_mapped_count, mapped_count),
        "mrr_at_10": _mean(float(row["reciprocal_rank_at_10"]) for row in rows),
        "hit_rate_at_5": _rate(sum(bool(row["hit_at_5"]) for row in rows), len(rows)),
        "planned_routes_all_executed_rate": _rate(
            sum(bool(row["planned_routes_all_executed"]) for row in route_rows), len(route_rows)
        ),
        "planned_route_micro_realization": _rate(
            sum(int(row["executed_planned_route_count"]) for row in route_rows),
            planned_route_count,
        ),
        "mean_latency_ms": _mean(latencies),
        "p95_latency_ms": latencies[math.ceil(len(latencies) * 0.95) - 1] if latencies else 0.0,
    }


def _policy_selected_retrieval_metrics(
    details: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
) -> dict[str, Any]:
    planned_rows = [row for row in details if row["query_variant"] == "planned"]
    eligible_sample_ids = {str(row["sample_id"]) for row in planned_rows}
    planned_mode_by_id = {
        str(row["sample_id"]): str(row["query_plan"].get("retriever_mode") or "none")
        for row in predictions
    }
    selected = [
        row
        for row in planned_rows
        if row["retriever_mode"] == planned_mode_by_id.get(str(row["sample_id"]))
    ]
    return {
        "query_variant": "planned",
        "eligible_sample_count": len(eligible_sample_ids),
        "selected_sample_count": len(selected),
        "selection_coverage": _rate(len(selected), len(eligible_sample_ids)),
        "mode_counts": dict(sorted(Counter(str(row["retriever_mode"]) for row in selected).items())),
        "overall": _retrieval_metric_group(selected),
        "by_intent": _group_metrics(selected, "intent", _retrieval_metric_group),
    }


def _reranker_ablation(details: list[dict[str, Any]]) -> dict[str, Any]:
    planned_rows = [row for row in details if row["query_variant"] == "planned"]
    by_sample: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in planned_rows:
        by_sample[str(row["sample_id"])][str(row["retriever_mode"])] = row
    pairs = [
        (rows["hybrid"], rows["hybrid_rerank"])
        for rows in by_sample.values()
        if "hybrid" in rows and "hybrid_rerank" in rows
    ]
    grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for pair in pairs:
        grouped[str(pair[0]["intent"])].append(pair)
    return {
        "query_variant": "planned",
        "overall": _reranker_ablation_group(pairs),
        "by_intent": {
            intent: _reranker_ablation_group(grouped[intent]) for intent in sorted(grouped)
        },
    }


def _reranker_ablation_group(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    hybrid_rows = [pair[0] for pair in pairs]
    reranked_rows = [pair[1] for pair in pairs]
    hybrid_metrics = _retrieval_metric_group(hybrid_rows)
    reranked_metrics = _retrieval_metric_group(reranked_rows)
    hit_transitions = Counter()
    rank_transitions = Counter()
    for hybrid, reranked in pairs:
        hybrid_hit = bool(hybrid["hit_at_5"])
        reranked_hit = bool(reranked["hit_at_5"])
        if not hybrid_hit and reranked_hit:
            hit_transitions["gained"] += 1
        elif hybrid_hit and not reranked_hit:
            hit_transitions["lost"] += 1
        elif hybrid_hit:
            hit_transitions["unchanged_hit"] += 1
        else:
            hit_transitions["unchanged_miss"] += 1

        hybrid_rank = float(hybrid["reciprocal_rank_at_10"])
        reranked_rank = float(reranked["reciprocal_rank_at_10"])
        if reranked_rank > hybrid_rank:
            rank_transitions["improved"] += 1
        elif reranked_rank < hybrid_rank:
            rank_transitions["worsened"] += 1
        else:
            rank_transitions["equal"] += 1

    return {
        "sample_count": len(pairs),
        "hybrid": hybrid_metrics,
        "hybrid_rerank": reranked_metrics,
        "recall_at_5_delta": _rounded_delta(
            reranked_metrics["recall_at_5_end_to_end"],
            hybrid_metrics["recall_at_5_end_to_end"],
        ),
        "mapped_recall_at_5_delta": _rounded_delta(
            reranked_metrics["recall_at_5_mapped_only"],
            hybrid_metrics["recall_at_5_mapped_only"],
        ),
        "mrr_at_10_delta": _rounded_delta(
            reranked_metrics["mrr_at_10"], hybrid_metrics["mrr_at_10"]
        ),
        "hit_rate_at_5_delta": _rounded_delta(
            reranked_metrics["hit_rate_at_5"], hybrid_metrics["hit_rate_at_5"]
        ),
        "mean_latency_ms_delta": _rounded_delta(
            reranked_metrics["mean_latency_ms"], hybrid_metrics["mean_latency_ms"]
        ),
        "p95_latency_ms_delta": _rounded_delta(
            reranked_metrics["p95_latency_ms"], hybrid_metrics["p95_latency_ms"]
        ),
        "hit_transitions": {
            key: int(hit_transitions[key])
            for key in ("gained", "lost", "unchanged_hit", "unchanged_miss")
        },
        "rank_transitions": {
            key: int(rank_transitions[key]) for key in ("improved", "equal", "worsened")
        },
    }


def _rounded_delta(after: float, before: float) -> float:
    return round(float(after) - float(before), 6)


def build_failures(
    predictions: list[dict[str, Any]],
    mappings: list[dict[str, Any]],
    details: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for row in predictions:
        failed = [
            key
            for key in (
                "intent_match",
                "workflow_match",
                "transform_action_exact_match",
                "must_preserve_all",
                "retriever_mode_match",
                "single_transform_strategy_legal",
            )
            if not row.get(key)
        ]
        if failed:
            failures.append({"type": "query_contract", "sample_id": row["sample_id"], "failed_checks": failed})
    for row in mappings:
        unmapped = [
            group["group_id"]
            for group in row["groups"]
            if not group["mapped_block_ids"]
        ]
        if unmapped:
            failures.append({"type": "gold_mapping", "sample_id": row["sample_id"], "unmapped_group_ids": unmapped})
    for row in details:
        if (
            row["query_variant"] == "planned"
            and row["retriever_mode"] == "hybrid_rerank"
            and not row["hit_at_5"]
        ):
            failures.append(
                {
                    "type": "planned_hybrid_rerank_miss",
                    "sample_id": row["sample_id"],
                    "mapped_group_count": row["mapped_group_count"],
                    "group_count": row["group_count"],
                }
            )
        if (
            row["query_variant"] == "planned"
            and row["retriever_mode"] == "hybrid_rerank"
            and not row["planned_routes_all_executed"]
        ):
            failures.append(
                {
                    "type": "planned_route_not_executed",
                    "sample_id": row["sample_id"],
                    "planned_routes": row["planned_routes"],
                    "executed_routes": row["executed_routes"],
                }
            )
    return failures


def finalize_outputs(
    *,
    args: argparse.Namespace,
    samples: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    mappings: list[dict[str, Any]],
    details: list[dict[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    query_report = query_metrics(predictions)
    retrieval_report = retrieval_metrics(details)
    policy_selected_report = _policy_selected_retrieval_metrics(details, predictions)
    reranker_ablation_report = _reranker_ablation(details)
    failures = build_failures(predictions, mappings, details)
    mapping_groups = [group for row in mappings for group in row["groups"]]
    workflow_coverage = _workflow_coverage(samples)
    generic_samples = _generic_retrieval_samples(samples)
    generic_sample_ids = {str(sample["sample_id"]) for sample in generic_samples}
    generic_mapping_groups = [
        group
        for row in mappings
        if str(row["sample_id"]) in generic_sample_ids
        for group in row["groups"]
    ]
    generic_retrieval_sample_count = len(generic_samples)
    metrics = {
        "sample_count": len(samples),
        "document_bound_sample_count": sum(bool(sample.get("document_file")) for sample in samples),
        "generic_retrieval_sample_count": generic_retrieval_sample_count,
        "workflow_coverage": workflow_coverage,
        "gold_group_count": len(mapping_groups),
        "mapped_gold_group_count": sum(bool(group["mapped_block_ids"]) for group in mapping_groups),
        "gold_mapping_rate": _rate(
            sum(bool(group["mapped_block_ids"]) for group in mapping_groups),
            len(mapping_groups),
        ),
        "generic_retrieval_gold_group_count": len(generic_mapping_groups),
        "generic_retrieval_mapped_gold_group_count": sum(
            bool(group["mapped_block_ids"]) for group in generic_mapping_groups
        ),
        "generic_retrieval_gold_mapping_rate": _rate(
            sum(bool(group["mapped_block_ids"]) for group in generic_mapping_groups),
            len(generic_mapping_groups),
        ),
        "query": query_report,
        "retrieval": retrieval_report,
        "policy_selected_retrieval": policy_selected_report,
        "reranker_ablation": reranker_ablation_report,
    }
    summary = {
        "run_id": args.run_id,
        "runner_version": RUNNER_VERSION,
        "status": "success",
        "benchmark_status": "benchmark_evaluated",
        "formal_answer_quality_evaluation": False,
        "chunk_qrels_reviewed": False,
        "retrieval_metrics_provisional": True,
        "used_training": False,
        "validation_subset_used_for_training": False,
        "used_external_llm_api": True,
        "used_bge_m3": True,
        "used_reranker": True,
        "query_model": args.router_model,
        "dense_model_path": args.dense_model_path,
        "reranker_model_path": args.reranker_model_path,
        "top_k": args.top_k,
        "metrics": metrics,
        "limitations": [
            "Automatic source-to-chunk alignments are unreviewed qrel candidates, so retrieval metrics are provisional.",
            "Legacy action and route-label metrics are diagnostics; transform actions, preservation, workflow dispatch, and executed routes are reported separately.",
            "Generic retrieval metrics only cover semantic_fact, navigation, and the current static complex_analysis text workflow.",
            "Policy-selected retrieval uses each predicted QueryPlan.retriever_mode and does not replace the four fixed-mode ablations.",
            "Table, visual, summary, no-retrieval, and clarification workflows require separate evaluators.",
            "The evaluation covers retrieval and query planning, not final answer quality.",
        ],
    }
    (output_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_jsonl(output_dir / "failures.jsonl", failures)
    (output_dir / "summary.md").write_text(_summary_markdown(summary), encoding="utf-8")
    result = {
        "command": "eval_m1_query_retrieval",
        "status": "success",
        "artifact_paths": [
            str(output_dir / name)
            for name in (
                "query_predictions.jsonl",
                "gold_chunk_mapping.jsonl",
                "retrieval_details.jsonl",
                "metrics.json",
                "summary.json",
                "summary.md",
                "failures.jsonl",
                "manifest.json",
            )
        ],
        "metrics": {
            "sample_count": len(samples),
            "gold_mapping_rate": metrics["gold_mapping_rate"],
            "generic_retrieval_gold_mapping_rate": metrics["generic_retrieval_gold_mapping_rate"],
            "intent_accuracy": query_report["overall"]["intent_accuracy"],
            "workflow_accuracy": query_report["overall"]["workflow_accuracy"],
            "transform_action_exact_match": query_report["overall"]["transform_action_exact_match"],
            "retriever_mode_accuracy": query_report["overall"]["retriever_mode_accuracy"],
            "single_transform_strategy_legal_rate": query_report["overall"]["single_transform_strategy_legal_rate"],
            "policy_selected_recall_at_5": policy_selected_report["overall"]["recall_at_5_end_to_end"],
            "policy_selected_mrr_at_10": policy_selected_report["overall"]["mrr_at_10"],
            "planned_hybrid_rerank_recall_at_5": retrieval_report["overall"]["planned"]["hybrid_rerank"]["recall_at_5_end_to_end"],
            "planned_hybrid_rerank_mrr_at_10": retrieval_report["overall"]["planned"]["hybrid_rerank"]["mrr_at_10"],
            "planned_hybrid_rerank_route_realization": retrieval_report["overall"]["planned"]["hybrid_rerank"]["planned_route_micro_realization"],
        },
    }
    (output_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_manifest(output_dir, args.run_id)
    _write_sync_pack(output_dir, args.sync_dir, summary, result, failures)
    return result


def _summary_markdown(summary: dict[str, Any]) -> str:
    query = summary["metrics"]["query"]["overall"]
    retrieval = summary["metrics"]["retrieval"]["overall"]
    policy_selected = summary["metrics"]["policy_selected_retrieval"]
    reranker_ablation = summary["metrics"]["reranker_ablation"]
    lines = [
        "# M1 Query and Retrieval Frozen Baseline",
        "",
        f"- status: `{summary['status']}`",
        f"- samples: {summary['metrics']['sample_count']}",
        f"- generic retrieval samples: {summary['metrics']['generic_retrieval_sample_count']}",
        f"- gold mapping rate (all workflows): {summary['metrics']['gold_mapping_rate']:.4f}",
        f"- gold mapping rate (generic retrieval scope): {summary['metrics']['generic_retrieval_gold_mapping_rate']:.4f}",
        "- chunk qrels reviewed: `false` (metrics are provisional)",
        f"- intent accuracy: {query['intent_accuracy']:.4f}",
        f"- workflow accuracy: {query['workflow_accuracy']:.4f}",
        f"- retriever mode accuracy: {query['retriever_mode_accuracy']:.4f}",
        f"- single transform strategy legal rate: {query['single_transform_strategy_legal_rate']:.4f}",
        f"- transform action ordered EM: {query['transform_action_exact_match']:.4f}",
        f"- legacy action ordered EM: {query['legacy_action_exact_match']:.4f}",
        f"- legacy required-route labels all-hit: {query['legacy_required_routes_all_hit_rate']:.4f}",
        f"- router statuses: `{json.dumps(query['router_statuses'], ensure_ascii=False, sort_keys=True)}`",
        f"- transformer statuses: `{json.dumps(query['transformer_statuses'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "| Variant | Retriever | Recall@5 (E2E) | Recall@5 (mapped) | MRR@10 | Hit@5 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for variant in QUERY_VARIANTS:
        for mode in RETRIEVAL_MODES:
            row = retrieval[variant][mode]
            lines.append(
                f"| {variant} | {mode} | {row['recall_at_5_end_to_end']:.4f} | "
                f"{row['recall_at_5_mapped_only']:.4f} | {row['mrr_at_10']:.4f} | "
                f"{row['hit_rate_at_5']:.4f} |"
            )
    lines.extend(
        [
            "",
            "## Policy-selected planned retrieval",
            "",
            f"- selected/eligible samples: {policy_selected['selected_sample_count']}/{policy_selected['eligible_sample_count']}",
            f"- mode counts: `{json.dumps(policy_selected['mode_counts'], ensure_ascii=False, sort_keys=True)}`",
            f"- Recall@5 (E2E): {policy_selected['overall']['recall_at_5_end_to_end']:.4f}",
            f"- MRR@10: {policy_selected['overall']['mrr_at_10']:.4f}",
            "",
            "## Planned-query reranker ablation",
            "",
            "| Intent | Samples | Recall@5 delta | MRR@10 delta | Hit gained | Hit lost | Rank improved | Rank worsened | Mean latency delta (ms) |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for intent, row in reranker_ablation["by_intent"].items():
        lines.append(
            f"| {intent} | {row['sample_count']} | {row['recall_at_5_delta']:.4f} | "
            f"{row['mrr_at_10_delta']:.4f} | {row['hit_transitions']['gained']} | "
            f"{row['hit_transitions']['lost']} | {row['rank_transitions']['improved']} | "
            f"{row['rank_transitions']['worsened']} | {row['mean_latency_ms_delta']:.3f} |"
        )
    lines.extend(
        [
            "",
            "Table, visual, summary, no-retrieval, and clarification workflows are not included in the generic retrieval aggregate.",
            "No final-answer quality metric or training was run.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_manifest(output_dir: Path, run_id: str) -> None:
    names = [
        "query_predictions.jsonl",
        "gold_chunk_mapping.jsonl",
        "retrieval_details.jsonl",
        "metrics.json",
        "summary.json",
        "summary.md",
        "failures.jsonl",
        "result.json",
    ]
    payload = {
        "run_id": run_id,
        "runner_version": RUNNER_VERSION,
        "files": [
            {"path": name, "size": (output_dir / name).stat().st_size, "sha256": _sha256(output_dir / name)}
            for name in names
        ],
        "contains_secrets": False,
        "contains_training_data": False,
    }
    (output_dir / "manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_sync_pack(
    output_dir: Path,
    sync_dir_value: str,
    summary: dict[str, Any],
    result: dict[str, Any],
    failures: list[dict[str, Any]],
) -> None:
    sync_dir = _repo_path(sync_dir_value)
    if sync_dir is None:
        raise ValueError("sync_dir is required")
    sync_dir.mkdir(parents=True, exist_ok=True)
    compact_summary = json.loads(json.dumps(summary))
    compact_summary["metrics"]["query"].pop("by_document", None)
    compact_summary["metrics"]["retrieval"].pop("by_document", None)
    (sync_dir / "summary.json").write_text(
        json.dumps(compact_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (sync_dir / "summary.md").write_text((output_dir / "summary.md").read_text(encoding="utf-8"), encoding="utf-8")
    (sync_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_jsonl(sync_dir / "failures_sample.jsonl", failures[:50])
    preview = {
        "run_id": summary["run_id"],
        "query_metrics": summary["metrics"]["query"]["overall"],
        "retrieval_metrics": summary["metrics"]["retrieval"]["overall"],
    }
    (sync_dir / "preview.json").write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf-8")
    (sync_dir / "log_tail.txt").write_text("evaluation completed; see result.json and summary.json\n", encoding="utf-8")
    (sync_dir / "stderr_tail.txt").write_text("", encoding="utf-8")
    names = ["result.json", "summary.json", "summary.md", "preview.json", "failures_sample.jsonl", "log_tail.txt", "stderr_tail.txt"]
    manifest = {
        "run_id": summary["run_id"],
        "runner_version": RUNNER_VERSION,
        "files": [
            {"path": name, "size": (sync_dir / name).stat().st_size, "sha256": _sha256(sync_dir / name)}
            for name in names
        ],
        "contains_complete_questions": False,
        "contains_complete_evidence": False,
        "contains_secrets": False,
        "contains_model_weights": False,
        "contains_database": False,
    }
    (sync_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _group_metrics(
    rows: list[dict[str, Any]],
    field_name: str,
    summarizer,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(field_name) or "<none>")].append(row)
    return {key: summarizer(grouped[key]) for key in sorted(grouped)}


def _document_name_for_id(documents: dict[str, dict[str, Any]], doc_id: str) -> str:
    for name, document in documents.items():
        if str(document["doc_id"]) == doc_id:
            return name
    raise KeyError(doc_id)


def _repo_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _mean(values: Iterable[float]) -> float:
    items = list(values)
    return round(sum(items) / len(items), 6) if items else 0.0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the frozen M1 query and retrieval baseline.")
    parser.add_argument("--run-id", default="m1_query_retrieval_baseline_20260730")
    parser.add_argument("--stage", choices=("query", "retrieval", "all"), default="all")
    parser.add_argument("--samples", default="data/benchmark/m1_query_routing/frozen_query_samples.jsonl")
    parser.add_argument(
        "--corpus-manifest",
        default="outputs/m1_frozen_corpus_v1_20260730/document_manifest.json",
    )
    parser.add_argument("--output-dir", default="outputs/m1_query_retrieval_baseline_20260730")
    parser.add_argument("--sync-dir", default="outputs/sync/m1_query_retrieval_baseline_20260730")
    parser.add_argument("--router-env-file", default=".secrets/router_llm.env")
    parser.add_argument("--router-model", default="qwen3.7-max-2026-05-17")
    parser.add_argument("--dense-model-path", default="/root/autodl-tmp/models/bge-m3")
    parser.add_argument("--reranker-model-path", default="/root/autodl-tmp/models/bge-reranker-v2-m3")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    samples_path = _repo_path(args.samples)
    corpus_manifest_path = _repo_path(args.corpus_manifest)
    output_dir = _repo_path(args.output_dir)
    env_file = _repo_path(args.router_env_file)
    dense_model_path = _repo_path(args.dense_model_path)
    reranker_model_path = _repo_path(args.reranker_model_path)
    if None in (samples_path, corpus_manifest_path, output_dir, env_file, dense_model_path, reranker_model_path):
        raise ValueError("evaluation paths are incomplete")
    output_dir.mkdir(parents=True, exist_ok=True)
    samples = load_samples(samples_path)
    documents_by_file, blocks_by_doc = load_corpus(corpus_manifest_path)
    mappings = map_gold_evidence(samples, documents_by_file, blocks_by_doc)
    write_jsonl(output_dir / "gold_chunk_mapping.jsonl", mappings)
    predictions_path = output_dir / "query_predictions.jsonl"
    if args.stage in {"query", "all"}:
        predictions = run_query_stage(
            samples=samples,
            documents_by_file=documents_by_file,
            blocks_by_doc=blocks_by_doc,
            env_file=env_file,
            output_path=predictions_path,
            resume=not args.no_resume,
        )
    else:
        predictions = [dict(item) for item in read_jsonl(predictions_path)]
        if len(predictions) != len(samples):
            raise ValueError("query stage is incomplete")
    if args.stage == "query":
        result = {
            "command": "eval_m1_query_retrieval",
            "status": "success",
            "stage": "query",
            "artifact_paths": [str(predictions_path), str(output_dir / "gold_chunk_mapping.jsonl")],
            "metrics": query_metrics(predictions)["overall"],
        }
        (output_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        return 0
    details = run_retrieval_stage(
        samples=samples,
        predictions=predictions,
        mappings=mappings,
        documents_by_file=documents_by_file,
        blocks_by_doc=blocks_by_doc,
        dense_model_path=dense_model_path,
        reranker_model_path=reranker_model_path,
        device=args.device,
        top_k=args.top_k,
        output_path=output_dir / "retrieval_details.jsonl",
    )
    result = finalize_outputs(
        args=args,
        samples=samples,
        predictions=predictions,
        mappings=mappings,
        details=details,
        output_dir=output_dir,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
