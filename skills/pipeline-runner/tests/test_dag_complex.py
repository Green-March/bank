"""Tests for complex DAG scenarios in pipeline-runner.

Covers:
  a. Diamond dependency (A→B, A→C, B→D, C→D)
  b. Intermediate step failure skips dependents
  c. Multiple undefined variables in validate_vars
  d. Gate failure stops pipeline
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

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
# a. Diamond dependency: A→B, A→C, B→D, C→D
# ---------------------------------------------------------------------------

def test_diamond_dependency_execution_order(tmp_path: Path) -> None:
    """Diamond DAG (A→B, A→C, B→D, C→D): topological order is correct."""
    steps = [
        {"id": "A", "skill": "s", "command": "echo A", "output_dir": "o/A"},
        {"id": "B", "skill": "s", "command": "echo B", "output_dir": "o/B", "depends_on": ["A"]},
        {"id": "C", "skill": "s", "command": "echo C", "output_dir": "o/C", "depends_on": ["A"]},
        {"id": "D", "skill": "s", "command": "echo D", "output_dir": "o/D", "depends_on": ["B", "C"]},
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    errors = config.validate_dag()
    assert errors == []

    order = config.execution_order()
    ids = [s.id for s in order]

    # A must come before B and C; B and C must come before D
    assert ids.index("A") < ids.index("B")
    assert ids.index("A") < ids.index("C")
    assert ids.index("B") < ids.index("D")
    assert ids.index("C") < ids.index("D")


def test_diamond_dependency_all_steps_run(tmp_path: Path) -> None:
    """Diamond DAG: all 4 steps execute successfully."""
    steps = [
        {"id": "A", "skill": "s", "command": "echo A", "output_dir": "o/A"},
        {"id": "B", "skill": "s", "command": "echo B", "output_dir": "o/B", "depends_on": ["A"]},
        {"id": "C", "skill": "s", "command": "echo C", "output_dir": "o/C", "depends_on": ["A"]},
        {"id": "D", "skill": "s", "command": "echo D", "output_dir": "o/D", "depends_on": ["B", "C"]},
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    executed: list[str] = []

    def mock_run(cmd, **kwargs):
        executed.append(cmd)
        return _ok_result()

    with patch("pipeline.subprocess.run", side_effect=mock_run):
        runner = PipelineRunner()
        log = runner.run(config, {})

    assert log["status"] == "completed"
    assert len(log["steps"]) == 4
    for step_log in log["steps"]:
        assert step_log["status"] == "completed"
    assert len(executed) == 4


# ---------------------------------------------------------------------------
# b. Intermediate step failure skips subsequent steps
# ---------------------------------------------------------------------------

def test_intermediate_failure_skips_dependents(tmp_path: Path) -> None:
    """When B fails, steps depending on B (D, E) are never executed.

    DAG: A→B, A→C (independent), B→D, B→E
    B fails → pipeline stops → C may or may not run (depends on topo order),
    but D and E are guaranteed not to run.
    """
    steps = [
        {"id": "A", "skill": "s", "command": "echo A", "output_dir": "o/A"},
        {"id": "B", "skill": "s", "command": "fail_cmd", "output_dir": "o/B", "depends_on": ["A"]},
        {"id": "C", "skill": "s", "command": "echo C", "output_dir": "o/C", "depends_on": ["A"]},
        {"id": "D", "skill": "s", "command": "echo D", "output_dir": "o/D", "depends_on": ["B"]},
        {"id": "E", "skill": "s", "command": "echo E", "output_dir": "o/E", "depends_on": ["B"]},
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    executed_cmds: list[str] = []

    def mock_run(cmd, **kwargs):
        executed_cmds.append(cmd)
        if "fail_cmd" in cmd:
            return _fail_result()
        return _ok_result()

    with patch("pipeline.subprocess.run", side_effect=mock_run):
        runner = PipelineRunner()
        log = runner.run(config, {})

    assert log["status"] == "failed"

    # D and E commands must never have been called
    assert not any("echo D" in c for c in executed_cmds), "D should not be executed after B fails"
    assert not any("echo E" in c for c in executed_cmds), "E should not be executed after B fails"

    # The failed step must be recorded
    failed_steps = [s for s in log["steps"] if s["status"] == "failed"]
    assert len(failed_steps) == 1
    assert failed_steps[0]["id"] == "B"


def test_failure_stops_pipeline_immediately(tmp_path: Path) -> None:
    """Pipeline stops at the first failed step; no subsequent steps execute."""
    steps = [
        {"id": "s1", "skill": "s", "command": "echo ok", "output_dir": "o/1"},
        {"id": "s2", "skill": "s", "command": "fail_here", "output_dir": "o/2", "depends_on": ["s1"]},
        {"id": "s3", "skill": "s", "command": "echo s3", "output_dir": "o/3", "depends_on": ["s2"]},
        {"id": "s4", "skill": "s", "command": "echo s4", "output_dir": "o/4", "depends_on": ["s3"]},
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    def mock_run(cmd, **kwargs):
        if "fail_here" in cmd:
            return _fail_result("step2 error")
        return _ok_result()

    with patch("pipeline.subprocess.run", side_effect=mock_run):
        runner = PipelineRunner()
        log = runner.run(config, {})

    assert log["status"] == "failed"
    # Only s1 (completed) and s2 (failed) should be in the log
    assert len(log["steps"]) == 2
    assert log["steps"][0]["status"] == "completed"
    assert log["steps"][1]["status"] == "failed"
    assert log["steps"][1]["error"] == "step2 error"


# ---------------------------------------------------------------------------
# c. Multiple undefined variables in validate_vars
# ---------------------------------------------------------------------------

def test_multiple_undefined_vars_raises_error(tmp_path: Path) -> None:
    """When 2+ variables are undefined, validate_vars raises PipelineError."""
    steps = [
        {
            "id": "s1",
            "skill": "s",
            "command": "fetch --code {edinet_code} --ticker {ticker} --month {fye_month}",
            "output_dir": "out/{ticker}",
        },
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    # No vars provided at all → multiple placeholders are undefined
    with pytest.raises(PipelineError, match="未定義です"):
        config.validate_vars({})


def test_single_undefined_var_with_others_defined(tmp_path: Path) -> None:
    """Even one undefined variable among defined ones triggers validation error."""
    steps = [
        {
            "id": "s1",
            "skill": "s",
            "command": "fetch --code {edinet_code} --ticker {ticker}",
            "output_dir": "out/{ticker}",
        },
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    # ticker is provided but edinet_code is not
    with pytest.raises(PipelineError, match="edinet_code"):
        config.validate_vars({"ticker": "7203"})


def test_output_vars_satisfy_later_step_placeholders(tmp_path: Path) -> None:
    """Variables produced by output_vars should satisfy later steps' placeholders."""
    steps = [
        {
            "id": "resolve",
            "skill": "s",
            "command": "echo resolve",
            "output_dir": "out/resolve",
            "output_vars": {"edinet_code": "edinet_code", "fye_month": "fye_month"},
        },
        {
            "id": "collect",
            "skill": "s",
            "command": "fetch --code {edinet_code} --month {fye_month}",
            "output_dir": "out/collect",
            "depends_on": ["resolve"],
        },
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    # Should NOT raise: edinet_code and fye_month come from resolve's output_vars
    config.validate_vars({})


# ---------------------------------------------------------------------------
# d. Gate failure stops pipeline
# ---------------------------------------------------------------------------

def test_gate_failure_stops_pipeline(tmp_path: Path) -> None:
    """When a quality gate fails, pipeline stops with status 'gate_failed'."""
    gate_file = tmp_path / "gates.yaml"
    gate_file.write_text("gates: []")

    steps = [
        {
            "id": "gated_step",
            "skill": "s",
            "command": "echo gated",
            "output_dir": str(tmp_path / "out"),
            "gates": str(gate_file),
        },
        {
            "id": "after_gate",
            "skill": "s",
            "command": "echo should_not_run",
            "output_dir": str(tmp_path / "out2"),
            "depends_on": ["gated_step"],
        },
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    gate_result_data = {"overall_pass": False, "gates_file": str(gate_file)}
    gate_json_path = tmp_path / "gated_step_gate_results.json"

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
        log = runner.run(config, {})

    assert log["status"] == "gate_failed"
    assert log["steps"][0]["gate_result"]["overall_pass"] is False
    # after_gate step should not have been executed
    assert not any("should_not_run" in c for c in executed_cmds)
    assert len(log["steps"]) == 1


def test_gate_failure_records_in_log(tmp_path: Path) -> None:
    """Gate failure is properly recorded in the step log and pipeline log."""
    gate_file = tmp_path / "gates.yaml"
    gate_file.write_text("gates: []")

    steps = [
        {
            "id": "checked",
            "skill": "s",
            "command": "echo checked",
            "output_dir": str(tmp_path / "out"),
            "gates": str(gate_file),
        },
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    gate_result_data = {"overall_pass": False, "gates_file": str(gate_file), "failed_gates": ["completeness"]}
    gate_json_path = tmp_path / "checked_gate_results.json"

    log_path = tmp_path / "pipeline_log.json"

    def mock_run(cmd, **kwargs):
        if "quality-gate" in cmd:
            gate_json_path.write_text(json.dumps(gate_result_data))
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        result.stdout = ""
        return result

    with patch("pipeline.subprocess.run", side_effect=mock_run):
        runner = PipelineRunner(working_dir=tmp_path)
        log = runner.run(config, {}, log_path=log_path)

    # Pipeline log
    assert log["status"] == "gate_failed"
    assert log["completed_at"] is not None

    # Step log
    step = log["steps"][0]
    assert step["status"] == "gate_failed"
    assert step["gate_result"]["overall_pass"] is False
    assert step["gate_result"]["failed_gates"] == ["completeness"]

    # Written log file
    assert log_path.exists()
    written = json.loads(log_path.read_text(encoding="utf-8"))
    assert written["status"] == "gate_failed"
