# 长期决策

更新日期：2026-08-05

> 本文档只记录会约束后续实现的稳定选择。当前完成状态和指标见
> `CURRENT_STATUS.md`，当前实施授权见 `docs/ACTIVE_PLAN.md`，历史方案演进见
> `docs/workplans/README.md`。

## 1. 产品与执行边界

- DocAgent 是本地、CLI 优先的个人复杂文档问答 MVP。UI、云存储、多用户服务、
  CDC、Demo 和新产品阶段必须单独立项。
- 规范主路径为：文档输入或 `doc_id` → MinerU 原始结果 → 规范 Chunk → 查询决策与
  按需查询变换 → 路由化检索/确定性工具 → AnswerPolicy → 答案、证据、引用与 trace。
- RAG 查询侧使用外部 LLM API 的两个独立角色：`QueryDecision` 负责识别任务需求，
  `QueryPlan` 负责决定是否 rewrite、expand 或 decompose。旧 Router/Planner 仅保留兼容，
  不再是目标主路径。
- 本地小模型保留给 AnswerPolicy 和后续有明确训练价值的垂直任务；不能为了满足“包含
  微调”而仅训练输出格式。

## 2. PDF、Chunk 与索引

### 2.1 MinerU 边界

- PDF 统一交给 MinerU，不新增 PDF 类型分类器。原始 PDF API 默认请求 OCR，但公开
  `is_ocr` 不能被解释为图片区域一定产生 OCR/VLM 内容。
- 请求模型和实际解析后端分别记录；执行事实以 MinerU 返回的 layout backend、version
  和 effort 为准。没有 image/chart 内容时保留视觉证据缺口，不伪造摘要。
- MinerU 原始项不能直接索引。索引与引用只能消费经过字段规范化、结构恢复、关系处理、
  跨页处理和长度切分后的 Chunk。

### 2.2 统一 Chunk 对象

- `Chunk` 是检索和引用的唯一领域对象，不再新建 `RetrievalChunk`。
  `EvidenceBlock` 只作为历史代码、SQLite 表名和 JSONL 文件名的兼容名称。
- Chunk 至少保留内容类型、物理页、可用的标注页码、标题层级/章节路径、来源项 ID、
  全局 ID、内容哈希、关系字段和可用的上游摘要/标签。字段没有可靠来源时不得补造。
- 原始 `Chunk.text` 与引用证据保持原文；`retrieval_text` 和 BM25 查询使用 NFKC，解决
  全角拉丁字母和数字召回问题而不破坏溯源。
- 同页邻接与全文阅读顺序使用不同关系字段；表格、图片、caption 和邻近正文的关系保存
  在 Chunk 元数据中，不建立第二套内容对象。

### 2.3 合并、切分与特殊内容

- 跨页合并只处理相邻页面、相同章节与兼容类型，且前页末尾没有终止标点的正文、列表
  或参考文献；标题、表格和图片不得自动跨页合并。
- 超长正文在跨页处理后按句子/子句边界拆分，并保留来源项、父 Chunk、来源页和段序号。
- MinerU 的 code/algorithm 项组合 caption、body 和 footnote 后形成可索引 Chunk，不能
  因缺少通用 `text/content` 字段而丢弃。
- 图题和正文分离必须基于可复用的文本、邻接和 bbox 证据，不能为单个样本增加特例。
- 页聚合块只用于上下文读取和审计，不进入普通 Top-K 检索。

### 2.4 表格与视觉内容

- 长表保留一个 `structured_parent` 供关系查询，并生成携带表题、完整表头、单位、脚注、
  页码和行范围的 `retrieval_child` 供文本检索。父表不进入文本检索，子表不重复进入
  结构化索引。
- 当前长表触发条件为超过 12 行或 Markdown 序列化超过 1,800 字符；修改阈值必须通过
  新的阶段评测，而不是针对单表调参。
- 无文本视觉块保留来源与关系，但只有获得可靠视觉摘要后才可进入文本索引。图题命中
  不能被描述为图内理解；像素依赖问题按需调用外部 VLM。

### 2.5 索引一致性

- 稀疏和稠密索引只接收非空 `retrieval_text` 的可索引 Chunk。
- 稠密索引保存由有序 Chunk ID、检索文本、内容哈希、Chunk 契约版本和嵌入模型组成的
  指纹；任一不匹配即为 stale，不得静默复用。
- Chunk 契约或检索文本变化后，受影响文档必须重新转换并重建稠密索引。

## 3. 查询、路由与检索

### 3.1 LLM 输出合同

- `QueryDecision` 使用正交字段表达任务类型、证据类型和是否多步；不让 LLM 输出置信度、
  理由、工具名或内部 workflow。
- `QueryPlan` 只输出一个 `none/rewrite/expand/decompose` 动作和最多 4 条检索查询。
  `preserve_terms` 由确定性逻辑提取和校验，不是模型动作。
- 两个角色使用独立、版本化提示词和拒绝额外字段的 Schema。首次语义非法最多纠错一次，
  仍非法或 API 失败时进入有界回退；trace 不保存完整 prompt、原始生成或思维链。
- 当前复杂查询只进行一次静态拆解，不声称已经实现循环式 Agentic RAG。

### 3.2 检索执行

- 显式物理页、标注页码、内容类型和标题角色约束在 BM25/Dense 前执行。Metadata 是前置
  过滤，不是参与 RRF 的第三路检索分数。
- 普通 Hybrid 只融合 BM25 与 Dense；RRF 按规范 Chunk ID 去重。多查询用于扩大候选，
  CrossEncoder 最终始终以用户原问题重排。
- 检索和精排按 workflow 执行，而不是所有查询固定通过同一流水线。调用方配置是能力
  上限，查询计划只能降级。
- 显式表格查询并行使用表格 Chunk 的 BM25/Dense 召回与确定性关系查询，再按 Chunk
  合并；纯结构化、纯视觉、摘要、无需检索和澄清路径不强制执行通用文本 Reranker。
- `QueryPlan.retrieval_routes` 表示计划能力，trace 的 `executed_routes` 记录实际稀疏、
  稠密、Metadata、多查询和结构化路径；不得用计划标签冒充实际执行。

### 3.3 问题、上下文与工具

- 查询重写、扩展和拆解只改变检索查询；AnswerPolicy 始终接收用户原问题。
- 输入超限时优先裁减检索证据，不允许截掉系统指令或用户问题。
- 精确页读取、全量结构抽取、表格单元格选择和确定性计算是文档操作能力，不能被普通
  Top-K 检索等价替换。视觉分析只在已召回文本证据不足时按需执行。
- 中英文统一使用 BGE-M3 与 bge-reranker-v2-m3；只有新的冻结评测证明持续语言差距时，
  才考虑语言专用嵌入模型。

## 4. 评测、训练与证据

- 检索评测保留不随 Chunk 边界变化的 `source_evidence` 和绑定具体 corpus 的
  `chunk_qrels`。未复核自动对齐只能作为 candidate，不能进入正式 Recall/MRR。
- `acceptable_chunk_sets` 的内层 Chunk 为 AND、不同集合为 OR；qrels 只能引用可索引
  Chunk，并绑定样本、PDF、corpus manifest、Chunk 内容和复核决策哈希。
- 正式检索至少报告 evidence-group Recall@5、Any-group Hit@5、All-required-groups
  Hit@5、MRR@10、平均延迟和 P95；表格结构化答案与视觉理解另行评测。
- 冻结评测集不得用于训练，也不得在同一小集合上反复调参。一次正式评测后的优化需要
  新 workplan，并保留原始结果。
- 全路径真实模型运行只证明执行链可用。最终答案正确性、忠实度、引用支持度、视觉答案
  质量和新的 SFT/GRPO 均需要独立目标、独立数据与验收合同。
- Mock、fixture、hash dense、关键词 reranker、启发式 AnswerPolicy 和 dry-run 不能证明
  真实模型能力。涉及真实模型的主张必须有服务器/API 验证和紧凑可核验产物。

## 5. 数据、产物与文档治理

- 大型模型、数据集、数据库、完整日志、原始输出树和密钥不进入 Git；服务器只按需要
  生成紧凑同步包，本地无需复制非必要大型结果。
- `AGENTS.md` 规定执行规则；`ACTIVE_PLAN.md` 只登记唯一活动方案；
  `docs/workplans/README.md` 负责方案发现；`CURRENT_STATUS.md` 记录当前事实；本文记录
  长期决策。任何历史报告、旧设计或审查文档都不能自行授权实施。
- 大范围实现完成后，稳定结论进入本文或 `CURRENT_STATUS.md`，活动引用从
  `ACTIVE_PLAN.md` 移除；已完成 workplan 保留用于审计，但不继续充当当前事实来源。
