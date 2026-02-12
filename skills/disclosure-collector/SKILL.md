# disclosure-collector

EDINET API と J-Quants API から日本株の開示・決算データを収集するスキル。

## Description

指定した銘柄コード/EDINETコードに対して、以下を取得する。
- J-Quants: 決算短信データ（構造化）
- EDINET: 有価証券報告書等の XBRL zip

取得データは `DATA_PATH`（既定: `./data`）配下へ保存する。

## Usage

### J-Quants 収集
```bash
python3 skills/disclosure-collector/scripts/main.py jquants 7203
```

### EDINET 収集
```bash
python3 skills/disclosure-collector/scripts/main.py edinet E02144 --ticker 7203
```

期間指定例:
```bash
python3 skills/disclosure-collector/scripts/main.py edinet E02144 \
  --ticker 7203 \
  --start-date 2020-01-01 \
  --end-date 2025-12-31
```

## Environment Variables

- `JQUANTS_REFRESH_TOKEN`
- `EDINET_API_KEY`（または `EDINET_SUBSCRIPTION_KEY`）
- `DATA_PATH`（任意）

## Output

- `data/{ticker}/raw/jquants/statements_YYYY-MM-DD.json`
- `data/{ticker}/raw/edinet/{docID}.zip`
- `data/{ticker}/raw/edinet/manifest.json`

## Status

実装済み
