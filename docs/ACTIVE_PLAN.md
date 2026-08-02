# 当前计划

> 当前里程碑、范围边界和停止条件的唯一来源。历史任务记录保留在 Git
> 历史中，不作为当前规划输入。

## 当前阶段

```text
Phase 5 个人使用 DocAgent MVP
```

## 当前实施依据

本阶段优先修复 Chunk 质量与检索 qrels 对齐。实现、范围变更和验收以以下临时计划为准：

```text
docs/workplans/M1_CHUNK_QRELS_ALIGNMENT_PLAN.md
```

任何方案变化必须先更新该计划的“方案变更记录”，再继续修改代码。

## 当前目标

维护已验收的本地、CLI 优先的文档问答交付路径：

```text
文件或既有文档
-> 导入 / 持久化 Chunk
-> 路由与检索
-> AnswerPolicy
-> answer + reasoning_summary + evidence_used + citations + trace_path
```

本阶段将把 RAG 问答主路径迁移为外部 LLM API 驱动的查询意图识别和按需查询
变换。确定性逻辑只承担显式文档操作、契约校验和 API 失败时的有界回退；旧
规则路由与旧查询规划器在新链路验收前保留兼容，但不再作为目标架构。

## 已验证的交付状态

| 能力 | 状态 | 边界 |
|---|---|---|
| 旧路由与查询规划兼容 | `accepted` | 仅保留显式文档操作与旧产物字段兼容，不再是 RAG 问答主路径。 |
| 统一 CLI 与文件到答案导入 | `accepted` | 已接入文本、既有 MinerU 输出和原始 PDF MinerU API 输入。 |
| 全模型工作流 | `real_model_verified` | 真实 API 路由/规划、BGE-M3、重排序器、Qwen AnswerPolicy、引用和追踪产物均有服务器冒烟证据。 |
| 证据恢复与仅 stderr 进度反馈 | `real_model_verified` | `user_best` 启用有界替换检索，JSON stdout 仍兼容。 |
| 确定性文档摘要、表格查找和简单计算 | `implemented` | 已有本地定向和 Phase 5 回归覆盖。 |
| MinerU Chunk 与索引契约 | `real_model_verified` | 12 页真实 VideoTree MinerU 产物在本地与服务器均重建为 184 个 `docagent_chunk_v3` Chunk（171 个可索引、3 个跨页、12 个句界拆分），契约错误为 0，并已用真实 BGE-M3 建立索引。 |
| 多路检索与结构化约束 | `real_model_verified` | 不经意图路由、查询规划和查询重写的真实 BGE-M3＋重排序器验证中，普通查询 Hit@5 为 18/18，表格文本 Hit@5 为 6/6，4 个结构化查询精确匹配；Metadata 仅作前置过滤。该小型回归集不是正式检索基准。 |
| 原问题/检索查询分离与证据优先截断 | `implemented` | 查询变换只进入检索；问答保留原问题，超限时先裁减证据。新的 AnswerPolicy 联合冒烟尚未执行。 |
| 新查询意图、路由与查询变换链 | `real_model_verified` | M1-F2 当前契约已改为正交任务/证据/复杂度字段、单一变换策略、JSON Mode＋严格校验＋一次纠错重试，并按 workflow 选择 BM25/Hybrid/Hybrid+Reranker。提交 `d2b52b6` 的真实 Qwen API 与 BGE-M3/reranker 接线冒烟通过；F1 冻结指标属于旧契约，当前契约尚未重新 benchmark。 |
| 最终答案质量基准 | `not_started` | 现有诊断运行不构成正式答案质量验收。 |
| 新的 SFT/GRPO 训练与检查点变更 | `not_started` | 需要明确批准及独立训练数据。 |
| 正式视觉问答基准 | `not_started` | 现有视觉 API 执行证据不构成基准验收。 |

## 允许范围

- 按当前临时实施计划升级查询意图、查询变换和检索前路由，并完成对应的最小验证。
- 修复当前“文件/文档到答案”执行链、证据与引用契约、确定性工具或 CLI
  可用性。
- 仅在变更主张涉及真实依赖时运行定向本地测试和既有服务器冒烟。
- 执行不改变交付契约的仓库与文档维护。

## 未经明确批准不得开展

- 新训练运行、检查点替换、奖励变更，或将验证子集用作训练数据。
- 正式 MP-DocVQA/TAT-QA 答案基准，或以单样本指标为目的的修复。
- UI、云服务、VLM 基准、CDC、Demo 或新阶段。

## 验证边界

M1-A 至 M1-D 的确定性实现属于 `local_only`；M1-E 的 MinerU 语料准备和真实
BGE-M3/重排序器评测属于 `server_required`。凡涉及 MinerU API、BGE-M3、重排序器、
Qwen、VLM、SFT/GRPO 或大型数据集的变更，必须先按
`docs/GPU_SERVER_BOUNDARY.md` 分类；执行服务器操作前必须阅读
`docs/SERVER_SETUP.md`。

## 当前里程碑

M1 Chunk/qrels 只读核查已完成：六文档共有 1,222 个 Chunk、1,016 个可索引
Chunk；150 个原文证据组只有 90 个被当前自动流程映射。60 个未映射组中，诊断发现
相邻多 Chunk 覆盖、页码不一致、OCR/公式/表格序列化差异和原文保留不足等多种原因。
正文 1,200 字符句界切分整体可用，但表格尚无父子 Chunk，且存在相邻表格与表题错配。

当前里程碑为 M1-G1：只实现并验证通用的表格关联、大表父子 Chunk 和对应质量报告；
不重建六文档、不生成最终 qrels、不修改 Prompt、RRF、候选规模或 Reranker。实现与
验收边界以 `docs/workplans/M1_CHUNK_QRELS_ALIGNMENT_PLAN.md` 为准。

## 停止条件

不得自动切换阶段或开始基准/训练工作。完成一项维护请求所需的定向验证与
文档更新（如有）后即停止。

## 文档职责图

| 文档 | 职责 |
|---|---|
| `README.md` / `README_EN.md` | 面向使用者的入口、输出契约和导航。 |
| `AGENTS.md` | 仓库执行、范围、测试和服务器规则。 |
| `docs/ACTIVE_PLAN.md` | 当前里程碑与允许范围。 |
| `docs/workplans/` | 当前大范围实现的临时计划；方案变化先更新计划，验收后不作为长期事实来源。 |
| `CURRENT_STATUS.md` | 精简的已验证能力与证据状态索引。 |
| `DECISIONS.md` | 约束后续工作的长期决策。 |
| `docs/FINAL_DELIVERY_CLI.md` | 实用 CLI 操作指南与限制。 |
| `docs/DATASETS.md` | 数据集角色、划分与下载策略。 |
| `docs/GPU_SERVER_BOUNDARY.md` / `docs/SERVER_SETUP.md` | 资源分类与稳定服务器流程。 |
| `docs/design/phase2/` 与 `docs/DocAgent 技术文档 3.0.pdf` | 历史技术设计参考，绝不可作为当前状态来源。 |
