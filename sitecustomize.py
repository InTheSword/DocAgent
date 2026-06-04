from __future__ import annotations

import os
import importlib.util
import sys
from pathlib import Path


if os.environ.get("DOCAGENT_NO_VLLM_STUB") == "1":
    root = Path(__file__).resolve().parent
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)

    stub_path = root / "scripts" / "no_vllm_stub.py"
    spec = importlib.util.spec_from_file_location("docagent_no_vllm_stub", stub_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load no-vLLM stub from {stub_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["docagent_no_vllm_stub"] = module
    spec.loader.exec_module(module)

    module.install_no_vllm_stub()
