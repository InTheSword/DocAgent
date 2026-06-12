from __future__ import annotations

import argparse
import json
import math
import sys
import traceback
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.retrieval.base import RetrievalCandidate
from docagent.retrieval.dense_encoder import DenseEncoder, DenseEncoderConfig
from docagent.retrieval.reranker import CrossEncoderReranker, CrossEncoderRerankerConfig
from docagent.schemas import EvidenceBlock, EvidenceLocation


BGE_REQUIRED_FILES = [
    "config.json",
    "pytorch_model.bin",
    "sentencepiece.bpe.model",
    "sparse_linear.pt",
    "colbert_linear.pt",
    "tokenizer.json",
    "tokenizer_config.json",
]

RERANKER_REQUIRED_FILES = [
    "config.json",
    "model.safetensors",
    "sentencepiece.bpe.model",
    "tokenizer.json",
    "tokenizer_config.json",
]


def _missing_files(path: Path, names: list[str]) -> list[str]:
    return [str(path / name) for name in names if not (path / name).is_file()]


def _model_device(model: Any) -> str | None:
    inner = getattr(model, "model", model)
    try:
        return str(next(inner.parameters()).device)
    except Exception:
        return None


def _exception_payload(exc: Exception) -> dict[str, object]:
    return {
        "status": "failed",
        "exception": f"{type(exc).__name__}: {exc}",
        "traceback_tail": traceback.format_exc().splitlines()[-20:],
    }


def _block(block_id: str, text: str) -> EvidenceBlock:
    return EvidenceBlock(
        doc_id="phase2_smoke",
        block_id=block_id,
        block_type="text",
        text=text,
        location=EvidenceLocation(page=1, block_id=block_id),
    )


def _candidate(block_id: str, text: str, *, rrf_rank: int) -> RetrievalCandidate:
    return RetrievalCandidate(block=_block(block_id, text), ranks={"rrf": rrf_rank})


def smoke_bge(*, model_path: Path, device: str, use_fp16: bool) -> dict[str, object]:
    try:
        missing = _missing_files(model_path, BGE_REQUIRED_FILES)
        if missing:
            raise FileNotFoundError(f"BGE-M3 model directory is incomplete: {missing}")
        encoder = DenseEncoder(
            DenseEncoderConfig(
                model_path=str(model_path),
                device=device,
                use_fp16=use_fp16,
                batch_size=2,
                max_length=128,
            )
        )
        dense = encoder.encode_documents(
            [
                "DocAgent verifies real dense retrieval.",
                "BGE-M3 returns dense embeddings.",
            ]
        )
        dense = np.asarray(dense, dtype=np.float32)
        finite = bool(np.isfinite(dense).all())
        if dense.ndim != 2 or dense.shape[0] != 2 or not finite:
            raise RuntimeError(f"invalid BGE-M3 dense embedding output: shape={dense.shape}, finite={finite}")
        model = getattr(encoder, "_model", None)
        return {
            "status": "success",
            "backend": "bge_m3_flagembedding",
            "model_path": str(model_path),
            "device": device,
            "target_devices": getattr(model, "target_devices", None),
            "model_device": _model_device(model),
            "dtype": "float16" if use_fp16 and device.startswith("cuda") else "float32",
            "dense_shape": list(dense.shape),
            "finite": finite,
        }
    except Exception as exc:
        payload = _exception_payload(exc)
        payload.update({"backend": "bge_m3_flagembedding", "model_path": str(model_path), "device": device})
        return payload


def smoke_reranker(*, model_path: Path, device: str, use_fp16: bool) -> dict[str, object]:
    try:
        missing = _missing_files(model_path, RERANKER_REQUIRED_FILES)
        if missing:
            raise FileNotFoundError(f"reranker model directory is incomplete: {missing}")
        reranker = CrossEncoderReranker(
            CrossEncoderRerankerConfig(
                model_path=str(model_path),
                device=device,
                use_fp16=use_fp16,
                batch_size=2,
                max_length=256,
            )
        )
        candidates = [
            _candidate("irrelevant", "The weather is sunny today.", rrf_rank=1),
            _candidate("relevant", "DocAgent verifies real dense retrieval and reranking.", rrf_rank=2),
        ]
        reranked = reranker.score(query="what is DocAgent verifying?", candidates=candidates)
        scores_by_id = {candidate.block.block_id: candidate.rerank_score for candidate in candidates}
        scores = [score for score in scores_by_id.values() if score is not None]
        scores_finite = len(scores) == 2 and all(math.isfinite(float(score)) for score in scores)
        relevant_score = scores_by_id.get("relevant")
        irrelevant_score = scores_by_id.get("irrelevant")
        relevant_gt_irrelevant = (
            relevant_score is not None
            and irrelevant_score is not None
            and float(relevant_score) > float(irrelevant_score)
        )
        if not scores_finite:
            raise RuntimeError(f"invalid reranker scores: {scores_by_id}")
        return {
            "status": "success",
            "backend": CrossEncoderReranker.backend,
            "model_path": str(model_path),
            "device": reranker.metadata["device"],
            "dtype": reranker.metadata["dtype"],
            "max_length": reranker.metadata["max_length"],
            "scores_count": len(scores),
            "scores_finite": scores_finite,
            "scores_by_block_id": scores_by_id,
            "ranking": [candidate.block.block_id for candidate in reranked],
            "relevant_score_gt_irrelevant_score": relevant_gt_irrelevant,
            "model_device": _model_device(getattr(reranker, "_model", None)),
        }
    except Exception as exc:
        payload = _exception_payload(exc)
        payload.update({"backend": CrossEncoderReranker.backend, "model_path": str(model_path), "device": device})
        return payload


def build_payload(args: argparse.Namespace) -> dict[str, object]:
    bge = smoke_bge(model_path=Path(args.bge_model_path), device=args.device, use_fp16=not args.no_fp16)
    reranker = smoke_reranker(model_path=Path(args.reranker_model_path), device=args.device, use_fp16=not args.no_fp16)
    statuses = [bge["status"], reranker["status"]]
    if statuses == ["success", "success"]:
        status = "success"
    elif "success" in statuses:
        status = "partial"
    else:
        status = "failed"
    return {
        "command": "phase2_real_model_api_smoke",
        "status": status,
        "bge_m3": bge,
        "reranker": reranker,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bge-model-path", default="/root/autodl-tmp/models/bge-m3")
    parser.add_argument("--reranker-model-path", default="/root/autodl-tmp/models/bge-reranker-v2-m3")
    parser.add_argument("--device", default="cuda:1")
    parser.add_argument("--no-fp16", action="store_true")
    parser.add_argument("--output", default="outputs/smoke/phase2_real_models.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_payload(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
