from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# スクリプト直接実行とパッケージインポートの両方に対応
if __name__ == "__main__":
    script_dir = Path(__file__).resolve().parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    from metrics import calculate_metrics_payload, write_metrics_payload
    from report import render_report_markdown
else:
    from .metrics import calculate_metrics_payload, write_metrics_payload
    from .report import render_report_markdown

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


def calculate_command(
    ticker: str,
    parsed_dir: Path | None,
    output_path: Path,
    *,
    input_file: Path | None = None,
) -> int:
    payload = calculate_metrics_payload(
        parsed_dir=parsed_dir, ticker=ticker, input_file=input_file
    )
    write_metrics_payload(payload=payload, output_path=output_path)
    print(f"metrics.json を生成しました: {output_path}")
    print(f"解析期数: {payload['source_count']}")
    return 0


def report_command(ticker: str, metrics_path: Path, output_path: Path) -> int:
    if not metrics_path.exists():
        print(f"metrics.json が見つかりません: {metrics_path}", file=sys.stderr)
        return 1

    try:
        payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"metrics.json の読み込みに失敗しました: {exc}", file=sys.stderr)
        return 1

    if not isinstance(payload, dict):
        print("metrics.json の形式が不正です", file=sys.stderr)
        return 1

    markdown = render_report_markdown(metrics_payload=payload, ticker=ticker)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    print(f"レポートを生成しました: {output_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="財務指標計算とMarkdownレポート生成")
    subparsers = parser.add_subparsers(dest="command", required=True)

    calc_parser = subparsers.add_parser("calculate", help="parsed JSONからmetrics.jsonを生成")
    calc_parser.add_argument("--ticker", required=True, help="銘柄コード（例: 2780）")
    calc_parser.add_argument(
        "--parsed-dir",
        default=None,
        help="入力ディレクトリ（省略時: data/{ticker}/parsed）",
    )
    calc_parser.add_argument(
        "--output",
        default=None,
        help="出力JSONパス（省略時: data/{ticker}/parsed/metrics.json）",
    )
    calc_parser.add_argument(
        "--input-file",
        default=None,
        help="単一入力ファイルパス（指定時: parsed-dir を無視しこのファイルのみ読む）",
    )

    report_parser = subparsers.add_parser("report", help="metrics.jsonからreport.mdを生成")
    report_parser.add_argument("--ticker", required=True, help="銘柄コード（例: 2780）")
    report_parser.add_argument(
        "--metrics",
        default=None,
        help="入力 metrics.json パス（省略時: data/{ticker}/parsed/metrics.json）",
    )
    report_parser.add_argument(
        "--output",
        default=None,
        help="出力Markdownパス（省略時: data/{ticker}/reports/report.md）",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    data_root = _data_root()
    ticker = str(args.ticker)

    if args.command == "calculate":
        input_file = Path(args.input_file) if args.input_file else None
        parsed_dir = (
            Path(args.parsed_dir)
            if args.parsed_dir
            else (data_root / ticker / "parsed")
        ) if not input_file else None
        output_path = (
            Path(args.output)
            if args.output
            else (data_root / ticker / "parsed" / "metrics.json")
        )
        return calculate_command(
            ticker=ticker, parsed_dir=parsed_dir, output_path=output_path,
            input_file=input_file,
        )

    metrics_path = (
        Path(args.metrics)
        if args.metrics
        else (data_root / ticker / "parsed" / "metrics.json")
    )
    default_report_dir = data_root / ticker / "reports"
    output_path = Path(args.output) if args.output else (default_report_dir / "report.md")
    return report_command(ticker=ticker, metrics_path=metrics_path, output_path=output_path)


if __name__ == "__main__":
    sys.exit(main())
