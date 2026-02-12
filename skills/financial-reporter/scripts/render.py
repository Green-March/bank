from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import markdown
from jinja2 import Template


def render_markdown(metrics_payload: dict[str, Any], ticker: str) -> str:
    company_name = str(metrics_payload.get("company_name") or "Unknown")
    generated_at = str(metrics_payload.get("generated_at") or _now_iso())

    series_raw = metrics_payload.get("metrics_series")
    series: list[dict[str, Any]] = [
        row for row in series_raw if isinstance(row, dict)
    ] if isinstance(series_raw, list) else []

    latest = series[-1] if series else {}

    def fmt(value: Any, suffix: str = "") -> str:
        if isinstance(value, (int, float)):
            return f"{value:.2f}{suffix}"
        return "N/A"

    lines: list[str] = []
    lines.append(f"# {ticker} {company_name} Analysis Report")
    lines.append("")
    lines.append("## Snapshot")
    lines.append(f"- Ticker: {ticker}")
    lines.append(f"- Company: {company_name}")
    lines.append(f"- Generated At (UTC): {generated_at}")
    lines.append("")
    lines.append("## Key Metrics (Latest)")
    lines.append(f"- Revenue: {fmt(latest.get('revenue'))}")
    lines.append(f"- Operating Income: {fmt(latest.get('operating_income'))}")
    lines.append(f"- Net Income: {fmt(latest.get('net_income'))}")
    lines.append(f"- ROE: {fmt(latest.get('roe_percent'), '%')}")
    lines.append(f"- ROA: {fmt(latest.get('roa_percent'), '%')}")
    lines.append(f"- Operating Margin: {fmt(latest.get('operating_margin_percent'), '%')}")
    lines.append(f"- Equity Ratio: {fmt(latest.get('equity_ratio_percent'), '%')}")
    lines.append(f"- Free Cash Flow: {fmt(latest.get('free_cash_flow'))}")
    lines.append("")
    lines.append("## Trend Table")
    lines.append("| Fiscal Year | Revenue | Operating Income | Net Income | ROE(%) | ROA(%) | Margin(%) | Equity Ratio(%) | FCF |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in series:
        lines.append(
            "| {fy} | {rev} | {op} | {net} | {roe} | {roa} | {margin} | {equity} | {fcf} |".format(
                fy=row.get("fiscal_year", "N/A"),
                rev=fmt(row.get("revenue")),
                op=fmt(row.get("operating_income")),
                net=fmt(row.get("net_income")),
                roe=fmt(row.get("roe_percent")),
                roa=fmt(row.get("roa_percent")),
                margin=fmt(row.get("operating_margin_percent")),
                equity=fmt(row.get("equity_ratio_percent")),
                fcf=fmt(row.get("free_cash_flow")),
            )
        )

    lines.append("")
    lines.append("## Risks and Watchpoints")
    lines.append("- Data lag risk: very recent disclosures may not yet be reflected.")
    lines.append("- Accounting policy and segment changes can distort YoY comparisons.")
    lines.append("- One-off gains/losses can inflate profitability metrics.")
    lines.append("- Price valuation requires market data integration beyond this report.")
    lines.append("")

    return "\n".join(lines)


def render_html(markdown_text: str, title: str) -> str:
    content_html = markdown.markdown(markdown_text, extensions=["tables", "fenced_code"])
    template = Template(
        """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{{ title }}</title>
  <style>
    body { font-family: 'Noto Sans JP', 'Hiragino Sans', 'Yu Gothic', sans-serif; margin: 32px auto; max-width: 1080px; color: #1f2937; line-height: 1.6; padding: 0 16px; }
    h1, h2, h3 { color: #0f172a; }
    table { border-collapse: collapse; width: 100%; margin: 16px 0; }
    th, td { border: 1px solid #cbd5e1; padding: 8px; text-align: right; }
    th:first-child, td:first-child { text-align: left; }
    th { background: #e2e8f0; }
    code { background: #f1f5f9; padding: 2px 4px; border-radius: 4px; }
  </style>
</head>
<body>
{{ content | safe }}
</body>
</html>
"""
    )
    return template.render(title=title, content=content_html)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
