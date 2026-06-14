# PKA 向量生成质量修复 — 实现方案 v2

> 审计日期: 2026-06-13
> 审计结论: 核心问题不是向量模型或检索算法，而是 **PDF 入库质量无门禁**
> v2 变更: 按 Codex 评审意见调整优先级，增加 P0 质量门禁 + OCR fallback + reindex 策略

---

## 目录

- [第一部分：重新审视根因](#part-1)
- [P0-1: PDF 解析质量门禁](#p0-1)
- [P0-2: 移除 PDF `## Page N` 硬前缀](#p0-2)
- [P0-3: bge-m3 query prefix 配置化](#p0-3)
- [P1-1: OCR fallback + 水印清洗](#p1-1)
- [P1-2: 上传结果质量分级展示](#p1-2)
- [P1-3: breadcrumb + embedding_text / display_text 分离](#p1-3)
- [P2-1: 滑动窗口句子边界切分](#p2-1)
- [P3-1: embedding 并发 + 写入补偿式一致性](#p3-1)
- [附录 A: Reindex 策略](#appendix-a)
- [附录 B: 测试策略](#appendix-b)

---

## <a id="part-1"></a>第一部分：重新审视根因

### 当前链路故障分析

```
上传 PDF
  → PyMuPDF get_text() 提取文本层
    → 如果 PDF 文本层为空/只有页码/主要是水印
      → parser 插入 ## Page N（触发 H2 切分）
        → chunker 产出大量 1 行 chunk（页码）、水印 chunk（重复文本）、空 chunk
          → bge-m3 对这些无用文本生成了向量
            → 检索时这些"脏向量"占满 top-K，挤掉真正有语义内容的结果
              → 用户感觉"向量质量差"
```

**真正的问题不是 bge-m3，不是 ChromaDB，不是 RRF——是入库的文本本身已经不可用。**

### 为什么之前没发现

当前 parser 逻辑对 PDF 无条件提取 + 无条件分块 + 无条件入库。没有任何一步检查提取出来的文本是否"可入"。以下三类 PDF 会被当前链路无声地导入脏数据：

| PDF 类型 | 文本层状态 | 当前行为 |
|---|---|---|
| 扫描版 PDF | 文本层为空 | 每页一个 `## Page N` → chunk 仅含 `## Page N`（废话 chunk） |
| 部分文本 + 水印 PDF | 文本层有内容但混入水印重复文本 | 水印被当作真实内容分块入库 |
| 页码密集型 PDF | 每页含页码但内容极少 | 大量 "Page N" / "第 N 页" chunk 污染索引 |

### v2 方案核心变化

| 维度 | v1 | v2 |
|---|---|---|
| 定位 | 向量检索优化 | PDF 入库质量治理 |
| P0 | instruction prefix + 去 ## Page N | 质量门禁 + 去 ## Page N + prefix 配置化 |
| 新增模块 | 无 | `engine/quality.py` — 质量检测 + 水印清洗 |
| OCR 角色 | 仅用于图片文件 | 扩展为 PDF 的降级通道 |
| breadcrumb | 写入 chunk.text | 分离 embedding_text / display_text |
| reindex | 未提及 | 已入库 322 chunk 的清理策略 |

---

## <a id="p0-1"></a>P0-1: PDF 解析质量门禁

### 问题

当前 `_parse_pdf()` 对任何 PDF 无差别提取 + 入库。扫描版 PDF（文本层为空）、水印 PDF（文本全是被重复水印污染）、页码 PDF（每页只有一个数字）会无声地产生大量无效 chunk，污染向量库和 FTS5。

### 新增模块

`engine/quality.py` — PDF 解析结果质量评估

### 具体方案

**Step 1:** `ParseResult` 扩展 quality 字段

```python
# engine/models.py — ParseResult 追加 quality 字段

@dataclass(frozen=True)
class ParseResult:
    text: str
    source_name: str
    source_type: str
    metadata: Dict[str, Any]
    quality: Optional["ParseQuality"] = None  # 新增


@dataclass(frozen=True)
class ParseQuality:
    status: str           # "high" | "low" | "needs_ocr" | "rejected"
    valid_ratio: float    # 有效文本占比 (0.0-1.0)
    short_chunk_pct: float  # 短 chunk (<50 chars) 占比
    watermark_ratio: float  # 疑似水印文本占比
    reasons: List[str]    # 判定理由
```

**Step 2:** 质量检测器

```python
# engine/quality.py (新文件)

import re
from typing import List, Tuple
from engine.models import ParseQuality


# 水印/页码/空白行特征模式
WATERMARK_PATTERNS = [
    re.compile(r'http[s]?://\S+', re.IGNORECASE),
    re.compile(r'仅供\S*参考', re.IGNORECASE),
    re.compile(r'Confidential|Internal Use Only', re.IGNORECASE),
    re.compile(r'第\s*\d+\s*页', re.IGNORECASE),
    re.compile(r'Page\s*\d+', re.IGNORECASE),
    re.compile(r'^\d{1,3}$', re.MULTILINE),          # 纯页码行
    re.compile(r'扫描全能王|CamScanner|Adobe Scan', re.IGNORECASE),
]

# 重复行检测阈值（同一行出现超过此比例视为水印）
REPEATED_LINE_THRESHOLD = 0.3


def assess_pdf_quality(text: str) -> ParseQuality:
    """
    评估 PDF 解析文本质量。
    返回 ParseQuality 供调用方决定是否入库、是否需要 OCR。
    """
    reasons: List[str] = []
    
    # 空内容检测
    if not text or not text.strip():
        return ParseQuality(
            status="needs_ocr",
            valid_ratio=0.0,
            short_chunk_pct=1.0,
            watermark_ratio=0.0,
            reasons=["文本层为空，需要 OCR"],
        )
    
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ParseQuality(
            status="needs_ocr",
            valid_ratio=0.0,
            short_chunk_pct=1.0,
            watermark_ratio=0.0,
            reasons=["无可提取文本行，需要 OCR"],
        )
    
    total_lines = len(lines)
    
    # 1) 极短行占比
    short_lines = [line for line in lines if len(line) < 10]
    short_ratio = len(short_lines) / total_lines
    
    # 2) 水印行占比
    watermark_count = 0
    for line in lines:
        for pattern in WATERMARK_PATTERNS:
            if pattern.search(line):
                watermark_count += 1
                break
    
    # 3) 重复行检测
    line_freq: dict = {}
    for line in lines:
        norm = line.lower().strip()
        if len(norm) > 3:  # 忽略过短行
            line_freq[norm] = line_freq.get(norm, 0) + 1
    repeated_count = sum(count for count in line_freq.values() if count > 3)
    repeated_ratio = repeated_count / total_lines if total_lines else 0
    
    watermark_ratio = max(watermark_count / total_lines, repeated_ratio)
    
    # 4) 有效文本占比
    valid_lines = total_lines - len(short_lines) - max(watermark_count, repeated_count)
    valid_ratio = max(0.0, valid_lines / total_lines) if total_lines else 0.0
    
    # 判定逻辑
    if valid_ratio < 0.1:
        status = "needs_ocr"
        reasons.append(f"有效文本占比 {valid_ratio:.1%}，低于 10%，建议 OCR")
    elif watermark_ratio > 0.5:
        status = "low"
        reasons.append(f"水印/页码占比 {watermark_ratio:.1%}，超过 50%")
    elif short_ratio > 0.6:
        status = "low"
        reasons.append(f"极短行占比 {short_ratio:.1%}，超过 60%")
    elif valid_ratio > 0.5 and watermark_ratio < 0.2:
        status = "high"
    else:
        status = "low"
        reasons.append(f"有效文本 {valid_ratio:.1%}，水印 {watermark_ratio:.1%}")
    
    return ParseQuality(
        status=status,
        valid_ratio=round(valid_ratio, 3),
        short_chunk_pct=round(short_ratio, 3),
        watermark_ratio=round(watermark_ratio, 3),
        reasons=reasons,
    )
```

**Step 3:** `_parse_pdf()` 调用质量检测

```python
# engine/parser.py — _parse_pdf() 修改

def _parse_pdf(path: Path) -> ParseResult:
    import fitz
    from engine.quality import assess_pdf_quality

    document = fitz.open(path)
    pages: List[str] = []
    page_texts: List[str] = []  # 保留每页文本用于溯源
    try:
        for page_index, page in enumerate(document, start=1):
            page_text = page.get_text().strip()
            if page_text:
                pages.append(page_text)
            page_texts.append(page_text)
        page_count = document.page_count
    finally:
        document.close()

    full_text = "\n\n".join(pages)
    quality = assess_pdf_quality(full_text)

    return ParseResult(
        text=full_text,
        source_name=path.name,
        source_type="pdf",
        metadata={
            "page_count": page_count,
            "non_empty_pages": len(pages),
            "quality_status": quality.status,
        },
        quality=quality,
    )
```

**Step 4:** server.py 中根据 quality 决定入库策略

```python
# server.py — _ingest_upload_file() 中添加质量门禁

async def _ingest_upload_file(file: UploadFile, ocr):
    # ... 保存文件逻辑不变 ...
    
    parsed = await parse_file(str(output_path), mime_type=file.content_type, ocr_client=ocr)
    
    # --- 新增：PDF 质量门禁 ---
    quality = parsed.quality
    quality_action = "direct"  # 默认直接入库
    
    if quality is not None and quality.status == "needs_ocr":
        if ocr and ocr.endpoint and ocr.api_key:
            # OCR fallback: 用 OCR 重新提取
            ocr_text = await ocr.extract([str(output_path)])
            if ocr_text and len(ocr_text.strip()) > 50:
                parsed = ParseResult(
                    text=ocr_text,
                    source_name=parsed.source_name,
                    source_type=parsed.source_type,
                    metadata={**parsed.metadata, "ocr_fallback": True},
                )
                quality_action = "ocr"
            else:
                # OCR 也失败，标记为低质量但不阻塞入库
                parsed.metadata["quality_status"] = "degraded"
                parsed.metadata["ocr_fallback_failed"] = True
                quality_action = "degraded"
        else:
            # 无 OCR 客户端，标记低质量但入库
            parsed.metadata["quality_status"] = "needs_ocr"
            quality_action = "warn_needs_ocr"
    
    elif quality is not None and quality.status == "low":
        # 低质量但可入库，前端展示警告
        parsed.metadata["quality_status"] = "low"
        quality_action = "warn_low"
    # --- 门禁结束 ---
    
    chunks = _chunk(parsed.text, parsed.source_name, parsed.source_type)
    raw_file_path = str(output_path.relative_to(Path(runtime.config["data_dir"])))
    count = runtime.indexer.upsert(chunks, raw_file_paths=[raw_file_path] * len(chunks))
    
    return {
        "chunks": count,
        "source_name": parsed.source_name,
        "content_type": file.content_type,
        "raw_file_path": raw_file_path,
        "chunk_ids": [chunk.id for chunk in chunks],
        "quality": {
            "action": quality_action,
            "status": quality.status if quality else "unknown",
            "reasons": quality.reasons if quality else [],
        },
    }
```

### 关键设计决策

质量门禁**不直接拒绝入库**——即使用户误传差质量 PDF，数据仍在库中（标记为 `needs_ocr` / `low`），用户可以：
1. 看到前端警告后删除该文件
2. 配置 OCR 后重新上传
3. 接受低质量检索结果

这避免了"过于激进地拒绝用户数据"的风险。

### 验收

- 上传文本层为空的扫描版 PDF → 返回 `quality.action = "warn_needs_ocr"`（OCR 未配置时）
- 上传文本层为空的扫描版 PDF（OCR 已配置）→ 返回 `quality.action = "ocr"`
- 上传含大量水印的 PDF → 返回 `quality.status = "low"`
- 上传内容完整的 PDF → 返回 `quality.action = "direct"`

---

## <a id="p0-2"></a>P0-2: 移除 PDF `## Page N` 硬前缀

### 问题

与 v1 一致。`parser.py` 为每页强制插入 `## Page N`，chunker 检测到 `## ` 触发 H2 切分，短页产生无意义 chunk。

### 改动范围

`engine/parser.py` — `_parse_pdf()`，删除 `.append(f"## Page {page_index}\n{page.get_text().strip()}")` 这一行，改为 `.append(page.get_text().strip())`。

具体代码见 P0-1 的 Step 3，已包含此修改。

### 验收

- 普通 PDF 上传后 chunk 内容不再包含 `## Page N`
- 多页跨段落内容不被截断
- metadata 中 page_count 和 non_empty_pages 正确

---

## <a id="p0-3"></a>P0-3: bge-m3 query prefix 配置化

### 问题

与 v1 一致，但按 Codex 意见改为**配置化**——prefix 仅在 BGE 类模型启用，通过 config.yaml 控制。

### 改动范围

`engine/indexer.py` — `OllamaEmbeddingClient`  
`engine/config.py` — `DEFAULT_CONFIG`  
`config.yaml` — 新增字段

### 具体方案

**Step 1:** config 新增 `embedding.query_prefix`

```python
# engine/config.py — DEFAULT_CONFIG 追加

DEFAULT_CONFIG = {
    # ... 现有配置 ...
    "embedding": {
        "host": "http://localhost:11434",
        "model": "bge-m3",
        "query_prefix": "",  # 新增：检索侧 instruction prefix
    },
    # ...
}
```

`config.yaml` 用户侧值：

```yaml
embedding:
  host: http://localhost:11434
  model: bge-m3
  query_prefix: "Represent this sentence for searching relevant passages: "
```

> 用户切换为非 BGE 模型时清空此字段即可。

**Step 2:** `OllamaEmbeddingClient` 读取配置

```python
# engine/indexer.py — OllamaEmbeddingClient 修改

class OllamaEmbeddingClient:
    def __init__(
        self,
        host: str = "http://localhost:11434",
        model: str = "bge-m3",
        query_prefix: str = "",  # 新增参数
    ):
        self.host = host
        self.model = model
        self.query_prefix = query_prefix

    def embed_query(self, query: str) -> List[float]:
        """检索侧向量化 — 仅在配置了 query_prefix 时添加前缀"""
        if self.query_prefix:
            query = self.query_prefix + query
        return self._embed_one(query)

    def embed(self, texts: List[str]) -> List[List[float]]:
        """入库侧向量化 — 永远不加前缀"""
        vectors = []
        for text in texts:
            vectors.append(self._embed_one(text))
        return vectors
```

**Step 3:** `HybridIndexer` 透传参数

```python
# engine/indexer.py — HybridIndexer.__init__() 修改

class HybridIndexer:
    def __init__(
        self,
        fts_db_path: str,
        vector_dir: str,
        collection_name: str,
        embedding_client: Optional[Any] = None,
        query_prefix: str = "",  # 新增
    ):
        # ...
        if embedding_client is None:
            embedding_client = OllamaEmbeddingClient(query_prefix=query_prefix)
        self.embedding_client = embedding_client
        # ...
```

**Step 4:** `server.py` 传递 query_prefix

```python
# server.py — Runtime._build_indexer() 修改

def _build_indexer(self) -> HybridIndexer:
    return HybridIndexer(
        fts_db_path=self.config["fts5"]["db_path"],
        vector_dir=self.config["chroma"]["persist_dir"],
        collection_name=self.config["chroma"]["collection_name"],
        query_prefix=self.config["embedding"].get("query_prefix", ""),
    )
```

**Step 5:** `search_vector` 改用 `embed_query`

```python
# engine/indexer.py — HybridIndexer.search_vector()

def search_vector(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
    if self.collection.count() == 0:
        return []
    query_vector = self.embedding_client.embed_query(query)  # 改这里
    # ... 后续不变
```

### 验收

- `query_prefix` 为空时行为与当前一致
- `query_prefix` 配置后，Ollama /api/embeddings 请求中的 prompt 被加上前缀
- 确保入库侧的 embed() **不加**前缀（通过测试验证）

---

## <a id="p1-1"></a>P1-1: OCR fallback + 水印清洗

### 问题

当前 OCR 仅在文件类型为 image/* 时启用。扫描版 PDF（文本层为空）不会触发 OCR，直接入库空文本。水印文本与真实内容混在一起被分块。

### 改动范围

`engine/ocr.py` — 新增 PDF OCR 方法  
`engine/quality.py` — 新增水印清洗函数  
`server.py` — 质量门禁中触发 OCR fallback

### 具体方案

**Step 1:** OCR 客户端支持 PDF 输入

```python
# engine/ocr.py — VolcengineOCR 新增方法

class VolcengineOCR:
    # ... 现有 __init__ 和 extract 不变 ...

    async def extract_pdf(self, pdf_path: str) -> str:
        """
        对 PDF 逐页截图后 OCR。
        策略：将 PDF 转为图片，批量发送 OCR。
        注意：需要 PyMuPDF 的 page.get_pixmap() 能力。
        """
        import fitz
        document = fitz.open(pdf_path)
        image_paths = []
        try:
            import tempfile
            tmp_dir = tempfile.mkdtemp(prefix="pka_ocr_pdf_")
            for page_index in range(min(document.page_count, self.max_pages)):
                page = document[page_index]
                pix = page.get_pixmap(dpi=150)
                img_path = f"{tmp_dir}/page_{page_index + 1:03d}.png"
                pix.save(img_path)
                image_paths.append(img_path)
            
            # 复用现有 extract 方法（逐批发送 OCR）
            text = await self.extract(image_paths)
            
        finally:
            document.close()
            import shutil
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)
        
        return text
```

> 注意：`max_pages` 上限（建议 50 页）避免 OCR 成本失控。超出部分提示"部分页面未 OCR"。

**Step 2:** 水印清洗

```python
# engine/quality.py — 追加水印清洗函数

def clean_text(text: str) -> str:
    """
    移除常见水印/页码行，保留有效内容。
    不改变原始文本结构，仅移除匹配行。
    """
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append("")
            continue
        if _is_watermark_line(stripped):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def _is_watermark_line(line: str) -> bool:
    """判断单行是否疑似水印/页码"""
    # 纯页码
    if re.match(r'^\d{1,3}$', line.strip()):
        return True
    # 页码格式
    if re.match(r'^(第\s*\d+\s*页|Page\s*\d+|-\s*\d+\s*-)$', line.strip(), re.IGNORECASE):
        return True
    # 常见水印关键词
    watermark_keywords = [
        '仅供', '机密', 'Confidential', 'Internal Use', '扫描全能王',
        'CamScanner', 'Adobe Scan', 'Created with', 'Powered by',
        'Evaluation Only', '试用版', '免费版',
    ]
    for kw in watermark_keywords:
        if kw.lower() in line.lower():
            return True
    return False
```

在 `_parse_pdf()` 提取文本后调用 `clean_text()`：

```python
# engine/parser.py — _parse_pdf() 中
full_text = "\n\n".join(pages)
full_text = clean_text(full_text)  # 新增：清洗水印
```

### 验收

- 包含 `仅供内部参考` 水印的 PDF 被清洗后无水印行
- 扫描版 PDF + OCR 已配置 → 自动 OCR fallback 成功提取文本
- OCR 结果文本长度 > 50 字符（表明真正提取到了内容）

---

## <a id="p1-2"></a>P1-2: 上传结果质量分级展示

### 问题

当前上传成功后前端仅显示"完成 · N 个片段"，用户无法知道上传的文件质量是否合格。

### 改动范围

`server.py` — 返回中追加 quality 字段（已在 P0-1 中实现）  
`static/app.js` — 渲染质量标记

### 具体方案

在现有 `formatIngestFeedback()` 和上传槽状态中追加质量标签：

```javascript
// static/app.js — formatIngestFeedback 扩展

function qualityBadge(result) {
  const q = result.quality || {};
  switch (q.action) {
    case "direct":    return { class: "is-high",   text: "高质量" };
    case "ocr":       return { class: "is-ocr",    text: "已 OCR" };
    case "warn_low":  return { class: "is-low",    text: "低质量" };
    case "warn_needs_ocr":
    case "degraded":  return { class: "is-warn",   text: "需 OCR" };
    default:          return null;
  }
}

function formatIngestFeedback(result, actionLabel) {
  if (!result || result.status !== "ok") {
    return `${actionLabel}失败。`;
  }
  const parts = [`${actionLabel}完成`];
  if (typeof result.chunks === "number") parts.push(`${result.chunks} 个片段`);
  if (result.source_name) parts.push(`来源：${result.source_name}`);
  
  // 新增质量标记
  const badge = qualityBadge(result);
  if (badge) parts.push(`[${badge.text}]`);
  
  const text = parts.join(" · ");
  
  // 低质量/需 OCR 时追加原因
  const reasons = result.quality?.reasons;
  if (reasons && reasons.length > 0 && badge && badge.class !== "is-high") {
    return text + "\n" + reasons.map(r => `⚠ ${r}`).join("\n");
  }
  return text;
}
```

各质量标签的 CSS（在 `static/style.css` 中追加）：

```css
.upload-slot.is-warn  { border-color: #e6a817; background: #fff8e6; }
.upload-slot.is-low   { border-color: #e67e22; background: #fff3e6; }
.upload-slot.is-ocr   { border-color: #3498db; background: #e8f4fd; }
```

### 验收

- 上传高质量 PDF → 显示 "[高质量]"
- 上传扫描版 PDF（无 OCR）→ 显示 "[需 OCR]" + warning 原因
- 上传低质量 PDF → 显示 "[低质量]" + 具体理由

---

## <a id="p1-3"></a>P1-3: breadcrumb + embedding_text / display_text 分离

### 问题

v1 中将 breadcrumb 直接写入 chunk.text，会同时影响 FTS 搜索结果（关键词检索时 breadcrumb 也参与匹配）和前端展示（用户看到 `[# 行业分析 > ## 市场规模]` 修饰符）。

按 Codex 意见，**短期不拆字段**，但需要让 breadcrumb 在用户可见的 chunk text 展示中去掉。

### 方案选择

**不拆 Chunk 数据模型**（改动面太大），采用标记格式：

```
// embedding_text（入库向量化用）:
"[BREADCRUMB]# 自动驾驶行业趋势 > ## 中国市场规模[/BREADCRUMB]\n\n### 细分数据\n..."

// display_text（前端展示用）:
"### 细分数据\n..."
```

生成 chunk 时同时存储两个版本：embedding 用带前缀的，前端展示时通过 `get_chunk()` 返回原始文本。

### 更简单的实现（推荐）

Chunk 模型新增一个可选字段 `embedding_text`，默认为 None 时使用 `text`：

```python
# engine/models.py — Chunk 扩展

@dataclass(frozen=True)
class Chunk:
    id: str
    text: str             # display_text — 前端展示用
    source_name: str
    source_type: str
    chunk_index: int
    created_at: str
    embedding_text: str = ""  # 向量化用；空时 fallback 到 text
```

```python
# engine/chunker.py — chunk_text() 修改

def chunk_text(...):
    # ...
    for breadcrumb, section_text in sections:
        display = section_text  # 展示文本不含 breadcrumb
        if breadcrumb:
            embedding = f"[BREADCRUMB]{breadcrumb}[/BREADCRUMB]\n\n{section_text}"
        else:
            embedding = section_text
        for window_text in _window_text(display, max_chunk_size, chunk_overlap):
            # ... 创建 Chunk 时:
            chunk = Chunk(
                id=...,
                text=window_text,          # display 用
                embedding_text=window_text if not breadcrumb else (
                    f"[BREADCRUMB]{breadcrumb}[/BREADCRUMB]\n\n{window_text}"
                ),
                # ...
            )
```

```python
# engine/indexer.py — upsert() 中向量化时使用 embedding_text

documents = []
embedding_texts = []
for chunk in chunks:
    documents.append(chunk.text)
    embedding_texts.append(chunk.embedding_text or chunk.text)

vectors = self.embedding_client.embed(embedding_texts)  # 向量化用 embedding_text

self.collection.upsert(
    ids=...,
    embeddings=vectors,
    documents=documents,  # 展示用 text
    metadatas=...,
)
```

### 验收

- 检索结果的 chunk text 中不含 `[BREADCRUMB]` 标记
- embedding 向量基于带 breadcrumb 的文本生成
- FTS5 中的 `text` 列（UNINDEXED）存储 display_text，`tokens` 列用 embedding 文本分词，保证关键词检索也不含 breadcrumb 干扰

> **注意**: 当前 FTS5 表结构中 `text` 字段是 UNINDEXED（仅存储不索引），`tokens` 是实际索引列。需将 tokens 列也切换为用 `chunk.text` 分词而非 `chunk.embedding_text`，避免 breadcrumb 影响关键词检索排序。

---

## <a id="p2-1"></a>P2-1: 滑动窗口句子边界切分

与 v1 的 P1-2 方案一致。

简化版实现：

```python
# engine/chunker.py — _window_text() 替换

def _window_text(text: str, max_chunk_size: int, chunk_overlap: int) -> Iterable[str]:
    cleaned = text.strip()
    if len(cleaned) <= max_chunk_size:
        yield cleaned
        return

    start = 0
    while start < len(cleaned):
        end = min(start + max_chunk_size, len(cleaned))

        # 不是最后一个窗口时，向前找句子边界
        if end < len(cleaned):
            # 向前回溯最多 200 字符找句号/换行
            for pos in range(end, max(start, end - 200), -1):
                if cleaned[pos - 1] in '。！？.!?\n':
                    end = pos
                    break

        yield cleaned[start:end]

        if end >= len(cleaned):
            break
        start = max(start + 1, end - chunk_overlap)
```

### 验收

- 长段落切分后每个中间 chunk 以。！？.!?\n 结尾

---

## <a id="p3-1"></a>P3-1: embedding 并发 + 写入补偿式一致性

### 问题

按 Codex 意见，这是**并发优化 + 补偿式一致性**，不是真批量也不是跨库原子事务。

### 改动范围

`engine/indexer.py` — `OllamaEmbeddingClient.embed()` 和 `HybridIndexer.upsert()`

### 具体方案

**并发 embedding（ThreadPoolExecutor）**

与 v1 的 P2-2 Step 1 方案一致，使用 ThreadPoolExecutor(4) 并行调用 `_embed_one()`。不赘述。

**补偿式一致性**

```python
# engine/indexer.py — upsert() 修改写入顺序

def upsert(self, chunks: List[Chunk], raw_file_paths: Optional[List[str]] = None) -> int:
    if not chunks:
        return 0
    
    vectors = self.embedding_client.embed([chunk.text for chunk in chunks])
    
    # 1) 先写 ChromaDB（主检索通道，不可丢）
    chroma_failed = []
    try:
        self.collection.upsert(
            ids=[chunk.id for chunk in chunks],
            embeddings=vectors,
            metadatas=...,
            documents=[chunk.text for chunk in chunks],
        )
    except Exception as exc:
        # ChromaDB 写入失败 → 向上抛异常，不入库
        raise RuntimeError(f"ChromaDB upsert failed: {exc}") from exc
    
    # 2) 补偿式写 FTS5（增强通道，失败不阻塞）
    try:
        with self._connect() as connection:
            for chunk in chunks:
                connection.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (chunk.id,))
                connection.execute("INSERT INTO chunks_fts(...)", ...)
    except Exception as exc:
        # FTS5 失败：记录异常，用户下次查询时自动退化到纯向量检索
        # 补偿策略：reindex 时可修复 FTS5 缺失
        import logging
        logging.warning(f"FTS5 write failed for {len(chunks)} chunks: {exc}")
        # 可选：将失败的 chunk_ids 写入补偿日志，供 reindex 使用
    
    return len(chunks)
```

**关键点：**
- ChromaDB 失败 → 整个 upsert 失败（因为向量检索是主通道）
- FTS5 失败 → ChromaDB 已写成功，FTS5 缺失。下一次查询时 hybrid_search 中 FTS5 返回空列表，RRF 自动退化到纯向量检索（天然降级）
- 补偿恢复：reindex 时可重建 FTS5

### 验收

- 正常场景：FTS5 + ChromaDB 均写入成功
- FTS5 写入失败模拟：检索仍可工作（纯向量模式），前端无报错
- ChromaDB 写入失败：返回明确错误

---

## <a id="appendix-a"></a>附录 A: Reindex 策略

当前已入库的 ~322 chunk 不会因代码修复自动变好。需要清理并重新录入。

### 手动 reindex（推荐先用这个）

```bash
# 1) 清空知识库
curl -X POST http://localhost:8086/api/ingest/clear

# 2) 删除旧的 raw 文件（可选，看是否需要保留原始文件）
# rm -rf ~/Documents/PKA_Data/raw/*

# 3) 用修复后的代码重新上传文件
# 通过 Web UI 或 CLI 逐个/批量重新录入
```

### CLI reindex 脚本（可选）

```python
# cli.py — 新增 reindex 子命令

def _reindex(config: Dict) -> int:
    """
    清空索引后重新扫描 raw/ 目录下所有文件并入库。
    """
    data_dir = Path(config["data_dir"])
    raw_dir = data_dir / "raw"
    
    if not raw_dir.exists():
        print(json.dumps({"status": "error", "message": "raw 目录不存在"}))
        return 1
    
    # 清空
    _post_json(base_url, "/api/ingest/clear", {})
    
    # 扫描所有文件
    files = list(raw_dir.rglob("*"))
    files = [f for f in files if f.is_file() and not f.name.startswith(".")]
    
    results = []
    for path in files:
        result = _post_file(base_url, "/api/ingest/file", path)
        results.append({
            "file": str(path.relative_to(raw_dir)),
            "status": result.get("status", "error"),
            "chunks": result.get("chunks", 0),
            "quality": result.get("quality", {}),
        })
    
    return _print_json({
        "status": "ok",
        "total": len(files),
        "results": results,
    })
```

---

## <a id="appendix-b"></a>附录 B: 测试策略

### 回归保护

| 测试文件 | 需要更新的用例 |
|---|---|
| `test_parser.py::test_parse_pdf_extracts_all_pages` | 不再检查 `## Page N` 字符串 |
| `test_chunker.py` (全部 6 个) | 全部需要验证通过 |
| `test_indexer_retriever.py` (全部 8 个) | 全部需要验证通过 |

### 新增测试

**tests/test_quality.py** (新文件)

```python
from engine.quality import assess_pdf_quality, clean_text


def test_empty_pdf_is_needs_ocr():
    q = assess_pdf_quality("")
    assert q.status == "needs_ocr"

def test_page_number_only_pdf_is_needs_ocr():
    q = assess_pdf_quality("1\n2\n3\n4\n5\n6\n7\n8\n9\n10\n11\n")
    assert q.status in ("needs_ocr", "low")

def test_watermark_heavy_pdf_is_low():
    text = "\n".join(["仅供内部参考 - 机密文档"] * 20 + ["实际内容只有一行"])
    q = assess_pdf_quality(text)
    assert q.status in ("low", "needs_ocr")

def test_clean_text_removes_watermark():
    text = "正常内容\n仅供内部参考\n另一段内容\n第 1 页"
    cleaned = clean_text(text)
    assert "仅供内部参考" not in cleaned
    assert "第 1 页" not in cleaned
    assert "正常内容" in cleaned
```

**tests/test_indexer_retriever.py 追加**

```python
def test_query_embedding_uses_prefix_when_configured(monkeypatch):
    captured = []

    def fake_embed_one(text):
        captured.append(text)
        return [0.1] * 1024

    client = OllamaEmbeddingClient(
        host="http://localhost:11434",
        model="bge-m3",
        query_prefix="TEST_PREFIX: ",
    )
    monkeypatch.setattr(client, "_embed_one", fake_embed_one)

    client.embed_query("测试查询")
    assert captured[0].startswith("TEST_PREFIX: ")


def test_embed_does_not_use_prefix(monkeypatch):
    captured = []

    def fake_embed_one(text):
        captured.append(text)
        return [0.1] * 1024

    client = OllamaEmbeddingClient(
        host="http://localhost:11434",
        model="bge-m3",
        query_prefix="TEST_PREFIX: ",
    )
    monkeypatch.setattr(client, "_embed_one", fake_embed_one)

    client.embed(["入库文本"])
    assert captured[0] == "入库文本"  # 不加前缀
```

---

## 实施顺序

| 批次 | 内容 | 改动文件 | 独立部署？ |
|---|---|---|---|
| **第1批 (P0)** | 质量门禁 + 去 ## Page N + query prefix | `quality.py`(新), `parser.py`, `models.py`, `indexer.py`, `config.py`, `config.yaml` | ✅ 可独立上线 |
| **第2批 (P1)** | OCR fallback + 质量展示 + breadcrumb 分离 | `ocr.py`, `server.py`, `static/app.js`, `chunker.py`, `models.py` | ✅ 依赖第1批 |
| **第3批 (P2+P3)** | 句子边界 + embedding 并发 + reindex | `chunker.py`, `indexer.py`, `cli.py` | ✅ 可独立上线 |

每批完成后需**清空索引 + 重新上传测试文件**进行端到端验证。

---

## 风险与回滚

| 风险 | 缓解 |
|---|---|
| 质量门禁误判正常 PDF 为 low | `threshold` 值保守设置，low 仍允许入库（仅警告） |
| OCR fallback 火山方舟成本 | `max_pages=50` 限制 + 仅 `needs_ocr` 时触发 |
| breadcrumb 分离增加 Chunk 字段 | `embedding_text` 默认为空字符串，向后兼容 |
| reindex 丢失用户已上传文件 | 不清除 `raw/` 目录，仅重建索引 |
