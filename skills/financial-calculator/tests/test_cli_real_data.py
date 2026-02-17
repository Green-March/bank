"""Integration tests for financial-calculator calculate/report using real 7685 data.

Uses data/7685/processed/financials.json as input.
All assertions use structural or normalized comparison — no exact string matching.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data" / "7685" / "processed"
FINANCIALS_JSON = DATA_DIR / "financials.json"
MAIN_SCRIPT = SKILL_ROOT / "scripts" / "main.py"

sys.path.insert(0, str(SKILL_ROOT))

from scripts.metrics import calculate_metrics_payload, load_financial_records  # noqa: E402
from scripts.report import render_report_markdown  # noqa: E402

pytestmark = pytest.mark.skipif(
    not FINANCIALS_JSON.exists(),
    reason="data/7685/processed/financials.json not found",
)

# ── Shared fixtures ──────────────────────────────────────────────


@pytest.fixture(scope="module")
def records():
    return load_financial_records(parsed_dir=DATA_DIR, ticker="7685")


@pytest.fixture(scope="module")
def metrics_payload():
    return calculate_metrics_payload(parsed_dir=DATA_DIR, ticker="7685")


@pytest.fixture(scope="module")
def report_markdown(metrics_payload):
    return render_report_markdown(metrics_payload=metrics_payload, ticker="7685")


# ── calculate: output structure ──────────────────────────────────


REQUIRED_TOP_KEYS = {
    "ticker",
    "company_name",
    "generated_at",
    "source_count",
    "metrics_series",
    "latest_snapshot",
}

REQUIRED_SERIES_KEYS = {
    "fiscal_year",
    "period",
    "revenue",
    "operating_income",
    "net_income",
    "roe_percent",
    "roa_percent",
    "operating_margin_percent",
    "revenue_growth_yoy_percent",
    "profit_growth_yoy_percent",
    "equity_ratio_percent",
    "operating_cf",
    "free_cash_flow",
}


class TestCalculateStructure:
    def test_top_level_keys(self, metrics_payload):
        assert REQUIRED_TOP_KEYS <= set(metrics_payload.keys())

    def test_ticker_matches(self, metrics_payload):
        assert metrics_payload["ticker"] == "7685"

    def test_source_count_positive(self, metrics_payload):
        assert isinstance(metrics_payload["source_count"], int)
        assert metrics_payload["source_count"] > 0

    def test_metrics_series_non_empty(self, metrics_payload):
        series = metrics_payload["metrics_series"]
        assert isinstance(series, list)
        assert len(series) > 0

    def test_series_entry_keys(self, metrics_payload):
        for entry in metrics_payload["metrics_series"]:
            missing = REQUIRED_SERIES_KEYS - set(entry.keys())
            assert not missing, f"Missing keys: {missing}"

    def test_latest_snapshot_has_required_keys(self, metrics_payload):
        snap = metrics_payload["latest_snapshot"]
        assert isinstance(snap, dict)
        missing = REQUIRED_SERIES_KEYS - set(snap.keys())
        assert not missing, f"Missing keys in latest_snapshot: {missing}"

    def test_series_sorted_by_fiscal_year(self, metrics_payload):
        years = [
            e["fiscal_year"]
            for e in metrics_payload["metrics_series"]
            if e["fiscal_year"] is not None
        ]
        assert years == sorted(years)


# ── calculate: value types ───────────────────────────────────────

NULLABLE_FLOAT_FIELDS = [
    "revenue",
    "operating_income",
    "net_income",
    "roe_percent",
    "roa_percent",
    "operating_margin_percent",
    "revenue_growth_yoy_percent",
    "profit_growth_yoy_percent",
    "equity_ratio_percent",
    "operating_cf",
    "free_cash_flow",
]


class TestCalculateTypes:
    def test_fiscal_year_type(self, metrics_payload):
        for entry in metrics_payload["metrics_series"]:
            fy = entry["fiscal_year"]
            assert fy is None or isinstance(fy, int)

    def test_period_is_string(self, metrics_payload):
        for entry in metrics_payload["metrics_series"]:
            assert isinstance(entry["period"], str)
            assert len(entry["period"]) > 0

    def test_numeric_fields_type(self, metrics_payload):
        for entry in metrics_payload["metrics_series"]:
            for field in NULLABLE_FLOAT_FIELDS:
                value = entry[field]
                assert value is None or isinstance(value, (int, float)), (
                    f"{field} has unexpected type {type(value).__name__}"
                )


# ── calculate: known value spot-checks ───────────────────────────


def _entries_by_fy(metrics_payload, fiscal_year):
    return [
        e
        for e in metrics_payload["metrics_series"]
        if e["fiscal_year"] == fiscal_year
    ]


class TestCalculateKnownValues:
    def test_has_fy2021_revenue(self, metrics_payload):
        entries = _entries_by_fy(metrics_payload, 2021)
        revenues = {e["revenue"] for e in entries if e["revenue"] is not None}
        assert 5_797_577_000.0 in revenues

    def test_has_fy2022_revenue(self, metrics_payload):
        entries = _entries_by_fy(metrics_payload, 2022)
        revenues = {e["revenue"] for e in entries if e["revenue"] is not None}
        assert 6_989_277_000.0 in revenues

    def test_has_fy2025_revenue(self, metrics_payload):
        entries = _entries_by_fy(metrics_payload, 2025)
        revenues = {e["revenue"] for e in entries if e["revenue"] is not None}
        assert 48_013_769_000.0 in revenues

    def test_latest_snapshot_is_last_series_entry(self, metrics_payload):
        series = metrics_payload["metrics_series"]
        snap = metrics_payload["latest_snapshot"]
        assert snap == series[-1]


# ── calculate: metric computations ───────────────────────────────


class TestCalculateComputations:
    def test_operating_margin(self, metrics_payload):
        for entry in metrics_payload["metrics_series"]:
            oi = entry["operating_income"]
            rev = entry["revenue"]
            margin = entry["operating_margin_percent"]
            if oi is not None and rev is not None and rev != 0:
                expected = round((oi / rev) * 100.0, 2)
                assert margin is not None
                assert math.isclose(margin, expected, rel_tol=1e-9), (
                    f"FY{entry['fiscal_year']}: margin expected={expected}, got={margin}"
                )

    def test_roa_range(self, metrics_payload):
        for entry in metrics_payload["metrics_series"]:
            roa = entry["roa_percent"]
            if roa is not None:
                assert -200.0 <= roa <= 200.0, f"ROA {roa}% out of plausible range"

    def test_revenue_growth_sign(self, metrics_payload):
        series = metrics_payload["metrics_series"]
        for i, entry in enumerate(series):
            growth = entry["revenue_growth_yoy_percent"]
            if growth is None or i == 0:
                continue
            prev_rev = series[i - 1]["revenue"]
            cur_rev = entry["revenue"]
            if prev_rev is not None and cur_rev is not None and prev_rev > 0:
                expected_sign = 1 if cur_rev >= prev_rev else -1
                actual_sign = 1 if growth >= 0 else -1
                assert expected_sign == actual_sign, (
                    f"FY{entry['fiscal_year']}: growth sign mismatch"
                )

    def test_free_cash_flow_sum(self, metrics_payload, records):
        for entry, rec in zip(metrics_payload["metrics_series"], records):
            fcf = entry["free_cash_flow"]
            if rec.operating_cf is not None or rec.investing_cf is not None:
                expected = (rec.operating_cf or 0.0) + (rec.investing_cf or 0.0)
                assert fcf is not None
                assert math.isclose(fcf, round(expected, 2), rel_tol=1e-9)


# ── calculate: file write ────────────────────────────────────────


class TestCalculateWriteFile:
    def test_writes_valid_json(self, tmp_path):
        from scripts.main import calculate_command

        output = tmp_path / "metrics.json"
        ret = calculate_command(ticker="7685", parsed_dir=DATA_DIR, output_path=output)
        assert ret == 0
        assert output.exists()
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["ticker"] == "7685"
        assert isinstance(payload["metrics_series"], list)
        assert len(payload["metrics_series"]) > 0


# ── report: output structure ─────────────────────────────────────

EXPECTED_SECTIONS = [
    "企業概要",
    "財務ハイライト",
    "収益性",
    "成長性",
    "安全性",
    "CF分析",
    "総合評価",
    "再現コマンド",
]


class TestReportStructure:
    def test_starts_with_h1(self, report_markdown):
        assert report_markdown.lstrip().startswith("#")

    def test_contains_all_sections(self, report_markdown):
        for section in EXPECTED_SECTIONS:
            assert section in report_markdown, f"Missing section: {section}"

    def test_contains_ticker(self, report_markdown):
        assert "7685" in report_markdown

    def test_contains_markdown_tables(self, report_markdown):
        lines = report_markdown.split("\n")
        table_lines = [ln for ln in lines if "|" in ln and "---" not in ln]
        assert len(table_lines) > 0

    def test_contains_reproduce_commands(self, report_markdown):
        assert "calculate --ticker 7685" in report_markdown
        assert "report --ticker 7685" in report_markdown


# ── report: command file write ───────────────────────────────────


class TestReportCommand:
    def test_writes_markdown(self, tmp_path):
        from scripts.main import calculate_command, report_command

        metrics_path = tmp_path / "metrics.json"
        calculate_command(ticker="7685", parsed_dir=DATA_DIR, output_path=metrics_path)

        report_path = tmp_path / "report.md"
        ret = report_command(
            ticker="7685", metrics_path=metrics_path, output_path=report_path
        )
        assert ret == 0
        assert report_path.exists()
        content = report_path.read_text(encoding="utf-8")
        for section in EXPECTED_SECTIONS:
            assert section in content

    def test_missing_metrics_returns_error(self, tmp_path):
        from scripts.main import report_command

        ret = report_command(
            ticker="7685",
            metrics_path=tmp_path / "nonexistent.json",
            output_path=tmp_path / "out.md",
        )
        assert ret == 1


# ── End-to-end CLI via subprocess ────────────────────────────────


# ── calculate: missing-key resilience ─────────────────────────────


def _write_minimal_financials(directory: Path, periods: list[dict]) -> None:
    """Write a synthetic financials.json with the given period entries."""
    payload = {
        "ticker": "0000",
        "documents": [],
        "period_index": periods,
        "schema": {"bs": [], "pl": [], "cf": []},
    }
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "financials.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


class TestCalculateMissingKeys:
    """Verify calculate handles missing input keys without crashing."""

    def test_missing_pl_revenue_yields_none(self, tmp_path):
        """Period with no pl.revenue → revenue/operating_margin/growth are None."""
        _write_minimal_financials(
            tmp_path,
            [
                {
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "period_type": "FY",
                    "bs": {"total_assets": 1_000_000, "net_assets": 500_000},
                    "pl": {"operating_income": 50_000, "net_income": 30_000},
                    "cf": {},
                }
            ],
        )
        payload = calculate_metrics_payload(parsed_dir=tmp_path, ticker="0000")
        assert payload["source_count"] == 1
        entry = payload["metrics_series"][0]
        assert entry["revenue"] is None
        assert entry["operating_margin_percent"] is None
        assert entry["revenue_growth_yoy_percent"] is None

    def test_missing_bs_total_assets_yields_none_roa(self, tmp_path):
        """Period with no bs.total_assets → roa_percent is None."""
        _write_minimal_financials(
            tmp_path,
            [
                {
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "period_type": "FY",
                    "bs": {},
                    "pl": {"revenue": 1_000_000, "net_income": 50_000},
                    "cf": {},
                }
            ],
        )
        payload = calculate_metrics_payload(parsed_dir=tmp_path, ticker="0000")
        entry = payload["metrics_series"][0]
        assert entry["roa_percent"] is None
        assert entry["equity_ratio_percent"] is None
        assert entry["revenue"] == 1_000_000.0

    def test_empty_period_index_falls_back_to_payload(self, tmp_path):
        """Empty period_index → _extract_candidates returns [payload] as fallback.
        This produces 1 record with all financial fields None."""
        _write_minimal_financials(tmp_path, [])
        payload = calculate_metrics_payload(parsed_dir=tmp_path, ticker="0000")
        assert payload["source_count"] == 1
        assert len(payload["metrics_series"]) == 1
        entry = payload["metrics_series"][0]
        for field in ("revenue", "operating_income", "net_income", "operating_cf"):
            assert entry[field] is None, f"{field} should be None for empty input"

    def test_all_pl_null_yields_all_none_metrics(self, tmp_path):
        """Period with all pl values null → derived metrics are None."""
        _write_minimal_financials(
            tmp_path,
            [
                {
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "period_type": "FY",
                    "bs": {"total_assets": 1_000_000},
                    "pl": {
                        "revenue": None,
                        "operating_income": None,
                        "net_income": None,
                    },
                    "cf": {},
                }
            ],
        )
        payload = calculate_metrics_payload(parsed_dir=tmp_path, ticker="0000")
        entry = payload["metrics_series"][0]
        for field in (
            "revenue",
            "operating_income",
            "net_income",
            "roe_percent",
            "roa_percent",
            "operating_margin_percent",
        ):
            assert entry[field] is None, f"{field} should be None when pl values are null"

    def test_missing_cf_yields_none_fcf(self, tmp_path):
        """Period with no cf data → operating_cf and free_cash_flow are None."""
        _write_minimal_financials(
            tmp_path,
            [
                {
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "period_type": "FY",
                    "bs": {"total_assets": 1_000_000},
                    "pl": {"revenue": 500_000, "net_income": 30_000},
                    "cf": {},
                }
            ],
        )
        payload = calculate_metrics_payload(parsed_dir=tmp_path, ticker="0000")
        entry = payload["metrics_series"][0]
        assert entry["operating_cf"] is None
        assert entry["free_cash_flow"] is None

    def test_nonexistent_parsed_dir_returns_empty(self, tmp_path):
        """Non-existent parsed_dir → source_count=0, empty series."""
        payload = calculate_metrics_payload(
            parsed_dir=tmp_path / "nonexistent", ticker="0000"
        )
        assert payload["source_count"] == 0
        assert payload["metrics_series"] == []
        assert payload["latest_snapshot"] is None

    def test_multi_period_with_partial_data(self, tmp_path):
        """Two periods, first has revenue only, second has all PL.
        Growth is computable on second entry; margin None on first."""
        _write_minimal_financials(
            tmp_path,
            [
                {
                    "period_end": "2023-03-31",
                    "fiscal_year": 2023,
                    "period_type": "FY",
                    "bs": {},
                    "pl": {"revenue": 800_000},
                    "cf": {},
                },
                {
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "period_type": "FY",
                    "bs": {"total_assets": 2_000_000},
                    "pl": {
                        "revenue": 1_000_000,
                        "operating_income": 100_000,
                        "net_income": 60_000,
                    },
                    "cf": {},
                },
            ],
        )
        payload = calculate_metrics_payload(parsed_dir=tmp_path, ticker="0000")
        assert payload["source_count"] == 2

        first, second = payload["metrics_series"]
        assert first["operating_margin_percent"] is None
        assert first["revenue_growth_yoy_percent"] is None

        assert second["revenue"] == 1_000_000.0
        assert second["revenue_growth_yoy_percent"] is not None
        expected_growth = round(((1_000_000 - 800_000) / 800_000) * 100.0, 2)
        assert math.isclose(
            second["revenue_growth_yoy_percent"], expected_growth, rel_tol=1e-9
        )


# ── End-to-end CLI via subprocess ────────────────────────────────


class TestCLIEndToEnd:
    def test_calculate_then_report(self, tmp_path):
        metrics_path = tmp_path / "metrics.json"
        report_path = tmp_path / "report.md"

        calc_result = subprocess.run(
            [
                sys.executable,
                str(MAIN_SCRIPT),
                "calculate",
                "--ticker",
                "7685",
                "--parsed-dir",
                str(DATA_DIR),
                "--output",
                str(metrics_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert calc_result.returncode == 0, f"stderr: {calc_result.stderr}"
        assert metrics_path.exists()

        payload = json.loads(metrics_path.read_text(encoding="utf-8"))
        assert payload["ticker"] == "7685"
        assert len(payload["metrics_series"]) > 0

        rpt_result = subprocess.run(
            [
                sys.executable,
                str(MAIN_SCRIPT),
                "report",
                "--ticker",
                "7685",
                "--metrics",
                str(metrics_path),
                "--output",
                str(report_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert rpt_result.returncode == 0, f"stderr: {rpt_result.stderr}"
        assert report_path.exists()

        content = report_path.read_text(encoding="utf-8")
        for section in EXPECTED_SECTIONS:
            assert section in content
