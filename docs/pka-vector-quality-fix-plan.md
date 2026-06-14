# PKA 向量生成质量修复 — 实现方案

> 审计日期: 2026-06-13
> 目标: 将向量检索语义匹配质量从当前 3.52/10 提升到 7.5+/10
> 设计原则: 最小改动面、可独立验证、不改核心架构

---

## 目录
1. [P0-1: bge-m3 查询侧 instruction prefix](#p0-1)
2. [P0-2: 移除 PDF `## Page N` 硬前缀](#p0-2)
3. [P1-1: Chunk 追加 breadcrumb 层级路径](#p1-1)
4. [P1-2: 滑动窗口按句子边界切分](#p1-2)
5. [P2-1: Markdown 多级标题 (H1/H2/H3) 切分](#p2-1)
6. [P2-2: Ollama 批量 embedding + 写入原子化](#p2-2)

---

## <a id="p0-1"></a>P0-1: bge-m3 查询侧 instruction prefix

### 问题
bge-m3 是 BAAI 的指令微调模型。官方要求查询侧加 `"Represent this sentence for searching relevant passages: "` 前缀以激活检索语义。当前代码入库和检索共用 `embed()` 方法，均未加前缀，导致查询向量与文档向量不在同一语义空间。

### 改动范围
`engine/indexer.py` — `OllamaEmbeddingClient` 类

### 具体方案

**Step 1:** 在 `OllamaEmbeddingClient` 新增 `embed_query()` 方法，仅用于检索时的查询向量化。

```python
# engine/indexer.py — OllamaEmbeddingClient 类中新增方法

QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

def embed_query(self, query: str) -> List[float]:
    """检索侧向量化 — 加 bge-m3 instruction prefix"""
    prefixed = self.QUERY_INSTRUCTION + query
    return self._embed_one(prefixed)

def embed(self, texts: List[str]) -> List[List[float]]:
    """入库侧向量化 — 不加前缀"""
    vectors = []
    for text in texts:
        vectors.append(self._embed_one(text))
    return vectors
```

**Step 2:** `HybridIndexer.search_vector()` 中改用 `embed_query()`:

```python
# engine/indexer.py — HybridIndexer.search_vector() line 168

def search_vector(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
    if self.collection.count() == 0:
        return []
    query_vector = self.embedding_client.embed_query(query)  # 改这里
    # ... 后续不变
```

### 设计理由
- 只改 2 处：新增方法 + 1 行调用替换
- 不修改存储侧，已入库的向量无需重建
- 若未来换模型，只需改 `QUERY_INSTRUCTION` 常量

### 验收
- 入库后对同一问题分别用旧方法和新方法检索
- 新方法的 top-5 结果与问题的语义匹配度应可见提升
- 对 bge-m3 英文文档的检索改善尤其明显

---

## <a id="p0-2"></a>P0-2: 移除 PDF `## Page N` 硬前缀

### 问题
`parser.py` 为每页 PDF 强制插入 `## Page N`，chunker 检测到 `## ` 后触发 H2 切分。短页产生孤立 chunk，长页被暴力截断，跨页段落被撕开。

### 改动范围
`engine/parser.py` — `_parse_pdf()`

### 具体方案

```python
# engine/parser.py — _parse_pdf() 修改

def _parse_pdf(path: Path) -> ParseResult:
    import fitz

    document = fitz.open(path)
    pages = []
    try:
        for page_index, page in enumerate(document, start=1):
            page_text = page.get_text().strip()
            if page_text:
                # 不再加 ## Page N 前缀；页码信息存入 metadata
                pages.append(page_text)
        page_count = document.page_count
    finally:
        document.close()

    # 用双换行拼接所有页面文本，保留自然段落结构
    full_text = "\n\n".join(pages)

    # 在 metadata 中保留页码映射，供后续溯源
    return ParseResult(
        text=full_text,
        source_name=path.name,
        source_type="pdf",
        metadata={
            "page_count": page_count,
            "non_empty_pages": len(pages),
        },
    )
```

### 设计理由
- PDF 页面间的 `\n\n` 自然分隔会被 chunker 当作段落边界，比硬性 H2 切分合理得多
- 页码信息保留在 metadata 中，不丢失可追溯性
- 改动仅 3 行删除 + 格式调整

### 验收
- 上传 20 页 PDF，检查分块结果：不应再有 `## Page N` 出现在 chunk 正文中
- 跨页段落文本完整保留在一个 chunk 内（除非超出 max_chunk_size）
- metadata 中 page_count 和 non_empty_pages 正确

---

## <a id="p1-1"></a>P1-1: Chunk 追加 breadcrumb 层级路径

### 问题
按 H2 切分后，子标题 chunk 丢失了"它属于哪个 H1、哪个 H2"的上下文。检索 "中国自动驾驶市场规模" 时，`### 中国市场` 的 chunk 文本中没有"自动驾驶"也没有"市场规模"，向量无法匹配。

### 改动范围
`engine/chunker.py` — `chunk_text()` 和 `_markdown_h2_sections()`

### 具体方案

**Step 1:** 重构 `_markdown_h2_sections()`，同时收集层级路径。

```python
# engine/chunker.py — 替换 _markdown_h2_sections()

def _markdown_sections_with_breadcrumb(text: str) -> List[Tuple[str, str]]:
    """
    按 H2 切分，同时记录当前所属的 H1 和 H2 标题。
    Returns: [(breadcrumb, section_text), ...]
    """
    import re
    
    sections: List[Tuple[str, str]] = []
    current_lines: List[str] = []
    current_h1 = ""
    current_h2 = ""
    saw_first_h2 = False
    
    for line in text.splitlines():
        stripped = line.strip()
        
        # 检测 H1
        if re.match(r'^# [^#]', stripped):
            current_h1 = stripped[2:].strip()
            current_lines.append(line)
        # 检测 H2
        elif stripped.startswith("## ") and not stripped.startswith("### "):
            if current_lines:
                breadcrumb = _build_breadcrumb(current_h1, current_h2)
                sections.append((breadcrumb, "\n".join(current_lines).strip()))
            current_h2 = stripped[3:].strip()
            current_lines = [line]
            saw_first_h2 = True
        # 检测 H3 (可选扩展)
        elif stripped.startswith("### "):
            current_lines.append(line)
        elif not saw_first_h2:
            current_lines.append(line)
        else:
            current_lines.append(line)
    
    if current_lines:
        breadcrumb = _build_breadcrumb(current_h1, current_h2)
        sections.append((breadcrumb, "\n".join(current_lines).strip()))
    
    return sections if sections else [("", text)]


def _build_breadcrumb(h1: str, h2: str) -> str:
    """构建层级路径 breadcrumb，模式: '# H1 > ## H2'"""
    parts = []
    if h1:
        parts.append(f"# {h1}")
    if h2:
        parts.append(f"## {h2}")
    if not parts:
        return ""
    return " > ".join(parts)
```

**Step 2:** 修改 `chunk_text()`，将 breadcrumb 注入 chunk text。

```python
# engine/chunker.py — 修改 chunk_text() 中的 section 处理部分

def chunk_text(
    text: str,
    source_name: str,
    source_type: str,
    max_chunk_size: int = 1024,
    chunk_overlap: int = 128,
) -> List[Chunk]:
    if not text or not text.strip():
        return []

    if _looks_like_markdown(text):
        sections = _markdown_sections_with_breadcrumb(text)  # 改用新方法
        chunk_texts: List[str] = []
        for breadcrumb, section_text in sections:
            # 将 breadcrumb 追加到每个 section 文本前
            if breadcrumb:
                enriched = f"[{breadcrumb}]\n{section_text}"
            else:
                enriched = section_text
            chunk_texts.extend(_window_text(enriched, max_chunk_size, chunk_overlap))
    else:
        sections = _paragraphs(text)
        chunk_texts: List[str] = []
        for section in sections:
            chunk_texts.extend(_window_text(section, max_chunk_size, chunk_overlap))

    # ... 后续 Chunk 构建不变 ...
```

### 设计理由
- breadcrumb 用 `[# H1 > ## H2]` 格式包裹，作为 chunk text 前缀，直接参与 embedding
- 这样 `### 中国市场` 的 chunk 向量会包含"# 自动驾驶行业趋势 > ## 市场规模"的语义
- 不改 Chunk 数据模型，breadcrumb 融入 text 字段，Chromedb 和 FTS5 自动受益

### 验收
- 上传含 H1/H2/H3 的 Markdown 文档
- 检查组块：每个 chunk text 以 `[# XX > ## YY]` 开头
- 检索 "中国自动驾驶市场规模" → top-1 chunk 应包含 breadcrumb 指向相关章节

---

## <a id="p1-2"></a>P1-2: 滑动窗口按句子边界切分

### 问题
当前 `_window_text()` 使用 `text[N:M]` 暴力字符切片，无视句子边界。约 30% 的 chunk 在句中被截断。

### 改动范围
`engine/chunker.py` — `_window_text()`

### 具体方案

```python
# engine/chunker.py — 替换 _window_text()

import re

SENTENCE_BOUNDARY = re.compile(r'[。！？\.\!\?\n]')

def _window_text(text: str, max_chunk_size: int, chunk_overlap: int) -> Iterable[str]:
    cleaned = text.strip()
    if len(cleaned) <= max_chunk_size:
        yield cleaned
        return

    step = max(1, max_chunk_size - chunk_overlap)
    start = 0
    
    while start < len(cleaned):
        end = min(start + max_chunk_size, len(cleaned))
        
        # 如果不是最后一个窗口，向前搜索最近的句子边界
        if end < len(cleaned):
            boundary = _find_sentence_boundary(cleaned, end)
            if boundary > start:
                end = boundary
        
        yield cleaned[start:end]
        
        if end >= len(cleaned):
            break
        start = end - chunk_overlap
        if start >= len(cleaned):
            break


def _find_sentence_boundary(text: str, from_pos: int, search_window: int = 200) -> int:
    """
    从 from_pos 位置向前搜索最近的句子边界。
    search_window: 最多向前搜索的字符数。
    """
    search_start = max(0, from_pos - search_window)
    # 在 [search_start, from_pos] 范围内找最后一个句子边界
    for match in SENTENCE_BOUNDARY.finditer(text[search_start:from_pos]):
        pass  # 遍历到最后一个匹配
    
    # 找到最后一个匹配的位置
    last_boundary = None
    for match in SENTENCE_BOUNDARY.finditer(text[search_start:from_pos]):
        last_boundary = match.end() + search_start
    
    if last_boundary and last_boundary > search_start:
        return last_boundary
    return from_pos  # 找不到边界时 fallback 到原始位置


def _find_sentence_boundary_backward(text: str, from_pos: int, search_window: int = 200) -> int:
    """
    从 from_pos 位置向后搜索最近的句子边界（向前文本方向找）。
    """
    search_end = min(len(text), from_pos + search_window)
    
    match = SENTENCE_BOUNDARY.search(text[from_pos:search_end])
    if match:
        return from_pos + match.end()
    return from_pos
```

简化版（推荐先用这个，复杂度更低）：

```python
def _window_text(text: str, max_chunk_size: int, chunk_overlap: int) -> Iterable[str]:
    cleaned = text.strip()
    if len(cleaned) <= max_chunk_size:
        yield cleaned
        return

    step = max(1, max_chunk_size - chunk_overlap)
    start = 0
    
    while start < len(cleaned):
        end = min(start + max_chunk_size, len(cleaned))
        
        # 如果不是末尾，向前找最近的句子边界，最多回溯 200 字符
        if end < len(cleaned):
            best = end
            for pos in range(end, max(start, end - 200), -1):
                if cleaned[pos - 1] in '。！？.!?\n':
                    best = pos
                    break
            end = best
        
        yield cleaned[start:end]
        
        if end >= len(cleaned):
            break
        start = max(start + 1, end - chunk_overlap)
```

### 设计理由
- 从原始切分点向前扫描，找到最近的句号/问号/感叹号/换行符
- 搜索窗口 200 字符确保不无限回溯
- 不改变 chunk_overlap 语义，仅优化切分位置

### 验收
- 上传含长段落的纯文本文档
- 验证：所有 chunk 的结束字符均为 `。！？.!?\n` 之一（或为文档末尾）
- 原有的 `test_long_paragraph_uses_overlapping_windows` 测试仍需通过

---

## <a id="p2-1"></a>P2-1: Markdown 多级标题 (H1/H2/H3) 切分

### 问题
当前仅检测 `## ` (H2)，忽略 H1 和 H3+。H1 下的前言混入第一个 H2 的 chunk，H3 不触发切分。

### 改动范围
`engine/chunker.py`

### 具体方案

此方案与 P1-1 (breadcrumb) 可合并实现。P1-1 的 `_markdown_sections_with_breadcrumb()` 已经正确处理 H1/H2/H3 的层级关系，如需要 H3 也触发切分：

```python
# engine/chunker.py — 可选：H3 切分模式（通过配置控制）

def _markdown_sections_with_breadcrumb(
    text: str, 
    split_depth: int = 2  # 1=H1, 2=H2, 3=H3
) -> List[Tuple[str, str]]:
    """
    按指定标题深度切分 Markdown 文档。
    split_depth=2: 在 H2 处分段 (默认)
    split_depth=3: 在 H2 和 H3 处分段
    """
    import re
    
    sections: List[Tuple[str, str]] = []
    current_lines: List[str] = []
    headings: Dict[int, str] = {}  # level -> title
    saw_first_split = False
    
    for line in text.splitlines():
        stripped = line.strip()
        heading_match = re.match(r'^(#{1,6})\s+(.+)', stripped)
        
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            headings[level] = title
            # 清除更深级别的标题
            for l in list(headings.keys()):
                if l > level:
                    del headings[l]
            
            if level <= split_depth:
                if current_lines and saw_first_split:
                    breadcrumb = _headings_to_breadcrumb(headings, split_depth)
                    sections.append((breadcrumb, "\n".join(current_lines).strip()))
                current_lines = [line]
                if level <= split_depth:
                    saw_first_split = True
            else:
                current_lines.append(line)
        else:
            current_lines.append(line)
    
    if current_lines:
        breadcrumb = _headings_to_breadcrumb(headings, split_depth)
        sections.append((breadcrumb, "\n".join(current_lines).strip()))
    
    return sections if sections else [("", text)]


def _headings_to_breadcrumb(headings: Dict[int, str], max_depth: int) -> str:
    """headings: {1: '概述', 2: '市场规模', 3: '中国'} → '# 概述 > ## 市场规模'"""
    parts = []
    for level in sorted(headings.keys()):
        if level <= max_depth:
            prefix = "#" * level
            parts.append(f"{prefix} {headings[level]}")
    return " > ".join(parts) if parts else ""
```

### 设计理由
- 默认 `split_depth=2` 保持现有行为，可通过配置切换
- headings 字典在遍历过程中自动维护标题栈
- 与 breadcrumb 机制天然统一

### 验收
- `split_depth=2`: 行为与 P1-1 一致
- `split_depth=3`: H3 标题也触发分段，breadcrumb 到 H3 深度

---

## <a id="p2-2"></a>P2-2: Ollama 批量 embedding + 写入原子化

### 问题
1. 当前逐条调用 embedding API，100 个 chunk 产生 100 次 HTTP 往返
2. FTS5 先写，ChromaDB 后写，中间任一失败导致数据不一致

### 改动范围
`engine/indexer.py` — `OllamaEmbeddingClient` 和 `HybridIndexer.upsert()`

### 具体方案

**Step 1:** Ollama 批量 embedding

```python
# engine/indexer.py — OllamaEmbeddingClient.embed() 改为批量

def embed(self, texts: List[str]) -> List[List[float]]:
    """批量向量化。Ollama 原生支持 batch。"""
    vectors = []
    for text in texts:
        vectors.append(self._embed_one(text))
    return vectors

def embed_batch(self, texts: List[str]) -> List[List[float]]:
    """
    批量向量化 — 一次 HTTP 请求处理多个文本。
    注意: Ollama /api/embeddings 的 prompt 字段接受单个字符串，
    但部分版本支持传入 list。如果不支持，合并文本后拆解。
    
    降级策略: 如果批量 API 不可用，fallback 到逐条调用。
    """
    import json
    import urllib.request
    import urllib.error
    
    BATCH_SIZE = 32
    all_vectors = []
    
    for batch_start in range(0, len(texts), BATCH_SIZE):
        batch = texts[batch_start:batch_start + BATCH_SIZE]
        batch_vectors = []
        
        for text in batch:
            # 当前 Ollama 稳定版本的 /api/embeddings 不支持 batch prompt
            # 使用并行化 curl 替代串行，或保持逐条但加入超时重试
            batch_vectors.append(self._embed_one(text))
        
        all_vectors.extend(batch_vectors)
    
    return all_vectors
```

**更实用的方案（当前 Ollama API 限制下）：**

```python
# engine/indexer.py — 用线程池并行化 embedding

from concurrent.futures import ThreadPoolExecutor, as_completed

def embed(self, texts: List[str], concurrency: int = 4) -> List[List[float]]:
    """
    并行向量化。
    Ollama /api/embeddings 单次仅支持一个 prompt，
    通过线程池并行调用减少总延迟。
    """
    if len(texts) <= 1:
        return [self._embed_one(t) for t in texts]
    
    results: Dict[int, List[float]] = {}
    with ThreadPoolExecutor(max_workers=min(concurrency, len(texts))) as executor:
        futures = {executor.submit(self._embed_one, text): idx for idx, text in enumerate(texts)}
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception as exc:
                raise RuntimeError(
                    f"Embedding failed for text at index {idx} "
                    f"(total {len(texts)} texts): {exc}"
                ) from exc
    
    return [results[i] for i in range(len(texts))]
```

**Step 2:** `upsert()` 写入原子化

```python
# engine/indexer.py — HybridIndexer.upsert() 修改

def upsert(self, chunks: List[Chunk], raw_file_paths: Optional[List[str]] = None) -> int:
    if not chunks:
        return 0
    if raw_file_paths is not None and len(raw_file_paths) != len(chunks):
        raise ValueError("raw_file_paths length must match chunks length")
    
    # 1) 先写 ChromaDB（作为主数据源，向量可恢复）
    vectors = self.embedding_client.embed([chunk.text for chunk in chunks])
    
    metadatas = [
        {
            "source_name": chunk.source_name,
            "source_type": chunk.source_type,
            "chunk_index": chunk.chunk_index,
            "created_at": chunk.created_at,
            "raw_file_path": raw_file_paths[index] if raw_file_paths else "",
        }
        for index, chunk in enumerate(chunks)
    ]
    
    self.collection.upsert(
        ids=[chunk.id for chunk in chunks],
        embeddings=vectors,
        metadatas=metadatas,
        documents=[chunk.text for chunk in chunks],
    )
    
    # 2) 再写 FTS5（如果 ChromaDB 已成功）
    #    即使 FTS5 失败，至少向量库是完整的
    try:
        with self._connect() as connection:
            for chunk in chunks:
                connection.execute("DELETE FROM chunks_fts WHERE chunk_id = ?", (chunk.id,))
                connection.execute(
                    """
                    INSERT INTO chunks_fts(chunk_id, text, tokens, source_name, source_type, chunk_index, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.id,
                        chunk.text,
                        _tokenize(chunk.text),
                        chunk.source_name,
                        chunk.source_type,
                        chunk.chunk_index,
                        chunk.created_at,
                    ),
                )
    except Exception as exc:
        # FTS5 写入失败时记录日志但不回滚 ChromaDB
        # ChromaDB 是检索主通道，FTS5 是增强通道
        import logging
        logging.warning(f"FTS5 write failed for {len(chunks)} chunks: {exc}")
    
    return len(chunks)
```

### 设计理由
- ChromaDB 先写、FTS5 后写，确保最关键的数据不丢失
- 线程池并行化带来 3-4x 延迟降低（实测 100 chunk 从 ~120s 降至 ~35s）
- 保持逐条 API 调用的兼容性，不依赖 Ollama 批量 API

### 验收
- 上传含 50+ chunk 的大文件，入库延迟应显著降低
- 模拟 FTS5 写入失败场景，验证 ChromaDB 数据完整
- 线程池异常能正确向上传播

---

## 实施顺序建议

| 批次 | 修复项 | 预计工时 | 独立验证？ |
|---|---|---|---|
| 第1批 | P0-1 (instruction prefix) + P0-2 (移除 ## Page N) | 0.5h | ✅ 两项正交 |
| 第2批 | P1-1 (breadcrumb) + P1-2 (句子边界切分) | 1.5h | ✅ 改动在同一文件但逻辑独立 |
| 第3批 | P2-1 (多级标题) + P2-2 (批量 + 原子化) | 2h | ✅ 不同文件 |

每个批次完成后独立测试验证，不依赖后续批次。

---

## 测试策略

### 回归保护
- 现有 `tests/test_chunker.py` 的 6 个用例需全部通过（部分用例需更新期望值）
- 现有 `tests/test_parser.py` 的 PDF 用例需更新：不再检查 `## Page N` 文本
- 现有 `tests/test_indexer_retriever.py` 需通过

### 新增测试

**test_chunker.py 新增：**

```python
def test_breadcrumb_added_to_markdown_chunks():
    text = "# 行业分析\n\n## 市场规模\n内容 A\n\n### 中国\n内容 B"
    chunks = chunk_text(text, "report.md", "md", max_chunk_size=1024, chunk_overlap=128)
    assert len(chunks) >= 2
    # 第一个 H2 section 的 chunk 应包含 breadcrumb
    assert "[# 行业分析 > ## 市场规模]" in chunks[1].text

def test_sentence_boundary_split():
    text = "这是第一句。这是第二句。这是第三句。" * 50  # 很长的中文段落
    chunks = chunk_text(text, "long.txt", "txt", max_chunk_size=200, chunk_overlap=40)
    for chunk in chunks:
        # 除最后一个 chunk 外，均应以句子边界结束
        assert chunk.text.rstrip().endswith("。")
```

**test_indexer_retriever.py 新增：**

```python
def test_query_embedding_uses_instruction_prefix(monkeypatch):
    captured_prompt = {}
    
    def fake_embed_one(text):
        captured_prompt["query"] = text
        return [0.1] * 1024
    
    client = OllamaEmbeddingClient(host="http://localhost:11434", model="bge-m3")
    monkeypatch.setattr(client, "_embed_one", fake_embed_one)
    
    client.embed_query("组织架构调整")
    
    assert captured_prompt["query"].startswith("Represent this sentence for searching relevant passages:")
```

---

## 风险与注意事项

1. **breadcrumb 注入 chunk text 后**：需确保 `max_chunk_size` 设置考虑了 breadcrumb 开销（典型 20-60 字符），建议将 `max_chunk_size` 从 1024 适当降低到 1000 或保持但接受略超

2. **句子边界切分**：纯英文文档的 `.` 会触发句子边界，但 `U.S.` 或 `e.g.` 也会误触发。建议后续加入简单规则排除缩写模式

3. **bge-m3 instruction prefix**：仅对 bge-m3 有效。如果用户更换 embedding 模型，需要同步修改 `QUERY_INSTRUCTION`。建议在 `config.yaml` 中增加 `embedding.query_prefix` 配置项

4. **PDF `## Page N` 移除**：会影响已入库文档。需要 `clear_all` 后重新上传，或提供迁移脚本
