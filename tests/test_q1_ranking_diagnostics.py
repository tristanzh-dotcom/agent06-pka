from scripts.diagnose_q1_ranking import build_channel_table, build_source_snippet_table


def test_channel_table_lists_three_independent_rank_sources():
    fts = [
        {"chunk_id": "auto.pdf#47", "source_name": "上海财经大学2026自动驾驶生态报告68页.pdf"},
        {"chunk_id": "cockpit.pdf#153", "source_name": "2026-2030年全球及中国汽车智能座舱行业发展前景与投资机会研究报告.pdf"},
    ]
    vector = [
        {"chunk_id": "cockpit.pdf#153", "source_name": "2026-2030年全球及中国汽车智能座舱行业发展前景与投资机会研究报告.pdf"},
        {"chunk_id": "cockpit.pdf#150", "source_name": "2026-2030年全球及中国汽车智能座舱行业发展前景与投资机会研究报告.pdf"},
    ]
    merged = [
        {"chunk_id": "auto.pdf#47", "source_name": "上海财经大学2026自动驾驶生态报告68页.pdf"},
        {"chunk_id": "cockpit.pdf#153", "source_name": "2026-2030年全球及中国汽车智能座舱行业发展前景与投资机会研究报告.pdf"},
    ]

    table = build_channel_table({"FTS5": fts, "Vector": vector, "RRF merged": merged})

    assert "| 通道 | Rank 1-5 chunk_id | 来源 PDF | 来源计数 |" in table
    assert "| FTS5 | `#47, #153` | 自动驾驶, 智能座舱 | 自动驾驶=1, 智能座舱=1 |" in table
    assert "| Vector | `#153, #150` | 智能座舱, 智能座舱 | 智能座舱=2 |" in table
    assert "| RRF merged | `#47, #153` | 自动驾驶, 智能座舱 | 自动驾驶=1, 智能座舱=1 |" in table


def test_source_snippet_table_prints_per_pdf_fts_competitors():
    snippets = {
        "智能座舱": [
            {
                "chunk_id": "cockpit.pdf#7",
                "source_name": "2026-2030年全球及中国汽车智能座舱行业发展前景与投资机会研究报告.pdf",
                "text": "快速发展期（2021—2030年）：AI大模型开始应用于车载语音助手。",
            }
        ],
        "自动驾驶": [
            {
                "chunk_id": "auto.pdf#15",
                "source_name": "上海财经大学2026自动驾驶生态报告68页.pdf",
                "text": "L3 从技术验证阶段进入制度建设阶段。",
            }
        ],
    }

    table = build_source_snippet_table(snippets)

    assert "| 来源 PDF | Rank | chunk_id | 文本片段 |" in table
    assert "| 智能座舱 | 1 | `#7` | 快速发展期（2021—2030年）：AI大模型开始应用于车载语音助手。 |" in table
    assert "| 自动驾驶 | 1 | `#15` | L3 从技术验证阶段进入制度建设阶段。 |" in table
