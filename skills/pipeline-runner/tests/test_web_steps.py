"""Tests for web_research / harmonize steps in the pipeline."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from pipeline import SKILL_REGISTRY, PipelineConfig, PipelineRunner

EXAMPLE_PIPELINE = (
    Path(__file__).resolve().parent.parent / "references" / "example_pipeline.yaml"
)


# ---------------------------------------------------------------------------
# SKILL_REGISTRY tests
# ---------------------------------------------------------------------------

class TestSkillRegistry:

    def test_web_researcher_in_registry(self) -> None:
        assert "web-researcher" in SKILL_REGISTRY

    def test_web_data_harmonizer_in_registry(self) -> None:
        assert "web-data-harmonizer" in SKILL_REGISTRY

    def test_web_researcher_command_template(self) -> None:
        cmd = SKILL_REGISTRY["web-researcher"]
        assert "web-researcher/scripts/main.py collect" in cmd
        assert "--ticker {ticker}" in cmd
        assert "--source all" in cmd

    def test_web_data_harmonizer_command_template(self) -> None:
        cmd = SKILL_REGISTRY["web-data-harmonizer"]
        assert "web-data-harmonizer/scripts/main.py harmonize" in cmd
        assert "--ticker {ticker}" in cmd
        assert "--source all" in cmd

    def test_all_example_pipeline_skills_in_registry(self) -> None:
        config = PipelineConfig.load(EXAMPLE_PIPELINE)
        for step in config.steps:
            assert step.skill in SKILL_REGISTRY, (
                f"Step '{step.id}' uses skill '{step.skill}' not in SKILL_REGISTRY"
            )


# ---------------------------------------------------------------------------
# DAG validation for web steps
# ---------------------------------------------------------------------------

class TestWebStepsDAG:

    def test_12_step_dag_is_valid(self) -> None:
        config = PipelineConfig.load(EXAMPLE_PIPELINE)
        errors = config.validate_dag()
        assert errors == [], f"DAG errors: {errors}"

    def test_12_steps_present(self) -> None:
        config = PipelineConfig.load(EXAMPLE_PIPELINE)
        assert len(config.steps) == 12

    def test_web_research_depends_on_resolve(self) -> None:
        config = PipelineConfig.load(EXAMPLE_PIPELINE)
        step_map = {s.id: s for s in config.steps}
        assert "web_research" in step_map
        assert step_map["web_research"].depends_on == ["resolve"]

    def test_harmonize_depends_on_web_research(self) -> None:
        config = PipelineConfig.load(EXAMPLE_PIPELINE)
        step_map = {s.id: s for s in config.steps}
        assert "harmonize" in step_map
        assert step_map["harmonize"].depends_on == ["web_research"]

    def test_integrate_depends_on_parse_and_harmonize(self) -> None:
        config = PipelineConfig.load(EXAMPLE_PIPELINE)
        step_map = {s.id: s for s in config.steps}
        assert "integrate" in step_map
        deps = set(step_map["integrate"].depends_on)
        assert deps == {"parse", "harmonize"}

    def test_three_parallel_branches_after_resolve(self) -> None:
        """collect_jquants, collect, web_research all depend only on resolve."""
        config = PipelineConfig.load(EXAMPLE_PIPELINE)
        step_map = {s.id: s for s in config.steps}
        for step_id in ["collect_jquants", "collect", "web_research"]:
            assert step_map[step_id].depends_on == ["resolve"]

    def test_execution_order_web_before_harmonize(self) -> None:
        config = PipelineConfig.load(EXAMPLE_PIPELINE)
        order = [s.id for s in config.execution_order()]
        assert order.index("web_research") < order.index("harmonize")

    def test_execution_order_harmonize_before_integrate(self) -> None:
        config = PipelineConfig.load(EXAMPLE_PIPELINE)
        order = [s.id for s in config.execution_order()]
        assert order.index("harmonize") < order.index("integrate")

    def test_integrate_command_has_harmonized_dir(self) -> None:
        config = PipelineConfig.load(EXAMPLE_PIPELINE)
        step_map = {s.id: s for s in config.steps}
        assert "--harmonized-dir" in step_map["integrate"].command

    def test_vars_validation_passes(self) -> None:
        config = PipelineConfig.load(EXAMPLE_PIPELINE)
        config.validate_vars({"ticker": "TEST"})


# ---------------------------------------------------------------------------
# Mock execution test
# ---------------------------------------------------------------------------

class TestWebStepsMockExecution:

    def test_12_step_mock_run_completes(self) -> None:
        config = PipelineConfig.load(EXAMPLE_PIPELINE)

        resolve_stdout = json.dumps({
            "fye_month": 3,
            "edinet_code": "E99999",
            "company_name": "テスト株式会社",
        })
        call_commands: list[str] = []

        def mock_run(cmd, **kwargs):
            call_commands.append(cmd)
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            result.stdout = resolve_stdout if len(call_commands) == 1 else "{}"
            return result

        with patch("pipeline.subprocess.run", side_effect=mock_run):
            runner = PipelineRunner()
            log = runner.run(config, {"ticker": "TEST"})

        assert log["status"] == "completed"
        assert len(log["steps"]) == 12

        web_cmds = [c for c in call_commands if "web-researcher" in c]
        assert len(web_cmds) == 1

        harmonize_cmds = [c for c in call_commands if "web-data-harmonizer" in c]
        assert len(harmonize_cmds) == 1

        integrate_cmds = [c for c in call_commands if "financial-integrator" in c]
        assert len(integrate_cmds) == 1
        assert "--harmonized-dir" in integrate_cmds[0]
