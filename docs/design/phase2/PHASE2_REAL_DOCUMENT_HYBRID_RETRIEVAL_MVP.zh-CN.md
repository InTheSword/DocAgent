# DocAgent Phase 2：真实文档接入与混合检索 MVP

> 用途：供 Codex 继续推进 DocAgent 项目。  
> 前置状态：Phase 1 已完成，Qwen3 Base / SFT / GRPO Answer Policy 已接入 LangGraph，结构化输出、位置校验、有界修复和 SQLite Trace 已跑通。  
> 核心原则：**优先补齐真实文档问答主链，先让系统成型，再优化检索与模型效果。**

---

## 1. Phase 1 结论与冻结项

Phase 1 已完成：

```text
Query Rewrite
→ same-doc BM25
→ Qwen3 Base / SFT / GRPO Answer Policy
→ JSON Parser
→ Format Check
→ Location Check
→ Bounded Repair
→ Final Answer
→ SQLite Trace
```

本阶段冻结：

- 不继续训练 SFT / GRPO；
- 不修改 reward；
- 不修改 MP-DocVQA split；
- 不继续做局部 prompt patch；
- 不改变 selected SFT / GRPO checkpoint；
- 不破坏 Phase 1 的 AnswerPolicy、Trace 和评测接口。

---

## 2. 本阶段目标

将当前“基于预构造 EvidenceBlock 的问答工作流”升级为“可接收真实文件并完成问答”的 MVP：

```text
真实 PDF / 页面图像
        ↓
文档注册与 SHA256 去重
        ↓
MinerU 解析
        ↓
Text / Table / Image EvidenceBlock
        ↓
Block-level Index
        ↓
Query Rewrite
        ↓
BM25 + BGE-M3 Dense Retrieval
        ↓
RRF 融合
        ↓
Cross-Encoder Reranker
        ↓
Top-k Evidence
        ↓
Phase 1 Qwen3 Answer Policy Workflow
        ↓
结构化答案 + 证据位置 + SQLite Trace
```

阶段完成后，应能运行：

```bash
python scripts/ingest_document.py --file examples/sample.pdf

python scripts/query_document.py   --doc-id <doc_id>   --question "..."   --policy-mode grpo   --retriever hybrid_rerank
```

输出：

- 最终答案；
- page / block 引用；
- top-k evidence；
- BM25 / Dense / RRF / Reranker 分数；
- Answer Policy 输出；
- SQLite run_id 和 trace。

---

## 3. 本阶段范围

### 3.1 必须完成

1. PDF / PNG / JPG 输入；
2. 文档注册、SHA256 去重和缓存；
3. MinerU 结构化解析；
4. MinerU 输出转换为统一 EvidenceBlock；
5. BGE-M3 Dense Retrieval；
6. BM25 + Dense 的 RRF 融合；
7. bge-reranker-v2-m3 真实接入；
8. 新 Retriever 接入 Phase 1 LangGraph；
9. CLI：ingest / query / inspect；
10. SQLite：documents / evidence_blocks / document_indexes；
11. MP-DocVQA 检索消融；
12. 至少 3 份真实文档端到端 smoke；
13. 测试、实施报告和文档更新。

### 3.2 暂不做

- 检索模型训练；
- Query Rewrite LLM 化；
- Reranker 微调；
- 多文档全局检索；
- TAT-QA；
- InfographicVQA；
- Qwen2.5-VL；
- FastAPI / Gradio；
- 新一轮 SFT / GRPO；
- 多 Agent / Tool Router。

---

## 4. 推荐目录结构

```text
docagent/
├── ingestion/
│   ├── service.py
│   ├── document_registry.py
│   └── hashing.py
├── parser/
│   ├── base.py
│   ├── mineru_backend.py
│   ├── mineru_converter.py
│   └── parser_registry.py
├── retrieval/
│   ├── base.py
│   ├── dense_encoder.py
│   ├── dense_index.py
│   ├── fusion.py
│   ├── reranker.py
│   ├── hybrid_retriever.py
│   └── index_manager.py
├── storage/
│   ├── db.py
│   ├── repositories.py
│   └── schema.sql
└── workflow/
    └── graph.py

configs/
├── parser_mineru.yaml
├── retrieval_hybrid.yaml
└── document_workflow.yaml

scripts/
├── ingest_document.py
├── query_document.py
├── inspect_document.py
├── eval_retrieval_phase2.py
└── eval_workflow_phase2.py

tests/
├── fixtures/mineru_sample/
├── test_mineru_converter.py
├── test_document_registry.py
├── test_dense_index.py
├── test_rrf_fusion.py
├── test_reranker.py
├── test_hybrid_retriever.py
├── test_document_ingestion.py
└── test_phase2_e2e_mock.py
```

已有同类文件时优先扩展，禁止重复维护两套实现。

---

## 5. 文档注册与缓存

### 5.1 doc_id

计算：

```text
sha256(file_bytes)
doc_id = SHA256 前 16 位
```

保存：

- 原始文件名；
- MIME type；
- 文件大小；
- SHA256；
- 文件路径；
- 页面数；
- parser backend；
- parse status；
- index status；
- 创建/更新时间。

重复上传相同文件时复用解析与索引。

### 5.2 文档目录

```text
data/documents/<doc_id>/
├── source/original.pdf
├── mineru/
├── pages/
├── figures/
├── evidence_blocks.jsonl
├── page_documents.jsonl
├── dense_embeddings.npy
├── dense_index.faiss
├── index_metadata.json
└── ingestion_report.json
```

### 5.3 状态

```text
registered → parsing → parsed → indexing → ready
```

失败：

```text
parse_failed
index_failed
```

支持：

```bash
--force-parse
--force-index
```

---

## 6. MinerU Parser Backend

### 6.1 接口

```python
class ParserBackend(Protocol):
    def parse(
        self,
        *,
        file_path: Path,
        doc_id: str,
        output_dir: Path,
    ) -> list[EvidenceBlock]:
        ...
```

### 6.2 两种模式

#### A. 解析已有 MinerU 输出

```text
mode = parse_existing
```

用途：

- 单元测试；
- MinerU 与 DocAgent 环境分离；
- 离线批处理；
- 不依赖模型启动。

#### B. 调用本地 MinerU

```text
mode = local_cli
```

配置示例：

```yaml
mineru:
  mode: local_cli
  command: mineru
  backend: pipeline
  timeout_seconds: 600
  output_root: data/documents
```

要求：

- 先检查当前服务器 MinerU 版本和 CLI；
- 使用 `subprocess.run([...])`；
- 禁止 `shell=True`；
- 保存 stdout、stderr、return code；
- 超时和失败写入 ingestion report；
- 不在未核对版本时写死命令参数。

### 6.3 转换内容

从 MinerU 结构化文件提取：

- page index；
- block type；
- text；
- bbox；
- reading order；
- table HTML / Markdown；
- image path；
- figure caption；
- page dimensions；
- parser metadata。

优先：

```text
content_list / middle JSON
> Markdown 辅助
> 纯文本 fallback
```

不得只读取 Markdown 再做固定长度硬切，并声称保留 layout。

### 6.4 EvidenceBlock

文本：

```json
{
  "doc_id": "abc123",
  "page_id": 3,
  "block_id": "abc123_p003_b0004",
  "block_type": "text",
  "text": "...",
  "bbox": [100, 200, 600, 280],
  "location": {
    "page": 3,
    "block_id": "abc123_p003_b0004"
  },
  "metadata": {
    "parser": "mineru",
    "reading_order": 4
  }
}
```

表格：

```json
{
  "block_type": "table",
  "text": "可检索表格文本",
  "table_html": "<table>...</table>",
  "metadata": {
    "caption": "...",
    "row_count": 10,
    "column_count": 4
  }
}
```

图片：

```json
{
  "block_type": "image",
  "text": "caption + nearby text",
  "image_path": "...",
  "metadata": {
    "visual_understanding_available": false
  }
}
```

### 6.5 简单块治理

小块合并：

- 同一页；
- reading order 相邻；
- 均为 text；
- 单块少于 100 字符；
- 合并后不超过 800～1200 字符。

大块切分：

- 优先按段落、行、句号切分；
- 保留 page_id；
- 子块记录 `parent_block_id`；
- block_id 加 `_s001` 等后缀。

---

## 7. Page-level 与 Block-level

### Block-level

用于检索和最终引用。

### Page-level

每页按 reading order 聚合：

```json
{
  "block_type": "page",
  "text": "本页文本、表格摘要与图注",
  "metadata": {
    "child_block_ids": [...]
  }
}
```

MVP 默认直接检索 block-level；page-level 仅保存，供后续 page-first / block-second 使用。

---

## 8. BGE-M3 Dense Encoder

### 8.1 实现

优先使用：

```text
FlagEmbedding.BGEM3FlagModel
```

配置：

```yaml
dense:
  model_path: /root/autodl-tmp/models/bge-m3
  device: cuda:1
  use_fp16: true
  batch_size: 16
  max_length: 1024
  normalize_embeddings: true
```

要求：

- 模型路径通过配置传入；
- import 时不自动联网下载；
- 支持 batch；
- query/document 分开编码；
- 输出 float32 NumPy；
- 默认 L2 normalize；
- 记录模型、维度、max_length、版本；
- 空文本过滤并记录。

接口：

```python
class DenseEncoder:
    def encode_queries(self, texts: list[str]) -> np.ndarray:
        ...

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        ...
```

### 8.2 检索文本

复用 `EvidenceBlock.retrieval_text`：

```text
block_type
+ section title
+ text
+ table caption / table text
+ figure caption
```

完整 HTML 不直接送入 embedding。

---

## 9. Dense Index

MVP 使用：

```text
FAISS IndexFlatIP
```

normalized embedding + inner product 等价于 cosine。

保存：

```text
dense_embeddings.npy
dense_index.faiss
index_metadata.json
```

metadata 包含：

```json
{
  "doc_id": "...",
  "model_id": "...",
  "embedding_dim": 1024,
  "normalized": true,
  "block_ids": [],
  "evidence_hash": "...",
  "created_at": "..."
}
```

EvidenceBlock 或模型变化时重建。

统一候选：

```python
@dataclass
class RetrievalCandidate:
    block: EvidenceBlock
    bm25_score: float | None
    dense_score: float | None
    rrf_score: float | None
    rerank_score: float | None
    ranks: dict[str, int]
    sources: list[str]
```

---

## 10. BM25 + Dense + RRF

默认候选：

```text
BM25 top 20
Dense top 20
RRF fusion top 20
```

配置：

```yaml
retrieval:
  bm25_top_n: 20
  dense_top_n: 20
  fusion_top_n: 20
  final_top_k: 5
  rrf_k: 60
```

RRF：

\[
RRF(d)=\sum_irac{1}{k+rank_i(d)}
\]

要求：

- rank 从 1 开始；
- block_id 去重；
- deterministic；
- 保存每路 rank；
- 缺失于某一路则该路不加分。

Query Rewrite 继续使用 Phase 1 规则实现，本阶段不引入 LLM rewrite。

---

## 11. Cross-Encoder Reranker

推荐：

```text
bge-reranker-v2-m3
```

配置：

```yaml
reranker:
  enabled: true
  model_path: /root/autodl-tmp/models/bge-reranker-v2-m3
  device: cuda:1
  use_fp16: true
  batch_size: 8
  candidate_top_n: 20
  final_top_k: 5
  max_length: 1024
```

接口：

```python
class Reranker:
    def score(
        self,
        *,
        query: str,
        candidates: list[RetrievalCandidate],
    ) -> list[RetrievalCandidate]:
        ...
```

要求：

- pair 为 `(query, retrieval_text)`；
- 保存 rerank score；
- 按 score 降序；
- 同分时按 RRF rank 稳定排序；
- 模型只加载一次；
- 模型缺失时 `hybrid_rerank` 明确报错；
- 不允许静默退化后仍标记为 reranker。

---

## 12. 统一 Retriever

```python
class Retriever(Protocol):
    def retrieve(
        self,
        *,
        doc_id: str,
        question: str,
        top_k: int,
    ) -> list[RetrievalCandidate]:
        ...
```

支持：

```text
bm25
dense
hybrid
hybrid_rerank
```

工作流仅依赖统一接口。

---

## 13. LangGraph 接入

保持 Phase 1 AnswerPolicy 不变，仅替换 `retrieve_evidence` 节点。

Trace 记录：

```json
{
  "node": "retrieve_evidence",
  "retriever_mode": "hybrid_rerank",
  "raw_question": "...",
  "rewritten_query": "...",
  "bm25_top_n": 20,
  "dense_top_n": 20,
  "rrf_k": 60,
  "reranker_enabled": true,
  "final_top_k": 5,
  "candidates": [
    {
      "block_id": "...",
      "page": 3,
      "bm25_score": 8.3,
      "dense_score": 0.72,
      "rrf_score": 0.031,
      "rerank_score": 0.91,
      "final_rank": 1
    }
  ],
  "latency_ms": {
    "rewrite": 0.5,
    "bm25": 2.1,
    "dense": 8.4,
    "fusion": 0.1,
    "rerank": 22.5
  }
}
```

禁止将 embedding 向量写入 trace。

Location Check 保持：

- final location 必须来自 top-k；
- repair 不访问 gold。

---

## 14. SQLite 扩展

新增/扩展：

```sql
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    sha256 TEXT UNIQUE NOT NULL,
    original_name TEXT NOT NULL,
    mime_type TEXT,
    file_path TEXT NOT NULL,
    page_count INTEGER,
    parser_backend TEXT,
    parse_status TEXT NOT NULL,
    index_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_blocks (
    block_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    page_id TEXT,
    block_type TEXT NOT NULL,
    text TEXT,
    table_html TEXT,
    image_path TEXT,
    bbox_json TEXT,
    metadata_json TEXT,
    FOREIGN KEY(doc_id) REFERENCES documents(doc_id)
);

CREATE TABLE IF NOT EXISTS document_indexes (
    doc_id TEXT NOT NULL,
    index_type TEXT NOT NULL,
    model_id TEXT,
    artifact_path TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY(doc_id, index_type, model_id)
);
```

不得破坏 Phase 1 的 `qa_runs` 和 `tool_traces`。

---

## 15. CLI

### 15.1 Ingest

```bash
python scripts/ingest_document.py   --file examples/sample.pdf   --parser mineru   --build-index   --dense-model-path /root/autodl-tmp/models/bge-m3   --reranker-model-path /root/autodl-tmp/models/bge-reranker-v2-m3   --sqlite-path outputs/docagent.db
```

输出：

```json
{
  "doc_id": "...",
  "parse_status": "parsed",
  "index_status": "ready",
  "page_count": 12,
  "block_count": 84,
  "block_type_counts": {
    "text": 70,
    "table": 8,
    "image": 6
  }
}
```

### 15.2 Query

```bash
python scripts/query_document.py   --doc-id <doc_id>   --question "What was the total revenue in 2023?"   --retriever hybrid_rerank   --policy-mode grpo   --base-model-path ...   --adapter-path ...   --sqlite-path outputs/docagent.db
```

### 15.3 Inspect

```bash
python scripts/inspect_document.py   --doc-id <doc_id>   --show-blocks   --show-index
```

---

## 16. MP-DocVQA 检索消融

保持现有 split 与 gold，不修改数据。

必须评估：

| 配置 | 说明 |
|---|---|
| BM25 | Phase 1 baseline |
| Dense | BGE-M3 |
| BM25 + Dense + RRF | Hybrid |
| BM25 + Dense + RRF + Reranker | 完整链路 |

指标：

```text
Recall@1
Recall@3
Recall@5
MRR@5
miss count
mean latency
p95 latency
```

不设置必须提升多少的硬阈值。若完整链路未优于 BM25：

- 保留真实结果；
- 分析失败类型；
- 默认部署可先选择最稳定配置；
- 不删除失败实验。

端到端固定 50 条比较：

```text
BM25 + GRPO
vs
Hybrid + Reranker + GRPO
```

指标：

```text
Answer EM
Answer F1
Location Accuracy
workflow success
mean latency
```

---

## 17. 真实文档 Smoke

至少选择 3 份合法公开文档：

1. 文本型 PDF；
2. 扫描型 PDF；
3. 含表格与图片的混合 PDF。

每份准备 3～5 个问题：

- 单页文本定位；
- 跨页面搜索；
- 表格字段查找；
- 不存在答案时拒答；
- 图片问题允许标记当前视觉能力受限。

保存：

```text
examples/phase2/
├── documents/
├── questions.jsonl
├── expected_evidence.jsonl
└── phase2_real_document_report.md
```

本阶段以功能闭环为主，人工核验答案和页码即可。

---

## 18. 测试要求

### MinerU Converter

覆盖：

- text / table / image；
- page / bbox / reading order；
- 空块过滤；
- 小块合并；
- 大块切分；
- 稳定 block_id。

单元测试不得启动真实 MinerU。

### Dense / FAISS

覆盖：

- embedding 维度；
- normalization；
- build/save/load；
- top-k；
- 缓存失效；
- 空索引；
- 重复 block_id。

### RRF

覆盖：

- 单路；
- 双路重叠；
- 双路不重叠；
- rank 从 1 开始；
- tie；
- 去重；
- deterministic。

### Reranker

覆盖：

- 排序；
- batch；
- tie；
- 单次加载；
- disabled；
- 错误路径。

### Ingestion

覆盖：

- SHA256；
- 重复文件；
- parse cache；
- index cache；
- force rebuild；
- 状态迁移；
- 失败恢复。

### Mock E2E

```text
fake document
→ fake MinerU output
→ EvidenceBlock
→ mock dense
→ RRF
→ mock reranker
→ mock AnswerPolicy
→ workflow
→ SQLite
```

### 回归

```bash
pytest -q
```

Phase 1 所有测试必须继续通过。

---

## 19. 资源分配

两张 4090D：

```text
GPU 0：Qwen3 Answer Policy
GPU 1：BGE-M3 + Reranker
CPU：BM25 + FAISS
```

若 MinerU 使用 GPU：

- ingestion 与 query 可分阶段；
- MinerU 可临时使用 GPU 1；
- 不要求微服务拆分；
- 单进程 + model registry 即可。

---

## 20. 实施顺序

1. 运行 Phase 1 全量测试并记录基线；
2. 审计现有 parser / retrieval / storage；
3. 实现 MinerU existing-output converter；
4. 完成 converter fixture 与测试；
5. 实现文档注册、SHA256 和缓存；
6. 核对服务器 MinerU CLI，跑通 1 PDF + 1 图片；
7. 实现 BGE-M3 encoder；
8. 实现 FAISS index；
9. 接入 BM25 + Dense + RRF；
10. 接入真实 Reranker；
11. 将新 Retriever 注入 workflow；
12. 完成 ingest/query/inspect CLI；
13. 运行 MP-DocVQA 消融；
14. 完成 3 份真实文档 smoke；
15. 更新 README / CURRENT_STATUS / DECISIONS / IMPLEMENTATION_PLAN / 项目实施进展。

---

## 21. 验收标准

### 功能

- [ ] PDF / 图片可注册；
- [ ] 相同 SHA256 不重复解析；
- [ ] MinerU 可输出 EvidenceBlock；
- [ ] text/table/image/page 均可保存；
- [ ] block 有稳定 page/location；
- [ ] BGE-M3 + FAISS 可用；
- [ ] BM25 / Dense 可独立检索；
- [ ] RRF 可融合；
- [ ] Reranker 真实执行；
- [ ] `hybrid_rerank` 返回 top-k；
- [ ] workflow 使用新 retriever；
- [ ] final location 来自 top-k；
- [ ] SQLite 保存文档、blocks、index 和 QA trace；
- [ ] 3 份真实文档 smoke 完成。

### 评估产物

```text
outputs/eval/phase2_retrieval_ablation.json
outputs/eval/phase2_workflow_comparison.json
reports/phase2_real_document_report.md
```

### 质量底线

- 解析成功后 block 数 > 0；
- 单文档内 block_id 100% 唯一；
- retrieved block 100% 可回查；
- final location 100% 来自 top-k；
- trace persist rate = 1.0；
- 真实文档 query 不访问 benchmark gold；
- 不允许静默 fallback 后仍标记为 hybrid/reranker。

---

## 22. 禁止事项

1. 不继续训练 SFT / GRPO；
2. 不修改 reward；
3. 不修改 benchmark split；
4. 不删除 BM25 baseline；
5. 不把规则 boost 冒充 Dense；
6. 不把未运行接口冒充 Reranker；
7. 不把 Markdown 硬切冒充 layout 解析；
8. 不在 import 时自动联网下载模型；
9. 不写死服务器路径；
10. 不重复解析同一文档；
11. 不把 embedding 写入 SQLite；
12. 不把 gold answer 传入 query；
13. 不同步开始 TAT-QA / VLM / Demo；
14. 不因指标未提升删除失败结果；
15. 不手工改候选顺序优化单个样本。

---

## 23. 推荐提交拆分

```text
1. Add document registry and ingestion cache
2. Add MinerU parser backend and EvidenceBlock conversion
3. Add BGE-M3 dense encoder and FAISS index
4. Add RRF fusion for BM25 and dense retrieval
5. Add cross-encoder reranker
6. Integrate hybrid reranker into QA workflow
7. Add ingest/query/inspect CLIs
8. Add retrieval ablation and real-document smoke
9. Add Phase 2 tests and documentation
```

每个提交需单一主题、测试通过、不混入模型训练。

---

## 24. Codex 执行摘要

```text
开始 DocAgent Phase 2：真实文档接入与混合检索 MVP。

Phase 1 已完成并冻结。本阶段不要继续训练模型、修改 reward 或调 reader prompt。

必须完成：
1. PDF/图片注册、SHA256 去重和缓存；
2. MinerU 解析及 EvidenceBlock 转换；
3. text/table/image/page 位置保存；
4. BGE-M3 dense embedding 与 FAISS；
5. BM25 top-20 + Dense top-20；
6. RRF(k=60)；
7. bge-reranker-v2-m3 将 top-20 重排到 top-5；
8. hybrid_rerank 注入 LangGraph；
9. ingest/query/inspect CLI；
10. SQLite 保存 documents、evidence_blocks、document_indexes 和 QA trace；
11. MP-DocVQA 的 BM25/Dense/Hybrid/Hybrid+Reranker 消融；
12. 3 份真实 PDF 的端到端 smoke；
13. mock 单测、GPU smoke、MinerU smoke 和文档更新。

优先形成可运行系统，不训练检索模型，不强制要求固定指标提升。所有结果必须真实保留，失败模块不得静默伪装为已启用。
```

---

## 25. 阶段完成后的下一步

Phase 2 完成后，DocAgent 将具备：

```text
真实文件输入
→ 结构化解析
→ 混合检索
→ Qwen 后训练模型回答
→ 引用校验
→ Trace
```

下一阶段再补：

```text
TAT-QA 表格数值工具链
+ InfographicVQA / Qwen2.5-VL 视觉复核
+ 多源增量 SFT
```
