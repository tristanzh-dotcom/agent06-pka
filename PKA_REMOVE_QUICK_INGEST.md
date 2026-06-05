# 撤销快速录入条

**目标**：从问答页移除快速录入条（quick-ingest-form），消除问答页的认知冲突。

---

## 改动范围

### `static/ask.html`
删除 `<form id="quick-ingest-form" ...>` 整块（约 4 行）：
```html
<form id="quick-ingest-form" class="quick-ingest-bar">
  <input id="quick-ingest-input" type="text" placeholder="快速录入一条笔记">
  <button type="submit">录入</button>
  <span id="quick-ingest-feedback" class="quick-ingest-feedback"></span>
</form>
```

### `static/app.js`
删除 `setupAsk()` 中的快速录入监听器（约 14 行）：
```javascript
const quickIngestForm = document.getElementById("quick-ingest-form");
...
quickIngestForm?.addEventListener("submit", async (event) => { ... });
```

### `static/style.css`
删除 `.quick-ingest-bar`、`.quick-ingest-bar input`、`.quick-ingest-bar button`、`.quick-ingest-feedback` 四个规则块，以及 `@media` 中的对应规则。

### `tests/test_project_files.py`
查找并删除/调整任何引用 `quick-ingest` 或 `quick_ingest` 的测试断言。

---

## 验收
1. 问答页不再显示快速录入条
2. `python3 -m pytest -q` 全量通过
3. 录入功能仅保留在录入页（`/`），不受影响
