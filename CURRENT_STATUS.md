# 当前状态

更新日期：2026-08-02

本文档是项目已验证能力的精简索引。`docs/ACTIVE_PLAN.md` 定义下一步允许
开展的工作；已被替代的任务日志与过程报告保留在 Git 历史中。

## 交付摘要

DocAgent 是本地、CLI 优先的个人使用文档问答 MVP。它接收文件或既有文档 ID，
并返回答案、简短推理摘要、所用证据、引用、所用工具和追踪路径。它不是 UI、
云服务，也不是已验收的最终答案质量基准。

| 范围 | 状态 | 已验证边界 |
|---|---|---|
| M1 查询意图与查询变换 | `benchmark_evaluated` | M1-F4 已在 94 条冻结查询上重跑 M1-F2/F3 合同：intent/workflow accuracy 均为 0.7234，retriever mode accuracy 为 0.8298，单变换策略合法率为 1.0000，Router/Transformer 实际 fallback 均为 0。普通正文事实使用 Reranker 后 provisional Recall@5/MRR@10 分别提升 0.0345/0.0854，复杂分析则变化 -0.0625/-0.0012。Gold→Chunk 自动映射未复核，因此未达到 `accepted`。 |
| M1 冻结评测语料准备 | `real_model_verified` | 6 份真实 PDF 已由 MinerU API `vlm` 解析为 1,222 个 `docagent_chunk_v3` Chunk，其中 1,016 个进入真实 BGE-M3 1024 维 FAISS 索引；6/6 索引按 Chunk 哈希重新加载通过，Chunk 契约错误为 0。该状态只证明评测语料与索引就绪，不代表已完成 Recall/MRR 基准。 |
| M1 Chunk 质量与 qrels 对齐 G2 | `accepted` | 基于六文档既有真实 MinerU JSON 隔离重建 1,233 个 Chunk（1,022 个可索引）；30 个物理表中 5 个大表生成 11 个行组检索子块，结构化索引仍使用 30 个物理表。Chunk/表格父子合同错误为 0，表 14/15 元数据与检索文本均正确分离，旧语料哈希未改变。本批未建立稠密索引或 qrels。 |
| M1 Chunk qrels G3/G3.6 | `frozen` | qrels v2 的 150 个证据组已有 15 组项目所有者人工决定和 135 组独立 AI 决定，分布为 95 个接受候选、13 个替换、42 个排除。样本、corpus manifest、PDF、Chunk 内容 hash 与可索引性校验通过；86 条冻结记录中 55 条可评测、31 条排除。尚未运行 M1-G4 检索指标。 |
| M1 无候选组与 Chunk 修复 G3.5 | `accepted` | 六文档重建为 1,239 个 Chunk（1,028 个可索引），新增 3 个算法块、2 个代码块及 1 个恢复正文块，合同错误为 0。检索表示使用 NFKC 而原文不变，IMF Figure 3 图题与正文正确分离并按 bbox 关联。15 组人工结论编码为 13 个替换、2 个排除，并已纳入 G3.6 冻结输入。 |
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
- 服务器 `outputs/sync/m1_frozen_corpus_v1_20260730/`：基于提交
  `a37a148` 对 6 份冻结评测 PDF 执行真实 MinerU API `vlm` 解析、统一 Chunk
  转换和真实 BGE-M3 索引构建。共 119 页、1,222 个 Chunk、1,016 个可索引
  Chunk、30 个结构化表格、114 个图片引用、8 个跨页 Chunk 和 21 个句界拆分
  Chunk；6/6 文档来源哈希、Chunk 契约、索引 Chunk 哈希、嵌入数量与 1024 维
  索引加载检查通过。质量报告保留 origin PDF 二进制差异及部分阅读顺序告警，
  但未触发失败条件。该记录不包含冻结集 Recall/MRR 或 reranker 指标。
- 服务器 `outputs/sync/m1_g2_chunk_rebuild_bca0893_20260802/`：基于提交
  `bca0893` 和既有六文档 MinerU JSON 执行隔离 Chunk 重建。1,222 个旧
  Chunk 重建为 1,233 个，新增 11 个大表行组检索子块；30 个物理表仍全部可供
  `TableRelationalIndex` 读取。Chunk 合同、表格父子合同、表 14/15 元数据与
  `retrieval_text` 检查全部通过，且旧 `data/documents` 哈希未改变。该记录
  不包含 BGE-M3 索引、qrels 或检索指标。
- 服务器 `outputs/sync/m1_g3_chunk_qrels_candidates_v4_20260802/`：基于提交
  `edcc03f` 为 86 条文档查询生成 86 条 v2 candidate、150 条复核队列和 150 条
  decision 模板。候选覆盖 135/150 个证据组；样本与 corpus manifest 哈希绑定、
  新模板字段和精选包大小/SHA256 全部校验通过，真实空白 decision 文件被
  fail-closed 冻结校验拒绝且未产生 frozen qrels。该记录没有调用 GPU/API，
  不包含索引重建或检索指标；v3 产物与 v1 模板已被替代。
- 服务器 `outputs/sync/m1_g35_unmapped15_chunk_repairs_a31f7f3_20260802/`：基于
  提交 `a31f7f3` 隔离重建新六文档 corpus，保存算法/代码块、NFKC 检索表示和
  IMF 图题/正文修复检查；真实 MinerU `is_ocr=true` 对照仍未得到膳食宝塔图内数值。
  v5 candidate 仍保留自动规则的 15 个 unmapped；人工审查单独编码为 13 个
  `replace` 和 2 个 `exclude`，部分冻结被 fail-closed 拒绝。本记录未建立稠密索引或
  运行检索指标，且已替代 v4 作为后续复核输入。
- 服务器 `outputs/sync/m1_g3_frozen_qrels_qwen37_20260802/`：基于提交
  `52c9ccf` 合并 15 组人工决定与 135 组独立 AI 决定，完整覆盖 150 个证据组并
  生成 86 条 qrels v2 冻结记录；55 条可评测、31 条排除。decision/qrels SHA256
  为 `8ea0580cb47c413675361a1aca02d2d843f8a325aaee0fcf7d990c359f3cd815` /
  `c3311ce24c2cb901f5952940ae371d88de652e1c8d6f23e8a520d82169bfe2ce`。该记录未使用
  GPU、未重建索引，也未运行 M1-G4 检索指标。
- 服务器 `outputs/sync/m1_query_retrieval_baseline_20260730/`：基于提交
  `dfb0a2f`，真实 `qwen3.7-max-2026-05-17`、BGE-M3 和
  bge-reranker-v2-m3 完成 94 条查询评测及 688 组原问题/计划查询、四检索器
  对照。原问题 Hybrid 的端到端 Recall@5/MRR@10 为 0.4267/0.5043；
  计划查询 Hybrid 为 0.4267/0.4520，Hybrid+Reranker 为 0.4000/0.5087。
  150 个 Gold evidence group 只有 90 个稳定映射到 Chunk；同步包 7 个文件、
  约 55 KB，大小和 SHA256 全部核验通过且不含密钥、全文、数据库或模型权重。
  该结果为 `benchmark_evaluated`，未建立验收通过主张。
- 服务器 `outputs/sync/m1_query_retrieval_v2_20260731/`：基于提交 `2d880e8`，
  使用真实 `qwen3.7-max-2026-05-17`、BGE-M3 与 bge-reranker-v2-m3 完成
  runner v2。94 条查询无 API 中断；11 条 QueryTransformer 输出因 action 超出
  `allowed_actions` 触发 fallback。通用检索只覆盖 54 条文本 workflow，原问题
  Hybrid 的 provisional Recall@5/MRR@10 为 0.4314/0.5230，计划 Hybrid 为
  0.4314/0.4380，计划 Hybrid+Reranker 为 0.3529/0.5016。全量/通用范围的
  Gold→Chunk 自动映射率为 0.6000/0.5882，均未复核为正式 qrels。同步包约
  52 KB，7/7 文件大小与 SHA256 核验通过且不含敏感或大型内容。该结果属于
  `benchmark_evaluated`，未建立验收通过主张。
- 服务器 `outputs/sync/m1_f2_query_policy_smoke_20260801/`：基于提交
  `d2b52b6` 完成 244 项服务器回归、8 条独立中英文真实
  `qwen3.7-max-2026-05-17` 查询决策/变换冒烟及三种真实检索策略接线。
  Qwen 输出合法率和通用预期匹配率均为 1.0，未发生纠错重试或 fallback；
  navigation 未加载 Dense/Reranker，简单事实只加载 BGE-M3，复杂分析加载
  BGE-M3 与 bge-reranker-v2-m3。同步包 6 个文件、约 7.4 KB，大小和 SHA256
  全部核验通过。该记录为 `real_model_verified`，没有重跑或调优冻结基准。
- 服务器 `outputs/sync/m1_f3_fact_reranker_smoke_20260801/`：基于提交
  `6813cd8`，一条普通正文事实查询的 planned/effective mode 均为
  `hybrid_rerank`，实际使用 BGE-M3 和 `bge-reranker-v2-m3` Cross-Encoder。
  返回 3 个候选且 3/3 具有重排分数，复用既有稠密索引。该记录为
  `real_model_verified`，不是正式检索质量基准。
- 服务器 `outputs/sync/m1_f2_f3_workflow_eval_20260801/`：原始 API/GPU
  评测基于 `adc0e22`，最终报告基于 `e03e8b3`；94 条 query prediction、
  94 条 Gold mapping 和 432 条真实检索 detail 完整。policy-selected
  provisional Recall@5/MRR@10 为 0.4118/0.5382；普通事实查询的重排收益
  为 +0.0345/+0.0854，复杂分析为 -0.0625/-0.0012。完整/精选 manifest
  哈希均通过，精选包约 71 KB。该记录为 `benchmark_evaluated`，指标仍受
  0.5882 的未复核 Gold→Chunk 映射率限制。

## 不构成以下主张

不得从上述已验证执行路径推断出：

- 已验收的 MP-DocVQA/TAT-QA 最终答案基准；
- 最终 Qwen 答案质量验收；
- 正式视觉问答基准验收；
- 可以启动新的 SFT/GRPO 训练、替换检查点，或将验证行作为训练输入。

## 文档职责

请使用 `docs/ACTIVE_PLAN.md` 中的文档职责图。尤其是，本文档是唯一的当前
能力/状态索引，刻意不重复任务计划、命令教程或历史实验叙述。
