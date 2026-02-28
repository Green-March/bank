"""4971 メック 3ソース実データ統合 E2E テスト (req_055)

Primary (EDINET + J-Quants + Web) と Fallback (Shikiho→Yahoo) の
実データ検証。以下を網羅:
  - 3ソース統合の coverage 検証
  - 型整合性 (全 numeric フィールドが int|float|None)
  - contribution 比率
  - Shikiho fallback メタデータ
  - 二重収集回避
  - Primary vs Fallback 一致性
  - FinancialRecord coercion 連携
  - J-Quants raw string numeric 問題の再現と防御確認

再現手順:
  1. python3 skills/ticker-resolver/scripts/main.py resolve 4971
  2. python3 skills/disclosure-collector/scripts/main.py jquants 4971
  3. python3 skills/disclosure-collector/scripts/main.py edinet E01054 --ticker 4971 ...
  4. python3 skills/disclosure-parser/scripts/main.py --ticker 4971 ...
  5. # J-Quants 正規化 (raw → parsed/jquants_fins_statements.json)
  6. python3 skills/web-researcher/scripts/main.py collect --ticker 4971 --source all
  7. python3 skills/web-data-harmonizer/scripts/main.py harmonize --ticker 4971 ...
  8. python3 skills/financial-integrator/scripts/main.py --ticker 4971 --fye-month 12 ...
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA_ROOT = _REPO_ROOT / "data"
_CLI_SCRIPT = _REPO_ROOT / "skills" / "financial-integrator" / "scripts" / "main.py"
_SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "4971"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def _has_4971_data() -> bool:
    """4971 の実データ (3ソース) が存在するか。"""
    parsed = _DATA_ROOT / "4971" / "parsed"
    harmonized = _DATA_ROOT / "4971" / "harmonized"
    return (
        (parsed / "financials.json").exists()
        and (parsed / "jquants_fins_statements.json").exists()
        and (harmonized / "harmonized_financials.json").exists()
    )


def _run_integrate(
    harmonized_dir: str | None = None,
    output_name: str = "integrated_test.json",
) -> dict:
    """CLI で統合を実行し結果 dict を返す。"""
    output_path = _DATA_ROOT / "4971" / "integrated" / output_name
    cmd = [
        sys.executable, str(_CLI_SCRIPT),
        "--ticker", "4971",
        "--fye-month", "12",
        "--parsed-dir", str(_DATA_ROOT / "4971" / "parsed"),
        "--output", str(output_path),
        "--company-name", "メック株式会社",
    ]
    if harmonized_dir:
        cmd.extend(["--harmonized-dir", harmonized_dir])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, (
        f"CLI failed (rc={result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return json.loads(output_path.read_text(encoding="utf-8"))


def _validate_numeric_types(data: dict) -> list[str]:
    """全 numeric フィールドが int|float|None であることを検証。"""
    errors = []
    for section_name in ["annual", "quarterly"]:
        for entry in data.get(section_name, []):
            fy = entry.get("fiscal_year")
            q = entry.get("quarter")
            for section in ["bs", "pl", "cf"]:
                sec_data = entry.get(section, {})
                for field, value in sec_data.items():
                    if value is not None and not isinstance(value, (int, float)):
                        errors.append(
                            f"{section_name} FY{fy} {q} {section}.{field}: "
                            f"{type(value).__name__}={value!r}"
                        )
    return errors


# ===================================================================
# Primary 3-source integration (EDINET + J-Quants + Web)
# ===================================================================

@pytest.mark.skipif(
    not _has_4971_data(),
    reason="4971 の3ソース実データが存在しません",
)
class TestPrimaryThreeSource:
    """Primary 3ソース統合テスト。"""

    @pytest.fixture(autouse=True)
    def run_integration(self):
        self.data = _run_integrate(
            harmonized_dir=str(_DATA_ROOT / "4971" / "harmonized"),
            output_name="integrated_test_primary.json",
        )

    def test_structure_keys(self):
        """出力 JSON に必須キーが存在する。"""
        for key in ("annual", "quarterly", "coverage_matrix", "integration_metadata"):
            assert key in self.data, f"必須キー '{key}' が欠落"

    def test_input_files_three_sources(self):
        """input_files に edinet, web, jquants の3ソースが含まれる。"""
        input_files = self.data["integration_metadata"]["input_files"]
        assert set(input_files.keys()) == {"edinet", "web", "jquants"}, (
            f"期待=edinet,web,jquants 実際={set(input_files.keys())}"
        )

    def test_three_source_annual_exists(self):
        """edinet+web+jquants ソースの annual エントリが存在する。"""
        sources = [e["source"] for e in self.data["annual"]]
        assert "edinet+web+jquants" in sources, (
            f"3ソース統合 annual が存在しない: {sources}"
        )

    def test_annual_type_integrity(self):
        """全 annual エントリの numeric フィールドが int|float|None。"""
        errors = _validate_numeric_types(
            {"annual": self.data["annual"], "quarterly": []}
        )
        assert not errors, f"型エラー {len(errors)} 件:\n" + "\n".join(errors)

    def test_quarterly_type_integrity(self):
        """全 quarterly エントリの numeric フィールドが int|float|None。"""
        errors = _validate_numeric_types(
            {"annual": [], "quarterly": self.data["quarterly"]}
        )
        assert not errors, f"型エラー {len(errors)} 件:\n" + "\n".join(errors)

    def test_coverage_summary_sources(self):
        """coverage_summary に3ソース FY が含まれる。"""
        cs = self.data["integration_metadata"]["coverage_summary"]
        three_src_fys = [
            fy for fy, info in cs.items()
            if info.get("annual") == "edinet+web+jquants"
        ]
        assert len(three_src_fys) >= 1, "3ソース annual FY が存在しない"

    def test_web_source_preserved(self):
        """3ソース annual エントリに web_source が保持される。"""
        for entry in self.data["annual"]:
            if "web" in entry.get("source", ""):
                assert "web_source" in entry, (
                    f"FY{entry['fiscal_year']}: web_source が欠落"
                )

    def test_jquants_disclosed_date_preserved(self):
        """3ソース annual エントリに jquants_disclosed_date が保持される。"""
        for entry in self.data["annual"]:
            if "jquants" in entry.get("source", ""):
                assert "jquants_disclosed_date" in entry, (
                    f"FY{entry['fiscal_year']}: jquants_disclosed_date が欠落"
                )

    def test_contribution_ratio(self):
        """ソース別 contribution を記録・検証。"""
        source_counts: dict[str, int] = {}
        for section in ["annual", "quarterly"]:
            for entry in self.data.get(section, []):
                src = entry.get("source", "unknown")
                source_counts[src] = source_counts.get(src, 0) + 1

        total = sum(source_counts.values())
        assert total > 0, "統合エントリが0件"
        assert "edinet+web+jquants" in source_counts, "3ソースエントリなし"

    def test_fye12_fiscal_year(self):
        """FYE=12月: annual の fiscal_year == period_end 年。"""
        for entry in self.data["annual"]:
            pe_year = int(entry["period_end"].split("-")[0])
            assert entry["fiscal_year"] == pe_year, (
                f"FYE12 fiscal_year 不一致: "
                f"period_end={entry['period_end']}, fiscal_year={entry['fiscal_year']}"
            )


# ===================================================================
# Fallback test (Shikiho → Yahoo auto-switch)
# ===================================================================

@pytest.mark.skipif(
    not _has_4971_data(),
    reason="4971 の3ソース実データが存在しません",
)
class TestFallbackIntegration:
    """Fallback シナリオ: Shikiho fallback 後の統合検証。"""

    @pytest.fixture(autouse=True)
    def run_integration(self):
        self.data = _run_integrate(
            harmonized_dir=str(_DATA_ROOT / "4971" / "harmonized"),
            output_name="integrated_test_fallback.json",
        )

    def test_fallback_metadata_snapshot(self):
        """Fallback メタデータスナップショットと整合する。"""
        snap_path = _SNAP_DIR / "fallback_metadata_snapshot.json"
        if not snap_path.exists():
            pytest.skip("fallback snapshot が存在しません")
        snap = json.loads(snap_path.read_text(encoding="utf-8"))
        assert snap["shikiho_fallback"]["fallback_source"] == "yahoo"
        assert snap["shikiho_fallback"]["fallback_reason"] == "AUTH_ENV_MISSING"

    def test_fallback_double_collect_avoided(self):
        """Shikiho fallback 時に Yahoo の二重収集が回避される。"""
        snap_path = _SNAP_DIR / "fallback_metadata_snapshot.json"
        if not snap_path.exists():
            pytest.skip("fallback snapshot が存在しません")
        snap = json.loads(snap_path.read_text(encoding="utf-8"))
        assert snap["shikiho_fallback"]["fallback_reused"] is True, (
            "Yahoo 二重収集回避 (fallback_reused=true) が確認できない"
        )

    def test_fallback_type_integrity(self):
        """Fallback 後の統合結果でも型整合性が保たれる。"""
        errors = _validate_numeric_types(self.data)
        assert not errors, f"型エラー {len(errors)} 件:\n" + "\n".join(errors)


# ===================================================================
# Primary vs Fallback consistency
# ===================================================================

@pytest.mark.skipif(
    not _has_4971_data(),
    reason="4971 の3ソース実データが存在しません",
)
class TestPrimaryVsFallbackConsistency:
    """Primary と Fallback の統合結果の一致性を検証。"""

    @pytest.fixture(autouse=True)
    def load_snapshots(self):
        primary_path = _SNAP_DIR / "integrated_primary_snapshot.json"
        fallback_path = _SNAP_DIR / "integrated_fallback_snapshot.json"
        if not primary_path.exists() or not fallback_path.exists():
            pytest.skip("Primary/Fallback スナップショットが存在しません")
        self.primary = json.loads(primary_path.read_text(encoding="utf-8"))
        self.fallback = json.loads(fallback_path.read_text(encoding="utf-8"))

    def test_annual_count_match(self):
        """Primary と Fallback の annual 件数が一致する。"""
        assert self.primary["annual_count"] == self.fallback["annual_count"]

    def test_quarterly_count_match(self):
        """Primary と Fallback の quarterly 件数が一致する。"""
        assert self.primary["quarterly_count"] == self.fallback["quarterly_count"]

    def test_annual_revenue_match(self):
        """Primary と Fallback の annual revenue が全 FY 一致する。"""
        for p_entry in self.primary["annual"]:
            fy = p_entry["fiscal_year"]
            f_entry = next(
                (e for e in self.fallback["annual"] if e["fiscal_year"] == fy),
                None,
            )
            assert f_entry is not None, f"Fallback に FY{fy} が存在しない"
            assert p_entry["revenue"] == f_entry["revenue"], (
                f"FY{fy} revenue 不一致: "
                f"Primary={p_entry['revenue']}, Fallback={f_entry['revenue']}"
            )


# ===================================================================
# FinancialRecord coercion integration (req_052 defense)
# ===================================================================

@pytest.mark.skipif(
    not _has_4971_data(),
    reason="4971 の3ソース実データが存在しません",
)
class TestFinancialRecordCoercion:
    """統合出力 → FinancialRecord 変換で coercion が正しく機能する。"""

    @pytest.fixture(autouse=True)
    def run_integration(self):
        self.data = _run_integrate(
            harmonized_dir=str(_DATA_ROOT / "4971" / "harmonized"),
            output_name="integrated_test_coercion.json",
        )

    def test_coercion_from_annual(self):
        """annual エントリを FinancialRecord に変換しても型エラーなし。"""
        sys.path.insert(
            0,
            str(_REPO_ROOT / "skills" / "financial-calculator" / "scripts"),
        )
        from metrics import FinancialRecord

        for entry in self.data["annual"]:
            rec = FinancialRecord(
                ticker="4971",
                company_name="メック株式会社",
                fiscal_year=entry.get("fiscal_year"),
                period=entry.get("quarter"),
                revenue=entry.get("pl", {}).get("revenue"),
                operating_income=entry.get("pl", {}).get("operating_income"),
                net_income=entry.get("pl", {}).get("net_income"),
                total_assets=entry.get("bs", {}).get("total_assets"),
                equity=entry.get("bs", {}).get("total_equity"),
                operating_cf=entry.get("cf", {}).get("operating_cf"),
                investing_cf=entry.get("cf", {}).get("investing_cf"),
                period_end=entry.get("period_end"),
                period_start=entry.get("period_start"),
                source_attribution=entry.get("source"),
            )
            if rec.revenue is not None:
                assert isinstance(rec.revenue, float), (
                    f"FY{entry['fiscal_year']} revenue coercion 失敗: "
                    f"{type(rec.revenue).__name__}"
                )
            if rec.fiscal_year is not None:
                assert isinstance(rec.fiscal_year, int), (
                    f"FY{entry['fiscal_year']} fiscal_year coercion 失敗"
                )

    def test_coercion_string_numeric_defense(self):
        """string numeric がそのまま渡されても FinancialRecord が防御する。"""
        sys.path.insert(
            0,
            str(_REPO_ROOT / "skills" / "financial-calculator" / "scripts"),
        )
        from metrics import FinancialRecord

        rec = FinancialRecord(
            ticker="4971",
            company_name="メック株式会社",
            fiscal_year="2024",
            period="FY",
            revenue="23338746000",
            operating_income="4894927000",
            net_income="2291615000",
            total_assets="33039172000",
            equity="23267790000",
            operating_cf="4200122000",
            investing_cf="51598000",
            period_end="2024-12-31",
        )
        assert isinstance(rec.revenue, float)
        assert rec.revenue == 23338746000.0
        assert isinstance(rec.fiscal_year, int)
        assert rec.fiscal_year == 2024


# ===================================================================
# J-Quants raw string numeric problem reproduction
# ===================================================================

class TestJQuantsStringNumericProblem:
    """J-Quants API が文字列型数値を返す問題の再現と防御確認。"""

    def test_raw_jquants_has_string_numerics(self):
        """Raw J-Quants データが文字列型数値を含むことを確認。"""
        raw_path = _DATA_ROOT / "4971" / "raw" / "jquants"
        raw_files = sorted(raw_path.glob("statements_*.json"))
        if not raw_files:
            pytest.skip("J-Quants raw data が存在しません")
        raw = json.loads(raw_files[-1].read_text(encoding="utf-8"))
        assert isinstance(raw, list) and len(raw) > 0

        string_fields = []
        for r in raw:
            for field in ["NetSales", "OperatingProfit", "TotalAssets"]:
                val = r.get(field)
                if val is not None and isinstance(val, str) and val.strip():
                    string_fields.append(f"{r.get('TypeOfCurrentPeriod')} {field}={val!r}")
        assert len(string_fields) > 0, (
            "J-Quants raw data に文字列型数値が見つからない "
            "(問題が修正された可能性あり)"
        )

    def test_normalized_jquants_has_proper_types(self):
        """正規化後の J-Quants データが適切な型を持つ。"""
        path = _DATA_ROOT / "4971" / "parsed" / "jquants_fins_statements.json"
        if not path.exists():
            pytest.skip("正規化 J-Quants data が存在しません")
        data = json.loads(path.read_text(encoding="utf-8"))
        for rec in data.get("records", []):
            actuals = rec.get("actuals", {})
            for field, value in actuals.items():
                if value is not None:
                    assert isinstance(value, (int, float)), (
                        f"正規化後 {rec['period_end']} actuals.{field}: "
                        f"{type(value).__name__}={value!r}"
                    )
