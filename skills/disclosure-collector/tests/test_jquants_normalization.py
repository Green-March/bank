"""J-Quants パーサー数値型正規化テスト.

task_057: string numeric → int/float 変換、エッジケース、
financial-calculator coercion との二重変換安全性を検証する。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from statements import (
    _to_float,
    _to_int,
    normalize_numeric_fields,
)

# financial-calculator の import 用パス追加
_calc_dir = str(Path(__file__).resolve().parents[2] / "financial-calculator")
if _calc_dir not in sys.path:
    sys.path.insert(0, _calc_dir)


# ===================================================================
# 1. _to_int: string → int 変換
# ===================================================================

class TestToInt:
    def test_normal_positive(self):
        assert _to_int("1000000") == 1000000

    def test_negative(self):
        assert _to_int("-500") == -500

    def test_zero(self):
        assert _to_int("0") == 0

    def test_comma_separated(self):
        assert _to_int("1,234,567") == 1234567

    def test_string_float_rejected(self):
        """小数点を含む文字列は切り捨て防止のため None."""
        assert _to_int("1000.9") is None

    def test_string_float_zero_rejected(self):
        """".0" 付き文字列も拒否."""
        assert _to_int("1000.0") is None

    def test_int_passthrough(self):
        assert _to_int(42) == 42

    def test_float_integer_to_int(self):
        """float(100.0) は整数なので int(100) に変換."""
        assert _to_int(100.0) == 100

    def test_float_fractional_rejected(self):
        """float(1000.9) は小数なので None."""
        assert _to_int(1000.9) is None

    def test_float_negative_fractional_rejected(self):
        """float(-0.5) は小数なので None."""
        assert _to_int(-0.5) is None

    def test_negative_comma(self):
        assert _to_int("-1,000") == -1000

    def test_nan_float(self):
        assert _to_int(float("nan")) is None

    def test_inf_float(self):
        assert _to_int(float("inf")) is None

    def test_neg_inf_float(self):
        assert _to_int(float("-inf")) is None


# ===================================================================
# 2. _to_float: string → float 変換
# ===================================================================

class TestToFloat:
    def test_decimal(self):
        assert _to_float("123.45") == pytest.approx(123.45)

    def test_negative_decimal(self):
        assert _to_float("-67.89") == pytest.approx(-67.89)

    def test_integer_string(self):
        assert _to_float("100") == pytest.approx(100.0)

    def test_float_passthrough(self):
        assert _to_float(3.14) == pytest.approx(3.14)

    def test_int_to_float(self):
        assert _to_float(42) == pytest.approx(42.0)

    def test_comma_separated(self):
        assert _to_float("1,234.5") == pytest.approx(1234.5)

    def test_nan_float(self):
        assert _to_float(float("nan")) is None

    def test_inf_float(self):
        assert _to_float(float("inf")) is None

    def test_neg_inf_float(self):
        assert _to_float(float("-inf")) is None

    def test_nan_string(self):
        assert _to_float("nan") is None

    def test_inf_string(self):
        assert _to_float("inf") is None


# ===================================================================
# 3. エッジケース: 無効値 → None
# ===================================================================

class TestNullValues:
    @pytest.mark.parametrize("value", ["", None, "-", "--", "N/A", "n/a", "null", "None"])
    def test_int_null_values(self, value):
        assert _to_int(value) is None

    @pytest.mark.parametrize("value", ["", None, "-", "--", "N/A", "n/a", "null", "None"])
    def test_float_null_values(self, value):
        assert _to_float(value) is None

    def test_int_bool_true(self):
        assert _to_int(True) is None

    def test_int_bool_false(self):
        assert _to_int(False) is None

    def test_float_bool_true(self):
        assert _to_float(True) is None

    def test_float_bool_false(self):
        assert _to_float(False) is None

    def test_int_invalid_string(self):
        assert _to_int("abc") is None

    def test_float_invalid_string(self):
        assert _to_float("abc") is None

    def test_int_unsupported_type(self):
        assert _to_int([1, 2]) is None

    def test_float_unsupported_type(self):
        assert _to_float([1, 2]) is None

    def test_int_whitespace_only(self):
        assert _to_int("   ") is None

    def test_float_whitespace_only(self):
        assert _to_float("   ") is None


# ===================================================================
# 4. normalize_numeric_fields: レコード全体の正規化
# ===================================================================

class TestNormalizeNumericFields:
    def test_full_record(self):
        record = {
            "DisclosedDate": "2024-11-14",
            "TypeOfDocument": "3rdQuarterConsolidated",
            "NetSales": "10000000",
            "OperatingProfit": "1000000",
            "OrdinaryProfit": "1100000",
            "Profit": "800000",
            "TotalAssets": "50000000",
            "Equity": "20000000",
            "CashFlowsFromOperatingActivities": "1200000",
            "CashFlowsFromInvestingActivities": "-500000",
            "EarningsPerShare": "123.45",
            "BookValuePerShare": "678.90",
        }
        result = normalize_numeric_fields(record)

        # 金額 → int
        assert result["NetSales"] == 10000000
        assert isinstance(result["NetSales"], int)
        assert result["OperatingProfit"] == 1000000
        assert isinstance(result["OperatingProfit"], int)
        assert result["OrdinaryProfit"] == 1100000
        assert result["Profit"] == 800000
        assert result["TotalAssets"] == 50000000
        assert result["Equity"] == 20000000
        assert result["CashFlowsFromOperatingActivities"] == 1200000
        assert result["CashFlowsFromInvestingActivities"] == -500000

        # 比率 → float
        assert result["EarningsPerShare"] == pytest.approx(123.45)
        assert isinstance(result["EarningsPerShare"], float)
        assert result["BookValuePerShare"] == pytest.approx(678.90)
        assert isinstance(result["BookValuePerShare"], float)

        # 非対象フィールドはそのまま
        assert result["DisclosedDate"] == "2024-11-14"
        assert result["TypeOfDocument"] == "3rdQuarterConsolidated"

    def test_original_not_mutated(self):
        original = {"NetSales": "1000", "EarningsPerShare": "12.3"}
        result = normalize_numeric_fields(original)
        assert original["NetSales"] == "1000"  # 元は変更されない
        assert result["NetSales"] == 1000

    def test_missing_fields_no_error(self):
        record = {"DisclosedDate": "2024-01-01"}
        result = normalize_numeric_fields(record)
        assert result == {"DisclosedDate": "2024-01-01"}

    def test_null_fields(self):
        record = {
            "NetSales": None,
            "EarningsPerShare": "",
            "OperatingProfit": "-",
        }
        result = normalize_numeric_fields(record)
        assert result["NetSales"] is None
        assert result["EarningsPerShare"] is None
        assert result["OperatingProfit"] is None

    def test_already_numeric(self):
        record = {
            "NetSales": 10000000,
            "EarningsPerShare": 123.45,
        }
        result = normalize_numeric_fields(record)
        assert result["NetSales"] == 10000000
        assert isinstance(result["NetSales"], int)
        assert result["EarningsPerShare"] == pytest.approx(123.45)
        assert isinstance(result["EarningsPerShare"], float)


# ===================================================================
# 5. financial-calculator coercion との二重変換安全性
# ===================================================================

class TestDoubleConversionSafety:
    """正規化済み int/float が FinancialRecord.__post_init__ coercion を
    通っても値が変わらないことを検証する。"""

    def test_int_survives_float_coercion(self):
        """int(10000) → _coerce_float → float(10000.0): 値保持."""
        from scripts.metrics import _coerce_float

        normalized = _to_int("10000")
        assert normalized == 10000
        assert isinstance(normalized, int)
        coerced = _coerce_float(normalized)
        assert coerced == pytest.approx(10000.0)

    def test_float_survives_float_coercion(self):
        """float(123.45) → _coerce_float → float(123.45): 値保持."""
        from scripts.metrics import _coerce_float

        normalized = _to_float("123.45")
        assert normalized == pytest.approx(123.45)
        coerced = _coerce_float(normalized)
        assert coerced == pytest.approx(123.45)

    def test_none_survives_coercion(self):
        """None → _coerce_float → None: 保持."""
        from scripts.metrics import _coerce_float

        normalized = _to_int("")
        assert normalized is None
        coerced = _coerce_float(normalized)
        assert coerced is None

    def test_negative_int_survives(self):
        """int(-500000) → _coerce_float → float(-500000.0): 値保持."""
        from scripts.metrics import _coerce_float

        normalized = _to_int("-500000")
        assert normalized == -500000
        coerced = _coerce_float(normalized)
        assert coerced == pytest.approx(-500000.0)

    def test_full_record_through_financial_record(self):
        """normalize → FinancialRecord: 値が正しく保持される."""
        from scripts.metrics import FinancialRecord

        record = {
            "NetSales": "1,000,000",
            "OperatingProfit": "100,000",
            "Profit": "-50,000",
            "TotalAssets": "5,000,000",
            "Equity": "2,000,000",
            "CashFlowsFromOperatingActivities": "120,000",
            "CashFlowsFromInvestingActivities": "-80,000",
            "EarningsPerShare": "123.45",
            "BookValuePerShare": "678.90",
        }
        normalized = normalize_numeric_fields(record)

        fr = FinancialRecord(
            ticker="9999",
            company_name="TestCo",
            fiscal_year=2024,
            period="FY",
            revenue=normalized["NetSales"],
            operating_income=normalized["OperatingProfit"],
            net_income=normalized["Profit"],
            total_assets=normalized["TotalAssets"],
            equity=normalized["Equity"],
            operating_cf=normalized["CashFlowsFromOperatingActivities"],
            investing_cf=normalized["CashFlowsFromInvestingActivities"],
            period_end="2024-03-31",
        )

        assert fr.revenue == pytest.approx(1000000.0)
        assert fr.operating_income == pytest.approx(100000.0)
        assert fr.net_income == pytest.approx(-50000.0)
        assert fr.total_assets == pytest.approx(5000000.0)
        assert fr.equity == pytest.approx(2000000.0)
        assert fr.operating_cf == pytest.approx(120000.0)
        assert fr.investing_cf == pytest.approx(-80000.0)
