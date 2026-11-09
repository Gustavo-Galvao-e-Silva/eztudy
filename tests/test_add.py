import json
import os

from eztudy import origins
from eztudy.cli import main, sync_sources
from eztudy.workspace import find_workspace


def _project(tmp_path):
    hw = tmp_path / "homework02"
    (hw / "src").mkdir(parents=True)
    (hw / "src" / "BST.java").write_text("class BST {}\n")
    (hw / "src" / "BSTNode.java").write_text("class BSTNode {}\n")
    (hw / "spec.md").write_text("# HW2\n")
    for junk in [".idea/workspace.xml", "out/BST.class", "hw.iml", "submission.zip", "notes/scratch.tmp"]:
        (hw / junk).parent.mkdir(parents=True, exist_ok=True)
        (hw / junk).write_text("junk")
    return hw


def test_add_copies_with_excludes_and_tracks_origins(notebook, tmp_path, capsys):
    hw = _project(tmp_path / "elsewhere")
    nb = str(notebook)
    assert main(["-C", nb, "add", str(hw), "--as", "hw2-bst", "--exclude", "*.tmp", "--dry-run"]) == 0
    assert "would copy: hw2-bst/src/BST.java" in capsys.readouterr().out
    assert not (notebook / "sources" / "hw2-bst").exists()

    assert main(["-C", nb, "add", str(hw), "--as", "hw2-bst", "--exclude", "*.tmp"]) == 0
    copied = sorted(p.relative_to(notebook / "sources").as_posix() for p in (notebook / "sources" / "hw2-bst").rglob("*") if p.is_file())
    assert copied == ["hw2-bst/spec.md", "hw2-bst/src/BST.java", "hw2-bst/src/BSTNode.java"]
    ws = find_workspace(notebook)
    assert origins.load(ws)["files"]["hw2-bst/src/BST.java"]["origin"] == str((hw / "src" / "BST.java").resolve())

    # Editing the original shows up in status; re-running add refreshes the copy.
    sync_sources(ws, quiet=True)
    orig = hw / "src" / "BST.java"
    orig.write_text("class BST { int size; }\n")
    os.utime(orig, (1, 1))
    capsys.readouterr()
    main(["-C", nb, "status", "--json"])
    st = json.loads(capsys.readouterr().out)
    assert st["origins_changed"] == [{"path": "hw2-bst/src/BST.java", "origin": str(orig.resolve()), "state": "changed"}]
    assert main(["-C", nb, "add", str(hw), "--as", "hw2-bst"]) == 0
    assert "updated: hw2-bst/src/BST.java" in capsys.readouterr().out
    assert (notebook / "sources" / "hw2-bst" / "src" / "BST.java").read_text() == "class BST { int size; }\n"
    assert origins.changed(ws) == []

    # Moving the copy inside sources/ keeps the link; a different file in the way is never overwritten.
    (notebook / "sources" / "hw2-bst" / "spec.md").rename(notebook / "sources" / "hw2-bst" / "README.md")
    sync_sources(ws, quiet=True)
    assert "hw2-bst/README.md" in origins.load(ws)["files"] and "hw2-bst/spec.md" not in origins.load(ws)["files"]
    (notebook / "sources" / "hw2-bst" / "src" / "BSTNode.java").write_text("my own edits\n")
    capsys.readouterr()
    assert main(["-C", nb, "add", str(hw / "src" / "BSTNode.java"), "--as", "hw2-bst/src"]) == 1
    assert "skipped: hw2-bst/src/BSTNode.java" in capsys.readouterr().err
    assert (notebook / "sources" / "hw2-bst" / "src" / "BSTNode.java").read_text() == "my own edits\n"


def test_add_rejects_paths_inside_sources(notebook, capsys):
    assert main(["-C", str(notebook), "add", str(notebook / "sources" / "bio")]) == 2
    assert main(["-C", str(notebook), "add", str(notebook / "nope")]) == 2
