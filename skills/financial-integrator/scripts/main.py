from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

if __name__ == "__main__":
    script_dir = Path(__file__).resolve().parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    from exceptions import IntegrationError
    from integrator import integrate
else:
    from .exceptions import IntegrationError
    from .integrator import integrate

load_dotenv()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_root(env_name: str, fallback_dirname: str) -> Path:
    configured = os.environ.get(env_name)
    if not configured:
        return _repo_root() / fallback_dirname
    path = Path(configured).expanduser()
    if path.is_absolute():
        return path
    return (_repo_root() / path).resolve()


def _data_root() -> Path:
    return _resolve_root("DATA_PATH", "data")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="EDINET + J-Quants 財務データ統合"
    )
    parser.add_argument(
        "--ticker", required=True, help="銘柄コード（例: 2780）"
    )
    parser.add_argument(
        "--fye-month",
        required=True,
        type=int,
        help="決算月（例: 3, 12）",
    )
    parser.add_argument(
        "--parsed-dir",
        default=None,
        help="入力ディレクトリ（省略時: data/{ticker}/parsed）",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="出力JSONパス（省略時: data/{ticker}/parsed/integrated_financials.json）",
    )
    parser.add_argument(
        "--company-name",
        default=None,
        help="会社名（省略時: ticker を使用）",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    data_root = _data_root()
    ticker = str(args.ticker)

    parsed_dir = (
        Path(args.parsed_dir)
        if args.parsed_dir
        else (data_root / ticker / "parsed")
    )
    output_path = (
        Path(args.output)
        if args.output
        else (data_root / ticker / "parsed" / "integrated_financials.json")
    )

    try:
        result = integrate(
            ticker=ticker,
            fye_month=args.fye_month,
            parsed_dir=parsed_dir,
            output_path=output_path,
            company_name=args.company_name,
        )
    except IntegrationError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1

    annual_count = len(result.get("annual", []))
    quarterly_count = len(result.get("quarterly", []))
    print(f"統合完了: {output_path}")
    print(f"Annual: {annual_count}, Quarterly: {quarterly_count}")

    coverage = result.get("integration_metadata", {}).get(
        "coverage_summary", {}
    )
    for fy_key in sorted(coverage.keys()):
        cs = coverage[fy_key]
        print(
            f"  {fy_key}: annual={cs['annual']}, quarters={cs['quarters']}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
