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

    def test_roe_computation(self, metrics_payload, records):
        """ROE = net_income / equity * 100; verify against raw records."""
        for entry, rec in zip(metrics_payload["metrics_series"], records):
            roe = entry["roe_percent"]
            if rec.net_income is not None and rec.equity is not None and rec.equity != 0:
                expected = round((rec.net_income / rec.equity) * 100.0, 2)
                assert roe is not None, (
                    f"FY{entry['fiscal_year']}: ROE should not be None"
                )
                assert math.isclose(roe, expected, rel_tol=1e-9), (
                    f"FY{entry['fiscal_year']}: ROE expected={expected}, got={roe}"
                )
            else:
                assert roe is None, (
                    f"FY{entry['fiscal_year']}: ROE should be None when inputs missing"
                )

    def test_equity_ratio_computation(self, metrics_payload, records):
        """equity_ratio = equity / total_assets * 100; verify against raw records."""
        for entry, rec in zip(metrics_payload["metrics_series"], records):
            eq_ratio = entry["equity_ratio_percent"]
            if rec.equity is not None and rec.total_assets is not None and rec.total_assets != 0:
                expected = round((rec.equity / rec.total_assets) * 100.0, 2)
                assert eq_ratio is not None, (
                    f"FY{entry['fiscal_year']}: equity_ratio should not be None"
                )
                assert math.isclose(eq_ratio, expected, rel_tol=1e-9), (
                    f"FY{entry['fiscal_year']}: equity_ratio expected={expected}, got={eq_ratio}"
                )
            else:
                assert eq_ratio is None, (
                    f"FY{entry['fiscal_year']}: equity_ratio should be None when inputs missing"
                )

    def test_roe_at_least_one_non_none(self, metrics_payload):
        """7685 data should produce at least one non-None ROE."""
        roe_values = [e["roe_percent"] for e in metrics_payload["metrics_series"]]
        non_none = [v for v in roe_values if v is not None]
        assert len(non_none) > 0, "No non-None ROE found in 7685 data"

    def test_equity_ratio_at_least_one_non_none(self, metrics_payload):
        """7685 data should produce at least one non-None equity_ratio."""
        eq_values = [e["equity_ratio_percent"] for e in metrics_payload["metrics_series"]]
        non_none = [v for v in eq_values if v is not None]
        assert len(non_none) > 0, "No non-None equity_ratio found in 7685 data"

    def test_roe_range(self, metrics_payload):
        """ROE should be within a plausible range."""
        for entry in metrics_payload["metrics_series"]:
            roe = entry["roe_percent"]
            if roe is not None:
                assert -500.0 <= roe <= 500.0, f"ROE {roe}% out of plausible range"


# ── calculate: total_equity alias ─────────────────────────────────


class TestTotalEquityAlias:
    """Verify that total_equity in bs is picked up as equity."""

    def test_total_equity_alias_resolves(self, tmp_path):
        """bs with total_equity (no net_assets/equity) → equity is resolved."""
        _write_minimal_financials(
            tmp_path,
            [
                {
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "period_type": "FY",
                    "bs": {"total_assets": 10_000_000, "total_equity": 4_000_000},
                    "pl": {"revenue": 5_000_000, "net_income": 500_000},
                    "cf": {},
                }
            ],
        )
        payload = calculate_metrics_payload(parsed_dir=tmp_path, ticker="0000")
        entry = payload["metrics_series"][0]
        assert entry["roe_percent"] is not None
        expected_roe = round((500_000 / 4_000_000) * 100.0, 2)
        assert math.isclose(entry["roe_percent"], expected_roe, rel_tol=1e-9)
        expected_eq_ratio = round((4_000_000 / 10_000_000) * 100.0, 2)
        assert math.isclose(entry["equity_ratio_percent"], expected_eq_ratio, rel_tol=1e-9)

    def test_equity_preferred_over_total_equity(self, tmp_path):
        """When both equity and total_equity exist, equity takes precedence."""
        _write_minimal_financials(
            tmp_path,
            [
                {
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "period_type": "FY",
                    "bs": {
                        "total_assets": 10_000_000,
                        "equity": 5_000_000,
                        "total_equity": 4_000_000,
                    },
                    "pl": {"net_income": 500_000},
                    "cf": {},
                }
            ],
        )
        payload = calculate_metrics_payload(parsed_dir=tmp_path, ticker="0000")
        entry = payload["metrics_series"][0]
        expected_roe = round((500_000 / 5_000_000) * 100.0, 2)
        assert math.isclose(entry["roe_percent"], expected_roe, rel_tol=1e-9)

    def test_total_equity_null_falls_through(self, tmp_path):
        """total_equity is null → falls through to net_assets."""
        _write_minimal_financials(
            tmp_path,
            [
                {
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "period_type": "FY",
                    "bs": {
                        "total_assets": 10_000_000,
                        "total_equity": None,
                        "net_assets": 3_000_000,
                    },
                    "pl": {"net_income": 300_000},
                    "cf": {},
                }
            ],
        )
        payload = calculate_metrics_payload(parsed_dir=tmp_path, ticker="0000")
        entry = payload["metrics_series"][0]
        expected_roe = round((300_000 / 3_000_000) * 100.0, 2)
        assert math.isclose(entry["roe_percent"], expected_roe, rel_tol=1e-9)


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

    def test_empty_period_index_yields_no_records(self, tmp_path):
        """Empty period_index → no candidates, no fiscal_year=None pollution."""
        _write_minimal_financials(tmp_path, [])
        payload = calculate_metrics_payload(parsed_dir=tmp_path, ticker="0000")
        assert payload["source_count"] == 0
        assert payload["metrics_series"] == []
        assert payload["latest_snapshot"] is None

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


# ── calculate: fiscal_year deduplication ──────────────────────────


class TestDeduplicateFiscalYear:
    """Verify fiscal_year dedup selects the best representative per FY."""

    def test_selects_highest_nonnull_count(self, tmp_path):
        """Record with more non-null financial fields wins."""
        _write_minimal_financials(
            tmp_path,
            [
                {
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "period_type": "duration",
                    "bs": {},
                    "pl": {"revenue": 1_000_000, "net_income": 50_000},
                    "cf": {},
                },
                {
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "period_type": "mixed",
                    "bs": {"total_assets": 5_000_000, "net_assets": 2_000_000},
                    "pl": {"revenue": 1_000_000, "operating_income": 100_000, "net_income": 50_000},
                    "cf": {},
                },
            ],
        )
        payload = calculate_metrics_payload(parsed_dir=tmp_path, ticker="0000")
        assert len(payload["metrics_series"]) == 1
        entry = payload["metrics_series"][0]
        # mixed record has BS data → roa_percent should be computable
        assert entry["roa_percent"] is not None

    def test_period_type_tiebreaker(self, tmp_path):
        """Same nonnull count → mixed > duration > instant."""
        _write_minimal_financials(
            tmp_path,
            [
                {
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "period_type": "duration",
                    "bs": {"total_assets": 5_000_000, "net_assets": 2_000_000},
                    "pl": {"revenue": 1_000_000, "net_income": 50_000},
                    "cf": {},
                },
                {
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "period_type": "mixed",
                    "bs": {"total_assets": 5_000_000, "net_assets": 2_000_000},
                    "pl": {"revenue": 2_000_000, "net_income": 100_000},
                    "cf": {},
                },
            ],
        )
        payload = calculate_metrics_payload(parsed_dir=tmp_path, ticker="0000")
        assert len(payload["metrics_series"]) == 1
        entry = payload["metrics_series"][0]
        assert entry["revenue"] == 2_000_000.0

    def test_period_end_tiebreaker(self, tmp_path):
        """Same nonnull count and period_type → newer period_end wins."""
        _write_minimal_financials(
            tmp_path,
            [
                {
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "period_type": "mixed",
                    "bs": {"total_assets": 5_000_000},
                    "pl": {"revenue": 1_000_000, "net_income": 50_000},
                    "cf": {},
                },
                {
                    "period_end": "2024-12-31",
                    "fiscal_year": 2024,
                    "period_type": "mixed",
                    "bs": {"total_assets": 8_000_000},
                    "pl": {"revenue": 3_000_000, "net_income": 200_000},
                    "cf": {},
                },
            ],
        )
        payload = calculate_metrics_payload(parsed_dir=tmp_path, ticker="0000")
        assert len(payload["metrics_series"]) == 1
        entry = payload["metrics_series"][0]
        assert entry["revenue"] == 3_000_000.0
        # Later period_end record has ta=8M, ni=200K → roa = 2.5%
        expected_roa = round((200_000 / 8_000_000) * 100.0, 2)
        assert math.isclose(entry["roa_percent"], expected_roa, rel_tol=1e-9)

    def test_instant_loses_to_duration(self, tmp_path):
        """instant (bs-only) loses to duration (pl-only) at equal nonnull count."""
        _write_minimal_financials(
            tmp_path,
            [
                {
                    "period_end": "2024-12-31",
                    "fiscal_year": 2024,
                    "period_type": "instant",
                    "bs": {"total_assets": 5_000_000, "net_assets": 2_000_000},
                    "pl": {},
                    "cf": {},
                },
                {
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "period_type": "duration",
                    "bs": {},
                    "pl": {"revenue": 1_000_000, "net_income": 50_000},
                    "cf": {},
                },
            ],
        )
        payload = calculate_metrics_payload(parsed_dir=tmp_path, ticker="0000")
        assert len(payload["metrics_series"]) == 1
        entry = payload["metrics_series"][0]
        assert entry["revenue"] == 1_000_000.0

    def test_unique_fiscal_years_in_real_data(self, metrics_payload):
        """After dedup, each fiscal_year appears at most once."""
        fiscal_years = [e["fiscal_year"] for e in metrics_payload["metrics_series"]]
        non_none = [fy for fy in fiscal_years if fy is not None]
        assert len(non_none) == len(set(non_none)), f"Duplicate fiscal_years: {non_none}"

    def test_real_data_record_count(self, records):
        """7685 real data: each fiscal_year represented exactly once."""
        from collections import Counter

        fy_counts = Counter(r.fiscal_year for r in records)
        for fy, count in fy_counts.items():
            assert count == 1, f"FY{fy} has {count} records, expected 1"

    def test_none_fiscal_year_preserved(self, tmp_path):
        """Records with fiscal_year=None are preserved (one representative)."""
        _write_minimal_financials(
            tmp_path,
            [
                {
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "period_type": "FY",
                    "bs": {"total_assets": 5_000_000},
                    "pl": {"revenue": 1_000_000},
                    "cf": {},
                },
                {
                    "period_end": None,
                    "fiscal_year": None,
                    "period_type": "FY",
                    "bs": {},
                    "pl": {"revenue": 500_000},
                    "cf": {},
                },
            ],
        )
        payload = calculate_metrics_payload(parsed_dir=tmp_path, ticker="0000")
        assert len(payload["metrics_series"]) == 2

    def test_three_way_dedup(self, tmp_path):
        """Three records same FY: instant(2), duration(3), mixed(5) → mixed wins."""
        _write_minimal_financials(
            tmp_path,
            [
                {
                    "period_end": "2024-12-31",
                    "fiscal_year": 2024,
                    "period_type": "instant",
                    "bs": {"total_assets": 10_000_000, "net_assets": 4_000_000},
                    "pl": {},
                    "cf": {},
                },
                {
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "period_type": "duration",
                    "bs": {},
                    "pl": {"revenue": 5_000_000, "operating_income": 500_000, "net_income": 300_000},
                    "cf": {},
                },
                {
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "period_type": "mixed",
                    "bs": {"total_assets": 8_000_000, "net_assets": 3_000_000},
                    "pl": {"revenue": 5_000_000, "operating_income": 500_000, "net_income": 300_000},
                    "cf": {},
                },
            ],
        )
        payload = calculate_metrics_payload(parsed_dir=tmp_path, ticker="0000")
        assert len(payload["metrics_series"]) == 1
        entry = payload["metrics_series"][0]
        assert entry["revenue"] == 5_000_000.0
        # mixed record has BS data → equity_ratio should be computable
        assert entry["equity_ratio_percent"] is not None

    def test_same_values_different_period_type_selects_mixed(self, tmp_path):
        """Same FY, same period_end, same financials, only period_type differs.
        Phase1 must NOT collapse them; Phase2 must pick mixed over duration."""
        _write_minimal_financials(
            tmp_path,
            [
                {
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "period_type": "duration",
                    "bs": {"total_assets": 5_000_000, "net_assets": 2_000_000},
                    "pl": {"revenue": 1_000_000, "operating_income": 100_000, "net_income": 50_000},
                    "cf": {},
                },
                {
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "period_type": "mixed",
                    "bs": {"total_assets": 5_000_000, "net_assets": 2_000_000},
                    "pl": {"revenue": 1_000_000, "operating_income": 100_000, "net_income": 50_000},
                    "cf": {},
                },
            ],
        )
        payload = calculate_metrics_payload(parsed_dir=tmp_path, ticker="0000")
        assert len(payload["metrics_series"]) == 1
        entry = payload["metrics_series"][0]
        assert entry["period"] == "mixed"
        assert entry["revenue"] == 1_000_000.0

    def test_same_values_different_period_type_duration_over_instant(self, tmp_path):
        """Same FY, same financials, period_type differs: duration beats instant."""
        _write_minimal_financials(
            tmp_path,
            [
                {
                    "period_end": "2024-12-31",
                    "fiscal_year": 2024,
                    "period_type": "instant",
                    "bs": {"total_assets": 5_000_000},
                    "pl": {"revenue": 1_000_000, "net_income": 50_000},
                    "cf": {},
                },
                {
                    "period_end": "2024-12-31",
                    "fiscal_year": 2024,
                    "period_type": "duration",
                    "bs": {"total_assets": 5_000_000},
                    "pl": {"revenue": 1_000_000, "net_income": 50_000},
                    "cf": {},
                },
            ],
        )
        payload = calculate_metrics_payload(parsed_dir=tmp_path, ticker="0000")
        assert len(payload["metrics_series"]) == 1
        entry = payload["metrics_series"][0]
        assert entry["period"] == "duration"


# ── extract_candidates: fallback / None fiscal_year ──────────────


class TestExtractCandidatesFallback:
    """Verify _extract_candidates fallback prevents fiscal_year=None pollution."""

    def test_payload_with_fiscal_year_used_as_fallback(self, tmp_path):
        """Payload with valid fiscal_year but no periods/documents → used as single record."""
        payload = {
            "ticker": "9999",
            "fiscal_year": 2024,
            "period": "FY",
            "period_end": "2024-03-31",
            "bs": {"total_assets": 10_000_000, "net_assets": 5_000_000},
            "pl": {"revenue": 3_000_000, "net_income": 200_000},
            "cf": {},
        }
        directory = tmp_path
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "single.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        result = calculate_metrics_payload(parsed_dir=directory, ticker="9999")
        assert result["source_count"] == 1
        entry = result["metrics_series"][0]
        assert entry["fiscal_year"] == 2024
        assert entry["revenue"] == 3_000_000.0

    def test_payload_without_fiscal_year_skipped(self, tmp_path):
        """Container payload (no fiscal_year, empty period_index) → 0 records."""
        payload = {
            "ticker": "0000",
            "documents": [],
            "period_index": [],
            "schema": {"bs": [], "pl": [], "cf": []},
        }
        directory = tmp_path
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "container.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        result = calculate_metrics_payload(parsed_dir=directory, ticker="0000")
        assert result["source_count"] == 0
        assert result["metrics_series"] == []

    def test_none_fiscal_year_not_injected_by_fallback(self, tmp_path):
        """Two files: one valid period_index, one empty container.
        Only valid records appear; no fiscal_year=None pollution."""
        valid = {
            "ticker": "1111",
            "period_index": [
                {
                    "period_end": "2024-03-31",
                    "fiscal_year": 2024,
                    "period_type": "FY",
                    "bs": {"total_assets": 5_000_000},
                    "pl": {"revenue": 1_000_000, "net_income": 50_000},
                    "cf": {},
                }
            ],
        }
        empty_container = {
            "ticker": "1111",
            "documents": [],
            "period_index": [],
        }
        directory = tmp_path
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "a_valid.json").write_text(
            json.dumps(valid, ensure_ascii=False), encoding="utf-8"
        )
        (directory / "b_empty.json").write_text(
            json.dumps(empty_container, ensure_ascii=False), encoding="utf-8"
        )
        result = calculate_metrics_payload(parsed_dir=directory, ticker="1111")
        assert result["source_count"] == 1
        fiscal_years = [e["fiscal_year"] for e in result["metrics_series"]]
        assert None not in fiscal_years
        assert fiscal_years == [2024]

    def test_duplicate_periods_across_files_deduped(self, tmp_path):
        """Same period in two files → dedup keeps one representative."""
        period_data = {
            "period_end": "2024-03-31",
            "fiscal_year": 2024,
            "period_type": "FY",
            "bs": {"total_assets": 10_000_000, "net_assets": 4_000_000},
            "pl": {"revenue": 5_000_000, "operating_income": 500_000, "net_income": 300_000},
            "cf": {"operating_cf": 400_000},
        }
        for name in ("file1.json", "file2.json"):
            payload = {"ticker": "2222", "period_index": [period_data]}
            (tmp_path / name).write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
        result = calculate_metrics_payload(parsed_dir=tmp_path, ticker="2222")
        assert len(result["metrics_series"]) == 1
        entry = result["metrics_series"][0]
        assert entry["fiscal_year"] == 2024
        assert entry["revenue"] == 5_000_000.0


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
