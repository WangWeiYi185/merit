"""Keep review evidence in the disposable workflow directory."""
import hashlib
import json
import os
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
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def record_skill(directory, **entry):
    directory.mkdir(exist_ok=True)
    if entry in skills(directory):
        return
    with (directory / "skills.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(entry, ensure_ascii=False) + "\n")
