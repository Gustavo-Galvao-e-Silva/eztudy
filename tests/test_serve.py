import json
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from eztudy import grading, serve
from eztudy import progress as prog
from eztudy.cli import main
from eztudy.render import to_html
from eztudy.workspace import find_workspace

DECK = {"type": "quiz", "id": "cells", "title": "Cells", "items": [
    {"id": "q1", "type": "mcq", "question": "ATP?", "options": ["Nucleus", "Mitochondrion"], "answer": 1, "citations": ["a:0"]},
    {"id": "q2", "type": "short", "topic": "Energy", "question": "What is ATP for?", "answer": "Energy currency of the cell.",
     "explanation": "ATP stores energy.", "citations": [{"cid": "a:1", "source": "bio.pdf", "location": "page 2"}]},
    {"id": "q3", "type": "code", "language": "python", "question": "Sum a list", "answer": "def s(xs):\n    return sum(xs)",
     "rubric": [{"id": "ret", "text": "Returns the sum", "points": 2}], "citations": ["a:2"]},
]}


def report(session="s1", pending=True):
    res = "pending" if pending else "wrong"
    return {"eztudy_report": 1, "kind": "quiz", "deck": {"id": "cells", "title": "Cells"}, "session": session,
            "started_at": "2026-11-11T10:00:00Z", "finished_at": "2026-11-11T10:05:00Z", "score": {"right": 1, "total": 3},
            "items": [
                {"id": "q1", "type": "mcq", "topic": "Organelles", "question": "ATP?", "result": "correct", "graded": "auto",
                 "given": "Mitochondrion", "correct_answer": "Mitochondrion"},
                {"id": "q2", "type": "short", "topic": "Energy", "question": "What is ATP for?", "result": res,
                 "graded": "pending" if pending else "self", "given": "stores energy", "correct_answer": "Energy currency of the cell."},
                {"id": "q3", "type": "code", "topic": "Python", "question": "Sum a list", "result": res, "graded": "pending" if pending else "self",
                 "given": "def s(xs): return 0", "correct_answer": "def s(xs):\n    return sum(xs)", "language": "python",
                 "rubric": [{"id": "ret", "text": "Returns the sum", "points": 2, "ticked": True}]},
            ]}


VERDICTS = {"items": [
    {"id": "q2", "result": "correct", "feedback": "Right: ATP carries energy."},
    {"id": "q3", "result": "wrong", "points": 0, "feedback": "Always returns 0.", "rubric": [{"index": 0, "met": False, "note": "returns 0"}]},
]}


@pytest.fixture
def nb(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "sources").mkdir()
    q = tmp_path / "study" / "quizzes"
    q.mkdir(parents=True)
    (q / "cells.json").write_text(json.dumps(DECK))
    (q / "cells.html").write_text(to_html(DECK))
    monkeypatch.setattr(serve, "SWEEP_EVERY_S", 0.05)
    return tmp_path


@pytest.fixture
def server(nb):
    started = []

    def start(fallback=None):
        (nb / ".eztudy").mkdir(exist_ok=True)  # on disk, so CLI calls (`report wait`) see the same grader config
        (nb / ".eztudy" / "config.toml").write_text('[grading]\nfallback = "none"\n' if fallback is None
                                                    else f"[grading]\ncommand = {json.dumps(fallback)}\n")
        srv = serve.Server(find_workspace(nb))
        threading.Thread(target=srv.run, daemon=True).start()
        started.append(srv)
        return srv
    yield start
    for srv in started:
        srv.shutdown()


def call(srv, path, body=None, token=None, host=None):
    token = srv.token if token is None else token
    headers = {"X-Eztudy-Token": token} if body is not None else {}
    if host:
        headers["Host"] = host
    sep = "&" if "?" in path else "?"
    req = urllib.request.Request(srv.url + path + (f"{sep}t={token}" if body is None else ""),
                                 data=json.dumps(body).encode() if body is not None else None, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if r.headers.get_content_type() == "application/json" else raw)
    except urllib.error.HTTPError as e:
        return e.code, None


def until(fn, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if (v := fn()):
            return v
        time.sleep(0.05)
    raise AssertionError("timed out")


def test_serves_pages_with_server_flag_and_guards_access(server, nb):
    srv = server()
    code, page = call(srv, "/study/quizzes/cells.html")
    assert code == 200 and "window.EZTUDY_SERVER = {" in page and srv.token in page
    assert "window.EZTUDY_SERVER = {" not in (nb / "study" / "quizzes" / "cells.html").read_text()  # disk copy untouched
    assert call(srv, "/study/quizzes/cells.html", token="nope")[0] == 403
    assert call(srv, "/study/quizzes/cells.json")[0] == 404
    assert call(srv, "/study/../sources/x.html")[0] == 404
    assert call(srv, "/ping", host="evil.example")[0] == 403  # DNS-rebinding guard
    # a page rendered by an older player (no served mode) is re-rendered from its JSON, keeping the skin
    (nb / "study" / "quizzes" / "cells.html").write_text('<html data-skin="terminal"><script>old player</script></html>')
    code, page = call(srv, "/study/quizzes/cells.html")
    assert "old player" not in page and 'data-skin="terminal"' in page and "window.EZTUDY_SERVER = {" in page
    code, index = call(srv, "/")
    assert code == 200 and "study/quizzes/cells.html" in index
    # POST needs the header token, not just the query string
    req = urllib.request.Request(f"{srv.url}/report?t={srv.token}", data=b"{}", headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 403


def test_report_is_imported_and_agent_grades_it(server, nb, capsys):
    srv = server()
    code, res = call(srv, "/report", report())
    assert code == 200 and res["grading"] == "pending"
    ws = find_workspace(nb)
    stored = grading.load_report(ws, "s1")
    assert stored["deck"]["path"] == "study/quizzes/cells.json"
    assert call(srv, "/grades/s1")[1]["status"] == "pending"
    # pending items carry no mastery signal yet
    assert {t["topic"] for t in prog.summarize(prog.load_all(ws))["topics"]} == {"Organelles"}

    assert main(["-C", str(nb), "report", "wait", "--timeout", "5"]) == 0
    out = capsys.readouterr().out
    pk = json.loads(out[out.index("\n{") + 1:])
    assert [it["id"] for it in pk["items"]] == ["q2", "q3"]
    assert pk["items"][0]["explanation"] == "ATP stores energy." and pk["items"][0]["citations"]
    assert pk["items"][1]["rubric"][0]["student_ticked"] is True
    assert "eztudy report grade s1 -" in out

    bad = nb / "bad.json"
    bad.write_text(json.dumps({"items": [{"id": "q2", "result": "maybe", "feedback": ""}]}))
    assert main(["-C", str(nb), "report", "grade", "s1", str(bad)]) == 1
    assert "no verdict for: q3" in capsys.readouterr().err

    good = nb / "v.json"
    good.write_text(json.dumps(VERDICTS))
    assert main(["-C", str(nb), "report", "grade", "s1", str(good)]) == 0
    g = call(srv, "/grades/s1")[1]
    assert g["status"] == "done" and g["grader"] == "agent" and g["score"] == {"right": 2, "total": 3}
    assert g["items"][1]["rubric"] == [{"index": 0, "met": False, "note": "returns 0"}]
    stored = grading.load_report(ws, "s1")
    q3 = stored["items"][2]
    assert q3["result"] == "wrong" and q3["graded"] == "agent" and q3["rubric"][0]["met"] is False
    assert {t["topic"] for t in prog.summarize(prog.load_all(ws))["topics"]} == {"Organelles", "Energy", "Python"}
    # the player re-posting its (now graded) report must not re-queue grading
    assert call(srv, "/report", report())[1]["grading"] == "done"


def test_self_graded_resend_replaces_pending_report(server, nb):
    srv = server()
    call(srv, "/report", report())
    code, res = call(srv, "/report", report(pending=False))
    assert res["grading"] == "none"
    assert grading.load_report(find_workspace(nb), "s1")["items"][1]["result"] == "wrong"


@pytest.fixture
def fake_claude(tmp_path):
    def make(output):
        script = tmp_path / "fake_claude.py"
        script.write_text("import sys, json\nprompt = sys.stdin.read()\nassert 'Grading packet' in prompt\n"
                          f"print(json.dumps({output!r}))\n")
        return [sys.executable, str(script)]
    return make


def test_fallback_grades_when_no_agent_waits(server, nb, fake_claude):
    wrapper = {"type": "result", "is_error": False, "result": "", "structured_output": VERDICTS}
    srv = server(fake_claude(wrapper))
    call(srv, "/report", report())
    g = until(lambda: (r := call(srv, "/grades/s1")[1])["status"] == "done" and r)
    assert g["grader"] == "claude"
    assert grading.load_report(find_workspace(nb), "s1")["items"][1]["graded"] == "claude"


def test_fallback_accepts_fenced_text_result(server, fake_claude):
    srv = server(fake_claude({"type": "result", "result": "```json\n" + json.dumps(VERDICTS) + "\n```"}))
    call(srv, "/report", report())
    assert until(lambda: call(srv, "/grades/s1")[1]["status"] == "done")


def test_fallback_failure_is_reported(server, fake_claude):
    srv = server(fake_claude({"type": "result", "result": "I can't grade this."}))
    call(srv, "/report", report())
    g = until(lambda: (r := call(srv, "/grades/s1")[1])["status"] == "failed" and r)
    assert "automatic grading failed" in g["error"]


def test_wait_reports_headless_result_for_the_learner_profile(server, nb, fake_claude, capsys):
    srv = server(fake_claude({"structured_output": VERDICTS}))
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("rc", main(["-C", str(nb), "report", "wait", "--timeout", "10"])))
    t.start()
    time.sleep(0.3)
    call(srv, "/report", report())
    t.join(15)
    text = capsys.readouterr().out
    assert out["rc"] == 0 and "graded by claude: q2 correct, q3 wrong" in text and "learner.md" in text


def test_headless_failure_falls_back_to_listening_agent(server, nb, fake_claude, capsys):
    srv = server(fake_claude({"result": "nope"}))
    ws = find_workspace(nb)
    grading.heartbeat(ws)  # an agent is listening
    call(srv, "/report", report())
    job = until(lambda: (p := grading.grading_dir(ws) / "s1.job.json").exists() and grading.agent_only(p))
    assert job and call(srv, "/grades/s1")[1]["status"] == "pending"
    assert main(["-C", str(nb), "report", "wait", "--timeout", "5"]) == 0
    assert "grade session s1" in capsys.readouterr().out


def test_cheap_model_by_default(nb, monkeypatch):
    monkeypatch.setattr(grading.shutil, "which", lambda _: "/usr/bin/claude")
    ws = find_workspace(nb)
    cmd = grading.fallback_command(ws)
    assert cmd[cmd.index("--model") + 1] == "haiku" and cmd[cmd.index("--tools") + 1] == ""
    ws.config["grading"] = {"model": "sonnet"}
    assert "sonnet" in grading.fallback_command(ws)
    pk = grading.packet(ws, {**report(), "deck": {"id": "cells", "path": "study/quizzes/cells.json"}})
    prompt = grading.prompt_for(pk)
    assert "Energy currency" in prompt and "bio.pdf" not in prompt  # key included, citations dropped


def test_status_and_serve_cli(nb, capsys):
    assert main(["-C", str(nb), "serve", "--stop"]) == 0
    assert "no server running" in capsys.readouterr().out
    assert main(["-C", str(nb), "serve", "--open", "study/quizzes/missing.html", "--no-browser"]) == 1
    ws = find_workspace(nb)
    prog.store(ws, report())
    grading.enqueue(ws, grading.load_report(ws, "s1"))
    assert main(["-C", str(nb), "status"]) == 0
    assert "grading:  1 waiting, 0 failed" in capsys.readouterr().out


def test_server_exits_once_the_last_page_closes(server, nb, monkeypatch):
    srv = server()
    srv.linger = 0.3
    assert call(srv, "/ping?page=tab1")[0] == 200
    time.sleep(0.6)
    assert srv.pages and not srv.done()  # an open tab keeps it alive
    call(srv, "/bye?page=tab1")
    until(lambda: serve.running(find_workspace(nb)) is None)
    assert not (nb / ".eztudy" / "serve.json").exists()


def test_server_stays_while_grading_is_in_flight(server, nb):
    srv = server()
    srv.linger = 0
    ws = find_workspace(nb)
    prog.store(ws, report())
    grading.enqueue(ws, grading.load_report(ws, "s1"))
    srv.last_page = 0
    assert not srv.done()
    (grading.grading_dir(ws) / "s1.job.json").unlink()
    assert srv.done()
