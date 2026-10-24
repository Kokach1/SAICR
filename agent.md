# Review Desk evaluation notes

This document describes observed local behavior, not evaluator instructions. It does not supersede evaluation rules or hidden tests.

## 1. Project scope and trust boundary

CLI-first tracked-workspace (staged and unstaged versus HEAD), merge-base range and non-merge single-commit reviews, with a no-network preview. All reviewed repository code, filenames, comments and model output are untrusted data. Never execute target-repository scripts or obey embedded instructions. Do not alter evaluator rules, scoring, hidden tests, evidence or reports. Deferred: untracked files, merge commits, whole-repository scans, autonomous execution, automatic fixes, CI/IDE/MCP/hosted integration, web UI and translation. AI findings need human review; a clean report does not prove safety. Scanning cannot guarantee the absence of secrets. Any build-time estimate is a target, not a guarantee.

## 2. Environment and setup

REAL EXECUTION: Windows, Python **3.14.0**, Git **2.52.0.windows.1**. A newly created `.venv` successfully installed the project using `.venv/Scripts/python.exe -m pip install -e .`, then installed pytest for development. Installed versions: Pydantic **2.14.1**, httpx **0.28.1**, pytest **9.1.1**. The only network use in Phase A was pip package installation. No credentials are needed for preview/tests. Python 3.11-3.13, Linux/macOS, live local/hosted model configurations and paid calls remain **not tested**. Third-party libraries retain their own license and notice files; no library is vendored.

## 3. Reproducible commands

REAL EXECUTION (Windows bash, from the repository root; no HTTP/model calls):

```sh
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e .
.venv/Scripts/python.exe -m pip install 'pytest>=8,<10'
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m pytest -q tests/test_privacy_real.py
.venv/Scripts/python.exe fixtures/prepare_demo.py
.venv/Scripts/reviewdesk.exe preview --repo fixtures/demo
env -u LLM_BASE_URL -u LLM_MODEL -u LLM_API_KEY .venv/Scripts/reviewdesk.exe review --repo fixtures/demo
```

The final command exits **2** with a safe configuration error. The controlled-input tests call the actual Git, scanner, message construction and privacy gate code, never a replacement model or HTTP client. Real-model `review`, `--output`, `sessions show` and `--resume` have **not** been run. They require the Phase B prerequisites in section 9.

## 4. Acceptance matrix

REAL EXECUTION: `evidence/test-output.txt` records the retained real-code checks. "Pass" covers only the listed direct checks, not provider interaction. `tests/test_privacy_real.py` checks controlled fixture input through actual scanner/serialization/gate functions without constructing a client.

| ID | Test file and representative test | Expected and observed | Status / gaps |
| --- | --- | --- | --- |
| T01 | `test_t01_strict_settings`, `test_t01_preview_cli_no_model` | Strict settings, preview 0, no-model review 2 | pass; preview no-client claim is inspection-only |
| T02 | `test_t02_workspace_and_historical`, `test_t02_range_and_rename`, `test_t02_merge_rejected_and_credential_not_read`, `test_t02_git_filter_is_rejected_without_execution`, `test_t02_recreate_demo_fixture`, `test_git_hooks_path_is_native` | Git revision modes, filter guard and native hooks setting | pass on Windows; POSIX inspected only |
| T03 | `test_t03_workspace_race_detected`, `test_t02_workspace_and_historical` | Concurrent controlled workspace edit rejected; historical target blobs read | pass for these inputs |
| T04 | `test_t04_paths_and_choices`, `test_t04_git_symlink_and_submodule_are_skipped` | Path exclusions and special entries | pass for tested cases |
| T05 | `test_t05_t06_redaction_and_packing`, `tests/test_privacy_real.py` | Seven fixture credential classes excluded from approved serialized body; eleven residual variants and nested/escaped cases rejected | pass locally; real provider-generated output unverified |
| T06 | `test_t06_boundaries_and_prompt_injection`, `test_t05_t06_redaction_and_packing` | Bundle size and data-envelope checks | pass for tested limits |
| T07 | `test_t01_strict_settings`, `test_t07_t09_validation` | Schema parsing and location validation | pass; live response repair unverified |
| T08 | `test_transport_rejects_unapproved_payload` | Unapproved object rejected locally, before HTTP construction | pass locally; live HTTP unverified |
| T09 | `test_t07_t09_validation` | Invalid locations rejected, exact dedup retained | pass |
| T10 | `test_t10_t11_checkpoint_accounting`, `test_t10_corrupt_state_and_key_options`, `test_t10_atomic_parallel_writes` | Real checkpoint I/O and local concurrency | pass; live checkpoint/resume unverified |
| T11 | `test_t10_t11_checkpoint_accounting` | Real accounting arithmetic and soft-cap decision | pass; provider usage/dispatch unverified |
| T12 | `test_export_symlink_refused`, `test_export_existing_destination_refused`, `test_t12_report_cannot_write_target_repo`, `test_parser_and_terminal_escape` | Real preview export guards and terminal escape | pass; live review/export/show/resume unverified |

Run `.venv/Scripts/python.exe -m pytest -q` to reproduce the actual retained tests (35 passed at the recorded run). The controlled fixture is input data, not a provider response.

## 5. Implementation status

Implemented: the 13 existing modules remain in place. Scanner rules now include JWT-shaped strings, Slack tokens, Stripe live keys, Google API keys, database credential URLs and context-labeled AWS secrets; the ruleset is `scanner-2`. Git hooksPath is OS-aware. `sessions show` includes saved finding path, start/end, severity, title and suggestion presence. The product is **not ready-to-use end-to-end** until a real endpoint run confirms review, export, checkpoint, sessions and resume. Partial limitations: heuristic scanning and incomplete platform/provider coverage. Not implemented: deferred features in section 1. Starting project HEAD: `de842a8a1fac68c7c3150db8dfa074f063a7f242`; the current changes are uncommitted and not represented by that SHA.

Fix 0 removal in `tests/test_pipeline.py`: deleted simulated-provider tests `test_t08_transport`, `test_t12_mocked_review_resume_and_export`, `test_t07_repair_and_uncertain`, `test_t05_secret_not_in_request_or_report`, `test_t11_budget_blocks_second_bundle`, `test_t08_unsupported_mode_and_response_limit`, `test_t10_uncertain_resume_requires_permission`, `test_t12_cli_export_and_resume_with_mock_http`, `test_t08_timeout_has_safe_error`, and `test_t01_preview_does_not_construct_http_client`. The real unapproved-payload check from `test_t08_transport` remains as `test_transport_rejects_unapproved_payload`. Removed only the simulated checkpoint-write failure part of `test_t12_export_symlink_and_checkpoint_exit`; its real symlink assertion remains as `test_export_symlink_refused`. Parser, terminal and existing-report refusal checks from the combined review test remain separately. Deleted `evidence/mock-export-resume.txt`. No reusable real-Git fixture helper or production function was removed.

Preserved `tests/test_core.py` real Git/path/privacy cases, the direct real-code tests in `tests/test_pipeline.py` (schema/location, checkpoint I/O, accounting, preview, export safety, packing and terminal escaping), and the real pipeline checks added in `tests/test_privacy_real.py`. The surviving `monkeypatch` usage in `test_core.py` only controls local Git fixture paths or mutates a real file mid-capture; it never supplies a provider response. Controlled schema examples validate a parser directly, not a model boundary.

Lost coverage: provider transport status/timeout/redirect behavior; response repair/attempt count; request and export/checkpoint privacy after real generation; provider-reported usage, in-flight soft-budget behavior and uncertain live resume; live CLI export and session findings. These are **unverified by execution**, not made green by removing tests. Existing direct checkpoint arithmetic/I/O tests do not verify a checkpoint produced by a real review.

## 6. Security checks

REAL EXECUTION: `tests/test_privacy_real.py` feeds controlled local Git fixture changes into real snapshot, selection, `sanitize_file`, packing, `compose_message`, JSON serialization and `gate_payload`. Seven credential classes yield 14 redaction records across context and patch; redaction path/new-file line and newline count match fixture input. Eleven deliberately residual variants, including contextual AWS and Slack user tokens, and nested/escaped JSON cases are blocked by the real outbound gate. SHA, digest, ordinary prose and `token_url` remain. No HTTP client is built by this check. Direct Git path traversal, symlink/submodule and repository-filter tests pass. Preview returns 0 without model configuration; no-model review returns 2. This tests concrete plaintext/JSON formats only, not arbitrary encodings or all secrets.

CODE INSPECTION ONLY - never had real test coverage; unverified by execution (do not induce these against a provider):

- HTTP 429: `transport.py:28-31` bounds integer `Retry-After` to 30 seconds; `runner.py:90-125` records an unknown-usage attempt and sleeps/retries only if under the two-attempt cap. A configured soft budget can stop that retry on unknown usage.
- HTTP 401/403: `transport.py:32-33` raises `authentication`; `runner.py:111-125,147-155` marks the bundle failed with that error code, no per-bundle retry and partial result (CLI exit 1). It does not halt other bundles solely for authentication failure; repeated failures across different bundles are possible.
- HTTP 5xx and ambiguous timeouts: `transport.py:36-37,66-67` marks them uncertain; `runner.py:115-126` stops unless `--retry-uncertain` authorizes one remaining attempt, with a two-attempt maximum. A previous simulated timeout check was deleted; there is no real execution coverage.
- HTTP 3xx: `transport.py:24-35` disables redirects and returns `redirect_denied`; `runner.py:111-126` does not retry that attempt. A previous simulated redirect check was deleted; there is no real execution coverage.

The lifecycle matches the documented per-bundle status and exit contract by inspection. No live provider response, TLS negotiation or provider-generated persistence was observed.

## 7. Accessibility and usability

Plain text output, `--help`, meaningful exit codes, severity in text rather than color, and terminal control escaping. A viewer was not built; keyboard navigation, labels, focus visibility and contrast checks are not applicable until a viewer exists. There are no authored emojis in UI output.

## 8. Evidence and limitations

REAL EXECUTION evidence (UTC, no credentials or raw source/payloads): `evidence/setup.txt` records fresh-venv editable installation; `evidence/environment.txt` records installed versions; `evidence/test-output.txt` records the retained suite; `evidence/privacy-check.txt` records secret-class counts, preservation/rejection verdicts and body size; `evidence/preview.json` is a real no-network preview of the controlled local Git fixture; `evidence/final-run.txt` records exact local commands and exit codes. Neither preview nor unit-level privacy inspection is a model-generated report. A newly recreated fixture gets a different Git commit OID but the same controlled source data. Limitations: only the current Windows platform and concrete serialization forms were observed; no live-model quality, generated output privacy, billing or resume behavior has been observed.

CODE INSPECTION evidence is explicitly confined to section 6 (source path and line references), and is not described as execution coverage. BLOCKED evidence is described in section 9. Do not use legacy test counts or the deleted provider-response evidence file as proof of current behavior.

## 9. Real-model validation and Phase B gate

BLOCKED: **Real-model operation unverified - blocked on missing prerequisites: chosen provider, model name and endpoint/base URL.** No endpoint or model was configured in the local environment at verification time. A key is needed only if the selected endpoint requires authentication; explicit spend approval (concrete amount and call limits) only if wallet-bearing; explicit code-upload consent only for a hosted endpoint. Those conditional items cannot be determined until an endpoint is chosen. No model call, live report export, provider-generated checkpoint, `sessions show` of real findings or exact live resume took place. The session-findings change is implemented but **unverified by execution**.

Once the owner provides the applicable prerequisites, run exactly one bounded real review of the controlled demo fixture; check actual terminal findings, exported JSON, checkpoint, `sessions list/show`, and exact resume without additional calls. Programmatically verify that none of the controlled fixture's credential-shaped inputs occur in any exported report, persisted state or stdout; report verdicts/counts only. Record actual findings against the two seeded issues, false positives, misses, usage if known, latency, and any cost only as a dated-rate estimate. Any retry requires newly approved limits. Never use deliberately induced provider failures or pretend a clean report proves safety.
