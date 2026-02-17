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
