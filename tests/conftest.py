import importlib.util
import subprocess
from pathlib import Path

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


@pytest.fixture
def demo_repo(tmp_path):
    """Build the controlled demo git fixture in tmp_path/demo using prepare_demo logic."""
    source = Path(__file__).resolve().parents[1] / "fixtures" / "prepare_demo.py"
    spec = importlib.util.spec_from_file_location("prepare_demo", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    demo_root = tmp_path / "demo"
    module_root_orig = module.ROOT
    module.ROOT = demo_root
    try:
        module.main()
    finally:
        module.ROOT = module_root_orig
    return demo_root, module
