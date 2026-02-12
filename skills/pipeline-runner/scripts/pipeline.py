"""Pipeline config loading, DAG validation, and execution engine."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import yaml


JST = timezone(timedelta(hours=9))

QUALITY_GATE_CMD = "python3 skills/quality-gate/scripts/main.py"


class PipelineError(Exception):
    """Pipeline configuration or execution error."""


@dataclass
class PipelineStep:
    id: str
    skill: str
    command: str
    output_dir: str
    depends_on: list[str] = field(default_factory=list)
    gates: str | None = None


@dataclass
class StepLog:
    id: str
    skill: str
    status: str = "pending"
    started_at: str | None = None
    completed_at: str | None = None
    duration_sec: float | None = None
    gate_result: dict | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "skill": self.skill,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_sec": self.duration_sec,
            "gate_result": self.gate_result,
            "error": self.error,
        }


class PipelineConfig:
    """Load and manage pipeline definition."""

    def __init__(self, name: str, description: str, steps: list[PipelineStep]) -> None:
        self.name = name
        self.description = description
        self.steps = steps
        self._step_map: dict[str, PipelineStep] = {s.id: s for s in steps}

    @classmethod
    def load(cls, path: str | Path) -> PipelineConfig:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        pipeline = raw.get("pipeline")
        if not isinstance(pipeline, dict):
            raise PipelineError("pipeline.yaml must have a top-level 'pipeline' key")

        name = pipeline.get("name", "unnamed")
        description = pipeline.get("description", "")
        raw_steps = pipeline.get("steps", [])

        if not isinstance(raw_steps, list) or len(raw_steps) == 0:
            raise PipelineError("pipeline must have at least one step")

        steps = []
        for s in raw_steps:
            if not isinstance(s, dict):
                raise PipelineError(f"step must be a dict, got {type(s)}")
            for required in ("id", "skill", "command", "output_dir"):
                if required not in s:
                    raise PipelineError(f"step missing required field: {required}")
            steps.append(
                PipelineStep(
                    id=s["id"],
                    skill=s["skill"],
                    command=s["command"],
                    output_dir=s["output_dir"],
                    depends_on=s.get("depends_on", []),
                    gates=s.get("gates"),
                )
            )

        return cls(name=name, description=description, steps=steps)

    def resolve_vars(self, vars_dict: dict[str, str]) -> None:
        for step in self.steps:
            # Resolve {prev_output} from first dependency
            prev_output = ""
            if step.depends_on:
                dep_id = step.depends_on[0]
                dep_step = self._step_map.get(dep_id)
                if dep_step:
                    prev_output = dep_step.output_dir

            all_vars = {**vars_dict, "prev_output": prev_output}
            for key, val in all_vars.items():
                placeholder = "{" + key + "}"
                step.command = step.command.replace(placeholder, val)
                step.output_dir = step.output_dir.replace(placeholder, val)

    def validate_dag(self) -> list[str]:
        """Validate DAG structure. Returns list of errors (empty if valid)."""
        errors = []
        ids = {s.id for s in self.steps}

        # Check for duplicate IDs
        if len(ids) != len(self.steps):
            seen = set()
            for s in self.steps:
                if s.id in seen:
                    errors.append(f"duplicate step id: {s.id}")
                seen.add(s.id)

        # Check for missing dependencies
        for s in self.steps:
            for dep in s.depends_on:
                if dep not in ids:
                    errors.append(f"step '{s.id}' depends on unknown step '{dep}'")

        # Check for cycles using DFS
        if not errors:
            visited: set[str] = set()
            in_stack: set[str] = set()

            def has_cycle(node: str) -> bool:
                if node in in_stack:
                    return True
                if node in visited:
                    return False
                visited.add(node)
                in_stack.add(node)
                step = self._step_map.get(node)
                if step:
                    for dep in step.depends_on:
                        if has_cycle(dep):
                            return True
                in_stack.discard(node)
                return False

            for s in self.steps:
                if has_cycle(s.id):
                    errors.append("cycle detected in step dependencies")
                    break

        return errors

    def execution_order(self) -> list[PipelineStep]:
        """Return steps in topological order (dependencies first)."""
        order: list[str] = []
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visited:
                return
            visited.add(node_id)
            step = self._step_map.get(node_id)
            if step:
                for dep in step.depends_on:
                    visit(dep)
            order.append(node_id)

        for s in self.steps:
            visit(s.id)

        return [self._step_map[sid] for sid in order]


class PipelineRunner:
    """Execute pipeline steps sequentially."""

    def __init__(self, working_dir: str | Path | None = None) -> None:
        self.working_dir = str(working_dir) if working_dir else None

    def run(self, config: PipelineConfig, vars_dict: dict[str, str],
            log_path: str | Path | None = None) -> dict[str, Any]:
        errors = config.validate_dag()
        if errors:
            raise PipelineError(f"DAG validation failed: {'; '.join(errors)}")

        config.resolve_vars(vars_dict)
        steps = config.execution_order()

        pipeline_log: dict[str, Any] = {
            "pipeline_name": config.name,
            "started_at": datetime.now(JST).isoformat(),
            "completed_at": None,
            "status": "running",
            "vars": vars_dict,
            "steps": [],
        }

        for step in steps:
            step_log = self._run_step(step)
            pipeline_log["steps"].append(step_log.to_dict())

            if step_log.status == "failed":
                pipeline_log["status"] = "failed"
                pipeline_log["completed_at"] = datetime.now(JST).isoformat()
                self._write_log(pipeline_log, log_path)
                return pipeline_log

            # Quality gate
            if step.gates and step_log.status == "completed":
                gate_log = self._run_gate(step)
                step_log_dict = pipeline_log["steps"][-1]
                step_log_dict["gate_result"] = gate_log

                if gate_log and not gate_log.get("overall_pass", True):
                    step_log_dict["status"] = "gate_failed"
                    pipeline_log["status"] = "gate_failed"
                    pipeline_log["completed_at"] = datetime.now(JST).isoformat()
                    self._write_log(pipeline_log, log_path)
                    return pipeline_log

        pipeline_log["status"] = "completed"
        pipeline_log["completed_at"] = datetime.now(JST).isoformat()
        self._write_log(pipeline_log, log_path)
        return pipeline_log

    def _run_step(self, step: PipelineStep) -> StepLog:
        log = StepLog(id=step.id, skill=step.skill)
        log.started_at = datetime.now(JST).isoformat()

        try:
            result = subprocess.run(
                step.command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=self.working_dir,
                timeout=600,
            )
            log.completed_at = datetime.now(JST).isoformat()
            started = datetime.fromisoformat(log.started_at)
            completed = datetime.fromisoformat(log.completed_at)
            log.duration_sec = round((completed - started).total_seconds(), 2)

            if result.returncode != 0:
                log.status = "failed"
                log.error = result.stderr.strip() or f"exit code {result.returncode}"
            else:
                log.status = "completed"
        except subprocess.TimeoutExpired:
            log.completed_at = datetime.now(JST).isoformat()
            log.status = "failed"
            log.error = "command timed out (600s)"
        except OSError as e:
            log.completed_at = datetime.now(JST).isoformat()
            log.status = "failed"
            log.error = str(e)

        return log

    def _run_gate(self, step: PipelineStep) -> dict | None:
        if not step.gates:
            return None

        output_file = f"{step.id}_gate_results.json"
        if self.working_dir:
            output_path = str(Path(self.working_dir) / output_file)
        else:
            output_path = output_file

        cmd = (
            f"{QUALITY_GATE_CMD} "
            f"--gates {step.gates} "
            f"--data-dir {step.output_dir} "
            f"--output {output_path}"
        )

        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                cwd=self.working_dir, timeout=120,
            )
            if Path(output_path).exists():
                with open(output_path, "r") as f:
                    return json.load(f)
            return {"overall_pass": result.returncode == 0, "gates_file": step.gates}
        except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
            return {"overall_pass": False, "gates_file": step.gates, "error": "gate execution failed"}

    @staticmethod
    def _write_log(log: dict, path: str | Path | None) -> None:
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(log, f, ensure_ascii=False, indent=2)


def format_status(log: dict) -> str:
    """Format pipeline log as human-readable status."""
    lines = [
        f"Pipeline: {log.get('pipeline_name', '?')}",
        f"Status: {log.get('status', '?')}",
        f"Started: {log.get('started_at', '?')}",
        f"Completed: {log.get('completed_at', '?')}",
        f"Vars: {log.get('vars', {})}",
        "",
        "Steps:",
    ]
    for s in log.get("steps", []):
        duration = f"{s['duration_sec']}s" if s.get("duration_sec") is not None else "?"
        gate = ""
        if s.get("gate_result"):
            gate_pass = s["gate_result"].get("overall_pass", "?")
            gate = f"  gate={'PASS' if gate_pass else 'FAIL'}"
        lines.append(f"  {s['id']}: {s['status']} ({duration}){gate}")
        if s.get("error"):
            lines.append(f"    error: {s['error']}")
    return "\n".join(lines)
