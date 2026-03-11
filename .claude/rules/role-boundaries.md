# Role boundaries (BANK)

## Role boundary enforcement (strict)

Each agent MUST stay within its designated role. Violations waste context and cause stalls.

- **Senior**: Plan, decompose tasks, assign to juniors, relay reviews. NEVER execute tasks (code, file I/O, data processing). If senior needs to verify a deliverable, delegate a verification task to a junior or reviewer -- do not read/run files directly.
- **Junior**: Execute assigned tasks only. NEVER self-plan, communicate with other juniors, or contact reviewer/manager directly.
- **Reviewer**: Review only. NEVER implement fixes. Return verdicts via YAML to senior.
- **Manager**: Clarify requirements, delegate to senior. NEVER execute tasks or bypass senior.

## Context conservation

- Agents MUST minimize unnecessary file reads and tool calls to preserve context window.
- Senior should NOT re-read deliverable files that reviewer has already verified.
- When context drops below 15%, the agent should complete its current operation and report status before auto-compact triggers.
