#!/usr/bin/env bash
set -euo pipefail
# Usage: senior_clear_junior.sh <pane_id> <follow_up_message>
# Sends /clear to a Junior pane, waits for session reset, then sends a follow-up message.
# This ensures Junior does not stall on an empty prompt after /clear.
pane_id="${1:?Usage: senior_clear_junior.sh <pane_id> <message>}"
message="${2:?Usage: senior_clear_junior.sh <pane_id> <message>}"

tmux send-keys -t "${pane_id}" "/clear" && sleep 1 && tmux send-keys -t "${pane_id}" Enter
sleep 5
tmux send-keys -t "${pane_id}" "${message}" && sleep 1 && tmux send-keys -t "${pane_id}" Enter

echo "senior_clear_junior: cleared ${pane_id} and sent follow-up"
