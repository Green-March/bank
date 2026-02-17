# Fix: /clear 後 Junior がロール指示書を読まずにタスクを開始する問題

## 問題

Senior が `/clear` + フォローアップメッセージで Junior をリセットした後、Junior がロール指示書（`instructions/junior{N}.md`, `instructions/junior.md`）を読み直さずにタスクを開始する。

SessionStart hook の `additionalContext` はコンテキストとして注入されるが、Junior が能動的に指示書を読む保証はない。結果として Junior がロール境界や運用ルールを忘れた状態で動作するリスクがある。

## 根本原因

`/clear` 後のフォローアップメッセージが「タスクを割り当てました。queue/tasks/junior{N}.yaml を読んでください」「タスク完了。次の指示があるまで待機してください。」となっており、ロール指示書の再読み込みを指示していなかった。

`/clear` はセッションを完全リセットするため、Junior の会話コンテキストは空になる。SessionStart hook で CLAUDE.md 等は注入されるが、ロール固有の指示書（`instructions/junior{N}.md`, `instructions/junior.md`）を明示的に読むよう促さないと、Junior が自身の役割・制約・運用ルールを把握しないまま動作する。

## 修正方針

フォローアップメッセージの先頭に「instructions/junior{N}.md と instructions/junior.md を読んで役割を理解してください。」を追加する。これにより Junior が `/clear` 後に必ずロール指示書を再読み込みしてからタスクに取り掛かる。

## 修正対象ファイル

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `instructions/senior.md` | 修正 | フォローアップメッセージ3箇所を変更 |
| `CLAUDE.md` | 修正 | 通知義務テーブル2箇所を変更 |

## 各ファイルの変更詳細

### 1. Senior 指示書の変更

**パス**: `instructions/senior.md` — 3箇所

**(a) Report リセット手順セクションの send-keys 例**

変更前:
```
tmux send-keys -t <junior_pane_id> "タスクを割り当てました。queue/tasks/junior{N}.yaml を読んでください" && sleep 1 && tmux send-keys -t <junior_pane_id> Enter
```

変更後:
```
tmux send-keys -t <junior_pane_id> "instructions/junior{N}.md と instructions/junior.md を読んで役割を理解してください。新しいタスクが割り当てられているので、queue/tasks/junior{N}.yaml を読んで実装してください。" && sleep 1 && tmux send-keys -t <junior_pane_id> Enter
```

**(b) verdict: ok 完了処理 — 次タスクがある場合**

変更前:
```bash
./templates/senior_clear_junior.sh <junior_pane_id> "タスクを割り当てました。queue/tasks/junior{N}.yaml を読んでください"
```

変更後:
```bash
./templates/senior_clear_junior.sh <junior_pane_id> "instructions/junior{N}.md と instructions/junior.md を読んで役割を理解してください。新しいタスクが割り当てられているので、queue/tasks/junior{N}.yaml を読んで実装してください。"
```

**(c) verdict: ok 完了処理 — 次タスクがない場合**

変更前:
```bash
./templates/senior_clear_junior.sh <junior_pane_id> "タスク完了。次の指示があるまで待機してください。"
```

変更後:
```bash
./templates/senior_clear_junior.sh <junior_pane_id> "instructions/junior{N}.md と instructions/junior.md を読んで役割を理解してください。次の指示があるまで待機してください。"
```

### 2. CLAUDE.md の変更

**パス**: `CLAUDE.md` — 通知義務テーブル 2箇所

**(a) Task assigned 行**

変更前:
```
| Task assigned | Senior | Junior{N} | 「タスクを割り当てました。queue/tasks/junior{N}.yaml を読んでください」 |
```

変更後:
```
| Task assigned | Senior | Junior{N} | 「instructions/junior{N}.md と instructions/junior.md を読んで役割を理解してください。新しいタスクが割り当てられているので、queue/tasks/junior{N}.yaml を読んで実装してください。」 |
```

**(b) Task close (no next task) 行**

変更前:
```
| Task close (no next task) | Senior | Junior{N} | 「タスク完了。次の指示があるまで待機してください。」 |
```

変更後:
```
| Task close (no next task) | Senior | Junior{N} | 「instructions/junior{N}.md と instructions/junior.md を読んで役割を理解してください。次の指示があるまで待機してください。」 |
```

## メッセージ構造

すべてのフォローアップメッセージは2文構成:

```
第1文（共通）: instructions/junior{N}.md と instructions/junior.md を読んで役割を理解してください。
第2文（状況別）:
  - 次タスクあり: 新しいタスクが割り当てられているので、queue/tasks/junior{N}.yaml を読んで実装してください。
  - 次タスクなし: 次の指示があるまで待機してください。
```

`junior{N}` はそれぞれ `junior1`, `junior2`, `junior3` に置き換えて使用する。

## 他プロジェクトへの適用チェックリスト

1. [ ] Senior の指示書で、Junior へのフォローアップメッセージにロール指示書の再読み込み指示を追加する
2. [ ] メイン設定ファイルの通知義務テーブルを更新する
3. [ ] ロール指示書のパスをプロジェクトの構成に合わせて変更する（例: `instructions/` → `roles/` 等）
4. [ ] 初回タスク割り当て（`/clear` を伴わない通常の send-keys 通知）のメッセージも同様に更新する

## 一般化: この問題が発生する条件

以下の条件がすべて揃うと同じ問題が発生する:

1. LLM エージェントのセッションリセット（`/clear`）が外部から行われる
2. SessionStart hook でコンテキストは注入されるが、ロール固有の指示書を能動的に読む指示がない
3. リセット後のフォローアップメッセージがタスク内容のみで、ロール再認識を促していない
4. エージェントが複数タスクを連続で処理するため、リセットのたびにロールを見失うリスクがある

## 関連修正

- `memory/decisions/fix-junior-stall-after-clear.md` — `/clear` 後のフォローアップメッセージ義務化（本修正の前提）
- `memory/decisions/fix-senior-proposal-stall.md` — Senior の計画提出ヘルパー `senior_submit_plan.sh` 追加
