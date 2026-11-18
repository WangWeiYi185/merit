"""Read-only human projections over task state and retained execution evidence."""
import hashlib
import json
import re

import task_audit
import task_topology


def compact(value, limit=180):
    text = ' '.join(str(task_audit.redact(value)).split())
    return text if len(text) <= limit else text[:limit] + '…'


def checks(requirement, task):
    result = {}
    for record in requirement.records(task):
        if record['kind'] == 'verification' and record.get('check'):
            result[record['check']] = record
    return result


def failed_checks(requirement, task):
    checkpoint = requirement.latest(task, 'verification').get('checkpoint')
    return [name for name, value in checks(requirement, task).items()
            if value['result'] != 'passed' or value.get('checkpoint') != checkpoint]


def _legacy_id(task, index, record):
    digest = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
    return f'record:{task}:{index}:{digest}'


def legacy_evidence(requirement, identifier):
    draft = re.fullmatch(r'plan:(T[0-9]{2,}):([0-9a-f]{64})', identifier)
    if draft:
        plan, _ = requirement.plan(draft[1])
        if hashlib.sha256(plan.encode()).hexdigest() != draft[2]:
            raise task_audit.AuditError('当前计划已改变，请刷新看板；不能冒充历史快照')
        return task_audit.redact({'task_brief': plan, 'limitation': '当前计划原文，非执行时上下文快照'})
    match = re.fullmatch(r'record:(T[0-9]{2,}):([0-9]+):([0-9a-f]{64})', identifier)
    if not match:
        raise task_audit.AuditError('无效的旧证据标识')
    task, index = match[1], int(match[2])
    records = requirement.records(task)
    if index >= len(records) or _legacy_id(task, index, records[index]) != identifier:
        raise task_audit.AuditError('旧记录已改变或缺失，不能冒充历史证据')
    record = records[index]
    detail = {'record': record, 'limitation': '旧记录，不代表当时完整上下文'}
    for key, directory in [('log', requirement.path), ('patch', requirement.audit_directory)]:
        if value := record.get(key):
            from pathlib import Path
            if Path(value).name != value:
                raise task_audit.AuditError('证据路径不能逃逸')
            path = directory / value
            if path.is_symlink() or directory.is_symlink():
                raise task_audit.AuditError('证据不能是符号链接')
            detail[key] = path.read_text(encoding='utf-8', errors='replace') if path.is_file() else '[证据缺失]'
    return task_audit.redact(detail)


def _rule_text(detail):
    if isinstance(detail.get('content'), str):
        return detail['content']
    if detail.get('tool') != 'read' or detail.get('inputObservation') != 'tool_result最终输入':
        return None
    args, output = detail.get('input', {}), detail.get('output', {})
    truncation = (output.get('details') or {}).get('truncation') or {}
    if (args.get('offset') not in (None, 1) or args.get('limit') is not None
            or truncation.get('truncated') or truncation.get('firstLineExceedsLimit')):
        return None
    parts = output.get('content', [])
    return parts[0].get('text') if len(parts) == 1 and parts[0].get('type') == 'text' else None


def build(root, requirement, task=None):
    if task:
        requirement.state(task)
    events = task_audit.events(requirement.audit_directory)
    selected = [e for e in events if not task or e.get('task') in (None, task)]
    data = {'requirement': requirement.path.name,
            'title': compact(requirement.lines[0].lstrip('# ')) if requirement.lines else requirement.path.name,
            'superiors': task_topology.superiors(requirement.path), 'tasks': [],
            'nodes': selected, 'skills': [], 'rules': [], 'inputs': [], 'outputs': [],
            'checks': {}, 'warnings': []}
    for key in ([task] if task else requirement.tasks):
        state = requirement.state(key)
        record = requirement.latest(key, 'verification')
        failures = failed_checks(requirement, key)
        related, warnings = task_topology.children(requirement.path.parent, requirement.path.name, key)
        data['warnings'].extend(warnings)
        row = {'task': key, 'title': requirement.tasks[key][1], 'state': state,
               'after': [] if requirement.tasks[key][2] == '—' else requirement.tasks[key][2].split(', '),
               'entry': f'{requirement.path.name}/tasks/{key}.md',
               'children': related,
               'result': record.get('result'), 'failed_checks': failures}
        if block := requirement.latest(key, 'block'):
            if state == '阻塞':
                row['blocker'] = compact(block['issue'])
        data['tasks'].append(row)
        if task:
            data['checks'] = {name: {**{field: value.get(field) for field in ('result', 'exit_code', 'checkpoint')},
                                            'current': value.get('checkpoint') == record.get('checkpoint')}
                              for name, value in checks(requirement, key).items()}
            data['verification_checkpoint'] = record.get('checkpoint')
            plan, _ = requirement.plan(key)
            input_ref = f'plan:{key}:' + hashlib.sha256(plan.encode()).hexdigest()
            execution_input = next((e for e in reversed(selected) if e.get('task') == key and e['source'] == 'workflow' and e['kind'] == 'lifecycle' and e['name'] in ('start', 'confirmation')), None)
            if execution_input:
                saved = task_audit.load_evidence(requirement.audit_directory, execution_input['evidence'])
                if saved_plan := saved.get('task_brief'):
                    if saved_plan != plan:
                        data['warnings'].append(f'{key} 当前计划已不同于本轮保存的输入；审计显示当时版本')
                    plan, input_ref = saved_plan, execution_input['evidence']
            parts = re.split(r'(?m)^## (.+)\n', plan)
            sections = dict(zip(parts[1::2], parts[2::2]))
            data['inputs'] = [{'name': name, 'summary': compact(sections[name]), 'source': 'declared',
                               'evidence': input_ref}
                              for name in ('目标与示例', '最大范围', '保留行为与暂停条件', '验收方案') if sections.get(name, '').strip()]
            data['rules'] = [{'name': line[2:] if line.startswith('- ') else line, 'source': 'declared',
                              'evidence': input_ref}
                             for line in sections.get('适用规范', '').splitlines() if line.strip()]
            snapshots = {e.get('reference'): e['evidence'] for e in selected if e['source'] == 'workflow' and e.get('reference')}
            for index, old in enumerate(requirement.records(key)):
                if old['kind'] not in ('verification', 'review', 'block', 'resolution'):
                    continue
                data['outputs'].append({'name': old['kind'] + (f" / {old['check']}" if old.get('check') else ''),
                    'summary': (f"{old.get('result', '未记录')} · 退出{old.get('exit_code', '未记录')} · 改动{len(old.get('files', []))}文件" if old['kind'] == 'verification'
                                else compact(old.get('note') or old.get('issue') or old.get('detail') or old.get('decision') or old['kind'])),
                    'source': 'workflow', 'evidence': snapshots.get(task_audit.record_reference(key, index, old)) or _legacy_id(key, index, old)})
        if failures:
            data['warnings'].append(f'{key} 未通过或已过期检查：' + '、'.join(failures))
        elif record.get('result') == 'passed':
            latest_by_command = {}
            for item in requirement.records(key):
                if item['kind'] == 'verification':
                    latest_by_command[tuple(item['command'])] = item['result']
            if 'failed' in latest_by_command.values():
                data['warnings'].append(f'{key} 有其他命令的历史失败；最近一次成功不证明所有检查通过')
    for event in selected:
        if event['kind'] == 'skill':
            data['skills'].append(event)
        elif event['kind'] == 'rule':
            data['rules'].append(event)
        elif event['kind'] == 'input':
            data['inputs'].append(event)
        elif event['kind'] == 'output':
            data['outputs'].append(event)
    versions = {}
    for event in data['rules']:
        if not event['source'].startswith('pi-') or not event.get('evidence'):
            continue
        try:
            text = _rule_text(task_audit.load_evidence(requirement.audit_directory, event['evidence']))
            if isinstance(text, str):
                version = hashlib.sha256(text.encode()).hexdigest()
                event['recorded_text_sha256'] = version
                versions.setdefault(event['name'], set()).add(version)
        except task_audit.AuditError as error:
            data['warnings'].append(f"{event['name']} 规则证据不可用：{error}")
    for name, observed in versions.items():
        if len(observed) > 1:
            data['warnings'].append(f'{name} 记录中的规则版本不一致；按执行轮次深审已加载输入、后续读取及采用依据')
    known = {(e['name'], e['stage'], e['source'], e.get('task')) for e in data['skills']}
    for old in task_audit.skills(requirement.audit_directory):
        if task and old.get('task') not in (None, task):
            continue
        if (old['name'], old['stage'], old['source'], old.get('task')) not in known:
            data['skills'].append({**old, 'summary': old.get('purpose') or '', 'evidence': None,
                                   'limitation': '旧声明/观察，无本轮原文快照'})
    if not any(e['source'].startswith('pi-') for e in selected):
        data['warnings'].append('暂无本轮Pi观察证据；声明使用不等于实际调用或独立Agent审查')
    elif not any(e['kind'] == 'agent' for e in selected):
        data['warnings'].append('已观察部分能力/工具，但未记录完整Agent运行入口；不补造委派链')
    data['warnings'] = list(dict.fromkeys(data['warnings']))
    return task_audit.redact(data)


def render(data):
    lines = [f"{data['requirement']} · {data['title']}"]
    for parent in data['superiors']:
        lines.append(f"上层：{parent['requirement']}/{parent['task']}")
    for task in data['tasks']:
        after = f" · 前置：{', '.join(task['after'])}" if task.get('after') else ''
        lines.append(f"- {task['task']} {task['title']} · {task['state']}" + after)
        if task.get('blocker'):
            lines.append('  阻塞：' + task['blocker'])
        for child in task['children']:
            lines.append(f"  └─ {child['requirement']} · " + compact(child.get('warning') or child.get('states', {})))
    for label, key in [('输入', 'inputs'), ('Skills', 'skills'), ('Rules', 'rules'), ('输出', 'outputs')]:
        if data[key]:
            lines.append(label + '：')
            items = data[key]
            if key == 'outputs':
                latest = {}
                for item in items:
                    latest[item['name']] = item
                items = list(latest.values())
            for item in items:
                lines.append(f"  - {compact(item['name'], 100)} · {compact(item.get('summary') or item.get('purpose') or '', 140)} [{item['source']}]")
    phases = []
    for node in data['nodes']:
        label = task_audit.STAGES[node['stage']]
        if not phases or phases[-1] != label:
            phases.append(label)
    if phases:
        lines.append('已记录阶段：' + ' → '.join(phases[:8]) + (' → …（其余可深审）' if len(phases) > 8 else ''))
    visible_nodes = [node for node in data['nodes'] if node['kind'] in ('derivation', 'agent', 'delegation', 'capability', 'recall')]
    if visible_nodes:
        lines.append('流程节点：')
        for node in visible_nodes:
            lines.append(f"  - {task_audit.STAGES[node['stage']]} · {node['kind']} / {compact(node['name'], 80)} · {compact(node['summary'], 120)} [{node['source']}]")
    internal = len(data['nodes']) - len(visible_nodes)
    if internal:
        lines.append(f'内部过程：{internal}项，默认折叠，可逐项深审。')
    for warning in data['warnings']:
        lines.append('注意：' + warning)
    lines.append('详细证据按节点展开；默认不展示内部日志、上下文全文或差异。')
    return '\n'.join(lines)
