#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
LOG_DIR="${PROJECT_DIR}/.claude/hooks/logs"
LOG_FILE="${LOG_DIR}/deny-check.log"

log_block() {
  mkdir -p "${LOG_DIR}" 2>/dev/null || true
  {
    printf '[%s] BLOCKED\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
    printf 'reason: %s\n' "$1"
    printf 'command: %s\n' "$2"
    printf '\n'
  } >> "${LOG_FILE}" 2>/dev/null || true
}

# Emergency override for controlled environments only.
if [[ "${CLAUDE_HOOK_ALLOW_RISKY:-0}" == "1" ]]; then
  exit 0
fi

INPUT_JSON="$(cat || true)"
if [[ -z "${INPUT_JSON//[[:space:]]/}" ]]; then
  exit 0
fi

if command -v jq >/dev/null 2>&1; then
  TOOL_NAME="$(jq -r '.tool_name // .tool // .name // empty' <<< "${INPUT_JSON}")"
  case "${TOOL_NAME}" in
    Bash|bash) ;;
    *) exit 0 ;;
  esac

  CMD="$(
    jq -r '.tool_input.command // .input.command // .arguments.command // .command // .tool_input.cmd // .input.cmd // .arguments.cmd // .cmd // empty' \
      <<< "${INPUT_JSON}"
  )"
else
  # Fallback parser for minimal environments without jq.
  if ! grep -Eiq '"(tool_name|tool|name)"[[:space:]]*:[[:space:]]*"(Bash|bash)"' <<< "${INPUT_JSON}"; then
    exit 0
  fi
  CMD="$(sed -nE 's/.*"(command|cmd)"[[:space:]]*:[[:space:]]*"(([^"\\]|\\.)*)".*/\2/p' <<< "${INPUT_JSON}" | head -n1)"
  CMD="${CMD//\\\"/\"}"
  CMD="${CMD//\\\\/\\}"
  CMD="${CMD//\\n/$'\n'}"
fi

if [[ -z "${CMD}" || "${CMD}" == "null" ]]; then
  echo "BLOCKED: could not parse command from hook payload." >&2
  exit 2
fi

CMD_ONE_LINE="$(printf '%s' "${CMD}" | tr '\n' ' ' | tr -s ' ')"

block_if_match() {
  local pattern="$1"
  local reason="$2"
  if grep -Eiq -- "${pattern}" <<< "${CMD_ONE_LINE}"; then
    log_block "${reason}" "${CMD_ONE_LINE}"
    echo "BLOCKED: ${reason}" >&2
    echo "command: ${CMD_ONE_LINE}" >&2
    exit 2
  fi
}

# Privilege escalation and host-level mutation.
block_if_match '(^|[;&|[:space:]])sudo([[:space:]]|$)' \
  "sudo is not allowed."
block_if_match '(^|[;&|[:space:]])(shutdown|reboot|halt|poweroff)([[:space:]]|$)' \
  "host shutdown/reboot commands are not allowed."

# Destructive filesystem/device operations.
block_if_match '(^|[;&|[:space:]])rm([[:space:]]|$).*(--no-preserve-root|(^|[[:space:]])/($|[[:space:]])|[[:space:]]/\*|[[:space:]]~/?|\s-rf\b|\s-fr\b)' \
  "destructive rm pattern detected."
block_if_match '(^|[;&|[:space:]])(shred|mkfs|fdisk|parted|dd)([[:space:]]|$)' \
  "disk or irreversible destructive command detected."
block_if_match '(^|[;&|[:space:]])(chmod|chown)[[:space:]].*(-R[[:space:]]+)?777([[:space:]]|$)' \
  "dangerous recursive permission/ownership mutation detected."

# Remote code execution patterns.
block_if_match '(^|[;&|[:space:]])(curl|wget)[[:space:]].*([|>][[:space:]]*)(sh|bash|zsh)([[:space:]]|$)' \
  "piped remote shell execution detected."
block_if_match 'base64[[:space:]]+-d[[:space:]]*\|[[:space:]]*(sh|bash|zsh)([[:space:]]|$)' \
  "base64-decoded shell execution detected."
block_if_match ':\(\)\{[[:space:]]*:[[:space:]]*\|[[:space:]]*:[[:space:]]*&[[:space:]]*\};:' \
  "fork bomb pattern detected."

# Network pivoting or exfiltration primitives.
block_if_match '(^|[;&|[:space:]])(nc|ncat|netcat|socat|telnet|ssh|scp|sftp)([[:space:]]|$)' \
  "raw network tunnel/remote shell command detected."

# Reduce stealthy global environment mutation.
block_if_match '(^|[;&|[:space:]])git[[:space:]]+config[[:space:]]+--global([[:space:]]|$)' \
  "global git config mutation is not allowed."

# Senior/Reviewer role boundary enforcement: audit and block direct file writes
# to implementation directories (skills/, src/, tests/, data/).
# This catches cat/tee/cp/mv/sed/python writes by Senior (Codex) agents.
AGENT_ROLE="${AGENT_ROLE:-}"
if [[ -z "${AGENT_ROLE}" ]]; then
  # Try to resolve role from tmux pane option if env var is not set.
  AGENT_ROLE="$(tmux display-message -p -t "${TMUX_PANE:-}" '#{@agent_role}' 2>/dev/null || true)"
fi

if [[ "${AGENT_ROLE}" == "senior" || "${AGENT_ROLE}" == "reviewer" ]]; then
  # Block direct file writes to implementation directories.
  block_if_match '(cat|tee|cp|mv|sed|awk|printf|echo)[[:space:]].*>[[:space:]]*(skills/|src/|tests/|data/)' \
    "Role boundary violation: ${AGENT_ROLE} attempted direct file write to implementation directory."

  # Block python/pytest execution (Senior should delegate to Junior).
  block_if_match '(^|[;&|[:space:]])(python3?|pytest|pip)[[:space:]]' \
    "Role boundary violation: ${AGENT_ROLE} attempted direct code/test execution."

  # Block patch/apply_patch to implementation files.
  block_if_match '(^|[;&|[:space:]])(patch|git[[:space:]]+apply)[[:space:]]' \
    "Role boundary violation: ${AGENT_ROLE} attempted direct patch application."

  # Audit log for any write redirections to non-queue/non-dashboard paths.
  if grep -Eiq '>[[:space:]]*(skills/|src/|tests/|data/|\.py|\.js|\.ts)' <<< "${CMD_ONE_LINE}"; then
    log_block "AUDIT: ${AGENT_ROLE} write attempt to implementation path" "${CMD_ONE_LINE}"
  fi
fi

exit 0
