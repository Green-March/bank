"""Tests for regression.py — regression testing script for BANK pipeline."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure scripts/ is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from regression import (
    json_diff,
    compute_exec_set,
    resolve_vars,
    find_log,
    backup_dirs,
    rollback,
    cleanup_backup,
    collect_json_files,
    run_ticker,
    generate_report,
    resolve_output_dirs,
    _extract_shares_outstanding,
)
from pipeline import PipelineConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_pipeline_yaml(tmp_path: Path) -> Path:
    """Create a simple 4-step pipeline for testing."""
    yaml_content = """\
pipeline:
  name: test_pipeline
  steps:
    - id: step_a
      skill: test
      command: "echo a > {ticker}/a.json && cat {ticker}/a.json"
      output_dir: "{ticker}/out_a"
    - id: step_b
      skill: test
      command: "echo b"
      output_dir: "{ticker}/out_b"
      depends_on: [step_a]
    - id: step_c
      skill: test
      command: "echo c"
      output_dir: "{ticker}/out_c"
      depends_on: [step_b]
    - id: step_d
      skill: test
      command: "echo d"
      output_dir: "{ticker}/out_d"
      depends_on: [step_b]
"""
    p = tmp_path / "pipeline.yaml"
    p.write_text(yaml_content)
    return p


@pytest.fixture
def config(simple_pipeline_yaml: Path) -> PipelineConfig:
    return PipelineConfig.load(str(simple_pipeline_yaml))


# ---------------------------------------------------------------------------
# 1. json_diff — changed / added / removed
# ---------------------------------------------------------------------------

class TestJsonDiff:
    def test_no_diff(self) -> None:
        assert json_diff({"a": 1, "b": 2}, {"a": 1, "b": 2}) == []

    def test_changed(self) -> None:
        diffs = json_diff({"a": 1}, {"a": 2})
        assert len(diffs) == 1
        assert diffs[0]["type"] == "changed"
        assert diffs[0]["path"] == "a"
        assert diffs[0]["old"] == 1
        assert diffs[0]["new"] == 2

    def test_added(self) -> None:
        diffs = json_diff({"a": 1}, {"a": 1, "b": 2})
        assert len(diffs) == 1
        assert diffs[0]["type"] == "added"
        assert diffs[0]["path"] == "b"
        assert diffs[0]["new"] == 2

    def test_removed(self) -> None:
        diffs = json_diff({"a": 1, "b": 2}, {"a": 1})
        assert len(diffs) == 1
        assert diffs[0]["type"] == "removed"
        assert diffs[0]["path"] == "b"
        assert diffs[0]["old"] == 2

    def test_nested(self) -> None:
        old = {"outer": {"inner": 1, "keep": "x"}}
        new = {"outer": {"inner": 2, "keep": "x"}}
        diffs = json_diff(old, new)
        assert len(diffs) == 1
        assert diffs[0]["path"] == "outer.inner"
        assert diffs[0]["old"] == 1
        assert diffs[0]["new"] == 2

    def test_list_changed(self) -> None:
        diffs = json_diff([1, 2, 3], [1, 9, 3])
        assert len(diffs) == 1
        assert diffs[0]["path"] == "[1]"

    def test_list_length_mismatch(self) -> None:
        diffs = json_diff([1, 2], [1, 2, 3])
        assert len(diffs) == 1
        assert diffs[0]["type"] == "added"
        assert diffs[0]["path"] == "[2]"

    def test_type_change(self) -> None:
        diffs = json_diff({"a": 1}, {"a": "one"})
        assert len(diffs) == 1
        assert diffs[0]["type"] == "changed"

    def test_null_to_value(self) -> None:
        """Key regression case: null -> non-null (e.g. relative valuation)."""
        diffs = json_diff(
            {"per": None, "pbr": None},
            {"per": 26.01, "pbr": 3.32},
        )
        assert len(diffs) == 2
        assert all(d["type"] == "changed" for d in diffs)
        # Keys are sorted alphabetically: pbr before per
        by_path = {d["path"]: d for d in diffs}
        assert by_path["per"]["old"] is None
        assert by_path["per"]["new"] == 26.01
        assert by_path["pbr"]["new"] == 3.32


# ---------------------------------------------------------------------------
# 2. compute_exec_set
# ---------------------------------------------------------------------------

class TestComputeExecSet:
    def test_from_leaf(self, config: PipelineConfig) -> None:
        """From a leaf step, only that step is in the exec set."""
        es = compute_exec_set(config, "step_d")
        assert es == {"step_d"}

    def test_from_middle(self, config: PipelineConfig) -> None:
        """From step_b, step_b + all downstream (step_c, step_d)."""
        es = compute_exec_set(config, "step_b")
        assert es == {"step_b", "step_c", "step_d"}

    def test_from_root(self, config: PipelineConfig) -> None:
        """From root step, everything is included."""
        es = compute_exec_set(config, "step_a")
        assert es == {"step_a", "step_b", "step_c", "step_d"}


# ---------------------------------------------------------------------------
# 3. Backup + rollback
# ---------------------------------------------------------------------------

class TestBackupRollback:
    def test_backup_creates_copy(self, tmp_path: Path) -> None:
        """Backup copies output_dir contents."""
        src_dir = tmp_path / "data" / "1234" / "valuation"
        src_dir.mkdir(parents=True)
        (src_dir / "dcf.json").write_text('{"value": 100}')
        (src_dir / "relative.json").write_text('{"per": null}')

        output_dirs = {"valuate": str(src_dir)}
        bmap = backup_dirs("1234", output_dirs, "20260302_120000")

        assert str(src_dir) in bmap
        dst = Path(bmap[str(src_dir)]["dst"])
        assert (dst / "dcf.json").exists()
        assert (dst / "relative.json").exists()

    def test_rollback_restores(self, tmp_path: Path) -> None:
        """Rollback restores original files after modification."""
        src_dir = tmp_path / "data" / "1234" / "valuation"
        src_dir.mkdir(parents=True)
        (src_dir / "dcf.json").write_text('{"value": 100}')

        output_dirs = {"valuate": str(src_dir)}
        bmap = backup_dirs("1234", output_dirs, "20260302_120000")

        # Modify original
        (src_dir / "dcf.json").write_text('{"value": 999}')
        (src_dir / "new_file.json").write_text('{"extra": true}')

        # Rollback
        rollback(bmap, "1234")

        restored = json.loads((src_dir / "dcf.json").read_text())
        assert restored["value"] == 100
        # New file should be gone after rollback (rmtree + copytree)
        assert not (src_dir / "new_file.json").exists()

    def test_cleanup_removes_backup(self, tmp_path: Path) -> None:
        """cleanup_backup removes the backup directory."""
        src_dir = tmp_path / "data" / "1234" / "valuation"
        src_dir.mkdir(parents=True)
        (src_dir / "dcf.json").write_text("{}")

        output_dirs = {"valuate": str(src_dir)}
        bmap = backup_dirs("1234", output_dirs, "20260302_120000")

        backup_root = Path(list(bmap.values())[0]["dst"]).parent
        assert backup_root.exists()

        cleanup_backup(bmap)
        assert not backup_root.exists()


# ---------------------------------------------------------------------------
# 4. Vars resolution — pipeline_log
# ---------------------------------------------------------------------------

class TestResolveVarsFromLog:
    def test_pipeline_log_with_runtime_vars(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Tier 1: pipeline_log.json with runtime_vars."""
        monkeypatch.chdir(tmp_path)
        log_dir = tmp_path / "data" / "9823"
        log_dir.mkdir(parents=True)
        log_file = log_dir / "pipeline_log.json"
        log_file.write_text(json.dumps({
            "runtime_vars": {
                "fye_month": "9",
                "edinet_code": "E03173",
                "company_name": "マミーマートHD",
                "shares_outstanding": "50000000",
            },
        }))

        found = find_log("9823")
        assert found is not None
        vars_dict, source = resolve_vars("9823", found)
        assert source == "pipeline_log"
        assert vars_dict["fye_month"] == "9"
        assert vars_dict["shares_outstanding"] == "50000000"


# ---------------------------------------------------------------------------
# 5. Vars resolution — resolve_result fallback
# ---------------------------------------------------------------------------

class TestResolveVarsFallback:
    def test_resolve_result_fallback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Tier 2: resolve_result.json (no pipeline_log runtime_vars)."""
        monkeypatch.chdir(tmp_path)
        resolved_dir = tmp_path / "data" / "4971" / "resolved"
        resolved_dir.mkdir(parents=True)
        (resolved_dir / "resolve_result.json").write_text(json.dumps({
            "edinet_code": "E01938",
            "company_name": "メック",
            "fye_month": 12,
        }))

        vars_dict, source = resolve_vars("4971", None)
        assert source == "resolve_result"
        assert vars_dict["edinet_code"] == "E01938"
        assert vars_dict["fye_month"] == "12"
        # shares_outstanding gets empty fallback
        assert vars_dict["shares_outstanding"] == ""

    def test_no_data_returns_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Tier 3: no data → skip."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "9999").mkdir(parents=True)
        vars_dict, source = resolve_vars("9999", None)
        assert vars_dict is None
        assert source is None

    def test_shares_outstanding_from_dcf(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Recover shares_outstanding from DCF output when log has no runtime_vars."""
        monkeypatch.chdir(tmp_path)
        ticker_dir = tmp_path / "data" / "9823"
        resolved_dir = ticker_dir / "resolved"
        resolved_dir.mkdir(parents=True)
        (resolved_dir / "resolve_result.json").write_text(json.dumps({
            "edinet_code": "E03173",
            "fye_month": 9,
        }))
        val_dir = ticker_dir / "valuation"
        val_dir.mkdir(parents=True)
        (val_dir / "dcf.json").write_text(json.dumps({
            "assumptions": {"shares_outstanding": 50013720.0},
        }))

        vars_dict, source = resolve_vars("9823", None)
        assert source == "resolve_result"
        assert vars_dict["shares_outstanding"] == "50013720"

    def test_log_without_runtime_vars_falls_back(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Log exists but has no runtime_vars → falls back to resolve_result."""
        monkeypatch.chdir(tmp_path)
        ticker_dir = tmp_path / "data" / "4971"
        log_dir = ticker_dir / "logs"
        log_dir.mkdir(parents=True)
        (log_dir / "pipeline_run.json").write_text(json.dumps({
            "vars": {"ticker": "4971"},
            "steps": [],
        }))
        resolved_dir = ticker_dir / "resolved"
        resolved_dir.mkdir(parents=True)
        (resolved_dir / "resolve_result.json").write_text(json.dumps({
            "edinet_code": "E01938",
            "fye_month": 12,
        }))

        log_path = find_log("4971")
        vars_dict, source = resolve_vars("4971", log_path)
        assert source == "resolve_result"
        assert vars_dict["edinet_code"] == "E01938"


# ---------------------------------------------------------------------------
# 6. Dry-run
# ---------------------------------------------------------------------------

class TestDryRun:
    @patch("regression.subprocess.run")
    def test_dry_run_does_not_call_subprocess(
        self, mock_run: MagicMock, tmp_path: Path,
        config: PipelineConfig, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--dry-run returns info without executing anything."""
        monkeypatch.chdir(tmp_path)

        # Create resolve_result for the ticker
        resolved_dir = tmp_path / "data" / "TEST" / "resolved"
        resolved_dir.mkdir(parents=True)
        (resolved_dir / "resolve_result.json").write_text(json.dumps({
            "edinet_code": "E00001",
            "fye_month": 3,
        }))

        exec_set = compute_exec_set(config, "step_b")
        output_dirs = resolve_output_dirs(config, "TEST", exec_set)

        result = run_ticker(
            "TEST", config, "step_b", str(tmp_path / "pipeline.yaml"),
            exec_set, output_dirs, dry_run=True,
        )

        assert result["status"] == "dry_run"
        assert "output_dirs" in result
        assert "vars" in result
        assert result["vars"]["ticker"] == "TEST"
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# 7. Report generation
# ---------------------------------------------------------------------------

class TestReportGeneration:
    def test_report_markdown(self, tmp_path: Path) -> None:
        """Report contains expected sections and data."""
        results = [
            {
                "ticker": "9823",
                "status": "completed",
                "vars_source": "pipeline_log",
                "diffs": {
                    "valuate_relative": {
                        "relative.json": [
                            {"path": "per", "type": "changed", "old": None, "new": 17.98},
                            {"path": "pbr", "type": "changed", "old": None, "new": 1.23},
                        ],
                    },
                },
                "errors": [],
            },
            {
                "ticker": "2780",
                "status": "skipped",
                "vars_source": None,
                "diffs": {},
                "errors": ["SKIPPED: insufficient data"],
            },
        ]

        report_path = str(tmp_path / "regression_report.md")
        report = generate_report(results, "calculate", report_path)

        assert "# Regression Report" in report
        assert "9823" in report
        assert "2780" in report
        assert "completed" in report
        assert "skipped" in report
        assert "relative.json" in report
        assert "17.98" in report
        assert "SKIPPED: insufficient data" in report
        assert Path(report_path).exists()

    def test_report_summary_table(self, tmp_path: Path) -> None:
        """Summary table shows correct changed file counts."""
        results = [
            {
                "ticker": "9716",
                "status": "completed",
                "vars_source": "pipeline_log",
                "diffs": {
                    "step_a": {"f1.json": [{"path": "x", "type": "changed"}]},
                    "step_b": {"f2.json": [{"path": "y", "type": "added"}]},
                },
                "errors": [],
            },
        ]
        report = generate_report(results, "calculate", str(tmp_path / "report.md"))
        # 2 changed files total
        assert "| 9716 |" in report


# ---------------------------------------------------------------------------
# 8. collect_json_files
# ---------------------------------------------------------------------------

class TestCollectJsonFiles:
    def test_collects_nested_json(self, tmp_path: Path) -> None:
        """Recursively finds JSON files."""
        (tmp_path / "sub").mkdir()
        (tmp_path / "a.json").write_text('{"k": 1}')
        (tmp_path / "sub" / "b.json").write_text('{"k": 2}')
        (tmp_path / "ignore.txt").write_text("not json")

        files = collect_json_files(str(tmp_path))
        assert "a.json" in files
        assert files["a.json"] == {"k": 1}
        assert "sub/b.json" in files
        assert "ignore.txt" not in files

    def test_nonexistent_dir_returns_empty(self) -> None:
        files = collect_json_files("/nonexistent/dir")
        assert files == {}


# ---------------------------------------------------------------------------
# 9. Full rerun mode (--full-rerun)
# ---------------------------------------------------------------------------

class TestFullRerun:
    """Tests for --full-rerun mode."""

    @patch("regression.subprocess.run")
    def test_full_rerun_skips_resolve_vars(
        self, mock_run: MagicMock, tmp_path: Path,
        config: PipelineConfig, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--full-rerun does not require resolve_result.json or pipeline_log."""
        monkeypatch.chdir(tmp_path)
        # No data at all for this ticker — normally would be skipped
        (tmp_path / "data" / "2780").mkdir(parents=True)

        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="ok")

        exec_set = compute_exec_set(config, "step_a")
        output_dirs = resolve_output_dirs(config, "2780", exec_set)

        result = run_ticker(
            "2780", config, "step_a", str(tmp_path / "pipeline.yaml"),
            exec_set, output_dirs, dry_run=False, full_rerun=True,
        )

        assert result["status"] == "completed"
        assert result["vars_source"] == "full_rerun"
        mock_run.assert_called_once()

    @patch("regression.subprocess.run")
    def test_full_rerun_no_from_step_in_cmd(
        self, mock_run: MagicMock, tmp_path: Path,
        config: PipelineConfig, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--full-rerun does not pass --from-step to pipeline CLI."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "7685").mkdir(parents=True)

        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="ok")

        exec_set = compute_exec_set(config, "step_a")
        output_dirs = resolve_output_dirs(config, "7685", exec_set)

        run_ticker(
            "7685", config, "step_a", str(tmp_path / "pipeline.yaml"),
            exec_set, output_dirs, dry_run=False, full_rerun=True,
        )

        cmd = mock_run.call_args[0][0]
        assert "--from-step" not in cmd

    @patch("regression.subprocess.run")
    def test_full_rerun_only_ticker_var(
        self, mock_run: MagicMock, tmp_path: Path,
        config: PipelineConfig, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--full-rerun passes only ticker= in --vars."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "9743").mkdir(parents=True)

        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="ok")

        exec_set = compute_exec_set(config, "step_a")
        output_dirs = resolve_output_dirs(config, "9743", exec_set)

        run_ticker(
            "9743", config, "step_a", str(tmp_path / "pipeline.yaml"),
            exec_set, output_dirs, dry_run=False, full_rerun=True,
        )

        cmd = mock_run.call_args[0][0]
        vars_idx = cmd.index("--vars")
        vars_val = cmd[vars_idx + 1]
        assert vars_val == "ticker=9743"

    def test_full_rerun_dry_run(
        self, tmp_path: Path,
        config: PipelineConfig, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--full-rerun + --dry-run returns dry_run status with full_rerun source."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "2780").mkdir(parents=True)

        exec_set = compute_exec_set(config, "step_a")
        output_dirs = resolve_output_dirs(config, "2780", exec_set)

        result = run_ticker(
            "2780", config, "step_a", str(tmp_path / "pipeline.yaml"),
            exec_set, output_dirs, dry_run=True, full_rerun=True,
        )

        assert result["status"] == "dry_run"
        assert result["vars_source"] == "full_rerun"
        assert result["vars"] == {"ticker": "2780"}

    @patch("regression.subprocess.run")
    def test_full_rerun_rollback_on_failure(
        self, mock_run: MagicMock, tmp_path: Path,
        config: PipelineConfig, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--full-rerun rolls back on pipeline failure."""
        monkeypatch.chdir(tmp_path)

        # Create output dir with existing data
        out_dir = tmp_path / "2780" / "out_a"
        out_dir.mkdir(parents=True)
        (out_dir / "data.json").write_text('{"original": true}')

        mock_run.return_value = MagicMock(returncode=1, stderr="error", stdout="")

        exec_set = compute_exec_set(config, "step_a")
        output_dirs = resolve_output_dirs(config, "2780", exec_set)

        result = run_ticker(
            "2780", config, "step_a", str(tmp_path / "pipeline.yaml"),
            exec_set, output_dirs, dry_run=False, full_rerun=True,
        )

        assert result["status"] == "rolled_back"
        assert any("exit code" in e for e in result["errors"])

    def test_normal_mode_still_skips_without_data(
        self, tmp_path: Path,
        config: PipelineConfig, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Normal mode (no --full-rerun) still skips tickers without data."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "2780").mkdir(parents=True)

        exec_set = compute_exec_set(config, "step_a")
        output_dirs = resolve_output_dirs(config, "2780", exec_set)

        result = run_ticker(
            "2780", config, "step_a", str(tmp_path / "pipeline.yaml"),
            exec_set, output_dirs, dry_run=False, full_rerun=False,
        )

        assert result["status"] == "skipped"
        assert "SKIPPED" in result["errors"][0]
