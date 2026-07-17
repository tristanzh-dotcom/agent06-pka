async function postJSON(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

const askState = {
  conversationId: "",
  resetToken: "",
  sessions: [],
  question: "",
  language: "zh",
  answer: "",
  sources: [],
  sourceStatus: "",
  evidence: {},
  answerMode: "answer",
  modelRoute: "",
  createdAt: "",
  answerCompleted: false,
  savedAssetId: "",
  messages: [],
};

const MAX_CONVERSATION_MESSAGES = 20;
const MAX_CONVERSATION_SESSIONS = 30;
let askRequestInFlight = false;

let selectedFiles = [];
let fileUploadResults = [];
let expandedQualityFiles = new Set();
let uploadTaskPollTimers = new Map();
let pendingUploadSlotIndex = null;
const MAX_UPLOAD_FILES = 6;
const ORG_CHART_SLOT_INDEX = 5;
const MAX_UPLOAD_FEEDBACK = "最多上传 6 个文件，请先移除一个文件。";
const OCR_TASK_POLL_INTERVAL_MS = 1500;

function createConversationId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `conversation-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function ensureActiveConversation() {
  if (!askState.conversationId) askState.conversationId = createConversationId();
}

function resetActiveConversationFields() {
  askState.question = "";
  askState.answer = "";
  askState.sources = [];
  askState.sourceStatus = "";
  askState.evidence = {};
  askState.answerMode = "answer";
  askState.modelRoute = "";
  askState.createdAt = "";
  askState.answerCompleted = false;
  askState.savedAssetId = "";
  askState.messages = [];
}

function activeConversationSnapshot() {
  ensureActiveConversation();
  return {
    id: askState.conversationId,
    resetToken: askState.resetToken,
    question: askState.question,
    language: askState.language,
    answer: askState.answer,
    sources: askState.sources,
    sourceStatus: askState.sourceStatus,
    evidence: askState.evidence,
    answerMode: askState.answerMode,
    modelRoute: askState.modelRoute,
    createdAt: askState.createdAt,
    answerCompleted: askState.answerCompleted,
    savedAssetId: askState.savedAssetId,
    messages: askState.messages.slice(-MAX_CONVERSATION_MESSAGES),
  };
}

function syncActiveConversation() {
  const snapshot = activeConversationSnapshot();
  const existingIndex = askState.sessions.findIndex((session) => session?.id === snapshot.id);
  if (existingIndex >= 0) askState.sessions[existingIndex] = snapshot;
  else askState.sessions.push(snapshot);
  askState.sessions = askState.sessions.slice(-MAX_CONVERSATION_SESSIONS);
}

function resetAskStateForKnowledgeUpdate() {
  askState.sessions = [];
  askState.conversationId = createConversationId();
  askState.resetToken = createConversationId();
  resetActiveConversationFields();
  syncActiveConversation();
}

function startNewConversation() {
  if (askRequestInFlight) return;
  syncActiveConversation();
  askState.conversationId = createConversationId();
  askState.resetToken = createConversationId();
  resetActiveConversationFields();
  syncActiveConversation();
  const box = document.getElementById("conversation");
  if (box) box.innerHTML = "";
  const exportBar = document.getElementById("export-bar");
  if (exportBar) exportBar.style.display = "none";
  updateAnswerOperationState();
  publishEmbeddedSnapshot();
}

function currentEmbeddedRoute() {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`;
}

function notifyKnowledgeUpdated(action) {
  resetAskStateForKnowledgeUpdate();
  publishEmbeddedSnapshot();
  if (window.parent === window) return;
  window.parent.postMessage({ type: "agent06:knowledge-updated", action }, window.location.origin);
}

function collectEmbeddedState() {
  syncActiveConversation();
  return {
    route: currentEmbeddedRoute(),
    textInput: document.getElementById("text-input")?.value || "",
    textFeedback: document.getElementById("text-feedback")?.textContent || "",
    fileFeedback: document.getElementById("file-feedback")?.textContent || "",
    questionInput: document.getElementById("question-input")?.value || "",
    language: document.querySelector('input[name="language"]:checked')?.value || "",
    ask: {
      conversationId: askState.conversationId,
      resetToken: askState.resetToken,
      sessions: askState.sessions,
      question: askState.question,
      language: askState.language,
      answer: askState.answer,
      sources: askState.sources,
      sourceStatus: askState.sourceStatus,
      evidence: askState.evidence,
      answerMode: askState.answerMode,
      modelRoute: askState.modelRoute,
      createdAt: askState.createdAt,
      answerCompleted: askState.answerCompleted,
      savedAssetId: askState.savedAssetId,
      messages: askState.messages,
    },
    settingsFeedback: document.getElementById("settings-feedback")?.textContent || "",
    clearFeedback: document.getElementById("clear-feedback")?.textContent || "",
  };
}

function publishEmbeddedSnapshot() {
  if (window.parent === window) return;
  window.parent.postMessage(
    {
      type: "web-publishing:embedded-state:snapshot",
      agentId: "agent06",
      payload: collectEmbeddedState(),
    },
    window.location.origin,
  );
}

function restoreEmbeddedState(state) {
  if (!state || typeof state !== "object") return;
  const textInput = document.getElementById("text-input");
  if (textInput && typeof state.textInput === "string") textInput.value = state.textInput;
  const questionInput = document.getElementById("question-input");
  if (questionInput && typeof state.questionInput === "string") questionInput.value = state.questionInput;
  const languageInput = state.language
    ? document.querySelector(`input[name="language"][value="${CSS.escape(state.language)}"]`)
    : null;
  if (languageInput) languageInput.checked = true;
  restoreAskConversation(state.ask);
  const feedbackIds = ["text-feedback", "file-feedback", "settings-feedback", "clear-feedback"];
  const stateKeys = ["textFeedback", "fileFeedback", "settingsFeedback", "clearFeedback"];
  feedbackIds.forEach((id, index) => {
    const node = document.getElementById(id);
    const value = state[stateKeys[index]];
    if (id === "file-feedback" && isStaleUploadFailure(value)) return;
    if (node && typeof value === "string" && (value || !node.textContent)) node.textContent = value;
  });
}

function setupEmbeddedStateBridge() {
  window.addEventListener("message", (event) => {
    if (event.origin !== window.location.origin) return;
    const data = event.data || {};
    if (data.agentId && data.agentId !== "agent06") return;
    if (data.type === "web-publishing:embedded-state:restore") {
      restoreEmbeddedState(data.payload);
      publishEmbeddedSnapshot();
    }
    if (data.type === "web-publishing:embedded-state:request-snapshot") {
      publishEmbeddedSnapshot();
    }
  });

  document.addEventListener("input", (event) => {
    if (event.target?.matches?.("#text-input, #question-input, input[name='language']")) {
      publishEmbeddedSnapshot();
    }
  });
  document.addEventListener("change", (event) => {
    if (event.target?.matches?.("input[name='language']")) {
      publishEmbeddedSnapshot();
    }
  });
}

function setFeedback(id, value) {
  const node = document.getElementById(id);
  if (node) {
    node.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
    publishEmbeddedSnapshot();
  }
}

function formatIngestFeedback(result, actionLabel) {
  if (!result) return `${actionLabel}失败。`;
  if (["duplicate", "duplicate_pending"].includes(result.status)) {
    return result.message || `${actionLabel}检测到完全相同的内容，未重复录入。`;
  }
  if (result.status === "accepted") {
    return `${actionLabel}已提交 · ${qualityStatusMessage(result) || "后台 OCR 排队中"}`;
  }
  if (result.status === "skipped") {
    return `${actionLabel}未入库 · ${qualityStatusMessage(result) || "需 OCR 未入库"}`;
  }
  if (result.status === "review_required") {
    return result.message || `${actionLabel}需要确认质量后再入库。`;
  }
  if (result.status === "version_conflict") {
    return result.message || `${actionLabel}检测到同名资料的不同版本，请选择处理方式。`;
  }
  if (result.status !== "ok") return `${actionLabel}失败。`;
  const parts = [`${actionLabel}完成`];
  if (typeof result.chunks === "number") parts.push(`${result.chunks} 个片段`);
  if (result.source_name) parts.push(`来源：${result.source_name}`);
  const qualityMessage = qualityStatusMessage(result);
  if (qualityMessage) parts.push(qualityMessage);
  return parts.join(" · ");
}

function qualityStatusMessage(result) {
  const quality = result?.quality || {};
  const action = quality.action;
  if (action === "too_large_skipped") return "文件过大，未入库";
  if ((action === "direct" || action === "cleaned") && quality.status === "low") return "全文入库，低信度";
  if (action === "direct" || action === "cleaned") return "全文入库";
  if (action === "low_indexed") return "低质量入库";
  if (action === "image_ocr") return "图片 OCR 入库";
  if (action === "image_ocr_low") return "图片 OCR 低信度入库";
  if (action === "ocr") {
    if (quality.ocr_partial) {
      const processed = Number(quality.ocr_pages_processed) || 0;
      const total = Number(quality.source_page_count) || 0;
      const pageText =
        processed && total
          ? `仅 OCR 前 ${processed} 页 / 共 ${total} 页`
          : processed
            ? `仅 OCR 前 ${processed} 页`
            : "仅完成部分页面 OCR";
      return `OCR 部分入库 · ${pageText}`;
    }
    return "OCR 入库";
  }
  if (action === "needs_ocr_queued") return "已进入后台 OCR 队列 · 未进入主知识库";
  if (action === "needs_ocr_skipped") return "未入库，需 OCR · 未进入主知识库，避免污染检索";
  if (action === "ocr_failed_skipped") return "OCR 失败未入库 · 未进入主知识库，避免污染检索";
  if (action === "ocr_timeout_skipped") return "OCR 超时未入库 · 未进入主知识库，避免污染检索";
  if (result?.status === "accepted" || result?.status === "queued") return "后台 OCR 排队中 · 未进入主知识库";
  if (result?.status === "processing") return "后台 OCR 处理中 · 未进入主知识库";
  if (result?.status === "duplicate_pending") return "检测到完全相同的资料正在处理 · 未创建重复任务";
  if (result?.status === "duplicate") return "检测到完全相同的资料 · 未重复录入";
  if (result?.status === "failed") return "后台 OCR 失败 · 未进入主知识库";
  return "";
}

function qualityBadge(result) {
  if (["duplicate", "duplicate_pending"].includes(result?.status)) {
    return { className: "quality-blocked", text: "重复未录入" };
  }
  if (result?.quality?.action === "too_large_skipped") {
    return { className: "quality-blocked", text: "文件过大，未入库" };
  }
  if (result?.status === "error") return { className: "quality-failed", text: "解析失败" };
  if (result?.status === "failed") return { className: "quality-failed", text: "OCR 失败" };
  const quality = result?.quality || {};
  const action = quality.action;
  if (action === "needs_ocr_queued" || ["accepted", "queued", "processing"].includes(result?.status)) {
    return { className: "quality-ocr", text: "后台 OCR" };
  }
  if ((action === "direct" || action === "cleaned") && quality.status === "high") {
    return { className: "quality-full", text: "全文入库" };
  }
  if ((action === "direct" || action === "cleaned") && quality.status === "low") {
    return { className: "quality-full-low", text: "全文入库，低信度" };
  }
  if (action === "ocr" && quality.ocr_partial) {
    const processed = Number(quality.ocr_pages_processed) || 0;
    return { className: "quality-ocr-partial", text: processed ? `OCR 部分入库（前 ${processed} 页）` : "OCR 部分入库" };
  }
  if (action === "ocr") return { className: "quality-ocr", text: "OCR 入库" };
  if (action === "image_ocr") return { className: "quality-ocr", text: "图片 OCR 入库" };
  if (action === "image_ocr_low") return { className: "quality-low", text: "图片 OCR 低信度" };
  if (action === "low_indexed" && quality.status === "low") {
    return { className: "quality-low", text: "低质量入库" };
  }
  if (["needs_ocr_skipped", "ocr_failed_skipped", "ocr_timeout_skipped"].includes(action)) {
    return { className: "quality-blocked", text: "未入库，需 OCR" };
  }
  return null;
}

function orgChartBadge(result) {
  const quality = result?.quality || {};
  if (Number(quality.org_chart_chunks) > 0 || quality.org_chart_mode === "pdf_layout_fallback") {
    return { className: "quality-org-chart", text: "Org Chart" };
  }
  return null;
}

function formatQualityPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "";
  return `${Math.round(number * 100)}%`;
}

function qualityDetails(result) {
  const quality = result?.quality || {};
  const rows = [];
  const reasons = Array.isArray(quality.reasons) && quality.reasons.length ? quality.reasons : ["无额外原因"];
  rows.push({ label: "原因", value: reasons.join("；") });
  const validRatio = formatQualityPercent(quality.valid_ratio);
  if (validRatio) rows.push({ label: "有效文本占比", value: validRatio });
  if (Number.isFinite(Number(quality.effective_chars_per_page))) {
    rows.push({ label: "每页有效字符", value: String(Math.round(Number(quality.effective_chars_per_page))) });
  }
  if (quality.ocr_provider) rows.push({ label: "OCR 服务", value: String(quality.ocr_provider) });
  return rows;
}

function hasRawFilePath(item) {
  return !!item?.raw_file_path;
}

function rawFileHref(result) {
  if (!hasRawFilePath(result)) return "";
  return `api/files/${result.raw_file_path.split("/").map(encodeURIComponent).join("/")}`;
}

function formatErrorFeedback(actionLabel, error) {
  return `${actionLabel}失败：${humanizeErrorMessage(error)}`;
}

function humanizeErrorMessage(error) {
  const raw = error?.message || String(error);
  try {
    const parsed = JSON.parse(raw);
    const upload413 = formatUpload413Error(parsed);
    if (upload413) return upload413;
    const detail = parsed?.detail;
    if (detail === "Not Found") return "接口未找到，请刷新后重试";
    if (Array.isArray(detail)) {
      if (detail.some((item) => item?.loc?.includes?.("files") && item?.type === "missing")) {
        return "未收到文件，请重新选择后上传";
      }
      return detail.map((item) => item?.msg).filter(Boolean).join("；") || raw;
    }
    if (typeof detail === "string") return detail;
  } catch {
    // Keep the original message when it is not a JSON API error.
  }
  if (raw === "Not Found") return "接口未找到，请刷新后重试";
  return raw;
}

function formatUpload413Error(errResponse) {
  const detail = errResponse?.detail;
  if (detail?.quality?.action === "too_large_skipped" || detail?.action === "too_large_skipped") {
    const chunks = detail?.chunks;
    const limit = detail?.limit;
    if (Number.isFinite(Number(chunks)) && Number.isFinite(Number(limit))) {
      return `文件过大，未入库：解析产生 ${chunks} 个片段，超过当前同步入库上限 ${limit}，已取消入库。`;
    }
    return detail?.reason || "文件过大，未入库。";
  }
  return "";
}

function isStaleUploadFailure(value) {
  return typeof value === "string" && value.startsWith("上传失败");
}

function formatBytes(size) {
  if (!Number.isFinite(size) || size <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(size) / Math.log(1024)), units.length - 1);
  const value = size / Math.pow(1024, index);
  return `${value.toFixed(value >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

function fileTypeLabel(file) {
  const extension = String(file.name || "").split(".").pop();
  if (file.type?.startsWith?.("image/")) return "IMG";
  if (["png", "jpg", "jpeg", "webp"].includes(extension.toLowerCase())) return "IMG";
  if (extension && extension !== file.name) return extension.toUpperCase();
  return (file.type || "FILE").split("/").pop().toUpperCase();
}

function uploadSlotStatus(result) {
  if (!result) return "pending";
  if (result.status === "error") return "error";
  if (result.status === "failed") return "error";
  if (result.status === "accepted") return "queued";
  if (result.status === "queued") return "queued";
  if (result.status === "processing") return "processing";
  if (result.status === "completed") return "complete";
  if (result.status === "skipped") return "skipped";
  if (result.status === "duplicate" || result.status === "duplicate_pending") return "skipped";
  if (result.status === "review_required" || result.status === "version_conflict") return "skipped";
  return "complete";
}

async function uploadFileWithPolicies(slotIndex, policies = {}) {
  const file = selectedFiles[slotIndex];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  form.append("org_chart_mode", slotIndex === ORG_CHART_SLOT_INDEX ? "enabled" : "disabled");
  if (policies.quality_policy) form.append("quality_policy", policies.quality_policy);
  if (policies.version_policy) form.append("version_policy", policies.version_policy);
  setFeedback("file-feedback", `正在处理 ${file.name}…`);
  try {
    const response = await fetch("api/ingest/file", { method: "POST", body: form });
    if (!response.ok) throw new Error(await response.text());
    const result = await response.json();
    fileUploadResults[slotIndex] = { filename: file.name, ...result };
    renderUploadSlots();
    setFeedback("file-feedback", formatIngestFeedback(result, "上传"));
    if (result.status === "ok") {
      notifyKnowledgeUpdated("ingest:file:decision");
      await loadIngestSources();
    }
    startUploadTaskPolling([fileUploadResults[slotIndex]]);
    publishEmbeddedSnapshot();
  } catch (error) {
    setFeedback("file-feedback", formatErrorFeedback("上传", error));
  }
}

async function deleteIngestSource(sourceId, successMessage = "资料已删除。") {
  const response = await fetch(`api/ingest/sources/${encodeURIComponent(sourceId)}`, { method: "DELETE" });
  if (!response.ok) throw new Error(await response.text());
  await loadIngestSources();
  setFeedback("file-feedback", successMessage);
  notifyKnowledgeUpdated("ingest:source:delete");
}

function appendUploadDecisionActions(row, result, slotIndex) {
  if (!result) return;
  const actions = document.createElement("div");
  actions.className = "upload-decision-actions";
  const addAction = (label, handler, primary = false) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    if (primary) button.className = "is-primary";
    button.addEventListener("click", handler);
    actions.appendChild(button);
  };
  if (result.status === "review_required") {
    addAction("仍然入库", () => uploadFileWithPolicies(slotIndex, { quality_policy: "accept" }), true);
    addAction("取消", () => {
      fileUploadResults[slotIndex] = null;
      renderUploadSlots();
    });
  } else if (result.status === "version_conflict") {
    addAction("替换旧版本", () => uploadFileWithPolicies(slotIndex, { version_policy: "replace" }), true);
    addAction("同时保留", () => uploadFileWithPolicies(slotIndex, { version_policy: "keep" }));
    addAction("取消", () => {
      fileUploadResults[slotIndex] = null;
      renderUploadSlots();
    });
  } else if (["ok", "completed"].includes(result.status) && result.source_id) {
    addAction("撤销本次录入", async () => {
      try {
        await deleteIngestSource(result.source_id, `已撤销 ${result.filename || selectedFiles[slotIndex]?.name || "本次录入"}。`);
        fileUploadResults[slotIndex] = null;
        renderUploadSlots();
      } catch (error) {
        setFeedback("file-feedback", formatErrorFeedback("撤销", error));
      }
    });
  }
  if (actions.childElementCount) row.appendChild(actions);
}

async function loadIngestSources() {
  const list = document.getElementById("ingest-source-list");
  if (!list) return;
  try {
    const response = await fetch("api/ingest/sources");
    if (!response.ok) throw new Error(await response.text());
    const result = await response.json();
    list.textContent = "";
    if (!result.sources?.length) {
      list.textContent = "暂无已录入资料。";
      return;
    }
    for (const source of result.sources) {
      const row = document.createElement("div");
      row.className = "source-row";
      const info = document.createElement("div");
      const name = document.createElement("div");
      name.className = "source-row-name";
      name.textContent = source.original_name || source.source_name;
      name.title = name.textContent;
      const meta = document.createElement("div");
      meta.className = "source-row-meta";
      meta.textContent = `${source.chunk_count || 0} 个片段 · ${source.created_at || "时间未知"}`;
      info.append(name, meta);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "删除资料";
      remove.addEventListener("click", async () => {
        remove.disabled = true;
        try {
          await deleteIngestSource(source.source_id, `已删除 ${name.textContent}。`);
        } catch (error) {
          remove.disabled = false;
          setFeedback("file-feedback", formatErrorFeedback("删除", error));
        }
      });
      row.append(info, remove);
      list.appendChild(row);
    }
  } catch (error) {
    list.textContent = `资料列表读取失败：${humanizeErrorMessage(error)}`;
  }
}

function selectedFileEntries() {
  return selectedFiles
    .map((file, slotIndex) => ({ file, slotIndex }))
    .filter((entry) => !!entry.file);
}

function selectedFileCount() {
  return selectedFileEntries().length;
}

function nextEmptyUploadSlot(startIndex = 0) {
  for (let offset = 0; offset < MAX_UPLOAD_FILES; offset += 1) {
    const index = (startIndex + offset) % MAX_UPLOAD_FILES;
    if (!selectedFiles[index]) return index;
  }
  return -1;
}

function addFilesToUploadSlots(files, preferredSlotIndex = null) {
  let nextStart = Number.isInteger(preferredSlotIndex) ? preferredSlotIndex : 0;
  const accepted = [];
  for (const file of files) {
    const targetIndex = nextEmptyUploadSlot(nextStart);
    if (targetIndex < 0) break;
    selectedFiles[targetIndex] = file;
    accepted.push(file);
    nextStart = targetIndex + 1;
  }
  return accepted;
}

function renderQualityBadge(row, result, fileKey) {
  const badge = qualityBadge(result);
  const chartBadge = orgChartBadge(result);
  const href = rawFileHref(result);
  if (!badge && !chartBadge && !href) return;

  const qualityRow = document.createElement("div");
  qualityRow.className = "upload-quality-row";
  if (badge) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `quality-badge ${badge.className}`;
    button.textContent = badge.text;
    button.setAttribute("aria-expanded", expandedQualityFiles.has(fileKey) ? "true" : "false");
    button.addEventListener("click", () => {
      if (expandedQualityFiles.has(fileKey)) {
        expandedQualityFiles.delete(fileKey);
      } else {
        expandedQualityFiles.add(fileKey);
      }
      renderUploadSlots();
      publishEmbeddedSnapshot();
    });
    qualityRow.appendChild(button);
  }
  if (chartBadge) {
    const marker = document.createElement("span");
    marker.className = `quality-badge ${chartBadge.className}`;
    marker.textContent = chartBadge.text;
    qualityRow.appendChild(marker);
  }
  if (href) {
    const link = document.createElement("a");
    link.className = "upload-raw-link";
    link.href = href;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = "查看原文件";
    qualityRow.appendChild(link);
  }
  row.appendChild(qualityRow);

  if (badge && expandedQualityFiles.has(fileKey)) {
    const detail = document.createElement("dl");
    detail.className = "upload-quality-detail";
    for (const item of qualityDetails(result)) {
      const term = document.createElement("dt");
      term.textContent = item.label;
      const description = document.createElement("dd");
      description.textContent = item.value;
      detail.append(term, description);
    }
    row.appendChild(detail);
  }
}

function summarizeBatchFeedback(result) {
  if (!result || !Array.isArray(result.files)) return "上传失败。";
  const parts = [
    result.status === "partial" ? "部分上传完成" : result.status === "accepted" ? "上传已提交" : "上传完成",
    `${result.succeeded || 0} 个成功`,
    `${result.duplicates || 0} 个重复`,
    `${result.review_required || 0} 个待质量确认`,
    `${result.version_conflicts || 0} 个版本待处理`,
    `${result.accepted || 0} 个后台 OCR`,
    `${result.skipped || 0} 个未入库`,
    `${result.failed || 0} 个失败`,
    `${result.total_chunks || 0} 个片段`,
  ];
  const failed = result.files
    .filter((item) => item.status === "error" || item.status === "failed")
    .map((item) => `${item.filename}：${item.error || item.result?.error || "OCR 失败"}`);
  const skipped = result.files
    .filter((item) => item.status === "skipped")
    .map((item) => `${item.filename}：${qualityStatusMessage(item) || "需 OCR 未入库"}`);
  const accepted = result.files
    .filter((item) => ["accepted", "queued", "processing"].includes(item.status))
    .map((item) => `${item.filename}：${qualityStatusMessage(item) || "后台 OCR 排队中"}`);
  const duplicates = result.files
    .filter((item) => item.status === "duplicate" || item.status === "duplicate_pending")
    .map((item) => `${item.filename}：${item.message || qualityStatusMessage(item) || "完全相同，未重复录入"}`);
  const reviews = result.files
    .filter((item) => item.status === "review_required")
    .map((item) => `${item.filename}：质量或提取完整性需要确认`);
  const conflicts = result.files
    .filter((item) => item.status === "version_conflict")
    .map((item) => `${item.filename}：已有同名不同内容的资料`);
  const detail = duplicates.concat(reviews, conflicts, accepted, skipped, failed);
  return detail.length ? `${parts.join(" · ")}\n${detail.join("\n")}` : parts.join(" · ");
}

function summarizeCurrentUploadFeedback() {
  const files = (fileUploadResults || []).filter(Boolean);
  const succeeded = files.filter((item) => ["ok", "completed"].includes(item.status)).length;
  const accepted = files.filter((item) => ["accepted", "queued", "processing"].includes(item.status)).length;
  const duplicates = files.filter((item) => item.status === "duplicate" || item.status === "duplicate_pending").length;
  const skipped = files.filter((item) => item.status === "skipped").length;
  const reviewRequired = files.filter((item) => item.status === "review_required").length;
  const versionConflicts = files.filter((item) => item.status === "version_conflict").length;
  const failed = files.filter((item) => ["error", "failed"].includes(item.status)).length;
  const totalChunks = files.reduce((sum, item) => sum + (Number(item.chunks) || Number(item.result?.chunks_inserted) || 0), 0);
  return summarizeBatchFeedback({
    status: failed || reviewRequired || versionConflicts ? "partial" : accepted ? "accepted" : "ok",
    succeeded,
    duplicates,
    accepted,
    skipped,
    review_required: reviewRequired,
    version_conflicts: versionConflicts,
    failed,
    total_chunks: totalChunks,
    files,
  });
}

function stopUploadTaskPolling(taskId) {
  const timer = uploadTaskPollTimers.get(taskId);
  if (timer) window.clearTimeout(timer);
  uploadTaskPollTimers.delete(taskId);
}

function stopAllUploadTaskPolling() {
  for (const taskId of uploadTaskPollTimers.keys()) {
    stopUploadTaskPolling(taskId);
  }
}

function mergeUploadTaskResult(current, task) {
  const result = task.result || {};
  const chunks = Number(result.chunks_inserted) || Number(current?.chunks) || 0;
  const quality = {
    ...(current?.quality || {}),
    action: task.status === "completed" ? result.quality_action || "ocr" : current?.quality?.action,
  };
  return {
    ...(current || {}),
    task_id: task.task_id,
    filename: current?.filename || task.file_name,
    file_name: task.file_name,
    raw_file_path: current?.raw_file_path || task.raw_file_path,
    status: task.status,
    progress: Number(task.progress) || 0,
    result,
    source_id: result.source_id || current?.source_id || "",
    coverage: result.coverage || current?.coverage || {},
    raw_file_path: result.raw_file_path || current?.raw_file_path || "",
    chunks,
    quality,
  };
}

async function pollUploadTask(taskId) {
  stopUploadTaskPolling(taskId);
  try {
    const response = await fetch(`api/tasks/${encodeURIComponent(taskId)}`);
    if (!response.ok) throw new Error(await response.text());
    const task = await response.json();
    const index = fileUploadResults.findIndex((item) => item?.task_id === taskId);
    if (index >= 0) {
      fileUploadResults[index] = mergeUploadTaskResult(fileUploadResults[index], task);
      renderUploadSlots();
      setFeedback("file-feedback", summarizeCurrentUploadFeedback());
    }
    if (task.status === "completed") {
      notifyKnowledgeUpdated("ingest:file:ocr");
      publishEmbeddedSnapshot();
      return;
    }
    if (task.status === "failed") {
      publishEmbeddedSnapshot();
      return;
    }
    if (task.status === "review_required") {
      publishEmbeddedSnapshot();
      return;
    }
    uploadTaskPollTimers.set(taskId, window.setTimeout(() => pollUploadTask(taskId), OCR_TASK_POLL_INTERVAL_MS));
  } catch (error) {
    uploadTaskPollTimers.set(taskId, window.setTimeout(() => pollUploadTask(taskId), OCR_TASK_POLL_INTERVAL_MS));
  }
}

function startUploadTaskPolling(results) {
  for (const result of results || []) {
    if (result?.task_id && result.status === "accepted") {
      pollUploadTask(result.task_id);
    }
  }
}

function renderUploadSlots() {
  const list = document.getElementById("file-list");
  const summary = document.getElementById("file-summary");
  const clearButton = document.getElementById("clear-selected-files");
  const fileInput = document.getElementById("file-input");
  if (!list || !summary) return;
  list.textContent = "";
  const count = selectedFileCount();
  if (fileInput) fileInput.disabled = selectedFileCount() >= MAX_UPLOAD_FILES;
  if (!count) {
    summary.textContent = `未选择文件 · 最多 ${MAX_UPLOAD_FILES} 个`;
    if (clearButton) clearButton.hidden = true;
  } else {
    const totalSize = selectedFileEntries().reduce((sum, entry) => sum + entry.file.size, 0);
    summary.textContent = `已选择 ${count} / ${MAX_UPLOAD_FILES} 个文件 · ${formatBytes(totalSize)}`;
    if (clearButton) clearButton.hidden = false;
  }

  for (let index = 0; index < MAX_UPLOAD_FILES; index += 1) {
    const file = selectedFiles[index];
    if (!file) {
      const isOrgChartSlot = index === ORG_CHART_SLOT_INDEX;
      const slot = document.createElement("button");
      slot.type = "button";
      slot.className = `upload-slot is-empty${isOrgChartSlot ? " is-org-chart-slot" : ""}`;
      slot.setAttribute("aria-label", `上传槽 ${index + 1}：${isOrgChartSlot ? "添加 Org Chart 文件" : "添加文件"}`);
      slot.innerHTML = isOrgChartSlot
        ? '<span class="upload-slot-plus">+</span><span class="upload-slot-label">Org Chart</span><span class="upload-slot-meta">组织图专用</span>'
        : '<span class="upload-slot-plus">+</span><span class="upload-slot-label">添加文件</span>';
      slot.addEventListener("click", () => {
        if (selectedFileCount() >= MAX_UPLOAD_FILES) {
          setFeedback("file-feedback", MAX_UPLOAD_FEEDBACK);
          return;
        }
        pendingUploadSlotIndex = index;
        fileInput?.click();
      });
      list.appendChild(slot);
      continue;
    }
    const result = fileUploadResults[index] || null;
    const status = uploadSlotStatus(result);
    const row = document.createElement("div");
    row.className = `upload-slot is-filled is-${status}${index === ORG_CHART_SLOT_INDEX ? " is-org-chart-slot" : ""}`;
    row.setAttribute("aria-label", `上传槽 ${index + 1}：${file.name}`);
    const head = document.createElement("div");
    head.className = "upload-slot-head";
    const type = document.createElement("span");
    type.className = "upload-slot-type";
    type.textContent = fileTypeLabel(file);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "upload-slot-remove";
    remove.textContent = "移除";
    remove.addEventListener("click", () => {
      const removedResult = fileUploadResults[index];
      if (removedResult?.task_id) stopUploadTaskPolling(removedResult.task_id);
      selectedFiles[index] = null;
      fileUploadResults[index] = null;
      expandedQualityFiles.delete(file.name);
      renderUploadSlots();
      publishEmbeddedSnapshot();
    });
    head.append(type, remove);
    const name = document.createElement("span");
    name.className = "upload-slot-name";
    name.textContent = file.name;
    name.title = file.name;
    const meta = document.createElement("span");
    meta.className = "upload-slot-meta";
    meta.textContent =
      status === "error"
        ? result?.status === "failed"
          ? "OCR 失败"
          : "失败"
        : status === "queued"
          ? "等待 OCR"
          : status === "processing"
            ? "OCR 处理中"
            : status === "skipped"
              ? ["duplicate", "duplicate_pending"].includes(result?.status)
                ? "重复未录入"
                : "未入库"
              : status === "complete" && result
                ? `${result.chunks || 0} 个片段`
                : formatBytes(file.size);
    meta.title = meta.textContent;
    row.append(head, name, meta);
    renderQualityBadge(row, result, result?.raw_file_path || file.name);
    appendUploadDecisionActions(row, result, index);
    list.appendChild(row);
  }
}

const renderSelectedFiles = renderUploadSlots;

function setupIngest() {
  const textForm = document.getElementById("text-form");
  const fileForm = document.getElementById("file-form");
  const fileInput = document.getElementById("file-input");
  const clearSelectedFiles = document.getElementById("clear-selected-files");
  const refreshIngestSources = document.getElementById("refresh-ingest-sources");
  refreshIngestSources?.addEventListener("click", (event) => {
    event.preventDefault();
    loadIngestSources();
  });
  loadIngestSources();
  textForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const textInput = document.getElementById("text-input");
    const text = textInput.value;
    try {
      setFeedback("text-feedback", "录入中...");
      const result = await postJSON("api/ingest/text", { text });
      textInput.value = "";
      setFeedback("text-feedback", formatIngestFeedback(result, "录入"));
      notifyKnowledgeUpdated("ingest:text");
      publishEmbeddedSnapshot();
    } catch (error) {
      setFeedback("text-feedback", formatErrorFeedback("录入", error));
    }
  });
  fileInput?.addEventListener("change", () => {
    const incomingFiles = Array.from(fileInput.files || []);
    const remainingSlots = MAX_UPLOAD_FILES - selectedFileCount();
    const acceptedFiles = incomingFiles.slice(0, Math.max(remainingSlots, 0));
    if (incomingFiles.length > acceptedFiles.length) {
      setFeedback("file-feedback", MAX_UPLOAD_FEEDBACK);
    } else {
      setFeedback("file-feedback", "");
    }
    if (acceptedFiles.length) {
      addFilesToUploadSlots(acceptedFiles, pendingUploadSlotIndex);
      fileUploadResults = [];
      expandedQualityFiles = new Set();
      stopAllUploadTaskPolling();
    }
    pendingUploadSlotIndex = null;
    fileInput.value = "";
    renderUploadSlots();
    publishEmbeddedSnapshot();
  });
  clearSelectedFiles?.addEventListener("click", () => {
    selectedFiles = [];
    fileUploadResults = [];
    expandedQualityFiles = new Set();
    stopAllUploadTaskPolling();
    renderUploadSlots();
    setFeedback("file-feedback", "");
    publishEmbeddedSnapshot();
  });
  renderUploadSlots();
  fileForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const uploadEntries = selectedFileEntries();
    if (!uploadEntries.length) {
      setFeedback("file-feedback", "请选择文件。");
      return;
    }
    const form = new FormData();
    uploadEntries.forEach((entry) => {
      form.append("files", entry.file);
      form.append("org_chart_modes", entry.slotIndex === ORG_CHART_SLOT_INDEX ? "enabled" : "disabled");
    });
    try {
      setFeedback("file-feedback", `上传中... ${uploadEntries.length} 个文件`);
      const response = await fetch("api/ingest/files", { method: "POST", body: form });
      if (!response.ok) throw new Error(await response.text());
      const result = await response.json();
      const nextResults = new Array(MAX_UPLOAD_FILES).fill(null);
      (result.files || []).forEach((item, uploadIndex) => {
        const slotIndex = uploadEntries[uploadIndex]?.slotIndex;
        if (Number.isInteger(slotIndex)) nextResults[slotIndex] = item;
      });
      fileUploadResults = nextResults;
      setFeedback("file-feedback", summarizeBatchFeedback(result));
      renderUploadSlots();
      if ((result.succeeded || 0) > 0 || (result.total_chunks || 0) > 0) notifyKnowledgeUpdated("ingest:file");
      if ((result.succeeded || 0) > 0 || (result.total_chunks || 0) > 0) loadIngestSources();
      startUploadTaskPolling(fileUploadResults.filter(Boolean));
      publishEmbeddedSnapshot();
    } catch (error) {
      setFeedback("file-feedback", formatErrorFeedback("上传", error));
    }
  });
}

function appendMessage(text, role, options = {}) {
  const box = document.getElementById("conversation");
  const node = document.createElement("div");
  node.className = `ask-message ${role}`;
  node.textContent = text;
  box.appendChild(node);
  if (!options.skipState) {
    const message = { role, text, sources: [] };
    askState.messages.push(message);
    if (askState.messages.length > MAX_CONVERSATION_MESSAGES) {
      askState.messages.shift();
      box.querySelector(".ask-message")?.remove();
    }
    box.querySelectorAll(".ask-message").forEach((messageNode, index) => {
      messageNode.dataset.messageIndex = String(index);
    });
    node.dataset.messageIndex = String(askState.messages.length - 1);
  }
  box.scrollTop = box.scrollHeight;
  return node;
}

function appendSources(answer, displaySources) {
  const sources = document.createElement("div");
  sources.className = "ask-sources";
  const title = document.createElement("div");
  title.className = "ask-sources-title";
  title.textContent = "参考来源";
  sources.appendChild(title);
  for (const source of displaySources) {
    const item = document.createElement("div");
    item.className = "ask-source-chip";
    const badge = sourceTypeBadge(source);
    if (badge) {
      const marker = document.createElement("span");
      marker.className = `source-type-badge ${badge.className}`;
      marker.textContent = badge.text;
      item.appendChild(marker);
    }
    const link = document.createElement("a");
    link.href = sourceHref(source);
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = formatSourceLabel(source);
    link.title = hasRawFilePath(source) ? "打开原始附件" : "打开来源片段";
    item.appendChild(link);
    sources.appendChild(item);
  }
  answer.appendChild(sources);
}

function appendSourceNotice(answer, text) {
  const sources = document.createElement("div");
  sources.className = "ask-sources ask-source-notice";
  sources.textContent = text;
  answer.appendChild(sources);
}

function normalizeAskMessages(messages) {
  return (Array.isArray(messages) ? messages : [])
    .filter((message) => message && typeof message.text === "string")
    .map((message) => ({
      role: message.role === "user" ? "user" : "assistant",
      text: message.text,
      sources: Array.isArray(message.sources) ? message.sources : [],
      sourceStatus: typeof message.sourceStatus === "string" ? message.sourceStatus : "",
    }))
    .slice(-MAX_CONVERSATION_MESSAGES);
}

function applyConversation(session) {
  askState.conversationId = typeof session.id === "string" && session.id ? session.id : createConversationId();
  askState.resetToken = typeof session.resetToken === "string" ? session.resetToken : "";
  askState.question = typeof session.question === "string" ? session.question : "";
  askState.language = typeof session.language === "string" ? session.language : askState.language;
  askState.answer = typeof session.answer === "string" ? session.answer : "";
  askState.sources = Array.isArray(session.sources) ? session.sources : [];
  askState.sourceStatus = typeof session.sourceStatus === "string" ? session.sourceStatus : "";
  askState.evidence = session.evidence && typeof session.evidence === "object" ? session.evidence : {};
  askState.answerMode = typeof session.answerMode === "string" ? session.answerMode : "answer";
  askState.modelRoute = typeof session.modelRoute === "string" ? session.modelRoute : "";
  askState.createdAt = typeof session.createdAt === "string" ? session.createdAt : "";
  askState.answerCompleted = session.answerCompleted === true;
  askState.savedAssetId = typeof session.savedAssetId === "string" ? session.savedAssetId : "";
  askState.messages = normalizeAskMessages(session.messages);
}

function restoreAskConversation(state) {
  const box = document.getElementById("conversation");
  if (!box || !state || typeof state !== "object") return;
  const sessionId = typeof state.conversationId === "string" ? state.conversationId : "";
  const sessions = (Array.isArray(state.sessions) ? state.sessions : [])
    .filter((session) => session && typeof session === "object")
    .slice(-MAX_CONVERSATION_SESSIONS);
  const legacySession = { ...state, id: sessionId || createConversationId() };
  const activeSession = sessions.find((session) => session.id === sessionId) || legacySession;
  askState.sessions = sessions.length ? sessions : [legacySession];
  applyConversation(activeSession);
  syncActiveConversation();
  box.innerHTML = "";
  if (!askState.messages.length) {
    updateAnswerOperationState();
    return;
  }
  askState.messages.forEach((message, index) => {
    const node = appendMessage(message.text, message.role, { skipState: true });
    node.dataset.messageIndex = String(index);
    if (message.role === "assistant" && ["no_answer", "clarification_required"].includes(message.sourceStatus)) {
      appendSourceNotice(node, "知识库缺失，未使用参考来源");
    } else if (message.role === "assistant" && message.sources.length) {
      appendSources(node, normalizeSourceList(message.sources));
    }
  });
  const exportBar = document.getElementById("export-bar");
  if (exportBar) exportBar.style.display = askState.question && askState.answer ? "flex" : "none";
  updateAnswerOperationState();
  box.scrollTop = box.scrollHeight;
}

function normalizeSourceList(sources) {
  const seen = new Set();
  const displaySources = [];
  for (const source of sources || []) {
    const key = hasRawFilePath(source) ? `file:${source.raw_file_path}` : `source:${source.source_name}`;
    if (seen.has(key)) continue;
    seen.add(key);
    displaySources.push(source);
  }
  return displaySources.slice(0, 5);
}

function formatSourceLabel(source) {
  if (hasRawFilePath(source)) {
    const parts = source.raw_file_path.split("/");
    return parts[parts.length - 1] || source.source_name;
  }
  const match = String(source.source_name || "").match(/^manual_(\d{8})_(\d{6})$/);
  if (match) {
    const time = match[2];
    return `手动录入 ${time.slice(0, 2)}:${time.slice(2, 4)}`;
  }
  return source.source_name || "来源片段";
}

function sourceTypeBadge(source) {
  source = source || {};
  const sourceType = String(source.source_type || "").toLowerCase();
  if (sourceType === "org_chart") return { className: "source-type-org-chart", text: "Org Chart" };
  if (sourceType === "pdf") return { className: "source-type-pdf", text: "PDF" };
  if (sourceType === "text") return { className: "source-type-text", text: "Text" };
  if (sourceType) return { className: "source-type-generic", text: sourceType.toUpperCase() };
  return { className: "source-type-generic", text: "Source" };
}

function sourceHref(source) {
  if (hasRawFilePath(source)) {
    return `api/files/${source.raw_file_path.split("/").map(encodeURIComponent).join("/")}`;
  }
  return `api/sources?chunk_id=${encodeURIComponent(source.chunk_id)}`;
}

function buildAnswerResultSnapshot() {
  const answerMode = askState.answerMode || askState.evidence?.answer_mode?.mode || "answer";
  return {
    question: askState.question,
    answer: askState.answer,
    sources: askState.sources,
    source_status: askState.sourceStatus || "grounded",
    evidence: askState.evidence,
    language: askState.language || "zh",
    answer_mode: answerMode,
    model_route: askState.modelRoute || (askState.language === "en" ? "dual" : "deepseek"),
    created_at: askState.createdAt || new Date().toISOString(),
    title: askState.question,
  };
}

function updateAnswerOperationState() {
  const answerCompleted = askState.answerCompleted === true;
  const pkaEligible = answerCompleted && !["no_answer", "clarification_required", "generated_only"].includes(askState.sourceStatus);
  const localButton = document.getElementById("save-local-asset");
  const obsidianButton = document.getElementById("publish-obsidian");
  const pkaButton = document.getElementById("add-pka-retrieval");
  if (localButton) localButton.disabled = !answerCompleted;
  if (obsidianButton) obsidianButton.disabled = !answerCompleted;
  if (pkaButton) pkaButton.disabled = !pkaEligible;
}

function formatAnswerOperationFeedback(operation, result) {
  if (operation === "local") return "本地资料已保存";
  if (operation === "obsidian") {
    if (result.publication_status === "pending_obsidian") return "本地已保存，Obsidian 待发布";
    if (result.publication_status === "published") return "已发布到 Obsidian";
  }
  if (operation === "pka") {
    if (result.index_status === "quarantined") return "PKA 索引已隔离，未发布到 Agent10";
    if (result.index_status === "indexed" && result.publication_status === "pending_agent10") return "PKA 已索引，待 Agent10 发布";
    if (result.index_status === "indexed" && result.publication_status === "published") return "已加入 PKA 问答检索";
  }
  return "操作完成";
}

async function runAnswerOperation(operation, request) {
  try {
    const result = await request();
    askState.savedAssetId = result.asset_id || result.local_asset?.asset_id || askState.savedAssetId;
    setFeedback("answer-operation-feedback", formatAnswerOperationFeedback(operation, result));
    publishEmbeddedSnapshot();
  } catch (error) {
    setFeedback("answer-operation-feedback", formatErrorFeedback("操作", error));
  }
}

async function saveAnswerAssetLocal() {
  await runAnswerOperation("local", () => postJSON("api/answer-assets/save-local", buildAnswerResultSnapshot()));
}

async function publishAnswerAssetToObsidian() {
  await runAnswerOperation("obsidian", () => postJSON("api/answer-assets/publish-obsidian", buildAnswerResultSnapshot()));
}

async function addAnswerAssetToPkaRetrieval() {
  await runAnswerOperation("pka", () => postJSON("api/answer-assets/add-pka-retrieval", buildAnswerResultSnapshot()));
}

function setupAsk() {
  const form = document.getElementById("query-form");
  const sendButton = form?.querySelector('button[type="submit"]');
  const newConversationButton = document.getElementById("new-conversation");
  const chips = document.querySelectorAll(".empty-chip");
  chips.forEach((chip) => {
    chip.addEventListener("click", () => {
      document.getElementById("question-input").value = chip.textContent;
      document.getElementById("query-form").requestSubmit();
    });
  });
  document.getElementById("export-word")?.addEventListener("click", () => exportAnswer("word"));
  document.getElementById("save-local-asset")?.addEventListener("click", saveAnswerAssetLocal);
  document.getElementById("publish-obsidian")?.addEventListener("click", publishAnswerAssetToObsidian);
  document.getElementById("add-pka-retrieval")?.addEventListener("click", addAnswerAssetToPkaRetrieval);
  document.getElementById("new-conversation")?.addEventListener("click", startNewConversation);
  ensureActiveConversation();
  syncActiveConversation();
  updateAnswerOperationState();
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (askRequestInFlight) return;
    const input = document.getElementById("question-input");
    const question = input.value.trim();
    const language = document.querySelector('input[name="language"]:checked')?.value || "zh";
    if (!question) return;
    const previousQuestion = [...askState.messages].reverse().find((message) => message.role === "user")?.text || "";
    askRequestInFlight = true;
    if (sendButton) sendButton.disabled = true;
    if (newConversationButton) newConversationButton.disabled = true;
    appendMessage(question, "user");
    askState.question = question;
    askState.language = language;
    askState.answer = "";
    askState.sources = [];
    askState.sourceStatus = "";
    askState.evidence = {};
    askState.answerMode = "answer";
    askState.modelRoute = language === "en" ? "dual" : "deepseek";
    askState.createdAt = "";
    askState.answerCompleted = false;
    setFeedback("answer-operation-feedback", "");
    updateAnswerOperationState();
    input.value = "";
    const exportBar = document.getElementById("export-bar");
    if (exportBar) exportBar.style.display = "none";
    const answer = appendMessage("", "assistant");
    const messageIndex = Number(answer.dataset.messageIndex);
    const pendingText = "检索中...";
    answer.dataset.pending = "true";
    answer.textContent = pendingText;
    publishEmbeddedSnapshot();
    try {
      const response = await fetch("api/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          language,
          conversation_id: askState.conversationId,
          previous_question: previousQuestion,
        }),
      });
      if (!response.ok) throw new Error(await response.text());
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop();
        for (const raw of events) {
          if (!raw.startsWith("data: ")) continue;
          const payload = JSON.parse(raw.slice(6));
          if (payload.type === "token") {
            const empty = document.getElementById("empty-state");
            if (empty) empty.remove();
            if (answer.dataset.pending === "true") {
              answer.textContent = "";
              delete answer.dataset.pending;
            }
            answer.textContent += payload.content;
            askState.answer += payload.content;
            askState.messages[messageIndex].text = askState.answer;
            document.getElementById("conversation").scrollTop = document.getElementById("conversation").scrollHeight;
            publishEmbeddedSnapshot();
          }
          if (payload.type === "error") {
            if (answer.dataset.pending === "true") {
              answer.textContent = "";
              delete answer.dataset.pending;
            }
            answer.textContent += `\n${payload.content}`;
            askState.messages[messageIndex].text = answer.textContent;
            publishEmbeddedSnapshot();
          }
          if (payload.type === "sources") {
            const sourceStatus = payload.source_status || "grounded";
            askState.sourceStatus = sourceStatus;
            askState.sources = ["no_answer", "clarification_required"].includes(sourceStatus) ? [] : payload.sources;
            askState.evidence = payload.evidence && typeof payload.evidence === "object" ? payload.evidence : {};
            askState.answerMode = askState.evidence?.answer_mode?.mode || askState.answerMode || "answer";
            askState.messages[messageIndex].sources = askState.sources;
            askState.messages[messageIndex].sourceStatus = sourceStatus;
            if (["no_answer", "clarification_required"].includes(sourceStatus)) {
              appendSourceNotice(
                answer,
                sourceStatus === "clarification_required" ? "需要补充上一轮主题，未使用参考来源" : "知识库缺失，未使用参考来源",
              );
              publishEmbeddedSnapshot();
              continue;
            }
            const displaySources = normalizeSourceList(payload.sources);
            appendSources(answer, displaySources);
            if ((payload.sources || []).length > displaySources.length) {
              const extra = document.createElement("span");
              extra.className = "ask-sources-extra";
              extra.textContent = `另有 ${(payload.sources || []).length - displaySources.length} 个相关片段`;
              answer.querySelector(".ask-sources")?.appendChild(extra);
            }
            publishEmbeddedSnapshot();
          }
          if (payload.type === "done") {
            if (answer.dataset.pending === "true") {
              answer.textContent = "";
              delete answer.dataset.pending;
            }
            if (!askState.createdAt) askState.createdAt = new Date().toISOString();
            askState.answerCompleted = true;
            const exportBar = document.getElementById("export-bar");
            if (exportBar) exportBar.style.display = "flex";
            updateAnswerOperationState();
            publishEmbeddedSnapshot();
          }
        }
      }
    } catch (error) {
      delete answer.dataset.pending;
      answer.textContent = formatErrorFeedback("问答", error);
      askState.messages[messageIndex].text = answer.textContent;
      publishEmbeddedSnapshot();
    } finally {
      askRequestInFlight = false;
      if (sendButton) sendButton.disabled = false;
      if (newConversationButton) newConversationButton.disabled = false;
    }
  });
}

async function exportAnswer(format) {
  if (!askState.question || !askState.answer) return;
  const response = await fetch(`api/export/${format}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(askState),
  });
  if (!response.ok) throw new Error(await response.text());
  const blob = await response.blob();
  const link = document.createElement("a");
  const disposition = response.headers.get("content-disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  link.href = URL.createObjectURL(blob);
  link.download = match ? match[1] : `pka-answer.${format === "word" ? "docx" : "pptx"}`;
  link.click();
  URL.revokeObjectURL(link.href);
}

let currentAssetId = "";

async function setupAssets() {
  if (document.body?.dataset?.page !== "assets") return;
  document.getElementById("asset-export-word")?.addEventListener("click", () => exportCurrentAsset("word"));
  document.getElementById("asset-export-ppt")?.addEventListener("click", () => exportCurrentAsset("ppt"));
  document.getElementById("asset-delete")?.addEventListener("click", deleteCurrentAsset);
  await loadAssetList();
  const params = new URLSearchParams(window.location.search);
  const requestedAssetId = params.get("asset_id");
  if (requestedAssetId) {
    await loadAssetDetail(requestedAssetId);
  }
}

async function loadAssetList() {
  const list = document.getElementById("asset-list");
  const status = document.getElementById("asset-list-status");
  if (!list) return;
  if (status) status.textContent = "加载中...";
  try {
    const response = await fetch("api/assets/answers?limit=50");
    if (!response.ok) throw new Error(await response.text());
    const payload = await response.json();
    renderAssetList(payload.assets || []);
    if (status) status.textContent = `${(payload.assets || []).length} 条`;
  } catch (error) {
    list.textContent = "资料库加载失败。";
    if (status) status.textContent = "加载失败";
  }
}

function renderAssetList(assets) {
  const list = document.getElementById("asset-list");
  if (!list) return;
  list.innerHTML = "";
  if (!assets.length) {
    list.textContent = "暂无资料。完成一次问答后点击“保存到资料库”。";
    return;
  }
  for (const asset of assets) {
    const item = document.createElement("div");
    item.className = "asset-list-item";
    item.dataset.assetId = asset.asset_id || "";
    const openButton = document.createElement("button");
    openButton.type = "button";
    openButton.className = "asset-list-open";
    openButton.innerHTML = `
      <span class="asset-list-title"></span>
      <span class="asset-list-question"></span>
      <span class="asset-list-meta"></span>
    `;
    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "asset-list-delete";
    deleteButton.textContent = "删除";
    deleteButton.addEventListener("click", () => deleteAsset(asset.asset_id, asset.title || "未命名资料"));
    openButton.querySelector(".asset-list-title").textContent = asset.title || "未命名资料";
    openButton.querySelector(".asset-list-question").textContent = asset.question || "";
    openButton.querySelector(".asset-list-meta").textContent = [
      asset.created_at || "",
      asset.language || "",
      asset.answer_mode || "",
      asset.source_status || "",
      asset.rag_status || "",
      `${asset.source_count || 0} 来源`,
      `${asset.export_count || 0} 导出`,
    ].filter(Boolean).join(" · ");
    openButton.addEventListener("click", () => loadAssetDetail(asset.asset_id));
    item.append(openButton, deleteButton);
    list.appendChild(item);
  }
}

async function loadAssetDetail(assetId) {
  if (!assetId) return;
  const response = await fetch(`api/assets/answers/${encodeURIComponent(assetId)}`);
  if (!response.ok) {
    showAssetDetailError("资料不存在或已移动。");
    return;
  }
  const payload = await response.json();
  renderAssetDetail(payload.asset);
}

function renderAssetDetail(asset) {
  currentAssetId = asset.asset_id || "";
  const manifest = asset.manifest || {};
  document.getElementById("asset-detail-empty")?.setAttribute("hidden", "");
  document.getElementById("asset-detail-content")?.removeAttribute("hidden");
  document.getElementById("asset-title").textContent = manifest.title || "未命名资料";
  document.getElementById("asset-meta").textContent = [manifest.created_at, manifest.language, manifest.answer_mode]
    .filter(Boolean)
    .join(" · ");
  document.getElementById("asset-source-status").textContent = manifest.source_status || "";
  document.getElementById("asset-rag-status").textContent = manifest.rag_status || "not_indexed";
  document.getElementById("asset-question").textContent = manifest.question || "";
  document.getElementById("asset-answer").textContent = asset.answer_markdown || "";
  const exportStatus = document.getElementById("asset-export-status");
  if (exportStatus) exportStatus.textContent = "";
}

function showAssetDetailError(message) {
  currentAssetId = "";
  const empty = document.getElementById("asset-detail-empty");
  const content = document.getElementById("asset-detail-content");
  if (empty) {
    empty.textContent = message;
    empty.removeAttribute("hidden");
  }
  if (content) content.setAttribute("hidden", "");
}

async function exportCurrentAsset(format) {
  if (!currentAssetId) return;
  const status = document.getElementById("asset-export-status");
  if (status) status.textContent = "导出中...";
  const response = await fetch(`api/assets/answers/${encodeURIComponent(currentAssetId)}/export/${format}`, {
    method: "POST",
  });
  if (!response.ok) {
    if (status) status.textContent = "导出失败";
    return;
  }
  const blob = await response.blob();
  const link = document.createElement("a");
  const disposition = response.headers.get("content-disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  link.href = URL.createObjectURL(blob);
  link.download = match ? match[1] : `pka-asset.${format === "word" ? "docx" : "pptx"}`;
  link.click();
  URL.revokeObjectURL(link.href);
  if (status) status.textContent = "导出完成";
  await loadAssetDetail(currentAssetId);
}

async function deleteCurrentAsset() {
  if (!currentAssetId) return;
  const title = document.getElementById("asset-title")?.textContent || "当前资料";
  await deleteAsset(currentAssetId, title);
}

async function deleteAsset(assetId, title) {
  if (!assetId) return;
  if (!window.confirm(`删除“${title}”？此操作不会影响知识库。`)) return;
  const status = document.getElementById("asset-export-status");
  if (status && currentAssetId === assetId) status.textContent = "删除中...";
  const response = await fetch(`api/assets/answers/${encodeURIComponent(assetId)}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    if (status && currentAssetId === assetId) status.textContent = "删除失败";
    return;
  }
  if (currentAssetId === assetId) {
    showAssetDetailError("资料已删除。");
  }
  await loadAssetList();
}

function setDeep(target, dottedKey, value) {
  const parts = dottedKey.split(".");
  let node = target;
  while (parts.length > 1) {
    const part = parts.shift();
    node[part] ||= {};
    node = node[part];
  }
  node[parts[0]] = value;
}

function getDeep(target, dottedKey) {
  return dottedKey.split(".").reduce((node, key) => (node ? node[key] : ""), target);
}

function formatSettingsFeedback(result) {
  if (!result || typeof result !== "object") return String(result || "");
  if (Array.isArray(result.checks)) {
    const labels = { ok: "可用", warn: "需配置", error: "不可用" };
    const markers = { ok: "通过", warn: "注意", error: "失败" };
    const checks = result.checks;
    return checks.map((check) => {
      const status = labels[check.status] || check.status || "未知";
      const marker = markers[check.status] || "状态";
      return `${marker}｜${check.label}：${status}。${check.detail || ""}`;
    }).join("\n");
  }
  if (typeof result.message === "string" && result.message.trim()) {
    return result.status === "ok" ? `连接测试通过：${result.message}` : result.message;
  }
  if (result.deepseek || result.embedding || result.retrieval || result.ocr) {
    return "保存完成。当前配置已生效。";
  }
  return "操作完成。";
}

function formatClearFeedback(result) {
  if (!result || result.status !== "ok") return "清空失败，请稍后重试。";
  return result.message || "知识库已清空。";
}

async function setupSettings() {
  const form = document.getElementById("settings-form");
  if (form) {
    const config = await fetch("api/config").then((response) => response.json());
    for (const field of form.querySelectorAll("input, select")) {
      field.value = getDeep(config, field.name) ?? "";
    }
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const payload = {};
      for (const field of form.querySelectorAll("input, select")) {
        if (field.type === "password" && field.value.startsWith("****")) continue;
        const value = field.type === "number" ? Number(field.value) : field.value;
        setDeep(payload, field.name, value);
      }
      const result = await postJSON("api/config", payload);
      setFeedback("settings-feedback", formatSettingsFeedback(result));
    });
  }
  document.getElementById("test-connection")?.addEventListener("click", async () => {
    const result = await fetch("api/test-connection", { method: "POST" }).then((r) => r.json());
    setFeedback("settings-feedback", formatSettingsFeedback(result));
  });
  setupClearKnowledgeGuard();
}

function setupClearKnowledgeGuard() {
  const clearButton = document.getElementById("clear-knowledge");
  const confirmation = document.getElementById("clear-confirmation");
  if (!clearButton || !confirmation) return;
  const phrase = confirmation.dataset.confirmPhrase || "清空知识库";
  const syncButton = () => {
    clearButton.disabled = confirmation.value.trim() !== phrase;
  };
  confirmation.addEventListener("input", syncButton);
  syncButton();
  clearButton.addEventListener("click", async () => {
    if (clearButton.disabled) return;
    const result = await postJSON("api/ingest/clear", {});
    setFeedback("clear-feedback", formatClearFeedback(result));
    confirmation.value = "";
    syncButton();
    notifyKnowledgeUpdated("clear");
    publishEmbeddedSnapshot();
  });
}

setupEmbeddedStateBridge();
setupIngest();
setupAsk();
setupAssets();
setupSettings();
