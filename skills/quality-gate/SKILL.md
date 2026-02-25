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

#### dir_not_empty

Check that the data directory exists and contains at least one file.
動的なファイル名を出力するステップ（collect, collect_jquants, report）向け。
`file_exists` はファイル名を事前に特定できるステップに使い、ファイル名が実行時に
決まるステップにはこのゲートを使う。

- **閾値**: ファイル数 >= 1（ディレクトリに1個以上のファイルが存在すること）
- **失敗条件**: ディレクトリが存在しない、またはディレクトリが空の場合 FAIL
- **失敗時の挙動**: pipeline-runner はステップを `gate_failed` にしてパイプライン全体を即時停止。後続ステップは実行されない
- **既存出力との差分**: 新規追加タイプ。既存の `file_exists` / `value_range` 等の出力構造とは独立。出力 JSON の detail は `{"exists": bool, "file_count": int}` 形式

```yaml
- id: collect_output
  type: dir_not_empty
  # params は不要
```

#### metrics_value_range

metrics.json の `latest_snapshot` から指標値（ROE, ROA 等）を読み込み、
指定範囲に収まっているか検証する。`value_range` が financials.json の
期間データ（BS/PL/CF）を対象とするのに対し、このタイプは financial-calculator
が出力する metrics.json の算出済み指標を対象とする。

- **閾値**: ゲート YAML の `params` で各指標に `min` / `max` を指定。推奨デフォルト値:
  - `roe_percent`: min=-100, max=200
  - `roa_percent`: min=-50, max=100
  - `operating_margin_percent`: min=-100, max=100
  - `equity_ratio_percent`: min=0, max=100
- **失敗条件**: いずれかの指標値が min 未満または max 超過の場合 FAIL。null 値はスキップ（violation にカウントしない）。metrics.json が存在しない場合も FAIL
- **失敗時の挙動**: pipeline-runner はステップを `gate_failed` にしてパイプライン全体を即時停止
- **既存出力との差分**: 新規追加タイプ。`value_range` と同様に violations リストを返すが、データソースが financials.json ではなく metrics.json である点が異なる。出力 JSON の detail は `{"violations": [...], "violation_count": int, "metrics_file": str, "checked_keys": [str]}` 形式

```yaml
- id: metrics_range
  type: metrics_value_range
  params:
    roe_percent:
      min: -100
      max: 200
    roa_percent:
      min: -50
      max: 100
```

## Pipeline Integration

quality-gate は pipeline-runner から自動実行される。
`example_pipeline.yaml` の各ステップに `gates` フィールドでゲート YAML を指定すると、
ステップ成功後に自動で quality-gate が呼ばれ、FAIL 時はパイプライン全体が停止する。

### ゲート失敗時の挙動

1. ステップのコマンドが正常終了（exit code 0）した後にゲートが実行される
2. ゲートが FAIL を返した場合:
   - 該当ステップの status が `gate_failed` になる
   - パイプライン全体の status が `gate_failed` になる
   - **後続ステップは一切実行されない**（即時停止）
   - 実行ログ（pipeline_run.json）にゲート結果の詳細が記録される
3. ゲートが PASS を返した場合のみ、次のステップへ進む

### ステップ別ゲート設定（references/）

| Step | Gate YAML | Gate Types | 目的 |
|---|---|---|---|
| resolve | `gates_resolve.yaml` | file_exists | resolver 出力ファイルの存在確認 |
| collect | `gates_collect.yaml` | dir_not_empty | EDINET 収集結果の存在確認 |
| collect_jquants | `gates_collect_jquants.yaml` | dir_not_empty | J-Quants 収集結果の存在確認 |
| parse | `gates_parse.yaml` | file_exists + key_coverage + null_rate | financials.json の品質検証 |
| integrate | `gates_integrate.yaml` | file_exists | 統合ファイルの存在確認 |
| calculate | `gates_calculate.yaml` | file_exists + metrics_value_range | metrics.json の存在と値域検証 |
| inventory | `gates_inventory.yaml` | file_exists | inventory.md の存在確認 |
| report | `gates_report.yaml` | dir_not_empty | レポートファイルの存在確認 |

### resolve ステップのコマンド変更

resolve ステップはもともと stdout に JSON を出力するのみで、ファイルを生成しなかった。
ゲート検証を可能にするため、コマンドを以下のように変更:

```
mkdir -p data/{ticker}/resolved && \
  python3 ... resolve {ticker} > data/{ticker}/resolved/resolve_result.json && \
  cat data/{ticker}/resolved/resolve_result.json
```

- `mkdir -p`: 出力ディレクトリを事前作成
- `> resolve_result.json`: stdout をファイルに保存
- `cat`: ファイル内容を再度 stdout へ出力し output_vars の動作を維持
- resolver が失敗した場合は `&&` チェーンにより後続の cat は実行されず、非ゼロ exit code がそのまま返る

**既存挙動への影響**: output_vars による変数キャプチャは cat 経由で従来通り動作する。
パイプラインの実行結果・出力に差異はなく、`data/{ticker}/resolved/resolve_result.json` が
副産物として追加されるのみ。

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
