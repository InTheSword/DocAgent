# 当前计划

更新日期：2026-08-05

> 本文档是“现在可以做什么”的唯一来源，只记录当前阶段、活动实施依据、范围、
> 资源边界和停止条件。已验证能力见 `CURRENT_STATUS.md`，长期架构决策见
> `DECISIONS.md`。

## 当前阶段

```text
Phase 5 个人使用 DocAgent MVP
```

当前没有执行中的产品实现里程碑。M1 Chunk/qrels、查询决策与正式检索测评已经结束，
Markdown 文档治理修订也已完成；后续产品优化方向尚未选定。

## 当前实施依据

当前没有活动 workplan。不得把 `docs/workplans/` 中任意已完成方案自动当作当前任务。

开始新的跨模块实现、公共契约变更、正式评测或训练前，必须：

1. 由用户明确选择目标；
2. 查看 `docs/workplans/README.md`，确认是延续历史问题还是新阶段；
3. 在 `docs/workplans/` 新建临时方案，并在本节写出唯一的精确路径；
4. 先冻结范围、接口、验收、资源边界和停止条件，再修改代码。

若本节没有列出具体文件，则旧 workplan 只可用于历史追溯，不能授权实施。

## 维护中的交付路径

```text
文件或既有文档
-> MinerU 解析与规范 Chunk 持久化
-> 查询决策与按需查询变换
-> Metadata 前置约束与路由化检索
-> AnswerPolicy
-> answer + reasoning_summary + evidence_used + citations + trace_path
```

产品边界仍是本地、CLI 优先的个人文档问答 MVP。当前目标是维护这条已经建立的交付
路径，不在没有新计划时静默扩展产品范围。

## 当前允许范围

- 用户明确要求的只读检查、解释和状态核对；
- 不改变公共契约的局部缺陷修复及最小充分验证；
- 当前执行链、证据、引用、CLI 或确定性工具的维护；
- 仓库、文档和不改变产品行为的工程维护。

出现跨模块修改、执行链变化、公共 Schema 变化、正式模型质量主张或需要反复调参时，
必须停止并先建立新的 workplan。

## 未经新计划不得开展

- 在 M1-G4 冻结查询集上继续调参或重复追逐指标；
- 新的答案质量基准、视觉问答基准或大型数据集评测；
- SFT/GRPO 数据重建、训练、奖励修改或检查点替换；
- UI、云服务、多用户系统、CDC、Demo 或新产品阶段；
- 自动恢复任何已经完成的历史 workplan。

## 资源与验证边界

- Markdown、确定性逻辑、CLI 胶水、SQLite/JSON 契约通常为 `local_only`。
- 真实 BGE-M3、重排序器、Qwen、VLM、在线 MinerU、训练或正式模型评测为
  `server_required` 或需要真实 API 验证。
- 具体判定以 `docs/GPU_SERVER_BOUNDARY.md` 为准；服务器执行前读取
  `docs/SERVER_SETUP.md`。

## 停止条件

没有活动 workplan 时，完成用户明确要求的维护或分析后即停止。不得自动选择下一阶段，
也不得从历史报告、审查文档或旧 workplan 推导新的实施授权。

## 文档导航

| 文档 | 唯一职责 |
|---|---|
| `AGENTS.md` | 仓库执行、范围、测试和服务器规则。 |
| `docs/ACTIVE_PLAN.md` | 当前阶段、活动实施依据、允许范围和停止条件。 |
| `docs/workplans/README.md` | workplan 目录、状态和读取条件。 |
| `CURRENT_STATUS.md` | 当前已验证能力、指标、边界和规范证据入口。 |
| `DECISIONS.md` | 约束后续实现的长期产品与技术决策。 |
| `docs/FINAL_DELIVERY_CLI.md` | 当前 CLI 使用方式和输出契约。 |
| `docs/DATASETS.md` | 数据集角色、划分和使用限制。 |
| `docs/GPU_SERVER_BOUNDARY.md` / `docs/SERVER_SETUP.md` | 资源分类和稳定服务器流程。 |
| `docs/reports/` | 特定运行的分析报告，不定义当前状态或实施授权。 |
| `docs/design/` | 历史设计参考，不定义当前状态或实施授权。 |
