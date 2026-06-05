# PKA 测试工具改动规格

## 功能概述

| # | 功能 | 用途 |
|---|------|------|
| 1 | 知识库清空 | 测试时一键重置 FTS5 + ChromaDB，不污染生产数据 |
| 2 | 附件溯源链接 | 回答中引用的原始文件（PDF/PPT/DOCX 等）可点击下载 |

---

## Feature 1：知识库清空

### API 路由

**`POST /api/ingest/clear`**

```python
@app.post("/api/ingest/clear")
async def clear_knowledge():
    runtime.indexer.clear_all()
    runtime.last_updated = datetime.now().isoformat()
    return {"status": "ok", "message": "知识库已清空"}
```

### `engine/indexer.py` — `HybridIndexer.clear_all()`

```python
def clear_all(self) -> None:
    # ChromaDB: 删除 collection 内所有数据
    all_ids = self.collection.get()["ids"]
    if all_ids:
        self.collection.delete(ids=all_ids)

    # FTS5: 清空虚拟表
    with self._connect() as connection:
        connection.execute("DELETE FROM chunks_fts")
```

### CLI

**`obs-asset clear`**

```python
# cli.py 新增子命令
clear_parser = subparsers.add_parser("clear")

# main() 路由:
if args.command == "clear":
    return _print_result(_post_json(args.base_url, "/api/ingest/clear", {}))
```

### 前端

配置页 (`settings.html`) 底部新增区域：

```html
<section class="panel danger-zone">
  <h2>⚠️ 危险操作</h2>
  <p>清空知识库中所有已索引的内容。此操作不可撤销。</p>
  <button type="button" id="clear-knowledge">清空知识库</button>
  <pre id="clear-feedback" class="feedback"></pre>
</section>
```

`app.js` — `setupSettings()` 中追加：

```javascript
document.getElementById("clear-knowledge")?.addEventListener("click", async () => {
  if (!confirm("确定清空全部知识库？此操作不可撤销。")) return;
  setFeedback("clear-feedback", await postJSON("api/ingest/clear", {}));
});
```

`style.css` 追加：

```css
.danger-zone {
  border-color: var(--accent-2);
}
.danger-zone h2 {
  color: var(--accent-2);
}
#clear-knowledge {
  background: var(--accent-2);
}
```

### 测试

`tests/test_generator_api.py` 新增：

```python
def test_clear_knowledge_resets_index():
    client = TestClient(app)
    # 先录入一条
    client.post("/api/ingest/text", json={"text": "测试数据"})
    before = client.get("/api/stats").json()
    assert before["total_chunks"] >= 1

    # 清空
    response = client.post("/api/ingest/clear")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    # 验证
    after = client.get("/api/stats").json()
    assert after["total_chunks"] == 0
    assert after["indexed_files"] == 0
```

---

## Feature 2：附件溯源链接

### 索引层

**`engine/models.py`** — `Chunk` 不变（frozen）。

**`engine/indexer.py`** — `upsert()` 中 ChromaDB metadata 增加字段：

```python
metadatas=[
    {
        "source_name": chunk.source_name,      # 文件名
        "source_type": chunk.source_type,       # docx/pptx/pdf/xlsx/image
        "chunk_index": chunk.chunk_index,
        "created_at": chunk.created_at,
        "raw_file_path": chunk.metadata.get("raw_file_path", ""),  # 新增
    }
    for chunk in chunks
],
```

Wait — Chunk 是 frozen dataclass，没有 `metadata` 字段。需要在 `ParseResult` → `Chunk` 的转换中传递。

**方案**：不改 `Chunk` 模型，而是在 `server.py` 的 `ingest_file` 中，构造完 chunks 后，将 `raw_file_path` 传入 `HybridIndexer.upsert` 的额外参数。

**实际改动** — `engine/indexer.py` `upsert()` 签名：

```python
def upsert(self, chunks: List[Chunk], raw_file_paths: List[str] | None = None) -> int:
```

ChromaDB metadata 中根据 raw_file_paths 列表填充 `raw_file_path`。手动文本（raw_file_paths=None）时不填。`search_fts` 和 `search_vector` 返回结果中自动带出 `raw_file_path`。

**`server.py`** — `ingest_file` 路由：

```python
raw_file_path = str(output_path.relative_to(runtime.config["data_dir"]))
chunks = _chunk(parsed.text, parsed.source_name, parsed.source_type)
count = runtime.indexer.upsert(chunks, raw_file_paths=[raw_file_path] * len(chunks))
```

退回 root 的路径是 `data_dir`（如 `~/Documents/PKA_Data`），所以 `relative_to` 后的 `raw_file_path` 是 `raw/2026-06-04/report.docx`。

### API 路由

**`GET /api/files/{raw_path:path}`**

```python
@app.get("/api/files/{raw_path:path}")
async def serve_raw_file(raw_path: str):
    full_path = Path(runtime.config["data_dir"]) / raw_path
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="file not found")
    if not str(full_path.resolve()).startswith(str(Path(runtime.config["data_dir"]).resolve())):
        raise HTTPException(status_code=403, detail="access denied")  # 路径穿越防护
    return FileResponse(full_path, filename=full_path.name)
```

### `engine/generator.py` — `generate_answer()` 来源信息扩展

`sources` 事件中的每个 source 增加 `raw_file_path` 字段（检索结果中已有则带上）：

```python
def _sources(chunks: Iterable[RetrievedChunk]) -> List[dict]:
    return [
        {
            "source_name": chunk.source_name,
            "chunk_index": chunk.chunk_index,
            "relevance": chunk.score,
            "chunk_id": chunk.chunk_id,
            "raw_file_path": chunk.metadata.get("raw_file_path", ""),  # 新增
        }
        for chunk in chunks
    ]
```

需要 `RetrievedChunk` 携带 metadata — 在 `engine/retriever.py` 的 `hybrid_search()` 中，从检索结果将 `raw_file_path` 传给 `RetrievedChunk`。

**方案**：`RetrievedChunk` 是 frozen，不能新增字段。最简单：在 `generator.py` 的 `_sources` 中不依赖 `RetrievedChunk` 新增字段，而是在 `generate_answer` 中单独传递一个 `{chunk_id → raw_file_path}` 映射表。但这样耦合太重。

**最优方案**：不改 `RetrievedChunk`。在 `HybridRetriever.hybrid_search()` 中，融合结果字典自带 `raw_file_path`。`_sources()` 函数直接从 chunk dict 中读取。

实际上检索结果的 dict 是从 `indexer.search_fts()` 和 `indexer.search_vector()` 返回的，这两个方法已经返回 dict。只需要在返回的 dict 中加上 `raw_file_path`。RRF 融合时会保留。

### 前端

`app.js` — `setupAsk()` 的来源渲染：

```javascript
// 修改 sources 渲染部分
if (payload.type === "sources") {
    askState.sources = payload.sources;
    const sources = document.createElement("details");
    sources.className = "sources";
    const items = payload.sources.map(source => {
        if (source.raw_file_path) {
            return `<div>
                <a href="api/files/${encodeURIComponent(source.raw_file_path)}" target="_blank">
                    📎 ${source.source_name}
                </a> #${source.chunk_index}
            </div>`;
        }
        return `<div>${source.source_name} #${source.chunk_index}</div>`;
    }).join("");
    sources.innerHTML = `<summary>参考来源</summary>${items}`;
    answer.appendChild(sources);
}
```

有 `raw_file_path` → 渲染为可点击链接；没有（手动文本）→ 纯文本。

### `engine/retriever.py` — `RetrievedChunk` 扩展

`RetrievedChunk` 需要 `raw_file_path` 字段。改为非 frozen（移除 `frozen=True`），增加可选字段：

```python
@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    source_name: str
    source_type: str
    chunk_index: int
    score: float
    rank_fts5: Optional[int]
    rank_vector: Optional[int]
    raw_file_path: str = ""  # 新增
```

`hybrid_search()` 中从融合结果赋值 `raw_file_path`。

### `engine/indexer.py` — 检索结果增加 `raw_file_path`

`search_fts()` 从 FTS5 无法读出 `raw_file_path`（FTS5 表没有这个列）。需要额外查 ChromaDB。

**更简洁的方案**：`raw_file_path` 只通过 ChromaDB 的 `get_chunk` 补充，不在 FTS5 返回。前端请求 `/api/sources/{chunk_id}` 时自然返回 `raw_file_path`。但这让 sources 事件中无法区分是否有源文件。

**最终方案**：FTS5 检索结果先获取 `chunk_id` 列表，然后批量查 ChromaDB 的 `get` 补充 `raw_file_path`。由于 FTS5 结果只有 top-10，这个二次查询成本极低。

```python
def search_fts(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
    # ... 已有查询逻辑 ...
    # 补充 raw_file_path
    chunk_ids = [row[0] for row in rows]
    chroma_metas = self.collection.get(ids=chunk_ids, include=["metadatas"])
    path_map = {}
    for cid, meta in zip(chroma_metas["ids"], chroma_metas["metadatas"]):
        path_map[cid] = meta.get("raw_file_path", "")
    # 在结果 dict 中加上 raw_file_path
```

### 测试

`tests/test_export_api.py` 或新建测试：

```python
def test_file_ingest_preserves_raw_file_path_in_chunks():
    client = TestClient(app)
    # 上传一个文件
    content = b"test pdf content"
    response = client.post(
        "/api/ingest/file",
        files={"file": ("report.pdf", content, "application/pdf")},
    )
    assert response.status_code == 200
    chunk_id = response.json()["chunk_ids"][0]

    # 查来源
    source = client.get(f"/api/sources/{chunk_id}").json()
    assert "raw" in source.get("raw_file_path", "")
    assert source["raw_file_path"].endswith("report.pdf")

def test_manual_text_has_no_raw_file_path():
    client = TestClient(app)
    response = client.post("/api/ingest/text", json={"text": "纯文本"})
    chunk_id = response.json()["chunk_ids"][0]
    source = client.get(f"/api/sources/{chunk_id}").json()
    assert source.get("raw_file_path", "") == ""

def test_raw_file_download_returns_original_file():
    # 上传一个 PDF，获取 raw_file_path，然后 GET /api/files/{path}
    # 验证文件内容和 MIME type

def test_raw_file_path_traversal_blocked():
    client = TestClient(app)
    response = client.get("/api/files/../../../etc/passwd")
    assert response.status_code == 403
```

---

## 执行顺序

```
1. indexer.py: upsert 增加 raw_file_paths 参数 → search_fts/search_vector 返回 raw_file_path
2. retriever.py: RetrievedChunk 加 raw_file_path 字段 → hybrid_search 透传
3. generator.py: _sources 输出 raw_file_path
4. server.py: ingest_file 传入 raw_file_path → GET /api/files/{path}
5. frontend: 问答页来源链接 + 配置页清空按钮
6. cli.py: obs-asset clear 命令
7. 测试: 覆盖清空 + 附件溯源 + 路径穿越防护
```
