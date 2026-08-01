# M1 查询意图、路由与查询变换实施计划

> 文件性质：当前阶段临时实施依据
> 计划版本：2.2
> 状态：`benchmark_evaluated`
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

### 3.1 查询决策采用正交字段，旧 intent 仅作兼容标签

M1-F2 起，LLM 不再从一个混合枚举中直接选择最终 `intent`。查询决策拆为三个
正交字段：

- `task_type`：`fact_lookup/navigation/analysis/document_summary/no_retrieval/clarification`；
- `evidence_types`：从 `text/table/visual` 选择一个或多个必要证据模态；
- `multi_step`：是否需要多个具有独立信息职责的检索子问题。

现有公开查询意图继续保留为兼容标签，并由上述字段确定性派生：

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

原有硬分类同时混合任务、证据模态、复杂度和控制状态，无法正确表达“表格加正文的
多步分析”等组合查询，不再作为 LLM 的首要判断空间。`selected_tools` 不属于新的
查询决策契约。实际调用哪个现有执行器，由查询计划到运行时的适配层决定。

### 3.2 查询变换动作固定为受限集合

LLM 只选择一个互斥的查询变换策略：

- `none`
- `rewrite`
- `expand`
- `decompose`
- `request_clarification` 仅由澄清短路路径确定性产生，不交给查询变换 LLM 选择

`preserve_terms` 不再是变换动作。实体、数字、年份、引文和缩写的保护由代码从原始
问题确定性提取并校验。LLM 只能从当前请求提供的策略白名单中选择一个值，不能组合
策略或创造新动作。

### 3.3 采用两阶段决策

第一阶段是意图路由：

- 输入只包含原始问题和轻量文档画像；
- 只输出 `task_type/evidence_types/multi_step`；
- 检索必要性、兼容 intent、候选执行路径、元数据约束和执行模式由代码派生；
- 不读取 PDF 正文、Chunk 或检索结果；
- 不生成答案。

第二阶段是查询变换：

- 输入原始问题、第一阶段意图和允许动作；
- 由 LLM 判断使用 `none`、`rewrite`、`expand` 或 `decompose`；
- 仅在需要查询变换的路径调用；
- 只输出一个 `strategy` 和一个或多个 `retrieval_queries`；
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
| `intent_router` | 查询任务、必要证据模态与是否多步 | 回答问题、生成检索查询、读取正文、选择内部工具、输出置信度或理由 | `task_type/evidence_types/multi_step` |
| `query_transformer` | 在允许动作内选择 `none/rewrite/expand/decompose` 并生成检索查询 | 改变原始需求、回答问题、创建新意图、选择执行工具 | `QueryPlan` 的变换字段 |

两个角色不得共用一份模糊的“Router/Planner”提示词。提示词需要分别版本化，并在
trace 中记录 `role`、`prompt_version`、`model_id` 和校验结果，不记录完整思维链。

官方结构化输出文档列明 Qwen3.7-Max 系列支持 JSON Mode。实现继续请求
`response_format=json_object`，但 JSON 可解析不等于字段语义正确，因此必须叠加
精确字段校验、枚举与组合约束、至多一次纠错重试和确定性回退，并通过当前精确快照
的真实 API 冒烟确认行为。

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

检索与重排按 workflow 条件执行：navigation 默认 Metadata 前置过滤加 BM25；简单
正文事实默认 Hybrid 但不重排；复杂/多步正文分析才默认 Hybrid+Reranker；表格、
视觉、摘要、无需检索和澄清路径不强制套用通用 Hybrid+Reranker。运行时显式配置是
能力上限，查询计划只能降级，不能静默启用未配置的真实模型。

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
  "task_type": "fact_lookup",
  "evidence_types": ["text"],
  "multi_step": false,
  "intent": "semantic_fact",
  "confidence": 0.0,
  "requires_retrieval": true,
  "allowed_actions": ["none", "rewrite", "expand", "preserve_terms"],
  "retrieval_routes": ["dense", "sparse"],
  "retriever_mode": "hybrid",
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
- `task_type/evidence_types/multi_step` 是 LLM 决策的唯一字段，必须严格符合 Schema；
- `intent`、动作、路径和 `retriever_mode` 由代码派生并来自枚举；
- `confidence/reason` 只为读取旧产物和 CLI 兼容保留，新 LLM 不再生成这两个字段；
- `metadata_filter` 只保存能从问题或文档画像可靠获得的约束。

### 4.2 QueryPlan

```json
{
  "original_question": "用户原始问题",
  "intent": "semantic_fact",
  "actions": ["rewrite", "preserve_terms"],
  "retrieval_queries": ["检索查询"],
  "retrieval_routes": ["dense", "sparse"],
  "retriever_mode": "hybrid",
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

M1-E 使用单一评测入口：

```text
scripts/eval_m1_query_retrieval.py
```

评测分为两个可恢复阶段，但属于同一次冻结运行：

1. `query`：真实 Qwen 意图识别和查询变换，逐条写入 checkpoint；
2. `retrieval`：加载六文档已有 Chunk/索引，执行原问题与计划查询的四配置对比。

查询侧主指标：

- 意图准确率；
- 查询动作严格有序 Exact Match；
- 查询动作集合 Exact Match；
- 必需检索路径全部命中率与路径 micro recall；
- `must_preserve` 术语完整保留率；
- LLM、fallback、短路和校验失败计数。

冻结标签允许 `none + preserve_terms`，而当前 `QueryPlan` 契约只允许单独的 `none`。
首次基线必须按现状严格计分并在限制中单列该契约差异，不得在运行前修改冻结样本
或为提高动作分数而放宽实现契约。

Gold evidence 映射规则：

- 只使用 `verbatim_content`、`physical_pages` 和 `evidence_type`；
- 先在指定物理页和兼容内容类型中做 Unicode/空白/Markdown 归一化后的包含匹配；
- 仅在包含匹配失败时使用统一阈值的页内字符覆盖 fallback；
- 每个证据组映射为一个或多个 Chunk ID，并保存匹配方法和分数；
- 未映射证据组必须进入失败样本，不能从指标分母静默删除；
- 同时报告映射覆盖率、仅已映射组检索指标和包含未映射组为零分的端到端指标。

检索侧固定比较：

```text
query_variant = original | planned
retriever = bm25 | dense | hybrid | hybrid_rerank
Recall@5
MRR@10
```

`original` 与 `planned` 使用相同的预测 Metadata Filter 和表格意图约束，二者只在
检索查询文本上不同，以便观察查询变换的下游影响。四种检索器均使用相同 Chunk；
Dense/Hybrid/Hybrid+Reranker 使用已保存的真实 BGE-M3 索引，
Hybrid+Reranker 使用真实 `bge-reranker-v2-m3`。不使用 hash dense 或 keyword
reranker 生成正式指标。

完整运行目录：

```text
outputs/m1_query_retrieval_baseline_20260730/
  query_predictions.jsonl
  gold_chunk_mapping.jsonl
  retrieval_details.jsonl
  metrics.json
  result.json
  manifest.json
  summary.json
  summary.md
  failures.jsonl
  logs/
```

精选同步包：

```text
outputs/sync/m1_query_retrieval_baseline_20260730/
  result.json
  manifest.json
  summary.json
  summary.md
  preview.json
  failures_sample.jsonl
  log_tail.txt
  stderr_tail.txt
```

完整输出只保留在服务器。同步包不得包含完整问题、完整模型输出、原文证据、
Chunk 正文、密钥、数据库或模型权重。

### M1-E 首次冻结基线结果

服务器运行：

```text
outputs/m1_query_retrieval_baseline_20260730/
outputs/sync/m1_query_retrieval_baseline_20260730/
Git commit: dfb0a2f
```

真实 `qwen3.7-max-2026-05-17`、BGE-M3、bge-reranker-v2-m3 和六文档
Chunk/FAISS 产物已完成 94 条查询侧评测及 86 条文档绑定样本的 688 组检索对照，
状态为 `benchmark_evaluated`，不等于 `accepted`。

主要基线：

- 意图准确率 0.8404；
- 查询动作有序/集合 Exact Match 均为 0.1596；
- 必需路由全部命中率 0.7128，路由 micro recall 0.8153；
- `must_preserve` micro recall 0.5693；
- 150 个 Gold evidence group 中 90 个可稳定映射到 Chunk，映射率 0.6000；
- 原问题 Hybrid 的端到端/仅已映射 Recall@5 为 0.4267/0.7111，
  MRR@10 为 0.5043；
- 计划查询 Hybrid 的端到端/仅已映射 Recall@5 同为 0.4267/0.7111，
  MRR@10 为 0.4520；
- 计划查询 Hybrid+Reranker 的端到端/仅已映射 Recall@5 为
  0.4000/0.6667，MRR@10 为 0.5087。

首次基线说明查询变换未带来整体检索收益，重排序器提升排序位置但降低部分
Recall@5；`clarification_required`、`table_lookup` 路由、查询动作标签契约和
Gold→Chunk 映射是进入验收前的主要问题。不得使用同一冻结集做个案 prompt、
路由规则或样本专属映射修补。

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

### M1-F1：高价值失败修复（评测合同与多查询重排）

首次基线暴露的样本合同、workflow 覆盖和重排查询错误会污染后续优化结论，必须先于
提示词规则调优、RRF 权重调优和动态复杂查询循环修复。本批只处理能够由通用规则
验证的基础问题，不根据冻结样本增加个案规则。

#### 当前缺口

1. `query_actions` 同时混合互斥变换动作与 `preserve_terms` 约束，旧 Exact Match
   将合同不兼容计为模型错误；
2. `expected_routes` 是规划标签，不等于运行时实际执行路径，旧路由分数不能证明
   检索链真正执行；
3. 旧评测把表格、视觉和文档摘要样本强制送入通用文本检索四配置，主指标包含并未
   执行对应生产 workflow 的代理结果；
4. Gold→Chunk 自动映射尚未经复核，却被直接用作检索 qrels；
5. 多查询召回后，重排器只使用 `active_queries[0]`，最终排序可能偏向第一个子查询，
   而不是原始用户问题。

#### 已确定方案与接口契约

1. 查询动作评测拆成：
   - `transform_action_*`：仅比较 `none/rewrite/expand/decompose/request_clarification`；
   - `must_preserve_*`：继续单独衡量受保护术语；
   - 旧动作 EM 保留为 `legacy_action_*` 诊断字段，不再作为主结论。
2. 查询侧增加 `expected_workflow/predicted_workflow` 与 workflow accuracy。旧
   `expected_routes` 分数保留为 legacy 标签诊断，不宣称为执行路径指标。
3. 检索结果增加 `executed_routes`：用统一路由名记录实际执行的 `sparse`、
   `dense`、`metadata_filter`、`multi_query` 和 `table_structured`。保留既有
   `retrieval_routes` 字段兼容旧调用方。
4. M1 通用检索主指标只覆盖当前真实走文本检索链的 `semantic_fact`、
   `navigation` 和 `complex_analysis`。`table_*`、`visual_lookup`、
   `document_summary`、`no_retrieval` 与 `clarification_required` 按 workflow
   统计为未被本 runner 专用评测覆盖，不用代理结果混入主均值。
5. `gold_chunk_mapping.jsonl` 明确标记为自动生成的 qrel candidate，summary 标记
   检索指标为 provisional。只有绑定 Chunk 合同版本并经复核的 Chunk qrels 才能
   用于正式检索验收；本批不改写冻结样本。
6. 多查询的 BM25/Dense 仍负责扩大候选召回，CrossEncoder 重排统一使用原始用户
   问题作为相关性目标。本批不改变 RRF 权重、不自动添加额外查询。

#### 文件范围

- `scripts/eval_m1_query_retrieval.py`
- `docagent/retrieval/hybrid_retriever.py`
- `tests/test_m1_query_retrieval_eval.py`
- 与多查询重排直接相关的一项检索测试
- 本计划与 `docs/ACTIVE_PLAN.md`

不修改用户已手工调整的 `intent_router` 和 `query_transformer` 提示词。

#### 验收测试

1. `none + preserve_terms` 与 `none` 的变换动作比较能够命中，但 legacy EM 仍能
   如实显示原始标签不同；
2. workflow 指标不再使用路由标签模拟执行成功；
3. 通用检索样本筛选排除表格、视觉和摘要 workflow，并报告各 workflow 覆盖数；
4. 自动 Gold 映射产物明确为未复核 candidate；
5. 多查询 Hybrid+Reranker 测试证明 reranker 收到原始问题，而不是第一条子查询；
6. 查询、检索和 CLI 相关既有回归通过。

#### 资源边界、迁移和停止条件

- 合同、执行记录、评测筛选和重排接线属于 `local_only`，先在本地完成确定性测试；
- 六文档真实 Qwen/BGE-M3/reranker 重跑属于 `server_required`，需要 GPU 服务器；
- 旧产物保持可读，新 runner 通过版本号和新增字段区分，不回写历史运行；
- 本批本地验证完成后停止并报告服务器重跑要求，不自动进入提示词规则、RRF、
  表格专用评测、VLM 或动态 Agentic loop。

#### 本地验证结果（2026-07-31）

- M1-F1 合同与检索接线已实现；
- 查询、检索、表格索引、模型包装器和 CLI 相关回归共 112 项通过；
- 当前仅达到本批确定性逻辑的 `mock_verified`；
- runner v2 尚未在六文档真实 Qwen/BGE-M3/reranker 环境重跑，因此 M1 整体仍沿用
  既有 `benchmark_evaluated` 状态，不得用 v1 分数评价 v2 修复收益。

#### 六文档真实验证结果（2026-07-31）

服务器 worktree 在执行 `source /etc/network_turbo` 后快进到提交 `2d880e8`，
112 项相关回归通过。runner v2 使用真实 `qwen3.7-max-2026-05-17`、BGE-M3、
bge-reranker-v2-m3 和 6 份冻结文档完成运行：

```text
outputs/m1_query_retrieval_v2_20260731/
outputs/sync/m1_query_retrieval_v2_20260731/
```

运行范围与主要结果：

- 查询样本 94 条；通用文本检索主指标只覆盖 54 条
  `semantic_fact/navigation/complex_analysis`；
- 意图准确率 0.8511，workflow accuracy 0.8617；
- 变换动作 Exact Match 0.4362；旧混合动作标签 EM 0.0957，仅保留作诊断；
- `must_preserve` micro recall 0.5545；
- 11 条 QueryTransformer 输出选择了意图不允许的 action，触发统一 fallback；
- 全 workflow Gold→Chunk 自动映射率仍为 0.6000，54 条通用检索范围内为
  0.5882；两者都只是未复核 qrel candidate；
- 原问题 Hybrid 的 provisional E2E Recall@5/MRR@10 为 0.4314/0.5230；
- 计划查询 Hybrid 为 0.4314/0.4380，Recall 没有改善且 MRR 下降 0.0850；
- 计划查询 Hybrid+Reranker 为 0.3529/0.5016；相对计划 Hybrid，MRR 提升
  0.0636，但 Recall@5 下降 0.0784；
- 计划路由 micro realization 为 0.8702；11 条缺少实际 metadata filter，3 条
  计划声明的 table text/structured 路由没有由当前通用 runner 执行；
- 精简同步包约 52 KB，7/7 文件大小与 SHA256 核验通过，不含密钥、全文、模型、
  数据库或完整日志。

本批修复证明评测口径和重排查询接线已按计划生效，但没有证明查询变换或重排产生
整体正收益。M1-F1 状态为 `benchmark_evaluated`，仍不满足 `accepted`。

后续问题按处理价值排序，但不在 M1-F1 自动实施：

1. 修复 QueryTransformer action 与 `allowed_actions` 的契约稳定性，消除 11 条
   可复现 validation fallback，并继续把术语保护作为独立约束；
2. 修复 `clarification_required` 0/4 和 `complex_analysis` 10/18 的通用意图边界；
3. 在独立开发集验证原问题锚点、条件变换和多查询融合，不用冻结测试集调权重；
4. 按意图分析重排策略，尤其是 navigation/complex 的 Recall 退化；任何融合阈值
   必须在开发集确定后再冻结测试；
5. 另建表格、视觉和摘要 workflow 评测，并复核 Chunk qrels；不得重新把代理文本
   检索分数混入通用检索主指标。

### M1-F2：正交查询决策、受约束变换与条件化检索

#### 当前缺口

1. 单一 `intent` 混合任务、证据模态、复杂度和控制状态，组合查询表达能力不足；
2. 查询变换输出允许多动作，且把 `preserve_terms` 当作动作，模型容易违反
   `allowed_actions`；
3. Router 输出 `confidence/reason`，但后续执行不需要这些主观字段；
4. JSON Mode 之后只有一次本地校验，非法语义输出立即退回规则，没有有界纠错机会；
5. CLI 的 `user_best` 默认对所有通用问答初始化 Hybrid+Reranker，未落实按 workflow
   选择检索与重排。

#### 已确定方案与接口契约

1. Router LLM 精确输出：
   `{"task_type":"...","evidence_types":["..."],"multi_step":false}`；禁止输出
   置信度、理由、工具、路由、检索查询或额外字段。
2. `task_type`、`evidence_types` 与 `multi_step` 经过严格类型、枚举和组合校验；旧
   `intent`、`requires_retrieval`、`allowed_actions`、`retrieval_routes`、
   `retriever_mode` 由确定性策略生成，保持既有产物和评测兼容。
3. Transformer LLM 精确输出：
   `{"strategy":"none|rewrite|expand|decompose","retrieval_queries":[...]}`；一次只允许
   一个策略。保护术语完全由代码提取和校验，不由模型声明。
4. 两个角色均使用 JSON Mode、严格字段拒绝、组合约束、至多一次携带精简校验错误的
   纠错重试；两次均失败才使用既有有界回退。trace 只记录状态、尝试次数和错误类别，
   不记录完整 prompt、原始生成或思维链。
5. 条件化策略固定为：navigation→BM25；简单正文事实与视觉文本召回→Hybrid；
   complex/multi-step 正文分析→Hybrid+Reranker；表格专用工具、摘要、no retrieval、
   clarification 不强制初始化通用 Hybrid+Reranker。调用方显式 `retriever_mode` 是能力
   上限，计划只允许降级。
6. 本批只验证通用契约与执行选择，不用冻结六文档测试集调 prompt、融合权重、阈值或
   reranker 候选规模。

#### 文件范围

- `docagent/query/schemas.py`
- `docagent/query/intent_router.py`
- `docagent/query/query_transformer.py`
- `docagent/query/pipeline.py`（仅必要 trace 接线）
- `scripts/docagent_cli.py`（仅检索模式降级适配）
- 上述模块的定向测试
- 本计划、`docs/ACTIVE_PLAN.md`，验收后更新稳定状态文档

不修改 Dense/BM25/RRF/重排序算法、Chunk、表格关系索引、AnswerPolicy、VLM、SFT
或 GRPO。

#### 验收测试

1. 中英文简单事实、定位、表格、视觉、混合证据、复杂分析、摘要、无需检索和澄清
   通用样例均能表达为正交字段并派生兼容 intent/workflow；
2. Router 与 Transformer 拒绝额外字段、未知枚举、非法组合、空查询、超量查询和
   受保护术语丢失；首次非法、第二次合法时成功，连续非法时有界回退；
3. Transformer 不再输出或接收 `preserved_terms`，也不会产生组合 action；
4. navigation 不初始化 Dense/Reranker，简单事实不初始化 Reranker，complex/multi-step
   在运行时允许时使用 Hybrid+Reranker；显式 BM25 配置不会被计划升级；
5. 查询、检索和 CLI 相关回归通过；服务器真实 Qwen API 冒烟确认两个角色输出合法，
   真实 BGE-M3/reranker 冒烟确认条件化初始化与执行元数据。

#### 资源边界、迁移和停止条件

- Prompt、Schema、校验、重试和模式选择属于 `local_only`；真实 Qwen API 属于
  `server_optional`，真实 BGE-M3/reranker 联合接线属于 `server_required`；
- 旧 `intent/confidence/reason` 和历史 `preserve_terms` 仍可从旧产物读取，但新 LLM
  不再输出；删除兼容字段留待独立迁移，不在本批扩大范围；
- 本批只使用人工编写的通用契约/冒烟样例开发。完成本地回归和一次服务器真实冒烟后
  更新状态并停止，不自动运行冻结基准或进入动态 Agentic loop。

#### 验证结果（2026-08-01）

- 本地和服务器相同的查询、检索、表格、CLI 与兼容层回归均为 244 项通过；
- 服务器 worktree 在执行 `source /etc/network_turbo` 后快进到提交 `d2b52b6`；
- 真实 `qwen3.7-max-2026-05-17` 使用 8 条独立编写的中英文通用冒烟样例：8/8
  输出合法、8/8 匹配预期正交字段、0 次纠错重试、0 次 fallback；
- navigation 实际使用 BM25，未加载 Dense/Reranker；简单事实实际使用 BGE-M3
  Hybrid，未加载 Reranker；复杂分析实际使用 BGE-M3 Hybrid 与
  bge-reranker-v2-m3；三路均返回候选并记录实际执行路径；
- 精简证据保存在服务器
  `outputs/sync/m1_f2_query_policy_smoke_20260801/`，6 个文件共约 7.4 KB，全部
  SHA256 校验通过，不含密钥、全文、数据库或模型；
- 本批状态为 `real_model_verified`。没有重跑冻结六文档 benchmark，因此不宣称
  新契约已经获得正式检索指标正收益或达到 `accepted`。

### M1-F3：纠正 workflow 的重排执行策略

#### 当前缺口

M1-F2 把“简单正文事实”硬编码为 Hybrid 但不重排，将查询复杂度与是否需要
二阶段相关性精排错误绑定。现有分类结果不支持该结论：普通语义事实查询在重排
后 Recall 基本稳定且 MRR 改善；退化主要出现在导航和部分复杂查询，不能推导出
普通事实查询应固定绕过 Reranker。

#### 已确定方案与边界

1. 普通正文事实查询默认使用 `Hybrid+Reranker`；查询复杂度只决定是否扩展、
   拆解或多路检索，不单独决定是否精排。
2. 复杂/多步正文分析继续使用 `Hybrid+Reranker`。
3. 精确导航继续使用 Metadata 前置约束加 BM25；纯表格结构化、纯视觉、全局摘要、
   `no_retrieval` 和 `clarification` 不强制套用通用文本 Reranker。
4. 混合模态或同时需要正文的查询，通用文本候选仍可重排；结构化结果和视觉结果
   不伪装成通用文本候选参与精排。
5. 调用方显式 `retriever_mode` 仍是能力上限；计划不得把 `bm25`/`hybrid` 静默升级为
   需要未配置真实模型的 `hybrid_rerank`。

#### 文件范围与验收

- 修改 `docagent/query/intent_router.py` 中的确定性执行策略；
- 只修改查询决策、查询计划和 CLI 检索模式接线的定向测试；
- 不修改 RRF、Reranker 模型/打分方法、候选规模、融合权重、Chunk 或冻结评测样本；
- 本地验收要证明事实查询默认计划重排、专用 workflow 按规则绕过，以及能力上限
  不被静默升级；
- 若真实检索接线因模式变化而受影响，在正式评测前执行一次真实 BGE-M3/reranker
  服务器冒烟，但不在本批调参或重跑冻结 benchmark。

#### 验证结果（2026-08-01）

- 本地查询决策、变换、流水线、CLI、Metadata、表格和 M1 runner 相关回归
  99 项通过；
- 服务器 worktree 在执行 `source /etc/network_turbo` 后快进到提交 `6813cd8`；
- 真实普通事实查询的 planned/effective mode 均为 `hybrid_rerank`，实际使用
  BGE-M3 与 `bge-reranker-v2-m3` Cross-Encoder；
- 冒烟返回 3 个候选，3/3 具有重排分数，实际执行路由为 Dense+Sparse，既有
  稠密索引未重建；
- 精简证据保存在服务器
  `outputs/sync/m1_f3_fact_reranker_smoke_20260801/`，不含密钥、全文、数据库或模型；
- M1-F3 状态为 `real_model_verified`。本批没有重跑冻结 benchmark，不宣称重排已对全部
  workflow 带来正收益。

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
| 2026-07-30 | 1.5 | 固定 M1-E runner、证据组映射、原问题/计划查询对照、四检索配置、指标和产物契约 | 运行首次正式基线前必须区分样本契约差异、证据映射失败和真实检索失败 | M1-E 评测实现与服务器基线 |
| 2026-07-30 | 1.6 | 记录首次六文档真实冻结基线，并保持未验收状态 | 基线已完成，但查询动作契约、部分意图/路由和 Gold→Chunk 映射仍有明显缺口 | M1-E 结果与下一步边界 |
| 2026-07-31 | 1.7 | 增加 M1-F1：拆分动作/约束指标，区分规划与执行路径，按真实 workflow 限定通用检索主指标，标记自动 qrel candidate，并修复多查询重排目标 | 首次基线中的合同污染和重排接线错误会使后续调优结论失真，需按价值优先修复 | M1 评测器、检索执行元数据与多查询重排 |
| 2026-07-31 | 1.8 | 记录 M1-F1 六文档 runner v2 真实验证与下一批问题优先级，保持未验收 | 修复后的评测口径已生效，但查询变换和重排仍无整体正收益，需防止用冻结测试集直接调参 | M1-F1 验证结论与停止边界 |
| 2026-08-01 | 1.9 | 增加 M1-F2：正交查询决策、单策略查询变换、JSON Mode 加严格校验/一次纠错重试，以及按 workflow 降级检索和重排 | 修复混合硬分类、11 条 action 合同失败、冗余 LLM 输出和全局 Hybrid+Reranker 执行 | 查询 Schema、两个 LLM 角色、CLI 检索模式适配与定向验证 |
| 2026-08-01 | 2.0 | 记录 M1-F2 本地/服务器回归、真实 Qwen API 与真实 BGE-M3/reranker 条件化接线结果，并停止在 `real_model_verified` | 当前执行契约已获真实组件证据，但未使用冻结集调优或重跑正式 benchmark | M1-F2 验证结论、状态与停止边界 |
| 2026-08-01 | 2.1 | 增加 M1-F3：普通正文事实默认恢复 Hybrid+Reranker，专用 workflow 保留有依据的绕过 | M1-F2 错误将查询复杂度与是否精排绑定，且与已有按意图分析证据不符 | 确定性 workflow 策略、检索模式接线与定向测试 |
| 2026-08-01 | 2.2 | 记录 M1-F3 本地回归与真实 BGE-M3/reranker 事实查询冒烟，并停止在 `real_model_verified` | 修正后的执行模式已获真实组件接线证据，但尚未进行正式分类评测 | M1-F3 验证结论、状态与停止边界 |

## 13. 外部技术依据

- 阿里云百炼 `qwen3.7-max` 官方模型页：
  <https://help.aliyun.com/zh/model-studio/qwen3-7-max>
- 阿里云百炼结构化输出说明：
  <https://help.aliyun.com/zh/model-studio/qwen-structured-output>
- BAAI BGE-M3 官方模型卡：
  <https://huggingface.co/BAAI/bge-m3>
- BAAI BGE Reranker v2 M3 官方模型卡：
  <https://huggingface.co/BAAI/bge-reranker-v2-m3>
- LangGraph Agentic RAG 官方示例（条件检索、相关性判断、查询重写与生成边）：
  <https://docs.langchain.com/oss/javascript/langgraph/agentic-rag>
- Anthropic Contextual Retrieval（BM25、Embedding 与可选 Reranking 的组合）：
  <https://www.anthropic.com/news/contextual-retrieval>
- Elasticsearch RRF 与 Ranking 官方文档（多检索器融合和二阶段重排）：
  <https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion>
  <https://www.elastic.co/docs/solutions/search/ranking>
