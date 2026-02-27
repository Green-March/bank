"""Tests for parallel execution in pipeline-runner."""

from __future__ import annotations

import json
import sys
import time
import threading
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


def _diamond_steps() -> list[dict]:
    """Diamond DAG: root -> {left, right} -> join."""
    return [
        {"id": "root", "skill": "s", "command": "echo root", "output_dir": "o/root"},
        {"id": "left", "skill": "s", "command": "echo left", "output_dir": "o/left",
         "depends_on": ["root"]},
        {"id": "right", "skill": "s", "command": "echo right", "output_dir": "o/right",
         "depends_on": ["root"]},
        {"id": "join", "skill": "s", "command": "echo join", "output_dir": "o/join",
         "depends_on": ["left", "right"]},
    ]


def _three_parallel_steps() -> list[dict]:
    """Mimics collect_jquants/collect/web_research (3 parallel after resolve)."""
    return [
        {"id": "resolve", "skill": "s", "command": "echo resolve", "output_dir": "o/resolve"},
        {"id": "collect_jquants", "skill": "s", "command": "echo cj",
         "output_dir": "o/cj", "depends_on": ["resolve"]},
        {"id": "collect", "skill": "s", "command": "echo c",
         "output_dir": "o/c", "depends_on": ["resolve"]},
        {"id": "web_research", "skill": "s", "command": "echo wr",
         "output_dir": "o/wr", "depends_on": ["resolve"]},
    ]


def _pipeline_with_two_paths() -> list[dict]:
    """Two independent paths: A->B->C and D->E."""
    return [
        {"id": "A", "skill": "s", "command": "echo A", "output_dir": "o/A"},
        {"id": "B", "skill": "s", "command": "echo B", "output_dir": "o/B",
         "depends_on": ["A"]},
        {"id": "C", "skill": "s", "command": "echo C", "output_dir": "o/C",
         "depends_on": ["B"]},
        {"id": "D", "skill": "s", "command": "echo D", "output_dir": "o/D"},
        {"id": "E", "skill": "s", "command": "echo E", "output_dir": "o/E",
         "depends_on": ["D"]},
    ]


# ---------------------------------------------------------------------------
# 1. Independent steps run in parallel
# ---------------------------------------------------------------------------

def test_independent_steps_parallel(tmp_path: Path) -> None:
    """collect_jquants/collect/web_research run concurrently after resolve."""
    yaml_path = _write_pipeline_yaml(tmp_path, _three_parallel_steps())
    config = PipelineConfig.load(yaml_path)

    execution_times: dict[str, float] = {}
    lock = threading.Lock()

    def mock_run(cmd, **kwargs):
        step_id = cmd.split()[-1]
        with lock:
            execution_times[step_id] = time.monotonic()
        # Small sleep to allow overlap detection
        time.sleep(0.05)
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        return result

    with patch("pipeline.subprocess.run", side_effect=mock_run):
        runner = PipelineRunner()
        log = runner.run(config, {}, max_parallel=3)

    assert log["status"] == "completed"
    assert len(log["steps"]) == 4

    # Verify concurrency_info exists and shows parallel execution
    assert "concurrency_info" in log
    # At least two of the three parallel steps should show concurrency > 1
    parallel_ids = {"collect_jquants", "collect", "web_research"}
    parallel_concurrency = [
        log["concurrency_info"][sid]
        for sid in parallel_ids
        if sid in log["concurrency_info"]
    ]
    assert max(parallel_concurrency) >= 2, (
        f"Expected parallel execution, got concurrency: {parallel_concurrency}"
    )


# ---------------------------------------------------------------------------
# 2. Diamond DAG parallel execution
# ---------------------------------------------------------------------------

def test_diamond_dag_parallel(tmp_path: Path) -> None:
    """Diamond DAG: left and right run in parallel, join waits for both."""
    yaml_path = _write_pipeline_yaml(tmp_path, _diamond_steps())
    config = PipelineConfig.load(yaml_path)

    completed_order: list[str] = []
    lock = threading.Lock()

    def mock_run(cmd, **kwargs):
        step_id = cmd.split()[-1]
        time.sleep(0.02)
        with lock:
            completed_order.append(step_id)
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        return result

    with patch("pipeline.subprocess.run", side_effect=mock_run):
        runner = PipelineRunner()
        log = runner.run(config, {}, max_parallel=3)

    assert log["status"] == "completed"
    assert len(log["steps"]) == 4

    # root must be first, join must be last
    assert completed_order[0] == "root"
    assert completed_order[-1] == "join"
    # left and right should be between root and join
    assert set(completed_order[1:3]) == {"left", "right"}


# ---------------------------------------------------------------------------
# 3. Failure propagation: downstream skipped, other path continues
# ---------------------------------------------------------------------------

def test_failure_skips_downstream_continues_other_path(tmp_path: Path) -> None:
    """When B fails, C is skipped; independent path D->E continues."""
    yaml_path = _write_pipeline_yaml(tmp_path, _pipeline_with_two_paths())
    config = PipelineConfig.load(yaml_path)

    def mock_run(cmd, **kwargs):
        step_id = cmd.split()[-1]
        result = MagicMock()
        result.stderr = ""
        result.stdout = ""
        if step_id == "B":
            result.returncode = 1
            result.stderr = "B failed"
        else:
            result.returncode = 0
        return result

    with patch("pipeline.subprocess.run", side_effect=mock_run):
        runner = PipelineRunner()
        log = runner.run(config, {}, max_parallel=3)

    assert log["status"] == "failed"

    status_map = {s["id"]: s["status"] for s in log["steps"]}
    assert status_map["A"] == "completed"
    assert status_map["B"] == "failed"
    assert status_map["C"] == "skipped"
    assert status_map["D"] == "completed"
    assert status_map["E"] == "completed"

    # Verify skipped_reason
    c_step = next(s for s in log["steps"] if s["id"] == "C")
    assert c_step["skipped_reason"] == "dependency B failed"


# ---------------------------------------------------------------------------
# 4. Transitive skip: A fails -> B,C,D all skipped
# ---------------------------------------------------------------------------

def test_transitive_skip(tmp_path: Path) -> None:
    """Failure propagates transitively through dependency chain."""
    steps = [
        {"id": "A", "skill": "s", "command": "echo A", "output_dir": "o/A"},
        {"id": "B", "skill": "s", "command": "echo B", "output_dir": "o/B",
         "depends_on": ["A"]},
        {"id": "C", "skill": "s", "command": "echo C", "output_dir": "o/C",
         "depends_on": ["B"]},
        {"id": "D", "skill": "s", "command": "echo D", "output_dir": "o/D",
         "depends_on": ["C"]},
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 1
        result.stderr = "failed"
        result.stdout = ""
        return result

    with patch("pipeline.subprocess.run", side_effect=mock_run):
        runner = PipelineRunner()
        log = runner.run(config, {}, max_parallel=3)

    assert log["status"] == "failed"
    status_map = {s["id"]: s["status"] for s in log["steps"]}
    assert status_map["A"] == "failed"
    assert status_map["B"] == "skipped"
    assert status_map["C"] == "skipped"
    assert status_map["D"] == "skipped"


# ---------------------------------------------------------------------------
# 5. output_vars propagation in parallel environment
# ---------------------------------------------------------------------------

def test_output_vars_parallel_propagation(tmp_path: Path) -> None:
    """output_vars from resolve are available to parallel downstream steps."""
    steps = [
        {
            "id": "resolve",
            "skill": "resolver",
            "command": "echo resolve",
            "output_dir": "o/resolve",
            "output_vars": {"edinet_code": "edinet_code", "fye_month": "fye_month"},
        },
        {
            "id": "collect",
            "skill": "collector",
            "command": "fetch --code {edinet_code}",
            "output_dir": "o/collect",
            "depends_on": ["resolve"],
        },
        {
            "id": "integrate",
            "skill": "integrator",
            "command": "integrate --fye {fye_month}",
            "output_dir": "o/integrate",
            "depends_on": ["resolve"],
        },
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    call_commands: list[str] = []
    lock = threading.Lock()

    def mock_run(cmd, **kwargs):
        with lock:
            call_commands.append(cmd)
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        if "resolve" in cmd:
            result.stdout = json.dumps({
                "edinet_code": "E03416",
                "fye_month": "3",
            })
        else:
            result.stdout = ""
        return result

    with patch("pipeline.subprocess.run", side_effect=mock_run):
        runner = PipelineRunner()
        log = runner.run(config, {"ticker": "2780"}, max_parallel=3)

    assert log["status"] == "completed"

    # Verify variable resolution in parallel steps
    collect_cmd = [c for c in call_commands if "fetch" in c]
    assert len(collect_cmd) == 1
    assert "fetch --code E03416" in collect_cmd[0]

    integrate_cmd = [c for c in call_commands if "integrate" in c]
    assert len(integrate_cmd) == 1
    assert "integrate --fye 3" in integrate_cmd[0]


# ---------------------------------------------------------------------------
# 6. output_vars conflict detection
# ---------------------------------------------------------------------------

def test_output_vars_conflict_error(tmp_path: Path) -> None:
    """Two parallel steps producing same output_var raises PipelineError."""
    steps = [
        {"id": "root", "skill": "s", "command": "echo root", "output_dir": "o/root"},
        {
            "id": "left",
            "skill": "s",
            "command": "echo left",
            "output_dir": "o/left",
            "depends_on": ["root"],
            "output_vars": {"shared_key": "value"},
        },
        {
            "id": "right",
            "skill": "s",
            "command": "echo right",
            "output_dir": "o/right",
            "depends_on": ["root"],
            "output_vars": {"shared_key": "value"},
        },
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stderr = ""
        result.stdout = json.dumps({"value": "data"})
        return result

    with patch("pipeline.subprocess.run", side_effect=mock_run):
        with pytest.raises(PipelineError, match="output_var conflict"):
            runner = PipelineRunner()
            runner.run(config, {}, max_parallel=3)


# ---------------------------------------------------------------------------
# 7. max_parallel=1 backward compatibility
# ---------------------------------------------------------------------------

def test_max_parallel_1_sequential(tmp_path: Path) -> None:
    """max_parallel=1 produces identical behavior to old sequential mode."""
    steps = [
        {"id": "good", "skill": "s", "command": "echo ok", "output_dir": "o/g"},
        {"id": "bad", "skill": "s", "command": "false", "output_dir": "o/b",
         "depends_on": ["good"]},
        {"id": "skip", "skill": "s", "command": "echo skip", "output_dir": "o/s",
         "depends_on": ["bad"]},
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    def mock_run(cmd, **kwargs):
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
        log = runner.run(config, {}, max_parallel=1)

    # Sequential fail-fast: only 2 steps executed
    assert log["status"] == "failed"
    assert len(log["steps"]) == 2
    assert log["steps"][0]["status"] == "completed"
    assert log["steps"][1]["status"] == "failed"
    assert "concurrency_info" not in log


# ---------------------------------------------------------------------------
# 8. Gate failure skips downstream
# ---------------------------------------------------------------------------

def test_gate_failure_skips_downstream_parallel(tmp_path: Path) -> None:
    """Gate failure in parallel mode causes downstream skip."""
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
        {
            "id": "downstream",
            "skill": "s",
            "command": "echo downstream",
            "output_dir": "o/downstream",
            "depends_on": ["gated"],
        },
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    gate_result_data = {"overall_pass": False, "gates_file": str(gate_file)}
    gate_json_path = tmp_path / "gated_gate_results.json"

    def mock_subprocess_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        if "quality-gate" in cmd:
            gate_json_path.write_text(json.dumps(gate_result_data))
        return result

    with patch("pipeline.subprocess.run", side_effect=mock_subprocess_run):
        runner = PipelineRunner(working_dir=tmp_path)
        log = runner.run(config, {}, max_parallel=3)

    assert log["status"] == "failed"
    status_map = {s["id"]: s["status"] for s in log["steps"]}
    assert status_map["gated"] == "gate_failed"
    assert status_map["downstream"] == "skipped"
    downstream_step = next(s for s in log["steps"] if s["id"] == "downstream")
    assert downstream_step["skipped_reason"] == "dependency gated failed"


# ---------------------------------------------------------------------------
# 9. Benchmark: parallel vs sequential timing
# ---------------------------------------------------------------------------

def test_benchmark_parallel_faster(tmp_path: Path) -> None:
    """Parallel execution is faster than sequential for independent steps."""
    steps = _three_parallel_steps()
    yaml_path = _write_pipeline_yaml(tmp_path, steps)

    sleep_sec = 0.1

    def mock_run_slow(cmd, **kwargs):
        step_id = cmd.split()[-1]
        if step_id != "resolve":
            time.sleep(sleep_sec)
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        return result

    # Sequential (max_parallel=1)
    config_seq = PipelineConfig.load(yaml_path)
    with patch("pipeline.subprocess.run", side_effect=mock_run_slow):
        runner = PipelineRunner()
        t0 = time.monotonic()
        log_seq = runner.run(config_seq, {}, max_parallel=1)
        seq_time = time.monotonic() - t0
    assert log_seq["status"] == "completed"

    # Parallel (max_parallel=3)
    config_par = PipelineConfig.load(yaml_path)
    with patch("pipeline.subprocess.run", side_effect=mock_run_slow):
        runner = PipelineRunner()
        t0 = time.monotonic()
        log_par = runner.run(config_par, {}, max_parallel=3)
        par_time = time.monotonic() - t0
    assert log_par["status"] == "completed"

    # Parallel should be meaningfully faster
    # Sequential: resolve + cj + c + wr = ~0.3s
    # Parallel:   resolve + max(cj, c, wr) = ~0.1s
    assert par_time < seq_time * 0.8, (
        f"Parallel ({par_time:.3f}s) not significantly faster than "
        f"sequential ({seq_time:.3f}s)"
    )


# ---------------------------------------------------------------------------
# 10. concurrency_info tracking
# ---------------------------------------------------------------------------

def test_concurrency_info_recorded(tmp_path: Path) -> None:
    """concurrency_info records the number of concurrent steps at start."""
    yaml_path = _write_pipeline_yaml(tmp_path, _diamond_steps())
    config = PipelineConfig.load(yaml_path)

    def mock_run(cmd, **kwargs):
        time.sleep(0.03)
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        return result

    with patch("pipeline.subprocess.run", side_effect=mock_run):
        runner = PipelineRunner()
        log = runner.run(config, {}, max_parallel=3)

    assert log["status"] == "completed"
    info = log["concurrency_info"]

    # root runs alone
    assert info["root"] == 1
    # left and right run in parallel
    assert info["left"] >= 1
    assert info["right"] >= 1
    assert info["left"] + info["right"] >= 3  # at least one should show 2


# ---------------------------------------------------------------------------
# 11. Step log ordering follows topological order
# ---------------------------------------------------------------------------

def test_log_topological_order(tmp_path: Path) -> None:
    """Pipeline log steps are in topological order regardless of finish order."""
    steps = [
        {"id": "A", "skill": "s", "command": "echo A", "output_dir": "o/A"},
        {"id": "B", "skill": "s", "command": "echo B", "output_dir": "o/B",
         "depends_on": ["A"]},
        {"id": "C", "skill": "s", "command": "echo C", "output_dir": "o/C",
         "depends_on": ["A"]},
        {"id": "D", "skill": "s", "command": "echo D", "output_dir": "o/D",
         "depends_on": ["B", "C"]},
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    def mock_run(cmd, **kwargs):
        step_id = cmd.split()[-1]
        # Make C finish before B
        if step_id == "C":
            time.sleep(0.01)
        elif step_id == "B":
            time.sleep(0.05)
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        return result

    with patch("pipeline.subprocess.run", side_effect=mock_run):
        runner = PipelineRunner()
        log = runner.run(config, {}, max_parallel=3)

    ids = [s["id"] for s in log["steps"]]
    assert ids.index("A") < ids.index("B")
    assert ids.index("A") < ids.index("C")
    assert ids.index("B") < ids.index("D")
    assert ids.index("C") < ids.index("D")


# ---------------------------------------------------------------------------
# 12. Full 12-step pipeline DAG (valuate/analyze_risk/inventory parallel)
# ---------------------------------------------------------------------------

def test_full_12step_dag_parallel(tmp_path: Path) -> None:
    """Full pipeline DAG: diamond pattern at valuate/analyze_risk/inventory."""
    steps = [
        {"id": "resolve", "skill": "s", "command": "echo resolve", "output_dir": "o/resolve"},
        {"id": "collect_jquants", "skill": "s", "command": "echo cj",
         "output_dir": "o/cj", "depends_on": ["resolve"]},
        {"id": "collect", "skill": "s", "command": "echo c",
         "output_dir": "o/c", "depends_on": ["resolve"]},
        {"id": "web_research", "skill": "s", "command": "echo wr",
         "output_dir": "o/wr", "depends_on": ["resolve"]},
        {"id": "parse", "skill": "s", "command": "echo parse",
         "output_dir": "o/parse", "depends_on": ["collect"]},
        {"id": "harmonize", "skill": "s", "command": "echo harm",
         "output_dir": "o/harm", "depends_on": ["web_research"]},
        {"id": "integrate", "skill": "s", "command": "echo int",
         "output_dir": "o/int", "depends_on": ["parse", "harmonize"]},
        {"id": "calculate", "skill": "s", "command": "echo calc",
         "output_dir": "o/calc", "depends_on": ["integrate"]},
        {"id": "valuate", "skill": "s", "command": "echo val",
         "output_dir": "o/val", "depends_on": ["calculate"]},
        {"id": "analyze_risk", "skill": "s", "command": "echo risk",
         "output_dir": "o/risk", "depends_on": ["calculate"]},
        {"id": "inventory", "skill": "s", "command": "echo inv",
         "output_dir": "o/inv", "depends_on": ["calculate"]},
        {"id": "report", "skill": "s", "command": "echo report",
         "output_dir": "o/report", "depends_on": ["valuate", "analyze_risk", "inventory"]},
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    def mock_run(cmd, **kwargs):
        time.sleep(0.02)
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = ""
        return result

    with patch("pipeline.subprocess.run", side_effect=mock_run):
        runner = PipelineRunner()
        log = runner.run(config, {}, max_parallel=3)

    assert log["status"] == "completed"
    assert len(log["steps"]) == 12

    # Verify ordering constraints
    ids = [s["id"] for s in log["steps"]]
    assert ids.index("resolve") < ids.index("collect")
    assert ids.index("resolve") < ids.index("collect_jquants")
    assert ids.index("resolve") < ids.index("web_research")
    assert ids.index("collect") < ids.index("parse")
    assert ids.index("web_research") < ids.index("harmonize")
    assert ids.index("parse") < ids.index("integrate")
    assert ids.index("harmonize") < ids.index("integrate")
    assert ids.index("calculate") < ids.index("valuate")
    assert ids.index("calculate") < ids.index("analyze_risk")
    assert ids.index("calculate") < ids.index("inventory")
    assert ids.index("valuate") < ids.index("report")
    assert ids.index("analyze_risk") < ids.index("report")
    assert ids.index("inventory") < ids.index("report")


# ---------------------------------------------------------------------------
# 13. StepLog skipped_reason field
# ---------------------------------------------------------------------------

def test_step_log_skipped_reason() -> None:
    """StepLog with skipped_reason includes it in to_dict()."""
    log = StepLog(id="x", skill="s", status="skipped",
                  skipped_reason="dependency y failed")
    d = log.to_dict()
    assert d["skipped_reason"] == "dependency y failed"
    assert d["status"] == "skipped"

    # Without skipped_reason, key is absent
    log2 = StepLog(id="y", skill="s", status="completed")
    d2 = log2.to_dict()
    assert "skipped_reason" not in d2


# ---------------------------------------------------------------------------
# 14. Default max_parallel in run() is 1 (backward compat)
# ---------------------------------------------------------------------------

def test_default_max_parallel_is_sequential(tmp_path: Path) -> None:
    """run() without max_parallel uses sequential mode (no concurrency_info)."""
    steps = [
        {"id": "s1", "skill": "s", "command": "echo 1", "output_dir": "o/1"},
    ]
    yaml_path = _write_pipeline_yaml(tmp_path, steps)
    config = PipelineConfig.load(yaml_path)

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    mock_result.stderr = ""

    with patch("pipeline.subprocess.run", return_value=mock_result):
        runner = PipelineRunner()
        log = runner.run(config, {})

    assert log["status"] == "completed"
    assert "concurrency_info" not in log
