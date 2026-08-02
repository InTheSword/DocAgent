# 长期决策

更新日期：2026-08-01

本文档记录约束后续工作的当前选择。它不是按时间排序的任务日志，也不重复
实现状态；状态请查看 `CURRENT_STATUS.md`。已被替代的讨论和实验细节可在 Git
历史中查阅。

## 产品边界

DocAgent 仍是本地、CLI 优先的个人使用文档问答 MVP。UI、云存储、多用户服务、
CDC、Demo 和新产品阶段均需要明确的范围决策。

## 执行路径

支持的路径是：文档输入或 `doc_id` 经持久化 Chunk、查询意图识别、按需查询
变换、检索、AnswerPolicy、引用和追踪产物。RAG 问答使用外部 LLM API 驱动的
两阶段 `QueryDecision -> QueryPlan`；确定性逻辑仅负责显式文档操作、约束
提取、Schema 校验和 API 失败时的有界回退。旧 Router/QueryPlanner 只保留
兼容，不再是 RAG 主路径。

## 模型与证据主张

关于真实 BGE-M3、重排序器、Qwen、MinerU API 和视觉 API 的主张必须有保存的
服务器冒烟证据。本地 fixture、hash dense、关键词重排序、启发式 AnswerPolicy
和 dry-run 路径不能证明真实组件完成。

## PDF、Chunk 与索引

- PDF 和页面图像统一交给 MinerU；DocAgent 不增加 PDF 类型分类器。OCR 默认
  交由 MinerU 自动判断，显式开关仅用于诊断或兼容。
- `Chunk` 是标准 RAG 检索与引用领域对象，不再新增独立 `RetrievalChunk`
  模型。`EvidenceBlock` 仅作为历史代码、SQLite 表名和 JSONL 文件名的兼容
  别名；新解析与检索代码使用 `Chunk`。
- MinerU 原始项不得直接进入索引。稳定边界为“原始 MinerU JSON → 字段规范化
  → 标题层级 → 保守跨页正文合并 → 超长正文句界拆分 → Chunk 元数据与关系
  定稿”；索引和引用只消费该过程输出的 Chunk。
- 每个 Chunk 的统一元数据至少保留内容类型、文档物理页、可用的标注页码、
  标题层级/章节路径、来源块 ID、全局 Chunk ID、内容哈希及可用的上游摘要/
  标签。没有可靠来源时不为满足字段完整性而伪造 LLM 摘要。
- `previous_block_id` / `next_block_id` 仅表示同页邻接；
  `previous_document_block_id` / `next_document_block_id` 表示全文阅读顺序。
  表格结构和图片/caption/邻近文本关系保存在 Chunk 元数据中，不另建第二套
  内容对象。
- 跨页合并仅处理相邻页面、相同章节和内容类型、前页末尾没有终止标点的正文/
  列表/参考文献；不自动合并标题、表格和图像。超长文本在跨页处理后按句界和
  子句界拆分，并保留来源项 ID/哈希、来源页、父 Chunk 和段序号。
- 稀疏和稠密索引只接收具有非空 `retrieval_text` 的 Chunk。无文本视觉块保留
  来源信息，但需经视觉理解补充文本后才能进入文本索引。
- 页聚合块只用于上下文读取和审计，不作为普通检索候选，避免与子 Chunk
  重复召回。Chunk 契约或 `retrieval_text` 变化后，既有文档需要重新转换并
  重建稠密索引。
- 结构化表格超过 12 行或序列化 Markdown 超过 1,800 字符时，保留完整
  `structured_parent` 供结构化查询，并生成携带完整表题、表头、单位、脚注、
  页码和行范围的 `retrieval_child` 供稀疏/稠密检索。父表不进入文本检索，
  子表不重复进入结构化索引。
- 检索评测保留两层真值：不随 Chunk 边界变化的原文 `source_evidence`，以及绑定
  PDF 哈希、MinerU 产物、Chunk 合同和 corpus manifest 的 `chunk_qrels`。未复核的
  自动对齐只能作为 candidate/诊断产物，不得进入正式 Recall/MRR。
- 稠密索引必须保存由有序 block ID、`retrieval_text`、内容哈希和 Chunk
  契约版本组成的 evidence hash；该指纹或模型不匹配时索引状态为 stale，
  不允许静默复用。
- MinerU image/chart 的非空 `content` 视为其内置视觉分析结果并直接进入
  `visual_summary`；只有图注而没有该内容时仍标记为需要视觉理解。
- 公开 MinerU v4 API 的请求模型与实际解析后端必须分开记录，以 `layout.json`
  的 backend/version/effort 作为执行事实。当前 API 未公开 `image_analysis`
  参数，真实 `vlm` 请求返回的 `hybrid/medium` 产物没有生成 image/chart
  `content`，因此像素依赖问题仍保留按需外部 VLM 路径，不使用未文档化参数。

## 查询、工具与上下文

- LLM 查询判断使用正交字段：`task_type` 表示事实查找、定位、分析、摘要或
  控制状态，`evidence_types` 可同时选择 text/table/visual，`multi_step` 表示
  是否需要独立子问题。旧 `semantic_fact/navigation/table_lookup/...` intent 仅由
  代码确定性派生，用于现有 CLI、评测和产物兼容；内部工具名不属于 LLM 契约。
- 意图路由与查询变换使用不同版本化角色提示词和精确输出 Schema。Router LLM
  只输出 `task_type/evidence_types/multi_step`，不输出置信度、理由、工具或路由；
  Transformer LLM 只输出一个 `none/rewrite/expand/decompose` 策略和最多 4 条
  检索查询。`preserve_terms` 是从原问题确定性提取并校验的约束，不再是模型动作。
- 两个 LLM 角色都请求 JSON Mode，并叠加拒绝额外字段的本地 Schema、枚举和组合
  校验。首次语义非法时最多纠错重试一次，仍非法或 API 失败才进入有界回退；trace
  不保存完整 prompt、原始生成或思维链。当前复杂查询仍只做一次静态拆解，不声称
  具备循环式 Agentic RAG。
- 显式的物理页、标注页码、内容类型和标题角色约束应在 BM25/稠密候选排序前
  执行；当前仅采用保守的确定性导航语句识别，不把一般语义词误当作字段过滤。
- Metadata 只用于 BM25/Dense 之前的候选硬过滤，不是独立排序路线，也不参与
  RRF。无关键词命中的纯导航查询可以直接返回过滤后的文档顺序结果，但不得将其
  表述为第三路检索分数。
- 普通 Hybrid 仅融合 BM25 与 Dense。显式表格意图先把候选限制为表格 Chunk：
  Markdown 序列化文本进入 BM25/Dense，`table_headers/table_rows` 进入确定性
  关系查询；两类结果按 Chunk 合并。当前只接收上游显式意图与结构化查询，不在
  检索器内部推测表格意图。
- 查询重写和查询扩展只改变检索查询；AnswerPolicy 始终接收用户原问题。
- 多查询只用于扩大 BM25/Dense 候选召回；CrossEncoder 重排以原始用户问题作为
  最终相关性目标，不以任一子查询替代用户问题。
- 检索和重排按 workflow 执行，不作为所有查询的固定流水线：navigation 默认使用
  Metadata 前置过滤与 BM25；普通正文事实和复杂/多步正文分析默认使用
  Hybrid+Reranker。查询复杂度只决定是否扩展、拆解或多路检索，不单独决定是否
  精排。纯表格结构化、纯视觉、摘要、无需检索和澄清路径不强制执行通用文本
  Reranker。调用方配置是能力上限，查询计划只能降级。
- `QueryPlan.retrieval_routes` 表示规划能力，检索 trace 另以 `executed_routes`
  记录实际执行的 sparse、dense、metadata filter、multi-query 和结构化表格路径；
  不再用规划标签命中率代替执行路径验证。
- 中英文统一使用 BGE-M3 与 bge-reranker-v2-m3；查询变换默认保持文档和问题
  语言，不对中文查询无条件生成英文扩展。只有冻结评测证明持续语言差距时才
  另立语言专用模型方案。
- 输入超限时优先减少检索证据，不允许通过保留提示词尾部而截掉系统指令或问题。
- 现有精确页读取、全量结构抽取、表格单元格选择和确定性计算继续作为文档操作
  保留；它们不能被仅返回 Top-K Chunk 的普通检索等价替换。视觉分析只在已检索
  图像/图表文本证据不足时按需执行。

## 第一阶段评测

第一阶段 RAG 报告只保留可直接量化的核心指标：Chunk 可索引数量、空检索文本
比例、来源可追溯率、Recall@5、MRR@5、平均延迟和 P95 延迟。依赖人工细粒度
标注或 LLM Judge 的忠实度、Context Precision 和引用蕴含暂不作为本阶段门禁。

## 答案质量与训练

全路径 Qwen 运行属于执行诊断，不是最终答案质量验收。正式答案质量评测、新的
SFT/GRPO 运行、检查点替换、奖励变更或训练数据构建均需明确批准。验证子集绝不
得成为训练输入。

## 数据与产物

只保留当前 Phase 5 诊断路径所需的验证输入。大型下载需要批准。生成输出、日志、
检查点、数据库和原始数据集不进入 Git；精简服务器同步包是可选排障证据，而不是
项目归档。

## 文档策略

当前规划、状态、决策、操作指南、数据集和服务器职责已在
`docs/ACTIVE_PLAN.md` 中分离。历史阶段计划、PM 任务包和过程报告被有意移除，
而非作为相互竞争的事实来源继续维护。
