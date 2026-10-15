/* ============================================================
   WorkBuddy 前端逻辑
   - 拉取专家/模型列表
   - SSE 流式对话（单专家 / 智囊团 / 工具调用 / Artifact）
   - Markdown 渲染 + Artifact 实时预览
   ============================================================ */
"use strict";

const $ = (id) => document.getElementById(id);

const state = {
  mode: "auto",
  agents: [],        // 全部专家
  models: { providers: [], default_mock: true },
  currentText: "",   // 正在流式拼接的助手文本
  streaming: false,
};

const MODE_LABEL = { auto: "自动路由", agent: "单专家", swarm: "智囊团" };

/* ---------- 初始化 ---------- */
async function init() {
  await Promise.all([loadAgents(), loadModels()]);
  bindEvents();
  triggerReveal();
}

async function loadAgents() {
  try {
    const r = await fetch("api/agents");
    const data = await r.json();
    state.agents = data.agents || [];
    fillAgentSelect();
    fillExpertList();
  } catch (e) {
    console.error("loadAgents failed", e);
  }
}

async function loadModels() {
  try {
    const r = await fetch("api/models");
    const data = await r.json();
    state.models = data;
    fillProviderSelect();
  } catch (e) {
    console.error("loadModels failed", e);
  }
}

/* ---------- 选择器填充 ---------- */
function fillProviderSelect() {
  const sel = $("providerSelect");
  sel.innerHTML = "";
  const provs = state.models.providers || [];
  // 默认选中第一个可用（非空 mock）provider；都没有则 mock
  let defaultId = "mock";
  for (const p of provs) {
    if (p.id !== "mock" && p.available) { defaultId = p.id; break; }
  }
  for (const p of provs) {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = p.id === "mock" ? "Mock（离线演示）" : `${p.name}`;
    opt.disabled = !p.available && p.id !== "mock";
    if (opt.disabled) opt.textContent += " · 未配置";
    if (p.id === defaultId) opt.selected = true;
    sel.appendChild(opt);
  }
  fillModelSelect();
}

function fillModelSelect() {
  const psel = $("providerSelect");
  const msel = $("modelSelect");
  const pid = psel.value;
  const prov = (state.models.providers || []).find((p) => p.id === pid);
  msel.innerHTML = "";
  const models = prov ? prov.models : ["mock"];
  for (const m of models) {
    const opt = document.createElement("option");
    opt.value = m;
    opt.textContent = m;
    msel.appendChild(opt);
  }
}

function fillAgentSelect() {
  const sel = $("agentSelect");
  sel.innerHTML = "";
  for (const a of state.agents) {
    const opt = document.createElement("option");
    opt.value = a.tag;
    opt.textContent = `${a.name} · ${a.role}`;
    sel.appendChild(opt);
  }
  if (!sel.value && state.agents[0]) sel.value = state.agents[0].tag;
}

function fillExpertList() {
  const box = $("expertList");
  box.innerHTML = "";
  for (const a of state.agents) {
    if (a.tag === "general") continue;
    const label = document.createElement("label");
    label.className = "check";
    const inp = document.createElement("input");
    inp.type = "checkbox";
    inp.value = a.tag;
    inp.checked = ["researcher", "coder", "critic"].includes(a.tag);
    const bx = document.createElement("span");
    bx.className = "box";
    const txt = document.createElement("span");
    txt.textContent = `${a.name}`;
    label.append(inp, bx, txt);
    box.appendChild(label);
  }
}

/* ---------- 事件绑定 ---------- */
function bindEvents() {
  // 模式分段
  const seg = $("modeSeg");
  seg.querySelectorAll(".seg-btn").forEach((b) => {
    b.addEventListener("click", () => setMode(b.dataset.mode));
  });
  setMode("auto");

  $("providerSelect").addEventListener("change", fillModelSelect);
  $("sendBtn").addEventListener("click", send);
  $("resetBtn").addEventListener("click", resetSession);
  $("input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  });
  $("menuToggle").addEventListener("click", toggleDrawer);
}

function setMode(mode) {
  state.mode = mode;
  const seg = $("modeSeg");
  const btns = seg.querySelectorAll(".seg-btn");
  let active = null;
  btns.forEach((b) => {
    const on = b.dataset.mode === mode;
    b.classList.toggle("active", on);
    if (on) active = b;
  });
  // 滑动药丸
  const pill = seg.querySelector(".seg-pill");
  if (active && pill) {
    pill.style.width = active.offsetWidth + "px";
    pill.style.transform = `translateX(${active.offsetLeft - 4}px)`;
  }
  $("agentPanel").hidden = mode !== "agent";
  $("swarmPanel").hidden = mode !== "swarm";
  $("modeBadge").textContent = MODE_LABEL[mode];
}

function triggerReveal() {
  requestAnimationFrame(() => {
    document.querySelectorAll(".sidebar .reveal").forEach((el) => el.classList.add("in"));
  });
}

function toggleDrawer() {
  const sb = $("sidebar");
  sb.classList.toggle("open");
  let scrim = document.querySelector(".scrim");
  if (sb.classList.contains("open") && !scrim) {
    scrim = document.createElement("div");
    scrim.className = "scrim";
    scrim.addEventListener("click", toggleDrawer);
    document.body.appendChild(scrim);
  } else if (!sb.classList.contains("open") && scrim) {
    scrim.remove();
  }
}

/* ---------- 发送 / SSE ---------- */
function selectedExperts() {
  return Array.from($("expertList").querySelectorAll("input:checked")).map((i) => i.value);
}

async function send() {
  if (state.streaming) return;
  const input = $("input");
  const msg = input.value.trim();
  if (!msg) return;
  input.value = "";

  const sessionId = $("sessionId").value.trim() || "default";
  const provider = $("providerSelect").value;
  const model = $("modelSelect").value;

  appendMessage("user", msg);
  resetActivity();
  resetArtifacts();
  setStatus("streaming", "生成中…");
  state.streaming = true;
  $("sendBtn").disabled = true;
  state.currentText = "";

  const body = {
    session_id: sessionId,
    message: msg,
    mode: state.mode,
    provider,
    model,
  };
  if (state.mode === "agent") body.agent = $("agentSelect").value;
  if (state.mode === "swarm") body.agents = selectedExperts();

  try {
    await streamChat(body);
  } catch (e) {
    addActivity("error", `请求失败：${e.message}`);
  } finally {
    state.streaming = false;
    $("sendBtn").disabled = false;
    setStatus("idle", "");
  }
}

async function streamChat(body) {
  const resp = await fetch("api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    addActivity("error", `HTTP ${resp.status}`);
    return;
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split("\n\n");
    buf = parts.pop() || "";
    for (const chunk of parts) {
      parseSSE(chunk);
    }
  }
  // 收尾：把助手文本渲染为 Markdown
  finalizeAssistant();
}

function parseSSE(chunk) {
  let event = "message";
  const dataLines = [];
  for (const line of chunk.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return;
  let payload;
  try { payload = JSON.parse(dataLines.join("")); } catch { return; }
  handleEvent(event, payload);
}

function handleEvent(event, data) {
  switch (event) {
    case "meta": {
      $("modeBadge").textContent = MODE_LABEL[data.mode] || data.mode;
      $("providerBadge").textContent = data.provider || "mock";
      const mb = $("modelBadge");
      mb.textContent = data.model || "mock";
      mb.classList.toggle("accent", data.mock === false);
      showRouting(data);
      break;
    }
    case "agent_start":
      ensureAssistant(data.name, data.color);
      addActivity("agent", `${data.name} 开始处理`, data.color);
      break;
    case "thought":
      addActivity("thought", data.text);
      break;
    case "tool_call":
      addActivity("tool", `⚙ ${data.tool}(${truncate(data.args || "", 80)})`, data.color);
      break;
    case "tool_result":
      addActivity("result", data.ok ? (data.result || "") : `错误：${data.result || ""}`);
      break;
    case "token":
      appendToken(data.text);
      break;
    case "swarm_view":
      addActivity("expert", `${data.name} · 置信 ${(data.confidence * 100).toFixed(0)}%`, data.color,
        data.text);
      break;
    case "swarm_consensus":
      addActivity("consensus", `共识度 ${(data.value * 100).toFixed(0)}%`);
      break;
    case "artifact":
      addArtifact(data);
      break;
    case "error":
      addActivity("error", `错误：${data.message}`);
      break;
    case "done":
      break;
  }
}

/* ---------- 消息渲染 ---------- */
function appendMessage(role, text) {
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "你" : "WB";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  wrap.append(avatar, bubble);
  $("messages").appendChild(wrap);
  scrollMessages();
  return wrap;
}

let assistantWrap = null;
let assistantBubble = null;

function ensureAssistant(name, color) {
  assistantWrap = document.createElement("div");
  assistantWrap.className = "msg assistant";
  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = "WB";
  avatar.style.background = color || "var(--color-accent)";
  assistantBubble = document.createElement("div");
  assistantBubble.className = "bubble";
  assistantBubble.innerHTML = '<span class="cursor"></span>';
  assistantWrap.append(avatar, assistantBubble);
  $("messages").appendChild(assistantWrap);
  scrollMessages();
}

function appendToken(text) {
  if (!assistantBubble) ensureAssistant("助手", "var(--color-accent)");
  state.currentText += text;
  assistantBubble.textContent = state.currentText;
  const cur = document.createElement("span");
  cur.className = "cursor";
  assistantBubble.appendChild(cur);
  scrollMessages();
}

function finalizeAssistant() {
  if (assistantBubble && state.currentText) {
    assistantBubble.innerHTML = marked.parse(state.currentText);
    state.currentText = "";
  }
  assistantWrap = null;
  assistantBubble = null;
}

/* ---------- 右侧轨迹 ---------- */
function resetActivity() {
  $("activity").innerHTML = "";
  assistantWrap = null;
  assistantBubble = null;
}

function addActivity(kind, text, color, full) {
  const box = $("activity");
  const empty = box.querySelector(".empty");
  if (empty) empty.remove();
  const card = document.createElement("div");
  card.className = "act-card";
  const head = document.createElement("div");
  head.className = "act-head";
  const dot = document.createElement("span");
  dot.className = "act-dot";
  dot.style.background = color || defaultColor(kind);
  const label = document.createElement("span");
  label.textContent = headLabel(kind);
  head.append(dot, label);
  if (kind === "expert" || kind === "consensus") {
    const c = document.createElement("span");
    c.className = "conf";
    c.textContent = kind === "consensus" ? text : "";
    head.appendChild(c);
  }
  card.appendChild(head);
  if (text) {
    const line = document.createElement("div");
    line.className = "act-line " + lineClass(kind);
    line.textContent = text;
    card.appendChild(line);
  }
  if (full) {
    const line = document.createElement("div");
    line.className = "act-line";
    line.textContent = full;
    card.appendChild(line);
  }
  box.appendChild(card);
}

function defaultColor(kind) {
  return {
    agent: "var(--color-accent)", thought: "var(--color-faint)",
    tool: "var(--color-warn)", result: "var(--color-success)",
    expert: "var(--color-accent)", consensus: "var(--color-accent)",
    route: "var(--color-signal)", error: "var(--color-danger)",
  }[kind] || "var(--color-muted)";
}
function headLabel(kind) {
  return {
    agent: "专家", thought: "思考", tool: "工具调用", result: "工具结果",
    expert: "专家观点", consensus: "综合", route: "路由判定", error: "错误",
  }[kind] || "事件";
}

/* 展示 TypeSafe(Jev) 的路由判定：选中专家 + 置信度 + 是否升级智囊团 */
function showRouting(meta) {
  const r = meta.routing;
  if (!r) return;
  if (r.source === "typesafe") {
    const pct = Math.round((r.confidence || 0) * 100);
    let extra = "";
    if (meta.route_reason === "needs_collab") extra = " · 需多角度协作 → 智囊团";
    else if (meta.route_reason === "low_confidence") extra = " · 置信不足 → 智囊团";
    const dist = Object.entries(r.probabilities || {})
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `${k} ${(v * 100).toFixed(0)}%`)
      .join("　");
    addActivity("route", `Jev → ${r.agent} · 置信 ${pct}%${extra}`, undefined,
      `模型 ${r.model}　协作需求 ${r.needs_collab == null ? "-" : (r.needs_collab * 100).toFixed(0) + "%"}\n${dist}`);
  } else if (r.source === "keyword") {
    addActivity("route", r.fallback_reason
      ? `关键词路由（Jev 不可用，已降级：${truncate(r.fallback_reason, 60)}）`
      : "关键词路由", undefined, r.fallback_reason || "");
  }
}
function lineClass(kind) {
  return { thought: "thought", tool: "tool", result: "result" }[kind] || "";
}

/* ---------- Artifact ---------- */
function resetArtifacts() {
  $("artifacts").innerHTML = "";
}

function addArtifact(a) {
  const box = $("artifacts");
  const empty = box.querySelector(".empty");
  if (empty) empty.remove();
  const card = document.createElement("div");
  card.className = "art-card";
  const head = document.createElement("div");
  head.className = "art-head";
  const title = document.createElement("span");
  title.textContent = a.title || a.type;
  const tag = document.createElement("span");
  tag.className = "art-tag";
  tag.textContent = a.type;
  const actions = document.createElement("div");
  actions.className = "art-actions";
  head.append(title, tag, actions);

  const body = document.createElement("div");
  body.className = "art-body";
  if (a.type === "html") {
    const iframe = document.createElement("iframe");
    iframe.srcdoc = a.content;
    iframe.sandbox = "allow-scripts";
    body.appendChild(iframe);
    const dl = document.createElement("a");
    dl.textContent = "下载";
    dl.href = "data:text/html;charset=utf-8," + encodeURIComponent(a.content);
    dl.download = (a.title || "artifact") + ".html";
    actions.appendChild(dl);
  } else {
    const pre = document.createElement("pre");
    pre.textContent = a.content;
    body.appendChild(pre);
    const copy = document.createElement("button");
    copy.textContent = "复制";
    copy.addEventListener("click", () => navigator.clipboard.writeText(a.content));
    actions.appendChild(copy);
  }
  card.append(head, body);
  box.appendChild(card);
}

/* ---------- 杂项 ---------- */
function setStatus(stateName, text) {
  const s = $("status");
  s.className = "status" + (stateName === "idle" ? " idle" : "");
  s.textContent = text;
}
function scrollMessages() {
  const m = $("messages");
  m.scrollTop = m.scrollHeight;
}
function truncate(s, n) {
  s = String(s || "");
  return s.length > n ? s.slice(0, n) + "…" : s;
}

async function resetSession() {
  const sessionId = $("sessionId").value.trim() || "default";
  try {
    await fetch("api/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    });
  } catch {}
  $("messages").innerHTML = "";
  resetActivity();
  resetArtifacts();
  setStatus("idle", "");
}

init();
