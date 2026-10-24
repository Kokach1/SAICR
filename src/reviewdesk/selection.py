"""Path boundaries and deterministic pre-context decisions."""
import fnmatch
from pathlib import Path, PurePosixPath
import re
from collections.abc import Sequence

from .contracts import Decision, Limits, Snapshot

LOCKS = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "go.sum", "poetry.lock"}


def check_path(root: Path, candidate: str) -> str:
    if (not candidate or "\\" in candidate or candidate.startswith("/")
            or re.match(r"^[A-Za-z]:", candidate)
            or any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in candidate)):
        raise ValueError("Unsafe path")
    try:
        candidate.encode("utf-8", "strict")
    except UnicodeError as exc:
        raise ValueError("Invalid path encoding") from exc
    parts = PurePosixPath(candidate).parts
    if any(p in ("", ".", "..") for p in candidate.split("/")) or str(PurePosixPath(candidate)) != candidate:
        raise ValueError("Noncanonical path")
    current = root.resolve()
    for part in parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlink ancestor")
    if (root / candidate).is_symlink() or not (root / candidate).resolve().is_relative_to(root.resolve()):
        raise ValueError("Path escapes repository")
    return candidate


def sensitive(path: str) -> bool:
    parts = path.lower().split("/")
    base = parts[-1]
    return (bool(re.search(r"(?i)(?:sk-[a-z0-9_-]{12,}|gh[pousr]_[a-z0-9_]{12,}|AKIA[0-9A-Z]{16}"
                           r"|\b(?:password|passwd|api[_-]?key|secret|token)\s*[:=]\s*[^\s/]{8,})", path))
            or any(p in (".aws", ".ssh") or p.startswith("credentials") or p.startswith("secrets")
                for p in parts) or base == ".env" or base.startswith(".env.")
            or base.endswith((".pem", ".key", ".p12", ".pfx", ".keystore"))
            or base.startswith("id_rsa"))


def safe_label(path: str) -> str:
    return "[sensitive path]" if sensitive(path) else path


def choose_files(snapshot: Snapshot, excludes: Sequence[str], limits: Limits) -> list[Decision]:
    result = []
    total = count = 0
    for change in snapshot.changes:
        path = change.path
        reason = ("credential_path" if sensitive(path) else "deleted" if change.status == "deleted"
                  else "special_file" if change.kind != "file" else "binary" if change.binary
                  else "lockfile" if path.split("/")[-1] in LOCKS
                  else "excluded" if any(fnmatch.fnmatchcase(path, g) for g in excludes)
                  else "limit" if change.size > limits.max_file_bytes or count >= limits.max_files
                  or total + change.size > limits.max_total_bytes else "included")
        result.append(Decision(path=safe_label(path), included=reason == "included", reason=reason))
        if reason == "included":
            total += change.size
            count += 1
    return result
