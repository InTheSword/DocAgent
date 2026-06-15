from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.eval.phase3_focused import corpus_hash, qid_hash, stable_sample_key, validate_benchmark_contract
from docagent.schemas import DocAgentSample, EvidenceBlock, EvidenceLocation
from docagent.utils.jsonl import read_jsonl, write_jsonl


class BuildError(RuntimeError):
    pass


@dataclass
class BuildInputs:
    source_imdb: Path
    source_ocr_root: Path | None
    source_qa: Path | None
    split: str
    limit: int | None
    seed: str


@dataclass
class BuildResult:
    qa_records: list[dict[str, Any]]
    corpus_blocks: list[EvidenceBlock]
    manifest: dict[str, Any]
    errors: list[str] = field(default_factory=list)


def repo_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def parse_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if hasattr(value, "tolist"):
        converted = value.tolist()
        return converted if isinstance(converted, list) else [converted]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = ast.literal_eval(stripped)
            except (SyntaxError, ValueError):
                return [value]
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, tuple):
                return list(parsed)
        return [value]
    return [value]


def safe_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, list):
        value = value[0] if value else None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def load_imdb_records(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        return read_jsonl(path)
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("data", "records", "questions"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        raise BuildError(f"unsupported JSON source-imdb payload: {path}")
    if suffix == ".npy":
        import numpy as np

        array = np.load(path, allow_pickle=True)
        records = []
        for item in array[1:]:
            if hasattr(item, "item"):
                item = item.item()
            if isinstance(item, dict):
                records.append(item)
        return records
    raise BuildError(f"unsupported source-imdb extension: {path.suffix}")


def load_qa_samples(path: Path | None) -> list[DocAgentSample]:
    if path is None:
        return []
    return [DocAgentSample.from_dict(record) for record in read_jsonl(path)]


def extra_info(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("extra_info")
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                parsed = ast.literal_eval(stripped)
            except (SyntaxError, ValueError):
                return {}
            return parsed if isinstance(parsed, dict) else {}
    return {}


def record_qid(record: dict[str, Any]) -> str:
    return str(record.get("question_id") or record.get("questionId") or record.get("qid") or record.get("id") or "").strip()


def record_doc_id(record: dict[str, Any]) -> str:
    info = extra_info(record)
    return str(
        record.get("doc_id")
        or record.get("document_id")
        or record.get("image_id")
        or info.get("ucsf_doc_id")
        or record_qid(record)
    ).strip()


def answer_candidates(record: dict[str, Any]) -> list[str]:
    values = parse_list(record.get("valid_answers") or record.get("answers") or record.get("answer"))
    candidates = []
    for value in values:
        text = str(value).strip()
        if text and text not in candidates:
            candidates.append(text)
    return candidates


def normalize_page_id(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("page_id", "image_name", "image_id", "image", "file_name", "filename", "id", "page"):
            if key in value:
                normalized = normalize_page_id(value[key])
                if normalized:
                    return normalized
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("\\", "/").split("/")[-1]
    suffix = Path(text).suffix
    if suffix:
        text = text[: -len(suffix)]
    return text.strip()


def page_ids_from_value(value: Any) -> list[str]:
    page_ids = []
    for item in parse_list(value):
        if isinstance(item, (list, tuple)) or hasattr(item, "tolist"):
            page_ids.extend(page_ids_from_value(item))
        else:
            page_id = normalize_page_id(item)
            if page_id:
                page_ids.append(page_id)
    return page_ids


def selected_page_ids(record: dict[str, Any]) -> list[str]:
    return page_ids_from_value(record.get("image_name") or record.get("image_names"))


def declared_doc_page_ids(record: dict[str, Any]) -> tuple[list[str], str]:
    for key in ("imdb_doc_pages", "doc_pages", "document_pages", "page_ids"):
        pages = page_ids_from_value(record.get(key))
        if pages:
            return pages, key
    pages = selected_page_ids(record)
    return pages, "image_name"


def total_doc_pages(record: dict[str, Any], page_ids: list[str]) -> int | None:
    return safe_int(record.get("total_doc_pages") or record.get("num_pages") or record.get("page_count"))


PAGE_ID_RE = re.compile(r"(?:^|[_-])p(?:age)?[_-]?(\d+)(?:$|[_-])", re.IGNORECASE)


def page_number(page_id: str, fallback_index: int) -> int:
    match = PAGE_ID_RE.search(page_id)
    if match:
        return int(match.group(1))
    return fallback_index + 1


def block_id_for_page(page_id: str) -> str:
    return f"{page_id}_official_ocr"


def text_from_ocr_payload(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    if hasattr(value, "tolist"):
        return text_from_ocr_payload(value.tolist())
    if isinstance(value, dict):
        for key in ("text", "ocr_text", "page_text", "line_text", "word", "token"):
            direct = value.get(key)
            if isinstance(direct, str) and direct.strip():
                return re.sub(r"\s+", " ", direct).strip()
        parts = []
        for key in ("ocr_tokens", "tokens", "words", "lines", "text_lines", "cells"):
            if key in value:
                text = text_from_ocr_payload(value[key])
                if text:
                    parts.append(text)
        return " ".join(parts).strip()
    if isinstance(value, list):
        parts = [text_from_ocr_payload(item) for item in value]
        return " ".join(part for part in parts if part).strip()
    return str(value).strip()


def record_ocr_text_by_page(record: dict[str, Any], doc_pages: list[str]) -> dict[str, str]:
    selected_pages = selected_page_ids(record)
    raw_pages = parse_list(record.get("ocr_tokens") or record.get("ocr") or record.get("ocr_lines"))
    if not raw_pages:
        return {}
    target_pages: list[str]
    if len(raw_pages) == len(doc_pages):
        target_pages = doc_pages
    elif selected_pages and len(raw_pages) == len(selected_pages):
        target_pages = selected_pages
    elif len(raw_pages) == 1 and selected_pages:
        target_pages = [selected_pages[0]]
    else:
        return {}
    return {
        page_id: text_from_ocr_payload(raw_pages[index])
        for index, page_id in enumerate(target_pages)
        if index < len(raw_pages)
    }


class OcrRootReader:
    def __init__(self, root: Path | None) -> None:
        self.root = root
        self._index: dict[str, Path] | None = None

    def read_page(self, *, doc_id: str, page_id: str) -> str:
        if self.root is None:
            return ""
        for candidate in self._direct_candidates(doc_id=doc_id, page_id=page_id):
            if candidate.is_file():
                return self._read_candidate(candidate)
        path = self._indexed_candidates().get(page_id)
        if path is not None:
            return self._read_candidate(path)
        return ""

    def _direct_candidates(self, *, doc_id: str, page_id: str) -> list[Path]:
        assert self.root is not None
        stems = [page_id, f"{page_id}_ocr", f"{doc_id}_{page_id}"]
        dirs = [self.root, self.root / doc_id, self.root / "ocr", self.root / "official_ocr"]
        return [
            directory / f"{stem}{suffix}"
            for directory in dirs
            for stem in stems
            for suffix in (".json", ".jsonl", ".txt")
        ]

    def _indexed_candidates(self) -> dict[str, Path]:
        if self._index is not None:
            return self._index
        self._index = {}
        if self.root is None or not self.root.is_dir():
            return self._index
        for path in self.root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".json", ".jsonl", ".txt"}:
                continue
            stem = path.stem
            self._index.setdefault(stem, path)
            if stem.endswith("_ocr"):
                self._index.setdefault(stem[:-4], path)
        return self._index

    def _read_candidate(self, path: Path) -> str:
        if path.suffix.lower() == ".txt":
            return re.sub(r"\s+", " ", path.read_text(encoding="utf-8-sig", errors="replace")).strip()
        if path.suffix.lower() == ".jsonl":
            records = read_jsonl(path)
            return text_from_ocr_payload(records)
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return text_from_ocr_payload(payload)


def source_qa_gold_ids(sample: DocAgentSample) -> list[str]:
    return [str(item) for item in sample.metadata.get("gold_block_ids") or [] if str(item).strip()]


def record_gold_ids(record: dict[str, Any]) -> list[str]:
    explicit = [str(item) for item in parse_list(record.get("gold_block_ids")) if str(item).strip()]
    if explicit:
        return explicit
    answer_page_idx = safe_int(record.get("answer_page_idx"))
    if answer_page_idx is None:
        return []
    pages = selected_page_ids(record)
    if not pages or answer_page_idx < 0 or answer_page_idx >= len(pages):
        return []
    return [block_id_for_page(pages[answer_page_idx])]


def build_qa_record(
    *,
    sample: DocAgentSample | None,
    record: dict[str, Any],
    doc_id: str,
    split: str,
    gold_block_ids: list[str],
    gold_pages: list[int],
) -> dict[str, Any]:
    answer = sample.answer if sample is not None else (answer_candidates(record)[0] if answer_candidates(record) else "")
    qid = sample.qid if sample is not None else record_qid(record)
    source = sample.source if sample is not None else "mp_docvqa"
    return {
        "qid": qid,
        "source": source,
        "doc_id": doc_id,
        "question": sample.question if sample is not None else str(record.get("question") or "").strip(),
        "answer": answer,
        "answer_type": sample.answer_type if sample is not None else "extractive",
        "evidence": [],
        "verifiable": sample.verifiable if sample is not None else bool(answer),
        "split": split,
        "gold_block_ids": gold_block_ids,
        "gold_pages": gold_pages,
        "metadata": {
            "gold_block_ids": gold_block_ids,
            "gold_pages": gold_pages,
            "corpus_artifact_role": "query_independent_retrieval_qa",
            "source_record": "mp_docvqa_imdb",
        },
    }


def git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


def page_coverage(doc_page_ids: dict[str, list[str]], totals_by_doc: dict[str, int | None]) -> dict[str, Any]:
    values: list[float] = []
    missing_total = 0
    missing_pages = 0
    for doc_id, pages in doc_page_ids.items():
        total = totals_by_doc.get(doc_id)
        if not total:
            missing_total += 1
            continue
        missing = max(total - len(pages), 0)
        missing_pages += missing
        values.append(min(len(pages) / total, 1.0))
    return {
        "document_count_with_declared_total": len(values),
        "document_count_missing_declared_total": missing_total,
        "mean": sum(values) / len(values) if values else None,
        "full_page_coverage_count": sum(1 for value in values if value >= 1.0),
        "full_page_coverage_denominator": len(values),
        "missing_page_count_against_declared_total": missing_pages,
    }


def select_records(
    *,
    imdb_by_qid: dict[str, dict[str, Any]],
    qa_samples: list[DocAgentSample],
    limit: int | None,
    seed: str,
) -> list[tuple[str, dict[str, Any], DocAgentSample | None]]:
    if qa_samples:
        qids = [sample.qid for sample in qa_samples]
    else:
        qids = sorted(imdb_by_qid)
    ordered_qids = sorted(qids, key=lambda qid: (stable_sample_key(qid, seed), qid))
    if limit is not None:
        ordered_qids = ordered_qids[:limit]
    sample_by_qid = {sample.qid: sample for sample in qa_samples}
    selected = []
    missing = []
    for qid in ordered_qids:
        record = imdb_by_qid.get(qid)
        if record is None:
            missing.append(qid)
            continue
        selected.append((qid, record, sample_by_qid.get(qid)))
    if missing:
        raise BuildError(f"source-imdb is missing {len(missing)} source-qa qids: {missing[:10]}")
    return selected


def build_benchmark(inputs: BuildInputs) -> BuildResult:
    imdb_records = load_imdb_records(inputs.source_imdb)
    imdb_by_qid = {record_qid(record): record for record in imdb_records if record_qid(record)}
    if len(imdb_by_qid) != len([record for record in imdb_records if record_qid(record)]):
        raise BuildError("duplicate qid in source-imdb")
    qa_samples = load_qa_samples(inputs.source_qa)
    if len({sample.qid for sample in qa_samples}) != len(qa_samples):
        raise BuildError("duplicate qid in source-qa")

    selected = select_records(imdb_by_qid=imdb_by_qid, qa_samples=qa_samples, limit=inputs.limit, seed=inputs.seed)
    ocr_root = OcrRootReader(inputs.source_ocr_root)
    doc_pages: dict[str, list[str]] = {}
    doc_page_source: dict[str, str] = {}
    totals_by_doc: dict[str, int | None] = {}
    text_by_doc_page: dict[tuple[str, str], str] = {}
    pending_qa: list[tuple[DocAgentSample | None, dict[str, Any], str, list[str]]] = []
    errors: list[str] = []

    for qid, record, sample in selected:
        doc_id = sample.doc_id if sample is not None else record_doc_id(record)
        if not doc_id:
            errors.append(f"{qid}: missing doc_id")
            continue
        pages, page_source = declared_doc_page_ids(record)
        if not pages:
            errors.append(f"{qid}: missing complete document page list")
            continue
        if len(pages) != len(set(pages)):
            errors.append(f"{qid}: duplicate page id in document page list")
            continue
        total = total_doc_pages(record, pages)
        if page_source == "image_name" and total is not None and len(pages) < total:
            errors.append(f"{qid}: image_name page list is incomplete ({len(pages)}/{total})")
            continue
        if total is not None and len(pages) < total:
            errors.append(f"{qid}: document page list is incomplete ({len(pages)}/{total})")
            continue
        existing_pages = doc_pages.get(doc_id)
        if existing_pages is not None and existing_pages != pages:
            errors.append(f"{qid}: conflicting document page list for doc_id={doc_id}")
            continue
        doc_pages[doc_id] = pages
        doc_page_source[doc_id] = page_source
        totals_by_doc[doc_id] = total
        for page_id, text in record_ocr_text_by_page(record, pages).items():
            if text:
                text_by_doc_page[(doc_id, page_id)] = text
        gold_ids = source_qa_gold_ids(sample) if sample is not None else record_gold_ids(record)
        if not gold_ids:
            errors.append(f"{qid}: missing gold_block_ids; builder does not infer gold from answer text")
            continue
        pending_qa.append((sample, record, doc_id, gold_ids))

    corpus_blocks: list[EvidenceBlock] = []
    seen_block_ids: set[str] = set()
    block_pages: dict[str, int] = {}
    for doc_id in sorted(doc_pages):
        for index, page_id in enumerate(doc_pages[doc_id]):
            block_id = block_id_for_page(page_id)
            if block_id in seen_block_ids:
                errors.append(f"duplicate block_id: {block_id}")
                continue
            seen_block_ids.add(block_id)
            text = text_by_doc_page.get((doc_id, page_id)) or ocr_root.read_page(doc_id=doc_id, page_id=page_id)
            if not text:
                errors.append(f"missing OCR text for doc_id={doc_id} page_id={page_id}")
                continue
            page = page_number(page_id, index)
            block_pages[block_id] = page
            corpus_blocks.append(
                EvidenceBlock(
                    doc_id=doc_id,
                    page_id=page,
                    block_id=block_id,
                    block_type="text",
                    text=text,
                    location=EvidenceLocation(page=page, block_id=block_id),
                    metadata={
                        "ocr_backend": "official_imdb_ocr",
                        "reading_order": index,
                        "page_id": page_id,
                        "source_page_list": doc_page_source.get(doc_id),
                    },
                )
            )

    qa_records = []
    for sample, record, doc_id, gold_ids in pending_qa:
        missing_gold = [block_id for block_id in gold_ids if block_id not in block_pages]
        if missing_gold:
            qid = sample.qid if sample is not None else record_qid(record)
            errors.append(f"{qid}: gold block not found in corpus: {missing_gold[:5]}")
            continue
        gold_pages = [block_pages[block_id] for block_id in gold_ids]
        qa_records.append(
            build_qa_record(
                sample=sample,
                record=record,
                doc_id=doc_id,
                split=inputs.split,
                gold_block_ids=gold_ids,
                gold_pages=gold_pages,
            )
        )

    doc_ids = {record["doc_id"] for record in qa_records}
    active_doc_pages = {doc_id: pages for doc_id, pages in doc_pages.items() if doc_id in doc_ids}
    block_count = len(corpus_blocks)
    gold_total = len(qa_records)
    gold_covered = sum(
        1
        for record in qa_records
        if set(record["metadata"]["gold_block_ids"]).issubset({block.block_id for block in corpus_blocks if block.doc_id == record["doc_id"]})
    )
    manifest = {
        "benchmark_id": "phase3_mpdocvqa_retrieval",
        "source_dataset": "MP-DocVQA RRC IMDb official OCR",
        "split": inputs.split,
        "construction_method": "source-qa qids and gold ids plus query-independent full document official OCR page blocks",
        "source_artifact": {
            "source_imdb": str(inputs.source_imdb),
            "source_ocr_root": str(inputs.source_ocr_root) if inputs.source_ocr_root else None,
            "source_qa": str(inputs.source_qa) if inputs.source_qa else None,
        },
        "qa_artifact": None,
        "corpus_artifact": None,
        "corpus_source": "canonical_official_imdb_ocr",
        "corpus_is_query_independent": True,
        "one_corpus_signature_per_doc": True,
        "sample_count": len(qa_records),
        "document_count": len(doc_ids),
        "block_count": block_count,
        "page_count": block_count,
        "page_coverage": page_coverage(active_doc_pages, totals_by_doc),
        "gold_block_coverage": {
            "covered_count": gold_covered,
            "total_count": gold_total,
            "coverage_rate": gold_covered / gold_total if gold_total else 0.0,
        },
        "qid_hash": qid_hash([record["qid"] for record in qa_records]),
        "corpus_hash": corpus_hash(corpus_blocks),
        "sampling_seed": inputs.seed,
        "git_commit": git_commit(),
    }

    if errors:
        return BuildResult(qa_records=qa_records, corpus_blocks=corpus_blocks, manifest=manifest, errors=errors[:100])
    samples = [DocAgentSample.from_dict(record) for record in qa_records]
    contract = validate_benchmark_contract(samples, input_path="phase3_mpdocvqa_qa.jsonl", corpus_blocks=corpus_blocks)
    if contract.status != "ready":
        errors.extend(contract.errors)
    return BuildResult(qa_records=qa_records, corpus_blocks=corpus_blocks, manifest=manifest, errors=errors[:100])


def record_for_corpus(block: EvidenceBlock) -> dict[str, Any]:
    data = block.to_dict()
    data["page"] = block.page_id if block.page_id is not None else block.location.page
    return data


def write_outputs(result: BuildResult, *, output_qa: Path, output_corpus: Path, output_manifest: Path) -> None:
    manifest = dict(result.manifest)
    manifest["qa_artifact"] = str(output_qa)
    manifest["corpus_artifact"] = str(output_corpus)
    write_jsonl(output_qa, result.qa_records)
    write_jsonl(output_corpus, [record_for_corpus(block) for block in result.corpus_blocks])
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a Phase 3A MP-DocVQA query-independent retrieval benchmark.")
    parser.add_argument("--source-imdb", required=True)
    parser.add_argument("--source-ocr-root", default=None)
    parser.add_argument("--source-qa", default=None)
    parser.add_argument("--output-qa", default=None)
    parser.add_argument("--output-corpus", default=None)
    parser.add_argument("--output-manifest", default=None)
    parser.add_argument("--split", default="dev")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--seed", default="phase3a-mpdocvqa-retrieval-v1")
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    inputs = BuildInputs(
        source_imdb=repo_path(args.source_imdb),
        source_ocr_root=repo_path(args.source_ocr_root) if args.source_ocr_root else None,
        source_qa=repo_path(args.source_qa) if args.source_qa else None,
        split=args.split,
        limit=args.limit,
        seed=args.seed,
    )
    exit_code = 0
    try:
        result = build_benchmark(inputs)
        if result.errors:
            raise BuildError("; ".join(result.errors[:10]))
        if not args.validate_only:
            missing = [
                name
                for name, value in (
                    ("--output-qa", args.output_qa),
                    ("--output-corpus", args.output_corpus),
                    ("--output-manifest", args.output_manifest),
                )
                if not value
            ]
            if missing:
                raise BuildError("missing required output arguments: " + ", ".join(missing))
            write_outputs(
                result,
                output_qa=repo_path(args.output_qa),
                output_corpus=repo_path(args.output_corpus),
                output_manifest=repo_path(args.output_manifest),
            )
        payload = {
            "command": "build_phase3_mpdocvqa_retrieval_benchmark",
            "status": "success",
            "artifact_paths": [
                args.output_qa,
                args.output_corpus,
                args.output_manifest,
            ]
            if not args.validate_only
            else [],
            "metrics": {
                "sample_count": result.manifest["sample_count"],
                "document_count": result.manifest["document_count"],
                "block_count": result.manifest["block_count"],
                "gold_block_coverage": result.manifest["gold_block_coverage"],
                "page_coverage": result.manifest["page_coverage"],
                "qid_hash": result.manifest["qid_hash"],
                "corpus_hash": result.manifest["corpus_hash"],
            },
        }
    except Exception as exc:
        exit_code = 1
        payload = {
            "command": "build_phase3_mpdocvqa_retrieval_benchmark",
            "status": "failed",
            "exit_code": 1,
            "exception": f"{type(exc).__name__}: {exc}",
            "log_tail": "",
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
