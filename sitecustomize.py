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
