"""Unit tests for step_type_consistency gate."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

_scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from validators import (
    INTEGRATOR_TYPE_MAP,
    STEP_TYPE_MAPPINGS,
    StepTypeConsistencyResult,
    run_all_gates,
    validate_step_type_consistency,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parsed_record(*, overrides: dict | None = None) -> dict:
    """Create a sample parsed financial record with bs/pl/cf sub-dicts."""
    record = {
        "period_end": "2024-03-31",
        "fiscal_year": 2024,
        "bs": {
            "total_assets": 1_000_000.0,
            "total_equity": 400_000.0,
            "equity": 400_000.0,
        },
        "pl": {
            "revenue": 500_000.0,
            "operating_income": 50_000.0,
            "net_income": 30_000.0,
        },
        "cf": {
            "operating_cf": 80_000.0,
            "investing_cf": -20_000.0,
        },
    }
    if overrides:
        for key, value in overrides.items():
            if "." in key:
                section, field = key.split(".", 1)
                record[section][field] = value
            else:
                record[key] = value
    return record


def _metrics_record(*, overrides: dict | None = None) -> dict:
    """Create a sample metrics series entry."""
    record = {
        "fiscal_year": 2024,
        "period": "FY",
        "revenue": 500_000.0,
        "operating_income": 50_000.0,
        "net_income": 30_000.0,
        "roe_percent": 7.5,
        "roa_percent": 3.0,
        "operating_margin_percent": 10.0,
        "revenue_growth_yoy_percent": 5.2,
        "profit_growth_yoy_percent": 8.1,
        "equity_ratio_percent": 40.0,
        "operating_cf": 80_000.0,
        "free_cash_flow": 60_000.0,
    }
    if overrides:
        record.update(overrides)
    return record


def _risk_record(*, overrides: dict | None = None) -> dict:
    """Create a sample raw XBRL-like text record."""
    record = {
        "content": "<xbrl>...</xbrl>",
        "text": "リスク情報のテキスト",
        "xbrl_content": "<xbrl>full content</xbrl>",
    }
    if overrides:
        record.update(overrides)
    return record


# ---------------------------------------------------------------------------
# Test: parsed → calculator connection
# ---------------------------------------------------------------------------

class TestParsedToCalculator:
    """Tests for parsed → calculator type consistency."""

    def test_all_float_pass(self):
        """All numeric fields are float → pass."""
        data = [_parsed_record()]
        result = validate_step_type_consistency(data, mapping_id="parsed_to_calculator")
        assert result.gate_pass is True
        assert len(result.mismatches) == 0
        assert result.detail["mapping"] == "parsed_to_calculator"

    def test_int_values_pass(self):
        """int values are accepted (int is valid numeric type)."""
        data = [_parsed_record(overrides={"bs.total_assets": 1_000_000, "pl.revenue": 500_000})]
        result = validate_step_type_consistency(data, mapping_id="parsed_to_calculator")
        assert result.gate_pass is True

    def test_string_numeric_fail(self):
        """String numeric '1000' must be detected as type mismatch."""
        data = [_parsed_record(overrides={"pl.revenue": "500000", "bs.total_assets": "1000000"})]
        result = validate_step_type_consistency(data, mapping_id="parsed_to_calculator")
        assert result.gate_pass is False
        assert len(result.mismatches) == 2
        fields = {m["field"] for m in result.mismatches}
        assert "revenue" in fields
        assert "total_assets" in fields
        for m in result.mismatches:
            assert m["actual_type"] == "str"
            assert "int" in m["expected_types"] or "float" in m["expected_types"]

    def test_none_values_pass(self):
        """None values are allowed (missing data, not type mismatch)."""
        data = [_parsed_record(overrides={
            "pl.revenue": None,
            "bs.total_assets": None,
            "cf.operating_cf": None,
        })]
        result = validate_step_type_consistency(data, mapping_id="parsed_to_calculator")
        assert result.gate_pass is True
        assert len(result.mismatches) == 0

    def test_bool_value_fail(self):
        """Boolean values should be rejected even though bool is subclass of int."""
        data = [_parsed_record(overrides={"pl.revenue": True})]
        result = validate_step_type_consistency(data, mapping_id="parsed_to_calculator")
        assert result.gate_pass is False
        assert result.mismatches[0]["field"] == "revenue"
        assert result.mismatches[0]["actual_type"] == "bool"

    def test_multiple_records(self):
        """Multiple records: mismatch in second record is detected."""
        data = [
            _parsed_record(),
            _parsed_record(overrides={"pl.net_income": "30000"}),
        ]
        result = validate_step_type_consistency(data, mapping_id="parsed_to_calculator")
        assert result.gate_pass is False
        assert len(result.mismatches) == 1
        assert result.mismatches[0]["record_index"] == 1
        assert result.mismatches[0]["field"] == "net_income"


# ---------------------------------------------------------------------------
# Test: calculator → valuate connection
# ---------------------------------------------------------------------------

class TestCalculatorToValuate:
    """Tests for calculator → valuate type consistency."""

    def test_all_float_pass(self):
        """All metrics are float → pass."""
        data = [_metrics_record()]
        result = validate_step_type_consistency(data, mapping_id="calculator_to_valuate")
        assert result.gate_pass is True
        assert result.detail["records_checked"] == 1

    def test_string_metric_fail(self):
        """String metric value must fail."""
        data = [_metrics_record(overrides={"roe_percent": "7.5"})]
        result = validate_step_type_consistency(data, mapping_id="calculator_to_valuate")
        assert result.gate_pass is False
        assert result.mismatches[0]["field"] == "roe_percent"

    def test_none_metric_pass(self):
        """None metric values are acceptable."""
        data = [_metrics_record(overrides={
            "roe_percent": None,
            "revenue_growth_yoy_percent": None,
        })]
        result = validate_step_type_consistency(data, mapping_id="calculator_to_valuate")
        assert result.gate_pass is True


# ---------------------------------------------------------------------------
# Test: raw → risk-analyzer connection
# ---------------------------------------------------------------------------

class TestRawToRisk:
    """Tests for raw → risk-analyzer type consistency."""

    def test_all_str_pass(self):
        """All text fields are str → pass."""
        data = [_risk_record()]
        result = validate_step_type_consistency(data, mapping_id="raw_to_risk")
        assert result.gate_pass is True

    def test_numeric_content_fail(self):
        """Numeric content field must fail (expected str)."""
        data = [_risk_record(overrides={"content": 12345})]
        result = validate_step_type_consistency(data, mapping_id="raw_to_risk")
        assert result.gate_pass is False
        assert result.mismatches[0]["field"] == "content"
        assert result.mismatches[0]["actual_type"] == "int"

    def test_none_text_pass(self):
        """None text fields are acceptable."""
        data = [_risk_record(overrides={"text": None})]
        result = validate_step_type_consistency(data, mapping_id="raw_to_risk")
        assert result.gate_pass is True


# ---------------------------------------------------------------------------
# Test: integrator output independent validation
# ---------------------------------------------------------------------------

class TestIntegratorOutput:
    """Tests for integrator output type validation."""

    def test_integrator_float_pass(self):
        """Integrator output with all float values passes."""
        data = {
            "period_end": "2024-03-31",
            "revenue": 500_000.0,
            "operating_income": 50_000.0,
            "net_income": 30_000.0,
            "total_assets": 1_000_000.0,
            "equity": 400_000.0,
            "total_equity": 400_000.0,
            "net_assets": 400_000.0,
            "operating_cf": 80_000.0,
            "investing_cf": -20_000.0,
            "financing_cf": -10_000.0,
        }
        result = validate_step_type_consistency(data, mapping_id="integrator_output")
        assert result.gate_pass is True

    def test_integrator_string_numeric_fail(self):
        """Integrator output with string numeric values fails."""
        data = {
            "revenue": "500000",
            "total_assets": 1_000_000.0,
        }
        result = validate_step_type_consistency(data, mapping_id="integrator_output")
        assert result.gate_pass is False
        assert len(result.mismatches) == 1
        assert result.mismatches[0]["field"] == "revenue"

    def test_integrator_mixed_types(self):
        """Integrator output with mixed valid types (int + float) passes."""
        data = {
            "revenue": 500_000,
            "total_assets": 1_000_000.0,
            "equity": 400_000,
        }
        result = validate_step_type_consistency(data, mapping_id="integrator_output")
        assert result.gate_pass is True


# ---------------------------------------------------------------------------
# Test: edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge case tests for validate_step_type_consistency."""

    def test_unknown_mapping_id(self):
        """Unknown mapping_id returns failure."""
        result = validate_step_type_consistency({}, mapping_id="nonexistent")
        assert result.gate_pass is False
        assert "error" in result.detail

    def test_empty_data_list(self):
        """Empty data list passes (no records to check)."""
        result = validate_step_type_consistency([], mapping_id="parsed_to_calculator")
        assert result.gate_pass is True
        assert result.detail["records_checked"] == 0

    def test_single_dict_input(self):
        """Single dict (not wrapped in list) is handled correctly."""
        data = _parsed_record()
        result = validate_step_type_consistency(data, mapping_id="parsed_to_calculator")
        assert result.gate_pass is True
        assert result.detail["records_checked"] == 1

    def test_custom_field_type_map(self):
        """Custom field type map overrides predefined mappings."""
        data = [{"custom_field": "hello"}]
        custom_map = {"custom_field": (int, float)}
        result = validate_step_type_consistency(data, custom_field_type_map=custom_map)
        assert result.gate_pass is False
        assert result.mismatches[0]["field"] == "custom_field"

    def test_custom_field_type_map_pass(self):
        """Custom field type map with matching type passes."""
        data = [{"custom_field": 42}]
        custom_map = {"custom_field": (int,)}
        result = validate_step_type_consistency(data, custom_field_type_map=custom_map)
        assert result.gate_pass is True

    def test_field_not_in_record_skipped(self):
        """Fields in mapping but not in record are simply skipped."""
        data = [{"some_other_field": "value"}]
        result = validate_step_type_consistency(data, mapping_id="parsed_to_calculator")
        assert result.gate_pass is True
        assert len(result.mismatches) == 0

    def test_mismatch_detail_structure(self):
        """Verify mismatch detail contains all required fields."""
        data = [_parsed_record(overrides={"pl.revenue": "bad"})]
        result = validate_step_type_consistency(data, mapping_id="parsed_to_calculator")
        m = result.mismatches[0]
        assert "record_index" in m
        assert "field" in m
        assert "expected_types" in m
        assert "actual_type" in m
        assert "actual_value" in m


# ---------------------------------------------------------------------------
# Test: run_all_gates integration with step_type_consistency
# ---------------------------------------------------------------------------

class TestRunAllGatesStepTypeConsistency:
    """Integration tests: step_type_consistency gate via run_all_gates."""

    def test_via_run_all_gates_financials(self):
        """step_type_consistency using financials.json period_index."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            financials = {
                "company_name": "Test Corp",
                "ticker": "9999",
                "period_index": [_parsed_record()],
            }
            (data_dir / "financials.json").write_text(
                json.dumps(financials, ensure_ascii=False, indent=2)
            )
            gates_config = [{
                "id": "step_type_check",
                "type": "step_type_consistency",
                "params": {"mapping_id": "parsed_to_calculator"},
            }]
            result = run_all_gates(gates_config, data_dir)
            assert result.overall_pass is True

    def test_via_run_all_gates_metrics_file(self):
        """step_type_consistency using a separate metrics.json file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            # Need financials.json (even empty) for run_all_gates
            (data_dir / "financials.json").write_text('{"period_index": []}')
            metrics = {
                "ticker": "9999",
                "metrics_series": [_metrics_record()],
                "latest_snapshot": _metrics_record(),
            }
            (data_dir / "metrics.json").write_text(
                json.dumps(metrics, ensure_ascii=False, indent=2)
            )
            gates_config = [{
                "id": "metrics_type_check",
                "type": "step_type_consistency",
                "params": {
                    "mapping_id": "calculator_to_valuate",
                    "file": "metrics.json",
                    "data_key": "metrics_series",
                },
            }]
            result = run_all_gates(gates_config, data_dir)
            assert result.overall_pass is True

    def test_via_run_all_gates_missing_file(self):
        """step_type_consistency with missing data file fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            (data_dir / "financials.json").write_text('{"period_index": []}')
            gates_config = [{
                "id": "type_check",
                "type": "step_type_consistency",
                "params": {
                    "mapping_id": "parsed_to_calculator",
                    "file": "nonexistent.json",
                },
            }]
            result = run_all_gates(gates_config, data_dir)
            assert result.overall_pass is False
            assert "not found" in result.gates[0]["detail"]["error"]

    def test_via_run_all_gates_with_string_mismatch(self):
        """step_type_consistency detects string numerics via run_all_gates."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            bad_record = _parsed_record(overrides={"pl.revenue": "500000"})
            financials = {
                "period_index": [bad_record],
            }
            (data_dir / "financials.json").write_text(
                json.dumps(financials, ensure_ascii=False, indent=2)
            )
            gates_config = [{
                "id": "type_check",
                "type": "step_type_consistency",
                "params": {"mapping_id": "parsed_to_calculator"},
            }]
            result = run_all_gates(gates_config, data_dir)
            assert result.overall_pass is False
            assert result.gates[0]["detail"]["mismatch_count"] >= 1
