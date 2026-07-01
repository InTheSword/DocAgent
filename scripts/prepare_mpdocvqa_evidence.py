from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.run_final_eval_subset import as_list, normalize_text


SCRIPT_VERSION = "mpdocvqa-evidence-materialization-v1"
DEFAULT_SUBSET_ROOT = ROOT / "outputs" / "final_eval" / "mpdocvqa_val_subset"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "mpdocvqa_val_evidence"
DEFAULT_CLI_PATH = ROOT / "scripts" / "docagent_cli.py"
DEFAULT_QUESTION = "How many pages are in this document?"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str = ""


CommandRunner = Callable[[list[str], Path, int], CommandResult]


def repo_path(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def safe_relpath(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def now_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"mpdocvqa_evidence_{stamp}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit() -> str:
    try:
        completed = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True, capture_output=True)
        return completed.stdout.strip() if completed.returncode == 0 else ""
    except Exception:
        return ""


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _default_command_runner(command: list[str], cwd: Path, timeout_seconds: int) -> CommandResult:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout_seconds, check=False)
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def parse_stdout(stdout: str) -> tuple[dict[str, Any] | None, str]:
    stripped = stdout.strip()
    if not stripped:
        return None, "stdout_empty"
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None, "stdout_not_json"
    if not isinstance(payload, dict):
        return None, "stdout_json_not_object"
    return payload, ""


def resolve_subset_file(subset_root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else subset_root / path


def load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [row for row in read_jsonl(path) if isinstance(row, dict)]


def rows_by_doc_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("doc_id") or ""): row for row in rows if row.get("doc_id")}


def build_cli_command(
    *,
    pdf_path: Path,
    db_path: Path,
    document_root: Path,
    cli_output_dir: Path,
    cli_path: Path,
    live_api: bool,
    mineru_env_file: Path | None,
    mineru_api_timeout_seconds: int,
    mineru_api_poll_interval_seconds: float,
    mineru_api_max_attempts: int,
    mineru_api_retry_delay_seconds: float,
    mineru_ocr: bool,
    rebuild_evidence_blocks: bool,
    python_executable: str,
) -> list[str]:
    command = [
        python_executable,
        str(cli_path),
        "--db-path",
        str(db_path),
        "--document-root",
        str(document_root),
        "--file",
        str(pdf_path),
        "--parser",
        "mineru_api",
    ]
    if live_api:
        command.append("--live-api")
    if mineru_env_file is not None:
        command.extend(["--mineru-env-file", str(mineru_env_file)])
    if mineru_ocr:
        command.append("--mineru-ocr")
    else:
        command.append("--no-mineru-ocr")
    if rebuild_evidence_blocks:
        command.append("--force-parse")
    command.extend(
        [
            "--mineru-api-timeout-seconds",
            str(mineru_api_timeout_seconds),
            "--mineru-api-poll-interval-seconds",
            str(mineru_api_poll_interval_seconds),
            "--mineru-api-max-attempts",
            str(mineru_api_max_attempts),
            "--mineru-api-retry-delay-seconds",
            str(mineru_api_retry_delay_seconds),
            "--question",
            DEFAULT_QUESTION,
            "--output-dir",
            str(cli_output_dir),
        ]
    )
    return command


def document_result_row(
    *,
    document: dict[str, Any],
    subset_root: Path,
    payload: dict[str, Any] | None,
    parse_error: str,
    completed: CommandResult,
    command: list[str],
) -> dict[str, Any]:
    pdf_path = resolve_subset_file(subset_root, str(document.get("pdf_path") or ""))
    failures: list[str] = []
    if parse_error:
        failures.append(parse_error)
    if completed.returncode != 0:
        failures.append(f"nonzero_returncode:{completed.returncode}")
    if payload is None:
        status = "failed"
        source: dict[str, Any] = {}
        ingestion: dict[str, Any] = {}
    else:
        status = "passed" if payload.get("status") == "success" and not failures else "failed"
        if payload.get("status") != "success":
            error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
            failures.append(f"status_not_success:{error.get('type') or payload.get('status')}")
        source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
        ingestion = source.get("ingestion") if isinstance(source.get("ingestion"), dict) else {}
    ingested_doc_id = str((payload or {}).get("doc_id") or source.get("resolved_doc_id") or "")
    return {
        "doc_id": str(document.get("doc_id") or ""),
        "source_document": str(document.get("source_doc_id") or ""),
        "pdf_path": safe_relpath(pdf_path) if pdf_path else "",
        "pdf_sha256": str(document.get("pdf_sha256") or ""),
        "ingested_doc_id": ingested_doc_id,
        "pass_fail": status,
        "failure_reasons": list(dict.fromkeys(failures)),
        "returncode": completed.returncode,
        "source_was_ingested": source.get("was_ingested"),
        "source_reused_existing": source.get("reused_existing"),
        "source_parser": source.get("parser") or "",
        "source_parser_mode": source.get("parser_mode") or "",
        "used_mineru_api": bool(source.get("used_mineru_api")),
        "api_status": str((source.get("mineru_api") or {}).get("api_status") or ""),
        "artifact_dir": str((payload or {}).get("artifact_dir") or ""),
        "ingestion_parse_status": str(ingestion.get("parse_status") or ""),
        "ingestion_page_count": ingestion.get("page_count"),
        "ingestion_block_count": ingestion.get("block_count"),
        "stdout_preview": completed.stdout.strip()[:1000],
        "stderr_preview": completed.stderr.strip()[:1000],
        "command": command,
    }


def block_page(block: Any) -> int | None:
    if getattr(block, "page_id", None) is not None:
        return int(block.page_id)
    location = getattr(block, "location", None)
    if location is not None and getattr(location, "page", None) is not None:
        return int(location.page)
    return None


def gold_pages(manifest: dict[str, Any]) -> list[int]:
    pages: list[int] = []
    for item in manifest.get("gold_evidence") or []:
        value = item.get("page") if isinstance(item, dict) else None
        try:
            pages.append(int(value))
        except (TypeError, ValueError):
            continue
    return sorted(set(pages))


def answer_text_hit(text: str, answers: list[str]) -> bool:
    normalized_text = normalize_text(text)
    return any(answer and normalize_text(answer) in normalized_text for answer in answers)


def build_sample_rows(
    *,
    sample_manifests: list[dict[str, Any]],
    document_rows: dict[str, dict[str, Any]],
    repository: DocumentRepository,
) -> list[dict[str, Any]]:
    blocks_by_doc: dict[str, list[Any]] = {}
    sample_rows: list[dict[str, Any]] = []
    for manifest in sample_manifests:
        source_doc_id = str(manifest.get("doc_id") or "")
        document_row = document_rows.get(source_doc_id, {})
        ingested_doc_id = str(document_row.get("ingested_doc_id") or "")
        if ingested_doc_id and ingested_doc_id not in blocks_by_doc:
            blocks_by_doc[ingested_doc_id] = repository.load_evidence_blocks(ingested_doc_id, include_page_blocks=True)
        blocks = blocks_by_doc.get(ingested_doc_id, [])
        pages = gold_pages(manifest)
        page_blocks = [block for block in blocks if getattr(block, "block_type", "") == "page"]
        page_block_ids = [block.block_id for block in page_blocks if block_page(block) in set(pages)]
        child_blocks_on_gold_pages = [
            block.block_id for block in blocks if getattr(block, "block_type", "") != "page" and block_page(block) in set(pages)
        ]
        gold_page_text = "\n".join(block.retrieval_text for block in page_blocks if block_page(block) in set(pages))
        answers = as_list(manifest.get("answers"))
        evidence_ready = bool(document_row.get("pass_fail") == "passed" and ingested_doc_id and pages and page_block_ids)
        hit = answer_text_hit(gold_page_text, answers) if gold_page_text else False
        sample_rows.append(
            {
                "sample_id": str(manifest.get("sample_id") or ""),
                "dataset": "mp_docvqa",
                "split": str(manifest.get("split") or "val"),
                "doc_id": source_doc_id,
                "ingested_doc_id": ingested_doc_id,
                "source_document": str(manifest.get("source_document") or ""),
                "question": str(manifest.get("question") or ""),
                "answers": answers,
                "expected_answer_type": str(manifest.get("expected_answer_type") or "extractive"),
                "expected_tools": [str(item) for item in manifest.get("expected_tools") or []],
                "gold_pages": pages,
                "gold_page_block_ids": page_block_ids,
                "gold_page_child_block_ids": child_blocks_on_gold_pages,
                "gold_page_text_preview": " ".join(gold_page_text.split())[:500],
                "document_pass_fail": str(document_row.get("pass_fail") or "missing_document"),
                "evidence_ready": evidence_ready,
                "answer_text_gold_page_hit": hit,
                "block_count": len(blocks),
                "page_block_count": len(page_blocks),
                "candidate_block_count_on_gold_pages": len(child_blocks_on_gold_pages),
                "evaluation_mode": "mpdocvqa_mineru_evidence_readiness",
                "requires_model_answer": True,
                "requires_mineru_or_retrieval": False,
                "pass_fail": "passed" if evidence_ready else "failed",
                "failure_reasons": [] if evidence_ready else ["evidence_not_ready"],
            }
        )
    return sample_rows


def summarize(
    *,
    run_id: str,
    artifact_dir: Path,
    document_rows: list[dict[str, Any]],
    sample_rows: list[dict[str, Any]],
    live_api: bool,
    mineru_ocr: bool,
) -> dict[str, Any]:
    document_status = Counter(str(row.get("pass_fail") or "") for row in document_rows)
    sample_status = Counter(str(row.get("pass_fail") or "") for row in sample_rows)
    failure_reasons = Counter(reason for row in [*document_rows, *sample_rows] for reason in row.get("failure_reasons") or [])
    sample_count = len(sample_rows)
    return {
        "command": "prepare_mpdocvqa_evidence",
        "status": "success" if document_status.get("failed", 0) == 0 and sample_status.get("failed", 0) == 0 else "failed",
        "script_version": SCRIPT_VERSION,
        "evaluation_scope": "mpdocvqa_mineru_evidence_materialization_not_formal_benchmark",
        "quality_status": "diagnostic_only",
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "document_count": len(document_rows),
        "document_passed_count": document_status.get("passed", 0),
        "document_failed_count": document_status.get("failed", 0),
        "sample_count": sample_count,
        "sample_evidence_ready_count": sum(1 for row in sample_rows if row.get("evidence_ready")),
        "sample_evidence_ready_rate": rate(sum(1 for row in sample_rows if row.get("evidence_ready")), sample_count),
        "answer_text_gold_page_hit_count": sum(1 for row in sample_rows if row.get("answer_text_gold_page_hit")),
        "answer_text_gold_page_hit_rate": rate(sum(1 for row in sample_rows if row.get("answer_text_gold_page_hit")), sample_count),
        "failure_reason_distribution": dict(sorted(failure_reasons.items())),
        "used_mineru_api": True,
        "used_online_mineru_ocr": bool(live_api and mineru_ocr),
        "used_external_api": bool(live_api),
        "used_qwen": False,
        "used_vlm": False,
        "used_training": False,
        "formal_benchmark_acceptance": False,
        "documents_path": safe_relpath(artifact_dir / "documents.jsonl"),
        "sample_evidence_manifest_path": safe_relpath(artifact_dir / "sample_evidence_manifest.jsonl"),
        "summary_path": safe_relpath(artifact_dir / "summary.json"),
        "preview_path": safe_relpath(artifact_dir / "preview.json"),
        "manifest_path": safe_relpath(artifact_dir / "manifest.json"),
    }


def rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# MP-DocVQA Evidence Materialization",
        "",
        f"- evaluation_scope: `{summary['evaluation_scope']}`",
        f"- quality_status: `{summary['quality_status']}`",
        f"- used_mineru_api: `{str(summary['used_mineru_api']).lower()}`",
        f"- formal_benchmark_acceptance: `{str(summary['formal_benchmark_acceptance']).lower()}`",
        "",
        "## Counts",
        "",
        f"- document_count: {summary['document_count']}",
        f"- document_passed_count: {summary['document_passed_count']}",
        f"- document_failed_count: {summary['document_failed_count']}",
        f"- sample_count: {summary['sample_count']}",
        f"- sample_evidence_ready_rate: {summary['sample_evidence_ready_rate']}",
        f"- answer_text_gold_page_hit_rate: {summary['answer_text_gold_page_hit_rate']}",
        "",
        "This is a MinerU/evidence-readiness diagnostic. It is not final answer-quality benchmark acceptance.",
    ]
    if summary.get("failure_reason_distribution"):
        lines.extend(["", "## Failures"])
        lines.extend(f"- {key}: {value}" for key, value in sorted(summary["failure_reason_distribution"].items()))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_manifest(path: Path, *, run_id: str, artifact_dir: Path, artifact_paths: list[Path], summary: dict[str, Any]) -> None:
    files = []
    for artifact in artifact_paths:
        if not artifact.is_file():
            continue
        files.append(
            {
                "path": safe_relpath(artifact),
                "size_bytes": artifact.stat().st_size,
                "sha256": sha256_file(artifact),
            }
        )
    write_json(
        path,
        {
            "run_id": run_id,
            "script_version": SCRIPT_VERSION,
            "git_commit": git_commit(),
            "artifact_dir": safe_relpath(artifact_dir),
            "summary": {
                "status": summary.get("status"),
                "document_count": summary.get("document_count"),
                "sample_count": summary.get("sample_count"),
                "sample_evidence_ready_rate": summary.get("sample_evidence_ready_rate"),
            },
            "files": files,
        },
    )


def create_sync_bundle(sync_root: Path, run_id: str, artifact_paths: list[Path]) -> tuple[Path, list[Path]]:
    sync_dir = sync_root / run_id
    sync_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for source in artifact_paths:
        if source.name not in {"summary.json", "summary.md", "preview.json", "manifest.json"} or not source.is_file():
            continue
        target = sync_dir / source.name
        target.write_bytes(source.read_bytes())
        copied.append(target)
    return sync_dir, copied


def prepare_mpdocvqa_evidence(
    *,
    subset_root: Path = DEFAULT_SUBSET_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
    db_path: Path | None = None,
    document_root: Path | None = None,
    cli_path: Path = DEFAULT_CLI_PATH,
    live_api: bool = False,
    mineru_env_file: Path | None = None,
    mineru_api_timeout_seconds: int = 900,
    mineru_api_poll_interval_seconds: float = 5.0,
    mineru_api_max_attempts: int = 3,
    mineru_api_retry_delay_seconds: float = 10.0,
    mineru_ocr: bool = True,
    max_documents: int | None = None,
    python_executable: str = sys.executable,
    timeout_seconds: int = 1200,
    command_runner: CommandRunner = _default_command_runner,
    sync_output_root: Path | None = None,
    previous_run_dir: Path | None = None,
    retry_failed_only: bool = False,
    rebuild_evidence_blocks: bool = False,
) -> dict[str, Any]:
    run_id = run_id or now_run_id()
    if not live_api:
        raise ValueError("MP-DocVQA evidence materialization uses MinerU API and requires --live-api")
    artifact_dir = output_root / run_id
    cli_output_dir = artifact_dir / "cli_artifacts"
    previous_summary: dict[str, Any] = {}
    previous_document_rows: list[dict[str, Any]] = []
    if previous_run_dir is not None:
        previous_document_rows = load_rows(previous_run_dir / "documents.jsonl")
        summary_path = previous_run_dir / "summary.json"
        if summary_path.is_file():
            previous_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if retry_failed_only and previous_run_dir is None:
        raise ValueError("--retry-failed-only requires --previous-run-dir")
    if db_path is None and previous_summary.get("db_path"):
        db_path = repo_path(str(previous_summary["db_path"]))
    if document_root is None and previous_summary.get("document_root"):
        document_root = repo_path(str(previous_summary["document_root"]))
    db_path = db_path or (artifact_dir / "docagent.db")
    document_root = document_root or (artifact_dir / "documents")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    cli_output_dir.mkdir(parents=True, exist_ok=True)
    document_root.mkdir(parents=True, exist_ok=True)

    all_source_documents = load_rows(subset_root / "documents.jsonl")
    if max_documents is not None:
        all_source_documents = all_source_documents[: max(0, int(max_documents))]
    source_documents = all_source_documents
    if retry_failed_only:
        failed_doc_ids = {
            str(row.get("doc_id") or "")
            for row in previous_document_rows
            if row.get("pass_fail") != "passed"
        }
        source_documents = [row for row in all_source_documents if str(row.get("doc_id") or "") in failed_doc_ids]
    sample_manifests = load_rows(subset_root / "sample_manifest.jsonl")
    if previous_run_dir is not None:
        selected_doc_ids = {str(row.get("doc_id") or "") for row in previous_document_rows}
        selected_doc_ids.update(str(row.get("doc_id") or "") for row in source_documents)
    else:
        selected_doc_ids = {str(row.get("doc_id") or "") for row in source_documents}
    sample_manifests = [row for row in sample_manifests if str(row.get("doc_id") or "") in selected_doc_ids]

    document_results: list[dict[str, Any]] = []
    for document in source_documents:
        pdf_path = resolve_subset_file(subset_root, str(document.get("pdf_path") or ""))
        if pdf_path is None or not pdf_path.is_file():
            document_results.append(
                {
                    "doc_id": str(document.get("doc_id") or ""),
                    "pdf_path": str(document.get("pdf_path") or ""),
                    "ingested_doc_id": "",
                    "pass_fail": "failed",
                    "failure_reasons": ["pdf_missing"],
                }
            )
            continue
        command = build_cli_command(
            pdf_path=pdf_path,
            db_path=db_path,
            document_root=document_root,
            cli_output_dir=cli_output_dir,
            cli_path=cli_path,
            live_api=live_api,
            mineru_env_file=mineru_env_file,
            mineru_api_timeout_seconds=mineru_api_timeout_seconds,
            mineru_api_poll_interval_seconds=mineru_api_poll_interval_seconds,
            mineru_api_max_attempts=mineru_api_max_attempts,
            mineru_api_retry_delay_seconds=mineru_api_retry_delay_seconds,
            mineru_ocr=mineru_ocr,
            rebuild_evidence_blocks=rebuild_evidence_blocks,
            python_executable=python_executable,
        )
        completed = command_runner(command, ROOT, timeout_seconds)
        payload, parse_error = parse_stdout(completed.stdout)
        document_results.append(
            document_result_row(
                document=document,
                subset_root=subset_root,
                payload=payload,
                parse_error=parse_error,
                completed=completed,
                command=command,
            )
        )

    if previous_run_dir is not None:
        merged_by_doc_id = rows_by_doc_id(previous_document_rows)
        merged_by_doc_id.update(rows_by_doc_id(document_results))
        ordered_doc_ids = [str(row.get("doc_id") or "") for row in all_source_documents if str(row.get("doc_id") or "") in merged_by_doc_id]
        extra_doc_ids = [doc_id for doc_id in merged_by_doc_id if doc_id not in set(ordered_doc_ids)]
        document_rows_for_summary = [merged_by_doc_id[doc_id] for doc_id in [*ordered_doc_ids, *extra_doc_ids]]
    else:
        document_rows_for_summary = document_results

    conn = connect(db_path)
    try:
        repository = DocumentRepository(conn)
        sample_rows = build_sample_rows(
            sample_manifests=sample_manifests,
            document_rows=rows_by_doc_id(document_rows_for_summary),
            repository=repository,
        )
    finally:
        conn.close()

    summary = summarize(
        run_id=run_id,
        artifact_dir=artifact_dir,
        document_rows=document_rows_for_summary,
        sample_rows=sample_rows,
        live_api=live_api,
        mineru_ocr=mineru_ocr,
    )
    if previous_run_dir is not None:
        summary["previous_run_dir"] = safe_relpath(previous_run_dir)
        summary["retry_failed_only"] = bool(retry_failed_only)
        summary["retried_document_count"] = len(document_results)
    summary["rebuild_evidence_blocks"] = bool(rebuild_evidence_blocks)
    summary["db_path"] = safe_relpath(db_path)
    summary["document_root"] = safe_relpath(document_root)
    summary["cli_artifact_dir"] = safe_relpath(cli_output_dir)
    artifact_paths = [
        artifact_dir / "documents.jsonl",
        artifact_dir / "sample_evidence_manifest.jsonl",
        artifact_dir / "summary.json",
        artifact_dir / "summary.md",
        artifact_dir / "preview.json",
        artifact_dir / "manifest.json",
    ]
    summary["artifact_paths"] = [safe_relpath(path) for path in artifact_paths]
    if sync_output_root is not None:
        sync_dir = sync_output_root / run_id
        summary["sync_bundle_path"] = safe_relpath(sync_dir)
        summary["sync_artifact_paths"] = [
            safe_relpath(sync_dir / name)
            for name in ("summary.json", "summary.md", "preview.json", "manifest.json")
        ]
    write_jsonl(artifact_paths[0], document_rows_for_summary)
    write_jsonl(artifact_paths[1], sample_rows)
    write_json(artifact_paths[2], summary)
    write_summary_markdown(artifact_paths[3], summary)
    write_json(artifact_paths[4], {"summary": summary, "documents": document_results[:5], "samples": sample_rows[:5]})
    write_manifest(artifact_paths[5], run_id=run_id, artifact_dir=artifact_dir, artifact_paths=artifact_paths, summary=summary)
    result = dict(summary)
    if sync_output_root is not None:
        _, sync_paths = create_sync_bundle(sync_output_root, run_id, artifact_paths)
        result["sync_artifact_paths"] = [safe_relpath(path) for path in sync_paths]
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize MP-DocVQA final subset PDFs into MinerU-backed evidence.")
    parser.add_argument("--subset-root", default=str(DEFAULT_SUBSET_ROOT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id")
    parser.add_argument("--db-path")
    parser.add_argument("--document-root")
    parser.add_argument("--cli-path", default=str(DEFAULT_CLI_PATH))
    parser.add_argument("--live-api", action="store_true")
    parser.add_argument("--mineru-env-file")
    parser.add_argument("--mineru-api-timeout-seconds", type=int, default=900)
    parser.add_argument("--mineru-api-poll-interval-seconds", type=float, default=5.0)
    parser.add_argument("--mineru-api-max-attempts", type=int, default=3)
    parser.add_argument("--mineru-api-retry-delay-seconds", type=float, default=10.0)
    parser.add_argument("--mineru-ocr", dest="mineru_ocr", action="store_true", default=True)
    parser.add_argument("--no-mineru-ocr", dest="mineru_ocr", action="store_false")
    parser.add_argument("--max-documents", type=int)
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    parser.add_argument("--sync-output-dir")
    parser.add_argument("--previous-run-dir")
    parser.add_argument("--retry-failed-only", action="store_true")
    parser.add_argument(
        "--rebuild-evidence-blocks",
        action="store_true",
        help="Pass --force-parse to docagent_cli so cached MinerU output is reconverted into EvidenceBlocks.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = prepare_mpdocvqa_evidence(
            subset_root=repo_path(args.subset_root) or DEFAULT_SUBSET_ROOT,
            output_root=repo_path(args.output_dir) or DEFAULT_OUTPUT_ROOT,
            run_id=args.run_id,
            db_path=repo_path(args.db_path),
            document_root=repo_path(args.document_root),
            cli_path=repo_path(args.cli_path) or DEFAULT_CLI_PATH,
            live_api=bool(args.live_api),
            mineru_env_file=repo_path(args.mineru_env_file),
            mineru_api_timeout_seconds=int(args.mineru_api_timeout_seconds),
            mineru_api_poll_interval_seconds=float(args.mineru_api_poll_interval_seconds),
            mineru_api_max_attempts=int(args.mineru_api_max_attempts),
            mineru_api_retry_delay_seconds=float(args.mineru_api_retry_delay_seconds),
            mineru_ocr=bool(args.mineru_ocr),
            max_documents=args.max_documents,
            python_executable=str(args.python_executable),
            timeout_seconds=int(args.timeout_seconds),
            sync_output_root=repo_path(args.sync_output_dir),
            previous_run_dir=repo_path(args.previous_run_dir),
            retry_failed_only=bool(args.retry_failed_only),
            rebuild_evidence_blocks=bool(args.rebuild_evidence_blocks),
        )
    except Exception as exc:
        result = {
            "command": "prepare_mpdocvqa_evidence",
            "status": "failed",
            "quality_status": "blocked",
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "used_mineru_api": True,
            "used_qwen": False,
            "used_training": False,
            "formal_benchmark_acceptance": False,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
