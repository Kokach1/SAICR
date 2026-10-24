"""Private, locked and atomic state; a running attempt is not reusable."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading

from .contracts import Checkpoint, Settings, Snapshot
from .messages import VERSION as PROMPT_VERSION
from .privacy import VERSION as SCANNER_VERSION, sanitize_output

VERSION = "1"
RUN_ID = re.compile(r"^[a-f0-9]{32}$")
_THREAD_LOCK = threading.Lock()


class CheckpointWriteError(OSError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def cache_dir() -> Path:
    parent = os.environ.get("LOCALAPPDATA") if os.name == "nt" else os.environ.get("XDG_CACHE_HOME")
    return Path(os.environ.get("REVIEWDESK_CACHE_DIR") or
                (Path(parent) if parent else Path.home() / ".cache") / "reviewdesk" / "runs")


def make_run_key(snapshot: Snapshot, config: Settings, bundle_ids: list[str]) -> str:
    obj = {"snapshot": snapshot.identity, "base": snapshot.base_oid, "target": snapshot.target_oid,
           "bundles": bundle_ids, "config": config.model_dump(exclude={"api_key", "retry_uncertain"}),
           "prompt": PROMPT_VERSION, "scanner": SCANNER_VERSION, "schema": VERSION}
    raw = json.dumps(obj, sort_keys=True, default=str, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


@contextmanager
def _lock(cache: Path):
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    with _THREAD_LOCK, (cache / ".lock").open("a+b") as stream:
        stream.seek(0)
        if not stream.read(1):
            stream.write(b"0")
            stream.flush()
            stream.seek(0)
        else:
            stream.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def save_state(cache: Path, state: Checkpoint) -> None:
    if not RUN_ID.fullmatch(state.run_id):
        raise ValueError("Unsafe run ID")
    state = sanitize_output(state)
    raw = state.model_dump_json().encode()
    if len(raw) > 1048576:
        raise ValueError("State too large")
    try:
        with _lock(cache):
            fd, name = tempfile.mkstemp(prefix=".state-", dir=cache)
            try:
                os.chmod(name, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(name, cache / (state.run_id + ".json"))
            finally:
                if os.path.exists(name):
                    os.unlink(name)
    except OSError as exc:
        raise CheckpointWriteError("Checkpoint write failed") from exc


def load_state(cache: Path, run_id: str, expected_key: str) -> Checkpoint:
    if not RUN_ID.fullmatch(run_id):
        raise ValueError("Unsafe run ID")
    with _lock(cache):
        path = cache / (run_id + ".json")
        if path.is_symlink() or path.stat().st_size > 1048576:
            raise ValueError("Unsafe or oversized state")
        state = Checkpoint.model_validate_json(path.read_bytes())
    if state.format_version != VERSION or state.run_id != run_id or state.run_key != expected_key:
        raise ValueError("Checkpoint does not match current review")
    return state.model_copy(update={"bundle_states": [
        s.model_copy(update={"status": "uncertain"}) if s.status == "running" else s
        for s in state.bundle_states]})
