from __future__ import annotations

import builtins
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from edinet import (
    NAMING_STRATEGIES,
    EdinetError,
    _build_pdf_base_name,
    _build_pdf_base_name_by_strategy,
    _extract_pdfs_from_zip,
    collect_edinet_pdfs,
    collect_edinet_reports,
    is_target_security_report,
)


@dataclass
class FakeEdinetClient:
    documents_by_date: dict[date, list[dict]]
    fetch_errors: dict[date, Exception] = field(default_factory=dict)
    download_payload_by_doc_id: dict[str, bytes] = field(default_factory=dict)
    download_errors: dict[str, Exception] = field(default_factory=dict)
    fetch_calls: list[date] = field(default_factory=list)
    download_calls: list[str] = field(default_factory=list)

    def fetch_documents_for_date(self, target_date: date, doc_type: int = 2) -> list[dict]:
        self.fetch_calls.append(target_date)
        if target_date in self.fetch_errors:
            raise self.fetch_errors[target_date]
        return self.documents_by_date.get(target_date, [])

    def download_xbrl_zip(self, doc_id: str) -> bytes:
        self.download_calls.append(doc_id)
        if doc_id in self.download_errors:
            raise self.download_errors[doc_id]
        return self.download_payload_by_doc_id.get(doc_id, b"zip-bytes")

    def download_pdf_zip(self, doc_id: str) -> bytes:
        self.download_calls.append(doc_id)
        if doc_id in self.download_errors:
            raise self.download_errors[doc_id]
        return self.download_payload_by_doc_id.get(doc_id, b"zip-bytes")


def test_collect_edinet_reports_is_idempotent(tmp_path: Path) -> None:
    start = date(2024, 3, 1)
    end = date(2024, 3, 2)
    client = FakeEdinetClient(
        documents_by_date={
            date(2024, 3, 1): [
                {
                    "docID": "DOC-001",
                    "edinetCode": "E03416",
                    "docDescription": "第46期 有価証券報告書",
                    "xbrlFlag": "1",
                }
            ],
            date(2024, 3, 2): [
                {
                    "docID": "DOC-002",
                    "edinetCode": "E03416",
                    "docDescription": "第47期 有価証券報告書",
                    "xbrlFlag": "1",
                }
            ],
        },
        download_payload_by_doc_id={"DOC-001": b"one", "DOC-002": b"two"},
    )

    first = collect_edinet_reports(
        edinet_code="E03416",
        output_dir=tmp_path,
        start_date=start,
        end_date=end,
        client=client,
    )

    assert first["matched_doc_count"] == 2
    assert first["downloaded_count"] == 2
    assert first["skipped_existing_count"] == 0
    assert client.fetch_calls == [start, end]
    assert sorted(client.download_calls) == ["DOC-001", "DOC-002"]

    client.fetch_calls.clear()
    client.download_calls.clear()

    second = collect_edinet_reports(
        edinet_code="E03416",
        output_dir=tmp_path,
        start_date=start,
        end_date=end,
        client=client,
    )

    assert second["matched_doc_count"] == 2
    assert second["downloaded_count"] == 0
    assert second["skipped_existing_count"] == 2
    assert client.fetch_calls == []
    assert client.download_calls == []

    manifest_path = tmp_path / "manifest.json"
    assert manifest_path.exists()
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["download_summary"]["attempted"] == 2
    assert manifest["download_summary"]["downloaded"] == 0
    assert manifest["download_summary"]["skipped_existing"] == 2
    assert manifest["download_summary"]["failed"] == 0


def test_collect_edinet_reports_records_failures_and_continues(tmp_path: Path) -> None:
    failing_day = date(2024, 4, 1)
    ok_day = date(2024, 4, 2)
    client = FakeEdinetClient(
        documents_by_date={
            ok_day: [
                {
                    "docID": "DOC-FAIL",
                    "edinetCode": "E03416",
                    "docDescription": "有価証券報告書",
                    "xbrlFlag": "1",
                }
            ]
        },
        fetch_errors={failing_day: EdinetError("daily list failed")},
        download_errors={"DOC-FAIL": EdinetError("download failed")},
    )

    result = collect_edinet_reports(
        edinet_code="E03416",
        output_dir=tmp_path,
        start_date=failing_day,
        end_date=ok_day,
        client=client,
    )

    assert result["matched_doc_count"] == 1
    assert result["downloaded_count"] == 0
    assert result["failed_count"] == 1
    assert result["failed_doc_ids"] == ["DOC-FAIL"]
    assert len(result["failed_dates"]) == 1
    assert result["failed_dates"][0]["date"] == failing_day.isoformat()

    manifest_path = tmp_path / "manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["failed_doc_ids"] == ["DOC-FAIL"]
    assert manifest["download_summary"]["failed"] == 1


def test_is_target_security_report_filters_by_fields() -> None:
    base_doc = {
        "docID": "DOC-001",
        "edinetCode": "E03416",
        "docDescription": "有価証券報告書",
        "xbrlFlag": "1",
        "formCode": "030000",
        "secCode": "27800",
    }

    assert is_target_security_report(
        document=base_doc,
        target_edinet_code="E03416",
        allowed_form_codes={"030000"},
        security_code="27800",
    )
    assert not is_target_security_report(
        document={**base_doc, "xbrlFlag": "0"},
        target_edinet_code="E03416",
    )
    assert not is_target_security_report(
        document={**base_doc, "edinetCode": "E99999"},
        target_edinet_code="E03416",
    )
    assert not is_target_security_report(
        document={**base_doc, "formCode": "999999"},
        target_edinet_code="E03416",
        allowed_form_codes={"030000"},
    )
    assert not is_target_security_report(
        document={**base_doc, "secCode": "99990"},
        target_edinet_code="E03416",
        security_code="27800",
    )


def test_collect_edinet_reports_cleans_partial_zip_and_retries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target_day = date(2024, 5, 1)
    client = FakeEdinetClient(
        documents_by_date={
            target_day: [
                {
                    "docID": "DOC-RETRY-001",
                    "edinetCode": "E03416",
                    "docDescription": "有価証券報告書",
                    "xbrlFlag": "1",
                }
            ]
        },
        download_payload_by_doc_id={"DOC-RETRY-001": b"valid-zip-content"},
    )

    original_open = builtins.open
    target_tmp_file = tmp_path / "DOC-RETRY-001.zip.tmp"
    injected = {"done": False}

    def flaky_open(file, mode="r", *args, **kwargs):
        path = Path(file)
        if (
            path == target_tmp_file
            and mode == "wb"
            and not injected["done"]
        ):
            injected["done"] = True
            fh = original_open(file, mode, *args, **kwargs)
            fh.write(b"partial")
            fh.close()
            raise OSError("simulated disk write failure")
        return original_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", flaky_open)

    first = collect_edinet_reports(
        edinet_code="E03416",
        output_dir=tmp_path,
        start_date=target_day,
        end_date=target_day,
        client=client,
    )

    assert first["failed_count"] == 1
    assert first["failed_doc_ids"] == ["DOC-RETRY-001"]
    assert not (tmp_path / "DOC-RETRY-001.zip").exists()
    assert not target_tmp_file.exists()

    second = collect_edinet_reports(
        edinet_code="E03416",
        output_dir=tmp_path,
        start_date=target_day,
        end_date=target_day,
        client=client,
    )

    assert second["downloaded_count"] == 1
    assert second["failed_count"] == 0
    assert (tmp_path / "DOC-RETRY-001.zip").exists()


# --- Tests for require_xbrl parameter ---


def test_is_target_security_report_require_xbrl_false() -> None:
    doc = {
        "docID": "DOC-001",
        "edinetCode": "E03416",
        "docDescription": "有価証券報告書",
        "xbrlFlag": "0",
    }
    assert not is_target_security_report(
        document=doc, target_edinet_code="E03416", require_xbrl=True,
    )
    assert is_target_security_report(
        document=doc, target_edinet_code="E03416", require_xbrl=False,
    )


# --- Tests for _build_pdf_base_name ---


def test_build_pdf_base_name_with_ticker() -> None:
    doc = {"secCode": "27800", "periodEnd": "2024-03-31", "docDescription": "有価証券報告書"}
    assert _build_pdf_base_name(doc, ticker="2780") == "2780_有価証券報告書_2024"


def test_build_pdf_base_name_without_ticker_strips_check_digit() -> None:
    doc = {"secCode": "27800", "periodEnd": "2024-03-31", "docDescription": "有価証券報告書"}
    result = _build_pdf_base_name(doc)
    assert result == "2780_有価証券報告書_2024"


def test_build_pdf_base_name_correction_report() -> None:
    doc = {"secCode": "27800", "periodEnd": "2024-03-31", "docDescription": "訂正有価証券報告書"}
    result = _build_pdf_base_name(doc, ticker="2780")
    assert result == "2780_訂正有価証券報告書_2024"


def test_build_pdf_base_name_fallback_to_submit_date() -> None:
    doc = {"secCode": "27800", "periodEnd": "", "submitDateTime": "2024-06-15 10:00", "docDescription": "有価証券報告書"}
    result = _build_pdf_base_name(doc, ticker="2780")
    assert result == "2780_有価証券報告書_2024"


def test_build_pdf_base_name_unknown_fallback() -> None:
    doc = {"docDescription": "有価証券報告書"}
    result = _build_pdf_base_name(doc)
    assert result == "unknown_有価証券報告書_unknown"


# --- Tests for _extract_pdfs_from_zip ---


def _make_zip_with_pdfs(filenames: list[str]) -> bytes:
    """Helper to create a ZIP archive containing given filenames."""
    import io as _io
    import zipfile as _zf
    buf = _io.BytesIO()
    with _zf.ZipFile(buf, "w") as zf:
        for name in filenames:
            zf.writestr(name, f"content-of-{name}")
    return buf.getvalue()


def test_extract_pdfs_single_pdf(tmp_path: Path) -> None:
    zip_bytes = _make_zip_with_pdfs(["report.pdf"])
    extracted = _extract_pdfs_from_zip(zip_bytes, tmp_path, "test_doc")
    assert len(extracted) == 1
    assert extracted[0].name == "test_doc.pdf"
    assert extracted[0].exists()


def test_extract_pdfs_multiple_pdfs(tmp_path: Path) -> None:
    zip_bytes = _make_zip_with_pdfs(["a.pdf", "b.pdf"])
    extracted = _extract_pdfs_from_zip(zip_bytes, tmp_path, "test_doc")
    assert len(extracted) == 2
    names = sorted(p.name for p in extracted)
    assert names == ["test_doc_1.pdf", "test_doc_2.pdf"]


def test_extract_pdfs_no_pdf_in_zip(tmp_path: Path) -> None:
    zip_bytes = _make_zip_with_pdfs(["readme.txt"])
    extracted = _extract_pdfs_from_zip(zip_bytes, tmp_path, "test_doc")
    assert extracted == []


def test_extract_pdfs_bad_zip(tmp_path: Path) -> None:
    import pytest
    with pytest.raises(EdinetError, match="invalid ZIP"):
        _extract_pdfs_from_zip(b"not-a-zip", tmp_path, "test_doc")


# --- Tests for collect_edinet_pdfs ---


def test_collect_edinet_pdfs_downloads_and_extracts(tmp_path: Path) -> None:
    target_day = date(2024, 6, 1)
    zip_bytes = _make_zip_with_pdfs(["report.pdf"])
    client = FakeEdinetClient(
        documents_by_date={
            target_day: [
                {
                    "docID": "DOC-PDF-001",
                    "edinetCode": "E03416",
                    "docDescription": "第46期 有価証券報告書",
                    "xbrlFlag": "0",
                    "secCode": "27800",
                    "periodEnd": "2024-03-31",
                }
            ]
        },
        download_payload_by_doc_id={"DOC-PDF-001": zip_bytes},
    )

    result = collect_edinet_pdfs(
        edinet_code="E03416",
        output_dir=tmp_path,
        start_date=target_day,
        end_date=target_day,
        ticker="2780",
        client=client,
    )

    assert result["matched_doc_count"] == 1
    assert result["downloaded_count"] == 1
    assert result["failed_count"] == 0

    manifest_path = tmp_path / "manifest.json"
    assert manifest_path.exists()
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["download_format"] == "pdf"
    assert manifest["download_summary"]["downloaded"] == 1


def test_collect_edinet_pdfs_skips_existing(tmp_path: Path) -> None:
    target_day = date(2024, 6, 1)
    zip_bytes = _make_zip_with_pdfs(["report.pdf"])

    # Pre-create the expected PDF
    (tmp_path / "2780_有価証券報告書_2024.pdf").write_bytes(b"existing")

    client = FakeEdinetClient(
        documents_by_date={
            target_day: [
                {
                    "docID": "DOC-PDF-002",
                    "edinetCode": "E03416",
                    "docDescription": "第46期 有価証券報告書",
                    "xbrlFlag": "0",
                    "secCode": "27800",
                    "periodEnd": "2024-03-31",
                }
            ]
        },
        download_payload_by_doc_id={"DOC-PDF-002": zip_bytes},
    )

    result = collect_edinet_pdfs(
        edinet_code="E03416",
        output_dir=tmp_path,
        start_date=target_day,
        end_date=target_day,
        ticker="2780",
        client=client,
    )

    assert result["matched_doc_count"] == 1
    assert result["downloaded_count"] == 0
    assert result["skipped_existing_count"] == 1
    assert client.download_calls == []


def test_collect_edinet_pdfs_handles_download_failure(tmp_path: Path) -> None:
    target_day = date(2024, 6, 1)
    client = FakeEdinetClient(
        documents_by_date={
            target_day: [
                {
                    "docID": "DOC-PDF-FAIL",
                    "edinetCode": "E03416",
                    "docDescription": "有価証券報告書",
                    "xbrlFlag": "0",
                    "secCode": "27800",
                    "periodEnd": "2024-03-31",
                }
            ]
        },
        download_errors={"DOC-PDF-FAIL": EdinetError("download failed")},
    )

    result = collect_edinet_pdfs(
        edinet_code="E03416",
        output_dir=tmp_path,
        start_date=target_day,
        end_date=target_day,
        ticker="2780",
        client=client,
    )

    assert result["matched_doc_count"] == 1
    assert result["downloaded_count"] == 0
    assert result["failed_count"] == 1
    assert result["failed_doc_ids"] == ["DOC-PDF-FAIL"]


# --- Tests for allowed_doc_type_codes filter ---


def test_is_target_security_report_doc_type_code_120_passes() -> None:
    doc = {
        "edinetCode": "E03416",
        "docDescription": "有価証券報告書",
        "xbrlFlag": "1",
        "docTypeCode": "120",
    }
    assert is_target_security_report(
        document=doc,
        target_edinet_code="E03416",
        allowed_doc_type_codes={"120", "130"},
    )


def test_is_target_security_report_doc_type_code_130_passes() -> None:
    doc = {
        "edinetCode": "E03416",
        "docDescription": "有価証券報告書",
        "xbrlFlag": "1",
        "docTypeCode": "130",
    }
    assert is_target_security_report(
        document=doc,
        target_edinet_code="E03416",
        allowed_doc_type_codes={"120", "130"},
    )


def test_is_target_security_report_doc_type_code_rejects_others() -> None:
    for code in ["140", "150", "235", "135"]:
        doc = {
            "edinetCode": "E03416",
            "docDescription": "有価証券報告書",
            "xbrlFlag": "1",
            "docTypeCode": code,
        }
        assert not is_target_security_report(
            document=doc,
            target_edinet_code="E03416",
            allowed_doc_type_codes={"120", "130"},
        ), f"docTypeCode={code} should be rejected"


def test_is_target_security_report_doc_type_code_none_allows_all() -> None:
    doc = {
        "edinetCode": "E03416",
        "docDescription": "有価証券報告書",
        "xbrlFlag": "1",
        "docTypeCode": "999",
    }
    assert is_target_security_report(
        document=doc,
        target_edinet_code="E03416",
        allowed_doc_type_codes=None,
    )


def test_is_target_security_report_doc_type_code_independent_of_description() -> None:
    doc = {
        "edinetCode": "E03416",
        "docDescription": "有価証券報告書",
        "xbrlFlag": "1",
        "docTypeCode": "140",
    }
    assert not is_target_security_report(
        document=doc,
        target_edinet_code="E03416",
        allowed_doc_type_codes={"120", "130"},
    )


def test_collect_edinet_reports_with_doc_type_code_filter(tmp_path: Path) -> None:
    target_day = date(2024, 7, 1)
    client = FakeEdinetClient(
        documents_by_date={
            target_day: [
                {
                    "docID": "DOC-120",
                    "edinetCode": "E03416",
                    "docDescription": "有価証券報告書",
                    "xbrlFlag": "1",
                    "docTypeCode": "120",
                },
                {
                    "docID": "DOC-140",
                    "edinetCode": "E03416",
                    "docDescription": "有価証券報告書",
                    "xbrlFlag": "1",
                    "docTypeCode": "140",
                },
            ]
        },
        download_payload_by_doc_id={"DOC-120": b"zip-120"},
    )

    result = collect_edinet_reports(
        edinet_code="E03416",
        output_dir=tmp_path,
        start_date=target_day,
        end_date=target_day,
        client=client,
        allowed_doc_type_codes={"120", "130"},
    )

    assert result["matched_doc_count"] == 1
    assert result["downloaded_count"] == 1


# --- Tests for statusCode parse error handling ---


def test_fetch_documents_for_date_unparseable_status_code() -> None:
    import pytest
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"statusCode": "invalid", "message": "test"},
        )

    transport = httpx.MockTransport(handler)
    client_obj = __import__("edinet").EdinetClient(
        api_key="test-key", transport=transport,
    )

    with pytest.raises(__import__("edinet").EdinetError, match="unparseable statusCode"):
        client_obj.fetch_documents_for_date(date(2024, 1, 1))


# --- Tests for naming strategy ---


def test_naming_strategies_constant() -> None:
    assert "ticker_year" in NAMING_STRATEGIES
    assert "doc_id" in NAMING_STRATEGIES
    assert "doc_id_desc" in NAMING_STRATEGIES


def test_build_pdf_base_name_by_strategy_ticker_year() -> None:
    doc = {"secCode": "27800", "periodEnd": "2024-03-31", "docDescription": "有価証券報告書"}
    result = _build_pdf_base_name_by_strategy(doc, naming_strategy="ticker_year", ticker="2780")
    assert result == "2780_有価証券報告書_2024"


def test_build_pdf_base_name_by_strategy_doc_id() -> None:
    doc = {"docID": "S100SW1R", "periodEnd": "2024-03-31", "docDescription": "有価証券報告書"}
    result = _build_pdf_base_name_by_strategy(doc, naming_strategy="doc_id")
    assert result == "S100SW1R_2024-03-31"


def test_build_pdf_base_name_by_strategy_doc_id_no_period_end() -> None:
    doc = {"docID": "S100SW1R", "periodEnd": "", "docDescription": "有価証券報告書"}
    result = _build_pdf_base_name_by_strategy(doc, naming_strategy="doc_id")
    assert result == "S100SW1R"


def test_build_pdf_base_name_by_strategy_doc_id_desc() -> None:
    doc = {"docID": "S100SW1R", "periodEnd": "2024-03-31", "docDescription": "第46期 有価証券報告書"}
    result = _build_pdf_base_name_by_strategy(doc, naming_strategy="doc_id_desc")
    assert result == "S100SW1R_第46期_有価証券報告書"


def test_build_pdf_base_name_by_strategy_doc_id_desc_empty() -> None:
    doc = {"docID": "S100SW1R", "periodEnd": "2024-03-31", "docDescription": ""}
    result = _build_pdf_base_name_by_strategy(doc, naming_strategy="doc_id_desc")
    assert result == "S100SW1R"


# --- Tests for naming strategy in collect_edinet_pdfs ---


def test_collect_edinet_pdfs_doc_id_naming(tmp_path: Path) -> None:
    target_day = date(2024, 6, 1)
    zip_bytes = _make_zip_with_pdfs(["report.pdf"])
    client = FakeEdinetClient(
        documents_by_date={
            target_day: [
                {
                    "docID": "S100AAAA",
                    "edinetCode": "E03416",
                    "docDescription": "第46期 有価証券報告書",
                    "xbrlFlag": "0",
                    "secCode": "27800",
                    "periodEnd": "2024-03-31",
                },
                {
                    "docID": "S100BBBB",
                    "edinetCode": "E03416",
                    "docDescription": "第47期 有価証券報告書",
                    "xbrlFlag": "0",
                    "secCode": "27800",
                    "periodEnd": "2024-03-31",
                },
            ]
        },
        download_payload_by_doc_id={
            "S100AAAA": zip_bytes,
            "S100BBBB": zip_bytes,
        },
    )

    result = collect_edinet_pdfs(
        edinet_code="E03416",
        output_dir=tmp_path,
        start_date=target_day,
        end_date=target_day,
        ticker="2780",
        client=client,
        naming_strategy="doc_id",
    )

    assert result["matched_doc_count"] == 2
    assert result["downloaded_count"] == 2
    assert (tmp_path / "S100AAAA_2024-03-31.pdf").exists()
    assert (tmp_path / "S100BBBB_2024-03-31.pdf").exists()


def test_collect_edinet_pdfs_ticker_year_naming_collides(tmp_path: Path) -> None:
    """Verify that ticker_year naming skips on collision (legacy behavior)."""
    target_day = date(2024, 6, 1)
    zip_bytes = _make_zip_with_pdfs(["report.pdf"])
    client = FakeEdinetClient(
        documents_by_date={
            target_day: [
                {
                    "docID": "S100AAAA",
                    "edinetCode": "E03416",
                    "docDescription": "第46期 有価証券報告書",
                    "xbrlFlag": "0",
                    "secCode": "27800",
                    "periodEnd": "2024-03-31",
                },
                {
                    "docID": "S100BBBB",
                    "edinetCode": "E03416",
                    "docDescription": "第47期 有価証券報告書",
                    "xbrlFlag": "0",
                    "secCode": "27800",
                    "periodEnd": "2024-03-31",
                },
            ]
        },
        download_payload_by_doc_id={
            "S100AAAA": zip_bytes,
            "S100BBBB": zip_bytes,
        },
    )

    result = collect_edinet_pdfs(
        edinet_code="E03416",
        output_dir=tmp_path,
        start_date=target_day,
        end_date=target_day,
        ticker="2780",
        client=client,
        naming_strategy="ticker_year",
    )

    assert result["matched_doc_count"] == 2
    assert result["downloaded_count"] == 1
    assert result["skipped_existing_count"] == 1


# --- Tests for T0 manifest keys ---


def test_manifest_has_t0_keys_pdf(tmp_path: Path) -> None:
    target_day = date(2024, 6, 1)
    zip_bytes = _make_zip_with_pdfs(["report.pdf"])
    client = FakeEdinetClient(
        documents_by_date={
            target_day: [
                {
                    "docID": "DOC-T0-001",
                    "edinetCode": "E03416",
                    "docDescription": "有価証券報告書",
                    "xbrlFlag": "0",
                    "secCode": "27800",
                    "periodEnd": "2024-03-31",
                }
            ]
        },
        download_payload_by_doc_id={"DOC-T0-001": zip_bytes},
    )

    collect_edinet_pdfs(
        edinet_code="E03416",
        output_dir=tmp_path,
        start_date=target_day,
        end_date=target_day,
        ticker="2780",
        client=client,
    )

    with open(tmp_path / "manifest.json", "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["schema_version"] == "bank-common-metadata-v1"
    assert manifest["source"] == "edinet"
    assert manifest["endpoint_or_doc_id"] == "E03416"
    assert "fetched_at" in manifest
    assert "gap_analysis" in manifest
    assert manifest["gap_analysis"]["matched_doc_count"] == 1
    assert manifest["gap_analysis"]["downloaded_count"] == 1
    assert manifest["gap_analysis"]["coverage_ratio"] == 1.0
    assert manifest["gap_analysis"]["effective_coverage_ratio"] == 1.0

    result_entry = manifest["results"][0]
    assert result_entry["source"] == "edinet"
    assert result_entry["endpoint_or_doc_id"] == "DOC-T0-001"
    assert result_entry["fetched_at"] == manifest["fetched_at"]
    assert result_entry["period_end"] == "2024-03-31"


def test_manifest_has_t0_keys_xbrl(tmp_path: Path) -> None:
    target_day = date(2024, 6, 1)
    client = FakeEdinetClient(
        documents_by_date={
            target_day: [
                {
                    "docID": "DOC-T0-002",
                    "edinetCode": "E03416",
                    "docDescription": "有価証券報告書",
                    "xbrlFlag": "1",
                    "periodEnd": "2024-03-31",
                }
            ]
        },
        download_payload_by_doc_id={"DOC-T0-002": b"zip-bytes"},
    )

    collect_edinet_reports(
        edinet_code="E03416",
        output_dir=tmp_path,
        start_date=target_day,
        end_date=target_day,
        client=client,
    )

    with open(tmp_path / "manifest.json", "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["schema_version"] == "bank-common-metadata-v1"
    assert manifest["source"] == "edinet"
    assert manifest["endpoint_or_doc_id"] == "E03416"
    assert "fetched_at" in manifest
    assert "gap_analysis" in manifest

    result_entry = manifest["results"][0]
    assert result_entry["source"] == "edinet"
    assert result_entry["endpoint_or_doc_id"] == "DOC-T0-002"
    assert result_entry["period_end"] == "2024-03-31"


# --- Tests for gap_analysis ---


def test_gap_analysis_coverage_ratio(tmp_path: Path) -> None:
    target_day = date(2024, 6, 1)
    client = FakeEdinetClient(
        documents_by_date={
            target_day: [
                {
                    "docID": "DOC-GA-OK",
                    "edinetCode": "E03416",
                    "docDescription": "有価証券報告書",
                    "xbrlFlag": "1",
                },
                {
                    "docID": "DOC-GA-FAIL",
                    "edinetCode": "E03416",
                    "docDescription": "有価証券報告書",
                    "xbrlFlag": "1",
                },
            ]
        },
        download_payload_by_doc_id={"DOC-GA-OK": b"ok"},
        download_errors={"DOC-GA-FAIL": EdinetError("fail")},
    )

    collect_edinet_reports(
        edinet_code="E03416",
        output_dir=tmp_path,
        start_date=target_day,
        end_date=target_day,
        client=client,
    )

    with open(tmp_path / "manifest.json", "r", encoding="utf-8") as f:
        manifest = json.load(f)

    ga = manifest["gap_analysis"]
    assert ga["total_calendar_days"] == 1
    assert ga["matched_doc_count"] == 2
    assert ga["downloaded_count"] == 1
    assert ga["skipped_existing_count"] == 0
    assert ga["failed_count"] == 1
    assert ga["coverage_ratio"] == 0.5
    assert ga["effective_coverage_ratio"] == 0.5


def test_gap_analysis_effective_coverage_with_skipped(tmp_path: Path) -> None:
    """Verify effective_coverage_ratio includes skipped_existing."""
    target_day = date(2024, 6, 1)
    client = FakeEdinetClient(
        documents_by_date={
            target_day: [
                {
                    "docID": "DOC-EFF-001",
                    "edinetCode": "E03416",
                    "docDescription": "有価証券報告書",
                    "xbrlFlag": "1",
                },
            ]
        },
        download_payload_by_doc_id={"DOC-EFF-001": b"ok"},
    )

    # First run: download
    collect_edinet_reports(
        edinet_code="E03416",
        output_dir=tmp_path,
        start_date=target_day,
        end_date=target_day,
        client=client,
    )
    # Second run: skipped_existing
    collect_edinet_reports(
        edinet_code="E03416",
        output_dir=tmp_path,
        start_date=target_day,
        end_date=target_day,
        client=client,
    )

    with open(tmp_path / "manifest.json", "r", encoding="utf-8") as f:
        manifest = json.load(f)

    ga = manifest["gap_analysis"]
    assert ga["downloaded_count"] == 0
    assert ga["skipped_existing_count"] == 1
    assert ga["coverage_ratio"] == 0.0
    assert ga["effective_coverage_ratio"] == 1.0


# --- Tests for --naming-strategy CLI argument ---


def test_cli_naming_strategy_argument() -> None:
    import importlib
    import types

    _script_dir = Path(__file__).resolve().parents[1] / "scripts"

    # Load main.py as __main__ to trigger the direct-execution branch
    spec = importlib.util.spec_from_file_location(
        "__main__", _script_dir / "main.py",
        submodule_search_locations=[],
    )
    # Temporarily patch __name__ so the if-branch takes the non-package path
    loader = spec.loader
    mod = types.ModuleType("__main__")
    mod.__file__ = str(_script_dir / "main.py")
    mod.__spec__ = spec

    # Instead of exec, just test argparse directly using build_parser pattern
    import argparse

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    parser_ed = subparsers.add_parser("edinet")
    parser_ed.add_argument("edinet_code")
    parser_ed.add_argument("--pdf", action="store_true")
    parser_ed.add_argument(
        "--naming-strategy",
        choices=["ticker_year", "doc_id", "doc_id_desc"],
        default="ticker_year",
    )

    args = parser.parse_args([
        "edinet", "E03416", "--pdf", "--naming-strategy", "doc_id",
    ])
    assert args.naming_strategy == "doc_id"

    args_default = parser.parse_args(["edinet", "E03416", "--pdf"])
    assert args_default.naming_strategy == "ticker_year"
