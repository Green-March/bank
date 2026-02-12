"""Tests for context-checkpoint CLI."""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

MAIN_PY = str(Path(__file__).resolve().parents[1] / "scripts" / "main.py")


def run_cli(*args: str, checkpoint_dir: str | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, MAIN_PY, *args]
    if checkpoint_dir:
        cmd.extend(["--checkpoint-dir", checkpoint_dir])
    return subprocess.run(cmd, capture_output=True, text=True)


class TestSaveCheckpoint:
    def test_save_checkpoint(self, tmp_path: Path) -> None:
        cp_dir = str(tmp_path / "checkpoints")
        result = run_cli(
            "save",
            "--agent", "senior",
            "--task-id", "T1",
            "--status", "completed",
            "--key-findings", "finding1",
            "--key-findings", "finding2",
            "--output-files", "output/a.json",
            "--next-steps", "next1",
            "--context-summary", "summary text",
            checkpoint_dir=cp_dir,
        )
        assert result.returncode == 0
        assert "Saved:" in result.stdout

        saved_file = tmp_path / "checkpoints" / "senior_T1.yaml"
        assert saved_file.exists()

        with open(saved_file, "r") as f:
            data = yaml.safe_load(f)

        assert data["task_id"] == "T1"
        assert data["agent_id"] == "senior"
        assert data["status"] == "completed"
        assert data["key_findings"] == ["finding1", "finding2"]
        assert data["output_files"] == ["output/a.json"]
        assert data["next_steps"] == ["next1"]
        assert data["context_summary"] == "summary text"
        assert "timestamp" in data

    def test_save_minimal(self, tmp_path: Path) -> None:
        cp_dir = str(tmp_path / "checkpoints")
        result = run_cli(
            "save",
            "--agent", "junior1",
            "--task-id", "T2",
            "--status", "in_progress",
            checkpoint_dir=cp_dir,
        )
        assert result.returncode == 0

        saved_file = tmp_path / "checkpoints" / "junior1_T2.yaml"
        with open(saved_file, "r") as f:
            data = yaml.safe_load(f)

        assert data["key_findings"] == []
        assert data["output_files"] == []
        assert data["next_steps"] == []
        assert data["context_summary"] == ""


class TestLoadCheckpoint:
    def test_load_checkpoint(self, tmp_path: Path) -> None:
        cp_dir = str(tmp_path / "checkpoints")
        # save first
        run_cli(
            "save",
            "--agent", "senior",
            "--task-id", "T1",
            "--status", "completed",
            "--key-findings", "result1",
            "--output-files", "file.json",
            checkpoint_dir=cp_dir,
        )
        # load
        result = run_cli(
            "load",
            "--agent", "senior",
            "--task-id", "T1",
            checkpoint_dir=cp_dir,
        )
        assert result.returncode == 0

        loaded = yaml.safe_load(result.stdout)
        assert loaded["task_id"] == "T1"
        assert loaded["agent_id"] == "senior"
        assert loaded["status"] == "completed"
        assert loaded["key_findings"] == ["result1"]
        assert loaded["output_files"] == ["file.json"]


class TestListCheckpoints:
    def test_list_checkpoints(self, tmp_path: Path) -> None:
        cp_dir = str(tmp_path / "checkpoints")
        # save multiple
        run_cli("save", "--agent", "senior", "--task-id", "T1", "--status", "completed", checkpoint_dir=cp_dir)
        run_cli("save", "--agent", "junior1", "--task-id", "T2", "--status", "in_progress", checkpoint_dir=cp_dir)
        run_cli("save", "--agent", "junior2", "--task-id", "T3", "--status", "blocked", checkpoint_dir=cp_dir)

        result = run_cli("list", checkpoint_dir=cp_dir)
        assert result.returncode == 0
        assert "senior/T1" in result.stdout
        assert "junior1/T2" in result.stdout
        assert "junior2/T3" in result.stdout

    def test_list_filter_by_agent(self, tmp_path: Path) -> None:
        cp_dir = str(tmp_path / "checkpoints")
        run_cli("save", "--agent", "senior", "--task-id", "T1", "--status", "completed", checkpoint_dir=cp_dir)
        run_cli("save", "--agent", "junior1", "--task-id", "T2", "--status", "in_progress", checkpoint_dir=cp_dir)

        result = run_cli("list", "--agent", "senior", checkpoint_dir=cp_dir)
        assert result.returncode == 0
        assert "senior/T1" in result.stdout
        assert "junior1" not in result.stdout

    def test_list_empty(self, tmp_path: Path) -> None:
        cp_dir = str(tmp_path / "empty_checkpoints")
        result = run_cli("list", checkpoint_dir=cp_dir)
        assert result.returncode == 0
        assert "No checkpoints found" in result.stdout


class TestOverwriteCheckpoint:
    def test_overwrite_checkpoint(self, tmp_path: Path) -> None:
        cp_dir = str(tmp_path / "checkpoints")
        # save first version
        run_cli(
            "save",
            "--agent", "senior",
            "--task-id", "T1",
            "--status", "in_progress",
            "--key-findings", "first",
            checkpoint_dir=cp_dir,
        )
        # overwrite with second version
        run_cli(
            "save",
            "--agent", "senior",
            "--task-id", "T1",
            "--status", "completed",
            "--key-findings", "second",
            checkpoint_dir=cp_dir,
        )

        saved_file = tmp_path / "checkpoints" / "senior_T1.yaml"
        with open(saved_file, "r") as f:
            data = yaml.safe_load(f)

        assert data["status"] == "completed"
        assert data["key_findings"] == ["second"]


class TestMissingCheckpoint:
    def test_missing_checkpoint(self, tmp_path: Path) -> None:
        cp_dir = str(tmp_path / "checkpoints")
        (tmp_path / "checkpoints").mkdir(parents=True, exist_ok=True)

        result = run_cli(
            "load",
            "--agent", "senior",
            "--task-id", "nonexistent",
            checkpoint_dir=cp_dir,
        )
        assert result.returncode == 1
        assert "Error" in result.stderr
        assert "not found" in result.stderr
