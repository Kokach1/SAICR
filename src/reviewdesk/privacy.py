"""Conservative pattern gate for outbound bytes and persisted metadata."""
import hashlib
import json
import re

from .contracts import (ApprovedPayload, Change, Checkpoint, EndpointPolicy, Excluded,
                        Redaction, RunResult, SafeDocument)
from .selection import safe_label, sensitive

VERSION = "scanner-1"
PATTERNS = (
    ("api_key", re.compile(r"(?i)\b(?:sk-[a-z0-9_-]{12,}|gh[pousr]_[a-z0-9_]{12,}|github_pat_[a-z0-9_]{12,}|AKIA[0-9A-Z]{16})\b")),
    ("assignment", re.compile(r"(?i)\b(?:password|passwd|api[_-]?key|secret|token)\s*[:=]\s*['\"]?[^\s'\",;]{8,}")),
)
PRIVATE = re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----", re.I)
SUSPICIOUS = re.compile(r"(?i)\b(?:authorization\s*:\s*bearer\s+\S+|-----BEGIN [^-]*PRIVATE KEY-----)")
LOCAL_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|file://|/(?:Users|home)/[^\s]+)")


def _redact(text: str, path: str, redactions: list[Redaction]) -> str:
    if PRIVATE.search(text):
        raise ValueError("private_key")
    for name, pattern in PATTERNS:
        matches = list(pattern.finditer(text))
        for match in matches:
            line = text.count("\n", 0, match.start()) + 1
            redactions.append(Redaction(path=safe_label(path), line=line,
                                        rule_id=name, action="redacted"))
        text = pattern.sub("[REDACTED]", text)
    if SUSPICIOUS.search(text):
        raise ValueError("suspicious")
    return text


def sanitize_file(change: Change, content: bytes) -> SafeDocument | Excluded:
    path = change.path
    if sensitive(path):
        return Excluded(path="[sensitive path]", reason="credential_path")
    try:
        text = content.decode("utf-8")
        patch = "".join(h.patch for h in change.hunks)
        redactions: list[Redaction] = []
        clean_content = _redact(text, path, redactions)
        clean_patch = _redact(patch, path, redactions)
    except (UnicodeError, ValueError):
        return Excluded(path=safe_label(path), reason="unsafe_content")
    return SafeDocument(path=path, content=clean_content, patch=clean_patch,
                        content_hash=hashlib.sha256(content).hexdigest(),
                        line_count=len(text.splitlines()), added_lines=sorted(set(
                            line for h in change.hunks for line in h.added_lines)),
                        redactions=redactions)


def gate_payload(body: bytes, policy: EndpointPolicy) -> ApprovedPayload:
    if not policy.upload_permitted or len(body) > 307200:
        raise ValueError("Request not approved or too large")
    try:
        text = body.decode("utf-8")
        json.loads(text)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("Invalid request body") from exc
    if PRIVATE.search(text) or SUSPICIOUS.search(text) or any(p.search(text) for _, p in PATTERNS):
        raise ValueError("Request failed final privacy scan")
    return ApprovedPayload(body=body, endpoint=policy.base_url + "/chat/completions")


def sanitize_output(value: RunResult | Checkpoint) -> RunResult | Checkpoint:
    if isinstance(value, Checkpoint):
        updates = []
        for state in value.bundle_states:
            findings = [f for f in state.findings if not _unsafe(f.model_dump_json())]
            updates.append(state.model_copy(update={"findings": findings,
                "status": "failed" if len(findings) != len(state.findings) else state.status,
                "error_code": "unsafe_output" if len(findings) != len(state.findings)
                or _unsafe(state.error_code or "") else state.error_code}))
        return value.model_copy(update={"bundle_states": updates,
                                        "complete": value.complete and all(
                                            item.status == "done" for item in updates)})
    findings = [f for f in value.findings if not _unsafe(f.model_dump_json())]
    rejected = len(value.findings) - len(findings)
    return value.model_copy(update={"findings": findings, "partial": value.partial or bool(rejected),
                                     "warnings": [w for w in value.warnings if not _unsafe(w)] +
                                     (["Unsafe generated finding rejected"] if rejected else [])})


def _unsafe(text: str) -> bool:
    return bool(PRIVATE.search(text) or SUSPICIOUS.search(text) or LOCAL_PATH.search(text)
                or any(p.search(text) for _, p in PATTERNS))
