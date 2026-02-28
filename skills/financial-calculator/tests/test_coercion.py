"""FinancialRecord __post_init__ 型 coercion テスト.

S38 req_048 で発覚した string numeric 通過問題への防御的 coercion を検証する。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from scripts.metrics import FinancialRecord, calculate_metrics_payload


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_record(**kwargs) -> FinancialRecord:
    """Minimal FinancialRecord factory with sensible defaults."""
    defaults = dict(
        ticker="9999",
        company_name="TestCo",
        fiscal_year=2024,
        period="FY",
        revenue=1000.0,
        operating_income=100.0,
        net_income=80.0,
        total_assets=5000.0,
        equity=2000.0,
        operating_cf=120.0,
        investing_cf=-50.0,
        period_end="2024-03-31",
    )
    defaults.update(kwargs)
    return FinancialRecord(**defaults)


# ===================================================================
# 1. String numeric → float 変換
# ===================================================================

class TestStringNumericToFloat:
    def test_simple_string_integer(self):
        rec = _make_record(revenue="1000")
        assert rec.revenue == 1000.0
        assert isinstance(rec.revenue, float)

    def test_string_float(self):
        rec = _make_record(revenue="1234.56")
        assert rec.revenue == pytest.approx(1234.56)

    def test_string_negative(self):
        rec = _make_record(net_income="-500.5")
        assert rec.net_income == pytest.approx(-500.5)

    def test_string_with_spaces(self):
        rec = _make_record(revenue=" 1000 ")
        assert rec.revenue == 1000.0


# ===================================================================
# 2. カンマ区切り対応
# ===================================================================

class TestCommaDelimited:
    def test_comma_separated_integer(self):
        rec = _make_record(revenue="1,234,567")
        assert rec.revenue == pytest.approx(1234567.0)

    def test_comma_separated_decimal(self):
        rec = _make_record(revenue="1,234.5")
        assert rec.revenue == pytest.approx(1234.5)

    def test_comma_only_thousands(self):
        rec = _make_record(total_assets="10,000,000")
        assert rec.total_assets == pytest.approx(10000000.0)


# ===================================================================
# 3. 不正値 → None 変換
# ===================================================================

class TestInvalidToNone:
    @pytest.mark.parametrize(
        "value",
        ["abc", "", "N/A", "n/a", "null", "None", "--", "-", "hello world"],
    )
    def test_invalid_strings(self, value):
        rec = _make_record(revenue=value)
        assert rec.revenue is None

    def test_unknown_type_to_none(self):
        """list, tuple 等の未対応型は None になる."""
        rec = _make_record(revenue=[1, 2, 3])
        assert rec.revenue is None


# ===================================================================
# 4. bool → None
# ===================================================================

class TestBoolToNone:
    def test_true_to_none(self):
        rec = _make_record(revenue=True)
        assert rec.revenue is None

    def test_false_to_none(self):
        rec = _make_record(revenue=False)
        assert rec.revenue is None

    def test_bool_net_income(self):
        rec = _make_record(net_income=True)
        assert rec.net_income is None


# ===================================================================
# 5. fiscal_year string → int 変換
# ===================================================================

class TestFiscalYearCoercion:
    def test_string_year(self):
        rec = _make_record(fiscal_year="2025")
        assert rec.fiscal_year == 2025
        assert isinstance(rec.fiscal_year, int)

    def test_float_year(self):
        rec = _make_record(fiscal_year=2025.0)
        assert rec.fiscal_year == 2025
        assert isinstance(rec.fiscal_year, int)

    def test_invalid_year_string(self):
        rec = _make_record(fiscal_year="abc")
        assert rec.fiscal_year is None

    def test_none_year(self):
        rec = _make_record(fiscal_year=None)
        assert rec.fiscal_year is None

    def test_bool_year(self):
        rec = _make_record(fiscal_year=True)
        assert rec.fiscal_year is None


# ===================================================================
# 6. 正しい型はそのまま通過
# ===================================================================

class TestPassthrough:
    def test_float_stays_float(self):
        rec = _make_record(revenue=1000.0)
        assert rec.revenue == 1000.0
        assert isinstance(rec.revenue, float)

    def test_int_to_float(self):
        rec = _make_record(revenue=1000)
        assert rec.revenue == 1000.0
        assert isinstance(rec.revenue, float)

    def test_none_stays_none(self):
        rec = _make_record(revenue=None)
        assert rec.revenue is None

    def test_int_fiscal_year_stays(self):
        rec = _make_record(fiscal_year=2024)
        assert rec.fiscal_year == 2024
        assert isinstance(rec.fiscal_year, int)


# ===================================================================
# 7. 全 float フィールド一括 coercion
# ===================================================================

class TestAllFloatFields:
    def test_all_string_fields(self):
        rec = FinancialRecord(
            ticker="9999",
            company_name="TestCo",
            fiscal_year="2024",
            period="FY",
            revenue="100",
            operating_income="10",
            net_income="8",
            total_assets="500",
            equity="200",
            operating_cf="12",
            investing_cf="-5",
            period_end="2024-03-31",
        )
        assert rec.fiscal_year == 2024
        assert isinstance(rec.fiscal_year, int)
        assert rec.revenue == 100.0
        assert rec.operating_income == 10.0
        assert rec.net_income == 8.0
        assert rec.total_assets == 500.0
        assert rec.equity == 200.0
        assert rec.operating_cf == 12.0
        assert rec.investing_cf == -5.0

    def test_mixed_types(self):
        """一部 string, 一部 float, 一部 None の混合入力."""
        rec = FinancialRecord(
            ticker="9999",
            company_name="TestCo",
            fiscal_year=2024,
            period="FY",
            revenue="1,000",
            operating_income=100.0,
            net_income=None,
            total_assets="N/A",
            equity=2000,
            operating_cf="abc",
            investing_cf=-50.0,
            period_end="2024-03-31",
        )
        assert rec.revenue == 1000.0
        assert rec.operating_income == 100.0
        assert rec.net_income is None
        assert rec.total_assets is None
        assert rec.equity == 2000.0
        assert rec.operating_cf is None
        assert rec.investing_cf == -50.0


# ===================================================================
# 8. frozen 属性の維持
# ===================================================================

class TestFrozenIntegrity:
    def test_still_frozen(self):
        rec = _make_record()
        with pytest.raises(AttributeError):
            rec.revenue = 999.0


# ===================================================================
# 9. integrator 出力モック → calculator --input-file 経由 E2E
# ===================================================================

class TestE2EIntegratorToCalculator:
    def test_string_numeric_via_input_file(self, tmp_path):
        """integrator が string numeric を出力した場合でも
        calculate_metrics_payload が正しく処理できることを検証."""
        integrated = {
            "ticker": "9999",
            "company_name": "TestCo",
            "annual": [
                {
                    "fiscal_year": "2024",
                    "period_end": "2024-03-31",
                    "revenue": "1,000,000",
                    "operating_income": "100,000",
                    "net_income": "80,000",
                    "total_assets": "5,000,000",
                    "equity": "2,000,000",
                    "operating_cf": "120,000",
                    "investing_cf": "-50,000",
                },
            ],
        }
        input_file = tmp_path / "integrated_financials.json"
        input_file.write_text(json.dumps(integrated), encoding="utf-8")

        payload = calculate_metrics_payload(
            ticker="9999", input_file=input_file
        )

        assert payload["source_count"] == 1
        series = payload["metrics_series"]
        assert len(series) == 1
        entry = series[0]
        assert entry["fiscal_year"] == 2024
        assert entry["revenue"] == pytest.approx(1000000.0)
        assert entry["operating_income"] == pytest.approx(100000.0)
        assert entry["net_income"] == pytest.approx(80000.0)
        assert entry["roe_percent"] is not None
        assert entry["roa_percent"] is not None

    def test_invalid_values_via_input_file(self, tmp_path):
        """integrator が不正値を含む場合でもクラッシュせず None 処理."""
        integrated = {
            "ticker": "9999",
            "company_name": "TestCo",
            "annual": [
                {
                    "fiscal_year": "2024",
                    "period_end": "2024-03-31",
                    "revenue": "N/A",
                    "operating_income": "--",
                    "net_income": "",
                    "total_assets": "abc",
                    "equity": None,
                    "operating_cf": True,
                    "investing_cf": False,
                },
            ],
        }
        input_file = tmp_path / "integrated_financials.json"
        input_file.write_text(json.dumps(integrated), encoding="utf-8")

        payload = calculate_metrics_payload(
            ticker="9999", input_file=input_file
        )

        assert payload["source_count"] == 1
        series = payload["metrics_series"]
        assert len(series) == 1
        entry = series[0]
        # All financials should be None due to invalid inputs
        assert entry["revenue"] is None
        assert entry["operating_income"] is None
        assert entry["net_income"] is None
        assert entry["roe_percent"] is None
        assert entry["roa_percent"] is None
