import subprocess

import pytest


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL).decode().strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "target"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Fixture")
    (root / "main.py").write_bytes(b"one = 1\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "base")
    return root
