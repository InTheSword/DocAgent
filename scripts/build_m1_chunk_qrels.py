from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docagent.schemas import Chunk
from docagent.utils.jsonl import read_jsonl, write_jsonl


SCHEMA_VERSION = "m1-chunk-qrels-v1"
EVIDENCE_TYPE_COMPATIBILITY = {
    "table": {"table"},
    "figure": {"image", "figure", "chart"},
    "heading": {"heading", "title"},
    "text": {"body", "text", "paragraph", "list_item", "caption", "reference"},
}
METHOD_PRIORITY = {
    "normalized_contains": 0,
    "compact_contains": 1,
    "character_coverage": 2,
}
QUEUE_PRIORITY = {
    "unmapped": 0,
    "fuzzy": 1,
    "exact_multi": 2,
    "exact_ambiguous": 3,
    "exact_single": 4,
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for piece in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(piece)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalized_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = normalized.translate(
        str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "—": "-", "–": "-"})
    )
    return re.sub(r"\s+", " ", normalized).strip()


def _compact_text(value: str) -> str:
    return "".join(re.findall(r"[0-9a-z\u4e00-\u9fff]+", _normalized_text(value)))


def _chunk_text(chunk: Chunk) -> str:
    metadata = chunk.metadata
    parts = [
        chunk.text,
        chunk.retrieval_text,
        chunk.visual_summary or "",
        str(metadata.get("table_markdown") or ""),
        str(metadata.get("table_context") or ""),
        str(metadata.get("table_caption") or ""),
        str(metadata.get("image_caption") or ""),
        str(metadata.get("summary") or ""),
    ]
    return "\n".join(dict.fromkeys(part for part in parts if part))


def _source_pages(chunk: Chunk) -> set[int]:
    pages = {
        int(page)
        for page in chunk.metadata.get("source_page_numbers") or []
        if isinstance(page, int) and not isinstance(page, bool)
    }
    if chunk.page_id is not None:
        pages.add(int(chunk.page_id))
    return pages


def _page_compatible(chunk: Chunk, pages: set[int]) -> bool:
    return not pages or bool(_source_pages(chunk).intersection(pages))


def _type_compatible(chunk: Chunk, evidence_type: str) -> bool:
    allowed = EVIDENCE_TYPE_COMPATIBILITY.get(evidence_type)
    if not allowed:
        return True
    block_type = chunk.block_type.casefold()
    content_type = str(chunk.metadata.get("content_type") or block_type).casefold()
    if evidence_type == "text" and block_type == "text":
        return True
    if evidence_type == "heading" and (content_type == "heading" or chunk.metadata.get("heading_role")):
        return True
    return block_type in allowed or content_type in allowed


def _reading_order(chunk: Chunk) -> tuple[int, str]:
    value = chunk.metadata.get("reading_order")
    return (int(value) if isinstance(value, int) else 10**9, chunk.block_id)


def _candidate_for_window(source_text: str, chunks: list[Chunk]) -> dict[str, Any] | None:
    combined = "\n".join(_chunk_text(chunk) for chunk in chunks)
    needle = _normalized_text(source_text)
    compact_needle = _compact_text(source_text)
    haystack = _normalized_text(combined)
    compact_haystack = _compact_text(combined)
    if not compact_needle or not compact_haystack:
        return None
    if needle and needle in haystack:
        method = "normalized_contains"
        coverage = 1.0
    elif compact_needle in compact_haystack:
        method = "compact_contains"
        coverage = 1.0
    else:
        match = SequenceMatcher(None, compact_needle, compact_haystack, autojunk=False).find_longest_match()
        method = "character_coverage"
        coverage = match.size / len(compact_needle)
    if coverage < 0.25:
        return None
    preview = "\n".join(
        f"[{chunk.block_id} p{chunk.page_id}] {_normalized_text(_chunk_text(chunk))[:420]}"
        for chunk in chunks
    )
    return {
        "chunk_ids": [chunk.block_id for chunk in chunks],
        "chunk_content_hashes": {
            chunk.block_id: str(chunk.metadata.get("content_hash") or "") for chunk in chunks
        },
        "pages": sorted(set().union(*(_source_pages(chunk) for chunk in chunks))),
        "block_types": [chunk.block_type for chunk in chunks],
        "match_method": method,
        "match_score": round(coverage, 4),
        "preview": preview[:1800],
    }


def _group_candidates(group: dict[str, Any], chunks: list[Chunk], *, max_window: int) -> list[dict[str, Any]]:
    pages = {int(page) for page in group.get("physical_pages") or []}
    evidence_type = str(group.get("evidence_type") or "").casefold()
    compatible = sorted(
        [
            chunk
            for chunk in chunks
            if chunk.is_indexable
            and _page_compatible(chunk, pages)
            and _type_compatible(chunk, evidence_type)
        ],
        key=_reading_order,
    )
    source_text = str(group.get("verbatim_content") or "")
    candidates: list[dict[str, Any]] = []
    for start in range(len(compatible)):
        for size in range(1, min(max_window, len(compatible) - start) + 1):
            candidate = _candidate_for_window(source_text, compatible[start : start + size])
            if candidate is not None:
                candidates.append(candidate)
    candidates.sort(
        key=lambda item: (
            -float(item["match_score"]),
            METHOD_PRIORITY[str(item["match_method"])],
            len(item["chunk_ids"]),
            item["chunk_ids"],
        )
    )
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for candidate in candidates:
        key = tuple(candidate["chunk_ids"])
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
        if len(result) == 5:
            break
    return result


def _review_class(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "unmapped"
    top = candidates[0]
    exact = top["match_method"] in {"normalized_contains", "compact_contains"}
    if not exact:
        return "fuzzy"
    if len(top["chunk_ids"]) > 1:
        return "exact_multi"
    if (
        len(candidates) > 1
        and len(candidates[1]["chunk_ids"]) == 1
        and candidates[1]["match_score"] == top["match_score"]
    ):
        return "exact_ambiguous"
    return "exact_single"


def _load_corpus(manifest_path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, list[Chunk]]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    corpus_id = str(manifest.get("corpus_id") or "")
    contract = str(manifest.get("chunk_contract_version") or "")
    if not corpus_id or not contract:
        raise ValueError("corpus manifest is missing corpus_id or chunk_contract_version")
    documents_by_file: dict[str, dict[str, Any]] = {}
    chunks_by_doc: dict[str, list[Chunk]] = {}
    for document in manifest.get("documents") or []:
        document_file = str(document.get("document_file") or "")
        doc_id = str(document.get("doc_id") or "")
        evidence_path_value = document.get("evidence_blocks_path")
        if not evidence_path_value and document.get("document_dir"):
            evidence_path_value = str(Path(str(document["document_dir"])) / "evidence_blocks.jsonl")
        if not document_file or not doc_id or not evidence_path_value:
            raise ValueError("corpus manifest contains an incomplete document")
        evidence_path = _repo_path(str(evidence_path_value))
        expected_sha = str(document.get("evidence_blocks_sha256") or "")
        if expected_sha and _sha256_file(evidence_path) != expected_sha:
            raise ValueError(f"stale evidence_blocks hash for {doc_id}")
        chunks = [Chunk.from_dict(item) for item in read_jsonl(evidence_path)]
        if not chunks:
            raise ValueError(f"document has no chunks: {doc_id}")
        missing_hashes = [chunk.block_id for chunk in chunks if not chunk.metadata.get("content_hash")]
        if missing_hashes:
            raise ValueError(f"chunks are missing content_hash: {missing_hashes[:3]}")
        documents_by_file[document_file] = {**document, "evidence_blocks_path": str(evidence_path)}
        chunks_by_doc[doc_id] = chunks
    return manifest, documents_by_file, chunks_by_doc


def build_candidates(
    *,
    samples: list[dict[str, Any]],
    manifest: dict[str, Any],
    documents_by_file: dict[str, dict[str, Any]],
    chunks_by_doc: dict[str, list[Chunk]],
    max_window: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    queue: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    corpus_id = str(manifest["corpus_id"])
    contract = str(manifest["chunk_contract_version"])
    for sample in samples:
        document_file = sample.get("document_file")
        if not document_file:
            continue
        document = documents_by_file.get(str(document_file))
        if document is None:
            raise ValueError(f"sample document is absent from corpus: {document_file}")
        doc_id = str(document["doc_id"])
        source_sha = str(document.get("source_pdf_sha256") or "")
        groups: list[dict[str, Any]] = []
        for group in sample.get("gold_evidence_groups") or []:
            group_id = str(group.get("group_id") or "")
            source_text = str(group.get("verbatim_content") or "")
            candidates = _group_candidates(group, chunks_by_doc[doc_id], max_window=max_window)
            review_class = _review_class(candidates)
            source_evidence = {
                "evidence_type": str(group.get("evidence_type") or ""),
                "physical_pages": list(group.get("physical_pages") or []),
                "source_locator": str(group.get("source_locator") or ""),
                "verbatim_content": source_text,
                "verbatim_content_sha256": _sha256_text(source_text),
            }
            group_row = {
                "group_id": group_id,
                "requirement": "required",
                "source_evidence": source_evidence,
                "candidates": candidates,
                "candidate_class": review_class,
                "review_status": "unreviewed",
                "mapping_origin": "automatic_source_alignment",
            }
            groups.append(group_row)
            queue.append(
                {
                    "sample_id": str(sample["sample_id"]),
                    "question": str(sample.get("question") or ""),
                    "document_file": str(document_file),
                    "doc_id": doc_id,
                    "corpus_id": corpus_id,
                    "chunk_contract_version": contract,
                    "source_pdf_sha256": source_sha,
                    **group_row,
                }
            )
            decisions.append(
                {
                    "sample_id": str(sample["sample_id"]),
                    "group_id": group_id,
                    "corpus_id": corpus_id,
                    "chunk_contract_version": contract,
                    "source_pdf_sha256": source_sha,
                    "decision": None,
                    "primary_chunk_ids": [],
                    "acceptable_alternative_chunk_ids": [],
                    "selected_chunk_hashes": {},
                    "reviewer": "",
                    "reviewed_at": "",
                    "rationale": "",
                }
            )
        rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "sample_id": str(sample["sample_id"]),
                "document_file": str(document_file),
                "doc_id": doc_id,
                "corpus_id": corpus_id,
                "chunk_contract_version": contract,
                "source_pdf_sha256": source_sha,
                "evidence_groups": groups,
                "minimal_required_group_ids": [group["group_id"] for group in groups],
                "review_status": "unreviewed",
            }
        )
    queue.sort(key=lambda item: (QUEUE_PRIORITY[item["candidate_class"]], item["sample_id"], item["group_id"]))
    return rows, queue, decisions


def freeze_qrels(
    candidates: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    chunks_by_doc: dict[str, list[Chunk]],
) -> list[dict[str, Any]]:
    expected = {
        (row["sample_id"], group["group_id"]): (row, group)
        for row in candidates
        for group in row["evidence_groups"]
    }
    provided: dict[tuple[str, str], dict[str, Any]] = {}
    for decision in decisions:
        key = (str(decision.get("sample_id") or ""), str(decision.get("group_id") or ""))
        if key in provided:
            raise ValueError(f"duplicate review decision: {key}")
        provided[key] = decision
    if set(provided) != set(expected):
        missing = sorted(set(expected) - set(provided))
        extra = sorted(set(provided) - set(expected))
        raise ValueError(f"review decisions do not cover candidate groups; missing={missing[:3]} extra={extra[:3]}")
    frozen_rows: list[dict[str, Any]] = []
    for row in candidates:
        chunk_map = {chunk.block_id: chunk for chunk in chunks_by_doc[row["doc_id"]]}
        frozen_groups: list[dict[str, Any]] = []
        eligible = True
        for group in row["evidence_groups"]:
            decision = provided[(row["sample_id"], group["group_id"])]
            for field in ("corpus_id", "chunk_contract_version", "source_pdf_sha256"):
                if decision.get(field) != row[field]:
                    raise ValueError(f"stale review decision binding for {row['sample_id']}/{group['group_id']}: {field}")
            action = str(decision.get("decision") or "")
            if action not in {"accept_candidate", "replace", "exclude"}:
                raise ValueError(f"invalid review decision for {row['sample_id']}/{group['group_id']}")
            if not all(str(decision.get(field) or "").strip() for field in ("reviewer", "reviewed_at", "rationale")):
                raise ValueError(f"incomplete review provenance for {row['sample_id']}/{group['group_id']}")
            primary = list(dict.fromkeys(str(value) for value in decision.get("primary_chunk_ids") or []))
            alternatives = list(
                dict.fromkeys(str(value) for value in decision.get("acceptable_alternative_chunk_ids") or [])
            )
            selected_ids = [*primary, *alternatives]
            if action == "exclude":
                if selected_ids:
                    raise ValueError("excluded evidence group cannot select chunks")
                eligible = False
            else:
                if not primary or any(block_id not in chunk_map for block_id in selected_ids):
                    raise ValueError(f"review decision selects invalid chunks for {row['sample_id']}/{group['group_id']}")
                candidate_ids = {
                    block_id
                    for candidate in group["candidates"]
                    for block_id in candidate["chunk_ids"]
                }
                if action == "accept_candidate" and not set(primary).issubset(candidate_ids):
                    raise ValueError("accept_candidate must select proposed chunk ids")
                expected_hashes = {
                    block_id: str(chunk_map[block_id].metadata["content_hash"])
                    for block_id in selected_ids
                }
                if decision.get("selected_chunk_hashes") != expected_hashes:
                    raise ValueError(f"stale selected chunk hashes for {row['sample_id']}/{group['group_id']}")
            frozen_groups.append(
                {
                    "group_id": group["group_id"],
                    "requirement": "required",
                    "source_evidence_sha256": group["source_evidence"]["verbatim_content_sha256"],
                    "primary_chunk_ids": primary,
                    "acceptable_alternative_chunk_ids": alternatives,
                    "chunk_content_hashes": dict(decision.get("selected_chunk_hashes") or {}),
                    "decision": action,
                    "review_status": "reviewed",
                    "reviewer": decision["reviewer"],
                    "reviewed_at": decision["reviewed_at"],
                    "rationale": decision["rationale"],
                }
            )
        frozen_rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "sample_id": row["sample_id"],
                "document_file": row["document_file"],
                "doc_id": row["doc_id"],
                "corpus_id": row["corpus_id"],
                "chunk_contract_version": row["chunk_contract_version"],
                "source_pdf_sha256": row["source_pdf_sha256"],
                "evidence_groups": frozen_groups,
                "minimal_required_group_ids": row["minimal_required_group_ids"],
                "review_status": "reviewed",
                "evaluation_eligible": eligible,
            }
        )
    return frozen_rows


def _artifact_manifest(run_id: str, output_dir: Path, files: list[Path]) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "command": "build_m1_chunk_qrels",
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "files": [
            {
                "path": str(path),
                "size": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
            for path in files
            if path.is_file()
        ],
        "output_dir": str(output_dir),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    sample_path = _repo_path(args.samples)
    manifest_path = _repo_path(args.corpus_manifest)
    output_dir = _repo_path(args.output_dir)
    sync_dir = _repo_path(args.sync_dir) if args.sync_dir else None
    samples = [dict(item) for item in read_jsonl(sample_path)]
    manifest, documents_by_file, chunks_by_doc = _load_corpus(manifest_path)
    candidates, queue, template = build_candidates(
        samples=samples,
        manifest=manifest,
        documents_by_file=documents_by_file,
        chunks_by_doc=chunks_by_doc,
        max_window=args.max_window,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = output_dir / "chunk_qrels_candidates.jsonl"
    queue_path = output_dir / "qrels_review_queue.jsonl"
    template_path = output_dir / "review_decisions.template.jsonl"
    write_jsonl(candidate_path, candidates)
    write_jsonl(queue_path, queue)
    write_jsonl(template_path, template)
    classes = Counter(item["candidate_class"] for item in queue)
    frozen_path = output_dir / "frozen_chunk_qrels.jsonl"
    frozen_rows: list[dict[str, Any]] = []
    if args.review_decisions:
        frozen_rows = freeze_qrels(candidates, read_jsonl(_repo_path(args.review_decisions)), chunks_by_doc)
        write_jsonl(frozen_path, frozen_rows)
    elif frozen_path.exists():
        raise ValueError("stale frozen_chunk_qrels.jsonl exists without review decisions")
    summary = {
        "schema_version": SCHEMA_VERSION,
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "corpus_id": manifest["corpus_id"],
        "chunk_contract_version": manifest["chunk_contract_version"],
        "sample_count": len(samples),
        "document_bound_sample_count": len(candidates),
        "non_document_sample_count": len(samples) - len(candidates),
        "evidence_group_count": len(queue),
        "candidate_class_counts": dict(sorted(classes.items())),
        "groups_with_candidates": sum(bool(item["candidates"]) for item in queue),
        "groups_without_candidates": sum(not item["candidates"] for item in queue),
        "reviewed_group_count": len(queue) if frozen_rows else 0,
        "frozen_sample_count": len(frozen_rows),
        "evaluation_eligible_sample_count": sum(row["evaluation_eligible"] for row in frozen_rows),
        "milestone_status": "frozen" if frozen_rows else "ready",
        "gpu_used": False,
        "llm_api_used": False,
        "mineru_api_used": False,
        "retrieval_evaluation_run": False,
    }
    summary_path = output_dir / "summary.json"
    result_path = output_dir / "result.json"
    _write_json(summary_path, summary)
    result = {
        "command": "build_m1_chunk_qrels",
        "status": "success",
        "git_commit": summary["git_commit"],
        "artifact_paths": [str(candidate_path), str(queue_path), str(template_path), str(summary_path)],
        "metrics": summary,
    }
    if frozen_rows:
        result["artifact_paths"].append(str(frozen_path))
    _write_json(result_path, result)
    preview_path = output_dir / "preview.json"
    _write_json(preview_path, queue[:10])
    manifest_output_path = output_dir / "manifest.json"
    files = [candidate_path, queue_path, template_path, summary_path, result_path, preview_path]
    if frozen_rows:
        files.append(frozen_path)
    _write_json(manifest_output_path, _artifact_manifest(args.run_id, output_dir, files))
    if sync_dir is not None:
        sync_dir.mkdir(parents=True, exist_ok=True)
        for source in (summary_path, result_path, preview_path):
            (sync_dir / source.name).write_bytes(source.read_bytes())
        summary_md = (
            "# M1-G3 qrels candidate summary\n\n"
            f"- milestone status: `{summary['milestone_status']}`\n"
            f"- corpus: `{summary['corpus_id']}`\n"
            f"- document-bound samples: {summary['document_bound_sample_count']}\n"
            f"- evidence groups: {summary['evidence_group_count']}\n"
            f"- candidate classes: `{summary['candidate_class_counts']}`\n"
            f"- groups without candidates: {summary['groups_without_candidates']}\n"
            f"- frozen qrels written: {bool(frozen_rows)}\n"
            "- GPU/API/retrieval evaluation: not used\n"
        )
        sync_summary_md = sync_dir / "summary.md"
        sync_summary_md.write_text(summary_md, encoding="utf-8")
        sync_files = [
            sync_dir / "result.json",
            sync_dir / "summary.json",
            sync_dir / "preview.json",
            sync_summary_md,
        ]
        _write_json(
            sync_dir / "manifest.json",
            _artifact_manifest(args.run_id, sync_dir, sync_files),
        )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build reviewable M1 Chunk qrels candidates")
    parser.add_argument("--samples", required=True)
    parser.add_argument("--corpus-manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--sync-dir", default="")
    parser.add_argument("--run-id", default="m1_g3_chunk_qrels")
    parser.add_argument("--max-window", type=int, default=6)
    parser.add_argument("--review-decisions", default="")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
