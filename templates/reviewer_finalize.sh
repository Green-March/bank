#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  reviewer_finalize.sh --mode plan|deliverable --output <yaml_path> --verdict <ok|revise> --senior-pane <pane_id> [options]

Plan review options:
  --request-id <id>
  --comment <text>              (repeatable)
  --suggestion <text>           (repeatable)

Deliverable review options:
  --request-id <id>             (required)
  --task-id <id>                (required)
  --junior-id <id>              (required)
  --data-integrity <text>       (required)
  --source-traceability <text>  (required)
  --analytical-validity <text>  (required)
  --clarity <text>              (required)
  --risk-disclosure <text>      (required)
  --suggestion <text>           (repeatable)
  --status <value>              (default: completed)
  --timestamp <value>           (default: current local time)

Notification options:
  --notify-message <text>       (default depends on mode)
EOF
}

yaml_quote() {
  local value="${1-}"
  value="${value//$'\r'/ }"
  value="${value//$'\n'/ }"
  value="${value//\'/\'\'}"
  printf "'%s'" "${value}"
}

emit_list() {
  local indent="$1"
  shift || true
  if [[ "$#" -eq 0 ]]; then
    printf '%s[]\n' "${indent}"
    return 0
  fi
  local item
  for item in "$@"; do
    printf '%s- %s\n' "${indent}" "$(yaml_quote "${item}")"
  done
}

require_value() {
  local flag="$1"
  local value="${2-}"
  if [[ -z "${value}" ]]; then
    echo "ERROR: ${flag} is required." >&2
    exit 2
  fi
}

mode=""
output=""
verdict=""
senior_pane=""
notify_message=""

request_id=""
task_id=""
junior_id=""
data_integrity=""
source_traceability=""
analytical_validity=""
clarity=""
risk_disclosure=""
status="completed"
timestamp="$(date '+%Y-%m-%d %H:%M:%S')"

declare -a comments=()
declare -a suggestions=()

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --mode)
      mode="${2-}"
      shift 2
      ;;
    --output)
      output="${2-}"
      shift 2
      ;;
    --verdict)
      verdict="${2-}"
      shift 2
      ;;
    --senior-pane)
      senior_pane="${2-}"
      shift 2
      ;;
    --notify-message)
      notify_message="${2-}"
      shift 2
      ;;
    --request-id)
      request_id="${2-}"
      shift 2
      ;;
    --task-id)
      task_id="${2-}"
      shift 2
      ;;
    --junior-id)
      junior_id="${2-}"
      shift 2
      ;;
    --comment)
      comments+=("${2-}")
      shift 2
      ;;
    --suggestion)
      suggestions+=("${2-}")
      shift 2
      ;;
    --data-integrity)
      data_integrity="${2-}"
      shift 2
      ;;
    --source-traceability)
      source_traceability="${2-}"
      shift 2
      ;;
    --analytical-validity)
      analytical_validity="${2-}"
      shift 2
      ;;
    --clarity)
      clarity="${2-}"
      shift 2
      ;;
    --risk-disclosure)
      risk_disclosure="${2-}"
      shift 2
      ;;
    --status)
      status="${2-}"
      shift 2
      ;;
    --timestamp)
      timestamp="${2-}"
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

require_value "--mode" "${mode}"
require_value "--output" "${output}"
require_value "--verdict" "${verdict}"
require_value "--senior-pane" "${senior_pane}"

if [[ "${mode}" != "plan" && "${mode}" != "deliverable" ]]; then
  echo "ERROR: --mode must be plan or deliverable." >&2
  exit 2
fi

if [[ "${verdict}" != "ok" && "${verdict}" != "revise" ]]; then
  echo "ERROR: --verdict must be ok or revise." >&2
  exit 2
fi

if [[ "${mode}" == "deliverable" ]]; then
  require_value "--request-id" "${request_id}"
  require_value "--task-id" "${task_id}"
  require_value "--junior-id" "${junior_id}"
  require_value "--data-integrity" "${data_integrity}"
  require_value "--source-traceability" "${source_traceability}"
  require_value "--analytical-validity" "${analytical_validity}"
  require_value "--clarity" "${clarity}"
  require_value "--risk-disclosure" "${risk_disclosure}"
fi

if [[ -z "${notify_message}" ]]; then
  if [[ "${mode}" == "plan" ]]; then
    notify_message="計画レビュー完了。queue/review/reviewer_to_senior.yaml を読んでください"
  else
    notify_message="成果物レビュー完了。queue/review/reviewer_to_junior.yaml を読んでください"
  fi
fi

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

{
  if [[ "${mode}" == "plan" ]]; then
    echo "plan_review_response:"
    if [[ -n "${request_id}" ]]; then
      printf '  request_id: %s\n' "$(yaml_quote "${request_id}")"
    fi
    printf '  verdict: %s\n' "$(yaml_quote "${verdict}")"

    if [[ "${#comments[@]}" -eq 0 ]]; then
      echo "  comments: []"
    else
      echo "  comments:"
      emit_list "    " "${comments[@]}"
    fi

    if [[ "${#suggestions[@]}" -eq 0 ]]; then
      echo "  suggested_changes: []"
    else
      echo "  suggested_changes:"
      emit_list "    " "${suggestions[@]}"
    fi
  else
    echo "review_response:"
    echo "  request_type: deliverable_review_response"
    echo "  review_type: deliverable"
    printf '  request_id: %s\n' "$(yaml_quote "${request_id}")"
    printf '  task_id: %s\n' "$(yaml_quote "${task_id}")"
    printf '  junior_id: %s\n' "$(yaml_quote "${junior_id}")"
    printf '  verdict: %s\n' "$(yaml_quote "${verdict}")"
    echo "  comments:"
    printf '    data_integrity: %s\n' "$(yaml_quote "${data_integrity}")"
    printf '    source_traceability: %s\n' "$(yaml_quote "${source_traceability}")"
    printf '    analytical_validity: %s\n' "$(yaml_quote "${analytical_validity}")"
    printf '    clarity: %s\n' "$(yaml_quote "${clarity}")"
    printf '    risk_disclosure: %s\n' "$(yaml_quote "${risk_disclosure}")"

    if [[ "${#suggestions[@]}" -eq 0 ]]; then
      echo "  suggested_changes: []"
    else
      echo "  suggested_changes:"
      emit_list "    " "${suggestions[@]}"
    fi

    printf '  status: %s\n' "$(yaml_quote "${status}")"
    printf '  timestamp: %s\n' "$(yaml_quote "${timestamp}")"
  fi
} > "${tmp_file}"

mv "${tmp_file}" "${output}"
tmp_file=""

tmux send-keys -t "${senior_pane}" "${notify_message}"
sleep 1
tmux send-keys -t "${senior_pane}" Enter

echo "reviewer finalize: wrote ${output} and notified ${senior_pane}"
