"""Unit tests for quality-gate validators."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure scripts directory is importable
_scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from validators import (
    CoverageResult,
    FileResult,
    GateResults,
    NullRateResult,
    RangeResult,
    SchemaResult,
    load_financials,
    run_all_gates,
    validate_file_exists,
    validate_json_schema,
    validate_key_coverage,
    validate_null_rate,
    validate_value_range,
)


# ---------------------------------------------------------------------------
# Sample data helpers
# ---------------------------------------------------------------------------

def _make_periods(n: int = 3, nulls: dict | None = None) -> list[dict]:
    """Create sample period data.

    Args:
        n: number of periods
        nulls: {(period_idx, section, key): None} to inject nulls
    """
    nulls = nulls or {}
    periods = []
    for i in range(n):
        period = {
            "period_end": f"2024-03-{i + 1:02d}",
            "bs": {
                "total_assets": 100_000 * (i + 1),
                "total_liabilities": 60_000 * (i + 1),
                "total_equity": 40_000 * (i + 1),
            },
            "pl": {
                "revenue": 50_000 * (i + 1),
                "operating_income": 5_000 * (i + 1),
                "net_income": 3_000 * (i + 1),
            },
            "cf": {
                "operating_cf": 8_000 * (i + 1),
                "investing_cf": -2_000 * (i + 1),
                "financing_cf": -1_000 * (i + 1),
            },
        }
        for (pi, sec, key) in nulls:
            if pi == i:
                period[sec][key] = None
        periods.append(period)
    return periods


# ---------------------------------------------------------------------------
# test_validate_null_rate
# ---------------------------------------------------------------------------

class TestValidateNullRate:
    """Tests for validate_null_rate."""

    def test_all_filled(self):
        periods = _make_periods(2)
        result = validate_null_rate(periods, threshold=0.5)
        assert result.gate_pass is True
        assert result.null_cells == 0
        assert result.null_rate == 0.0
        assert result.total_cells == 18  # 9 keys * 2 periods

    def test_below_threshold(self):
        nulls = {(0, "bs", "total_equity")}
        periods = _make_periods(2, nulls=nulls)
        result = validate_null_rate(periods, threshold=0.5)
        assert result.gate_pass is True
        assert result.null_cells == 1
        assert result.null_rate == round(1 / 18, 4)

    def test_above_threshold(self):
        # Make most cells null
        nulls = set()
        for pi in range(2):
            for sec in ("bs", "pl", "cf"):
                for key in ("total_assets", "total_liabilities", "total_equity",
                            "revenue", "operating_income", "net_income",
                            "operating_cf", "investing_cf", "financing_cf"):
                    if sec == "bs" and key in ("total_assets", "total_liabilities", "total_equity"):
                        nulls.add((pi, sec, key))
                    elif sec == "pl" and key in ("revenue", "operating_income", "net_income"):
                        nulls.add((pi, sec, key))
        periods = _make_periods(2, nulls=nulls)
        result = validate_null_rate(periods, threshold=0.3)
        assert result.gate_pass is False
        assert result.null_cells == 12  # 6 keys * 2 periods

    def test_empty_periods(self):
        result = validate_null_rate([], threshold=0.5)
        assert result.gate_pass is False
        assert result.null_rate == 1.0

    def test_exact_threshold(self):
        # 9 cells per period, 2 periods = 18 cells. 9 null = 0.5
        nulls = set()
        for key in ("total_assets", "total_liabilities", "total_equity"):
            nulls.add((0, "bs", key))
        for key in ("revenue", "operating_income", "net_income"):
            nulls.add((0, "pl", key))
        for key in ("operating_cf", "investing_cf", "financing_cf"):
            nulls.add((0, "cf", key))
        periods = _make_periods(2, nulls=nulls)
        result = validate_null_rate(periods, threshold=0.5)
        assert result.gate_pass is True
        assert result.null_rate == 0.5


# ---------------------------------------------------------------------------
# test_validate_key_coverage
# ---------------------------------------------------------------------------

class TestValidateKeyCoverage:
    """Tests for validate_key_coverage."""

    def test_all_non_null(self):
        periods = _make_periods(3)
        requirements = {
            "bs": {"keys": ["total_assets", "total_liabilities", "total_equity"], "min_required": 2},
            "pl": {"keys": ["revenue", "operating_income", "net_income"], "min_required": 2},
        }
        result = validate_key_coverage(periods, requirements)
        assert result.gate_pass is True
        assert result.detail["bs"]["pass"] is True
        assert result.detail["pl"]["pass"] is True

    def test_partial_null(self):
        nulls = {(1, "bs", "total_assets")}
        periods = _make_periods(3, nulls=nulls)
        requirements = {
            "bs": {"keys": ["total_assets", "total_liabilities", "total_equity"], "min_required": 2},
        }
        result = validate_key_coverage(periods, requirements)
        # total_assets is non-null in only 2 of 3 periods, so all_period_keys=2
        assert result.gate_pass is True
        assert result.detail["bs"]["all_period_keys"] == 2

    def test_all_null_fails(self):
        nulls = set()
        for pi in range(3):
            for key in ("total_assets", "total_liabilities", "total_equity"):
                nulls.add((pi, "bs", key))
        periods = _make_periods(3, nulls=nulls)
        requirements = {
            "bs": {"keys": ["total_assets", "total_liabilities", "total_equity"], "min_required": 1},
        }
        result = validate_key_coverage(periods, requirements)
        assert result.gate_pass is False
        assert result.detail["bs"]["all_period_keys"] == 0

    def test_min_required_exact(self):
        nulls = {(0, "pl", "net_income")}
        periods = _make_periods(2, nulls=nulls)
        requirements = {
            "pl": {"keys": ["revenue", "operating_income", "net_income"], "min_required": 2},
        }
        result = validate_key_coverage(periods, requirements)
        # revenue and operating_income are non-null in ALL periods = 2 keys
        assert result.gate_pass is True
        assert result.detail["pl"]["all_period_keys"] == 2


# ---------------------------------------------------------------------------
# test_validate_value_range
# ---------------------------------------------------------------------------

class TestValidateValueRange:
    """Tests for validate_value_range."""

    def test_all_in_range(self):
        periods = _make_periods(2)
        rules = {"total_assets": {"min": 0}, "revenue": {"min": 0}}
        result = validate_value_range(periods, rules)
        assert result.gate_pass is True
        assert len(result.violations) == 0

    def test_negative_assets(self):
        periods = _make_periods(1)
        periods[0]["bs"]["total_assets"] = -100
        rules = {"total_assets": {"min": 0}}
        result = validate_value_range(periods, rules)
        assert result.gate_pass is False
        assert len(result.violations) == 1
        assert result.violations[0]["concept"] == "total_assets"
        assert result.violations[0]["value"] == -100

    def test_exceeds_max(self):
        periods = _make_periods(1)
        periods[0]["pl"]["revenue"] = 1e16
        rules = {"revenue": {"min": 0, "max": 1e15}}
        result = validate_value_range(periods, rules)
        assert result.gate_pass is False
        assert len(result.violations) == 1
        assert "max" in result.violations[0]["rule"]

    def test_null_values_skipped(self):
        periods = _make_periods(1, nulls={(0, "bs", "total_assets")})
        rules = {"total_assets": {"min": 0}}
        result = validate_value_range(periods, rules)
        assert result.gate_pass is True
        assert len(result.violations) == 0

    def test_unknown_concept_ignored(self):
        periods = _make_periods(1)
        rules = {"nonexistent_concept": {"min": 0}}
        result = validate_value_range(periods, rules)
        assert result.gate_pass is True


# ---------------------------------------------------------------------------
# test_validate_file_exists
# ---------------------------------------------------------------------------

class TestValidateFileExists:
    """Tests for validate_file_exists."""

    def test_file_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            (p / "financials.json").write_text('{"data": 1}')
            result = validate_file_exists(p, ["financials.json"])
            assert result.gate_pass is True
            assert result.detail["financials.json"]["exists"] is True
            assert result.detail["financials.json"]["size"] > 0

    def test_file_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            result = validate_file_exists(p, ["financials.json"])
            assert result.gate_pass is False
            assert result.detail["financials.json"]["exists"] is False

    def test_empty_file_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            (p / "financials.json").write_text("")
            result = validate_file_exists(p, ["financials.json"])
            assert result.gate_pass is False
            assert result.detail["financials.json"]["size"] == 0

    def test_multiple_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            (p / "financials.json").write_text('{"data": 1}')
            (p / "report.md").write_text("# Report")
            result = validate_file_exists(p, ["financials.json", "report.md"])
            assert result.gate_pass is True

    def test_partial_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            (p / "financials.json").write_text('{"data": 1}')
            result = validate_file_exists(p, ["financials.json", "missing.txt"])
            assert result.gate_pass is False


# ---------------------------------------------------------------------------
# test_validate_json_schema
# ---------------------------------------------------------------------------

class TestValidateJsonSchema:
    """Tests for validate_json_schema."""

    def test_all_keys_present(self):
        data = {"company_name": "Test", "ticker": "1234", "period_index": []}
        result = validate_json_schema(data, ["company_name", "ticker", "period_index"])
        assert result.gate_pass is True
        assert result.missing_keys == []

    def test_missing_keys(self):
        data = {"company_name": "Test"}
        result = validate_json_schema(data, ["company_name", "ticker", "period_index"])
        assert result.gate_pass is False
        assert "ticker" in result.missing_keys
        assert "period_index" in result.missing_keys

    def test_empty_required(self):
        data = {"foo": "bar"}
        result = validate_json_schema(data, [])
        assert result.gate_pass is True


# ---------------------------------------------------------------------------
# test_run_all_gates (integration)
# ---------------------------------------------------------------------------

class TestRunAllGates:
    """Integration tests for run_all_gates."""

    def _setup_data_dir(self, tmpdir: str, periods: list[dict] | None = None) -> Path:
        p = Path(tmpdir)
        if periods is None:
            periods = _make_periods(3)
        financials = {
            "company_name": "Test Corp",
            "ticker": "9999",
            "period_index": periods,
        }
        (p / "financials.json").write_text(
            json.dumps(financials, ensure_ascii=False, indent=2)
        )
        return p

    def test_all_gates_pass(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = self._setup_data_dir(tmpdir)
            gates_config = [
                {"id": "null_rate", "type": "null_rate", "params": {"threshold": 0.5}},
                {
                    "id": "key_coverage",
                    "type": "key_coverage",
                    "params": {
                        "bs": {"keys": ["total_assets", "total_equity"], "min_required": 2},
                    },
                },
                {
                    "id": "value_range",
                    "type": "value_range",
                    "params": {"total_assets": {"min": 0}},
                },
                {
                    "id": "file_check",
                    "type": "file_exists",
                    "params": {"required_files": ["financials.json"]},
                },
                {
                    "id": "schema_check",
                    "type": "json_schema",
                    "params": {"required_keys": ["company_name", "ticker", "period_index"]},
                },
            ]
            result = run_all_gates(gates_config, data_dir)
            assert result.overall_pass is True
            assert len(result.gates) == 5
            assert all(g["pass"] for g in result.gates)

    def test_one_gate_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = self._setup_data_dir(tmpdir)
            gates_config = [
                {"id": "null_rate", "type": "null_rate", "params": {"threshold": 0.5}},
                {
                    "id": "value_range",
                    "type": "value_range",
                    "params": {"total_assets": {"min": 999_999_999}},
                },
            ]
            result = run_all_gates(gates_config, data_dir)
            assert result.overall_pass is False
            passed = [g for g in result.gates if g["pass"]]
            failed = [g for g in result.gates if not g["pass"]]
            assert len(passed) == 1
            assert len(failed) == 1

    def test_unknown_gate_type(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = self._setup_data_dir(tmpdir)
            gates_config = [
                {"id": "mystery", "type": "not_a_real_gate", "params": {}},
            ]
            result = run_all_gates(gates_config, data_dir)
            assert result.overall_pass is False
            assert "unknown gate type" in result.gates[0]["detail"]["error"]

    def test_no_financials(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            # No financials.json written
            gates_config = [
                {
                    "id": "schema_check",
                    "type": "json_schema",
                    "params": {"required_keys": ["ticker"]},
                },
            ]
            result = run_all_gates(gates_config, data_dir)
            assert result.overall_pass is False

    def test_default_gates_yaml(self):
        """Run with the bundled default_gates.yaml to verify it parses correctly."""
        import yaml

        gates_path = Path(__file__).resolve().parent.parent / "references" / "default_gates.yaml"
        if not gates_path.exists():
            pytest.skip("default_gates.yaml not found")

        with gates_path.open("r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        gates_list = config.get("gates", [])
        assert len(gates_list) >= 3

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = self._setup_data_dir(tmpdir)
            result = run_all_gates(gates_list, data_dir)
            assert isinstance(result.overall_pass, bool)
            assert len(result.gates) == len(gates_list)


# ---------------------------------------------------------------------------
# test_gate_results_json_format
# ---------------------------------------------------------------------------

class TestGateResultsJsonFormat:
    """Verify the output JSON structure matches specification."""

    def test_output_structure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            periods = _make_periods(2)
            financials = {
                "company_name": "Format Test",
                "ticker": "0000",
                "period_index": periods,
            }
            (data_dir / "financials.json").write_text(
                json.dumps(financials, ensure_ascii=False, indent=2)
            )
            gates_config = [
                {"id": "null_rate", "type": "null_rate", "params": {"threshold": 0.5}},
            ]
            result = run_all_gates(gates_config, data_dir)

            # Verify GateResults structure
            assert isinstance(result, GateResults)
            assert isinstance(result.overall_pass, bool)
            assert isinstance(result.gates, list)

            for gate in result.gates:
                assert "id" in gate
                assert "pass" in gate
                assert "detail" in gate
                assert isinstance(gate["pass"], bool)
                assert isinstance(gate["detail"], dict)

    def test_serializable_to_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            periods = _make_periods(1)
            financials = {"period_index": periods}
            (data_dir / "financials.json").write_text(json.dumps(financials))

            gates_config = [
                {"id": "null_rate", "type": "null_rate", "params": {"threshold": 0.5}},
                {"id": "file_check", "type": "file_exists", "params": {"required_files": ["financials.json"]}},
            ]
            result = run_all_gates(gates_config, data_dir)

            output = {
                "overall_pass": result.overall_pass,
                "gates": result.gates,
            }
            serialized = json.dumps(output, ensure_ascii=False, indent=2)
            parsed = json.loads(serialized)
            assert parsed["overall_pass"] == result.overall_pass
            assert len(parsed["gates"]) == 2


# ---------------------------------------------------------------------------
# test_load_financials
# ---------------------------------------------------------------------------

class TestLoadFinancials:
    """Tests for load_financials helper."""

    def test_load_valid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir)
            data = {"ticker": "1234", "period_index": []}
            (p / "financials.json").write_text(json.dumps(data))
            result = load_financials(p)
            assert result is not None
            assert result["ticker"] == "1234"

    def test_load_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = load_financials(Path(tmpdir))
            assert result is None
