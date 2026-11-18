"""Loose requirement links: pointers and accepted-result recalls, never parent state copies."""
import hashlib
import json
from pathlib import Path
import re
import tempfile

import task_audit

NAME = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_-]*')
TASK = re.compile(r'T[0-9]{2,}')
ROW = re.compile(r'\| \[(T[0-9]{2,})\]\(tasks/\1\.md\) \| ([^|]+) \| ([^|]+) \| ([^|]+) \|')


def requirement_path(directory, name):
    if not NAME.fullmatch(name):
        raise task_audit.AuditError('无效的需求标识')
    directory = Path(directory)
    path = directory / name
    if directory.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
        raise task_audit.AuditError('需求路径不能逃逸或使用符号链接')
    return path


def task_rows(path):
    index = path / 'tasks.md'
    if index.is_symlink() or not index.is_file():
        raise task_audit.AuditError('上层需求入口不可用')
    matches = [m for line in index.read_text(encoding='utf-8').splitlines() if (m := ROW.fullmatch(line))]
    rows = {m[1]: {'title': m[2].strip(), 'after': m[3].strip(), 'state': m[4].strip()} for m in matches}
    if len(rows) != len(matches):
        raise task_audit.AuditError('上层任务编号重复，不能建立含糊关系')
    return rows


def parent_entry(directory, name, task):
    if not TASK.fullmatch(task):
        raise task_audit.AuditError('无效的上层任务')
    path = requirement_path(directory, name)
    entry = path / 'tasks' / f'{task}.md'
    if (task not in task_rows(path) or (path / 'tasks').is_symlink()
            or entry.is_symlink() or not entry.is_file()):
        raise task_audit.AuditError('上层收敛任务入口不可用')
    return {'requirement': name, 'task': task, 'entry': f'{name}/tasks/{task}.md'}


def superiors(path):
    file = path / 'superiors'
    if file.is_symlink():
        raise task_audit.AuditError('superiors不能是符号链接')
    if not file.exists():
        return []
    entries = json.loads(file.read_text(encoding='utf-8'))
    if not isinstance(entries, list):
        raise task_audit.AuditError('superiors必须是上层指针列表')
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != {'requirement', 'task', 'entry'}
                or not isinstance(entry['requirement'], str) or not NAME.fullmatch(entry['requirement'])
                or not isinstance(entry['task'], str) or not TASK.fullmatch(entry['task'])
                or entry['entry'] != f"{entry['requirement']}/tasks/{entry['task']}.md"):
            raise task_audit.AuditError('无效的上层指针，拒绝路径逃逸')
    if len({(e['requirement'], e['task']) for e in entries}) != len(entries):
        raise task_audit.AuditError('superiors包含重复关系')
    return entries


def validate_link(directory, child, parent, task):
    entry = parent_entry(directory, parent, task)
    visited = set()
    def visit(name, stack):
        if name == child or name in stack:
            raise task_audit.AuditError('父子关系不能自引用或形成循环')
        if name in visited:
            return
        visited.add(name)
        path = requirement_path(directory, name)
        for upper in superiors(path):
            visit(upper['requirement'], stack | {name})
    visit(parent, set())
    return entry


def _write_pointers(path, entries):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(entries, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.close()
            temporary.replace(path / 'superiors')
        finally:
            temporary.unlink(missing_ok=True)


def derive(directory, parent, task, child, goal, contract, initializer):
    destination = requirement_path(directory, child)
    entry = validate_link(directory, child, parent, task)
    if destination.exists():
        raise task_audit.AuditError('需求已存在；续接或用link补充关联，不重复创建')
    with tempfile.TemporaryDirectory(prefix='.derive-', dir=directory) as scratch:
        staging = Path(scratch) / child
        initializer(staging, goal)
        _write_pointers(staging, [entry])
        task_audit.store_event(staging / 'audit', kind='derivation', name=child, stage='clarify',
                               source='workflow', summary=contract['reason'], parent=f'{parent}/{task}',
                               detail={'goal': goal, 'parent': entry, **contract})
        staging.rename(destination)
    return destination


def link(directory, child, parent, task, reason, statement):
    path = requirement_path(directory, child)
    task_rows(path)
    entry = validate_link(directory, child, parent, task)
    entries = superiors(path)
    if entry in entries:
        return False
    task_audit.store_event(path / 'audit', kind='derivation', name=child, stage='clarify',
                           source='declared', summary=f'补充关联决策：{reason}', parent=f'{parent}/{task}',
                           detail={'parent': entry, 'reason': reason, 'statement': statement,
                                   'historical_relation': '补充关联决策，不是历史自动派生或指针成功安装的证明'})
    try:
        _write_pointers(path, entries + [entry])
    except OSError as error:
        raise task_audit.AuditError(f'关联决策已留存，但上层指针未建立：{error}') from error
    return True


def children(directory, parent, task):
    result, warnings = [], []
    for path in sorted(Path(directory).iterdir()):
        if path.name.startswith('.') or not path.is_dir() or path.is_symlink():
            continue
        linked = False
        try:
            entries = superiors(path)
            if any(e['requirement'] == parent and e['task'] == task for e in entries):
                linked = True
                rows = task_rows(path)
                result.append({'requirement': path.name, 'entry': f'{path.name}/tasks.md',
                               'states': {key: value['state'] for key, value in rows.items()}})
        except (task_audit.AuditError, ValueError, OSError) as error:
            if linked:
                result.append({'requirement': path.name, 'warning': str(error)})
            else:
                warnings.append(f'{path.name} 上层关系不可读，未作为子节点：{error}')
    return result, warnings


def recall(requirement):
    entries = superiors(requirement.path)
    if not entries or not requirement.tasks:
        return []
    accepted = []
    for task in requirement.tasks:
        review = requirement.latest(task, 'review')
        verification = requirement.latest(task, 'verification')
        if (requirement.state(task) != '通过' or review.get('decision') != 'accept'
                or not review.get('patch') or review.get('patch') != verification.get('patch')
                or verification.get('result') != 'passed'):
            return []
        plan, _ = requirement.plan(task)
        if requirement.latest(task, 'confirmation').get('plan_sha256') != requirement.approval_digest(plan):
            return []
        accepted.append((task, review, requirement.latest(task, 'confirmation')))
    completion = hashlib.sha256(json.dumps(accepted, sort_keys=True).encode()).hexdigest()
    if any(e['kind'] == 'recall' and e.get('run') == completion
           for e in task_audit.events(requirement.audit_directory)):
        return []
    targets = []
    for entry in entries:
        try:
            parent_entry(requirement.path.parent, entry['requirement'], entry['task'])
            targets.append({**entry, 'available': True})
        except (task_audit.AuditError, OSError, ValueError) as error:
            targets.append({**entry, 'available': False, 'warning': f'上层入口不可用：{error}'})
    task_audit.store_event(requirement.audit_directory, kind='recall', name=requirement.path.name,
                           stage='verify', source='workflow', run=completion,
                           summary='负责人已接受全部任务；返回上层收敛入口，不自动执行或完成父任务',
                           detail={'targets': targets, 'completion': completion})
    return targets
