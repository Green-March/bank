# financial-reporter

財務指標データ（metrics.json）から Markdown / HTML の分析レポートを生成するスキル。

## 概要

`financial-calculator` が出力した `metrics.json` を入力として、
投資判断に必要な要点（最新スナップショット、時系列推移、リスク）を
Markdown と HTML の2形式で出力する。

**CLI メッセージ・エラー出力はすべて日本語。**
レポート本文（見出し・ラベル等）は render.py が制御する。

## 使い方

```bash
python3 skills/financial-reporter/scripts/main.py --ticker 7203
```

入力・出力を明示する場合:

```bash
python3 skills/financial-reporter/scripts/main.py \
  --ticker 7203 \
  --metrics data/7203/parsed/metrics.json \
  --output-md data/7203/reports/7203_report.md \
  --output-html data/7203/reports/7203_report.html
```

数値フォーマットと reconciliation パスを指定する場合:

```bash
python3 skills/financial-reporter/scripts/main.py \
  --ticker 7685 \
  --number-format man_yen \
  --reconciliation data/7685/qa/source_reconciliation.json
```

## CLI オプション

| オプション | デフォルト | 説明 |
|---|---|---|
| `--ticker` | (必須) | 銘柄コード (例: 7203) |
| `--metrics` | auto | 入力 metrics.json パス (省略時: `data/{ticker}/processed/metrics.json` または `parsed/`) |
| `--output-md` | auto | Markdown 出力先パス |
| `--output-html` | auto | HTML 出力先パス |
| `--number-format` | `raw` | 数値表示形式: `raw` (デフォルト・生数値), `man_yen` (百万円), `oku_yen` (億円) |
| `--reconciliation` | auto | source_reconciliation.json パス (省略時は自動検出) |

## 出力

- Markdown: `data/{ticker}/reports/{ticker}_report.md`
- HTML: `data/{ticker}/reports/{ticker}_report.html`

### CLI 出力例

正常終了時:
```
Markdown 出力: data/7203/reports/7203_report.md
HTML 出力: data/7203/reports/7203_report.html
```

エラー時:
```
metrics.json が見つかりません: data/7203/parsed/metrics.json
metrics データの読み込みに失敗しました: Expecting value: line 1 column 1 (char 0)
不正な metrics データ形式です
```

## 機能

### confirmed_absent スキーマ

`source_reconciliation.json` の `t1_judgment: "confirmed_absent"` と連携し、
null 値の表示理由を区別する:

- `N/A` — 未収集 (データ未取得)
- `—†` — 確認済み不在 (開示資料に該当データが存在しないことを確認済み)

レポート末尾に **データ品質に関する注記** セクションを自動生成し、
確認済み不在の period_end / field / reason を一覧表示する。

### 決算月の自動推定

`source_reconciliation.json` の `jquants_period_type: "FY"` エントリから
決算月を自動推定し、期間マッチングに使用する (`infer_fy_end_month`)。
推定不能な場合は 12月決算をデフォルトとする。

対応例:
- 12月決算: FY2024 = 2024-01-01 … 2024-12-31
- 3月決算: FY2024 = 2023-04-01 … 2024-03-31
- 6月決算: FY2025 = 2024-07-01 … 2025-06-30

### 数値フォーマット切替

`--number-format` は **金額フィールド (monetary)** のみに適用される。
**比率フィールド (ratio)** は常に `value:.2f` + suffix で表示され、
`--number-format` の影響を受けない。

#### フィールド分類 (`_MONETARY_FIELDS`)

| 分類 | フィールド名 | `--number-format` 適用 |
|---|---|---|
| 金額 | `revenue` | あり |
| 金額 | `operating_income` | あり |
| 金額 | `net_income` | あり |
| 金額 | `free_cash_flow` | あり |
| 比率 | `roe_percent` | **なし** (常に `.2f%`) |
| 比率 | `roa_percent` | **なし** (常に `.2f%`) |
| 比率 | `operating_margin_percent` | **なし** (常に `.2f%`) |
| 比率 | `equity_ratio_percent` | **なし** (常に `.2f%`) |

#### 表示例

| `--number-format` | 金額 (revenue=59,973,669,000) | 比率 (ROE=19.30) |
|---|---|---|
| `raw` | `59973669000.00` | `19.30%` |
| `man_yen` | `59,974 (百万円)` | `19.30%` |
| `oku_yen` | `599.7 (億円)` | `19.30%` |

## 含まれるスクリプト

- `scripts/main.py` - CLI エントリポイント (メッセージ日本語化済み、HTML タイトルは `{ticker} 分析レポート`)
- `scripts/render.py` - Markdown/HTML レンダラー (`build_absence_map`, `render_markdown`, `render_html`)

## 依存パッケージ

- jinja2
- markdown
- python-dotenv

## ステータス

実装済み
