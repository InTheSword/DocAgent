from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.ingestion.service import DocumentIngestionService
from docagent.integrations.mineru_api import MinerUApiClient
from docagent.parser.mineru_backend import MinerUParserBackend
from docagent.retrieval.dense_encoder import DenseEncoder, DenseEncoderConfig
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository


def _looks_like_local_absolute_path(value: str) -> bool:
    return (
        (len(value) >= 3 and value[1] == ":" and value[2] in {"\\", "/"})
        or value.startswith("\\\\")
        or (value.startswith("/") and "://" not in value)
    )


def _sanitize_manifest_paths(value):
    if isinstance(value, dict):
        return {key: _sanitize_manifest_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_manifest_paths(item) for item in value]
    if isinstance(value, str) and _looks_like_local_absolute_path(value):
        return Path(value).name
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file")
    parser.add_argument("--input", dest="input_file")
    parser.add_argument("--parser", choices=["mineru", "mineru_existing", "mineru_api"], default="mineru")
    parser.add_argument("--parser-mode", choices=["parse_existing", "local_cli"], default="parse_existing")
    parser.add_argument("--mineru-output-dir")
    parser.add_argument("--mineru-output")
    parser.add_argument("--mineru-command", default="mineru")
    parser.add_argument("--mineru-model-version", default="vlm")
    parser.add_argument("--mineru-data-id")
    parser.add_argument("--mineru-language", default="en")
    parser.add_argument("--mineru-ocr", action="store_true")
    parser.add_argument("--disable-mineru-table", action="store_true")
    parser.add_argument("--disable-mineru-formula", action="store_true")
    parser.add_argument("--live-api", action="store_true")
    parser.add_argument("--document-root", default="data/documents")
    parser.add_argument("--sqlite-path", default="outputs/docagent.db")
    parser.add_argument("--build-index", action="store_true")
    parser.add_argument("--dense-model-path")
    parser.add_argument("--dense-device", default="cpu")
    parser.add_argument("--dense-fp16", action="store_true")
    parser.add_argument("--force-parse", action="store_true")
    parser.add_argument("--force-index", action="store_true")
    args = parser.parse_args()
    input_file = args.input_file or args.file
    if not input_file:
        raise SystemExit("--input or --file is required")
    mineru_output = args.mineru_output or args.mineru_output_dir
    parser_mode = "parse_existing" if args.parser in {"mineru_existing", "mineru_api"} else args.parser_mode
    if args.parser == "mineru_api" and not args.live_api:
        raise SystemExit("--parser mineru_api requires --live-api")

    conn = connect(ROOT / args.sqlite_path)
    repository = DocumentRepository(conn)
    service = DocumentIngestionService(document_root=ROOT / args.document_root, repository=repository)
    backend_name = "mineru_existing" if args.parser in {"mineru_existing", "mineru_api"} else "mineru"
    backend = MinerUParserBackend(mode=parser_mode, command=args.mineru_command, backend_name=backend_name)

    dense_encoder = None
    if args.build_index:
        if not args.dense_model_path:
            raise SystemExit("--build-index requires --dense-model-path")
        dense_encoder = DenseEncoder(
            DenseEncoderConfig(
                model_path=args.dense_model_path,
                device=args.dense_device,
                use_fp16=args.dense_fp16,
            )
        )

    if mineru_output:
        # Copy once into the document cache so later runs do not depend on external fixture paths.
        from docagent.ingestion.document_registry import DocumentRegistry

        preview_record = DocumentRegistry(ROOT / args.document_root).register(ROOT / input_file)
        target = Path(preview_record.document_dir) / "mineru"
        if target.exists() and args.force_parse:
            shutil.rmtree(target)
        if not target.exists():
            source_output = ROOT / mineru_output
            shutil.copytree(source_output, target)
            manifest = source_output.parent / "source_manifest.json"
            if manifest.exists():
                manifest_payload = json.loads(manifest.read_text(encoding="utf-8-sig"))
                manifest_payload = _sanitize_manifest_paths(manifest_payload)
                manifest_payload["source_file"] = "source/original.pdf"
                (Path(preview_record.document_dir) / "mineru_source_manifest.json").write_text(
                    json.dumps(manifest_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
    elif args.parser == "mineru_api":
        from docagent.ingestion.document_registry import DocumentRegistry

        preview_record = DocumentRegistry(ROOT / args.document_root).register(ROOT / input_file)
        target = Path(preview_record.document_dir) / "mineru"
        if target.exists() and args.force_parse:
            shutil.rmtree(target)
        data_id = args.mineru_data_id or Path(input_file).stem
        client = MinerUApiClient()
        client.run(
            file_path=ROOT / input_file,
            data_id=data_id,
            output_dir=target,
            model_version=args.mineru_model_version,
            is_ocr=args.mineru_ocr,
            enable_table=not args.disable_mineru_table,
            enable_formula=not args.disable_mineru_formula,
            language=args.mineru_language,
        )

    result = service.ingest(
        file_path=ROOT / input_file,
        parser_backend=backend,
        build_index=args.build_index,
        dense_encoder=dense_encoder,
        force_parse=args.force_parse,
        force_index=args.force_index,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
