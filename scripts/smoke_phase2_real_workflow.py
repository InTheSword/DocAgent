from __future__ import annotations

import argparse
import gc
import json
import math
import sys
import traceback
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.models.qwen_answer_policy import QwenAnswerPolicy, QwenAnswerPolicyConfig
from docagent.parser.build_evidence_blocks import collect_evidence_blocks
from docagent.retrieval.base import RetrievalResult
from docagent.retrieval.dense_encoder import DenseEncoder, DenseEncoderConfig
from docagent.retrieval.dense_index import DenseIndex
from docagent.retrieval.index_manager import IndexedDocumentRetriever
from docagent.retrieval.reranker import CrossEncoderReranker, CrossEncoderRerankerConfig
from docagent.schemas import DocAgentSample, EvidenceBlock
from docagent.storage.db import connect
from docagent.storage.repositories import TraceRepository
from docagent.utils.jsonl import read_jsonl
from docagent.workflow.graph import run_qa_workflow


DENSE_BACKEND = "bge_m3"
RERANKER_BACKEND = CrossEncoderReranker.backend
DEFAULT_DENSE_MODEL_ID = "bge-m3-dense-1024"
DEFAULT_GRPO_ADAPTER_PATH = (
    "outputs/checkpoints/qwen3-docagent-trl-grpo-mpdocvqa-retrieved-grounded-100step-20260606_105535"
)


class ReleasingRetriever:
    def __init__(self, retriever: IndexedDocumentRetriever, *, dense_model_id: str) -> None:
        self.retriever = retriever
        self.dense_model_id = dense_model_id

    def retrieve(
        self,
        *,
        doc_id: str | None,
        question: str,
        top_k: int,
        answer_type_hint: str | None = None,
    ) -> RetrievalResult:
        result = self.retriever.retrieve(
            doc_id=doc_id,
            question=question,
            top_k=top_k,
            answer_type_hint=answer_type_hint,
        )
        result.metadata.update(
            {
                "dense_backend": DENSE_BACKEND,
                "dense_model_id": self.dense_model_id,
                "reranker_backend": RERANKER_BACKEND,
                "no_mock_fallback": True,
            }
        )
        release_retriever_models(self.retriever)
        return result


def resolve_repo_path(path: str | Path) -> Path:
    resolved = Path(path)
    return resolved if resolved.is_absolute() else ROOT / resolved


def require_model_dir(path: Path, *, name: str) -> None:
    if not path.is_dir():
        raise FileNotFoundError(f"{name} model directory does not exist: {path}")
    if not (path / "config.json").is_file():
        raise FileNotFoundError(f"{name} model directory is missing config.json: {path}")
    tokenizer_files = ["tokenizer.json", "tokenizer_config.json", "sentencepiece.bpe.model"]
    if not any((path / item).is_file() for item in tokenizer_files):
        raise FileNotFoundError(f"{name} model directory is missing tokenizer files: {path}")
    weight_files = list(path.glob("*.bin")) + list(path.glob("*.safetensors"))
    if not weight_files:
        raise FileNotFoundError(f"{name} model directory is missing local weight files: {path}")


def require_qwen_paths(*, base_model_path: Path, adapter_path: Path, mode: str) -> None:
    if not (base_model_path / "config.json").is_file():
        raise FileNotFoundError(f"Qwen base model is missing config.json: {base_model_path}")
    if mode in {"sft", "grpo"}:
        if not adapter_path.is_dir():
            raise FileNotFoundError(f"Qwen adapter path does not exist: {adapter_path}")
        if not (adapter_path / "adapter_config.json").is_file():
            raise FileNotFoundError(f"Qwen adapter is missing adapter_config.json: {adapter_path}")
        if not any((adapter_path / name).is_file() for name in ("adapter_model.safetensors", "adapter_model.bin")):
            raise FileNotFoundError(f"Qwen adapter is missing adapter weights: {adapter_path}")


def load_samples(path: Path) -> list[DocAgentSample]:
    records = read_jsonl(path)
    samples = [DocAgentSample.from_dict(record) for record in records]
    if not samples:
        raise RuntimeError(f"no samples found in {path}")
    return samples


def select_sample(samples: list[DocAgentSample], *, qid: str, doc_id: str) -> DocAgentSample:
    for sample in samples:
        if sample.qid == qid and sample.doc_id == doc_id:
            return sample
    raise RuntimeError(f"sample not found: qid={qid}, doc_id={doc_id}")


def selected_doc_blocks(samples: list[DocAgentSample], *, doc_id: str) -> list[EvidenceBlock]:
    blocks = [block for block in collect_evidence_blocks(samples) if block.doc_id == doc_id]
    if not blocks:
        raise RuntimeError(f"no EvidenceBlock records found for doc_id={doc_id}")
    return blocks


def validate_no_mock_fallback(*, dense_backend: str, reranker_backend: str, policy_mode: str) -> None:
    if dense_backend != DENSE_BACKEND:
        raise RuntimeError(f"expected dense_backend={DENSE_BACKEND}, got {dense_backend}")
    if reranker_backend != RERANKER_BACKEND:
        raise RuntimeError(f"expected reranker_backend={RERANKER_BACKEND}, got {reranker_backend}")
    if policy_mode != "grpo":
        raise RuntimeError(f"expected GRPO AnswerPolicy, got {policy_mode}")


def validate_embeddings(embeddings: np.ndarray, *, expected_rows: int, expected_dim: int) -> None:
    if embeddings.ndim != 2:
        raise RuntimeError(f"expected 2D embeddings, got shape={embeddings.shape}")
    if embeddings.shape[0] != expected_rows:
        raise RuntimeError(f"expected {expected_rows} embeddings, got shape={embeddings.shape}")
    if embeddings.shape[1] != expected_dim:
        raise RuntimeError(f"expected embedding_dim={expected_dim}, got shape={embeddings.shape}")
    if not np.isfinite(embeddings).all():
        raise RuntimeError("embeddings contain non-finite values")


def build_real_retriever(
    *,
    blocks: list[EvidenceBlock],
    bge_model_path: Path,
    reranker_model_path: Path,
    device: str,
    use_fp16: bool,
    dense_model_id: str,
    expected_embedding_dim: int,
    dense_batch_size: int,
    reranker_batch_size: int,
    dense_max_length: int,
    reranker_max_length: int,
) -> ReleasingRetriever:
    encoder = DenseEncoder(
        DenseEncoderConfig(
            model_path=str(bge_model_path),
            device=device,
            use_fp16=use_fp16,
            batch_size=dense_batch_size,
            max_length=dense_max_length,
        )
    )
    embeddings = encoder.encode_documents([block.retrieval_text for block in blocks])
    validate_embeddings(embeddings, expected_rows=len(blocks), expected_dim=expected_embedding_dim)
    dense_index = DenseIndex.build(blocks=blocks, embeddings=embeddings, model_id=dense_model_id)
    if dense_index.backend != "faiss":
        raise RuntimeError(f"real workflow smoke requires FAISS backend, got {dense_index.backend}")
    reranker = CrossEncoderReranker(
        CrossEncoderRerankerConfig(
            model_path=str(reranker_model_path),
            device=device,
            use_fp16=use_fp16,
            batch_size=reranker_batch_size,
            max_length=reranker_max_length,
        )
    )
    return ReleasingRetriever(
        IndexedDocumentRetriever(
            blocks,
            mode="hybrid_rerank",
            dense_encoder=encoder,
            dense_index=dense_index,
            reranker=reranker,
        ),
        dense_model_id=dense_model_id,
    )


def build_grpo_policy(args: argparse.Namespace) -> QwenAnswerPolicy:
    require_qwen_paths(
        base_model_path=Path(args.base_model_path),
        adapter_path=resolve_repo_path(args.adapter_path),
        mode="grpo",
    )
    return QwenAnswerPolicy(
        QwenAnswerPolicyConfig(
            mode="grpo",
            base_model_path=args.base_model_path,
            adapter_path=str(resolve_repo_path(args.adapter_path)),
            device=args.qwen_device,
            torch_dtype=args.qwen_torch_dtype,
            max_prompt_tokens=args.max_prompt_tokens,
            max_new_tokens=args.max_new_tokens,
            do_sample=False,
        )
    )


def release_gpu_memory() -> None:
    gc.collect()
    try:
        import torch
    except ImportError:
        return
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        try:
            torch.cuda.ipc_collect()
        except Exception:
            pass


def release_retriever_models(retriever: IndexedDocumentRetriever) -> None:
    if getattr(retriever, "dense_encoder", None) is not None:
        retriever.dense_encoder._model = None
    reranker = getattr(getattr(retriever, "hybrid", None), "reranker", None)
    if reranker is not None:
        if hasattr(reranker, "_model"):
            reranker._model = None
        if hasattr(reranker, "_tokenizer"):
            reranker._tokenizer = None
    release_gpu_memory()


def release_policy_model(policy: QwenAnswerPolicy) -> None:
    if hasattr(policy, "_model"):
        policy._model = None
    if hasattr(policy, "_tokenizer"):
        policy._tokenizer = None
    if hasattr(policy, "_loaded"):
        policy._loaded = False
    release_gpu_memory()


def trace_by_node(traces: list[dict[str, Any]], node_name: str) -> dict[str, Any] | None:
    for trace in traces:
        if trace.get("node_name") == node_name:
            return trace
    return None


def top_k_ids_from_retrieval_trace(retrieval_trace: dict[str, Any] | None) -> list[str]:
    if not retrieval_trace:
        return []
    output = retrieval_trace.get("output_summary") or {}
    return [str(item) for item in output.get("block_ids") or []]


def validate_run_artifacts(
    *,
    state,
    trace_repository: TraceRepository,
    doc_id: str,
    gold_block_id: str,
) -> dict[str, Any]:
    if not state.run_id:
        raise RuntimeError("workflow did not create a run_id")
    run = trace_repository.get_run(state.run_id)
    traces = trace_repository.list_traces(state.run_id)
    if run is None:
        raise RuntimeError(f"SQLite run lookup failed for run_id={state.run_id}")
    retrieval_trace = trace_by_node(traces, "retrieve_evidence")
    answer_trace = trace_by_node(traces, "generate_answer")
    if retrieval_trace is None:
        raise RuntimeError("SQLite trace is missing retrieve_evidence")
    if answer_trace is None:
        raise RuntimeError("SQLite trace is missing generate_answer")
    retrieval_output = retrieval_trace.get("output_summary") or {}
    candidates = retrieval_output.get("candidates") or []
    all_candidates_same_doc = bool(candidates) and all(candidate.get("doc_id") == doc_id for candidate in candidates)
    top_k_block_ids = top_k_ids_from_retrieval_trace(retrieval_trace)
    final_location = state.final_answer.get("evidence_location") if isinstance(state.final_answer, dict) else {}
    final_block_id = final_location.get("block_id") if isinstance(final_location, dict) else None
    final_location_in_top_k = final_block_id in set(top_k_block_ids)
    return {
        "run": run,
        "traces": traces,
        "retrieval_trace": retrieval_trace,
        "answer_trace": answer_trace,
        "retrieval_output": retrieval_output,
        "all_candidates_same_doc": all_candidates_same_doc,
        "gold_block_in_top_k": gold_block_id in set(top_k_block_ids),
        "top_k_block_ids": top_k_block_ids,
        "final_location_in_top_k": final_location_in_top_k,
        "final_location_block_id": final_block_id,
        "retrieval_trace_present": bool(candidates and retrieval_output.get("dense_backend") == DENSE_BACKEND),
        "answer_trace_present": bool((answer_trace.get("output_summary") or {}).get("raw_preview")),
    }


def build_success_payload(
    *,
    args: argparse.Namespace,
    sample: DocAgentSample,
    state,
    artifacts: dict[str, Any],
    sqlite_path: Path,
) -> dict[str, Any]:
    retrieval_output = artifacts["retrieval_output"]
    parse_result = state.parse_result or {}
    final_answer = state.final_answer if isinstance(state.final_answer, dict) else {}
    location = final_answer.get("evidence_location") or {}
    format_valid = bool(state.format_check.get("success"))
    location_valid = bool(state.location_check.get("success"))
    if not artifacts["all_candidates_same_doc"]:
        raise RuntimeError("retrieval returned candidates outside the selected doc_id")
    if not artifacts["gold_block_in_top_k"]:
        raise RuntimeError(f"gold block is not in top-k: {args.gold_block_id}")
    if not artifacts["final_location_in_top_k"]:
        raise RuntimeError(f"final location is not in top-k: {location}")
    if artifacts["final_location_block_id"] != args.gold_block_id:
        raise RuntimeError(f"final block_id must be {args.gold_block_id}, got {artifacts['final_location_block_id']}")
    if not format_valid or not location_valid:
        raise RuntimeError(f"workflow validation failed: format={state.format_check}, location={state.location_check}")
    if not artifacts["retrieval_trace_present"] or not artifacts["answer_trace_present"]:
        raise RuntimeError("SQLite trace is missing retrieval or answer details")

    return {
        "command": "phase2_real_workflow_smoke",
        "status": "success",
        "qid": sample.qid,
        "doc_id": sample.doc_id,
        "retrieval": {
            "mode": retrieval_output.get("retriever_mode"),
            "dense_backend": retrieval_output.get("dense_backend"),
            "dense_model_id": retrieval_output.get("dense_model_id"),
            "reranker_backend": retrieval_output.get("reranker_backend"),
            "all_candidates_same_doc": artifacts["all_candidates_same_doc"],
            "gold_block_in_top_k": artifacts["gold_block_in_top_k"],
            "top_k_block_ids": artifacts["top_k_block_ids"],
            "candidates": retrieval_output.get("candidates") or [],
        },
        "answer_policy": {
            "mode": state.generation_metadata.get("policy_mode"),
            "model_loaded": True,
            "base_model_path": args.base_model_path,
            "adapter_path": str(resolve_repo_path(args.adapter_path)),
            "device": args.qwen_device,
            "raw_output_present": artifacts["answer_trace_present"],
        },
        "validation": {
            "json_parsed": bool(parse_result.get("schema_ok") or state.draft_answer),
            "format_valid": format_valid,
            "location_valid": location_valid,
            "final_location_in_top_k": artifacts["final_location_in_top_k"],
            "repair_attempted": state.repair_attempted,
            "repair_result": state.repair_result,
        },
        "final": {
            "answer": final_answer.get("answer"),
            "location": location,
        },
        "trace": {
            "persisted": True,
            "sqlite_path": str(sqlite_path),
            "run_id": state.run_id,
            "retrieval_trace_present": artifacts["retrieval_trace_present"],
            "answer_trace_present": artifacts["answer_trace_present"],
            "trace_nodes": [trace.get("node_name") for trace in artifacts["traces"]],
        },
        "no_gold_leakage": True,
        "no_mock_fallback": True,
    }


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    validate_no_mock_fallback(
        dense_backend=DENSE_BACKEND,
        reranker_backend=RERANKER_BACKEND,
        policy_mode="grpo",
    )
    input_path = resolve_repo_path(args.input)
    sqlite_path = resolve_repo_path(args.sqlite_path)
    bge_model_path = Path(args.bge_model_path)
    reranker_model_path = Path(args.reranker_model_path)
    require_model_dir(bge_model_path, name="BGE-M3")
    require_model_dir(reranker_model_path, name="bge-reranker-v2-m3")

    samples = load_samples(input_path)
    sample = select_sample(samples, qid=args.qid, doc_id=args.doc_id)
    blocks = selected_doc_blocks(samples, doc_id=args.doc_id)
    if any(block.doc_id != args.doc_id for block in blocks):
        raise RuntimeError(f"selected blocks contain records outside doc_id={args.doc_id}")

    retriever = build_real_retriever(
        blocks=blocks,
        bge_model_path=bge_model_path,
        reranker_model_path=reranker_model_path,
        device=args.retrieval_device,
        use_fp16=not args.no_fp16,
        dense_model_id=args.dense_model_id,
        expected_embedding_dim=args.expected_embedding_dim,
        dense_batch_size=args.dense_batch_size,
        reranker_batch_size=args.reranker_batch_size,
        dense_max_length=args.dense_max_length,
        reranker_max_length=args.reranker_max_length,
    )
    policy = build_grpo_policy(args)
    conn = connect(sqlite_path)
    trace_repository = TraceRepository(conn)
    try:
        state = run_qa_workflow(
            qid=sample.qid,
            doc_id=args.doc_id,
            question=sample.question,
            blocks=blocks,
            answer_policy=policy,
            top_k=min(args.top_k, len(blocks)),
            answer_type_hint=sample.answer_type,
            trace_repository=trace_repository,
            retriever=retriever,
        )
        artifacts = validate_run_artifacts(
            state=state,
            trace_repository=trace_repository,
            doc_id=args.doc_id,
            gold_block_id=args.gold_block_id,
        )
        return build_success_payload(
            args=args,
            sample=sample,
            state=state,
            artifacts=artifacts,
            sqlite_path=sqlite_path,
        )
    finally:
        release_policy_model(policy)


def exception_payload(exc: Exception) -> dict[str, Any]:
    return {
        "command": "phase2_real_workflow_smoke",
        "status": "failed",
        "exception": f"{type(exc).__name__}: {exc}",
        "traceback_tail": traceback.format_exc().splitlines()[-20:],
        "no_gold_leakage": True,
        "no_mock_fallback": True,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/benchmark/smoke_eval.jsonl")
    parser.add_argument("--output", default="outputs/smoke/phase2_real_workflow.json")
    parser.add_argument("--sqlite-path", default="outputs/smoke/phase2_real_workflow.sqlite")
    parser.add_argument("--qid", default="smoke_invoice_date")
    parser.add_argument("--doc-id", default="smoke_invoice")
    parser.add_argument("--gold-block-id", default="smoke_invoice_p1_b1")
    parser.add_argument("--bge-model-path", default="/root/autodl-tmp/models/bge-m3")
    parser.add_argument("--reranker-model-path", default="/root/autodl-tmp/models/bge-reranker-v2-m3")
    parser.add_argument("--retrieval-device", default="cuda:1")
    parser.add_argument("--dense-model-id", default=DEFAULT_DENSE_MODEL_ID)
    parser.add_argument("--expected-embedding-dim", type=int, default=1024)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--dense-batch-size", type=int, default=8)
    parser.add_argument("--reranker-batch-size", type=int, default=4)
    parser.add_argument("--dense-max-length", type=int, default=1024)
    parser.add_argument("--reranker-max-length", type=int, default=1024)
    parser.add_argument("--no-fp16", action="store_true")
    parser.add_argument("--base-model-path", default="/root/autodl-tmp/models/Qwen3-1.7B")
    parser.add_argument("--adapter-path", default=DEFAULT_GRPO_ADAPTER_PATH)
    parser.add_argument("--qwen-device", default="cuda:0")
    parser.add_argument("--qwen-torch-dtype", default="bfloat16")
    parser.add_argument("--max-prompt-tokens", type=int, default=4096)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = resolve_repo_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    exit_code = 0
    try:
        payload = run_smoke(args)
    except Exception as exc:
        payload = exception_payload(exc)
        exit_code = 1
    finally:
        release_gpu_memory()
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
