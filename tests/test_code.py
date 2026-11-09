import json

from eztudy import chunk, vectordb
from eztudy.cli import build_parser, cmd_index, cmd_search, main
from eztudy.workspace import find_workspace

JAVA = """package x;

import java.util.NoSuchElementException;

/**
 * A binary search tree.
 */
public class BST<T extends Comparable<? super T>> {
    private BSTNode<T> root;
    private int size;

    /**
     * Removes the data from the tree.
     */
    public T remove(T data) {
        if (data == null) {
            throw new IllegalArgumentException("null");
        }
        return removeRecurse(root, data);
    }

    @SuppressWarnings("unchecked")
    private T removeRecurse(BSTNode<T> node, T data) {
        for (int i = 0; i < size; i++) {
            visit(i);
        }
        int cmp = data.compareTo(node.getData());
        return null;
    }
}
"""

PY = '''import heapq


class MinHeap:
    """A min-heap."""

    def push(self, x):
        heapq.heappush(self.a, x)

    @staticmethod
    def build(xs):
        def helper(v):
            return v
        return sorted(map(helper, xs))


def heap_sort(xs):
    return MinHeap.build(xs)
'''


def test_java_symbols_and_chunks():
    syms = {s.heading: (s.start, s.line, s.end) for s in chunk.code_symbols(JAVA, ".java")}
    assert syms == {
        "BST": (5, 8, 30),
        "BST > remove": (12, 15, 20),            # Javadoc belongs to its method
        "BST > removeRecurse": (22, 23, 30),     # so does the annotation; for/if/calls are not symbols
    }
    chunks = chunk.chunk_code(JAVA, ".java", tokens=60, overlap=5)
    by_heading = {c.heading: (c.loc_kind, c.loc_start, c.loc_end) for c in chunks}
    assert by_heading["BST > remove"] == ("line", 12, 20)
    assert by_heading["BST > removeRecurse"] == ("line", 22, 30)
    assert all(c.text == "\n".join(JAVA.splitlines()[c.loc_start - 1:c.loc_end]) for c in chunks)


def test_python_symbols_skip_nested_and_merge_small():
    syms = [s.heading for s in chunk.code_symbols(PY, ".py")]
    assert syms == ["MinHeap", "MinHeap > push", "MinHeap > build", "heap_sort"]  # nested helper skipped
    chunks = chunk.chunk_code(PY, ".py")  # default size: everything small merges
    assert len(chunks) == 1 and chunks[0].loc_start == 1 and chunks[0].loc_end == 18
    assert chunks[0].heading == "MinHeap > push, build; heap_sort"
    merged = chunk.chunk_code(JAVA, ".java")
    assert merged[0].heading == "BST > remove" and merged[0].loc_start == 1


def test_index_search_and_show_code(notebook, fake_embedder, capsys):
    (notebook / "sources" / "hw2").mkdir()
    (notebook / "sources" / "hw2" / "BST.java").write_text(JAVA)
    ws = find_workspace(notebook)
    ws.config["chunk_tokens"], ws.config["chunk_overlap"] = 60, 5
    cmd_index(ws, build_parser().parse_args(["index"]), embedder=fake_embedder)
    capsys.readouterr()
    cmd_search(ws, build_parser().parse_args(["search", "removeRecurse compareTo", "--mode", "fts", "--json"]))
    hit = json.loads(capsys.readouterr().out)[0]
    assert hit["type"] == "code" and hit["location"] == "lines 22-30"
    assert hit["citation"] == "hw2/BST.java:22-30 (removeRecurse)"

    assert main(["-C", str(notebook), "show", "BST.java", "--symbol", "remove"]) == 0
    out = capsys.readouterr().out
    assert "[sources/hw2/BST.java:12-20] (BST > remove)" in out and "15  " in out and "removeRecurse(root" in out
    assert main(["-C", str(notebook), "show", "BST.java", "--lines", "3"]) == 0
    assert capsys.readouterr().out.splitlines()[1] == "3  import java.util.NoSuchElementException;"
    assert main(["-C", str(notebook), "show", "BST.java", "--symbol", "nope"]) == 1
    assert main(["-C", str(notebook), "show", "cells.pdf", "--lines", "1-2"]) == 1


def test_old_index_rechunks_only_code(notebook, fake_embedder, capsys):
    (notebook / "sources" / "BST.java").write_text(JAVA)
    ws = find_workspace(notebook)
    cmd_index(ws, build_parser().parse_args(["index"]), embedder=fake_embedder)
    db = vectordb.connect(ws.db_path)
    db.execute("DELETE FROM meta WHERE key='code_chunker'")
    db.commit()
    capsys.readouterr()
    cmd_index(ws, build_parser().parse_args(["index"]), embedder=fake_embedder)
    out = capsys.readouterr().out
    assert "+1 docs" in out and "BST.java" in out
    capsys.readouterr()
    cmd_index(ws, build_parser().parse_args(["index"]), embedder=fake_embedder)
    assert "+0 docs" in capsys.readouterr().out
