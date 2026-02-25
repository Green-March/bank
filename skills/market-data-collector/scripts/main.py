"""market-data-collector メインスクリプト.

J-Quants API の daily_quotes / listed_info からデータを収集する CLI。
"""

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv
from skills.common.auth import JQuantsAuth, JQuantsAuthError

# スクリプト直接実行とパッケージインポートの両方に対応
if __name__ == "__main__":
    from collector import (
        DailyQuotesClient,
        DailyQuotesError,
        ListedInfoClient,
        ListedInfoError,
    )
else:
    from .collector import (
        DailyQuotesClient,
        DailyQuotesError,
        ListedInfoClient,
        ListedInfoError,
    )

load_dotenv()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _data_root() -> Path:
    import os

    root = _repo_root()
    configured = os.environ.get("DATA_PATH")
    if not configured:
        return root / "data"
    path = Path(configured).expanduser()
    if path.is_absolute():
        return path
    return (root / path).resolve()


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"日付形式が不正です: {value} (YYYY-MM-DD を指定してください)"
        ) from e


def collect(
    ticker: str,
    from_date: date,
    to_date: date,
    output_dir: Path,
) -> dict:
    """株価・上場情報を収集して保存

    Returns:
        結果サマリ dict
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    auth = JQuantsAuth()

    # daily_quotes 取得
    quotes_client = DailyQuotesClient(auth)
    quotes = quotes_client.fetch(
        code=ticker,
        from_date=from_date.isoformat(),
        to_date=to_date.isoformat(),
    )

    market_data_path = output_dir / "market_data.json"
    with open(market_data_path, "w", encoding="utf-8") as f:
        json.dump(quotes, f, ensure_ascii=False, indent=2)

    # listed_info 取得
    info_client = ListedInfoClient(auth)
    info = info_client.fetch(code=ticker)

    listed_info_path = output_dir / "listed_info.json"
    with open(listed_info_path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)

    return {
        "ticker": ticker,
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "daily_quotes_count": len(quotes),
        "listed_info_count": len(info),
        "outputs": {
            "market_data": str(market_data_path),
            "listed_info": str(listed_info_path),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="J-Quants API から株価・上場情報を収集"
    )
    parser.add_argument(
        "--ticker",
        type=str,
        required=True,
        help="銘柄コード（例: 7203）",
    )
    parser.add_argument(
        "--from-date",
        type=_parse_iso_date,
        default=None,
        help="開始日（YYYY-MM-DD、省略時: 1年前）",
    )
    parser.add_argument(
        "--to-date",
        type=_parse_iso_date,
        default=None,
        help="終了日（YYYY-MM-DD、省略時: 今日）",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="出力先ディレクトリ（省略時: data/{ticker}/raw/jquants）",
    )
    return parser


def main() -> int:
    """CLIエントリーポイント

    Returns:
        終了コード（0: 成功, 1: エラー）
    """
    parser = build_parser()
    args = parser.parse_args()

    today = date.today()
    from_date = args.from_date if args.from_date else today - timedelta(days=365)
    to_date = args.to_date if args.to_date else today

    if from_date > to_date:
        print(
            f"期間が不正です: from-date ({from_date}) > to-date ({to_date})",
            file=sys.stderr,
        )
        return 1

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        output_dir = _data_root() / args.ticker / "raw" / "jquants"

    try:
        result = collect(
            ticker=args.ticker,
            from_date=from_date,
            to_date=to_date,
            output_dir=output_dir,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    except JQuantsAuthError as e:
        print(f"認証エラー: {e}", file=sys.stderr)
        return 1
    except DailyQuotesError as e:
        print(f"株価データ取得エラー: {e}", file=sys.stderr)
        return 1
    except ListedInfoError as e:
        print(f"上場情報取得エラー: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"ファイル書き込みエラー: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
