"""Tests for extract_shares_outstanding in disclosure-collector."""

from __future__ import annotations

import pytest

from shares import extract_shares_outstanding


class TestExtractSharesOutstanding:

    def test_normal_case(self) -> None:
        """Issued minus treasury = net shares outstanding."""
        statements = [
            {
                "NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock": "19571093",
                "NumberOfTreasuryStockAtTheEndOfFiscalYear": "1310362",
            }
        ]
        result = extract_shares_outstanding(statements)
        assert result == str(19571093 - 1310362)
        assert result == "18260731"

    def test_no_treasury_stock(self) -> None:
        """When treasury is absent, use issued as-is."""
        statements = [
            {
                "NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock": "10000000",
            }
        ]
        result = extract_shares_outstanding(statements)
        assert result == "10000000"

    def test_empty_treasury_stock(self) -> None:
        """Empty string treasury is treated as 0."""
        statements = [
            {
                "NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock": "10000000",
                "NumberOfTreasuryStockAtTheEndOfFiscalYear": "",
            }
        ]
        result = extract_shares_outstanding(statements)
        assert result == "10000000"

    def test_no_issued_shares(self) -> None:
        """Missing issued field returns empty string."""
        statements = [{"SomeOtherField": "value"}]
        result = extract_shares_outstanding(statements)
        assert result == ""

    def test_empty_statements(self) -> None:
        """Empty list returns empty string."""
        assert extract_shares_outstanding([]) == ""

    def test_uses_latest_record(self) -> None:
        """Should use the last record in the array (latest period)."""
        statements = [
            {
                "NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock": "5000000",
                "NumberOfTreasuryStockAtTheEndOfFiscalYear": "0",
            },
            {
                "NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock": "8000000",
                "NumberOfTreasuryStockAtTheEndOfFiscalYear": "1000000",
            },
        ]
        result = extract_shares_outstanding(statements)
        assert result == "7000000"

    def test_invalid_issued_value(self) -> None:
        """Non-numeric issued value returns empty string."""
        statements = [
            {
                "NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock": "not_a_number",
            }
        ]
        result = extract_shares_outstanding(statements)
        assert result == ""

    def test_null_issued_value(self) -> None:
        """None issued value returns empty string."""
        statements = [
            {
                "NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock": None,
            }
        ]
        result = extract_shares_outstanding(statements)
        assert result == ""

    def test_result_is_integer_string(self) -> None:
        """Result should be an integer string (no decimals)."""
        statements = [
            {
                "NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock": "10000000.0",
                "NumberOfTreasuryStockAtTheEndOfFiscalYear": "500000.0",
            }
        ]
        result = extract_shares_outstanding(statements)
        assert result == "9500000"
        assert "." not in result
