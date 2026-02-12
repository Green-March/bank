"""context-checkpoint CLI — save/load/list agent checkpoints."""

import argparse
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml


JST = timezone(timedelta(hours=9))

DEFAULT_CHECKPOINT_DIR = Path(__file__).resolve().parents[3] / "memory" / "checkpoints"


def _checkpoint_path(checkpoint_dir: Path, agent: str, task_id: str) -> Path:
    safe_name = f"{agent}_{task_id}.yaml"
    return checkpoint_dir / safe_name


def cmd_save(args: argparse.Namespace) -> int:
    checkpoint_dir = Path(args.checkpoint_dir)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "task_id": args.task_id,
        "agent_id": args.agent,
        "status": args.status,
        "key_findings": args.key_findings or [],
        "output_files": args.output_files or [],
        "next_steps": args.next_steps or [],
        "context_summary": args.context_summary or "",
        "timestamp": datetime.now(JST).isoformat(),
    }

    path = _checkpoint_path(checkpoint_dir, args.agent, args.task_id)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    print(f"Saved: {path}")
    return 0


def cmd_load(args: argparse.Namespace) -> int:
    checkpoint_dir = Path(args.checkpoint_dir)
    path = _checkpoint_path(checkpoint_dir, args.agent, args.task_id)

    if not path.exists():
        print(
            f"Error: checkpoint not found: {path}",
            file=sys.stderr,
        )
        return 1

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    yaml.dump(data, sys.stdout, allow_unicode=True, default_flow_style=False, sort_keys=False)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    checkpoint_dir = Path(args.checkpoint_dir)

    if not checkpoint_dir.exists():
        print("No checkpoints found.")
        return 0

    files = sorted(checkpoint_dir.glob("*.yaml"))

    if args.agent:
        prefix = f"{args.agent}_"
        files = [f for f in files if f.name.startswith(prefix)]

    if not files:
        print("No checkpoints found.")
        return 0

    for f in files:
        with open(f, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        agent = data.get("agent_id", "?")
        task = data.get("task_id", "?")
        status = data.get("status", "?")
        ts = data.get("timestamp", "?")
        print(f"{agent}/{task}  status={status}  timestamp={ts}  file={f.name}")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Save/load/list agent context checkpoints"
    )
    subparsers = parser.add_subparsers(dest="command")

    # save
    p_save = subparsers.add_parser("save", help="Save a checkpoint")
    p_save.add_argument("--agent", required=True, help="Agent ID (e.g. senior, junior1)")
    p_save.add_argument("--task-id", required=True, help="Task ID")
    p_save.add_argument(
        "--status",
        required=True,
        choices=["in_progress", "completed", "blocked"],
        help="Task status",
    )
    p_save.add_argument("--key-findings", action="append", default=None, help="Key finding (repeatable)")
    p_save.add_argument("--output-files", action="append", default=None, help="Output file path (repeatable)")
    p_save.add_argument("--next-steps", action="append", default=None, help="Next step (repeatable)")
    p_save.add_argument("--context-summary", default=None, help="Free-text context summary")
    p_save.add_argument(
        "--checkpoint-dir",
        default=str(DEFAULT_CHECKPOINT_DIR),
        help="Checkpoint directory",
    )

    # load
    p_load = subparsers.add_parser("load", help="Load a checkpoint")
    p_load.add_argument("--agent", required=True, help="Agent ID")
    p_load.add_argument("--task-id", required=True, help="Task ID")
    p_load.add_argument(
        "--checkpoint-dir",
        default=str(DEFAULT_CHECKPOINT_DIR),
        help="Checkpoint directory",
    )

    # list
    p_list = subparsers.add_parser("list", help="List checkpoints")
    p_list.add_argument("--agent", default=None, help="Filter by agent ID")
    p_list.add_argument(
        "--checkpoint-dir",
        default=str(DEFAULT_CHECKPOINT_DIR),
        help="Checkpoint directory",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "save":
        return cmd_save(args)
    if args.command == "load":
        return cmd_load(args)
    if args.command == "list":
        return cmd_list(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
