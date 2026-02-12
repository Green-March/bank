from __future__ import annotations

from typing import Sequence


def render_report_markdown(metrics_payload: dict[str, object], ticker: str) -> str:
    company_name = _as_str(metrics_payload.get("company_name")) or "Unknown"
    generated_at = _as_str(metrics_payload.get("generated_at")) or "N/A"
    source_count = _as_int(metrics_payload.get("source_count")) or 0

    series = metrics_payload.get("metrics_series")
    metrics_series: list[dict[str, object]] = []
    if isinstance(series, list):
        metrics_series = [row for row in series if isinstance(row, dict)]

    latest = metrics_payload.get("latest_snapshot")
    latest_snapshot = latest if isinstance(latest, dict) else {}

    lines: list[str] = []
    lines.append(f"# {ticker} {company_name} 財務分析レポート")
    lines.append("")
    lines.append("## 企業概要")
    lines.append(f"- 銘柄コード: {ticker}")
    lines.append(f"- 企業名: {company_name}")
    lines.append(f"- 解析対象期数: {source_count}")
    lines.append(f"- 生成日時(UTC): {generated_at}")
    lines.append("")
    lines.append("## 財務ハイライト")
    lines.append(_bullet("売上高", latest_snapshot.get("revenue"), "百万円"))
    lines.append(_bullet("営業利益", latest_snapshot.get("operating_income"), "百万円"))
    lines.append(_bullet("当期純利益", latest_snapshot.get("net_income"), "百万円"))
    lines.append(_bullet("ROE", latest_snapshot.get("roe_percent"), "%"))
    lines.append(_bullet("ROA", latest_snapshot.get("roa_percent"), "%"))
    lines.append("")
    lines.append("## 収益性")
    lines.append(_table_header())
    for row in metrics_series:
        lines.append(
            _table_row(
                row=row,
                columns=(
                    "fiscal_year",
                    "roe_percent",
                    "roa_percent",
                    "operating_margin_percent",
                ),
            )
        )
    lines.append("")
    lines.append("## 成長性")
    lines.append(_table_header())
    for row in metrics_series:
        lines.append(
            _table_row(
                row=row,
                columns=(
                    "fiscal_year",
                    "revenue_growth_yoy_percent",
                    "profit_growth_yoy_percent",
                    "revenue",
                ),
            )
        )
    lines.append("")
    lines.append("## 安全性")
    lines.append(_table_header())
    for row in metrics_series:
        lines.append(_table_row(row=row, columns=("fiscal_year", "equity_ratio_percent")))
    lines.append("")
    lines.append("## CF分析")
    lines.append(_table_header())
    for row in metrics_series:
        lines.append(_table_row(row=row, columns=("fiscal_year", "operating_cf", "free_cash_flow")))
    lines.append("")
    lines.append("## 総合評価")
    lines.append(_overall_assessment(latest_snapshot))
    lines.append("")
    lines.append("## 再現コマンド")
    lines.append(f"- 指標算出: `python3 skills/financial-calculator/scripts/main.py calculate --ticker {ticker}`")
    lines.append(f"- レポート生成: `python3 skills/financial-calculator/scripts/main.py report --ticker {ticker}`")
    lines.append("")
    return "\n".join(lines)


def _overall_assessment(latest_snapshot: dict[str, object]) -> str:
    roe = _as_float(latest_snapshot.get("roe_percent"))
    operating_margin = _as_float(latest_snapshot.get("operating_margin_percent"))
    equity_ratio = _as_float(latest_snapshot.get("equity_ratio_percent"))
    free_cash_flow = _as_float(latest_snapshot.get("free_cash_flow"))

    if roe is None or operating_margin is None or equity_ratio is None:
        return "必要データが不足しており、総合評価は保留です。"

    score = 0
    if roe >= 10.0:
        score += 1
    if operating_margin >= 5.0:
        score += 1
    if equity_ratio >= 30.0:
        score += 1
    if free_cash_flow is not None and free_cash_flow > 0:
        score += 1

    if score >= 4:
        return "収益性・安全性・キャッシュ創出力がバランス良く、財務状態は良好です。"
    if score >= 2:
        return "一定の収益力はあるものの、継続的な改善余地があります。"
    return "主要指標が弱く、財務面の慎重なモニタリングが必要です。"


def _bullet(label: str, value: object, unit: str) -> str:
    numeric = _as_float(value)
    if numeric is None:
        return f"- {label}: N/A"
    return f"- {label}: {numeric:.2f}{unit}"


def _table_header() -> str:
    return "| 項目1 | 項目2 | 項目3 | 項目4 |\n|---|---:|---:|---:|"


def _table_row(row: dict[str, object], columns: Sequence[str]) -> str:
    rendered = [_as_cell(row.get(column)) for column in columns]
    while len(rendered) < 4:
        rendered.append("-")
    return f"| {rendered[0]} | {rendered[1]} | {rendered[2]} | {rendered[3]} |"


def _as_cell(value: object) -> str:
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, str) and value.strip():
        return value
    return "-"


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _as_int(value: object) -> int | None:
    numeric = _as_float(value)
    if numeric is None:
        return None
    return int(numeric)


def _as_str(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None
