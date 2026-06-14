### ☀️ 次日启动胶囊 (Boot Prompt)
请在明天开启新对话时，直接复制以下指令发给系统：

```text
请静默读取并完全理解当前目录下的 `HANDOVER_pka_web_publishing_20260613.md`。
1. 请将本对话的逻辑分支锁定为：【PKA Web发布移交】，并在你回复的第一句话使用 Markdown 的 H1 标题 (`# PKA Web发布移交 工作流重启`) 输出，以便系统自动重命名此对话。
2. 在执行任何操作前，请简要复述当前的【核心卡点】与【下一步行动】。等待我的确认后，再开始执行。
```

## 第一性原理与项目上下文

本轮 PKA/Agent06 工作同时触碰了两类边界：

1. `Personal-Asset` 负责个人知识库的业务能力：资料录入、问答、导出、与 Agent05 的 PPT 生成调用。
2. `/Users/tristanzh/agent/web` 负责统一 Web 发布壳：Agent06 外层导航、iframe 容器、主题变量、跨 agent 一致的布局范式、嵌入状态恢复、发布级视觉治理。

本交接文件只归档需要移交给 web 工作流统一管理或复核的内容。业务逻辑本身仍属于 PKA/Agent06 项目，不应由 web 工作流重写。

## 今日完成事项

1. Agent06 外层功能切换改为接近 Agent04 的卡片式 segmented switch。
   - 文件：`/Users/tristanzh/agent/web/server.mjs`
   - 结构：新增 `agent06-info-switch` 容器，显示 `功能切换` 标签。
   - 结构：原 `agent06-workflow-nav` 保留，叠加 `agent06-tab-switch`。
   - 链接：`录入 / 问答 / 设置` 增加 `agent06-tab-switch__button` class。
   - 目的：解决原来三项无论选中与否显示完全一样的问题。

2. Agent06 外层功能切换样式局部化。
   - 文件：`/Users/tristanzh/agent/web/app/agent06.css`
   - 新增 `.agent06-info-switch`、`.agent06-tab-switch`、`.agent06-tab-switch__button.is-active`。
   - active 背景固定为浅蓝 `#b9e9fb`，与当前 PKA 浅色科技视觉保持一致。
   - 保留 `data-agent06-nav`、`data-agent06-src`、`aria-pressed`，不破坏既有 `agent06.js` 状态同步。

3. Agent06 外层发布壳的测试契约同步。
   - 文件：`/Users/tristanzh/agent/web/tests/agent06-service.test.mjs`
   - 覆盖：`agent06-info-switch`、`功能切换`、`agent06-tab-switch`、active 背景色。
   - 覆盖：受限高度下 iframe、页脚和功能切换仍可见。

4. PKA 录入页做了可见 UI 改动，需 web 工作流复核是否纳入统一视觉治理。
   - 文件：`/Users/tristanzh/agent/Personal-Asset/static/index.html`
   - 删除视觉标题 `内容录入`，只保留 `<main class="ingest-workbench" aria-label="内容录入">`。
   - 原因：外层 Agent06 已有“个人知识库”和功能切换，录入页内部标题重复并占用首屏空间。

5. PKA 文件上传区做了可见 UI/状态改动，需 web 工作流复核。
   - 文件：`/Users/tristanzh/agent/Personal-Asset/static/index.html`
   - 文件：`/Users/tristanzh/agent/Personal-Asset/static/style.css`
   - 文件：`/Users/tristanzh/agent/Personal-Asset/static/app.js`
   - 支持多文件队列、文件类型 badge、文件大小、单文件移除。
   - `清空选择` 从 disabled 浅色常驻改为无文件时 hidden、有文件时显示。
   - 旧上传失败状态不再通过 embedded-state 恢复，避免刷新后保留 `上传失败：{"detail":"Not Found"}`。
   - API JSON 错误改成人话，例如 `接口未找到，请刷新后重试`。

6. Agent06 嵌入状态与数据刷新链路已在本轮/前序本对话内强化，需 web 工作流复核边界。
   - PKA iframe 内通过 `postMessage` 发出 `agent06:knowledge-updated`。
   - web 发布壳监听后刷新 header stats。
   - PKA iframe 内支持 `web-publishing:embedded-state:snapshot`、`restore`、`request-snapshot`。
   - 刷新页面时保留输入草稿和非错误反馈，但不保留 stale upload failure。

7. Agent06 发布壳曾处理过后端不可用时的用户可读降级页面。
   - 文件：`/Users/tristanzh/agent/web/server.mjs`
   - 目标：避免 iframe 内出现裸 JSON `connect ECONNREFUSED 127.0.0.1:8086`。
   - 相关测试在 `agent06-service.test.mjs` 内覆盖后端不可用 HTML 状态。

8. Agent06 页脚采用单行模型链路说明。
   - 文件：`/Users/tristanzh/agent/web/server.mjs`
   - 文件：`/Users/tristanzh/agent/web/app/agent06.css`
   - 文案：`GPT-5.5 基座模型 · DeepSeek V4 Pro 中文语义分析 · bge-m3 + ChromaDB 本地向量检索`
   - 注意：该文案是发布壳显示层，应由 web 工作流决定最终样式；模型路由事实仍以 `GLOBAL_MODEL_ROUTING_RECORD.md` 和 PKA 配置为准。

9. 与 Agent05/PPT-maker 的边界被明确。
   - PKA `导出 PPT` 现在优先尝试 Agent05/PPT-maker 服务，失败时回退本地 `python-pptx`。
   - Web 工作流不应把 Gorden PPT 模板逻辑复制到 Agent06 发布壳。
   - Web 工作流只需关注 Agent05/Agent06 跨 agent 入口、下载体验、错误态和视觉一致性。

## 已作出的关键决策

1. PKA iframe 内不恢复一级导航。
   - 原因：`录入 / 问答 / 设置` 的导航责任已经上移到 Agent06 外层发布壳。
   - 放弃方案：在 PKA 内部重新做 topbar 或二级导航。

2. Agent06 外层功能切换使用 Agent04 类似的 segmented switch，但不直接复用 Agent04 class。
   - 原因：避免跨 agent CSS 泄漏；Agent06 使用 `.agent06-*` scoped selector。
   - 放弃方案：直接套 `.agent04-tab-switch`。

3. PKA 录入页删除外层视觉标题。
   - 原因：外层发布壳已提供上下文，内部重复标题浪费首屏高度。
   - 保留方案：用 `aria-label` 保留语义。

4. `清空选择` 使用 hidden，而不是 disabled 浅色常驻。
   - 原因：无文件时按钮没有操作价值；disabled 低对比状态让用户误以为 UI 损坏。

5. 上传失败的旧错误不应跨刷新恢复。
   - 原因：`Not Found` 多数来自旧进程/旧接口状态，恢复后会误导用户以为当前仍失败。
   - 保留：文本草稿、问题输入、普通反馈仍可恢复。

6. Agent05/Gorden PPT 能力通过 Agent05 服务边界调用。
   - 原因：Agent05/PPT-maker 拥有模板选择、Gorden 构建、预览和质量检查职责。
   - 放弃方案：把 Gorden 脚本和模板编排直接内嵌进 PKA 后端。

## 未解决的风险/报错

1. `/Users/tristanzh/agent/web` 工作区存在多项非本轮 PKA Web 移交内容的脏文件。
   - web 工作流接手时必须用精确 diff 和文件路径识别，不要误把其他 agent 的改动归入 Agent06。
   - 本交接重点文件是：
     - `/Users/tristanzh/agent/web/server.mjs`
     - `/Users/tristanzh/agent/web/app/agent06.css`
     - `/Users/tristanzh/agent/web/app/agent06.js`
     - `/Users/tristanzh/agent/web/app/embedded-state.js`
     - `/Users/tristanzh/agent/web/tests/agent06-service.test.mjs`
     - `/Users/tristanzh/agent/web/tests/result-state-persistence-browser.test.mjs`

2. PKA 内部静态页面仍在 `Personal-Asset/static/*` 中维护。
   - 这些是可见发布面的一部分，但目前不在 `/Users/tristanzh/agent/web`。
   - web 工作流需要决定：继续允许 domain 项目维护局部 UI，还是将通用布局/状态规范沉淀到 web 发布层文档或模板中。

3. Agent06 功能切换 active 色目前固定为 `#b9e9fb`。
   - 这是为了贴合当前浅色科技视觉。
   - 若 web 工作流要统一 theme token，应评估是否改为平台 token，例如 `--ka-accent-soft` 或 Agent06 专属 token。

4. `last_updated` 仍可能显示 `未知`。
   - 这是 PKA runtime 状态和持久化索引之间的业务问题，不属于单纯 web 发布壳问题。

5. Gorden 内置 PPT 模板存在非商业用途限制。
   - Web 工作流若要强化 Agent05/Agent06 高质量 PPT 入口，需要显式标注或避免暗示商业授权。

6. 一次误触发真实 Agent05 生成曾产生临时工作目录，已经删除。
   - 删除目录：`/Users/tristanzh/agent/PPT-maker/work/ppt-maker/20260613-151847_964df0b4`
   - 当前 Agent05 `/api/generate/status` 检查为 `in_progress:false`。

## 下一步行动

1. Web 工作流第一步读取本文件，并重点检查 Agent06 发布壳 diff：
   - `cd /Users/tristanzh/agent/web`
   - `git diff -- server.mjs app/agent06.css app/agent06.js app/embedded-state.js tests/agent06-service.test.mjs tests/result-state-persistence-browser.test.mjs`

2. 复核 Agent06 外层功能切换视觉是否应成为平台级模式。
   - 对照 Agent04 的 `功能切换`。
   - 判断 Agent06 是否继续使用 `#b9e9fb`，或改为平台 token。
   - 确保不影响 Agent02/03/04/05。

3. 复核 PKA 内部录入页可见 UI 改动是否符合 web 发布规范。
   - 文件：
     - `/Users/tristanzh/agent/Personal-Asset/static/index.html`
     - `/Users/tristanzh/agent/Personal-Asset/static/style.css`
     - `/Users/tristanzh/agent/Personal-Asset/static/app.js`
   - 重点：删除 `内容录入` header、文件上传队列布局、清空选择显示策略、错误态文案。

4. 跑 web 侧验证：
   - `cd /Users/tristanzh/agent/web && node --check server.mjs`
   - `cd /Users/tristanzh/agent/web && node --test tests/agent06-service.test.mjs`
   - 如要覆盖状态恢复：`cd /Users/tristanzh/agent/web && node --test tests/result-state-persistence-browser.test.mjs`

5. 跑 PKA 侧验证，确认 web 复核不破坏业务：
   - `cd /Users/tristanzh/agent/Personal-Asset && python3 -m pytest -q`
   - 当前基线结果：`94 passed, 1 warning`

6. 浏览器验收建议：
   - 打开 `http://127.0.0.1:3000/agent06?view=ingest`
   - 检查外层 `功能切换` active 态。
   - 检查录入页不再显示外层 `内容录入`。
   - 检查无文件时 `清空选择` 不显示；选中文件后才显示。
   - 手动注入旧上传错误或刷新页面，确认 stale `上传失败：{"detail":"Not Found"}` 不再恢复。

