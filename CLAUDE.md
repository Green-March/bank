# CLAUDE.md

This file provides guidance to Claude Code when working in the BANK repository.
Common multi-agent conventions are in the parent `../CLAUDE.md`.
Detailed protocols are in `.claude/rules/`.

## System overview

BANK is a multi-agent orchestration system for Japanese equity intelligence.
6 agents (manager, senior, junior1-3, reviewer) run in a single tmux session (`multiagent`).
Communication is file-based via YAML queues, event-driven via `tmux send-keys`. No polling.

- **manager**: User-facing coordinator. Clarifies analysis goals and constraints, then delegates to senior.
- **senior**: Planner/dispatcher. Designs the end-to-end analysis workflow and assigns tasks to juniors.
- **junior1-3**: Task executors. Collect data, parse disclosures, compute metrics, draft report sections.
- **reviewer**: Quality reviewer (Codex). Reviews plans and deliverables with finance-specific criteria.

## Commands

```bash
./go.sh                          # Start tmux session with all agents
./go.sh --target /path/to/workspace  # Specify target workspace
./go.sh -s                       # Setup-only (create session, don't launch agents)
tmux attach-session -t multiagent
```

`setup.sh` is a compatibility wrapper that forwards all args to `go.sh`.

## Communication flow

```
User -> Manager -> queue/manager_to_senior.yaml -> Senior
Senior -> queue/review/senior_to_reviewer.yaml -> Reviewer (plan review)
Reviewer -> queue/review/reviewer_to_senior.yaml -> Senior (plan approval)
Senior -> queue/tasks/junior{N}.yaml -> Junior{N}
Junior{N} -> queue/reports/junior{N}_report.yaml -> Senior
Senior -> queue/review/junior_to_reviewer.yaml -> Reviewer (deliverable review)
Reviewer -> queue/review/reviewer_to_junior.yaml -> Senior
Senior -> Junior{N} (review relay: verdict: revise only)
Senior -> dashboard.md (verdict: ok -> immediate update)
Senior -> Junior{N} (/clear + standby or next task)
Senior -> Manager (all tasks completed)
```

## Queue file structure

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

Review queues: `queue/review/senior_to_reviewer.yaml`, `queue/review/reviewer_to_senior.yaml`, `queue/review/junior_to_reviewer.yaml`, `queue/review/reviewer_to_junior.yaml`.
Correlation keys (`request_id`, `task_id`, `junior_id`) are mandatory for deliverable review relay.

## Key constraints

- **Target workspace**: `config/target.yaml` is authoritative.
- **Permissions**: `config/permissions.yaml` is authoritative.
- **Network usage**: allowed for market/disclosure data (EDINET, J-Quants, JPX, approved sources).
- **Write scope**: restricted to allowed paths in `config/permissions.yaml`.
- **Dashboard**: only senior updates `dashboard.md`.
- **Race condition rule**: multiple juniors must never write the same output file.

## Dashboard sections

Senior maintains: Action Required, In Progress, Intake, Data Collection, Parsing/Normalization, Metrics/Valuation, Report Drafting, Risk/QA, Completed Today, Skill Candidates, Questions.

## Role instructions

- `instructions/manager.md`, `instructions/senior.md`, `instructions/junior.md`, `instructions/reviewer.md`

## Skills

Core BANK skills in `skills/`:
- `disclosure-collector/` -- EDINET/J-Quants data collection
- `disclosure-parser/` -- XBRL normalization into comparable JSON
- `financial-calculator/` -- metrics calculation (ROE, ROA, margin, growth, CF)
- `financial-reporter/` -- markdown/html report rendering
- `pdf-reader/`, `excel-handler/`, `word-handler/` -- supporting document operations
