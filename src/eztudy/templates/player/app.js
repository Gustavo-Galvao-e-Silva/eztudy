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

/* Markdown subset, built as DOM (never innerHTML, so quiz text can't inject markup).
   Blocks: ``` / ~~~ fences, paragraphs (single newlines kept), - * + and 1. lists (nestable), # headings, > quotes,
   unfenced multi-line code. Inline: `code`, **bold**, *em* / _em_, ~~strike~~, [text](https://…), \-escapes. */
const looksLikeCode = t => /\n/.test(t) && (/[{};]\s*$/m.test(t) || /^(\t| {2,})\S/m.test(t));
const INLINE = /\\([\\`*_~\[\]()#>+\-.!|])|(`+)([^`]|[^`][\s\S]*?[^`])\2(?!`)|\*\*(?=\S)([\s\S]*?\S)\*\*|~~(?=\S)([\s\S]*?\S)~~|\*(?=[^\s*])([\s\S]*?[^\s*\\])\*(?!\*)|(?<![\w\\])_(?=[^\s_])([\s\S]*?[^\s_])_(?!\w)|\[([^\]\n]+)\]\(((?:https?:\/\/|mailto:)[^\s)]+)\)/g;
function mdInline(text) {
  const s = String(text ?? ""), out = [], re = new RegExp(INLINE.source, "g");
  let last = 0, m;
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(s.slice(last, m.index));
    if (m[1] != null) out.push(m[1]);
    else if (m[2]) out.push(h("code", {}, m[3].length > 2 && /^ .* $/.test(m[3]) ? m[3].slice(1, -1) : m[3]));
    else if (m[4] != null) out.push(h("strong", {}, mdInline(m[4])));
    else if (m[5] != null) out.push(h("del", {}, mdInline(m[5])));
    else if (m[6] != null || m[7] != null) out.push(h("em", {}, mdInline(m[6] ?? m[7])));
    else out.push(h("a", { href: m[9], target: "_blank", rel: "noopener noreferrer" }, mdInline(m[8])));
    last = re.lastIndex;
  }
  if (last < s.length) out.push(s.slice(last));
  return out;
}
const FENCE = /^ {0,3}(`{3,}|~{3,})\s*([\w+#.-]*)/, ITEM = /^( *)([-*+]|\d{1,9}[.)])\s+(.*)$/, HEAD = /^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$/, QUOTE = /^ {0,3}> ?/;
const pre = code => h("pre", { class: "code" }, h("code", {}, code));
function mdBlocks(text) {
  const lines = String(text ?? "").replace(/\r\n?/g, "\n").split("\n"), out = [];
  const starts = l => FENCE.test(l) || HEAD.test(l) || QUOTE.test(l) || (ITEM.test(l) && /^ *([-*+]|1[.)])\s/.test(l));
  let i = 0, m;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    if ((m = line.match(FENCE))) {
      const close = new RegExp("^ {0,3}" + m[1][0] + "{" + m[1].length + ",}\\s*$"), body = [];
      for (i++; i < lines.length && !close.test(lines[i]); i++) body.push(lines[i]);
      i++; out.push(pre(body.join("\n"))); continue;
    }
    if ((m = line.match(HEAD))) { out.push(h("p", { class: "md-h" }, h("strong", {}, mdInline(m[2])))); i++; continue; }
    if (QUOTE.test(line)) {
      const body = [];
      while (i < lines.length && QUOTE.test(lines[i])) body.push(lines[i++].replace(QUOTE, ""));
      out.push(h("blockquote", {}, mdBlocks(body.join("\n")))); continue;
    }
    if ((m = line.match(ITEM))) {
      const indent = m[1].length, ordered = /\d/.test(m[2]), items = [];
      while (i < lines.length && (m = lines[i].match(ITEM)) && m[1].length === indent && /\d/.test(m[2]) === ordered) {
        const body = [m[3]], start = items.length ? null : parseInt(m[2], 10);
        // Continuation: indented lines (incl. nested lists), or blank lines followed by indented ones.
        for (i++; i < lines.length; i++) {
          const l = lines[i];
          if (l.trim() && l.search(/\S/) > indent) body.push(l.slice(Math.min(l.search(/\S/), indent + 2)));
          else if (!l.trim() && lines[i + 1] && lines[i + 1].search(/\S/) > indent) body.push("");
          else break;
        }
        items.push({ body: body.join("\n"), start });
      }
      const list = h(ordered ? "ol" : "ul", ordered && items[0].start !== 1 ? { start: items[0].start } : {},
        items.map(it => h("li", {}, mdFlow(it.body))));
      out.push(list); continue;
    }
    const para = [line];
    for (i++; i < lines.length && lines[i].trim() && !starts(lines[i]); i++) para.push(lines[i]);
    const t = para.join("\n");
    out.push(looksLikeCode(t) ? pre(t.replace(/\s+$/, "")) : h("p", {}, mdInline(t)));
  }
  return out;
}
// Flow content for inline-ish slots (options, list items): a lone plain paragraph unwraps to its inline nodes.
const mdFlow = text => {
  const b = mdBlocks(text);
  return b.length === 1 && b[0].tagName === "P" && !b[0].className ? [...b[0].childNodes] : b;
};
const rich = (text, tag = "div") => h(tag, { class: "rich" }, mdFlow(text));
// The question heading takes the first paragraph; anything after it (code, lists) follows in a body block.
const questionEls = q => {
  const blocks = mdBlocks(q), head = h("h1", { class: "q rich", id: "qh", tabindex: "-1" });
  if (blocks[0] && blocks[0].tagName === "P" && !blocks[0].className) head.append(...blocks.shift().childNodes);
  else head.setAttribute("aria-label", String(q ?? "").split("\n").find(l => l.trim() && !FENCE.test(l)) || "Question");
  return [head, blocks.length ? h("div", { class: "q-more rich" }, blocks) : null];
};
// Join several answers (option texts) as rendered Markdown, separated by "; ".
const joinRich = texts => texts.flatMap((t, k) => k ? ["; ", ...mdFlow(t)] : mdFlow(t));

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

/* ---------------- performance report (picked up by `eztudy report import`) ---------------- */
const newSession = () => ({ id: Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 8), started: new Date().toISOString(), recorded: false });
const makeReport = (session, items, score) => ({
  eztudy_report: 1, kind: DATA.type === "flashcards" ? "flashcards" : "quiz",
  deck: { id: DATA.id || DATA.title, title: DATA.title }, session: session.id,
  started_at: session.started, finished_at: new Date().toISOString(), score, items,
});
const reportName = r => `${String(r.deck.id).replace(/[^\w.-]+/g, "-").replace(/^-+|-+$/g, "") || "deck"}.${r.finished_at.replace(/[-:]/g, "").slice(0, 15)}.eztudy-report.json`;
function saveReport(r) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(r, null, 2)], { type: "application/json" }));
  const a = h("a", { href: url, download: reportName(r) });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  say("Report saved. Ask your agent to run eztudy report import.");
}
function copyReport(r, btn) {
  const text = JSON.stringify(r, null, 2);
  const done = ok => { btn.textContent = ok ? "Copied" : "Copy failed"; say(ok ? "Report copied. Paste it to your agent." : "Could not copy the report."); };
  const fallback = () => {
    const ta = h("textarea", { style: "position:fixed;opacity:0" }); ta.value = text; document.body.append(ta); ta.select();
    let ok = false; try { ok = document.execCommand("copy"); } catch {} ta.remove(); done(ok);
  };
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(() => done(true), fallback);
  else fallback();
}
const reportBox = r => {
  const copy = h("button", { type: "button", class: "btn ghost", onclick: () => copyReport(r, copy) }, "Copy report");
  return h("section", { class: "sect report" }, h("h2", {}, "Performance report"),
    h("p", { class: "expl" }, "Save this session for your study agent so the next quiz or deck targets what you missed."),
    h("div", { class: "actions" }, h("button", { type: "button", class: "btn ghost", onclick: () => saveReport(r) }, "Save report"), copy));
};

const stage = $("#stage");
$("#title").textContent = DATA.title;
$("#desc").textContent = DATA.description || "";
$("#winTitle").textContent = DATA.title;
const setCount = s => { $("#count").textContent = s; };

const explain = item => {
  if (!item.explanation) return null;
  const el = rich(item.explanation);
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
    ...[].concat(menuExtras()).filter(Boolean));
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

/* ---------------- code editor (vendored CodeMirror, only present when the quiz has code items) ---------------- */
const LANG_NAMES = { java: "Java", python: "Python", cpp: "C/C++", javascript: "JavaScript", sql: "SQL", go: "Go", rust: "Rust" };
const hasEditor = () => !!(window.EZCM && window.EZCM.createEditor);
const vimOn = () => pref.get("vim") === "on";
let liveEditors = [];
const dropEditors = () => { for (const e of liveEditors) { try { e.destroy(); } catch {} } liveEditors = []; };
// Mount an editor in `host`; returns the editor, or null after rendering the textarea fallback.
function mountEditor(host, opts, fallback) {
  if (hasEditor()) {
    try { const ed = window.EZCM.createEditor(host, { vim: vimOn(), ...opts }); liveEditors.push(ed); return ed; }
    catch (e) { console.error("eztudy: editor failed, using plain text", e); }
  }
  host.replaceChildren(...fallback());
  return null;
}
const codeBlock = text => pre(String(text ?? "").replace(/\n+$/, ""));

/* ---------------- quiz ---------------- */
function quiz(items) {
  const instant = DATA.instant_feedback === true;
  let order = items.map((_, i) => i), pos = 0, states = {}, session = newSession();
  const S = i => (states[i] ||= { sel: new Set(), graded: false, ok: null, revealed: false, draft: null, ticks: new Set() });
  const draftOf = (it, st) => st.draft ?? (it.type === "code" ? String(it.starter || "").replace("$0", "") : "");
  const hasCode = items.some(it => it.type === "code");
  let currentEditor = null;
  const optionsOf = it => it.type === "true_false" ? ["True", "False"] : (it.options || []);
  const correctIdx = it => it.type === "true_false" ? [it.answer === true || it.answer === "true" ? 0 : 1]
    : Array.isArray(it.answer) ? it.answer.slice().sort((a, b) => a - b) : [it.answer];
  const answerText = it => it.type === "short" || it.type === "code" ? "" : correctIdx(it).map(i => optionsOf(it)[i]).join("; ");
  const answerRich = it => it.type === "short" || it.type === "code" ? [] : joinRich(correctIdx(it).map(i => optionsOf(it)[i]));

  menuExtras = () => {
    const missed = order.filter(i => states[i] && states[i].graded && !states[i].ok);
    return [h("section", {}, h("h2", {}, "Quiz"), h("div", { class: "choices" },
      menuAction(`Retry missed (${missed.length})`, () => start(shuffle(missed)), !missed.length),
      menuAction("Restart (shuffled)", () => start(shuffle(items.map((_, i) => i)))))),
      hasCode && hasEditor() ? h("section", {}, h("h2", {}, "Code editor"), h("div", { class: "row" }, [["off", "Standard keys"], ["on", "Vim keys"]].map(([v, name]) =>
        h("button", { type: "button", class: "choice", "aria-pressed": String((vimOn() ? "on" : "off") === v),
          onclick: () => { pref.set("vim", v); if (currentEditor) currentEditor.setVim(v === "on"); renderMenu(); } }, name)))) : null];
  };
  function start(newOrder) { order = newOrder; pos = 0; states = {}; session = newSession(); render(); }

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
    dropEditors(); currentEditor = null;
    stage.replaceChildren();
    if (pos >= order.length) return summary();
    setCount(`${pos + 1} / ${order.length}`);
    const qi = order[pos], it = items[qi], st = S(qi);
    const multi = it.type === "multi";
    const lang = it.type === "code" && hasEditor() ? window.EZCM.resolveLang(it.language).id : "";
    const typeLabel = { mcq: "Choose one", true_false: "True or false", multi: "Select all that apply", short: "Write your answer",
      code: "Write code" + (LANG_NAMES[lang] || it.language ? ` (${LANG_NAMES[lang] || it.language})` : "") + ", then submit to compare with a model solution" }[it.type];
    const box = h("article", { class: "qbox", "aria-labelledby": "qh" },
      h("div", { class: "meta" }, [it.topic, it.difficulty, ...(it.tags || [])].filter(Boolean).map(t => h("span", {}, t))),
      ...questionEls(it.question),
      h("p", { class: "hint" }, typeLabel + (multi ? ". Graded as an exact set." : "")));

    // Every question gets Back / Next. Next is the primary action once the question is answered.
    const allGraded = order.every(q => states[q] && states[q].graded);
    const back = h("button", { type: "button", class: "btn ghost nav-back", disabled: pos === 0, "aria-label": "Previous question",
      onclick: () => goTo(pos - 1) }, ICON.left(), "Back");
    const next = h("button", { type: "button", class: "btn nav-next" + (st.graded ? "" : " ghost"), onclick: forward,
      "aria-label": pos + 1 < order.length ? "Next question" : allGraded ? "See results" : "Go to the first unanswered question" },
      pos + 1 < order.length || !allGraded ? "Next" : "See results", ICON.right());
    const actions = h("div", { class: "actions" }, back, h("span", { class: "spacer" }));

    if (it.type === "code") return renderCode(qi, it, st, box, actions, next);

    if (it.type === "short") {
      const ta = h("textarea", { class: "answer", spellcheck: "false", placeholder: "Type your answer, then reveal the model answer…",
        disabled: st.revealed, "aria-label": "Your answer", oninput: e => { st.draft = e.target.value; } });
      ta.value = draftOf(it, st);
      box.append(ta);
      if (!st.revealed) {
        actions.append(h("button", { type: "button", class: "btn",
          onclick: () => { st.revealed = true; render(); say("Model answer shown. Grade yourself."); } }, "Reveal answer"), next);
      } else {
        const fb = h("div", { class: "fb" });
        if (st.graded) fb.append(...verdict(st.ok, it, true));
        fb.append(h("p", { class: "label" }, "Model answer"), rich(it.answer, "div"), explain(it), citeList(it));
        box.append(fb);
        if (!st.graded) actions.append(
          h("button", { type: "button", class: "btn ghost", onclick: () => grade(qi, false) }, "I missed it"),
          h("button", { type: "button", class: "btn", onclick: () => grade(qi, true) }, "I got it"));
        actions.append(next);
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
        onclick: () => pick(qi, i) }, h("span", { class: "mark", "aria-hidden": "true" }), h("span", { class: "txt rich" }, mdFlow(o)), flag);
    }));
    box.append(list);
    if (st.graded) {
      box.append(h("div", { class: "fb" }, ...verdict(st.ok, it), explain(it), citeList(it)));
    } else if (!(instant && !multi)) {
      actions.append(h("button", { type: "button", class: "btn", id: "confirm", disabled: !st.sel.size,
        onclick: () => confirmAnswer(qi) }, "Confirm"));
    }
    actions.append(next);
    box.append(actions);
    stage.append(...progress(), box);
  }

  function renderCode(qi, it, st, box, actions, next) {
    const host = h("div", { class: "code-host" });
    box.append(host);
    const fallbackArea = () => {
      const ta = h("textarea", { class: "answer code-fallback", spellcheck: "false", disabled: st.revealed, "aria-label": "Your code",
        placeholder: "Write your code here…", oninput: e => { st.draft = e.target.value; } });
      ta.value = draftOf(it, st);
      return [ta, h("p", { class: "hint" }, "Editor unavailable: plain text mode.")];
    };
    const rubric = Array.isArray(it.rubric) ? it.rubric : [];
    let fb = null;
    if (!st.revealed) {
      actions.append(h("button", { type: "button", class: "btn", onclick: () => { st.draft = draftOf(it, st); st.revealed = true; render(); say("Submitted. Compare with the model solution, then grade yourself."); } }, "Submit"), next);
    } else {
      fb = h("div", { class: "fb" });
      if (st.graded) fb.append(...verdict(st.ok, it, true));
      const model = h("div", { class: "code-host model" });
      fb.append(h("p", { class: "label" }, "Model solution"), model);
      if (rubric.length) fb.append(rubricList(it, st, rubric));
      fb.append(...[explain(it), citeList(it)].filter(Boolean));
      box.append(fb);
      if (!st.graded) actions.append(
        h("button", { type: "button", class: "btn ghost", onclick: () => grade(qi, false) }, "I missed it"),
        h("button", { type: "button", class: "btn", onclick: () => grade(qi, true) }, "I got it"));
      actions.append(next);
    }
    box.append(actions);
    stage.append(...progress(), box);
    // Mount after the box is in the document so CodeMirror can measure it.
    const ed = mountEditor(host, { doc: st.draft ?? String(it.starter || ""), language: it.language, identifiers: (it.context || {}).identifiers || [],
      readOnly: st.revealed, label: "Your code", onChange: text => { st.draft = text; } }, fallbackArea);
    if (ed && !st.revealed) currentEditor = ed;
    if (ed && st.revealed && rubric.some(c => c.match)) {
      ed.setHints(window.EZCM.rubricHints(ed.getText(), rubric).filter(r => r.checked).map(r => ({ line: r.line || 1, ok: !!r.line, text: r.criterion.text }))
        .filter(hh => hh.ok));
    }
    if (fb) mountEditor(fb.querySelector(".code-host.model"), { doc: it.answer, language: it.language, readOnly: true, label: "Model solution" },
      () => [codeBlock(it.answer)]);
  }

  // Rubric: a self-check list. `match` hints come from the quiz author, are labelled as hints, never grade.
  function rubricList(it, st, rubric) {
    const hints = hasEditor() ? window.EZCM.rubricHints(st.draft || "", rubric) : rubric.map(c => ({ criterion: c, line: null, checked: false }));
    const total = rubric.reduce((a, c) => a + (+c.points || 0), 0);
    const ticked = rubric.reduce((a, c, k) => a + (st.ticks.has(k) ? (+c.points || 0) : 0), 0);
    return h("section", { class: "rubric", "aria-label": "Rubric" },
      h("p", { class: "label" }, "Rubric: tick what your code does", total ? h("span", { class: "pts" }, ` ${ticked} / ${total} pts`) : null),
      h("ul", {}, rubric.map((c, k) => {
        const hint = hints[k];
        return h("li", {}, h("button", { type: "button", class: "tick", role: "checkbox", "aria-checked": String(st.ticks.has(k)),
          onclick: () => { st.ticks.has(k) ? st.ticks.delete(k) : st.ticks.add(k); render(); } },
          h("span", { class: "box", "aria-hidden": "true" }, st.ticks.has(k) ? ICON.check() : null),
          h("span", { class: "txt rich" }, mdFlow(c.text)), c.points != null ? h("span", { class: "pts" }, `${c.points} pt`) : null),
          hint && hint.checked ? h("span", { class: "rhint " + (hint.line ? "ok" : "bad") }, hint.line ? `hint: line ${hint.line}` : "hint: not found") : null);
      })));
  }

  function verdict(ok, it, self = false) {
    const ans = !ok && it.type !== "short" ? answerRich(it) : [];
    return [
      h("div", { class: "verdict" }, h("span", { class: "badge " + (ok ? "ok" : "bad") }, ok ? ICON.check() : ICON.x(), ok ? "Correct" : "Not quite"),
        self ? h("span", { class: "ans" }, "self-graded") : ans.length ? h("span", { class: "ans" }, "Answer: ", ans) : null),
      h("p", { class: "verdict-term " + (ok ? "ok" : "bad") }, ok ? "> correct" : ans.length ? ["> wrong, expected: ", ans.map(n => n.cloneNode(true))] : "> marked: missed"),
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
  function goTo(p) {
    pos = Math.max(0, Math.min(p, order.length));
    render();
    window.scrollTo({ top: 0 });
  }
  function forward() {
    if (pos + 1 < order.length) return goTo(pos + 1);
    // On the last question: results if everything is answered, else the first question still open.
    const firstOpen = order.findIndex(qi => !(states[qi] && states[qi].graded));
    goTo(firstOpen >= 0 ? firstOpen : order.length);
  }

  function summary() {
    const total = order.length, right = order.filter(i => states[i].ok).length;
    const missed = order.filter(i => !states[i].ok);
    const hist = store.get(); hist.attempts ||= [];
    if (!session.recorded) { hist.attempts.push({ at: new Date().toISOString(), right, total }); store.set(hist); session.recorded = true; }
    const best = Math.max(...hist.attempts.map(a => a.right / a.total));
    setCount("Results");
    const topics = {};
    for (const i of order) { const t = items[i].topic; if (t) { (topics[t] ||= [0, 0]); topics[t][1]++; if (states[i].ok) topics[t][0]++; } }
    const given = i => {
      const it = items[i], st = states[i];
      if (it.type === "short" || it.type === "code") return (st.draft || "").trim() ? "self-graded: missed" : "(left blank)";
      const picked = [...st.sel].sort((a, b) => a - b).map(k => optionsOf(it)[k]);
      return picked.length ? joinRich(picked) : "—";
    };
    session.report ||= makeReport(session, order.map(i => {
      const it = items[i], st = states[i];
      return { id: it.id || `q${i + 1}`, type: it.type, topic: it.topic || null, tags: it.tags || [], difficulty: it.difficulty || null,
        question: it.question, result: st.ok ? "correct" : "wrong", graded: it.type === "short" || it.type === "code" ? "self" : "auto",
        given: it.type === "short" || it.type === "code" ? (st.draft || "") : [...st.sel].sort((a, b) => a - b).map(k => optionsOf(it)[k]).join("; "),
        correct_answer: it.type === "short" || it.type === "code" ? it.answer : answerText(it),
        ...(it.type === "code" ? { language: it.language || null,
          rubric: (it.rubric || []).map((c, k) => ({ id: c.id || null, text: c.text, points: c.points ?? null, ticked: st.ticks.has(k) })) } : {}) };
    }), { right, total });
    stage.replaceChildren(...[...progress(),
      h("div", { class: "score" }, h("span", { class: "big" }, right), h("span", { class: "of" }, `of ${total} · ${Math.round(right / total * 100)}% · best ${Math.round(best * 100)}% over ${hist.attempts.length} attempt${hist.attempts.length > 1 ? "s" : ""}`)),
      Object.keys(topics).length > 1 ? h("section", { class: "sect" }, h("h2", {}, "By topic"), h("ul", { class: "topics" }, Object.entries(topics).map(([t, [r, n]]) =>
        h("li", {}, h("span", { class: "tn", title: t }, t), h("span", { class: "track" }, h("i", { style: `width:${r / n * 100}%` })), h("span", { class: "n" }, `${r}/${n}`))))) : null,
      h("section", { class: "sect" }, h("h2", {}, missed.length ? "To review" : "Perfect score"),
        missed.length ? h("ul", { class: "misses" }, missed.map(i => {
          const it = items[i];
          return h("li", {}, h("div", { class: "mq rich" }, mdFlow(it.question)),
            h("dl", {}, h("dt", {}, "You"), h("dd", {}, given(i)),
              h("dt", {}, "Correct"), h("dd", {}, it.type === "short" ? rich(it.answer, "div") : it.type === "code" ? codeBlock(it.answer) : answerRich(it))),
            explain(it));
        })) : h("p", { class: "expl" }, "Every answer was right.")),
      reportBox(session.report),
      h("div", { class: "actions" }, h("span", { class: "spacer" }),
        missed.length ? h("button", { type: "button", class: "btn ghost", onclick: () => start(shuffle(missed)) }, `Retry missed (${missed.length})`) : null,
        h("button", { type: "button", class: "btn", onclick: () => start(shuffle(items.map((_, i) => i))) }, "Restart (shuffled)"))].filter(Boolean));
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
  let tag = "", deck = [], pos = 0, rot = 0, end = false, session = newSession(), seen = new Set();

  menuExtras = () => h("section", {}, h("h2", {}, "Flashcards"), h("div", { class: "choices" },
    allTags.length ? h("select", { "aria-label": "Filter by tag", onchange: e => { tag = e.target.value; closeMenu(); build(); } },
      h("option", { value: "" }, "All tags"), allTags.map(t => h("option", { value: t, selected: t === tag }, t))) : null,
    menuAction("Reset marks", () => { for (const k of Object.keys(marks)) delete marks[k]; save(); build(); })));

  function build(onlyLearning = false) {
    deck = items.map((_, i) => i).filter(i => (!tag || (items[i].tags || []).includes(tag)) && (!onlyLearning || marks[ids[i]] === "learn"));
    pos = 0; rot = 0; end = false; session = newSession(); seen = new Set();
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
    seen.add(i);
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
    const reviewed = deck.filter(i => seen.has(i));
    const r = reviewed.length ? makeReport(session, reviewed.map(i => ({
      id: ids[i], tags: items[i].tags || [], front: items[i].front, correct_answer: items[i].back,
      result: marks[ids[i]] || "unmarked" })), { ...counts(reviewed), unmarked: reviewed.length - counts(reviewed).know - counts(reviewed).learn }) : null;
    stage.append(...[h("div", { class: "fc-top" }, h("span"), tally),
      h("div", { class: "score" }, h("span", { class: "big" }, deck.length ? `✓ ${c.know}` : "0"),
        h("span", { class: "of" }, deck.length ? `known · ${c.learn} still learning${unmarked ? ` · ${unmarked} unmarked` : ""}` : "No cards match this filter.")),
      r ? reportBox(r) : null,
      h("div", { class: "actions" }, h("span", { class: "spacer" }),
        h("button", { type: "button", class: "btn ghost", disabled: !counts(pool()).learn, onclick: () => build(true) }, `Review ✗ cards (${counts(pool()).learn})`),
        h("button", { type: "button", class: "btn", onclick: () => build(false) }, "Start over"))].filter(Boolean));
  }
  build();
}

(DATA.type === "flashcards" ? flashcards : quiz)(DATA.items);
