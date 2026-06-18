### ☀️ 次日启动胶囊 (Boot Prompt)
请在明天开启新对话时，直接复制以下指令发给系统：

```text
请静默读取并完全理解当前目录下的 `HANDOVER_pka_v11_20260616.md`。
1. 请将本对话的逻辑分支锁定为：【PKA自动化验收与检索可观测性】，并在你回复的第一句话使用 Markdown 的 H1 标题 (`# PKA自动化验收与检索可观测性 工作流重启`) 输出，以便系统自动重命名此对话。
2. 在执行任何操作前，请简要复述当前的【核心卡点】与【下一步行动】。等待我的确认后，再开始执行。
```

## 第一性原理与项目上下文

PKA v1.1 的当前核心目标是先把 v1.0 的可信入库能力固化成一键自动化验收安全网，再进入检索可观测性。先造安全网，再做大手术：后续异步 OCR、检索调试面板、全局文本归一化都必须能被同一套矩阵验证拦住退化。

当前系统基线：

- 统一入库管道 `_ingest_parsed_result()` 已经把手工文本和文件入库收敛到同一漏斗。
- 同步链路保留两道熔断：`max_sync_chunks_per_file=150` 数量熔断、`needs_ocr_skipped` 时间熔断。
- JLR Corporate Deck 的 Org Chart 旁路稳定落库：105 chunks，其中 83 个 `org_chart`，22 个 `pdf`。
- Q6/Q8 检索对峙门禁成立：说明类问题 Top source 为 `pdf`，结构关系问题 Top source 为 `org_chart`。

## 今日完成事项

- 新增 `scripts/verify_ingest_matrix.py`
  - 以纯客户端黑盒方式调用 `http://127.0.0.1:8086`。
  - 覆盖 7 个验收用例：手工文本、Turtle 超大文件、GEO 扫描件、JLR 正向入库、Q6 说明类检索、Q8 结构化检索、最终 JLR 基线恢复。
  - 每次运行开头清库，极限矩阵后再次清库并恢复 JLR 105 chunk 生产基线。
  - 直接读取 FTS5 与 Chroma 物理计数，确认双路一致。
  - 生成机器可读 JSON 报告到 `docs/superpowers/releases/verification_report_20260616_210000.json`。
- 新增 `tests/test_verify_ingest_matrix.py`
  - 使用 fake client 锁定脚本状态机。
  - 断言首步清库、末步恢复 JLR 基线、报告写盘。
  - 新增 CLI help 测试，防止直接运行 `python3 scripts/verify_ingest_matrix.py` 时因 `engine` 导入路径失败。
- 微调 `tests/test_retrieval_quality_gate.py`
  - Q7 必含文本从 `Digital Platform` 调整为更贴近当前查询与真实投影文本的 `D P` + `FIRST LINE STRUCTURE`。
  - Q6 对峙测试不再要求 Top1 必须是唯一的 `HOW TO READ` chunk，只要求 Top1 类型为 `pdf`，且 top5 仍包含 `HOW TO READ` 与 `ORGANISATION CHARTS` 证据。
- 执行真实验收
  - `python3 scripts/verify_ingest_matrix.py --timestamp 20260616_210000` 通过。
  - `python3 -m pytest -q` 通过：`222 passed, 15 warnings`。
  - 最终物理库：FTS5 105，Chroma 105，source types 为 `{"org_chart": 83, "pdf": 22}`。

## 已作出的关键决策

- 自动化验收脚本只走真实 HTTP，不 mock 后端内部函数。原因是它要证明真实客户端链路、SSE、FTS5/Chroma 写入和恢复逻辑都成立。
- 脚本必须有零状态残留：开始清库，最后恢复 JLR 基线，避免 Turtle/GEO/手工文本污染后续调试。
- 验收报告写成 JSON，而不是只打印终端 PASS。原因是后续 CI/CD 或 release 审计需要机器可读证据。
- 不在 v1.1 第二轮直接开 `/api/search`。检索可观测性先落在真实主链路 `/api/query` 的 debug SSE sources event 上，避免出现搜索接口和问答接口两套逻辑漂移。
- 检索可观测性 SDD 已初步口头定稿，但还没有写 RED 测试：
  - `POST /api/query` 请求体新增可选 `debug: true`。
  - 默认 `debug=false`，正常 SSE 不出现 `_debug`。
  - debug 开启时，仅在 `sources` event 附加 `_debug`。
  - `_debug` 至少包含 `fts_rank`、`vector_rank`、`rrf_score`、`final_rank`、`intent_bias_triggered`、`intent_bias_applied`、`source_type`、`chunk_id`。

## 未解决的风险/报错

- Chroma 进程锁/并发访问风险仍存在：当 8086 服务进程和 pytest 进程同时打开同一 Chroma 持久化目录时，HybridRetriever 排序边界会偶发波动。今天的处理方式是跑完真实 HTTP 矩阵后停止 8086，再跑 pytest。
- `scripts/verify_ingest_matrix.py` 当前会操作真实知识库和真实 8086 服务，不适合在已有人工测试数据时直接运行；运行后会恢复成 JLR 105 chunk 基线。
- 当前新增脚本和测试尚未提交。`git status --short -- .` 里本轮相关变更为：
  - `?? scripts/verify_ingest_matrix.py`
  - `?? tests/test_verify_ingest_matrix.py`
  - `?? docs/superpowers/releases/verification_report_20260616_210000.json`
  - ` M tests/test_retrieval_quality_gate.py`
  - 本交接文件 `HANDOVER_pka_v11_20260616.md`
- 父级 `/Users/tristanzh/agent` 仍有大量其他项目脏文件。本项目后续提交必须限定在 `Personal-Asset` 相关路径。
- 15 个 warnings 仍是第三方环境警告：urllib3 LibreSSL、matplotlib/pyparsing deprecation，当前非业务失败。

## 下一步行动

1. 先确认没有 8086 进程持有 Chroma：
   ```bash
   lsof -nP -iTCP:8086 -sTCP:LISTEN || true
   ```
2. 复跑当前安全网：
   ```bash
   python3 -m pytest -q tests/test_verify_ingest_matrix.py tests/test_retrieval_quality_gate.py
   python3 -m pytest -q
   ```
3. 如果要重新跑黑盒矩阵，先启动 8086：
   ```bash
   python3 -m uvicorn server:app --host 0.0.0.0 --port 8086
   python3 scripts/verify_ingest_matrix.py --timestamp 20260617_XXXXXX
   ```
   跑完后停止 8086，再跑 pytest。
4. 进入第 2 轮「检索可观测性」时，先写 RED：
   - `tests/test_indexer_retriever.py`
     - `HybridRetriever.hybrid_search_with_debug()` 返回 chunks + debug payload。
     - Q8 `intent_bias_triggered == True`，Q6 `intent_bias_triggered == False`。
   - `tests/test_generator_api.py`
     - `/api/query` debug=true 的 `sources` event 包含 `_debug`。
     - `/api/query` 默认不输出 `_debug`。
5. GREEN 实现建议：
   - 在 `engine/retriever.py` 保留现有 `hybrid_search()` 兼容行为。
   - 新增 `hybrid_search_with_debug()`。
   - 给 `apply_org_chart_intent_bias()` 增加可选 debug 输出，不改变排序公式。
   - 在 `server.py` 的 `QueryRequest` 增加 `debug: bool = False`，只在 debug 开启时把 payload 透传到 generator/source event。
