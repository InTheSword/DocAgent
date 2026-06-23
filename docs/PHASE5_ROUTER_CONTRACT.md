# Phase 5 Router Contract

## Scope

This contract defines the Phase 5 router / planner surface for the personal-use
DocAgent MVP. Phase 5A only documents the contract. It does not implement
router code, document tools, prompt changes, Candidate-ID Reader, VLM support,
or full GRPO E2E.

Initial supported task types:

```text
local_fact_qa
table_lookup_or_calculation
document_statistics
page_lookup
structured_extraction
document_summary
```

Deferred task types:

```text
visual_pixel_qa
multi_document_comparison
long_horizon_agent_task
multi_turn_memory_task
```

## Task Types

`local_fact_qa`: specific answer questions grounded by a small number of
text/table evidence blocks. This should reuse the existing hybrid RAG path.

`table_lookup_or_calculation`: table row/column lookup or simple arithmetic over
table values. The router should classify it separately even if the first MVP
fallback still uses `local_fact_qa`.

`document_statistics`: deterministic metadata/count questions such as page,
block, table, and image counts. This must not use retrieval or an LLM.

`page_lookup`: explicit page requests such as showing or summarizing page text.

`structured_extraction`: full-scan extraction or listing tasks such as all
tables, all figures, all section headings, or all dates.

`document_summary`: global document summary. It should not depend on arbitrary
top-k retrieval as the only context.

## Router Input Schema

```json
{
  "doc_id": "string",
  "question": "string",
  "document_profile": {
    "page_count": 12,
    "block_count": 340,
    "table_count": 5,
    "image_count": 3,
    "has_ocr": true,
    "has_tables": true,
    "has_images": true
  },
  "available_tools": [
    "local_fact_qa",
    "count_pages",
    "count_blocks",
    "count_tables",
    "count_images",
    "get_page_text",
    "list_pages",
    "extract_all_tables",
    "extract_all_images",
    "document_summary"
  ],
  "options": {
    "allow_external_llm_router": false,
    "prefer_deterministic_tools": true,
    "max_tool_calls": 4
  }
}
```

Required input fields:

- `doc_id`
- `question`
- `available_tools`

Optional input fields:

- `document_profile`
- `options`

If `document_profile` is absent, the router may use conservative rules from the
question text only, but downstream validation must still confirm selected tools
exist.

## Router Output Schema

```json
{
  "task_type": "local_fact_qa",
  "selected_tools": ["local_fact_qa"],
  "requires_retrieval": true,
  "requires_full_scan": false,
  "requires_table_tool": false,
  "requires_calculation": false,
  "requires_visual_understanding": false,
  "target_evidence_types": ["text", "table"],
  "query_rewrite": "optional rewritten query",
  "confidence": 0.86,
  "reason": "The user asks for a specific field value likely supported by local evidence.",
  "fallback_used": false,
  "warnings": []
}
```

Validation requirements:

- `task_type` must be one of the supported task types.
- `selected_tools` must be non-empty and each tool must be available.
- `requires_visual_understanding` must be `false` in Phase 5.
- `confidence` must be a number in `[0.0, 1.0]`.
- `reason` must be a short operational explanation, not chain-of-thought.
- Router output must be JSON-serializable.

## Rule-first Routing Policy

Use deterministic rules for obvious cases:

- Count words: route page/block/table/image count questions to
  `document_statistics`.
- Explicit page references: route `page N`, `show page N`, or `text from page N`
  to `page_lookup`.
- Full extraction verbs: route `extract all`, `list all`, `show all tables`,
  or `list figures` to `structured_extraction`.
- Summary verbs over the whole document: route `summarize`, `what is this PDF
  about`, or `key points` to `document_summary`.
- Table/calculation terms: route row/column/value/highest/difference/sum/rate
  questions to `table_lookup_or_calculation`.
- Otherwise, route specific fact questions to `local_fact_qa`.

Deterministic tools take priority over retrieval when the question is about
document structure or metadata.

## External LLM Router Fallback Policy

External LLM routing is allowed only for high-level planning when rule
confidence is low or the question is ambiguous.

Default:

```text
allow_external_llm_router = false
```

Allowed:

- classify ambiguous user intent;
- choose between supported task types;
- propose a short `query_rewrite`.

Not allowed by default:

- answer the document question directly;
- receive full document text;
- receive image pixels;
- run batch evaluation;
- override Phase 5 VLM restrictions.

External fallback output must still pass the same schema validation as rule
output.

## Routing Failure Fallback Behavior

If routing fails validation:

1. If `local_fact_qa` is available, return a low-confidence `local_fact_qa`
   route with a warning.
2. If no usable tool is available, return a structured router error. Do not
   silently answer.
3. Never route to VLM or external answer generation in Phase 5.

Failure fallback example:

```json
{
  "task_type": "local_fact_qa",
  "selected_tools": ["local_fact_qa"],
  "requires_retrieval": true,
  "requires_full_scan": false,
  "requires_table_tool": false,
  "requires_calculation": false,
  "requires_visual_understanding": false,
  "target_evidence_types": ["text", "table"],
  "query_rewrite": "",
  "confidence": 0.2,
  "reason": "Router validation failed; falling back to local_fact_qa.",
  "fallback_used": true,
  "warnings": ["router_validation_failed"]
}
```

## Example Cases

| # | Question pattern | Task type | Selected tools |
|---|---|---|---|
| 1 | How many pages are in this document? | `document_statistics` | `count_pages` |
| 2 | Count the tables in this PDF. | `document_statistics` | `count_tables` |
| 3 | How many image or figure regions are detected? | `document_statistics` | `count_images` |
| 4 | How many OCR blocks are stored? | `document_statistics` | `count_blocks` |
| 5 | Show the text on page 3. | `page_lookup` | `get_page_text` |
| 6 | What is on page 5? | `page_lookup` | `get_page_text` |
| 7 | List all pages in the document. | `page_lookup` | `list_pages` |
| 8 | Extract all tables. | `structured_extraction` | `extract_all_tables` |
| 9 | List all figures. | `structured_extraction` | `extract_all_images` |
| 10 | List section headings. | `structured_extraction` | `list_sections` |
| 11 | Give the document outline. | `structured_extraction` | `document_outline` |
| 12 | Summarize this document. | `document_summary` | `document_summary` |
| 13 | What is this PDF about? | `document_summary` | `document_summary` |
| 14 | Give me the key points. | `document_summary` | `document_summary` |
| 15 | What is the invoice date? | `local_fact_qa` | `local_fact_qa` |
| 16 | Which organization issued the report? | `local_fact_qa` | `local_fact_qa` |
| 17 | What is the total amount due? | `local_fact_qa` | `local_fact_qa` |
| 18 | What was revenue in 2020? | `table_lookup_or_calculation` | `table_lookup` |
| 19 | What is the difference between 2020 and 2021 revenue? | `table_lookup_or_calculation` | `table_lookup`, `simple_calculation` |
| 20 | Which row has the highest amount? | `table_lookup_or_calculation` | `table_lookup`, `simple_calculation` |
| 21 | Extract all dates mentioned in the document. | `structured_extraction` | full-scan extraction tool |
| 22 | What does the chart color mean? | unsupported in Phase 5 | router error or `local_fact_qa` only if OCR/caption text exists |

## Acceptance For Router Implementation Later

- At least 30 fixed router examples pass.
- The 20+ examples above are included in tests or a stricter successor set.
- Rule routing works with no external API.
- External LLM fallback is disabled by default.
- Unsupported VLM-style questions do not trigger image understanding.
- Router decisions are recorded in the trace artifact.
