/* eztudy answer checks: pure functions (no DOM) for the exactly-checked item types. Inlined into the player before
   app.js; also loadable from node for tests. Each check returns {ok, marks, right, total}: `marks[i]` is true/false
   for each blank / row / pair, and `ok` is true only when every mark is. */
"use strict";

// Text the student typed vs. an accepted answer: case-, accent-, whitespace- and edge-punctuation-insensitive.
const normText = (s, caseSensitive = false) => {
  let t = String(s ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/\s+/g, " ").trim()
    .replace(/^[\s.,;:!?"'`()\[\]]+|[\s.,;:!?"'`()\[\]]+$/g, "");
  return caseSensitive ? t : t.toLowerCase();
};

// "3,5" -> 3.5, "1e-3", "-2", "3/4", "1 000" -> number; NaN when it isn't one.
function parseNumber(input) {
  let s = String(input ?? "").replace(/[\s_  ]/g, "").replace(/^\+/, "").replace(/−/g, "-");
  if (!s) return NaN;
  const frac = s.match(/^(-?\d+(?:\.\d+)?)\/(\d+(?:\.\d+)?)$/);
  if (frac) return Number(frac[2]) === 0 ? NaN : Number(frac[1]) / Number(frac[2]);
  if (s.includes(",") && !s.includes(".")) s = /^-?\d{1,3}(,\d{3})+$/.test(s) && !/^-?0,/.test(s) ? s.replace(/,/g, "") : s.replace(",", ".");
  else s = s.replace(/,/g, "");
  return /^-?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(s) ? Number(s) : NaN;
}

// Decimal places of the key as written in the JSON: 9.81 -> 2, 1.5e-7 -> 8, 300 -> 0.
const decimals = n => { const [m, e] = String(n).toLowerCase().split("e"); return Math.max(0, (m.split(".")[1] || "").length - Number(e || 0)); };

// Allowed error for a numeric item: `tolerance` number (absolute) or "N%" (relative); default: half a unit in the
// answer's last decimal place, so 9.81 accepts 9.805..9.815.
function allowedError(item) {
  const tol = item.tolerance, ans = Number(item.answer);
  if (typeof tol === "string" && /%\s*$/.test(tol)) return Math.abs(ans) * parseFloat(tol) / 100;
  if (typeof tol === "number") return Math.abs(tol);
  return 0.5 * Math.pow(10, -decimals(item.answer));
}

function checkNumeric(item, input) {
  const v = parseNumber(input), ok = Number.isFinite(v) && Math.abs(v - Number(item.answer)) <= allowedError(item) * (1 + 1e-9) + 1e-12;
  return { ok, marks: [ok], right: ok ? 1 : 0, total: 1, value: v };
}

// One blank's accepted answers: "x", ["x", "y"], or {accept: [...], regex: "...", case_sensitive: bool}.
const blankSpec = b => typeof b === "string" ? { accept: [b] } : Array.isArray(b) ? { accept: b } : (b || { accept: [] });
const blankAnswer = b => (blankSpec(b).accept || [])[0] ?? "";
function blankOk(b, given) {
  const spec = blankSpec(b), cs = !!spec.case_sensitive, g = normText(given, cs);
  if (!g) return false;
  if ((spec.accept || []).some(a => normText(a, cs) === g)) return true;
  if (spec.regex) { try { return new RegExp("^(?:" + spec.regex + ")$", cs ? "" : "i").test(String(given).trim()); } catch { return false; } }
  return false;
}
const tally = marks => { const right = marks.filter(Boolean).length; return { ok: right === marks.length && marks.length > 0, marks, right, total: marks.length }; };

const checkCloze = (item, inputs) => tally((item.answer || []).map((b, i) => blankOk(b, (inputs || [])[i])));

// `order`: the student's sequence of entries (strings). Marks: each position holds the right entry.
const checkOrdering = (item, order) => tally((item.answer || []).map((a, i) => (order || [])[i] === a));

// `picks[i]`: the right-hand value chosen for left item i (in `answer` order).
const checkMatching = (item, picks) => tally((item.answer || []).map(([, r], i) => (picks || [])[i] === r));

// Shuffle that never returns the solved order (when there is more than one entry).
function shuffleAway(list, rnd = Math.random) {
  if (list.length < 2) return list.slice();
  for (let tries = 0; tries < 20; tries++) {
    const a = list.slice();
    for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
    if (a.some((x, i) => x !== list[i])) return a;
  }
  return list.slice(1).concat(list[0]);
}

if (typeof module !== "undefined") module.exports = { normText, parseNumber, allowedError, checkNumeric, blankOk, blankAnswer, checkCloze, checkOrdering, checkMatching, shuffleAway };
