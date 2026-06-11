from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.eval.retrieval_metrics import mrr_at_k, recall_at_k
from docagent.parser.build_evidence_blocks import collect_evidence_blocks
from docagent.retrieval.dense_encoder import DenseEncoder, DenseEncoderConfig
from docagent.retrieval.dense_index import DenseIndex
from docagent.retrieval.index_manager import IndexedDocumentRetriever
from docagent.retrieval.reranker import CrossEncoderReranker, CrossEncoderRerankerConfig
from docagent.schemas import DocAgentSample, EvidenceBlock
from docagent.utils.jsonl import read_jsonl


def load_samples(path: Path, limit: int | None) -> list[DocAgentSample]:
    records = read_jsonl(path)
    if limit is not None:
        records = records[:limit]
    return [DocAgentSample.from_dict(record) for record in records]


def summarize(details: list[dict], *, top_k: int) -> dict:
    rankings = [item["ranking"] for item in details]
    gold_ids = [set(item["gold"]) for item in details]
    latencies = [item["latency_ms"] for item in details]
    return {
        "num_samples": len(details),
        "top_k": top_k,
        "recall_at_1": recall_at_k(rankings, gold_ids, k=1),
        "recall_at_3": recall_at_k(rankings, gold_ids, k=min(3, top_k)),
        "recall_at_5": recall_at_k(rankings, gold_ids, k=min(5, top_k)),
        "mrr_at_5": mrr_at_k(rankings, gold_ids, k=min(5, top_k)),
        "num_misses": sum(1 for item in details if not item["hit"]),
        "mean_latency_ms": sum(latencies) / max(len(latencies), 1),
        "p95_latency_ms": sorted(latencies)[int(len(latencies) * 0.95) - 1] if latencies else 0.0,
    }


def build_dense_index(
    *,
    blocks: list[EvidenceBlock],
    dense_encoder: DenseEncoder | None,
    model_id: str,
) -> DenseIndex:
    if dense_encoder is None:
        raise RuntimeError("dense modes require --dense-model-path")
    embeddings = dense_encoder.encode_documents([block.retrieval_text for block in blocks])
    if embeddings.shape[0] != len(blocks):
        raise RuntimeError("dense encoder returned a different number of embeddings than blocks")
    return DenseIndex.build(blocks=blocks, embeddings=embeddings, model_id=model_id)


def evaluate_mode(
    *,
    mode: str,
    samples: list[DocAgentSample],
    blocks_by_doc: dict[str, list[EvidenceBlock]],
    top_k: int,
    dense_encoder: DenseEncoder | None,
    reranker,
) -> dict:
    dense_cache: dict[str, DenseIndex] = {}
    details = []
    for sample in samples:
        doc_blocks = blocks_by_doc.get(sample.doc_id, [])
        dense_index = None
        if mode in {"dense", "hybrid", "hybrid_rerank"}:
            dense_index = dense_cache.get(sample.doc_id)
            if dense_index is None:
                dense_index = build_dense_index(
                    blocks=doc_blocks,
                    dense_encoder=dense_encoder,
                    model_id=dense_encoder.model_id if dense_encoder is not None else "",
                )
                dense_cache[sample.doc_id] = dense_index
        retriever = IndexedDocumentRetriever(
            doc_blocks,
            mode=mode,
            dense_encoder=dense_encoder,
            dense_index=dense_index,
            reranker=reranker if mode == "hybrid_rerank" else None,
        )
        start = time.perf_counter()
        result = retriever.retrieve(
            doc_id=sample.doc_id,
            question=sample.question,
            top_k=top_k,
            answer_type_hint=sample.answer_type,
        )
        elapsed = (time.perf_counter() - start) * 1000
        ranking = [candidate.block.block_id for candidate in result.candidates]
        metadata_gold = sample.metadata.get("gold_block_ids")
        gold = set(metadata_gold) if metadata_gold else {block.block_id for block in sample.evidence}
        details.append(
            {
                "qid": sample.qid,
                "doc_id": sample.doc_id,
                "question": sample.question,
                "ranking": ranking,
                "ranking_details": [
                    candidate.to_trace_dict(final_rank=rank)
                    for rank, candidate in enumerate(result.candidates, start=1)
                ],
                "gold": sorted(gold),
                "hit": bool(set(ranking[:top_k]) & gold),
                "latency_ms": elapsed,
            }
        )
    summary = summarize(details, top_k=top_k)
    summary["mode"] = mode
    return {"summary": summary, "details": details}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="outputs/eval/phase2_retrieval_ablation.json")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--modes", default="bm25")
    parser.add_argument("--dense-model-path")
    parser.add_argument("--dense-device", default="cpu")
    parser.add_argument("--dense-fp16", action="store_true")
    parser.add_argument("--reranker-model-path")
    parser.add_argument("--reranker-device", default="cpu")
    parser.add_argument("--reranker-fp16", action="store_true")
    args = parser.parse_args()

    samples = load_samples(ROOT / args.input, args.limit)
    blocks = collect_evidence_blocks(samples)
    blocks_by_doc: dict[str, list[EvidenceBlock]] = {}
    for block in blocks:
        blocks_by_doc.setdefault(block.doc_id, []).append(block)

    modes = [mode.strip() for mode in args.modes.split(",") if mode.strip()]
    dense_encoder = None
    if any(mode in {"dense", "hybrid", "hybrid_rerank"} for mode in modes):
        if not args.dense_model_path:
            raise SystemExit("dense/hybrid modes require --dense-model-path")
        dense_encoder = DenseEncoder(
            DenseEncoderConfig(
                model_path=args.dense_model_path,
                device=args.dense_device,
                use_fp16=args.dense_fp16,
            )
        )
    reranker = None
    if "hybrid_rerank" in modes:
        if not args.reranker_model_path:
            raise SystemExit("hybrid_rerank requires --reranker-model-path")
        reranker = CrossEncoderReranker(
            CrossEncoderRerankerConfig(
                model_path=args.reranker_model_path,
                device=args.reranker_device,
                use_fp16=args.reranker_fp16,
            )
        )

    report = {
        "input": args.input,
        "num_blocks": len(blocks),
        "num_docs": len(blocks_by_doc),
        "modes": {},
    }
    for mode in modes:
        report["modes"][mode] = evaluate_mode(
            mode=mode,
            samples=samples,
            blocks_by_doc=blocks_by_doc,
            top_k=args.top_k,
            dense_encoder=dense_encoder,
            reranker=reranker,
        )
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "input": args.input,
        "num_samples": len(samples),
        "num_blocks": len(blocks),
        "modes": {mode: data["summary"] for mode, data in report["modes"].items()},
        "output": args.output,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

