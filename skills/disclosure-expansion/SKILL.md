---
name: disclosure-expansion
description: >-
  EDINET四半期/半期報告書とJ-Quants決算データを収集・構造化・突合し、
  銘柄の開示データを時系列で拡張するエンドツーエンドスキル。
  disclosure-collector / disclosure-parser を拡張再利用し、
  T0共通スキーマ準拠の統合データセットを生成する。
---

# disclosure-expansion

EDINET四半期/半期報告書とJ-Quants決算データを収集・構造化・突合し、銘柄の開示データを時系列で拡張するエンドツーエンドスキル。

## Purpose

指定銘柄に対して以下のパイプラインを一貫実行する:

1. EDINET文書一覧の日次スキャン・キャッシュ（T1R1相当）
2. 四半期/半期報告書PDFのダウンロード（T2相当）
3. PDFテキスト抽出・正規化（T3相当）
4. 構造化JSON生成（T5相当、T5R2修正適用済み）
5. J-Quants決算データ収集（T4相当）
6. ソース間突合QA（T6相当）

2780（コメ兵ホールディングス）での実証結果をベースに設計。

## Inputs

### 必須引数

| 引数 | 型 | 説明 | 例 |
|------|-----|------|-----|
| `ticker` | string | 銘柄コード（4桁） | `2780` |
| `edinet_code` | string | EDINETコード | `E03416` |

### オプション引数

| 引数 | 型 | デフォルト | 説明 |
|------|-----|-----------|------|
| `timeframe` | string | `過去5年..today` | 収集対象期間（`YYYY-MM-DD..YYYY-MM-DD`形式） |
| `report_keyword` | string | `報告書` | EDINET文書フィルタキーワード |
| `doc_type_codes` | list[string] | `["140", "160"]` | docTypeCode（140=四半期報告書, 160=半期報告書） |
| `security_code` | string | `{ticker}0` | 証券コード5桁（自動推定可） |
| `skip_qa` | bool | `false` | QAステップ（T6）をスキップ |
| `skip_jquants` | bool | `false` | J-Quants収集（T4）をスキップ |
| `naming_strategy` | string | `doc_id` | ファイル命名規則（`doc_id` / `doc_id_desc` / `ticker_year`） |

### ticker → edinet_code の解決

`edinet_code`が不明な場合、EDINET提出者コードリスト(CSV)から`ticker + "0"` = security_codeで検索可能。
将来的に自動解決機能を実装予定。

## Usage

### 実装状態

現在提供するサブコマンド:

| サブコマンド | 状態 | 説明 |
|-------------|------|------|
| `validate` | 実装済み (S1) | 入力・環境変数・スキーマの事前検証 |
| `status` | 実装済み (S1) | 既存データの収集状況確認 |
| `reconcile` | 実装済み (S2) | T6突合QAの実行（実データ検証済み） |
| `run` | 実装済み (S3) | パイプラインDAG依存順実行 |

### 事前検証

```bash
python3 skills/disclosure-expansion/scripts/main.py validate \
  --ticker 2780 \
  --edinet-code E03416
```

### ステータス確認

```bash
python3 skills/disclosure-expansion/scripts/main.py status \
  --ticker 2780
```

### T6突合QA実行

```bash
python3 skills/disclosure-expansion/scripts/main.py reconcile \
  --ticker 2780 \
  --tolerance 0.0001
```

### パイプライン自動実行

```bash
# 全ステップ実行
python3 skills/disclosure-expansion/scripts/main.py run \
  --ticker 2780 --edinet-code E03416 \
  --timeframe "2021-01-01..2026-02-16"

# ドライラン（コマンド表示のみ）
python3 skills/disclosure-expansion/scripts/main.py run \
  --ticker 2780 --edinet-code E03416 --dry-run

# J-Quantsスキップ、失敗時はスキップして続行
python3 skills/disclosure-expansion/scripts/main.py run \
  --ticker 2780 --edinet-code E03416 \
  --skip-jquants --on-fail skip

# 特定ステップのみ実行（依存ステップも自動追加）
python3 skills/disclosure-expansion/scripts/main.py run \
  --ticker 2780 --edinet-code E03416 \
  --step t6_reconciliation
```

## Environment Variables

| 変数名 | 必須 | 説明 |
|--------|------|------|
| `EDINET_API_KEY` | Yes | EDINET API v2 サブスクリプションキー |
| `JQUANTS_REFRESH_TOKEN` | Yes* | J-Quants APIリフレッシュトークン（`skip_jquants=true`時は不要） |
| `JQUANTS_EMAIL` | No | トークン自動更新用メールアドレス |
| `JQUANTS_PASSWORD` | No | トークン自動更新用パスワード |
| `DATA_PATH` | No | データ保存先ルート（デフォルト: `./data`） |

## Execution Pipeline

### Step 1: T0 — スキーマ検証

T0共通メタデータスキーマ（`data/{ticker}/schema/common-metadata.schema.json`）の存在を確認。
存在しない場合は初期テンプレートを生成。

**必須キー**: `source`, `endpoint_or_doc_id`, `fetched_at`, `period_end`

### Step 2: T1R1 — EDINET文書一覧収集

```bash
python3 skills/disclosure-collector/scripts/main.py edinet {edinet_code} \
  --ticker {ticker} --security-code {security_code} \
  --start-date {start_date} --end-date {end_date} \
  --report-keyword {report_keyword} \
  --doc-type-code {doc_type_codes[0]} --doc-type-code {doc_type_codes[1]}
```

- 日次キャッシュ: `data/{ticker}/raw/edinet/kessan_tanshin/documents_{YYYY-MM-DD}.json`
- 冪等実行: キャッシュ済み日付はスキップ
- レート制限対策: リクエスト間 sleep(1)

### Step 3: T2 — PDF収集

```bash
python3 skills/disclosure-collector/scripts/main.py edinet {edinet_code} \
  --ticker {ticker} --security-code {security_code} \
  --start-date {start_date} --end-date {end_date} \
  --doc-type-code {doc_type_codes[0]} --doc-type-code {doc_type_codes[1]} \
  --pdf --output-dir data/{ticker}/raw/edinet/shihanki_hokokusho/ \
  --naming-strategy {naming_strategy}
```

- 出力: `data/{ticker}/raw/edinet/shihanki_hokokusho/{doc_id}_{period_end}.pdf`
- manifest: `data/{ticker}/raw/edinet/shihanki_hokokusho/manifest.json`
- T0準拠: 各レコードに `source`, `endpoint_or_doc_id`, `fetched_at`, `period_end` を付与

### Step 4: T3 — PDFテキスト抽出

T2で取得したPDFをpdfplumber + multi-strategyで解析し、セクション分類・テーブル抽出を実行。

- 入力: `data/{ticker}/raw/edinet/shihanki_hokokusho/*.pdf`
- 出力: `data/{ticker}/parsed/kessan_tanshin_text.json`
- 処理: PDF→テキスト分割、テーブル構造解析、財務セクション自動分類
- T0準拠: 各documentの`metadata`に必須4キーを保持

### Step 5: T5 — 構造化JSON生成（T5R2修正適用）

T3出力から財務数値を抽出し、BS/PL/CF/包括利益を構造化JSONに変換。

- 入力: `data/{ticker}/parsed/kessan_tanshin_text.json`
- 出力: `data/{ticker}/parsed/shihanki_structured.json`

#### T5R2で適用済みの修正事項

1. **BS total_assets 完全一致ガード**: `item_matches()`で「資産合計」が「流動資産合計」に誤マッチしないよう、完全一致/部分一致の区別を実装。`資産合計`は完全一致のみ許可。`負債純資産合計`/`負債及び純資産合計`は安全なため部分一致を許可。

2. **半期報告書 period_end 補正**: docTypeCode=160（半期報告書）で、EDINET APIの`periodEnd`（FY末日）ではなく、表紙の`【中間会計期間】`記載から実際の中間期末日を抽出。`period_end_original`に元のFY末日を保持。

3. **脚注パース修正**: `parse_jpn_number()`で全角脚注（`※１`）とASCII脚注マーカー（`※`単独）を区別。全角脚注は`※[０-９]`で除去、ASCII`※`は単独除去。

4. **0行テーブル復元**: pdfplumberがヘッダに数値を格納する分断テーブルに対し、`parse_financial_table()`でヘッダ行をデータ行として復元。

5. **四半期PL/CI期間サブ見出し対応**: `【第N四半期連結累計期間】`等のサブ見出しを直前の財務区分（PL/CI）のコンテキストとして継承。

### Step 6: T4 — J-Quants収集（オプション）

```bash
python3 skills/disclosure-collector/scripts/main.py jquants {ticker}
```

- 出力(raw): `data/{ticker}/raw/jquants/statements_{date}.json`
- 出力(parsed): `data/{ticker}/parsed/jquants_fins_statements.json`
- 認証: `JQUANTS_REFRESH_TOKEN` → IDトークン
- 制約: Free/Lightプランでは過去データに制限あり（FP-5参照）

### Step 7: T6 — 突合QA（オプション）

T4（J-Quants）とT5（EDINET構造化）のクロスチェック。

- 入力: T4 + T5 の parsed JSON
- 出力: `data/{ticker}/qa/source_reconciliation.json`
- 照合キー: `period_end`（T5R2補正後の値を使用）
- 比較項目: `revenue`, `operating_income`, `net_income`, `total_assets`, `equity`
- 許容誤差: 0.01%
- 半期報告書: T4の2Qレコードと照合（`period_end_original`ではなく補正後`period_end`で突合）

## Output

### データディレクトリ構造

```
data/{ticker}/
├── schema/
│   ├── common-metadata.schema.json   # T0
│   ├── common-metadata.md            # T0
│   └── validation.log                # T0
├── raw/
│   ├── edinet/
│   │   ├── kessan_tanshin/           # T1R1 (日次文書一覧JSON)
│   │   └── shihanki_hokokusho/       # T2 (四半期/半期PDF + manifest.json)
│   └── jquants/
│       └── statements_{date}.json    # T4 (生データ)
├── parsed/
│   ├── kessan_tanshin_text.json      # T3 (テキスト抽出)
│   ├── shihanki_structured.json      # T5 (構造化、T5R2修正適用)
│   └── jquants_fins_statements.json  # T4 (正規化)
└── qa/
    └── source_reconciliation.json    # T6 (突合QA)
```

### 出力サマリ（2780実績値）

| ソース | 期間カバレッジ | レコード/文書数 | データサイズ |
|--------|---------------|----------------|-------------|
| EDINET文書一覧 (T1R1) | 2021-01-01 ~ 2026-02-15 | 1872 日次ファイル | — |
| EDINET PDF (T2) | 2020-12-31 ~ 2026-03-31 | 12 PDF + manifest | 12ファイル |
| テキスト抽出 (T3) | 同上 | 12 文書 | 1.2MB |
| 構造化 (T5) | 同上 | 12 文書 | 1.2MB |
| J-Quants (T4) | 2023-12-31 ~ 2025-09-30 | 10 レコード | 15KB |
| 突合QA (T6) | 17期間 (overlap 3, match 3 at 0.1%) | 5 比較項目 × 3 overlap | 14KB |

## Quality Gates

| ゲートID | ステップ | 基準 | 自動化 |
|----------|---------|------|--------|
| QG-T0 | T0以降全ステップ | jsonschema validate PASS（必須4キー） | 自動 |
| QG-T2 | T2 (PDF収集) | `manifest.download_summary.failed == 0` | 自動 |
| QG-T3 | T3 (テキスト抽出) | `document_count == manifest.matched_doc_count` | 自動 |
| QG-T4 | T4 (J-Quants) | `record_count > 0`, revenue非null(FinancialStatements) | 自動 |
| QG-T5-count | T5 (構造化) | `document_count == T3.document_count` | 自動 |
| QG-T5-bs | T5 (構造化) | total_assets完全一致ガード適用済み（流動資産合計≠総資産） | 自動 |
| QG-T5-period | T5 (構造化) | 半期報告書period_end == 実際の中間期末日（FY末日でない） | 自動 |
| QG-T5-pl | T5 (構造化) | PL整合: 売上高 - 売上原価 ≈ 売上総利益 | 自動 |
| QG-T6 | T6 (突合QA) | overlap期間で主要項目が許容誤差0.01%以内 | 自動 |
| QG-T4-cf | T4 (J-Quants) | FYレコードにoperating_cf非null | 自動 |
| QG-coverage | T4+T5 | 全期間の少なくとも1ソースにデータあり | 手動確認 |

### 品質ゲート定義ファイル

`references/quality_gates.yaml` に機械可読な定義を配置。
pipeline-runner の `gates` パラメータと連携可能。

## Failure Patterns and Recovery

### FP-1: J-Quants リフレッシュトークン期限切れ

```
症状:   HTTP 400 "The incoming token is invalid or expired."
影響:   T4 実行不可
検出:   StatementsClient.fetch() で JQuantsAuthError
対処:
  1. .env から JQUANTS_EMAIL / JQUANTS_PASSWORD を読み取る
  2. POST https://api.jquants.com/v1/token/auth_user
     body: {"mailaddress": email, "password": password}
  3. レスポンスの refreshToken を .env の JQUANTS_REFRESH_TOKEN に書き込む
  4. IDトークン取得(auth_refresh)で検証
  5. T4 を再実行
有効期限: 約1週間
自動化:   jquants-token-refresher スキルで対応推奨
```

### FP-2: BS total_assets 誤抽出（T5R2で修正済み）

```
症状:   T6でtotal_assetsがMISMATCH (T5R1値がT4の60-80%程度)
原因:   item_matches()が「資産合計」を「流動資産合計」にマッチ（部分一致バグ）
影響:   T5の総資産値が過小（流動資産合計を返却）
検出:   T6 source_reconciliation.json の total_assets match == "MISMATCH"
修正:   T5R2で適用済み — item_matches()に完全一致ガードを導入
  - 「資産合計」: 完全一致のみ許可
  - 「負債純資産合計」「負債及び純資産合計」: 安全なため部分一致許可
  - 「流動資産合計」「固定資産合計」は total_assets にマッチしない
再発防止: QG-T5-bs ゲートで自動検出
```

### FP-3: 半期報告書の period_end ミスマッチ（T5R2で修正済み）

```
症状:   T6でrevenue等がPERIOD_MISMATCH (T5R1値がT4の約50%)
原因:   半期報告書(docType=160)のperiod_endがFY末日にマッピング、
        実データは中間期(2Q)末日まで
影響:   T6のperiod_end照合で偽のミスマッチが発生
検出:   T6 comparisons[].coverage == "overlap_but_period_mismatch"
修正:   T5R2で適用済み — extract_actual_period_for_hanki()を実装
  - 表紙の【中間会計期間】セクションから実際の中間期末日を抽出
  - period_end を中間期末日に置換、元のFY末日を period_end_original に保持
  - T6突合では補正後 period_end を使用
再発防止: QG-T5-period ゲートで自動検出
```

### FP-4: EDINET API レート制限

```
症状:   HTTP 429 or 連続リクエストでタイムアウト
影響:   T1R1, T2 の収集が不完全
検出:   manifest.json の failed_doc_ids が非空
対処:
  1. リクエスト間に sleep(1) を挿入（デフォルトで実装済み）
  2. manifest.json の failed_doc_ids を確認し、失敗分のみ再取得
  3. 日次一覧は並列不可（EDINET利用規約）
再実行: 同一コマンドを再実行すれば、キャッシュ済み分はスキップされる
```

### FP-5: J-Quants APIの返却期間制約

```
症状:   timeframe要求が2021-01-01〜だが2023年12月以降のみ返却
原因:   J-Quants Free/Light プランの過去データ制限
影響:   2021-2023年のデータはJ-Quantsから取得不可
検出:   T4 record_count < 期待レコード数、または最古period_end > start_date
対処:
  1. EDINET(T2/T3/T5)の四半期報告書で当該期間をカバー
  2. J-Quants Premium プランでは過去10年分取得可能
  3. T6の突合QAで期間ギャップを明示し、single-sourceを許容
QG影響: QG-coverage の手動確認で対応
```

### FP-6: PDF解析失敗（テーブル構造認識不能）

```
症状:   T3/T5のfinancials内の値が全てnull
原因:   PDFのテーブルレイアウトが想定外（画像ベース、複雑な罫線等）
影響:   当該期間の財務データが欠落
検出:   T5 qa.results で対象doc_idが fail、items_extracted == 0
対処:
  1. pdf_metadata.strategy_usedを確認（S1→S2→S3→text_fallback）
  2. OCR対応パーサー(pdf-processing-proスキル)で再試行
  3. 手動でfinancials値を補完し source="manual" を設定
  4. 0行テーブル復元ロジック（T5R2実装済み）を確認
QG影響: QG-T5-count で文書数不一致として検出
```

## Task Dependency Graph

```
T0 (共通スキーマ)
 │
 ├──→ T4 (J-Quants収集) ──────────────────────→ T6 (突合QA)
 │                                                  ↑
 ├──→ T1R1 (EDINET文書一覧)                        │
 │     │                                           │
 │     └──→ T2 (PDF収集)                           │
 │           │                                     │
 │           └──→ T3 (テキスト抽出)                │
 │                 │                               │
 │                 └──→ T5 (構造化, T5R2修正)  ────┘
 │
 └──→ 本スキル (disclosure-expansion)
```

## Dependencies

### 前提スキル（拡張再利用）

| スキル | 用途 | 修正ステータス |
|--------|------|---------------|
| disclosure-collector | T1R1/T2/T4 | TODO: naming-strategy追加、manifestスキーマ拡張（T7R1確定後） |
| disclosure-parser | T3/T5 | T5R2修正適用済み（BS完全一致、period_end補正、脚注パース、0行テーブル） |

### TODO: T7R1/T6R1 確定後の反映事項

以下はT7R1（collector修正）・T6R1（parser修正）の確定を前提とする項目。
確定後にSKILL.mdおよびスクリプトを更新する。

- [ ] **collector: `--naming-strategy` CLI引数追加** — `_build_pdf_base_name()`の修正（edinet.py:312-333）。`doc_id`/`doc_id_desc`/`ticker_year`の選択
- [ ] **collector: manifestのT0共通スキーマ準拠** — `collect_edinet_pdfs()`/`collect_edinet_reports()`のmanifest生成部（edinet.py:486-498, 647-655）に4フィールド標準追加
- [ ] **collector: gap_analysisセクション標準化** — manifest直下に`gap_analysis`オブジェクト追加
- [ ] **parser: BS概念マッチング優先度のskill本体反映** — pdf_parser.pyの`_match_concept()`に優先度導入（T5R2のitem_matches修正をskill本体に統合）
- [ ] **parser: period_end解析のskill本体反映** — pdf_parser.pyの`_parse_period_headers()`にdocTypeCode連動補正を統合
- [ ] **parser: T0共通スキーマ出力** — parser.py/pdf_parser.pyのoutputにsource/endpoint_or_doc_id/fetched_at追加
- [ ] **T6再突合**: T5R2補正後period_endでの突合ログ更新（non-blocker推奨事項）

### ランタイム依存

- Python 3.10+
- pdfplumber (PDF解析)
- **pyyaml** (pipeline.yaml / quality_gates.yaml 解析、`run` サブコマンドで必須)
- jsonschema (T0バリデーション)
- requests (API通信)

```bash
# 依存パッケージ一括インストール
pip install pyyaml pdfplumber jsonschema requests
```

## Re-execution Commands

```bash
# 全パイプライン実行
python3 skills/disclosure-expansion/scripts/main.py run \
  --ticker 2780 --edinet-code E03416 \
  --timeframe "2021-01-01..2026-02-16"

# 個別ステップ再実行

# T1R1: EDINET文書一覧収集
python3 skills/disclosure-collector/scripts/main.py edinet E03416 \
  --ticker 2780 --start-date 2021-01-01 --end-date 2026-02-15 \
  --doc-type-code 140 --doc-type-code 160 --report-keyword "四半期報告書"

# T2: EDINET PDF収集
python3 skills/disclosure-collector/scripts/main.py edinet E03416 \
  --ticker 2780 --start-date 2021-01-01 --end-date 2026-02-15 \
  --doc-type-code 140 --doc-type-code 160 --pdf

# T4: J-Quants決算短信収集
python3 skills/disclosure-collector/scripts/main.py jquants 2780

# T0: スキーマバリデーション
python3 -c "import json, jsonschema; \
  schema=json.load(open('data/2780/schema/common-metadata.schema.json')); \
  data=json.load(open('TARGET_FILE')); \
  jsonschema.validate(data, schema); print('OK')"
```

## Notes

- 2024年制度変更により四半期報告書（docTypeCode=140）は廃止、半期報告書（docTypeCode=160）のみEDINETで提出
- 決算短信はTDnet管轄であり、EDINETからは取得不可（J-Quantsで構造化データを代替取得）
- Q1/Q3四半期報告書にはCF計算書が含まれないのは正常（expected_absent）
- J-Quants Free/LightプランではFYレコードのみoperating_cfが非null

## Subcommand Interface Contracts

### S1: validate / status

| 項目 | validate | status |
|------|----------|--------|
| 必須CLI | `--ticker`, `--edinet-code` | `--ticker` |
| 任意CLI | `--timeframe`, `--skip-jquants` | — |
| 入力 | 環境変数, `data/{ticker}/schema/`, `references/` | `data/{ticker}/` ディレクトリ |
| 出力 | stdout（検証結果テキスト） | stdout（ステータステキスト） |
| 終了コード | 0=PASS, 1=FAIL | 0（常時正常終了） |
| 必須キー | EDINET_API_KEY, JQUANTS_REFRESH_TOKEN* | — |

*`--skip-jquants` 時はJQUANTS_REFRESH_TOKEN不要

### S2: reconcile

| 項目 | 値 |
|------|-----|
| 必須CLI | `--ticker` |
| 任意CLI | `--tolerance` (default: 0.0001 = 0.01%) |
| 入力 | `data/{ticker}/parsed/shihanki_structured.json` (T5), `data/{ticker}/parsed/jquants_fins_statements.json` (T4) |
| 出力 | `data/{ticker}/qa/source_reconciliation.json` |
| 終了コード | 0=全MATCH, 1=MISMATCH or INVALID_COMPARISON あり |
| 必須キー | period_end（照合キー）, revenue/operating_income/net_income/total_assets/equity（比較項目） |

### S3: run

| 項目 | 値 |
|------|-----|
| 必須CLI | `--ticker`, `--edinet-code` |
| 任意CLI | `--timeframe`, `--security-code`, `--report-keyword`, `--skip-jquants`, `--skip-qa`, `--dry-run`, `--retry` (default: 1), `--on-fail` (abort/skip), `--step`, `--log-dir` |
| 入力 | `references/pipeline.yaml` (DAG定義), `references/quality_gates.yaml` (品質ゲート), 環境変数 |
| 出力 | `data/{ticker}/logs/run_{timestamp}.json` (実行ログ), 各ステップの成果物 |
| 終了コード | 0=全SUCCESS, 1=FAILED あり |
| DAG順序 | トポロジカルソート（depends_on ベース） |
| 失敗制御 | `--on-fail abort`: 失敗で停止, `--on-fail skip`: 失敗ステップの下流をスキップして続行 |

## Status

実装完了（validate / status / reconcile / run）
