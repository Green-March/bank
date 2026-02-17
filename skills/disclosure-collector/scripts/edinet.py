"""EDINET API v2 client and collection workflow."""

from __future__ import annotations

import io
import json
import os
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import httpx
from dotenv import load_dotenv


BASE_URL = "https://disclosure.edinet-fsa.go.jp/api/v2"
DEFAULT_TIMEOUT = 60.0
DEFAULT_START_DATE = date(2008, 1, 1)
DEFAULT_REPORT_KEYWORD = "有価証券報告書"
DOC_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")


class EdinetError(Exception):
    """EDINET API error."""


@dataclass(frozen=True)
class DownloadStatus:
    """Result for each docID."""

    doc_id: str
    status: str
    file_path: str | None
    error: str | None


class EdinetClient:
    """Client for EDINET API v2."""

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        base_url: str = BASE_URL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        load_dotenv()
        self._api_key = (
            api_key
            or os.environ.get("EDINET_API_KEY")
            or os.environ.get("EDINET_SUBSCRIPTION_KEY")
        )
        self._timeout = timeout
        self._base_url = base_url.rstrip("/")
        self._transport = transport

    def _auth_params(self) -> dict[str, str]:
        if self._api_key:
            return {"Subscription-Key": self._api_key}
        return {}

    def fetch_documents_for_date(self, target_date: date, doc_type: int = 2) -> list[dict]:
        """Fetch document list for a single date."""
        try:
            with httpx.Client(
                base_url=self._base_url,
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = client.get(
                    "/documents.json",
                    params={"date": target_date.isoformat(), "type": doc_type, **self._auth_params()},
                )
                response.raise_for_status()
        except httpx.TimeoutException as e:
            raise EdinetError(f"documents API timeout ({target_date.isoformat()}): {e}") from e
        except httpx.HTTPStatusError as e:
            raise EdinetError(
                "documents API error "
                f"({target_date.isoformat()}, status={e.response.status_code}): {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise EdinetError(f"documents API request failed ({target_date.isoformat()}): {e}") from e

        try:
            payload = response.json()
        except ValueError as e:
            raise EdinetError(f"documents API JSON parse failed ({target_date.isoformat()}): {e}") from e

        # EDINET API returns HTTP 200 even on auth errors; check JSON statusCode
        json_status = payload.get("statusCode")
        if json_status is not None:
            try:
                status_int = int(json_status)
            except (ValueError, TypeError) as e:
                raise EdinetError(
                    f"documents API returned unparseable statusCode={json_status!r} "
                    f"({target_date.isoformat()})"
                ) from e
            if status_int != 200:
                message = payload.get("message", "unknown error")
                raise EdinetError(
                    f"documents API returned statusCode={json_status} "
                    f"({target_date.isoformat()}): {message}"
                )

        results = payload.get("results")
        if not isinstance(results, list):
            raise EdinetError(
                "documents API response is invalid: "
                f"'results' is not list for date {target_date.isoformat()}"
            )
        return results

    def download_document(self, doc_id: str, doc_type: int = 1) -> bytes:
        """Download document zip by docID.

        Args:
            doc_id: EDINET document ID.
            doc_type: 1=XBRL, 2=PDF, 3=代替書面, 4=英文, 5=CSV.
        """
        try:
            with httpx.Client(
                base_url=self._base_url,
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = client.get(f"/documents/{doc_id}", params={"type": doc_type, **self._auth_params()})
                response.raise_for_status()
        except httpx.TimeoutException as e:
            raise EdinetError(f"download timeout (docID={doc_id}, type={doc_type}): {e}") from e
        except httpx.HTTPStatusError as e:
            raise EdinetError(
                f"download API error (docID={doc_id}, type={doc_type}, "
                f"status={e.response.status_code}): {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise EdinetError(f"download request failed (docID={doc_id}, type={doc_type}): {e}") from e

        if not response.content:
            raise EdinetError(f"download response is empty (docID={doc_id}, type={doc_type})")
        return response.content

    def download_xbrl_zip(self, doc_id: str) -> bytes:
        """Download XBRL zip by docID (type=1)."""
        return self.download_document(doc_id, doc_type=1)

    def download_pdf_zip(self, doc_id: str) -> bytes:
        """Download PDF zip by docID (type=2)."""
        return self.download_document(doc_id, doc_type=2)


def date_range(start_date: date, end_date: date) -> Iterable[date]:
    """Yield dates from start_date to end_date, inclusive."""
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def has_xbrl(document: dict) -> bool:
    """Return True when document has XBRL data."""
    flag = document.get("xbrlFlag")
    return flag in ("1", 1, True)


def is_safe_doc_id(doc_id: str) -> bool:
    """Return True when docID is safe to use as filename."""
    return bool(DOC_ID_PATTERN.fullmatch(doc_id))


def is_target_security_report(
    document: dict,
    target_edinet_code: str,
    report_keyword: str = DEFAULT_REPORT_KEYWORD,
    allowed_form_codes: set[str] | None = None,
    security_code: str | None = None,
    require_xbrl: bool = True,
    allowed_doc_type_codes: set[str] | None = None,
) -> bool:
    """Check whether a document matches target conditions."""
    if str(document.get("edinetCode", "")).strip() != target_edinet_code:
        return False

    if security_code is not None:
        sec_code = str(document.get("secCode", "")).strip()
        if sec_code != security_code:
            return False

    if allowed_doc_type_codes is not None:
        doc_type_code = str(document.get("docTypeCode", "")).strip()
        if doc_type_code not in allowed_doc_type_codes:
            return False

    if allowed_form_codes is not None:
        form_code = str(document.get("formCode", "")).strip()
        if form_code not in allowed_form_codes:
            return False

    description = str(document.get("docDescription", ""))
    if report_keyword not in description:
        return False

    if require_xbrl and not has_xbrl(document):
        return False

    return True


def _load_or_fetch_documents_for_date(
    client: EdinetClient,
    output_dir: Path,
    target_date: date,
) -> list[dict]:
    date_text = target_date.isoformat()
    cache_path = output_dir / f"documents_{date_text}.json"

    if cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise EdinetError(
                f"cached documents file is invalid: {cache_path}"
            )
        return payload["results"]

    results = client.fetch_documents_for_date(target_date=target_date)
    payload = {"date": date_text, "result_count": len(results), "results": results}
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return results


def _cleanup_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def _write_zip_atomically(zip_path: Path, content: bytes) -> None:
    tmp_path = zip_path.with_suffix(f"{zip_path.suffix}.tmp")
    _cleanup_file(tmp_path)

    try:
        with open(tmp_path, "wb") as f:
            f.write(content)
        tmp_path.replace(zip_path)
    except OSError:
        # Keep retry-safe state: no partial tmp/zip should remain.
        _cleanup_file(tmp_path)
        _cleanup_file(zip_path)
        raise


def _write_file_atomically(file_path: Path, content: bytes) -> None:
    tmp_path = file_path.with_suffix(f"{file_path.suffix}.tmp")
    _cleanup_file(tmp_path)

    try:
        with open(tmp_path, "wb") as f:
            f.write(content)
        tmp_path.replace(file_path)
    except OSError:
        _cleanup_file(tmp_path)
        _cleanup_file(file_path)
        raise


def _extract_pdfs_from_zip(zip_bytes: bytes, output_dir: Path, base_name: str) -> list[Path]:
    """Extract PDF files from a ZIP archive, or save raw PDF if not zipped.

    EDINET API type=2 may return a raw PDF (Content-Type: application/pdf)
    instead of a ZIP archive. This function handles both cases.

    Returns list of extracted PDF file paths.
    """
    extracted: list[Path] = []

    # Check if the response is a raw PDF (starts with %PDF-)
    if zip_bytes[:5] == b"%PDF-":
        pdf_path = output_dir / f"{base_name}.pdf"
        _write_file_atomically(pdf_path, zip_bytes)
        extracted.append(pdf_path)
        return extracted

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            pdf_entries = [n for n in zf.namelist() if n.lower().endswith(".pdf")]
            if len(pdf_entries) == 1:
                content = zf.read(pdf_entries[0])
                pdf_path = output_dir / f"{base_name}.pdf"
                _write_file_atomically(pdf_path, content)
                extracted.append(pdf_path)
            else:
                for i, entry in enumerate(pdf_entries):
                    content = zf.read(entry)
                    suffix = f"_{i + 1}" if len(pdf_entries) > 1 else ""
                    pdf_path = output_dir / f"{base_name}{suffix}.pdf"
                    _write_file_atomically(pdf_path, content)
                    extracted.append(pdf_path)
    except zipfile.BadZipFile as e:
        raise EdinetError(f"invalid ZIP for {base_name}: {e}") from e
    return extracted


def _build_pdf_base_name(document: dict, ticker: str | None = None) -> str:
    """Build a descriptive base filename from document metadata.

    Format: {ticker}_有価証券報告書_{periodEnd_year}
    """
    sec_code = str(document.get("secCode", "")).strip()
    if sec_code and len(sec_code) == 5 and sec_code[-1] == "0":
        sec_code = sec_code[:4]
    code = ticker or sec_code or "unknown"
    period_end = str(document.get("periodEnd", "")).strip()
    if period_end and len(period_end) >= 4:
        year = period_end[:4]
    else:
        submit_date = str(document.get("submitDateTime", "")).strip()
        year = submit_date[:4] if submit_date and len(submit_date) >= 4 else "unknown"

    description = str(document.get("docDescription", ""))
    doc_type_label = "有価証券報告書"
    if "訂正" in description:
        doc_type_label = "訂正有価証券報告書"

    return f"{code}_{doc_type_label}_{year}"


NAMING_STRATEGIES = ("ticker_year", "doc_id", "doc_id_desc")


def _build_pdf_base_name_by_strategy(
    document: dict,
    naming_strategy: str = "ticker_year",
    ticker: str | None = None,
) -> str:
    """Build PDF base filename using the specified naming strategy.

    Strategies:
        ticker_year: {ticker}_{docType}_{year} (legacy default)
        doc_id: {docID}_{periodEnd} (unique per document)
        doc_id_desc: {docID}_{docDescription_sanitized}
    """
    if naming_strategy == "doc_id":
        doc_id = str(document.get("docID", "")).strip()
        period_end = str(document.get("periodEnd", "")).strip()
        if period_end:
            return f"{doc_id}_{period_end}"
        return doc_id
    if naming_strategy == "doc_id_desc":
        doc_id = str(document.get("docID", "")).strip()
        description = str(document.get("docDescription", "")).strip()
        desc_safe = re.sub(r'[\\/:*?"<>|\s　]+', "_", description)[:30].rstrip("_")
        return f"{doc_id}_{desc_safe}" if desc_safe else doc_id
    # ticker_year (default, backward compatible)
    return _build_pdf_base_name(document, ticker=ticker)


def _build_manifest_t0_header(
    edinet_code: str,
    start: date,
    end: date,
    matched_count: int,
    downloaded_count: int,
    skipped_existing_count: int,
    failed_count: int,
) -> dict:
    """Build standard T0 common metadata and gap_analysis for manifest."""
    total_days = (end - start).days + 1
    coverage = downloaded_count / max(matched_count, 1) if matched_count else 0.0
    effective = (downloaded_count + skipped_existing_count) / max(matched_count, 1) if matched_count else 0.0
    return {
        "schema_version": "bank-common-metadata-v1",
        "source": "edinet",
        "endpoint_or_doc_id": edinet_code,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }, {
        "total_calendar_days": total_days,
        "matched_doc_count": matched_count,
        "downloaded_count": downloaded_count,
        "skipped_existing_count": skipped_existing_count,
        "failed_count": failed_count,
        "coverage_ratio": round(coverage, 4),
        "effective_coverage_ratio": round(effective, 4),
        "notes": [],
    }


def collect_edinet_pdfs(
    edinet_code: str,
    output_dir: Path | str,
    start_date: date | None = None,
    end_date: date | None = None,
    report_keyword: str = DEFAULT_REPORT_KEYWORD,
    allowed_form_codes: set[str] | None = None,
    security_code: str | None = None,
    ticker: str | None = None,
    client: EdinetClient | None = None,
    allowed_doc_type_codes: set[str] | None = None,
    naming_strategy: str = "ticker_year",
) -> dict:
    """Collect EDINET securities reports and download PDFs for each docID."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    start = start_date or DEFAULT_START_DATE
    end = end_date or date.today()
    if start > end:
        raise EdinetError("start_date must be earlier than or equal to end_date")

    edinet_client = client or EdinetClient()

    matched_docs_by_id: dict[str, dict] = {}
    failed_dates: list[dict[str, str]] = []

    for target_date in date_range(start, end):
        try:
            documents = _load_or_fetch_documents_for_date(
                client=edinet_client,
                output_dir=output_path,
                target_date=target_date,
            )
        except (EdinetError, OSError, ValueError, TypeError) as e:
            failed_dates.append(
                {"date": target_date.isoformat(), "error": str(e)}
            )
            continue

        for document in documents:
            if not isinstance(document, dict):
                continue
            if not is_target_security_report(
                document=document,
                target_edinet_code=edinet_code,
                report_keyword=report_keyword,
                allowed_form_codes=allowed_form_codes,
                security_code=security_code,
                require_xbrl=False,
                allowed_doc_type_codes=allowed_doc_type_codes,
            ):
                continue

            doc_id = str(document.get("docID", "")).strip()
            if not doc_id:
                continue
            matched_docs_by_id[doc_id] = document

    sorted_doc_ids = sorted(matched_docs_by_id.keys())
    download_statuses: list[DownloadStatus] = []
    failed_doc_ids: list[str] = []

    for doc_id in sorted_doc_ids:
        if not is_safe_doc_id(doc_id):
            failed_doc_ids.append(doc_id)
            download_statuses.append(
                DownloadStatus(
                    doc_id=doc_id,
                    status="failed",
                    file_path=None,
                    error="invalid docID format",
                )
            )
            continue

        document = matched_docs_by_id[doc_id]
        base_name = _build_pdf_base_name_by_strategy(
            document, naming_strategy=naming_strategy, ticker=ticker,
        )

        # Check if any PDF for this doc already exists
        existing = list(output_path.glob(f"{base_name}*.pdf"))
        if existing:
            download_statuses.append(
                DownloadStatus(
                    doc_id=doc_id,
                    status="skipped_existing",
                    file_path=str(existing[0]),
                    error=None,
                )
            )
            continue

        try:
            zip_bytes = edinet_client.download_pdf_zip(doc_id=doc_id)
            extracted = _extract_pdfs_from_zip(zip_bytes, output_path, base_name)
        except (EdinetError, OSError) as e:
            failed_doc_ids.append(doc_id)
            download_statuses.append(
                DownloadStatus(
                    doc_id=doc_id,
                    status="failed",
                    file_path=None,
                    error=str(e),
                )
            )
            continue

        if not extracted:
            failed_doc_ids.append(doc_id)
            download_statuses.append(
                DownloadStatus(
                    doc_id=doc_id,
                    status="failed",
                    file_path=None,
                    error="no PDF found in ZIP",
                )
            )
            continue

        download_statuses.append(
            DownloadStatus(
                doc_id=doc_id,
                status="downloaded",
                file_path=str(extracted[0]),
                error=None,
            )
        )

    downloaded_count = sum(1 for s in download_statuses if s.status == "downloaded")
    skipped_count = sum(1 for s in download_statuses if s.status == "skipped_existing")
    failed_count = sum(1 for s in download_statuses if s.status == "failed")

    t0_header, gap_analysis = _build_manifest_t0_header(
        edinet_code=edinet_code,
        start=start,
        end=end,
        matched_count=len(sorted_doc_ids),
        downloaded_count=downloaded_count,
        skipped_existing_count=skipped_count,
        failed_count=failed_count,
    )

    manifest = {
        **t0_header,
        "edinet_code": edinet_code,
        "security_code": security_code,
        "ticker": ticker,
        "report_keyword": report_keyword,
        "allowed_form_codes": sorted(allowed_form_codes) if allowed_form_codes else None,
        "download_format": "pdf",
        "naming_strategy": naming_strategy,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "matched_doc_count": len(sorted_doc_ids),
        "download_summary": {
            "attempted": len(sorted_doc_ids),
            "downloaded": downloaded_count,
            "skipped_existing": skipped_count,
            "failed": failed_count,
        },
        "gap_analysis": gap_analysis,
        "failed_dates": failed_dates,
        "failed_doc_ids": failed_doc_ids,
        "results": [
            {
                "doc_id": s.doc_id,
                "source": "edinet",
                "endpoint_or_doc_id": s.doc_id,
                "fetched_at": t0_header["fetched_at"],
                "doc_description": matched_docs_by_id.get(s.doc_id, {}).get("docDescription"),
                "period_start": matched_docs_by_id.get(s.doc_id, {}).get("periodStart"),
                "period_end": matched_docs_by_id.get(s.doc_id, {}).get("periodEnd"),
                "submit_date_time": matched_docs_by_id.get(s.doc_id, {}).get("submitDateTime"),
                "status": s.status,
                "file_path": s.file_path,
                "error": s.error,
            }
            for s in download_statuses
        ],
    }

    manifest_path = output_path / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    return {
        "manifest_path": str(manifest_path),
        "output_dir": str(output_path),
        "matched_doc_count": len(sorted_doc_ids),
        "downloaded_count": downloaded_count,
        "skipped_existing_count": skipped_count,
        "failed_count": failed_count,
        "failed_doc_ids": failed_doc_ids,
        "failed_dates": failed_dates,
    }


def collect_edinet_reports(
    edinet_code: str,
    output_dir: Path | str,
    start_date: date | None = None,
    end_date: date | None = None,
    report_keyword: str = DEFAULT_REPORT_KEYWORD,
    allowed_form_codes: set[str] | None = None,
    security_code: str | None = None,
    client: EdinetClient | None = None,
    allowed_doc_type_codes: set[str] | None = None,
) -> dict:
    """Collect EDINET securities reports and download XBRL zip for each docID."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    start = start_date or DEFAULT_START_DATE
    end = end_date or date.today()
    if start > end:
        raise EdinetError("start_date must be earlier than or equal to end_date")

    edinet_client = client or EdinetClient()

    matched_docs_by_id: dict[str, dict] = {}
    failed_dates: list[dict[str, str]] = []

    for target_date in date_range(start, end):
        try:
            documents = _load_or_fetch_documents_for_date(
                client=edinet_client,
                output_dir=output_path,
                target_date=target_date,
            )
        except (EdinetError, OSError, ValueError, TypeError) as e:
            failed_dates.append(
                {"date": target_date.isoformat(), "error": str(e)}
            )
            continue

        for document in documents:
            if not isinstance(document, dict):
                continue
            if not is_target_security_report(
                document=document,
                target_edinet_code=edinet_code,
                report_keyword=report_keyword,
                allowed_form_codes=allowed_form_codes,
                security_code=security_code,
                allowed_doc_type_codes=allowed_doc_type_codes,
            ):
                continue

            doc_id = str(document.get("docID", "")).strip()
            if not doc_id:
                continue
            matched_docs_by_id[doc_id] = document

    sorted_doc_ids = sorted(matched_docs_by_id.keys())
    download_statuses: list[DownloadStatus] = []
    failed_doc_ids: list[str] = []

    for doc_id in sorted_doc_ids:
        if not is_safe_doc_id(doc_id):
            failed_doc_ids.append(doc_id)
            download_statuses.append(
                DownloadStatus(
                    doc_id=doc_id,
                    status="failed",
                    file_path=None,
                    error="invalid docID format",
                )
            )
            continue

        zip_path = output_path / f"{doc_id}.zip"
        if zip_path.exists() and zip_path.stat().st_size > 0:
            download_statuses.append(
                DownloadStatus(
                    doc_id=doc_id,
                    status="skipped_existing",
                    file_path=str(zip_path),
                    error=None,
                )
            )
            continue

        try:
            content = edinet_client.download_xbrl_zip(doc_id=doc_id)
            _write_zip_atomically(zip_path=zip_path, content=content)
        except (EdinetError, OSError) as e:
            failed_doc_ids.append(doc_id)
            download_statuses.append(
                DownloadStatus(
                    doc_id=doc_id,
                    status="failed",
                    file_path=str(zip_path),
                    error=str(e),
                )
            )
            continue

        download_statuses.append(
            DownloadStatus(
                doc_id=doc_id,
                status="downloaded",
                file_path=str(zip_path),
                error=None,
            )
        )

    downloaded_count = sum(1 for status in download_statuses if status.status == "downloaded")
    skipped_count = sum(1 for status in download_statuses if status.status == "skipped_existing")
    failed_count = sum(1 for status in download_statuses if status.status == "failed")

    t0_header, gap_analysis = _build_manifest_t0_header(
        edinet_code=edinet_code,
        start=start,
        end=end,
        matched_count=len(sorted_doc_ids),
        downloaded_count=downloaded_count,
        skipped_existing_count=skipped_count,
        failed_count=failed_count,
    )

    manifest = {
        **t0_header,
        "edinet_code": edinet_code,
        "security_code": security_code,
        "report_keyword": report_keyword,
        "allowed_form_codes": sorted(allowed_form_codes) if allowed_form_codes else None,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "matched_doc_count": len(sorted_doc_ids),
        "download_summary": {
            "attempted": len(sorted_doc_ids),
            "downloaded": downloaded_count,
            "skipped_existing": skipped_count,
            "failed": failed_count,
        },
        "gap_analysis": gap_analysis,
        "failed_dates": failed_dates,
        "failed_doc_ids": failed_doc_ids,
        "results": [
            {
                "doc_id": status.doc_id,
                "source": "edinet",
                "endpoint_or_doc_id": status.doc_id,
                "fetched_at": t0_header["fetched_at"],
                "period_end": matched_docs_by_id.get(status.doc_id, {}).get("periodEnd"),
                "status": status.status,
                "file_path": status.file_path,
                "error": status.error,
            }
            for status in download_statuses
        ],
    }

    manifest_path = output_path / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    return {
        "manifest_path": str(manifest_path),
        "output_dir": str(output_path),
        "matched_doc_count": len(sorted_doc_ids),
        "downloaded_count": downloaded_count,
        "skipped_existing_count": skipped_count,
        "failed_count": failed_count,
        "failed_doc_ids": failed_doc_ids,
        "failed_dates": failed_dates,
    }
