from engine.query_rewriter import expand_query


def test_expand_query_keeps_original_first_and_adds_jlr_interview_variants():
    plan = expand_query("整理一下我关于 JLR 面试的所有材料")

    queries = [variant.query for variant in plan.queries]
    assert queries[0] == "整理一下我关于 JLR 面试的所有材料"
    assert "JLR 面试" in queries
    assert "JLR 面试准备" in queries
    assert "JLR 职位要求" in queries
    assert "JLR 面试复盘" in queries
    assert "JLR 面试反馈" in queries
    assert len(queries) <= 6
    assert all(variant.reason for variant in plan.queries)


def test_expand_query_uses_source_title_hints_without_duplicates():
    plan = expand_query(
        "总结 Audi 项目经验",
        source_titles=["Audi_project_retro.md", "Audi 技术选型复盘.pdf"],
    )

    queries = [variant.query for variant in plan.queries]
    assert queries[0] == "总结 Audi 项目经验"
    assert "Audi 项目复盘" in queries
    assert len(queries) == len(set(queries))
    assert len(queries) <= 6

