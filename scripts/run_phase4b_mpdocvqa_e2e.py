from __future__ import annotations

import argparse
import gc
import json
import math
import shutil
import sqlite3
import sys
import time
import traceback
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.eval.answer_metrics import character_f1, exact_match, normalize_text, token_f1
from docagent.eval.phase3_focused import (
    DEFAULT_BGE_MODEL_PATH,
    DEFAULT_GRPO_ADAPTER_PATH,
    DEFAULT_QWEN_MODEL_PATH,
    DEFAULT_RERANKER_MODEL_PATH,
    build_answer_policy,
    build_dense_index_for_corpus,
    build_dense_resources,
    build_reranker,
    compare_metrics,
    fixed_evidence_hash,
    release_policy,
    safe_model_label,
)
from docagent.retrieval.bm25_index import BM25Index
from docagent.retrieval.dense_index import DenseIndex
from docagent.retrieval.fusion import reciprocal_rank_fusion
from docagent.schemas import EvidenceBlock
from docagent.storage.db import connect
from docagent.storage.repositories import TraceRepository
from docagent.utils.jsonl import read_jsonl, write_jsonl
from docagent.workflow.graph import run_qa_workflow


COMMAND = "run_phase4b_mpdocvqa_e2e"
PHASE = "Phase 4B"
GATE = "Gate 3"
EVALUATION_SCOPE = "mpdocvqa_raw_input_e2e_regression"
RETRIEVAL_SCOPE = "selected_document_window"
DEFAULT_DOC_IDS = [
    "hqvw0217__bc714cf4181a5632",
    "rzbj0037__e09400dd12a9c549",
    "jrcy0227__558596710c584b02",
]
DEFAULT_SAMPLE_ROOT = "outputs/phase4/mpdocvqa_raw_server_sample"
DEFAULT_INGESTION_ROOT = "outputs/phase4/mpdocvqa_ingestion"
DEFAULT_OUTPUT_ROOT = "outputs/evaluation/phase4b_mpdocvqa_e2e"


class Phase4BE2EError(RuntimeError):
    pass


@dataclass(frozen=True)
class PageRecord:
    doc_id: str
    source_doc_id: str
    parsed_page_number: int
    page_aggregate_id: str
    source_page_id: str
    child_block_ids: list[str]


@dataclass
class DocumentWindow:
    doc_id: str
    source_doc_id: str
    work_dir: Path
    internal_doc_dir: Path
    page_blocks: list[EvidenceBlock]
    child_blocks: list[EvidenceBlock]
    page_records: list[PageRecord]
    qa_mappings: list[dict[str, Any]]
    qa_records: list[dict[str, Any]]


def repo_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def _relative_posix(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.name if path.is_absolute() else path.as_posix()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _stage(message: str) -> None:
    print(f"[phase4b-gate3] {message}", file=sys.stderr, flush=True)


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _prepare_run_dir(output_root: Path, run_id: str, *, force: bool) -> Path:
    run_dir = output_root / run_id
    resolved = run_dir.resolve()
    if resolved in {Path(resolved.anchor), ROOT.resolve(), output_root.resolve()}:
        raise Phase4BE2EError(f"refusing to clean unsafe run directory: {run_dir}")
    if run_dir.exists():
        if not force:
            raise Phase4BE2EError(f"run directory already exists: {run_dir}; use --force")
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    return run_dir


def _find_internal_doc_dir(work_dir: Path) -> Path:
    document_root = work_dir / "documents"
    candidates = sorted(
        path
        for path in document_root.iterdir()
        if path.is_dir() and (path / "evidence_blocks.jsonl").is_file() and (path / "page_documents.jsonl").is_file()
    ) if document_root.is_dir() else []
    if len(candidates) != 1:
        raise Phase4BE2EError(f"expected one ingested document directory under {work_dir}, got {len(candidates)}")
    return candidates[0]


def _as_int(value: Any, *, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise Phase4BE2EError(f"{field} is not an integer") from exc


def _load_blocks(path: Path) -> list[EvidenceBlock]:
    return [EvidenceBlock.from_dict(record) for record in read_jsonl(path)]


def _doc_ids_from_file(path: Path) -> list[str]:
    if not path.is_file():
        raise Phase4BE2EError(f"doc id file missing: {path}")
    if path.suffix.lower() == ".jsonl":
        return [
            str(record.get("doc_id") or "").strip()
            for record in read_jsonl(path)
            if str(record.get("doc_id") or "").strip()
        ]
    payload = _read_json(path)
    if isinstance(payload, list):
        return [str(item).strip() for item in payload if str(item).strip()]
    if isinstance(payload, dict):
        values = payload.get("selected_window_ids") or payload.get("doc_ids") or payload.get("records")
        if isinstance(values, list):
            if values and isinstance(values[0], dict):
                return [
                    str(item.get("doc_id") or "").strip()
                    for item in values
                    if str(item.get("doc_id") or "").strip()
                ]
            return [str(item).strip() for item in values if str(item).strip()]
    raise Phase4BE2EError(f"unsupported doc id file format: {path}")


def _requested_doc_ids(args: argparse.Namespace) -> list[str]:
    doc_ids: list[str] = []
    if args.doc_id_file:
        doc_ids.extend(_doc_ids_from_file(repo_path(args.doc_id_file)))
    if args.doc_id:
        doc_ids.extend(args.doc_id)
    seen: set[str] = set()
    unique: list[str] = []
    for doc_id in doc_ids or DEFAULT_DOC_IDS:
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            unique.append(doc_id)
    return unique


def _load_document_window(
    *,
    doc_id: str,
    sample_root: Path,
    ingestion_root: Path,
) -> DocumentWindow:
    work_dir = ingestion_root / doc_id
    if not work_dir.is_dir():
        raise Phase4BE2EError(f"ingestion directory missing for doc_id={doc_id}")
    acceptance_path = work_dir / "acceptance_report.json"
    if not acceptance_path.is_file():
        raise Phase4BE2EError(f"acceptance_report.json missing for doc_id={doc_id}")
    acceptance = _read_json(acceptance_path)
    if acceptance.get("status") != "success" or acceptance.get("failures"):
        raise Phase4BE2EError(f"ingestion acceptance is not clean for doc_id={doc_id}")
    source_doc_id = str(acceptance.get("source_doc_id") or "")
    if not source_doc_id:
        raise Phase4BE2EError(f"source_doc_id missing in acceptance_report for doc_id={doc_id}")

    internal_doc_dir = _find_internal_doc_dir(work_dir)
    child_blocks = _load_blocks(internal_doc_dir / "evidence_blocks.jsonl")
    page_blocks = _load_blocks(internal_doc_dir / "page_documents.jsonl")
    page_identity_path = work_dir / "page_identity_mapping.jsonl"
    qa_mapping_path = work_dir / "qa_page_mapping.jsonl"
    if not page_identity_path.is_file() or not qa_mapping_path.is_file():
        raise Phase4BE2EError(f"Gate 2 mapping artifacts are missing for doc_id={doc_id}")
    page_identity = read_jsonl(page_identity_path)
    qa_mappings = read_jsonl(qa_mapping_path)
    if not all(record.get("mapping_valid") for record in qa_mappings):
        raise Phase4BE2EError(f"invalid QA page mapping for doc_id={doc_id}")
    if not all(record.get("mapping_valid") for record in page_identity):
        raise Phase4BE2EError(f"invalid page identity mapping for doc_id={doc_id}")

    page_records = [
        PageRecord(
            doc_id=doc_id,
            source_doc_id=source_doc_id,
            parsed_page_number=_as_int(record.get("parsed_page_number"), field="parsed_page_number"),
            page_aggregate_id=str(record.get("page_aggregate_id") or ""),
            source_page_id=str(record.get("source_page_id") or ""),
            child_block_ids=[str(item) for item in record.get("child_block_ids") or []],
        )
        for record in page_identity
    ]
    if len(page_records) != len(page_blocks):
        raise Phase4BE2EError(f"page_identity count does not match page_documents for doc_id={doc_id}")

    qa_path = sample_root / "qa.jsonl"
    if not qa_path.is_file():
        raise Phase4BE2EError("qa.jsonl missing under sample root")
    qa_records = [record for record in read_jsonl(qa_path) if record.get("doc_id") == doc_id]
    if len(qa_records) != len(qa_mappings):
        raise Phase4BE2EError(f"QA count does not match qa_page_mapping for doc_id={doc_id}")
    qa_by_qid = {str(record.get("qid")): record for record in qa_records}
    missing = [record.get("qid") for record in qa_mappings if str(record.get("qid")) not in qa_by_qid]
    if missing:
        raise Phase4BE2EError(f"qa_page_mapping references missing qids for doc_id={doc_id}: {missing}")

    return DocumentWindow(
        doc_id=doc_id,
        source_doc_id=source_doc_id,
        work_dir=work_dir,
        internal_doc_dir=internal_doc_dir,
        page_blocks=page_blocks,
        child_blocks=child_blocks,
        page_records=page_records,
        qa_mappings=qa_mappings,
        qa_records=qa_records,
    )


def load_gate3_inputs(args: argparse.Namespace) -> list[DocumentWindow]:
    sample_root = repo_path(args.sample_root)
    ingestion_root = repo_path(args.ingestion_root)
    doc_ids = _requested_doc_ids(args)
    windows = [
        _load_document_window(doc_id=doc_id, sample_root=sample_root, ingestion_root=ingestion_root)
        for doc_id in doc_ids
    ]
    qid_count = sum(len(window.qa_records) for window in windows)
    mapping_count = sum(len(window.qa_mappings) for window in windows)
    if qid_count != mapping_count:
        raise Phase4BE2EError("loaded QA count does not match mapping count")
    return windows


def _page_block_lookup(windows: list[DocumentWindow]) -> dict[str, EvidenceBlock]:
    return {block.block_id: block for window in windows for block in window.page_blocks}


def _child_block_lookup(windows: list[DocumentWindow]) -> dict[str, EvidenceBlock]:
    return {block.block_id: block for window in windows for block in window.child_blocks}


def _page_record_lookup(windows: list[DocumentWindow]) -> dict[str, PageRecord]:
    return {record.page_aggregate_id: record for window in windows for record in window.page_records}


def _qa_records_by_qid(windows: list[DocumentWindow]) -> dict[str, dict[str, Any]]:
    return {str(record.get("qid")): record for window in windows for record in window.qa_records}


def build_page_corpus(windows: list[DocumentWindow]) -> list[dict[str, Any]]:
    child_lookup = _child_block_lookup(windows)
    rows: list[dict[str, Any]] = []
    for window in windows:
        records_by_page = {record.page_aggregate_id: record for record in window.page_records}
        for page_block in sorted(window.page_blocks, key=lambda block: (block.page_id or 0, block.block_id)):
            record = records_by_page.get(page_block.block_id)
            if record is None:
                raise Phase4BE2EError(f"page block has no page identity record: {page_block.block_id}")
            child_blocks = [child_lookup[block_id] for block_id in record.child_block_ids if block_id in child_lookup]
            rows.append(
                {
                    "doc_id": window.doc_id,
                    "source_doc_id": window.source_doc_id,
                    "parsed_page_number": record.parsed_page_number,
                    "source_page_id": record.source_page_id,
                    "page_aggregate_id": page_block.block_id,
                    "page_text": page_block.retrieval_text,
                    "child_block_ids": list(record.child_block_ids),
                    "block_type_counts": dict(sorted(Counter(block.block_type for block in child_blocks).items())),
                }
            )
    return rows


def _qa_answer_list(record: dict[str, Any]) -> list[str]:
    answers = record.get("answers")
    if isinstance(answers, list):
        return [str(item) for item in answers]
    if answers:
        return [str(answers)]
    return []


def _first_rank(ranking: list[str], gold_id: str) -> int | None:
    try:
        return ranking.index(gold_id) + 1
    except ValueError:
        return None


def _retrieval_failure_taxonomy(gold_page_rank: int | None) -> list[str]:
    if gold_page_rank is None or gold_page_rank > 5:
        return ["retrieval_gold_miss_top5"]
    return []


def _mean(values: list[float]) -> float:
    return sum(values) / max(len(values), 1)


def _mean_bool(values: list[bool]) -> float:
    return sum(1 for value in values if value) / max(len(values), 1)


def _latency(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean_ms": 0.0, "max_ms": 0.0}
    return {"mean_ms": _mean(values), "max_ms": max(values)}


def summarize_page_retrieval(rows: list[dict[str, Any]], *, mode: str) -> dict[str, Any]:
    mode_rows = [row for row in rows if row["mode"] == mode]
    ranks = [row["gold_page_rank"] for row in mode_rows]
    latencies = [float(row["latency_ms"]) for row in mode_rows]
    by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_shard: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in mode_rows:
        by_doc[row["doc_id"]].append(row)
        by_shard[str(row.get("source_shard") or "unknown")].append(row)

    def _metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
        item_ranks = [item["gold_page_rank"] for item in items]
        return {
            "sample_count": len(items),
            "recall_at_1": _mean_bool([rank is not None and rank <= 1 for rank in item_ranks]),
            "recall_at_3": _mean_bool([rank is not None and rank <= 3 for rank in item_ranks]),
            "recall_at_5": _mean_bool([rank is not None and rank <= 5 for rank in item_ranks]),
            "mrr": sum((1.0 / rank) if rank else 0.0 for rank in item_ranks) / max(len(item_ranks), 1),
        }

    return {
        **_metrics(mode_rows),
        "mode": mode,
        "latency": _latency(latencies),
        "by_doc": {doc_id: _metrics(items) for doc_id, items in sorted(by_doc.items())},
        "by_shard": {shard: _metrics(items) for shard, items in sorted(by_shard.items())},
        "gold_page_ranks": [
            {"qid": row["qid"], "doc_id": row["doc_id"], "gold_page_rank": row["gold_page_rank"]}
            for row in mode_rows
        ],
    }


def _bm25_rank_pages(page_blocks: list[EvidenceBlock], query: str, *, top_n: int) -> list[tuple[EvidenceBlock, float]]:
    index = BM25Index(page_blocks)
    scored = [(block, float(index.score(query, idx))) for idx, block in enumerate(page_blocks)]
    scored.sort(key=lambda item: (-item[1], item[0].page_id or 0, item[0].block_id))
    return scored[: min(len(scored), top_n)]


def _hybrid_rank_pages(
    *,
    page_blocks: list[EvidenceBlock],
    query: str,
    dense_encoder: Any,
    dense_index: DenseIndex,
    reranker: Any,
    bm25_top_n: int,
    dense_top_n: int,
    fusion_top_n: int,
    rrf_k: int,
) -> list[Any]:
    bm25_hits = _bm25_rank_pages(page_blocks, query, top_n=min(len(page_blocks), bm25_top_n))
    query_embedding = dense_encoder.encode_queries([query])
    dense_hits = [
        (hit.block, float(hit.score))
        for hit in dense_index.search(query_embedding, top_k=len(dense_index.blocks))
        if hit.block.doc_id == page_blocks[0].doc_id
    ][:dense_top_n]
    candidates = reciprocal_rank_fusion({"bm25": bm25_hits, "dense": dense_hits}, rrf_k=rrf_k)[:fusion_top_n]
    for rank, candidate in enumerate(candidates, start=1):
        candidate.ranks["rrf"] = rank
    candidates = reranker.score(query=query, candidates=candidates)
    for rank, candidate in enumerate(candidates, start=1):
        candidate.ranks["reranker"] = rank
    return candidates


def _candidate_payload(candidate: Any, *, final_rank: int) -> dict[str, Any]:
    block = candidate.block
    return {
        "page_aggregate_id": block.block_id,
        "parsed_page_number": block.page_id,
        "final_rank": final_rank,
        "bm25_score": _json_float(candidate.bm25_score),
        "dense_score": _json_float(candidate.dense_score),
        "rrf_score": _json_float(candidate.rrf_score),
        "reranker_score": _json_float(candidate.rerank_score),
        "ranks": dict(candidate.ranks),
        "sources": list(candidate.sources),
    }


def _json_float(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _candidate_score(candidate: dict[str, Any]) -> float | None:
    for key in ("reranker_score", "rrf_score", "dense_score", "bm25_score"):
        if candidate.get(key) is not None:
            return _json_float(candidate.get(key))
    return None


def _candidate_top_page(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": candidate.get("final_rank"),
        "parsed_page_number": candidate.get("parsed_page_number"),
        "page_aggregate_id": candidate.get("page_aggregate_id"),
        "score": _candidate_score(candidate),
    }


def _top_pages(row: dict[str, Any]) -> list[dict[str, Any]]:
    return [_candidate_top_page(candidate) for candidate in row.get("candidates") or []]


def build_retrieval_preview(retrieval_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_qid: dict[str, dict[str, Any]] = defaultdict(dict)
    for row in retrieval_rows:
        qid = str(row.get("qid"))
        item = by_qid.setdefault(
            qid,
            {
                "qid": qid,
                "doc_id": row.get("doc_id"),
                "source_doc_id": row.get("source_doc_id"),
                "source_shard": row.get("source_shard"),
                "gold_parsed_page_number": row.get("gold_parsed_page_number"),
                "gold_page_aggregate_id": row.get("gold_page_aggregate_id"),
            },
        )
        mode = str(row.get("mode"))
        item[mode] = {
            "gold_page_rank": row.get("gold_page_rank"),
            "gold_page_in_top_k": row.get("gold_page_rank") is not None,
            "top_pages": _top_pages(row),
        }
    return [by_qid[qid] for qid in sorted(by_qid)]


def run_retrieval(
    *,
    windows: list[DocumentWindow],
    dense_encoder: Any,
    dense_index: DenseIndex,
    reranker: Any,
    top_k_pages: int,
    bm25_top_n: int,
    dense_top_n: int,
    fusion_top_n: int,
    rrf_k: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    qa_by_qid = _qa_records_by_qid(windows)
    page_lookup = _page_block_lookup(windows)
    page_ids_by_doc = {
        window.doc_id: [block.block_id for block in sorted(window.page_blocks, key=lambda item: item.page_id or 0)]
        for window in windows
    }
    for window in windows:
        page_blocks = sorted(window.page_blocks, key=lambda block: (block.page_id or 0, block.block_id))
        for mapping in sorted(window.qa_mappings, key=lambda item: str(item.get("qid"))):
            qid = str(mapping["qid"])
            qa = qa_by_qid[qid]
            question = str(qa.get("question") or "")
            source_shard = str(qa.get("source_shard") or "unknown")
            gold_page_id = str(mapping["page_aggregate_id"])
            gold_page_number = _as_int(mapping.get("parsed_page_number"), field=f"{qid}.parsed_page_number")
            started = time.perf_counter()
            bm25_hits = _bm25_rank_pages(page_blocks, question, top_n=max(bm25_top_n, top_k_pages))
            bm25_latency = (time.perf_counter() - started) * 1000
            bm25_ranking = [block.block_id for block, _score in bm25_hits[:top_k_pages]]
            rows.append(
                {
                    "qid": qid,
                    "doc_id": window.doc_id,
                    "source_doc_id": window.source_doc_id,
                    "source_shard": source_shard,
                    "question": question,
                    "mode": "bm25",
                    "retrieval_scope": RETRIEVAL_SCOPE,
                    "query_rewrite": "none",
                    "corpus_page_ids": page_ids_by_doc[window.doc_id],
                    "ranking": bm25_ranking,
                    "gold_page_aggregate_id": gold_page_id,
                    "gold_parsed_page_number": gold_page_number,
                    "gold_page_rank": _first_rank(bm25_ranking, gold_page_id),
                    "latency_ms": bm25_latency,
                    "candidates": [
                        {
                            "page_aggregate_id": block.block_id,
                            "parsed_page_number": block.page_id,
                            "final_rank": rank,
                            "bm25_score": _json_float(score),
                            "sources": ["bm25"],
                        }
                        for rank, (block, score) in enumerate(bm25_hits[:top_k_pages], start=1)
                    ],
                }
            )
            started = time.perf_counter()
            hybrid_candidates = _hybrid_rank_pages(
                page_blocks=page_blocks,
                query=question,
                dense_encoder=dense_encoder,
                dense_index=dense_index,
                reranker=reranker,
                bm25_top_n=bm25_top_n,
                dense_top_n=dense_top_n,
                fusion_top_n=fusion_top_n,
                rrf_k=rrf_k,
            )[:top_k_pages]
            hybrid_latency = (time.perf_counter() - started) * 1000
            hybrid_ranking = [candidate.block.block_id for candidate in hybrid_candidates]
            hybrid_gold_rank = _first_rank(hybrid_ranking, gold_page_id)
            rows.append(
                {
                    "qid": qid,
                    "doc_id": window.doc_id,
                    "source_doc_id": window.source_doc_id,
                    "source_shard": source_shard,
                    "question": question,
                    "mode": "hybrid",
                    "retrieval_scope": RETRIEVAL_SCOPE,
                    "query_rewrite": "none",
                    "corpus_page_ids": page_ids_by_doc[window.doc_id],
                    "ranking": hybrid_ranking,
                    "gold_page_aggregate_id": gold_page_id,
                    "gold_parsed_page_number": gold_page_number,
                    "gold_page_rank": hybrid_gold_rank,
                    "latency_ms": hybrid_latency,
                    "failure_taxonomy": _retrieval_failure_taxonomy(hybrid_gold_rank),
                    "candidates": [
                        _candidate_payload(candidate, final_rank=rank)
                        for rank, candidate in enumerate(hybrid_candidates, start=1)
                    ],
                }
            )
            if any(page_id not in page_ids_by_doc[window.doc_id] for page_id in hybrid_ranking):
                raise Phase4BE2EError(f"hybrid retrieval crossed document scope for qid={qid}")
            if gold_page_id not in page_lookup:
                raise Phase4BE2EError(f"gold page aggregate missing from corpus for qid={qid}")
    metrics = {
        "bm25": summarize_page_retrieval(rows, mode="bm25"),
        "hybrid": summarize_page_retrieval(rows, mode="hybrid"),
    }
    metrics["comparison"] = compare_metrics(
        metrics["hybrid"],
        metrics["bm25"],
        ["recall_at_1", "recall_at_3", "recall_at_5", "mrr"],
    )
    return rows, metrics


def release_retrieval_resources(dense_encoder: Any, reranker: Any) -> dict[str, bool]:
    if hasattr(dense_encoder, "_model"):
        setattr(dense_encoder, "_model", None)
    if hasattr(reranker, "_model"):
        setattr(reranker, "_model", None)
    if hasattr(reranker, "_tokenizer"):
        setattr(reranker, "_tokenizer", None)
    gc.collect()
    cuda_cache_cleared = False
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            cuda_cache_cleared = True
    except Exception:
        pass
    return {"retrieval_models_released": True, "cuda_cache_cleared": cuda_cache_cleared}


def _clone_block_with_context_metadata(
    block: EvidenceBlock,
    *,
    page_rank: int,
    parsed_page_number: int,
    page_aggregate_id: str,
) -> EvidenceBlock:
    payload = block.to_dict()
    metadata = dict(payload.get("metadata") or {})
    metadata.update(
        {
            "phase4b_context_source": "hybrid_page_retrieval",
            "retrieval_scope": RETRIEVAL_SCOPE,
            "retrieval_rank": page_rank,
            "parsed_page_number": parsed_page_number,
            "page_aggregate_id": page_aggregate_id,
            "retrieval_page_rank": page_rank,
            "retrieval_parsed_page_number": parsed_page_number,
            "retrieval_page_aggregate_id": page_aggregate_id,
        }
    )
    payload["metadata"] = metadata
    return EvidenceBlock.from_dict(payload)


def build_fixed_evidence(
    *,
    windows: list[DocumentWindow],
    retrieval_rows: list[dict[str, Any]],
    max_context_blocks: int,
) -> tuple[list[dict[str, Any]], dict[str, list[EvidenceBlock]]]:
    child_lookup = _child_block_lookup(windows)
    page_record_lookup = _page_record_lookup(windows)
    qa_by_qid = _qa_records_by_qid(windows)
    hybrid_rows = {row["qid"]: row for row in retrieval_rows if row["mode"] == "hybrid"}
    records: list[dict[str, Any]] = []
    evidence_by_qid: dict[str, list[EvidenceBlock]] = {}
    for qid, row in sorted(hybrid_rows.items()):
        blocks: list[EvidenceBlock] = []
        selected_pages: list[dict[str, Any]] = []
        for page_rank, candidate in enumerate(row["candidates"], start=1):
            page_id = str(candidate["page_aggregate_id"])
            page_record = page_record_lookup[page_id]
            selected_pages.append(
                {
                    "rank": page_rank,
                    "retrieval_rank": page_rank,
                    "page_aggregate_id": page_id,
                    "parsed_page_number": page_record.parsed_page_number,
                    "child_block_count": len(page_record.child_block_ids),
                    "child_block_ids": list(page_record.child_block_ids),
                }
            )
            child_blocks = [
                child_lookup[block_id]
                for block_id in page_record.child_block_ids
                if block_id in child_lookup
            ]
            child_blocks.sort(key=lambda block: (int(block.metadata.get("reading_order", 0)), block.block_id))
            for block in child_blocks:
                blocks.append(
                    _clone_block_with_context_metadata(
                        block,
                        page_rank=page_rank,
                        parsed_page_number=page_record.parsed_page_number,
                        page_aggregate_id=page_id,
                    )
                )
        truncated = len(blocks) > max_context_blocks
        selected_blocks = blocks[:max_context_blocks]
        evidence_by_qid[qid] = selected_blocks
        qa = qa_by_qid[qid]
        records.append(
            {
                "qid": qid,
                "doc_id": row["doc_id"],
                "source_doc_id": row["source_doc_id"],
                "question": qa.get("question"),
                "retrieval_scope": RETRIEVAL_SCOPE,
                "query_rewrite": "none",
                "selected_pages": selected_pages,
                "max_context_blocks": max_context_blocks,
                "truncation_applied": truncated,
                "dropped_block_count": max(len(blocks) - len(selected_blocks), 0),
                "evidence": [block.to_dict() for block in selected_blocks],
            }
        )
    return records, evidence_by_qid


FORBIDDEN_CONTEXT_KEYS = {"answer_page_idx", "answers", "gold_page_id", "gold_page_ordinal", "gold_parsed_page_number"}


def _gold_leakage_hits(value: Any, *, path: str = "fixed_evidence") -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            next_path = f"{path}.{key_text}"
            if lowered.startswith("gold") or lowered in FORBIDDEN_CONTEXT_KEYS:
                hits.append(next_path)
            hits.extend(_gold_leakage_hits(item, path=next_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            hits.extend(_gold_leakage_hits(item, path=f"{path}[{index}]"))
    return hits


def assert_no_gold_leakage(records: list[dict[str, Any]]) -> None:
    hits = _gold_leakage_hits(records)
    if hits:
        raise Phase4BE2EError(f"fixed evidence contains gold leakage keys: {hits[:5]}")


def _score_answer(prediction: str, answers: list[str]) -> dict[str, Any]:
    return {
        "normalized_exact_match": any(exact_match(prediction, answer) for answer in answers),
        "answer_hit": any(normalize_text(answer) in normalize_text(prediction) for answer in answers if normalize_text(answer)),
        "token_f1": max([token_f1(prediction, answer) for answer in answers] or [0.0]),
        "character_f1": max([character_f1(prediction, answer) for answer in answers] or [0.0]),
    }


def _answer_failure_taxonomy(
    *,
    scores: dict[str, Any],
    valid_json: bool,
    format_valid: bool,
    location_valid: bool,
    gold_page_location_hit: bool,
    final_location_in_evidence: bool,
) -> list[str]:
    labels: list[str] = []
    if not valid_json:
        labels.append("invalid_json")
    if not format_valid:
        labels.append("format_invalid")
    if not location_valid:
        labels.append("location_invalid")
    if not scores["answer_hit"]:
        labels.append("answer_miss")
    if not gold_page_location_hit:
        labels.append("gold_page_location_miss")
    if not final_location_in_evidence:
        labels.append("location_outside_selected_evidence")
    return labels


def _compact_id_list(values: list[str], *, edge: int = 3) -> dict[str, Any]:
    ordered = list(values)
    if len(ordered) <= edge * 2:
        return {"count": len(ordered), "first": ordered, "last": []}
    return {"count": len(ordered), "first": ordered[:edge], "last": ordered[-edge:]}


def _model_answer(row: dict[str, Any]) -> str | None:
    prediction = row.get("prediction")
    if isinstance(prediction, dict) and prediction.get("answer") is not None:
        return str(prediction.get("answer"))
    canonical = row.get("canonical_output")
    if isinstance(canonical, dict) and canonical.get("answer") is not None:
        return str(canonical.get("answer"))
    if row.get("model_answer") is not None:
        return str(row.get("model_answer"))
    return None


def _prediction_location(row: dict[str, Any]) -> dict[str, Any]:
    prediction = row.get("prediction")
    if isinstance(prediction, dict) and isinstance(prediction.get("evidence_location"), dict):
        return prediction["evidence_location"]
    canonical = row.get("canonical_output")
    if isinstance(canonical, dict) and isinstance(canonical.get("evidence_location"), dict):
        return canonical["evidence_location"]
    return {}


def build_answer_results_preview(answer_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preview: list[dict[str, Any]] = []
    for row in answer_rows:
        location = _prediction_location(row)
        preview.append(
            {
                "qid": row.get("qid"),
                "doc_id": row.get("doc_id"),
                "source_shard": row.get("source_shard"),
                "status": row.get("status"),
                "model_answer": _model_answer(row),
                "predicted_page": location.get("page"),
                "predicted_block_id": location.get("block_id"),
                "gold_parsed_page_number": (row.get("gold") or {}).get("parsed_page_number"),
                "answer_hit": (row.get("answer_metrics") or {}).get("answer_hit"),
                "gold_page_location_hit": (row.get("validation") or {}).get("gold_page_location_hit"),
                "page_location_hit": (row.get("validation") or {}).get("page_location_hit"),
                "block_location_hit": (row.get("validation") or {}).get("block_location_hit"),
                "failure_taxonomy": list(row.get("failure_taxonomy") or []),
            }
        )
    return preview


def build_failure_cases(
    *,
    answer_rows: list[dict[str, Any]],
    retrieval_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    preview_by_qid = {record["qid"]: record for record in build_retrieval_preview(retrieval_rows)}
    cases: list[dict[str, Any]] = []
    for row in retrieval_rows:
        taxonomy = list(row.get("failure_taxonomy") or [])
        if not taxonomy or row.get("mode") != "hybrid":
            continue
        cases.append(
            {
                "qid": row.get("qid"),
                "doc_id": row.get("doc_id"),
                "source_shard": row.get("source_shard"),
                "status": "retrieval_failed",
                "failure_taxonomy": taxonomy,
                "gold": {
                    "parsed_page_number": row.get("gold_parsed_page_number"),
                    "page_aggregate_id": row.get("gold_page_aggregate_id"),
                },
                "gold_page_rank": row.get("gold_page_rank"),
                "gold_page_in_top_k": row.get("gold_page_rank") is not None,
                "selected_top_pages": _top_pages(row),
                "evidence_block_ids": _compact_id_list([]),
                "answer_metrics": {},
                "validation": {},
            }
        )
    for row in answer_rows:
        taxonomy = list(row.get("failure_taxonomy") or [])
        if not taxonomy:
            continue
        retrieval = preview_by_qid.get(str(row.get("qid")), {})
        hybrid = retrieval.get("hybrid") or {}
        evidence_ids = [str(item) for item in row.get("evidence_block_ids") or []]
        cases.append(
            {
                "qid": row.get("qid"),
                "doc_id": row.get("doc_id"),
                "source_shard": row.get("source_shard"),
                "status": row.get("status"),
                "failure_taxonomy": taxonomy,
                "model_answer": _model_answer(row),
                "predicted_location": _prediction_location(row),
                "gold": row.get("gold") or {},
                "gold_page_rank": hybrid.get("gold_page_rank"),
                "gold_page_in_top_k": bool(hybrid.get("gold_page_in_top_k")),
                "selected_top_pages": hybrid.get("top_pages") or [],
                "evidence_block_ids": _compact_id_list(evidence_ids),
                "answer_metrics": row.get("answer_metrics") or {},
                "validation": row.get("validation") or {},
            }
        )
    return cases


def summarize_answer_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def _metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
        completed = [row for row in items if row.get("status") == "completed"]
        latencies = [float(row.get("latency_ms") or 0.0) for row in completed]
        page_location_hit = _mean_bool([row["validation"]["gold_page_location_hit"] for row in completed])
        return {
            "sample_count": len(items),
            "completed_count": len(completed),
            "failed_count": len(items) - len(completed),
            "normalized_exact_match": _mean_bool([row["answer_metrics"]["normalized_exact_match"] for row in completed]),
            "answer_hit": _mean_bool([row["answer_metrics"]["answer_hit"] for row in completed]),
            "token_f1": _mean([float(row["answer_metrics"]["token_f1"]) for row in completed]),
            "character_f1": _mean([float(row["answer_metrics"]["character_f1"]) for row in completed]),
            "valid_json_rate": _mean_bool([row["validation"]["valid_json"] for row in completed]),
            "format_valid_rate": _mean_bool([row["validation"]["format_valid"] for row in completed]),
            "gold_page_location_hit": page_location_hit,
            "page_location_hit": page_location_hit,
            "block_location_hit": _mean_bool([row["validation"].get("block_location_hit", False) for row in completed]),
            "final_location_in_evidence_rate": _mean_bool(
                [row["validation"]["final_location_in_evidence"] for row in completed]
            ),
            "repair_attempted_rate": _mean_bool([row["validation"]["repair_attempted"] for row in completed]),
            "repair_success_rate": _mean_bool([row["validation"]["repair_success"] for row in completed]),
            "latency": _latency(latencies),
        }

    by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_shard: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_doc[str(row.get("doc_id") or "unknown")].append(row)
        by_shard[str(row.get("source_shard") or "unknown")].append(row)
    summary = _metrics(rows)
    summary["by_doc"] = {doc_id: _metrics(items) for doc_id, items in sorted(by_doc.items())}
    summary["by_shard"] = {shard: _metrics(items) for shard, items in sorted(by_shard.items())}
    return summary


def _trace_counts(sqlite_path: Path) -> dict[str, int]:
    if not sqlite_path.is_file():
        return {"qa_runs": 0, "tool_traces": 0}
    with sqlite3.connect(sqlite_path) as conn:
        qa_runs = conn.execute("SELECT COUNT(*) FROM qa_runs").fetchone()[0]
        traces = conn.execute("SELECT COUNT(*) FROM tool_traces").fetchone()[0]
    return {"qa_runs": int(qa_runs), "tool_traces": int(traces)}


def run_answer_phase(
    *,
    windows: list[DocumentWindow],
    fixed_evidence_by_qid: dict[str, list[EvidenceBlock]],
    answer_policy: Any,
    sqlite_path: Path,
    max_prompt_tokens: int,
    rank_aware_context: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    conn = connect(sqlite_path)
    repository = TraceRepository(conn)
    qa_by_qid = _qa_records_by_qid(windows)
    mappings = {
        str(mapping["qid"]): mapping
        for window in windows
        for mapping in window.qa_mappings
    }
    rows: list[dict[str, Any]] = []
    try:
        for qid in sorted(fixed_evidence_by_qid):
            qa = qa_by_qid[qid]
            mapping = mappings[qid]
            evidence_blocks = fixed_evidence_by_qid[qid]
            started = time.perf_counter()
            try:
                state = run_qa_workflow(
                    qid=qid,
                    question=str(qa.get("question") or ""),
                    blocks=evidence_blocks,
                    answer_policy=answer_policy,
                    top_k=len(evidence_blocks),
                    answer_type_hint=str(qa.get("answer_type") or "extractive"),
                    doc_id=str(qa.get("doc_id") or ""),
                    trace_repository=repository,
                    preserve_input_order=True,
                    rank_aware_context=rank_aware_context,
                )
                elapsed = (time.perf_counter() - started) * 1000
                prediction = state.final_answer if isinstance(state.final_answer, dict) else {}
                pred_answer = str(prediction.get("answer") or "")
                scores = _score_answer(pred_answer, _qa_answer_list(qa))
                location = prediction.get("evidence_location") or {}
                selected_block_ids = {block.block_id for block in evidence_blocks}
                selected_pages = {block.page_id for block in evidence_blocks if block.page_id is not None}
                location_page = location.get("page")
                location_block_id = location.get("block_id")
                gold_page = _as_int(mapping.get("parsed_page_number"), field=f"{qid}.parsed_page_number")
                block_location_hit = bool(location_block_id and location_block_id in selected_block_ids)
                final_location_in_evidence = bool(
                    block_location_hit
                    or (location_page in selected_pages)
                )
                valid_json = bool(state.parse_result.get("raw_json_ok") or state.parse_result.get("schema_ok") or state.draft_answer)
                format_valid = bool(state.format_check.get("success"))
                location_valid = bool(state.location_check.get("success"))
                gold_page_location_hit = location_page == gold_page
                page_location_hit = gold_page_location_hit
                repair_success = bool(
                    state.repair_attempted
                    and state.format_check.get("success")
                    and state.location_check.get("success")
                )
                rows.append(
                    {
                        "qid": qid,
                        "doc_id": qa.get("doc_id"),
                        "source_doc_id": qa.get("source_doc_id"),
                        "source_shard": qa.get("source_shard"),
                        "question": qa.get("question"),
                        "status": "completed",
                        "prediction": prediction,
                        "answers": _qa_answer_list(qa),
                        "answer_metrics": scores,
                        "validation": {
                            "valid_json": valid_json,
                            "format_valid": format_valid,
                            "location_valid": location_valid,
                            "gold_page_location_hit": gold_page_location_hit,
                            "page_location_hit": page_location_hit,
                            "block_location_hit": block_location_hit,
                            "final_location_in_evidence": final_location_in_evidence,
                            "repair_attempted": bool(state.repair_attempted),
                            "repair_success": repair_success,
                        },
                        "gold": {
                            "parsed_page_number": gold_page,
                            "page_aggregate_id": mapping.get("page_aggregate_id"),
                        },
                        "evidence_block_ids": sorted(selected_block_ids),
                        "run_id": state.run_id,
                        "latency_ms": elapsed,
                        "generation_latency_ms": state.generation_metadata.get("latency_ms"),
                        "max_prompt_tokens": max_prompt_tokens,
                        "failure_taxonomy": _answer_failure_taxonomy(
                            scores=scores,
                            valid_json=valid_json,
                            format_valid=format_valid,
                            location_valid=location_valid,
                            gold_page_location_hit=gold_page_location_hit,
                            final_location_in_evidence=final_location_in_evidence,
                        ),
                    }
                )
            except Exception as exc:
                rows.append(
                    {
                        "qid": qid,
                        "doc_id": qa.get("doc_id"),
                        "source_shard": qa.get("source_shard"),
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                        "traceback_tail": traceback.format_exc().splitlines()[-12:],
                        "failure_taxonomy": ["generation_failed"],
                    }
                )
    finally:
        conn.close()
    return rows, summarize_answer_rows(rows)


def _failure_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(row.get("failure_taxonomy") or [])
    return dict(sorted(counts.items()))


def write_summary_md(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Phase 4B MP-DocVQA E2E Summary",
        "",
        f"- Evaluation scope: {summary['evaluation_scope']}",
        f"- Formal benchmark: {str(summary['formal_benchmark']).lower()}",
        f"- Retrieval scope: {summary['retrieval_scope']}",
        f"- Documents/pages/QA: {summary['document_count']}/{summary['page_count']}/{summary['qa_count']}",
        f"- BM25 Recall@1: {summary['page_retrieval_metrics']['bm25']['recall_at_1']:.4f}",
        f"- Hybrid Recall@1: {summary['page_retrieval_metrics']['hybrid']['recall_at_1']:.4f}",
        f"- Answer completed: {summary['answer_metrics'].get('completed_count', 0)}/{summary['answer_metrics'].get('sample_count', 0)}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _artifact_paths(run_dir: Path, paths: dict[str, Path]) -> dict[str, str]:
    return {key: _relative_posix(path, run_dir) for key, path in paths.items()}


def validate_only_payload(args: argparse.Namespace, windows: list[DocumentWindow]) -> dict[str, Any]:
    page_corpus = build_page_corpus(windows)
    return {
        "command": COMMAND,
        "status": "success",
        "phase": PHASE,
        "gate": GATE,
        "validate_only": True,
        "document_count": len(windows),
        "page_count": len(page_corpus),
        "qa_count": sum(len(window.qa_records) for window in windows),
        "gold_page_mapping_valid_count": sum(len(window.qa_mappings) for window in windows),
        "retrieval_scope": RETRIEVAL_SCOPE,
        "models_loaded": False,
        "warnings": [],
        "failures": [],
    }


def build_run_manifest(args: argparse.Namespace, *, run_id: str, windows: list[DocumentWindow]) -> dict[str, Any]:
    return {
        "command": COMMAND,
        "phase": PHASE,
        "gate": GATE,
        "run_id": run_id,
        "evaluation_scope": EVALUATION_SCOPE,
        "formal_benchmark": False,
        "primary_benchmark": False,
        "retrieval_scope": RETRIEVAL_SCOPE,
        "query_rewrite": "none",
        "doc_ids": [window.doc_id for window in windows],
        "top_k_pages": args.top_k_pages,
        "max_context_blocks": args.max_context_blocks,
        "max_prompt_tokens": args.max_prompt_tokens,
        "max_new_tokens": args.max_new_tokens,
        "rank_aware_context": bool(args.rank_aware_context),
        "retrieval": {
            "baseline": "bm25",
            "candidate": "bm25_bge_m3_rrf_reranker" if args.dense_backend == "bge" else "bm25_hash_rrf_keyword",
            "dense_backend": args.dense_backend,
            "dense_model": safe_model_label(args.dense_model_path),
            "reranker_backend": args.reranker_backend,
            "reranker_model": safe_model_label(args.reranker_model_path),
            "bm25_top_n": args.bm25_top_n,
            "dense_top_n": args.dense_top_n,
            "fusion_top_n": args.fusion_top_n,
            "rrf_k": args.rrf_k,
        },
        "answer_policy": {
            "backend": args.answer_backend,
            "mode": args.answer_mode,
            "base_model": safe_model_label(args.base_model_path),
            "adapter": safe_model_label(args.adapter_path),
            "device": args.qwen_device,
            "torch_dtype": args.qwen_torch_dtype,
        },
    }


def run_phase4b_e2e(args: argparse.Namespace) -> dict[str, Any]:
    if args.validate_only and args.retrieval_only:
        raise Phase4BE2EError("--validate-only and --retrieval-only cannot be combined")
    windows = load_gate3_inputs(args)
    if args.validate_only:
        return validate_only_payload(args, windows)

    run_id = args.run_id or _run_id()
    run_dir = _prepare_run_dir(repo_path(args.output_root), run_id, force=bool(args.force))
    paths = {
        "run_manifest": run_dir / "run_manifest.json",
        "page_corpus": run_dir / "page_corpus.jsonl",
        "page_retrieval_results": run_dir / "page_retrieval_results.jsonl",
        "page_retrieval_metrics": run_dir / "page_retrieval_metrics.json",
        "retrieval_preview": run_dir / "retrieval_preview.json",
        "fixed_evidence": run_dir / "fixed_evidence.jsonl",
        "answer_results": run_dir / "answer_results.jsonl",
        "answer_results_preview": run_dir / "answer_results_preview.json",
        "answer_metrics": run_dir / "answer_metrics.json",
        "failure_cases": run_dir / "failure_cases.jsonl",
        "summary": run_dir / "summary.json",
        "summary_md": run_dir / "summary.md",
        "sqlite": run_dir / "docagent.sqlite",
    }

    page_corpus = build_page_corpus(windows)
    write_jsonl(paths["page_corpus"], page_corpus)
    _write_json(paths["run_manifest"], build_run_manifest(args, run_id=run_id, windows=windows))

    _stage("loading retrieval models")
    dense_encoder, dense_timing = build_dense_resources(
        backend=args.dense_backend,
        model_path=args.dense_model_path,
        device=args.retrieval_device,
        use_fp16=args.retrieval_fp16,
        allow_mock_backends=args.allow_mock_backends,
    )
    if dense_encoder is None:
        raise Phase4BE2EError("Gate 3 hybrid retrieval requires a dense encoder")
    all_page_blocks = [block for window in windows for block in window.page_blocks]
    dense_index, dense_index_build_ms = build_dense_index_for_corpus(
        blocks=all_page_blocks,
        dense_encoder=dense_encoder,
        output_dir=run_dir,
    )
    if dense_index is None:
        raise Phase4BE2EError("failed to build dense page index")
    reranker, reranker_timing = build_reranker(
        backend=args.reranker_backend,
        model_path=args.reranker_model_path,
        device=args.retrieval_device,
        use_fp16=args.retrieval_fp16,
        allow_mock_backends=args.allow_mock_backends,
    )
    if reranker is None:
        raise Phase4BE2EError("Gate 3 hybrid retrieval requires a reranker")

    _stage("running page retrieval")
    retrieval_rows, page_metrics = run_retrieval(
        windows=windows,
        dense_encoder=dense_encoder,
        dense_index=dense_index,
        reranker=reranker,
        top_k_pages=args.top_k_pages,
        bm25_top_n=args.bm25_top_n,
        dense_top_n=args.dense_top_n,
        fusion_top_n=args.fusion_top_n,
        rrf_k=args.rrf_k,
    )
    write_jsonl(paths["page_retrieval_results"], retrieval_rows)
    _write_json(paths["page_retrieval_metrics"], page_metrics)
    retrieval_preview = build_retrieval_preview(retrieval_rows)
    _write_json(paths["retrieval_preview"], {"records": retrieval_preview})

    fixed_records, fixed_evidence_by_qid = build_fixed_evidence(
        windows=windows,
        retrieval_rows=retrieval_rows,
        max_context_blocks=args.max_context_blocks,
    )
    assert_no_gold_leakage(fixed_records)
    fixed_hash = fixed_evidence_hash(fixed_records)
    write_jsonl(paths["fixed_evidence"], fixed_records)

    release_info = release_retrieval_resources(dense_encoder, reranker)
    release_info["retrieval_released_before_answer_policy"] = True

    answer_rows: list[dict[str, Any]] = []
    answer_metrics: dict[str, Any] = {
        "status": "skipped",
        "sample_count": len(fixed_records),
        "completed_count": 0,
        "failed_count": 0,
    }
    answer_model_load_ms: float | None = None
    if not args.retrieval_only:
        _stage("loading answer policy")
        answer_policy, answer_model_load_ms = build_answer_policy(
            policy_backend=args.answer_backend,
            mode=args.answer_mode,
            base_model_path=args.base_model_path,
            adapter_path=args.adapter_path,
            device=args.qwen_device,
            torch_dtype=args.qwen_torch_dtype,
            max_prompt_tokens=args.max_prompt_tokens,
            max_new_tokens=args.max_new_tokens,
            allow_mock_backends=args.allow_mock_backends,
            rank_aware_context=bool(args.rank_aware_context),
        )
        _stage("running AnswerPolicy")
        answer_rows, answer_metrics = run_answer_phase(
            windows=windows,
            fixed_evidence_by_qid=fixed_evidence_by_qid,
            answer_policy=answer_policy,
            sqlite_path=paths["sqlite"],
            max_prompt_tokens=args.max_prompt_tokens,
            rank_aware_context=bool(args.rank_aware_context),
        )
        write_jsonl(paths["answer_results"], answer_rows)
        _write_json(paths["answer_metrics"], answer_metrics)
        release_policy(answer_policy)
    else:
        write_jsonl(paths["answer_results"], [])
        _write_json(paths["answer_metrics"], answer_metrics)
    answer_results_preview = build_answer_results_preview(answer_rows)
    _write_json(paths["answer_results_preview"], {"records": answer_results_preview})

    failure_rows = build_failure_cases(answer_rows=answer_rows, retrieval_rows=retrieval_rows)
    write_jsonl(paths["failure_cases"], failure_rows)
    trace_counts = _trace_counts(paths["sqlite"])
    summary = {
        "command": COMMAND,
        "status": "success",
        "phase": PHASE,
        "gate": GATE,
        "run_id": run_id,
        "evaluation_scope": EVALUATION_SCOPE,
        "formal_benchmark": False,
        "primary_benchmark": False,
        "retrieval_scope": RETRIEVAL_SCOPE,
        "query_rewrite": "none",
        "rank_aware_context": bool(args.rank_aware_context),
        "document_count": len(windows),
        "page_count": len(page_corpus),
        "qa_count": sum(len(window.qa_records) for window in windows),
        "page_retrieval_metrics": page_metrics,
        "page_retrieval_delta": page_metrics["comparison"],
        "answer_metrics": answer_metrics,
        "page_location_hit": answer_metrics.get("page_location_hit", answer_metrics.get("gold_page_location_hit")),
        "block_location_hit": answer_metrics.get("block_location_hit"),
        "fixed_evidence_hash": fixed_hash,
        "trace_counts": trace_counts,
        "retrieval_preview": retrieval_preview,
        "answer_results_preview": answer_results_preview,
        "resource_plan": {
            **release_info,
            "dense_model_load_ms": dense_timing.dense_model_load_ms,
            "reranker_model_load_ms": reranker_timing.reranker_model_load_ms,
            "dense_index_build_ms": dense_index_build_ms,
            "answer_model_load_ms": answer_model_load_ms,
        },
        "warnings": [
            "one-page window is trivially retrievable; do not use it to overstate Hybrid gains",
        ],
        "failure_taxonomy": _failure_counts(failure_rows),
        "artifact_paths": _artifact_paths(run_dir, paths),
    }
    _write_json(paths["summary"], summary)
    write_summary_md(paths["summary_md"], summary)
    return summary


def _failure_payload(args: argparse.Namespace, exc: Exception) -> dict[str, Any]:
    return {
        "command": COMMAND,
        "status": "failed",
        "exit_code": 1,
        "phase": PHASE,
        "gate": GATE,
        "exception": f"{type(exc).__name__}: {exc}",
        "traceback_tail": traceback.format_exc().splitlines()[-12:],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 4B Gate 3 MP-DocVQA page-level retrieval and E2E.")
    parser.add_argument("--sample-root", default=DEFAULT_SAMPLE_ROOT)
    parser.add_argument("--ingestion-root", default=DEFAULT_INGESTION_ROOT)
    parser.add_argument("--doc-id", action="append")
    parser.add_argument("--doc-id-file")
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run-id")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--top-k-pages", type=int, default=5)
    parser.add_argument("--max-context-blocks", type=int, default=64)
    parser.add_argument("--max-prompt-tokens", type=int, default=4096)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--bm25-top-n", type=int, default=20)
    parser.add_argument("--dense-top-n", type=int, default=20)
    parser.add_argument("--fusion-top-n", type=int, default=20)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--dense-backend", choices=["hash", "bge"], default="bge")
    parser.add_argument("--dense-model-path", default=DEFAULT_BGE_MODEL_PATH)
    parser.add_argument("--reranker-backend", choices=["keyword", "cross_encoder"], default="cross_encoder")
    parser.add_argument("--reranker-model-path", default=DEFAULT_RERANKER_MODEL_PATH)
    parser.add_argument("--retrieval-device", default="cuda")
    parser.add_argument("--retrieval-fp16", action="store_true", default=True)
    parser.add_argument("--no-retrieval-fp16", dest="retrieval_fp16", action="store_false")
    parser.add_argument("--answer-backend", choices=["heuristic", "qwen"], default="qwen")
    parser.add_argument("--answer-mode", choices=["base", "sft", "grpo"], default="grpo")
    parser.add_argument("--base-model-path", default=DEFAULT_QWEN_MODEL_PATH)
    parser.add_argument("--adapter-path", default=DEFAULT_GRPO_ADAPTER_PATH)
    parser.add_argument("--qwen-device", default="cuda")
    parser.add_argument("--qwen-torch-dtype", default="bfloat16")
    parser.add_argument("--allow-mock-backends", action="store_true")
    parser.add_argument("--rank-aware-context", action="store_true")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    try:
        payload = run_phase4b_e2e(args)
    except Exception as exc:
        payload = _failure_payload(args, exc)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(0 if payload.get("status") == "success" else 1)


if __name__ == "__main__":
    main()
