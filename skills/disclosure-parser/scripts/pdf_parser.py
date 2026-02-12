"""PDF parser for Japanese securities reports (有価証券報告書).

Extracts BS/PL/CF tables from PDF using pdfplumber and produces
the same ParsedDocument / PeriodFinancial output as the XBRL parser.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

from parser import (
    BS_KEYS,
    CF_KEYS,
    PL_KEYS,
    ParsedDocument,
    PeriodFinancial,
    fiscal_year_from_period_end,
)

__version__ = "0.3.0"

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Unit detection
# ---------------------------------------------------------------------------

UNIT_PATTERNS: list[tuple[re.Pattern[str], int, str]] = [
    (re.compile(r"[（(]?\s*単位\s*[：:]\s*百万円\s*[）)]?|[（(]\s*百万円\s*[）)]"), 1_000_000, "百万円"),
    (re.compile(r"[（(]?\s*単位\s*[：:]\s*千円\s*[）)]?|[（(]\s*千円\s*[）)]"), 1_000, "千円"),
    (re.compile(r"[（(]?\s*単位\s*[：:]\s*円\s*[）)]?|[（(]\s*円\s*[）)]"), 1, "円"),
]

DEFAULT_MULTIPLIER = 1_000_000
DEFAULT_UNIT_LABEL = "百万円（デフォルト）"


def detect_unit(text: str) -> tuple[int, str]:
    """Detect monetary unit from text near a table.

    Returns (multiplier, label).
    """
    for pattern, multiplier, label in UNIT_PATTERNS:
        if pattern.search(text):
            return multiplier, label
    return DEFAULT_MULTIPLIER, DEFAULT_UNIT_LABEL


# ---------------------------------------------------------------------------
# Negative sign normalisation & numeric parsing
# ---------------------------------------------------------------------------

_FOOTNOTE_RE = re.compile(r"※[０-９]*[,、]?\s*")
_FULLWIDTH_MINUS = re.compile(r"[－﹣−‐]")
_PAREN_NEG_RE = re.compile(r"^[（(]\s*(.+?)\s*[）)]$")
_TRIANGLE_RE = re.compile(r"^[△▲]\s*")
_COMMA_RE = re.compile(r",")
_EMPTY_VALUES = {"", "-", "－", "―", "—", "−", "–"}


def normalize_value(raw: str | None, multiplier: int = 1) -> int | None:
    """Parse a Japanese financial table cell to an integer yen amount.

    Returns None for blank / dash cells.
    """
    if raw is None:
        return None

    text = raw.strip()
    text = _FOOTNOTE_RE.sub("", text).strip()

    if text in _EMPTY_VALUES:
        return None

    negative = False
    m = _PAREN_NEG_RE.match(text)
    if m:
        text = m.group(1)
        negative = True

    if _TRIANGLE_RE.match(text):
        text = _TRIANGLE_RE.sub("", text)
        negative = True

    text = _FULLWIDTH_MINUS.sub("-", text)
    if text.startswith("-"):
        text = text[1:]
        negative = True

    text = _COMMA_RE.sub("", text).strip()

    if not text:
        return None

    try:
        value = float(text)
    except ValueError:
        return None

    if negative:
        value = -abs(value)

    return int(value * multiplier)


# ---------------------------------------------------------------------------
# Statement classification — strict consolidated headers
# ---------------------------------------------------------------------------

# Strict bracket-enclosed headers for consolidated financial statements.
# These appear as section titles like "①【連結貸借対照表】" in the PDF text.
_CONSOLIDATED_BS_RE = re.compile(r"【連結貸借対照表】")
_CONSOLIDATED_PL_RE = re.compile(r"【連結損益計算書(?:及び連結包括利益計算書)?】")
_CONSOLIDATED_CF_RE = re.compile(r"【連結キャッシュ・フロー計算書】")

# Fallback for companies without consolidated statements
_STANDALONE_BS_RE = re.compile(r"【貸借対照表】")
_STANDALONE_PL_RE = re.compile(r"【損益計算書】")
_STANDALONE_CF_RE = re.compile(r"【キャッシュ・フロー計算書】")


def classify_statement(page_text: str) -> str | None:
    """Return 'bs', 'pl', or 'cf' based on bracketed section headers.

    Prioritises consolidated (連結) statements.  Returns None if no
    financial-statement header is found on the page.
    """
    for pattern, label in [
        (_CONSOLIDATED_BS_RE, "bs"),
        (_CONSOLIDATED_PL_RE, "pl"),
        (_CONSOLIDATED_CF_RE, "cf"),
    ]:
        if pattern.search(page_text):
            return label

    for pattern, label in [
        (_STANDALONE_BS_RE, "bs"),
        (_STANDALONE_PL_RE, "pl"),
        (_STANDALONE_CF_RE, "cf"),
    ]:
        if pattern.search(page_text):
            return label

    return None


# ---------------------------------------------------------------------------
# Period extraction from table headers
# ---------------------------------------------------------------------------

_ERA_OFFSETS: dict[str, int] = {
    "令和": 2018,
    "平成": 1988,
    "昭和": 1925,
}

# Western calendar: 2024年３月31日
_WESTERN_DATE_RE = re.compile(
    r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
)
# Japanese era: 平成27年３月31日
_ERA_DATE_RE = re.compile(
    r"(令和|平成|昭和)\s*(\d{1,2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
)

_INSTANT_DATE_RE = _WESTERN_DATE_RE
_DURATION_START_RE = re.compile(
    r"自\s*(?:(\d{4})\s*年|(令和|平成|昭和)\s*(\d{1,2})\s*年)\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
)
_DURATION_END_RE = re.compile(
    r"至\s*(?:(\d{4})\s*年|(令和|平成|昭和)\s*(\d{1,2})\s*年)\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
)


def _era_to_western(era: str, era_year: int) -> int:
    return _ERA_OFFSETS.get(era, 0) + era_year


def _parse_date_from_text(text: str) -> str | None:
    """Parse a single date (Western or era) from text and return ISO format."""
    m = _WESTERN_DATE_RE.search(text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    m = _ERA_DATE_RE.search(text)
    if m:
        year = _era_to_western(m.group(1), int(m.group(2)))
        return f"{year}-{int(m.group(3)):02d}-{int(m.group(4)):02d}"

    return None


def _parse_duration_start(text: str) -> str | None:
    """Parse 自 YYYY年M月D日 or 自 平成N年M月D日."""
    m = _DURATION_START_RE.search(text)
    if not m:
        return None
    if m.group(1):  # Western
        year = int(m.group(1))
    else:  # Era
        year = _era_to_western(m.group(2), int(m.group(3)))
    return f"{year}-{int(m.group(4)):02d}-{int(m.group(5)):02d}"


def _parse_duration_end(text: str) -> str | None:
    """Parse 至 YYYY年M月D日 or 至 平成N年M月D日."""
    m = _DURATION_END_RE.search(text)
    if not m:
        return None
    if m.group(1):  # Western
        year = int(m.group(1))
    else:  # Era
        year = _era_to_western(m.group(2), int(m.group(3)))
    return f"{year}-{int(m.group(4)):02d}-{int(m.group(5)):02d}"


def _match_to_iso(m: re.Match[str]) -> str:
    year, month, day = m.group(1), m.group(2), m.group(3)
    return f"{year}-{int(month):02d}-{int(day):02d}"


@dataclass
class PeriodInfo:
    """Parsed period metadata from a column header."""

    period_start: str | None
    period_end: str
    period_type: str  # "instant" or "duration"
    label: str  # "prior" or "current"


def parse_column_header(header_text: str) -> PeriodInfo | None:
    """Extract period information from a table column header.

    Supports both Western (2024年) and Japanese era (平成27年) dates.
    """
    if not header_text:
        return None

    label = "current"
    if "前" in header_text:
        label = "prior"

    start_date = _parse_duration_start(header_text)
    end_date = _parse_duration_end(header_text)
    if start_date and end_date:
        return PeriodInfo(
            period_start=start_date,
            period_end=end_date,
            period_type="duration",
            label=label,
        )

    instant_date = _parse_date_from_text(header_text)
    if instant_date:
        return PeriodInfo(
            period_start=None,
            period_end=instant_date,
            period_type="instant",
            label=label,
        )

    return None


# ---------------------------------------------------------------------------
# Japanese concept name → canonical key mapping
# ---------------------------------------------------------------------------

PDF_CONCEPT_ALIASES: dict[str, list[str]] = {
    # BS
    "total_assets": ["資産合計", "総資産", "総資産額"],
    "current_assets": ["流動資産合計"],
    "total_liabilities": ["負債合計", "負債の部合計"],
    "current_liabilities": ["流動負債合計"],
    "total_equity": ["純資産合計", "純資産の部合計"],
    "net_assets": ["純資産合計", "純資産の部合計"],
    # PL
    "revenue": ["売上高", "営業収益"],
    "gross_profit": ["売上総利益"],
    "operating_income": ["営業利益"],
    "ordinary_income": ["経常利益"],
    "net_income": [
        "親会社株主に帰属する当期純利益",
        "親会社株主に帰属する当期純損失",
        "当期純利益",
        "当期純損失",
    ],
    # CF
    "operating_cf": ["営業活動によるキャッシュ・フロー"],
    "investing_cf": ["投資活動によるキャッシュ・フロー"],
    "financing_cf": ["財務活動によるキャッシュ・フロー"],
}

_CONCEPT_LOOKUP: dict[str, str] = {}
for _canonical, _aliases in PDF_CONCEPT_ALIASES.items():
    for _alias in _aliases:
        if _alias not in _CONCEPT_LOOKUP:
            _CONCEPT_LOOKUP[_alias] = _canonical

CONCEPT_TO_STATEMENT: dict[str, str] = {
    "total_assets": "bs",
    "current_assets": "bs",
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


def map_concept(japanese_name: str) -> str | None:
    """Map a Japanese concept name to a canonical key.

    Tries exact match first, then prefix match for concept names that
    include suffixes like "又は...純損失（△）".
    """
    cleaned = japanese_name.strip()
    result = _CONCEPT_LOOKUP.get(cleaned)
    if result is not None:
        return result

    # Prefix match: "親会社株主に帰属する当期純利益又は..." → net_income
    for alias, canonical in _CONCEPT_LOOKUP.items():
        if cleaned.startswith(alias):
            return canonical

    return None


# ---------------------------------------------------------------------------
# PDF discovery
# ---------------------------------------------------------------------------

_YEAR_RE = re.compile(r"_(\d{4})(?:\.pdf)?$", re.IGNORECASE)


def discover_pdfs(input_path: Path, ticker: str) -> list[Path]:
    """Find and sort PDFs matching the naming convention."""
    pattern = f"{ticker}_有価証券報告書_*.pdf"
    return sorted(
        input_path.glob(pattern),
        key=lambda p: (_extract_year(p), p.name),
    )


def _extract_year(path: Path) -> int:
    m = _YEAR_RE.search(path.stem)
    return int(m.group(1)) if m else 0


def load_manifest_doc_ids(input_path: Path) -> dict[str, str]:
    """Load doc_id mapping from manifest.json if present.

    Returns {normalised_filename: doc_id}.
    """
    manifest_path = input_path / "manifest.json"
    if not manifest_path.exists():
        return {}

    try:
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

    mapping: dict[str, str] = {}
    for result in manifest.get("results", []):
        file_path = result.get("file_path")
        doc_id = result.get("doc_id")
        if file_path and doc_id:
            mapping[Path(file_path).name] = doc_id

    matched_count = manifest.get("matched_doc_count")
    if matched_count is not None and len(mapping) != matched_count:
        logger.warning(
            "manifest.matched_doc_count=%s but found %s file_path entries",
            matched_count,
            len(mapping),
        )

    return mapping


# ---------------------------------------------------------------------------
# Multi-strategy table extraction
# ---------------------------------------------------------------------------

STRATEGIES: list[dict] = [
    {"id": "S1", "name": "lines/lines",
     "settings": {"vertical_strategy": "lines", "horizontal_strategy": "lines"}},
    {"id": "S2", "name": "text/text",
     "settings": {"vertical_strategy": "text", "horizontal_strategy": "text",
                  "snap_tolerance": 5, "join_tolerance": 5}},
    {"id": "S3", "name": "text/lines",
     "settings": {"vertical_strategy": "text", "horizontal_strategy": "lines"}},
]


def _concept_score(data_rows: list[list[str | None]]) -> int:
    """Count unique recognised financial concepts in data rows."""
    found: set[str] = set()
    for row in data_rows:
        if row and row[0]:
            c = map_concept((row[0] or "").strip())
            if c is not None:
                found.add(c)
    return len(found)


@dataclass
class ExtractedStatement:
    """Data extracted from one financial statement across pages."""

    statement_type: str  # "bs", "pl", "cf"
    periods: list[PeriodInfo]
    rows: list[list[str | None]]
    pages: list[int]
    unit_multiplier: int
    unit_label: str
    strategy_id: str = "S1"
    concept_score: int = 0


@dataclass
class _PageScan:
    """Result of scanning a single page for statement headers."""

    page_idx: int
    page_num: int
    statement_type: str


def _scan_statement_headers(pdf: pdfplumber.PDF) -> list[_PageScan]:
    """Pass 1: find pages with consolidated financial statement headers."""
    results: list[_PageScan] = []
    for idx, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        stmt_type = classify_statement(text)
        if stmt_type is not None:
            results.append(_PageScan(page_idx=idx, page_num=idx + 1, statement_type=stmt_type))
    return results


def _is_continuation_page(page: pdfplumber.pdf.Page, expected_cols: int) -> bool:
    """Check if a page continues the previous statement table."""
    tables = page.extract_tables()
    if not tables:
        return False

    # Check if any table row has the expected column count and a unit marker
    for table in tables:
        for row in table[:3]:
            if not row:
                continue
            if len(row) != expected_cols:
                continue
            row_text = " ".join(cell or "" for cell in row)
            if "単位" in row_text or "千円" in row_text or "百万円" in row_text:
                return True
    return False


# Pattern to match a financial data line in raw text:
# "科目名  1,234,567  2,345,678"
_TEXT_LINE_RE = re.compile(
    r"^(.+?)\s+"
    r"([※０-９\d△▲（(－\-][^\n]*?)\s+"
    r"([※０-９\d△▲（(－\-][^\n]*?)$",
    re.MULTILINE,
)

_TEXT_LINE_2COL_RE = re.compile(
    r"^(.+?)\s+"
    r"([※０-９\d△▲（(－\-][,\d０-９,．.※]+)$",
    re.MULTILINE,
)


def _extract_concepts_from_text(
    page_text: str,
    num_columns: int,
) -> list[list[str | None]]:
    """Fallback: extract concept→value rows from raw page text.

    Looks for lines like "科目名  1,234,567  2,345,678".
    Only returns rows where the first cell matches a known concept.
    """
    rows: list[list[str | None]] = []

    if num_columns >= 3:
        for m in _TEXT_LINE_RE.finditer(page_text):
            name = m.group(1).strip()
            if map_concept(name) is not None:
                rows.append([name, m.group(2).strip(), m.group(3).strip()])
    else:
        for m in _TEXT_LINE_2COL_RE.finditer(page_text):
            name = m.group(1).strip()
            if map_concept(name) is not None:
                rows.append([name, m.group(2).strip()])

    return rows


def _merge_tables(tables: list[list[list[str | None]]]) -> list[list[str | None]]:
    """Merge tables with the most common column count, dedup headers, skip blanks."""
    if not tables:
        return []

    # Find the most common column count (typically 3: item, prior, current)
    col_counts: dict[int, int] = {}
    for t in tables:
        for row in t:
            if row:
                n = len(row)
                col_counts[n] = col_counts.get(n, 0) + 1
    if not col_counts:
        return []

    target_cols = max(col_counts, key=lambda k: col_counts[k])

    merged: list[list[str | None]] = []
    seen_headers: set[str] = set()
    for t in tables:
        for row in t:
            if not row or len(row) != target_cols:
                continue
            # Keep unit/period header rows (may have empty first cell) but dedup
            if _is_unit_row(row) or _is_period_header_row(row):
                key = "|".join(c or "" for c in row)
                if key in seen_headers:
                    continue
                seen_headers.add(key)
                merged.append(row)
                continue
            # For data rows, skip if first cell (item name) is empty
            first = (row[0] or "").strip()
            if not first:
                continue
            merged.append(row)
    return merged


def _is_unit_row(row: list[str | None]) -> bool:
    """Check if a table row is a unit header row."""
    text = " ".join(cell or "" for cell in row)
    return "単位" in text or "千円" in text or "百万円" in text


def _is_period_header_row(row: list[str | None]) -> bool:
    """Check if a table row contains period headers."""
    for cell in row:
        if cell and ("年度" in cell or ("年" in cell and "月" in cell)):
            return True
    return False


def _extract_table_from_page(
    page: pdfplumber.pdf.Page,
    is_header_page: bool,
    table_settings: dict | None = None,
) -> tuple[list[PeriodInfo], list[list[str | None]], int, str]:
    """Extract table data from a single page.

    Merges all tables on the page, then supplements with text-based
    fallback for rows that pdfplumber's table detection missed.
    Returns (periods, data_rows, unit_multiplier, unit_label).
    """
    page_text = page.extract_text() or ""
    if table_settings is not None:
        tables = page.extract_tables(table_settings=table_settings)
    else:
        tables = page.extract_tables()

    merged = _merge_tables(tables) if tables else []

    # Detect unit from page text or early rows
    multiplier, unit_label = detect_unit(page_text)
    if unit_label == DEFAULT_UNIT_LABEL and merged:
        for row in merged[:3]:
            for cell in row:
                if cell:
                    m, l = detect_unit(cell)
                    if l != DEFAULT_UNIT_LABEL:
                        multiplier, unit_label = m, l
                        break
            if unit_label != DEFAULT_UNIT_LABEL:
                break

    # Parse period headers
    periods: list[PeriodInfo] = []
    data_start = 0

    for i, row in enumerate(merged[:4]):
        if _is_unit_row(row):
            data_start = i + 1
            continue
        if _is_period_header_row(row):
            if is_header_page or not periods:
                for cell in row:
                    if cell:
                        info = parse_column_header(cell)
                        if info:
                            periods.append(info)
            data_start = i + 1
            continue
        break

    data_rows: list[list[str | None]] = []

    for row in merged[data_start:]:
        if row and len(row) >= 2:
            data_rows.append(row)

    return periods, data_rows, multiplier, unit_label


def _try_strategies(
    pages: list[pdfplumber.pdf.Page],
    is_header_flags: list[bool],
) -> tuple[list[PeriodInfo], list[list[str | None]], int, str, str, int]:
    """Try multiple table_settings strategies, pick the best one.

    Selection: (period_count, concept_score) — more periods wins first,
    then higher concept_score breaks ties.
    Returns (periods, data_rows, multiplier, unit_label, strategy_id, score).
    """
    candidates: list[tuple[list[PeriodInfo], list[list[str | None]], int, str, str, int]] = []

    for strategy in STRATEGIES:
        all_periods: list[PeriodInfo] = []
        all_rows: list[list[str | None]] = []
        multiplier = DEFAULT_MULTIPLIER
        unit_label = DEFAULT_UNIT_LABEL

        for page, is_header in zip(pages, is_header_flags):
            periods, rows, mult, ulabel = _extract_table_from_page(
                page, is_header_page=is_header, table_settings=strategy["settings"],
            )
            if is_header and periods:
                all_periods = periods
            if ulabel != DEFAULT_UNIT_LABEL:
                multiplier = mult
                unit_label = ulabel
            all_rows.extend(rows)

        score = _concept_score(all_rows)
        candidates.append((all_periods, all_rows, multiplier, unit_label, strategy["id"], score))

    # Select best strategy: prefer more periods extracted, then by concept_score
    candidates.sort(key=lambda c: (len(c[0]), c[5]), reverse=True)
    periods, rows, multiplier, unit_label, sid, score = candidates[0]

    # Supplement: fill missing concepts from text extraction
    found_concepts: set[str] = set()
    for row in rows:
        if row and row[0]:
            c = map_concept((row[0] or "").strip())
            if c is not None:
                # Only count if at least one value column is non-empty
                for cell in row[1:]:
                    if cell and cell.strip() and cell.strip() not in _EMPTY_VALUES:
                        found_concepts.add(c)
                        break

    for page in pages:
        page_text = page.extract_text() or ""
        # Use period count + 1 (item name + value columns) for text extraction
        num_cols = len(periods) + 1 if periods else (len(rows[0]) if rows else 3)
        text_rows = _extract_concepts_from_text(page_text, num_cols)
        for row in text_rows:
            name = (row[0] or "").strip()
            canonical = map_concept(name)
            if canonical and canonical not in found_concepts:
                rows.append(row)
                found_concepts.add(canonical)

    if score == 0 and found_concepts:
        sid = "text_fallback"
    score = _concept_score(rows)

    return periods, rows, multiplier, unit_label, sid, score


def _extract_financial_pages(pdf: pdfplumber.PDF) -> list[ExtractedStatement]:
    """Multi-strategy extraction: find headers, collect pages, try strategies."""
    # Pass 1: scan for headers
    scans = _scan_statement_headers(pdf)
    if not scans:
        return []

    # Deduplicate: keep only the FIRST occurrence of each statement type
    seen_types: set[str] = set()
    unique_scans: list[_PageScan] = []
    for scan in scans:
        if scan.statement_type not in seen_types:
            seen_types.add(scan.statement_type)
            unique_scans.append(scan)

    statements: list[ExtractedStatement] = []

    for i, scan in enumerate(unique_scans):
        # Determine upper bound: next statement header page or end of PDF
        if i + 1 < len(unique_scans):
            upper_bound = unique_scans[i + 1].page_idx
        else:
            upper_bound = min(scan.page_idx + 10, len(pdf.pages))

        # Collect all pages for this statement (header + continuations)
        stmt_pages: list[pdfplumber.pdf.Page] = [pdf.pages[scan.page_idx]]
        is_header_flags: list[bool] = [True]
        page_numbers: list[int] = [scan.page_num]

        for page_idx in range(scan.page_idx + 1, upper_bound):
            page = pdf.pages[page_idx]
            page_text = page.extract_text() or ""

            # Stop if we hit another financial statement header
            if classify_statement(page_text) is not None:
                break

            # Check continuation with default settings
            if not _is_continuation_page(page, expected_cols=3):
                break

            stmt_pages.append(page)
            is_header_flags.append(False)
            page_numbers.append(page_idx + 1)

        # Try all strategies on the collected pages
        periods, rows, multiplier, unit_label, sid, score = _try_strategies(
            stmt_pages, is_header_flags,
        )

        statements.append(ExtractedStatement(
            statement_type=scan.statement_type,
            periods=periods,
            rows=rows,
            pages=page_numbers,
            unit_multiplier=multiplier,
            unit_label=unit_label,
            strategy_id=sid,
            concept_score=score,
        ))

    return statements


# ---------------------------------------------------------------------------
# Build PeriodFinancial objects from extracted statements
# ---------------------------------------------------------------------------

def _build_period_financials(
    statements: list[ExtractedStatement],
) -> list[PeriodFinancial]:
    """Convert extracted statements into PeriodFinancial objects."""
    period_map: dict[str, PeriodFinancial] = {}

    for stmt in statements:
        if not stmt.periods:
            continue

        for row in stmt.rows:
            item_name = (row[0] or "").strip()
            if not item_name:
                continue

            canonical = map_concept(item_name)
            if canonical is None:
                continue

            statement_type = CONCEPT_TO_STATEMENT.get(canonical)
            if statement_type is None:
                continue

            for col_idx, period_info in enumerate(stmt.periods):
                value_idx = col_idx + 1
                if value_idx >= len(row):
                    continue

                value = normalize_value(row[value_idx], stmt.unit_multiplier)
                if value is None:
                    continue

                period_key = period_info.period_end
                if period_key not in period_map:
                    period_map[period_key] = PeriodFinancial(
                        period_end=period_info.period_end,
                        period_start=period_info.period_start,
                        period_type=period_info.period_type,
                        fiscal_year=fiscal_year_from_period_end(period_info.period_end),
                    )

                pf = period_map[period_key]
                # Merge period_type if mixed (instant BS + duration PL/CF)
                if pf.period_type != period_info.period_type:
                    pf.period_type = "mixed"
                if pf.period_start is None and period_info.period_start is not None:
                    pf.period_start = period_info.period_start

                target = (
                    pf.bs if statement_type == "bs"
                    else pf.pl if statement_type == "pl"
                    else pf.cf
                )
                # First match wins
                if target.get(canonical) is None:
                    target[canonical] = value

    for pf in period_map.values():
        pf.finalize()

    return sorted(period_map.values(), key=lambda p: p.period_end)


# ---------------------------------------------------------------------------
# Main parsing API
# ---------------------------------------------------------------------------

@dataclass
class PdfParseMetadata:
    """Metadata for a parsed PDF document."""

    doc_id: str | None
    source_pdf: str
    period_start: str | None
    period_end: str | None
    extraction_pages: list[int]
    parser_version: str
    extraction_method: str
    unit_detected: str
    unit_multiplier: int
    strategy_used: str = "S1"
    concept_score: int = 0


def parse_pdf(
    pdf_path: Path,
    ticker: str,
    doc_id: str | None = None,
) -> tuple[ParsedDocument, PdfParseMetadata]:
    """Parse a single PDF securities report.

    Returns (ParsedDocument, PdfParseMetadata).
    """
    with pdfplumber.open(pdf_path) as pdf:
        statements = _extract_financial_pages(pdf)

    periods = _build_period_financials(statements)

    # Build metadata
    all_pages: list[int] = []
    unit_label = DEFAULT_UNIT_LABEL
    unit_mult = DEFAULT_MULTIPLIER
    strategies_used: list[str] = []
    total_score = 0
    for stmt in statements:
        all_pages.extend(stmt.pages)
        if stmt.unit_label != DEFAULT_UNIT_LABEL:
            unit_label = stmt.unit_label
            unit_mult = stmt.unit_multiplier
        strategies_used.append(stmt.strategy_id)
        total_score += stmt.concept_score

    current_period = periods[-1] if periods else None
    # Determine dominant strategy
    dominant_strategy = max(set(strategies_used), key=strategies_used.count) if strategies_used else "S1"

    metadata = PdfParseMetadata(
        doc_id=doc_id,
        source_pdf=pdf_path.name,
        period_start=current_period.period_start if current_period else None,
        period_end=current_period.period_end if current_period else None,
        extraction_pages=sorted(set(all_pages)),
        parser_version=__version__,
        extraction_method="pdfplumber_table",
        unit_detected=unit_label,
        unit_multiplier=unit_mult,
        strategy_used=dominant_strategy,
        concept_score=total_score,
    )

    document = ParsedDocument(
        ticker=ticker,
        document_id=doc_id or pdf_path.stem,
        source_zip=str(pdf_path),
        company_name=None,
        periods=periods,
    )

    return document, metadata


def parse_pdf_directory(
    input_path: Path,
    ticker: str,
) -> tuple[list[ParsedDocument], list[PdfParseMetadata]]:
    """Parse all PDF securities reports in a directory.

    Returns (documents, metadata_list).
    """
    pdf_files = discover_pdfs(input_path, ticker)
    if not pdf_files:
        raise FileNotFoundError(
            f"No PDF files matching pattern '{ticker}_有価証券報告書_*.pdf' "
            f"found in {input_path}"
        )

    doc_id_map = load_manifest_doc_ids(input_path)

    manifest_path = input_path / "manifest.json"
    if manifest_path.exists():
        try:
            with manifest_path.open("r", encoding="utf-8") as f:
                manifest = json.load(f)
            expected = manifest.get("matched_doc_count")
            if expected is not None and len(pdf_files) != expected:
                logger.warning(
                    "Found %d PDFs but manifest.matched_doc_count=%s",
                    len(pdf_files),
                    expected,
                )
        except (json.JSONDecodeError, OSError):
            pass

    documents: list[ParsedDocument] = []
    metadata_list: list[PdfParseMetadata] = []

    for pdf_path in pdf_files:
        doc_id = doc_id_map.get(pdf_path.name)
        doc, meta = parse_pdf(pdf_path, ticker, doc_id=doc_id)
        documents.append(doc)
        metadata_list.append(meta)

    return documents, metadata_list
