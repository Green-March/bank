from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import markdown
from jinja2 import Template

# period_end -> {field_name: reason}
AbsenceMap = dict[str, dict[str, str]]

# Fields where number_format applies (monetary values).
# Ratio/percent fields are always displayed as-is.
_MONETARY_FIELDS = frozenset(
    ("revenue", "operating_income", "net_income", "free_cash_flow")
)


def build_absence_map(reconciliation: dict[str, Any]) -> AbsenceMap:
    """Extract confirmed_absent entries from source_reconciliation.json."""
    absence: AbsenceMap = {}
    comparisons = reconciliation.get("comparisons", [])
    for comp in comparisons:
        if not isinstance(comp, dict):
            continue
        period_end = comp.get("period_end")
        if not period_end:
            continue
        fields = comp.get("fields")
        if not isinstance(fields, dict):
            continue
        for field_name, field_data in fields.items():
            if not isinstance(field_data, dict):
                continue
            if field_data.get("t1_judgment") == "confirmed_absent":
                reason = (
                    field_data.get("reason")
                    or field_data.get("t1_reason")
                    or ""
                )
                absence.setdefault(period_end, {})[field_name] = reason
    return absence


def infer_fy_end_month(reconciliation: dict[str, Any]) -> int:
    """Infer fiscal year end month from reconciliation FY period_end dates.

    Looks for comparisons with ``jquants_period_type == "FY"`` and extracts the
    month from ``period_end``.  Returns 12 (December) when unable to determine.
    """
    for comp in reconciliation.get("comparisons", []):
        if not isinstance(comp, dict):
            continue
        if comp.get("jquants_period_type") == "FY":
            pe = str(comp.get("period_end", ""))
            try:
                return int(pe[5:7])
            except (ValueError, IndexError):
                continue
    return 12


def _period_in_fiscal_year(
    period_end_str: str, fiscal_year: int, fy_end_month: int
) -> bool:
    """Check whether *period_end_str* falls within *fiscal_year*.

    Japanese convention: ``fiscal_year`` = calendar year the FY **ends** in.

    Examples (fy_end_month=3, fiscal_year=2024):
        FY range: 2023-04-01 … 2024-03-31
        Q1 ends 2023-06-30 ✓, Q2 ends 2023-09-30 ✓, FY ends 2024-03-31 ✓

    Examples (fy_end_month=12, fiscal_year=2024):
        FY range: 2024-01-01 … 2024-12-31
        All quarterly period_ends in 2024 ✓
    """
    try:
        pe_year = int(period_end_str[:4])
        pe_month = int(period_end_str[5:7])
    except (ValueError, TypeError, IndexError):
        return False

    if fy_end_month == 12:
        return pe_year == fiscal_year

    # Non-December fiscal year:
    # FY ends at fiscal_year-fy_end_month,
    # FY starts at (fiscal_year - 1)-(fy_end_month + 1).
    return (
        (pe_year == fiscal_year and pe_month <= fy_end_month)
        or (pe_year == fiscal_year - 1 and pe_month > fy_end_month)
    )


def _row_absence(
    row: dict[str, Any],
    absence_map: AbsenceMap | None,
    *,
    fy_end_month: int = 12,
) -> dict[str, str]:
    """Return {field_name: reason} for confirmed_absent fields matching a metrics row."""
    if not absence_map:
        return {}
    fy = row.get("fiscal_year")
    if fy is None:
        return {}
    result: dict[str, str] = {}
    for period_end, field_reasons in absence_map.items():
        if _period_in_fiscal_year(period_end, fy, fy_end_month):
            result.update(field_reasons)
    return result


def _fmt_value(
    value: Any,
    suffix: str = "",
    *,
    number_format: str = "raw",
    is_monetary: bool = False,
    absence_reason: str | None = None,
) -> str:
    """Format a single metric value.

    Returns ``"N/A"`` for uncollected nulls,
    ``"\u2014\u2020"`` (—†) for confirmed-absent nulls.
    """
    if not isinstance(value, (int, float)):
        if absence_reason is not None:
            return "\u2014\u2020"  # —†
        return "N/A"

    if is_monetary and number_format == "man_yen":
        return f"{value / 1_000_000:,.0f}{suffix}"
    if is_monetary and number_format == "oku_yen":
        return f"{value / 100_000_000:,.1f}{suffix}"
    return f"{value:.2f}{suffix}"


def _period_label(period_months: int | None) -> str:
    """Map period length in months to a Japanese label."""
    if period_months is None:
        return ""
    labels = {3: "四半期", 6: "半期", 9: "3Q累計", 12: "通期"}
    return labels.get(period_months, f"{period_months}M")


def _fiscal_year_display(row: dict[str, Any]) -> str:
    """Format fiscal year with optional period label for disambiguation."""
    fy = row.get("fiscal_year", "N/A")
    label = _period_label(row.get("period_months"))
    if label and label != "通期":
        return f"{fy} ({label})"
    return str(fy)


def render_markdown(
    metrics_payload: dict[str, Any],
    ticker: str,
    *,
    number_format: str = "raw",
    absence_map: AbsenceMap | None = None,
    fy_end_month: int = 12,
) -> str:
    company_name = str(metrics_payload.get("company_name") or "不明")
    generated_at = str(metrics_payload.get("generated_at") or _now_iso())

    series_raw = metrics_payload.get("metrics_series")
    series: list[dict[str, Any]] = [
        row for row in series_raw if isinstance(row, dict)
    ] if isinstance(series_raw, list) else []

    latest = series[-1] if series else {}
    latest_abs = _row_absence(latest, absence_map, fy_end_month=fy_end_month)

    # Unit label for monetary columns
    unit_label = ""
    if number_format == "man_yen":
        unit_label = " (百万円)"
    elif number_format == "oku_yen":
        unit_label = " (億円)"

    def fmt(
        value: Any,
        suffix: str = "",
        *,
        field: str = "",
        row_abs: dict[str, str] | None = None,
    ) -> str:
        is_mon = field in _MONETARY_FIELDS
        abs_reason = (
            (row_abs or {}).get(field)
            if not isinstance(value, (int, float))
            else None
        )
        return _fmt_value(
            value,
            suffix,
            number_format=number_format,
            is_monetary=is_mon,
            absence_reason=abs_reason,
        )

    lines: list[str] = []
    lines.append(f"# {ticker} {company_name} 分析レポート")
    lines.append("")
    lines.append("## 概要")
    lines.append(f"- 証券コード: {ticker}")
    lines.append(f"- 企業名: {company_name}")
    lines.append(f"- 生成日時 (UTC): {generated_at}")
    lines.append("")
    lines.append("## 主要指標（直近）")
    latest_label = _period_label(latest.get("period_months"))
    latest_suffix = f" ({latest_label})" if latest_label and latest_label != "通期" else ""
    lines.append(f"- 売上高{latest_suffix}: {fmt(latest.get('revenue'), field='revenue', row_abs=latest_abs)}{unit_label}")
    lines.append(f"- 営業利益{latest_suffix}: {fmt(latest.get('operating_income'), field='operating_income', row_abs=latest_abs)}{unit_label}")
    lines.append(f"- 当期純利益{latest_suffix}: {fmt(latest.get('net_income'), field='net_income', row_abs=latest_abs)}{unit_label}")
    lines.append(f"- ROE: {fmt(latest.get('roe_percent'), '%', field='roe_percent', row_abs=latest_abs)}")
    lines.append(f"- ROA: {fmt(latest.get('roa_percent'), '%', field='roa_percent', row_abs=latest_abs)}")
    lines.append(f"- 営業利益率: {fmt(latest.get('operating_margin_percent'), '%', field='operating_margin_percent', row_abs=latest_abs)}")
    lines.append(f"- 自己資本比率: {fmt(latest.get('equity_ratio_percent'), '%', field='equity_ratio_percent', row_abs=latest_abs)}")
    lines.append(f"- フリーキャッシュフロー{latest_suffix}: {fmt(latest.get('free_cash_flow'), field='free_cash_flow', row_abs=latest_abs)}{unit_label}")
    lines.append("")
    lines.append("## 推移表")
    lines.append("| 会計年度 | 売上高 | 営業利益 | 当期純利益 | ROE(%) | ROA(%) | 営業利益率(%) | 自己資本比率(%) | FCF |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in series:
        row_abs = _row_absence(row, absence_map, fy_end_month=fy_end_month)
        lines.append(
            "| {fy} | {rev} | {op} | {net} | {roe} | {roa} | {margin} | {equity} | {fcf} |".format(
                fy=_fiscal_year_display(row),
                rev=fmt(row.get("revenue"), field="revenue", row_abs=row_abs),
                op=fmt(row.get("operating_income"), field="operating_income", row_abs=row_abs),
                net=fmt(row.get("net_income"), field="net_income", row_abs=row_abs),
                roe=fmt(row.get("roe_percent"), field="roe_percent", row_abs=row_abs),
                roa=fmt(row.get("roa_percent"), field="roa_percent", row_abs=row_abs),
                margin=fmt(row.get("operating_margin_percent"), field="operating_margin_percent", row_abs=row_abs),
                equity=fmt(row.get("equity_ratio_percent"), field="equity_ratio_percent", row_abs=row_abs),
                fcf=fmt(row.get("free_cash_flow"), field="free_cash_flow", row_abs=row_abs),
            )
        )

    lines.append("")
    lines.append("## リスクと注意点")
    lines.append("- データ遅延リスク: 直近の開示情報がまだ反映されていない可能性があります。")
    lines.append("- 会計方針やセグメント変更により、前年同期比較が歪む場合があります。")
    lines.append("- 一時的な損益が収益性指標を歪める可能性があります。")
    lines.append("- 株価バリュエーションには本レポート範囲外の市場データが必要です。")
    lines.append("")

    # Data Quality Notes (only when absence_map has entries)
    if absence_map:
        footnotes: list[str] = []
        for period_end in sorted(absence_map):
            for field_name, reason in sorted(absence_map[period_end].items()):
                footnotes.append(
                    f"  - {period_end} / {field_name}: {reason}"
                )
        if footnotes:
            lines.append("## データ品質に関する注記")
            lines.append("")
            lines.append(
                "\u2020: 確認済み不在"
                " \u2014 開示資料に該当データが存在しないことを確認済み。"
            )
            lines.append("")
            lines.extend(footnotes)
            lines.append("")

    return "\n".join(lines)


def render_html(markdown_text: str, title: str) -> str:
    content_html = markdown.markdown(markdown_text, extensions=["tables", "fenced_code"])
    template = Template(
        """<!doctype html>
<html lang=\"ja\">
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
