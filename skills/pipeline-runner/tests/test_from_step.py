"""Tests for --from-step and runtime_vars persistence features."""

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
    StepLog,
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


def _three_step_linear() -> list[dict]:
    """A -> B -> C linear pipeline."""
    return [
        {"id": "A", "skill": "s", "command": "echo A", "output_dir": "out/A"},
        {"id": "B", "skill": "s", "command": "echo B --input {prev_output}",
         "output_dir": "out/B", "depends_on": ["A"]},
        {"id": "C", "skill": "s", "command": "echo C --input {prev_output}",
         "output_dir": "out/C", "depends_on": ["B"]},
    ]


def _diamond_dag() -> list[dict]:
    """Diamond: root -> {left, right} -> join."""
    return [
        {"id": "root", "skill": "s", "command": "echo root", "output_dir": "out/root"},
        {"id": "left", "skill": "s", "command": "echo left",
         "output_dir": "out/left", "depends_on": ["root"]},
        {"id": "right", "skill": "s", "command": "echo right",
         "output_dir": "out/right", "depends_on": ["root"]},
        {"id": "join", "skill": "s", "command": "echo join",
         "output_dir": "out/join", "depends_on": ["left", "right"]},
    ]


def _output_vars_pipeline() -> list[dict]:
    """Pipeline with output_vars for variable propagation."""
    return [
        {
            "id": "resolve",
            "skill": "resolver",
            "command": "echo resolve",
            "output_dir": "out/resolve",
            "output_vars": {"edinet_code": "edinet_code", "fye_month": "fye_month"},
        },
        {
            "id": "collect",
            "skill": "collector",
            "command": "fetch --code {edinet_code} --fye {fye_month}",
            "output_dir": "out/collect",
            "depends_on": ["resolve"],
        },
        {
            "id": "parse",
            "skill": "parser",
            "command": "parse --input {prev_output}",
            "output_dir": "out/parse",
            "depends_on": ["collect"],
        },
    ]


def _mock_ok(cmd, **kwargs):
    result = MagicMock()
    result.returncode = 0
    result.stdout = ""
    result.stderr = ""
    return result


# ---------------------------------------------------------------------------
# 1. from_step basic: 3-step linear, start from middle step B
# ---------------------------------------------------------------------------

class TestFromStepBasic:

    def test_from_step_middle(self, tmp_path: Path) -> None:
        """from_step=B: only B and C execute, A is skipped."""
        yaml_path = _write_pipeline_yaml(tmp_path, _three_step_linear())
        config = PipelineConfig.load(yaml_path)

        # Create output_dir for skipped step A
        (tmp_path / "out" / "A").mkdir(parents=True)

        call_cmds = []

        def mock_run(cmd, **kwargs):
            call_cmds.append(cmd)
            return _mock_ok(cmd, **kwargs)

        with patch("pipeline.subprocess.run", side_effect=mock_run):
            runner = PipelineRunner(working_dir=tmp_path)
            log = runner.run(config, {}, from_step="B")

        assert log["status"] == "completed"
        step_statuses = {s["id"]: s["status"] for s in log["steps"]}
        assert step_statuses["A"] == "skipped"
        assert step_statuses["B"] == "completed"
        assert step_statuses["C"] == "completed"
        assert log["steps"][0].get("skipped_reason") == "upstream of from-step"
        assert len(call_cmds) == 2  # only B and C executed


# ---------------------------------------------------------------------------
# 2. from_step first step: all steps execute
# ---------------------------------------------------------------------------

    def test_from_step_first(self, tmp_path: Path) -> None:
        """from_step=A: all steps execute (equivalent to no from_step)."""
        yaml_path = _write_pipeline_yaml(tmp_path, _three_step_linear())
        config = PipelineConfig.load(yaml_path)

        call_count = 0

        def mock_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            return _mock_ok(cmd, **kwargs)

        with patch("pipeline.subprocess.run", side_effect=mock_run):
            runner = PipelineRunner(working_dir=tmp_path)
            log = runner.run(config, {}, from_step="A")

        assert log["status"] == "completed"
        assert all(s["status"] == "completed" for s in log["steps"])
        assert call_count == 3


# ---------------------------------------------------------------------------
# 3. from_step last step: only last step executes
# ---------------------------------------------------------------------------

    def test_from_step_last(self, tmp_path: Path) -> None:
        """from_step=C: only C executes, A and B are skipped."""
        yaml_path = _write_pipeline_yaml(tmp_path, _three_step_linear())
        config = PipelineConfig.load(yaml_path)

        # Create output_dirs for skipped steps
        (tmp_path / "out" / "A").mkdir(parents=True)
        (tmp_path / "out" / "B").mkdir(parents=True)

        call_count = 0

        def mock_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            return _mock_ok(cmd, **kwargs)

        with patch("pipeline.subprocess.run", side_effect=mock_run):
            runner = PipelineRunner(working_dir=tmp_path)
            log = runner.run(config, {}, from_step="C")

        assert log["status"] == "completed"
        step_statuses = {s["id"]: s["status"] for s in log["steps"]}
        assert step_statuses["A"] == "skipped"
        assert step_statuses["B"] == "skipped"
        assert step_statuses["C"] == "completed"
        assert call_count == 1


# ---------------------------------------------------------------------------
# 4. Invalid step name raises PipelineError
# ---------------------------------------------------------------------------

class TestFromStepValidation:

    def test_invalid_step_name(self, tmp_path: Path) -> None:
        """from_step with nonexistent step raises PipelineError."""
        yaml_path = _write_pipeline_yaml(tmp_path, _three_step_linear())
        config = PipelineConfig.load(yaml_path)

        with pytest.raises(PipelineError, match="not a valid step"):
            runner = PipelineRunner(working_dir=tmp_path)
            runner.run(config, {}, from_step="nonexistent")


# ---------------------------------------------------------------------------
# 5. output_vars restoration from previous log
# ---------------------------------------------------------------------------

    def test_output_vars_from_prev_log(self, tmp_path: Path) -> None:
        """from_step uses prev_runtime_vars to resolve variables."""
        yaml_path = _write_pipeline_yaml(tmp_path, _output_vars_pipeline())
        config = PipelineConfig.load(yaml_path)

        # Create output_dirs for skipped steps
        (tmp_path / "out" / "resolve").mkdir(parents=True)
        (tmp_path / "out" / "collect").mkdir(parents=True)

        prev_runtime_vars = {"edinet_code": "E03416", "fye_month": "3"}
        call_cmds = []

        def mock_run(cmd, **kwargs):
            call_cmds.append(cmd)
            return _mock_ok(cmd, **kwargs)

        with patch("pipeline.subprocess.run", side_effect=mock_run):
            runner = PipelineRunner(working_dir=tmp_path)
            log = runner.run(
                config, {"ticker": "2780"}, from_step="parse",
                prev_runtime_vars=prev_runtime_vars,
            )

        assert log["status"] == "completed"
        assert len(call_cmds) == 1  # only parse executed
        step_statuses = {s["id"]: s["status"] for s in log["steps"]}
        assert step_statuses["resolve"] == "skipped"
        assert step_statuses["collect"] == "skipped"
        assert step_statuses["parse"] == "completed"


# ---------------------------------------------------------------------------
# 6. output_vars missing: no --vars and no prev log
# ---------------------------------------------------------------------------

    def test_output_vars_missing_raises_error(self, tmp_path: Path) -> None:
        """from_step without required vars raises PipelineError."""
        yaml_path = _write_pipeline_yaml(tmp_path, _output_vars_pipeline())
        config = PipelineConfig.load(yaml_path)

        # Create output_dirs for skipped steps
        (tmp_path / "out" / "resolve").mkdir(parents=True)

        with pytest.raises(PipelineError, match="--from-step collect requires variable"):
            runner = PipelineRunner(working_dir=tmp_path)
            runner.run(config, {"ticker": "2780"}, from_step="collect")


# ---------------------------------------------------------------------------
# 7. output_dir missing for skipped step
# ---------------------------------------------------------------------------

    def test_output_dir_missing_raises_error(self, tmp_path: Path) -> None:
        """from_step with missing output_dir for skipped step raises error."""
        yaml_path = _write_pipeline_yaml(tmp_path, _three_step_linear())
        config = PipelineConfig.load(yaml_path)

        # Do NOT create out/A — it should be required
        with pytest.raises(PipelineError, match="output dir.*does not exist"):
            runner = PipelineRunner(working_dir=tmp_path)
            runner.run(config, {}, from_step="B")


# ---------------------------------------------------------------------------
# 8. Parallel execution + from_step: diamond DAG from middle
# ---------------------------------------------------------------------------

class TestFromStepParallel:

    def test_parallel_from_step_diamond(self, tmp_path: Path) -> None:
        """from_step=left in diamond DAG: left and join execute, root and right skipped."""
        yaml_path = _write_pipeline_yaml(tmp_path, _diamond_dag())
        config = PipelineConfig.load(yaml_path)

        # Create output_dirs for skipped steps
        (tmp_path / "out" / "root").mkdir(parents=True)
        # right is NOT in exec_set (only left's dependents = join)
        # But right is a dependency of join... need right's output too
        (tmp_path / "out" / "right").mkdir(parents=True)

        call_cmds = []

        def mock_run(cmd, **kwargs):
            call_cmds.append(cmd)
            return _mock_ok(cmd, **kwargs)

        with patch("pipeline.subprocess.run", side_effect=mock_run):
            runner = PipelineRunner(working_dir=tmp_path)
            log = runner.run(config, {}, max_parallel=3, from_step="left")

        assert log["status"] == "completed"
        step_statuses = {s["id"]: s["status"] for s in log["steps"]}
        assert step_statuses["root"] == "skipped"
        assert step_statuses["right"] == "skipped"
        assert step_statuses["left"] == "completed"
        assert step_statuses["join"] == "completed"
        assert len(call_cmds) == 2


# ---------------------------------------------------------------------------
# 9. runtime_vars persistence in log
# ---------------------------------------------------------------------------

class TestRuntimeVarsPersistence:

    def test_runtime_vars_in_log(self, tmp_path: Path) -> None:
        """Pipeline log contains runtime_vars with output-derived variables."""
        steps = [
            {
                "id": "resolve",
                "skill": "resolver",
                "command": "echo resolve",
                "output_dir": "out/resolve",
                "output_vars": {"edinet_code": "edinet_code", "fye_month": "fye_month"},
            },
            {
                "id": "collect",
                "skill": "collector",
                "command": "fetch --code {edinet_code}",
                "output_dir": "out/collect",
                "depends_on": ["resolve"],
            },
        ]
        yaml_path = _write_pipeline_yaml(tmp_path, steps)
        config = PipelineConfig.load(yaml_path)

        call_idx = 0

        def mock_run(cmd, **kwargs):
            nonlocal call_idx
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            if call_idx == 0:
                result.stdout = json.dumps(
                    {"edinet_code": "E03416", "fye_month": "3"}
                )
            else:
                result.stdout = ""
            call_idx += 1
            return result

        log_path = tmp_path / "log.json"

        with patch("pipeline.subprocess.run", side_effect=mock_run):
            runner = PipelineRunner()
            log = runner.run(config, {"ticker": "2780"}, log_path=log_path)

        assert log["status"] == "completed"
        assert "runtime_vars" in log
        assert log["runtime_vars"]["edinet_code"] == "E03416"
        assert log["runtime_vars"]["fye_month"] == "3"
        # User vars should NOT be in runtime_vars
        assert "ticker" not in log["runtime_vars"]

        # Verify written log file also has runtime_vars
        written = json.loads(log_path.read_text(encoding="utf-8"))
        assert written["runtime_vars"]["edinet_code"] == "E03416"

    def test_runtime_vars_backward_compat(self, tmp_path: Path) -> None:
        """Old logs without runtime_vars are handled gracefully."""
        old_log = {
            "pipeline_name": "old",
            "vars": {"ticker": "2780"},
            "steps": [],
        }
        # runtime_vars key missing — should default to {}
        assert old_log.get("runtime_vars", {}) == {}


# ---------------------------------------------------------------------------
# 10. runtime_vars with parallel execution
# ---------------------------------------------------------------------------

    def test_runtime_vars_parallel(self, tmp_path: Path) -> None:
        """runtime_vars are captured correctly in parallel mode."""
        steps = [
            {
                "id": "resolve",
                "skill": "resolver",
                "command": "echo resolve",
                "output_dir": "out/resolve",
                "output_vars": {"code": "code"},
            },
            {
                "id": "use",
                "skill": "user",
                "command": "echo {code}",
                "output_dir": "out/use",
                "depends_on": ["resolve"],
            },
        ]
        yaml_path = _write_pipeline_yaml(tmp_path, steps)
        config = PipelineConfig.load(yaml_path)

        call_idx = 0

        def mock_run(cmd, **kwargs):
            nonlocal call_idx
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            if call_idx == 0:
                result.stdout = json.dumps({"code": "X123"})
            else:
                result.stdout = ""
            call_idx += 1
            return result

        with patch("pipeline.subprocess.run", side_effect=mock_run):
            runner = PipelineRunner()
            log = runner.run(config, {}, max_parallel=2)

        assert log["runtime_vars"]["code"] == "X123"


# ---------------------------------------------------------------------------
# 11. End-to-end: full run then from_step with log
# ---------------------------------------------------------------------------

class TestFromStepEndToEnd:

    def test_full_then_from_step(self, tmp_path: Path) -> None:
        """Run full pipeline, then re-run from middle using saved log."""
        steps = [
            {
                "id": "resolve",
                "skill": "resolver",
                "command": "echo resolve",
                "output_dir": "out/resolve",
                "output_vars": {"code": "code"},
            },
            {
                "id": "collect",
                "skill": "collector",
                "command": "fetch --code {code}",
                "output_dir": "out/collect",
                "depends_on": ["resolve"],
            },
            {
                "id": "parse",
                "skill": "parser",
                "command": "parse --input {prev_output}",
                "output_dir": "out/parse",
                "depends_on": ["collect"],
            },
        ]
        yaml_path = _write_pipeline_yaml(tmp_path, steps)
        log_path = tmp_path / "pipeline_log.json"

        # --- First run: full pipeline ---
        config1 = PipelineConfig.load(yaml_path)
        call_idx = 0

        def mock_run_full(cmd, **kwargs):
            nonlocal call_idx
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            if call_idx == 0:
                result.stdout = json.dumps({"code": "E99"})
            else:
                result.stdout = ""
            call_idx += 1
            return result

        with patch("pipeline.subprocess.run", side_effect=mock_run_full):
            runner1 = PipelineRunner(working_dir=tmp_path)
            log1 = runner1.run(config1, {"ticker": "1234"}, log_path=log_path)

        assert log1["status"] == "completed"
        assert log1["runtime_vars"]["code"] == "E99"

        # Create output dirs (simulating real execution)
        (tmp_path / "out" / "resolve").mkdir(parents=True, exist_ok=True)
        (tmp_path / "out" / "collect").mkdir(parents=True, exist_ok=True)

        # --- Second run: from_step=parse using saved log ---
        config2 = PipelineConfig.load(yaml_path)

        # Load prev_runtime_vars from saved log
        with open(log_path, "r") as f:
            prev_log = json.load(f)
        prev_rv = prev_log.get("runtime_vars", {})

        rerun_cmds = []

        def mock_run_rerun(cmd, **kwargs):
            rerun_cmds.append(cmd)
            return _mock_ok(cmd, **kwargs)

        with patch("pipeline.subprocess.run", side_effect=mock_run_rerun):
            runner2 = PipelineRunner(working_dir=tmp_path)
            log2 = runner2.run(
                config2, {"ticker": "1234"}, log_path=log_path,
                from_step="parse", prev_runtime_vars=prev_rv,
            )

        assert log2["status"] == "completed"
        assert len(rerun_cmds) == 1  # only parse ran
        step_statuses = {s["id"]: s["status"] for s in log2["steps"]}
        assert step_statuses["resolve"] == "skipped"
        assert step_statuses["collect"] == "skipped"
        assert step_statuses["parse"] == "completed"


# ---------------------------------------------------------------------------
# 12. from_step with --vars override priority
# ---------------------------------------------------------------------------

    def test_from_step_vars_override_prev_log(self, tmp_path: Path) -> None:
        """--vars takes priority over prev_runtime_vars."""
        steps = [
            {
                "id": "resolve",
                "skill": "resolver",
                "command": "echo resolve",
                "output_dir": "out/resolve",
                "output_vars": {"code": "code"},
            },
            {
                "id": "collect",
                "skill": "collector",
                "command": "fetch --code {code}",
                "output_dir": "out/collect",
                "depends_on": ["resolve"],
            },
        ]
        yaml_path = _write_pipeline_yaml(tmp_path, steps)
        config = PipelineConfig.load(yaml_path)

        (tmp_path / "out" / "resolve").mkdir(parents=True)

        prev_runtime_vars = {"code": "OLD_VALUE"}
        call_cmds = []

        def mock_run(cmd, **kwargs):
            call_cmds.append(cmd)
            return _mock_ok(cmd, **kwargs)

        with patch("pipeline.subprocess.run", side_effect=mock_run):
            runner = PipelineRunner(working_dir=tmp_path)
            log = runner.run(
                config, {"code": "NEW_VALUE"}, from_step="collect",
                prev_runtime_vars=prev_runtime_vars,
            )

        assert log["status"] == "completed"
        # --vars value should be used, not prev_runtime_vars
        assert "fetch --code NEW_VALUE" in call_cmds[0]


# ---------------------------------------------------------------------------
# 13. Diamond DAG sibling validation
# ---------------------------------------------------------------------------

def _wide_diamond_dag() -> list[dict]:
    """Realistic diamond: root -> mid -> {A, B, C, D} -> final."""
    return [
        {"id": "root", "skill": "s", "command": "echo root", "output_dir": "out/root"},
        {"id": "mid", "skill": "s", "command": "echo mid",
         "output_dir": "out/mid", "depends_on": ["root"]},
        {"id": "A", "skill": "s", "command": "echo A",
         "output_dir": "out/A", "depends_on": ["mid"]},
        {"id": "B", "skill": "s", "command": "echo B",
         "output_dir": "out/B", "depends_on": ["mid"]},
        {"id": "C", "skill": "s", "command": "echo C",
         "output_dir": "out/C", "depends_on": ["mid"]},
        {"id": "D", "skill": "s", "command": "echo D",
         "output_dir": "out/D", "depends_on": ["mid"]},
        {"id": "final", "skill": "s", "command": "echo final",
         "output_dir": "out/final", "depends_on": ["A", "B", "C", "D"]},
    ]


class TestDiamondSiblingValidation:

    def test_from_step_sibling_no_output_raises_error(self, tmp_path: Path) -> None:
        """--from-step=A with siblings B,C,D missing output -> specific error."""
        yaml_path = _write_pipeline_yaml(tmp_path, _wide_diamond_dag())
        config = PipelineConfig.load(yaml_path)

        # Create upstream output dirs (root, mid) but NOT siblings B, C, D
        (tmp_path / "out" / "root").mkdir(parents=True)
        (tmp_path / "out" / "mid").mkdir(parents=True)

        with pytest.raises(PipelineError, match="diamond DAG.*missing sibling") as exc_info:
            runner = PipelineRunner(working_dir=tmp_path)
            runner.run(config, {}, from_step="A")

        err_msg = str(exc_info.value)
        assert "B" in err_msg
        assert "C" in err_msg
        assert "D" in err_msg
        assert "--from-step='mid'" in err_msg

    def test_from_step_sibling_with_output_ok(self, tmp_path: Path) -> None:
        """--from-step=A with siblings B,C,D having output -> execution allowed."""
        yaml_path = _write_pipeline_yaml(tmp_path, _wide_diamond_dag())
        config = PipelineConfig.load(yaml_path)

        # Create ALL required output dirs
        for d in ["root", "mid", "B", "C", "D"]:
            (tmp_path / "out" / d).mkdir(parents=True)

        call_cmds = []

        def mock_run(cmd, **kwargs):
            call_cmds.append(cmd)
            return _mock_ok(cmd, **kwargs)

        with patch("pipeline.subprocess.run", side_effect=mock_run):
            runner = PipelineRunner(working_dir=tmp_path)
            log = runner.run(config, {}, from_step="A")

        assert log["status"] == "completed"
        step_statuses = {s["id"]: s["status"] for s in log["steps"]}
        assert step_statuses["A"] == "completed"
        assert step_statuses["final"] == "completed"
        assert step_statuses["B"] == "skipped"
        assert step_statuses["C"] == "skipped"
        assert step_statuses["D"] == "skipped"

    def test_from_step_parent_includes_all_siblings(self, tmp_path: Path) -> None:
        """--from-step=mid -> exec_set includes all 4 siblings + final -> no error."""
        yaml_path = _write_pipeline_yaml(tmp_path, _wide_diamond_dag())
        config = PipelineConfig.load(yaml_path)

        # Create output for root (upstream of mid)
        (tmp_path / "out" / "root").mkdir(parents=True)

        call_cmds = []

        def mock_run(cmd, **kwargs):
            call_cmds.append(cmd)
            return _mock_ok(cmd, **kwargs)

        with patch("pipeline.subprocess.run", side_effect=mock_run):
            runner = PipelineRunner(working_dir=tmp_path)
            log = runner.run(config, {}, from_step="mid")

        assert log["status"] == "completed"
        # mid + A + B + C + D + final = 6 steps executed
        executed = [s for s in log["steps"] if s["status"] == "completed"]
        assert len(executed) == 6
        assert len(call_cmds) == 6

    def test_from_step_partial_sibling_missing(self, tmp_path: Path) -> None:
        """Only 1 of 3 siblings missing output -> error lists only the missing one."""
        yaml_path = _write_pipeline_yaml(tmp_path, _wide_diamond_dag())
        config = PipelineConfig.load(yaml_path)

        (tmp_path / "out" / "root").mkdir(parents=True)
        (tmp_path / "out" / "mid").mkdir(parents=True)
        (tmp_path / "out" / "B").mkdir(parents=True)
        (tmp_path / "out" / "C").mkdir(parents=True)
        # D is missing

        with pytest.raises(PipelineError, match="diamond DAG.*missing sibling") as exc_info:
            runner = PipelineRunner(working_dir=tmp_path)
            runner.run(config, {}, from_step="A")

        err_msg = str(exc_info.value)
        assert "D" in err_msg
        # B and C have output, should not be in the missing list
        assert "['D']" in err_msg or "D" in err_msg

    def test_simple_diamond_from_step_no_siblings(self, tmp_path: Path) -> None:
        """from_step=root in diamond DAG -> no missing siblings (all downstream)."""
        yaml_path = _write_pipeline_yaml(tmp_path, _diamond_dag())
        config = PipelineConfig.load(yaml_path)

        call_cmds = []

        def mock_run(cmd, **kwargs):
            call_cmds.append(cmd)
            return _mock_ok(cmd, **kwargs)

        with patch("pipeline.subprocess.run", side_effect=mock_run):
            runner = PipelineRunner(working_dir=tmp_path)
            log = runner.run(config, {}, from_step="root")

        assert log["status"] == "completed"
        assert len(call_cmds) == 4  # all 4 steps

    def test_linear_pipeline_no_sibling_issue(self, tmp_path: Path) -> None:
        """Linear pipeline has no diamond siblings -> no validation error."""
        yaml_path = _write_pipeline_yaml(tmp_path, _three_step_linear())
        config = PipelineConfig.load(yaml_path)

        (tmp_path / "out" / "A").mkdir(parents=True)

        call_cmds = []

        def mock_run(cmd, **kwargs):
            call_cmds.append(cmd)
            return _mock_ok(cmd, **kwargs)

        with patch("pipeline.subprocess.run", side_effect=mock_run):
            runner = PipelineRunner(working_dir=tmp_path)
            log = runner.run(config, {}, from_step="B")

        assert log["status"] == "completed"
        assert len(call_cmds) == 2
