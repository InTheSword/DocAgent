from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.parser.mineru_converter import (
    build_page_blocks,
    content_list_to_chunks,
    validate_mineru_chunk_contract,
)
from docagent.retrieval.dense_encoder import DenseEncoder, DenseEncoderConfig, HashDenseEncoder
from docagent.retrieval.dense_index import DenseIndex
from docagent.retrieval.index_manager import IndexedDocumentRetriever
from docagent.retrieval.reranker import CrossEncoderReranker, CrossEncoderRerankerConfig
from docagent.schemas import Chunk
from docagent.utils.jsonl import read_jsonl, write_jsonl


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_records(sample_path: Path, table_sample_path: Path | None) -> list[dict[str, Any]]:
    source_records = read_jsonl(sample_path)
    records = [
        record
        for record in source_records
        if (
            str(record.get("target_modality") or "") == "table"
            or str(record.get("query_type") or "") in {"keyword", "semantic"}
        )
    ]
    if table_sample_path is not None:
        records.extend(read_jsonl(table_sample_path))
    return records


def _mapped_gold_ids(record: dict[str, Any], chunks: list[Chunk]) -> list[str]:
    legacy_ids = {str(item) for item in record.get("gold_block_ids") or []}
    return [
        chunk.block_id
        for chunk in chunks
        if legacy_ids.intersection(str(item) for item in chunk.metadata.get("source_block_ids") or [chunk.block_id])
    ]


def _build_encoder(args: argparse.Namespace):
    if args.dense_backend == "hash":
        return HashDenseEncoder()
    if not args.dense_model_path:
        raise ValueError("--dense-model-path is required for --dense-backend bge")
    return DenseEncoder(
        DenseEncoderConfig(
            model_path=str(repo_path(args.dense_model_path)),
            device=args.device,
            use_fp16=not args.no_fp16,
            batch_size=args.dense_batch_size,
            max_length=args.dense_max_length,
        )
    )


def _build_reranker(args: argparse.Namespace):
    if not args.reranker_model_path:
        return None
    return CrossEncoderReranker(
        CrossEncoderRerankerConfig(
            model_path=str(repo_path(args.reranker_model_path)),
            device=args.device,
            use_fp16=not args.no_fp16,
            batch_size=args.reranker_batch_size,
            max_length=args.reranker_max_length,
        )
    )


def _structured_match(record: dict[str, Any], results: list[dict[str, Any]]) -> bool | None:
    expected = record.get("expected_structured")
    if not isinstance(expected, dict):
        return None
    match = next(
        (
            result
            for result in results
            if result.get("block_id") == expected.get("block_id")
        ),
        None,
    )
    if match is None:
        return False
    if "selected_rows" in expected and match.get("selected_rows") != expected["selected_rows"]:
        return False
    if "aggregate" in expected and match.get("aggregate") != expected["aggregate"]:
        return False
    return True


def _bucket(record: dict[str, Any]) -> str:
    if record.get("table_query"):
        return "table_structured"
    if str(record.get("target_modality") or "") == "table":
        return "table_text"
    return "ordinary"


def _summary(rows: list[dict[str, Any]]) -> dict[str, object]:
    if not rows:
        return {
            "query_count": 0,
            "hit_rate_at_k": 0.0,
            "mean_gold_recall_at_k": 0.0,
            "mrr_at_k": 0.0,
            "mean_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
        }
    latencies = sorted(float(row["latency_ms"]) for row in rows)
    return {
        "query_count": len(rows),
        "hit_rate_at_k": sum(bool(row["hit"]) for row in rows) / len(rows),
        "mean_gold_recall_at_k": sum(float(row["gold_recall"]) for row in rows) / len(rows),
        "mrr_at_k": sum(float(row["reciprocal_rank"]) for row in rows) / len(rows),
        "mean_latency_ms": sum(latencies) / len(latencies),
        "p95_latency_ms": latencies[math.ceil(len(latencies) * 0.95) - 1],
    }


def run_validation(args: argparse.Namespace) -> dict[str, object]:
    content_list = repo_path(args.content_list)
    sample_path = repo_path(args.samples)
    table_sample_path = repo_path(args.table_samples) if args.table_samples else None
    output_dir = repo_path(args.output_dir)
    document_dir = repo_path(args.document_dir) if args.document_dir else content_list.parent.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    chunks = content_list_to_chunks(
        doc_id=args.doc_id,
        content_list_path=content_list,
        document_dir=document_dir,
    )
    page_chunks = build_page_blocks(args.doc_id, chunks)
    contract_errors = validate_mineru_chunk_contract(chunks)
    write_jsonl(output_dir / "chunks_v3.jsonl", [chunk.to_dict() for chunk in chunks])
    write_jsonl(output_dir / "page_chunks_v3.jsonl", [chunk.to_dict() for chunk in page_chunks])

    records = _load_records(sample_path, table_sample_path)
    mapped_records = [
        {
            **record,
            "mapped_gold_block_ids": _mapped_gold_ids(record, chunks),
        }
        for record in records
    ]
    write_jsonl(output_dir / "direct_retrieval_samples.jsonl", mapped_records)

    indexable = [chunk for chunk in chunks if chunk.is_indexable]
    encoder = _build_encoder(args)
    embeddings = encoder.encode_documents([chunk.retrieval_text for chunk in indexable])
    dense_index = DenseIndex.build(blocks=indexable, embeddings=embeddings, model_id=encoder.model_id)
    dense_metadata = dense_index.save(output_dir / "dense_index")
    reranker = _build_reranker(args)
    mode = "hybrid_rerank" if reranker is not None else "hybrid"
    retriever = IndexedDocumentRetriever(
        chunks,
        mode=mode,
        dense_encoder=encoder,
        dense_index=dense_index,
        reranker=reranker,
    )

    details: list[dict[str, Any]] = []
    for record in mapped_records:
        start = time.perf_counter()
        result = retriever.retrieve(
            doc_id=args.doc_id,
            question=str(record["question"]),
            top_k=args.top_k,
            query_intent="table" if _bucket(record).startswith("table") else None,
            table_query=record.get("table_query"),
            enable_query_rewrite=False,
        )
        latency_ms = (time.perf_counter() - start) * 1000
        ranking = [candidate.block.block_id for candidate in result.candidates]
        gold = list(record["mapped_gold_block_ids"])
        matching_ranks = [index + 1 for index, block_id in enumerate(ranking) if block_id in gold]
        structured_results = list(result.metadata.get("table_structured_results") or [])
        details.append(
            {
                "qid": record.get("qid"),
                "bucket": _bucket(record),
                "question": record.get("question"),
                "gold_block_ids": gold,
                "ranking": ranking,
                "ranking_details": [
                    candidate.to_trace_dict(final_rank=rank)
                    for rank, candidate in enumerate(result.candidates, start=1)
                ],
                "hit": bool(matching_ranks),
                "gold_recall": len(set(ranking).intersection(gold)) / len(gold) if gold else 0.0,
                "reciprocal_rank": 1.0 / min(matching_ranks) if matching_ranks else 0.0,
                "structured_match": _structured_match(record, structured_results),
                "table_structured_results": structured_results,
                "retrieval_routes": result.metadata.get("retrieval_routes"),
                "metadata_filter": result.metadata.get("metadata_filter"),
                "query_rewrite_enabled": result.metadata.get("query_rewrite_enabled"),
                "query_planner_used": "query_planner" in result.metadata,
                "latency_ms": latency_ms,
            }
        )
    write_jsonl(output_dir / "details.jsonl", details)

    summaries = {
        bucket: _summary([row for row in details if row["bucket"] == bucket])
        for bucket in ("ordinary", "table_text", "table_structured")
    }
    structured_rows = [row for row in details if row["structured_match"] is not None]
    route_contract_valid = all(
        row["query_rewrite_enabled"] is False
        and row["query_planner_used"] is False
        and "metadata" not in row["retrieval_routes"]
        and (
            ("table_structured" in row["retrieval_routes"])
            == (row["bucket"] == "table_structured")
        )
        for row in details
    )
    validation_passed = (
        not contract_errors
        and all(record["mapped_gold_block_ids"] for record in mapped_records)
        and all(row["structured_match"] is True for row in structured_rows)
        and route_contract_valid
    )
    chunk_strategies = Counter(str(chunk.metadata.get("chunk_strategy") or "") for chunk in chunks)
    summary = {
        "run_id": args.run_id,
        "status": "success" if validation_passed else "failed",
        "validation_scope": "direct retrieval without intent routing, query planning, or query rewriting",
        "formal_benchmark": False,
        "doc_id": args.doc_id,
        "chunk_rebuild": {
            "chunk_contract_version": "docagent_chunk_v3",
            "raw_content_list": str(content_list),
            "chunk_count": len(chunks),
            "indexable_chunk_count": len(indexable),
            "page_chunk_count": len(page_chunks),
            "chunk_strategy_counts": dict(sorted(chunk_strategies.items())),
            "cross_page_chunk_count": sum(
                len(chunk.metadata.get("source_page_numbers") or []) > 1
                for chunk in chunks
            ),
            "structured_table_count": sum(
                chunk.block_type == "table"
                and bool(chunk.metadata.get("table_headers"))
                and bool(chunk.metadata.get("table_rows"))
                for chunk in chunks
            ),
            "contract_error_count": sum(len(errors) for errors in contract_errors.values()),
        },
        "retrieval": {
            "mode": mode,
            "dense_backend": args.dense_backend,
            "dense_model_id": encoder.model_id,
            "reranker_backend": getattr(reranker, "backend", None),
            "top_k": args.top_k,
            "query_rewrite_enabled": False,
            "query_planning_enabled": False,
            "intent_router_enabled": False,
            "buckets": summaries,
            "structured_exact_match_rate": (
                sum(row["structured_match"] is True for row in structured_rows) / len(structured_rows)
                if structured_rows
                else None
            ),
            "route_contract_valid": route_contract_valid,
        },
        "limitations": [
            "This is a real-document regression probe, not a formal retrieval benchmark.",
            (
                "Hash dense is a mock and cannot establish semantic retrieval quality."
                if args.dense_backend == "hash"
                else "BGE-M3 results apply only to this small regression set."
            ),
        ],
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary_md = (
        f"# Direct RAG retrieval validation\n\n"
        f"- status: `{summary['status']}`\n"
        f"- chunks: {len(chunks)} ({len(indexable)} indexable)\n"
        f"- dense backend: `{args.dense_backend}`\n"
        f"- mode: `{mode}`\n"
        f"- ordinary Hit@{args.top_k}: {summaries['ordinary']['hit_rate_at_k']:.4f}\n"
        f"- table text Hit@{args.top_k}: {summaries['table_text']['hit_rate_at_k']:.4f}\n"
        f"- table structured exact match: {summary['retrieval']['structured_exact_match_rate']}\n"
        f"- query rewrite / planner / intent router: disabled\n"
    )
    (output_dir / "summary.md").write_text(summary_md, encoding="utf-8")
    artifacts = [
        "chunks_v3.jsonl",
        "page_chunks_v3.jsonl",
        "direct_retrieval_samples.jsonl",
        "details.jsonl",
        "summary.json",
        "summary.md",
        "result.json",
    ]
    result = {
        "command": "validate_direct_rag_retrieval",
        "status": summary["status"],
        "artifact_paths": [
            str(output_dir / name)
            for name in [*artifacts, "manifest.json"]
        ],
        "metrics": {
            "chunk_count": len(chunks),
            "contract_error_count": summary["chunk_rebuild"]["contract_error_count"],
            "ordinary_hit_rate_at_k": summaries["ordinary"]["hit_rate_at_k"],
            "table_text_hit_rate_at_k": summaries["table_text"]["hit_rate_at_k"],
            "table_structured_exact_match_rate": summary["retrieval"]["structured_exact_match_rate"],
        },
    }
    (output_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest = {
        "run_id": args.run_id,
        "files": [
            {
                "path": name,
                "size": (output_dir / name).stat().st_size,
                "sha256": _sha256(output_dir / name),
            }
            for name in artifacts
        ],
        "dense_index": dense_metadata,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild MinerU Chunk v3 and validate direct retrieval.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--content-list", required=True)
    parser.add_argument("--samples", required=True)
    parser.add_argument("--table-samples")
    parser.add_argument("--document-dir")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--dense-backend", choices=["hash", "bge"], default="hash")
    parser.add_argument("--dense-model-path")
    parser.add_argument("--reranker-model-path")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--no-fp16", action="store_true")
    parser.add_argument("--dense-batch-size", type=int, default=8)
    parser.add_argument("--dense-max-length", type=int, default=8192)
    parser.add_argument("--reranker-batch-size", type=int, default=4)
    parser.add_argument("--reranker-max-length", type=int, default=4096)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = run_validation(args)
    except Exception as exc:
        result = {
            "command": "validate_direct_rag_retrieval",
            "status": "failed",
            "exit_code": 1,
            "exception": f"{type(exc).__name__}: {exc}",
            "log_tail": "",
        }
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "success" else 1)


if __name__ == "__main__":
    main()
