from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


ENV_API_KEY = "VLM_API_KEY"
ENV_BASE_URL = "VLM_BASE_URL"
ENV_MODEL = "VLM_MODEL"
ENV_TIMEOUT_SECONDS = "VLM_TIMEOUT_SECONDS"
DEFAULT_TIMEOUT_SECONDS = 60.0


class VLMApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class VLMConfig:
    api_key: str = field(repr=False)
    base_url: str
    model: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    def masked_api_key(self) -> str:
        if len(self.api_key) <= 8:
            return "***"
        return f"{self.api_key[:4]}...{self.api_key[-4:]}"


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
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


def load_vlm_config(
    *,
    env_file: Path | None = None,
    env: Mapping[str, str] | None = None,
    model_override: str | None = None,
) -> tuple[VLMConfig | None, list[str]]:
    values = dict(os.environ if env is None else env)
    warnings: list[str] = []
    if env_file is not None:
        if env_file.is_file():
            values.update(read_env_file(env_file))
        else:
            warnings.extend(["vlm_env_file_not_found", "vlm_not_configured"])
            return None, list(dict.fromkeys(warnings))
    if model_override:
        values[ENV_MODEL] = model_override
    missing = [name for name in (ENV_API_KEY, ENV_BASE_URL, ENV_MODEL) if not values.get(name)]
    if missing:
        warnings.append("vlm_not_configured")
        return None, list(dict.fromkeys(warnings))
    timeout = DEFAULT_TIMEOUT_SECONDS
    timeout_raw = values.get(ENV_TIMEOUT_SECONDS)
    if timeout_raw:
        try:
            timeout = max(1.0, float(timeout_raw))
        except ValueError:
            warnings.append("vlm_timeout_invalid")
    return (
        VLMConfig(
            api_key=str(values[ENV_API_KEY]),
            base_url=str(values[ENV_BASE_URL]).rstrip("/"),
            model=str(values[ENV_MODEL]),
            timeout_seconds=timeout,
        ),
        list(dict.fromkeys(warnings)),
    )


class OpenAICompatibleVLMClient:
    def __init__(self, config: VLMConfig):
        self.config = config

    def summarize_image(
        self,
        *,
        image_path: str | Path,
        context: str = "",
    ) -> dict[str, Any]:
        prompt = (
            "Summarize this document image for retrieval. Return one JSON object with "
            "image_kind, caption, visual_summary, key_text, data_points, confidence, and should_index. "
            "Use concise factual language. If the image is decorative, set should_index=false."
        )
        if context:
            prompt += f"\nDocument context: {context[:1200]}"
        return self._image_json(prompt=prompt, image_path=image_path)

    def answer_image_question(
        self,
        *,
        image_path: str | Path,
        question: str,
        context: str = "",
    ) -> dict[str, Any]:
        prompt = (
            "Answer the question using only the provided document image and context. "
            "Return one JSON object with answer, reasoning_summary, visual_summary, key_text, "
            "confidence, and support_status. Use support_status='insufficient' if the image "
            "does not contain enough information."
        )
        if context:
            prompt += f"\nDocument context: {context[:1200]}"
        prompt += f"\nQuestion: {question}"
        return self._image_json(prompt=prompt, image_path=image_path)

    def _image_json(self, *, prompt: str, image_path: str | Path) -> dict[str, Any]:
        image_url = _image_url_payload(image_path)
        body = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            url=f"{self.config.base_url}/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise VLMApiError(str(exc)) from exc
        try:
            content = str(payload["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise VLMApiError("VLM response did not contain message content.") from exc
        return _parse_json_object(content)


def _image_url_payload(image_path: str | Path) -> str:
    text = str(image_path).strip()
    if re.match(r"^https?://", text, flags=re.IGNORECASE):
        return text
    path = Path(text)
    if not path.is_file():
        raise VLMApiError(f"image file not found: {path}")
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    try:
        value = json.loads(stripped)
        return value if isinstance(value, dict) else {"visual_summary": stripped}
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        try:
            value = json.loads(stripped[start : end + 1])
            return value if isinstance(value, dict) else {"visual_summary": stripped}
        except json.JSONDecodeError:
            pass
    return {"visual_summary": stripped}
