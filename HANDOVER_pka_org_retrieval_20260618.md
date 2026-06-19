### ☀️ 次日启动胶囊 (Boot Prompt)
请在明天开启新对话时，直接复制以下指令发给系统：

```text
请静默读取并完全理解当前目录下的 `HANDOVER_pka_org_retrieval_20260618.md`。
1. 请将本对话的逻辑分支锁定为：【PKA组织架构检索消歧与仓库拆分收口】，并在你回复的第一句话使用 Markdown 的 H1 标题 (`# PKA组织架构检索消歧与仓库拆分收口 工作流重启`) 输出，以便系统自动重命名此对话。
2. 在执行任何操作前，请简要复述当前的【核心卡点】与【下一步行动】。等待我的确认后，再开始执行。
```

## 第一性原理与项目上下文

本次工作属于 PKA / Agent06 个人知识库的组织架构检索质量收口。核心目标是让 JLR org-chart 类资料在用户提问时按真实语义选择证据页：如果问题明确带有上级锚点，例如 `Marcus 下面`、`under him`，应优先沿该上级链路收敛；如果问题没有上级锚点，只问某个团队或实体本身，则应允许详细分页优先，而不是强制回全局总览页。

Project path was renamed during Agent08 repo split; old path `/Users/tristanzh/agent/Personal-Asset` now maps to new path `/Users/tristanzh/agent/agent06-pka`. 收工扫描、测试、git 状态均已按新 repo 根目录 `/Users/tristanzh/agent/agent06-pka` 执行。不要在 `/Users/tristanzh/agent` monorepo 根目录执行 `git stash pop`。

当前开发阶段：verification / handoff。今天最后一轮 org-chart 检索消歧修复在 repo split 前后的路径切换中出现了证据断层，必须明天先处理该断层，再继续实测。

## 今日完成事项

- 已读取并理解 `/Users/tristanzh/agent/AGENT_REPO_SPLIT_NOTICE_20260618.md`。
- 确认 PKA 新权威 repo 根目录为 `/Users/tristanzh/agent/agent06-pka`。
- 在新 repo 内执行证据扫描：
  - `git rev-parse --show-toplevel` 返回 `/Users/tristanzh/agent/agent06-pka`。
  - `git status --short --untracked-files=all` 仅显示未跟踪日志文件：
    - `pka-backend-8086.log`
    - `pka-backend.log`
  - 新 repo 当前没有 tracked diff。
- 在新 repo 内执行验证：
  - `python3 -m pytest -q --ignore=tests/test_retrieval_quality_gate.py`
  - 结果：`238 passed, 15 warnings`
- 确认当前 8086 服务已从新 repo 启动：
  - PID: `28352`
  - 启动目录：`/Users/tristanzh/agent/agent06-pka`

对话中已完成但未进入新 repo tracked diff 的工作，需要明天优先复核：

- org-chart 检索消歧 SDD 草案：
  - 目标文件曾为 `docs/pka-org-chart-retrieval-disambiguation-sdd.md`
  - 在新 repo 当前不存在。
- 检索修复逻辑曾落在：
  - `engine/retriever.py`
  - 关键修复包括 `leads/report to/under him` 英文关系意图、`and/structurally` 等 focus-token stopword。
- 回归测试曾落在：
  - `tests/test_indexer_retriever.py`
  - 覆盖 anchored-chain 与 unanchored detailed-page 两种裁决。
- 旧路径验证结果曾包括：
  - `python3 -m pytest -q --ignore=tests/test_retrieval_quality_gate.py` -> `248 passed`
  - 端到端 Marcus hard cases 6/6 通过。

## 已作出的关键决策

- 默认采用推荐裁决，不再等 TZ 二次选择：
  - 带明确上级锚点的问题，优先上级链路。
  - 未带上级锚点的问题，优先详细团队页。
- 不追求把自动压力测试中的所有 OCR 派生问题都变绿。部分自动问题本身是脏 oracle，例如把部门节点反推跨页祖先，或从 OCR 残留生成 `VCDP VCDP`、`Ireland Ireland` 这类问题。
- 压测的交付标准应分层：
  - 用户高频真实问题与 Marcus global-site hard cases 必须端到端正确。
  - 自动遍历问题用于暴露新能力边界，不作为无条件通过门槛。
- repo split 后，所有 PKA 收工、测试、服务重启、git 操作必须以 `/Users/tristanzh/agent/agent06-pka` 为根。不要把 `/Users/tristanzh/agent` 根目录中旧路径删除视作项目文件被删。

## 未解决的风险/报错

- 核心风险：今天最后一轮 org-chart disambiguation 修改没有出现在新 repo tracked diff 中。新 repo 当前 `engine/retriever.py` 仍只显示旧的 relation intent 规则，不包含今天最后加入的 focus-token 扩展与 SDD 文件。
- `/Users/tristanzh/agent` 根目录仍处于 repo split 中间态，`git status` 会显示大量旧目录删除和新 `agentXX-*` 目录未跟踪。这是 split 预期状态，不能在 monorepo 根执行普通恢复动作。
- 根目录存在冻结 stash：
  - `stash@{Thu Jun 18 22:01:48 2026}: On main: pre-split-freeze-20260618-late-pet-ledger`
  - `stash@{Thu Jun 18 21:47:48 2026}: On main: pre-split-freeze-20260618-residual`
  - `stash@{Thu Jun 18 21:47:33 2026}: On main: pre-split-freeze-20260618`
  - 明天如需恢复，只能做 path-based restore，从旧 `Personal-Asset/` 前缀映射到新 `agent06-pka/`，禁止 blind `git stash pop`。
- 新 repo 的当前验证基线是 `238 passed`，而对话中旧路径最后一轮曾出现 `248 passed`。这说明 repo split 造成测试/文件状态不同步，明天第一步必须对齐状态。
- `tests/test_retrieval_quality_gate.py` 仍依赖可变 live corpus，当前收工验证按既有方式使用 `--ignore=tests/test_retrieval_quality_gate.py`。

## 下一步行动

1. 在新对话中首先确认当前目录是 `/Users/tristanzh/agent/agent06-pka`。
2. 读取 `/Users/tristanzh/agent/AGENT_REPO_SPLIT_NOTICE_20260618.md` 和本文件。
3. 不要在 `/Users/tristanzh/agent` 根执行 `git stash pop`。
4. 先检查新 repo 是否仍缺少今天最后一轮文件：
   ```bash
   cd /Users/tristanzh/agent/agent06-pka
   rg -n "leads\\?|ORG_CHART_FOCUS_STOPWORDS|test_org_chart_relation_query_keeps_named_person_page|retrieval-disambiguation" engine tests docs -S
   git status --short --untracked-files=all
   ```
5. 若缺失，按 TDD 重新在新 repo 落地：
   - 新增/恢复 `docs/pka-org-chart-retrieval-disambiguation-sdd.md`
   - 在 `tests/test_indexer_retriever.py` 增加 anchored-chain 和 unanchored detailed-page 回归测试
   - 在 `engine/retriever.py` 补齐英文关系意图和 focus-token stopword
6. 运行验证：
   ```bash
   cd /Users/tristanzh/agent/agent06-pka
   python3 -m pytest -q tests/test_indexer_retriever.py tests/test_generator_api.py
   python3 -m pytest -q --ignore=tests/test_retrieval_quality_gate.py
   ```
7. 重启新 repo 的 8086 服务后，端到端验证 Marcus hard cases：
   - Marcus 中国研发领导 -> Dave Ross
   - Marcus 爱尔兰 -> Paul Girr
   - Marcus India -> Jai Gupta
   - Marcus Hungary -> Akos Garaba
   - Marcus USA -> Blake Lyman
8. 只有在新 repo 文件、测试、API 三者都对齐后，再通知 TZ 进行下一轮实测。
