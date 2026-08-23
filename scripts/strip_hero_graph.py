# -*- coding: utf-8 -*-
"""One-off: remove the hero canvas animation engine from index.html."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
idx = ROOT / "index.html"
lines = idx.read_text(encoding="utf-8").splitlines(keepends=True)

start = next((i for i, l in enumerate(lines)
              if "Living Knowledge Graph" in l), None)
if start is None:
    print("marker not found - nothing to do")
    raise SystemExit(0)

end = next(i for i in range(start, len(lines)) if lines[i].rstrip("\r\n") == "        };")
removed = end - start + 1
del lines[start:end + 1]

out = []
for l in lines:
    if "graph.init()" in l or "knowledge-graph" in l:
        continue
    out.append(l)

idx.write_text("".join(out), encoding="utf-8")
print("removed %d engine lines; file now %d lines" % (removed, len(out)))
