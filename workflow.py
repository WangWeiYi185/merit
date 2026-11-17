#!/usr/bin/env python3
"""Local Markdown workflow for a single Git worktree."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import tempfile

import task_audit
import task_graphify


STATE_DIR = ".ai-workflow"
PENDING, ACTIVE, BLOCKED, REVIEW, PASSED = "待执行", "执行中", "阻塞", "待审阅", "通过"
KINDS = {"decision": "需要人决定", "evidence": "Agent 待取证", "external": "缺外部条件"}
HEADINGS = ("现状与依据", "目标与示例", "实现设计", "最低交付", "最大范围", "保留行为与暂停条件", "验收方案")
GRAPHIFY_HEADINGS = ("修改范围", "Graphify 与只读证据范围", "Graphify 依赖证据", "流程变化与确定编码上下文")
RECORDS = "\n## 工作流记录\n"
MAP_LINK = "澄清与验收示例见 [Example Mapping](examples.md)。"
TASK_ID = r"T[0-9]{2,}"
EXAMPLE_ID = r"E[0-9]{2,}"
MAP_PATTERNS = {
    "规则": re.compile(r"- (R[0-9]{2,}):\s*(\S.*)"),
    "示例": re.compile(rf"- ({EXAMPLE_ID}) \[(R[0-9]{{2,}})\]:\s*(\S.*)"),
    "未决问题": re.compile(r"- \[([ xX])\] (Q[0-9]{2,}) \[(R[0-9]{2,}|\*)\]:\s*(\S.*)"),
}
ROW = re.compile(rf"\| \[({TASK_ID})\]\(tasks/\1\.md\) \| ([^|]+) \| ([^|]+) \| ({PENDING}|{ACTIVE}|{BLOCKED}|{REVIEW}|{PASSED}) \|")


class WorkflowError(Exception):
    pass


def git(root, *args):
    result = subprocess.run(["git", *args], cwd=root, capture_output=True)
    if result.returncode:
        raise WorkflowError(result.stderr.decode(errors="replace").strip() or "Git 命令失败")
    return result.stdout


def write(path, content):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        try:
            file.write(content)
            file.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def read(path):
    return path.read_text(encoding="utf-8")


@contextmanager
def lock(directory):
    directory.mkdir(exist_ok=True)
    ignore = directory / ".gitignore"
    with (directory / ".lock").open("a") as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise WorkflowError("有另一个工作流操作正在运行，请稍后重试") from error
        if not ignore.exists():
            write(ignore, "*\n")
        yield


def snapshot(root, manifest=None):
    """Identify HEAD and current tracked/unignored file contents without modifying Git."""
    head = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "HEAD"],
                          cwd=root, capture_output=True)
    if head.returncode not in (0, 1):
        raise WorkflowError(head.stderr.decode(errors="replace").strip() or "无法读取 Git HEAD")
    digest = hashlib.sha256(head.stdout if head.returncode == 0 else b"unborn")
    raw_paths = git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    for raw in sorted(set(raw_paths.split(b"\0")) - {b""}):
        relative = raw.decode(sys.getfilesystemencoding(), errors="surrogateescape")
        path = root / relative
        if path.relative_to(root).parts[0] == STATE_DIR:
            continue
        digest.update(raw + b"\0")
        state = file_state(path)
        digest.update(state)
        if manifest is not None and state != b"missing":
            manifest[relative] = state.hex()
    return digest.hexdigest()


def file_state(path):
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return b"missing"
    if stat.S_ISLNK(mode):
        return b"link\0" + bytes(path.readlink())
    if stat.S_ISREG(mode):
        kind = b"executable" if mode & stat.S_IXUSR else b"file"
        with path.open("rb") as stream:
            return kind + hashlib.file_digest(stream, "sha256").digest()
    if stat.S_ISDIR(mode):
        prefix = b"directory\0" + git(path, "rev-parse", "--show-prefix")
        return prefix + snapshot(path).encode() if (path / ".git").exists() else prefix
    return b""


class Requirement:
    def __init__(self, path):
        self.path = path
        self.index = path / "tasks.md"
        if not self.index.is_file():
            raise WorkflowError(f"需求不存在：{path.name}")
        self.lines = read(self.index).splitlines()
        self.tasks = {}
        for position, line in enumerate(self.lines):
            match = ROW.fullmatch(line)
            if match:
                task, title, after, state = match.groups()
                if task in self.tasks:
                    raise WorkflowError(f"清单包含重复任务：{task}")
                self.tasks[task] = (position, title.strip(), after.strip(), state)

    def add(self, task, title, after, examples, investigation, graphify_context=False, graphify_audit=False):
        mapping = self.example_mapping()
        if mapping and not (examples or investigation):
            raise WorkflowError("请用 --example 引用已整理的业务示例，或用 --investigation 创建调查任务")
        if not mapping and (examples or investigation):
            raise WorkflowError("示例引用需要 examples.md")
        reference = ", ".join(examples) if examples else "调查（仅限取证）"
        example_section = f"## 示例引用\n\n{reference}\n\n" if mapping else ""
        if task in self.tasks or self.task_path(task).exists():
            raise WorkflowError(f"任务已存在：{task}")
        if set(after) - self.tasks.keys():
            raise WorkflowError("前置任务必须已经在清单中")
        headings = [h for h in GRAPHIFY_HEADINGS if graphify_context or h != "Graphify 依赖证据"]
        extra = "".join(f"## {heading}\n\n\n" for heading in headings) if graphify_context or graphify_audit else ""
        write(self.task_path(task), f"# {task} {title}\n\n" + example_section +
              "".join(f"## {heading}\n\n\n" for heading in HEADINGS) + "## 适用规范\n\n\n" + extra + RECORDS)
        self.tasks[task] = (len(self.lines), title, ', '.join(after) or '—', PENDING)
        self.lines.append(f"| [{task}](tasks/{task}.md) | {title} | {', '.join(after) or '—'} | {PENDING} |")
        self.save()
        if graphify_context or graphify_audit:
            self.record(task, "context_policy", mode="graphify-task-scope", version=2,
                        before=graphify_context, after=True)

    def task_path(self, task):
        return self.path / "tasks" / f"{task}.md"

    def save(self):
        write(self.index, "\n".join(self.lines) + "\n")

    def state(self, task):
        if task not in self.tasks:
            raise WorkflowError(f"任务不在清单中：{task}")
        return self.tasks[task][3]

    def set_state(self, task, state):
        position, title, after, _ = self.tasks[task]
        self.lines[position] = f"| [{task}](tasks/{task}.md) | {title} | {after} | {state} |"
        self.tasks[task] = (position, title, after, state)
        self.save()

    def active(self):
        return next((task for task in self.tasks if self.state(task) in (ACTIVE, REVIEW)), None)

    @property
    def audit_directory(self):
        return self.path / "audit"

    def records(self, task):
        _, records = self.plan(task)
        return [json.loads(line[2:]) for line in records.splitlines() if line.startswith('- {"kind": ')]

    def plan(self, task):
        self.state(task)
        content = read(self.task_path(task))
        plan, sep, records = content.partition(RECORDS)
        if not sep:
            raise WorkflowError("单任务文件缺少「工作流记录」标题")
        return plan, records

    def record(self, task_id, kind, **fields):
        plan, records = self.plan(task_id)
        payload = json.dumps({"kind": kind, **fields}, ensure_ascii=False)
        write(self.task_path(task_id), plan + RECORDS + records.rstrip() + "\n- " + payload + "\n")

    def latest(self, task, kind):
        for record in reversed(self.records(task)):
            if record["kind"] == kind:
                return record
        return {}

    def graphify_enabled(self, task):
        return self.latest(task, "context_policy").get("mode") == "graphify-task-scope"

    def graphify_policy(self, task):
        policy = self.latest(task, "context_policy")
        if policy.get("mode") != "graphify-task-scope":
            return {"version": 0, "before": False, "after": False}
        if policy.get("version", 1) == 1:
            return {"version": 1, "before": True, "after": False}
        return policy

    def graphify_record(self, task, phase="before"):
        for record in reversed(self.records(task)):
            if record["kind"] == "graphify_context" and record.get("phase", "before") == phase:
                return record
        return {}

    def confirmed_scope(self, task):
        return self.latest(task, "confirmation").get("scope") or self.graphify_record(task).get("scope", {})

    def confirm(self, task, statement, root):
        state = self.state(task)
        if state in (ACTIVE, REVIEW):
            raise WorkflowError("执行中或待审阅任务请先暂停，再重新确认")
        plan, _ = self.plan(task)
        values = sections(plan)
        missing = [heading for heading in HEADINGS if not values.get(heading, "").strip()]
        policy = self.graphify_policy(task)
        if self.graphify_enabled(task):
            required = [h for h in GRAPHIFY_HEADINGS if policy['before'] or h != 'Graphify 依赖证据']
            missing += [h for h in required if h != 'Graphify 与只读证据范围' and not values.get(h, '').strip()]
        if missing:
            raise WorkflowError("先补齐任务内容：" + "、".join(missing))
        context, scope, sources = None, None, None
        if self.graphify_enabled(task):
            scope = task_graphify.validate_scope(root, plan)
            sources = task_graphify.scope_sources(root, scope)
        if policy['before']:
            context = self.graphify_record(task)
            if not context:
                raise WorkflowError("请先运行 graphify 准备任务范围上下文")
            task_graphify.validate_current(root, self.path, context, plan)
            if not values.get("Graphify 依赖证据", "").strip() or not values.get("流程变化与确定编码上下文", "").strip():
                raise WorkflowError("请在任务文件中写明 Graphify 源码证据和业务流程变化")
        if state == BLOCKED and self.latest(task, "block").get("category") != "decision":
            raise WorkflowError("请先用 resolve 记录取证或外部条件的解决结果")
        digest = self.approval_digest(plan)
        if state == PASSED and self.latest(task, "confirmation").get("plan_sha256") == digest:
            raise WorkflowError("任务已通过；如需重跑验证，请用 verify --task")
        if state == PASSED:
            self.set_state(task, PENDING)
        self.record(task, "confirmation", plan_sha256=digest, statement=statement,
                    graphify_manifest_sha256=context.get("manifest_sha256") if context else None,
                    graphify_graph_sha256=context.get("graph_sha256") if context else None,
                    scope=scope, sources=sources)
        if state == BLOCKED:
            self.set_state(task, PENDING)

    def approved(self, task, root, check_sources=True):
        plan, _ = self.plan(task)
        if self.latest(task, "confirmation").get("plan_sha256") != self.approval_digest(plan):
            raise WorkflowError("当前任务内容需由负责人确认后才能继续")
        policy = self.graphify_policy(task)
        confirmation = self.latest(task, "confirmation")
        if self.graphify_enabled(task) and confirmation.get('scope'):
            if task_graphify.parse_scope(plan) != confirmation['scope']:
                raise WorkflowError('任务范围需重新确认')
            if check_sources and task_graphify.scope_sources(root, confirmation['scope']) != confirmation['sources']:
                raise WorkflowError('任务范围内源码或证据已变化，请重新确认')
        if policy['before']:
            context = self.graphify_record(task)
            if not context or confirmation.get("graphify_manifest_sha256") != context.get("manifest_sha256"):
                raise WorkflowError("Graphify 上下文未包含在当前确认中，请重新确认")
            if check_sources:
                task_graphify.validate_current(root, self.path, context, plan)
            else:
                task_graphify.validate_artifacts(self.path, context)


    def unchanged_evidence(self, task, root):
        if not self.graphify_enabled(task):
            return
        scope = self.confirmed_scope(task)
        sources = self.latest(task, 'confirmation').get('sources') or self.graphify_record(task).get('sources', {})
        try:
            current = task_graphify.scope_sources(root, {**scope, 'editable': {}})
        except task_graphify.ScopeError as error:
            raise WorkflowError(f'只读输入或证据已变化：{error}') from error
        if any(sources.get(name) != value for name, value in current.items()):
            raise WorkflowError('只读输入或证据已变化，请恢复原内容或修订范围并重新确认')

    def dependencies(self, task):
        after = self.tasks[task][2]
        dependencies = [] if after == "—" else after.split(", ")
        for dep in dependencies:
            if self.state(dep) != PASSED:
                raise WorkflowError(f"前置任务 {dep} 尚未通过")
            try:
                root = Path(git(None, 'rev-parse', '--show-toplevel').decode().strip())
                self.approved(dep, root, check_sources=False)
                if self.graphify_policy(dep)['after']:
                    verification = self.latest(dep, 'verification')
                    if self.latest(dep, 'review').get('patch') != verification.get('patch'):
                        raise WorkflowError('前置任务交付尚未接受')
                    task_graphify.validate_audit(root, self.path, self.latest(dep, 'graphify_audit'),
                                                verification, check_sources=False)
            except (WorkflowError, task_graphify.ScopeError) as error:
                raise WorkflowError(f"前置任务 {dep} 的确认失效，请重新确认和验证：{error}") from error
        return dependencies

    def example_mapping(self):
        path = self.path / "examples.md"
        if path.is_file():
            return path
        if MAP_LINK in self.lines:
            raise WorkflowError("需求缺少 examples.md，请恢复对应的澄清记录")
        return None

    def approval_digest(self, plan):
        mapping = self.example_mapping()
        if mapping is None:
            return fingerprint(plan)
        references = sections(plan).get("示例引用", "").strip()
        if references == "调查（仅限取证）":
            return fingerprint(plan)
        ids = [value.strip() for value in references.split(",")]
        if not all(re.fullmatch(EXAMPLE_ID, value) for value in ids):
            raise WorkflowError("任务需要可识别的示例引用，例如 E01, E02")
        facts = mapped_examples(read(mapping), ids)
        return fingerprint(plan + json.dumps(facts, ensure_ascii=False))


def sections(markdown):
    parts = re.split(r"(?m)^## (.+)\n", markdown)
    return dict(zip(parts[1::2], parts[2::2]))


def mapped_examples(markdown, ids):
    mapped = sections(markdown)
    entries = {}
    for heading, pattern in MAP_PATTERNS.items():
        for line in mapped.get(heading, "").splitlines():
            if not line.startswith("- "):
                continue
            match = pattern.fullmatch(line.strip())
            if not match:
                raise WorkflowError(f"examples.md 的「{heading}」条目格式无效：{line}")
            key = match[2] if heading == "未决问题" else match[1]
            if key in entries:
                raise WorkflowError(f"examples.md 中编号重复：{key}")
            entries[key] = (heading, match.groups())

    for key, (heading, values) in entries.items():
        rule = values[1] if heading == "示例" else values[2] if heading == "未决问题" else key
        if rule != "*" and rule not in entries:
            raise WorkflowError(f"{key} 引用未知规则：{rule}")

    selected = {}
    rules = set()
    for key in ids:
        if key not in entries:
            raise WorkflowError(f"examples.md 缺少示例：{key}")
        example = entries[key][1]
        rule = example[1]
        rules.add(rule)
        selected[key] = example
        selected[rule] = entries[rule][1]
    for key, (heading, values) in entries.items():
        if heading != "未决问题" or values[2] not in rules | {"*"}:
            continue
        if values[0] == " ":
            raise WorkflowError(f"相关未决问题 {key} 需要负责人确认后关闭")
        if "决定：" not in values[3] or not values[3].partition("决定：")[2].strip():
            raise WorkflowError(f"已关闭问题 {key} 需要在同一行记录决定：…")
        selected[key] = values
    return sorted(selected.items())


def fingerprint(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def init_requirement(path, goal):
    try:
        path.mkdir()
    except FileExistsError as error:
        raise WorkflowError(f"需求已存在：{path.name}") from error
    (path / "tasks").mkdir()
    (path / "audit").mkdir()
    write(path / "examples.md", f"# 需求澄清\n\n## 故事\n\n{goal}\n\n"
          "## 规则\n\n<!-- - R01: 已有或拟议的业务规则 -->\n\n"
          "## 示例\n\n<!-- - E01 [R01]: 给定条件、动作、预期结果与副作用 -->\n\n"
          "## 未决问题\n\n<!-- - [ ] Q01 [R01]: 会改变业务结果的问题 -->\n")
    write(path / "tasks.md", f"# {goal}\n\n## 需求来源与共享约束\n\n"
          f"{MAP_LINK}\n\n"
          "在这里引用当前适用的业务材料、规则及相关代码。\n\n"
          "| 任务 | 可观察结果 | 前置任务 | 状态 |\n| --- | --- | --- | --- |\n")


def verify(root, requirement, task, command):
    requirement.approved(task, root, check_sources=False)
    requirement.unchanged_evidence(task, root)
    requirement.dependencies(task)
    before = snapshot(root)
    with tempfile.NamedTemporaryFile(dir=requirement.path, prefix=f"{task}-", suffix=".log", delete=False) as log:
        log_path = Path(log.name)
        print(f"运行验证：{shlex.join(command)}\n日志：{log_path}", flush=True)
        try:
            code = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT).returncode
        except OSError as error:
            log.write(str(error).encode())
            code = 127
    manifest = {}
    after = snapshot(root, manifest)
    requirement.approved(task, root, check_sources=False)
    requirement.unchanged_evidence(task, root)
    requirement.dependencies(task)
    passed = code == 0 and before == after
    receipt = {}
    baseline = requirement.latest(task, "start").get("tree")
    audited_delivery = baseline and (requirement.state(task) in (ACTIVE, REVIEW)
                                    or requirement.graphify_policy(task)['after'])
    if audited_delivery and before == after:
        current = task_audit.capture_tree(root, requirement.audit_directory)
        if snapshot(root) != after:
            raise WorkflowError("生成审阅材料时工作区发生变化，请重新验证")
        patch, patch_digest, files = task_audit.capture_diff(root, requirement.audit_directory, baseline, current)
        original = json.loads(read(requirement.audit_directory / f"{task}-baseline.json"))
        raw_files = {name for name in original.keys() | manifest.keys() if original.get(name) != manifest.get(name)}
        receipt = {"patch": patch, "patch_sha256": patch_digest,
                   "files": sorted(raw_files | set(files)), "without_patch": sorted(raw_files - set(files))}
        if requirement.graphify_enabled(task):
            receipt["scope_violations"] = task_graphify.changed_paths(
                original, manifest, requirement.confirmed_scope(task)["editable"])
    requirement.record(task, "verification", result="passed" if passed else "failed", command=command,
                       exit_code=code, checkpoint=after, log=log_path.name,
                       source_changed=before != after, **receipt)
    if receipt.get("scope_violations"):
        requirement.record(task, "scope_violation", paths=receipt["scope_violations"])
        requirement.set_state(task, BLOCKED)
        raise WorkflowError("交付包含已确认范围之外的改动，任务已阻塞：" + "、".join(receipt["scope_violations"]))
    if not passed:
        if requirement.state(task) == PASSED:
            requirement.set_state(task, PENDING)
        elif requirement.state(task) == REVIEW:
            requirement.set_state(task, ACTIVE)
        raise WorkflowError("验证期间代码状态发生变化，未能形成检查点" if before != after
                            else f"验证失败（退出码 {code}），{task} 未通过")
    requirement.set_state(task, REVIEW if audited_delivery else PASSED)
    print(f"{task} 验证通过。" + ("待负责人审阅。" if audited_delivery else "") + f"检查点：{after}")


def review(root, requirement, task, decision, note):
    state = requirement.state(task)
    verification = requirement.latest(task, "verification")
    patch = verification.get("patch")
    prior = requirement.latest(task, "review")
    if not patch or (state not in (ACTIVE, REVIEW) and prior.get("patch") != patch):
        raise WorkflowError("请先完成本次验证并生成审阅材料")
    task_audit.review_patch(requirement.audit_directory, verification)
    if verification.get("checkpoint") != snapshot(root):
        raise WorkflowError("工作区与审阅材料不一致，请重新验证")
    requirement.approved(task, root, check_sources=False)
    requirement.dependencies(task)
    if decision == 'accept' and requirement.graphify_policy(task)['after']:
        task_graphify.validate_audit(root, requirement.path, requirement.latest(task, 'graphify_audit'), verification)
    new_state = PASSED if decision == "accept" else ACTIVE
    if prior.get("patch") == patch:
        if prior.get("decision") != decision:
            raise WorkflowError("本次交付已有审阅结论，请在重新验证后再审阅")
    else:
        if decision == "accept" and (state != REVIEW or verification["result"] != "passed"):
            raise WorkflowError("接受前必须通过本次验证")
        requirement.record(task, "review", decision=decision, note=note, patch=patch,
                           checkpoint=verification["checkpoint"])
    requirement.set_state(task, new_state)
    print("已接受" if decision == "accept" else "已记录返工，任务继续执行")


def graphify_status(root, requirement, task):
    policy = requirement.graphify_policy(task)
    if not requirement.graphify_enabled(task):
        return
    print(f"Graphify：{task} · before={policy['before']} · after={policy['after']}")
    for phase in ('before', 'after'):
        if not policy[phase]:
            continue
        context = requirement.graphify_record(task, phase)
        if not context:
            if phase == 'after' and requirement.state(task) != REVIEW:
                print('after：等待本任务验证成功后按需生成')
            else:
                print(f"{phase}：未生成；按需运行 flow graphify {requirement.path.name} {task} --phase {phase}")
            continue
        try:
            task_graphify.validate_artifacts(requirement.path, context)
            if phase == 'before' and requirement.state(task) == PENDING:
                task_graphify.validate_current(root, requirement.path, context, requirement.plan(task)[0])
            if phase == 'after':
                task_graphify.validate_audit(root, requirement.path, requirement.latest(task, 'graphify_audit'),
                                            requirement.latest(task, 'verification'))
            state = '有效' if phase == 'after' or requirement.state(task) == PENDING else '历史证据'
        except (task_graphify.ScopeError, OSError, ValueError) as error:
            state = str(error)
        print(f"{phase}：{state} · {requirement.path / context['graph']}")
        if context.get('report'):
            print(f"审计报告：{requirement.path / context['report']}")
            print(f"调用流程：{requirement.path / context['callflow']}")
            if not requirement.latest(task, 'graphify_audit'):
                print(f"下一步：核对报告后 flow graphify {requirement.path.name} {task} --phase after --seal")


def audit_report(root, requirement, task, show_diff):
    if show_diff:
        if not task:
            raise WorkflowError("--diff 需要任务编号")
        receipt = requirement.latest(task, "verification")
        if not receipt.get("patch"):
            raise WorkflowError("本次任务尚无审阅差异，请先运行 verify")
        sys.stdout.buffer.write(task_audit.review_patch(requirement.audit_directory, receipt))
        return
    print(f"需求 {requirement.path.name}" + (f" · {task} · {requirement.state(task)}" if task else ""))
    for event in task_audit.skills(requirement.audit_directory):
        if task and event.get("task") not in (None, task):
            continue
        details = " · ".join(value for value in (event.get("task"), event.get("purpose"), event.get("evidence")) if value)
        print(f"- {task_audit.STAGES[event['stage']]} · {event['name']} · {task_audit.SOURCES[event['source']]}"
              + (f" · {details}" if details else ""))
    if task:
        plan, _ = requirement.plan(task)
        scope = sections(plan).get("最大范围", "").strip()
        latest = requirement.latest(task, "verification")
        print(f"允许范围：{scope}")
        if rules := sections(plan).get('适用规范', '').strip():
            print(f'适用规范：\n{rules}')
        if requirement.graphify_enabled(task):
            allowed = requirement.confirmed_scope(task) or task_graphify.parse_scope(plan)
            print("EDITABLE：" + ", ".join(f"{action} {name}" for name, action in allowed["editable"].items()))
            print("GRAPHIFY_INPUT：" + ", ".join(allowed["graphify_input"]))
            print("READ_ONLY_EVIDENCE：" + ", ".join(allowed["read_only_evidence"]))
            graphify_status(root, requirement, task)
            print("流程变化与编码上下文：" + sections(plan).get("流程变化与确定编码上下文", "").strip())
            if violations := requirement.latest(task, "scope_violation").get("paths"):
                print("范围违规：" + ", ".join(violations))
        if latest:
            files = "、".join(latest.get("files", [])) or "无"
            print(f"本次改动：{files}")
            if without_patch := latest.get("without_patch"):
                print("工作区内容变化但无 Git 文本/二进制差异，请核对原文件：" + "、".join(without_patch))
            print(f"验证：{latest['result']} · {shlex.join(latest['command'])} · {latest['log']}")
            if patch := latest.get("patch"):
                print(f"差异：{requirement.audit_directory / patch}")
        reviewed = requirement.latest(task, "review")
        if decision := reviewed.get("decision"):
            label = "人工结论" if reviewed.get("patch") == latest.get("patch") else "上次人工结论"
            note = f" · {reviewed['note']}" if reviewed.get("note") else ""
            print(f"{label}：" + ("接受" if decision == "accept" else "返工") + note)
    else:
        first = {}
        for key in requirement.tasks:
            for event in requirement.records(key):
                if event["kind"] == "review":
                    first[key] = event["decision"]
                    break
        accepted = sum(value == "accept" for value in first.values())
        print(f"首次交付接受：{accepted}/{len(first)}" if first else "首次交付接受：暂无已审阅任务")


def display(root, requirement):
    print(read(requirement.index), end="")
    active = requirement.active()
    if active:
        print(f"当前任务：{requirement.task_path(active)}")
    passed = []
    for task in requirement.tasks:
        if requirement.state(task) == PASSED:
            result = requirement.latest(task, "verification")
            if result.get("result") == "passed":
                passed.append((result["checkpoint"], requirement.task_path(task)))
    focus = active or next((task for task in requirement.tasks if requirement.state(task) == PENDING), None)
    if focus:
        graphify_status(root, requirement, focus)
    if passed:
        current = snapshot(root)
        matching = [str(path) for checkpoint, path in passed if checkpoint == current]
        print("与当前工作区一致的验证：" + ("、".join(matching) or "无，请核对并重验受影响的行为"))


def ensure_idle(directory):
    for index in sorted(directory.glob("*/tasks.md")):
        other = Requirement(index.parent)
        if active := other.active():
            raise WorkflowError(f"已有执行中的任务：{other.path.name}/{active}")


def run(args, command):
    root = Path(git(None, "rev-parse", "--show-toplevel").decode().strip())
    directory = root / STATE_DIR
    path = directory / args.requirement
    with lock(directory):
        if args.action == "init":
            init_requirement(path, args.goal)
            print(path / "tasks.md")
            return
        requirement = Requirement(path)
        if args.action == "add":
            requirement.add(args.task, args.title, args.after, args.example, args.investigation, args.graphify_context,
                            getattr(args, 'graphify_audit', False))
            print(requirement.task_path(args.task))
        elif args.action == "graphify":
            plan, _ = requirement.plan(args.task)
            policy = requirement.graphify_policy(args.task)
            if not policy[args.phase]:
                raise WorkflowError(f'该任务未启用 Graphify {args.phase}')
            if args.seal and args.phase != 'after':
                raise WorkflowError('--seal 仅用于 after 后置审计')
            if args.phase == 'before':
                if requirement.state(args.task) not in (PENDING, BLOCKED):
                    raise WorkflowError('前置图仅可在确认开工前生成，不能覆盖执行中的证据')
                record = task_graphify.prepare(root, requirement.path, args.task, plan)
            else:
                if requirement.state(args.task) != REVIEW:
                    raise WorkflowError('后置图需要当前交付先验证成功并进入待审阅')
                requirement.approved(args.task, root, check_sources=False)
                requirement.unchanged_evidence(args.task, root)
                verification = requirement.latest(args.task, 'verification')
                binding = task_graphify.verification_binding(verification)
                if snapshot(root) != binding['checkpoint']:
                    raise WorkflowError('工作区与验证不一致，请重新验证')
                task_audit.review_patch(requirement.audit_directory, verification)
                if args.seal:
                    record = task_graphify.seal_audit(root, requirement.path,
                                                    requirement.graphify_record(args.task, 'after'), verification)
                    if snapshot(root) != binding['checkpoint']:
                        raise WorkflowError('封存期间工作区发生变化，请重新验证')
                    requirement.record(args.task, 'graphify_audit', **record)
                    print('已封存后置审计，待负责人审阅')
                    return
                record = task_graphify.prepare(root, requirement.path, args.task, plan, phase='after')
                record['verification'] = binding
                record['callflow'] = task_graphify.export_callflow(root, requirement.path, record)
                record['callflow_sha256'] = task_graphify.sha((requirement.path / record['callflow']).read_bytes())
                before = requirement.graphify_record(args.task)
                before_path = task_graphify.artifact_path(requirement.path, before, 'graph') if before else None
                report = task_graphify.artifact_path(requirement.path, record, 'manifest').parent / 'audit.md'
                task_graphify.write_audit_report(before_path, requirement.path / record['graph'], verification, report)
                record['report'] = str(report.relative_to(requirement.path))
                task_graphify.validate_current(root, requirement.path, record, plan)
                requirement.unchanged_evidence(args.task, root)
                if snapshot(root) != binding['checkpoint']:
                    raise WorkflowError('生成审计期间工作区发生变化，请重新验证')
            requirement.record(args.task, 'graphify_context', **record)
            print(f"Graphify {args.phase} 已生成：{requirement.path / record['graph']}")
            if record.get('report'):
                print(f"请核验报告后封存：{requirement.path / record['report']}")
        elif args.action == "status":
            display(root, requirement)
        elif args.action == "confirm":
            requirement.confirm(args.task, args.statement, root)
        elif args.action == "start":
            if requirement.state(args.task) != PENDING:
                raise WorkflowError("仅待执行任务可以开工")
            requirement.approved(args.task, root)
            dependencies = requirement.dependencies(args.task)
            ensure_idle(directory)
            manifest = {}
            baseline = snapshot(root, manifest)
            for dep in dependencies:
                evidence = requirement.latest(dep, "verification")
                if evidence.get("checkpoint") != baseline:
                    print(f"提示：{dep} 的验证使用了不同的工作区状态，请核对相关输入。", file=sys.stderr)
            tree = requirement.latest(args.task, "start").get("tree")
            if requirement.graphify_policy(args.task)['after']:
                requirement.audit_directory.mkdir(exist_ok=True)
            if requirement.audit_directory.is_dir() and not tree:
                tree = task_audit.capture_tree(root, requirement.audit_directory)
                if snapshot(root) != baseline:
                    raise WorkflowError("生成开工基线时工作区发生变化，请重试")
                write(requirement.audit_directory / f"{args.task}-baseline.json", json.dumps(manifest))
            requirement.record(args.task, "start", baseline=baseline, tree=tree)
            requirement.set_state(args.task, ACTIVE)
            print(requirement.task_path(args.task))
        elif args.action == "block":
            task = args.task or requirement.active()
            if not task or requirement.state(task) not in (PENDING, ACTIVE, REVIEW):
                raise WorkflowError("只能阻塞待执行或执行中的任务")
            requirement.record(task, "block", category=args.kind, label=KINDS[args.kind],
                               issue=args.issue, impact=args.impact, next=args.next)
            requirement.set_state(task, BLOCKED)
        elif args.action == "resolve":
            if requirement.state(args.task) != BLOCKED:
                raise WorkflowError("任务当前没有阻塞")
            if requirement.latest(args.task, "block").get("category") == "decision":
                raise WorkflowError("业务决定需由负责人用 confirm 确认")
            requirement.record(args.task, "resolution", detail=args.detail)
            requirement.set_state(args.task, PENDING)
        elif args.action in ("skill", "_observe-skill"):
            if args.stage in ("execute", "verify") and not args.task:
                raise WorkflowError("执行和验收阶段需要 --task")
            if args.task:
                requirement.state(args.task)
            task_audit.record_skill(requirement.audit_directory, name=args.name, stage=args.stage,
                                    source=getattr(args, "source", "declared"), task=args.task,
                                    purpose=getattr(args, "purpose", None), evidence=args.evidence)
        elif args.action == "audit":
            audit_report(root, requirement, args.task, args.diff)
        elif args.action == "review":
            review(root, requirement, args.task, args.decision, args.note)
        elif args.action == "verify":
            task = requirement.active()
            if args.task:
                ensure_idle(directory)
                if requirement.state(args.task) != PASSED:
                    raise WorkflowError("verify --task 仅用于复验已通过任务")
                task = args.task
            if not task:
                raise WorkflowError("没有执行中的任务")
            verify(root, requirement, task, command)


def identifier(pattern):
    def parse(value):
        if not re.fullmatch(pattern, value):
            raise argparse.ArgumentTypeError(f"无效标识：{value}")
        return value
    return parse


def one_line(value):
    result = value.strip()
    if not result or any(char in result for char in "|\n\r"):
        raise argparse.ArgumentTypeError("请输入非空单行文本，且不含竖线")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    task_id = identifier(TASK_ID)
    for action in ("init", "add", "status", "confirm", "start", "block", "resolve", "verify", "audit", "review", "skill", "_observe-skill", "graphify"):
        item = sub.add_parser(action)
        item.add_argument("requirement", type=identifier(r"[a-zA-Z0-9][a-zA-Z0-9_-]*"))
        if action in ("add", "confirm", "start", "resolve", "review", "graphify"):
            item.add_argument("task", type=task_id)
        if action == "init":
            item.add_argument("--goal", required=True, type=one_line)
        elif action == "add":
            item.add_argument("--title", required=True, type=one_line)
            item.add_argument("--after", action="append", type=task_id, default=[])
            reference = item.add_mutually_exclusive_group()
            reference.add_argument("--example", action="append", type=identifier(EXAMPLE_ID), default=[])
            reference.add_argument("--investigation", action="store_true")
            graphify = item.add_mutually_exclusive_group()
            graphify.add_argument('--graphify-context', action='store_true', help='启用修改前上下文及交付后审计')
            graphify.add_argument('--graphify-audit', action='store_true', help='仅启用交付后关系与流程审计')
        elif action == 'graphify':
            item.add_argument('--phase', choices=('before', 'after'), default='before')
            item.add_argument('--seal', action='store_true', help='核验并封存本次后置审计报告')
        elif action == "confirm":
            item.add_argument("--statement", required=True, type=one_line)
        elif action == "resolve":
            item.add_argument("--detail", required=True, type=one_line)
        elif action == "verify":
            item.add_argument("--task", type=task_id)
        elif action == "audit":
            item.add_argument("task", nargs="?", type=task_id)
            item.add_argument("--diff", action="store_true")
        elif action == "review":
            item.add_argument("decision", choices=("accept", "rework"))
            item.add_argument("--note", type=one_line)
        elif action in ("skill", "_observe-skill"):
            item.add_argument("name", type=one_line)
            item.add_argument("--stage", choices=task_audit.STAGES, required=True)
            item.add_argument("--task", type=task_id)
            if action == "skill":
                item.add_argument("--purpose", type=one_line)
            else:
                item.add_argument("--source", choices=("pi-read", "pi-command"), required=True)
            item.add_argument("--evidence", type=one_line, required=action == "_observe-skill")
        elif action == "block":
            item.add_argument("--task", type=task_id)
            item.add_argument("--kind", required=True, choices=KINDS)
            for field in ("issue", "impact", "next"):
                item.add_argument(f"--{field}", required=True, type=one_line)

    argv = sys.argv[1:]
    delimiter = argv.index("--") if "--" in argv else len(argv)
    args = parser.parse_args(argv[:delimiter])
    command = argv[delimiter + 1:]
    if args.action == "verify" and not command:
        parser.error("verify 需要 -- 后的验证命令")
    if args.action != "verify" and delimiter < len(argv):
        parser.error("只有 verify 接受 -- 后的命令")
    try:
        run(args, command)
    except (WorkflowError, task_audit.AuditError, task_graphify.ScopeError, OSError, ValueError) as error:
        print(f"工作流：{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
