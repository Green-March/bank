"""Checkpoint models for agent context persistence."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Checkpoint(BaseModel):
    """Agent checkpoint for context handoff."""

    model_config = ConfigDict(extra="allow")

    task_id: str
    agent_id: str
    status: str
    key_findings: list[str] = []
    output_files: list[str] = []
    next_steps: list[str] = []
    context_summary: str = ""
    timestamp: str
