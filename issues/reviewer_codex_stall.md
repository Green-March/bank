# Issue: Reviewer (Codex) YAML 書き込み直前のセッション停止

## ステータス
- 発生日: 2026-02-17
- 重大度: High（ワークフロー全体をブロックする）
- 発生回数: 同一セッション内で **4回連続**
- 暫定対処: Manager が YAML 記入と Senior 通知を代行

---

## 1. 症状

Reviewer (Codex) がレビュー判定を完了した後、結果を YAML ファイルに書き込む段階で **Codex セッションが停止またはタイムアウト** し、新しいセッションに切り替わる。Senior への send-keys 完了通知も送信されない。

### 発生パターン（4回とも同一）

```
[正常] レビュー依頼を受信
[正常] 対象ファイルを読み込み・検証
[正常] pytest 実行で回帰確認
[正常] verdict を内部的に決定
[異常] YAML 書き込み段階で停止 → Codex セッション切り替わり
[異常] Senior への send-keys 通知が送信されない
[結果] reviewer_to_junior.yaml が null のまま → Senior が検知不能 → Manager にエスカレーション
```

### 各回の停止時メッセージ

| 回 | 対象 | Codex 停止時の表示 | YAML 書き込み | 通知 |
|----|------|-------------------|--------------|------|
| 1回目 | plan_review revision:1 | `zsh:15: parse error near '&&'` → 再試行後成功 | 成功 | 成功 |
| 2回目 | review_req_20260217_008_T2 | `Preparing to edit file (1m 03s)` → セッション切替 | **失敗** → 後に自力成功 | **失敗** |
| 3回目 | review_req_20260217_009_T3 | `Reviewing schema for comments structure (1m 32s)` → セッション切替 | **失敗** | **失敗** |
| 4回目 | review_req_20260217_009_T4 | `Composing detailed review response (1m 00s)` → セッション切替 | 成功 | **失敗** |

### Codex セッション切り替わりの証跡

停止後、ペインに以下が表示される:
```
Token usage: total=60,968 input=51,486 (+ 292,736 cached) output=9,482 (reasoning 5,331)
To continue this session, run codex resume 019c6a77-a6b9-77d0-9926-c5b5e08a58e4

╭──────────────────────────────────────────────────╮
│ >_ OpenAI Codex (v0.101.0)                      │
│ model:     gpt-5.3-codex xhigh   /model to change │
│ directory: ~/Dropbox/dev/bank                    │
╰──────────────────────────────────────────────────╯

› Explain this codebase
```

新しい Codex セッションが起動し、レビューコンテキストが完全に失われる。

---

## 2. 影響

- **ワークフロー全停止**: Senior はレビュー結果がないと次のステップに進めない
- **Manager の手動介入が必須**: 毎回 Manager が YAML を代筆し、Senior に通知を代行する必要がある
- **所要時間の増大**: 1回の復旧に Manager のエスカレーション対応 + 状況確認 + YAML 記入 + 通知で数分ロスする
- **スケーラビリティ阻害**: 現状では Reviewer のレビューごとに停止リスクがあり、タスク数に比例して停止回数が増える

---

## 3. 根本原因の仮説

### 仮説 A: Codex のファイル書き込みオペレーションのタイムアウト

Codex が `cat > file <<EOF ... EOF` で YAML を書き込もうとした際に:
- 1回目は `zsh:15: parse error near '&&'` — heredoc 内の `&&` がシェル構文と衝突
- 2〜4回目は「Preparing to edit file」「Composing detailed review response」等のメッセージを表示した後、1分前後で応答なくセッション終了

**仮説の根拠**: Codex の `apply_patch` や `cat > file <<EOF` は Claude Code の `Write` ツールとは異なるメカニズムで、YAML 内の特殊文字（`:`, `"`, `&&`）がシェルエスケープ問題を起こしやすい。

### 仮説 B: Codex の出力トークン制限

Reviewer のレビューコメントは5観点 (data_integrity, source_traceability, analytical_validity, clarity, risk_disclosure) + suggested_changes を含み、1回の YAML 書き込みで大量のテキストを生成する。Codex の出力トークン上限に到達してセッションが強制終了した可能性。

**仮説の根拠**: Token usage ログで `output=9,482 (reasoning 5,331)` と表示されており、出力トークンの大半がレビュー内容の生成に使われている。

### 仮説 C: Codex の長時間タスク実行制限

Codex がレビュー作業（ファイル読み込み → pytest 実行 → 差分確認 → YAML 記入 → send-keys）を1ターンで完遂しようとすると、総実行時間が Codex のターン制限を超過する可能性。

**仮説の根拠**: Reviewer のペインログを見ると、1レビューあたり複数の `Explored`, `Ran pytest`, `Ran git diff` 等のツール呼び出しがあり、ツール実行回数が多い。

---

## 4. 背景情報

### Reviewer の起動構成

```bash
# go.sh line 360
env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u AWS_ACCESS_KEY_ID \
    -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN \
    -u GOOGLE_API_KEY -u GOOGLE_APPLICATION_CREDENTIALS \
    -u AZURE_OPENAI_API_KEY -u GITHUB_TOKEN -u GH_TOKEN \
    -u GITLAB_TOKEN -u SSH_AUTH_SOCK \
    codex -s danger-full-access -a never -C /Users/fumitotakahashi/Dropbox/dev/bank
```

- **ツール**: OpenAI Codex v0.101.0
- **モデル**: gpt-5.3-codex xhigh
- **サンドボックス**: `danger-full-access`（tmux ソケットアクセスのため）
- **承認**: `-a never`（自動承認）
- **環境変数**: 10種のクレデンシャル変数をスクラブ

### Junior (Claude Code) との比較

| 項目 | Reviewer (Codex) | Junior (Claude Code) |
|------|-----------------|---------------------|
| ツール | `codex` | `claude` |
| モデル | gpt-5.3-codex | claude opus |
| ファイル書き込み | `cat > file <<EOF` / `apply_patch` | `Write` ツール (内蔵) |
| send-keys パターン | 単一チェーンコマンド必須 | 2ステップ (メッセージ → Enter 別呼び出し) |
| SessionStart hook | 対応 (`/clear` で reviewer.md 再読み込み) | 対応 (`/clear` で junior.md 再読み込み) |
| PreToolUse hook | `deny-check.sh` 適用 | `deny-check.sh` 適用 |
| セッション持続性 | タイムアウトで自動終了 → 新セッション起動 | 自動コンパクション → 継続 |

### 重要な非対称性

1. **Claude Code はコンテキスト自動コンパクション機能がある** が、Codex にはない（セッション終了 → 再起動）
2. **Claude Code の `Write` ツールはアトミック** だが、Codex の `cat > file <<EOF` はシェル構文依存で失敗しやすい
3. **Codex のセッション終了は通知なし** — 他のエージェントは Reviewer が停止したことを検知できない

### hooks の適用状況

```json
// .claude/settings.json
{
  "hooks": {
    "SessionStart": [{ "matcher": "clear", "hooks": [{ "type": "command", "command": "...sessionstart-clear-load-junior-context.sh" }] }],
    "PreToolUse": [{ "matcher": "Bash", "hooks": [{ "type": "command", "command": "...deny-check.sh" }] }]
  }
}
```

- SessionStart hook: Reviewer は `reviewer` ロールとして対応済み（`/clear` で `instructions/reviewer.md` を再読み込み）
- PreToolUse hook: `deny-check.sh` は Codex にも適用される（ただし Codex のツール名が `Bash` と一致する場合のみ）
- **注意**: hooks は Claude Code の仕組み。Codex が hooks を同様に処理するかは未検証。

### Reviewer の期待動作フロー

```
1. Senior から send-keys で wakeup を受信
2. queue/review/junior_to_reviewer.yaml を読み込み
3. 対象ファイル・テスト結果を確認（Explore, pytest 等）
4. verdict/comments/suggested_changes を決定
5. queue/review/reviewer_to_junior.yaml に書き込み  ← ここで停止
6. Senior に send-keys で完了通知                    ← ここまで到達しない
```

### CLAUDE.md に定義された復旧プロトコル

```
### Reviewer stall recovery (mandatory, Senior)
- 受領通知後、reviewer_to_senior.yaml / reviewer_to_junior.yaml を1回確認し、null の場合のみ是正メッセージを1回送る（Polling禁止）
- 是正後も null が続く場合は dashboard.md の Action Required に incident 記録し、Manager にエスカレーション
```

---

## 5. 過去の関連インシデント

| 日付 | インシデント | 症状 | 原因 | 対処 |
|------|------------|------|------|------|
| 2026-02-11 | Permission blocking | 全エージェント停止 | `--dangerously-skip-permissions` 未付与 | go.sh 修正 |
| 2026-02-16 | send-keys 順序 | Enter がメッセージより先に到着 | Codex がバッチ処理を並列化 | 単一チェーンコマンドに統一 |
| 2026-02-17 | Reviewer context 57% | 応答不能 | コンテキスト枯渇 | Manager が verdict 代筆 |
| 2026-02-17 | 本件 (4回) | YAML 書き込み前にセッション停止 | 未確定（上記3仮説） | Manager が YAML 代筆 + 通知代行 |

---

## 6. 検討すべき恒久対策の方向性

### 方向性 A: Reviewer を Claude Code に切り替え
- `Write` ツールによるアトミックなファイル書き込み
- 自動コンパクションによるセッション継続性
- hooks の完全な適用
- **課題**: tmux ソケットアクセスの互換性確認が必要

### 方向性 B: YAML 書き込み専用ラッパースクリプト
- Reviewer がレビュー結果を引数で渡すと、スクリプトが YAML 書き込み + send-keys 通知をアトミックに実行
- Codex のシェル構文問題を回避
- **例**: `./scripts/write-review.sh --file reviewer_to_junior.yaml --verdict ok --request-id xxx --task-id xxx --junior-id xxx --comments "..." --senior-pane %81`

### 方向性 C: Senior 側の自動ポーリング（制限付き）
- Senior が Reviewer に通知後、一定回数（例: 3回 × 30秒間隔）だけ YAML を確認する
- 現在は1回確認 → エスカレーションだが、Reviewer が書き込み完了しているケース（4回目）を自動検知できる
- **課題**: CLAUDE.md の Polling 禁止ルールとの整合

### 方向性 D: Reviewer の処理を分割
- 1ターンで全て完遂するのではなく、判定フェーズと書き込みフェーズを分離
- 判定結果を中間ファイルに保存 → 別コマンドで YAML に転記
- **課題**: フロー複雑化

---

## 7. 参照ファイル

| ファイル | 関連箇所 |
|---------|---------|
| `instructions/reviewer.md` | Reviewer の全指示書 |
| `go.sh` | 339-382行: Codex 起動コマンドと初期化メッセージ |
| `CLAUDE.md` | 221-231行: Reviewer completion contract, stall recovery |
| `.claude/settings.json` | hooks 設定 |
| `.claude/hooks/deny-check.sh` | PreToolUse ガード（Senior/Reviewer 用ロール境界追加済み） |
| `.claude/hooks/sessionstart-clear-load-junior-context.sh` | SessionStart hook（reviewer 対応済み） |
| `memory/session_20260217.md` | 110-120行: 本セッションのインシデント記録 |
| `memory/session_20260216.md` | 58-70行: send-keys 順序問題の修正 |
| `memory/session_20260211.md` | 93-98行: Permission blocking 障害 |
