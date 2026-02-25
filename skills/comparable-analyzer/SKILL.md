# comparable-analyzer

業種コードから比較企業群を自動選定し、財務指標ベンチマーク比較を行うスキル。

## Usage

```bash
python3 skills/comparable-analyzer/scripts/main.py --ticker 7203
python3 skills/comparable-analyzer/scripts/main.py --ticker 7203 --max-peers 5
python3 skills/comparable-analyzer/scripts/main.py --ticker 7203 --data-root /path/to/data
```

## CLI Options

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--ticker` | Yes | - | 4桁ティッカーコード |
| `--max-peers` | No | 10 | 最大比較企業数 |
| `--data-root` | No | `<repo_root>/data` | データルートパス |

## Output

`data/{ticker}/parsed/comparables.json` に以下の構造で出力:

- `schema_version`: `"comparable-analyzer-v1"`
- `target`: 対象企業の情報と指標 (ROE, ROA, operating_margin, revenue_growth)
- `peers`: 比較企業リスト（各社の指標と警告）
- `benchmarks`: 各指標の統計値（median, mean, std, q1, q3, target_percentile）
- `warnings`: 全体の警告メッセージ
- `peer_count` / `max_peers_requested`: 実際の比較企業数と要求数

## Environment Variables

| Variable | Description |
|----------|-------------|
| `DATA_PATH` | データルートパスの上書き（`--data-root` が優先） |

## Dependencies

- **ticker-resolver**: `data/.ticker_cache/EdinetcodeDlInfo.csv` を業種コード・企業名の参照に使用
- **financial-calculator**: `data/{ticker}/parsed/metrics.json` を指標データソースとして使用

## Processing Flow

1. EDINET CSV から対象ティッカーの業種コードを取得
2. 同業種の上場企業を抽出（対象自身を除外、最大 max_peers 社）
3. 各社の metrics.json から最新指標を取得
4. 指標比較マトリクスを構築
5. 四分位ランキング・統計値を算出
6. `comparables.json` に出力

## Status

- Version: 1.0
- Tests: `pytest skills/comparable-analyzer/tests/`
