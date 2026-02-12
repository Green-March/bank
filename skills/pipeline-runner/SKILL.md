---
name: pipeline-runner
description: >-
  Execute multi-step skill pipelines defined as a DAG in YAML.
  This skill should be used when orchestrating sequential or dependent
  skill executions (e.g. collect → parse → calculate → report),
  with optional quality-gate validation after each step.
---

# Pipeline Runner

Execute multi-step skill pipelines defined as a DAG in pipeline.yaml,
with variable expansion and optional quality-gate integration.

## Purpose

Automate end-to-end analysis workflows by chaining skills in a declarative
pipeline definition. Each step specifies a command, output directory, dependencies,
and optional quality gates. The runner resolves the DAG, executes steps in
topological order, and produces a structured execution log.

## Usage

### run — Execute a pipeline

```bash
python3 skills/pipeline-runner/scripts/main.py run \
  --pipeline <pipeline.yaml> \
  --vars ticker=2780,edinet_code=E03416 \
  [--log <pipeline_log.json>]
```

Reads the pipeline definition, expands variables, validates the DAG,
and executes steps in dependency order. Writes an execution log on completion.

### validate — Validate a pipeline definition

```bash
python3 skills/pipeline-runner/scripts/main.py validate \
  --pipeline <pipeline.yaml>
```

Checks YAML syntax, required fields, and DAG acyclicity without executing anything.
Exit code 0 if valid, 1 if errors found.

### status — Show execution status

```bash
python3 skills/pipeline-runner/scripts/main.py status \
  --log <pipeline_log.json>
```

Displays progress from a previous execution log.

## Pipeline Definition Format

```yaml
pipeline:
  name: "disclosure_analysis"
  description: "収集→パース→指標計算→レポート生成"
  steps:
    - id: collect
      skill: disclosure-collector
      command: "python3 skills/disclosure-collector/scripts/main.py edinet {edinet_code} --ticker {ticker}"
      output_dir: "data/{ticker}/raw/edinet"
      gates: null
    - id: parse
      skill: disclosure-parser
      command: "python3 skills/disclosure-parser/scripts/main.py --ticker {ticker} --input-dir {prev_output} --output-dir data/{ticker}/parsed"
      output_dir: "data/{ticker}/parsed"
      depends_on: [collect]
      gates: "skills/quality-gate/references/default_gates.yaml"
```

### Variable Expansion

| Variable | Description |
|---|---|
| `{ticker}` | Ticker code from `--vars` |
| `{edinet_code}` | EDINET code from `--vars` |
| `{prev_output}` | output_dir of the first dependency step |
| Any `{key}` | Expanded from `--vars key=value` |

### Quality Gate Integration

When a step specifies `gates: <path>`, the runner automatically invokes:

```bash
python3 skills/quality-gate/scripts/main.py \
  --gates <gates_path> \
  --data-dir <step_output_dir> \
  --output <step_id>_gate_results.json
```

If the gate fails (exit code != 0), the pipeline stops at that step.

## Execution Log Format

```json
{
  "pipeline_name": "disclosure_analysis",
  "started_at": "2026-02-12T...",
  "completed_at": "2026-02-12T...",
  "status": "completed",
  "vars": {"ticker": "2780"},
  "steps": [
    {
      "id": "collect",
      "skill": "disclosure-collector",
      "status": "completed",
      "started_at": "...",
      "completed_at": "...",
      "duration_sec": 12.3,
      "gate_result": null,
      "error": null
    }
  ]
}
```

## Scripts

- `scripts/main.py` — CLI entrypoint with run/validate/status subcommands.
- `scripts/pipeline.py` — Pipeline config loading, DAG validation, and execution engine.

## References

- `references/example_pipeline.yaml` — Disclosure analysis pipeline definition example.

## Dependencies

- Python 3.10+
- pyyaml (only external dependency)
- subprocess (standard library)
