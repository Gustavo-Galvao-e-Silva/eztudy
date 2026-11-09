import { javascript } from "@codemirror/lang-javascript";
window.EZCM.langs.javascript = (d = "") => javascript({ typescript: d.startsWith("ts"), jsx: d.endsWith("x") });
