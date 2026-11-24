// Shared by the home page, Studio and the editor: the prompt composer, uploads, recent projects.
const Cutline = (() => {
  const API = (document.querySelector('meta[name="cutline-api"]')?.content || "").replace(/\/$/, "");
  const $ = (s, root = document) => root.querySelector(s);
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const fmt = s => { s = Math.max(0, Math.round(s || 0)); const m = Math.floor(s / 60); return `${m}:${String(s % 60).padStart(2, "0")}`; };
  const VIDEO = /\.(mp4|mov|m4v|mkv|webm)$/i;

  async function api(path, opts = {}) {
    const headers = opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {};
    const r = await fetch(API + path, { ...opts, headers });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || `Request failed (${r.status})`);
    return j;
  }

  // ---- recent projects, this browser only ----
  function recent() { try { return JSON.parse(localStorage.getItem("cutline.recent") || "[]"); } catch { return []; } }
  function remember(s) {
    try {
      const list = recent().filter(r => r.id !== s.project_id);
      list.unshift({ id: s.project_id, name: s.filename, seconds: s.original_seconds, at: Date.now() });
      localStorage.setItem("cutline.recent", JSON.stringify(list.slice(0, 12)));
    } catch {}
  }

  // Upload a file (with progress), then start the edit: chat if there's a prompt and chat is on, else auto.
  function startProject(file, prompt, opts, onProgress) {
    return new Promise((resolve, reject) => {
      const fd = new FormData(); fd.append("video", file);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", API + "/api/projects");
      xhr.upload.onprogress = e => e.lengthComputable && onProgress && onProgress(e.loaded / e.total);
      xhr.onerror = () => reject(new Error("Upload failed. Check your connection and try again."));
      xhr.onload = async () => {
        let s = {}; try { s = JSON.parse(xhr.responseText); } catch {}
        if (xhr.status === 401 && s.need_code && !location.pathname.startsWith("/app")) {
          location.href = "/app" + (prompt ? "?prompt=" + encodeURIComponent(prompt) : ""); return;
        }
        if (xhr.status >= 300) return reject(new Error(s.error || `Upload failed (${xhr.status})`));
        remember(s);
        const pid = s.project_id;
        try {
          if (prompt && s.chat_enabled) {
            s = await api(`/api/projects/${pid}/chat`, { method: "POST", body: JSON.stringify({ message: prompt }) });
          } else {
            s = await api(`/api/projects/${pid}/auto`, { method: "POST", body: JSON.stringify(opts || {}) });
          }
        } catch (e) { s.startError = e.message; }
        resolve(s);
      };
      xhr.send(fd);
    });
  }

  // Wire up a .composer-card: textarea, attach button, drag and drop, file pill, send.
  function composer(card, { onSubmit, requireFile = false }) {
    const ta = $("textarea", card), input = $("input[type=file]", card), attach = $("[data-attach]", card);
    const send = $(".send-btn", card), pills = $("[data-file]", card), msg = $(".composer-msg", card);
    const bar = $(".upbar", card);
    let file = null;
    const sync = () => { send.disabled = card.classList.contains("busy") || (requireFile ? !file : !(file || ta.value.trim())); };
    const setFile = f => {
      if (f && !VIDEO.test(f.name)) { say("That's not a video. Use MP4, MOV, MKV or WebM.", true); return; }
      file = f || null; pills.replaceChildren();
      if (file) {
        const p = el("span", "file-pill"); p.append(el("span", null, file.name));
        const x = el("button", null, "×"); x.type = "button"; x.title = "Remove"; x.onclick = () => setFile(null);
        p.append(x); pills.append(p); say("");
      }
      sync();
    };
    const say = (text, err) => { msg.textContent = text; msg.classList.toggle("err", !!err); };
    attach.onclick = () => input.click();
    input.onchange = () => input.files[0] && setFile(input.files[0]);
    ["dragenter", "dragover"].forEach(ev => card.addEventListener(ev, e => { e.preventDefault(); card.classList.add("drag"); }));
    ["dragleave", "drop"].forEach(ev => card.addEventListener(ev, e => { e.preventDefault(); card.classList.remove("drag"); }));
    card.addEventListener("drop", e => e.dataTransfer.files[0] && setFile(e.dataTransfer.files[0]));
    ta.addEventListener("input", () => { sync(); ta.style.height = "auto"; ta.style.height = Math.min(320, Math.max(ta.scrollHeight, 0)) + "px"; });
    ta.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (!send.disabled) go(); } });
    send.onclick = go;
    async function go() {
      card.classList.add("busy"); sync();
      try { await onSubmit({ file, prompt: ta.value.trim(), progress: p => { if (bar) { bar.hidden = false; bar.firstElementChild.style.width = `${p * 100}%`; } }, say }); }
      catch (e) { say(e.message, true); }
      finally { card.classList.remove("busy"); if (bar) bar.hidden = true; sync(); }
    }
    sync();
    return { setPrompt(t) { ta.value = t; ta.dispatchEvent(new Event("input")); ta.focus(); }, setFile, say, get file() { return file; } };
  }

  // Waitlist form
  function waitlist(form, msg) {
    if (!form) return;
    form.addEventListener("submit", async e => {
      e.preventDefault();
      msg.className = "form-msg"; msg.textContent = "Adding you…";
      try {
        await api("/api/waitlist", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(form))) });
        form.reset(); msg.className = "form-msg ok"; msg.textContent = "You're on the list. We'll be in touch soon.";
      } catch (err) {
        msg.className = "form-msg err"; msg.textContent = err.message === "Failed to fetch" ? "Couldn't reach the server. Try again in a minute." : err.message;
      }
    });
  }

  // Play muted loops only while on screen.
  function autoplay(root = document) {
    const vids = root.querySelectorAll("video[data-auto]");
    if (!("IntersectionObserver" in window)) { vids.forEach(v => v.play().catch(() => {})); return; }
    const io = new IntersectionObserver(es => es.forEach(e => e.isIntersecting ? e.target.play().catch(() => {}) : e.target.pause()), { rootMargin: "100px" });
    vids.forEach(v => { v.muted = true; v.loop = true; v.playsInline = true; io.observe(v); });
  }

  if (API) document.querySelectorAll("[data-app-link]").forEach(a => a.href = API + a.getAttribute("href"));
  document.querySelectorAll("[data-year]").forEach(e => e.textContent = new Date().getFullYear());

  return { API, $, el, fmt, api, recent, remember, startProject, composer, waitlist, autoplay };
})();
