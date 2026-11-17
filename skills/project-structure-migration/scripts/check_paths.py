#!/usr/bin/env python3
"""Read-only preflight and scope checks for one migration batch."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unicodedata


def git(*args, cwd):
    return subprocess.check_output(["git", *args], cwd=cwd)


def paths_from_git(*args, cwd):
    return {os.fsdecode(path) for path in git(*args, cwd=cwd).split(b"\0") if path}


def relative_path(value):
    if (
        not isinstance(value, str)
        or "\\" in value
        or any(ord(char) < 32 for char in value)
        or any(part.casefold() in {"", ".", "..", ".git"} for part in value.split("/"))
    ):
        raise ValueError(f"expected a repository-relative file path: {value!r}")
    return value


def folded(name):
    return unicodedata.normalize("NFD", name).casefold()


def exact_path(root, path):
    """Check each component for case/normalization collisions and symlinks."""
    current = root
    parts = path.split("/")
    for index, name in enumerate(parts):
        matching = [entry for entry in current.iterdir() if folded(entry.name) == folded(name)]
        if not matching:
            return None
        if len(matching) > 1 or matching[0].name != name:
            raise ValueError(f"case or Unicode path collision: {path} against {matching[0].relative_to(root)}")
        current = matching[0]
        if current.is_symlink():
            raise ValueError(f"symbolic link in path: {current.relative_to(root)}")
        if index < len(parts) - 1 and not current.is_dir():
            raise ValueError(f"parent path collision: {current.relative_to(root)}")
    return current


def load_plan(plan_file):
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    if not isinstance(plan, dict) or not isinstance(plan.get("moves"), list) or not plan["moves"]:
        raise ValueError("expected a plan with a non-empty moves list")
    if not isinstance(plan.get("module"), str) or not plan["module"].strip():
        raise ValueError("expected a module name")
    base_commit = plan.get("base_commit")
    if not isinstance(base_commit, str) or not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", base_commit):
        raise ValueError("base_commit must be a full Git commit SHA")
    if not isinstance(plan.get("linked_edits"), list):
        raise ValueError("expected a linked_edits list")
    moves = [(relative_path(item["from"]), relative_path(item["to"])) for item in plan["moves"]]
    linked = [relative_path(path) for path in plan["linked_edits"]]
    all_paths = [path for move in moves for path in move] + linked
    if len({folded(path) for path in all_paths}) != len(all_paths):
        raise ValueError("path collision between plan entries, including case-only renames")
    spellings = {}
    leaves = {folded(path) for path in all_paths}
    for path in all_paths:
        parts = path.split("/")
        for end in range(1, len(parts)):
            parent = "/".join(parts[:end])
            if folded(parent) in leaves or spellings.setdefault(folded(parent), parent) != parent:
                raise ValueError(f"parent path collision: {path}")
    return plan["base_commit"], moves, set(linked)


def check(mode, plan_file, cwd):
    base_ref, moves, linked = load_plan(plan_file)
    root = Path(os.fsdecode(git("rev-parse", "--show-toplevel", cwd=cwd).rstrip(b"\n")))
    base = git("rev-parse", "--verify", "--end-of-options", base_ref + "^{commit}", cwd=root).decode().strip()
    head = git("rev-parse", "HEAD", cwd=root).decode().strip()
    if mode == "preflight" and head != base:
        raise ValueError("HEAD differs from the plan baseline")
    git("merge-base", "--is-ancestor", base, "HEAD", cwd=root)
    baseline = paths_from_git("ls-tree", "-r", "--name-only", "-z", base, cwd=root)

    for source, target in moves:
        if source not in baseline:
            raise ValueError(f"source is absent from the baseline: {source}")
        if target in baseline:
            raise ValueError(f"destination collision in baseline: {target}")
        source_path = exact_path(root, source)
        target_path = exact_path(root, target)
        if mode == "preflight":
            if source_path is None or not source_path.is_file():
                raise ValueError(f"missing source file: {source}")
            if target_path is not None:
                raise ValueError(f"destination collision: {target}")
        else:
            if source_path is not None:
                raise ValueError(f"source still exists: {source}")
            if target_path is None or not target_path.is_file():
                raise ValueError(f"missing destination file: {target}")

    for path in sorted(linked):
        linked_path = exact_path(root, path)
        if path not in baseline or linked_path is None or not linked_path.is_file():
            raise ValueError(f"linked edit must refer to an existing baseline file: {path}")

    options = ("--no-renames", "--name-only", "-z")
    worktree = paths_from_git("diff", *options, base, "--", cwd=root)
    committed = paths_from_git("diff", *options, base, "HEAD", "--", cwd=root)
    staged = paths_from_git("diff", *options, "--cached", "HEAD", "--", cwd=root)
    unstaged = paths_from_git("diff", *options, "--", cwd=root)
    untracked = paths_from_git("ls-files", "--others", "--exclude-standard", "-z", cwd=root)
    changed = worktree | committed | staged | unstaged | untracked
    if mode == "preflight":
        if changed:
            raise ValueError("preflight requires a clean baseline: " + ", ".join(sorted(changed)))
        return

    move_paths = {path for move in moves for path in move}
    if extra := changed - move_paths - linked:
        raise ValueError("paths outside scope: " + ", ".join(sorted(extra)))
    if missing := move_paths - (worktree | untracked):
        raise ValueError("move paths missing from the Git delta: " + ", ".join(sorted(missing)))
    if missing := linked - worktree:
        raise ValueError("missing linked edit: " + ", ".join(sorted(missing)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "verify"))
    parser.add_argument("plan", type=Path)
    args = parser.parse_args()
    try:
        check(args.mode, args.plan.resolve(), Path.cwd())
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"PASS: {args.mode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
