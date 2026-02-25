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
| Any `{key}` | Expanded from `--vars key=value` or `output_vars` |

### output_vars — ステップ間変数伝搬

ステップの stdout JSON から値を抽出し、後続ステップのプレースホルダーに自動供給する。

```yaml
steps:
  - id: resolve
    skill: ticker-resolver
    command: "python3 skills/ticker-resolver/scripts/main.py resolve {ticker}"
    output_dir: "data/{ticker}/resolved"
    output_vars:
      fye_month: fye_month
      edinet_code: edinet_code
      company_name: company_name
  - id: integrate
    skill: financial-integrator
    command: "... --fye-month {fye_month} ..."
    depends_on: [resolve]
```

`output_vars` のキーはランタイム変数名、値は stdout JSON のキー名。
上記の例では resolve ステップが `{"fye_month": 3, "edinet_code": "E12345", ...}` を stdout に出力すると、
後続ステップの `{fye_month}` が `3` に、`{edinet_code}` が `E12345` に自動展開される。

**優先度ルール**: `--vars` で指定された値は output_vars より常に優先される。
例: `--vars fye_month=6` を指定すると、resolve の output_vars で得た fye_month は無視される。

**エラー仕様**:

| 状況 | 挙動 |
|---|---|
| stdout が有効な JSON でない | `PipelineError`: "stdout is not valid JSON" |
| JSON が dict 以外 (list, int, str) | `PipelineError`: "expects JSON object (dict), got {type}" |
| 指定したキーが JSON に存在しない | `PipelineError`: "key '{key}' not found in stdout JSON" |
| stderr 出力がある場合 | stderr は sys.stderr に転送される（output_vars 処理には影響しない） |

**バリデーション** (`validate_vars`):
パイプライン実行前に、全ステップのプレースホルダーが `--vars` または先行ステップの `output_vars` で
解決可能かを静的にチェックする。未解決の変数があれば実行前に `PipelineError` を発生させる。

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
