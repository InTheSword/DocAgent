#!/usr/bin/env bash
set -euo pipefail

python --version
python scripts/smoke_test.py

if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi
else
  echo "nvidia-smi is not available"
fi

