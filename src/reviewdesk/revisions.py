"""Bounded Git operations; never run commands supplied by a repository."""
import hashlib
import fnmatch
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .contracts import Change, Hunk, ReviewOptions, Snapshot
from .selection import LOCKS, check_path, sensitive

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
MAX_CAPTURE = 8 * 1024 * 1024
GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "NUL" if os.name == "nt" else "/dev/null",
           "GIT_CONFIG_SYSTEM": "NUL" if os.name == "nt" else "/dev/null",
           "GIT_PAGER": "cat", "GIT_EXTERNAL_DIFF": "0",
           "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}
GIT_BINARY = shutil.which("git")
HOOKS_PATH = "NUL" if os.name == "nt" else "/dev/null"


def _git(root: Path, *args: str, max_bytes: int = MAX_CAPTURE) -> bytes:
    if not GIT_BINARY:
        raise ValueError("Git is not installed")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    env.update(GIT_ENV)
    try:
        with tempfile.TemporaryFile() as output:
            proc = subprocess.run([GIT_BINARY, "-c", f"core.hooksPath={HOOKS_PATH}", "-c", "diff.external=",
                                   "-c", "diff.trustExitCode=false", "-c", "core.quotePath=false",
                                   "-C", str(root), *args], env=env, shell=False,
                                  stdout=output, stderr=subprocess.DEVNULL, timeout=15)
            if proc.returncode or output.tell() > max_bytes:
                raise ValueError("Git operation failed or exceeded size limit")
            output.seek(0)
            return output.read(max_bytes + 1)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise ValueError("Git operation failed or timed out") from exc


def find_root(requested: Path) -> Path:
    requested = requested.resolve(strict=True)
    root = _git(requested, "rev-parse", "--show-toplevel", max_bytes=4096).decode("utf-8").strip()
    return Path(root).resolve(strict=True)


def _reject_filters(root: Path) -> None:
    local = _git(root, "config", "--local", "--list", max_bytes=65536).decode("utf-8")
    if re.search(r"(?im)^filter\.[^\n=]+\.(?:clean|smudge|process)=", local):
        raise ValueError("Repository filter commands are not permitted")
    gitdir = Path(_git(root, "rev-parse", "--absolute-git-dir", max_bytes=4096).decode().strip())
    attributes = [gitdir / "info" / "attributes"]
    pending = [root]
    inspected = 0
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                inspected += 1
                if inspected > 10000:
                    raise ValueError("Repository directory scan exceeded limit")
                if entry.name == ".git":
                    continue
                if entry.name == ".gitattributes":
                    attributes.append(Path(entry.path))
                elif entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
    for path in attributes:
        if path.is_symlink() or (path.is_file() and (
                path.stat().st_size > 65536 or re.search(
                    rb"(?i)(?:^|\s)filter\s*=", path.read_bytes()))):
            raise ValueError("Repository filter attributes are not permitted")


def _ref(root: Path, ref: str) -> str:
    if not ref or ref.startswith("-") or any(ord(c) < 32 for c in ref):
        raise ValueError("Invalid Git ref")
    return _git(root, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}",
                max_bytes=128).decode().strip()


def load_target(root: Path, path: str, target_oid: str | None) -> bytes:
    safe = check_path(root, path)
    if target_oid:
        oid = _git(root, "rev-parse", "--verify", "--end-of-options",
                   target_oid + ":" + safe, max_bytes=128).decode().strip()
        size = int(_git(root, "cat-file", "-s", oid, max_bytes=64))
        if size > 1048576:
            raise ValueError("File exceeds capture limit")
        return _git(root, "cat-file", "blob", oid, max_bytes=1048576)
    location = root / safe
    before = location.lstat()
    if not location.is_file() or location.is_symlink() or before.st_size > 1048576:
        raise ValueError("Unsafe or oversized working-tree file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(location, flags)
    with os.fdopen(descriptor, "rb") as stream:
        during = os.fstat(stream.fileno())
        data = stream.read(1048577)
    after = location.lstat()
    signature = lambda stat: (stat.st_ino, stat.st_dev, stat.st_size, stat.st_mtime_ns)
    if (location.is_symlink() or len(data) > 1048576
            or signature(before) != signature(during) or signature(before) != signature(after)):
        raise ValueError("Workspace changed during capture")
    return data


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _hunks(patch: str) -> list[Hunk]:
    found = []
    header = None
    lines = []
    for line in patch.splitlines(keepends=True):
        match = _HUNK.match(line)
        if match:
            if header:
                found.append(Hunk(**header, patch="".join(lines), added_lines=added))
            header = dict(old_start=int(match[1]), old_count=int(match[2] or 1),
                          new_start=int(match[3]), new_count=int(match[4] or 1))
            lines, added, current = [line], [], int(match[3])
        elif header:
            lines.append(line)
            if line.startswith("+"):
                added.append(current)
                current += 1
            elif line.startswith(" "):
                current += 1
    if header:
        found.append(Hunk(**header, patch="".join(lines), added_lines=added))
    return found


def _capture(root: Path, options: ReviewOptions) -> Snapshot:
    _reject_filters(root)
    head = _ref(root, "HEAD")
    if options.mode == "range":
        if not options.from_ref or not options.to_ref:
            raise ValueError("Range requires both refs")
        target = _ref(root, options.to_ref)
        base = _git(root, "merge-base", _ref(root, options.from_ref), target,
                    max_bytes=128).decode().strip()
    elif options.mode == "commit":
        target = _ref(root, options.commit_ref or "")
        parents = _git(root, "rev-list", "--parents", "-n", "1", target, max_bytes=256).decode().split()
        if len(parents) > 2:
            raise ValueError("Merge commits are not supported")
        base = parents[1] if len(parents) == 2 else EMPTY_TREE
    else:
        base, target = head, None
    diffargs = [base] + ([target] if target else [])
    raw = _git(root, "diff", "--no-ext-diff", "--no-textconv", "--no-color",
               "--raw", "--abbrev=40", "-z", "-M", *diffargs, "--")
    parts = raw.split(b"\0")
    changes = []
    total = 0
    content = {}
    i = 0
    while i < len(parts) and parts[i]:
        meta = parts[i].decode("ascii")
        match = re.fullmatch(r":([0-7]{6}) ([0-7]{6}) ([0-9a-f]{40,64}) ([0-9a-f]{40,64}) ([A-Z])(\d*)", meta)
        if not match:
            raise ValueError("Unrecognized Git change metadata")
        status = match[5]
        old = parts[i + 1].decode("utf-8")
        i += 2
        path = parts[i].decode("utf-8") if status in ("R", "C") else old
        if status in ("R", "C"):
            i += 1
        kind = "symlink" if match[2] == "120000" else "submodule" if match[2] == "160000" else "file"
        if kind == "symlink":
            if (not path or path.startswith("/") or "\\" in path or
                    any(p in ("", ".", "..") for p in path.split("/")) or
                    re.match(r"^[A-Za-z]:", path) or
                    any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in path)):
                raise ValueError("Unsafe symlink path")
        else:
            check_path(root, path)
        if status in ("R", "C"):
            check_path(root, old)
        label = {"A": "added", "D": "deleted", "R": "renamed", "C": "renamed"}.get(status, "modified")
        data = b""
        skip_read = sensitive(path) or path.split("/")[-1] in LOCKS or any(
            fnmatch.fnmatchcase(path, pattern) for pattern in options.exclude)
        if label != "deleted" and kind == "file" and not skip_read:
            if len(changes) >= 50:
                raise ValueError("More than 50 files in snapshot")
            data = load_target(root, path, target)
            total += len(data)
            if total > 5242880:
                raise ValueError("Snapshot exceeds 5 MiB")
            content[path] = data
        patch = "" if skip_read or kind != "file" else _git(
            root, "diff", "--no-ext-diff", "--no-textconv", "--no-color",
            "-U3", *diffargs, "--", path).decode("utf-8")
        changes.append(Change(path=path, old_path=old if status in ("R", "C") else None,
                              status=label, binary=b"\0" in data or "Binary files " in patch,
                              hunks=_hunks(patch), kind=kind, size=len(data)))
    if not target:
        second = _git(root, "diff", "--no-ext-diff", "--no-textconv", "--no-color",
                      "--raw", "--abbrev=40", "-z", "-M", *diffargs, "--")
        if second != raw or any(load_target(root, path, None) != data for path, data in content.items()):
            raise ValueError("Workspace changed during snapshot")
    digest = hashlib.sha256(raw)
    for change in changes:
        digest.update(change.path.encode())
        digest.update(content.get(change.path, b""))
        for hunk in change.hunks:
            digest.update(hunk.patch.encode())
    return Snapshot(mode=options.mode, base_oid=base, target_oid=target,
                    identity=digest.hexdigest(), changes=changes, target_bytes=content)


def capture_snapshot(root: Path, options: ReviewOptions) -> Snapshot:
    return _capture(root, options)
