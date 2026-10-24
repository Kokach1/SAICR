# Review Desk

Review Desk is a CLI for bounded Git changes using one explicitly configured OpenAI-compatible chat-completions endpoint. It proposes findings at added new-file lines. **AI findings require human review; an empty report is not proof of safety.** Secret scanning reduces risk but cannot guarantee that no secrets remain. Any build-time estimate is a target, not a guarantee.

## Setup

Python 3.11+ and Git are required. The verified environment was Windows, Python 3.14.0, Git 2.52.0.windows.1, Pydantic 2.14.1, httpx 0.28.1 and pytest 9.1.1. Other platforms and Python versions have not been verified here. In a virtual environment:

```sh
python -m pip install -e '.[test]'
python -m pytest -q
python -m reviewdesk --help
python fixtures/prepare_demo.py
python -m reviewdesk preview --repo fixtures/demo
```

Dependencies are installed separately by pip under their respective licenses; this repository does not vendor or remove their license, copyright or notice files. `fixtures/prepare_demo.py` creates a controlled local Git repository under `fixtures/demo` with two seeded defects, non-secret identifiers and obviously invented credential-shaped strings. It is input data for the real pipeline, not a provider response. The nested repository is intentionally not committed as a Git submodule. Preparation updates only a recognized older fixture version and refuses unexpected contents.

## Revision semantics

* `reviewdesk preview --repo fixtures/demo` inspects the same bounded Git snapshot as review, with no model configuration or HTTP client. Preview does not run reviewed scripts.
* `reviewdesk review --repo PATH` compares tracked staged and unstaged workspace changes with `HEAD` (untracked files excluded). A clean workspace has no bundles.
* `--from REF --to REF` compares `merge-base(REF, TARGET)` to the resolved target commit.
* `--commit REF` compares one non-merge commit with its parent; a root commit is compared with the empty tree. Merge commits are rejected.

Historical contents come from target Git blobs, not current workspace files. For workspace mode the program checks each bounded regular file before and after capture and compares the diff metadata again; changed snapshots fail rather than return mismatched content. Renames are reported at target paths. Deletion-only findings cannot be placed on an added line and are not supported.

Check the actual local scanner and fail-closed gate without an endpoint:

```sh
python -m pytest -q tests/test_privacy_real.py
```

For an actual explicitly permitted local inference server, set `LLM_BASE_URL`, `LLM_MODEL` and, only if the server requires it, `LLM_API_KEY`; then use `reviewdesk review --repo fixtures/demo --allow-loopback-http --output review-result.json`. This example has **not** been executed against a running server. Do not treat a local server as automatically free or safe. For HTTPS endpoints outside loopback, add `--allow-hosted-upload` for that invocation; this is permission for transmitting selected code. Paid calls also require separately approved amount and call limits. No provider/model, prices, free credits or availability are assumed. Real-model operation remains unverified.

Endpoint URL must be a bare HTTPS origin (for example an origin with no path) or an explicitly allowed loopback HTTP origin. HTTP redirects are not followed. Providers differ: start with default `--schema-mode text`; `json_object` and `json_schema` are opt-in, and unsupported options fail rather than silently downgrade. Choose `--max-output-parameter max_tokens` or `max_completion_tokens` to match your server. `--max-output-tokens` defaults to 1500.

`--output PATH` writes JSON atomically outside the reviewed repository, refusing an existing destination unless `--overwrite` is specified. `--format json` prints a versioned JSON report. `reviewdesk sessions list` and `reviewdesk sessions show RUN_ID` inspect private checkpoints. `--resume RUN_ID` requires an exact snapshot, model, endpoint and request configuration match. A previously running or ambiguously delivered request requires `--retry-uncertain`; a second request may incur duplicate charges. A bundle makes at most two HTTP attempts, including repair/retry.

## Coverage, privacy and limits

Credential paths (`.env`, `.env.*`, `*.pem`, `*.key`, `id_rsa*`, `*.p12`, `*.pfx`, `credentials*`, `secrets*`, `*.keystore`, `.aws/**`, `.ssh/**`) are hard-excluded. Lockfiles, binary files, deletions, symlinks, submodules and user `--exclude GLOB` matches are skipped with reason codes. More than 50 selected files, 1 MiB per selected file or 5 MiB in total is rejected; a single oversized bundle is explicitly skipped. Bundles contain at most five files, 800 patch lines and 200 KiB serialized safe documents. Outbound bodies are limited to 300 KiB and responses to 512 KiB. The shared scanner recognizes common tokens/password assignments, JWT-shaped strings, Slack tokens, Stripe live keys, Google API keys, database URLs with credentials and context-labeled AWS secret access keys; private-key blocks are excluded. It does **not** redact arbitrary bare 40-character values. Real local checks cover the concrete plaintext and JSON serialization formats emitted by this app, not arbitrary encodings or unknown credentials. These heuristics cannot guarantee absence of secrets. Preview exits before redaction, so it shows selected paths but **not** sanitized payloads or redaction results; inspect source and choose exclusions before permitting uploads. Checkpoint design excludes raw prompts, code and replies, but actual provider-generated checkpoint/report privacy remains unverified until a real run.

Git is invoked through a fixed executable path with argv, a timeout, size limits and disabled external diffs/textconv/hooks; repositories with registered filter commands or filter attributes are rejected. Do not execute reviewed-repository scripts, tests or commands: only controlled test fixtures run. Repository content and model text are untrusted data, not tool instructions. Suggestions are never applied. This version does not implement untracked files, merge commits, whole-repository scans, autonomous commands/tools, automatic fixes, CI/IDE/MCP/hosted-service integrations, a web UI or translation.

`--max-tokens-budget N` is a **soft** provider-reported input-plus-output token cap. It stops subsequent sequential dispatch on the cap or on unknown usage; an in-flight call can overshoot. It is not a dollar limit, invoice or hard spend guarantee. Optional estimates require all four supplied fields: `--input-per-million RATE --output-per-million RATE --price-currency USD --price-as-of YYYY-MM-DD`. Missing rates or incomplete usage produces a null estimate. Estimates omit taxes, infrastructure and provider-specific charges. No static prices or assumed balance are included.

Exit codes: `0` complete or preview (including reviews with findings), `1` partial (failed/uncertain/budget-stopped bundles), `2` invalid/unsafe configuration or snapshot, `3` checkpoint or report write failure. Errors deliberately omit raw provider messages. State is stored in the platform user cache under `reviewdesk/runs`, configurable with `REVIEWDESK_CACHE_DIR` outside the reviewed repository. See [agent.md](agent.md) for verified commands, local evidence and limitations.

## Verification coverage

Provider-response simulations have been removed. `tests/test_pipeline.py` no longer contains `test_t08_transport`, `test_t12_mocked_review_resume_and_export`, `test_t07_repair_and_uncertain`, `test_t05_secret_not_in_request_or_report`, `test_t11_budget_blocks_second_bundle`, `test_t08_unsupported_mode_and_response_limit`, `test_t10_uncertain_resume_requires_permission`, `test_t12_cli_export_and_resume_with_mock_http`, `test_t08_timeout_has_safe_error` or `test_t01_preview_does_not_construct_http_client`. The real unapproved-payload assertion from the former transport test remains as `test_transport_rejects_unapproved_payload`. Only the simulated checkpoint-write half of `test_t12_export_symlink_and_checkpoint_exit` was removed; the real symlink check remains as `test_export_symlink_refused`. Real parser, terminal-control and existing-report refusal checks from the former combined review test remain separately. The simulation-only evidence file `evidence/mock-export-resume.txt` was removed. No production CLI behavior or reusable real-fixture helpers were deleted.

Real Git, path, scanner, packing, schema/location, checkpoint I/O, accounting arithmetic, preview and export-safety tests remain in `tests/test_core.py`, `tests/test_pipeline.py` and `tests/test_privacy_real.py`. Deleting provider-response tests does **not** validate transport, response repairs, endpoint compatibility, in-flight usage/budgets, actual review export/checkpoint/session findings or exact resume. Those remain unverified by execution without a real endpoint. HTTP 429, 401/403, 5xx/timeouts and redirects are inspected only; none is deliberately induced against a live provider. See `agent.md` for explicit per-class status and Phase B prerequisites.
