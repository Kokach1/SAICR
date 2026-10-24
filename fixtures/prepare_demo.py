"""Recreate the synthetic Git fixture if its nested .git directory is missing."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent / "demo"
BASE = b"def divide(a, b):\n    return a / b\n"
PREVIOUS = BASE + b"\nresult = divide(10, 0)\n"
SECRETS = {
    "jwt": "eyJhbGciOiJIUzI1NiJ9" + "." + "eyJ0ZXN0IjoiZHVtbXkifQ" + "." + "ZHVtbXktc2lnbmF0dXJlMTIz",
    "slack": "xo" + "xb-" + "000000000000-000000000000-" + "FAKE" * 6,
    "stripe": "sk" + "_live_" + "FAKE" * 6,
    "stripe_restricted": "rk" + "_live_" + "FAKE" * 6,
    "google": "AIza" + "FAKE" * 8 + "ABC",
    "database": "postgres://demo:FAKEPASSWORD123@localhost/demo",
    "aws": "FAKE" * 10,
}
CHANGED = (PREVIOUS.decode() + "\nitems = [1]\nresult_2 = items[2]\n"
           + "\n".join(f'{name}_fixture = "{value}"' if name != "aws"
                       else f'aws_secret_access_key = "{value}"'
                       for name, value in SECRETS.items())
           + '\ngit_sha = "' + "a" * 40 + '"\n'
           + 'hex_digest = "' + "b" * 64 + '"\n'
           + 'token_url = "https://example.invalid/path"\n'
           + '# ordinary prose stays as data\n').encode()


def git(*args):
    hooks_path = "NUL" if os.name == "nt" else "/dev/null"
    subprocess.run(["git", "-c", f"core.hooksPath={hooks_path}", "-C", str(ROOT), *args],
                   check=True, timeout=15)


def main():
    ROOT.mkdir(exist_ok=True)
    example = ROOT / "example.py"
    if (ROOT / ".git").exists():
        if example.read_bytes() == PREVIOUS:
            example.write_bytes(CHANGED)
        elif example.read_bytes() != CHANGED:
            raise ValueError("Fixture has unexpected content; refusing to replace it")
        print("Controlled Git fixture ready")
        return
    if example.exists() and example.read_bytes() not in (PREVIOUS, CHANGED):
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
