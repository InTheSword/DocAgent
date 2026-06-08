from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.eval.answer_metrics import exact_match, token_f1
from docagent.models.base import HeuristicAnswerPolicy
from docagent.models.qwen_answer_policy import QwenAnswerPolicy, QwenAnswerPolicyConfig
from docagent.rewards.location_reward import location_reward
from docagent.storage.db import connect
from docagent.storage.repositories import TraceRepository
from docagent.utils.jsonl import read_jsonl, write_jsonl
from docagent.workflow.graph import run_qa_workflow
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


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    if n == 0:
        return {"num_samples": 0}
    latencies = [row["latency_ms"] for row in rows if row.get("latency_ms") is not None]
    return {
        "num_samples": n,
        "workflow_success_rate": sum(row["workflow_success"] for row in rows) / n,
        "raw_json_rate": sum(row.get("raw_json_ok", False) for row in rows) / n,
        "recovered_json_rate": sum(row.get("recovered_json_ok", False) for row in rows) / n,
        "schema_pass_rate": sum(row.get("schema_ok", False) for row in rows) / n,
        "answer_em": sum(row.get("answer_em", False) for row in rows) / n,
        "answer_f1": sum(row.get("answer_f1", 0.0) for row in rows) / n,
        "location_accuracy": sum(row.get("location_ok", False) for row in rows) / n,
        "repair_trigger_rate": sum(row.get("repair_attempted", False) for row in rows) / n,
        "repair_success_rate": sum(row.get("repair_success", False) for row in rows) / n,
        "mean_latency_ms": statistics.mean(latencies) if latencies else 0.0,
        "p95_latency_ms": sorted(latencies)[int(len(latencies) * 0.95) - 1] if latencies else 0.0,
        "trace_persist_rate": sum(bool(row.get("run_id")) for row in rows) / n,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary-output", required=True)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--policy-mode", choices=["heuristic", "base", "sft", "grpo"], default="heuristic")
    parser.add_argument("--base-model-path", default="/root/autodl-tmp/models/Qwen3-1.7B")
    parser.add_argument("--adapter-path", default=None)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--torch-dtype", default="bfloat16")
    parser.add_argument("--max-prompt-tokens", type=int, default=4096)
    parser.add_argument("--max-new-tokens", type=int, default=384)
    parser.add_argument("--sqlite-path", default="outputs/traces/workflow_eval.sqlite")
    args = parser.parse_args()

    records = read_jsonl(ROOT / args.input)[: args.limit]
    conn = connect(ROOT / args.sqlite_path)
    repository = TraceRepository(conn)
    policy = build_policy(args)
    rows = []
    for record in records:
        item = workflow_input_from_record(record)
        gold = item.get("gold") or {}
        try:
            state = run_qa_workflow(
                qid=item["qid"],
                doc_id=item["doc_id"],
                question=item["question"],
                blocks=item["blocks"],
                answer_policy=policy,
                top_k=min(5, len(item["blocks"])) if item["blocks"] else 5,
                answer_type_hint=item["answer_type"],
                trace_repository=repository,
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
                    "prediction": state.final_answer,
                    "gold": gold,
                }
            )
        except Exception as exc:
            rows.append({"id": item.get("qid"), "workflow_success": False, "error": str(exc)})

    write_jsonl(ROOT / args.output, rows)
    summary = summarize(rows)
    summary.update({"input": args.input, "output": args.output, "policy_mode": args.policy_mode})
    summary_path = ROOT / args.summary_output
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
