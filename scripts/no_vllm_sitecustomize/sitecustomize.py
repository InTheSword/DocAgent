from __future__ import annotations

import os


if os.environ.get("DOCAGENT_NO_VLLM_STUB") == "1":
    from scripts.no_vllm_stub import install_no_vllm_stub

    install_no_vllm_stub()
