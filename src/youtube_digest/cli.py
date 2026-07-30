from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta

from youtube_digest.config import (
    interactive_configure,
    load_config,
)
from youtube_digest.doctor import run_checks
from youtube_digest.logging_utils import configure_logging
from youtube_digest.pipeline import run_pipeline
from youtube_digest.scheduler import install_task, remove_task, task_status
from youtube_digest.youtube import authorize


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="youtube-digest",
        description="Local YouTube finance/macro/trading digest.",
    )
    parser.add_argument("--verbose", action="store_true")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("configure", help="Configure local credentials and settings.")
    subcommands.add_parser("auth", help="Authorize the YouTube Data API.")
    subcommands.add_parser("doctor", help="Validate local services and credentials.")

    run = subcommands.add_parser("run", help="Discover, analyze, and deliver new videos.")
    run.add_argument("--since", type=_parse_datetime)
    run.add_argument("--no-send", action="store_true")

    backfill = subcommands.add_parser("backfill", help="Process a fixed historical window.")
    backfill.add_argument("--hours", type=float, default=24)
    backfill.add_argument("--no-send", action="store_true")

    schedule = subcommands.add_parser("schedule", help="Manage the Windows Scheduled Task.")
    schedule.add_argument("action", choices=("install", "status", "remove"))
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "configure":
            path = interactive_configure()
            print(f"Configuration saved to {path}")
            return 0

        config = load_config()
        logger = configure_logging(config.log_dir, args.verbose)

        if args.command == "auth":
            authorize(config.oauth_client_path, config.oauth_token_path)
            print(f"OAuth token saved to {config.oauth_token_path}")
            return 0

        if args.command == "doctor":
            checks = run_checks(config, logger)
            for check in checks:
                marker = "PASS" if check.ok else "FAIL"
                print(f"[{marker}] {check.name}: {check.detail}")
            return 0 if all(check.ok for check in checks) else 1

        if args.command == "run":
            result = run_pipeline(
                config,
                logger,
                since=args.since,
                no_send=args.no_send,
            )
            for message in result.preview_messages:
                print(message)
                print()
            print(
                f"run={result.run_id} discovered={result.discovered} "
                f"delivered={result.delivered} failures={len(result.failures)}"
            )
            return 0 if not result.failures else 2

        if args.command == "backfill":
            if args.hours <= 0:
                parser.error("--hours must be positive")
            result = run_pipeline(
                config,
                logger,
                since=datetime.now(UTC) - timedelta(hours=args.hours),
                no_send=args.no_send,
            )
            for message in result.preview_messages:
                print(message)
                print()
            print(
                f"run={result.run_id} discovered={result.discovered} "
                f"delivered={result.delivered} failures={len(result.failures)}"
            )
            return 0 if not result.failures else 2

        if args.command == "schedule":
            if args.action == "install":
                print(install_task(config.digest_time))
            elif args.action == "remove":
                print(remove_task())
            else:
                print(task_status())
            return 0

        parser.error(f"Unknown command: {args.command}")
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0
