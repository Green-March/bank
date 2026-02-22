---
name: quality-gate
description: >-
  Validate financial data deliverables against acceptance gates.
  This skill should be used when automated quality checks are needed
  before passing parsed financial data to downstream analysis or review.
  It reads a gates definition YAML and data directory, then outputs
  PASS/FAIL judgments as a structured JSON report.
---

# Quality Gate

Validate parsed financial data against configurable acceptance gates and
produce a machine-readable gate_results.json report.

## Purpose

Reduce mechanical checking burden on reviewers by automating data quality
verification. Run this skill after disclosure-parser produces financials.json
and before metrics calculation or report drafting begins.

## Usage

```bash
python3 skills/quality-gate/scripts/main.py \
  --gates <gates.yaml> \
  --data-dir <dir> \
  --output <gate_results.json>
```

### CLI Options

| Option | Required | Description |
|---|---|---|
| `--gates` | Yes | Path to gates definition YAML file |
| `--data-dir` | Yes | Directory containing financials.json and other data files |
| `--output` | No | Output path for gate_results.json (default: stdout) |

### Example

```bash
python3 skills/quality-gate/scripts/main.py \
  --gates skills/quality-gate/references/default_gates.yaml \
  --data-dir data/2780/parsed/ \
  --output data/2780/parsed/gate_results.json
```

## Gates Definition YAML

Each gate has an `id`, `type`, and `params`. See `references/default_gates.yaml`
for a ready-to-use template.

### Supported Gate Types

#### null_rate

Check that the overall null rate across all BS/PL/CF concepts and periods
stays below a threshold.

```yaml
- id: null_rate
  type: null_rate
  params:
    threshold: 0.5   # max allowed null fraction (0.0-1.0)
```

#### key_coverage

Check that required keys have non-null values across all periods.
Each section (bs, pl, cf) specifies keys and a minimum count that must
be non-null in every period.

```yaml
- id: key_coverage
  type: key_coverage
  params:
    bs:
      keys: [total_assets, total_liabilities, total_equity]
      min_required: 2
    pl:
      keys: [revenue, operating_income, net_income]
      min_required: 2
```

#### value_range

Detect anomalous values by enforcing min/max bounds on specific concepts.

```yaml
- id: value_range
  type: value_range
  params:
    total_assets:
      min: 0
    revenue:
      min: 0
      max: 1000000000000000
```

#### file_exists

Verify that required files exist and are non-empty in the data directory.

```yaml
- id: file_check
  type: file_exists
  params:
    required_files:
      - "financials.json"
```

#### json_schema

Verify that required top-level keys exist in financials.json.

```yaml
- id: schema_check
  type: json_schema
  params:
    required_keys:
      - "company_name"
      - "ticker"
      - "period_index"
```

## Output Format

gate_results.json structure:

```json
{
  "timestamp": "2026-02-12T...",
  "gates_file": "path/to/gates.yaml",
  "data_dir": "path/to/data",
  "overall_pass": true,
  "gates": [
    {"id": "key_coverage", "pass": true, "detail": {...}},
    {"id": "null_rate", "pass": true, "detail": {"total_cells": 165, "null_cells": 11, "null_rate": 0.067, "threshold": 0.5}},
    {"id": "value_range", "pass": true, "detail": {"violations": [], "violation_count": 0}},
    {"id": "file_check", "pass": true, "detail": {"financials.json": {"exists": true, "size": 12345}}}
  ]
}
```

Exit code: 0 if overall_pass is true, 1 otherwise.

## Scripts

- `scripts/main.py` — CLI entrypoint. Loads gates YAML, calls validators, writes JSON output.
- `scripts/validators.py` — Validation functions and result dataclasses.

## Dependencies

- Python 3.10+
- pyyaml (only external dependency)
