# M1 Chunk 质量与检索 Qrels 对齐实施计划

> 文件性质：当前阶段临时实施依据
> 计划版本：1.5
> 状态：M1-G2 `accepted`；M1-G3/M1-G4 `not_started`
> 建立日期：2026-08-02
> 适用范围：六文档 MinerU→Chunk 处理、原文证据到 Chunk qrels 对齐，以及依赖该 qrels 的检索评测

## 1. 当前缺口

1. 94 条冻结查询保存的是原文证据，150 个 `gold_evidence_groups` 尚未形成经复核的
   Chunk qrels；当前评测运行时只做自动字符串映射。
2. 自动映射仅成功 90/150 个证据组，且所有成功项都只映射到一个 Chunk，无法表达
   跨 Chunk 证据和多跳问题的最小必需 Chunk 组合。
3. 当前正文 Chunk 只对超过 1200 字符的 `body/list_item/reference` 做句界切分；表格
   不做父子切分。
4. 六文档中存在 MinerU 表格块与表题错配或相邻表格粘连。例如表 14 的数值表块没有
   表题，而包含“表 14/表 15”说明的后续块实际保存的是表 15 数据。
5. 当前未复核映射被用于 provisional Recall/MRR，导致解析、切分、标签对齐和检索器
   错误混在同一个指标中。

## 2. 2026-08-02 六文档只读核查结果

服务器核查产物：

```text
outputs/sync/m1_qrels_chunk_audit_20260802/summary.json
outputs/sync/m1_qrels_chunk_audit_20260802/alignment_diagnostics.json
```

核查范围和结果：

- 6 份文档、1,222 个 Chunk、1,016 个可索引 Chunk；
- 正文主体 Chunk 的文本长度上限约为 1,185 字符，未发现超过当前 1,200 字符阈值的
  未切分正文；
- 30 个结构化表格中有 13 个检索文本超过 1,200 字符，最大 2,558 字符；最大表格为
  26 行或 12 列，但没有大到足以仅凭长度判定全部必须拆分；
- 60 个未映射证据组的诊断性归因包括：12 个相邻多 Chunk 覆盖、5 个页码不一致、
  28 个 OCR/公式/表格序列化差异、15 个原文片段未被当前 Chunk 文本充分保留或并非
  可直接逐字对齐；
- 11 条表格查询中只有 6 条通过当前自动映射得到 Chunk ID；多个失败项在标注页上
  已存在明确目标表格，说明主要是 qrels 对齐合同失败，而不是表格内容完全缺失；
- 存在大量短正文原始块，但其中既有应组合的连续提示/段落，也有应保留为独立项的
  列表条目，不能使用统一的最小字符数盲目合并。

上述自动失败归因只用于建立复核队列，不直接写成最终 qrels。

## 3. 已确定方案

### 3.1 双层 Gold，而不是二选一

保留两种相互独立的事实层：

1. `source_evidence`：现有原文证据，保存物理页、标注页、定位说明、原文内容和证据
   类型；它不随 Chunk 边界改变。
2. `chunk_qrels`：绑定冻结的 PDF 哈希、MinerU 配置、Chunk 合同版本和 corpus
   manifest；它只用于检索指标。

不得从单个最终 Chunk 反向生成问题并把该 Chunk 自动设为 Gold。这样会让问题生成受
当前切分方式影响，并人为提高词面召回。

### 3.2 Chunk qrels 最小合同

每条文档绑定查询至少保存：

```json
{
  "sample_id": "D01-001",
  "doc_id": "...",
  "corpus_id": "...",
  "chunk_contract_version": "docagent_chunk_v3-or-later",
  "source_pdf_sha256": "...",
  "evidence_groups": [
    {
      "group_id": "g1",
      "requirement": "required",
      "primary_chunk_ids": ["chunk-A"],
      "acceptable_alternative_chunk_ids": [],
      "review_status": "reviewed"
    }
  ],
  "minimal_required_group_ids": ["g1"],
  "review_status": "reviewed"
}
```

规则：

- 单点事实优先只标一个包含答案且语义自足的主 Chunk；确有重复文本时，等价块放入
  `acceptable_alternative_chunk_ids`，不与主 Chunk 混为一个必需集合。
- 多跳问题把每个必需事实拆成独立 evidence group；每组至少命中一个主块或等价块，
  所有必需组都命中才算 all-evidence success。
- 一项原文证据跨 Chunk 时，标注覆盖该事实的最小 Chunk 组合；不得为了获得更高分而
  纳入整页或所有相邻块。
- 表格事实优先指向实际包含目标行列的表格 Chunk；表题或上下文块只有在回答确实需要
  时才作为另一必需组。
- qrels 必须记录 Chunk `content_hash`，用于发现 ID 未变但内容变化的失效情况。

### 3.3 Chunk 修复先于最终 qrels 冻结

实施顺序固定为：

```text
通用 Chunk 质量修复
-> 六文档受控重建
-> 冻结 corpus manifest
-> 生成 qrels candidate 与复核队列
-> 完成人工/独立复核
-> 使用 reviewed qrels 重跑检索评测
```

不得先在当前 Chunk ID 上完成最终 qrels，再修改切分导致全部失效。

## 4. Chunk 修复边界

### 4.1 本阶段必须处理

1. **相邻表格与表题关联**：保留表题、表号、脚注和数据表之间的正确关系；禁止把
   后一张表的数据错误挂到前一张表题下。
2. **大表父子 Chunk**：只有在序列化长度或行数超过明确阈值时，保留完整父表结构，
   并生成按连续行分组的检索子 Chunk。每个子 Chunk 强制复制表题、完整表头、单位、
   section path、页码、父表 ID 和行范围。
3. **检索与结构化查询分工**：父表继续供结构化表格索引使用；有子块时，文本检索
   默认使用子块，避免父子重复占据 Top-K。
4. **正文切分回归**：保持“跨页处理后再按句界切分”和 1,200 字符上限；只修复能由
   通用规则证明的语义断裂，不为现有 Gold 长片段反向合并 Chunk。
5. **短块审计**：区分列表项、标题、公式邻接文本和真正的碎片段落。未形成可靠通用
   规则前只报告，不进行全局短块合并。

M1-G1 固定参数与角色字段：

- 当 `table_rows > 12` 或 `table_markdown > 1800` 字符时生成行组子块；
- 子块按连续行贪心分组，每组最多 12 行，且序列化 Markdown 尽量不超过 1800 字符；
- 原表设置 `table_role=structured_parent`、`exclude_from_retrieval=true`、
  `include_in_structured_table_index=true`；
- 子表设置 `table_role=retrieval_child`、`table_parent_id`、`row_start/row_end`、
  `include_in_structured_table_index=false`，并复制完整表头、表题、单位、脚注和溯源；
- 表题修复处理两种确定性模式：同页紧邻的显式表格 `caption` 块，以及连续表格中
  “前表无题，后表题包含多个明确表号”的合并表题；后者按表号拆分并依阅读顺序
  回填，不使用文档名、页码或查询文本。

### 4.2 暂不处理

- 复杂多级表头的完全恢复；
- 基于单个冻结问题的 Chunk 合并或阈值调整；
- 新 VLM、OCR 或 MinerU 模型切换；
- Prompt、RRF、候选规模和 Reranker 参数优化；
- 最终答案质量评测。

## 5. 模块与文件范围

预计修改：

- `docagent/parser/mineru_converter.py`
- `docagent/ingestion/quality.py`
- `docagent/retrieval/table_index.py`
- `docagent/retrieval/hybrid_retriever.py`
- `tests/test_mineru_converter.py`
- `tests/test_ingestion_quality_report.py`
- `tests/test_table_index.py`
- 新增一个只负责生成/校验 Chunk qrels candidate 的脚本及其定向测试
- `scripts/eval_m1_query_retrieval.py`：只在 reviewed qrels 合同完成后接入，不提前
  改写当前 provisional 结果
- 本计划、`docs/ACTIVE_PLAN.md`，以及验收完成后的稳定状态文档

不修改查询 Router、QueryTransformer、检索融合、Reranker 和 AnswerPolicy。

## 6. 验收测试

### 6.1 本地确定性测试

1. 表题与相邻数据表正确关联，不能跨表串联；
2. 大表子块均携带完整表头、表题、父表 ID、行范围和稳定 ID；
3. 小表保持单块，不发生无意义拆分；
4. 有子块的父表仍可被结构化表格索引读取，但不与子块一起重复进入文本检索；
5. 正文跨页、句界切分、邻接关系和 `content_hash` 回归通过；
6. qrels candidate 能表达单点主块、等价块和多组最小必需证据；
7. 未复核 qrels 不能进入正式检索指标。

### 6.2 服务器真实产物验证

1. 使用既有 MinerU 解析结果重建六文档 Chunk，不再次调用 MinerU API；
2. 六文档 Chunk 合同错误为 0，索引重新加载通过；
3. 表 14/表 15 等已知结构问题通过通用规则修正，不使用文档名、页码或问题文本硬编码；
4. 输出新旧 Chunk 数量、类型、长度、父子表和异常块对照；
5. 生成 86 条文档绑定查询的 qrels candidate 和最小复核队列；
6. 只有 `review_status=reviewed` 且 hash/版本一致的样本才能参与正式 Recall/MRR。

## 7. 资源边界

- 代码、fixture、qrels schema 和候选生成属于 `local_only`。
- 基于现有 MinerU JSON 的六文档 Chunk 重建属于 `server_optional`，不需要 GPU。
- BGE-M3 索引重建与正式检索重跑属于 `server_required`，需要 GPU。
- 本阶段不重新调用 MinerU API，不下载模型或数据。

## 8. 迁移策略

- 保留 `frozen_query_samples.jsonl` 原样，不把 Chunk ID 回写到原始样本文件。
- 新 qrels 文件单独版本化，并绑定 corpus manifest 与 Chunk content hash。
- 旧 `gold_chunk_mapping.jsonl` 继续作为 `automatic_source_alignment` 诊断产物，不能
  改名为 reviewed qrels。
- Chunk 合同或内容改变时，旧 qrels 自动失效并重新生成候选；人工复核状态不得静默
  继承。

## 9. 停止条件

本阶段分批执行：

1. M1-G1：表格关联、大表父子 Chunk 与质量报告的本地实现和测试；
2. M1-G2：六文档无 GPU 重建与 Chunk 质量对照；
3. M1-G3：qrels candidate 生成、复核和冻结；
4. M1-G4：GPU 索引重建与 reviewed-qrels 检索评测。

每批完成后停止并报告；不得自动进入下一批，更不得根据冻结评测结果调检索参数。

## 10. 方案变更记录

### M1-G1 本地验证结果（2026-08-02）

- 已实现同页紧邻显式表题关联，以及连续表格的多表号组合表题拆分；
- 已实现基于 12 行/1800 Markdown 字符阈值的表格父子 Chunk；
- 结构化父表退出 BM25/Dense，但仍由 `TableRelationalIndex` 使用；检索子表不重复
  进入结构化索引；
- 质量报告新增物理表、表格 Chunk、拆分父表和检索子表计数，通用 Chunk 合同增加
  父子表角色校验；
- 正文 1200 字符句界切分、跨页逻辑和短块策略保持不变；
- MinerU 转换、质量报告、表格索引、metadata/hybrid 检索、Phase 2、文档导入、
  Phase 5 CLI 与表格工具相关回归共 104 项通过；
- 本批仅使用本地 fixture 和确定性回归，状态为 `mock_verified`；尚未重建六文档，
  也未生成新的 Chunk qrels。

### M1-G2 服务器重建中发现的阻断问题（2026-08-02）

- 六文档首次隔离重建显示 Chunk 合同错误为 0，表 14/表 15 的
  `table_caption` 元数据也已分开；
- 但表 15 的 `text/retrieval_text` 仍保留旧组合表题中的表 14 描述。根因是
  MinerU 以多项 caption 输出时，`table_caption` 使用换行拼接，而
  `table_context` 使用空格归一化，旧逻辑的精确字符串替换失败；
- M1-G2 验收因此增加：表题分配不仅检查 `table_caption`，还必须检查
  实际 `text/retrieval_text` 不含其他相邻表的表题段；修复后重新运行定向回归和
  六文档隔离重建，之前的首次重建不作为验收结果。

### M1-G2 验收结果（2026-08-02）

- 最终修复提交：`bca0893`；本地与服务器同范围回归均为 90 项通过；
- 使用六文档既有 MinerU JSON 隔离重建，Chunk 总数 1,222→1,233，可索引
  Chunk 1,016→1,022；新增的 11 个 Chunk 全部为大表行组检索子块；
- 30 个物理表保持不变，其中 5 个大表成为 `structured_parent`，生成 11 个
  `retrieval_child`；结构化表索引仍只接收 30 个物理表；
- Chunk 合同错误、表格父子合同错误均为 0，表 14/表 15 的元数据与
  `retrieval_text` 均完成分离；
- 重建前后旧 `data/documents/<doc_id>/evidence_blocks.jsonl` 哈希完全一致；
  新 corpus 仅保存在隔离输出目录；
- 服务器精选产物：`outputs/sync/m1_g2_chunk_rebuild_bca0893_20260802/`；
- 本批未调用 MinerU API、未生成 BGE-M3/FAISS 索引、未生成 qrels，到此停止。

| 日期 | 版本 | 变更 | 原因 |
|---|---|---|---|
| 2026-08-02 | 1.0 | 建立双层 Gold、Chunk 修复先行和分批验收方案 | 六文档实测证明当前自动映射率仅 0.6000，且存在跨 Chunk、页码、OCR/序列化及表题错配问题 |
| 2026-08-02 | 1.1 | 冻结 M1-G1 大表阈值、父子角色和表题修复边界 | 避免父表退出文本检索后同时丢失结构化查询能力，并限制表题修复为可验证的通用模式 |
| 2026-08-02 | 1.2 | 将同页紧邻的显式表格 caption 纳入表题关联 | 表格子块必须携带标题，而 MinerU 可能把标题输出为独立 caption 块 |
| 2026-08-02 | 1.3 | 记录 M1-G1 实现和 104 项本地回归结果 | 表格父子 Chunk、表题关联、结构化父表接线和质量报告已达到本地 fixture 验证边界 |
| 2026-08-02 | 1.4 | 增加表题分配后的实际检索文本验收 | 服务器真实 MinerU 产物暴露换行/空格归一化差异，仅检查元数据会误报通过 |
| 2026-08-02 | 1.5 | 记录 M1-G2 六文档隔离重建验收 | 实际 MinerU 产物上的 Chunk/表格父子合同、表题检索文本与源语料不可变性均通过 |
