from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.parser.build_evidence_blocks import collect_evidence_blocks
from docagent.retrieval.hybrid_retriever import HybridRetriever
from docagent.schemas import DocAgentSample, EvidenceBlock
from docagent.utils.jsonl import read_jsonl, write_jsonl


def load_samples(path: Path) -> list[DocAgentSample]:
    return [DocAgentSample.from_dict(record) for record in read_jsonl(path)]


def clone_retrieved_block(block: EvidenceBlock, score: float, rank: int) -> EvidenceBlock:
    data = block.to_dict()
    metadata = dict(data.get("metadata") or {})
    metadata["retrieval_score"] = score
    metadata["retrieval_rank"] = rank
    metadata["retrieval_source"] = "same_doc_bm25"
    data["metadata"] = metadata
    return EvidenceBlock.from_dict(data)


def build_retrievers(samples: list[DocAgentSample]) -> tuple[HybridRetriever, dict[str, HybridRetriever]]:
    blocks = collect_evidence_blocks(samples)
    global_retriever = HybridRetriever(blocks)
    blocks_by_doc: dict[str, list[EvidenceBlock]] = {}
    for block in blocks:
        blocks_by_doc.setdefault(block.doc_id, []).append(block)
    retrievers_by_doc = {
        doc_id: HybridRetriever(doc_blocks) for doc_id, doc_blocks in blocks_by_doc.items()
    }
    return global_retriever, retrievers_by_doc


def convert_sample(
    sample: DocAgentSample,
    retriever: HybridRetriever,
    top_k: int,
    require_gold: bool,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    rewritten_query, hits = retriever.retrieve(sample.question, top_k=top_k, answer_type_hint=sample.answer_type)
    gold_ids = set(sample.metadata.get("gold_block_ids") or [block.block_id for block in sample.evidence])
    retrieved_blocks = [
        clone_retrieved_block(block, score=score, rank=index + 1)
        for index, (block, score) in enumerate(hits)
    ]
    ranking = [block.block_id for block in retrieved_blocks]
    gold_ranks = [index + 1 for index, block_id in enumerate(ranking) if block_id in gold_ids]
    hit = bool(gold_ranks)
    detail = {
        "qid": sample.qid,
        "doc_id": sample.doc_id,
        "rewritten_query": rewritten_query,
        "ranking": ranking,
        "gold": sorted(gold_ids),
        "hit": hit,
        "gold_rank": min(gold_ranks) if gold_ranks else None,
    }
    if require_gold and not hit:
        return None, detail

    record = sample.to_dict()
    record["evidence"] = [block.to_dict() for block in retrieved_blocks]
    metadata = dict(record.get("metadata") or {})
    metadata.update(
        {
            "reader_evidence_source": "same_doc_bm25",
            "reader_top_k": top_k,
            "retrieval_rewritten_query": rewritten_query,
            "retrieval_ranking": ranking,
            "retrieval_gold_rank": detail["gold_rank"],
            "retrieval_hit": hit,
        }
    )
    record["metadata"] = metadata
    return record, detail


def summarize(details: list[dict[str, Any]], total_samples: int, output_records: int, top_k: int) -> dict[str, Any]:
    hits = [detail for detail in details if detail["hit"]]
    reciprocal_ranks = [
        1 / detail["gold_rank"] for detail in details if detail["gold_rank"]
    ]
    return {
        "num_samples": total_samples,
        "num_output_records": output_records,
        "top_k": top_k,
        "retrieval_hit_count": len(hits),
        "retrieval_recall_at_k": len(hits) / total_samples if total_samples else 0.0,
        "retrieval_mrr_at_k": sum(reciprocal_ranks) / total_samples if total_samples else 0.0,
        "num_skipped_no_gold": total_samples - output_records,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--details-output", default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-scope", choices=["same_doc", "global"], default="same_doc")
    parser.add_argument("--require-gold", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    samples = load_samples(ROOT / args.input)
    if args.limit is not None:
        samples = samples[: args.limit]
    global_retriever, retrievers_by_doc = build_retrievers(samples)

    records = []
    details = []
    for sample in samples:
        retriever = (
            retrievers_by_doc.get(sample.doc_id, global_retriever)
            if args.candidate_scope == "same_doc"
            else global_retriever
        )
        record, detail = convert_sample(sample, retriever, top_k=args.top_k, require_gold=args.require_gold)
        details.append(detail)
        if record is not None:
            records.append(record)

    write_jsonl(ROOT / args.output, records)
    if args.details_output:
        output = ROOT / args.details_output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"details": details}, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "input": args.input,
        "output": args.output,
        "details_output": args.details_output,
        "candidate_scope": args.candidate_scope,
        "require_gold": args.require_gold,
        **summarize(details, total_samples=len(samples), output_records=len(records), top_k=args.top_k),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
