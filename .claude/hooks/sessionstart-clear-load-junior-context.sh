#!/usr/bin/env bash
set -euo pipefail

project_dir="${CLAUDE_PROJECT_DIR:-$PWD}"
log_dir="${project_dir}/.claude/hooks/logs"
log_file="${log_dir}/sessionstart-clear.log"
runtime_map_file="${project_dir}/.claude/runtime/agent-pane-map.tsv"

log() {
  mkdir -p "${log_dir}" 2>/dev/null || true
  printf '[%s] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" >> "${log_file}" 2>/dev/null || true
}

normalize_role() {
  case "$1" in
    manager|senior|junior|junior1|junior2|junior3|reviewer)
      printf '%s' "$1"
      return 0
      ;;
    *)
      return 1
      ;;
  esac
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

role_from_env() {
  normalize_role "${AGENT_ROLE:-}" 2>/dev/null || return 1
}

role_from_tmux_option() {
  local pane_id="$1"
  local raw
  raw="$(tmux display-message -p -t "${pane_id}" '#{@agent_role}' 2>/dev/null || true)"
  normalize_role "${raw}" 2>/dev/null || return 1
}

role_from_runtime_map() {
  local pane_id="$1"
  local raw=""

  if [ ! -f "${runtime_map_file}" ]; then
    return 1
  fi

  raw="$(awk -v pane="${pane_id}" '
    $1 == pane { print $2; exit }
    $2 == pane { print $1; exit }
  ' "${runtime_map_file}" 2>/dev/null || true)"
  normalize_role "${raw}" 2>/dev/null || return 1
}

role_from_pane_title() {
  local pane_id="$1"
  local raw
  raw="$(tmux display-message -p -t "${pane_id}" '#{pane_title}' 2>/dev/null || true)"
  normalize_role "${raw}" 2>/dev/null || return 1
}

role_from_layout() {
  local pane_id="$1"
  local target_window
  target_window="$(tmux display-message -p -t "${pane_id}" '#{session_name}:#{window_index}' 2>/dev/null || true)"
  if [ -z "${target_window}" ]; then
    return 1
  fi

  local pane_table
  pane_table="$(tmux list-panes -t "${target_window}" -F '#{pane_id} #{pane_left} #{pane_top}' 2>/dev/null || true)"
  if [ -z "${pane_table}" ]; then
    return 1
  fi

  local left_values left_count left1 left2 left3 left4 target_left target_top
  left_values="$(printf '%s\n' "${pane_table}" | awk '{print $2}' | sort -n | uniq)"
  left_count="$(printf '%s\n' "${left_values}" | awk 'NF { c++ } END { print c + 0 }')"
  if [ "${left_count}" -lt 4 ]; then
    return 1
  fi

  left1="$(printf '%s\n' "${left_values}" | sed -n '1p')"
  left2="$(printf '%s\n' "${left_values}" | sed -n '2p')"
  left3="$(printf '%s\n' "${left_values}" | sed -n '3p')"
  left4="$(printf '%s\n' "${left_values}" | sed -n '4p')"

  target_left="$(printf '%s\n' "${pane_table}" | awk -v id="${pane_id}" '$1 == id { print $2; exit }')"
  target_top="$(printf '%s\n' "${pane_table}" | awk -v id="${pane_id}" '$1 == id { print $3; exit }')"
  if [ -z "${target_left}" ] || [ -z "${target_top}" ]; then
    return 1
  fi

  case "${target_left}" in
    "${left1}")
      printf 'manager'
      return 0
      ;;
    "${left2}")
      printf 'senior'
      return 0
      ;;
    "${left3}")
      local col3_top_first
      col3_top_first="$(printf '%s\n' "${pane_table}" | awk -v left="${left3}" '$2 == left { print $3 }' | sort -n | sed -n '1p')"
      if [ -z "${col3_top_first}" ]; then
        return 1
      fi
      if [ "${target_top}" = "${col3_top_first}" ]; then
        printf 'junior1'
      else
        printf 'junior2'
      fi
      return 0
      ;;
    "${left4}")
      local col4_top_first
      col4_top_first="$(printf '%s\n' "${pane_table}" | awk -v left="${left4}" '$2 == left { print $3 }' | sort -n | sed -n '1p')"
      if [ -z "${col4_top_first}" ]; then
        return 1
      fi
      if [ "${target_top}" = "${col4_top_first}" ]; then
        printf 'junior3'
      else
        printf 'reviewer'
      fi
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

resolve_role() {
  local pane_id="$1"
  local role=""

  role="$(role_from_env || true)"
  if [ -n "${role}" ]; then
    log "role-resolve: source=env role='${role}' pane='${pane_id}'"
    printf '%s' "${role}"
    return 0
  fi

  role="$(role_from_tmux_option "${pane_id}" || true)"
  if [ -n "${role}" ]; then
    log "role-resolve: source=tmux_option role='${role}' pane='${pane_id}'"
    printf '%s' "${role}"
    return 0
  fi

  role="$(role_from_runtime_map "${pane_id}" || true)"
  if [ -n "${role}" ]; then
    log "role-resolve: source=runtime_map role='${role}' pane='${pane_id}'"
    printf '%s' "${role}"
    return 0
  fi

  role="$(role_from_pane_title "${pane_id}" || true)"
  if [ -n "${role}" ]; then
    log "role-resolve: source=pane_title role='${role}' pane='${pane_id}'"
    printf '%s' "${role}"
    return 0
  fi

  role="$(role_from_layout "${pane_id}" || true)"
  if [ -n "${role}" ]; then
    log "role-resolve: source=layout role='${role}' pane='${pane_id}'"
    printf '%s' "${role}"
    return 0
  fi

  return 1
}

build_context_for_role() {
  local role="$1"
  local bootstrap_path=""
  local core_path=""

  case "${role}" in
    junior1|junior2|junior3)
      bootstrap_path="${project_dir}/instructions/${role}.md"
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

  local role
  role="$(resolve_role "${pane_id}" || true)"

  local context
  context="$(build_context_for_role "${role}" || true)"
  if [ -z "${context}" ]; then
    local pane_title pane_option
    pane_title="$(tmux display-message -p -t "${pane_id}" '#{pane_title}' 2>/dev/null || true)"
    pane_option="$(tmux display-message -p -t "${pane_id}" '#{@agent_role}' 2>/dev/null || true)"
    if [ -z "${role}" ]; then
      log "skip: role unresolved (pane='${pane_id}' env='${AGENT_ROLE:-}' opt='${pane_option}' title='${pane_title}')"
    else
      log "skip: non-target role '${role}' (pane='${pane_id}' title='${pane_title}')"
    fi
    exit 0
  fi

  if ! printf '%s' "${context}" | emit_json; then
    exit 0
  fi
  log "success: emitted SessionStart additionalContext for pane='${pane_id}' role='${role}'"
}

main "$@"
