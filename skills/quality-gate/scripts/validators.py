"""Quality gate validators for financial data verification."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class NullRateResult:
    """Result of null rate validation."""

    gate_pass: bool
    total_cells: int
    null_cells: int
    null_rate: float
    threshold: float


@dataclass
class CoverageResult:
    """Result of key coverage validation."""

    gate_pass: bool
    detail: dict[str, dict]  # {"bs": {"pass": bool, "coverage": {...}}, ...}


@dataclass
class RangeResult:
    """Result of value range validation."""

    gate_pass: bool
    violations: list[dict]


@dataclass
class FileResult:
    """Result of file existence validation."""

    gate_pass: bool
    detail: dict[str, dict]  # {"filename": {"exists": bool, "size": int}, ...}


@dataclass
class SchemaResult:
    """Result of JSON schema validation."""

    gate_pass: bool
    missing_keys: list[str]
    detail: str


@dataclass
class DirResult:
    """Result of directory not-empty validation."""

    gate_pass: bool
    detail: dict[str, object]  # {"exists": bool, "file_count": int}


@dataclass
class MetricsRangeResult:
    """Result of metrics value range validation."""

    gate_pass: bool
    violations: list[dict]
    detail: dict[str, object]


@dataclass
class JsonFileSchemaResult:
    """Result of JSON file schema validation."""

    gate_pass: bool
    missing_keys: list[str]
    detail: str


@dataclass
class JsonFileValueRangeResult:
    """Result of JSON file value range validation."""

    gate_pass: bool
    violations: list[dict]
    detail: dict[str, object]


@dataclass
class StepTypeConsistencyResult:
    """Result of step-to-step type consistency validation."""

    gate_pass: bool
    mismatches: list[dict]
    detail: dict[str, object]


@dataclass
class GateResults:
    """Aggregated results from all gates."""

    overall_pass: bool
    gates: list[dict]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_financials(data_dir: Path) -> dict | None:
    """Load financials.json from data directory."""
    path = data_dir / "financials.json"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def extract_periods(financials: dict) -> list[dict]:
    """Extract periods from financials, falling back to documents[].periods.

    Primary source is ``period_index``.  When it is empty or missing,
    collect periods from ``documents[].periods`` as a fallback.
    """
    periods = financials.get("period_index") or []
    if periods:
        return periods

    # Fallback: gather periods from documents
    for doc in financials.get("documents", []):
        doc_periods = doc.get("periods")
        if doc_periods:
            periods.extend(doc_periods)
    return periods


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def validate_null_rate(
    periods: list[dict],
    threshold: float = 0.5,
) -> NullRateResult:
    """Check that the overall null rate across all concepts and periods is below threshold."""
    if not periods:
        return NullRateResult(
            gate_pass=False, total_cells=0, null_cells=0, null_rate=1.0, threshold=threshold,
        )

    total = 0
    nulls = 0
    for period in periods:
        for section in ("bs", "pl", "cf"):
            section_data = period.get(section, {})
            for value in section_data.values():
                total += 1
                if value is None:
                    nulls += 1

    rate = nulls / total if total > 0 else 1.0
    return NullRateResult(
        gate_pass=rate <= threshold,
        total_cells=total,
        null_cells=nulls,
        null_rate=round(rate, 4),
        threshold=threshold,
    )


def validate_key_coverage(
    periods: list[dict],
    requirements: dict[str, dict],
) -> CoverageResult:
    """Check that required keys have non-null values across all periods.

    requirements: {"bs": {"keys": [...], "min_required": 2}, "pl": {...}, "cf": {...}}
    A section passes if at least min_required keys are non-null in ALL periods.
    """
    if not periods:
        detail = {
            section: {
                "pass": False,
                "all_period_keys": 0,
                "min_required": req.get("min_required", 1),
                "coverage": {k: 0 for k in req.get("keys", [])},
            }
            for section, req in requirements.items()
        }
        return CoverageResult(gate_pass=False, detail=detail)

    detail: dict[str, dict] = {}
    all_pass = True

    for section, req in requirements.items():
        keys = req.get("keys", [])
        min_required = req.get("min_required", 1)

        # Filter to periods where at least one check-target key is non-null
        # (excludes stub periods that only hold unrelated instant values)
        relevant = [
            p for p in periods
            if any(p.get(section, {}).get(k) is not None for k in keys)
        ]
        total_periods = len(relevant)

        coverage: dict[str, int] = {}
        for key in keys:
            non_null = sum(
                1 for p in relevant
                if p.get(section, {}).get(key) is not None
            )
            coverage[key] = non_null

        if total_periods == 0:
            section_pass = False
            all_period_keys = 0
        else:
            all_period_keys = sum(1 for k in keys if coverage.get(k, 0) == total_periods)
            section_pass = all_period_keys >= min_required

        detail[section] = {
            "pass": section_pass,
            "all_period_keys": all_period_keys,
            "min_required": min_required,
            "total_periods": total_periods,
            "coverage": coverage,
        }

        if not section_pass:
            all_pass = False

    return CoverageResult(gate_pass=all_pass, detail=detail)


def validate_value_range(
    periods: list[dict],
    rules: dict[str, dict],
) -> RangeResult:
    """Check that values fall within specified ranges.

    rules: {"total_assets": {"min": 0}, "revenue": {"min": 0, "max": 1e15}}
    """
    violations: list[dict] = []

    # Build a lookup: concept -> section (scan ALL periods so that
    # concepts present only in later periods, e.g. CF in Q3, are captured)
    concept_section: dict[str, str] = {}
    for period in periods:
        for section in ("bs", "pl", "cf"):
            for key in period.get(section, {}):
                if key not in concept_section:
                    concept_section[key] = section

    for concept, rule in rules.items():
        section = concept_section.get(concept)
        if section is None:
            continue

        min_val = rule.get("min")
        max_val = rule.get("max")

        for period in periods:
            value = period.get(section, {}).get(concept)
            if value is None:
                continue

            if min_val is not None and value < min_val:
                violations.append({
                    "concept": concept,
                    "period_end": period.get("period_end", "?"),
                    "value": value,
                    "rule": f"min={min_val}",
                    "reason": f"value {value} < min {min_val}",
                })
            if max_val is not None and value > max_val:
                violations.append({
                    "concept": concept,
                    "period_end": period.get("period_end", "?"),
                    "value": value,
                    "rule": f"max={max_val}",
                    "reason": f"value {value} > max {max_val}",
                })

    return RangeResult(gate_pass=len(violations) == 0, violations=violations)


def validate_file_exists(
    data_dir: Path,
    required_files: list[str],
) -> FileResult:
    """Check that required files exist and are non-empty."""
    detail: dict[str, dict] = {}
    all_exist = True

    for filename in required_files:
        path = data_dir / filename
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        detail[filename] = {"exists": exists, "size": size}
        if not exists or size == 0:
            all_exist = False

    return FileResult(gate_pass=all_exist, detail=detail)


def validate_json_schema(
    data: dict,
    required_keys: list[str],
) -> SchemaResult:
    """Check that required top-level keys exist in the JSON data."""
    missing = [k for k in required_keys if k not in data]
    return SchemaResult(
        gate_pass=len(missing) == 0,
        missing_keys=missing,
        detail=f"checked {len(required_keys)} keys, {len(missing)} missing",
    )


def validate_dir_not_empty(data_dir: Path) -> DirResult:
    """Check that data_dir exists and contains at least one file."""
    if not data_dir.is_dir():
        return DirResult(gate_pass=False, detail={"exists": False, "file_count": 0})
    file_count = sum(1 for _ in data_dir.iterdir())
    return DirResult(
        gate_pass=file_count > 0,
        detail={"exists": True, "file_count": file_count},
    )


def validate_metrics_value_range(
    data_dir: Path,
    rules: dict[str, dict],
) -> MetricsRangeResult:
    """Check that metrics in metrics.json fall within specified ranges.

    Loads metrics.json from data_dir and validates latest_snapshot values.
    rules: {"roe_percent": {"min": -100, "max": 200}, ...}
    """
    metrics_path = data_dir / "metrics.json"
    if not metrics_path.exists():
        return MetricsRangeResult(
            gate_pass=False,
            violations=[],
            detail={"error": "metrics.json not found"},
        )

    with metrics_path.open("r", encoding="utf-8") as f:
        metrics = json.load(f)

    violations: list[dict] = []
    snapshot = metrics.get("latest_snapshot", {})

    for key, rule in rules.items():
        value = snapshot.get(key)
        if value is None:
            continue
        min_val = rule.get("min")
        max_val = rule.get("max")
        if min_val is not None and value < min_val:
            violations.append({
                "metric": key,
                "value": value,
                "rule": f"min={min_val}",
                "reason": f"value {value} < min {min_val}",
            })
        if max_val is not None and value > max_val:
            violations.append({
                "metric": key,
                "value": value,
                "rule": f"max={max_val}",
                "reason": f"value {value} > max {max_val}",
            })

    return MetricsRangeResult(
        gate_pass=len(violations) == 0,
        violations=violations,
        detail={"metrics_file": str(metrics_path), "checked_keys": list(rules.keys())},
    )


def _resolve_nested(data: dict, dotted_key: str) -> object:
    """Resolve a dot-separated key path (e.g. 'summary.total_risks') in a dict."""
    parts = dotted_key.split(".")
    current: object = data
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def validate_json_file_schema(
    data_dir: Path,
    filename: str,
    required_keys: list[str],
) -> JsonFileSchemaResult:
    """Check that required keys exist in an arbitrary JSON file.

    Supports dot-notation for nested keys (e.g. 'summary.by_category').
    """
    json_path = data_dir / filename
    if not json_path.exists():
        return JsonFileSchemaResult(
            gate_pass=False,
            missing_keys=required_keys,
            detail=f"{filename} not found",
        )
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    missing = [k for k in required_keys if _resolve_nested(data, k) is None]
    return JsonFileSchemaResult(
        gate_pass=len(missing) == 0,
        missing_keys=missing,
        detail=f"checked {len(required_keys)} keys in {filename}, {len(missing)} missing",
    )


def validate_json_file_value_range(
    data_dir: Path,
    filename: str,
    rules: dict[str, dict],
) -> JsonFileValueRangeResult:
    """Check that numeric values in an arbitrary JSON file fall within specified ranges.

    Supports dot-notation for nested keys (e.g. 'summary.total_risks').
    rules: {"enterprise_value": {"min": 0}, "summary.total_risks": {"min": 0}}
    """
    json_path = data_dir / filename
    if not json_path.exists():
        return JsonFileValueRangeResult(
            gate_pass=False,
            violations=[],
            detail={"error": f"{filename} not found"},
        )
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    violations: list[dict] = []
    for key, rule in rules.items():
        value = _resolve_nested(data, key)
        if value is None:
            continue
        if not isinstance(value, (int, float)):
            continue

        min_val = rule.get("min")
        max_val = rule.get("max")
        if min_val is not None and value < min_val:
            violations.append({
                "key": key,
                "value": value,
                "rule": f"min={min_val}",
                "reason": f"value {value} < min {min_val}",
            })
        if max_val is not None and value > max_val:
            violations.append({
                "key": key,
                "value": value,
                "rule": f"max={max_val}",
                "reason": f"value {value} > max {max_val}",
            })

    return JsonFileValueRangeResult(
        gate_pass=len(violations) == 0,
        violations=violations,
        detail={"json_file": str(json_path), "checked_keys": list(rules.keys())},
    )


# ---------------------------------------------------------------------------
# Step type consistency mappings & validator
# ---------------------------------------------------------------------------

# Each mapping defines the expected types for fields flowing between steps.
# "from_step" and "to_step" are descriptive labels.
# "field_type_map" maps field names to expected Python types.
# None values are always allowed (missing data is distinct from wrong type).

STEP_TYPE_MAPPINGS: list[dict] = [
    {
        "id": "parsed_to_calculator",
        "from_step": "parsed",
        "to_step": "calculator",
        "description": "parsed/*.json bs/pl/cf numeric fields → FinancialRecord float|None",
        "field_type_map": {
            "revenue": (int, float),
            "operating_income": (int, float),
            "net_income": (int, float),
            "total_assets": (int, float),
            "equity": (int, float),
            "total_equity": (int, float),
            "operating_cf": (int, float),
            "investing_cf": (int, float),
        },
    },
    {
        "id": "calculator_to_valuate",
        "from_step": "calculator",
        "to_step": "valuate",
        "description": "metrics.json metrics_series numeric → valuation input float",
        "field_type_map": {
            "roe_percent": (int, float),
            "roa_percent": (int, float),
            "operating_margin_percent": (int, float),
            "revenue_growth_yoy_percent": (int, float),
            "profit_growth_yoy_percent": (int, float),
            "equity_ratio_percent": (int, float),
            "revenue": (int, float),
            "operating_income": (int, float),
            "net_income": (int, float),
            "operating_cf": (int, float),
            "free_cash_flow": (int, float),
        },
    },
    {
        "id": "raw_to_risk",
        "from_step": "raw",
        "to_step": "risk-analyzer",
        "description": "raw EDINET XBRL → text data str type",
        "field_type_map": {
            "content": (str,),
            "text": (str,),
            "xbrl_content": (str,),
        },
    },
]

# Integrator output has its own independent type expectations
INTEGRATOR_TYPE_MAP: dict[str, tuple] = {
    "revenue": (int, float),
    "operating_income": (int, float),
    "net_income": (int, float),
    "total_assets": (int, float),
    "equity": (int, float),
    "total_equity": (int, float),
    "net_assets": (int, float),
    "operating_cf": (int, float),
    "investing_cf": (int, float),
    "financing_cf": (int, float),
}


def validate_step_type_consistency(
    data: dict | list,
    mapping_id: str | None = None,
    custom_field_type_map: dict[str, tuple] | None = None,
) -> StepTypeConsistencyResult:
    """Validate that field values match expected types for a step connection.

    Args:
        data: The data to validate. Can be a single record (dict) or a list of records.
              For parsed data, each record may have bs/pl/cf sub-dicts.
              For metrics data, each record is a flat dict of metric values.
        mapping_id: One of the predefined mapping IDs (e.g. 'parsed_to_calculator').
        custom_field_type_map: Override field_type_map instead of using a predefined mapping.

    Returns:
        StepTypeConsistencyResult with mismatches list.
    """
    # Resolve field type map
    field_type_map: dict[str, tuple] | None = custom_field_type_map
    mapping_label = "custom"

    if field_type_map is None and mapping_id is not None:
        for mapping in STEP_TYPE_MAPPINGS:
            if mapping["id"] == mapping_id:
                field_type_map = mapping["field_type_map"]
                mapping_label = mapping_id
                break
        if field_type_map is None and mapping_id == "integrator_output":
            field_type_map = INTEGRATOR_TYPE_MAP
            mapping_label = "integrator_output"

    if field_type_map is None:
        return StepTypeConsistencyResult(
            gate_pass=False,
            mismatches=[],
            detail={"error": f"unknown mapping_id: {mapping_id}"},
        )

    # Normalize data to list of records
    records: list[dict] = []
    if isinstance(data, list):
        records = [r for r in data if isinstance(r, dict)]
    elif isinstance(data, dict):
        records = [data]

    mismatches: list[dict] = []

    for idx, record in enumerate(records):
        # Collect all fields to check: top-level + bs/pl/cf sub-dicts
        flat_fields: dict[str, object] = {}
        for key, value in record.items():
            if isinstance(value, dict) and key in ("bs", "pl", "cf"):
                for sub_key, sub_value in value.items():
                    flat_fields[sub_key] = sub_value
            elif key not in ("bs", "pl", "cf"):
                flat_fields[key] = value

        for field_name, expected_types in field_type_map.items():
            if field_name not in flat_fields:
                continue
            value = flat_fields[field_name]
            # None is always allowed (missing data)
            if value is None:
                continue
            # bool is not a valid numeric type even though bool is subclass of int
            if isinstance(value, bool):
                mismatches.append({
                    "record_index": idx,
                    "field": field_name,
                    "expected_types": [t.__name__ for t in expected_types],
                    "actual_type": type(value).__name__,
                    "actual_value": value,
                })
                continue
            if not isinstance(value, expected_types):
                mismatches.append({
                    "record_index": idx,
                    "field": field_name,
                    "expected_types": [t.__name__ for t in expected_types],
                    "actual_type": type(value).__name__,
                    "actual_value": value,
                })

    return StepTypeConsistencyResult(
        gate_pass=len(mismatches) == 0,
        mismatches=mismatches,
        detail={
            "mapping": mapping_label,
            "records_checked": len(records),
            "fields_in_map": len(field_type_map),
            "mismatch_count": len(mismatches),
        },
    )


# ---------------------------------------------------------------------------
# Gate runner
# ---------------------------------------------------------------------------


def run_all_gates(
    gates_config: list[dict],
    data_dir: Path,
) -> GateResults:
    """Execute all gates defined in the configuration.

    Each gate dict has: {"id": str, "type": str, "params": dict}
    """
    financials = load_financials(data_dir)
    periods = extract_periods(financials) if financials else []

    results: list[dict] = []

    for gate in gates_config:
        gate_id = gate["id"]
        gate_type = gate["type"]
        params = gate.get("params", {})

        if gate_type == "null_rate":
            r = validate_null_rate(periods, threshold=params.get("threshold", 0.5))
            results.append({
                "id": gate_id,
                "pass": r.gate_pass,
                "detail": {
                    "total_cells": r.total_cells,
                    "null_cells": r.null_cells,
                    "null_rate": r.null_rate,
                    "threshold": r.threshold,
                },
            })

        elif gate_type == "key_coverage":
            r = validate_key_coverage(periods, requirements=params)
            results.append({
                "id": gate_id,
                "pass": r.gate_pass,
                "detail": r.detail,
            })

        elif gate_type == "value_range":
            r = validate_value_range(periods, rules=params)
            results.append({
                "id": gate_id,
                "pass": r.gate_pass,
                "detail": {
                    "violations": r.violations,
                    "violation_count": len(r.violations),
                },
            })

        elif gate_type == "file_exists":
            r = validate_file_exists(data_dir, required_files=params.get("required_files", []))
            results.append({
                "id": gate_id,
                "pass": r.gate_pass,
                "detail": r.detail,
            })

        elif gate_type == "json_schema":
            if financials is None:
                results.append({
                    "id": gate_id,
                    "pass": False,
                    "detail": {"error": "financials.json not found"},
                })
            else:
                r = validate_json_schema(financials, required_keys=params.get("required_keys", []))
                results.append({
                    "id": gate_id,
                    "pass": r.gate_pass,
                    "detail": {
                        "missing_keys": r.missing_keys,
                        "detail": r.detail,
                    },
                })

        elif gate_type == "dir_not_empty":
            r = validate_dir_not_empty(data_dir)
            results.append({
                "id": gate_id,
                "pass": r.gate_pass,
                "detail": r.detail,
            })

        elif gate_type == "metrics_value_range":
            r = validate_metrics_value_range(data_dir, rules=params)
            results.append({
                "id": gate_id,
                "pass": r.gate_pass,
                "detail": {
                    "violations": r.violations,
                    "violation_count": len(r.violations),
                    **r.detail,
                },
            })

        elif gate_type == "json_file_schema":
            filename = params.get("file", "")
            required_keys = params.get("required_keys", [])
            r = validate_json_file_schema(data_dir, filename, required_keys)
            results.append({
                "id": gate_id,
                "pass": r.gate_pass,
                "detail": {
                    "missing_keys": r.missing_keys,
                    "detail": r.detail,
                },
            })

        elif gate_type == "json_file_value_range":
            filename = params.get("file", "")
            rules = params.get("rules", {})
            r = validate_json_file_value_range(data_dir, filename, rules)
            results.append({
                "id": gate_id,
                "pass": r.gate_pass,
                "detail": {
                    "violations": r.violations,
                    "violation_count": len(r.violations),
                    **r.detail,
                },
            })

        elif gate_type == "step_type_consistency":
            mapping_id = params.get("mapping_id")
            data_file = params.get("file", "")
            data_key = params.get("data_key")  # e.g. "period_index", "metrics_series"

            json_path = data_dir / data_file if data_file else None
            if json_path and json_path.exists():
                with json_path.open("r", encoding="utf-8") as f:
                    file_data = json.load(f)
                if data_key:
                    check_data = file_data.get(data_key, [])
                else:
                    check_data = file_data
            elif data_file:
                results.append({
                    "id": gate_id,
                    "pass": False,
                    "detail": {"error": f"{data_file} not found"},
                })
                continue
            else:
                # Use financials period_index as default
                check_data = periods

            r = validate_step_type_consistency(check_data, mapping_id=mapping_id)
            results.append({
                "id": gate_id,
                "pass": r.gate_pass,
                "detail": {
                    "mismatches": r.mismatches,
                    "mismatch_count": len(r.mismatches),
                    **r.detail,
                },
            })

        else:
            logger.warning("Unknown gate type: %s", gate_type)
            results.append({
                "id": gate_id,
                "pass": False,
                "detail": {"error": f"unknown gate type: {gate_type}"},
            })

    overall = all(g["pass"] for g in results) if results else False
    return GateResults(overall_pass=overall, gates=results)
