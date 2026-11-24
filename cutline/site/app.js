// Cutline editor: a chat center. Start with a prompt and a video, then watch, chat, download.
const { $, el, fmt, api, recent, remember, startProject, composer } = Cutline;
const params = new URLSearchParams(location.search);
const NOTICE = "Chat editing isn't switched on for this server yet, so Cutline made the automatic cut and Shorts instead. Your request is saved in the box below.";
let pid = params.get("p");
let state = null, current = null, pollTimer = null;

// ---------- sidebar ----------
function showRecent() {
  const box = $("#recent"), list = recent();
  if (!list.length) return;
  box.replaceChildren();
  for (const r of list) {
    const a = el("a"); a.href = `/app?p=${r.id}`;
    if (r.id === pid) a.className = "on";
    a.append(el("span", null, r.name || r.id), el("span", null, fmt(r.seconds)));
    box.append(a);
  }
}
const menu = open => document.body.classList.toggle("menu-open", open);
$("#menu-btn").onclick = () => menu(true);
$("#side-close").onclick = $("#scrim").onclick = () => menu(false);

// ---------- start view ----------
const startBox = composer($("#start-composer"), {
  requireFile: true,
  async onSubmit({ file, prompt, progress, say }) {
    say("Uploading…");
    const s = await startProject(file, prompt, { shorts: +$("#opt-shorts").value, captions: $("#opt-captions").value }, progress);
    pid = s.project_id;
    history.pushState({}, "", `/app?p=${pid}`);
    say("");
    if (prompt && !s.chat_enabled) s.notice = NOTICE;
    openEditor(s);
    if (s.notice) { $("#input").value = prompt; }
    if (s.startError) showError(s.startError);
  },
});
if (params.get("prompt")) startBox.setPrompt(params.get("prompt"));
document.querySelectorAll("#start-chips .chip").forEach(c => c.onclick = () => startBox.setPrompt(c.dataset.prompt));
const dz = $("#dropzone");
dz.onclick = e => { e.preventDefault(); $("#start-composer input[type=file]").click(); };
// drop a file anywhere on the start screen
["dragenter", "dragover"].forEach(ev => document.addEventListener(ev, e => { if (!$("#start-view").hidden) { e.preventDefault(); dz.classList.add("over"); } }));
["dragleave", "drop"].forEach(ev => document.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove("over"); }));
document.addEventListener("drop", e => { if (!$("#start-view").hidden && e.dataTransfer.files[0]) startBox.setFile(e.dataTransfer.files[0]); });

// ---------- editor ----------
function openEditor(s) {
  $("#start-view").hidden = true; $("#editor-view").hidden = false;
  menu(false);
  render(s);
  showRecent();
}

function showError(msg) { const st = $("#status"); st.hidden = false; st.className = "status err"; $("#status-text").textContent = msg; }

function outputsList(s) {
  const o = s.outputs || {}, list = [];
  if (o.long) list.push(["long", "Long cut", o.long]);
  else if (o.preview) list.push(["preview", "Preview", o.preview]);
  Object.keys(o).filter(k => k.startsWith("short_")).sort((a, b) => +a.split("_")[1] - +b.split("_")[1]).forEach(k => {
    const i = +k.split("_")[1], short = (s.shorts || [])[i - 1];
    list.push([k, short ? `Short ${i} · ${short.title}` : `Short ${i}`, o[k]]);
  });
  Object.keys(o).filter(k => !["long", "preview"].includes(k) && !k.startsWith("short_")).forEach(k => list.push([k, k.replace(/_/g, " "), o[k]]));
  return list;
}

function render(s) {
  const prevJob = state && state.job && state.job.state;
  const notice = s.notice || (state && state.notice);
  state = s; if (notice) state.notice = notice;
  $("#proj-name").textContent = s.filename || "";
  document.title = `${s.filename || "Editor"} · Cutline`;

  const stats = $("#stats"); stats.replaceChildren();
  const add = (v, l, hl) => { const d = el("span", "stat" + (hl ? " hl" : "")); d.append(el("b", null, v), document.createTextNode(l)); stats.append(d); };
  add(fmt(s.original_seconds), "original");
  if (s.cut_seconds && s.cut_seconds < s.original_seconds - 0.5) { add(fmt(s.cut_seconds), "edited", true); add(fmt(s.removed_seconds), "removed"); }
  if (s.shorts && s.shorts.length) add(String(s.shorts.length), s.shorts.length === 1 ? "Short" : "Shorts", true);

  const outs = outputsList(s), tabs = $("#tabs");
  tabs.replaceChildren();
  if (!outs.find(o => o[0] === current)) current = outs.length ? outs[0][0] : null;
  for (const [key, label] of outs) {
    const b = el("button", "tab" + (key === current ? " on" : ""), label);
    b.title = label;
    b.onclick = () => { current = key; render(state); };
    tabs.append(b);
  }
  const out = outs.find(o => o[0] === current), video = $("#video"), dl = $("#download");
  const running = s.job && s.job.state === "running";
  if (out) {
    if (video.dataset.src !== out[2]) { video.dataset.src = out[2]; video.src = Cutline.API + out[2]; }
    dl.href = `${Cutline.API}${out[2]}&download=1`; dl.hidden = false;
    $("#player-empty").hidden = true;
  } else {
    video.removeAttribute("src"); video.dataset.src = ""; dl.hidden = true;
    $("#player-empty").hidden = false;
    $("#spinner").hidden = !running;
    $("#player-msg").textContent = running ? "Working on your first cut. A 10-minute video takes a few minutes." : "Nothing rendered yet. Ask for an edit in the chat.";
  }

  const st = $("#status");
  if (running) { st.hidden = false; st.className = "status"; $("#status-text").textContent = (s.job.step || "Working") + "…"; }
  else if (s.job && s.job.state === "error") showError(s.job.error || "Something went wrong");
  else st.hidden = true;

  const box = $("#messages"), hint = $("#chat-hint");
  box.querySelectorAll(".bubble").forEach(b => b.remove());
  const chat = s.chat || [];
  hint.hidden = !!(chat.length || state.notice);
  if (state.notice) box.append(el("div", "bubble ai", state.notice));
  for (const m of chat) box.append(el("div", "bubble " + (m.role === "user" ? "me" : "ai"), m.text));
  if (running && chat.length && chat[chat.length - 1].role === "user") box.append(el("div", "bubble tool", (s.job.step || "Thinking") + "…"));
  box.scrollTop = box.scrollHeight;

  const canChat = s.chat_enabled !== false;
  $("#input").disabled = !canChat || running; $("#send").disabled = !canChat || running;
  box.querySelectorAll(".chip").forEach(c => c.disabled = !canChat || running);
  $("#chat-note").textContent = canChat ? "" : "Off on this server";
  $("#input").placeholder = canChat ? (running ? "Working…" : "Ask for an edit…") : "Chat needs a Claude API key";

  clearTimeout(pollTimer);
  if (running) pollTimer = setTimeout(refresh, 1500);
  else if (prevJob === "running" && !out) refresh();
}

async function refresh() {
  try { render(await api(`/api/projects/${pid}`)); }
  catch { pollTimer = setTimeout(refresh, 4000); }
}

async function send(text) {
  text = text.trim(); if (!text) return;
  $("#input").value = ""; autosize();
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
document.querySelectorAll("#chat-hint .chip").forEach(c => c.addEventListener("click", () => send(c.textContent)));

// ---------- start ----------
function boot() {
if (pid) {
  api(`/api/projects/${pid}`).then(s => {
    remember(s);
    if (params.get("prompt") && !s.chat_enabled) s.notice = NOTICE;
    openEditor(s);
    if (s.notice) $("#input").value = params.get("prompt");
  }).catch(() => { history.replaceState({}, "", "/app"); pid = null; showRecent(); });
} else showRecent();
}

// Beta gate: when the server has an access code, ask for it once (it's kept in a cookie).
api("/api/access").then(a => {
  if (!a.required || a.ok) return boot();
  const g = $("#gate"); g.hidden = false; $("#gate-code").focus();
  $("#gate-form").onsubmit = async e => {
    e.preventDefault();
    try {
      await api("/api/access", { method: "POST", body: JSON.stringify({ code: $("#gate-code").value }) });
      g.hidden = true; boot();
    } catch (err) { $("#gate-msg").textContent = err.message; }
  };
}).catch(boot);
