"""Real-pipeline tests using controlled input data; no network, no mocked provider.

FIX 1: test_controlled_git_fixture_through_real_privacy_gate now uses the demo_repo
conftest fixture (builds the controlled git repo in tmp_path) so it passes on a fresh
clone without running fixtures/prepare_demo.py first.

FIX 2: test_gate_rejection_state_is_persisted exercises the real _update/save_state
persistence functions on a real checkpoint directory in tmp_path; no monkeypatching of
the provider or scanner. Verified by function-level real execution (not CLI-level,
because a safe CLI-level trigger for the gate ValueError path requires either an
oversized request body or a policy with upload_permitted=False, which cannot be
constructed from the normal public API without additional plumbing outside this test).

FIX 5: Assertions updated to ==1 redaction per location; new multi-occurrence and
multi-line real-execution checks added.
"""
import importlib.util
import json
from pathlib import Path

import pytest

from reviewdesk.checkpoints import load_state, save_state
from reviewdesk.contracts import (BundleState, Change, Checkpoint, ErrorRecord, Hunk,
                                  Limits, ReviewOptions, Settings)
from reviewdesk.messages import compose_message
from reviewdesk.packing import pack_documents
from reviewdesk.privacy import VERSION, gate_payload, sanitize_file
from reviewdesk.revisions import capture_snapshot, find_root
from reviewdesk.runner import _record_gate_rejection
from reviewdesk.selection import choose_files
from reviewdesk.settings import validate_endpoint


# ---------------------------------------------------------------------------
# Module-level import of SECRETS constants for parametrize (no side-effects).
# prepare_demo.main() is NOT called here; we only need the constant dict.
# ---------------------------------------------------------------------------
_pdemo_spec = importlib.util.spec_from_file_location(
    "prepare_demo_const", Path(__file__).resolve().parents[1] / "fixtures" / "prepare_demo.py"
)
_pdemo = importlib.util.module_from_spec(_pdemo_spec)
_pdemo_spec.loader.exec_module(_pdemo)
_SECRETS = _pdemo.SECRETS
del _pdemo_spec, _pdemo


# ---------------------------------------------------------------------------
# FIX 1: self-sufficient controlled fixture test
# ---------------------------------------------------------------------------

def test_controlled_git_fixture_through_real_privacy_gate(demo_repo):
    """End-to-end test using a controlled git fixture built in tmp_path.

    Uses the demo_repo conftest fixture so this test is self-sufficient on a
    fresh clone; no prior run of fixtures/prepare_demo.py is required.
    """
    root, module = demo_repo
    SECRETS = module.SECRETS
    CHANGED = module.CHANGED

    git_root = find_root(root)
    snapshot = capture_snapshot(git_root, ReviewOptions(repo=git_root))
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
    # FIX 5: one record per occurrence (was incorrectly ==2 before deduplication fix).
    for name, line_number in expected_lines.items():
        count = sum(r.path == "example.py" and r.line == line_number
                    for r in document.redactions)
        assert count == 1, (
            f"Expected 1 redaction record for {name} at line {line_number}, got {count}; "
            f"records: {[(r.rule_id, r.line) for r in document.redactions]}"
        )

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


# ---------------------------------------------------------------------------
# Residual-secret gate rejection tests (parametrized)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,secret", [
    *_SECRETS.items(),
    ("slack_user", "xo" + "xp-" + "000000000000-000000000000-" + "FAKE" * 6),
    ("mysql", "mysql://demo:FAKEPASSWORD123@localhost/demo"),
    ("mongodb", "mongodb://demo:FAKEPASSWORD123@localhost/demo"),
    ("redis", "redis://:FAKEPASSWORD123@localhost/0"),
], ids=[*_SECRETS, "slack_user", "mysql", "mongodb", "redis"])
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
    # FIX 5: one record per location.
    assert all(redaction.line == 2 for redaction in document.redactions)
    assert len(document.redactions) == 1, (
        f"Expected 1 redaction record, got {len(document.redactions)}: "
        f"{[(r.rule_id, r.line) for r in document.redactions]}"
    )


def test_gate_checks_decoded_json_string_and_contextual_key():
    policy = validate_endpoint(Settings(base_url="http://localhost:11434", model="offline-inspection",
                                        allow_loopback_http=True))
    secret = _SECRETS["aws"]
    for residual in ({"content": f'aws_secret_access_key = "{secret}"'},
                     {"aws_secret_access_key": secret},
                     {"content": _SECRETS["database"]},
                     {"messages": [{"content": json.dumps({
                         "documents": [{"content": f'aws_secret_access_key = "{secret}"'}]})}]}):
        with pytest.raises(ValueError, match="privacy scan"):
            gate_payload(json.dumps(residual).replace("/", "\\/").encode(), policy)


# ---------------------------------------------------------------------------
# FIX 5 edge-case tests: multi-occurrence and multi-line deduplication
# ---------------------------------------------------------------------------

def test_two_same_class_secrets_on_one_line_produce_two_records():
    """Two distinct stripe-live secrets on a single line must yield two separate records."""
    s1 = "sk" + "_live_" + "FIRST" * 5
    s2 = "rk" + "_live_" + "SECOND" * 4
    line = f"{s1} and {s2}"
    content = (line + "\n").encode()
    change = Change(path="two.py", status="added", hunks=[
        Hunk(old_start=0, old_count=0, new_start=1, new_count=1,
             patch=f"@@ -0,0 +1 @@\n+{line}\n",
             added_lines=[1])])
    doc = sanitize_file(change, content)
    assert s1 not in doc.content + doc.patch
    assert s2 not in doc.content + doc.patch
    stripe_records = [r for r in doc.redactions if r.rule_id == "stripe_live"]
    assert len(stripe_records) == 2, (
        f"Expected 2 stripe_live records for two secrets on one line, got {len(stripe_records)}"
    )
    assert all(r.line == 1 for r in stripe_records)


def test_same_secret_on_two_lines_produces_two_records():
    """The same secret appearing on two different lines must yield two separate records."""
    secret = "sk" + "_live_" + "SAME" * 6
    content = f"line_a = '{secret}'\nline_b = '{secret}'\n".encode()
    change = Change(path="twolines.py", status="added", hunks=[
        Hunk(old_start=0, old_count=0, new_start=1, new_count=2,
             patch=(f"@@ -0,0 +1,2 @@\n+line_a = '{secret}'\n+line_b = '{secret}'\n"),
             added_lines=[1, 2])])
    doc = sanitize_file(change, content)
    assert secret not in doc.content + doc.patch
    stripe_records = [r for r in doc.redactions if r.rule_id == "stripe_live"]
    assert len(stripe_records) == 2, (
        f"Expected 2 records for the same secret on two lines, got {len(stripe_records)}"
    )
    assert {r.line for r in stripe_records} == {1, 2}


def test_interleaved_rules_produce_records_ordered_by_line():
    """Secrets matching different rule classes must be ordered by (path, line), not rule name.

    stripe_live (rule 's') on line 1 and google_api (rule 'g') on line 2:
    alphabetical rule order would emit line 2 then line 1;
    correct file/location ordering must emit line 1 then line 2.
    """
    secret_stripe = "sk" + "_live_" + "1234567890ABCDEF"
    secret_google = "AIza" + "G" * 35
    line1 = f"s_live = '{secret_stripe}'"
    line2 = f"g_api = '{secret_google}'"
    content = f"{line1}\n{line2}\n".encode()
    change = Change(path="interleaved.py", status="added", hunks=[
        Hunk(old_start=0, old_count=0, new_start=1, new_count=2,
             patch=f"@@ -0,0 +1,2 @@\n+{line1}\n+{line2}\n",
             added_lines=[1, 2])])
    doc = sanitize_file(change, content)
    assert secret_stripe not in doc.content + doc.patch
    assert secret_google not in doc.content + doc.patch
    assert len(doc.redactions) == 2
    assert [r.line for r in doc.redactions] == [1, 2]
    assert [r.rule_id for r in doc.redactions] == ["stripe_live", "google_api"]


# ---------------------------------------------------------------------------
# FIX 1: Gate-rejection checkpoint persistence (production helper execution)
# ---------------------------------------------------------------------------
# Verification route: function-level real execution of the production helper.
# A CLI-level trigger for the gate ValueError path requires either (a) an oversized
# request body (>307200 bytes) or (b) a policy with upload_permitted=False.
# Neither is safely constructible from the current public API without additional
# plumbing: oversized files are excluded at selection, packing caps bundles below
# the gate limit, and upload_permitted=False fails endpoint validation.
# Therefore, runner.py extracts the gate rejection sequence into _record_gate_rejection,
# and this test exercises that exact production helper directly on a real Checkpoint.

def test_gate_rejection_state_is_persisted(tmp_path):
    """Verify that _record_gate_rejection persists the privacy_gate failed status.

    Function-level real-execution check. Calls the production _record_gate_rejection
    helper (which runner.py calls in its except ValueError block) against a real
    Checkpoint in tmp_path. Verifies both the ErrorRecord appending and durable
    persistence via save_state / load_state round-trip.
    """
    state = Checkpoint(
        format_version="1",
        run_id="d" * 32,
        run_key="test_key",
        snapshot_identity="snap",
        bundle_states=[BundleState(id="bundle-001", status="pending")],
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )
    cache = tmp_path / "cache"

    # Save initial pending state.
    save_state(cache, state)
    loaded = load_state(cache, state.run_id, "test_key")
    assert loaded.bundle_states[0].status == "pending"
    assert loaded.bundle_states[0].error_code is None

    # Call production _record_gate_rejection helper.
    errors: list[ErrorRecord] = []
    item = state.bundle_states[0]
    updated_state = _record_gate_rejection(errors, state, cache, 0, item, "bundle-001")

    # Assert error record was appended.
    assert len(errors) == 1
    assert errors[0].code == "privacy_gate"
    assert errors[0].message == "Request blocked by privacy gate"
    assert errors[0].bundle_id == "bundle-001"

    # Reload from disk and verify durable persistence.
    reloaded = load_state(cache, state.run_id, "test_key")
    assert reloaded.bundle_states[0].status == "failed"
    assert reloaded.bundle_states[0].error_code == "privacy_gate"
    assert updated_state.bundle_states[0].status == "failed"
    assert updated_state.bundle_states[0].error_code == "privacy_gate"

