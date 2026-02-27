"""Tests for PYTHONPATH auto-resolution in _run_step()."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from pipeline import PipelineConfig, PipelineRunner, PipelineStep


def _write_pipeline_yaml(path: Path, steps: list[dict], name: str = "test") -> Path:
    data = {
        "pipeline": {
            "name": name,
            "description": "test",
            "steps": steps,
        }
    }
    yaml_path = path / "pipeline.yaml"
    yaml_path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return yaml_path


# ---------------------------------------------------------------------------
# Unit tests: env construction
# ---------------------------------------------------------------------------


class TestPythonPathEnv:
    """Verify that _run_step() builds env with PYTHONPATH correctly."""

    def test_env_passed_to_subprocess(self, tmp_path: Path) -> None:
        """subprocess.run() receives env kwarg with PYTHONPATH set."""
        steps = [{"id": "s1", "skill": "sk", "command": "echo hi", "output_dir": str(tmp_path / "out")}]
        yaml_path = _write_pipeline_yaml(tmp_path, steps)
        config = PipelineConfig.load(yaml_path)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("pipeline.subprocess.run", return_value=mock_result) as mock_run:
            runner = PipelineRunner()
            runner.run(config, {})

        _, kwargs = mock_run.call_args
        assert "env" in kwargs
        assert "PYTHONPATH" in kwargs["env"]

    def test_pythonpath_contains_working_dir(self, tmp_path: Path) -> None:
        """PYTHONPATH starts with self.working_dir (project root)."""
        steps = [{"id": "s1", "skill": "sk", "command": "echo hi", "output_dir": str(tmp_path / "out")}]
        yaml_path = _write_pipeline_yaml(tmp_path, steps)
        config = PipelineConfig.load(yaml_path)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("pipeline.subprocess.run", return_value=mock_result) as mock_run:
            runner = PipelineRunner()
            runner.run(config, {})

        _, kwargs = mock_run.call_args
        pythonpath = kwargs["env"]["PYTHONPATH"]
        working_dir = str(runner.working_dir)
        assert pythonpath.startswith(working_dir)

    def test_pythonpath_prepend_to_existing(self, tmp_path: Path) -> None:
        """When PYTHONPATH already exists, working_dir is prepended."""
        steps = [{"id": "s1", "skill": "sk", "command": "echo hi", "output_dir": str(tmp_path / "out")}]
        yaml_path = _write_pipeline_yaml(tmp_path, steps)
        config = PipelineConfig.load(yaml_path)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        existing_path = "/some/existing/path"
        with patch.dict(os.environ, {"PYTHONPATH": existing_path}):
            with patch("pipeline.subprocess.run", return_value=mock_result) as mock_run:
                runner = PipelineRunner()
                runner.run(config, {})

        _, kwargs = mock_run.call_args
        pythonpath = kwargs["env"]["PYTHONPATH"]
        parts = pythonpath.split(os.pathsep)
        assert parts[0] == str(runner.working_dir)
        assert existing_path in parts

    def test_pythonpath_without_existing(self, tmp_path: Path) -> None:
        """When PYTHONPATH is unset, only working_dir is set."""
        steps = [{"id": "s1", "skill": "sk", "command": "echo hi", "output_dir": str(tmp_path / "out")}]
        yaml_path = _write_pipeline_yaml(tmp_path, steps)
        config = PipelineConfig.load(yaml_path)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        env_without_pythonpath = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        with patch.dict(os.environ, env_without_pythonpath, clear=True):
            with patch("pipeline.subprocess.run", return_value=mock_result) as mock_run:
                runner = PipelineRunner()
                runner.run(config, {})

        _, kwargs = mock_run.call_args
        pythonpath = kwargs["env"]["PYTHONPATH"]
        assert pythonpath == str(runner.working_dir)
        assert os.pathsep not in pythonpath

    def test_no_hardcoded_paths(self) -> None:
        """_run_step source must not contain hardcoded absolute paths."""
        import inspect
        from pipeline import PipelineRunner

        source = inspect.getsource(PipelineRunner._run_step)
        # Should use self.working_dir, not hardcoded paths
        assert "/Users/" not in source
        assert "/home/" not in source
        assert "C:\\" not in source


# ---------------------------------------------------------------------------
# Unit tests: working_dir default resolution
# ---------------------------------------------------------------------------


class TestWorkingDirDefault:
    """Verify PipelineRunner defaults working_dir to project root."""

    def test_default_working_dir_is_not_none(self) -> None:
        """When working_dir is omitted, it must not be None."""
        runner = PipelineRunner()
        assert runner.working_dir is not None

    def test_default_working_dir_is_valid_directory(self) -> None:
        """Default working_dir must point to an existing directory."""
        runner = PipelineRunner()
        assert Path(runner.working_dir).is_dir()

    def test_default_working_dir_not_none_string(self) -> None:
        """Default working_dir must never be the literal string 'None'."""
        runner = PipelineRunner()
        assert runner.working_dir != "None"

    def test_explicit_working_dir_is_preserved(self, tmp_path: Path) -> None:
        """Explicit working_dir is used as-is."""
        runner = PipelineRunner(working_dir=tmp_path)
        assert runner.working_dir == str(tmp_path)

    def test_pythonpath_not_none_string(self, tmp_path: Path) -> None:
        """PYTHONPATH in subprocess env must never contain 'None'."""
        steps = [{"id": "s1", "skill": "sk", "command": "echo hi", "output_dir": str(tmp_path / "out")}]
        yaml_path = _write_pipeline_yaml(tmp_path, steps)
        config = PipelineConfig.load(yaml_path)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("pipeline.subprocess.run", return_value=mock_result) as mock_run:
            runner = PipelineRunner()
            runner.run(config, {})

        _, kwargs = mock_run.call_args
        pythonpath = kwargs["env"]["PYTHONPATH"]
        assert "None" not in pythonpath
