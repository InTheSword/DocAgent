# GPU 与服务器验证边界

> 用于 DocAgent 实现、验证和服务器产物处理的资源边界。本文档是运行策略，
> 不是里程碑计划。

## 目的

产品需求可能不说明某项功能是否依赖本地 GPU/服务器。实现时仍必须在选择测试、
评测和验收证据前完成资源分类。计划中的能力不等于已实现；本地 mock、fixture 或
CPU-only 测试也不证明真实 GPU/模型组件完成。

## 资源类别

| 类别 | 含义 | 验证规则 |
|---|---|---|
| `local_only` | 不需要本地模型、GPU 或大型数据集的确定性代码或轻量 API 逻辑。 | 本地定向测试加相关回归即可。 |
| `server_optional` | 可有限度本地运行，但真实吞吐或依赖可能需要服务器。 | 必须本地测试；仅当验收依赖真实组件时才需服务器冒烟。 |
| `server_required` | 验收需要真实 GPU/模型/服务器资源。 | 必须新增或复用真实服务器冒烟/评测路径；本地测试最多支持 `implemented` 或 `mock_verified`。 |

## 必须服务器验证的组件

当验收主张涉及下列组件时，必须在服务器 GPU 上验证：

| 组件 | 典型代码/脚本 | 所需服务器依赖 | 说明 |
|---|---|---|---|
| BGE-M3 稠密编码器 | `docagent/retrieval/dense_encoder.py`、`scripts/smoke_phase2_real_models.py`、`scripts/smoke_phase2_real_retrieval.py` | `/root/autodl-tmp/models/bge-m3`、支持 CUDA 的 PyTorch | Hash dense 测试仅是 mock。 |
| bge-reranker-v2-m3 CrossEncoder | `docagent/retrieval/reranker.py`、`scripts/smoke_phase2_real_models.py`、`scripts/smoke_phase2_real_retrieval.py` | `/root/autodl-tmp/models/bge-reranker-v2-m3`、支持 CUDA 的 PyTorch | Keyword reranker 测试仅是 mock。 |
| 真实混合检索基准/冒烟 | `scripts/smoke_phase2_real_retrieval.py`、`scripts/run_phase4b_mpdocvqa_e2e.py` | BGE-M3、reranker、FAISS、已接受语料产物 | BM25/RRF 单测不能证明真实稠密检索。 |
| Qwen3 AnswerPolicy 推理 | `docagent/models/qwen_answer_policy.py`、`scripts/run_workflow_smoke.py`、`scripts/eval_workflow_e2e.py` | `/root/autodl-tmp/models/Qwen3-1.7B`、可选 SFT/GRPO adapter、CUDA | 启发式 AnswerPolicy 仅限本地，不能替代模型。 |
| 完整 GRPO 工作流 E2E | `scripts/smoke_phase2_real_workflow.py`、`scripts/verify_phase2b_real_e2e.py`、`scripts/run_phase4b_mpdocvqa_e2e.py` | BGE-M3、reranker、Qwen3、GRPO adapter、CUDA | 显存紧张时应在加载 Qwen 前释放检索模型。 |
| SFT 训练 | 经明确批准的 AnswerPolicy 训练 runner | Qwen3 base model、训练数据集、CUDA | 未经明确批准，新训练不在范围内。 |
| GRPO/RL 训练 | 经明确批准的 AnswerPolicy RL runner | Qwen3 base model、adapter、奖励代码、数据集、CUDA | GRPO 的 CPU 运行对项目验证过慢。 |
| VLM 视觉审查 | `docagent/integrations/vlm_api.py`、`docagent/tools/visual_summary.py`、`docagent/tools/visual_review.py`、`scripts/docagent_cli.py` | VLM 模型/API 或 GPU VLM runtime | API summary/review、CLI pre-index 持久化和一条真实 PDF 文件输入视觉链已 `real_model_verified`；正式视觉答案基准尚未验收。 |
| 大型真实模型基准 | Phase 3/4/5 服务器基准脚本 | 已接受数据集产物及所需模型 | 本地 fixture 测试不是基准证据。 |

## 服务器可选组件

| 组件 | 边界 |
|---|---|
| MinerU 原始 PDF 解析 | 可在本地或服务器消费既有 MinerU 输出。在线 MinerU CLI/API 必须使用隔离环境；仅在吞吐需要时才要求 GPU MinerU。 |
| 外部 LLM 路由器或查询规划器回退 | 不需要本地 GPU；但若验收依赖此回退，则需 API 凭证和真实 API 冒烟。 |
| FAISS 索引保存/加载 | 可用小嵌入在本地测试；真实稠密嵌入仍需 BGE-M3 服务器验证。 |
| SQLite 追踪、CLI JSON 契约、确定性工具 | 除非路径也调用真实模型，否则本地测试通常充分。 |

## 每项任务的验证检查表

对每项非平凡实现任务，在选择验证方式前回答：

1. 实现是否调用或评测 BGE-M3、reranker、Qwen、SFT、GRPO、VLM、在线 MinerU
   或大型已接受数据集？
2. 预期验收主张是否包含某真实组件的 `real_model_verified`、
   `benchmark_evaluated` 或 `accepted`？
3. 本地测试是否使用 mock、fixture、hash dense、keyword reranker、启发式
   AnswerPolicy 或 dry-run 路径？
4. 若第 1 或第 2 项为是，必须增加或复用服务器验证路径与精简产物契约。
5. 若第 1 和第 2 项均为否，保持实现和验证在本地完成。

对于 `server_required` 功能，本地工作仍应包含定向单测与回归，但在取得真实服务器
证据前，最终状态只能是 `implemented` 或 `mock_verified`。

## 服务器验证要求

服务器验证命令和脚本必须：

- 运行前检查模型、数据集、数据库和包路径；
- 对 GPU 任务先以 `python scripts/check_runtime.py --compact` 分类当前服务器模式；
  仅 `resource_mode=gpu_visible` 可用于 PyTorch 模型加载/训练；
- 不静默下载或替换环境；
- 输出精简的最终 JSON；
- 将长 stdout/stderr 写入文件；
- 将摘要、指标、预览和失败样本保存为结构化文件；
- 不在同步产物中保存密钥、签名 URL、完整 prompt、完整生成或原始大型数据；
- 报告是否使用 GPU、外部 API、VLM、训练和完整 E2E 路径。

## 可同步的服务器产物

原始 `outputs/`、数据集、数据库、日志、检查点和模型均保持忽略状态，不得整体
取消忽略或提交。需要远程检查时，为新服务器任务创建小型精简同步包：

```text
outputs/sync/<run_id>/
  result.json
  manifest.json
  summary.json
  summary.md
  preview.json
  failures_sample.jsonl
  log_tail.txt
  stderr_tail.txt
```

必需文件：

- `result.json`：最终命令状态、退出码、指标和关键产物路径；
- `manifest.json`：run id、命令名、Git commit、服务器路径、文件列表、文件大小和哈希；
- `summary.json` 与 `summary.md`：精简的机器可读和人工可读结果摘要；
- `log_tail.txt` 与 `stderr_tail.txt`：仅保留末尾相关行，通常 60–200 行。

可选文件：

- `preview.json`：有上限的代表性记录预览；
- `failures_sample.jsonl`：有上限且已脱敏的失败样本；
- `metrics.json`：当 `summary.json` 范围更广时的纯指标载荷。

同步包规则：

- 目标大小应低于 2 MB；超过 10 MB 时应总结而非同步原始内容；
- 不包含模型权重、数据集、完整 SQLite 数据库、完整原始日志、`.env`、API key、
  签名 URL 或私有 token；
- 优先保存派生摘要，而非原始生成或完整 EvidenceBlocks；
- 保留足够的产物路径和哈希，使后续服务器重跑可以定位原始完整输出；
- 仅在预计有助于后续排障时，命令说明才命名具体同步/结果文件；成功命令不默认要求
  广泛上传文件。

服务器命令完成后，Codex 应按以下顺序通过 SSH 直接检查同步产物：

1. `outputs/sync/<run_id>/result.json`
2. `outputs/sync/<run_id>/manifest.json`
3. `outputs/sync/<run_id>/summary.md`
4. `outputs/sync/<run_id>/summary.json`
5. 仅在需要时查看定向预览或失败样本。

除非 SSH 不可用且在 Codex 之外执行了回退命令，否则不得向用户索取文件；除非同步包
缺失或不足以排障，否则不得索要完整终端日志。若终端 JSON 无法判断，不得仅凭本地
代码推断根因；应直接检查命名的同步/结果文件，或运行仅报告分类所需字段的窄范围
只读检查。没有 SSH 时，只索取所需的命名产物或精简检查输出。

## 验收映射

| 可用证据 | 允许状态 |
|---|---|
| 仅本地实现 | `implemented` |
| 本地 mock/fixture/hash/keyword 测试通过 | `mock_verified` |
| 服务器依赖存在但真实组件冒烟未运行 | `server_dependency_ready` |
| 真实模型冒烟通过且产物已保存 | `real_model_verified` |
| 已接受范围内的正式真实模型评测通过 | `benchmark_evaluated` |
| 所需实现、测试、服务器冒烟、产物和状态更新均完成 | `accepted` |

若 GPU/服务器依赖不可用，应使用 `blocked`，而不是凭本地证据报告真实组件完成。
