from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docagent.ingestion.document_registry import SUPPORTED_EXTENSIONS, DocumentRegistry
from docagent.ingestion.hashing import sha256_file
from docagent.ingestion.service import DocumentIngestionService
from docagent.integrations.mineru_api import MinerUApiClient, refresh_mineru_api_manifest_inventory
from docagent.parser.mineru_backend import MinerUParserBackend
from docagent.parser.mineru_converter import find_content_list
from docagent.parser.text_backend import TextParserBackend
from docagent.retrieval.dense_encoder import DenseEncoder, DenseEncoderConfig, HashDenseEncoder
from docagent.retrieval.dense_index import DenseIndex
from docagent.retrieval.index_manager import IndexedDocumentRetriever
from docagent.retrieval.query_planner import plan_queries
from docagent.retrieval.reranker import CrossEncoderReranker, CrossEncoderRerankerConfig, KeywordOverlapReranker
from docagent.router.llm_router import DEFAULT_LLM_ROUTER_THRESHOLD, plan_route_with_optional_llm
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository, TraceRepository
from docagent.tools.document_tools import (
    count_blocks,
    count_images,
    count_pages,
    count_tables,
    get_page_text,
    list_pages,
)
from docagent.tools.document_summary import summarize_document
from docagent.tools.local_fact_qa import local_fact_qa
from docagent.tools.structured_extraction import structured_extract
from docagent.tools.table_tools import table_lookup_or_calculation


AVAILABLE_TOOLS = [
    "local_fact_qa",
    "count_pages",
    "count_blocks",
    "count_tables",
    "count_images",
    "get_page_text",
    "list_pages",
    "document_summary",
    "extract_all_tables",
    "extract_all_images",
    "list_sections",
    "document_outline",
    "extract_all_dates",
    "structured_extract",
    "table_lookup",
    "simple_calculation",
]
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "cli"
DEFAULT_DOCUMENT_ROOT = ROOT / "data" / "documents"
DEFAULT_ROUTER_LLM_ENV_FILE = ".secrets/router_llm.env"
DEFAULT_MINERU_ENV_FILE = ".secrets/mineru.env"
DEFAULT_QWEN_BASE_MODEL_PATH = "/root/autodl-tmp/models/Qwen3-1.7B"
DEFAULT_BGE_MODEL_PATH = "/root/autodl-tmp/models/bge-m3"
DEFAULT_RERANKER_MODEL_PATH = "/root/autodl-tmp/models/bge-reranker-v2-m3"
ANSWER_POLICY_CHOICES = {"heuristic", "base", "sft", "grpo"}
RETRIEVER_MODE_CHOICES = {"bm25", "dense", "hybrid", "hybrid_rerank"}


def _now_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"docagent_cli_{stamp}_{uuid.uuid4().hex[:8]}"


def _project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _json_default(value: Any) -> str:
    return str(value)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def _print_json(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)
    try:
        print(text)
    except UnicodeEncodeError:
        print(json.dumps(payload, ensure_ascii=True, indent=2, default=_json_default))


def _build_answer_policy(
    *,
    answer_policy: str,
    base_model_path: str,
    adapter_path: str | None,
    device: str,
    torch_dtype: str,
    max_prompt_tokens: int | None,
    max_new_tokens: int,
    answer_output_contract: str,
):
    if answer_policy == "heuristic":
        from docagent.models.base import HeuristicAnswerPolicy

        return HeuristicAnswerPolicy()
    from docagent.models.qwen_answer_policy import QwenAnswerPolicy, QwenAnswerPolicyConfig

    return QwenAnswerPolicy(
        QwenAnswerPolicyConfig(
            mode=answer_policy,
            base_model_path=base_model_path,
            adapter_path=adapter_path,
            device=device,
            torch_dtype=torch_dtype,
            max_prompt_tokens=max_prompt_tokens,
            max_new_tokens=max_new_tokens,
            answer_output_contract=answer_output_contract,
        )
    )


def _answer_policy_metadata(answer_policy: Any) -> dict[str, Any]:
    mode = str(getattr(answer_policy, "mode", "unknown") or "unknown")
    config = getattr(answer_policy, "config", None)
    output_contract = str(getattr(config, "answer_output_contract", "") or "")
    payload = {
        "answer_policy_mode": mode,
        "used_qwen_answer_policy": mode in {"base", "sft", "grpo"},
        "used_external_answer_api": False,
    }
    if output_contract:
        payload["answer_output_contract"] = output_contract
    return payload


def _router_execution(router_plan: dict[str, Any]) -> dict[str, Any]:
    warnings = [str(item) for item in router_plan.get("warnings") or []]
    llm_router = router_plan.get("llm_router") if isinstance(router_plan.get("llm_router"), dict) else {}
    router_source = str(router_plan.get("router_source") or "")
    llm_status = str(llm_router.get("status") or ("used" if router_source == "llm_fallback" else "skipped"))
    skip_reason = ""
    if router_source == "rule":
        if "llm_router_disabled" in warnings:
            skip_reason = "llm_router_disabled"
        elif "visual_understanding_unsupported" in warnings:
            skip_reason = "visual_understanding_unsupported"
        else:
            skip_reason = "high_confidence_or_rule_sufficient"
    elif router_source == "rule_after_llm_failure":
        error = llm_router.get("error") if isinstance(llm_router.get("error"), dict) else {}
        skip_reason = str(error.get("type") or next((item for item in warnings if item.startswith("llm_router_")), "llm_router_failed"))
    return {
        "router_source": router_source,
        "llm_router_status": llm_status,
        "llm_router_skip_reason": skip_reason,
        "llm_router_attempted": bool(llm_router),
        "used_llm_router": router_source == "llm_fallback",
        "rule_confidence": router_plan.get("confidence"),
        "final_task_type": str(router_plan.get("task_type") or ""),
    }


def _query_planner_execution(query_planner: dict[str, Any]) -> dict[str, Any]:
    query_sources = query_planner.get("query_sources") if isinstance(query_planner.get("query_sources"), dict) else {}
    llm_queries_in_final = list(query_sources.get("llm") or [])
    llm_status = str(query_planner.get("llm_status") or "")
    return {
        "query_planner_mode": str(query_planner.get("mode") or ""),
        "llm_query_rewriter_status": llm_status,
        "llm_query_rewriter_attempted": llm_status not in {"", "not_started", "skipped"},
        "used_llm_query_rewriter": bool(llm_queries_in_final),
        "llm_final_query_count": len(llm_queries_in_final),
        "final_query_count": len(query_planner.get("final_queries") or []),
    }


def _base_result(
    *,
    mode: str,
    run_id: str,
    doc_id: str = "",
    source: dict[str, Any] | None = None,
    question: str = "",
    task_type: str = "",
    router_plan: dict[str, Any] | None = None,
    artifact_dir: str = "",
) -> dict[str, Any]:
    return {
        "status": "success",
        "mode": mode,
        "doc_id": doc_id,
        "source": source or {},
        "question": question,
        "task_type": task_type,
        "router_plan": router_plan or {},
        "answer": "",
        "reasoning_summary": "",
        "evidence_used": [],
        "citations": [],
        "supporting_evidence_ids": [],
        "tools_used": [],
        "run_id": run_id,
        "trace_path": "",
        "artifact_dir": artifact_dir,
        "warnings": [],
        "error": {},
    }


def _error_result(
    *,
    mode: str,
    run_id: str,
    error_type: str,
    message: str,
    doc_id: str = "",
    source: dict[str, Any] | None = None,
    question: str = "",
    task_type: str = "",
    router_plan: dict[str, Any] | None = None,
    artifact_dir: str = "",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    result = _base_result(
        mode=mode,
        run_id=run_id,
        doc_id=doc_id,
        source=source,
        question=question,
        task_type=task_type,
        router_plan=router_plan,
        artifact_dir=artifact_dir,
    )
    result["status"] = "error"
    result["warnings"] = list(dict.fromkeys(warnings or []))
    result["error"] = {"type": error_type, "message": message}
    return result


def _document_profile(repository: DocumentRepository, doc_id: str) -> dict[str, Any]:
    page_result = count_pages(repository, doc_id)
    block_result = count_blocks(repository, doc_id)
    table_result = count_tables(repository, doc_id)
    image_result = count_images(repository, doc_id)
    return {
        "page_count": page_result.get("page_count") if page_result.get("status") == "success" else None,
        "block_count": block_result.get("block_count") if block_result.get("status") == "success" else None,
        "table_count": table_result.get("table_count") if table_result.get("status") == "success" else None,
        "image_count": image_result.get("image_count") if image_result.get("status") == "success" else None,
        "has_ocr": bool((block_result.get("block_count") or 0) > 0),
        "has_tables": bool((table_result.get("table_count") or 0) > 0),
        "has_images": bool((image_result.get("image_count") or 0) > 0),
    }


def _find_document_by_sha(repository: DocumentRepository, sha256: str) -> dict[str, Any] | None:
    for item in repository.list_documents():
        doc = repository.get_document(str(item.get("doc_id") or ""))
        if doc and doc.get("sha256") == sha256:
            return doc
    return None


def _resolve_file_doc_id(
    *,
    repository: DocumentRepository,
    file_path: Path,
) -> tuple[str | None, list[str], dict[str, Any] | None]:
    digest = sha256_file(file_path)
    document = _find_document_by_sha(repository, digest)
    if document is None:
        return None, [], None
    return str(document["doc_id"]), ["file_reused_existing_doc_id"], document


def _file_source(*, file_path: Path, db_path: Path) -> dict[str, Any]:
    return {
        "type": "file",
        "file": str(file_path),
        "file_path": str(file_path),
        "db_path": str(db_path),
        "was_ingested": False,
        "reused_existing": False,
    }


def _looks_like_local_absolute_path(value: str) -> bool:
    return (
        (len(value) >= 3 and value[1] == ":" and value[2] in {"\\", "/"})
        or value.startswith("\\\\")
        or (value.startswith("/") and "://" not in value)
    )


def _sanitize_manifest_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_manifest_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_manifest_paths(item) for item in value]
    if isinstance(value, str) and _looks_like_local_absolute_path(value):
        return Path(value).name
    return value


def _copy_mineru_output_to_document_cache(
    *,
    file_path: Path,
    document_root: Path,
    mineru_output_dir: Path,
) -> dict[str, str] | None:
    if not mineru_output_dir.is_dir():
        return {
            "type": "file_ingestion_failed",
            "message": f"MinerU output directory not found: {mineru_output_dir}",
        }

    try:
        preview_record = DocumentRegistry(document_root).register(file_path)
    except Exception as exc:
        return {
            "type": "document_registration_failed",
            "message": str(exc),
        }
    target = Path(preview_record.document_dir) / "mineru"
    if target.exists():
        if any(
            path.name.endswith("content_list.json") and not path.name.endswith("_content_list_v2.json")
            for path in target.rglob("*.json")
        ):
            return None
        return {
            "type": "file_ingestion_failed",
            "message": f"Document cache MinerU directory exists but has no content list: {target}",
        }

    shutil.copytree(mineru_output_dir, target)
    manifest = mineru_output_dir.parent / "source_manifest.json"
    if manifest.exists():
        manifest_payload = json.loads(manifest.read_text(encoding="utf-8-sig"))
        manifest_payload = _sanitize_manifest_paths(manifest_payload)
        manifest_payload["source_file"] = f"source/original{file_path.suffix.lower()}"
        (Path(preview_record.document_dir) / "mineru_source_manifest.json").write_text(
            json.dumps(manifest_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return None


def _resolve_optional_mineru_env_file(value: str | None) -> Path | None:
    if value:
        return _project_path(value)
    default_path = ROOT / DEFAULT_MINERU_ENV_FILE
    return default_path if default_path.is_file() else None


def _cached_mineru_output_ready(path: Path, *, parse_options: dict[str, Any] | None = None) -> bool:
    try:
        find_content_list(path)
    except Exception:
        return False
    if parse_options is None:
        return True
    manifest_path = path / "mineru_api_manifest.json"
    if not manifest_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    existing_options = manifest.get("parse_options")
    if not isinstance(existing_options, dict):
        return False
    return {key: existing_options.get(key) for key in parse_options} == parse_options


def _load_mineru_api_manifest(path: Path) -> dict[str, Any]:
    manifest_path = path / "mineru_api_manifest.json"
    if not manifest_path.is_file():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _mineru_api_manifest_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    inventory = manifest.get("output_inventory") if isinstance(manifest.get("output_inventory"), dict) else {}
    category_counts = inventory.get("category_counts") if isinstance(inventory.get("category_counts"), dict) else {}
    return {
        "status": manifest.get("status"),
        "batch_id_present": bool(manifest.get("batch_id")),
        "source_sha256_present": bool(manifest.get("source_sha256")),
        "result_zip_sha256_present": bool(manifest.get("result_zip_sha256")),
        "api_attempt_count": manifest.get("api_attempt_count"),
        "retry_error_count": len(manifest.get("retry_errors") or []),
        "output_file_count": inventory.get("file_count"),
        "output_total_size": inventory.get("total_size"),
        "output_inventory_truncated": inventory.get("truncated"),
        "output_category_counts": category_counts,
        "ordinary_content_list_count": category_counts.get("ordinary_content_list", 0),
        "content_list_v2_count": category_counts.get("content_list_v2", 0),
        "markdown_file_count": category_counts.get("markdown", 0),
        "layout_json_count": category_counts.get("layout_json", 0),
        "image_resource_count": category_counts.get("image_resource", 0),
        "table_image_resource_count": category_counts.get("table_image_resource", 0),
        "table_html_artifact_count": category_counts.get("table_html_artifact", 0),
    }


def _run_mineru_api_to_document_cache(
    *,
    file_path: Path,
    document_root: Path,
    env_file: Path | None,
    data_id: str | None,
    model_version: str,
    language: str,
    is_ocr: bool,
    enable_table: bool,
    enable_formula: bool,
    timeout_seconds: float,
    poll_interval_seconds: float,
    api_max_attempts: int,
    api_retry_delay_seconds: float,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    preview_record = DocumentRegistry(document_root).register(file_path)
    target = Path(preview_record.document_dir) / "mineru"
    parse_options = {
        "model_version": model_version,
        "is_ocr": is_ocr,
        "enable_table": enable_table,
        "enable_formula": enable_formula,
        "language": language,
    }
    if target.exists():
        if _cached_mineru_output_ready(target, parse_options=parse_options):
            manifest = refresh_mineru_api_manifest_inventory(target) or _load_mineru_api_manifest(target)
            return None, {
                "status": "success",
                "api_status": "cached_existing_output",
                "output_dir": str(target),
                "manifest": _mineru_api_manifest_summary(manifest),
            }
        shutil.rmtree(target)

    client = MinerUApiClient(env_file=env_file)
    manifest = client.run(
        file_path=file_path,
        data_id=data_id or file_path.stem,
        output_dir=target,
        model_version=model_version,
        is_ocr=is_ocr,
        enable_table=enable_table,
        enable_formula=enable_formula,
        language=language,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        api_max_attempts=api_max_attempts,
        api_retry_delay_seconds=api_retry_delay_seconds,
    )
    return None, {
        "status": "success",
        "api_status": "submitted",
        "output_dir": str(target),
        "manifest": _mineru_api_manifest_summary(manifest),
    }


def _parser_backend_for_file(
    file_path: Path,
    *,
    parser_name: str,
    mineru_output_dir: Path | None,
) -> tuple[Any | None, dict[str, str] | None]:
    extension = file_path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        return None, {
            "type": "unsupported_file_type",
            "message": f"Unsupported file type for ingestion: {extension or '<none>'}",
        }
    if parser_name == "text" or (parser_name == "auto" and extension == ".txt"):
        if extension != ".txt":
            return None, {
                "type": "parser_backend_unavailable",
                "message": f"Text parser only supports .txt files, not {extension}.",
            }
        return TextParserBackend(), None
    if parser_name in {"mineru_existing", "mineru_api"} or (
        parser_name == "auto" and extension in {".pdf", ".png", ".jpg", ".jpeg"} and mineru_output_dir is not None
    ):
        backend_name = "mineru_api" if parser_name == "mineru_api" else "mineru_existing"
        return (
            MinerUParserBackend(
                mode="parse_existing",
                backend_name=backend_name,
            ),
            None,
        )
    return None, {
        "type": "parser_backend_unavailable",
        "message": (
            f"No CLI parser backend is configured for {extension} files. "
            "Use --parser mineru_existing with --mineru-output-dir for existing MinerU output, "
            "--parser mineru_api --live-api for MinerU API parsing, "
            "or use a UTF-8 .txt file."
        ),
    }


def _ingest_file(
    *,
    repository: DocumentRepository,
    file_path: Path,
    document_root: Path,
    parser_name: str,
    mineru_output_dir: Path | None,
    live_api: bool,
    mineru_env_file: Path | None,
    mineru_model_version: str,
    mineru_data_id: str | None,
    mineru_language: str,
    mineru_ocr: bool,
    mineru_enable_table: bool,
    mineru_enable_formula: bool,
    mineru_api_timeout_seconds: float,
    mineru_api_poll_interval_seconds: float,
    mineru_api_max_attempts: int,
    mineru_api_retry_delay_seconds: float,
    force_parse: bool = False,
) -> tuple[str | None, dict[str, Any] | None, dict[str, Any]]:
    parser_backend, parser_error = _parser_backend_for_file(
        file_path,
        parser_name=parser_name,
        mineru_output_dir=mineru_output_dir,
    )
    if parser_error is not None:
        return None, parser_error, {"status": "failed", "error": parser_error}
    assert parser_backend is not None
    mineru_api_summary: dict[str, Any] = {}
    if isinstance(parser_backend, MinerUParserBackend) and parser_backend.mode == "parse_existing" and mineru_output_dir is not None:
        copy_error = _copy_mineru_output_to_document_cache(
            file_path=file_path,
            document_root=document_root,
            mineru_output_dir=mineru_output_dir,
        )
        if copy_error is not None:
            return None, copy_error, {"status": "failed", "error": copy_error}
    elif parser_name == "mineru_api":
        if not live_api:
            error = {
                "type": "mineru_api_requires_live_api",
                "message": "--parser mineru_api requires --live-api.",
            }
            return None, error, {"status": "failed", "error": error}
        try:
            api_error, mineru_api_summary = _run_mineru_api_to_document_cache(
                file_path=file_path,
                document_root=document_root,
                env_file=mineru_env_file,
                data_id=mineru_data_id,
                model_version=mineru_model_version,
                language=mineru_language,
                is_ocr=mineru_ocr,
                enable_table=mineru_enable_table,
                enable_formula=mineru_enable_formula,
                timeout_seconds=mineru_api_timeout_seconds,
                poll_interval_seconds=mineru_api_poll_interval_seconds,
                api_max_attempts=mineru_api_max_attempts,
                api_retry_delay_seconds=mineru_api_retry_delay_seconds,
            )
        except Exception as exc:
            error = {"type": "file_ingestion_failed", "message": str(exc)}
            return None, error, {"status": "failed", "error": error}
        if api_error is not None:
            return None, api_error, {"status": "failed", "error": api_error}
    service = DocumentIngestionService(document_root=document_root, repository=repository)
    try:
        ingestion_result = service.ingest(file_path=file_path, parser_backend=parser_backend, force_parse=force_parse)
    except ValueError as exc:
        message = str(exc)
        error_type = "unsupported_file_type" if "unsupported document type" in message else "file_ingestion_failed"
        error = {"type": error_type, "message": message}
        return None, error, {"status": "failed", "error": error}
    except Exception as exc:
        error = {"type": "file_ingestion_failed", "message": str(exc)}
        return None, error, {"status": "failed", "error": error}
    payload = ingestion_result.to_dict()
    payload["status"] = "success"
    if mineru_api_summary:
        payload["mineru_api"] = mineru_api_summary
    return ingestion_result.document.doc_id, None, payload


def _list_documents(*, db_path: Path, limit: int) -> dict[str, Any]:
    run_id = _now_run_id()
    if not db_path.is_file():
        return _error_result(
            mode="list_documents",
            run_id=run_id,
            error_type="db_path_not_found",
            message=f"SQLite database not found: {db_path}",
            source={"type": "db", "db_path": str(db_path)},
        )

    conn = connect(db_path)
    try:
        repository = DocumentRepository(conn)
        documents = []
        for item in repository.list_documents()[: max(0, limit)]:
            doc = repository.get_document(str(item.get("doc_id") or "")) or {}
            documents.append(
                {
                    "doc_id": item.get("doc_id") or "",
                    "original_name": item.get("original_name") or "",
                    "file_path": item.get("file_path") or "",
                    "page_count": doc.get("page_count"),
                    "parse_status": item.get("parse_status") or "",
                    "index_status": item.get("index_status") or "",
                    "created_at": item.get("created_at") or "",
                    "updated_at": item.get("updated_at") or "",
                }
            )
    finally:
        conn.close()

    result = _base_result(mode="list_documents", run_id=run_id, source={"type": "db", "db_path": str(db_path)})
    result["documents"] = documents
    result["document_count"] = len(documents)
    result["limit"] = limit
    return result


def _parse_page(question: str) -> int | None:
    match = re.search(r"\b(?:page|p\.)\s*(\d+)\b", question, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _run_document_statistics(
    *,
    repository: DocumentRepository,
    doc_id: str,
    router_plan: dict[str, Any],
) -> dict[str, Any]:
    handlers = {
        "count_pages": count_pages,
        "count_blocks": count_blocks,
        "count_tables": count_tables,
        "count_images": count_images,
    }
    tool_results: list[dict[str, Any]] = []
    for tool_name in router_plan.get("selected_tools") or []:
        handler = handlers.get(str(tool_name))
        if handler is not None:
            tool_results.append(handler(repository, doc_id))

    failed = [item for item in tool_results if item.get("status") != "success"]
    if failed:
        first = failed[0]
        error = first.get("error") or {}
        return {
            "status": "error",
            "answer": "",
            "tools_used": [item.get("tool") for item in tool_results if item.get("tool")],
            "structured_result": {"tool_results": tool_results},
            "error": {
                "type": str(error.get("code") or "document_statistics_failed"),
                "message": str(error.get("message") or "Document statistics tool failed."),
            },
        }

    parts = []
    for item in tool_results:
        if item.get("tool") == "count_pages":
            parts.append(f"{item.get('page_count')} pages")
        elif item.get("tool") == "count_blocks":
            parts.append(f"{item.get('block_count')} blocks")
        elif item.get("tool") == "count_tables":
            parts.append(f"{item.get('table_count')} tables")
        elif item.get("tool") == "count_images":
            parts.append(f"{item.get('image_count')} image or figure regions")
    return {
        "status": "success",
        "answer": "The document contains " + ", ".join(parts) + "." if parts else "",
        "tools_used": [str(item.get("tool")) for item in tool_results],
        "structured_result": {"tool_results": tool_results},
        "error": {},
    }


def _run_page_lookup(
    *,
    repository: DocumentRepository,
    doc_id: str,
    question: str,
    router_plan: dict[str, Any],
) -> dict[str, Any]:
    selected = set(str(tool) for tool in router_plan.get("selected_tools") or [])
    if "list_pages" in selected:
        tool_result = list_pages(repository, doc_id)
        if tool_result.get("status") != "success":
            return _tool_error(tool_result, "page_lookup_failed")
        return {
            "status": "success",
            "answer": f"The document has {tool_result.get('page_count')} pages.",
            "citations": [
                {"page": page.get("page"), "block_id": page.get("page_block_id"), "text_preview": page.get("text_preview")}
                for page in tool_result.get("pages", [])
            ],
            "tools_used": ["list_pages"],
            "structured_result": tool_result,
            "error": {},
        }

    page = _parse_page(question)
    if page is None:
        return {
            "status": "error",
            "answer": "",
            "citations": [],
            "tools_used": ["get_page_text"],
            "structured_result": {},
            "error": {"type": "page_number_required", "message": "A 1-based page number is required for page lookup."},
        }
    tool_result = get_page_text(repository, doc_id, page)
    if tool_result.get("status") != "success":
        return _tool_error(tool_result, "page_lookup_failed")
    citation = {
        "page": page,
        "block_id": tool_result.get("page_block_id") or (tool_result.get("block_ids") or [""])[0],
        "text_preview": tool_result.get("text_preview") or "",
    }
    return {
        "status": "success",
        "answer": str(tool_result.get("text") or ""),
        "citations": [citation],
        "tools_used": ["get_page_text"],
        "structured_result": tool_result,
        "error": {},
    }


def _tool_error(tool_result: dict[str, Any], default_type: str) -> dict[str, Any]:
    error = tool_result.get("error") or {}
    return {
        "status": "error",
        "answer": "",
        "citations": [],
        "tools_used": [str(tool_result.get("tool") or "")],
        "structured_result": tool_result,
        "error": {
            "type": str(error.get("code") or default_type),
            "message": str(error.get("message") or "Tool execution failed."),
        },
    }


def _page_metadata_consistency(
    repository: DocumentRepository,
    doc_id: str,
    document: dict[str, Any],
    citations: list[dict[str, Any]],
) -> dict[str, Any]:
    page_count = document.get("page_count")
    try:
        page_count_int = int(page_count)
    except (TypeError, ValueError):
        page_count_int = None

    blocks = repository.load_evidence_blocks(doc_id, include_page_blocks=True)
    page_block_count = sum(1 for block in blocks if block.block_type == "page")
    evidence_pages = [
        int(block.location.page)
        for block in blocks
        if block.block_type != "page" and block.location.page is not None
    ]
    citation_pages: list[int] = []
    for citation in citations:
        try:
            citation_pages.append(int(citation.get("page")))
        except (TypeError, ValueError):
            continue

    max_evidence_page = max(evidence_pages) if evidence_pages else None
    max_citation_page = max(citation_pages) if citation_pages else None
    inconsistent = False
    if page_count_int is not None and page_count_int > 0:
        if page_block_count and page_block_count != page_count_int:
            inconsistent = True
        if max_evidence_page is not None and max_evidence_page > page_count_int:
            inconsistent = True
        if max_citation_page is not None and max_citation_page > page_count_int:
            inconsistent = True
    return {
        "documents_page_count": page_count_int,
        "page_documents_count": page_block_count,
        "max_evidence_page": max_evidence_page,
        "max_citation_page": max_citation_page,
        "status": "warning" if inconsistent else "ok",
        "warning": "page_metadata_inconsistent" if inconsistent else "",
    }


def _page_metadata_warnings(metadata_consistency: dict[str, Any]) -> list[str]:
    warning = str(metadata_consistency.get("warning") or "")
    return [warning] if warning else []


def _normalize_citations(
    repository: DocumentRepository,
    doc_id: str,
    citations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    blocks_by_id = {
        block.block_id: block
        for block in repository.load_evidence_blocks(doc_id, include_page_blocks=True)
    }
    normalized: list[dict[str, Any]] = []
    for raw in citations:
        if not isinstance(raw, dict):
            continue
        citation = dict(raw)
        block_id = str(citation.get("block_id") or "")
        block = blocks_by_id.get(block_id)
        citation["doc_id"] = str(citation.get("doc_id") or (block.doc_id if block is not None else doc_id))
        if block is not None:
            if citation.get("page") in {None, ""}:
                citation["page"] = _citation_block_page(block)
            citation["block_type"] = str(citation.get("block_type") or block.block_type)
            if not citation.get("text_preview"):
                citation["text_preview"] = _citation_preview(block)
            caption = _citation_caption(block)
            if caption and block.block_type == "table" and not citation.get("table_caption"):
                citation["table_caption"] = caption
            if caption and block.block_type in {"image", "figure"} and not citation.get("image_caption"):
                citation["image_caption"] = caption
            if block.image_path and not citation.get("image_path"):
                citation["image_path"] = block.image_path
        else:
            citation["block_type"] = str(citation.get("block_type") or "")
            citation["text_preview"] = str(citation.get("text_preview") or citation.get("preview") or "")
        normalized.append(citation)
    return normalized


def _evidence_used_from_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for citation in citations:
        item = {
            "doc_id": citation.get("doc_id") or "",
            "page": citation.get("page"),
            "block_id": citation.get("block_id") or "",
            "block_type": citation.get("block_type") or "",
            "text_preview": citation.get("text_preview") or "",
        }
        for optional_key in ("table_caption", "image_caption", "image_path"):
            if citation.get(optional_key):
                item[optional_key] = citation[optional_key]
        evidence.append(item)
    return evidence


def _reasoning_summary_for_tool(tool_result: dict[str, Any], task_type: str) -> str:
    explicit = str(tool_result.get("reasoning_summary") or "").strip()
    if explicit:
        return explicit
    if tool_result.get("status") == "error":
        error = tool_result.get("error") if isinstance(tool_result.get("error"), dict) else {}
        return str(error.get("message") or "The request could not be completed with the available document evidence.")
    mapping = {
        "document_statistics": "Computed deterministic document statistics from the registered document metadata and evidence blocks.",
        "page_lookup": "Returned the requested page text and cited the page evidence block.",
        "local_fact_qa": "Answered from retrieved document evidence blocks using the configured AnswerPolicy.",
        "document_summary": "Built an extractive document summary from persisted evidence blocks and cited supporting blocks.",
        "structured_extraction": "Scanned persisted evidence blocks for the requested structured items and cited matching blocks.",
        "table_lookup_or_calculation": "Selected table evidence and returned a traceable lookup or simple calculation result.",
    }
    return mapping.get(task_type, "")


def _citation_block_page(block: Any) -> int | None:
    page_id = getattr(block, "page_id", None)
    if page_id is not None:
        return int(page_id)
    location = getattr(block, "location", None)
    page = getattr(location, "page", None)
    return int(page) if page is not None else None


def _citation_preview(block: Any, limit: int = 220) -> str:
    text = str(getattr(block, "retrieval_text", "") or getattr(block, "text", "") or getattr(block, "table_html", "") or "")
    return " ".join(text.split())[:limit]


def _citation_caption(block: Any) -> str:
    metadata = getattr(block, "metadata", {}) or {}
    for key in ("table_caption", "caption", "image_caption", "chart_caption", "title"):
        value = metadata.get(key)
        if not value:
            continue
        if isinstance(value, list):
            return " ".join(str(item) for item in value if str(item).strip())
        return " ".join(str(value).split())
    return ""


def _safe_model_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "model"


def _read_dense_index_metadata(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _dense_index_metadata_matches(metadata_path: Path, model_id: str) -> tuple[bool, dict[str, Any]]:
    metadata = _read_dense_index_metadata(metadata_path)
    return str(metadata.get("model_id") or "") == model_id, metadata


def _build_dense_index_for_blocks(
    *,
    repository: DocumentRepository,
    doc_id: str,
    index_dir: Path,
    blocks: list[Any],
    dense_encoder: Any,
) -> tuple[DenseIndex, dict[str, Any]]:
    embeddings = dense_encoder.encode_documents([block.retrieval_text for block in blocks])
    dense_index = DenseIndex.build(blocks=blocks, embeddings=embeddings, model_id=dense_encoder.model_id)
    metadata = dense_index.save(index_dir)
    model_index_metadata = index_dir / f"index_metadata_{_safe_model_id(dense_encoder.model_id)}.json"
    model_index_metadata.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    repository_metadata_save_error: dict[str, str] | None = None
    try:
        repository.save_index_metadata(
            doc_id=doc_id,
            index_type="dense",
            model_id=str(metadata.get("model_id") or ""),
            artifact_path=str(index_dir),
            metadata=metadata,
        )
    except Exception as exc:
        repository_metadata_save_error = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
    dense_metadata: dict[str, Any] = {
        "index_built": True,
        "index_metadata_path": str(model_index_metadata),
    }
    if repository_metadata_save_error is not None:
        dense_metadata["repository_metadata_save_error"] = repository_metadata_save_error
    return dense_index, dense_metadata


def _build_indexed_retriever(
    *,
    repository: DocumentRepository,
    doc_id: str,
    document_root: Path,
    mode: str,
    dense_backend: str,
    dense_model_path: str,
    dense_device: str,
    dense_fp16: bool,
    build_dense_index_if_missing: bool,
    reranker_backend: str,
    reranker_model_path: str,
    reranker_device: str,
    reranker_fp16: bool,
    query_plan: Any,
) -> tuple[IndexedDocumentRetriever, dict[str, Any]]:
    blocks = repository.load_evidence_blocks(doc_id)
    dense_encoder = None
    dense_index = None
    dense_metadata: dict[str, Any] = {}
    if mode in {"dense", "hybrid", "hybrid_rerank"}:
        if dense_backend == "hash":
            dense_encoder = HashDenseEncoder()
        else:
            dense_encoder = DenseEncoder(
                DenseEncoderConfig(
                    model_path=dense_model_path,
                    device=dense_device,
                    use_fp16=dense_fp16,
                )
            )
        index_dir = document_root / doc_id
        model_index_metadata = index_dir / f"index_metadata_{_safe_model_id(dense_encoder.model_id)}.json"
        index_metadata = model_index_metadata
        legacy_index_metadata = index_dir / "index_metadata.json"
        if not index_metadata.exists() and legacy_index_metadata.exists() and dense_backend == "bge":
            legacy_matches, legacy_metadata = _dense_index_metadata_matches(
                legacy_index_metadata,
                dense_encoder.model_id,
            )
            if legacy_matches:
                index_metadata = legacy_index_metadata
                dense_metadata["legacy_index_reused"] = True
            else:
                dense_metadata.update(
                    {
                        "legacy_index_reused": False,
                        "stale_legacy_index_metadata_path": str(legacy_index_metadata),
                        "stale_legacy_index_model_id": str(legacy_metadata.get("model_id") or ""),
                    }
                )
        if not index_metadata.exists() or (
            index_metadata == legacy_index_metadata and dense_metadata.get("legacy_index_reused") is False
        ):
            if not build_dense_index_if_missing:
                raise RuntimeError(
                    f"dense index is missing for doc_id={doc_id}: {index_metadata}. "
                    "Pass --build-dense-index-if-missing for a smoke run, or ingest/build the index first."
                )
            dense_index, built_metadata = _build_dense_index_for_blocks(
                repository=repository,
                doc_id=doc_id,
                index_dir=index_dir,
                blocks=blocks,
                dense_encoder=dense_encoder,
            )
            dense_metadata.update(built_metadata)
        else:
            dense_index = DenseIndex.load(index_dir=index_dir, blocks=blocks, metadata_path=index_metadata)
            if dense_index.model_id != dense_encoder.model_id:
                if not build_dense_index_if_missing:
                    raise RuntimeError(
                        "dense index model_id does not match requested encoder: "
                        f"index_model_id={dense_index.model_id}, requested_model_id={dense_encoder.model_id}"
                    )
                dense_metadata.update(
                    {
                        "stale_index_metadata_path": str(index_metadata),
                        "stale_index_model_id": dense_index.model_id,
                    }
                )
                dense_index, built_metadata = _build_dense_index_for_blocks(
                    repository=repository,
                    doc_id=doc_id,
                    index_dir=index_dir,
                    blocks=blocks,
                    dense_encoder=dense_encoder,
                )
                dense_metadata.update(built_metadata)
            else:
                dense_metadata["index_built"] = False
                dense_metadata["index_metadata_path"] = str(index_metadata)
        dense_metadata.update(
            {
                "backend": dense_backend,
                "model_id": dense_encoder.model_id,
                "device": dense_device,
                "fp16": bool(dense_fp16),
            }
        )

    reranker = None
    reranker_metadata: dict[str, Any] = {}
    if mode == "hybrid_rerank":
        if reranker_backend == "keyword":
            reranker = KeywordOverlapReranker()
            reranker_metadata = {"backend": "keyword", "model_path": ""}
        else:
            reranker = CrossEncoderReranker(
                CrossEncoderRerankerConfig(
                    model_path=reranker_model_path,
                    device=reranker_device,
                    use_fp16=reranker_fp16,
                )
            )
            reranker_metadata = {
                "backend": "cross_encoder",
                "model_path": reranker_model_path,
                "device": reranker_device,
                "fp16": bool(reranker_fp16),
            }

    retriever = IndexedDocumentRetriever(
        blocks,
        mode=mode,
        dense_encoder=dense_encoder,
        dense_index=dense_index,
        reranker=reranker,
        query_plan=query_plan,
    )
    metadata = {
        "mode": mode,
        "block_count": len(blocks),
        "uses_dense": mode in {"dense", "hybrid", "hybrid_rerank"},
        "uses_reranker": mode == "hybrid_rerank",
        "dense": dense_metadata,
        "reranker": reranker_metadata,
    }
    return retriever, metadata


def _run_local_fact_qa(
    *,
    repository: DocumentRepository,
    trace_repository: TraceRepository,
    db_path: Path,
    document_root: Path,
    doc_id: str,
    question: str,
    router_plan: dict[str, Any],
    dry_run: bool,
    run_id: str,
    enable_query_planning: bool = False,
    query_planner_mode: str = "hybrid",
    document_profile: dict[str, Any] | None = None,
    query_planner_env_file: Path | None = None,
    query_planner_model: str | None = None,
    retriever_mode: str = "bm25",
    dense_backend: str = "bge",
    dense_model_path: str = DEFAULT_BGE_MODEL_PATH,
    dense_device: str = "cpu",
    dense_fp16: bool = False,
    build_dense_index_if_missing: bool = False,
    reranker_backend: str = "cross_encoder",
    reranker_model_path: str = DEFAULT_RERANKER_MODEL_PATH,
    reranker_device: str = "cpu",
    reranker_fp16: bool = False,
    answer_policy: Any,
) -> dict[str, Any]:
    options: dict[str, Any] = {"dry_run": dry_run, "qid": run_id}
    if not dry_run:
        options["trace_path"] = str(db_path)
    query_planner_payload: dict[str, Any] = {}
    retriever = None
    retriever_payload: dict[str, Any] = {
        "mode": "legacy_bm25",
        "requested_mode": retriever_mode,
        "uses_dense": False,
        "uses_reranker": False,
        "initialization_status": "not_started",
    }
    query_planner_warnings: list[str] = []
    query_plan = None
    if enable_query_planning:
        query_plan = plan_queries(
            question=question,
            task_type=str(router_plan.get("task_type") or "local_fact_qa"),
            document_profile=document_profile or {},
            mode=query_planner_mode,
            env_file=query_planner_env_file,
            model_override=query_planner_model,
        )
        query_planner_payload = {"enabled": True, **query_plan.to_dict()}
        query_planner_warnings = ["query_planning_enabled", *query_plan.warnings]
    if not dry_run and (enable_query_planning or retriever_mode != "bm25"):
        retriever_payload = {
            "mode": retriever_mode,
            "requested_mode": retriever_mode,
            "uses_dense": retriever_mode in {"dense", "hybrid", "hybrid_rerank"},
            "uses_reranker": retriever_mode == "hybrid_rerank",
            "initialization_status": "started",
        }
        try:
            retriever, retriever_payload = _build_indexed_retriever(
                repository=repository,
                doc_id=doc_id,
                document_root=document_root,
                mode=retriever_mode,
                dense_backend=dense_backend,
                dense_model_path=dense_model_path,
                dense_device=dense_device,
                dense_fp16=dense_fp16,
                build_dense_index_if_missing=build_dense_index_if_missing,
                reranker_backend=reranker_backend,
                reranker_model_path=reranker_model_path,
                reranker_device=reranker_device,
                reranker_fp16=reranker_fp16,
                query_plan=query_plan,
            )
            retriever_payload["requested_mode"] = retriever_mode
            retriever_payload["initialization_status"] = "success"
        except Exception as exc:
            retriever_error = {"type": type(exc).__name__, "message": str(exc)}
            failed_payload = {
                **retriever_payload,
                "requested_mode": retriever_mode,
                "initialization_status": "failed",
                "initialization_error": retriever_error,
            }
            answer_policy_payload = _answer_policy_metadata(answer_policy)
            # The policy is configured, but it has not run if retriever setup fails.
            answer_policy_payload["used_qwen_answer_policy"] = False
            answer_policy_payload["used_external_answer_api"] = False
            payload = {
                "status": "error",
                "answer": "",
                "citations": [],
                "supporting_evidence_ids": [],
                "tools_used": ["local_fact_qa"],
                "tool_run_id": "",
                "tool_trace_path": "",
                "trace_run_id": "",
                "retrieval_candidate_count": 0,
                "citation_count": 0,
                "structured_result": {},
                "workflow_trace": [],
                "retriever": failed_payload,
                "retriever_mode": retriever_mode,
                "warnings": list(dict.fromkeys(query_planner_warnings + ["retriever_initialization_failed"])),
                "error": {"type": "retriever_initialization_failed", "message": str(exc), "cause": retriever_error},
                **answer_policy_payload,
            }
            if query_planner_payload:
                payload["query_planner"] = query_planner_payload
                payload["query_planner_execution"] = _query_planner_execution(query_planner_payload)
            return payload
    elif dry_run:
        retriever_payload = {
            "mode": retriever_mode if enable_query_planning else "dry_run_input_order",
            "requested_mode": retriever_mode,
            "uses_dense": False,
            "uses_reranker": False,
            "initialization_status": "dry_run",
        }
    result = local_fact_qa(
        {"doc_id": doc_id, "question": question, "router_plan": router_plan, "options": options},
        document_repository=repository,
        trace_repository=None if dry_run else trace_repository,
        retriever=retriever,
        answer_policy=answer_policy,
    )
    citations = result.get("citations") or []
    supporting_evidence_ids = result.get("supporting_evidence_ids") or []
    payload = {
        "status": "success" if result.get("status") == "success" else "error",
        "answer": result.get("answer") or "",
        "citations": citations,
        "supporting_evidence_ids": supporting_evidence_ids,
        "tools_used": result.get("tools_used") or ["local_fact_qa"],
        "tool_run_id": result.get("run_id") or "",
        "tool_trace_path": result.get("trace_path") or "",
        "trace_run_id": result.get("run_id") or "",
        "retrieval_candidate_count": max(len(supporting_evidence_ids), len(citations)),
        "citation_count": len(citations),
        "structured_result": result,
        "workflow_trace": result.get("workflow_trace") or [],
        "retriever": retriever_payload,
        "retriever_mode": retriever_payload.get("mode") or "",
        "warnings": list(dict.fromkeys(query_planner_warnings + (result.get("warnings") or []))),
        "error": result.get("error") or {},
        **_answer_policy_metadata(answer_policy),
    }
    if query_planner_payload:
        payload["query_planner"] = query_planner_payload
    return payload


def _run_document_summary(
    *,
    repository: DocumentRepository,
    doc_id: str,
    question: str,
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        return {
            "status": "success",
            "answer": "",
            "citations": [],
            "supporting_evidence_ids": [],
            "tools_used": ["document_summary"],
            "structured_result": {"task_type": "document_summary", "status": "dry_run", "summary": None},
            "warnings": ["dry_run_no_answer_generated"],
            "error": {},
        }

    result = summarize_document(repository=repository, doc_id=doc_id, question=question)
    error = result.get("error") if isinstance(result.get("error"), dict) else {}
    status = "success" if result.get("status") == "completed" else str(result.get("status") or "error")
    return {
        "status": status,
        "answer": result.get("answer") or "",
        "citations": result.get("citations") or [],
        "supporting_evidence_ids": result.get("supporting_evidence_ids") or [],
        "tools_used": ["document_summary"],
        "structured_result": result,
        "summary": result.get("summary"),
        "trace": result.get("trace") or {},
        "warnings": result.get("warnings") or [],
        "error": {
            "type": str(error.get("code") or ""),
            "message": str(error.get("message") or ""),
        }
        if error
        else {},
    }


def _run_structured_extraction(
    *,
    repository: DocumentRepository,
    doc_id: str,
    question: str,
    router_plan: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    selected_tools = [str(item) for item in router_plan.get("selected_tools") or ["structured_extract"]]
    if dry_run:
        return {
            "status": "success",
            "answer": "",
            "citations": [],
            "supporting_evidence_ids": [],
            "tools_used": selected_tools,
            "structured_result": {
                "task_type": "structured_extraction",
                "status": "dry_run",
                "selected_tools": selected_tools,
                "items": [],
            },
            "warnings": ["dry_run_no_answer_generated"],
            "error": {},
        }

    result = structured_extract(repository, doc_id, selected_tools=selected_tools, question=question)
    if result.get("status") != "success":
        return _tool_error(result, "structured_extraction_failed")

    item_count = int(result.get("item_count") or 0)
    counts = result.get("counts_by_type") if isinstance(result.get("counts_by_type"), dict) else {}
    count_text = ", ".join(f"{key}: {value}" for key, value in counts.items()) if counts else "no structured items"
    answer = f"Found {item_count} structured item(s): {count_text}."
    citations = result.get("citations") or []
    return {
        "status": "success",
        "answer": answer,
        "citations": citations,
        "supporting_evidence_ids": [str(item.get("block_id")) for item in result.get("items") or [] if item.get("block_id")],
        "tools_used": selected_tools,
        "structured_result": result,
        "warnings": result.get("warnings") or [],
        "error": {},
    }


def _run_table_lookup_or_calculation(
    *,
    repository: DocumentRepository,
    doc_id: str,
    question: str,
    router_plan: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    selected_tools = [str(item) for item in router_plan.get("selected_tools") or ["table_lookup"]]
    if dry_run:
        return {
            "status": "success",
            "answer": "",
            "reasoning_summary": "Dry run only; table lookup and calculation were not executed.",
            "evidence_used": [],
            "citations": [],
            "supporting_evidence_ids": [],
            "tools_used": selected_tools,
            "structured_result": {
                "task_type": "table_lookup_or_calculation",
                "status": "dry_run",
                "selected_tools": selected_tools,
            },
            "warnings": ["dry_run_no_answer_generated"],
            "error": {},
        }
    return table_lookup_or_calculation(
        repository,
        doc_id,
        question,
        selected_tools=selected_tools,
    )


def _unsupported_task(task_type: str) -> dict[str, Any]:
    mapping = {
        "table_lookup_or_calculation": (
            "table_lookup_not_implemented",
            "table_lookup and simple_calculation are not implemented in this CLI MVP.",
        ),
    }
    error_type, message = mapping.get(task_type, ("unsupported_task_type", f"Unsupported task type: {task_type}"))
    return {
        "status": "error",
        "answer": "",
        "citations": [],
        "supporting_evidence_ids": [],
        "tools_used": [],
        "structured_result": {},
        "warnings": [],
        "error": {"type": error_type, "message": message},
    }


def _dispatch_tool(
    *,
    repository: DocumentRepository,
    trace_repository: TraceRepository,
    db_path: Path,
    document_root: Path,
    doc_id: str,
    question: str,
    router_plan: dict[str, Any],
    dry_run: bool,
    run_id: str,
    enable_query_planning: bool = False,
    query_planner_mode: str = "hybrid",
    document_profile: dict[str, Any] | None = None,
    query_planner_env_file: Path | None = None,
    query_planner_model: str | None = None,
    retriever_mode: str = "bm25",
    dense_backend: str = "bge",
    dense_model_path: str = DEFAULT_BGE_MODEL_PATH,
    dense_device: str = "cpu",
    dense_fp16: bool = False,
    build_dense_index_if_missing: bool = False,
    reranker_backend: str = "cross_encoder",
    reranker_model_path: str = DEFAULT_RERANKER_MODEL_PATH,
    reranker_device: str = "cpu",
    reranker_fp16: bool = False,
    answer_policy: Any,
) -> dict[str, Any]:
    task_type = str(router_plan.get("task_type") or "")
    if router_plan.get("status") == "error":
        error = router_plan.get("error") or {}
        return {
            "status": "error",
            "answer": "",
            "citations": [],
            "supporting_evidence_ids": [],
            "tools_used": [],
            "structured_result": {},
            "warnings": router_plan.get("warnings") or [],
            "error": {
                "type": str(error.get("code") or "router_error"),
                "message": str(error.get("message") or "Router returned an error."),
            },
        }
    if task_type == "document_statistics":
        return _run_document_statistics(repository=repository, doc_id=doc_id, router_plan=router_plan)
    if task_type == "page_lookup":
        return _run_page_lookup(repository=repository, doc_id=doc_id, question=question, router_plan=router_plan)
    if task_type == "local_fact_qa":
        return _run_local_fact_qa(
            repository=repository,
            trace_repository=trace_repository,
            db_path=db_path,
            document_root=document_root,
            doc_id=doc_id,
            question=question,
            router_plan=router_plan,
            dry_run=dry_run,
            run_id=run_id,
            enable_query_planning=enable_query_planning,
            query_planner_mode=query_planner_mode,
            document_profile=document_profile,
            query_planner_env_file=query_planner_env_file,
            query_planner_model=query_planner_model,
            retriever_mode=retriever_mode,
            dense_backend=dense_backend,
            dense_model_path=dense_model_path,
            dense_device=dense_device,
            dense_fp16=dense_fp16,
            build_dense_index_if_missing=build_dense_index_if_missing,
            reranker_backend=reranker_backend,
            reranker_model_path=reranker_model_path,
            reranker_device=reranker_device,
            reranker_fp16=reranker_fp16,
            answer_policy=answer_policy,
        )
    if task_type == "document_summary":
        return _run_document_summary(repository=repository, doc_id=doc_id, question=question, dry_run=dry_run)
    if task_type == "structured_extraction":
        return _run_structured_extraction(
            repository=repository,
            doc_id=doc_id,
            question=question,
            router_plan=router_plan,
            dry_run=dry_run,
        )
    if task_type == "table_lookup_or_calculation":
        return _run_table_lookup_or_calculation(
            repository=repository,
            doc_id=doc_id,
            question=question,
            router_plan=router_plan,
            dry_run=dry_run,
        )
    return _unsupported_task(task_type)


def _finalize_qa_result(
    *,
    result: dict[str, Any],
    output_dir: Path,
    router_plan: dict[str, Any],
    source_type: str,
    used_file_ingestion: bool,
) -> dict[str, Any]:
    run_id = str(result["run_id"])
    artifact_dir = output_dir / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    router_plan_path = artifact_dir / "router_plan.json"
    result_path = artifact_dir / "result.json"
    summary_path = artifact_dir / "summary.json"
    trace_path = artifact_dir / "trace.json"

    result["artifact_dir"] = str(artifact_dir)
    result["trace_path"] = str(trace_path)
    source = result.get("source") or {}

    summary = {
        "status": result["status"],
        "run_id": run_id,
        "doc_id": result.get("doc_id") or "",
        "source_type": source_type,
        "question": result.get("question") or "",
        "task_type": result.get("task_type") or "",
        "tools_used": result.get("tools_used") or [],
        "reasoning_summary": result.get("reasoning_summary") or "",
        "evidence_used": result.get("evidence_used") or [],
        "used_file_ingestion": bool(source.get("was_ingested", used_file_ingestion)),
        "reused_existing_document": bool(source.get("reused_existing", False)),
        "ingestion_status": source.get("ingestion_status") or "",
        "ingestion_error": source.get("ingestion_error") or {},
        "used_router": bool(router_plan),
        "full_model_path": bool(result.get("full_model_path", False)),
        "router_execution": result.get("router_execution") or {},
        "used_llm_router": bool(result.get("used_llm_router", False)),
        "llm_router_status": str(result.get("llm_router_status") or ""),
        "llm_router_skip_reason": str(result.get("llm_router_skip_reason") or ""),
        "used_query_planning": bool((result.get("query_planner") or {}).get("enabled")),
        "query_planner_mode": str((result.get("query_planner") or {}).get("mode") or ""),
        "query_planner_execution": result.get("query_planner_execution") or {},
        "used_llm_query_rewriter": bool(result.get("used_llm_query_rewriter", False)),
        "llm_query_rewriter_status": str(result.get("llm_query_rewriter_status") or ""),
        "query_count": len((result.get("query_planner") or {}).get("final_queries") or []),
        "answer_policy_mode": str(result.get("answer_policy_mode") or ""),
        "used_qwen_answer_policy": bool(result.get("used_qwen_answer_policy", False)),
        "used_external_answer_api": bool(result.get("used_external_answer_api", False)),
        "retriever": result.get("retriever") or {},
        "retriever_mode": str(result.get("retriever_mode") or ""),
        "used_dense_retrieval": bool((result.get("retriever") or {}).get("uses_dense")),
        "used_reranker": bool((result.get("retriever") or {}).get("uses_reranker")),
        "retrieval_candidate_count": int(result.get("retrieval_candidate_count") or 0),
        "citation_count": int(result.get("citation_count") or 0),
        "trace_run_id": str(result.get("trace_run_id") or ""),
        "used_mineru_api": bool(source.get("used_mineru_api", False)),
        "used_external_api": bool(source.get("used_mineru_api", False))
        or _router_used_external_api(router_plan)
        or _query_planner_used_external_api(result.get("query_planner") or {}),
        "used_vlm": False,
        "used_training": False,
        "used_full_e2e": bool(
            result.get("full_model_path")
            and result.get("status") == "success"
            and result.get("used_qwen_answer_policy")
            and (result.get("query_planner") or {}).get("enabled")
        ),
        "warnings": result.get("warnings") or [],
        "error": result.get("error") or {},
    }
    if result.get("summary") is not None:
        summary["summary"] = result.get("summary")
        summary["citations"] = result.get("citations") or []
        summary["trace"] = result.get("trace") or {}
    trace = {
        "run_id": run_id,
        "source": source,
        "router_plan": router_plan,
        "router_execution": result.get("router_execution") or {},
        "query_planner": result.get("query_planner") or {},
        "query_planner_execution": result.get("query_planner_execution") or {},
        "retriever": result.get("retriever") or {},
        "retriever_mode": str(result.get("retriever_mode") or ""),
        "workflow_trace": result.get("workflow_trace") or [],
        "answer_policy_mode": str(result.get("answer_policy_mode") or ""),
        "used_qwen_answer_policy": bool(result.get("used_qwen_answer_policy", False)),
        "used_llm_router": bool(result.get("used_llm_router", False)),
        "used_llm_query_rewriter": bool(result.get("used_llm_query_rewriter", False)),
        "trace_run_id": str(result.get("trace_run_id") or ""),
        "result_status": result.get("status"),
        "tools_used": result.get("tools_used") or [],
        "reasoning_summary": result.get("reasoning_summary") or "",
        "evidence_used": result.get("evidence_used") or [],
        "citations": result.get("citations") or [],
        "supporting_evidence_ids": result.get("supporting_evidence_ids") or [],
        "error": result.get("error") or {},
    }
    if result.get("trace") is not None:
        trace["document_summary"] = result.get("trace")

    _write_json(router_plan_path, router_plan)
    _write_json(summary_path, summary)
    _write_json(trace_path, trace)
    _write_json(result_path, result)
    return result


def _router_used_external_api(router_plan: dict[str, Any]) -> bool:
    if router_plan.get("router_source") == "llm_fallback":
        return True
    llm_router = router_plan.get("llm_router")
    if not isinstance(llm_router, dict):
        return False
    return str(llm_router.get("status") or "") in {"used", "api_error", "invalid_output", "validation_failed"}


def _query_planner_used_external_api(query_planner: dict[str, Any]) -> bool:
    if not query_planner:
        return False
    return str(query_planner.get("llm_status") or "") in {"used", "api_error", "invalid_output", "echoed_payload"}


def run_cli(args: argparse.Namespace) -> dict[str, Any]:
    db_path = _project_path(args.db_path)
    output_dir = _project_path(args.output_dir)
    document_root = _project_path(args.document_root)
    mineru_output_dir = _project_path(args.mineru_output_dir) if args.mineru_output_dir else None
    mineru_env_file = _resolve_optional_mineru_env_file(args.mineru_env_file)
    limit = max(0, int(args.limit))
    full_model_path = bool(getattr(args, "full_model_path", False))
    allow_llm_router = bool(args.allow_llm_router or full_model_path)
    enable_query_planning = bool(args.enable_query_planning or full_model_path)
    query_planner_mode = "hybrid" if full_model_path else str(args.query_planner_mode)
    router_llm_env_file = (
        _project_path(args.router_llm_env_file or DEFAULT_ROUTER_LLM_ENV_FILE)
        if args.router_llm_env_file or full_model_path
        else None
    )

    if args.list_documents:
        return _list_documents(db_path=db_path, limit=limit)

    run_id = _now_run_id()
    question = str(args.question or "").strip()
    source: dict[str, Any] = {}
    source_type = "doc_id"
    used_file_ingestion = False
    file_path: Path | None = None

    if args.file:
        source_type = "file"
        file_path = _project_path(args.file)
        source = _file_source(file_path=file_path, db_path=db_path)

    if not question:
        result = _error_result(
            mode="qa",
            run_id=run_id,
            error_type="question_required",
            message="--question is required unless --list-documents is used.",
        )
        return _finalize_qa_result(
            result=result,
            output_dir=output_dir,
            router_plan={},
            source_type="unknown",
            used_file_ingestion=False,
        )
    if not args.doc_id and not args.file:
        result = _error_result(
            mode="qa",
            run_id=run_id,
            error_type="document_required",
            message="At least one of --doc-id or --file is required.",
            question=question,
        )
        return _finalize_qa_result(
            result=result,
            output_dir=output_dir,
            router_plan={},
            source_type="unknown",
            used_file_ingestion=False,
        )
    if file_path is not None and not file_path.is_file():
        result = _error_result(
            mode="qa",
            run_id=run_id,
            error_type="file_not_found",
            message=f"Input file not found: {file_path}",
            question=question,
            source=source,
        )
        return _finalize_qa_result(
            result=result,
            output_dir=output_dir,
            router_plan={},
            source_type=source_type,
            used_file_ingestion=False,
        )
    if not db_path.is_file() and file_path is None:
        result = _error_result(
            mode="qa",
            run_id=run_id,
            error_type="db_path_not_found",
            message=f"SQLite database not found: {db_path}",
            question=question,
            source={"type": "db", "db_path": str(db_path)},
        )
        return _finalize_qa_result(
            result=result,
            output_dir=output_dir,
            router_plan={},
            source_type="unknown",
            used_file_ingestion=False,
        )

    conn = connect(db_path)
    try:
        repository = DocumentRepository(conn)
        trace_repository = TraceRepository(conn)
        warnings: list[str] = []
        doc_id = str(args.doc_id or "").strip()

        if file_path is not None:
            resolved_doc_id, file_warnings, _document = (
                (None, [], None)
                if bool(args.force_parse)
                else _resolve_file_doc_id(repository=repository, file_path=file_path)
            )
            warnings.extend(file_warnings)
            if resolved_doc_id:
                doc_id = resolved_doc_id
                source["was_ingested"] = False
                source["reused_existing"] = True
                source["resolved_doc_id"] = resolved_doc_id
                source["ingestion_status"] = "reused_existing"
            else:
                ingested_doc_id, ingestion_error, ingestion_summary = _ingest_file(
                    repository=repository,
                    file_path=file_path,
                    document_root=document_root,
                    parser_name=str(args.parser),
                    mineru_output_dir=mineru_output_dir,
                    live_api=bool(args.live_api),
                    mineru_env_file=mineru_env_file,
                    mineru_model_version=str(args.mineru_model_version),
                    mineru_data_id=str(args.mineru_data_id) if args.mineru_data_id else None,
                    mineru_language=str(args.mineru_language),
                    mineru_ocr=bool(args.mineru_ocr),
                    mineru_enable_table=not bool(args.disable_mineru_table),
                    mineru_enable_formula=not bool(args.disable_mineru_formula),
                    mineru_api_timeout_seconds=float(args.mineru_api_timeout_seconds),
                    mineru_api_poll_interval_seconds=float(args.mineru_api_poll_interval_seconds),
                    mineru_api_max_attempts=int(args.mineru_api_max_attempts),
                    mineru_api_retry_delay_seconds=float(args.mineru_api_retry_delay_seconds),
                    force_parse=bool(args.force_parse),
                )
                if ingestion_error is not None:
                    source["ingestion_status"] = "failed"
                    source["ingestion_error"] = ingestion_error
                    source["ingestion"] = ingestion_summary
                    warnings.append(str(ingestion_error["type"]))
                    result = _error_result(
                        mode="qa",
                        run_id=run_id,
                        error_type=str(ingestion_error["type"]),
                        message=str(ingestion_error["message"]),
                        source=source,
                        question=question,
                        warnings=warnings,
                    )
                    return _finalize_qa_result(
                        result=result,
                        output_dir=output_dir,
                        router_plan={},
                        source_type=source_type,
                        used_file_ingestion=False,
                    )
                assert ingested_doc_id is not None
                doc_id = ingested_doc_id
                used_file_ingestion = True
                source["was_ingested"] = True
                source["reused_existing"] = False
                source["resolved_doc_id"] = doc_id
                source["ingestion_status"] = str(ingestion_summary.get("parse_status") or ingestion_summary.get("status") or "success")
                source["ingestion"] = ingestion_summary
                source["parser"] = str(args.parser)
                source["parser_mode"] = "parse_existing"
                if mineru_output_dir is not None:
                    source["mineru_output_dir"] = str(mineru_output_dir)
                if str(args.parser) == "mineru_api":
                    source["used_mineru_api"] = True
                    if mineru_env_file is not None:
                        source["mineru_env_file"] = str(mineru_env_file)
                    source["mineru_api"] = ingestion_summary.get("mineru_api") or {}
                warnings.append("file_ingested")
        else:
            source = {"type": "doc_id", "doc_id": doc_id, "db_path": str(db_path)}

        if not doc_id:
            result = _error_result(
                mode="qa",
                run_id=run_id,
                error_type="document_required",
                message="A document id could not be resolved from --doc-id or --file.",
                source=source,
                question=question,
                warnings=warnings,
            )
            return _finalize_qa_result(
                result=result,
                output_dir=output_dir,
                router_plan={},
                source_type=source_type,
                used_file_ingestion=used_file_ingestion,
            )

        document = repository.get_document(doc_id)
        if document is None:
            result = _error_result(
                mode="qa",
                run_id=run_id,
                error_type="document_not_found",
                message=f"Document not found: {doc_id}",
                doc_id=doc_id,
                source=source,
                question=question,
                warnings=warnings,
            )
            return _finalize_qa_result(
                result=result,
                output_dir=output_dir,
                router_plan={},
                source_type=source_type,
                used_file_ingestion=used_file_ingestion,
            )

        profile = _document_profile(repository, doc_id)
        if full_model_path and router_llm_env_file is not None and not router_llm_env_file.is_file():
            result = _error_result(
                mode="qa",
                run_id=run_id,
                error_type="llm_planning_config_missing",
                message=f"Full model path requires Router/Rewriter LLM config: {router_llm_env_file}",
                doc_id=doc_id,
                source=source,
                question=question,
                warnings=[*warnings, "full_model_path_requires_llm_planning_config"],
            )
            result["full_model_path"] = True
            result["answer_policy_mode"] = str(args.answer_policy)
            result["used_qwen_answer_policy"] = False
            result["used_external_answer_api"] = False
            result["router_execution"] = {}
            result["query_planner_execution"] = {}
            return _finalize_qa_result(
                result=result,
                output_dir=output_dir,
                router_plan={},
                source_type=source_type,
                used_file_ingestion=used_file_ingestion,
            )

        router_plan = plan_route_with_optional_llm(
            {
                "doc_id": doc_id,
                "question": question,
                "document_profile": profile,
                "available_tools": AVAILABLE_TOOLS,
                "options": {
                    "allow_external_llm_router": allow_llm_router,
                    "prefer_deterministic_tools": True,
                    "max_tool_calls": 4,
                },
            },
            threshold=float(args.router_llm_threshold),
            env_file=router_llm_env_file,
            model_override=str(args.router_llm_model or "") or None,
        )
        try:
            answer_policy = _build_answer_policy(
                answer_policy=str(args.answer_policy),
                base_model_path=str(args.base_model_path),
                adapter_path=str(args.adapter_path) if args.adapter_path else None,
                device=str(args.device),
                torch_dtype=str(args.torch_dtype),
                max_prompt_tokens=args.max_prompt_tokens,
                max_new_tokens=int(args.max_new_tokens),
                answer_output_contract=str(args.answer_output_contract),
            )
        except Exception as exc:
            result = _error_result(
                mode="qa",
                run_id=run_id,
                error_type="answer_policy_build_failed",
                message=str(exc),
                doc_id=doc_id,
                source=source,
                question=question,
                task_type=str(router_plan.get("task_type") or ""),
                router_plan=router_plan,
                warnings=warnings + (router_plan.get("warnings") or []),
            )
            result["full_model_path"] = full_model_path
            result["answer_policy_mode"] = str(args.answer_policy)
            result["answer_output_contract"] = str(args.answer_output_contract)
            result["used_qwen_answer_policy"] = False
            result["used_external_answer_api"] = False
            result["router_execution"] = _router_execution(router_plan)
            result["query_planner_execution"] = {}
            return _finalize_qa_result(
                result=result,
                output_dir=output_dir,
                router_plan=router_plan,
                source_type=source_type,
                used_file_ingestion=used_file_ingestion,
            )
        tool_result = _dispatch_tool(
            repository=repository,
            trace_repository=trace_repository,
            db_path=db_path,
            document_root=document_root,
            doc_id=doc_id,
            question=question,
            router_plan=router_plan,
            dry_run=bool(args.dry_run),
            run_id=run_id,
            enable_query_planning=enable_query_planning,
            query_planner_mode=query_planner_mode,
            document_profile=profile,
            query_planner_env_file=router_llm_env_file,
            query_planner_model=str(args.router_llm_model or "") or None,
            retriever_mode=str(args.retriever_mode),
            dense_backend=str(args.dense_backend),
            dense_model_path=str(args.dense_model_path),
            dense_device=str(args.dense_device),
            dense_fp16=bool(args.dense_fp16),
            build_dense_index_if_missing=bool(args.build_dense_index_if_missing),
            reranker_backend=str(args.reranker_backend),
            reranker_model_path=str(args.reranker_model_path),
            reranker_device=str(args.reranker_device),
            reranker_fp16=bool(args.reranker_fp16),
            answer_policy=answer_policy,
        )

        result = _base_result(
            mode="qa",
            run_id=run_id,
            doc_id=doc_id,
            source=source,
            question=question,
            task_type=str(tool_result.get("effective_task_type") or router_plan.get("task_type") or ""),
            router_plan=router_plan,
        )
        result["status"] = tool_result.get("status") or "error"
        result["answer"] = tool_result.get("answer") or ""
        result["citations"] = _normalize_citations(repository, doc_id, tool_result.get("citations") or [])
        result["reasoning_summary"] = _reasoning_summary_for_tool(tool_result, result["task_type"])
        result["evidence_used"] = tool_result.get("evidence_used") or _evidence_used_from_citations(result["citations"])
        result["supporting_evidence_ids"] = tool_result.get("supporting_evidence_ids") or []
        result["tools_used"] = tool_result.get("tools_used") or []
        router_execution = _router_execution(router_plan)
        query_planner_execution = _query_planner_execution(tool_result.get("query_planner") or {})
        result["full_model_path"] = full_model_path
        result["router_execution"] = router_execution
        result["query_planner_execution"] = query_planner_execution
        result["used_llm_router"] = bool(router_execution.get("used_llm_router"))
        result["llm_router_status"] = str(router_execution.get("llm_router_status") or "")
        result["llm_router_skip_reason"] = str(router_execution.get("llm_router_skip_reason") or "")
        result["used_llm_query_rewriter"] = bool(query_planner_execution.get("used_llm_query_rewriter"))
        result["llm_query_rewriter_status"] = str(query_planner_execution.get("llm_query_rewriter_status") or "")
        result["answer_policy_mode"] = str(tool_result.get("answer_policy_mode") or args.answer_policy)
        result["answer_output_contract"] = str(tool_result.get("answer_output_contract") or args.answer_output_contract)
        result["used_qwen_answer_policy"] = bool(tool_result.get("used_qwen_answer_policy", False))
        result["used_external_answer_api"] = bool(tool_result.get("used_external_answer_api", False))
        result["retrieval_candidate_count"] = int(tool_result.get("retrieval_candidate_count") or len(result["supporting_evidence_ids"]))
        result["citation_count"] = int(tool_result.get("citation_count") or len(result["citations"]))
        result["trace_run_id"] = str(tool_result.get("trace_run_id") or tool_result.get("tool_run_id") or "")
        metadata_consistency = _page_metadata_consistency(repository, doc_id, document, result["citations"])
        result["metadata_consistency"] = metadata_consistency
        result["warnings"] = list(
            dict.fromkeys(
                warnings
                + (router_plan.get("warnings") or [])
                + (tool_result.get("warnings") or [])
                + _page_metadata_warnings(metadata_consistency)
            )
        )
        result["error"] = tool_result.get("error") or {}
        if tool_result.get("structured_result") is not None:
            result["structured_result"] = tool_result.get("structured_result")
        if tool_result.get("summary") is not None:
            result["summary"] = tool_result.get("summary")
        if tool_result.get("trace") is not None:
            result["trace"] = tool_result.get("trace")
        if tool_result.get("query_planner") is not None:
            result["query_planner"] = tool_result.get("query_planner")
        if tool_result.get("query_planner_execution") is not None:
            result["query_planner_execution"] = tool_result.get("query_planner_execution")
        if tool_result.get("retriever") is not None:
            result["retriever"] = tool_result.get("retriever")
        if tool_result.get("retriever_mode") is not None:
            result["retriever_mode"] = tool_result.get("retriever_mode")
        if tool_result.get("workflow_trace") is not None:
            result["workflow_trace"] = tool_result.get("workflow_trace")
        if tool_result.get("tool_run_id"):
            result["tool_run_id"] = tool_result.get("tool_run_id")
        if tool_result.get("tool_trace_path"):
            result["tool_trace_path"] = tool_result.get("tool_trace_path")
        return _finalize_qa_result(
            result=result,
            output_dir=output_dir,
            router_plan=router_plan,
            source_type=source_type,
            used_file_ingestion=used_file_ingestion,
        )
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Unified DocAgent Phase 5 CLI MVP.")
    parser.add_argument("--db-path", default="outputs/docagent.db")
    parser.add_argument("--doc-id")
    parser.add_argument("--file")
    parser.add_argument("--question")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--document-root", default=str(DEFAULT_DOCUMENT_ROOT))
    parser.add_argument("--parser", choices=["auto", "text", "mineru_existing", "mineru_api"], default="auto")
    parser.add_argument("--mineru-output-dir", "--mineru-output", dest="mineru_output_dir")
    parser.add_argument("--live-api", action="store_true")
    parser.add_argument("--mineru-env-file", help=f"Optional MinerU API env file, defaults to {DEFAULT_MINERU_ENV_FILE} when present.")
    parser.add_argument("--mineru-model-version", default="vlm")
    parser.add_argument("--mineru-data-id")
    parser.add_argument("--mineru-language", default="en")
    parser.add_argument("--mineru-ocr", dest="mineru_ocr", action="store_true", default=True)
    parser.add_argument("--no-mineru-ocr", dest="mineru_ocr", action="store_false")
    parser.add_argument("--disable-mineru-table", action="store_true")
    parser.add_argument("--disable-mineru-formula", action="store_true")
    parser.add_argument("--mineru-api-timeout-seconds", type=float, default=600.0)
    parser.add_argument("--mineru-api-poll-interval-seconds", type=float, default=5.0)
    parser.add_argument("--mineru-api-max-attempts", type=int, default=3)
    parser.add_argument("--mineru-api-retry-delay-seconds", type=float, default=10.0)
    parser.add_argument(
        "--force-parse",
        action="store_true",
        help="Rebuild EvidenceBlocks from parser output even when this file was ingested before.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list-documents", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--allow-llm-router", action="store_true")
    parser.add_argument("--router-llm-threshold", type=float, default=DEFAULT_LLM_ROUTER_THRESHOLD)
    parser.add_argument("--router-llm-model")
    parser.add_argument("--router-llm-env-file")
    parser.add_argument("--enable-query-planning", action="store_true")
    parser.add_argument("--query-planner-mode", choices=["rule", "llm", "hybrid"], default="hybrid")
    parser.add_argument("--retriever-mode", choices=sorted(RETRIEVER_MODE_CHOICES), default="bm25")
    parser.add_argument("--dense-backend", choices=["bge", "hash"], default="bge")
    parser.add_argument("--dense-model-path", default=DEFAULT_BGE_MODEL_PATH)
    parser.add_argument("--dense-device", default="cpu")
    parser.add_argument("--dense-fp16", action="store_true")
    parser.add_argument("--build-dense-index-if-missing", action="store_true")
    parser.add_argument("--reranker-backend", choices=["cross_encoder", "keyword"], default="cross_encoder")
    parser.add_argument("--reranker-model-path", default=DEFAULT_RERANKER_MODEL_PATH)
    parser.add_argument("--reranker-device", default="cpu")
    parser.add_argument("--reranker-fp16", action="store_true")
    parser.add_argument(
        "--full-model-path",
        action="store_true",
        help="Enable the full model-enhanced QA path: LLM router, hybrid LLM query planning, and real local_fact_qa.",
    )
    parser.add_argument("--answer-policy", choices=sorted(ANSWER_POLICY_CHOICES), default="heuristic")
    parser.add_argument(
        "--answer-output-contract",
        choices=["candidate_citations", "v3_refs"],
        default="candidate_citations",
        help="Internal AnswerPolicy output contract; v3_refs maps model-selected E# refs back to citations.",
    )
    parser.add_argument("--base-model-path", default=DEFAULT_QWEN_BASE_MODEL_PATH)
    parser.add_argument("--adapter-path")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--torch-dtype", default="bfloat16")
    parser.add_argument("--max-prompt-tokens", type=int, default=4096)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run_cli(args)
    except Exception as exc:
        result = _error_result(
            mode="error",
            run_id=_now_run_id(),
            error_type=type(exc).__name__,
            message=str(exc),
        )
        _print_json(result)
        return 1
    _print_json(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
