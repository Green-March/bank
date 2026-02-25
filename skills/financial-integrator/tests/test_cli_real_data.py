"""financial-integrator 実データ統合テスト

実データ (data/{ticker}/parsed/financials.json) が存在する場合のみ実行。
pytest.mark.skipif で実データ不在時はスキップする。
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA_ROOT = _REPO_ROOT / "data"
_CLI_SCRIPT = (
    _REPO_ROOT / "skills" / "financial-integrator" / "scripts" / "main.py"
)


def _has_real_data(ticker: str) -> bool:
    return (_DATA_ROOT / ticker / "parsed" / "financials.json").exists()


def _run_cli(ticker: str, fye_month: int, extra_args: list[str] | None = None):
    """CLI を実行し、出力 JSON を返す。"""
    output_path = _DATA_ROOT / ticker / "parsed" / "integrated_financials.json"
    cmd = [
        sys.executable,
        str(_CLI_SCRIPT),
        "--ticker", ticker,
        "--fye-month", str(fye_month),
        "--output", str(output_path),
    ]
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, (
        f"CLI failed (rc={result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert output_path.exists(), f"出力ファイルが生成されていません: {output_path}"
    return json.loads(output_path.read_text(encoding="utf-8"))


def _validate_structure(data: dict):
    """共通構造検証。"""
    for key in ("annual", "quarterly", "coverage_matrix", "integration_metadata"):
        assert key in data, f"キー '{key}' が出力 JSON に存在しません"


# ==================================================================
# 2780 (FYE=3月)
# ==================================================================

@pytest.mark.skipif(
    not _has_real_data("2780"),
    reason="実データ data/2780/parsed/financials.json が存在しません",
)
class TestCli2780:
    """銘柄 2780（FYE=3月）の実データ統合テスト。"""

    @pytest.fixture(autouse=True)
    def run_cli(self):
        self.data = _run_cli("2780", 3)

    def test_structure(self):
        _validate_structure(self.data)

    def test_annual_count(self):
        assert len(self.data["annual"]) == 7, (
            f"2780 annual 件数が不正: 期待=7, 実際={len(self.data['annual'])}"
        )

    def test_quarterly_count(self):
        assert len(self.data["quarterly"]) == 18, (
            f"2780 quarterly 件数が不正: 期待=18, 実際={len(self.data['quarterly'])}"
        )

    def test_annual_quarter_is_fy(self):
        for entry in self.data["annual"]:
            assert entry["quarter"] == "FY", (
                f"annual エントリの quarter が FY でない: {entry.get('period_end')}"
            )

    def test_quarterly_quarter_is_q1_q2_q3(self):
        valid_quarters = {"Q1", "Q2", "Q3"}
        for entry in self.data["quarterly"]:
            assert entry["quarter"] in valid_quarters, (
                f"quarterly エントリの quarter が不正: "
                f"{entry.get('quarter')} ({entry.get('period_end')})"
            )

    def test_annual_source_distribution(self):
        """annual エントリの source が期待通りであること（回帰検知）。"""
        sources = [e["source"] for e in self.data["annual"]]
        assert "edinet" in sources, "annual に edinet source が存在しない"
        assert "both" in sources, "annual に both source が存在しない"


# ==================================================================
# 7685 (FYE=12月)
# ==================================================================

@pytest.mark.skipif(
    not _has_real_data("7685"),
    reason="実データ data/7685/parsed/financials.json が存在しません",
)
class TestCli7685:
    """銘柄 7685（FYE=12月）の実データ統合テスト。"""

    @pytest.fixture(autouse=True)
    def run_cli(self):
        self.data = _run_cli("7685", 12)

    def test_structure(self):
        _validate_structure(self.data)

    def test_annual_count(self):
        assert len(self.data["annual"]) == 6, (
            f"7685 annual 件数が不正: 期待=6, 実際={len(self.data['annual'])}"
        )

    def test_quarterly_count(self):
        assert len(self.data["quarterly"]) == 19, (
            f"7685 quarterly 件数が不正: 期待=19, 実際={len(self.data['quarterly'])}"
        )

    def test_annual_quarter_is_fy(self):
        for entry in self.data["annual"]:
            assert entry["quarter"] == "FY", (
                f"annual エントリの quarter が FY でない: {entry.get('period_end')}"
            )

    def test_quarterly_quarter_is_q1_q2_q3(self):
        valid_quarters = {"Q1", "Q2", "Q3"}
        for entry in self.data["quarterly"]:
            assert entry["quarter"] in valid_quarters, (
                f"quarterly エントリの quarter が不正: "
                f"{entry.get('quarter')} ({entry.get('period_end')})"
            )

    def test_fiscal_year_fye12(self):
        """FYE=12月での fiscal_year 算出: annual は period_end 年 == fiscal_year。"""
        for entry in self.data["annual"]:
            pe_year = int(entry["period_end"].split("-")[0])
            assert entry["fiscal_year"] == pe_year, (
                f"FYE12 の fiscal_year が不正: "
                f"期待={pe_year}, 実際={entry['fiscal_year']}"
            )

    def test_annual_source_distribution(self):
        """annual エントリの source が期待通りであること（回帰検知）。"""
        sources = [e["source"] for e in self.data["annual"]]
        assert "edinet" in sources, "annual に edinet source が存在しない"
        assert "both" in sources, "annual に both source が存在しない"


# ==================================================================
# J-Quants 欠損シミュレーション
# ==================================================================

@pytest.mark.skipif(
    not _has_real_data("2780"),
    reason="実データ data/2780/parsed/financials.json が存在しません",
)
class TestCliJquantsMissing:
    """J-Quants ファイルが存在しない場合でも CLI が正常完了すること。"""

    def test_jquants_missing_completes(self, tmp_path):
        # financials.json のみ tmpdir にコピー
        src = _DATA_ROOT / "2780" / "parsed" / "financials.json"
        dst = tmp_path / "financials.json"
        shutil.copy2(src, dst)

        output_path = tmp_path / "integrated_financials.json"
        cmd = [
            sys.executable,
            str(_CLI_SCRIPT),
            "--ticker", "2780",
            "--fye-month", "3",
            "--parsed-dir", str(tmp_path),
            "--output", str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        assert result.returncode == 0, (
            f"J-Quants 欠損時に CLI が失敗:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert output_path.exists(), "出力 JSON が生成されていません"

        data = json.loads(output_path.read_text(encoding="utf-8"))
        _validate_structure(data)
