# DocAgent 最终交付 CLI 指南

更新日期：2026-07-30

这是个人使用 DocAgent MVP 的仅限 CLI 的交付界面。本文说明如何使用当前实现，
而不是如何运行新训练或主张基准质量。当前能力状态见 `CURRENT_STATUS.md`。

## 范围

```text
文件或既有 doc_id
-> 持久化 Chunk
-> 查询意图 / 按需查询变换 / 检索 / 可选确定性工具
-> AnswerPolicy
-> 答案、证据、引用和追踪产物
```

支持文本文件、既有 MinerU 输出，以及通过 MinerU API 导入的原始 PDF。MinerU
结果可包含 `*_content_list_v2.json`、Markdown、表格 HTML 和图像元数据；可用时
这些字段会保留在证据与引用记录中。

## 前置条件

正常使用需要所选执行配置对应的资源。`user_best` 需要真实 MinerU API 凭证、
查询意图/查询变换 API 配置、BGE-M3、交叉编码器重排序器、Qwen3 和已配置的
AnswerPolicy adapter。缺少资源时会返回结构化失败，而非静默回退。

`self_test` 仅用于本地或 CI 检查，不能描述为真实模型运行。

JSON 输出中的 `query_decision` 保存意图、检索路径和 Metadata 前置约束；
`query_plan` 保存最多 4 条检索查询及变换动作。两者均逐字保留
`original_question`，AnswerPolicy 不会收到改写后的问题。

## 常用命令

询问新文件：

```powershell
python scripts\docagent_cli.py --file <path> --question "<question>"
```

询问已登记文档：

```powershell
python scripts\docagent_cli.py --doc-id <doc_id> --question "<question>"
```

执行轻量本地检查：

```powershell
python scripts\docagent_cli.py --execution-profile self_test --file <path> --question "<question>"
```

输出面向使用者的文本而非 JSON：

```powershell
python scripts\docagent_cli.py --file <path> --question "<question>" --stdout-format text
```

列出已登记文档、检查索引或准备缺失索引：

```powershell
python scripts\docagent_cli.py --list-documents --db-path outputs\docagent.db
python scripts\docagent_cli.py --doc-id <doc_id> --check-index --db-path outputs\docagent.db
python scripts\docagent_cli.py --doc-id <doc_id> --prepare-index --db-path outputs\docagent.db
```

在不调用模型或数据集的情况下运行本地交付契约检查：

```powershell
python scripts\check_final_delivery_readiness.py
```

仅在准备好的服务器上运行诊断性的编排：

```powershell
python scripts\run_final_delivery_benchmark_gate.py --run-id final_delivery_gate_probe
```

## 输出契约

普通问答 JSON 包含：

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

引用和证据记录会标识文档、页、块和块类型。源文件提供时，表格和图像记录还会
包含表格/图像元数据与预览。进度仅写入 stderr，以保持 JSON stdout 可由机器读取。

## 本地路径

```text
outputs/docagent.db             已登记文档状态
data/documents/<doc_id>/        缓存的文档源文件与解析资源
outputs/cli/<run_id>/           每次运行的答案与追踪产物
outputs/final_eval/             可重新生成的诊断输出
```

原始数据集、生成输出树、模型权重、日志、数据库和密钥均是本地产物，不得提交。

## 边界

- 不存在已验收的 MP-DocVQA/TAT-QA 最终答案基准。
- 不存在正式视觉问答基准验收。
- 最终交付基准门控仅用于诊断。
- 未经明确批准，不得启动新的 SFT/GRPO 训练、变更检查点或将验证子集作为训练
  数据。
- 真实模型或服务器操作请遵循 `docs/GPU_SERVER_BOUNDARY.md` 和
  `docs/SERVER_SETUP.md`。
