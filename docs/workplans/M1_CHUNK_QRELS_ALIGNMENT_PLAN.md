# M1 Chunk 质量与检索 Qrels 对齐实施计划

> 文件性质：当前阶段临时实施依据
> 计划版本：2.1
> 状态：M1-G2/G3.5 `accepted`；M1-G3 `ready`；M1-G4 `not_started`
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
      "acceptable_chunk_sets": [["chunk-A"]],
      "review_status": "reviewed"
    }
  ],
  "minimal_required_group_ids": ["g1"],
  "review_status": "reviewed"
}
```

规则：

- 单点事实优先只标一个包含答案且语义自足的 Chunk 集合；确有重复文本时，以新的
  完整数组记录等价集合，不与首选集合混为一个必需集合。
- 多跳问题把每个必需事实拆成独立 evidence group；每组至少命中一个主块或等价块，
  所有必需组都命中才算 all-evidence success。
- 一项原文证据跨 Chunk 时，标注覆盖该事实的最小 Chunk 组合；不得为了获得更高分而
  纳入整页或所有相邻块。
- 表格事实优先指向实际包含目标行列的表格 Chunk；表题或上下文块只有在回答确实需要
  时才作为另一必需组。
- qrels 必须记录 Chunk `content_hash`，用于发现 ID 未变但内容变化的失效情况；每个
  `acceptable_chunk_sets` 内层数组必须整体命中，数组之间是 OR 关系。

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

### 9.1 M1-G3 执行合同（2026-08-02）

#### 本批做什么

1. 新增一个确定性 qrels candidate 工具，只读取：
   - 94 条 `frozen_query_samples.jsonl`；
   - M1-G2 冻结的 `corpus_manifest.json`；
   - 六文档隔离重建的 `evidence_blocks.jsonl`。
2. 只为 86 条文档绑定查询生成 candidate；8 条非文档路由样本不生成
   Chunk qrels，但在摘要中显式计数。
3. 对每个原文证据组保留 `source_evidence`，并根据页码和证据类型约束生成：
   - 单 Chunk 候选；
   - 按文档阅读顺序相邻的最小多 Chunk 候选；
   - 候选 Chunk ID、`content_hash`、页码、类型、匹配方式和有上限的复核预览。
4. 输出两个分离合同：
   - `chunk_qrels_candidates.jsonl`：机器候选，始终是 `unreviewed`；
   - `qrels_review_queue.jsonl`：每个证据组一条，按无候选、多块、模糊、
     精确单块的优先级排序，同时生成独立的 review decision 模板。
5. 实现 fail-closed 冻结校验：只有显式 review decision 覆盖所有必需证据组，
   且 PDF/corpus/Chunk 哈希、Chunk ID 与内容哈希全部一致时，才能生成
   `frozen_chunk_qrels.jsonl`。
6. 在服务器对 M1-G2 真实 Chunk corpus 运行一次，保存完整本地产物和
   `outputs/sync/<run_id>/` 精选包，报告候选覆盖率和复核队列规模。

#### 本批不做什么

- 不把 normalized/compact/fuzzy 匹配自动标记为 `reviewed`；
- 不伪造人工复核人、复核时间或复核结论；
- 本轮没有外部复核决策文件，因此预期产出为 candidate + review queue；
  冻结器必须被测试为“缺少复核时拒绝冻结”，不生成伪 `reviewed` qrels；
- 不改写 `frozen_query_samples.jsonl`，不修改问题、原文证据或 Chunk；
- 不调用 LLM/VLM/MinerU API，不加载 BGE-M3/reranker，不重建 FAISS 索引；
- 不接入正式 Recall/MRR，不执行 M1-G4，不根据 candidate 调整检索参数。

#### 文件、验收和资源边界

- 预计新增 `scripts/build_m1_chunk_qrels.py` 和
  `tests/test_build_m1_chunk_qrels.py`；只在 reviewed qrels 真正冻结后才修改
  `scripts/eval_m1_query_retrieval.py`。
- 定向验收：候选可表达单块/最小多块，证据组和 Chunk 哈希可验证，
  未复核时冻结失败，缺失/错误决策、过期 corpus 或 Chunk 哈希均失败。
- 该工具是确定性 JSON/JSONL 处理，实现为 `local_only`；基于服务器既有六文档
  产物的真实运行为 `server_optional`，即使服务器有 GPU 也不使用。
- 停止条件：candidate/review queue 真实运行与 fail-closed 冻结验证完成后停止；
  没有真实 review decisions 时状态最高为 `ready`，不得报告 `frozen`。

### 9.2 M1-G3 执行结果（2026-08-02）

- 实现 `scripts/build_m1_chunk_qrels.py` 及定向测试，本地与服务器同范围
  17 项回归均通过；
- 最终服务器运行基于提交 `cdcc6f6` 和 M1-G2 corpus
  `m1-chunk-v3-g2-bca0893-20260802`；
- 94 条冻结样本中，86 条文档绑定查询生成 candidate，8 条非文档路由样本
  按合同排除；150/150 个证据组全部进入复核队列；
- candidate 分布：60 个 `exact_single`、19 个 `exact_multi`、2 个
  `exact_ambiguous`、54 个 `fuzzy`、15 个 `unmapped`；135/150 个证据组至少有
  一组候选；
- `chunk_qrels_candidates.jsonl`、`qrels_review_queue.jsonl` 和
  `review_decisions.template.jsonl` 分别为 86、150 和 150 条；
- 在真实 corpus 上将空白 review template 交给冻结器时，冻结器非零退出且
  没有产生 `frozen_chunk_qrels.jsonl`；同步包 manifest 与实际文件完全一致；
- 最终精选产物：
  `outputs/sync/m1_g3_chunk_qrels_candidates_v3_20260802/`；summary/result/manifest 均绑定
  同一 Git 提交，sync manifest 的文件范围、大小和 SHA256 全部校验通过。完整 candidate、复核队列和
  decision 模板仅保存在服务器完整输出目录，不向本地复制六文档 Chunk。
- 本批没有使用 GPU、LLM/VLM/MinerU API，没有重建索引或运行检索指标。
  由于尚无显式 review decisions，M1-G3 状态为 `ready`，不是 `frozen`。

### 9.3 M1-G3 冻结合同加固（2026-08-02）

现有 v1 candidate 已足以辅助定位原文证据，但在进入人工/独立复核前仍存在会使正式
评测失真的合同漏洞。本批只加固 qrels 生成与冻结边界，完成后重新生成复核材料；
不修改 Chunk、检索器、Router、QueryTransformer 或 Reranker，也不进入 M1-G4。

#### 本批必须修复

1. 将证据组输出统一为 `acceptable_chunk_sets`。每个内层数组表示一个完整且最小的
   必需 Chunk 集合；命中集合中的一部分不算命中，后续数组表示完整等价集合，不再用
   扁平 `acceptable_alternative_chunk_ids` 表达多 Chunk 替代关系。
2. `accept_candidate` 只能选择生成器提出的一个或多个完整候选集合，不能截取
   `exact_multi` 的部分 Chunk，也不能跨候选拼接；`replace` 允许复核者提交新集合，
   但仍须通过完整合同校验。
3. 所有进入 qrels 的 Chunk 必须存在、`is_indexable=true`、集合内部无重复，且不同
   可接受集合不得完全重复。选中 Chunk 的 `content_hash` 必须与冻结 corpus 一致。
4. 样本 ID、文档内 evidence group ID 必须非空且唯一；必需证据组必须得到且只得到
   一条显式决策。复核人、复核类型、理由和带时区 ISO-8601 时间均为必填字段。
5. candidate、review queue、decision template 与 frozen qrels 全部绑定：
   `samples_sha256`、`corpus_manifest_sha256`、`corpus_id`、Chunk 合同版本和源 PDF
   哈希。冻结结果额外记录 `review_decisions_sha256`，防止样本、语料或决策文件被
   替换后静默复用。
6. qrels schema 升级为 `m1-chunk-qrels-v2`。现有 v1 decision 模板不得迁移或自动
   继承复核状态；应基于同一冻结 corpus 重新生成 v2 candidate 和空白 decision 模板。

#### 验收与资源边界

- 增加针对性测试覆盖：多 Chunk 部分接受、跨候选拼接、不可索引 Chunk、重复样本或
  证据组、无时区复核时间、过期样本/manifest 哈希均被拒绝；合法的多 Chunk 主集合
  与完整替代集合可以冻结。
- 完成定向测试与既有 qrels/评测回归后，提交并同步服务器；使用 M1-G2 已冻结 corpus
  重新生成一次 v2 candidate、review queue 和 decision template，并再次验证空白决策
  无法冻结。
- 本批为确定性 JSON/JSONL 处理，属于 `local_only + server_optional`，不使用 GPU，
  不加载真实嵌入或重排序模型。
- 停止条件仍为 M1-G3 `ready`：只有用户另行提供真实、完整且通过 v2 校验的 review
  decisions 后才可冻结；不得在本批启动 M1-G4。

### 9.4 M1-G3 v2 加固结果（2026-08-02）

- 提交 `edcc03f` 将 schema 升级为 `m1-chunk-qrels-v2`，以
  `acceptable_chunk_sets` 表达完整必需集合与等价集合，并移除旧模板中的主块/扁平
  替代块字段；
- 冻结器已拒绝部分多块候选、跨候选拼接、不可索引 Chunk、重复样本/证据组、无时区
  时间、错误 Chunk hash、过期样本/manifest 绑定和旧 schema decision；合法多块及
  完整替代集合可以冻结；
- 本地与服务器的 qrels + M1 检索评测同范围 21 项回归通过；
- 在服务器同一 M1-G2 corpus 上重新生成 86 条 candidate、150 条复核队列和 150 条
  v2 decision 模板。候选分布保持 60 个 `exact_single`、19 个 `exact_multi`、2 个
  `exact_ambiguous`、54 个 `fuzzy` 和 15 个 `unmapped`；
- 所有 candidate、queue、template 与 summary/result 均绑定同一
  `samples_sha256` 和 `corpus_manifest_sha256`，精选包 manifest 的文件大小与 SHA256
  校验通过；空白 v2 decision 模板被冻结器非零拒绝，未生成 frozen qrels；
- 完整产物：`outputs/m1_g3_chunk_qrels_candidates_v4_20260802/`；精选产物：
  `outputs/sync/m1_g3_chunk_qrels_candidates_v4_20260802/`。本批未使用 GPU/API、未重建
  索引、未运行检索指标；M1-G3 仍为 `ready`，M1-G4 仍为 `not_started`。

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

### 9.5 M1-G3.5 十五个无候选证据组复核与通用 Chunk 修复（2026-08-02）

人工复核已经覆盖 v4 复核队列中的 15 个无候选证据组。复核结果证明其中既有可直接
绑定现有 Chunk 的标注对齐问题，也有转换器丢弃算法块、上游图题与正文粘连、图片无
可检索文本等 Chunk 语料问题。本批先修复通用处理合同并重建候选，不能在旧 corpus
上写入最终 qrels。

#### 本批做什么

1. 将 15 个无候选组分类为：现有 Chunk 可直接复核绑定、语料修复后绑定、证据不足
   排除。复核决定只记录到新的 corpus/qrels candidate 配套产物，不改写冻结查询文件。
2. 补全 MinerU `code`/`algorithm` 原始块转换：组合 `code_caption`、`code_body` 和脚注，
   保留为可索引的算法/代码 Chunk；不得按具体论文、页码或问题文本特判。
3. 对兼容全角字符执行 Unicode NFKC 检索规范化。`Chunk.text` 和原文证据保持原样，
   仅 `retrieval_text` 与 BM25 查询分词使用规范化值，避免破坏引用保真。
4. 增加保守的同页视觉图题修复：仅当短行几何、显式 Figure/Fig./Chart/Table 标记、
   紧邻无题视觉块、异常长混合文本和同页空正文槽同时成立时，才把图题前缀与溢出正文
   分开；修复来源写入 Chunk metadata。规则不得包含文档名、页码或样本措辞。
5. 原始 PDF 产品导入默认显式请求 MinerU OCR，同时保留 `--no-mineru-ocr`。公开 API
   没有独立的图片区域 OCR 开关，因此只对缺失图片证据的目标文档执行一次隔离
   `is_ocr=true` 对照；若仍无可用文本，则该组作为视觉证据缺口排除，不伪造 OCR/VLM
   内容，也不声称 API 已支持图片内部 OCR。
6. 本地回归通过后提交并同步服务器；基于修复后的转换器隔离重建六文档 corpus，重新
   生成 qrels candidate/review queue，并把 15 个已人工复核组编码为与新 corpus 绑定的
   部分 review decisions。旧 v4 candidate/template 只保留为历史产物。

#### 本批不做什么

- 不针对单个 PDF、页码、问题或答案字符串加入解析规则；
- 不切换到当前转换器尚不能完整消费的 MinerU v2 分页嵌套 JSON；
- 不调用额外 VLM，不从图片标题臆造图片内部数据，不修改人工证据原文；
- 不调整 Router、QueryTransformer、RRF、候选规模、Reranker 或检索参数；
- 不把 15 条部分决策冒充覆盖全部 150 证据组的 frozen qrels；
- 不重建 BGE-M3/FAISS 索引，不运行 M1-G4 正式检索评测。

#### 文件、验收和资源边界

- 预计修改 `docagent/parser/mineru_converter.py`、`docagent/schemas.py`、
  `docagent/retrieval/bm25_index.py`、`docagent/parser/mineru_api.py`、原始 PDF CLI 入口及
  对应定向测试；只更新与本批结论直接相关的状态/数据文档。
- 本地验收覆盖算法块保留、图题/正文分离、原文保真与检索 NFKC、OCR 默认及显式关闭、
  既有表格父子/跨页/句界回归。
- MinerU API 对照属于 `server_required` 的真实外部依赖验证但不需要 GPU；六文档转换和
  qrels 重建属于 `server_optional`。服务器即使有 GPU，本批也不加载 GPU 模型。
- 停止条件：新 corpus、qrels candidate 和 15 组部分复核决策完成并校验；图片 OCR
  对照若失败，记录为视觉证据缺口后停止。M1-G3 仍最高为 `ready`，M1-G4 保持
  `not_started`。

### 9.6 M1-G3.5 验收结果（2026-08-02）

- 提交 `a31f7f3` 完成通用 MinerU `code/algorithm` 字段保留、检索文本 NFKC、保守
  图题/正文分离、bbox 图题关联、OCR 默认显式开启和质量报告字段更新；本地与服务器
  同范围 109 项回归通过。
- 六文档使用既有 MinerU JSON 隔离重建为 1,239 个 Chunk、1,028 个可索引 Chunk，
  Chunk 合同错误为 0；新增 3 个 algorithm Chunk、2 个 code Chunk和 1 个从上游
  混合块恢复的 IMF 正文 Chunk。Figure 3 图题与正文已分离并关联到正确图表。
- 381 个源 Chunk 的原始文本含 NFKC 兼容字符；`Chunk.text` 保持原样，只有
  `retrieval_text` 和 BM25 查询侧被规范化。
- 对“科学营养餐桌”执行一次真实 MinerU API `vlm + is_ocr=true` 隔离对照；物理页
  20 的两张图片仍无 OCR/视觉文本，所需摄入量未出现在 content-list，因此未替换六文档
  基线解析，D04-009 作为视觉证据缺口排除。
- 新 corpus 为 `m1-chunk-v3-g35-a31f7f3-20260802`；基于它生成 v5 candidate。自动
  候选仍为 135/150 有候选、15/150 无候选，没有为提高覆盖率放宽类型或页码约束。
- 15 组人工复核结论已编码为独立部分 decision：13 个 `replace`、2 个 `exclude`，
  共选择 14 个均存在且可索引的 Chunk。冻结器确认部分 decision 无法生成 frozen
  qrels；其余 135 组仍需显式复核。
- 精选服务器产物：
  `outputs/sync/m1_g35_unmapped15_chunk_repairs_a31f7f3_20260802/`。本批没有重建
  BGE-M3/FAISS 索引或运行 M1-G4 指标，到此停止。

| 日期 | 版本 | 变更 | 原因 |
|---|---|---|---|
| 2026-08-02 | 1.0 | 建立双层 Gold、Chunk 修复先行和分批验收方案 | 六文档实测证明当前自动映射率仅 0.6000，且存在跨 Chunk、页码、OCR/序列化及表题错配问题 |
| 2026-08-02 | 1.1 | 冻结 M1-G1 大表阈值、父子角色和表题修复边界 | 避免父表退出文本检索后同时丢失结构化查询能力，并限制表题修复为可验证的通用模式 |
| 2026-08-02 | 1.2 | 将同页紧邻的显式表格 caption 纳入表题关联 | 表格子块必须携带标题，而 MinerU 可能把标题输出为独立 caption 块 |
| 2026-08-02 | 1.3 | 记录 M1-G1 实现和 104 项本地回归结果 | 表格父子 Chunk、表题关联、结构化父表接线和质量报告已达到本地 fixture 验证边界 |
| 2026-08-02 | 1.4 | 增加表题分配后的实际检索文本验收 | 服务器真实 MinerU 产物暴露换行/空格归一化差异，仅检查元数据会误报通过 |
| 2026-08-02 | 1.5 | 记录 M1-G2 六文档隔离重建验收 | 实际 MinerU 产物上的 Chunk/表格父子合同、表题检索文本与源语料不可变性均通过 |
| 2026-08-02 | 1.6 | 冻结 M1-G3 candidate、review queue 和 fail-closed 冻结边界 | 自动映射不等于内容复核；在缺少显式 review decisions 时不得伪造 reviewed qrels |
| 2026-08-02 | 1.7 | 记录 M1-G3 candidate 真实运行与冻结拒绝结果 | 150 个证据组已形成可复核队列，但没有显式复核决策，状态只能是 `ready` |
| 2026-08-02 | 1.8 | 加固 M1-G3 qrels v2 冻结合同并要求重生复核材料 | v1 无法完整表达多 Chunk 等价集合，且对部分候选、不可索引块和样本/决策版本漂移约束不足 |
| 2026-08-02 | 1.9 | 记录 qrels v2 本地/服务器验收与新复核材料 | v2 契约、输入绑定和 fail-closed 行为已验证，但尚无真实复核决策，不能进入 M1-G4 |
| 2026-08-02 | 2.0 | 纳入 15 个无候选组人工复核和通用 MinerU→Chunk 修复 | 人工复核证明旧候选失败同时包含标注对齐、算法块丢失、视觉图题粘连、全角检索表示和图片 OCR 缺口，必须先产生新 corpus 再编码决策 |
| 2026-08-02 | 2.1 | 记录 G3.5 通用修复、真实 OCR 对照、新 corpus 与 15 组部分决策 | 修复已通过真实六文档转换，图片内 OCR 缺口仍存在，部分复核不能越过完整冻结合同 |
