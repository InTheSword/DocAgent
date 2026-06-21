# Phase 4C Candidate Spans Report

## Scope

Phase 4C evaluates query-aware / structure-aware multi-granularity evidence
packing on the accepted Phase 4B Gate 4 MP-DocVQA raw-input sample.

This is an expanded raw-input integration regression, not a formal MP-DocVQA
benchmark. The run does not change retrieval models, AnswerPolicy default
prompt, SFT/GRPO checkpoints, training data, CDC scope, or Demo scope.

Default behavior remains:

```text
--evidence-packing page_children
```

The evaluated accepted experimental mode is:

```text
--evidence-packing candidate_spans
```

## Baseline: Page Children

```text
run_dir = outputs/evaluation/phase4b_mpdocvqa_gate4/gate4_full_grpo
evidence_packing_mode = page_children
document_count = 26
page_count = 197
qa_count = 90

normalized_exact_match = 0.3333
answer_hit = 0.3444
token_f1 = 0.3689
character_f1 = 0.5235
gold_page_location_hit = 0.4889
page_location_hit = 0.4889
block_location_hit = 0.9667
final_location_in_evidence_rate = 1.0
valid_json_rate = 1.0
format_valid_rate = 1.0

failure_taxonomy:
  answer_miss = 59
  gold_page_location_miss = 46
  retrieval_gold_miss_top5 = 4

trace_counts:
  qa_runs = 90
  tool_traces = 613
```

## Candidate Spans: Retrieval-Only / Packing-Only

```text
run_dir = outputs/evaluation/phase4c_candidate_spans/gate4_candidate_spans_retrieval_only
status = success
evidence_packing_mode = candidate_spans
document_count = 26
page_count = 197
qa_count = 90
fixed_evidence_hash = 75a0fcb3f7e0c847d64a767a6a7116ec975a88b7c4ec3c48f54d70bd2f164bba

BM25 Recall@1/3/5 = 0.6111 / 0.8667 / 0.9111
BM25 MRR = 0.7259

Hybrid Recall@1/3/5 = 0.7333 / 0.9222 / 0.9556
Hybrid MRR = 0.8257

retrieval_gold_miss_top5 = 4
```

Candidate packing:

```text
sample_count = 90
mean_original_page_count = 2.9889
mean_original_block_count = 39.8444
mean_candidate_span_count = 7.9111
mean_candidate_block_count = 15.3333
mean_dropped_block_count = 24.5111
mean_estimated_prompt_tokens_before = 1911.7222
mean_estimated_prompt_tokens_after = 1809.9889
compression_ratio_blocks = 0.3848
compression_ratio_tokens = 0.9468
gold_page_in_candidate_pages_rate = 0.9556
gold_page_has_candidate_span_rate = 0.9556
no_gold_leakage = true
```

Retrieval-only / packing-only conclusions:

1. Phase 4C candidate evidence generation runs stably on the real accepted
   Gate 4 artifacts.
2. `candidate_evidence.jsonl`, `candidate_evidence_preview.json`,
   `candidate_packing_metrics.json`, and `fixed_evidence.jsonl` were produced.
3. `no_gold_leakage = true`, so candidate artifacts did not leak answers,
   gold page identifiers, `answer_page_idx`, or related supervision fields.
4. `gold_page_in_candidate_pages_rate` matches Hybrid Recall@5, so page-level
   retrieval was not degraded by the evidence packing mode.
5. `gold_page_has_candidate_span_rate = 0.9556`, so the second-stage candidate
   selection did not broadly remove valid candidates from gold pages.
6. Block compression is substantial, while token compression is weak. This
   indicates the method mainly reduces block-level noise rather than simply
   shortening the prompt.

## Candidate Spans: Full GRPO E2E

```text
run_dir = outputs/evaluation/phase4c_candidate_spans/gate4_candidate_spans_full_grpo
status = success
evidence_packing_mode = candidate_spans
document_count = 26
page_count = 197
qa_count = 90
fixed_evidence_hash = 75a0fcb3f7e0c847d64a767a6a7116ec975a88b7c4ec3c48f54d70bd2f164bba

completed_count = 90
failed_count = 0
normalized_exact_match = 0.4111
answer_hit = 0.4556
token_f1 = 0.4628
character_f1 = 0.6341
valid_json_rate = 1.0
format_valid_rate = 1.0
gold_page_location_hit = 0.6778
page_location_hit = 0.6778
block_location_hit = 1.0
final_location_in_evidence_rate = 1.0

failure_taxonomy:
  answer_miss = 49
  gold_page_location_miss = 29
  retrieval_gold_miss_top5 = 4

trace_counts:
  qa_runs = 90
  tool_traces = 599
```

## A/B Comparison

| Metric | page_children | candidate_spans | Delta |
|---|---:|---:|---:|
| normalized_exact_match | 0.3333 | 0.4111 | +0.0778 |
| answer_hit | 0.3444 | 0.4556 | +0.1111 |
| token_f1 | 0.3689 | 0.4628 | +0.0939 |
| character_f1 | 0.5235 | 0.6341 | +0.1106 |
| gold_page_location_hit | 0.4889 | 0.6778 | +0.1889 |
| page_location_hit | 0.4889 | 0.6778 | +0.1889 |
| block_location_hit | 0.9667 | 1.0000 | +0.0333 |
| valid_json_rate | 1.0000 | 1.0000 | 0 |
| format_valid_rate | 1.0000 | 1.0000 | 0 |
| final_location_in_evidence_rate | 1.0000 | 1.0000 | 0 |
| answer_miss | 59 | 49 | -10 |
| gold_page_location_miss | 46 | 29 | -17 |
| retrieval_gold_miss_top5 | 4 | 4 | 0 |

## Result Analysis

Phase 4C 的结果表明，candidate_spans 的提升不是来自 retrieval 模型变化，也不是来自更换 AnswerPolicy 或重训模型。Hybrid retrieval metrics 与 Phase 4B Gate 4 baseline 保持一致，retrieval_gold_miss_top5 仍为 4。因此，answer_hit 和 gold_page_location_hit 的提升主要来自 query-aware / structure-aware evidence packing 对 Reader 输入证据的重新组织。

具体来说，原始 page_children 模式会将 Hybrid Top-k pages 展开为较多 child EvidenceBlocks，让 Reader 在多页、多字段、多数字和相似版式中自行选择答案。candidate_spans 在不使用 gold 信息的前提下，根据 question hint、block_type、layout metadata、numeric/date/source/heading 等规则在 Top-k pages 内筛选候选 span，将平均输入 block 数从 39.84 降至 15.33，减少了约 61.5% 的 block 级噪声。

虽然 token compression ratio 仅为 0.9468，说明 prompt 长度并未显著减少，但 answer_hit、normalized EM、token/character F1 和 gold_page_location_hit 均明显提升。这说明 candidate_spans 的主要收益不是简单缩短上下文，而是减少无关 block 干扰、强化候选证据与问题的结构对应关系，从而改善 Reader grounding 和答案抽取稳定性。

Phase 4C 也验证了此前问题判断：page-level Top-5 recall 高并不等于最终 QA 准确。page-level retrieval 只能保证 gold page 被看到，但无法保证 gold page 内的正确字段、表格值、标题、source 或日期被 Reader 正确选择。因此，在 page-level retrieval 和 Reader 之间增加多粒度证据筛选层是有效的。

In short, Phase 4C shows that query-aware / structure-aware candidate evidence
packing improves Reader grounding and answer extraction under the same
retrieval and AnswerPolicy setting.

## Accepted Boundary

```text
Phase 4C local implementation -> accepted
Phase 4C server retrieval-only / packing-only -> accepted
Phase 4C server full GRPO E2E -> accepted
```

Boundary notes:

- default `page_children` behavior remains unchanged;
- `candidate_spans` is an accepted experimental and recommended evidence
  packing mode for the Gate 4 style raw-input E2E path;
- Phase 4C does not change the retrieval model;
- Phase 4C does not change the default AnswerPolicy prompt;
- Phase 4C does not involve SFT or GRPO retraining;
- Phase 4C does not enter CDC;
- Phase 4C is not a formal MP-DocVQA benchmark;
- setting `candidate_spans` as a global default requires more shard and
  document-type validation.
