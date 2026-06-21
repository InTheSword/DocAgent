# Phase 4D-A：Candidate Answer Coverage Audit

## 0. 当前项目背景

当前 `main` 已经包含：

```text
Phase 4B Gate 4 accepted
+ Phase 4C candidate_spans accepted
+ Phase 4C documentation closure
```

Phase 4C 已完成并合并到主线，核心结论为：

```text
在不改变 retrieval model、不更换 AnswerPolicy、不重新训练的条件下，
query-aware / structure-aware candidate_spans evidence packing
显著提升了 Reader 的答案抽取和证据页定位稳定性。
```

已接受的 Phase 4C 结果：

```text
Baseline page_children:
normalized_exact_match = 0.3333
answer_hit = 0.3444
token_f1 = 0.3689
character_f1 = 0.5235
gold_page_location_hit = 0.4889
answer_miss = 59
gold_page_location_miss = 46
retrieval_gold_miss_top5 = 4

Phase 4C candidate_spans:
normalized_exact_match = 0.4111
answer_hit = 0.4556
token_f1 = 0.4628
character_f1 = 0.6341
gold_page_location_hit = 0.6778
answer_miss = 49
gold_page_location_miss = 29
retrieval_gold_miss_top5 = 4
```

Phase 4C 证明：

```text
page-level retrieval 之后，增加 query-aware / structure-aware candidate evidence packing 是有效的。
```

但当前整体 QA 效果仍然一般：

```text
answer_hit = 0.4556
normalized_exact_match = 0.4111
answer_miss = 49 / 90
```

这说明当前瓶颈已经从：

```text
page-level retrieval 是否召回 gold page
```

进一步转移到：

```text
candidate span / candidate answer / minimal evidence unit 是否覆盖正确答案；
Reader 是否能从 candidate evidence 中抽取或选择正确答案；
答案、答案类型与证据来源是否一致。
```

---

## 1. 本阶段核心判断

### 1.1 为什么不能继续只看 page-level Recall@5

Phase 4B / Phase 4C 使用 MP-DocVQA `answer_page_idx`，因此 page-level recall 是合理的粗粒度指标。

但现在系统链路已经变为：

```text
Hybrid page retrieval
→ candidate_spans 二级证据筛选
→ candidate blocks / spans
→ AnswerPolicy
```

最终返回给大模型的不是完整 page，而是经过筛选后的 candidate evidence。

因此，Phase 4D-A 更应关注：

```text
candidate span 是否包含 gold answer；
candidate answer 是否能被规则抽取出来；
candidate answer 在候选列表中的位置；
候选答案中是否存在大量同类型干扰项；
错误样本是 evidence coverage 问题，还是 Reader selection 问题。
```

换言之，当前需要从：

```text
Page Recall@k
```

转向：

```text
Evidence Unit Coverage
Candidate Answer Coverage
Candidate Answer Rank
Same-type Distractor Count
```

---

### 1.2 为什么本阶段暂不直接实现 Two-stage Reader

此前预设的 Two-stage Reader 思路为：

```text
Stage 1: Evidence Selection
Stage 2: Answer Extraction / Verification
```

但当前还没有回答一个前置问题：

```text
candidate_spans 中是否已经覆盖了正确答案？
```

如果直接改 Reader / Prompt / full E2E，会导致结果难以解释：

```text
如果效果提升：是 candidate answer 覆盖好，还是 prompt 变清楚？
如果效果下降：是 candidate board 抽取错，还是 prompt 干扰 Reader？
```

因此本阶段先不改 Reader，不改 prompt，不跑 full GRPO，而是只做：

```text
candidate answer extraction
+ candidate answer coverage audit
+ error bucket analysis
```

等确认 candidate answer 覆盖率足够后，再进入 Phase 4D-B：

```text
Candidate-ID Grounded Reader / Two-stage Reader
```

---

### 1.3 为什么要重新思考 SFT / GRPO 输出协议

当前 SFT / GRPO 旧协议让模型直接输出：

```json
{
  "answer": "...",
  "evidence_location": {
    "page": 3,
    "block_id": "...",
    "bbox": [...]
  },
  "evidence": "...",
  "reason": "..."
}
```

这个设计在早期用于快速形成结构化输出是合理的，但在系统已经具备 multi-level evidence index 后，可能存在结构性问题：

1. `page / block_id / bbox` 是系统索引信息，不一定应该让 LLM 自由生成；
2. 模型可能答案正确但 location 复制错误；
3. 模型可能 location 正确但 answer 抽错；
4. SFT / RL 可能过多学习格式和 ID 复制，而不是学习证据选择；
5. 最终系统只需要保证输出中包含答案和来源，不一定需要来源由模型直接生成。

更合理的未来协议可能是：

```json
{
  "answer": "31",
  "supporting_candidate_ids": ["C007"],
  "reason": "The requested field is the index, which is the number in parentheses."
}
```

系统根据 `supporting_candidate_ids` 自动还原：

```json
{
  "evidence_location": {
    "page": 3,
    "block_id": "...",
    "bbox": [...]
  },
  "evidence": "Share of the 21-25 Segment: 2.5% (31)"
}
```

因此，SFT / GRPO 的未来重点应从：

```text
让模型生成完整 location JSON
```

转向：

```text
让模型选择正确 candidate_id、抽取正确 answer、判断 answer type、处理拒答与多证据融合。
```

本阶段不重新训练，也不修改训练协议，只为后续协议调整建立 candidate answer coverage 数据基础。

---

## 2. 本轮目标

请在新的功能分支上实现：

```text
Phase 4D-A：Candidate Answer Coverage Audit
```

目标：

```text
基于 Phase 4C candidate_spans artifacts，
实现 typed candidate answer extraction，
生成 candidate answer board artifacts，
并计算 candidate answer coverage / rank / distractor / error bucket metrics。
```

本轮不做：

```text
不改 Reader prompt；
不接入 AnswerPolicy；
不跑 full GRPO；
不重新训练；
不改 retrieval model；
不改 MinerU；
不进入 CDC；
不做 Demo；
不改变 candidate_spans accepted 结论；
不合并 main。
```

本轮只做：

```text
candidate answer extraction
candidate answer coverage audit
minimal evidence unit coverage metrics
error bucket analysis
documentation update
local tests
```

---

## 3. 分支要求

在本地仓库：

```text
D:/Projects/docagent
```

执行：

```bash
git fetch --all --prune
git checkout main
git pull --ff-only origin main
git status --porcelain --untracked-files=no
```

要求 tracked worktree 必须干净。

如果不干净，停止并报告，不要自动 stash，不要自动丢弃文件。

创建新分支：

```text
codex/phase4d-candidate-answer-coverage
```

---

## 4. 开始前必须读取

请先读取并理解：

```text
AGENTS.md
CURRENT_STATUS.md
DECISIONS.md
docs/ACTIVE_PLAN.md
docs/PHASE4_ACTIVE_PLAN.md
docs/IMPLEMENTATION_PLAN.md
docs/PHASE4C_CANDIDATE_SPANS_REPORT.md  # 若存在
scripts/run_phase4b_mpdocvqa_e2e.py
docagent/retrieval/evidence_packing.py
tests/test_evidence_packing.py
tests/test_phase4b_mpdocvqa_e2e.py
```

重点确认：

1. `candidate_spans` 的 schema；
2. `question_hints` 当前包含哪些字段；
3. `candidate_evidence.jsonl` 如何生成；
4. `fixed_evidence.jsonl` 如何进入 AnswerPolicy；
5. `answer_metrics` 如何计算；
6. gold answers 在 metrics 阶段如何读取；
7. no-gold-leakage 当前如何检查；
8. summary / metrics / preview artifact 的写入方式。

---

## 5. 输入 artifact

服务器已存在 Phase 4C candidate_spans 结果：

```text
outputs/evaluation/phase4c_candidate_spans/gate4_candidate_spans_retrieval_only/
outputs/evaluation/phase4c_candidate_spans/gate4_candidate_spans_full_grpo/
```

本阶段主要应支持从以下 artifact 读取：

```text
candidate_evidence.jsonl
candidate_packing_metrics.json
page_retrieval_results.jsonl
summary.json
```

以及从 sample root 读取 QA gold answers：

```text
outputs/phase4/mpdocvqa_raw_gate4_expanded/qa.jsonl
```

注意：

- `candidate_answers.jsonl` 不允许写入 gold answers；
- gold answers 只能用于 coverage metrics；
- candidate answer extraction 不得读取 gold answers。

---

## 6. 新增核心模块

建议新增模块，路径可按现有结构调整：

```text
docagent/retrieval/candidate_answer_extraction.py
```

核心函数建议：

```python
extract_candidate_answers(question, question_hints, candidate_spans) -> CandidateAnswerBoard
compute_candidate_answer_coverage(candidate_answers, gold_answers) -> dict
bucket_candidate_answer_failures(...) -> dict
```

也可以与现有 `docagent/retrieval/evidence_packing.py` 复用数据结构，但不要把文件写得过于臃肿。

---

## 7. Candidate Answer schema

每条 QA 输出到：

```text
candidate_answers.jsonl
```

每行示例：

```json
{
  "qid": "...",
  "doc_id": "...",
  "question": "...",
  "question_hints": {
    "answer_type_hint": "index",
    "keywords": ["share", "21-25", "segment"],
    "field_hints": ["index", "share"]
  },
  "candidate_answers": [
    {
      "candidate_answer_id": "a0001",
      "answer_text": "31",
      "normalized_answer": "31",
      "answer_type": "index",
      "source_candidate_id": "c0003",
      "source_block_ids": ["..."],
      "page": 3,
      "block_id": "...",
      "evidence_text": "Share of the 21-25 Segment: 2.5% (31)",
      "extraction_rule": "parenthesized_index",
      "score": 0.87,
      "score_breakdown": {
        "field_hint_match": 0.3,
        "answer_type_match": 0.3,
        "lexical_context_match": 0.2,
        "candidate_span_score": 0.1
      }
    }
  ],
  "answer_board_stats": {
    "candidate_answer_count": 8,
    "unique_normalized_answer_count": 6,
    "answer_type_distribution": {
      "index": 3,
      "percentage": 2,
      "date": 1
    },
    "same_type_distractor_count": 2,
    "numeric_distractor_count": 4
  }
}
```

必须禁止写入以下字段：

```text
answers
gold_answers
answer_page_idx
gold_page_id
gold_page_ordinal
gold_page_mapping
```

---

## 8. Candidate Answer 抽取规则

使用 deterministic rule-based extraction，不调用大模型。

### 8.1 date

匹配：

```text
\d{1,2}[./-]\d{1,2}[./-]\d{2,4}
\d{4}
Jan|Feb|...|December + day/year
```

示例：

```text
6.14.74
1/12/04
June 14, 1974
1974
```

### 8.2 percentage

匹配：

```text
2.5%
0.9%
12 percent
12 percentage
```

### 8.3 index

重点支持：

```text
(31)
( 31)
31
```

当 `question_hints.field_hints` 包含：

```text
index
```

且 evidence 中出现：

```text
share
segment
rate
franchise
loss
index
```

时，括号数字或 index 相关数字应优先于百分比。

### 8.4 source

如果问题包含：

```text
source
bottom
starting with
```

优先抽取：

```text
Source: ...
USMM ...
https://...
```

注意：

source/footer 不能因为 boilerplate 默认被完全忽略。

### 8.5 heading / title

如果问题包含：

```text
heading
title
subject
```

优先抽取：

```text
text_level
raw_mineru_type = heading/title
页面顶部 bbox block
```

### 8.6 numeric

匹配：

```text
整数
小数
金额
括号负数
rate/value/total/amount 相关数字
```

### 8.7 generic text

对于没有明显 answer_type 的问题，抽取短文本候选：

- 避免整段长文本直接作为 answer；
- 避免只返回停用词；
- 可从标题、字段值、冒号后的短语中抽取。

---

## 9. Coverage metrics

新增：

```text
candidate_answer_coverage_metrics.json
```

至少包含：

```text
sample_count
candidate_span_answer_coverage
candidate_answer_coverage
candidate_answer_coverage_by_answer_type
candidate_answer_coverage_by_question_hint
gold_answer_rank_distribution
mean_candidate_answer_count
mean_unique_candidate_answer_count
mean_same_type_distractor_count
mean_numeric_distractor_count
no_candidate_answer_count
candidate_answer_no_gold_leakage
```

### 9.1 candidate_span_answer_coverage

定义：

```text
任一 gold answer normalized 后是否出现在 candidate span text 中。
```

这衡量：

```text
candidate_spans 是否已经覆盖正确答案文本。
```

### 9.2 candidate_answer_coverage

定义：

```text
任一 gold answer normalized 后是否出现在 extracted candidate_answers.normalized_answer 中。
```

这衡量：

```text
抽取规则是否能把正确答案从 candidate spans 中抽出来。
```

### 9.3 gold_answer_rank_distribution

如果 gold answer 出现在 candidate_answers 中，记录其首次出现排名：

```text
rank_1
rank_2
rank_3
rank_4_5
rank_6_10
rank_gt10
missing
```

### 9.4 distractor metrics

记录：

```text
same_type_distractor_count
numeric_distractor_count
candidate_answer_count
unique_candidate_answer_count
```

用于分析：

```text
候选答案列表是否过长；
是否存在大量同类型干扰；
Reader 为什么容易抽错。
```

---

## 10. Error bucket analysis

新增：

```text
candidate_answer_error_buckets.json
```

将样本分为：

```text
A. retrieval_gold_miss_top5
B. gold_page_in_top5_but_no_candidate_span_on_gold_page
C. gold_answer_not_in_candidate_spans
D. gold_answer_in_candidate_spans_but_not_extracted
E. gold_answer_in_candidate_answers_but_model_answer_wrong
F. gold_answer_in_candidate_answers_and_model_answer_correct
G. unclear_or_unclassified
```

说明：

- 对于 E/F，需要读取 Phase 4C full GRPO `answer_results.jsonl`；
- 如果 answer_results 不存在，可以跳过 E/F，并在 report 中标注 unavailable；
- 不允许把这些 gold 信息写入 `candidate_answers.jsonl`；
- gold 只允许进入 metrics / buckets。

---

## 11. Runner / Script 实现方式

可以二选一：

### 方案 A：新增独立脚本，推荐

新增：

```text
scripts/analyze_phase4d_candidate_answer_coverage.py
```

CLI 参数建议：

```text
--candidate-evidence
--qa-jsonl
--answer-results
--output-root
--run-id
--force
```

示例：

```bash
python scripts/analyze_phase4d_candidate_answer_coverage.py \
  --candidate-evidence outputs/evaluation/phase4c_candidate_spans/gate4_candidate_spans_full_grpo/candidate_evidence.jsonl \
  --qa-jsonl outputs/phase4/mpdocvqa_raw_gate4_expanded/qa.jsonl \
  --answer-results outputs/evaluation/phase4c_candidate_spans/gate4_candidate_spans_full_grpo/answer_results.jsonl \
  --output-root outputs/evaluation/phase4d_candidate_answer_coverage \
  --run-id gate4_candidate_answer_coverage \
  --force
```

### 方案 B：扩展原 E2E runner

不推荐本轮扩展 `run_phase4b_mpdocvqa_e2e.py`，因为本阶段是 analysis / audit，不应进一步增加主 runner 复杂度。

优先使用方案 A。

---

## 12. 输出 artifacts

输出目录：

```text
outputs/evaluation/phase4d_candidate_answer_coverage/<run_id>/
```

至少包含：

```text
candidate_answers.jsonl
candidate_answers_preview.json
candidate_answer_coverage_metrics.json
candidate_answer_error_buckets.json
summary.json
summary.md
```

summary 中明确记录：

```json
{
  "phase": "Phase 4D-A",
  "task": "candidate_answer_coverage_audit",
  "status": "success",
  "input_candidate_evidence": "...",
  "input_qa_jsonl": "...",
  "input_answer_results": "...",
  "does_not_modify_reader": true,
  "does_not_run_answer_policy": true,
  "does_not_train": true,
  "no_gold_leakage_in_candidate_answers": true
}
```

---

## 13. No-gold-leakage 要求

必须实现自动检查：

`candidate_answers.jsonl` 不得包含：

```text
answers
gold_answers
answer_page_idx
gold_page_id
gold_page_ordinal
gold_page_mapping
```

`candidate_answer_coverage_metrics.json` 和 `candidate_answer_error_buckets.json` 可以包含 coverage / bucket 统计，但不要把完整 gold answer 文本批量输出到 preview 中。

如果为调试需要保存失败样本，最多保存：

```text
qid
doc_id
question
bucket
counts
```

不要在 preview 中大段泄露 gold answers。

---

## 14. 测试要求

新增或扩展 fixture tests，至少覆盖：

1. date extraction；
2. percentage extraction；
3. index extraction；
4. source extraction；
5. heading/title extraction；
6. numeric extraction；
7. generic text fallback；
8. index question 中括号数字优先于百分比；
9. source/footer 不被默认排除；
10. candidate_answers 不包含 gold/answers 字段；
11. candidate_span_answer_coverage 计算正确；
12. candidate_answer_coverage 计算正确；
13. gold answer rank distribution 计算正确；
14. distractor metrics 计算正确；
15. error bucket A/B/C/D/E/F 至少用合成样本覆盖主要分支；
16. answer_results 缺失时仍能运行；
17. CLI `--help` 正常；
18. summary 记录 no-gold-leakage；
19. 所有输出路径为 relative POSIX 或明确记录为 input path；
20. git diff check 通过。

---

## 15. 文档更新

最小更新：

```text
docs/ACTIVE_PLAN.md
docs/PHASE4_ACTIVE_PLAN.md
CURRENT_STATUS.md
DECISIONS.md
```

记录：

```text
Phase 4D-A = active / implemented
目标 = candidate answer coverage audit
不改 Reader
不改 Prompt
不跑模型
不重训
不进入 CDC
```

不要改写 Phase 4C accepted 结论。

---

## 16. 本地验证

执行：

```bash
python -m py_compile <新增/修改 Python 文件>
python -m pytest -q <新增/相关 targeted tests>
python -m pytest -q
git diff --check
python scripts/analyze_phase4d_candidate_answer_coverage.py --help
```

如果本地没有真实 Phase 4C server artifacts，只需要 fixture tests 通过。不要因为缺服务器 outputs 阻塞本地实现。

---

## 17. Git 要求

完成后：

1. commit；
2. push 到：

```text
origin/codex/phase4d-candidate-answer-coverage
```

3. 不合并 main；
4. 不删除其他分支；
5. 不运行服务器 full E2E；
6. 不调用 MinerU；
7. 不训练模型；
8. 停止等待用户确认。

---

## 18. 返回内容

请返回：

1. 分支与基线确认；
2. 实现摘要；
3. 新增脚本 / 模块；
4. 新增 artifacts；
5. 新增 metrics；
6. no-gold-leakage 检查；
7. 修改文件；
8. targeted/full tests；
9. commit hash；
10. 是否已 push；
11. 服务器下一步建议命令：
    - A. candidate answer coverage audit；
    - B. compact summary check；
    - C. 是否根据 coverage 进入 Candidate-ID Grounded Reader。
```

---

## 19. 阶段完成后的决策标准

服务器运行 Phase 4D-A 后，根据结果判断：

### 情况 1：candidate_answer_coverage 高，但 answer_hit 仍低

说明：

```text
Reader selection 是瓶颈。
```

下一步进入：

```text
Phase 4D-B：Candidate-ID Grounded Reader
```

### 情况 2：candidate_span_answer_coverage 高，但 candidate_answer_coverage 低

说明：

```text
答案在 evidence 中，但 typed extraction 规则不足。
```

下一步优先改抽取规则，不改 Reader。

### 情况 3：candidate_span_answer_coverage 低

说明：

```text
candidate_spans 仍未覆盖足够答案。
```

下一步回到 evidence packing / block-span selection。

### 情况 4：candidate_answer_coverage 高，candidate answer 干扰项也很多

说明：

```text
需要 candidate ranking / type-aware candidate selection。
```

下一步可做 candidate answer reranking，而不是直接让 Reader 自由生成。

### 情况 5：candidate_answer_coverage 和 answer_hit 都较高

说明：

```text
系统已经具备 candidate-id grounded protocol 的数据基础。
```

下一步可考虑调整 AnswerPolicy 输出协议：

```json
{
  "answer": "...",
  "supporting_candidate_ids": ["..."]
}
```

由系统还原 page/block/bbox。
