#!/usr/bin/env bash
set -euo pipefail

# Repair known AutoDL/package conflicts without reinstalling PyTorch.

echo "== Before repair =="
python scripts/inspect_env.py

echo "== Remove packages not required by DocAgent =="
python -m pip uninstall -y hf-gradio || true

echo "== Ensure ms-swift compatible Gradio stack =="
python -m pip install -U "gradio>=3.40.0,<6.0"

echo "== Re-check ms-swift metadata against final environment =="
python -m pip install -U ms-swift msgspec

echo "== Final dependency check =="
python -m pip check
python scripts/inspect_env.py
python scripts/check_runtime.py
