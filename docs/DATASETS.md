# DocAgent 数据集策略

> 仅记录数据集来源、已接受产物、划分策略与下载规则。

## 1. 当前策略

在当前 Phase 5 最终交付路径中：

```text
在本地准备小型、可复现的验证子集
-> 保留源文件、哈希、过滤报告、清单和预览
-> 仅在子集契约验收后运行正式检索/最终答案基准
```

不得静默下载大型数据集，也不得将子集准备视为基准评测。训练数据重建、SFT、
GRPO 和模型质量主张仍需明确批准。

Phase 5 的 MP-DocVQA 与 TAT-QA 验证子集仅是诊断/评测产物。不得转换为
SFT/GRPO 训练记录；未来训练必须使用独立训练集数据或明确批准的训练划分。

## 2. MP-DocVQA

当前角色：

- 多页文档问答；
- 检索评测；
- retrieved-reader SFT；
- 有依据的 GRPO；
- 答案与位置评测。

权威来源：

```text
RRC imdb_val.npy：
  问答元数据
  官方 OCR token 与框
  答案所在页信息

lmms-lab/MP-DocVQA val Parquet：
  按需使用的选定页图像
```

当前 Phase 1 训练/评测证据主要基于官方 OCR。不得描述为完整 MinerU 解析的
MP-DocVQA；未经明确批准不得下载完整 RRC 图像归档。

Phase 5 最终交付的本地子集准备：

```text
prepare_script = scripts/prepare_final_eval_subset.py
diagnostic_runner = scripts/run_final_eval_subset.py
local_input_dir = data/benchmark/mp_docvqa/val
local_inputs = val-00001-of-00029.parquet, val-00002-of-00029.parquet
output_root = outputs/final_eval/mpdocvqa_val_subset
status = implemented
benchmark_status = not_started
```

2026-06-29 本地冒烟从两个验证 parquet shard 恢复了 10 份页窗口文档和 55 条
问答记录，产出页窗口 PDF、`qa.jsonl`、`sample_manifest.jsonl`、
`filter_report.json`、`source_manifest.json` 和预览。它适合原始 PDF/OCR/页归因
准备，但不是 MinerU OCR 验收运行，也不是最终答案质量基准。

除非后续提供 MinerU/OCR/检索产物，`scripts/run_final_eval_subset.py` 当前只将
MP-DocVQA 视为页清单就绪性，且不会单独评估其答案质量。

AnswerPolicy v3 训练数据试验可使用
`/root/autodl-tmp/datasets/mp_docvqa/parquet_train` 中的 MP-DocVQA train
parquet shard。此类运行必须写入 `outputs/training_prep/`，在页窗口子集准备时传入
`--mpdocvqa-split train`，并在构建 v3 SFT 记录前通过 MinerU API 物化证据。不得将
`outputs/final_eval/` 的验证产物重用为训练数据。

## 3. 冻结的 Phase 1 产物

代表性产物：

```text
data/benchmark/mp_docvqa_train_sft_retrieved_clean.jsonl
data/benchmark/mp_docvqa_dev_sft_retrieved_clean.jsonl
data/benchmark/mp_docvqa_train_grpo_retrieved_clean.jsonl
```

在 Phase 2 期间：

- 不改变文档划分；
- 不重建 SFT/GRPO 数据；
- 不改变 gold answer/location 字段；
- 不重启 hard-subset 挖掘或 GRPO sweep。

## 4. 真实文档 ScenarioSet

Phase 2B 应使用小型公开冒烟集：

```text
3-5 份文档
每份文档 3-5 个经人工核对的问题
```

覆盖以下类型：

1. 文本密集 PDF；
2. 扫描件/图像 PDF；
3. 含常规表格和图的 PDF。

ScenarioSet 用于功能验证，不用于训练。Git 中只保存安全元数据、哈希、预期证据
和报告。

## 5. M1 查询意图与检索冻结集

本地与服务器分别保留未跟踪目录：

```text
data/benchmark/m1_query_routing/
  frozen_query_samples.jsonl
  sample_summary.md
  generation_issues.md
```

冻结集包含 94 条样本：86 条绑定 6 份真实 PDF，8 条为不绑定文档的
`no_retrieval` 或 `clarification_required` 路由样本。中文文档只使用中文查询，
英文文档只使用英文查询；`gold_evidence_groups` 保存可与原文 Chunk 核对的证据
文本，不作为训练目标。

服务器语料准备运行 `m1_frozen_corpus_v1_20260730` 已使用 MinerU API `vlm`
处理 6 份 PDF，并建立统一 Chunk 与真实 BGE-M3 索引，状态为
`real_model_verified`。运行 `m1_query_retrieval_baseline_20260730` 已完成真实
查询与检索首次基线，状态为 `benchmark_evaluated`：94 条查询、150 个 Gold
evidence group、Gold→Chunk 映射率 0.6000，计划查询 Hybrid+Reranker 的端到端
Recall@5/MRR@10 为 0.4000/0.5087。该运行尚未达到 `accepted`；不得将首次基线
反向用于修改样本、构造样本专属规则或训练模型。

M1-F2/F3 修正后运行 `m1_f2_f3_workflow_eval_20260801` 复用同一冻结集、
同一六文档 Chunk 和索引，生成 94 条查询预测和 432 条四检索器对照。
普通正文事实在 Hybrid+Reranker 相对 Hybrid 下的 provisional
Recall@5/MRR@10 差值为 +0.0345/+0.0854，复杂分析为 -0.0625/-0.0012。
通用检索范围 Gold→Chunk 自动映射率仍为 0.5882，因此该运行状态为
`benchmark_evaluated`，不构成未复核 Chunk qrels 上的检索验收。该冻结集仍不得用于
Prompt、RRF、候选规模或 Reranker 参数调优。

M1-G3.5 使用提交 `a31f7f3` 和既有 MinerU JSON 重建
`m1-chunk-v3-g35-a31f7f3-20260802` corpus：1,239 个 Chunk、1,028 个可索引 Chunk。
旧 v4 candidate/template 因 Chunk 内容哈希和 corpus manifest 变化而失效。v5 仍将
150 个证据组全部放入复核队列：135 组有自动候选、15 组无自动候选。15 组人工审查
已单独编码为 13 个 `replace` 和 2 个 `exclude`；其中 D04-009 的真实 MinerU
`is_ocr=true` 对照仍无法提取图片内数值。其余 135 组独立复核已在 M1-G3.6 完成；
合并后的 150 个证据组决定分布为 95 个
`accept_candidate`、13 个 `replace`、42 个 `exclude`。v2 使用完整
`acceptable_chunk_sets` 表达 AND/OR 证据集合，并绑定样本、corpus manifest、PDF、
Chunk 内容和复核决策哈希；全部校验通过后生成 86 条 `frozen_chunk_qrels.jsonl`，
其中 55 条可进入后续 Recall/MRR，31 条排除。服务器完整产物位于
`outputs/m1_g3_frozen_qrels_qwen37_20260802/`。

M1-G4 已在上述 55 条 eligible 中的 54 条检索 workflow 上完成正式测评；1 条
`document_summary` 不进入 Top-K 指标。运行使用当前 Qwen API、真实 BGE-M3/FAISS
和 bge-reranker-v2-m3，生成 94 条查询预测和 432 条检索明细。Policy-selected 的
Group Recall@5/All-groups@5/MRR@10 为 0.5125/0.5741/0.7799；该结果状态为
`benchmark_evaluated`，不得作为训练数据或用于在同一冻结集上反复调参。服务器精选
产物位于 `outputs/sync/m1_g4_reviewed_retrieval_20260802/`。

## 6. 延后数据集

### TAT-QA

本地子集准备状态为 `implemented`，基准评测为 `not_started`。

当前角色：

- 表格 + 段落问答；
- 计算器；
- 数值归一化；
- Numeric Accuracy；
- 类型感知奖励。

Phase 5 最终交付的本地子集准备：

```text
prepare_script = scripts/prepare_final_eval_subset.py
diagnostic_runner = scripts/run_final_eval_subset.py
local_input = data/benchmark/tatqa/tatqa_dataset_dev.json
output_root = outputs/final_eval/tatqa_dev_subset
status = implemented
benchmark_status = not_started
```

2026-06-29 本地冒烟选择了 80 个验证问题，并在 `table_arithmetic`、
`table_lookup`、`table_text` 和 `text` 桶之间保持平衡。TAT-QA 是结构化表格/文本
问答数据，不是原始 PDF，不能描述为 MinerU 解析证据。它用于在最终模型训练或评测
之前测试表格查找、简单计算和证据使用行为。

本地诊断运行器可对 TAT-QA 样本执行确定性表格工具。诊断可能暴露答案/引用缺口，
但不是正式 TAT-QA 基准，也不验证 Qwen 答案质量。当前诊断产物为
`results.jsonl`、`summary.json`、`summary.md`、`preview.json` 和
`manual_review.md`。

### InfographicVQA

状态：`deferred`

未来角色：

- OCR + 视觉审查；
- 图像区域证据；
- OCR-only 与 OCR+VLM 比较。

在明确启动视觉推理/VLM 工作前不得添加 InfographicVQA。

## 7. 划分与泄漏策略

所有基准划分必须保持文档级。同一 `doc_id` 不得跨 train/dev/test。推理和修复绝不
能接收：

- gold answer；
- gold location；
- assistant target。

应区分：

```text
检索成功
以已检索证据为条件的 reader 成功
端到端成功
```

## 8. 数据质量要求

未来添加任何数据集时，记录：

- 来源和版本；
- 字段映射；
- 归一化；
- 证据/位置映射；
- 文档级划分；
- schema 验证；
- 答案覆盖率；
- accepted/deferred/dropped 计数。

不得将 schema/规则验证通过率描述为人工质量批准。

## 9. 下载策略

默认行为：

```text
离线/仅本地
```

任何大型下载都需要用户明确确认。不得静默下载：

- 完整图像归档；
- 完整数据集 shard；
- 模型权重；
- 带签名的临时 URL。
