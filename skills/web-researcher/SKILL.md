# web-researcher

Web 上の企業情報を複数ソース（Yahoo ファイナンス、株探、四季報オンライン、企業公式サイト）から収集するスキル。

## 概要

銘柄コードを指定すると、最大4つの Web ソースから企業情報を並列的に収集し、統一 JSON に集約する。
各コレクターは robots.txt 準拠・ドメインホワイトリスト・レートリミットを共通基盤で遵守する。

| ソース | ドメイン | 認証 | 主な収集データ |
|---|---|---|---|
| yahoo | finance.yahoo.co.jp | 不要 | 株価・財務・指標・ニュース |
| kabutan | kabutan.jp | 不要 | 株価・業績・指標・決算速報・ニュース |
| shikiho | shikiho.toyokeizai.net | 要（メール/パスワード） | 会社概要・業績予想・コンセンサス・株主・指標 |
| homepage | 企業公式HP（EDINET経由） | 不要 | 会社情報・IRページ・IRリンク・ニュース |

## Usage

```bash
# 全ソースから収集
python skills/web-researcher/scripts/main.py collect --ticker 7203

# 特定ソースのみ
python skills/web-researcher/scripts/main.py collect --ticker 7203 --source yahoo

# 複数ソース指定（カンマ区切り）
python skills/web-researcher/scripts/main.py collect --ticker 7203 --source yahoo,kabutan

# 出力先を指定
python skills/web-researcher/scripts/main.py collect --ticker 7203 --output /tmp/research.json

# 既存JSONの該当ソースのみ上書きマージ
python skills/web-researcher/scripts/main.py collect --ticker 7203 --source kabutan --merge
```

## CLI Options

| オプション | 説明 |
|---|---|
| `collect` | サブコマンド（必須） |
| `--ticker` | 銘柄コード4桁（必須、例: 7203） |
| `--source` | ソース指定: `all` / `yahoo` / `kabutan` / `shikiho` / `homepage` / カンマ区切り（デフォルト: `all`） |
| `--output` | 出力先パス（デフォルト: `data/{ticker}/web_research/research.json`） |
| `--merge` | 既存 JSON の該当 source のみ上書きマージ |

## Output

`data/{ticker}/web_research/research.json`

```json
{
  "ticker": "7203",
  "company_name": null,
  "collected_at": "2026-02-26T12:00:00+09:00",
  "sources": {
    "yahoo": {
      "url": "https://finance.yahoo.co.jp/quote/7203",
      "collected": true,
      "data": { "stock_price": {}, "financials": [], "indicators": {}, "news": [] },
      "error": null
    },
    "kabutan": { "url": "...", "collected": true, "data": {}, "error": null },
    "shikiho": { "url": "...", "collected": true, "data": {}, "error": null },
    "homepage": { "url": "...", "collected": true, "data": {}, "error": null }
  },
  "metadata": {
    "source_count": 4,
    "success_count": 4,
    "errors": [],
    "accessed_domains": ["finance.yahoo.co.jp", "kabutan.jp"],
    "robots_checked": true
  }
}
```

各ソースの `data` 構造:

| ソース | data キー |
|---|---|
| yahoo | `stock_price`, `financials`, `indicators`, `news` |
| kabutan | `stock_price`, `financials`, `indicators`, `earnings_flash`, `news` |
| shikiho | `company_overview`, `earnings_forecast`, `consensus`, `shareholders`, `indicators` |
| homepage | `company_info`, `ir_page`, `ir_links`, `news` |

## Environment Variables

| 変数 | 説明 |
|---|---|
| `DATA_PATH` | データルートパス（デフォルト: `./data`） |
| `SHIKIHO_EMAIL` | 四季報オンライン有料会員メールアドレス（shikiho ソース用） |
| `SHIKIHO_PASSWORD` | 四季報オンライン有料会員パスワード（shikiho ソース用） |

## Configuration

`references/default_config.yaml`:

| 設定 | デフォルト | 説明 |
|---|---|---|
| `request_interval_seconds` | 2 | リクエスト間隔（秒） |
| `max_retries` | 3 | リトライ回数 |
| `backoff_base_seconds` | 2 | 指数バックオフ基底（秒） |
| `backoff_max_seconds` | 30 | バックオフ上限（秒） |
| `user_agent` | BANK-WebResearcher/1.0 | User-Agent ヘッダ |
| `timeout_seconds` | 30 | HTTP タイムアウト（秒） |
| `allowed_domains` | 3ドメイン | 静的ホワイトリスト |

## Tests

```bash
pytest skills/web-researcher/tests/ -v
pytest skills/web-researcher/tests/ --cov=scripts --cov-report=term-missing
```

## Status

実装済み
