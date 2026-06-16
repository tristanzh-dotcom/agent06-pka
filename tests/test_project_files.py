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


def test_settings_page_hides_fallback_english_generation_section():
    root = Path(__file__).resolve().parents[1]
    settings_html = (root / "static/settings.html").read_text(encoding="utf-8")

    assert "连接诊断" in settings_html
    assert "DeepSeek 分析模型" not in settings_html
    assert 'name="deepseek.endpoint"' not in settings_html
    assert 'name="deepseek.api_key"' not in settings_html
    assert 'name="deepseek.model"' not in settings_html
    assert "英文输出模型" not in settings_html
    assert 'name="generation.endpoint"' not in settings_html
    assert 'name="generation.api_key"' not in settings_html
    assert 'name="generation.model"' not in settings_html
    assert "Codex 基座模型" not in settings_html


def test_settings_page_keeps_fixed_model_stack_out_of_maintenance_controls():
    root = Path(__file__).resolve().parents[1]
    settings_html = (root / "static/settings.html").read_text(encoding="utf-8")
    style_css = (root / "static/style.css").read_text(encoding="utf-8")
    app_js = (root / "static/app.js").read_text(encoding="utf-8")

    assert "OCR 与向量检索" not in settings_html
    assert 'name="ocr.endpoint"' not in settings_html
    assert 'name="ocr.api_key"' not in settings_html
    assert 'name="retrieval.final_top_k"' not in settings_html
    assert "bge-m3" not in settings_html
    assert "智谱向量模型" not in settings_html
    assert 'class="embedding-field"' not in settings_html
    assert 'id="settings-form"' not in settings_html
    assert 'id="test-connection"' in settings_html
    assert 'id="settings-feedback"' in settings_html
    assert "diagnostic-list" in settings_html
    assert "#test-connection" in style_css
    test_button_rule = style_css[style_css.index("#test-connection") : style_css.index(".danger-zone")]
    assert "background: var(--panel);" in test_button_rule
    assert "color: var(--ink);" in test_button_rule
    assert "border: 1px solid var(--line);" in test_button_rule
    assert "background: var(--accent-2);" not in test_button_rule
    assert "function formatSettingsFeedback" in app_js
    assert 'setFeedback("settings-feedback", formatSettingsFeedback(result))' in app_js
    assert "checks.map" in app_js
    assert "20260616-source-type-ui" in settings_html


def test_settings_page_uses_readable_diagnostic_text_colors():
    root = Path(__file__).resolve().parents[1]
    style_css = (root / "static/style.css").read_text(encoding="utf-8")

    assert ".diagnostic-panel" in style_css
    diagnostic_rule = style_css[style_css.index(".diagnostic-panel") : style_css.index(".diagnostic-actions")]
    assert "min-height: 0;" in diagnostic_rule
    assert ".diagnostic-list" in style_css
    list_rule = style_css[style_css.index(".diagnostic-list") : style_css.index(".diagnostic-actions")]
    assert "color: var(--ink);" in list_rule
    feedback_rule = style_css[style_css.index(".feedback") : style_css.index(".ingest-workbench")]
    assert "color: var(--ink);" in feedback_rule


def test_settings_page_exposes_clear_knowledge_action():
    root = Path(__file__).resolve().parents[1]
    settings_html = (root / "static/settings.html").read_text(encoding="utf-8")
    app_js = (root / "static/app.js").read_text(encoding="utf-8")

    assert 'id="clear-knowledge"' in settings_html
    assert "清空知识库" in settings_html
    assert 'id="clear-feedback"' in settings_html
    assert 'postJSON("api/ingest/clear", {})' in app_js
    assert "formatClearFeedback" in app_js
    assert 'setFeedback("clear-feedback", formatClearFeedback(result))' in app_js
    assert 'id="clear-confirmation"' in settings_html
    assert 'data-confirm-phrase="清空知识库"' in settings_html
    assert 'id="clear-knowledge" disabled' in settings_html
    assert "setupClearKnowledgeGuard" in app_js
    assert 'confirm(' not in app_js


def test_settings_danger_zone_is_collapsed_to_a_two_line_maintenance_control():
    root = Path(__file__).resolve().parents[1]
    settings_html = (root / "static/settings.html").read_text(encoding="utf-8")
    style_css = (root / "static/style.css").read_text(encoding="utf-8")

    assert '<details class="panel danger-zone">' in settings_html
    assert '<details class="panel danger-zone" open>' not in settings_html
    assert '<summary class="danger-summary">' in settings_html
    assert 'class="danger-title"' in settings_html
    assert 'class="danger-meta"' in settings_html
    assert 'class="danger-body"' in settings_html
    assert settings_html.index('class="danger-summary"') < settings_html.index('class="danger-body"')
    assert ".danger-zone {" in style_css
    danger_zone_rule = style_css[style_css.index(".danger-zone {") : style_css.index(".danger-summary")]
    assert "padding: 0;" in danger_zone_rule
    assert "overflow: hidden;" in danger_zone_rule
    danger_summary_rule = style_css[style_css.index(".danger-summary") : style_css.index(".danger-summary::-webkit-details-marker")]
    assert "min-height: 64px;" in danger_summary_rule
    assert "display: flex;" in danger_summary_rule
    assert ".danger-body" in style_css


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

    assert '<main class="ingest-workbench" aria-label="内容录入">' in index_html
    assert '<header class="ingest-header">' not in index_html
    assert '<h1>内容录入</h1>' not in index_html
    assert 'class="ingest-grid"' in index_html
    assert 'class="ingest-pane ingest-text-pane"' in index_html
    assert 'class="ingest-pane ingest-upload-pane"' in index_html
    assert '<main class="shell">' not in index_html

    assert ".ingest-workbench" in style_css
    assert "height: 100vh" in style_css
    assert "grid-template-rows: minmax(0, 1fr)" in style_css
    assert ".ingest-header" not in style_css
    assert ".ingest-grid" in style_css
    assert "grid-template-columns: minmax(0, 1.15fr) minmax(300px, 0.85fr)" in style_css
    assert ".ingest-feedback" in style_css
    assert "max-height: 48px" in style_css


def test_ingest_upload_feedback_has_reserved_non_overlapping_status_row():
    root = Path(__file__).resolve().parents[1]
    index_html = (root / "static/index.html").read_text(encoding="utf-8")
    style_css = (root / "static/style.css").read_text(encoding="utf-8")

    assert 'id="file-feedback" class="feedback ingest-feedback upload-feedback"' in index_html
    pane_rule = style_css[style_css.index(".ingest-pane {") : style_css.index(".ingest-pane-heading")]
    assert "gap: 10px;" in pane_rule
    form_rule = style_css[style_css.index(".ingest-form {") : style_css.index(".ingest-text-form textarea")]
    assert "overflow: hidden;" in form_rule
    file_form_rule = style_css[style_css.index(".ingest-file-form {") : style_css.index(".upload-native-input")]
    assert "grid-template-rows: minmax(0, 1fr) auto auto;" in file_form_rule
    feedback_rule = style_css[style_css.index(".ingest-feedback {") : style_css.index(".ask-workbench")]
    assert "margin: 0;" in feedback_rule
    assert "min-height: 40px;" in feedback_rule
    assert "max-height: 48px;" in feedback_rule
    assert "line-height: 1.45;" in feedback_rule
    assert ".upload-feedback" in style_css


def test_ingest_upload_supports_multi_file_queue_and_batch_endpoint():
    root = Path(__file__).resolve().parents[1]
    index_html = (root / "static/index.html").read_text(encoding="utf-8")
    app_js = (root / "static/app.js").read_text(encoding="utf-8")
    style_css = (root / "static/style.css").read_text(encoding="utf-8")

    assert 'id="file-input" type="file" multiple' in index_html
    assert 'data-upload-slot-board' in index_html
    assert 'id="file-list"' in index_html
    assert 'id="file-summary"' in index_html
    assert 'id="clear-selected-files" class="secondary-action" hidden' in index_html
    assert "renderSelectedFiles" in app_js
    assert "selectedFiles" in app_js
    assert 'fetch("api/ingest/files"' in app_js
    assert "clearButton.hidden = true" in app_js
    assert "clearButton.hidden = false" in app_js
    assert "if (clearButton) clearButton.disabled" not in app_js
    assert "input.files[0]" not in app_js
    assert ".upload-slot-board" in style_css
    assert ".upload-slot" in style_css


def test_ingest_upload_displays_quality_and_skipped_status():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "static/app.js").read_text(encoding="utf-8")
    style_css = (root / "static/style.css").read_text(encoding="utf-8")

    assert "qualityBadge" in app_js
    assert "需 OCR 未入库" in app_js
    assert "result.skipped" in app_js
    assert 'result.status === "skipped"' in app_js
    assert ".upload-slot.is-skipped" in style_css
    assert ".quality-badge" in style_css
    assert ".quality-full" in style_css
    assert ".quality-ocr" in style_css
    assert ".quality-low" in style_css
    assert ".quality-blocked" in style_css
    assert ".quality-failed" in style_css
    assert "button.quality-full" in style_css
    assert "button.quality-low" in style_css
    assert "button.quality-blocked" in style_css
    assert "button.quality-failed" in style_css
    assert ".upload-slot.is-low" not in style_css
    assert ".upload-slot.is-ocr" not in style_css


def test_quality_badge_mapping_uses_existing_quality_fields_without_upload_slot_colors():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "static/app.js").read_text(encoding="utf-8")

    assert "全文入库，低信度" in app_js
    assert "全文入库" in app_js
    assert "OCR 入库" in app_js
    assert "OCR 部分入库" in app_js
    assert "低质量入库" in app_js
    assert "未入库，需 OCR" in app_js
    assert '"quality-full"' in app_js
    assert '"quality-full-low"' in app_js
    assert '"quality-ocr"' in app_js
    assert '"quality-ocr-partial"' in app_js
    assert '"quality-low"' in app_js
    assert '"quality-blocked"' in app_js
    assert '"is-ocr"' not in app_js
    assert '"is-low"' not in app_js


def test_quality_badge_independent_of_upload_status():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "static/app.js").read_text(encoding="utf-8")

    error_guard = 'if (result?.status === "error") return { className: "quality-failed", text: "解析失败" };'
    quality_read = "const quality = result?.quality || {};"
    quality_badge_body = app_js[app_js.index("function qualityBadge") : app_js.index("function formatQualityPercent")]
    assert error_guard in quality_badge_body
    assert quality_badge_body.index(error_guard) < quality_badge_body.index(quality_read)


def test_ingest_upload_quality_details_expand_inline_and_link_raw_file():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "static/app.js").read_text(encoding="utf-8")
    style_css = (root / "static/style.css").read_text(encoding="utf-8")

    assert "function qualityDetails" in app_js
    assert "function formatQualityPercent" in app_js
    assert "Math.round" in app_js
    assert "valid_ratio" in app_js
    assert "effective_chars_per_page" in app_js
    assert "ocr_provider" in app_js
    assert "reasons" in app_js
    assert "查看原文件" in app_js
    assert "raw_file_path" in app_js
    assert "api/files/" in app_js
    assert "upload-quality-detail" in app_js
    assert ".upload-quality-detail" in style_css


def test_ingest_upload_slot_meta_does_not_duplicate_quality_badge_text():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "static/app.js").read_text(encoding="utf-8")
    render_body = app_js[app_js.index("function renderUploadSlots") : app_js.index("const renderSelectedFiles")]

    assert 'const qualityMessage = qualityStatusMessage(result);' not in render_body
    assert 'result.chunks || 0} 个片段' in render_body
    assert '"未入库"' in render_body


def test_ingest_upload_quality_status_explains_partial_ocr_and_skipped_indexing():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "static/app.js").read_text(encoding="utf-8")

    assert "qualityStatusMessage" in app_js
    assert "ocr_partial" in app_js
    assert "ocr_pages_processed" in app_js
    assert "source_page_count" in app_js
    assert "OCR 部分入库" in app_js
    assert "仅 OCR 前" in app_js
    assert "未进入主知识库，避免污染检索" in app_js
    assert "OCR 失败未入库" in app_js
    assert "OCR 超时未入库" in app_js
    assert 'action === "ocr_timeout_skipped"' in app_js
    assert 'qualityStatusMessage(item)' in app_js


def test_ingest_upload_uses_six_slot_board_interaction_contract():
    root = Path(__file__).resolve().parents[1]
    index_html = (root / "static/index.html").read_text(encoding="utf-8")
    app_js = (root / "static/app.js").read_text(encoding="utf-8")
    style_css = (root / "static/style.css").read_text(encoding="utf-8")

    assert 'data-upload-slot-board' in index_html
    assert 'data-upload-max-files="6"' in index_html
    assert "upload-picker" not in index_html
    assert "选择多个文件" not in index_html
    assert "const MAX_UPLOAD_FILES = 6;" in app_js
    assert "function renderUploadSlots" in app_js
    assert "index < MAX_UPLOAD_FILES" in app_js
    assert "selectedFiles.length >= MAX_UPLOAD_FILES" in app_js
    assert "fileInput.disabled = selectedFiles.length >= MAX_UPLOAD_FILES" in app_js
    assert "最多上传 6 个文件，请先移除一个文件。" in app_js
    assert "uploadSlotStatus" in app_js
    assert "上传槽" in app_js
    assert "upload-slot-hint" not in app_js
    assert "txt / md / docx / pptx / pdf / xlsx / 图片" not in app_js
    assert ".upload-slot-board" in style_css
    slot_board_rule = style_css[style_css.index(".upload-slot-board") : style_css.index(".upload-slot {")]
    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in slot_board_rule
    assert "overflow-x: hidden;" in slot_board_rule
    assert ".upload-slot.is-empty" in style_css
    assert ".upload-slot.is-filled" in style_css
    assert ".upload-slot.is-complete" in style_css
    assert ".upload-slot.is-error" in style_css


def test_ingest_upload_errors_are_readable_and_not_restored_as_stale_state():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "static/app.js").read_text(encoding="utf-8")

    assert "function humanizeErrorMessage" in app_js
    assert "function isStaleUploadFailure" in app_js
    assert "JSON.parse" in app_js
    assert "接口未找到，请刷新后重试" in app_js
    assert 'id === "file-feedback" && isStaleUploadFailure(value)' in app_js
    assert 'setFeedback("file-feedback", formatErrorFeedback("上传", error))' in app_js


def test_upload_413_error_detail_is_unwrapped_safely_for_user_feedback():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "static/app.js").read_text(encoding="utf-8")

    assert "function formatUpload413Error" in app_js
    assert "detail?.chunks" in app_js
    assert "detail?.limit" in app_js
    assert 'detail?.quality?.action === "too_large_skipped"' in app_js
    assert "文件过大，未入库" in app_js
    assert "解析产生" in app_js
    assert "超过当前同步入库上限" in app_js


def test_upload_quality_badge_maps_too_large_skipped_without_parser_failure_copy():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "static/app.js").read_text(encoding="utf-8")

    quality_badge_body = app_js[app_js.index("function qualityBadge") : app_js.index("function formatQualityPercent")]
    assert 'action === "too_large_skipped"' in quality_badge_body
    assert "文件过大，未入库" in quality_badge_body
    assert "解析失败" in quality_badge_body
    assert quality_badge_body.index('action === "too_large_skipped"') < quality_badge_body.index('"解析失败"')


def test_upload_quality_renders_org_chart_secondary_badge_without_replacing_main_badge():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "static/app.js").read_text(encoding="utf-8")
    style_css = (root / "static/style.css").read_text(encoding="utf-8")

    assert "function orgChartBadge" in app_js
    assert "quality.org_chart_chunks" in app_js
    assert 'quality.org_chart_mode === "pdf_layout_fallback"' in app_js
    assert "Org Chart" in app_js
    render_badge_body = app_js[app_js.index("function renderQualityBadge") : app_js.index("function summarizeBatchFeedback")]
    assert "qualityBadge(result)" in render_badge_body
    assert "orgChartBadge(result)" in render_badge_body
    assert ".quality-org-chart" in style_css


def test_ask_sources_render_source_type_badges_for_org_chart_pdf_and_text():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "static/app.js").read_text(encoding="utf-8")
    style_css = (root / "static/style.css").read_text(encoding="utf-8")

    assert "function sourceTypeBadge" in app_js
    assert "source.source_type" in app_js
    assert "source-type-badge" in app_js
    assert "source-type-org-chart" in app_js
    assert "source-type-pdf" in app_js
    assert "source-type-text" in app_js
    assert "Org Chart" in app_js
    assert "PDF" in app_js
    assert "Text" in app_js
    assert ".source-type-badge" in style_css
    assert ".source-type-org-chart" in style_css
    assert ".source-type-pdf" in style_css
    assert ".source-type-text" in style_css


def test_raw_file_links_use_truthy_raw_file_path_helper_not_property_presence():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "static/app.js").read_text(encoding="utf-8")

    assert '"raw_file_path" in' not in app_js
    assert "function hasRawFilePath" in app_js
    assert "hasRawFilePath(result)" in app_js
    assert "hasRawFilePath(source)" in app_js


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


def test_ask_embedded_state_preserves_answer_transcript_across_shell_switches():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "static/app.js").read_text(encoding="utf-8")

    assert "messages: askState.messages" in app_js
    assert "function restoreAskConversation" in app_js
    assert "restoreAskConversation(state.ask)" in app_js
    assert "appendSources(answer, displaySources)" in app_js
    assert "askState.messages[messageIndex].sources = askState.sources" in app_js
    assert "askState.messages[messageIndex].sourceStatus = sourceStatus" in app_js
    assert "askState.messages[messageIndex].text = askState.answer" in app_js


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

    assert '<main class="ingest-workbench" aria-label="内容录入">' in (root / "static/index.html").read_text(encoding="utf-8")
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


def test_ask_page_marks_no_answer_sources_as_unused():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "static/app.js").read_text(encoding="utf-8")
    style_css = (root / "static/style.css").read_text(encoding="utf-8")

    assert "appendSourceNotice" in app_js
    assert 'payload.source_status === "no_answer"' in app_js
    assert "知识库缺失，未使用参考来源" in app_js
    assert "sourceStatus" in app_js
    assert "ask-source-notice" in app_js
    assert ".ask-source-notice" in style_css


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


def test_frontend_notifies_agent06_after_knowledge_mutations_and_supports_embedded_state():
    root = Path(__file__).resolve().parents[1]
    app_js = (root / "static/app.js").read_text(encoding="utf-8")

    assert "agent06:knowledge-updated" in app_js
    assert "ingest:text" in app_js
    assert "ingest:file" in app_js
    assert "clear" in app_js
    assert "web-publishing:embedded-state:snapshot" in app_js
    assert "web-publishing:embedded-state:restore" in app_js
    assert "web-publishing:embedded-state:request-snapshot" in app_js
    assert "file-input" in app_js
    assert ".files =" not in app_js
    assert ".value = state.file" not in app_js


def test_agent06_shell_uses_agent04_style_workflow_switch_contract():
    web_root = Path(__file__).resolve().parents[2] / "web"
    server_mjs = (web_root / "server.mjs").read_text(encoding="utf-8")
    agent06_css = (web_root / "app/agent06.css").read_text(encoding="utf-8")

    assert 'class="agent06-info-switch"' in server_mjs
    assert "<small>功能切换</small>" in server_mjs
    assert "agent06-tab-switch" in server_mjs
    assert "agent06-tab-switch__button" in server_mjs
    assert ".agent06-info-switch" in agent06_css
    assert ".agent06-tab-switch" in agent06_css
    assert ".agent06-tab-switch__button.is-active" in agent06_css
