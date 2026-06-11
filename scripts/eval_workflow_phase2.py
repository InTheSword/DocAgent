from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.eval.answer_metrics import exact_match, token_f1
from docagent.models.base import HeuristicAnswerPolicy
from docagent.models.qwen_answer_policy import QwenAnswerPolicy, QwenAnswerPolicyConfig
from docagent.retrieval.dense_encoder import DenseEncoder, DenseEncoderConfig, HashDenseEncoder
from docagent.retrieval.dense_index import DenseIndex
from docagent.retrieval.index_manager import IndexedDocumentRetriever
from docagent.retrieval.reranker import CrossEncoderReranker, CrossEncoderRerankerConfig, KeywordOverlapReranker
from docagent.rewards.location_reward import location_reward
from docagent.storage.db import connect
from docagent.storage.repositories import TraceRepository
from docagent.utils.jsonl import read_jsonl, write_jsonl
from docagent.workflow.graph import run_qa_workflow
from scripts.eval_workflow_e2e import summarize
from scripts.workflow_record_utils import workflow_input_from_record


def build_policy(args: argparse.Namespace):
    if args.policy_mode == "heuristic":
        return HeuristicAnswerPolicy()
    return QwenAnswerPolicy(
        QwenAnswerPolicyConfig(
            mode=args.policy_mode,
            base_model_path=args.base_model_path,
            adapter_path=args.adapter_path,
            device=args.device,
            torch_dtype=args.torch_dtype,
            max_prompt_tokens=args.max_prompt_tokens,
            max_new_tokens=args.max_new_tokens,
        )
    )


def dense_index_for_blocks(blocks, dense_encoder: DenseEncoder | None, retriever_mode: str) -> DenseIndex | None:
    if retriever_mode == "bm25":
        return None
    if dense_encoder is None:
        raise RuntimeError(f"{retriever_mode} requires dense encoder")
    embeddings = dense_encoder.encode_documents([block.retrieval_text for block in blocks])
    return DenseIndex.build(blocks=blocks, embeddings=np.asarray(embeddings, dtype=np.float32), model_id=dense_encoder.model_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary-output", required=True)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--retriever", choices=["bm25", "dense", "hybrid", "hybrid_rerank"], default="bm25")
    parser.add_argument("--policy-mode", choices=["heuristic", "base", "sft", "grpo"], default="heuristic")
    parser.add_argument("--dense-backend", choices=["bge", "hash"], default="bge")
    parser.add_argument("--dense-model-path")
    parser.add_argument("--dense-device", default="cpu")
    parser.add_argument("--dense-fp16", action="store_true")
    parser.add_argument("--reranker-backend", choices=["cross_encoder", "keyword"], default="cross_encoder")
    parser.add_argument("--reranker-model-path")
    parser.add_argument("--reranker-device", default="cpu")
    parser.add_argument("--reranker-fp16", action="store_true")
    parser.add_argument("--base-model-path", default="/root/autodl-tmp/models/Qwen3-1.7B")
    parser.add_argument("--adapter-path", default=None)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--torch-dtype", default="bfloat16")
    parser.add_argument("--max-prompt-tokens", type=int, default=4096)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--sqlite-path", default="outputs/traces/workflow_phase2_eval.sqlite")
    args = parser.parse_args()

    dense_encoder = None
    if args.retriever in {"dense", "hybrid", "hybrid_rerank"}:
        if args.dense_backend == "hash":
            dense_encoder = HashDenseEncoder()
        elif not args.dense_model_path:
            raise SystemExit(f"{args.retriever} requires --dense-model-path")
        else:
            dense_encoder = DenseEncoder(
                DenseEncoderConfig(
                    model_path=args.dense_model_path,
                    device=args.dense_device,
                    use_fp16=args.dense_fp16,
                )
            )
    reranker = None
    if args.retriever == "hybrid_rerank":
        if args.reranker_backend == "keyword":
            reranker = KeywordOverlapReranker()
        elif not args.reranker_model_path:
            raise SystemExit("hybrid_rerank requires --reranker-model-path")
        else:
            reranker = CrossEncoderReranker(
                CrossEncoderRerankerConfig(
                    model_path=args.reranker_model_path,
                    device=args.reranker_device,
                    use_fp16=args.reranker_fp16,
                )
            )

    records = read_jsonl(ROOT / args.input)[: args.limit]
    conn = connect(ROOT / args.sqlite_path)
    repository = TraceRepository(conn)
    policy = build_policy(args)
    rows = []
    for record in records:
        item = workflow_input_from_record(record)
        gold = item.get("gold") or {}
        try:
            dense_index = dense_index_for_blocks(item["blocks"], dense_encoder, args.retriever)
            retriever = IndexedDocumentRetriever(
                item["blocks"],
                mode=args.retriever,
                dense_encoder=dense_encoder,
                dense_index=dense_index,
                reranker=reranker,
            )
            state = run_qa_workflow(
                qid=item["qid"],
                doc_id=item["doc_id"],
                question=item["question"],
                blocks=item["blocks"],
                answer_policy=policy,
                top_k=min(5, len(item["blocks"])) if item["blocks"] else 5,
                answer_type_hint=item["answer_type"],
                trace_repository=repository,
                retriever=retriever,
            )
            pred_answer = str(state.final_answer.get("answer", ""))
            gold_answer = str(gold.get("answer", ""))
            loc_score = location_reward(state.final_answer.get("evidence_location") or {}, gold.get("evidence_location") or {})
            parse_result = state.parse_result or {}
            rows.append(
                {
                    "id": item["qid"],
                    "run_id": state.run_id,
                    "workflow_success": state.status == "completed",
                    "raw_json_ok": parse_result.get("raw_json_ok", bool(state.draft_answer)),
                    "recovered_json_ok": parse_result.get("recovered_json_ok", False),
                    "schema_ok": state.format_check.get("success", False),
                    "answer_em": exact_match(pred_answer, gold_answer) if gold_answer else False,
                    "answer_f1": token_f1(pred_answer, gold_answer) if gold_answer else 0.0,
                    "location_ok": loc_score == 1.0 if gold.get("evidence_location") else state.location_check.get("success", False),
                    "repair_attempted": state.repair_attempted,
                    "repair_success": state.repair_attempted and state.format_check.get("success", False) and state.location_check.get("success", False),
                    "latency_ms": state.generation_metadata.get("latency_ms"),
                    "retriever": args.retriever,
                    "dense_backend": args.dense_backend if args.retriever in {"dense", "hybrid", "hybrid_rerank"} else None,
                    "reranker_backend": args.reranker_backend if args.retriever == "hybrid_rerank" else None,
                    "prediction": state.final_answer,
                    "gold": gold,
                }
            )
        except Exception as exc:
            rows.append({"id": item.get("qid"), "workflow_success": False, "retriever": args.retriever, "error": str(exc)})

    write_jsonl(ROOT / args.output, rows)
    summary = summarize(rows)
    summary.update(
        {
            "input": args.input,
            "output": args.output,
            "policy_mode": args.policy_mode,
            "retriever": args.retriever,
            "dense_backend": args.dense_backend if args.retriever in {"dense", "hybrid", "hybrid_rerank"} else None,
            "reranker_backend": args.reranker_backend if args.retriever == "hybrid_rerank" else None,
        }
    )
    summary_path = ROOT / args.summary_output
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
