# Fix: Senior が計画立案後「提案」で停止しワークフローを自律実行しない問題

## 問題

Senior（Codex/o4-mini）が Manager から依頼を受けて計画を立案した後、「必要なら...します」「提出用に整形します」と提案するだけで停止し、正規ワークフロー（YAML書き込み → Reviewer通知 → verdict取得 → Junior委任）を自律実行しない。

### 症状の例

```
Senior: 計画を立てました。レビュー観点は以下の通りです。
       必要ならこのまま提出用フォーマットに変換して再提示します。
       （→ 停止。YAML書き込みも通知もしない）
```

## 根本原因

### 1. 計画レビュー提出段階にヘルパースクリプトが存在しない

他の段階には原子化ヘルパーがあり「このスクリプトを実行せよ」と強制されている:

| 段階 | ヘルパー | 指示書での強制 |
|---|---|---|
| Reviewer のレビュー完了 | `reviewer_finalize.sh` | 「手書き禁止、必ずスクリプト使用」 |
| Senior のタスク完了処理 | `senior_clear_junior.sh` | 「/clear単独禁止、必ずスクリプト使用」 |
| **Senior の計画レビュー提出** | **なし** | **YAML例を示すだけ** |

ヘルパーがないため、Codex は「計画を書く」ことと「YAMLに書き込んで通知する」ことを別のステップとみなし、後者を実行せずに提案で止まる。

### 2. 指示書に「実行義務」の記述がない

`instructions/senior.md` の計画レビューセクションは YAML の例を示すだけで、「この場で実行せよ」「提案で止まるな」という強制的な指示がなかった。

### 3. 起動時メッセージが禁止事項のみ

`go.sh` の Senior 起動時メッセージは「コード編集・テスト実行を自分でやるな」という禁止のみで、「計画立案後は即座にYAML書き込み+通知を実行せよ」という正の義務がなかった。

### 4. Codex の特性

Codex（o4-mini）は conversational agent として「提案モード」にフォールバックしやすい。明示的な tool/script 指定がない限り、各ステップで確認を求めて停止する傾向がある。

## 修正方針

`reviewer_finalize.sh` / `senior_clear_junior.sh` と同じ設計パターンを適用:
- **ヘルパースクリプト**: 操作（YAML書き込み）+ 通知（send-keys）を1コマンドで原子的に実行
- **指示書の強制化**: スクリプト使用を義務化し、手動実行と提案停止を明示的に禁止
- **起動時メッセージ**: 正の義務（「即座に実行せよ」）を追加

## 修正対象ファイル

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `templates/senior_submit_plan.sh` | 新規作成 | 計画YAML書き込み + Reviewer通知の原子化ヘルパー |
| `instructions/senior.md` | 修正 | 自律実行ルール追加 + 計画レビューセクション書き換え |
| `go.sh` | 修正 | Senior起動時に正の義務メッセージ追加 |
| `config/permissions.yaml` | 修正 | `exec_commands` にヘルパーを追加 |
| `CLAUDE.md` | 修正 | Plan review flow にヘルパー使用を明記 |

## 各ファイルの変更詳細

### 1. ヘルパースクリプト（新規作成）

**パス**: `templates/senior_submit_plan.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
# Usage: senior_submit_plan.sh --reviewer-pane <pane_id> [--plan-file <path>] [--notify-message <text>]
#
# Writes plan review request YAML to queue/review/senior_to_reviewer.yaml
# and notifies Reviewer via tmux send-keys — both in one atomic operation.
#
# YAML source (one of):
#   --plan-file <path>    Read YAML from this file
#   stdin                 If --plan-file is not given, reads from stdin (heredoc)
#
# Example:
#   cat <<'PLAN_EOF' | ./templates/senior_submit_plan.sh --reviewer-pane %108
#   plan_review_request:
#     request_id: req_20260217_012
#     objective: "2780 パイプラインE2Eテスト"
#     ...
#   PLAN_EOF

usage() {
  cat <<'USAGE'
Usage:
  senior_submit_plan.sh --reviewer-pane <pane_id> [--plan-file <path>] [--notify-message <text>]

Writes plan review request YAML to queue/review/senior_to_reviewer.yaml
and notifies Reviewer via tmux send-keys.

YAML source (one of):
  --plan-file <path>    Read YAML from this file
  stdin                 If --plan-file is not given, reads from stdin

Options:
  --reviewer-pane <id>  (required) Reviewer tmux pane ID
  --notify-message <t>  Override notification message
  -h, --help            Show this help
USAGE
}

plan_file=""
reviewer_pane=""
notify_message="計画レビュー依頼です。queue/review/senior_to_reviewer.yaml を読んでください"
output="queue/review/senior_to_reviewer.yaml"

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --plan-file)
      plan_file="${2-}"
      shift 2
      ;;
    --reviewer-pane)
      reviewer_pane="${2-}"
      shift 2
      ;;
    --notify-message)
      notify_message="${2-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "${reviewer_pane}" ]]; then
  echo "ERROR: --reviewer-pane is required." >&2
  exit 2
fi

# Read YAML content
yaml_content=""
if [[ -n "${plan_file}" ]]; then
  if [[ ! -f "${plan_file}" ]]; then
    echo "ERROR: plan file not found: ${plan_file}" >&2
    exit 2
  fi
  yaml_content="$(cat "${plan_file}")"
else
  # Read from stdin
  yaml_content="$(cat)"
fi

if [[ -z "${yaml_content}" ]]; then
  echo "ERROR: plan YAML content is empty." >&2
  exit 2
fi

# Validate that content is not just the null placeholder
if printf '%s' "${yaml_content}" | grep -qE '^plan_review_request:[[:space:]]*null[[:space:]]*$'; then
  echo "ERROR: plan YAML content is null placeholder. Provide actual plan content." >&2
  exit 2
fi

# Atomic write (tmp + mv)
output_dir="$(dirname "${output}")"
mkdir -p "${output_dir}"

tmp_file=""
cleanup() {
  if [[ -n "${tmp_file}" && -f "${tmp_file}" ]]; then
    rm -f "${tmp_file}"
  fi
}
trap cleanup EXIT INT TERM

tmp_file="$(mktemp "${output_dir}/.$(basename "${output}").tmp.XXXXXX")"
printf '%s\n' "${yaml_content}" > "${tmp_file}"
mv "${tmp_file}" "${output}"
tmp_file=""

# Notify Reviewer (Codex single-chained command pattern)
tmux send-keys -t "${reviewer_pane}" "${notify_message}" && sleep 1 && tmux send-keys -t "${reviewer_pane}" Enter

echo "senior_submit_plan: wrote ${output} and notified reviewer (${reviewer_pane})"
```

作成後 `chmod +x` で実行権限を付与すること。

**設計意図**:
- stdin/heredoc 対応: 計画YAMLは大きな構造化データなので、CLIフラグでなく heredoc で渡す
- 空入力・null placeholder を拒否するバリデーション付き
- tmp + mv による原子的書き込み（他エージェントとの競合防止）
- Codex の single chained command パターン（`msg && sleep 1 && Enter`）で通知
- `reviewer_finalize.sh` / `senior_clear_junior.sh` と同じ設計パターン

### 2. Senior 指示書の変更

**パス**: `instructions/senior.md` — 2箇所

**(a) 新セクション追加: YAML frontmatter `---` の直後、`# Senior Instructions` の直前**

```markdown
## 自律実行ルール（必須 — 最優先）
- Manager からの wakeup を受けたら、workflow の全ステップを **自律的に** 実行する。途中で停止して「提案」や「確認」を求めてはならない。
- 計画を立案したら、**その同じターン内で** `./templates/senior_submit_plan.sh` を実行して Reviewer に提出する。
- Junior にタスクを割り当てる際は、**その同じターン内で** report リセット → task YAML 書き込み → send-keys 通知を実行する。
- 以下のフレーズは **使用禁止**: 「必要なら...します」「ご確認ください」「続けてもよろしいですか？」「提出用に整形します」「次ターンで...」。これらは全てワークフロー違反である。
- 唯一の待機ポイントは **Reviewer の verdict 返却** と **Junior の成果物完了報告** のみ。それ以外で停止してはならない。
```

**ポイント**: YAML frontmatter の直後、本文の最初に配置することで、Senior が最初に読む位置に強制ルールを置く。

**(b) 「計画レビュー（必須）」セクションを書き換え**

変更前:
```markdown
## 計画レビュー（必須）
Junior 配賦前に Reviewer 承認を得る。

`queue/review/senior_to_reviewer.yaml` 例:
```yaml
plan_review_request:
  request_id: ...
  ...
```（YAML例のみ）
```

変更後:
```markdown
## 計画レビュー提出（必須 — 提案で止まるな、実行せよ）
Junior 配賦前に Reviewer 承認を得る。

### 手順（全ステップ実行必須 — 計画を立てたら即座に実行）
1. 計画 YAML を構成する（`plan_review_request` ブロック）
2. `./templates/senior_submit_plan.sh` を実行して YAML 書き込み + Reviewer 通知を1コマンドで完了する
3. Reviewer からの verdict を `queue/review/reviewer_to_senior.yaml` で待つ

**禁止**: 計画を「提案」として説明するだけで停止すること。計画を考えたら、その場で下記スクリプトを実行すること。

### 実行例
```bash
cat <<'PLAN_EOF' | ./templates/senior_submit_plan.sh --reviewer-pane <reviewer_pane_id>
plan_review_request:
  request_id: req_20260211_001
  objective: "7203 決算分析"
  scope:
    ticker: "7203"
    timeframe: "5y"
  workplan:
    - id: T1
      owner: junior1
      action: "EDINET/J-Quants 収集"
      output: "data/7203/raw/"
    - id: T2
      owner: junior2
      action: "XBRL 解析と正規化"
      output: "data/7203/parsed/financials.json"
    - id: T3
      owner: junior3
      action: "指標計算とレポート草案"
      output: "projects/7203/report.md"
  quality_criteria:
    - "数値の出典を明示"
    - "前提・制約を記載"
    - "リスク要因を列挙"
PLAN_EOF
```

**重要**: YAML書き込みと send-keys 通知は `senior_submit_plan.sh` で連続実行すること。手書き heredoc で直接 `senior_to_reviewer.yaml` に書き込み、手動で send-keys を実行する方式は禁止。必ずヘルパースクリプトを使用すること。
```

### 3. 起動スクリプトの変更

**パス**: `go.sh` — Senior 起動時メッセージ追加（既存の禁止メッセージの直後）

```bash
# 既存行（変更なし）:
send_msg "$senior_pane" "重要: Senior はコード編集・テスト実行・ファイルI/O・データ処理を絶対に自分で実行してはなりません。..."

# 追加行:
send_msg "$senior_pane" "義務: 計画立案後は ./templates/senior_submit_plan.sh で即座にYAML書き込み+Reviewer通知を実行してください。「提案」や「確認待ち」で停止することは禁止です。workflowの各ステップは承認なしで自律実行してください。"
```

**ポイント**: 既存の禁止メッセージ（「やるな」）と対になる義務メッセージ（「やれ」）を追加。セッション開始のたびに Senior のコンテキストに注入される。

### 4. パーミッション設定の変更

**パス**: `config/permissions.yaml`

`exec_commands` リストに追加:
```yaml
    - ./templates/senior_submit_plan.sh
```

### 5. メイン設定ファイルの変更

**パス**: `CLAUDE.md` — Plan review flow セクション

変更前:
```markdown
## Plan review flow (mandatory)
1. Senior writes plan to `queue/review/senior_to_reviewer.yaml`
2. Reviewer evaluates coverage, risk, feasibility, and data source quality
3. Reviewer writes verdict to `queue/review/reviewer_to_senior.yaml`
4. If `verdict: revise`, senior revises and resubmits
5. If `verdict: ok`, senior assigns junior tasks
```

変更後:
```markdown
## Plan review flow (mandatory)
1. Senior designs the plan (workplan, scope, quality_criteria)
2. Senior executes `./templates/senior_submit_plan.sh` to write plan to `queue/review/senior_to_reviewer.yaml` and notify Reviewer (YAML write + notification in one command, mandatory)
3. Reviewer evaluates coverage, risk, feasibility, and data source quality
4. Reviewer writes verdict to `queue/review/reviewer_to_senior.yaml`
5. If `verdict: revise`, senior revises and resubmits (repeat from step 2)
6. If `verdict: ok`, senior assigns junior tasks
```

## 他プロジェクトへの適用チェックリスト

1. [ ] `templates/senior_submit_plan.sh` をコピーし `chmod +x` する
2. [ ] 出力先パス（`output` 変数）をプロジェクトのキュー構造に合わせて変更する
3. [ ] 通知メッセージ（`notify_message` 変数）をプロジェクトの通知規約に合わせて変更する
4. [ ] Senior の指示書に「自律実行ルール」セクションを追加する（禁止フレーズリストはプロジェクトに合わせて調整）
5. [ ] Senior の指示書の「計画レビュー」セクションをヘルパー使用義務に書き換える
6. [ ] 起動スクリプトに正の義務メッセージ（「即座に実行せよ」）を追加する
7. [ ] パーミッション設定にヘルパースクリプトを追加する
8. [ ] メイン設定ファイルの Plan review flow にヘルパー使用を明記する
9. [ ] テスト: 正常系（heredoc入力）、異常系（空入力、null入力、引数欠落）を確認する

## 一般化: この問題が発生する条件

以下の条件がすべて揃うと同じ問題が発生する:

1. Codex（または他の conversational LLM）がオーケストレーターエージェントとして動作している
2. ワークフローの特定ステップで「YAML書き込み + 他エージェントへの通知」が必要
3. そのステップに原子化ヘルパースクリプトが存在しない
4. 指示書の記述が「YAMLの例」にとどまり、「このスクリプトを実行せよ」という強制的な指示がない
5. 起動時メッセージが禁止事項のみで、正の義務（「即座に実行せよ」）がない

## 設計パターン: 操作+通知の原子化

この修正は BANK プロジェクトで繰り返し適用されている共通パターンの3例目:

| # | 問題 | ヘルパー | 設計 |
|---|---|---|---|
| 1 | Reviewer がレビュー後にYAML書き込み+通知をしない | `reviewer_finalize.sh` | YAML生成 + send-keys を1コマンド化 |
| 2 | /clear 後に Junior がフォローアップなしで停止する | `senior_clear_junior.sh` | /clear + sleep + フォローアップを1コマンド化 |
| 3 | **Senior が計画立案後に提案で停止する** | **`senior_submit_plan.sh`** | **stdin→YAML書き込み + send-keys を1コマンド化** |

**パターンの原則**:
- LLM エージェントに「2つの操作を連続で実行せよ」と指示するだけでは不十分
- 2つの操作を1つのスクリプトにまとめ、「このスクリプトを実行せよ」と指示する
- 指示書では手動実行（スクリプトを使わない方法）を明示的に禁止する
- 起動時メッセージでスクリプト使用義務をリマインドする
