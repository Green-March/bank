#!/bin/bash
# BANK startup script
# Usage:
#   ./go.sh
#   ./go.sh -s
#   ./go.sh --target /path/to/workspace

set -e

ORIGINAL_DIR="$(pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LANG_SETTING="ja"
SHELL_SETTING="bash"
SETUP_ONLY=false
OPEN_TERMINAL=false
SHELL_OVERRIDE=""
TARGET_OVERRIDE=""

if [ -f "./config/settings.yaml" ]; then
    LANG_SETTING=$(grep "^language:" ./config/settings.yaml 2>/dev/null | awk '{print $2}' || echo "ja")
    SHELL_SETTING=$(grep "^shell:" ./config/settings.yaml 2>/dev/null | awk '{print $2}' || echo "bash")
fi

log_info() { echo -e "[INFO] $1"; }
log_success() { echo -e "[OK] $1"; }
log_warn() { echo -e "[WARN] $1"; }

usage() {
    echo ""
    echo "BANK startup script"
    echo ""
    echo "Usage: ./go.sh [options]"
    echo "Options:"
    echo "  -s, --setup-only       Create tmux layout only"
    echo "  -t, --terminal         Open Windows Terminal tab (WSL)"
    echo "  -shell, --shell <sh>   Override shell (bash|zsh)"
    echo "  --target <dir>         Target workspace directory"
    echo "  -h, --help             Show this help"
    echo ""
    exit 0
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -s|--setup-only)
            SETUP_ONLY=true
            shift
            ;;
        -t|--terminal)
            OPEN_TERMINAL=true
            shift
            ;;
        -shell|--shell)
            if [[ -n "$2" && "$2" != -* ]]; then
                SHELL_OVERRIDE="$2"
                shift 2
            else
                echo "Error: -shell requires bash or zsh"
                exit 1
            fi
            ;;
        --target)
            if [[ -n "$2" && "$2" != -* ]]; then
                TARGET_OVERRIDE="$2"
                shift 2
            else
                echo "Error: --target requires directory path"
                exit 1
            fi
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use -h for help"
            exit 1
            ;;
    esac
done

if [ -n "$SHELL_OVERRIDE" ]; then
    if [[ "$SHELL_OVERRIDE" == "bash" || "$SHELL_OVERRIDE" == "zsh" ]]; then
        SHELL_SETTING="$SHELL_OVERRIDE"
    else
        echo "Error: -shell requires bash or zsh"
        exit 1
    fi
fi

if [ -n "$TARGET_OVERRIDE" ]; then
    TARGET_DIR="$TARGET_OVERRIDE"
else
    TARGET_DIR="$ORIGINAL_DIR"
fi

if [ ! -d "$TARGET_DIR" ]; then
    echo "Error: target directory does not exist: $TARGET_DIR"
    exit 1
fi

mkdir -p ./config
cat > ./config/target.yaml <<EOF_TARGET
workspace:
  path: "$TARGET_DIR"
EOF_TARGET

log_info "Workspace target: $TARGET_DIR"

log_info "Cleaning existing tmux session..."
tmux kill-session -t multiagent 2>/dev/null && log_info "  - multiagent removed" || log_info "  - no existing session"

mkdir -p ./logs
BACKUP_DIR="./logs/backup_$(date '+%Y%m%d_%H%M%S')"
NEED_BACKUP=false
if [ -f "./dashboard.md" ] && grep -q "req_" "./dashboard.md" 2>/dev/null; then
    NEED_BACKUP=true
fi

if [ "$NEED_BACKUP" = true ]; then
    mkdir -p "$BACKUP_DIR" || true
    cp "./dashboard.md" "$BACKUP_DIR/" 2>/dev/null || true
    cp -r "./queue/reports" "$BACKUP_DIR/" 2>/dev/null || true
    cp -r "./queue/tasks" "$BACKUP_DIR/" 2>/dev/null || true
    cp -r "./queue/review" "$BACKUP_DIR/" 2>/dev/null || true
    cp "./queue/paper_to_senior.yaml" "$BACKUP_DIR/" 2>/dev/null || true
    log_info "Backup created: $BACKUP_DIR"
fi

log_info "Resetting queue files..."
mkdir -p ./queue/tasks ./queue/reports ./queue/review

for i in {1..3}; do
    cat > ./queue/tasks/junior${i}.yaml <<EOF
# Junior ${i} task file
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
EOF
done

for i in {1..3}; do
    cat > ./queue/reports/junior${i}_report.yaml <<EOF
worker_id: junior${i}
task_id: null
ticker: null
analysis_type: null
timestamp: ""
status: idle
result: null
quality_check_required: true
EOF
done

cat > ./queue/paper_to_senior.yaml <<'EOF_QUEUE'
queue: []
EOF_QUEUE

cat > ./queue/review/junior_to_reviewer.yaml <<'EOF_R1'
review_request: null
review_followup: null
EOF_R1

cat > ./queue/review/reviewer_to_junior.yaml <<'EOF_R2'
review_response: null
EOF_R2

cat > ./queue/review/senior_to_reviewer.yaml <<'EOF_R3'
plan_review_request: null
EOF_R3

cat > ./queue/review/reviewer_to_senior.yaml <<'EOF_R4'
plan_review_response: null
EOF_R4

log_success "Queue reset complete"

log_info "Initializing dashboard..."
TIMESTAMP=$(date "+%Y-%m-%d %H:%M")
cat > ./dashboard.md <<EOF_DASH
# Status Dashboard
Last Updated: ${TIMESTAMP}

## Action Required
None

## Intake
None

## Data Collection
None

## Parsing / Normalization
None

## Metrics / Valuation
None

## Report Drafting
None

## Risk / QA
None

## Completed Today
| Time | Ticker | Task | Result |
|------|--------|------|--------|

## Skill Candidates
None

## Questions
None
EOF_DASH

log_success "Dashboard initialized"

log_info "Creating tmux session (multiagent, 6 panes)..."
if ! tmux new-session -d -s multiagent 2>/dev/null; then
    echo "Failed to create tmux session 'multiagent'"
    exit 1
fi

left_root="$(tmux list-panes -t multiagent:0 -F '#{pane_id}' | head -1)"
right_root="$(tmux split-window -h -t "$left_root" -P -F '#{pane_id}')"
senior_pane="$(tmux split-window -h -t "$left_root" -P -F '#{pane_id}')"

right_right_top="$(tmux split-window -h -t "$right_root" -P -F '#{pane_id}')"
right_left_top="$right_root"
right_left_bottom="$(tmux split-window -v -t "$right_left_top" -P -F '#{pane_id}')"
right_right_bottom="$(tmux split-window -v -t "$right_right_top" -P -F '#{pane_id}')"

generate_prompt() {
    local label="$1"
    local color="$2"
    local shell_type="$3"
    if [ "$shell_type" == "zsh" ]; then
        echo "(%F{${color}}%B${label}%b%f) %F{green}%B%~%b%f%# "
    else
        local color_code
        case "$color" in
            red) color_code="1;31" ;;
            green) color_code="1;32" ;;
            yellow) color_code="1;33" ;;
            blue) color_code="1;34" ;;
            magenta) color_code="1;35" ;;
            cyan) color_code="1;36" ;;
            *) color_code="1;37" ;;
        esac
        echo "(\\[\\033[${color_code}m\\]${label}\\[\\033[0m\\]) \\[\\033[1;32m\\]\\w\\[\\033[0m\\]\\$ "
    fi
}

manager_pane="$left_root"
junior1_pane="$right_left_top"
junior2_pane="$right_left_bottom"
junior3_pane="$right_right_top"
reviewer_pane="$right_right_bottom"

set_pane() {
    local pane_id="$1"
    local label="$2"
    local color="$3"
    local prompt
    prompt="$(generate_prompt "$label" "$color" "$SHELL_SETTING")"
    tmux select-pane -t "$pane_id" -T "$label"
    tmux send-keys -t "$pane_id" "cd \"$TARGET_DIR\" && export PS1='${prompt}' && clear" Enter
}

set_pane "$manager_pane" "manager" "magenta"
set_pane "$senior_pane" "senior" "red"
set_pane "$junior1_pane" "junior1" "blue"
set_pane "$junior2_pane" "junior2" "blue"
set_pane "$junior3_pane" "junior3" "blue"
set_pane "$reviewer_pane" "reviewer" "yellow"

log_success "Tmux session ready"

if [ "$SETUP_ONLY" = false ]; then
    log_info "Launching agents..."

    tmux send-keys -t "$manager_pane" "MAX_THINKING_TOKENS=0 claude --model opus --dangerously-skip-permissions" Enter
    tmux send-keys -t "$senior_pane" "claude --model opus --dangerously-skip-permissions" Enter
    tmux send-keys -t "$junior1_pane" "claude --model opus --dangerously-skip-permissions" Enter
    tmux send-keys -t "$junior2_pane" "claude --model opus --dangerously-skip-permissions" Enter
    tmux send-keys -t "$junior3_pane" "claude --model opus --dangerously-skip-permissions" Enter
    tmux send-keys -t "$reviewer_pane" "codex" Enter

    log_success "Agents launched"

    sleep 5

    send_msg() {
        local pane="$1"
        local msg="$2"
        tmux send-keys -t "$pane" "$msg"
        sleep 1
        tmux send-keys -t "$pane" Enter
    }

    send_msg "$manager_pane" "instructions/manager.md を読んで役割を理解してください。"
    send_msg "$senior_pane" "instructions/senior.md を読んで役割を理解してください。"
    send_msg "$junior1_pane" "instructions/junior.md を読んで役割を理解してください。あなたはjunior1です。"
    send_msg "$junior2_pane" "instructions/junior.md を読んで役割を理解してください。あなたはjunior2です。"
    send_msg "$junior3_pane" "instructions/junior.md を読んで役割を理解してください。あなたはjunior3です。"
    send_msg "$reviewer_pane" "instructions/reviewer.md を読んで役割を理解してください。"
fi

log_info "Session layout: multiagent (6 panes)"

if [ "$SETUP_ONLY" = true ]; then
    log_warn "Setup-only mode: agents not launched"
fi

echo ""
echo "Next steps:"
echo "  tmux attach-session -t multiagent"
echo ""

if [ "$OPEN_TERMINAL" = true ]; then
    if command -v wt.exe &> /dev/null; then
        wt.exe -w 0 new-tab wsl.exe -e bash -c "tmux attach-session -t multiagent"
        log_success "Windows Terminal opened"
    else
        log_warn "wt.exe not found; attach manually"
    fi
fi
