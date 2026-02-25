"""valuation-calculator 計算ロジック

DCF（割引キャッシュフロー）と相対バリュエーション（PER/PBR/EV-EBITDA）を計算する。
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# DCF
# ---------------------------------------------------------------------------

@dataclass
class DCFResult:
    enterprise_value: float
    equity_value: float
    per_share_value: float | None
    assumptions: dict[str, Any]


def compute_dcf(
    fcf_series: list[float],
    wacc: float = 0.08,
    terminal_growth_rate: float = 0.02,
    net_debt: float = 0.0,
    shares_outstanding: float | None = None,
    projection_years: int = 5,
) -> DCFResult:
    """FCF系列からDCFベースの企業価値を算出する。

    Parameters
    ----------
    fcf_series : list[float]
        過去のフリーキャッシュフロー系列（古い→新しい順）。
        最新年のFCFをベースに将来FCFを予測する。
    wacc : float
        加重平均資本コスト。
    terminal_growth_rate : float
        永久成長率。
    net_debt : float
        純有利子負債（有利子負債 − 現金）。enterprise_value から差し引いて equity_value を算出。
    shares_outstanding : float | None
        発行済株式数。指定時に per_share_value を算出。
    projection_years : int
        FCF予測期間。
    """
    if not fcf_series:
        raise ValueError("fcf_series is empty")
    if wacc <= terminal_growth_rate:
        raise ValueError(
            f"wacc ({wacc}) must be greater than terminal_growth_rate ({terminal_growth_rate})"
        )
    if wacc <= 0:
        raise ValueError(f"wacc must be positive, got {wacc}")

    base_fcf = fcf_series[-1]

    # FCF成長率の推定: 系列が2年以上あれば CAGR、1年なら terminal_growth_rate をそのまま使用
    if len(fcf_series) >= 2 and fcf_series[0] > 0 and base_fcf > 0:
        n = len(fcf_series) - 1
        cagr = (base_fcf / fcf_series[0]) ** (1 / n) - 1
        # 極端な成長率はクランプ
        growth = max(min(cagr, 0.30), -0.10)
    else:
        growth = terminal_growth_rate

    # 将来FCFの現在価値
    pv_fcfs = 0.0
    projected_fcf = base_fcf
    for year in range(1, projection_years + 1):
        projected_fcf *= 1 + growth
        pv_fcfs += projected_fcf / (1 + wacc) ** year

    # ターミナルバリュー（永久成長率モデル）
    terminal_fcf = projected_fcf * (1 + terminal_growth_rate)
    terminal_value = terminal_fcf / (wacc - terminal_growth_rate)
    pv_terminal = terminal_value / (1 + wacc) ** projection_years

    enterprise_value = pv_fcfs + pv_terminal
    equity_value = enterprise_value - net_debt

    per_share = None
    if shares_outstanding and shares_outstanding > 0:
        per_share = equity_value / shares_outstanding

    return DCFResult(
        enterprise_value=round(enterprise_value, 2),
        equity_value=round(equity_value, 2),
        per_share_value=round(per_share, 2) if per_share is not None else None,
        assumptions={
            "wacc": wacc,
            "terminal_growth_rate": terminal_growth_rate,
            "projection_years": projection_years,
            "base_fcf": base_fcf,
            "estimated_growth_rate": round(growth, 6),
            "net_debt": net_debt,
            "shares_outstanding": shares_outstanding,
        },
    )


# ---------------------------------------------------------------------------
# 相対バリュエーション
# ---------------------------------------------------------------------------

@dataclass
class RelativeMetrics:
    ticker: str
    per: float | None = None
    pbr: float | None = None
    ev_ebitda: float | None = None
    data_sources: dict[str, str] | None = None


@dataclass
class RelativeResult:
    target: RelativeMetrics
    peers: list[RelativeMetrics] = field(default_factory=list)
    comparison: dict[str, Any] = field(default_factory=dict)


def _safe_divide(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def compute_relative_metrics(metrics: dict[str, Any]) -> RelativeMetrics:
    """metrics.json の latest_snapshot からPER/PBR/EV-EBITDAを計算する。

    データ補完フォールバック（優先度順）:
      1. latest_snapshot の直接値（market_cap, net_income, equity 等）
         - market_data_collector が listed_info.json / market_data.json 経由で
           時価総額を latest_snapshot.market_cap に格納している場合はこれを使用。
      2. latest_snapshot に market_cap が欠損している場合:
         → metrics_series の最新年度（末尾要素）から market_cap を取得。
         → 同様に net_income, equity も欠損時は metrics_series から補完。
         ※ metrics_series の market_cap は決算期末時点の値であり、
           market_data_collector のリアルタイム時価総額とは乖離しうる。
      3. EBITDA は snapshot.ebitda → (operating_income + depreciation) の順で近似。
      4. いずれのソースにも値がない場合は None を返す（計算不能）。

    data_sources フィールドで各値の取得元を追跡可能にする。
    """
    ticker = metrics.get("ticker", "unknown")
    snapshot = metrics.get("latest_snapshot") or {}
    series = metrics.get("metrics_series") or []
    sources: dict[str, str] = {}

    market_cap = snapshot.get("market_cap")
    net_income = snapshot.get("net_income")
    equity = snapshot.get("equity")
    total_debt = snapshot.get("total_debt", 0) or 0
    cash = snapshot.get("cash_and_equivalents", 0) or 0

    if market_cap is not None:
        sources["market_cap"] = "latest_snapshot"
    if net_income is not None:
        sources["net_income"] = "latest_snapshot"
    if equity is not None:
        sources["equity"] = "latest_snapshot"

    # EBITDA の取得: snapshot に直接あるか、operating_income + depreciation で近似
    ebitda = snapshot.get("ebitda")
    if ebitda is not None:
        sources["ebitda"] = "latest_snapshot.ebitda"
    else:
        op_income = snapshot.get("operating_income")
        depreciation = snapshot.get("depreciation", 0) or 0
        if op_income is not None:
            ebitda = op_income + depreciation
            sources["ebitda"] = "latest_snapshot.operating_income+depreciation"

    # フォールバック: latest_snapshot に market_cap がない場合、
    # metrics_series の最新年度から取得を試みる。
    # 注意: metrics_series の値は決算期末時点であり、
    # market_data_collector のリアルタイム時価総額とは乖離する可能性がある。
    if market_cap is None and series:
        latest = series[-1]
        market_cap = latest.get("market_cap")
        if market_cap is not None:
            sources["market_cap"] = f"metrics_series[{latest.get('fiscal_year', '?')}]"
        if net_income is None:
            net_income = latest.get("net_income")
            if net_income is not None:
                sources["net_income"] = f"metrics_series[{latest.get('fiscal_year', '?')}]"
        if equity is None:
            equity = latest.get("equity")
            if equity is not None:
                sources["equity"] = f"metrics_series[{latest.get('fiscal_year', '?')}]"

    per = _safe_divide(market_cap, net_income)
    pbr = _safe_divide(market_cap, equity)

    ev_ebitda_val = None
    if market_cap is not None and ebitda is not None and ebitda != 0:
        ev = market_cap + total_debt - cash
        ev_ebitda_val = ev / ebitda

    return RelativeMetrics(
        ticker=ticker,
        per=round(per, 2) if per is not None else None,
        pbr=round(pbr, 2) if pbr is not None else None,
        ev_ebitda=round(ev_ebitda_val, 2) if ev_ebitda_val is not None else None,
        data_sources=sources if sources else None,
    )


def compute_peer_comparison(
    target_metrics: dict[str, Any],
    peer_metrics_list: list[dict[str, Any]],
) -> RelativeResult:
    """対象銘柄と同業他社の相対バリュエーションを比較する。"""
    target = compute_relative_metrics(target_metrics)
    peers = [compute_relative_metrics(p) for p in peer_metrics_list]

    comparison: dict[str, Any] = {}
    for metric_name in ("per", "pbr", "ev_ebitda"):
        peer_vals = [
            getattr(p, metric_name) for p in peers if getattr(p, metric_name) is not None
        ]
        target_val = getattr(target, metric_name)

        if not peer_vals or target_val is None:
            comparison[metric_name] = {
                "target": target_val,
                "peer_median": None,
                "peer_average": None,
                "vs_median": None,
                "vs_average": None,
            }
            continue

        median_val = statistics.median(peer_vals)
        average_val = statistics.mean(peer_vals)

        comparison[metric_name] = {
            "target": target_val,
            "peer_median": round(median_val, 2),
            "peer_average": round(average_val, 2),
            "vs_median": round(target_val - median_val, 2),
            "vs_average": round(target_val - average_val, 2),
        }

    return RelativeResult(target=target, peers=peers, comparison=comparison)


# ---------------------------------------------------------------------------
# metrics.json ヘルパー
# ---------------------------------------------------------------------------

def extract_fcf_series(metrics: dict[str, Any]) -> list[float]:
    """metrics.json から FCF 系列を抽出する（古い→新しい順）。"""
    series = metrics.get("metrics_series") or []
    fcf_values = []
    for entry in series:
        fcf = entry.get("free_cash_flow")
        if fcf is not None:
            fcf_values.append(float(fcf))
    return fcf_values


def extract_net_debt(metrics: dict[str, Any]) -> float:
    """latest_snapshot から純有利子負債を推定する。"""
    snapshot = metrics.get("latest_snapshot") or {}
    total_debt = snapshot.get("total_debt", 0) or 0
    cash = snapshot.get("cash_and_equivalents", 0) or 0
    return float(total_debt - cash)
