#!/usr/bin/env python3
"""risk-analyzer CLI entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    from analyzer import run_analysis
else:
    from .analyzer import run_analysis


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def _data_root() -> Path:
    import os
    return Path(os.environ.get("DATA_PATH", _repo_root() / "data"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="risk-analyzer: 有価証券報告書のリスクテキストを抽出・分類",
    )
    sub = parser.add_subparsers(dest="command")

    analyze = sub.add_parser("analyze", help="リスク分析を実行")
    analyze.add_argument("--ticker", required=True, help="銘柄コード")
    analyze.add_argument("--input-dir", type=Path, help="XBRL ZIP ディレクトリ")
    analyze.add_argument("--parsed-json", type=Path, help="disclosure-parser の financials.json")
    analyze.add_argument("--output", type=Path, help="出力先JSONファイルパス")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    if args.command == "analyze":
        if not args.input_dir and not args.parsed_json:
            print("Error: --input-dir or --parsed-json のいずれかを指定してください", file=sys.stderr)
            return 1

        result = run_analysis(
            ticker=args.ticker,
            input_dir=args.input_dir,
            parsed_json=args.parsed_json,
        )

        output_dict = result.to_dict()

        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(output_dict, f, ensure_ascii=False, indent=2)
            print(f"Output written to {args.output}")
        else:
            print(json.dumps(output_dict, ensure_ascii=False, indent=2))

        total = output_dict["summary"]["total_risks"]
        print(f"\nTotal risks identified: {total}", file=sys.stderr)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
