# market-data-collector

J-Quants API から日次株価データ（daily_quotes）と上場銘柄情報（listed_info）を収集するスキル。

## Description

指定した銘柄コードに対して、以下を取得する。
- daily_quotes: 日次株価データ（始値・高値・安値・終値・出来高等）
- listed_info: 上場銘柄情報（銘柄名・業種・市場区分等）

## Usage

```bash
python3 skills/market-data-collector/scripts/main.py --ticker 7203
```

期間指定例:
```bash
python3 skills/market-data-collector/scripts/main.py \
  --ticker 7203 \
  --from-date 2025-01-01 \
  --to-date 2026-02-25
```

出力先指定:
```bash
python3 skills/market-data-collector/scripts/main.py \
  --ticker 7203 \
  --output-dir /tmp/market_data
```

## CLI Options

| Option | Required | Default | Description |
|---|---|---|---|
| `--ticker` | Yes | - | 銘柄コード（例: 7203） |
| `--from-date` | No | 1年前 | 開始日（YYYY-MM-DD） |
| `--to-date` | No | 今日 | 終了日（YYYY-MM-DD） |
| `--output-dir` | No | `data/{ticker}/raw/jquants` | 出力先ディレクトリ |

## Output

### ファイル
- `data/{ticker}/raw/jquants/market_data.json` — 日次株価データ
- `data/{ticker}/raw/jquants/listed_info.json` — 上場銘柄情報

### stdout
成功時、結果サマリを JSON で出力:
```json
{
  "ticker": "7203",
  "from_date": "2025-02-25",
  "to_date": "2026-02-25",
  "daily_quotes_count": 245,
  "listed_info_count": 1,
  "outputs": {
    "market_data": "data/7203/raw/jquants/market_data.json",
    "listed_info": "data/7203/raw/jquants/listed_info.json"
  }
}
```

### 終了コード
- `0`: 成功
- `1`: エラー（認証、API制限、銘柄未存在、期間不正、ファイルI/O）

## Environment Variables

- `JQUANTS_REFRESH_TOKEN` — J-Quants APIリフレッシュトークン（必須）
- `JQUANTS_EMAIL` — リフレッシュトークン自動更新用メール（任意）
- `JQUANTS_PASSWORD` — リフレッシュトークン自動更新用パスワード（任意）
- `DATA_PATH` — データ出力ルート（任意、省略時: リポジトリ内 `data/`）

## Dependencies

- `httpx` — HTTPクライアント
- `python-dotenv` — 環境変数読み込み
- `skills/disclosure-collector/scripts/auth.py` — JQuantsAuth（認証モジュール共有）

## Status

実装済み
