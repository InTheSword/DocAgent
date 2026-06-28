# Phase 5I-B：模型驱动问答质量基线与 API 全通路验证需求文档

## 0. 文档信息

- 项目：DocAgent 复杂文档问答系统
- 阶段：Phase 5I-B
- 任务名称：模型驱动问答质量基线与 API 全通路验证
- 面向执行者：Codex
- 文档语言：中文
- 当前状态：待实现
- 前置阶段：
  - Phase 5E Document Summary MVP：已本地实现
  - Phase 5E-A Document Summary Acceptance Pack：Codex 报告为 implemented，本 PM 记录为 local accepted by report；未做服务器复验
- 本阶段核心目标：从“执行稳定性 / 工具闭环”推进到“真实模型问答质量可评估、API 通路可复现、失败样本可沉淀”

---

## 1. PM 结论

当前不应继续优先做纯规则类工具、artifact 校验或文档状态整理。下一阶段必须切换到更接近产品目标的主链路：

```text
文档摄入
-> Router
-> Query Planner / Retriever
-> evidence context
-> 模型 AnswerPolicy 生成
-> format/location check
-> repair
-> 结构化答案
-> 自动评估
-> 失败归因
-> 可用于后续 SFT/GRPO 的候选样本沉淀
```

本阶段不是训练阶段，也不是 UI 阶段。它的定位是：

> 建立一个可复现的小规模模型驱动问答质量基线，验证本地或外部大模型 API 可以真正接入 DocAgent 的 local_fact_qa 主链路，并输出可量化的 answer quality、citation/location、format、failure taxonomy 和后续训练数据候选。

---

## 2. 背景

目前 DocAgent 已经具备：

- 文档注册 / 摄入；
- TextParser 和 existing MinerU output 路径；
- EvidenceBlock 持久化；
- Router；
- Query Planning；
- BM25 / hybrid retrieval 历史能力；
- local_fact_qa workflow；
- AnswerPolicy 接口和 Qwen AnswerPolicy 历史接入；
- JSON artifact 和 trace；
- document_summary deterministic 工具。

但目前仍缺少被正式接受的：

- final answer quality benchmark；
- 模型 AnswerPolicy API 端到端验收；
- 可复现的小规模真实问答场景集；
- 按 answer correctness / citation / location / format 维度的质量报告；
- 可用于后续训练或 prompt 优化的失败样本导出。

因此，本阶段要从“系统能跑”推进到“模型回答质量能测、能复现、能归因”。

---

## 3. 本阶段目标

### 3.1 产品目标

实现一个 Phase 5I-B runner，使项目能够在小规模 scenario set 上运行模型驱动问答，并生成完整质量报告：

```text
scenario_set.jsonl
-> ingest / reuse document
-> local_fact_qa
-> model-backed AnswerPolicy.generate
-> output parsing / repair / citation check
-> prediction record
-> metrics report
-> failure analysis
-> acceptance report
```

### 3.2 工程目标

- 建立 scenario set schema；
- 建立 answer quality evaluator；
- 明确模型 API 配置入口；
- 支持真实模型调用和 mock/fake 测试分离；
- 输出可复查 artifacts；
- 将模型输入、模型输出、gold answer、失败标签沉淀为后续训练数据候选。

### 3.3 验收目标

本阶段完成后，项目可以回答以下问题：

1. 当前 DocAgent 在小规模真实 / 半真实文档问答场景上的 answer quality 是多少？
2. API 是否真正经过了 AnswerPolicy，而不是 fake workflow？
3. 模型输出是否稳定满足 JSON / citation / location contract？
4. 主要失败来自 routing、retrieval、evidence packing、generation、format、location，还是 refusal？
5. 哪些失败样本应该进入后续 SFT / GRPO / prompt 优化数据池？

---

## 4. 非目标

本阶段禁止做以下事情：

| 非目标 | 说明 |
|---|---|
| 不启动 SFT / GRPO 训练 | 本阶段只做评估与数据沉淀，不训练 |
| 不实现 table lookup / simple calculation | 表格数值工具需要单独里程碑 |
| 不实现 VLM / visual_pixel_qa | 当前仍不做视觉像素级推理 |
| 不实现 UI / Gradio / FastAPI | 后端质量基线完成后再做 |
| 不修改大规模数据集 pipeline | 只做小规模 scenario set 和候选样本导出 |
| 不把 mock 结果记为真实模型结果 | fake policy 仅用于单测 |
| 不提交 secrets / API key | `.secrets/` 必须继续 ignored |
| 不静默安装模型或修改 CUDA/Torch | 大模型本地部署和服务器环境变更必须另行批准 |
| 不追求指标好看 | 本阶段允许低分，重点是真实、可复现、可归因 |

---

## 5. 术语定义

| 术语 | 定义 |
|---|---|
| scenario set | 小规模可复现问答场景集合，包含文档路径、问题、gold answer、answer_type、期望任务类型等 |
| model-backed run | 真实调用本地模型或外部 OpenAI-compatible API 的 run |
| fake run | 单测中使用 fake AnswerPolicy，不计入真实验收 |
| answer quality | 针对最终 answer 的 correctness，不等同于 evidence readiness |
| citation validity | 输出 citation 是否引用了存在的 page / block_id |
| location accuracy | 输出位置是否命中 gold page / block |
| failure taxonomy | 对失败样本按 router / retrieval / generation / format / location / refusal 等阶段归因 |
| training candidate | 本阶段导出的可人工复核样本，后续可能进入 SFT / GRPO，但本阶段不训练 |

---

## 6. 任务范围

## 6.1 新增或改造文件

Codex 应优先复用现有模块，避免重复实现大型逻辑。建议新增或改造：

```text
scripts/run_phase5i_b_model_answer_quality.py
docagent/eval/answer_quality.py
docagent/eval/scenario_schema.py
docagent/eval/failure_taxonomy.py
docs/PHASE5I_B_MODEL_ANSWER_QUALITY.md
tests/test_phase5i_b_answer_quality_metrics.py
tests/test_phase5i_b_scenario_schema.py
tests/test_phase5i_b_model_answer_quality_runner.py
```

如现有 `scripts/run_phase5i_answer_quality_benchmark.py` 已经承担 Phase 5I-A evidence readiness，不建议直接混入最终答案质量语义，除非实现方式能明确区分：

```text
--mode evidence_readiness
--mode final_answer_quality
```

更推荐新增 `run_phase5i_b_model_answer_quality.py`，避免语义污染。

---

## 6.2 scenario set schema

新增小规模 scenario set，推荐路径：

```text
data/scenario_sets/phase5i_b/README.md
data/scenario_sets/phase5i_b/phase5i_b_cases.jsonl
```

如果仓库策略不允许提交 `data/` 下文件，则改用：

```text
tests/fixtures/phase5i_b/phase5i_b_cases.jsonl
tests/fixtures/phase5i_b/docs/*.txt
```

### 6.2.1 JSONL 单条样本格式

每行一个 JSON：

```json
{
  "case_id": "phase5i_b_txt_001",
  "doc_key": "globocan_africa_2022_or_fixture_doc",
  "file": "tests/fixtures/phase5i_b/docs/sample_report.txt",
  "parser": "text",
  "mineru_output_dir": null,
  "question": "What organization published the report?",
  "expected_task_type": "local_fact_qa",
  "gold_answer": "World Health Organization",
  "answer_type": "extractive",
  "gold_locations": [
    {
      "page": 1,
      "block_id": null
    }
  ],
  "gold_evidence_text_contains": [
    "World Health Organization"
  ],
  "eval_method": "normalized_exact_or_contains",
  "tags": ["txt", "extractive", "single_evidence"],
  "notes": "Small reproducible fixture case."
}
```

### 6.2.2 字段要求

| 字段 | 必填 | 说明 |
|---|---:|---|
| `case_id` | 是 | 全局唯一 |
| `doc_key` | 是 | 文档逻辑名，不要求等于 doc_id |
| `file` | 是/条件 | 新摄入文件路径；若复用 doc_id 可为空 |
| `doc_id` | 否 | 已摄入文档 ID |
| `parser` | 是 | `text` 或 `mineru_existing` |
| `mineru_output_dir` | 条件 | `mineru_existing` 时必填 |
| `question` | 是 | 用户问题 |
| `expected_task_type` | 是 | 本阶段主要是 `local_fact_qa` |
| `gold_answer` | 是 | 标准答案；拒答样本可使用 `null` 并配置 expected_behavior |
| `answer_type` | 是 | `extractive` / `numeric` / `boolean` / `choice` / `refusal`，本阶段 P0 优先 extractive/refusal |
| `gold_locations` | 否 | 至少 page-level；block_id 可为空 |
| `gold_evidence_text_contains` | 否 | 用于辅助检查 evidence grounding |
| `eval_method` | 是 | `normalized_exact_or_contains` / `numeric_tolerance` / `boolean_exact` / `refusal_expected` |
| `tags` | 否 | 用于分组统计 |
| `notes` | 否 | 人工说明 |

### 6.2.3 P0 场景数量要求

至少 12 个 case：

| 类型 | 数量 | 要求 |
|---|---:|---|
| 单证据抽取式 QA | >= 6 | 答案在一个明确 EvidenceBlock 中 |
| 多页 / 多段上下文 QA | >= 2 | 需要检索或上下文选择 |
| 中文问题 | >= 2 | 验证中文入口 |
| 英文问题 | >= 2 | 验证英文入口 |
| 拒答 / 证据不足 | >= 2 | 验证 refusal |
| 摘要类 | 0 | 不纳入本阶段 answer quality；summary 已独立验收 |

说明：

- P0 可以优先使用 `.txt` fixture 保证可复现。
- 如果本地存在 `data/real_documents/globocan_africa_2022/` 或 existing MinerU fixture，可增加真实文档 case，但不能作为必须条件导致本地测试失败。
- 如果使用真实文档路径，runner 必须在路径不存在时标记 `skipped_missing_optional_fixture`，不能误报 passed。

---

## 6.3 模型 API 配置入口

本阶段必须支持真实模型 AnswerPolicy，但不得提交 secrets。

### 6.3.1 推荐 CLI 参数

```bash
python scripts/run_phase5i_b_model_answer_quality.py \
  --scenario-path data/scenario_sets/phase5i_b/phase5i_b_cases.jsonl \
  --db-path outputs/phase5i_b_model_answer_quality/docagent.db \
  --output-dir outputs/phase5i_b_model_answer_quality \
  --allow-external-api \
  --answer-policy-provider openai_compatible \
  --answer-policy-model qwen3-or-compatible-model-name \
  --answer-policy-env-file .secrets/answer_policy.env \
  --enable-query-planning \
  --query-planner-mode rule
```

### 6.3.2 `.secrets/answer_policy.env` 示例

只能在文档中给 example，不得提交真实文件：

```bash
DOCAGENT_ANSWER_BASE_URL=https://your-openai-compatible-endpoint/v1
DOCAGENT_ANSWER_API_KEY=sk-***
DOCAGENT_ANSWER_MODEL=qwen3-or-compatible-model-name
DOCAGENT_ANSWER_TIMEOUT_SECONDS=60
DOCAGENT_ANSWER_TEMPERATURE=0
```

### 6.3.3 安全要求

- 不得打印完整 API key；
- 不得把 `.secrets/answer_policy.env` 写入 artifact；
- 报告中仅允许记录：
  - provider；
  - model；
  - base_url host 或 masked base_url；
  - timeout；
  - temperature；
  - `used_external_api=true/false`；
- 如果没有 `--allow-external-api`，不得真实调用外部 API；
- 如果配置缺失，runner 应返回明确错误或 skipped，不得 silently fallback 到 fake policy 并标记为真实通过。

---

## 6.4 Runner 行为要求

新增 runner：

```text
scripts/run_phase5i_b_model_answer_quality.py
```

### 6.4.1 输入

支持参数：

| 参数 | 必填 | 说明 |
|---|---:|---|
| `--scenario-path` | 是 | JSONL case 文件 |
| `--db-path` | 是 | SQLite DB |
| `--output-dir` | 是 | 输出目录 |
| `--document-root` | 否 | 文档根目录 |
| `--allow-external-api` | 条件 | 真实外部 API 必须显式开启 |
| `--answer-policy-provider` | 是 | `heuristic` / `fake` / `openai_compatible` / existing provider |
| `--answer-policy-model` | 条件 | 真实模型名 |
| `--answer-policy-env-file` | 条件 | env 文件路径 |
| `--enable-query-planning` | 否 | 是否启用 query planning |
| `--query-planner-mode` | 否 | `rule` / `llm` / `hybrid`，P0 默认 rule |
| `--max-cases` | 否 | 调试用 |
| `--fail-on-api-error` | 否 | API 错误是否直接非零退出 |
| `--export-training-candidates` | 否 | 是否导出训练候选样本；默认开启 |

### 6.4.2 执行流程

每个 case 应执行：

```text
load scenario case
-> validate schema
-> ingest or reuse document
-> run CLI/product-equivalent local_fact_qa path
-> ensure Router task_type == expected_task_type
-> collect model input summary
-> call model-backed AnswerPolicy
-> parse output
-> validate format
-> validate citations
-> compare answer with gold_answer
-> compare location with gold_locations when available
-> classify failure
-> write per-case artifacts
```

### 6.4.3 重要约束

- P0 可以直接调用内部函数，也可以通过 `scripts/docagent_cli.py` 子进程执行；但报告必须说明采用哪条路径。
- 如果没有走 `AnswerPolicy.generate`，不能标记为 model-backed。
- 如果使用 fake policy，只能用于单测，不得写入真实 acceptance report。
- 真实验收 run 必须满足：
  - `used_model_answer_generation=true`
  - `used_fake_policy=false`
  - `final_answer_quality_evaluated=true`

---

## 6.5 输出 artifacts

输出目录结构建议：

```text
outputs/phase5i_b_model_answer_quality/
  acceptance_report.json
  metrics.json
  predictions.jsonl
  case_reports.jsonl
  failure_analysis.md
  training_candidates_raw.jsonl
  model_config_masked.json
  scenario_snapshot.jsonl
  cli_artifacts/
    <case_id>/
      result.json
      summary.json
      router_plan.json
      trace.json
      model_io.json
```

### 6.5.1 `predictions.jsonl`

每行：

```json
{
  "case_id": "phase5i_b_txt_001",
  "status": "completed",
  "task_type": "local_fact_qa",
  "question": "...",
  "gold_answer": "...",
  "predicted_answer": "...",
  "answer_type": "extractive",
  "answer_correct": true,
  "token_f1": 1.0,
  "normalized_exact_match": 1.0,
  "citation_valid": true,
  "location_correct": true,
  "json_valid": true,
  "used_model_answer_generation": true,
  "used_fake_policy": false,
  "failure_stage": null,
  "warnings": []
}
```

### 6.5.2 `metrics.json`

必须包含：

```json
{
  "evaluation_scope": "final_answer_quality",
  "final_answer_generation_enabled": true,
  "final_answer_quality_evaluated": true,
  "case_count": 12,
  "completed_count": 12,
  "failed_count": 0,
  "skipped_count": 0,
  "answer_accuracy": 0.0,
  "normalized_exact_match": 0.0,
  "average_token_f1": 0.0,
  "json_valid_rate": 0.0,
  "citation_valid_rate": 0.0,
  "location_accuracy": 0.0,
  "refusal_accuracy": 0.0,
  "router_task_type_accuracy": 0.0,
  "unsupported_count": 0,
  "api_error_count": 0,
  "failure_stage_distribution": {}
}
```

### 6.5.3 `acceptance_report.json`

必须包含：

```json
{
  "phase": "Phase 5I-B",
  "status": "completed",
  "acceptance_state": "acceptance_candidate",
  "used_model_answer_generation": true,
  "used_external_api": true,
  "used_fake_policy": false,
  "used_vlm": false,
  "used_training": false,
  "used_grpo": false,
  "used_table_lookup": false,
  "used_simple_calculation": false,
  "final_answer_quality_evaluated": true,
  "scenario_path": "...",
  "output_dir": "...",
  "metrics_path": "...",
  "predictions_path": "...",
  "failure_analysis_path": "...",
  "training_candidates_path": "...",
  "notes": []
}
```

### 6.5.4 `failure_analysis.md`

必须按以下结构生成：

```markdown
# Phase 5I-B Failure Analysis

## 1. 总览

- case_count:
- answer_accuracy:
- json_valid_rate:
- citation_valid_rate:
- location_accuracy:

## 2. 按失败阶段统计

| failure_stage | count | representative_cases |
|---|---:|---|

## 3. 典型失败样本

### case_id

- question:
- gold_answer:
- predicted_answer:
- retrieved_evidence_summary:
- failure_stage:
- likely_root_cause:
- suggested_next_action:

## 4. 后续优化建议

- retrieval:
- evidence packing:
- prompt / output format:
- SFT data:
- GRPO data:
```

### 6.5.5 `training_candidates_raw.jsonl`

每个失败或低分样本导出一行：

```json
{
  "case_id": "phase5i_b_txt_001",
  "question": "...",
  "evidence_context": "...",
  "tool_results": {},
  "gold_answer": "...",
  "gold_locations": [],
  "model_output": {},
  "failure_stage": "generation_error",
  "candidate_use": ["sft", "prompt_debug"],
  "requires_human_review": true
}
```

要求：

- 这是候选数据，不是最终训练数据。
- 必须包含 `requires_human_review=true`。
- 不得直接写入正式 `train_sft.jsonl` 或 `grpo_train.jsonl`。

---

## 7. 评估指标要求

### 7.1 Answer correctness

优先复用已有 `docagent/eval/answer_metrics.py`。如果功能不足，可新增轻量封装。

必须支持：

| answer_type | 指标 |
|---|---|
| extractive | normalized exact match、contains、token F1 |
| boolean | exact match |
| numeric | numeric tolerance，P0 可只实现已有逻辑或标记 unsupported_numeric_eval |
| refusal | 是否正确拒答 |
| choice | exact match，P0 可选 |

### 7.2 Format

指标：

- `json_valid`
- `required_fields_present`
- `answer_non_empty`
- `evidence_location_present`
- `reason_present`

### 7.3 Citation / location

指标：

- `citation_valid`: citation page/block 是否存在于 EvidenceBlock；
- `location_correct`: 与 gold page/block 是否匹配；
- `citation_count`;
- `supporting_evidence_ids_count`.

### 7.4 Failure taxonomy

失败阶段枚举：

```text
none
scenario_schema_error
ingestion_error
router_error
retrieval_miss
evidence_context_missing_answer
model_api_error
model_output_parse_error
format_error
generation_error
location_error
citation_error
refusal_error
unsupported_task
unknown_error
```

归因规则：

- 如果 Router task_type 错，优先记为 `router_error`；
- 如果 evidence context 中不含 gold evidence text，记为 `retrieval_miss` 或 `evidence_context_missing_answer`；
- 如果 API 调用失败，记为 `model_api_error`；
- 如果输出不可解析，记为 `model_output_parse_error`；
- 如果答案错但 evidence 正确，记为 `generation_error`；
- 如果答案对但位置错，记为 `location_error`；
- 如果 citation 引用不存在，记为 `citation_error`；
- 如果拒答样本误答或应答样本拒答，记为 `refusal_error`。

---

## 8. 测试要求

### 8.1 单元测试

新增：

```text
tests/test_phase5i_b_scenario_schema.py
tests/test_phase5i_b_answer_quality_metrics.py
tests/test_phase5i_b_model_answer_quality_runner.py
```

必须覆盖：

- scenario JSONL schema validation；
- 缺字段报错；
- answer normalization；
- exact / contains / token_f1；
- citation validity；
- location correctness；
- failure taxonomy 分类；
- fake AnswerPolicy runner 不标记为真实 model-backed；
- 缺 API 配置时不 silent pass；
- acceptance_report schema。

### 8.2 集成测试

允许使用 fake AnswerPolicy 做 CI 级测试：

```bash
python -m pytest tests/test_phase5i_b_scenario_schema.py \
  tests/test_phase5i_b_answer_quality_metrics.py \
  tests/test_phase5i_b_model_answer_quality_runner.py -q
```

真实 API 测试必须由显式命令执行，不放入默认 CI：

```bash
python scripts/run_phase5i_b_model_answer_quality.py \
  --scenario-path data/scenario_sets/phase5i_b/phase5i_b_cases.jsonl \
  --db-path outputs/phase5i_b_model_answer_quality/docagent.db \
  --output-dir outputs/phase5i_b_model_answer_quality \
  --allow-external-api \
  --answer-policy-provider openai_compatible \
  --answer-policy-env-file .secrets/answer_policy.env \
  --enable-query-planning \
  --query-planner-mode rule
```

### 8.3 回归测试

本阶段完成后，至少运行：

```bash
python -m pytest tests/test_phase5i_b_scenario_schema.py \
  tests/test_phase5i_b_answer_quality_metrics.py \
  tests/test_phase5i_b_model_answer_quality_runner.py -q

python -m pytest tests/test_phase5_local_fact_qa_tool.py \
  tests/test_phase5f_cli.py \
  tests/test_phase5e_document_summary_tool.py \
  tests/test_phase5e_document_summary_cli.py \
  tests/test_phase5e_document_summary_acceptance.py -q
```

如时间允许，再运行：

```bash
python -m pytest tests/test_phase5*.py -q
```

---

## 9. 验收标准

| AC | 验收标准 |
|---|---|
| AC-1 | 新增 Phase 5I-B scenario schema，并有至少 12 个 P0 case |
| AC-2 | 新增或改造 final answer quality runner，明确区别于 Phase 5I-A evidence readiness |
| AC-3 | runner 可以显式调用真实模型 AnswerPolicy，而不是 fake workflow |
| AC-4 | 缺少 API 配置时不能 silent fallback 成 fake pass |
| AC-5 | 真实 run 输出 `used_model_answer_generation=true` |
| AC-6 | 真实 run 输出 `final_answer_quality_evaluated=true` |
| AC-7 | 输出 `metrics.json`、`predictions.jsonl`、`case_reports.jsonl`、`failure_analysis.md`、`acceptance_report.json` |
| AC-8 | 每个 completed case 都有 answer correctness、format、citation、location 字段 |
| AC-9 | 每个失败 case 都有 `failure_stage` |
| AC-10 | 至少导出一个 `training_candidates_raw.jsonl`，即使为空也要有合法 JSONL 或空文件说明 |
| AC-11 | 单元测试通过 |
| AC-12 | 本地真实 API smoke 至少完成 8 个 model-backed cases，除非 Codex 明确报告 API 配置缺失导致无法执行 |
| AC-13 | 不启动训练、不使用 VLM、不实现 table lookup/simple calculation、不做 UI |
| AC-14 | 更新 `CURRENT_STATUS.md`、`docs/ACTIVE_PLAN.md`、`docs/PHASE5_ACTIVE_PLAN.md` |
| AC-15 | 报告必须明确本阶段是 small-scenario baseline，不是正式 leaderboard，不是商业级质量证明 |

---

## 10. 推荐实现步骤

### Step 1：冻结 schema 和测试夹具

- 新增 scenario schema validator；
- 准备 12 个 fixture cases；
- 准备至少一个 `.txt` fixture 文档；
- 写 schema 测试。

### Step 2：实现 answer quality metrics

- 复用已有 answer metrics；
- 增加 refusal / citation / location 检查；
- 写 metrics 测试。

### Step 3：实现 runner 主流程

- 支持 ingest/reuse；
- 调用 local_fact_qa；
- 接入 model-backed AnswerPolicy；
- 写 predictions 和 case reports。

### Step 4：实现 API config 和安全报告

- env file 加载；
- secrets masking；
- 缺配置 fail fast；
- 写 model_config_masked.json。

### Step 5：实现 failure analysis 和 training candidates

- failure taxonomy；
- 失败样本 markdown 报告；
- raw training candidates 导出。

### Step 6：文档更新与回归测试

- 更新状态文档；
- 运行 targeted tests；
- 如有 API 配置，运行真实 model-backed smoke；
- 返回 Codex 实现报告。

---

## 11. 状态文档更新要求

### 11.1 `CURRENT_STATUS.md`

必须新增：

```markdown
## Phase 5I-B Model-backed Answer Quality Baseline

Status: implemented / acceptance_candidate / skipped_api_missing

Phase 5I-B introduces a small-scenario final answer quality evaluation runner.
Unlike Phase 5I-A evidence readiness, this phase enables model-backed answer
generation and evaluates final answer correctness, format validity, citation
validity, location accuracy, and failure taxonomy.

Boundary:
- small scenario baseline only;
- not a leaderboard benchmark;
- not training;
- not VLM;
- not table lookup or simple calculation;
- not UI.
```

### 11.2 `docs/ACTIVE_PLAN.md`

记录当前 active milestone 为 Phase 5I-B，并标注停止条件。

### 11.3 `docs/PHASE5_ACTIVE_PLAN.md`

增加：

- scenario set 路径；
- runner 命令；
- artifacts 路径；
- metrics；
- 已知限制；
- 下一阶段建议候选。

---

## 12. Codex 返回报告格式

Codex 完成后必须按以下格式返回：

```markdown
# Codex Implementation Report: Phase 5I-B Model-backed Answer Quality Baseline

## 1. 结论

- 状态：implemented / acceptance_candidate / skipped_api_missing / blocked
- 一句话总结：
- 是否真实调用模型 AnswerPolicy：yes/no
- 是否使用 fake policy：yes/no
- 是否评估 final answer quality：yes/no

## 2. 变更文件

| 文件 | 变更摘要 |
|---|---|

## 3. scenario set

| 指标 | 数值 |
|---|---:|
| case_count | |
| extractive_count | |
| refusal_count | |
| zh_question_count | |
| en_question_count | |
| optional_real_doc_count | |
| skipped_optional_fixture_count | |

## 4. 模型 / API 配置

| 字段 | 值 |
|---|---|
| provider | |
| model | |
| used_external_api | true/false |
| base_url_masked | |
| temperature | |
| timeout | |
| api_key_logged | 必须为 false |

## 5. 执行命令

| 命令 | 结果 |
|---|---|

## 6. 测试结果

| 测试 | 结果 |
|---|---|

## 7. 质量指标

| 指标 | 数值 |
|---|---:|
| case_count | |
| completed_count | |
| failed_count | |
| skipped_count | |
| answer_accuracy | |
| normalized_exact_match | |
| average_token_f1 | |
| json_valid_rate | |
| citation_valid_rate | |
| location_accuracy | |
| refusal_accuracy | |
| router_task_type_accuracy | |
| unsupported_count | |
| api_error_count | |

## 8. 失败归因

| failure_stage | count | representative_cases |
|---|---:|---|

## 9. 生成产物

| 产物 | 路径 | 是否有效 |
|---|---|---|
| metrics.json | | |
| predictions.jsonl | | |
| case_reports.jsonl | | |
| failure_analysis.md | | |
| training_candidates_raw.jsonl | | |
| acceptance_report.json | | |

## 10. 验收标准映射

| AC | 结果 | 证据 |
|---|---|---|

## 11. 边界确认

- 使用真实模型 AnswerPolicy：yes/no
- 使用外部 API：yes/no
- 使用 fake policy 作为真实验收：必须为 no
- 使用 VLM：必须为 no
- 使用训练：必须为 no
- 使用 GRPO：必须为 no
- 使用 table lookup：必须为 no
- 使用 simple calculation：必须为 no
- 实现 UI：必须为 no
- 是否正式 leaderboard benchmark：必须为 no

## 12. 与规格偏差

- 无 / 列出偏差

## 13. 已知风险 / 限制

- 

## 14. 下一步建议

- 
```

---

## 13. 停止条件

完成以下任一情况即停止并返回报告：

1. 所有 AC 达成，返回 implemented / acceptance_candidate；
2. API 配置缺失，已完成 fake/unit 路径和文档，但真实模型 run 未执行，返回 `skipped_api_missing`；
3. 发现现有 AnswerPolicy 接口无法接入真实模型，返回 `blocked`，并说明最小阻塞点；
4. 发现 scenario schema 与现有 ingestion/CLI 设计冲突，返回 `blocked`，并给出最小修复建议。

不得在本任务中继续扩展到训练、UI、VLM、table calculation 或大规模数据构建。
