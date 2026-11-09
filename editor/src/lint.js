// Conservative, language-aware lint for the quiz editor. Pure: (text, lang) -> diagnostics.
// Rule of thumb: a false alarm is worse than a missed error, so anything ambiguous is skipped.
// Diagnostics: {from, to, severity: "error" | "warning", message}. Offsets are into `text`.

export const CODE = 1, STR = 2, COMMENT = 0;
const CLOSE = { "(": ")", "[": "]", "{": "}" };
const OPENER = { ")": "(", "]": "[", "}": "{" };
const C_LIKE = new Set(["java", "cpp", "javascript", "go", "rust"]);

/** Classify every character as CODE, STR (inside a string/char literal) or COMMENT. */
export function codeMask(text, lang) {
  const n = text.length, mask = new Uint8Array(n).fill(CODE);
  const fill = (a, b, v) => { for (let k = a; k < Math.min(b, n); k++) mask[k] = v; };
  const cLike = C_LIKE.has(lang);
  const lastCode = (k) => { for (k--; k >= 0; k--) if (mask[k] === CODE && !/\s/.test(text[k])) return k; return -1; };
  let i = 0;
  while (i < n) {
    const c = text[i], two = text.slice(i, i + 2), three = text.slice(i, i + 3);
    const eol = () => { const e = text.indexOf("\n", i); return e < 0 ? n : e; };
    const until = (s, from) => { const e = text.indexOf(s, from); return e < 0 ? n : e + s.length; };
    let end = -1, kind = STR;
    if ((cLike && two === "//") || (lang === "python" && c === "#") || (lang === "sql" && two === "--")) { end = eol(); kind = COMMENT; }
    else if ((cLike || lang === "sql") && two === "/*") { end = until("*/", i + 2); kind = COMMENT; }
    else if ((lang === "python" && (three === '"""' || three === "'''")) || (lang === "java" && three === '"""')) end = until(three, i + 3);
    else if (lang === "rust" && /^r#*"/.test(text.slice(i, i + 8)) && !/\w/.test(text[i - 1] || "")) {
      const hashes = text.slice(i + 1).match(/^#*/)[0];
      end = until('"' + hashes, i + 2 + hashes.length);
    } else if (c === "`" && lang === "go") end = until("`", i + 1);
    else if (c === "`" && lang === "javascript") end = template(i);
    else if (c === '"' || (c === "'" && lang !== "rust")) {
      if (c === "'" && lang === "cpp" && /[0-9a-fA-F]/.test(text[i - 1] || "") && /[0-9a-fA-F]/.test(text[i + 1] || "")) { i++; continue; }  // 1'000'000
      end = quoted(i, c);
    } else if (c === "'" && lang === "rust") {
      const m = text.slice(i, i + 16).match(/^'(\\(x[0-9a-fA-F]{2}|u\{[0-9a-fA-F]+\}|.)|[^\\'\n])'/);
      if (m) end = i + m[0].length;  // otherwise a lifetime like 'a, which is code
    } else if (c === "/" && lang === "javascript" && !"/*".includes(text[i + 1] || "")) {
      const p = lastCode(i), before = p < 0 ? "" : text.slice(Math.max(0, p - 6), p + 1);
      if (p < 0 || /[(,=:[!&|?{};+\-*%<>~^]$/.test(before) || /\b(return|typeof|case|in|of)$/.test(before)) end = regex(i);
    }
    if (end > i) { fill(i, end, kind); i = end; } else i++;
  }
  return mask;

  function quoted(s, q) {  // single-line string or char literal with backslash escapes ('' in SQL)
    let k = s + 1;
    for (; k < n; k++) {
      if (text[k] === "\\" && lang !== "sql") { k++; continue; }
      if (text[k] === q) { if (lang === "sql" && text[k + 1] === q) { k++; continue; } return k + 1; }
      if (text[k] === "\n" && lang !== "sql" && lang !== "rust") return k;
    }
    return n;
  }
  function template(s) {  // JS template literal; ${ … } inside it is code
    let k = s + 1;
    for (; k < n; k++) {
      if (text[k] === "\\") { k++; continue; }
      if (text[k] === "`") return k + 1;
      if (text[k] === "$" && text[k + 1] === "{") {
        let depth = 0, j = k + 1;
        for (; j < n; j++) { if (text[j] === "{") depth++; else if (text[j] === "}" && --depth === 0) break; }
        fill(s, k + 2, STR);  // the literal part so far; the expression stays CODE
        s = j; k = j;
      }
    }
    return n;
  }
  function regex(s) {
    let k = s + 1, cls = false;
    for (; k < n && text[k] !== "\n"; k++) {
      if (text[k] === "\\") { k++; continue; }
      if (text[k] === "[") cls = true;
      else if (text[k] === "]") cls = false;
      else if (text[k] === "/" && !cls) return k + 1;
    }
    return -1;  // no closing slash on the line: it was division after all
  }
}

const lineOf = (text, pos) => text.slice(0, pos).split("\n").length;

function checkBrackets(text, mask) {
  const stack = [];
  for (let i = 0; i < text.length; i++) {
    if (mask[i] !== CODE) continue;
    const c = text[i];
    if (CLOSE[c]) stack.push(i);
    else if (OPENER[c]) {
      const top = stack.pop();
      if (top === undefined) return [{ from: i, to: i + 1, severity: "error", message: `Unmatched '${c}': nothing is open here.` }];
      if (text[top] !== OPENER[c]) {
        return [{ from: i, to: i + 1, severity: "error", message: `'${c}' does not close '${text[top]}' from line ${lineOf(text, top)}.` }];
      }
    }
  }
  if (!stack.length) return [];
  const top = stack[stack.length - 1];
  return [{ from: top, to: top + 1, severity: "error", message: `'${text[top]}' is never closed (missing '${CLOSE[text[top]]}').` }];
}

/** Lines with code-only text: strings become "_" (still a value), comments become spaces. */
function codeLines(text, mask) {
  const out = [];
  let start = 0;
  for (const raw of text.split("\n")) {
    let code = "";
    for (let k = 0; k < raw.length; k++) {
      const m = mask[start + k];
      code += m === CODE ? raw[k] : m === STR ? "_" : " ";
    }
    out.push({ start, code: code.replace(/\s+$/, ""), len: raw.length });
    start += raw.length + 1;
  }
  return out;
}

// Statement starters that never take a ';' on their own line.
const C_HEADER = /^(}\s*)?(if|else|for|while|do|switch|try|catch|finally|case|default|synchronized|namespace|template|static\s*$|extern\s+_)\b/;
const C_DECL = /\b(class|interface|enum|record|struct|union)\b/;
// A line ending in one of these continues on the next line.
const CONTINUES = /([,([?!&|+\-*/%=<>.\\^~:]|\b(return|new|throw|else|extends|implements|throws))$/;
// A next line starting with one of these continues the current statement.
const NEXT_CONTINUES = /^([{.)\]?:+\-*/%&|^=<>]|->|extends\b|implements\b|throws\b|const\b|override\b|noexcept\b|final\b|requires\b|try\b)/;

function checkSemicolons(text, mask) {
  const lines = codeLines(text, mask), diags = [];
  const braces = [];      // kind of each open '{': "block" or "list" (enum constants, initializer lists)
  let depth = 0;          // ( and [ nesting
  let first = null;       // code of the line that began the current statement
  const nextCode = (k) => { for (let j = k + 1; j < lines.length; j++) { const t = lines[j].code.trim(); if (t) return t; } return ""; };
  for (let k = 0; k < lines.length; k++) {
    const { code, start } = lines[k], t = code.trim();
    if (!t) continue;
    const depthBefore = depth;
    if (first === null) first = t;
    for (let j = 0; j < code.length; j++) {
      if (mask[start + j] !== CODE) continue;
      const ch = code[j];
      if (ch === "(" || ch === "[") depth++;
      else if (ch === ")" || ch === "]") depth = Math.max(0, depth - 1);
      else if (ch === "{") {
        const before = (code.slice(0, j).trim() || (k > 0 ? lines[k - 1].code.trim() : ""));
        braces.push(/(=|\]|,|\(|\{|\breturn)$/.test(before) || /\benum\b/.test(before) ? "list" : "block");
      } else if (ch === "}") braces.pop();
    }
    const ended = /[;{}]$/.test(t);
    const inMultiline = start + lines[k].len < text.length && mask[start + lines[k].len] !== CODE;  // string/comment goes on
    const ok =
      ended || inMultiline || depth > 0 || depthBefore > 0 || CONTINUES.test(t) ||
      /^[#@]/.test(first) || /\\$/.test(t) ||
      C_HEADER.test(first) || C_DECL.test(first) ||
      /^}/.test(t) ||
      braces[braces.length - 1] === "list" ||
      NEXT_CONTINUES.test(nextCode(k)) ||
      /^(public|private|protected)\s*:$/.test(t);
    if (!ok) {
      const end = start + lines[k].code.length;
      diags.push({ from: end - 1, to: end, severity: "warning", message: "Missing ';' at the end of this statement?" });
    }
    if (inMultiline) continue;
    if (ended || !(CONTINUES.test(t) || depth > 0 || NEXT_CONTINUES.test(nextCode(k)))) first = null;
  }
  return diags;
}

const PY_BLOCK = /^(async\s+)?(def|class|if|elif|else|for|while|try|except|finally|with)\b/;

function checkPythonColons(text, mask) {
  const lines = codeLines(text, mask), diags = [];
  let depth = 0, logical = null;
  for (let k = 0; k < lines.length; k++) {
    const { code, start } = lines[k];
    const depthBefore = depth;
    for (let j = 0; j < code.length; j++) {
      if (mask[start + j] !== CODE) continue;
      if ("([{".includes(code[j])) depth++;
      else if (")]}".includes(code[j])) depth = Math.max(0, depth - 1);
    }
    if (!logical) {
      if (!code.trim() || depthBefore > 0) continue;
      logical = [];
    }
    logical.push(lines[k]);
    if (depth > 0 || /\\$/.test(code)) continue;  // the logical line goes on
    const head = logical[0].code.trim(), m = head.match(PY_BLOCK);
    if (m) {
      // Needs a ':' at bracket depth 0 after the keyword; one-liners like `if x: return` count.
      let d = 0, found = false;
      for (const ln of logical) for (let j = 0; j < ln.code.length; j++) {
        if (mask[ln.start + j] !== CODE) continue;
        const ch = ln.code[j];
        if ("([{".includes(ch)) d++;
        else if (")]}".includes(ch)) d--;
        else if (ch === ":" && d === 0 && ln.code[j + 1] !== "=") found = true;
      }
      if (!found) {
        const last = logical[logical.length - 1], end = last.start + last.code.length;
        diags.push({ from: end - 1, to: end, severity: "warning", message: `Missing ':' after this '${m[2]}' line?` });
      }
    }
    logical = null;
  }
  return diags;
}

export const LINTED = new Set(["java", "cpp", "javascript", "go", "rust", "python", "sql"]);

export function lintCode(text, lang) {
  if (!LINTED.has(lang)) return [];
  const mask = codeMask(text, lang);
  const brackets = checkBrackets(text, mask);
  // With broken brackets, statement-level guesses are unreliable: report the bracket problem only.
  if (brackets.length) return brackets;
  if (lang === "java" || lang === "cpp") return checkSemicolons(text, mask);
  if (lang === "python") return checkPythonColons(text, mask);
  return [];
}
