#!/bin/bash
# ============================================================
# first_setup.sh - BANK 初回セットアップスクリプト
# Ubuntu / WSL / Mac 用環境構築ツール
# ============================================================
# 実行方法:
#   chmod +x first_setup.sh
#   ./first_setup.sh
# ============================================================

set -e

# 色定義
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# アイコン付きログ関数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "\n${CYAN}${BOLD}━━━ $1 ━━━${NC}\n"
}

# スクリプトのディレクトリを取得
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 結果追跡用変数
RESULTS=()
HAS_ERROR=false

echo ""
echo "  ╔══════════════════════════════════════════════════════════════╗"
echo "  ║  BANK インストーラー                               ║"
echo "  ║     Initial Setup Script for Ubuntu / WSL                    ║"
echo "  ╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "  このスクリプトは初回セットアップ用です。"
echo "  依存関係の確認とディレクトリ構造の作成を行います。"
echo ""
echo "  インストール先: $SCRIPT_DIR"
echo ""

# ============================================================
# STEP 1: OS チェック
# ============================================================
log_step "STEP 1: システム環境チェック"

# OS情報を取得
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS_NAME=$NAME
    OS_VERSION=$VERSION_ID
    log_info "OS: $OS_NAME $OS_VERSION"
else
    OS_NAME="Unknown"
    log_warn "OS情報を取得できませんでした"
fi

# WSL チェック
if grep -qi microsoft /proc/version 2>/dev/null; then
    log_info "環境: WSL (Windows Subsystem for Linux)"
    IS_WSL=true
else
    log_info "環境: Native Linux"
    IS_WSL=false
fi

RESULTS+=("システム環境: OK")

# ============================================================
# STEP 2: tmux チェック・インストール
# ============================================================
log_step "STEP 2: tmux チェック"

if command -v tmux &> /dev/null; then
    TMUX_VERSION=$(tmux -V | awk '{print $2}')
    log_success "tmux がインストール済みです (v$TMUX_VERSION)"
    RESULTS+=("tmux: OK (v$TMUX_VERSION)")
else
    log_warn "tmux がインストールされていません"
    echo ""

    # Ubuntu/Debian系かチェック
    if command -v apt-get &> /dev/null; then
        if [ ! -t 0 ]; then
            REPLY="Y"
        else
            read -p "  tmux をインストールしますか? [Y/n]: " REPLY
        fi
        REPLY=${REPLY:-Y}
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            log_info "tmux をインストール中..."
            if ! sudo -n apt-get update -qq 2>/dev/null; then
                if ! sudo apt-get update -qq 2>/dev/null; then
                    log_error "sudo の実行に失敗しました。ターミナルから直接実行してください"
                    RESULTS+=("tmux: インストール失敗 (sudo失敗)")
                    HAS_ERROR=true
                fi
            fi

            if [ "$HAS_ERROR" != true ]; then
                if ! sudo -n apt-get install -y tmux 2>/dev/null; then
                    if ! sudo apt-get install -y tmux 2>/dev/null; then
                        log_error "tmux のインストールに失敗しました"
                        RESULTS+=("tmux: インストール失敗")
                        HAS_ERROR=true
                    fi
                fi
            fi

            if command -v tmux &> /dev/null; then
                TMUX_VERSION=$(tmux -V | awk '{print $2}')
                log_success "tmux インストール完了 (v$TMUX_VERSION)"
                RESULTS+=("tmux: インストール完了 (v$TMUX_VERSION)")
            else
                log_error "tmux のインストールに失敗しました"
                RESULTS+=("tmux: インストール失敗")
                HAS_ERROR=true
            fi
        else
            log_warn "tmux のインストールをスキップしました"
            RESULTS+=("tmux: 未インストール (スキップ)")
            HAS_ERROR=true
        fi
    else
        log_error "apt-get が見つかりません。手動で tmux をインストールしてください"
        echo ""
        echo "  インストール方法:"
        echo "    Ubuntu/Debian: sudo apt-get install tmux"
        echo "    Fedora:        sudo dnf install tmux"
        echo "    macOS:         brew install tmux"
        RESULTS+=("tmux: 未インストール (手動インストール必要)")
        HAS_ERROR=true
    fi
fi

# ============================================================
# STEP 3: tmux マウススクロール設定
# ============================================================
log_step "STEP 3: tmux マウススクロール設定"

TMUX_CONF="$HOME/.tmux.conf"
TMUX_MOUSE_SETTING="set -g mouse on"

if [ -f "$TMUX_CONF" ] && grep -qF "$TMUX_MOUSE_SETTING" "$TMUX_CONF" 2>/dev/null; then
    log_info "tmux マウス設定は既に ~/.tmux.conf に存在します"
else
    log_info "~/.tmux.conf に '$TMUX_MOUSE_SETTING' を追加中..."
    echo "" >> "$TMUX_CONF"
    echo "# マウススクロール有効化 (added by first_setup.sh)" >> "$TMUX_CONF"
    echo "$TMUX_MOUSE_SETTING" >> "$TMUX_CONF"
    log_success "tmux マウス設定を追加しました"
fi

# tmux が起動中の場合は即反映
if command -v tmux &> /dev/null && tmux list-sessions &> /dev/null; then
    log_info "tmux が起動中のため、設定を即反映します..."
    if tmux source-file "$TMUX_CONF" 2>/dev/null; then
        log_success "tmux 設定を再読み込みしました"
    else
        log_warn "tmux 設定の再読み込みに失敗しました（手動で tmux source-file ~/.tmux.conf を実行してください）"
    fi
else
    log_info "tmux は起動していないため、次回起動時に反映されます"
fi

RESULTS+=("tmux マウス設定: OK")

# ============================================================
# STEP 4: Node.js チェック
# ============================================================
log_step "STEP 4: Node.js チェック"

if command -v node &> /dev/null; then
    NODE_VERSION=$(node -v)
    log_success "Node.js がインストール済みです ($NODE_VERSION)"

    # バージョンチェック（18以上推奨）
    NODE_MAJOR=$(echo $NODE_VERSION | cut -d'.' -f1 | tr -d 'v')
    if [ "$NODE_MAJOR" -lt 18 ]; then
        log_warn "Node.js 18以上を推奨します（現在: $NODE_VERSION）"
        RESULTS+=("Node.js: OK (v$NODE_MAJOR - 要アップグレード推奨)")
    else
        RESULTS+=("Node.js: OK ($NODE_VERSION)")
    fi
else
    log_warn "Node.js がインストールされていません"
    echo ""

    # nvm が既にインストール済みか確認
    export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
    if [ -s "$NVM_DIR/nvm.sh" ]; then
        log_info "nvm が既にインストール済みです。Node.js をセットアップ中..."
        \. "$NVM_DIR/nvm.sh"
    else
        # nvm 自動インストール
        if [ ! -t 0 ]; then
            REPLY="Y"
        else
            read -p "  Node.js (nvm経由) をインストールしますか? [Y/n]: " REPLY
        fi
        REPLY=${REPLY:-Y}
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            log_info "nvm をインストール中..."
            curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
            export NVM_DIR="$HOME/.nvm"
            [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
        else
            log_warn "Node.js のインストールをスキップしました"
            echo ""
            echo "  手動でインストールする場合:"
            echo "    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash"
            echo "    source ~/.bashrc"
            echo "    nvm install 20"
            echo ""
            RESULTS+=("Node.js: 未インストール (スキップ)")
            HAS_ERROR=true
        fi
    fi

    # nvm が利用可能なら Node.js をインストール
    if command -v nvm &> /dev/null; then
        log_info "Node.js 20 をインストール中..."
        nvm install 20 || true
        nvm use 20 || true

        if command -v node &> /dev/null; then
            NODE_VERSION=$(node -v)
            log_success "Node.js インストール完了 ($NODE_VERSION)"
            RESULTS+=("Node.js: インストール完了 ($NODE_VERSION)")
        else
            log_error "Node.js のインストールに失敗しました"
            RESULTS+=("Node.js: インストール失敗")
            HAS_ERROR=true
        fi
    elif [ "$HAS_ERROR" != true ]; then
        log_error "nvm のインストールに失敗しました"
        echo ""
        echo "  手動でインストールしてください:"
        echo "    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash"
        echo "    source ~/.bashrc"
        echo "    nvm install 20"
        echo ""
        RESULTS+=("Node.js: 未インストール (nvm失敗)")
        HAS_ERROR=true
    fi
fi

# npm チェック
if command -v npm &> /dev/null; then
    NPM_VERSION=$(npm -v)
    log_success "npm がインストール済みです (v$NPM_VERSION)"
else
    if command -v node &> /dev/null; then
        log_warn "npm が見つかりません（Node.js と一緒にインストールされるはずです）"
    fi
fi

# ============================================================
# STEP 5: Claude Code CLI チェック
# ============================================================
log_step "STEP 5: Claude Code CLI チェック"

if command -v claude &> /dev/null; then
    # バージョン取得を試みる
    CLAUDE_VERSION=$(claude --version 2>/dev/null || echo "unknown")
    log_success "Claude Code CLI がインストール済みです"
    log_info "バージョン: $CLAUDE_VERSION"
    RESULTS+=("Claude Code CLI: OK")
else
    log_warn "Claude Code CLI がインストールされていません"
    echo ""

    if command -v npm &> /dev/null; then
        echo "  インストールコマンド:"
        echo "     npm install -g @anthropic-ai/claude-code"
        echo ""
        if [ ! -t 0 ]; then
            REPLY="Y"
        else
            read -p "  今すぐインストールしますか? [Y/n]: " REPLY
        fi
        REPLY=${REPLY:-Y}
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            log_info "Claude Code CLI をインストール中..."
            npm install -g @anthropic-ai/claude-code

            if command -v claude &> /dev/null; then
                log_success "Claude Code CLI インストール完了"
                RESULTS+=("Claude Code CLI: インストール完了")
            else
                log_error "インストールに失敗しました。パスを確認してください"
                RESULTS+=("Claude Code CLI: インストール失敗")
                HAS_ERROR=true
            fi
        else
            log_warn "インストールをスキップしました"
            RESULTS+=("Claude Code CLI: 未インストール (スキップ)")
            HAS_ERROR=true
        fi
    else
        echo "  npm がインストールされていないため、先に Node.js をインストールしてください"
        RESULTS+=("Claude Code CLI: 未インストール (npm必要)")
        HAS_ERROR=true
    fi
fi

# ============================================================
# STEP 5.5: Codex CLI チェック
# ============================================================
log_step "STEP 5.5: Codex CLI チェック"

if command -v codex &> /dev/null; then
    CODEX_VERSION=$(codex --version 2>/dev/null || echo "unknown")
    log_success "Codex CLI がインストール済みです"
    log_info "バージョン: $CODEX_VERSION"
    RESULTS+=("Codex CLI: OK")
else
    log_warn "Codex CLI がインストールされていません"
    echo ""
    echo "  Codex CLI をインストールして PATH に通してください。"
    RESULTS+=("Codex CLI: 未インストール")
    HAS_ERROR=true
fi

# ============================================================
# STEP 6: ディレクトリ構造作成
# ============================================================
log_step "STEP 6: ディレクトリ構造作成"

# 必要なディレクトリ一覧
DIRECTORIES=(
    "queue/tasks"
    "queue/reports"
    "queue/review"
    "config"
    "status"
    "instructions"
    "logs"
    "demo_output"
    "skills"
    "memory"
)

CREATED_COUNT=0
EXISTED_COUNT=0

for dir in "${DIRECTORIES[@]}"; do
    if [ ! -d "$SCRIPT_DIR/$dir" ]; then
        mkdir -p "$SCRIPT_DIR/$dir"
        log_info "作成: $dir/"
        CREATED_COUNT=$((CREATED_COUNT + 1))
    else
        EXISTED_COUNT=$((EXISTED_COUNT + 1))
    fi
done

if [ $CREATED_COUNT -gt 0 ]; then
    log_success "$CREATED_COUNT 個のディレクトリを作成しました"
fi
if [ $EXISTED_COUNT -gt 0 ]; then
    log_info "$EXISTED_COUNT 個のディレクトリは既に存在します"
fi

RESULTS+=("ディレクトリ構造: OK (作成:$CREATED_COUNT, 既存:$EXISTED_COUNT)")

# ============================================================
# STEP 7: 設定ファイル初期化
# ============================================================
log_step "STEP 7: 設定ファイル確認"

# config/settings.yaml
if [ ! -f "$SCRIPT_DIR/config/settings.yaml" ]; then
    log_info "config/settings.yaml を作成中..."
    cat > "$SCRIPT_DIR/config/settings.yaml" << EOF
# BANK settings

# Language
# ja: Japanese
# en: English
language: ja

# Shell
# bash: bash prompt
# zsh: zsh prompt
shell: bash

# Skill settings
skill:
  # Global skill path
  save_path: "~/.claude/skills/"

  # Local skill path (project-specific)
  local_path: "$SCRIPT_DIR/skills/"

# Logging
logging:
  level: info  # debug | info | warn | error
  path: "$SCRIPT_DIR/logs/"
EOF
    log_success "settings.yaml を作成しました"
else
    log_info "config/settings.yaml は既に存在します"
fi

# config/projects.yaml
if [ ! -f "$SCRIPT_DIR/config/projects.yaml" ]; then
    log_info "config/projects.yaml を作成中..."
    cat > "$SCRIPT_DIR/config/projects.yaml" << 'EOF'
projects:
  - id: sample_project
    name: "Sample Project"
    path: "/path/to/your/project"
    priority: high
    status: active

current_project: sample_project
EOF
    log_success "projects.yaml を作成しました"
else
    log_info "config/projects.yaml は既に存在します"
fi

# config/target.yaml
if [ ! -f "$SCRIPT_DIR/config/target.yaml" ]; then
    log_info "config/target.yaml を作成中..."
    cat > "$SCRIPT_DIR/config/target.yaml" << 'EOF'
workspace:
  path: "/path/to/your/workspace"
EOF
    log_success "target.yaml を作成しました"
else
    log_info "config/target.yaml は既に存在します"
fi

# config/permissions.yaml
if [ ! -f "$SCRIPT_DIR/config/permissions.yaml" ]; then
    log_info "config/permissions.yaml を作成中..."
    cat > "$SCRIPT_DIR/config/permissions.yaml" << 'EOF'
# BANK permissions policy

allowed:
  read_commands:
    - ls
    - rg
    - cat
    - sed -n
    - find
    - head
    - tail
    - awk
    - jq
    - tmux list-panes
    - tmux capture-pane
  edit_tools:
    - apply_patch
  exec_commands:
    - python3
    - pytest
    - tmux send-keys
    - ./go.sh
    - ./first_setup.sh
    - pip install -e
    - pip install -r
    - curl
  network:
    mode: allowlist
    allowed_domains:
      - disclosure.edinet-fsa.go.jp
      - api.jquants.com
      - www.jpx.co.jp
      - api.jpx-jquants.com

denied:
  destructive:
    - rm -rf
    - git reset --hard
    - git checkout --

write_scope:
  allowed_paths:
    - /tmp
    - ./queue
    - ./dashboard.md
    - ./config
    - ./memory
    - ./logs
    - ./README.md
    - ./README_ja.md
    - ./CLAUDE.md
    - ./instructions
    - ./templates
    - ./go.sh
    - ./first_setup.sh
    - ./setup.sh
    - ./install.bat
    - ./skills
    - ./data
    - ./projects
    - ./.env.example
EOF
    log_success "permissions.yaml を作成しました"
else
    log_info "config/permissions.yaml は既に存在します"
fi

# memory/global_context.md（システム全体のコンテキスト）
if [ ! -f "$SCRIPT_DIR/memory/global_context.md" ]; then
    log_info "memory/global_context.md を作成中..."
    cat > "$SCRIPT_DIR/memory/global_context.md" << 'EOF'
# グローバルコンテキスト
最終更新: (未設定)

## システム方針
- (ユーザーの好み・方針をここに記載)

## プロジェクト横断の決定事項
- (複数プロジェクトに影響する決定をここに記載)

## 注意事項
- (全エージェントが知るべき注意点をここに記載)
EOF
    log_success "global_context.md を作成しました"
else
    log_info "memory/global_context.md は既に存在します"
fi

RESULTS+=("設定ファイル: OK")

# ============================================================
# STEP 8: Junior用タスク・レポートファイル初期化
# ============================================================
log_step "STEP 8: キューファイル初期化"

# Junior用タスクファイル作成
for i in {1..3}; do
    TASK_FILE="$SCRIPT_DIR/queue/tasks/junior${i}.yaml"
    if [ ! -f "$TASK_FILE" ]; then
        cat > "$TASK_FILE" << EOF
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
    fi
done
log_info "Juniorタスクファイル (1-3) を確認/作成しました"

# Junior用レポートファイル作成
for i in {1..3}; do
    REPORT_FILE="$SCRIPT_DIR/queue/reports/junior${i}_report.yaml"
    if [ ! -f "$REPORT_FILE" ]; then
        cat > "$REPORT_FILE" << EOF
worker_id: junior${i}
task_id: null
ticker: null
analysis_type: null
timestamp: ""
status: idle
result: null
quality_check_required: true
EOF
    fi
done
log_info "Juniorレポートファイル (1-3) を確認/作成しました"

# Manager → Senior queue
COMMAND_QUEUE="$SCRIPT_DIR/queue/paper_to_senior.yaml"
if [ ! -f "$COMMAND_QUEUE" ]; then
    cat > "$COMMAND_QUEUE" << EOF
queue: []
EOF
fi

# Review queue files
REVIEW_DIR="$SCRIPT_DIR/queue/review"
mkdir -p "$REVIEW_DIR"

if [ ! -f "$REVIEW_DIR/junior_to_reviewer.yaml" ]; then
    cat > "$REVIEW_DIR/junior_to_reviewer.yaml" << EOF
review_request: null
review_followup: null
EOF
fi

if [ ! -f "$REVIEW_DIR/reviewer_to_junior.yaml" ]; then
    cat > "$REVIEW_DIR/reviewer_to_junior.yaml" << EOF
review_response: null
EOF
fi

if [ ! -f "$REVIEW_DIR/senior_to_reviewer.yaml" ]; then
    cat > "$REVIEW_DIR/senior_to_reviewer.yaml" << EOF
plan_review_request: null
EOF
fi

if [ ! -f "$REVIEW_DIR/reviewer_to_senior.yaml" ]; then
    cat > "$REVIEW_DIR/reviewer_to_senior.yaml" << EOF
plan_review_response: null
EOF
fi

RESULTS+=("キューファイル: OK")

# ============================================================
# STEP 9: スクリプト実行権限付与
# ============================================================
log_step "STEP 9: 実行権限設定"

SCRIPTS=(
    "setup.sh"
    "go.sh"
    "first_setup.sh"
)

for script in "${SCRIPTS[@]}"; do
    if [ -f "$SCRIPT_DIR/$script" ]; then
        chmod +x "$SCRIPT_DIR/$script"
        log_info "$script に実行権限を付与しました"
    fi
done

RESULTS+=("実行権限: OK")

# ============================================================
# STEP 10: bashrc alias設定
# ============================================================
log_step "STEP 10: alias設定"

# alias追加対象ファイル
BASHRC_FILE="$HOME/.bashrc"

# aliasが既に存在するかチェックし、なければ追加
ALIAS_ADDED=false

# cba alias (multiagentセッションの起動)
if [ -f "$BASHRC_FILE" ]; then
    EXPECTED_CSS="alias cba='tmux attach-session -t multiagent'"
    if ! grep -q "alias cba=" "$BASHRC_FILE" 2>/dev/null; then
        # alias が存在しない → 新規追加
        echo "" >> "$BASHRC_FILE"
        echo "# BANK aliases (added by first_setup.sh)" >> "$BASHRC_FILE"
        echo "$EXPECTED_CSS" >> "$BASHRC_FILE"
        log_info "alias cba を追加しました（multiagentセッションの起動）"
        ALIAS_ADDED=true
    elif ! grep -qF "$EXPECTED_CSS" "$BASHRC_FILE" 2>/dev/null; then
        # alias は存在するがパスが異なる → 更新
        if sed -i "s|alias cba=.*|$EXPECTED_CSS|" "$BASHRC_FILE" 2>/dev/null; then
            log_info "alias cba を更新しました（パス変更検出）"
        else
            log_warn "alias cba の更新に失敗しました"
        fi
        ALIAS_ADDED=true
    else
        log_info "alias cba は既に正しく設定されています"
    fi

    # cbw alias (起動スクリプトの起動)
    EXPECTED_CSM="alias cbw='cd $SCRIPT_DIR && ./go.sh'"
    if ! grep -q "alias cbw=" "$BASHRC_FILE" 2>/dev/null; then
        if [ "$ALIAS_ADDED" = false ]; then
            echo "" >> "$BASHRC_FILE"
            echo "# BANK aliases (added by first_setup.sh)" >> "$BASHRC_FILE"
        fi
        echo "$EXPECTED_CSM" >> "$BASHRC_FILE"
        log_info "alias cbw を追加しました（起動スクリプトの起動）"
        ALIAS_ADDED=true
    elif ! grep -qF "$EXPECTED_CSM" "$BASHRC_FILE" 2>/dev/null; then
        if sed -i "s|alias cbw=.*|$EXPECTED_CSM|" "$BASHRC_FILE" 2>/dev/null; then
            log_info "alias cbw を更新しました（パス変更検出）"
        else
            log_warn "alias cbw の更新に失敗しました"
        fi
        ALIAS_ADDED=true
    else
        log_info "alias cbw は既に正しく設定されています"
    fi
else
    log_warn "$BASHRC_FILE が見つかりません"
fi

if [ "$ALIAS_ADDED" = true ]; then
    log_success "alias設定を追加しました"
    log_warn "alias を反映するには、以下のいずれかを実行してください："
    log_info "  1. source ~/.bashrc"
    log_info "  2. PowerShell で 'wsl --shutdown' してからターミナルを開き直す"
    log_info "  ※ ウィンドウを閉じるだけでは WSL が終了しないため反映されません"
fi

RESULTS+=("alias設定: OK")

# ============================================================
# STEP 11: Memory MCP セットアップ
# ============================================================
log_step "STEP 11: Memory MCP セットアップ"

if command -v claude &> /dev/null; then
    # Memory MCP が既に設定済みか確認
    if claude mcp list 2>/dev/null | grep -q "memory"; then
        log_info "Memory MCP は既に設定済みです"
        RESULTS+=("Memory MCP: OK (設定済み)")
    else
        log_info "Memory MCP を設定中..."
        if claude mcp add memory \
            -e MEMORY_FILE_PATH="$SCRIPT_DIR/memory/bank_memory.jsonl" \
            -- npx -y @modelcontextprotocol/server-memory 2>/dev/null; then
            log_success "Memory MCP 設定完了"
            RESULTS+=("Memory MCP: 設定完了")
        else
            log_warn "Memory MCP の設定に失敗しました（手動で設定可能）"
            RESULTS+=("Memory MCP: 設定失敗 (手動設定可能)")
        fi
    fi
else
    log_warn "claude コマンドが見つからないため Memory MCP 設定をスキップ"
    RESULTS+=("Memory MCP: スキップ (claude未インストール)")
fi

# ============================================================
# 結果サマリー
# ============================================================
echo ""
echo "  ╔══════════════════════════════════════════════════════════════╗"
echo "  ║  📋 セットアップ結果サマリー                                  ║"
echo "  ╚══════════════════════════════════════════════════════════════╝"
echo ""

for result in "${RESULTS[@]}"; do
    if [[ $result == *"未インストール"* ]] || [[ $result == *"失敗"* ]]; then
        echo -e "  ${RED}✗${NC} $result"
    elif [[ $result == *"アップグレード"* ]] || [[ $result == *"スキップ"* ]]; then
        echo -e "  ${YELLOW}!${NC} $result"
    else
        echo -e "  ${GREEN}✓${NC} $result"
    fi
done

echo ""

if [ "$HAS_ERROR" = true ]; then
    echo "  ╔══════════════════════════════════════════════════════════════╗"
    echo "  ║  ⚠️  一部の依存関係が不足しています                           ║"
    echo "  ╚══════════════════════════════════════════════════════════════╝"
    echo ""
    echo "  上記の警告を確認し、不足しているものをインストールしてください。"
    echo "  すべての依存関係が揃ったら、再度このスクリプトを実行して確認できます。"
else
    echo "  ╔══════════════════════════════════════════════════════════════╗"
    echo "  ║  ✅ セットアップ完了！                                      ║"
    echo "  ╚══════════════════════════════════════════════════════════════╝"
fi

echo ""
echo "  ┌──────────────────────────────────────────────────────────────┐"
echo "  │  📜 次のステップ                                             │"
echo "  └──────────────────────────────────────────────────────────────┘"
echo ""
echo "  起動（全エージェント起動）:"
echo "     ./go.sh"
echo ""
echo "  オプション:"
echo "     ./go.sh -s            # セットアップのみ（Claude手動起動）"
echo "     ./go.sh -t            # Windows Terminalタブ展開"
echo "     ./go.sh -shell bash   # bash用プロンプトで起動"
echo "     ./go.sh -shell zsh    # zsh用プロンプトで起動"
echo ""
echo "  ※ シェル設定は config/settings.yaml の shell: でも変更可能です"
echo ""
echo "  詳細は README.md を参照してください。"
echo ""
echo "  ════════════════════════════════════════════════════════════════"
echo "  Ready."
echo "  ════════════════════════════════════════════════════════════════"
echo ""

# 依存関係不足の場合は exit 1 を返す（install.bat が検知できるように）
if [ "$HAS_ERROR" = true ]; then
    exit 1
fi
