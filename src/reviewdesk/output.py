"""CLI and terminal-safe report rendering."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from .checkpoints import RUN_ID, CheckpointWriteError, cache_dir
from .contracts import ReviewOptions, RunResult
from .privacy import sanitize_output
from .runner import execute_review
from .settings import load_settings


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reviewdesk", description="Bounded AI code review")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("review", "preview"):
        command = commands.add_parser(name)
        command.add_argument("--repo", type=Path, required=True)
        revisions = command.add_mutually_exclusive_group()
        revisions.add_argument("--commit")
        revisions.add_argument("--from", dest="from_ref")
        command.add_argument("--to", dest="to_ref")
        command.add_argument("--exclude", action="append", default=[])
        command.add_argument("--model")
        command.add_argument("--base-url")
        command.add_argument("--schema-mode", choices=("text", "json_object", "json_schema"), default="text")
        command.add_argument("--max-output-tokens", type=int, default=1500)
        command.add_argument("--max-output-parameter", choices=("max_tokens", "max_completion_tokens"),
                             default="max_tokens")
        command.add_argument("--max-tokens-budget", type=int)
        command.add_argument("--input-per-million", help="User-supplied input-token rate")
        command.add_argument("--output-per-million", help="User-supplied output-token rate")
        command.add_argument("--price-currency", help="Currency of both supplied rates")
        command.add_argument("--price-as-of", help="ISO date for both supplied rates")
        command.add_argument("--allow-hosted-upload", action="store_true")
        command.add_argument("--allow-loopback-http", action="store_true")
        command.add_argument("--retry-uncertain", action="store_true")
        command.add_argument("--resume")
        command.add_argument("--format", choices=("text", "json"), default="text")
        command.add_argument("--output", type=Path)
        command.add_argument("--overwrite", action="store_true")
    sessions = commands.add_parser("sessions")
    sub = sessions.add_subparsers(dest="session_command", required=True)
    sub.add_parser("list")
    show = sub.add_parser("show")
    show.add_argument("run_id")
    return parser


def _terminal(text: str) -> str:
    return "".join(c if c >= " " and c != "\x7f" else "\\x%02x" % ord(c) for c in text)


def render_report(result: RunResult, format: str) -> str:
    result = sanitize_output(result)
    if format == "json":
        return result.model_dump_json(indent=2)
    lines = ["Review Desk | " + ("PARTIAL" if result.partial else "COMPLETE"),
             "Run: " + _terminal(result.run_id or "preview"),
             "Revision: " + _terminal(result.revision["mode"])]
    for decision in result.decisions:
        lines.append(("Included: " if decision.included else "Skipped: ") +
                     _terminal(decision.path) + " (" + decision.reason + ")")
    for redaction in result.redactions:
        lines.append(f"Redacted: {_terminal(redaction.path)}:{redaction.line} ({redaction.rule_id})")
    for finding in result.findings:
        lines.append(f"{_terminal(finding.path)}:{finding.start_line}-{finding.end_line} "
                     f"[{finding.severity}] {_terminal(finding.title)}")
        lines.append("  " + _terminal(finding.explanation))
        if finding.suggestion:
            lines.append("  Suggestion (inert): " + _terminal(finding.suggestion))
    for error in result.bundle_errors:
        lines.append("Error: " + error.code + " " + _terminal(error.message))
    lines.extend("Notice: " + _terminal(w) for w in result.warnings)
    lines.append("Usage: " + (f"{result.usage.known_input} input, {result.usage.known_output} output"
                               if result.usage.complete else "incomplete (unknown attempts)"))
    if result.cost.complete:
        lines.append(f"Estimated cost: {result.cost.amount} {result.cost.currency} "
                     f"(rates as of {result.cost.as_of}; {result.cost.omitted_charges})")
    else:
        lines.append("Estimated cost: unknown (" + (result.cost.reason or "no complete rates") + ")")
    return "\n".join(lines)


def write_report(destination: Path, result: RunResult, overwrite: bool = False) -> None:
    result = sanitize_output(result)
    parent = destination.parent.resolve(strict=True)
    if destination.is_symlink() or (destination.exists() and not overwrite):
        raise OSError("Report exists or destination is symlink")
    raw = render_report(result, "json").encode()
    fd, name = tempfile.mkstemp(prefix=".report-", dir=parent)
    try:
        os.chmod(name, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if destination.is_symlink() or (destination.exists() and not overwrite):
            raise OSError("Report destination changed")
        os.replace(name, destination)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    if args.command == "sessions":
        cache = cache_dir()
        if args.session_command == "list":
            for path in sorted(cache.glob("*.json")) if cache.exists() else ():
                if RUN_ID.fullmatch(path.stem):
                    print(path.stem)
            return 0
        if not RUN_ID.fullmatch(args.run_id):
            parser.error("Invalid run ID")
        path = cache / (args.run_id + ".json")
        if not path.exists() or path.is_symlink() or path.stat().st_size > 1048576:
            parser.error("Unsafe or missing session")
        from .contracts import Checkpoint
        state = Checkpoint.model_validate_json(path.read_bytes())
        print(json.dumps({"run_id": state.run_id, "complete": state.complete,
                          "bundles": [{"id": b.id, "status": b.status, "attempts": b.attempts}
                                      for b in state.bundle_states]}, indent=2))
        return 0
    if bool(args.from_ref) != bool(args.to_ref) or (args.commit and args.to_ref):
        parser.error("--from and --to must appear together, and exclude --commit")
    mode = "commit" if args.commit else "range" if args.to_ref else "workspace"
    try:
        options = ReviewOptions(repo=args.repo, mode=mode, from_ref=args.from_ref, to_ref=args.to_ref,
                                commit_ref=args.commit, exclude=args.exclude,
                                preview=args.command == "preview", resume_id=args.resume)
        config = load_settings(args, os.environ)
        result = asyncio.run(execute_review(options, config))
    except CheckpointWriteError:
        print("Checkpoint write failed; review stopped.", file=sys.stderr)
        return 3
    except (ValueError, OSError):
        # Never print raw exception text from paths, providers or filesystem.
        print("Review configuration, snapshot or checkpoint failed; check inputs and permissions.", file=sys.stderr)
        return 2
    print(render_report(result, args.format))
    if args.output:
        try:
            if args.output.resolve().is_relative_to(args.repo.resolve()):
                raise OSError("Report must be outside target repository")
            write_report(args.output, result, args.overwrite)
        except (OSError, ValueError):
            print("Report export failed; check destination and permissions.", file=sys.stderr)
            return 3
    return 1 if result.partial else 0
