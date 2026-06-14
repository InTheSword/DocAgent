from __future__ import annotations

import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from docagent.integrations.mineru_api import HttpResponse, MinerUApiClient, MinerUApiError


class FakeHttpClient:
    def __init__(self, *, states: list[str] | None = None, zip_bytes: bytes | None = None) -> None:
        self.states = states or ["done"]
        self.zip_bytes = zip_bytes if zip_bytes is not None else _zip_bytes({"sample_content_list.json": "[]"})
        self.post_payloads: list[dict] = []
        self.post_headers: list[dict] = []
        self.put_calls: list[tuple[str, Path]] = []
        self.get_urls: list[str] = []

    def post_json(self, url: str, *, headers: dict[str, str], payload: dict) -> HttpResponse:
        self.post_payloads.append(payload)
        self.post_headers.append(headers)
        return HttpResponse(
            status_code=200,
            json_data={"code": 0, "msg": "ok", "data": {"batch_id": "batch1", "file_urls": ["https://upload.example/signed"]}},
        )

    def put_file(self, url: str, file_path: Path) -> HttpResponse:
        self.put_calls.append((url, file_path))
        return HttpResponse(status_code=200, content=b"ok")

    def get_json(self, url: str, *, headers: dict[str, str]) -> HttpResponse:
        self.get_urls.append(url)
        state = self.states.pop(0) if self.states else "done"
        result = {"file_name": "sample.pdf", "state": state, "err_msg": ""}
        if state == "done":
            result["full_zip_url"] = "https://download.example/signed.zip"
        return HttpResponse(
            status_code=200,
            json_data={"code": 0, "msg": "ok", "data": {"batch_id": "batch1", "extract_result": [result]}},
        )

    def get_bytes(self, url: str) -> HttpResponse:
        self.get_urls.append(url)
        return HttpResponse(status_code=200, content=self.zip_bytes)


def _zip_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_mineru_api_client_reads_token_and_writes_sanitized_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINERU_TOKEN", "secret-token")
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-1.4\nsample")
    fake = FakeHttpClient(states=["waiting-file", "running", "done"])
    client = MinerUApiClient(http_client=fake)

    manifest = client.run(
        file_path=source,
        data_id="sample_data",
        output_dir=tmp_path / "mineru",
        poll_interval_seconds=0,
        timeout_seconds=5,
    )

    assert fake.post_payloads[0]["files"] == [{"name": "sample.pdf", "data_id": "sample_data"}]
    assert fake.post_payloads[0]["model_version"] == "vlm"
    assert fake.put_calls[0][0] == "https://upload.example/signed"
    manifest_text = (tmp_path / "mineru" / "mineru_api_manifest.json").read_text(encoding="utf-8")
    assert "secret-token" not in manifest_text
    assert "upload.example" not in manifest_text
    assert "download.example" not in manifest_text
    assert manifest["batch_result"]["extract_result"][0]["full_zip_url"] == "<redacted>"
    assert (tmp_path / "mineru" / "sample_content_list.json").is_file()


def test_mineru_api_client_missing_token_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MINERU_TOKEN", raising=False)
    with pytest.raises(MinerUApiError, match="MINERU_TOKEN"):
        MinerUApiClient(http_client=FakeHttpClient())


def test_mineru_api_client_failed_state_and_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINERU_TOKEN", "secret-token")
    client = MinerUApiClient(http_client=FakeHttpClient(states=["failed"]))
    with pytest.raises(MinerUApiError, match="failed"):
        client.wait_until_done(batch_id="batch1", poll_interval_seconds=0, timeout_seconds=1)

    client = MinerUApiClient(http_client=FakeHttpClient(states=["running", "running"]))
    with pytest.raises(TimeoutError):
        client.wait_until_done(batch_id="batch1", poll_interval_seconds=0, timeout_seconds=-1)


def test_mineru_api_client_rejects_empty_zip_and_zip_slip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINERU_TOKEN", "secret-token")
    client = MinerUApiClient(http_client=FakeHttpClient(zip_bytes=b""))
    with pytest.raises(MinerUApiError, match="empty"):
        client.download_result(
            batch_result={"extract_result": [{"state": "done", "full_zip_url": "https://download.example/signed.zip"}]},
            output_dir=tmp_path,
        )

    slip_zip = _zip_bytes({"../evil.txt": "bad"})
    zip_path = tmp_path / "slip.zip"
    zip_path.write_bytes(slip_zip)
    with pytest.raises(MinerUApiError, match="unsafe zip"):
        client.extract_result(zip_path=zip_path, output_dir=tmp_path / "extract")


def test_mineru_api_client_reuses_successful_existing_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINERU_TOKEN", "secret-token")
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-1.4\nsample")
    output = tmp_path / "mineru"
    output.mkdir()
    (output / "sample_content_list.json").write_text("[]", encoding="utf-8")
    manifest = {
        "status": "success",
        "source_sha256": "placeholder",
    }
    from docagent.ingestion.hashing import sha256_file

    manifest["source_sha256"] = sha256_file(source)
    (output / "mineru_api_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    fake = FakeHttpClient()
    client = MinerUApiClient(http_client=fake)

    result = client.run(file_path=source, data_id="sample_data", output_dir=output)

    assert result["status"] == "success"
    assert fake.post_payloads == []


def test_ingest_document_mineru_api_requires_live_api_before_network(tmp_path: Path) -> None:
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-1.4\nsample")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/ingest_document.py",
            "--input",
            str(source),
            "--parser",
            "mineru_api",
            "--document-root",
            str(tmp_path / "documents"),
            "--sqlite-path",
            str(tmp_path / "docagent.db"),
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "--live-api" in completed.stderr
