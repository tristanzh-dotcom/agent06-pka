# PKA（Personal Knowledge Archive）项目任务书

## 元信息

| 字段 | 内容 |
|------|------|
| 项目代号 | PKA |
| 版本 | v1.0.0-MVP |
| 角色 | Agent06 - 个人知识资产管理 |
| 创建日期 | 2026-06-04 |
| 前端框架 | 简单 HTML/JS（内嵌于 FastAPI） |
| 后端框架 | Python 3.11+ / FastAPI |
| 部署环境 | macOS 本地，内网访问 |

---

## 一、项目定义

### 1.1 一句话描述

本地 Web 应用：上传/粘贴任意内容（文本、Word、PPT、PDF、Excel、图片），自动解析入库；用自然语言提问，基于全部历史内容给出综合建议，并支持格式化文档输出。

### 1.2 核心链路

```
Web UI 输入（文本/文件）
  → 文档解析（docx/pptx/pdf/xlsx/md/txt + OCR via 火山方舟）
    → 智能分块（Markdown 按标题切，纯文本按段落切）
      → 双检索引擎索引
        ├─ SQLite FTS5 + Jieba（关键词倒排）
        └─ ChromaDB + Ollama bge-m3（语义向量）
          → Web UI 提问
            → 混合检索（RRF 融合 FTS5 结果 + 向量结果）
              → 远程 LLM 生成（codex 基座，模型通过 Web 配置页可切换）
                → Web UI 流式展示答案 + 来源引用
                  → 可选：输出 Word/PPT 格式化文档
```

### 1.3 不做什么（Out of Scope）

- 不做 Obsidian 插件或依赖 Obsidian 运行时
- 不做多用户/权限系统（单用户本地）
- 不做对话历史持久化（MVP 仅当前会话有效）
- 不做移动端适配

---

## 二、项目目录结构

```
pka/
├── server.py                 # FastAPI 主入口，路由注册
├── config.yaml               # 系统配置（模型名、路径、chunk 参数）
├── requirements.txt          # Python 依赖
├── static/                   # 前端静态资源
│   ├── index.html            # 录入页
│   ├── ask.html              # 问答页
│   ├── settings.html         # 配置页
│   ├── style.css             # 全局样式（简洁、内网工具风格）
│   └── app.js                # 前端交互逻辑（三页面共享）
├── engine/
│   ├── __init__.py
│   ├── parser.py             # 文档解析引擎（F1）
│   ├── chunker.py            # 智能分块引擎（F2）
│   ├── indexer.py            # 双检索引擎索引层（F3）
│   ├── retriever.py          # 混合检索 + RRF 融合（F3）
│   ├── generator.py          # RAG 问答生成 + 来源引用（F4）
│   ├── exporter.py           # 输出文档生成（F6）
│   └── ocr.py               # OCR 客户端（火山方舟）
├── cli.py                    # CLI 入口（F7）
└── tests/
    ├── test_parser.py
    ├── test_chunker.py
    ├── test_indexer.py
    ├── test_retriever.py
    └── test_e2e.py
```

持久化数据目录（与项目代码分离，可配置路径）：

```
~/Documents/PKA_Data/         # 默认数据目录（config.yaml 可改）
├── .vector/                  # ChromaDB 持久化
├── .fts5/                    # SQLite FTS5 数据库文件
├── raw/                      # 原始上传文件按日期归档
│   ├── 2026-06-01/
│   └── 2026-06-04/
└── chunks/                   # 分块缓存文件（用于来源追溯）
```

---

## 三、环境与依赖

### 3.1 外部服务

| 服务 | 用途 | 获取方式 |
|------|------|---------|
| Ollama | 本地 Embedding (bge-m3) | `brew install ollama && ollama pull bge-m3` |
| 火山方舟 | OCR (doubao-1-5-vision-pro-32k) | API Key + Endpoint，Web 配置页填写 |
| 远程 LLM | 生成回答 | codex 基座，Web 配置页可切换 endpoint/model |

### 3.2 Python 依赖 (requirements.txt)

```
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
python-multipart>=0.0.9
python-docx>=1.1.0
python-pptx>=0.6.23
PyMuPDF>=1.23.0
openpyxl>=3.1.0
pyyaml>=6.0
jieba>=0.42.1
chromadb>=0.4.22
ollama>=0.1.6
httpx>=0.27.0
aiofiles>=23.2.0
markdown-it-py>=3.0.0
```

全部通过 pip 安装，无系统级依赖。

---

## 四、配置文件规范

### config.yaml

```yaml
# 数据存储路径
data_dir: "~/Documents/PKA_Data"

# ChromaDB
chroma:
  collection_name: "pka_knowledge"
  persist_dir: "{data_dir}/.vector"

# SQLite FTS5
fts5:
  db_path: "{data_dir}/.fts5/pka.db"

# Ollama Embedding
embedding:
  host: "http://localhost:11434"
  model: "bge-m3"

# 火山方舟 OCR
ocr:
  endpoint: ""           # Web 配置页填写
  api_key: ""            # Web 配置页填写
  model: "doubao-1-5-vision-pro-32k"
  max_images_per_request: 10

# 生成模型
generation:
  endpoint: ""           # Web 配置页填写
  api_key: ""            # Web 配置页填写
  model: ""              # Web 配置页填写
  max_context_chunks: 10

# 分块参数
chunking:
  max_chunk_size: 1024   # tokens
  chunk_overlap: 128     # tokens
  md_split_by: "##"      # Markdown 按 H2 切分

# 检索参数
retrieval:
  fts5_top_k: 10
  vector_top_k: 10
  rrf_k: 60              # RRF 融合参数
  final_top_k: 10        # 最终返回给 LLM 的 chunk 数

# 服务
server:
  host: "0.0.0.0"
  port: 8080
```

---

## 五、MVP 功能详细规格

---

### F0：Web 应用框架

**优先级**：P0  
**文件**：`server.py`, `static/index.html`, `static/ask.html`, `static/settings.html`, `static/style.css`, `static/app.js`

#### 页面路由

| 路由 | 页面 | 功能 |
|------|------|------|
| `GET /` | 录入页 | 文本粘贴 + 文件上传 |
| `GET /ask` | 问答页 | 对话式提问 + 流式回答 |
| `GET /settings` | 配置页 | 模型 endpoint/key 配置 |

#### API 路由

| 方法 | 路径 | 功能 |
|------|------|------|
| `POST /api/ingest/text` | 文本录入 | 接收 `{"text": "..."}` → 分块 → 入库 → 返回片段数 |
| `POST /api/ingest/file` | 文件录入 | multipart 上传 → 解析 → 分块 → 入库 → 返回片段数 |
| `POST /api/query` | 问答 | 接收 `{"question": "..."}` → SSE 流式返回答案 + 来源 |
| `GET /api/stats` | 统计 | 返回已索引文件数、总 chunk 数、最后更新时间 |
| `GET /api/config` | 读配置 | 返回当前配置（脱敏 api_key） |
| `POST /api/config` | 写配置 | 更新 config.yaml 并热加载 |
| `GET /api/sources/{chunk_id}` | 来源内容 | 返回 chunk 对应的原始文本片段 |

#### 前端要求

- 单页风格，三页面共用 `app.js` 和 `style.css`
- 录入页：拖拽上传区域 + 文本框，上传后即时反馈
- 问答页：对话气泡样式，打字机流式输出，答案下方可折叠"参考来源"
- 配置页：表单填写 API 地址/Key/模型名，保存后即时生效
- 无外部 CDN 依赖，CSS/JS 全本地

#### 验收标准

- [ ] 三个页面可正常访问
- [ ] 文件上传 -> 解析 -> 入库 端到端链路通畅
- [ ] 文本粘贴 -> 分块 -> 入库 端到端链路通畅
- [ ] 问答流式输出正常，无超时断开
- [ ] 配置页保存后查询功能即时使用新模型

---

### F1：文档解析引擎

**优先级**：P0  
**文件**：`engine/parser.py`, `engine/ocr.py`

#### 输入

| 格式 | MIME Type | 解析方法 |
|------|-----------|---------|
| `.txt` | text/plain | `open().read()` |
| `.md` | text/markdown | `open().read()` |
| `.docx` | application/vnd.openxmlformats-officedocument.wordprocessingml.document | `python-docx` 提取段落文本 |
| `.pptx` | application/vnd.openxmlformats-officedocument.presentationml.presentation | `python-pptx` 提取所有 slide 文本 |
| `.pdf` | application/pdf | `PyMuPDF (fitz)` 提取页面文本 |
| `.xlsx` | application/vnd.openxmlformats-officedocument.spreadsheetml.sheet | `openpyxl` 提取 sheet → 转 Markdown 表格文本 |
| `.png/.jpg/.jpeg/.webp` | image/* | 火山方舟 OCR（`engine/ocr.py`） |

#### 接口签名

```python
def parse_file(file_path: str, mime_type: str | None = None) -> ParseResult:
    """
    返回:
        ParseResult(
            text: str,           # 提取的纯文本
            source_name: str,    # 原始文件名
            source_type: str,    # "docx" | "pptx" | "pdf" | "xlsx" | "txt" | "md" | "image"
            metadata: dict,      # 额外元信息（页数、sheet 数等）
        )
    """

def parse_text(text: str, source_name: str = "manual_input") -> ParseResult:
    """
    直接文本录入
    """

def ocr_image(image_path: str) -> str:
    """
    调用火山方舟 doubao-1-5-vision-pro-32k
    发送图片 → 返回提取的文本
    批量上传（一次最多 10 张）→ 减少 API 调用次数
    """
```

#### OCR 实现要点 (`engine/ocr.py`)

```python
# 使用 httpx 异步调用火山方舟 API
# 将图片转为 base64，构造 multipart 请求
# 多图时在一个请求中发送，prompt 要求返回每张图的文本
# 错误处理：网络超时重试 2 次，API 错误记录日志并返回空字符串

import httpx
import base64
from pathlib import Path

class VolcengineOCR:
    def __init__(self, endpoint: str, api_key: str, model: str):
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
    
    async def extract(self, image_paths: list[str]) -> str:
        """批量 OCR，最多 10 张"""
        ...
```

#### 验收标准

- [ ] 六种文件格式各上传一个测试样本，文本提取完整
- [ ] PDF 多页文档全部提取
- [ ] XLSX 多 sheet 表格转为可读文本
- [ ] PNG/JPG 图片 OCR 返回可读中文文本
- [ ] 解析失败时返回明确错误信息，不崩溃

---

### F2：智能分块引擎

**优先级**：P0  
**文件**：`engine/chunker.py`

#### 分块策略

```
输入文本
  │
  ├─ 如果是 Markdown（含 ## 或 # 标题）
  │    └─ 按 H2 (##) 切分，每个 section 为一个 chunk
  │       超长 section（> max_chunk_size）→ 滑动窗口二次切分
  │
  └─ 如果是纯文本（无 Markdown 标题）
       └─ 按 \n\n（段落）切分
          超长段落 → 滑动窗口切分（chunk_overlap 128 tokens）
```

#### 接口签名

```python
def chunk_text(text: str, source_name: str, source_type: str) -> list[Chunk]:
    """
    返回:
        list[Chunk(
            id: str,              # "{source_name}#{chunk_index}"
            text: str,            # chunk 文本内容
            source_name: str,     # 原始文件名
            source_type: str,     # 原始文件类型
            chunk_index: int,     # 在源文件中的序号
            created_at: str,      # ISO 8601 创建时间
        )]
    """
```

#### 实现要点

- 用 `markdown-it-py` 解析 Markdown AST，按 H2 切分
- 用 `tiktoken` 或近似方法（1 token ≈ 0.7 中文字符 ≈ 4 英文字符）估算长度
- 滑动窗口：`[0:max_chunk_size]`, `[max_chunk_size-overlap:2*max_chunk_size-overlap]`, ...
- 每个 chunk 保留所属源文件信息用于来源追溯

#### 验收标准

- [ ] Markdown 有标题时按 H2 正确切分（包含标题行）
- [ ] 纯文本按段落正确切分
- [ ] 超长段落正确滑动窗口切分，窗口间有重叠
- [ ] 单个 chunk 不超过 1500 字符

---

### F3：双检索引擎（索引 + 检索）

**优先级**：P0  
**文件**：`engine/indexer.py`, `engine/retriever.py`

#### 3a. 索引层 (`engine/indexer.py`)

**FTS5 索引**：

```python
# SQLite 表结构
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id,
    text,
    source_name,
    source_type,
    created_at,
    tokenize='jieba'  # 使用 Jieba 分词
);

# 或者通过注册自定义 tokenizer 实现 Jieba
# 如果 sqlite3 模块不支持自定义 tokenizer，
# 则在 Python 层用 Jieba 分词后写入 FTS5
```

**ChromaDB 索引**：

```python
import chromadb
from ollama import Client

class VectorIndexer:
    def __init__(self, persist_dir: str, collection_name: str, embedding_host: str, embedding_model: str):
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection(name=collection_name)
        self.ollama = Client(host=embedding_host)
        self.embedding_model = embedding_model
    
    def embed(self, texts: list[str]) -> list[list[float]]:
        """调用 Ollama bge-m3 批量向量化"""
        ...
    
    def upsert(self, chunks: list[Chunk]) -> int:
        """批量 embedding + upsert"""
        ...
```

**全量接口**：

```python
def index_chunks(chunks: list[Chunk]) -> int:
    """
    同时写入 FTS5 和 ChromaDB
    返回已索引 chunk 数
    """
```

#### 3b. 检索层 (`engine/retriever.py`)

**混合检索 + RRF 融合**：

```python
def hybrid_search(query: str, top_k: int = 10) -> list[RetrievedChunk]:
    """
    1. FTS5 关键词检索 → top-10
    2. ChromaDB 向量检索 → top-10
    3. RRF 融合：
       score(doc) = Σ (1 / (k + rank_i))
       其中 k=60, rank_i 是该 doc 在两个排序列表中的排位
    4. 去重（同一个 chunk_id 取最高分）
    5. 按融合分数降序排，取 top_k
    """

# 返回结构
RetrievedChunk = dict(
    chunk_id=str,
    text=str,
    source_name=str,
    source_type=str,
    score=float,
    rank_fts5=int | None,
    rank_vector=int | None,
)
```

**RRF 实现参考**：

```python
def reciprocal_rank_fusion(results_a: list[dict], results_b: list[dict], k: int = 60) -> list[dict]:
    scores = {}
    for rank, item in enumerate(results_a, start=1):
        chunk_id = item["chunk_id"]
        scores[chunk_id] = scores.get(chunk_id, 0) + 1.0 / (k + rank)
        # merge metadata
    for rank, item in enumerate(results_b, start=1):
        chunk_id = item["chunk_id"]
        scores[chunk_id] = scores.get(chunk_id, 0) + 1.0 / (k + rank)
    merged = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [{"chunk_id": cid, "score": s, ...} for cid, s in merged]
```

#### 验收标准

- [ ] FTS5 + Jieba 分词检索可正常返回中文关键词结果
- [ ] ChromaDB 向量检索可正常返回语义相似结果
- [ ] RRF 融合后结果在两个列表中均出现过的 chunk 排名更高
- [ ] 检索延迟 < 2 秒（1000 chunk 规模）
- [ ] 新增 chunk 后立即可检索到

---

### F4：RAG 问答引擎

**优先级**：P0  
**文件**：`engine/generator.py`

#### 处理流程

```
用户提问
  → retriever.hybrid_search(question)
    → 获得 top-K 相关 chunk（K = config.retrieval.final_top_k）
      → 构建 prompt
        → 调用远程 LLM（codex 基座 / 用户配置的模型）
          → SSE 流式返回
```

#### Prompt 模板

```
你是一个个人知识库助手。用户积累了大量个人文档、笔记、面试复盘、项目报告等内容。
现在用户基于这些内容向你提问。你需要：

1. 仔细阅读所有 [参考内容] 片段
2. 综合分析这些片段中的信息
3. 如果信息充分，给出专业、具体的建议和回答
4. 如果某些方面的信息不足，请明确指出"当前知识库中缺少关于 XX 的信息"
5. 在回答末尾列出本次引用的来源文件

[参考内容]
--- chunk_1 (来源: {source_name_1})
{chunk_text_1}
--- chunk_2 (来源: {source_name_2})
{chunk_text_2}
...

[用户问题]
{question}

请回答：
```

#### 接口签名

```python
async def generate_answer(
    question: str,
    chunks: list[RetrievedChunk],
    model_endpoint: str,
    model_api_key: str,
    model_name: str,
) -> AsyncGenerator[str, None]:
    """
    SSE 流式生成器
    yield 每个 token
    最后 yield "[SOURCES]..." 标记 + JSON 格式的来源列表
    """
```

#### SSE 输出协议

```
data: {"type": "token", "content": "根据"}

data: {"type": "token", "content": "你的"}

...

data: {"type": "sources", "sources": [{"source_name": "组织架构调整方案.pptx", "chunk_index": 2, "relevance": 0.89}, ...]}

data: {"type": "done"}
```

#### 验收标准

- [ ] 问答返回内容与参考 chunk 内容相关
- [ ] 流式输出 SSE 正常工作
- [ ] 来源引用精确到文件名 + chunk 序号
- [ ] 知识库为空时返回"暂无相关内容"而非幻觉
- [ ] LLM 调用失败时有明确错误提示

---

### F5：模型配置页

**优先级**：P0  
**文件**：`static/settings.html`（在 `app.js` 中实现配置读写逻辑）  
**API**：`GET /api/config`, `POST /api/config`

#### 配置页面元素

| 配置项 | 字段名 | 说明 |
|--------|--------|------|
| 生成模型 Endpoint | `generation.endpoint` | 如 `https://api.openai.com/v1/chat/completions` |
| 生成模型 API Key | `generation.api_key` | 密码框，保存后脱敏显示 `****xxxx` |
| 生成模型名称 | `generation.model` | 如 `gpt-4o`, `deepseek-v3` |
| OCR Endpoint | `ocr.endpoint` | 火山方舟 API 地址 |
| OCR API Key | `ocr.api_key` | 密码框，脱敏显示 |
| Embedding 模型 | `embedding.model` | 下拉选择 Ollama 已安装模型 |
| 检索结果数量 | `retrieval.final_top_k` | 数字输入 |

#### 行为

- 页面加载时 `GET /api/config` 获取当前配置并填充表单
- 保存时 `POST /api/config` → 后端写 `config.yaml` → 热加载生效
- 提供"测试连接"按钮：点击后调用一次 embedding 和一次 LLM 简单请求验证连通性

#### 验收标准

- [ ] 配置正常保存并持久化到 config.yaml
- [ ] 保存后问答功能即时使用新模型
- [ ] API Key 密码框不回显明文
- [ ] 测试连接按钮可验证模型连通性

---

### F6：输出文档生成

**优先级**：P1  
**文件**：`engine/exporter.py`

#### 能力

| 输出格式 | 触发方式 | 实现 |
|----------|---------|------|
| Word (.docx) | 问答页"导出为 Word"按钮 | 用 `python-docx` 生成包含问答内容和来源引用的文档 |
| PPT (.pptx) | "导出为 PPT"按钮（可选） | 调用 Agent05 PPT-maker 能力；无 Agent05 时降级为提示"PPT 导出需要 Agent05" |

#### 接口签名

```python
def export_to_word(question: str, answer: str, sources: list[dict], output_path: str) -> str:
    """
    生成 Word 文档，包含:
    - 问题（标题）
    - 回答（正文）
    - 参考来源（表格）
    返回输出文件路径
    """

def export_to_ppt(question: str, answer: str, sources: list[dict], output_path: str) -> str:
    """
    调用 Agent05 生成 PPT
    降级方案：生成 Markdown 结构化大纲
    """
```

#### 验收标准

- [ ] Word 导出文件可正常打开，内容完整
- [ ] Word 包含问题、回答、来源表格
- [ ] PPT 导出在有 Agent05 环境下正常工作

---

### F7：CLI / API Agent 接口

**优先级**：P1  
**文件**：`cli.py`

#### 命令

```bash
# 录入文件
obs-asset ingest --file /path/to/report.docx

# 录入文本
obs-asset ingest --text "今天面试了一个自动驾驶CTO岗位..."

# 查询
obs-asset query "我之前关于组织架构调整的记录有哪些？"

# 查看统计
obs-asset stats

# 启动 Web 服务
obs-asset serve
```

#### 实现要点

- `cli.py` 是 FastAPI 后端的 CLI 封装，通过 HTTP 调用本地 `localhost:{port}` 的 API
- `obs-asset serve` 等同于 `uvicorn server:app --host 0.0.0.0 --port 8080`
- 所有命令返回结构化 JSON，方便 Agent 解析

#### 验收标准

- [ ] 所有 CLI 命令可用
- [ ] JSON 输出格式正确
- [ ] 服务未启动时 CLI 提示启动服务

---

## 六、数据流与状态图

### 6.1 录入流程

```
用户在 Web UI 操作
  │
  ├─ 粘贴文本
  │    → POST /api/ingest/text {"text": "..."}
  │      → parse_text() → chunk_text() → index_chunks()
  │        → 返回 {"status": "ok", "chunks": 5, "source_name": "manual_20260604_001"}
  │
  └─ 上传文件
       → POST /api/ingest/file (multipart)
         → 保存到 raw/YYYY-MM-DD/ 目录
         → parse_file() → chunk_text() → index_chunks()
           → 返回 {"status": "ok", "chunks": 12, "source_name": "report.docx"}
```

### 6.2 问答流程

```
用户输入问题
  → POST /api/query {"question": "..."}
    → retriever.hybrid_search(question)
      → LLM 生成 (SSE 流式)
        → 实时推送 token 到前端
          → 推送来源引用
            → 返回 "done"
```

### 6.3 配置热加载

```
POST /api/config → 写 config.yaml → 重新读取配置 → 更新全局 config 对象
下次 query 或 ingest 请求自动使用新配置（OCR client / LLM client 重新初始化）
```

---

## 七、测试用例清单

### 7.1 文档解析测试 (`test_parser.py`)

| 用例 | 输入 | 期望输出 |
|------|------|---------|
| 解析 docx 文件 | 一个包含 3 段文字的 docx | 提取出完整 3 段文本 |
| 解析 pptx 文件 | 包含 5 页 slide 的 pptx | 提取出所有 slide 文本 |
| 解析 pdf 文件 | 包含 2 页的 pdf | 提取出 2 页文本 |
| 解析 xlsx 文件 | 包含 2 个 sheet 的 xlsx | 提取出表格文本 |
| 解析 txt 文件 | UTF-8 文本文件 | 完整读取 |
| 解析 Markdown 文件 | 包含标题和段落的 md | 完整读取 |
| OCR 图片 | 包含中文文字的 PNG | 返回识别的中文文本 |
| 解析错误文件 | 损坏的 docx | 返回明确错误信息，不崩溃 |

### 7.2 分块引擎测试 (`test_chunker.py`)

| 用例 | 输入 | 期望输出 |
|------|------|---------|
| Markdown 切分 | 3 个 H2 section 的 md | 3 个 chunk，每个含标题行 |
| 纯文本切分 | 5 段话 | 5 个 chunk |
| 超长段落 | 2000 字的单段落 | 切为 2+ 个窗口，重叠 128 tokens |
| 空文本 | "" | 返回空列表 |

### 7.3 检索引擎测试 (`test_indexer.py`, `test_retriever.py`)

| 用例 | 输入 | 期望输出 |
|------|------|---------|
| FT5 关键词检索 | query="组织架构调整" | 返回包含关键词的 chunk |
| 向量语义检索 | query="管理变革" | 返回"组织架构调整"相关 chunk |
| RRF 融合 | 两个列表有交集 | 交集项排名更高 |
| 增量索引 | 新增 chunk 后立即检索 | 新 chunk 可被检索到 |
| 空检索 | 检索不存在的词 | 返回空列表 |

### 7.4 端到端测试 (`test_e2e.py`)

| 用例 | 流程 | 期望 |
|------|------|------|
| 完整录入→检索 | 上传 docx → 等待入库 → 提问 | 答案引用 docx 内容 |
| 多格式混合 | 上传 pptx + pdf + 粘贴文本 → 提问 | 答案综合多个来源 |
| 配置热加载 | 改生成模型 → 提问 | 使用新模型生成答案 |
| OCR 录入 | 上传 PNG 截图 → 提问 | 答案引用 OCR 文本 |

---

## 八、验收标准总览

| # | 功能 | 关键验收条件 |
|---|------|------------|
| F0 | Web 框架 | 三页面正常访问，API 路由全部可用 |
| F1 | 文档解析 | 6 种格式 + OCR 全部提取成功 |
| F2 | 智能分块 | Markdown/纯文本正确切分，超长段落滑动窗口 |
| F3 | 双检索 | FT5 + 向量混合检索，RRF 融合，<2s 延迟 |
| F4 | RAG 问答 | SSE 流式输出 + 来源引用，无内容时不幻觉 |
| F5 | 配置页 | 配置保存/热加载/测试连接 |
| F6 | 文档输出 | Word 导出完整（PPT 可选） |
| F7 | CLI | 全部命令可用，JSON 输出正确 |

---

## 九、开发顺序建议

```
第一轮（核心链路打通）:
  F1 文档解析引擎
  F2 智能分块引擎
  F3 双索引引擎

第二轮（Web 化）:
  F0 Web 应用框架（与 F1-F3 同时开发后台 API）
  F5 模型配置页

第三轮（智能能力）:
  F4 RAG 问答引擎

第四轮（周边完善）:
  F6 文档输出生成
  F7 CLI Agent 接口
```

---

## 十、注意事项

1. **API Key 安全**：config.yaml 中的 api_key 不得提交到 git。在 server.py 启动时读取，config.yaml 加入 `.gitignore`
2. **大文件处理**：PDF 超过 100 页、PPTX 超过 50 页时需要考虑内存控制（分页流式处理）
3. **Ollama 依赖**：启动前检查 Ollama 是否运行且 bge-m3 模型已安装，未安装时在启动日志提示
4. **ChromaDB 版本**：锁定 >=0.4.22，0.5.x 有 breaking changes，不要追最新
5. **Jieba + FTS5**：需验证 macOS 自带 Python 的 sqlite3 是否支持 FTS5 扩展（通常支持），不支持时用 `pysqlite3-binary` 替代
6. **SSE 实现**：FastAPI 使用 `StreamingResponse` + `text/event-stream`，前端用 `EventSource` 接收
7. **并发**：单用户场景，无需异步锁。但 ChromaDB 的 PersistentClient 是线程安全的，不需要额外加锁
