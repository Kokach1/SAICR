import json
from pathlib import Path

import pytest

from fixtures.prepare_demo import CHANGED, SECRETS
from reviewdesk.contracts import Change, Hunk, Limits, ReviewOptions, Settings
from reviewdesk.messages import compose_message
from reviewdesk.packing import pack_documents
from reviewdesk.privacy import VERSION, gate_payload, sanitize_file
from reviewdesk.revisions import capture_snapshot, find_root
from reviewdesk.selection import choose_files
from reviewdesk.settings import validate_endpoint


def test_controlled_git_fixture_through_real_privacy_gate():
    root = find_root(Path(__file__).resolve().parents[1] / "fixtures" / "demo")
    snapshot = capture_snapshot(root, ReviewOptions(repo=root))
    assert [d.path for d in choose_files(snapshot, [], Limits()) if d.included] == ["example.py"]
    change = snapshot.changes[0]
    document = sanitize_file(change, snapshot.target_bytes[change.path])
    assert document.content.count("\n") == CHANGED.decode().count("\n")
    assert document.patch.count("\n") == "".join(h.patch for h in change.hunks).count("\n")
    expected_lines = {}
    for line_number, line in enumerate(CHANGED.decode().splitlines(), 1):
        for name, secret in SECRETS.items():
            if secret in line:
                expected_lines[name] = line_number
    assert len(expected_lines) == len(SECRETS)
    for name, line_number in expected_lines.items():
        assert sum(r.path == "example.py" and r.line == line_number
                   for r in document.redactions) == 2

    serialized = json.dumps(document.model_dump(exclude={"content_hash"}))
    bundle = pack_documents([document], Limits())[0]
    draft = compose_message(bundle, Settings(model="offline-inspection"))
    body = json.dumps(draft.body, ensure_ascii=True).encode()
    policy = validate_endpoint(Settings(base_url="http://localhost:11434", model="offline-inspection",
                                        allow_loopback_http=True))
    approved = gate_payload(body, policy)
    for secret in SECRETS.values():
        assert secret not in document.content + document.patch + serialized
        assert secret.encode() not in approved.body
    for keep in ("a" * 40, "b" * 64, "ordinary prose", "token_url"):
        assert keep in document.content and keep in serialized
    assert "\\n" in serialized
    assert VERSION == "scanner-2"


@pytest.mark.parametrize("name,secret", [
    *SECRETS.items(),
    ("slack_user", "xoxp-000000000000-000000000000-FAKEFAKEFAKEFAKEFAKEFAKE"),
    ("mysql", "mysql://demo:FAKEPASSWORD123@localhost/demo"),
    ("mongodb", "mongodb://demo:FAKEPASSWORD123@localhost/demo"),
    ("redis", "redis://:FAKEPASSWORD123@localhost/0"),
], ids=[*SECRETS, "slack_user", "mysql", "mongodb", "redis"])
def test_residual_secret_is_rejected_by_real_gate(name, secret):
    policy = validate_endpoint(Settings(base_url="http://localhost:11434", model="offline-inspection",
                                        allow_loopback_http=True))
    sample = f"aws_secret_access_key = '{secret}'" if name == "aws" else secret
    with pytest.raises(ValueError, match="privacy scan"):
        gate_payload(json.dumps({"content": sample}).encode(), policy)
    text = f"before\n{sample}\nafter\n".encode()
    change = Change(path="example.py", status="added", hunks=[
        Hunk(old_start=0, old_count=0, new_start=1, new_count=3,
             patch=f"@@ -0,0 +1,3 @@\n+before\n+{sample}\n+after\n",
             added_lines=[1, 2, 3])])
    document = sanitize_file(change, text)
    assert secret not in document.content + document.patch
    assert document.content.count("\n") == text.count(b"\n")
    assert all(redaction.line == 2 for redaction in document.redactions)


def test_gate_checks_decoded_json_string_and_contextual_key():
    policy = validate_endpoint(Settings(base_url="http://localhost:11434", model="offline-inspection",
                                        allow_loopback_http=True))
    secret = SECRETS["aws"]
    for residual in ({"content": f'aws_secret_access_key = "{secret}"'},
                     {"aws_secret_access_key": secret},
                     {"content": SECRETS["database"]},
                     {"messages": [{"content": json.dumps({
                         "documents": [{"content": f'aws_secret_access_key = "{secret}"'}]})}]}):
        with pytest.raises(ValueError, match="privacy scan"):
            gate_payload(json.dumps(residual).replace("/", "\\/").encode(), policy)
