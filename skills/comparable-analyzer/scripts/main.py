"""comparable-analyzer CLI: 業種コードから比較企業群を選定し財務指標ベンチマーク比較."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

if __name__ == "__main__":
    _script_dir = Path(__file__).resolve().parent
    if str(_script_dir) not in sys.path:
        sys.path.insert(0, str(_script_dir))
    from analyzer import (  # type: ignore[import-untyped]
        CacheNotFoundError,
        TickerNotFoundError,
        run_analysis,
    )
else:
    from .analyzer import CacheNotFoundError, TickerNotFoundError, run_analysis

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import argparse


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _data_root() -> Path:
    configured = os.environ.get("DATA_PATH")
    if not configured:
        return _repo_root() / "data"
    path = Path(configured).expanduser()
    if path.is_absolute():
        return path
    return (_repo_root() / path).resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="業種コードから比較企業群を自動選定し、財務指標ベンチマーク比較を行う",
    )
    parser.add_argument(
        "--ticker",
        required=True,
        help="4桁ティッカーコード (例: 7203)",
    )
    parser.add_argument(
        "--max-peers",
        type=int,
        default=10,
        help="最大比較企業数 (デフォルト: 10)",
    )
    parser.add_argument(
        "--data-root",
        type=str,
        default=None,
        help="データルートパス (デフォルト: <repo_root>/data)",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    data_root = Path(args.data_root) if args.data_root else _data_root()

    try:
        result = run_analysis(
            data_root=data_root,
            ticker=args.ticker,
            max_peers=args.max_peers,
        )
    except CacheNotFoundError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1
    except TickerNotFoundError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1

    out_path = data_root / args.ticker / "parsed" / "comparables.json"
    print(f"出力: {out_path}")
    print(f"比較企業数: {result['peer_count']}/{result['max_peers_requested']}")
    if result["warnings"]:
        for w in result["warnings"]:
            print(f"  警告: {w}")

    target = result["target"]
    print(f"\n対象: {target['ticker']} {target['company_name']} ({target['industry']})")

    benchmarks = result["benchmarks"]
    if benchmarks:
        print("\nベンチマーク:")
        for metric, stats in benchmarks.items():
            pct = stats.get("target_percentile")
            pct_str = f"{pct}%" if pct is not None else "N/A"
            median = stats.get("median")
            median_str = f"{median}" if median is not None else "N/A"
            print(f"  {metric}: median={median_str}, percentile={pct_str}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
