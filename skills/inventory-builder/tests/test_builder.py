"""inventory-builder テストスイート。

単体テスト・JSON欠損キーバリデーション・統合テスト・CLIテストを含む。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

# ── builder モジュールのインポート ──

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from builder import (  # noqa: E402
    InventoryBuildError,
    analyze_gaps,
    build_coverage_matrix,
    build_inventory,
    calculate_quality_summary,
    classify_period,
    generate_inventory_md,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = REPO_ROOT / "data"


# ============================================================
# 1. 単体テスト
# ============================================================


class TestClassifyPeriod:
    """classify_period のテスト。"""

    # ---- fye_month=3 (3月期) ----

    def test_annual_march(self):
        result = classify_period(
            date(2024, 3, 31), fye_month=3, period_start=date(2023, 4, 1)
        )
        assert result == "annual"

    def test_q1_march(self):
        result = classify_period(
            date(2023, 6, 30), fye_month=3, period_start=date(2023, 4, 1)
        )
        assert result == "q1"

    def test_q2_march(self):
        result = classify_period(
            date(2023, 9, 30), fye_month=3, period_start=date(2023, 4, 1)
        )
        assert result == "q2"

    def test_q3_march(self):
        result = classify_period(
            date(2023, 12, 31), fye_month=3, period_start=date(2023, 4, 1)
        )
        assert result == "q3"

    def test_h1_march_post_reform(self):
        """2024年度以降の period_start>=2024-04-01 で H1 判定。"""
        result = classify_period(
            date(2024, 9, 30), fye_month=3, period_start=date(2024, 4, 1)
        )
        assert result == "h1"

    # ---- fye_month=12 (12月期) ----

    def test_annual_december(self):
        result = classify_period(
            date(2024, 12, 31), fye_month=12, period_start=date(2024, 1, 1)
        )
        assert result == "annual"

    def test_q1_december(self):
        result = classify_period(
            date(2024, 3, 31), fye_month=12, period_start=date(2024, 1, 1)
        )
        assert result == "q1"

    def test_q2_december(self):
        result = classify_period(
            date(2024, 6, 30), fye_month=12, period_start=date(2024, 1, 1)
        )
        assert result == "q2"


class TestBuildCoverageMatrix:
    """build_coverage_matrix のテスト。"""

    def test_basic_matrix(self):
        documents = [
            {
                "doc_id": "D001",
                "period_end": date(2023, 3, 31),
                "period_start": date(2022, 4, 1),
                "period_type": "annual",
                "fiscal_year": 2023,
            },
            {
                "doc_id": "D002",
                "period_end": date(2022, 6, 30),
                "period_start": date(2022, 4, 1),
                "period_type": "q1",
                "fiscal_year": 2022,
            },
            {
                "doc_id": "D003",
                "period_end": date(2022, 9, 30),
                "period_start": date(2022, 4, 1),
                "period_type": "q2",
                "fiscal_year": 2022,
            },
            {
                "doc_id": "D004",
                "period_end": date(2022, 12, 31),
                "period_start": date(2022, 4, 1),
                "period_type": "q3",
                "fiscal_year": 2022,
            },
        ]
        result = build_coverage_matrix(documents, fye_month=3)

        assert result["years"] == [2022, 2023]
        assert result["matrix"][2023]["annual"] == "D001"
        assert result["matrix"][2022]["q1"] == "D002"
        assert result["matrix"][2022]["q2"] == "D003"
        assert result["matrix"][2022]["q3"] == "D004"
        # 未登録のセルは None
        assert result["matrix"][2022]["annual"] is None
        assert result["matrix"][2023]["q1"] is None


class TestAnalyzeGaps:
    """analyze_gaps のテスト。"""

    def test_acceptable_gaps(self):
        """IPO 以前の最初の年度と 2024年度以降の Q1/Q3 廃止。"""
        matrix = {
            "years": [2023, 2025],
            "matrix": {
                2023: {
                    "q1": None,
                    "q2": "D1",
                    "q3": None,
                    "h1": None,
                    "annual": "D2",
                    "jquants": None,
                },
                2025: {
                    "q1": None,
                    "q2": None,
                    "q3": None,
                    "h1": "D3",
                    "annual": None,
                    "jquants": None,
                },
            },
        }
        result = analyze_gaps(matrix, fye_month=3)

        acceptable_keys = {
            (g["fiscal_year"], g["quarter"]) for g in result["acceptable"]
        }
        # FY2023 は最初の年度 → Q1, Q3 は許容
        assert (2023, "Q1") in acceptable_keys
        assert (2023, "Q3") in acceptable_keys
        # FY2025: Q1, Q3 は 2024年4月施行後 → 許容
        assert (2025, "Q1") in acceptable_keys
        assert (2025, "Q3") in acceptable_keys
        # FY2025: 最新年度の有報 → 許容
        assert (2025, "有報") in acceptable_keys

    def test_actionable_gaps(self):
        """存在すべき有報の欠損は要対応。"""
        matrix = {
            "years": [2022, 2023, 2024],
            "matrix": {
                2022: {
                    "q1": "D1",
                    "q2": "D2",
                    "q3": "D3",
                    "h1": None,
                    "annual": "D4",
                    "jquants": None,
                },
                2023: {
                    "q1": None,
                    "q2": None,
                    "q3": None,
                    "h1": None,
                    "annual": None,
                    "jquants": None,
                },
                2024: {
                    "q1": "D5",
                    "q2": "D6",
                    "q3": "D7",
                    "h1": None,
                    "annual": "D8",
                    "jquants": None,
                },
            },
        }
        result = analyze_gaps(matrix, fye_month=3)

        actionable_keys = {
            (g["fiscal_year"], g["quarter"]) for g in result["actionable"]
        }
        # FY2023: 中間年度の有報欠損 → 要対応
        assert (2023, "有報") in actionable_keys
        # FY2023: 中間年度の Q1/Q2/Q3 欠損 → 要対応
        assert (2023, "Q1") in actionable_keys
        assert (2023, "Q2") in actionable_keys
        assert (2023, "Q3") in actionable_keys


class TestCalculateQualitySummary:
    """calculate_quality_summary のテスト。"""

    def test_non_null_ratio(self):
        financials = {
            "documents": [
                {
                    "document_id": "D1",
                    "periods": [
                        {
                            "period_end": "2023-03-31",
                            "period_start": "2022-04-01",
                            "bs": {
                                "total_assets": 1000,
                                "total_equity": 500,
                                "net_assets": 600,
                                "total_liabilities": 400,
                            },
                            "pl": {
                                "revenue": 2000,
                                "operating_income": 100,
                                "net_income": 50,
                            },
                            "cf": {"operating_cf": 200},
                        }
                    ],
                },
                {
                    "document_id": "D2",
                    "periods": [
                        {
                            "period_end": "2024-03-31",
                            "period_start": "2023-04-01",
                            "bs": {
                                "total_assets": 1200,
                                "total_equity": 600,
                                "net_assets": 700,
                                "total_liabilities": None,
                            },
                            "pl": {
                                "revenue": 2500,
                                "operating_income": 150,
                                "net_income": 80,
                            },
                            "cf": {"operating_cf": None},
                        }
                    ],
                },
            ]
        }
        result = calculate_quality_summary(financials)

        assert result["total"] == 2
        assert result["metrics"]["revenue"]["count"] == 2
        assert result["metrics"]["revenue"]["ratio"] == 1.0
        assert result["metrics"]["operating_cf"]["count"] == 1
        assert result["metrics"]["operating_cf"]["ratio"] == 0.5
        assert result["metrics"]["total_liabilities"]["count"] == 1
        assert result["metrics"]["total_liabilities"]["ratio"] == 0.5

    def test_all_null_metrics(self):
        """全メトリクスが null の場合は 0%。"""
        financials = {
            "documents": [
                {
                    "document_id": "D1",
                    "periods": [
                        {
                            "period_end": "2023-03-31",
                            "period_start": "2022-04-01",
                            "bs": {
                                "total_assets": None,
                                "total_equity": None,
                                "net_assets": None,
                                "total_liabilities": None,
                            },
                            "pl": {
                                "revenue": None,
                                "operating_income": None,
                                "net_income": None,
                            },
                            "cf": {"operating_cf": None},
                        }
                    ],
                }
            ]
        }
        result = calculate_quality_summary(financials)

        assert result["total"] == 1
        for metric_info in result["metrics"].values():
            assert metric_info["count"] == 0
            assert metric_info["ratio"] == 0.0


class TestGenerateInventoryMd:
    """generate_inventory_md のテスト。"""

    @pytest.fixture()
    def sample_context(self):
        return {
            "ticker": "9999",
            "fye_month": 3,
            "edinet_code": "E99999",
            "company_name": "テスト株式会社",
            "documents": [
                {
                    "doc_id": "D001",
                    "period_end": date(2023, 3, 31),
                    "period_start": date(2022, 4, 1),
                    "period_type": "annual",
                    "fiscal_year": 2023,
                    "company_name": "テスト株式会社",
                    "source_file": "manifest.json",
                    "fetched_at": "2026-01-01T00:00:00+00:00",
                },
            ],
            "coverage": {
                "years": [2023],
                "matrix": {
                    2023: {
                        "q1": None,
                        "q2": None,
                        "q3": None,
                        "h1": None,
                        "annual": "D001",
                        "jquants": None,
                    }
                },
            },
            "gaps": {"acceptable": [], "actionable": []},
            "quality": {
                "total": 1,
                "metrics": {
                    "revenue": {"count": 1, "ratio": 1.0},
                    "operating_income": {"count": 1, "ratio": 1.0},
                    "net_income": {"count": 1, "ratio": 1.0},
                    "total_assets": {"count": 1, "ratio": 1.0},
                    "total_equity": {"count": 1, "ratio": 1.0},
                    "net_assets": {"count": 1, "ratio": 1.0},
                    "operating_cf": {"count": 0, "ratio": 0.0},
                    "total_liabilities": {"count": 0, "ratio": 0.0},
                },
            },
            "jquants_available": False,
            "manifest_sources": [
                {"file": "manifest.json", "fetched_at": "2026-01-01T00:00:00+00:00"}
            ],
        }

    def test_all_sections_present(self, sample_context):
        md = generate_inventory_md(sample_context)

        section_patterns = [
            r"##\s*\(a\)\s*収集概要",
            r"##\s*\(b\)\s*書類種別ごとの収集状況表",
            r"##\s*\(c\)\s*文書一覧",
            r"##\s*\(d\)\s*年度×四半期カバレッジマトリクス",
            r"##\s*\(e\)\s*データ品質サマリ",
            r"##\s*\(f\)\s*データ分析ノート",
            r"##\s*\(g\)\s*欠損リスト",
            r"##\s*\(h\)\s*再現コマンド一覧",
            r"##\s*\(i\)\s*後続タスクへの推奨事項",
        ]
        for pattern in section_patterns:
            assert re.search(pattern, md), f"セクション未検出: {pattern}"


# ============================================================
# 2. JSON 欠損キーのバリデーションテスト
# ============================================================


class TestMissingJsonKeys:
    """JSON キーが欠損した場合のエラーハンドリング。"""

    def _make_edinet_dir(self, tmp_path, manifest_data):
        ticker_dir = tmp_path / "XXXX" / "raw" / "edinet"
        ticker_dir.mkdir(parents=True)
        (ticker_dir / "manifest.json").write_text(
            json.dumps(manifest_data), encoding="utf-8"
        )
        return tmp_path

    def test_manifest_no_results_key(self, tmp_path):
        """manifest.json に results キーが無い場合。"""
        data_root = self._make_edinet_dir(tmp_path, {"fetched_at": "2026-01-01"})
        with pytest.raises(InventoryBuildError, match="manifest に文書が含まれていません"):
            build_inventory("XXXX", fye_month=3, data_root=data_root)

    def test_financials_no_documents_key(self, tmp_path):
        """financials.json に documents キーが無い場合。"""
        data_root = self._make_edinet_dir(
            tmp_path,
            {
                "results": [{"doc_id": "D1", "period_end": "2023-03-31"}],
                "fetched_at": "2026-01-01",
            },
        )
        parsed_dir = tmp_path / "XXXX" / "parsed"
        parsed_dir.mkdir(parents=True)
        (parsed_dir / "financials.json").write_text(
            json.dumps({"ticker": "XXXX"}), encoding="utf-8"
        )
        # documents キーが無くてもエラーにならず空の品質サマリになる
        out = build_inventory(
            "XXXX", fye_month=3, data_root=data_root, output_path=tmp_path / "out.md"
        )
        md = out.read_text(encoding="utf-8")
        assert "品質" in md or "(e)" in md

    def test_documents_empty_periods(self, tmp_path):
        """documents[].periods が空配列の場合。"""
        financials = {
            "documents": [
                {"document_id": "D1", "periods": []}
            ]
        }
        result = calculate_quality_summary(financials)
        # periods が空 → current period 見つからず → total=0
        assert result["total"] == 0

    def test_bs_pl_cf_null_values(self):
        """bs/pl/cf の個別キーが null の場合の品質サマリ計算。"""
        financials = {
            "documents": [
                {
                    "document_id": "D1",
                    "periods": [
                        {
                            "period_end": "2023-03-31",
                            "period_start": "2022-04-01",
                            "bs": {
                                "total_assets": None,
                                "total_equity": 500,
                                "net_assets": None,
                                "total_liabilities": None,
                            },
                            "pl": {
                                "revenue": 1000,
                                "operating_income": None,
                                "net_income": None,
                            },
                            "cf": {"operating_cf": None},
                        }
                    ],
                }
            ]
        }
        result = calculate_quality_summary(financials)
        assert result["total"] == 1
        assert result["metrics"]["revenue"]["count"] == 1
        assert result["metrics"]["total_assets"]["count"] == 0
        assert result["metrics"]["operating_income"]["count"] == 0
        assert result["metrics"]["total_equity"]["count"] == 1


class TestEmptyInputs:
    """空入力に対するテスト。"""

    def _make_edinet_dir(self, tmp_path, manifest_data):
        ticker_dir = tmp_path / "XXXX" / "raw" / "edinet"
        ticker_dir.mkdir(parents=True)
        (ticker_dir / "manifest.json").write_text(
            json.dumps(manifest_data), encoding="utf-8"
        )
        return tmp_path

    def test_manifest_results_empty_array(self, tmp_path):
        """manifest.json の results が空配列。"""
        data_root = self._make_edinet_dir(
            tmp_path, {"results": [], "fetched_at": "2026-01-01"}
        )
        with pytest.raises(InventoryBuildError, match="manifest に文書が含まれていません"):
            build_inventory("XXXX", fye_month=3, data_root=data_root)

    def test_financials_documents_empty_array(self):
        """financials.json の documents が空配列。"""
        financials = {"documents": []}
        result = calculate_quality_summary(financials)
        assert result["total"] == 0
        for metric_info in result["metrics"].values():
            assert metric_info["count"] == 0
            assert metric_info["ratio"] == 0.0


# ============================================================
# 3. 統合テスト
# ============================================================


@pytest.mark.skipif(
    not (DATA_ROOT / "2780" / "raw" / "edinet" / "manifest.json").exists(),
    reason="data/2780 実データが存在しない",
)
def test_integration_2780(tmp_path):
    """data/2780 の実データで build_inventory() を実行。"""
    output = tmp_path / "inventory_2780.md"
    result = build_inventory(
        "2780", fye_month=3, data_root=DATA_ROOT, output_path=output
    )
    assert result.exists()
    md = result.read_text(encoding="utf-8")

    section_patterns = [
        r"##\s*\(a\)\s*収集概要",
        r"##\s*\(b\)\s*書類種別ごとの収集状況表",
        r"##\s*\(c\)\s*文書一覧",
        r"##\s*\(d\)\s*年度×四半期カバレッジマトリクス",
        r"##\s*\(e\)\s*データ品質サマリ",
        r"##\s*\(f\)\s*データ分析ノート",
        r"##\s*\(g\)\s*欠損リスト",
        r"##\s*\(h\)\s*再現コマンド一覧",
        r"##\s*\(i\)\s*後続タスクへの推奨事項",
    ]
    for pattern in section_patterns:
        assert re.search(pattern, md), f"セクション未検出: {pattern}"


@pytest.mark.skipif(
    not (DATA_ROOT / "7685" / "raw" / "edinet" / "manifest.json").exists(),
    reason="data/7685 実データが存在しない",
)
def test_integration_7685(tmp_path):
    """data/7685 の実データで build_inventory() を実行 (fye_month=12)。"""
    output = tmp_path / "inventory_7685.md"
    result = build_inventory(
        "7685", fye_month=12, data_root=DATA_ROOT, output_path=output
    )
    assert result.exists()
    md = result.read_text(encoding="utf-8")

    section_patterns = [
        r"##\s*\(a\)\s*収集概要",
        r"##\s*\(b\)\s*書類種別ごとの収集状況表",
        r"##\s*\(c\)\s*文書一覧",
        r"##\s*\(d\)\s*年度×四半期カバレッジマトリクス",
        r"##\s*\(e\)\s*データ品質サマリ",
        r"##\s*\(f\)\s*データ分析ノート",
        r"##\s*\(g\)\s*欠損リスト",
        r"##\s*\(h\)\s*再現コマンド一覧",
        r"##\s*\(i\)\s*後続タスクへの推奨事項",
    ]
    for pattern in section_patterns:
        assert re.search(pattern, md), f"セクション未検出: {pattern}"

    # J-Quants データが統合されていることを確認
    assert "J-Quants" in md


@pytest.mark.skipif(
    not (DATA_ROOT / "2780" / "raw" / "edinet" / "manifest.json").exists(),
    reason="data/2780 実データが存在しない",
)
def test_jquants_optional(tmp_path):
    """J-Quants データが無くてもエラーにならないことを確認。"""
    # 2780 のデータを J-Quants 無しのディレクトリにコピー
    import shutil

    ticker_dir = tmp_path / "2780"
    raw_edinet = ticker_dir / "raw" / "edinet"
    raw_edinet.mkdir(parents=True)

    # manifest だけコピー
    src_manifest = DATA_ROOT / "2780" / "raw" / "edinet" / "manifest.json"
    shutil.copy2(src_manifest, raw_edinet / "manifest.json")

    # parsed もコピー
    parsed_src = DATA_ROOT / "2780" / "parsed"
    if parsed_src.exists():
        parsed_dst = ticker_dir / "parsed"
        parsed_dst.mkdir(parents=True)
        fin_src = parsed_src / "financials.json"
        if fin_src.exists():
            shutil.copy2(fin_src, parsed_dst / "financials.json")

    # jquants ディレクトリは作らない → J-Quants データ無し
    output = tmp_path / "inventory_no_jquants.md"
    result = build_inventory(
        "2780", fye_month=3, data_root=tmp_path, output_path=output
    )
    assert result.exists()
    md = result.read_text(encoding="utf-8")

    # J-Quants 関連が適切にスキップされている
    assert "J-Quants API" not in md
    # 基本セクションは存在する
    assert "(a) 収集概要" in md
    assert "(d) 年度×四半期カバレッジマトリクス" in md


# ============================================================
# 4. CLI テスト
# ============================================================


def test_cli_help():
    """main.py --help が正常終了すること。"""
    main_py = SCRIPTS_DIR / "main.py"
    result = subprocess.run(
        [sys.executable, str(main_py), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "ticker" in result.stdout.lower()


@pytest.mark.skipif(
    not (DATA_ROOT / "2780" / "raw" / "edinet" / "manifest.json").exists(),
    reason="data/2780 実データが存在しない",
)
def test_cli_execution(tmp_path):
    """main.py --ticker 2780 --fye-month 3 が正常終了し inventory.md を生成。"""
    main_py = SCRIPTS_DIR / "main.py"
    output = tmp_path / "inventory.md"
    result = subprocess.run(
        [
            sys.executable,
            str(main_py),
            "--ticker",
            "2780",
            "--fye-month",
            "3",
            "--data-root",
            str(DATA_ROOT),
            "--output-path",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert output.exists()
    md = output.read_text(encoding="utf-8")
    assert "(a) 収集概要" in md
