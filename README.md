# DocAgent

[简体中文](README.md) | [English](README_EN.md)

DocAgent 是一个以本地命令行为优先的复杂文档问答项目。当前活跃方向为 Phase 5 个人使用 MVP：导入或选择一份文档、提出问题，并返回答案、简短推理摘要、所用证据、引用、调用工具和本地追踪产物。

当前交付物不是 UI 产品、云服务、VLM 视觉推理系统，也不是已验收的最终答案质量基准。

## 当前入口

主 CLI：

```powershell
python scripts\docagent_cli.py --file <path> --question "<question>"
python scripts\docagent_cli.py --doc-id <doc_id> --question "<question>"
```

默认情况下，CLI 会为正常使用启用 `user_best` 执行配置。该配置要求可用的真实 MinerU API 令牌、路由器/查询规划器 LLM 配置、BGE-M3、交叉编码器重排序器、Qwen3，以及当前最优的 AnswerPolicy v3 检查点。若缺少这些资源，CLI 会明确报错。

轻量配置仅用于本地或 CI 检查：

```powershell
python scripts\docagent_cli.py --execution-profile self_test --file <path> --question "<question>"
```

如需面向用户的终端输出且不显示内部 ID：

```powershell
python scripts\docagent_cli.py --file <path> --question "<question>" --stdout-format text
```

列出本地文档：

```powershell
python scripts\docagent_cli.py --list-documents --db-path outputs\docagent.db
```

提问前检查或预构建文档稠密索引：

```powershell
python scripts\docagent_cli.py --doc-id <doc_id> --check-index --db-path outputs\docagent.db
python scripts\docagent_cli.py --doc-id <doc_id> --prepare-index --db-path outputs\docagent.db
```

准备本地最终评测子集：

```powershell
python scripts\prepare_final_eval_subset.py `
  --dataset all `
  --tatqa-limit 80 `
  --mpdocvqa-target-qa-count 50 `
  --mpdocvqa-min-qa-count 30 `
  --mpdocvqa-max-qa-count 70 `
  --overwrite
```

运行本地子集诊断：

```powershell
python scripts\run_final_eval_subset.py `
  --dataset all `
  --run-id local_subset_full_diagnostic_report `
  --output-dir outputs\final_eval\local_subset_diagnostic
```

在准备就绪的服务器上运行最终交付基准门控：

```powershell
python scripts\run_final_delivery_benchmark_gate.py --run-id final_delivery_gate_probe
```

完整的当前 CLI 契约、存储路径、数据集命令、输出字段和限制请参阅 [docs/FINAL_DELIVERY_CLI.md](docs/FINAL_DELIVERY_CLI.md)。
当前交付状态表、已验收证据边界和仍处于 `not_started` 状态的工作请参阅 [docs/FINAL_DELIVERY_REPORT.md](docs/FINAL_DELIVERY_REPORT.md)。

## 当前输出契约

常规问答类 CLI 输出包含：

```json
{
  "answer": "...",
  "reasoning_summary": "...",
  "evidence_used": [],
  "citations": [],
  "tools_used": [],
  "trace_path": "outputs/cli/<run_id>/trace.json"
}
```

引用记录包含 `doc_id`、`page`、`block_id`、`block_type` 等文档和位置字段；可用时还包括预览文本、表格或图像元数据。这些详细字段保存在 JSON 产物中。`--stdout-format text` 会输出面向用户的答案、简短推理、可读来源和追踪路径，而不暴露内部的 `block_id`、`doc_id` 或资源路径。

## 本地存储

默认路径：

```text
outputs/docagent.db
outputs/cli/<run_id>/
data/documents/
outputs/final_eval/
```

这些都是本地产物。原始数据集、生成结果、SQLite 数据库、文档缓存、密钥、模型权重和日志不应提交至 Git。

## 已在本地实现

- 统一的 CLI 和产物契约；
- 文本文件导入；
- 既有 MinerU 输出导入；
- 原始 PDF 的 MinerU API 导入，且已通过实时执行冒烟验证；
- 确定性的文档统计和页面查找；
- 确定性的抽取式文档摘要；
- 基于持久化证据的确定性结构化提取；
- 确定性的表格查找和简单、可追踪的计算；
- `local_fact_qa` 工作流包装器；
- AnswerPolicy 候选输出模式和引用白名单过滤；
- 本地 TAT-QA / MP-DocVQA 验证子集准备；
- 用于 MinerU API 生成证据映射的 MP-DocVQA 证据物化运行器；
- 带有 `summary.json` 和 `summary.md` 的本地诊断报告；
- 本地最终交付就绪检查，用于验证 CLI 选项、输出契约字段、引用/证据位置字段、文档边界和已弃用的 PM 交接清理；
- 面向就绪检查、AnswerPolicy 基线和 MP-DocVQA 全工作流诊断的最终交付基准门控编排；它仅用于诊断，不主张基准已验收；
- 对最终交付基准门控产物的只读检查，用于验证本地/同步清单哈希、步骤状态及基准/训练安全标志。

## 尚未验收

- 正式 MP-DocVQA/TAT-QA 最终答案基准；
- 最终 Qwen 答案质量验收；
- 像素级图像/图表 VLM 推理；
- 新的 SFT/GRPO 训练；
- UI、FastAPI、Gradio、云存储或多用户服务。

## 文档导航

- [docs/ACTIVE_PLAN.md](docs/ACTIVE_PLAN.md)：当前里程碑和停止条件。
- [CURRENT_STATUS.md](CURRENT_STATUS.md)：当前已验证的能力状态。
- [docs/FINAL_DELIVERY_CLI.md](docs/FINAL_DELIVERY_CLI.md)：当前 CLI 交付指南。
- [docs/FINAL_DELIVERY_REPORT.md](docs/FINAL_DELIVERY_REPORT.md)：最终交付状态和证据边界报告。
- [docs/DATASETS.md](docs/DATASETS.md)：数据集角色、划分策略和下载约束。
- [AGENTS.md](AGENTS.md)：实现和验证的仓库规则。

面向 PM 的交接文档已弃用，并非当前规划来源。

Phase 1–4 的历史实现细节仍保留在 `docs/` 下按阶段划分的文档中。
