from engine.answer_planner import infer_answer_mode


def test_infer_answer_mode_prefers_english_report_for_en_language():
    decision = infer_answer_mode("总结一下 JLR 面试材料", language="en")

    assert decision.mode == "english_report"
    assert decision.reason == "language_en"


def test_infer_answer_mode_detects_interview_story_and_retrospective():
    assert infer_answer_mode("把 Audi 项目经验整理成面试故事").mode == "interview_story"
    assert infer_answer_mode("总结一下 JLR 项目复盘").mode == "retrospective"


def test_infer_answer_mode_defaults_to_answer_for_generic_questions():
    decision = infer_answer_mode("我关于技术选型有哪些稳定观点？")

    assert decision.mode == "answer"
    assert decision.reason == "default"

