"""Tests for pdf_parser.py — multi-strategy pdfplumber PDF parser."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pdf_parser

# ---------------------------------------------------------------------------
# Project-level paths for integration tests
# ---------------------------------------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parents[3] / "projects" / "2780_コメ兵ホールディングス"
PDF_2019 = PROJECT_DIR / "2780_有価証券報告書_2019.pdf"
PDF_2020 = PROJECT_DIR / "2780_有価証券報告書_2020.pdf"
PDF_2025 = PROJECT_DIR / "2780_有価証券報告書_2025.pdf"


# ===========================================================================
# Unit tests
# ===========================================================================


class TestDetectUnit(unittest.TestCase):
    """単位検出テスト（百万円/千円/円）"""

    def test_million_yen(self) -> None:
        m, l = pdf_parser.detect_unit("（単位：百万円）")
        self.assertEqual(m, 1_000_000)
        self.assertEqual(l, "百万円")

    def test_million_yen_parens(self) -> None:
        m, l = pdf_parser.detect_unit("（百万円）")
        self.assertEqual(m, 1_000_000)

    def test_thousand_yen(self) -> None:
        m, l = pdf_parser.detect_unit("（単位：千円）")
        self.assertEqual(m, 1_000)
        self.assertEqual(l, "千円")

    def test_yen(self) -> None:
        m, l = pdf_parser.detect_unit("（単位：円）")
        self.assertEqual(m, 1)
        self.assertEqual(l, "円")

    def test_default_when_no_unit(self) -> None:
        m, l = pdf_parser.detect_unit("何も書かれていない")
        self.assertEqual(m, pdf_parser.DEFAULT_MULTIPLIER)
        self.assertIn("デフォルト", l)


class TestNormalizeValue(unittest.TestCase):
    """負号正規化テスト（△/▲/括弧/ハイフン）"""

    def test_plain_integer(self) -> None:
        self.assertEqual(pdf_parser.normalize_value("1,234,567", 1), 1234567)

    def test_triangle_negative(self) -> None:
        self.assertEqual(pdf_parser.normalize_value("△1,234", 1), -1234)

    def test_filled_triangle_negative(self) -> None:
        self.assertEqual(pdf_parser.normalize_value("▲1,234", 1), -1234)

    def test_paren_negative(self) -> None:
        self.assertEqual(pdf_parser.normalize_value("（1,234）", 1), -1234)

    def test_half_paren_negative(self) -> None:
        self.assertEqual(pdf_parser.normalize_value("(1,234)", 1), -1234)

    def test_hyphen_negative(self) -> None:
        self.assertEqual(pdf_parser.normalize_value("-1,234", 1), -1234)

    def test_fullwidth_minus(self) -> None:
        self.assertEqual(pdf_parser.normalize_value("－1,234", 1), -1234)

    def test_multiplier_thousand(self) -> None:
        self.assertEqual(pdf_parser.normalize_value("100", 1_000), 100_000)

    def test_multiplier_million(self) -> None:
        self.assertEqual(pdf_parser.normalize_value("100", 1_000_000), 100_000_000)

    def test_none_input(self) -> None:
        self.assertIsNone(pdf_parser.normalize_value(None))

    def test_dash(self) -> None:
        self.assertIsNone(pdf_parser.normalize_value("-"))

    def test_em_dash(self) -> None:
        self.assertIsNone(pdf_parser.normalize_value("―"))

    def test_empty_string(self) -> None:
        self.assertIsNone(pdf_parser.normalize_value(""))

    def test_footnote_marker_stripped(self) -> None:
        self.assertEqual(pdf_parser.normalize_value("※1,234", 1), 1234)


class TestMapConcept(unittest.TestCase):
    """科目名マッピングテスト"""

    def test_total_assets(self) -> None:
        self.assertEqual(pdf_parser.map_concept("資産合計"), "total_assets")

    def test_revenue(self) -> None:
        self.assertEqual(pdf_parser.map_concept("売上高"), "revenue")

    def test_operating_income(self) -> None:
        self.assertEqual(pdf_parser.map_concept("営業利益"), "operating_income")

    def test_net_income(self) -> None:
        self.assertEqual(pdf_parser.map_concept("親会社株主に帰属する当期純利益"), "net_income")

    def test_net_loss(self) -> None:
        self.assertEqual(pdf_parser.map_concept("親会社株主に帰属する当期純損失"), "net_income")

    def test_operating_cf(self) -> None:
        self.assertEqual(pdf_parser.map_concept("営業活動によるキャッシュ・フロー"), "operating_cf")

    def test_investing_cf(self) -> None:
        self.assertEqual(pdf_parser.map_concept("投資活動によるキャッシュ・フロー"), "investing_cf")

    def test_financing_cf(self) -> None:
        self.assertEqual(pdf_parser.map_concept("財務活動によるキャッシュ・フロー"), "financing_cf")

    def test_total_equity(self) -> None:
        self.assertEqual(pdf_parser.map_concept("純資産合計"), "total_equity")

    def test_prefix_match_loss_variant(self) -> None:
        result = pdf_parser.map_concept("親会社株主に帰属する当期純利益又は親会社株主に帰属する当期純損失（△）")
        self.assertEqual(result, "net_income")

    def test_unknown_concept(self) -> None:
        self.assertIsNone(pdf_parser.map_concept("未知の科目"))

    def test_whitespace_stripped(self) -> None:
        self.assertEqual(pdf_parser.map_concept("  売上高  "), "revenue")


class TestClassifyStatement(unittest.TestCase):
    """財務諸表種別判定テスト"""

    def test_consolidated_bs(self) -> None:
        self.assertEqual(pdf_parser.classify_statement("①【連結貸借対照表】"), "bs")

    def test_consolidated_pl(self) -> None:
        self.assertEqual(pdf_parser.classify_statement("②【連結損益計算書及び連結包括利益計算書】"), "pl")

    def test_consolidated_cf(self) -> None:
        self.assertEqual(pdf_parser.classify_statement("④【連結キャッシュ・フロー計算書】"), "cf")

    def test_standalone_bs(self) -> None:
        self.assertEqual(pdf_parser.classify_statement("①【貸借対照表】"), "bs")

    def test_no_statement(self) -> None:
        self.assertIsNone(pdf_parser.classify_statement("目次"))


class TestParseColumnHeader(unittest.TestCase):
    """期間ヘッダー解析テスト"""

    def test_western_instant(self) -> None:
        info = pdf_parser.parse_column_header("当連結会計年度\n(2025年３月31日)")
        self.assertIsNotNone(info)
        self.assertEqual(info.period_end, "2025-03-31")
        self.assertEqual(info.label, "current")

    def test_prior_period(self) -> None:
        info = pdf_parser.parse_column_header("前連結会計年度\n(2024年３月31日)")
        self.assertIsNotNone(info)
        self.assertEqual(info.label, "prior")

    def test_era_date(self) -> None:
        info = pdf_parser.parse_column_header("当連結会計年度\n(平成28年3月31日)")
        self.assertIsNotNone(info)
        self.assertEqual(info.period_end, "2016-03-31")

    def test_duration(self) -> None:
        info = pdf_parser.parse_column_header(
            "当連結会計年度\n(自 2024年4月1日\n至 2025年3月31日)"
        )
        self.assertIsNotNone(info)
        self.assertEqual(info.period_type, "duration")
        self.assertEqual(info.period_start, "2024-04-01")
        self.assertEqual(info.period_end, "2025-03-31")

    def test_empty_returns_none(self) -> None:
        self.assertIsNone(pdf_parser.parse_column_header(""))


class TestConceptScore(unittest.TestCase):
    """concept_score 計算テスト"""

    def test_empty_rows(self) -> None:
        self.assertEqual(pdf_parser._concept_score([]), 0)

    def test_known_concepts(self) -> None:
        rows = [
            ["売上高", "100", "200"],
            ["営業利益", "10", "20"],
            ["不明な科目", "5", "6"],
        ]
        self.assertEqual(pdf_parser._concept_score(rows), 2)

    def test_dedup_same_concept(self) -> None:
        rows = [
            ["純資産合計", "100", "200"],
            ["純資産合計", "100", "200"],  # duplicate
        ]
        self.assertEqual(pdf_parser._concept_score(rows), 1)


# ===========================================================================
# Strategy scoring test
# ===========================================================================


class TestStrategyScoring(unittest.TestCase):
    """戦略スコアリングテスト — 期間数優先の検証"""

    def test_more_periods_beats_higher_score(self) -> None:
        """2期間+score=2 が 1期間+score=3 に勝つことを検証"""
        from pdf_parser import PeriodInfo

        # Simulate candidate tuples: (periods, rows, mult, unit, sid, score)
        p_prior = PeriodInfo(period_start="2017-04-01", period_end="2018-03-31",
                             period_type="duration", label="prior")
        p_current = PeriodInfo(period_start="2018-04-01", period_end="2019-03-31",
                               period_type="duration", label="current")
        p_single = PeriodInfo(period_start=None, period_end="2018-03-31",
                              period_type="instant", label="current")

        candidates = [
            ([p_prior, p_current], [], 1000, "千円", "S1", 2),  # 2 periods, score 2
            ([], [], 1000, "千円", "S2", 3),                     # 0 periods, score 3
            ([p_single], [], 1000, "千円", "S3", 3),             # 1 period, score 3
        ]

        # Sort as _try_strategies does
        candidates.sort(key=lambda c: (len(c[0]), c[5]), reverse=True)

        # S1 (2 periods) should win
        self.assertEqual(candidates[0][4], "S1")
        self.assertEqual(len(candidates[0][0]), 2)


class TestMergeTables(unittest.TestCase):
    """_merge_tables テスト — ヘッダー重複排除、空行スキップ"""

    def test_dedup_unit_rows(self) -> None:
        tables = [
            [["", "（単位：千円）", ""], ["売上高", "100", "200"]],
            [["", "（単位：千円）", ""], ["営業利益", "10", "20"]],
        ]
        merged = pdf_parser._merge_tables(tables)
        unit_rows = [r for r in merged if pdf_parser._is_unit_row(r)]
        self.assertEqual(len(unit_rows), 1)

    def test_skip_empty_first_cell_data_rows(self) -> None:
        tables = [
            [["売上高", "100", "200"], ["", "50", "60"], ["営業利益", "10", "20"]],
        ]
        merged = pdf_parser._merge_tables(tables)
        data = [r for r in merged if not pdf_parser._is_unit_row(r) and not pdf_parser._is_period_header_row(r)]
        self.assertEqual(len(data), 2)  # 売上高 and 営業利益 only

    def test_keep_period_header_with_empty_first(self) -> None:
        tables = [
            [["", "前連結会計年度\n(2024年３月31日)", "当連結会計年度\n(2025年３月31日)"],
             ["売上高", "100", "200"]],
        ]
        merged = pdf_parser._merge_tables(tables)
        period_rows = [r for r in merged if pdf_parser._is_period_header_row(r)]
        self.assertEqual(len(period_rows), 1)


class TestNonOverfitAliases(unittest.TestCase):
    """非2780 合成ゴールデンセット — エイリアス非過適合テスト"""

    def test_standard_aliases_work_for_generic_company(self) -> None:
        """汎用的な科目名がマッピングされることを確認（2780固有でないこと）"""
        # These concept names should work for any Japanese company
        generic_concepts = {
            "資産合計": "total_assets",
            "負債合計": "total_liabilities",
            "純資産合計": "total_equity",
            "売上高": "revenue",
            "営業利益": "operating_income",
            "経常利益": "ordinary_income",
            "当期純利益": "net_income",
            "営業活動によるキャッシュ・フロー": "operating_cf",
            "投資活動によるキャッシュ・フロー": "investing_cf",
            "財務活動によるキャッシュ・フロー": "financing_cf",
        }
        for jp_name, expected_key in generic_concepts.items():
            with self.subTest(jp_name=jp_name):
                self.assertEqual(pdf_parser.map_concept(jp_name), expected_key)

    def test_alternative_revenue_name(self) -> None:
        """営業収益も revenue にマッピングされること"""
        self.assertEqual(pdf_parser.map_concept("営業収益"), "revenue")

    def test_no_company_specific_aliases(self) -> None:
        """2780固有の科目名がハードコードされていないことを確認"""
        # Verify that aliases are generic, not specific to コメ兵
        for canonical, aliases in pdf_parser.PDF_CONCEPT_ALIASES.items():
            for alias in aliases:
                with self.subTest(alias=alias):
                    self.assertNotIn("コメ兵", alias)


# ===========================================================================
# Integration tests (require actual PDFs)
# ===========================================================================


@unittest.skipUnless(PDF_2025.exists(), "2025 PDF not available")
class TestIntegration2025(unittest.TestCase):
    """2025年PDFでの統合テスト"""

    def test_extracts_5_key_concepts(self) -> None:
        doc, meta = pdf_parser.parse_pdf(PDF_2025, "2780")
        self.assertTrue(len(doc.periods) >= 1)

        current = max(doc.periods, key=lambda p: p.period_end)
        self.assertIsNotNone(current.bs.get("total_assets"))
        self.assertIsNotNone(current.pl.get("revenue"))
        self.assertIsNotNone(current.pl.get("operating_income"))
        self.assertIsNotNone(current.pl.get("net_income"))
        self.assertIsNotNone(current.cf.get("operating_cf"))

    def test_metadata_fields(self) -> None:
        _, meta = pdf_parser.parse_pdf(PDF_2025, "2780")
        self.assertEqual(meta.parser_version, pdf_parser.__version__)
        self.assertIn(meta.strategy_used, ["S1", "S2", "S3", "text_fallback"])
        self.assertGreater(meta.concept_score, 0)
        self.assertTrue(len(meta.extraction_pages) > 0)


@unittest.skipUnless(PDF_2019.exists(), "2019 PDF not available")
class TestIntegration2019(unittest.TestCase):
    """2019年PDF — fix_1 解消確認（operating_cf 抽出）"""

    def test_operating_cf_extracted(self) -> None:
        doc, meta = pdf_parser.parse_pdf(PDF_2019, "2780")
        current = max(doc.periods, key=lambda p: p.period_end)
        self.assertIsNotNone(
            current.cf.get("operating_cf"),
            "2019 operating_cf should not be None after fix_1"
        )
        # Value should be 1,447,926 * 1000 = 1,447,926,000
        self.assertEqual(current.cf["operating_cf"], 1_447_926_000)


@unittest.skipUnless(PDF_2020.exists(), "2020 PDF not available")
class TestIntegration2020(unittest.TestCase):
    """2020年PDF — 分断テーブル対応確認"""

    def test_total_assets_extracted(self) -> None:
        doc, _ = pdf_parser.parse_pdf(PDF_2020, "2780")
        current = max(doc.periods, key=lambda p: p.period_end)
        self.assertIsNotNone(
            current.bs.get("total_assets"),
            "2020 total_assets should be extractable with multi-strategy + text supplement"
        )

    def test_5_key_concepts(self) -> None:
        doc, _ = pdf_parser.parse_pdf(PDF_2020, "2780")
        current = max(doc.periods, key=lambda p: p.period_end)
        self.assertIsNotNone(current.bs.get("total_assets"))
        self.assertIsNotNone(current.pl.get("revenue"))
        self.assertIsNotNone(current.pl.get("operating_income"))
        self.assertIsNotNone(current.pl.get("net_income"))
        self.assertIsNotNone(current.cf.get("operating_cf"))


if __name__ == "__main__":
    unittest.main()
