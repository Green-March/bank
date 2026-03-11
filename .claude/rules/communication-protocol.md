# Communication protocol (BANK)

## Send-keys rules (mandatory)

### Claude Code agents (manager, senior, junior1-3): two-step method
```bash
# Step 1: send message (without Enter)
tmux send-keys -t <pane_id> "message"

# Step 2: send Enter in a separate call
sleep 1 && tmux send-keys -t <pane_id> Enter
```

### Codex agents (reviewer): single chained command
Reviewer (Codex) may parallelize separate bash calls, causing Enter to arrive before the message.
Always combine into one command:
```bash
tmux send-keys -t <pane_id> "message" && sleep 1 && tmux send-keys -t <pane_id> Enter
```
Never split this into two separate bash tool invocations.
Reviewer completion writes should use `./templates/reviewer_finalize.sh` so YAML write and notify happen in one command.

## Notification obligations

Every YAML write that changes another agent's state MUST be followed by a send-keys notification.

| Event | Notifier | Target | Message |
|---|---|---|---|
| Task assigned | Senior | Junior{N} | instructions/junior{N}.md と instructions/junior.md を読んで役割を理解してください。新しいタスクが割り当てられているので、queue/tasks/junior{N}.yaml を読んで実装してください。 |
| Plan review request | Senior | Reviewer | 計画レビュー依頼です。queue/review/senior_to_reviewer.yaml を読んでください |
| Plan review completed | Reviewer | Senior | 計画レビュー完了。queue/review/reviewer_to_senior.yaml を読んでください |
| Deliverable submitted | Junior{N} | Senior | 成果物完了。レビュー依頼をお願いします。queue/reports/junior{N}_report.yaml を読んでください |
| Deliverable review request | Senior | Reviewer | 成果物レビュー依頼です。queue/review/junior_to_reviewer.yaml を読んでください |
| Deliverable review completed | Reviewer | Senior | 成果物レビュー完了。queue/review/reviewer_to_junior.yaml を読んでください |
| Review result relay (verdict: revise) | Senior | Junior{N} | レビュー結果です。queue/review/reviewer_to_junior.yaml を読んでください |
| Task close (verdict: ok) | Senior | Junior{N} | `./templates/senior_clear_junior.sh` で `/clear` + フォローアップ |
| Task close (no next task) | Senior | Junior{N} | instructions/junior{N}.md と instructions/junior.md を読んで役割を理解してください。次の指示があるまで待機してください。 |
| Final completion | Senior | Manager | 全タスク完了。dashboard.md を確認してください |
| Task assigned (prep) | Senior | junior{N}_report | タスク割り当て前に queue/reports/junior{N}_report.yaml をテンプレートにリセット |

## Report reset rule (mandatory)

Senior は queue/tasks/junior{N}.yaml を書き込む**前に**、
queue/reports/junior{N}_report.yaml を以下のテンプレートにリセットすること:
```yaml
worker_id: junior{N}
task_id: null
ticker: null
analysis_type: null
timestamp: ""
status: idle
result: null
quality_check_required: true
```
リセットを怠ると前回タスクのレポートが残留し、成果物レビューフローが破綻する。
Senior はタスク割り当て前に `./templates/senior_reset_report.sh {N}` を実行してリセットする。
