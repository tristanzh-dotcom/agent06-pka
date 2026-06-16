### ☀️ 次日启动胶囊 (Boot Prompt)
请在明天开启新对话时，直接复制以下指令发给系统：

```text
请静默读取并完全理解当前目录下的 `HANDOVER_pka_release_20260616.md`。
1. 请将本对话的逻辑分支锁定为：【PKA封版候选】，并在你回复的第一句话使用 Markdown 的 H1 标题 (`# PKA封版候选 工作流重启`) 输出，以便系统自动重命名此对话。
2. 在执行任何操作前，请简要复述当前的【核心卡点】与【下一步行动】。等待我的确认后，再开始执行。
```

## 第一性原理与项目上下文

PKA v1 的核心目标是可信入库，而不是尽可能多地把文件塞进向量库。同步入库链路只允许可控、可验证、不会拖死单 worker 的内容进入主知识库；扫描件 OCR、超大 chunk 批量、Chroma HNSW 瞬态异常都必须被拦截或降级，避免污染 FTS5/Chroma 或造成服务假死。

当前封版候选的后端主线已经收敛为统一入库管道：入口只负责把手工文本或文件解析成 `ParseResult`，后续统一经过 `_ingest_parsed_result()` 完成普通 chunk、`pre_chunks`、数量熔断、双路写入和标准响应。

## 今日完成事项

- `server.py`
  - 将 `needs_ocr` 同步链路改为立即跳过：返回 `status="skipped"`、`quality.action="needs_ocr_skipped"`、`chunks=0`。
  - 删除同步 OCR 执行器、provider chain 调用、legacy `extract_pdf()` 调用和相关超时/失败分支。
  - 保证 `needs_ocr` 不再进入 `_ingest_parsed_result()`，因此不会写入 Chroma 或 FTS5。
- `engine/indexer.py`
  - 修复 Chroma HNSW RuntimeError 导致 vector 通道静默消失的问题。
  - `search_vector()` 在 `n_results` 较大触发 RuntimeError 时按 `top_k -> 5 -> 3 -> 1` 降级重试。
  - 在当前线程存在 running event loop 时，将 Chroma query 隔离到短生命周期线程中执行，避免 async 测试/请求上下文触发 Chroma 边界异常。
- `tests/test_ingest_quality.py`
  - 新增并更新 needs-OCR 同步熔断断言：即使 OCR provider 可用，也不能调用 OCR，必须保持 `chunks=0` 和 `upsert_calls=[]`。
  - 将旧的同步 OCR 成功/超时/失败契约统一改为 `needs_ocr_skipped`。
- `tests/test_indexer_retriever.py`
  - 新增 Chroma async 边界测试。
  - 新增 HNSW `n_results` 降级重试测试，保留全部失败时 fail-open 的原有防线。
- E2E 验证
  - GEO 扫描 PDF：0.07 秒返回，`skipped=1`，`quality.action=needs_ocr_skipped`，FTS5/Chroma 均为 0。
  - Turtle 超大 PDF：0.75 秒返回 `too_large_skipped`，不污染索引。
  - JLR Corporate Deck：13.25 秒入库，105 chunks，其中 83 个 `org_chart` chunks。
  - JLR 检索质量门禁：10 题全绿。
  - 全量测试：`216 passed, 15 warnings`。
  - `node --check static/app.js` 通过。

## 已作出的关键决策

- 同步链路不再执行 OCR。扫描 PDF 一律 `needs_ocr_skipped`，OCR 只能进入未来异步队列 Backlog。
- “OCR 部分入库”在 v1 封版中被移除出同步主流程。部分入库会制造事实覆盖黑洞，直接拒绝比无预警缺页更可信。
- 413 chunk 数量熔断继续保留，当前阈值为 `ingest.max_sync_chunks_per_file=150`，用于阻断超大文件拖垮同步服务。
- Chroma RuntimeError 不是简单吞掉即可。保留 fail-open 作为最后防线，但先做可控降级重试，尽量保住 vector 通道。
- `source_type` 表征内容形态，`raw_file_path=""` 表示没有原文件下载入口；前端以真值判断隐藏手工文本的原文件链接。
- `org_chart` 旁路仍是 JLR 这类二维结构文档的主策略：Markdown Structure 给生成端读拓扑，Semantic Search Triggers 给 embedding 召回。

## 未解决的风险/报错

- Chroma HNSW 的根因来自底层索引参数或持久化实现，目前通过 `n_results` 自适应降级规避；未来如果升级 Chroma 或改索引参数，需要重新验证。
- OCR provider chain 仍保留在 `engine/ocr.py` 中，但同步服务不再调用。未来异步 OCR 队列接入时，要重新设计任务状态、进度轮询和 OCR 结果质量门禁。
- JLR 普通 PDF chunk 仍存在部分拆字残留，例如 `H O W T O R E A D`。当前只在 org chart 旁路做强归一化，普通 PDF 全局归一化仍是 Backlog。
- 全量测试仍有 15 个第三方 warning：`urllib3` LibreSSL、matplotlib/pyparsing deprecation；当前非业务失败。
- 父级 monorepo 仍有大量其他项目脏文件，本项目封版操作必须只提交 `Personal-Asset` 相关文件。

## 下一步行动

1. 如需继续验证运行态，先确认服务和索引：
   ```bash
   curl -s http://127.0.0.1:8086/api/stats
   python3 -m pytest -q tests/test_retrieval_quality_gate.py
   ```
2. 如需重新跑极限矩阵，按顺序清库后执行：
   - 手工文本入库：验证 `source_type=text`、`raw_file_path=""`。
   - GEO 扫描 PDF：验证 `needs_ocr_skipped`、0 chunks、FTS5/Chroma 0。
   - Turtle PDF：验证 `too_large_skipped`、0 chunks。
   - JLR PDF：验证 105 chunks、83 `org_chart`。
3. 封版后优先 Backlog：
   - 异步 OCR 队列与前端进度轮询。
   - 普通 PDF 字符拆散全局归一化。
   - Chroma HNSW 参数/版本专项复测。
4. 当前推荐 release tag：
   ```bash
   git tag -a pka-v1.0.0-backend-frontend-unified -m "PKA v1.0.0: Unified Ingest Pipeline, Org Chart Bypass, and Ingest Quality Surfacer"
   ```
