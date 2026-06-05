### ☀️ 次日启动胶囊 (Boot Prompt)
请在明天开启新对话时，直接复制以下指令发给系统：

```text
请静默读取并完全理解当前目录下的 `HANDOVER_pka_layout_20260605.md`。
1. 请将本对话的逻辑分支锁定为：【PKA页面布局】，并在你回复的第一句话使用 Markdown 的 H1 标题 (`# PKA页面布局 工作流重启`) 输出，以便系统自动重命名此对话。
2. 在执行任何操作前，请简要复述当前的【核心卡点】与【下一步行动】。等待我的确认后，再开始执行。
```

## 第一性原理与项目上下文

PKA 的核心价值是让用户高效完成个人知识库的三个动作：录入资料、基于资料问答、必要时配置模型/检索。页面布局必须服务这三件事，不能让导航、页脚、外层容器、卡片嵌套和硬编码高度抢占核心工作区。

当前 `/agent06` 是 web 平台壳嵌入 PKA iframe。已经确认 PKA 独立 8086 访问降级为裸业务面板，完整工作台入口以 `http://127.0.0.1:3000/agent06` 为准。导航归属外层平台壳，iframe 内部只暴露业务内容。

## 今日完成事项

1. Agent06 外层导航改为真实可切换入口：
   - 修改 `/Users/tristanzh/agent/web/server.mjs`
   - 导航从 `<button>` 改为真实链接：
     - `/agent06?view=ingest`
     - `/agent06?view=ask`
     - `/agent06?view=settings`
   - iframe 初始 src 根据 `view` 参数设置。
   - 显式 `view` 请求增加 `data-embedded-state-force-src="true"`，避免 localStorage 中旧 iframe 路由覆盖用户指定入口。

2. Agent06 导航 JS 补齐 URL、iframe、active 状态同步：
   - 修改 `/Users/tristanzh/agent/web/app/agent06.js`
   - 点击导航时：
     - `event.preventDefault()`
     - 更新 iframe `src`
     - `history.replaceState()` 同步地址栏 `?view=...`
     - 从 iframe src 推导 active 状态。

3. Agent06 外层高度修正：
   - 修改 `/Users/tristanzh/agent/web/app/agent06.css`
   - 删除 `minmax(720px, 1fr)`、`minmax(680px, 1fr)`、iframe `min-height: 704px`。
   - 使用 `.agent06-view.agent06-reference-cockpit` 提升选择器权重，避免被共享 `.ka-view.is-active` 覆盖。

4. 录入页一屏双入口工作台：
   - 修改 `static/index.html`
   - 旧结构：
     - `<main class="shell">`
     - 上下两个 `.panel`
   - 新结构：
     - `<main class="ingest-workbench">`
     - `.ingest-grid`
     - `.ingest-pane ingest-text-pane`
     - `.ingest-pane ingest-upload-pane`
   - 文本录入和文件上传在 MBP 14 级视口内同时可见。

5. 录入页 CSS 重构：
   - 修改 `static/style.css`
   - `.ingest-workbench` 使用 `height: 100vh` 与 `grid-template-rows: auto minmax(0, 1fr)`。
   - `.ingest-grid` 使用左右两列：`minmax(0, 1.15fr) minmax(300px, 0.85fr)`。
   - `.ingest-feedback` 限制 `max-height: 86px`，避免反馈内容撑破首屏。

6. Agent06 单行模型页脚：
   - 修改 `/Users/tristanzh/agent/web/server.mjs`
   - 新增 `.agent06-supplement-bar`，高度固定 34px。
   - 页脚文案：
     - `GPT-5.5 基座模型 · DeepSeek V4 Pro 中文语义分析 · bge-m3 + ChromaDB 本地向量检索`
   - 明确不显示 `codex-base` 这种内部路由名。

7. 测试更新：
   - 修改 `tests/test_project_files.py`
   - 修改 `/Users/tristanzh/agent/web/tests/agent06-service.test.mjs`
   - 修改 `/Users/tristanzh/agent/web/tests/platform-home-browser.test.mjs`
   - 覆盖录入页一屏工作台、Agent06 真实链接导航、单行页脚和主题桥新选择器。

## 已作出的关键决策

1. PKA 内层不再保留一级导航。
   - 原因：导航责任已经上移到 Agent06 外层，避免双层工作台。
   - 放弃方案：iframe 内隐藏旧 topbar 或代理层注入隐藏。

2. 录入页采用左右双入口，而不是压缩上下两张卡。
   - 原因：文本录入和文件上传都是一级入口，必须同屏可见。
   - 放弃方案：只减少 margin/padding 或 textarea 高度，这只能缓解，不能解决入口层级错误。

3. Agent06 页脚只保留一行状态线。
   - 原因：页脚职责是说明模型链路，不是配置面板；过高会继续挤压 iframe。
   - 放弃方案：照搬 Agent04 三列 chip 卡片。

4. 页脚展示真实用户可理解模型名。
   - 使用 `GPT-5.5`，不展示 `codex-base`。
   - 原因：`codex-base` 是内部路由名，不是用户需要理解的模型事实。

5. `?view=` 优先于本地持久化 iframe 路由。
   - 原因：用户显式访问书签或链接时，URL 应是最高优先级状态源。

## 未解决的风险/报错

1. `/Users/tristanzh/agent` 仓库仍有两处非本轮改动的脏文件：
   - `Passenger-Vehicle-Intel/workflows/foreign-jv-china-watch/data/latest_card_payload.json`
   - `Passenger-Vehicle-Intel/workflows/jlr-sales/data/raw/jlr_results_centre-JLR%20Volumes%20Q4%20FY26.xlsx`
   - 本轮提交不应包含它们，除非 TZ 明确要求。

2. PKA `settings.html` 仍使用旧 `.shell/.panel` 布局。
   - 这是可接受状态，因为当前问题集中在录入页和问答页。
   - 如果后续追求全站一致，可单独做设置页工作台化。

3. 页脚文案目前是静态写死。
   - 当前符合 TZ 对“当前配置就是 GPT-5.5”的要求。
   - 若未来模型路由改动，需要同步更新文案、测试和 `GLOBAL_MODEL_ROUTING_RECORD.md`。

4. `last_updated` 仍可能显示“未知”。
   - 原因是 PKA runtime 的更新时间可能是进程内状态。
   - 若需要稳定显示，需要从索引或数据库持久化读取。

## 下一步行动

1. 首先查看这几个文件确认当前布局契约：
   - `static/index.html`
   - `static/style.css`
   - `/Users/tristanzh/agent/web/server.mjs`
   - `/Users/tristanzh/agent/web/app/agent06.css`

2. 常用验证命令：
   - PKA：`python3 -m pytest -q`
   - Agent06 平台契约：`cd /Users/tristanzh/agent/web && node --test tests/agent06-service.test.mjs`
   - web 全量：`cd /Users/tristanzh/agent/web && npm test`
   - 语法：`cd /Users/tristanzh/agent/web && node --check server.mjs`

3. 浏览器验收口径：
   - 访问 `http://127.0.0.1:3000/agent06?view=ingest`
   - MBP 14 级视口下：
     - 外层页面不滚动
     - iframe 内不滚动
     - 文本录入和文件上传同时可见
     - 页脚高度约 34px
     - 页脚显示 `GPT-5.5 / DeepSeek V4 Pro / bge-m3 + ChromaDB`

4. 当前服务参考：
   - web 平台端口：3000
   - PKA 后端端口：8086
   - 当前入口：`http://127.0.0.1:3000/agent06`
