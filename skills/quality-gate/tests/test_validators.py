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
    DirResult,
    FileResult,
    GateResults,
    MetricsRangeResult,
    NullRateResult,
    RangeResult,
    SchemaResult,
    ValuationReasonablenessResult,
    extract_periods,
    load_financials,
    run_all_gates,
    validate_dir_not_empty,
    validate_file_exists,
    validate_json_schema,
    validate_key_coverage,
    validate_metrics_value_range,
    validate_null_rate,
    validate_value_range,
    validate_valuation_reasonableness,
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


# ---------------------------------------------------------------------------
# test_extract_periods (fallback logic)
# ---------------------------------------------------------------------------

class TestExtractPeriods:
    """Tests for extract_periods fallback from documents[].periods."""

    def test_period_index_present(self):
        periods = _make_periods(2)
        financials = {"period_index": periods}
        result = extract_periods(financials)
        assert len(result) == 2
        assert result[0]["period_end"] == "2024-03-01"

    def test_period_index_empty_fallback_to_documents(self):
        """period_index is empty; should fall back to documents[].periods."""
        doc_periods = _make_periods(2)
        financials = {
            "period_index": [],
            "documents": [
                {"doc_id": "E00001", "periods": doc_periods},
            ],
        }
        result = extract_periods(financials)
        assert len(result) == 2
        assert result[0]["bs"]["total_assets"] == 100_000

    def test_period_index_missing_fallback_to_documents(self):
        """period_index key missing entirely; should fall back."""
        doc_periods = _make_periods(1)
        financials = {
            "documents": [
                {"doc_id": "E00001", "periods": doc_periods},
            ],
        }
        result = extract_periods(financials)
        assert len(result) == 1

    def test_multiple_documents_merged(self):
        """Periods from multiple documents should be merged."""
        p1 = _make_periods(1)
        p2 = _make_periods(1)
        p2[0]["period_end"] = "2024-09-30"
        financials = {
            "period_index": [],
            "documents": [
                {"doc_id": "E00001", "periods": p1},
                {"doc_id": "E00002", "periods": p2},
            ],
        }
        result = extract_periods(financials)
        assert len(result) == 2

    def test_no_periods_anywhere(self):
        """No period_index and no documents → empty list."""
        financials = {"company_name": "Test"}
        result = extract_periods(financials)
        assert result == []


# ---------------------------------------------------------------------------
# test_extract_periods integration with run_all_gates
# ---------------------------------------------------------------------------

class TestRunAllGatesFallback:
    """Integration: run_all_gates with period_index empty, data in documents."""

    def test_fallback_periods_used_by_gates(self):
        """Gates should receive fallback periods and produce valid results."""
        doc_periods = _make_periods(2)
        financials = {
            "company_name": "Fallback Corp",
            "ticker": "8888",
            "period_index": [],
            "documents": [
                {"doc_id": "E99999", "periods": doc_periods},
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            (data_dir / "financials.json").write_text(
                json.dumps(financials, ensure_ascii=False, indent=2)
            )
            gates_config = [
                {"id": "null_rate", "type": "null_rate", "params": {"threshold": 0.5}},
                {
                    "id": "key_coverage",
                    "type": "key_coverage",
                    "params": {
                        "bs": {"keys": ["total_assets", "total_equity"], "min_required": 2},
                    },
                },
            ]
            result = run_all_gates(gates_config, data_dir)
            assert result.overall_pass is True
            assert all(g["pass"] for g in result.gates)


# ---------------------------------------------------------------------------
# test_validate_value_range: full period CF scan
# ---------------------------------------------------------------------------

class TestValueRangeAllPeriods:
    """validate_value_range must scan ALL periods for concept_section."""

    def test_cf_only_in_later_periods(self):
        """CF keys present only from period 2 onward must still be validated."""
        periods = [
            {
                "period_end": "2024-06-30",
                "bs": {"total_assets": 100_000},
                "pl": {"revenue": 50_000},
                # No CF in Q1
            },
            {
                "period_end": "2024-09-30",
                "bs": {"total_assets": 200_000},
                "pl": {"revenue": 100_000},
                "cf": {"operating_cf": 8_000, "investing_cf": -2_000, "financing_cf": -1_000},
            },
            {
                "period_end": "2025-03-31",
                "bs": {"total_assets": 300_000},
                "pl": {"revenue": 150_000},
                "cf": {"operating_cf": -999, "investing_cf": -3_000, "financing_cf": -2_000},
            },
        ]
        rules = {"operating_cf": {"min": 0}}
        result = validate_value_range(periods, rules)
        # operating_cf = -999 in period 3 should be caught as a violation
        assert result.gate_pass is False
        assert len(result.violations) == 1
        assert result.violations[0]["concept"] == "operating_cf"
        assert result.violations[0]["value"] == -999

    def test_cf_in_all_periods_validated(self):
        """CF present in multiple periods should all be range-checked."""
        periods = _make_periods(3)
        # All operating_cf values are positive (8000, 16000, 24000)
        rules = {"operating_cf": {"min": 0}}
        result = validate_value_range(periods, rules)
        assert result.gate_pass is True
        assert len(result.violations) == 0

    def test_cf_violation_in_middle_period(self):
        """Violation in a non-first period must be detected."""
        periods = _make_periods(3)
        periods[1]["cf"]["operating_cf"] = -500
        rules = {"operating_cf": {"min": 0}}
        result = validate_value_range(periods, rules)
        assert result.gate_pass is False
        assert any(v["value"] == -500 for v in result.violations)


# ---------------------------------------------------------------------------
# test_validate_key_coverage: empty periods guard
# ---------------------------------------------------------------------------

class TestKeyCoverageEmptyPeriods:
    """validate_key_coverage must fail when periods list is empty."""

    def test_empty_periods_fails(self):
        requirements = {
            "bs": {"keys": ["total_assets", "total_equity"], "min_required": 1},
            "pl": {"keys": ["revenue"], "min_required": 1},
        }
        result = validate_key_coverage([], requirements)
        assert result.gate_pass is False
        assert result.detail["bs"]["pass"] is False
        assert result.detail["bs"]["all_period_keys"] == 0
        assert result.detail["pl"]["pass"] is False


# ---------------------------------------------------------------------------
# test_validate_key_coverage: stub period handling
# ---------------------------------------------------------------------------

class TestKeyCoverageStubPeriods:
    """validate_key_coverage must exclude stub periods from relevant count."""

    def test_key_coverage_stub_period_excluded(self):
        """Stub period (bs all null) + 3 normal periods -> all_period_keys=3."""
        stub = {
            "period_end": "2021-01-31",
            "bs": {"total_assets": None, "total_liabilities": None, "total_equity": None},
            "pl": {"revenue": None, "operating_income": None, "net_income": None},
            "cf": {},
        }
        normal = _make_periods(3)
        periods = [stub] + normal
        requirements = {
            "bs": {"keys": ["total_assets", "total_liabilities", "total_equity"], "min_required": 3},
        }
        result = validate_key_coverage(periods, requirements)
        assert result.gate_pass is True
        assert result.detail["bs"]["all_period_keys"] == 3
        assert result.detail["bs"]["total_periods"] == 3

    def test_key_coverage_all_stub_periods_fails(self):
        """All periods are stubs -> section_pass = False."""
        stubs = [
            {
                "period_end": f"2021-0{i+1}-31",
                "bs": {"total_assets": None, "total_liabilities": None, "total_equity": None},
            }
            for i in range(3)
        ]
        requirements = {
            "bs": {"keys": ["total_assets", "total_liabilities", "total_equity"], "min_required": 1},
        }
        result = validate_key_coverage(stubs, requirements)
        assert result.gate_pass is False
        assert result.detail["bs"]["pass"] is False
        assert result.detail["bs"]["all_period_keys"] == 0
        assert result.detail["bs"]["total_periods"] == 0

    def test_key_coverage_mixed_sections_different_relevant_counts(self):
        """bs has 4 relevant periods, cf has 3 relevant periods."""
        periods = [
            {
                "period_end": "2021-01-31",
                "bs": {"total_assets": 1000, "net_assets": 500},
                "cf": {},  # stub for cf
            },
            *[
                {
                    "period_end": f"2024-03-{i+1:02d}",
                    "bs": {"total_assets": 100_000 * (i+1), "net_assets": 40_000 * (i+1)},
                    "cf": {"operating_cf": 8_000 * (i+1), "investing_cf": -2_000 * (i+1)},
                }
                for i in range(3)
            ],
        ]
        requirements = {
            "bs": {"keys": ["total_assets", "net_assets"], "min_required": 2},
            "cf": {"keys": ["operating_cf", "investing_cf"], "min_required": 2},
        }
        result = validate_key_coverage(periods, requirements)
        assert result.gate_pass is True
        assert result.detail["bs"]["total_periods"] == 4
        assert result.detail["cf"]["total_periods"] == 3
        assert result.detail["bs"]["all_period_keys"] == 2
        assert result.detail["cf"]["all_period_keys"] == 2

    def test_key_coverage_detail_includes_total_periods(self):
        """detail must include total_periods field."""
        periods = _make_periods(2)
        requirements = {
            "bs": {"keys": ["total_assets"], "min_required": 1},
            "pl": {"keys": ["revenue"], "min_required": 1},
        }
        result = validate_key_coverage(periods, requirements)
        for section in ("bs", "pl"):
            assert "total_periods" in result.detail[section]
            assert result.detail[section]["total_periods"] == 2


# ---------------------------------------------------------------------------
# test_validate_dir_not_empty
# ---------------------------------------------------------------------------

class TestValidateDirNotEmpty:
    """Tests for validate_dir_not_empty."""

    def test_dir_with_files(self, tmp_path):
        """Directory with files passes."""
        (tmp_path / "file1.json").write_text("{}")
        result = validate_dir_not_empty(tmp_path)
        assert result.gate_pass is True
        assert result.detail["exists"] is True
        assert result.detail["file_count"] >= 1

    def test_empty_dir(self, tmp_path):
        """Empty directory fails."""
        result = validate_dir_not_empty(tmp_path)
        assert result.gate_pass is False
        assert result.detail["exists"] is True
        assert result.detail["file_count"] == 0

    def test_nonexistent_dir(self, tmp_path):
        """Non-existent directory fails."""
        result = validate_dir_not_empty(tmp_path / "no_such_dir")
        assert result.gate_pass is False
        assert result.detail["exists"] is False

    def test_multiple_files(self, tmp_path):
        """Directory with multiple files passes."""
        for i in range(3):
            (tmp_path / f"file{i}.json").write_text("{}")
        result = validate_dir_not_empty(tmp_path)
        assert result.gate_pass is True
        assert result.detail["file_count"] == 3


# ---------------------------------------------------------------------------
# test_validate_metrics_value_range
# ---------------------------------------------------------------------------

class TestValidateMetricsValueRange:
    """Tests for validate_metrics_value_range."""

    def _write_metrics(self, tmp_path, snapshot):
        """Write a metrics.json file with the given latest_snapshot."""
        data = {
            "ticker": "TEST",
            "company_name": "テスト株式会社",
            "generated_at": "2026-01-01T00:00:00",
            "source_count": 1,
            "metrics_series": [],
            "latest_snapshot": snapshot,
        }
        (tmp_path / "metrics.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )

    def test_all_within_range(self, tmp_path):
        """All metrics within range passes."""
        self._write_metrics(tmp_path, {
            "roe_percent": 10.0,
            "roa_percent": 5.0,
            "operating_margin_percent": 8.0,
        })
        rules = {
            "roe_percent": {"min": -100, "max": 200},
            "roa_percent": {"min": -50, "max": 100},
            "operating_margin_percent": {"min": -100, "max": 100},
        }
        result = validate_metrics_value_range(tmp_path, rules)
        assert result.gate_pass is True
        assert len(result.violations) == 0

    def test_violation_below_min(self, tmp_path):
        """Value below min triggers violation."""
        self._write_metrics(tmp_path, {"roe_percent": -150.0})
        rules = {"roe_percent": {"min": -100, "max": 200}}
        result = validate_metrics_value_range(tmp_path, rules)
        assert result.gate_pass is False
        assert len(result.violations) == 1
        assert result.violations[0]["metric"] == "roe_percent"

    def test_violation_above_max(self, tmp_path):
        """Value above max triggers violation."""
        self._write_metrics(tmp_path, {"roa_percent": 150.0})
        rules = {"roa_percent": {"min": -50, "max": 100}}
        result = validate_metrics_value_range(tmp_path, rules)
        assert result.gate_pass is False
        assert len(result.violations) == 1

    def test_null_metric_ignored(self, tmp_path):
        """Null metric values are skipped (not violations)."""
        self._write_metrics(tmp_path, {"roe_percent": None, "roa_percent": 5.0})
        rules = {
            "roe_percent": {"min": -100, "max": 200},
            "roa_percent": {"min": -50, "max": 100},
        }
        result = validate_metrics_value_range(tmp_path, rules)
        assert result.gate_pass is True

    def test_missing_metrics_file(self, tmp_path):
        """Missing metrics.json fails."""
        rules = {"roe_percent": {"min": -100, "max": 200}}
        result = validate_metrics_value_range(tmp_path, rules)
        assert result.gate_pass is False

    def test_empty_rules(self, tmp_path):
        """Empty rules with existing file passes."""
        self._write_metrics(tmp_path, {"roe_percent": 10.0})
        result = validate_metrics_value_range(tmp_path, {})
        assert result.gate_pass is True


# ---------------------------------------------------------------------------
# test_run_all_gates with new gate types
# ---------------------------------------------------------------------------

class TestRunAllGatesNewTypes:
    """Tests for dir_not_empty and metrics_value_range in run_all_gates."""

    def test_dir_not_empty_gate(self, tmp_path):
        """dir_not_empty gate via run_all_gates."""
        (tmp_path / "some_file.json").write_text("{}")
        gates_config = [{"id": "dir_check", "type": "dir_not_empty"}]
        result = run_all_gates(gates_config, tmp_path)
        assert result.overall_pass is True

    def test_dir_not_empty_gate_fail(self, tmp_path):
        """dir_not_empty fails for empty directory."""
        gates_config = [{"id": "dir_check", "type": "dir_not_empty"}]
        result = run_all_gates(gates_config, tmp_path)
        assert result.overall_pass is False

    def test_metrics_value_range_gate(self, tmp_path):
        """metrics_value_range gate via run_all_gates."""
        data = {
            "ticker": "TEST",
            "company_name": "テスト",
            "generated_at": "2026-01-01",
            "source_count": 1,
            "metrics_series": [],
            "latest_snapshot": {"roe_percent": 10.0},
        }
        (tmp_path / "metrics.json").write_text(json.dumps(data))
        gates_config = [{
            "id": "metrics_range",
            "type": "metrics_value_range",
            "params": {"roe_percent": {"min": -100, "max": 200}},
        }]
        result = run_all_gates(gates_config, tmp_path)
        assert result.overall_pass is True


# ---------------------------------------------------------------------------
# ValuationReasonableness tests
# ---------------------------------------------------------------------------


class TestValuationReasonableness:
    """Tests for validate_valuation_reasonableness."""

    @staticmethod
    def _write_relative(tmp_path, data):
        (tmp_path / "relative.json").write_text(json.dumps(data))

    def test_per_above_max_warns(self, tmp_path):
        """PER=61.06 exceeds default max=50 -> violation."""
        self._write_relative(tmp_path, {"valuation_type": "relative", "per": 61.06, "pbr": 3.0, "ev_ebitda": 20.0})
        result = validate_valuation_reasonableness(tmp_path)
        assert result.gate_pass is False
        assert any(v["metric"] == "per" for v in result.violations)

    def test_per_in_range_passes(self, tmp_path):
        """PER=15.0 within default range -> pass."""
        self._write_relative(tmp_path, {"valuation_type": "relative", "per": 15.0, "pbr": 2.0, "ev_ebitda": 10.0})
        result = validate_valuation_reasonableness(tmp_path)
        assert result.gate_pass is True
        assert len(result.violations) == 0

    def test_pbr_above_max_warns(self, tmp_path):
        """PBR=6.01 exceeds default max=5.0 -> violation."""
        self._write_relative(tmp_path, {"valuation_type": "relative", "per": 10.0, "pbr": 6.01, "ev_ebitda": 10.0})
        result = validate_valuation_reasonableness(tmp_path)
        assert result.gate_pass is False
        assert any(v["metric"] == "pbr" for v in result.violations)

    def test_pbr_in_range_passes(self, tmp_path):
        """PBR=3.0 within default range -> pass."""
        self._write_relative(tmp_path, {"valuation_type": "relative", "per": 10.0, "pbr": 3.0, "ev_ebitda": 10.0})
        result = validate_valuation_reasonableness(tmp_path)
        assert result.gate_pass is True

    def test_ev_ebitda_above_max_warns(self, tmp_path):
        """EV/EBITDA=45.0 exceeds default max=40 -> violation."""
        self._write_relative(tmp_path, {"valuation_type": "relative", "per": 10.0, "pbr": 2.0, "ev_ebitda": 45.0})
        result = validate_valuation_reasonableness(tmp_path)
        assert result.gate_pass is False
        assert any(v["metric"] == "ev_ebitda" for v in result.violations)

    def test_null_values_skipped(self, tmp_path):
        """Null metric values are skipped (not violations)."""
        self._write_relative(tmp_path, {"valuation_type": "relative", "per": None, "pbr": None, "ev_ebitda": None})
        result = validate_valuation_reasonableness(tmp_path)
        assert result.gate_pass is True
        assert len(result.violations) == 0
        assert len(result.detail["checked_metrics"]) == 0

    def test_custom_thresholds_override(self, tmp_path):
        """Custom per_max=100 -> PER=61.06 passes."""
        self._write_relative(tmp_path, {"valuation_type": "relative", "per": 61.06, "pbr": 3.0, "ev_ebitda": 10.0})
        result = validate_valuation_reasonableness(tmp_path, thresholds={"per": {"min": 0, "max": 100}})
        assert result.gate_pass is True
        assert len(result.violations) == 0

    def test_missing_file_fails(self, tmp_path):
        """Missing relative.json -> fail."""
        result = validate_valuation_reasonableness(tmp_path)
        assert result.gate_pass is False
        assert "error" in result.detail

    def test_multiple_violations(self, tmp_path):
        """Multiple metrics out of range -> multiple violations."""
        self._write_relative(tmp_path, {"valuation_type": "relative", "per": 61.06, "pbr": 6.01, "ev_ebitda": 45.0})
        result = validate_valuation_reasonableness(tmp_path)
        assert result.gate_pass is False
        assert len(result.violations) == 3

    def test_custom_filename(self, tmp_path):
        """Custom filename parameter works."""
        (tmp_path / "custom_valuation.json").write_text(json.dumps({"per": 10.0, "pbr": 2.0, "ev_ebitda": 5.0}))
        result = validate_valuation_reasonableness(tmp_path, filename="custom_valuation.json")
        assert result.gate_pass is True


class TestValuationReasonablenessProfiles:
    """Tests for thresholds_profile parameter."""

    @staticmethod
    def _write_relative(tmp_path, data):
        (tmp_path / "relative.json").write_text(json.dumps(data))

    def test_default_profile_same_as_before(self, tmp_path):
        """default profile uses PER 0-50, PBR 0-5.0, EV-EBITDA 0-40."""
        self._write_relative(tmp_path, {"per": 51.0, "pbr": 2.0, "ev_ebitda": 10.0})
        result = validate_valuation_reasonableness(tmp_path, thresholds_profile="default")
        assert result.gate_pass is False
        assert any(v["metric"] == "per" for v in result.violations)

    def test_growth_profile_per_relaxed(self, tmp_path):
        """growth profile: PER=61.06 passes (max=100)."""
        self._write_relative(tmp_path, {"per": 61.06, "pbr": 3.0, "ev_ebitda": 20.0})
        result = validate_valuation_reasonableness(tmp_path, thresholds_profile="growth")
        assert result.gate_pass is True
        assert len(result.violations) == 0

    def test_growth_profile_ev_ebitda_relaxed(self, tmp_path):
        """growth profile: EV/EBITDA=60 passes (max=80)."""
        self._write_relative(tmp_path, {"per": 30.0, "pbr": 5.0, "ev_ebitda": 60.0})
        result = validate_valuation_reasonableness(tmp_path, thresholds_profile="growth")
        assert result.gate_pass is True

    def test_value_profile_stricter(self, tmp_path):
        """value profile: PER=35 fails (max=30)."""
        self._write_relative(tmp_path, {"per": 35.0, "pbr": 2.0, "ev_ebitda": 10.0})
        result = validate_valuation_reasonableness(tmp_path, thresholds_profile="value")
        assert result.gate_pass is False
        assert any(v["metric"] == "per" for v in result.violations)

    def test_financial_profile_pbr_relaxed(self, tmp_path):
        """financial profile: PBR=8.0 passes (max=10.0)."""
        self._write_relative(tmp_path, {"per": 20.0, "pbr": 8.0, "ev_ebitda": 15.0})
        result = validate_valuation_reasonableness(tmp_path, thresholds_profile="financial")
        assert result.gate_pass is True
        assert len(result.violations) == 0

    def test_unknown_profile_falls_back_to_default(self, tmp_path):
        """Unknown profile name falls back to default thresholds."""
        self._write_relative(tmp_path, {"per": 51.0, "pbr": 2.0, "ev_ebitda": 10.0})
        result = validate_valuation_reasonableness(tmp_path, thresholds_profile="nonexistent")
        assert result.gate_pass is False
        assert any(v["metric"] == "per" for v in result.violations)

    def test_profile_with_threshold_override(self, tmp_path):
        """Profile base + per-metric override: growth base with custom PER max=50."""
        self._write_relative(tmp_path, {"per": 61.06, "pbr": 5.0, "ev_ebitda": 20.0})
        result = validate_valuation_reasonableness(
            tmp_path,
            thresholds={"per": {"max": 50}},
            thresholds_profile="growth",
        )
        assert result.gate_pass is False
        assert any(v["metric"] == "per" for v in result.violations)

    def test_profile_via_run_all_gates(self, tmp_path):
        """Profile parameter works through run_all_gates."""
        self._write_relative(tmp_path, {"per": 61.06, "pbr": 3.0, "ev_ebitda": 20.0})
        gates_config = [{
            "id": "val_reasonableness",
            "type": "valuation_reasonableness",
            "severity": "warn",
            "params": {"file": "relative.json", "profile": "growth"},
        }]
        result = run_all_gates(gates_config, tmp_path)
        assert result.overall_pass is True
        assert len(result.warnings) == 0


class TestValuationReasonablenessRunAllGates:
    """Tests for valuation_reasonableness gate type in run_all_gates."""

    @staticmethod
    def _write_relative(tmp_path, data):
        (tmp_path / "relative.json").write_text(json.dumps(data))

    def test_warn_severity_does_not_block_overall(self, tmp_path):
        """valuation_reasonableness with severity:warn doesn't block overall_pass."""
        self._write_relative(tmp_path, {"valuation_type": "relative", "per": 61.06, "pbr": 6.01, "ev_ebitda": 45.0})
        gates_config = [{
            "id": "val_reasonableness",
            "type": "valuation_reasonableness",
            "severity": "warn",
            "params": {"file": "relative.json"},
        }]
        result = run_all_gates(gates_config, tmp_path)
        assert result.overall_pass is True
        assert "val_reasonableness" in result.warnings

    def test_pass_case_via_run_all_gates(self, tmp_path):
        """Normal values pass via run_all_gates."""
        self._write_relative(tmp_path, {"valuation_type": "relative", "per": 15.0, "pbr": 2.0, "ev_ebitda": 10.0})
        gates_config = [{
            "id": "val_reasonableness",
            "type": "valuation_reasonableness",
            "severity": "warn",
            "params": {"file": "relative.json"},
        }]
        result = run_all_gates(gates_config, tmp_path)
        assert result.overall_pass is True
        assert len(result.warnings) == 0


class TestTickerOverrides:
    """Tests for per-ticker severity override in run_all_gates."""

    def _write_dcf(self, tmp_path, data):
        with (tmp_path / "dcf.json").open("w") as f:
            json.dump(data, f)

    def test_ticker_override_applies_warn(self, tmp_path):
        """ticker='2780' overrides valuation_range severity from error to warn."""
        self._write_dcf(tmp_path, {"enterprise_value": -100, "equity_value": -50, "assumptions": {}})
        gates_config = [{
            "id": "valuation_range",
            "type": "json_file_value_range",
            "severity": "error",
            "params": {
                "file": "dcf.json",
                "rules": {"enterprise_value": {"min": 0}, "equity_value": {"min": 0}},
            },
        }]
        ticker_overrides = {
            "2780": {
                "valuation_range": {"severity": "warn"},
            },
        }
        result = run_all_gates(gates_config, tmp_path, ticker="2780", ticker_overrides=ticker_overrides)
        # Violations exist but severity is warn, so overall_pass is True
        assert result.overall_pass is True
        assert "valuation_range" in result.warnings

    def test_ticker_not_in_overrides_uses_default(self, tmp_path):
        """ticker='9999' (not in overrides) keeps default severity=error."""
        self._write_dcf(tmp_path, {"enterprise_value": -100, "equity_value": -50, "assumptions": {}})
        gates_config = [{
            "id": "valuation_range",
            "type": "json_file_value_range",
            "severity": "error",
            "params": {
                "file": "dcf.json",
                "rules": {"enterprise_value": {"min": 0}, "equity_value": {"min": 0}},
            },
        }]
        ticker_overrides = {
            "2780": {
                "valuation_range": {"severity": "warn"},
            },
        }
        result = run_all_gates(gates_config, tmp_path, ticker="9999", ticker_overrides=ticker_overrides)
        assert result.overall_pass is False
        assert "valuation_range" not in result.warnings

    def test_ticker_none_no_override(self, tmp_path):
        """ticker=None means no overrides applied (default behavior)."""
        self._write_dcf(tmp_path, {"enterprise_value": -100, "equity_value": -50, "assumptions": {}})
        gates_config = [{
            "id": "valuation_range",
            "type": "json_file_value_range",
            "severity": "error",
            "params": {
                "file": "dcf.json",
                "rules": {"enterprise_value": {"min": 0}, "equity_value": {"min": 0}},
            },
        }]
        ticker_overrides = {
            "2780": {
                "valuation_range": {"severity": "warn"},
            },
        }
        result = run_all_gates(gates_config, tmp_path, ticker=None, ticker_overrides=ticker_overrides)
        assert result.overall_pass is False
        assert "valuation_range" not in result.warnings

    def test_ticker_override_no_overrides_dict(self, tmp_path):
        """ticker specified but ticker_overrides is None → no crash, default behavior."""
        self._write_dcf(tmp_path, {"enterprise_value": 100, "equity_value": 50, "assumptions": {}})
        gates_config = [{
            "id": "valuation_range",
            "type": "json_file_value_range",
            "severity": "error",
            "params": {
                "file": "dcf.json",
                "rules": {"enterprise_value": {"min": 0}, "equity_value": {"min": 0}},
            },
        }]
        result = run_all_gates(gates_config, tmp_path, ticker="2780", ticker_overrides=None)
        assert result.overall_pass is True

    def test_ticker_override_only_severity_allowed(self, tmp_path):
        """Only 'severity' key from ticker_overrides is applied."""
        self._write_dcf(tmp_path, {"enterprise_value": -100, "equity_value": -50, "assumptions": {}})
        gates_config = [{
            "id": "valuation_range",
            "type": "json_file_value_range",
            "severity": "error",
            "params": {
                "file": "dcf.json",
                "rules": {"enterprise_value": {"min": 0}, "equity_value": {"min": 0}},
            },
        }]
        ticker_overrides = {
            "2780": {
                "valuation_range": {"severity": "warn"},
            },
        }
        result = run_all_gates(gates_config, tmp_path, ticker="2780", ticker_overrides=ticker_overrides)
        # severity=warn is allowed, so violations don't block overall_pass
        assert result.overall_pass is True
        vr = [g for g in result.gates if g["id"] == "valuation_range"][0]
        assert vr["severity"] == "warn"

    def test_ticker_override_invalid_key_ignored(self, tmp_path):
        """Disallowed keys (e.g. params, gate_type) in ticker_overrides are ignored."""
        self._write_dcf(tmp_path, {"enterprise_value": -100, "equity_value": -50, "assumptions": {}})
        gates_config = [{
            "id": "valuation_range",
            "type": "json_file_value_range",
            "severity": "error",
            "params": {
                "file": "dcf.json",
                "rules": {"enterprise_value": {"min": 0}, "equity_value": {"min": 0}},
            },
        }]
        ticker_overrides = {
            "2780": {
                "valuation_range": {"severity": "warn", "params": {"file": "evil.json"}, "type": "null_rate"},
            },
        }
        result = run_all_gates(gates_config, tmp_path, ticker="2780", ticker_overrides=ticker_overrides)
        # severity=warn applied, but params/type overrides ignored
        vr = [g for g in result.gates if g["id"] == "valuation_range"][0]
        assert vr["severity"] == "warn"
        # Violations still found from dcf.json (not evil.json), confirming params was not overridden
        assert vr["detail"]["violation_count"] > 0

    def test_ticker_override_invalid_key_warning_logged(self, tmp_path, caplog):
        """Disallowed keys produce a warning log message."""
        import logging
        self._write_dcf(tmp_path, {"enterprise_value": 100, "equity_value": 50, "assumptions": {}})
        gates_config = [{
            "id": "valuation_range",
            "type": "json_file_value_range",
            "severity": "error",
            "params": {
                "file": "dcf.json",
                "rules": {"enterprise_value": {"min": 0}},
            },
        }]
        ticker_overrides = {
            "2780": {
                "valuation_range": {"severity": "warn", "params": {"file": "x.json"}},
            },
        }
        with caplog.at_level(logging.WARNING, logger="validators"):
            run_all_gates(gates_config, tmp_path, ticker="2780", ticker_overrides=ticker_overrides)
        assert any("ignoring disallowed keys" in msg for msg in caplog.messages)
