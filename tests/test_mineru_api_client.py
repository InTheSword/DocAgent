from __future__ import annotations

import io
import json
import subprocess
import sys
import zipfile
import http.client
from pathlib import Path

import pytest
import requests

from docagent.integrations.mineru_api import HttpResponse, MinerUApiClient, MinerUApiError, UrllibMinerUHttpClient


class FakeHttpClient:
    def __init__(
        self,
        *,
        states: list[str] | None = None,
        zip_bytes: bytes | None = None,
        upload_response: HttpResponse | None = None,
    ) -> None:
        self.states = states or ["done"]
        self.zip_bytes = zip_bytes if zip_bytes is not None else _zip_bytes({"sample_content_list.json": "[]"})
        self.upload_response = upload_response or HttpResponse(status_code=200, content=b"ok")
        self.post_payloads: list[dict] = []
        self.post_headers: list[dict] = []
        self.put_calls: list[tuple[str, Path, tuple[float, float] | None]] = []
        self.get_urls: list[str] = []

    def post_json(self, url: str, *, headers: dict[str, str], payload: dict) -> HttpResponse:
        self.post_payloads.append(payload)
        self.post_headers.append(headers)
        return HttpResponse(
            status_code=200,
            json_data={"code": 0, "msg": "ok", "data": {"batch_id": "batch1", "file_urls": ["https://upload.example/signed"]}},
        )

    def put_file(self, url: str, file_path: Path, *, timeout: tuple[float, float] | None = None) -> HttpResponse:
        self.put_calls.append((url, file_path, timeout))
        return self.upload_response

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


def _response(status_code: int, content: bytes = b"") -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = content
    return response


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
    assert fake.put_calls[0][2] == (10.0, 600.0)
    manifest_text = (tmp_path / "mineru" / "mineru_api_manifest.json").read_text(encoding="utf-8")
    assert "secret-token" not in manifest_text
    assert "upload.example" not in manifest_text
    assert "download.example" not in manifest_text
    assert manifest["batch_result"]["extract_result"][0]["full_zip_url"] == "<redacted>"
    assert (tmp_path / "mineru" / "sample_content_list.json").is_file()


def test_mineru_api_client_reads_token_from_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MINERU_TOKEN", raising=False)
    env_file = tmp_path / "mineru.env"
    env_file.write_text("export MINERU_TOKEN='file-secret-token'\n", encoding="utf-8")
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-1.4\nsample")
    fake = FakeHttpClient()
    client = MinerUApiClient(env_file=env_file, http_client=fake, env={})

    client.run(file_path=source, data_id="sample_data", output_dir=tmp_path / "mineru")

    assert fake.post_headers[0]["Authorization"] == "Bearer file-secret-token"
    manifest_text = (tmp_path / "mineru" / "mineru_api_manifest.json").read_text(encoding="utf-8")
    assert "file-secret-token" not in manifest_text


def test_mineru_api_client_accepts_api_token_key_from_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MINERU_TOKEN", raising=False)
    env_file = tmp_path / "mineru.env"
    env_file.write_text("API_TOKEN=file-secret-token\n", encoding="utf-8")
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-1.4\nsample")
    fake = FakeHttpClient()
    client = MinerUApiClient(env_file=env_file, http_client=fake, env={})

    client.run(file_path=source, data_id="sample_data", output_dir=tmp_path / "mineru")

    assert fake.post_headers[0]["Authorization"] == "Bearer file-secret-token"
    manifest_text = (tmp_path / "mineru" / "mineru_api_manifest.json").read_text(encoding="utf-8")
    assert "file-secret-token" not in manifest_text


def test_mineru_api_client_does_not_use_generic_api_token_without_env_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MINERU_TOKEN", raising=False)
    monkeypatch.setenv("API_TOKEN", "not-mineru-specific")

    with pytest.raises(MinerUApiError, match="MINERU_TOKEN"):
        MinerUApiClient(http_client=FakeHttpClient())


def test_mineru_api_client_missing_token_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MINERU_TOKEN", raising=False)
    with pytest.raises(MinerUApiError, match="MINERU_TOKEN"):
        MinerUApiClient(http_client=FakeHttpClient())


def test_mineru_api_client_missing_explicit_env_file_fails(tmp_path: Path) -> None:
    with pytest.raises(MinerUApiError, match="env file not found"):
        MinerUApiClient(env_file=tmp_path / "missing.env", http_client=FakeHttpClient(), env={})


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


def test_mineru_api_client_retries_transient_result_download(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINERU_TOKEN", "secret-token")
    fake = FakeHttpClient()
    calls = {"count": 0}

    def flaky_get_bytes(url: str) -> HttpResponse:
        calls["count"] += 1
        if calls["count"] == 1:
            raise http.client.IncompleteRead(b"partial", 10)
        return HttpResponse(status_code=200, content=fake.zip_bytes)

    fake.get_bytes = flaky_get_bytes  # type: ignore[method-assign]
    client = MinerUApiClient(http_client=fake)

    zip_path = client.download_result(
        batch_result={"extract_result": [{"state": "done", "full_zip_url": "https://download.example/signed.zip"}]},
        output_dir=tmp_path,
        retry_delay_seconds=0,
    )

    assert calls["count"] == 2
    assert zip_path.is_file()


def test_mineru_api_client_retries_retryable_download_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINERU_TOKEN", "secret-token")
    fake = FakeHttpClient()
    responses = [HttpResponse(status_code=503, content=b"busy"), HttpResponse(status_code=200, content=fake.zip_bytes)]

    def retryable_get_bytes(url: str) -> HttpResponse:
        return responses.pop(0)

    fake.get_bytes = retryable_get_bytes  # type: ignore[method-assign]
    client = MinerUApiClient(http_client=fake)

    zip_path = client.download_result(
        batch_result={"extract_result": [{"state": "done", "full_zip_url": "https://download.example/signed.zip"}]},
        output_dir=tmp_path,
        retry_delay_seconds=0,
    )

    assert not responses
    assert zip_path.is_file()


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


def test_signed_upload_uses_streaming_put_without_api_headers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "sample.pdf"
    raw = b"%PDF-1.4\nstream body"
    source.write_bytes(raw)
    captured: dict[str, object] = {}

    def fake_put(url: str, *, data, timeout):
        captured["url"] = url
        captured["body"] = data.read()
        captured["timeout"] = timeout
        captured["data_type"] = type(data).__name__
        return _response(200, b"ok")

    monkeypatch.setattr(requests, "put", fake_put)
    response = UrllibMinerUHttpClient().put_file(
        "https://mineru.oss-cn-shanghai.aliyuncs.com/object.pdf?Signature=abc&Expires=123",
        source,
        timeout=(3.0, 7.0),
    )

    assert response.status_code == 200
    assert captured["url"] == "https://mineru.oss-cn-shanghai.aliyuncs.com/object.pdf?Signature=abc&Expires=123"
    assert captured["body"] == raw
    assert captured["timeout"] == (3.0, 7.0)
    assert captured["data_type"] in {"BufferedReader", "FileIO"}


def test_signed_upload_does_not_call_read_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-1.4\nstream")

    def forbidden_read_bytes(self):
        raise AssertionError("read_bytes must not be used for signed upload")

    def fake_put(url: str, *, data, timeout):
        return _response(200, data.read())

    monkeypatch.setattr(Path, "read_bytes", forbidden_read_bytes)
    monkeypatch.setattr(requests, "put", fake_put)

    response = UrllibMinerUHttpClient().put_file("https://upload.example/signed", source, timeout=(1.0, 2.0))

    assert response.status_code == 200


def test_signed_upload_accepts_any_2xx_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-1.4\nsample")

    def fake_put(url: str, *, data, timeout):
        data.read()
        return _response(204)

    monkeypatch.setattr(requests, "put", fake_put)

    response = UrllibMinerUHttpClient().put_file("https://upload.example/signed", source, timeout=(1.0, 2.0))

    assert response.status_code == 204


def test_signed_upload_403_parses_safe_oss_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-1.4\nsample")
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<Error>
  <Code>SignatureDoesNotMatch</Code>
  <Message>The request signature we calculated does not match.</Message>
  <RequestId>abc123</RequestId>
</Error>"""

    def fake_put(url: str, *, data, timeout):
        data.read()
        return _response(403, xml)

    monkeypatch.setattr(requests, "put", fake_put)

    response = UrllibMinerUHttpClient().put_file(
        "https://upload.example/object?Signature=secret-query",
        source,
        timeout=(1.0, 2.0),
    )

    assert response.status_code == 403
    assert response.error_code == "SignatureDoesNotMatch"
    assert response.error_message == "The request signature we calculated does not match."
    assert response.request_id_present is True


def test_submit_local_pdf_403_error_is_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINERU_TOKEN", "secret-token")
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-1.4\nsample")
    fake = FakeHttpClient(
        upload_response=HttpResponse(
            status_code=403,
            content=b"<Error><Code>SignatureDoesNotMatch</Code><Message>bad signature</Message><RequestId>r1</RequestId></Error>",
            error_code="SignatureDoesNotMatch",
            error_message="bad signature",
            request_id_present=True,
        )
    )
    client = MinerUApiClient(http_client=fake)

    with pytest.raises(MinerUApiError) as excinfo:
        client.submit_local_pdf(file_path=source, data_id="sample_data")

    message = str(excinfo.value)
    assert "HTTP 403" in message
    assert "OSS code=SignatureDoesNotMatch" in message
    assert "request_id_present=True" in message
    assert "https://upload.example" not in message
    assert "secret-token" not in message
    assert "Signature=" not in message
