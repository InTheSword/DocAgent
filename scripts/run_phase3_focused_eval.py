from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.eval.phase3_focused import (
    DEFAULT_BGE_MODEL_PATH,
    DEFAULT_QWEN_MODEL_PATH,
    DEFAULT_RERANKER_MODEL_PATH,
    DEFAULT_SEED,
    GRPO_DEFAULT_ADAPTER_PATH,
    SFT_DEFAULT_ADAPTER_PATH,
    run_focused_evaluation,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 3A focused retrieval and AnswerPolicy evaluation.")
    parser.add_argument("--benchmark-input", default="data/benchmark/mp_docvqa_imdb_ocr_5000_split/dev.jsonl")
    parser.add_argument("--qa-input", default=None)
    parser.add_argument("--corpus-input", default=None)
    parser.add_argument("--output-root", default="outputs/evaluation/phase3_focused_eval")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--answer-only", action="store_true")
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument("--retrieval-limit", type=int, default=300)
    parser.add_argument("--answer-limit", type=int, default=150)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--bm25-top-n", type=int, default=20)
    parser.add_argument("--dense-top-n", type=int, default=20)
    parser.add_argument("--fusion-top-n", type=int, default=20)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--dense-backend", choices=["bge", "hash"], default="bge")
    parser.add_argument("--dense-model-path", default=DEFAULT_BGE_MODEL_PATH)
    parser.add_argument("--dense-device", default="cuda:1")
    parser.add_argument("--dense-fp16", action="store_true")
    parser.add_argument("--reranker-backend", choices=["cross_encoder", "keyword"], default="cross_encoder")
    parser.add_argument("--reranker-model-path", default=DEFAULT_RERANKER_MODEL_PATH)
    parser.add_argument("--reranker-device", default="cuda:1")
    parser.add_argument("--reranker-fp16", action="store_true")
    parser.add_argument("--answer-backend", choices=["qwen", "heuristic"], default="qwen")
    parser.add_argument("--base-model-path", default=DEFAULT_QWEN_MODEL_PATH)
    parser.add_argument("--sft-adapter-path", default=SFT_DEFAULT_ADAPTER_PATH)
    parser.add_argument("--grpo-adapter-path", default=GRPO_DEFAULT_ADAPTER_PATH)
    parser.add_argument("--qwen-device", default="cuda:0")
    parser.add_argument("--qwen-torch-dtype", default="bfloat16")
    parser.add_argument("--max-prompt-tokens", type=int, default=4096)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument(
        "--allow-mock-backends",
        action="store_true",
        help="Allow hash dense, keyword reranker, or heuristic AnswerPolicy for local fixture tests only.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    exit_code = 0
    try:
        payload = run_focused_evaluation(args, root=ROOT)
    except Exception as exc:
        payload = getattr(exc, "payload", None)
        if payload is None:
            payload = {
                "command": "phase3_focused_eval",
                "status": "failed",
                "exception": f"{type(exc).__name__}: {exc}",
                "traceback_tail": traceback.format_exc().splitlines()[-20:],
            }
        exit_code = 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
