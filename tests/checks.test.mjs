// Unit tests for the player's answer checks (src/eztudy/templates/player/checks.js). Run: node tests/checks.test.mjs
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const C = require("../src/eztudy/templates/player/checks.js");
let failed = 0, passed = 0;
const eq = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? passed++ : (failed++, console.error(`FAIL ${name}: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`));
};

// parseNumber
for (const [s, n] of [["3,5", 3.5], ["1e-3", 0.001], ["-2", -2], ["+4", 4], ["3/4", 0.75], ["1 000", 1000], ["1,234", 1234],
  ["1,234.5", 1234.5], ["0,5", 0.5], [".5", 0.5], ["−3", -3], ["9.81", 9.81]]) eq(`parse ${s}`, C.parseNumber(s), n);
for (const s of ["", "abc", "1/0", "1..2", "3 m"]) eq(`parse NaN ${s}`, Number.isNaN(C.parseNumber(s)), true);

// numeric tolerance
const g = { answer: 9.81 };
eq("default tol in", C.checkNumeric(g, "9.814").ok, true);
eq("default tol out", C.checkNumeric(g, "9.82").ok, false);
eq("abs tol", C.checkNumeric({ answer: 9.81, tolerance: 0.05 }, "9.86").ok, true);
eq("abs tol out", C.checkNumeric({ answer: 9.81, tolerance: 0.05 }, "9.87").ok, false);
eq("pct tol", C.checkNumeric({ answer: 200, tolerance: "2%" }, "204").ok, true);
eq("pct tol out", C.checkNumeric({ answer: 200, tolerance: "2%" }, "204.5").ok, false);
eq("int exact", C.checkNumeric({ answer: 300 }, "300.4").ok, true);
eq("sci key", C.checkNumeric({ answer: 1.5e-7 }, "1.5e-7").ok, true);
eq("garbage", C.checkNumeric(g, "nine").ok, false);

// cloze
const cz = { answer: [["mitochondria", "mitochondrion"], { accept: ["oxidative phosphorylation"], regex: "ox ?phos" }, { accept: ["Na"], case_sensitive: true }] };
eq("cloze all", C.checkCloze(cz, ["Mitochondrion.", "OXPHOS", "Na"]), { ok: true, marks: [true, true, true], right: 3, total: 3 });
eq("cloze accents/case", C.blankOk("café", "  CAFE "), true);
eq("cloze case-sensitive", C.checkCloze(cz, ["mitochondria", "oxidative  phosphorylation", "na"]).marks, [true, true, false]);
eq("cloze blank", C.checkCloze(cz, ["", "", ""]).right, 0);
eq("cloze bad regex", C.blankOk({ accept: [], regex: "(" }, "x"), false);
eq("blank answer", C.blankAnswer(["a", "b"]), "a");

// ordering
const od = { answer: ["P", "M", "A", "T"] };
eq("order right", C.checkOrdering(od, ["P", "M", "A", "T"]).ok, true);
eq("order marks", C.checkOrdering(od, ["P", "A", "M", "T"]).marks, [true, false, false, true]);

// matching (many-to-one allowed)
const mt = { answer: [["Mito", "ATP"], ["Chloro", "ATP"], ["Ribo", "Proteins"]] };
eq("match right", C.checkMatching(mt, ["ATP", "ATP", "Proteins"]).ok, true);
eq("match partial", C.checkMatching(mt, ["ATP", "Lipids", undefined]), { ok: false, marks: [true, false, false], right: 1, total: 3 });

// shuffleAway never returns the solved order
for (let k = 0; k < 200; k++) { const s = C.shuffleAway(["a", "b"]); if (s.join() === "a,b") { failed++; console.error("FAIL shuffleAway"); break; } }
eq("shuffle constant rnd", C.shuffleAway(["a", "b", "c"], () => 0.999).join(), "b,c,a");

console.log(`${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
