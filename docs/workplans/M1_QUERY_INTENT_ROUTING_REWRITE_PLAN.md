# M1 查询意图、路由与查询变换实施计划

> 文件性质：当前阶段临时实施依据
> 计划版本：1.4
> 状态：`implemented`
> 建立日期：2026-07-30
> 适用范围：从用户查询输入到检索请求输出，不包含最终答案生成

## 1. 目标

将当前面向固定任务和工具选择的旧路由链，升级为面向 RAG 查询语义的查询前
处理链：

```text
原始问题
-> 查询意图识别
-> 执行路径路由
-> 查询变换决策
-> 改写 / 扩展 / 拆解
-> 元数据前置约束
-> 路由化检索请求
```

本阶段完成后，系统应能根据查询意图决定是否检索、采用哪些检索路径、是否需要
查询变换，并把一个或多个检索查询及结构化约束交给现有检索层。原始问题必须
保持不变，只供后续问答节点使用。

## 2. 当前缺口

### 2.1 旧路由以任务和工具为中心

当前 `docagent/router/rule_router.py` 主要通过关键词规则生成：

- `task_type`；
- `selected_tools`；
- 若干 `requires_*` 布尔字段；
- 一条轻量 `query_rewrite`。

该模型把用户意图、执行工具和检索策略混在同一个决策中。`local_fact_qa`、
`table_lookup_or_calculation` 等名称属于项目内部实现概念，不适合作为专业
RAG 查询意图。

### 2.2 LLM 路由只是旧规则路由的补丁

`docagent/router/llm_router.py` 只在规则结果低置信度时替换旧 `task_type`，
仍然围绕工具选择生成结果，不能稳定表达：

- 查询属于正文、表格、图片还是跨章节分析；
- 元数据约束应如何作用；
- 是否需要改写、扩展或拆解；
- 不同子查询分别应走哪条检索路径。

### 2.3 查询规划没有受意图约束

当前 `docagent/retrieval/query_planner.py` 和
`query_generator_llm.py` 主要生成固定数量的关键词式扩展查询。存在以下问题：

- 不是所有查询都需要改写或扩展；
- 不能在 `rewrite`、`expand`、`decompose` 之间按查询选择；
- 中文查询会被提示词强制生成英文检索词，未考虑文档语言；
- 查询规划结果缺少明确的元数据过滤和检索路径；
- 复杂查询虽然能生成多查询，但不区分静态拆解与后续动态 Agent 检索。

### 2.4 CLI 仍由旧任务类型控制执行

`scripts/docagent_cli.py` 先生成旧 `router_plan`，再按 `task_type` 分发工具。
新的混合检索已经支持元数据前置过滤、多查询和表格结构化查询，但这些能力尚未
由统一查询决策契约驱动。

### 2.5 已有正确边界必须保留

以下现有行为是正确的，本阶段不得破坏：

- 原始问题用于答案生成；
- 改写或扩展后的查询只用于检索；
- 超出问答上下文限制时优先裁减检索证据；
- Metadata 是稠密与稀疏检索的前置过滤条件，不参与第三路分数融合；
- 真实 BGE-M3、重排序器、表格索引和 Chunk 构建逻辑不在本阶段重写。

## 3. 已确定的方案

### 3.1 查询意图是领域概念，工具是执行细节

新的公开查询意图固定为：

| 意图 | 含义 |
|---|---|
| `semantic_fact` | 一个或少量局部正文证据可回答 |
| `navigation` | 查找章节、页、图、表或特定位置 |
| `table_lookup` | 读取表格中的明确字段或数值 |
| `table_analysis` | 对表格执行筛选、比较、排序或简单计算 |
| `visual_lookup` | 需要图片、图表或图中信息 |
| `complex_analysis` | 需要多个分散证据的比较、归因或综合 |
| `document_summary` | 面向全文或多个章节的概述 |
| `no_retrieval` | 无需文档检索 |
| `clarification_required` | 缺少关键对象、范围或条件 |

`selected_tools` 不再属于新的查询决策契约。实际调用哪个现有执行器，由查询计划
到运行时的适配层决定。

### 3.2 查询变换动作固定为受限集合

查询动作固定为：

- `none`
- `rewrite`
- `expand`
- `decompose`
- `preserve_terms`
- `request_clarification`

LLM 只能从该集合选择。不同意图允许的动作由代码中的策略表约束，不能由提示词
自由创造新动作。

### 3.3 采用两阶段决策

第一阶段是意图路由：

- 输入只包含原始问题和轻量文档画像；
- 输出意图、置信度、是否需要检索、候选执行路径和显式元数据约束；
- 不读取 PDF 正文、Chunk 或检索结果；
- 不生成答案。

第二阶段是查询变换：

- 输入原始问题、第一阶段意图和允许动作；
- 由 LLM 判断使用 `none`、`rewrite`、`expand` 或 `decompose`；
- 仅在需要查询变换的路径调用；
- 输出一个或多个检索查询；
- 不允许改变原问题中的实体、数字、时间、比较关系和输出目标。

内部使用结构化 JSON 是合理的，因为这是机器间契约；最终面向用户的答案仍为
自由文本或 Markdown。

### 3.4 LLM 模型基线、角色提示词与确定性职责

本阶段所有通用 LLM API 角色统一使用：

```text
qwen3.7-max-2026-05-17
```

模型、Base URL 和 API Key 继续从本地与服务器各自的 `router_llm.env` 读取，
不得把密钥或 Base URL 写入仓库。模型 ID 也不在提示词代码中重复硬编码，以环境
配置为事实来源；每次真实冒烟在紧凑产物中记录实际加载的模型 ID。当前已核对
本地配置为该快照，服务器端在首次真实冒烟前单独预检。

同一模型承担不同角色时，必须使用不同的 System Prompt、输入字段和输出 Schema：

| 角色 | 只负责 | 禁止行为 | 主要输出 |
|---|---|---|---|
| `intent_router` | 查询意图、检索必要性、候选路径与显式约束 | 回答问题、生成检索查询、读取正文、选择内部工具 | `QueryDecision` |
| `query_transformer` | 在允许动作内选择 `none/rewrite/expand/decompose` 并生成检索查询 | 改变原始需求、回答问题、创建新意图、选择执行工具 | `QueryPlan` 的变换字段 |

两个角色不得共用一份模糊的“Router/Planner”提示词。提示词需要分别版本化，并在
trace 中记录 `role`、`prompt_version`、`model_id` 和校验结果，不记录完整思维链。

官方资料显示该快照属于 Qwen3.7-Max 系列并只支持思考模式；不同官方页面对
Qwen3.7-Max 的严格结构化输出支持标注存在差异。因此实现不得只依赖
`response_format=json_object` 保证正确性：可以继续请求 JSON，但必须保留本地
JSON 提取、Schema 校验和最小回退，并通过该精确快照的真实 API 冒烟确认行为。

主要查询意图和查询变换使用上述外部 LLM API。确定性逻辑只负责：

- 输入和输出 Schema 校验；
- 明确页码、章节、表号、图号等约束提取；
- 动作白名单和意图—路由兼容性校验；
- API 缺失、超时或非法输出时的有界回退；
- 去重、数量限制和原问题字段保护。

回退不是另一套复杂路由系统。无法调用 LLM 时：

- 明确的摘要、表格、图片、页码和澄清请求可使用少量稳定规则；
- 其他文档问答退回 `semantic_fact`；
- 检索查询只使用原始问题；
- 输出中记录回退原因。

### 3.5 检索路径

查询计划可选择以下检索路径：

- `dense`
- `sparse`
- `metadata_filter`
- `table_text`
- `table_structured`
- `visual`
- `multi_query`
- `global_scan`
- `no_retrieval`
- `clarification`

主要映射如下：

| 意图 | 默认路径 |
|---|---|
| `semantic_fact` | `dense + sparse` |
| `navigation` | `metadata_filter` 后接 `dense + sparse` |
| `table_lookup` | `table_text`，适用时增加 `table_structured` |
| `table_analysis` | `table_structured + table_text` |
| `visual_lookup` | 图片元数据约束后进入 `visual` |
| `complex_analysis` | `multi_query + dense + sparse` |
| `document_summary` | `global_scan` |
| `no_retrieval` | `no_retrieval` |
| `clarification_required` | `clarification` |

Metadata 始终作为召回前约束。它不产生独立候选集，也不参与 RRF。

### 3.6 多语言查询与嵌入模型决策

- 中文文档的查询变换默认保持中文；
- 英文文档的查询变换默认保持英文；
- 不再对中文查询无条件生成英文查询；
- 当前文档记录没有稳定的语言字段，因此先由 `_document_profile` 对少量已持久化
  Chunk 做确定性语言判断并提供 `dominant_language`，不新增数据库迁移；
- 只有文档画像明确表明查询语言与索引内容语言不一致时，才允许跨语言扩展；
- 原文实体、缩写、方法名和专有名词可按原形式保留。

本阶段不为中文和英文分别部署两套稠密嵌入模型，统一保留：

```text
Dense embedding: BAAI/bge-m3
Reranker: BAAI/bge-reranker-v2-m3
Sparse retrieval: current BM25 implementation
```

理由：

- BGE-M3 官方定位就是多语言统一嵌入模型，支持 100 多种语言，覆盖中文和英文；
- 当前 `bge-reranker-v2-m3` 官方同样标记为多语言模型；
- 当前评测约束是中文文档使用中文查询、英文文档使用英文查询，不要求跨语言问答；
- 分开使用中文和英文嵌入模型会引入两套权重、索引和模型路由；两种模型的向量
  空间不能直接混用，在没有评测证据时收益不足以抵消复杂度。

当前多语言链路仍有一个独立风险：`BM25Index.tokenize()` 对英文按单词切分，对
中文按单汉字切分。它可以召回中文原字匹配内容，但词语边界和短语区分能力较弱。
此外，CLI 默认路径与 `configs/retrieval_hybrid.yaml` 使用
`bge-reranker-v2-m3`，而历史 `configs/retriever.yaml` 仍写有
`bge-reranker-base`。后者不视为当前真实运行事实，但实施时需要统一或明确废弃，
避免不同入口加载不同重排器。

若中文检索明显落后，应优先比较以下方案，而不是先更换中文稠密模型：

1. 改进中文稀疏分词；
2. 使用 BGE-M3 自带的 sparse lexical weights；
3. 调整稀疏/稠密融合权重或重排候选规模。

只有冻结评测集显示中文或英文的稠密召回存在持续、显著且可复现的差距时，才单独
立项比较语言专用嵌入模型。不能在本阶段直接增加第二套向量模型和索引。

### 3.7 复杂分析的本阶段边界

本阶段支持一次性的有界查询拆解和多查询并行检索，但不实现：

- 基于首轮证据再次思考并动态生成新查询；
- 循环检索直到模型自行判断信息充分；
- 多 Agent 审核、反思或辩论；
- LangGraph 中的动态递归检索。

`complex_analysis` 的动态 Agent 路由留到后续独立里程碑。本阶段输出必须显式标记
为静态拆解，不能声称已经具备迭代式 Agentic RAG。

### 3.8 旧模块迁移策略

旧模块暂不立即删除，避免在同一次改动中破坏已有 CLI 与回归脚本：

- 新查询链成为 RAG 问答的唯一主路径；
- 旧 `rule_router.py`、`llm_router.py` 和旧查询生成器停止被主路径直接调用；
- 现有确定性文档统计、页面读取和结构化导出通过薄适配器继续可用；
- CLI 以 `query_decision` 和 `query_plan` 作为新规范字段；
- `router_plan`、`query_planner` 若仍被旧脚本需要，只在输出边界生成兼容视图，
  新代码不得反向依赖这些兼容字段；
- 完成回归验证后，再单独决定是否删除旧实现和旧字段。

## 4. 新接口契约

### 4.1 QueryDecision

```json
{
  "original_question": "用户原始问题",
  "intent": "semantic_fact",
  "confidence": 0.0,
  "requires_retrieval": true,
  "allowed_actions": ["none", "rewrite", "expand", "preserve_terms"],
  "retrieval_routes": ["dense", "sparse"],
  "metadata_filter": {
    "physical_pages": [],
    "printed_pages": [],
    "section_path": [],
    "content_types": []
  },
  "reason": "简短决策理由",
  "source": "llm",
  "warnings": []
}
```

要求：

- `original_question` 必须逐字保留；
- `intent`、动作和路径必须来自枚举；
- `confidence` 只用于诊断和回退，不直接当作评测正确性；
- `reason` 只允许简短说明，不保存思维链；
- `metadata_filter` 只保存能从问题或文档画像可靠获得的约束。

### 4.2 QueryPlan

```json
{
  "original_question": "用户原始问题",
  "intent": "semantic_fact",
  "actions": ["rewrite", "preserve_terms"],
  "retrieval_queries": ["检索查询"],
  "retrieval_routes": ["dense", "sparse"],
  "metadata_filter": {},
  "preserved_terms": [],
  "transformation_source": "llm",
  "warnings": []
}
```

要求：

- `retrieval_queries` 最多 4 条；
- `none` 时只保留原始问题；
- `rewrite` 生成一条更适合检索的等价查询；
- `expand` 生成少量互补表达，不能只是同义句堆叠；
- `decompose` 生成彼此有信息职责的子查询；
- 任何变换不得覆盖 `original_question`；
- `clarification_required` 和 `no_retrieval` 的检索查询为空。

### 4.3 下游边界

检索器只接收：

- `retrieval_queries`
- `retrieval_routes`
- `metadata_filter`
- `intent`

问答模型只接收：

- `original_question`
- 检索结果
- 工具或结构化查询结果

查询变换结果不得替代问答模型看到的原始问题。

## 5. 代码范围

### 5.1 计划新增

```text
docagent/query/__init__.py
docagent/query/schemas.py
docagent/query/intent_router.py
docagent/query/query_transformer.py
docagent/query/pipeline.py
tests/test_query_intent_router.py
tests/test_query_transformer.py
tests/test_query_pipeline_integration.py
```

职责：

- `schemas.py`：意图、动作、路由、Metadata 和查询计划契约；
- `intent_router.py`：LLM 意图识别、验证及最小回退；
- `query_transformer.py`：按允许动作生成和校验检索查询；
- `pipeline.py`：严格串联意图识别与查询变换；
- 三组测试分别验证契约、变换和下游集成边界。

### 5.2 计划修改

```text
docagent/retrieval/hybrid_retriever.py
scripts/docagent_cli.py
docagent/router/llm_client.py 或等价的通用 LLM JSON 客户端
configs/retriever.yaml
configs/retrieval_hybrid.yaml
tests/中与 CLI 查询计划输出直接相关的回归测试
```

修改原则：

- 只增加新查询计划的接入，不改稠密、稀疏、RRF 和重排序算法；
- 复用现有 OpenAI 兼容 API 调用能力；
- 不复制另一份 HTTP 客户端；
- 兼容层只存在于 CLI/产物边界。

### 5.3 本阶段不修改

```text
docagent/ingestion/
docagent/parser/
Chunk 构建与持久化
Dense/BM25/RRF/重排序核心算法
表格关系索引构建
AnswerPolicy、SFT、GRPO
VLM 图片理解实现
```

## 6. 实施步骤与验收

### M1-A：冻结查询契约

工作：

- 实现 `QueryDecision`、`QueryPlan` 和 Metadata Filter Schema；
- 增加枚举、字段校验和序列化；
- 将原问题不可变性写入测试。

验收：

- 合法结构能稳定序列化；
- 未知意图、未知动作、未知路由和非法过滤字段被拒绝；
- 原问题在决策和计划中完全一致；
- 不调用模型或检索器。

### M1-B：实现意图识别与路由

工作：

- 定义只返回 `QueryDecision` 的 LLM 提示词；
- 将提示词角色固定为 `intent_router` 并设置独立版本号；
- 传入轻量文档画像，不传正文；
- 校验文档是否具备表格或图片；
- 实现明确规则的有界回退；
- 短路 `no_retrieval` 和 `clarification_required`。

验收：

- 使用 Fake LLM 覆盖 9 类意图；
- 表格、图片与文档画像不匹配时产生明确警告或安全回退；
- 非法 JSON、越界置信度和未知枚举不能进入下游；
- trace 记录 `qwen3.7-max-2026-05-17`、角色和提示词版本，不记录密钥或思维链；
- 不生成答案，不调用检索。

### M1-C：实现按意图查询变换

工作：

- 根据意图生成允许动作集合；
- LLM 在允许集合内选择动作并产生检索查询；
- 使用与意图路由完全分离的 `query_transformer` 提示词和输出 Schema；
- 保留实体、数字、时间、缩写和显式定位信息；
- 按文档语言控制查询语言；
- 对查询去重并限制为最多 4 条；
- 支持静态 `decompose`。

验收：

- 简单事实查询允许保持原问题；
- 导航查询保留页码、章节、表号或图号；
- 表格查询不丢失指标、年份、运算与比较方向；
- 复杂查询的子查询职责不同且仍服务原问题；
- 文档画像的 `dominant_language` 来自有界 Chunk 抽样，不读取完整 PDF；
- 中文文档不会无条件产生英文检索查询；
- 失败时只用原问题检索。

### M1-D：接入现有检索与 CLI

工作：

- 在检索前执行新的 `QueryPipeline`；
- Metadata Filter 先于稠密和稀疏检索；
- 多查询结果继续使用现有融合与重排序；
- 表格意图接入已有表格文本/结构化路径；
- 图片意图只接入已有图片检索与 VLM 边界；
- 统一实际 CLI 与检索配置中的 BGE-M3、`bge-reranker-v2-m3` 模型标识；
- 新增 `query_decision`、`query_plan` 和紧凑执行 trace；
- 原问题继续进入 AnswerPolicy。

验收：

- Fake Retriever 能证明接收到正确查询、路径和过滤条件；
- AnswerPolicy 测试能证明收到的是原始问题；
- Metadata 不作为第三路 RRF 候选；
- 表格与非表格路径不会无条件同时执行；
- 不同入口不会静默加载不同的稠密模型或重排器；
- CLI dry-run 和现有本地自测路径保持可用。

### M1-E：评测与回归

在冻结样本生成完成后执行：

- 意图分类准确率；
- 查询动作 Exact Match；
- 必需检索路径命中率；
- `gold_evidence_groups` 映射 Chunk 后的 Recall@5；
- MRR@10；
- 按意图和文档分别报告结果。
- 按中文与英文分别报告 Recall@5、MRR@10 和样本数；
- 对统一 BGE-M3 方案进行中英文分组比较，不在同一汇总均值中掩盖语言差异；
- 分别记录 Dense、BM25、Hybrid 和 Hybrid+Reranker 的语言分组结果。

不使用 BLEU、ROUGE 或主观“改写得像不像”作为查询重写主指标。查询变换是否有效，
主要通过下游检索 Recall@5 和 MRR@10 的变化衡量。

首次运行先记录基线，不在看到冻结集结果后为单个样本增加规则。正式阈值在基线
产物可用后另行写入本计划，再进行验收比较。

冻结评测文件统一放置在以下对应目录：

```text
本地：
D:\Projects\docagent\data\benchmark\m1_query_routing\

服务器：
/root/autodl-tmp/docagent_worktrees/chunk-v3-real-retrieval-1f2a00e/data/benchmark/m1_query_routing/
```

目录内容固定为：

```text
frozen_query_samples.jsonl
sample_summary.md
generation_issues.md
```

其中 `frozen_query_samples.jsonl` 是评测程序的运行输入；另外两个 Markdown
文件用于核对样本分布、配额变化和生成问题，不作为逐条评测输入。这些文件是冻结
评测数据，不得用于训练，也不得提交到 Git。服务器端保持相同的项目内相对路径，
以便本地与服务器使用同一评测命令；无需通过 Git 同步，可手动上传。

当前 M1 的代码同步、数据预检和后续评测统一在上述独立 worktree 中执行。主检出目录
`/root/autodl-tmp/docagent` 保留为旧分支工作区，不作为本阶段命令执行目录。

2026-07-30 服务器预检确认冻结样本的 6 份原始 PDF 已存在，但尚未生成对应的
MinerU 解析产物、检索 Chunk 和真实稠密索引。因此：

- 意图分类、查询动作与路由契约评测可在无卡服务器上执行；
- Recall@5、MRR@10 及 Dense/BM25/Hybrid/Hybrid+Reranker 对比，必须先完成
  6 份文档的 MinerU 转换、Chunk 重建和真实索引构建；
- 当前代码同步不受该派生产物缺失阻断，但不得把同步完成报告为正式检索评测就绪。

### M1-E 冻结语料准备产物契约

本次冻结语料准备使用固定运行标识：

```text
m1_frozen_corpus_v1_20260730
```

每篇文档的规范产物继续由现有内容寻址注册流程保存：

```text
data/documents/<doc_id>/
  source/original.pdf
  mineru/
    mineru_api_manifest.json
    mineru_result.zip
    <MinerU 原始解析文件>
  evidence_blocks.jsonl
  page_documents.jsonl
  structure_quality.json
  ingestion_report.json
  dense_embeddings.npy
  dense_index.faiss
  index_metadata.json
```

其中 `evidence_blocks.jsonl` 是历史兼容文件名，文件内对象必须是统一
`docagent_chunk_v3` Chunk；不得把它解释为 MinerU 原始块。完整 MinerU、Chunk、
嵌入和索引产物只保留在服务器，不同步到本地。

本批次的运行记录统一放置：

```text
outputs/m1_frozen_corpus_v1_20260730/
  docagent.db
  document_manifest.json
  per_document_results.jsonl
  logs/

outputs/sync/m1_frozen_corpus_v1_20260730/
  result.json
  manifest.json
  summary.json
  summary.md
  failures_sample.jsonl
  log_tail.txt
```

`document_manifest.json` 必须记录文档文件名、语言、SHA256、`doc_id`、规范文档目录、
MinerU 模型与解析选项、Chunk 数量、可索引 Chunk 数量、结构质量状态、稠密模型、
索引维度和各阶段状态，不记录令牌、签名下载地址或完整文档内容。

本批次解析配置固定为：

- `model_version=vlm`；
- 表格与公式识别开启；
- 不强制 OCR，由 MinerU VLM 自动处理；
- 中文文档使用 `language=ch`，英文文档使用 `language=en`；
- Dense 模型使用 `/root/autodl-tmp/models/bge-m3`；
- GPU 设备使用服务器预检确认的首个可见 CUDA 设备；
- 对来源 SHA256、解析选项和现有成功 manifest 一致的缓存不重复调用 API。

载入后、实现评测脚本前只进行只读预检：

- 三个文件均存在；
- JSONL 每个非空行均可解析为 JSON 对象；
- 样本 ID 唯一；
- `document_file` 能对应冻结文档清单；
- 汇总数量与 JSONL 实际数量一致；
- 不修改样本问题、意图、动作或原文证据。

## 7. 依赖与资源边界

### 本地即可完成

- Schema、策略表和校验逻辑；
- Fake LLM 单元测试；
- Fake Retriever 集成测试；
- CLI dry-run；
- SQLite/JSON 契约验证；
- 规则回退测试。

### 外部 API 验证

- 真实意图路由 LLM；
- 真实查询变换 LLM。

这两项统一使用 `router_llm.env` 中的 `qwen3.7-max-2026-05-17`，但使用不同
角色提示词。这两项不需要 GPU，可在本地通过现有 API 配置进行一次小规模冒烟。
若无 API 配置，代码最多标记为 `mock_verified`。

### 服务器必需

只有在需要证明新查询计划与真实 BGE-M3、重排序器联合工作时，才同步有限代码到
AutoDL 并执行一次真实检索冒烟。服务器不需要同步桌面规范、完整本地输出或评测
文档。服务器 Git 网络操作前必须执行：

```bash
source /etc/network_turbo
```

本阶段不安装新模型、不下载新数据集、不修改 Torch/CUDA。

GPU 启动时机：

- M1-A、M1-B、M1-C 以及 M1-D 的本地实现和 mock 集成期间不启动服务器 GPU；
- 真实 `qwen3.7-max-2026-05-17` API 冒烟不依赖服务器 GPU；
- M1-D 本地回归完成后，准备运行真实 BGE-M3 与重排器联合冒烟时再开启 GPU；
- M1-E 的 Dense、Hybrid、Hybrid+Reranker 冻结集评测需要 GPU；
- 纯 BM25、样本 Schema 检查和 gold evidence 到 Chunk 的确定性映射不需要 GPU。

## 8. 风险与控制

| 风险 | 控制 |
|---|---|
| 意图和执行工具再次耦合 | QueryDecision 不包含 `selected_tools` |
| 所有查询都被过度改写 | 动作允许为 `none`，按意图限制调用 |
| 改写改变原问题 | 原问题单独保存并做不可变测试 |
| LLM 输出不稳定 | 结构化输出、白名单校验和最小回退 |
| 同一模型承担不同角色时职责混淆 | 角色专属提示词、输入白名单和独立输出 Schema |
| 精确模型快照的 JSON Mode 行为与文档标注不一致 | 真实 API 冒烟、本地 JSON 解析和 Schema 校验并存 |
| 中文查询被强制英文化 | 依据文档语言决定，取消无条件翻译 |
| 中英文平均指标掩盖单一语言退化 | 按语言分别报告 Dense/BM25/Hybrid/Rerank |
| 中文 BM25 单字切分噪声较高 | 先评测稀疏路径，再决定分词或 BGE-M3 sparse 改造 |
| 双嵌入模型造成向量空间与索引分裂 | 本阶段冻结统一 BGE-M3，不增加语言专用模型 |
| Metadata 被错误并行融合 | 只在检索前过滤 |
| 复杂查询被误报为 Agentic RAG | 本阶段明确标记为静态拆解 |
| 旧脚本大面积失效 | CLI 输出边界提供临时兼容视图 |
| 为评测样本做个案规则 | 禁止从冻结样本措辞生成专用规则 |

## 9. 完成标准

本阶段只有同时满足以下条件才可完成：

1. M1-A 至 M1-D 的针对性测试全部通过；
2. 相关既有 CLI、检索和 AnswerPolicy 回归测试通过；
3. 原问题与检索查询边界有自动化测试；
4. API 配置可用时完成一次真实 LLM 冒烟并保存紧凑产物；
5. 真实检索依赖可用时完成一次 BGE-M3/重排序器冒烟；
6. 冻结样本可用后完成 M1-E 基线；
7. 将稳定架构决策更新到 `DECISIONS.md`；
8. 将已验证状态更新到 `CURRENT_STATUS.md`；
9. 更新 CLI 使用文档和必要的 README；
10. 从 `docs/ACTIVE_PLAN.md` 移除本临时计划的当前引用。

在真实 LLM 冒烟前，最高状态为 `mock_verified`；在真实检索评测完成前，不得标记
为 `benchmark_evaluated` 或 `accepted`。

## 10. 范围外工作

本阶段不进行：

- LangGraph 循环检索和反思；
- 多 Agent 分工；
- AnswerPolicy 微调、SFT、DPO 或 GRPO；
- 最终答案忠实度、相关性或引用支持度评测；
- 除上述 6 份 M1-E 冻结文档语料准备外，不进行其他 Chunk、MinerU 转换和索引重建；
- 新的 VLM 图表理解实现；
- UI 或服务化部署；
- 迁移 SQLite 到 Milvus。

## 11. 停止条件

完成本计划定义的实现、最小验证和项目文档更新后停止，不自动进入：

- 动态 Agentic RAG；
- 训练阶段；
- 最终答案质量优化；
- 正式视觉问答基准；
- 数据库或向量库迁移。

如果冻结评测样本尚未完成，先完成 M1-A 至 M1-D 和相应回归，将状态保持在
`implemented`、`mock_verified` 或 `real_model_verified`，等待样本后再执行
M1-E，不以临时自造样本替代冻结评测集。

## 12. 方案变更记录

实现过程中若方案变化，必须先在此处新增记录，再修改代码。

| 日期 | 版本 | 变更 | 原因 | 影响范围 |
|---|---|---|---|---|
| 2026-07-30 | 1.0 | 建立初始计划 | 将历史讨论固化为可执行依据 | 查询前处理链 |
| 2026-07-30 | 1.1 | 冻结 Qwen3.7-Max 快照与角色提示词；冻结统一多语言 BGE-M3 方案 | 明确现有 API 配置及中英文检索边界 | LLM 调用、提示词、检索评测 |
| 2026-07-30 | 1.2 | 固定冻结样本双端目录和 GPU 启动时机 | 样本已生成，需要安全载入并避免提前占用显卡 | 数据放置、资源调度、M1-E |
| 2026-07-30 | 1.3 | `preserved_terms` 中非原文声明项改为忽略并记录警告；数字、年份、缩写和引号内容仍由代码强制保护 | 首次真实 API 冒烟表明模型可能同时返回语义标签；为此回退整份有效查询计划过于严格 | 查询变换输出归一化 |
| 2026-07-30 | 1.4 | 增加 6 份冻结评测文档的 MinerU、Chunk、真实稠密索引与运行记录契约 | 冻结样本已就绪，需要在 M1-E 正式评测前建立可追溯且互不混淆的语料产物 | 服务器数据目录、运行记录、GPU 语料准备 |

## 13. 外部技术依据

- 阿里云百炼 `qwen3.7-max` 官方模型页：
  <https://help.aliyun.com/zh/model-studio/qwen3-7-max>
- 阿里云百炼结构化输出说明：
  <https://help.aliyun.com/zh/model-studio/qwen-structured-output>
- BAAI BGE-M3 官方模型卡：
  <https://huggingface.co/BAAI/bge-m3>
- BAAI BGE Reranker v2 M3 官方模型卡：
  <https://huggingface.co/BAAI/bge-reranker-v2-m3>
