from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.models.base import HeuristicAnswerPolicy
from docagent.models.qwen_answer_policy import QwenAnswerPolicy, QwenAnswerPolicyConfig
from docagent.retrieval.dense_encoder import DenseEncoder, DenseEncoderConfig, HashDenseEncoder
from docagent.retrieval.dense_index import DenseIndex
from docagent.retrieval.index_manager import IndexedDocumentRetriever
from docagent.retrieval.reranker import CrossEncoderReranker, CrossEncoderRerankerConfig, KeywordOverlapReranker
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository, TraceRepository
from docagent.workflow.graph import run_qa_workflow


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
    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--retriever", choices=["bm25", "dense", "hybrid", "hybrid_rerank"], default="bm25")
    parser.add_argument("--policy-mode", choices=["heuristic", "base", "sft", "grpo"], default="heuristic")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--sqlite-path", default="outputs/docagent.db")
    parser.add_argument("--document-root", default="data/documents")
    parser.add_argument("--dense-backend", choices=["bge", "hash"], default="bge")
    parser.add_argument("--dense-model-path")
    parser.add_argument("--dense-device", default="cpu")
    parser.add_argument("--dense-fp16", action="store_true")
    parser.add_argument("--build-index-if-missing", action="store_true")
    parser.add_argument("--reranker-backend", choices=["cross_encoder", "keyword"], default="cross_encoder")
    parser.add_argument("--reranker-model-path")
    parser.add_argument("--reranker-device", default="cpu")
    parser.add_argument("--reranker-fp16", action="store_true")
    parser.add_argument("--base-model-path", default="/root/autodl-tmp/models/Qwen3-1.7B")
    parser.add_argument("--adapter-path")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--torch-dtype", default="bfloat16")
    parser.add_argument("--max-prompt-tokens", type=int, default=4096)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--do-sample", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()

    conn = connect(ROOT / args.sqlite_path)
    document_repository = DocumentRepository(conn)
    trace_repository = TraceRepository(conn)
    blocks = document_repository.load_evidence_blocks(args.doc_id)
    if not blocks:
        raise SystemExit(f"no evidence blocks found for doc_id={args.doc_id}")

    dense_encoder = None
    dense_index = None
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
        index_dir = ROOT / args.document_root / args.doc_id
        index_metadata = index_dir / f"index_metadata_{dense_encoder.model_id.replace('/', '_')}.json"
        legacy_index_metadata = index_dir / "index_metadata.json"
        if not index_metadata.exists() and legacy_index_metadata.exists() and args.dense_backend == "bge":
            index_metadata = legacy_index_metadata
        if not index_metadata.exists():
            if not args.build_index_if_missing:
                raise SystemExit(
                    f"dense index is missing for doc_id={args.doc_id}: {index_metadata}. "
                    "Run scripts/ingest_document.py with --build-index, or pass --build-index-if-missing."
                )
            embeddings = dense_encoder.encode_documents([block.retrieval_text for block in blocks])
            dense_index = DenseIndex.build(blocks=blocks, embeddings=embeddings, model_id=dense_encoder.model_id)
            metadata = dense_index.save(index_dir)
            model_index_metadata = index_dir / f"index_metadata_{dense_encoder.model_id.replace('/', '_')}.json"
            model_index_metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
            document_repository.save_index_metadata(
                doc_id=args.doc_id,
                index_type="dense",
                model_id=str(metadata.get("model_id") or ""),
                artifact_path=str(index_dir),
                metadata=metadata,
            )
        else:
            dense_index = DenseIndex.load(index_dir=index_dir, blocks=blocks, metadata_path=index_metadata)

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

    retriever = IndexedDocumentRetriever(
        blocks,
        mode=args.retriever,
        dense_encoder=dense_encoder,
        dense_index=dense_index,
        reranker=reranker,
    )
    policy = build_policy(args)
    state = run_qa_workflow(
        qid=f"query_{args.doc_id}",
        doc_id=args.doc_id,
        question=args.question,
        blocks=blocks,
        answer_policy=policy,
        top_k=args.top_k,
        answer_type_hint="extractive",
        trace_repository=trace_repository,
        retriever=retriever,
    )
    payload = {
        "run_id": state.run_id,
        "doc_id": args.doc_id,
        "question": args.question,
        "retriever": args.retriever,
        "dense_backend": args.dense_backend if args.retriever in {"dense", "hybrid", "hybrid_rerank"} else None,
        "reranker_backend": args.reranker_backend if args.retriever == "hybrid_rerank" else None,
        "final_answer": state.final_answer,
        "top_k_evidence": [block.to_dict() for block in state.retrieved_blocks],
        "trace": state.trace,
    }
    if args.output:
        output = ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
