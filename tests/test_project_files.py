from pathlib import Path


def test_required_project_files_exist():
    root = Path(__file__).resolve().parents[1]

    for relative_path in [
        "requirements.txt",
        "config.example.yaml",
        ".gitignore",
        "server.py",
        "cli.py",
        "static/index.html",
        "static/ask.html",
        "static/settings.html",
        "static/style.css",
        "static/app.js",
        "engine/__init__.py",
        "engine/models.py",
        "engine/config.py",
        "engine/parser.py",
        "engine/chunker.py",
        "engine/indexer.py",
        "engine/retriever.py",
        "engine/generator.py",
        "engine/exporter.py",
        "engine/ocr.py",
    ]:
        assert (root / relative_path).exists(), relative_path


def test_gitignore_protects_local_data_and_secrets():
    root = Path(__file__).resolve().parents[1]
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")

    for pattern in [
        "config.yaml",
        "PKA_Data/",
        "__pycache__/",
        ".vector/",
        ".fts5/",
    ]:
        assert pattern in gitignore


def test_settings_page_exposes_both_model_sections():
    root = Path(__file__).resolve().parents[1]
    settings_html = (root / "static/settings.html").read_text(encoding="utf-8")

    assert "DeepSeek 分析模型" in settings_html
    assert 'name="deepseek.endpoint"' in settings_html
    assert 'name="deepseek.api_key"' in settings_html
    assert 'name="deepseek.model"' in settings_html
    assert "英文输出模型" in settings_html
    assert '<select name="generation.model">' in settings_html
    assert '<option value="codex-base">Codex 基座模型</option>' in settings_html
    assert settings_html.count('<option value=') == 1


def test_settings_page_exposes_clear_knowledge_action():
    root = Path(__file__).resolve().parents[1]
    settings_html = (root / "static/settings.html").read_text(encoding="utf-8")
    app_js = (root / "static/app.js").read_text(encoding="utf-8")

    assert 'id="clear-knowledge"' in settings_html
    assert "清空知识库" in settings_html
    assert 'id="clear-feedback"' in settings_html
    assert 'postJSON("api/ingest/clear", {})' in app_js
    assert "确定清空全部知识库" in app_js


def test_ingest_page_uses_separate_feedback_for_text_and_file_forms():
    root = Path(__file__).resolve().parents[1]
    index_html = (root / "static/index.html").read_text(encoding="utf-8")
    app_js = (root / "static/app.js").read_text(encoding="utf-8")

    assert 'id="text-feedback"' in index_html
    assert 'id="file-feedback"' in index_html
    assert 'setFeedback("text-feedback"' in app_js
    assert 'setFeedback("file-feedback"' in app_js
    assert 'setFeedback("feedback"' not in app_js


def test_ingest_page_uses_single_screen_dual_entry_workbench():
    root = Path(__file__).resolve().parents[1]
    index_html = (root / "static/index.html").read_text(encoding="utf-8")
    style_css = (root / "static/style.css").read_text(encoding="utf-8")

    assert '<main class="ingest-workbench">' in index_html
    assert 'class="ingest-grid"' in index_html
    assert 'class="ingest-pane ingest-text-pane"' in index_html
    assert 'class="ingest-pane ingest-upload-pane"' in index_html
    assert '<main class="shell">' not in index_html

    assert ".ingest-workbench" in style_css
    assert "height: 100vh" in style_css
    assert "grid-template-rows: auto minmax(0, 1fr)" in style_css
    assert ".ingest-grid" in style_css
    assert "grid-template-columns: minmax(0, 1.15fr) minmax(300px, 0.85fr)" in style_css
    assert ".ingest-feedback" in style_css
    assert "max-height: 86px" in style_css


def test_ingest_feedback_is_summarized_without_chunk_id_dump():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "static/app.js").read_text(encoding="utf-8")

    assert "formatIngestFeedback" in app_js
    assert "chunk_ids" not in app_js
    assert "JSON.stringify(value, null, 2)" in app_js


def test_frontend_assets_are_cache_busted_after_ui_contract_changes():
    root = Path(__file__).resolve().parents[1]

    for html_file in [
        root / "static/index.html",
        root / "static/ask.html",
        root / "static/settings.html",
    ]:
        html = html_file.read_text(encoding="utf-8")
        assert 'href="static/style.css?v=' in html
        assert 'src="static/app.js?v=' in html


def test_ingest_forms_show_errors_instead_of_silent_failures():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "static/app.js").read_text(encoding="utf-8")

    assert "formatErrorFeedback" in app_js
    assert 'setFeedback("text-feedback", formatErrorFeedback("录入", error))' in app_js
    assert 'setFeedback("file-feedback", formatErrorFeedback("上传", error))' in app_js


def test_text_ingest_clears_textarea_after_success():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "static/app.js").read_text(encoding="utf-8")

    assert 'const textInput = document.getElementById("text-input")' in app_js
    assert 'textInput.value = ""' in app_js


def test_ask_page_exposes_language_switch_and_query_payload_uses_it():
    root = Path(__file__).resolve().parents[1]
    ask_html = (root / "static/ask.html").read_text(encoding="utf-8")
    app_js = (root / "static/app.js").read_text(encoding="utf-8")

    assert 'class="language-switch"' in ask_html
    assert 'name="language" value="zh" checked' in ask_html
    assert 'name="language" value="en"' in ask_html
    assert "中文建议" in ask_html
    assert "English Report" in ask_html
    assert 'input[name="language"]:checked' in app_js
    assert "JSON.stringify({ question, language })" in app_js


def test_ask_page_p0_layout_contract_keeps_input_in_first_viewport():
    root = Path(__file__).resolve().parents[1]
    ask_html = (root / "static/ask.html").read_text(encoding="utf-8")
    style_css = (root / "static/style.css").read_text(encoding="utf-8")
    app_js = (root / "static/app.js").read_text(encoding="utf-8")

    assert '<main class="ask-workbench">' in ask_html
    assert '<header class="ask-header">' in ask_html
    assert '<div class="exportbar" id="export-bar" style="display:none">' in ask_html
    assert '<div id="conversation" class="ask-conversation">' in ask_html
    assert '<div id="empty-state" class="empty-chips">' in ask_html
    assert '<button type="button" class="empty-chip">我之前关于组织架构的看法是什么？</button>' in ask_html
    assert '<button type="button" class="empty-chip">总结一下我最近录入的所有内容</button>' in ask_html
    assert '<button type="button" class="empty-chip">基于我的笔记，给出当前的技术选型建议</button>' in ask_html
    assert "我之前关于组织架构的看法是什么？" in ask_html
    assert "总结一下我最近录入的所有内容" in ask_html
    assert "基于我的笔记，给出当前的技术选型建议" in ask_html

    query_form_start = ask_html.index('<form id="query-form" class="ask-input-bar">')
    language_start = ask_html.index('<fieldset class="language-switch" id="language-switch">')
    input_start = ask_html.index('<input id="question-input"')
    send_start = ask_html.index('<button type="submit">发送</button>')
    assert query_form_start < language_start < input_start < send_start

    assert ".ask-workbench" in style_css
    assert "height: 100vh;" in style_css
    assert ".ask-panel" not in style_css
    assert ".panel ask-panel" not in ask_html
    assert "height: calc(100vh - 102px);" not in style_css
    assert "height: calc(100vh - 160px);" not in style_css
    assert "flex: 1;" in style_css
    assert "min-height: 0;" in style_css
    assert "max-height: calc(100vh - 262px);" not in style_css
    assert "max-height: calc(100vh - 320px);" not in style_css
    assert "overflow-y: auto;" in style_css
    assert ".ask-conversation" in style_css
    assert ".conversation" not in style_css
    assert ".conversation {\n  min-height: 420px;" not in style_css
    assert ".ask-input-bar {\n  display: flex;" in style_css
    assert ".querybar" not in style_css
    assert "align-items: center;" in style_css
    assert "flex-shrink: 0;" in style_css
    assert ".ask-input-bar {\n    grid-template-columns" not in style_css
    assert ".empty-chip" in style_css
    assert '.empty-chip[type="button"]' in style_css
    assert '.empty-chip[type="button"] {\n  background: var(--panel);' in style_css
    assert 'document.querySelectorAll(".empty-chip")' in app_js
    assert 'document.getElementById("question-input").value = chip.textContent' in app_js
    assert 'document.getElementById("query-form").requestSubmit()' in app_js


def test_ask_page_p0_interactions_hide_export_and_clear_empty_state():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "static/app.js").read_text(encoding="utf-8")

    assert 'document.getElementById("export-bar")' in app_js
    assert 'exportBar.style.display = "none"' in app_js
    assert 'exportBar.style.display = "flex"' in app_js
    assert 'payload.type === "done"' in app_js
    assert 'document.getElementById("empty-state")' in app_js
    assert "empty.remove()" in app_js


def test_ask_export_buttons_use_neutral_publishing_theme_style():
    root = Path(__file__).resolve().parents[1]
    ask_html = (root / "static/ask.html").read_text(encoding="utf-8")
    style_css = (root / "static/style.css").read_text(encoding="utf-8")

    assert '<button type="button" id="export-word">导出 Word</button>' in ask_html
    assert '<button type="button" id="export-ppt">导出 PPT</button>' in ask_html
    assert "button[type=\"button\"] {\n  background: var(--accent-2);" in style_css
    assert ".exportbar button[type=\"button\"]" in style_css
    export_button_rule = style_css[
        style_css.index(".exportbar button[type=\"button\"]") : style_css.index(".ask-conversation")
    ]
    assert "background: var(--panel);" in export_button_rule
    assert "color: var(--accent);" in export_button_rule
    assert "border: 1px solid var(--line);" in export_button_rule
    assert "background: var(--accent-2);" not in export_button_rule


def test_ask_submit_shows_pending_feedback_before_stream_tokens():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "static/app.js").read_text(encoding="utf-8")

    assert 'const pendingText = "检索中..."' in app_js
    assert "answer.dataset.pending = \"true\"" in app_js
    assert 'answer.textContent = pendingText' in app_js
    assert 'if (answer.dataset.pending === "true")' in app_js
    assert "delete answer.dataset.pending" in app_js
    assert 'answer.textContent = formatErrorFeedback("问答", error)' in app_js


def test_quick_ingest_bar_is_removed_from_frontend():
    root = Path(__file__).resolve().parents[1]
    for relative_path in [
        "static/index.html",
        "static/ask.html",
        "static/settings.html",
        "static/app.js",
        "static/style.css",
    ]:
        content = (root / relative_path).read_text(encoding="utf-8")
        assert "quick-ingest" not in content
        assert "quickIngest" not in content


def test_ask_page_sources_are_flat_not_collapsed_details():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "static/app.js").read_text(encoding="utf-8")
    style_css = (root / "static/style.css").read_text(encoding="utf-8")

    assert 'document.createElement("details")' not in app_js
    assert 'document.createElement("summary")' not in app_js
    assert "ask-sources" in app_js
    assert "ask-source-chip" in app_js
    assert ".ask-sources" in style_css
    assert ".ask-source-chip" in style_css
    assert "sources-flat" not in app_js
    assert "source-item" not in app_js
    assert ".sources-flat" not in style_css
    assert ".source-item" not in style_css


def test_pka_pages_are_bare_embedded_panels_without_internal_topbar():
    root = Path(__file__).resolve().parents[1]
    style_css = (root / "static/style.css").read_text(encoding="utf-8")

    for html_file in [
        root / "static/index.html",
        root / "static/ask.html",
        root / "static/settings.html",
    ]:
        html = html_file.read_text(encoding="utf-8")
        assert '<nav class="topbar">' not in html
        assert '<a class="brand" href="./">PKA</a>' not in html
        assert '<a href="./">录入</a>' not in html
        assert '<a href="ask">问答</a>' not in html
        assert '<a class="topbar-settings" href="settings">设置</a>' not in html

    assert '<main class="ingest-workbench">' in (root / "static/index.html").read_text(encoding="utf-8")
    assert '<main class="ask-workbench">' in (root / "static/ask.html").read_text(encoding="utf-8")
    assert '<main class="shell">' in (root / "static/settings.html").read_text(encoding="utf-8")

    assert "--topbar-bg" not in style_css
    assert ".topbar" not in style_css
    assert ".topbar-settings" not in style_css


def test_ask_page_renders_source_links_for_raw_files():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "static/app.js").read_text(encoding="utf-8")

    assert "source.raw_file_path" in app_js
    assert "api/files/" in app_js
    assert "api/sources?chunk_id=" in app_js
    assert "source.chunk_id" in app_js
    assert "encodeURIComponent" in app_js


def test_ask_page_sources_are_deduplicated_and_readable():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "static/app.js").read_text(encoding="utf-8")

    assert "function normalizeSourceList" in app_js
    assert "function formatSourceLabel" in app_js
    assert "manual_" in app_js
    assert "手动录入" in app_js
    assert "displaySources.slice(0, 5)" in app_js
    assert '${source.source_name} #${source.chunk_index}' not in app_js


def test_frontend_uses_relative_paths_for_agent06_prefix_proxy():
    root = Path(__file__).resolve().parents[1]
    html_files = [
        root / "static/index.html",
        root / "static/ask.html",
        root / "static/settings.html",
    ]

    for html_file in html_files:
        html = html_file.read_text(encoding="utf-8")
        assert 'href="/static/' not in html
        assert 'src="/static/' not in html
        assert 'href="/"' not in html
        assert 'href="/ask"' not in html
        assert 'href="/settings"' not in html

    app_js = (root / "static/app.js").read_text(encoding="utf-8")
    assert 'fetch("/api/' not in app_js
    assert "fetch('/api/" not in app_js
    assert "postJSON(\"/api/" not in app_js
    assert "postJSON('/api/" not in app_js
    assert "fetch(`/api/" not in app_js
