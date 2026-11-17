"""Build and validate an exact, per-task Graphify source context."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess


class ScopeError(Exception):
    pass


SECTIONS = ("修改范围", "Graphify 与只读证据范围")
CODE_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".m", ".mm",
                 ".swift", ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".kts",
                 ".go", ".rs", ".rb", ".php", ".cs", ".scala"}
FORBIDDEN = {".git", ".ai-workflow", "Pods", "DerivedData", "build", "vendor", "node_modules"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def parse_scope(plan):
    from workflow import sections, WorkflowError
    values = sections(plan)
    editable, graphify, evidence = {}, [], []
    for line in values.get("修改范围", "").splitlines():
        if not line.strip() or line.lstrip().startswith("<!--"):
            continue
        import re
        match = re.fullmatch(r"\s*-\s*(MODIFY|CREATE|DELETE)\s+`?([^`\s]+)`?(?:\s+—\s+.+)?\s*", line)
        if not match:
            raise ScopeError("修改范围只接受 `- MODIFY path — 意图`、`- CREATE path — 意图` 或 `- DELETE path — 意图`")
        action, name = match.groups()
        if name in editable:
            raise ScopeError(f"范围路径重复：{name}")
        editable[name] = action
    for heading, destination in (("Graphify 与只读证据范围", None),):
        for line in values.get(heading, "").splitlines():
            if not line.strip() or line.lstrip().startswith("<!--"):
                continue
            import re
            match = re.fullmatch(r"\s*-\s*(GRAPHIFY_INPUT|READ_ONLY_EVIDENCE)\s+`?([^`\s]+)`?(?:\s+—\s+.+)?\s*", line)
            if not match:
                raise ScopeError("证据范围只接受 `- GRAPHIFY_INPUT path — 理由` 或 `- READ_ONLY_EVIDENCE path — 理由`")
            kind, name = match.groups()
            (graphify if kind == "GRAPHIFY_INPUT" else evidence).append(name)
    if not editable:
        raise ScopeError("EDITABLE 范围不能为空")
    if not graphify:
        raise ScopeError("GRAPHIFY_INPUT 范围不能为空")
    names = list(editable) + graphify + evidence
    if len(set(names)) != len(names):
        raise ScopeError("同一文件不能重复出现在多个范围条目中；可编辑的源码无需重复列入 GRAPHIFY_INPUT")
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or not path.parts or any(part in ("", ".", "..") or part in FORBIDDEN for part in path.parts):
            raise ScopeError(f"路径必须是仓库内精确文件，且不能位于禁止目录：{name}")
        if "*" in name or "?" in name or "[" in name:
            raise ScopeError(f"不接受通配符路径：{name}")
    return {"editable": editable, "graphify_input": graphify, "read_only_evidence": evidence}


def _safe(root, name, action):
    root = root.resolve(strict=True)
    current = root
    parts = PurePosixPath(name).parts
    for part in parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            mode = None
        if mode is not None and os.path.islink(current):
            raise ScopeError(f"范围路径含符号链接：{name}")
    try:
        current.resolve(strict=False).relative_to(root)
    except ValueError as error:
        raise ScopeError(f"路径超出当前工作区：{name}") from error
    if action == "CREATE":
        if current.exists():
            raise ScopeError(f"CREATE 路径必须尚不存在：{name}")
        if not current.parent.is_dir():
            raise ScopeError(f"CREATE 路径的父目录必须存在：{name}")
    else:
        if not current.is_file():
            raise ScopeError(f"范围文件不存在或不是普通文件：{name}")
    return current


def _state(path):
    return sha(path.read_bytes())


def prepare(root, requirement_dir, task, plan):
    scope = parse_scope(plan)
    root = Path(root).resolve(strict=True)
    all_actions = dict(scope["editable"])
    all_actions.update({name: "READ" for name in scope["graphify_input"] + scope["read_only_evidence"]})
    sources, inputs = {}, []
    for name, action in all_actions.items():
        source = _safe(root, name, action)
        sources[name] = _state(source) if source.is_file() else None
        if name in scope["editable"] and action == "CREATE":
            continue
        if name in scope["editable"] and action == "DELETE":
            continue
        if name in scope["editable"] or name in scope["graphify_input"]:
            if source.suffix.lower() not in CODE_SUFFIXES:
                raise ScopeError(f"Graphify 输入扩展名不在支持清单内：{name}")
            inputs.append(name)
    if not inputs:
        raise ScopeError("没有可供 Graphify 分析的源码文件")
    base = Path(requirement_dir) / "graphify-scope" / task
    source_dir, out_dir = base / "source", base / "graphify-out"
    source_dir.mkdir(parents=True, exist_ok=True)
    for name in inputs:
        src = _safe(root, name, all_actions[name])
        target = source_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(src.read_bytes())
    executable = shutil.which("graphify")
    if not executable:
        raise ScopeError("找不到本机 Graphify CLI；安装或配置完成后再运行 graphify")
    out_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([executable, str(source_dir), "--code-only", "--no-gitignore", "--no-viz", "--out", str(out_dir)],
                            cwd=root, capture_output=True, text=True)
    graph = next((p for p in out_dir.rglob("graph.json") if p.is_file()), None)
    if result.returncode or graph is None:
        raise ScopeError("Graphify 建图失败或未生成 graph.json：" + (result.stderr.strip() or result.stdout.strip()))
    current = {name: (_state(_safe(root, name, all_actions[name])) if all_actions[name] != "CREATE" else None)
               for name in all_actions}
    if current != sources:
        raise ScopeError("建图期间范围源码发生变化，请重新准备")
    record = {"task": task, "scope": scope, "sources": sources,
              "scope_sha256": sha(json.dumps(scope, sort_keys=True, ensure_ascii=False).encode()),
              "graph": str(graph.relative_to(Path(requirement_dir))), "graph_sha256": _state(graph),
              "graphify_exit_code": result.returncode, "inputs": inputs}
    manifest = base / "manifest.json"
    manifest.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record["manifest"] = str(manifest.relative_to(Path(requirement_dir)))
    record["manifest_sha256"] = _state(manifest)
    return record


def validate_current(root, requirement_dir, record, plan):
    scope = parse_scope(plan)
    manifest = Path(requirement_dir) / record.get("manifest", "")
    if not manifest.is_file() or _state(manifest) != record.get("manifest_sha256"):
        raise ScopeError("Graphify 范围清单缺失或已变化，请重新构建上下文")
    try:
        stored = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ScopeError("Graphify 范围清单无法读取，请重新构建上下文") from error
    for key in ("task", "scope", "sources", "scope_sha256", "graph", "graph_sha256", "graphify_exit_code", "inputs"):
        if stored.get(key) != record.get(key):
            raise ScopeError("工作流记录与 Graphify 范围清单不一致，请重新构建上下文")
    expected = sha(json.dumps(scope, sort_keys=True, ensure_ascii=False).encode())
    if expected != record.get("scope_sha256"):
        raise ScopeError("任务文件范围与最近一次 Graphify 清单不一致，请重建")
    all_actions = dict(scope["editable"])
    all_actions.update({name: "READ" for name in scope["graphify_input"] + scope["read_only_evidence"]})
    current = {name: (_state(_safe(Path(root), name, action)) if action != "CREATE" else None)
               for name, action in all_actions.items()}
    if current != record.get("sources"):
        raise ScopeError("任务范围内的源码或证据已变化，请重建 Graphify 上下文并重新确认")
    graph = Path(requirement_dir) / record["graph"]
    if not graph.is_file() or _state(graph) != record.get("graph_sha256"):
        raise ScopeError("Graphify 图已变化或缺失，请重建并重新确认")


def changed_paths(before, after, allowed):
    violations = []
    for name in sorted(set(before) | set(after)):
        old, new = before.get(name), after.get(name)
        if old == new:
            continue
        action = "CREATE" if old is None else "DELETE" if new is None else "MODIFY"
        if allowed.get(name) != action and not (action == "MODIFY" and allowed.get(name) == "MODIFY"):
            violations.append(f"{action} {name}")
    return violations
