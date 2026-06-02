#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="${ENV_NAME:-docagent}"
PYTHON_VERSION="${PYTHON_VERSION:-3.10}"
USE_CONDA_ENV="${USE_CONDA_ENV:-0}"
INSTALL_TORCH="${INSTALL_TORCH:-auto}"
INSTALL_DEEPSPEED="${INSTALL_DEEPSPEED:-0}"
TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu124}"

if [[ "$USE_CONDA_ENV" == "1" ]]; then
  if ! command -v conda >/dev/null 2>&1; then
    echo "conda is required when USE_CONDA_ENV=1" >&2
    exit 1
  fi
  eval "$(conda shell.bash hook)"
  if ! conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
    conda create -n "$ENV_NAME" "python=$PYTHON_VERSION" -y
  fi
  conda activate "$ENV_NAME"
else
  echo "Using current Python environment: $(python -V)"
fi

python -m pip install -U pip

torch_ok=0
python - <<'PY' && torch_ok=1 || torch_ok=0
import torch
raise SystemExit(0 if torch.cuda.is_available() else 1)
PY

if [[ "$INSTALL_TORCH" == "1" ]] || [[ "$INSTALL_TORCH" == "auto" && "$torch_ok" == "0" ]]; then
  echo "Installing PyTorch from $TORCH_INDEX_URL"
  python -m pip install torch torchvision torchaudio --index-url "$TORCH_INDEX_URL"
else
  echo "Keeping existing PyTorch installation"
fi

python -m pip install -U transformers accelerate datasets peft
if [[ "$INSTALL_DEEPSPEED" == "1" ]]; then
  python -m pip install -U deepspeed
else
  echo "Skipping deepspeed install. Set INSTALL_DEEPSPEED=1 when needed."
fi
python -m pip install -U ms-swift
python -m pip install -U sentence-transformers faiss-cpu rank-bm25
python -m pip install -U langgraph fastapi uvicorn gradio pandas pyyaml

python scripts/check_runtime.py
