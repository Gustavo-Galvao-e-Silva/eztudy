import asyncio
import json

import pytest

pytest.importorskip("textual")

from eztudy import progress as prog  # noqa: E402
from eztudy import tui  # noqa: E402
from eztudy.workspace import find_workspace  # noqa: E402
from test_insights import T0, at, report  # noqa: E402


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "sources").mkdir()
    q = tmp_path / "study" / "quizzes"
    q.mkdir(parents=True)
    (q / "cells.json").write_text(json.dumps({"type": "quiz", "id": "cells", "title": "Cells", "items": [
        {"id": "q1", "type": "mcq", "question": "?", "options": ["a", "b"], "answer": 0, "citations": ["c"]}]}))
    ws = find_workspace(tmp_path)
    prog.store(ws, report("s1", T0, [("q1", "Organelles", "wrong")]))
    return ws


def test_dashboard_mounts_acts_and_refreshes(ws, monkeypatch):
    opened, copied = [], []

    async def scenario():
        app = tui.Dashboard(ws)
        monkeypatch.setattr(app, "open_page", opened.append)
        monkeypatch.setattr(app, "copy_to_clipboard", copied.append)
        monkeypatch.setattr(app, "run_review", lambda topic=None: opened.append(f"review:{topic}"))
        async with app.run_test(size=(120, 40)) as pilot:
            recs = app.query_one("#recs")
            assert recs.option_count == 1 and "Organelles" in str(recs.get_option_at_index(0).prompt)
            assert "Mastery" in app.export_screenshot() and "Still" in app.export_screenshot()
            recs.focus()
            await pilot.press("enter")  # the item is due (missed long ago): review that topic
            assert opened == ["review:Organelles"]
            app.query_one("#decks").focus()
            await pilot.press("enter")
            assert opened[-1] == "study/quizzes/cells.json"
            await pilot.press("d")
            assert app.screen.__class__.__name__ == "DueScreen"
            await pilot.press("escape")
            # A finished session shows up without a key press.
            prog.store(ws, report("s2", at(40), [("q1", "Organelles", "correct")]))
            app.poll()
            await pilot.pause()
            assert app.info["today"]["sessions"] == 2
            await pilot.press("q")
        assert not copied

    asyncio.run(scenario())


def test_launch_command_and_fallback(ws, capsys, monkeypatch):
    monkeypatch.setenv("EZTUDY_BIN", "/opt/eztudy/bin/eztudy")
    assert tui.launch_command(ws) == f"/opt/eztudy/bin/eztudy -C {ws.root} tui"
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setattr("sys.platform", "linux")
    assert tui.open_beside(ws).startswith("run this in another terminal")
