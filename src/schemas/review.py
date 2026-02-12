"""Review and gate result models for BANK system."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class GateResult(BaseModel):
    """Single gate validation result."""

    model_config = ConfigDict(extra="allow")

    id: str
    gate_type: Optional[str] = None
    passed: bool
    detail: dict = {}


class ReviewResult(BaseModel):
    """Review verdict from reviewer agent."""

    model_config = ConfigDict(extra="allow")

    verdict: Literal["ok", "revise", "reject"]
    comments: dict = {}
    suggested_changes: list[str] = []
