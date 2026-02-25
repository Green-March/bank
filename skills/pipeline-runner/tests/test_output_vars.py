"""Tests for output_vars feature in pipeline-runner."""

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
    PipelineStep,
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


# ---------------------------------------------------------------------------
# a. output_vars ステップ間変数伝搬テスト
# ---------------------------------------------------------------------------

def test_output_vars_propagation(tmp_path: Path) -> None:
    """output_vars from step1 are resolved in step2's command."""
    steps = [
        {
            "id": "resolve",
            "skill": "resolver",
            "command": "echo resolve",
            "output_dir": "out/resolve",
            "output_vars": {"edinet_code": "edinet_code"},
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
            result.stdout = json.dumps({"edinet_code": "E03416"})
        else:
            result.stdout = ""
        call_idx += 1
        return result

    with patch("pipeline.subprocess.run", side_effect=mock_run) as mock:
        runner = PipelineRunner()
        log = runner.run(config, {"ticker": "2780"})

    assert log["status"] == "completed"
    calls = mock.call_args_list
    assert "fetch --code E03416" in calls[1][0][0]


# ---------------------------------------------------------------------------
# b. --vars オーバーライド優先度テスト
# ---------------------------------------------------------------------------

def test_output_vars_no_override_user_vars(tmp_path: Path) -> None:
    """--vars keys take precedence over output_vars."""
    steps = [
        {
            "id": "resolve",
            "skill": "resolver",
            "command": "echo resolve",
            "output_dir": "out/resolve",
            "output_vars": {"edinet_code": "edinet_code"},
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

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        result.stdout = json.dumps({"edinet_code": "E99999"})
        return result

    with patch("pipeline.subprocess.run", side_effect=mock_run) as mock:
        runner = PipelineRunner()
        log = runner.run(config, {"edinet_code": "E00001"})

    assert log["status"] == "completed"
    calls = mock.call_args_list
    assert "fetch --code E00001" in calls[1][0][0]


# ---------------------------------------------------------------------------
# c. 未解決 placeholder バリデーションエラーテスト
# ---------------------------------------------------------------------------

def test_unresolved_placeholder_validation(tmp_path: Path) -> None:
    """Unresolvable placeholder raises PipelineError with helpful message."""
    steps = [
        {
            "id": "collect",
            "skill": "collector",
            "command": "fetch --code {edinet_code} --ticker {ticker}",
            "output_dir": "out/collect",
        },
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    with pytest.raises(PipelineError, match="変数 'edinet_code' が未定義です"):
        runner = PipelineRunner()
        runner.run(config, {"ticker": "2780"})


# ---------------------------------------------------------------------------
# d. JSON パース失敗テスト（非 JSON stdout）
# ---------------------------------------------------------------------------

def test_output_vars_json_parse_failure(tmp_path: Path) -> None:
    """Non-JSON stdout raises PipelineError with stdout excerpt."""
    steps = [
        {
            "id": "bad",
            "skill": "s",
            "command": "echo not-json",
            "output_dir": "out/bad",
            "output_vars": {"key": "key"},
        },
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = ""
    mock_result.stdout = "not valid json"

    with patch("pipeline.subprocess.run", return_value=mock_result):
        with pytest.raises(PipelineError, match="not valid JSON"):
            runner = PipelineRunner()
            runner.run(config, {})


# ---------------------------------------------------------------------------
# e. JSON 型チェックテスト（list/int/str → PipelineError）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_value,type_name", [
    ([1, 2], "list"),
    (42, "int"),
    ("hello", "str"),
])
def test_output_vars_non_dict_json(tmp_path: Path, bad_value: object, type_name: str) -> None:
    """Non-dict JSON stdout raises PipelineError with type name."""
    steps = [
        {
            "id": "bad",
            "skill": "s",
            "command": "echo bad",
            "output_dir": "out/bad",
            "output_vars": {"key": "key"},
        },
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = ""
    mock_result.stdout = json.dumps(bad_value)

    with patch("pipeline.subprocess.run", return_value=mock_result):
        with pytest.raises(PipelineError, match=f"got {type_name}"):
            runner = PipelineRunner()
            runner.run(config, {})


# ---------------------------------------------------------------------------
# f. JSON キー欠損テスト
# ---------------------------------------------------------------------------

def test_output_vars_missing_key(tmp_path: Path) -> None:
    """Missing JSON key raises PipelineError with key name."""
    steps = [
        {
            "id": "missing",
            "skill": "s",
            "command": "echo missing",
            "output_dir": "out/missing",
            "output_vars": {"my_var": "nonexistent_key"},
        },
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = ""
    mock_result.stdout = json.dumps({"other_key": "value"})

    with patch("pipeline.subprocess.run", return_value=mock_result):
        with pytest.raises(PipelineError, match="'nonexistent_key' not found"):
            runner = PipelineRunner()
            runner.run(config, {})


# ---------------------------------------------------------------------------
# g. stderr 転送 + StepLog.error 格納確認（str 型）
# ---------------------------------------------------------------------------

def test_stderr_forwarding_and_error(tmp_path: Path) -> None:
    """stderr is forwarded to sys.stderr and stored as str in StepLog.error."""
    steps = [
        {"id": "err", "skill": "s", "command": "echo err", "output_dir": "out/err"},
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "some error message"
    mock_result.stdout = ""

    with patch("pipeline.subprocess.run", return_value=mock_result):
        with patch("pipeline.sys.stderr") as mock_stderr:
            runner = PipelineRunner()
            log = runner.run(config, {})

    assert log["status"] == "failed"
    assert log["steps"][0]["error"] == "some error message"
    assert isinstance(log["steps"][0]["error"], str)
    mock_stderr.write.assert_called_with("some error message")


# ---------------------------------------------------------------------------
# h. stderr 空時 exit-code フォールバックテスト
# ---------------------------------------------------------------------------

def test_stderr_empty_exit_code_fallback(tmp_path: Path) -> None:
    """Empty stderr falls back to exit code message."""
    steps = [
        {"id": "err", "skill": "s", "command": "echo err", "output_dir": "out/err"},
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    mock_result = MagicMock()
    mock_result.returncode = 42
    mock_result.stderr = ""
    mock_result.stdout = ""

    with patch("pipeline.subprocess.run", return_value=mock_result):
        runner = PipelineRunner()
        log = runner.run(config, {})

    assert log["status"] == "failed"
    assert log["steps"][0]["error"] == "Step failed with exit code 42"
