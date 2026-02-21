from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from render import (
    _MONETARY_FIELDS,
    _fiscal_year_display,
    _fmt_value,
    _period_in_fiscal_year,
    _period_label,
    _row_absence,
    build_absence_map,
    infer_fy_end_month,
    render_markdown,
)


def test_financial_reporter_generates_markdown_and_html() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "main.py"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        metrics_path = tmp_path / "metrics.json"
        output_md = tmp_path / "out.md"
        output_html = tmp_path / "out.html"

        payload = {
            "ticker": "7203",
            "company_name": "Sample Co.",
            "generated_at": "2026-02-11T00:00:00+00:00",
            "metrics_series": [
                {
                    "fiscal_year": 2024,
                    "revenue": 100,
                    "operating_income": 10,
                    "net_income": 7,
                    "roe_percent": 8.1,
                    "roa_percent": 3.2,
                    "operating_margin_percent": 10.0,
                    "equity_ratio_percent": 35.0,
                    "free_cash_flow": 4.5,
                }
            ],
        }
        metrics_path.write_text(json.dumps(payload), encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--ticker",
                "7203",
                "--metrics",
                str(metrics_path),
                "--output-md",
                str(output_md),
                "--output-html",
                str(output_html),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr
        assert output_md.exists()
        assert output_html.exists()
        assert "7203 Sample Co. 分析レポート" in output_md.read_text(encoding="utf-8")
        assert "<table>" in output_html.read_text(encoding="utf-8")


def test_resolve_company_name_from_parsed_json() -> None:
    """company_name missing in metrics → resolved from parsed JSON."""
    script = Path(__file__).resolve().parents[1] / "scripts" / "main.py"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # Build data/{ticker}/parsed/ structure
        ticker = "9999"
        parsed_dir = tmp_path / ticker / "parsed"
        parsed_dir.mkdir(parents=True)

        # metrics.json without company_name
        metrics_payload = {
            "ticker": ticker,
            "company_name": None,
            "generated_at": "2026-02-17T00:00:00+00:00",
            "metrics_series": [
                {"fiscal_year": 2024, "revenue": 50, "operating_income": 5,
                 "net_income": 3, "roe_percent": 6.0, "roa_percent": 2.0,
                 "operating_margin_percent": 10.0, "equity_ratio_percent": 40.0,
                 "free_cash_flow": 2.0}
            ],
        }
        metrics_path = parsed_dir / "metrics.json"
        metrics_path.write_text(json.dumps(metrics_payload), encoding="utf-8")

        # Parsed document with company_name
        parsed_doc = {
            "ticker": ticker,
            "company_name": "テスト株式会社",
            "periods": [{"fiscal_year": 2024, "period_type": "FY"}],
        }
        (parsed_dir / "doc1.json").write_text(
            json.dumps(parsed_doc, ensure_ascii=False), encoding="utf-8"
        )

        output_md = tmp_path / "out.md"
        output_html = tmp_path / "out.html"

        env = {**os.environ, "DATA_PATH": str(tmp_path)}
        result = subprocess.run(
            [sys.executable, str(script), "--ticker", ticker,
             "--metrics", str(metrics_path),
             "--output-md", str(output_md), "--output-html", str(output_html)],
            check=False, capture_output=True, text=True, env=env,
        )

        assert result.returncode == 0, result.stderr
        md_text = output_md.read_text(encoding="utf-8")
        assert "テスト株式会社" in md_text
        assert "Unknown" not in md_text


def test_resolve_company_name_from_processed_dir() -> None:
    """company_name resolved from processed/ directory (not just parsed/)."""
    script = Path(__file__).resolve().parents[1] / "scripts" / "main.py"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        ticker = "8888"
        processed_dir = tmp_path / ticker / "processed"
        processed_dir.mkdir(parents=True)

        # metrics.json without company_name
        metrics_payload = {
            "ticker": ticker,
            "company_name": None,
            "generated_at": "2026-02-17T00:00:00+00:00",
            "metrics_series": [
                {"fiscal_year": 2024, "revenue": 50, "operating_income": 5,
                 "net_income": 3, "roe_percent": 6.0, "roa_percent": 2.0,
                 "operating_margin_percent": 10.0, "equity_ratio_percent": 40.0,
                 "free_cash_flow": 2.0}
            ],
        }
        metrics_path = processed_dir / "metrics.json"
        metrics_path.write_text(json.dumps(metrics_payload), encoding="utf-8")

        # Processed document with company_name
        processed_doc = {
            "ticker": ticker,
            "company_name": "プロセス株式会社",
            "periods": [{"fiscal_year": 2024, "period_type": "FY"}],
        }
        (processed_dir / "doc1.json").write_text(
            json.dumps(processed_doc, ensure_ascii=False), encoding="utf-8"
        )

        output_md = tmp_path / "out.md"
        output_html = tmp_path / "out.html"

        env = {**os.environ, "DATA_PATH": str(tmp_path)}
        result = subprocess.run(
            [sys.executable, str(script), "--ticker", ticker,
             "--metrics", str(metrics_path),
             "--output-md", str(output_md), "--output-html", str(output_html)],
            check=False, capture_output=True, text=True, env=env,
        )

        assert result.returncode == 0, result.stderr
        md_text = output_md.read_text(encoding="utf-8")
        assert "プロセス株式会社" in md_text
        assert "Unknown" not in md_text


def test_resolve_company_name_from_edinet_cache() -> None:
    """company_name missing in metrics and parsed → resolved from EDINET cache."""
    script = Path(__file__).resolve().parents[1] / "scripts" / "main.py"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        ticker = "7685"
        parsed_dir = tmp_path / ticker / "parsed"
        parsed_dir.mkdir(parents=True)
        edinet_dir = tmp_path / ticker / "raw" / "edinet"
        edinet_dir.mkdir(parents=True)

        # metrics.json with "Unknown"
        metrics_payload = {
            "ticker": ticker,
            "company_name": "Unknown",
            "generated_at": "2026-02-17T00:00:00+00:00",
            "metrics_series": [],
        }
        metrics_path = parsed_dir / "metrics.json"
        metrics_path.write_text(json.dumps(metrics_payload), encoding="utf-8")

        # EDINET documents cache with matching secCode
        edinet_cache = {
            "date": "2021-03-31",
            "result_count": 2,
            "results": [
                {"secCode": "76850", "filerName": "WDBココ株式会社",
                 "edinetCode": "E12345", "docID": "S100TEST"},
                {"secCode": "99990", "filerName": "Other Corp",
                 "edinetCode": "E99999", "docID": "S100XXXX"},
            ],
        }
        (edinet_dir / "documents_2021-03-31.json").write_text(
            json.dumps(edinet_cache, ensure_ascii=False), encoding="utf-8"
        )

        output_md = tmp_path / "out.md"
        output_html = tmp_path / "out.html"

        env = {**os.environ, "DATA_PATH": str(tmp_path)}
        result = subprocess.run(
            [sys.executable, str(script), "--ticker", ticker,
             "--metrics", str(metrics_path),
             "--output-md", str(output_md), "--output-html", str(output_html)],
            check=False, capture_output=True, text=True, env=env,
        )

        assert result.returncode == 0, result.stderr
        md_text = output_md.read_text(encoding="utf-8")
        assert "WDBココ株式会社" in md_text
        assert "Unknown" not in md_text


def test_resolve_company_name_from_edinet_subdir() -> None:
    """company_name resolved from EDINET subdirectory (e.g. shihanki_hokokusho/)."""
    script = Path(__file__).resolve().parents[1] / "scripts" / "main.py"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        ticker = "7685"
        processed_dir = tmp_path / ticker / "processed"
        processed_dir.mkdir(parents=True)
        subdir = tmp_path / ticker / "raw" / "edinet" / "shihanki_hokokusho"
        subdir.mkdir(parents=True)

        metrics_payload = {
            "ticker": ticker,
            "company_name": "Unknown",
            "generated_at": "2026-02-17T00:00:00+00:00",
            "metrics_series": [],
        }
        metrics_path = processed_dir / "metrics.json"
        metrics_path.write_text(json.dumps(metrics_payload), encoding="utf-8")

        edinet_cache = {
            "date": "2024-08-14",
            "results": [
                {"secCode": "76850",
                 "filerName": "株式会社ＢｕｙＳｅｌｌ　Ｔｅｃｈｎｏｌｏｇｉｅｓ",
                 "edinetCode": "E36404", "docID": "S100TEST2"},
            ],
        }
        (subdir / "documents_2024-08-14.json").write_text(
            json.dumps(edinet_cache, ensure_ascii=False), encoding="utf-8"
        )

        output_md = tmp_path / "out.md"
        output_html = tmp_path / "out.html"

        env = {**os.environ, "DATA_PATH": str(tmp_path)}
        result = subprocess.run(
            [sys.executable, str(script), "--ticker", ticker,
             "--metrics", str(metrics_path),
             "--output-md", str(output_md), "--output-html", str(output_html)],
            check=False, capture_output=True, text=True, env=env,
        )

        assert result.returncode == 0, result.stderr
        md_text = output_md.read_text(encoding="utf-8")
        assert "株式会社ＢｕｙＳｅｌｌ　Ｔｅｃｈｎｏｌｏｇｉｅｓ" in md_text
        assert "Unknown" not in md_text


def test_company_name_present_no_resolution_needed() -> None:
    """company_name already in metrics → no resolution triggered."""
    script = Path(__file__).resolve().parents[1] / "scripts" / "main.py"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        metrics_path = tmp_path / "metrics.json"
        output_md = tmp_path / "out.md"
        output_html = tmp_path / "out.html"

        payload = {
            "ticker": "1234",
            "company_name": "既存企業名",
            "generated_at": "2026-02-17T00:00:00+00:00",
            "metrics_series": [],
        }
        metrics_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(script), "--ticker", "1234",
             "--metrics", str(metrics_path),
             "--output-md", str(output_md), "--output-html", str(output_html)],
            check=False, capture_output=True, text=True,
        )

        assert result.returncode == 0, result.stderr
        md_text = output_md.read_text(encoding="utf-8")
        assert "既存企業名" in md_text


# ===================================================================
# Period label / fiscal year display tests
# ===================================================================

class TestPeriodLabel:
    def test_full_year(self):
        assert _period_label(12) == "通期"

    def test_half_year(self):
        assert _period_label(6) == "半期"

    def test_quarter(self):
        assert _period_label(3) == "四半期"

    def test_three_quarters(self):
        assert _period_label(9) == "3Q累計"

    def test_none(self):
        assert _period_label(None) == ""

    def test_unknown_months(self):
        assert _period_label(5) == "5M"


class TestFiscalYearDisplay:
    def test_full_year_no_suffix(self):
        """通期は括弧なし."""
        assert _fiscal_year_display({"fiscal_year": 2024, "period_months": 12}) == "2024"

    def test_half_year_with_suffix(self):
        """半期は括弧付き."""
        assert _fiscal_year_display({"fiscal_year": 2025, "period_months": 6}) == "2025 (半期)"

    def test_quarter_with_suffix(self):
        assert _fiscal_year_display({"fiscal_year": 2025, "period_months": 3}) == "2025 (四半期)"

    def test_no_period_months(self):
        """period_months なしは括弧なし (後方互換)."""
        assert _fiscal_year_display({"fiscal_year": 2024}) == "2024"

    def test_na_fallback(self):
        assert _fiscal_year_display({}) == "N/A"


class TestRenderMarkdownPeriodDisplay:
    def test_half_year_shown_in_trend_table(self):
        """半期データが Trend Table に '(半期)' 付きで表示される."""
        payload = {
            "ticker": "7685",
            "company_name": "TestCo",
            "generated_at": "2026-02-17T00:00:00+00:00",
            "metrics_series": [
                {
                    "fiscal_year": 2024,
                    "period_months": 12,
                    "revenue": 59973669000.0,
                    "operating_income": 4733796000.0,
                    "net_income": 2411292000.0,
                    "roe_percent": 19.3,
                    "roa_percent": 5.2,
                    "operating_margin_percent": 7.89,
                    "equity_ratio_percent": 26.94,
                    "free_cash_flow": None,
                },
                {
                    "fiscal_year": 2025,
                    "period_months": 6,
                    "revenue": 48013769000.0,
                    "operating_income": 4843786000.0,
                    "net_income": 2789540000.0,
                    "roe_percent": 14.89,
                    "roa_percent": 5.36,
                    "operating_margin_percent": 10.09,
                    "equity_ratio_percent": 35.99,
                    "free_cash_flow": 3798765000.0,
                },
            ],
        }
        md = render_markdown(payload, "7685")
        assert "2025 (半期)" in md
        assert "2024 (通期)" not in md  # 通期は括弧不要
        assert "| 2024 |" in md

    def test_no_period_months_backward_compat(self):
        """period_months がない既存データでも正常描画."""
        payload = {
            "ticker": "7203",
            "company_name": "Sample Co.",
            "generated_at": "2026-02-11T00:00:00+00:00",
            "metrics_series": [
                {
                    "fiscal_year": 2024,
                    "revenue": 100,
                    "operating_income": 10,
                    "net_income": 7,
                    "roe_percent": 8.1,
                    "roa_percent": 3.2,
                    "operating_margin_percent": 10.0,
                    "equity_ratio_percent": 35.0,
                    "free_cash_flow": 4.5,
                }
            ],
        }
        md = render_markdown(payload, "7203")
        assert "| 2024 |" in md
        assert "(半期)" not in md
        assert "(四半期)" not in md

    def test_latest_snapshot_half_year_label(self):
        """最新が半期の場合、Key Metrics に (半期) が付く."""
        payload = {
            "ticker": "7685",
            "company_name": "TestCo",
            "generated_at": "2026-02-17T00:00:00+00:00",
            "metrics_series": [
                {
                    "fiscal_year": 2025,
                    "period_months": 6,
                    "revenue": 48013769000.0,
                    "operating_income": 4843786000.0,
                    "net_income": 2789540000.0,
                    "roe_percent": 14.89,
                    "roa_percent": 5.36,
                    "operating_margin_percent": 10.09,
                    "equity_ratio_percent": 35.99,
                    "free_cash_flow": 3798765000.0,
                },
            ],
        }
        md = render_markdown(payload, "7685")
        assert "売上高 (半期)" in md
        assert "当期純利益 (半期)" in md
        assert "フリーキャッシュフロー (半期)" in md


# ===================================================================
# confirmed_absent / absence_map tests
# ===================================================================

class TestBuildAbsenceMap:
    def test_extracts_confirmed_absent(self):
        """t1_judgment: confirmed_absent のフィールドが抽出される."""
        recon = {
            "comparisons": [
                {
                    "period_end": "2024-06-30",
                    "fields": {
                        "total_assets": {
                            "match": "EDINET_NULL",
                            "t1_judgment": "confirmed_absent",
                            "reason": "半期BSに前中間末列なし",
                        },
                        "equity": {
                            "match": "EDINET_NULL",
                            "t1_judgment": "confirmed_absent",
                            "t1_reason": "半期BSに純資産列なし",
                        },
                        "revenue": {
                            "match": "MATCH",
                            "edinet": 100,
                            "jquants": 100,
                        },
                    },
                }
            ]
        }
        absence = build_absence_map(recon)
        assert "2024-06-30" in absence
        assert "total_assets" in absence["2024-06-30"]
        assert "equity" in absence["2024-06-30"]
        assert "revenue" not in absence["2024-06-30"]
        assert absence["2024-06-30"]["total_assets"] == "半期BSに前中間末列なし"
        # t1_reason fallback
        assert absence["2024-06-30"]["equity"] == "半期BSに純資産列なし"

    def test_empty_when_no_confirmed_absent(self):
        recon = {
            "comparisons": [
                {
                    "period_end": "2024-12-31",
                    "fields": {
                        "revenue": {"match": "MATCH", "edinet": 100, "jquants": 100},
                    },
                }
            ]
        }
        assert build_absence_map(recon) == {}

    def test_empty_reconciliation(self):
        assert build_absence_map({}) == {}
        assert build_absence_map({"comparisons": []}) == {}


class TestConfirmedAbsentRendering:
    """confirmed_absent null と通常 null の表示が区別されることを検証."""

    _PAYLOAD = {
        "ticker": "7685",
        "company_name": "TestCo",
        "generated_at": "2026-02-17T00:00:00+00:00",
        "metrics_series": [
            {
                "fiscal_year": 2024,
                "revenue": 59973669000.0,
                "operating_income": 4733796000.0,
                "net_income": None,  # uncollected → N/A
                "roe_percent": None,
                "roa_percent": None,
                "operating_margin_percent": 7.89,
                "equity_ratio_percent": None,  # confirmed_absent field
                "free_cash_flow": None,  # confirmed_absent field
            },
        ],
    }

    _ABSENCE_MAP = {
        "2024-06-30": {
            "equity_ratio_percent": "半期BSに前中間末列なし",
            "free_cash_flow": "四半期報告書にCF計算書なし",
        },
    }

    def test_confirmed_absent_shows_dagger(self):
        md = render_markdown(self._PAYLOAD, "7685", absence_map=self._ABSENCE_MAP)
        # equity_ratio_percent and free_cash_flow are null + confirmed_absent → —†
        assert "\u2014\u2020" in md  # —†

    def test_uncollected_null_shows_na(self):
        md = render_markdown(self._PAYLOAD, "7685", absence_map=self._ABSENCE_MAP)
        # net_income is null + NOT confirmed_absent → N/A
        assert "N/A" in md

    def test_data_quality_notes_section(self):
        md = render_markdown(self._PAYLOAD, "7685", absence_map=self._ABSENCE_MAP)
        assert "## データ品質に関する注記" in md
        assert "確認済み不在" in md
        assert "半期BSに前中間末列なし" in md
        assert "四半期報告書にCF計算書なし" in md

    def test_no_absence_map_backward_compat(self):
        """absence_map なしでは従来通り N/A 表示のみ."""
        md = render_markdown(self._PAYLOAD, "7685")
        assert "\u2014\u2020" not in md
        assert "データ品質に関する注記" not in md
        assert "N/A" in md


# ===================================================================
# Number format tests
# ===================================================================

class TestFmtValue:
    def test_raw_default(self):
        assert _fmt_value(1234567890.0) == "1234567890.00"

    def test_man_yen_monetary(self):
        result = _fmt_value(
            59973669000.0, number_format="man_yen", is_monetary=True
        )
        assert result == "59,974"

    def test_oku_yen_monetary(self):
        result = _fmt_value(
            59973669000.0, number_format="oku_yen", is_monetary=True
        )
        assert result == "599.7"

    def test_non_monetary_ignores_format(self):
        """Ratio fields are not affected by number_format."""
        result = _fmt_value(8.1, "%", number_format="man_yen", is_monetary=False)
        assert result == "8.10%"

    def test_none_returns_na(self):
        assert _fmt_value(None) == "N/A"

    def test_none_with_absence_returns_dagger(self):
        assert _fmt_value(None, absence_reason="理由あり") == "\u2014\u2020"

    def test_numeric_ignores_absence(self):
        """数値がある場合は absence_reason があっても数値を表示."""
        result = _fmt_value(100.0, absence_reason="理由あり")
        assert result == "100.00"


class TestNumberFormatRendering:
    _PAYLOAD = {
        "ticker": "7685",
        "company_name": "TestCo",
        "generated_at": "2026-02-17T00:00:00+00:00",
        "metrics_series": [
            {
                "fiscal_year": 2024,
                "revenue": 59973669000.0,
                "operating_income": 4733796000.0,
                "net_income": 2411292000.0,
                "roe_percent": 19.3,
                "roa_percent": 5.2,
                "operating_margin_percent": 7.89,
                "equity_ratio_percent": 26.94,
                "free_cash_flow": 3798765000.0,
            },
        ],
    }

    def test_raw_format_default(self):
        md = render_markdown(self._PAYLOAD, "7685")
        assert "59973669000.00" in md
        assert "(百万円)" not in md
        assert "(億円)" not in md

    def test_man_yen_format(self):
        md = render_markdown(self._PAYLOAD, "7685", number_format="man_yen")
        assert "(百万円)" in md
        assert "59,974" in md  # revenue in millions
        # Ratio fields unchanged
        assert "19.30" in md  # ROE

    def test_oku_yen_format(self):
        md = render_markdown(self._PAYLOAD, "7685", number_format="oku_yen")
        assert "(億円)" in md
        assert "599.7" in md  # revenue in billions

    def test_raw_backward_compat(self):
        """number_format=raw は既存出力と同一."""
        md_default = render_markdown(self._PAYLOAD, "7685")
        md_raw = render_markdown(self._PAYLOAD, "7685", number_format="raw")
        assert md_default == md_raw


class TestNumberFormatCli:
    """CLI --number-format / --reconciliation の統合テスト."""

    def test_man_yen_via_cli(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "main.py"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            metrics_path = tmp_path / "metrics.json"
            output_md = tmp_path / "out.md"
            output_html = tmp_path / "out.html"

            payload = {
                "ticker": "7685",
                "company_name": "TestCo",
                "generated_at": "2026-02-17T00:00:00+00:00",
                "metrics_series": [
                    {
                        "fiscal_year": 2024,
                        "revenue": 59973669000.0,
                        "operating_income": 4733796000.0,
                        "net_income": 2411292000.0,
                        "roe_percent": 19.3,
                        "roa_percent": 5.2,
                        "operating_margin_percent": 7.89,
                        "equity_ratio_percent": 26.94,
                        "free_cash_flow": 3798765000.0,
                    }
                ],
            }
            metrics_path.write_text(json.dumps(payload), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable, str(script),
                    "--ticker", "7685",
                    "--metrics", str(metrics_path),
                    "--output-md", str(output_md),
                    "--output-html", str(output_html),
                    "--number-format", "man_yen",
                ],
                check=False, capture_output=True, text=True,
            )

            assert result.returncode == 0, result.stderr
            md_text = output_md.read_text(encoding="utf-8")
            assert "(百万円)" in md_text
            assert "59,974" in md_text

    def test_reconciliation_via_cli(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "main.py"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            metrics_path = tmp_path / "metrics.json"
            recon_path = tmp_path / "reconciliation.json"
            output_md = tmp_path / "out.md"
            output_html = tmp_path / "out.html"

            payload = {
                "ticker": "7685",
                "company_name": "TestCo",
                "generated_at": "2026-02-17T00:00:00+00:00",
                "metrics_series": [
                    {
                        "fiscal_year": 2024,
                        "revenue": 100.0,
                        "operating_income": 10.0,
                        "net_income": None,
                        "roe_percent": None,
                        "roa_percent": None,
                        "operating_margin_percent": 10.0,
                        "equity_ratio_percent": None,
                        "free_cash_flow": None,
                    }
                ],
            }
            recon = {
                "comparisons": [
                    {
                        "period_end": "2024-06-30",
                        "fields": {
                            "equity_ratio_percent": {
                                "match": "EDINET_NULL",
                                "t1_judgment": "confirmed_absent",
                                "reason": "半期BSなし",
                            },
                        },
                    }
                ]
            }
            metrics_path.write_text(json.dumps(payload), encoding="utf-8")
            recon_path.write_text(json.dumps(recon), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable, str(script),
                    "--ticker", "7685",
                    "--metrics", str(metrics_path),
                    "--reconciliation", str(recon_path),
                    "--output-md", str(output_md),
                    "--output-html", str(output_html),
                ],
                check=False, capture_output=True, text=True,
            )

            assert result.returncode == 0, result.stderr
            md_text = output_md.read_text(encoding="utf-8")
            assert "データ品質に関する注記" in md_text
            assert "\u2014\u2020" in md_text  # —†
            assert "半期BSなし" in md_text


# ===================================================================
# Fiscal year end month inference + period matching tests
# ===================================================================

class TestInferFyEndMonth:
    def test_december_end(self):
        recon = {
            "comparisons": [
                {"period_end": "2024-12-31", "jquants_period_type": "FY"},
            ]
        }
        assert infer_fy_end_month(recon) == 12

    def test_march_end(self):
        recon = {
            "comparisons": [
                {"period_end": "2024-06-30", "jquants_period_type": "1Q"},
                {"period_end": "2025-03-31", "jquants_period_type": "FY"},
            ]
        }
        assert infer_fy_end_month(recon) == 3

    def test_june_end(self):
        recon = {
            "comparisons": [
                {"period_end": "2025-06-30", "jquants_period_type": "FY"},
            ]
        }
        assert infer_fy_end_month(recon) == 6

    def test_default_when_no_fy(self):
        recon = {
            "comparisons": [
                {"period_end": "2024-06-30", "jquants_period_type": "2Q"},
            ]
        }
        assert infer_fy_end_month(recon) == 12

    def test_empty(self):
        assert infer_fy_end_month({}) == 12


class TestPeriodInFiscalYear:
    """_period_in_fiscal_year の境界テスト."""

    # --- December end ---
    def test_dec_fy_match(self):
        assert _period_in_fiscal_year("2024-12-31", 2024, 12) is True

    def test_dec_q1_match(self):
        assert _period_in_fiscal_year("2024-03-31", 2024, 12) is True

    def test_dec_previous_year_no_match(self):
        assert _period_in_fiscal_year("2023-12-31", 2024, 12) is False

    def test_dec_next_year_no_match(self):
        assert _period_in_fiscal_year("2025-01-01", 2024, 12) is False

    # --- March end (3月決算) ---
    def test_mar_fy_end_match(self):
        """FY2024 ends 2024-03-31."""
        assert _period_in_fiscal_year("2024-03-31", 2024, 3) is True

    def test_mar_q1_match(self):
        """Q1 of FY2024 ends 2023-06-30."""
        assert _period_in_fiscal_year("2023-06-30", 2024, 3) is True

    def test_mar_q2_match(self):
        """Q2 of FY2024 ends 2023-09-30."""
        assert _period_in_fiscal_year("2023-09-30", 2024, 3) is True

    def test_mar_q3_match(self):
        """Q3 of FY2024 ends 2023-12-31."""
        assert _period_in_fiscal_year("2023-12-31", 2024, 3) is True

    def test_mar_prev_fy_no_match(self):
        """2023-03-31 is FY2023, not FY2024."""
        assert _period_in_fiscal_year("2023-03-31", 2024, 3) is False

    def test_mar_next_fy_start_no_match(self):
        """2024-04-01 is start of FY2025."""
        assert _period_in_fiscal_year("2024-04-01", 2024, 3) is False

    # --- June end (6月決算) ---
    def test_jun_fy_end_match(self):
        """FY2025 ends 2025-06-30."""
        assert _period_in_fiscal_year("2025-06-30", 2025, 6) is True

    def test_jun_q1_match(self):
        """Q1 of FY2025 ends 2024-09-30."""
        assert _period_in_fiscal_year("2024-09-30", 2025, 6) is True

    def test_jun_q3_match(self):
        """Q3 of FY2025 ends 2025-03-31."""
        assert _period_in_fiscal_year("2025-03-31", 2025, 6) is True

    def test_jun_prev_fy_no_match(self):
        """2024-06-30 is FY2024, not FY2025."""
        assert _period_in_fiscal_year("2024-06-30", 2025, 6) is False

    # --- Invalid input ---
    def test_invalid_date_string(self):
        assert _period_in_fiscal_year("invalid", 2024, 12) is False

    def test_empty_string(self):
        assert _period_in_fiscal_year("", 2024, 12) is False


class TestRowAbsenceWithFyEndMonth:
    """_row_absence が fy_end_month を正しく使用することを検証."""

    _ABSENCE_MAP = {
        "2023-09-30": {"total_assets": "3月決算Q2のBS列なし"},
        "2024-03-31": {"equity": "通期BSなし"},
    }

    def test_march_end_fy2024_matches_both(self):
        """3月決算 FY2024 (2023-04 to 2024-03) → 両方マッチ."""
        row = {"fiscal_year": 2024}
        result = _row_absence(row, self._ABSENCE_MAP, fy_end_month=3)
        assert "total_assets" in result
        assert "equity" in result

    def test_december_end_fy2024_matches_only_march(self):
        """12月決算 FY2024 → 2024-03-31 のみマッチ (2023-09-30 は FY2023)."""
        row = {"fiscal_year": 2024}
        result = _row_absence(row, self._ABSENCE_MAP, fy_end_month=12)
        assert "total_assets" not in result
        assert "equity" in result

    def test_december_end_fy2023_matches_only_sep(self):
        """12月決算 FY2023 → 2023-09-30 のみマッチ."""
        row = {"fiscal_year": 2023}
        result = _row_absence(row, self._ABSENCE_MAP, fy_end_month=12)
        assert "total_assets" in result
        assert "equity" not in result


class TestMarchEndRendering:
    """3月決算企業の統合レンダリング回帰テスト."""

    _PAYLOAD = {
        "ticker": "7203",
        "company_name": "トヨタ自動車",
        "generated_at": "2026-02-17T00:00:00+00:00",
        "metrics_series": [
            {
                "fiscal_year": 2024,
                "revenue": 45095325000000.0,
                "operating_income": 5352934000000.0,
                "net_income": None,  # confirmed_absent for this FY
                "roe_percent": None,
                "roa_percent": None,
                "operating_margin_percent": 11.87,
                "equity_ratio_percent": 38.0,
                "free_cash_flow": None,
            },
        ],
    }

    _ABSENCE_MAP = {
        # Q2 of FY2024 (3月決算) → period 2023-09-30
        "2023-09-30": {
            "net_income": "四半期報告書に累計純利益なし",
        },
    }

    def test_march_end_absence_detected(self):
        """3月決算でQ2 period_end(2023-09-30)がFY2024にマッチ."""
        md = render_markdown(
            self._PAYLOAD, "7203",
            absence_map=self._ABSENCE_MAP, fy_end_month=3,
        )
        assert "\u2014\u2020" in md  # —†
        assert "データ品質に関する注記" in md
        assert "四半期報告書に累計純利益なし" in md

    def test_march_end_wrong_fy_end_month_misses(self):
        """fy_end_month=12 だと 2023-09-30 は FY2023 扱いで FY2024 にマッチしない."""
        md = render_markdown(
            self._PAYLOAD, "7203",
            absence_map=self._ABSENCE_MAP, fy_end_month=12,
        )
        # net_income is still None → shows N/A (not —†)
        lines = md.split("\n")
        trend_rows = [l for l in lines if l.startswith("| 2024")]
        assert len(trend_rows) == 1
        assert "N/A" in trend_rows[0]
        assert "\u2014\u2020" not in trend_rows[0]


# ===================================================================
# Ratio field exclusion specification (仕様固定)
# ===================================================================

class TestMonetaryFieldsBoundary:
    """_MONETARY_FIELDS の範囲が仕様として固定されていることを検証."""

    _EXPECTED_MONETARY = {"revenue", "operating_income", "net_income", "free_cash_flow"}
    _RATIO_FIELDS = {
        "roe_percent", "roa_percent", "operating_margin_percent",
        "equity_ratio_percent",
    }

    def test_monetary_fields_exact_set(self):
        """金額フィールドは正確にこの4つ."""
        assert set(_MONETARY_FIELDS) == self._EXPECTED_MONETARY

    def test_ratio_fields_not_in_monetary(self):
        """比率フィールドは _MONETARY_FIELDS に含まれない."""
        for field in self._RATIO_FIELDS:
            assert field not in _MONETARY_FIELDS, f"{field} should NOT be monetary"

    def test_all_ratio_fields_unchanged_with_man_yen(self):
        """man_yen モードで全比率フィールドが生数値のまま表示される."""
        payload = {
            "ticker": "TEST",
            "company_name": "Test",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "metrics_series": [
                {
                    "fiscal_year": 2024,
                    "revenue": 1000000000.0,
                    "operating_income": 100000000.0,
                    "net_income": 50000000.0,
                    "roe_percent": 12.34,
                    "roa_percent": 5.67,
                    "operating_margin_percent": 10.00,
                    "equity_ratio_percent": 45.50,
                    "free_cash_flow": 80000000.0,
                }
            ],
        }
        md = render_markdown(payload, "TEST", number_format="man_yen")
        # Ratio values must appear exactly as raw .2f
        assert "12.34%" in md  # ROE
        assert "5.67%" in md   # ROA
        assert "10.00%" in md  # Operating Margin
        assert "45.50%" in md  # Equity Ratio

    def test_all_ratio_fields_unchanged_with_oku_yen(self):
        """oku_yen モードでも全比率フィールドが生数値のまま表示される."""
        payload = {
            "ticker": "TEST",
            "company_name": "Test",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "metrics_series": [
                {
                    "fiscal_year": 2024,
                    "revenue": 1000000000.0,
                    "operating_income": 100000000.0,
                    "net_income": 50000000.0,
                    "roe_percent": 12.34,
                    "roa_percent": 5.67,
                    "operating_margin_percent": 10.00,
                    "equity_ratio_percent": 45.50,
                    "free_cash_flow": 80000000.0,
                }
            ],
        }
        md = render_markdown(payload, "TEST", number_format="oku_yen")
        assert "12.34%" in md
        assert "5.67%" in md
        assert "10.00%" in md
        assert "45.50%" in md
