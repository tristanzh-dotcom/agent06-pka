### ☀️ 次日启动胶囊 (Boot Prompt)
请在明天开启新对话时，直接复制以下指令发给系统：

```text
请静默读取并完全理解当前目录下的 `HANDOVER_pka_ui_20260605.md`。
1. 请将本对话的逻辑分支锁定为：【PKA页面布局】，并在你回复的第一句话使用 Markdown 的 H1 标题 (`# PKA页面布局 工作流重启`) 输出，以便系统自动重命名此对话。
2. 在执行任何操作前，请简要复述当前的【核心卡点】与【下一步行动】。等待我的确认后，再开始执行。
```

## 第一性原理与项目上下文

PKA 的核心目的不是展示部署状态，而是让用户高效完成个人知识库的三个动作：录入资料、基于资料问答、必要时配置模型/检索。当前 `/agent06` 是 web 平台壳嵌套 PKA iframe 的结构，用户实际看到两层导航和两层头部：外层 Agent06 抬头栏，内层 PKA `PKA / 录入 / 问答 / 设置` 顶部导航。

今天的核心问题已经从“工程信息暴露”推进到“工作台空间组织”：抬头栏右侧仍有大面积空白，而内层导航继续占据 58px 高度，导致真正的录入/问答工作区被压缩。

## 今日完成事项

1. 根据 `PKA_HEADER_REFACTOR.md` 重构 Agent06 平台抬头栏：
   - 修改 `/Users/tristanzh/agent/web/server.mjs`
   - `renderAgent06Page()` 删除“后端通道 / 前端挂载 / 项目名称”等工程信息
   - 抬头改为用户态摘要：知识片段数、资料数、更新时间、DeepSeek 状态、本地向量库状态
   - 后端不可达时显示“知识库后端未连接”，不显示误导性的 `0/0`

2. 扩展 Agent06 状态 API：
   - `/api/agent06/status` 改为顶层状态结构
   - 新增字段：`total_chunks`、`source_count`、`last_updated`、`deepseek_connected`、`embedding_available`
   - 从 PKA 后端 `/api/stats` 和 `/api/config` 聚合状态
   - 本地向量库状态通过配置中的 embedding model 或 `ollama list` 中的 `bge-m3` 判断

3. 紧凑化 Agent06 平台 CSS：
   - 修改 `/Users/tristanzh/agent/web/app/agent06.css`
   - `.agent06-reference-cockpit` 第一行从固定高度改为 `auto`
   - `.agent06-info-status-bar` 从三列 grid 改为纵向 flex
   - 增加 `.agent06-info-stat-line`、`.agent06-info-status-line`、`.status-dot`

4. 补充平台测试：
   - 修改 `/Users/tristanzh/agent/web/tests/agent06-service.test.mjs`
   - 覆盖新状态 API、抬头无工程信息、后端不可达降级
   - agent06 契约测试 9 条通过

5. 修正 PKA CLI 测试：
   - 修改 `tests/test_cli.py`
   - `serve --dry-run` 测试不再硬编码 8080，改为读取 `config.yaml` 当前端口
   - 当前 PKA 配置端口是 8086

6. 生成当前页面排布说明文档：
   - 新增 `PKA_CURRENT_PAGE_LAYOUT.md`
   - 用 Markdown 描述外层平台代理壳、Agent06 抬头栏、iframe、PKA 内层录入/问答/设置三页
   - 明确记录当前横向空白、纵向浪费、重复导航、重复信息

## 已作出的关键决策

1. 平台抬头不再展示端口、URL、挂载路径。
   - 原因：这些是部署诊断信息，对普通用户没有直接工作价值。
   - 放弃方案：继续展示 `http://127.0.0.1:8086` 和 `/agent06/`。

2. 状态 API 保留机器可读字段，但页面只展示用户可理解摘要。
   - 原因：调试信息和用户界面信息应分层。
   - 放弃方案：把所有 backend/frontend 结构直接渲染到页面上。

3. 没有立即改掉内层 PKA topbar。
   - 原因：用户要求先把当前页面排布完整用 Markdown 表示出来，尚未确认下一轮 UI 设计方案。
   - 后续应按 SDD -> TDD -> 实现，不直接动代码。

4. `PKA_CURRENT_PAGE_LAYOUT.md` 只描述现状，不作为实现规格。
   - 原因：它是诊断文档，用于对齐“哪里浪费空间”和“哪些导航重复”。

## 未解决的风险/报错

1. 当前核心卡点：Agent06 抬头栏右侧仍然空置，内层 PKA topbar 继续占据空间。
   - 外层抬头已有状态摘要，但没有承载 `录入 / 问答 / 设置` 操作。
   - 内层 iframe 页面仍显示 `PKA / 录入 / 问答 / 设置`。

2. 页面仍是“平台工作台嵌套 PKA 工作台”。
   - 这会继续导致视觉层级重、首屏可用面积低。
   - 下一轮需要决定是否把页面切换入口上移到外层抬头，并隐藏/删除内层 topbar。

3. `last_updated` 当前可能显示“未知”。
   - 现场 `/api/agent06/status` 返回 `last_updated: null`。
   - 原因是 PKA runtime 的 `last_updated` 是进程内状态，服务重启后会丢失。
   - 如需稳定显示最近更新时间，需要后端从索引/数据库持久化读取，而不是只读 runtime 变量。

4. web 仓库已有大量非本次改动的脏状态。
   - `git status` 显示 `/Users/tristanzh/agent/web` 有大量历史修改和未跟踪文件。
   - 本次主线只应关注 `server.mjs`、`app/agent06.css`、`tests/agent06-service.test.mjs`。
   - 不要回滚 unrelated changes。

5. 今日验证通过，但未做浏览器截图级视觉验收。
   - 已用 curl 确认 HTML 不含旧工程信息。
   - 下一步如果改布局，必须做实际浏览器/截图验收。

## 下一步行动

1. 先阅读当前排布文档：
   - `PKA_CURRENT_PAGE_LAYOUT.md`

2. 和 TZ 确认下一轮 SDD，建议围绕这个接口/布局契约讨论：
   - 外层抬头右侧是否承载 `[录入] [问答] [设置]`
   - 内层 PKA topbar 是否隐藏或删除
   - 平台页脚栏模型说明是否合并到抬头状态行
   - iframe 是否仍保持三页路由，还是由外层导航控制 iframe src

3. 确认后先写测试，不要直接改业务代码：
   - 平台测试：`/Users/tristanzh/agent/web/tests/agent06-service.test.mjs`
   - PKA 文件契约测试：`tests/test_project_files.py`

4. 推荐第一条实现路径：
   - 外层抬头左侧：`个人知识库 + 资料状态`
   - 外层抬头右侧：`录入 / 问答 / 设置` 分段控制
   - 点击控制 iframe src 到 `/agent06/`、`/agent06/ask`、`/agent06/settings`
   - 隐藏 iframe 内层 `.topbar`
   - 删除或压缩平台页脚栏模型说明

5. 常用验证命令：
   - PKA：`python3 -m pytest -q`
   - agent06 平台契约：`cd /Users/tristanzh/agent/web && node --test tests/agent06-service.test.mjs`
   - web 全量：`cd /Users/tristanzh/agent/web && npm test`
   - 语法：`cd /Users/tristanzh/agent/web && node --check server.mjs`

6. 当前服务状态参考：
   - PKA 后端端口：8086
   - web 平台端口：3000
   - 当前访问入口：`http://127.0.0.1:3000/agent06`
