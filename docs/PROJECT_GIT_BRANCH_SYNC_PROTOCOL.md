# DocAgent 项目 Git 分支与同步强制协议

## 0. 文档信息

- 项目：DocAgent 复杂文档问答系统
- 文档类型：项目级工程协作协议
- 适用对象：PM、Codex、后续任何执行代理
- 语言：中文
- 状态：立即生效
- 生效范围：所有代码实现、测试补充、评估 runner、配置变更、文档更新、验收打包、修复任务

---

## 1. PM 决策

从本协议生效开始，DocAgent 的每一个阶段、子阶段或独立任务都必须遵守以下规则：

1. **每个阶段实施时必须新建独立 Git 分支。**
2. **任何实现、改动或文档更新不得直接在 `main` / `master` / 稳定集成分支上完成。**
3. **每次任务执行都必须自动执行 Git 检查、分支创建或确认、变更检查、提交和同步相关命令。**
4. **任务完成后必须提交 commit；如存在远程仓库且网络可用，应同步到远程同名分支。**
5. **后续收束阶段再由 PM 明确发起合并，不允许 Codex 在普通任务中自动 merge 到主干。**
6. **任何 Git 阻塞、冲突、未跟踪敏感文件、测试失败、push 失败，都必须在返回报告中列出。**

---

## 2. 分支命名规范

### 2.1 功能 / 阶段分支

```bash
phase5/<phase-id>-<short-scope>
```

示例：

```bash
phase5/phase5i-b-model-answer-quality
phase5/phase5e-document-summary
phase5/phase5e-a-summary-acceptance
```

### 2.2 评估 / benchmark 分支

```bash
eval/<phase-id>-<short-scope>
```

示例：

```bash
eval/phase5i-b-answer-quality-baseline
```

### 2.3 文档分支

```bash
docs/<short-scope>
```

示例：

```bash
docs/git-branch-sync-protocol
```

### 2.4 修复分支

```bash
fix/<short-scope>
```

示例：

```bash
fix/router-summary-intent
fix/phase5i-b-citation-validation
```

---

## 3. 每次任务必须包含的 Git 执行流程

以下流程必须嵌入到每一份后续 Codex 任务文档中。Codex 返回报告也必须逐项反馈执行结果。

### 3.1 Git preflight

任务开始前必须执行：

```bash
git rev-parse --is-inside-work-tree
git remote -v
git branch --show-current
git status --branch --short
git log --oneline -5
```

如有远程仓库，继续执行：

```bash
git fetch --all --prune
git status --branch --short
```

#### 3.1.1 preflight 阻塞条件

出现以下情况时，不得继续修改代码，必须停止并返回 `preflight_blocked`：

- 当前目录不是 Git 仓库；
- 起始工作区存在未知来源的未提交变更；
- 存在未解决冲突；
- 当前分支不是预期主干、阶段分支或任务分支，且无法判断是否应继续；
- `.secrets/`、API key、模型权重、数据库、压缩包、大型数据文件出现在待提交列表中；
- `git fetch` 后发现本地分支明显落后且无法 fast-forward。

允许继续的例外：

- 任务文档明确说明“继续当前未完成分支”；
- 未提交变更全部由本轮任务在同一会话中产生；
- 仅存在忽略文件或不影响提交的本地产物。

---

## 4. 分支创建 / 确认流程

### 4.1 新任务默认从主干创建分支

Codex 应先识别默认主干：

```bash
git symbolic-ref refs/remotes/origin/HEAD || true
git branch --list main master
```

优先级：

1. `origin/main`；
2. `main`；
3. `origin/master`；
4. `master`；
5. 任务文档指定的集成分支。

从主干创建任务分支：

```bash
git switch main
# 或：git switch master

git pull --ff-only

git switch -c <task-branch>
```

### 4.2 如果分支已存在

```bash
git switch <task-branch>
git status --branch --short
git pull --ff-only || git pull --rebase
```

如出现冲突，必须停止并返回 `sync_blocked`，不得自动乱解冲突。

---

## 5. 实现后必须执行的 Git 检查

代码、测试或文档改动完成后，必须执行：

```bash
git status --branch --short
git diff --stat
git diff --check
```

如涉及代码，必须按任务文档执行 pytest / smoke / py_compile。示例：

```bash
python -m py_compile <changed_python_file>.py
python -m pytest <targeted_tests> -q
```

对于 Phase 5 相关改动，建议至少执行：

```bash
python -m pytest tests/test_phase5*.py -q
```

如测试过重，应执行任务文档指定的 targeted tests，并在返回报告中说明未跑全量测试的原因。

---

## 6. 提交规范

### 6.1 提交前必须检查敏感与大文件

```bash
git status --short
git diff --name-only --cached
```

禁止提交：

- `.secrets/`；
- `.env`、API key、token；
- 模型权重；
- 大型原始数据；
- SQLite 数据库；
- `outputs/` 下的大量本地产物，除非任务文档明确要求提交小型验收报告；
- `__pycache__`、`.pytest_cache`、临时日志。

### 6.2 commit message 规范

```bash
git add <explicit_files>
git commit -m "<type>(<scope>): <summary>"
```

推荐类型：

| type | 用途 |
|---|---|
| `feat` | 新功能 |
| `fix` | bug 修复 |
| `test` | 测试补充 |
| `eval` | 评估 runner / benchmark |
| `docs` | 文档更新 |
| `refactor` | 重构 |
| `chore` | 工程维护 |

示例：

```bash
git commit -m "eval(phase5i-b): add model-backed answer quality baseline"
git commit -m "docs(pm): add git branch sync protocol"
```

---

## 7. 同步远程分支

提交完成后，必须执行：

```bash
git status --branch --short
git log --oneline -3
```

如存在远程仓库且网络可用：

```bash
git push -u origin <task-branch>
```

如果远程分支已存在：

```bash
git pull --rebase origin <task-branch>
git push origin <task-branch>
```

如 push 失败，不得强推；必须返回：

```text
sync_status: push_failed
原因：...
本地 commit: <hash>
当前分支: <branch>
```

禁止默认执行：

```bash
git push --force
git push --force-with-lease
git reset --hard
git clean -fd
git rebase --skip
```

除非 PM 在单独任务中明确授权。

---

## 8. 合并收束协议

普通任务不得自动合并到主干。只有当 PM 明确提出“收束 / merge / 合并 / accept 到主干”时，才能执行合并任务。

合并任务必须单独生成 Markdown 任务文档，至少包含：

- 待合并分支；
- 合并目标分支；
- 验收证据；
- 回归测试范围；
- 冲突处理策略；
- 是否打 tag；
- 是否 push 主干。

推荐合并流程：

```bash
git switch main
# 或目标集成分支

git pull --ff-only
git merge --no-ff <task-branch> -m "merge: accept <phase/task>"
python -m pytest <acceptance_tests> -q
git status --branch --short
git push origin main
```

可选 tag：

```bash
git tag <phase-id>-accepted-YYYYMMDD
git push origin <phase-id>-accepted-YYYYMMDD
```

---

## 9. Codex 返回报告必须包含 Git 区块

每次 Codex 回复必须包含以下区块：

```markdown
## Git 执行报告

| 项目 | 结果 |
|---|---|
| 起始分支 | `<branch>` |
| 新建/使用分支 | `<branch>` |
| 远程仓库 | `<origin url or none>` |
| preflight status | `passed / preflight_blocked` |
| 起始工作区是否干净 | `yes / no` |
| fetch/pull 结果 | `passed / skipped / failed` |
| 提交 hash | `<hash or none>` |
| commit message | `<message or none>` |
| push 结果 | `pushed / skipped / failed` |
| 最终工作区是否干净 | `yes / no` |
| 是否合并主干 | `no` |
```

如有阻塞，必须补充：

```markdown
### Git 阻塞说明

- 阻塞阶段：`preflight / branch_create / sync / commit / push`
- 具体命令：`...`
- stderr / 摘要：`...`
- 当前分支：`...`
- 当前状态：`git status --branch --short` 输出
- 建议 PM 决策：`...`
```

---

## 10. 后续任务文档模板中必须加入的固定章节

后续所有任务文档必须包含以下章节：

```markdown
## Git 分支与同步要求

- 本任务必须在独立分支 `<branch-name>` 上完成。
- 不允许直接在 `main` / `master` 上修改。
- 开始前必须执行 Git preflight。
- 若工作区存在未知未提交变更，必须停止并返回 `preflight_blocked`。
- 完成后必须执行 targeted tests、`git diff --check`、`git status --branch --short`。
- 完成后必须提交 commit。
- 如存在远程仓库且网络可用，必须 push 到远程同名分支。
- 不允许自动 merge 主干；合并必须等 PM 单独下达收束任务。
```

---

## 11. 状态词汇

| 状态 | 含义 |
|---|---|
| `branch_created` | 已创建任务分支，尚未实现 |
| `implemented_uncommitted` | 已实现但未提交，不可接受 |
| `implemented_committed` | 已实现且有本地 commit |
| `implemented_pushed` | 已实现、提交并 push 到远程任务分支 |
| `acceptance_candidate` | 有测试和验收产物，但未合并 |
| `accepted_unmerged` | PM 接受，但尚未合并主干 |
| `accepted_merged` | 已合并到主干或稳定集成分支 |
| `preflight_blocked` | Git 起始状态阻塞 |
| `sync_blocked` | pull / rebase / push 阻塞 |

---

## 12. 当前 PM 约束

后续 PM 输出任务文档时，不再只写“实现”和“测试”，而必须写清：

1. 分支名；
2. Git preflight；
3. 分支创建或确认；
4. 测试命令；
5. commit message；
6. push 要求；
7. 禁止 merge 主干；
8. 返回报告中的 Git 执行报告。
