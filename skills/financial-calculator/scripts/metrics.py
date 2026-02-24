from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence


@dataclass(frozen=True)
class FinancialRecord:
    ticker: str
    company_name: str | None
    fiscal_year: int | None
    period: str | None
    revenue: float | None
    operating_income: float | None
    net_income: float | None
    total_assets: float | None
    equity: float | None
    operating_cf: float | None
    investing_cf: float | None
    period_end: str | None
    period_start: str | None = None
    provisional: bool = False
    statement_type: str | None = None
    source_attribution: str | None = None
    source_details: dict | None = None
    cumulative: bool = False


def calculate_metrics_payload(
    parsed_dir: Path | None = None,
    ticker: str = "",
    *,
    input_file: Path | None = None,
) -> dict[str, object]:
    records = load_financial_records(
        parsed_dir=parsed_dir, ticker=ticker, input_file=input_file
    )
    annual_series, quarterly_series = _build_metrics_series(records=records)

    company_name = None
    if records:
        company_name = records[-1].company_name

    latest_snapshot: dict[str, object] | None = None
    if annual_series:
        last = annual_series[-1]
        latest_snapshot = dict(last)

    payload: dict[str, object] = {
        "ticker": ticker,
        "company_name": company_name or "Unknown",
        "generated_at": _utc_now_iso(),
        "source_count": len(records),
        "metrics_series": annual_series,
        "latest_snapshot": latest_snapshot,
    }
    if quarterly_series:
        payload["quarterly_series"] = quarterly_series

    return payload


def write_metrics_payload(payload: dict[str, object], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_financial_records(
    parsed_dir: Path | None = None,
    ticker: str = "",
    *,
    input_file: Path | None = None,
) -> list[FinancialRecord]:
    # Determine which files to read
    if input_file is not None:
        json_paths = [input_file] if input_file.exists() else []
    elif parsed_dir is not None and parsed_dir.exists():
        json_paths = sorted(parsed_dir.glob("*.json"))
    else:
        return []

    records: list[FinancialRecord] = []
    for json_path in json_paths:
        if json_path.name == "metrics.json":
            continue
        payload = _load_json(json_path)
        if payload is None:
            continue
        for candidate in _extract_candidates(payload=payload, fallback_ticker=ticker):
            payload_ticker = _as_str(candidate.get("ticker"))
            if payload_ticker and payload_ticker != ticker:
                continue
            records.append(_to_financial_record(payload=candidate, fallback_ticker=ticker))

    records = _deduplicate_records(records)

    _PERIOD_ORDER = {"FY": 0, "Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}

    records.sort(
        key=lambda record: (
            record.fiscal_year is None,
            -1 if record.fiscal_year is None else record.fiscal_year,
            _PERIOD_ORDER.get((record.period or "").upper(), 99),
            record.period_end or "",
        )
    )
    return records


def _load_json(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _to_financial_record(payload: dict[str, object], fallback_ticker: str) -> FinancialRecord:
    bs = _as_mapping(payload.get("bs"))
    pl = _as_mapping(payload.get("pl"))
    cf = _as_mapping(payload.get("cf"))
    all_map = _as_mapping(payload)

    ticker = _as_str(payload.get("ticker")) or fallback_ticker
    company_name = _as_str(payload.get("company_name"))
    fiscal_year = _to_int(payload.get("fiscal_year")) or _to_int(payload.get("fiscalYear"))
    period = _as_str(payload.get("period"))
    period_end = _as_str(payload.get("period_end"))
    period_start = _as_str(payload.get("period_start"))

    revenue = _pick_number(
        primary=pl,
        aliases=("revenue", "net_sales", "sales", "売上高", "売上収益"),
        fallback=all_map,
    )
    operating_income = _pick_number(
        primary=pl,
        aliases=("operating_income", "operating_profit", "営業利益"),
        fallback=all_map,
    )
    net_income = _pick_number(
        primary=pl,
        aliases=(
            "net_income",
            "profit",
            "profit_attributable_to_owners_of_parent",
            "親会社株主に帰属する当期純利益",
            "当期純利益",
        ),
        fallback=all_map,
    )
    total_assets = _pick_number(
        primary=bs,
        aliases=("total_assets", "assets", "資産合計", "総資産"),
        fallback=all_map,
    )
    equity = _pick_number(
        primary=bs,
        aliases=("equity", "total_equity", "net_assets", "自己資本", "純資産", "純資産合計"),
        fallback=all_map,
    )
    operating_cf = _pick_number(
        primary=cf,
        aliases=(
            "operating_cf",
            "cash_flow_from_operating_activities",
            "営業活動によるキャッシュフロー",
        ),
        fallback=all_map,
    )
    investing_cf = _pick_number(
        primary=cf,
        aliases=(
            "investing_cf",
            "cash_flow_from_investing_activities",
            "投資活動によるキャッシュフロー",
        ),
        fallback=all_map,
    )

    # Extract metadata fields
    provisional = bool(payload.get("provisional", False))
    statement_type = _as_str(payload.get("statement_type"))
    source_attribution = _as_str(payload.get("source_attribution"))
    source_details_raw = payload.get("source_details")
    source_details = dict(source_details_raw) if isinstance(source_details_raw, dict) else None
    cumulative = bool(payload.get("cumulative", False))

    return FinancialRecord(
        ticker=ticker,
        company_name=company_name,
        fiscal_year=fiscal_year,
        period=period,
        revenue=revenue,
        operating_income=operating_income,
        net_income=net_income,
        total_assets=total_assets,
        equity=equity,
        operating_cf=operating_cf,
        investing_cf=investing_cf,
        period_end=period_end,
        period_start=period_start,
        provisional=provisional,
        statement_type=statement_type,
        source_attribution=source_attribution,
        source_details=source_details,
        cumulative=cumulative,
    )


def _build_metrics_series(records: Sequence[FinancialRecord]) -> list[dict[str, object]]:
    """Build metrics series from records, computing growth rates within same period type."""
    # Separate annual and quarterly records
    annual_records = [r for r in records if (r.period or "").upper() in ("FY", "MIXED", "DURATION", "INSTANT", "N/A", "")]
    quarterly_records = [r for r in records if (r.period or "").upper() in ("Q1", "Q2", "Q3", "Q4")]

    annual_series = _build_series_for_group(annual_records)
    quarterly_series = _build_quarterly_series(quarterly_records)

    return annual_series, quarterly_series


def _build_series_for_group(records: Sequence[FinancialRecord]) -> list[dict[str, object]]:
    """Build annual metrics series with YoY growth."""
    series: list[dict[str, object]] = []
    previous: FinancialRecord | None = None

    for record in records:
        roe = _ratio_percent(record.net_income, record.equity)
        roa = _ratio_percent(record.net_income, record.total_assets)
        operating_margin = _ratio_percent(record.operating_income, record.revenue)
        revenue_growth = _growth_percent(record.revenue, previous.revenue if previous else None)
        profit_growth = _growth_percent(record.net_income, previous.net_income if previous else None)
        equity_ratio = _ratio_percent(record.equity, record.total_assets)
        free_cash_flow = _sum_nullable(record.operating_cf, record.investing_cf)

        period_months = _compute_period_months(record.period_start, record.period_end)

        entry: dict[str, object] = {
            "fiscal_year": record.fiscal_year,
            "period": record.period or "N/A",
            "period_months": period_months,
            "revenue": _round_num(record.revenue),
            "operating_income": _round_num(record.operating_income),
            "net_income": _round_num(record.net_income),
            "roe_percent": _round_num(roe),
            "roa_percent": _round_num(roa),
            "operating_margin_percent": _round_num(operating_margin),
            "revenue_growth_yoy_percent": _round_num(revenue_growth),
            "profit_growth_yoy_percent": _round_num(profit_growth),
            "equity_ratio_percent": _round_num(equity_ratio),
            "operating_cf": _round_num(record.operating_cf),
            "free_cash_flow": _round_num(free_cash_flow),
        }
        # Add metadata if available
        if record.provisional:
            entry["provisional"] = True
        if record.statement_type:
            entry["statement_type"] = record.statement_type
        if record.source_attribution:
            entry["source_attribution"] = record.source_attribution
        if record.source_details:
            entry["source_details"] = record.source_details

        series.append(entry)
        previous = record

    return series


def _build_quarterly_series(records: Sequence[FinancialRecord]) -> list[dict[str, object]]:
    """Build quarterly metrics series with YoY growth (same quarter comparison)."""
    series: list[dict[str, object]] = []

    # Build lookup for same-quarter prior year comparison
    quarter_lookup: dict[tuple[int, str], FinancialRecord] = {}
    for record in records:
        if record.fiscal_year is not None and record.period:
            quarter_lookup[(record.fiscal_year, record.period.upper())] = record

    for record in records:
        roe = _ratio_percent(record.net_income, record.equity)
        roa = _ratio_percent(record.net_income, record.total_assets)
        operating_margin = _ratio_percent(record.operating_income, record.revenue)
        equity_ratio = _ratio_percent(record.equity, record.total_assets)
        free_cash_flow = _sum_nullable(record.operating_cf, record.investing_cf)

        period_months = _compute_period_months(record.period_start, record.period_end)

        # YoY: compare with same quarter in previous fiscal year
        prev_key = (record.fiscal_year - 1, (record.period or "").upper()) if record.fiscal_year else None
        prev_record = quarter_lookup.get(prev_key) if prev_key else None
        revenue_growth_yoy = _growth_percent(
            record.revenue, prev_record.revenue if prev_record else None
        )
        profit_growth_yoy = _growth_percent(
            record.net_income, prev_record.net_income if prev_record else None
        )

        entry: dict[str, object] = {
            "fiscal_year": record.fiscal_year,
            "period": record.period or "N/A",
            "period_months": period_months,
            "cumulative": record.cumulative,
            "revenue": _round_num(record.revenue),
            "operating_income": _round_num(record.operating_income),
            "net_income": _round_num(record.net_income),
            "roe_percent": _round_num(roe),
            "roa_percent": _round_num(roa),
            "operating_margin_percent": _round_num(operating_margin),
            "revenue_growth_yoy_percent": _round_num(revenue_growth_yoy),
            "profit_growth_yoy_percent": _round_num(profit_growth_yoy),
            "equity_ratio_percent": _round_num(equity_ratio),
            "operating_cf": _round_num(record.operating_cf),
            "free_cash_flow": _round_num(free_cash_flow),
        }
        if record.provisional:
            entry["provisional"] = True
        if record.statement_type:
            entry["statement_type"] = record.statement_type
        if record.source_attribution:
            entry["source_attribution"] = record.source_attribution
        if record.source_details:
            entry["source_details"] = record.source_details

        series.append(entry)

    return series


def _pick_number(
    primary: Mapping[str, object], aliases: Sequence[str], fallback: Mapping[str, object]
) -> float | None:
    value = _pick_from_mapping(mapping=primary, aliases=aliases)
    if value is not None:
        return value
    return _pick_from_mapping(mapping=fallback, aliases=aliases)


def _pick_from_mapping(mapping: Mapping[str, object], aliases: Sequence[str]) -> float | None:
    normalized_map: dict[str, object] = {}
    for key, value in mapping.items():
        normalized_key = _normalize_key(key)
        if normalized_key not in normalized_map:
            normalized_map[normalized_key] = value

    for alias in aliases:
        normalized_alias = _normalize_key(alias)
        matched = normalized_map.get(normalized_alias)
        numeric = _to_float(matched)
        if numeric is not None:
            return numeric

    return None


def _normalize_key(value: str) -> str:
    lower = value.lower()
    return "".join(ch for ch in lower if ch.isalnum())


def _to_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        if cleaned in {"", "-", "--", "N/A", "n/a", "null", "None"}:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    if isinstance(value, dict):
        value_mapping = _as_mapping(value)
        for key in ("value", "amount", "current", "fy"):
            nested = value_mapping.get(key)
            numeric = _to_float(nested)
            if numeric is not None:
                return numeric
        return None
    return None


def _to_int(value: object) -> int | None:
    numeric = _to_float(value)
    if numeric is None:
        return None
    return int(numeric)


def _as_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, dict):
        return value
    return {}


def _as_str(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _compute_period_months(period_start: str | None, period_end: str | None) -> int | None:
    """Compute period length in months from ISO date strings.

    Returns None if either date is missing or unparseable.
    """
    if not period_start or not period_end:
        return None
    try:
        start = date.fromisoformat(period_start)
        end = date.fromisoformat(period_end)
    except ValueError:
        return None
    # Financial periods start on 1st and end on last day of month,
    # so add 1 to include the end month.
    months = (end.year - start.year) * 12 + (end.month - start.month + 1)
    if months <= 0:
        return None
    return months


def _ratio_percent(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return (numerator / denominator) * 100.0


def _growth_percent(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return ((current - previous) / abs(previous)) * 100.0


def _sum_nullable(first: float | None, second: float | None) -> float | None:
    if first is None and second is None:
        return None
    return (first or 0.0) + (second or 0.0)


def _round_num(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 2)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _extract_candidates(payload: dict[str, object], fallback_ticker: str) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []

    periods = payload.get("periods")
    if isinstance(periods, list):
        for period in periods:
            if isinstance(period, dict):
                candidates.append(
                    _merge_period(
                        period=period,
                        ticker=_as_str(payload.get("ticker")) or fallback_ticker,
                        company_name=_as_str(payload.get("company_name")),
                    )
                )

    documents = payload.get("documents")
    if isinstance(documents, list):
        for document in documents:
            if not isinstance(document, dict):
                continue
            document_periods = document.get("periods")
            if not isinstance(document_periods, list):
                continue
            for period in document_periods:
                if isinstance(period, dict):
                    candidates.append(
                        _merge_period(
                            period=period,
                            ticker=_as_str(document.get("ticker")) or fallback_ticker,
                            company_name=_as_str(document.get("company_name")),
                        )
                    )

    period_index = payload.get("period_index")
    if isinstance(period_index, list):
        for period in period_index:
            if isinstance(period, dict):
                candidates.append(
                    _merge_period(
                        period=period,
                        ticker=_as_str(payload.get("ticker")) or fallback_ticker,
                        company_name=_as_str(payload.get("company_name")),
                    )
                )

    # Handle integrated_financials.json format (annual/quarterly arrays)
    annual = payload.get("annual")
    if isinstance(annual, list):
        top_ticker = _as_str(payload.get("ticker")) or fallback_ticker
        top_company = _as_str(payload.get("company_name"))
        for entry in annual:
            if isinstance(entry, dict):
                merged = dict(entry)
                merged["ticker"] = top_ticker
                merged["company_name"] = top_company
                merged["period"] = "FY"
                candidates.append(merged)

    quarterly = payload.get("quarterly")
    if isinstance(quarterly, list):
        top_ticker = _as_str(payload.get("ticker")) or fallback_ticker
        top_company = _as_str(payload.get("company_name"))
        for entry in quarterly:
            if isinstance(entry, dict):
                merged = dict(entry)
                merged["ticker"] = top_ticker
                merged["company_name"] = top_company
                merged["period"] = _as_str(entry.get("quarter")) or "Q"
                candidates.append(merged)

    if candidates:
        return candidates
    # Fallback: only use payload if it has a valid fiscal_year to prevent None pollution
    if _to_int(payload.get("fiscal_year")) is not None or _to_int(payload.get("fiscalYear")) is not None:
        return [payload]
    return []


def _merge_period(period: dict[str, object], ticker: str, company_name: str | None) -> dict[str, object]:
    merged: dict[str, object] = dict(period)
    merged["ticker"] = ticker
    merged["company_name"] = company_name
    merged["period"] = _as_str(period.get("period_type")) or _as_str(period.get("period")) or "FY"
    return merged


_PERIOD_TYPE_PRIORITY: dict[str, int] = {"mixed": 2, "duration": 1, "instant": 0}


def _nonnull_financial_count(record: FinancialRecord) -> int:
    """Count non-null financial fields for dedup ranking."""
    return sum(
        1
        for value in (
            record.revenue,
            record.operating_income,
            record.net_income,
            record.total_assets,
            record.equity,
            record.operating_cf,
            record.investing_cf,
        )
        if value is not None
    )


def _dedup_sort_key(record: FinancialRecord) -> tuple[int, int, str]:
    """Sort key: nonnull count desc, period_type priority desc, period_end desc."""
    return (
        _nonnull_financial_count(record),
        _PERIOD_TYPE_PRIORITY.get((record.period or "").lower(), -1),
        record.period_end or "",
    )


def _deduplicate_records(records: list[FinancialRecord]) -> list[FinancialRecord]:
    """Deduplicate: remove exact duplicates, then select one representative per fiscal_year.

    Selection criteria (higher wins):
      1. Non-null financial field count
      2. period_type priority: mixed > duration > instant
      3. period_end (newer is better)
    """
    # Phase 1: remove exact duplicates
    unique: list[FinancialRecord] = []
    seen: set[tuple[object, ...]] = set()
    for record in records:
        key = (
            record.fiscal_year,
            record.period,
            record.period_end,
            record.revenue,
            record.operating_income,
            record.net_income,
            record.total_assets,
            record.equity,
            record.operating_cf,
            record.investing_cf,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)

    # Phase 2: one representative per (fiscal_year, period_group)
    # Normalize period to group key: FY/Q1/Q2/Q3/Q4 stay as-is,
    # other values (mixed/duration/instant) group as "FY"
    def _period_group(record: FinancialRecord) -> str:
        p = (record.period or "").upper()
        if p in ("Q1", "Q2", "Q3", "Q4"):
            return p
        return "FY"

    groups: dict[tuple[int | None, str], list[FinancialRecord]] = {}
    for record in unique:
        key = (record.fiscal_year, _period_group(record))
        groups.setdefault(key, []).append(record)

    result: list[FinancialRecord] = []
    for group in groups.values():
        result.append(max(group, key=_dedup_sort_key))
    return result
