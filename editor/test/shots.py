"""Screenshot the code editor in one or more skins (light + dark) with headless Chrome.

    uv run python editor/test/shots.py --skin terminal [--out DIR]

Writes <skin>-<mode>-edit.png (Vim on, lint squiggle, completion popup open) and
<skin>-<mode>-review.png (submitted: model solution, rubric ticks and hints, verdict).
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from eztudy.render import SKINS, to_html

HERE = Path(__file__).parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

EDIT = """
const ed = liveEditors[0], v = ed.view, ac = EZCM.modules["@codemirror/autocomplete"];
v.dispatch({changes: {from: 0, to: v.state.doc.length, insert:
  "public T remove() {\\n    if (size == 0) {\\n        throw new NoSuchElementException(\\"empty\\");\\n    }\\n    T min = backingArray[1]\\n    // move the last leaf up\\n    backingArray[1] = backingArray[size];\\n    downHeap(1);\\n    return min;\\n}"}});
const end = v.state.doc.line(8).from + 4;
v.dispatch({changes: {from: end, insert: "ba"}, selection: {anchor: end + 2}});
v.focus(); ac.startCompletion(v);
"""
REVIEW = """
const click = t => [...document.querySelectorAll("button")].find(b => b.textContent.trim().startsWith(t)).click();
const v = liveEditors[0].view;
v.dispatch({changes: {from: 0, to: v.state.doc.length, insert:
  "public T remove() {\\n    if (size == 0) {\\n        throw new NoSuchElementException(\\"empty\\");\\n    }\\n    T min = backingArray[1];\\n    backingArray[1] = backingArray[size];\\n    backingArray[size--] = null;\\n    return min;\\n}"}});
click("Submit");
document.querySelectorAll(".tick")[0].click();
document.querySelectorAll(".tick")[1].click();
click("I missed it");
"""


def page(skin: str, mode: str, script: str, vim: bool) -> str:
    data = json.loads((HERE / "fixtures" / "quiz.json").read_text())
    head = ('<style>*,*::before,*::after{animation:none!important;transition:none!important}</style>'
            f'<script>localStorage.setItem("eztudy:pref:theme","{mode}");'
            f'localStorage.setItem("eztudy:pref:skin","{skin}");'
            f'localStorage.setItem("eztudy:pref:vim","{"on" if vim else "off"}");</script>')
    run = f"<script>setTimeout(() => {{ try {{ {script} }} catch (e) {{ document.title = 'ERR ' + e; console.error(e); }} }}, 300);</script>"
    return to_html(data, skin).replace("<head>", "<head>" + head, 1).replace("</body>", run + "</body>")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skin", action="append", choices=SKINS, help="repeatable; default: all")
    ap.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "eztudy-shots"))
    ap.add_argument("--width", type=int, default=900)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for skin in args.skin or SKINS:
        for mode in ("light", "dark"):
            for name, script, vim in (("edit", EDIT, True), ("review", REVIEW, False)):
                html = out / f"{skin}-{mode}-{name}.html"
                html.write_text(page(skin, mode, script, vim))
                png = html.with_suffix(".png")
                subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                                f"--window-size={args.width},1250", "--virtual-time-budget=4000", f"--screenshot={png}",
                                html.as_uri()], check=True, capture_output=True)
                print(png)
    return 0


if __name__ == "__main__":
    sys.exit(main())
