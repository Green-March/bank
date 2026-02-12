from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

if __package__ in {None, ""}:
    script_dir = Path(__file__).resolve().parent
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    from render import render_html, render_markdown
else:
    from .render import render_html, render_markdown

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
    parser = argparse.ArgumentParser(description="Generate markdown/html financial report")
    parser.add_argument("--ticker", required=True, help="Ticker code (e.g. 7203)")
    parser.add_argument("--metrics", default=None, help="Input metrics.json path")
    parser.add_argument("--output-md", default=None, help="Output markdown path")
    parser.add_argument("--output-html", default=None, help="Output html path")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    ticker = str(args.ticker)
    data_root = _data_root()

    metrics_path = Path(args.metrics) if args.metrics else (data_root / ticker / "parsed" / "metrics.json")
    output_md = Path(args.output_md) if args.output_md else (data_root / ticker / "reports" / f"{ticker}_report.md")
    output_html = Path(args.output_html) if args.output_html else (data_root / ticker / "reports" / f"{ticker}_report.html")

    if not metrics_path.exists():
        print(f"metrics.json not found: {metrics_path}", file=sys.stderr)
        return 1

    try:
        payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"failed to read metrics payload: {exc}", file=sys.stderr)
        return 1

    if not isinstance(payload, dict):
        print("invalid metrics payload", file=sys.stderr)
        return 1

    markdown_text = render_markdown(metrics_payload=payload, ticker=ticker)
    html_text = render_html(markdown_text=markdown_text, title=f"{ticker} Analysis Report")

    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_html.parent.mkdir(parents=True, exist_ok=True)

    output_md.write_text(markdown_text, encoding="utf-8")
    output_html.write_text(html_text, encoding="utf-8")

    print(f"markdown: {output_md}")
    print(f"html: {output_html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
