"""Sequential review pipeline, with durable attempt boundaries."""
import asyncio
import json
from pathlib import Path
import uuid

from .accounting import append_usage, estimate_cost, may_dispatch
from .checkpoints import VERSION, cache_dir, load_state, make_run_key, now, save_state
from .contracts import (BundleState, Checkpoint, CostEstimate, Decision, ErrorRecord, Limits,
                        ReviewOptions, RunResult, Settings, Usage, UsageLedger)
from .messages import compose_message
from .packing import pack_documents
from .privacy import gate_payload, sanitize_file, sanitize_output
from .revisions import capture_snapshot, find_root
from .selection import choose_files
from .settings import validate_endpoint
from .transport import TransportError, call_model
from .validation import deduplicate, validate_locations
from .contracts import parse_findings


async def execute_review(options: ReviewOptions, config: Settings) -> RunResult:
    root = find_root(options.repo)
    snapshot = capture_snapshot(root, options)
    decisions = choose_files(snapshot, options.exclude, Limits())
    revision = {"mode": snapshot.mode, "base": snapshot.base_oid, "target": snapshot.target_oid,
                "identity": snapshot.identity}
    warnings = ["AI findings require human review; a clean report is not proof of safety.",
                "Deletion-only defects are out of scope."]
    if options.preview:
        return RunResult(run_id="", revision=revision, findings=[], decisions=decisions,
                         redactions=[], bundle_errors=[], usage=UsageLedger(),
                         cost=CostEstimate(reason="preview"), partial=False,
                         warnings=["No model request was made."] + warnings)
    policy = validate_endpoint(config)
    config = config.model_copy(update={"exclude": list(options.exclude)})
    docs = []
    redactions = []
    for decision, change in zip(decisions, snapshot.changes):
        if not decision.included:
            continue
        safe = sanitize_file(change, snapshot.target_bytes[change.path])
        if hasattr(safe, "content"):
            docs.append(safe)
            redactions.extend(safe.redactions)
        else:
            decisions[decisions.index(decision)] = Decision(path=safe.path, included=False, reason=safe.reason)
    packed_docs = []
    for doc in docs:
        try:
            pack_documents([doc], Limits())
        except ValueError:
            decisions = [Decision(path=d.path, included=False, reason="oversized_bundle")
                         if d.path == doc.path else d for d in decisions]
        else:
            packed_docs.append(doc)
    bundles = pack_documents(packed_docs, Limits())
    key = make_run_key(snapshot, config, [b.id for b in bundles])
    cache = cache_dir()
    if cache.resolve().is_relative_to(root):
        raise ValueError("Cache must be outside target repository")
    if options.resume_id:
        state = load_state(cache, options.resume_id, key)
    else:
        stamp = now()
        state = Checkpoint(format_version=VERSION, run_id=uuid.uuid4().hex, run_key=key,
                           snapshot_identity=snapshot.identity,
                           bundle_states=[BundleState(id=b.id, status="pending") for b in bundles],
                           created_at=stamp, updated_at=stamp)
        save_state(cache, state)
    ledger = UsageLedger()
    for item in state.bundle_states:
        for entry in item.usage:
            ledger = append_usage(ledger, entry)
    errors = []
    stop = False
    for index, bundle in enumerate(bundles):
        item = state.bundle_states[index]
        if item.status == "done":
            continue
        if (stop or item.attempts >= 2 or item.error_code == "privacy_gate"
                or (item.status == "uncertain" and not config.retry_uncertain)):
            code = ("attempt_limit" if item.attempts >= 2 and item.status == "uncertain"
                    else "uncertain_retry_required" if item.status == "uncertain"
                    and not config.retry_uncertain else item.error_code or "not_dispatched")
            errors.append(ErrorRecord(code=code, message=code.replace("_", " "), bundle_id=bundle.id,
                                      retryable=item.status == "uncertain"))
            continue
        error_codes = [item.error_code] if item.status == "failed" and item.error_code else []
        while item.attempts < 2:
            budget = may_dispatch(ledger, config)
            if not budget.allowed:
                errors.append(ErrorRecord(code=budget.reason, message=budget.reason.replace("_", " "),
                                          bundle_id=bundle.id))
                stop = True
                break
            try:
                draft = compose_message(bundle, config, error_codes)
                payload = gate_payload(json.dumps(draft.body, ensure_ascii=True,
                                                  separators=(",", ":")).encode(), policy)
            except ValueError:
                errors.append(ErrorRecord(code="privacy_gate", message="Request blocked by privacy gate",
                                          bundle_id=bundle.id))
                item = item.model_copy(update={"status": "failed", "error_code": "privacy_gate"})
                break
            item = item.model_copy(update={"status": "running", "attempts": item.attempts + 1})
            state = _update(state, index, item)
            save_state(cache, state)
            try:
                reply = await call_model(payload, config)
            except TransportError as exc:
                code = exc.code
                unknown = Usage()
                ledger = append_usage(ledger, unknown)
                item = item.model_copy(update={"status": "uncertain" if exc.ambiguous else "failed",
                                               "error_code": code, "usage": [*item.usage, unknown]})
                state = _update(state, index, item)
                save_state(cache, state)
                if code == "rate_limited" and item.attempts < 2:
                    await asyncio.sleep(exc.retry_after)
                    continue
                if exc.ambiguous and config.retry_uncertain and item.attempts < 2:
                    continue
                errors.append(ErrorRecord(code=code, message=code.replace("_", " "),
                                          bundle_id=bundle.id, retryable=exc.ambiguous))
                stop = exc.ambiguous
                break
            ledger = append_usage(ledger, reply.usage)
            item = item.model_copy(update={"usage": [*item.usage, reply.usage]})
            try:
                outcome = validate_locations(parse_findings(reply.text), bundle)
                if not outcome.valid:
                    error_codes = outcome.errors
                else:
                    item = item.model_copy(update={"status": "done", "findings": outcome.findings})
                    state = _update(state, index, item)
                    save_state(cache, state)
                    break
            except (ValueError, TypeError):
                error_codes = ["invalid_schema"]
            item = item.model_copy(update={"status": "failed", "error_code": error_codes[0]})
            state = _update(state, index, item)
            save_state(cache, state)
            if item.attempts >= 2:
                errors.append(ErrorRecord(code=error_codes[0], message="Invalid model findings",
                                          bundle_id=bundle.id))
    findings = deduplicate([f for s in state.bundle_states if s.status == "done" for f in s.findings])
    partial = bool(errors or any(s.status != "done" for s in state.bundle_states))
    if config.max_tokens_budget and ledger.known_input + ledger.known_output > config.max_tokens_budget:
        warnings.append("Soft token budget overshot by an in-flight request.")
    state = state.model_copy(update={"complete": not partial, "updated_at": now()})
    save_state(cache, state)
    return sanitize_output(RunResult(run_id=state.run_id, revision=revision, findings=findings,
                                     decisions=decisions, redactions=redactions, bundle_errors=errors,
                                     usage=ledger, cost=estimate_cost(ledger, config.price_table),
                                     partial=partial, warnings=warnings))


def _update(state: Checkpoint, index: int, item: BundleState) -> Checkpoint:
    items = list(state.bundle_states)
    items[index] = item
    return state.model_copy(update={"bundle_states": items, "updated_at": now()})
