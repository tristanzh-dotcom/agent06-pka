# PKA 双模型分层生成改动规格

## 背景

当前生成层：单一 LLM（codex-base），无法区分"中文个人建议"和"英文对外汇报"两种输出场景。

目标：**DeepSeek v4 pro 做跨语言分析 + 中文直接输出，codex-base 仅在英文汇报时调用。**

## 一、架构变更

```
Before:  query → retrieval → codex-base → 回答（不分语言）

After:   query → retrieval → DeepSeek 分析
                ├─ lang=zh → DeepSeek 直接中文回答
                └─ lang=en → DeepSeek 分析结果 → codex-base 英文生成
```

## 二、配置变更

### `config.example.yaml` 新增

```yaml
deepseek:
  endpoint: ""
  api_key: ""
  model: "deepseek-v4-pro"
```

`generation` 节保持不变，但语义收窄为"英文输出模型"。

### `engine/config.py`

`DEFAULT_CONFIG` 新增 `deepseek` 条目，`sanitize_config` 新增对 `deepseek.api_key` 的脱敏。

## 三、生成引擎改动

### `engine/generator.py`

**新增函数：**

```python
async def analyze_with_deepseek(
    question: str,
    chunks: list[RetrievedChunk],
    endpoint: str,
    api_key: str,
    model_name: str,
) -> str:
    """
    输入：用户问题 + 检索到的中英混杂 chunks
    输出：结构化 JSON 字符串，包含：
      - key_facts: 关键事实提取（中英对照）
      - terminology: 关键术语的中英对照表
      - logic_chain: 逻辑关系梳理
    """
```

**Prompt 设计：**

```
你是一个跨语言个人知识库分析助手。用户给出了一个问题，以及从其个人资料库中检索到的相关材料。
材料中包含中文文档（个人简历、笔记、心得）和英文文档（外部报告、组织架构图）。

请完成以下分析：
1. 从材料中提取与问题相关的**关键事实**，分别标注原文语言
2. 列出关键**术语中英对照表**
3. 梳理材料之间的**逻辑关系**（因果、时间线、对比等）

输出 JSON 格式：
{
  "key_facts": [
    {"content": "...", "source": "文件名", "language": "zh|en"}
  ],
  "terminology": [
    {"zh": "组织架构", "en": "organizational structure"}
  ],
  "logic_chain": "这些材料之间的逻辑关系..."
}
```

**修改 `generate_answer()`：**

```python
async def generate_answer(
    question: str,
    chunks: list[RetrievedChunk],
    language: str,  # 新增: "zh" | "en"
    deepseek_endpoint: str,      # 新增
    deepseek_api_key: str,       # 新增
    deepseek_model: str,         # 新增
    generation_endpoint: str,    # 原有，重命名为英文输出
    generation_api_key: str,     # 原有
    generation_model: str,       # 原有
    deepseek_client=None,
    llm_client=None,
) -> AsyncGenerator[str, None]:
    """
    1. 调用 DeepSeek 做结构化分析
    2. 如果 language == "zh"：将 DS 分析结果转为中文建议（DS 自输出）
    3. 如果 language == "en"：将 DS 分析结果 + 原始 chunks 交给 codex-base 做英文汇报
    """
```

**关键逻辑：**

- **lang=zh 路径**：DeepSeek 分析后追加一个总结 prompt，"基于以上分析，给出中文个人建议"，SSE 流式返回，1 次 DS 调用
- **lang=en 路径**：DeepSeek 分析 JSON 作为 codex-base prompt 的上下文前缀，原始 chunks 作为后备参考，codex-base SSE 流式输出英文报告
- **chunks 为空**：不调用任何 LLM，SSE 返回"暂无相关内容"
- **DS 不可用且 lang=zh**：降级为"DeepSeek 模型未配置"提示
- **codex 不可用且 lang=en**：降级为"英文输出模型未配置"提示

## 四、API 变更

### `POST /api/query` 请求体扩展

```json
{
  "question": "组织架构调整建议",
  "language": "zh"   // 新增，默认 "zh"
}
```

### `server.py`

```python
class QueryRequest(BaseModel):
    question: str
    language: str = "zh"  # 新增
```

`/api/query` 路由中，从 `runtime.config` 读取 `deepseek` 和 `generation` 两组配置，传入 `generate_answer`。

## 五、前端变更

### `static/ask.html`

在输入框上方或旁边增加语言切换控件：

```html
<fieldset class="language-switch">
  <label><input type="radio" name="language" value="zh" checked> 中文建议</label>
  <label><input type="radio" name="language" value="en"> English Report</label>
</fieldset>
```

### `static/app.js`

- `setupAsk()` 中读取 `document.querySelector('input[name="language"]:checked').value`
- `fetch("api/query", ...)` 的 body 中增加 `language` 字段
- `askState` 中增加 `language` 字段
- SSE token 正常流式渲染

### `static/style.css`

```css
.language-switch {
  display: flex;
  gap: 16px;
  margin-bottom: 12px;
  border: 0;
  padding: 0;
}
.language-switch label {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}
```

## 六、测试变更

### `tests/test_generator_api.py`

新增：

- `test_query_with_language_zh_uses_deepseek_path`：mock DeepSeek client，验证 lang=zh 时不调用 codex
- `test_query_with_language_en_uses_both_models`：mock 双 client，验证 lang=en 时先 DS 后 codex
- `test_query_without_deepseek_returns_config_error_for_zh`：DS 未配置且 lang=zh → 返回配置提示
- `test_query_without_generation_returns_config_error_for_en`：codex 未配置且 lang=en → 返回配置提示

### `tests/test_models_config.py`

- `test_deepseek_config_is_sanitized`：验证 deepseek.api_key 脱敏
- `test_config_supports_deepseek_section`：验证 deepseek 段正确读写

### `tests/test_project_files.py`

- `test_frontend_uses_relative_paths` 保持不变
- `test_settings_page_exposes_both_model_sections`：验证配置页包含 deepseek 和 generation 两组模型

## 七、执行顺序

```
1. 配置层: config.yaml schema + sanitize_config 更新
2. 生成层: generator.py DeepSeek 分析 + 双路径分发
3. API 层: server.py QueryRequest 新增 language 字段
4. 前端层: ask.html 语言切换 + app.js 传递 language
5. 测试层: 新增双模型路径测试 → 回归全量测试
```
