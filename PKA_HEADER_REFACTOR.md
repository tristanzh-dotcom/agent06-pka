# Agent06 抬头栏重构

## 目标

抬头栏从"部署诊断信息"改为"知识库状态摘要"，删除所有工程标签和导航按钮。

---

## 1. 平台壳抬头栏 — `server.mjs`

### 当前（诊断风格）

```html
后端通道: http://127.0.0.1:8086
前端挂载: /agent06/
项目名称 / 本地知识资产
[录入资料] [开始问答]
```

### 改为（状态摘要）

```html
个人知识库
{N} 个知识片段 · {M} 份资料 · 最近更新 {last_updated}
DeepSeek 已连接 · 本地向量库已启用
```

无按钮。无 URL。无端口号。

---

## 2. 状态 API 扩展 — `server.mjs`

### `/api/agent06/status` 输出

```json
{
  "id": "agent06",
  "name": "个人知识库",
  "deployable": false,
  "healthy": true,
  "source_url": "/agent06/",
  "apiPrefix": "/agent06/api",
  "staticRoute": "/agent06/",
  "total_chunks": 175,
  "source_count": 7,
  "last_updated": "2026-06-05 14:25",
  "deepseek_connected": true,
  "embedding_available": true
}
```

新增字段说明：

| 字段 | 来源 | 获取方式 |
|------|------|---------|
| `total_chunks` | PKA 后端 `/api/stats` → `total_chunks` | HTTP GET 到 PKA backend |
| `source_count` | PKA 后端 `/api/stats` → `indexed_files` | 同上 |
| `last_updated` | PKA 后端 `/api/stats` → `last_updated` | 同上 |
| `deepseek_connected` | PKA 后端 `/api/config` → `deepseek.endpoint` 非空 | 同上 |
| `embedding_available` | 本地 `ollama list` 包含 `bge-m3` 或配置 `embedding.model` 已设置 | 本地检测 |

`agent06Status({ backendBaseUrl })` 函数内部 fetch PKA 后端 stats 和 config，fallback 为 `total_chunks: 0, source_count: 0` 当后端不可达。

---

## 3. 抬头栏模板 — 无后端时降级

当 PKA 后端不可达时：

```html
个人知识库
知识库后端未连接
```

不显示 0/0 的误导性数字，不显示假连接状态。

---

## 4. CSS — `app/agent06.css`

删除与旧抬头栏相关的过宽布局规则。新抬头栏紧凑：

```css
.agent06-info-status-bar {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 16px 20px;
}

.agent06-info-project-block h1 {
  font-size: 20px;
  margin: 0;
}

.agent06-info-stat-line {
  font-size: 13px;
  color: var(--muted);
}

.agent06-info-status-line {
  font-size: 12px;
  color: var(--muted);
  display: flex;
  gap: 12px;
}

.agent06-info-status-line .status-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 4px;
}

.agent06-info-status-line .status-dot.on  { background: var(--accent); }
.agent06-info-status-line .status-dot.off { background: var(--accent-2); }
```

---

## 5. 验收

1. 打开 `http://127.0.0.1:3000/agent06`，抬头栏显示知识库片段数/资料数/更新时间
2. DeepSeek 和向量库连接状态正确反映实际配置
3. 无任何 URL、端口号、工程标签、导航按钮
4. PKA 后端停止后抬头栏显示"知识库后端未连接"，不显示 0/0
5. `python3 -m pytest -q` 全量通过（PKA 侧）
6. web 平台 `npm test` 全量通过
