from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


ENV_API_KEY = "DOCAGENT_ROUTER_LLM_API_KEY"
ENV_BASE_URL = "DOCAGENT_ROUTER_LLM_BASE_URL"
ENV_MODEL = "DOCAGENT_ROUTER_LLM_MODEL"
ENV_TIMEOUT_SECONDS = "DOCAGENT_ROUTER_LLM_TIMEOUT_SECONDS"
DEFAULT_TIMEOUT_SECONDS = 30.0


class RouterLLMError(RuntimeError):
    """Raised when the optional router LLM call fails."""


@dataclass(frozen=True)
class RouterLLMConfig:
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


def load_router_llm_config(
    *,
    env_file: Path | None = None,
    env: Mapping[str, str] | None = None,
    model_override: str | None = None,
) -> tuple[RouterLLMConfig | None, list[str]]:
    values = dict(os.environ if env is None else env)
    warnings: list[str] = []
    if env_file is not None:
        if env_file.is_file():
            values.update(read_env_file(env_file))
        else:
            warnings.append("llm_router_env_file_not_found")
            warnings.append("llm_router_not_configured")
            return None, list(dict.fromkeys(warnings))
    if model_override:
        values[ENV_MODEL] = model_override

    missing = [name for name in (ENV_API_KEY, ENV_BASE_URL, ENV_MODEL) if not values.get(name)]
    if missing:
        warnings.append("llm_router_not_configured")
        return None, list(dict.fromkeys(warnings))

    timeout = DEFAULT_TIMEOUT_SECONDS
    timeout_raw = values.get(ENV_TIMEOUT_SECONDS)
    if timeout_raw:
        try:
            timeout = max(1.0, float(timeout_raw))
        except ValueError:
            warnings.append("llm_router_timeout_invalid")

    return (
        RouterLLMConfig(
            api_key=str(values[ENV_API_KEY]),
            base_url=str(values[ENV_BASE_URL]).rstrip("/"),
            model=str(values[ENV_MODEL]),
            timeout_seconds=timeout,
        ),
        list(dict.fromkeys(warnings)),
    )


class OpenAICompatibleRouterClient:
    def __init__(self, config: RouterLLMConfig):
        self.config = config

    def complete(self, *, system_prompt: str, user_payload: Mapping[str, Any]) -> str:
        body = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
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
            raise RouterLLMError(str(exc)) from exc

        try:
            return str(payload["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise RouterLLMError("Router LLM response did not contain message content.") from exc
