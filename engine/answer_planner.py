from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class AnswerModeDecision:
    mode: str
    reason: str


def infer_answer_mode(question: str, language: str = "zh") -> AnswerModeDecision:
    text = str(question or "")
    if language == "en" or re.search(r"\benglish report\b", text, re.IGNORECASE) or "英文报告" in text:
        return AnswerModeDecision(mode="english_report", reason="language_en")
    if "面试故事" in text or re.search(r"\binterview story\b|\bSTAR\b", text, re.IGNORECASE):
        return AnswerModeDecision(mode="interview_story", reason="interview_story_keyword")
    if "复盘" in text or re.search(r"\bretrospective\b|\blessons learned\b", text, re.IGNORECASE):
        return AnswerModeDecision(mode="retrospective", reason="retrospective_keyword")
    if "PPT" in text.upper() or "幻灯片" in text or "slide" in text.lower():
        return AnswerModeDecision(mode="ppt_outline", reason="ppt_keyword")
    if "决策" in text or "decision memo" in text.lower():
        return AnswerModeDecision(mode="decision_memo", reason="decision_keyword")
    return AnswerModeDecision(mode="answer", reason="default")
