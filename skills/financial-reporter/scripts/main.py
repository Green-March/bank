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
    from render import build_absence_map, infer_fy_end_month, render_html, render_markdown
else:
    from .render import build_absence_map, infer_fy_end_month, render_html, render_markdown

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


def _resolve_company_name(ticker: str, data_root: Path) -> str | None:
    """Resolve company name from parsed JSON or EDINET document cache.

    Resolution order:
      1. parsed/*.json — company_name field
      2. raw/edinet/**/documents_*.json — filerName matching secCode
    """
    ticker_dir = data_root / ticker

    # Strategy 1: scan parsed JSON files for company_name
    for dirname in ("parsed",):
        data_dir = ticker_dir / dirname
        if not data_dir.is_dir():
            continue
        for json_path in sorted(data_dir.glob("*.json")):
            if json_path.name == "metrics.json":
                continue
            try:
                payload = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            # Top-level company_name
            name = payload.get("company_name")
            if isinstance(name, str) and name.strip() and name.strip() != "Unknown":
                return name.strip()
            # Nested in documents[]
            documents = payload.get("documents")
            if isinstance(documents, list):
                for doc in documents:
                    if isinstance(doc, dict):
                        name = doc.get("company_name")
                        if isinstance(name, str) and name.strip() and name.strip() != "Unknown":
                            return name.strip()

    # Strategy 2: scan EDINET document listing cache for filerName
    # Search subdirectories first (more targeted), then top-level
    edinet_dir = ticker_dir / "raw" / "edinet"
    if edinet_dir.is_dir():
        sec_code = f"{ticker}0"
        for doc_json in sorted(edinet_dir.rglob("documents_*.json"), reverse=True):
            try:
                cache = json.loads(doc_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            results = cache.get("results") if isinstance(cache, dict) else None
            if not isinstance(results, list):
                continue
            for entry in results:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("secCode", "")).strip() == sec_code:
                    filer = entry.get("filerName")
                    if isinstance(filer, str) and filer.strip():
                        return filer.strip()

    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="財務指標データから Markdown/HTML 分析レポートを生成")
    parser.add_argument("--ticker", required=True, help="銘柄コード (例: 7203)")
    parser.add_argument("--metrics", default=None, help="入力 metrics.json パス")
    parser.add_argument("--output-md", default=None, help="Markdown 出力先パス")
    parser.add_argument("--output-html", default=None, help="HTML 出力先パス")
    parser.add_argument(
        "--reconciliation",
        default=None,
        help="source_reconciliation.json パス (省略時は自動検出)",
    )
    parser.add_argument(
        "--number-format",
        choices=["raw", "man_yen", "oku_yen"],
        default="raw",
        help="数値表示形式: raw (デフォルト・生数値), man_yen (百万円), oku_yen (億円)",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    ticker = str(args.ticker)
    data_root = _data_root()

    if args.metrics:
        metrics_path = Path(args.metrics)
    else:
        metrics_path = data_root / ticker / "parsed" / "metrics.json"
    output_md = Path(args.output_md) if args.output_md else (data_root / ticker / "reports" / f"{ticker}_report.md")
    output_html = Path(args.output_html) if args.output_html else (data_root / ticker / "reports" / f"{ticker}_report.html")

    if not metrics_path.exists():
        print(f"metrics.json が見つかりません: {metrics_path}", file=sys.stderr)
        return 1

    try:
        payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"metrics データの読み込みに失敗しました: {exc}", file=sys.stderr)
        return 1

    if not isinstance(payload, dict):
        print("不正な metrics データ形式です", file=sys.stderr)
        return 1

    # Resolve company_name if missing or "Unknown"
    existing_name = payload.get("company_name")
    if not existing_name or existing_name == "Unknown":
        resolved = _resolve_company_name(ticker=ticker, data_root=data_root)
        if resolved:
            payload["company_name"] = resolved

    # Load reconciliation data for confirmed_absent annotations
    absence_map = None
    fy_end_month = 12
    recon_path = (
        Path(args.reconciliation)
        if args.reconciliation
        else (data_root / ticker / "qa" / "source_reconciliation.json")
    )
    if recon_path.exists():
        try:
            recon_data = json.loads(recon_path.read_text(encoding="utf-8"))
            if isinstance(recon_data, dict):
                absence_map = build_absence_map(recon_data)
                if not absence_map:
                    absence_map = None
                fy_end_month = infer_fy_end_month(recon_data)
        except (OSError, json.JSONDecodeError):
            pass  # reconciliation is optional; skip on error

    markdown_text = render_markdown(
        metrics_payload=payload,
        ticker=ticker,
        number_format=args.number_format,
        absence_map=absence_map,
        fy_end_month=fy_end_month,
    )
    html_text = render_html(markdown_text=markdown_text, title=f"{ticker} 分析レポート")

    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_html.parent.mkdir(parents=True, exist_ok=True)

    output_md.write_text(markdown_text, encoding="utf-8")
    output_html.write_text(html_text, encoding="utf-8")

    print(f"Markdown 出力: {output_md}")
    print(f"HTML 出力: {output_html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
