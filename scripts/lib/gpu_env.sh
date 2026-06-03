#!/usr/bin/env bash

prepare_gpu_env() {
  CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"

  if [[ -z "${NPROC_PER_NODE:-}" ]]; then
    if [[ -z "$CUDA_VISIBLE_DEVICES" || "$CUDA_VISIBLE_DEVICES" == "-1" ]]; then
      NPROC_PER_NODE=1
    else
      local devices="${CUDA_VISIBLE_DEVICES// /}"
      local parts
      IFS=',' read -r -a parts <<< "$devices"
      NPROC_PER_NODE="${#parts[@]}"
    fi
  fi

  export CUDA_VISIBLE_DEVICES
  export NPROC_PER_NODE
  echo "Using CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES NPROC_PER_NODE=$NPROC_PER_NODE"
}
