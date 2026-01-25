# 🏯 claude-shogun

<div align="center">

**Multi-Agent Orchestration System for Claude Code**

*Inspired by the Japanese Feudal Military Structure*

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Claude Code](https://img.shields.io/badge/Claude-Code-blueviolet)](https://claude.ai)
[![tmux](https://img.shields.io/badge/tmux-required-green)](https://github.com/tmux/tmux)

[English](README.md) | [日本語](README_ja.md)

</div>

---

## ⚔️ What is claude-shogun?

**claude-shogun** transforms Claude Code into a **parallel development powerhouse** by orchestrating multiple AI agents in a feudal military hierarchy.

> 🎯 **One human. One command. Eight agents working in parallel.**

```
                    ┌─────────────────┐
                    │   上様 (Human)   │
                    │    The Lord     │
                    └────────┬────────┘
                             │ Commands
                             ▼
                    ┌─────────────────┐
                    │     SHOGUN      │  ← Strategic Oversight
                    │      将軍       │     Plans & Delegates
                    └────────┬────────┘
                             │ Orders via YAML
                             ▼
                    ┌─────────────────┐
                    │      KARO       │  ← Tactical Management
                    │      家老       │     Distributes Tasks
                    └────────┬────────┘
                             │ Tasks via dedicated files
                             ▼
        ┌───┬───┬───┬───┬───┬───┬───┬───┐
        │ 1 │ 2 │ 3 │ 4 │ 5 │ 6 │ 7 │ 8 │  ← Parallel Execution
        └───┴───┴───┴───┴───┴───┴───┴───┘
                  ASHIGARU 足軽
                  (Infantry Workers)
```

---

## ✨ Key Features

| Feature | Description |
|---------|-------------|
| 🔄 **Event-Driven Communication** | No polling. Agents wake each other via `tmux send-keys` |
| 📁 **Dedicated Task Files** | Each Ashigaru has its own task file—no conflicts |
| 🛡️ **Race Condition Protection** | Built-in safeguards against concurrent file writes |
| 📊 **Real-time Dashboard** | Human-readable status at `dashboard.md` |
| 🎭 **Samurai Personas** | Fun feudal aesthetics, professional-grade output |
| 🌏 **Bilingual Support** | Japanese + English (configurable) |

---

## 🚀 Quick Start

### Prerequisites

- **WSL2** (Ubuntu recommended)
- **tmux** (`sudo apt install tmux`)
- **Claude Code CLI** ([Installation Guide](https://claude.ai/code))

### Installation

```bash
# Clone the repository
git clone https://github.com/yohey-w/multi-agent-shogun.git /mnt/c/tools/claude-shogun

# Create symlink for easy access
ln -s /mnt/c/tools/claude-shogun ~/claude-shogun

# Run setup
cd ~/claude-shogun && ./setup.sh
```

### Recommended Aliases

Add to your `~/.bashrc`:

```bash
# claude-shogun shortcuts
alias csst='cd /mnt/c/tools/claude-shogun && ./setup.sh'
alias css='tmux attach-session -t shogun'
alias csm='tmux attach-session -t multiagent'

# One command to rule them all
alias cssta='cd /mnt/c/tools/claude-shogun && ./setup.sh && \
  tmux send-keys -t shogun "claude --dangerously-skip-permissions" Enter && \
  for i in {0..8}; do tmux send-keys -t multiagent:0.$i "claude --dangerously-skip-permissions" Enter; done && \
  wt.exe -w 0 new-tab wsl.exe -e bash -c "tmux attach-session -t shogun" \; new-tab wsl.exe -e bash -c "tmux attach-session -t multiagent"'
```

| Alias | Description |
|-------|-------------|
| `csst` | Initialize tmux sessions |
| `css` | Attach to Shogun (commander) |
| `csm` | Attach to Karo + Ashigaru |
| `cssta` | **Full deployment** - Setup + Start all agents + Open terminals |

### Deploy

```bash
# Option 1: Full auto-deployment
cssta

# Option 2: Manual
css                                    # Attach to Shogun
claude --dangerously-skip-permissions  # Start Claude Code
# Then give the order:
# "Read CLAUDE.md and instructions/shogun.md. You are the Shogun."
```

---

## 📂 Architecture

```
claude-shogun/
├── 📜 instructions/           # Agent instruction manuals
│   ├── shogun.md              #   └─ Shogun: Strategy & oversight
│   ├── karo.md                #   └─ Karo: Task distribution
│   └── ashigaru.md            #   └─ Ashigaru: Execution
│
├── ⚙️ config/
│   ├── settings.yaml          # Language & skill settings
│   └── projects.yaml          # Project definitions
│
├── 📬 queue/                   # Communication channels
│   ├── shogun_to_karo.yaml    #   └─ Shogun → Karo orders
│   ├── tasks/                 #   └─ Dedicated task files per Ashigaru
│   │   ├── ashigaru1.yaml
│   │   ├── ashigaru2.yaml
│   │   └── ...
│   └── reports/               #   └─ Completion reports
│       ├── ashigaru1_report.yaml
│       └── ...
│
├── 📊 status/
│   └── master_status.yaml     # System-wide status
│
├── 📋 dashboard.md            # Human-readable overview
├── 📖 CLAUDE.md               # System context for Claude
└── 🔧 setup.sh                # Session initialization
```

---

## 🔧 Communication Protocol

### Event-Driven (No Polling)

Agents communicate via **YAML files + tmux send-keys**:

```
1. Shogun writes order to queue/shogun_to_karo.yaml
2. Shogun wakes Karo via: tmux send-keys -t multiagent:0.0 "..." Enter
3. Karo reads order, distributes to Ashigaru via dedicated files
4. Ashigaru completes task, writes report, wakes Karo
5. Karo aggregates, wakes Shogun
6. Shogun updates dashboard for human
```

### Critical Rule: Two-Step send-keys

```bash
# ✅ CORRECT - Two separate calls
tmux send-keys -t multiagent:0.0 "Your message here"
tmux send-keys -t multiagent:0.0 Enter

# ❌ WRONG - Will not work
tmux send-keys -t multiagent:0.0 "Your message" Enter
```

---

## 🎭 Samurai Communication Style

Agents speak in feudal Japanese with translations:

| Phrase | Meaning |
|--------|---------|
| `はっ！(Ha!)` | Acknowledged |
| `承知つかまつった (Acknowledged!)` | Understood |
| `任務完了でござる (Task completed!)` | Mission complete |
| `出陣いたす (Deploying!)` | Starting work |
| `申し上げます (Reporting!)` | Reporting |

> 💡 Set `language: ja` in `config/settings.yaml` for Japanese-only mode.

---

## 🛣️ Roadmap

### ✅ Completed (v1.0)

- [x] Event-driven YAML communication
- [x] Dedicated task files per Ashigaru
- [x] Race condition protection (RACE-001)
- [x] Human dashboard
- [x] Bilingual support
- [x] Persona system for quality output
- [x] Skill discovery & generation flow

### 🔮 Future

- [ ] **MCP Integration** - Gmail, Notion, Slack, Google Calendar
- [ ] **Multi-project parallel execution**
- [ ] **Auto-recovery from agent failures**
- [ ] **Web UI dashboard**

---

## 🙏 Credits

Based on [Claude-Code-Communication](https://github.com/Akira-Papa/Claude-Code-Communication) by Akira-Papa.

---

## 📄 License

MIT License - See [LICENSE](LICENSE) for details.

---

<div align="center">

**⚔️ Command your AI army. Build faster. 🏯**

</div>
