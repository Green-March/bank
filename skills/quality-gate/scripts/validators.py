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
    detail: dict[str, dict] = {}
    all_pass = True

    for section, req in requirements.items():
        keys = req.get("keys", [])
        min_required = req.get("min_required", 1)

        coverage: dict[str, int] = {}
        for key in keys:
            non_null = sum(
                1 for p in periods
                if p.get(section, {}).get(key) is not None
            )
            coverage[key] = non_null

        # Count how many keys are non-null in ALL periods
        total_periods = len(periods)
        all_period_keys = sum(1 for k in keys if coverage.get(k, 0) == total_periods)
        section_pass = all_period_keys >= min_required

        detail[section] = {
            "pass": section_pass,
            "all_period_keys": all_period_keys,
            "min_required": min_required,
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

    # Build a lookup: concept -> section
    concept_section: dict[str, str] = {}
    for period in periods[:1]:
        for section in ("bs", "pl", "cf"):
            for key in period.get(section, {}):
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
    periods = financials.get("period_index", []) if financials else []

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

        else:
            logger.warning("Unknown gate type: %s", gate_type)
            results.append({
                "id": gate_id,
                "pass": False,
                "detail": {"error": f"unknown gate type: {gate_type}"},
            })

    overall = all(g["pass"] for g in results) if results else False
    return GateResults(overall_pass=overall, gates=results)
