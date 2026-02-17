"""EDINET XBRL parser for normalized BS/PL/CF extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from typing import Iterable, cast
import zipfile

from lxml import etree

BS_KEYS: tuple[str, ...] = (
    "total_assets",
    "current_assets",
    "noncurrent_assets",
    "total_liabilities",
    "current_liabilities",
    "total_equity",
    "net_assets",
)

PL_KEYS: tuple[str, ...] = (
    "revenue",
    "gross_profit",
    "operating_income",
    "ordinary_income",
    "net_income",
)

CF_KEYS: tuple[str, ...] = (
    "operating_cf",
    "investing_cf",
    "financing_cf",
    "free_cash_flow",
)

CONCEPT_ALIASES: dict[str, tuple[str, ...]] = {
    "total_assets": ("totalassets", "assetstotal"),
    "current_assets": ("currentassets",),
    "noncurrent_assets": ("noncurrentassets", "fixedassets"),
    "total_liabilities": ("totalliabilities", "liabilitiestotal"),
    "current_liabilities": ("currentliabilities",),
    "total_equity": (
        "totalequity",
        "shareholdersequity",
        "equityattributabletoownersofparent",
    ),
    "net_assets": ("netassets",),
    "revenue": ("netsales", "sales", "revenue", "operatingrevenue"),
    "gross_profit": ("grossprofit",),
    "operating_income": ("operatingincome", "operatingincomeloss"),
    "ordinary_income": ("ordinaryincome", "ordinaryincomeloss"),
    "net_income": (
        "profitloss",
        "netincome",
        "incomeloss",
        "profitattributabletoownersofparent",
    ),
    "operating_cf": ("netcashprovidedbyusedinoperatingactivities",),
    "investing_cf": ("netcashprovidedbyusedininvestingactivities",),
    "financing_cf": ("netcashprovidedbyusedinfinancingactivities",),
}

CONCEPT_TO_STATEMENT: dict[str, str] = {
    "total_assets": "bs",
    "current_assets": "bs",
    "noncurrent_assets": "bs",
    "total_liabilities": "bs",
    "current_liabilities": "bs",
    "total_equity": "bs",
    "net_assets": "bs",
    "revenue": "pl",
    "gross_profit": "pl",
    "operating_income": "pl",
    "ordinary_income": "pl",
    "net_income": "pl",
    "operating_cf": "cf",
    "investing_cf": "cf",
    "financing_cf": "cf",
}

COMPANY_NAME_CONCEPTS: tuple[str, ...] = (
    "filernameinjapanesedei",
    "companynamecoverpage",
    "entitycurrentlegalorregisteredname",
    "filernameinenglishdei",
)

_IDENTIFIER_PATTERN = re.compile(r"[^0-9a-z]+")
_NUMBER_PATTERN = re.compile(r"^[+-]?\d+(\.\d+)?$")


class ParserError(Exception):
    """Raised when EDINET parsing fails."""


@dataclass(frozen=True)
class ContextInfo:
    """Minimal context information for period grouping."""

    context_id: str
    period_type: str
    start_date: str | None
    end_date: str | None
    instant_date: str | None

    @property
    def period_end(self) -> str:
        if self.instant_date is not None:
            return self.instant_date
        if self.end_date is not None:
            return self.end_date
        return "unknown"


@dataclass
class PeriodFinancial:
    """Financial values grouped by comparable period end date."""

    period_end: str
    period_start: str | None
    period_type: str
    fiscal_year: int | None
    bs: dict[str, int | float | None] = field(
        default_factory=lambda: {key: None for key in BS_KEYS}
    )
    pl: dict[str, int | float | None] = field(
        default_factory=lambda: {key: None for key in PL_KEYS}
    )
    cf: dict[str, int | float | None] = field(
        default_factory=lambda: {key: None for key in CF_KEYS}
    )
    source_context_ids: list[str] = field(default_factory=list)
    period_end_original: str | None = None
    _scores: dict[str, int] = field(default_factory=dict)

    def set_metric(
        self,
        statement: str,
        key: str,
        value: int | float,
        priority: int,
        context_id: str,
    ) -> None:
        score_key = f"{statement}:{key}"
        existing_score = self._scores.get(score_key, -10**9)
        if priority >= existing_score:
            target = self.bs if statement == "bs" else self.pl if statement == "pl" else self.cf
            target[key] = value
            self._scores[score_key] = priority

        if context_id not in self.source_context_ids:
            self.source_context_ids.append(context_id)

    def finalize(self) -> None:
        # BUG-1b: BS fallback — total_assets = current_assets + noncurrent_assets
        if self.bs.get("total_assets") is None:
            current = self.bs.get("current_assets")
            noncurrent = self.bs.get("noncurrent_assets")
            if current is not None and noncurrent is not None:
                self.bs["total_assets"] = current + noncurrent

        operating_cf = self.cf["operating_cf"]
        investing_cf = self.cf["investing_cf"]
        if operating_cf is not None and investing_cf is not None:
            self.cf["free_cash_flow"] = operating_cf + investing_cf

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "period_end": self.period_end,
            "period_start": self.period_start,
            "period_type": self.period_type,
            "fiscal_year": self.fiscal_year,
            "bs": self.bs,
            "pl": self.pl,
            "cf": self.cf,
            "source_context_ids": self.source_context_ids,
        }
        if self.period_end_original is not None:
            result["period_end_original"] = self.period_end_original
        return result


@dataclass
class ParsedDocument:
    """Parsed result per EDINET zip."""

    ticker: str
    document_id: str
    source_zip: str
    company_name: str | None
    periods: list[PeriodFinancial]
    source: str | None = None
    endpoint_or_doc_id: str | None = None
    fetched_at: str | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "ticker": self.ticker,
            "document_id": self.document_id,
            "source_zip": self.source_zip,
            "company_name": self.company_name,
            "periods": [period.to_dict() for period in self.periods],
        }
        if self.source is not None:
            result["source"] = self.source
        if self.endpoint_or_doc_id is not None:
            result["endpoint_or_doc_id"] = self.endpoint_or_doc_id
        if self.fetched_at is not None:
            result["fetched_at"] = self.fetched_at
        return result


def normalize_identifier(value: str) -> str:
    """Normalize concept names for alias lookup."""
    return _IDENTIFIER_PATTERN.sub("", value.lower())


def _build_alias_lookup() -> dict[str, str]:
    alias_lookup: dict[str, str] = {}
    for canonical, aliases in CONCEPT_ALIASES.items():
        candidates = list(aliases)
        candidates.append(normalize_identifier(canonical))
        for alias in candidates:
            if alias in alias_lookup and alias_lookup[alias] != canonical:
                raise ValueError(f"Alias collision detected: {alias}")
            alias_lookup[alias] = canonical
    return alias_lookup


CONCEPT_ALIAS_LOOKUP = _build_alias_lookup()


def canonical_key_for_concept(concept_name: str) -> str | None:
    """Map concept local-name variants to canonical schema keys."""
    normalized = normalize_identifier(concept_name)
    return CONCEPT_ALIAS_LOOKUP.get(normalized)


def parse_numeric_value(raw_text: str, sign: str | None) -> int | float | None:
    """Parse XBRL numeric text to int/float while preserving null on non-numeric."""
    cleaned = raw_text.strip().replace(",", "").replace(" ", "")
    if cleaned in {"", "-", "－", "―"}:
        return None

    if not _NUMBER_PATTERN.match(cleaned):
        return None

    numeric = float(cleaned)
    if sign == "-":
        numeric = -abs(numeric)

    if numeric.is_integer():
        return int(numeric)
    return numeric


def context_priority(context_id: str) -> int:
    """Prioritize current year and consolidated contexts when duplicates exist."""
    normalized = context_id.lower()
    score = 0

    if "currentyear" in normalized:
        score += 100
    if "current" in normalized:
        score += 60
    if "consolidated" in normalized:
        score += 40
    if "nonconsolidated" in normalized:
        score -= 25
    if "prior" in normalized or "previous" in normalized:
        score -= 80

    return score


def fiscal_year_from_period_end(period_end: str) -> int | None:
    """Convert YYYY-MM-DD style period end date to integer fiscal year."""
    try:
        return int(period_end[:4])
    except (TypeError, ValueError):
        return None


def parse_contexts(root: etree._Element) -> dict[str, ContextInfo]:
    """Build context lookup table from XBRL root."""
    contexts: dict[str, ContextInfo] = {}
    for context in root.xpath(".//*[local-name()='context']"):
        context_id = context.get("id")
        if context_id is None:
            continue

        period_elements: list[etree._Element] = context.xpath("./*[local-name()='period']")
        if not period_elements:
            continue
        period = period_elements[0]

        instant = _first_text(period.xpath("./*[local-name()='instant']"))
        start_date = _first_text(period.xpath("./*[local-name()='startDate']"))
        end_date = _first_text(period.xpath("./*[local-name()='endDate']"))

        if instant is not None:
            period_type = "instant"
        elif start_date is not None or end_date is not None:
            period_type = "duration"
        else:
            period_type = "unknown"

        contexts[context_id] = ContextInfo(
            context_id=context_id,
            period_type=period_type,
            start_date=start_date,
            end_date=end_date,
            instant_date=instant,
        )
    return contexts


def _first_text(elements: Iterable[etree._Element]) -> str | None:
    for element in elements:
        if element.text is None:
            continue
        stripped = element.text.strip()
        if stripped:
            return stripped
    return None


def _choose_xbrl_member(zip_file: zipfile.ZipFile) -> str:
    xbrl_candidates = [
        name
        for name in zip_file.namelist()
        if name.lower().endswith(".xbrl") and not name.endswith("/")
    ]
    if not xbrl_candidates:
        raise ParserError("No .xbrl member found in zip archive.")

    preferred = sorted(
        xbrl_candidates,
        key=lambda name: (
            "publicdoc" not in name.lower(),
            len(name),
            name.lower(),
        ),
    )
    return preferred[0]


def parse_edinet_zip(zip_path: Path, ticker: str) -> ParsedDocument:
    """Parse one EDINET zip file and return normalized statement data."""
    if not zip_path.exists():
        raise ParserError(f"Zip file not found: {zip_path}")

    try:
        with zipfile.ZipFile(zip_path) as archive:
            member_name = _choose_xbrl_member(archive)
            xbrl_bytes = archive.read(member_name)
    except zipfile.BadZipFile as exc:
        raise ParserError(f"Invalid zip file: {zip_path}") from exc
    except OSError as exc:
        raise ParserError(f"Failed reading zip file: {zip_path}") from exc

    try:
        root = etree.fromstring(
            xbrl_bytes,
            parser=etree.XMLParser(
                resolve_entities=False,
                no_network=True,
                load_dtd=False,
                recover=False,
                huge_tree=False,
            ),
        )
    except etree.XMLSyntaxError as exc:
        raise ParserError(f"Invalid XBRL XML in {zip_path.name}") from exc

    contexts = parse_contexts(root)
    periods: dict[str, PeriodFinancial] = {}
    company_name: str | None = None

    for element in root.xpath(".//*[@contextRef]"):
        context_id = element.get("contextRef")
        if context_id is None:
            continue
        context = contexts.get(context_id)
        if context is None:
            continue

        try:
            concept_local_name = etree.QName(element).localname
        except ValueError:
            continue
        normalized_concept = normalize_identifier(concept_local_name)

        text = (element.text or "").strip()
        if not text:
            continue

        if company_name is None and normalized_concept in COMPANY_NAME_CONCEPTS:
            company_name = text

        canonical = canonical_key_for_concept(concept_local_name)
        if canonical is None:
            continue

        statement = CONCEPT_TO_STATEMENT[canonical]
        value = parse_numeric_value(text, element.get("sign"))
        if value is None:
            continue

        period_end = context.period_end
        if period_end not in periods:
            periods[period_end] = PeriodFinancial(
                period_end=period_end,
                period_start=context.start_date,
                period_type=context.period_type,
                fiscal_year=fiscal_year_from_period_end(period_end),
            )

        period = periods[period_end]
        if period.period_start is None and context.start_date is not None:
            period.period_start = context.start_date

        if period.period_type != context.period_type:
            known_types = {period.period_type, context.period_type}
            if known_types == {"instant", "duration"}:
                period.period_type = "mixed"
            elif period.period_type == "unknown":
                period.period_type = context.period_type

        priority = context_priority(context.context_id)
        period.set_metric(statement, canonical, value, priority, context.context_id)

    for period in periods.values():
        period.finalize()

    sorted_periods = sorted(periods.values(), key=lambda item: item.period_end)
    return ParsedDocument(
        ticker=ticker,
        document_id=zip_path.stem,
        source_zip=str(zip_path),
        company_name=company_name,
        periods=sorted_periods,
    )


def parse_edinet_directory(input_dir: Path, ticker: str) -> list[ParsedDocument]:
    """Parse all EDINET zip files under input_dir."""
    zip_files = sorted(input_dir.glob("*.zip"))
    if not zip_files:
        raise ParserError(f"No zip files found in: {input_dir}")

    documents: list[ParsedDocument] = []
    for zip_file in zip_files:
        documents.append(parse_edinet_zip(zip_file, ticker=ticker))
    return documents


def build_period_index(documents: list[ParsedDocument]) -> list[dict[str, object]]:
    """Merge period-level metrics across documents for easier fiscal comparison."""
    merged: dict[str, dict[str, object]] = {}

    for document in documents:
        for period in document.periods:
            if period.period_end not in merged:
                merged[period.period_end] = {
                    "period_end": period.period_end,
                    "period_start": period.period_start,
                    "period_type": period.period_type,
                    "fiscal_year": period.fiscal_year,
                    "bs": {key: None for key in BS_KEYS},
                    "pl": {key: None for key in PL_KEYS},
                    "cf": {key: None for key in CF_KEYS},
                    "source_document_ids": [],
                }

            entry = merged[period.period_end]
            entry_bs = cast(dict[str, int | float | None], entry["bs"])
            entry_pl = cast(dict[str, int | float | None], entry["pl"])
            entry_cf = cast(dict[str, int | float | None], entry["cf"])
            source_document_ids = cast(list[str], entry["source_document_ids"])

            _merge_statement(entry_bs, period.bs)
            _merge_statement(entry_pl, period.pl)
            _merge_statement(entry_cf, period.cf)

            if document.document_id not in source_document_ids:
                source_document_ids.append(document.document_id)

    return [merged[key] for key in sorted(merged.keys())]


def _merge_statement(
    destination: dict[str, int | float | None],
    source: dict[str, int | float | None],
) -> None:
    for key, value in source.items():
        if destination.get(key) is None and value is not None:
            destination[key] = value


def write_outputs(
    documents: list[ParsedDocument],
    output_dir: Path,
    ticker: str,
) -> dict[str, str]:
    """Write per-document JSON and aggregate financials.json output."""
    output_dir.mkdir(parents=True, exist_ok=True)

    saved_files: dict[str, str] = {}
    for document in documents:
        path = output_dir / f"{document.document_id}.json"
        with path.open("w", encoding="utf-8") as file:
            json.dump(document.to_dict(), file, ensure_ascii=False, indent=2)
        saved_files[document.document_id] = str(path)

    aggregate_path = output_dir / "financials.json"
    aggregate = {
        "ticker": ticker,
        "generated_at": datetime.now(UTC).isoformat(),
        "document_count": len(documents),
        "documents": [document.to_dict() for document in documents],
        "period_index": build_period_index(documents),
        "schema": {
            "bs": list(BS_KEYS),
            "pl": list(PL_KEYS),
            "cf": list(CF_KEYS),
        },
    }
    with aggregate_path.open("w", encoding="utf-8") as file:
        json.dump(aggregate, file, ensure_ascii=False, indent=2)
    saved_files["financials"] = str(aggregate_path)

    return saved_files
