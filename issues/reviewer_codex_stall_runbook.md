# Reviewer Stall Runbook (2026-02-17)

## Goal
- Verify whether Reviewer stall is caused mainly by `write+notify` handling, output volume, or total turn duration.
- Decide whether Reviewer stays on Codex (`high`) or switches runtime/model strategy.

## Preconditions
- Start with `./go.sh --codex-model high`.
- Reviewer must use `./templates/reviewer_finalize.sh` for all review completions.
- Senior follows single-check recovery rule (no polling loop).

## Test matrix (A/B/C)
1. Case A: minimal plan review response  
   - 2 short comments, 0 suggestions
   - expected: YAML non-null + notify success
2. Case B: maximal concise deliverable response  
   - 5 one-line comments + 2 suggestions
   - expected: YAML non-null + notify success
3. Case C: full normal flow  
   - read request -> review -> `reviewer_finalize.sh` completion
   - expected: no session reset before notify

Run each case 3 times (`A1..A3, B1..B3, C1..C3`).

## Record format
Append each run in `memory/session_YYYYMMDD.md`:
- timestamp
- case id
- request_id/task_id
- codex model (`high` or `xhigh`)
- success/failure (`yaml_non_null`, `notify_sent`, `session_alive`)
- token usage snapshot (if available)
- fallback used (`minimal_revise` yes/no)

## Gate criteria
- **Pass**: 10 consecutive review requests complete with
  - YAML non-null
  - notify sent
  - no reviewer session reset before completion
- **Fail**: any single recurrence of stall pattern
  - action: switch Reviewer launch to Claude Code or keep Codex with stricter fallback-only mode

## Escalation rule
- On fail, Senior logs incident in `dashboard.md` (`Action Required`) and notifies Manager with:
  - failed case id
  - last successful case id
  - model in use
  - whether `reviewer_finalize.sh` was used
