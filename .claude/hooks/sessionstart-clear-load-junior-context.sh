#!/usr/bin/env bash
set -euo pipefail

project_dir="${CLAUDE_PROJECT_DIR:-$PWD}"
log_dir="${project_dir}/.claude/hooks/logs"
log_file="${log_dir}/sessionstart-clear.log"

log() {
  mkdir -p "${log_dir}" 2>/dev/null || true
  printf '[%s] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" >> "${log_file}" 2>/dev/null || true
}

resolve_pane_id() {
  if [ -n "${TMUX_PANE:-}" ]; then
    printf '%s' "${TMUX_PANE}"
    return 0
  fi

  if ! command -v tmux >/dev/null 2>&1; then
    return 1
  fi

  local tty_path
  tty_path="$(tty 2>/dev/null || true)"
  if [ -z "${tty_path}" ] || [ "${tty_path}" = "not a tty" ]; then
    return 1
  fi

  tmux list-panes -a -F '#{pane_id} #{pane_tty}' 2>/dev/null \
    | awk -v target="${tty_path}" '$2 == target { print $1; exit }'
}

build_context() {
  local pane_title="$1"
  local bootstrap_path=""
  local core_path=""

  case "${pane_title}" in
    junior1|junior2|junior3)
      bootstrap_path="${project_dir}/instructions/${pane_title}.md"
      core_path="${project_dir}/instructions/junior.md"
      ;;
    junior)
      core_path="${project_dir}/instructions/junior.md"
      ;;
    reviewer)
      core_path="${project_dir}/instructions/reviewer.md"
      ;;
    *)
      return 1
      ;;
  esac

  local context=""
  context+="[SessionStart/clear hook] /clear received. Resetting context. Apply the following as active session instructions."
  context+=$'\n\n'

  if [ -n "${bootstrap_path}" ]; then
    if [ -f "${bootstrap_path}" ]; then
      context+="[${bootstrap_path#${project_dir}/}]"
      context+=$'\n'
      context+="$(cat "${bootstrap_path}")"
      context+=$'\n\n'
    else
      log "bootstrap instruction missing: ${bootstrap_path}"
    fi
  fi

  if [ -f "${core_path}" ]; then
    context+="[${core_path#${project_dir}/}]"
    context+=$'\n'
    context+="$(cat "${core_path}")"
  else
    log "core instruction missing: ${core_path}"
    return 1
  fi

  printf '%s' "${context}"
}

emit_json() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import json,sys; print(json.dumps({"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":sys.stdin.read()}}, ensure_ascii=False))'
    return 0
  fi

  if command -v jq >/dev/null 2>&1; then
    jq -Rs '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":.}}'
    return 0
  fi

  log "skip: cannot emit JSON (python3/jq not found)"
  return 1
}

main() {
  local pane_id
  pane_id="$(resolve_pane_id || true)"
  if [ -z "${pane_id}" ]; then
    log "skip: pane id unresolved (TMUX_PANE='${TMUX_PANE:-}')"
    exit 0
  fi

  local pane_title
  pane_title="$(tmux display-message -p -t "${pane_id}" '#{pane_title}' 2>/dev/null || true)"
  if [ -z "${pane_title}" ]; then
    log "skip: pane title unresolved (pane=${pane_id})"
    exit 0
  fi

  local context
  context="$(build_context "${pane_title}" || true)"
  if [ -z "${context}" ]; then
    log "skip: non-target pane title '${pane_title}'"
    exit 0
  fi

  if ! printf '%s' "${context}" | emit_json; then
    exit 0
  fi
  log "success: emitted SessionStart additionalContext for pane='${pane_id}' title='${pane_title}'"
}

main "$@"
