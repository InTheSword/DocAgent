# 当前状态

更新日期：2026-08-05

> 本文档是项目当前已验证能力的精简索引。它不安排下一步任务，不保存完整实验日志，
> 也不把实现计划当作已经完成。当前范围见 `docs/ACTIVE_PLAN.md`，长期决策见
> `DECISIONS.md`。

## 交付摘要

DocAgent 是本地、CLI 优先的个人复杂文档问答 MVP。系统支持导入原始 PDF 或读取既有
文档，经规范 Chunk、查询决策、检索和 AnswerPolicy 返回答案、证据、引用与追踪产物。
它不是已交付的 UI/云服务，也尚未完成最终答案质量验收。

## 当前能力

| 能力 | 状态 | 已验证边界 |
|---|---|---|
| Phase 5 CLI、文件导入与输出契约 | `accepted` | 文件和 `doc_id` 路径均提供稳定的 answer、reasoning summary、证据、引用和 trace 契约；原始 PDF MinerU API 路径已有真实执行证据。 |
| MinerU → Chunk 规范处理 | `accepted` | `Chunk` 是唯一检索领域对象；支持来源保留、标题层级、保守跨页合并、长正文句界拆分、NFKC 检索表示、表格父子 Chunk 及图题关系。六文档最终 corpus 为 1,239 个 Chunk，其中 1,028 个可索引，合同错误为 0。 |
| Chunk qrels v2 | `frozen` | 150 个证据组完成复核，形成 86 条冻结记录；55 条 eligible、31 条 excluded。qrels 绑定样本、PDF、corpus、Chunk 内容和复核决策哈希。 |
| 查询意图、路由与查询变换 | `benchmark_evaluated` | 使用 `qwen3.7-max-2026-06-08` 在 94 条冻结查询上评测：intent/workflow/retriever-mode accuracy 为 0.7021/0.7234/0.8404，变换动作 exact match 为 0.5213；Router 无 fallback，Transformer 1 次 fallback。 |
| Reviewed-qrels 检索 | `benchmark_evaluated` | 54 条可检索样本完成 432 条对照。Policy-selected Group Recall@5/All-groups@5/MRR@10 为 0.5125/0.5741/0.7799；planned Hybrid+Reranker 为 0.5750/0.5741/0.7780。查询变换未产生总体 Recall 正收益；Reranker 提升 MRR 但降低 Hit@5 并增加延迟。 |
| 真实模型问答执行链 | `real_model_verified` | 外部查询 LLM、BGE-M3、bge-reranker-v2-m3、Qwen AnswerPolicy、引用和持久化 trace 已完成服务器冒烟；该状态只证明真实链路可执行，不等于答案正确率验收。 |
| 文档摘要、页读取、表格查找与简单计算 | `implemented` | 确定性实现已有本地定向和回归覆盖；结构化表格精确查询与文本检索是两条不同路径。 |
| 视觉 API 执行链 | `real_model_verified` | 已验证按需 API 调用和产物契约；当前 MinerU 结果不能保证图片内部 OCR/VLM 内容，正式视觉问答基准仍为 `not_started`。 |
| 最终答案质量基准 | `not_started` | 现有全路径冒烟和检索指标不能代替答案正确性、忠实度与引用支持度验收。 |
| 新的 SFT/GRPO 训练 | `not_started` | 当前运行检查点不构成新训练成果；训练目标、独立数据和验收合同尚未建立。 |

## 当前运行边界

- `user_best` 是正常 CLI 配置，需要真实服务、模型与已配置的 AnswerPolicy 产物。
- `self_test` 只用于本地或 CI，不得作为真实模型能力证据。
- 查询变换只影响检索查询；AnswerPolicy 始终接收原始问题。
- Metadata 是稀疏/稠密检索的前置约束，不是 RRF 的第三路分数。
- `EvidenceBlock` 只作为历史代码、SQLite/JSONL 名称的兼容别名；新文档和新实现使用
  `Chunk`。
- 验证集和冻结检索集不得转为训练数据，也不得用于反复调参。

## 规范证据入口

以下是当前状态所依赖的最小证据入口；更早运行保留在历史 workplan、报告、服务器产物
或 Git 历史中，不在本文逐项复制。

| 证据 | 证明范围 |
|---|---|
| `outputs/sync/m1_g35_unmapped15_chunk_repairs_a31f7f3_20260802/` | 六文档最终 Chunk 修复、合同和视觉 OCR 缺口。 |
| `outputs/sync/m1_g3_frozen_qrels_qwen37_20260802/` | reviewed qrels v2 冻结、输入绑定和哈希。 |
| `outputs/sync/m1_g4_reviewed_retrieval_20260802/` | 94 条查询决策、54 条检索样本、432 条检索明细和正式指标。 |
| `final_delivery_user_best_profile_closeout_20260706` 运行记录 | 原始 PDF 到答案的真实组件执行链。 |

上述路径是服务器工作树内的运行产物位置，不要求完整同步到本地，也不应提交大型产物、
数据库、模型权重、密钥或完整日志。

## 不构成的主张

当前状态不表示：

- 最终 Qwen 答案质量已经验收；
- 表格检索命中等于结构化统计答案正确；
- 图题或视觉文本 Chunk 命中等于具备图内 VLM 理解；
- 可以启动新 SFT/GRPO、替换检查点或使用验证样本训练；
- 项目已经成为 UI、云服务或生产级多用户系统。

## 相关文档

- 当前允许范围：`docs/ACTIVE_PLAN.md`
- 长期架构决策：`DECISIONS.md`
- workplan 目录与读取条件：`docs/workplans/README.md`
- CLI 使用方法：`docs/FINAL_DELIVERY_CLI.md`
- 数据集角色：`docs/DATASETS.md`
