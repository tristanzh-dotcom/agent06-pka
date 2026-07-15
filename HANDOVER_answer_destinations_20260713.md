### ☀️ 次日启动胶囊 (Boot Prompt)
请在明天开启新对话时，直接复制以下指令发给系统：

```text
请静默读取并完全理解当前目录下的 `HANDOVER_answer_destinations_20260713.md`。
1. 请将本对话的逻辑分支锁定为：【PKA问答结果去向操作】，并在你回复的第一句话使用 Markdown 的 H1 标题 (`# PKA问答结果去向操作 工作流重启`) 输出，以便系统自动重命名此对话。
2. 在执行任何操作前，请简要复述当前的【核心卡点】与【下一步行动】。等待我的确认后，再开始执行。
```

## 第一性原理与项目上下文

项目根：`/Users/tristanzh/agent/agent06-pka`。

本轮完成 PKA AnswerResult 的三个明确去向：本地资料、Obsidian 发布、加入 PKA 问答检索。生成内容可被保存为二阶知识，但永远不是 primary evidence；只有 generated chunks 时，系统默认拒答事实结论。

全局模型路由新规则已对齐：无 generation endpoint 时，`codex-base` 只是确定性英文报告渲染兼容标识，不是远程或本地 Codex 模型。运行时字段及历史 `model_route` 均保持不改名、原样透传。

## 今日完成事项

1. 新增 `engine/generated_knowledge.py`：从 AnswerAsset 写入 generated Markdown、保存 provenance metadata，并索引为 `source_type="generated_asset"`。
2. 扩展 `engine/chunker.py`、`engine/indexer.py`：将 generated metadata 持久化到 FTS/向量索引；向量部分写入且清理失败时，写入本地隔离表，向量检索过滤对应 chunk ID。
3. 更新 `engine/generator.py`：
   - primary + generated 混合检索时，DeepSeek 分析与远程英文报告提示都明确 generated 为 secondary context、不得作为 primary evidence；
   - generated-only 检索在所有模型/确定性渲染分支之前终止，返回缺 primary source 的明确提示，并输出 `source_status="generated_only"`；
   - 无 endpoint 的 `codex-base` 确定性英文渲染路径未改。
4. 新增 `POST /api/answer-assets/add-pka-retrieval`：顺序为本地保存 → generated-secondary 索引 → Agent10 发布；索引失败、隔离、Agent10 未配置或发布失败均返回明确 partial 状态，且不触发发布。
5. 接线问答页三枚既有控件：
   - `保存到本地资料` → `api/answer-assets/save-local`；
   - `发布到 Obsidian` → `api/answer-assets/publish-obsidian`；
   - `加入 PKA 问答检索` → `api/answer-assets/add-pka-retrieval`。
   控件仅在 SSE `done` 后可用；检索按钮对 `no_answer` 与 `generated_only` 保持禁用。
6. 修改核心文件：`engine/chunker.py`、`engine/generated_knowledge.py`、`engine/indexer.py`、`engine/generator.py`、`server.py`、`static/app.js`、`static/ask.html` 及对应测试文件。
7. 已验证：
   - Task 3 受影响回归：`python3 -m pytest -q tests/test_generated_knowledge.py tests/test_answer_result_operations.py tests/test_generator_api.py tests/test_indexer_retriever.py` → `105 passed`；
   - Task 4：`python3 -m pytest -q tests/test_answer_result_operations.py` → `11 passed`；
   - `node --check static/app.js`、`python3 -m compileall -q engine server.py`、`git diff --check` 均通过。

## 已作出的关键决策

1. TZ 确认：generated-only 检索默认“拒答事实结论”，不调用 DeepSeek、远程 generation 或确定性 `codex-base` renderer。
2. `model_route` 是兼容审计字段；本轮不重命名 `codex-base` 或任何历史路由值。
3. “加入 PKA 问答检索”只接纳有 primary evidence 的 AnswerResult；生成内容进入 RAG 时必须带 generated / not-primary 标记。
4. 遇到索引无法彻底清理的部分写入，优先隔离 chunk 并阻断 Agent10 发布，不把它伪报成普通失败或成功。
5. Git 仍未写入：所有变更留在当前 `main` 工作树，后续 Git add/commit/push 必须交由 Agent08 Git Control。

## 未解决的风险/报错

1. 工作树有未提交修改及一个新文件 `engine/generated_knowledge.py`；本交接文档也尚未提交。
2. Task 5 的真实服务端重启、Agent10 实机联调、Obsidian vault/mirror 复核尚未执行。
3. `python3 -m pytest -q tests/test_answer_result_operations.py tests/test_project_files.py` 的全组合运行仍有 3 个既有、非本切片失败：全局 `confirm(` 断言及 shared-web Agent06 workflow-switch 合约；Task 4 相关的 3 个聚焦测试均已通过。
4. Python 测试会输出现有环境告警：urllib3 LibreSSL 与 matplotlib/Pyparsing deprecation；未观察到本轮新增失败。

## 下一步行动

1. 先读取本文件，再读 `docs/superpowers/plans/2026-07-13-pka-answer-destinations-function.md`；计划的 Task 5 是下一项。
2. 先做只读复核：`git status --short` 与 `git diff --stat`，确认本地变更仍完整。
3. 按 Task 5 执行受控实机验证：使用非敏感 AnswerResult 验证本地保存、Obsidian 发布、RAG 晋升、重复操作幂等、Agent10 mirror 及响应中无密钥。
4. 实机验证后更新本交接状态或生成新的当天交接文件；若需要提交，转 Agent08 Git Control。

## 2026-07-15 Task 5 验收更新

Task 5 已完成。受管 Agent06 已通过 Agent08 重启，并加载三条结果去向接口；非敏感实机样本验证了本地保存、Obsidian 发布、generated-secondary PKA 检索晋升、重复点击幂等复用、Agent10 mirror 与响应脱敏。

- Agent06 聚焦测试 `116 passed`，非实时回归 `259 passed`；Agent10 全套 `103 passed`，Agent08 全套 `106 passed`。
- 首次 Obsidian 发布与检索晋升均返回已发布且 mirror `upserted`；重复操作保留同一 Agent06/Agent10 资产，返回 `idempotent_reuse` 与 `reused`，不会重写既有 note。
- Agent10 治理快照显示 3 个 mirror assets、0 个 open gaps、0 个 active/stale locks 与 0 个 temporary files；验证过程未记录答案正文或任何凭据。
- 联调发现并修复两项受管运行合同缺口：Agent08 启动 Agent06 时遗漏 Agent10 runtime 环境；Agent10 幂等复用响应未明确标示 mirror 已复用。
