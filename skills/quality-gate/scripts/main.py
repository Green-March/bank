"""CLI entrypoint for quality-gate skill."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

if __package__ in {None, ""}:
    _script_dir = Path(__file__).resolve().parent
    if str(_script_dir) not in sys.path:
        sys.path.insert(0, str(_script_dir))
    from validators import run_all_gates
else:
    from .validators import run_all_gates


def main() -> int:
    """Run quality gate CLI."""
    parser = argparse.ArgumentParser(
        description="Validate financial data against acceptance gates."
    )
    parser.add_argument(
        "--gates",
        type=str,
        required=True,
        help="Path to gates definition YAML file.",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        required=True,
        help="Directory containing financials.json and other data files.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output path for gate_results.json (default: stdout).",
    )
    args = parser.parse_args()

    gates_path = Path(args.gates)
    data_dir = Path(args.data_dir)

    if not gates_path.exists():
        print(f"Error: gates file not found: {gates_path}", file=sys.stderr)
        return 1
    if not data_dir.is_dir():
        print(f"Error: data directory not found: {data_dir}", file=sys.stderr)
        return 1

    with gates_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    gates_list = config.get("gates", [])
    if not gates_list:
        print("Error: no gates defined in config", file=sys.stderr)
        return 1

    results = run_all_gates(gates_list, data_dir)

    output = {
        "timestamp": datetime.now(UTC).isoformat(),
        "gates_file": str(gates_path),
        "data_dir": str(data_dir),
        "overall_pass": results.overall_pass,
        "gates": results.gates,
    }

    output_json = json.dumps(output, ensure_ascii=False, indent=2)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            f.write(output_json)
        print(f"Results written to {out_path}")
        print(f"Overall: {'PASS' if results.overall_pass else 'FAIL'}")
    else:
        print(output_json)

    return 0 if results.overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
