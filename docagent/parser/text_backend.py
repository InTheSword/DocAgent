from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from docagent.parser.mineru_converter import content_list_to_blocks
from docagent.schemas import EvidenceBlock


@dataclass
class TextParserBackend:
    backend_name: str = "text"

    def parse(self, *, file_path: Path, doc_id: str, output_dir: Path) -> list[EvidenceBlock]:
        if file_path.suffix.lower() != ".txt":
            raise ValueError(f"text parser only supports .txt files: {file_path.suffix}")

        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            text = file_path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("text parser requires UTF-8 compatible text") from exc

        pages = [page.strip() for page in text.split("\f") if page.strip()]
        items = [
            {"type": "text", "page_idx": index, "text": page}
            for index, page in enumerate(pages)
        ]
        if not items:
            raise ValueError("text file contains no extractable text")

        content_list_path = output_dir / "text_content_list.json"
        content_list_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        layout = {
            "_backend": self.backend_name,
            "_version_name": "docagent_text_v1",
            "_ocr_enable": False,
            "_vlm_ocr_enable": False,
            "pdf_info": [{} for _ in items],
        }
        (output_dir / "layout.json").write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
        source_manifest = {
            "parser_backend": self.backend_name,
            "source_file": f"source/original{file_path.suffix.lower()}",
        }
        (output_dir.parent / "mineru_source_manifest.json").write_text(
            json.dumps(source_manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        blocks = content_list_to_blocks(
            doc_id=doc_id,
            content_list_path=content_list_path,
            document_dir=output_dir.parent,
        )
        for block in blocks:
            block.metadata["parser"] = self.backend_name
            block.metadata["parser_backend"] = self.backend_name
        return blocks
