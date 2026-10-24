from argparse import Namespace
from pathlib import Path
import json

import pytest
from pydantic import ValidationError

from reviewdesk.contracts import (Change, Finding, Hunk, Limits, ReviewOptions, Settings,
                                  Snapshot, parse_findings)
from reviewdesk.packing import pack_documents
from reviewdesk.privacy import gate_payload, sanitize_file
from reviewdesk.revisions import capture_snapshot, find_root, load_target
from reviewdesk.selection import check_path, choose_files
from reviewdesk.settings import load_settings, validate_endpoint
from conftest import git


def finding(**changes):
    return dict(path="main.py", start_line=2, end_line=2, category="bug",
                severity="high", title="Defect", explanation="Broken behavior",
                suggestion=None) | changes


def test_t01_strict_settings():
    assert parse_findings('{"findings": []}') == []
    for data in ('not json', '{"findings":[],"extra":1}',
                 json.dumps({"findings": [finding(start_line=True)]}),
                 json.dumps({"findings": [finding(extra="bad")]})):
        with pytest.raises((ValueError, ValidationError)):
            parse_findings(data)
    args = Namespace(command="preview")
    assert not load_settings(args, {}).model
    with pytest.raises(ValueError):
        load_settings(Namespace(command="review"), {})
    config = Settings(model="m", base_url="https://example.invalid", allow_hosted_upload=True)
    assert validate_endpoint(config).upload_permitted
    for url in ("http://example.invalid", "https://user:pass@example.invalid",
                "https://example.invalid/?key=123", "https://example.invalid/#x"):
        with pytest.raises(ValueError):
            validate_endpoint(config.model_copy(update={"base_url": url}))
    with pytest.raises(ValueError):
        validate_endpoint(Settings(model="m", base_url="http://localhost:8080"))
    key = load_settings(Namespace(command="review", base_url="https://example.invalid",
                                  model="m"), {"LLM_API_KEY": "synthetic-test-only"})
    assert "synthetic-test-only" not in repr(key) + key.model_dump_json()


def test_t02_workspace_and_historical(repo):
    (repo / "main.py").write_bytes(b"one = 1\ntwo = 2\n")
    git(repo, "add", "main.py")
    (repo / "main.py").write_bytes(b"one = 1\ntwo = 2\nthree = 3\n")
    (repo / "untracked.py").write_text("no = 1\n")
    snap = capture_snapshot(find_root(repo), ReviewOptions(repo=repo))
    assert [c.path for c in snap.changes] == ["main.py"]
    assert set(snap.changes[0].hunks[0].added_lines) == {2, 3}
    assert snap.target_bytes["main.py"].endswith(b"three = 3\n")
    root_commit = git(repo, "rev-list", "--max-parents=0", "HEAD")
    root = capture_snapshot(repo, ReviewOptions(repo=repo, mode="commit", commit_ref=root_commit))
    assert root.changes[0].status == "added"
    historical = capture_snapshot(repo, ReviewOptions(repo=repo, mode="commit", commit_ref="HEAD"))
    assert historical.target_bytes["main.py"] == b"one = 1\n"
    assert load_target(repo, "main.py", historical.target_oid) == b"one = 1\n"


def test_t02_range_and_rename(repo):
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-qb", "side")
    (repo / "side.py").write_text("side = 1\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "side")
    side = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-")
    git(repo, "mv", "main.py", "new name.py")
    (repo / "new name.py").write_bytes(b"one = 1\ntwo = 2\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "rename")
    target = git(repo, "rev-parse", "HEAD")
    snap = capture_snapshot(repo, ReviewOptions(repo=repo, mode="range",
                                                from_ref=side, to_ref=target))
    assert snap.base_oid == base
    assert snap.changes[0].path == "new name.py"
    assert snap.target_bytes["new name.py"].endswith(b"two = 2\n")
    with pytest.raises(ValueError):
        capture_snapshot(repo, ReviewOptions(repo=repo, mode="commit", commit_ref="--bad"))


def test_t04_paths_and_choices(repo):
    for path in ("../x", "/x", "C:/x", "a//b", "a/../b", "x\x00y", "x\ud800", "a\\b"):
        with pytest.raises(ValueError):
            check_path(repo, path)
    (repo / "link").symlink_to(repo, target_is_directory=True)
    with pytest.raises(ValueError):
        check_path(repo, "link/secret.py")
    changes = [Change(path=p, status="modified", size=2, binary=binary, kind=kind)
               for p, binary, kind in [(".env", False, "file"), ("a.key", False, "file"),
                                       ("password=fakepassword123.py", False, "file"),
                                       ("poetry.lock", False, "file"), ("binary", True, "file"),
                                       ("special", False, "submodule"), ("a.py", False, "file")]]
    decisions = choose_files(Snapshot(mode="workspace", base_oid="a", target_oid=None,
                                      identity="x", changes=changes), ["*.py"], Limits())
    assert [d.reason for d in decisions] == ["credential_path", "credential_path", "credential_path",
                                                "lockfile", "binary", "special_file", "excluded"]
    assert "a.key" not in [d.path for d in decisions]
    assert "fakepassword123" not in repr(decisions)


def test_t05_t06_redaction_and_packing():
    change = Change(path="x.py", status="added", hunks=[Hunk(
        old_start=0, old_count=0, new_start=1, new_count=2,
        patch="+password = fakepassword123\n+safe = 1\n", added_lines=[1, 2])])
    doc = sanitize_file(change, b"password = fakepassword123\nsafe = 1\n")
    assert doc.line_count == 2
    assert "fakepassword123" not in doc.content + doc.patch
    assert len(doc.redactions) == 2
    assert sanitize_file(change, b"-----BEGIN PRIVATE KEY-----\nsynthetic\n").reason == "unsafe_content"
    bundle = pack_documents([doc], Limits())[0]
    assert bundle == pack_documents([doc], Limits())[0]
    with pytest.raises(ValueError):
        pack_documents([doc], Limits(max_bundle_code_bytes=1))
    from reviewdesk.contracts import EndpointPolicy
    with pytest.raises(ValueError):
        gate_payload(b'{"token":"sk-fakeabcdefgh12345678"}',
                     EndpointPolicy(base_url="http://localhost", loopback=True, upload_permitted=True))


def test_t02_merge_rejected_and_credential_not_read(repo, monkeypatch):
    git(repo, "checkout", "-qb", "side")
    (repo / "side.py").write_bytes(b"side = 1\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "side")
    git(repo, "checkout", "-q", "-")
    (repo / "main.py").write_bytes(b"one = 2\n")
    git(repo, "commit", "-qam", "main")
    git(repo, "merge", "--no-edit", "side")
    with pytest.raises(ValueError, match="Merge commits"):
        capture_snapshot(repo, ReviewOptions(repo=repo, mode="commit", commit_ref="HEAD"))
    (repo / ".env").write_bytes(b"password = fakepassword123\n")
    git(repo, "add", ".env")
    original = __import__("reviewdesk.revisions", fromlist=["load_target"]).load_target
    def guarded(root, path, target):
        assert path != ".env"
        return original(root, path, target)
    monkeypatch.setattr("reviewdesk.revisions.load_target", guarded)
    snap = capture_snapshot(repo, ReviewOptions(repo=repo))
    assert ".env" not in snap.target_bytes
    assert any(d.reason == "credential_path" for d in choose_files(snap, [], Limits()))


def test_t03_workspace_race_detected(repo, monkeypatch):
    (repo / "main.py").write_bytes(b"one = 2\n")
    from reviewdesk import revisions
    original = revisions.load_target
    calls = []
    def changing(root, path, target):
        result = original(root, path, target)
        calls.append(1)
        if len(calls) == 1:
            (root / path).write_bytes(b"one = 3\n")
        return result
    monkeypatch.setattr(revisions, "load_target", changing)
    with pytest.raises(ValueError, match="changed"):
        capture_snapshot(repo, ReviewOptions(repo=repo))


def test_t04_git_symlink_and_submodule_are_skipped(repo):
    (repo / "linked.py").symlink_to(repo / "main.py")
    git(repo, "add", "linked.py")
    git(repo, "update-index", "--add", "--cacheinfo",
        "160000," + git(repo, "rev-parse", "HEAD") + ",submodule")
    git(repo, "commit", "-qm", "special entries")
    snap = capture_snapshot(repo, ReviewOptions(repo=repo, mode="commit", commit_ref="HEAD"))
    decisions = choose_files(snap, [], Limits())
    assert {d.path: d.reason for d in decisions} == {
        "linked.py": "special_file", "submodule": "special_file"}


def test_t02_git_filter_is_rejected_without_execution(repo):
    git(repo, "config", "filter.bad.clean", "synthetic-command-that-must-not-run")
    with pytest.raises(ValueError, match="filter"):
        capture_snapshot(repo, ReviewOptions(repo=repo))


def test_t02_recreate_demo_fixture(tmp_path, monkeypatch):
    import importlib.util
    source = Path(__file__).resolve().parents[1] / "fixtures" / "prepare_demo.py"
    spec = importlib.util.spec_from_file_location("prepare_demo", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path / "demo")
    module.main()
    snap = capture_snapshot(module.ROOT, ReviewOptions(repo=module.ROOT, preview=True))
    assert [c.path for c in snap.changes] == ["example.py"]
