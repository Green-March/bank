"""Unit and integration tests for BANK Pydantic v2 schemas."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.schemas import (
    BSData,
    CFData,
    Checkpoint,
    DocumentMetadata,
    FinancialsJson,
    GateResult,
    ParsedDocument,
    PdfMetadata,
    PeriodFinancial,
    PLData,
    ReviewResult,
)


# ---------------------------------------------------------------------------
# test_financials_model
# ---------------------------------------------------------------------------


class TestFinancialsModel:
    """FinancialsJson model_validate tests."""

    def test_minimal(self):
        data = {
            "ticker": "1234",
            "generated_at": "2026-01-01T00:00:00",
            "document_count": 0,
            "source_format": "xbrl",
        }
        m = FinancialsJson.model_validate(data)
        assert m.ticker == "1234"
        assert m.documents == []
        assert m.period_index == []
        assert m.schema_ is None

    def test_with_documents_and_periods(self):
        data = {
            "ticker": "9999",
            "generated_at": "2026-01-01T00:00:00",
            "document_count": 1,
            "source_format": "pdf",
            "documents": [
                {
                    "ticker": "9999",
                    "document_id": "DOC001",
                    "source_zip": "path/to/file.pdf",
                    "company_name": "Test Corp",
                    "periods": [
                        {
                            "period_end": "2025-03-31",
                            "bs": {"total_assets": 100000},
                            "pl": {"revenue": 50000},
                            "cf": {"operating_cf": 8000},
                        }
                    ],
                }
            ],
            "period_index": [
                {
                    "period_end": "2025-03-31",
                    "bs": {"total_assets": 100000},
                    "pl": {"revenue": 50000},
                    "cf": {"operating_cf": 8000},
                }
            ],
            "schema": {
                "bs": ["total_assets"],
                "pl": ["revenue"],
                "cf": ["operating_cf"],
            },
        }
        m = FinancialsJson.model_validate(data)
        assert m.document_count == 1
        assert len(m.documents) == 1
        assert len(m.period_index) == 1
        assert m.schema_ is not None
        assert m.documents[0].periods[0].bs.total_assets == 100000

    def test_schema_round_trip(self):
        data = {
            "ticker": "0000",
            "generated_at": "2026-01-01T00:00:00",
            "document_count": 0,
            "source_format": "xbrl",
            "schema": {"bs": ["total_assets"]},
        }
        m = FinancialsJson.model_validate(data)
        dumped = m.model_dump()
        assert "schema" in dumped
        assert dumped["schema"]["bs"] == ["total_assets"]

    def test_json_schema_output(self):
        schema = FinancialsJson.model_json_schema()
        assert "properties" in schema
        assert "ticker" in schema["properties"]


# ---------------------------------------------------------------------------
# test_bsdata_optional / test_pldata_optional / test_cfdata_optional
# ---------------------------------------------------------------------------


class TestBSDataOptional:
    """BSData allows all-null fields."""

    def test_all_null(self):
        m = BSData.model_validate({})
        assert m.total_assets is None
        assert m.current_assets is None
        assert m.total_liabilities is None
        assert m.current_liabilities is None
        assert m.total_equity is None
        assert m.net_assets is None

    def test_partial(self):
        m = BSData.model_validate({"total_assets": 1000, "total_equity": 500})
        assert m.total_assets == 1000
        assert m.total_equity == 500
        assert m.total_liabilities is None

    def test_extra_fields_allowed(self):
        m = BSData.model_validate({"total_assets": 1000, "custom_field": 999})
        assert m.total_assets == 1000


class TestPLDataOptional:
    """PLData allows all-null fields."""

    def test_all_null(self):
        m = PLData.model_validate({})
        assert m.revenue is None
        assert m.gross_profit is None
        assert m.operating_income is None
        assert m.ordinary_income is None
        assert m.net_income is None

    def test_partial(self):
        m = PLData.model_validate({"revenue": 50000, "net_income": 3000})
        assert m.revenue == 50000
        assert m.net_income == 3000


class TestCFDataOptional:
    """CFData allows all-null fields."""

    def test_all_null(self):
        m = CFData.model_validate({})
        assert m.operating_cf is None
        assert m.investing_cf is None
        assert m.financing_cf is None
        assert m.free_cash_flow is None

    def test_negative_values(self):
        m = CFData.model_validate({"investing_cf": -500, "financing_cf": -300})
        assert m.investing_cf == -500
        assert m.financing_cf == -300


# ---------------------------------------------------------------------------
# test_pdf_metadata_model
# ---------------------------------------------------------------------------


class TestPdfMetadata:
    """PdfMetadata model tests."""

    def test_minimal(self):
        m = PdfMetadata.model_validate({
            "doc_id": "DOC001",
            "source_pdf": "path/to/doc.pdf",
            "period_end": "2025-03-31",
        })
        assert m.doc_id == "DOC001"
        assert m.parser_version is None
        assert m.unit_multiplier is None

    def test_full(self):
        m = PdfMetadata.model_validate({
            "doc_id": "DOC001",
            "source_pdf": "path/to/doc.pdf",
            "period_start": "2024-04-01",
            "period_end": "2025-03-31",
            "extraction_pages": [10, 11, 12],
            "parser_version": "0.3.0",
            "extraction_method": "multi-strategy",
            "unit_detected": "千円",
            "unit_multiplier": 1000,
            "strategy_used": "S1",
            "concept_score": 5,
        })
        assert m.unit_multiplier == 1000
        assert m.concept_score == 5
        assert len(m.extraction_pages) == 3


# ---------------------------------------------------------------------------
# test_period_financial
# ---------------------------------------------------------------------------


class TestPeriodFinancial:
    """PeriodFinancial model tests."""

    def test_normal(self):
        m = PeriodFinancial.model_validate({
            "period_end": "2025-03-31",
            "period_start": "2024-04-01",
            "period_type": "annual",
            "fiscal_year": 2025,
            "bs": {"total_assets": 100000},
            "pl": {"revenue": 50000},
            "cf": {"operating_cf": 8000},
        })
        assert m.period_end == "2025-03-31"
        assert m.fiscal_year == 2025
        assert m.bs.total_assets == 100000

    def test_null_sections(self):
        m = PeriodFinancial.model_validate({
            "period_end": "2025-03-31",
            "bs": {},
            "pl": {},
            "cf": {},
        })
        assert m.bs.total_assets is None
        assert m.pl.revenue is None
        assert m.cf.operating_cf is None

    def test_fiscal_year_as_string(self):
        m = PeriodFinancial.model_validate({
            "period_end": "2025-03-31",
            "fiscal_year": "2025",
        })
        assert m.fiscal_year == "2025"

    def test_extra_fields_preserved(self):
        m = PeriodFinancial.model_validate({
            "period_end": "2025-03-31",
            "source_document_ids": ["DOC001"],
        })
        assert m.period_end == "2025-03-31"


# ---------------------------------------------------------------------------
# test_review_result
# ---------------------------------------------------------------------------


class TestReviewResult:
    """ReviewResult verdict Literal validation."""

    def test_ok(self):
        m = ReviewResult.model_validate({"verdict": "ok"})
        assert m.verdict == "ok"

    def test_revise(self):
        m = ReviewResult.model_validate({
            "verdict": "revise",
            "comments": {"code": "needs refactoring"},
            "suggested_changes": ["fix imports"],
        })
        assert m.verdict == "revise"
        assert len(m.suggested_changes) == 1

    def test_reject(self):
        m = ReviewResult.model_validate({"verdict": "reject"})
        assert m.verdict == "reject"

    def test_invalid_verdict(self):
        with pytest.raises(ValidationError):
            ReviewResult.model_validate({"verdict": "maybe"})


# ---------------------------------------------------------------------------
# test_gate_result
# ---------------------------------------------------------------------------


class TestGateResult:
    """GateResult construction and validation."""

    def test_basic(self):
        m = GateResult.model_validate({
            "id": "null_rate",
            "passed": True,
            "detail": {"null_rate": 0.05},
        })
        assert m.id == "null_rate"
        assert m.passed is True
        assert m.detail["null_rate"] == 0.05

    def test_with_gate_type(self):
        m = GateResult.model_validate({
            "id": "coverage",
            "gate_type": "key_coverage",
            "passed": False,
            "detail": {"missing": ["revenue"]},
        })
        assert m.gate_type == "key_coverage"
        assert m.passed is False


# ---------------------------------------------------------------------------
# test_checkpoint_model
# ---------------------------------------------------------------------------


class TestCheckpointModel:
    """Checkpoint round-trip: model_validate -> model_dump."""

    def test_round_trip(self):
        data = {
            "task_id": "req_001_T1",
            "agent_id": "junior1",
            "status": "done",
            "key_findings": ["found issue A", "resolved B"],
            "output_files": ["output.json"],
            "next_steps": ["run tests"],
            "context_summary": "Completed parsing task.",
            "timestamp": "2026-02-12T10:00:00+09:00",
        }
        m = Checkpoint.model_validate(data)
        dumped = m.model_dump()
        assert dumped["task_id"] == "req_001_T1"
        assert dumped["agent_id"] == "junior1"
        assert len(dumped["key_findings"]) == 2
        assert dumped["context_summary"] == "Completed parsing task."

    def test_minimal(self):
        m = Checkpoint.model_validate({
            "task_id": "T1",
            "agent_id": "junior2",
            "status": "in_progress",
            "timestamp": "2026-01-01T00:00:00",
        })
        assert m.key_findings == []
        assert m.output_files == []
        assert m.next_steps == []
        assert m.context_summary == ""


# ---------------------------------------------------------------------------
# test_backward_compatibility (real data)
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Validate against real financials.json data."""

    REAL_DATA_PATH = (
        Path(__file__).resolve().parents[3]
        / "projects"
        / "2780_コメ兵ホールディングス"
        / "parsed"
        / "financials.json"
    )

    @pytest.fixture()
    def real_data(self):
        if not self.REAL_DATA_PATH.exists():
            pytest.skip("Real data not available")
        with self.REAL_DATA_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)

    def test_model_validate(self, real_data):
        m = FinancialsJson.model_validate(real_data)
        assert m.ticker == "2780"
        assert m.document_count == 10
        assert m.source_format == "pdf"
        assert len(m.documents) == 10
        assert len(m.period_index) == 11

    def test_period_data_integrity(self, real_data):
        m = FinancialsJson.model_validate(real_data)
        for period in m.period_index:
            assert period.period_end is not None
            assert isinstance(period.bs, BSData)
            assert isinstance(period.pl, PLData)
            assert isinstance(period.cf, CFData)

    def test_document_structure(self, real_data):
        m = FinancialsJson.model_validate(real_data)
        for doc in m.documents:
            assert doc.ticker == "2780"
            assert doc.document_id is not None
            assert len(doc.periods) > 0

    def test_schema_field_preserved(self, real_data):
        m = FinancialsJson.model_validate(real_data)
        assert m.schema_ is not None
        dumped = m.model_dump()
        assert "schema" in dumped
        assert "bs" in dumped["schema"]

    def test_round_trip_json(self, real_data):
        m = FinancialsJson.model_validate(real_data)
        dumped = m.model_dump()
        serialized = json.dumps(dumped, ensure_ascii=False)
        reparsed = json.loads(serialized)
        m2 = FinancialsJson.model_validate(reparsed)
        assert m2.ticker == m.ticker
        assert m2.document_count == m.document_count
        assert len(m2.period_index) == len(m.period_index)

    def test_model_json_schema(self, real_data):
        schema = FinancialsJson.model_json_schema()
        assert "properties" in schema
        assert "ticker" in schema["properties"]
        assert "period_index" in schema["properties"]


# ---------------------------------------------------------------------------
# test_document_metadata
# ---------------------------------------------------------------------------


class TestDocumentMetadata:
    """DocumentMetadata model tests."""

    def test_minimal(self):
        m = DocumentMetadata.model_validate({})
        assert m.ticker is None
        assert m.document_id is None

    def test_full(self):
        m = DocumentMetadata.model_validate({
            "ticker": "7203",
            "document_id": "S100XXX",
            "doc_type": "有価証券報告書",
            "filing_date": "2025-06-20",
            "edinet_code": "E00001",
        })
        assert m.edinet_code == "E00001"
