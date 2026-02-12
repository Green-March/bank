"""Document metadata models for BANK system."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class PdfMetadata(BaseModel):
    """Metadata from PDF parsing."""

    model_config = ConfigDict(extra="allow")

    doc_id: str
    source_pdf: str
    period_start: Optional[str] = None
    period_end: str
    extraction_pages: Optional[list] = None
    parser_version: Optional[str] = None
    extraction_method: Optional[str] = None
    unit_detected: Optional[str] = None
    unit_multiplier: Optional[int] = None
    strategy_used: Optional[str] = None
    concept_score: Optional[int] = None


class DocumentMetadata(BaseModel):
    """EDINET document metadata."""

    model_config = ConfigDict(extra="allow")

    ticker: Optional[str] = None
    document_id: Optional[str] = None
    doc_type: Optional[str] = None
    filing_date: Optional[str] = None
    edinet_code: Optional[str] = None
