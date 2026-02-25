# ticker-resolver

ticker(4桁) → edinet_code, company_name, fye_month を自動解決する CLI ツール。

## Description

日本株の銘柄コード（4桁）を入力として、EDINET コード・会社名・決算月を
ローカルキャッシュまたは外部 API から解決する。他スキル（disclosure-collector,
financial-integrator 等）の前処理として利用する。

## Usage

```bash
# 銘柄コードから企業情報を解決
python3 skills/ticker-resolver/scripts/main.py resolve --ticker 7203

# キャッシュを更新（EDINET / J-Quants から取得）
python3 skills/ticker-resolver/scripts/main.py update

# キャッシュ内の全銘柄を一覧表示
python3 skills/ticker-resolver/scripts/main.py list
python3 skills/ticker-resolver/scripts/main.py list --format json
```

## CLI Options

### resolve

| Option | Required | Description |
|--------|----------|-------------|
| `--ticker` | Yes | 銘柄コード（4桁、例: 7203） |
| `--format` | No | 出力形式 (`text` / `json`)。デフォルト: `text` |

### update

| Option | Required | Description |
|--------|----------|-------------|
| `--source` | No | データソース (`edinet` / `jquants` / `all`)。デフォルト: `all` |
| `--force` | No | キャッシュ有効期限を無視して強制更新 |

### list

| Option | Required | Description |
|--------|----------|-------------|
| `--format` | No | 出力形式 (`text` / `json`)。デフォルト: `text` |
| `--fye-month` | No | 決算月でフィルタ（1-12） |

## Output

### text 形式（デフォルト）
```
7203  E02144  トヨタ自動車  3月決算
```

### json 形式
```json
{
  "ticker": "7203",
  "edinet_code": "E02144",
  "company_name": "トヨタ自動車株式会社",
  "fye_month": 3
}
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATA_PATH` | データディレクトリのパス | `<repo_root>/data` |
| `JQUANTS_REFRESH_TOKEN` | J-Quants API リフレッシュトークン | (必須: jquants/all 使用時) |
| `EDINET_API_KEY` | EDINET API キー | (任意) |

## Data Source Field Mapping

| EDINET CSV column | J-Quants field | Internal key | Notes |
|-------------------|---------------|--------------|-------|
| 証券コード (e.g. "72030") | Code ("72030") | sec_code | 5桁。両ソース共通キー |
| 提出者名 | CompanyName | company_name | EDINET 優先 (all 時) |
| ＥＤＩＮＥＴコード | (なし) | edinet_code | EDINET 固有 |
| 決算日 → 月抽出 | (なし) | fye_month | EDINET 固有。J-Quants 単独時は None |
| 上場区分 | MarketCode | (フィルタ用) | EDINET:"上場" / J-Quants:市場コード |

## Implementation Roadmap

| Phase | Task ID | 内容 | Status |
|-------|---------|------|--------|
| T1 | T1_skill_scaffold | ディレクトリ構造・SKILL.md・CLI スケルトン・クラススケルトン作成 | done |
| T2 | (過去実装済) | `_load_cache()` / `resolve()` 実装 + EDINET コードマッピング | done |
| T3 | (過去実装済) | `update_cache()` EDINET API 連携 | done |
| T4 | (過去実装済) | `list_all()` 実装 + pytest 統合テスト + CLI ハンドラ結合 | done |
| T5 | T5_req022 | J-Quants ソース実装 (`source='jquants'`/`'all'` マージ) | done |

### T5 完了時点の実装状況

- **J-Quants 連携完了**: `update_cache(source='jquants')` で J-Quants `/v1/listed/info` から上場銘柄一覧を取得
- **マージロジック**: `source='all'` で EDINET + J-Quants データを sec_code をキーにマージ（EDINET 側が優先）
- **best-effort 設計**: `source='all'` で J-Quants 取得失敗時は EDINET のみで続行
- **認証**: `skills/common/auth.py` の `JQuantsAuth` を使用（`sys.path.insert` 不使用）
- **テスト**: 38テスト（既存27 + J-Quants 11）全 PASSED
- **キャッシュファイル**: EDINET → `EdinetcodeDlInfo.csv`, J-Quants → `jquants_listed.json`

## Status

T5 完了 — EDINET + J-Quants 両ソース対応済み、38テスト PASSED
