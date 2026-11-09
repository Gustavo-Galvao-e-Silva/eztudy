// node test/run.mjs — tests for the pure editor modules (lint, completions). Exit 1 on failure.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { lintCode } from "../src/lint.js";
import { localCompletions } from "../src/complete.js";

const here = dirname(fileURLToPath(import.meta.url));
const fx = (name) => readFileSync(join(here, "fixtures", name), "utf8");
let failed = 0, passed = 0;
const check = (name, cond, detail = "") => {
  if (cond) passed++;
  else { failed++; console.log(`FAIL ${name}${detail ? "\n     " + detail : ""}`); }
};
const lineOf = (text, pos) => text.slice(0, pos).split("\n").length;
const show = (text, ds) => ds.map((d) => `line ${lineOf(text, d.from)}: ${d.message} | ${text.split("\n")[lineOf(text, d.from) - 1].trim()}`).join("\n     ");

// 1. Model answers: zero false alarms.
const FIXTURES = { "MinHeap.java": "java", "bfs.py": "python", "list.cpp": "cpp", "lib.rs": "rust", "main.go": "go", "app.js": "javascript", "query.sql": "sql", "Stress.java": "java", "stress.cpp": "cpp" };
for (const [file, lang] of Object.entries(FIXTURES)) {
  const text = fx(file), ds = lintCode(text, lang);
  check(`no false alarms in ${file}`, ds.length === 0, show(text, ds));
}

// 2. Injected errors are flagged on the right line.
const replaceOnce = (text, a, b) => { if (!text.includes(a)) throw new Error(`fixture lacks ${JSON.stringify(a)}`); return text.replace(a, b); };
const INJECT = [
  ["MinHeap.java", "java", "T min = backingArray[1];", "T min = backingArray[1]", "Missing ';'"],
  ["MinHeap.java", "java", "downHeap(1);", "downHeap(1)", "Missing ';'"],
  ["MinHeap.java", "java", "return min;", "return min", "Missing ';'"],
  ["MinHeap.java", "java", "child++;\n", "child++;\n}\n", "Unmatched '}'"],
  ["MinHeap.java", "java", "downHeap(1);", "downHeap(1;", "not close|never closed"],
  ["MinHeap.java", "java", "backingArray[1] = backingArray[size];", "backingArray[1] = backingArray[size);", "does not close"],
  ["list.cpp", "cpp", "++count;", "++count", "Missing ';'"],
  ["list.cpp", "cpp", "count = 0;", "count = 0", "Missing ';'"],
  ["list.cpp", "cpp", "delete head;", "delete head", "Missing ';'"],
  ["bfs.py", "python", "def bfs(self, start):", "def bfs(self, start)", "Missing ':'"],
  ["bfs.py", "python", "while queue:", "while queue", "Missing ':'"],
  ["bfs.py", "python", "        else:\n", "        else\n", "Missing ':'"],
  ["bfs.py", "python", "except (KeyError,\n                ValueError) as e:", "except (KeyError,\n                ValueError) as e", "Missing ':'"],
  ["bfs.py", "python", "queue = deque([start])", "queue = deque([start)", "does not close"],
  ["lib.rs", "rust", "Some(v) => Some(*v),", "Some(v) => Some(*v,", "does not close"],
  ["main.go", "go", "for i, w := range words {", "for i, w := range words", "Unmatched '}'"],
  ["app.js", "javascript", "return items.map((x) => ({ x, y: x * 2 }))", "return items.map((x) => ({ x, y: x * 2 })", "not close|never closed"],
  ["query.sql", "sql", "HAVING SUM(o.total) > (SELECT AVG(total) FROM orders)", "HAVING SUM(o.total) > (SELECT AVG(total) FROM orders", "never closed"],
];
for (const [file, lang, a, b, msg] of INJECT) {
  const text = replaceOnce(fx(file), a, b);
  const ds = lintCode(text, lang);
  const want = lineOf(text, text.indexOf(b) + (msg.startsWith("Missing") ? b.length - 1 : 0));
  const hit = ds.find((d) => new RegExp(msg).test(d.message));
  check(`${file}: ${JSON.stringify(b.slice(0, 40))} -> ${msg}`, hit && (msg.startsWith("Missing") ? lineOf(text, hit.from) === want : true), show(text, ds) || "no diagnostics");
}
check("plain text is never linted", lintCode("don't ( panic", "plain").length === 0);

// 3. Completions: keywords, context identifiers, document words and snippets, each with a kind.
const doc = "int total = 0;\nfor (int idx = 0; idx < 3; idx++) totalCount += idx;\nba";
const opts = localCompletions({ lang: "java", doc, word: "ba", identifiers: ["backingArray", { name: "size", kind: "field" }, { name: "downHeap", kind: "method", detail: "(int i)" }] });
const by = (label) => opts.find((o) => o.label === label);
check("context identifier (string)", by("backingArray")?.type === "variable", JSON.stringify(by("backingArray")));
check("context field", by("size")?.type === "property" && by("size").detail === "field");
check("context method", by("downHeap")?.type === "method" && by("downHeap").detail.includes("(int i)"));
check("keyword", by("boolean")?.type === "keyword");
check("document word", by("totalCount")?.type === "text" && by("totalCount").detail === "in file");
check("current word excluded", !by("ba"));
check("snippet", opts.some((o) => o.snippet && o.type === "snippet" && /for/.test(o.label)));
check("no duplicate labels", new Set(opts.map((o) => o.label + o.type)).size === opts.length);
const py = localCompletions({ lang: "python", doc: "", word: "", identifiers: [] });
check("python keywords", py.some((o) => o.label === "lambda" && o.type === "keyword"));
check("python snippets", py.some((o) => o.snippet && o.label.startsWith("def")));
const plain = localCompletions({ lang: "plain", doc: "alpha beta", word: "", identifiers: [] });
check("plain: document words only", plain.length === 2 && plain.every((o) => o.type === "text"));

console.log(`${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
