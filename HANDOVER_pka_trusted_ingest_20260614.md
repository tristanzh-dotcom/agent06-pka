### ☀️ 次日启动胶囊 (Boot Prompt)
请在明天开启新对话时，直接复制以下指令发给系统：

```text
请静默读取并完全理解当前目录下的 `HANDOVER_pka_trusted_ingest_20260614.md`。
1. 请将本对话的逻辑分支锁定为：【PKA可信入库架构】，并在你回复的第一句话使用 Markdown 的 H1 标题 (`# PKA可信入库架构 工作流重启`) 输出，以便系统自动重命名此对话。
2. 在执行任何操作前，请简要复述当前的【核心卡点】与【下一步行动】。等待我的确认后，再开始执行。
```

## 第一性原理与项目上下文

PKA 的核心目标不是“尽量把 PDF 变成向量”，而是建立可信入库架构：主知识库只能索引 faithful source text。PyMuPDF 文本层和 OCR 原文转写可以进入 main corpus；Qwen2.5-VL 等视觉理解产物只能作为 page/source-level `visual_metadata`，不得进入 ChromaDB 主 collection 或 FTS5 主表。

本轮工作从页面布局、文件上传体验、PPT 导出问题，推进到 PDF 入库质量治理。最终确认的硬边界是：`needs_ocr` 且 OCR 不可用或失败时必须 `chunks: 0`，不污染主索引；已有脏数据不会因代码修复自动消失，必须 clear 后重新上传或未来做 reindex。

## 今日完成事项

- 生成并落地设计文档：
  - `docs/pka-vector-quality-fix-plan.md`
  - `docs/pka-vector-quality-fix-plan-v2.md`
  - `docs/pka-vector-quality-fix-plan-v3.md`
  - `docs/pka-ocr-provider-abstraction-sdd-tdd.md`
- PDF 质量治理：
  - 新增 `engine/quality.py`，实现 `clean_pdf_text()` 和 `assess_pdf_quality()`。
  - 新增页级指标：`non_empty_page_ratio`、`effective_chars_per_page`、`cleaned_chars_ratio`、`unique_line_ratio`。
  - 增加页眉/页脚/水印清洗，后续追加了基于跨页重复行的频率去重，避免只靠厂商关键词白名单。
  - 清洗后重新评估质量，避免“清洗后几乎没有正文”仍然入库。
- OCR provider chain：
  - 重构 `engine/ocr.py`，加入 `OCRProvider`、`OCRAttempt`、`OCRChainResult`、`OCRProviderChain`。
  - 默认 provider 顺序为 `["paddle", "volcengine"]`。
  - 新增 `PaddleOCRProvider`，本地 PaddleOCR 未安装时不崩溃，安装后懒加载模型。
  - 保留 `VolcengineOCR`，并纳入统一 chain；PDF fallback 走 `extract_pdf()`，不复用图片接口处理 PDF。
  - OCR prompt 明确 faithful transcription：只转写，不摘要、不解释、不改写、不翻译、不补全。
- OCR 安全阀：
  - `engine/config.py` 和 `config.example.yaml` 增加/调整 `ocr.max_pdf_pages = 10`、`ocr.timeout_seconds = 120`。
  - `server.py` 中 OCR chain 通过 `ThreadPoolExecutor(max_workers=1)` 隔离，避免单 worker 请求线程被长时间 OCR 阻塞。
  - OCR 超时返回 `ocr_timeout_skipped`，不写 ChromaDB，不写 FTS5。
  - OCR 部分处理结果加入 `source_page_count`、`pages_processed`、`page_limit_reached`、`partial` 元数据。
- 入库与索引：
  - `server.py` 中 `_ingest_upload_file()` 支持 `needs_ocr` 后走 OCR chain，成功才替换 parse text 并入库。
  - 失败/不可用/超时均返回 skipped，`chunks: 0`。
  - `engine/indexer.py` 已支持 `embedding_text/display_text` 分离：向量可以用 breadcrumb 增强，FTS5 和展示仍使用 display text。
  - `engine/retriever.py` 新增/接入 reranker 设计，位置在 RRF 之后、DeepSeek 之前，作为检索质量门；不参与入库，不要求重建索引。
- 本地环境：
  - 已安装 `paddleocr 3.7.0` 和 `paddlepaddle 3.3.1`。
  - `requirements.txt` 已加入相关依赖。
  - Paddle/PaddleX 模型已在本机缓存到 `~/.paddlex/official_models/`。
- 前端/交互相关：
  - 上传支持多文件选择和选中文件列表展示。
  - 文件上传布局做过收敛，减少无效空白。
  - “清空知识库”结果从 JSON 原文改为更用户可读的提示。
  - 录入后知识片段/资料数量应自动刷新；刷新页面需保持页面状态。
  - 问答页卡片切换样式参考 Agent04 做过同步。
  - 导出 Word 可用；导出 PPT 曾出现下载 MD 的问题，已分析引入 gorden ppt skill 的方向。
- 测试与验证：
  - 执行 `python3 -m pytest -q`，结果：`140 passed, 15 warnings in 7.04s`。
  - 警告来自 `urllib3` LibreSSL 以及 Paddle/PaddleX 触发的 matplotlib/pyparsing deprecation，不是业务失败。
  - 最新 3 份 PDF 上传后：
    - `/api/stats`: `indexed_files=3`, `total_chunks=171`
    - FTS5: `171` 条
    - Chroma collection `pka_knowledge`: `171` 条
    - 服务进程 `127.0.0.1:8086` CPU 回到 0%，OCR 未继续阻塞服务。

## 已作出的关键决策

- 不把“文本层为空/只有水印页码”的 PDF 强行入库。根因不是 chunker 或 embedding，而是没有可信正文。
- OCR fallback 用本地 PaddleOCR 优先、火山方舟兜底，而不是默认云端优先；这符合 PKA 本地知识库和低边际成本属性。
- `low` PDF 不触发 OCR。`low` 表示仍有正文可用，OCR 的目标是救回 `needs_ocr`，不是重做所有低质量文本。
- `needs_ocr` 全链路失败必须 `chunks: 0`。这是防止污染主索引的核心约束。
- Qwen2.5-VL 不参与主正文提取。它的价值在图表/版面理解，未来只能落到 `visual_metadata`，由问答阶段按需引用。
- 跨库写入只能称为补偿式一致性，不能称为跨库原子事务。
- 频率去重优于页脚/水印关键词白名单。页脚的第一性原理特征是“跨页重复”，不是“包含某些已知词”。
- OCR 线程隔离 + 页数安全阀是当前阶段的合适止损方案；完整异步任务队列暂不做，避免过度工程化。

## 未解决的风险/报错

- 当前 OCR 只处理前 10 页作为安全阀。中汽信科和 ECAIA 已可读入库，但属于部分 OCR，不是全文覆盖。前端必须把“部分 OCR”明确展示给用户。
- Python 的线程超时不能强杀已进入 Paddle C++ 推理的后台线程；现在能保证请求路径恢复，但极端长 PDF 仍可能占用 CPU 直到当前推理自然结束。
- 亿欧智库 PDF 是强防复制水印型 PDF。此前 PyMuPDF 文本层几乎只有 `©亿欧智库-大王 (439219)`，PaddleOCR 前几页也混入大量斜向水印。当前策略是不要放宽质量门槛污染主索引；未来需要单独做水印 OCR 专项。
- 上传结果质量状态目前还没有足够清晰地展示到用户界面。用户无法直观看到“全文入库 / 部分 OCR / OCR 失败 / 被拦截”。
- 当前最新上传没有包含亿欧智库那份 PDF；最新 3 份为智能座舱、中汽信科、ECAIA。
- `git status` 在父级 repo 中显示大量其他项目脏变更，不能误改或回滚。PKA 相关变更集中在 `Personal-Asset` 下。
- 根目录 `/Users/tristanzh/Documents/PKA_Data/pka.sqlite3` 是空旧文件；当前真实 FTS 库是 `/Users/tristanzh/Documents/PKA_Data/.fts5/pka.db`，Chroma 在 `/Users/tristanzh/Documents/PKA_Data/.vector`。

## 下一步行动

1. 启动后先确认服务状态：
   ```bash
   lsof -nP -iTCP:8086 -sTCP:LISTEN
   curl -s http://127.0.0.1:8086/api/stats
   ```
2. 验证真实索引一致性：
   ```bash
   python3 - <<'PY'
   from pathlib import Path
   import sqlite3, chromadb
   base = Path('/Users/tristanzh/Documents/PKA_Data')
   con = sqlite3.connect(base / '.fts5' / 'pka.db')
   print('FTS5', con.execute('select count(*) from chunks_fts').fetchone()[0])
   for row in con.execute('select source_name, count(*) from chunks_fts group by source_name order by count(*) desc'):
       print(row)
   con.close()
   client = chromadb.PersistentClient(path=str(base / '.vector'))
   collection = client.get_collection('pka_knowledge')
   print('Chroma', collection.count())
   PY
   ```
3. 下一项最建议做“入库结果质量状态展示”：
   - 上传结果按文件显示 `high / low / ocr / partial / skipped`。
   - 对 `ocr_partial=true` 明确显示“仅 OCR 前 10 页”。
   - 对 `chunks=0` 明确显示“不进入主知识库，避免污染检索”。
4. 在继续开发前按规则先补 SDD/TDD：
   - SDD：定义上传响应 quality UI 契约、前端状态映射、刷新 stats 行为。
   - TDD：覆盖多文件上传后 stats 自动刷新、partial OCR 文案、skipped 文案、清空知识库用户可读文案。
5. 再做检索质量验证：
   - 针对智能座舱报告、中汽信科、ECAIA 各提出 2-3 个确定问题。
   - 检查 hybrid search + reranker 的 top chunks 是否来自正确文件。
   - 确认 DeepSeek 回答未把 OCR partial 覆盖误当全文覆盖。
