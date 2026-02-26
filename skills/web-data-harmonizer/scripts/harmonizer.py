"""web-data-harmonizer core module.

web-researcher の出力をパイプライン互換スキーマに変換する。
ソース別のフラット構造データ（文字列混在・期間情報なし）を、
数値型 + 期間情報 + source_attribution 付きの統一スキーマに正規化する。
"""

from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta, timezone

_JST = timezone(timedelta(hours=9))

# 単位マッピング（処理順序が重要: 百万 を 万 より先に処理）
_UNIT_MAP: list[tuple[str, float]] = [
    ("兆", 1e12),
    ("億", 1e8),
    ("百万", 1e6),
    ("万", 1e4),
]

_NULL_STRINGS = frozenset({"---", "--", "N/A", "NA", "n/a", "", "-", "－", "—"})


# ------------------------------------------------------------------
# 1. 日本語数値パーサー
# ------------------------------------------------------------------


def _parse_japanese_number(text: str | None) -> float | None:
    """日本語数値文字列を float に変換する。

    Examples:
        >>> _parse_japanese_number('1,234百万円')
        1234000000.0
        >>> _parse_japanese_number('△1,234')
        -1234.0
        >>> _parse_japanese_number('▲1,234')
        -1234.0
        >>> _parse_japanese_number('1兆2,345億円')
        1234500000000.0
        >>> _parse_japanese_number('---')
        >>> _parse_japanese_number(None)
    """
    if text is None:
        return None
    s = str(text).strip()
    if s in _NULL_STRINGS:
        return None

    negative = False
    if s.startswith(("△", "▲")):
        negative = True
        s = s[1:]
    elif s.startswith(("-", "−", "ー")):
        negative = True
        s = s[1:]

    # 単位サフィックスを除去
    s = re.sub(r"[%％倍円株]$", "", s.strip()).strip()
    if not s:
        return None

    # 兆/億/百万/万 を含む場合
    has_unit = any(unit in s for unit, _ in _UNIT_MAP)
    if has_unit:
        total = 0.0
        remaining = s
        for unit_char, multiplier in _UNIT_MAP:
            if unit_char in remaining:
                parts = remaining.split(unit_char, 1)
                num_str = parts[0].replace(",", "").strip()
                if num_str:
                    try:
                        total += float(num_str) * multiplier
                    except ValueError:
                        return None
                remaining = parts[1] if len(parts) > 1 else ""
        # 残余部分
        remaining = remaining.replace(",", "").strip()
        remaining = re.sub(r"[%％倍円株]$", "", remaining).strip()
        if remaining:
            try:
                total += float(remaining)
            except ValueError:
                pass
        return -total if negative else total

    # 通常の数値: カンマ除去
    s = s.replace(",", "")
    try:
        value = float(s)
        return -value if negative else value
    except ValueError:
        return None


# ------------------------------------------------------------------
# 2. 期間推定ユーティリティ
# ------------------------------------------------------------------


def _infer_period_end(period_str: str | None, source: str) -> str | None:
    """期間文字列から period_end (YYYY-MM-DD) を推定する。

    Args:
        period_str: "2024-03" (yahoo) or "2024.03" (kabutan)
        source: "yahoo" or "kabutan"

    Returns:
        "2024-03-31" 形式の月末日。不正形式なら None。
    """
    if not period_str:
        return None

    s = str(period_str).strip()

    m = re.match(r"(\d{4})[.\-/](\d{1,2})", s)
    if not m:
        return None

    year = int(m.group(1))
    month = int(m.group(2))

    if not (1 <= month <= 12):
        return None
    if not (1900 <= year <= 2100):
        return None

    _, last_day = calendar.monthrange(year, month)
    return f"{year:04d}-{month:02d}-{last_day:02d}"


def _infer_fiscal_year(period_end: str | None) -> int | None:
    """period_end から fiscal_year を推定する。

    "2024-03-31" → 2024
    """
    if not period_end:
        return None
    m = re.match(r"(\d{4})-", period_end)
    return int(m.group(1)) if m else None


# ------------------------------------------------------------------
# Helper: float 変換
# ------------------------------------------------------------------


def _to_float(value: object) -> float | None:
    """数値を float に変換する。文字列なら _parse_japanese_number を使う。"""
    if value is None:
        return None
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return float(value)
    if isinstance(value, str):
        return _parse_japanese_number(value)
    return None


# ------------------------------------------------------------------
# Helper: annual エントリテンプレート
# ------------------------------------------------------------------


def _make_annual_entry(
    period_end: str | None = None,
    fiscal_year: int | None = None,
    source: str = "web:unknown",
    revenue: float | None = None,
    operating_income: float | None = None,
    ordinary_income: float | None = None,
    net_income: float | None = None,
    gross_profit: float | None = None,
    eps: float | None = None,
) -> dict:
    """annual エントリを生成する。BS/CF は Web 源では取得不可のため null。"""
    return {
        "period_end": period_end,
        "fiscal_year": fiscal_year,
        "quarter": "FY",
        "source": source,
        "statement_type": None,
        "bs": {
            "total_assets": None,
            "current_assets": None,
            "noncurrent_assets": None,
            "total_liabilities": None,
            "current_liabilities": None,
            "noncurrent_liabilities": None,
            "total_equity": None,
            "net_assets": None,
        },
        "pl": {
            "revenue": revenue,
            "operating_income": operating_income,
            "ordinary_income": ordinary_income,
            "net_income": net_income,
            "gross_profit": gross_profit,
            "eps": eps,
        },
        "cf": {
            "operating_cf": None,
            "investing_cf": None,
            "financing_cf": None,
            "free_cash_flow": None,
        },
    }


# ------------------------------------------------------------------
# 3. ソース別ハーモナイザー
# ------------------------------------------------------------------


def _harmonize_yahoo(data: dict) -> list[dict]:
    """Yahoo Finance データを annual エントリ形式に変換する。

    入力: sources.yahoo.data (web-researcher 出力)
    """
    if not data:
        return []

    financials = data.get("financials", [])
    if not financials:
        return []

    results: list[dict] = []
    for item in financials:
        period_end = _infer_period_end(item.get("period"), "yahoo")
        fiscal_year = _infer_fiscal_year(period_end)

        entry = _make_annual_entry(
            period_end=period_end,
            fiscal_year=fiscal_year,
            source="web:yahoo",
            revenue=_to_float(item.get("revenue")),
            operating_income=_to_float(item.get("operating_income")),
        )
        results.append(entry)

    return results


def _harmonize_kabutan(data: dict) -> list[dict]:
    """株探データを annual エントリ形式に変換する。

    入力: sources.kabutan.data
    kabutan は ordinary_income, net_income, eps も提供する。
    """
    if not data:
        return []

    financials = data.get("financials", [])
    if not financials:
        return []

    results: list[dict] = []
    for item in financials:
        period_end = _infer_period_end(item.get("period"), "kabutan")
        fiscal_year = _infer_fiscal_year(period_end)

        entry = _make_annual_entry(
            period_end=period_end,
            fiscal_year=fiscal_year,
            source="web:kabutan",
            revenue=_to_float(item.get("revenue")),
            operating_income=_to_float(item.get("operating_income")),
            ordinary_income=_to_float(item.get("ordinary_income")),
            net_income=_to_float(item.get("net_income")),
            eps=_to_float(item.get("eps")),
        )
        results.append(entry)

    return results


def _harmonize_shikiho(data: dict) -> list[dict]:
    """四季報データを annual エントリ形式に変換する。

    入力: sources.shikiho.data
    earnings_forecast のキー ('売上高', '営業利益' 等) を
    _parse_japanese_number で文字列→数値変換する。
    """
    if not data:
        return []

    forecast = data.get("earnings_forecast")
    if not forecast:
        return []

    revenue = _parse_japanese_number(forecast.get("売上高"))
    operating_income = _parse_japanese_number(forecast.get("営業利益"))
    ordinary_income = _parse_japanese_number(forecast.get("経常利益"))
    # 「純利益」を優先し、なければ「当期純利益」にフォールバック
    net_income = _parse_japanese_number(forecast.get("純利益"))
    if net_income is None:
        net_income = _parse_japanese_number(forecast.get("当期純利益"))

    # 全て None なら空リスト
    if all(v is None for v in (revenue, operating_income, ordinary_income, net_income)):
        return []

    entry = _make_annual_entry(
        period_end=None,
        fiscal_year=None,
        source="web:shikiho",
        revenue=revenue,
        operating_income=operating_income,
        ordinary_income=ordinary_income,
        net_income=net_income,
    )

    return [entry]


# ------------------------------------------------------------------
# 4. インジケーター抽出
# ------------------------------------------------------------------


def _extract_indicators(sources: dict) -> dict:
    """yahoo/kabutan の indicators をマージ（kabutan 優先）。

    出力: {per, pbr, dividend_yield, market_cap, eps, shares_outstanding}
    すべて float | int | None。
    """
    result: dict = {
        "per": None,
        "pbr": None,
        "dividend_yield": None,
        "market_cap": None,
        "eps": None,
        "shares_outstanding": None,
    }

    # Yahoo (ベース)
    yahoo = sources.get("yahoo", {})
    if yahoo.get("collected") and yahoo.get("data"):
        indicators = yahoo["data"].get("indicators") or {}
        for key in ("per", "pbr", "dividend_yield", "market_cap"):
            val = _to_float(indicators.get(key))
            if val is not None:
                result[key] = val
        # shares_outstanding も float | None で統一
        shares = _to_float(indicators.get("shares_outstanding"))
        if shares is not None:
            result["shares_outstanding"] = shares

    # Shikiho (Yahoo の上に上書き)
    shikiho = sources.get("shikiho", {})
    if shikiho.get("collected") and shikiho.get("data"):
        indicators = shikiho["data"].get("indicators") or {}
        # shikiho は大文字キー (PER, PBR) の場合がある
        _SHIKIHO_KEY_MAP = {
            "per": ["per", "PER"],
            "pbr": ["pbr", "PBR"],
            "dividend_yield": ["dividend_yield", "配当利回り"],
            "market_cap": ["market_cap", "時価総額"],
        }
        for canonical, aliases in _SHIKIHO_KEY_MAP.items():
            for alias in aliases:
                val = _to_float(indicators.get(alias))
                if val is not None:
                    result[canonical] = val
                    break

    # Kabutan (最高優先度で上書き)
    kabutan = sources.get("kabutan", {})
    if kabutan.get("collected") and kabutan.get("data"):
        indicators = kabutan["data"].get("indicators") or {}
        for key in ("per", "pbr", "dividend_yield", "market_cap"):
            val = _to_float(indicators.get(key))
            if val is not None:
                result[key] = val

        # eps: kabutan financials の最新期エントリから取得
        financials = kabutan["data"].get("financials", [])
        if financials:
            # period 降順ソートで最新を選択（kabutan は通常先頭が最新）
            best = max(
                financials,
                key=lambda f: _infer_period_end(f.get("period"), "kabutan") or "",
            )
            latest_eps = _to_float(best.get("eps"))
            if latest_eps is not None:
                result["eps"] = latest_eps

    return result


# ------------------------------------------------------------------
# 5. 定性データ抽出
# ------------------------------------------------------------------


def _extract_qualitative(sources: dict) -> dict:
    """定性データを各ソースから抽出する。

    - shikiho: company_overview, consensus, shareholders
    - kabutan: earnings_flash, news
    - homepage: ir_links, company_info
    """
    result: dict = {
        "company_overview": None,
        "consensus": None,
        "shareholders": None,
        "earnings_flash": None,
        "news": None,
        "ir_links": None,
        "company_info": None,
    }

    # shikiho
    shikiho = sources.get("shikiho", {})
    if shikiho.get("collected") and shikiho.get("data"):
        data = shikiho["data"]
        result["company_overview"] = data.get("company_overview")
        result["consensus"] = data.get("consensus")
        result["shareholders"] = data.get("shareholders")

    # kabutan
    kabutan = sources.get("kabutan", {})
    if kabutan.get("collected") and kabutan.get("data"):
        data = kabutan["data"]
        result["earnings_flash"] = data.get("earnings_flash")
        result["news"] = data.get("news")

    # homepage
    homepage = sources.get("homepage", {})
    if homepage.get("collected") and homepage.get("data"):
        data = homepage["data"]
        result["ir_links"] = data.get("ir_links")
        result["company_info"] = data.get("company_info")

    return result


# ------------------------------------------------------------------
# 6. マージロジック
# ------------------------------------------------------------------

_SOURCE_PRIORITY: dict[str, int] = {
    "web:shikiho": 0,
    "web:yahoo": 1,
    "web:kabutan": 2,
}


def _merge_periods(all_records: list[list[dict]]) -> list[dict]:
    """同一 period_end のレコードをマージする。

    優先順位: kabutan > yahoo > shikiho (PLフィールドの上書き順)
    source を "web:kabutan+yahoo" 等の結合形式に更新し、
    period_end でソート（降順）する。
    """
    by_period: dict[str | None, list[dict]] = {}
    for records in all_records:
        for rec in records:
            pe = rec.get("period_end")
            if pe not in by_period:
                by_period[pe] = []
            by_period[pe].append(rec)

    merged: list[dict] = []
    for period_end, records in by_period.items():
        # 優先度昇順にソート（後から上書き = 高優先度が勝つ）
        records.sort(key=lambda r: _SOURCE_PRIORITY.get(r.get("source", ""), -1))

        base = _make_annual_entry(period_end=period_end)
        sources_used: list[str] = []

        for rec in records:
            src = rec.get("source", "")
            short = src.replace("web:", "") if src.startswith("web:") else src
            if short and short not in sources_used:
                sources_used.append(short)

            # fiscal_year
            if rec.get("fiscal_year") is not None:
                base["fiscal_year"] = rec["fiscal_year"]

            # PL フィールドをマージ（高優先度が上書き）
            rec_pl = rec.get("pl", {})
            for field in (
                "revenue",
                "operating_income",
                "ordinary_income",
                "net_income",
                "gross_profit",
                "eps",
            ):
                val = rec_pl.get(field)
                if val is not None:
                    base["pl"][field] = val

        # source 文字列を結合
        if sources_used:
            base["source"] = "web:" + "+".join(sources_used)

        merged.append(base)

    # period_end 降順ソート（None は末尾）
    merged.sort(key=lambda r: r.get("period_end") or "", reverse=True)

    return merged


# ------------------------------------------------------------------
# 7. メインエントリポイント
# ------------------------------------------------------------------


def harmonize(web_research: dict, source_filter: str = "all") -> dict:
    """web-researcher 出力をパイプライン互換スキーマに変換する。

    Args:
        web_research: web-researcher の出力 JSON
        source_filter: "all" | "yahoo" | "kabutan" | "shikiho" | "yahoo,kabutan" 等

    Returns:
        {
            "ticker": str,
            "company_name": str | null,
            "generated_at": ISO datetime,
            "harmonization_metadata": {...},
            "annual": [annual エントリ],
            "indicators": dict,
            "qualitative": dict,
        }
    """
    # dict 以外の入力に対する防御
    if not isinstance(web_research, dict):
        return {
            "ticker": "",
            "company_name": None,
            "generated_at": datetime.now(_JST).isoformat(),
            "harmonization_metadata": {
                "input_sources": {
                    "yahoo": False,
                    "kabutan": False,
                    "shikiho": False,
                    "homepage": False,
                },
                "sources_used": [],
                "sources_skipped": [],
                "source_priority": "kabutan > yahoo > shikiho",
            },
            "annual": [],
            "indicators": {
                "per": None,
                "pbr": None,
                "dividend_yield": None,
                "market_cap": None,
                "eps": None,
                "shares_outstanding": None,
            },
            "qualitative": {
                "company_overview": None,
                "consensus": None,
                "shareholders": None,
                "earnings_flash": None,
                "news": None,
                "ir_links": None,
                "company_info": None,
            },
        }

    sources = web_research.get("sources", {})
    ticker = web_research.get("ticker", "")

    # company_name: shikiho → homepage の順で検索
    company_name = web_research.get("company_name")
    if not company_name:
        shikiho = sources.get("shikiho", {})
        if shikiho.get("collected") and shikiho.get("data"):
            overview = (shikiho["data"].get("company_overview") or {})
            company_name = overview.get("name")
    if not company_name:
        homepage = sources.get("homepage", {})
        if homepage.get("collected") and homepage.get("data"):
            info = (homepage["data"].get("company_info") or {})
            company_name = info.get("company_name")

    # source_filter をパース
    if source_filter == "all":
        allowed = {"yahoo", "kabutan", "shikiho"}
    else:
        allowed = {s.strip() for s in source_filter.split(",")}

    input_sources = {
        "yahoo": sources.get("yahoo", {}).get("collected", False),
        "kabutan": sources.get("kabutan", {}).get("collected", False),
        "shikiho": sources.get("shikiho", {}).get("collected", False),
        "homepage": sources.get("homepage", {}).get("collected", False),
    }

    sources_used: list[str] = []
    sources_skipped: list[str] = []
    all_records: list[list[dict]] = []

    # 各ソースを処理
    _SRC_HANDLERS: list[tuple[str, object]] = [
        ("yahoo", _harmonize_yahoo),
        ("kabutan", _harmonize_kabutan),
        ("shikiho", _harmonize_shikiho),
    ]

    for src_name, handler in _SRC_HANDLERS:
        if src_name not in allowed:
            sources_skipped.append(src_name)
            continue
        src = sources.get(src_name, {})
        if src.get("collected") and src.get("data"):
            records = handler(src["data"])
            if records:
                all_records.append(records)
                sources_used.append(src_name)
            else:
                sources_skipped.append(src_name)
        else:
            sources_skipped.append(src_name)

    annual = _merge_periods(all_records)
    indicators = _extract_indicators(sources)
    qualitative = _extract_qualitative(sources)

    return {
        "ticker": ticker,
        "company_name": company_name,
        "generated_at": datetime.now(_JST).isoformat(),
        "harmonization_metadata": {
            "input_sources": input_sources,
            "sources_used": sources_used,
            "sources_skipped": sources_skipped,
            "source_priority": "kabutan > yahoo > shikiho",
        },
        "annual": annual,
        "indicators": indicators,
        "qualitative": qualitative,
    }
