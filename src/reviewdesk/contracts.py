"""Strict records shared across the review pipeline."""
import json
from datetime import datetime, timezone, date
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictInt, field_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Finding(Record):
    path: str = Field(min_length=1, max_length=512)
    start_line: StrictInt = Field(ge=1)
    end_line: StrictInt = Field(ge=1)
    category: Literal["bug", "security", "performance", "test", "maintainability", "other"]
    severity: Literal["critical", "high", "medium", "low"]
    title: str = Field(min_length=1, max_length=160)
    explanation: str = Field(min_length=1, max_length=2000)
    suggestion: str | None = Field(max_length=4000)


class FindingsEnvelope(Record):
    findings: list[Finding] = Field(max_length=30)


def parse_findings(text: str) -> list[Finding]:
    return FindingsEnvelope.model_validate(json.loads(text)).findings


class PriceTable(Record):
    input_per_million: Decimal
    output_per_million: Decimal
    currency: str
    as_of: str

    @field_validator("as_of")
    @classmethod
    def valid_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value


class ReviewOptions(Record):
    repo: Path
    mode: Literal["workspace", "range", "commit"] = "workspace"
    from_ref: str | None = None
    to_ref: str | None = None
    commit_ref: str | None = None
    exclude: list[str] = Field(default_factory=list)
    preview: bool = False
    resume_id: str | None = None


class Settings(Record):
    base_url: str = ""
    model: str = ""
    api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)
    schema_mode: Literal["text", "json_object", "json_schema"] = "text"
    max_output_tokens: StrictInt = Field(default=1500, gt=0)
    max_output_parameter: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    max_tokens_budget: StrictInt | None = Field(default=None, gt=0)
    timeout_seconds: float = 60.0
    allow_hosted_upload: bool = False
    allow_loopback_http: bool = False
    retry_uncertain: bool = False
    price_table: PriceTable | None = None
    account_label: str = ""
    exclude: list[str] = Field(default_factory=list)


class Limits(Record):
    max_file_bytes: int = 1048576
    max_files: int = 50
    max_total_bytes: int = 5242880
    max_bundle_files: int = 5
    max_bundle_patch_lines: int = 800
    max_bundle_code_bytes: int = 204800
    max_http_body_bytes: int = 307200


class Hunk(Record):
    old_start: StrictInt
    old_count: StrictInt
    new_start: StrictInt
    new_count: StrictInt
    patch: str
    added_lines: list[StrictInt]


class Change(Record):
    path: str
    old_path: str | None = None
    status: Literal["added", "modified", "renamed", "deleted"]
    binary: bool = False
    hunks: list[Hunk] = Field(default_factory=list)
    kind: str = "file"
    size: int = 0


class Snapshot(Record):
    mode: str
    base_oid: str
    target_oid: str | None
    identity: str
    changes: list[Change]
    target_bytes: dict[str, bytes] = Field(default_factory=dict, exclude=True)


class Decision(Record):
    path: str
    included: bool
    reason: str


class Redaction(Record):
    path: str
    line: StrictInt
    rule_id: str
    action: Literal["redacted", "excluded"]


class SafeDocument(Record):
    path: str
    content: str
    patch: str
    content_hash: str = Field(exclude=True)
    line_count: int
    added_lines: list[int]
    redactions: list[Redaction]


class Excluded(Record):
    path: str
    reason: str


class Bundle(Record):
    id: str
    documents: list[SafeDocument]
    payload_bytes: int


class EndpointPolicy(Record):
    base_url: str
    loopback: bool
    upload_permitted: bool


class RequestDraft(Record):
    body: dict


class ApprovedPayload(Record):
    body: bytes
    endpoint: str


class Usage(Record):
    input_tokens: StrictInt | None = Field(default=None, ge=0)
    output_tokens: StrictInt | None = Field(default=None, ge=0)
    complete: bool = False
    source: Literal["provider", "missing", "invalid"] = "missing"


class UsageLedger(Record):
    entries: list[Usage] = Field(default_factory=list)
    known_input: int = 0
    known_output: int = 0
    complete: bool = True


class ModelReply(Record):
    text: str
    usage: Usage
    request_id: str | None = None
    finish_reason: str | None = None


class ValidationOutcome(Record):
    valid: bool
    findings: list[Finding]
    errors: list[str]


class BudgetDecision(Record):
    allowed: bool
    reason: str


class CostEstimate(Record):
    amount: Decimal | None = None
    currency: str | None = None
    reason: str | None = None
    complete: bool = False
    as_of: str | None = None
    omitted_charges: str = "Taxes, infrastructure and provider-specific charges excluded"


class ErrorRecord(Record):
    code: str
    message: str = Field(max_length=200)
    bundle_id: str | None = None
    retryable: bool = False


class BundleState(Record):
    id: str
    status: Literal["pending", "running", "done", "failed", "uncertain"]
    attempts: int = 0
    findings: list[Finding] = Field(default_factory=list)
    usage: list[Usage] = Field(default_factory=list)
    error_code: str | None = None


class Checkpoint(Record):
    format_version: str
    run_id: str
    run_key: str
    snapshot_identity: str
    bundle_states: list[BundleState]
    created_at: str
    updated_at: str
    complete: bool = False

    @field_validator("created_at", "updated_at")
    @classmethod
    def utc_timestamp(cls, value: str) -> str:
        moment = datetime.fromisoformat(value)
        if moment.tzinfo is None or moment.utcoffset().total_seconds() != 0:
            raise ValueError("UTC timestamp required")
        return value


class RunResult(Record):
    format_version: str = "1"
    run_id: str
    revision: dict[str, str | None]
    findings: list[Finding]
    decisions: list[Decision]
    redactions: list[Redaction]
    bundle_errors: list[ErrorRecord]
    usage: UsageLedger
    cost: CostEstimate
    partial: bool
    warnings: list[str]
