# risk-analyzer

有価証券報告書の定性テキスト（事業等のリスク）を抽出・分類し、リスクカテゴリ別に構造化JSONで出力する。

## Usage

```bash
# XBRL ZIP ファイルから直接抽出
python3 scripts/main.py analyze --ticker 7203 --input-dir data/7203/raw/edinet/

# disclosure-parser の出力JSON経由
python3 scripts/main.py analyze --ticker 7203 --parsed-json data/7203/parsed/financials.json

# 出力先を指定
python3 scripts/main.py analyze --ticker 7203 --input-dir data/7203/raw/edinet/ --output data/7203/risk_analysis.json
```

## Risk Categories

| カテゴリ | キー | 対象 |
|---|---|---|
| 市場リスク | market_risk | 為替・金利・株価変動等 |
| 信用リスク | credit_risk | 取引先の信用力・債務不履行等 |
| オペレーショナルリスク | operational_risk | 内部統制・人材・IT障害等 |
| 規制リスク | regulatory_risk | 法令改正・行政処分・コンプライアンス等 |
| その他 | other_risk | 上記に該当しないリスク |

## Output

`{ticker}_risk_analysis.json`:
```json
{
  "ticker": "7203",
  "analyzed_at": "2026-02-26T...",
  "source_documents": ["S100ABC0"],
  "risk_categories": {
    "market_risk": [{"text": "...", "source": "S100ABC0", "severity": "high"}],
    "credit_risk": [],
    "operational_risk": [],
    "regulatory_risk": [],
    "other_risk": []
  },
  "summary": {
    "total_risks": 5,
    "by_category": {"market_risk": 2, "credit_risk": 1, ...},
    "by_severity": {"high": 1, "medium": 3, "low": 1}
  }
}
```

## Severity判定の精度検証

### 判定方式
キーワードヒューリスティックによる3段階分類:
- **high**: 「重大」「著しい」「大幅」「深刻」「甚大」「多大」「大きな影響」「経営に重要」「事業継続」
- **low**: 「軽微」「限定的」「僅か」「わずか」「小さい」
- **medium**: 上記いずれにも該当しない場合（デフォルト）

### 簡易精度検証（サンプルデータ: tests/evidence/）
| テストケース | 入力テキスト概要 | 期待severity | 判定結果 | 正誤 |
|---|---|---|---|---|
| 為替リスク（重大な影響） | 「為替変動による重大な影響」 | high | high | OK |
| 情報セキュリティ（限定的） | 「事業運営に限定的な影響」 | low | low | OK |
| 法令遵守（キーワードなし） | 「コンプライアンス体制の強化」 | medium | medium | OK |
| 取引先信用（キーワードなし） | 「売掛金の回収が困難」 | medium | medium | OK |
| その他リスク（キーワードなし） | 「外部環境の変化」 | medium | medium | OK |

5件中5件正答（精度: 100%）。ただしサンプルは典型的な表現のみであり、実運用では以下の制約がある:
- 婉曲表現（「一定の影響が生じうる」等）はmediumに分類される
- 文脈依存の重要度（金額規模に対する比率等）は判定不能
- 将来的にLLMベースの判定に切り替えることで精度向上が見込める

### カテゴリ分類の精度
キーワード頻度カウント方式。複数カテゴリのキーワードが混在する場合は最多ヒットカテゴリを採用。
いずれのキーワードにもヒットしない場合は `other_risk` に分類。

## XBRL要素の対応状況と未対応時の処理方針

### 対応済み要素（3種）
| XBRL要素 | 内容 |
|---|---|
| `jpcrp_cor:BusinessRisksTextBlock` | 事業等のリスク |
| `jpcrp_cor:RiskManagementTextBlock` | リスク管理 |
| `jpcrp_cor:ManagementAnalysisOfFinancialPositionOperatingResultsAndCashFlowsTextBlock` | 経営者による分析 |

### 未対応の主要テキスト要素
| XBRL要素 | 内容 | 優先度 |
|---|---|---|
| `jpcrp_cor:CriticalContractsForOperationTextBlock` | 経営上の重要な契約 | 中 |
| `jpcrp_cor:ResearchAndDevelopmentActivitiesTextBlock` | 研究開発活動 | 低 |
| `jpcrp_cor:OverviewOfCapitalExpendituresEtcTextBlock` | 設備投資等の概要 | 低 |

### 未対応要素時の処理方針
- **現行動作**: 未対応のXBRL要素は無視（スキップ）される。エラーにはならない。
- **出力への影響**: `source_documents` にはZIPファイル単位で記録されるため、対応要素が1つも含まれないZIPは `source_documents` から除外される。
- **リスク**: 未対応要素にのみ記載されたリスク情報（例: 重要契約関連リスク）は抽出されない。
- **拡張方法**: `analyzer.py` の `RISK_TEXT_ELEMENTS` タプルに要素名を追加するだけで対応可能。コード変更は1箇所のみ。

## Tests

```bash
pytest --cov=skills/risk-analyzer/scripts --cov-report=term-missing skills/risk-analyzer/tests/
```

### Evidence
`tests/evidence/` に以下を保存:
- `pytest_coverage.log`: テスト実行ログ（44件全通過、カバレッジ95%）
- `sample_input_S100SAMPLE.zip`: サンプルXBRL入力
- `sample_output.json`: 構造化出力JSON
- `REPRODUCE.md`: 再現コマンド

## Status

Implemented.
