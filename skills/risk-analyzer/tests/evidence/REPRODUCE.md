# Evidence: risk-analyzer 再現手順

## テスト実行 + カバレッジ計測
```bash
cd /Users/fumitotakahashi/Dropbox/dev/bank
python3 -m pytest --cov=skills/risk-analyzer/scripts --cov-report=term-missing skills/risk-analyzer/tests/ -v
```

## サンプル分析実行（XBRL ZIP 直接）
```bash
cd /Users/fumitotakahashi/Dropbox/dev/bank
python3 skills/risk-analyzer/scripts/main.py analyze \
  --ticker 7203 \
  --input-dir skills/risk-analyzer/tests/evidence/ \
  --output /tmp/risk_output.json
```

## サンプル分析実行（disclosure-parser JSON 経由）
```bash
python3 skills/risk-analyzer/scripts/main.py analyze \
  --ticker 7203 \
  --parsed-json data/7203/parsed/financials.json \
  --output /tmp/risk_output.json
```

## ファイル一覧
- `pytest_coverage.log`: テスト44件全通過 + カバレッジ95%のログ
- `sample_input_S100SAMPLE.zip`: サンプルXBRL ZIP（5リスク項目）
- `sample_output.json`: 上記入力に対する構造化出力JSON
