"""Keep review evidence in the disposable workflow directory."""
import hashlib
import json
import math
import os
import re
import time
import uuid
from pathlib import Path
import subprocess
import tempfile


STAGES = {"clarify": "需求澄清", "plan": "整体规划", "execute": "任务执行", "verify": "任务验收"}
SOURCES = {"declared": "声明使用", "pi-read": "Pi 观察到读取", "pi-command": "Pi 观察到调用"}


class AuditError(Exception):
    pass


def git(root, *args, env=None, data=None):
    result = subprocess.run(["git", "-c", "core.splitIndex=false", "-c", "core.hooksPath=/dev/null", *args], cwd=root,
                            env=env, input=data, capture_output=True)
    if result.returncode:
        raise AuditError(result.stderr.decode(errors="replace").strip() or "无法生成 Git 审计证据")
    return result.stdout


def object_environment(root, directory):
    objects = directory / "objects"
    info = objects / "info"
    info.mkdir(parents=True, exist_ok=True)
    location = git(root, "rev-parse", "--git-path", "objects").decode().rstrip("\n")
    (info / "alternates").write_text(str((root / location).resolve()) + "\n", encoding="utf-8")
    return {**os.environ, "GIT_OBJECT_DIRECTORY": str(objects)}


def capture_tree(root, directory):
    """Snapshot tracked and unignored paths without changing the real index."""
    env = object_environment(root, directory)
    with tempfile.TemporaryDirectory(dir=directory, prefix="index-") as scratch:
        env["GIT_INDEX_FILE"] = str(Path(scratch) / "index")
        entries = git(root, "ls-files", "--stage", "-z")
        git(root, "update-index", "-z", "--index-info", env=env, data=entries)
        git(root, "add", "-A", "--", ".", ":(exclude,top).ai-workflow", env=env)
        return git(root, "write-tree", env=env).decode().strip()


def capture_diff(root, directory, baseline, current):
    env = object_environment(root, directory)
    options = ("diff", "--no-ext-diff", "--no-textconv", "--no-renames")
    names = git(root, *options, "--name-only", "-z", baseline, current, "--", env=env)
    patch = git(root, *options, "--binary", baseline, current, "--", env=env)
    with tempfile.NamedTemporaryFile(dir=directory, prefix="task-", suffix=".patch", delete=False) as file:
        file.write(patch)
    return Path(file.name).name, hashlib.sha256(patch).hexdigest(), [
        os.fsdecode(name) for name in names.split(b"\0") if name
    ]


def review_patch(directory, receipt):
    name = receipt["patch"]
    if Path(name).name != name:
        raise AuditError("无效的审阅差异路径")
    path = directory / name
    if not path.is_file():
        raise AuditError("审阅差异缺失，请重新验证")
    patch = path.read_bytes()
    if hashlib.sha256(patch).hexdigest() != receipt.get("patch_sha256"):
        raise AuditError("审阅差异已改变，请重新验证")
    return patch


def skills(directory):
    log = directory / "skills.jsonl"
    if directory.is_symlink() or log.is_symlink():
        raise AuditError('Skill记录不能是符号链接')
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def record_skill(directory, **entry):
    if directory.is_symlink() or (directory / 'skills.jsonl').is_symlink():
        raise AuditError('Skill记录不能是符号链接')
    directory.mkdir(exist_ok=True)
    if entry in skills(directory):
        return
    with (directory / "skills.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(entry, ensure_ascii=False) + "\n")


SECRET_KEY = re.compile(r"(?:password|passwd|secret|authorization|api[_-]?key|(?:access|refresh|auth)[_-]?token)", re.I)
SECRET_VALUE = re.compile(r'''(?i)((?:password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token)\b["']?\s*[:=]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\s,;]+)''')
EVENT_KINDS = ('input', 'output', 'skill', 'rule', 'tool', 'agent', 'delegation', 'derivation', 'recall', 'lifecycle', 'verification', 'capability', 'gap')


def _validate_event(entry, complete=False):
    if not isinstance(entry, dict):
        raise AuditError('节点记录必须是对象')
    for key, allowed in [('kind', EVENT_KINDS), ('stage', STAGES), ('source', (*SOURCES, 'pi-event', 'workflow'))]:
        if not isinstance(entry.get(key), str) or entry[key] not in allowed:
            raise AuditError(f'无效的节点{key}')
    if not isinstance(entry.get('name'), str) or not entry['name'].strip() or not isinstance(entry.get('summary', ''), str):
        raise AuditError('节点名称和摘要必须是文本')
    for key in ('task', 'node', 'parent', 'run', 'reference'):
        if entry.get(key) is not None and not isinstance(entry[key], str):
            raise AuditError(f'无效的节点{key}')
    if entry.get('task') is not None and not re.fullmatch(r'T[0-9]{2,}', entry['task']):
        raise AuditError('无效的审计任务')
    if complete:
        if not isinstance(entry.get('id'), str) or not re.fullmatch(r'[0-9a-f]{32}', entry['id']):
            raise AuditError('节点标识缺失或损坏')
        if not isinstance(entry.get('evidence'), str) or not re.fullmatch(r'[0-9a-f]{64}', entry['evidence']):
            raise AuditError('节点证据标识缺失或损坏')
        if not isinstance(entry.get('timestamp'), (int, float)) or not math.isfinite(entry['timestamp']):
            raise AuditError('节点时间缺失或损坏')


def redact(value):
    """Retain observable facts, never known credential fields or terminal controls."""
    if isinstance(value, dict):
        sensitive_file = Path(str(value.get('path', ''))).name.lower()
        omit_content = (sensitive_file == '.env' or sensitive_file.startswith('.env.')
                        or sensitive_file in ('auth.json', 'credentials.json', 'id_rsa', 'id_ed25519')
                        or sensitive_file.endswith(('.pem', '.key')))
        return {key: '[REDACTED]' if SECRET_KEY.search(str(key)) or
                (omit_content and key in ('text', 'content', 'output', 'result')) else redact(item)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----', '[REDACTED]', value, flags=re.S)
        value = re.sub(r'(?i)Bearer\s+[^\s"\'<>]+', 'Bearer [REDACTED]', value)
        value = SECRET_VALUE.sub(r'\1[REDACTED]', value)
        return ''.join(char if char in '\n\t' or ord(char) >= 32 and ord(char) != 127
                       else f'\\x{ord(char):02x}' for char in value)
    return value


def _audit_paths(directory):
    directory = Path(directory)
    if directory.is_symlink():
        raise AuditError('审计目录不能是符号链接')
    directory.mkdir(parents=True, exist_ok=True)
    evidence = directory / 'evidence'
    if evidence.is_symlink() or (directory / 'events.jsonl').is_symlink():
        raise AuditError('审计证据不能是符号链接')
    evidence.mkdir(exist_ok=True)
    return directory, evidence


def store_event(directory, *, kind, name, stage, summary='', detail=None, source='declared',
                task=None, node=None, parent=None, run=None, reference=None):
    _validate_event(dict(kind=kind, name=name, stage=stage, source=source, summary=summary,
                         task=task, node=node, parent=parent, run=run, reference=reference))
    directory, evidence = _audit_paths(directory)
    data = redact(detail if detail is not None else {})
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode('utf-8')
    digest = hashlib.sha256(raw).hexdigest()
    target = evidence / f'{digest}.json'
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        load_evidence(directory, digest)
    else:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
    entry = redact(dict(id=uuid.uuid4().hex, timestamp=time.time(), kind=kind, name=name,
                        stage=stage, task=task, node=node, parent=parent, run=run,
                        source=source, summary=summary, evidence=digest, reference=reference))
    with (directory / 'events.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + '\n')
    return entry


def record_reference(task, index, record):
    raw = json.dumps(record, sort_keys=True, ensure_ascii=False).encode('utf-8')
    return f'{task}:{index}:' + hashlib.sha256(raw).hexdigest()


def events(directory):
    directory = Path(directory)
    path = directory / 'events.jsonl'
    if directory.is_symlink() or path.is_symlink():
        raise AuditError('审计记录不能是符号链接')
    if not path.exists():
        return []
    try:
        result = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        for entry in result:
            _validate_event(entry, complete=True)
        return result
    except (ValueError, OSError) as error:
        raise AuditError(f'审计记录不可读：{error}') from error


def load_evidence(directory, digest):
    if not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise AuditError('无效的证据标识')
    directory = Path(directory)
    path = directory / 'evidence' / f'{digest}.json'
    if directory.is_symlink() or path.parent.is_symlink() or path.is_symlink():
        raise AuditError('审计证据不能是符号链接')
    if not path.is_file():
        raise AuditError('证据缺失')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise AuditError('证据已改变，不能作为原始输入审阅')
    return json.loads(raw)
