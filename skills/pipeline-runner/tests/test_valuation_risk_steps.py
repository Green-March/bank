"""Tests for valuation and risk analysis pipeline steps.

Covers:
  a. Diamond dependency: calculate → valuate + analyze_risk → report
  b. Execution order correctness for the diamond pattern
  c. Variable propagation ({ticker}, {prev_output})
  d. Failure in valuate skips report but analyze_risk may still run
  e. All steps complete successfully in the diamond DAG
  f. Integration: gates YAML loaded with mock data for pass/fail verification
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "quality-gate" / "scripts"))

from pipeline import (
    PipelineConfig,
    PipelineError,
    PipelineRunner,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_pipeline_yaml(path: Path, steps: list[dict], name: str = "test_pipe") -> Path:
    data = {
        "pipeline": {
            "name": name,
            "description": "test pipeline",
            "steps": steps,
        }
    }
    yaml_path = path / "pipeline.yaml"
    yaml_path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return yaml_path


def _ok_result(stdout: str = "") -> MagicMock:
    result = MagicMock()
    result.returncode = 0
    result.stderr = ""
    result.stdout = stdout
    return result


def _fail_result(stderr: str = "command failed") -> MagicMock:
    result = MagicMock()
    result.returncode = 1
    result.stderr = stderr
    result.stdout = ""
    return result


# ---------------------------------------------------------------------------
# Pipeline step definitions for valuation/risk diamond
# ---------------------------------------------------------------------------

def _valuation_risk_diamond_steps(ticker: str = "7203") -> list[dict]:
    """calculate → valuate + analyze_risk → report diamond."""
    return [
        {
            "id": "calculate",
            "skill": "financial-calculator",
            "command": "python3 skills/financial-calculator/scripts/main.py --ticker {ticker}",
            "output_dir": "data/{ticker}/metrics",
        },
        {
            "id": "valuate",
            "skill": "valuation-calculator",
            "command": "python3 skills/valuation-calculator/scripts/main.py --ticker {ticker} --input {prev_output}",
            "output_dir": "data/{ticker}/valuation",
            "depends_on": ["calculate"],
        },
        {
            "id": "analyze_risk",
            "skill": "risk-analyzer",
            "command": "python3 skills/risk-analyzer/scripts/main.py --ticker {ticker} --input {prev_output}",
            "output_dir": "data/{ticker}/risk",
            "depends_on": ["calculate"],
        },
        {
            "id": "report",
            "skill": "financial-reporter",
            "command": "python3 skills/financial-reporter/scripts/main.py --ticker {ticker}",
            "output_dir": "data/{ticker}/report",
            "depends_on": ["valuate", "analyze_risk"],
        },
    ]


# ---------------------------------------------------------------------------
# a. Diamond DAG validation
# ---------------------------------------------------------------------------

class TestValuationRiskDiamondDAG:
    """DAG structure tests for calculate → valuate/analyze_risk → report."""

    def test_dag_is_valid(self, tmp_path: Path) -> None:
        """Diamond DAG has no validation errors."""
        yaml_path = _write_pipeline_yaml(tmp_path, _valuation_risk_diamond_steps())
        config = PipelineConfig.load(yaml_path)

        errors = config.validate_dag()
        assert errors == []

    def test_execution_order_respects_dependencies(self, tmp_path: Path) -> None:
        """Topological order: calculate before valuate/analyze_risk, both before report."""
        yaml_path = _write_pipeline_yaml(tmp_path, _valuation_risk_diamond_steps())
        config = PipelineConfig.load(yaml_path)

        order = config.execution_order()
        ids = [s.id for s in order]

        # calculate must precede valuate and analyze_risk
        assert ids.index("calculate") < ids.index("valuate")
        assert ids.index("calculate") < ids.index("analyze_risk")
        # valuate and analyze_risk must precede report
        assert ids.index("valuate") < ids.index("report")
        assert ids.index("analyze_risk") < ids.index("report")

    def test_all_four_steps_present(self, tmp_path: Path) -> None:
        """Execution order includes all 4 steps."""
        yaml_path = _write_pipeline_yaml(tmp_path, _valuation_risk_diamond_steps())
        config = PipelineConfig.load(yaml_path)

        order = config.execution_order()
        assert len(order) == 4
        assert {s.id for s in order} == {"calculate", "valuate", "analyze_risk", "report"}


# ---------------------------------------------------------------------------
# b. Variable propagation
# ---------------------------------------------------------------------------

class TestVariablePropagation:
    """{ticker} and {prev_output} variable resolution tests."""

    def test_ticker_variable_resolves(self, tmp_path: Path) -> None:
        """All {ticker} placeholders resolve to the provided value."""
        yaml_path = _write_pipeline_yaml(tmp_path, _valuation_risk_diamond_steps())
        config = PipelineConfig.load(yaml_path)

        config.resolve_vars({"ticker": "7203"})

        for step in config.steps:
            assert "{ticker}" not in step.command, f"{step.id}: unresolved {{ticker}} in command"
            assert "{ticker}" not in step.output_dir, f"{step.id}: unresolved {{ticker}} in output_dir"
            assert "7203" in step.command or "7203" in step.output_dir

    def test_prev_output_resolves_for_valuate(self, tmp_path: Path) -> None:
        """{prev_output} in valuate resolves to calculate's output_dir."""
        yaml_path = _write_pipeline_yaml(tmp_path, _valuation_risk_diamond_steps())
        config = PipelineConfig.load(yaml_path)

        config.resolve_vars({"ticker": "7203"})

        valuate = next(s for s in config.steps if s.id == "valuate")
        assert "data/7203/metrics" in valuate.command

    def test_prev_output_resolves_for_analyze_risk(self, tmp_path: Path) -> None:
        """{prev_output} in analyze_risk resolves to calculate's output_dir."""
        yaml_path = _write_pipeline_yaml(tmp_path, _valuation_risk_diamond_steps())
        config = PipelineConfig.load(yaml_path)

        config.resolve_vars({"ticker": "7203"})

        analyze_risk = next(s for s in config.steps if s.id == "analyze_risk")
        assert "data/7203/metrics" in analyze_risk.command

    def test_validate_vars_with_ticker(self, tmp_path: Path) -> None:
        """validate_vars passes when ticker is provided."""
        yaml_path = _write_pipeline_yaml(tmp_path, _valuation_risk_diamond_steps())
        config = PipelineConfig.load(yaml_path)

        # Should not raise
        config.validate_vars({"ticker": "7203"})

    def test_validate_vars_missing_ticker_raises(self, tmp_path: Path) -> None:
        """validate_vars raises PipelineError when ticker is not provided."""
        yaml_path = _write_pipeline_yaml(tmp_path, _valuation_risk_diamond_steps())
        config = PipelineConfig.load(yaml_path)

        with pytest.raises(PipelineError, match="ticker"):
            config.validate_vars({})


# ---------------------------------------------------------------------------
# c. Full diamond execution
# ---------------------------------------------------------------------------

class TestDiamondExecution:
    """End-to-end execution tests for the diamond DAG."""

    def test_all_steps_complete_successfully(self, tmp_path: Path) -> None:
        """All 4 steps execute and pipeline completes."""
        yaml_path = _write_pipeline_yaml(tmp_path, _valuation_risk_diamond_steps())
        config = PipelineConfig.load(yaml_path)

        executed: list[str] = []

        def mock_run(cmd, **kwargs):
            executed.append(cmd)
            return _ok_result()

        with patch("pipeline.subprocess.run", side_effect=mock_run):
            runner = PipelineRunner()
            log = runner.run(config, {"ticker": "7203"})

        assert log["status"] == "completed"
        assert len(log["steps"]) == 4
        for step_log in log["steps"]:
            assert step_log["status"] == "completed"
        assert len(executed) == 4

    def test_valuate_failure_stops_pipeline(self, tmp_path: Path) -> None:
        """When valuate fails, report is never executed."""
        yaml_path = _write_pipeline_yaml(tmp_path, _valuation_risk_diamond_steps())
        config = PipelineConfig.load(yaml_path)

        executed_cmds: list[str] = []

        def mock_run(cmd, **kwargs):
            executed_cmds.append(cmd)
            if "valuation-calculator" in cmd:
                return _fail_result("valuation failed")
            return _ok_result()

        with patch("pipeline.subprocess.run", side_effect=mock_run):
            runner = PipelineRunner()
            log = runner.run(config, {"ticker": "7203"})

        assert log["status"] == "failed"
        # report step must not have been executed
        assert not any("financial-reporter" in c for c in executed_cmds)

    def test_analyze_risk_failure_stops_pipeline(self, tmp_path: Path) -> None:
        """When analyze_risk fails, report is never executed."""
        yaml_path = _write_pipeline_yaml(tmp_path, _valuation_risk_diamond_steps())
        config = PipelineConfig.load(yaml_path)

        executed_cmds: list[str] = []

        def mock_run(cmd, **kwargs):
            executed_cmds.append(cmd)
            if "risk-analyzer" in cmd:
                return _fail_result("risk analysis failed")
            return _ok_result()

        with patch("pipeline.subprocess.run", side_effect=mock_run):
            runner = PipelineRunner()
            log = runner.run(config, {"ticker": "7203"})

        assert log["status"] == "failed"
        assert not any("financial-reporter" in c for c in executed_cmds)


# ---------------------------------------------------------------------------
# d. Gate integration with valuation/risk steps
# ---------------------------------------------------------------------------

class TestGateIntegration:
    """Quality gate behavior within the diamond DAG."""

    def test_valuation_gate_failure_stops_pipeline(self, tmp_path: Path) -> None:
        """Valuation gate failure prevents report from running."""
        gate_file = tmp_path / "gates_valuation.yaml"
        gate_file.write_text("gates: []")

        steps = _valuation_risk_diamond_steps()
        # Add gates to valuate step
        steps[1]["gates"] = str(gate_file)

        yaml_path = _write_pipeline_yaml(tmp_path, steps)
        config = PipelineConfig.load(yaml_path)

        gate_result_data = {"overall_pass": False, "gates_file": str(gate_file)}
        gate_json_path = tmp_path / "valuate_gate_results.json"

        executed_cmds: list[str] = []

        def mock_run(cmd, **kwargs):
            executed_cmds.append(cmd)
            if "quality-gate" in cmd:
                gate_json_path.write_text(json.dumps(gate_result_data))
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            result.stdout = ""
            return result

        with patch("pipeline.subprocess.run", side_effect=mock_run):
            runner = PipelineRunner(working_dir=tmp_path)
            log = runner.run(config, {"ticker": "7203"})

        assert log["status"] == "gate_failed"
        assert not any("financial-reporter" in c for c in executed_cmds)

    def test_risk_gate_failure_stops_pipeline(self, tmp_path: Path) -> None:
        """Risk gate failure prevents report from running."""
        gate_file = tmp_path / "gates_risk.yaml"
        gate_file.write_text("gates: []")

        steps = _valuation_risk_diamond_steps()
        # Add gates to analyze_risk step
        steps[2]["gates"] = str(gate_file)

        yaml_path = _write_pipeline_yaml(tmp_path, steps)
        config = PipelineConfig.load(yaml_path)

        gate_result_data = {"overall_pass": False, "gates_file": str(gate_file)}
        gate_json_path = tmp_path / "analyze_risk_gate_results.json"

        executed_cmds: list[str] = []

        def mock_run(cmd, **kwargs):
            executed_cmds.append(cmd)
            if "quality-gate" in cmd:
                gate_json_path.write_text(json.dumps(gate_result_data))
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            result.stdout = ""
            return result

        with patch("pipeline.subprocess.run", side_effect=mock_run):
            runner = PipelineRunner(working_dir=tmp_path)
            log = runner.run(config, {"ticker": "7203"})

        assert log["status"] == "gate_failed"
        assert not any("financial-reporter" in c for c in executed_cmds)


# ---------------------------------------------------------------------------
# e. Gates YAML integration: load real YAML, run against mock data
# ---------------------------------------------------------------------------

GATES_VALUATION_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "quality-gate" / "references" / "gates_valuation.yaml"
)
GATES_RISK_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "quality-gate" / "references" / "gates_risk.yaml"
)


def _load_gates_config(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config.get("gates", [])


def _make_valid_dcf_data() -> dict:
    """Valid DCFResult-compatible data."""
    return {
        "enterprise_value": 50_000_000_000.0,
        "equity_value": 45_000_000_000.0,
        "per_share_value": 3500.0,
        "assumptions": {
            "wacc": 0.08,
            "terminal_growth_rate": 0.02,
            "projection_years": 5,
            "base_fcf": 5_000_000_000.0,
            "estimated_growth_rate": 0.05,
            "net_debt": 5_000_000_000.0,
            "shares_outstanding": 12_857_142.86,
        },
    }


def _make_valid_risk_data() -> dict:
    """Valid RiskAnalysisResult.to_dict()-compatible data."""
    return {
        "ticker": "7203",
        "analyzed_at": "2026-02-26T09:00:00+00:00",
        "source_documents": ["E00001", "E00002"],
        "risk_categories": {
            "market_risk": [{"text": "為替リスク", "source": "E00001", "severity": "high"}],
            "credit_risk": [],
            "operational_risk": [],
            "regulatory_risk": [],
            "other_risk": [],
        },
        "summary": {
            "total_risks": 1,
            "by_category": {
                "market_risk": 1,
                "credit_risk": 0,
                "operational_risk": 0,
                "regulatory_risk": 0,
                "other_risk": 0,
            },
            "by_severity": {"high": 1, "medium": 0, "low": 0},
        },
    }


class TestGatesValuationYAMLIntegration:
    """Load gates_valuation.yaml and run against mock DCF data."""

    @pytest.fixture(autouse=True)
    def _skip_if_missing(self):
        if not GATES_VALUATION_PATH.exists():
            pytest.skip("gates_valuation.yaml not found")

    def test_valid_dcf_passes_all_gates(self, tmp_path: Path) -> None:
        """Valid DCF output passes all valuation gates. Expected: PASS."""
        from validators import run_all_gates

        (tmp_path / "dcf.json").write_text(
            json.dumps(_make_valid_dcf_data(), ensure_ascii=False)
        )
        gates = _load_gates_config(GATES_VALUATION_PATH)
        result = run_all_gates(gates, tmp_path)

        assert result.overall_pass is True, (
            f"Expected all gates to pass but got: "
            f"{[(g['id'], g['pass'], g.get('detail')) for g in result.gates]}"
        )

    def test_missing_dcf_file_fails(self, tmp_path: Path) -> None:
        """Missing dcf.json fails file_exists and schema gates. Expected: FAIL."""
        from validators import run_all_gates

        gates = _load_gates_config(GATES_VALUATION_PATH)
        result = run_all_gates(gates, tmp_path)

        assert result.overall_pass is False
        file_gate = next(g for g in result.gates if g["id"] == "valuation_file_check")
        assert file_gate["pass"] is False

    def test_missing_assumptions_key_fails_schema(self, tmp_path: Path) -> None:
        """DCF data without 'assumptions' key fails schema gate. Expected: FAIL."""
        from validators import run_all_gates

        data = _make_valid_dcf_data()
        del data["assumptions"]
        (tmp_path / "dcf.json").write_text(json.dumps(data))

        gates = _load_gates_config(GATES_VALUATION_PATH)
        result = run_all_gates(gates, tmp_path)

        assert result.overall_pass is False
        schema_gate = next(g for g in result.gates if g["id"] == "valuation_schema")
        assert schema_gate["pass"] is False
        assert "assumptions" in schema_gate["detail"]["missing_keys"]

    def test_negative_enterprise_value_fails_range(self, tmp_path: Path) -> None:
        """Negative enterprise_value fails value range gate. Expected: FAIL."""
        from validators import run_all_gates

        data = _make_valid_dcf_data()
        data["enterprise_value"] = -100_000.0
        (tmp_path / "dcf.json").write_text(json.dumps(data))

        gates = _load_gates_config(GATES_VALUATION_PATH)
        result = run_all_gates(gates, tmp_path)

        assert result.overall_pass is False
        range_gate = next(g for g in result.gates if g["id"] == "valuation_range")
        assert range_gate["pass"] is False
        assert any(v["key"] == "enterprise_value" for v in range_gate["detail"]["violations"])


class TestGatesRiskYAMLIntegration:
    """Load gates_risk.yaml and run against mock risk analysis data."""

    @pytest.fixture(autouse=True)
    def _skip_if_missing(self):
        if not GATES_RISK_PATH.exists():
            pytest.skip("gates_risk.yaml not found")

    def test_valid_risk_passes_all_gates(self, tmp_path: Path) -> None:
        """Valid risk analysis output passes all risk gates. Expected: PASS."""
        from validators import run_all_gates

        (tmp_path / "risk_analysis.json").write_text(
            json.dumps(_make_valid_risk_data(), ensure_ascii=False)
        )
        gates = _load_gates_config(GATES_RISK_PATH)
        result = run_all_gates(gates, tmp_path)

        assert result.overall_pass is True, (
            f"Expected all gates to pass but got: "
            f"{[(g['id'], g['pass'], g.get('detail')) for g in result.gates]}"
        )

    def test_missing_risk_file_fails(self, tmp_path: Path) -> None:
        """Missing risk_analysis.json fails file_exists and schema gates. Expected: FAIL."""
        from validators import run_all_gates

        gates = _load_gates_config(GATES_RISK_PATH)
        result = run_all_gates(gates, tmp_path)

        assert result.overall_pass is False
        file_gate = next(g for g in result.gates if g["id"] == "risk_file_check")
        assert file_gate["pass"] is False

    def test_missing_summary_key_fails_schema(self, tmp_path: Path) -> None:
        """Risk data without 'summary' key fails schema gate. Expected: FAIL."""
        from validators import run_all_gates

        data = _make_valid_risk_data()
        del data["summary"]
        (tmp_path / "risk_analysis.json").write_text(json.dumps(data))

        gates = _load_gates_config(GATES_RISK_PATH)
        result = run_all_gates(gates, tmp_path)

        assert result.overall_pass is False
        schema_gate = next(g for g in result.gates if g["id"] == "risk_schema")
        assert schema_gate["pass"] is False
        assert "summary" in schema_gate["detail"]["missing_keys"]

    def test_missing_by_severity_fails_schema(self, tmp_path: Path) -> None:
        """Risk data without 'summary.by_severity' fails schema gate. Expected: FAIL."""
        from validators import run_all_gates

        data = _make_valid_risk_data()
        del data["summary"]["by_severity"]
        (tmp_path / "risk_analysis.json").write_text(json.dumps(data))

        gates = _load_gates_config(GATES_RISK_PATH)
        result = run_all_gates(gates, tmp_path)

        assert result.overall_pass is False
        schema_gate = next(g for g in result.gates if g["id"] == "risk_schema")
        assert schema_gate["pass"] is False
        assert "summary.by_severity" in schema_gate["detail"]["missing_keys"]

    def test_zero_risks_passes(self, tmp_path: Path) -> None:
        """Zero total_risks is valid (min=0). Expected: PASS."""
        from validators import run_all_gates

        data = _make_valid_risk_data()
        data["risk_categories"] = {c: [] for c in data["risk_categories"]}
        data["summary"]["total_risks"] = 0
        data["summary"]["by_category"] = {c: 0 for c in data["summary"]["by_category"]}
        data["summary"]["by_severity"] = {"high": 0, "medium": 0, "low": 0}
        (tmp_path / "risk_analysis.json").write_text(json.dumps(data))

        gates = _load_gates_config(GATES_RISK_PATH)
        result = run_all_gates(gates, tmp_path)

        assert result.overall_pass is True
