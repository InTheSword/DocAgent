# Phase 5I-B Model-backed Answer Quality Baseline

## Status

```text
status = skipped_api_missing
resource_boundary = server_optional
branch = phase5/phase5i-b-model-answer-quality
runner = scripts/run_phase5i_b_model_answer_quality.py
scenario_set = data/scenario_sets/phase5i_b/phase5i_b_cases.jsonl
```

The local implementation, fake-policy test path, schema validation, metrics,
failure taxonomy, and artifact contract are implemented. The real
OpenAI-compatible API smoke was not executed because `.secrets/answer_policy.env`
is missing.

## Scenario Set

```text
case_count = 14
extractive_count = 12
refusal_count = 2
zh_question_count = 2
en_question_count = 12
optional_real_doc_count = 0
```

The P0 scenario set uses a committed `.txt` fixture document so local tests are
reproducible without large datasets, MinerU, GPU models, or external APIs.

## Runner

The runner uses a product-equivalent internal path:

```text
scenario case
-> DocumentIngestionService / DocumentRepository
-> rule Router
-> optional rule Query Planner / BM25 IndexedDocumentRetriever
-> local_fact_qa
-> explicitly injected AnswerPolicy.generate
-> format, citation, location, answer-quality, failure-taxonomy evaluation
-> artifacts
```

It does not modify Phase 5I-A evidence-readiness semantics.

## Artifacts

Default output root:

```text
outputs/phase5i_b_model_answer_quality/
```

Files:

```text
acceptance_report.json
metrics.json
predictions.jsonl
case_reports.jsonl
failure_analysis.md
training_candidates_raw.jsonl
model_config_masked.json
scenario_snapshot.jsonl
cli_artifacts/<case_id>/
```

## API Configuration

Real model-backed execution requires:

```text
--allow-external-api
--answer-policy-provider openai_compatible
--answer-policy-env-file .secrets/answer_policy.env
```

Expected env keys:

```text
DOCAGENT_ANSWER_BASE_URL
DOCAGENT_ANSWER_API_KEY
DOCAGENT_ANSWER_MODEL
DOCAGENT_ANSWER_TIMEOUT_SECONDS
DOCAGENT_ANSWER_TEMPERATURE
```

Secrets are not written to artifacts. Reports include only masked base URL,
provider, model, timeout, temperature, and whether an API key was configured.

## Boundary

This phase is a small-scenario answer-quality baseline. It is not a leaderboard
benchmark, not a commercial-quality proof, not training, not GRPO, not VLM, not
table lookup/simple calculation, and not UI work.
