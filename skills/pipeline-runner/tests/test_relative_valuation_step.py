"""Tests for valuate_relative step and shares_outstanding pipeline integration.

Covers:
  a. 13-step DAG: valuate_relative present with correct dependencies
  b. valuate_relative in execution order (after calculate, before report)
  c. shares_outstanding propagation from collect_jquants to valuate command
  d. shares_outstanding empty string: valuate command omits --shares
  e. report depends_on includes valuate_relative
  f. valuate_relative gate YAML integration
  g. Full 13-step mock run with shares_outstanding + valuate_relative
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

from pipeline import PipelineConfig, PipelineRunner


EXAMPLE_PIPELINE = (
    Path(__file__).resolve().parent.parent / "references" / "example_pipeline.yaml"
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


# ---------------------------------------------------------------------------
# a. DAG structure: valuate_relative step
# ---------------------------------------------------------------------------

class TestValuateRelativeDAG:

    def test_valuate_relative_exists(self) -> None:
        config = PipelineConfig.load(EXAMPLE_PIPELINE)
        step_ids = {s.id for s in config.steps}
        assert "valuate_relative" in step_ids

    def test_valuate_relative_depends_on_calculate(self) -> None:
        config = PipelineConfig.load(EXAMPLE_PIPELINE)
        step_map = {s.id: s for s in config.steps}
        assert step_map["valuate_relative"].depends_on == ["calculate"]

    def test_valuate_relative_skill_is_valuation_calculator(self) -> None:
        config = PipelineConfig.load(EXAMPLE_PIPELINE)
        step_map = {s.id: s for s in config.steps}
        assert step_map["valuate_relative"].skill == "valuation-calculator"

    def test_valuate_relative_command_has_relative(self) -> None:
        config = PipelineConfig.load(EXAMPLE_PIPELINE)
        step_map = {s.id: s for s in config.steps}
        assert "relative" in step_map["valuate_relative"].command

    def test_report_depends_on_valuate_relative(self) -> None:
        config = PipelineConfig.load(EXAMPLE_PIPELINE)
        step_map = {s.id: s for s in config.steps}
        assert "valuate_relative" in step_map["report"].depends_on

    def test_dag_is_valid(self) -> None:
        config = PipelineConfig.load(EXAMPLE_PIPELINE)
        errors = config.validate_dag()
        assert errors == [], f"DAG errors: {errors}"


# ---------------------------------------------------------------------------
# b. Execution order
# ---------------------------------------------------------------------------

class TestValuateRelativeExecutionOrder:

    def test_valuate_relative_after_calculate(self) -> None:
        config = PipelineConfig.load(EXAMPLE_PIPELINE)
        order = [s.id for s in config.execution_order()]
        assert order.index("calculate") < order.index("valuate_relative")

    def test_valuate_relative_before_report(self) -> None:
        config = PipelineConfig.load(EXAMPLE_PIPELINE)
        order = [s.id for s in config.execution_order()]
        assert order.index("valuate_relative") < order.index("report")


# ---------------------------------------------------------------------------
# c. shares_outstanding propagation: non-empty value
# ---------------------------------------------------------------------------

class TestSharesOutstandingPropagation:

    def test_shares_in_valuate_command(self, tmp_path: Path) -> None:
        """When shares_outstanding is non-empty, valuate command includes --shares."""
        steps = [
            {
                "id": "collect_jquants",
                "skill": "disclosure-collector",
                "command": "echo jquants",
                "output_dir": "out/jq",
                "output_vars": {"shares_outstanding": "shares_outstanding"},
            },
            {
                "id": "valuate",
                "skill": "valuation-calculator",
                "command": 'python3 dcf $([ -n "{shares_outstanding}" ] && echo "--shares {shares_outstanding}")',
                "output_dir": "out/val",
                "depends_on": ["collect_jquants"],
            },
        ]
        yaml_path = _write_pipeline_yaml(tmp_path, steps)
        config = PipelineConfig.load(yaml_path)

        call_idx = 0
        executed_cmds: list[str] = []

        def mock_run(cmd, **kwargs):
            nonlocal call_idx
            executed_cmds.append(cmd)
            if call_idx == 0:
                call_idx += 1
                return _ok_result(json.dumps({"shares_outstanding": "18260731"}))
            call_idx += 1
            return _ok_result()

        with patch("pipeline.subprocess.run", side_effect=mock_run):
            runner = PipelineRunner()
            log = runner.run(config, {})

        assert log["status"] == "completed"
        valuate_cmd = executed_cmds[1]
        assert "--shares 18260731" in valuate_cmd

    def test_shares_empty_produces_false_conditional(self, tmp_path: Path) -> None:
        """When shares_outstanding is empty string, the shell conditional
        evaluates to false ([ -n "" ] is false), so --shares is not passed."""
        steps = [
            {
                "id": "collect_jquants",
                "skill": "disclosure-collector",
                "command": "echo jquants",
                "output_dir": "out/jq",
                "output_vars": {"shares_outstanding": "shares_outstanding"},
            },
            {
                "id": "valuate",
                "skill": "valuation-calculator",
                "command": 'python3 dcf $([ -n "{shares_outstanding}" ] && echo "--shares {shares_outstanding}")',
                "output_dir": "out/val",
                "depends_on": ["collect_jquants"],
            },
        ]
        yaml_path = _write_pipeline_yaml(tmp_path, steps)
        config = PipelineConfig.load(yaml_path)

        call_idx = 0
        executed_cmds: list[str] = []

        def mock_run(cmd, **kwargs):
            nonlocal call_idx
            executed_cmds.append(cmd)
            if call_idx == 0:
                call_idx += 1
                return _ok_result(json.dumps({"shares_outstanding": ""}))
            call_idx += 1
            return _ok_result()

        with patch("pipeline.subprocess.run", side_effect=mock_run):
            runner = PipelineRunner()
            log = runner.run(config, {})

        assert log["status"] == "completed"
        valuate_cmd = executed_cmds[1]
        # The shell conditional has empty test: [ -n "" ] → false → echo not executed
        assert '[ -n "" ]' in valuate_cmd
        # No actual shares value appears after --shares (only empty string in echo)
        assert '--shares 18260731' not in valuate_cmd


# ---------------------------------------------------------------------------
# d. collect_jquants output_vars in example pipeline
# ---------------------------------------------------------------------------

class TestCollectJquantsOutputVars:

    def test_collect_jquants_has_output_vars(self) -> None:
        config = PipelineConfig.load(EXAMPLE_PIPELINE)
        step_map = {s.id: s for s in config.steps}
        assert step_map["collect_jquants"].output_vars == {
            "shares_outstanding": "shares_outstanding"
        }

    def test_collect_jquants_command_has_extract_shares(self) -> None:
        config = PipelineConfig.load(EXAMPLE_PIPELINE)
        step_map = {s.id: s for s in config.steps}
        assert "--extract-shares" in step_map["collect_jquants"].command


# ---------------------------------------------------------------------------
# e. Gate YAML integration for valuate_relative
# ---------------------------------------------------------------------------

GATES_RELATIVE_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "quality-gate" / "references" / "gates_valuation_relative.yaml"
)


class TestGatesRelativeYAMLIntegration:

    @pytest.fixture(autouse=True)
    def _skip_if_missing(self):
        if not GATES_RELATIVE_PATH.exists():
            pytest.skip("gates_valuation_relative.yaml not found")

    def _load_gates(self) -> list[dict]:
        with GATES_RELATIVE_PATH.open("r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return config.get("gates", [])

    def test_valid_relative_passes_all_gates(self, tmp_path: Path) -> None:
        from validators import run_all_gates

        data = {
            "valuation_type": "relative",
            "per": 15.2,
            "pbr": 1.8,
            "ev_ebitda": 9.5,
        }
        (tmp_path / "relative.json").write_text(json.dumps(data))
        gates = self._load_gates()
        result = run_all_gates(gates, tmp_path)
        assert result.overall_pass is True

    def test_missing_relative_file_fails(self, tmp_path: Path) -> None:
        from validators import run_all_gates

        gates = self._load_gates()
        result = run_all_gates(gates, tmp_path)
        assert result.overall_pass is False

    def test_missing_valuation_type_fails(self, tmp_path: Path) -> None:
        from validators import run_all_gates

        data = {"per": 15.2, "pbr": 1.8}
        (tmp_path / "relative.json").write_text(json.dumps(data))
        gates = self._load_gates()
        result = run_all_gates(gates, tmp_path)
        assert result.overall_pass is False


# ---------------------------------------------------------------------------
# f. Full 13-step mock with valuate_relative + shares
# ---------------------------------------------------------------------------

class TestFull13StepWithRelative:

    def test_13_step_mock_with_shares_and_relative(self) -> None:
        config = PipelineConfig.load(EXAMPLE_PIPELINE)

        resolve_stdout = json.dumps({
            "fye_month": 3,
            "edinet_code": "E99999",
            "company_name": "テスト株式会社",
        })
        jquants_stdout = json.dumps({
            "saved_path": "/tmp/test/statements.json",
            "record_count": 8,
            "shares_outstanding": "18260731",
        })

        call_commands: list[str] = []

        def mock_run(cmd, **kwargs):
            call_commands.append(cmd)
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            if "ticker-resolver" in cmd:
                result.stdout = resolve_stdout
            elif "--extract-shares" in cmd:
                result.stdout = jquants_stdout
            else:
                result.stdout = "{}"
            return result

        with patch("pipeline.subprocess.run", side_effect=mock_run):
            runner = PipelineRunner()
            log = runner.run(config, {"ticker": "TEST"})

        assert log["status"] == "completed"
        assert len(log["steps"]) == 13

        # valuate_relative step exists and completed
        vr_steps = [s for s in log["steps"] if s["id"] == "valuate_relative"]
        assert len(vr_steps) == 1
        assert vr_steps[0]["status"] == "completed"

        # valuate command includes --shares
        valuate_cmds = [c for c in call_commands
                        if "valuation-calculator" in c and "dcf" in c]
        assert len(valuate_cmds) == 1
        assert "--shares 18260731" in valuate_cmds[0]

        # relative command exists
        relative_cmds = [c for c in call_commands
                         if "valuation-calculator" in c and "relative" in c]
        assert len(relative_cmds) == 1
        assert "--output data/TEST/valuation/relative.json" in relative_cmds[0]
