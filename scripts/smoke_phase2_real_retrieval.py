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

from docagent.parser.build_evidence_blocks import collect_evidence_blocks
from docagent.retrieval.bm25_index import BM25Index
from docagent.retrieval.dense_encoder import DenseEncoder, DenseEncoderConfig
from docagent.retrieval.dense_index import DenseIndex
from docagent.retrieval.fusion import reciprocal_rank_fusion
from docagent.retrieval.query_rewrite import rewrite_query
from docagent.retrieval.reranker import CrossEncoderReranker, CrossEncoderRerankerConfig
from docagent.schemas import DocAgentSample
from docagent.utils.jsonl import read_jsonl


DENSE_BACKEND = "bge_m3"
RERANKER_BACKEND = CrossEncoderReranker.backend
DEFAULT_DENSE_MODEL_ID = "bge-m3-dense-1024"


def resolve_repo_path(path: str | Path) -> Path:
    resolved = Path(path)
    return resolved if resolved.is_absolute() else ROOT / resolved


def dense_artifact_prefix(model_id: str) -> str:
    if model_id.startswith("hash-dense"):
        raise RuntimeError(f"real retrieval smoke cannot use mock dense model_id={model_id}")
    if any(part in model_id for part in ("/", "\\", ":", "\0")):
        raise RuntimeError(f"dense model_id must be safe for artifact filenames: {model_id!r}")
    return model_id


def dense_metadata_path(index_dir: str | Path, model_id: str) -> Path:
    return Path(index_dir) / f"index_metadata_{dense_artifact_prefix(model_id)}.json"


def validate_real_backends(*, dense_backend: str, reranker_backend: str, dense_model_id: str) -> None:
    if dense_backend != DENSE_BACKEND:
        raise RuntimeError(f"expected dense_backend={DENSE_BACKEND}, got {dense_backend}")
    if reranker_backend != RERANKER_BACKEND:
        raise RuntimeError(f"expected reranker_backend={RERANKER_BACKEND}, got {reranker_backend}")
    if dense_model_id.startswith("hash-dense"):
        raise RuntimeError(f"mock dense index is not allowed: {dense_model_id}")
    if reranker_backend == "keyword":
        raise RuntimeError("keyword reranker is not allowed for real retrieval smoke")


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


def load_samples(path: Path) -> list[DocAgentSample]:
    records = read_jsonl(path)
    samples = [DocAgentSample.from_dict(record) for record in records]
    if not samples:
        raise RuntimeError(f"no samples found in {path}")
    return samples


def select_sample(samples: list[DocAgentSample], sample_index: int) -> DocAgentSample:
    if sample_index < 0 or sample_index >= len(samples):
        raise RuntimeError(f"sample_index={sample_index} is out of range for {len(samples)} samples")
    sample = samples[sample_index]
    if not sample.evidence:
        raise RuntimeError(f"selected sample has no EvidenceBlock records: qid={sample.qid}")
    return sample


def json_float(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        raise RuntimeError(f"non-finite score cannot be serialized: {value}")
    return number


def candidate_payload(
    candidate,
    *,
    final_rank: int,
    dense_model_id: str,
    reranker_model_path: str,
) -> dict[str, object]:
    location = candidate.block.location.to_dict()
    page = candidate.block.page_id if candidate.block.page_id is not None else location.get("page")
    return {
        "block_id": candidate.block.block_id,
        "doc_id": candidate.block.doc_id,
        "page": page,
        "location": location,
        "block_type": candidate.block.block_type,
        "bm25_score": json_float(candidate.bm25_score),
        "bm25_rank": candidate.ranks.get("bm25"),
        "dense_score": json_float(candidate.dense_score),
        "dense_rank": candidate.ranks.get("dense"),
        "rrf_score": json_float(candidate.rrf_score),
        "rrf_rank": candidate.ranks.get("rrf"),
        "reranker_score": json_float(candidate.rerank_score),
        "reranker_rank": candidate.ranks.get("reranker"),
        "final_rank": final_rank,
        "sources": list(candidate.sources),
        "dense_backend": DENSE_BACKEND,
        "dense_model_id": dense_model_id,
        "reranker_backend": RERANKER_BACKEND,
        "reranker_model_path": reranker_model_path,
    }


def validate_embeddings(embeddings: np.ndarray, *, expected_rows: int, expected_dim: int) -> None:
    if embeddings.ndim != 2:
        raise RuntimeError(f"expected 2D embeddings, got shape={embeddings.shape}")
    if embeddings.shape[0] != expected_rows:
        raise RuntimeError(f"expected {expected_rows} embeddings, got shape={embeddings.shape}")
    if embeddings.shape[1] != expected_dim:
        raise RuntimeError(f"expected embedding_dim={expected_dim}, got shape={embeddings.shape}")
    if not np.isfinite(embeddings).all():
        raise RuntimeError("embeddings contain non-finite values")


def validate_dense_reload_stability(
    *,
    original: DenseIndex,
    loaded: DenseIndex,
    query_embedding: np.ndarray,
    top_k: int,
) -> dict[str, object]:
    original_hits = original.search(query_embedding, top_k=top_k)
    loaded_hits = loaded.search(query_embedding, top_k=top_k)
    original_ids = [hit.block.block_id for hit in original_hits]
    loaded_ids = [hit.block.block_id for hit in loaded_hits]
    original_scores = [hit.score for hit in original_hits]
    loaded_scores = [hit.score for hit in loaded_hits]
    stable = original_ids == loaded_ids and np.allclose(original_scores, loaded_scores, atol=1e-6)
    if not stable:
        raise RuntimeError(
            "dense index reload changed search results: "
            f"original={original_ids}, loaded={loaded_ids}"
        )
    return {
        "stable": True,
        "block_ids": loaded_ids,
    }


def run_smoke(args: argparse.Namespace) -> dict[str, object]:
    validate_real_backends(
        dense_backend=DENSE_BACKEND,
        reranker_backend=RERANKER_BACKEND,
        dense_model_id=args.dense_model_id,
    )
    input_path = resolve_repo_path(args.input)
    bge_model_path = Path(args.bge_model_path)
    reranker_model_path = Path(args.reranker_model_path)
    require_model_dir(bge_model_path, name="BGE-M3")
    require_model_dir(reranker_model_path, name="bge-reranker-v2-m3")

    samples = load_samples(input_path)
    sample = select_sample(samples, args.sample_index)
    blocks = collect_evidence_blocks(samples)
    if not blocks:
        raise RuntimeError("no EvidenceBlock records found in smoke input")
    doc_ids = sorted({block.doc_id for block in blocks})

    encoder = DenseEncoder(
        DenseEncoderConfig(
            model_path=str(bge_model_path),
            device=args.device,
            use_fp16=not args.no_fp16,
            batch_size=args.dense_batch_size,
            max_length=args.dense_max_length,
        )
    )
    embeddings = encoder.encode_documents([block.retrieval_text for block in blocks])
    validate_embeddings(embeddings, expected_rows=len(blocks), expected_dim=args.expected_embedding_dim)
    query_embedding = encoder.encode_queries([sample.question])
    validate_embeddings(query_embedding, expected_rows=1, expected_dim=args.expected_embedding_dim)

    dense_index = DenseIndex.build(blocks=blocks, embeddings=embeddings, model_id=args.dense_model_id)
    if dense_index.backend != "faiss":
        raise RuntimeError(f"real retrieval smoke requires FAISS backend, got {dense_index.backend}")
    index_dir = resolve_repo_path(args.index_dir)
    metadata = dense_index.save(index_dir, artifact_prefix=dense_artifact_prefix(args.dense_model_id))
    metadata_path = dense_metadata_path(index_dir, args.dense_model_id)
    faiss_path = Path(str(metadata.get("faiss_path") or ""))
    if not metadata_path.is_file():
        raise RuntimeError(f"dense index metadata was not saved: {metadata_path}")
    if not faiss_path.is_file():
        raise RuntimeError(f"FAISS index file was not saved: {faiss_path}")
    loaded_index = DenseIndex.load(index_dir=index_dir, blocks=blocks, metadata_path=metadata_path)
    reload_check = validate_dense_reload_stability(
        original=dense_index,
        loaded=loaded_index,
        query_embedding=query_embedding,
        top_k=min(args.dense_top_n, len(blocks)),
    )

    rewrite = rewrite_query(sample.question, answer_type_hint=sample.answer_type)
    retrieval_query = f"{sample.question} {rewrite.rewritten_query}".strip()
    bm25_hits = BM25Index(blocks).search(retrieval_query, top_k=min(args.bm25_top_n, len(blocks)))
    dense_hits = [
        (hit.block, hit.score)
        for hit in loaded_index.search(query_embedding, top_k=min(args.dense_top_n, len(blocks)))
    ]
    fused = reciprocal_rank_fusion({"bm25": bm25_hits, "dense": dense_hits}, rrf_k=args.rrf_k)[: args.fusion_top_n]
    for rank, candidate in enumerate(fused, start=1):
        candidate.ranks["rrf"] = rank

    reranker = CrossEncoderReranker(
        CrossEncoderRerankerConfig(
            model_path=str(reranker_model_path),
            device=args.device,
            use_fp16=not args.no_fp16,
            batch_size=args.reranker_batch_size,
            max_length=args.reranker_max_length,
        )
    )
    reranked = reranker.score(query=retrieval_query, candidates=fused)
    final_candidates = reranked[: args.top_k]
    if not final_candidates:
        raise RuntimeError("real retrieval smoke produced no final candidates")

    candidate_json = [
        candidate_payload(
            candidate,
            final_rank=rank,
            dense_model_id=args.dense_model_id,
            reranker_model_path=str(reranker_model_path),
        )
        for rank, candidate in enumerate(final_candidates, start=1)
    ]
    json.dumps(candidate_json, ensure_ascii=False)

    return {
        "command": "phase2_real_retrieval_smoke",
        "status": "success",
        "input": str(input_path),
        "selected_sample": {
            "qid": sample.qid,
            "doc_id": sample.doc_id,
            "answer_type": sample.answer_type,
            "gold_block_ids": sorted(sample.metadata.get("gold_block_ids") or [block.block_id for block in sample.evidence]),
        },
        "corpus": {
            "scope": "all_input_evidence_blocks",
            "num_samples": len(samples),
            "num_docs": len(doc_ids),
            "doc_ids": doc_ids,
            "num_blocks": len(blocks),
        },
        "dense": {
            "backend": DENSE_BACKEND,
            "model_id": args.dense_model_id,
            "model_path": str(bge_model_path),
            "device": args.device,
            "dtype": "float16" if not args.no_fp16 and args.device.startswith("cuda") else "float32",
            "embedding_dim": int(embeddings.shape[1]),
            "embeddings_shape": list(embeddings.shape),
            "embeddings_finite": bool(np.isfinite(embeddings).all()),
            "query_embedding_shape": list(query_embedding.shape),
            "query_embedding_finite": bool(np.isfinite(query_embedding).all()),
            "index_backend": dense_index.backend,
            "index_saved": True,
            "index_reloaded": True,
            "index_reload_stable": reload_check["stable"],
            "metadata_path": str(metadata_path),
            "faiss_path": str(faiss_path),
        },
        "fusion": {
            "method": "rrf",
            "rrf_k": args.rrf_k,
            "bm25_top_n": args.bm25_top_n,
            "dense_top_n": args.dense_top_n,
            "fusion_top_n": args.fusion_top_n,
            "bm25_hits": len(bm25_hits),
            "dense_hits": len(dense_hits),
            "rrf_candidates": len(fused),
        },
        "reranker": {
            "backend": RERANKER_BACKEND,
            "model_path": str(reranker_model_path),
            "device": reranker.metadata["device"],
            "dtype": reranker.metadata["dtype"],
            "max_length": reranker.metadata["max_length"],
            "scores_count": len(reranked),
            "scores_finite": all(
                candidate.rerank_score is not None and math.isfinite(float(candidate.rerank_score))
                for candidate in reranked
            ),
        },
        "query": sample.question,
        "rewritten_query": rewrite.rewritten_query,
        "candidates": candidate_json,
        "no_mock_fallback": True,
    }


def exception_payload(exc: Exception) -> dict[str, object]:
    return {
        "command": "phase2_real_retrieval_smoke",
        "status": "failed",
        "exception": f"{type(exc).__name__}: {exc}",
        "traceback_tail": traceback.format_exc().splitlines()[-20:],
        "no_mock_fallback": True,
    }


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/benchmark/smoke_eval.jsonl")
    parser.add_argument("--output", default="outputs/smoke/phase2_real_retrieval.json")
    parser.add_argument("--index-dir", default="outputs/smoke/phase2_real_retrieval_index")
    parser.add_argument("--sample-index", type=int, default=0)
    parser.add_argument("--bge-model-path", default="/root/autodl-tmp/models/bge-m3")
    parser.add_argument("--reranker-model-path", default="/root/autodl-tmp/models/bge-reranker-v2-m3")
    parser.add_argument("--device", default="cuda:1")
    parser.add_argument("--dense-model-id", default=DEFAULT_DENSE_MODEL_ID)
    parser.add_argument("--expected-embedding-dim", type=int, default=1024)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--bm25-top-n", type=int, default=20)
    parser.add_argument("--dense-top-n", type=int, default=20)
    parser.add_argument("--fusion-top-n", type=int, default=20)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--dense-batch-size", type=int, default=8)
    parser.add_argument("--dense-max-length", type=int, default=1024)
    parser.add_argument("--reranker-batch-size", type=int, default=4)
    parser.add_argument("--reranker-max-length", type=int, default=1024)
    parser.add_argument("--no-fp16", action="store_true")
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
