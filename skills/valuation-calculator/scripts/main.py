"""valuation-calculator CLI エントリポイント

Usage:
    python3 scripts/main.py dcf --metrics <metrics.json> [--wacc 0.08] [--growth-rate 0.02] [--output <output.json>]
    python3 scripts/main.py relative --metrics <metrics.json> [--peers <peer1.json> ...] [--output <output.json>]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

if __name__ == "__main__":
    script_dir = Path(__file__).resolve().parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    from valuation import (
        compute_dcf,
        compute_peer_comparison,
        compute_relative_metrics,
        extract_fcf_series,
        extract_net_debt,
    )
else:
    from .valuation import (
        compute_dcf,
        compute_peer_comparison,
        compute_relative_metrics,
        extract_fcf_series,
        extract_net_debt,
    )


def _load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_output(data: dict, output_path: str | None) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(text + "\n", encoding="utf-8")
        print(f"Written to {output_path}", file=sys.stderr)
    print(text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="DCF・相対バリュエーション計算ツール"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- dcf ---
    dcf_p = subparsers.add_parser("dcf", help="DCF（割引キャッシュフロー）計算")
    dcf_p.add_argument("--metrics", required=True, help="financial-calculator の metrics.json パス")
    dcf_p.add_argument("--wacc", type=float, default=0.08, help="加重平均資本コスト (default: 0.08)")
    dcf_p.add_argument("--growth-rate", type=float, default=0.02, help="永久成長率 (default: 0.02)")
    dcf_p.add_argument("--projection-years", type=int, default=5, help="FCF予測期間 (default: 5)")
    dcf_p.add_argument("--shares", type=float, default=None, help="発行済株式数（1株あたり価値算出用）")
    dcf_p.add_argument("--output", default=None, help="出力JSONファイルパス")

    # --- relative ---
    rel_p = subparsers.add_parser("relative", help="相対バリュエーション（PER/PBR/EV-EBITDA）計算")
    rel_p.add_argument("--metrics", required=True, help="対象銘柄の metrics.json パス")
    rel_p.add_argument("--peers", nargs="*", default=[], help="同業他社の metrics.json パス群")
    rel_p.add_argument("--output", default=None, help="出力JSONファイルパス")

    return parser


def cmd_dcf(args: argparse.Namespace) -> int:
    metrics = _load_json(args.metrics)
    fcf_series = extract_fcf_series(metrics)
    if not fcf_series:
        print("Error: metrics.json に free_cash_flow データがありません", file=sys.stderr)
        return 1

    net_debt = extract_net_debt(metrics)
    result = compute_dcf(
        fcf_series=fcf_series,
        wacc=args.wacc,
        terminal_growth_rate=args.growth_rate,
        net_debt=net_debt,
        shares_outstanding=args.shares,
        projection_years=args.projection_years,
    )

    output = {
        "ticker": metrics.get("ticker", "unknown"),
        "valuation_type": "dcf",
        **asdict(result),
    }
    _write_output(output, args.output)
    return 0


def cmd_relative(args: argparse.Namespace) -> int:
    metrics = _load_json(args.metrics)

    if args.peers:
        peer_data = [_load_json(p) for p in args.peers]
        result = compute_peer_comparison(metrics, peer_data)
        output = {
            "ticker": metrics.get("ticker", "unknown"),
            "valuation_type": "relative",
            "target": asdict(result.target),
            "peers": [asdict(p) for p in result.peers],
            "comparison": result.comparison,
        }
    else:
        rm = compute_relative_metrics(metrics)
        output = {
            "ticker": metrics.get("ticker", "unknown"),
            "valuation_type": "relative",
            **asdict(rm),
        }

    _write_output(output, args.output)
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "dcf":
        return cmd_dcf(args)
    elif args.command == "relative":
        return cmd_relative(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
