#!/usr/bin/env python3
"""
T6相当: ソース間突合QAスクリプト

T4(J-Quants)とT5(EDINET構造化)のクロスチェックを実行し、
source_reconciliation.json を生成する。

T5R2修正適用:
  - 照合キーは補正後 period_end を使用（period_end_original ではない）
  - 半期報告書は T4 の 2Q レコードと照合

データ構造前提:
  EDINET: documents[].financials.{balance_sheet|income_statement|cash_flow}
          .tables[].records[] — item名マッチングで値を抽出、単位=千円
  J-Quants: records[].actuals.{revenue|operating_income|...} — 単位=円

Usage:
    python3 skills/disclosure-expansion/scripts/reconcile.py \
        --ticker 2780 \
        --edinet-data data/2780/processed/shihanki_structured.json \
        --jquants-data data/2780/processed/jquants_fins_statements.json \
        --output data/2780/qa/source_reconciliation.json \
        --tolerance 0.0001
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path


COMPARE_FIELDS = ["revenue", "operating_income", "net_income", "total_assets", "equity"]

# EDINET item name → compare field mapping
# Each entry: (field_name, section_key, item_patterns)
# item_patterns: list of (pattern, match_type) where match_type is "exact" or "contains"
EDINET_ITEM_MAP = [
    ("revenue", "income_statement", [
        ("売上高", "exact"),
        ("営業収益", "exact"),
    ]),
    ("operating_income", "income_statement", [
        ("営業利益又は営業損失（△）", "exact"),
        ("営業利益", "exact"),
    ]),
    ("net_income", "income_statement", [
        ("親会社株主に帰属する", "contains"),
    ]),
    ("total_assets", "balance_sheet", [
        ("資産合計", "exact"),
    ]),
    ("equity", "balance_sheet", [
        ("純資産合計", "exact"),
    ]),
]

# Unit detection from table headers
UNIT_PATTERNS = [
    (re.compile(r"百万円"), 1_000_000),
    (re.compile(r"千円"), 1_000),
    (re.compile(r"（単位：円）|（円）"), 1),
]
DEFAULT_UNIT_MULTIPLIER = 1_000  # 千円 is the most common in quarterly reports


def _detect_unit(headers: list[str]) -> int:
    """Detect unit multiplier from table headers."""
    header_text = " ".join(str(h) for h in headers if h)
    for pattern, multiplier in UNIT_PATTERNS:
        if pattern.search(header_text):
            return multiplier
    return DEFAULT_UNIT_MULTIPLIER


def _item_matches(item_label: str, pattern: str, match_type: str) -> bool:
    """Match an item label against a pattern."""
    if match_type == "exact":
        return item_label.strip() == pattern
    elif match_type == "contains":
        return pattern in item_label
    return False


def _extract_current_period_value(record: dict) -> float | None:
    """Extract the current period value (highest column_index) from a record."""
    values = record.get("values", [])
    if not values:
        return None
    # Take the value with the highest column_index (= current period)
    best = max(values, key=lambda v: v.get("column_index", 0))
    return best.get("parsed")


def _load_edinet_periods_v1(data: dict) -> dict:
    """Load legacy T5 structured data (documents[].financials.tables[])."""
    periods = {}

    for doc in data.get("documents", []):
        doc_id = doc.get("doc_id") or doc.get("metadata", {}).get("endpoint_or_doc_id", "unknown")
        doc_type = doc.get("doc_type_code", "")
        metadata = doc.get("metadata", {})
        period_end = doc.get("period_end") or metadata.get("period_end")
        if not period_end:
            continue

        entry = {
            "doc_id": doc_id,
            "doc_type_code": doc_type,
            "period_end": period_end,
            "period_end_original": doc.get("period_end_original") or metadata.get("period_end_original"),
            "source": "edinet",
        }

        financials = doc.get("financials", {})

        for field_name, section_key, patterns in EDINET_ITEM_MAP:
            section = financials.get(section_key, {})
            tables = section.get("tables", [])
            found_value = None

            for table in tables:
                unit_mult = _detect_unit(table.get("headers", []))
                for rec in table.get("records", []):
                    item_label = rec.get("item", "")
                    for pattern, match_type in patterns:
                        if _item_matches(item_label, pattern, match_type):
                            raw_val = _extract_current_period_value(rec)
                            if raw_val is not None:
                                found_value = raw_val * unit_mult
                            break
                    if found_value is not None:
                        break
                if found_value is not None:
                    break

            entry[field_name] = found_value

        periods[period_end] = entry

    return periods


# Mapping from period_index flat fields to compare fields
_PERIOD_INDEX_FIELD_MAP = {
    "revenue": ("pl", "revenue"),
    "operating_income": ("pl", "operating_income"),
    "net_income": ("pl", "net_income"),
    "total_assets": ("bs", "total_assets"),
    "equity": ("bs", "total_equity"),
}


def _load_edinet_periods_v2(data: dict) -> dict:
    """Load T2-fixed parser output (period_index[] with bs/pl/cf sub-objects)."""
    periods = {}
    period_index = data.get("period_index", [])

    for p in period_index:
        period_end = p.get("period_end")
        if not period_end:
            continue

        source_doc_ids = p.get("source_document_ids", [])
        entry = {
            "doc_id": source_doc_ids[0] if source_doc_ids else "unknown",
            "doc_type_code": None,
            "period_end": period_end,
            "period_end_original": None,
            "source": "edinet",
            "period_type": p.get("period_type"),
        }

        for compare_field, (section, field) in _PERIOD_INDEX_FIELD_MAP.items():
            section_data = p.get(section, {})
            entry[compare_field] = section_data.get(field)

        # Keep the entry with more non-null compare fields if duplicate
        if period_end in periods:
            existing = periods[period_end]
            new_count = sum(1 for f in COMPARE_FIELDS if entry.get(f) is not None)
            old_count = sum(1 for f in COMPARE_FIELDS if existing.get(f) is not None)
            if new_count <= old_count:
                continue

        periods[period_end] = entry

    return periods


def load_edinet_periods(edinet_path: str) -> dict:
    """Load EDINET data, auto-detecting format (v1: tables, v2: period_index)."""
    data = json.loads(Path(edinet_path).read_text())

    # Detect format: v2 has period_index with bs/pl/cf sub-objects
    if data.get("period_index") and any(
        p.get("bs") or p.get("pl") or p.get("cf")
        for p in data.get("period_index", [])
    ):
        return _load_edinet_periods_v2(data)

    return _load_edinet_periods_v1(data)


def load_jquants_periods(jquants_path: str) -> dict:
    """Load T4 J-Quants data, extract from records[].actuals,
    and index by period_end. Filters out records with all-null actuals."""
    data = json.loads(Path(jquants_path).read_text())
    periods = {}
    records = data if isinstance(data, list) else data.get("records", data.get("statements", []))

    for rec in records:
        period_end = rec.get("period_end")
        if not period_end:
            continue

        actuals = rec.get("actuals", {})

        # Skip records with all-null actuals (e.g., EarnForecastRevision)
        if all(actuals.get(f) is None for f in COMPARE_FIELDS):
            continue

        entry = {
            "source": "jquants",
            "period_end": period_end,
            "type_of_current_period": rec.get("type_of_current_period"),
            "type_of_document": rec.get("type_of_document"),
            "revenue": actuals.get("revenue"),
            "operating_income": actuals.get("operating_income"),
            "net_income": actuals.get("net_income"),
            "total_assets": actuals.get("total_assets"),
            "equity": actuals.get("equity"),
            "operating_cf": actuals.get("operating_cf"),
        }

        # If duplicate period_end, keep the record with more non-null values
        if period_end in periods:
            existing = periods[period_end]
            new_count = sum(1 for f in COMPARE_FIELDS if entry.get(f) is not None)
            old_count = sum(1 for f in COMPARE_FIELDS if existing.get(f) is not None)
            if new_count <= old_count:
                continue

        periods[period_end] = entry

    return periods


def compare_values(edinet_val, jquants_val, tolerance: float) -> dict:
    """Compare two values within tolerance."""
    if edinet_val is None and jquants_val is None:
        return {"match": "BOTH_NULL", "edinet": None, "jquants": None}
    if edinet_val is None:
        return {"match": "EDINET_NULL", "edinet": None, "jquants": jquants_val}
    if jquants_val is None:
        return {"match": "JQUANTS_NULL", "edinet": edinet_val, "jquants": None}

    if jquants_val == 0 and edinet_val == 0:
        return {"match": "MATCH", "edinet": 0, "jquants": 0, "diff_pct": 0}

    if jquants_val == 0:
        return {
            "match": "MISMATCH",
            "edinet": edinet_val,
            "jquants": jquants_val,
            "diff_pct": None,
            "note": "jquants_val is 0",
        }

    diff_pct = abs(edinet_val - jquants_val) / abs(jquants_val)
    match = "MATCH" if diff_pct <= tolerance else "MISMATCH"
    return {
        "match": match,
        "edinet": edinet_val,
        "jquants": jquants_val,
        "diff_pct": round(diff_pct, 6),
    }


def reconcile(edinet_path: str, jquants_path: str, tolerance: float) -> dict:
    """Execute reconciliation between EDINET and J-Quants data."""
    edinet = load_edinet_periods(edinet_path)
    jquants = load_jquants_periods(jquants_path)

    all_periods = sorted(set(list(edinet.keys()) + list(jquants.keys())))
    overlap_periods = sorted(set(edinet.keys()) & set(jquants.keys()))

    comparisons = []
    summary = {
        "total": len(all_periods),
        "overlap": len(overlap_periods),
        "edinet_only": 0,
        "jquants_only": 0,
        "match": 0,
        "mismatch": 0,
        "invalid_comparison": 0,
    }

    for period in all_periods:
        e = edinet.get(period)
        j = jquants.get(period)

        if e and not j:
            comparisons.append({
                "period_end": period,
                "coverage": "edinet_only",
                "doc_id": e.get("doc_id"),
                "doc_type_code": e.get("doc_type_code"),
            })
            summary["edinet_only"] += 1
            continue

        if j and not e:
            comparisons.append({
                "period_end": period,
                "coverage": "jquants_only",
                "type_of_current_period": j.get("type_of_current_period"),
            })
            summary["jquants_only"] += 1
            continue

        # Overlap: compare fields
        comp = {
            "period_end": period,
            "coverage": "overlap",
            "doc_id": e.get("doc_id"),
            "doc_type_code": e.get("doc_type_code"),
            "period_end_original": e.get("period_end_original"),
            "jquants_period_type": j.get("type_of_current_period"),
            "fields": {},
        }

        all_match = True
        non_null_comparisons = 0
        for field in COMPARE_FIELDS:
            result = compare_values(
                e.get(field), j.get(field), tolerance
            )
            comp["fields"][field] = result
            if result["match"] == "MISMATCH":
                all_match = False
            if result["match"] not in ("BOTH_NULL",):
                non_null_comparisons += 1

        # Guard: if all fields are BOTH_NULL, mark as invalid_comparison
        if non_null_comparisons == 0:
            comp["overall"] = "INVALID_COMPARISON"
            comp["note"] = "All compare fields are null on both sides — no meaningful comparison"
            summary["invalid_comparison"] += 1
        elif all_match:
            comp["overall"] = "MATCH"
            summary["match"] += 1
        else:
            comp["overall"] = "MISMATCH"
            summary["mismatch"] += 1

        comparisons.append(comp)

    return {
        "reconciliation": {
            "generated_at": datetime.now().isoformat(),
            "tolerance": tolerance,
            "compare_fields": COMPARE_FIELDS,
            "edinet_source": edinet_path,
            "jquants_source": jquants_path,
            "edinet_unit": "千円 (×1000 to JPY)",
            "jquants_unit": "JPY",
            "note": "period_end uses T5R2-corrected values (半期報告書=中間期末日)",
        },
        "summary": summary,
        "comparisons": comparisons,
    }


def main():
    parser = argparse.ArgumentParser(description="T6: ソース間突合QA")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--edinet-data", required=True,
                        help="T5 structured JSON path")
    parser.add_argument("--jquants-data", required=True,
                        help="T4 J-Quants processed JSON path")
    parser.add_argument("--output", required=True,
                        help="Output reconciliation JSON path")
    parser.add_argument("--tolerance", type=float, default=0.0001,
                        help="Tolerance for numeric comparison (default: 0.01%%)")
    args = parser.parse_args()

    # Validate inputs exist
    for path in [args.edinet_data, args.jquants_data]:
        if not Path(path).exists():
            print(f"ERROR: Input file not found: {path}", file=sys.stderr)
            sys.exit(1)

    result = reconcile(args.edinet_data, args.jquants_data, args.tolerance)

    # Ensure output directory exists
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))

    print(f"Reconciliation complete: {args.output}")
    s = result["summary"]
    print(f"  Total periods: {s['total']}")
    print(f"  Overlap: {s['overlap']}")
    print(f"  Match: {s['match']}")
    print(f"  Mismatch: {s['mismatch']}")
    print(f"  Invalid comparison: {s['invalid_comparison']}")
    print(f"  EDINET only: {s['edinet_only']}")
    print(f"  J-Quants only: {s['jquants_only']}")

    # Exit with non-zero if any mismatch or invalid comparison
    if s["mismatch"] > 0 or s["invalid_comparison"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
