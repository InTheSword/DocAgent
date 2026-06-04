#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p outputs/logs outputs/run_state

timestamp="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_FILE:-outputs/logs/grpo_background_${timestamp}.log}"
PID_FILE="${PID_FILE:-outputs/run_state/grpo_background_${timestamp}.pid}"
OUTPUT_DIR="${OUTPUT_DIR:-outputs/checkpoints/qwen3-docagent-grpo-background-${timestamp}}"

export OUTPUT_DIR

nohup bash "$SCRIPT_DIR/train_grpo.sh" > "$LOG_FILE" 2>&1 &
pid="$!"
printf '%s\n' "$pid" > "$PID_FILE"

python - <<PY
import json
print(json.dumps({
    "pid": $pid,
    "log_file": "$LOG_FILE",
    "pid_file": "$PID_FILE",
    "output_dir": "$OUTPUT_DIR",
}, ensure_ascii=False, indent=2))
PY
