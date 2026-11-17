"""Build and validate an exact, per-task Graphify source context."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile


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
    names = list(editable) + graphify + evidence
    if len(set(names)) != len(names):
        raise ScopeError("同一文件不能重复出现在多个范围条目中；可编辑的源码无需重复列入 GRAPHIFY_INPUT")
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or not path.parts or any(part in ("", ".", "..") or part in FORBIDDEN for part in name.split("/")):
            raise ScopeError(f"路径必须是仓库内精确文件，且不能位于禁止目录：{name}")
        if "*" in name or "?" in name or "[" in name:
            raise ScopeError(f"不接受通配符路径：{name}")
        if any(part == '.env' or part.startswith('.env.') or part in {'id_rsa', 'id_ed25519'}
               or Path(part).suffix.lower() in {'.pem', '.key', '.p12', '.pfx'} for part in path.parts):
            raise ScopeError(f"不接受密钥路径：{name}")
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
    if action in ("CREATE", "ABSENT"):
        if current.exists():
            raise ScopeError(f"CREATE 路径必须尚不存在：{name}")
        if action == "CREATE" and not current.parent.is_dir():
            raise ScopeError(f"CREATE 路径的父目录必须存在：{name}")
    elif action == 'DIRECTORY':
        if current.exists() and not current.is_dir():
            raise ScopeError(f'产物目录不是普通目录：{name}')
    else:
        if not current.is_file():
            raise ScopeError(f"范围文件不存在或不是普通文件：{name}")
    return current


def _state(path):
    return sha(path.read_bytes())


def scope_sources(root, scope, phase="before"):
    if phase not in ("before", "after"):
        raise ScopeError("Graphify 阶段必须为 before 或 after")
    actions = dict(scope["editable"])
    actions.update({name: "READ" for name in scope["graphify_input"] + scope["read_only_evidence"]})
    sources = {}
    for name, action in actions.items():
        if phase == "after":
            action = "ABSENT" if action == "DELETE" else "READ"
        path = _safe(Path(root), name, action)
        sources[name] = _state(path) if path.is_file() else None
    return sources


def validate_scope(root, plan, phase="before"):
    scope = parse_scope(plan)
    scope_sources(root, scope, phase)
    return scope


def prepare(root, requirement_dir, task, plan, phase="before"):
    scope = validate_scope(root, plan, phase)
    root = Path(root).resolve(strict=True)
    requirement_dir = Path(requirement_dir).resolve(strict=True)
    sources = scope_sources(root, scope, phase)
    inputs = []
    for name in list(scope["editable"]) + scope["graphify_input"]:
        if sources[name] is None:
            continue
        if Path(name).suffix.lower() not in CODE_SUFFIXES:
            if name in scope["graphify_input"]:
                raise ScopeError(f"Graphify 输入扩展名不在支持清单内：{name}")
            continue
        inputs.append(name)
    if not inputs:
        raise ScopeError("没有可供 Graphify 分析的源码文件")
    parent = _safe(Path(requirement_dir), f'graphify-scope/{task}/{phase}', 'DIRECTORY')
    parent.mkdir(parents=True, exist_ok=True)
    base = Path(tempfile.mkdtemp(prefix="build-", dir=parent))
    try:
        source_dir, out_dir = base / "source", base / "output"
        source_dir.mkdir()
        for name in inputs:
            src = _safe(root, name, "READ")
            target = source_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            data = src.read_bytes()
            if sha(data) != sources[name]:
                raise ScopeError("镜像期间范围源码发生变化，请重新准备")
            target.write_bytes(data)
        executable = shutil.which("graphify")
        if not executable:
            raise ScopeError("找不到本机 Graphify CLI；安装或配置完成后再运行 graphify")
        result = subprocess.run([executable, "extract", str(source_dir), "--code-only", "--no-gitignore",
                                 "--no-cluster", "--out", str(out_dir)],
                                cwd=root, capture_output=True, text=True)
        graph = out_dir / "graphify-out" / "graph.json"
        if result.returncode or not graph.is_file():
            raise ScopeError("Graphify 建图失败或未生成 graph.json：" + (result.stderr.strip() or result.stdout.strip()))
        data = json.loads(graph.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get('nodes'), list) or not data['nodes']:
            raise ScopeError('Graphify 图格式无效或没有源码节点')
        if not isinstance(data.get('edges', data.get('links')), list):
            raise ScopeError('Graphify 图缺少关系列表')
        recognized = {node_source(node, graph) for node in data['nodes'] if isinstance(node, dict)}
        missing = set(inputs) - recognized
        if missing:
            raise ScopeError('Graphify 未识别以下输入源码，不能作为完整上下文：' + '、'.join(sorted(missing)))
        current = scope_sources(root, scope, phase)
        if current != sources:
            raise ScopeError("建图期间范围源码发生变化，请重新准备")
        record = {"version": 2, "phase": phase, "task": task, "scope": scope, "sources": sources,
                  "scope_sha256": sha(json.dumps(scope, sort_keys=True, ensure_ascii=False).encode()),
                  "graph": str(graph.relative_to(Path(requirement_dir))), "graph_sha256": _state(graph),
                  "graphify_exit_code": result.returncode, "inputs": inputs}
        manifest = base / "manifest.json"
        manifest.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        record["manifest"] = str(manifest.relative_to(Path(requirement_dir)))
        record["manifest_sha256"] = _state(manifest)
        return record
    except (OSError, ValueError, ScopeError) as error:
        shutil.rmtree(base)
        raise ScopeError(str(error)) from error


def artifact_path(requirement_dir, record, key):
    name = record.get(key, "")
    parts = name.split("/")
    if not name or Path(name).is_absolute() or any(p in ("", ".", "..") for p in parts):
        raise ScopeError("无效的 Graphify 产物路径")
    if record.get("version", 1) >= 2:
        expected = ["graphify-scope", record.get("task"), record.get("phase")]
        if parts[:3] != expected or len(parts) < 5:
            raise ScopeError("Graphify 产物不属于本任务阶段")
        if key != 'manifest' and parts[:4] != record.get('manifest', '').split('/')[:4]:
            raise ScopeError('Graphify 产物不属于同一生成批次')
    return _safe(Path(requirement_dir), name, "READ")


def validate_artifacts(requirement_dir, record):
    manifest = artifact_path(requirement_dir, record, "manifest")
    if not manifest.is_file() or _state(manifest) != record.get("manifest_sha256"):
        raise ScopeError("Graphify 范围清单缺失或已变化，请重新构建上下文")
    try:
        stored = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ScopeError("Graphify 范围清单无法读取，请重新构建上下文") from error
    for key in ("version", "phase", "task", "scope", "sources", "scope_sha256", "graph", "graph_sha256", "graphify_exit_code", "inputs"):
        if stored.get(key) != record.get(key):
            raise ScopeError("工作流记录与 Graphify 范围清单不一致，请重新构建上下文")
    graph = artifact_path(requirement_dir, record, "graph")
    if _state(graph) != record.get("graph_sha256"):
        raise ScopeError("Graphify 图已变化或缺失，请重建并重新确认")


def validate_current(root, requirement_dir, record, plan):
    validate_artifacts(requirement_dir, record)
    scope = parse_scope(plan)
    expected = sha(json.dumps(scope, sort_keys=True, ensure_ascii=False).encode())
    if expected != record.get("scope_sha256"):
        raise ScopeError("任务文件范围与最近一次 Graphify 清单不一致，请重建")
    current = scope_sources(root, scope, record.get("phase", "before"))
    if current != record.get("sources"):
        raise ScopeError("任务范围内的源码或证据已变化，请重建 Graphify 上下文并重新确认")


FLOW_HEADINGS = ("实际流程", "条件、异常与副作用", "保留行为", "规则、示例与验证", "源码核验", "未解析边界")


def node_source(node, graph_path):
    name = node.get('source_file') or node.get('file') or node.get('file_path') or node.get('path')
    if not isinstance(name, str):
        return None
    path = Path(name)
    if path.is_absolute():
        try:
            return path.relative_to(Path(graph_path).parents[2] / 'source').as_posix()
        except (ValueError, IndexError):
            return None
    return PurePosixPath(name).as_posix()


def graph_relations(path):
    """Compare stable symbol identities, not generated node or community IDs."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get('nodes'), list):
        raise ScopeError('Graphify 图缺少 nodes')
    edges = data.get('links', data.get('edges'))
    if not isinstance(edges, list):
        raise ScopeError('Graphify 图缺少 edges/links')
    nodes, limits, identities = {}, [], Counter()
    for node in data['nodes']:
        if not isinstance(node, dict):
            raise ScopeError('Graphify 节点格式无效')
        file = node_source(node, path)
        label = node.get('qualified_name') or node.get('label') or node.get('name')
        if file and label and 'id' in node:
            identity = (file, str(label), str(node.get('node_type', node.get('type', node.get('kind', '')))))
            nodes[str(node['id'])] = identity
            identities[identity] += 1
        else:
            limits.append('无法稳定映射节点：' + str(node.get('id', '?')))
    ambiguous = {identity for identity, count in identities.items() if count > 1}
    if ambiguous:
        limits.append('同路径同名节点存在歧义，相关关系未比较')
    result = Counter()
    for edge in edges:
        if not isinstance(edge, dict):
            raise ScopeError('Graphify 边格式无效')
        source, target = edge.get('source'), edge.get('target')
        source = source.get('id') if isinstance(source, dict) else source
        target = target.get('id') if isinstance(target, dict) else target
        left, right = nodes.get(str(source)), nodes.get(str(target))
        relation = edge.get('relation') or edge.get('type') or edge.get('kind')
        if not left or not right or left in ambiguous or right in ambiguous or not relation:
            limits.append('未比较缺少稳定端点或类型的关系')
            continue
        confidence = str(edge.get('confidence', 'EXTRACTED')).upper()
        result[(left, str(relation), right, confidence)] += 1
    return result, sorted(set(limits))


def write_audit_report(before, after, verification, output):
    after_edges, limits = graph_relations(after)
    lines = ['# 单任务交付关系与流程审计', '',
             '图是代码关系线索，不是完整控制流或业务语义证明。', '',
             f"验证日志：{verification['log']}", f"检查点：{verification['checkpoint']}",
             f"差异 SHA-256：{verification['patch_sha256']}", '',
             '## 拓扑与调用流程', '', f'后置图：{Path(after).relative_to(Path(output).parent)}',
             '[调用流程 HTML](callflow.html)', '', '## 关系变化', '']
    if before is None:
        lines.append('无前置图，不作关系差异断言。')
    else:
        before_edges, before_limits = graph_relations(before)
        limits += before_limits
        lines.append(f'前置图：{before}')
        for label, changes in [('新增', after_edges - before_edges), ('移除', before_edges - after_edges)]:
            lines.append(f'### {label}关系（{sum(changes.values())}）')
            for relation, count in sorted(changes.items()):
                lines.append(f'- {json.dumps(relation, ensure_ascii=False)} × {count}')
    lines += ['', '## 图解析限制', '', *(limits or ['未发现格式映射缺口；动态依赖仍需核验。'])]
    for heading in FLOW_HEADINGS:
        lines += ['', f'## {heading}', '', '待核验']
    output = Path(output)
    output.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return output


def export_callflow(root, requirement_dir, record):
    graph = artifact_path(requirement_dir, record, 'graph')
    output = artifact_path(requirement_dir, record, 'manifest').parent / 'callflow.html'
    executable = shutil.which('graphify')
    if not executable:
        raise ScopeError('找不到本机 Graphify CLI')
    result = subprocess.run([executable, 'export', 'callflow-html', '--graph', str(graph),
                             '--output', str(output)], cwd=root, capture_output=True, text=True)
    if result.returncode or not output.is_file():
        raise ScopeError('Graphify 调用流程导出失败：' + (result.stderr.strip() or result.stdout.strip()))
    return str(output.relative_to(requirement_dir))


def verification_binding(verification):
    if verification.get('result') != 'passed' or not verification.get('patch_sha256') or verification.get('scope_violations'):
        raise ScopeError('后置审计需要成功且未越界的验证与差异')
    return {key: verification[key] for key in ('checkpoint', 'patch_sha256', 'log')}


def validate_audit(root, requirement_dir, receipt, verification, check_sources=True):
    if not receipt or receipt.get('phase') != 'after':
        raise ScopeError('请先生成并封存 after 后置审计')
    if receipt.get('verification') != verification_binding(verification):
        raise ScopeError('后置审计不匹配本次验证，请重新生成并封存')
    validate_artifacts(requirement_dir, receipt)
    if check_sources and scope_sources(root, receipt['scope'], 'after') != receipt['sources']:
        raise ScopeError('后置审计的源码或只读证据已变化')
    for key in ('callflow', 'report'):
        path = artifact_path(requirement_dir, receipt, key)
        if _state(path) != receipt.get(key + '_sha256'):
            raise ScopeError('后置审计产物已变化或未封存：' + key)


def seal_audit(root, requirement_dir, record, verification):
    from workflow import sections
    if record.get('phase') != 'after' or record.get('verification') != verification_binding(verification):
        raise ScopeError('后置图不匹配当前验证，请重新生成')
    validate_artifacts(requirement_dir, record)
    if scope_sources(root, record['scope'], 'after') != record['sources']:
        raise ScopeError('后置图源码或只读证据已变化')
    report = artifact_path(requirement_dir, record, 'report')
    values = sections(report.read_text(encoding='utf-8'))
    if any(not values.get(h, '').strip() or '待核验' in values[h] for h in FLOW_HEADINGS):
        raise ScopeError('请先补齐审计报告中的源码核验和实际流程')
    receipt = {k: v for k, v in record.items() if k != 'kind'}
    for key in ('callflow', 'report'):
        path = artifact_path(requirement_dir, record, key)
        if key == 'callflow' and _state(path) != record.get('callflow_sha256'):
            raise ScopeError('调用流程 HTML 已变化，请重新生成')
        receipt[key + '_sha256'] = _state(path)
    validate_audit(root, requirement_dir, receipt, verification)
    return receipt


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
