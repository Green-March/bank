# Review flow (BANK)

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

## Reviewer completion contract (mandatory)

- Review request is complete only when response YAML is non-null:
  - Plan review: `queue/review/reviewer_to_senior.yaml`
  - Deliverable review: `queue/review/reviewer_to_junior.yaml`
- Receipt-only responses such as "読みました/確認しました" are invalid and must not terminate the review flow.
- If Reviewer is blocked, Reviewer must still write `verdict: revise` with blockers and required follow-up in `suggested_changes`, then notify Senior.
- Reviewer must keep comments concise (deliverable 6観点は各1文、`suggested_changes` は最大2件) and use `./templates/reviewer_finalize.sh`.
- パイプライン経由の成果物レビュー時は、E2E チェックリスト (ステップ間データ整合性・欠損伝播・source_attribution 一貫性・数値精度保持) を適用し、`--e2e-check` オプションで結果を記録する。

## Reviewer stall recovery (mandatory, Senior)

- After notifying Reviewer, Senior performs a single verification read of the expected output YAML (no polling loop).
- If output remains `null` and Reviewer gave only an acknowledgement, Senior sends a corrective message with explicit output contract (`verdict/comments/suggested_changes`), concise-output limits, and `./templates/reviewer_finalize.sh` usage.
- If still unresolved, Senior logs an incident in `dashboard.md` (`Action Required`) and escalates to Manager.
