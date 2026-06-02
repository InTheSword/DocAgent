#!/usr/bin/env bash
set -euo pipefail

ENV_NAME="${ENV_NAME:-docagent}"
PYTHON_VERSION="${PYTHON_VERSION:-3.10}"
TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu121}"

if command -v conda >/dev/null 2>&1; then
  eval "$(conda shell.bash hook)"
  if ! conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
    conda create -n "$ENV_NAME" "python=$PYTHON_VERSION" -y
  fi
  conda activate "$ENV_NAME"
else
  echo "conda is required on the AutoDL image for this bootstrap script" >&2
  exit 1
fi

python -m pip install -U pip
python -m pip install torch torchvision torchaudio --index-url "$TORCH_INDEX_URL"
python -m pip install -U transformers accelerate datasets peft deepspeed
python -m pip install -U ms-swift
python -m pip install -U sentence-transformers faiss-cpu rank-bm25
python -m pip install -U langgraph fastapi uvicorn gradio pandas pyyaml

python scripts/check_runtime.py

