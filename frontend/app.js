"use strict";

const $ = (id) => document.getElementById(id);

const state = {
  sessionId: "default",
  mode: "auto",
  agent: null,
  agents: new Set(),
  controller: null,
  rawText: "",
  assistantEl: null,
  actCards: {}, // agent tag -> activity card element
};

// ---------- 初始化 ----------
async function init() {
  try {
    const res = await fetch("/api/agents");
    const data = await res.json();
    fillAgents(data.agents || []);
    $("modelBadge").textContent = `${data.model || "?"}${data.mock ? " · Mock" : ""}`;
  } catch (e) {
    console.error(e);
  }
  bindUI();
}

function fillAgents(agents) {
  const sel = $("agentSelect");
  const list = $("expertList");
  sel.innerHTML = "";
  list.innerHTML = "";
  agents.forEach((a) => {
    const opt = document.createElement("option");
    opt.value = a.tag;
    opt.textContent = `${a.name}（${a.role.slice(0, 12)}）`;
    sel.appendChild(opt);

    const label = document.createElement("label");
    label.className = "check";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = a.tag;
    cb.checked = ["researcher", "coder", "critic", "planner"].includes(a.tag);
    cb.addEventListener("change", () => {
      if (cb.checked) state.agents.add(a.tag);
      else state.agents.delete(a.tag);
    });
    label.appendChild(cb);
    const span = document.createElement("span");
    span.textContent = a.name;
    span.style.color = a.color;
    label.appendChild(span);
    list.appendChild(label);
    if (cb.checked) state.agents.add(a.tag);
  });
  state.agent = sel.value;
}

function bindUI() {
  document.querySelectorAll(".seg-btn").forEach((b) => {
    b.addEventListener("click", () => {
      document.querySelectorAll(".seg-btn").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      state.mode = b.dataset.mode;
      $("agentPanel").hidden = state.mode !== "agent";
      $("swarmPanel").hidden = state.mode !== "swarm";
      const txt = { auto: "自动路由", agent: "单专家", swarm: "智囊团" }[state.mode];
      $("modeBadge").textContent = txt;
    });
  });
  $("agentSelect").addEventListener("change", (e) => (state.agent = e.target.value));
  $("sessionId").addEventListener("change", (e) => (state.sessionId = e.target.value || "default"));
  $("resetBtn").addEventListener("click", async () => {
    await fetch("/api/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: state.sessionId }),
    });
    $("messages").innerHTML = "";
    $("activity").innerHTML = "";
    $("artifacts").innerHTML = '<div class="empty">暂无产物。让助手生成代码 / HTML 即可在此预览。</div>';
  });
  $("sendBtn").addEventListener("click", send);
  $("input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
}

// ---------- 发送与 SSE ----------
async function send() {
  const input = $("input");
  const text = input.value.trim();
  if (!text || state.controller) return;
  input.value = "";

  addMessage("user", text);
  const aEl = addMessage("assistant", "");
  state.assistantEl = aEl;
  state.rawText = "";
  state.actCards = {};
  $("activity").innerHTML = "";

  const body = {
    session_id: state.sessionId,
    message: text,
    mode: state.mode,
    agent: state.mode === "agent" ? state.agent : null,
    agents: state.mode === "swarm" ? [...state.agents] : null,
  };

  const controller = new AbortController();
  state.controller = controller;
  $("sendBtn").disabled = true;
  $("status").textContent = "思考中…";

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const blocks = buf.split("\n\n");
      buf = blocks.pop() || "";
      for (const block of blocks) dispatchBlock(block);
    }
  } catch (e) {
    if (e.name !== "AbortError") appendText(state.assistantEl, "\n[连接错误] " + e.message);
  } finally {
    finish();
  }
}

function dispatchBlock(block) {
  let event = "message";
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!data) return;
  let payload;
  try { payload = JSON.parse(data); } catch { return; }
  dispatch(event, payload);
}

function dispatch(event, p) {
  switch (event) {
    case "meta":
      $("modeBadge").textContent = p.mode === "swarm" ? "智囊团" : "单专家 / 自动";
      break;
    case "agent_start":
      ensureAgentCard(p.agent, p.name, p.color, p.role);
      break;
    case "thought":
      appendActLine(p.agent, "thought", p.text);
      break;
    case "tool_call": {
      let args = p.args || "";
      try { args = JSON.stringify(JSON.parse(args)); } catch {}
      appendActLine(p.agent, "tool", `🔧 调用 ${p.tool}(${args.length > 80 ? args.slice(0, 80) + "…" : args})`);
      break;
    }
    case "tool_result":
      appendActLine(p.agent, "result", `↳ ${p.ok ? "成功" : "失败"}: ${String(p.result).slice(0, 300)}`);
      break;
    case "token":
      state.rawText += p.text;
      state.assistantEl.querySelector(".bubble").textContent = state.rawText;
      scrollChat();
      break;
    case "artifact":
      renderArtifact(p);
      break;
    case "swarm_view":
      renderSwarmView(p);
      break;
    case "swarm_consensus": {
      const d = document.createElement("div");
      d.className = "consensus";
      d.textContent = `🧠 共识度 ${Math.round(p.value * 100)}%`;
      $("activity").appendChild(d);
      break;
    }
    case "done":
      if (state.assistantEl) {
        state.assistantEl.querySelector(".bubble").innerHTML = renderMarkdown(state.rawText);
      }
      break;
    case "error":
      appendText(state.assistantEl, "\n[错误] " + p.message);
      break;
  }
}

function finish() {
  state.controller = null;
  $("sendBtn").disabled = false;
  $("status").textContent = "就绪";
  scrollChat();
}

// ---------- 渲染辅助 ----------
function addMessage(role, text) {
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;
  const av = document.createElement("div");
  av.className = "avatar";
  av.textContent = role === "user" ? "你" : "AI";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  wrap.appendChild(av);
  wrap.appendChild(bubble);
  $("messages").appendChild(wrap);
  scrollChat();
  return wrap;
}

function appendText(el, t) {
  if (!el) return;
  el.querySelector(".bubble").textContent += t;
  scrollChat();
}

function scrollChat() {
  const m = $("messages");
  m.scrollTop = m.scrollHeight;
}

function ensureAgentCard(tag, name, color, role) {
  if (state.actCards[tag]) return state.actCards[tag];
  const card = document.createElement("div");
  card.className = "act-card";
  card.innerHTML = `<div class="act-head"><span class="act-dot" style="background:${color}"></span>${name}<span class="act-line" style="margin-left:6px;font-weight:400">· ${role}</span></div>`;
  $("activity").appendChild(card);
  state.actCards[tag] = card;
  return card;
}

function appendActLine(tag, cls, text) {
  const card = state.actCards[tag];
  if (!card) return;
  const line = document.createElement("div");
  line.className = `act-line ${cls}`;
  line.textContent = text;
  card.appendChild(line);
  const a = $("activity");
  a.scrollTop = a.scrollHeight;
}

function renderSwarmView(p) {
  const card = document.createElement("div");
  card.className = "act-card";
  card.innerHTML = `<div class="act-head"><span class="act-dot" style="background:${p.color}"></span>${p.name}<span class="conf">置信度 ${Math.round(p.confidence * 100)}%</span></div>`;
  const body = document.createElement("div");
  body.className = "act-line";
  body.innerHTML = renderMarkdown(p.text);
  card.appendChild(body);
  $("activity").appendChild(card);
  state.actCards["swarm_" + p.agent] = card;
}

function renderArtifact(p) {
  const box = $("artifacts");
  const empty = box.querySelector(".empty");
  if (empty) empty.remove();

  const card = document.createElement("div");
  card.className = "art-card";
  const head = document.createElement("div");
  head.className = "art-head";
  head.innerHTML = `<span class="art-tag">${p.type}</span><span>${escapeHtml(p.title)}</span>`;
  const actions = document.createElement("div");
  actions.className = "art-actions";
  const openBtn = document.createElement("a");
  openBtn.textContent = "新标签打开";
  openBtn.target = "_blank";
  const blob = new Blob([p.content], { type: p.type === "html" ? "text/html" : "text/plain" });
  openBtn.href = URL.createObjectURL(blob);
  actions.appendChild(openBtn);
  head.appendChild(actions);

  const bodyEl = document.createElement("div");
  bodyEl.className = "art-body";
  if (p.type === "html") {
    const iframe = document.createElement("iframe");
    iframe.setAttribute("sandbox", "allow-scripts");
    iframe.srcdoc = p.content;
    bodyEl.appendChild(iframe);
  } else {
    const pre = document.createElement("pre");
    pre.textContent = p.content;
    bodyEl.appendChild(pre);
  }

  card.appendChild(head);
  card.appendChild(bodyEl);
  box.appendChild(card);
}

// ---------- Markdown ----------
function renderMarkdown(text) {
  if (text && window.marked && marked.parse) {
    try { return marked.parse(text); } catch { /* fall through */ }
  }
  return escapeHtml(text).replace(/\n/g, "<br>");
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

init();
