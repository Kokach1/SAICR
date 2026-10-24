"""Recreate the synthetic Git fixture if its nested .git directory is missing."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent / "demo"
BASE = b"def divide(a, b):\n    return a / b\n"
CHANGED = BASE + b"\nresult = divide(10, 0)\n"


def git(*args):
    subprocess.run(["git", "-c", "core.hooksPath=NUL", "-C", str(ROOT), *args],
                   check=True, timeout=15)


def main():
    ROOT.mkdir(exist_ok=True)
    if (ROOT / ".git").exists():
        print("Synthetic fixture already initialized")
        return
    example = ROOT / "example.py"
    if example.exists() and example.read_bytes() != CHANGED:
        raise ValueError("Fixture has unexpected content; refusing to replace it")
    git("init", "-q")
    example.write_bytes(BASE)
    git("add", "example.py")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "fixture baseline")
    example.write_bytes(CHANGED)
    print("Synthetic fixture initialized with one tracked workspace change")


if __name__ == "__main__":
    main()
