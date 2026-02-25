"""
financial-integrator: EDINET + J-Quants 統合ロジック

EDINET パーサー出力 (financials.json) と J-Quants 決算データ
(jquants_fins_statements.json) を統合し、銘柄非依存の
integrated_financials.json を生成する。
"""

from __future__ import annotations

import hashlib
import json
import logging
import warnings
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Period helpers
# ------------------------------------------------------------------

def determine_fiscal_year(period_end: str, fye_month: int) -> int:
    """period_end (YYYY-MM-DD) と決算月から会計年度を決定する。"""
    parts = period_end.split("-")
    year, month = int(parts[0]), int(parts[1])
    return year if month <= fye_month else year + 1


def determine_quarter(period_end: str, fye_month: int) -> str:
    """period_end から四半期ラベルを決定する。

    fye_month から動的にマッピングを生成:
      Q1 = fye_month+3, Q2 = fye_month+6, Q3 = fye_month+9, FY = fye_month
    """
    month = int(period_end.split("-")[1])
    quarter_months: dict[int, str] = {}
    for label, offset in [("Q1", 3), ("Q2", 6), ("Q3", 9), ("FY", 12)]:
        m = ((fye_month + offset - 1) % 12) + 1
        quarter_months[m] = label
    return quarter_months.get(month, f"M{month}")


def classify_period(
    period_end: str, period_start: str | None, fye_month: int
) -> str:
    """期間を "annual" または "quarterly" に分類する。

    annual 条件: period_end.month == fye_month AND 期間長 > 300 日
    """
    pe_month = int(period_end.split("-")[1])
    if pe_month != fye_month:
        return "quarterly"
    if period_start is None:
        return "annual"
    pe = date.fromisoformat(period_end)
    ps = date.fromisoformat(period_start)
    duration = (pe - ps).days
    return "annual" if duration > 300 else "quarterly"


# ------------------------------------------------------------------
# Merge
# ------------------------------------------------------------------

def merge_entry(
    edinet_entry: dict | None, jquants_entry: dict | None
) -> dict | None:
    """EDINET 優先、J-Quants で null フィールドを補完。"""
    if edinet_entry is None:
        if jquants_entry:
            jquants_entry["source"] = "jquants"
            return jquants_entry
        return None
    if jquants_entry is None:
        return edinet_entry

    merged = dict(edinet_entry)
    merged["source"] = "both"
    merged["jquants_disclosed_date"] = jquants_entry.get("disclosed_date")

    for section in ["bs", "pl", "cf"]:
        e_sec = merged.get(section, {})
        j_sec = jquants_entry.get(section, {})
        for k, v in j_sec.items():
            if v is not None and e_sec.get(k) is None:
                e_sec[k] = v
        merged[section] = e_sec

    return merged


# ------------------------------------------------------------------
# EDINET extraction
# ------------------------------------------------------------------

def _extract_edinet(
    edinet_data: dict, fye_month: int
) -> tuple[dict[int, dict], dict[str, dict]]:
    """EDINET financials.json から annual / quarterly entries を抽出。"""
    annual_entries: dict[int, dict] = {}
    quarterly_entries: dict[str, dict] = {}

    for doc in edinet_data.get("documents", []):
        doc_id = doc.get("document_id", "")

        for period in doc.get("periods", []):
            pe = period.get("period_end")
            ps = period.get("period_start")
            if not pe:
                continue

            bs = period.get("bs", {})
            pl = period.get("pl", {})
            cf = period.get("cf", {})

            non_null_count = sum(
                1 for v in {**bs, **pl}.values() if v is not None
            )
            if non_null_count < 2:
                continue

            period_type = classify_period(pe, ps, fye_month)
            fy = determine_fiscal_year(pe, fye_month)
            quarter = determine_quarter(pe, fye_month)

            entry = {
                "period_end": pe,
                "period_start": ps,
                "fiscal_year": fy,
                "quarter": quarter,
                "source": "edinet",
                "edinet_doc_id": doc_id,
                "statement_type": "consolidated",
                "bs": {
                    "total_assets": bs.get("total_assets"),
                    "current_assets": bs.get("current_assets"),
                    "noncurrent_assets": bs.get("noncurrent_assets"),
                    "total_liabilities": bs.get("total_liabilities"),
                    "current_liabilities": bs.get("current_liabilities"),
                    "total_equity": bs.get("total_equity"),
                    "net_assets": bs.get("net_assets"),
                },
                "pl": {
                    "revenue": pl.get("revenue"),
                    "gross_profit": pl.get("gross_profit"),
                    "operating_income": pl.get("operating_income"),
                    "ordinary_income": pl.get("ordinary_income"),
                    "net_income": pl.get("net_income"),
                },
                "cf": {
                    "operating_cf": cf.get("operating_cf"),
                    "investing_cf": cf.get("investing_cf"),
                    "financing_cf": cf.get("financing_cf"),
                    "free_cash_flow": cf.get("free_cash_flow"),
                },
            }

            if period_type == "annual" and quarter == "FY":
                annual_entries[fy] = entry
            elif period_type == "quarterly" and quarter != "FY":
                key = f"{fy}_{quarter}"
                if key not in quarterly_entries:
                    quarterly_entries[key] = entry
                else:
                    old_count = sum(
                        1
                        for k in [
                            "revenue",
                            "operating_income",
                            "net_income",
                            "total_assets",
                        ]
                        if quarterly_entries[key].get("pl", {}).get(k) is not None
                        or quarterly_entries[key].get("bs", {}).get(k) is not None
                    )
                    new_count = sum(
                        1
                        for k in [
                            "revenue",
                            "operating_income",
                            "net_income",
                            "total_assets",
                        ]
                        if entry.get("pl", {}).get(k) is not None
                        or entry.get("bs", {}).get(k) is not None
                    )
                    if new_count > old_count:
                        quarterly_entries[key] = entry

    return annual_entries, quarterly_entries


# ------------------------------------------------------------------
# J-Quants extraction
# ------------------------------------------------------------------

def _extract_jquants(
    jquants_data: dict, fye_month: int
) -> tuple[dict[int, dict], dict[str, dict]]:
    """J-Quants データから annual / quarterly entries を抽出。"""
    jquants_annual: dict[int, dict] = {}
    jquants_quarterly: dict[str, dict] = {}

    for rec in jquants_data.get("records", []):
        pe = rec.get("period_end")
        if not pe:
            continue
        actuals = rec.get("actuals", {})
        fy = determine_fiscal_year(pe, fye_month)
        quarter = determine_quarter(pe, fye_month)

        entry = {
            "period_end": pe,
            "period_start": rec.get("period_start"),
            "fiscal_year": fy,
            "quarter": quarter,
            "source": "jquants",
            "disclosed_date": rec.get("disclosed_date"),
            "type_of_current_period": rec.get("type_of_current_period"),
            "type_of_document": rec.get("type_of_document"),
            "bs": {
                "total_assets": actuals.get("total_assets"),
                "total_equity": actuals.get("equity"),
                "net_assets": actuals.get("net_assets"),
            },
            "pl": {
                "revenue": actuals.get("revenue"),
                "operating_income": actuals.get("operating_income"),
                "ordinary_income": actuals.get("ordinary_income"),
                "net_income": actuals.get("net_income"),
            },
            "cf": {
                "operating_cf": actuals.get("operating_cf"),
            },
        }

        if quarter == "FY":
            jquants_annual[fy] = entry
        else:
            key = f"{fy}_{quarter}"
            if key not in jquants_quarterly:
                jquants_quarterly[key] = entry

    return jquants_annual, jquants_quarterly


# ------------------------------------------------------------------
# Coverage helpers
# ------------------------------------------------------------------

def _build_coverage_summary(
    annual_list: list[dict], quarterly_list: list[dict]
) -> dict:
    coverage: dict[str, dict] = {}
    for entry in annual_list + quarterly_list:
        fy_key = f"FY{entry['fiscal_year']}"
        if fy_key not in coverage:
            coverage[fy_key] = {
                "annual": None,
                "quarters": [],
                "sources": set(),
            }
        if entry["quarter"] == "FY":
            coverage[fy_key]["annual"] = entry["source"]
        else:
            if entry["quarter"] not in coverage[fy_key]["quarters"]:
                coverage[fy_key]["quarters"].append(entry["quarter"])
        coverage[fy_key]["sources"].add(entry["source"])

    for fy_key in coverage:
        coverage[fy_key]["sources"] = sorted(coverage[fy_key]["sources"])
        coverage[fy_key]["quarters"] = sorted(coverage[fy_key]["quarters"])

    return dict(sorted(coverage.items()))


def _build_coverage_matrix(
    annual_list: list[dict], quarterly_list: list[dict]
) -> list[dict]:
    matrix = []
    for entry in sorted(
        annual_list + quarterly_list, key=lambda x: x["period_end"]
    ):
        cm: dict = {
            "period_end": entry["period_end"],
            "fiscal_year": entry["fiscal_year"],
            "quarter": entry["quarter"],
            "source": entry["source"],
            "statement_type": entry.get("statement_type", "consolidated"),
        }
        if "edinet_doc_id" in entry:
            cm["edinet_doc_id"] = entry["edinet_doc_id"]
        matrix.append(cm)
    return matrix


def _build_source_priority_rules(coverage_summary: dict) -> dict:
    """coverage_summary から汎用的な source_priority_rules を自動生成。"""
    rules: dict[str, str] = {}
    for fy_key, info in sorted(coverage_summary.items()):
        sources = info["sources"]
        annual_src = info["annual"]
        quarters = info["quarters"]

        parts = []
        if annual_src:
            parts.append(f"annual={annual_src}")
        if quarters:
            parts.append(f"quarters={quarters}")
        parts.append(f"sources={sources}")
        rules[fy_key] = ", ".join(parts)
    return rules


# ------------------------------------------------------------------
# Main integration
# ------------------------------------------------------------------

def integrate(
    ticker: str,
    fye_month: int,
    parsed_dir: Path,
    output_path: Path,
    *,
    company_name: str | None = None,
) -> dict:
    """EDINET + J-Quants 統合メイン関数。

    Args:
        ticker: 銘柄コード
        fye_month: 決算月 (1-12)
        parsed_dir: パーサー出力ディレクトリ
        output_path: 出力 JSON パス
        company_name: 会社名（省略時は ticker を使用）

    Returns:
        出力 JSON dict
    """
    edinet_path = parsed_dir / "financials.json"
    jquants_path = parsed_dir / "jquants_fins_statements.json"

    # --- Load EDINET ---
    edinet_data = json.loads(edinet_path.read_text(encoding="utf-8"))
    edinet_sha = hashlib.sha256(
        edinet_path.read_bytes()
    ).hexdigest()

    # --- Load J-Quants (optional) ---
    jquants_data: dict = {"records": []}
    jquants_sha: str | None = None
    jquants_record_count = 0

    if jquants_path.exists():
        jquants_data = json.loads(
            jquants_path.read_text(encoding="utf-8")
        )
        jquants_sha = hashlib.sha256(
            jquants_path.read_bytes()
        ).hexdigest()
        jquants_record_count = len(jquants_data.get("records", []))
    else:
        warnings.warn(
            f"J-Quants ファイルが見つかりません: {jquants_path}  "
            "EDINET のみで統合します。",
            stacklevel=2,
        )

    # --- Extract ---
    annual_entries, quarterly_entries = _extract_edinet(
        edinet_data, fye_month
    )
    jquants_annual, jquants_quarterly = _extract_jquants(
        jquants_data, fye_month
    )

    # --- Merge ---
    all_annual_fys = sorted(
        set(list(annual_entries.keys()) + list(jquants_annual.keys()))
    )
    annual_list = []
    for fy in all_annual_fys:
        merged = merge_entry(
            annual_entries.get(fy), jquants_annual.get(fy)
        )
        if merged:
            annual_list.append(merged)

    all_q_keys = sorted(
        set(list(quarterly_entries.keys()) + list(jquants_quarterly.keys()))
    )
    quarterly_list = []
    for key in all_q_keys:
        merged = merge_entry(
            quarterly_entries.get(key), jquants_quarterly.get(key)
        )
        if merged:
            quarterly_list.append(merged)

    # --- Coverage ---
    coverage_summary = _build_coverage_summary(annual_list, quarterly_list)
    coverage_matrix = _build_coverage_matrix(annual_list, quarterly_list)
    source_priority_rules = _build_source_priority_rules(coverage_summary)

    # --- Build input_files metadata ---
    input_files: dict = {
        "edinet": {
            "path": str(edinet_path),
            "sha256": edinet_sha,
            "document_count": edinet_data.get("document_count", len(edinet_data.get("documents", []))),
        },
    }
    if jquants_sha is not None:
        input_files["jquants"] = {
            "path": str(jquants_path),
            "sha256": jquants_sha,
            "record_count": jquants_record_count,
        }

    # --- Output ---
    output = {
        "ticker": ticker,
        "company_name": company_name or ticker,
        "fiscal_year_end_month": fye_month,
        "integration_metadata": {
            "generated_at": datetime.now().astimezone().isoformat(),
            "input_files": input_files,
            "coverage_summary": coverage_summary,
            "source_priority_rules": source_priority_rules,
        },
        "coverage_matrix": coverage_matrix,
        "annual": annual_list,
        "quarterly": quarterly_list,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info("Written: %s", output_path)
    logger.info("Annual: %d, Quarterly: %d", len(annual_list), len(quarterly_list))

    return output
