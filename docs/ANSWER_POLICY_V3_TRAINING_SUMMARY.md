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

High-diversity candidate generation was then tested from the 377-record
continuation checkpoint:

```text
answer_policy_v3_candidates_rejection377_temp095_train64x8_offset512_20260705
answer_policy_v3_candidates_rejection377_temp095_train192x8_offset576_20260705
answer_policy_v3_rejection_rejection377_temp095_train64x8_offset512_20260705
answer_policy_v3_rejection_rejection377_temp095_train192x8_offset576_20260705
```

The strategy used `temperature=0.95`, `top_p=0.97`, and 8 candidates per
record over 256 additional train-only records. It produced 2048 candidates,
201 rejection-SFT records, and 26 training-ready preference pairs. Schema
validity stayed high, but preference-pair coverage remained too low for DPO.

A second bounded continuation used those 201 high-diversity rejection-SFT
records:

```text
answer_policy_v3_rejection_sft_temp095_201records_52steps_20260705
```

This continued from the 377-record checkpoint for 52 ms-swift steps and ended
with `train_loss=0.01452`. Heldout256 comparison:

| Metric | Promptfix | 377-record continuation | temp0.95 continuation |
|---|---:|---:|---:|
| json_valid_rate | 0.9961 | 1.0000 | 1.0000 |
| schema_valid_rate | 0.9961 | 1.0000 | 1.0000 |
| answer_exact_rate | 0.5859 | 0.6016 | 0.6055 |
| support_status_match_rate | 0.9727 | 0.9766 | 0.9766 |
| supporting_refs_subset_rate | 0.9961 | 1.0000 | 1.0000 |
| positive_ref_hit_rate | 0.9407 | 0.9367 | 0.9409 |
| insufficient_ref_empty_rate | 0.9474 | 1.0000 | 0.9474 |
| thinking_rate | 0.0000 | 0.0000 | 0.0000 |

Compared with the frozen promptfix checkpoint, the temp0.95 continuation had
13 answer improvements and 8 regressions. Compared with the 377-record
continuation, it had 5 improvements and 4 regressions, with answer exact and
positive-ref hit slightly higher but insufficient empty-ref behavior lower.

Clean6 guard:

```text
phase5ib_v3refs_clean6_temp095_rejection201_20260705
phase5ib_v3refs_clean6_promptfix1024_vs_temp095_rejection201_20260705
phase5ib_v3refs_clean6_rejection377_vs_temp095_rejection201_20260705
```

The checkpoint preserved full workflow execution, JSON/artifact output, and
6/6 citation page hits. It matched the compared promptfix/adapter clean6 pass
count at 3/6 and improved over the 377-record continuation's 2/6, but the
deployment gate still requires broader evaluation because clean6 remains a
small guard and candidate regressions are present.

Decision:

```text
keep the temp0.95 201-record continuation as the strongest current
post-training candidate for fixed-evidence metrics; do not promote as default;
do not start DPO/GRPO
```

Follow-up bounded DPO readiness work expanded candidate coverage from the
temp0.95 checkpoint:

```text
answer_policy_v3_candidates_temp095_train512x8_offset768_20260705
answer_policy_v3_rejection_temp095_train512x8_offset768_20260705
```

This used 512 additional train-only records, 8 candidates per record,
`temperature=0.95`, and `top_p=0.97`. It produced:

| Artifact | Count |
|---|---:|
| model candidates | 4096 |
| schema-valid candidates | 3693 |
| rejection-SFT records | 402 |
| training-ready preference pairs | 131 |

The preference-pair count was enough for a small DPO smoke, so the DPO
entrypoint was added and verified:

```text
answer_policy_v3_dpo_temp095_pairs128_16steps_20260705
```

It trained for 16 ms-swift DPO steps on 128 train-only preference pairs from
the temp0.95 checkpoint. Heldout256 comparison against the temp0.95 checkpoint:

| Metric | temp0.95 continuation | DPO 16-step |
|---|---:|---:|
| json_valid_rate | 1.0000 | 1.0000 |
| schema_valid_rate | 1.0000 | 1.0000 |
| answer_exact_rate | 0.6055 | 0.5977 |
| support_status_match_rate | 0.9766 | 0.9766 |
| supporting_refs_subset_rate | 1.0000 | 1.0000 |
| positive_ref_hit_rate | 0.9409 | 0.9409 |
| insufficient_ref_empty_rate | 0.9474 | 0.9474 |

Row movement had zero improvements and two regressions. This verifies the
ms-swift DPO training entrypoint and data format, but it does not improve the
current checkpoint.

Decision:

```text
do not promote the DPO checkpoint; do not continue DPO tuning unless stronger
train-only preference-pair coverage or a clearer reward/data strategy is added
```

### 3.4 Temp0.95 rejection-SFT continuation

Because the DPO smoke regressed the fixed-evidence heldout objective, the same
train-only candidate pool was used for one bounded rejection-SFT continuation
instead of further preference optimization:

```text
answer_policy_v3_rejection_sft_temp095_402records_96steps_20260705
```

This run continued from the temp0.95 checkpoint on 402 train-only
rejection-SFT records for 96 ms-swift steps. It ended with
`train_loss=0.02247`. Heldout256 comparison against the temp0.95 checkpoint:

| Metric | temp0.95 continuation | 402-record rejection-SFT |
|---|---:|---:|
| json_valid_rate | 1.0000 | 1.0000 |
| schema_valid_rate | 1.0000 | 1.0000 |
| answer_exact_rate | 0.6055 | 0.6133 |
| support_status_match_rate | 0.9766 | 0.9805 |
| supporting_refs_subset_rate | 1.0000 | 1.0000 |
| positive_ref_hit_rate | 0.9409 | 0.9409 |
| insufficient_ref_empty_rate | 0.9474 | 1.0000 |
| thinking_rate | 0.0000 | 0.0000 |

Row movement was net positive, with 10 candidate improvements and 8
regressions. The small system-chain gate
`final_delivery_gate_temp095_rejsft402_v3refs_system_subset_20260705` then ran
readiness, AnswerPolicy baseline, and MP-DocVQA full workflow diagnostics with
the new checkpoint and `answer_output_contract=v3_refs`; review
`final_delivery_gate_temp095_rejsft402_v3refs_system_subset_20260705_review`
verified manifests, safety flags, complete component metrics, and observed
`v3_refs` contracts. MP-DocVQA workflow execution remained healthy
(`cli_success_rate=1.0`, 8/8 Qwen/BGE/reranker/query-rewriter component use,
retrieved/citation page-hit rates 0.875). This is system compatibility
evidence, not formal benchmark acceptance.

Decision:

```text
freeze the 402-record rejection-SFT checkpoint as the strongest current
fixed-evidence/post-training SFT candidate; do not promote as default
production AnswerPolicy; do not continue DPO/GRPO without stronger preference
data or a new approved reward strategy
```

Follow-up candidate expansion from this 402-record checkpoint was used as a
stop-condition check, not as open-ended tuning:

```text
answer_policy_v3_candidates_rejsft402_temp095_train256x8_offset1280_20260705
answer_policy_v3_rejection_rejsft402_temp095_train256x8_offset1280_20260705
answer_policy_v3_rejection_sft_rejsft402_offset1280_195records_48steps_20260705
```

The fresh 256-row train-only slice produced 2048 candidates with schema-ok
rate 0.9990, 195 rejection-SFT records, but only 32 training-ready preference
pairs. This still does not justify DPO. A bounded 48-step rejection-SFT
continuation on the 195 rows regressed heldout256 against the 402-record
checkpoint:

| Metric | 402-record checkpoint | 195-record continuation |
|---|---:|---:|
| json_valid_rate | 1.0000 | 0.9922 |
| schema_valid_rate | 1.0000 | 0.9922 |
| answer_exact_rate | 0.6133 | 0.6016 |
| support_status_match_rate | 0.9805 | 0.9648 |
| supporting_refs_subset_rate | 1.0000 | 0.9922 |
| positive_ref_hit_rate | 0.9409 | 0.9277 |
| insufficient_ref_empty_rate | 1.0000 | 1.0000 |

Row movement was 11 improvements and 14 regressions. This triggers the
post-training stop condition for this branch: keep the 402-record checkpoint
and do not keep adding rejection-SFT steps from the current candidate recipe.

### 3.5 Custom GRPO bounded probes

Custom GRPO was then tried from the 402-record rejection-SFT checkpoint as a
bounded post-training probe:

```text
answer_policy_v3_grpo_smoke4_ng2_from_rejsft402_20260705
answer_policy_v3_grpo_variance_probe8_ng3_temp12_20260705
```

The first run used 64 selected train-only records, 4 update steps, and 2
generations per prompt. It completed successfully, but every group had identical
rewards:

```text
nonzero_reward_std_steps = 0
```

Therefore all advantages and losses were effectively zero. Heldout256
comparison against the 402-record checkpoint was identical:

| Metric | 402-record checkpoint | GRPO smoke4 |
|---|---:|---:|
| answer_exact_rate | 0.6133 | 0.6133 |
| support_status_match_rate | 0.9805 | 0.9805 |
| supporting_refs_subset_rate | 1.0000 | 1.0000 |
| positive_ref_hit_rate | 0.9409 | 0.9409 |
| insufficient_ref_empty_rate | 1.0000 | 1.0000 |

Row movement was 0 improvements and 0 regressions. This verifies execution
plumbing only; it is not a learning result.

The second run increased sampling diversity with `num_generations=3`,
`temperature=1.2`, `top_p=0.95`, 8 update steps, and a low learning rate. It
produced nonzero reward variance on 3/8 steps, mostly on MP-DocVQA supported
records, so the GRPO objective did receive a real advantage signal. Heldout256
comparison still regressed:

| Metric | 402-record checkpoint | GRPO variance probe |
|---|---:|---:|
| answer_exact_rate | 0.6133 | 0.6055 |
| support_status_match_rate | 0.9805 | 0.9805 |
| supporting_refs_subset_rate | 1.0000 | 1.0000 |
| positive_ref_hit_rate | 0.9409 | 0.9409 |
| insufficient_ref_empty_rate | 1.0000 | 1.0000 |

Row movement was 0 improvements and 2 regressions.

Decision:

```text
do not promote either GRPO checkpoint
```

Rationale:

- The 2-generation smoke had no reward variance, so it could not learn.
- The diversity probe created reward variance, but the heldout delta was
  negative.
- Continuing the same recipe by adding steps would be open-ended tuning rather
  than a justified training-plan stage.
- The 402-record rejection-SFT checkpoint remains the strongest current
  fixed-evidence/post-training candidate.

### 3.6 Table/calculation continuation diagnostic

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
- temp0.95 201-record continuation: 3/6, preserving 6/6 citation page hits and
  workflow execution;
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
- the temp0.95 continuation improved heldout256 answer exact further to 0.6055
  and restored positive-ref hit to 0.9409, but insufficient empty-ref behavior
  returned to the promptfix level of 0.9474;
- two 256-row candidate slices produced 377 training-ready rejection-SFT rows
  but only 44 training-ready preference pairs.
- a later 512-row temp0.95 candidate slice produced 131 training-ready
  preference pairs and enabled a 16-step DPO smoke, but the DPO checkpoint
  regressed heldout256 answer exact 0.6055 -> 0.5977 with no improvement rows.
- the 402-record rejection-SFT continuation is the strongest current
  fixed-evidence/post-training candidate, with heldout256 answer exact 0.6133,
  support-status match 0.9805, and insufficient empty-ref behavior 1.0.
- bounded custom GRPO probes from that checkpoint either had zero reward
  variance or regressed heldout256 to 0.6055, so GRPO is not promoted.

Therefore, the next step is not more DPO/GRPO tuning under the current recipe.
Default deployment remains unapproved. If post-training continues, it should
first improve train-only preference-data quality, reward separation, or GRPO
hard-sample selection; simply adding DPO/GRPO steps from the current artifacts
is not justified.

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
