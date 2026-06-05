# PKA 问答页工作台化 + 导航硬约束

## 目标

1. 导航按钮永不消失（硬约束）
2. 问答页从"卡片嵌套卡片"改为"三段式工作台画布"（容器扁平化）
3. 空状态从居中大框改为输入框上方的轻量 chip

---

## 一、导航硬约束 — `app/agent06.css`

改动：`.agent06-info-status-bar` 加 `min-width: 0` 保护移除，nav 按钮不可被挤压消失。窄屏（<720px）时导航换行到标题下方一整行。

```css
.agent06-info-status-bar {
  display: flex;
  align-items: flex-start;         /* 改为 start，允许换行后对齐 */
  justify-content: space-between;
  gap: 12px;
  padding: 16px 20px;
  flex-wrap: wrap;                 /* 新增：窄屏时导航换行 */
}

.agent06-workflow-nav {
  display: inline-flex;
  flex-shrink: 0;                  /* 新增：不被挤压 */
  align-items: center;
  gap: 4px;
  padding: 4px;
  border: 1px solid var(--ka-border);
  border-radius: var(--ka-radius-control);
  background: var(--ka-bg-stage);
}

@media (max-width: 720px) {
  .agent06-workflow-nav {
    width: 100%;                   /* 窄屏时占满整行 */
  }
  .agent06-workflow-nav button {
    flex: 1;
  }
}
```

删除旧 `@media (max-width: 980px)` 中的 `align-items: stretch` 和 `flex-direction: column` 规则，统一使用 flex-wrap + 窄屏整行策略。

---

## 二、问答页容器扁平化 — `static/ask.html`

### 当前（嵌套）

```html
<main class="shell">
  <section class="panel ask-panel">
    <h1>...</h1>
    <div id="export-bar">...</div>
    <div id="conversation" class="conversation">...</div>
    <form class="querybar">...</form>
  </section>
</main>
```

### 改为（扁平工作台）

```html
<main class="ask-workbench">
  <header class="ask-header">
    <h1>知识库问答</h1>
    <div class="exportbar" id="export-bar" style="display:none">
      <button type="button" id="export-word">导出 Word</button>
      <button type="button" id="export-ppt">导出 PPT</button>
    </div>
  </header>
  <div id="conversation" class="ask-conversation">
    <div id="empty-state" class="empty-chips">
      <button type="button" class="empty-chip">我之前关于组织架构的看法是什么？</button>
      <button type="button" class="empty-chip">总结一下我最近录入的所有内容</button>
      <button type="button" class="empty-chip">基于我的笔记，给出当前的技术选型建议</button>
    </div>
  </div>
  <form id="query-form" class="ask-input-bar">
    <fieldset class="language-switch" id="language-switch">
      <label><input type="radio" name="language" value="zh" checked> 中文建议</label>
      <label><input type="radio" name="language" value="en"> English Report</label>
    </fieldset>
    <input id="question-input" type="text" placeholder="基于历史内容提问">
    <button type="submit">发送</button>
  </form>
</main>
```

---

## 三、问答页 CSS 重写 — `static/style.css`

### 删除

删除所有 `.shell`、`.panel`、`.ask-panel`、`.conversation`、`.querybar`、`.empty-state`、`.sources`、`.sources-flat`、`.sources-title`、`.source-item`、`.message`、`.message.user` 规则。

### 新增

```css
/* ── 工作台容器 ── */
.ask-workbench {
  display: flex;
  flex-direction: column;
  height: 100vh;
  padding: 20px 24px;
  box-sizing: border-box;
  background: var(--bg);
}

/* ── 顶部：标题 + 导出 ── */
.ask-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
  margin-bottom: 14px;
}
.ask-header h1 {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
}

/* ── 导出按钮区 ── */
.exportbar {
  display: flex;
  gap: 8px;
}

/* ── 对话流 ── */
.ask-conversation {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* ── 空状态 chip ── */
.empty-chips {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 20px 0;
}
.empty-chip {
  display: block;
  width: 100%;
  padding: 10px 14px;
  border: 1px solid var(--line);
  border-radius: var(--radius-control);
  background: var(--panel);
  color: var(--muted);
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  min-height: auto;
}
.empty-chip:hover {
  color: var(--ink);
  border-color: var(--accent);
}

/* ── 消息气泡 ── */
.ask-message {
  max-width: 72ch;
  padding: 10px 14px;
  border-radius: var(--radius-card);
  white-space: pre-wrap;
  font-size: 14px;
  line-height: 1.6;
}
.ask-message.user {
  align-self: flex-end;
  background: var(--message-user-bg);
}
.ask-message.assistant {
  align-self: flex-start;
  background: transparent;
}

/* ── 来源 chips ── */
.ask-sources {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  font-size: 12px;
  color: var(--muted);
}
.ask-sources-title {
  font-weight: 700;
  color: var(--ink);
}
.ask-source-chip {
  display: inline-flex;
  align-items: center;
  max-width: 240px;
  padding: 3px 8px;
  border: 1px solid var(--line);
  border-radius: var(--radius-control);
  background: var(--panel);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ask-source-chip a {
  color: var(--accent);
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ── 底部输入栏 ── */
.ask-input-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
  margin-top: 14px;
}
.ask-input-bar input[type="text"] {
  flex: 1;
}
.ask-input-bar button {
  flex-shrink: 0;
}

/* ── 语言切换 ── */
.language-switch {
  display: flex;
  gap: 12px;
  flex-shrink: 0;
  margin: 0;
  border: 0;
  padding: 0;
}
.language-switch label {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--muted);
  cursor: pointer;
  white-space: nowrap;
  font-size: 13px;
}
.language-switch input {
  width: auto;
}
```

`100vh` 不再需要 `calc()`，因为工作台容器直接就是 `height: 100vh`，flex 自动分配空间。

---

## 四、JavaScript 适配 — `static/app.js`

### 改动 1：消息追加用新 class

```javascript
function appendMessage(text, role) {
  const box = document.getElementById("conversation");  // 改为 ask-conversation
  const node = document.createElement("div");
  node.className = `ask-message ${role}`;               // 改为 ask-message
  ...
}
```

### 改动 2：来源渲染用新 class

```javascript
// sources → ask-sources
sources.className = "ask-sources";
// title → ask-sources-title
title.className = "ask-sources-title";
// item → ask-source-chip
item.className = "ask-source-chip";
```

### 改动 3：空状态 chip click-to-fill

```javascript
// setupAsk() 中新增
const chips = document.querySelectorAll(".empty-chip");
chips.forEach(chip => {
  chip.addEventListener("click", () => {
    document.getElementById("question-input").value = chip.textContent;
    document.getElementById("query-form").requestSubmit();
  });
});
```

### 改动 4：空状态清理

首次 token 时，清空整个 `.empty-chips` 容器：

```javascript
if (payload.type === "token") {
  const empty = document.getElementById("empty-state");
  if (empty) empty.remove();  // 移除整个 empty-chips 容器
  ...
}
```

---

## 五、录入页和设置页 — 保持不变

录入页（`index.html`）和设置页（`settings.html`）的 CSS 类名（`.shell`、`.panel`、`.stack`、`.feedback` 等）**不入 question 页重构范围**。它们在独立 iframe 页面中仅自己使用，不需要扁平化。它们移除的仅是 `<nav class="topbar">`。

---

## 六、测试更新

### `tests/test_project_files.py`

- 删除断言 `.shell`、`.panel`、`.conversation`、`.message` 的测试
- 新增断言：
  - `.ask-workbench` 存在
  - `.ask-conversation` 存在
  - `.ask-message` 存在
  - `.ask-sources` 存在
  - `.ask-source-chip` 存在
  - `.ask-input-bar` 存在
  - `.empty-chip` 存在
  - `ask-message.user` / `ask-message.assistant` 存在
  - `height: 100vh`（无 calc）
- 保留相对路径和缓存版本测试

### `tests/agent06-service.test.mjs`

- 新增断言：
  - `flex-shrink: 0` 在 `.agent06-workflow-nav` 规则中
  - `flex-wrap: wrap` 在 `.agent06-info-status-bar` 中

---

## 七、验收

1. 问答页打开，标题 + 对话流 + 输入栏三段式垂直分布
2. 无边框中框——对话区内无独立边框、面板无阴影、无圆角卡片包裹
3. 空状态为三个 chip，点击自动填入输入框并提交
4. 输入栏始终固定在底部
5. 导航按钮不消失（重启 3000 后）
6. `python3 -m pytest -q` 全量通过
7. `npm test` web 平台全量通过
