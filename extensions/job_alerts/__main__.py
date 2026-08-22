"""Command-line interface for the isolated job alert extension."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from .config import (
    DEFAULT_CONFIG_PATH,
    import_saved_search,
    load_config,
    profile_needs_playwright,
)
from .cv_secret import prepare_cv_file, upload_cv_secret
from .email_sender import build_test_message, send_message, settings_from_env
from .state import DEFAULT_STATE_PATH, due_profiles, load_state


def _add_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)


def _write_github_output(path: str, values: dict[str, str]) -> None:
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def _print_results(results) -> int:
    failures = 0
    for result in results:
        print(
            f"{result.profile_id}: {result.status}; found={result.found}; "
            f"qualifying={result.qualifying}; selected={result.selected}; "
            f"emailed={result.emailed}"
        )
        if result.error:
            print(f"  error: {result.error}")
            failures += 1
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Isolated Job Finder email alerts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check-due", help="Report whether any profiles are due")
    _add_paths(check)
    check.add_argument("--github-output", default=os.getenv("GITHUB_OUTPUT", ""))
    check.add_argument("--profile-id", default="")

    run_due = subparsers.add_parser("run-due", help="Run all due enabled profiles")
    _add_paths(run_due)
    run_due.add_argument("--dry-run", action="store_true")

    run_one = subparsers.add_parser("run-profile", help="Run one profile immediately")
    _add_paths(run_one)
    run_one.add_argument("--id", required=True, dest="profile_id")
    run_one.add_argument("--dry-run", action="store_true")

    subparsers.add_parser("test-email", help="Send a Gmail SMTP test message")

    prepare = subparsers.add_parser("prepare-cv", help="Upload compressed CV text as a secret")
    prepare.add_argument("--file", required=True, type=Path)
    prepare.add_argument("--output", type=Path)

    imported = subparsers.add_parser("import-search", help="Copy a local saved search")
    imported.add_argument("--name", required=True)
    imported.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    imported.add_argument("--saved-searches", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = build_parser().parse_args(argv)

    if args.command == "check-due":
        config = load_config(args.config)
        state = load_state(args.state)
        if args.profile_id:
            profiles = [
                profile
                for profile in config["profiles"]
                if profile["id"] == args.profile_id
            ]
            if not profiles:
                raise SystemExit(f"Unknown profile id: {args.profile_id}")
        else:
            profiles = due_profiles(config, state)
        values = {
            "due": str(bool(profiles)).lower(),
            "needs_playwright": str(
                any(profile_needs_playwright(profile) for profile in profiles)
            ).lower(),
            "profile_ids": ",".join(profile["id"] for profile in profiles),
        }
        _write_github_output(args.github_output, values)
        print(
            f"due={values['due']} needs_playwright={values['needs_playwright']} "
            f"profiles={values['profile_ids'] or '-'}"
        )
        return 0

    if args.command in {"run-due", "run-profile"}:
        from .runner import run_profiles

        config = load_config(args.config)
        state = load_state(args.state)
        if args.command == "run-due":
            profiles = due_profiles(config, state)
        else:
            profiles = [
                profile
                for profile in config["profiles"]
                if profile["id"] == args.profile_id
            ]
            if not profiles:
                raise SystemExit(f"Unknown profile id: {args.profile_id}")
        if not profiles:
            print("No alert profiles are due.")
            return 0
        return _print_results(
            run_profiles(profiles, state, args.state, dry_run=args.dry_run)
        )

    if args.command == "test-email":
        settings = settings_from_env()
        send_message(build_test_message(settings), settings)
        print(f"Test email sent to {settings.recipient}")
        return 0

    if args.command == "prepare-cv":
        if args.output:
            encoded = prepare_cv_file(args.file)
            args.output.write_text(encoded, encoding="ascii")
            print(
                f"Secret value written to {args.output}. Delete it after adding the "
                "GitHub Actions secret."
            )
        else:
            upload_cv_secret(args.file)
            print("JOBFINDER_CV_GZIP_BASE64 updated through GitHub CLI.")
        return 0


    profile_id = import_saved_search(
        args.name,
        config_path=args.config,
        saved_searches_path=args.saved_searches,
    )
    print(f"Imported saved search as disabled alert profile: {profile_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
