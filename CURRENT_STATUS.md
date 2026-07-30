# 当前状态

更新日期：2026-07-30

本文档是项目已验证能力的精简索引。`docs/ACTIVE_PLAN.md` 定义下一步允许
开展的工作；已被替代的任务日志与过程报告保留在 Git 历史中。

## 交付摘要

DocAgent 是本地、CLI 优先的个人使用文档问答 MVP。它接收文件或既有文档 ID，
并返回答案、简短推理摘要、所用证据、引用、所用工具和追踪路径。它不是 UI、
云服务，也不是已验收的最终答案质量基准。

| 范围 | 状态 | 已验证边界 |
|---|---|---|
| M1 查询意图与查询变换 | `real_model_verified` | RAG 问答主链已迁移为两阶段 `QueryDecision -> QueryPlan`；真实 `qwen3.7-max-2026-05-17` 冒烟完成意图识别和 3 路静态拆解。显式统计、整页读取和全量结构导出仍走确定性操作；新的真实 BGE-M3 联合评测尚未执行。 |
| Phase 5 CLI、导入与输出契约 | `accepted` | 文件和 `doc_id` 路径提供稳定的答案/证据/引用/追踪契约。 |
| 原始 PDF MinerU API 路径 | `accepted` | 实时 API 冒烟建立了导入和引用契约。 |
| 混合检索与模型回答工作流 | `real_model_verified` | 真实 BGE-M3、交叉编码器重排序器、Qwen AnswerPolicy、LLM 查询规划与持久化检索追踪均有服务器冒烟证据。 |
| `user_best` 恢复与进度路径 | `real_model_verified` | 已验证有界证据恢复与仅 stderr 进度反馈，JSON stdout 未改变。 |
| 文档摘要、表格查找与简单计算 | `implemented` | 确定性本地实现，已有定向/回归覆盖。 |
| MinerU Chunk 与索引契约 | `real_model_verified` | `Chunk` 是规范检索领域对象，`EvidenceBlock` 仅为兼容别名；12 页真实 VideoTree MinerU 产物在本地与服务器均重建为 184 个 v3 Chunk（171 个可索引、3 个跨页合并、12 个句界拆分），契约错误为 0，并已使用真实 BGE-M3 建立索引。 |
| 多路检索与结构化约束 | `real_model_verified` | 真实 BGE-M3 与 bge-reranker-v2-m3 直接检索验证关闭了意图路由、查询规划和查询重写：普通查询 Hit@5 为 18/18，表格文本 Hit@5 为 6/6，4 个结构化表格查询精确匹配。Metadata 仅作前置过滤，未进入 RRF。该小型回归集不构成正式检索基准。 |
| 原问题与检索查询分离 | `implemented` | 新查询链自动测试证明原问题与最多 4 条检索查询相互独立；查询重写仅用于检索，Qwen 输入超限时优先裁减证据。新的 AnswerPolicy 联合冒烟尚未执行。 |
| 视觉 API 工作流 | `real_model_verified` | 已验证 API 执行；正式视觉问答评测尚未验收。 |
| 最终答案质量基准 | `not_started` | 诊断产物和全路径冒烟不等于正确性验收。 |
| 新的 SFT/GRPO 训练 | `not_started` | 当前检查点证据仅供运行；新训练需要明确批准。 |

## 当前运行默认值

- `user_best` 是正常 CLI 配置，要求已配置真实服务和模型产物。
- `self_test` 是轻量本地/CI 配置，不能作为真实模型能力证据。
- 配置服务器上，402 条记录的 rejection-SFT 检查点是 `user_best` 的运行
  AnswerPolicy 默认值，但不被提升为已正式验收的答案质量结果。
- 验证子集仅用于诊断，不得用作训练数据。

## 证据边界

以下服务器记录建立的是执行链证据，而不是正式基准主张：

- `final_delivery_user_best_profile_closeout_20260706`：从原始 PDF 到答案，
  包含 MinerU API、路由/规划 API、混合重排序、Qwen SFT、引用和追踪产物。
- `evidence_recovery_progress_user_best_smoke_final_20260708`：在真实
  `user_best` 组件下验证有界恢复与 stderr 进度。
- `final_full_workflow_hybrid_rerank_smoke_rowalign_20260630`：真实检索器、
  规划器、Qwen 工作流及持久化 `retrieve_evidence` 追踪。
- `final_raw_pdf_full_workflow_api_hybrid_qwen_fresh_20260630_172350`：全新的
  原始 PDF 全模型工作流。
- `outputs/sync/mineru_vlm_chart_probe_20260727/`：真实 MinerU API 结构与
  Chunk 冒烟；请求 `vlm`，产物报告 MinerU 3.4.0 `hybrid/medium`，181 个
  identity Chunk、168 个可索引 Chunk，来源可追溯率为 1.0。基于同一真实
  产物的 `docagent_chunk_v2` 本地转换复核得到 0 个契约错误、5/5 个表格具有
  结构化行列、4/4 个视觉块具有关系元数据，4/4 严格元数据查询集合匹配；
  该记录不验证当前 `docagent_chunk_v3` 跨页合并、句界拆分和表格关系检索；
  未运行新的真实 BGE-M3/重排序器评测。
- `outputs/sync/videotree_chunk_v3_direct_hash_20260729/`：基于上述真实 MinerU
  产物重建 v3 Chunk，并在禁用意图路由、查询规划和查询重写后验证直接检索。
  184 个 Chunk 的契约错误为 0；5/5 表格具有可查询表头/行数据，表格文本
  Hit@5 为 1.0，4 个关系查询精确匹配率为 1.0。普通 Hash Hybrid Hit@5
  为 0.7222，仅属于 `mock_verified`。
- 服务器
  `outputs/sync/videotree_chunk_v3_direct_bge_reranker_layout_20260729/`：
  基于提交 `1f2a00e`、完整 content list 与 `layout.json` 重建出与本地一致的
  184 个 Chunk，并使用真实 BGE-M3 与 bge-reranker-v2-m3 运行 28 条直接检索
  回归。普通查询 Hit@5 为 1.0、MRR@5 为 0.8889；表格文本 Hit@5 与 MRR@5
  均为 1.0；4 个结构化查询精确匹配率为 1.0，路由契约检查通过。该结果属于
  `real_model_verified`，不是正式检索质量基准。
- `outputs/sync/m1_qwen_api_smoke_20260730_032733/`：真实
  `qwen3.7-max-2026-05-17` 分别以 `intent_router` 和
  `query_transformer` 角色执行；识别 `complex_analysis`，生成 3 条静态
  拆解查询，两个阶段均通过 Schema 校验。该记录不包含 BGE-M3 联合检索评测。

## 不构成以下主张

不得从上述已验证执行路径推断出：

- 已验收的 MP-DocVQA/TAT-QA 最终答案基准；
- 最终 Qwen 答案质量验收；
- 正式视觉问答基准验收；
- 可以启动新的 SFT/GRPO 训练、替换检查点，或将验证行作为训练输入。

## 文档职责

请使用 `docs/ACTIVE_PLAN.md` 中的文档职责图。尤其是，本文档是唯一的当前
能力/状态索引，刻意不重复任务计划、命令教程或历史实验叙述。
