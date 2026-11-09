"use strict";
/* eztudy offline player. Click-only by design: no keyboard shortcuts are registered (buttons are real
   <button>s, so the browser's own Tab / Enter / Space still work). DATA is the quiz or flashcard JSON. */

const SKINS = [["focus", "Focus"], ["editorial", "Editorial"], ["terminal", "Terminal"], ["system7", "System 7"], ["typewriter", "Typewriter"]];
const $ = (s, el = document) => el.querySelector(s);
const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return el;
};
const svg = path => {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("aria-hidden", "true");
  s.innerHTML = path;  // static, trusted markup only
  return s;
};
const ICON = {
  check: () => svg('<path d="M5 12.5l4.5 4.5L19 7.5"/>'),
  x: () => svg('<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>'),
  left: () => svg('<path d="M14.5 6l-6 6 6 6"/>'),
  right: () => svg('<path d="M9.5 6l6 6-6 6"/>'),
};
const shuffle = a => { a = a.slice(); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
const say = msg => { const el = $("#live"); el.textContent = ""; setTimeout(() => { el.textContent = msg; }, 30); };

// Text keeps its line breaks; ``` fences (and unfenced multi-line code) become <pre>. DOM only, no innerHTML.
const looksLikeCode = t => /\n/.test(t) && (/[{};]\s*$/m.test(t) || /^(\t| {2,})\S/m.test(t));
const rich = (text, tag = "span") => {
  const s = String(text ?? "");
  if (!s.includes("```")) return looksLikeCode(s) ? h("pre", { class: "code" }, h("code", {}, s.replace(/^\n+|\s+$/g, ""))) : h(tag, { class: "rich" }, s);
  return h(tag, { class: "rich" }, s.split(/```/).map((part, i) => {
    if (i % 2 === 0) return part.replace(/^\n|\n$/g, "");
    return h("pre", { class: "code" }, h("code", {}, part.replace(/^[\w+#.-]*\n/, "").replace(/\n$/, "")));
  }));
};

/* ---------------- viewer preferences (skin, light/dark) ---------------- */
const pref = {
  get(k) { try { return localStorage.getItem("eztudy:pref:" + k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem("eztudy:pref:" + k, v); } catch {} },
};
const root = document.documentElement;
const DEFAULT_SKIN = root.dataset.skin;
const darkMQ = window.matchMedia ? matchMedia("(prefers-color-scheme: dark)") : null;
function applyLook() {
  const skin = pref.get("skin");
  root.dataset.skin = SKINS.some(([id]) => id === skin) ? skin : DEFAULT_SKIN;
  const t = pref.get("theme") || "system";
  root.dataset.mode = t === "dark" || (t === "system" && darkMQ && darkMQ.matches) ? "dark" : "light";
}
applyLook();
darkMQ && darkMQ.addEventListener && darkMQ.addEventListener("change", applyLook);

/* per-deck progress (attempt history, flashcard marks) */
const store = {
  key: "eztudy:" + (DATA.id || DATA.title),
  get() { try { return JSON.parse(localStorage.getItem(this.key)) || {}; } catch { return {}; } },
  set(v) { try { localStorage.setItem(this.key, JSON.stringify(v)); } catch {} },
};

const stage = $("#stage");
$("#title").textContent = DATA.title;
$("#desc").textContent = DATA.description || "";
$("#winTitle").textContent = DATA.title;
const setCount = s => { $("#count").textContent = s; };

const explain = item => {
  if (!item.explanation) return null;
  const el = rich(item.explanation, "p");
  el.classList.add("expl");
  return el;
};
const citeList = item => {
  const c = item.citations || [];
  if (!c.length) return null;
  return h("div", { class: "cites", "aria-label": "Sources" }, c.map((x, k) => typeof x === "string"
    ? h("span", { class: "cite" }, h("span", { class: "n" }, k + 1), h("span", { class: "src" }, x))
    : h("span", { class: "cite", title: x.cid ? "chunk " + x.cid : null },
        h("span", { class: "n" }, k + 1), h("span", { class: "src" }, x.source || x.cid || ""), x.location ? h("span", { class: "loc" }, x.location) : null)));
};

/* ---------------- options menu ---------------- */
let menuExtras = () => [];
const menu = $("#menu"), menuBtn = $("#menuBtn");
function renderMenu() {
  menu.replaceChildren(
    h("section", {}, h("h2", {}, "Skin"), h("div", { class: "choices" }, SKINS.map(([id, name]) =>
      h("button", { type: "button", class: "choice", "aria-pressed": String(root.dataset.skin === id),
        onclick: () => { pref.set("skin", id); applyLook(); renderMenu(); } },
        h("span", { class: "swatch", "data-skin": id }), name)))),
    h("section", {}, h("h2", {}, "Appearance"), h("div", { class: "row" }, [["system", "System"], ["light", "Light"], ["dark", "Dark"]].map(([id, name]) =>
      h("button", { type: "button", class: "choice", "aria-pressed": String((pref.get("theme") || "system") === id),
        onclick: () => { pref.set("theme", id); applyLook(); renderMenu(); } }, name)))),
    menuExtras());
}
function closeMenu() { menu.hidden = true; menuBtn.setAttribute("aria-expanded", "false"); }
menuBtn.addEventListener("click", e => {
  e.stopPropagation();
  if (!menu.hidden) return closeMenu();
  renderMenu(); menu.hidden = false; menuBtn.setAttribute("aria-expanded", "true");
});
document.addEventListener("click", e => { if (!menu.hidden && !menu.contains(e.target)) closeMenu(); });
const menuAction = (label, fn, disabled = false) =>
  h("button", { type: "button", class: "choice", disabled, onclick: () => { closeMenu(); fn(); } }, label);

/* ---------------- quiz ---------------- */
function quiz(items) {
  const instant = DATA.instant_feedback === true;
  let order = items.map((_, i) => i), pos = 0, states = {};
  const S = i => (states[i] ||= { sel: new Set(), graded: false, ok: null, revealed: false, draft: "" });
  const optionsOf = it => it.type === "true_false" ? ["True", "False"] : (it.options || []);
  const correctIdx = it => it.type === "true_false" ? [it.answer === true || it.answer === "true" ? 0 : 1]
    : Array.isArray(it.answer) ? it.answer.slice().sort((a, b) => a - b) : [it.answer];
  const answerText = it => it.type === "short" ? "" : correctIdx(it).map(i => optionsOf(it)[i]).join("; ");

  menuExtras = () => {
    const missed = order.filter(i => states[i] && states[i].graded && !states[i].ok);
    return h("section", {}, h("h2", {}, "Quiz"), h("div", { class: "choices" },
      menuAction(`Retry missed (${missed.length})`, () => start(shuffle(missed)), !missed.length),
      menuAction("Restart (shuffled)", () => start(shuffle(items.map((_, i) => i))))));
  };
  function start(newOrder) { order = newOrder; pos = 0; states = {}; render(); }

  function progress() {
    const dots = h("nav", { class: "dots", "aria-label": "Questions" }, order.map((qi, p) => {
      const st = states[qi];
      const cls = ["dot", st && st.graded ? (st.ok ? "ok" : "bad") : "", p === pos && pos < order.length ? "cur" : ""].join(" ");
      const label = `Question ${p + 1}` + (st && st.graded ? (st.ok ? ", correct" : ", missed") : "");
      return h("button", { type: "button", class: cls, title: label, "aria-label": label, "aria-current": p === pos ? "step" : null,
        onclick: () => { pos = p; render(); } });
    }));
    const done = order.filter(i => states[i] && states[i].graded).length, w = 12, f = Math.round(done / order.length * w);
    const ascii = h("p", { class: "ascii", "aria-hidden": "true" }, "[", h("b", {}, "#".repeat(f)), ".".repeat(w - f), `] ${done}/${order.length}`);
    return [dots, ascii];
  }

  function render() {
    stage.replaceChildren();
    if (pos >= order.length) return summary();
    setCount(`${pos + 1} / ${order.length}`);
    const qi = order[pos], it = items[qi], st = S(qi);
    const multi = it.type === "multi";
    const typeLabel = { mcq: "Choose one", true_false: "True or false", multi: "Select all that apply", short: "Write your answer" }[it.type];
    const box = h("article", { class: "qbox", "aria-labelledby": "qh" },
      h("div", { class: "meta" }, [it.topic, it.difficulty, ...(it.tags || [])].filter(Boolean).map(t => h("span", {}, t))),
      h("h1", { class: "q", id: "qh", tabindex: "-1" }, it.question),
      h("p", { class: "hint" }, typeLabel + (multi ? ". Graded as an exact set." : "")));

    const actions = h("div", { class: "actions" });
    const next = h("button", { type: "button", class: "btn", onclick: advance },
      pos + 1 < order.length ? "Next" : "See results");

    if (it.type === "short") {
      const ta = h("textarea", { class: "answer", spellcheck: "false", placeholder: "Type your answer, then reveal the model answer…",
        disabled: st.revealed, "aria-label": "Your answer", oninput: e => { st.draft = e.target.value; } });
      ta.value = st.draft;
      box.append(ta);
      if (!st.revealed) {
        actions.append(h("span", { class: "spacer" }), h("button", { type: "button", class: "btn",
          onclick: () => { st.revealed = true; render(); say("Model answer shown. Grade yourself."); } }, "Reveal answer"));
      } else {
        const fb = h("div", { class: "fb" });
        if (st.graded) fb.append(...verdict(st.ok, it, true));
        fb.append(h("p", { class: "label" }, "Model answer"), rich(it.answer, "div"), explain(it), citeList(it));
        box.append(fb);
        if (st.graded) actions.append(h("span", { class: "spacer" }), next);
        else actions.append(h("span", { class: "spacer" }),
          h("button", { type: "button", class: "btn ghost", onclick: () => grade(qi, false) }, "I missed it"),
          h("button", { type: "button", class: "btn", onclick: () => grade(qi, true) }, "I got it"));
      }
      box.append(actions);
      stage.append(...progress(), box);
      return;
    }

    const opts = optionsOf(it), right = correctIdx(it);
    const list = h("div", { class: "opts", role: multi ? "group" : "radiogroup", "aria-labelledby": "qh" }, opts.map((o, i) => {
      const sel = st.sel.has(i);
      let cls = "opt" + (multi ? " multi" : ""), flag = h("span");
      if (st.graded) {
        if (right.includes(i)) { cls += " is-right"; flag = h("span", { class: "flag ok" }, ICON.check(), sel ? "Your pick" : "Answer"); }
        else if (sel) { cls += " is-wrong"; flag = h("span", { class: "flag bad" }, ICON.x(), "Your pick"); }
        else cls += " dim";
      }
      return h("button", { type: "button", class: cls, role: multi ? "checkbox" : "radio", "aria-checked": String(sel), disabled: st.graded,
        onclick: () => pick(qi, i) }, h("span", { class: "mark", "aria-hidden": "true" }), h("span", { class: "txt" }, o), flag);
    }));
    box.append(list);
    if (st.graded) {
      box.append(h("div", { class: "fb" }, ...verdict(st.ok, it), explain(it), citeList(it)));
      actions.append(h("span", { class: "spacer" }), next);
    } else if (!(instant && !multi)) {
      actions.append(h("span", { class: "spacer" }), h("button", { type: "button", class: "btn", id: "confirm", disabled: !st.sel.size,
        onclick: () => confirmAnswer(qi) }, "Confirm"));
    }
    box.append(actions);
    stage.append(...progress(), box);
  }

  function verdict(ok, it, self = false) {
    const ans = !ok && it.type !== "short" ? answerText(it) : "";
    return [
      h("div", { class: "verdict" }, h("span", { class: "badge " + (ok ? "ok" : "bad") }, ok ? ICON.check() : ICON.x(), ok ? "Correct" : "Not quite"),
        self ? h("span", { class: "ans" }, "self-graded") : ans ? h("span", { class: "ans" }, "Answer: " + ans) : null),
      h("p", { class: "verdict-term " + (ok ? "ok" : "bad") }, ok ? "> correct" : ans ? "> wrong, expected: " + ans : "> marked: missed"),
      h("span", { class: "stamp " + (ok ? "ok" : "bad"), "aria-hidden": "true" }, ok ? "Correct" : "Missed"),
    ];
  }

  function pick(qi, i) {
    const it = items[qi], st = S(qi);
    if (st.graded) return;
    if (it.type === "multi") st.sel.has(i) ? st.sel.delete(i) : st.sel.add(i);
    else st.sel = new Set([i]);
    if (instant && it.type !== "multi") return confirmAnswer(qi);
    // Update in place: selecting never reveals anything.
    stage.querySelectorAll(".opt").forEach((b, j) => b.setAttribute("aria-checked", String(st.sel.has(j))));
    const c = $("#confirm"); if (c) c.disabled = !st.sel.size;
  }
  function confirmAnswer(qi) {
    const it = items[qi], st = S(qi);
    if (st.graded || !st.sel.size) return;
    const picked = [...st.sel].sort((a, b) => a - b), right = correctIdx(it);
    grade(qi, picked.length === right.length && picked.every((v, k) => v === right[k]));
  }
  function grade(qi, ok) {
    const st = S(qi);
    st.graded = true; st.ok = ok;
    render();
    say(ok ? "Correct." : "Not quite.");
  }
  function advance() {
    const nextUngraded = order.findIndex((qi, p) => p > pos && !(states[qi] && states[qi].graded));
    const firstUngraded = order.findIndex(qi => !(states[qi] && states[qi].graded));
    pos = nextUngraded >= 0 ? nextUngraded : firstUngraded >= 0 ? firstUngraded : order.length;
    render();
    window.scrollTo({ top: 0 });
  }

  function summary() {
    const total = order.length, right = order.filter(i => states[i].ok).length;
    const missed = order.filter(i => !states[i].ok);
    const hist = store.get(); (hist.attempts ||= []).push({ at: new Date().toISOString(), right, total }); store.set(hist);
    const best = Math.max(...hist.attempts.map(a => a.right / a.total));
    setCount("Results");
    const topics = {};
    for (const i of order) { const t = items[i].topic; if (t) { (topics[t] ||= [0, 0]); topics[t][1]++; if (states[i].ok) topics[t][0]++; } }
    const given = i => {
      const it = items[i], st = states[i];
      if (it.type === "short") return st.draft.trim() ? "self-graded: missed" : "(left blank)";
      return [...st.sel].sort((a, b) => a - b).map(k => optionsOf(it)[k]).join("; ") || "—";
    };
    stage.replaceChildren(...progress(),
      h("div", { class: "score" }, h("span", { class: "big" }, right), h("span", { class: "of" }, `of ${total} · ${Math.round(right / total * 100)}% · best ${Math.round(best * 100)}% over ${hist.attempts.length} attempt${hist.attempts.length > 1 ? "s" : ""}`)),
      Object.keys(topics).length > 1 ? h("section", { class: "sect" }, h("h2", {}, "By topic"), h("ul", { class: "topics" }, Object.entries(topics).map(([t, [r, n]]) =>
        h("li", {}, h("span", { class: "tn", title: t }, t), h("span", { class: "track" }, h("i", { style: `width:${r / n * 100}%` })), h("span", { class: "n" }, `${r}/${n}`))))) : null,
      h("section", { class: "sect" }, h("h2", {}, missed.length ? "To review" : "Perfect score"),
        missed.length ? h("ul", { class: "misses" }, missed.map(i => {
          const it = items[i];
          return h("li", {}, h("span", { class: "mq" }, it.question),
            h("dl", {}, h("dt", {}, "You"), h("dd", {}, given(i)),
              h("dt", {}, "Correct"), h("dd", {}, it.type === "short" ? rich(it.answer, "div") : answerText(it))),
            explain(it));
        })) : h("p", { class: "expl" }, "Every answer was right.")),
      h("div", { class: "actions" }, h("span", { class: "spacer" }),
        missed.length ? h("button", { type: "button", class: "btn ghost", onclick: () => start(shuffle(missed)) }, `Retry missed (${missed.length})`) : null,
        h("button", { type: "button", class: "btn", onclick: () => start(shuffle(items.map((_, i) => i))) }, "Restart (shuffled)")));
  }
  render();
}

/* ---------------- flashcards ---------------- */
function flashcards(items) {
  const ids = items.map((c, i) => c.id || String(i));
  const allTags = [...new Set(items.flatMap(c => c.tags || []))].sort();
  const saved = store.get();
  saved.marks ||= {};
  if (saved.known) {  // older players stored {id: true|false}
    for (const [k, v] of Object.entries(saved.known)) saved.marks[k] ||= v ? "know" : "learn";
    delete saved.known;
  }
  const marks = saved.marks, save = () => store.set(saved);
  let tag = "", deck = [], pos = 0, rot = 0, end = false;

  menuExtras = () => h("section", {}, h("h2", {}, "Flashcards"), h("div", { class: "choices" },
    allTags.length ? h("select", { "aria-label": "Filter by tag", onchange: e => { tag = e.target.value; closeMenu(); build(); } },
      h("option", { value: "" }, "All tags"), allTags.map(t => h("option", { value: t, selected: t === tag }, t))) : null,
    menuAction("Reset marks", () => { for (const k of Object.keys(marks)) delete marks[k]; save(); build(); })));

  function build(onlyLearning = false) {
    deck = items.map((_, i) => i).filter(i => (!tag || (items[i].tags || []).includes(tag)) && (!onlyLearning || marks[ids[i]] === "learn"));
    pos = 0; rot = 0; end = false;
    render();
  }
  const pool = () => items.map((_, i) => i).filter(i => !tag || (items[i].tags || []).includes(tag));
  const counts = idx => ({ know: idx.filter(i => marks[ids[i]] === "know").length, learn: idx.filter(i => marks[ids[i]] === "learn").length });

  function render() {
    stage.replaceChildren();
    const c = counts(deck);
    const tally = h("div", { class: "tally", "aria-label": `${c.know} known, ${c.learn} still learning` },
      h("span", { class: "k" }, "✓ ", c.know), h("span", { class: "l" }, "✗ ", c.learn));
    if (end || !deck.length) return finish(tally);
    setCount(`${pos + 1} / ${deck.length}`);
    const i = deck[pos], card = items[i], mark = marks[ids[i]];
    const flipped = rot % 360 !== 0;
    const inner = h("div", { class: "fc-inner", style: `transform: rotateY(${rot}deg)` },
      h("div", { class: "fc-face front", "aria-hidden": String(flipped) },
        h("div", { class: "side" }, h("span", {}, "Question"), h("span", {}, `${pos + 1} / ${deck.length}`)),
        h("div", { class: "body" }, rich(card.front, "div")),
        card.tags && card.tags.length ? h("div", { class: "tags" }, card.tags.map(t => h("span", { class: "tag" }, t))) : null,
        h("p", { class: "tip" }, "Tap to flip")),
      h("div", { class: "fc-face back", "aria-hidden": String(!flipped) },
        h("div", { class: "side" }, h("span", {}, "Answer"), h("span", {}, `${pos + 1} / ${deck.length}`)),
        h("div", { class: "body" }, rich(card.back, "div")), citeList(card)));
    const fc = h("button", { type: "button", class: "fc" + (flipped ? " flipped" : ""), "aria-label": flipped ? "Answer side. Tap to show the question." : "Question side. Tap to see the answer.",
      onclick: () => {
        rot += 180;  // always turn the same way
        const now = rot % 360 !== 0;
        inner.style.transform = `rotateY(${rot}deg)`;
        fc.classList.toggle("flipped", now);
        fc.setAttribute("aria-label", now ? "Answer side. Tap to show the question." : "Question side. Tap to see the answer.");
        inner.children[0].setAttribute("aria-hidden", String(now));
        inner.children[1].setAttribute("aria-hidden", String(!now));
      } }, inner);
    const dots = h("nav", { class: "dots", "aria-label": "Cards" }, deck.map((ci, p) => {
      const m = marks[ids[ci]];
      return h("button", { type: "button", class: ["dot", m === "know" ? "know" : m === "learn" ? "learn" : "", p === pos ? "cur" : ""].join(" "),
        "aria-label": `Card ${p + 1}` + (m ? (m === "know" ? ", known" : ", still learning") : ""), onclick: () => go(p) });
    }));
    const markBtn = (kind, label, icon) => h("button", { type: "button", class: "mk " + (kind === "know" ? "yes" : "no"), "aria-pressed": String(mark === kind),
      onclick: () => { if (marks[ids[i]] === kind) delete marks[ids[i]]; else marks[ids[i]] = kind; save(); render(); } },
      h("span", { class: "ring" }, icon), h("span", {}, label));
    stage.append(
      h("div", { class: "fc-top" }, dots, tally),
      h("div", { class: "fc-stage" },
        h("button", { type: "button", class: "arrow prev", "aria-label": "Previous card", disabled: pos === 0, onclick: () => go(pos - 1) }, ICON.left()),
        fc,
        h("button", { type: "button", class: "arrow next", "aria-label": pos + 1 < deck.length ? "Next card" : "Finish deck", onclick: () => go(pos + 1) }, ICON.right())),
      h("div", { class: "fc-marks" }, markBtn("learn", "Still learning", ICON.x()), markBtn("know", "Know it", ICON.check())));
  }
  function go(p) {
    if (p < 0) return;
    if (p >= deck.length) { end = true; render(); return; }
    pos = p; rot = 0; render();
  }
  function finish(tally) {
    setCount("Done");
    const c = counts(deck), unmarked = deck.length - c.know - c.learn;
    stage.append(h("div", { class: "fc-top" }, h("span"), tally),
      h("div", { class: "score" }, h("span", { class: "big" }, deck.length ? `✓ ${c.know}` : "0"),
        h("span", { class: "of" }, deck.length ? `known · ${c.learn} still learning${unmarked ? ` · ${unmarked} unmarked` : ""}` : "No cards match this filter.")),
      h("div", { class: "actions" }, h("span", { class: "spacer" }),
        h("button", { type: "button", class: "btn ghost", disabled: !counts(pool()).learn, onclick: () => build(true) }, `Review ✗ cards (${counts(pool()).learn})`),
        h("button", { type: "button", class: "btn", onclick: () => build(false) }, "Start over")));
  }
  build();
}

(DATA.type === "flashcards" ? flashcards : quiz)(DATA.items);
