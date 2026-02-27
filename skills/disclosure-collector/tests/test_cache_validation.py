"""Tests for EDINET cache corruption detection and purge.

Covers:
- 302→notfound.html reproduction (mock)
- Content-Type validation in download_document
- HTML content detection (_looks_like_html)
- Cache file validation (_is_valid_cached_file)
- Corrupted cache scanning (scan_corrupted_cache)
- Purge functionality (purge_corrupted_cache)
- collect_edinet_reports / collect_edinet_pdfs re-download on corrupted cache
- Normal download regression (valid files are not affected)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import httpx
import pytest

from edinet import (
    MIN_VALID_DOC_SIZE,
    EdinetClient,
    EdinetError,
    _is_valid_cached_file,
    _looks_like_html,
    collect_edinet_pdfs,
    collect_edinet_reports,
    purge_corrupted_cache,
    scan_corrupted_cache,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOTFOUND_HTML = (
    b'<!DOCTYPE html><html><head><title>Not Found</title></head>'
    b'<body><h1>The requested document was not found.</h1></body></html>'
)

NOTFOUND_HTML_UPPER = (
    b'<HTML><HEAD><TITLE>Not Found</TITLE></HEAD>'
    b'<BODY><H1>Not Found</H1></BODY></HTML>'
)

VALID_ZIP_HEADER = b"PK\x03\x04" + b"\x00" * 2048  # fake but >1KB


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
        return self.download_payload_by_doc_id.get(doc_id, VALID_ZIP_HEADER)

    def download_pdf_zip(self, doc_id: str) -> bytes:
        self.download_calls.append(doc_id)
        if doc_id in self.download_errors:
            raise self.download_errors[doc_id]
        return self.download_payload_by_doc_id.get(doc_id, VALID_ZIP_HEADER)


def _make_zip_with_pdfs(filenames: list[str]) -> bytes:
    import io as _io
    import zipfile as _zf
    buf = _io.BytesIO()
    with _zf.ZipFile(buf, "w") as zf:
        for name in filenames:
            zf.writestr(name, "x" * 2048)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# _looks_like_html
# ---------------------------------------------------------------------------


class TestLooksLikeHtml:
    def test_detects_doctype_html(self) -> None:
        assert _looks_like_html(NOTFOUND_HTML)

    def test_detects_html_tag_uppercase(self) -> None:
        assert _looks_like_html(NOTFOUND_HTML_UPPER)

    def test_detects_html_with_leading_whitespace(self) -> None:
        assert _looks_like_html(b"  \n  <!DOCTYPE html><html>")

    def test_rejects_binary_zip(self) -> None:
        assert not _looks_like_html(VALID_ZIP_HEADER)

    def test_rejects_pdf(self) -> None:
        assert not _looks_like_html(b"%PDF-1.4 ...")

    def test_rejects_empty(self) -> None:
        assert not _looks_like_html(b"")


# ---------------------------------------------------------------------------
# _is_valid_cached_file
# ---------------------------------------------------------------------------


class TestIsValidCachedFile:
    def test_valid_large_file(self, tmp_path: Path) -> None:
        f = tmp_path / "good.zip"
        f.write_bytes(b"\x00" * 2048)
        assert _is_valid_cached_file(f)

    def test_empty_file_is_invalid(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.zip"
        f.write_bytes(b"")
        assert not _is_valid_cached_file(f)

    def test_small_html_is_invalid(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.zip"
        f.write_bytes(NOTFOUND_HTML)
        assert not _is_valid_cached_file(f)

    def test_small_binary_is_valid(self, tmp_path: Path) -> None:
        f = tmp_path / "tiny.zip"
        f.write_bytes(b"PK\x03\x04" + b"\x00" * 100)
        assert _is_valid_cached_file(f)

    def test_nonexistent_file_is_invalid(self, tmp_path: Path) -> None:
        assert not _is_valid_cached_file(tmp_path / "does_not_exist.zip")

    def test_390_bytes_html_is_invalid(self, tmp_path: Path) -> None:
        """Reproduce the exact 390-byte notfound.html corruption."""
        html = NOTFOUND_HTML[:390] if len(NOTFOUND_HTML) >= 390 else NOTFOUND_HTML + b"\x00" * (390 - len(NOTFOUND_HTML))
        f = tmp_path / "corrupted.zip"
        f.write_bytes(html)
        assert not _is_valid_cached_file(f)


# ---------------------------------------------------------------------------
# scan_corrupted_cache / purge_corrupted_cache
# ---------------------------------------------------------------------------


class TestScanCorruptedCache:
    def test_scan_finds_corrupted_zip(self, tmp_path: Path) -> None:
        (tmp_path / "good.zip").write_bytes(b"\x00" * 2048)
        (tmp_path / "bad.zip").write_bytes(NOTFOUND_HTML)
        (tmp_path / "unrelated.json").write_bytes(b"{}")

        result = scan_corrupted_cache(tmp_path)
        assert len(result) == 1
        assert result[0].name == "bad.zip"

    def test_scan_finds_corrupted_pdf(self, tmp_path: Path) -> None:
        (tmp_path / "bad.pdf").write_bytes(NOTFOUND_HTML)
        result = scan_corrupted_cache(tmp_path)
        assert len(result) == 1
        assert result[0].name == "bad.pdf"

    def test_scan_empty_dir(self, tmp_path: Path) -> None:
        assert scan_corrupted_cache(tmp_path) == []

    def test_scan_nonexistent_dir(self, tmp_path: Path) -> None:
        assert scan_corrupted_cache(tmp_path / "nonexistent") == []

    def test_scan_ignores_valid_files(self, tmp_path: Path) -> None:
        (tmp_path / "good.zip").write_bytes(b"\x00" * 2048)
        (tmp_path / "good.pdf").write_bytes(b"%PDF-1.4" + b"\x00" * 2048)
        assert scan_corrupted_cache(tmp_path) == []

    def test_scan_ignores_non_zip_pdf(self, tmp_path: Path) -> None:
        (tmp_path / "small.json").write_bytes(NOTFOUND_HTML)
        (tmp_path / "small.txt").write_bytes(NOTFOUND_HTML)
        assert scan_corrupted_cache(tmp_path) == []


class TestPurgeCorruptedCache:
    def test_purge_removes_corrupted(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.zip"
        bad.write_bytes(NOTFOUND_HTML)
        good = tmp_path / "good.zip"
        good.write_bytes(b"\x00" * 2048)

        removed = purge_corrupted_cache(tmp_path)
        assert len(removed) == 1
        assert removed[0].name == "bad.zip"
        assert not bad.exists()
        assert good.exists()

    def test_purge_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        assert purge_corrupted_cache(tmp_path) == []

    def test_purge_removes_multiple(self, tmp_path: Path) -> None:
        (tmp_path / "a.zip").write_bytes(NOTFOUND_HTML)
        (tmp_path / "b.pdf").write_bytes(NOTFOUND_HTML)
        removed = purge_corrupted_cache(tmp_path)
        assert len(removed) == 2


# ---------------------------------------------------------------------------
# download_document — response validation (httpx MockTransport)
# ---------------------------------------------------------------------------


class TestDownloadDocumentValidation:
    def test_rejects_html_content_type(self) -> None:
        """302→notfound.html: server returns text/html after redirect."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=NOTFOUND_HTML,
                headers={"content-type": "text/html; charset=utf-8"},
            )

        transport = httpx.MockTransport(handler)
        client = EdinetClient(api_key="test", transport=transport)

        with pytest.raises(EdinetError, match="HTML instead of document"):
            client.download_document("DOC-001", doc_type=5)

    def test_rejects_html_content_without_content_type(self) -> None:
        """Response has no explicit Content-Type but body is HTML."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=NOTFOUND_HTML,
                headers={"content-type": "application/octet-stream"},
            )

        transport = httpx.MockTransport(handler)
        client = EdinetClient(api_key="test", transport=transport)

        with pytest.raises(EdinetError, match="appears to be HTML"):
            client.download_document("DOC-001", doc_type=5)

    def test_accepts_valid_zip_response(self) -> None:
        """Normal ZIP download should succeed."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=VALID_ZIP_HEADER,
                headers={"content-type": "application/zip"},
            )

        transport = httpx.MockTransport(handler)
        client = EdinetClient(api_key="test", transport=transport)

        result = client.download_document("DOC-001", doc_type=1)
        assert result == VALID_ZIP_HEADER

    def test_accepts_valid_pdf_response(self) -> None:
        """Normal PDF download should succeed."""
        pdf_content = b"%PDF-1.4" + b"\x00" * 2048

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=pdf_content,
                headers={"content-type": "application/pdf"},
            )

        transport = httpx.MockTransport(handler)
        client = EdinetClient(api_key="test", transport=transport)

        result = client.download_document("DOC-001", doc_type=2)
        assert result == pdf_content

    def test_rejects_empty_response(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"")

        transport = httpx.MockTransport(handler)
        client = EdinetClient(api_key="test", transport=transport)

        with pytest.raises(EdinetError, match="empty"):
            client.download_document("DOC-001")


# ---------------------------------------------------------------------------
# collect_edinet_reports — corrupted cache re-download
# ---------------------------------------------------------------------------


class TestCollectReportsCorruptedCache:
    def test_redownloads_corrupted_zip(self, tmp_path: Path) -> None:
        """A corrupted .zip (HTML content) should trigger re-download."""
        target_day = date(2024, 3, 1)

        # Pre-plant corrupted cache
        corrupted_zip = tmp_path / "DOC-CORR.zip"
        corrupted_zip.write_bytes(NOTFOUND_HTML)

        client = FakeEdinetClient(
            documents_by_date={
                target_day: [
                    {
                        "docID": "DOC-CORR",
                        "edinetCode": "E03416",
                        "docDescription": "有価証券報告書",
                        "xbrlFlag": "1",
                    }
                ]
            },
            download_payload_by_doc_id={"DOC-CORR": VALID_ZIP_HEADER},
        )

        result = collect_edinet_reports(
            edinet_code="E03416",
            output_dir=tmp_path,
            start_date=target_day,
            end_date=target_day,
            client=client,
        )

        assert result["downloaded_count"] == 1
        assert result["skipped_existing_count"] == 0
        assert "DOC-CORR" in client.download_calls

        # The corrupted file should now be replaced with valid content
        assert corrupted_zip.read_bytes() == VALID_ZIP_HEADER

    def test_skips_valid_cached_zip(self, tmp_path: Path) -> None:
        """A valid .zip should still be skipped (regression test)."""
        target_day = date(2024, 3, 1)

        valid_zip = tmp_path / "DOC-VALID.zip"
        valid_zip.write_bytes(VALID_ZIP_HEADER)

        client = FakeEdinetClient(
            documents_by_date={
                target_day: [
                    {
                        "docID": "DOC-VALID",
                        "edinetCode": "E03416",
                        "docDescription": "有価証券報告書",
                        "xbrlFlag": "1",
                    }
                ]
            },
        )

        result = collect_edinet_reports(
            edinet_code="E03416",
            output_dir=tmp_path,
            start_date=target_day,
            end_date=target_day,
            client=client,
        )

        assert result["skipped_existing_count"] == 1
        assert result["downloaded_count"] == 0
        assert client.download_calls == []


# ---------------------------------------------------------------------------
# collect_edinet_pdfs — corrupted cache re-download
# ---------------------------------------------------------------------------


class TestCollectPdfsCorruptedCache:
    def test_redownloads_corrupted_pdf(self, tmp_path: Path) -> None:
        """A corrupted .pdf (HTML content) should trigger re-download."""
        target_day = date(2024, 6, 1)
        zip_bytes = _make_zip_with_pdfs(["report.pdf"])

        # Pre-plant corrupted PDF cache
        (tmp_path / "2780_有価証券報告書_2024.pdf").write_bytes(NOTFOUND_HTML)

        client = FakeEdinetClient(
            documents_by_date={
                target_day: [
                    {
                        "docID": "DOC-PDF-CORR",
                        "edinetCode": "E03416",
                        "docDescription": "第46期 有価証券報告書",
                        "xbrlFlag": "0",
                        "secCode": "27800",
                        "periodEnd": "2024-03-31",
                    }
                ]
            },
            download_payload_by_doc_id={"DOC-PDF-CORR": zip_bytes},
        )

        result = collect_edinet_pdfs(
            edinet_code="E03416",
            output_dir=tmp_path,
            start_date=target_day,
            end_date=target_day,
            ticker="2780",
            client=client,
        )

        assert result["downloaded_count"] == 1
        assert result["skipped_existing_count"] == 0
        assert "DOC-PDF-CORR" in client.download_calls

    def test_skips_valid_cached_pdf(self, tmp_path: Path) -> None:
        """A valid .pdf should still be skipped (regression test)."""
        target_day = date(2024, 6, 1)

        # Pre-create a valid large PDF
        (tmp_path / "2780_有価証券報告書_2024.pdf").write_bytes(b"%PDF-1.4" + b"\x00" * 2048)

        client = FakeEdinetClient(
            documents_by_date={
                target_day: [
                    {
                        "docID": "DOC-PDF-VALID",
                        "edinetCode": "E03416",
                        "docDescription": "第46期 有価証券報告書",
                        "xbrlFlag": "0",
                        "secCode": "27800",
                        "periodEnd": "2024-03-31",
                    }
                ]
            },
        )

        result = collect_edinet_pdfs(
            edinet_code="E03416",
            output_dir=tmp_path,
            start_date=target_day,
            end_date=target_day,
            ticker="2780",
            client=client,
        )

        assert result["skipped_existing_count"] == 1
        assert result["downloaded_count"] == 0
        assert client.download_calls == []


# ---------------------------------------------------------------------------
# MIN_VALID_DOC_SIZE constant
# ---------------------------------------------------------------------------


def test_min_valid_doc_size_is_reasonable() -> None:
    """MIN_VALID_DOC_SIZE should be at least 512 bytes (catch most HTML error pages)."""
    assert MIN_VALID_DOC_SIZE >= 512
    assert MIN_VALID_DOC_SIZE <= 4096
