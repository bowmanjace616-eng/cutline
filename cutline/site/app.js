// Cutline editor: upload -> auto edit -> watch, chat, download. No build step.
const $ = s => document.querySelector(s);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

let pid = new URLSearchParams(location.search).get("p");
let state = null, current = null, pollTimer = null;

const fmt = s => { s = Math.max(0, Math.round(s || 0)); const m = Math.floor(s / 60); return `${m}:${String(s % 60).padStart(2, "0")}`; };

async function api(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {} });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `Request failed (${r.status})`);
  return j;
}

// ---------- recent projects (this browser only) ----------
function recent() { try { return JSON.parse(localStorage.getItem("cutline.recent") || "[]"); } catch { return []; } }
function remember(s) {
  try {
    const list = recent().filter(r => r.id !== s.project_id);
    list.unshift({ id: s.project_id, name: s.filename, seconds: s.original_seconds, at: Date.now() });
    localStorage.setItem("cutline.recent", JSON.stringify(list.slice(0, 8)));
  } catch {}
}
function showRecent() {
  const list = recent(), box = $("#recent");
  box.replaceChildren();
  if (!list.length) return;
  box.append(el("h3", null, "Recent videos"));
  for (const r of list) {
    const a = el("a"); a.href = `?p=${r.id}`;
    a.append(el("span", null, r.name || r.id), el("span", null, fmt(r.seconds)));
    box.append(a);
  }
}

// ---------- upload ----------
const drop = $("#drop"), file = $("#file");
["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", e => e.dataTransfer.files[0] && upload(e.dataTransfer.files[0]));
file.addEventListener("change", () => file.files[0] && upload(file.files[0]));

function upload(f) {
  const msg = $("#up-msg"); msg.textContent = "";
  const bar = $("#up-bar"), fill = bar.querySelector("i");
  bar.hidden = false; drop.classList.add("busy");
  drop.querySelector("strong").textContent = `Uploading ${f.name}`;
  const fd = new FormData(); fd.append("video", f);
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/projects");
  xhr.upload.onprogress = e => { if (e.lengthComputable) fill.style.width = `${(e.loaded / e.total) * 100}%`; };
  xhr.onload = async () => {
    let j = {}; try { j = JSON.parse(xhr.responseText); } catch {}
    if (xhr.status >= 300) return fail(j.error || `Upload failed (${xhr.status})`);
    pid = j.project_id; history.pushState({}, "", `?p=${pid}`);
    remember(j);
    try {
      const s = await api(`/api/projects/${pid}/auto`, { method: "POST", body: JSON.stringify({ shorts: +$("#opt-shorts").value, captions: $("#opt-captions").value }) });
      openEditor(s);
    } catch (e) { openEditor(j); fail(e.message); }
  };
  xhr.onerror = () => fail("Upload failed. Check your connection and try again.");
  xhr.send(fd);
  function fail(m) { msg.textContent = m; bar.hidden = true; fill.style.width = 0; drop.classList.remove("busy"); drop.querySelector("strong").textContent = "Drop your video here"; }
}

// ---------- editor ----------
function openEditor(s) {
  $("#upload-view").hidden = true; $("#editor-view").hidden = false; $("#new-btn").hidden = false;
  render(s);
}

function outputsList(s) {
  const o = s.outputs || {}, list = [];
  if (o.long) list.push(["long", "Long cut", o.long]);
  else if (o.preview) list.push(["preview", "Preview", o.preview]);
  Object.keys(o).filter(k => k.startsWith("short_")).sort((a, b) => +a.split("_")[1] - +b.split("_")[1]).forEach(k => {
    const i = +k.split("_")[1], short = (s.shorts || [])[i - 1];
    list.push([k, short ? `Short ${i}: ${short.title}` : `Short ${i}`, o[k]]);
  });
  return list;
}

function render(s) {
  const prevJob = state && state.job && state.job.state;
  state = s;
  $("#proj-name").textContent = s.filename || "";
  document.title = `${s.filename || "Editor"} · Cutline`;

  // stats
  const stats = $("#stats"); stats.replaceChildren();
  const add = (v, l) => { const d = el("div", "stat"); d.append(el("b", null, v), el("span", null, l)); stats.append(d); };
  add(fmt(s.original_seconds), "Original");
  if (s.cut_seconds && s.cut_seconds < s.original_seconds - 0.5) { add(fmt(s.cut_seconds), "Edited"); add(fmt(s.removed_seconds), "Removed"); }
  if (s.shorts && s.shorts.length) add(String(s.shorts.length), "Shorts");

  // tabs + player
  const outs = outputsList(s), tabs = $("#tabs");
  tabs.replaceChildren();
  if (!outs.find(o => o[0] === current)) current = outs.length ? outs[0][0] : null;
  for (const [key, label] of outs) {
    const b = el("button", "tab" + (key === current ? " on" : ""), label);
    b.onclick = () => { current = key; render(state); };
    tabs.append(b);
  }
  const out = outs.find(o => o[0] === current), video = $("#video"), dl = $("#download");
  const running = s.job && s.job.state === "running";
  if (out) {
    const src = out[2];
    if (video.dataset.src !== src) { video.dataset.src = src; video.src = src; }
    dl.href = `${out[2]}&download=1`; dl.hidden = false;
    $("#player-empty").hidden = true;
  } else {
    video.removeAttribute("src"); video.dataset.src = ""; dl.hidden = true;
    $("#player-empty").hidden = false;
    $("#spinner").hidden = !running;
    $("#player-msg").textContent = running ? "Working on your first cut. A 10-minute video takes a few minutes." : "Nothing rendered yet. Ask for an edit in the chat.";
  }

  // status
  const st = $("#status");
  if (running) { st.hidden = false; st.className = "status"; $("#status-text").textContent = (s.job.step || "Working") + "…"; }
  else if (s.job && s.job.state === "error") { st.hidden = false; st.className = "status err"; $("#status-text").textContent = s.job.error || "Something went wrong"; }
  else st.hidden = true;

  // chat
  const box = $("#messages"), hint = $("#chat-hint");
  box.querySelectorAll(".bubble").forEach(b => b.remove());
  hint.hidden = !!(s.chat && s.chat.length);
  for (const m of s.chat || []) box.append(el("div", "bubble " + (m.role === "user" ? "me" : "ai"), m.text));
  if (running && s.chat && s.chat.length && s.chat[s.chat.length - 1].role === "user") box.append(el("div", "bubble tool", (s.job.step || "Thinking") + "…"));
  box.scrollTop = box.scrollHeight;

  const canChat = s.chat_enabled !== false;
  $("#input").disabled = !canChat || running; $("#send").disabled = !canChat || running;
  box.querySelectorAll(".chip").forEach(c => c.disabled = !canChat || running);
  $("#chat-note").textContent = canChat ? "" : "Chat is off on this server";
  $("#input").placeholder = canChat ? (running ? "Working…" : "Ask for an edit…") : "Chat needs a Claude API key";

  clearTimeout(pollTimer);
  if (running) pollTimer = setTimeout(refresh, 1500);
  else if (prevJob === "running" && !out) refresh();
}

async function refresh() {
  try { render(await api(`/api/projects/${pid}`)); }
  catch (e) { pollTimer = setTimeout(refresh, 4000); }
}

async function send(text) {
  text = text.trim(); if (!text) return;
  $("#input").value = ""; autosize();
  // show it straight away
  state.chat = [...(state.chat || []), { role: "user", text }];
  state.job = { state: "running", step: "Thinking" };
  render(state);
  try { render(await api(`/api/projects/${pid}/chat`, { method: "POST", body: JSON.stringify({ message: text }) })); }
  catch (e) { state.chat.push({ role: "assistant", text: e.message }); state.job = { state: "idle" }; render(state); }
}

$("#composer").addEventListener("submit", e => { e.preventDefault(); send($("#input").value); });
$("#input").addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send($("#input").value); } });
function autosize() { const t = $("#input"); t.style.height = "auto"; t.style.height = Math.min(140, t.scrollHeight) + "px"; }
$("#input").addEventListener("input", autosize);
document.querySelectorAll(".chip").forEach(c => c.addEventListener("click", () => send(c.textContent)));
$("#new-btn").addEventListener("click", () => { location.href = "/app"; });

// ---------- start ----------
if (pid) {
  api(`/api/projects/${pid}`).then(s => { remember(s); openEditor(s); }).catch(() => { history.replaceState({}, "", "/app"); pid = null; showRecent(); });
} else showRecent();
