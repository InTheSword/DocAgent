from __future__ import annotations

import http.client
import json
import os
import shutil
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

import requests

from docagent.ingestion.hashing import sha256_file
from docagent.parser.mineru_converter import find_content_list


DONE_STATE = "done"
FAILED_STATE = "failed"
ACTIVE_STATES = {"waiting-file", "pending", "running", "converting"}
TERMINAL_STATES = {DONE_STATE, FAILED_STATE}
ENV_MINERU_TOKEN = "MINERU_TOKEN"
ENV_FILE_TOKEN_KEYS = (ENV_MINERU_TOKEN, "API_TOKEN")
RETRYABLE_DOWNLOAD_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class MinerUApiError(RuntimeError):
    pass


@dataclass
class HttpResponse:
    status_code: int
    json_data: dict[str, Any] | None = None
    content: bytes | None = None
    error_code: str | None = None
    error_message: str | None = None
    request_id_present: bool | None = None


class MinerUHttpClient(Protocol):
    def post_json(self, url: str, *, headers: dict[str, str], payload: dict[str, Any]) -> HttpResponse:
        ...

    def get_json(self, url: str, *, headers: dict[str, str]) -> HttpResponse:
        ...

    def get_bytes(self, url: str) -> HttpResponse:
        ...

    def put_file(self, url: str, file_path: Path, *, timeout: tuple[float, float] | None = None) -> HttpResponse:
        ...


class UrllibMinerUHttpClient:
    def post_json(self, url: str, *, headers: dict[str, str], payload: dict[str, Any]) -> HttpResponse:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        return self._open_json(request)

    def get_json(self, url: str, *, headers: dict[str, str]) -> HttpResponse:
        request = urllib.request.Request(url, headers=headers, method="GET")
        return self._open_json(request)

    def get_bytes(self, url: str) -> HttpResponse:
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request) as response:
                return HttpResponse(status_code=response.status, content=response.read())
        except urllib.error.HTTPError as exc:
            return HttpResponse(status_code=exc.code, content=exc.read())

    def put_file(self, url: str, file_path: Path, *, timeout: tuple[float, float] | None = None) -> HttpResponse:
        timeout_value = timeout or (10.0, 600.0)
        try:
            with file_path.open("rb") as handle:
                response = requests.put(url, data=handle, timeout=timeout_value)
        except requests.RequestException as exc:
            raise MinerUApiError(f"MinerU file upload request failed: {type(exc).__name__}") from exc
        content = response.content or b""
        error = _safe_oss_error(content) if response.status_code < 200 or response.status_code >= 300 else {}
        return HttpResponse(
            status_code=response.status_code,
            content=content,
            error_code=error.get("code"),
            error_message=error.get("message"),
            request_id_present=error.get("request_id_present"),
        )

    def _open_json(self, request: urllib.request.Request) -> HttpResponse:
        try:
            with urllib.request.urlopen(request) as response:
                content = response.read()
                return HttpResponse(status_code=response.status, json_data=json.loads(content.decode("utf-8")))
        except urllib.error.HTTPError as exc:
            content = exc.read()
            try:
                payload = json.loads(content.decode("utf-8"))
            except Exception:
                payload = None
            return HttpResponse(status_code=exc.code, json_data=payload, content=content)


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        raise MinerUApiError(f"MinerU env file not found: {path}")
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            values[key] = value
    return values


def load_mineru_token(
    *,
    token: str | None = None,
    env_file: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    if token:
        return token
    values = dict(os.environ if env is None else env)
    if env_file is not None:
        env_file_values = read_env_file(env_file)
        for key in ENV_FILE_TOKEN_KEYS:
            value = env_file_values.get(key)
            if value:
                return value
    value = values.get(ENV_MINERU_TOKEN)
    if not value:
        raise MinerUApiError(
            f"{ENV_MINERU_TOKEN} is not set; MinerU env files may contain "
            f"{' or '.join(ENV_FILE_TOKEN_KEYS)}"
        )
    return value


def _sanitize_result(data: dict[str, Any]) -> dict[str, Any]:
    sanitized = json.loads(json.dumps(data))
    for item in sanitized.get("extract_result") or []:
        if isinstance(item, dict) and "full_zip_url" in item:
            item["full_zip_url"] = "<redacted>"
    return sanitized


def _first_done_result(data: dict[str, Any]) -> dict[str, Any]:
    results = data.get("extract_result")
    if isinstance(results, dict):
        results = [results]
    if not isinstance(results, list):
        raise MinerUApiError("batch result missing extract_result")
    for item in results:
        if isinstance(item, dict) and item.get("state") == DONE_STATE:
            return item
    raise MinerUApiError("batch result has no done extract_result")


def _safe_oss_error(content: bytes, *, max_message_chars: int = 160) -> dict[str, Any]:
    if not content:
        return {}
    try:
        root = ET.fromstring(content[:4096])
    except ET.ParseError:
        return {}
    code = root.findtext("Code")
    message = root.findtext("Message")
    request_id = root.findtext("RequestId")
    result: dict[str, Any] = {}
    if code:
        result["code"] = code.strip()[:80]
    if message:
        result["message"] = " ".join(message.split())[:max_message_chars]
    result["request_id_present"] = bool(request_id)
    return result


def _upload_error_message(response: HttpResponse) -> str:
    message = f"MinerU file upload failed: HTTP {response.status_code}"
    if response.error_code:
        message += f", OSS code={response.error_code}"
    if response.error_message:
        message += f", message={response.error_message}"
    if response.request_id_present is not None:
        message += f", request_id_present={response.request_id_present}"
    return message


def _safe_extract(zip_path: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    target_root = target_dir.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            destination = (target_dir / member.filename).resolve()
            if not str(destination).startswith(str(target_root)):
                raise MinerUApiError(f"unsafe zip member path: {member.filename}")
        archive.extractall(target_dir)


def _reset_incomplete_output(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


class MinerUApiClient:
    def __init__(
        self,
        *,
        token: str | None = None,
        env_file: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        base_url: str = "https://mineru.net",
        http_client: MinerUHttpClient | None = None,
    ) -> None:
        self._token = load_mineru_token(
            token=token,
            env_file=Path(env_file) if env_file is not None else None,
            env=env,
        )
        self.base_url = base_url.rstrip("/")
        self.http_client = http_client or UrllibMinerUHttpClient()

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._token}",
        }

    def submit_local_pdf(
        self,
        *,
        file_path: str | Path,
        data_id: str,
        model_version: str = "vlm",
        is_ocr: bool | None = False,
        enable_table: bool | None = True,
        enable_formula: bool | None = True,
        language: str | None = "en",
        upload_timeout: tuple[float, float] = (10.0, 600.0),
    ) -> dict[str, Any]:
        path = Path(file_path)
        payload: dict[str, Any] = {
            "files": [{"name": path.name, "data_id": data_id}],
            "model_version": model_version,
        }
        for key, value in {
            "is_ocr": is_ocr,
            "enable_table": enable_table,
            "enable_formula": enable_formula,
            "language": language,
        }.items():
            if value is not None:
                payload[key] = value
        response = self.http_client.post_json(
            f"{self.base_url}/api/v4/file-urls/batch",
            headers=self._headers(),
            payload=payload,
        )
        data = self._checked_json(response, "submit local pdf")
        batch_id = data.get("data", {}).get("batch_id")
        file_urls = data.get("data", {}).get("file_urls")
        if not batch_id or not isinstance(file_urls, list) or len(file_urls) != 1:
            raise MinerUApiError("MinerU upload-url response missing batch_id or file_urls")
        upload_response = self.http_client.put_file(str(file_urls[0]), path, timeout=upload_timeout)
        if upload_response.status_code < 200 or upload_response.status_code >= 300:
            raise MinerUApiError(_upload_error_message(upload_response))
        return {
            "batch_id": batch_id,
            "payload": payload,
            "source_sha256": sha256_file(path),
            "source_size": path.stat().st_size,
        }

    def get_batch_result(self, batch_id: str) -> dict[str, Any]:
        response = self.http_client.get_json(
            f"{self.base_url}/api/v4/extract-results/batch/{batch_id}",
            headers=self._headers(),
        )
        return self._checked_json(response, "get batch result").get("data", {})

    def wait_until_done(self, *, batch_id: str, timeout_seconds: float = 600, poll_interval_seconds: float = 5) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        last_state = None
        while time.monotonic() <= deadline:
            data = self.get_batch_result(batch_id)
            results = data.get("extract_result") or []
            if isinstance(results, dict):
                results = [results]
            states = [item.get("state") for item in results if isinstance(item, dict)]
            if states:
                last_state = ",".join(str(state) for state in states)
            if any(state == FAILED_STATE for state in states):
                raise MinerUApiError("MinerU batch failed")
            if states and all(state == DONE_STATE for state in states):
                return data
            unknown = [state for state in states if state not in ACTIVE_STATES | TERMINAL_STATES]
            if unknown:
                raise MinerUApiError(f"MinerU batch returned unknown state: {unknown[0]}")
            time.sleep(poll_interval_seconds)
        raise TimeoutError(f"MinerU batch did not finish before timeout; last_state={last_state}")

    def download_result(
        self,
        *,
        batch_result: dict[str, Any],
        output_dir: str | Path,
        max_attempts: int = 3,
        retry_delay_seconds: float = 2.0,
    ) -> Path:
        done_result = _first_done_result(batch_result)
        url = done_result.get("full_zip_url")
        if not url:
            raise MinerUApiError("done batch result missing full_zip_url")
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        zip_path = output / "mineru_result.zip"
        attempts = max(1, int(max_attempts))
        response: HttpResponse | None = None
        last_exception: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = self.http_client.get_bytes(str(url))
                last_exception = None
            except (http.client.IncompleteRead, urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                last_exception = exc
                if attempt >= attempts:
                    break
                time.sleep(max(0.0, retry_delay_seconds))
                continue
            if response.status_code in RETRYABLE_DOWNLOAD_STATUS_CODES and attempt < attempts:
                time.sleep(max(0.0, retry_delay_seconds))
                continue
            if response.status_code < 200 or response.status_code >= 300:
                break
            content = response.content or b""
            if not content:
                last_exception = MinerUApiError("MinerU result ZIP is empty")
                if attempt >= attempts:
                    break
                time.sleep(max(0.0, retry_delay_seconds))
                continue
            zip_path.write_bytes(content)
            try:
                with zipfile.ZipFile(zip_path) as archive:
                    bad_member = archive.testzip()
                    if bad_member:
                        raise zipfile.BadZipFile(f"bad zip member: {bad_member}")
            except zipfile.BadZipFile as exc:
                zip_path.unlink(missing_ok=True)
                last_exception = exc
                if attempt >= attempts:
                    break
                time.sleep(max(0.0, retry_delay_seconds))
                continue
            return zip_path
        if last_exception is not None:
            detail = " ".join(str(last_exception).split())[:160]
            suffix = f": {detail}" if detail else ""
            raise MinerUApiError(
                f"MinerU result download failed after retries: {type(last_exception).__name__}{suffix}"
            ) from last_exception
        if response is None:
            raise MinerUApiError("MinerU result download failed before response")
        if response.status_code < 200 or response.status_code >= 300:
            raise MinerUApiError(f"MinerU result download failed with HTTP {response.status_code}")
        raise MinerUApiError("MinerU result download failed after retries")

    def extract_result(self, *, zip_path: str | Path, output_dir: str | Path) -> Path:
        target = Path(output_dir)
        _safe_extract(Path(zip_path), target)
        find_content_list(target)
        return target

    def run(
        self,
        *,
        file_path: str | Path,
        data_id: str,
        output_dir: str | Path,
        model_version: str = "vlm",
        is_ocr: bool | None = False,
        enable_table: bool | None = True,
        enable_formula: bool | None = True,
        language: str | None = "en",
        timeout_seconds: float = 600,
        poll_interval_seconds: float = 5,
        api_max_attempts: int = 3,
        api_retry_delay_seconds: float = 10.0,
    ) -> dict[str, Any]:
        source = Path(file_path)
        output = Path(output_dir)
        manifest_path = output / "mineru_api_manifest.json"
        source_sha256 = sha256_file(source)
        if manifest_path.exists():
            try:
                existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
            try:
                cached_content_list = find_content_list(output)
            except Exception:
                cached_content_list = None
            if existing.get("source_sha256") == source_sha256 and existing.get("status") == "success" and cached_content_list:
                return existing

        attempts = max(1, int(api_max_attempts))
        retry_errors: list[dict[str, Any]] = []
        last_exception: Exception | None = None
        submission: dict[str, Any] = {}
        batch_result: dict[str, Any] = {}
        zip_path: Path | None = None
        for attempt in range(1, attempts + 1):
            _reset_incomplete_output(output)
            try:
                submission = self.submit_local_pdf(
                    file_path=source,
                    data_id=data_id,
                    model_version=model_version,
                    is_ocr=is_ocr,
                    enable_table=enable_table,
                    enable_formula=enable_formula,
                    language=language,
                )
                batch_result = self.wait_until_done(
                    batch_id=str(submission["batch_id"]),
                    timeout_seconds=timeout_seconds,
                    poll_interval_seconds=poll_interval_seconds,
                )
                zip_path = self.download_result(
                    batch_result=batch_result,
                    output_dir=output,
                    retry_delay_seconds=min(2.0, max(0.0, api_retry_delay_seconds)),
                )
                self.extract_result(zip_path=zip_path, output_dir=output)
                break
            except Exception as exc:
                last_exception = exc
                retry_errors.append(
                    {
                        "attempt": attempt,
                        "error_type": type(exc).__name__,
                        "message": " ".join(str(exc).split())[:240],
                    }
                )
                if attempt >= attempts:
                    raise MinerUApiError(
                        f"MinerU API run failed after {attempts} attempts; last_error={type(exc).__name__}"
                    ) from exc
                time.sleep(max(0.0, api_retry_delay_seconds))
        if zip_path is None or last_exception is not None and len(retry_errors) >= attempts:
            raise MinerUApiError("MinerU API run failed before result extraction")
        manifest = {
            "status": "success",
            "batch_id": submission["batch_id"],
            "source_file": str(source),
            "source_size": submission["source_size"],
            "source_sha256": source_sha256,
            "model_version": model_version,
            "data_id": data_id,
            "result_zip_size": zip_path.stat().st_size,
            "result_zip_sha256": sha256_file(zip_path),
            "api_attempt_count": len(retry_errors) + 1,
            "retry_errors": retry_errors,
            "batch_result": _sanitize_result(batch_result),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest

    def _checked_json(self, response: HttpResponse, action: str) -> dict[str, Any]:
        if response.status_code < 200 or response.status_code >= 300:
            raise MinerUApiError(f"MinerU {action} failed with HTTP {response.status_code}")
        payload = response.json_data or {}
        if payload.get("code") != 0:
            msg = payload.get("msg") or "unknown error"
            raise MinerUApiError(f"MinerU {action} failed: {msg}")
        return payload
