"""web-data-harmonizer メインスクリプト.

web-researcher の出力 JSON をパイプライン互換スキーマに変換する CLI。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# スクリプト直接実行・パッケージインポート・sys.path経由インポートすべてに対応
if __name__ == "__main__":
    script_dir = Path(__file__).resolve().parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    from harmonizer import harmonize
else:
    try:
        from .harmonizer import harmonize
    except ImportError:
        from harmonizer import harmonize


VALID_SOURCES = {"yahoo", "kabutan", "shikiho"}


def _validate_source(source_str: str) -> list[str] | None:
    """--source 値を検証し、有効なソース名リストを返す。無効値時は None。"""
    if source_str == "all":
        return sorted(VALID_SOURCES)
    sources = []
    invalid = []
    for s in source_str.split(","):
        s = s.strip()
        if not s:
            continue
        if s in VALID_SOURCES:
            sources.append(s)
        else:
            invalid.append(s)
    if invalid:
        print(
            f"エラー: 無効なソース指定: {', '.join(invalid)} "
            f"(有効値: all, {', '.join(sorted(VALID_SOURCES))})",
            file=sys.stderr,
        )
        return None
    if not sources:
        print(
            f"エラー: ソースが指定されていません "
            f"(有効値: all, {', '.join(sorted(VALID_SOURCES))})",
            file=sys.stderr,
        )
        return None
    return sources


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
        description="web-researcher 出力をパイプライン互換スキーマに変換"
    )
    sub = parser.add_subparsers(dest="command")
    harmonize_cmd = sub.add_parser("harmonize", help="Web データを正規化・変換")
    harmonize_cmd.add_argument(
        "--ticker",
        type=str,
        required=True,
        help="銘柄コード4桁（例: 2780）",
    )
    harmonize_cmd.add_argument(
        "--source",
        type=str,
        default="all",
        help="ソース指定: all|yahoo|kabutan|shikiho（カンマ区切り対応）",
    )
    harmonize_cmd.add_argument(
        "--input",
        type=str,
        default=None,
        help="web-researcher 出力 JSON パス（デフォルト: data/{ticker}/web_research/research.json）",
    )
    harmonize_cmd.add_argument(
        "--output",
        type=str,
        default=None,
        help="出力パス（デフォルト: data/{ticker}/harmonized/harmonized_financials.json）",
    )
    return parser


def cmd_harmonize(args: argparse.Namespace) -> int:
    ticker = args.ticker

    # --source バリデーション
    validated_sources = _validate_source(args.source)
    if validated_sources is None:
        return 1

    # 入力パス解決
    if args.input:
        input_path = Path(args.input)
    else:
        input_path = _data_root() / ticker / "web_research" / "research.json"

    if not input_path.exists():
        print(
            f"エラー: 入力ファイルが見つかりません: {input_path}",
            file=sys.stderr,
        )
        return 1

    # JSON 読み込み
    try:
        with open(input_path, encoding="utf-8") as f:
            web_research = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"エラー: 入力ファイルの読み込みに失敗: {e}", file=sys.stderr)
        return 1

    # 変換実行
    result = harmonize(web_research, source_filter=args.source)

    # 出力パス解決
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = _data_root() / ticker / "harmonized" / "harmonized_financials.json"

    # ディレクトリ作成 + 書き込み
    os.makedirs(output_path.parent, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # stdout にも出力
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    if args.command == "harmonize":
        return cmd_harmonize(args)

    return 1


if __name__ == "__main__":
    sys.exit(main())
