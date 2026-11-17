"""A local CLI double; Graphify is external and must not run in unit tests."""
from pathlib import Path
import sys


def install_graphify(directory):
    path = Path(directory) / "graphify"
    path.write_text(f"#!{sys.executable}\n" + '''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if args[:2] == ["export", "callflow-html"]:
    if os.environ.get("GRAPHIFY_TEST_EXPORT_FAIL"):
        sys.exit(1)
    graph = Path(args[args.index("--graph") + 1])
    assert graph.is_file()
    Path(args[args.index("--output") + 1]).write_text("<html>callflow</html>")
    sys.exit(0)
source = Path(args[1] if args[0] == "extract" else args[0])
out = Path(args[args.index("--out") + 1]) / "graphify-out"
if os.environ.get("GRAPHIFY_TEST_FAIL"):
    sys.exit(1)
if os.environ.get("GRAPHIFY_TEST_MISSING"):
    sys.exit(0)
out.mkdir(parents=True, exist_ok=True)
if os.environ.get("GRAPHIFY_TEST_MUTATE"):
    Path(os.environ["GRAPHIFY_TEST_MUTATE"]).write_text("changed while extracting")
nodes = [{"id": str(i), "label": p.stem, "file": p.relative_to(source).as_posix(), "type": "function"}
         for i, p in enumerate(sorted(source.rglob("*.py")))]
if os.environ.get("GRAPHIFY_TEST_EMPTY"):
    nodes = []
(out / "graph.json").write_text("not json" if os.environ.get("GRAPHIFY_TEST_INVALID") else
                               json.dumps({"nodes": nodes, "edges": [], "multigraph": True}))
''')
    path.chmod(0o755)
    return path


def plan(editable="- MODIFY a.py", inputs="- GRAPHIFY_INPUT b.py", evidence=""):
    return (f"## 修改范围\n\n{editable}\n\n## Graphify 与只读证据范围\n\n"
            f"{inputs}\n{evidence}\n")
