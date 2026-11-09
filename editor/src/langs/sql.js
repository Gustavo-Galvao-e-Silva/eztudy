import { sql, StandardSQL, PostgreSQL, MySQL, SQLite } from "@codemirror/lang-sql";
const DIALECTS = { postgresql: PostgreSQL, mysql: MySQL, sqlite: SQLite };
window.EZCM.langs.sql = (d = "") => sql({ dialect: DIALECTS[d] || StandardSQL, upperCaseKeywords: true });
