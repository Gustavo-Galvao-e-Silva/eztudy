// The quiz editor: CodeMirror 6 set up for the eztudy player. Bundled into vendor/cm-core.js, which
// exposes `window.EZCM`. Language packs (vendor/cm-lang-*.js) register themselves in EZCM.langs.
// All colours come from CSS (skins define --syn-* / --ed-* tokens); nothing here hard-codes a theme.

import * as state from "@codemirror/state";
import * as viewMod from "@codemirror/view";
import * as language from "@codemirror/language";
import * as commands from "@codemirror/commands";
import * as autocomplete from "@codemirror/autocomplete";
import * as lint from "@codemirror/lint";
import * as search from "@codemirror/search";
import * as lezerCommon from "@lezer/common";
import * as lezerLr from "@lezer/lr";
import * as lezerHighlight from "@lezer/highlight";
import { vim, getCM } from "@replit/codemirror-vim";
import { lintCode, LINTED } from "./lint.js";
import { localCompletions } from "./complete.js";

const { EditorState, Compartment, StateField, StateEffect, RangeSet } = state;
const { EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter, drawSelection, gutter, GutterMarker } = viewMod;
const { indentOnInput, bracketMatching, syntaxHighlighting, indentUnit } = language;
const { tags: t, tagHighlighter } = lezerHighlight;

// Syntax classes: skins colour .tok-* with --syn-* tokens.
const highlighter = tagHighlighter([
  { tag: [t.keyword, t.controlKeyword, t.definitionKeyword, t.moduleKeyword, t.operatorKeyword, t.modifier, t.self], class: "tok-keyword" },
  { tag: [t.string, t.special(t.string), t.character, t.regexp, t.escape], class: "tok-string" },
  { tag: [t.number, t.bool, t.null, t.atom, t.unit], class: "tok-number" },
  { tag: [t.comment, t.lineComment, t.blockComment, t.docComment], class: "tok-comment" },
  { tag: [t.typeName, t.className, t.namespace, t.standard(t.typeName), t.annotation, t.meta, t.macroName, t.processingInstruction], class: "tok-type" },
  { tag: [t.function(t.variableName), t.function(t.propertyName), t.function(t.definition(t.variableName))], class: "tok-function" },
  { tag: [t.variableName, t.propertyName, t.definition(t.variableName), t.labelName, t.attributeName], class: "tok-variable" },
  { tag: [t.operator, t.compareOperator, t.arithmeticOperator, t.logicOperator, t.bitwiseOperator, t.updateOperator, t.definitionOperator, t.derefOperator], class: "tok-operator" },
  { tag: [t.punctuation, t.separator, t.bracket, t.paren, t.brace, t.squareBracket, t.angleBracket], class: "tok-punct" },
  { tag: t.invalid, class: "tok-invalid" },
]);

/** Map a quiz `language` value to a pack id + dialect. Mirrors LANG_ALIASES in render.py. */
const ALIASES = {
  java: "java", python: "python", py: "python", python3: "python",
  c: "cpp", "c++": "cpp", cpp: "cpp", cc: "cpp", cxx: "cpp", h: "cpp", hpp: "cpp",
  javascript: "javascript", js: "javascript", jsx: "javascript:jsx", mjs: "javascript", node: "javascript",
  typescript: "javascript:ts", ts: "javascript:ts", tsx: "javascript:tsx",
  sql: "sql", postgres: "sql:postgresql", postgresql: "sql:postgresql", mysql: "sql:mysql", sqlite: "sql:sqlite",
  go: "go", golang: "go", rust: "rust", rs: "rust",
};
export function resolveLang(name) {
  const v = ALIASES[String(name || "").trim().toLowerCase()];
  if (!v) return { id: "plain", dialect: "" };
  const [id, dialect = ""] = v.split(":");
  return { id, dialect };
}

const langs = {};  // filled by language packs: id -> (dialect) => Extension

// ---- rubric hints: gutter markers set from outside --------------------------------------------
class HintMarker extends GutterMarker {
  constructor(ok, text) { super(); this.ok = ok; this.text = text; }
  eq(o) { return o.ok === this.ok && o.text === this.text; }
  toDOM() {
    const el = document.createElement("span");
    el.className = "cm-rubric-mark " + (this.ok ? "ok" : "bad");
    el.textContent = this.ok ? "✓" : "✗";
    el.title = (this.ok ? "Hint: looks like this line covers: " : "Hint: ") + this.text;
    return el;
  }
}
const setHints = StateEffect.define();
const hintField = StateField.define({
  create: () => RangeSet.empty,
  update(set, tr) {
    set = set.map(tr.changes);
    for (const e of tr.effects) if (e.is(setHints)) set = RangeSet.of(e.value, true);
    return set;
  },
});
const hintGutter = [hintField, gutter({ class: "cm-rubric-gutter", markers: (v) => v.state.field(hintField) })];

// ---- completions ----------------------------------------------------------------------------------
function completionSource(lang, dialect, identifiers) {
  return (ctx) => {
    const w = ctx.matchBefore(/[\w$]+/);
    if (!w && !ctx.explicit) return null;
    const word = w ? w.text : "";
    const opts = localCompletions({ lang, dialect, doc: ctx.state.doc.toString(), word, identifiers }).map((o) =>
      o.snippet ? autocomplete.snippetCompletion(o.snippet, { label: o.label, type: o.type, detail: o.detail, boost: o.boost })
        : { label: o.label, type: o.type, detail: o.detail, boost: o.boost });
    return { from: w ? w.from : ctx.pos, options: opts, validFor: /^[\w$]*$/ };
  };
}

/**
 * Mount an editor.
 * @param {HTMLElement} parent
 * @param {{doc?: string, language?: string, identifiers?: any[], readOnly?: boolean, vim?: boolean,
 *          lint?: boolean, label?: string, onChange?: (text: string) => void}} o
 */
export function createEditor(parent, o = {}) {
  const { id, dialect } = resolveLang(o.language);
  const ro = new Compartment(), vimC = new Compartment();
  let doc = String(o.doc ?? ""), cursor = -1;
  const mark = doc.indexOf("$0");
  if (mark >= 0) { cursor = mark; doc = doc.slice(0, mark) + doc.slice(mark + 2); }
  const readOnlyExt = (on) => [EditorState.readOnly.of(on), EditorView.editable.of(!on)];
  const ext = [
    vimC.of(o.vim && !o.readOnly ? vim({ status: true }) : []),  // must come before other keymaps
    lineNumbers(), highlightActiveLineGutter(), highlightActiveLine(), drawSelection(),
    commands.history(), indentOnInput(), bracketMatching(), autocomplete.closeBrackets(),
    syntaxHighlighting(highlighter), indentUnit.of(id === "go" ? "\t" : "    "),
    EditorState.tabSize.of(4), EditorView.lineWrapping,
    keymap.of([...autocomplete.closeBracketsKeymap, ...commands.defaultKeymap, ...commands.historyKeymap,
      ...lint.lintKeymap, commands.indentWithTab]),  // autocompletion() adds its own keymap at higher precedence
    ro.of(readOnlyExt(!!o.readOnly)),
    hintGutter,
    EditorView.editorAttributes.of({ class: `ez-editor lang-${id}` + (o.readOnly ? " is-readonly" : "") }),
    EditorView.contentAttributes.of({ "aria-label": o.label || "Code editor", spellcheck: "false", autocorrect: "off", autocapitalize: "off" }),
  ];
  if (langs[id]) ext.push(langs[id](dialect));
  if (!o.readOnly) {
    ext.push(autocomplete.autocompletion({ override: [completionSource(id, dialect, o.identifiers || [])], icons: true,
      tooltipClass: () => "ez-complete", optionClass: (c) => "ez-kind-" + (c.type || "text") }));
    if (o.lint !== false && LINTED.has(id)) {
      ext.push(lint.linter((v) => lintCode(v.state.doc.toString(), id).map((d) => ({ ...d, source: "eztudy lint (heuristic)" })), { delay: 400 }),
        lint.lintGutter());
    }
  }
  if (o.onChange) ext.push(EditorView.updateListener.of((u) => { if (u.docChanged) o.onChange(u.state.doc.toString()); }));
  const view = new EditorView({ parent, state: EditorState.create({ doc, extensions: ext, selection: cursor >= 0 ? { anchor: cursor } : undefined }) });
  return {
    view,
    language: id,
    getText: () => view.state.doc.toString(),
    setReadOnly(on) { view.dispatch({ effects: [ro.reconfigure(readOnlyExt(on)), ...(on ? [vimC.reconfigure([])] : [])] }); },
    setVim(on) { if (!view.state.readOnly) view.dispatch({ effects: vimC.reconfigure(on ? vim({ status: true }) : []) }); },
    /** hints: [{line: 1-based, ok: boolean, text}] — rubric hints (not grades) shown in their own gutter. */
    setHints(hints) {
      const ranges = hints.filter((h) => h.line >= 1 && h.line <= view.state.doc.lines)
        .map((h) => new HintMarker(h.ok, h.text).range(view.state.doc.line(h.line).from))
        .sort((a, b) => a.from - b.from);
      view.dispatch({ effects: setHints.of(ranges) });
    },
    focus: () => view.focus(),
    destroy: () => view.destroy(),
  };
}

/** Rubric `match` hints: first line matching each criterion's regex. Returns [{criterion, line|null}]. */
export function rubricHints(text, rubric) {
  const lines = text.split("\n");
  return (rubric || []).map((c) => {
    if (!c || !c.match) return { criterion: c, line: null, checked: false };
    let re;
    try { re = new RegExp(c.match, "m"); } catch { return { criterion: c, line: null, checked: false }; }
    const idx = lines.findIndex((l) => re.test(l));
    return { criterion: c, line: idx >= 0 ? idx + 1 : null, checked: true };
  });
}

// Shared modules for language packs (they are built with these imports mapped to EZCM.modules).
const modules = {
  "@codemirror/state": state, "@codemirror/view": viewMod, "@codemirror/language": language,
  "@codemirror/commands": commands, "@codemirror/autocomplete": autocomplete, "@codemirror/lint": lint,
  "@codemirror/search": search, "@lezer/common": lezerCommon, "@lezer/lr": lezerLr, "@lezer/highlight": lezerHighlight,
};

window.EZCM = { createEditor, resolveLang, rubricHints, langs, modules, getCM, version: "1" };
