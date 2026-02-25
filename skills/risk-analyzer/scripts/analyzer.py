"""risk-analyzer: XBRL/JSON からリスクテキストを抽出・分類する."""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


# ---------------------------------------------------------------------------
# Risk categories and keyword mappings
# ---------------------------------------------------------------------------

RISK_CATEGORIES = (
    "market_risk",
    "credit_risk",
    "operational_risk",
    "regulatory_risk",
    "other_risk",
)

# Keywords that indicate a specific risk category (Japanese)
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "market_risk": [
        "為替", "金利", "株価", "市場変動", "価格変動", "商品価格",
        "原材料価格", "有価証券", "デリバティブ", "通貨", "景気",
        "経済環境", "需要変動", "市況",
    ],
    "credit_risk": [
        "信用", "債務不履行", "取引先", "貸倒", "与信", "回収",
        "売掛金", "不良債権", "デフォルト", "破綻", "倒産",
    ],
    "operational_risk": [
        "内部統制", "人材", "IT", "情報システム", "セキュリティ",
        "サイバー", "災害", "自然災害", "感染症", "パンデミック",
        "品質", "製品安全", "リコール", "サプライチェーン", "供給",
        "事故", "不正", "人件費", "労務", "技術革新", "知的財産",
    ],
    "regulatory_risk": [
        "法令", "規制", "コンプライアンス", "行政処分", "訴訟",
        "法的", "税制", "税務", "会計基準", "開示", "許認可",
        "独占禁止", "個人情報", "環境規制", "排出", "カーボン",
    ],
}

# XBRL elements that contain risk-related narrative text
RISK_TEXT_ELEMENTS = (
    "jpcrp_cor:BusinessRisksTextBlock",
    "jpcrp_cor:RiskManagementTextBlock",
    "jpcrp_cor:ManagementAnalysisOfFinancialPositionOperatingResultsAndCashFlowsTextBlock",
)

# Severity keywords
_SEVERITY_HIGH = [
    "重大", "著しい", "大幅", "深刻", "甚大", "多大", "大きな影響",
    "経営に重要", "事業継続",
]
_SEVERITY_LOW = [
    "軽微", "限定的", "僅か", "わずか", "小さい",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RiskItem:
    """Single identified risk."""
    text: str
    source: str
    severity: str  # high / medium / low
    category: str  # one of RISK_CATEGORIES


@dataclass
class RiskAnalysisResult:
    """Full analysis output."""
    ticker: str
    analyzed_at: str
    source_documents: list[str]
    risk_items: list[RiskItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        categories: dict[str, list[dict[str, str]]] = {c: [] for c in RISK_CATEGORIES}
        for item in self.risk_items:
            categories[item.category].append({
                "text": item.text,
                "source": item.source,
                "severity": item.severity,
            })
        by_category = {c: len(v) for c, v in categories.items()}
        severity_counts = {"high": 0, "medium": 0, "low": 0}
        for item in self.risk_items:
            severity_counts[item.severity] += 1
        return {
            "ticker": self.ticker,
            "analyzed_at": self.analyzed_at,
            "source_documents": self.source_documents,
            "risk_categories": categories,
            "summary": {
                "total_risks": len(self.risk_items),
                "by_category": by_category,
                "by_severity": severity_counts,
            },
        }


# ---------------------------------------------------------------------------
# Text extraction from XBRL
# ---------------------------------------------------------------------------

def _strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"[ \t]+", " ", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean.strip()


def _find_xbrl_in_zip(zip_path: Path) -> str | None:
    """Return the path of the main XBRL instance document inside a ZIP."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            lower = name.lower()
            if lower.endswith(".xbrl") and "audit" not in lower:
                return name
    return None


def extract_risk_texts_from_zip(zip_path: Path) -> list[tuple[str, str]]:
    """Extract risk-related text blocks from an EDINET XBRL ZIP.

    Returns list of (element_tag, cleaned_text) tuples.
    """
    xbrl_name = _find_xbrl_in_zip(zip_path)
    if xbrl_name is None:
        return []

    with zipfile.ZipFile(zip_path, "r") as zf:
        with zf.open(xbrl_name) as f:
            tree = ET.parse(f)

    root = tree.getroot()
    results: list[tuple[str, str]] = []

    # Build set of local names to look for
    target_locals = set()
    for elem_qname in RISK_TEXT_ELEMENTS:
        _, local = elem_qname.split(":", 1)
        target_locals.add(local)

    for elem in root.iter():
        tag = elem.tag
        # Strip namespace
        if "}" in tag:
            local_name = tag.split("}", 1)[1]
        else:
            local_name = tag

        if local_name in target_locals:
            raw = elem.text or ""
            cleaned = _strip_html(raw)
            if cleaned:
                results.append((local_name, cleaned))

    return results


def extract_risk_texts_from_dir(input_dir: Path) -> dict[str, list[tuple[str, str]]]:
    """Extract risk texts from all ZIP files in a directory.

    Returns {document_id: [(element_tag, text), ...]}.
    """
    results: dict[str, list[tuple[str, str]]] = {}
    if not input_dir.is_dir():
        return results

    for zip_path in sorted(input_dir.glob("*.zip")):
        doc_id = zip_path.stem
        texts = extract_risk_texts_from_zip(zip_path)
        if texts:
            results[doc_id] = texts

    return results


def extract_risk_texts_from_parsed_json(json_path: Path) -> dict[str, list[tuple[str, str]]]:
    """Extract risk-related info from disclosure-parser financials.json.

    The parser output focuses on numeric data, so risk text may be limited.
    We extract document IDs and look for any narrative fields.
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    results: dict[str, list[tuple[str, str]]] = {}
    ticker = data.get("ticker", "")

    # Try to find raw XBRL zips referenced by the parsed JSON
    documents = data.get("documents", [])
    for doc in documents:
        doc_id = doc.get("document_id", "")
        source_zip = doc.get("source_zip", "")
        if source_zip and doc_id:
            zip_path = Path(source_zip)
            if not zip_path.is_absolute():
                zip_path = json_path.parent.parent.parent / zip_path
            if zip_path.exists():
                texts = extract_risk_texts_from_zip(zip_path)
                if texts:
                    results[doc_id] = texts

    # If no zips found, try to locate raw edinet dir
    if not results and ticker:
        raw_dir = json_path.parent.parent / "raw" / "edinet"
        if raw_dir.is_dir():
            results = extract_risk_texts_from_dir(raw_dir)

    return results


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_category(text: str) -> str:
    """Classify a risk text snippet into one of the 5 categories."""
    scores: dict[str, int] = {c: 0 for c in RISK_CATEGORIES if c != "other_risk"}
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            scores[cat] += len(re.findall(re.escape(kw), text))

    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0:
        return "other_risk"
    return best


def assess_severity(text: str) -> str:
    """Assess severity as high/medium/low based on keyword presence."""
    for kw in _SEVERITY_HIGH:
        if kw in text:
            return "high"
    for kw in _SEVERITY_LOW:
        if kw in text:
            return "low"
    return "medium"


def split_risk_paragraphs(text: str) -> list[str]:
    """Split a long risk text block into individual risk paragraphs.

    Heuristic: split on numbered patterns (1., (1), etc.) or double newlines.
    """
    # Try numbered patterns first: e.g. "(1)", "①", "1."
    parts = re.split(r"(?:(?<=\n)|(?<=^))[\s]*(?:\(\d+\)|\d+[\.\)）]|[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])", text)

    if len(parts) <= 1:
        # Fallback: split on double newlines
        parts = re.split(r"\n\n+", text)

    cleaned = []
    for p in parts:
        p = p.strip()
        if len(p) >= 20:  # Skip very short fragments
            cleaned.append(p)

    return cleaned if cleaned else [text.strip()] if text.strip() else []


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def analyze_risks(
    ticker: str,
    risk_texts: dict[str, list[tuple[str, str]]],
) -> RiskAnalysisResult:
    """Analyze extracted risk texts and produce structured output."""
    now = datetime.now(timezone.utc).isoformat()
    result = RiskAnalysisResult(
        ticker=ticker,
        analyzed_at=now,
        source_documents=sorted(risk_texts.keys()),
    )

    for doc_id, texts in risk_texts.items():
        for _tag, text in texts:
            paragraphs = split_risk_paragraphs(text)
            for para in paragraphs:
                category = classify_category(para)
                severity = assess_severity(para)
                result.risk_items.append(RiskItem(
                    text=para,
                    source=doc_id,
                    severity=severity,
                    category=category,
                ))

    return result


def run_analysis(
    ticker: str,
    input_dir: Path | None = None,
    parsed_json: Path | None = None,
) -> RiskAnalysisResult:
    """High-level entry point: extract texts then analyze."""
    if input_dir is not None:
        risk_texts = extract_risk_texts_from_dir(input_dir)
    elif parsed_json is not None:
        risk_texts = extract_risk_texts_from_parsed_json(parsed_json)
    else:
        raise ValueError("Either input_dir or parsed_json must be provided")

    return analyze_risks(ticker, risk_texts)
