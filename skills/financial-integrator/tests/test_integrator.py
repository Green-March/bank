"""financial-integrator ユニットテスト

対象関数: determine_fiscal_year, determine_quarter, classify_period, merge_entry
"""

import sys
from pathlib import Path

import pytest

# integrator.py をインポートできるようにパスを追加
_scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from integrator import (
    classify_period,
    determine_fiscal_year,
    determine_quarter,
    merge_entry,
)


# ==================================================================
# determine_fiscal_year
# ==================================================================

class TestDetermineFiscalYear:
    """fye_month を基準に period_end から会計年度を決定する。"""

    # --- fye_month=3 ---
    def test_fye3_march_end(self):
        assert determine_fiscal_year("2024-03-31", 3) == 2024

    def test_fye3_june_end(self):
        assert determine_fiscal_year("2024-06-30", 3) == 2025

    def test_fye3_december_end(self):
        assert determine_fiscal_year("2024-12-31", 3) == 2025

    # --- fye_month=12 ---
    def test_fye12_december_end(self):
        assert determine_fiscal_year("2024-12-31", 12) == 2024

    def test_fye12_march_end(self):
        assert determine_fiscal_year("2024-03-31", 12) == 2024

    def test_fye12_june_end(self):
        assert determine_fiscal_year("2024-06-30", 12) == 2024

    # --- fye_month=12 境界ケース ---
    # fye=12 では全月 (1-12) が <= 12 なので fiscal_year = calendar year
    def test_fye12_january_same_year(self):
        # 1月: month(1) <= fye(12) → calendar year = fiscal year
        assert determine_fiscal_year("2025-01-31", 12) == 2025

    def test_fye12_november_same_year(self):
        assert determine_fiscal_year("2024-11-30", 12) == 2024

    def test_fye12_all_months_equal_calendar_year(self):
        # fye=12 の特性: 全月で fiscal_year == calendar year
        for m in range(1, 13):
            period_end = f"2024-{m:02d}-28"
            assert determine_fiscal_year(period_end, 12) == 2024, (
                f"fye=12, month={m}: 期待=2024, 実際={determine_fiscal_year(period_end, 12)}"
            )

    def test_fye12_year_boundary(self):
        # 年をまたぐ: 2024-12 → FY2024, 2025-01 → FY2025
        assert determine_fiscal_year("2024-12-31", 12) == 2024
        assert determine_fiscal_year("2025-01-15", 12) == 2025

    # --- fye_month=9 (変則決算) 境界ケース ---
    def test_fye9_september_end(self):
        assert determine_fiscal_year("2024-09-30", 9) == 2024

    def test_fye9_october_next_fy(self):
        # 10月: month(10) > fye(9) → year + 1
        assert determine_fiscal_year("2024-10-31", 9) == 2025

    def test_fye9_boundary_exact(self):
        # 9月 == fye_month → 当年度
        assert determine_fiscal_year("2023-09-30", 9) == 2023

    # --- fye_month=6 (変則決算) 境界ケース ---
    def test_fye6_june_end(self):
        assert determine_fiscal_year("2024-06-30", 6) == 2024

    def test_fye6_july_next_fy(self):
        # 7月: month(7) > fye(6) → year + 1
        assert determine_fiscal_year("2024-07-31", 6) == 2025

    def test_fye6_january(self):
        # 1月: month(1) <= fye(6) → 当年度
        assert determine_fiscal_year("2024-01-31", 6) == 2024


# ==================================================================
# determine_quarter
# ==================================================================

class TestDetermineQuarter:
    """fye_month から動的に四半期ラベルを決定する。"""

    # --- fye_month=3 ---
    def test_fye3_q1(self):
        assert determine_quarter("2024-06-30", 3) == "Q1"

    def test_fye3_q2(self):
        assert determine_quarter("2024-09-30", 3) == "Q2"

    def test_fye3_q3(self):
        assert determine_quarter("2024-12-31", 3) == "Q3"

    def test_fye3_fy(self):
        assert determine_quarter("2025-03-31", 3) == "FY"

    # --- fye_month=12 ---
    def test_fye12_q1(self):
        assert determine_quarter("2024-03-31", 12) == "Q1"

    def test_fye12_q2(self):
        assert determine_quarter("2024-06-30", 12) == "Q2"

    def test_fye12_q3(self):
        assert determine_quarter("2024-09-30", 12) == "Q3"

    def test_fye12_fy(self):
        assert determine_quarter("2024-12-31", 12) == "FY"


# ==================================================================
# classify_period
# ==================================================================

class TestClassifyPeriod:
    """期間長と period_end.month で annual/quarterly を分類する。"""

    def test_annual_12months_fye_month(self):
        # 12ヶ月 + FYE 月末 → annual
        assert classify_period("2024-03-31", "2023-04-01", 3) == "annual"

    def test_quarterly_3months_non_fye(self):
        # 3ヶ月 + 非 FYE 月末 → quarterly
        assert classify_period("2024-06-30", "2024-04-01", 3) == "quarterly"

    def test_quarterly_6months_half_year(self):
        # 6ヶ月（半期）→ quarterly（pe_month != fye_month）
        assert classify_period("2024-09-30", "2024-04-01", 3) == "quarterly"

    def test_annual_period_start_none(self):
        # period_start=None かつ pe.month == fye_month → annual
        assert classify_period("2024-03-31", None, 3) == "annual"

    def test_quarterly_period_start_none_non_fye(self):
        # period_start=None かつ pe.month != fye_month → quarterly
        assert classify_period("2024-06-30", None, 3) == "quarterly"

    def test_quarterly_short_period_at_fye_month(self):
        # 期間 < 300 日 だが fye_month 末 → quarterly
        assert classify_period("2024-03-31", "2023-10-01", 3) == "quarterly"


# ==================================================================
# merge_entry
# ==================================================================

class TestMergeEntry:
    """EDINET 優先、J-Quants で null 補完するマージロジック。"""

    def test_edinet_only(self):
        edinet = {
            "source": "edinet",
            "bs": {"total_assets": 1000},
            "pl": {"revenue": 500},
        }
        result = merge_entry(edinet, None)
        assert result is not None
        assert result["source"] == "edinet"
        assert result["bs"]["total_assets"] == 1000

    def test_jquants_only(self):
        jquants = {
            "bs": {"total_assets": 2000},
            "pl": {"revenue": 800},
        }
        result = merge_entry(None, jquants)
        assert result is not None
        assert result["source"] == "jquants"
        assert result["bs"]["total_assets"] == 2000

    def test_both_edinet_priority(self):
        edinet = {
            "source": "edinet",
            "bs": {"total_assets": 1000, "total_equity": None},
            "pl": {"revenue": 500},
        }
        jquants = {
            "disclosed_date": "2024-05-15",
            "bs": {"total_assets": 1100, "total_equity": 300},
            "pl": {"revenue": 550},
        }
        result = merge_entry(edinet, jquants)
        assert result is not None
        assert result["source"] == "both"
        # EDINET の値が優先される
        assert result["bs"]["total_assets"] == 1000
        assert result["pl"]["revenue"] == 500
        # null 値のみ J-Quants で補完
        assert result["bs"]["total_equity"] == 300
        # jquants_disclosed_date が付与される
        assert result["jquants_disclosed_date"] == "2024-05-15"

    def test_both_null(self):
        result = merge_entry(None, None)
        assert result is None
