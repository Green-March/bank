#!/usr/bin/env bash
set -euo pipefail
# Usage: senior_clear_junior.sh <pane_id> <follow_up_message>
# Sends queue-idle reset + /clear to a Junior pane, then sends follow-up message.
# This avoids stale tasks being re-run after verdict: ok.
pane_id="${1:?Usage: senior_clear_junior.sh <pane_id> <message>}"
message="${2:?Usage: senior_clear_junior.sh <pane_id> <message>}"

# Determine junior number from startup message and reset the corresponding task queue.
junior_num=""
if [[ "$message" =~ junior([0-9]+) ]]; then
    junior_num="${BASH_REMATCH[1]}"
fi

if [ -n "$junior_num" ]; then
    script_dir="$(cd "$(dirname "$0")" && pwd)"
    queue_file="${script_dir}/../queue/tasks/junior${junior_num}.yaml"
    if [ -f "$queue_file" ]; then
        cat > "$queue_file" << 'YAML'
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
YAML
        echo "Reset $queue_file to idle"
    fi
fi

tmux send-keys -t "${pane_id}" "/clear"
sleep 1
tmux send-keys -t "${pane_id}" Enter
sleep 1
tmux send-keys -t "${pane_id}" "${message}"
sleep 1
tmux send-keys -t "${pane_id}" Enter

echo "senior_clear_junior: cleared ${pane_id} and sent follow-up"
