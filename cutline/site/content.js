// Content Center: viral templates + a prompt box that works like the home page composer.
(() => {
  const C = Cutline, $ = C.$;

  // kind "ai": needs AI video generation (coming soon). kind "footage": runs today on the creator's own uploaded video.
  // Thumbnails are CSS illustrations; there is no sample footage on the site.
  const T = [
    { cat: "whatif", kind: "ai", scene: "jungle", hook: "What if you went missing in", blank: "the Amazon", prompt: "What if you went missing in ___? Make a 30-second faceless story: day-by-day survival beats, eerie narration, and bold captions." },
    { cat: "whatif", kind: "ai", scene: "sepia", hook: "What if you woke up in", blank: "1925", prompt: "What if you woke up in ___? Walk through the first 24 hours in a 30-second faceless story with period-accurate scenes and narration." },
    { cat: "whatif", kind: "ai", scene: "ocean", hook: "What if you lived under", blank: "the ocean", prompt: "What if you lived under ___ for a year? A 30-second faceless explainer with cinematic shots and a twist at the end." },
    { cat: "whatif", kind: "ai", scene: "space", hook: "What if you got stranded on", blank: "Mars", prompt: "What if you got stranded on ___? Tell it as a 45-second countdown survival story with captions and tense music." },
    { cat: "pov", kind: "ai", scene: "city", hook: "POV: you're the last person in", blank: "New York", prompt: "POV: you're the last person in ___. A 30-second first-person faceless short with empty streets and a creepy reveal." },
    { cat: "pov", kind: "ai", scene: "castle", hook: "POV: you were born a", blank: "medieval king", prompt: "POV: you were born a ___. Show a day in that life in 30 seconds, first person, with captions." },
    { cat: "facts", kind: "ai", scene: "lab", hook: "5 facts about", blank: "sleep", tail: "that sound fake", prompt: "5 facts about ___ that sound fake but are true. Number each one on screen, fast cuts, bold captions, 40 seconds." },
    { cat: "facts", kind: "ai", scene: "empire", hook: "The rise and fall of", blank: "Blockbuster", prompt: "The rise and fall of ___ in 60 seconds. Timeline style with dates on screen, archival look, and narration." },
    { cat: "rank", kind: "ai", scene: "neon", hook: "Ranking every", blank: "fast food fry", tail: "worst to best", prompt: "Ranking every ___ from worst to best. Tier-list visuals, quick verdicts, 45 seconds, captions on." },
    { cat: "story", kind: "footage", scene: "story", hook: "Storytime:", blank: "the worst job I ever had", prompt: "Storytime: ___. Turn my recording into a tight vertical story. Cut the dead air, punch in on the big moments, karaoke captions." },
    { cat: "story", kind: "footage", scene: "split", hook: "Day 1 vs day 100 of", blank: "learning guitar", prompt: "Day 1 vs day 100 of ___. Cut my clips into a before-and-after Short with a split screen at the end and bold captions." },
    { cat: "clips", kind: "footage", scene: "podcast", hook: "5 hook-first Shorts from", blank: "my podcast", prompt: "Turn ___ into 5 Shorts that each open on a strong hook. Vertical, karaoke captions, blue highlight." },
    { cat: "clips", kind: "footage", scene: "rant", hook: "Hot take:", blank: "college is overrated", prompt: "Hot take: ___. Cut my rant into a 30-second Short, punch in on every strong line, and caption it." },
    { cat: "clips", kind: "footage", scene: "list", hook: "3 things nobody tells you about", blank: "YouTube", prompt: "3 things nobody tells you about ___. Turn my recording into a numbered list Short with animated cards between points." },
    { cat: "whatif", kind: "ai", scene: "desert", hook: "What if you were trapped in", blank: "the Sahara", prompt: "What if you were trapped in ___ with one bottle of water? 30-second faceless survival story, captions, ticking-clock music." },
    { cat: "pov", kind: "ai", scene: "snow", hook: "POV: your flight crashed in", blank: "Antarctica", prompt: "POV: your flight crashed in ___. First-person survival short, 30 seconds, captions, cold blue grade." },
  ];
  const CATS = { whatif: "What if", pov: "POV", facts: "Facts", rank: "Rankings", story: "Storytime", clips: "Clips" };

  // ---- template grid ----
  const grid = $("#templates");
  T.forEach((t, i) => {
    const card = C.el("article", "tpl");
    card.dataset.cat = t.cat; card.dataset.kind = t.kind;
    const thumb = C.el("div", "tpl-thumb" + (t.scene ? " scene-" + t.scene : ""));
    const cap = C.el("div", "tpl-cap");
    cap.append(document.createTextNode(t.hook + " "), C.el("mark", null, t.blank), document.createTextNode(t.tail ? " " + t.tail : t.cat === "whatif" ? "?" : ""));
    thumb.append(cap);
    const tags = C.el("div", "tpl-tags");
    tags.append(C.el("span", "tpl-tag", CATS[t.cat]));
    tags.append(C.el("span", "tpl-tag " + (t.kind === "ai" ? "soon" : "live"), t.kind === "ai" ? "AI · Soon" : "Your footage"));
    thumb.append(tags);
    const use = C.el("button", "tpl-use", "Use template"); use.type = "button";
    thumb.append(use);
    const body = C.el("div", "tpl-body");
    body.append(C.el("div", "tpl-title", t.hook + " ___" + (t.tail ? " " + t.tail : "")));
    body.append(C.el("div", "tpl-sub", t.kind === "ai" ? "Faceless · generated from scratch" : "Edits your own recording"));
    card.append(thumb, body);
    card.tabIndex = 0;
    const pick = () => useTemplate(t);
    card.addEventListener("click", pick);
    card.addEventListener("keydown", e => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), pick()));
    grid.append(card);
  });
  C.autoplay(grid);

  // ---- filters ----
  document.querySelectorAll("#cc-filters .filter").forEach(b => b.onclick = () => {
    document.querySelectorAll("#cc-filters .filter").forEach(x => x.classList.toggle("on", x === b));
    const f = b.dataset.f;
    grid.querySelectorAll(".tpl").forEach(c => c.classList.toggle("gone", !(f === "all" || c.dataset.cat === f || c.dataset.kind === f)));
  });

  // ---- mode: edit my footage (live) vs generate from scratch (coming soon) ----
  let mode = "edit";
  const setMode = m => {
    mode = m;
    document.querySelectorAll("#cc-mode button").forEach(b => b.classList.toggle("on", b.dataset.mode === m));
    $("#cc-composer textarea").placeholder = m === "edit"
      ? "Attach your video and describe the Short. Or pick a template below."
      : "Describe the video you want generated. For example: What if you went missing in the Amazon?";
  };
  document.querySelectorAll("#cc-mode button").forEach(b => b.onclick = () => setMode(b.dataset.mode));

  // ---- composer ----
  const card = $("#cc-composer");
  const box = C.composer(card, {
    async onSubmit({ file, prompt, progress, say }) {
      const len = $("#cc-length").value, fmt = $("#cc-format").value, n = +$("#cc-count").value;
      const full = prompt + (prompt ? ` (${len}, ${fmt}${n > 1 ? `, ${n} versions` : ""})` : "");
      if (!file) {
        if (mode === "generate") {
          say("AI generation from scratch is coming soon. Switch to “Edit my footage” and attach a video to make this today, or join the waitlist below to hear first.", true);
          return;
        }
        location.href = C.API + "/app" + (full ? "?prompt=" + encodeURIComponent(full) : "");
        return;
      }
      say("Uploading…");
      const s = await C.startProject(file, full, { shorts: Math.max(1, n), captions: "karaoke" }, progress);
      location.href = C.API + "/app?p=" + s.project_id + (full && !s.chat_enabled ? "&prompt=" + encodeURIComponent(full) : "");
    },
  });

  function useTemplate(t) {
    setMode(t.kind === "ai" ? "generate" : "edit");
    const ta = $("#cc-composer textarea");
    box.setPrompt(t.prompt.replace("___", t.blank));
    // Select the filled-in blank so the creator can type their own topic straight away.
    const at = t.prompt.indexOf("___");
    if (at >= 0) ta.setSelectionRange(at, at + t.blank.length);
    box.say(t.kind === "ai"
      ? "This template generates new footage, which is coming soon. Change the highlighted part to make it yours."
      : "Change the highlighted part, attach your video, and send.");
    card.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
  }

  C.waitlist($("#cc-waitlist-form"), $("#cc-waitlist-msg"));
})();
