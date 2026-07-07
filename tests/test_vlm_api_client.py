from __future__ import annotations

from pathlib import Path

from docagent.integrations.vlm_api import load_vlm_config


def test_load_vlm_config_reads_env_file_without_exposing_secret(tmp_path: Path) -> None:
    env_file = tmp_path / "vlm.env"
    env_file.write_text(
        "\n".join(
            [
                "VLM_API_KEY=sk-test-secret",
                "VLM_BASE_URL=https://example.test/v1",
                "VLM_MODEL=test-vlm",
                "VLM_TIMEOUT_SECONDS=12",
            ]
        ),
        encoding="utf-8",
    )

    config, warnings = load_vlm_config(env_file=env_file, env={})

    assert warnings == []
    assert config is not None
    assert config.base_url == "https://example.test/v1"
    assert config.model == "test-vlm"
    assert config.timeout_seconds == 12
    assert "sk-test-secret" not in repr(config)
    assert config.masked_api_key() == "sk-t...cret"


def test_load_vlm_config_reports_missing_values() -> None:
    config, warnings = load_vlm_config(env={})

    assert config is None
    assert warnings == ["vlm_not_configured"]
