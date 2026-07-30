# AutoDL 服务器设置

> 本文只记录稳定的环境事实以及本地/服务器执行规则。
> 任务范围由 `docs/ACTIVE_PLAN.md` 定义；数据集角色由 `docs/DATASETS.md` 定义。

## 1. 执行模型

本地 Windows 工作区：

- Codex 编辑代码、运行本地测试、提交并推送。

AutoDL 服务器：

- 安装或运行大模型、下载大数据集、GPU 冒烟与长时间评估。
- 默认通过直接 SSH 执行；SSH 不可用、用户明确要求，或必须用户侧交互时，才提供用户粘贴的命令组。

服务器工作必须先预检项目路径、环境、软件包、模型、数据集和 GPU。不要将密码、令牌或密钥写入仓库、日志或同步包。

## 2. 服务器路径

```text
主检出目录：/root/autodl-tmp/docagent
分支工作树目录：/root/autodl-tmp/docagent_worktrees/<worktree-name>
模型目录：/root/autodl-tmp/models
数据集目录：/root/autodl-tmp/datasets
```

这些目录是服务器本地状态；不得提交其中的模型、数据、检查点、数据库、缓存或长日志。
当活跃任务已经使用独立 worktree 时，代码拉取、项目内数据、测试和评测必须继续在该
worktree 中执行，不得回退到主检出目录。具体 worktree 路径由当前阶段计划记录。

### 本地连接记录

当前 AutoDL 连接参数保存在本机、未跟踪的 `.secrets/autodl_ssh.json`。该文件记录
已确认的主机指纹，以及仅能由当前 Windows 用户解密的 DPAPI 密码；不得将其复制到
服务器、压缩包、日志或 Git。连接前必须将服务器呈现的主机密钥与该记录匹配。

## 3. 主 DocAgent 环境

稳定环境名称为 `docagent`：

```bash
conda activate docagent
cd <当前阶段使用的项目目录或 worktree>
```

非交互 SSH 命令应先加载 Conda：

```bash
source /root/miniconda3/etc/profile.d/conda.sh
conda activate docagent
```

已观测的稳定环境基线：

```text
Python 3.10.20
PyTorch 2.12.0.dev20260624+cu130
CUDA runtime 13.0
GPU NVIDIA GeForce RTX 4090 D
```

AutoDL 默认可能以无卡模式启动，此时 `torch.cuda.is_available()` 为 `False` 并不自动表示环境损坏。先检查运行时，再决定是否需要带卡实例：

```bash
python - <<'PY'
import torch
print({"cuda_available": torch.cuda.is_available(), "device_count": torch.cuda.device_count(), "torch": torch.__version__})
PY
```

资源模式：

- 无 GPU：允许代码检查、小型 CPU 契约测试和服务器依赖检查；不得将其称为真实模型验证。
- 单 GPU：允许模型加载、真实组件冒烟与小规模评估。
- 多 GPU：仅在活跃计划明确要求吞吐量或并行评估时使用。

不得为了处理无卡状态而重装或替换稳定环境中的 Torch、CUDA、驱动或核心依赖。

## 4. 模型路径与下载规则

模型应放在服务器模型目录，使用明确的本地路径。例如：

```text
/root/autodl-tmp/models/Qwen2.5-7B-Instruct
/root/autodl-tmp/models/bge-m3
/root/autodl-tmp/models/bge-reranker-v2-m3
```

下载大型模型、数据集或安装大型依赖前，必须获得用户明确批准。下载后记录实际路径、版本/提交标识、校验结果及最小可复现命令；不要把权重复制进仓库。

AnswerPolicy v3 的 schema 冒烟可使用 PEFT LoRA runner 与 ms-swift，但不得为此替换稳定环境中的软件包或修改训练检查点。

## 5. MinerU 策略

MinerU 必须在独立环境中运行，不能安装进稳定的 `docagent` 环境。在线 MinerU API 依赖令牌，建议保存在未跟踪的本地密钥文件中；兼容 `API_TOKEN` 环境变量。

可接受状态：

- 本地合成 fixture：`mock_verified`；
- 已获得服务器依赖但尚未真实转换：`server_dependency_ready`；
- 对真实 PDF 的一次成功转换并保存紧凑产物：`real_model_verified`。

MinerU 安装、下载或真实转换不得阻断当前本地里程碑；如果依赖不可用，应报告 `blocked_by_missing_mineru_output` 并继续处理不依赖它的工作。

## 5A. VLM 策略

视觉问答只使用经配置的 OpenAI-compatible API。端点、密钥和模型别名保存在未跟踪的密钥文件或环境变量中，不能写入代码、文档示例、日志或同步包。

`qwen-image` 不是本项目的 VQA 模型，不得用于真实视觉问答验收。真实 VLM 验证需要成功调用、保存紧凑结果产物，并明确记录模型别名与接口类型。

## 6. 环境和下载限制

未获用户批准前，不得：

- 安装或升级 Torch、CUDA、MinerU、vLLM、ms-swift 或其他大型依赖；
- 下载模型、数据集或检查点；
- 修改稳定 `docagent` 环境；
- 删除服务器模型、数据、输出或缓存。

优先重用现有模型路径、环境和同步脚本。若需要新依赖，先说明大小、磁盘影响、预期用途及回滚方式。

## 7. 服务器预检

在真实模型、数据集或 GPU 命令前，最少检查：

```bash
pwd
test -d <当前阶段使用的项目目录或 worktree>
python --version
python - <<'PY'
import importlib.util
for name in ("torch", "transformers", "peft"):
    print(name, bool(importlib.util.find_spec(name)))
PY
nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader
```

缺少软件包、模型、数据、GPU 或令牌时，先按失败分类记录，不要进行试探性安装或长时间重试。

## 8. 服务器操作要求

直接 SSH 命令必须：

- 激活正确的 Conda 环境；
- 使用明确的绝对路径；
- 先完成路径和依赖预检；
- 将长输出写入具名日志；
- 仅返回紧凑 JSON、指标和需要检查的具名产物路径；
- 当服务器端 Git 需要联网且存在该文件时，先 `source /etc/network_turbo`。

若不得不提供用户粘贴的回退命令，每次交互最多一个简短前台命令组。它必须保持交互终端，且当内部命令失败时不得故意关闭、替换或终止用户的 shell。不得使用 `nohup`、`setsid`、后台 `&`、`tmux`、`kill`、`pkill` 或 `exec`。不得使用 `set -e`、shell `exit`、`trap ... EXIT`，也不得用内联 Python 的 `raise SystemExit` / `sys.exit(...)` 作为外层失败传播；应将返回码和异常收集到紧凑 JSON 中。

## 9. 结果协议与同步包

成功时返回：

```json
{
  "command": "...",
  "status": "success",
  "artifact_paths": [],
  "metrics": {}
}
```

失败时返回：

```json
{
  "command": "...",
  "status": "failed",
  "exit_code": 1,
  "exception": "...",
  "log_tail": "last 60 lines"
}
```

对于新服务器任务，优先在以下位置创建精选同步包：

```text
outputs/sync/<run_id>/
```

同步包可包含 `result.json`、`manifest.json`、`summary.json`、`summary.md`、小型预览、失败样本与日志尾部。不得同步原始数据集、完整输出树、模型权重、数据库、完整日志或密钥。

终端 JSON 仅用于第一层状态路由；若不足以判断问题，应通过 SSH 读取具名结果文件或运行小型只读检查，而不是请求完整终端输出。

## 10. Git 同步

服务器端 Git 操作前，确认当前目录、分支和工作树状态。若存在网络加速脚本，先执行：

```bash
source /etc/network_turbo
```

不要在服务器上覆盖本地未提交改动、执行破坏性 reset，或将服务器生成物混入源码提交。

## 11. 安全与清理

将密钥、令牌、真实用户文档、模型权重和数据集视为敏感或大型服务器状态。清理前必须先确认精确目标与恢复需要；不得用宽泛通配符删除项目根目录、模型目录或数据集目录。
