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

## Implementation Roadmap

| Phase | Task ID | 内容 | Status |
|-------|---------|------|--------|
| T1 | T1_skill_scaffold | ディレクトリ構造・SKILL.md・CLI スケルトン・クラススケルトン作成 | done |
| T2 | (未割当) | `_load_cache()` / `resolve()` 実装 + EDINET コードマッピング JSON 作成 | pending |
| T3 | (未割当) | `update_cache()` 実装（EDINET API / J-Quants API 連携） | pending |
| T4 | (未割当) | `list_all()` 実装 + pytest 統合テスト + CLI ハンドラ結合 | pending |

### T1 完了時点の制約事項

- **CLI 動作不能**: 全サブコマンド (resolve/update/list) は `NotImplementedError` を返す。T2 以降で順次実装。
- **TickerResolver 未実装**: 4メソッド (`resolve`, `update_cache`, `list_all`, `_load_cache`) は全て `NotImplementedError`。
- **テスト未整備**: `tests/` ディレクトリは空。T4 で pytest テストを追加予定。
- **4桁→5桁変換**: 証券コード4桁から EDINET 用5桁コードへの変換ロジックは T2 で実装。
- **キャッシュ仕様未確定**: キャッシュファイル形式 (JSON)・有効期限・格納パスは T2 で確定。

> T1 はスキャフォールド（骨組み）のみを提供する。
> 本スキルを他スキルから呼び出すのは T2 完了以降とすること。

## Status

T1 完了（スキャフォールド作成済み） — CLI・クラス骨組みのみ、コア処理は未実装
