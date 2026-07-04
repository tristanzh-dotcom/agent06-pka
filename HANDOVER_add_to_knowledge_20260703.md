### ☀️ 次日启动胶囊 (Boot Prompt)
请在明天开启新对话时，直接复制以下指令发给系统：

```text
请静默读取并完全理解当前目录下的 `HANDOVER_add_to_knowledge_20260703.md`。
1. 请将本对话的逻辑分支锁定为：【PKA 加入知识库】，并在你回复的第一句话使用 Markdown 的 H1 标题 (`# PKA 加入知识库 工作流重启`) 输出，以便系统自动重命名此对话。
2. 在执行任何操作前，请简要复述当前的【核心卡点】与【下一步行动】。等待我的确认后，再开始执行。
```

## 第一性原理与项目上下文

当前项目是 `/Users/tristanzh/agent/agent06-pka`，主题是 Agent06 PKA 的“加入知识库”能力。

核心目的：让用户把一次已经生成、已经审阅的模型回答，主动保存回个人知识库，使它未来可被 RAG 检索到。但模型输出必须被视为二级、派生、用户确认的生成知识，不能伪装成一手事实源。

必须继续遵守 `/Users/tristanzh/agent/AGENTS.md` 与 `/Users/tristanzh/agent/GLOBAL_MODEL_ROUTING_RECORD.md`：

- Agent06 可用 DeepSeek 做中文语义理解与回答生成，codex-base 做英文报告生成，Ollama bge-m3 做本地语义检索。
- 事实不是由语言模型生成的；生成答案加入知识库后，也只能作为 `generated_asset` 二级知识。
- 本功能保存动作本身不能新增 DeepSeek / codex-base 调用。
- 开发必须按设计确认、计划、TDD、验证的顺序推进。
- 不在业务 agent 仓库内执行 `git commit`、`git push`、`git pull`、`git stash`、`git rebase`。

权威上下文文件：

- `docs/pka-add-to-knowledge-discussion-handoff.md`

## 今日完成事项

今日主要完成的是上下文恢复与设计接续，没有写业务代码。

已确认：

- `docs/pka-add-to-knowledge-discussion-handoff.md` 已读完，并作为当前功能讨论的权威交接文档。
- 根级 `AGENTS.md` 已读，确认收工时必须生成本交接文档。
- `GLOBAL_MODEL_ROUTING_RECORD.md` 已读，确认 Agent06 的模型路由和“事实不是由 LLM 生成”的最高约束。
- 当前仓库 `git status --short` 只显示：
  - `?? docs/pka-add-to-knowledge-discussion-handoff.md`
- 2026-07-03 当前项目根内今天修改/新增的核心文件只有：
  - `docs/pka-add-to-knowledge-discussion-handoff.md`
- 已检查当前主要实现入口：
  - `server.py`
  - `engine/indexer.py`
  - `engine/generator.py`
  - `static/app.js`
  - `tests/test_generator_api.py`

当前尚未实现：

- 未新增 `POST /api/knowledge/add-generated`。
- 未扩展索引 metadata。
- 未修改 generator prompt。
- 未新增 UI 按钮。
- 未新增测试。

## 已作出的关键决策

已明确的功能边界：

- 只做“加入知识库”，不做完整生成资产库 UI。
- 不做 asset browsing、asset editing、asset collections、asset search UI、asset-to-chat replay。
- 不自动保存所有模型回答，必须用户主动触发。
- 入库的生成内容必须标记为：
  - `source_type="generated_asset"`
  - `generated=true`
  - `not_primary_source=true`
  - `user_confirmed_for_knowledge_base=true`
- 必须保留：
  - original question
  - answer
  - source chunk ids
  - derived source names
  - evidence coverage
  - language
  - answer mode
  - model route
  - timestamp
- 未来 `/api/query` 检索到 generated knowledge 时，prompt 必须告诉模型它是“用户确认过的历史生成综合”，不是 primary source。

初步推荐的 v1 方向：

- 新增 `POST /api/knowledge/add-generated`。
- 保存物理 Markdown 文件到 `{data_dir}/generated/knowledge/YYYY-MM-DD/`。
- 文件再进入 RAG 索引，避免 invisible database-only knowledge。
- generated entry 可进入 FTS 和 vector search，但必须保留 `source_type="generated_asset"`。
- `thin` evidence 后端 v1 可 warn 但不一定阻止；`no_answer` 默认应阻止，除非以后引入 explicit force 参数。
- 长答案可以正常 chunk，但每个 chunk 都必须继承 generated/provenance metadata。
- 优先复用现有 ingestion/chunking/indexing 路径；如果 `_ingest_parsed_result()` 无法保留 metadata，再建窄 helper。

尚未最终确认、但当前推荐：

- v1 允许重复保存同一条生成答案，每次保存独立生成 Markdown 文件。理由：每次点击都是一次用户确认的知识沉淀，版本/去重适合后续资产库再处理。

## 未解决的风险/报错

当前没有测试报错，因为尚未进入实现与测试阶段。

未解决设计风险：

- `engine.indexer.HybridIndexer.upsert()` 当前 Chroma metadata 只保存基础字段：`source_name`、`source_type`、`chunk_index`、`created_at`、`raw_file_path`。如果要保存 generated/provenance metadata，需要扩展 `Chunk` 模型或为 upsert 增加 metadata 传递能力。
- `server._ingest_parsed_result()` 当前会调用 `_chunk(parsed.text, parsed.source_name, parsed.source_type)`，但 `ParseResult.metadata` 没有传到 chunk/index metadata。直接复用会丢失 generated 关键元数据。
- `engine.generator.build_deepseek_analysis_prompt()` 当前参考内容只按 chunk 顺序列出，没有区分 primary source 与 generated knowledge；必须增加明确提示，避免生成内容自我强化。
- `engine.models.RetrievedChunk` 当前没有携带任意 metadata；如果 prompt 只依赖 `source_type`，v1 可以先够用，但 provenance 展示和调试可能还不完整。
- 前端 `static/app.js` 当前已经保存 askState 的 question/answer/sources，但没有“加入知识库”交互。UI 要做最小可用，不能扩展成资产库。
- 如果 generated Markdown 内包含完整 answer、metadata 和 wrapper，chunking 后未来检索可能把 metadata 区块也检出。需要设计文件正文结构，既可审计又不污染回答。

未解决产品卡点：

- 是否正式采用“重复保存允许，每次独立文件”的 v1 策略，还需要 TZ 明确确认。

## 下一步行动

明天第一步：

1. 读取 `docs/pka-add-to-knowledge-discussion-handoff.md` 和本文件。
2. 复述核心卡点：generated answer 要可检索，但不能成为 primary evidence；当前代码的 metadata 传递链不足。
3. 等 TZ 确认重复保存策略。

建议接下来的执行顺序：

1. 设计确认：
   - 决定重复保存策略。
   - 决定 generated entries 是否 chunk normally。
   - 决定 `thin` / `no_answer` 的后端阻止策略。
   - 决定 Markdown 文件是否只存 source refs，不存完整 source excerpts。
2. 写正式设计 spec：
   - 建议路径：`docs/superpowers/specs/2026-07-03-pka-add-generated-knowledge-design.md`
3. 写 implementation plan。
4. TDD 红灯测试：
   - `POST /api/knowledge/add-generated` 创建物理 Markdown 文件。
   - 返回 `source_type="generated_asset"` 与 chunk ids。
   - 索引 metadata 保留 generated/provenance 字段。
   - 空 question / answer 返回 400。
   - evidence `no_answer` 默认返回 400。
   - 保存动作不调用 DeepSeek/codex-base。
   - generator prompt 对 `generated_asset` chunk 做二级知识标注。
5. 实现后端：
   - 请求模型 `AddGeneratedKnowledgeRequest`。
   - Markdown 写入 helper。
   - metadata-aware chunk/index helper。
   - prompt 分组或标注。
6. 最小 UI：
   - 在回答完成后显示“加入知识库”按钮。
   - 调用新 endpoint。
   - 成功后发出 `agent06:knowledge-updated`。
7. 验证：
   - 先跑 focused tests，例如 `python3 -m pytest tests/test_generator_api.py` 及新增测试文件。
   - 再视改动范围跑相关 indexer/generator/project file tests。

推荐明天先看的代码位置：

- `server.py` around `_ingest_parsed_result()` and `/api/query`
- `engine/indexer.py` around `HybridIndexer.upsert()`
- `engine/generator.py` around `build_deepseek_analysis_prompt()`
- `static/app.js` around askState, query streaming, sources handling, export actions
