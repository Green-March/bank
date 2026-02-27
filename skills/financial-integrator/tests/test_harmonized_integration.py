"""Tests for --harmonized-dir (web data 3rd source) integration."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from integrator import (
    _extract_web,
    merge_entry,
    merge_three_entries,
    integrate,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_edinet_financials(fye_month: int = 3) -> dict:
    """Minimal EDINET financials.json for testing."""
    return {
        "documents": [
            {
                "document_id": "S100TEST",
                "periods": [
                    {
                        "period_start": "2024-04-01",
                        "period_end": "2025-03-31",
                        "bs": {
                            "total_assets": 100000,
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
                ],
            }
        ]
    }


def _make_jquants_data() -> dict:
    """Minimal J-Quants data for testing."""
    return {
        "records": [
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
    }


def _make_harmonized_data() -> dict:
    """Minimal web-data-harmonizer output for testing."""
    return {
        "ticker": "9999",
        "company_name": "テスト株式会社",
        "annual": [
            {
                "period_end": "2025-03-31",
                "fiscal_year": 2025,
                "quarter": "FY",
                "source": "web:kabutan+yahoo",
                "bs": {
                    "total_assets": None,
                    "total_equity": None,
                },
                "pl": {
                    "revenue": 80500,
                    "operating_income": 10200,
                    "gross_profit": 35000,
                    "net_income": None,
                },
                "cf": {},
            },
            {
                "period_end": "2024-03-31",
                "fiscal_year": 2024,
                "quarter": "FY",
                "source": "web:kabutan",
                "bs": {},
                "pl": {
                    "revenue": 75000,
                    "operating_income": 9000,
                    "net_income": 6000,
                },
                "cf": {},
            },
        ],
    }


# ---------------------------------------------------------------------------
# _extract_web tests
# ---------------------------------------------------------------------------

class TestExtractWeb:

    def test_extracts_annual_entries(self) -> None:
        web_data = _make_harmonized_data()
        result = _extract_web(web_data, fye_month=3)
        assert 2025 in result
        assert 2024 in result

    def test_entry_has_correct_structure(self) -> None:
        web_data = _make_harmonized_data()
        result = _extract_web(web_data, fye_month=3)
        entry = result[2025]
        assert entry["period_end"] == "2025-03-31"
        assert entry["fiscal_year"] == 2025
        assert entry["quarter"] == "FY"
        assert "bs" in entry
        assert "pl" in entry
        assert "cf" in entry

    def test_preserves_pl_values(self) -> None:
        web_data = _make_harmonized_data()
        result = _extract_web(web_data, fye_month=3)
        assert result[2025]["pl"]["gross_profit"] == 35000

    def test_empty_annual_returns_empty(self) -> None:
        result = _extract_web({"annual": []}, fye_month=3)
        assert result == {}

    def test_missing_annual_key_returns_empty(self) -> None:
        result = _extract_web({}, fye_month=3)
        assert result == {}


# ---------------------------------------------------------------------------
# merge_three_entries tests
# ---------------------------------------------------------------------------

class TestMergeThreeEntries:

    def test_all_three_sources(self) -> None:
        edinet = {
            "period_end": "2025-03-31",
            "fiscal_year": 2025,
            "quarter": "FY",
            "source": "edinet",
            "bs": {"total_assets": 100000},
            "pl": {"revenue": 80000, "gross_profit": None},
            "cf": {"operating_cf": 12000},
        }
        web = {
            "period_end": "2025-03-31",
            "fiscal_year": 2025,
            "quarter": "FY",
            "source": "web:kabutan",
            "bs": {},
            "pl": {"revenue": 80500, "gross_profit": 35000},
            "cf": {},
        }
        jquants = {
            "period_end": "2025-03-31",
            "fiscal_year": 2025,
            "source": "jquants",
            "disclosed_date": "2025-05-10",
            "bs": {"total_assets": 100000},
            "pl": {"revenue": 80000},
            "cf": {},
        }
        merged = merge_three_entries(edinet, web, jquants)
        assert merged is not None
        assert merged["source"] == "edinet+web+jquants"
        # EDINET value preserved (primary)
        assert merged["pl"]["revenue"] == 80000
        # Web value fills null (secondary)
        assert merged["pl"]["gross_profit"] == 35000
        # J-Quants disclosed_date included
        assert merged["jquants_disclosed_date"] == "2025-05-10"
        # Web source detail preserved
        assert merged["web_source"] == "web:kabutan"

    def test_edinet_plus_web_only(self) -> None:
        edinet = {
            "source": "edinet",
            "bs": {"total_assets": 100000},
            "pl": {"revenue": 80000, "gross_profit": None},
            "cf": {},
        }
        web = {
            "source": "web:yahoo",
            "bs": {},
            "pl": {"gross_profit": 35000},
            "cf": {},
        }
        merged = merge_three_entries(edinet, web, None)
        assert merged is not None
        assert merged["source"] == "edinet+web"
        assert merged["pl"]["gross_profit"] == 35000
        assert merged["web_source"] == "web:yahoo"

    def test_web_plus_jquants_only(self) -> None:
        web = {
            "source": "web:kabutan+yahoo",
            "bs": {},
            "pl": {"revenue": 80000},
            "cf": {},
        }
        jquants = {
            "source": "jquants",
            "disclosed_date": "2025-05-10",
            "bs": {"total_assets": 100000},
            "pl": {"revenue": 79000},
            "cf": {},
        }
        merged = merge_three_entries(None, web, jquants)
        assert merged is not None
        assert merged["source"] == "web+jquants"
        # Web priority over J-Quants
        assert merged["pl"]["revenue"] == 80000
        # J-Quants fills missing bs
        assert merged["bs"]["total_assets"] == 100000
        assert merged["web_source"] == "web:kabutan+yahoo"

    def test_edinet_only_via_three_way(self) -> None:
        """web=None, jquants=None → merge_entry に委譲、source='edinet'。"""
        edinet = {
            "source": "edinet",
            "bs": {"total_assets": 100000},
            "pl": {"revenue": 80000},
            "cf": {},
        }
        merged = merge_three_entries(edinet, None, None)
        assert merged is not None
        assert merged["source"] == "edinet"
        assert "web_source" not in merged

    def test_edinet_jquants_no_web_uses_both(self) -> None:
        """web=None → merge_entry に委譲、source='both' 後方互換。"""
        edinet = {
            "source": "edinet",
            "bs": {"total_assets": 100000},
            "pl": {"revenue": 80000},
            "cf": {},
        }
        jquants = {
            "source": "jquants",
            "disclosed_date": "2025-05-10",
            "bs": {},
            "pl": {"revenue": 80000},
            "cf": {},
        }
        merged = merge_three_entries(edinet, None, jquants)
        assert merged is not None
        assert merged["source"] == "both"
        assert "web_source" not in merged

    def test_web_only(self) -> None:
        web = {
            "source": "web:shikiho",
            "bs": {},
            "pl": {"revenue": 80000},
            "cf": {},
        }
        merged = merge_three_entries(None, web, None)
        assert merged is not None
        assert merged["source"] == "web"
        assert merged["web_source"] == "web:shikiho"

    def test_all_none_returns_none(self) -> None:
        assert merge_three_entries(None, None, None) is None

    def test_edinet_priority_over_web(self) -> None:
        edinet = {
            "source": "edinet",
            "bs": {},
            "pl": {"revenue": 80000},
            "cf": {},
        }
        web = {
            "source": "web:kabutan",
            "bs": {},
            "pl": {"revenue": 99999},
            "cf": {},
        }
        merged = merge_three_entries(edinet, web, None)
        assert merged["pl"]["revenue"] == 80000


# ---------------------------------------------------------------------------
# merge_entry backward compatibility
# ---------------------------------------------------------------------------

class TestMergeEntryBackwardCompat:

    def test_edinet_jquants_still_works(self) -> None:
        edinet = {
            "source": "edinet",
            "bs": {"total_assets": 100000},
            "pl": {"revenue": 80000},
            "cf": {},
        }
        jquants = {
            "source": "jquants",
            "disclosed_date": "2025-05-10",
            "bs": {"total_assets": 100000},
            "pl": {"revenue": 80000},
            "cf": {},
        }
        merged = merge_entry(edinet, jquants)
        assert merged is not None
        assert merged["source"] == "both"
        assert merged["jquants_disclosed_date"] == "2025-05-10"

    def test_edinet_only_still_works(self) -> None:
        edinet = {
            "source": "edinet",
            "bs": {"total_assets": 100000},
            "pl": {"revenue": 80000},
            "cf": {},
        }
        merged = merge_entry(edinet, None)
        assert merged is not None
        assert merged["source"] == "edinet"

    def test_jquants_only_still_works(self) -> None:
        jquants = {
            "source": "jquants",
            "disclosed_date": "2025-05-10",
            "bs": {},
            "pl": {"revenue": 80000},
            "cf": {},
        }
        merged = merge_entry(None, jquants)
        assert merged is not None
        assert merged["source"] == "jquants"

    def test_both_none_still_returns_none(self) -> None:
        assert merge_entry(None, None) is None


# ---------------------------------------------------------------------------
# Full integration with harmonized_dir
# ---------------------------------------------------------------------------

class TestIntegrateWithHarmonizedDir:

    def _setup_dirs(self, tmp_path: Path) -> tuple[Path, Path, Path]:
        parsed_dir = tmp_path / "parsed"
        parsed_dir.mkdir()
        harmonized_dir = tmp_path / "harmonized"
        harmonized_dir.mkdir()
        output_path = tmp_path / "output" / "integrated.json"
        return parsed_dir, harmonized_dir, output_path

    def _write_edinet(self, parsed_dir: Path) -> None:
        (parsed_dir / "financials.json").write_text(
            json.dumps(_make_edinet_financials()), encoding="utf-8"
        )

    def _write_jquants(self, parsed_dir: Path) -> None:
        (parsed_dir / "jquants_fins_statements.json").write_text(
            json.dumps(_make_jquants_data()), encoding="utf-8"
        )

    def _write_harmonized(self, harmonized_dir: Path) -> None:
        (harmonized_dir / "harmonized_financials.json").write_text(
            json.dumps(_make_harmonized_data()), encoding="utf-8"
        )

    def test_with_harmonized_dir(self, tmp_path: Path) -> None:
        parsed_dir, harmonized_dir, output_path = self._setup_dirs(tmp_path)
        self._write_edinet(parsed_dir)
        self._write_jquants(parsed_dir)
        self._write_harmonized(harmonized_dir)

        result = integrate(
            ticker="9999",
            fye_month=3,
            parsed_dir=parsed_dir,
            output_path=output_path,
            harmonized_dir=harmonized_dir,
        )

        assert output_path.exists()
        assert "web" in result["integration_metadata"]["input_files"]
        # FY2025 has all 3 sources
        fy2025 = [a for a in result["annual"] if a["fiscal_year"] == 2025]
        assert len(fy2025) == 1
        assert "edinet" in fy2025[0]["source"]
        assert "web" in fy2025[0]["source"]
        # Web-only FY2024 should appear
        fy2024 = [a for a in result["annual"] if a["fiscal_year"] == 2024]
        assert len(fy2024) >= 1

    def test_without_harmonized_dir_backward_compat(self, tmp_path: Path) -> None:
        parsed_dir, _, output_path = self._setup_dirs(tmp_path)
        self._write_edinet(parsed_dir)
        self._write_jquants(parsed_dir)

        result = integrate(
            ticker="9999",
            fye_month=3,
            parsed_dir=parsed_dir,
            output_path=output_path,
        )

        assert output_path.exists()
        assert "web" not in result["integration_metadata"]["input_files"]
        fy2025 = [a for a in result["annual"] if a["fiscal_year"] == 2025]
        assert len(fy2025) == 1
        assert fy2025[0]["source"] == "both"

    def test_harmonized_dir_missing_file(self, tmp_path: Path) -> None:
        parsed_dir, harmonized_dir, output_path = self._setup_dirs(tmp_path)
        self._write_edinet(parsed_dir)
        # harmonized_dir exists but no file inside

        with pytest.warns(UserWarning, match="Harmonized ファイルが見つかりません"):
            result = integrate(
                ticker="9999",
                fye_month=3,
                parsed_dir=parsed_dir,
                output_path=output_path,
                harmonized_dir=harmonized_dir,
            )

        assert "web" not in result["integration_metadata"]["input_files"]

    def test_web_fills_gross_profit_null(self, tmp_path: Path) -> None:
        """Web source fills EDINET's null gross_profit."""
        parsed_dir, harmonized_dir, output_path = self._setup_dirs(tmp_path)
        self._write_edinet(parsed_dir)
        self._write_harmonized(harmonized_dir)

        result = integrate(
            ticker="9999",
            fye_month=3,
            parsed_dir=parsed_dir,
            output_path=output_path,
            harmonized_dir=harmonized_dir,
        )

        fy2025 = [a for a in result["annual"] if a["fiscal_year"] == 2025]
        assert fy2025[0]["pl"]["gross_profit"] == 35000

    def test_edinet_value_not_overwritten_by_web(self, tmp_path: Path) -> None:
        """EDINET revenue should not be overwritten by web revenue."""
        parsed_dir, harmonized_dir, output_path = self._setup_dirs(tmp_path)
        self._write_edinet(parsed_dir)
        self._write_harmonized(harmonized_dir)

        result = integrate(
            ticker="9999",
            fye_month=3,
            parsed_dir=parsed_dir,
            output_path=output_path,
            harmonized_dir=harmonized_dir,
        )

        fy2025 = [a for a in result["annual"] if a["fiscal_year"] == 2025]
        # EDINET revenue=80000, web revenue=80500 -> EDINET wins
        assert fy2025[0]["pl"]["revenue"] == 80000

    def test_web_source_detail_preserved(self, tmp_path: Path) -> None:
        """web_source フィールドに元の出典ラベルが保持される。"""
        parsed_dir, harmonized_dir, output_path = self._setup_dirs(tmp_path)
        self._write_edinet(parsed_dir)
        self._write_jquants(parsed_dir)
        self._write_harmonized(harmonized_dir)

        result = integrate(
            ticker="9999",
            fye_month=3,
            parsed_dir=parsed_dir,
            output_path=output_path,
            harmonized_dir=harmonized_dir,
        )

        fy2025 = [a for a in result["annual"] if a["fiscal_year"] == 2025]
        assert fy2025[0]["web_source"] == "web:kabutan+yahoo"

    def test_harmonized_invalid_json(self, tmp_path: Path) -> None:
        """無効 JSON の harmonized ファイルは警告を出してスキップ。"""
        parsed_dir, harmonized_dir, output_path = self._setup_dirs(tmp_path)
        self._write_edinet(parsed_dir)
        self._write_jquants(parsed_dir)
        (harmonized_dir / "harmonized_financials.json").write_text(
            "{ invalid json }", encoding="utf-8"
        )

        with pytest.warns(UserWarning, match="Harmonized JSON が不正です"):
            result = integrate(
                ticker="9999",
                fye_month=3,
                parsed_dir=parsed_dir,
                output_path=output_path,
                harmonized_dir=harmonized_dir,
            )

        assert "web" not in result["integration_metadata"]["input_files"]
        fy2025 = [a for a in result["annual"] if a["fiscal_year"] == 2025]
        assert fy2025[0]["source"] == "both"


# ---------------------------------------------------------------------------
# _extract_web edge cases (schema_conformance / risk_disclosure)
# ---------------------------------------------------------------------------

class TestExtractWebEdgeCases:

    def test_period_end_none_skipped(self) -> None:
        """period_end が None のレコードはスキップされる。"""
        web_data = {
            "annual": [
                {
                    "period_end": None,
                    "fiscal_year": 2025,
                    "source": "web:kabutan",
                    "bs": {},
                    "pl": {"revenue": 80000},
                    "cf": {},
                },
                {
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "source": "web:kabutan",
                    "bs": {},
                    "pl": {"revenue": 75000},
                    "cf": {},
                },
            ]
        }
        result = _extract_web(web_data, fye_month=3)
        assert 2025 not in result
        assert 2024 in result

    def test_non_dict_record_skipped(self) -> None:
        """dict 以外のレコードはスキップされる。"""
        web_data = {"annual": ["invalid", None, 42]}
        result = _extract_web(web_data, fye_month=3)
        assert result == {}

    def test_both_period_end_and_fy_none_skipped(self) -> None:
        web_data = {
            "annual": [
                {"period_end": None, "fiscal_year": None, "bs": {}, "pl": {}, "cf": {}}
            ]
        }
        result = _extract_web(web_data, fye_month=3)
        assert result == {}
