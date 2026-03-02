"""Unit tests for value_presence gate type and severity field."""

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
    ValuePresenceResult,
    run_all_gates,
    validate_value_presence,
)


# ---------------------------------------------------------------------------
# validate_value_presence unit tests
# ---------------------------------------------------------------------------


class TestValidateValuePresence:
    """Tests for validate_value_presence()."""

    def test_all_fields_non_null(self):
        """a) All fields non-null → PASS."""
        data = {
            "indicators": {
                "market_cap": 1_000_000_000,
                "shares_outstanding": 50_000_000,
            }
        }
        fields = {
            "market_cap": {"path": "indicators.market_cap", "threshold": 0.5},
            "shares_outstanding": {"path": "indicators.shares_outstanding", "threshold": 0.5},
        }
        result = validate_value_presence(data, fields)
        assert result.gate_pass is True
        assert result.field_results["market_cap"]["pass"] is True
        assert result.field_results["market_cap"]["presence_rate"] == 1.0
        assert result.field_results["shares_outstanding"]["pass"] is True
        assert result.summary["fields_checked"] == 2
        assert result.summary["fields_passed"] == 2
        assert result.summary["fields_failed"] == 0

    def test_below_threshold_fail(self):
        """b) Field is null, below threshold → FAIL."""
        data = {"indicators": {"market_cap": None}}
        fields = {
            "market_cap": {"path": "indicators.market_cap", "threshold": 0.5},
        }
        result = validate_value_presence(data, fields)
        assert result.gate_pass is False
        assert result.field_results["market_cap"]["pass"] is False
        assert result.field_results["market_cap"]["presence_rate"] == 0.0

    def test_threshold_boundary_exact(self):
        """c) Presence rate exactly at threshold → PASS (>=)."""
        data = {"values": [1, None]}  # 50% non-null
        fields = {
            "values": {"path": "values", "threshold": 0.5},
        }
        result = validate_value_presence(data, fields)
        assert result.gate_pass is True
        assert result.field_results["values"]["pass"] is True
        assert result.field_results["values"]["presence_rate"] == 0.5

    def test_mixed_fields_partial_pass(self):
        """d) Multiple fields, some pass some fail."""
        data = {
            "indicators": {
                "market_cap": 1_000_000,
                "shares_outstanding": None,
            }
        }
        fields = {
            "market_cap": {"path": "indicators.market_cap", "threshold": 0.5},
            "shares_outstanding": {"path": "indicators.shares_outstanding", "threshold": 0.5},
        }
        result = validate_value_presence(data, fields)
        assert result.gate_pass is False
        assert result.field_results["market_cap"]["pass"] is True
        assert result.field_results["shares_outstanding"]["pass"] is False
        assert result.summary["fields_passed"] == 1
        assert result.summary["fields_failed"] == 1

    def test_field_not_found_in_data(self):
        """g) Path points to non-existent key → null → presence_rate 0.0."""
        data = {"indicators": {}}
        fields = {
            "market_cap": {"path": "indicators.market_cap", "threshold": 0.5},
        }
        result = validate_value_presence(data, fields)
        assert result.gate_pass is False
        assert result.field_results["market_cap"]["presence_rate"] == 0.0
        assert result.field_results["market_cap"]["non_null_count"] == 0

    def test_list_values_presence_rate(self):
        """List with mixed null/non-null values calculates rate correctly."""
        data = {"periods": [100, None, 200, None, 300]}  # 3/5 = 0.6
        fields = {
            "periods": {"path": "periods", "threshold": 0.5},
        }
        result = validate_value_presence(data, fields)
        assert result.gate_pass is True
        assert result.field_results["periods"]["presence_rate"] == 0.6
        assert result.field_results["periods"]["non_null_count"] == 3
        assert result.field_results["periods"]["total"] == 5

    def test_list_below_threshold(self):
        """List with too many nulls fails threshold."""
        data = {"periods": [None, None, None, 100]}  # 1/4 = 0.25
        fields = {
            "periods": {"path": "periods", "threshold": 0.5},
        }
        result = validate_value_presence(data, fields)
        assert result.gate_pass is False
        assert result.field_results["periods"]["presence_rate"] == 0.25

    def test_default_threshold(self):
        """Default threshold is 0.5 when not specified."""
        data = {"value": 42}
        fields = {"value": {"path": "value"}}
        result = validate_value_presence(data, fields)
        assert result.gate_pass is True
        assert result.field_results["value"]["threshold"] == 0.5

    def test_empty_fields_spec(self):
        """Empty fields dict → pass (nothing to check, vacuously true)."""
        data = {"something": 1}
        result = validate_value_presence(data, {})
        assert result.gate_pass is True
        assert result.summary["fields_checked"] == 0


# ---------------------------------------------------------------------------
# run_all_gates integration: severity tests
# ---------------------------------------------------------------------------


class TestSeverityInRunAllGates:
    """Tests for severity field handling in run_all_gates()."""

    @pytest.fixture()
    def data_dir(self, tmp_path):
        """Create a temp data dir with harmonized_financials.json."""
        harmonized = {
            "indicators": {
                "market_cap": None,
                "shares_outstanding": None,
            },
            "annual": [],
        }
        (tmp_path / "harmonized_financials.json").write_text(
            json.dumps(harmonized), encoding="utf-8"
        )
        return tmp_path

    def test_severity_warn_does_not_affect_overall_pass(self, data_dir):
        """e) severity: warn gate fails but overall_pass remains True."""
        gates = [
            {
                "id": "file_check",
                "type": "file_exists",
                "params": {"required_files": ["harmonized_financials.json"]},
            },
            {
                "id": "indicator_presence",
                "type": "value_presence",
                "severity": "warn",
                "params": {
                    "file": "harmonized_financials.json",
                    "fields": {
                        "market_cap": {"path": "indicators.market_cap", "threshold": 0.5},
                    },
                },
            },
        ]
        result = run_all_gates(gates, data_dir)
        # file_check passes, value_presence fails but is warn → overall PASS
        assert result.overall_pass is True
        assert "indicator_presence" in result.warnings
        # The warn gate itself should report pass=False
        vp_gate = [g for g in result.gates if g["id"] == "indicator_presence"][0]
        assert vp_gate["pass"] is False
        assert vp_gate["severity"] == "warn"

    def test_severity_error_affects_overall_pass(self, data_dir):
        """f) severity: error (default) gate fails → overall_pass is False."""
        gates = [
            {
                "id": "file_check",
                "type": "file_exists",
                "params": {"required_files": ["harmonized_financials.json"]},
            },
            {
                "id": "indicator_presence",
                "type": "value_presence",
                "severity": "error",
                "params": {
                    "file": "harmonized_financials.json",
                    "fields": {
                        "market_cap": {"path": "indicators.market_cap", "threshold": 0.5},
                    },
                },
            },
        ]
        result = run_all_gates(gates, data_dir)
        assert result.overall_pass is False
        assert result.warnings == []

    def test_default_severity_is_error(self, data_dir):
        """Gates without explicit severity default to 'error'."""
        gates = [
            {
                "id": "file_check",
                "type": "file_exists",
                "params": {"required_files": ["harmonized_financials.json"]},
            },
        ]
        result = run_all_gates(gates, data_dir)
        assert result.gates[0]["severity"] == "error"

    def test_value_presence_file_not_found(self, data_dir):
        """value_presence with missing file → FAIL."""
        gates = [
            {
                "id": "missing_file_check",
                "type": "value_presence",
                "params": {
                    "file": "nonexistent.json",
                    "fields": {"x": {"path": "x", "threshold": 0.5}},
                },
            },
        ]
        result = run_all_gates(gates, data_dir)
        assert result.overall_pass is False
        assert result.gates[0]["pass"] is False

    def test_value_presence_uses_financials_fallback(self, tmp_path):
        """value_presence without file param falls back to financials.json."""
        financials = {
            "period_index": [],
            "ticker": "1234",
        }
        (tmp_path / "financials.json").write_text(
            json.dumps(financials), encoding="utf-8"
        )
        gates = [
            {
                "id": "ticker_presence",
                "type": "value_presence",
                "params": {
                    "fields": {"ticker": {"path": "ticker", "threshold": 0.5}},
                },
            },
        ]
        result = run_all_gates(gates, tmp_path)
        assert result.overall_pass is True
        assert result.gates[0]["pass"] is True

    def test_warnings_list_only_contains_warn_failures(self, data_dir):
        """warnings list contains only IDs of severity=warn gates that failed."""
        gates = [
            {
                "id": "warn_pass",
                "type": "file_exists",
                "severity": "warn",
                "params": {"required_files": ["harmonized_financials.json"]},
            },
            {
                "id": "warn_fail",
                "type": "value_presence",
                "severity": "warn",
                "params": {
                    "file": "harmonized_financials.json",
                    "fields": {
                        "market_cap": {"path": "indicators.market_cap", "threshold": 0.5},
                    },
                },
            },
            {
                "id": "error_pass",
                "type": "file_exists",
                "params": {"required_files": ["harmonized_financials.json"]},
            },
        ]
        result = run_all_gates(gates, data_dir)
        assert result.overall_pass is True
        assert result.warnings == ["warn_fail"]
