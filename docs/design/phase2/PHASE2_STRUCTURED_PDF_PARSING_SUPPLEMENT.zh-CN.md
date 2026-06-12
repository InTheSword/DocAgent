# DocAgent Phase 2 补充实施任务：结构感知 PDF 解析与上下文保留

> 目的：补充 `DocAgent_Phase2_RealDocument_HybridRetrieval_MVP.md`。  
> 原则：不扩大 Phase 2 的总体范围，只补齐避免“PDF 全量转文本 + 固定切片”所必须的结构化处理能力。  
> 优先级：先形成可用闭环，再优化复杂版面、跨页表格和视觉理解效果。

---

## 1. 补充目标

Phase 2 的 PDF 处理链路应从：

```text
PDF
→ OCR / Markdown
→ 固定长度切片
→ 入库
```

调整为：

```text
PDF / 页面图像
→ MinerU 版面解析
→ 页面、标题、段落、列表、表格、图片区域识别
→ 保留层级、位置、阅读顺序和邻接关系
→ 结构感知 EvidenceBlock
→ Boilerplate 过滤
→ Block Retrieval
→ Context Expansion
→ Qwen3 Answer Policy
```

本补充任务重点解决：

1. 标题层级和章节上下文丢失；
2. 页眉、页脚、页码重复污染检索；
3. 表格被压平后行列关系丢失；
4. 图片、图注和附近文本关系丢失；
5. 命中单个 block 后缺少父标题和前后文；
6. 跨页段落、续表和相邻页关系缺失；
7. MinerU 解析异常未被发现而直接入库。

---

## 2. EvidenceBlock 必须补充的结构字段

在不破坏现有 schema 的前提下，为 `metadata` 增加以下字段：

```json
{
  "section_id": "sec_2_3",
  "section_path": [
    "2 Financial Results",
    "2.3 Revenue Analysis"
  ],
  "heading_level": 2,
  "parent_block_id": "doc_p003_sec_2_3",
  "previous_block_id": "doc_p003_b0003",
  "next_block_id": "doc_p003_b0005",
  "container_id": "textbox_01",
  "container_type": "section|textbox|sidebar|table|figure",
  "reading_order": 4,
  "is_boilerplate": false,
  "cross_page_group_id": null,
  "continuation_of": null,
  "continued_by": null
}
```

最低要求：

- 标题 block 能识别 `heading_level`；
- 正文 block 能保存 `section_path`；
- 同页 block 建立前后邻接关系；
- 表格、图片、文本框保留 `container_id`；
- 页眉页脚可标记 `is_boilerplate`；
- 跨页连续内容预留关系字段。

---

## 3. MinerU 输出转换要求

### 3.1 禁止简化为 Markdown 固定切片

转换器优先读取 MinerU 的结构化 JSON：

```text
content_list / middle JSON
> Markdown 辅助
> 纯文本 fallback
```

不得仅执行：

```text
MinerU Markdown
→ 每 800 字符切片
```

并声称保留了 layout。

### 3.2 Block 类型映射

至少统一映射：

| MinerU 内容 | DocAgent block_type |
|---|---|
| title / heading | `heading` |
| paragraph / text | `text` |
| list item | `list_item` |
| table | `table` |
| figure / image | `image` |
| caption | `caption` |
| page aggregate | `page` |

未知类型：

```text
block_type = "unknown"
```

并在解析报告中统计，不能静默丢弃。

### 3.3 稳定 block_id

格式建议：

```text
{doc_id}_p{page:03d}_{type}_{order:04d}
```

切分子块：

```text
{parent_block_id}_s001
```

相同文件、相同 MinerU 输出重复转换时，block_id 必须一致。

---

## 4. 标题层级与章节上下文

### 4.1 章节树

按阅读顺序维护标题栈：

```text
H1 → H2 → H3
```

正文、列表、表格和图片均继承当前 `section_path`。

示例：

```json
{
  "block_type": "text",
  "text": "Revenue increased by ...",
  "metadata": {
    "section_path": [
      "2 Financial Results",
      "2.3 Revenue Analysis"
    ]
  }
}
```

### 4.2 检索文本

构造 `retrieval_text` 时加入：

```text
section_path
+ block_type
+ caption / headers
+ block text
```

示例：

```text
[Section: 2 Financial Results > 2.3 Revenue Analysis]
[Type: text]
Revenue increased by ...
```

不得把整份文档标题树重复拼入每个 block。

---

## 5. 页眉、页脚与重复内容过滤

实现轻量 `BoilerplateDetector`。

### 5.1 检测规则

对每页顶部和底部区域的 block：

1. 文本归一化；
2. 统计跨页重复频率；
3. 若在较多页面重复且 bbox 位于顶部/底部，则标记 `is_boilerplate = true`；
4. 页码单独保存到 page metadata；
5. 默认不进入 BM25 / Dense 索引，或给予显著降权。

### 5.2 不应过滤

以下内容即使重复，也不能自动删除：

- 表格列名；
- 章节标题；
- 法律条款编号；
- 表单字段名；
- 跨页表头。

规则必须结合：

```text
位置 + 重复率 + block_type
```

而不是只按文本重复判断。

---

## 6. 表格结构保留

### 6.1 表格 EvidenceBlock

除 `text` 和 `table_html` 外，尽量保留：

```json
{
  "headers": ["Year", "Revenue", "Growth"],
  "rows": [
    ["2022", "100", "5%"],
    ["2023", "130", "30%"]
  ],
  "caption": "Table 2 Revenue Summary",
  "row_count": 2,
  "column_count": 3,
  "unit": "USD million",
  "cell_locations": {
    "r1c2": {"row": 1, "col": 2}
  }
}
```

### 6.2 表格检索文本

使用：

```text
caption
+ headers
+ row-wise text
+ unit
```

不要只保存连续 OCR 文本。

### 6.3 MVP 边界

Phase 2 只要求：

- 标准表格可解析；
- HTML/Markdown 可保存；
- 表头与行数据可检索；
- page/table/block 位置可引用。

以下问题留到后续：

- 多级表头；
- 跨页表格完整拼接；
- rowspan / colspan 精确恢复；
- 数值计算和 calculator；
- TAT-QA 专项训练。

---

## 7. 图片、图注与附近文本

Phase 2 不要求完成视觉理解，但必须保留图片上下文。

每个 image block 保存：

```json
{
  "block_type": "image",
  "image_path": "...",
  "bbox": [100, 200, 800, 700],
  "text": "图注 + 附近文本",
  "metadata": {
    "caption_block_id": "...",
    "nearby_block_ids": ["...", "..."],
    "visual_understanding_available": false
  }
}
```

要求：

- 图注与图片建立关联；
- 保存前后最近文本 block；
- 检索时可使用图注和附近文本；
- 未接入 VLM 时，不生成虚假的视觉内容摘要。

---

## 8. Context Expansion

新增检索后上下文扩展模块：

```text
directly retrieved block
→ parent heading
→ previous / next block
→ table caption / figure caption
```

### 8.1 接口

```python
class ContextExpander:
    def expand(
        self,
        *,
        retrieved: list[RetrievalCandidate],
        block_store: BlockStore,
        max_added_blocks: int = 4,
        max_total_chars: int = 6000,
    ) -> list[EvidenceBlock]:
        ...
```

### 8.2 扩展规则

优先级：

1. 父级标题；
2. 表格/图片 caption；
3. 前一个相邻正文块；
4. 后一个相邻正文块；
5. 跨页 continuation block。

### 8.3 Trace

区分：

```text
retrieval_source = direct
retrieval_source = context_expansion
```

扩展 block 不计入 Recall@K 直接检索指标，只用于 Answer Policy 上下文。

---

## 9. 跨页关系的最低实现

Phase 2 不要求完整解决跨页内容，但必须提供简单支持。

### 9.1 文本连续性

若：

- 当前页最后一个 text block 没有完整终止符；
- 下一页第一个 block 不是 heading；
- 两块语义/格式连续；

则可标记：

```text
continued_by
continuation_of
cross_page_group_id
```

### 9.2 续表检测

检测：

```text
continued
续表
table continued
```

并关联相邻页 table block。

无法可靠合并时：

- 不强制合并；
- 保留关系；
- Context Expansion 时同时返回相邻表格。

---

## 10. 解析质量检查

每个文档生成 `ingestion_report.json`：

```json
{
  "doc_id": "...",
  "page_count": 20,
  "block_count": 180,
  "block_type_counts": {
    "heading": 20,
    "text": 130,
    "table": 8,
    "image": 10,
    "caption": 12
  },
  "empty_pages": [],
  "unknown_block_count": 2,
  "boilerplate_block_count": 18,
  "bbox_error_count": 0,
  "reading_order_warning_count": 1,
  "table_parse_warning_count": 2,
  "image_missing_count": 0,
  "parse_success": true
}
```

### 10.1 Warning 条件

以下情况必须记录：

- 页面无 block；
- 页面文本量异常低；
- bbox 越界；
- reading order 重复或缺失；
- table HTML 为空；
- image_path 不存在；
- heading 层级跳跃异常；
- unknown block 比例过高。

### 10.2 Ready 条件

文档仅在满足以下条件后标记为 `index_status = ready`：

- 至少存在 1 个可检索 block；
- block_id 全部唯一；
- page/location 可回查；
- parser 未出现 fatal error；
- EvidenceBlock 文件可重新加载。

---

## 11. 检索接入要求

### 11.1 默认不索引

- `is_boilerplate = true`；
- 空文本 image block；
- unknown 且无有效文本的 block。

### 11.2 默认索引

- heading；
- text；
- list_item；
- table；
- caption；
- 有 caption/附近文本的 image。

### 11.3 Answer Policy 输入

最终 evidence 顺序：

```text
直接召回候选
→ 各候选对应的父标题和邻接上下文
```

避免所有扩展块集中放在 prompt 尾部。

---

## 12. 新增测试

至少新增：

```text
tests/test_heading_hierarchy.py
tests/test_boilerplate_detector.py
tests/test_table_structure_conversion.py
tests/test_image_caption_linking.py
tests/test_context_expansion.py
tests/test_cross_page_relations.py
tests/test_ingestion_quality_report.py
```

测试覆盖：

- 标题树和 section_path；
- 页眉页脚标记；
- 正文重复内容不误删；
- 表头与行数据保留；
- 图片与图注关联；
- 前后文扩展；
- 跨页关系；
- quality warning；
- stable block_id；
- reload 后关系不丢失。

---

## 13. 补充验收标准

### 13.1 结构保留

- [ ] heading/text/list/table/image/caption 可区分；
- [ ] 正文可获得 section_path；
- [ ] block 有 previous/next 关系；
- [ ] table 保留 headers/rows 或等价结构；
- [ ] image 可关联 caption 和附近文本；
- [ ] 页眉页脚可识别并降权/过滤；
- [ ] parsing report 可输出异常。

### 13.2 检索与上下文

- [ ] retrieval_text 包含必要章节信息；
- [ ] boilerplate 默认不进入 top-k；
- [ ] Context Expansion 可附加父标题和邻接块；
- [ ] expanded block 与 direct block 可区分；
- [ ] final location 仍引用真实 block；
- [ ] 不破坏 Phase 1 location check。

### 13.3 真实文档人工核验

对 Phase 2 的 3 份真实文档核验：

- [ ] 标题层级基本正确；
- [ ] 阅读顺序基本可用；
- [ ] 页眉页脚未主导检索；
- [ ] 至少一个表格保持行列结构；
- [ ] 至少一个图片保留图注关系；
- [ ] 一个需要前后文的问题可通过 Context Expansion 回答；
- [ ] ingestion report 与实际问题一致。

---

## 14. 禁止的简化

1. 不得只读取 MinerU Markdown 后固定字符切片；
2. 不得丢弃 page、bbox、reading_order；
3. 不得把所有 block 统一为 `text`；
4. 不得把表格仅压平成无结构字符串；
5. 不得把图片 OCR 文本冒充视觉理解结果；
6. 不得将页眉页脚全部入库而不做标记；
7. 不得为了简化 prompt 删除 section_path；
8. 不得把 Context Expansion 结果计入直接检索 Recall@K；
9. 不得强行合并不确定的跨页表格；
10. 不得在 parser warning 存在时静默标记为完全成功。

---

## 15. 推荐实施顺序

```text
1. 扩展 EvidenceBlock metadata
2. MinerU block 类型映射
3. heading hierarchy / section_path
4. previous / next 邻接关系
5. boilerplate detector
6. table structure conversion
7. image-caption linking
8. context expansion
9. cross-page relation MVP
10. ingestion quality report
11. 检索和 workflow 接入
12. 单元测试与 3 份真实文档人工验收
```

---

## 16. Codex 执行摘要

```text
对 DocAgent Phase 2 增加“结构感知 PDF 解析与上下文保留”补充实现。

重点不是扩大项目范围，而是避免 MinerU 最终退化为 Markdown 转文本后固定切片。

必须补充：
1. heading/text/list/table/image/caption 类型化 EvidenceBlock；
2. section_id、section_path、heading_level；
3. parent/previous/next/container 关系；
4. 页眉页脚 boilerplate 检测与过滤；
5. 表格 headers/rows/caption/unit 等结构；
6. image-caption-nearby text 关联；
7. Context Expansion：父标题 + 相邻块 + caption；
8. 最低限度跨页 continuation 关系；
9. ingestion_report 解析质量检查；
10. 相应单元测试和 3 份真实文档人工验收。

保持 Phase 1 AnswerPolicy、reward、checkpoint 和评测不变。
保持 Phase 2 的 BGE-M3、RRF、Reranker、CLI 和 SQLite 主任务不变。
优先完成可用结构化文档问答闭环，不做复杂视觉训练或跨页表格算法研究。
```
