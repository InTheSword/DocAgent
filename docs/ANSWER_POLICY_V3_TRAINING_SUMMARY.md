# AnswerPolicy v3 Training Summary

> Current decision record for the AnswerPolicy v3 SFT stage and the next
> post-training step. This document summarizes train-only evidence only and
> does not claim formal benchmark acceptance.

## 1. Training Target

AnswerPolicy v3 trains the final answer generation layer, not the whole
retrieval or tool-planning system.

The model input is:

```text
Question + numbered evidence candidates / optional tool observations
```

The model output target is:

```json
{
  "answer": "...",
  "supporting_refs": ["E2"],
  "support_status": "supported|insufficient",
  "reasoning_summary": "..."
}
```

The model does not output real `block_id`, `doc_id`, page paths, image paths,
or trace paths. System code maps temporary refs such as `E2` back to internal
evidence metadata through `EvidenceRefMap`.

This stage trains evidence-grounded answer behavior only. It does not train:

- retrieval;
- OCR or PDF parsing;
- tool planning / Agent actions;
- VLM image understanding;
- production DPO/GRPO behavior.

## 2. Data Status

The full train-only data construction target for the current SFT experiment is
complete enough for the first expanded stage.

Server materialization:

- MP-DocVQA train windows: 848/848 completed with live MinerU API/OCR.
- MP-DocVQA QA rows evidence-ready: 3036/3039.
- The materialization command status was diagnostic `failed` only because 3 QA
  rows were not evidence-ready; document parsing itself had 0 failed documents.

Train-only v3 sources:

| Source | Records |
|---|---:|
| MP-DocVQA supported | 2156 |
| MP-DocVQA insufficient | 2000 |
| TAT-QA supported | 5000 |
| TAT-QA insufficient | 2000 |

The expanded mixed pack selected 4096 records with no shortage/backfill:

| Bucket | Records |
|---|---:|
| MP-DocVQA supported | 2048 |
| TAT-QA supported | 1638 |
| insufficient | 410 |

Validation/final-eval subsets were not used as training data.

## 3. Completed SFT Experiments

### 3.1 Expanded mixed SFT

Run:

```text
answer_policy_v3_msswift_stage2_full4096_1024steps_20260705
```

This run trained Qwen3-1.7B with ms-swift LoRA for 1024 steps on the expanded
4096-record mixed pack. It verified the full train-data and SFT execution path,
but later prompt/input-contract issues made it a historical diagnostic rather
than the preferred checkpoint.

### 3.2 Promptfix expanded mixed SFT

Run:

```text
answer_policy_v3_msswift_stage2_promptfix3840_1024steps_20260705
```

Checkpoint:

```text
/root/autodl-tmp/docagent/outputs/training/answer_policy_v3_msswift_sft/answer_policy_v3_msswift_stage2_promptfix3840_1024steps_20260705/swift_output/v0-20260705-060610/checkpoint-1024
```

The promptfix rebuild repaired the training prompt / runtime evidence-contract
alignment before training:

- runtime-style evidence candidates are used;
- `reasoning_summary` is constrained to the v3 schema limit;
- legacy table-prefix prompt artifacts are removed;
- v3 refs remain temporary `E#` values rather than system block IDs.

Heldout split:

```text
answer_policy_v3_full4096_promptfix_split256_20260705
```

Promptfix heldout comparison:

| Metric | Base | Promptfix adapter |
|---|---:|---:|
| answer_exact_rate | 0.3750 | 0.5859 |
| schema_valid_rate | 0.8906 | 0.9961 |
| support_status_match_rate | 0.9063 | 0.9727 |
| positive_ref_hit_rate | 0.8851 | 0.9407 |
| insufficient_ref_empty_rate | 0.0556 | 0.9474 |

Decision:

```text
freeze as current SFT checkpoint for post-training preparation
```

Rationale:

- It is the cleanest checkpoint trained after prompt-contract repair.
- It improves the intended train-only v3 objective across the main reported
  metrics.
- It does not rely on validation/final-eval rows.
- Later continuation runs either have narrower scope or introduce regressions.

### 3.3 Rejection-SFT continuation diagnostic

Run:

```text
answer_policy_v3_rejection_sft_full4096_adapter_56steps_20260705
```

This run verified the adapter-continuation and rejection-SFT artifact path. It
showed useful train-only heldout movement, but it continued from the earlier
full4096 adapter rather than the promptfix checkpoint. It also was not a
production post-training decision. Keep it as a historical path validation, not
as the frozen SFT checkpoint.

Promptfix-based bounded post-training preparation then generated real model
candidates from the frozen SFT checkpoint:

```text
answer_policy_v3_candidates_promptfix1024_train256x4_20260705
answer_policy_v3_candidates_promptfix1024_train256x4_offset256_20260705
```

These runs used two bounded 256-record train-only slices and 4 Qwen+LoRA
candidates per record:

| Metric | Value |
|---|---:|
| records | 512 |
| candidates | 2048 |
| first-slice raw JSON OK | 1018 / 1024 |
| first-slice schema OK | 1018 / 1024 |
| second-slice raw JSON OK | 1024 / 1024 |
| second-slice schema OK | 1023 / 1024 |

Reward ranking run:

```text
answer_policy_v3_rejection_promptfix1024_train256x4_20260705
answer_policy_v3_rejection_promptfix1024_train256x4_offset256_20260705
```

produced:

| Artifact | Count |
|---|---:|
| selected candidates | 512 |
| training-ready selected candidates | 377 |
| preference pairs | 512 |
| training-ready preference pairs | 44 |
| rejection-SFT records | 377 |

The first 182 rejection-SFT records contained 67 MP-DocVQA records, 115 TAT-QA
records, 161 supported records, and 21 insufficient records, and were used for a
small bounded continuation. The combined 377 rejection-SFT records are useful
for future rejection-SFT distillation, but the 44 training-ready preference
pairs are still not enough for a reliable DPO stage. Most unavailable
preference pairs are blocked by insufficient reward margin rather than schema
failure.

Promptfix-based bounded rejection-SFT continuation:

```text
answer_policy_v3_rejection_sft_promptfix1024_182records_46steps_20260705
```

continued from the promptfix checkpoint for 46 ms-swift steps on the 182
train-only rejection-SFT records. Heldout256 comparison against the promptfix
checkpoint:

| Metric | Promptfix | Rejection-SFT continuation |
|---|---:|---:|
| json_valid_rate | 0.9961 | 1.0000 |
| schema_valid_rate | 0.9961 | 1.0000 |
| answer_exact_rate | 0.5859 | 0.5859 |
| support_status_match_rate | 0.9727 | 0.9766 |
| supporting_refs_subset_rate | 0.9961 | 1.0000 |
| positive_ref_hit_rate | 0.9407 | 0.9409 |
| insufficient_ref_empty_rate | 0.9474 | 1.0000 |
| thinking_rate | 0.0000 | 0.0000 |

Row movement was balanced: 9 candidate improvements and 9 regressions. This
means the continuation is a valid bounded post-training candidate with no
aggregate contract regression, but it is not a clear answer-quality improvement
over the frozen promptfix SFT checkpoint.

The combined 377 rejection-SFT records were then trained in one bounded
continuation:

```text
answer_policy_v3_rejection_sft_promptfix1024_377records_96steps_20260705
```

This run continued from the same frozen promptfix checkpoint for 96 ms-swift
steps. Training completed successfully with final `train_loss=0.01395`.
Heldout256 comparison against the promptfix checkpoint:

| Metric | Promptfix | 377-record continuation |
|---|---:|---:|
| json_valid_rate | 0.9961 | 1.0000 |
| schema_valid_rate | 0.9961 | 1.0000 |
| answer_exact_rate | 0.5859 | 0.6016 |
| support_status_match_rate | 0.9727 | 0.9766 |
| supporting_refs_subset_rate | 0.9961 | 1.0000 |
| positive_ref_hit_rate | 0.9407 | 0.9367 |
| insufficient_ref_empty_rate | 0.9474 | 1.0000 |
| thinking_rate | 0.0000 | 0.0000 |

Row movement was net positive on the fixed-evidence heldout: 10 candidate
improvements, 6 regressions, 144 both correct, and 96 both missed. This makes
the checkpoint a stronger post-training candidate than the 182-record
continuation for the intended AnswerPolicy v3 objective. It still should not be
promoted as the default production checkpoint from this signal alone.

Clean6 full-workflow guard:

```text
phase5ib_v3refs_clean6_rejection377_continue96_20260705
phase5ib_v3refs_clean6_promptfix1024_vs_rejection377_continue96_20260705
```

The 377-record continuation preserved workflow execution and citation mapping:
6/6 rows used the LLM query rewriter, BGE-M3 retrieval, reranker, Qwen SFT
AnswerPolicy, and `v3_refs`; JSON/artifact output and citation page hits were
6/6. The deployment guard still blocked default promotion because the clean6
pass count moved from 3/6 in the compared adapter run to 2/6, with two
candidate regressions and one candidate improvement. This is a deployment
guard result, not a rejection of the fixed-evidence training objective gain.

Decision:

```text
keep the 377-record continuation as the current post-training candidate;
do not promote as default; do not start DPO/GRPO
```

### 3.4 Table/calculation continuation diagnostic

Run:

```text
answer_policy_v3_msswift_tablecalc_continue1984_384steps_20260705
```

This run continued from the promptfix checkpoint on 1984 train-only
table/calculation records.

Strict table/calculation heldout:

| Metric | Promptfix | Tablecalc continuation |
|---|---:|---:|
| answer_exact_rate | 0.7519 | 0.7669 |
| calculation answer_exact_rate | 1.0000 | 1.0000 |
| table-value answer_exact_rate | 0.6118 | 0.6353 |

Broader heldout256:

| Metric | Promptfix | Tablecalc continuation |
|---|---:|---:|
| answer_exact_rate | 0.5859 | 0.5898 |
| insufficient_ref_empty_rate | 0.9474 | 0.8421 |

Decision:

```text
do not promote
```

Rationale:

- It is useful evidence that table/value selection can be improved with
  focused data.
- The gain is narrow.
- It regresses insufficient-evidence behavior on the broader heldout.
- It does not improve the clean workflow guard.

## 4. System Guard Interpretation

`clean6` is a six-case full workflow guard. It exercises:

```text
question -> query rewrite -> hybrid retrieval -> reranker -> evidence board
-> Qwen AnswerPolicy -> v3 refs -> citation mapping -> final case report
```

It is not the SFT training target and should not be used as the primary measure
of whether AnswerPolicy v3 learned the intended contract. Its role is deployment
safety: a checkpoint that regresses these clean full-workflow cases should not
become the default production checkpoint without further review.

Current clean6 signal:

- base Qwen path: 6/6 in the recorded guard;
- promptfix adapter: 4/6;
- promptfix-based 377-record rejection continuation: 2/6 in the compared
  clean6 guard, while preserving 6/6 citation page hits and workflow execution;
- tablecalc continuation: 4/6.

Therefore, the promptfix adapter is suitable as the SFT anchor for post-training
preparation, but not yet accepted as the default production AnswerPolicy.

## 5. Current SFT Decision

Use this checkpoint as the current SFT anchor:

```text
answer_policy_v3_msswift_stage2_promptfix3840_1024steps_20260705
```

Do not continue open-ended LoRA tuning at this point.

Allowed SFT adjustment boundary:

- at most one future bounded refresher SFT run if post-training preparation
  reveals a broad contract regression that can be fixed by data balance;
- it must use train-only data;
- it must preserve or improve insufficient behavior;
- it must compare against the promptfix checkpoint on the heldout256 split;
- it must not be driven by clean6 case-specific repairs.

No further SFT run is required before beginning post-training preparation.

## 6. Next Training Stage

Proceed from the frozen promptfix SFT checkpoint into bounded post-training
preparation:

1. Generate real-model candidate answers from the promptfix checkpoint on a
   train-only subset of the v3 mixed pack.
2. Score candidates with the existing calibrated v3 reward.
3. Build rejection-sampling artifacts:
   - ranked candidates;
   - selected candidates;
   - rejection-SFT candidates;
   - preference pairs when quality separation is strong enough.
4. Run a small rejection-SFT or DPO readiness decision from those artifacts.
5. Do not run GRPO until reward calibration and candidate-quality separation
   are strong enough.

Current post-training result:

- bounded rejection-SFT from the promptfix checkpoint is executable;
- the 377-record continuation improved heldout256 answer exact from 0.5859 to
  0.6016 and restored JSON/schema/ref legality plus insufficient empty-ref
  behavior to 1.0;
- positive-ref hit moved slightly down from 0.9407 to 0.9367, so this remains
  a candidate checkpoint rather than a final default;
- two 256-row candidate slices produced 377 training-ready rejection-SFT rows
  but only 44 training-ready preference pairs.

Therefore, the next step is not DPO/GRPO. The 377-record continuation can be
used as the current post-training candidate for further fixed-evidence or
system-chain diagnostics, but default deployment remains blocked by the clean6
guard. If post-training continues, change the candidate-generation or ranking
strategy in a bounded way and require stronger train-only preference-pair
coverage before any DPO decision. GRPO remains optional and gated.

GPU boundary:

- real candidate generation from Qwen + LoRA requires the AutoDL GPU mode;
- no-card mode can still inspect artifacts, prepare documents, and run
  deterministic scripts, but it cannot advance model-backed post-training
  candidate generation or SFT/RL execution;
- when the server is in no-card mode, pause before candidate generation and
  resume after the user switches the server to GPU mode.

## 7. Stop Rules

Stop SFT tuning unless one of these is true:

- the frozen promptfix checkpoint cannot generate valid v3 outputs under the
  post-training candidate-generation path;
- reward-calibrated candidates show systematic prompt-contract failure;
- a bounded data-balance correction is needed and can be verified on train-only
  heldout without regressions.

Stop post-training escalation before DPO/GRPO if:

- preference pairs are too few or low-confidence;
- reward scores do not separate target-like and bad candidates;
- insufficient-evidence behavior regresses;
- candidate improvements are limited to one narrow slice.
