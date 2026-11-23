// Cutline motion. Reveals blocks as they come into view; never changes how the page scrolls.
(() => {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fine = matchMedia("(pointer: fine)").matches;
  const io = (fn, opts) => new IntersectionObserver(es => es.forEach(e => e.isIntersecting && fn(e.target, e)), { threshold: .18, rootMargin: "0px 0px -8% 0px", ...opts });

  // Stagger index for children of [data-stagger]
  document.querySelectorAll("[data-stagger]").forEach(p => [...p.children].forEach((c, i) => {
    c.style.setProperty("--i", i);
    if (!c.hasAttribute("data-reveal")) c.setAttribute("data-reveal", p.dataset.stagger || "up");
  }));
  document.querySelectorAll(".hero .chips .chip").forEach((c, i) => c.style.setProperty("--i", i));

  // Split headlines into words (an inline element such as .grad stays one unit)
  document.querySelectorAll("[data-split]").forEach(h => {
    let i = 0;
    const wrap = node => { const w = document.createElement("span"); w.className = "w"; const s = document.createElement("span"); s.style.setProperty("--i", i++); w.append(s); s.append(node); return w; };
    [...h.childNodes].forEach(n => {
      if (n.nodeType === 3) {
        const frag = document.createDocumentFragment();
        n.textContent.split(/(\s+)/).forEach(part => {
          if (!part) return;
          frag.append(/^\s+$/.test(part) ? document.createTextNode(" ") : wrap(document.createTextNode(part)));
        });
        n.replaceWith(frag);
      } else if (n.nodeType === 1 && n.tagName !== "BR") n.replaceWith(wrap(n.cloneNode(true)));
    });
  });

  if (reduce) {
    document.querySelectorAll("[data-split]").forEach(h => h.classList.add("split-in"));
    document.querySelectorAll(".widget-host").forEach(h => h.classList.add("play"));
  }

  // Reveal, then drop the attribute so hover effects run without the reveal delay
  const reveal = io((el, e) => {
    el.classList.add("in");
    reveal.unobserve(el);
    const delay = parseFloat(getComputedStyle(el).getPropertyValue("--i") || 0) * 90;
    setTimeout(() => { el.removeAttribute("data-reveal"); el.classList.remove("in"); }, 1300 + delay);
  });
  document.querySelectorAll("[data-reveal]").forEach(el => reveal.observe(el));
  const splits = io(el => { el.classList.add("split-in"); splits.unobserve(el); }, { threshold: .4 });
  document.querySelectorAll("[data-split]").forEach(el => splits.observe(el));

  // Count-up numbers
  const counters = io(el => {
    counters.unobserve(el);
    const to = +el.dataset.count, dur = 1500, t0 = performance.now(), fmt = n => n.toLocaleString("en-US");
    if (reduce) { el.textContent = fmt(to); return; }
    const step = t => { const k = Math.min(1, (t - t0) / dur); el.textContent = fmt(Math.round(to * (1 - Math.pow(1 - k, 4)))); if (k < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  }, { threshold: .6 });
  document.querySelectorAll("[data-count]").forEach(el => counters.observe(el));

  // Live widgets: start when visible; the waveform cuts its silences on a loop
  const widgets = io(el => {
    el.classList.add("play");
    const wave = el.querySelector(".w-wave");
    if (wave && !wave.dataset.loop) {
      wave.dataset.loop = 1;
      const len = wave.querySelector("[data-len]");
      const cycle = () => {
        wave.classList.remove("cut"); if (len) len.textContent = len.dataset.from;
        setTimeout(() => { wave.classList.add("cut"); if (len) len.textContent = len.dataset.to; }, 1200);
      };
      cycle(); setInterval(cycle, 4200);
    }
  }, { threshold: .35 });
  document.querySelectorAll(".widget-host").forEach(el => widgets.observe(el));

  // Scroll progress bar: reads the scroll position, never moves it
  const bar = document.createElement("div"); bar.className = "progress"; document.body.append(bar);
  let ticking = false, lastY = scrollY;
  const marquee = document.querySelector(".marquee-track");
  addEventListener("scroll", () => {
    if (ticking) return; ticking = true;
    requestAnimationFrame(() => {
      const max = document.documentElement.scrollHeight - innerHeight;
      bar.style.setProperty("--p", max > 0 ? scrollY / max : 0);
      if (marquee) marquee.style.animationDirection = scrollY < lastY ? "reverse" : "normal";
      lastY = scrollY; ticking = false;
    });
  }, { passive: true });

  if (reduce || !fine) return;

  // Tilt + glare on video tiles
  document.querySelectorAll(".tile").forEach(t => {
    t.addEventListener("pointermove", e => {
      const r = t.getBoundingClientRect(), x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
      t.classList.add("tilt");
      t.style.setProperty("--ry", `${(x - .5) * 10}deg`); t.style.setProperty("--rx", `${(.5 - y) * 8}deg`);
      t.style.setProperty("--mx", `${x * 100}%`); t.style.setProperty("--my", `${y * 100}%`);
    });
    t.addEventListener("pointerleave", () => { t.classList.remove("tilt"); t.style.removeProperty("--rx"); t.style.removeProperty("--ry"); });
  });

  // Magnetic buttons
  document.querySelectorAll(".btn.primary, .btn.white, .send-btn").forEach(b => {
    b.classList.add("magnet");
    b.addEventListener("pointermove", e => { const r = b.getBoundingClientRect(); b.style.transform = `translate(${(e.clientX - r.left - r.width / 2) * .18}px, ${(e.clientY - r.top - r.height / 2) * .25}px)`; });
    b.addEventListener("pointerleave", () => { b.style.transform = ""; });
  });

  // Hero: floaters drift with the cursor, plus a soft glow that follows it
  const hero = document.querySelector(".hero");
  if (hero) {
    const glow = document.createElement("div"); glow.className = "cursor-glow"; hero.prepend(glow);
    const fl = [...hero.querySelectorAll(".floater")];
    hero.addEventListener("pointermove", e => {
      const r = hero.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
      glow.style.setProperty("--cx", `${x}px`); glow.style.setProperty("--cy", `${y}px`);
      const dx = x / r.width - .5, dy = y / r.height - .5;
      fl.forEach((f, i) => { const d = [22, 14, 26, 18][i] || 16; f.style.setProperty("--px", `${-dx * d}px`); f.style.setProperty("--py", `${-dy * d}px`); });
    });
  }
})();
