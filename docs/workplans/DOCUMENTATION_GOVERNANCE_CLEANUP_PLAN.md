# 项目 Markdown 文档治理修订计划

> 文件性质：已完成阶段的临时实施记录
> 计划版本：1.1
> 状态：`accepted`
> 建立日期：2026-08-05
> 适用范围：项目 Markdown 的职责、状态、导航与冗余清理，不修改产品代码和运行产物

## 1. 当前缺口

1. `docs/ACTIVE_PLAN.md` 同时声明没有活动计划和按当前临时计划执行，并混入大量已完成里程碑日志。
2. `CURRENT_STATUS.md` 重复保存历史服务器运行流水账，弱化了“当前能力索引”的职责。
3. `DECISIONS.md` 的文档策略与工作树中实际保留的历史方案不一致。
4. `docs/workplans/` 没有目录索引；读者只能从历史对话或文件名猜测何时参考某份方案。
5. README 导航存在重复链接和“历史计划已从工作树清除”的错误描述。

## 2. 已确定方案

- 建立唯一导航链：`AGENTS.md → docs/ACTIVE_PLAN.md → docs/workplans/README.md → 指定活动方案`。
- `ACTIVE_PLAN.md` 只保存当前阶段、活动实施依据、允许范围、资源边界和停止条件。
- `CURRENT_STATUS.md` 只保存当前能力状态、最新正式指标、边界和少量规范证据入口。
- `DECISIONS.md` 只保存会约束后续实现的长期决策，不记录任务进度和实验流水账。
- `docs/workplans/README.md` 负责方案目录、状态和选用规则。已完成方案只在追溯设计理由、审计对应阶段或用户明确指定时读取。
- 历史报告和详细方案保留，不因本次清理重写其技术正文。

## 3. 文件范围

主要修改：

- `AGENTS.md`
- `docs/ACTIVE_PLAN.md`
- `CURRENT_STATUS.md`
- `DECISIONS.md`
- `docs/workplans/README.md`
- `README.md` / `README_EN.md`

仅在存在错误状态或导航时修改：

- `docs/workplans/*.md`
- `docs/reports/*.md`
- 其他 Markdown 的交叉引用

范围外：产品代码、测试代码、模型配置、数据、服务器产物、历史 Git 提交和旧方案技术内容重写。

## 4. 验收

1. `ACTIVE_PLAN.md` 只有一个明确的活动实施依据；完成后变为“无活动计划”。
2. `docs/workplans/README.md` 列出全部方案及其状态、范围和读取条件。
3. 三份核心文档不再重复大段里程碑或服务器日志，状态与 M1-G4 结果一致。
4. README 不再包含重复导航或错误的历史文档声明。
5. 项目内 Markdown 相对链接检查通过，关键职责描述不存在互相冲突。

## 5. 资源边界与停止条件

本任务为 `local_only`，不需要 API、GPU 或服务器验证。完成文档检查和状态更新后停止，
不进入新的 RAG 优化、答案评测或训练阶段。

## 6. 变更记录

| 日期 | 版本 | 变更 | 原因 |
|---|---|---|---|
| 2026-08-05 | 1.0 | 建立文档治理修订合同 | 核心文档职责重叠且 workplans 缺少可发现的选用规则 |
| 2026-08-05 | 1.1 | 完成核心文档收敛、workplan 索引和全仓 Markdown 一致性检查 | 17 份项目 Markdown 链接与关键职责检查通过，3 份 workplan 全部登记 |
