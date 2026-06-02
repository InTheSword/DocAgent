# AutoDL Server Setup Notes

This project is designed for local coding on Windows and remote GPU execution
on AutoDL through git/ssh.

## Current remote target

```bash
ssh -p 13566 root@connect.cqa1.seetacloud.com
```

Hardware: 2x RTX 4090D.

AutoDL may not expose useful output through `nvidia-smi`. Use
`scripts/check_runtime.py` after installing PyTorch to verify CUDA instead.

## Recommended remote layout

```bash
/root/autodl-tmp/docagent/      # code, logs, outputs
/root/autodl-tmp/models/        # downloaded model weights
/root/autodl-tmp/datasets/      # downloaded datasets
```

Avoid downloading large datasets to the local Windows machine.

## Recommended environment

```bash
cd /root/autodl-tmp
git clone <your_repo_url> docagent
cd docagent

bash scripts/bootstrap_autodl.sh
conda activate docagent
python scripts/check_runtime.py
python scripts/smoke_test.py
```

MinerU can be installed in a separate environment if dependencies conflict with
ms-swift or OCR packages.

## Remote commands

After a GitHub remote exists:

```bash
ssh -p 13566 root@connect.cqa1.seetacloud.com "cd /root/autodl-tmp/docagent && git pull"
ssh -p 13566 root@connect.cqa1.seetacloud.com "cd /root/autodl-tmp/docagent && python scripts/smoke_test.py"
ssh -p 13566 root@connect.cqa1.seetacloud.com "cd /root/autodl-tmp/docagent && python scripts/check_runtime.py"
```

For long jobs:

```bash
tmux new -s docagent
CUDA_VISIBLE_DEVICES=0,1 bash scripts/train_sft.sh 2>&1 | tee outputs/logs/sft.log
```

Monitor:

```bash
tail -f outputs/logs/sft.log
python scripts/check_runtime.py
```

## First GPU experiment order

1. `python scripts/check_runtime.py`
2. `python scripts/smoke_test.py`
3. Build 50-100 sample dataset subsets on the server.
4. Run retrieval evaluation.
5. Run `Qwen/Qwen3-1.7B` LoRA-SFT smoke test.
6. Run a small GRPO reward smoke test.
7. Expand data volume only after logs and metrics are stable.
