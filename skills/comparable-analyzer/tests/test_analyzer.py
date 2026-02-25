"""comparable-analyzer テスト."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
from pathlib import Path

import pytest

# パッケージインポート対応
_script_dir = Path(__file__).resolve().parents[1] / "scripts"
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

from analyzer import (
    CacheNotFoundError,
    TickerNotFoundError,
    _extract_metrics,
    _load_edinet_csv,
    build_comparison_matrix,
    calculate_benchmarks,
    find_peers,
    run_analysis,
)

# ── テストデータ ──────────────────────────────────────────

CSV_FIELDNAMES = [
    "ＥＤＩＮＥＴコード",
    "提出者種別",
    "上場区分",
    "連結の有無",
    "資本金",
    "決算日",
    "提出者名",
    "提出者名（英字）",
    "提出者名（ヨミ）",
    "所在地",
    "提出者業種",
    "証券コード",
    "提出者法人番号",
]


def _make_row(
    edinet: str,
    name: str,
    sec_code: str,
    industry: str,
    listing: str = "上場",
) -> dict[str, str]:
    return {
        "ＥＤＩＮＥＴコード": edinet,
        "提出者種別": "",
        "上場区分": listing,
        "連結の有無": "",
        "資本金": "",
        "決算日": "3月31日",
        "提出者名": name,
        "提出者名（英字）": "",
        "提出者名（ヨミ）": "",
        "所在地": "",
        "提出者業種": industry,
        "証券コード": sec_code,
        "提出者法人番号": "",
    }


SAMPLE_ROWS = [
    _make_row("E02144", "トヨタ自動車株式会社", "72030", "輸送用機器"),
    _make_row("E02153", "本田技研工業株式会社", "72670", "輸送用機器"),
    _make_row("E02163", "日産自動車株式会社", "72010", "輸送用機器"),
    _make_row("E01777", "マツダ株式会社", "72610", "輸送用機器"),
    _make_row("E01786", "スズキ株式会社", "72690", "輸送用機器"),
    _make_row("E01620", "ソニーグループ株式会社", "67580", "電気機器"),
    _make_row("E01624", "パナソニック株式会社", "67520", "電気機器"),
    _make_row("E99999", "非上場テスト株式会社", "99990", "輸送用機器", listing="非上場"),
]


def _write_csv(cache_dir: Path, rows: list[dict[str, str]] | None = None) -> None:
    """テスト用 CSV をキャッシュディレクトリに書き込む."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    csv_path = cache_dir / "EdinetcodeDlInfo.csv"
    data = rows if rows is not None else SAMPLE_ROWS
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(data)


def _write_metrics(data_root: Path, ticker: str, snapshot: dict) -> None:
    """テスト用 metrics.json を作成."""
    parsed_dir = data_root / ticker / "parsed"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "ticker": ticker,
        "generated_at": "2026-01-01T00:00:00+00:00",
        "source_count": 1,
        "metrics_series": [snapshot],
        "latest_snapshot": snapshot,
    }
    with open(parsed_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


# ── テストケース ──────────────────────────────────────────


class TestFindPeers:
    """test_find_peers: 業種コードで同業他社を正しく抽出するか."""

    def test_find_peers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / ".ticker_cache"
            _write_csv(cache_dir)
            rows = _load_edinet_csv(cache_dir)

            peers, warnings = find_peers(rows, "7203", "輸送用機器", max_peers=10)
            peer_codes = [r["証券コード"] for r in peers]

            # トヨタ(72030)以外の輸送用機器企業が含まれる
            assert "72670" in peer_codes  # ホンダ
            assert "72010" in peer_codes  # 日産
            assert "72610" in peer_codes  # マツダ
            assert "72690" in peer_codes  # スズキ
            assert len(peers) == 4

    def test_find_peers_excludes_target(self) -> None:
        """test_find_peers_excludes_target: 対象企業自身を除外するか."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / ".ticker_cache"
            _write_csv(cache_dir)
            rows = _load_edinet_csv(cache_dir)

            peers, _ = find_peers(rows, "7203", "輸送用機器", max_peers=10)
            peer_codes = [r["証券コード"] for r in peers]

            assert "72030" not in peer_codes

    def test_find_peers_insufficient(self) -> None:
        """test_find_peers_insufficient: 候補不足時に警告が出るか."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / ".ticker_cache"
            # 電気機器は2社のみ（対象含む）
            _write_csv(cache_dir)
            rows = _load_edinet_csv(cache_dir)

            peers, warnings = find_peers(rows, "6758", "電気機器", max_peers=10)
            # ソニー以外はパナソニックの1社のみ → 3社未満
            assert len(peers) == 1
            assert any("候補が1社のみ" in w for w in warnings)

    def test_find_peers_max_limit(self) -> None:
        """max_peers で件数を制限できるか."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / ".ticker_cache"
            _write_csv(cache_dir)
            rows = _load_edinet_csv(cache_dir)

            peers, _ = find_peers(rows, "7203", "輸送用機器", max_peers=2)
            assert len(peers) == 2


class TestBuildComparisonMatrix:
    """test_build_comparison_matrix: 指標比較マトリクスの構造検証."""

    def test_build_comparison_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir)
            cache_dir = data_root / ".ticker_cache"
            _write_csv(cache_dir)

            _write_metrics(data_root, "7203", {
                "roe_percent": 12.5,
                "roa_percent": 5.0,
                "operating_margin_percent": 8.0,
                "revenue_growth_yoy_percent": 3.0,
            })
            _write_metrics(data_root, "7267", {
                "roe_percent": 10.0,
                "roa_percent": 4.5,
                "operating_margin_percent": 6.5,
                "revenue_growth_yoy_percent": 2.0,
            })

            rows = _load_edinet_csv(cache_dir)
            peers, _ = find_peers(rows, "7203", "輸送用機器")

            target_entry, peer_entries, warnings = build_comparison_matrix(
                data_root, "7203", "トヨタ自動車株式会社", "輸送用機器", peers,
            )

            assert target_entry["ticker"] == "7203"
            assert target_entry["metrics"]["roe"] == 12.5
            assert len(peer_entries) == 4

            # ホンダは metrics あり
            honda = next(p for p in peer_entries if p["ticker"] == "7267")
            assert honda["metrics"]["roe"] == 10.0
            assert honda["warnings"] == []

            # 日産は metrics なし
            nissan = next(p for p in peer_entries if p["ticker"] == "7201")
            assert nissan["metrics"]["roe"] is None
            assert len(nissan["warnings"]) > 0


class TestCalculateBenchmarks:
    """test_calculate_benchmarks: 四分位・統計値の算出精度."""

    def test_calculate_benchmarks(self) -> None:
        target_metrics = {"roe": 12.0, "roa": 5.0, "operating_margin": 8.0, "revenue_growth": 3.0}
        peer_entries = [
            {"ticker": "A", "metrics": {"roe": 10.0, "roa": 4.0, "operating_margin": 6.0, "revenue_growth": 2.0}},
            {"ticker": "B", "metrics": {"roe": 14.0, "roa": 6.0, "operating_margin": 10.0, "revenue_growth": 5.0}},
            {"ticker": "C", "metrics": {"roe": 8.0, "roa": 3.0, "operating_margin": 5.0, "revenue_growth": 1.0}},
            {"ticker": "D", "metrics": {"roe": 16.0, "roa": 7.0, "operating_margin": 12.0, "revenue_growth": 6.0}},
        ]

        benchmarks = calculate_benchmarks(target_metrics, peer_entries)

        assert "roe" in benchmarks
        assert "roa" in benchmarks
        assert "operating_margin" in benchmarks
        assert "revenue_growth" in benchmarks

        roe = benchmarks["roe"]
        # Values: [8, 10, 12, 14, 16] sorted
        assert roe["median"] == 12.0
        assert roe["mean"] == 12.0
        assert roe["std"] is not None
        assert roe["q1"] is not None
        assert roe["q3"] is not None
        assert roe["target_percentile"] is not None
        # 12.0 is the 3rd of 5 values → 60th percentile
        assert roe["target_percentile"] == 60.0

    def test_benchmark_single_value(self) -> None:
        """有効値が1つだけの場合."""
        target_metrics = {"roe": 10.0, "roa": None, "operating_margin": None, "revenue_growth": None}
        peer_entries = [
            {"ticker": "A", "metrics": {"roe": None, "roa": None, "operating_margin": None, "revenue_growth": None}},
        ]

        benchmarks = calculate_benchmarks(target_metrics, peer_entries)
        assert benchmarks["roe"]["median"] == 10.0
        assert benchmarks["roe"]["std"] is None
        assert benchmarks["roa"]["median"] is None


class TestMissingMetrics:
    """test_missing_metrics: metrics.json 未存在時のフォールバック."""

    def test_missing_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir)
            # metrics.json を作成しない
            target_entry, peer_entries, warnings = build_comparison_matrix(
                data_root, "7203", "トヨタ自動車株式会社", "輸送用機器", [],
            )

            # 全指標が null
            for val in target_entry["metrics"].values():
                assert val is None


class TestMissingCache:
    """test_missing_cache: キャッシュ未存在時のエラーメッセージ."""

    def test_missing_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir)
            cache_dir = data_root / ".ticker_cache"
            # CSV を作成しない

            with pytest.raises(CacheNotFoundError, match="ticker-resolver cache not found"):
                _load_edinet_csv(cache_dir)

    def test_missing_cache_in_run_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir)
            with pytest.raises(CacheNotFoundError, match="ticker-resolver cache not found"):
                run_analysis(data_root, "7203")


class TestRunAnalysis:
    """統合テスト: run_analysis の全体フロー."""

    def test_full_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir)
            cache_dir = data_root / ".ticker_cache"
            _write_csv(cache_dir)

            _write_metrics(data_root, "7203", {
                "roe_percent": 12.5,
                "roa_percent": 5.0,
                "operating_margin_percent": 8.0,
                "revenue_growth_yoy_percent": 3.0,
            })
            _write_metrics(data_root, "7267", {
                "roe_percent": 10.0,
                "roa_percent": 4.5,
                "operating_margin_percent": 6.5,
                "revenue_growth_yoy_percent": 2.0,
            })

            result = run_analysis(data_root, "7203", max_peers=10)

            assert result["schema_version"] == "comparable-analyzer-v1"
            assert result["target"]["ticker"] == "7203"
            assert result["peer_count"] == 4
            assert result["max_peers_requested"] == 10
            assert "benchmarks" in result

            # 出力ファイル確認
            out_path = data_root / "7203" / "parsed" / "comparables.json"
            assert out_path.exists()

            with open(out_path, encoding="utf-8") as f:
                saved = json.load(f)
            assert saved["schema_version"] == "comparable-analyzer-v1"
