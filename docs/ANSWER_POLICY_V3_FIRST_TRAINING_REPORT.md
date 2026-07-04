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

## 6. Limitations

1. This was a diagnostic SFT run, not a final production SFT acceptance run.
2. The heldout set came from the generated train-source pack, not validation or
   final-evaluation data.
3. The system-chain smoke used only 2 cases and did not show answer-quality
   success in the full workflow.
4. MP-DocVQA materialization stopped at 400 document windows by design; the
   remaining train windows are available for later expansion.
5. No GRPO, DPO, or best-of-N distillation was approved by this run.
6. Pixel-level VLM image reasoning remains out of scope for this training run.

## 7. Decision

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
Run a controlled adapter-vs-base system-level comparison on a larger small
set, using the same v3_refs contract and real workflow path, before scaling
training or starting reward-based post-training.
```

Do not tune against the two failed CLI smoke cases individually.
