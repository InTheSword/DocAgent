# 当前计划

> 当前里程碑、范围边界和停止条件的唯一来源。历史任务记录保留在 Git
> 历史中，不作为当前规划输入。

## 当前阶段

```text
Phase 5 个人使用 DocAgent MVP
```

## 当前实施依据

本阶段将升级检索前查询链。实现、范围变更和验收以以下临时计划为准：

```text
docs/workplans/M1_QUERY_INTENT_ROUTING_REWRITE_PLAN.md
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
| 新查询意图、路由与查询变换链 | `benchmark_evaluated` | M1-F1 已拆分动作/约束指标、限定通用检索 workflow、增加实际执行路由并修复多查询重排目标，112 项相关本地回归通过；runner v2 尚未完成六文档真实重跑。既有 v1 六文档基线仅用于失败定位，Gold→Chunk 自动映射率为 0.6000，尚未验收。 |
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

## 下一步

执行临时计划 1.7 的 M1-F1：先修复查询动作/约束评测合同、规划路由与实际执行
路径混淆、通用检索指标混入非文本 workflow，以及多查询重排只使用第一条子查询的
接线错误。自动 Gold→Chunk 结果只作为 qrel candidate，不作为已复核正式 qrels。
本批本地验证后停止；六文档真实 Qwen/BGE-M3/reranker 重跑需在 GPU 服务器进行。
不得根据冻结样本增加个案 prompt、映射或路由规则，也不启动最终答案质量评测或训练。

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
