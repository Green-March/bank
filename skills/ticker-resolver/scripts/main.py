#!/usr/bin/env python3
"""ticker-resolver CLI: 銘柄コード → edinet_code / company_name / fye_month 解決."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Dual-run support: direct script execution & package import
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    _script_dir = Path(__file__).resolve().parent
    if str(_script_dir) not in sys.path:
        sys.path.insert(0, str(_script_dir))
    from resolver import TickerResolver, TickerNotFoundError, CacheExpiredError, NetworkError
else:
    from .resolver import TickerResolver, TickerNotFoundError, CacheExpiredError, NetworkError

from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    """Return the repository root (4 levels up from this file)."""
    return Path(__file__).resolve().parents[3]


def _data_root() -> Path:
    """Return the data directory, honouring DATA_PATH env var."""
    configured = os.environ.get("DATA_PATH")
    if not configured:
        return _repo_root() / "data"
    path = Path(configured).expanduser()
    if path.is_absolute():
        return path
    return (_repo_root() / path).resolve()


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def _handle_resolve(args: argparse.Namespace) -> int:
    """resolve サブコマンド: ticker → 企業情報."""
    resolver = TickerResolver(cache_dir=_data_root() / ".ticker_cache")
    result = resolver.resolve(args.ticker)

    if args.output_format == "json":
        print(json.dumps(result, ensure_ascii=False))
    else:
        fye = f"{result['fye_month']}月" if result["fye_month"] else "不明"
        print(f"銘柄コード:   {result['sec_code'][:4]}")
        print(f"証券コード:   {result['sec_code']}")
        print(f"EDINETコード: {result['edinet_code']}")
        print(f"企業名:       {result['company_name']}")
        print(f"決算月:       {fye}")
    return 0


def _handle_update(args: argparse.Namespace) -> int:
    """update サブコマンド: キャッシュ更新."""
    resolver = TickerResolver(cache_dir=_data_root() / ".ticker_cache")
    count = resolver.update_cache(source=args.source, force=args.force)
    if count == 0:
        print("キャッシュは有効期限内です。強制更新するには --force を指定してください。")
    else:
        print(f"キャッシュを更新しました（{count}件）")
    return 0


def _handle_list(args: argparse.Namespace) -> int:
    """list サブコマンド: キャッシュ内全銘柄一覧."""
    resolver = TickerResolver(cache_dir=_data_root() / ".ticker_cache")
    entries = resolver.list_all(fye_month=args.fye_month)

    if args.output_format == "json":
        print(json.dumps(entries, ensure_ascii=False, indent=2))
    else:
        if not entries:
            print("キャッシュにデータがありません。update サブコマンドでキャッシュを更新してください。")
            return 0
        print(f"{'ticker':<8} {'sec_code':<10} {'edinet_code':<16} {'fye':<6} {'company_name'}")
        print("-" * 72)
        for e in entries:
            fye = f"{e['fye_month']}月" if e["fye_month"] else "N/A"
            print(f"{e['ticker']:<8} {e['sec_code']:<10} {e['edinet_code']:<16} {fye:<6} {e['company_name']}")
        print(f"\n合計: {len(entries)}件")
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with resolve / update / list subcommands."""
    parser = argparse.ArgumentParser(
        description="ticker-resolver: 銘柄コード → edinet_code / company_name / fye_month 解決",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # -- resolve --------------------------------------------------------
    p_resolve = subparsers.add_parser("resolve", help="銘柄コードから企業情報を解決")
    p_resolve.add_argument(
        "ticker",
        help="銘柄コード（4桁、例: 7203）",
    )
    p_resolve.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        dest="output_format",
        help="出力形式（デフォルト: json）",
    )
    p_resolve.set_defaults(func=_handle_resolve)

    # -- update ---------------------------------------------------------
    p_update = subparsers.add_parser("update", help="キャッシュを更新")
    p_update.add_argument(
        "--source",
        choices=["edinet", "jquants", "all"],
        default="all",
        help="データソース（デフォルト: all）",
    )
    p_update.add_argument(
        "--force",
        action="store_true",
        help="キャッシュ有効期限を無視して強制更新",
    )
    p_update.set_defaults(func=_handle_update)

    # -- list -----------------------------------------------------------
    p_list = subparsers.add_parser("list", help="キャッシュ内の全銘柄を一覧表示")
    p_list.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        dest="output_format",
        help="出力形式（デフォルト: text）",
    )
    p_list.add_argument(
        "--fye-month",
        type=int,
        choices=range(1, 13),
        metavar="{1..12}",
        help="決算月でフィルタ（1-12）",
    )
    p_list.set_defaults(func=_handle_list)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    """CLI entry point. Returns 0 on success, 1 on error."""
    parser = build_parser()
    args = parser.parse_args()

    try:
        return args.func(args)
    except TickerNotFoundError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1
    except CacheExpiredError:
        print(
            "エラー: キャッシュを更新してください (update サブコマンド)",
            file=sys.stderr,
        )
        return 1
    except NetworkError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
