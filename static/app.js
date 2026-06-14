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
const MAX_UPLOAD_FILES = 6;
const MAX_UPLOAD_FEEDBACK = "最多上传 6 个文件，请先移除一个文件。";

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
  if (action === "direct") return "已全文入库";
  if (action === "cleaned") return "已清洗入库";
  if (action === "low_indexed") return "低质量入库";
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
      return `部分 OCR 入库 · ${pageText}`;
    }
    return "OCR 入库";
  }
  if (action === "needs_ocr_skipped") return "需 OCR 未入库 · 未进入主知识库，避免污染检索";
  if (action === "ocr_failed_skipped") return "OCR 失败未入库 · 未进入主知识库，避免污染检索";
  if (action === "ocr_timeout_skipped") return "OCR 超时未入库 · 未进入主知识库，避免污染检索";
  return "";
}

function qualityBadge(result) {
  const action = result?.quality?.action;
  const text = qualityStatusMessage(result);
  if (action === "ocr") return { className: "is-ocr", text: text || "OCR 入库" };
  if (action === "low_indexed") return { className: "is-low", text: text || "低质量入库" };
  if (action === "needs_ocr_skipped" || action === "ocr_failed_skipped" || action === "ocr_timeout_skipped") {
    return { className: "is-skipped", text: text || "需 OCR 未入库" };
  }
  if (action === "direct" || action === "cleaned") return { className: "is-complete", text };
  return null;
}

function formatErrorFeedback(actionLabel, error) {
  return `${actionLabel}失败：${humanizeErrorMessage(error)}`;
}

function humanizeErrorMessage(error) {
  const raw = error?.message || String(error);
  try {
    const parsed = JSON.parse(raw);
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
  if (result.status === "skipped") return "skipped";
  const badge = qualityBadge(result);
  if (badge?.className === "is-low") return "low";
  if (badge?.className === "is-ocr") return "ocr";
  return "complete";
}

function summarizeBatchFeedback(result) {
  if (!result || !Array.isArray(result.files)) return "上传失败。";
  const parts = [
    result.status === "partial" ? "部分上传完成" : "上传完成",
    `${result.succeeded || 0} 个成功`,
    `${result.skipped || 0} 个未入库`,
    `${result.failed || 0} 个失败`,
    `${result.total_chunks || 0} 个片段`,
  ];
  const failed = result.files
    .filter((item) => item.status === "error")
    .map((item) => `${item.filename}：${item.error}`);
  const skipped = result.files
    .filter((item) => item.status === "skipped")
    .map((item) => `${item.filename}：${qualityStatusMessage(item) || "需 OCR 未入库"}`);
  const detail = skipped.concat(failed);
  return detail.length ? `${parts.join(" · ")}\n${detail.join("\n")}` : parts.join(" · ");
}

function renderUploadSlots() {
  const list = document.getElementById("file-list");
  const summary = document.getElementById("file-summary");
  const clearButton = document.getElementById("clear-selected-files");
  const fileInput = document.getElementById("file-input");
  if (!list || !summary) return;
  list.textContent = "";
  if (fileInput) fileInput.disabled = selectedFiles.length >= MAX_UPLOAD_FILES;
  if (!selectedFiles.length) {
    summary.textContent = `未选择文件 · 最多 ${MAX_UPLOAD_FILES} 个`;
    if (clearButton) clearButton.hidden = true;
  } else {
    const totalSize = selectedFiles.reduce((sum, file) => sum + file.size, 0);
    summary.textContent = `已选择 ${selectedFiles.length} / ${MAX_UPLOAD_FILES} 个文件 · ${formatBytes(totalSize)}`;
    if (clearButton) clearButton.hidden = false;
  }

  for (let index = 0; index < MAX_UPLOAD_FILES; index += 1) {
    const file = selectedFiles[index];
    if (!file) {
      const slot = document.createElement("button");
      slot.type = "button";
      slot.className = "upload-slot is-empty";
      slot.setAttribute("aria-label", `上传槽 ${index + 1}：添加文件`);
      slot.innerHTML = '<span class="upload-slot-plus">+</span><span class="upload-slot-label">添加文件</span>';
      slot.addEventListener("click", () => {
        if (selectedFiles.length >= MAX_UPLOAD_FILES) {
          setFeedback("file-feedback", MAX_UPLOAD_FEEDBACK);
          return;
        }
        fileInput?.click();
      });
      list.appendChild(slot);
      continue;
    }
    const result = fileUploadResults.find((item) => item.filename === file.name);
    const status = uploadSlotStatus(result);
    const row = document.createElement("div");
    row.className = `upload-slot is-filled is-${status}`;
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
      selectedFiles.splice(index, 1);
      fileUploadResults = fileUploadResults.filter((item) => item.filename !== file.name);
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
    const qualityMessage = qualityStatusMessage(result);
    meta.textContent =
      status === "error"
        ? "失败"
        : status === "skipped"
          ? qualityMessage || "需 OCR 未入库"
          : qualityMessage || (status === "complete" ? "完成" : formatBytes(file.size));
    meta.title = meta.textContent;
    row.append(head, name, meta);
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
    const remainingSlots = MAX_UPLOAD_FILES - selectedFiles.length;
    const acceptedFiles = incomingFiles.slice(0, Math.max(remainingSlots, 0));
    if (incomingFiles.length > acceptedFiles.length) {
      setFeedback("file-feedback", MAX_UPLOAD_FEEDBACK);
    } else {
      setFeedback("file-feedback", "");
    }
    if (acceptedFiles.length) {
      selectedFiles = selectedFiles.concat(acceptedFiles);
      fileUploadResults = [];
    }
    fileInput.value = "";
    renderUploadSlots();
    publishEmbeddedSnapshot();
  });
  clearSelectedFiles?.addEventListener("click", () => {
    selectedFiles = [];
    fileUploadResults = [];
    renderUploadSlots();
    setFeedback("file-feedback", "");
    publishEmbeddedSnapshot();
  });
  renderUploadSlots();
  fileForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!selectedFiles.length) {
      setFeedback("file-feedback", "请选择文件。");
      return;
    }
    const form = new FormData();
    selectedFiles.forEach((file) => form.append("files", file));
    try {
      setFeedback("file-feedback", `上传中... ${selectedFiles.length} 个文件`);
      const response = await fetch("api/ingest/files", { method: "POST", body: form });
      if (!response.ok) throw new Error(await response.text());
      const result = await response.json();
      fileUploadResults = result.files || [];
      setFeedback("file-feedback", summarizeBatchFeedback(result));
      renderUploadSlots();
      notifyKnowledgeUpdated("ingest:file");
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
    const link = document.createElement("a");
    link.href = sourceHref(source);
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = formatSourceLabel(source);
    link.title = source.raw_file_path ? "打开原始附件" : "打开来源片段";
    item.appendChild(link);
    sources.appendChild(item);
  }
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
    }));
  if (!askState.messages.length) return;
  box.innerHTML = "";
  askState.messages.forEach((message, index) => {
    const node = appendMessage(message.text, message.role, { skipState: true });
    node.dataset.messageIndex = String(index);
    if (message.role === "assistant" && message.sources.length) {
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
    const key = source.raw_file_path ? `file:${source.raw_file_path}` : `source:${source.source_name}`;
    if (seen.has(key)) continue;
    seen.add(key);
    displaySources.push(source);
  }
  return displaySources.slice(0, 5);
}

function formatSourceLabel(source) {
  if (source.raw_file_path) {
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

function sourceHref(source) {
  if (source.raw_file_path) {
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
            askState.sources = payload.sources;
            askState.messages[messageIndex].sources = payload.sources;
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
