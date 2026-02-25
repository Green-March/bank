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

    def test_none_raises_attribute_error(self):
        # None 入力は str.lower() で AttributeError — 現仕様では str 型を前提とする
        with self.assertRaises(AttributeError):
            disclosure_parser.context_priority(None)


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


# ============================================================
# 回帰テスト (task_026): エッジケース網羅
# ============================================================


class TestContextPriorityCaseMixing(unittest.TestCase):
    """エッジケース1: 大文字小文字混在パターン (.lower() 正規化の確認)"""

    def test_upper_lower_mix(self):
        # CURRENTyearDURATION → currentyearduration
        # currentyear +100, current +60 = 160
        self.assertEqual(disclosure_parser.context_priority("CURRENTyearDURATION"), 160)

    def test_camel_case_reversed(self):
        # currentYEARduration → currentyearduration
        # currentyear +100, current +60 = 160
        self.assertEqual(disclosure_parser.context_priority("currentYEARduration"), 160)

    def test_alternating_case(self):
        # cUrReNtYeArDuRaTiOn → currentyearduration
        # currentyear +100, current +60 = 160
        self.assertEqual(
            disclosure_parser.context_priority("cUrReNtYeArDuRaTiOn"), 160
        )

    def test_mixed_case_nonconsolidated(self):
        # NonCONSOLIDATEDmember → nonconsolidatedmember
        # nonconsolidated -25
        self.assertEqual(
            disclosure_parser.context_priority("NonCONSOLIDATEDmember"), -25
        )

    def test_mixed_case_current_quarter(self):
        # CURRENTquarterDuration → currentquarterduration
        # currentquarter +50 (current +60 は排他で除外)
        self.assertEqual(
            disclosure_parser.context_priority("CURRENTquarterDuration"), 50
        )


class TestContextPriorityDuplicateKeywords(unittest.TestCase):
    """エッジケース2: 重複キーワードを含むコンテキストID"""

    def test_duplicate_current_year(self):
        # `in` 演算子は回数に関係なく1回マッチ
        # currentyear +100, current +60 = 160
        result = disclosure_parser.context_priority(
            "CurrentYearDuration_CurrentYearInstant"
        )
        self.assertEqual(result, 160)

    def test_duplicate_nonconsolidated(self):
        # nonconsolidated -25 (1回のみ適用)
        result = disclosure_parser.context_priority(
            "NonConsolidatedMember_NonConsolidatedMember"
        )
        self.assertEqual(result, -25)

    def test_duplicate_prior(self):
        # prior -80 (1回のみ適用)
        result = disclosure_parser.context_priority(
            "PriorYearDuration_PriorQuarterDuration"
        )
        self.assertEqual(result, -80)

    def test_both_consolidated_and_nonconsolidated(self):
        # nonconsolidated が先に評価され -25、elif で consolidated +40 はスキップ
        result = disclosure_parser.context_priority(
            "ConsolidatedMember_NonConsolidatedMember"
        )
        self.assertEqual(result, -25)


class TestContextPriorityZeroScore(unittest.TestCase):
    """エッジケース3: 境界値テスト — スコアが正確に0になるパターン"""

    def test_no_keywords_arbitrary(self):
        # キーワードを一切含まない文字列 → 0
        self.assertEqual(disclosure_parser.context_priority("FooBarBaz"), 0)

    def test_duration_only(self):
        # "Duration" はスコアキーワードではない → 0
        self.assertEqual(disclosure_parser.context_priority("Duration"), 0)

    def test_instant_only(self):
        # "Instant" はスコアキーワードではない → 0
        self.assertEqual(disclosure_parser.context_priority("Instant"), 0)

    def test_member_only(self):
        # "Member" はスコアキーワードではない → 0
        self.assertEqual(disclosure_parser.context_priority("Member"), 0)

    def test_partial_keyword_curr(self):
        # "curr" は "current" に不足 → マッチしない → 0
        self.assertEqual(disclosure_parser.context_priority("CurrDuration"), 0)

    def test_partial_keyword_prio(self):
        # "prio" は "prior" に不足 → マッチしない → 0
        self.assertEqual(disclosure_parser.context_priority("PrioDuration"), 0)


class TestContextPriorityConflictingModifiers(unittest.TestCase):
    """エッジケース4: 全修飾子の組み合わせ (競合ケース)"""

    def test_current_year_nonconsolidated_prior(self):
        # currentyear +100, current +60, nonconsolidated -25, prior -80 = 55
        result = disclosure_parser.context_priority(
            "CurrentYearDuration_NonConsolidatedMember_PriorContext"
        )
        self.assertEqual(result, 55)

    def test_current_year_consolidated_prior(self):
        # currentyear +100, current +60, consolidated +40, prior -80 = 120
        result = disclosure_parser.context_priority(
            "CurrentYearDuration_ConsolidatedMember_PriorContext"
        )
        self.assertEqual(result, 120)

    def test_current_quarter_nonconsolidated_prior(self):
        # currentquarter +50 (current排他), nonconsolidated -25, prior -80 = -55
        result = disclosure_parser.context_priority(
            "CurrentQuarterDuration_NonConsolidatedMember_PriorContext"
        )
        self.assertEqual(result, -55)

    def test_current_quarter_consolidated_previous(self):
        # currentquarter +50, consolidated +40, previous -80 = 10
        result = disclosure_parser.context_priority(
            "CurrentQuarterDuration_ConsolidatedMember_PreviousContext"
        )
        self.assertEqual(result, 10)

    def test_current_year_consolidated_previous(self):
        # currentyear +100, current +60, consolidated +40, previous -80 = 120
        result = disclosure_parser.context_priority(
            "CurrentYearDuration_ConsolidatedMember_PreviousContext"
        )
        self.assertEqual(result, 120)

    def test_prior_and_previous_single_deduction(self):
        # prior と previous が同時に存在しても -80 は1回のみ (単一 if 文)
        result = disclosure_parser.context_priority(
            "PriorYearDuration_PreviousContext"
        )
        self.assertEqual(result, -80)


class TestContextPrioritySubstringRegression(unittest.TestCase):
    """エッジケース5: nonconsolidated 部分文字列マッチ誤判定防止 (回帰防止)"""

    def test_nonconsolidated_standalone(self):
        # nonconsolidated -25 のみ、consolidated +40 は付かない
        result = disclosure_parser.context_priority("NonConsolidatedMember")
        self.assertEqual(result, -25)
        # 誤って consolidated +40 が加算されると 15 になる
        self.assertNotEqual(result, 15)

    def test_nonconsolidated_with_prior(self):
        # nonconsolidated -25, prior -80 = -105
        # 誤加算時は -65 になる
        result = disclosure_parser.context_priority(
            "PriorYearDuration_NonConsolidatedMember"
        )
        self.assertEqual(result, -105)
        self.assertNotEqual(result, -65)

    def test_nonconsolidated_embedded_in_longer_string(self):
        # "XNonConsolidatedY" でも nonconsolidated がマッチ → -25
        result = disclosure_parser.context_priority("XNonConsolidatedY")
        self.assertEqual(result, -25)

    def test_consolidated_not_triggered_by_nonconsolidated(self):
        # elif 分岐により nonconsolidated が先に評価 → consolidated +40 は付かない
        for ctx in [
            "NonConsolidatedMember",
            "CurrentYearDuration_NonConsolidatedMember",
            "PriorYearDuration_NonConsolidatedMember",
        ]:
            with self.subTest(ctx=ctx):
                score = disclosure_parser.context_priority(ctx)
                # NonConsolidatedMember を除去した基準スコアとの差が -25 であること
                base_ctx = ctx.replace("_NonConsolidatedMember", "").replace(
                    "NonConsolidatedMember", ""
                )
                base_score = disclosure_parser.context_priority(base_ctx)
                self.assertEqual(score, base_score - 25)


class TestContextPriorityCurrentQuarterExclusion(unittest.TestCase):
    """エッジケース6: currentquarter は +50 のみ、current の +60 を加算しない"""

    def test_current_quarter_excludes_current_bonus(self):
        # currentquarter +50 のみ
        result = disclosure_parser.context_priority("CurrentQuarterDuration")
        self.assertEqual(result, 50)
        # 誤って current +60 が加算されると 110 になる
        self.assertNotEqual(result, 110)

    def test_current_quarter_instant(self):
        # Instant でも同一ロジック: currentquarter +50 のみ
        result = disclosure_parser.context_priority("CurrentQuarterInstant")
        self.assertEqual(result, 50)

    def test_current_quarter_nonconsolidated(self):
        # currentquarter +50, nonconsolidated -25 = 25
        result = disclosure_parser.context_priority(
            "CurrentQuarterDuration_NonConsolidatedMember"
        )
        self.assertEqual(result, 25)

    def test_current_quarter_consolidated(self):
        # currentquarter +50, consolidated +40 = 90
        result = disclosure_parser.context_priority(
            "CurrentQuarterDuration_ConsolidatedMember"
        )
        self.assertEqual(result, 90)

    def test_current_year_includes_current_bonus_contrast(self):
        # 対照: currentyear は currentquarter と異なり current +60 が加算される
        result = disclosure_parser.context_priority("CurrentYearDuration")
        # currentyear +100, current +60 = 160
        self.assertEqual(result, 160)
        self.assertGreater(result, 100)


if __name__ == "__main__":
    unittest.main()
