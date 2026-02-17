# Fix: /clear 後 Junior がプロンプト待ちで停止する問題

## 問題

Senior が `verdict: ok` 後に Junior へ `/clear` を送った際、Junior が instruction を読み込むが空のプロンプト待ちで停止する。

## 根本原因

Claude Code の SessionStart hook (`additionalContext`) は受動的なコンテキスト注入であり、Claude に能動的なアクションを起こさせる機能はない。`/clear` 後に Junior のコンテキストには instruction が注入されるが、ユーザー入力（send-keys メッセージ）がないと Claude は何も実行しない。

Senior が次タスクを持っている場合はタスク通知メッセージが送られるため問題にならないが、**次タスクがない場合にメッセージが送られず Junior が停止する**。

## 修正方針

`/clear` 後に **必ずフォローアップメッセージを送る** ことを義務化する。ヘルパースクリプトで `/clear` + sleep + フォローアップを1コマンドで実行し、送り忘れを防ぐ。

## 修正対象ファイル

| ファイル | 変更種別 | 内容 |
|---------|---------|------|
| `templates/senior_clear_junior.sh` | 新規作成 | `/clear` → sleep → フォローアップの一括実行スクリプト |
| `instructions/senior.md` | 修正 | 完了処理をヘルパー使用に変更、`/clear` 単独送信を禁止 |
| `instructions/junior.md` | 修正 | `/clear` 後にフォローアップメッセージを待つ記述に変更 |
| `CLAUDE.md` | 修正 | 通信フロー・通知義務テーブル・レビューフローの記述更新 |
| `config/permissions.yaml` | 修正 | `exec_commands` にヘルパースクリプトを追加 |

## 各ファイルの変更詳細

### 1. ヘルパースクリプト (新規作成)

**パス**: `templates/senior_clear_junior.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
# Usage: senior_clear_junior.sh <pane_id> <follow_up_message>
pane_id="${1:?Usage: senior_clear_junior.sh <pane_id> <message>}"
message="${2:?Usage: senior_clear_junior.sh <pane_id> <message>}"

tmux send-keys -t "${pane_id}" "/clear" && sleep 1 && tmux send-keys -t "${pane_id}" Enter
sleep 5
tmux send-keys -t "${pane_id}" "${message}" && sleep 1 && tmux send-keys -t "${pane_id}" Enter

echo "senior_clear_junior: cleared ${pane_id} and sent follow-up"
```

作成後 `chmod +x` で実行権限を付与すること。

**設計意図**:
- `/clear` 後の 5秒 sleep は Claude Code がセッションをリセットし SessionStart hook を処理する時間
- Codex (Senior) は複数の bash 呼び出しを並列実行する可能性があるため、1スクリプトにまとめる
- `reviewer_finalize.sh` と同じ設計パターン（YAML 書き込み + 通知の原子的実行）

### 2. Senior 指示書の変更

**パス**: `instructions/senior.md` — `verdict: ok` 完了処理セクション

変更前:
```
### `verdict: ok` 受領時の完了処理（必須）
1. dashboard.md に完了を反映。
2. Junior ペインに /clear を送信。
3. dashboard.md を読み直し、次タスクがあれば指示。なければ待機。

送信例:
tmux send-keys -t <pane_id> "/clear" && sleep 1 && tmux send-keys -t <pane_id> Enter
```

変更後:
```
### `verdict: ok` 受領時の完了処理（必須）
1. dashboard.md に完了を反映。
2. dashboard.md を読み直し、次タスクの有無を確認。
3. ヘルパースクリプトで /clear + フォローアップを送信:

   次タスクがある場合（report リセット・task YAML 書き込み後）:
   ./templates/senior_clear_junior.sh <pane_id> "instructions/junior{N}.md と instructions/junior.md を読んで役割を理解してください。新しいタスクが割り当てられているので、queue/tasks/junior{N}.yaml を読んで実装してください。"

   次タスクがない場合:
   ./templates/senior_clear_junior.sh <pane_id> "instructions/junior{N}.md と instructions/junior.md を読んで役割を理解してください。次の指示があるまで待機してください。"

重要: /clear 単独での送信は禁止。必ず senior_clear_junior.sh を使用すること。
```

**ポイント**: 手順2と3の順番を入れ替え、`/clear` を送る前に次タスクの有無を判定するようにした。

### 3. Junior 指示書の変更

**パス**: `instructions/junior.md` — 連絡ルールセクション

変更前:
```
- Reviewer の verdict: ok 後は追加の完了通知を送らず、Senior からの /clear に従って待機する
```

変更後:
```
- Reviewer の verdict: ok 後は追加の完了通知を送らず、Senior からの /clear + フォローアップメッセージを待つ。
  /clear 後に Senior から「待機指示」または「次タスク通知」が届くので、それに従う。
```

### 4. CLAUDE.md の変更

**パス**: `CLAUDE.md` — 3箇所

**(a) 通信フロー図**

変更前: `Senior → Junior{N} (/clear)`
変更後: `Senior → Junior{N} (/clear + 待機指示 or 次タスク通知)`

**(b) 通知義務テーブル**

既存行を変更:
```
| Task close (verdict: ok) | Senior | Junior{N} | ./templates/senior_clear_junior.sh で /clear + フォローアップ |
```

新規行を追加:
```
| Task close (no next task) | Senior | Junior{N} | 「instructions/junior{N}.md と instructions/junior.md を読んで役割を理解してください。次の指示があるまで待機してください。」 |
```

**(c) Deliverable review flow ステップ5**

変更前: `Senior updates dashboard.md, sends /clear to that Junior, then reads dashboard.md and issues the next task`
変更後: `Senior updates dashboard.md, then uses ./templates/senior_clear_junior.sh to send /clear + follow-up message to that Junior`

### 5. permissions.yaml の変更

**パス**: `config/permissions.yaml`

`exec_commands` リストに追加:
```yaml
    - ./templates/senior_clear_junior.sh
```

## 他プロジェクトへの適用チェックリスト

1. [ ] ヘルパースクリプトをコピーし `chmod +x` する
2. [ ] Senior の指示書で `/clear` 単独送信を禁止し、ヘルパー使用に変更する
3. [ ] Junior の指示書で `/clear` 後のフォローアップメッセージ受信を記述する
4. [ ] メインの設定ファイル（CLAUDE.md 相当）の通信フロー・通知義務テーブルを更新する
5. [ ] パーミッション設定にヘルパースクリプトを追加する
6. [ ] sleep 秒数はプロジェクトの SessionStart hook 処理時間に応じて調整する（デフォルト5秒）

## 一般化: この問題が発生する条件

以下の条件がすべて揃うと同じ問題が発生する:

1. Claude Code のセッションリセット（`/clear`）を tmux 経由で別エージェントから送信している
2. SessionStart hook で instruction を注入しているが、それだけでは Claude が自発的に動作しない
3. `/clear` 後に後続メッセージを送るかどうかが条件分岐になっており、送らないパスが存在する
