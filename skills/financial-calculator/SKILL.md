# financial-calculator

正規化済み財務データから時系列指標を算出し、Markdown レポートを生成するスキル。

## Description

`disclosure-parser` の `financials.json` 等を読み込み、
収益性・成長性・安全性・CF 指標を算出して `metrics.json` を出力する。
必要に応じて簡易 Markdown レポートも生成する。

## Usage

### 指標算出
```bash
python3 skills/financial-calculator/scripts/main.py calculate --ticker 7203
```

### Markdown レポート生成
```bash
python3 skills/financial-calculator/scripts/main.py report --ticker 7203
```

明示指定例:
```bash
python3 skills/financial-calculator/scripts/main.py calculate \
  --ticker 7203 \
  --parsed-dir data/7203/parsed \
  --output data/7203/parsed/metrics.json

python3 skills/financial-calculator/scripts/main.py report \
  --ticker 7203 \
  --metrics data/7203/parsed/metrics.json \
  --output projects/7203/reports/report.md
```

## Calculated Metrics

- ROE
- ROA
- 営業利益率
- 売上成長率（YoY）
- 利益成長率（YoY）
- 自己資本比率
- 営業CF
- フリーキャッシュフロー

## Output

- `data/{ticker}/parsed/metrics.json`
- `projects/{ticker}/reports/report.md`（既定）

## Environment Variables

- `DATA_PATH`（任意）
- `PROJECTS_PATH`（任意）

## Status

実装済み
