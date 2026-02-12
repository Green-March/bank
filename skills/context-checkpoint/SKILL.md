---
name: context-checkpoint
description: >-
  Save and restore agent context for task handoff across sessions.
  This skill should be used when an agent needs to persist its working state
  (task progress, key findings, output files, next steps) before auto-compact
  or session restart, and when a new session needs to resume from a saved checkpoint.
---

# Context Checkpoint

Persist and restore agent working state across sessions via YAML checkpoint files.

## Purpose

Enable seamless task continuity when agents hit auto-compact boundaries or restart.
Save structured snapshots of task progress so a fresh session can load the checkpoint
and resume work without information loss.

## Usage

### save — Save a checkpoint

```bash
python3 skills/context-checkpoint/scripts/main.py save \
  --agent <agent_id> \
  --task-id <task_id> \
  --status <in_progress|completed|blocked> \
  --key-findings "finding 1" \
  --key-findings "finding 2" \
  --output-files "path/to/file" \
  --next-steps "next action" \
  [--context-summary "free text summary"]
```

Writes to `memory/checkpoints/{agent_id}_{task_id}.yaml`.
Overwrites if the file already exists.

### load — Load a checkpoint

```bash
python3 skills/context-checkpoint/scripts/main.py load \
  --agent <agent_id> \
  --task-id <task_id>
```

Prints the checkpoint YAML to stdout. Exit code 1 if not found.

### list — List checkpoints

```bash
python3 skills/context-checkpoint/scripts/main.py list [--agent <agent_id>]
```

Lists all checkpoints in `memory/checkpoints/`. Use `--agent` to filter by agent.

## Checkpoint Schema

```yaml
task_id: "req_20260212_001_T1"
agent_id: "senior"
status: "completed"          # in_progress | completed | blocked
key_findings:
  - "quality-gate実装完了"
output_files:
  - "skills/quality-gate/"
next_steps:
  - "T2割り当て"
context_summary: ""          # optional free text
timestamp: "2026-02-12T10:00:00+09:00"
```

## CLI Options

| Option | Subcommand | Required | Description |
|---|---|---|---|
| `--agent` | save, load, list | save/load: Yes, list: No | Agent identifier (e.g. senior, junior1) |
| `--task-id` | save, load | Yes | Task identifier |
| `--status` | save | Yes | One of: in_progress, completed, blocked |
| `--key-findings` | save | No | Key findings (repeatable) |
| `--output-files` | save | No | Output file paths (repeatable) |
| `--next-steps` | save | No | Next steps (repeatable) |
| `--context-summary` | save | No | Free-text context summary |
| `--checkpoint-dir` | all | No | Override checkpoint directory (default: memory/checkpoints/) |

## Typical Workflow

1. Agent completes a task or detects low context remaining
2. Run `save` to persist current state
3. Session ends (auto-compact or manual restart)
4. New session starts, runs `load` to restore context
5. Agent continues from where it left off

## Scripts

- `scripts/main.py` — CLI entrypoint with save/load/list subcommands.

## Dependencies

- Python 3.10+
- pyyaml (only external dependency)
