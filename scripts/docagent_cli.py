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
from docagent.parser.mineru_backend import MinerUParserBackend
from docagent.parser.text_backend import TextParserBackend
from docagent.retrieval.index_manager import IndexedDocumentRetriever
from docagent.retrieval.query_planner import plan_queries
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
from docagent.tools.local_fact_qa import local_fact_qa


AVAILABLE_TOOLS = [
    "local_fact_qa",
    "count_pages",
    "count_blocks",
    "count_tables",
    "count_images",
    "get_page_text",
    "list_pages",
]
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "cli"
DEFAULT_DOCUMENT_ROOT = ROOT / "data" / "documents"


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


def _parser_backend_for_file(
    file_path: Path,
    *,
    parser_name: str,
    parser_mode: str,
    mineru_output_dir: Path | None,
    mineru_command: str,
    mineru_timeout_seconds: int,
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
    if parser_name in {"mineru_existing", "mineru"} or (
        parser_name == "auto" and extension in {".pdf", ".png", ".jpg", ".jpeg"} and mineru_output_dir is not None
    ):
        mode = "parse_existing" if parser_name == "mineru_existing" or mineru_output_dir is not None else parser_mode
        backend_name = "mineru_existing" if mode == "parse_existing" else "mineru"
        return (
            MinerUParserBackend(
                mode=mode,
                command=mineru_command,
                timeout_seconds=mineru_timeout_seconds,
                backend_name=backend_name,
            ),
            None,
        )
    return None, {
        "type": "parser_backend_unavailable",
        "message": (
            f"No CLI parser backend is configured for {extension} files. "
            "Use --parser mineru_existing with --mineru-output-dir for existing MinerU output, "
            "or use a UTF-8 .txt file."
        ),
    }


def _ingest_file(
    *,
    repository: DocumentRepository,
    file_path: Path,
    document_root: Path,
    parser_name: str,
    parser_mode: str,
    mineru_output_dir: Path | None,
    mineru_command: str,
    mineru_timeout_seconds: int,
) -> tuple[str | None, dict[str, Any] | None, dict[str, Any]]:
    parser_backend, parser_error = _parser_backend_for_file(
        file_path,
        parser_name=parser_name,
        parser_mode=parser_mode,
        mineru_output_dir=mineru_output_dir,
        mineru_command=mineru_command,
        mineru_timeout_seconds=mineru_timeout_seconds,
    )
    if parser_error is not None:
        return None, parser_error, {"status": "failed", "error": parser_error}
    assert parser_backend is not None
    if isinstance(parser_backend, MinerUParserBackend) and parser_backend.mode == "parse_existing" and mineru_output_dir is not None:
        copy_error = _copy_mineru_output_to_document_cache(
            file_path=file_path,
            document_root=document_root,
            mineru_output_dir=mineru_output_dir,
        )
        if copy_error is not None:
            return None, copy_error, {"status": "failed", "error": copy_error}
    service = DocumentIngestionService(document_root=document_root, repository=repository)
    try:
        ingestion_result = service.ingest(file_path=file_path, parser_backend=parser_backend)
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


def _run_local_fact_qa(
    *,
    repository: DocumentRepository,
    trace_repository: TraceRepository,
    db_path: Path,
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
) -> dict[str, Any]:
    options: dict[str, Any] = {"dry_run": dry_run, "qid": run_id}
    if not dry_run:
        options["trace_path"] = str(db_path)
    query_planner_payload: dict[str, Any] = {}
    retriever = None
    query_planner_warnings: list[str] = []
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
        if not dry_run:
            retriever = IndexedDocumentRetriever(
                repository.load_evidence_blocks(doc_id),
                mode="bm25",
                query_plan=query_plan,
            )
    result = local_fact_qa(
        {"doc_id": doc_id, "question": question, "router_plan": router_plan, "options": options},
        document_repository=repository,
        trace_repository=None if dry_run else trace_repository,
        retriever=retriever,
    )
    payload = {
        "status": "success" if result.get("status") == "success" else "error",
        "answer": result.get("answer") or "",
        "citations": result.get("citations") or [],
        "supporting_evidence_ids": result.get("supporting_evidence_ids") or [],
        "tools_used": result.get("tools_used") or ["local_fact_qa"],
        "tool_run_id": result.get("run_id") or "",
        "tool_trace_path": result.get("trace_path") or "",
        "structured_result": result,
        "warnings": list(dict.fromkeys(query_planner_warnings + (result.get("warnings") or []))),
        "error": result.get("error") or {},
    }
    if query_planner_payload:
        payload["query_planner"] = query_planner_payload
    return payload


def _unsupported_task(task_type: str) -> dict[str, Any]:
    mapping = {
        "document_summary": (
            "document_summary_not_implemented",
            "document_summary remains Phase 5E and is not implemented in this CLI MVP.",
        ),
        "table_lookup_or_calculation": (
            "table_lookup_not_implemented",
            "table_lookup and simple_calculation are not implemented in this CLI MVP.",
        ),
        "structured_extraction": (
            "structured_extraction_not_implemented",
            "structured extraction tools are not implemented in this CLI MVP.",
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
        )
    if task_type == "document_summary" and dry_run and "local_fact_qa" in set(str(tool) for tool in router_plan.get("selected_tools") or []):
        result = _run_local_fact_qa(
            repository=repository,
            trace_repository=trace_repository,
            db_path=db_path,
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
        )
        result["effective_task_type"] = "local_fact_qa"
        return result
    if task_type in {"document_summary", "table_lookup_or_calculation", "structured_extraction"}:
        unsupported = _unsupported_task(task_type)
        unsupported["warnings"] = list(dict.fromkeys((router_plan.get("warnings") or []) + [unsupported["error"]["type"]]))
        return unsupported
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
        "used_file_ingestion": bool(source.get("was_ingested", used_file_ingestion)),
        "reused_existing_document": bool(source.get("reused_existing", False)),
        "ingestion_status": source.get("ingestion_status") or "",
        "ingestion_error": source.get("ingestion_error") or {},
        "used_router": bool(router_plan),
        "used_query_planning": bool((result.get("query_planner") or {}).get("enabled")),
        "query_planner_mode": str((result.get("query_planner") or {}).get("mode") or ""),
        "query_count": len((result.get("query_planner") or {}).get("final_queries") or []),
        "used_external_api": _router_used_external_api(router_plan) or _query_planner_used_external_api(result.get("query_planner") or {}),
        "used_vlm": False,
        "used_training": False,
        "used_full_e2e": False,
        "warnings": result.get("warnings") or [],
        "error": result.get("error") or {},
    }
    trace = {
        "run_id": run_id,
        "source": source,
        "router_plan": router_plan,
        "query_planner": result.get("query_planner") or {},
        "result_status": result.get("status"),
        "tools_used": result.get("tools_used") or [],
        "supporting_evidence_ids": result.get("supporting_evidence_ids") or [],
        "error": result.get("error") or {},
    }

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
    limit = max(0, int(args.limit))

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
            resolved_doc_id, file_warnings, _document = _resolve_file_doc_id(repository=repository, file_path=file_path)
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
                    parser_mode=str(args.parser_mode),
                    mineru_output_dir=mineru_output_dir,
                    mineru_command=str(args.mineru_command),
                    mineru_timeout_seconds=int(args.mineru_timeout_seconds),
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
                source["parser_mode"] = str(args.parser_mode)
                if mineru_output_dir is not None:
                    source["mineru_output_dir"] = str(mineru_output_dir)
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
        router_llm_env_file = _project_path(args.router_llm_env_file) if args.router_llm_env_file else None
        router_plan = plan_route_with_optional_llm(
            {
                "doc_id": doc_id,
                "question": question,
                "document_profile": profile,
                "available_tools": AVAILABLE_TOOLS,
                "options": {
                    "allow_external_llm_router": bool(args.allow_llm_router),
                    "prefer_deterministic_tools": True,
                    "max_tool_calls": 4,
                },
            },
            threshold=float(args.router_llm_threshold),
            env_file=router_llm_env_file,
            model_override=str(args.router_llm_model or "") or None,
        )
        tool_result = _dispatch_tool(
            repository=repository,
            trace_repository=trace_repository,
            db_path=db_path,
            doc_id=doc_id,
            question=question,
            router_plan=router_plan,
            dry_run=bool(args.dry_run),
            run_id=run_id,
            enable_query_planning=bool(args.enable_query_planning),
            query_planner_mode=str(args.query_planner_mode),
            document_profile=profile,
            query_planner_env_file=router_llm_env_file,
            query_planner_model=str(args.router_llm_model or "") or None,
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
        result["citations"] = tool_result.get("citations") or []
        result["supporting_evidence_ids"] = tool_result.get("supporting_evidence_ids") or []
        result["tools_used"] = tool_result.get("tools_used") or []
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
        if tool_result.get("query_planner") is not None:
            result["query_planner"] = tool_result.get("query_planner")
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
    parser.add_argument("--parser", choices=["auto", "text", "mineru_existing", "mineru"], default="auto")
    parser.add_argument("--parser-mode", choices=["parse_existing", "local_cli"], default="parse_existing")
    parser.add_argument("--mineru-output-dir", "--mineru-output", dest="mineru_output_dir")
    parser.add_argument("--mineru-command", default="mineru")
    parser.add_argument("--mineru-timeout-seconds", type=int, default=600)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list-documents", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--allow-llm-router", action="store_true")
    parser.add_argument("--router-llm-threshold", type=float, default=DEFAULT_LLM_ROUTER_THRESHOLD)
    parser.add_argument("--router-llm-model")
    parser.add_argument("--router-llm-env-file")
    parser.add_argument("--enable-query-planning", action="store_true")
    parser.add_argument("--query-planner-mode", choices=["rule", "llm", "hybrid"], default="hybrid")
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
        print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
