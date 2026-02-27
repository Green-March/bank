"""3ソースマージ境界ケーステスト

テスト対象:
  1. 欠損ソース6パターン (integrate / merge 関数レベル)
  2. 重複期間のマージ優先順位
  3. 型不一致 (文字列数値混在 / null / 欠損フィールド)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from integrator import (
    _extract_web,
    _merge_two,
    integrate,
    merge_entry,
    merge_three_entries,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _edinet_financials(
    *,
    fye_month: int = 3,
    periods: list[dict] | None = None,
) -> dict:
    """EDINET financials.json を生成する。"""
    if periods is None:
        periods = [
            {
                "period_start": "2024-04-01",
                "period_end": "2025-03-31",
                "bs": {
                    "total_assets": 100000,
                    "current_assets": 60000,
                    "total_equity": 50000,
                    "net_assets": 55000,
                },
                "pl": {
                    "revenue": 80000,
                    "operating_income": 10000,
                    "net_income": 7000,
                    "gross_profit": None,
                },
                "cf": {
                    "operating_cf": 12000,
                    "investing_cf": -5000,
                    "financing_cf": -3000,
                },
            }
        ]
    return {
        "documents": [
            {"document_id": "S100TEST", "periods": periods}
        ]
    }


def _jquants_data(*, records: list[dict] | None = None) -> dict:
    """J-Quants データを生成する。"""
    if records is None:
        records = [
            {
                "period_end": "2025-03-31",
                "period_start": "2024-04-01",
                "disclosed_date": "2025-05-10",
                "actuals": {
                    "revenue": 80000,
                    "operating_income": 10000,
                    "net_income": 7000,
                    "total_assets": 100000,
                    "equity": 50000,
                    "net_assets": 55000,
                },
            }
        ]
    return {"records": records}


def _harmonized_data(*, annual: list[dict] | None = None) -> dict:
    """web-data-harmonizer 出力を生成する。"""
    if annual is None:
        annual = [
            {
                "period_end": "2025-03-31",
                "fiscal_year": 2025,
                "quarter": "FY",
                "source": "web:kabutan+yahoo",
                "bs": {},
                "pl": {
                    "revenue": 80500,
                    "operating_income": 10200,
                    "gross_profit": 35000,
                    "net_income": None,
                },
                "cf": {},
            }
        ]
    return {
        "ticker": "9999",
        "company_name": "テスト株式会社",
        "annual": annual,
    }


def _write_files(
    tmp_path: Path,
    *,
    edinet: dict | None = None,
    jquants: dict | None = None,
    harmonized: dict | None = None,
) -> tuple[Path, Path | None, Path]:
    """テスト用ディレクトリにファイルを書き出す。"""
    parsed_dir = tmp_path / "parsed"
    parsed_dir.mkdir(exist_ok=True)
    output_path = tmp_path / "output" / "integrated.json"

    if edinet is not None:
        (parsed_dir / "financials.json").write_text(
            json.dumps(edinet), encoding="utf-8"
        )
    if jquants is not None:
        (parsed_dir / "jquants_fins_statements.json").write_text(
            json.dumps(jquants), encoding="utf-8"
        )

    harmonized_dir = None
    if harmonized is not None:
        harmonized_dir = tmp_path / "harmonized"
        harmonized_dir.mkdir(exist_ok=True)
        (harmonized_dir / "harmonized_financials.json").write_text(
            json.dumps(harmonized), encoding="utf-8"
        )

    return parsed_dir, harmonized_dir, output_path


# ===================================================================
# 1. 欠損ソース6パターン
# ===================================================================

class TestMissingSourcePatterns:
    """6パターンの欠損ソース組み合わせを検証する。

    integrate() レベル (EDINET 必須):
      - EDINET のみ
      - EDINET + J-Quants
      - EDINET + Web
      - EDINET + J-Quants + Web (全ソース)

    merge_three_entries レベル (EDINET 不要):
      - J-Quants のみ
      - Web のみ
      - J-Quants + Web
    """

    # --- integrate() レベル ---

    def test_integrate_edinet_only(self, tmp_path: Path) -> None:
        """EDINET のみ: J-Quants なし・Web なし。"""
        parsed_dir, _, output_path = _write_files(
            tmp_path, edinet=_edinet_financials()
        )
        with pytest.warns(UserWarning, match="J-Quants ファイルが見つかりません"):
            result = integrate(
                ticker="9999",
                fye_month=3,
                parsed_dir=parsed_dir,
                output_path=output_path,
            )

        assert output_path.exists()
        assert "jquants" not in result["integration_metadata"]["input_files"]
        assert "web" not in result["integration_metadata"]["input_files"]
        fy2025 = [a for a in result["annual"] if a["fiscal_year"] == 2025]
        assert len(fy2025) == 1
        assert fy2025[0]["source"] == "edinet"
        assert fy2025[0]["pl"]["revenue"] == 80000

    def test_integrate_edinet_plus_jquants(self, tmp_path: Path) -> None:
        """EDINET + J-Quants: Web なし。"""
        parsed_dir, _, output_path = _write_files(
            tmp_path,
            edinet=_edinet_financials(),
            jquants=_jquants_data(),
        )
        result = integrate(
            ticker="9999",
            fye_month=3,
            parsed_dir=parsed_dir,
            output_path=output_path,
        )

        assert "jquants" in result["integration_metadata"]["input_files"]
        assert "web" not in result["integration_metadata"]["input_files"]
        fy2025 = [a for a in result["annual"] if a["fiscal_year"] == 2025]
        assert fy2025[0]["source"] == "both"
        assert fy2025[0]["jquants_disclosed_date"] == "2025-05-10"

    def test_integrate_edinet_plus_web(self, tmp_path: Path) -> None:
        """EDINET + Web: J-Quants なし。"""
        parsed_dir, harmonized_dir, output_path = _write_files(
            tmp_path,
            edinet=_edinet_financials(),
            harmonized=_harmonized_data(),
        )
        with pytest.warns(UserWarning, match="J-Quants ファイルが見つかりません"):
            result = integrate(
                ticker="9999",
                fye_month=3,
                parsed_dir=parsed_dir,
                output_path=output_path,
                harmonized_dir=harmonized_dir,
            )

        assert "web" in result["integration_metadata"]["input_files"]
        assert "jquants" not in result["integration_metadata"]["input_files"]
        fy2025 = [a for a in result["annual"] if a["fiscal_year"] == 2025]
        assert fy2025[0]["source"] == "edinet+web"
        assert fy2025[0]["pl"]["gross_profit"] == 35000
        assert fy2025[0]["web_source"] == "web:kabutan+yahoo"

    def test_integrate_all_three_sources(self, tmp_path: Path) -> None:
        """EDINET + J-Quants + Web: 全ソース。"""
        parsed_dir, harmonized_dir, output_path = _write_files(
            tmp_path,
            edinet=_edinet_financials(),
            jquants=_jquants_data(),
            harmonized=_harmonized_data(),
        )
        result = integrate(
            ticker="9999",
            fye_month=3,
            parsed_dir=parsed_dir,
            output_path=output_path,
            harmonized_dir=harmonized_dir,
        )

        assert "edinet" in result["integration_metadata"]["input_files"]
        assert "jquants" in result["integration_metadata"]["input_files"]
        assert "web" in result["integration_metadata"]["input_files"]
        fy2025 = [a for a in result["annual"] if a["fiscal_year"] == 2025]
        assert fy2025[0]["source"] == "edinet+web+jquants"
        assert fy2025[0]["pl"]["revenue"] == 80000  # EDINET wins
        assert fy2025[0]["pl"]["gross_profit"] == 35000  # Web fills
        assert fy2025[0]["jquants_disclosed_date"] == "2025-05-10"

    # --- merge_three_entries レベル (EDINET 不要) ---

    def test_merge_jquants_only(self) -> None:
        """J-Quants のみ: merge_three_entries(None, None, jquants)。"""
        jquants = {
            "source": "jquants",
            "disclosed_date": "2025-05-10",
            "bs": {"total_assets": 100000, "total_equity": 50000},
            "pl": {"revenue": 80000, "operating_income": 10000},
            "cf": {"operating_cf": 12000},
        }
        merged = merge_three_entries(None, None, jquants)
        assert merged is not None
        assert merged["source"] == "jquants"
        assert merged["bs"]["total_assets"] == 100000
        assert merged["pl"]["revenue"] == 80000
        assert "web_source" not in merged

    def test_merge_web_only(self) -> None:
        """Web のみ: merge_three_entries(None, web, None)。"""
        web = {
            "source": "web:yahoo",
            "bs": {},
            "pl": {"revenue": 80500, "gross_profit": 35000},
            "cf": {},
        }
        merged = merge_three_entries(None, web, None)
        assert merged is not None
        assert merged["source"] == "web"
        assert merged["pl"]["revenue"] == 80500
        assert merged["web_source"] == "web:yahoo"

    def test_merge_jquants_plus_web(self) -> None:
        """J-Quants + Web: merge_three_entries(None, web, jquants)。"""
        web = {
            "source": "web:kabutan",
            "bs": {},
            "pl": {"revenue": 80500, "gross_profit": 35000},
            "cf": {},
        }
        jquants = {
            "source": "jquants",
            "disclosed_date": "2025-05-10",
            "bs": {"total_assets": 100000},
            "pl": {"revenue": 79000},
            "cf": {"operating_cf": 12000},
        }
        merged = merge_three_entries(None, web, jquants)
        assert merged is not None
        assert merged["source"] == "web+jquants"
        # Web > J-Quants: revenue は Web が優先
        assert merged["pl"]["revenue"] == 80500
        # J-Quants が Web にない BS を補完
        assert merged["bs"]["total_assets"] == 100000
        # J-Quants が Web にない CF を補完
        assert merged["cf"]["operating_cf"] == 12000
        assert merged["web_source"] == "web:kabutan"
        assert merged["jquants_disclosed_date"] == "2025-05-10"


# ===================================================================
# 2. 重複期間のマージ優先順位
# ===================================================================

class TestOverlappingPeriodPriority:
    """同一 fiscal_year/period_end に複数ソースがある場合の優先順位検証。"""

    def test_three_source_priority_cascade(self) -> None:
        """EDINET > Web > J-Quants の優先カスケードを全フィールドで検証。"""
        edinet = {
            "source": "edinet",
            "bs": {"total_assets": 100000, "total_equity": None, "net_assets": None},
            "pl": {"revenue": 80000, "gross_profit": None, "operating_income": 10000},
            "cf": {"operating_cf": 12000, "investing_cf": -5000},
        }
        web = {
            "source": "web:kabutan",
            "bs": {"total_equity": 48000, "net_assets": None},
            "pl": {"revenue": 99999, "gross_profit": 35000, "operating_income": 99999},
            "cf": {},
        }
        jquants = {
            "source": "jquants",
            "disclosed_date": "2025-05-10",
            "bs": {"total_assets": 99999, "total_equity": 99999, "net_assets": 55000},
            "pl": {"revenue": 99999, "gross_profit": 99999, "operating_income": 99999},
            "cf": {"operating_cf": 99999},
        }
        merged = merge_three_entries(edinet, web, jquants)
        assert merged is not None
        # EDINET 値が保持される (non-None)
        assert merged["bs"]["total_assets"] == 100000
        assert merged["pl"]["revenue"] == 80000
        assert merged["pl"]["operating_income"] == 10000
        assert merged["cf"]["operating_cf"] == 12000
        assert merged["cf"]["investing_cf"] == -5000
        # Web が EDINET の null を補完 (2nd priority)
        assert merged["bs"]["total_equity"] == 48000
        assert merged["pl"]["gross_profit"] == 35000
        # J-Quants が残りの null を補完 (3rd priority)
        assert merged["bs"]["net_assets"] == 55000
        # Web の null は J-Quants では補完されない
        # (Web の net_assets=None → Stage1 merge で EDINET の None のまま
        #  → Stage2 merge で J-Quants の 55000 が入る)
        assert merged["source"] == "edinet+web+jquants"

    def test_multi_fy_mixed_source_availability(self, tmp_path: Path) -> None:
        """複数 FY で異なるソース可用性パターン。

        FY2023: EDINET のみ
        FY2024: EDINET + Web
        FY2025: EDINET + J-Quants + Web
        """
        edinet = _edinet_financials(
            periods=[
                {
                    "period_start": "2022-04-01",
                    "period_end": "2023-03-31",
                    "bs": {"total_assets": 90000, "total_equity": 45000},
                    "pl": {"revenue": 70000, "operating_income": 8000},
                    "cf": {"operating_cf": 10000},
                },
                {
                    "period_start": "2023-04-01",
                    "period_end": "2024-03-31",
                    "bs": {"total_assets": 95000, "total_equity": 47000},
                    "pl": {"revenue": 75000, "operating_income": 9000, "gross_profit": None},
                    "cf": {"operating_cf": 11000},
                },
                {
                    "period_start": "2024-04-01",
                    "period_end": "2025-03-31",
                    "bs": {"total_assets": 100000, "total_equity": 50000},
                    "pl": {"revenue": 80000, "operating_income": 10000, "gross_profit": None},
                    "cf": {"operating_cf": 12000},
                },
            ]
        )
        jquants = _jquants_data(
            records=[
                {
                    "period_end": "2025-03-31",
                    "period_start": "2024-04-01",
                    "disclosed_date": "2025-05-10",
                    "actuals": {
                        "revenue": 80000,
                        "operating_income": 10000,
                        "net_income": 7000,
                        "total_assets": 100000,
                        "equity": 50000,
                    },
                }
            ]
        )
        harmonized = _harmonized_data(
            annual=[
                {
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "quarter": "FY",
                    "source": "web:yahoo",
                    "bs": {},
                    "pl": {"gross_profit": 30000},
                    "cf": {},
                },
                {
                    "period_end": "2025-03-31",
                    "fiscal_year": 2025,
                    "quarter": "FY",
                    "source": "web:kabutan+yahoo",
                    "bs": {},
                    "pl": {"gross_profit": 35000},
                    "cf": {},
                },
            ]
        )

        parsed_dir, harmonized_dir, output_path = _write_files(
            tmp_path,
            edinet=edinet,
            jquants=jquants,
            harmonized=harmonized,
        )
        result = integrate(
            ticker="9999",
            fye_month=3,
            parsed_dir=parsed_dir,
            output_path=output_path,
            harmonized_dir=harmonized_dir,
        )

        annual = {a["fiscal_year"]: a for a in result["annual"]}

        # FY2023: EDINET のみ (Web/J-Quants に該当 FY なし)
        assert annual[2023]["source"] == "edinet"
        assert annual[2023]["pl"]["revenue"] == 70000

        # FY2024: EDINET + Web
        assert annual[2024]["source"] == "edinet+web"
        assert annual[2024]["pl"]["revenue"] == 75000
        assert annual[2024]["pl"]["gross_profit"] == 30000

        # FY2025: EDINET + Web + J-Quants
        assert annual[2025]["source"] == "edinet+web+jquants"
        assert annual[2025]["pl"]["revenue"] == 80000
        assert annual[2025]["pl"]["gross_profit"] == 35000

    def test_duplicate_edinet_quarterly_richer_wins(self, tmp_path: Path) -> None:
        """同一四半期に EDINET 重複がある場合、non-null フィールドが多い方が残る。"""
        edinet = {
            "documents": [
                {
                    "document_id": "S100POOR",
                    "periods": [
                        {
                            "period_start": "2024-04-01",
                            "period_end": "2025-03-31",
                            "bs": {"total_assets": 100000, "total_equity": 50000},
                            "pl": {"revenue": 80000, "operating_income": 10000},
                            "cf": {},
                        },
                        {
                            "period_start": "2024-04-01",
                            "period_end": "2024-06-30",
                            "bs": {"total_assets": 95000},
                            "pl": {"revenue": 20000},
                            "cf": {},
                        },
                    ],
                },
                {
                    "document_id": "S100RICH",
                    "periods": [
                        {
                            "period_start": "2024-04-01",
                            "period_end": "2024-06-30",
                            "bs": {"total_assets": 95000, "total_equity": 47000},
                            "pl": {
                                "revenue": 20000,
                                "operating_income": 2500,
                                "net_income": 1800,
                            },
                            "cf": {},
                        },
                    ],
                },
            ]
        }
        parsed_dir, _, output_path = _write_files(
            tmp_path, edinet=edinet
        )
        with pytest.warns(UserWarning, match="J-Quants ファイルが見つかりません"):
            result = integrate(
                ticker="9999",
                fye_month=3,
                parsed_dir=parsed_dir,
                output_path=output_path,
            )

        q1_entries = [
            q for q in result["quarterly"]
            if q["quarter"] == "Q1" and q["fiscal_year"] == 2025
        ]
        assert len(q1_entries) == 1
        # RICH の方が non-null フィールド多い (total_assets, total_equity, revenue,
        # operating_income, net_income = 5) vs POOR (total_assets, revenue = 2)
        assert q1_entries[0]["edinet_doc_id"] == "S100RICH"
        assert q1_entries[0]["pl"]["operating_income"] == 2500
        assert q1_entries[0]["pl"]["net_income"] == 1800

    def test_web_only_fy_appears_alongside_edinet_fys(self, tmp_path: Path) -> None:
        """EDINET に無い FY の Web データが annual に追加される。"""
        edinet = _edinet_financials(
            periods=[
                {
                    "period_start": "2024-04-01",
                    "period_end": "2025-03-31",
                    "bs": {"total_assets": 100000, "total_equity": 50000},
                    "pl": {"revenue": 80000, "operating_income": 10000},
                    "cf": {"operating_cf": 12000},
                }
            ]
        )
        harmonized = _harmonized_data(
            annual=[
                {
                    "period_end": "2025-03-31",
                    "fiscal_year": 2025,
                    "quarter": "FY",
                    "source": "web:kabutan",
                    "bs": {},
                    "pl": {"gross_profit": 35000},
                    "cf": {},
                },
                {
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "quarter": "FY",
                    "source": "web:kabutan",
                    "bs": {},
                    "pl": {"revenue": 75000, "gross_profit": 30000},
                    "cf": {},
                },
            ]
        )
        parsed_dir, harmonized_dir, output_path = _write_files(
            tmp_path, edinet=edinet, harmonized=harmonized
        )
        with pytest.warns(UserWarning):
            result = integrate(
                ticker="9999",
                fye_month=3,
                parsed_dir=parsed_dir,
                output_path=output_path,
                harmonized_dir=harmonized_dir,
            )

        annual = {a["fiscal_year"]: a for a in result["annual"]}
        # FY2024 は Web のみ
        assert 2024 in annual
        assert annual[2024]["source"] == "web"
        assert annual[2024]["pl"]["revenue"] == 75000
        # FY2025 は EDINET + Web
        assert annual[2025]["source"] == "edinet+web"


# ===================================================================
# 3. 型不一致・null・欠損フィールド
# ===================================================================

class TestTypeMismatch:
    """文字列数値混在・null・欠損フィールドの境界ケース。"""

    def test_string_numeric_primary_preserved(self) -> None:
        """primary に文字列 "1000" がある場合、secondary の int で上書きされない。"""
        primary = {
            "bs": {"total_assets": "1000"},
            "pl": {"revenue": "80000"},
            "cf": {},
        }
        secondary = {
            "bs": {"total_assets": 100000},
            "pl": {"revenue": 80000},
            "cf": {},
        }
        merged = _merge_two(primary, secondary)
        assert merged is not None
        # 文字列 "1000" は non-None なので保持される
        assert merged["bs"]["total_assets"] == "1000"
        assert merged["pl"]["revenue"] == "80000"

    def test_string_numeric_secondary_fills_null(self) -> None:
        """primary が None で secondary に文字列 "1000" がある場合、文字列が入る。"""
        primary = {
            "bs": {"total_assets": None},
            "pl": {"revenue": None},
            "cf": {},
        }
        secondary = {
            "bs": {"total_assets": "100000"},
            "pl": {"revenue": "80000"},
            "cf": {},
        }
        merged = _merge_two(primary, secondary)
        assert merged is not None
        assert merged["bs"]["total_assets"] == "100000"
        assert merged["pl"]["revenue"] == "80000"

    def test_null_values_fill_correctly(self) -> None:
        """primary の null フィールドが secondary の値で補完される。"""
        edinet = {
            "source": "edinet",
            "bs": {
                "total_assets": 100000,
                "total_equity": None,
                "net_assets": None,
                "current_assets": None,
            },
            "pl": {
                "revenue": 80000,
                "gross_profit": None,
                "operating_income": None,
                "net_income": None,
            },
            "cf": {"operating_cf": None},
        }
        jquants = {
            "source": "jquants",
            "disclosed_date": "2025-05-10",
            "bs": {
                "total_assets": 99999,
                "total_equity": 50000,
                "net_assets": 55000,
            },
            "pl": {
                "revenue": 99999,
                "operating_income": 10000,
                "net_income": 7000,
            },
            "cf": {"operating_cf": 12000},
        }
        merged = merge_entry(edinet, jquants)
        assert merged is not None
        # EDINET non-null は保持
        assert merged["bs"]["total_assets"] == 100000
        assert merged["pl"]["revenue"] == 80000
        # J-Quants で null 補完
        assert merged["bs"]["total_equity"] == 50000
        assert merged["bs"]["net_assets"] == 55000
        assert merged["pl"]["operating_income"] == 10000
        assert merged["pl"]["net_income"] == 7000
        assert merged["cf"]["operating_cf"] == 12000
        # EDINET にキーがあり J-Quants にキーがない → None のまま
        assert merged["bs"]["current_assets"] is None
        assert merged["pl"]["gross_profit"] is None

    def test_missing_section_key_in_primary(self) -> None:
        """primary に bs キーがない場合、secondary の bs が使われる。"""
        primary = {
            "pl": {"revenue": 80000},
            "cf": {},
        }
        secondary = {
            "bs": {"total_assets": 100000},
            "pl": {"revenue": 99999},
            "cf": {"operating_cf": 12000},
        }
        merged = _merge_two(primary, secondary)
        assert merged is not None
        # primary に bs がない → secondary の bs がそのまま入る
        assert merged["bs"]["total_assets"] == 100000
        # primary に pl がある → primary 優先
        assert merged["pl"]["revenue"] == 80000
        # cf は secondary から補完
        assert merged["cf"]["operating_cf"] == 12000

    def test_missing_section_key_in_secondary(self) -> None:
        """secondary に pl キーがない場合、primary の pl がそのまま残る。"""
        primary = {
            "bs": {"total_assets": 100000},
            "pl": {"revenue": 80000, "gross_profit": None},
            "cf": {},
        }
        secondary = {
            "bs": {"total_equity": 50000},
            "cf": {"operating_cf": 12000},
        }
        merged = _merge_two(primary, secondary)
        assert merged is not None
        assert merged["pl"]["revenue"] == 80000
        assert merged["pl"]["gross_profit"] is None
        assert merged["bs"]["total_equity"] == 50000
        assert merged["cf"]["operating_cf"] == 12000

    def test_empty_sections_both_sources(self) -> None:
        """両ソースとも空セクション {} の場合。"""
        edinet = {"source": "edinet", "bs": {}, "pl": {}, "cf": {}}
        jquants = {
            "source": "jquants",
            "disclosed_date": "2025-05-10",
            "bs": {},
            "pl": {},
            "cf": {},
        }
        merged = merge_entry(edinet, jquants)
        assert merged is not None
        assert merged["source"] == "both"
        assert merged["bs"] == {}
        assert merged["pl"] == {}
        assert merged["cf"] == {}

    def test_zero_value_not_treated_as_null(self) -> None:
        """値 0 は null ではないため、secondary で上書きされない。"""
        primary = {
            "bs": {"total_assets": 0},
            "pl": {"revenue": 0, "net_income": 0},
            "cf": {"operating_cf": 0},
        }
        secondary = {
            "bs": {"total_assets": 100000},
            "pl": {"revenue": 80000, "net_income": 7000},
            "cf": {"operating_cf": 12000},
        }
        merged = _merge_two(primary, secondary)
        assert merged is not None
        assert merged["bs"]["total_assets"] == 0
        assert merged["pl"]["revenue"] == 0
        assert merged["pl"]["net_income"] == 0
        assert merged["cf"]["operating_cf"] == 0

    def test_extra_keys_in_secondary_added(self) -> None:
        """secondary にのみ存在するキーが primary に追加される。"""
        primary = {
            "bs": {"total_assets": 100000},
            "pl": {"revenue": 80000},
            "cf": {},
        }
        secondary = {
            "bs": {"total_assets": 99999, "current_liabilities": 30000},
            "pl": {"revenue": 99999, "ordinary_income": 9500},
            "cf": {"free_cash_flow": 7000},
        }
        merged = _merge_two(primary, secondary)
        assert merged is not None
        # primary にないキーは secondary から追加
        assert merged["bs"]["current_liabilities"] == 30000
        assert merged["pl"]["ordinary_income"] == 9500
        assert merged["cf"]["free_cash_flow"] == 7000
        # primary の既存値は保持
        assert merged["bs"]["total_assets"] == 100000
        assert merged["pl"]["revenue"] == 80000

    def test_three_way_merge_with_mixed_nulls(self) -> None:
        """3ソースで異なるフィールドが null のパターン。"""
        edinet = {
            "source": "edinet",
            "bs": {"total_assets": 100000, "total_equity": None, "net_assets": None},
            "pl": {"revenue": None, "operating_income": 10000, "gross_profit": None},
            "cf": {"operating_cf": None, "investing_cf": -5000},
        }
        web = {
            "source": "web:kabutan",
            "bs": {"total_equity": None},
            "pl": {"revenue": 80500, "gross_profit": 35000},
            "cf": {},
        }
        jquants = {
            "source": "jquants",
            "disclosed_date": "2025-05-10",
            "bs": {"total_equity": 50000, "net_assets": 55000},
            "pl": {"revenue": 79000},
            "cf": {"operating_cf": 12000},
        }
        merged = merge_three_entries(edinet, web, jquants)
        assert merged is not None
        assert merged["source"] == "edinet+web+jquants"
        # EDINET: total_assets=100000 (non-null, preserved)
        assert merged["bs"]["total_assets"] == 100000
        # EDINET: total_equity=None → Web: None → J-Quants: 50000
        assert merged["bs"]["total_equity"] == 50000
        # EDINET: net_assets=None → Web: no key → J-Quants: 55000
        assert merged["bs"]["net_assets"] == 55000
        # EDINET: revenue=None → Web: 80500 (fills)
        assert merged["pl"]["revenue"] == 80500
        # EDINET: operating_income=10000 (preserved)
        assert merged["pl"]["operating_income"] == 10000
        # EDINET: gross_profit=None → Web: 35000 (fills)
        assert merged["pl"]["gross_profit"] == 35000
        # EDINET: operating_cf=None → Web: no key → J-Quants: 12000
        assert merged["cf"]["operating_cf"] == 12000
        # EDINET: investing_cf=-5000 (preserved)
        assert merged["cf"]["investing_cf"] == -5000


# ===================================================================
# 4. Coverage メタデータ検証
# ===================================================================

class TestCoverageMetadata:
    """coverage_summary と coverage_matrix の正確性を検証する。"""

    def test_coverage_summary_reflects_multi_source(self, tmp_path: Path) -> None:
        """coverage_summary に各 FY の source ラベルが正しく反映される。"""
        edinet = _edinet_financials(
            periods=[
                {
                    "period_start": "2023-04-01",
                    "period_end": "2024-03-31",
                    "bs": {"total_assets": 95000, "total_equity": 47000},
                    "pl": {"revenue": 75000, "operating_income": 9000},
                    "cf": {},
                },
                {
                    "period_start": "2024-04-01",
                    "period_end": "2025-03-31",
                    "bs": {"total_assets": 100000, "total_equity": 50000},
                    "pl": {"revenue": 80000, "operating_income": 10000},
                    "cf": {},
                },
            ]
        )
        jquants = _jquants_data(
            records=[
                {
                    "period_end": "2025-03-31",
                    "period_start": "2024-04-01",
                    "disclosed_date": "2025-05-10",
                    "actuals": {
                        "revenue": 80000,
                        "total_assets": 100000,
                    },
                }
            ]
        )
        parsed_dir, _, output_path = _write_files(
            tmp_path, edinet=edinet, jquants=jquants
        )
        result = integrate(
            ticker="9999",
            fye_month=3,
            parsed_dir=parsed_dir,
            output_path=output_path,
        )

        summary = result["integration_metadata"]["coverage_summary"]
        assert "FY2024" in summary
        assert "FY2025" in summary
        assert summary["FY2024"]["annual"] == "edinet"
        assert summary["FY2025"]["annual"] == "both"

    def test_coverage_matrix_sorted_by_period_end(self, tmp_path: Path) -> None:
        """coverage_matrix が period_end 昇順でソートされている。"""
        edinet = _edinet_financials(
            periods=[
                {
                    "period_start": "2023-04-01",
                    "period_end": "2024-03-31",
                    "bs": {"total_assets": 95000, "total_equity": 47000},
                    "pl": {"revenue": 75000, "operating_income": 9000},
                    "cf": {},
                },
                {
                    "period_start": "2024-04-01",
                    "period_end": "2025-03-31",
                    "bs": {"total_assets": 100000, "total_equity": 50000},
                    "pl": {"revenue": 80000, "operating_income": 10000},
                    "cf": {},
                },
            ]
        )
        parsed_dir, _, output_path = _write_files(
            tmp_path, edinet=edinet
        )
        with pytest.warns(UserWarning):
            result = integrate(
                ticker="9999",
                fye_month=3,
                parsed_dir=parsed_dir,
                output_path=output_path,
            )

        matrix = result["coverage_matrix"]
        period_ends = [m["period_end"] for m in matrix]
        assert period_ends == sorted(period_ends)

    def test_source_priority_rules_generated(self, tmp_path: Path) -> None:
        """source_priority_rules が coverage_summary から自動生成される。"""
        parsed_dir, harmonized_dir, output_path = _write_files(
            tmp_path,
            edinet=_edinet_financials(),
            jquants=_jquants_data(),
            harmonized=_harmonized_data(),
        )
        result = integrate(
            ticker="9999",
            fye_month=3,
            parsed_dir=parsed_dir,
            output_path=output_path,
            harmonized_dir=harmonized_dir,
        )

        rules = result["integration_metadata"]["source_priority_rules"]
        assert "FY2025" in rules
        assert isinstance(rules["FY2025"], str)
        assert "annual=" in rules["FY2025"]


# ===================================================================
# 5. _extract_web 追加境界ケース
# ===================================================================

class TestExtractWebAdditional:
    """_extract_web の追加境界ケース。"""

    def test_fiscal_year_inferred_from_period_end(self) -> None:
        """fiscal_year が None の場合、period_end から推定される。"""
        web_data = {
            "annual": [
                {
                    "period_end": "2025-03-31",
                    "fiscal_year": None,
                    "source": "web:kabutan",
                    "bs": {},
                    "pl": {"revenue": 80000},
                    "cf": {},
                }
            ]
        }
        result = _extract_web(web_data, fye_month=3)
        assert 2025 in result
        assert result[2025]["fiscal_year"] == 2025

    def test_duplicate_fy_first_entry_wins(self) -> None:
        """同一 FY に複数 Web エントリーがある場合、最初の方が残る。"""
        web_data = {
            "annual": [
                {
                    "period_end": "2025-03-31",
                    "fiscal_year": 2025,
                    "source": "web:kabutan",
                    "bs": {},
                    "pl": {"revenue": 80000},
                    "cf": {},
                },
                {
                    "period_end": "2025-03-31",
                    "fiscal_year": 2025,
                    "source": "web:yahoo",
                    "bs": {},
                    "pl": {"revenue": 85000},
                    "cf": {},
                },
            ]
        }
        result = _extract_web(web_data, fye_month=3)
        assert result[2025]["pl"]["revenue"] == 80000
        assert result[2025]["source"] == "web:kabutan"

    def test_fye12_fiscal_year_calculation(self) -> None:
        """fye_month=12 の場合の fiscal_year 計算。"""
        web_data = {
            "annual": [
                {
                    "period_end": "2024-12-31",
                    "fiscal_year": 2024,
                    "source": "web:kabutan",
                    "bs": {},
                    "pl": {"revenue": 80000},
                    "cf": {},
                }
            ]
        }
        result = _extract_web(web_data, fye_month=12)
        assert 2024 in result
        assert result[2024]["period_end"] == "2024-12-31"
