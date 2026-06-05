# PKA 问答页一屏适配 — P0 修正任务

## 目标

MacBook Pro 14" 浏览器打开 `/agent06/ask`，输入框必须在首屏可见，不需要滚动。

## 修改文件

`static/ask.html`、`static/app.js`、`static/style.css`

---

## 1. 对话区：从固定高度改为弹性伸缩

### `style.css`

**删除**：
```css
.conversation {
  min-height: 420px;  /* 删除这行 */
}
```

**改为**：
```css
.conversation {
  flex: 1;
  min-height: 0;             /* 允许 flex item 收缩到 0 */
  max-height: calc(100vh - 320px);  /* 防止对话撑出屏幕 */
  overflow-y: auto;
  display: grid;
  align-content: start;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fbf8f0;
}
```

### `style.css` — `.ask-panel` 改为 flex 列

```css
.ask-panel {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 160px);  /* 面板占满可用高度 */
}
```

---

## 2. 语言切换 + 输入框合并为单行

### `style.css`

```css
.querybar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 12px;
  flex-shrink: 0;             /* 不参与收缩，始终可见 */
}

.querybar input[type="text"] {
  flex: 1;
}

.querybar button {
  flex-shrink: 0;
}

.language-switch {
  display: flex;
  gap: 12px;
  flex-shrink: 0;
}

.language-switch label {
  display: flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
  font-size: 13px;
  cursor: pointer;
}
```

### `ask.html`

将语言切换从独立行移入 `querybar`，放在输入框前面：

```html
<form id="query-form" class="querybar">
  <fieldset class="language-switch" id="language-switch">
    <label><input type="radio" name="language" value="zh" checked> 中文建议</label>
    <label><input type="radio" name="language" value="en"> English Report</label>
  </fieldset>
  <input id="question-input" type="text" placeholder="基于历史内容提问">
  <button type="submit">发送</button>
</form>
```

去掉原来独立放置语言切换的代码（如果有的话）。

---

## 3. 导出按钮延迟到回答完成后显示

### `ask.html`

导出按钮初始隐藏：

```html
<div class="exportbar" id="export-bar" style="display:none">
  <button type="button" id="export-word">导出 Word</button>
  <button type="button" id="export-ppt">导出 PPT</button>
</div>
```

### `app.js`

在 `setupAsk()` 的 SSE 循环中，`type === "done"` 事件后显示导出按钮：

```javascript
if (payload.type === "done") {
  const exportBar = document.getElementById("export-bar");
  if (exportBar) exportBar.style.display = "flex";
}
```

在下次提问时再次隐藏：

```javascript
// 在 form submit 事件处理中，fetch 调用之前：
const exportBar = document.getElementById("export-bar");
if (exportBar) exportBar.style.display = "none";
```

---

## 4. 空状态：示例问题引导

### `ask.html`

对话区内初始显示引导文案：

```html
<div id="conversation" class="conversation">
  <div id="empty-state" style="color: var(--muted); text-align: center; padding: 36px 12px; line-height: 2;">
    <div style="font-size: 15px;">💡 试试问我：</div>
    <div>· "我之前关于组织架构的看法是什么？"</div>
    <div>· "总结一下我最近录入的所有内容"</div>
    <div>· "基于我的笔记，给出当前的技术选型建议"</div>
  </div>
</div>
```

### `app.js`

首次收到 SSE token 时（即回答开始），自动删除空状态：

```javascript
if (payload.type === "token") {
  const empty = document.getElementById("empty-state");
  if (empty) empty.remove();
  answer.textContent += payload.content;
  askState.answer += payload.content;
}
```

---

## 5. 响应式清理

### `style.css`

删除旧的 `.querybar` grid 规则（已改为 flex）：

```css
/* 删除 */
.querybar {
  grid-template-columns: 1fr auto;
}

/* 删除 @media 中针对 .querybar 的 grid 重设 */
```

---

## 验收标准

1. MBP 14" 浏览器打开 `/ask`，**输入框在首屏可见**，无需滚动
2. 空状态显示 3 条示例问题，提问后消失
3. 导出按钮在回答流式输出完成后才出现，初始不占位
4. 语言切换 + 输入框 + 发送按钮在同一行
5. `python3 -m pytest -q` 全量回归通过
