from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.eval.answer_metrics import normalize_text, numeric_match
from docagent.parser.parse_tatqa import convert_tatqa_question
from docagent.schemas import EvidenceBlock
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from docagent.utils.jsonl import write_jsonl
from docagent.workflow.answer_contract import MODEL_OUTPUT_V3_SCHEMA, validate_model_output_v3
from docagent.workflow.prompts import EXTRACTION_RULES_TEXT


SCRIPT_VERSION = "answer-policy-v3-training-data-v1"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "training_prep" / "answer_policy_v3"
VALIDATION_PATH_MARKERS = {"dev", "val", "valid", "validation", "test", "final_eval"}
TRAIN_SPLITS = {"train", "training"}

SYSTEM_PROMPT = (
    "You are DocAgent's final answer policy. Use only the numbered evidence candidates. "
    "Return exactly one valid JSON object with answer, supporting_refs, support_status, and reasoning_summary. "
    "Keep reasoning_summary under 300 characters."
)


def repo_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def safe_relpath(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json_list(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"expected JSON list in {path}")
    return [item for item in data if isinstance(item, dict)]


def compact_text(value: Any, limit: int = 900) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def answer_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    text = str(value).strip()
    return [text] if text else []


def answer_text(value: Any) -> str:
    return ", ".join(answer_values(value))


def _is_blank_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def text_contains_answer(text: str, answer: str) -> bool:
    if not answer:
        return False
    normalized_text = normalize_text(text)
    normalized_answer = normalize_text(answer)
    if normalized_answer and normalized_answer in normalized_text:
        return True
    return numeric_match(text, answer)


def block_display_text(block: EvidenceBlock, *, max_chars: int) -> str:
    prefix = f"{block.block_type.title()}"
    page = block.location.page if block.location.page is not None else block.page_id
    if page is not None:
        prefix = f"{prefix}, page {page}"
    text = block.retrieval_text or block.text or block.table_html or block.visual_summary or ""
    return f"{prefix}: {compact_text(text, max_chars)}"


def candidate_from_block(ref: str, block: EvidenceBlock, *, max_chars: int) -> dict[str, Any]:
    page = block.location.page if block.location.page is not None else block.page_id
    return {
        "ref": ref,
        "kind": candidate_kind(block),
        "display_text": block_display_text(block, max_chars=max_chars),
        "metadata": {
            "source_kind": "evidence_block",
            "doc_id": block.doc_id,
            "page": page,
            "block_id": block.block_id,
            "block_type": block.block_type,
        },
    }


def candidate_kind(block: EvidenceBlock) -> str:
    if block.block_type == "table":
        return "table"
    if block.block_type in {"image", "figure", "visual_summary"}:
        return "image"
    if block.block_type == "page":
        return "markdown"
    raw_type = str(block.metadata.get("raw_mineru_type") or "").lower()
    if raw_type in {"ocr", "text", "title"}:
        return "ocr"
    return "text"


def ref_map_entry(candidate: dict[str, Any]) -> dict[str, Any]:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    return {
        key: value
        for key, value in {
            "source_kind": metadata.get("source_kind"),
            "doc_id": metadata.get("doc_id"),
            "page": metadata.get("page"),
            "block_id": metadata.get("block_id"),
            "block_type": metadata.get("block_type"),
            "preview": candidate.get("display_text"),
            "derived_from_refs": metadata.get("derived_from_refs"),
            "expression": metadata.get("expression"),
            "value": metadata.get("value"),
        }.items()
        if not _is_blank_value(value)
    }


def candidate_prompt_text(candidate: dict[str, Any]) -> str:
    kind = str(candidate.get("kind") or "text").strip() or "text"
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    page = metadata.get("page")
    header = f"[{candidate['ref']}] kind={kind}"
    if kind not in {"calculation_result", "tool_observation"} and page not in {None, ""}:
        header = f"{header} page={page}"
    display_text = str(candidate.get("display_text") or "")
    if kind in {"calculation_result", "tool_observation"}:
        content = display_text.strip()
    else:
        content = re.sub(r"^[A-Za-z_ ]+(?:, page [^:]+)?:\s*", "", display_text, count=1).strip()
    return f"{header}\n{content or display_text}"


def build_prompt(question: str, candidates: list[dict[str, Any]], *, answer_type: str = "extractive") -> str:
    evidence_lines = [candidate_prompt_text(item) for item in candidates]
    output_schema = json.dumps(MODEL_OUTPUT_V3_SCHEMA, ensure_ascii=False)
    return (
        "## Task\n"
        "Answer the question from the numbered evidence candidates. Select only supporting_refs from the listed [E#] refs.\n\n"
        "## Question\n"
        f"{question}\n\n"
        "## Answer Type\n"
        f"{answer_type or 'extractive'}\n\n"
        "## Evidence Candidates\n"
        + "\n".join(evidence_lines)
        + "\n\n"
        "## Output Contract\n"
        f"Return JSON matching this schema: {output_schema}\n"
        "Rules:\n"
        f"{EXTRACTION_RULES_TEXT}\n"
        "- answer must be concise and grounded in the evidence.\n"
        "- Use only the numbered evidence candidates.\n"
        "- For supported answers, supporting_refs must contain the evidence refs that directly support the answer.\n"
        "- For insufficient evidence, use support_status=insufficient and supporting_refs=[].\n"
        "- Keep reasoning_summary under 300 characters.\n"
        "- Do not output page numbers, block ids, document ids, paths, markdown, or hidden reasoning."
    )


def build_insufficient_record(
    *,
    sample_id: str,
    source: str,
    question: str,
    candidates: list[dict[str, Any]],
    evidence_ref_map: dict[str, dict[str, Any]],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    target = make_target(
        "Insufficient evidence.",
        [],
        status="insufficient",
        reason="The provided evidence candidates do not contain enough information to answer.",
    )
    return {
        "sample_id": sample_id,
        "source": source,
        "bucket": "insufficient_confirmed",
        "board_type": "oracle_board",
        "question": question,
        "answer": "",
        "evidence_candidates": candidates,
        "target_model_output": target,
        "evidence_ref_map": evidence_ref_map,
        "alignment": {"method": "confirmed_no_answer_in_candidates", "confidence": "high"},
        "metadata": metadata,
    }


def make_target(answer: str, refs: list[str], *, status: str, reason: str) -> dict[str, Any]:
    target = {
        "answer": answer,
        "supporting_refs": refs,
        "support_status": status,
        "reasoning_summary": reason,
    }
    ok, error = validate_model_output_v3(target, allowed_refs=set(refs) if refs else set())
    if not ok:
        raise ValueError(f"invalid v3 target: {error}")
    return target


def build_sft_record(record: dict[str, Any]) -> dict[str, Any]:
    target = record["target_model_output"]
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    answer_type = "numeric" if metadata.get("derivation") or metadata.get("raw_answer_type") in {"arithmetic", "count"} else "extractive"
    return {
        "id": record["sample_id"],
        "source": record["source"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_prompt(record["question"], record["evidence_candidates"], answer_type=answer_type)},
            {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)},
        ],
        "metadata": {
            "bucket": record["bucket"],
            "board_type": record["board_type"],
            "source": record["source"],
            "evidence_context_hash": hashlib.sha256(
                json.dumps(record["evidence_candidates"], ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        },
    }


def positive_block_refs(
    sample_blocks: list[EvidenceBlock],
    candidates: list[dict[str, Any]],
    answers: list[str],
    gold_block_ids: list[str],
) -> list[str]:
    by_id = {block.block_id: block for block in sample_blocks}
    candidate_by_block = {
        str(item.get("metadata", {}).get("block_id")): str(item["ref"])
        for item in candidates
        if isinstance(item.get("metadata"), dict) and item.get("metadata", {}).get("block_id")
    }
    refs: list[str] = []
    search_blocks = [by_id[block_id] for block_id in gold_block_ids if block_id in by_id] or sample_blocks
    for block in search_blocks:
        text = block.retrieval_text or block.text or block.table_html or ""
        if any(text_contains_answer(text, answer) for answer in answers):
            ref = candidate_by_block.get(block.block_id)
            if ref:
                refs.append(ref)
    return list(dict.fromkeys(refs))


def calculation_candidate(
    ref: str,
    *,
    answer: str,
    derivation: str,
    scale: str,
    derived_from_refs: list[str],
) -> dict[str, Any]:
    scale_text = f" ({scale})" if scale else ""
    expression = compact_text(derivation, 500)
    display = f"Calculation result: {expression} = {answer}{scale_text}"
    return {
        "ref": ref,
        "kind": "calculation_result",
        "display_text": display,
        "metadata": {
            "source_kind": "calculation_result",
            "derived_from_refs": derived_from_refs,
            "expression": expression,
            "value": answer,
            "scale": scale,
        },
    }


def build_tatqa_record(
    context: dict[str, Any],
    question: dict[str, Any],
    *,
    split: str,
    max_candidates: int,
    max_candidate_chars: int,
) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
    sample = convert_tatqa_question(context, question, split=split)
    answers = answer_values(sample.answer)
    if not answers:
        return None, "unsupported_or_ambiguous", {"reason": "missing_answer", "sample_id": sample.qid}

    candidates = [
        candidate_from_block(f"E{index}", block, max_chars=max_candidate_chars)
        for index, block in enumerate(sample.evidence[:max_candidates], start=1)
    ]
    evidence_ref_map = {item["ref"]: ref_map_entry(item) for item in candidates}
    answer = answer_text(sample.answer)
    raw_answer_type = str(question.get("answer_type") or "")
    derivation = str(question.get("derivation") or "").strip()
    scale = str(question.get("scale") or "").strip()
    gold_block_ids = [str(item) for item in sample.metadata.get("gold_block_ids") or []]

    if raw_answer_type == "arithmetic" or derivation:
        if derivation:
            calc_ref = f"E{len(candidates) + 1}"
            table_refs = [item["ref"] for item in candidates if item["kind"] == "table"][:1]
            calc = calculation_candidate(
                calc_ref,
                answer=answer,
                derivation=derivation,
                scale=scale,
                derived_from_refs=table_refs,
            )
            candidates.append(calc)
            evidence_ref_map[calc_ref] = ref_map_entry(calc)
            target = make_target(
                answer,
                [calc_ref],
                status="supported",
                reason="The calculation observation gives the requested numeric answer.",
            )
            return (
                _aligned_record(sample, question, candidates, evidence_ref_map, target, "deterministic_tool_supported", "numeric_derivation"),
                "deterministic_tool_supported",
                {},
            )
        return None, "needs_tool_planning", {"reason": "arithmetic_without_derivation", "sample_id": sample.qid}

    refs = positive_block_refs(sample.evidence, candidates, answers, gold_block_ids)
    if refs:
        target = make_target(
            answer,
            refs[:2],
            status="supported",
            reason="The selected evidence candidate contains the answer.",
        )
        return (
            _aligned_record(sample, question, candidates, evidence_ref_map, target, "evidence_extractive_supported", "answer_text_match"),
            "evidence_extractive_supported",
            {},
        )

    return None, "alignment_failed", {
        "sample_id": sample.qid,
        "source": "tatqa",
        "question": sample.question,
        "answer": answer,
        "reason": "answer_not_found_in_candidate_evidence",
        "raw_answer_type": raw_answer_type,
        "answer_from": question.get("answer_from"),
    }


def _aligned_record(
    sample: Any,
    question: dict[str, Any],
    candidates: list[dict[str, Any]],
    evidence_ref_map: dict[str, dict[str, Any]],
    target: dict[str, Any],
    bucket: str,
    alignment_method: str,
) -> dict[str, Any]:
    return {
        "sample_id": sample.qid,
        "source": "tatqa",
        "bucket": bucket,
        "board_type": "oracle_board",
        "question": sample.question,
        "answer": answer_text(sample.answer),
        "evidence_candidates": candidates,
        "target_model_output": target,
        "evidence_ref_map": evidence_ref_map,
        "alignment": {
            "method": alignment_method,
            "confidence": "high",
        },
        "metadata": {
            "doc_id": sample.doc_id,
            "split": sample.split,
            "scale": sample.metadata.get("scale"),
            "derivation": sample.metadata.get("derivation"),
            "answer_from": sample.metadata.get("answer_from"),
            "raw_answer_type": sample.metadata.get("raw_answer_type"),
            "source_question_uid": question.get("uid"),
        },
    }


def validation_path_markers(path: Path) -> list[str]:
    markers: list[str] = []
    for part in path.parts:
        normalized = part.lower().replace("-", "_")
        if normalized in VALIDATION_PATH_MARKERS:
            markers.append(part)
    return markers


def block_page(block: EvidenceBlock) -> int | None:
    if block.location.page is not None:
        return int(block.location.page)
    if block.page_id is not None:
        return int(block.page_id)
    return None


def mpdocvqa_candidate_blocks(blocks: list[EvidenceBlock], gold_pages: list[int], max_candidates: int) -> list[EvidenceBlock]:
    gold_page_set = {int(page) for page in gold_pages}
    child_blocks = [block for block in blocks if block.block_type != "page" and block_page(block) in gold_page_set]
    page_blocks = [block for block in blocks if block.block_type == "page" and block_page(block) in gold_page_set]
    other_blocks = [block for block in blocks if block.block_type != "page" and block_page(block) not in gold_page_set]
    ordered: list[EvidenceBlock] = []
    seen: set[str] = set()
    for block in [*child_blocks, *page_blocks, *other_blocks]:
        if block.block_id in seen:
            continue
        text = block.retrieval_text or block.text or block.table_html or block.visual_summary or ""
        if not text.strip():
            continue
        seen.add(block.block_id)
        ordered.append(block)
        if len(ordered) >= max_candidates:
            break
    return ordered


def build_mpdocvqa_record(
    manifest: dict[str, Any],
    blocks: list[EvidenceBlock],
    *,
    max_candidates: int,
    max_candidate_chars: int,
) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
    sample_id = str(manifest.get("sample_id") or "")
    answers = answer_values(manifest.get("answers"))
    if not answers:
        return None, "unsupported_or_ambiguous", {"reason": "missing_answer", "sample_id": sample_id}
    if not manifest.get("evidence_ready"):
        return None, "alignment_failed", {"reason": "evidence_not_ready", "sample_id": sample_id}

    gold_pages = []
    for value in manifest.get("gold_pages") or []:
        try:
            gold_pages.append(int(value))
        except (TypeError, ValueError):
            continue
    if not gold_pages:
        return None, "alignment_failed", {"reason": "missing_gold_pages", "sample_id": sample_id}

    candidates = [
        candidate_from_block(f"E{index}", block, max_chars=max_candidate_chars)
        for index, block in enumerate(mpdocvqa_candidate_blocks(blocks, gold_pages, max_candidates), start=1)
    ]
    evidence_ref_map = {item["ref"]: ref_map_entry(item) for item in candidates}
    refs: list[str] = []
    for candidate in candidates:
        display = str(candidate.get("display_text") or "")
        if any(text_contains_answer(display, answer) for answer in answers):
            refs.append(str(candidate["ref"]))
    refs = list(dict.fromkeys(refs))
    if not refs:
        return None, "alignment_failed", {
            "reason": "answer_not_found_in_candidate_evidence",
            "sample_id": sample_id,
            "question": manifest.get("question"),
            "answers": answers,
            "gold_pages": gold_pages,
            "candidate_count": len(candidates),
        }

    answer = answer_text(answers)
    target = make_target(
        answer,
        refs[:2],
        status="supported",
        reason="The selected evidence candidate contains the answer on the answer page.",
    )
    return (
        {
            "sample_id": sample_id,
            "source": "mp_docvqa",
            "bucket": "evidence_extractive_supported",
            "board_type": "oracle_board",
            "question": str(manifest.get("question") or ""),
            "answer": answer,
            "evidence_candidates": candidates,
            "target_model_output": target,
            "evidence_ref_map": evidence_ref_map,
            "alignment": {
                "method": "answer_text_match_on_gold_page_candidates",
                "confidence": "high",
            },
            "metadata": {
                "doc_id": str(manifest.get("ingested_doc_id") or ""),
                "source_doc_id": str(manifest.get("doc_id") or ""),
                "split": str(manifest.get("split") or ""),
                "gold_pages": gold_pages,
                "source_document": str(manifest.get("source_document") or ""),
                "expected_tools": manifest.get("expected_tools") or [],
            },
        },
        "evidence_extractive_supported",
        {},
    )


def build_answer_policy_v3_mpdocvqa_data(
    *,
    evidence_manifest: str | Path,
    db_path: str | Path,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    run_id: str = "answer_policy_v3_mpdocvqa_trial",
    split: str = "train",
    limit: int = 100,
    max_candidates: int = 8,
    max_candidate_chars: int = 900,
    allow_non_train_source: bool = False,
) -> dict[str, Any]:
    manifest_path = repo_path(evidence_manifest)
    sqlite_path = repo_path(db_path)
    artifact_dir = repo_path(output_root) / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    paths = artifact_paths(artifact_dir)

    block_reasons: list[str] = []
    if not allow_non_train_source:
        markers = [*validation_path_markers(manifest_path), *validation_path_markers(sqlite_path)]
        if markers:
            block_reasons.append(f"validation_like_input_path:{','.join(dict.fromkeys(markers))}")
    if not manifest_path.is_file():
        block_reasons.append(f"missing_evidence_manifest:{safe_relpath(manifest_path)}")
    if not sqlite_path.is_file():
        block_reasons.append(f"missing_db_path:{safe_relpath(sqlite_path)}")
    if block_reasons:
        write_empty_artifacts(paths)
        summary = _summary(
            status="blocked",
            run_id=run_id,
            artifact_dir=artifact_dir,
            raw_path=manifest_path,
            split=split,
            limit=limit,
            counts={},
            block_reasons=block_reasons,
            aligned=[],
            rejected_count=0,
            source="mp_docvqa",
            db_path=sqlite_path,
        )
        _write_summary(paths, summary)
        return summary

    rows = load_rows(manifest_path)
    row_splits = sorted({str(row.get("split") or "") for row in rows if row.get("split")})
    if not allow_non_train_source and any(row_split.lower() not in TRAIN_SPLITS for row_split in row_splits):
        block_reasons.append(f"non_train_manifest_splits:{','.join(row_splits)}")
    if block_reasons:
        write_empty_artifacts(paths)
        summary = _summary(
            status="blocked",
            run_id=run_id,
            artifact_dir=artifact_dir,
            raw_path=manifest_path,
            split=split,
            limit=limit,
            counts={},
            block_reasons=block_reasons,
            aligned=[],
            rejected_count=0,
            source="mp_docvqa",
            db_path=sqlite_path,
        )
        _write_summary(paths, summary)
        return summary

    conn = connect(sqlite_path)
    try:
        repository = DocumentRepository(conn)
        blocks_by_doc: dict[str, list[EvidenceBlock]] = {}
        aligned: list[dict[str, Any]] = []
        alignment_failed: list[dict[str, Any]] = []
        needs_tool_planning: list[dict[str, Any]] = []
        unsupported: list[dict[str, Any]] = []
        counts = Counter()
        scanned = 0
        for row in rows:
            if len(aligned) >= limit:
                break
            scanned += 1
            doc_id = str(row.get("ingested_doc_id") or "")
            if doc_id not in blocks_by_doc:
                blocks_by_doc[doc_id] = repository.load_evidence_blocks(doc_id, include_page_blocks=True) if doc_id else []
            record, bucket, rejected = build_mpdocvqa_record(
                row,
                blocks_by_doc.get(doc_id, []),
                max_candidates=max_candidates,
                max_candidate_chars=max_candidate_chars,
            )
            counts[bucket] += 1
            if record is not None:
                aligned.append(record)
            elif bucket == "alignment_failed":
                alignment_failed.append(rejected)
            elif bucket == "needs_tool_planning":
                needs_tool_planning.append(rejected)
            else:
                unsupported.append(rejected)
    finally:
        conn.close()

    sft_records = [build_sft_record(record) for record in aligned]
    write_training_artifacts(paths, aligned, sft_records, alignment_failed, needs_tool_planning, unsupported)
    summary = _summary(
        status="success",
        run_id=run_id,
        artifact_dir=artifact_dir,
        raw_path=manifest_path,
        split=split,
        limit=limit,
        counts={**dict(sorted(counts.items())), "raw_question_count_scanned": scanned},
        block_reasons=[],
        aligned=aligned,
        rejected_count=len(alignment_failed) + len(needs_tool_planning) + len(unsupported),
        source="mp_docvqa",
        db_path=sqlite_path,
    )
    _write_summary(paths, summary)
    return summary


def artifact_paths(artifact_dir: Path) -> dict[str, Path]:
    return {
        "aligned": artifact_dir / "aligned_records.jsonl",
        "sft": artifact_dir / "sft_train.jsonl",
        "alignment_failed": artifact_dir / "alignment_failed.jsonl",
        "needs_tool_planning": artifact_dir / "needs_tool_planning.jsonl",
        "insufficient": artifact_dir / "insufficient_evidence.jsonl",
        "unsupported": artifact_dir / "unsupported_or_ambiguous.jsonl",
        "summary": artifact_dir / "summary.json",
        "summary_md": artifact_dir / "summary.md",
        "preview": artifact_dir / "preview.json",
        "manifest": artifact_dir / "manifest.json",
    }


def write_empty_artifacts(paths: dict[str, Path]) -> None:
    for key in ("aligned", "sft", "alignment_failed", "needs_tool_planning", "insufficient", "unsupported"):
        write_jsonl(paths[key], [])
    write_json(paths["preview"], {"aligned": [], "sft": [], "alignment_failed": []})


def write_training_artifacts(
    paths: dict[str, Path],
    aligned: list[dict[str, Any]],
    sft_records: list[dict[str, Any]],
    alignment_failed: list[dict[str, Any]],
    needs_tool_planning: list[dict[str, Any]],
    unsupported: list[dict[str, Any]],
) -> None:
    write_jsonl(paths["aligned"], aligned)
    write_jsonl(paths["sft"], sft_records)
    write_jsonl(paths["alignment_failed"], alignment_failed)
    write_jsonl(paths["needs_tool_planning"], needs_tool_planning)
    write_jsonl(paths["insufficient"], [])
    write_jsonl(paths["unsupported"], unsupported)
    write_json(paths["preview"], {"aligned": aligned[:3], "sft": sft_records[:2], "alignment_failed": alignment_failed[:3]})


def load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
    return rows


def build_answer_policy_v3_tatqa_data(
    *,
    tatqa_raw: str | Path,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    run_id: str = "answer_policy_v3_tatqa_trial",
    split: str = "train",
    limit: int = 300,
    max_candidates: int = 8,
    max_candidate_chars: int = 900,
    allow_non_train_source: bool = False,
) -> dict[str, Any]:
    raw_path = repo_path(tatqa_raw)
    artifact_dir = repo_path(output_root) / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    paths = artifact_paths(artifact_dir)

    block_reasons: list[str] = []
    if not allow_non_train_source:
        if split.lower() not in TRAIN_SPLITS:
            block_reasons.append(f"non_train_split:{split}")
        markers = validation_path_markers(raw_path)
        if markers:
            block_reasons.append(f"validation_like_input_path:{','.join(markers)}")

    if block_reasons:
        write_empty_artifacts(paths)
        summary = _summary(
            status="blocked",
            run_id=run_id,
            artifact_dir=artifact_dir,
            raw_path=raw_path,
            split=split,
            limit=limit,
            counts={},
            block_reasons=block_reasons,
            aligned=[],
            rejected_count=0,
        )
        _write_summary(paths, summary)
        return summary

    records = load_json_list(raw_path)
    aligned: list[dict[str, Any]] = []
    alignment_failed: list[dict[str, Any]] = []
    needs_tool_planning: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    counts = Counter()
    raw_question_count = 0

    for context in records:
        for question in context.get("questions") or []:
            if len(aligned) >= limit:
                break
            if not isinstance(question, dict):
                counts["unsupported_or_ambiguous"] += 1
                unsupported.append({"reason": "invalid_question_record"})
                continue
            raw_question_count += 1
            try:
                record, bucket, rejected = build_tatqa_record(
                    context,
                    question,
                    split=split,
                    max_candidates=max_candidates,
                    max_candidate_chars=max_candidate_chars,
                )
            except Exception as exc:
                bucket = "unsupported_or_ambiguous"
                record = None
                rejected = {"reason": f"{type(exc).__name__}: {exc}", "question": question.get("question")}
            counts[bucket] += 1
            if record is not None:
                aligned.append(record)
            elif bucket == "alignment_failed":
                alignment_failed.append(rejected)
            elif bucket == "needs_tool_planning":
                needs_tool_planning.append(rejected)
            else:
                unsupported.append(rejected)
        if len(aligned) >= limit:
            break

    sft_records = [build_sft_record(record) for record in aligned]
    write_training_artifacts(paths, aligned, sft_records, alignment_failed, needs_tool_planning, unsupported)

    summary = _summary(
        status="success",
        run_id=run_id,
        artifact_dir=artifact_dir,
        raw_path=raw_path,
        split=split,
        limit=limit,
        counts={**dict(sorted(counts.items())), "raw_question_count_scanned": raw_question_count},
        block_reasons=[],
        aligned=aligned,
        rejected_count=len(alignment_failed) + len(needs_tool_planning) + len(unsupported),
    )
    _write_summary(paths, summary)
    return summary


def _summary(
    *,
    status: str,
    run_id: str,
    artifact_dir: Path,
    raw_path: Path,
    split: str,
    limit: int,
    counts: dict[str, int],
    block_reasons: list[str],
    aligned: list[dict[str, Any]],
    rejected_count: int,
    source: str = "tatqa",
    db_path: Path | None = None,
) -> dict[str, Any]:
    bucket_counts = Counter(record["bucket"] for record in aligned)
    summary = {
        "command": "build_answer_policy_v3_training_data",
        "status": status,
        "script_version": SCRIPT_VERSION,
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "source": source,
        "source_path": safe_relpath(raw_path),
        "split": split,
        "limit": limit,
        "aligned_record_count": len(aligned),
        "sft_record_count": len(aligned),
        "rejected_record_count": rejected_count,
        "bucket_counts": dict(sorted(bucket_counts.items())),
        "scan_counts": counts,
        "block_reasons": block_reasons,
        "used_training": False,
        "training_started": False,
        "used_qwen": False,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
    }
    if source == "tatqa":
        summary["tatqa_raw"] = safe_relpath(raw_path)
    if db_path is not None:
        summary["db_path"] = safe_relpath(db_path)
    if source == "mp_docvqa":
        summary["mpdocvqa_evidence_manifest"] = safe_relpath(raw_path)
        summary["mpdocvqa_db_path"] = safe_relpath(db_path) if db_path is not None else ""
    return summary


def _write_summary(paths: dict[str, Path], summary: dict[str, Any]) -> None:
    artifact_paths = [paths[key] for key in ("aligned", "sft", "alignment_failed", "needs_tool_planning", "insufficient", "unsupported", "preview", "summary", "summary_md")]
    summary["artifact_paths"] = [safe_relpath(path) for path in [*artifact_paths, paths["manifest"]]]
    write_json(paths["summary"], summary)
    paths["summary_md"].write_text(_summary_markdown(summary), encoding="utf-8")
    manifest_artifacts = [_artifact_entry(path) for path in artifact_paths if path.exists()]
    manifest = {
        "status": summary["status"],
        "run_id": summary["run_id"],
        "script_version": SCRIPT_VERSION,
        "artifact_count": len(manifest_artifacts),
        "artifacts": manifest_artifacts,
        "used_training": False,
        "training_started": False,
        "validation_subset_used_for_training": False,
        "formal_benchmark_acceptance": False,
    }
    write_json(paths["manifest"], manifest)


def _artifact_entry(path: Path) -> dict[str, Any]:
    return {"path": safe_relpath(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# AnswerPolicy v3 Training Data Trial",
        "",
        f"- status: `{summary['status']}`",
        f"- run_id: `{summary['run_id']}`",
        f"- aligned_record_count: `{summary['aligned_record_count']}`",
        f"- sft_record_count: `{summary['sft_record_count']}`",
        f"- rejected_record_count: `{summary['rejected_record_count']}`",
        f"- used_training: `{str(summary['used_training']).lower()}`",
        f"- validation_subset_used_for_training: `{str(summary['validation_subset_used_for_training']).lower()}`",
    ]
    if summary.get("block_reasons"):
        lines.extend(["", "## Block Reasons"])
        lines.extend(f"- `{reason}`" for reason in summary["block_reasons"])
    lines.extend(["", "## Buckets"])
    for bucket, count in (summary.get("bucket_counts") or {}).items():
        lines.append(f"- {bucket}: {count}")
    lines.extend(
        [
            "",
            "This is training-data preparation only. It does not call Qwen, run SFT/GRPO, use VLM, or claim benchmark acceptance.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build small high-confidence AnswerPolicy v3 SFT data.")
    parser.add_argument("--source", choices=["tatqa", "mpdocvqa"], default="tatqa")
    parser.add_argument("--tatqa-raw", default="data/benchmark/tatqa/tatqa_dataset_train.json")
    parser.add_argument("--mpdocvqa-evidence-manifest")
    parser.add_argument("--mpdocvqa-db-path")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id", default="answer_policy_v3_tatqa_trial")
    parser.add_argument("--split", default="train")
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--max-candidates", type=int, default=8)
    parser.add_argument("--max-candidate-chars", type=int, default=900)
    parser.add_argument("--allow-non-train-source", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.source == "mpdocvqa":
        if not args.mpdocvqa_evidence_manifest or not args.mpdocvqa_db_path:
            result = {
                "command": "build_answer_policy_v3_training_data",
                "status": "blocked",
                "block_reasons": ["mpdocvqa_requires_evidence_manifest_and_db_path"],
                "used_training": False,
                "training_started": False,
                "formal_benchmark_acceptance": False,
                "validation_subset_used_for_training": False,
            }
        else:
            result = build_answer_policy_v3_mpdocvqa_data(
                evidence_manifest=args.mpdocvqa_evidence_manifest,
                db_path=args.mpdocvqa_db_path,
                output_root=args.output_root,
                run_id=args.run_id,
                split=args.split,
                limit=args.limit,
                max_candidates=args.max_candidates,
                max_candidate_chars=args.max_candidate_chars,
                allow_non_train_source=bool(args.allow_non_train_source),
            )
    else:
        result = build_answer_policy_v3_tatqa_data(
            tatqa_raw=args.tatqa_raw,
            output_root=args.output_root,
            run_id=args.run_id,
            split=args.split,
            limit=args.limit,
            max_candidates=args.max_candidates,
            max_candidate_chars=args.max_candidate_chars,
            allow_non_train_source=bool(args.allow_non_train_source),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
