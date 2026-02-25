"""comparable-analyzer: 業種コードから比較企業群を選定し財務指標ベンチマーク比較を行う."""

from __future__ import annotations

import csv
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CACHE_CSV_NAME = "EdinetcodeDlInfo.csv"

# metrics.json の指標キー
METRIC_KEYS = ("roe_percent", "roa_percent", "operating_margin_percent", "revenue_growth_yoy_percent")

# 出力 JSON の指標名マッピング
METRIC_OUTPUT_NAMES = {
    "roe_percent": "roe",
    "roa_percent": "roa",
    "operating_margin_percent": "operating_margin",
    "revenue_growth_yoy_percent": "revenue_growth",
}


class CacheNotFoundError(Exception):
    """ticker-resolver キャッシュが見つからない場合."""


class TickerNotFoundError(Exception):
    """対象ティッカーが EDINET CSV に見つからない場合."""


def _load_edinet_csv(cache_dir: Path) -> list[dict[str, str]]:
    """EdinetcodeDlInfo.csv を読み込み、上場企業のみ返す."""
    csv_path = cache_dir / CACHE_CSV_NAME
    if not csv_path.exists():
        raise CacheNotFoundError(
            "ticker-resolver cache not found. Run ticker-resolver update first."
        )

    rows: list[dict[str, str]] = []
    # Shift-JIS / UTF-8 両対応
    for enc in ("utf-8", "cp932"):
        try:
            with open(csv_path, encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                if reader.fieldnames is None:
                    return []
                for row in reader:
                    listing = row.get("上場区分", "").strip()
                    if not listing or listing == "非上場":
                        continue
                    sec_code = row.get("証券コード", "").strip()
                    if not sec_code:
                        continue
                    rows.append(row)
            break
        except UnicodeDecodeError:
            continue
    return rows


def _sec_code_from_ticker(ticker: str) -> str:
    """4桁ティッカーを5桁証券コードに変換."""
    return ticker.strip() + "0"


def _find_industry(rows: list[dict[str, str]], ticker: str) -> tuple[str, str]:
    """対象ティッカーの業種コードと企業名を返す."""
    sec_code = _sec_code_from_ticker(ticker)
    for row in rows:
        if row.get("証券コード", "").strip() == sec_code:
            industry = row.get("提出者業種", "").strip()
            company_name = row.get("提出者名", "").strip()
            if not industry:
                raise TickerNotFoundError(
                    f"Ticker {ticker}: 業種コード（提出者業種）が空です"
                )
            return industry, company_name
    raise TickerNotFoundError(f"Ticker {ticker} not found in EDINET cache")


def find_peers(
    rows: list[dict[str, str]],
    ticker: str,
    industry: str,
    max_peers: int = 10,
) -> tuple[list[dict[str, str]], list[str]]:
    """同業他社を選定する。対象企業自身は除外。

    Returns:
        (peers, warnings) - peers は最大 max_peers 件の行リスト、warnings は警告メッセージ
    """
    sec_code = _sec_code_from_ticker(ticker)
    peers: list[dict[str, str]] = []
    for row in rows:
        if row.get("提出者業種", "").strip() != industry:
            continue
        if row.get("証券コード", "").strip() == sec_code:
            continue
        peers.append(row)
        if len(peers) >= max_peers:
            break

    warnings: list[str] = []
    if len(peers) < 3:
        warnings.append(
            f"業種候補が{len(peers)}社のみ（基準3社未満）"
        )
    elif len(peers) < max_peers:
        warnings.append(
            f"業種候補が{len(peers)}社のみ（基準{max_peers}社未満）"
        )

    return peers, warnings


def _load_metrics(data_root: Path, ticker: str) -> dict[str, Any] | None:
    """data/{ticker}/parsed/metrics.json から最新スナップショットの指標を読み込む."""
    metrics_path = data_root / ticker / "parsed" / "metrics.json"
    if not metrics_path.exists():
        return None
    try:
        with open(metrics_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    snapshot = data.get("latest_snapshot")
    if snapshot:
        return snapshot

    series = data.get("metrics_series", [])
    if series:
        return series[-1]

    return None


def _extract_metrics(snapshot: dict[str, Any] | None) -> dict[str, float | None]:
    """スナップショットから比較用指標を抽出."""
    result: dict[str, float | None] = {}
    for key, out_name in METRIC_OUTPUT_NAMES.items():
        if snapshot is not None:
            val = snapshot.get(key)
            result[out_name] = float(val) if val is not None else None
        else:
            result[out_name] = None
    return result


def build_comparison_matrix(
    data_root: Path,
    target_ticker: str,
    target_company_name: str,
    target_industry: str,
    peers: list[dict[str, str]],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """指標比較マトリクスを構築する.

    Returns:
        (target_entry, peer_entries, warnings)
    """
    warnings: list[str] = []

    # 対象企業
    target_snapshot = _load_metrics(data_root, target_ticker)
    target_metrics = _extract_metrics(target_snapshot)
    target_entry = {
        "ticker": target_ticker,
        "company_name": target_company_name,
        "industry": target_industry,
        "metrics": target_metrics,
    }

    # 比較企業
    peer_entries: list[dict[str, Any]] = []
    for peer_row in peers:
        sec_code = peer_row.get("証券コード", "").strip()
        peer_ticker = sec_code[:-1] if len(sec_code) == 5 else sec_code
        peer_name = peer_row.get("提出者名", "").strip()

        peer_snapshot = _load_metrics(data_root, peer_ticker)
        peer_metrics = _extract_metrics(peer_snapshot)
        peer_warnings: list[str] = []
        if peer_snapshot is None:
            peer_warnings.append(f"metrics.json not found for {peer_ticker}")
            warnings.append(f"metrics.json not found for {peer_ticker}")

        peer_entries.append({
            "ticker": peer_ticker,
            "company_name": peer_name,
            "metrics": peer_metrics,
            "warnings": peer_warnings,
        })

    return target_entry, peer_entries, warnings


def calculate_benchmarks(
    target_metrics: dict[str, float | None],
    peer_entries: list[dict[str, Any]],
) -> dict[str, dict[str, float | None]]:
    """各指標の統計値と対象企業のパーセンタイルを算出."""
    benchmarks: dict[str, dict[str, float | None]] = {}

    for out_name in METRIC_OUTPUT_NAMES.values():
        # 全企業（対象含む）の有効値を収集
        all_values: list[float] = []
        if target_metrics.get(out_name) is not None:
            all_values.append(target_metrics[out_name])  # type: ignore[arg-type]
        for peer in peer_entries:
            val = peer.get("metrics", {}).get(out_name)
            if val is not None:
                all_values.append(float(val))

        if len(all_values) < 2:
            benchmarks[out_name] = {
                "median": all_values[0] if all_values else None,
                "mean": all_values[0] if all_values else None,
                "std": None,
                "q1": None,
                "q3": None,
                "target_percentile": None,
            }
            continue

        sorted_vals = sorted(all_values)
        n = len(sorted_vals)
        median_val = round(statistics.median(sorted_vals), 2)
        mean_val = round(statistics.mean(sorted_vals), 2)
        std_val = round(statistics.stdev(sorted_vals), 2)

        # 四分位
        q1 = round(statistics.median(sorted_vals[: n // 2]), 2)
        q3_start = n // 2 + (1 if n % 2 else 0)
        q3 = round(statistics.median(sorted_vals[q3_start:]), 2)

        # 対象企業のパーセンタイル
        target_val = target_metrics.get(out_name)
        if target_val is not None:
            rank = sum(1 for v in sorted_vals if v <= float(target_val))
            target_percentile = round(rank / n * 100, 1)
        else:
            target_percentile = None

        benchmarks[out_name] = {
            "median": median_val,
            "mean": mean_val,
            "std": std_val,
            "q1": q1,
            "q3": q3,
            "target_percentile": target_percentile,
        }

    return benchmarks


def run_analysis(
    data_root: Path,
    ticker: str,
    max_peers: int = 10,
) -> dict[str, Any]:
    """comparable-analyzer のメインエントリポイント."""
    cache_dir = data_root / ".ticker_cache"
    rows = _load_edinet_csv(cache_dir)

    industry, company_name = _find_industry(rows, ticker)
    peers, peer_warnings = find_peers(rows, ticker, industry, max_peers)

    target_entry, peer_entries, matrix_warnings = build_comparison_matrix(
        data_root, ticker, company_name, industry, peers,
    )

    benchmarks = calculate_benchmarks(target_entry["metrics"], peer_entries)

    all_warnings = peer_warnings + matrix_warnings

    # missing peer 判定: 全指標が None の peer
    missing_peers: list[dict[str, str]] = []
    for peer in peer_entries:
        metrics = peer.get("metrics", {})
        if all(v is None for v in metrics.values()):
            missing_peers.append({
                "ticker": peer["ticker"],
                "company_name": peer["company_name"],
                "reason": "metrics.json not found or all metrics null",
            })

    missing_peers_count = len(missing_peers)
    total_peer_count = len(peer_entries)
    benchmark_reliable = missing_peers_count < total_peer_count if total_peer_count > 0 else False

    if missing_peers_count == total_peer_count and total_peer_count > 0:
        all_warnings.append("全peerのmetricsが欠損しています。ベンチマーク比較の信頼性が低下しています")

    output: dict[str, Any] = {
        "schema_version": "comparable-analyzer-v1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "target": target_entry,
        "peers": peer_entries,
        "benchmarks": benchmarks,
        "warnings": all_warnings,
        "peer_count": total_peer_count,
        "max_peers_requested": max_peers,
        "missing_peers": missing_peers,
        "missing_peers_count": missing_peers_count,
        "benchmark_reliable": benchmark_reliable,
    }

    # 出力ディレクトリ作成と書き込み
    out_dir = data_root / ticker / "parsed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "comparables.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    return output
