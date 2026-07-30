# DocAgent M1 RAG 查询与检索阶段失败分析报告

> 报告日期：2026-07-30
> 对应运行：`m1_query_retrieval_baseline_20260730`
> 对应代码：`dfb0a2f`
> 当前状态：`benchmark_evaluated`，未达到 `accepted`
> 报告范围：冻结样本、Gold→Chunk 对齐、意图识别、查询动作、路由、查询变换、
> BM25、BGE-M3 Dense、Hybrid、RRF、bge-reranker-v2-m3 及评测器覆盖边界
> 范围外：最终答案正确率、忠实度、引用支持度、AnswerPolicy 质量、SFT/GRPO

## 1. 执行结论

本次评测不能简单解释为“当前 RAG 的 Recall@5 只有 0.4”或“查询重写和重排
无效”。低分由三类问题叠加产生：

1. **样本与运行契约不一致。**
   150 个原文 Gold evidence group 只有 90 个能够稳定映射到最终 Chunk，
   映射率为 0.6000；54/94 条查询动作标签在当前 `QueryPlan` 契约下不可能命中，
   20/94 条必需路由标签也不可能由当前意图策略产生。
2. **评测器没有执行所有意图对应的真实系统 workflow。**
   文档摘要、表格查询、视觉查询在主系统中具有专用工具或额外步骤，但本次
   检索评测把全部 86 条文档内样本统一送入四种文本检索配置。部分按意图统计
   只是“代理检索指标”，不是实际生产执行链的端到端成绩。
3. **系统存在真实的查询侧与后检索问题。**
   `clarification_required` 识别、复杂分析意图区分、受保护术语保留、查询变换
   Schema 稳定性、多查询 RRF、重排器只使用第一条子查询等问题，均可由代码和
   本次产物直接确认。

因此，本次运行的正确用途是：

- 作为第一轮故障定位基线；
- 分离数据构建、Chunk 对齐、查询决策和实际检索问题；
- 为下一版评测合同与系统修正确定优先级。

它不适合直接用于：

- 宣布 RAG 已通过或未通过最终验收；
- 比较模型训练收益；
- 为同一冻结集增加样本专属 prompt、路由规则或文本匹配规则；
- 评价表格结构化查询、文档摘要或 VLM 视觉理解的实际质量。

## 2. 证据来源与运行事实

### 2.1 项目证据

- 冻结样本：
  `data/benchmark/m1_query_routing/frozen_query_samples.jsonl`
- 样本汇总：
  `data/benchmark/m1_query_routing/sample_summary.md`
- 生成问题记录：
  `data/benchmark/m1_query_routing/generation_issues.md`
- 评测器：
  `scripts/eval_m1_query_retrieval.py`
- 查询链：
  `docagent/query/`
- 检索链：
  `docagent/retrieval/`
- 主 CLI 调度：
  `scripts/docagent_cli.py`
- 完整服务器产物：
  `outputs/m1_query_retrieval_baseline_20260730/`
- 精简服务器产物：
  `outputs/sync/m1_query_retrieval_baseline_20260730/`

### 2.2 运行规模

- 查询样本：94 条；
- 文档内查询：86 条；
- 无文档通用路由查询：8 条；
- 中文查询：44 条；
- 英文查询：50 条；
- 文档：6 份；
- Gold evidence group：150 组；
- 检索明细：`86 × 2 种查询形式 × 4 种检索器 = 688` 条；
- 查询模型：`qwen3.7-max-2026-05-17`；
- 稠密模型：BGE-M3；
- 重排模型：bge-reranker-v2-m3；
- GPU：RTX 4090D。

### 2.3 本次没有发生的运行错误

本次不存在 GPU 不可用、模型缺失、API 配置缺失、FAISS 加载失败、服务器进程
崩溃或 Schema 文件无法读取等基础设施故障。查询阶段和检索阶段均成功结束，
同步包的文件大小与 SHA256 全部核验通过。

报告中的“失败”主要指：

- 样本或评测合同失配；
- 模型输出未达到预期；
- 查询/检索质量退化；
- 系统声明的路由没有真正执行；
- 当前评测无法覆盖某项生产能力。

## 3. RAG 检索样本应该如何构建

### 3.1 不应该在“只基于原文”和“只基于 Chunk”之间二选一

检索评测需要同时保留两层 Gold：

1. **原文证据层（source-level evidence）**
   - 证明问题确实可以由输入 PDF 回答；
   - 保存物理页、标注页码、版面区域、表格/图片标识、原文 span 或事实 nugget；
   - 不随 Chunk 边界变化；
   - 用于评估解析、切分、溯源、答案覆盖和引用。
2. **检索相关性层（chunk-level qrels）**
   - 绑定已经冻结的可检索语料版本；
   - 保存与查询相关的一个或多个 `chunk_id`、内容哈希和相关性等级；
   - 用于 Recall@K、MRR、nDCG 等检索指标；
   - Chunk 版本变化后必须重新解析映射并复核，不能沿用旧 ID。

标准 IR 基准通常以 `corpus + queries + qrels` 评估检索对象；BEIR 明确使用这类
标准格式。[BEIR](https://arxiv.org/abs/2104.08663)
TREC RAG 则进一步把检索段落的 qrels 与回答事实 nuggets 分开，说明检索相关性
和最终回答覆盖本来就是两个不同的 Gold 层。
[TREC RAG evaluation](https://trec-rag.github.io/annoucements/evaluation/)

### 3.2 推荐的样本构建顺序

对本项目这种“每次输入一份 PDF，再建立该文档索引”的 RAG，推荐流程为：

1. 冻结 PDF 来源哈希、MinerU 版本、解析参数、Chunk 合同版本和索引版本；
2. 从原文、真实用户问题或面向原文的人工/AI 阅读生成候选查询，避免只根据单个
   Chunk 反向编写问题；
3. 标注原文证据：
   `physical_page + printed_page + element/bbox + verbatim_span/nugget + evidence_type`；
4. 运行正式 MinerU→Chunk 处理流程；
5. 将每组原文证据解析为一个或多个 `gold_chunk_ids`；
6. 对跨 Chunk、表格、图片、OCR 差异和无法映射项进行复核；
7. 将“原文存在但索引不可达”的样本保留为 ingestion/chunking 失败，不得直接
   当成检索器失败；
8. 正式检索指标只使用已经复核的 Chunk qrels；同时报告原文证据到 Chunk 的
   对齐覆盖率；
9. Chunk 合同变更后重建 qrels，并用独立的开发集调试，冻结测试集只做验收。

### 3.3 为什么不建议只从最终 Chunk 直接生成问题

直接构造“Chunk→问题→同一 Chunk ID”虽然容易得到稳定 qrels，但会产生新的偏差：

- 问题容易复用 Chunk 原词，BM25 和 Dense 检索被人为简化；
- 缺少跨 Chunk、跨页、多跳、表格与图文联合问题；
- 无法发现解析丢失、切分破坏语义、标题与正文断开等 ingestion 问题；
- Chunk 策略本身变成了问题生成器的一部分，评价结果可能只证明系统能找回
  自己用来造问题的文本。

因此，**问题应主要面向原文构建，检索 Gold 必须在最终 Chunk 语料上落地并复核**。
这是比当前“原文证据后置自动匹配 Chunk”更稳健的双层设计。

### 3.4 当前样本构建对结果的具体影响

当前样本从 PDF 原文构建，保存物理页和 `verbatim_content`，但没有在最终
`docagent_chunk_v3` 产物上生成经复核的 qrels。评测时才通过以下规则自动映射：

- 相同物理页；
- 兼容的 `evidence_type`；
- 归一化包含匹配；
- 失败后使用单个 Chunk 的最长连续字符覆盖率，阈值 0.65。

该映射存在以下限制：

- 一组原文证据跨两个或多个 Chunk 时，fallback 不会组合多个 Chunk 的覆盖率；
- `heading`、图题、表题和邻近正文可能在 MinerU→Chunk 中采用不同内容类型；
- PDF 文本层去断词、OCR、公式、连字符、表格 Markdown 和 MinerU 文本不完全一致；
- `source_locator` 没有参与解析，只被原样记录；
- 对图表样本，生成说明明确记录部分 `verbatim_content` 来自图题、邻近文字或
  数据来源，真正图内标签放在 `visible_text_verbatim`，这与“figure Gold 必须
  映射到 image/figure Chunk”的规则不完全一致；
- 物理页与文档标注页码虽然在数据思想上有区分，但当前映射只使用
  `physical_pages`；
- 映射结果没有人工/独立模型复核。

这足以解释为什么目标证据位置存在于原文，但无法与处理后的 Chunk 完全匹配。

## 4. Gold→Chunk 对齐失败分析

### 4.1 总体结果

| Gold 类型 | 已映射 | 总数 | 映射率 |
|---|---:|---:|---:|
| text | 50 | 88 | 0.5682 |
| heading | 9 | 19 | 0.4737 |
| table | 14 | 22 | 0.6364 |
| figure | 17 | 21 | 0.8095 |
| **全部** | **90** | **150** | **0.6000** |

`heading` 和普通文本映射最差。图像映射率较高不代表图表数据能够被正确读取；
当前 Gold 匹配主要证明图像/图题 Chunk 能被定位，不证明图内数值理解。

### 4.2 按文档结果

| 文档 | 已映射/总 Gold | 映射率 |
|---|---:|---:|
| VideoAgent | 11/27 | 0.4074 |
| Video-Grounded Entailment Tree | 18/27 | 0.6667 |
| 中国癌症症状管理实践指南更新 | 7/19 | 0.3684 |
| 科学营养餐桌行动报告 | 15/24 | 0.6250 |
| 绿色金融与海洋经济研究 | 18/25 | 0.7200 |
| IMF 文件名对应的实际 GFS Update 文档 | 21/28 | 0.7500 |

低映射不是均匀随机噪声，而是与文档版式、语言、文本提取方式和 Chunk 类型有关。
因此不能简单用统一字符阈值补高映射率，也不能把未映射 Gold 全部删除。

### 4.3 当前端到端 Recall 的正确解释

评测器把未映射 Gold group 以零分保留在端到端 Recall 分母中，这一做法适合衡量
“从原文到可检索证据”的全链覆盖，但不能把该指标单独解释成检索器 Recall。

应同时查看：

- **Gold→Chunk 映射率**：解析和切分是否保留了原文证据；
- **mapped-only Recall@5**：在 Gold 已能落到 Chunk 的条件下，检索器能否找回；
- **end-to-end Recall@5**：解析、切分、映射和检索的联合结果。

本次计划查询 Hybrid 的 mapped-only Recall@5 为 0.7111，而端到端为 0.4267。
二者差距首先说明 ingestion/evaluation alignment 是主要瓶颈之一，不代表检索器
本身已经达到 0.7111 的可接受水平。

## 5. 查询标签与运行契约失配

### 5.1 查询动作 Exact Match 不能直接使用

当前动作 Exact Match 为 0.1596，即 15/94。但冻结标签中有 54 条在当前运行契约
下不可能匹配：

| 不可实现原因 | 样本数 |
|---|---:|
| 标签使用 `none + preserve_terms`，而 `QueryPlan` 禁止 `none` 与其他动作组合 | 41 |
| `semantic_fact`/`visual_lookup` 标签要求 `decompose`，但对应意图策略不允许 | 3 |
| `document_summary` 标签要求 `decompose`，但运行策略固定为 `none` | 6 |
| `no_retrieval` 标签要求 `none`，但运行时短路计划使用空动作 | 4 |
| **合计** | **54** |

因此，当前标签下理论最高动作 Exact Match 只有 `40/94 = 0.4255`。在可实现的
40 条中实际命中 15 条，即 0.3750。后一个数字仍然说明查询动作选择不佳，但比
直接用 0.1596 更接近系统真实问题。

`preserve_terms` 更适合作为查询计划的约束或独立评测字段，而不是必须与 `none`
并列的互斥“动作”。当前冻结标签与运行模型对动作语义的理解没有统一。

### 5.2 必需路由指标也存在合同冲突

当前必需路由全部命中率为 0.7128，但有 20 条标签不能由当前意图策略产生：

| 意图 | 冲突样本数 | 主要差异 |
|---|---:|---|
| table_lookup | 7 | 标签要求 `table_text+dense+sparse`，系统策略为 `table_text+table_structured` |
| complex_analysis | 9 | 标签额外要求 `table_text` 或 `visual`，系统固定为 `multi_query+dense+sparse` |
| navigation | 4 | 标签额外要求 `table_text` 或 `visual`，系统固定为 `metadata_filter+dense+sparse` |

在当前合同下路由指标理论上最多为 `74/94 = 0.7872`。实际命中 67 条，相当于
在可实现标签上的 0.9054。由此可见：

- 0.7128 不能全部归因于 Qwen 路由能力；
- `table_lookup` 路由 0/7 主要是冻结标签与新版双索引设计不一致，而不是意图
  模型把 7 条查询全部识别错；
- 复杂分析和导航的“组合路由”尚未进入当前策略合同。

### 5.3 `query_contract` 失败数被放大

失败文件记录了 91 条 `query_contract`。该字段只要意图、动作、路由或术语保留
任一项不匹配就会计入，因此：

- 它不是 91 个独立代码错误；
- 它包含大量确定性的标签合同冲突；
- 不能用作系统错误率；
- 后续必须分别报告意图、可实现动作、可实现路由和术语保留。

## 6. 意图识别与查询变换问题

### 6.1 意图识别结果

总体意图准确率为 0.8404。

| 预期意图 | 正确/总数 | 准确率 | 主要问题 |
|---|---:|---:|---|
| clarification_required | 0/4 | 0.0000 | 全部被当作可执行检索 |
| complex_analysis | 11/18 | 0.6111 | 5 条降为 semantic_fact，2 条变为 table_analysis |
| semantic_fact | 21/24 | 0.8750 | 少量被扩大为 complex/summary/table |
| navigation | 11/12 | 0.9167 | 1 条变为 visual_lookup |
| document_summary | 6/6 | 1.0000 | 意图正确，但评测 workflow 不正确 |
| table_lookup | 7/7 | 1.0000 | 意图正确，但路由标签与执行链不一致 |
| table_analysis | 4/4 | 1.0000 | 意图正确，但结构化查询未在本评测执行 |
| visual_lookup | 15/15 | 1.0000 | 意图正确，但未执行 VLM |
| no_retrieval | 4/4 | 1.0000 | 正确短路 |

`clarification_required` 的 0/4 同时包含模型问题和样本定义问题：

- “比较两份文档”但没有指定两份文档，确实应澄清；
- “找报告中的影响因素结论”或“找到报告主要结果表”在单文档会话里也可以被合理
  解释为宽泛但可检索的查询；
- 当前 prompt 没有定义“缺少对象”“缺少比较范围”“查询宽泛但仍可执行”之间的
  判定边界。

因此该意图需要更清晰的业务语义和最小信息槽位，而不是只增加几个示例。

### 6.2 查询变换状态

| 变换状态 | 数量 | 含义 |
|---|---:|---|
| LLM 输出通过校验 | 72 | 真正使用 LLM 查询计划 |
| `validation_failed` | 11 | LLM 同时选择 `none` 和非原问题查询，违反合同 |
| `not_needed` | 7 | 意图策略只允许 `none`，属于正常跳过 |
| `short_circuited` | 4 | `no_retrieval` 正常短路 |

产物中的 `transformation_source=fallback` 为 18 条，其中包含：

- 11 条真实校验失败；
- 7 条设计上的 `not_needed`。

因此“18 条 fallback”不能解释成 18 次 API 故障。真正的输出合同问题是 11 条
`none must preserve the original question as the only retrieval query`。

### 6.3 术语保留不足

`must_preserve` micro recall 为 0.5693。当前代码只硬保护：

- 引号内容；
- 数字、百分比和年份；
- 大写缩写。

普通实体名、方法名、章节名称、指标名称和中文专有词主要依赖 prompt，未进入
确定性保护集合。这会让查询扩展或改写丢失区分性最强的词，并进一步影响 BM25、
Dense 和重排器。

### 6.4 查询动作存在过度变换

大量本应保留原问题的查询被选择为 `rewrite`、`expand` 或组合动作。查询变换没有
使用初次检索结果、候选分数、命中实体或证据充分性，只根据问题和轻量文档画像
一次生成。其结果是：

- 简单事实查询被不必要扩展；
- 生成的同义表达增加噪声通道；
- 多查询之间没有明确证据职责；
- 不知道原查询本来是否已经足够好；
- 无法利用检索反馈纠正 query drift。

## 7. 主系统实际存在的 workflow

### 7.1 LLM 之前的确定性 workflow

主 CLI 在 M1 查询链之前仍保留三类明确文档操作：

| 输入类型 | 实际执行链 | 本次评测覆盖 |
|---|---|---|
| 页数、表格数、图片数、块数 | 正则识别 → `document_statistics` → 元数据统计 | 未覆盖 |
| 读取指定页、列出页面 | 正则识别 → `page_lookup` → 直接页读取 | 未覆盖 |
| 列出全部表格/图片/日期/标题/大纲 | 正则识别 → `structured_extraction` → 结构化导出 | 未覆盖 |

`scripts/eval_m1_query_retrieval.py` 直接调用 `run_query_pipeline`，绕过上述 CLI
前置调度。因此本次不能评价这些 workflow。

### 7.2 九类查询意图 workflow

| 意图 | 主系统实际执行链 | M1-E 实际执行 | 测试暴露的问题 |
|---|---|---|---|
| no_retrieval | LLM 意图 → 空查询计划 → 固定对话回复 | 只评意图/动作，不检索 | 4/4 意图正确；Gold 动作 `none` 与运行时空动作冲突 |
| clarification_required | LLM 意图 → `request_clarification` → 固定澄清回复 | 只评意图/动作，不检索 | 0/4；prompt 与样本对“可检索但宽泛”的边界不清 |
| document_summary | LLM 意图 → 不做查询变换 → `summarize_document` 启发式全局扫描 | 被强制执行四种 Top-K 文本检索 | 实际摘要工具完全未测；当前低 Recall 不能代表摘要 workflow |
| table_lookup | LLM 意图/查询变换 → `table_lookup_or_calculation` → 在表格 Chunk 中选单表/单元格；QueryPlan 不驱动该工具 | 只把候选过滤为 table，再跑四种文本检索 | 没有执行主表格工具，也没有执行真正的关系型查询 |
| table_analysis | LLM 意图/查询变换 → 表格工具 → 启发式选择输入 → 简单计算器；QueryPlan 不驱动该工具 | 同 table_lookup，仅做 table 文本检索 | `table_structured` 声明未执行；统计/聚合准确率未测 |
| semantic_fact | LLM 意图 → 可选查询变换 → `local_fact_qa` → 配置的检索器 → 一次回答 | 四种检索器的原问题/计划查询对照 | 这是本次最接近真实生产链的类别；查询变换略有退化 |
| navigation | LLM 意图 → 元数据约束 → `local_fact_qa` → 约束内检索 → 回答 | 使用预测 metadata filter 后跑四种检索器 | 基本方向正确；复合表格/视觉导航路由尚未表达 |
| visual_lookup | LLM 意图 → image/figure 约束 → `local_fact_qa` → 命中视觉 Chunk 后可选 VLM review → 回答 | 只检索 image/figure Chunk，不调用 VLM | 只能评价视觉 Chunk 定位，不能评价图表理解 |
| complex_analysis | LLM 意图 → 最多 4 条静态子查询 → BM25/Dense 多路检索 → RRF → 一次回答 | 执行静态多查询检索，不生成答案 | 没有证据充分性判断、动态追加查询或多轮 Agent 循环 |

### 7.3 路由目前更像“声明”，不是完整控制平面

`QueryPlan.retrieval_routes` 会被记录和评测，但主执行链并没有逐项解释该列表并
调度所有索引：

- 检索器模式主要由 CLI 的 `--retriever-mode` 配置决定；
- `dense/sparse` 不会因为列表内容自动选择或关闭；
- 表格意图在 CLI 中直接进入表格工具，前面生成的 retrieval queries、metadata
  filter 和 `table_structured` 声明没有转换为该工具的执行参数；
- `table_structured` 只有在显式提供非空 `TableStructuredQuery` 时才进入
  `HybridRetriever` 的关系索引，而当前 QueryPlan 不产生该对象；
- `global_scan` 不由 HybridRetriever 执行，而由文档摘要工具处理；
- `visual` 也不是独立检索后端，而是内容类型约束和后续可选 VLM review。

这导致“预测路由正确”与“路由已执行”是两件不同的事。生产系统需要分别记录：

- `planned_routes`；
- `executed_routes`；
- 每一路候选数量、过滤数量、融合贡献和失败原因。

## 8. 本次检索结果

### 8.1 总体指标

| 查询形式 | 检索器 | E2E Recall@5 | Mapped-only Recall@5 | MRR@10 |
|---|---|---:|---:|---:|
| original | BM25 | 0.3933 | 0.6556 | 0.4676 |
| original | Dense | 0.4133 | 0.6889 | 0.4829 |
| original | Hybrid | **0.4267** | **0.7111** | 0.5043 |
| original | Hybrid+Reranker | 0.3867 | 0.6444 | **0.5124** |
| planned | BM25 | 0.3533 | 0.5889 | 0.4069 |
| planned | Dense | 0.4133 | 0.6889 | 0.4525 |
| planned | Hybrid | **0.4267** | **0.7111** | 0.4520 |
| planned | Hybrid+Reranker | 0.4000 | 0.6667 | 0.5087 |

可确认的结论：

- Hybrid 的 Recall@5 高于单独 BM25 或 Dense，说明稀疏/稠密互补在该语料上存在；
- 计划查询没有提高整体 Hybrid Recall；
- 计划查询显著降低 Hybrid MRR；
- 重排器对 MRR 有有限帮助，但降低了部分 Recall@5；
- 上述结论仍受 Gold 映射率和 workflow 代理评测影响。

### 8.2 样本级查询变换对照

计划查询相对原问题：

| 对照 | 提升 | 下降 | 持平 |
|---|---:|---:|---:|
| Hybrid Recall@5 | 2 | 2 | 82 |
| Hybrid MRR@10 | 5 | 12 | 69 |
| Hybrid+Reranker Recall@5 | 3 | 1 | 82 |
| Hybrid+Reranker MRR@10 | 7 | 3 | 76 |

这说明查询变换不是对所有样本普遍有害，而是：

- 对绝大多数样本没有改变 Top-K Gold 覆盖；
- 在未重排 Hybrid 中，排序下降样本多于提升样本；
- 重排器可以修复部分计划查询排序，但没有形成稳定的 Recall 收益。

### 8.3 重排器对照

| 对照 | 提升 | 下降 | 持平 |
|---|---:|---:|---:|
| 原问题：Rerank 相对 Hybrid Recall@5 | 1 | 6 | 79 |
| 原问题：Rerank 相对 Hybrid MRR@10 | 9 | 11 | 66 |
| 计划查询：Rerank 相对 Hybrid Recall@5 | 4 | 7 | 75 |
| 计划查询：Rerank 相对 Hybrid MRR@10 | 18 | 11 | 57 |

计划查询下的重排器更容易改善首个相关块的位置，但同时有更多样本丢失 Top-5
Gold 覆盖。当前结果符合“排序收益与覆盖损失并存”，不能只看平均 MRR。

## 9. 查询重写没有产生正收益的原因

### 9.1 不同意图没有严格按需启用

生产 RAG 中，查询翻译通常是可选步骤，而不是所有问题的默认步骤。微软的高级
RAG 文档也把 rewrite、augmentation、decomposition 视为按问题选择的可选策略，
并强调保留原查询和原意。
[Microsoft advanced RAG](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/rag/rag-information-retrieval)

当前系统对大量简单事实、表格定位和视觉定位查询也调用变换模型，导致：

- 已经清晰的问题被扩展；
- 原始精确词被同义改写稀释；
- BM25 的精确词优势下降；
- 额外查询带来更多非 Gold 候选。

### 9.2 查询变换缺少检索反馈

当前变换是：

```text
原问题 + 轻量文档画像
-> 一次 LLM 查询变换
-> 固定检索
```

它没有观察：

- 原问题检索是否已经高置信命中；
- 候选是否覆盖所有实体和比较维度；
- 哪条子查询没有找到证据；
- 初次结果是否发生主题漂移；
- 是否应该保留原问题作为融合锚点。

关于多重 reformulation，近期研究也指出，简单增加改写数量会形成 Recall 与 query
drift 的权衡，需要利用 ranker feedback 选择 reformulation，而不是无条件合并。
[When More Reformulations Hurt](https://arxiv.org/abs/2605.00560)

### 9.3 术语保护集合过窄

当前硬保护只覆盖数字、引号和英文缩写。领域实体、方法名、中文术语和章节名可能
被改写或省略。`must_preserve` micro recall 只有 0.5693，已经直接证明该问题。

### 9.4 多查询 RRF 对每条查询等权

HybridRetriever 会为每条子查询分别生成 BM25 和 Dense 排名，然后全部等权进入
RRF。查询数增加时：

- 一个 Chunk 可因在多条相似改写中重复出现而累积分数；
- 子查询质量没有权重；
- 原问题没有单独的保底权重；
- 不同 evidence responsibility 没有分组覆盖约束；
- 噪声子查询与关键子查询具有相同投票权。

因此，多查询可能提升候选多样性，也可能让“多次命中同一偏题主题”的 Chunk
超过只由一条关键子查询召回的 Gold Chunk。

### 9.5 本次“原问题”并非完全无规划基线

评测器为了只比较查询文本，original 与 planned 使用相同的预测 metadata filter
和表格意图约束。这能隔离“查询文本变化”的影响，但意味着 original 不是完整的
`no-router/no-planner` 基线。

如果预测意图或 metadata filter 错误，两种查询都会在同一错误候选集合上检索。
后续需要至少区分：

- 原问题 + 无预测约束；
- 原问题 + 预测约束；
- 计划查询 + 预测约束；
- 计划查询 + oracle 约束（只用于误差上界分析）。

## 10. 检索重排没有稳定正收益的原因

### 10.1 重排器只使用第一条子查询

当前 `HybridRetriever` 对多查询完成 RRF 后，调用重排器时使用：

```text
active_queries[0]
```

这意味着：

- 候选池可能由 2–4 条子查询共同召回；
- 重排器却只根据第一条子查询判断相关性；
- 支持第二、第三条证据责任的 Chunk 可能被降权；
- 复杂分析的多证据覆盖会被单查询相关性破坏。

这是本次“计划查询重排提高部分 MRR、但降低部分 Recall”的直接代码级原因之一。

### 10.2 重排只能重排已有候选

当前 Hybrid 先保留约 20 个融合候选，再输出 Top-5/Top-10。重排器不能找回初始
BM25/Dense 没有召回的 Gold。若初始候选覆盖不足，增加重排不会提高 Recall。

Anthropic 的 Contextual Retrieval 实验使用更大的初始候选池后再重排，并明确把
候选池大小、最终 Top-K、延迟和成本作为需要按语料实验的参数，而不是假设重排
必然提升。[Anthropic Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval)

### 10.3 重排目标只表示单块相关性

bge-reranker-v2-m3 当前逐个计算 `query-chunk` 相关性，没有优化：

- 多组 Gold 的联合覆盖；
- 表格与正文互补；
- 标题/图题与主体块的父子关系；
- 子查询之间的证据职责；
- 冗余去除和多样性。

因此它可以把最相关单块提前，却不保证 Top-5 覆盖所有证据组。

### 10.4 当前 Chunk 文本与 Gold 仍不稳定对齐

当 Gold 映射本身只有 0.6000 时，重排器可能把语义相关但未被映射为 Gold 的 Chunk
排在前面，从指标看却属于错误。不能在修复 qrels 之前据此微调重排器。

## 11. 各 workflow 的生产级反思

### 11.1 简单事实查询

当前最接近可用路径，但默认变换比例过高。生产策略应优先：

```text
原问题直接 Hybrid
-> 观察置信度/覆盖
-> 仅在失败或低置信时重写/扩展
```

原问题必须始终保留为检索锚点，不应被单条改写完全替代。

### 11.2 导航查询

metadata 作为检索前置过滤的方向正确，但需要：

- 明确区分物理页与印刷页；
- 支持标题层级、章节 ID 和元素 ID；
- 对过滤后零候选进行可解释放宽；
- 记录 `pre_filter_count`、`post_filter_count` 和实际命中过滤字段；
- 对“第 X 页的表/图”组合约束执行真实复合路由。

### 11.3 表格查询

当前存在三套尚未统一的能力：

1. QueryDecision 声明 `table_text/table_structured`；
2. HybridRetriever 具备 `TableRelationalIndex`，但需要外部构造
   `TableStructuredQuery`；
3. CLI 表格工具直接在所有表格 Chunk 中用启发式选表、选行并计算。

生产链应统一为：

```text
表格意图
-> 生成/校验结构化表格查询
-> 表格关系索引精确执行
-> 表格 Markdown/上下文文本检索
-> 合并并交叉核对
-> 需要时计算
```

本次评测只覆盖第二路中的表格文本检索代理，没有评估结构化执行。

### 11.4 视觉查询

MinerU 生成视觉 Chunk、图题和视觉摘要是检索基础，但“找到图”与“读懂图”必须
分开评估：

- Visual Retrieval：目标图像/图题 Chunk 是否进入 Top-K；
- Visual Understanding：VLM 是否正确读取图中实体、趋势和数值；
- Cross-modal Evidence：图像与邻近正文是否共同支持回答；
- Citation：是否能回到物理页和图号。

本次只覆盖第一项的一部分。

### 11.5 文档摘要

全局摘要不应以普通 Top-5 相似度作为唯一入口。当前主系统实际使用启发式页面扫描，
但本次却用普通检索评价，因此结果无效。生产级摘要更适合：

- 章节/标题层级扫描；
- 每章代表块与摘要索引；
- 表格、图像和结论段的覆盖配额；
- map-reduce 或分层摘要；
- 覆盖度而不是单一 MRR。

### 11.6 复杂分析

当前多查询只是一次静态拆解，不是用户预期的 Agentic RAG：

```text
一次意图识别
-> 一次拆解
-> 多查询并行检索
-> RRF
-> 一次回答
```

已有 evidence recovery 也只是扩大同一检索结果池并切换排名窗口，没有根据缺失
信息生成新查询。生产级复杂分析至少需要：

```text
任务拆解
-> 为每个证据责任检索
-> 判断每项是否有充分证据
-> 只对缺失项补充查询/工具
-> 汇总证据
-> 最终回答
```

但该循环只应服务复杂分析、跨表/跨图或多跳问题，不应让简单事实查询承担同样成本。

## 12. 检索组件层面的进一步反思

### 12.1 BGE-M3 只使用了 Dense 输出

当前 BGE-M3 编码器只读取 `dense_vecs`。所谓 sparse 路由实际是项目自实现 BM25，
并未使用 BGE-M3 的 lexical weight 或 multi-vector 能力。这不是错误，但文档和
trace 应准确表述：

- `dense = BGE-M3 dense`；
- `sparse = BM25`；
- `hybrid = BGE-M3 dense + BM25 + RRF`。

### 12.2 中文 BM25 使用单汉字切分

BM25 tokenizer 把每个汉字作为 token，未使用中文分词、词组或 n-gram。该实现
可能降低中文专有词的稀疏检索区分度。但本次中文 Hybrid mapped-only Recall
高于英文，因此当前数据没有证明它是主要失败原因；应作为待独立消融的技术风险，
不能根据直觉立即替换。

### 12.3 Contextual Retrieval 尚未形成统一合同

当前 Chunk 已保存章节、标题、摘要等上下文信息，但需要确认：

- 稠密嵌入文本是否稳定包含同一份上下文；
- BM25 是否索引相同或有意不同的字段；
- 重排器是否看到与初检一致的 `retrieval_text`；
- Gold qrels 是否指向主体 Chunk，而不是上下文复制产生的伪命中。

Anthropic 的方法是在嵌入和 BM25 建索引前为每个 Chunk 添加简短的文档内定位
上下文，并强调 Chunk 边界和语料实测，而不是只增加通用文档摘要。
[Anthropic Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval)

### 12.4 评测指标需要按意图区分

统一 Recall@5/MRR@10 不足以覆盖全部 workflow：

| 类型 | 最小必要指标 |
|---|---|
| semantic_fact | Gold group Recall@5、MRR@10 |
| navigation | 元数据过滤正确率、目标元素 Hit@K |
| table_lookup | 目标表 Hit@K、结构化行/列匹配 |
| table_analysis | 查询执行正确率、数值准确率 |
| visual_lookup | 图像/图题 Hit@K、VLM 问答准确率 |
| document_summary | 章节/关键 nugget 覆盖率 |
| complex_analysis | All-evidence Recall、每个子任务覆盖率 |
| no_retrieval/clarification | 路由准确率与不必要检索率 |

多跳问题只用 MRR 会奖励“第一块证据排得很高”，却忽略其他必需证据完全缺失。

## 13. 延迟和工程可用性问题

查询阶段的样本级耗时：

- 平均约 11.20 秒；
- P50 约 10.53 秒；
- P95 约 19.08 秒；
- 最大约 31.08 秒；
- 估算共执行 94 次意图 API 调用和 83 次查询变换 API 调用。

对个人 PC 的交互式应用，这一查询前延迟偏高。后续应减少不必要的第二次 API 调用，
尤其是：

- no-retrieval/clarification；
- document summary；
- 清晰的简单事实查询；
- 可由确定性 metadata 解析完成的导航；
- 表格结构化查询可以由受约束解析器处理的场景。

检索明细中的 Dense/Hybrid 延迟不包含批量查询向量编码和模型加载，重排器首条请求
还包含模型 warm-up。因此本次各检索模式的毫秒数不能直接作为在线 SLA 对比。
这是评测时序合同不完整，不是模型推理速度结论。

## 14. 全部问题清单

### P0：阻断有效验收

1. Gold 只绑定原文证据，未形成经复核的最终 Chunk qrels；
2. Gold→Chunk 映射率只有 0.6000；
3. 54/94 条动作标签在运行契约下不可实现；
4. 20/94 条路由标签在当前意图策略下不可实现；
5. 评测器没有执行 document summary 的实际 workflow；
6. 评测器没有执行 table structured 或 CLI 表格工具；
7. 评测器没有执行 visual VLM；
8. `retrieval_routes` 没有成为统一的可执行控制平面；
9. 不同意图仍被统一 Recall/MRR 混合评价。

### P1：已确认的系统质量问题

1. `clarification_required` 0/4，且业务判定标准不清；
2. `complex_analysis` 只有 11/18 正确；
3. 11 条查询变换输出违反 `none` 合同并回退；
4. `must_preserve` micro recall 只有 0.5693；
5. 简单查询被过度 rewrite/expand；
6. 多查询 RRF 等权，缺少原问题锚点与子查询权重；
7. 重排器对多查询只使用第一条子查询；
8. 重排只优化单块相关性，不优化多证据覆盖；
9. 复杂分析没有动态证据充分性判断与补充检索；
10. 表格结构化查询对象没有由 M1 QueryPlan 生成；
11. planned Hybrid MRR 从 0.5043 降至 0.4520；
12. 查询前平均 API 延迟约 11.20 秒。

### P2：需要独立消融，不能由本次直接定罪

1. 中文 BM25 单字切分；
2. BGE-M3 未使用 sparse/multi-vector 输出；
3. Chunk 上下文在 Dense、BM25、reranker 三处是否完全一致；
4. 候选池 20、最终 Top-5/Top-10 是否适合全部文档；
5. bge-reranker-v2-m3 是否需要领域适配；
6. 句界拆分、跨页合并和父子 Chunk 对不同意图的具体收益；
7. SQLite/FAISS 是否需要替换为 Milvus。

其中第 7 项对当前单机个人项目不是质量瓶颈。本次失败主要发生在数据合同、路由执行、
查询变换和评测覆盖层，不应优先通过更换向量数据库处理。

### 数据治理问题

`IMF《Fiscal Monitor Update》（2021-01）.pdf` 的文件名与正文实际内容
`Global Financial Stability Update, June 2020` 不一致。样本生成已按正文处理，
因此它不是本次检索失败原因，但生产系统需要：

- 从正文提取规范标题；
- 同时保留上传文件名和规范文档标题；
- 对标题冲突产生告警；
- 检索和展示时避免把错误文件名当作内容事实。

## 15. 建议的下一版最小评测合同

在不扩大为完整平台的前提下，下一版只需保留最关键、易量化的指标：

### 15.1 数据与解析

- Source evidence→Chunk 对齐率；
- 按 text/heading/table/figure 分组；
- 无法映射原因分类；
- 每个 Gold group 对应一个或多个经复核 `chunk_id`。

### 15.2 查询侧

- 意图准确率；
- 是否需要检索；
- 是否需要查询变换；
- 必需实际 workflow 命中率；
- `must_preserve` 术语覆盖率。

动作标签应改为正交字段，例如：

```text
transformation = none | rewrite | expand | decompose
preserve_terms_required = true | false
requires_clarification = true | false
```

不要继续使用互相冲突的 `none + preserve_terms` 列表。

### 15.3 检索侧

- Gold group Recall@5；
- 单证据问题 MRR@10；
- 多证据问题 All-evidence Recall@K；
- original-only 与 conditional-rewrite 对照；
- 各实际 workflow 分开报告，不再把摘要、表格结构化和视觉理解混入普通文本检索。

### 15.4 运行追踪

每条记录至少保存：

```text
predicted_intent
planned_routes
executed_routes
original_query
retrieval_queries
metadata_filter
candidate_counts_by_route
gold_chunk_ids
retrieved_chunk_ids
reranked_chunk_ids
latency_by_stage
fallback_reason
```

## 16. 对当前 RAG 架构的最终反思

### 16.1 已经合理的部分

- MinerU 原始结果会转换为统一 Chunk，而不是直接入索引；
- Chunk 具备结构、页面、章节、表格和视觉元数据；
- metadata 作为前置约束，而不是 RRF 第三路；
- 原问题与检索查询分离；
- BM25、BGE-M3 Dense、RRF 和 CrossEncoder 均有真实服务器执行；
- 表格同时存在文本表示和关系数据结构；
- 未映射 Gold 没有被静默删除；
- 已具备按语言、意图、文档和检索器分组的评测产物。

### 16.2 当前最核心的架构缺口

当前系统拥有许多“组件”，但组件之间仍缺少一个统一的可执行查询计划：

```text
意图与约束
-> 是否需要变换
-> 应调用哪些真实索引/工具
-> 每个子查询负责什么证据
-> 如何融合
-> 是否证据充分
-> 是否需要补充检索
```

目前 `retrieval_routes` 主要是声明，CLI task dispatch、HybridRetriever、
TableRelationalIndex、表格工具、摘要工具和 VLM review 各自存在，但没有由一个
共同合同完整驱动。

### 16.3 不应把所有查询都升级成重型 Agent

生产级方向不等于每条查询都反复调用 LLM：

- 简单事实：直接 Hybrid，失败时才变换；
- 导航：metadata/结构定位优先；
- 表格：结构化执行与文本检索双路；
- 摘要：分层全局扫描；
- 视觉：先定位图，再按需 VLM；
- 复杂分析：才进入多步检索、证据检查和动态补充。

这种按复杂度升级的设计比“所有问题统一多智能体循环”更适合个人 PC、本地小模型
和外部 API 混合的项目目标。

### 16.4 下一阶段的先后顺序

本报告只进行分析，不实施修改。若进入下一阶段，合理顺序应为：

1. 修正双层 Gold 与动作/路由评测合同；
2. 让 `planned_routes` 与 `executed_routes` 建立真实映射；
3. 分开建立普通、表格、视觉、摘要和复杂分析评测；
4. 将简单查询默认保留原问题，按失败或低置信触发变换；
5. 修正多查询重排只使用第一子查询的问题；
6. 最后再评估是否需要 Agentic 循环、模型微调或替换存储后端。

## 17. 外部依据

- [BEIR: A Heterogeneous Benchmark for Zero-shot Evaluation of Information Retrieval Models](https://arxiv.org/abs/2104.08663)
- [TREC 2024 RAG Evaluation Overview](https://trec-rag.github.io/annoucements/evaluation/)
- [CoFE-RAG: A Comprehensive Full-chain Evaluation Framework](https://arxiv.org/abs/2410.12248)
- [Anthropic: Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval)
- [Microsoft: Build Advanced Retrieval-Augmented Generation Systems](https://learn.microsoft.com/en-us/azure/developer/ai/advanced-retrieval-augmented-generation)
- [Microsoft: RAG Information-Retrieval Phase](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/rag/rag-information-retrieval)
- [When More Reformulations Hurt: Avoiding Drift using Ranker Feedback](https://arxiv.org/abs/2605.00560)
