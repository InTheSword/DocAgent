from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


def test_phase2b_verifier_outputs_success_json_and_no_persisted_absolute_paths(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n/Type /Page\n/Type /Page\nsource")
    export_root = tmp_path / "mineru_export"
    mineru_output = export_root / "mineru_raw"
    shutil.copytree("tests/fixtures/mineru_real_schema", mineru_output)
    (export_root / "source_manifest.json").write_text(
        json.dumps(
            {
                "source_file": str(source.resolve()),
                "archive_path": str((tmp_path / "download.zip").resolve()),
                "download_url": "https://example.invalid/public/path",
            }
        ),
        encoding="utf-8",
    )
    work_dir = tmp_path / "verification"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_phase2b_real_pdf.py",
            "--source-pdf",
            str(source),
            "--mineru-output",
            str(mineru_output),
            "--work-dir",
            str(work_dir),
        ],
        cwd=Path.cwd(),
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    report = json.loads((work_dir / "verification_report.json").read_text(encoding="utf-8"))
    manifest = json.loads(
        next((work_dir / "documents").glob("*/mineru_source_manifest.json")).read_text(encoding="utf-8")
    )

    assert payload["status"] == "success"
    assert report == payload
    assert payload["raw_block_count"] == 6
    assert payload["converted_block_count"] == 6
    assert payload["page_document_count"] == 2
    assert payload["table_count"] == 1
    assert payload["table_html_count"] == 1
    assert payload["chart_count"] == 1
    assert payload["image_reference_count"] == 2
    assert payload["missing_image_reference_count"] == 0
    assert payload["persisted_absolute_path_count"] == 0
    assert payload["page_aggregates_valid"] is True
    assert payload["sqlite"]["documents"] == 1
    assert payload["sqlite"]["evidence_blocks"] == 8
    assert manifest["source_file"] == "source/original.pdf"
    assert manifest["archive_path"] == "download.zip"
    assert manifest["download_url"] == "https://example.invalid/public/path"
