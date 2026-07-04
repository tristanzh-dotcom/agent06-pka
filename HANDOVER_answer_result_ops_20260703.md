### ☀️ 次日启动胶囊 (Boot Prompt)
请在明天开启新对话时，直接复制以下指令发给系统：

```text
请静默读取并完全理解当前目录下的 `HANDOVER_answer_result_ops_20260703.md`。
1. 请将本对话的逻辑分支锁定为：【PKA问答结果操作层】，并在你回复的第一句话使用 Markdown 的 H1 标题 (`# PKA问答结果操作层 工作流重启`) 输出，以便系统自动重命名此对话。
2. 在执行任何操作前，请简要复述当前的【核心卡点】与【下一步行动】。等待我的确认后，再开始执行。
```

## 第一性原理与项目上下文

当前项目根：`/Users/tristanzh/agent/agent06-pka`。

当前工作流关注点不是完整知识库设计开发。TZ 已明确：完整的“加入知识库”设计与开发会在另一个工作流中进行。

本工作流要回到更上层、更贴近用户操作的环节：

```text
用户提问
-> PKA 检索个人知识库
-> 模型生成回答
-> 页面出现 Answer Result
-> 用户对这条回答执行操作
```

这里的核心对象暂定为 `Answer Result`，它不是知识库条目，也不是资产库条目，而是一次问答完成后的结果对象。

建议的 `Answer Result` 最小字段：

- `question`：用户原始问题；
- `answer`：模型最终回答；
- `sources`：本轮引用的知识库 chunks；
- `evidence`：chunk-level coverage / input fidelity 等质量元数据；
- `language`：`zh|en`；
- `created_at`；
- `model_route`；
- `answer_mode`：内部推断的 answer / interview_story / retrospective / english_report 等。

当前讨论已经厘清三个动作的命名边界：

- `导出`：一次性生成 Word/PPT/文件，不影响 RAG；
- `保存资产`：保存为可管理、可回看、可复用、可再加工的生成物，默认不进入 RAG；
- `加入知识库`：把模型输出作为可检索的二阶知识加入 RAG，必须标记 generated / not primary source。

## 今日完成事项

1. 明确 PKA 当前不是单纯访问知识库，而是 RAG 问答：
   - 原始问题保留；
   - 检索出的 chunks 作为参考内容；
   - DeepSeek / codex-base 基于“问题 + 检索片段”生成回答。

2. 明确当前 PKA 不会把用户问题改写成新的主问题再发给模型：
   - query expansion 只服务于检索；
   - 原始问题仍进入 LLM prompt。

3. 明确当前模型回答默认是一过性结果：
   - 不会自动写回知识库；
   - 不会自动成为资产；
   - 除非用户导出，否则不会形成长期可管理对象。

4. 对“保存资产”和“加入知识库”做了第一性原理区分：
   - 保存资产 = 生成物管理，默认不进 RAG；
   - 加入知识库 = 二阶知识入库，会影响未来 RAG，必须防污染。

5. 生成了面向另一个工作流的“加入知识库”讨论交接文档：
   - `docs/pka-add-to-knowledge-discussion-handoff.md`
   - 该文档记录了 generated answer 加入 RAG 的边界、metadata、API 草案、风险和测试建议。

6. 确认当前 repo 中已经存在输入连贯性相关实现：
   - `engine/input_fidelity.py`
   - `server.py` 中 `_retrieve_quality_context()` 会调用 `expand_adjacent_chunks()`；
   - trace/debug 下会返回 `evidence.input_fidelity`；
   - 相关测试包括 `tests/test_input_fidelity.py` 和 `tests/test_generator_api.py` 中 input fidelity API 测试。

## 已作出的关键决策

1. 当前工作流不继续推进完整知识库设计。

   原因：TZ 已明确知识库完整设计开发在另一个工作流中进行。本工作流只负责厘清和推进“问答完成后，对 Answer Result 做什么操作”。

2. 不再反复展开“导出 / 保存资产 / 加入知识库”的泛泛说明。

   当前已确认命名：

   - `Export / 导出`
   - `Save Asset / 保存资产`
   - `Add to Knowledge / 加入知识库`

   后续只在具体设计需要时引用。

3. `保存资产` 是更大的产品功能。

   它未来需要：

   - 资产列表；
   - 详情页；
   - 回看；
   - 编辑；
   - 复用；
   - 再次流回对话框；
   - 可能再进入知识库。

   因此它不应被误认为一个简单按钮。

4. `加入知识库` 可以作为一次性动作。

   它 UI 改动相对小，但后端和检索策略必须严谨，尤其要避免模型生成内容污染 primary evidence。

5. 当前本对话下一步不直接实现 UI。

   需要先定义 Answer Result 操作层，再决定 UI 按钮、后端 API 和状态流。

## 未解决的风险/报错

1. 工作树状态：

   当前 `git status --short --untracked-files=all` 显示：

   ```text
   ?? docs/pka-add-to-knowledge-discussion-handoff.md
   ```

   也就是说，当前尚有一份未跟踪的讨论交接文档。不要丢失。

2. 尚未形成 Answer Result 数据结构的正式设计。

   已有口头定义，但还没有落成 SDD / API contract。

3. 保存资产与加入知识库的边界已清楚，但当前还没有明确“问答结果操作层”的最小功能切片。

   需要继续收敛：

   - 当前页面上的 Answer Result 是否需要统一内存状态；
   - 是否先只支持“导出”和“加入知识库”；
   - 是否暂时不做“保存资产”；
   - 是否需要先落一个 `AnswerResult` schema。

4. 全量测试历史边界：

   此前运行全量测试时，已知存在两类非本次路径失败：

   - `tests/test_retrieval_quality_gate.py` 依赖 live corpus；
   - `tests/test_project_files.py` 会读取 `/Users/tristanzh/agent/web` 的 shared web shell 合约。

   做当前 Agent06 后端功能验证时，常用命令是：

   ```bash
   python3 -m pytest -q --ignore=tests/test_retrieval_quality_gate.py --ignore=tests/test_project_files.py
   ```

## 下一步行动

1. 新对话启动后先读取：

   ```bash
   sed -n '1,260p' HANDOVER_answer_result_ops_20260703.md
   sed -n '1,260p' docs/pka-add-to-knowledge-discussion-handoff.md
   ```

2. 复述当前工作流边界：

   - 完整知识库设计开发在另一个工作流；
   - 当前只关注模型回答完成后的 Answer Result 操作层。

3. 先产出一个简短设计，不急着写代码：

   建议文档名：

   ```text
   docs/pka-answer-result-operations-sdd.md
   ```

   建议内容：

   - Answer Result 定义；
   - 当前支持的操作；
   - 暂不支持的操作；
   - 每个操作是否影响 RAG；
   - 前端需要持有什么状态；
   - 后端需要哪些 API；
   - 与另一个“加入知识库”工作流的接口边界。

4. 若进入实现，必须 TDD：

   - 先写 Answer Result 状态/API 测试；
   - 再接最小 UI 或后端操作；
   - 不要顺手实现完整资产库 UI。

5. 不执行 git commit / push / pull / stash / rebase。

   根据全局 AGENTS 规则，业务仓库 Git 写操作交给 Agent08 Git Control。

