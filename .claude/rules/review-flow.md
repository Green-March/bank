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

### タイムアウトフォールバックフロー
Senior の `reviewer_timeout_seconds`（120秒、instructions/senior.md で定義）に基づく3段階リカバリ:

1. **120秒後: verification read** — Reviewer 通知から120秒経過後、応答 YAML を1回読む（no polling loop）。
2. **応答 null または acknowledgement-only → corrective message** — 応答が `null` または acknowledgement-only の場合、corrective message を送信。
   - 明示する内容: `verdict/comments/suggested_changes` の出力形式、簡潔な出力制限、`./templates/reviewer_finalize.sh` の使用。
3. **さらに120秒後: Senior 簡易レビュー** — 応答 YAML がまだ `null` または acknowledgement-only の場合、Senior 自身が簡易レビューを実施。
   - 簡易レビューは `verdict/comments/suggested_changes` の出力形式を維持する。
   - Plan review: `queue/review/reviewer_to_senior.yaml` に書き込む。
   - Deliverable review: `queue/review/reviewer_to_junior.yaml` に書き込む。
   - `comments` に「Senior 簡易レビュー（Reviewer タイムアウト）」と明記する。
   - Manager へのエスカレーションは不要（Senior が自律的に解決する）。

### 遅延応答の競合解決ルール
- Senior 簡易レビュー実行後に Reviewer の遅延応答が到着した場合 → **Senior 簡易レビューの verdict を優先**する。
- 遅延した Reviewer 応答は無視する（Junior への二重指示防止）。
- `dashboard.md` の `Action Required` に「Reviewer 遅延応答検知」ログを記録する。
- 次回以降のレビューサイクルは通常フロー（Reviewer 優先）に復帰する。
