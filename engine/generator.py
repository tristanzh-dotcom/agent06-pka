import json
import re
from typing import Any, AsyncGenerator, Iterable, List, Optional

import httpx

from engine.models import RetrievedChunk


NO_ANSWER_CONSTRAINT = """如果参考内容中没有任何与该问题相关的信息，请只输出：
"当前知识库缺少相关信息，无法回答该问题。建议补充相关资料后重新提问。"
不要给出外部知识、推测或通用建议。"""


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


def build_deepseek_analysis_prompt(
    question: str,
    chunks: List[RetrievedChunk],
    include_chinese_advice: bool = False,
    report_language: str = "zh",
) -> str:
    references = []
    for index, chunk in enumerate(chunks, start=1):
        context_label = "generated secondary context" if chunk.source_type == "generated_asset" else "primary source context"
        references.append(
            f"--- chunk_{index}\n"
            f"source: {chunk.source_name}#{chunk.chunk_index}\n"
            f"context: {context_label}\n"
            f"text: {chunk.text}"
        )
    generated_instruction = _generated_knowledge_instruction(chunks)
    org_chart_instruction = _org_chart_grounding_instruction(chunks)
    if include_chinese_advice:
        return f"""你是一个个人知识库中文问答助手。用户给出了一个问题，以及从其个人资料库中检索到的相关材料。
请直接给用户一段自然、可读的中文个人建议，不要输出 JSON、代码块、字段名或调试结构。

回答要求：
1. 先给出核心结论
2. 再列出关键依据，依据必须来自参考内容
3. 给出具体、可执行的中文个人建议
4. 在回答末尾列出来源，格式为“来源：文件名#段落号”
5. 如果资料不足，明确说明当前知识库缺少哪些信息
{NO_ANSWER_CONSTRAINT}
{org_chart_instruction}
{generated_instruction}

[参考内容]
{chr(10).join(references)}

[用户问题]
{question}

请用中文回答：
"""
    english_report_instruction = ""
    if report_language == "en":
        english_report_instruction = """
English Report mode:
- Write all report-facing JSON values in English.
- Translate Chinese source meaning into fluent English for key_facts.content and logic_chain.
- Keep language as the original source language marker: "zh" for Chinese source text and "en" for English source text.
- Keep terminology.zh in Chinese when relevant, but terminology.en must be natural English.
- Do not output Chinese prose in key_facts.content or logic_chain unless it is a proper noun, title, or unavoidable source term.
"""
    return f"""你是一个跨语言个人知识库分析助手。用户给出了一个问题，以及从其个人资料库中检索到的相关材料。
材料中包含中文文档（个人简历、笔记、心得）和英文文档（外部报告、组织架构图）。
{english_report_instruction}

请完成以下分析：
1. 从材料中提取与问题相关的关键事实，分别标注原文语言
2. 列出关键术语中英对照表
3. 梳理材料之间的逻辑关系（因果、时间线、对比等）
{NO_ANSWER_CONSTRAINT}
{org_chart_instruction}
{generated_instruction}

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


def _org_chart_grounding_instruction(chunks: List[RetrievedChunk]) -> str:
    if not any(chunk.source_type == "org_chart" or chunk.text.startswith("[ORG_CHART") for chunk in chunks):
        return ""
    return """
组织架构图关系题额外规则：
- 必须只依据同一个结构链中的明示父子关系、"is structurally under" 关系或同一 Page/Context Root 内的结构缩进回答。
- 不要把不同 Page、不同 Context Root 或不同分支的人员关系拼接成新的汇报链。
- 如果多个 org chart 片段看起来都相关，优先使用包含问题中明确人名/团队名的片段；其它片段只能作为补充背景，不能创造跨分支结论。
- 如果参考内容只显示名字拆行，可以合并为同一个人名，但必须说明这是基于同一结构链的合并；例如 "Dave" 下一层是 "Ross"，应合并为 Dave Ross；例如 "Ireland" 下是 "Paul" 再下一层 "Girr"，应合并为 Paul Girr。
""".strip()


def _generated_knowledge_instruction(chunks: List[RetrievedChunk]) -> str:
    if not any(chunk.source_type == "generated_asset" for chunk in chunks):
        return ""
    return """
Generated knowledge chunks are previous model-generated syntheses that the user saved to the knowledge base.
Treat them as secondary context, not primary evidence. Prefer primary source chunks for factual claims and do not promote generated wording into an unsupported fact.
""".strip()


def build_english_report_prompt(question: str, analysis: str, chunks: List[RetrievedChunk]) -> str:
    references = []
    for index, chunk in enumerate(chunks, start=1):
        context_label = "generated secondary context" if chunk.source_type == "generated_asset" else "primary source context"
        references.append(
            f"--- chunk_{index} ({chunk.source_name}#{chunk.chunk_index})\n"
            f"context: {context_label}\n"
            f"{chunk.text}"
        )
    generated_instruction = _generated_knowledge_instruction(chunks)
    return f"""You are writing an English report based on a personal knowledge base.

DeepSeek analysis:
{analysis}

Original references:
{chr(10).join(references)}

{generated_instruction}

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
    report_language: str = "zh",
) -> str:
    deepseek = client or RemoteLLMClient(endpoint, api_key, model_name)
    prompt = build_deepseek_analysis_prompt(
        question,
        chunks,
        include_chinese_advice=include_chinese_advice,
        report_language=report_language,
    )
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
    debug_payload: Optional[dict] = None,
    evidence_payload: Optional[dict] = None,
) -> AsyncGenerator[str, None]:
    if not chunks:
        yield _sse({"type": "token", "content": "暂无相关内容。"})
        yield _sse(_sources_event(chunks, debug_payload=debug_payload, evidence_payload=evidence_payload))
        yield _sse({"type": "done"})
        return

    normalized_language = language if language in {"zh", "en"} else "zh"
    if _is_generated_only_retrieval(chunks):
        message = (
            "仅检索到历史生成摘要，缺少可用于事实结论的原始资料。"
            if normalized_language == "zh"
            else "Only historical generated summaries were found; primary source material is missing for factual conclusions."
        )
        yield _sse({"type": "token", "content": message})
        yield _sse(
            _sources_event(
                chunks,
                debug_payload=debug_payload,
                evidence_payload=evidence_payload,
                source_status="generated_only",
            )
        )
        yield _sse({"type": "done"})
        return

    if not _is_deepseek_available(deepseek_endpoint, deepseek_client):
        yield _sse({"type": "token", "content": "DeepSeek 模型未配置。"})
        yield _sse(_sources_event(chunks, debug_payload=debug_payload, evidence_payload=evidence_payload))
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
            answer = _format_chinese_answer(analysis, chunks)
            yield _sse({"type": "token", "content": answer})
        except Exception as exc:
            yield _sse({"type": "error", "content": f"DeepSeek 调用失败: {exc}"})
            answer = ""
        yield _sse(_sources_event(chunks, answer, debug_payload=debug_payload, evidence_payload=evidence_payload))
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
            report_language="en",
        )
    except Exception as exc:
        yield _sse({"type": "error", "content": f"DeepSeek 调用失败: {exc}"})
        yield _sse(_sources_event(chunks, debug_payload=debug_payload, evidence_payload=evidence_payload))
        yield _sse({"type": "done"})
        return

    if not generation_model and llm_client is None:
        yield _sse({"type": "token", "content": "英文输出模型未配置。"})
        yield _sse(_sources_event(chunks, debug_payload=debug_payload, evidence_payload=evidence_payload))
        yield _sse({"type": "done"})
        return

    if not generation_endpoint and llm_client is None:
        if generation_model == "codex-base":
            for token in _generate_codex_base_english_report(question, analysis, chunks):
                yield _sse({"type": "token", "content": token})
            yield _sse(_sources_event(chunks, analysis, debug_payload=debug_payload, evidence_payload=evidence_payload))
            yield _sse({"type": "done"})
            return
        yield _sse({"type": "token", "content": "英文输出模型未配置。"})
        yield _sse(_sources_event(chunks, debug_payload=debug_payload, evidence_payload=evidence_payload))
        yield _sse({"type": "done"})
        return

    client = llm_client or RemoteLLMClient(generation_endpoint, generation_api_key, generation_model)
    prompt = build_english_report_prompt(question, analysis, chunks)
    try:
        async for token in client.stream(prompt):
            yield _sse({"type": "token", "content": token})
    except Exception as exc:
        yield _sse({"type": "error", "content": f"LLM 调用失败: {exc}"})
    yield _sse(_sources_event(chunks, analysis, debug_payload=debug_payload, evidence_payload=evidence_payload))
    yield _sse({"type": "done"})


def _sources(chunks: Iterable[RetrievedChunk]) -> List[dict]:
    return [
        {
            "source_name": chunk.source_name,
            "source_type": chunk.source_type,
            "chunk_index": chunk.chunk_index,
            "relevance": chunk.score,
            "chunk_id": chunk.chunk_id,
            "raw_file_path": chunk.raw_file_path,
        }
        for chunk in chunks
    ]


def _source_refs(chunks: Iterable[RetrievedChunk]) -> List[str]:
    refs = []
    for chunk in chunks:
        source = f"{chunk.source_name}#{chunk.chunk_index}"
        if source not in refs:
            refs.append(source)
    return refs


def _sources_event(
    chunks: Iterable[RetrievedChunk],
    answer: str = "",
    debug_payload: Optional[dict] = None,
    evidence_payload: Optional[dict] = None,
    source_status: Optional[str] = None,
) -> dict:
    if source_status == "generated_only":
        event = {"type": "sources", "source_status": "generated_only", "sources": []}
    elif _is_no_answer(answer):
        event = {"type": "sources", "source_status": "no_answer", "sources": []}
    else:
        event = {"type": "sources", "source_status": "grounded", "sources": _sources(chunks)}
    if debug_payload is not None:
        event["_debug"] = debug_payload
    if evidence_payload is not None:
        event["evidence"] = evidence_payload
    return event


def _is_generated_only_retrieval(chunks: Iterable[RetrievedChunk]) -> bool:
    retrieved = list(chunks)
    return bool(retrieved) and all(chunk.source_type == "generated_asset" for chunk in retrieved)


def _is_no_answer(answer: str) -> bool:
    text = " ".join(str(answer or "").split())
    if not text:
        return False
    head = text[:500]
    no_answer_markers = [
        "无法回答",
        "暂无相关内容",
        "无匹配来源",
        "没有匹配来源",
        "没有任何信息涉及",
        "没有直接涉及",
        "无法为您解答",
        "没有关于",
        "没有与",
        "还没有与",
        "并没有关于",
        "知识库缺少",
        "当前知识库缺少",
        "知识库中缺少",
        "当前知识库缺失",
        "知识库缺失",
        "没有涉及",
        "没有直接相关",
        "无直接相关",
        "未涉及",
        "未提及",
        "无法用来回答",
        "无法判断",
        "无适用资料",
        "完全不包含",
        "完全不相关",
        "不包含相关主题",
        "没有涵盖任何",
        "资料不足",
        "信息不足",
    ]
    return any(marker in head for marker in no_answer_markers)


def _strip_source_references(answer: str) -> str:
    stripped = re.split(r"(?:\n\s*)?来源[:：]", answer, maxsplit=1)[0].strip()
    return re.sub(r"[（(【\[]\s*$", "", stripped).rstrip()


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


def _generate_grounded_chinese_fallback(question: str, chunks: List[RetrievedChunk]) -> str:
    lines = [
        "检索到与问题直接相关的资料，但模型未能完成综合判断。先基于当前知识库给出可追溯的初步结论。\n\n",
        f"问题：{question}\n\n",
        "相关依据：\n",
    ]
    for index, chunk in enumerate(chunks[:5], start=1):
        excerpt = _compact_text(chunk.text, 220)
        if excerpt:
            lines.append(f"{index}. {excerpt}（来源：{chunk.source_name}#{chunk.chunk_index}）\n")
    lines.append("\n建议：请优先打开以上来源核对原文；如需更明确状态判断，可以继续追问“只基于这些来源归纳当前状态”。")
    return "".join(lines)


def _generate_codex_base_english_report(question: str, analysis: str, chunks: List[RetrievedChunk]) -> Iterable[str]:
    parsed = _parse_json_object(analysis)
    facts = parsed.get("key_facts") if isinstance(parsed, dict) and isinstance(parsed.get("key_facts"), list) else []
    terminology = parsed.get("terminology") if isinstance(parsed, dict) and isinstance(parsed.get("terminology"), list) else []
    logic_chain = parsed.get("logic_chain") if isinstance(parsed, dict) and isinstance(parsed.get("logic_chain"), str) else ""

    lines = [
        "English Report\n\n",
        "Executive Summary\n",
        f"This report answers the user question: {question}\n",
    ]
    if logic_chain:
        lines.append(f"{logic_chain.strip()}\n")
    elif facts:
        first_fact = facts[0] if isinstance(facts[0], dict) else {}
        content = str(first_fact.get("content", "")).strip()
        if content:
            lines.append(f"The most relevant evidence is: {content}\n")
    else:
        summary = _compact_text(analysis, 260)
        if summary:
            lines.append(f"The retrieved materials indicate the following: {summary}\n")

    if facts:
        lines.append("\nKey Findings\n")
        for index, fact in enumerate(facts[:6], start=1):
            if not isinstance(fact, dict):
                continue
            content = str(fact.get("content", "")).strip()
            source = str(fact.get("source", "")).strip()
            if not content:
                continue
            suffix = f" Source: {source}." if source else ""
            lines.append(f"{index}. {content}{suffix}\n")
    else:
        lines.append("\nKey Findings\n")
        for index, chunk in enumerate(chunks[:5], start=1):
            excerpt = _compact_text(chunk.text, 180)
            if excerpt:
                lines.append(f"{index}. {excerpt} Source: {chunk.source_name}#{chunk.chunk_index}.\n")

    term_lines = []
    for term in terminology[:8]:
        if not isinstance(term, dict):
            continue
        zh = str(term.get("zh", "")).strip()
        en = str(term.get("en", "")).strip()
        if zh and en:
            term_lines.append(f"- {en}: {zh}\n")
    if term_lines:
        lines.extend(["\nTerminology\n", *term_lines])

    lines.append("\nRecommended Use\n")
    lines.append(
        "Use this as a readable first draft. Where the source material is sparse or image-derived, verify the original file before making final decisions.\n"
    )

    lines.append("\nSources\n")
    seen_sources = set()
    for chunk in chunks[:8]:
        label = f"{chunk.source_name}#{chunk.chunk_index}"
        if label in seen_sources:
            continue
        seen_sources.add(label)
        lines.append(f"- {label}\n")
    return lines


def _format_chinese_answer(raw_answer: str, chunks: List[RetrievedChunk]) -> str:
    answer = raw_answer.strip()
    if _is_no_answer(answer):
        return _strip_source_references(answer)

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
            if content:
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

    sources = _source_refs(chunks)
    if sources:
        lines.extend(["", "来源：", *[f"- {source}" for source in sources]])

    return "\n".join(lines).strip()


def _compact_text(text: str, limit: int) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) > limit:
        return compact[:limit].rstrip() + "..."
    return compact


def _parse_json_object(text: str) -> Optional[dict]:
    cleaned = _strip_json_markdown_wrapper(text)
    for candidate in _json_object_candidates(cleaned):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            recovered = _recover_json_object_fragment(candidate)
            if recovered is None:
                continue
            try:
                parsed = json.loads(recovered)
            except json.JSONDecodeError:
                continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _strip_json_markdown_wrapper(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"^\s*```[ \t]*(?:json|JSON)?[ \t]*\r?\n?", "", cleaned)
    cleaned = re.sub(r"\r?\n?\s*```\s*$", "", cleaned)
    return cleaned.strip()


def _json_object_candidates(text: str) -> List[str]:
    cleaned = str(text or "").strip()
    if not cleaned:
        return []
    candidates = [cleaned]
    first = cleaned.find("{")
    if first == -1:
        return candidates
    last = cleaned.rfind("}")
    if last >= first:
        candidates.append(cleaned[first : last + 1])
    else:
        candidates.append(cleaned[first:])
    deduped = []
    for candidate in candidates:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _recover_json_object_fragment(text: str) -> Optional[str]:
    fragment = _remove_trailing_json_commas(str(text or "").strip())
    if not fragment.startswith("{"):
        return None
    stack = []
    in_string = False
    escaped = False
    for char in fragment:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append(char)
        elif char in "}]":
            if not stack:
                return None
            expected = "{" if char == "}" else "["
            if stack[-1] != expected:
                return None
            stack.pop()
    if in_string:
        fragment += '"'
    while stack:
        opener = stack.pop()
        fragment += "}" if opener == "{" else "]"
    return _remove_trailing_json_commas(fragment)


def _remove_trailing_json_commas(text: str) -> str:
    previous = None
    cleaned = text
    while cleaned != previous:
        previous = cleaned
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    return cleaned


def _is_deepseek_available(endpoint: str, client: Optional[Any]) -> bool:
    return bool(endpoint or client is not None)


def _sse(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
