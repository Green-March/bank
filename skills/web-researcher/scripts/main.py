"""web-researcher メインスクリプト.

Web 上の企業情報を複数ソースから収集する CLI。
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

# スクリプト直接実行とパッケージインポートの両方に対応
if __name__ == "__main__":
    from collector_base import CollectorError
    from yahoo_finance import YahooFinanceCollector
    from kabutan import KabutanCollector
    from shikiho import ShikihoCollector
    from homepage import HomepageCollector
else:
    from .collector_base import CollectorError
    from .yahoo_finance import YahooFinanceCollector
    from .kabutan import KabutanCollector
    from .shikiho import ShikihoCollector
    from .homepage import HomepageCollector


JST = timezone(timedelta(hours=9))

SOURCE_MAP = {
    "yahoo": YahooFinanceCollector,
    "kabutan": KabutanCollector,
    "shikiho": ShikihoCollector,
    "homepage": HomepageCollector,
}

ALL_SOURCES = list(SOURCE_MAP.keys())


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


def _parse_sources(source_str: str) -> list[str]:
    """source 文字列をパースしてソース名リストを返す。"""
    if source_str == "all":
        return ALL_SOURCES
    sources = []
    for s in source_str.split(","):
        s = s.strip()
        if s in SOURCE_MAP:
            sources.append(s)
        else:
            print(f"警告: 不明なソース '{s}' をスキップ", file=sys.stderr)
    return sources


def _build_result(
    ticker: str,
    source_results: dict[str, dict],
    accessed_domains: list[str],
    robots_checked: bool,
) -> dict:
    """統一JSON構造を組み立てる。"""
    errors = []
    success_count = 0
    for name, result in source_results.items():
        if result.get("collected"):
            success_count += 1
        if result.get("error"):
            errors.append(f"{name}: {result['error']}")

    return {
        "ticker": ticker,
        "company_name": None,
        "collected_at": datetime.now(JST).isoformat(),
        "sources": source_results,
        "metadata": {
            "source_count": len(source_results),
            "success_count": success_count,
            "errors": errors,
            "accessed_domains": accessed_domains,
            "robots_checked": robots_checked,
        },
    }


def _extract_domain(url: str | None) -> str | None:
    """URL からドメインを抽出する。"""
    if not url:
        return None
    parsed = urlparse(url)
    return parsed.netloc or None


def _create_resolver():
    """TickerResolver を生成する（利用不可時は None）。

    ディレクトリ名が ticker-resolver (ハイフン) のため、
    標準 import 失敗時にファイルパスから直接ロードする。
    """
    # 1. 標準 import
    try:
        from skills.ticker_resolver.scripts.resolver import TickerResolver
        return TickerResolver()
    except ImportError:
        pass

    # 2. ファイルパスから直接ロード
    try:
        import importlib.util
        resolver_path = (
            Path(__file__).resolve().parents[2]
            / "ticker-resolver"
            / "scripts"
            / "resolver.py"
        )
        if resolver_path.exists():
            spec = importlib.util.spec_from_file_location(
                "ticker_resolver_scripts_resolver", resolver_path
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.TickerResolver()
    except Exception:
        pass

    return None


def _shikiho_fallback(
    ticker: str,
    error: CollectorError,
    source_results: dict[str, dict],
    config: dict | None,
) -> dict:
    """Shikiho 失敗時に Yahoo Finance へフォールバックする。

    (b) yahoo 収集済み → データ再利用
    (c) yahoo 未収集 → YahooFinanceCollector で新規収集
    (e) 結果は source_results['shikiho'] キーに格納 (メタデータで fallback 記録)
    """
    error_code = getattr(error, "error_code", "UNKNOWN")
    fallback_meta = {
        "fallback_source": "yahoo",
        "fallback_reason": error_code,
    }

    # (b) yahoo 収集済みか確認
    yahoo_existing = source_results.get("yahoo", {})
    if yahoo_existing.get("collected"):
        fallback_meta["fallback_reused"] = True
        return {
            "url": yahoo_existing.get("url"),
            "collected": True,
            "data": yahoo_existing.get("data"),
            "error": None,
            "fallback": fallback_meta,
        }

    # (c) yahoo 未収集 → YahooFinanceCollector でフォールバック実行
    fallback_meta["fallback_reused"] = False
    try:
        collector = YahooFinanceCollector(config=config)
        with collector:
            result = collector.collect(ticker)
            if result.get("collected"):
                return {
                    "url": result.get("url"),
                    "collected": True,
                    "data": result.get("data"),
                    "error": None,
                    "fallback": fallback_meta,
                }
            # yahoo も失敗
            return {
                "url": None,
                "collected": False,
                "data": None,
                "error": f"shikiho: {error}; yahoo fallback: {result.get('error', 'unknown')}",
                "fallback": fallback_meta,
            }
    except Exception as fallback_err:
        return {
            "url": None,
            "collected": False,
            "data": None,
            "error": f"shikiho: {error}; yahoo fallback: {fallback_err}",
            "fallback": fallback_meta,
        }


def collect(
    ticker: str,
    sources: list[str],
    config: dict | None = None,
    edinet_csv: str | None = None,
) -> dict:
    """指定ソースから企業情報を収集する。"""
    source_results: dict[str, dict] = {}
    accessed_domains: set[str] = set()
    robots_checked = True  # BaseCollector は全 fetch 前に robots.txt を確認する契約

    # HomepageCollector 用の共有 resolver
    resolver = _create_resolver() if "homepage" in sources else None

    for source_name in sources:
        collector_cls = SOURCE_MAP[source_name]
        try:
            if source_name == "homepage":
                collector = collector_cls(
                    config=config,
                    resolver=resolver,
                    csv_path=edinet_csv,
                )
            else:
                collector = collector_cls(config=config)
            with collector:
                result = collector.collect(ticker)
                source_results[source_name] = result
                domain = _extract_domain(result.get("url"))
                if domain:
                    accessed_domains.add(domain)
        except CollectorError as e:
            # Shikiho fallback: shikiho 失敗時に yahoo へフォールバック
            if source_name == "shikiho":
                fallback_result = _shikiho_fallback(
                    ticker, e, source_results, config
                )
                source_results[source_name] = fallback_result
                domain = _extract_domain(fallback_result.get("url"))
                if domain:
                    accessed_domains.add(domain)
            else:
                source_results[source_name] = {
                    "url": None,
                    "collected": False,
                    "data": None,
                    "error": str(e),
                }
        except Exception as e:
            source_results[source_name] = {
                "url": None,
                "collected": False,
                "data": None,
                "error": f"予期しないエラー: {e}",
            }

    return _build_result(ticker, source_results, sorted(accessed_domains), robots_checked)


def merge_results(existing: dict, new_result: dict, sources: list[str]) -> dict:
    """既存 research.json に対して指定 source のみ上書きマージする。"""
    for source_name in sources:
        if source_name in new_result.get("sources", {}):
            existing.setdefault("sources", {})[source_name] = new_result["sources"][source_name]
    existing["collected_at"] = new_result.get("collected_at", existing.get("collected_at"))
    existing.setdefault("metadata", {}).update({
        "source_count": len(existing.get("sources", {})),
        "success_count": sum(
            1 for v in existing.get("sources", {}).values() if v.get("collected")
        ),
        "errors": [
            f"{k}: {v['error']}"
            for k, v in existing.get("sources", {}).items()
            if v.get("error")
        ],
    })
    return existing


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Web 上の企業情報を複数ソースから収集"
    )
    sub = parser.add_subparsers(dest="command")
    collect_cmd = sub.add_parser("collect", help="企業情報を収集")
    collect_cmd.add_argument(
        "--ticker",
        type=str,
        required=True,
        help="銘柄コード4桁（例: 7203）",
    )
    collect_cmd.add_argument(
        "--source",
        type=str,
        default="all",
        help="ソース指定: all|homepage|shikiho|yahoo|kabutan（カンマ区切り対応）",
    )
    collect_cmd.add_argument(
        "--output",
        type=str,
        default=None,
        help="出力先パス（省略時: data/{ticker}/web_research/research.json）",
    )
    collect_cmd.add_argument(
        "--merge",
        action="store_true",
        default=False,
        help="既存JSONの該当sourceのみ上書き",
    )
    collect_cmd.add_argument(
        "--edinet-csv",
        type=str,
        default=None,
        help="EdinetcodeDlInfo.csv パス（HomepageCollector 用）",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command != "collect":
        parser.print_help()
        return 1

    sources = _parse_sources(args.source)
    if not sources:
        print("有効なソースが指定されていません", file=sys.stderr)
        return 1

    edinet_csv = getattr(args, "edinet_csv", None)
    result = collect(args.ticker, sources, edinet_csv=edinet_csv)

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = _data_root() / args.ticker / "web_research" / "research.json"

    if args.merge and output_path.exists():
        with open(output_path, encoding="utf-8") as f:
            existing = json.load(f)
        result = merge_results(existing, result, sources)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    success_count = result.get("metadata", {}).get("success_count", 0)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    return 0 if success_count >= 1 else 1


if __name__ == "__main__":
    sys.exit(main())
