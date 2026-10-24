"""Conservative pattern gate for outbound bytes and persisted metadata."""
import hashlib
import json
import re

from .contracts import (ApprovedPayload, Change, Checkpoint, EndpointPolicy, Excluded,
                        Redaction, RunResult, SafeDocument)
from .selection import safe_label, sensitive

VERSION = "scanner-2"
PATTERNS = (
    ("api_key", re.compile(r"(?i)\b(?:sk-[a-z0-9_-]{12,}|gh[pousr]_[a-z0-9_]{12,}|github_pat_[a-z0-9_]{12,}|AKIA[0-9A-Z]{16})\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("slack_token", re.compile(r"\bxox[bp]-(?:[A-Za-z0-9]+-){1,3}[A-Za-z0-9]{12,}\b")),
    ("stripe_live", re.compile(r"\b(?:sk_live|rk_live)_[A-Za-z0-9]{16,}\b")),
    ("google_api", re.compile(r"\bAIza[A-Za-z0-9_-]{35}\b")),
    ("database_url", re.compile(
        r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|rediss?):"
        r"//[^\s/@:'\"\\]*:[^\s/@'\"\\]+@[^\s'\"\\]+")),
    ("assignment", re.compile(r"(?i)\b(?:password|passwd|api[_-]?key|secret|token"
                              r"|aws_secret_access_key)\s*[:=]\s*['\"]?[^\s'\",;]{8,}")),
)
PRIVATE = re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----", re.I)
SUSPICIOUS = re.compile(r"(?i)\b(?:authorization\s*:\s*bearer\s+\S+|-----BEGIN [^-]*PRIVATE KEY-----)")
LOCAL_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|file://|/(?:Users|home)/[^\s]+)")


def _redact(text: str, path: str, redactions: list[Redaction],
            line_numbers: dict[int, int] | None = None) -> str:
    if PRIVATE.search(text):
        raise ValueError("private_key")
    for name, pattern in PATTERNS:
        matches = list(pattern.finditer(text))
        for match in matches:
            offset = text.count("\n", 0, match.start()) + 1
            line = line_numbers.get(offset, offset) if line_numbers else offset
            redactions.append(Redaction(path=safe_label(path), line=line,
                                        rule_id=name, action="redacted"))
        text = pattern.sub("[REDACTED]", text)
    if SUSPICIOUS.search(text):
        raise ValueError("suspicious")
    return text


def _redact_collecting(text: str, path: str, redactions: list[Redaction],
                       line_numbers: dict[int, int] | None = None) -> None:
    """Collect Redaction records without mutating text.  Raises ValueError on unsafe text."""
    if PRIVATE.search(text):
        raise ValueError("private_key")
    for name, pattern in PATTERNS:
        for match in pattern.finditer(text):
            offset = text.count("\n", 0, match.start()) + 1
            line = line_numbers.get(offset, offset) if line_numbers else offset
            redactions.append(Redaction(path=safe_label(path), line=line,
                                        rule_id=name, action="redacted"))
    if SUSPICIOUS.search(text):
        raise ValueError("suspicious")


def _apply_redactions(text: str) -> str:
    """Apply all PATTERN substitutions and raise on unsafe text (private key / suspicious)."""
    if PRIVATE.search(text):
        raise ValueError("private_key")
    for _, pattern in PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    if SUSPICIOUS.search(text):
        raise ValueError("suspicious")
    return text


def _dedup_redactions(content_records: list[Redaction],
                      patch_records: list[Redaction]) -> list[Redaction]:
    """Pair content-scan and patch-scan records by (rule_id, within-rule ordinal).

    For each rule, we have N content-scan records and M patch-scan records.
    Pair them positionally: record i from content with record i from patch if their
    file-line numbers agree.  If they agree, emit only the content-scan record (it
    always carries a true file line number).  If they disagree or one side has no
    counterpart, keep both records (fail open – losing a location is worse than noise).
    """
    from collections import defaultdict
    # Group records by rule_id, preserving ordinal order within each rule.
    def _group(records: list[Redaction]) -> dict[str, list[Redaction]]:
        groups: dict[str, list[Redaction]] = defaultdict(list)
        for r in records:
            groups[r.rule_id].append(r)
        return groups

    content_by_rule = _group(content_records)
    patch_by_rule = _group(patch_records)
    all_rules = sorted(set(list(content_by_rule) + list(patch_by_rule)))

    result: list[Redaction] = []
    for rule in all_rules:
        c_list = content_by_rule.get(rule, [])
        p_list = patch_by_rule.get(rule, [])
        n = max(len(c_list), len(p_list))
        for i in range(n):
            c = c_list[i] if i < len(c_list) else None
            p = p_list[i] if i < len(p_list) else None
            if c is not None and p is not None and c.line == p.line:
                # Confident pair: content record has the canonical file-line number.
                result.append(c)
            else:
                # Not a confident pair – keep whichever exist (fail open).
                if c is not None:
                    result.append(c)
                if p is not None:
                    result.append(p)
    return result




def sanitize_file(change: Change, content: bytes) -> SafeDocument | Excluded:
    path = change.path
    if sensitive(path):
        return Excluded(path="[sensitive path]", reason="credential_path")
    try:
        text = content.decode("utf-8")
        patch = "".join(h.patch for h in change.hunks)
        # Build patch-offset -> new-file-line map.  Only '+' and context (' ')
        # lines have a target file line; '-' lines and hunk headers do not.
        patch_lines: dict[int, int] = {}
        offset = 0
        for hunk in change.hunks:
            current = hunk.new_start
            for line in hunk.patch.splitlines(keepends=True):
                patch_lines[offset + 1] = current
                offset += 1
                if line.startswith(("+", " ")):
                    current += 1
        # Collect per-rule matches from content and patch separately so we can
        # pair them by ordinal and deduplicate without using secret values.
        content_matches: list[Redaction] = []
        patch_matches: list[Redaction] = []
        _redact_collecting(text, path, content_matches, line_numbers=None)
        _redact_collecting(patch, path, patch_matches, line_numbers=patch_lines)
        clean_content = _apply_redactions(text)
        clean_patch = _apply_redactions(patch)
        redactions = _dedup_redactions(content_matches, patch_matches)
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
        document = json.loads(text)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("Invalid request body") from exc
    if _has_residual(text) or _has_residual(document):
        raise ValueError("Request failed final privacy scan")
    return ApprovedPayload(body=body, endpoint=policy.base_url + "/chat/completions")


def _has_residual(value: object, depth: int = 0) -> bool:
    if depth > 32:
        return True
    if isinstance(value, str):
        if PRIVATE.search(value) or SUSPICIOUS.search(value) or any(
                pattern.search(value) for _, pattern in PATTERNS):
            return True
        if value.lstrip().startswith(("{", "[")):
            try:
                return _has_residual(json.loads(value), depth + 1)
            except ValueError:
                pass
        return False
    if isinstance(value, dict):
        return any(_has_residual(key, depth + 1) or _has_residual(item, depth + 1)
                   or (isinstance(key, str) and isinstance(item, str)
                       and _has_residual(f"{key} = {item}", depth + 1))
                   for key, item in value.items())
    if isinstance(value, list):
        return any(_has_residual(item, depth + 1) for item in value)
    return False


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
    if _has_residual(text) or LOCAL_PATH.search(text):
        return True
    try:
        decoded = json.loads(text)
    except ValueError:
        return False
    return _has_residual(decoded)
