"""Financial data models for BANK system."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class BSData(BaseModel):
    """Balance sheet data."""

    model_config = ConfigDict(extra="allow")

    total_assets: Optional[int] = None
    current_assets: Optional[int] = None
    total_liabilities: Optional[int] = None
    current_liabilities: Optional[int] = None
    total_equity: Optional[int] = None
    net_assets: Optional[int] = None


class PLData(BaseModel):
    """Profit and loss data."""

    model_config = ConfigDict(extra="allow")

    revenue: Optional[int] = None
    gross_profit: Optional[int] = None
    operating_income: Optional[int] = None
    ordinary_income: Optional[int] = None
    net_income: Optional[int] = None


class CFData(BaseModel):
    """Cash flow data."""

    model_config = ConfigDict(extra="allow")

    operating_cf: Optional[int] = None
    investing_cf: Optional[int] = None
    financing_cf: Optional[int] = None
    free_cash_flow: Optional[int] = None


class PeriodFinancial(BaseModel):
    """Single period financial data."""

    model_config = ConfigDict(extra="allow")

    period_end: str
    period_start: Optional[str] = None
    period_type: Optional[str] = None
    fiscal_year: Optional[int | str] = None
    bs: BSData = BSData()
    pl: PLData = PLData()
    cf: CFData = CFData()


class ParsedDocument(BaseModel):
    """Parsed document containing one or more periods."""

    model_config = ConfigDict(extra="allow")

    ticker: str
    document_id: str
    source_zip: Optional[str] = None
    company_name: Optional[str] = None
    periods: list[PeriodFinancial] = []


class FinancialsJson(BaseModel):
    """Top-level financials.json model."""

    model_config = ConfigDict(extra="allow")

    ticker: str
    generated_at: str
    document_count: int
    source_format: str
    documents: list[ParsedDocument] = []
    period_index: list[PeriodFinancial] = []
    schema_: Optional[dict] = None

    def __init__(self, **data):
        if "schema" in data and "schema_" not in data:
            data["schema_"] = data.pop("schema")
        super().__init__(**data)

    def model_dump(self, **kwargs):
        d = super().model_dump(**kwargs)
        if "schema_" in d:
            d["schema"] = d.pop("schema_")
        return d
