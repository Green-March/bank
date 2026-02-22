# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## System overview

BANK is a multi-agent orchestration system for Japanese equity intelligence.
6 agents (manager, senior, junior1-3, reviewer) run in a single tmux session (`multiagent`).
Communication is file-based via YAML queues, event-driven via `tmux send-keys`. No polling.

- **manager**: User-facing coordinator. Clarifies analysis goals and constraints, then delegates to senior.
- **senior**: Planner/dispatcher. Designs the end-to-end analysis workflow and assigns tasks to juniors.
- **junior1-3**: Task executors. Collect data, parse disclosures, compute metrics, draft report sections.
- **reviewer**: Quality reviewer (Codex). Reviews plans and deliverables with finance-specific criteria.

## Commands

### Initial setup
```bash
# Windows: run install.bat as Administrator first, then in Ubuntu/WSL:
./first_setup.sh
```

### Daily startup
```bash
./go.sh                          # Start tmux session with all agents
./go.sh --target /path/to/workspace  # Specify target workspace
./go.sh -s                       # Setup-only (create session, don't launch agents)
./go.sh --shell bash             # Force shell type (bash/zsh)
```

### Tmux session
```bash
tmux attach-session -t multiagent
tmux list-panes -t multiagent:0 -F '#{pane_id} #{pane_title} #{@agent_role} #{pane_left} #{pane_top}'
```

`setup.sh` is a compatibility wrapper that forwards all args to `go.sh`.

### Python development
```bash
pip install -e ".[dev]"
pytest
black --check skills/ src/
ruff check skills/ src/
mypy src/
```

## Architecture

### Pane layout (tmux session: `multiagent`)
```
┌─────────────┬─────────────┬─────────────┬─────────────┐
│  manager    │  senior     │  junior1    │  junior3    │
│  (magenta)  │  (red)      │  (blue)     │  (blue)     │
│             │             ├─────────────├─────────────┤
│             │             │  junior2    │  reviewer   │
│             │             │  (blue)     │  (yellow)   │
└─────────────┴─────────────┴─────────────┴─────────────┘
```

### Communication flow
```
User → Manager → queue/manager_to_senior.yaml → Senior
Senior → queue/review/senior_to_reviewer.yaml → Reviewer (計画レビュー)
Reviewer → queue/review/reviewer_to_senior.yaml → Senior (計画承認)
Senior → queue/tasks/junior{N}.yaml → Junior{N}
Junior{N} → queue/reports/junior{N}_report.yaml → Senior
Senior → queue/review/junior_to_reviewer.yaml → Reviewer (成果物レビュー)
Reviewer → queue/review/reviewer_to_junior.yaml → Senior
Senior → Junior{N} (レビュー結果中継: verdict: revise のみ)
Senior → dashboard.md (verdict: ok を即時反映)
Senior → Junior{N} (/clear + 待機指示 or 次タスク通知)
Senior → Manager (全タスク完了報告)
```

Senior is the communication hub. Junior and Reviewer never communicate directly.

### Notification obligations (send-keys)
Every YAML write that changes another agent's state MUST be followed by a send-keys notification.

| Event | Notifier | Target | Message |
|---|---|---|---|
| Task assigned | Senior | Junior{N} | 「instructions/junior{N}.md と instructions/junior.md を読んで役割を理解してください。新しいタスクが割り当てられているので、queue/tasks/junior{N}.yaml を読んで実装してください。」 |
| Plan review request | Senior | Reviewer | 「計画レビュー依頼です。queue/review/senior_to_reviewer.yaml を読んでください」 |
| Plan review completed | Reviewer | Senior | 「計画レビュー完了。queue/review/reviewer_to_senior.yaml を読んでください」 |
| Deliverable submitted | Junior{N} | Senior | 「成果物完了。レビュー依頼をお願いします。queue/reports/junior{N}_report.yaml を読んでください」 |
| Deliverable review request | Senior | Reviewer | 「成果物レビュー依頼です。queue/review/junior_to_reviewer.yaml を読んでください」 |
| Deliverable review completed | Reviewer | Senior | 「成果物レビュー完了。queue/review/reviewer_to_junior.yaml を読んでください」 |
| Review result relay (`verdict: revise`) | Senior | Junior{N} | 「レビュー結果です。queue/review/reviewer_to_junior.yaml を読んでください」 |
| Task close (`verdict: ok`) | Senior | Junior{N} | `./templates/senior_clear_junior.sh` で `/clear` + フォローアップ |
| Task close (no next task) | Senior | Junior{N} | 「instructions/junior{N}.md と instructions/junior.md を読んで役割を理解してください。次の指示があるまで待機してください。」 |
| Final completion | Senior | Manager | 「全タスク完了。dashboard.md を確認してください」 |
| Task assigned (prep) | Senior | junior{N}_report | タスク割り当て前に queue/reports/junior{N}_report.yaml をテンプレートにリセット |

### Report reset rule (mandatory)
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
これは go.sh の reset 処理（行154-163）と同一テンプレート。
リセットを怠ると前回タスクのレポートが残留し、成果物レビューフローが破綻する。

### Send-keys rules (mandatory)

#### Claude Code agents (manager, senior, junior1-3): two-step method
```bash
# Step 1: send message (without Enter)
tmux send-keys -t <pane_id> "message"

# Step 2: send Enter in a separate call
sleep 1 && tmux send-keys -t <pane_id> Enter
```

#### Codex agents (reviewer): single chained command
Reviewer (Codex) may parallelize separate bash calls, causing Enter to arrive before the message.
Always combine into one command:
```bash
tmux send-keys -t <pane_id> "message" && sleep 1 && tmux send-keys -t <pane_id> Enter
```
Never split this into two separate bash tool invocations.
Reviewer completion writes should use `./templates/reviewer_finalize.sh` so YAML write and notify happen in one command.

### Queue file structure

Task assignment (`queue/tasks/junior{N}.yaml`):
```yaml
task:
  task_id: null
  parent_cmd: null
  description: null
  ticker: null
  universe: null
  analysis_type: null
  timeframe: null
  output_path: null
  priority: medium
  status: idle
  timestamp: ""
```

Report (`queue/reports/junior{N}_report.yaml`):
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

Plan review request (`queue/review/senior_to_reviewer.yaml`):
```yaml
plan_review_request: null
```

Plan review response (`queue/review/reviewer_to_senior.yaml`):
```yaml
plan_review_response: null
```

Deliverable review request (`queue/review/junior_to_reviewer.yaml`):
```yaml
review_request:
  request_type: deliverable_review
  review_type: deliverable
  request_id: null
  task_id: null
  junior_id: null
  status: idle
  timestamp: ""
  payload: null
review_followup:
  request_id: null
  task_id: null
  junior_id: null
  status: null
  timestamp: ""
  payload: null
```

Deliverable review response (`queue/review/reviewer_to_junior.yaml`):
```yaml
review_response:
  request_type: deliverable_review_response
  review_type: deliverable
  request_id: null
  task_id: null
  junior_id: null
  verdict: null
  comments: null
  suggested_changes: null
  status: idle
  timestamp: ""
```

Common-queue correlation keys (`request_id`, `task_id`, `junior_id`) are mandatory for deliverable review relay.

## Plan review flow (mandatory)
1. Senior designs the plan (workplan, scope, quality_criteria)
2. Senior executes `./templates/senior_submit_plan.sh` to write plan to `queue/review/senior_to_reviewer.yaml` and notify Reviewer (YAML write + notification in one command, mandatory)
3. Reviewer evaluates coverage, risk, feasibility, and data source quality
4. Reviewer writes verdict to `queue/review/reviewer_to_senior.yaml`
5. If `verdict: revise`, senior revises and resubmits (repeat from step 2)
6. If `verdict: ok`, senior assigns junior tasks

## Deliverable review flow (mandatory)
1. Junior writes deliverable report to `queue/reports/junior{N}_report.yaml`
2. Senior relays review request via `queue/review/junior_to_reviewer.yaml`
3. Reviewer writes review via `queue/review/reviewer_to_junior.yaml`
4. If `verdict: revise`, Senior relays review results to Junior and repeats from step 2
5. If `verdict: ok`, Senior updates `dashboard.md`, then uses `./templates/senior_clear_junior.sh` to send `/clear` + follow-up message to that Junior (next task notification or standby instruction)

### Reviewer completion contract (mandatory)
- Review request is complete only when response YAML is non-null:
  - Plan review: `queue/review/reviewer_to_senior.yaml`
  - Deliverable review: `queue/review/reviewer_to_junior.yaml`
- Receipt-only responses such as "読みました/確認しました" are invalid and must not terminate the review flow.
- If Reviewer is blocked, Reviewer must still write `verdict: revise` with blockers and required follow-up in `suggested_changes`, then notify Senior.
- Reviewer must keep comments concise (deliverable 5観点は各1文、`suggested_changes` は最大2件) and use `./templates/reviewer_finalize.sh`.

### Reviewer stall recovery (mandatory, Senior)
- After notifying Reviewer, Senior performs a single verification read of the expected output YAML (no polling loop).
- If output remains `null` and Reviewer gave only an acknowledgement, Senior sends a corrective message with explicit output contract (`verdict/comments/suggested_changes`), concise-output limits, and `./templates/reviewer_finalize.sh` usage.
- If still unresolved, Senior logs an incident in `dashboard.md` (`Action Required`) and escalates to Manager.

## Junior context management
- Max 3 consecutive tasks per junior in a single session.
- Heavy tasks (large file merge, integrated report assembly) go to the least-loaded junior.
- Restart triggers: `Compacting conversation`, `Context left until auto-compact: 0%`, or 3 tasks completed.

## Key constraints
- **Target workspace**: `config/target.yaml` is authoritative.
- **Permissions**: `config/permissions.yaml` is authoritative.
- **Network usage**: allowed for market/disclosure data collection (EDINET, J-Quants, JPX, and approved sources).
- **Write scope**: restricted to allowed paths in `config/permissions.yaml`.
- **Dashboard**: only senior updates `dashboard.md`.
- **Race condition rule**: multiple juniors must never write the same output file.

## Role boundary enforcement (strict)
Each agent MUST stay within its designated role. Violations waste context and cause stalls.

- **Senior**: Plan, decompose tasks, assign to juniors, relay reviews. NEVER execute tasks (code, file I/O, data processing). If senior needs to verify a deliverable, delegate a verification task to a junior or reviewer — do not read/run files directly.
- **Junior**: Execute assigned tasks only. NEVER self-plan, communicate with other juniors, or contact reviewer/manager directly.
- **Reviewer**: Review only. NEVER implement fixes. Return verdicts via YAML to senior.
- **Manager**: Clarify requirements, delegate to senior. NEVER execute tasks or bypass senior.

### Context conservation
- Agents MUST minimize unnecessary file reads and tool calls to preserve context window.
- Senior should NOT re-read deliverable files that reviewer has already verified.
- When context drops below 15%, the agent should complete its current operation and report status before auto-compact triggers.

## go.sh startup sequence
1. Write target to `config/target.yaml`
2. Kill existing `multiagent` session
3. Backup prior dashboard/report queues if activity exists
4. Reset queue files to idle state
5. Initialize `dashboard.md`
6. Create tmux session with 6 panes
7. Launch agents: manager/juniors/senior (`claude --model opus --dangerously-skip-permissions`), reviewer (`codex -s danger-full-access -a never`)
8. Send init instructions

### Agent launch flags (mandatory)
All Claude agents (manager, junior1-3) MUST be launched with `--dangerously-skip-permissions`.
Without this flag, every file write and bash execution requires manual approval via "accept edits on" prompt,
which causes agents to stall indefinitely when other agents send them messages via `tmux send-keys`.
Senior uses Claude with `--dangerously-skip-permissions`. Reviewer uses Codex with `-s danger-full-access -a never` so tmux socket operations are not blocked by macOS sandboxing.
`go.sh` mitigates risk by scrubbing common credential environment variables and pinning Codex working directory with `-C <target>`.

## Session start requirements (all agents)
1. Read Memory MCP if available.
2. Read role instruction file in `instructions/`.
3. Read required context files: `CLAUDE.md`, `config/target.yaml`, `config/permissions.yaml`, and relevant workspace context files.

## Role instructions
- `instructions/manager.md`
- `instructions/senior.md`
- `instructions/junior.md`
- `instructions/reviewer.md`

## Dashboard sections (`dashboard.md`)
Senior maintains these sections:
- Action Required
- Intake
- Data Collection
- Parsing / Normalization
- Metrics / Valuation
- Report Drafting
- Risk / QA
- Completed Today
- Skill Candidates
- Questions

## Skills system
Skills are stored in `skills/`.

Core BANK skills:
- `skills/disclosure-collector/` — EDINET/J-Quants data collection
- `skills/disclosure-parser/` — XBRL normalization into comparable JSON
- `skills/financial-calculator/` — metrics calculation (ROE, ROA, margin, growth, CF)
- `skills/financial-reporter/` — markdown/html report rendering
- `skills/pdf-reader/`, `skills/excel-handler/`, `skills/word-handler/` — supporting document operations
