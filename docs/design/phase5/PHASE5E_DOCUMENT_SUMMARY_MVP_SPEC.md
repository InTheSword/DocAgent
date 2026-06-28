# DocAgent Phase 5E Product Spec: Document Summary MVP

> 用途：交给 Codex 作为本次实现任务说明。  
> 角色定位：你是接手 DocAgent Phase 5 MVP 的实现工程师。请基于现有代码实现 `document_summary` 工具闭环。  
> 当前目标：把“Router 已能识别但 CLI 仍返回 unsupported 的 document_summary 请求”推进为“可执行、可追溯、可测试的 MVP 工具”。

---

## 1. 背景与问题

DocAgent 当前是一个个人使用 / 求职展示型复杂文档 QA MVP，不是商业级成品，也不是最终答案质量 benchmark 系统。

现有系统已经具备以下主链路：

```text
document registration / ingestion
-> MinerU or text parser output to EvidenceBlock
-> SQLite persistence
-> deterministic Router
-> optional LLM router fallback
-> optional query planning / multi-query retrieval
-> deterministic document tools or local_fact_qa
-> citations, JSON output, CLI artifacts, and traces
```

当前关键产品缺口：

```text
Router taxonomy 中已经包含 document_summary，
但 summary tool 尚未实现，CLI 对 summary 类请求仍可能返回 unsupported 或 fallback warning。
```

本次任务只补齐 **Phase 5E Document Summary MVP**。

---

## 2. 本次任务结论

请实现一个 **deterministic / extractive / evidence-grounded document summary tool**：

```text
已摄入文档
-> 用户发起“总结 / 概括 / summary / overview”类请求
-> Router 识别为 document_summary
-> CLI dispatch 调用 document_summary 工具
-> 工具从 DocumentRepository 加载 EvidenceBlock
-> 按页聚合、筛选代表性文本块
-> 生成结构化摘要、key_points、page_summaries
-> 每条摘要点附带 page/block citation
-> 输出 result.json / summary.json / router_plan.json / trace.json
```

### 核心原则

- **先做 P0 可控闭环，不做开放式 LLM 摘要。**
- **摘要内容必须能追溯到 EvidenceBlock。**
- **不得调用 VLM、训练脚本、GRPO、AnswerPolicy 或外部 API。**
- **不得把本次实现包装成 final answer quality benchmark。**
- **不得顺手实现 table lookup、simple calculation、raw PDF online OCR 或 UI。**

---

## 3. In Scope

### 3.1 需要新增 / 修改的代码

优先按以下文件实现：

```text
docagent/tools/document_summary.py          # 新增：summary 工具主体
docagent/tools/__init__.py                  # 如项目已有工具导出规范，则补 export
scripts/docagent_cli.py                     # 修改：document_summary task dispatch
tests/test_phase5e_document_summary_tool.py # 新增：工具级测试
tests/test_phase5e_document_summary_cli.py  # 新增：CLI artifact / dispatch 测试
```

如现有项目已经有更合适的测试命名或 artifact helper，请遵循现有风格，但必须保留 Phase 5E 语义。

### 3.2 可选更新文档

若测试通过，可更新：

```text
docs/PHASE5_ACTIVE_PLAN.md
CURRENT_STATUS.md
DECISIONS.md
```

更新时必须使用准确状态词：

```text
Phase 5E Document Summary MVP: implemented / tested locally / accepted only after smoke
```

不要写成：

```text
final answer quality solved
full document QA completed
table QA completed
VLM reasoning supported
```

---

## 4. Out of Scope

本次任务明确不做：

| 能力 | 原因 |
|---|---|
| table lookup | 需要单独 row/column citation contract |
| simple calculation | 需要可追溯 numeric tool，不应混入 summary |
| raw PDF online MinerU OCR | 环境风险高，不属于 summary MVP |
| VLM / visual_pixel_qa | Phase 5 当前明确不做 |
| SFT / GRPO / 训练重启 | 本次是产品补洞，不是训练任务 |
| AnswerPolicy prompt 修改 | 避免影响 local_fact_qa 稳定链路 |
| final answer quality benchmark | 当前只做 summary 工具闭环 |
| FastAPI / Gradio UI | 后端工具稳定后再做 |
| Candidate-ID Reader | 当前不是本阶段优先级 |

---

## 5. 用户故事

### US-1：全文摘要

用户输入：

```text
总结这份文档
```

或：

```text
Summarize this document.
```

系统行为：

```text
Router -> document_summary
CLI -> summarize_document(...)
输出全文 bounded extractive summary，并附 citations。
```

### US-2：概括主要内容

用户输入：

```text
这篇报告主要讲什么？
```

系统行为：

```text
输出 answer + key_points + page_summaries。
```

### US-3：按页摘要，P0 可选

用户输入：

```text
概括第 3 页内容
```

可接受行为：

- 若 Router 将其识别为 `page_lookup`，保持现有 page_lookup 行为；
- 若 Router 将其识别为 `document_summary`，summary 工具可以解析页码并只摘要对应页；
- P0 不强制复杂 page range parser，但不得崩溃。

---

## 6. Functional Requirements

### FR-1：新增 summary 工具入口

新增文件：

```text
docagent/tools/document_summary.py
```

建议提供以下主函数：

```python
def summarize_document(
    repository,
    doc_id: str,
    *,
    question: str | None = None,
    page_range: list[int] | None = None,
    max_pages: int = 8,
    max_blocks_per_page: int = 4,
    max_key_points: int = 8,
    max_chars_per_point: int = 240,
    max_answer_chars: int = 2500,
) -> dict:
    """Build a deterministic, evidence-grounded document summary."""
```

如果项目 Python 版本不支持 `|` 类型语法，请改用 `Optional[str]` / `Optional[List[int]]`。

### FR-2：加载 EvidenceBlock

工具必须从现有 `DocumentRepository` 加载证据块。

优先使用现有方法，例如：

```python
blocks = repository.load_evidence_blocks(doc_id)
```

如果实际方法名不同，请根据 `docagent/storage/repositories.py` 的现有接口适配。

不得重新解析原始 PDF。  
不得从本地 output 文件绕过 repository 读取。  
不得调用 retriever 作为唯一摘要上下文。

### FR-3：EvidenceBlock 字段兼容

EvidenceBlock 字段可能包含：

```text
doc_id
page_id
block_id
block_type
text
table_html
image_path
visual_summary
location
bbox
```

实现时不要硬编码只适配一种 dict/dataclass 结构。建议添加小型 helper：

```python
def _get_field(block, name: str, default=None):
    if isinstance(block, dict):
        return block.get(name, default)
    return getattr(block, name, default)
```

对 location 也要兼容 dict/dataclass：

```python
location.page
location.block_id
```

或：

```python
location["page"]
location["block_id"]
```

### FR-4：文本归一化

实现轻量文本清洗：

```text
- strip 首尾空白
- collapse 多空格 / 多换行
- 跳过空文本
- 跳过过短噪声块，例如 < 12 chars，除非像标题
- 截断单个 key point 文本长度，默认 <= 240 chars
```

不要做复杂 NLP 依赖，不新增重型依赖。

### FR-5：按页聚合

按 page 排序并聚合 blocks：

```text
blocks -> group_by_page -> ordered_pages
```

页码来源优先级建议：

```text
location.page > block.page_id > block.metadata.page > unknown
```

若无法获得页码：

- 不应崩溃；
- citation 中 page 可以为 `null`；
- 添加 warning：`missing_page_metadata`。

### FR-6：bounded 摘要范围

默认只处理前 `max_pages=8` 页的有效文本块。

如果文档超过 max_pages：

```json
"warnings": [
  {
    "code": "summary_truncated_by_max_pages",
    "message": "Only the first 8 pages with textual evidence were summarized."
  }
]
```

如果实际项目 warning 习惯使用 string，也可以用 string，但建议结构化。

### FR-7：block 选择策略

P0 使用 deterministic scoring，不调用 LLM。

建议 score 逻辑：

```text
base score = normalized text length
+ heading/title bonus
+ early page bonus
+ informative keyword bonus
- repeated/boilerplate penalty
```

最低可接受实现：

```text
每页按原文顺序选取前 max_blocks_per_page 个有效文本块。
```

但建议更稳健：

```text
1. 保留疑似标题块；
2. 保留长度适中的正文块；
3. 跳过重复块；
4. 每页最多 max_blocks_per_page；
5. 全文最多 max_key_points。
```

可实现的简单规则：

```python
heading_bonus = 0.3 if len(text) <= 80 and not text.endswith(".") else 0.0
length_score = min(len(text) / 400.0, 1.0)
early_page_bonus = 0.1 if page in first_two_pages else 0.0
score = length_score + heading_bonus + early_page_bonus
```

### FR-8：标题候选

输出 `title_candidates`，从前 1-2 页选择：

```text
- 非空
- 较短
- 可能是标题 / heading
- 优先 page 靠前
```

最多返回 3 个。

若无法识别，返回空数组，不报错。

### FR-9：key_points

输出全局 key points：

```json
"key_points": [
  {
    "text": "...",
    "citations": [
      {
        "doc_id": "...",
        "page": 1,
        "block_id": "doc_xxx_p001_b003",
        "block_type": "text"
      }
    ]
  }
]
```

要求：

- 每个 key point 至少 1 个 citation；
- citation 必须来自已加载的 EvidenceBlock；
- 不生成无证据摘要点；
- key_points 数量默认 <= 8。

### FR-10：page_summaries

输出页级摘要：

```json
"page_summaries": [
  {
    "page": 1,
    "summary": "...",
    "citations": [
      {
        "doc_id": "...",
        "page": 1,
        "block_id": "doc_xxx_p001_b001",
        "block_type": "text"
      }
    ]
  }
]
```

P0 可以直接把该页选中的 1-2 个代表性块拼接为 summary preview。

### FR-11：answer 字段

最终 result 顶层必须有 `answer` 字段，方便 CLI 用户阅读。

中文问题可以输出中文 heading：

```text
文档摘要：
- ...
- ...
```

英文问题可以输出英文 heading：

```text
Document summary:
- ...
- ...
```

判断是否中文可使用简单 CJK 检测。

注意：正文可以保留原文语言，不需要机器翻译。

### FR-12：citation validation

必须实现 citation validation helper。

要求：

```text
valid block_id set = 所有加载到的 EvidenceBlock 的 block_id
每个 citation.block_id 必须在 valid block_id set 中
每个 citation.page 不应超过 documents.page_count，如果能读取 page_count
```

如果发现无效 citation：

- 测试中应 fail；
- 运行时不要 silently pass；
- 可返回 structured error 或 warning，并移除非法 citation。

### FR-13：错误处理

#### 文档不存在 / repository 读取失败

返回：

```json
{
  "task_type": "document_summary",
  "status": "error",
  "error": {
    "code": "document_not_found_or_unreadable",
    "message": "..."
  },
  "answer": "Unable to summarize the document because it could not be loaded.",
  "warnings": [],
  "citations": [],
  "summary": null
}
```

#### 文档无 evidence blocks

返回：

```json
{
  "task_type": "document_summary",
  "status": "error",
  "error": {
    "code": "no_evidence_blocks",
    "message": "No evidence blocks were found for this document."
  },
  "citations": [],
  "summary": null
}
```

#### 文档有 blocks 但没有可摘要文本

返回：

```json
{
  "task_type": "document_summary",
  "status": "unsupported",
  "error": {
    "code": "no_textual_evidence_for_summary",
    "message": "The document has evidence blocks but no textual content suitable for extractive summary."
  },
  "citations": [],
  "summary": null
}
```

### FR-14：trace 字段

输出中必须包含 trace 信息：

```json
"trace": {
  "tool": "document_summary",
  "strategy": "extractive_page_preview_v1",
  "used_llm": false,
  "used_vlm": false,
  "used_training": false,
  "blocks_loaded": 48,
  "blocks_considered": 24,
  "pages_considered": [1, 2, 3],
  "warnings_count": 0
}
```

字段名可适配现有 trace 风格，但必须表达：

```text
tool
strategy
used_llm=false
used_vlm=false
used_training=false
blocks/pages considered
```

---

## 7. Expected Output Schema

P0 推荐顶层结果：

```json
{
  "task_type": "document_summary",
  "status": "completed",
  "doc_id": "doc_xxx",
  "answer": "Document summary:\n- ...\n- ...",
  "summary": {
    "strategy": "extractive_page_preview_v1",
    "scope": {
      "doc_id": "doc_xxx",
      "page_count": 12,
      "pages_considered": [1, 2, 3, 4, 5, 6, 7, 8],
      "blocks_loaded": 64,
      "blocks_considered": 32,
      "max_pages": 8,
      "max_blocks_per_page": 4,
      "max_key_points": 8
    },
    "title_candidates": [
      {
        "text": "Annual Report 2022",
        "page": 1,
        "block_id": "doc_xxx_p001_b001"
      }
    ],
    "key_points": [
      {
        "text": "The document discusses ...",
        "citations": [
          {
            "doc_id": "doc_xxx",
            "page": 1,
            "block_id": "doc_xxx_p001_b003",
            "block_type": "text"
          }
        ]
      }
    ],
    "page_summaries": [
      {
        "page": 1,
        "summary": "Page 1 introduces ...",
        "citations": [
          {
            "doc_id": "doc_xxx",
            "page": 1,
            "block_id": "doc_xxx_p001_b003",
            "block_type": "text"
          }
        ]
      }
    ]
  },
  "citations": [
    {
      "doc_id": "doc_xxx",
      "page": 1,
      "block_id": "doc_xxx_p001_b003",
      "block_type": "text"
    }
  ],
  "warnings": [],
  "trace": {
    "tool": "document_summary",
    "strategy": "extractive_page_preview_v1",
    "used_llm": false,
    "used_vlm": false,
    "used_training": false
  }
}
```

如果现有 CLI 有统一 result schema，请尽量复用现有 schema，但不得丢失：

```text
status
answer
summary
citations
warnings
trace
```

---

## 8. CLI Dispatch Requirements

修改：

```text
scripts/docagent_cli.py
```

在 task dispatch 中新增：

```python
if router_decision.task_type == "document_summary":
    result = summarize_document(
        repository=repository,
        doc_id=doc_id,
        question=args.question,
    )
```

实际变量名请按现有 CLI 代码适配。

### 8.1 dry-run 语义

如果现有 `--dry-run` 只输出 router plan / 不执行工具，则保持现有 dry-run 语义。

要求：

- `--dry-run` 不应调用 summary 工具；
- 非 dry-run 才执行 summarize_document；
- dry-run 下不得被测试误判为 summary 未实现。

### 8.2 artifact 输出

summary 非 dry-run 成功执行后，output-dir 至少包含：

```text
result.json
summary.json
router_plan.json
trace.json
```

如当前 CLI 已经固定写 `result.json` / `router_plan.json` / `trace.json`，只新增 `summary.json` 即可。

`summary.json` 内容建议为：

```json
{
  "doc_id": "...",
  "task_type": "document_summary",
  "summary": {...},
  "citations": [...],
  "warnings": [...],
  "trace": {...}
}
```

### 8.3 不能影响已有任务

必须保证以下已有任务行为不被破坏：

```text
document_statistics
page_lookup
local_fact_qa
structured unsupported tasks
table_lookup_or_calculation unsupported boundary
```

---

## 9. Router Compatibility Requirements

Router 已支持 task types：

```text
local_fact_qa
table_lookup_or_calculation
document_statistics
page_lookup
structured_extraction
document_summary
```

本次不需要重写 Router。只有在现有 Router 无法识别明显 summary query 时，才做最小规则补充。

应识别的 summary intents：

```text
总结
概括
摘要
主要内容
主要讲什么
key points
takeaways
summarize
summary
overview
recap
abstract
```

不得把 summary 误路由到：

```text
table_lookup_or_calculation
simple calculation
VLM
training
```

---

## 10. Test Requirements

### 10.1 新增工具测试

新增：

```text
tests/test_phase5e_document_summary_tool.py
```

至少覆盖：

#### test_summarize_document_completed

给定一个 fixture repository，包含多页 text EvidenceBlock。  
调用 `summarize_document`。  
断言：

```text
status == completed
task_type == document_summary
summary is not None
len(key_points) > 0
len(page_summaries) > 0
len(citations) > 0
```

#### test_summary_citations_are_valid

断言所有 citation.block_id 均来自输入 blocks。

#### test_summary_is_bounded_by_max_pages

构造超过 `max_pages` 的多页 blocks。  
断言：

```text
len(pages_considered) <= max_pages
warnings contains summary_truncated_by_max_pages
```

#### test_empty_document_returns_structured_error

repository 返回空 blocks。  
断言：

```text
status == error
error.code == no_evidence_blocks
citations == []
```

#### test_no_textual_evidence_returns_unsupported

blocks 只有 image_path / empty text。  
断言：

```text
status == unsupported
error.code == no_textual_evidence_for_summary
```

#### test_summary_does_not_use_llm_vlm_training

断言 trace：

```text
used_llm == false
used_vlm == false
used_training == false
```

### 10.2 新增 CLI 测试

新增：

```text
tests/test_phase5e_document_summary_cli.py
```

至少覆盖：

#### test_cli_document_summary_dispatch_writes_artifacts

使用临时 `.txt` 文件或现有项目测试 fixture 完成 ingestion + CLI query。

示例问题：

```text
总结这份文档
```

断言 output-dir 中存在：

```text
result.json
summary.json
router_plan.json
trace.json
```

断言 result.json：

```text
task_type == document_summary
status == completed
summary.key_points exists
citations exists
```

#### test_cli_summary_no_longer_returns_unsupported

对明确 summary query，非 dry-run 下不应返回：

```text
status == unsupported
error.code == unsupported_task
```

除非 fixture 文档完全无文本；此时应返回 `no_textual_evidence_for_summary`。

#### test_cli_dry_run_keeps_existing_semantics

如果项目已有 dry-run 测试规范，保持兼容。

---

## 11. Manual Smoke Commands

### 11.1 TXT ingestion smoke

可在本地执行：

```bash
cat > /tmp/docagent_summary_smoke.txt <<'TXT'
DocAgent is a complex document question answering MVP.
It converts parsed document content into EvidenceBlock records.
The system supports routing, retrieval, deterministic document tools, citations, JSON artifacts, and traces.
The current milestone implements a document summary tool based on textual evidence blocks.
TXT

python scripts/docagent_cli.py \
  --db-path /tmp/docagent_phase5e_summary.db \
  --file /tmp/docagent_summary_smoke.txt \
  --question "总结这份文档" \
  --output-dir /tmp/docagent_phase5e_summary_out
```

检查：

```bash
python -m json.tool /tmp/docagent_phase5e_summary_out/result.json
python -m json.tool /tmp/docagent_phase5e_summary_out/summary.json
python -m json.tool /tmp/docagent_phase5e_summary_out/router_plan.json
python -m json.tool /tmp/docagent_phase5e_summary_out/trace.json
```

### 11.2 Existing doc_id smoke

如果已有数据库中有文档：

```bash
python scripts/docagent_cli.py \
  --db-path outputs/docagent.db \
  --doc-id <EXISTING_DOC_ID> \
  --question "Summarize this document." \
  --output-dir outputs/phase5e_document_summary_smoke
```

---

## 12. Acceptance Criteria

### P0 必须满足

| 编号 | 验收标准 |
|---|---|
| AC-1 | 明确 summary query 能被 Router 识别为 `document_summary`，或至少 CLI 能进入 document_summary dispatch |
| AC-2 | 非 dry-run 下 `document_summary` 不再返回 generic unsupported |
| AC-3 | summary 工具能从 DocumentRepository 加载 EvidenceBlock |
| AC-4 | 输出包含 `answer`、`summary`、`key_points`、`page_summaries`、`citations`、`warnings`、`trace` |
| AC-5 | 每个 key point 至少有一个有效 page/block citation |
| AC-6 | citation.block_id 必须来自已加载 EvidenceBlock |
| AC-7 | 长文档摘要范围受 `max_pages` / `max_blocks_per_page` 限制 |
| AC-8 | output-dir 写出 `result.json` / `summary.json` / `router_plan.json` / `trace.json` |
| AC-9 | 新增工具测试和 CLI 测试通过 |
| AC-10 | 不调用 LLM、VLM、training、GRPO、AnswerPolicy |
| AC-11 | 不破坏 Phase 5 既有 CLI / Router / deterministic tools / local_fact_qa 测试 |

### 推荐测试命令

按项目现有环境执行：

```bash
pytest tests/test_phase5e_document_summary_tool.py -q
pytest tests/test_phase5e_document_summary_cli.py -q
pytest tests/test_phase5f_cli.py tests/test_phase5_document_tools.py tests/test_phase5_router.py -q
```

若时间允许：

```bash
pytest tests/test_phase5g_cli_regression.py -q
```

---

## 13. Implementation Hints

### 13.1 建议内部数据结构

可定义轻量内部 dict：

```python
{
    "doc_id": doc_id,
    "page": page,
    "block_id": block_id,
    "block_type": block_type,
    "text": normalized_text,
    "score": score,
}
```

### 13.2 推荐函数拆分

```python
def summarize_document(...):
    blocks = _load_blocks(repository, doc_id)
    normalized = _normalize_blocks(blocks)
    grouped = _group_by_page(normalized)
    selected = _select_blocks(grouped, max_pages, max_blocks_per_page)
    title_candidates = _select_title_candidates(selected)
    key_points = _build_key_points(selected, max_key_points, max_chars_per_point)
    page_summaries = _build_page_summaries(selected, max_chars_per_point)
    citations = _collect_citations(key_points, page_summaries)
    warnings = _build_warnings(...)
    _validate_citations(citations, normalized)
    return _build_result(...)
```

### 13.3 去重规则

简单可用：

```python
seen = set()
key = normalized_text.lower()[:160]
if key in seen: skip
```

### 13.4 CJK 检测

```python
def _is_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text or "")
```

### 13.5 Citation 构造

```python
def _make_citation(item):
    return {
        "doc_id": item["doc_id"],
        "page": item.get("page"),
        "block_id": item.get("block_id"),
        "block_type": item.get("block_type"),
    }
```

### 13.6 避免引入重型依赖

不要新增：

```text
transformers
langchain
openai
spacy
nltk
pandas
faiss
```

如果项目已有依赖，也不要为了 summary 引入调用。

---

## 14. Definition of Done

本任务完成的标准：

```text
1. 新增 document_summary 工具。
2. CLI 能 dispatch document_summary。
3. Summary 输出结构化 JSON。
4. Summary 中的 key_points / page_summaries 有有效 citations。
5. summary.json artifact 被写入 output-dir。
6. 新增 Phase 5E tests。
7. 相关 Phase 5 regression tests 未被破坏。
8. 文档更新准确描述 implemented/tested 状态。
9. 没有新增 LLM/VLM/training/table/UI 逻辑。
```

---

## 15. 面试展示边界

实现完成后，可以对外描述为：

```text
我补齐了复杂文档 QA MVP 中的 document_summary 产品断点：在 Router 已能识别摘要意图的基础上，新增 evidence-grounded extractive summary 工具，从 SQLite 中加载 EvidenceBlock，按页聚合并筛选代表性文本块，生成带 page/block citation 的结构化摘要，并接入 CLI artifact 与 trace 流程，保证摘要内容可追溯。
```

不能描述为：

```text
实现了最终答案质量 benchmark。
实现了表格数值问答。
实现了 VLM 图文理解。
实现了任意 PDF 在线 OCR。
实现了完整商业级 DocAgent。
```

---

## 16. Codex Execution Checklist

开始实现前：

```text
- 先阅读 AGENTS.md。
- 再阅读 docs/ACTIVE_PLAN.md、CURRENT_STATUS.md、docs/PHASE5_ACTIVE_PLAN.md。
- 查看 scripts/docagent_cli.py 的现有 task dispatch 和 artifact writer。
- 查看 docagent/tools/document_tools.py 的工具返回格式。
- 查看 docagent/storage/repositories.py 的 DocumentRepository 接口。
- 查看 tests/test_phase5f_cli.py 和 tests/test_phase5_document_tools.py 的测试风格。
```

实现顺序：

```text
1. 新增 docagent/tools/document_summary.py。
2. 添加工具级单测，先让工具测试通过。
3. 修改 scripts/docagent_cli.py dispatch。
4. 添加 CLI artifact 测试。
5. 跑相关 Phase 5 regression tests。
6. 只在测试通过后更新文档状态。
```

提交前检查：

```text
- grep 确认没有新增训练调用。
- grep 确认没有新增 VLM 调用。
- grep 确认 summary 不依赖外部 API。
- 确认 result.json 和 summary.json 都是 valid JSON。
- 确认 citations 中 block_id 可回溯到 EvidenceBlock。
```
