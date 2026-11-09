// Build the vendored editor for the eztudy player: `npm run build` (dev only; output is committed).
//   vendor/cm-core.js        CodeMirror + vim + eztudy editor, exposes window.EZCM
//   vendor/cm-lang-<id>.js   one per language; shares the core's modules via EZCM.modules
//   vendor/sizes.json        bytes (raw / gzip) per file + a hash of the sources that built them
import { build } from "esbuild";
import { createHash } from "node:crypto";
import { readFileSync, readdirSync, writeFileSync, mkdirSync, statSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, "..", "src", "eztudy", "templates", "player", "vendor");
mkdirSync(out, { recursive: true });

const SHARED = /^@(codemirror\/(state|view|language|commands|autocomplete|lint|search)|lezer\/(common|lr|highlight))$/;
// Language packs import the shared modules from the core instead of bundling a second copy
// (two copies of @codemirror/state break the editor).
const useCore = {
  name: "ezcm-shared",
  setup(b) {
    b.onResolve({ filter: SHARED }, (a) => ({ path: a.path, namespace: "ezcm" }));
    b.onLoad({ filter: /.*/, namespace: "ezcm" }, (a) => ({ contents: `module.exports = window.EZCM.modules[${JSON.stringify(a.path)}];`, loader: "js" }));
  },
};

const common = { bundle: true, minify: true, format: "iife", target: ["es2020"], legalComments: "none", logLevel: "warning" };
const LANGS = readdirSync(join(here, "src", "langs")).filter((f) => f.endsWith(".js")).map((f) => f.slice(0, -3)).sort();

await build({ ...common, entryPoints: [join(here, "src", "editor.js")], outfile: join(out, "cm-core.js") });
for (const id of LANGS) {
  await build({ ...common, entryPoints: [join(here, "src", "langs", `${id}.js`)], outfile: join(out, `cm-lang-${id}.js`), plugins: [useCore] });
}

export function sourceHash() {
  // Same algorithm as tests/test_code_items.py::_source_hash: sorted relative paths of build inputs.
  const files = ["build.mjs", "package-lock.json"];
  const walk = (d) => readdirSync(join(here, d)).forEach((f) => {
    const p = join(d, f);
    if (statSync(join(here, p)).isDirectory()) walk(p); else files.push(p.split("\\").join("/"));
  });
  walk("src");
  const h = createHash("sha256");
  for (const f of files.sort()) h.update(f + "\0").update(readFileSync(join(here, f))).update("\0");
  return h.digest("hex").slice(0, 16);
}

const sizes = { source_hash: sourceHash(), files: {} };
for (const f of readdirSync(out).filter((f) => f.endsWith(".js")).sort()) {
  const buf = readFileSync(join(out, f));
  sizes.files[f] = { raw: buf.length, gzip: gzipSync(buf, { level: 9 }).length };
}
writeFileSync(join(out, "sizes.json"), JSON.stringify(sizes, null, 2) + "\n");
for (const [f, s] of Object.entries(sizes.files)) console.log(`${f.padEnd(22)} ${(s.raw / 1024).toFixed(1).padStart(7)} KB  (${(s.gzip / 1024).toFixed(1)} KB gzip)`);
console.log(`source hash ${sizes.source_hash} -> ${relative(process.cwd(), out)}`);
