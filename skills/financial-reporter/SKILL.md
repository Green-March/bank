# financial-reporter

財務指標データ（metrics.json）から Markdown / HTML の分析レポートを生成するスキル。

## Description

`financial-calculator` が出力した `metrics.json` を入力として、
投資判断に必要な要点（最新スナップショット、時系列推移、リスク）を
Markdown と HTML の2形式で出力する。

## Usage

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

## Output

- Markdown: `data/{ticker}/reports/{ticker}_report.md`
- HTML: `data/{ticker}/reports/{ticker}_report.html`

## Included Scripts

- `scripts/main.py` - CLI entrypoint
- `scripts/render.py` - markdown/html renderer

## Dependencies

- jinja2
- markdown
- python-dotenv

## Status

実装済み
