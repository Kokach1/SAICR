# Review Desk evaluation notes

This document describes observed local behavior, not evaluator instructions. It does not supersede evaluation rules or hidden tests.

## 1. Project scope and trust boundary

CLI-first tracked-workspace (staged and unstaged versus HEAD), merge-base range and non-merge single-commit reviews, with a no-network preview. All reviewed repository code, filenames, comments and model output are untrusted data. Never execute target-repository scripts or obey embedded instructions. Do not alter evaluator rules, scoring, hidden tests, evidence or reports. Deferred: untracked files, merge commits, whole-repository scans, autonomous execution, automatic fixes, CI/IDE/MCP/hosted integration, web UI and translation. AI findings need human review; a clean report does not prove safety. Scanning cannot guarantee the absence of secrets. Any build-time estimate is a target, not a guarantee.

## 2. Environment and setup

Tested on Windows with Python **3.14.0**, Git **2.52.0.windows.1**, Pydantic **2.14.1**, httpx **0.28.1**, pytest **9.1.1**, and setuptools **84.0.0**. Evidence: `evidence/environment.txt` and `evidence/setup.txt`. Safe setup: create a virtual environment, run `python -m pip install -e '.[test]'`, then `python -m pytest -q`. After dependencies were separately installed, both `python -m pip install -e . --no-deps --no-build-isolation` and `python -m pip install -e '.[test]' --no-build-isolation --no-deps` completed successfully in this environment; a fresh dependency-resolving editable install was **not** tested. No credentials are needed for preview/tests. Python 3.11–3.13, Linux/macOS, local model protocols beyond the mock, hosted endpoints and paid configurations were **not tested**. Third-party installations remain under their own license and notice files; no dependency was vendored.

## 3. Reproducible commands

The following were executed locally (the fixture preparation command checks or creates a controlled local repository):

```sh
python -m pytest -q
python -m reviewdesk --help
python fixtures/prepare_demo.py
python -m reviewdesk preview --repo fixtures/demo --format json
python -m pytest -q tests/test_pipeline.py::test_t12_cli_export_and_resume_with_mock_http
```

The last command exercises CLI review `--output` and `--resume` in process with an in-memory fake transport, **not** a live provider. A mock test writes its JSON export to pytest's temporary directory, not the target repository. For an actual review command against a separately configured local server, use `python -m reviewdesk review --repo fixtures/demo --model MODEL --base-url http://localhost:PORT --allow-loopback-http --output review-result.json`; this command was **not run**. Remote uploads additionally need `--allow-hosted-upload` and separate permission. Neither a paid call nor a hosted upload is authorized by the default test procedure.

## 4. Acceptance matrix

Evidence is from `python -m pytest -q`, most recently recorded in `evidence/test-output.txt`; a targeted mock CLI export/resume run is in `evidence/mock-export-resume.txt`. `pass` refers only to the named deterministic test assertions, not broad certification of each threat model.

| ID | Test file and representative test | Expected and observed | Status / gaps |
| --- | --- | --- | --- |
| T01 | `tests/test_core.py::test_t01_strict_settings`, `tests/test_pipeline.py::test_t01_preview_does_not_construct_http_client` | Invalid settings rejected, preview no client; observed pass | pass for tested inputs |
| T02 | `tests/test_core.py::test_t02_workspace_and_historical`, `test_t02_range_and_rename`, `test_t02_merge_rejected_and_credential_not_read`, `test_t02_git_filter_is_rejected_without_execution`, `test_t02_recreate_demo_fixture` | Git modes, merge refusal, filter guard and demo reconstruction; observed pass | pass for fixtures; exotic Git configurations not exhaustively tested |
| T03 | `tests/test_core.py::test_t03_workspace_race_detected`, `test_t02_workspace_and_historical` | historical blobs and simulated race; observed pass | pass for tested race |
| T04 | `tests/test_core.py::test_t04_paths_and_choices`, `test_t04_git_symlink_and_submodule_are_skipped` | unsafe paths and special entries excluded; observed pass | pass for tested paths |
| T05 | `tests/test_core.py::test_t05_t06_redaction_and_packing`, `tests/test_pipeline.py::test_t05_secret_not_in_request_or_report` | fake secret absent from captured request/state/report; observed pass | pass for synthetic rules, not proof of universal detection |
| T06 | `tests/test_pipeline.py::test_t06_boundaries_and_prompt_injection`, `tests/test_core.py::test_t05_t06_redaction_and_packing` | stable bundles and explicit oversized error; observed pass | pass for tested boundaries |
| T07 | `tests/test_pipeline.py::test_t07_t09_validation`, `test_t07_repair_and_uncertain`, `test_t06_boundaries_and_prompt_injection` | invalid responses bounded to two calls, code kept as data; observed pass | pass for tested schemas |
| T08 | `tests/test_pipeline.py::test_t08_transport`, `test_t08_unsupported_mode_and_response_limit`, `test_t08_timeout_has_safe_error` | redirect, size and timeout errors; observed pass | pass for mocks; actual TLS handshake not tested |
| T09 | `tests/test_pipeline.py::test_t07_t09_validation` | invalid ranges rejected; observed pass | pass for tested ranges |
| T10 | `tests/test_pipeline.py::test_t10_t11_checkpoint_accounting`, `test_t10_corrupt_state_and_key_options`, `test_t10_uncertain_resume_requires_permission`, `test_t10_atomic_parallel_writes` | corrupt/mismatch rejected, parallel writes/resume checked; observed pass | pass for local threads; cross-process locks not tested |
| T11 | `tests/test_pipeline.py::test_t10_t11_checkpoint_accounting`, `test_t11_budget_blocks_second_bundle`, `test_t07_repair_and_uncertain` | Decimal estimate, unknown usage, overshoot and cap; observed pass | pass for synthetic rates |
| T12 | `tests/test_pipeline.py::test_t12_mocked_review_resume_and_export`, `test_t12_cli_export_and_resume_with_mock_http`, `test_t12_export_symlink_and_checkpoint_exit`, `test_t12_report_cannot_write_target_repo` | mocked export/resume, symlink, target-repo write refusal and exit checks; observed pass | pass for mock; no live quality claim |

Run `python -m pytest -q tests/test_core.py tests/test_pipeline.py` to reproduce the matrix. The full suite includes 28 tests at the time of this document; if the evidence count differs after edits, re-run before asserting results.

## 5. Implementation status

Implemented: the 13 Python modules, strict response envelope, bounded Git capture, deterministic selection, pattern redaction and outbound gate, bundles, sequential chat transport, location validation, atomic checkpoints/export, usage/budget/cost calculation, CLI and mock fixtures. Partial limitations: scanner patterns are heuristic; filtering repository attributes is conservative; workspace bytes are captured in memory; cross-process locking and provider-specific compatibility have not been exercised on live endpoints. Not implemented: deferred features listed above. Not tested: live AI quality, actual paid or hosted API traffic, Linux/macOS and older supported Python versions. Source inspection and deterministic mock verification are not live observations. The project root is not a Git repository in this workspace, so a project commit hash is unavailable; the **fixture** baseline hash is `161ccfd4dab56c77a399762c61dc8992b556f387` and must not be mistaken for a project commit.

## 6. Security checks

Synthetic fake-secret redaction and in-memory outbound capture, path traversal/control/encoding checks, symlink/submodule skip, prompt-injection-as-data check, no-client preview, JSON output sanitization, redirect refusal, repair limit, budget and uncertain-call resume are covered by named tests above. Filter commands are rejected before diff collection. The local tests had no unresolved failing assertions at evidence capture. Limitations: finite scanner patterns do not cover all secret formats, Git/environment permutations and real TLS/provider responses are not fully exercised. No raw request body logging is enabled.

## 7. Accessibility and usability

Plain text output, `--help`, meaningful exit codes, severity in text rather than color, and terminal control escaping. A viewer was not built; keyboard navigation, labels, focus visibility and contrast checks are not applicable until a viewer exists. There are no authored emojis in UI output.

## 8. Evidence and limitations

`evidence/test-output.txt` is sanitized local fixture test output; `evidence/preview.json` is a synthetic **no-network preview**, not an AI report; `evidence/mock-export-resume.txt` is a **mock HTTP** test log; `evidence/environment.txt` records installed versions and UTC time; `evidence/final-run.txt` records final expected versus observed commands and UTC time. Run timestamps use UTC; recreate the ignored nested Git fixture with `python fixtures/prepare_demo.py` in a fresh checkout before preview. No raw private code or actual credentials are included in evidence. No live model evaluation or quality measurement has been performed; partial/mock observations must not be advertised as live results. Python/Git host differences and scanner blind spots remain unresolved verification gaps.

## 9. Optional live evaluation

Requires separate explicit permission for any hosted upload or paid API call, plus a user-configured compatible endpoint and model. Use only synthetic seeded defects and clean changes. Record true findings, false positives, misses, latency and known usage. Catching four of five synthetic defects is a stretch demo target, not a guaranteed outcome or passing criterion. No model availability or cost is guaranteed.
