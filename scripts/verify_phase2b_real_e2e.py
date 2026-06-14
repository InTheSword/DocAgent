from __future__ import annotations

import argparse
import gc
import json
import math
import re
import shutil
import sqlite3
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.eval.answer_metrics import exact_match, normalize_text, token_f1
from docagent.ingestion.document_registry import DocumentRegistry
from docagent.ingestion.hashing import sha256_file
from docagent.ingestion.service import DocumentIngestionService
from docagent.models.qwen_answer_policy import QwenAnswerPolicy, QwenAnswerPolicyConfig
from docagent.parser.mineru_backend import MinerUParserBackend
from docagent.retrieval.base import RetrievalCandidate, RetrievalResult
from docagent.retrieval.dense_encoder import DenseEncoder, DenseEncoderConfig
from docagent.retrieval.dense_index import DenseIndex
from docagent.retrieval.index_manager import IndexedDocumentRetriever
from docagent.retrieval.query_rewrite import rewrite_query
from docagent.retrieval.reranker import CrossEncoderReranker, CrossEncoderRerankerConfig
from docagent.schemas import EvidenceBlock
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository, TraceRepository
from docagent.utils.jsonl import read_jsonl, write_jsonl
from docagent.workflow.graph import run_qa_workflow


COMMAND = "verify_phase2b_real_e2e"
DOC_ID = "fe3465edd3da60d2"
DENSE_BACKEND = "bge_m3"
DENSE_MODEL_ID = "bge-m3-dense-1024"
RERANKER_BACKEND = CrossEncoderReranker.backend
REWRITE_BACKEND = "deterministic_keyword_v1"
ANSWER_POLICY_MODE = "grpo"
DEFAULT_GRPO_ADAPTER_PATH = (
    "outputs/checkpoints/qwen3-docagent-trl-grpo-mpdocvqa-retrieved-grounded-100step-20260606_105535"
)
ALLOWED_ANSWER_TYPES = {"text", "number", "table_lookup", "ranking", "comparison", "chart"}
WINDOWS_PATH_RE = re.compile(r"(^|[^A-Za-z0-9])([A-Za-z]:[\\/]|\\\\)")


@dataclass(frozen=True)
class ScenarioQA:
    qid: str
    doc_id: str
    question: str
    answers: list[str]
    answer_type: str
    gold_pages: list[int]
    gold_block_ids: list[str]
    evidence_note: str
    verified: bool

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScenarioQA":
        return cls(
            qid=str(data.get("qid") or ""),
            doc_id=str(data.get("doc_id") or ""),
            question=str(data.get("question") or ""),
            answers=[str(item) for item in data.get("answers") or []],
            answer_type=str(data.get("answer_type") or ""),
            gold_pages=[int(item) for item in data.get("gold_pages") or []],
            gold_block_ids=[str(item) for item in data.get("gold_block_ids") or []],
            evidence_note=str(data.get("evidence_note") or ""),
            verified=bool(data.get("verified")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "qid": self.qid,
            "doc_id": self.doc_id,
            "question": self.question,
            "answers": self.answers,
            "answer_type": self.answer_type,
            "gold_pages": self.gold_pages,
            "gold_block_ids": self.gold_block_ids,
            "evidence_note": self.evidence_note,
            "verified": self.verified,
        }


class RealMetadataRetriever:
    def __init__(
        self,
        retriever: IndexedDocumentRetriever,
        *,
        dense_model_id: str,
        index_backend: str,
    ) -> None:
        self.retriever = retriever
        self.dense_model_id = dense_model_id
        self.index_backend = index_backend

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
                "index_backend": self.index_backend,
                "sparse_backend": "bm25",
                "fusion": "rrf",
                "reranker_backend": RERANKER_BACKEND,
                "rewrite_backend": REWRITE_BACKEND,
                "no_mock_fallback": True,
            }
        )
        return result


class CachedRetriever:
    def __init__(self, cache: dict[str, RetrievalResult]) -> None:
        self.cache = cache

    def retrieve(
        self,
        *,
        doc_id: str | None,
        question: str,
        top_k: int,
        answer_type_hint: str | None = None,
    ) -> RetrievalResult:
        key = _cache_key(doc_id or "", question)
        if key not in self.cache:
            raise RuntimeError(f"cached retrieval result missing for doc_id={doc_id}, question={question!r}")
        result = self.cache[key]
        return RetrievalResult(
            rewritten_query=result.rewritten_query,
            candidates=result.candidates[:top_k],
            metadata=dict(result.metadata),
        )


def _cache_key(doc_id: str, question: str) -> str:
    return f"{doc_id}\0{question}"


def resolve_repo_path(path: str | Path) -> Path:
    resolved = Path(path)
    return resolved if resolved.is_absolute() else ROOT / resolved


def artifact_path(path: Path, *, work_dir: Path) -> str:
    resolved = path.resolve()
    for base in (ROOT.resolve(), work_dir.resolve()):
        try:
            return resolved.relative_to(base).as_posix() if base == work_dir.resolve() else resolved.relative_to(base).as_posix()
        except ValueError:
            continue
    return path.name


def _prepare_work_dir(work_dir: Path) -> None:
    resolved = work_dir.resolve()
    if resolved in {Path(resolved.anchor), ROOT.resolve()}:
        raise RuntimeError(f"refusing to clean unsafe work directory: {work_dir}")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    (work_dir / "logs").mkdir()


def _looks_like_local_absolute_path(value: str) -> bool:
    if "://" in value:
        return False
    if WINDOWS_PATH_RE.search(value):
        return True
    return value.startswith("/") and not value.startswith("//")


def _sanitize_manifest_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_manifest_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_manifest_paths(item) for item in value]
    if isinstance(value, str) and _looks_like_local_absolute_path(value):
        return Path(value).name
    return value


def _copy_source_manifest(mineru_output: Path, document_dir: Path) -> None:
    manifest = mineru_output.parent / "source_manifest.json"
    if not manifest.exists():
        return
    payload = json.loads(manifest.read_text(encoding="utf-8-sig"))
    if isinstance(payload, dict):
        payload = _sanitize_manifest_paths(payload)
        payload["source_file"] = "source/original.pdf"
        (document_dir / "mineru_source_manifest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _scan_absolute_paths(value: Any, *, where: str, hits: list[dict[str, str]]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _scan_absolute_paths(item, where=f"{where}.{key}", hits=hits)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_absolute_paths(item, where=f"{where}[{index}]", hits=hits)
    elif isinstance(value, str) and _looks_like_local_absolute_path(value):
        hits.append({"where": where, "value": value})


def scan_persisted_absolute_paths(document_dir: Path, sqlite_path: Path) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for name in (
        "evidence_blocks.jsonl",
        "page_documents.jsonl",
        "ingestion_report.json",
        "structure_quality.json",
        "mineru_source_manifest.json",
    ):
        path = document_dir / name
        if not path.exists():
            continue
        if path.suffix == ".jsonl":
            _scan_absolute_paths(read_jsonl(path), where=name, hits=hits)
        else:
            _scan_absolute_paths(json.loads(path.read_text(encoding="utf-8-sig")), where=name, hits=hits)
    with sqlite3.connect(sqlite_path) as conn:
        rows = conn.execute("SELECT block_id, payload_json, metadata_json FROM evidence_blocks").fetchall()
    for block_id, payload_json, metadata_json in rows:
        _scan_absolute_paths(json.loads(payload_json), where=f"sqlite.payload_json[{block_id}]", hits=hits)
        if metadata_json:
            _scan_absolute_paths(json.loads(metadata_json), where=f"sqlite.metadata_json[{block_id}]", hits=hits)
    return hits


def load_blocks(path: Path) -> list[EvidenceBlock]:
    return [EvidenceBlock.from_dict(record) for record in read_jsonl(path)]


def retrieval_eligible_blocks(blocks: list[EvidenceBlock]) -> list[EvidenceBlock]:
    return [
        block
        for block in blocks
        if not block.metadata.get("is_boilerplate")
        and not block.metadata.get("exclude_from_retrieval")
        and bool(block.retrieval_text)
        and block.block_type != "page"
    ]


def load_scenario_qa(path: Path) -> list[ScenarioQA]:
    samples = [ScenarioQA.from_dict(record) for record in read_jsonl(path)]
    if not samples:
        raise RuntimeError(f"no scenario QA records found: {path}")
    return samples


def validate_scenario_qa(samples: list[ScenarioQA], blocks_by_id: dict[str, EvidenceBlock]) -> dict[str, Any]:
    errors: list[str] = []
    seen_qids: set[str] = set()
    type_counts: dict[str, int] = {}
    for sample in samples:
        if not sample.qid:
            errors.append("empty qid")
        if sample.qid in seen_qids:
            errors.append(f"duplicate qid: {sample.qid}")
        seen_qids.add(sample.qid)
        if sample.doc_id != DOC_ID:
            errors.append(f"{sample.qid}: unexpected doc_id={sample.doc_id}")
        if not sample.question:
            errors.append(f"{sample.qid}: empty question")
        if not sample.answers or any(not answer.strip() for answer in sample.answers):
            errors.append(f"{sample.qid}: empty answer")
        if sample.answer_type not in ALLOWED_ANSWER_TYPES:
            errors.append(f"{sample.qid}: unsupported answer_type={sample.answer_type}")
        if not sample.verified:
            errors.append(f"{sample.qid}: verified must be true")
        if not sample.gold_block_ids:
            errors.append(f"{sample.qid}: missing gold_block_ids")
        if not sample.gold_pages:
            errors.append(f"{sample.qid}: missing gold_pages")
        type_counts[sample.answer_type] = type_counts.get(sample.answer_type, 0) + 1
        question_norm = normalize_text(sample.question)
        for block_id in sample.gold_block_ids:
            if block_id and block_id.lower() in sample.question.lower():
                errors.append(f"{sample.qid}: question contains gold block id")
        for answer in sample.answers:
            answer_norm = normalize_text(answer)
            if answer_norm and any(char.isdigit() for char in answer_norm) and answer_norm in question_norm:
                errors.append(f"{sample.qid}: question appears to contain gold answer")
        for block_id in sample.gold_block_ids:
            block = blocks_by_id.get(block_id)
            if block is None:
                errors.append(f"{sample.qid}: missing gold block {block_id}")
                continue
            if block.page_id not in set(sample.gold_pages):
                errors.append(f"{sample.qid}: gold page mismatch for {block_id}")
            if not answer_supported_by_block(sample.answers, block):
                errors.append(f"{sample.qid}: answers not supported by {block_id}")
    if errors:
        raise RuntimeError("invalid scenario QA: " + "; ".join(errors))
    return {
        "sample_count": len(samples),
        "answer_type_counts": dict(sorted(type_counts.items())),
        "validated": True,
    }


def answer_supported_by_block(answers: list[str], block: EvidenceBlock) -> bool:
    evidence = " ".join(
        part
        for part in (block.text, block.table_html, block.visual_summary, str(block.metadata.get("table_body") or ""))
        if part
    )
    evidence_norm = normalize_text(evidence)
    for answer in answers:
        answer_norm = normalize_text(answer)
        if answer_norm and answer_norm in evidence_norm:
            return True
        compact_answer = re.sub(r"\s+", "", answer_norm)
        compact_evidence = re.sub(r"\s+", "", evidence_norm)
        if compact_answer and compact_answer in compact_evidence:
            return True
        answer_numbers = re.findall(r"\d+(?:\.\d+)?%?", answer_norm)
        if answer_numbers and all(number in evidence_norm for number in answer_numbers):
            return True
    return False


def require_model_dir(path: Path, *, name: str) -> None:
    if not path.is_dir():
        raise FileNotFoundError(f"{name} model directory does not exist: {path}")
    if not (path / "config.json").is_file():
        raise FileNotFoundError(f"{name} model directory is missing config.json: {path}")
    weight_files = list(path.glob("*.bin")) + list(path.glob("*.safetensors"))
    if not weight_files:
        raise FileNotFoundError(f"{name} model directory is missing local weight files: {path}")


def require_qwen_paths(base_model_path: Path, adapter_path: Path) -> None:
    require_model_dir(base_model_path, name="Qwen base")
    if not adapter_path.is_dir():
        raise FileNotFoundError(f"Qwen GRPO adapter path does not exist: {adapter_path}")
    if not (adapter_path / "adapter_config.json").is_file():
        raise FileNotFoundError(f"Qwen GRPO adapter is missing adapter_config.json: {adapter_path}")
    if not any((adapter_path / name).is_file() for name in ("adapter_model.safetensors", "adapter_model.bin")):
        raise FileNotFoundError(f"Qwen GRPO adapter is missing adapter weights: {adapter_path}")


def dense_artifact_prefix(model_id: str) -> str:
    if model_id.startswith("hash-dense"):
        raise RuntimeError(f"mock dense model is not allowed: {model_id}")
    if any(part in model_id for part in ("/", "\\", ":", "\0")):
        raise RuntimeError(f"dense model_id must be safe for artifact filenames: {model_id!r}")
    return model_id


def validate_no_mock_fallback(*, dense_backend: str, reranker_backend: str, answer_policy: str, dense_model_id: str) -> None:
    if dense_backend != DENSE_BACKEND:
        raise RuntimeError(f"expected dense_backend={DENSE_BACKEND}, got {dense_backend}")
    if reranker_backend != RERANKER_BACKEND:
        raise RuntimeError(f"expected reranker_backend={RERANKER_BACKEND}, got {reranker_backend}")
    if answer_policy != ANSWER_POLICY_MODE:
        raise RuntimeError(f"expected answer_policy={ANSWER_POLICY_MODE}, got {answer_policy}")
    if dense_model_id.startswith("hash-dense"):
        raise RuntimeError(f"mock dense model is not allowed: {dense_model_id}")


def validate_embeddings(embeddings: np.ndarray, *, expected_rows: int, expected_dim: int | None) -> None:
    if embeddings.ndim != 2:
        raise RuntimeError(f"expected 2D embeddings, got shape={embeddings.shape}")
    if embeddings.shape[0] != expected_rows:
        raise RuntimeError(f"expected {expected_rows} embeddings, got shape={embeddings.shape}")
    if expected_dim is not None and embeddings.shape[1] != expected_dim:
        raise RuntimeError(f"expected embedding_dim={expected_dim}, got shape={embeddings.shape}")
    if not np.isfinite(embeddings).all():
        raise RuntimeError("embeddings contain non-finite values")


def validate_dense_reload_stability(
    *,
    original: DenseIndex,
    loaded: DenseIndex,
    query_embedding: np.ndarray,
    top_k: int,
) -> dict[str, Any]:
    original_hits = original.search(query_embedding, top_k=top_k)
    loaded_hits = loaded.search(query_embedding, top_k=top_k)
    original_ids = [hit.block.block_id for hit in original_hits]
    loaded_ids = [hit.block.block_id for hit in loaded_hits]
    original_scores = [hit.score for hit in original_hits]
    loaded_scores = [hit.score for hit in loaded_hits]
    stable = original_ids == loaded_ids and np.allclose(original_scores, loaded_scores, atol=1e-6)
    if not stable:
        raise RuntimeError(f"dense index reload changed search results: original={original_ids}, loaded={loaded_ids}")
    return {"stable": True, "block_ids": loaded_ids}


def build_real_retriever(args: argparse.Namespace, blocks: list[EvidenceBlock], samples: list[ScenarioQA]) -> tuple[RealMetadataRetriever, dict[str, Any]]:
    bge_model_path = Path(args.bge_model_path)
    reranker_model_path = Path(args.reranker_model_path)
    require_model_dir(bge_model_path, name="BGE-M3")
    require_model_dir(reranker_model_path, name="bge-reranker-v2-m3")
    encoder = DenseEncoder(
        DenseEncoderConfig(
            model_path=str(bge_model_path),
            device=args.retrieval_device,
            use_fp16=not args.no_fp16,
            batch_size=args.dense_batch_size,
            max_length=args.dense_max_length,
        )
    )
    embeddings = encoder.encode_documents([block.retrieval_text for block in blocks])
    validate_embeddings(embeddings, expected_rows=len(blocks), expected_dim=args.expected_embedding_dim)
    dense_index = DenseIndex.build(blocks=blocks, embeddings=embeddings, model_id=args.dense_model_id)
    if dense_index.backend != "faiss":
        raise RuntimeError(f"real E2E verifier requires FAISS backend, got {dense_index.backend}")
    index_dir = resolve_repo_path(args.work_dir) / "index"
    metadata = dense_index.save(index_dir, artifact_prefix=dense_artifact_prefix(args.dense_model_id))
    metadata_path = Path(str(metadata["metadata_path"]))
    loaded_index = DenseIndex.load(index_dir=index_dir, blocks=blocks, metadata_path=metadata_path)
    first_query = encoder.encode_queries([samples[0].question])
    validate_embeddings(first_query, expected_rows=1, expected_dim=args.expected_embedding_dim)
    reload_check = validate_dense_reload_stability(
        original=dense_index,
        loaded=loaded_index,
        query_embedding=first_query,
        top_k=min(args.dense_top_n, len(blocks)),
    )
    reranker = CrossEncoderReranker(
        CrossEncoderRerankerConfig(
            model_path=str(reranker_model_path),
            device=args.retrieval_device,
            use_fp16=not args.no_fp16,
            batch_size=args.reranker_batch_size,
            max_length=args.reranker_max_length,
        )
    )
    indexed = IndexedDocumentRetriever(
        blocks,
        mode="hybrid_rerank",
        dense_encoder=encoder,
        dense_index=loaded_index,
        reranker=reranker,
        bm25_top_n=args.bm25_top_n,
        dense_top_n=args.dense_top_n,
        fusion_top_n=args.fusion_top_n,
        rrf_k=args.rrf_k,
    )
    retriever = RealMetadataRetriever(indexed, dense_model_id=args.dense_model_id, index_backend=loaded_index.backend)
    return retriever, {
        "dense_backend": DENSE_BACKEND,
        "dense_model_id": args.dense_model_id,
        "embedding_dim": int(embeddings.shape[1]),
        "embedding_count": int(embeddings.shape[0]),
        "index_backend": loaded_index.backend,
        "index_saved": True,
        "index_reloaded": True,
        "index_reload_stable": reload_check["stable"],
        "reranker_backend": RERANKER_BACKEND,
        "retrieval_device": args.retrieval_device,
        "dtype": "float16" if not args.no_fp16 and args.retrieval_device.startswith("cuda") else "float32",
        "metadata_path": artifact_path(metadata_path, work_dir=resolve_repo_path(args.work_dir)),
        "faiss_path": artifact_path(Path(str(metadata.get("faiss_path") or "")), work_dir=resolve_repo_path(args.work_dir)),
    }


def build_grpo_policy(args: argparse.Namespace) -> QwenAnswerPolicy:
    base_model_path = Path(args.base_model_path)
    adapter_path = resolve_repo_path(args.adapter_path)
    require_qwen_paths(base_model_path, adapter_path)
    return QwenAnswerPolicy(
        QwenAnswerPolicyConfig(
            mode=ANSWER_POLICY_MODE,
            base_model_path=str(base_model_path),
            adapter_path=str(adapter_path),
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


def release_retriever_models(retriever: RealMetadataRetriever) -> None:
    indexed = retriever.retriever
    if getattr(indexed, "dense_encoder", None) is not None:
        indexed.dense_encoder._model = None
    reranker = getattr(getattr(indexed, "hybrid", None), "reranker", None)
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


def candidate_payload(
    candidate: RetrievalCandidate,
    *,
    final_rank: int,
    dense_model_id: str = DENSE_MODEL_ID,
    index_backend: str = "faiss",
) -> dict[str, Any]:
    block = candidate.block
    metadata = block.metadata or {}
    return {
        "block_id": block.block_id,
        "page": block.page_id,
        "block_type": block.block_type,
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
        "raw_mineru_type": metadata.get("raw_mineru_type"),
        "is_boilerplate": bool(metadata.get("is_boilerplate")),
        "exclude_from_retrieval": bool(metadata.get("exclude_from_retrieval")),
        "dense_backend": DENSE_BACKEND,
        "dense_model_id": dense_model_id,
        "index_backend": index_backend,
        "sparse_backend": "bm25",
        "fusion": "rrf",
        "reranker_backend": RERANKER_BACKEND,
    }


def json_float(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        raise RuntimeError(f"non-finite score cannot be serialized: {value}")
    return number


def run_retrieval_phase(
    *,
    samples: list[ScenarioQA],
    retriever: RealMetadataRetriever,
    top_k: int,
) -> dict[str, RetrievalResult]:
    cache: dict[str, RetrievalResult] = {}
    for sample in samples:
        result = retriever.retrieve(
            doc_id=sample.doc_id,
            question=sample.question,
            top_k=top_k,
            answer_type_hint=sample.answer_type,
        )
        cache[_cache_key(sample.doc_id, sample.question)] = result
    return cache


def trace_by_node(traces: list[dict[str, Any]], node_name: str) -> dict[str, Any] | None:
    for trace in traces:
        if trace.get("node_name") == node_name:
            return trace
    return None


def run_answer_phase(
    *,
    samples: list[ScenarioQA],
    blocks: list[EvidenceBlock],
    retrieval_cache: dict[str, RetrievalResult],
    policy,
    trace_repository: TraceRepository,
    top_k: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cached_retriever = CachedRetriever(retrieval_cache)
    for sample in samples:
        started = time.perf_counter()
        try:
            state = run_qa_workflow(
                qid=sample.qid,
                doc_id=sample.doc_id,
                question=sample.question,
                blocks=blocks,
                answer_policy=policy,
                top_k=top_k,
                answer_type_hint=sample.answer_type,
                trace_repository=trace_repository,
                retriever=cached_retriever,
            )
            traces = trace_repository.list_traces(state.run_id or "")
            rows.append(evaluate_sample(sample=sample, state=state, traces=traces, elapsed_ms=(time.perf_counter() - started) * 1000))
        except Exception as exc:
            rows.append(
                {
                    "qid": sample.qid,
                    "doc_id": sample.doc_id,
                    "status": "failed",
                    "failure_taxonomy": ["workflow_error"],
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback_tail": traceback.format_exc().splitlines()[-10:],
                }
            )
    return rows


def evaluate_sample(*, sample: ScenarioQA, state, traces: list[dict[str, Any]], elapsed_ms: float) -> dict[str, Any]:
    retrieval_trace = trace_by_node(traces, "retrieve_evidence")
    generation_trace = trace_by_node(traces, "generate_answer")
    retrieval_output = retrieval_trace.get("output_summary") if retrieval_trace else {}
    candidates = retrieval_output.get("candidates") or []
    ranking = [str(candidate.get("block_id")) for candidate in candidates]
    final_answer = state.final_answer if isinstance(state.final_answer, dict) else {}
    pred_answer = str(final_answer.get("answer") or "")
    final_location = final_answer.get("evidence_location") or {}
    gold_set = set(sample.gold_block_ids)
    gold_pages = set(sample.gold_pages)
    gold_rank = first_gold_rank(ranking, gold_set)
    answer_scores = score_answer(pred_answer, sample.answers)
    block_location_hit = final_location.get("block_id") in gold_set
    page_location_hit = final_location.get("page") in gold_pages
    final_location_in_top_k = final_location.get("block_id") in set(ranking) if final_location.get("block_id") else False
    parse_result = state.parse_result or {}
    format_valid = bool(state.format_check.get("success"))
    location_valid = bool(state.location_check.get("success"))
    taxonomy: list[str] = []
    if gold_rank is None:
        taxonomy.append("retrieval_miss")
    if not answer_scores["answer_hit"]:
        taxonomy.append("answer_miss")
    if not block_location_hit:
        taxonomy.append("location_miss")
    if not (parse_result.get("raw_json_ok") or parse_result.get("schema_ok") or bool(state.draft_answer)):
        taxonomy.append("json_invalid")
    if not format_valid:
        taxonomy.append("format_invalid")
    return {
        "qid": sample.qid,
        "doc_id": sample.doc_id,
        "question": sample.question,
        "answer_type": sample.answer_type,
        "status": "completed",
        "gold_block_ids": sample.gold_block_ids,
        "gold_pages": sample.gold_pages,
        "ranking": ranking,
        "gold_block_rank": gold_rank,
        "gold_page_hit": bool({candidate.get("page") for candidate in candidates} & gold_pages),
        "retrieval": {
            "original_query": sample.question,
            "rewritten_query": state.rewritten_query,
            "rewrite_backend": retrieval_output.get("rewrite_backend") or REWRITE_BACKEND,
            "rewrite_changed": normalize_text(state.rewritten_query) != normalize_text(sample.question),
            "candidates": candidates,
        },
        "prediction": final_answer,
        "answers": sample.answers,
        "answer_metrics": answer_scores,
        "validation": {
            "valid_json": bool(parse_result.get("raw_json_ok") or parse_result.get("schema_ok") or state.draft_answer),
            "format_valid": format_valid,
            "location_valid": location_valid,
            "block_location_hit": block_location_hit,
            "page_location_hit": page_location_hit,
            "final_location_in_retrieved_top_k": final_location_in_top_k,
            "repair_attempted": bool(state.repair_attempted),
        },
        "trace": {
            "run_id": state.run_id,
            "nodes": [trace.get("node_name") for trace in traces],
            "retrieval_trace_present": retrieval_trace is not None,
            "generation_trace_present": generation_trace is not None,
        },
        "latency_ms": elapsed_ms,
        "failure_taxonomy": taxonomy,
    }


def score_answer(prediction: str, answers: list[str]) -> dict[str, Any]:
    em = any(exact_match(prediction, answer) for answer in answers)
    f1 = max([token_f1(prediction, answer) for answer in answers] or [0.0])
    char_f1 = max([character_f1(prediction, answer) for answer in answers] or [0.0])
    pred_norm = normalize_text(prediction)
    hit = any(normalize_text(answer) in pred_norm for answer in answers if normalize_text(answer))
    return {
        "normalized_exact_match": em,
        "token_f1": f1,
        "character_f1": char_f1,
        "answer_hit": hit or em,
    }


def character_f1(prediction: str, gold: str) -> float:
    pred = normalize_text(prediction).replace(" ", "")
    ref = normalize_text(gold).replace(" ", "")
    if not pred or not ref:
        return 0.0
    pred_counts: dict[str, int] = {}
    ref_counts: dict[str, int] = {}
    for char in pred:
        pred_counts[char] = pred_counts.get(char, 0) + 1
    for char in ref:
        ref_counts[char] = ref_counts.get(char, 0) + 1
    overlap = sum(min(pred_counts.get(char, 0), ref_counts.get(char, 0)) for char in set(pred_counts) | set(ref_counts))
    if overlap == 0:
        return 0.0
    precision = overlap / len(pred)
    recall = overlap / len(ref)
    return 2 * precision * recall / (precision + recall)


def first_gold_rank(ranking: list[str], gold_ids: set[str]) -> int | None:
    for index, block_id in enumerate(ranking, start=1):
        if block_id in gold_ids:
            return index
    return None


def aggregate_metrics(rows: list[dict[str, Any]], *, top_k: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    completed = [row for row in rows if row.get("status") == "completed"]
    count = len(completed)
    ranks = [row.get("gold_block_rank") for row in completed]
    retrieval_metrics = {
        "sample_count": count,
        "top_k": top_k,
        "recall_at_1": mean(rank is not None and rank <= 1 for rank in ranks),
        "recall_at_3": mean(rank is not None and rank <= min(3, top_k) for rank in ranks),
        "recall_at_5": mean(rank is not None and rank <= min(5, top_k) for rank in ranks),
        "mrr": sum((1.0 / rank) if rank else 0.0 for rank in ranks) / max(count, 1),
        "mean_reciprocal_rank": sum((1.0 / rank) if rank else 0.0 for rank in ranks) / max(count, 1),
        "gold_block_ranks": {row["qid"]: row.get("gold_block_rank") for row in completed},
        "gold_page_hit_rate": mean(bool(row.get("gold_page_hit")) for row in completed),
    }
    answer_metrics = {
        "sample_count": count,
        "normalized_exact_match": mean(row["answer_metrics"]["normalized_exact_match"] for row in completed),
        "token_f1": sum(row["answer_metrics"]["token_f1"] for row in completed) / max(count, 1),
        "character_f1": sum(row["answer_metrics"]["character_f1"] for row in completed) / max(count, 1),
        "answer_hit": mean(row["answer_metrics"]["answer_hit"] for row in completed),
        "valid_json_rate": mean(row["validation"]["valid_json"] for row in completed),
        "format_valid_rate": mean(row["validation"]["format_valid"] for row in completed),
    }
    location_metrics = {
        "sample_count": count,
        "block_location_hit": mean(row["validation"]["block_location_hit"] for row in completed),
        "page_location_hit": mean(row["validation"]["page_location_hit"] for row in completed),
        "final_location_in_retrieved_top_k": mean(row["validation"]["final_location_in_retrieved_top_k"] for row in completed),
        "location_valid_rate": mean(row["validation"]["location_valid"] for row in completed),
    }
    return retrieval_metrics, answer_metrics, location_metrics


def mean(values) -> float:
    items = [bool(value) for value in values]
    return sum(1 for value in items if value) / max(len(items), 1)


def failure_cases(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cases = []
    for row in rows:
        taxonomy = row.get("failure_taxonomy") or []
        if taxonomy:
            cases.append(
                {
                    "qid": row.get("qid"),
                    "status": row.get("status"),
                    "failure_taxonomy": taxonomy,
                    "gold_block_ids": row.get("gold_block_ids"),
                    "gold_block_rank": row.get("gold_block_rank"),
                    "prediction": row.get("prediction"),
                    "error": row.get("error"),
                }
            )
    return cases


def ingest_real_document(args: argparse.Namespace, work_dir: Path) -> tuple[Path, Path, dict[str, Any]]:
    source_pdf = resolve_repo_path(args.source_pdf)
    mineru_output = resolve_repo_path(args.mineru_output)
    if source_pdf.name.lower() == "cdc_135850_ds1.pdf":
        raise RuntimeError("CDC PDF is out of scope for this verifier")
    if not source_pdf.is_file():
        raise FileNotFoundError(f"source PDF missing: {source_pdf}")
    if not mineru_output.is_dir():
        raise FileNotFoundError(f"MinerU output directory missing: {mineru_output}")
    document_root = work_dir / "documents"
    sqlite_path = work_dir / "docagent.sqlite"
    preview = DocumentRegistry(document_root).register(source_pdf)
    document_dir = Path(preview.document_dir)
    shutil.copytree(mineru_output, document_dir / "mineru")
    _copy_source_manifest(mineru_output, document_dir)
    conn = connect(sqlite_path)
    repository = DocumentRepository(conn)
    service = DocumentIngestionService(document_root=document_root, repository=repository)
    try:
        result = service.ingest(
            file_path=source_pdf,
            parser_backend=MinerUParserBackend(mode="parse_existing", backend_name="mineru_existing"),
            force_parse=True,
        )
    finally:
        conn.close()
    quality = json.loads((document_dir / "structure_quality.json").read_text(encoding="utf-8"))
    return document_dir, sqlite_path, {"result": result.to_dict(), "quality": quality}


def build_report(
    *,
    args: argparse.Namespace,
    work_dir: Path,
    document_dir: Path,
    sqlite_path: Path,
    ingestion: dict[str, Any],
    qa_validation: dict[str, Any],
    model_metadata: dict[str, Any],
    rows: list[dict[str, Any]],
    absolute_hits: list[dict[str, str]],
) -> dict[str, Any]:
    retrieval_metrics, answer_metrics, location_metrics = aggregate_metrics(rows, top_k=args.top_k)
    failures = failure_cases(rows)
    quality = ingestion["quality"]
    completed_count = sum(1 for row in rows if row.get("status") == "completed")
    with sqlite3.connect(sqlite_path) as conn:
        trace_counts = {
            "qa_runs": conn.execute("SELECT COUNT(*) FROM qa_runs").fetchone()[0],
            "tool_traces": conn.execute("SELECT COUNT(*) FROM tool_traces WHERE run_id IS NOT NULL").fetchone()[0],
        }
    return {
        "command": COMMAND,
        "status": "success",
        "result_type": "real-document scenario acceptance",
        "document": {
            "doc_id": DOC_ID,
            "source_sha256": sha256_file(resolve_repo_path(args.source_pdf)),
            "raw_block_count": quality["raw_block_count"],
            "converted_block_count": quality["converted_block_count"],
            "page_count": quality["content_list_page_count"],
            "retrieval_block_count": quality["converted_block_count"] - quality["boilerplate_count"],
            "boilerplate_count": quality["boilerplate_count"],
            "missing_image_reference_count": quality["missing_image_reference_count"],
            "persisted_absolute_path_count": len(absolute_hits),
        },
        "models": {
            "dense_backend": DENSE_BACKEND,
            "index_backend": model_metadata.get("index_backend"),
            "sparse_backend": "bm25",
            "fusion": "rrf",
            "reranker_backend": RERANKER_BACKEND,
            "answer_policy": ANSWER_POLICY_MODE,
            "query_rewrite": REWRITE_BACKEND,
            "no_mock_fallback": True,
        },
        "scenario": {
            "sample_count": qa_validation["sample_count"],
            "completed_count": completed_count,
            "answer_type_counts": qa_validation["answer_type_counts"],
        },
        "retrieval_metrics": retrieval_metrics,
        "answer_metrics": answer_metrics,
        "location_metrics": location_metrics,
        "trace": {
            "sqlite_persisted": trace_counts["qa_runs"] == completed_count and trace_counts["tool_traces"] >= completed_count,
            "qa_runs": trace_counts["qa_runs"],
            "tool_traces": trace_counts["tool_traces"],
        },
        "no_gold_leakage": True,
        "no_mock_fallback": True,
        "failure_case_count": len(failures),
        "failures": failures,
        "artifact_paths": {
            "verification_report": artifact_path(work_dir / "verification_report.json", work_dir=work_dir),
            "per_sample_results": artifact_path(work_dir / "per_sample_results.jsonl", work_dir=work_dir),
            "retrieval_metrics": artifact_path(work_dir / "retrieval_metrics.json", work_dir=work_dir),
            "answer_metrics": artifact_path(work_dir / "answer_metrics.json", work_dir=work_dir),
            "failure_cases": artifact_path(work_dir / "failure_cases.jsonl", work_dir=work_dir),
            "sqlite": artifact_path(sqlite_path, work_dir=work_dir),
            "documents": artifact_path(document_dir, work_dir=work_dir),
        },
    }


def run_verifier(args: argparse.Namespace) -> dict[str, Any]:
    validate_no_mock_fallback(
        dense_backend=DENSE_BACKEND,
        reranker_backend=RERANKER_BACKEND,
        answer_policy=ANSWER_POLICY_MODE,
        dense_model_id=args.dense_model_id,
    )
    work_dir = resolve_repo_path(args.work_dir)
    _prepare_work_dir(work_dir)
    document_dir, sqlite_path, ingestion = ingest_real_document(args, work_dir)
    blocks = load_blocks(document_dir / "evidence_blocks.jsonl")
    blocks_by_id = {block.block_id: block for block in blocks}
    retrieval_blocks = retrieval_eligible_blocks(blocks)
    qa_samples = load_scenario_qa(resolve_repo_path(args.qa_path))
    qa_validation = validate_scenario_qa(qa_samples, blocks_by_id)
    if any(sample.doc_id != DOC_ID for sample in qa_samples):
        raise RuntimeError("scenario QA contains records outside the target document")
    retriever, model_metadata = build_real_retriever(args, retrieval_blocks, qa_samples)
    try:
        retrieval_cache = run_retrieval_phase(samples=qa_samples, retriever=retriever, top_k=args.top_k)
    finally:
        release_retriever_models(retriever)
    policy = build_grpo_policy(args)
    conn = connect(sqlite_path)
    trace_repository = TraceRepository(conn)
    try:
        rows = run_answer_phase(
            samples=qa_samples,
            blocks=retrieval_blocks,
            retrieval_cache=retrieval_cache,
            policy=policy,
            trace_repository=trace_repository,
            top_k=args.top_k,
        )
    finally:
        conn.close()
        release_policy_model(policy)
    for row in rows:
        if row.get("status") != "completed" or not row.get("question"):
            continue
        key = _cache_key(row["doc_id"], row["question"])
        result = retrieval_cache.get(key)
        if result is not None:
            candidates = [
                candidate_payload(
                    candidate,
                    final_rank=rank,
                    dense_model_id=args.dense_model_id,
                    index_backend=str(model_metadata.get("index_backend") or "faiss"),
                )
                for rank, candidate in enumerate(result.candidates, start=1)
            ]
            row["retrieval"]["candidates"] = candidates
            row["ranking"] = [candidate["block_id"] for candidate in candidates]
            row["gold_block_rank"] = first_gold_rank(row["ranking"], set(row["gold_block_ids"]))
    retrieval_metrics, answer_metrics, location_metrics = aggregate_metrics(rows, top_k=args.top_k)
    failures = failure_cases(rows)
    write_jsonl(work_dir / "per_sample_results.jsonl", rows)
    (work_dir / "retrieval_metrics.json").write_text(json.dumps(retrieval_metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    (work_dir / "answer_metrics.json").write_text(json.dumps(answer_metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    write_jsonl(work_dir / "failure_cases.jsonl", failures)
    absolute_hits = scan_persisted_absolute_paths(document_dir, sqlite_path)
    report = build_report(
        args=args,
        work_dir=work_dir,
        document_dir=document_dir,
        sqlite_path=sqlite_path,
        ingestion=ingestion,
        qa_validation=qa_validation,
        model_metadata=model_metadata,
        rows=rows,
        absolute_hits=absolute_hits,
    )
    (work_dir / "verification_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def exception_payload(exc: Exception) -> dict[str, Any]:
    return {
        "command": COMMAND,
        "status": "failed",
        "result_type": "real-document scenario acceptance",
        "exception": f"{type(exc).__name__}: {exc}",
        "traceback_tail": traceback.format_exc().splitlines()[-20:],
        "no_gold_leakage": True,
        "no_mock_fallback": True,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-pdf", default="data/real_documents/globocan_africa_2022/source/original.pdf")
    parser.add_argument("--mineru-output", default="data/real_documents/globocan_africa_2022/mineru_raw")
    parser.add_argument("--qa-path", default="data/real_documents/globocan_africa_2022/qa/scenario_qa.jsonl")
    parser.add_argument("--work-dir", default="outputs/verification/phase2b_real_e2e")
    parser.add_argument("--bge-model-path", default="/root/autodl-tmp/models/bge-m3")
    parser.add_argument("--reranker-model-path", default="/root/autodl-tmp/models/bge-reranker-v2-m3")
    parser.add_argument("--base-model-path", default="/root/autodl-tmp/models/Qwen3-1.7B")
    parser.add_argument("--adapter-path", default=DEFAULT_GRPO_ADAPTER_PATH)
    parser.add_argument("--retrieval-device", default="cuda:1")
    parser.add_argument("--qwen-device", default="cuda:0")
    parser.add_argument("--qwen-torch-dtype", default="bfloat16")
    parser.add_argument("--dense-model-id", default=DENSE_MODEL_ID)
    parser.add_argument("--expected-embedding-dim", type=int, default=1024)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--bm25-top-n", type=int, default=20)
    parser.add_argument("--dense-top-n", type=int, default=20)
    parser.add_argument("--fusion-top-n", type=int, default=20)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--dense-batch-size", type=int, default=8)
    parser.add_argument("--reranker-batch-size", type=int, default=4)
    parser.add_argument("--dense-max-length", type=int, default=1024)
    parser.add_argument("--reranker-max-length", type=int, default=1024)
    parser.add_argument("--max-prompt-tokens", type=int, default=4096)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--no-fp16", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    exit_code = 0
    try:
        payload = run_verifier(args)
    except Exception as exc:
        payload = exception_payload(exc)
        exit_code = 1
        try:
            work_dir = resolve_repo_path(args.work_dir)
            work_dir.mkdir(parents=True, exist_ok=True)
            (work_dir / "verification_report.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass
    finally:
        release_gpu_memory()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
