// Local, LSP-style completions for the quiz editor. Pure: no CodeMirror imports, so node can test it.
// Sources: language keywords, identifiers from the item's `context`, words already in the document,
// and per-language snippets. Every entry carries a `type` (drives the kind icon) and a `detail` label.

const KW = {
  java: "abstract assert boolean break byte case catch char class continue default do double else enum extends final finally float for if implements import instanceof int interface long new null package private protected public return short static super switch synchronized this throw throws try var void volatile while true false record yield",
  cpp: "auto bool break case catch char class const constexpr continue default delete do double else enum explicit extern false float for friend if inline int long namespace new noexcept nullptr operator private protected public return short signed sizeof static static_cast struct switch template this throw true try typedef typename unsigned using virtual void volatile while include define std vector string",
  javascript: "async await break case catch class const continue default delete do else export extends false finally for function if import in instanceof let new null of return static super switch this throw true try typeof undefined var void while yield",
  ts: "interface type enum implements private public protected readonly declare namespace abstract as keyof unknown never any string number boolean",
  python: "and as assert async await break class continue def del elif else except False finally for from global if import in is lambda None nonlocal not or pass raise return True try while with yield self print len range enumerate isinstance",
  go: "break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var nil true false make len append error string int",
  rust: "as async await break const continue crate else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while Some None Ok Err Option Result Vec String",
  sql: "SELECT FROM WHERE JOIN LEFT RIGHT INNER OUTER ON GROUP BY ORDER HAVING LIMIT OFFSET INSERT INTO VALUES UPDATE SET DELETE CREATE TABLE PRIMARY KEY FOREIGN REFERENCES AND OR NOT NULL IS IN EXISTS BETWEEN LIKE AS DISTINCT COUNT SUM AVG MIN MAX CASE WHEN THEN ELSE END UNION ALL ASC DESC WITH",
};

// CodeMirror snippet syntax: ${name} is a field, ${} the final cursor position.
const SNIPPETS = {
  java: [
    ["for (int i…)", "for (int ${i} = 0; ${i} < ${n}; ${i}++) {\n\t${}\n}", "counted loop"],
    ["for-each", "for (${Type} ${item} : ${items}) {\n\t${}\n}", "enhanced for"],
    ["if", "if (${condition}) {\n\t${}\n}", "if block"],
    ["while", "while (${condition}) {\n\t${}\n}", "while loop"],
    ["try/catch", "try {\n\t${}\n} catch (${Exception} e) {\n\t\n}", "try block"],
    ["public method", "public ${void} ${name}(${}) {\n\t\n}", "method"],
    ["throw new", "throw new ${IllegalArgumentException}(\"${message}\");", "throw"],
    ["sysout", "System.out.println(${});", "print"],
  ],
  cpp: [
    ["for (int i…)", "for (int ${i} = 0; ${i} < ${n}; ++${i}) {\n\t${}\n}", "counted loop"],
    ["for (auto&…)", "for (auto& ${item} : ${items}) {\n\t${}\n}", "range for"],
    ["if", "if (${condition}) {\n\t${}\n}", "if block"],
    ["while", "while (${condition}) {\n\t${}\n}", "while loop"],
    ["class", "class ${Name} {\npublic:\n\t${}\n};", "class"],
    ["cout", "std::cout << ${} << std::endl;", "print"],
  ],
  javascript: [
    ["for (let i…)", "for (let ${i} = 0; ${i} < ${n}; ${i}++) {\n\t${}\n}", "counted loop"],
    ["for…of", "for (const ${item} of ${items}) {\n\t${}\n}", "for of"],
    ["if", "if (${condition}) {\n\t${}\n}", "if block"],
    ["function", "function ${name}(${params}) {\n\t${}\n}", "function"],
    ["arrow fn", "const ${name} = (${params}) => {\n\t${}\n};", "arrow function"],
    ["try/catch", "try {\n\t${}\n} catch (e) {\n\t\n}", "try block"],
  ],
  python: [
    ["def", "def ${name}(${params}):\n\t${pass}", "function"],
    ["for … in range", "for ${i} in range(${n}):\n\t${pass}", "counted loop"],
    ["for … in", "for ${item} in ${items}:\n\t${pass}", "for loop"],
    ["if", "if ${condition}:\n\t${pass}", "if block"],
    ["while", "while ${condition}:\n\t${pass}", "while loop"],
    ["class", "class ${Name}:\n\tdef __init__(self${}):\n\t\tpass", "class"],
    ["try/except", "try:\n\t${pass}\nexcept ${Exception} as e:\n\traise", "try block"],
  ],
  go: [
    ["for i…", "for ${i} := 0; ${i} < ${n}; ${i}++ {\n\t${}\n}", "counted loop"],
    ["for range", "for ${i}, ${v} := range ${items} {\n\t${}\n}", "range loop"],
    ["if err", "if err != nil {\n\treturn ${err}\n}", "error check"],
    ["func", "func ${name}(${params}) ${type} {\n\t${}\n}", "function"],
  ],
  rust: [
    ["fn", "fn ${name}(${params}) -> ${Type} {\n\t${}\n}", "function"],
    ["for in", "for ${item} in ${items} {\n\t${}\n}", "for loop"],
    ["match", "match ${value} {\n\t${pattern} => ${},\n\t_ => {}\n}", "match"],
    ["impl", "impl ${Type} {\n\t${}\n}", "impl block"],
  ],
  sql: [
    ["SELECT … FROM", "SELECT ${columns}\nFROM ${table}\nWHERE ${condition};", "query"],
    ["JOIN … ON", "JOIN ${table} ON ${a} = ${b}", "join"],
    ["GROUP BY … HAVING", "GROUP BY ${column}\nHAVING ${condition}", "grouping"],
  ],
};

// Context kinds (as written in the quiz JSON) -> CodeMirror completion types (icons).
const KIND = { field: "property", property: "property", method: "method", function: "function", type: "class", class: "class",
  interface: "interface", enum: "enum", variable: "variable", constant: "constant", keyword: "keyword" };

export const keywordsFor = (lang, dialect) => {
  const base = (KW[lang] || "").split(/\s+/).filter(Boolean);
  return lang === "javascript" && dialect && dialect.startsWith("ts") ? base.concat(KW.ts.split(" ")) : base;
};

/**
 * All local completion candidates for the word being typed.
 * @param {{lang: string, dialect?: string, doc: string, word: string, identifiers?: (string|{name, kind?, detail?})[]}} o
 * @returns {{label, type, detail, boost, snippet?}[]} — `snippet` is a CodeMirror snippet template.
 */
export function localCompletions({ lang, dialect, doc, word, identifiers = [] }) {
  const out = [], seen = new Set();
  const add = (o) => { const k = o.label + "\u0000" + o.type; if (!seen.has(k) && o.label !== word) { seen.add(k); out.push(o); } };
  for (const id of identifiers) {
    const o = typeof id === "string" ? { name: id } : id;
    if (!o || !o.name) continue;
    const kind = String(o.kind || "variable").toLowerCase();
    add({ label: o.name, type: KIND[kind] || "variable", detail: [o.kind ? kind : "", o.detail || ""].filter(Boolean).join(" ") || "context", boost: 3 });
  }
  const kws = keywordsFor(lang, dialect);
  for (const k of kws) add({ label: k, type: "keyword", detail: "keyword", boost: 1 });
  for (const [label, template, detail] of SNIPPETS[lang] || []) add({ label, type: "snippet", detail: `snippet · ${detail}`, snippet: template, boost: 0 });
  const known = new Set([...seen].map((k) => k.split("\u0000")[0]));
  for (const w of new Set(doc.match(/[A-Za-z_$][\w$]{2,}/g) || [])) {
    if (!known.has(w)) add({ label: w, type: "text", detail: "in file", boost: -1 });
  }
  return out;
}
