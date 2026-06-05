# PKA 第一批修复任务书

## 优先级

P0 必须先修，P1 建议修，P2 可选修。

---

## P0-1: 修复 `asyncio.run()` 崩溃

**文件**：`engine/parser.py`, `server.py`

**问题**：`ingest_file`（async）→ `parse_file`（sync）→ `asyncio.run(ocr.extract(...))` 在事件循环内二次调用 `asyncio.run()` 崩溃。

**修复方案**：

1. 将 `parse_file` 改为 `async def parse_file(...)`，OCR 调用改为 `await ocr_client.extract([str(path)])`
2. `server.py:96` 调用改为 `parsed = await parse_file(str(output_path), ...)`
3. 不需要改 `parse_text`（它是纯文本，不涉及异步）
4. 测试文件 `tests/test_parser.py` 中直接调 `parse_file` 的地方，改为 `await parse_file(...)` 或保持用 `asyncio.run(parse_file(...))` 包装

**验收**：上传 PNG 图片到 Web UI，不再报 500，OCR 结果正常入库。`python3 -m pytest tests/test_parser.py -q` 全绿。

---

## P0-2: 修复 Markdown H1 段落丢失

**文件**：`engine/chunker.py`

**问题**：`# 总览\n\n内容\n\n## 第一节\n...` 这种结构中，H1 及其附属段落被静默丢弃。

**修复方案**：

```python
def _looks_like_markdown(text: str) -> bool:
    return any(line.startswith("##") for line in text.splitlines())
    # 改为检查 ## 而非 #，避免把单行 # 注释/标签当做 Markdown

def _markdown_h2_sections(text: str) -> List[str]:
    sections: List[List[str]] = []
    current: List[str] = []
    saw_first_h2 = False
    for line in text.splitlines():
        if line.startswith("## "):
            if current:
                sections.append(current)
            current = [line]
            saw_first_h2 = True
        elif not saw_first_h2:
            current.append(line)  # H1 及其附属内容作为前置段落
        else:
            current.append(line)
    if current:
        sections.append(current)
    return ["\n".join(section).strip() for section in sections] if sections else _paragraphs(text)
```

**验收**：`tests/test_chunker.py` 中第一个用例 `test_markdown_with_h2_splits_into_sections_including_heading` 扩展验证 H1 内容不被丢弃。新增 H1+正文+多个H2 的混合文本用例。

---

## P1: 集成 ChromaDB 替换 JSON 向量存储

**文件**：`engine/indexer.py`

**问题**：当前用 JSON 文件存向量，O(n) 全量遍历检索。任务书要求 ChromaDB。

**要求**：

1. 保持 `HybridIndexer` 对外接口不变：
   - `upsert(chunks)` → 同时写入 FTS5 和 ChromaDB
   - `search_vector(query, top_k)` → 调用 ChromaDB collection.query
   - `search_fts(query, top_k)` → 不变
   - `get_chunk(chunk_id)` → 从 ChromaDB collection.get 获取
   - `count_chunks()` → `collection.count()`
   - `count_sources()` → 从 metadata 中去重统计，或维持 FTS5 查询

2. ChromaDB collection 设计：

```python
import chromadb

self.client = chromadb.PersistentClient(path=persist_dir)
self.collection = self.client.get_or_create_collection(name=collection_name)

# upsert:
self.collection.upsert(
    ids=[chunk.id for chunk in chunks],
    embeddings=vectors,
    metadatas=[{"source_name": c.source_name, "source_type": c.source_type, "chunk_index": c.chunk_index, "created_at": c.created_at} for c in chunks],
    documents=[chunk.text for chunk in chunks],
)

# search_vector:
results = self.collection.query(query_embeddings=[query_vector], n_results=top_k)
# 将 ChromaDB 返回格式转为现有 search_vector 返回的 dict 格式
```

3. `OllamaEmbeddingClient` 保持不变，注入给 `HybridIndexer`
4. 移除 `_vectors.json` 读写逻辑、`_cosine_similarity`、`_load_vectors`、`_save_vectors`（`_cosine_similarity` 仅保留给测试用 fake client）
5. `requirements.txt` 已有 `chromadb>=0.4.22,<0.5.0`，无需修改

**验收**：`python3 -m pytest tests/test_indexer_retriever.py -q` 全绿。FakeEmbeddingClient 返回的 1024 维向量能被 ChromaDB 正常 upsert 和 query。

---

## P2-1: OCR 失败时抛出异常

**文件**：`engine/ocr.py`

**问题**：三次重试全失败后返回空字符串 `""`，静默吞错。

**修复**：

```python
# engine/ocr.py:48
return ""  # 改为 raise
raise RuntimeError(f"OCR failed after 3 retries: {last_error}")
```

**验收**：上传损坏图片时 Web UI 返回明确错误，不产生空 chunk。

---

## P2-2: FTS5 `text` 列标记 `UNINDEXED`

**文件**：`engine/indexer.py:50-63`

```sql
-- 将 text 改为 UNINDEXED
text UNINDEXED,
```

**原因**：检索只走 `tokens` 列，`text` 列被索引浪费空间。

**验收**：FTS5 检索行为不变，`python3 -m pytest tests/test_indexer_retriever.py -q` 全绿。

---

## P2-3: 大文件流式写入

**文件**：`server.py:90`

```python
# 当前
output_path.write_bytes(await file.read())

# 改为
with output_path.open("wb") as f:
    while chunk := await file.read(1024 * 1024):  # 1MB chunks
        f.write(chunk)
```

**验收**：上传大文件不 OOM。

---

## 执行顺序

```
P0-1 (asyncio)  →  P0-2 (H1 loss)  →  全部测试回归
    ↓
P1 (ChromaDB)
    ↓
P2-1 (OCR 异常) → P2-2 (FTS5 UNINDEXED) → P2-3 (流式写入)
    ↓
全部测试 → 提交
```
