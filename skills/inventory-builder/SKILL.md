# inventory-builder

data/{ticker} の収集・パース済みデータから inventory.md を自動生成するスキル。

## Description

`disclosure-collector` と `disclosure-parser` で取得・正規化したデータを走査し、
データの収集状況・品質・分析可能範囲をまとめた inventory.md を出力する。

## Usage

```bash
python3 skills/inventory-builder/scripts/main.py --ticker 2780 --fye-month 3
```

明示指定例:
```bash
python3 skills/inventory-builder/scripts/main.py \
  --ticker 2780 \
  --fye-month 3 \
  --data-root data \
  --output-path data/2780/inventory.md
```

## Arguments

| Argument | Required | Description |
|---|---|---|
| `--ticker` | Yes | 銘柄コード（例: 2780） |
| `--fye-month` | Yes | 決算月 1-12（例: 3月決算なら 3） |
| `--data-root` | No | データルートディレクトリ（デフォルト: 自動検出） |
| `--output-path` | No | 出力パス（デフォルト: data/{ticker}/inventory.md） |

## Input Files

実データ構成に基づく入力ファイル:

- `data/{ticker}/logs/manifest.json` — 収集メタデータ（取得日時・ソース・件数）
- `data/{ticker}/parsed/financials.json` — 正規化済み財務データ
- `data/{ticker}/parsed/jquants_fins_statements.json` — J-Quants 財務諸表（パース済み）
- `data/{ticker}/raw/edinet/` — EDINET 生データ（documents_*.json）
- `data/{ticker}/raw/jquants/` — J-Quants 生データ

## Output

- `data/{ticker}/inventory.md`

## Output Sections

inventory.md には以下のセクションが含まれる:

- **(a) 収集概要** — データソースごとの取得状況サマリ
- **(b) EDINET 開示一覧** — 取得済み書類の docID・種別・提出日
- **(c) J-Quants データ概要** — statements 取得期間・件数
- **(d) パース結果** — financials.json の期数・フィールド充足率
- **(e) 時系列カバレッジ** — 利用可能な決算期の一覧
- **(f) データ品質** — 欠損フィールド・整合性チェック結果
- **(g) 分析可能範囲** — 算出可能な指標と制約条件
- **(h) 推奨事項** — 追加収集・再パースの提案

## Dependencies

- `disclosure-collector` — データ収集（EDINET / J-Quants）
- `disclosure-parser` — XBRL 正規化

## Prerequisites

`disclosure-collector` と `disclosure-parser` が実行済みであること。
対象銘柄の `data/{ticker}/` 配下に `raw/` および `parsed/` ディレクトリが存在する必要がある。

## Error Handling

- `builder.py` 未配備時: 明示的な ImportError メッセージで停止
- `data/{ticker}/` 未存在時: エラーメッセージで停止
- `--fye-month` 範囲外（1-12 以外）: argparse が拒否

## Environment Variables

- `DATA_PATH`（任意） — データルートディレクトリの上書き指定

## Status

実装中
