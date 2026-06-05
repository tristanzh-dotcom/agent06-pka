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
};

function setFeedback(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function formatIngestFeedback(result, actionLabel) {
  if (!result || result.status !== "ok") {
    return `${actionLabel}失败。`;
  }
  const parts = [`${actionLabel}完成`];
  if (typeof result.chunks === "number") parts.push(`${result.chunks} 个片段`);
  if (result.source_name) parts.push(`来源：${result.source_name}`);
  return parts.join(" · ");
}

function formatErrorFeedback(actionLabel, error) {
  return `${actionLabel}失败：${error.message || String(error)}`;
}

function setupIngest() {
  const textForm = document.getElementById("text-form");
  const fileForm = document.getElementById("file-form");
  textForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const textInput = document.getElementById("text-input");
    const text = textInput.value;
    try {
      setFeedback("text-feedback", "录入中...");
      const result = await postJSON("api/ingest/text", { text });
      textInput.value = "";
      setFeedback("text-feedback", formatIngestFeedback(result, "录入"));
    } catch (error) {
      setFeedback("text-feedback", formatErrorFeedback("录入", error));
    }
  });
  fileForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = document.getElementById("file-input");
    if (!input.files.length) {
      setFeedback("file-feedback", "请选择文件。");
      return;
    }
    const form = new FormData();
    form.append("file", input.files[0]);
    try {
      setFeedback("file-feedback", "上传中...");
      const response = await fetch("api/ingest/file", { method: "POST", body: form });
      if (!response.ok) throw new Error(await response.text());
      setFeedback("file-feedback", formatIngestFeedback(await response.json(), "上传"));
    } catch (error) {
      setFeedback("file-feedback", formatErrorFeedback("上传", error));
    }
  });
}

function appendMessage(text, role) {
  const box = document.getElementById("conversation");
  const node = document.createElement("div");
  node.className = `ask-message ${role}`;
  node.textContent = text;
  box.appendChild(node);
  return node;
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
    const pendingText = "检索中...";
    answer.dataset.pending = "true";
    answer.textContent = pendingText;
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
          }
          if (payload.type === "error") {
            if (answer.dataset.pending === "true") {
              answer.textContent = "";
              delete answer.dataset.pending;
            }
            answer.textContent += `\n${payload.content}`;
          }
          if (payload.type === "sources") {
            askState.sources = payload.sources;
            const displaySources = normalizeSourceList(payload.sources);
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
            if ((payload.sources || []).length > displaySources.length) {
              const extra = document.createElement("span");
              extra.className = "ask-sources-extra";
              extra.textContent = `另有 ${(payload.sources || []).length - displaySources.length} 个相关片段`;
              sources.appendChild(extra);
            }
            answer.appendChild(sources);
          }
          if (payload.type === "done") {
            if (answer.dataset.pending === "true") {
              answer.textContent = "";
              delete answer.dataset.pending;
            }
            const exportBar = document.getElementById("export-bar");
            if (exportBar) exportBar.style.display = "flex";
          }
        }
      }
    } catch (error) {
      delete answer.dataset.pending;
      answer.textContent = formatErrorFeedback("问答", error);
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
  link.download = match ? match[1] : `pka-answer.${format === "word" ? "docx" : "md"}`;
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

async function setupSettings() {
  const form = document.getElementById("settings-form");
  if (!form) return;
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
    setFeedback("settings-feedback", await postJSON("api/config", payload));
  });
  document.getElementById("test-connection")?.addEventListener("click", async () => {
    setFeedback("settings-feedback", await fetch("api/test-connection", { method: "POST" }).then((r) => r.json()));
  });
  document.getElementById("clear-knowledge")?.addEventListener("click", async () => {
    if (!confirm("确定清空全部知识库？此操作不可撤销。")) return;
    setFeedback("clear-feedback", await postJSON("api/ingest/clear", {}));
  });
}

setupIngest();
setupAsk();
setupSettings();
