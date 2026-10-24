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

Dependencies are installed separately by pip under their respective licenses; this repository does not vendor or remove their license, copyright or notice files. `fixtures/prepare_demo.py` creates a **synthetic local Git repository** under `fixtures/demo` with one uncommitted defect; it is not a live AI result. The nested repository is intentionally not committed as a Git submodule. If an existing demo fixture is found, the preparation script leaves it unchanged; when creating one, it refuses unexpected file contents.

## Revision semantics

* `reviewdesk preview --repo fixtures/demo` inspects the same bounded Git snapshot as review, with no model configuration or HTTP client. Preview does not run reviewed scripts.
* `reviewdesk review --repo PATH` compares tracked staged and unstaged workspace changes with `HEAD` (untracked files excluded). A clean workspace has no bundles.
* `--from REF --to REF` compares `merge-base(REF, TARGET)` to the resolved target commit.
* `--commit REF` compares one non-merge commit with its parent; a root commit is compared with the empty tree. Merge commits are rejected.

Historical contents come from target Git blobs, not current workspace files. For workspace mode the program checks each bounded regular file before and after capture and compares the diff metadata again; changed snapshots fail rather than return mismatched content. Renames are reported at target paths. Deletion-only findings cannot be placed on an added line and are not supported.

Example of a **mocked**, no-hosted-request review/export/resume verification:

```sh
python -m pytest -q tests/test_pipeline.py::test_t12_cli_export_and_resume_with_mock_http
```

For an actual explicitly permitted local inference server, set `LLM_BASE_URL`, `LLM_MODEL` and optionally `LLM_API_KEY`, then use `reviewdesk review --repo fixtures/demo --allow-loopback-http --output review-result.json`. This example has **not** been executed against a running server. Do not treat a local server as automatically free or safe. For HTTPS endpoints outside loopback, add `--allow-hosted-upload` for that invocation; this is permission for transmitting selected code. No provider/model, prices, free credits or availability are assumed. No live API call was made during development.

Endpoint URL must be a bare HTTPS origin (for example an origin with no path) or an explicitly allowed loopback HTTP origin. HTTP redirects are not followed. Providers differ: start with default `--schema-mode text`; `json_object` and `json_schema` are opt-in, and unsupported options fail rather than silently downgrade. Choose `--max-output-parameter max_tokens` or `max_completion_tokens` to match your server. `--max-output-tokens` defaults to 1500.

`--output PATH` writes JSON atomically outside the reviewed repository, refusing an existing destination unless `--overwrite` is specified. `--format json` prints a versioned JSON report. `reviewdesk sessions list` and `reviewdesk sessions show RUN_ID` inspect private checkpoints. `--resume RUN_ID` requires an exact snapshot, model, endpoint and request configuration match. A previously running or ambiguously delivered request requires `--retry-uncertain`; a second request may incur duplicate charges. A bundle makes at most two HTTP attempts, including repair/retry.

## Coverage, privacy and limits

Credential paths (`.env`, `.env.*`, `*.pem`, `*.key`, `id_rsa*`, `*.p12`, `*.pfx`, `credentials*`, `secrets*`, `*.keystore`, `.aws/**`, `.ssh/**`) are hard-excluded. Lockfiles, binary files, deletions, symlinks, submodules and user `--exclude GLOB` matches are skipped with reason codes. More than 50 selected files, 1 MiB per selected file or 5 MiB in total is rejected; a single oversized bundle is explicitly skipped. Bundles contain at most five files, 800 patch lines and 200 KiB serialized safe documents. Outbound bodies are limited to 300 KiB and responses to 512 KiB. Scanner rules look for common token/password forms and private-key delimiters, redact while preserving line count and exclude detected key blocks. These heuristics cannot guarantee the absence of secrets; inspect preview and choose exclusions before permitting uploads. No raw prompts, code or model replies are saved in checkpoints.

Git is invoked through a fixed executable path with argv, a timeout, size limits and disabled external diffs/textconv/hooks; repositories with registered filter commands or filter attributes are rejected. Do not execute reviewed-repository scripts, tests or commands: only controlled test fixtures run. Repository content and model text are untrusted data, not tool instructions. Suggestions are never applied. This version does not implement untracked files, merge commits, whole-repository scans, autonomous commands/tools, automatic fixes, CI/IDE/MCP/hosted-service integrations, a web UI or translation.

`--max-tokens-budget N` is a **soft** provider-reported input-plus-output token cap. It stops subsequent sequential dispatch on the cap or on unknown usage; an in-flight call can overshoot. It is not a dollar limit, invoice or hard spend guarantee. Optional estimates require all four supplied fields: `--input-per-million RATE --output-per-million RATE --price-currency USD --price-as-of YYYY-MM-DD`. Missing rates or incomplete usage produces a null estimate. Estimates omit taxes, infrastructure and provider-specific charges. No static prices or assumed balance are included.

Exit codes: `0` complete or preview (including reviews with findings), `1` partial (failed/uncertain/budget-stopped bundles), `2` invalid/unsafe configuration or snapshot, `3` checkpoint or report write failure. Errors deliberately omit raw provider messages. State is stored in the platform user cache under `reviewdesk/runs`, configurable with `REVIEWDESK_CACHE_DIR` outside the reviewed repository. See [agent.md](agent.md) for verified commands, local evidence and limitations.

## Hackathon scaffold

This repository also applies the DevDay Exchange Community Kochi template for workflow and submission documents. See [RULES.md](RULES.md), [AGENTS.md](AGENTS.md), [CHANGELOG.md](CHANGELOG.md), [AI_USAGE.md](AI_USAGE.md), [SUBMISSION.md](SUBMISSION.md), and [.github/pull_request_template.md](.github/pull_request_template.md). Template source: `anima-regem/devday-kochi-hackathon-template`, commit `416329035c57c5cc82e42289bcf38d9cf5587011`.

**Important caveat:** this repository was implemented on 24 October 2026 UTC, after the event dates listed in `RULES.md`; it is not represented as code begun during that event. Team fields and final submitted commit selection in `SUBMISSION.md` remain for the owner to complete. No Codex usage is claimed; `AI_USAGE.md` records Devin assistance.
