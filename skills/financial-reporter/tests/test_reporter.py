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
    _compute_dcf_equity,
    _fiscal_year_display,
    _fmt_value,
    _max_severity,
    _period_in_fiscal_year,
    _period_label,
    _row_absence,
    build_absence_map,
    infer_fy_end_month,
    render_html,
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


def test_resolve_company_name_from_parsed_dir() -> None:
    """company_name resolved from parsed/ directory."""
    script = Path(__file__).resolve().parents[1] / "scripts" / "main.py"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        ticker = "8888"
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
            "company_name": "プロセス株式会社",
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


# ===================================================================
# Valuation section tests
# ===================================================================

_BASE_METRICS_PAYLOAD = {
    "ticker": "9743",
    "company_name": "丹青社",
    "generated_at": "2026-02-27T00:00:00+00:00",
    "metrics_series": [
        {
            "fiscal_year": 2025,
            "revenue": 80000000000.0,
            "operating_income": 6000000000.0,
            "net_income": 4000000000.0,
            "roe_percent": 14.0,
            "roa_percent": 6.2,
            "operating_margin_percent": 7.5,
            "equity_ratio_percent": 40.0,
            "free_cash_flow": 4500000000.0,
        }
    ],
}

_DCF_DATA = {
    "ticker": "9743",
    "valuation_type": "dcf",
    "enterprise_value": 102115349771.21,
    "equity_value": 97115349771.21,
    "per_share_value": 1942.31,
    "assumptions": {
        "wacc": 0.08,
        "terminal_growth_rate": 0.02,
        "projection_years": 5,
        "base_fcf": 4500000000.0,
        "estimated_growth_rate": 0.08738,
        "net_debt": 5000000000.0,
        "shares_outstanding": 50000000.0,
    },
}

_RELATIVE_SIMPLE = {
    "ticker": "9743",
    "valuation_type": "relative",
    "per": 12.5,
    "pbr": 1.67,
    "ev_ebitda": 7.86,
}

_RELATIVE_WITH_PEERS = {
    "ticker": "9743",
    "valuation_type": "relative",
    "target": {"ticker": "9743", "per": 10.0, "pbr": 1.67, "ev_ebitda": 6.88},
    "peers": [
        {"ticker": "4680", "per": 8.0, "pbr": 1.6, "ev_ebitda": 5.5},
        {"ticker": "2327", "per": 15.0, "pbr": 3.0, "ev_ebitda": 9.2},
    ],
    "comparison": {
        "per": {
            "target": 10.0,
            "peer_median": 11.5,
            "peer_average": 11.5,
            "vs_median": -1.5,
            "vs_average": -1.5,
        },
        "pbr": {
            "target": 1.67,
            "peer_median": 2.3,
            "peer_average": 2.3,
            "vs_median": -0.63,
            "vs_average": -0.63,
        },
        "ev_ebitda": {
            "target": 6.88,
            "peer_median": 7.35,
            "peer_average": 7.35,
            "vs_median": -0.47,
            "vs_average": -0.47,
        },
    },
}

_RISK_DATA = {
    "ticker": "9743",
    "analyzed_at": "2026-02-27T14:30:00+00:00",
    "source_documents": ["S100TEST"],
    "risk_categories": {
        "market_risk": [
            {
                "text": "為替リスクについて\n当社は海外事業を展開しており影響を受ける可能性があります。",
                "source": "S100TEST",
                "severity": "high",
            }
        ],
        "credit_risk": [
            {
                "text": "取引先の信用リスクにより売掛金回収が困難になる可能性があります。",
                "source": "S100TEST",
                "severity": "medium",
            }
        ],
        "operational_risk": [
            {
                "text": "情報セキュリティリスクにより事業運営に限定的な影響が生じる可能性。",
                "source": "S100TEST",
                "severity": "low",
            }
        ],
        "regulatory_risk": [
            {
                "text": "法令改正に伴いコンプライアンス体制の強化が求められる可能性があります。",
                "source": "S100TEST",
                "severity": "medium",
            }
        ],
        "other_risk": [],
    },
    "summary": {
        "total_risks": 4,
        "by_category": {
            "market_risk": 1,
            "credit_risk": 1,
            "operational_risk": 1,
            "regulatory_risk": 1,
            "other_risk": 0,
        },
        "by_severity": {"high": 1, "medium": 2, "low": 1},
    },
}


class TestValuationDcfSection:
    """DCF バリュエーションセクションのレンダリングテスト."""

    def test_dcf_section_rendered(self):
        """DCF データ指定時にバリュエーション分析セクションが出力される."""
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743",
            valuation_data={"dcf": _DCF_DATA, "relative": None},
        )
        assert "## バリュエーション分析" in md
        assert "### DCF 評価" in md
        assert "1,021.2" in md  # enterprise_value in 億円
        assert "971.2" in md    # equity_value in 億円
        assert "1,942" in md    # per_share_value

    def test_dcf_assumptions_rendered(self):
        """DCF 前提条件が出力される."""
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743",
            valuation_data={"dcf": _DCF_DATA, "relative": None},
        )
        assert "WACC: 8.0%" in md
        assert "永久成長率: 2.0%" in md
        assert "予測期間: 5年" in md
        assert "ベースFCF:" in md
        assert "推定FCF成長率:" in md

    def test_sensitivity_table_rendered(self):
        """感度分析テーブルが出力される."""
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743",
            valuation_data={"dcf": _DCF_DATA, "relative": None},
        )
        assert "感度分析" in md
        assert "WACC＼永久成長率" in md
        # Check WACC steps appear: 6.0%, 7.0%, 8.0%, 9.0%, 10.0%
        assert "6.0%" in md
        assert "10.0%" in md

    def test_per_share_value_null_shows_na(self):
        """per_share_value が null の場合 N/A 表示."""
        dcf_no_shares = {**_DCF_DATA, "per_share_value": None}
        dcf_no_shares["assumptions"] = {
            **_DCF_DATA["assumptions"],
            "shares_outstanding": None,
        }
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743",
            valuation_data={"dcf": dcf_no_shares, "relative": None},
        )
        assert "理論株価: N/A" in md
        # Sensitivity uses 億円 instead of per-share
        assert "株式価値 億円" in md

    def test_valuation_section_before_annual_table(self):
        """バリュエーション分析セクションが主要指標の後、通期推移表の前に配置される."""
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743",
            valuation_data={"dcf": _DCF_DATA, "relative": None},
        )
        idx_key_metrics = md.index("## 主要指標")
        idx_valuation = md.index("## バリュエーション分析")
        idx_annual = md.index("## 通期推移表")
        assert idx_key_metrics < idx_valuation < idx_annual


class TestValuationRelativeSection:
    """相対バリュエーションセクションのレンダリングテスト."""

    def test_simple_relative_rendered(self):
        """ピアなし相対バリュエーションが表示される."""
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743",
            valuation_data={"dcf": None, "relative": _RELATIVE_SIMPLE},
        )
        assert "### 相対バリュエーション" in md
        assert "PER" in md
        assert "12.50" in md
        assert "PBR" in md
        assert "1.67" in md
        assert "EV/EBITDA" in md
        assert "7.86" in md

    def test_peer_comparison_rendered(self):
        """ピアありの相対バリュエーション比較テーブルが表示される."""
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743",
            valuation_data={"dcf": None, "relative": _RELATIVE_WITH_PEERS},
        )
        assert "ピア中央値" in md
        assert "ピア平均" in md
        assert "vs 中央値" in md
        assert "-1.50" in md  # PER vs_median

    def test_both_dcf_and_relative(self):
        """DCF と相対バリュエーション両方が表示される."""
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743",
            valuation_data={"dcf": _DCF_DATA, "relative": _RELATIVE_SIMPLE},
        )
        assert "### DCF 評価" in md
        assert "### 相対バリュエーション" in md

    def test_valuation_source_traceability(self):
        """バリュエーションセクションに出典情報が表示される."""
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743",
            valuation_data={"dcf": _DCF_DATA, "relative": None},
        )
        assert "出典情報" in md
        assert "DCF: valuation-calculator 出力" in md


class TestValuationGracefulDegradation:
    """バリュエーションデータなし時の graceful degradation テスト."""

    def test_no_valuation_data_omits_section(self):
        """valuation_data=None ではバリュエーション分析セクション見出し省略."""
        md = render_markdown(_BASE_METRICS_PAYLOAD, "9743")
        assert "## バリュエーション分析" not in md
        # 警告文は表示される
        assert "バリュエーション分析データが未指定" in md

    def test_empty_valuation_dict_omits_section(self):
        """dcf=None, relative=None ではセクション見出し省略."""
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743",
            valuation_data={"dcf": None, "relative": None},
        )
        assert "## バリュエーション分析" not in md

    def test_backward_compat_no_valuation(self):
        """valuation_data 未指定の既存呼び出しが正常動作."""
        md_old = render_markdown(_BASE_METRICS_PAYLOAD, "9743")
        assert "## 主要指標" in md_old
        assert "## 通期推移表" in md_old


# ===================================================================
# Risk section tests
# ===================================================================

class TestRiskSection:
    """リスク分析セクションのレンダリングテスト."""

    def test_risk_section_rendered(self):
        """risk_data 指定時にリスク分析セクションが出力される."""
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743", risk_data=_RISK_DATA,
        )
        assert "## リスク分析" in md

    def test_risk_summary_counts(self):
        """リスク総数と severity 内訳が表示される."""
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743", risk_data=_RISK_DATA,
        )
        assert "4件" in md
        assert "高: 1" in md
        assert "中: 2" in md
        assert "低: 1" in md

    def test_risk_categories_in_table(self):
        """カテゴリ別テーブルが表示される."""
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743", risk_data=_RISK_DATA,
        )
        assert "市場リスク" in md
        assert "信用リスク" in md
        assert "オペレーショナルリスク" in md
        assert "規制リスク" in md

    def test_required_5_categories_always_shown(self):
        """要件定義の5カテゴリが必ず表示される (liquidity含む)."""
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743", risk_data=_RISK_DATA,
        )
        assert "流動性リスク" in md
        # liquidity_risk has no data → shows (該当データなし)
        lines = md.split("\n")
        liq_line = [l for l in lines if "流動性リスク" in l][0]
        assert "該当データなし" in liq_line
        assert "| 0 |" in liq_line

    def test_empty_extra_category_skipped(self):
        """件数0の追加カテゴリ (other_risk) はテーブルに含まれない."""
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743", risk_data=_RISK_DATA,
        )
        assert "その他リスク" not in md

    def test_other_risk_shown_when_items_exist(self):
        """other_risk にアイテムがある場合は表示される."""
        risk_with_other = {
            **_RISK_DATA,
            "risk_categories": {
                **_RISK_DATA["risk_categories"],
                "other_risk": [
                    {"text": "その他のリスク要因", "source": "S100", "severity": "medium"}
                ],
            },
        }
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743", risk_data=risk_with_other,
        )
        assert "その他リスク" in md

    def test_risk_section_before_data_sources(self):
        """リスク分析セクションがデータソースの前に配置される."""
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743", risk_data=_RISK_DATA,
        )
        idx_risk = md.index("## リスク分析")
        idx_datasrc = md.index("## データソース")
        assert idx_risk < idx_datasrc

    def test_severity_level_per_category(self):
        """各カテゴリの最大 severity がテーブルに表示される."""
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743", risk_data=_RISK_DATA,
        )
        lines = md.split("\n")
        market_line = [l for l in lines if "市場リスク" in l][0]
        assert "高" in market_line
        op_line = [l for l in lines if "オペレーショナルリスク" in l][0]
        assert "低" in op_line

    def test_risk_source_traceability(self):
        """リスク分析セクションに出典情報が表示される."""
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743", risk_data=_RISK_DATA,
        )
        assert "出典情報" in md
        assert "分析日時:" in md
        assert "2026-02-27T14:30:00+00:00" in md
        assert "参照文書:" in md
        assert "S100TEST" in md


class TestRiskGracefulDegradation:
    """リスクデータなし時の graceful degradation テスト."""

    def test_no_risk_data_omits_section(self):
        """risk_data=None ではリスク分析セクション省略."""
        md = render_markdown(_BASE_METRICS_PAYLOAD, "9743")
        assert "## リスク分析" not in md
        # 警告文は表示される
        assert "リスク分析データが未指定" in md

    def test_backward_compat_no_risk(self):
        """risk_data 未指定の既存呼び出しが正常動作."""
        md = render_markdown(_BASE_METRICS_PAYLOAD, "9743")
        assert "## データソース" in md


# ===================================================================
# Valuation + Risk integration tests
# ===================================================================

class TestDataAbsenceWarnings:
    """データ未指定時の警告表示テスト."""

    def test_both_absent_warnings(self):
        """valuation/risk 未指定で両方の警告が出る."""
        md = render_markdown(_BASE_METRICS_PAYLOAD, "9743")
        assert "バリュエーション分析データが未指定" in md
        assert "リスク分析データが未指定" in md
        assert "--valuation" in md
        assert "--risk" in md

    def test_valuation_present_no_warning(self):
        """valuation 指定時はバリュエーション警告が出ない."""
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743",
            valuation_data={"dcf": _DCF_DATA, "relative": None},
        )
        assert "バリュエーション分析データが未指定" not in md
        # risk 警告は出る
        assert "リスク分析データが未指定" in md

    def test_risk_present_no_warning(self):
        """risk 指定時はリスク警告が出ない."""
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743",
            risk_data=_RISK_DATA,
        )
        assert "リスク分析データが未指定" not in md
        # valuation 警告は出る
        assert "バリュエーション分析データが未指定" in md

    def test_both_present_no_warnings(self):
        """valuation/risk 両方指定で警告が出ない."""
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743",
            valuation_data={"dcf": _DCF_DATA, "relative": None},
            risk_data=_RISK_DATA,
        )
        assert "バリュエーション分析データが未指定" not in md
        assert "リスク分析データが未指定" not in md


class TestValuationRiskIntegration:
    """valuation + risk 両方指定時の統合テスト."""

    def test_both_sections_present(self):
        """valuation と risk 両方のセクションが出力される."""
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743",
            valuation_data={"dcf": _DCF_DATA, "relative": _RELATIVE_SIMPLE},
            risk_data=_RISK_DATA,
        )
        assert "## バリュエーション分析" in md
        assert "## リスク分析" in md

    def test_section_order(self):
        """セクション順序: 主要指標 → バリュエーション → 通期推移表 → リスク → データソース."""
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743",
            valuation_data={"dcf": _DCF_DATA, "relative": _RELATIVE_SIMPLE},
            risk_data=_RISK_DATA,
        )
        idx = [
            md.index("## 主要指標"),
            md.index("## バリュエーション分析"),
            md.index("## 通期推移表"),
            md.index("## リスク分析"),
            md.index("## データソース"),
        ]
        assert idx == sorted(idx)

    def test_html_output_with_both(self):
        """HTML 出力でも valuation/risk セクションが正しくレンダリングされる."""
        md = render_markdown(
            _BASE_METRICS_PAYLOAD, "9743",
            valuation_data={"dcf": _DCF_DATA, "relative": _RELATIVE_SIMPLE},
            risk_data=_RISK_DATA,
        )
        html = render_html(md, "9743 分析レポート")
        assert "<table>" in html
        assert "バリュエーション分析" in html
        assert "リスク分析" in html
        assert "DCF 評価" in html


# ===================================================================
# Valuation/Risk helper unit tests
# ===================================================================

class TestComputeDcfEquity:
    """_compute_dcf_equity の単体テスト."""

    def test_basic_computation(self):
        """基本的なDCF計算が正の値を返す."""
        eq = _compute_dcf_equity(
            base_fcf=4500000000.0,
            growth=0.08738,
            wacc=0.08,
            terminal_growth=0.02,
            years=5,
            net_debt=5000000000.0,
        )
        assert eq is not None
        assert eq > 0

    def test_wacc_equals_growth_returns_none(self):
        """WACC == terminal_growth では None を返す."""
        eq = _compute_dcf_equity(
            base_fcf=1e9, growth=0.05, wacc=0.05,
            terminal_growth=0.05, years=5, net_debt=0,
        )
        assert eq is None

    def test_wacc_less_than_growth_returns_none(self):
        """WACC < terminal_growth では None を返す."""
        eq = _compute_dcf_equity(
            base_fcf=1e9, growth=0.05, wacc=0.03,
            terminal_growth=0.05, years=5, net_debt=0,
        )
        assert eq is None

    def test_higher_wacc_lower_value(self):
        """WACC が高いほど株式価値が下がる."""
        eq_low = _compute_dcf_equity(
            base_fcf=1e9, growth=0.05, wacc=0.06,
            terminal_growth=0.02, years=5, net_debt=0,
        )
        eq_high = _compute_dcf_equity(
            base_fcf=1e9, growth=0.05, wacc=0.10,
            terminal_growth=0.02, years=5, net_debt=0,
        )
        assert eq_low > eq_high


class TestMaxSeverity:
    """_max_severity の単体テスト."""

    def test_high_wins(self):
        items = [
            {"severity": "low"},
            {"severity": "high"},
            {"severity": "medium"},
        ]
        assert _max_severity(items) == "high"

    def test_all_low(self):
        items = [{"severity": "low"}, {"severity": "low"}]
        assert _max_severity(items) == "low"

    def test_default_medium(self):
        """severity フィールドがない場合は medium 扱い."""
        items = [{"text": "something"}]
        assert _max_severity(items) == "medium"

    def test_empty_list(self):
        assert _max_severity([]) == "low"


# ===================================================================
# CLI integration tests for --valuation and --risk
# ===================================================================

class TestValuationRiskCli:
    """CLI --valuation / --risk の統合テスト."""

    def test_valuation_via_cli(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "main.py"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            metrics_path = tmp_path / "metrics.json"
            valuation_dir = tmp_path / "valuation"
            valuation_dir.mkdir()
            dcf_path = valuation_dir / "dcf.json"
            output_md = tmp_path / "out.md"
            output_html = tmp_path / "out.html"

            metrics_path.write_text(
                json.dumps(_BASE_METRICS_PAYLOAD), encoding="utf-8"
            )
            dcf_path.write_text(json.dumps(_DCF_DATA), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable, str(script),
                    "--ticker", "9743",
                    "--metrics", str(metrics_path),
                    "--valuation", str(dcf_path),
                    "--output-md", str(output_md),
                    "--output-html", str(output_html),
                ],
                check=False, capture_output=True, text=True,
            )

            assert result.returncode == 0, result.stderr
            md_text = output_md.read_text(encoding="utf-8")
            assert "バリュエーション分析" in md_text
            assert "DCF 評価" in md_text

    def test_risk_via_cli(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "main.py"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            metrics_path = tmp_path / "metrics.json"
            risk_path = tmp_path / "risk_analysis.json"
            output_md = tmp_path / "out.md"
            output_html = tmp_path / "out.html"

            metrics_path.write_text(
                json.dumps(_BASE_METRICS_PAYLOAD), encoding="utf-8"
            )
            risk_path.write_text(json.dumps(_RISK_DATA), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable, str(script),
                    "--ticker", "9743",
                    "--metrics", str(metrics_path),
                    "--risk", str(risk_path),
                    "--output-md", str(output_md),
                    "--output-html", str(output_html),
                ],
                check=False, capture_output=True, text=True,
            )

            assert result.returncode == 0, result.stderr
            md_text = output_md.read_text(encoding="utf-8")
            assert "リスク分析" in md_text
            assert "市場リスク" in md_text

    def test_valuation_auto_discovers_relative(self):
        """--valuation で dcf.json を指定すると同ディレクトリの relative.json も自動検出."""
        script = Path(__file__).resolve().parents[1] / "scripts" / "main.py"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            metrics_path = tmp_path / "metrics.json"
            valuation_dir = tmp_path / "valuation"
            valuation_dir.mkdir()
            output_md = tmp_path / "out.md"
            output_html = tmp_path / "out.html"

            metrics_path.write_text(
                json.dumps(_BASE_METRICS_PAYLOAD), encoding="utf-8"
            )
            (valuation_dir / "dcf.json").write_text(
                json.dumps(_DCF_DATA), encoding="utf-8"
            )
            (valuation_dir / "relative.json").write_text(
                json.dumps(_RELATIVE_SIMPLE), encoding="utf-8"
            )

            result = subprocess.run(
                [
                    sys.executable, str(script),
                    "--ticker", "9743",
                    "--metrics", str(metrics_path),
                    "--valuation", str(valuation_dir / "dcf.json"),
                    "--output-md", str(output_md),
                    "--output-html", str(output_html),
                ],
                check=False, capture_output=True, text=True,
            )

            assert result.returncode == 0, result.stderr
            md_text = output_md.read_text(encoding="utf-8")
            assert "DCF 評価" in md_text
            assert "相対バリュエーション" in md_text

    def test_no_valuation_no_risk_backward_compat(self):
        """--valuation/--risk 未指定で既存動作が保持される."""
        script = Path(__file__).resolve().parents[1] / "scripts" / "main.py"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            metrics_path = tmp_path / "metrics.json"
            output_md = tmp_path / "out.md"
            output_html = tmp_path / "out.html"

            metrics_path.write_text(
                json.dumps(_BASE_METRICS_PAYLOAD), encoding="utf-8"
            )

            result = subprocess.run(
                [
                    sys.executable, str(script),
                    "--ticker", "9743",
                    "--metrics", str(metrics_path),
                    "--output-md", str(output_md),
                    "--output-html", str(output_html),
                ],
                check=False, capture_output=True, text=True,
            )

            assert result.returncode == 0, result.stderr
            md_text = output_md.read_text(encoding="utf-8")
            assert "## バリュエーション分析" not in md_text
            assert "## リスク分析" not in md_text
            assert "主要指標" in md_text
            # 警告文は表示される
            assert "バリュエーション分析データが未指定" in md_text
            assert "リスク分析データが未指定" in md_text

    def test_both_valuation_and_risk_via_cli(self):
        """--valuation + --risk 同時指定の統合テスト."""
        script = Path(__file__).resolve().parents[1] / "scripts" / "main.py"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            metrics_path = tmp_path / "metrics.json"
            dcf_path = tmp_path / "dcf.json"
            risk_path = tmp_path / "risk.json"
            output_md = tmp_path / "out.md"
            output_html = tmp_path / "out.html"

            metrics_path.write_text(
                json.dumps(_BASE_METRICS_PAYLOAD), encoding="utf-8"
            )
            dcf_path.write_text(json.dumps(_DCF_DATA), encoding="utf-8")
            risk_path.write_text(json.dumps(_RISK_DATA), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable, str(script),
                    "--ticker", "9743",
                    "--metrics", str(metrics_path),
                    "--valuation", str(dcf_path),
                    "--risk", str(risk_path),
                    "--output-md", str(output_md),
                    "--output-html", str(output_html),
                ],
                check=False, capture_output=True, text=True,
            )

            assert result.returncode == 0, result.stderr
            md_text = output_md.read_text(encoding="utf-8")
            assert "バリュエーション分析" in md_text
            assert "リスク分析" in md_text
            html_text = output_html.read_text(encoding="utf-8")
            assert "<table>" in html_text
            assert "バリュエーション分析" in html_text
