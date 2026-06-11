from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.ingestion.service import DocumentIngestionService
from docagent.parser.mineru_backend import MinerUParserBackend
from docagent.retrieval.dense_encoder import DenseEncoder, DenseEncoderConfig
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument("--parser", choices=["mineru"], default="mineru")
    parser.add_argument("--parser-mode", choices=["parse_existing", "local_cli"], default="parse_existing")
    parser.add_argument("--mineru-output-dir")
    parser.add_argument("--mineru-command", default="mineru")
    parser.add_argument("--document-root", default="data/documents")
    parser.add_argument("--sqlite-path", default="outputs/docagent.db")
    parser.add_argument("--build-index", action="store_true")
    parser.add_argument("--dense-model-path")
    parser.add_argument("--dense-device", default="cpu")
    parser.add_argument("--dense-fp16", action="store_true")
    parser.add_argument("--force-parse", action="store_true")
    parser.add_argument("--force-index", action="store_true")
    args = parser.parse_args()

    conn = connect(ROOT / args.sqlite_path)
    repository = DocumentRepository(conn)
    service = DocumentIngestionService(document_root=ROOT / args.document_root, repository=repository)
    backend = MinerUParserBackend(mode=args.parser_mode, command=args.mineru_command)

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

    if args.mineru_output_dir:
        # Copy once into the document cache so later runs do not depend on external fixture paths.
        from docagent.ingestion.document_registry import DocumentRegistry

        preview_record = DocumentRegistry(ROOT / args.document_root).register(ROOT / args.file)
        target = Path(preview_record.document_dir) / "mineru"
        if target.exists() and args.force_parse:
            shutil.rmtree(target)
        if not target.exists():
            shutil.copytree(ROOT / args.mineru_output_dir, target)

    result = service.ingest(
        file_path=ROOT / args.file,
        parser_backend=backend,
        build_index=args.build_index,
        dense_encoder=dense_encoder,
        force_parse=args.force_parse,
        force_index=args.force_index,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

