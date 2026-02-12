from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
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


def calculate_metrics_payload(parsed_dir: Path, ticker: str) -> dict[str, object]:
    records = load_financial_records(parsed_dir=parsed_dir, ticker=ticker)
    metrics_series = _build_metrics_series(records=records)

    company_name = None
    if records:
        company_name = records[-1].company_name

    latest_snapshot: dict[str, object] | None = None
    if metrics_series:
        last = metrics_series[-1]
        latest_snapshot = dict(last)

    return {
        "ticker": ticker,
        "company_name": company_name or "Unknown",
        "generated_at": _utc_now_iso(),
        "source_count": len(records),
        "metrics_series": metrics_series,
        "latest_snapshot": latest_snapshot,
    }


def write_metrics_payload(payload: dict[str, object], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_financial_records(parsed_dir: Path, ticker: str) -> list[FinancialRecord]:
    if not parsed_dir.exists():
        return []

    records: list[FinancialRecord] = []
    for json_path in sorted(parsed_dir.glob("*.json")):
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

    records.sort(
        key=lambda record: (
            record.fiscal_year is None,
            -1 if record.fiscal_year is None else record.fiscal_year,
            record.period or "",
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
        aliases=("equity", "net_assets", "自己資本", "純資産", "純資産合計"),
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
    )


def _build_metrics_series(records: Sequence[FinancialRecord]) -> list[dict[str, object]]:
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

        series.append(
            {
                "fiscal_year": record.fiscal_year,
                "period": record.period or "N/A",
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
        )
        previous = record

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

    if candidates:
        return candidates
    return [payload]


def _merge_period(period: dict[str, object], ticker: str, company_name: str | None) -> dict[str, object]:
    merged: dict[str, object] = dict(period)
    merged["ticker"] = ticker
    merged["company_name"] = company_name
    merged["period"] = _as_str(period.get("period_type")) or _as_str(period.get("period")) or "FY"
    return merged


def _deduplicate_records(records: list[FinancialRecord]) -> list[FinancialRecord]:
    deduplicated: list[FinancialRecord] = []
    seen: set[tuple[object, ...]] = set()
    for record in records:
        key = (
            record.fiscal_year,
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
        deduplicated.append(record)
    return deduplicated
