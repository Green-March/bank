"""CLI entrypoint for pipeline-runner skill."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running as script from project root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline import PipelineConfig, PipelineError, PipelineRunner, format_status


def cmd_run(args: argparse.Namespace) -> None:
    """Execute a pipeline."""
    vars_dict: dict[str, str] = {}
    if args.vars:
        for pair in args.vars.split(","):
            pair = pair.strip()
            if "=" not in pair:
                print(f"Error: invalid var format '{pair}', expected key=value", file=sys.stderr)
                sys.exit(1)
            key, value = pair.split("=", 1)
            vars_dict[key.strip()] = value.strip()

    try:
        config = PipelineConfig.load(args.pipeline)
    except (PipelineError, FileNotFoundError, Exception) as e:
        print(f"Error loading pipeline: {e}", file=sys.stderr)
        sys.exit(1)

    runner = PipelineRunner()
    try:
        log = runner.run(config, vars_dict, log_path=args.log)
    except PipelineError as e:
        print(f"Pipeline error: {e}", file=sys.stderr)
        sys.exit(1)

    print(format_status(log))

    if log["status"] not in ("completed",):
        sys.exit(1)


def cmd_validate(args: argparse.Namespace) -> None:
    """Validate a pipeline definition."""
    try:
        config = PipelineConfig.load(args.pipeline)
    except (PipelineError, FileNotFoundError, Exception) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    errors = config.validate_dag()
    if errors:
        for err in errors:
            print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    print(f"Pipeline '{config.name}' is valid ({len(config.steps)} steps)")


def cmd_status(args: argparse.Namespace) -> None:
    """Show execution status from a log file."""
    log_path = Path(args.log)
    if not log_path.exists():
        print(f"Error: log file not found: {args.log}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(log_path, "r", encoding="utf-8") as f:
            log = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error reading log: {e}", file=sys.stderr)
        sys.exit(1)

    print(format_status(log))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pipeline-runner",
        description="Execute multi-step skill pipelines defined as a DAG.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run
    run_parser = subparsers.add_parser("run", help="Execute a pipeline")
    run_parser.add_argument("--pipeline", required=True, help="Path to pipeline.yaml")
    run_parser.add_argument("--vars", default=None, help="Variables as key=val,key=val")
    run_parser.add_argument("--log", default=None, help="Path to write execution log JSON")

    # validate
    val_parser = subparsers.add_parser("validate", help="Validate a pipeline definition")
    val_parser.add_argument("--pipeline", required=True, help="Path to pipeline.yaml")

    # status
    stat_parser = subparsers.add_parser("status", help="Show execution status")
    stat_parser.add_argument("--log", required=True, help="Path to execution log JSON")

    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args)
    elif args.command == "validate":
        cmd_validate(args)
    elif args.command == "status":
        cmd_status(args)


if __name__ == "__main__":
    main()
