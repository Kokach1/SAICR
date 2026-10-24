"""Locations are checked against immutable target lines and added lines."""
from collections.abc import Sequence

from .contracts import Bundle, Finding, ValidationOutcome


def validate_locations(findings: Sequence[Finding], bundle: Bundle) -> ValidationOutcome:
    docs = {d.path: d for d in bundle.documents}
    errors = []
    for finding in findings:
        doc = docs.get(finding.path)
        if not doc:
            errors.append("unknown_path")
        elif finding.start_line > finding.end_line or finding.end_line > doc.line_count:
            errors.append("invalid_range")
        elif not any(finding.start_line <= n <= finding.end_line for n in doc.added_lines):
            errors.append("not_added_line")
    return ValidationOutcome(valid=not errors, findings=list(findings) if not errors else [],
                             errors=sorted(set(errors)))


def deduplicate(findings: Sequence[Finding]) -> list[Finding]:
    unique = {f.model_dump_json(): f for f in findings}
    return sorted(unique.values(), key=lambda f: (f.path, f.start_line, f.severity, f.title))
