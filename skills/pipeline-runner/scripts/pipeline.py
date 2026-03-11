"""Pipeline config loading, DAG validation, and execution engine."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import yaml


JST = timezone(timedelta(hours=9))

QUALITY_GATE_CMD = "python3 skills/quality-gate/scripts/main.py"

# Known skill commands — used for validation and as documentation.
# Pipeline YAML steps reference these skill names; commands are inline in YAML.
SKILL_REGISTRY: dict[str, str] = {
    "ticker-resolver": (
        "python3 skills/ticker-resolver/scripts/main.py resolve {ticker}"
    ),
    "disclosure-collector": (
        "python3 skills/disclosure-collector/scripts/main.py"
    ),
    "disclosure-parser": (
        "python3 skills/disclosure-parser/scripts/main.py"
    ),
    "financial-integrator": (
        "python3 skills/financial-integrator/scripts/main.py"
        " --ticker {ticker} --fye-month {fye_month}"
        " --parsed-dir data/{ticker}/parsed"
        " --output data/{ticker}/integrated/integrated_financials.json"
    ),
    "financial-calculator": (
        "python3 skills/financial-calculator/scripts/main.py calculate"
        " --ticker {ticker} --parsed-dir data/{ticker}/parsed"
        " --output data/{ticker}/parsed/metrics.json"
    ),
    "valuation-calculator": (
        "python3 skills/valuation-calculator/scripts/main.py dcf"
        " --metrics data/{ticker}/parsed/metrics.json"
        " --output data/{ticker}/valuation/dcf.json"
    ),
    "risk-analyzer": (
        "python3 skills/risk-analyzer/scripts/main.py analyze"
        " --ticker {ticker} --input-dir data/{ticker}/raw/edinet"
        " --output data/{ticker}/risk/risk_analysis.json"
    ),
    "inventory-builder": (
        "python3 skills/inventory-builder/scripts/main.py"
        " --ticker {ticker} --fye-month {fye_month}"
    ),
    "financial-reporter": (
        "python3 skills/financial-reporter/scripts/main.py"
        " --ticker {ticker} --metrics data/{ticker}/parsed/metrics.json"
        " --output-md data/{ticker}/reports/{ticker}_report.md"
        " --output-html data/{ticker}/reports/{ticker}_report.html"
    ),
    "web-researcher": (
        "python3 skills/web-researcher/scripts/main.py collect"
        " --ticker {ticker} --source all"
        " --output data/{ticker}/web_research/research.json"
    ),
    "web-data-harmonizer": (
        "python3 skills/web-data-harmonizer/scripts/main.py harmonize"
        " --ticker {ticker} --source all"
        " --input data/{ticker}/web_research/research.json"
        " --output data/{ticker}/harmonized/harmonized_financials.json"
    ),
}


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
    output_vars: dict[str, str] = field(default_factory=dict)


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
    skipped_reason: str | None = None

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "skill": self.skill,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_sec": self.duration_sec,
            "gate_result": self.gate_result,
            "error": self.error,
        }
        if self.skipped_reason is not None:
            d["skipped_reason"] = self.skipped_reason
        return d


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
                    output_vars=s.get("output_vars") or {},
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

    def _resolve_step(self, step: PipelineStep, vars_dict: dict[str, str]) -> None:
        """Resolve placeholders in a single step's command and output_dir."""
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

    def validate_vars(self, vars_dict: dict[str, str],
                      from_step: str | None = None,
                      exec_set: set[str] | None = None) -> None:
        """Validate that all placeholders can be resolved at execution time.

        If exec_set is provided, only validate and count output_vars for
        steps in the execution set (skipped steps are ignored).
        """
        placeholder_re = re.compile(r"\{(\w+)\}")
        steps = self.execution_order()
        available_output_vars: set[str] = set()

        for step in steps:
            in_scope = exec_set is None or step.id in exec_set

            available = set(vars_dict.keys())
            available.add("prev_output")
            available.update(available_output_vars)

            if in_scope:
                placeholders = set(placeholder_re.findall(step.command))
                placeholders.update(placeholder_re.findall(step.output_dir))

                for name in placeholders:
                    if name not in available:
                        if from_step:
                            raise PipelineError(
                                f"--from-step {from_step} requires variable "
                                f"'{name}'. Provide via --vars or --log with "
                                f"a previous run log."
                            )
                        raise PipelineError(
                            f"変数 '{name}' が未定義です。"
                            f"--vars {name}=VALUE で指定するか、"
                            f"output_vars を持つ先行ステップを追加してください"
                        )

            if in_scope:
                for key in step.output_vars:
                    available_output_vars.add(key)

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

        # Check for isolated nodes: nodes with no depends_on AND not depended
        # upon by any other step.  Legitimate roots are depended upon by at
        # least one downstream step; a truly isolated node is disconnected.
        referenced = {dep for s in self.steps for dep in s.depends_on}
        for s in self.steps:
            if not s.depends_on and s.id not in referenced and len(ids) > 1:
                errors.append(f"isolated node: '{s.id}' has no dependencies and is not depended upon")

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
    """Execute pipeline steps with optional parallelism."""

    def __init__(self, working_dir: str | Path | None = None) -> None:
        if working_dir:
            self.working_dir = str(working_dir)
        else:
            self.working_dir = str(Path(__file__).resolve().parent.parent.parent.parent)

    def run(self, config: PipelineConfig, vars_dict: dict[str, str],
            log_path: str | Path | None = None,
            max_parallel: int = 1,
            from_step: str | None = None,
            prev_runtime_vars: dict[str, str] | None = None) -> dict[str, Any]:
        sys.stderr.write(f"[pipeline] working_dir={self.working_dir}\n")
        errors = config.validate_dag()
        if errors:
            raise PipelineError(f"DAG validation failed: {'; '.join(errors)}")

        exec_set: set[str] | None = None

        if from_step:
            if from_step not in config._step_map:
                raise PipelineError(
                    f"--from-step '{from_step}' is not a valid step. "
                    f"Available steps: {', '.join(s.id for s in config.steps)}"
                )

            exec_set = self._compute_exec_set(config, from_step)

            # Build effective vars for validation and output_dir checks
            effective_vars = dict(prev_runtime_vars or {})
            effective_vars.update(vars_dict)

            # Validate diamond DAG sibling dependencies
            self._validate_sibling_deps(config, exec_set, from_step,
                                        effective_vars)

            # Validate output_dirs for skipped steps
            resolved_dirs: dict[str, str] = {}
            for step in config.execution_order():
                prev_output = ""
                if step.depends_on:
                    dep_id = step.depends_on[0]
                    if dep_id in resolved_dirs:
                        prev_output = resolved_dirs[dep_id]
                resolved_dir = step.output_dir
                all_vars = {**effective_vars, "prev_output": prev_output}
                for k, v in all_vars.items():
                    resolved_dir = resolved_dir.replace("{" + k + "}", v)
                resolved_dirs[step.id] = resolved_dir

                if step.id not in exec_set:
                    output_path = Path(self.working_dir) / resolved_dir
                    if not output_path.exists():
                        raise PipelineError(
                            f"--from-step: skipped step '{step.id}' output dir "
                            f"'{resolved_dir}' does not exist. "
                            f"Run the full pipeline first."
                        )

            config.validate_vars(effective_vars, from_step=from_step,
                                exec_set=exec_set)
        else:
            config.validate_vars(vars_dict)

        if max_parallel <= 1:
            return self._run_sequential(config, vars_dict, log_path,
                                        exec_set=exec_set,
                                        prev_runtime_vars=prev_runtime_vars)
        return self._run_parallel(config, vars_dict, log_path, max_parallel,
                                  exec_set=exec_set,
                                  prev_runtime_vars=prev_runtime_vars)

    @staticmethod
    def _compute_exec_set(config: PipelineConfig, from_step: str) -> set[str]:
        """Compute the set of steps to execute: from_step + transitive dependents."""
        dependents: dict[str, list[str]] = {s.id: [] for s in config.steps}
        for step in config.steps:
            for dep in step.depends_on:
                dependents[dep].append(step.id)

        exec_set = {from_step}
        queue = [from_step]
        while queue:
            sid = queue.pop(0)
            for dep_id in dependents.get(sid, []):
                if dep_id not in exec_set:
                    exec_set.add(dep_id)
                    queue.append(dep_id)
        return exec_set

    @staticmethod
    def _ancestors(config: PipelineConfig, step_id: str) -> set[str]:
        """Return all ancestor step IDs (transitive dependencies) of step_id."""
        step_map = {s.id: s for s in config.steps}
        visited: set[str] = set()
        queue = list(step_map[step_id].depends_on)
        while queue:
            sid = queue.pop(0)
            if sid not in visited:
                visited.add(sid)
                queue.extend(step_map[sid].depends_on)
        return visited

    @staticmethod
    def _find_missing_siblings(
        config: PipelineConfig, exec_set: set[str], from_step: str,
    ) -> dict[str, list[str]]:
        """Find diamond DAG siblings: deps of exec_set steps not in exec_set
        and not ancestors of from_step (i.e., parallel branches, not upstream).

        Returns a mapping of step_id -> list of missing sibling IDs.
        """
        ancestors = PipelineRunner._ancestors(config, from_step)
        step_map = {s.id: s for s in config.steps}
        missing: dict[str, list[str]] = {}
        for sid in exec_set:
            step = step_map[sid]
            for dep in step.depends_on:
                if dep not in exec_set and dep not in ancestors:
                    missing.setdefault(sid, []).append(dep)
        return missing

    def _validate_sibling_deps(
        self,
        config: PipelineConfig,
        exec_set: set[str],
        from_step: str,
        effective_vars: dict[str, str],
    ) -> None:
        """Validate diamond DAG siblings: deps of exec_set steps not in exec_set.

        If missing siblings have no output_dir on disk, raise PipelineError
        with the list of missing siblings and a recommended --from-step.
        """
        missing = self._find_missing_siblings(config, exec_set, from_step)
        if not missing:
            return

        step_map = {s.id: s for s in config.steps}
        all_missing_ids: set[str] = set()
        for deps in missing.values():
            all_missing_ids.update(deps)

        # Check which missing siblings lack output_dir on disk
        missing_no_output: list[str] = []
        for mid in sorted(all_missing_ids):
            step = step_map[mid]
            resolved_dir = step.output_dir
            for k, v in effective_vars.items():
                resolved_dir = resolved_dir.replace("{" + k + "}", v)
            output_path = Path(self.working_dir) / resolved_dir
            if not output_path.exists():
                missing_no_output.append(mid)

        if not missing_no_output:
            return

        # Find recommended --from-step: common parent of from_step + siblings
        from_step_obj = step_map[from_step]
        from_deps = set(from_step_obj.depends_on)
        sibling_deps: set[str] = set()
        for mid in all_missing_ids:
            sibling_deps.update(step_map[mid].depends_on)
        common = from_deps & sibling_deps
        if common:
            recommended = sorted(common)[0]
        else:
            # Fallback: suggest the first missing sibling's parent
            first_missing = sorted(all_missing_ids)[0]
            parents = step_map[first_missing].depends_on
            recommended = parents[0] if parents else from_step

        # Build error listing which exec_set steps need the missing siblings
        affected = [
            f"  '{sid}' depends on: {deps}"
            for sid, deps in sorted(missing.items())
        ]
        raise PipelineError(
            f"--from-step='{from_step}': diamond DAG has missing sibling steps "
            f"without prior output: {missing_no_output}\n"
            + "\n".join(affected) + "\n"
            f"These steps are not in the exec set but are required dependencies.\n"
            f"Recommended: --from-step='{recommended}' "
            f"(includes all sibling branches)"
        )

    def _run_sequential(self, config: PipelineConfig, vars_dict: dict[str, str],
                        log_path: str | Path | None,
                        exec_set: set[str] | None = None,
                        prev_runtime_vars: dict[str, str] | None = None) -> dict[str, Any]:
        """Sequential execution (original fail-fast behavior)."""
        steps = config.execution_order()
        runtime_vars = dict(vars_dict)
        if prev_runtime_vars:
            for k, v in prev_runtime_vars.items():
                if k not in vars_dict:
                    runtime_vars[k] = v

        pipeline_log: dict[str, Any] = {
            "pipeline_name": config.name,
            "started_at": datetime.now(JST).isoformat(),
            "completed_at": None,
            "status": "running",
            "vars": vars_dict,
            "runtime_vars": {},
            "steps": [],
        }

        def _snapshot_rv() -> None:
            pipeline_log["runtime_vars"] = {
                k: v for k, v in runtime_vars.items() if k not in vars_dict
            }

        for step in steps:
            if exec_set is not None and step.id not in exec_set:
                skip_log = StepLog(
                    id=step.id, skill=step.skill, status="skipped",
                    skipped_reason="upstream of from-step",
                )
                pipeline_log["steps"].append(skip_log.to_dict())
                continue

            config._resolve_step(step, runtime_vars)
            step_log, stdout = self._run_step(step)
            pipeline_log["steps"].append(step_log.to_dict())

            if step_log.status == "failed":
                pipeline_log["status"] = "failed"
                pipeline_log["completed_at"] = datetime.now(JST).isoformat()
                _snapshot_rv()
                self._write_log(pipeline_log, log_path)
                return pipeline_log

            if step.output_vars and step_log.status == "completed":
                self._process_output_vars(step, stdout, runtime_vars, vars_dict)

            if step.gates and step_log.status == "completed":
                gate_log = self._run_gate(step, ticker=runtime_vars.get("ticker"))
                step_log_dict = pipeline_log["steps"][-1]
                step_log_dict["gate_result"] = gate_log

                if gate_log and not gate_log.get("overall_pass", True):
                    step_log_dict["status"] = "gate_failed"
                    pipeline_log["status"] = "gate_failed"
                    pipeline_log["completed_at"] = datetime.now(JST).isoformat()
                    _snapshot_rv()
                    self._write_log(pipeline_log, log_path)
                    return pipeline_log

        pipeline_log["status"] = "completed"
        pipeline_log["completed_at"] = datetime.now(JST).isoformat()
        _snapshot_rv()
        self._write_log(pipeline_log, log_path)
        return pipeline_log

    def _run_parallel(self, config: PipelineConfig, vars_dict: dict[str, str],
                      log_path: str | Path | None,
                      max_parallel: int,
                      exec_set: set[str] | None = None,
                      prev_runtime_vars: dict[str, str] | None = None) -> dict[str, Any]:
        """Parallel execution with dependency-based scheduling."""
        runtime_vars = dict(vars_dict)
        if prev_runtime_vars:
            for k, v in prev_runtime_vars.items():
                if k not in vars_dict:
                    runtime_vars[k] = v
        step_map = config._step_map

        # Build reverse dependency map
        dependents: dict[str, list[str]] = {s.id: [] for s in config.steps}
        for step in config.steps:
            for dep in step.depends_on:
                dependents[dep].append(step.id)

        # State tracking (main thread only, except active_count)
        finished: dict[str, str] = {}  # step_id -> status
        step_results: dict[str, dict] = {}
        concurrency_info: dict[str, int] = {}

        active_lock = threading.Lock()
        active_count = 0

        pipeline_log: dict[str, Any] = {
            "pipeline_name": config.name,
            "started_at": datetime.now(JST).isoformat(),
            "completed_at": None,
            "status": "running",
            "vars": vars_dict,
            "runtime_vars": {},
            "steps": [],
            "concurrency_info": {},
        }

        # Pre-register skipped steps for from_step
        if exec_set is not None:
            for step in config.steps:
                if step.id not in exec_set:
                    finished[step.id] = "completed"
                    step_results[step.id] = StepLog(
                        id=step.id, skill=step.skill, status="skipped",
                        skipped_reason="upstream of from-step",
                    ).to_dict()

        def mark_downstream_skipped(failed_id: str) -> None:
            """BFS to mark all transitive dependents as skipped."""
            queue = list(dependents[failed_id])
            while queue:
                sid = queue.pop(0)
                if sid in finished:
                    continue
                finished[sid] = "skipped"
                step_results[sid] = StepLog(
                    id=sid, skill=step_map[sid].skill,
                    status="skipped",
                    skipped_reason=f"dependency {failed_id} failed",
                ).to_dict()
                queue.extend(dependents[sid])

        def execute_step(step: PipelineStep) -> tuple:
            nonlocal active_count
            with active_lock:
                active_count += 1
                concurrency = active_count
            try:
                step_log, stdout = self._run_step(step)
                gate_log = None
                if step.gates and step_log.status == "completed":
                    gate_log = self._run_gate(step, ticker=runtime_vars.get("ticker"))
                    if gate_log and not gate_log.get("overall_pass", True):
                        step_log.status = "gate_failed"
                return step.id, step_log, stdout, gate_log, concurrency
            finally:
                with active_lock:
                    active_count -= 1

        submitted: set[str] = set()

        with ThreadPoolExecutor(max_workers=max_parallel) as executor:
            futures: dict = {}

            while len(finished) < len(config.steps):
                # Find and submit ready steps (main thread only)
                for step in config.steps:
                    if step.id in finished or step.id in submitted:
                        continue
                    if all(d in finished for d in step.depends_on):
                        if all(finished.get(d) == "completed"
                               for d in step.depends_on):
                            config._resolve_step(step, runtime_vars)
                            future = executor.submit(execute_step, step)
                            futures[future] = step.id
                            submitted.add(step.id)

                if not futures:
                    break

                done, _ = wait(set(futures.keys()),
                               return_when=FIRST_COMPLETED)

                for f in done:
                    futures.pop(f)
                    step_id, step_log, stdout, gate_log, concurrency = \
                        f.result()

                    step_dict = step_log.to_dict()
                    if gate_log:
                        step_dict["gate_result"] = gate_log

                    step_results[step_id] = step_dict
                    concurrency_info[step_id] = concurrency

                    if step_log.status in ("failed", "gate_failed"):
                        finished[step_id] = step_log.status
                        mark_downstream_skipped(step_id)
                    else:
                        finished[step_id] = "completed"
                        step = step_map[step_id]
                        if step.output_vars:
                            for var_name in step.output_vars:
                                if (var_name in runtime_vars
                                        and var_name not in vars_dict):
                                    raise PipelineError(
                                        f"output_var conflict: '{var_name}' "
                                        f"already set by another step"
                                    )
                            self._process_output_vars(
                                step, stdout, runtime_vars, vars_dict
                            )

        # Build final log in topological order
        for step in config.execution_order():
            if step.id in step_results:
                pipeline_log["steps"].append(step_results[step.id])

        pipeline_log["concurrency_info"] = concurrency_info
        pipeline_log["runtime_vars"] = {
            k: v for k, v in runtime_vars.items() if k not in vars_dict
        }
        has_failure = any(v != "completed" for v in finished.values())
        pipeline_log["status"] = "failed" if has_failure else "completed"
        pipeline_log["completed_at"] = datetime.now(JST).isoformat()
        self._write_log(pipeline_log, log_path)
        return pipeline_log

    def _run_step(self, step: PipelineStep) -> tuple[StepLog, str]:
        log = StepLog(id=step.id, skill=step.skill)
        log.started_at = datetime.now(JST).isoformat()
        stdout = ""

        try:
            env = os.environ.copy()
            project_root = self.working_dir
            existing = env.get("PYTHONPATH", "")
            if existing:
                env["PYTHONPATH"] = project_root + os.pathsep + existing
            else:
                env["PYTHONPATH"] = project_root

            result = subprocess.run(
                step.command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=self.working_dir,
                timeout=600,
                env=env,
            )
            log.completed_at = datetime.now(JST).isoformat()
            started = datetime.fromisoformat(log.started_at)
            completed = datetime.fromisoformat(log.completed_at)
            log.duration_sec = round((completed - started).total_seconds(), 2)

            if result.stderr:
                sys.stderr.write(result.stderr)

            stdout = result.stdout

            if result.returncode != 0:
                log.status = "failed"
                log.error = result.stderr if result.stderr else f"Step failed with exit code {result.returncode}"
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

        return log, stdout

    def _process_output_vars(
        self,
        step: PipelineStep,
        stdout: str,
        runtime_vars: dict[str, str],
        user_vars: dict[str, str],
    ) -> None:
        """Parse stdout JSON and extract output_vars into runtime_vars."""
        try:
            data = json.loads(stdout)
        except (json.JSONDecodeError, ValueError):
            raise PipelineError(
                f"Step '{step.id}' output_vars: stdout is not valid JSON: {stdout[:200]}"
            )

        if not isinstance(data, dict):
            raise PipelineError(
                f"Step '{step.id}' output_vars expects JSON object (dict), "
                f"got {type(data).__name__}"
            )

        for var_name, json_key in step.output_vars.items():
            if json_key not in data:
                raise PipelineError(
                    f"Step '{step.id}' output_vars key '{json_key}' not found in stdout JSON"
                )
            if var_name not in user_vars:
                runtime_vars[var_name] = str(data[json_key])

    def _run_gate(self, step: PipelineStep, ticker: str | None = None) -> dict | None:
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
        if ticker:
            cmd += f" --ticker {ticker}"

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
        if s.get("skipped_reason"):
            lines.append(f"    skipped_reason: {s['skipped_reason']}")
    return "\n".join(lines)
