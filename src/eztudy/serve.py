"""`eztudy serve`: a tiny localhost server for the study player, so finishing a quiz needs no clicks.

The player pages are the same files `eztudy render` writes; served pages get one extra
`window.EZTUDY_SERVER` script, which makes the player POST its report here when the session ends and
poll for the agent's grades (see grading.py). Opened from disk (`file://`) the player works exactly as before.

Bound to 127.0.0.1 only; every request needs the per-server token (URL `?t=` for pages, `X-Eztudy-Token`
header for the API) and a localhost Host header, so other sites and local pages can't read or post.
"""

from __future__ import annotations

import html
import json
import os
import re
import secrets
import signal
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import grading
from . import progress as prog
from . import render as rendering
from .workspace import Workspace

MAX_BODY = 1_000_000
IDLE_SHUTDOWN_S = 2 * 3600  # safety net: exit after this long with no requests at all
LINGER_S = 120              # exit this long after the last open page went away (and no grading is in flight)
PAGE_ALIVE_S = 150          # a page that hasn't pinged for this long is gone (open pages ping every 30s;
                            # browsers may slow timers in background tabs to once a minute)
SWEEP_EVERY_S = 2
LOCAL_HOSTS = {"127.0.0.1", "localhost"}


def state_path(ws: Workspace) -> Path:
    return ws.state / "serve.json"


def running(ws: Workspace) -> dict | None:
    """The live server's {port, token, pid, url}, or None (stale state files are removed)."""
    try:
        st = json.loads(state_path(ws).read_text())
        with urllib.request.urlopen(f"http://127.0.0.1:{st['port']}/ping?t={st['token']}", timeout=2) as r:
            if json.loads(r.read()).get("root") == str(ws.root):
                return st
    except (OSError, ValueError, KeyError):
        pass
    state_path(ws).unlink(missing_ok=True)
    return None


def page_url(st: dict, rel: str = "") -> str:
    return f"{st['url']}/{urllib.parse.quote(rel)}?t={st['token']}" if rel else f"{st['url']}/?t={st['token']}"


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, ws: Workspace, port: int = 0, token: str | None = None):
        self.ws, self.token = ws, token or secrets.token_urlsafe(18)
        self.last_seen = self.last_page = time.time()
        self.pages: dict[str, float] = {}  # open player tabs -> last ping
        self.fallback = grading.fallback_command(ws)
        cfg = ws.config.get("grading") if isinstance(ws.config.get("grading"), dict) else {}
        self.idle_after = float(cfg.get("idle_shutdown_s", IDLE_SHUTDOWN_S))
        self.linger = float(cfg.get("linger_s", LINGER_S))
        self._stop = threading.Event()
        super().__init__(("127.0.0.1", port), Handler)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def state(self) -> dict:
        return {"port": self.server_address[1], "token": self.token, "pid": os.getpid(), "url": self.url, "root": str(self.ws.root)}

    def watchdog(self) -> None:
        while not self._stop.wait(SWEEP_EVERY_S):
            if self.fallback:
                grading.sweep(self.ws, lambda s: threading.Thread(
                    target=grading.run_fallback, args=(self.ws, s, self.fallback), daemon=True).start())
            if self.done():
                threading.Thread(target=self.shutdown, daemon=True).start()
                return

    def page_seen(self, page: str, gone: bool = False) -> None:
        now = time.time()
        self.last_page = now
        if gone:
            self.pages.pop(page, None)
        elif page:
            self.pages[page] = now

    def done(self) -> bool:
        """Nobody needs the server: no open page for `linger` seconds and nothing being graded (or idle for hours)."""
        now = time.time()
        if now - self.last_seen > self.idle_after:
            return True
        self.pages = {k: t for k, t in self.pages.items() if now - t < PAGE_ALIVE_S}
        if self.pages or now - self.last_page < self.linger:
            return False
        return not (grading.jobs(self.ws, "job") or grading.jobs(self.ws, "claimed"))

    def run(self) -> None:
        state_path(self.ws).parent.mkdir(parents=True, exist_ok=True)
        state_path(self.ws).write_text(json.dumps(self.state()) + "\n")
        threading.Thread(target=self.watchdog, daemon=True).start()
        try:
            self.serve_forever()
        finally:
            self._stop.set()
            st = json.loads(state_path(self.ws).read_text()) if state_path(self.ws).exists() else {}
            if st.get("pid") == os.getpid():
                state_path(self.ws).unlink(missing_ok=True)
            self.server_close()


def _current(page_path: Path) -> str:
    """The page rendered in memory from its JSON with the current player (keeping its skin), so a page written by
    an older eztudy still gets served mode and its fixes. Falls back to the file as written."""
    page = page_path.read_text()
    src = page_path.with_suffix(".json")
    if src.is_file():
        m = re.search(r'<html[^>]*data-skin="([\w-]+)"', page)
        try:
            return rendering.to_html(rendering.load(src), m.group(1) if m and m.group(1) in rendering.SKINS else None)
        except (rendering.StudyFormatError, ValueError, OSError):
            pass
    return page


def inject(page: str, st: dict) -> str:
    cfg = json.dumps({"url": "", "token": st["token"]}).replace("</", "<\\/")
    return page.replace("<script>", f"<script>window.EZTUDY_SERVER = {cfg};</script>\n<script>", 1)


class Handler(BaseHTTPRequestHandler):
    server: Server
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet: the agent's background log stays readable
        pass

    def _send(self, code: int, body: bytes | str | dict, ctype: str = "application/json") -> None:
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self, query: dict) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in LOCAL_HOSTS:
            return False
        given = self.headers.get("X-Eztudy-Token") or (query.get("t") or [""])[0]
        return secrets.compare_digest(given, self.server.token)

    def _route(self):
        u = urllib.parse.urlsplit(self.path)
        return urllib.parse.unquote(u.path), urllib.parse.parse_qs(u.query)

    def do_GET(self):
        path, query = self._route()
        if path == "/favicon.ico":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            return self.end_headers()
        if not self._authorized(query):
            return self._send(403, {"error": "forbidden"})
        self.server.last_seen = time.time()
        ws = self.server.ws
        if path in ("/ping", "/bye"):
            if query.get("page"):
                self.server.page_seen(query["page"][0][:64], gone=path == "/bye")
            return self._send(200, {"ok": True, "root": str(ws.root)})
        if path.startswith("/grades/"):
            return self._send(200, grading.status(ws, path.removeprefix("/grades/")))
        if path in ("/", ""):
            self.server.page_seen("")
            return self._send(200, self._index(), "text/html")
        target = (ws.root / path.lstrip("/")).resolve()
        study = ws.study.resolve()
        if target.suffix != ".html" or not target.is_relative_to(study) or not target.is_file():
            return self._send(404, {"error": "not found"})
        self.server.page_seen("")
        return self._send(200, inject(_current(target), self.server.state()), "text/html")

    def do_POST(self):
        path, query = self._route()
        if not self._authorized(query) or not self.headers.get("X-Eztudy-Token"):
            return self._send(403, {"error": "forbidden"})
        self.server.last_seen = time.time()
        if path != "/report":
            return self._send(404, {"error": "not found"})
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BODY:
            return self._send(413, {"error": "report too large"})
        try:
            rep = prog.parse(self.rfile.read(n).decode("utf-8"), "player")
        except (prog.ReportError, UnicodeDecodeError) as e:
            return self._send(400, {"error": str(e)})
        ws = self.server.ws
        key, _ = prog.store(ws, rep)
        try:
            stored = grading.load_report(ws, key)
        except grading.GradingError:
            stored = rep
        state = grading.status(ws, key)["status"]
        if grading.pending_items(stored):
            if state != "pending":
                grading.enqueue(ws, stored)
            state = "pending"
        elif state != "done":
            state = "none"
        return self._send(200, {"stored": True, "session": key, "grading": state,
                                "grader": "claude" if self.server.fallback else ("agent" if grading.waiter_alive(ws) else None)})

    def _index(self) -> str:
        ws, t = self.server.ws, urllib.parse.quote(self.server.token)
        pages = sorted(p.relative_to(ws.root).as_posix() for p in ws.study.rglob("*.html")) if ws.study.exists() else []
        rows = "".join(f'<li><a href="/{urllib.parse.quote(p)}?t={t}">{html.escape(p)}</a></li>' for p in pages) or "<li>No rendered quizzes or decks yet.</li>"
        return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
                "<title>eztudy</title><style>body{font:16px/1.5 system-ui,sans-serif;max-width:40rem;margin:2rem auto;padding:0 16px;"
                "background:#fff;color:#111}@media(prefers-color-scheme:dark){body{background:#111;color:#eee}a{color:#8ab4f8}}</style>"
                f"<h1>eztudy</h1><ul>{rows}</ul>")


def stop(ws: Workspace) -> bool:
    st = running(ws)
    if not st:
        return False
    try:
        os.kill(int(st["pid"]), signal.SIGTERM)
    except (OSError, ValueError):
        return False
    state_path(ws).unlink(missing_ok=True)
    return True
