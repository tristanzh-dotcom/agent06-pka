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
  question: "",
  language: "zh",
  answer: "",
  sources: [],
  messages: [],
};

let selectedFiles = [];
let fileUploadResults = [];
let expandedQualityFiles = new Set();
let uploadTaskPollTimers = new Map();
let pendingUploadSlotIndex = null;
const MAX_UPLOAD_FILES = 6;
const ORG_CHART_SLOT_INDEX = 5;
const MAX_UPLOAD_FEEDBACK = "最多上传 6 个文件，请先移除一个文件。";
const OCR_TASK_POLL_INTERVAL_MS = 1500;

function currentEmbeddedRoute() {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`;
}

function notifyKnowledgeUpdated(action) {
  if (window.parent === window) return;
  window.parent.postMessage({ type: "agent06:knowledge-updated", action }, window.location.origin);
}

function collectEmbeddedState() {
  return {
    route: currentEmbeddedRoute(),
    textInput: document.getElementById("text-input")?.value || "",
    textFeedback: document.getElementById("text-feedback")?.textContent || "",
    fileFeedback: document.getElementById("file-feedback")?.textContent || "",
    questionInput: document.getElementById("question-input")?.value || "",
    language: document.querySelector('input[name="language"]:checked')?.value || "",
    ask: {
      question: askState.question,
      language: askState.language,
      answer: askState.answer,
      sources: askState.sources,
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
  if (result.status === "accepted") {
    return `${actionLabel}已提交 · ${qualityStatusMessage(result) || "后台 OCR 排队中"}`;
  }
  if (result.status === "skipped") {
    return `${actionLabel}未入库 · ${qualityStatusMessage(result) || "需 OCR 未入库"}`;
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
  if (result?.status === "failed") return "后台 OCR 失败 · 未进入主知识库";
  return "";
}

function qualityBadge(result) {
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
  return "complete";
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
  const detail = accepted.concat(skipped, failed);
  return detail.length ? `${parts.join(" · ")}\n${detail.join("\n")}` : parts.join(" · ");
}

function summarizeCurrentUploadFeedback() {
  const files = (fileUploadResults || []).filter(Boolean);
  const succeeded = files.filter((item) => ["ok", "completed"].includes(item.status)).length;
  const accepted = files.filter((item) => ["accepted", "queued", "processing"].includes(item.status)).length;
  const skipped = files.filter((item) => item.status === "skipped").length;
  const failed = files.filter((item) => ["error", "failed"].includes(item.status)).length;
  const totalChunks = files.reduce((sum, item) => sum + (Number(item.chunks) || Number(item.result?.chunks_inserted) || 0), 0);
  return summarizeBatchFeedback({
    status: failed ? "partial" : accepted ? "accepted" : "ok",
    succeeded,
    accepted,
    skipped,
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
              ? "未入库"
              : status === "complete" && result
                ? `${result.chunks || 0} 个片段`
                : formatBytes(file.size);
    meta.title = meta.textContent;
    row.append(head, name, meta);
    renderQualityBadge(row, result, result?.raw_file_path || file.name);
    list.appendChild(row);
  }
}

const renderSelectedFiles = renderUploadSlots;

function setupIngest() {
  const textForm = document.getElementById("text-form");
  const fileForm = document.getElementById("file-form");
  const fileInput = document.getElementById("file-input");
  const clearSelectedFiles = document.getElementById("clear-selected-files");
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
    node.dataset.messageIndex = String(askState.messages.length - 1);
  }
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

function restoreAskConversation(state) {
  const box = document.getElementById("conversation");
  if (!box || !state || typeof state !== "object") return;
  const messages = Array.isArray(state.messages) ? state.messages : [];
  askState.question = typeof state.question === "string" ? state.question : "";
  askState.language = typeof state.language === "string" ? state.language : askState.language;
  askState.answer = typeof state.answer === "string" ? state.answer : "";
  askState.sources = Array.isArray(state.sources) ? state.sources : [];
  askState.messages = messages
    .filter((message) => message && typeof message.text === "string")
    .map((message) => ({
      role: message.role === "user" ? "user" : "assistant",
      text: message.text,
      sources: Array.isArray(message.sources) ? message.sources : [],
      sourceStatus: typeof message.sourceStatus === "string" ? message.sourceStatus : "",
    }));
  if (!askState.messages.length) return;
  box.innerHTML = "";
  askState.messages.forEach((message, index) => {
    const node = appendMessage(message.text, message.role, { skipState: true });
    node.dataset.messageIndex = String(index);
    if (message.role === "assistant" && message.sourceStatus === "no_answer") {
      appendSourceNotice(node, "知识库缺失，未使用参考来源");
    } else if (message.role === "assistant" && message.sources.length) {
      appendSources(node, normalizeSourceList(message.sources));
    }
  });
  const exportBar = document.getElementById("export-bar");
  if (exportBar) exportBar.style.display = askState.question && askState.answer ? "flex" : "none";
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

function setupAsk() {
  const form = document.getElementById("query-form");
  const chips = document.querySelectorAll(".empty-chip");
  chips.forEach((chip) => {
    chip.addEventListener("click", () => {
      document.getElementById("question-input").value = chip.textContent;
      document.getElementById("query-form").requestSubmit();
    });
  });
  document.getElementById("export-word")?.addEventListener("click", () => exportAnswer("word"));
  document.getElementById("export-ppt")?.addEventListener("click", () => exportAnswer("ppt"));
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = document.getElementById("question-input");
    const question = input.value.trim();
    const language = document.querySelector('input[name="language"]:checked')?.value || "zh";
    if (!question) return;
    appendMessage(question, "user");
    askState.question = question;
    askState.language = language;
    askState.answer = "";
    askState.sources = [];
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
        body: JSON.stringify({ question, language }),
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
            askState.sources = sourceStatus === "no_answer" ? [] : payload.sources;
            askState.messages[messageIndex].sources = askState.sources;
            askState.messages[messageIndex].sourceStatus = sourceStatus;
            if (payload.source_status === "no_answer") {
              appendSourceNotice(answer, "知识库缺失，未使用参考来源");
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
            const exportBar = document.getElementById("export-bar");
            if (exportBar) exportBar.style.display = "flex";
            publishEmbeddedSnapshot();
          }
        }
      }
    } catch (error) {
      delete answer.dataset.pending;
      answer.textContent = formatErrorFeedback("问答", error);
      askState.messages[messageIndex].text = answer.textContent;
      publishEmbeddedSnapshot();
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
setupSettings();
