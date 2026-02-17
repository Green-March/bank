#!/usr/bin/env bash
set -euo pipefail

# SessionStart(clear) hook for Claude junior panes.
# Inject junior role instructions into context only for junior panes.

if ! command -v tmux >/dev/null 2>&1; then
  exit 0
fi

if [ -z "${TMUX_PANE:-}" ]; then
  exit 0
fi

pane_title="$(tmux display-message -p -t "${TMUX_PANE}" '#{pane_title}' 2>/dev/null || true)"
case "${pane_title}" in
  junior1|junior2|junior3|junior)
    instruction_path="${CLAUDE_PROJECT_DIR:-$PWD}/instructions/junior.md"
    if [ -f "${instruction_path}" ]; then
      printf '%s\n\n' "[SessionStart/clear hook] Reloading junior instructions from instructions/junior.md"
      cat "${instruction_path}"
    fi
    ;;
  *)
    ;;
esac
