import json
from typing import Any, AsyncGenerator, Iterable, List, Optional

import httpx

from engine.models import RetrievedChunk


def build_prompt(question: str, chunks: List[RetrievedChunk]) -> str:
    references = []
    for index, chunk in enumerate(chunks, start=1):
        references.append(f"--- chunk_{index} (来源: {chunk.source_name})\n{chunk.text}")
    reference_text = "\n".join(references)
    return f"""你是一个个人知识库助手。用户积累了大量个人文档、笔记、面试复盘、项目报告等内容。
现在用户基于这些内容向你提问。你需要：

1. 仔细阅读所有 [参考内容] 片段
2. 综合分析这些片段中的信息
3. 如果信息充分，给出专业、具体的建议和回答
4. 如果某些方面的信息不足，请明确指出"当前知识库中缺少关于 XX 的信息"
5. 在回答末尾列出本次引用的来源文件

[参考内容]
{reference_text}

[用户问题]
{question}

请回答：
"""


def build_deepseek_analysis_prompt(question: str, chunks: List[RetrievedChunk], include_chinese_advice: bool = False) -> str:
    references = []
    for index, chunk in enumerate(chunks, start=1):
        references.append(
            f"--- chunk_{index}\n"
            f"source: {chunk.source_name}#{chunk.chunk_index}\n"
            f"text: {chunk.text}"
        )
    if include_chinese_advice:
        return f"""你是一个个人知识库中文问答助手。用户给出了一个问题，以及从其个人资料库中检索到的相关材料。
请直接给用户一段自然、可读的中文个人建议，不要输出 JSON、代码块、字段名或调试结构。

回答要求：
1. 先给出核心结论
2. 再列出关键依据，依据必须来自参考内容
3. 给出具体、可执行的中文个人建议
4. 在回答末尾列出来源，格式为“来源：文件名#段落号”
5. 如果资料不足，明确说明当前知识库缺少哪些信息

[参考内容]
{chr(10).join(references)}

[用户问题]
{question}

请用中文回答：
"""
    return f"""你是一个跨语言个人知识库分析助手。用户给出了一个问题，以及从其个人资料库中检索到的相关材料。
材料中包含中文文档（个人简历、笔记、心得）和英文文档（外部报告、组织架构图）。

请完成以下分析：
1. 从材料中提取与问题相关的关键事实，分别标注原文语言
2. 列出关键术语中英对照表
3. 梳理材料之间的逻辑关系（因果、时间线、对比等）

输出 JSON 格式：
{{
  "key_facts": [
    {{"content": "...", "source": "文件名", "language": "zh|en"}}
  ],
  "terminology": [
    {{"zh": "组织架构", "en": "organizational structure"}}
  ],
  "logic_chain": "这些材料之间的逻辑关系..."
}}

[参考内容]
{chr(10).join(references)}

[用户问题]
{question}
"""


def build_english_report_prompt(question: str, analysis: str, chunks: List[RetrievedChunk]) -> str:
    references = []
    for index, chunk in enumerate(chunks, start=1):
        references.append(f"--- chunk_{index} ({chunk.source_name}#{chunk.chunk_index})\n{chunk.text}")
    return f"""You are writing an English report based on a personal knowledge base.

DeepSeek analysis:
{analysis}

Original references:
{chr(10).join(references)}

User question:
{question}

Write a concise English report. Use the DeepSeek analysis as the primary structure, keep claims grounded in the references, and mention source files where useful.
"""


class RemoteLLMClient:
    def __init__(self, endpoint: str, api_key: str, model_name: str):
        self.endpoint = endpoint
        self.api_key = api_key
        self.model_name = model_name

    async def stream(self, prompt: str) -> AsyncGenerator[str, None]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream("POST", self.endpoint, headers=headers, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line.removeprefix("data: ").strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = event.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content


async def analyze_with_deepseek(
    question: str,
    chunks: List[RetrievedChunk],
    endpoint: str,
    api_key: str,
    model_name: str,
    client: Optional[Any] = None,
    include_chinese_advice: bool = False,
) -> str:
    deepseek = client or RemoteLLMClient(endpoint, api_key, model_name)
    prompt = build_deepseek_analysis_prompt(question, chunks, include_chinese_advice=include_chinese_advice)
    parts = []
    async for token in deepseek.stream(prompt):
        parts.append(token)
    return "".join(parts)


async def generate_answer(
    question: str,
    chunks: List[RetrievedChunk],
    language: str = "zh",
    deepseek_endpoint: str = "",
    deepseek_api_key: str = "",
    deepseek_model: str = "deepseek-v4-pro",
    generation_endpoint: str = "",
    generation_api_key: str = "",
    generation_model: str = "codex-base",
    deepseek_client: Optional[Any] = None,
    llm_client: Optional[Any] = None,
) -> AsyncGenerator[str, None]:
    if not chunks:
        yield _sse({"type": "token", "content": "暂无相关内容。"})
        yield _sse({"type": "done"})
        return

    normalized_language = language if language in {"zh", "en"} else "zh"
    if not _is_deepseek_available(deepseek_endpoint, deepseek_client):
        yield _sse({"type": "token", "content": "DeepSeek 模型未配置。"})
        yield _sse({"type": "sources", "sources": _sources(chunks)})
        yield _sse({"type": "done"})
        return

    if normalized_language == "zh":
        try:
            analysis = await analyze_with_deepseek(
                question,
                chunks,
                deepseek_endpoint,
                deepseek_api_key,
                deepseek_model,
                client=deepseek_client,
                include_chinese_advice=True,
            )
            yield _sse({"type": "token", "content": _format_chinese_answer(analysis, chunks)})
        except Exception as exc:
            yield _sse({"type": "error", "content": f"DeepSeek 调用失败: {exc}"})
        yield _sse({"type": "sources", "sources": _sources(chunks)})
        yield _sse({"type": "done"})
        return

    try:
        analysis = await analyze_with_deepseek(
            question,
            chunks,
            deepseek_endpoint,
            deepseek_api_key,
            deepseek_model,
            client=deepseek_client,
        )
    except Exception as exc:
        yield _sse({"type": "error", "content": f"DeepSeek 调用失败: {exc}"})
        yield _sse({"type": "sources", "sources": _sources(chunks)})
        yield _sse({"type": "done"})
        return

    if not generation_model and llm_client is None:
        yield _sse({"type": "token", "content": "英文输出模型未配置。"})
        yield _sse({"type": "sources", "sources": _sources(chunks)})
        yield _sse({"type": "done"})
        return

    if not generation_endpoint and llm_client is None:
        if generation_model == "codex-base":
            for token in _generate_codex_base_english_report(question, analysis, chunks):
                yield _sse({"type": "token", "content": token})
            yield _sse({"type": "sources", "sources": _sources(chunks)})
            yield _sse({"type": "done"})
            return
        yield _sse({"type": "token", "content": "英文输出模型未配置。"})
        yield _sse({"type": "sources", "sources": _sources(chunks)})
        yield _sse({"type": "done"})
        return

    client = llm_client or RemoteLLMClient(generation_endpoint, generation_api_key, generation_model)
    prompt = build_english_report_prompt(question, analysis, chunks)
    try:
        async for token in client.stream(prompt):
            yield _sse({"type": "token", "content": token})
    except Exception as exc:
        yield _sse({"type": "error", "content": f"LLM 调用失败: {exc}"})
    yield _sse({"type": "sources", "sources": _sources(chunks)})
    yield _sse({"type": "done"})


def _sources(chunks: Iterable[RetrievedChunk]) -> List[dict]:
    return [
        {
            "source_name": chunk.source_name,
            "chunk_index": chunk.chunk_index,
            "relevance": chunk.score,
            "chunk_id": chunk.chunk_id,
            "raw_file_path": chunk.raw_file_path,
        }
        for chunk in chunks
    ]


def _generate_codex_base_fallback(question: str, chunks: List[RetrievedChunk]) -> Iterable[str]:
    lines = [
        "基于当前知识库检索结果，先给出可执行的初步回答。\n\n",
        f"问题：{question}\n\n",
        "相关内容：\n",
    ]
    for index, chunk in enumerate(chunks[:5], start=1):
        excerpt = " ".join(chunk.text.split())
        if len(excerpt) > 220:
            excerpt = excerpt[:220] + "..."
        lines.append(f"{index}. {excerpt}（来源：{chunk.source_name}#{chunk.chunk_index}）\n")
    lines.append("\n建议：优先围绕以上来源中的事实继续追问或补充材料；如果需要更强的综合推理，可在配置页接入外部生成模型。\n")
    return lines


def _generate_codex_base_english_report(question: str, analysis: str, chunks: List[RetrievedChunk]) -> Iterable[str]:
    lines = [
        "English report draft based on DeepSeek analysis.\n\n",
        f"Question: {question}\n\n",
        "DeepSeek analysis:\n",
        analysis,
        "\n\nReference excerpts:\n",
    ]
    for index, chunk in enumerate(chunks[:5], start=1):
        excerpt = " ".join(chunk.text.split())
        if len(excerpt) > 220:
            excerpt = excerpt[:220] + "..."
        lines.append(f"{index}. {excerpt} (Source: {chunk.source_name}#{chunk.chunk_index})\n")
    lines.append("\nUse these points as a grounded first draft for an English report.\n")
    return lines


def _format_chinese_answer(raw_answer: str, chunks: List[RetrievedChunk]) -> str:
    answer = raw_answer.strip()
    parsed = _parse_json_object(answer)
    if not isinstance(parsed, dict):
        return answer

    facts = parsed.get("key_facts") if isinstance(parsed.get("key_facts"), list) else []
    terminology = parsed.get("terminology") if isinstance(parsed.get("terminology"), list) else []
    logic_chain = parsed.get("logic_chain") if isinstance(parsed.get("logic_chain"), str) else ""

    if not facts and not logic_chain:
        return answer

    lines = ["核心结论："]
    if logic_chain:
        lines.append(logic_chain)
    else:
        first_fact = facts[0] if isinstance(facts[0], dict) else {}
        lines.append(str(first_fact.get("content", "")).strip())

    if facts:
        lines.extend(["", "关键依据："])
        for index, fact in enumerate(facts, start=1):
            if not isinstance(fact, dict):
                continue
            content = str(fact.get("content", "")).strip()
            source = str(fact.get("source", "")).strip()
            if content and source:
                lines.append(f"{index}. {content}（来源：{source}）")
            elif content:
                lines.append(f"{index}. {content}")

    if terminology:
        term_lines = []
        for term in terminology:
            if not isinstance(term, dict):
                continue
            zh = str(term.get("zh", "")).strip()
            en = str(term.get("en", "")).strip()
            if zh and en:
                term_lines.append(f"- {zh}：{en}")
        if term_lines:
            lines.extend(["", "相关术语：", *term_lines])

    sources = []
    for fact in facts:
        if isinstance(fact, dict):
            source = str(fact.get("source", "")).strip()
            if source and source not in sources:
                sources.append(source)
    if not sources:
        for chunk in chunks:
            source = f"{chunk.source_name}#{chunk.chunk_index}"
            if source not in sources:
                sources.append(source)
    if sources:
        lines.extend(["", "来源：", *[f"- {source}" for source in sources]])

    return "\n".join(lines).strip()


def _parse_json_object(text: str) -> Optional[dict]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _is_deepseek_available(endpoint: str, client: Optional[Any]) -> bool:
    return bool(endpoint or client is not None)


def _sse(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
