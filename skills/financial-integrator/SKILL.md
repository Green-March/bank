# financial-integrator

EDINET パーサー出力と J-Quants 決算データを統合し、銘柄非依存の時系列財務 JSON を生成するスキル。

## Description

`disclosure-parser` が生成した `financials.json` と J-Quants API の
`jquants_fins_statements.json` を入力に、EDINET 優先・J-Quants 補完の
マージロジックで `integrated_financials.json` を出力する。

通期/四半期の分類は決算月 (`fye_month`) から動的に判定するため、
3月決算・12月決算などすべての決算月に対応する。

## Usage

```bash
python3 skills/financial-integrator/scripts/main.py \
  --ticker 2780 --fye-month 3
```

入力・出力を明示する場合:
```bash
python3 skills/financial-integrator/scripts/main.py \
  --ticker 7203 \
  --fye-month 3 \
  --parsed-dir data/7203/parsed \
  --output data/7203/parsed/integrated_financials.json \
  --company-name "トヨタ自動車"
```

## CLI Options

| オプション | 必須 | 説明 |
|---|---|---|
| `--ticker` | Yes | 銘柄コード（例: 2780） |
| `--fye-month` | Yes | 決算月（例: 3, 12） |
| `--parsed-dir` | No | 入力ディレクトリ（省略時: `data/{ticker}/parsed`） |
| `--output` | No | 出力JSONパス（省略時: `data/{ticker}/parsed/integrated_financials.json`） |
| `--company-name` | No | 会社名（省略時: ticker を使用） |

`DATA_PATH` 環境変数でデータルートを変更可能。

## Output

`integrated_financials.json`:

```json
{
  "ticker": "2780",
  "company_name": "...",
  "fiscal_year_end_month": 3,
  "integration_metadata": {
    "generated_at": "...",
    "input_files": { "edinet": {...}, "jquants": {...} },
    "coverage_summary": { "FY2024": {...} },
    "source_priority_rules": { "FY2024": "..." }
  },
  "coverage_matrix": [...],
  "annual": [...],
  "quarterly": [...]
}
```

各エントリには `bs`, `pl`, `cf` セクションが含まれ、`source` フィールドで
データソース (`edinet`, `jquants`, `both`) を識別できる。

## Notes

- J-Quants ファイルが存在しない場合は Warning を出力し、EDINET のみで統合する（エラーにしない）
- 通期判定: `period_end.month == fye_month` かつ期間長 > 300日
- 四半期マッピングは `fye_month` から動的生成（例: fye_month=3 → Q1=6月, Q2=9月, Q3=12月, FY=3月）
- EDINET 優先、J-Quants で null フィールドを補完
- `source_priority_rules` は coverage データから自動生成（銘柄固有テキストなし）
- 銘柄固有ハードコードなし

## Tests

```bash
python3 -m pytest skills/financial-integrator/tests/ -v
```

## Status

実装済み
