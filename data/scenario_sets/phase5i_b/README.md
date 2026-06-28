# Phase 5I-B Scenario Set

Small reproducible fixture scenarios for the Phase 5I-B model-backed final
answer quality baseline.

Scope:

- parser: `text`
- document fixture: `docs/sample_climate_report.txt`
- case types: extractive and refusal local fact QA
- non-goals: summary, table lookup, simple calculation, VLM, training

The same scenario set can be used for local fake-policy tests and for a real
OpenAI-compatible AnswerPolicy smoke when `.secrets/answer_policy.env` is
available.
