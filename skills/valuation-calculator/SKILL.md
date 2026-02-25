# valuation-calculator

DCF（割引キャッシュフロー）と相対バリュエーション（PER/PBR/EV-EBITDA同業比較）を計算しJSONで出力する。

## Description

- financial-calculator が出力する `metrics.json` を入力として、企業価値評価を実施
- DCF: FCF系列 → 将来FCF予測 → ターミナルバリュー → 企業価値・株主価値・1株あたり価値
- 相対バリュエーション: PER・PBR・EV/EBITDA を算出し、同業他社との比較を実施

## Usage

### DCF

```bash
# 基本
python3 skills/valuation-calculator/scripts/main.py dcf \
  --metrics data/9743/parsed/metrics.json

# パラメータ指定
python3 skills/valuation-calculator/scripts/main.py dcf \
  --metrics data/9743/parsed/metrics.json \
  --wacc 0.10 \
  --growth-rate 0.03 \
  --projection-years 10 \
  --shares 50000000 \
  --output data/9743/valuation/dcf.json
```

### 相対バリュエーション

```bash
# 単独
python3 skills/valuation-calculator/scripts/main.py relative \
  --metrics data/9743/parsed/metrics.json

# 同業比較
python3 skills/valuation-calculator/scripts/main.py relative \
  --metrics data/9743/parsed/metrics.json \
  --peers data/4680/parsed/metrics.json data/2327/parsed/metrics.json \
  --output data/9743/valuation/relative.json
```

## CLI オプション

### dcf サブコマンド

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--metrics` | Yes | - | financial-calculator の metrics.json パス |
| `--wacc` | No | 0.08 | 加重平均資本コスト |
| `--growth-rate` | No | 0.02 | 永久成長率 |
| `--projection-years` | No | 5 | FCF予測期間（年） |
| `--shares` | No | - | 発行済株式数（1株あたり価値算出用） |
| `--output` | No | - | 出力JSONファイルパス（未指定時はstdoutのみ） |

### relative サブコマンド

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--metrics` | Yes | - | 対象銘柄の metrics.json パス |
| `--peers` | No | - | 同業他社の metrics.json パス群（スペース区切り） |
| `--output` | No | - | 出力JSONファイルパス（未指定時はstdoutのみ） |

## Output

### DCF 出力

```json
{
  "ticker": "9743",
  "valuation_type": "dcf",
  "enterprise_value": 25000000000,
  "equity_value": 20000000000,
  "per_share_value": 400.0,
  "assumptions": {
    "wacc": 0.08,
    "terminal_growth_rate": 0.02,
    "projection_years": 5,
    "base_fcf": 1500000000,
    "estimated_growth_rate": 0.05,
    "net_debt": 5000000000,
    "shares_outstanding": 50000000
  }
}
```

### 相対バリュエーション出力（同業比較あり）

```json
{
  "ticker": "9743",
  "valuation_type": "relative",
  "target": {"ticker": "9743", "per": 10.0, "pbr": 1.67, "ev_ebitda": 6.88},
  "peers": [
    {"ticker": "4680", "per": 8.0, "pbr": 1.6, "ev_ebitda": 5.5},
    {"ticker": "2327", "per": 15.0, "pbr": 3.0, "ev_ebitda": 9.2}
  ],
  "comparison": {
    "per": {"target": 10.0, "peer_median": 11.5, "peer_average": 11.5, "vs_median": -1.5, "vs_average": -1.5},
    "pbr": {"target": 1.67, "peer_median": 2.3, "peer_average": 2.3, "vs_median": -0.63, "vs_average": -0.63},
    "ev_ebitda": {"target": 6.88, "peer_median": 7.35, "peer_average": 7.35, "vs_median": -0.47, "vs_average": -0.47}
  }
}
```

## 入力フォーマット

financial-calculator の `metrics.json` を入力とする。必須フィールド:

- DCF: `metrics_series[].free_cash_flow`
- 相対バリュエーション: `latest_snapshot.{market_cap, net_income, equity, operating_income, total_debt, cash_and_equivalents}`

## データ補完フォールバック仕様

相対バリュエーション計算時、`latest_snapshot` のフィールドが欠損している場合の補完ルール:

| 優先度 | ソース | 対象フィールド | 備考 |
|--------|--------|---------------|------|
| 1 | `latest_snapshot` 直接値 | market_cap, net_income, equity | market_data_collector が `listed_info.json` / `market_data.json` から統合した値が格納される場合はこれを使用 |
| 2 | `metrics_series` 最新年度 | market_cap, net_income, equity | 決算期末時点の値であり、market_data_collector のリアルタイム時価総額と乖離する可能性あり |
| 3 | 近似計算 | EBITDA | `snapshot.ebitda` → `operating_income + depreciation` の順 |
| - | 補完不可 | - | いずれにも値がない場合は `null` を返し計算をスキップ |

### market_data_collector との整合

- market_data_collector が `data/{ticker}/market/market_data.json` に時価総額を出力している場合、financial-calculator が `latest_snapshot.market_cap` に統合済みであることを前提とする。
- financial-calculator が market_cap を統合していない場合（EDINET/XBRL のみのパイプライン等）、`metrics_series` の決算期末時価総額にフォールバックする。この場合、出力の `data_sources.market_cap` が `metrics_series[YYYY]` となり、リアルタイム値ではないことが追跡可能。
- いずれのソースにも market_cap がない場合は PER/PBR/EV-EBITDA すべて `null` を返す。

### 再現コマンド

```bash
# テスト全件実行
python3 -m pytest skills/valuation-calculator/tests/test_valuation.py -v

# カバレッジ計測
python3 -m pytest --cov=skills/valuation-calculator/scripts --cov-report=term-missing skills/valuation-calculator/tests/
```

## Status

実装済み
