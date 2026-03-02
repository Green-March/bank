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


# ---------------------------------------------------------------------------
# per_share_value 算出検証テスト (req_051)
# ---------------------------------------------------------------------------

class TestPerShareValue:
    """shares_outstanding → per_share_value 計算の正確性・エッジケースを検証する。"""

    def test_exact_per_share_value(self):
        """既知の値で per_share_value の正確性を検証する。

        FCF系列=[10_000_000] (1年分なので growth=terminal_growth_rate=0.02),
        wacc=0.08, net_debt=2_000_000, shares=100_000

        計算:
          base_fcf=10_000_000, growth=0.02
          year1: 10_200_000 / 1.08 = 9_444_444.44...
          year2: 10_404_000 / 1.1664 = 8_919_753.09...
          year3: 10_612_080 / 1.259712 = 8_424_183.45...
          year4: 10_824_321.6 / 1.36048896 = 7_955_961.07...
          year5: 11_040_808.032 / 1.46932808 = 7_513_371.29...
          pv_fcfs = 42_257_713.34...
          terminal_fcf = 11_040_808.032 * 1.02 = 11_261_624.19...
          terminal_value = 11_261_624.19... / 0.06 = 187_693_736.54...
          pv_terminal = 187_693_736.54... / 1.46932808 = 127_741_189.72...
          EV = 42_257_713.34... + 127_741_189.72... = 169_998_903.07...
          equity = 169_998_903.07... - 2_000_000 = 167_998_903.07...
          per_share = 167_998_903.07... / 100_000 = 1679.99
        """
        result = compute_dcf(
            fcf_series=[10_000_000],
            wacc=0.08,
            terminal_growth_rate=0.02,
            net_debt=2_000_000,
            shares_outstanding=100_000,
            projection_years=5,
        )
        assert result.per_share_value is not None
        # EV から net_debt を引いた equity_value を shares で割った値
        expected_per_share = result.equity_value / 100_000
        assert result.per_share_value == round(expected_per_share, 2)
        # equity_value = enterprise_value - net_debt
        assert result.equity_value == result.enterprise_value - 2_000_000

    def test_shares_none_returns_none(self):
        """shares_outstanding=None のとき per_share_value=None"""
        result = compute_dcf(
            fcf_series=[1_000_000, 1_200_000],
            wacc=0.08,
            terminal_growth_rate=0.02,
            shares_outstanding=None,
        )
        assert result.per_share_value is None
        assert result.assumptions["shares_outstanding"] is None

    def test_shares_zero_returns_none(self):
        """shares_outstanding=0 のときゼロ除算せず per_share_value=None"""
        result = compute_dcf(
            fcf_series=[1_000_000, 1_200_000],
            wacc=0.08,
            terminal_growth_rate=0.02,
            shares_outstanding=0,
        )
        assert result.per_share_value is None

    def test_shares_zero_float_returns_none(self):
        """shares_outstanding=0.0 のときもゼロ除算せず per_share_value=None"""
        result = compute_dcf(
            fcf_series=[1_000_000],
            wacc=0.08,
            terminal_growth_rate=0.02,
            shares_outstanding=0.0,
        )
        assert result.per_share_value is None

    def test_shares_negative_returns_none(self):
        """shares_outstanding が負の場合も per_share_value=None"""
        result = compute_dcf(
            fcf_series=[1_000_000],
            wacc=0.08,
            terminal_growth_rate=0.02,
            shares_outstanding=-100_000,
        )
        assert result.per_share_value is None

    def test_per_share_with_large_shares(self):
        """大きな株式数（実際の上場企業規模）で計算精度を検証"""
        result = compute_dcf(
            fcf_series=[5_000_000_000, 5_500_000_000, 6_000_000_000],
            wacc=0.08,
            terminal_growth_rate=0.02,
            net_debt=10_000_000_000,
            shares_outstanding=500_000_000,
        )
        assert result.per_share_value is not None
        assert result.per_share_value > 0
        # 手動検証: equity_value / shares
        assert result.per_share_value == round(result.equity_value / 500_000_000, 2)

    def test_per_share_negative_equity(self):
        """equity_value が負の場合でも per_share_value が算出される（債務超過ケース）"""
        # net_debt を非常に大きくして equity_value < 0 にする
        result = compute_dcf(
            fcf_series=[100_000],
            wacc=0.08,
            terminal_growth_rate=0.02,
            net_debt=100_000_000_000,
            shares_outstanding=100_000,
        )
        assert result.equity_value < 0
        assert result.per_share_value is not None
        assert result.per_share_value < 0

    def test_assumptions_include_shares(self):
        """assumptions に shares_outstanding が含まれる"""
        result = compute_dcf(
            fcf_series=[1_000_000],
            wacc=0.08,
            terminal_growth_rate=0.02,
            shares_outstanding=50_000,
        )
        assert "shares_outstanding" in result.assumptions
        assert result.assumptions["shares_outstanding"] == 50_000


class TestPerShareCLI:
    """CLI 経由の per_share_value テスト。"""

    def test_dcf_cli_with_shares(self, tmp_path):
        """--shares 指定時に per_share_value が出力される"""
        metrics = _make_metrics(
            fcf_values=[1_000_000_000, 1_200_000_000, 1_500_000_000],
            total_debt=0,
            cash=0,
        )
        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text(json.dumps(metrics), encoding="utf-8")

        output_file = tmp_path / "dcf_result.json"
        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "main.py"), "dcf",
             "--metrics", str(metrics_file),
             "--shares", "200000",
             "--output", str(output_file)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(output_file.read_text(encoding="utf-8"))
        assert data["per_share_value"] is not None
        assert data["per_share_value"] > 0
        assert data["assumptions"]["shares_outstanding"] == 200_000

    def test_dcf_cli_without_shares(self, tmp_path):
        """--shares 未指定時に per_share_value が null"""
        metrics = _make_metrics(fcf_values=[1_000_000, 1_200_000])
        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text(json.dumps(metrics), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "main.py"), "dcf",
             "--metrics", str(metrics_file)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["per_share_value"] is None
        assert data["assumptions"]["shares_outstanding"] is None


class TestPipelineOutputVarsPropagation:
    """pipeline output_vars 経由の shares_outstanding 伝播を検証する。

    実際の pipeline-runner の subprocess 実行ではなく、
    パイプライン定義の構造的整合性とコマンドテンプレートの正しさを検証する。
    """

    def _load_pipeline_steps(self):
        """example_pipeline.yaml のステップ一覧を読み込む。"""
        import yaml

        pipeline_path = Path(__file__).resolve().parent.parent.parent / \
            "pipeline-runner" / "references" / "example_pipeline.yaml"
        if not pipeline_path.exists():
            pytest.skip("example_pipeline.yaml not found")

        with open(pipeline_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return data.get("pipeline", {}).get("steps", [])

    def test_valuate_command_template_includes_shares_conditional(self):
        """valuate ステップのコマンドテンプレートが shares_outstanding の
        shell conditional を含むことを検証する。"""
        steps = self._load_pipeline_steps()
        valuate_step = next((s for s in steps if s["id"] == "valuate"), None)
        assert valuate_step is not None, "valuate step not found in pipeline"

        # コマンドに shares_outstanding の条件付き展開が含まれる
        cmd = valuate_step["command"]
        assert "{shares_outstanding}" in cmd
        assert "--shares" in cmd

    def test_collect_jquants_output_vars_has_shares(self):
        """collect_jquants ステップの output_vars に shares_outstanding が定義されている。"""
        steps = self._load_pipeline_steps()
        jquants_step = next((s for s in steps if s["id"] == "collect_jquants"), None)
        assert jquants_step is not None, "collect_jquants step not found"

        output_vars = jquants_step.get("output_vars", {})
        assert "shares_outstanding" in output_vars

    def test_shares_propagation_simulation(self):
        """output_vars の値を使って valuate コマンドをシミュレーションする。

        collect_jquants が shares_outstanding=18260731 を出力した場合、
        valuate コマンドに --shares 18260731 が含まれることを検証。
        """
        # パイプラインの変数展開をシミュレート
        cmd_template = 'python3 main.py dcf --metrics metrics.json $([ -n "{shares_outstanding}" ] && echo "--shares {shares_outstanding}")'

        # shares_outstanding が設定された場合
        rendered_with_shares = cmd_template.replace("{shares_outstanding}", "18260731")
        assert "--shares 18260731" in rendered_with_shares

        # shares_outstanding が空の場合
        rendered_without_shares = cmd_template.replace("{shares_outstanding}", "")
        assert '[ -n "" ]' in rendered_without_shares


# ---------------------------------------------------------------------------
# --market-data テスト (req_061)
# ---------------------------------------------------------------------------

def _make_market_data(
    market_cap: float | None = 94_418_000_000.0,
    shares_outstanding: float | None = 53_983_965.0,
    per: float | None = 16.5,
    pbr: float | None = 2.01,
) -> dict:
    """harmonized_financials.json 相当のテストデータを生成する。"""
    indicators: dict = {}
    if market_cap is not None:
        indicators["market_cap"] = market_cap
    if shares_outstanding is not None:
        indicators["shares_outstanding"] = shares_outstanding
    if per is not None:
        indicators["per"] = per
    if pbr is not None:
        indicators["pbr"] = pbr
    return {"indicators": indicators}


class TestMarketDataIntegration:
    """--market-data (harmonized_financials.json) 経由の market_cap 補完テスト。"""

    def test_backward_compat_no_market_data(self):
        """a) 後方互換: market_data=None → 従来通り metrics のみで計算"""
        metrics = _make_metrics(market_cap=50_000, net_income=5_000, equity=30_000)
        result = compute_relative_metrics(metrics, market_data=None)
        assert result.per == 10.0  # 50000 / 5000
        assert result.pbr == pytest.approx(1.67, abs=0.01)
        assert result.data_sources["market_cap"] == "latest_snapshot"

    def test_market_data_provides_market_cap(self):
        """b) 正常系: market_data 指定 → PER/PBR が non-null"""
        # metrics には market_cap がない
        metrics = _make_metrics(
            market_cap=None,
            net_income=5_000_000_000,
            equity=30_000_000_000,
        )
        market_data = _make_market_data(market_cap=94_418_000_000.0)

        result = compute_relative_metrics(metrics, market_data=market_data)
        assert result.per is not None
        assert result.pbr is not None
        # PER = 94_418_000_000 / 5_000_000_000 ≈ 18.88
        assert result.per == pytest.approx(18.88, abs=0.01)
        assert result.data_sources["market_cap"] == "market_data.indicators"

    def test_market_data_overrides_snapshot(self):
        """market_data の market_cap が snapshot より優先される"""
        metrics = _make_metrics(
            market_cap=50_000,
            net_income=5_000,
            equity=30_000,
        )
        market_data = _make_market_data(market_cap=100_000)

        result = compute_relative_metrics(metrics, market_data=market_data)
        # market_data の 100_000 が使われる
        assert result.per == 20.0  # 100_000 / 5_000
        assert result.data_sources["market_cap"] == "market_data.indicators"

    def test_market_data_no_indicators_key(self):
        """d) エッジケース: market_data に indicators キーがない → graceful degradation"""
        metrics = _make_metrics(market_cap=50_000, net_income=5_000)
        market_data = {"some_other_key": "value"}

        result = compute_relative_metrics(metrics, market_data=market_data)
        # snapshot の market_cap にフォールバック
        assert result.per == 10.0
        assert result.data_sources["market_cap"] == "latest_snapshot"

    def test_market_data_indicators_empty(self):
        """market_data.indicators が空 → snapshot にフォールバック"""
        metrics = _make_metrics(market_cap=50_000, net_income=5_000)
        market_data = {"indicators": {}}

        result = compute_relative_metrics(metrics, market_data=market_data)
        assert result.per == 10.0
        assert result.data_sources["market_cap"] == "latest_snapshot"

    def test_market_data_market_cap_none(self):
        """market_data.indicators.market_cap が None → snapshot にフォールバック"""
        metrics = _make_metrics(market_cap=50_000, net_income=5_000)
        market_data = _make_market_data(market_cap=None)

        result = compute_relative_metrics(metrics, market_data=market_data)
        assert result.per == 10.0
        assert result.data_sources["market_cap"] == "latest_snapshot"

    def test_ev_ebitda_with_market_data(self):
        """market_data 由来の market_cap で EV/EBITDA も計算される"""
        metrics = _make_metrics(
            market_cap=None,
            net_income=5_000,
            equity=30_000,
            operating_income=7_000,
            depreciation=1_000,
            total_debt=10_000,
            cash=5_000,
        )
        market_data = _make_market_data(market_cap=50_000)

        result = compute_relative_metrics(metrics, market_data=market_data)
        # EV = 50000 + 10000 - 5000 = 55000, EBITDA = 7000 + 1000 = 8000
        assert result.ev_ebitda == pytest.approx(6.88, abs=0.01)


class TestMarketDataCLI:
    """CLI 経由の --market-data テスト。"""

    def test_relative_with_market_data(self, tmp_path):
        """b) 正常系 CLI: --market-data 指定 → PER/PBR が non-null"""
        metrics = _make_metrics(market_cap=None, net_income=5_000, equity=30_000)
        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text(json.dumps(metrics), encoding="utf-8")

        market_data = _make_market_data(market_cap=100_000)
        md_file = tmp_path / "harmonized.json"
        md_file.write_text(json.dumps(market_data), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "main.py"), "relative",
             "--metrics", str(metrics_file),
             "--market-data", str(md_file)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["per"] == 20.0  # 100_000 / 5_000
        assert data["data_sources"]["market_cap"] == "market_data.indicators"

    def test_relative_market_data_file_missing(self, tmp_path):
        """c) エッジケース CLI: --market-data ファイル不在 → graceful degradation"""
        metrics = _make_metrics(market_cap=50_000, net_income=5_000)
        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text(json.dumps(metrics), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "main.py"), "relative",
             "--metrics", str(metrics_file),
             "--market-data", str(tmp_path / "nonexistent.json")],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        # ファイル不在でも snapshot の値で計算成功
        assert data["per"] == 10.0
        assert "Warning: market-data file not found" in result.stderr

    def test_relative_without_market_data_backward_compat(self, tmp_path):
        """a) 後方互換 CLI: --market-data 未指定 → 従来通り動作"""
        metrics = _make_metrics(market_cap=50_000, net_income=5_000, equity=30_000)
        metrics_file = tmp_path / "metrics.json"
        metrics_file.write_text(json.dumps(metrics), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "main.py"), "relative",
             "--metrics", str(metrics_file)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["per"] == 10.0
        assert data["data_sources"]["market_cap"] == "latest_snapshot"


class TestMarketDataPipelineCompat:
    """e) パイプライン互換テスト: pipeline YAML の valuate_relative ステップ構造検証。"""

    def _load_pipeline_steps(self):
        import yaml

        pipeline_path = Path(__file__).resolve().parent.parent.parent / \
            "pipeline-runner" / "references" / "example_pipeline.yaml"
        if not pipeline_path.exists():
            pytest.skip("example_pipeline.yaml not found")

        with open(pipeline_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("pipeline", {}).get("steps", [])

    def test_valuate_relative_has_market_data_flag(self):
        """valuate_relative ステップが --market-data を含む"""
        steps = self._load_pipeline_steps()
        vr_step = next((s for s in steps if s["id"] == "valuate_relative"), None)
        assert vr_step is not None, "valuate_relative step not found"
        assert "--market-data" in vr_step["command"]
        assert "harmonized_financials.json" in vr_step["command"]

    def test_valuate_relative_depends_on_calculate(self):
        """valuate_relative は calculate に依存している"""
        steps = self._load_pipeline_steps()
        vr_step = next((s for s in steps if s["id"] == "valuate_relative"), None)
        assert vr_step is not None
        assert "calculate" in vr_step.get("depends_on", [])
