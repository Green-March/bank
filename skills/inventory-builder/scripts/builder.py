"""inventory-builder: Generate inventory.md for a ticker's collected data."""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any


# ── Path helpers (same pattern as financial-calculator) ──────


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_root(env_name: str, fallback_dirname: str) -> Path:
    configured = os.environ.get(env_name)
    if not configured:
        return _repo_root() / fallback_dirname
    path = Path(configured).expanduser()
    if path.is_absolute():
        return path
    return (_repo_root() / path).resolve()


def _data_root() -> Path:
    return _resolve_root("DATA_PATH", "data")


class InventoryBuildError(Exception):
    """build_inventory の回復可能エラー。"""


# ── Low-level helpers ────────────────────────────────────────


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def _fiscal_year(period_end: date, fye_month: int) -> int:
    """period_end と決算月から会計年度ラベルを算出する。"""
    if period_end.month <= fye_month:
        return period_end.year
    return period_end.year + 1


def _fy_start_date(fy: int, fye_month: int) -> date:
    """会計年度の開始日を算出する。"""
    if fye_month == 12:
        return date(fy, 1, 1)
    return date(fy - 1, fye_month + 1, 1)


def _quarter_start_date(fy: int, fye_month: int, quarter: str) -> date:
    """会計年度内の各四半期の開始日を算出する。"""
    fy_start = _fy_start_date(fy, fye_month)
    offsets = {"q1": 0, "q2": 3, "q3": 6}
    offset = offsets.get(quarter, 0)
    m = fy_start.month + offset
    y = fy_start.year
    while m > 12:
        m -= 12
        y += 1
    return date(y, m, 1)


# ── classify_period ──────────────────────────────────────────


def classify_period(
    period_end: date,
    fye_month: int,
    period_start: date | None = None,
) -> str:
    """period_end と fye_month から文書種別を判定する。

    Returns: "annual", "h1", "q1", "q2", "q3", or "unknown"
    """
    m = period_end.month
    q1_month = (fye_month + 3) % 12 or 12
    q2_h1_month = (fye_month + 6) % 12 or 12
    q3_month = (fye_month + 9) % 12 or 12

    duration = (period_end - period_start).days if period_start else None

    # FYE month: annual or h1 (post-reform, period at FYE month with short duration)
    if m == fye_month:
        if duration is not None and duration > 300:
            return "annual"
        if duration is not None and 150 <= duration <= 200:
            return "h1"
        if duration is None:
            return "annual"

    # Q2 / H1 (same month — disambiguate by period_start / duration)
    if m == q2_h1_month:
        if period_start and period_start >= date(2024, 4, 1):
            if duration is None or 150 <= duration <= 200:
                return "h1"
        if duration is not None and duration > 200:
            return "h1"
        return "q2"

    if m == q1_month:
        return "q1"

    if m == q3_month:
        return "q3"

    return "unknown"


# ── Data loading ─────────────────────────────────────────────


def _load_all_manifests(edinet_dir: Path) -> tuple[list[dict], dict]:
    """全 manifest*.json を読み込み、(results, metadata) を返す。

    各 result に _source_file (採用元ファイル名) と _fetched_at を付与する。
    同一 doc_id が複数 manifest に存在する場合、fetched_at が新しい方を採用する。
    """
    seen: dict[str, dict] = {}
    meta: dict[str, Any] = {}
    manifest_sources: list[dict] = []
    for p in sorted(edinet_dir.glob("manifest*.json")):
        try:
            data = _load_json(p)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"manifest 読込スキップ ({p.name}): {exc}", file=sys.stderr)
            continue
        if not isinstance(data, dict):
            print(f"manifest スキップ ({p.name}): 内容が dict でない (type={type(data).__name__})", file=sys.stderr)
            continue
        fname = p.name
        fetched = data.get("fetched_at", "")
        manifest_sources.append({"file": fname, "fetched_at": fetched})
        if not meta.get("edinet_code"):
            meta["edinet_code"] = data.get("edinet_code")
        if not meta.get("generated_at"):
            meta["generated_at"] = data.get("generated_at")
        results = data.get("results", [])
        if not isinstance(results, list):
            print(f"manifest スキップ ({p.name}): results が list でない (type={type(results).__name__})", file=sys.stderr)
            continue
        for r in results:
            if not isinstance(r, dict):
                continue
            doc_id = r.get("doc_id")
            if not doc_id:
                continue
            r["_source_file"] = fname
            r["_fetched_at"] = fetched
            if doc_id not in seen:
                seen[doc_id] = r
            else:
                # fetched_at が新しい方を採用
                existing_ts = seen[doc_id].get("_fetched_at", "")
                if fetched > existing_ts:
                    seen[doc_id] = r
    meta["manifest_sources"] = manifest_sources
    return list(seen.values()), meta


def _load_jquants_latest(jquants_dir: Path) -> list[dict]:
    """最新の J-Quants statements ファイルを読み込む。"""
    candidates = sorted(jquants_dir.glob("statements_*.json"))
    if not candidates:
        return []
    data = _load_json(candidates[-1])
    return data if isinstance(data, list) else []


def _build_fin_index(financials: dict | None) -> dict[str, dict]:
    """financials.json から {document_id: doc} のインデックスを構築する。"""
    if not financials:
        return {}
    return {
        doc["document_id"]: doc
        for doc in financials.get("documents", [])
        if doc.get("document_id")
    }


# ── Document assembly ────────────────────────────────────────


def _find_current_period(fin_doc: dict | None, target_pe: date | None) -> dict | None:
    """financials の期間から最適な current period を取得する。"""
    if not fin_doc:
        return None
    periods = fin_doc.get("periods", [])

    # 1. target_pe と一致し period_start を持つ期間
    if target_pe:
        for p in periods:
            pe = _parse_date(p.get("period_end"))
            if pe == target_pe and p.get("period_start"):
                return p

    # 2. Fallback: period_start を持つ最新期間
    best: dict | None = None
    best_pe: date | None = None
    for p in periods:
        if not p.get("period_start"):
            continue
        pe = _parse_date(p.get("period_end"))
        if pe and (best_pe is None or pe > best_pe):
            best = p
            best_pe = pe
    return best


def _assemble_documents(
    manifest_results: list[dict],
    fin_index: dict[str, dict],
    fye_month: int,
) -> list[dict]:
    """manifest + financials を結合し、各文書を分類する。"""
    docs: list[dict] = []
    for r in manifest_results:
        doc_id = r.get("doc_id")
        if not doc_id:
            continue
        manifest_pe = _parse_date(r.get("period_end"))
        if not manifest_pe:
            continue

        fin_doc = fin_index.get(doc_id)
        period = _find_current_period(fin_doc, manifest_pe)

        if period:
            pe = _parse_date(period.get("period_end")) or manifest_pe
            ps = _parse_date(period.get("period_start"))
        else:
            pe = manifest_pe
            ps = None

        docs.append({
            "doc_id": doc_id,
            "period_end": pe,
            "period_start": ps,
            "period_type": classify_period(pe, fye_month, ps),
            "fiscal_year": _fiscal_year(pe, fye_month),
            "company_name": fin_doc.get("company_name") if fin_doc else None,
            "source_file": r.get("_source_file", ""),
            "fetched_at": r.get("_fetched_at", ""),
        })

    docs.sort(key=lambda d: d["period_end"])
    return docs


# ── build_coverage_matrix ────────────────────────────────────


COLUMNS = ("q1", "q2", "q3", "h1", "annual", "jquants")


def build_coverage_matrix(documents: list[dict], fye_month: int) -> dict:
    """FY × 期間種別のカバレッジマトリクスを構築する。

    Returns: {"years": [...], "matrix": {fy: {col: doc_id|None}}}
    """
    matrix: dict[int, dict[str, str | None]] = {}

    for doc in documents:
        fy = doc["fiscal_year"]
        pt = doc["period_type"]
        if pt not in COLUMNS:
            continue
        if fy not in matrix:
            matrix[fy] = {c: None for c in COLUMNS}
        if matrix[fy][pt] is None:
            matrix[fy][pt] = doc["doc_id"]

    return {"years": sorted(matrix.keys()), "matrix": matrix}


def _merge_jquants(coverage: dict, jquants: list[dict], fye_month: int) -> None:
    """J-Quants 短信データをカバレッジマトリクスに統合する (in-place)。"""
    mat = coverage["matrix"]
    for stmt in jquants:
        fy_end = _parse_date(stmt.get("CurrentFiscalYearEndDate"))
        if not fy_end:
            continue
        fy = _fiscal_year(fy_end, fye_month)
        if fy not in mat:
            mat[fy] = {c: None for c in COLUMNS}
            coverage["years"] = sorted(mat.keys())

        qt = stmt.get("TypeOfCurrentPeriod", "")
        disclosed = stmt.get("DisclosedDate", "")
        label = f"{qt} {disclosed}" if disclosed else qt
        prev = mat[fy].get("jquants")
        mat[fy]["jquants"] = f"{prev}, {label}" if prev else label


# ── analyze_gaps ─────────────────────────────────────────────


def analyze_gaps(matrix: dict, fye_month: int) -> dict:
    """欠損を許容 (△) と要対応 (✗) に分類する。

    Returns: {"acceptable": [...], "actionable": [...]}
    """
    acceptable: list[dict] = []
    actionable: list[dict] = []
    years = matrix["years"]
    mat = matrix["matrix"]

    for fy in years:
        row = mat.get(fy, {})

        for qt in ("q1", "q2", "q3"):
            if row.get(qt) is not None:
                continue

            qs = _quarter_start_date(fy, fye_month, qt)

            if qs >= date(2024, 4, 1) and qt in ("q1", "q3"):
                acceptable.append({
                    "fiscal_year": fy,
                    "quarter": qt.upper(),
                    "reason": "四半期報告書制度廃止 (2024年4月施行)",
                })
            elif qs >= date(2024, 4, 1) and qt == "q2":
                # Q2 は H1 に置き換え — H1 も無い場合のみ要対応
                if row.get("h1") is None:
                    actionable.append({
                        "fiscal_year": fy,
                        "quarter": "H1",
                        "reason": "半期報告書が未収集",
                    })
            elif fy == years[0]:
                acceptable.append({
                    "fiscal_year": fy,
                    "quarter": qt.upper(),
                    "reason": "収集対象期間の開始年度",
                })
            else:
                actionable.append({
                    "fiscal_year": fy,
                    "quarter": qt.upper(),
                    "reason": "存在すべきだが欠損",
                })

        # 有報チェック
        if row.get("annual") is None:
            if fy == years[-1]:
                acceptable.append({
                    "fiscal_year": fy,
                    "quarter": "有報",
                    "reason": "最新年度 (未発表の可能性)",
                })
            elif fy == years[0]:
                acceptable.append({
                    "fiscal_year": fy,
                    "quarter": "有報",
                    "reason": "収集対象期間の開始年度",
                })
            else:
                actionable.append({
                    "fiscal_year": fy,
                    "quarter": "有報",
                    "reason": "存在すべきだが欠損",
                })

    return {"acceptable": acceptable, "actionable": actionable}


# ── calculate_quality_summary ────────────────────────────────


QUALITY_METRICS = (
    "revenue",
    "operating_income",
    "net_income",
    "total_assets",
    "total_equity",
    "net_assets",
    "operating_cf",
    "total_liabilities",
)

_METRIC_SECTION = {
    "revenue": "pl",
    "operating_income": "pl",
    "net_income": "pl",
    "total_assets": "bs",
    "total_equity": "bs",
    "net_assets": "bs",
    "operating_cf": "cf",
    "total_liabilities": "bs",
}


def calculate_quality_summary(financials: dict | None) -> dict:
    """各メトリクスの非 null カバレッジ率を算出する。

    Returns: {"total": int, "metrics": {name: {"count": int, "ratio": float}}}
    """
    if not financials:
        return {"total": 0, "metrics": {}}

    counts: dict[str, int] = {m: 0 for m in QUALITY_METRICS}
    total = 0

    for doc in financials.get("documents", []):
        # current period = period_start を持つ最新期間
        best: dict | None = None
        best_pe: date | None = None
        for p in doc.get("periods", []):
            if not p.get("period_start"):
                continue
            pe = _parse_date(p.get("period_end"))
            if pe and (best_pe is None or pe > best_pe):
                best = p
                best_pe = pe
        if not best:
            continue

        total += 1
        for metric in QUALITY_METRICS:
            section = _METRIC_SECTION[metric]
            val = best.get(section, {}).get(metric)
            if val is not None:
                counts[metric] += 1

    metrics = {}
    for m in QUALITY_METRICS:
        c = counts[m]
        metrics[m] = {
            "count": c,
            "ratio": c / total if total > 0 else 0.0,
        }
    return {"total": total, "metrics": metrics}


# ── generate_inventory_md ────────────────────────────────────


_METRIC_LABELS = {
    "revenue": "revenue (売上高)",
    "operating_income": "operating_income (営業利益)",
    "net_income": "net_income (純利益)",
    "total_assets": "total_assets (総資産)",
    "total_equity": "total_equity (株主資本)",
    "net_assets": "net_assets (純資産)",
    "operating_cf": "operating_cf (営業CF)",
    "total_liabilities": "total_liabilities (負債合計)",
}

_PERIOD_LABELS = {
    "q1": "Q1 四半期報告書",
    "q2": "Q2 四半期報告書",
    "q3": "Q3 四半期報告書",
    "h1": "半期報告書",
    "annual": "有価証券報告書",
    "unknown": "不明",
}

_PERIOD_SHORT = {
    "q1": "Q1",
    "q2": "Q2",
    "q3": "Q3",
    "h1": "H1",
    "annual": "有報",
    "unknown": "不明",
}


def generate_inventory_md(context: dict) -> str:
    """組み立て済み context から inventory.md の Markdown を生成する。"""
    lines: list[str] = []

    ticker = context["ticker"]
    fye_month = context["fye_month"]
    edinet_code = context.get("edinet_code", "不明")
    company_name = context.get("company_name", "")
    documents = context["documents"]
    coverage = context["coverage"]
    gaps = context["gaps"]
    quality = context["quality"]
    jquants_available = context.get("jquants_available", False)

    title = f"{company_name} ({ticker})" if company_name else f"({ticker})"
    lines.append(f"# {title} 書類棚卸し一覧\n")

    # ── (a) 収集概要 ──
    lines.append("## (a) 収集概要\n")
    lines.append("| 項目 | 内容 |")
    lines.append("|------|------|")
    lines.append(f"| 対象銘柄 | {ticker} {company_name} ({fye_month}月期決算) |")
    lines.append(f"| 生成日 | {date.today().isoformat()} |")
    years = coverage["years"]
    if years:
        lines.append(f"| 対象期間 | FY{years[0]} 〜 FY{years[-1]} |")
    sources = [f"EDINET API ({edinet_code})" if edinet_code else "EDINET API"]
    if jquants_available:
        sources.append("J-Quants API")
    lines.append(f"| データソース | {', '.join(sources)} |")
    lines.append("")

    # ── (b) 書類種別ごとの収集状況表 ──
    lines.append("---\n")
    lines.append("## (b) 書類種別ごとの収集状況表\n")
    type_counts: dict[str, int] = {}
    for doc in documents:
        label = _PERIOD_LABELS.get(doc["period_type"], doc["period_type"])
        type_counts[label] = type_counts.get(label, 0) + 1

    lines.append("| 書類種別 | ソース | 件数 |")
    lines.append("|---------|--------|------|")
    for label, count in type_counts.items():
        lines.append(f"| {label} | EDINET | {count}件 |")
    if jquants_available:
        jq_count = sum(
            1 for fy in coverage["matrix"] if coverage["matrix"][fy].get("jquants")
        )
        if jq_count:
            lines.append(f"| 決算短信 | J-Quants | {jq_count}FY分 |")
    lines.append("")

    # ── (c) 文書一覧 ──
    lines.append("---\n")
    lines.append("## (c) 文書一覧\n")
    lines.append("| # | doc_id | period_end | FY | 種別 | 採用元 |")
    lines.append("|---|--------|------------|----|------|--------|")
    for i, doc in enumerate(documents, 1):
        pt_label = _PERIOD_SHORT.get(doc["period_type"], doc["period_type"])
        src = doc.get("source_file", "")
        lines.append(
            f"| {i} | {doc['doc_id']} | {doc['period_end'].isoformat()} "
            f"| FY{doc['fiscal_year']} | {pt_label} | {src} |"
        )
    lines.append("")

    # ── (d) カバレッジマトリクス ──
    lines.append("---\n")
    lines.append("## (d) 年度×四半期カバレッジマトリクス\n")
    lines.append("凡例: ✓=取得済 / △=欠損許容 / ✗=欠損要対応 / -=制度非該当\n")

    gap_set_ok = {(g["fiscal_year"], g["quarter"]) for g in gaps["acceptable"]}
    gap_set_ng = {(g["fiscal_year"], g["quarter"]) for g in gaps["actionable"]}

    has_jquants = any(
        coverage["matrix"][fy].get("jquants") for fy in coverage["years"]
    )

    header = "| FY | Q1 | Q2 | Q3 | H1 | 有報 |"
    sep = "|----|:---:|:---:|:---:|:---:|:---:|"
    if has_jquants:
        header += " 短信 |"
        sep += ":---:|"
    lines.append(header)
    lines.append(sep)

    for fy in coverage["years"]:
        row = coverage["matrix"][fy]
        cells = []
        for col, gap_label in [
            ("q1", "Q1"), ("q2", "Q2"), ("q3", "Q3"),
            ("h1", "H1"), ("annual", "有報"),
        ]:
            doc_id = row.get(col)
            if doc_id:
                cells.append(f"✓ {doc_id}")
            elif (fy, gap_label) in gap_set_ok:
                cells.append("△")
            elif (fy, gap_label) in gap_set_ng:
                cells.append("✗")
            else:
                cells.append("-")

        line = f"| FY{fy} | " + " | ".join(cells) + " |"
        if has_jquants:
            jq = row.get("jquants")
            line += f" {jq or '-'} |"
        lines.append(line)
    lines.append("")

    # ── (e) データ品質サマリ ──
    lines.append("---\n")
    lines.append("## (e) データ品質サマリ\n")
    total = quality["total"]
    if total > 0:
        lines.append("| 指標 | カバレッジ | 備考 |")
        lines.append("|------|----------|------|")
        for metric in QUALITY_METRICS:
            info = quality["metrics"].get(metric, {})
            count = info.get("count", 0)
            ratio = info.get("ratio", 0.0)
            label = _METRIC_LABELS.get(metric, metric)
            lines.append(f"| {label} | {count}/{total} ({ratio:.0%}) | |")
    else:
        lines.append("financials.json が未生成のため品質評価不可。\n")
    lines.append("")

    # ── (f) データ分析ノート ──
    lines.append("---\n")
    lines.append("## (f) データ分析ノート\n")
    manifest_sources = context.get("manifest_sources", [])
    if manifest_sources:
        lines.append("### 採用 manifest ファイル\n")
        lines.append("| ファイル | 取得日時 |")
        lines.append("|---------|---------|")
        for ms in manifest_sources:
            lines.append(f"| {ms['file']} | {ms.get('fetched_at', '')} |")
        lines.append("")
    # CF 開示パターン（operating_cf カバレッジが < 100% の場合）
    if total > 0:
        ocf = quality["metrics"].get("operating_cf", {})
        if ocf.get("ratio", 1.0) < 1.0:
            lines.append("### CF計算書の開示パターン\n")
            lines.append(
                "日本の四半期報告書制度では Q1/Q3 の CF 計算書は任意開示。"
                "Q2（累計半期）と有報のみで CF を開示する企業が多い。\n"
            )
    tl = quality["metrics"].get("total_liabilities", {}) if total > 0 else {}
    if total > 0 and tl.get("ratio", 1.0) == 0.0:
        lines.append("### total_liabilities 未取得\n")
        lines.append(
            "XBRL 概念 `Liabilities` がパーサーの `total_liabilities` 別名に"
            "未登録の可能性。total_assets - net_assets で代替計算可能。\n"
        )
    lines.append("")

    # ── (g) 欠損リスト ──
    lines.append("---\n")
    lines.append("## (g) 欠損リスト\n")
    lines.append("### 許容欠損 (△)\n")
    if gaps["acceptable"]:
        lines.append("| 対象 | 理由 |")
        lines.append("|------|------|")
        for g in gaps["acceptable"]:
            lines.append(f"| FY{g['fiscal_year']} {g['quarter']} | {g['reason']} |")
    else:
        lines.append("なし\n")
    lines.append("")
    lines.append("### 要対応欠損 (✗)\n")
    if gaps["actionable"]:
        lines.append("| 対象 | 理由 |")
        lines.append("|------|------|")
        for g in gaps["actionable"]:
            lines.append(f"| FY{g['fiscal_year']} {g['quarter']} | {g['reason']} |")
    else:
        lines.append("なし\n")
    lines.append("")

    # ── (h) 再現コマンド一覧 ──
    lines.append("---\n")
    lines.append("## (h) 再現コマンド一覧\n")
    lines.append("```bash")
    lines.append("# EDINET 収集")
    lines.append(
        f"python3 skills/disclosure-collector/scripts/main.py edinet {edinet_code} \\"
    )
    lines.append(f"  --ticker {ticker}")
    lines.append("")
    lines.append("# XBRL パース")
    lines.append(f"python3 skills/disclosure-parser/scripts/main.py --ticker {ticker}")
    lines.append("")
    lines.append("# 指標計算")
    lines.append(
        f"python3 skills/financial-calculator/scripts/main.py calculate --ticker {ticker}"
    )
    lines.append("")
    lines.append("# 棚卸し生成")
    lines.append(
        f"python3 skills/inventory-builder/scripts/main.py"
        f" --ticker {ticker} --fye-month {fye_month}"
    )
    lines.append("```\n")

    # ── (i) 後続タスクへの推奨事項 ──
    lines.append("---\n")
    lines.append("## (i) 後続タスクへの推奨事項\n")
    rec_num = 1
    if gaps["actionable"]:
        lines.append(f"### {rec_num}. 欠損文書の追加収集 (優先度: 高)\n")
        for g in gaps["actionable"]:
            lines.append(f"- FY{g['fiscal_year']} {g['quarter']}: {g['reason']}")
        lines.append("")
        rec_num += 1

    if total == 0:
        lines.append(f"### {rec_num}. XBRL パース実行 (優先度: 高)\n")
        lines.append(
            "financials.json が未生成。`disclosure-parser` を実行してください。\n"
        )
        rec_num += 1

    lines.append(
        f"### {rec_num}. 指標計算・バリュエーション (優先度: パース完了後)\n"
    )
    lines.append(
        "`financial-calculator` で ROE / ROA / マージン / 成長率 / CF 分析を実施。\n"
    )

    return "\n".join(lines) + "\n"


# ── build_inventory (main entry) ─────────────────────────────


def build_inventory(
    ticker: str,
    fye_month: int,
    data_root: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    """指定銘柄の inventory.md を生成するメインエントリポイント。"""
    root = data_root or _data_root()
    ticker_dir = root / ticker
    edinet_dir = ticker_dir / "raw" / "edinet"
    parsed_dir = ticker_dir / "parsed"
    jquants_dir = ticker_dir / "raw" / "jquants"

    if not edinet_dir.exists():
        raise InventoryBuildError(
            f"EDINET ディレクトリが見つかりません: {edinet_dir}"
        )

    # Load data
    manifest_results, meta = _load_all_manifests(edinet_dir)
    if not manifest_results:
        raise InventoryBuildError(
            f"manifest に文書が含まれていません: {edinet_dir}"
        )

    financials: dict | None = None
    fin_path = parsed_dir / "financials.json"
    if fin_path.exists():
        try:
            financials = _load_json(fin_path)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"financials.json 読込失敗（スキップ）: {exc}", file=sys.stderr)
    fin_index = _build_fin_index(financials)

    jquants: list[dict] = []
    if jquants_dir.exists():
        try:
            jquants = _load_jquants_latest(jquants_dir)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"J-Quants 読込失敗（スキップ）: {exc}", file=sys.stderr)
    if not jquants:
        print(f"J-Quants データなし（スキップ）: {jquants_dir}", file=sys.stderr)

    # Assemble
    documents = _assemble_documents(manifest_results, fin_index, fye_month)
    company_name = next(
        (d["company_name"] for d in documents if d.get("company_name")), ""
    )
    coverage = build_coverage_matrix(documents, fye_month)
    if jquants:
        _merge_jquants(coverage, jquants, fye_month)

    gaps = analyze_gaps(coverage, fye_month)
    quality = calculate_quality_summary(financials)

    context = {
        "ticker": ticker,
        "fye_month": fye_month,
        "edinet_code": meta.get("edinet_code", ""),
        "company_name": company_name,
        "documents": documents,
        "coverage": coverage,
        "gaps": gaps,
        "quality": quality,
        "jquants_available": bool(jquants),
        "manifest_sources": meta.get("manifest_sources", []),
    }

    md = generate_inventory_md(context)

    out = output_path or (ticker_dir / "inventory.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"inventory.md を生成しました: {out}")
    return out


# ── CLI ──────────────────────────────────────────────────────


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="書類棚卸し一覧 (inventory.md) を生成"
    )
    parser.add_argument("--ticker", required=True, help="銘柄コード（例: 7685）")
    parser.add_argument(
        "--fye-month", required=True, type=int, help="決算月（例: 12）"
    )
    parser.add_argument(
        "--data-root", default=None, help="データルート（省略時: data/）"
    )
    parser.add_argument(
        "--output", default=None, help="出力パス（省略時: data/{ticker}/inventory.md）"
    )
    args = parser.parse_args()

    dr = Path(args.data_root) if args.data_root else None
    out = Path(args.output) if args.output else None
    try:
        build_inventory(
            ticker=args.ticker,
            fye_month=args.fye_month,
            data_root=dr,
            output_path=out,
        )
    except InventoryBuildError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1
    return 0


