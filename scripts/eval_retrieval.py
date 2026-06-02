from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.eval.retrieval_metrics import mrr_at_k, recall_at_k
from docagent.parser.build_evidence_blocks import collect_evidence_blocks
from docagent.retrieval.hybrid_retriever import HybridRetriever
from docagent.schemas import DocAgentSample
from docagent.utils.jsonl import read_jsonl


def load_samples(path: Path) -> list[DocAgentSample]:
    return [DocAgentSample.from_dict(record) for record in read_jsonl(path)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/benchmark/smoke_eval.jsonl")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", default="outputs/eval/retrieval_smoke.json")
    parser.add_argument("--include-details", action="store_true")
    args = parser.parse_args()

    samples = load_samples(ROOT / args.input)
    blocks = collect_evidence_blocks(samples)
    retriever = HybridRetriever(blocks)

    rankings: list[list[str]] = []
    gold_ids: list[set[str]] = []
    details = []
    for sample in samples:
        rewritten_query, hits = retriever.retrieve(
            sample.question,
            top_k=args.top_k,
            answer_type_hint=sample.answer_type,
        )
        ranking = [block.block_id for block, _score in hits]
        ranking_details = [
            {"block_id": block.block_id, "block_type": block.block_type, "score": score}
            for block, score in hits
        ]
        metadata_gold = sample.metadata.get("gold_block_ids")
        gold = set(metadata_gold) if metadata_gold else {block.block_id for block in sample.evidence}
        rankings.append(ranking)
        gold_ids.append(gold)
        details.append(
            {
                "qid": sample.qid,
                "question": sample.question,
                "rewritten_query": rewritten_query,
                "ranking": ranking,
                "ranking_details": ranking_details,
                "gold": sorted(gold),
                "hit": bool(set(ranking[: args.top_k]) & gold),
            }
        )

    summary = {
        "input": args.input,
        "num_samples": len(samples),
        "num_blocks": len(blocks),
        "top_k": args.top_k,
        "recall_at_k": recall_at_k(rankings, gold_ids, k=args.top_k),
        "mrr_at_k": mrr_at_k(rankings, gold_ids, k=args.top_k),
        "num_misses": sum(1 for item in details if not item["hit"]),
        "miss_qids": [item["qid"] for item in details if not item["hit"]],
    }
    report = {
        **summary,
        "details": details,
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report if args.include_details else summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
