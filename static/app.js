const el = (id) => document.getElementById(id);

const chatEl = el("chat");
const promptEl = el("prompt");
const modelSelect = el("modelSelect");

const statusDot = el("statusDot");
const statusText = el("statusText");
const ragSummary = el("ragSummary");

const btnSend = el("btnSend");
const btnStop = el("btnStop");
const btnEditLast = el("btnEditLast");

const btnTheme = el("btnTheme");
const btnHelp = el("btnHelp");

const systemPromptEl = el("systemPrompt");
const tempEl = el("temperature");
const numCtxEl = el("numCtx");
const keepAliveEl = el("keepAlive");

const shortcutsOverlay = el("shortcutsOverlay");
const shortcutsModal = el("shortcutsModal");
const btnShortcutsClose = el("btnShortcutsClose");

const slashPalette = el("slashPalette");

const prismThemeLink = el("prismTheme");

const PRISM_THEMES = {
  dark: "https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism-tomorrow.min.css",
  light: "https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism.min.css",
};

function applyTheme(theme, persist = true) {
  state.theme = (theme === "light") ? "light" : "dark";
  document.documentElement.dataset.theme = state.theme;
  if (prismThemeLink && PRISM_THEMES[state.theme]) prismThemeLink.href = PRISM_THEMES[state.theme];
  if (persist) saveState();
}

function toggleTheme() {
  applyTheme(state.theme === "light" ? "dark" : "light");
}

const btnSettings = el("btnSettings");
const btnSettingsClose = el("btnSettingsClose");
const settingsOverlay = el("settingsOverlay");
const settingsModal = el("settingsModal");

function openSettings(){
  settingsOverlay.classList.remove("hidden");
  settingsModal.classList.remove("hidden");
}
function closeSettings(){
  settingsOverlay.classList.add("hidden");
  settingsModal.classList.add("hidden");
}

btnSettings?.addEventListener("click", openSettings);
btnSettingsClose?.addEventListener("click", closeSettings);
settingsOverlay?.addEventListener("click", closeSettings);

document.addEventListener("keydown", (e)=>{
  if(e.key==="Escape") closeSettings();
});

document.querySelectorAll(".settingsTab").forEach(btn=>{
  btn.addEventListener("click", ()=>{
    document.querySelectorAll(".settingsTab").forEach(b=>b.classList.remove("active"));
    btn.classList.add("active");

    const key = btn.getAttribute("data-settings-tab");
    document.querySelectorAll(".settingsPanel").forEach(p=>{
      p.classList.toggle("hidden", p.getAttribute("data-settings-panel") !== key);
    });
  });
});


const ragToggle = el("ragToggle");
const topKEl = el("topK");
const mmrToggle = el("mmrToggle");
const autoModelToggle = el("autoModelToggle");
const presetSelect = el("presetSelect");

const scrollHint = el("scrollHint");
const scrollToBottomBtn = el("scrollToBottomBtn");
const scrollCount = el("scrollCount");

const sidebar = el("sidebar");
const sidebarOverlay = el("sidebarOverlay");
const btnSidebar = el("btnSidebar");
const btnSidebarClose = el("btnSidebarClose");

const tabChats = el("tabChats");
const tabDocs = el("tabDocs");
const tabSettings = el("tabSettings");
const panelChats = el("panelChats");
const panelDocs = el("panelDocs");
const panelSettings = el("panelSettings");

const btnNewChat = el("btnNewChat");
const showArchived = el("showArchived");
const chatSearch = el("chatSearch");
const chatList = el("chatList");
const btnClear = el("btnClear");
const btnExportChat = el("btnExportChat");

const fileUpload = el("fileUpload");
const docsList = el("docsList");
const btnDocsAll = el("btnDocsAll");
const btnDocsNone = el("btnDocsNone");

const btnSaveSettings = el("btnSaveSettings");
const btnResetSettings = el("btnResetSettings");

// modal
const modalOverlay = el("modalOverlay");
const modal = el("modal");
const modalTitle = el("modalTitle");
const modalBody = el("modalBody");
const btnModalClose = el("btnModalClose");

let abortCtl = null;
let isGenerating = false;
let lastSources = [];

let currentChatId = localStorage.getItem("currentChatId") || null;

const STORAGE_KEY = "ollama_web_state_v2";

const state = {
  model: "",
  theme: "dark",
  settings: {
    system: "",
    temperature: 0.7,
    num_ctx: 4096,
    keep_alive: "5m",
    top_k: 6,
    use_mmr: false,
  },
  messages: [],
  docs: [],
  prefs: { rag_enabled: 0, doc_ids: null },
  lastResearchRunId: null,
};

const PRESETS = [
  { name: "Coding",   temperature: 0.2, num_ctx: 8192, top_k: 6,  use_mmr: false },
  { name: "Writing",  temperature: 0.9, num_ctx: 4096, top_k: 4,  use_mmr: false },
  { name: "Fast",     temperature: 0.5, num_ctx: 2048, top_k: 3,  use_mmr: false },
  { name: "Accurate", temperature: 0.3, num_ctx: 8192, top_k: 8,  use_mmr: true  },
  { name: "RAG-heavy",temperature: 0.2, num_ctx: 8192, top_k: 12, use_mmr: true  },
];

function nowTs() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
function fmtTsFromEpoch(sec){
  if (!sec) return "";
  const d = new Date(Number(sec) * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
function parseMeta(meta){
  if (!meta) return null;
  if (typeof meta === "object") return meta;
  try { return JSON.parse(meta); } catch { return null; }
}

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

// code blocks + inline `code` + newlines
function renderLiteMarkdown(text) {
  const src = String(text ?? "");
  const fence = "```";
  let out = "";
  let i = 0;

  while (true) {
    const a = src.indexOf(fence, i);
    if (a === -1) { out += renderInline(src.slice(i)); break; }
    out += renderInline(src.slice(i, a));

    const b = src.indexOf(fence, a + fence.length);
    if (b === -1) { out += renderInline(src.slice(a)); break; }

    let codeBlock = src.slice(a + fence.length, b);
    if (codeBlock.startsWith("\n")) codeBlock = codeBlock.slice(1);
    const firstNl = codeBlock.indexOf("\n");
    if (firstNl !== -1 && firstNl <= 20) {
      const maybeLang = codeBlock.slice(0, firstNl).trim();
      const rest = codeBlock.slice(firstNl + 1);
      if (/^[a-z0-9+#.-]{1,20}$/i.test(maybeLang)) codeBlock = rest;
    }

    out += `<pre><code>${escapeHtml(codeBlock)}</code></pre>`;
    i = b + fence.length;
  }
  return out;

  function renderInline(chunk) {
    const parts = chunk.split("`");
    return parts.map((p, idx) => {
      if (idx % 2 === 1) return `<code class="inline">${escapeHtml(p)}</code>`;
      return escapeHtml(p).replaceAll("\n", "<br>");
    }).join("");
  }
}

function saveState() {
  const ui = {
    auto_model: !!autoModelToggle?.checked,
    preset: presetSelect?.value || ""
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify({
    model: state.model,
    theme: state.theme,
    settings: state.settings,
    ui,
    lastResearchRunId: state.lastResearchRunId || null
  }));
}
function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const obj = JSON.parse(raw);
    if (!obj || typeof obj !== "object") return;

    state.model = obj.model || state.model;
    state.theme = obj.theme || state.theme;
    state.settings = { ...state.settings, ...(obj.settings || {}) };
    state.lastResearchRunId = obj.lastResearchRunId || state.lastResearchRunId || null;

    const ui = obj.ui || {};
    if (autoModelToggle && typeof ui.auto_model === "boolean") autoModelToggle.checked = ui.auto_model;
    if (presetSelect && typeof ui.preset === "string") presetSelect.value = ui.preset;
  } catch {}
}

function setStatus(ok, msg) {
  statusDot?.classList.toggle("ok", !!ok);
  statusDot?.classList.toggle("bad", ok === false);
  if (statusText) statusText.textContent = msg;
}

function showError(message, action = null, callback = null) {
  // Remove existing error banner
  const existing = document.querySelector(".error-banner");
  if (existing) existing.remove();

  const banner = document.createElement("div");
  banner.className = "error-banner";

  const content = document.createElement("div");
  content.className = "error-content";

  const icon = document.createElement("span");
  icon.className = "error-icon";
  icon.textContent = "⚠️";

  const msg = document.createElement("span");
  msg.className = "error-message";
  msg.textContent = String(message || "Error");

  content.append(icon, msg);

  if (action) {
    const actionBtn = document.createElement("button");
    actionBtn.className = "error-action btn";
    actionBtn.type = "button";
    actionBtn.textContent = action;
    actionBtn.addEventListener("click", () => {
      banner.remove();
      callback?.();
    });
    content.appendChild(actionBtn);
  }

  const closeBtn = document.createElement("button");
  closeBtn.className = "error-close iconbtn";
  closeBtn.type = "button";
  closeBtn.textContent = "✕";
  closeBtn.addEventListener("click", () => banner.remove());

  content.appendChild(closeBtn);
  banner.appendChild(content);
  document.body.appendChild(banner);

  // Auto-hide after 8 seconds
  setTimeout(() => {
    if (banner.parentNode) banner.remove();
  }, 8000);
}

let slashCommands = [];
let slashOpen = false;
let slashActive = 0;

async function loadSlashCommands() {
  try {
    const r = await fetch("/api/slash_commands");
    const j = await r.json();
    slashCommands = Array.isArray(j.commands) ? j.commands : [];
  } catch {
    slashCommands = [];
  }
}

function escHtml(s="") {
  return s.replace(/[&<>"']/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
}

function buildSlashList(filterText) {
  const q = (filterText || "").trim().toLowerCase();
  const list = slashCommands.filter(x => {
    const hay = `${x.cmd} ${x.args||""} ${x.desc||""}`.toLowerCase();
    return hay.includes(q);
  });

  if (!list.length) {
    slashPalette.innerHTML = `<div class="slashItem"><span class="slashCmd">No matches</span></div>`;
    slashActive = 0;
    return list;
  }

  slashActive = Math.max(0, Math.min(slashActive, list.length - 1));

  slashPalette.innerHTML = list.map((x, i) => `
    <div class="slashItem ${i===slashActive ? "active":""}" data-i="${i}" role="option" aria-selected="${i===slashActive}">
      <div>
        <span class="slashCmd">${escHtml(x.cmd)}</span>
        ${x.args ? `<span class="slashArgs">${escHtml(x.args)}</span>` : ""}
      </div>
      <div class="slashDesc">${escHtml(x.desc || "")}</div>
    </div>
  `).join("");

  return list;
}

function openSlash() {
  slashOpen = true;
  slashPalette.classList.remove("hidden");
}

function closeSlash() {
  slashOpen = false;
  slashPalette.classList.add("hidden");
}

function showShortcuts() {
  shortcutsOverlay?.classList.remove("hidden");
  shortcutsModal?.classList.remove("hidden");
}

function hideShortcuts() {
  shortcutsOverlay?.classList.add("hidden");
  shortcutsModal?.classList.add("hidden");
}

function toggleChatSearch() {
  openSidebar();
  setTab("chats");
  chatSearch?.focus();
  chatSearch?.select?.();
}

function insertSlash(cmd) {
  // If user typed "/fi", replace that token; otherwise just insert.
  const v = promptEl.value || "";
  const m = v.match(/^\/\S*/);
  if (m) {
    promptEl.value = cmd + " " + v.slice(m[0].length).trimStart();
  } else {
    promptEl.value = cmd + " " + v;
  }
  promptEl.focus();
  promptEl.setSelectionRange(promptEl.value.length, promptEl.value.length);
  closeSlash();
  autoGrow();
}

let newMessagesCount = 0;

function isNearBottom() {
  const t = chatEl;
  return t.scrollHeight - (t.scrollTop + t.clientHeight) < 140;
}

function scrollToBottom(force = false, smooth = true) {
  if (force || isNearBottom()) {
    chatEl.scrollTo({
      top: chatEl.scrollHeight,
      behavior: smooth ? 'smooth' : 'auto'
    });
    newMessagesCount = 0;
    updateScrollButton();
  }
}

function updateScrollButton() {
  if (!scrollToBottomBtn || !scrollCount) return;

  const notAtBottom = !isNearBottom();
  const hasNewMessages = newMessagesCount > 0;

  scrollToBottomBtn.style.display = notAtBottom ? 'flex' : 'none';
  scrollCount.style.display = hasNewMessages ? 'inline' : 'none';
  scrollCount.textContent = newMessagesCount > 99 ? '99+' : newMessagesCount.toString();

  if (hasNewMessages) {
    scrollToBottomBtn.classList.add('has-new');
  } else {
    scrollToBottomBtn.classList.remove('has-new');
  }
}

function showScrollHint(show) {
  scrollHint?.classList.toggle("hidden", !show);
}

function incrementNewMessages() {
  newMessagesCount++;
  updateScrollButton();
}

scrollHint?.addEventListener("click", () => {
  scrollToBottom(true);
  showScrollHint(false);
});

scrollToBottomBtn?.addEventListener("click", () => {
  scrollToBottom(true);
  newMessagesCount = 0;
  updateScrollButton();
});

chatEl?.addEventListener("click", async (e) => {
  const a = e.target.closest?.("[data-chunk]");
  if (!a) return;
  e.preventDefault();
  const cid = Number(a.getAttribute("data-chunk"));
  if (!cid) return;
  await openSourceModal(cid);
});

chatEl?.addEventListener("scroll", () => {
  if (isNearBottom()) {
    newMessagesCount = 0;
    showScrollHint(false);
  }
  updateScrollButton();
});

function setGenerating(on) {
  isGenerating = on;
  btnStop?.classList.toggle("hidden", !on);
  btnSend.disabled = on;
  modelSelect.disabled = on;
  promptEl.disabled = on;
  btnEditLast.disabled = on;
}

function autoGrow() {
  promptEl.style.height = "auto";
  promptEl.style.height = Math.min(promptEl.scrollHeight, 220) + "px";
}

// click handling
slashPalette.addEventListener("mousedown", (e) => {
  const item = e.target.closest(".slashItem");
  if (!item) return;
  e.preventDefault(); // keep focus in textarea
  const i = Number(item.dataset.i);
  const list = buildSlashList((promptEl.value || "").slice(1));
  const picked = list[i];
  if (picked) insertSlash(picked.cmd);
});

// keyboard nav
promptEl.addEventListener("keydown", (e) => {
  // Ctrl/Cmd+Enter sends (matches placeholder)
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !e.shiftKey) {
    e.preventDefault();
    send();
    return;
  }

  if (!slashOpen) return;
  const list = buildSlashList((promptEl.value || "").slice(1));

  if (e.key === "Escape") {
    e.preventDefault();
    closeSlash();
    return;
  }
  if (e.key === "ArrowDown") {
    e.preventDefault();
    slashActive = Math.min(slashActive + 1, Math.max(0, list.length - 1));
    buildSlashList((promptEl.value || "").slice(1));
    return;
  }
  if (e.key === "ArrowUp") {
    e.preventDefault();
    slashActive = Math.max(slashActive - 1, 0);
    buildSlashList((promptEl.value || "").slice(1));
    return;
  }
  if (e.key === "Tab" || e.key === "Enter") {
    // Only hijack Enter if input begins with "/" (so it doesn't break normal send)
    if (e.key === "Enter" && !promptEl.value.startsWith("/")) return;
    e.preventDefault();
    const picked = list[slashActive];
    if (picked) insertSlash(picked.cmd);
    return;
  }
});

// show/hide + filtering
promptEl.addEventListener("input", () => {
  autoGrow();
  const v = promptEl.value || "";
  if (v.startsWith("/")) {
    if (!slashOpen) openSlash();
    slashActive = 0;
    buildSlashList(v.slice(1));
  } else if (slashOpen) {
    closeSlash();
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && isGenerating && abortCtl) abortCtl.abort();
  if (e.key === "/" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    showShortcuts();
  }
  if (e.key === "k" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    if (confirm("Clear this chat?")) {
      btnClear?.click();
    }
  }
  if (e.key === "n" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    btnNewChat?.click();
  }
  if (e.key === "e" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    btnEditLast?.click();
  }
  if (e.key === "f" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    toggleChatSearch();
  }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && isGenerating && abortCtl) abortCtl.abort();
});

btnSend.addEventListener("click", send);
btnStop.addEventListener("click", () => abortCtl?.abort());

function openSidebar(){
  sidebar?.classList.remove("closed");
  sidebarOverlay?.classList.remove("hidden");
}
function closeSidebar(){
  sidebar?.classList.add("closed");
  sidebarOverlay?.classList.add("hidden");
}
btnSidebar?.addEventListener("click", openSidebar);
btnSidebarClose?.addEventListener("click", closeSidebar);
sidebarOverlay?.addEventListener("click", closeSidebar);

function setTab(which){
  const chats = which === "chats";
  const docs = which === "docs";
  const settings = which === "settings";
  tabChats?.classList.toggle("active", chats);
  tabDocs?.classList.toggle("active", docs);
  tabSettings?.classList.toggle("active", settings);
  panelChats?.classList.toggle("hidden", !chats);
  panelDocs?.classList.toggle("hidden", !docs);
  panelSettings?.classList.toggle("hidden", !settings);
}
tabChats?.addEventListener("click", () => setTab("chats"));
tabDocs?.addEventListener("click", () => { setTab("docs"); loadDocs(); });
tabSettings?.addEventListener("click", () => setTab("settings"));

async function api(path, opts){
  const res = await fetch(path, opts);
  const text = await res.text();
  let j = {};
  try { j = JSON.parse(text); } catch {}
  if (!res.ok) throw new Error(j.error || j.detail || `HTTP ${res.status}`);
  return j;
}

async function apiPostJson(path, payload) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type":"application/json" },
    body: JSON.stringify(payload || {})
  });
  const j = await res.json().catch(()=> ({}));
  if (!res.ok) throw new Error(j.detail || j.error || `HTTP ${res.status}`);
  return j;
}

async function apiGet(path) {
  const res = await fetch(path);
  const j = await res.json().catch(()=> ({}));
  if (!res.ok) throw new Error(j.detail || j.error || `HTTP ${res.status}`);
  return j;
}

/* ---------------- prefs (DB) ---------------- */

async function loadPrefs(){
  if (!currentChatId) return;
  const j = await api(`/api/chats/${currentChatId}/prefs`);
  state.prefs = j.prefs || { rag_enabled:0, doc_ids:null };
  ragToggle.checked = !!state.prefs.rag_enabled;
  updateRagSummary();
}

async function savePrefs(patch){
  if (!currentChatId) return;
  const body = JSON.stringify(patch);
  await api(`/api/chats/${currentChatId}/prefs`, {
    method:"POST",
    headers:{ "Content-Type":"application/json" },
    body
  });
  await loadPrefs();
}

/* ---------------- rag summary ---------------- */

function updateRagSummary(){
  if (!ragSummary) return;
  const on = !!ragToggle?.checked;
  const sel = state.prefs?.doc_ids ?? null;
  if (!on) {
    ragSummary.textContent = "RAG: off";
    return;
  }
  if (sel === null) {
    ragSummary.textContent = "RAG: all docs";
    return;
  }
  ragSummary.textContent = `RAG: ${sel.length} doc${sel.length===1?"":"s"}`;
}

/* ---------------- docs UI ---------------- */

async function loadDocs(){
  const j = await api("/api/docs");
  state.docs = j.docs || [];
  renderDocsList();
  updateRagSummary();
}

function renderDocsList(){
  if (!docsList) return;
  docsList.innerHTML = "";

  const sel = state.prefs?.doc_ids ?? null;
  const isAll = sel === null;

  for (const d of state.docs){
    const item = document.createElement("div");
    item.className = "docItem";

    const top = document.createElement("div");
    top.className = "docTop";

    const left = document.createElement("div");
    const name = document.createElement("div");
    name.className = "docName";
    name.textContent = d.filename || `Doc ${d.id}`;

    const meta = document.createElement("div");
    meta.className = "docMeta";
    const g = d.group_name ? ` • group: ${d.group_name}` : "";
    const w = (d.weight ?? 1.0);
    meta.textContent = `id ${d.id} • chunks ${d.chunk_count ?? "?"} • w ${Number(w).toFixed(2)}${g}`;
    left.append(name, meta);

    const right = document.createElement("div");
    right.style.display = "flex";
    right.style.gap = "8px";
    right.style.alignItems = "center";

    const chk = document.createElement("input");
    chk.type = "checkbox";
    chk.checked = isAll ? true : sel.includes(Number(d.id));
    chk.title = "Active for this chat";
    chk.onchange = async () => {
      let next = state.prefs?.doc_ids ?? null;
      if (next === null) next = state.docs.map(x => Number(x.id));

      const id = Number(d.id);
      if (chk.checked) next = Array.from(new Set(next.concat([id])));
      else next = next.filter(x => x !== id);

      // if equals all, store null
      const allIds = state.docs.map(x => Number(x.id)).sort((a,b)=>a-b);
      const nextSorted = next.slice().sort((a,b)=>a-b);
      const same = allIds.length === nextSorted.length && allIds.every((v,i)=>v===nextSorted[i]);

      await savePrefs({ doc_ids: same ? null : nextSorted });
      renderDocsList();
    };

    const btnWeight = document.createElement("button");
    btnWeight.className = "iconbtn";
    btnWeight.textContent = "Weight";
    btnWeight.onclick = async () => {
      const cur = Number(d.weight ?? 1.0);
      const next = prompt("Doc weight (0.0 - 5.0). 1.0 = neutral:", String(cur));
      if (next === null) return;
      const w = Number(next);
      if (!Number.isFinite(w)) return alert("Bad number");
      await api(`/api/docs/${d.id}`, {
        method:"PATCH",
        headers:{ "Content-Type":"application/json" },
        body: JSON.stringify({ weight: w })
      });
      await loadDocs();
    };

    const btnGroup = document.createElement("button");
    btnGroup.className = "iconbtn";
    btnGroup.textContent = "Group";
    btnGroup.onclick = async () => {
      const cur = d.group_name || "";
      const next = prompt("Group name (blank clears):", cur);
      if (next === null) return;
      await api(`/api/docs/${d.id}`, {
        method:"PATCH",
        headers:{ "Content-Type":"application/json" },
        body: JSON.stringify({ group_name: next })
      });
      await loadDocs();
    };

    const del = document.createElement("button");
    del.className = "iconbtn";
    del.textContent = "Delete";
    del.onclick = async () => {
      if (!confirm(`Delete doc "${d.filename}"?`)) return;
      await api(`/api/docs/${d.id}`, { method:"DELETE" });
      await loadDocs();
    };

    right.append(chk, btnWeight, btnGroup, del);
    top.append(left, right);

    item.append(top);
    docsList.appendChild(item);
  }
}

btnDocsAll?.addEventListener("click", async () => {
  if (!currentChatId) return;
  await savePrefs({ doc_ids: null });
  renderDocsList();
});
btnDocsNone?.addEventListener("click", async () => {
  if (!currentChatId) return;
  await savePrefs({ doc_ids: [] });
  renderDocsList();
});

fileUpload?.addEventListener("change", async () => {
  const f = fileUpload.files?.[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  try {
    await fetch("/api/docs/upload", { method: "POST", body: fd });
  } finally {
    fileUpload.value = "";
  }
  await loadDocs();
});

/* ---------------- chats ---------------- */

async function loadChats(){
  const archived = showArchived?.checked ? 1 : 0;
  const q = (chatSearch?.value || "").trim();
  const qs = new URLSearchParams();
  qs.set("archived", String(archived));
  if (q) qs.set("q", q);

  const j = await api(`/api/chats?${qs.toString()}`);
  renderChatList(j.chats || []);
}

function renderChatList(chats){
  if (!chatList) return;
  chatList.innerHTML = "";
  for (const c of chats){
    const item = document.createElement("div");
    item.className = "chatItem" + (c.id === currentChatId ? " active" : "");
    item.onclick = () => selectChat(c.id);

    const title = document.createElement("div");
    title.className = "chatTitle";
    title.textContent = c.title || "Untitled";

    const meta = document.createElement("div");
    meta.className = "chatMeta";
    meta.textContent = (c.last_preview ? c.last_preview : "");

    const actions = document.createElement("div");
    actions.className = "chatActions";

    const btnRename = document.createElement("button");
    btnRename.className = "iconbtn";
    btnRename.textContent = "Rename";
    btnRename.onclick = async (e) => {
      e.stopPropagation();
      const next = prompt("New chat name:", c.title || "");
      if (next && next.trim()){
        await api(`/api/chats/${c.id}`, {
          method:"PATCH",
          headers:{ "Content-Type":"application/json" },
          body: JSON.stringify({ title: next.trim() })
        });
        await loadChats();
      }
    };

    const btnArchive = document.createElement("button");
    btnArchive.className = "iconbtn";
    btnArchive.textContent = c.archived ? "Unarchive" : "Archive";
    btnArchive.onclick = async (e) => {
      e.stopPropagation();
      const nextArchived = !c.archived;
      await api(`/api/chats/${c.id}`, {
        method:"PATCH",
        headers:{ "Content-Type":"application/json" },
        body: JSON.stringify({ archived: nextArchived })
      });
      if (c.id === currentChatId && nextArchived && !showArchived.checked) {
        currentChatId = null;
        localStorage.removeItem("currentChatId");
        await ensureChatSelected();
      }
      await loadChats();
    };

    const btnDelete = document.createElement("button");
    btnDelete.className = "iconbtn";
    btnDelete.textContent = "Delete";
    btnDelete.onclick = async (e) => {
      e.stopPropagation();
      if (!confirm("Delete this chat permanently?")) return;
      await api(`/api/chats/${c.id}`, { method:"DELETE" });
      if (c.id === currentChatId) currentChatId = null;
      await ensureChatSelected();
      await loadChats();
    };

    actions.append(btnRename, btnArchive, btnDelete);
    item.append(title, meta, actions);
    chatList.appendChild(item);
  }
}

async function ensureChatSelected(){
  if (currentChatId) return;
  const created = await api("/api/chats", {
    method:"POST",
    headers:{ "Content-Type":"application/json" },
    body: JSON.stringify({ title:"New Chat" })
  });
  currentChatId = created.chat.id;
  localStorage.setItem("currentChatId", currentChatId);
  await selectChat(currentChatId);
}

async function selectChat(chatId){
  currentChatId = chatId;
  localStorage.setItem("currentChatId", chatId);

  const j = await api(`/api/chats/${chatId}`);
  state.messages = (j.messages || []).map(m => ({
    id: m.id,
    role: m.role,
    content: m.content,
    ts: fmtTsFromEpoch(m.created_at),
    model: m.model || "",
    meta: m.meta_json || null
  }));

  await loadPrefs();
  renderChat();
  await loadChats();
}

async function appendToChat(role, content, meta_json=null){
  if (!currentChatId) return;
  await api(`/api/chats/${currentChatId}/append`, {
    method:"POST",
    headers:{ "Content-Type":"application/json" },
    body: JSON.stringify({ messages: [{ role, content, model: state.model, meta_json }] })
  });
}

/* ---------------- chat rendering ---------------- */

function msgNode(m) {
  const { role, content, ts, model, meta, id } = m;

  const wrap = document.createElement("div");
  wrap.className = `msg ${role === "user" ? "user" : role === "assistant" ? "assistant" : "system"}`;
  if (id != null) {
    wrap.dataset.msgId = String(id);   // for /jump selector
    wrap.id = `msg-${id}`;             // fallback for /jump
  }

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "U" : role === "assistant" ? "A" : "S";

  const bubble = document.createElement("div");
  bubble.className = "bubble";

  const metaEl = document.createElement("div");
  metaEl.className = "meta";

  const left = document.createElement("div");
  left.textContent = role.toUpperCase() + (model ? ` • ${model}` : "");

  const tools = document.createElement("div");
  tools.className = "tools";

  const right = document.createElement("div");
  right.textContent = ts || "";

  // Copy button
  const btnCopy = document.createElement("button");
  btnCopy.className = "iconbtn";
  btnCopy.textContent = "Copy";
  btnCopy.onclick = async () => {
    try {
      await navigator.clipboard.writeText(content || "");
      setStatus(true, "Copied");
    } catch {
      alert("Copy failed (clipboard blocked)");
    }
  };
  tools.appendChild(btnCopy);

  // Fork button
  if (id) {
    const btnFork = document.createElement("button");
    btnFork.className = "iconbtn";
    btnFork.textContent = "Fork";
    btnFork.onclick = async () => {
      if (!confirm("Fork/branch this chat at this point?")) return;
      const j = await api(
        `/api/chats/${currentChatId}/fork?msg_id=${encodeURIComponent(id)}`,
        { method: "POST" }
      );
      const newId = j?.chat?.id;
      if (newId) await selectChat(newId);
      closeSidebar();
    };
    tools.appendChild(btnFork);
  }

  metaEl.append(left, tools, right);

  const body = document.createElement("div");
  body.className = "content";
  body.textContent = content || "";

  bubble.append(metaEl, body);

  const mobj = parseMeta(meta);

  if (mobj?.stats?.lat_ms != null) {
    const s = mobj.stats;
    const extra = document.createElement("div");
    extra.className = "docMeta";
    const parts = [];
    parts.push(`lat ${Math.round(Number(s.lat_ms))}ms`);
    if (s.prompt_eval_count != null) parts.push(`prompt_toks ${s.prompt_eval_count}`);
    if (s.eval_count != null) parts.push(`gen_toks ${s.eval_count}`);
    extra.textContent = parts.join(" • ");
    bubble.appendChild(extra);
  }

  if (mobj?.sources?.length) {
    const box = document.createElement("div");
    box.className = "sources";
    box.innerHTML = `<b>Sources</b>`;

    mobj.sources.forEach((s, i) => {
      const row = document.createElement("div");
      row.className = "srcRow";

      const left2 = document.createElement("div");
      left2.innerHTML = `[S${i + 1}] <a href="#" data-chunk="${s.chunk_id}">${escapeHtml(s.filename)} • chunk ${s.chunk_index}</a>`;

      const right2 = document.createElement("div");
      right2.textContent = Number(s.score).toFixed(3);

      row.append(left2, right2);
      box.appendChild(row);
    });

    bubble.appendChild(box);
  }

  wrap.append(avatar, bubble);
  return { wrap, body };
}

function renderChat() {
  const wasAtBottom = isNearBottom();
  chatEl.innerHTML = "";
  const frag = document.createDocumentFragment();
  state.messages.forEach((m) => {
    const node = msgNode(m);
    if (m.role !== "user") node.body.innerHTML = renderLiteMarkdown(m.content || "");
    frag.appendChild(node.wrap);
  });
  chatEl.appendChild(frag);

  // Only auto-scroll if user was already at bottom
  if (wasAtBottom) {
    scrollToBottom(true, false); // Instant scroll for initial load
  } else {
    incrementNewMessages();
  }

  chatEl.querySelectorAll("[data-chunk]").forEach(a => {
    a.addEventListener("click", async (e) => {
      e.preventDefault();
      const cid = Number(a.getAttribute("data-chunk"));
      if (!cid) return;
      await openSourceModal(cid);
    });
  });

  // Restore search highlights if any
  if (state.searchHighlight) {
    searchInChat(state.searchHighlight);
  }

  // Prism highlight (if loaded)
  try { if (window.Prism?.highlightAllUnder) window.Prism.highlightAllUnder(chatEl); } catch {}
}

/* ---------------- modal ---------------- */

function openModal(title, bodyText){
  modalTitle.textContent = title || "Source";
  modalBody.textContent = bodyText || "";
  modalOverlay.classList.remove("hidden");
  modal.classList.remove("hidden");
}
function closeModal(){
  modalOverlay.classList.add("hidden");
  modal.classList.add("hidden");
}
btnModalClose?.addEventListener("click", closeModal);
modalOverlay?.addEventListener("click", closeModal);

async function openSourceModal(chunkId){
  try{
    const base = await api(`/api/chunks/${chunkId}`);
    const neigh = await api(`/api/chunks/${chunkId}/neighbors?span=1`);
    const lines = [];
    lines.push(`${base.filename} — chunk ${base.chunk_index} (id ${base.id})`);
    lines.push("");
    for (const c of neigh.chunks){
      lines.push(`--- chunk ${c.chunk_index} (id ${c.id}) ---`);
      lines.push(c.text || "");
      lines.push("");
    }
    openModal("Source", lines.join("\n"));
  } catch (e){
    openModal("Source", `Failed to load chunk: ${e}`);
  }
}

/* ---------------- settings + presets ---------------- */

function applySettingsToUI(){
  systemPromptEl.value = state.settings.system || "";
  tempEl.value = String(state.settings.temperature ?? 0.7);
  numCtxEl.value = String(state.settings.num_ctx ?? 4096);
  keepAliveEl.value = String(state.settings.keep_alive ?? "5m");
  topKEl.value = String(state.settings.top_k ?? 6);
  mmrToggle.checked = !!state.settings.use_mmr;
}

function readUIToSettings(){
  state.settings.system = systemPromptEl.value || "";
  state.settings.temperature = Number(tempEl.value || 0.7);
  state.settings.num_ctx = Number(numCtxEl.value || 4096);
  state.settings.keep_alive = keepAliveEl.value || "5m";
  state.settings.top_k = Number(topKEl.value || 6);
  state.settings.use_mmr = !!mmrToggle.checked;
  saveState();
}

function initPresets(){
  presetSelect.innerHTML = "";
  const opt0 = document.createElement("option");
  opt0.value = "";
  opt0.textContent = "— choose —";
  presetSelect.appendChild(opt0);

  PRESETS.forEach((p) => {
    const opt = document.createElement("option");
    opt.value = p.name;
    opt.textContent = p.name;
    presetSelect.appendChild(opt);
  });

  presetSelect.addEventListener("change", () => {
    const name = presetSelect.value;
    const p = PRESETS.find(x => x.name === name);
    if (!p) return;
    state.settings.temperature = p.temperature;
    state.settings.num_ctx = p.num_ctx;
    state.settings.top_k = p.top_k;
    state.settings.use_mmr = p.use_mmr;
    applySettingsToUI();
    saveState();
  });
}

btnSaveSettings?.addEventListener("click", async () => {
  readUIToSettings();
  closeSidebar();
});
btnResetSettings?.addEventListener("click", async () => {
  state.settings = { system:"", temperature:0.7, num_ctx:4096, keep_alive:"5m", top_k:6, use_mmr:false };
  applySettingsToUI();
  saveState();
});

/* ---------------- status + models ---------------- */

async function refreshStatusAndModels() {
  try {
    const j = await api("/api/status");
    if (j.ok) setStatus(true, `Ollama OK • ${j.version || "unknown"}`);
    else setStatus(false, j.error || "Ollama down");

    const mj = await api("/api/models");
    const models = mj.models || [];
    modelSelect.innerHTML = "";
    if (!models.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "No models found";
      modelSelect.appendChild(opt);
      state.model = "";
    } else {
      for (const name of models) {
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = name;
        modelSelect.appendChild(opt);
      }
      if (!state.model || !models.includes(state.model)) state.model = models[0];
    }
    modelSelect.value = state.model || "";
    saveState();
  } catch {
    setStatus(false, "Can't reach backend / Ollama");
  }
}

modelSelect.addEventListener("change", () => {
  state.model = modelSelect.value;
  saveState();
});

/* ---------------- compose helpers ---------------- */

function buildMessagesForRequest() {
  const msgs = [];
  if (state.settings.system?.trim()) {
    msgs.push({ role: "system", content: state.settings.system.trim() });
  }
  const recent = state.messages
    .filter(m => m.role === "user" || m.role === "assistant")
    .slice(-40)
    .map(m => ({ role: m.role, content: m.content }));
  return msgs.concat(recent);
}

async function decideModel(query, ragEnabled) {
  const res = await fetch("/api/decide_model", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, rag_enabled: !!ragEnabled }),
  });
  const j = await res.json();
  if (j?.model && Array.from(modelSelect.options).some(o => o.value === j.model)) {
    state.model = j.model;
    modelSelect.value = j.model;
    saveState();
  }
  return j;
}

/* ---------------- rag toggle (DB) ---------------- */

ragToggle?.addEventListener("change", async () => {
  await savePrefs({ rag_enabled: !!ragToggle.checked });
  updateRagSummary();
});

/* ---------------- send / stream ---------------- */

async function runSlashCommand(text) {
  const t = (text || "").trim();
  if (!t.startsWith("/")) return null;

  const parts = t.split(/\s+/);
  const cmd = (parts[0] || "").toLowerCase();
  const rest = t.slice(parts[0].length).trim();

  async function post(path, payload = null) {
    const res = await fetch(path, {
      method: "POST",
      headers: payload ? { "Content-Type": "application/json" } : undefined,
      body: payload ? JSON.stringify(payload) : undefined,
    });
    const j = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(j.error || j.detail || `HTTP ${res.status}`);
    return j;
  }

  async function get(path) {
    const res = await fetch(path);
    const j = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(j.error || j.detail || `HTTP ${res.status}`);
    return j;
  }

  if (!currentChatId) return { kind: "local", text: "No chat selected." };

  if (cmd === "/pin") {
    const j = await post(`/api/chats/${currentChatId}/toggle_pin`);
    await loadChats();
    return { kind: "local", text: `Pinned: ${j.pinned ? "ON" : "OFF"}` };
  }

  if (cmd === "/archive") {
    const j = await post(`/api/chats/${currentChatId}/toggle_archive`);
    await loadChats();
    return { kind: "local", text: `Archived: ${j.archived ? "ON" : "OFF"}` };
  }

  if (cmd === "/find") {
    if (!rest) return { kind: "local", text: "Usage: /find <query>" };
    const qs = new URLSearchParams({ q: rest, limit: "25", offset: "0" });
    const j = await get(`/api/chats/${currentChatId}/search?${qs.toString()}`);
    const hits = j.hits || [];
    if (!hits.length) return { kind: "local", text: `No hits in this chat for: ${rest}` };
    const lines = [
      `**/find** results for \`${rest}\` (${hits.length}):`,
      "",
      ...hits.map(h => `- \`#${h.msg_id}\` **${h.role}** @ ${new Date(h.created_at*1000).toLocaleString()} — ${h.snippet}`)
    ];
    return { kind: "local", text: lines.join("\n") };
  }

  if (cmd === "/search") {
    if (!rest) return { kind: "local", text: "Usage: /search <query>" };
    const qs = new URLSearchParams({ q: rest, limit: "25", offset: "0" });
    const j = await get(`/api/search?${qs.toString()}`);
    const hits = j.hits || [];
    if (!hits.length) return { kind: "local", text: `No hits across chats for: ${rest}` };
    const lines = [
      `**/search** results for \`${rest}\` (${hits.length}):`,
      "",
      ...hits.map(h => `- **${h.chat_title}** (\`${h.chat_id}\`) \`#${h.msg_id}\` **${h.role}** — ${h.snippet}`)
    ];
    return { kind: "local", text: lines.join("\n") };
  }

  if (cmd === "/tags") {
    const j = await get(`/api/chats/${currentChatId}/tags`);
    const tags = j.tags || [];
    return { kind: "local", text: tags.length ? `Tags: ${tags.join(", ")}` : "No tags on this chat." };
  }

  if (cmd === "/tag") {
    const sub = (parts[1] || "").toLowerCase();
    const val = parts.slice(2).join(" ").trim();
    if (!sub || !val) return { kind: "local", text: "Usage: /tag add <name>  OR  /tag rm <name>" };
    if (sub === "add") {
      const j = await fetch(`/api/chats/${currentChatId}/tags/add`, { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify({ tag: val })}).then(r=>r.json());
      await loadChats();
      return { kind: "local", text: `Tags: ${(j.tags||[]).join(", ")}` };
    }
    if (sub === "rm" || sub === "remove" || sub === "del") {
      const j = await fetch(`/api/chats/${currentChatId}/tags/remove`, { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify({ tag: val })}).then(r=>r.json());
      await loadChats();
      return { kind: "local", text: `Tags: ${(j.tags||[]).join(", ")}` };
    }
    return { kind: "local", text: "Usage: /tag add <name>  OR  /tag rm <name>" };
  }

  if (cmd === "/set") {
    const key = (parts[1] || "").toLowerCase();
    const val = parts.slice(2).join(" ").trim();
    if (!key || !val) return { kind: "local", text: "Usage: /set <model|temp|ctx|top_k|mmr|lambda> <value>" };

    const payload = {};
    if (key === "model") payload.model = val;
    else if (key === "temp") payload.temperature = Number(val);
    else if (key === "ctx") payload.num_ctx = parseInt(val, 10);
    else if (key === "top_k") payload.top_k = parseInt(val, 10);
    else if (key === "mmr") payload.use_mmr = (val === "1" || val.toLowerCase() === "true" || val.toLowerCase() === "on");
    else if (key === "lambda") payload.mmr_lambda = Number(val);
    else return { kind: "local", text: "Keys: model, temp, ctx, top_k, mmr, lambda" };

    const res = await fetch(`/api/chats/${currentChatId}/settings`, { method:"POST", headers:{ "Content-Type":"application/json" }, body: JSON.stringify(payload) });
    const j = await res.json().catch(()=> ({}));
    if (!res.ok) throw new Error(j.detail || j.error || `HTTP ${res.status}`);
    return { kind: "local", text: `Saved settings: ${JSON.stringify(j.settings || {})}` };
  }

  if (cmd === "/summary") {
    const res = await fetch(`/api/chats/${currentChatId}/summary`, { method:"POST" });
    const j = await res.json().catch(()=> ({}));
    if (!res.ok) throw new Error(j.detail || j.error || `HTTP ${res.status}`);
    return { kind: "local", text: j.summary || "(no summary)" };
  }

  if (cmd === "/jump") {
    const id = parseInt(parts[1] || "", 10);
    if (!id) return { kind: "local", text: "Usage: /jump <msg_id>" };

    const qs = new URLSearchParams({ msg_id: String(id), span: "20" });
    const j = await get(`/api/chats/${currentChatId}/jump?${qs.toString()}`);

    state.messages = (j.messages || []).map(m => ({
      id: m.id, role: m.role, content: m.content, ts: fmtTsFromEpoch(m.created_at), model: m.model, meta: m.meta_json
    }));
    saveState();
    renderChat();

    setTimeout(() => {
      const el = document.querySelector(`[data-msg-id="${id}"]`) || document.getElementById(`msg-${id}`);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 50);

    return { kind: "local", text: `Jumped near message #${id}` };
  }

  if (cmd === "/autosummary") {
    const sub = (parts[1] || "").toLowerCase();
    if (!currentChatId) return { kind: "local", text: "No chat selected." };

    if (sub === "on" || sub === "off") {
      const enabled = (sub === "on");
      await fetch(`/api/chats/${currentChatId}/settings`, {
        method:"POST",
        headers:{ "Content-Type":"application/json" },
        body: JSON.stringify({ autosummary_enabled: enabled })
      });
      return { kind: "local", text: `Autosummary: ${enabled ? "ON" : "OFF"}` };
    }

    if (sub === "every") {
      const n = parseInt(parts[2] || "", 10);
      if (!n || n < 4 || n > 80) { return { kind: "local", text: "Usage: /autosummary every 4..80" }; }
      await fetch(`/api/chats/${currentChatId}/settings`, {
        method:"POST",
        headers:{ "Content-Type":"application/json" },
        body: JSON.stringify({ autosummary_every: n })
      });
      return { kind: "local", text: `Autosummary every ${n} msgs` };
    }

    if (sub === "now") {
      const res = await fetch(`/api/chats/${currentChatId}/autosummary?force=1`, { method:"POST" });
      const j = await res.json().catch(()=> ({}));
      return { kind: "local", text: j.summary ? "Summary added to chat." : "No summary produced." };
    }

    return { kind: "local", text: "Usage: /autosummary on | off | every <N> | now" };
  }

  if (cmd === "/research") {
    if (!rest) return { kind: "local", text: "Usage: /research <question>" };
    const payload = {
      chat_id: currentChatId || null,
      query: rest,
      mode: "deep",
      use_docs: true,
      use_web: true,
      rounds: 3,
      pages_per_round: 5,
      doc_top_k: 6,
      web_top_k: 6
    };
    const j = await post("/api/research/run", payload);
    state.lastResearchRunId = j.run_id;
    saveState();
    return { kind: "local", text: `Run: ${j.run_id}\n\n${j.answer}` };
  }

  if (cmd === "/trace") {
    const id = parts[1] || state.lastResearchRunId;
    if (!id) return { kind: "local", text: "Usage: /trace <run_id>" };
    const j = await get(`/api/research/${id}/trace?limit=200&offset=0`);
    const lines = (j.trace || []).map(t => `- ${t.step}: ${JSON.stringify(t.payload || {})}`);
    return { kind: "local", text: `Trace for ${id}:\n\n` + (lines.join("\n") || "(empty)") };
  }

  if (cmd === "/sources") {
    const id = parts[1] || state.lastResearchRunId;
    if (!id) return { kind: "local", text: "Usage: /sources <run_id>" };
    const j = await get(`/api/research/${id}/sources`);
    const src = j.sources || [];
    const lines = src.map(s => `- #${s.id} ${s.source_type.toUpperCase()} ${s.domain || ""} ${s.title || ""} (pinned:${s.pinned}, excl:${s.excluded}) score:${(s.score||0).toFixed?.(3) ?? s.score}`);
    return { kind: "local", text: `Sources for ${id}:\n\n` + (lines.join("\n") || "(none)") };
  }

  if (cmd === "/claims") {
    const id = parts[1] || state.lastResearchRunId;
    if (!id) return { kind: "local", text: "Usage: /claims <run_id>" };
    const j = await get(`/api/research/${id}/claims`);
    const cs = j.claims || [];
    const lines = cs.map(c => `- ${c.status.toUpperCase()} — ${c.claim}  ${JSON.stringify(c.citations||[])}`);
    return { kind: "local", text: `Claims for ${id}:\n\n` + (lines.join("\n") || "(none)") };
  }

  return { kind: "local", text: `Unknown command: ${cmd}` };
}

async function send() {
  if (isGenerating) return;
  const text = (promptEl.value || "").trim();
  if (!text) return;

  // Hide slash palette when sending
  closeSlash();

  if (text.startsWith("/")) {
    setGenerating(true);
    try {
      const result = await runSlashCommand(text);
      if (result) {
        const userMsg = { id: null, role: "user", content: text, ts: nowTs() };
        state.messages.push(userMsg);
        await appendToChat("user", text);

        const assistant = { id: null, role: "assistant", content: result.text, ts: nowTs(), model: "system", meta: { slash: true } };
        state.messages.push(assistant);
        await appendToChat("assistant", assistant.content, assistant.meta);

        renderChat();
        promptEl.value = "";
        autoGrow();
        await loadChats();
        return;
      }
    } catch (e) {
      const err = `Command failed: ${e}`;
      const userMsg = { id: null, role: "user", content: text, ts: nowTs() };
      state.messages.push(userMsg);
      await appendToChat("user", text);

      const assistant = { id: null, role: "assistant", content: err, ts: nowTs(), model: "system", meta: { slash: true, error: true } };
      state.messages.push(assistant);
      await appendToChat("assistant", assistant.content, assistant.meta);

      renderChat();
      promptEl.value = "";
      autoGrow();
      return;
    } finally {
      setGenerating(false);
    }
  }

  lastSources = [];

  const userMsg = { id: null, role: "user", content: text, ts: nowTs() };
  state.messages.push(userMsg);
  await appendToChat("user", text);

  const assistant = { id: null, role: "assistant", content: "", ts: nowTs(), model: state.model, meta: null };
  state.messages.push(assistant);

  saveState();
  renderChat();
  promptEl.value = "";
  autoGrow();

  setGenerating(true);
  abortCtl = new AbortController();

  const shouldHint = !isNearBottom();
  if (shouldHint) showScrollHint(true);

  const lastWrap = chatEl.lastElementChild;
  const liveBody = lastWrap?.querySelector?.(".content");
  let assistantSaved = false;

  const ragEnabled = !!ragToggle?.checked;
  if (autoModelToggle?.checked) {
    try { await decideModel(text, ragEnabled); } catch {}
  }

  const docSel = state.prefs?.doc_ids ?? null;

  const started = performance.now();
  let finalStats = null;

  try {
    const payload = {
      model: state.model,
      messages: buildMessagesForRequest(),
      options: {
        temperature: state.settings.temperature,
        num_ctx: state.settings.num_ctx,
      },
      keep_alive: state.settings.keep_alive,
      rag: {
        enabled: ragEnabled,
        top_k: Number(state.settings.top_k || 6),
        doc_ids: docSel, // null => all docs
        embed_model: "embeddinggemma",
        use_mmr: !!state.settings.use_mmr,
        mmr_lambda: 0.75,
      }
    };

    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: abortCtl.signal,
    });

     if (!res.ok) {
       const errorData = await res.json().catch(() => ({}));
       const errorMsg = errorData.detail || errorData.error || `HTTP ${res.status}`;
       promptEl.value = originalText;
       autoGrow();
       showError(`Failed to send message: ${errorMsg}`, "retry", () => { promptEl.value = originalText; autoGrow(); send(); });
       return;
     }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";

    const handleLine = (line) => {
      if (!line) return;
      let data;
      try { data = JSON.parse(line); } catch { return; }

      if (data?.type === "sources") {
        lastSources = data.sources || [];
        assistant.meta = { ...(assistant.meta || {}), sources: lastSources };

        if (lastWrap) {
          let box = lastWrap.querySelector(".sources");
          if (!box) {
            box = document.createElement("div");
            box.className = "sources";
            box.innerHTML = "<b>Sources</b>";
            lastWrap.querySelector(".bubble")?.appendChild(box);
          }
          box.querySelectorAll(".srcRow").forEach(x => x.remove());
          lastSources.forEach((s,i)=>{
            const row = document.createElement("div");
            row.className = "srcRow";
            const left = document.createElement("div");
            left.innerHTML = `[S${i+1}] <a href="#" data-chunk="${s.chunk_id}">${escapeHtml(s.filename)} • chunk ${s.chunk_index}</a>`;
            const right = document.createElement("div");
            right.textContent = Number(s.score).toFixed(3);
            row.append(left,right);
            box.appendChild(row);
          });
        }
        return;
      }

      if (data?.type === "error" && data?.error) {
        assistant.content += `\n\n[error] ${data.error}`;
        if (liveBody) liveBody.innerHTML = renderLiteMarkdown(assistant.content);
        return;
      }

      // Ollama "done" frame carries stats (varies by version)
      if (data?.done === true) {
        finalStats = {
          prompt_eval_count: data.prompt_eval_count ?? data.prompt_eval_tokens ?? null,
          eval_count: data.eval_count ?? data.eval_tokens ?? null,
          total_duration: data.total_duration ?? null,
        };
      }

      const chunk = data?.message?.content ?? data?.response ?? "";
      if (chunk) {
        assistant.content += chunk;
        if (liveBody) {
          liveBody.textContent = assistant.content;
          if (isNearBottom()) scrollToBottom();
          else showScrollHint(true);
        }
      }
      if (data?.error) assistant.content += `\n\n[error] ${data.error}`;
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n")) !== -1) {
        const line = buf.slice(0, idx).trim();
        buf = buf.slice(idx + 1);
        handleLine(line);
      }
    }
    for (const line of buf.split("\n")) handleLine(line.trim());

    if (liveBody) liveBody.innerHTML = renderLiteMarkdown(assistant.content);

    const latMs = performance.now() - started;
    assistant.meta = {
      ...(assistant.meta || {}),
      sources: lastSources,
      stats: { ...(finalStats || {}), lat_ms: latMs }
    };

    saveState();

    await appendToChat("assistant", assistant.content, assistant.meta);
    assistantSaved = true;

    try { await fetch(`/api/chats/${currentChatId}/autosummary`, { method:"POST" }); } catch {}

    await loadChats();
   } catch (e) {
     if (String(e?.name) === "AbortError") {
       assistant.content += "\n\n[stopped]";
       assistant.meta = { ...(assistant.meta || {}), stopped: true, sources: lastSources };
       setStatus(true, "Generation stopped");
     } else {
       const errorMsg = `Request failed: ${e}`;
       assistant.content = errorMsg;
       assistant.meta = { ...(assistant.meta || {}), error: String(e), sources: lastSources };
       promptEl.value = originalText;
       autoGrow();
       showError(errorMsg, "retry", () => { promptEl.value = originalText; autoGrow(); send(); });
     }
     if (liveBody) liveBody.innerHTML = renderLiteMarkdown(assistant.content);
     saveState();

    if (!assistantSaved && assistant.content.trim()) {
      try {
        await appendToChat("assistant", assistant.content, assistant.meta || null);
        assistantSaved = true;
        await loadChats();
      } catch {}
    }
  } finally {
    setGenerating(false);
    abortCtl = null;
    renderChat();
  }
}

/* ---------------- edit last user + regen ---------------- */

btnEditLast?.addEventListener("click", async () => {
  if (isGenerating) return;

  await selectChat(currentChatId);
  const lastUser = [...state.messages].reverse().find(m => m.role === "user");
  if (!lastUser?.id) {
    alert("No user message to edit");
    return;
  }

  // Create edit modal
  const editModal = document.createElement("div");
  editModal.className = "edit-modal-overlay";
  editModal.innerHTML = `
    <div class="edit-modal">
      <div class="edit-modal-header">
        <h3>Edit Message</h3>
        <button class="edit-modal-close iconbtn">✕</button>
      </div>
      <textarea class="edit-modal-textarea">${escapeHtml(lastUser.content || "")}</textarea>
      <div class="edit-modal-actions">
        <button class="edit-modal-cancel btn">Cancel</button>
        <button class="edit-modal-save btn primary">Save & Resend</button>
      </div>
    </div>
  `;

  document.body.appendChild(editModal);

  const textarea = editModal.querySelector(".edit-modal-textarea");
  const cancelBtn = editModal.querySelector(".edit-modal-cancel");
  const saveBtn = editModal.querySelector(".edit-modal-save");
  const closeBtn = editModal.querySelector(".edit-modal-close");

  textarea.focus();
  textarea.setSelectionRange(textarea.value.length, textarea.value.length);

  const closeModal = () => {
    editModal.remove();
  };

  cancelBtn.addEventListener("click", closeModal);
  closeBtn.addEventListener("click", closeModal);
  editModal.addEventListener("click", (e) => {
    if (e.target === editModal) closeModal();
  });

  saveBtn.addEventListener("click", async () => {
    const newContent = textarea.value.trim();
    if (!newContent) {
      alert("Message cannot be empty");
      return;
    }

    try {
      await api(`/api/chats/${currentChatId}/edit_last`, {
        method:"POST",
        headers:{ "Content-Type":"application/json" },
        body: JSON.stringify({ msg_id: lastUser.id, new_content: newContent })
      });

      await selectChat(currentChatId);
      promptEl.value = newContent;
      autoGrow();
      closeModal();
      await send();
    } catch (e) {
      alert(`Failed to edit message: ${e}`);
    }
  });

  // Handle Enter to save (Ctrl+Enter for new line)
  textarea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.ctrlKey && !e.shiftKey) {
      e.preventDefault();
      saveBtn.click();
    }
  });
});

/* ---------------- clear/export ---------------- */

btnClear?.addEventListener("click", async () => {
  if (isGenerating) return;
  if (!currentChatId) return;
  await fetch(`/api/chats/${currentChatId}/clear`, { method:"POST" });
  await selectChat(currentChatId);
  await loadChats();
});

btnExportChat?.addEventListener("click", (e) => {
  e.stopPropagation();
  toggleExportMenu();
});

document.addEventListener("click", (e) => {
  if (!e.target.closest(".export-dropdown")) {
    hideExportMenu();
  }
});

document.querySelectorAll(".export-option").forEach(option => {
  option.addEventListener("click", async (e) => {
    const format = e.target.dataset.format;
    await exportChat(format);
    hideExportMenu();
  });
});

function toggleExportMenu() {
  const menu = document.querySelector(".export-menu");
  if (!menu) return;
  menu.classList.toggle("hidden");
}

function hideExportMenu() {
  const menu = document.querySelector(".export-menu");
  if (!menu) menu.classList.add("hidden");
}

async function exportChat(format) {
  if (!currentChatId) return;

  try {
    let mimeType, filename, content;

    if (format === "json") {
      const res = await fetch(`/api/chats/${currentChatId}`);
      const data = await res.json();
      content = JSON.stringify(data, null, 2);
      mimeType = "application/json";
      filename = `chat-${currentChatId}.json`;
    } else if (format === "txt") {
      const res = await fetch(`/api/export/chat/${currentChatId}`);
      content = await res.text();
      content = content.replace(/#+\s/g, '').replace(/\*\*(.*?)\*\*/g, '$1'); // Remove markdown formatting
      mimeType = "text/plain";
      filename = `chat-${currentChatId}.txt`;
    } else {
      // Default markdown
      const res = await fetch(`/api/export/chat/${currentChatId}`);
      content = await res.text();
      mimeType = "text/markdown";
      filename = `chat-${currentChatId}.md`;
    }

    const blob = new Blob([content], { type: mimeType });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);

    setStatus(true, `Exported as ${format.toUpperCase()}`);
  } catch (e) {
    alert(`Export failed: ${e}`);
  }
}

/* ---------------- init ---------------- */

(async function init(){
  loadState();
  applyTheme(state.theme, false);
  initPresets();
  applySettingsToUI();

  await ensureChatSelected();
  await loadChats();
  await selectChat(currentChatId); // loads prefs too
  await loadDocs();
  renderChat();
  closeSidebar();

  refreshStatusAndModels();
  setInterval(refreshStatusAndModels, 12000);

  if (showArchived) showArchived.addEventListener("change", loadChats);
  if (chatSearch) chatSearch.addEventListener("input", loadChats);

  btnNewChat?.addEventListener("click", async () => {
    const created = await api("/api/chats", {
      method:"POST",
      headers:{ "Content-Type":"application/json" },
      body: JSON.stringify({ title:"New Chat" })
    });
    currentChatId = created.chat.id;
    localStorage.setItem("currentChatId", currentChatId);
    if (showArchived) showArchived.checked = false;
    await selectChat(currentChatId);
    await loadDocs();
    updateRagSummary();
  });

  updateRagSummary();
  // Theme toggle
  btnTheme?.addEventListener("click", () => {
    toggleTheme();
    setStatus(true, `Switched to ${state.theme} theme`);
  });

  // Load slash commands and initialize command palette
  loadSlashCommands();
})();
