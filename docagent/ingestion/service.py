from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from docagent.ingestion.document_registry import DocumentRecord, DocumentRegistry
from docagent.parser.base import ParserBackend
from docagent.parser.mineru_converter import build_page_blocks
from docagent.retrieval.dense_encoder import DenseEncoder
from docagent.retrieval.dense_index import DenseIndex
from docagent.schemas import EvidenceBlock
from docagent.storage.repositories import DocumentRepository
from docagent.utils.jsonl import write_jsonl


@dataclass
class IngestionResult:
    document: DocumentRecord
    blocks: list[EvidenceBlock]
    page_blocks: list[EvidenceBlock]
    dense_index_metadata: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        block_type_counts = Counter(block.block_type for block in self.blocks)
        return {
            "doc_id": self.document.doc_id,
            "parse_status": self.document.parse_status,
            "index_status": self.document.index_status,
            "page_count": self.document.page_count,
            "block_count": len(self.blocks),
            "block_type_counts": dict(sorted(block_type_counts.items())),
            "dense_index": self.dense_index_metadata,
        }


class DocumentIngestionService:
    def __init__(
        self,
        *,
        document_root: str | Path = "data/documents",
        repository: DocumentRepository | None = None,
    ) -> None:
        self.registry = DocumentRegistry(document_root=document_root)
        self.repository = repository

    def ingest(
        self,
        *,
        file_path: str | Path,
        parser_backend: ParserBackend,
        build_index: bool = False,
        dense_encoder: DenseEncoder | None = None,
        force_parse: bool = False,
        force_index: bool = False,
    ) -> IngestionResult:
        record = self.registry.register(file_path)
        document_dir = Path(record.document_dir)
        blocks_path = document_dir / "evidence_blocks.jsonl"
        pages_path = document_dir / "page_documents.jsonl"
        mineru_dir = document_dir / "mineru"

        should_parse = force_parse or not blocks_path.exists()
        if should_parse:
            record.parse_status = "parsing"
            self._save_document(record)
            try:
                blocks = parser_backend.parse(file_path=Path(record.file_path), doc_id=record.doc_id, output_dir=mineru_dir)
            except Exception as exc:
                record.parse_status = "parse_failed"
                self._save_document(record)
                (document_dir / "ingestion_report.json").write_text(
                    json.dumps(
                        {
                            "doc_id": record.doc_id,
                            "parse_status": record.parse_status,
                            "index_status": record.index_status,
                            "error": str(exc),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                raise
            page_blocks = build_page_blocks(record.doc_id, blocks)
            write_jsonl(blocks_path, [block.to_dict() for block in blocks])
            write_jsonl(pages_path, [block.to_dict() for block in page_blocks])
        else:
            from docagent.utils.jsonl import read_jsonl

            blocks = [EvidenceBlock.from_dict(record_data) for record_data in read_jsonl(blocks_path)]
            page_blocks = [EvidenceBlock.from_dict(record_data) for record_data in read_jsonl(pages_path)] if pages_path.exists() else []

        record.page_count = len({block.page_id for block in blocks if block.page_id is not None})
        record.parser_backend = parser_backend.backend_name
        record.parse_status = "parsed"
        record.index_status = "not_started"
        dense_metadata = None

        if build_index:
            if dense_encoder is None:
                raise RuntimeError("--build-index requires a dense encoder")
            index_metadata_path = document_dir / "index_metadata.json"
            if force_index or not index_metadata_path.exists():
                record.index_status = "indexing"
                self._save_document(record)
                try:
                    texts = [block.retrieval_text for block in blocks]
                    embeddings = dense_encoder.encode_documents(texts)
                    index = DenseIndex.build(blocks=blocks, embeddings=embeddings, model_id=dense_encoder.model_id)
                    dense_metadata = index.save(document_dir)
                    index_metadata_path.write_text(json.dumps(dense_metadata, ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception:
                    record.index_status = "index_failed"
                    self._save_document(record)
                    raise
            else:
                dense_metadata = json.loads(index_metadata_path.read_text(encoding="utf-8"))
            record.index_status = "ready"
        else:
            record.index_status = "not_started"

        self._save_document(record)
        if self.repository is not None:
            self.repository.save_evidence_blocks([*blocks, *page_blocks])
            if dense_metadata is not None:
                self.repository.save_index_metadata(
                    doc_id=record.doc_id,
                    index_type="dense",
                    model_id=str(dense_metadata.get("model_id") or ""),
                    artifact_path=str(document_dir),
                    metadata=dense_metadata,
                )
        report = IngestionResult(document=record, blocks=blocks, page_blocks=page_blocks, dense_index_metadata=dense_metadata)
        (document_dir / "ingestion_report.json").write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return report

    def _save_document(self, record: DocumentRecord) -> None:
        if self.repository is not None:
            self.repository.upsert_document(record)
