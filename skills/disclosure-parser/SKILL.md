# disclosure-parser

EDINET XBRL（zip）またはPDF有価証券報告書を解析し、比較可能な共通スキーマの BS/PL/CF JSON を生成するスキル。

## Description

### XBRL モード（デフォルト）
`disclosure-collector` が保存した `data/{ticker}/raw/edinet/*.zip` を入力に、
科目名ゆれを正規化して時系列比較しやすい JSON を出力する。

### PDF モード
有価証券報告書のPDFファイルを入力に、multi-strategy pdfplumber でテーブルを抽出し、
日本語科目名を正規化キーにマッピングして同一スキーマの JSON を出力する。

## Usage

### XBRL モード
```bash
python3 skills/disclosure-parser/scripts/main.py --ticker 7203
```

入力・出力を明示する場合:
```bash
python3 skills/disclosure-parser/scripts/main.py \
  --ticker 7203 \
  --input-dir data/7203/raw/edinet \
  --output-dir data/7203/parsed
```

### PDF モード
```bash
# --pdf フラグで明示指定
python3 skills/disclosure-parser/scripts/main.py \
  --ticker 2780 \
  --input-dir data/2780/raw/edinet/shihanki_hokokusho/ \
  --output-dir data/2780/parsed/ \
  --pdf

# 自動判別（ディレクトリに .pdf のみの場合は自動的にPDFモード）
python3 skills/disclosure-parser/scripts/main.py \
  --ticker 2780 \
  --input-dir data/2780/raw/edinet/shihanki_hokokusho/ \
  --output-dir data/2780/parsed/
```

### CLI オプション
| オプション | 説明 |
|---|---|
| `--ticker` / `--code` | 証券コード（必須） |
| `--input-dir` | 入力ディレクトリ（省略時: `data/{ticker}/raw/edinet`） |
| `--output-dir` | 出力ディレクトリ（省略時: `data/{ticker}/parsed`） |
| `--pdf` | PDF解析モードを強制（省略時: ファイル拡張子で自動判別） |

## Output

- `{output-dir}/{docID}.json` — 各期の個別JSON
- `{output-dir}/financials.json` — 全期間統合JSON

PDFモードでは各期の個別JSONに `pdf_metadata` フィールドが追加される:
| フィールド | 説明 |
|---|---|
| `source_pdf` | 入力PDFファイル名 |
| `extraction_pages` | BS/PL/CF が抽出されたページ番号リスト |
| `parser_version` | pdf_parser.py のバージョン |
| `extraction_method` | `pdfplumber_table` |
| `unit_detected` | 検出された単位表記（百万円/千円/円） |
| `unit_multiplier` | 適用した単位乗数 |
| `strategy_used` | 選択された table_settings 戦略（S1/S2/S3/text_fallback） |
| `concept_score` | 認識できた財務科目数の合計 |

## PDF 解析仕様

### Multi-strategy pdfplumber + concept-scored selection
単一の table_settings ではなく、3つの戦略を試行し、認識できた財務科目数で最適戦略を自動選択する。

| 戦略 | vertical_strategy | horizontal_strategy | 用途 |
|---|---|---|---|
| S1 | lines | lines | 明確な罫線を持つPDF |
| S2 | text | text | 罫線がないPDF（snap_tolerance=5, join_tolerance=5） |
| S3 | text | lines | 水平罫線のみのPDF |

選択アルゴリズム: `(期間数, concept_score)` タプルの降順ソート。期間数が多い戦略を優先し、同数ならconcept_scoreで選択。全戦略で concept_score=0 の場合のみテキストベースフォールバックを使用。テーブル抽出後も不足する科目はテキストから補完する。

### 日本語科目名エイリアス（PDF_CONCEPT_ALIASES）
| 正規化キー | 日本語科目名 |
|---|---|
| `total_assets` | 資産合計, 総資産, 総資産額 |
| `current_assets` | 流動資産合計 |
| `total_liabilities` | 負債合計, 負債の部合計 |
| `current_liabilities` | 流動負債合計 |
| `total_equity` / `net_assets` | 純資産合計, 純資産の部合計 |
| `revenue` | 売上高, 営業収益 |
| `gross_profit` | 売上総利益 |
| `operating_income` | 営業利益 |
| `ordinary_income` | 経常利益 |
| `net_income` | 親会社株主に帰属する当期純利益, 当期純利益, 当期純損失 |
| `operating_cf` | 営業活動によるキャッシュ・フロー |
| `investing_cf` | 投資活動によるキャッシュ・フロー |
| `financing_cf` | 財務活動によるキャッシュ・フロー |

### 単位変換
PDFテーブル近傍のテキストから単位を検出し、全値を円に統一して出力する。

| 検出パターン | 乗数 |
|---|---|
| （単位：百万円）, （百万円） | 1,000,000 |
| （単位：千円）, （千円） | 1,000 |
| （単位：円）, （円） | 1 |

未検出時のデフォルトは百万円。

### 負号正規化
| 入力パターン | 出力 |
|---|---|
| △123, ▲123 | -123 |
| （123）, (123) | -123 |
| -123, －123 | -123 |
| 空文字, -, ―, — | null |

## Notes

- 欠損項目は `null` を保持
- 主要科目の alias 正規化を実施
- `DATA_PATH` 環境変数を参照可能
- PDF/XBRL混在ディレクトリでは `--pdf` フラグで明示指定が必要

## Tests

```bash
# 全テスト実行
python3 -m pytest skills/disclosure-parser/tests/ -v

# XBRLパーサーテストのみ
python3 -m pytest skills/disclosure-parser/tests/test_parser.py -v

# PDFパーサーテストのみ
python3 -m pytest skills/disclosure-parser/tests/test_pdf_parser.py -v
```

## Status

実装済み（XBRL + PDF対応）
