from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.models.base import HeuristicAnswerPolicy
from docagent.models.qwen_answer_policy import QwenAnswerPolicy, QwenAnswerPolicyConfig
from docagent.storage.db import connect
from docagent.storage.repositories import TraceRepository
from docagent.utils.jsonl import read_jsonl
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
            do_sample=args.do_sample,
            temperature=args.temperature,
            top_p=args.top_p,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--policy-mode", choices=["heuristic", "base", "sft", "grpo"], default="heuristic")
    parser.add_argument("--base-model-path", default="/root/autodl-tmp/models/Qwen3-1.7B")
    parser.add_argument("--adapter-path", default=None)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--torch-dtype", default="bfloat16")
    parser.add_argument("--max-prompt-tokens", type=int, default=4096)
    parser.add_argument("--max-new-tokens", type=int, default=384)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--do-sample", action="store_true")
    parser.add_argument("--sqlite-path", default="outputs/traces/workflow_smoke.sqlite")
    parser.add_argument("--output", default="outputs/traces/workflow_smoke.json")
    args = parser.parse_args()

    records = read_jsonl(ROOT / args.input)
    record = records[args.index]
    item = workflow_input_from_record(record)
    conn = connect(ROOT / args.sqlite_path)
    repository = TraceRepository(conn)
    policy = build_policy(args)
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
    payload = {
        "run_id": state.run_id,
        "qid": state.qid,
        "question": state.question,
        "rewritten_query": state.rewritten_query,
        "retrieved_block_ids": [block.block_id for block in state.retrieved_blocks],
        "draft_answer": state.draft_answer,
        "final_answer": state.final_answer,
        "format_check": state.format_check,
        "location_check": state.location_check,
        "repair_attempted": state.repair_attempted,
        "generation_metadata": state.generation_metadata,
        "parse_result": state.parse_result,
        "trace": state.trace,
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
