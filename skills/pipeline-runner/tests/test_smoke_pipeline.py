"""Smoke tests for example_pipeline.yaml with output_vars."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from pipeline import PipelineConfig, PipelineRunner


EXAMPLE_PIPELINE = Path(__file__).resolve().parent.parent / "references" / "example_pipeline.yaml"


# ---------------------------------------------------------------------------
# a. test_validate_example_pipeline
# ---------------------------------------------------------------------------

def test_validate_example_pipeline() -> None:
    """example_pipeline.yaml loads, DAG is valid, and --vars ticker=TEST
    resolves all placeholders (fye_month, edinet_code, company_name come
    from resolve step's output_vars)."""
    config = PipelineConfig.load(EXAMPLE_PIPELINE)

    errors = config.validate_dag()
    assert errors == [], f"DAG errors: {errors}"

    assert len(config.steps) == 7

    # validate_vars should pass with only ticker
    config.validate_vars({"ticker": "TEST"})


# ---------------------------------------------------------------------------
# b. test_mock_run_example_pipeline
# ---------------------------------------------------------------------------

def test_mock_run_example_pipeline() -> None:
    """Full 7-step mock run: resolve outputs JSON vars, subsequent steps
    receive expanded fye_month. No real API calls."""
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
        # First call is resolve step
        if len(call_commands) == 1:
            result.stdout = resolve_stdout
        else:
            result.stdout = "{}"
        return result

    with patch("pipeline.subprocess.run", side_effect=mock_run):
        runner = PipelineRunner()
        log = runner.run(config, {"ticker": "TEST"})

    # All 7 steps completed
    assert log["status"] == "completed"
    assert len(log["steps"]) == 7
    for step_log in log["steps"]:
        assert step_log["status"] == "completed"

    # Find integrate and inventory commands by content
    # (quality gate subprocess calls may shift indices)
    integrate_cmds = [c for c in call_commands if "financial-integrator" in c]
    assert len(integrate_cmds) == 1, f"Expected 1 integrate cmd, got {integrate_cmds}"
    assert "--fye-month 3" in integrate_cmds[0], (
        f"integrate command missing fye_month expansion: {integrate_cmds[0]}"
    )

    inventory_cmds = [c for c in call_commands if "inventory-builder" in c]
    assert len(inventory_cmds) == 1, f"Expected 1 inventory cmd, got {inventory_cmds}"
    assert "--fye-month 3" in inventory_cmds[0], (
        f"inventory command missing fye_month expansion: {inventory_cmds[0]}"
    )
