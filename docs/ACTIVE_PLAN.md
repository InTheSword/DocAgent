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

M1 Chunk/qrels 修复前只读核查已完成：六文档共有 1,222 个 Chunk、1,016 个可索引
Chunk；150 个原文证据组只有 90 个被当前自动流程映射。60 个未映射组中，诊断发现
相邻多 Chunk 覆盖、页码不一致、OCR/公式/表格序列化差异和原文保留不足等多种原因。
正文 1,200 字符句界切分整体可用，但表格尚无父子 Chunk，且存在相邻表格与表题错配。

M1-G2 已达到 `accepted`：提交 `bca0893` 修复了 MinerU 多项组合表题中
换行/空格归一化差异导致的检索文本污染；服务器相关回归 90 项通过。六文档使用既有
MinerU JSON 在隔离目录重建为 1,233 个 Chunk（1,022 个可索引），30 个物理表生成
5 个结构化父块和 11 个行组检索子块；Chunk 合同和表格父子合同错误均为 0，
表 14/表 15 的元数据与实际检索文本均已分离。旧 `data/documents` 的 Chunk 文件哈希
未改变；本批未调用 MinerU API、未重建稠密索引、未生成 qrels。验收产物位于服务器：

```text
outputs/sync/m1_g2_chunk_rebuild_bca0893_20260802/
```

M1-G3 qrels v2 candidate 已达到 `ready`：提交 `edcc03f` 使用完整
`acceptable_chunk_sets` 表达多 Chunk 与等价证据集合，并对可索引性、唯一性、复核
来源、样本/corpus manifest/decision 哈希和 schema 版本执行 fail-closed 校验。基于
M1-G2 corpus 重新生成 86 条 candidate、150 条复核队列和 150 条 decision 模板；
135 个证据组有候选，15 个无候选。服务器同范围 21 项回归通过，真实空白 v2 模板被
拒绝且未生成 `frozen_chunk_qrels.jsonl`。最终服务器精选产物：

```text
outputs/sync/m1_g3_chunk_qrels_candidates_v4_20260802/
```

M1-G3.5 已达到 `accepted`：提交 `a31f7f3` 在真实六文档上完成算法/代码块保留、
检索 NFKC、图题/正文分离和 bbox 图题关联；重建 corpus 含 1,239 个 Chunk、1,028 个
可索引 Chunk，合同错误为 0。真实 MinerU `is_ocr=true` 对照仍未提取膳食宝塔图片内
数值，因此未伪造视觉文本。基于新 corpus 的 v5 candidate 已生成，15 个原无候选组
编码为 13 个 `replace` 和 2 个 `exclude`；冻结器确认该部分 decision 不能生成正式
qrels。旧 v4 candidate/template 已失效。

当前执行 M1-G3.6：使用已配置 Qwen API 独立复核其余 135 个证据组，与 15 组人工
decision 合并；只有 150/150 组通过 qrels v2 绑定、内容哈希和可索引性校验后才生成
frozen qrels。该批不需要 GPU，不重建 BGE-M3/FAISS 索引，也不运行 M1-G4 检索评测。
真实 API 首轮出现 HTTP 429/读取超时；按阶段计划先加入可恢复 partial 和瞬时错误
有界重试，再以较低并发续跑，判定标准与冻结合同不变。

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
