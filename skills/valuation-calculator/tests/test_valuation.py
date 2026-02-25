"""valuation-calculator テスト

カバレッジ目標: 80% 以上
対象: skills/valuation-calculator/scripts/valuation.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from scripts.valuation import (
    DCFResult,
    RelativeMetrics,
    compute_dcf,
    compute_peer_comparison,
    compute_relative_metrics,
    extract_fcf_series,
    extract_net_debt,
)

# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _make_metrics(
    ticker: str = "9743",
    fcf_values: list[float] | None = None,
    market_cap: float | None = 50_000_000_000,
    net_income: float | None = 5_000_000_000,
    equity: float | None = 30_000_000_000,
    operating_income: float | None = 7_000_000_000,
    total_debt: float | None = 10_000_000_000,
    cash: float | None = 5_000_000_000,
    depreciation: float | None = 1_000_000_000,
) -> dict:
    series = []
    if fcf_values:
        for i, fcf in enumerate(fcf_values):
            series.append({
                "fiscal_year": 2021 + i,
                "revenue": 100_000_000_000,
                "operating_income": operating_income,
                "net_income": net_income,
                "operating_cf": fcf + 2_000_000_000 if fcf else None,
                "free_cash_flow": fcf,
            })

    snapshot: dict = {}
    if market_cap is not None:
        snapshot["market_cap"] = market_cap
    if net_income is not None:
        snapshot["net_income"] = net_income
    if equity is not None:
        snapshot["equity"] = equity
    if operating_income is not None:
        snapshot["operating_income"] = operating_income
    if total_debt is not None:
        snapshot["total_debt"] = total_debt
    if cash is not None:
        snapshot["cash_and_equivalents"] = cash
    if depreciation is not None:
        snapshot["depreciation"] = depreciation

    return {
        "ticker": ticker,
        "metrics_series": series,
        "latest_snapshot": snapshot,
    }


# ---------------------------------------------------------------------------
# DCF テスト
# ---------------------------------------------------------------------------

class TestComputeDCF:
    def test_normal_calculation(self):
        """FCF系列ありの正常計算"""
        fcf_series = [1_000_000, 1_100_000, 1_200_000, 1_300_000]
        result = compute_dcf(fcf_series, wacc=0.10, terminal_growth_rate=0.02)

        assert isinstance(result, DCFResult)
        assert result.enterprise_value > 0
        assert result.equity_value > 0  # net_debt=0 なので EV == equity_value
        assert result.per_share_value is None  # shares 未指定
        assert result.assumptions["wacc"] == 0.10
        assert result.assumptions["terminal_growth_rate"] == 0.02
        assert result.assumptions["base_fcf"] == 1_300_000

    def test_with_shares(self):
        """1株あたり価値の算出"""
        result = compute_dcf(
            [1_000_000, 1_200_000],
            wacc=0.08,
            terminal_growth_rate=0.02,
            shares_outstanding=100_000,
        )
        assert result.per_share_value is not None
        assert result.per_share_value > 0

    def test_with_net_debt(self):
        """純有利子負債の控除"""
        result_no_debt = compute_dcf([1_000_000], wacc=0.08, terminal_growth_rate=0.02, net_debt=0)
        result_with_debt = compute_dcf([1_000_000], wacc=0.08, terminal_growth_rate=0.02, net_debt=500_000)

        assert result_with_debt.equity_value < result_no_debt.equity_value
        assert result_with_debt.enterprise_value == result_no_debt.enterprise_value

    def test_single_fcf(self):
        """FCF系列が1年分のみの場合（成長率=terminal_growth_rate で計算）"""
        result = compute_dcf([1_000_000], wacc=0.08, terminal_growth_rate=0.02)
        assert result.enterprise_value > 0

    def test_empty_fcf_raises(self):
        """空のFCF系列はエラー"""
        with pytest.raises(ValueError, match="fcf_series is empty"):
            compute_dcf([])

    def test_wacc_lte_growth_raises(self):
        """WACC <= terminal_growth_rate はエラー"""
        with pytest.raises(ValueError, match="wacc.*must be greater"):
            compute_dcf([1_000_000], wacc=0.02, terminal_growth_rate=0.02)

        with pytest.raises(ValueError, match="wacc.*must be greater"):
            compute_dcf([1_000_000], wacc=0.01, terminal_growth_rate=0.02)

    def test_negative_wacc_raises(self):
        """負の WACC はエラー"""
        with pytest.raises(ValueError, match="wacc must be positive"):
            compute_dcf([1_000_000], wacc=-0.05, terminal_growth_rate=-0.10)

    def test_negative_fcf(self):
        """負のFCFでも計算可能（企業価値が負になりうる）"""
        result = compute_dcf([-1_000_000, -500_000], wacc=0.10, terminal_growth_rate=0.02)
        assert isinstance(result, DCFResult)
        # 負のFCFからの成長率推定: fcf_series[0] < 0 なので growth = terminal_growth_rate
        assert result.assumptions["estimated_growth_rate"] == 0.02

    def test_growth_rate_clamped(self):
        """極端なCAGRはクランプされる"""
        # 10倍成長 → CAGR が非常に高い → 30%にクランプ
        result = compute_dcf([100_000, 1_000_000], wacc=0.35, terminal_growth_rate=0.02)
        assert result.assumptions["estimated_growth_rate"] <= 0.30

    def test_projection_years(self):
        """予測期間の変更（成長率 != terminal_growth_rate のとき値が変わる）"""
        # 2年以上の系列で CAGR != terminal_growth_rate を生成
        fcf = [1_000_000, 1_100_000, 1_210_000]  # ~10% CAGR
        r5 = compute_dcf(fcf, wacc=0.15, terminal_growth_rate=0.02, projection_years=5)
        r10 = compute_dcf(fcf, wacc=0.15, terminal_growth_rate=0.02, projection_years=10)
        assert r5.enterprise_value != r10.enterprise_value


# ---------------------------------------------------------------------------
# 相対バリュエーション テスト
# ---------------------------------------------------------------------------

class TestComputeRelativeMetrics:
    def test_normal_calculation(self):
        """PER/PBR/EV-EBITDA の正常計算"""
        metrics = _make_metrics()
        result = compute_relative_metrics(metrics)

        assert result.ticker == "9743"
        assert result.per == 10.0  # 50B / 5B
        assert result.pbr == pytest.approx(1.67, abs=0.01)  # 50B / 30B
        assert result.ev_ebitda is not None
        # data_sources: latest_snapshot から取得
        assert result.data_sources["market_cap"] == "latest_snapshot"
        assert result.data_sources["net_income"] == "latest_snapshot"

    def test_ev_ebitda_calculation(self):
        """EV/EBITDA = (market_cap + debt - cash) / (operating_income + depreciation)"""
        metrics = _make_metrics(
            market_cap=50_000,
            total_debt=10_000,
            cash=5_000,
            operating_income=7_000,
            depreciation=1_000,
        )
        result = compute_relative_metrics(metrics)
        # EV = 50000 + 10000 - 5000 = 55000, EBITDA = 7000 + 1000 = 8000
        assert result.ev_ebitda == pytest.approx(6.88, abs=0.01)

    def test_missing_market_cap_fallback_to_series(self):
        """latest_snapshot に market_cap がない場合、series の最新年から取得"""
        metrics = {
            "ticker": "1234",
            "metrics_series": [
                {"fiscal_year": 2024, "market_cap": 100_000, "net_income": 10_000, "equity": 50_000}
            ],
            "latest_snapshot": {"operating_income": 15_000},
        }
        result = compute_relative_metrics(metrics)
        assert result.per == 10.0  # 100000 / 10000
        assert result.pbr == 2.0   # 100000 / 50000
        # data_sources: metrics_series からフォールバック
        assert result.data_sources["market_cap"] == "metrics_series[2024]"
        assert result.data_sources["net_income"] == "metrics_series[2024]"
        assert result.data_sources["equity"] == "metrics_series[2024]"

    def test_zero_net_income(self):
        """net_income=0 で PER は None（ゼロ除算防止）"""
        metrics = _make_metrics(net_income=0)
        result = compute_relative_metrics(metrics)
        assert result.per is None

    def test_none_values(self):
        """データ欠損時は None を返す"""
        metrics = {"ticker": "0000", "metrics_series": [], "latest_snapshot": {}}
        result = compute_relative_metrics(metrics)
        assert result.per is None
        assert result.pbr is None
        assert result.ev_ebitda is None
        assert result.data_sources is None  # ソース情報もなし

    def test_zero_ebitda(self):
        """EBITDA=0 で EV/EBITDA は None"""
        metrics = _make_metrics(operating_income=0, depreciation=0)
        result = compute_relative_metrics(metrics)
        assert result.ev_ebitda is None

    def test_no_depreciation(self):
        """depreciation がない場合は operating_income のみで EBITDA 近似"""
        metrics = _make_metrics(depreciation=None)
        result = compute_relative_metrics(metrics)
        # EBITDA = operating_income + 0 = 7B
        assert result.ev_ebitda is not None


class TestPeerComparison:
    def test_normal_comparison(self):
        """複数銘柄入力の同業比較"""
        target = _make_metrics(ticker="9743", market_cap=50_000, net_income=5_000, equity=30_000)
        peer1 = _make_metrics(ticker="4680", market_cap=40_000, net_income=5_000, equity=25_000)
        peer2 = _make_metrics(ticker="2327", market_cap=60_000, net_income=4_000, equity=20_000)

        result = compute_peer_comparison(target, [peer1, peer2])

        assert result.target.ticker == "9743"
        assert len(result.peers) == 2
        assert "per" in result.comparison
        assert "pbr" in result.comparison
        assert "ev_ebitda" in result.comparison

        per_cmp = result.comparison["per"]
        assert per_cmp["target"] == 10.0  # 50000 / 5000
        assert per_cmp["peer_median"] is not None
        assert per_cmp["vs_median"] is not None

    def test_empty_peers(self):
        """ピアなしの場合"""
        target = _make_metrics()
        result = compute_peer_comparison(target, [])

        assert result.target.ticker == "9743"
        assert len(result.peers) == 0
        assert result.comparison["per"]["peer_median"] is None

    def test_peer_with_missing_data(self):
        """一部ピアのデータ欠損"""
        target = _make_metrics()
        peer_incomplete = {"ticker": "0000", "metrics_series": [], "latest_snapshot": {}}

        result = compute_peer_comparison(target, [peer_incomplete])
        # ピアの値が None でも集計可能
        assert result.comparison["per"]["peer_median"] is None


# ---------------------------------------------------------------------------
# ヘルパー関数テスト
# ---------------------------------------------------------------------------

class TestExtractors:
    def test_extract_fcf_series(self):
        """FCF系列抽出"""
        metrics = _make_metrics(fcf_values=[1_000, 2_000, 3_000])
        series = extract_fcf_series(metrics)
        assert series == [1_000, 2_000, 3_000]

    def test_extract_fcf_series_empty(self):
        """FCFデータなし"""
        metrics = _make_metrics(fcf_values=None)
        assert extract_fcf_series(metrics) == []

    def test_extract_fcf_series_partial_none(self):
        """一部 None を含む FCF 系列"""
        metrics = {
            "ticker": "1234",
            "metrics_series": [
                {"fiscal_year": 2022, "free_cash_flow": 1_000},
                {"fiscal_year": 2023, "free_cash_flow": None},
                {"fiscal_year": 2024, "free_cash_flow": 3_000},
            ],
            "latest_snapshot": {},
        }
        assert extract_fcf_series(metrics) == [1_000, 3_000]

    def test_extract_net_debt(self):
        """純有利子負債抽出"""
        metrics = _make_metrics(total_debt=10_000, cash=3_000)
        assert extract_net_debt(metrics) == 7_000

    def test_extract_net_debt_missing(self):
        """debt/cash 欠損時は 0"""
        metrics = {"ticker": "0000", "metrics_series": [], "latest_snapshot": {}}
        assert extract_net_debt(metrics) == 0

    def test_extract_net_debt_none_values(self):
        """None 値のフォールバック"""
        metrics = {
            "ticker": "0000",
            "metrics_series": [],
            "latest_snapshot": {"total_debt": None, "cash_and_equivalents": None},
        }
        assert extract_net_debt(metrics) == 0


# ---------------------------------------------------------------------------
# CLI 統合テスト
# ---------------------------------------------------------------------------

class TestCLI:
    def test_dcf_command(self, tmp_path):
        """dcf サブコマンドの正常実行"""
        metrics = _make_metrics(fcf_values=[1_000_000, 1_200_000, 1_500_000])
        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text(json.dumps(metrics), encoding="utf-8")

        output_file = tmp_path / "dcf_result.json"
        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "main.py"), "dcf",
             "--metrics", str(metrics_file),
             "--wacc", "0.10",
             "--growth-rate", "0.03",
             "--output", str(output_file)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(output_file.read_text(encoding="utf-8"))
        assert data["valuation_type"] == "dcf"
        assert data["enterprise_value"] > 0

    def test_relative_command(self, tmp_path):
        """relative サブコマンドの正常実行（ピアなし）"""
        metrics = _make_metrics()
        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text(json.dumps(metrics), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "main.py"), "relative",
             "--metrics", str(metrics_file)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["valuation_type"] == "relative"
        assert data["per"] is not None

    def test_relative_with_peers(self, tmp_path):
        """relative サブコマンドの同業比較実行"""
        target = _make_metrics(ticker="9743")
        peer1 = _make_metrics(ticker="4680", market_cap=40_000, net_income=5_000)
        peer2 = _make_metrics(ticker="2327", market_cap=60_000, net_income=4_000)

        target_file = tmp_path / "target.json"
        peer1_file = tmp_path / "peer1.json"
        peer2_file = tmp_path / "peer2.json"
        target_file.write_text(json.dumps(target), encoding="utf-8")
        peer1_file.write_text(json.dumps(peer1), encoding="utf-8")
        peer2_file.write_text(json.dumps(peer2), encoding="utf-8")

        output_file = tmp_path / "relative_result.json"
        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "main.py"), "relative",
             "--metrics", str(target_file),
             "--peers", str(peer1_file), str(peer2_file),
             "--output", str(output_file)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(output_file.read_text(encoding="utf-8"))
        assert data["valuation_type"] == "relative"
        assert len(data["peers"]) == 2
        assert "comparison" in data

    def test_dcf_no_fcf_error(self, tmp_path):
        """FCFなしの metrics.json で dcf はエラー終了"""
        metrics = _make_metrics(fcf_values=None)
        metrics_file = tmp_path / "empty_metrics.json"
        metrics_file.write_text(json.dumps(metrics), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "main.py"), "dcf",
             "--metrics", str(metrics_file)],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "free_cash_flow" in result.stderr
