# AnswerPolicy v3 First Training Report

> Scope: first expanded AnswerPolicy v3 SFT diagnostic with ms-swift.
> This report summarizes train-only data construction, training execution,
> heldout evaluation, and system-chain smoke evidence. It is not a formal
> MP-DocVQA/TAT-QA benchmark acceptance report.

## 1. Conclusion

The first expanded AnswerPolicy v3 SFT run was successful as a training-method
validation step.

It proved that the current contract

```json
{
  "answer": "...",
  "supporting_refs": ["E2"],
  "support_status": "supported|insufficient",
  "reasoning_summary": "..."
}
```

can be trained with ms-swift LoRA on mixed train-only data, loaded back as a
PEFT adapter, evaluated on a heldout split, and routed through the real
DocAgent CLI using `--answer-output-contract v3_refs`.

The trained checkpoint improved all primary heldout contract metrics over the
same Qwen3-1.7B base model:

| Metric | Base | 480-step adapter | Delta |
|---|---:|---:|---:|
| JSON valid rate | 0.9766 | 1.0000 | +0.0234 |
| Schema valid rate | 0.9688 | 1.0000 | +0.0313 |
| Answer exact rate | 0.3516 | 0.5938 | +0.2422 |
| Support status match rate | 0.8828 | 0.9844 | +0.1016 |
| Supporting refs subset rate | 0.9766 | 1.0000 | +0.0234 |
| Positive ref hit rate | 0.6814 | 0.9138 | +0.2324 |
| Insufficient empty-ref rate | 0.0000 | 0.9167 | +0.9167 |
| Thinking tag rate | 0.0000 | 0.0000 | +0.0000 |

This is meaningful evidence that SFT improves the intended AnswerPolicy v3
behavior. It is still diagnostic evidence only. It does not approve GRPO, does
not use validation/final-eval data for training, and does not establish formal
final answer-quality benchmark acceptance.

A follow-up real workflow comparison over 8 Phase 5I cases did not show a
system-level pass-rate gain from the 480-step adapter. The adapter preserved
format and citation validity, but did not improve the small-scenario final
answer-quality outcome. This means the first SFT run is validated as a contract
and train-only heldout improvement, but it is not yet validated as a full
workflow answer-quality improvement.

A later clean fixed-evidence contract probe over 6 curated Phase 5I cases made
the boundary sharper: the Qwen3-1.7B base model passed 6/6, while the 480-step
adapter passed 3/6 on the same clean evidence-board workflow. Both paths kept
JSON/citation/location validity at 1.0. This confirms the v3 system contract is
usable, but the 480-step adapter should not be promoted over the base model for
the current full workflow without stronger clean-probe or heldout evidence.

## 2. Data Construction

### MP-DocVQA Train Materialization

Run:

```text
mpdocvqa_train_evidence_api_400_reuse233_20260704
```

Artifact:

```text
outputs/training_prep/mpdocvqa_train_evidence/mpdocvqa_train_evidence_api_400_reuse233_20260704/summary.json
```

Summary:

| Item | Value |
|---|---:|
| Document windows requested | 400 |
| Document windows passed | 400 |
| Document windows failed | 0 |
| QA samples | 1469 |
| Evidence-ready QA samples | 1467 |
| Evidence-ready rate | 0.9986 |
| Answer text gold-page hit count | 1238 |
| Answer text gold-page hit rate | 0.8428 |
| Reused previous passed windows | 233 |
| Newly retried/parsed windows | 167 |
| MinerU API/OCR used | true |

The command-level status was `failed` only because 2 QA samples were marked
`evidence_not_ready`. Document parsing itself succeeded for 400/400 windows.

### MP-DocVQA v3 SFT Conversion

Run:

```text
answer_policy_v3_mpdocvqa_train_400docs_20260704
```

Artifact:

```text
outputs/training_prep/answer_policy_v3/answer_policy_v3_mpdocvqa_train_400docs_20260704/summary.json
```

Summary:

| Item | Value |
|---|---:|
| Aligned records | 1037 |
| SFT records | 1037 |
| Rejected records | 432 |
| Accepted bucket | evidence_extractive_supported |

Rejected records were not forced into training.

### Mixed SFT Pack

Run:

```text
answer_policy_v3_mixed_stage2_2048_mp400_20260704
```

Artifact:

```text
outputs/training_prep/answer_policy_v3/answer_policy_v3_mixed_stage2_2048_mp400_20260704/summary.json
```

Input availability:

| Source | Valid records |
|---|---:|
| MP-DocVQA supported | 1037 |
| TAT-QA supported/tool | 13137 |
| TAT-QA insufficient | 13005 |

Selected pack:

| Bucket | Count |
|---|---:|
| evidence_extractive_supported | 1432 |
| deterministic_tool_supported | 411 |
| insufficient_confirmed | 205 |
| Total | 2048 |

Dataset split:

Run:

```text
answer_policy_v3_mixed_stage2_2048_mp400_split128_20260704
```

| Split | Total | MP-DocVQA | TAT-QA |
|---|---:|---:|---:|
| Train | 1920 | 958 | 962 |
| Heldout | 128 | 66 | 62 |
| Excluded | 0 | 0 | 0 |

The split reported `overlap_count=0`.

## 3. Training Execution

Run:

```text
answer_policy_v3_msswift_stage2_1920_steps480_20260704
```

Artifacts:

```text
outputs/training/answer_policy_v3_msswift_sft/answer_policy_v3_msswift_stage2_1920_steps480_20260704/result.json
outputs/training/answer_policy_v3_msswift_sft/answer_policy_v3_msswift_stage2_1920_steps480_20260704/swift_command.json
```

Training configuration:

| Item | Value |
|---|---|
| Base model | `/root/autodl-tmp/models/Qwen3-1.7B` |
| Backend | ms-swift 4.2.3 |
| Method | LoRA |
| Selected records | 1920 |
| Train source counts | MP-DocVQA 958, TAT-QA 962 |
| `max_steps` | 480 optimizer update steps |
| Per-device train batch size | 1 |
| Gradient accumulation steps | 8 |
| Learning rate | `8e-05` |
| Max length | 2048 |
| Torch dtype | bfloat16 |
| LoRA rank | 8 |
| LoRA alpha | 16 |
| Save steps | 480 |
| Duration | 885.128 seconds |

Checkpoint:

```text
outputs/training/answer_policy_v3_msswift_sft/answer_policy_v3_msswift_stage2_1920_steps480_20260704/swift_output/v0-20260704-193705/checkpoint-480
```

`max_steps=480` is the number of optimizer update steps, not an epoch count.

Safety flags:

```text
used_training = true
formal_benchmark_acceptance = false
validation_subset_used_for_training = false
```

## 4. Heldout Evaluation

Heldout file:

```text
outputs/training_prep/answer_policy_v3_sft_split/answer_policy_v3_mixed_stage2_2048_mp400_split128_20260704/heldout_eval.jsonl
```

Base run:

```text
answer_policy_v3_base_only_heldout128_mp400_eval_20260704
```

Adapter run:

```text
answer_policy_v3_msswift_stage2_1920_steps480_heldout128_eval_20260704
```

Both evaluated 128 heldout records. The base run used Qwen3-1.7B without an
adapter. The adapter run used the 480-step PEFT checkpoint.

### Metric Interpretation

The main improvements are aligned with the intended training target:

- JSON/schema stability reached 1.0.
- Answer exact rate improved materially.
- The model became much better at selecting valid supporting evidence refs.
- The model learned the `insufficient` behavior: insufficient cases should
  produce empty `supporting_refs` instead of fake citations.
- No `<think>` leakage was observed in either run.

The heldout split is train-source heldout data, not a formal benchmark split.
It is useful for training-method validation, but should not be reported as
public benchmark performance.

## 5. System-Chain Smoke

Run:

```text
phase5ib_v3refs_400doc_checkpoint_cli_smoke_20260704
```

Artifact:

```text
outputs/benchmark/phase5i_answer_quality/phase5ib_v3refs_400doc_checkpoint_cli_smoke_20260704/phase5i_summary.json
```

This smoke ran 2 Phase 5I full-model cases through:

```text
run_phase5i_answer_quality_benchmark.py
-> docagent_cli.py
-> LLM query rewriting
-> BGE-M3 retrieval
-> cross-encoder reranking
-> Qwen3-1.7B + checkpoint-480
-> answer_output_contract=v3_refs
```

Observed:

| Item | Value |
|---|---:|
| Case count | 2 |
| Qwen AnswerPolicy used | 2 |
| LLM query rewriter used | 2 |
| Answer output contract | v3_refs |
| Passed | 0 |
| Failed | 2 |

Failure reasons:

```text
answer_keyword_missing: 2
citation_page_mismatch: 1
```

The smoke confirms that the trained checkpoint can enter the real system path.
The failures are answer/citation quality diagnostics, not execution-chain
blockers.

## 6. System-Level Base vs Adapter Comparison

Run:

```text
answer_policy_v3_system_compare_base_vs_adapter480_8cases_20260704_pathfix
```

Artifacts:

```text
outputs/final_eval/answer_policy_v3_system_compare/answer_policy_v3_system_compare_base_vs_adapter480_8cases_20260704_pathfix/result.json
outputs/sync/answer_policy_v3_system_compare_base_vs_adapter480_8cases_20260704_pathfix/
```

The comparison used the same 8 Phase 5I selected-context workflow cases for the
Qwen3-1.7B base model and the 480-step v3 adapter. Both paths used the real
workflow stack:

```text
docagent_cli.py
-> LLM query rewriting
-> BGE-M3 retrieval
-> cross-encoder reranking
-> Qwen AnswerPolicy
-> answer_output_contract=v3_refs
```

Observed:

| Metric | Base | 480-step adapter | Delta |
|---|---:|---:|---:|
| Case count | 8 | 8 | 0 |
| Passed count | 2 | 2 | 0 |
| Failed count | 6 | 6 | 0 |
| Answer correct rate | 0.125 | 0.000 | -0.125 |
| Format valid rate | 1.000 | 1.000 | 0 |
| Citation valid rate | 1.000 | 1.000 | 0 |
| Location valid rate | 0.750 | 0.750 | 0 |
| Qwen AnswerPolicy used | 7 | 7 | 0 |
| LLM query rewriter used | 7 | 7 | 0 |

Case-level movement:

| Change | Count |
|---|---:|
| Improved | 0 |
| Regressed | 0 |
| Unchanged passed | 2 |
| Unchanged failed | 6 |

Failure reasons remained concentrated in:

```text
answer_keyword_missing
citation_page_mismatch
downstream_answer_not_evaluated
```

Interpretation:

- The v3 adapter can run through the real system path.
- The v3 adapter improves the train-only heldout contract metrics.
- The same adapter does not yet improve this small real workflow answer-quality
  probe.
- Increasing steps blindly is not justified by this comparison.
- Before more training, inspect whether remaining failures are caused by
  retrieval/context selection, benchmark keyword expectations, citation
  packaging, or AnswerPolicy generation.

Follow-up read-only failure inspection:

```text
answer_policy_v3_system_failure_inspect_base_vs_adapter480_8cases_20260704
```

Bucket counts:

| Bucket | Count |
|---|---:|
| already_passed | 2 |
| answer_generation_or_keyword_metric | 4 |
| citation_or_expected_page_alignment | 2 |

The inspection did not call Qwen or start training. It showed that the remaining
failures are mixed:

- Some rows have correct-page citations but fail keyword checks where expected
  keywords are coarse labels such as `date` or `%`, so the current diagnostic
  metric is not always a precise measure of answer usefulness.
- Two rows cite page 1 while the scenario expects page 24, indicating an
  evidence/page-alignment or scenario-definition issue rather than a pure SFT
  optimization target.

This reinforces the stop condition: do not increase SFT steps or start GRPO
based on these 8 workflow rows. First build or select a cleaner system-level
answer-quality evaluation target, or fix generic evidence/citation packaging if
the failure is confirmed to be a reusable system defect.

## 7. Clean Fixed-Evidence Contract Probe

Runs:

```text
phase5ib_v3refs_clean6_base_contract_probe_20260704
phase5ib_v3refs_clean6_adapter480_contract_probe_20260704
phase5ib_v3refs_clean6_base_vs_adapter480_contract_compare_20260704
phase5ib_v3refs_clean6_base_vs_adapter480_boundaryfix_20260704
```

Artifacts:

```text
outputs/final_eval/phase5i_answer_quality_compare/phase5ib_v3refs_clean6_base_vs_adapter480_contract_compare_20260704/result.json
outputs/sync/phase5ib_v3refs_clean6_base_vs_adapter480_contract_compare_20260704/
outputs/final_eval/phase5i_answer_quality_compare/phase5ib_v3refs_clean6_base_vs_adapter480_boundaryfix_20260704/summary.json
outputs/sync/phase5ib_v3refs_clean6_base_vs_adapter480_boundaryfix_20260704/
```

The clean pack was built from curated cases validated against persisted
EvidenceBlocks in `outputs/docagent.db` / `c1fc1c5e040ec894`. Both base and
adapter probes used the same real system stack:

```text
accepted clean cases
-> LLM query rewriting
-> BGE-M3 retrieval
-> cross-encoder reranking
-> Qwen AnswerPolicy
-> answer_output_contract=v3_refs
```

Observed:

| Metric | Base | 480-step adapter | Delta |
|---|---:|---:|---:|
| Case count | 6 | 6 | 0 |
| Passed count | 6 | 3 | -3 |
| JSON valid count | 6 | 6 | 0 |
| Citation page hit count | 6 | 6 | 0 |
| Answer keyword hit count | 6 | 4 | -2 |
| Evidence keyword hit count | 6 | 5 | -1 |
| Answer correct rate | 1.0000 | 0.6667 | -0.3333 |
| Format valid rate | 1.0000 | 1.0000 | 0 |
| Citation valid rate | 1.0000 | 1.0000 | 0 |
| Location valid rate | 1.0000 | 1.0000 | 0 |

Case-level movement:

| Change | Count |
|---|---:|
| Both passed | 3 |
| Adapter regressed | 3 |
| Adapter improved | 0 |
| Both failed | 0 |

Interpretation:

- The clean fixed-evidence probe is a better controlled signal than the earlier
  default Phase 5I cases, because the evidence board was validated before model
  execution.
- The result does not test retrieval improvement or model knowledge gain; it
  tests the AnswerPolicy contract inside a complete system path.
- The promotion gate is a default-deployment regression guard. It does not
  judge whether the SFT training objective improved.
- Training effectiveness should be judged with the predefined v3 objective
  metrics on train-only heldout or fixed-evidence probes: JSON/schema legality,
  legal `supporting_refs`, `support_status`, positive evidence-ref hit,
  concise grounded reasoning, and insufficient-evidence behavior.
- Real workflow diagnostics are still necessary, but their role is to check
  whether the intended system processing flow is followed: retrieval, evidence
  mapping, citation packaging, and answer generation. They should not be
  reduced to "did the final answer string match" when retrieval/context or
  gold/metric issues may dominate.
- The 480-step adapter should not be promoted as the default AnswerPolicy for
  current CLI workflow use.
- More SFT steps or GRPO are not justified by this signal alone. If further
  training is attempted, it should first diagnose why the adapter regressed on
  clean evidence despite improving train-only heldout contract metrics.

## 8. Follow-Up Expanded v3 Training

Later Stage 2 expansion completed the full MP-DocVQA train-window
materialization and trained a larger mixed AnswerPolicy v3 SFT checkpoint:

```text
mpdocvqa_train_evidence_api_848_resume400_20260705
answer_policy_v3_mixed_stage2_full4096_20260705
answer_policy_v3_msswift_stage2_full4096_1024steps_20260705
```

The materialization processed 848/848 MP-DocVQA train document windows with
live MinerU API/OCR. The resulting train-only v3 sources provided 2156
MP-DocVQA supported records, 2000 MP-DocVQA insufficient records, 5000 TAT-QA
supported records, and 2000 TAT-QA insufficient records. The mixed Stage 2 pack
selected 4096 records with no shortage/backfill: 2048 MP-DocVQA supported,
1638 TAT-QA supported, and 410 insufficient records.

The 1024-step ms-swift LoRA run wrote checkpoint:

```text
outputs/training/answer_policy_v3_msswift_sft/answer_policy_v3_msswift_stage2_full4096_1024steps_20260705/swift_output/v0-20260705-033450/checkpoint-1024
```

The follow-up rejection-SFT continuation run selected 222 train-only
rejection-SFT rows and continued from the 1024-step adapter for 56 update
steps:

```text
answer_policy_v3_rejection_sft_full4096_adapter_56steps_20260705
```

Full 256-record train-only heldout comparison:

```text
answer_policy_v3_full4096_mixed_heldout256_compare_20260705
```

| Metric | 1024-step adapter | Rejection continuation | Delta |
|---|---:|---:|---:|
| JSON valid rate | 0.9922 | 0.9961 | +0.0039 |
| Schema valid rate | 0.9922 | 0.9961 | +0.0039 |
| Answer exact rate | 0.6484 | 0.6680 | +0.0195 |
| Support status match rate | 0.9844 | 0.9883 | +0.0039 |
| Supporting refs subset rate | 0.9922 | 0.9961 | +0.0039 |
| Positive ref hit rate | 0.9536 | 0.9622 | +0.0086 |
| Insufficient empty-ref rate | 0.9412 | 0.9412 | 0.0000 |

Source-level movement:

| Source/status | 1024-step answer exact | Continued answer exact | Delta |
|---|---:|---:|---:|
| MP-DocVQA supported | 0.4361 | 0.4812 | +0.0451 |
| TAT-QA supported | 0.8679 | 0.8585 | -0.0094 |
| TAT-QA insufficient | 0.9412 | 0.9412 | 0.0000 |

Interpretation:

- The continuation checkpoint shows a modest aggregate gain and a clearer
  MP-DocVQA-supported gain on train-only heldout data.
- It does not show a broad v3 contract regression.
- The small TAT-QA supported answer-exact dip means the checkpoint remains a
  candidate checkpoint, not a default deployment choice.
- This still does not approve DPO/GRPO or formal benchmark acceptance.

Clean fixed-evidence workflow probes were also rerun for both later
checkpoints:

```text
phase5ib_v3refs_clean6_full4096_adapter1024_20260705
phase5ib_v3refs_clean6_rejection_continue56_20260705
phase5ib_v3refs_clean6_base_vs_full4096_adapter1024_20260705
phase5ib_v3refs_clean6_base_vs_rejection_continue56_20260705
phase5ib_v3refs_clean6_full4096_vs_rejection_continue56_20260705
```

| Clean6 run | Passed | Format | Citation | Location |
|---|---:|---:|---:|---:|
| Base Qwen3-1.7B | 6/6 | 1.0000 | 1.0000 | 1.0000 |
| 1024-step full4096 adapter | 3/6 | 1.0000 | 1.0000 | 1.0000 |
| Rejection-continuation adapter | 3/6 | 1.0000 | 1.0000 | 1.0000 |

The default-deployment gate remains blocked for both adapters because each
regressed three clean cases relative to the base run. The rejection continuation
matched the 1024-step adapter on this clean workflow signal; it did not improve
system-level pass count. This does not contradict the train-only heldout gain:
it reinforces that current SFT improves the intended v3 evidence-output
contract more reliably than it improves the small clean workflow answer-quality
guard.

Read-only failure attribution:

```text
phase5ib_v3refs_clean6_checkpoint_failure_attribution_20260705
```

The attribution found 3 `both_adapters_regress_from_base` rows and 3 `all_pass`
rows. The regressed rows still had successful `hybrid_rerank` retrieval and
citation-page hits, so they are not evidence of a broken execution chain. The
generic pattern is AnswerPolicy table/value selection from a correct-page
evidence board. This should be addressed, if pursued, through broader
fixed-evidence table/value-selection training or evaluation design, not through
clean6-specific prompt rules.

## 9. Limitations

1. This was a diagnostic SFT run, not a final production SFT acceptance run.
2. The heldout set came from the generated train-source pack, not validation or
   final-evaluation data.
3. The system-chain smoke used only 2 cases and did not show answer-quality
   success in the full workflow.
4. The 8-case base-vs-adapter system comparison also did not show a pass-rate
   gain, so the current checkpoint should not be treated as a system-quality
   improvement checkpoint.
5. The 6-case clean fixed-evidence comparison showed base outperforming the
   480-step adapter on current full-workflow answer quality.
6. The later MP-DocVQA expansion processed 848/848 train document windows, but
   the resulting heldout diagnostics remain train-source diagnostics rather
   than formal benchmark acceptance.
7. No GRPO, DPO, or best-of-N distillation was approved by this run.
8. Pixel-level VLM image reasoning remains out of scope for this training run.

## 10. Decision

This first training run should be treated as a successful AnswerPolicy v3 SFT
method validation:

```text
status = real_model_verified
scope = train-only heldout diagnostic + system-chain integration smoke
formal_benchmark_acceptance = false
validation_subset_used_for_training = false
grpo_approved = false
```

Recommended next step:

```text
Do not promote either the 480-step adapter or the 56-step rejection-continuation
adapter as the default full-workflow AnswerPolicy from heldout evidence alone.
Keep DPO/GRPO unapproved. Treat the 1024-step full4096 adapter and its
rejection-continuation checkpoint as candidate checkpoints for targeted
fixed-evidence/system-chain diagnostics, or continue bounded train-only
candidate distillation if the next experiment has a clear acceptance gate.
```

Do not tune against the two failed CLI smoke cases individually.
