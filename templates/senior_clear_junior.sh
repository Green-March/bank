#!/usr/bin/env bash
set -euo pipefail
# Usage: senior_clear_junior.sh <pane_id> <follow_up_message> <junior_number>
# Sends queue-idle reset + /clear to a Junior pane, then sends follow-up message.
# This avoids stale tasks being re-run after verdict: ok.

if [[ "$#" -lt 3 || -z "${1-}" || -z "${2-}" || -z "${3-}" ]]; then
  echo "ERROR: 3 arguments required." >&2
  echo "Usage: senior_clear_junior.sh <pane_id> <message> <junior_number>" >&2
  exit 2
fi

pane_id="$1"
message="$2"
junior_num="$3"

if [[ ! "$junior_num" =~ ^[1-3]$ ]]; then
  echo "ERROR: junior_number must be 1, 2, or 3. Got: ${junior_num}" >&2
  exit 2
fi

script_dir="$(cd "$(dirname "$0")" && pwd)"
queue_file="${script_dir}/../queue/tasks/junior${junior_num}.yaml"

if [[ ! -d "$(dirname "${queue_file}")" ]]; then
  echo "ERROR: directory not found: $(dirname "${queue_file}")" >&2
  exit 1
fi

# Atomic write: mktemp + mv
tmp_file=""
cleanup() {
  if [[ -n "${tmp_file}" && -f "${tmp_file}" ]]; then
    rm -f "${tmp_file}"
  fi
}
trap cleanup EXIT INT TERM

tmp_file="$(mktemp "$(dirname "${queue_file}")/.junior${junior_num}.yaml.tmp.XXXXXX")"

cat > "${tmp_file}" << 'YAML'
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
  execution_command: null
YAML

mv "${tmp_file}" "${queue_file}"
tmp_file=""

echo "Reset ${queue_file} to idle"

# Send /clear + follow-up message (4-step tmux sequence)
tmux send-keys -t "${pane_id}" "/clear"
sleep 1
tmux send-keys -t "${pane_id}" Enter
sleep 1
tmux send-keys -t "${pane_id}" "${message}"
sleep 1
tmux send-keys -t "${pane_id}" Enter

echo "senior_clear_junior: cleared ${pane_id} and sent follow-up"
