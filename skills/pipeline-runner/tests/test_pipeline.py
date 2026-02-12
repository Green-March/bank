"""Tests for pipeline-runner skill."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# Add scripts dir to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from pipeline import (
    PipelineConfig,
    PipelineError,
    PipelineRunner,
    PipelineStep,
    StepLog,
    format_status,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_pipeline_yaml(path: Path, steps: list[dict], name: str = "test_pipe") -> Path:
    """Write a minimal pipeline YAML and return the path."""
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


def _simple_steps() -> list[dict]:
    return [
        {
            "id": "step1",
            "skill": "skill-a",
            "command": "echo hello",
            "output_dir": "out/step1",
        },
        {
            "id": "step2",
            "skill": "skill-b",
            "command": "echo world --input {prev_output}",
            "output_dir": "out/step2",
            "depends_on": ["step1"],
            "gates": None,
        },
    ]


# ---------------------------------------------------------------------------
# 1. test_pipeline_config_load
# ---------------------------------------------------------------------------

def test_pipeline_config_load(tmp_path: Path) -> None:
    """YAML reading and basic field mapping."""
    yaml_path = _write_pipeline_yaml(tmp_path, _simple_steps(), name="demo")
    config = PipelineConfig.load(yaml_path)

    assert config.name == "demo"
    assert len(config.steps) == 2
    assert config.steps[0].id == "step1"
    assert config.steps[1].depends_on == ["step1"]


# ---------------------------------------------------------------------------
# 2. test_dag_validation_valid
# ---------------------------------------------------------------------------

def test_dag_validation_valid(tmp_path: Path) -> None:
    """Valid DAG returns no errors."""
    yaml_path = _write_pipeline_yaml(tmp_path, _simple_steps())
    config = PipelineConfig.load(yaml_path)
    errors = config.validate_dag()
    assert errors == []


# ---------------------------------------------------------------------------
# 3. test_dag_validation_cycle
# ---------------------------------------------------------------------------

def test_dag_validation_cycle(tmp_path: Path) -> None:
    """Cycle in DAG is detected."""
    steps = [
        {"id": "a", "skill": "s", "command": "echo a", "output_dir": "o/a", "depends_on": ["b"]},
        {"id": "b", "skill": "s", "command": "echo b", "output_dir": "o/b", "depends_on": ["a"]},
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)
    errors = config.validate_dag()
    assert any("cycle" in e for e in errors)


# ---------------------------------------------------------------------------
# 4. test_execution_order
# ---------------------------------------------------------------------------

def test_execution_order(tmp_path: Path) -> None:
    """Topological sort respects dependencies."""
    steps = [
        {"id": "c", "skill": "s", "command": "echo c", "output_dir": "o/c", "depends_on": ["a", "b"]},
        {"id": "a", "skill": "s", "command": "echo a", "output_dir": "o/a"},
        {"id": "b", "skill": "s", "command": "echo b", "output_dir": "o/b", "depends_on": ["a"]},
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)
    order = config.execution_order()
    ids = [s.id for s in order]

    assert ids.index("a") < ids.index("b")
    assert ids.index("a") < ids.index("c")
    assert ids.index("b") < ids.index("c")


# ---------------------------------------------------------------------------
# 5. test_pipeline_step_execution
# ---------------------------------------------------------------------------

def test_pipeline_step_execution(tmp_path: Path) -> None:
    """Single step executes via mocked subprocess."""
    steps = [
        {"id": "only", "skill": "s", "command": "echo ok", "output_dir": str(tmp_path / "out")},
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "ok\n"
    mock_result.stderr = ""

    with patch("pipeline.subprocess.run", return_value=mock_result) as mock_run:
        runner = PipelineRunner()
        log = runner.run(config, {})

    assert log["status"] == "completed"
    assert len(log["steps"]) == 1
    assert log["steps"][0]["status"] == "completed"
    mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# 6. test_quality_gate_integration
# ---------------------------------------------------------------------------

def test_quality_gate_integration(tmp_path: Path) -> None:
    """Gate execution after step completion (mocked)."""
    gate_file = tmp_path / "gates.yaml"
    gate_file.write_text("gates: []")

    steps = [
        {
            "id": "gated",
            "skill": "s",
            "command": "echo gated",
            "output_dir": str(tmp_path / "out"),
            "gates": str(gate_file),
        },
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    step_result = MagicMock()
    step_result.returncode = 0
    step_result.stdout = ""
    step_result.stderr = ""

    gate_result_data = {"overall_pass": True, "gates_file": str(gate_file)}
    gate_json_path = tmp_path / "gated_gate_results.json"

    def mock_subprocess_run(cmd, **kwargs):
        # Write gate result file when gate command is invoked
        if "quality-gate" in cmd:
            gate_json_path.write_text(json.dumps(gate_result_data))
        return step_result

    with patch("pipeline.subprocess.run", side_effect=mock_subprocess_run):
        runner = PipelineRunner(working_dir=tmp_path)
        log = runner.run(config, {})

    assert log["status"] == "completed"
    assert log["steps"][0]["gate_result"] is not None
    assert log["steps"][0]["gate_result"]["overall_pass"] is True


# ---------------------------------------------------------------------------
# 7. test_pipeline_log_format
# ---------------------------------------------------------------------------

def test_pipeline_log_format(tmp_path: Path) -> None:
    """Execution log has correct JSON structure."""
    steps = [
        {"id": "s1", "skill": "sk", "command": "echo 1", "output_dir": "o/1"},
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_result.stderr = ""

    log_path = tmp_path / "log.json"

    with patch("pipeline.subprocess.run", return_value=mock_result):
        runner = PipelineRunner()
        log = runner.run(config, {"ticker": "1234"}, log_path=log_path)

    # Check in-memory log structure
    assert "pipeline_name" in log
    assert "started_at" in log
    assert "completed_at" in log
    assert "status" in log
    assert "vars" in log
    assert "steps" in log
    assert log["vars"] == {"ticker": "1234"}

    step = log["steps"][0]
    for key in ("id", "skill", "status", "started_at", "completed_at", "duration_sec", "gate_result", "error"):
        assert key in step

    # Check written log file
    assert log_path.exists()
    written = json.loads(log_path.read_text(encoding="utf-8"))
    assert written["pipeline_name"] == log["pipeline_name"]


# ---------------------------------------------------------------------------
# 8. test_error_handling
# ---------------------------------------------------------------------------

def test_error_handling(tmp_path: Path) -> None:
    """Failed command stops pipeline and records error."""
    steps = [
        {"id": "good", "skill": "s", "command": "echo ok", "output_dir": "o/g"},
        {"id": "bad", "skill": "s", "command": "false", "output_dir": "o/b", "depends_on": ["good"]},
        {"id": "skip", "skill": "s", "command": "echo skip", "output_dir": "o/s", "depends_on": ["bad"]},
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    call_count = 0

    def mock_run(cmd, **kwargs):
        nonlocal call_count
        call_count += 1
        result = MagicMock()
        if "false" in cmd:
            result.returncode = 1
            result.stderr = "command failed"
            result.stdout = ""
        else:
            result.returncode = 0
            result.stderr = ""
            result.stdout = "ok"
        return result

    with patch("pipeline.subprocess.run", side_effect=mock_run):
        runner = PipelineRunner()
        log = runner.run(config, {})

    assert log["status"] == "failed"
    # "skip" step should not have been executed
    assert len(log["steps"]) == 2
    assert log["steps"][0]["status"] == "completed"
    assert log["steps"][1]["status"] == "failed"
    assert log["steps"][1]["error"] is not None


# ---------------------------------------------------------------------------
# 9. test_variable_expansion
# ---------------------------------------------------------------------------

def test_variable_expansion(tmp_path: Path) -> None:
    """{ticker}, {edinet_code}, {prev_output} are expanded correctly."""
    steps = [
        {
            "id": "collect",
            "skill": "collector",
            "command": "fetch {edinet_code} --ticker {ticker}",
            "output_dir": "data/{ticker}/raw",
        },
        {
            "id": "parse",
            "skill": "parser",
            "command": "parse --input {prev_output} --ticker {ticker}",
            "output_dir": "data/{ticker}/parsed",
            "depends_on": ["collect"],
        },
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)
    config.resolve_vars({"ticker": "2780", "edinet_code": "E03416"})

    assert config.steps[0].command == "fetch E03416 --ticker 2780"
    assert config.steps[0].output_dir == "data/2780/raw"
    assert config.steps[1].command == "parse --input data/2780/raw --ticker 2780"
    assert config.steps[1].output_dir == "data/2780/parsed"


# ---------------------------------------------------------------------------
# 10. test_validate_subcommand
# ---------------------------------------------------------------------------

def test_validate_subcommand(tmp_path: Path) -> None:
    """validate subcommand exits 0 for valid pipeline, 1 for invalid."""
    # Valid pipeline
    (tmp_path / "valid").mkdir(parents=True, exist_ok=True)
    valid_path = _write_pipeline_yaml(tmp_path / "valid", _simple_steps())

    main_py = str(Path(__file__).resolve().parent.parent / "scripts" / "main.py")

    result = subprocess.run(
        [sys.executable, main_py, "validate", "--pipeline", str(valid_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "valid" in result.stdout.lower()

    # Invalid pipeline (cycle)
    cycle_steps = [
        {"id": "x", "skill": "s", "command": "echo x", "output_dir": "o/x", "depends_on": ["y"]},
        {"id": "y", "skill": "s", "command": "echo y", "output_dir": "o/y", "depends_on": ["x"]},
    ]
    (tmp_path / "invalid").mkdir(parents=True, exist_ok=True)
    invalid_path = _write_pipeline_yaml(tmp_path / "invalid", cycle_steps)

    result = subprocess.run(
        [sys.executable, main_py, "validate", "--pipeline", str(invalid_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
