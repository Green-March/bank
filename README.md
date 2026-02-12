# BANK

Multi-agent orchestration for Japanese equity intelligence with Claude Code + tmux.

## What this is
`BANK` runs 6 agents in one tmux session:
- manager: user-facing coordinator
- senior: planner/dispatcher
- junior1-3: data collection, parsing, metrics, and report drafting
- reviewer: quality reviewer

All communication is file-based (YAML queues) and event-driven (`tmux send-keys`). No polling loops.

## Core objective
Collect Japanese stock information and generate high-quality analysis reports quickly and reproducibly.

## Data pipeline
1. Collect disclosure and financial data (EDINET / J-Quants)
2. Parse and normalize XBRL data
3. Calculate metrics and trends
4. Generate markdown/html analysis report
5. Run reviewer quality checks

## Quick start

### Windows (WSL2)
1. Clone this repository.
2. Run `install.bat` as Administrator.
3. In Ubuntu:
```bash
cd /mnt/c/tools/bank
./first_setup.sh
./go.sh
```

### Linux / macOS
```bash
git clone <your-repo-url> ~/bank
cd ~/bank
chmod +x *.sh
./first_setup.sh
./go.sh
```

## Target workspace
Run inside the target workspace or specify explicitly:
```bash
./go.sh --target /path/to/workspace
```
Target path is saved to `config/target.yaml`.

## Permissions and network
Operational permissions are defined in `config/permissions.yaml`.
Network is enabled for approved financial data sources.

## Required environment variables
Set API credentials in `.env`:
- `JQUANTS_REFRESH_TOKEN`
- `EDINET_API_KEY` (or `EDINET_SUBSCRIPTION_KEY`)

See `.env.example`.

## Skills
- `skills/disclosure-collector/`
- `skills/disclosure-parser/`
- `skills/financial-calculator/`
- `skills/financial-reporter/`
- `skills/pdf-reader/`, `skills/excel-handler/`, `skills/word-handler/`

## Templates
`templates/` includes practical templates for:
- analysis request intake
- hypothesis framing
- data collection and validation logs
- risk checklist
- final report structure

## Scripts
- `install.bat` — Windows WSL2 + Ubuntu setup
- `first_setup.sh` — initial environment setup
- `go.sh` — daily startup (tmux + agents)
- `setup.sh` — compatibility wrapper to `go.sh`

## Attach tmux session
```bash
tmux attach-session -t multiagent
```

## File structure (excerpt)
```
BANK/
├── instructions/
├── queue/
├── config/
├── skills/
├── templates/
└── dashboard.md
```
