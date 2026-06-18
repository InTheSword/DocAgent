from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from docagent.eval.answer_metrics import character_f1, exact_match, normalize_text, token_f1
from docagent.eval.retrieval_metrics import mrr_at_k, recall_at_k
from docagent.models.base import AnswerPolicy, HeuristicAnswerPolicy
from docagent.models.qwen_answer_policy import QwenAnswerPolicy, QwenAnswerPolicyConfig
from docagent.parser.build_evidence_blocks import collect_evidence_blocks
from docagent.retrieval.base import RetrievalResult
from docagent.retrieval.dense_encoder import DenseEncoder, DenseEncoderConfig, HashDenseEncoder
from docagent.retrieval.dense_index import DenseIndex
from docagent.retrieval.index_manager import IndexedDocumentRetriever
from docagent.retrieval.reranker import CrossEncoderReranker, CrossEncoderRerankerConfig, KeywordOverlapReranker
from docagent.schemas import DocAgentSample, EvidenceBlock
from docagent.storage.db import connect
from docagent.storage.repositories import TraceRepository
from docagent.utils.jsonl import read_jsonl, write_jsonl
from docagent.workflow.graph import run_qa_workflow


QUERY_PROCESSING_LABEL = "deterministic_query_normalization"
QUERY_PROCESSING_BACKEND = "deterministic_keyword_v1"
REAL_DENSE_BACKEND = "bge_m3"
REAL_RERANKER_BACKEND = CrossEncoderReranker.backend
SFT_DEFAULT_ADAPTER_PATH = (
    "outputs/checkpoints/qwen3-docagent-sft-mpdocvqa-retrieved-20260605_180454/"
    "v0-20260605-180519/checkpoint-155"
)
GRPO_DEFAULT_ADAPTER_PATH = (
    "outputs/checkpoints/qwen3-docagent-trl-grpo-mpdocvqa-retrieved-grounded-100step-20260606_105535"
)
DEFAULT_GRPO_ADAPTER_PATH = GRPO_DEFAULT_ADAPTER_PATH
DEFAULT_BGE_MODEL_PATH = "/root/autodl-tmp/models/bge-m3"
DEFAULT_RERANKER_MODEL_PATH = "/root/autodl-tmp/models/bge-reranker-v2-m3"
DEFAULT_QWEN_MODEL_PATH = "/root/autodl-tmp/models/Qwen3-1.7B"
DEFAULT_SEED = "phase3a-focused-eval-v1"
WINDOWS_ABSOLUTE_RE = re.compile(r"(^|[^A-Za-z0-9])([A-Za-z]:[\\/]|\\\\)")
SIGNED_URL_RE = re.compile(
    r"(X-Amz-(?:Signature|Credential|Security-Token)=|[?&](?:token|signature|sig)=)",
    re.IGNORECASE,
)
SEMANTIC_TEXT_FIELDS = {
    "answer",
    "content",
    "evidence",
    "reason",
    "table_html",
    "text",
    "visual_summary",
}
STRUCTURED_CREDENTIAL_FIELDS = {
    "access_token",
    "api_key",
    "api_token",
    "authorization",
    "bearer_token",
    "mineru_token",
    "secret_key",
}
ALLOWED_MODEL_PATH_PREFIX = "/root/autodl-tmp/models/"


class ContractValidationError(RuntimeError):
    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__(str(payload.get("exception") or "contract validation failed"))
        self.payload = payload


@dataclass(frozen=True)
class BenchmarkContract:
    input_path: str
    role: str
    status: str
    total_records: int
    valid_records: int
    invalid_records: int
    doc_count: int
    block_count: int
    qid_hash: str
    errors: list[str]
    corpus_source: str = "embedded_query_evidence"
    corpus_is_query_independent: bool = False
    one_corpus_signature_per_doc: bool = False
    corpus_hash: str = ""
    page_coverage: dict[str, Any] | None = None
    gold_block_coverage: dict[str, Any] | None = None
    repeated_doc_audit: dict[str, Any] | None = None
    source_qa_role: str | None = None
    evaluation_scope: str = "primary_retrieval"
    formal_benchmark: bool = False
    primary_benchmark: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_role": self.role,
            "input_path": self.input_path,
            "role": self.role,
            "source_qa_role": self.source_qa_role or self.role,
            "evaluation_scope": self.evaluation_scope,
            "formal_benchmark": self.formal_benchmark,
            "primary_benchmark": self.primary_benchmark,
            "status": self.status,
            "total_records": self.total_records,
            "valid_records": self.valid_records,
            "invalid_records": self.invalid_records,
            "document_count": self.doc_count,
            "doc_count": self.doc_count,
            "block_count": self.block_count,
            "corpus_source": self.corpus_source,
            "corpus_is_query_independent": self.corpus_is_query_independent,
            "one_corpus_signature_per_doc": self.one_corpus_signature_per_doc,
            "page_coverage": self.page_coverage or {},
            "gold_block_coverage": self.gold_block_coverage or {},
            "qid_hash": self.qid_hash,
            "corpus_hash": self.corpus_hash,
            "repeated_doc_audit": self.repeated_doc_audit or {},
            "errors": self.errors,
        }


@dataclass(frozen=True)
class ModelTiming:
    dense_model_load_ms: float | None = None
    reranker_model_load_ms: float | None = None
    dense_index_build_ms: float | None = None
    answer_model_load_ms: float | None = None


def repo_path(root: Path, path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else root / value


def safe_artifact_path(root: Path, path: str | Path) -> str:
    value = Path(path)
    try:
        return value.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return value.name


def safe_model_label(path: str | Path) -> str:
    value = str(path)
    if not value:
        return ""
    normalized = value.replace("\\", "/").rstrip("/")
    if normalized.startswith("/root/autodl-tmp/models/"):
        return Path(normalized).name
    path_value = Path(value)
    if path_value.is_absolute() or WINDOWS_ABSOLUTE_RE.search(value):
        return path_value.name
    return normalized


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def qid_hash(qids: list[str]) -> str:
    return sha256_text("\n".join(sorted(qids)))


def stable_sample_key(qid: str, seed: str) -> str:
    return sha256_text(f"{seed}\0{qid}")


def select_stable_subset(samples: list[DocAgentSample], *, limit: int | None, seed: str) -> list[DocAgentSample]:
    ordered = sorted(samples, key=lambda sample: (stable_sample_key(sample.qid, seed), sample.qid))
    return ordered if limit is None else ordered[:limit]


def load_samples(path: Path) -> list[DocAgentSample]:
    return [DocAgentSample.from_dict(record) for record in read_jsonl(path)]


def load_corpus_blocks(path: Path) -> list[EvidenceBlock]:
    blocks: list[EvidenceBlock] = []
    for record in read_jsonl(path):
        if all(key in record for key in ("doc_id", "block_id", "block_type")):
            blocks.append(EvidenceBlock.from_dict(record))
        else:
            raise ValueError(f"corpus records must be EvidenceBlock JSON objects, got keys={sorted(record)[:8]}")
    return blocks


def classify_benchmark_path(path: str | Path) -> str:
    normalized = str(path).replace("\\", "/").lower()
    if "smoke_eval" in normalized:
        return "smoke_fixture"
    if "globocan_africa_2022" in normalized or "scenario_qa" in normalized:
        return "globocan_scenario_acceptance"
    if "retrieved" in normalized:
        return "pre_retrieved_reader_data"
    if "mp_docvqa" in normalized:
        return "retrieval_benchmark"
    return "candidate_benchmark"


def _block_page(block: EvidenceBlock) -> int | None:
    return block.page_id if block.page_id is not None else block.location.page


def _block_signature_payload(block: EvidenceBlock) -> dict[str, Any]:
    return {
        "doc_id": block.doc_id,
        "block_id": block.block_id,
        "block_type": block.block_type,
        "page": _block_page(block),
        "text_hash": sha256_text(block.retrieval_text),
    }


def corpus_hash(blocks: list[EvidenceBlock]) -> str:
    payload = [_block_signature_payload(block) for block in blocks]
    payload.sort(key=lambda item: (str(item["doc_id"]), str(item["block_id"])))
    return sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def evidence_signature(blocks: list[EvidenceBlock]) -> str:
    payload = [_block_signature_payload(block) for block in blocks]
    payload.sort(key=lambda item: (str(item["block_id"]), str(item["page"])))
    return sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def blocks_by_doc(samples: list[DocAgentSample]) -> dict[str, list[EvidenceBlock]]:
    grouped: dict[str, dict[str, EvidenceBlock]] = {}
    for block in collect_evidence_blocks(samples):
        grouped.setdefault(block.doc_id, {})[block.block_id] = block
    return {doc_id: list(blocks.values()) for doc_id, blocks in grouped.items()}


def corpus_blocks_by_doc(blocks: list[EvidenceBlock]) -> dict[str, list[EvidenceBlock]]:
    grouped: dict[str, dict[str, EvidenceBlock]] = {}
    for block in blocks:
        grouped.setdefault(block.doc_id, {})[block.block_id] = block
    return {doc_id: list(values.values()) for doc_id, values in grouped.items()}


def page_coverage_report(samples: list[DocAgentSample], corpus_by_doc: dict[str, list[EvidenceBlock]]) -> dict[str, Any]:
    values: list[float] = []
    full = 0
    missing_total = 0
    for sample in samples:
        total_pages = sample.metadata.get("total_doc_pages")
        try:
            total = int(total_pages) if total_pages is not None else None
        except (TypeError, ValueError):
            total = None
        if not total:
            missing_total += 1
            continue
        pages = {
            page
            for page in (_block_page(block) for block in corpus_by_doc.get(sample.doc_id, []))
            if page is not None
        }
        value = min(len(pages) / total, 1.0) if total > 0 else 0.0
        values.append(value)
        if value >= 1.0:
            full += 1
    return {
        "sample_count_with_total_pages": len(values),
        "sample_count_missing_total_pages": missing_total,
        "mean": statistics.mean(values) if values else None,
        "full_page_coverage_count": full,
        "full_page_coverage_denominator": len(values),
    }


def repeated_doc_signature_audit(samples: list[DocAgentSample]) -> dict[str, Any]:
    signatures_by_doc: dict[str, set[str]] = {}
    for sample in samples:
        signatures_by_doc.setdefault(sample.doc_id, set()).add(evidence_signature(sample.evidence))
    repeated = {doc_id: sigs for doc_id, sigs in signatures_by_doc.items() if len([s for s in samples if s.doc_id == doc_id]) > 1}
    inconsistent = {doc_id: sorted(sigs) for doc_id, sigs in repeated.items() if len(sigs) > 1}
    return {
        "repeated_doc_count": len(repeated),
        "consistent_repeated_doc_count": sum(1 for sigs in repeated.values() if len(sigs) == 1),
        "inconsistent_repeated_doc_count": len(inconsistent),
        "evidence_signature_count_total": sum(len(sigs) for sigs in signatures_by_doc.values()),
        "inconsistent_doc_ids": sorted(inconsistent),
    }


def gold_coverage_report(samples: list[DocAgentSample], corpus_by_doc: dict[str, list[EvidenceBlock]]) -> dict[str, Any]:
    missing: list[str] = []
    covered = 0
    for sample in samples:
        doc_block_ids = {block.block_id for block in corpus_by_doc.get(sample.doc_id, [])}
        gold_ids = set(str(item) for item in sample.metadata.get("gold_block_ids") or [])
        if gold_ids and gold_ids.issubset(doc_block_ids):
            covered += 1
        else:
            missing.append(sample.qid)
    return {
        "covered_count": covered,
        "total_count": len(samples),
        "coverage_rate": covered / len(samples) if samples else 0.0,
        "missing_qids": missing[:50],
    }


def corpus_block_errors(blocks: list[EvidenceBlock]) -> list[str]:
    errors: list[str] = []
    seen_block_ids: set[str] = set()
    for block in blocks:
        if block.block_id in seen_block_ids:
            errors.append(f"duplicate block_id in corpus: {block.block_id}")
        seen_block_ids.add(block.block_id)
        if not block.doc_id:
            errors.append(f"missing doc_id for block_id={block.block_id}")
        if not block.retrieval_text:
            errors.append(f"missing retrieval content for block_id={block.block_id}")
    return errors


def validate_benchmark_contract(
    samples: list[DocAgentSample],
    *,
    input_path: str | Path,
    corpus_blocks: list[EvidenceBlock] | None = None,
    corpus_input_path: str | Path | None = None,
    artifact_role: str | None = None,
    evaluation_scope: str = "primary_retrieval",
    formal_benchmark: bool = False,
    primary_benchmark: bool = True,
    source_qa_role: str | None = None,
) -> BenchmarkContract:
    errors: list[str] = []
    inferred_source_role = source_qa_role or classify_benchmark_path(input_path)
    role = artifact_role or inferred_source_role
    forbidden_primary_roles = {"smoke_fixture", "globocan_scenario_acceptance", "pre_retrieved_reader_data"}
    scenario_regression_ok = (
        role == "real_document_regression"
        and inferred_source_role == "globocan_scenario_acceptance"
        and evaluation_scope == "scenario_regression"
        and not formal_benchmark
        and not primary_benchmark
    )
    source_role_forbidden = inferred_source_role in forbidden_primary_roles
    if source_role_forbidden and not scenario_regression_ok:
        errors.append(f"forbidden primary benchmark role: {inferred_source_role}")
    elif (formal_benchmark or primary_benchmark) and source_role_forbidden:
        errors.append(f"forbidden primary benchmark role: {inferred_source_role}")
    using_independent_corpus = corpus_blocks is not None
    if using_independent_corpus:
        corpus_source = "independent_corpus_input"
        active_corpus_blocks = list(corpus_blocks or [])
        repeated_audit = {
            "repeated_doc_count": 0,
            "consistent_repeated_doc_count": 0,
            "inconsistent_repeated_doc_count": 0,
            "evidence_signature_count_total": 0,
            "inconsistent_doc_ids": [],
        }
    else:
        corpus_source = "embedded_query_evidence"
        active_corpus_blocks = collect_evidence_blocks(samples)
        repeated_audit = repeated_doc_signature_audit(samples)
        errors.append("retrieval benchmark requires --corpus-input with a query-independent document corpus")
        if repeated_audit["inconsistent_repeated_doc_count"]:
            errors.append(
                "same doc_id has multiple evidence signatures: "
                + ", ".join(repeated_audit["inconsistent_doc_ids"][:10])
            )

    errors.extend(corpus_block_errors(active_corpus_blocks))
    corpus_by_doc = corpus_blocks_by_doc(active_corpus_blocks)
    block_count = sum(len(blocks) for blocks in corpus_by_doc.values())
    one_signature_per_doc = bool(using_independent_corpus) and all(
        len({evidence_signature(blocks)}) == 1 for blocks in corpus_by_doc.values()
    )
    seen_qids: set[str] = set()
    invalid_qids: set[str] = set()
    for sample in samples:
        sample_errors: list[str] = []
        if sample.qid in seen_qids:
            sample_errors.append("duplicate qid")
        seen_qids.add(sample.qid)
        if not sample.question:
            sample_errors.append("missing question")
        gold_ids = [str(item) for item in sample.metadata.get("gold_block_ids") or []]
        if not gold_ids:
            sample_errors.append("missing metadata.gold_block_ids")
        doc_blocks = {block.block_id: block for block in corpus_by_doc.get(sample.doc_id, [])}
        if not doc_blocks:
            sample_errors.append(f"doc_id missing from corpus: {sample.doc_id}")
        for block_id in gold_ids:
            if block_id not in doc_blocks:
                sample_errors.append(f"gold block not in query-independent corpus: {block_id}")
            if block_id and block_id.lower() in sample.question.lower():
                sample_errors.append(f"question contains gold block id: {block_id}")
        if sample_errors:
            invalid_qids.add(sample.qid)
            errors.extend(f"{sample.qid}: {item}" for item in sample_errors)

    valid_records = len(samples) - len(invalid_qids)
    status = "ready" if samples and not errors else "invalid"
    return BenchmarkContract(
        input_path=str(corpus_input_path or input_path),
        role=role,
        status=status,
        total_records=len(samples),
        valid_records=valid_records,
        invalid_records=len(invalid_qids),
        doc_count=len(corpus_by_doc),
        block_count=block_count,
        qid_hash=qid_hash([sample.qid for sample in samples]),
        errors=errors[:50],
        corpus_source=corpus_source,
        corpus_is_query_independent=using_independent_corpus,
        one_corpus_signature_per_doc=one_signature_per_doc,
        corpus_hash=corpus_hash(active_corpus_blocks),
        page_coverage=page_coverage_report(samples, corpus_by_doc),
        gold_block_coverage=gold_coverage_report(samples, corpus_by_doc),
        repeated_doc_audit=repeated_audit,
        source_qa_role=inferred_source_role,
        evaluation_scope=evaluation_scope,
        formal_benchmark=formal_benchmark,
        primary_benchmark=primary_benchmark,
    )


def require_ready_contract(contract: BenchmarkContract) -> None:
    if contract.status != "ready":
        raise RuntimeError("invalid benchmark contract: " + "; ".join(contract.errors))


def validate_reader_artifact_contract(
    samples: list[DocAgentSample],
    *,
    input_path: str | Path,
    require_gold_in_evidence: bool = True,
) -> BenchmarkContract:
    errors: list[str] = []
    invalid_qids: set[str] = set()
    seen_qids: set[str] = set()
    active_blocks = collect_evidence_blocks(samples)
    corpus_by_doc = corpus_blocks_by_doc(active_blocks)
    for sample in samples:
        sample_errors: list[str] = []
        if sample.qid in seen_qids:
            sample_errors.append("duplicate qid")
        seen_qids.add(sample.qid)
        if not sample.evidence:
            sample_errors.append("missing reader evidence")
        gold_ids = [str(item) for item in sample.metadata.get("gold_block_ids") or []]
        if not gold_ids:
            sample_errors.append("missing metadata.gold_block_ids")
        evidence_ids = {block.block_id for block in sample.evidence}
        for block_id in gold_ids:
            if require_gold_in_evidence and block_id not in evidence_ids:
                sample_errors.append(f"gold block not in reader evidence: {block_id}")
        if sample_errors:
            invalid_qids.add(sample.qid)
            errors.extend(f"{sample.qid}: {item}" for item in sample_errors)
    return BenchmarkContract(
        input_path=str(input_path),
        role=classify_benchmark_path(input_path),
        status="ready" if samples and not errors else "invalid",
        total_records=len(samples),
        valid_records=len(samples) - len(invalid_qids),
        invalid_records=len(invalid_qids),
        doc_count=len(corpus_by_doc),
        block_count=sum(len(blocks) for blocks in corpus_by_doc.values()),
        qid_hash=qid_hash([sample.qid for sample in samples]),
        errors=errors[:50],
        corpus_source="provided_reader_evidence",
        corpus_is_query_independent=False,
        one_corpus_signature_per_doc=False,
        corpus_hash=corpus_hash(active_blocks),
        page_coverage=page_coverage_report(samples, corpus_by_doc),
        gold_block_coverage=gold_coverage_report(samples, corpus_by_doc),
        repeated_doc_audit=repeated_doc_signature_audit(samples),
    )


def contract_payload(
    *,
    retrieval_contract: BenchmarkContract,
    reader_contract: BenchmarkContract | None,
    status: str,
    exception: str | None = None,
) -> dict[str, Any]:
    retrieval_ready = retrieval_contract.status == "ready"
    reader_ready = reader_contract is not None and reader_contract.status == "ready"
    payload: dict[str, Any] = {
        "command": "phase3_focused_eval_contract",
        "status": status,
        "retrieval_evaluation": "ready" if retrieval_ready else "blocked",
        "answer_policy_evaluation": "ready" if reader_ready or retrieval_ready else "blocked",
        "retrieval_contract": retrieval_contract.to_dict(),
    }
    if reader_contract is not None:
        payload["reader_contract"] = reader_contract.to_dict()
    if exception:
        payload["exception"] = exception
    return payload


def _leaf_field_name(where: str) -> str:
    segment = where.rsplit(".", 1)[-1]
    segment = re.sub(r"\[\d+\]", "", segment)
    return segment.lower()


def _is_semantic_text_field(where: str) -> bool:
    return _leaf_field_name(where) in SEMANTIC_TEXT_FIELDS


def _is_structured_credential_field(where: str) -> bool:
    field_name = _leaf_field_name(where)
    return field_name in STRUCTURED_CREDENTIAL_FIELDS or field_name.endswith("_token")


def validate_no_forbidden_paths(value: Any, *, where: str = "payload") -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            hits.extend(validate_no_forbidden_paths(item, where=f"{where}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            hits.extend(validate_no_forbidden_paths(item, where=f"{where}[{index}]"))
    elif isinstance(value, str):
        if _is_semantic_text_field(where):
            return hits
        if _is_structured_credential_field(where) and value.strip():
            hits.append({"where": where, "reason": "credential_field", "value": value[:120]})
        elif SIGNED_URL_RE.search(value):
            hits.append({"where": where, "reason": "signed_url_or_token", "value": value[:120]})
        elif WINDOWS_ABSOLUTE_RE.search(value):
            hits.append({"where": where, "reason": "windows_absolute_path", "value": value})
        elif value.startswith("/") and not value.startswith(ALLOWED_MODEL_PATH_PREFIX):
            hits.append({"where": where, "reason": "absolute_path", "value": value})
    return hits


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
    return ordered[index]


def aggregate_latency(latencies: list[float]) -> dict[str, float]:
    return {
        "mean_ms": statistics.mean(latencies) if latencies else 0.0,
        "p50_ms": statistics.median(latencies) if latencies else 0.0,
        "p95_ms": _percentile(latencies, 0.95),
    }


def first_gold_rank(ranking: list[str], gold_ids: set[str]) -> int | None:
    for rank, block_id in enumerate(ranking, start=1):
        if block_id in gold_ids:
            return rank
    return None


def retrieval_failure_labels(*, mode: str, ranking: list[str], gold_ids: set[str], gold_in_corpus: bool) -> list[str]:
    if not gold_in_corpus:
        return ["gold_not_in_corpus"]
    if set(ranking) & gold_ids:
        return []
    if mode == "bm25":
        return ["bm25_miss"]
    if mode == "hybrid_rerank":
        return ["hybrid_miss"]
    return ["gold_not_recalled"]


def summarize_retrieval_rows(rows: list[dict[str, Any]], *, top_k: int, total_records: int, invalid_records: int) -> dict[str, Any]:
    completed = [row for row in rows if row.get("status") == "completed"]
    rankings = [row["ranking"] for row in completed]
    gold_ids = [set(row["gold_block_ids"]) for row in completed]
    latencies = [float(row["query_latency_ms"]) for row in completed]
    return {
        "sample_count": total_records,
        "completed_count": len(completed),
        "invalid_count": invalid_records,
        "skipped_count": max(total_records - invalid_records - len(completed), 0),
        "top_k": top_k,
        "recall_at_1": recall_at_k(rankings, gold_ids, k=1),
        "recall_at_3": recall_at_k(rankings, gold_ids, k=min(3, top_k)),
        "recall_at_5": recall_at_k(rankings, gold_ids, k=min(5, top_k)),
        "mrr": mrr_at_k(rankings, gold_ids, k=min(5, top_k)),
        "gold_page_hit_rate": _mean_bool(row["gold_page_hit"] for row in completed),
        "latency": aggregate_latency(latencies),
    }


def compare_metrics(candidate: dict[str, Any], baseline: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for key in keys:
        base_value = float(baseline.get(key, 0.0) or 0.0)
        candidate_value = float(candidate.get(key, 0.0) or 0.0)
        delta = candidate_value - base_value
        metrics[key] = {
            "baseline": base_value,
            "candidate": candidate_value,
            "absolute_delta": delta,
            "relative_delta": None if base_value == 0 else delta / base_value,
        }
    return metrics


def _mean_bool(values) -> float:
    items = [bool(value) for value in values]
    return sum(1 for item in items if item) / max(len(items), 1)


def _answers(sample: DocAgentSample) -> list[str]:
    if isinstance(sample.answer, list):
        return [str(item) for item in sample.answer]
    return [str(sample.answer)]


def answer_scores(prediction: str, answers: list[str]) -> dict[str, Any]:
    return {
        "normalized_exact_match": any(exact_match(prediction, answer) for answer in answers),
        "token_f1": max([token_f1(prediction, answer) for answer in answers] or [0.0]),
        "character_f1": max([character_f1(prediction, answer) for answer in answers] or [0.0]),
        "answer_hit": any(normalize_text(answer) in normalize_text(prediction) for answer in answers if normalize_text(answer)),
    }


def classify_answer_failures(
    *,
    sample: DocAgentSample,
    prediction: dict[str, Any],
    scores: dict[str, Any],
    valid_json: bool,
    format_valid: bool,
    block_location_hit: bool,
) -> list[str]:
    labels: list[str] = []
    if not valid_json:
        labels.append("invalid_json")
    if not format_valid:
        labels.append("format_error")
    if not block_location_hit:
        labels.append("location_error")
    if not scores["normalized_exact_match"]:
        if scores["token_f1"] > 0:
            labels.append("partial_answer")
        else:
            labels.append("answer_miss")
        if sample.answer_type == "numeric":
            labels.append("wrong_number")
        elif prediction.get("answer"):
            labels.append("wrong_entity")
    return sorted(set(labels))


def _clone_block_with_retrieval_metadata(block: EvidenceBlock, *, mode: str, rank: int, candidate: dict[str, Any]) -> EvidenceBlock:
    payload = block.to_dict()
    metadata = dict(payload.get("metadata") or {})
    metadata.update(
        {
            "fixed_evidence_source": "phase3_hybrid_retrieval",
            "retrieval_mode": mode,
            "retrieval_rank": rank,
            "bm25_score": candidate.get("bm25_score"),
            "dense_score": candidate.get("dense_score"),
            "rrf_score": candidate.get("rrf_score"),
            "rerank_score": candidate.get("rerank_score"),
        }
    )
    payload["metadata"] = metadata
    return EvidenceBlock.from_dict(payload)


def build_fixed_evidence_records(
    *,
    samples: list[DocAgentSample],
    retrieval_rows: list[dict[str, Any]],
    corpus_blocks: dict[str, EvidenceBlock],
    top_k: int,
    seed: str,
    retrieval_config: dict[str, Any],
) -> list[dict[str, Any]]:
    rows_by_qid = {row["qid"]: row for row in retrieval_rows if row.get("status") == "completed"}
    fixed_records: list[dict[str, Any]] = []
    for sample in samples:
        row = rows_by_qid.get(sample.qid)
        if row is None:
            continue
        evidence_blocks: list[EvidenceBlock] = []
        for rank, candidate in enumerate(row["candidates"][:top_k], start=1):
            block = corpus_blocks.get(str(candidate["block_id"]))
            if block is None:
                continue
            evidence_blocks.append(
                _clone_block_with_retrieval_metadata(block, mode="hybrid_rerank", rank=rank, candidate=candidate)
            )
        record = sample.to_dict()
        record["evidence"] = [block.to_dict() for block in evidence_blocks]
        metadata = dict(record.get("metadata") or {})
        metadata.update(
            {
                "reader_evidence_source": "phase3_fixed_hybrid_retrieval",
                "reader_top_k": top_k,
                "fixed_evidence_qid_hash": stable_sample_key(sample.qid, seed),
                "fixed_evidence_retrieval_config": retrieval_config,
                "fixed_evidence_block_ids": [block.block_id for block in evidence_blocks],
                "gold_pages": sorted(
                    {
                        page
                        for page in (
                            _block_page(block)
                            for block in sample.evidence
                            if block.block_id in set(metadata.get("gold_block_ids") or [])
                        )
                        if page is not None
                    }
                ),
            }
        )
        record["metadata"] = metadata
        fixed_records.append(record)
    return fixed_records


def build_fixed_reader_evidence_records(
    *,
    samples: list[DocAgentSample],
    top_k: int,
    seed: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for sample in samples:
        record = sample.to_dict()
        record["evidence"] = [block.to_dict() for block in sample.evidence[:top_k]]
        metadata = dict(record.get("metadata") or {})
        metadata.update(
            {
                "reader_evidence_source": "provided_reader_evidence",
                "reader_top_k": top_k,
                "fixed_evidence_qid_hash": stable_sample_key(sample.qid, seed),
                "retrieval_metrics_allowed": False,
            }
        )
        record["metadata"] = metadata
        records.append(record)
    return records


def fixed_evidence_hash(records: list[dict[str, Any]]) -> str:
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    return sha256_text(text)


def build_dense_resources(
    *,
    backend: str,
    model_path: str,
    device: str,
    use_fp16: bool,
    allow_mock_backends: bool,
) -> tuple[Any | None, ModelTiming]:
    if backend == "none":
        return None, ModelTiming()
    if backend == "hash":
        if not allow_mock_backends:
            raise RuntimeError("hash dense backend is only allowed with --allow-mock-backends")
        return HashDenseEncoder(), ModelTiming(dense_model_load_ms=0.0)
    if backend != "bge":
        raise RuntimeError(f"unsupported dense backend: {backend}")
    encoder = DenseEncoder(DenseEncoderConfig(model_path=model_path, device=device, use_fp16=use_fp16))
    start = time.perf_counter()
    if hasattr(encoder, "_load_model"):
        encoder._load_model()
    return encoder, ModelTiming(dense_model_load_ms=(time.perf_counter() - start) * 1000)


def build_reranker(
    *,
    backend: str,
    model_path: str,
    device: str,
    use_fp16: bool,
    allow_mock_backends: bool,
) -> tuple[Any | None, ModelTiming]:
    if backend == "none":
        return None, ModelTiming()
    if backend == "keyword":
        if not allow_mock_backends:
            raise RuntimeError("keyword reranker backend is only allowed with --allow-mock-backends")
        return KeywordOverlapReranker(), ModelTiming(reranker_model_load_ms=0.0)
    if backend != "cross_encoder":
        raise RuntimeError(f"unsupported reranker backend: {backend}")
    reranker = CrossEncoderReranker(
        CrossEncoderRerankerConfig(model_path=model_path, device=device, use_fp16=use_fp16)
    )
    start = time.perf_counter()
    if hasattr(reranker, "_load_model"):
        reranker._load_model()
    return reranker, ModelTiming(reranker_model_load_ms=(time.perf_counter() - start) * 1000)


def build_dense_index_for_corpus(
    *,
    blocks: list[EvidenceBlock],
    dense_encoder: Any | None,
    output_dir: Path,
) -> tuple[DenseIndex | None, float | None]:
    if dense_encoder is None:
        return None, None
    start = time.perf_counter()
    embeddings = dense_encoder.encode_documents([block.retrieval_text for block in blocks])
    if np.asarray(embeddings).shape[0] != len(blocks):
        raise RuntimeError("dense encoder returned a different number of rows than corpus blocks")
    dense_index = DenseIndex.build(blocks=blocks, embeddings=np.asarray(embeddings, dtype=np.float32), model_id=dense_encoder.model_id)
    return dense_index, (time.perf_counter() - start) * 1000


def evaluate_retrieval_mode(
    *,
    mode: str,
    samples: list[DocAgentSample],
    blocks: list[EvidenceBlock],
    top_k: int,
    dense_encoder: Any | None = None,
    dense_index: DenseIndex | None = None,
    reranker: Any | None = None,
    bm25_top_n: int = 20,
    dense_top_n: int = 20,
    fusion_top_n: int = 20,
    rrf_k: int = 60,
    total_records: int | None = None,
    invalid_records: int = 0,
) -> dict[str, Any]:
    retriever = IndexedDocumentRetriever(
        blocks,
        mode=mode,
        dense_encoder=dense_encoder,
        dense_index=dense_index,
        reranker=reranker if mode == "hybrid_rerank" else None,
        bm25_top_n=bm25_top_n,
        dense_top_n=dense_top_n,
        fusion_top_n=fusion_top_n,
        rrf_k=rrf_k,
    )
    block_lookup = {block.block_id: block for block in blocks}
    rows: list[dict[str, Any]] = []
    for sample in samples:
        gold_ids = set(str(item) for item in sample.metadata.get("gold_block_ids") or [])
        start = time.perf_counter()
        result = retriever.retrieve(
            doc_id=sample.doc_id,
            question=sample.question,
            top_k=top_k,
            answer_type_hint=sample.answer_type,
        )
        elapsed = (time.perf_counter() - start) * 1000
        ranking = [candidate.block.block_id for candidate in result.candidates]
        candidate_pages = {_block_page(candidate.block) for candidate in result.candidates}
        gold_pages = {
            _block_page(block_lookup[block_id])
            for block_id in gold_ids
            if block_id in block_lookup and _block_page(block_lookup[block_id]) is not None
        }
        rows.append(
            {
                "qid": sample.qid,
                "doc_id": sample.doc_id,
                "status": "completed",
                "question": sample.question,
                "answer_type": sample.answer_type,
                "ranking": ranking,
                "gold_block_ids": sorted(gold_ids),
                "gold_block_rank": first_gold_rank(ranking, gold_ids),
                "gold_page_hit": bool(candidate_pages & gold_pages),
                "query_input": sample.question,
                "query_processing": QUERY_PROCESSING_LABEL,
                "query_processing_backend": QUERY_PROCESSING_BACKEND,
                "rewritten_query": result.rewritten_query,
                "query_latency_ms": elapsed,
                "component_latency_ms": result.metadata.get("latency_ms", {}),
                "candidates": [
                    candidate.to_trace_dict(final_rank=rank)
                    for rank, candidate in enumerate(result.candidates, start=1)
                ],
                "failure_taxonomy": retrieval_failure_labels(
                    mode=mode,
                    ranking=ranking,
                    gold_ids=gold_ids,
                    gold_in_corpus=gold_ids.issubset(block_lookup),
                ),
            }
        )
    summary = summarize_retrieval_rows(
        rows,
        top_k=top_k,
        total_records=total_records if total_records is not None else len(samples),
        invalid_records=invalid_records,
    )
    summary["mode"] = mode
    return {"summary": summary, "rows": rows}


def build_answer_policy(
    *,
    policy_backend: str,
    mode: str,
    base_model_path: str,
    adapter_path: str | None,
    device: str,
    torch_dtype: str,
    max_prompt_tokens: int,
    max_new_tokens: int,
    allow_mock_backends: bool,
    rank_aware_context: bool = False,
) -> tuple[AnswerPolicy, float]:
    if policy_backend == "heuristic":
        if not allow_mock_backends:
            raise RuntimeError("heuristic AnswerPolicy is only allowed with --allow-mock-backends")
        return HeuristicAnswerPolicy(rank_aware_context=rank_aware_context), 0.0
    if policy_backend != "qwen":
        raise RuntimeError(f"unsupported answer policy backend: {policy_backend}")
    policy = QwenAnswerPolicy(
        QwenAnswerPolicyConfig(
            mode=mode,
            base_model_path=base_model_path,
            adapter_path=adapter_path,
            device=device,
            torch_dtype=torch_dtype,
            max_prompt_tokens=max_prompt_tokens,
            max_new_tokens=max_new_tokens,
            rank_aware_context=rank_aware_context,
        )
    )
    start = time.perf_counter()
    if hasattr(policy, "_load"):
        policy._load()
    return policy, (time.perf_counter() - start) * 1000


def release_policy(policy: AnswerPolicy) -> None:
    if hasattr(policy, "_model"):
        setattr(policy, "_model", None)
    if hasattr(policy, "_tokenizer"):
        setattr(policy, "_tokenizer", None)
    if hasattr(policy, "_loaded"):
        setattr(policy, "_loaded", False)
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def evaluate_answer_policy(
    *,
    samples: list[DocAgentSample],
    policy: AnswerPolicy,
    policy_mode: str,
    top_k: int,
    sqlite_path: Path | None = None,
) -> dict[str, Any]:
    repository = None
    conn = None
    if sqlite_path is not None:
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        conn = connect(sqlite_path)
        repository = TraceRepository(conn)
    rows: list[dict[str, Any]] = []
    try:
        for sample in samples:
            gold_ids = set(str(item) for item in sample.metadata.get("gold_block_ids") or [])
            gold_pages = set(sample.metadata.get("gold_pages") or [])
            if not gold_pages:
                gold_pages = {
                    page
                    for page in (
                        _block_page(block)
                        for block in sample.evidence
                        if block.block_id in gold_ids
                    )
                    if page is not None
                }
            started = time.perf_counter()
            try:
                state = run_qa_workflow(
                    qid=sample.qid,
                    doc_id=sample.doc_id,
                    question=sample.question,
                    blocks=sample.evidence,
                    answer_policy=policy,
                    top_k=min(top_k, len(sample.evidence)),
                    answer_type_hint=sample.answer_type,
                    trace_repository=repository,
                    preserve_input_order=True,
                )
                elapsed = (time.perf_counter() - started) * 1000
                prediction = state.final_answer if isinstance(state.final_answer, dict) else {}
                pred_answer = str(prediction.get("answer") or "")
                scores = answer_scores(pred_answer, _answers(sample))
                location = prediction.get("evidence_location") or {}
                block_location_hit = location.get("block_id") in gold_ids
                page_location_hit = location.get("page") in gold_pages
                final_location_in_evidence = location.get("block_id") in {block.block_id for block in sample.evidence}
                parse_result = state.parse_result or {}
                valid_json = bool(parse_result.get("raw_json_ok") or parse_result.get("schema_ok") or state.draft_answer)
                format_valid = bool(state.format_check.get("success"))
                location_valid = bool(state.location_check.get("success"))
                rows.append(
                    {
                        "qid": sample.qid,
                        "doc_id": sample.doc_id,
                        "status": "completed",
                        "policy_mode": policy_mode,
                        "evidence_block_ids": [block.block_id for block in sample.evidence],
                        "prediction": prediction,
                        "answers": _answers(sample),
                        "answer_metrics": scores,
                        "validation": {
                            "valid_json": valid_json,
                            "format_valid": format_valid,
                            "location_valid": location_valid,
                            "block_location_hit": block_location_hit,
                            "page_location_hit": page_location_hit,
                            "final_location_in_evidence": final_location_in_evidence,
                            "repair_attempted": bool(state.repair_attempted),
                            "repair_success": bool(
                                state.repair_attempted
                                and state.format_check.get("success")
                                and state.location_check.get("success")
                            ),
                        },
                        "latency_ms": elapsed,
                        "generation_latency_ms": state.generation_metadata.get("latency_ms"),
                        "run_id": state.run_id,
                        "failure_taxonomy": classify_answer_failures(
                            sample=sample,
                            prediction=prediction,
                            scores=scores,
                            valid_json=valid_json,
                            format_valid=format_valid,
                            block_location_hit=block_location_hit,
                        ),
                    }
                )
            except Exception as exc:
                rows.append(
                    {
                        "qid": sample.qid,
                        "doc_id": sample.doc_id,
                        "status": "failed",
                        "policy_mode": policy_mode,
                        "error": f"{type(exc).__name__}: {exc}",
                        "failure_taxonomy": ["unsupported_answer"],
                    }
                )
    finally:
        if conn is not None:
            conn.close()
    return {"summary": summarize_answer_rows(rows), "rows": rows}


def summarize_answer_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [row for row in rows if row.get("status") == "completed"]
    count = len(completed)
    latencies = [float(row["latency_ms"]) for row in completed]
    return {
        "sample_count": len(rows),
        "completed_count": count,
        "failed_count": len(rows) - count,
        "normalized_exact_match": _mean_bool(row["answer_metrics"]["normalized_exact_match"] for row in completed),
        "answer_hit": _mean_bool(row["answer_metrics"]["answer_hit"] for row in completed),
        "token_f1": sum(float(row["answer_metrics"]["token_f1"]) for row in completed) / max(count, 1),
        "character_f1": sum(float(row["answer_metrics"]["character_f1"]) for row in completed) / max(count, 1),
        "valid_json_rate": _mean_bool(row["validation"]["valid_json"] for row in completed),
        "format_valid_rate": _mean_bool(row["validation"]["format_valid"] for row in completed),
        "block_location_hit": _mean_bool(row["validation"]["block_location_hit"] for row in completed),
        "page_location_hit": _mean_bool(row["validation"]["page_location_hit"] for row in completed),
        "final_location_in_evidence_rate": _mean_bool(
            row["validation"]["final_location_in_evidence"] for row in completed
        ),
        "repair_attempted_rate": _mean_bool(row["validation"]["repair_attempted"] for row in completed),
        "repair_success_rate": _mean_bool(row["validation"]["repair_success"] for row in completed),
        "latency": aggregate_latency(latencies),
    }


def write_summary_markdown(
    path: Path,
    *,
    retrieval_comparison: dict[str, Any],
    answer_comparison: dict[str, Any],
    failure_counts: dict[str, int],
    benchmark_role: str,
    result_type: str = "fixed subset evaluation, not formal benchmark",
) -> None:
    hybrid_better = any(
        item.get("absolute_delta", 0.0) > 0
        for key, item in retrieval_comparison.get("metrics", {}).items()
        if key in {"recall_at_1", "recall_at_3", "recall_at_5", "mrr", "gold_page_hit_rate"}
    )
    grpo_better = any(
        item.get("absolute_delta", 0.0) > 0
        for key, item in answer_comparison.get("metrics", {}).items()
        if key
        in {
            "normalized_exact_match",
            "token_f1",
            "character_f1",
            "format_valid_rate",
            "block_location_hit",
            "page_location_hit",
        }
    )
    retrieval_improved = [
        key
        for key, item in retrieval_comparison.get("metrics", {}).items()
        if item.get("absolute_delta", 0.0) > 0
    ]
    answer_improved = [
        key
        for key, item in answer_comparison.get("metrics", {}).items()
        if item.get("absolute_delta", 0.0) > 0
    ]
    lines = [
        "# Phase 3A Focused Evaluation Summary",
        "",
        f"- Hybrid better than BM25: {str(hybrid_better).lower()}",
        f"- Retrieval improvements: {', '.join(retrieval_improved) if retrieval_improved else 'none'}",
        f"- GRPO better than SFT: {str(grpo_better).lower()}",
        f"- AnswerPolicy improvements: {', '.join(answer_improved) if answer_improved else 'none'}",
        f"- Main failure types: {json.dumps(failure_counts, ensure_ascii=False, sort_keys=True)}",
        f"- Result type: {result_type}; dataset role={benchmark_role}",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def collect_failure_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        for label in row.get("failure_taxonomy") or []:
            counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


def load_benchmark_manifest(root: Path, manifest_arg: str | Path | None) -> dict[str, Any] | None:
    if not manifest_arg:
        return None
    path = repo_path(root, manifest_arg)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"invalid evaluation contract metadata: cannot read benchmark manifest: {exc}") from exc


def manifest_artifact_arg(manifest: dict[str, Any], key: str) -> str:
    value = manifest.get(key)
    if not value:
        raise RuntimeError(f"invalid evaluation contract metadata: benchmark manifest missing {key}")
    return str(value)


def _same_repo_path(root: Path, left: str | Path, right: str | Path) -> bool:
    return repo_path(root, left).resolve() == repo_path(root, right).resolve()


def manifest_contract_kwargs(manifest: dict[str, Any] | None) -> dict[str, Any]:
    if not manifest:
        return {}
    return {
        "artifact_role": manifest.get("artifact_role"),
        "source_qa_role": manifest.get("source_qa_role"),
        "evaluation_scope": manifest.get("evaluation_scope", "primary_retrieval"),
        "formal_benchmark": bool(manifest.get("formal_benchmark", False)),
        "primary_benchmark": bool(manifest.get("primary_benchmark", True)),
    }


def verify_manifest_contract_metadata(
    *,
    manifest: dict[str, Any] | None,
    samples: list[DocAgentSample],
    corpus_blocks: list[EvidenceBlock] | None,
) -> None:
    if not manifest:
        return
    expected_qid_hash = manifest.get("qid_hash")
    actual_qid_hash = qid_hash([sample.qid for sample in samples])
    if expected_qid_hash and expected_qid_hash != actual_qid_hash:
        raise RuntimeError(
            "invalid evaluation contract metadata: "
            f"qid_hash mismatch manifest={expected_qid_hash} actual={actual_qid_hash}"
        )
    expected_corpus_hash = manifest.get("corpus_hash")
    if expected_corpus_hash:
        if corpus_blocks is None:
            raise RuntimeError("invalid evaluation contract metadata: benchmark manifest requires corpus input")
        actual_corpus_hash = corpus_hash(corpus_blocks)
        if expected_corpus_hash != actual_corpus_hash:
            raise RuntimeError(
                "invalid evaluation contract metadata: "
                f"corpus_hash mismatch manifest={expected_corpus_hash} actual={actual_corpus_hash}"
            )
    if manifest.get("corpus_is_query_independent") is False:
        raise RuntimeError("invalid evaluation contract metadata: manifest corpus_is_query_independent is false")


def result_type_for_contract(contract: BenchmarkContract, *, retrieval_only: bool = False) -> str:
    if contract.evaluation_scope == "scenario_regression":
        suffix = "retrieval-only " if retrieval_only else ""
        return f"real-document scenario regression {suffix}metrics, not formal benchmark"
    suffix = "retrieval-only " if retrieval_only else ""
    return f"{suffix}fixed subset evaluation, not formal benchmark"


def run_focused_evaluation(args: Any, *, root: Path) -> dict[str, Any]:
    if getattr(args, "validate_only", False) and getattr(args, "answer_only", False):
        raise RuntimeError("--validate-only and --answer-only cannot be combined")
    if getattr(args, "retrieval_only", False) and getattr(args, "answer_only", False):
        raise RuntimeError("--retrieval-only and --answer-only cannot be combined")
    benchmark_manifest_arg = getattr(args, "benchmark_manifest", None)
    source_manifest = load_benchmark_manifest(root, benchmark_manifest_arg)
    manifest_qa_arg = manifest_artifact_arg(source_manifest, "qa_artifact") if source_manifest else None
    manifest_corpus_arg = manifest_artifact_arg(source_manifest, "corpus_artifact") if source_manifest else None
    explicit_qa_arg = getattr(args, "qa_input", None)
    explicit_corpus_arg = getattr(args, "corpus_input", None)
    if source_manifest and explicit_qa_arg and not _same_repo_path(root, explicit_qa_arg, manifest_qa_arg):
        raise RuntimeError("invalid evaluation contract metadata: --qa-input does not match benchmark manifest")
    if source_manifest and explicit_corpus_arg and not _same_repo_path(root, explicit_corpus_arg, manifest_corpus_arg):
        raise RuntimeError("invalid evaluation contract metadata: --corpus-input does not match benchmark manifest")
    qa_input_arg = manifest_qa_arg or explicit_qa_arg or args.benchmark_input
    qa_input = repo_path(root, qa_input_arg)
    samples = load_samples(qa_input)
    corpus_input_arg = manifest_corpus_arg or explicit_corpus_arg
    corpus_blocks = load_corpus_blocks(repo_path(root, corpus_input_arg)) if corpus_input_arg else None
    verify_manifest_contract_metadata(
        manifest=source_manifest,
        samples=samples,
        corpus_blocks=corpus_blocks,
    )
    retrieval_contract = validate_benchmark_contract(
        samples,
        input_path=qa_input_arg,
        corpus_blocks=corpus_blocks,
        corpus_input_path=corpus_input_arg,
        **manifest_contract_kwargs(source_manifest),
    )
    answer_only = bool(getattr(args, "answer_only", False))
    reader_contract = (
        validate_reader_artifact_contract(samples, input_path=qa_input_arg)
        if answer_only
        else None
    )
    if getattr(args, "validate_only", False):
        payload = contract_payload(
            retrieval_contract=retrieval_contract,
            reader_contract=reader_contract,
            status="success" if retrieval_contract.status == "ready" else "failed",
            exception=None
            if retrieval_contract.status == "ready"
            else "invalid evaluation contract metadata: " + "; ".join(retrieval_contract.errors[:5]),
        )
        if payload["status"] != "success":
            raise ContractValidationError(payload)
        return payload
    if not answer_only and retrieval_contract.status != "ready":
        raise ContractValidationError(
            contract_payload(
                retrieval_contract=retrieval_contract,
                reader_contract=reader_contract,
                status="failed",
                exception="invalid evaluation contract metadata: " + "; ".join(retrieval_contract.errors[:5]),
            )
        )
    if answer_only and reader_contract.status != "ready":
        raise ContractValidationError(
            contract_payload(
                retrieval_contract=retrieval_contract,
                reader_contract=reader_contract,
                status="failed",
                exception="answer policy evaluation blocked: reader evidence artifact is invalid",
            )
        )

    active_corpus_blocks = list(corpus_blocks or [])
    retrieval_samples = select_stable_subset(samples, limit=args.retrieval_limit, seed=args.seed)
    answer_limit = args.answer_limit if args.answer_limit is not None else args.retrieval_limit
    answer_source_samples = retrieval_samples if not answer_only else select_stable_subset(samples, limit=answer_limit, seed=args.seed)
    answer_sample_ids = {
        sample.qid for sample in select_stable_subset(answer_source_samples, limit=answer_limit, seed=args.seed)
    }
    answer_samples = [sample for sample in answer_source_samples if sample.qid in answer_sample_ids]
    corpus_by_id = {block.block_id: block for block in active_corpus_blocks}
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = repo_path(root, args.output_root) / run_id
    if run_dir.exists() and not args.force:
        raise RuntimeError(f"output run directory already exists: {safe_artifact_path(root, run_dir)}")
    if run_dir.exists():
        shutil.rmtree(run_dir)
    for subdir in ("retrieval", "answer_policy", "logs"):
        (run_dir / subdir).mkdir(parents=True, exist_ok=True)

    retrieval_config = {
        "top_k": args.top_k,
        "bm25_top_n": args.bm25_top_n,
        "dense_top_n": args.dense_top_n,
        "fusion_top_n": args.fusion_top_n,
        "rrf_k": args.rrf_k,
        "query_processing": QUERY_PROCESSING_LABEL,
        "dense_backend": REAL_DENSE_BACKEND if args.dense_backend == "bge" else args.dense_backend,
        "reranker_backend": REAL_RERANKER_BACKEND if args.reranker_backend == "cross_encoder" else args.reranker_backend,
    }
    result_type = result_type_for_contract(retrieval_contract)
    if answer_only:
        bm25 = {"summary": {"status": "blocked"}, "rows": []}
        hybrid = {"summary": {"status": "blocked"}, "rows": []}
        retrieval_comparison = {
            "status": "blocked",
            "reason": "query-independent retrieval corpus was not supplied",
            "metrics": {},
        }
        combined_retrieval_rows: list[dict[str, Any]] = []
        fixed_records = build_fixed_reader_evidence_records(
            samples=answer_samples,
            top_k=args.top_k,
            seed=args.seed,
        )
    else:
        dense_encoder, dense_load_timing = build_dense_resources(
            backend=args.dense_backend,
            model_path=args.dense_model_path,
            device=args.dense_device,
            use_fp16=args.dense_fp16,
            allow_mock_backends=args.allow_mock_backends,
        )
        dense_index, dense_index_build_ms = build_dense_index_for_corpus(
            blocks=active_corpus_blocks,
            dense_encoder=dense_encoder,
            output_dir=run_dir,
        )
        reranker, reranker_load_timing = build_reranker(
            backend=args.reranker_backend,
            model_path=args.reranker_model_path,
            device=args.reranker_device,
            use_fp16=args.reranker_fp16,
            allow_mock_backends=args.allow_mock_backends,
        )
        bm25 = evaluate_retrieval_mode(
            mode="bm25",
            samples=retrieval_samples,
            blocks=active_corpus_blocks,
            top_k=args.top_k,
            total_records=len(retrieval_samples),
            invalid_records=retrieval_contract.invalid_records,
            bm25_top_n=args.bm25_top_n,
        )
        hybrid = evaluate_retrieval_mode(
            mode="hybrid_rerank",
            samples=retrieval_samples,
            blocks=active_corpus_blocks,
            top_k=args.top_k,
            dense_encoder=dense_encoder,
            dense_index=dense_index,
            reranker=reranker,
            total_records=len(retrieval_samples),
            invalid_records=retrieval_contract.invalid_records,
            bm25_top_n=args.bm25_top_n,
            dense_top_n=args.dense_top_n,
            fusion_top_n=args.fusion_top_n,
            rrf_k=args.rrf_k,
        )
        hybrid["summary"]["model_load_latency_ms"] = {
            "dense": dense_load_timing.dense_model_load_ms,
            "reranker": reranker_load_timing.reranker_model_load_ms,
        }
        hybrid["summary"]["index_build_latency_ms"] = dense_index_build_ms
        retrieval_comparison = {
            "baseline": "bm25",
            "candidate": "hybrid_rerank",
            "metrics": compare_metrics(
                hybrid["summary"],
                bm25["summary"],
                ["recall_at_1", "recall_at_3", "recall_at_5", "mrr", "gold_page_hit_rate"],
            ),
        }
        combined_retrieval_rows = []
        bm25_rows = {row["qid"]: row for row in bm25["rows"]}
        for hybrid_row in hybrid["rows"]:
            row = {"qid": hybrid_row["qid"], "bm25": bm25_rows.get(hybrid_row["qid"]), "hybrid": hybrid_row}
            if row["bm25"] and not hybrid_row["gold_block_rank"] and row["bm25"].get("gold_block_rank"):
                hybrid_row["failure_taxonomy"] = sorted(
                    set(hybrid_row["failure_taxonomy"] + ["reranker_demoted_gold"])
                )
            combined_retrieval_rows.append(row)
        if bool(getattr(args, "retrieval_only", False)):
            retrieval_failures = [
                {
                    "qid": row["hybrid"]["qid"],
                    "bm25_failure_taxonomy": (row.get("bm25") or {}).get("failure_taxonomy", []),
                    "hybrid_failure_taxonomy": row["hybrid"].get("failure_taxonomy", []),
                    "bm25_gold_block_rank": (row.get("bm25") or {}).get("gold_block_rank"),
                    "hybrid_gold_block_rank": row["hybrid"].get("gold_block_rank"),
                }
                for row in combined_retrieval_rows
                if (row.get("bm25") or {}).get("failure_taxonomy") or row["hybrid"].get("failure_taxonomy")
            ]
            failure_counts = collect_failure_counts(hybrid["rows"])
            write_jsonl(run_dir / "retrieval" / "per_sample_results.jsonl", combined_retrieval_rows)
            write_jsonl(run_dir / "retrieval" / "failure_cases.jsonl", retrieval_failures)
            for path, payload in (
                (run_dir / "retrieval" / "bm25_metrics.json", bm25["summary"]),
                (run_dir / "retrieval" / "hybrid_metrics.json", hybrid["summary"]),
                (run_dir / "retrieval" / "comparison.json", retrieval_comparison),
            ):
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            benchmark_manifest = {
                "retrieval_contract": retrieval_contract.to_dict(),
                "reader_contract": reader_contract.to_dict() if reader_contract is not None else None,
                "source_benchmark_manifest": safe_artifact_path(root, repo_path(root, benchmark_manifest_arg)) if benchmark_manifest_arg else None,
                "seed": args.seed,
                "retrieval_sample_count": len(retrieval_samples),
                "answer_sample_count": 0,
                "retrieval_qid_hash": qid_hash([sample.qid for sample in retrieval_samples]),
                "answer_qid_hash": None,
                "fixed_evidence_sha256": None,
                "fixed_evidence_path": None,
                "retrieval_config": retrieval_config,
            }
            run_manifest = {
                "command": "phase3_focused_eval",
                "run_id": run_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "status": "success",
                "result_type": result_type_for_contract(retrieval_contract, retrieval_only=True),
                "qa_input": safe_artifact_path(root, qa_input),
                "corpus_input": safe_artifact_path(root, repo_path(root, corpus_input_arg)) if corpus_input_arg else None,
                "benchmark_manifest_input": safe_artifact_path(root, repo_path(root, benchmark_manifest_arg)) if benchmark_manifest_arg else None,
                "output_dir": safe_artifact_path(root, run_dir),
                "models": {
                    "dense_backend": retrieval_config["dense_backend"],
                    "dense_model": safe_model_label(args.dense_model_path),
                    "reranker_backend": retrieval_config["reranker_backend"],
                    "reranker_model": safe_model_label(args.reranker_model_path),
                    "answer_backend": None,
                    "mock_backends_allowed": bool(args.allow_mock_backends),
                },
            }
            summary = {
                "command": "phase3_focused_eval",
                "status": "success",
                "run_id": run_id,
                "result_type": result_type_for_contract(retrieval_contract, retrieval_only=True),
                "benchmark_role": retrieval_contract.role,
                "source_qa_role": retrieval_contract.source_qa_role,
                "evaluation_scope": retrieval_contract.evaluation_scope,
                "formal_benchmark": retrieval_contract.formal_benchmark,
                "primary_benchmark": retrieval_contract.primary_benchmark,
                "retrieval_evaluation": "ready",
                "answer_policy_evaluation": "not_started",
                "retrieval": {
                    "bm25": bm25["summary"],
                    "hybrid": hybrid["summary"],
                    "comparison": retrieval_comparison,
                },
                "answer_policy": {},
                "failure_counts": failure_counts,
                "artifact_paths": {
                    "run_manifest": safe_artifact_path(root, run_dir / "run_manifest.json"),
                    "benchmark_manifest": safe_artifact_path(root, run_dir / "benchmark_manifest.json"),
                    "summary": safe_artifact_path(root, run_dir / "summary.json"),
                    "summary_md": safe_artifact_path(root, run_dir / "summary.md"),
                },
            }
            for path, payload in (
                (run_dir / "run_manifest.json", run_manifest),
                (run_dir / "benchmark_manifest.json", benchmark_manifest),
                (run_dir / "summary.json", summary),
            ):
                forbidden = validate_no_forbidden_paths(payload)
                if forbidden:
                    raise RuntimeError(f"refusing to persist forbidden path or URL data in {path.name}: {forbidden[:3]}")
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            write_summary_markdown(
                run_dir / "summary.md",
                retrieval_comparison=retrieval_comparison,
                answer_comparison={"metrics": {}},
                failure_counts=failure_counts,
                benchmark_role=retrieval_contract.role,
                result_type=result_type_for_contract(retrieval_contract, retrieval_only=True),
            )
            return summary
        fixed_records = build_fixed_evidence_records(
            samples=answer_samples,
            retrieval_rows=hybrid["rows"],
            corpus_blocks=corpus_by_id,
            top_k=args.top_k,
            seed=args.seed,
            retrieval_config=retrieval_config,
        )
    fixed_hash = fixed_evidence_hash(fixed_records)
    forbidden_fixed = validate_no_forbidden_paths(fixed_records, where="fixed_evidence")
    if forbidden_fixed:
        raise RuntimeError(f"refusing to persist forbidden path or URL data in fixed evidence: {forbidden_fixed[:3]}")
    fixed_path = run_dir / "answer_policy" / "fixed_evidence.jsonl"
    write_jsonl(fixed_path, fixed_records)
    fixed_samples = [DocAgentSample.from_dict(record) for record in fixed_records]
    reader_contract = validate_reader_artifact_contract(
        fixed_samples,
        input_path=safe_artifact_path(root, fixed_path),
        require_gold_in_evidence=answer_only,
    )
    if reader_contract.status != "ready":
        raise ContractValidationError(
            contract_payload(
                retrieval_contract=retrieval_contract,
                reader_contract=reader_contract,
                status="failed",
                exception="answer policy evaluation blocked: fixed reader evidence artifact is invalid",
            )
        )

    sft_policy, sft_load_ms = build_answer_policy(
        policy_backend=args.answer_backend,
        mode="sft",
        base_model_path=args.base_model_path,
        adapter_path=args.sft_adapter_path,
        device=args.qwen_device,
        torch_dtype=args.qwen_torch_dtype,
        max_prompt_tokens=args.max_prompt_tokens,
        max_new_tokens=args.max_new_tokens,
        allow_mock_backends=args.allow_mock_backends,
    )
    try:
        sft_result = evaluate_answer_policy(
            samples=fixed_samples,
            policy=sft_policy,
            policy_mode="sft",
            top_k=args.top_k,
            sqlite_path=run_dir / "logs" / "sft_trace.sqlite",
        )
    finally:
        release_policy(sft_policy)
    grpo_policy, grpo_load_ms = build_answer_policy(
        policy_backend=args.answer_backend,
        mode="grpo",
        base_model_path=args.base_model_path,
        adapter_path=args.grpo_adapter_path,
        device=args.qwen_device,
        torch_dtype=args.qwen_torch_dtype,
        max_prompt_tokens=args.max_prompt_tokens,
        max_new_tokens=args.max_new_tokens,
        allow_mock_backends=args.allow_mock_backends,
    )
    try:
        grpo_result = evaluate_answer_policy(
            samples=fixed_samples,
            policy=grpo_policy,
            policy_mode="grpo",
            top_k=args.top_k,
            sqlite_path=run_dir / "logs" / "grpo_trace.sqlite",
        )
    finally:
        release_policy(grpo_policy)
    sft_result["summary"]["model_load_latency_ms"] = sft_load_ms
    grpo_result["summary"]["model_load_latency_ms"] = grpo_load_ms
    answer_comparison = {
        "baseline": "sft",
        "candidate": "grpo",
        "fixed_evidence_sha256": fixed_hash,
        "metrics": compare_metrics(
            grpo_result["summary"],
            sft_result["summary"],
            [
                "normalized_exact_match",
                "answer_hit",
                "token_f1",
                "character_f1",
                "valid_json_rate",
                "format_valid_rate",
                "block_location_hit",
                "page_location_hit",
                "final_location_in_evidence_rate",
                "repair_attempted_rate",
                "repair_success_rate",
            ],
        ),
    }

    retrieval_failures = [
        {
            "qid": row["hybrid"]["qid"],
            "bm25_failure_taxonomy": (row.get("bm25") or {}).get("failure_taxonomy", []),
            "hybrid_failure_taxonomy": row["hybrid"].get("failure_taxonomy", []),
            "bm25_gold_block_rank": (row.get("bm25") or {}).get("gold_block_rank"),
            "hybrid_gold_block_rank": row["hybrid"].get("gold_block_rank"),
        }
        for row in combined_retrieval_rows
        if (row.get("bm25") or {}).get("failure_taxonomy") or row["hybrid"].get("failure_taxonomy")
    ]
    answer_failures = [
        {
            "qid": row.get("qid"),
            "policy_mode": row.get("policy_mode"),
            "failure_taxonomy": row.get("failure_taxonomy"),
            "prediction": row.get("prediction"),
        }
        for row in [*sft_result["rows"], *grpo_result["rows"]]
        if row.get("failure_taxonomy")
    ]
    failure_counts = collect_failure_counts(
        [*hybrid["rows"], *sft_result["rows"], *grpo_result["rows"]]
    )

    write_jsonl(run_dir / "retrieval" / "per_sample_results.jsonl", combined_retrieval_rows)
    write_jsonl(run_dir / "retrieval" / "failure_cases.jsonl", retrieval_failures)
    write_jsonl(run_dir / "answer_policy" / "sft_results.jsonl", sft_result["rows"])
    write_jsonl(run_dir / "answer_policy" / "grpo_results.jsonl", grpo_result["rows"])
    write_jsonl(run_dir / "answer_policy" / "failure_cases.jsonl", answer_failures)
    for path, payload in (
        (run_dir / "retrieval" / "bm25_metrics.json", bm25["summary"]),
        (run_dir / "retrieval" / "hybrid_metrics.json", hybrid["summary"]),
        (run_dir / "retrieval" / "comparison.json", retrieval_comparison),
        (run_dir / "answer_policy" / "sft_metrics.json", sft_result["summary"]),
        (run_dir / "answer_policy" / "grpo_metrics.json", grpo_result["summary"]),
        (run_dir / "answer_policy" / "comparison.json", answer_comparison),
    ):
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    benchmark_manifest = {
        "retrieval_contract": retrieval_contract.to_dict(),
        "reader_contract": reader_contract.to_dict(),
        "source_benchmark_manifest": safe_artifact_path(root, repo_path(root, benchmark_manifest_arg)) if benchmark_manifest_arg else None,
        "seed": args.seed,
        "retrieval_sample_count": 0 if answer_only else len(retrieval_samples),
        "answer_sample_count": len(fixed_samples),
        "retrieval_qid_hash": None if answer_only else qid_hash([sample.qid for sample in retrieval_samples]),
        "answer_qid_hash": qid_hash([sample.qid for sample in fixed_samples]),
        "fixed_evidence_sha256": fixed_hash,
        "fixed_evidence_path": safe_artifact_path(root, fixed_path),
        "fixed_evidence_top_k": args.top_k,
        "retrieval_config": retrieval_config,
    }
    run_manifest = {
        "command": "phase3_focused_eval",
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "success",
        "result_type": result_type,
        "qa_input": safe_artifact_path(root, qa_input),
        "corpus_input": safe_artifact_path(root, repo_path(root, corpus_input_arg)) if corpus_input_arg else None,
        "benchmark_manifest_input": safe_artifact_path(root, repo_path(root, benchmark_manifest_arg)) if benchmark_manifest_arg else None,
        "output_dir": safe_artifact_path(root, run_dir),
        "models": {
            "dense_backend": retrieval_config["dense_backend"],
            "dense_model": safe_model_label(args.dense_model_path),
            "reranker_backend": retrieval_config["reranker_backend"],
            "reranker_model": safe_model_label(args.reranker_model_path),
            "answer_backend": args.answer_backend,
            "base_model": safe_model_label(args.base_model_path),
            "sft_adapter": safe_model_label(args.sft_adapter_path),
            "grpo_adapter": safe_model_label(args.grpo_adapter_path),
            "mock_backends_allowed": bool(args.allow_mock_backends),
        },
    }
    summary = {
        "command": "phase3_focused_eval",
        "status": "success",
        "run_id": run_id,
        "result_type": result_type,
        "benchmark_role": retrieval_contract.role,
        "source_qa_role": retrieval_contract.source_qa_role,
        "evaluation_scope": retrieval_contract.evaluation_scope,
        "formal_benchmark": retrieval_contract.formal_benchmark,
        "primary_benchmark": retrieval_contract.primary_benchmark,
        "retrieval_evaluation": "blocked" if answer_only else "ready",
        "answer_policy_evaluation": "ready",
        "retrieval": {
            "bm25": bm25["summary"],
            "hybrid": hybrid["summary"],
            "comparison": retrieval_comparison,
        },
        "answer_policy": {
            "fixed_evidence_sha256": fixed_hash,
            "sft": sft_result["summary"],
            "grpo": grpo_result["summary"],
            "comparison": answer_comparison,
        },
        "failure_counts": failure_counts,
        "artifact_paths": {
            "run_manifest": safe_artifact_path(root, run_dir / "run_manifest.json"),
            "benchmark_manifest": safe_artifact_path(root, run_dir / "benchmark_manifest.json"),
            "summary": safe_artifact_path(root, run_dir / "summary.json"),
            "summary_md": safe_artifact_path(root, run_dir / "summary.md"),
        },
    }
    for path, payload in (
        (run_dir / "run_manifest.json", run_manifest),
        (run_dir / "benchmark_manifest.json", benchmark_manifest),
        (run_dir / "summary.json", summary),
    ):
        forbidden = validate_no_forbidden_paths(payload)
        if forbidden:
            raise RuntimeError(f"refusing to persist forbidden path or URL data in {path.name}: {forbidden[:3]}")
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_summary_markdown(
        run_dir / "summary.md",
        retrieval_comparison=retrieval_comparison,
        answer_comparison=answer_comparison,
        failure_counts=failure_counts,
        benchmark_role=retrieval_contract.role,
        result_type=result_type,
    )
    return summary
