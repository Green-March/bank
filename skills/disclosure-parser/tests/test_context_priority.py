from __future__ import annotations

from pathlib import Path
import sys
import unittest

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import parser as disclosure_parser


class TestContextPriorityBasic(unittest.TestCase):
    """基本ケース: 時期キーワードによるスコア計算"""

    def test_current_year_duration(self):
        # currentyear +100, current +60 = 160
        self.assertEqual(disclosure_parser.context_priority("CurrentYearDuration"), 160)

    def test_current_quarter_duration(self):
        # currentquarter +50 (current の +60 は除外される)
        self.assertEqual(disclosure_parser.context_priority("CurrentQuarterDuration"), 50)

    def test_prior_year_duration(self):
        # prior -80
        self.assertEqual(disclosure_parser.context_priority("PriorYearDuration"), -80)


class TestContextPriorityConsolidation(unittest.TestCase):
    """連結/非連結判定（過去バグ再発防止・最重要）"""

    def test_nonconsolidated_member(self):
        # currentyear +100, current +60, nonconsolidated -25 = 135
        result = disclosure_parser.context_priority(
            "CurrentYearDuration_NonConsolidatedMember"
        )
        self.assertEqual(result, 135)

    def test_consolidated_member(self):
        # currentyear +100, current +60, consolidated +40 = 200
        result = disclosure_parser.context_priority(
            "CurrentYearDuration_ConsolidatedMember"
        )
        self.assertEqual(result, 200)

    def test_plain_no_consolidation_bonus(self):
        # Member なし → 連結加点なし → 160
        self.assertEqual(disclosure_parser.context_priority("CurrentYearDuration"), 160)

    def test_nonconsolidated_not_matched_as_consolidated(self):
        """nonconsolidated が consolidated の substring match で
        誤って +40 されないことを明示的に確認"""
        result = disclosure_parser.context_priority(
            "CurrentYearDuration_NonConsolidatedMember"
        )
        # もし誤って consolidated +40 が付くと 175 になる
        self.assertNotEqual(result, 175)
        # 正しくは nonconsolidated -25 のみ → 135
        self.assertEqual(result, 135)


class TestContextPriorityBoundary(unittest.TestCase):
    """境界ケース"""

    def test_empty_string(self):
        self.assertEqual(disclosure_parser.context_priority(""), 0)

    def test_uppercase(self):
        # .lower() で正規化されるので同一スコア
        self.assertEqual(
            disclosure_parser.context_priority("CURRENTYEARDURATION"), 160
        )

    def test_previous_year_duration(self):
        # previous -80
        self.assertEqual(disclosure_parser.context_priority("PreviousYearDuration"), -80)

    def test_unknown_context(self):
        self.assertEqual(disclosure_parser.context_priority("UnknownContext"), 0)


class TestContextPriorityCompound(unittest.TestCase):
    """複合ケース"""

    def test_prior_nonconsolidated(self):
        # prior -80, nonconsolidated -25 = -105
        result = disclosure_parser.context_priority(
            "PriorYearDuration_NonConsolidatedMember"
        )
        self.assertEqual(result, -105)

    def test_current_quarter_consolidated(self):
        # currentquarter +50, consolidated +40 = 90
        result = disclosure_parser.context_priority(
            "CurrentQuarterDuration_ConsolidatedMember"
        )
        self.assertEqual(result, 90)


if __name__ == "__main__":
    unittest.main()
