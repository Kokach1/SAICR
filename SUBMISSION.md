# Project submission

Complete this file during the actual submission process announced by the organizers. Do not submit this project to the template repository. **Note:** this build occurred on 24 October 2026 UTC, after the event dates stated in `RULES.md`; it should not be represented as implementation started during that event.

## Project

- **Project name:** Review Desk
- **Short description:** A bounded, local-first code-review CLI that inspects tracked workspace changes, a merge-base range or one non-merge commit, applies deterministic selection and redaction before any endpoint call, then reports schema-validated findings at added new-file line numbers. It helps reviewers triage concrete possible defects without treating model output or source code as instructions.
- **Code repository URL:** https://github.com/Kokach1/SAICR
- **Final submitted implementation commit SHA:** To be filled after the final project implementation commit is chosen; current repository history is not final until the owner selects it.
- **Working demo URL or local demo steps:** Run `python fixtures/prepare_demo.py`, then `python -m reviewdesk preview --repo fixtures/demo`. This is a no-network preview, not a live AI review.
- **Demo access requirements:** Python 3.11+ and Git. Preview needs no credentials. Live review needs user-configured `LLM_BASE_URL`, `LLM_MODEL`, optionally `LLM_API_KEY`, plus explicit upload permission.

## Participants

| Participant name | GitHub handle | Contribution |
| --- | --- | --- |
| TODO | TODO | TODO |

## Run and demonstrate

- **Prerequisites and versions:** Python 3.11+ and Git; verified locally on Python 3.14.0, Git 2.52.0.windows.1.
- **Install command:** `python -m pip install -e '.[test]'`
- **Required environment variable names:** None for preview; `LLM_BASE_URL`, `LLM_MODEL`, optional `LLM_API_KEY`, `REVIEWDESK_CACHE_DIR`, `REVIEWDESK_ACCOUNT_LABEL` for a separately configured live review.
- **Start command:** `python -m reviewdesk --help`; no-network demo uses `python -m reviewdesk preview --repo fixtures/demo`.
- **Demo walkthrough:** Run `python fixtures/prepare_demo.py`, run preview, and verify `example.py` is listed as included with an explicit no-request warning. For a locally permitted mock review check, run `python -m pytest -q tests/test_pipeline.py::test_t12_cli_export_and_resume_with_mock_http`.
- **Checks performed and results:** `python -m pytest -q`: 28 passed; no-network preview produced a JSON preview; mock export/resume passed. Sanitized evidence is under `evidence/`.
- **Known limitations or incomplete features:** No live provider or quality evaluation was run. Scanner heuristics cannot guarantee secrets are absent. Deferred features and gaps are listed in `README.md` and `agent.md`.
- **Libraries, APIs, and public datasets used:** Pydantic 2.14.1, httpx 0.28.1 and pytest 9.1.1 installed from PyPI under their own licenses; no public datasets. Uses the OpenAI-compatible chat-completions protocol only when explicitly configured; no API call was made during the recorded checks.
- **AI usage record:** [AI_USAGE.md](AI_USAGE.md)
- **Development change log:** [CHANGELOG.md](CHANGELOG.md)

## Submission checklist

- [ ] The project implementation started from scratch at the event. **Not applicable/accurate to assert for this repository: build timestamp was 24 October 2026 UTC, after the listed event window.**
- [ ] I participated solo or with no more than 4 team members in total.
- [x] An AI assistant was used during development and its usage is documented. The assistant was Devin, not Codex.
- [x] The code repository URL, short description, and working demo are provided.
- [x] README setup and demo instructions match the submitted code.
- [x] Actual checks and known limitations are documented.
- [x] Meaningful changes are documented and committed throughout development.
- [ ] The final implementation is committed and pushed, and its SHA is recorded above.
- [x] No credentials or private data are included in the repository or demo instructions.
- [ ] The organizers' announced submission method and timing have been followed.
