# Change log

Record each meaningful project change during development, newest first. This project was built on 24 October 2026 UTC after the referenced event window; this log therefore records observed implementation work, not event eligibility.

## 2026-10-24T17:12:00+00:00 — Add hackathon documentation scaffold

- Changed: Added `RULES.md`, `AGENTS.md`, `.github/pull_request_template.md`, `CHANGELOG.md`, `AI_USAGE.md`, and `SUBMISSION.md`; aligned `README.md` and `.gitignore` with the template structure.
- Why: Apply the supplied DevDay Kochi template documentation format.
- Validation: Cloned template commit `416329035c57c5cc82e42289bcf38d9cf5587011`; documented files were reviewed locally. Project test suite is rerun before commit.
- Limitations: Template requires project/team placeholders to be completed by the owner. Event-specific "Codex" and in-event development checkboxes are not asserted.

## 2026-10-24T16:30:15+00:00 — Implement Review Desk CLI

- Changed: Implemented the Python CLI, strict records, bounded Git capture, path and content selection, privacy gate, packing, request construction, transport, validation, checkpointing, usage accounting, orchestration and reporting; added deterministic mocked tests and sanitized evidence.
- Why: Build a local-first bounded code review prototype.
- Validation: `python -m pytest -q` produced 28 passed in 23.91s. Preview and mock export/resume checks are recorded under `evidence/`.
- Limitations: Scanner coverage is heuristic; live endpoint compatibility and quality were not tested. See `agent.md` for details.
