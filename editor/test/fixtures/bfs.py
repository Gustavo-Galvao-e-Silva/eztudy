from collections import deque


class Graph:
    """Adjacency list graph. A colon-less docstring line: if x"""

    def __init__(self, edges):
        self.adj = {}
        for a, b in edges:
            self.adj.setdefault(a, []).append(b)

    def bfs(self, start):
        seen = {start}
        queue = deque([start])
        order = []
        while queue:
            node = queue.popleft()
            order.append(node)
            for nxt in self.adj.get(node, []):
                if nxt not in seen: seen.add(nxt)
                else:
                    continue
                queue.append(nxt)
        result = [n for n in order
                  if n is not None]
        label = "done" if result else "empty"
        if (len(result) > 0 and
                label == "done"):
            pass
        with open("x") as f, \
                open("y") as g:
            pass
        try:
            data = {"a": 1, "b": lambda x: x}
        except (KeyError,
                ValueError) as e:
            raise
        finally:
            pass
        if (n := len(result)) > 3:
            return result[1:n]
        return result  # trailing comment with if
