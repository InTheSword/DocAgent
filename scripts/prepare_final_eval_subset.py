from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.parser.parse_tatqa import convert_tatqa_question
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.build_phase4b_expanded_sample import run_expanded_sample


SCRIPT_VERSION = "final-eval-subset-v1"
TATQA_ALLOWED_ANSWER_TYPES = {"span", "multi-span", "arithmetic", "count"}
TATQA_ALLOWED_ANSWER_FROM = {"text", "table", "table-text"}


def repo_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def safe_relpath(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_key(seed: str, value: str) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode("utf-8")).hexdigest()


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def answer_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def has_answer(value: Any) -> bool:
    return any(item.strip() for item in answer_list(value))


def text_preview(value: str | None, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def load_json_list(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"expected a JSON list in {path}")
    return [item for item in data if isinstance(item, dict)]


def tatqa_bucket(question: dict[str, Any]) -> str:
    raw_answer_type = str(question.get("answer_type") or "")
    answer_from = str(question.get("answer_from") or "")
    if raw_answer_type == "arithmetic" or question.get("derivation"):
        return "table_arithmetic"
    if raw_answer_type == "count":
        return "table_count"
    if answer_from == "table":
        return "table_lookup"
    if answer_from == "table-text":
        return "table_text"
    if answer_from == "text":
        return "text"
    return "other"


def tatqa_expected_tools(question: dict[str, Any]) -> list[str]:
    raw_answer_type = str(question.get("answer_type") or "")
    answer_from = str(question.get("answer_from") or "")
    if raw_answer_type == "arithmetic" or question.get("derivation"):
        return ["table_lookup", "simple_calculation"]
    if raw_answer_type == "count":
        return ["table_lookup", "simple_calculation"] if answer_from != "text" else ["retrieval", "simple_calculation"]
    if answer_from == "table":
        return ["table_lookup"]
    if answer_from == "table-text":
        return ["retrieval", "table_lookup"]
    if answer_from == "text":
        return ["retrieval", "local_fact_qa"]
    return ["retrieval"]


def block_manifest(block: Any) -> dict[str, Any]:
    page = block.location.page if block.location and block.location.page is not None else block.page_id
    return {
        "doc_id": block.doc_id,
        "page": page,
        "block_id": block.block_id,
        "block_type": block.block_type,
        "text_preview": text_preview(block.text or block.table_html or block.visual_summary),
        "table_id": None if not block.location else block.location.table_id,
        "image_id": None if not block.location else block.location.image_id,
        "source_uid": block.metadata.get("table_uid") or block.metadata.get("paragraph_uid"),
    }


def build_tatqa_candidate(
    context: dict[str, Any],
    question: dict[str, Any],
    *,
    context_index: int,
    split: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    table_obj = context.get("table")
    table = table_obj.get("table") if isinstance(table_obj, dict) else table_obj
    if not table:
        reasons.append("missing_table")
    if not str(question.get("question") or "").strip():
        reasons.append("missing_question")
    if not has_answer(question.get("answer")):
        reasons.append("missing_answer")
    raw_answer_type = str(question.get("answer_type") or "")
    if raw_answer_type not in TATQA_ALLOWED_ANSWER_TYPES:
        reasons.append(f"unsupported_answer_type:{raw_answer_type or '<missing>'}")
    answer_from = str(question.get("answer_from") or "")
    if answer_from not in TATQA_ALLOWED_ANSWER_FROM:
        reasons.append(f"unsupported_answer_from:{answer_from or '<missing>'}")
    if reasons:
        return None, reasons

    sample = convert_tatqa_question(context, question, split=split)
    evidence_by_id = {block.block_id: block for block in sample.evidence}
    gold_block_ids = [str(item) for item in sample.metadata.get("gold_block_ids") or []]
    gold_evidence = [block_manifest(evidence_by_id[item]) for item in gold_block_ids if item in evidence_by_id]
    bucket = tatqa_bucket(question)
    manifest = {
        "sample_id": sample.qid,
        "dataset": "tatqa",
        "split": split,
        "doc_id": sample.doc_id,
        "question": sample.question,
        "answers": answer_list(sample.answer),
        "expected_answer_type": sample.answer_type,
        "expected_tools": tatqa_expected_tools(question),
        "gold_evidence": gold_evidence,
        "source_record_id": str(question.get("uid") or sample.qid),
        "source_context_index": context_index,
        "source_table_uid": (table_obj or {}).get("uid") if isinstance(table_obj, dict) else None,
        "filter_tags": [
            bucket,
            f"answer_from:{answer_from}",
            f"raw_answer_type:{raw_answer_type}",
        ],
        "metadata": {
            "derivation": question.get("derivation"),
            "scale": question.get("scale"),
            "answer_from": answer_from,
            "raw_answer_type": raw_answer_type,
        },
    }
    return {"sample": sample.to_dict(), "manifest": manifest, "bucket": bucket}, []


def select_balanced(candidates: list[dict[str, Any]], *, limit: int, seed: str) -> list[dict[str, Any]]:
    by_bucket: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
    for candidate in sorted(candidates, key=lambda item: stable_key(seed, item["manifest"]["sample_id"])):
        by_bucket[str(candidate["bucket"])].append(candidate)
    bucket_order = ["table_arithmetic", "table_lookup", "table_text", "text", "table_count", "other"]
    bucket_order.extend(bucket for bucket in sorted(by_bucket) if bucket not in bucket_order)
    selected: list[dict[str, Any]] = []
    while len(selected) < limit and any(by_bucket.values()):
        for bucket in bucket_order:
            if len(selected) >= limit:
                break
            if by_bucket[bucket]:
                selected.append(by_bucket[bucket].popleft())
    return selected


def prepare_tatqa_subset(
    *,
    raw_path: Path,
    output_root: Path,
    split: str,
    limit: int,
    seed: str,
    overwrite: bool,
) -> dict[str, Any]:
    if not raw_path.is_file():
        payload = {
            "dataset": "tatqa",
            "status": "blocked",
            "reason": "missing_raw_json",
            "raw_path": safe_relpath(raw_path),
        }
        output_root.mkdir(parents=True, exist_ok=True)
        write_json(output_root / "filter_report.json", payload)
        return payload
    if output_root.exists() and any(output_root.iterdir()) and not overwrite:
        raise FileExistsError(f"output root already exists: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    records = load_json_list(raw_path)
    candidates: list[dict[str, Any]] = []
    discarded = Counter()
    raw_question_count = 0
    for context_index, context in enumerate(records):
        for question in context.get("questions") or []:
            if not isinstance(question, dict):
                discarded["invalid_question_record"] += 1
                continue
            raw_question_count += 1
            candidate, reasons = build_tatqa_candidate(context, question, context_index=context_index, split=split)
            if candidate is None:
                for reason in reasons:
                    discarded[reason] += 1
                continue
            candidates.append(candidate)

    selected = select_balanced(candidates, limit=limit, seed=seed)
    samples = [item["sample"] for item in selected]
    manifests = [item["manifest"] for item in selected]
    write_jsonl(output_root / "samples.jsonl", samples)
    write_jsonl(output_root / "sample_manifest.jsonl", manifests)
    write_json(output_root / "preview.json", manifests[:5])

    selected_buckets = Counter(str(item["bucket"]) for item in selected)
    selected_answer_from = Counter(str(item["manifest"]["metadata"]["answer_from"]) for item in selected)
    selected_answer_type = Counter(str(item["manifest"]["metadata"]["raw_answer_type"]) for item in selected)
    filter_report = {
        "dataset": "tatqa",
        "split": split,
        "status": "success",
        "script_version": SCRIPT_VERSION,
        "raw_context_count": len(records),
        "raw_question_count": raw_question_count,
        "candidate_count": len(candidates),
        "selected_sample_count": len(selected),
        "limit": limit,
        "seed": seed,
        "discarded_by_reason": dict(sorted(discarded.items())),
        "selected_bucket_distribution": dict(sorted(selected_buckets.items())),
        "selected_answer_from_distribution": dict(sorted(selected_answer_from.items())),
        "selected_raw_answer_type_distribution": dict(sorted(selected_answer_type.items())),
        "selection_rules": {
            "allowed_answer_types": sorted(TATQA_ALLOWED_ANSWER_TYPES),
            "allowed_answer_from": sorted(TATQA_ALLOWED_ANSWER_FROM),
            "balanced_buckets": ["table_arithmetic", "table_lookup", "table_text", "text", "table_count"],
            "note": "TAT-QA is used as structured table/text/numeric QA data, not as raw PDF or MinerU parsing evidence.",
        },
        "warnings": [] if len(selected) >= limit else ["selected_sample_count_below_limit"],
    }
    write_json(output_root / "filter_report.json", filter_report)
    source_manifest = {
        "dataset": "tatqa",
        "split": split,
        "status": "success",
        "script_version": SCRIPT_VERSION,
        "source_path": safe_relpath(raw_path),
        "source_sha256": sha256_file(raw_path),
        "outputs": {
            "samples": "samples.jsonl",
            "sample_manifest": "sample_manifest.jsonl",
            "filter_report": "filter_report.json",
            "preview": "preview.json",
        },
        "output_hashes": {
            "samples_jsonl_sha256": sha256_file(output_root / "samples.jsonl"),
            "sample_manifest_jsonl_sha256": sha256_file(output_root / "sample_manifest.jsonl"),
        },
        "download_performed": False,
    }
    write_json(output_root / "source_manifest.json", source_manifest)
    return {
        "dataset": "tatqa",
        "status": "success",
        "output_root": safe_relpath(output_root),
        "selected_sample_count": len(selected),
        "artifact_paths": [
            safe_relpath(output_root / "samples.jsonl"),
            safe_relpath(output_root / "sample_manifest.jsonl"),
            safe_relpath(output_root / "filter_report.json"),
            safe_relpath(output_root / "source_manifest.json"),
            safe_relpath(output_root / "preview.json"),
        ],
    }


def source_file_record(path: Path) -> dict[str, Any]:
    return {
        "path": safe_relpath(path),
        "name": path.name,
        "byte_size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def discover_mpdocvqa_parquets(parquet_dir: Path, explicit_paths: Iterable[str] | None) -> list[Path]:
    if explicit_paths:
        return sorted({repo_path(path) for path in explicit_paths}, key=lambda item: item.name)
    return sorted(parquet_dir.glob("*.parquet"), key=lambda item: item.name)


def mpdocvqa_manifest_row(record: dict[str, Any]) -> dict[str, Any]:
    page = record.get("gold_page_ordinal")
    return {
        "sample_id": str(record.get("qid") or record.get("raw_question_id")),
        "dataset": "mp_docvqa",
        "split": str(record.get("source_split") or "val"),
        "doc_id": str(record.get("doc_id")),
        "source_document": str(record.get("source_doc_id")),
        "question": str(record.get("question") or ""),
        "answers": answer_list(record.get("answers")),
        "expected_answer_type": "extractive",
        "expected_tools": ["retrieval", "local_fact_qa"],
        "gold_evidence": [
            {
                "doc_id": str(record.get("doc_id")),
                "page": page,
                "block_id": f"{record.get('doc_id')}_page_{page}",
                "block_type": "page",
                "page_id": record.get("gold_page_id"),
                "text_preview": "",
                "note": "Gold evidence is page-level before MinerU/OCR ingestion.",
            }
        ],
        "source_record_id": str(record.get("raw_question_id") or record.get("qid")),
        "source_shard": record.get("source_shard"),
        "source_row_index": record.get("source_row_index"),
        "filter_tags": ["page_window", "raw_pdf_candidate", "extractive"],
    }


def prepare_mpdocvqa_subset(
    *,
    parquet_dir: Path,
    parquet_paths: list[str] | None,
    output_root: Path,
    target_qa_count: int,
    min_qa_count: int,
    max_qa_count: int,
    seed: str,
    validate_only: bool,
    overwrite: bool,
    baseline_doc_ids: list[str],
) -> dict[str, Any]:
    parquets = discover_mpdocvqa_parquets(parquet_dir, parquet_paths)
    temp_files = sorted(path.name for path in parquet_dir.glob("*.crdownload"))
    if not parquets:
        payload = {
            "dataset": "mp_docvqa",
            "status": "blocked",
            "reason": "missing_parquet_shards",
            "parquet_dir": safe_relpath(parquet_dir),
            "temporary_download_files": temp_files,
        }
        output_root.mkdir(parents=True, exist_ok=True)
        write_json(output_root / "filter_report.json", payload)
        return payload

    args = argparse.Namespace(
        input_parquet=[str(path) for path in parquets],
        output_root=str(output_root),
        baseline_doc_id=baseline_doc_ids,
        target_qa_count=target_qa_count,
        min_qa_count=min_qa_count,
        max_qa_count=max_qa_count,
        seed=seed,
        validate_only=validate_only,
        overwrite=overwrite,
    )
    payload = run_expanded_sample(args)
    status = str(payload.get("status") or "success")
    qa_path = output_root / "qa.jsonl"
    manifests: list[dict[str, Any]] = []
    if qa_path.is_file():
        manifests = [mpdocvqa_manifest_row(record) for record in read_jsonl(qa_path)]
        write_jsonl(output_root / "sample_manifest.jsonl", manifests)
        write_json(output_root / "preview.json", manifests[:5])

    source_files = [source_file_record(path) for path in parquets]
    filter_report = {
        "dataset": "mp_docvqa",
        "split": "val",
        "status": status,
        "script_version": SCRIPT_VERSION,
        "validate_only": validate_only,
        "source_file_count": len(parquets),
        "source_files": source_files,
        "target_qa_count": target_qa_count,
        "min_qa_count": min_qa_count,
        "max_qa_count": max_qa_count,
        "selected_sample_count": len(manifests),
        "selection_summary": payload.get("selection_summary"),
        "build_metrics": payload.get("build_metrics"),
        "selection_rules": {
            "input_scope": "page_window",
            "note": "MP-DocVQA parquet shards are restored to page-window PDFs for raw PDF/OCR and page attribution evaluation.",
        },
    }
    write_json(output_root / "filter_report.json", filter_report)

    source_manifest_path = output_root / "source_manifest.json"
    if source_manifest_path.exists():
        source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    else:
        source_manifest = {"dataset": "mp_docvqa", "split": "val"}
    source_manifest["final_eval_preparation"] = {
        "status": status,
        "script_version": SCRIPT_VERSION,
        "source_files": source_files,
        "outputs": {
            "sample_manifest": "sample_manifest.jsonl" if manifests else None,
            "filter_report": "filter_report.json",
            "preview": "preview.json" if manifests else None,
            "documents": "documents.jsonl" if (output_root / "documents.jsonl").is_file() else None,
            "qa": "qa.jsonl" if qa_path.is_file() else None,
        },
        "output_hashes": {
            "sample_manifest_jsonl_sha256": sha256_file(output_root / "sample_manifest.jsonl")
            if manifests
            else None,
            "qa_jsonl_sha256": sha256_file(qa_path) if qa_path.is_file() else None,
        },
        "download_performed": False,
    }
    write_json(source_manifest_path, source_manifest)

    artifacts = [
        output_root / "filter_report.json",
        output_root / "source_manifest.json",
        output_root / "expanded_sample_manifest.jsonl",
        output_root / "selection_summary.json",
    ]
    if manifests:
        artifacts.extend([output_root / "sample_manifest.jsonl", output_root / "preview.json"])
    if qa_path.is_file():
        artifacts.append(qa_path)
    return {
        "dataset": "mp_docvqa",
        "status": status,
        "output_root": safe_relpath(output_root),
        "selected_sample_count": len(manifests),
        "source_file_count": len(parquets),
        "artifact_paths": [safe_relpath(path) for path in artifacts if path.exists()],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare reproducible final-evaluation subsets for DocAgent.")
    parser.add_argument("--dataset", choices=["tatqa", "mpdocvqa", "all"], default="all")
    parser.add_argument("--overwrite", action="store_true")

    parser.add_argument("--tatqa-raw", default="data/benchmark/tatqa/tatqa_dataset_dev.json")
    parser.add_argument("--tatqa-output-root", default="outputs/final_eval/tatqa_dev_subset")
    parser.add_argument("--tatqa-split", default="dev")
    parser.add_argument("--tatqa-limit", type=int, default=120)
    parser.add_argument("--tatqa-seed", default="final-delivery-v1")

    parser.add_argument("--mpdocvqa-parquet-dir", default="data/benchmark/mp_docvqa/val")
    parser.add_argument("--mpdocvqa-parquet", nargs="*")
    parser.add_argument("--mpdocvqa-output-root", default="outputs/final_eval/mpdocvqa_val_subset")
    parser.add_argument("--mpdocvqa-target-qa-count", type=int, default=50)
    parser.add_argument("--mpdocvqa-min-qa-count", type=int, default=30)
    parser.add_argument("--mpdocvqa-max-qa-count", type=int, default=70)
    parser.add_argument("--mpdocvqa-seed", default="final-delivery-v1")
    parser.add_argument("--mpdocvqa-validate-only", action="store_true")
    parser.add_argument("--mpdocvqa-baseline-doc-id", action="append", default=[])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    results: list[dict[str, Any]] = []
    try:
        if args.dataset in {"tatqa", "all"}:
            results.append(
                prepare_tatqa_subset(
                    raw_path=repo_path(args.tatqa_raw),
                    output_root=repo_path(args.tatqa_output_root),
                    split=str(args.tatqa_split),
                    limit=int(args.tatqa_limit),
                    seed=str(args.tatqa_seed),
                    overwrite=bool(args.overwrite),
                )
            )
        if args.dataset in {"mpdocvqa", "all"}:
            results.append(
                prepare_mpdocvqa_subset(
                    parquet_dir=repo_path(args.mpdocvqa_parquet_dir),
                    parquet_paths=args.mpdocvqa_parquet,
                    output_root=repo_path(args.mpdocvqa_output_root),
                    target_qa_count=int(args.mpdocvqa_target_qa_count),
                    min_qa_count=int(args.mpdocvqa_min_qa_count),
                    max_qa_count=int(args.mpdocvqa_max_qa_count),
                    seed=str(args.mpdocvqa_seed),
                    validate_only=bool(args.mpdocvqa_validate_only),
                    overwrite=bool(args.overwrite),
                    baseline_doc_ids=list(args.mpdocvqa_baseline_doc_id),
                )
            )
        final_status = "success" if all(item.get("status") == "success" for item in results) else "blocked"
        payload = {"command": "prepare_final_eval_subset", "status": final_status, "results": results}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        raise SystemExit(0 if final_status == "success" else 1)
    except Exception as exc:
        payload = {
            "command": "prepare_final_eval_subset",
            "status": "failed",
            "exit_code": 1,
            "exception": f"{type(exc).__name__}: {exc}",
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
