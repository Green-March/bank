# web-data-harmonizer

web-researcher の出力 JSON をパイプライン互換スキーマ（financial-calculator / financial-integrator 接続可能）に変換するスキル。

## 概要

web-researcher が収集したソース別フラット構造データ（文字列混在・期間情報なし）を、
BANK パイプラインが要求する数値型 + 期間情報 + source_attribution 付きの統一スキーマに正規化する。

| ソース | 変換元 | 主な変換内容 |
|---|---|---|
| yahoo | `sources.yahoo.data` | 財務数値の型変換・期間情報付与 |
| kabutan | `sources.kabutan.data` | 業績データの正規化・単位統一 |
| shikiho | `sources.shikiho.data` | 業績予想・コンセンサスの構造化 |

## Usage

```bash
# 全ソースから変換
python skills/web-data-harmonizer/scripts/main.py harmonize --ticker 2780

# 特定ソースのみ
python skills/web-data-harmonizer/scripts/main.py harmonize --ticker 2780 --source yahoo

# 複数ソース指定（カンマ区切り）
python skills/web-data-harmonizer/scripts/main.py harmonize --ticker 2780 --source yahoo,kabutan

# 入力・出力パスを指定
python skills/web-data-harmonizer/scripts/main.py harmonize --ticker 2780 --input /tmp/research.json --output /tmp/harmonized.json
```

## CLI Options

| オプション | 説明 |
|---|---|
| `harmonize` | サブコマンド（必須） |
| `--ticker` | 銘柄コード4桁（必須、例: 2780） |
| `--source` | ソース指定: `all` / `yahoo` / `kabutan` / `shikiho` / カンマ区切り（デフォルト: `all`） |
| `--input` | web-researcher 出力 JSON パス（デフォルト: `data/{ticker}/web_research/research.json`） |
| `--output` | 出力パス（デフォルト: `data/{ticker}/harmonized/harmonized_financials.json`） |

## Output

`data/{ticker}/harmonized/harmonized_financials.json`

## Output Schema

```json
{
  "ticker": "2780",
  "company_name": "コメ兵ホールディングス",
  "generated_at": "2026-02-26T12:00:00+09:00",
  "harmonization_metadata": {
    "input_sources": ["yahoo", "kabutan", "shikiho"],
    "sources_used": ["yahoo", "kabutan", "shikiho"],
    "source_priority": ["kabutan", "yahoo", "shikiho"]
  },
  "annual": [
    {
      "period_end": "2024-03-31",
      "fiscal_year": 2024,
      "quarter": "FY",
      "source": "web:yahoo,web:kabutan",
      "statement_type": null,
      "bs": {
        "total_assets": null,
        "current_assets": null,
        "noncurrent_assets": null,
        "total_liabilities": null,
        "current_liabilities": null,
        "noncurrent_liabilities": null,
        "total_equity": null,
        "net_assets": null
      },
      "pl": {
        "revenue": 180000.0,
        "operating_income": 12000.0,
        "ordinary_income": 11500.0,
        "net_income": 7800.0,
        "gross_profit": null
      },
      "cf": {
        "operating_cf": null,
        "investing_cf": null,
        "financing_cf": null,
        "free_cash_flow": null
      }
    }
  ],
  "indicators": {
    "per": 15.0,
    "pbr": 1.7,
    "dividend_yield": 2.2,
    "shares_outstanding": null
  },
  "qualitative": {
    "company_overview": { "name": "コメ兵ホールディングス" },
    "consensus": {},
    "earnings_flash": {},
    "ir_links": []
  }
}
```

### annual エントリ構造

各エントリは `bs` / `pl` / `cf` のサブオブジェクトに分離され、全数値は `float | int | null` 型。
同一 `period_end` のデータは複数ソースからマージされ、`source` フィールドにカンマ区切りで帰属を記録する。

### エラー規約

| 状況 | 動作 |
|---|---|
| 入力ファイル不在 | stderr にエラーメッセージ + return 1 |
| JSON パースエラー | stderr にエラーメッセージ + return 1 |
| `--source` に無効値 | stderr にエラーメッセージ + return 1（有効値: `all`, `yahoo`, `kabutan`, `shikiho`） |

## Tests

```bash
pytest skills/web-data-harmonizer/tests/ -v
pytest skills/web-data-harmonizer/tests/ --cov=scripts --cov-report=term-missing
```

## Status

実装済み
