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
    EdinetError,
    _build_pdf_base_name,
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
