"""pytest unit tests for metrics.py – 主要6指標 + null/期間不足エッジケース."""

from __future__ import annotations

import pytest

from scripts.metrics import (
    FinancialRecord,
    _build_metrics_series,
    _growth_percent,
    _ratio_percent,
    _round_num,
    _sum_nullable,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_record(
    fiscal_year: int | None = 2024,
    *,
    revenue: float | None = 1000.0,
    operating_income: float | None = 100.0,
    net_income: float | None = 80.0,
    total_assets: float | None = 5000.0,
    equity: float | None = 2000.0,
    operating_cf: float | None = 120.0,
    investing_cf: float | None = -50.0,
    period: str | None = "FY",
    period_end: str | None = "2024-03-31",
    ticker: str = "7685",
) -> FinancialRecord:
    return FinancialRecord(
        ticker=ticker,
        company_name="TestCo",
        fiscal_year=fiscal_year,
        period=period,
        revenue=revenue,
        operating_income=operating_income,
        net_income=net_income,
        total_assets=total_assets,
        equity=equity,
        operating_cf=operating_cf,
        investing_cf=investing_cf,
        period_end=period_end,
    )


# ===================================================================
# 1. ROE  (net_income / equity * 100)
# ===================================================================

class TestROE:
    def test_normal(self):
        assert _ratio_percent(80.0, 2000.0) == pytest.approx(4.0)

    def test_numerator_none(self):
        assert _ratio_percent(None, 2000.0) is None

    def test_denominator_none(self):
        assert _ratio_percent(80.0, None) is None

    def test_denominator_zero(self):
        assert _ratio_percent(80.0, 0) is None

    def test_both_none(self):
        assert _ratio_percent(None, None) is None

    def test_negative_net_income(self):
        assert _ratio_percent(-50.0, 2000.0) == pytest.approx(-2.5)

    def test_negative_equity(self):
        result = _ratio_percent(80.0, -400.0)
        assert result == pytest.approx(-20.0)


# ===================================================================
# 2. ROA  (net_income / total_assets * 100)
# ===================================================================

class TestROA:
    def test_normal(self):
        assert _ratio_percent(80.0, 5000.0) == pytest.approx(1.6)

    def test_numerator_none(self):
        assert _ratio_percent(None, 5000.0) is None

    def test_denominator_none(self):
        assert _ratio_percent(80.0, None) is None

    def test_denominator_zero(self):
        assert _ratio_percent(80.0, 0) is None


# ===================================================================
# 3. 営業利益率  (operating_income / revenue * 100)
# ===================================================================

class TestOperatingMargin:
    def test_normal(self):
        assert _ratio_percent(100.0, 1000.0) == pytest.approx(10.0)

    def test_revenue_none(self):
        assert _ratio_percent(100.0, None) is None

    def test_operating_income_none(self):
        assert _ratio_percent(None, 1000.0) is None

    def test_revenue_zero(self):
        assert _ratio_percent(100.0, 0) is None

    def test_loss(self):
        assert _ratio_percent(-30.0, 1000.0) == pytest.approx(-3.0)


# ===================================================================
# 4. 売上成長率 YoY  ((current - previous) / |previous| * 100)
# ===================================================================

class TestRevenueGrowthYoY:
    def test_positive_growth(self):
        assert _growth_percent(1200.0, 1000.0) == pytest.approx(20.0)

    def test_negative_growth(self):
        assert _growth_percent(800.0, 1000.0) == pytest.approx(-20.0)

    def test_current_none(self):
        assert _growth_percent(None, 1000.0) is None

    def test_previous_none(self):
        """期間不足: 前期データがない場合は None."""
        assert _growth_percent(1200.0, None) is None

    def test_previous_zero(self):
        assert _growth_percent(1200.0, 0) is None

    def test_both_none(self):
        assert _growth_percent(None, None) is None

    def test_negative_previous(self):
        """前期が負の場合 abs(previous) で割る."""
        result = _growth_percent(100.0, -200.0)
        assert result == pytest.approx((100.0 - (-200.0)) / 200.0 * 100.0)

    def test_no_change(self):
        assert _growth_percent(1000.0, 1000.0) == pytest.approx(0.0)


# ===================================================================
# 5. 利益成長率 YoY  ((current - previous) / |previous| * 100)
# ===================================================================

class TestProfitGrowthYoY:
    def test_positive_growth(self):
        assert _growth_percent(120.0, 80.0) == pytest.approx(50.0)

    def test_negative_growth(self):
        assert _growth_percent(60.0, 80.0) == pytest.approx(-25.0)

    def test_current_none(self):
        assert _growth_percent(None, 80.0) is None

    def test_previous_none(self):
        """期間不足: 前期データなし."""
        assert _growth_percent(120.0, None) is None

    def test_previous_zero(self):
        assert _growth_percent(120.0, 0) is None

    def test_turnaround_to_profit(self):
        """赤字→黒字転換."""
        result = _growth_percent(50.0, -100.0)
        assert result == pytest.approx(150.0)


# ===================================================================
# 6. 自己資本比率  (equity / total_assets * 100)
# ===================================================================

class TestEquityRatio:
    def test_normal(self):
        assert _ratio_percent(2000.0, 5000.0) == pytest.approx(40.0)

    def test_equity_none(self):
        assert _ratio_percent(None, 5000.0) is None

    def test_total_assets_none(self):
        assert _ratio_percent(2000.0, None) is None

    def test_total_assets_zero(self):
        assert _ratio_percent(2000.0, 0) is None

    def test_high_ratio(self):
        assert _ratio_percent(9000.0, 10000.0) == pytest.approx(90.0)


# ===================================================================
# _build_metrics_series 統合テスト
# ===================================================================

class TestBuildMetricsSeries:
    def test_single_record_no_previous(self):
        """1期分のみ: YoY 成長率は None になる."""
        records = [_make_record(2024)]
        series = _build_metrics_series(records)

        assert len(series) == 1
        entry = series[0]
        assert entry["fiscal_year"] == 2024
        assert entry["roe_percent"] == pytest.approx(4.0)
        assert entry["roa_percent"] == pytest.approx(1.6)
        assert entry["operating_margin_percent"] == pytest.approx(10.0)
        assert entry["equity_ratio_percent"] == pytest.approx(40.0)
        # 前期なし → YoY は None
        assert entry["revenue_growth_yoy_percent"] is None
        assert entry["profit_growth_yoy_percent"] is None

    def test_two_records_yoy(self):
        """2期分: YoY 成長率が算出される."""
        r1 = _make_record(2023, revenue=1000.0, net_income=80.0, period_end="2023-03-31")
        r2 = _make_record(2024, revenue=1200.0, net_income=100.0, period_end="2024-03-31")
        series = _build_metrics_series([r1, r2])

        assert len(series) == 2
        first, second = series[0], series[1]

        # 1期目: YoY なし
        assert first["revenue_growth_yoy_percent"] is None
        assert first["profit_growth_yoy_percent"] is None

        # 2期目: YoY あり
        assert second["revenue_growth_yoy_percent"] == pytest.approx(20.0)
        assert second["profit_growth_yoy_percent"] == pytest.approx(25.0)

    def test_empty_records(self):
        series = _build_metrics_series([])
        assert series == []

    def test_all_none_financials(self):
        """全フィールド None のレコード: 全指標 None."""
        record = _make_record(
            2024,
            revenue=None,
            operating_income=None,
            net_income=None,
            total_assets=None,
            equity=None,
            operating_cf=None,
            investing_cf=None,
        )
        series = _build_metrics_series([record])

        assert len(series) == 1
        entry = series[0]
        assert entry["roe_percent"] is None
        assert entry["roa_percent"] is None
        assert entry["operating_margin_percent"] is None
        assert entry["revenue_growth_yoy_percent"] is None
        assert entry["profit_growth_yoy_percent"] is None
        assert entry["equity_ratio_percent"] is None
        assert entry["free_cash_flow"] is None

    def test_partial_none_second_record(self):
        """2期目の net_income が None → 利益成長率は None, 売上成長率は算出."""
        r1 = _make_record(2023, revenue=1000.0, net_income=80.0, period_end="2023-03-31")
        r2 = _make_record(2024, revenue=1200.0, net_income=None, period_end="2024-03-31")
        series = _build_metrics_series([r1, r2])

        second = series[1]
        assert second["revenue_growth_yoy_percent"] == pytest.approx(20.0)
        assert second["profit_growth_yoy_percent"] is None
        assert second["roe_percent"] is None

    def test_free_cash_flow(self):
        record = _make_record(2024, operating_cf=120.0, investing_cf=-50.0)
        series = _build_metrics_series([record])
        assert series[0]["free_cash_flow"] == pytest.approx(70.0)

    def test_free_cash_flow_both_none(self):
        record = _make_record(2024, operating_cf=None, investing_cf=None)
        series = _build_metrics_series([record])
        assert series[0]["free_cash_flow"] is None

    def test_free_cash_flow_one_none(self):
        record = _make_record(2024, operating_cf=120.0, investing_cf=None)
        series = _build_metrics_series([record])
        assert series[0]["free_cash_flow"] == pytest.approx(120.0)

    def test_period_defaults_to_na(self):
        record = _make_record(2024, period=None)
        series = _build_metrics_series([record])
        assert series[0]["period"] == "N/A"


# ===================================================================
# ヘルパー関数
# ===================================================================

class TestRoundNum:
    def test_normal(self):
        assert _round_num(3.14159) == pytest.approx(3.14)

    def test_none(self):
        assert _round_num(None) is None

    def test_integer(self):
        assert _round_num(5.0) == pytest.approx(5.0)


class TestSumNullable:
    def test_both_values(self):
        assert _sum_nullable(100.0, -30.0) == pytest.approx(70.0)

    def test_first_none(self):
        assert _sum_nullable(None, -30.0) == pytest.approx(-30.0)

    def test_second_none(self):
        assert _sum_nullable(100.0, None) == pytest.approx(100.0)

    def test_both_none(self):
        assert _sum_nullable(None, None) is None
