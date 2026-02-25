"""Tests for risk-analyzer."""

from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path

import pytest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from analyzer import (
    RISK_CATEGORIES,
    RiskAnalysisResult,
    RiskItem,
    _strip_html,
    analyze_risks,
    assess_severity,
    classify_category,
    extract_risk_texts_from_dir,
    extract_risk_texts_from_parsed_json,
    extract_risk_texts_from_zip,
    run_analysis,
    split_risk_paragraphs,
)
from main import main as cli_main, build_parser


# ---------------------------------------------------------------------------
# Sample XBRL body for testing
# ---------------------------------------------------------------------------

SAMPLE_XBRL = """\
<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl
  xmlns:xbrli="http://www.xbrl.org/2003/instance"
  xmlns:jpcrp_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jpcrp/2023-12-01/jpcrp_cor">
  <jpcrp_cor:BusinessRisksTextBlock contextRef="CurrentYearDuration">
    <![CDATA[
    (1) 為替リスクについて
    当社グループは海外での事業活動を行っており、為替変動による重大な影響を受ける可能性があります。

    (2) 情報セキュリティリスク
    サイバー攻撃や情報漏洩により、事業運営に限定的な影響が生じる可能性があります。

    (3) 法令遵守リスク
    各国の法令改正に伴い、コンプライアンス体制の強化が求められる可能性があります。

    (4) 取引先の信用リスク
    主要取引先の経営破綻や債務不履行により、売掛金の回収が困難になる可能性があります。

    (5) その他のリスク
    予測困難な外部環境の変化により事業に影響を及ぼす可能性があります。
    ]]>
  </jpcrp_cor:BusinessRisksTextBlock>
</xbrli:xbrl>
"""

SAMPLE_XBRL_HTML = """\
<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl
  xmlns:xbrli="http://www.xbrl.org/2003/instance"
  xmlns:jpcrp_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jpcrp/2023-12-01/jpcrp_cor">
  <jpcrp_cor:BusinessRisksTextBlock contextRef="CurrentYearDuration">
    &lt;p&gt;為替変動による&lt;b&gt;著しい&lt;/b&gt;影響があります。&lt;/p&gt;
    &lt;p&gt;金利上昇リスクがあります。&lt;/p&gt;
  </jpcrp_cor:BusinessRisksTextBlock>
</xbrli:xbrl>
"""

SAMPLE_XBRL_EMPTY = """\
<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl
  xmlns:xbrli="http://www.xbrl.org/2003/instance"
  xmlns:jpcrp_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jpcrp/2023-12-01/jpcrp_cor">
  <jpcrp_cor:BusinessRisksTextBlock contextRef="CurrentYearDuration">
  </jpcrp_cor:BusinessRisksTextBlock>
</xbrli:xbrl>
"""

SAMPLE_XBRL_NO_RISK = """\
<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl
  xmlns:xbrli="http://www.xbrl.org/2003/instance"
  xmlns:jpcrp_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jpcrp/2023-12-01/jpcrp_cor">
  <jpcrp_cor:CompanyNameTextBlock contextRef="CurrentYearDuration">
    テスト株式会社
  </jpcrp_cor:CompanyNameTextBlock>
</xbrli:xbrl>
"""


def _create_zip(tmp: Path, name: str, xbrl_body: str) -> Path:
    """Create a minimal XBRL ZIP for testing."""
    zip_path = tmp / f"{name}.zip"
    xbrl_name = f"XBRL/PublicDoc/{name}.xbrl"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(xbrl_name, xbrl_body)
    return zip_path


# ---------------------------------------------------------------------------
# Tests: _strip_html
# ---------------------------------------------------------------------------

class TestStripHtml:
    def test_removes_tags(self):
        assert _strip_html("<p>hello</p>") == "hello"

    def test_collapses_whitespace(self):
        assert _strip_html("a   b\t\tc") == "a b c"

    def test_empty(self):
        assert _strip_html("") == ""

    def test_nested_tags(self):
        result = _strip_html("<div><p>text <b>bold</b></p></div>")
        assert "text" in result
        assert "bold" in result
        assert "<" not in result


# ---------------------------------------------------------------------------
# Tests: classify_category
# ---------------------------------------------------------------------------

class TestClassifyCategory:
    def test_market_risk(self):
        assert classify_category("為替変動により業績に影響がある") == "market_risk"

    def test_credit_risk(self):
        assert classify_category("取引先の債務不履行による貸倒リスク") == "credit_risk"

    def test_operational_risk(self):
        assert classify_category("サイバー攻撃による情報システム障害") == "operational_risk"

    def test_regulatory_risk(self):
        assert classify_category("法令改正によるコンプライアンス対応") == "regulatory_risk"

    def test_other_risk(self):
        assert classify_category("特に該当するものはありません") == "other_risk"

    def test_multiple_keywords_strongest_wins(self):
        # 市場系キーワード2つ vs 信用系1つ → market_risk
        text = "為替と株価の変動により取引先に影響"
        assert classify_category(text) == "market_risk"


# ---------------------------------------------------------------------------
# Tests: assess_severity
# ---------------------------------------------------------------------------

class TestAssessSeverity:
    def test_high(self):
        assert assess_severity("重大な影響を及ぼす可能性") == "high"

    def test_low(self):
        assert assess_severity("限定的な影響にとどまる") == "low"

    def test_medium_default(self):
        assert assess_severity("何らかの影響がある可能性") == "medium"

    def test_high_keywords(self):
        assert assess_severity("著しい損害") == "high"
        assert assess_severity("事業継続に関わる") == "high"

    def test_low_keywords(self):
        assert assess_severity("軽微な影響") == "low"


# ---------------------------------------------------------------------------
# Tests: split_risk_paragraphs
# ---------------------------------------------------------------------------

class TestSplitRiskParagraphs:
    def test_numbered_split(self):
        text = "(1) 為替リスクがあります。為替変動は重要です。\n(2) 金利リスクがあります。金利変動は重要です。"
        parts = split_risk_paragraphs(text)
        assert len(parts) == 2

    def test_double_newline_split(self):
        text = "為替リスクの影響は大きい可能性があります。\n\n金利リスクについても留意が必要と考えられます。"
        parts = split_risk_paragraphs(text)
        assert len(parts) == 2

    def test_single_paragraph(self):
        text = "為替変動リスクは当社グループの業績に影響を及ぼす可能性があります。"
        parts = split_risk_paragraphs(text)
        assert len(parts) == 1
        assert parts[0] == text

    def test_empty(self):
        assert split_risk_paragraphs("") == []

    def test_short_fragments_filtered(self):
        text = "(1) 短い\n(2) これは十分に長いテキストで最低20文字はあるはずです"
        parts = split_risk_paragraphs(text)
        assert len(parts) == 1


# ---------------------------------------------------------------------------
# Tests: extract_risk_texts_from_zip
# ---------------------------------------------------------------------------

class TestExtractFromZip:
    def test_normal_xbrl(self):
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = _create_zip(Path(tmp), "S100TEST", SAMPLE_XBRL)
            texts = extract_risk_texts_from_zip(zip_path)
            assert len(texts) >= 1
            tag, content = texts[0]
            assert tag == "BusinessRisksTextBlock"
            assert "為替" in content

    def test_empty_text_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = _create_zip(Path(tmp), "S100EMPTY", SAMPLE_XBRL_EMPTY)
            texts = extract_risk_texts_from_zip(zip_path)
            assert texts == []

    def test_no_risk_element(self):
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = _create_zip(Path(tmp), "S100NORISK", SAMPLE_XBRL_NO_RISK)
            texts = extract_risk_texts_from_zip(zip_path)
            assert texts == []

    def test_nonexistent_xbrl_in_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "noxml.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("readme.txt", "no xbrl here")
            texts = extract_risk_texts_from_zip(zip_path)
            assert texts == []


# ---------------------------------------------------------------------------
# Tests: extract_risk_texts_from_dir
# ---------------------------------------------------------------------------

class TestExtractFromDir:
    def test_multiple_zips(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _create_zip(tmp_path, "S100AAA", SAMPLE_XBRL)
            _create_zip(tmp_path, "S100BBB", SAMPLE_XBRL)
            result = extract_risk_texts_from_dir(tmp_path)
            assert "S100AAA" in result
            assert "S100BBB" in result

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = extract_risk_texts_from_dir(Path(tmp))
            assert result == {}

    def test_nonexistent_dir(self):
        result = extract_risk_texts_from_dir(Path("/nonexistent/path"))
        assert result == {}


# ---------------------------------------------------------------------------
# Tests: extract_risk_texts_from_parsed_json
# ---------------------------------------------------------------------------

class TestExtractFromParsedJson:
    def test_with_source_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Create directory structure: data/{ticker}/raw/edinet/
            raw_dir = tmp_path / "data" / "7203" / "raw" / "edinet"
            raw_dir.mkdir(parents=True)
            parsed_dir = tmp_path / "data" / "7203" / "parsed"
            parsed_dir.mkdir(parents=True)

            zip_rel = f"data/7203/raw/edinet/S100DOC1.zip"
            _create_zip(raw_dir, "S100DOC1", SAMPLE_XBRL)

            financials = {
                "ticker": "7203",
                "documents": [
                    {
                        "document_id": "S100DOC1",
                        "source_zip": zip_rel,
                    }
                ],
            }
            json_path = parsed_dir / "financials.json"
            json_path.write_text(json.dumps(financials), encoding="utf-8")

            result = extract_risk_texts_from_parsed_json(json_path)
            assert "S100DOC1" in result

    def test_fallback_to_raw_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            raw_dir = tmp_path / "raw" / "edinet"
            raw_dir.mkdir(parents=True)
            parsed_dir = tmp_path / "parsed"
            parsed_dir.mkdir(parents=True)

            _create_zip(raw_dir, "S100FB01", SAMPLE_XBRL)

            financials = {
                "ticker": "9999",
                "documents": [],
            }
            json_path = parsed_dir / "financials.json"
            json_path.write_text(json.dumps(financials), encoding="utf-8")

            result = extract_risk_texts_from_parsed_json(json_path)
            assert "S100FB01" in result

    def test_empty_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            financials = {"ticker": "", "documents": []}
            json_path = Path(tmp) / "financials.json"
            json_path.write_text(json.dumps(financials), encoding="utf-8")

            result = extract_risk_texts_from_parsed_json(json_path)
            assert result == {}


# ---------------------------------------------------------------------------
# Tests: analyze_risks
# ---------------------------------------------------------------------------

class TestAnalyzeRisks:
    def test_full_analysis(self):
        risk_texts = {
            "S100TEST": [
                ("BusinessRisksTextBlock",
                 "(1) 為替リスクについて\n当社は為替変動による重大な影響を受ける可能性があります。\n\n"
                 "(2) 取引先の信用リスク\n主要取引先の債務不履行により貸倒が発生する可能性があります。\n\n"
                 "(3) サイバーセキュリティリスク\nサイバー攻撃による情報システム障害が限定的に発生する可能性があります。")
            ]
        }
        result = analyze_risks("7203", risk_texts)
        assert result.ticker == "7203"
        assert "S100TEST" in result.source_documents
        assert len(result.risk_items) >= 3

        d = result.to_dict()
        assert d["summary"]["total_risks"] >= 3
        assert d["risk_categories"]["market_risk"]  # at least 1
        assert d["risk_categories"]["credit_risk"]
        assert d["risk_categories"]["operational_risk"]

    def test_empty_input(self):
        result = analyze_risks("0000", {})
        assert result.risk_items == []
        d = result.to_dict()
        assert d["summary"]["total_risks"] == 0

    def test_multiple_documents(self):
        risk_texts = {
            "DOC1": [("BusinessRisksTextBlock", "為替変動は当社グループの業績に大きな影響を与える可能性があります。")],
            "DOC2": [("BusinessRisksTextBlock", "法令改正によるコンプライアンス違反のリスクがあると認識しています。")],
        }
        result = analyze_risks("1234", risk_texts)
        assert len(result.source_documents) == 2
        assert result.risk_items[0].source == "DOC1"
        assert result.risk_items[1].source == "DOC2"


# ---------------------------------------------------------------------------
# Tests: RiskAnalysisResult.to_dict
# ---------------------------------------------------------------------------

class TestToDictOutput:
    def test_structure(self):
        result = RiskAnalysisResult(
            ticker="7203",
            analyzed_at="2026-02-26T00:00:00+00:00",
            source_documents=["S100A"],
            risk_items=[
                RiskItem(text="為替リスク", source="S100A", severity="high", category="market_risk"),
                RiskItem(text="法規制リスク", source="S100A", severity="medium", category="regulatory_risk"),
                RiskItem(text="その他", source="S100A", severity="low", category="other_risk"),
            ],
        )
        d = result.to_dict()
        assert d["ticker"] == "7203"
        assert len(d["risk_categories"]["market_risk"]) == 1
        assert len(d["risk_categories"]["regulatory_risk"]) == 1
        assert len(d["risk_categories"]["other_risk"]) == 1
        assert d["summary"]["total_risks"] == 3
        assert d["summary"]["by_severity"]["high"] == 1
        assert d["summary"]["by_severity"]["medium"] == 1
        assert d["summary"]["by_severity"]["low"] == 1
        assert d["summary"]["by_category"]["market_risk"] == 1
        assert d["summary"]["by_category"]["credit_risk"] == 0


# ---------------------------------------------------------------------------
# Tests: run_analysis
# ---------------------------------------------------------------------------

class TestRunAnalysis:
    def test_with_input_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _create_zip(tmp_path, "S100RUN1", SAMPLE_XBRL)
            result = run_analysis("7203", input_dir=tmp_path)
            assert result.ticker == "7203"
            assert len(result.risk_items) > 0

    def test_with_parsed_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            raw_dir = tmp_path / "raw" / "edinet"
            raw_dir.mkdir(parents=True)
            parsed_dir = tmp_path / "parsed"
            parsed_dir.mkdir(parents=True)

            _create_zip(raw_dir, "S100PJ01", SAMPLE_XBRL)
            financials = {"ticker": "7777", "documents": []}
            json_path = parsed_dir / "financials.json"
            json_path.write_text(json.dumps(financials), encoding="utf-8")

            result = run_analysis("7777", parsed_json=json_path)
            assert result.ticker == "7777"
            assert len(result.risk_items) > 0

    def test_no_input_raises(self):
        with pytest.raises(ValueError, match="Either input_dir or parsed_json"):
            run_analysis("0000")

    def test_empty_dir_returns_zero_risks(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_analysis("0000", input_dir=Path(tmp))
            assert result.risk_items == []


# ---------------------------------------------------------------------------
# Tests: CLI (main.py)
# ---------------------------------------------------------------------------

class TestCli:
    def test_no_command_returns_1(self):
        assert cli_main([]) == 1

    def test_analyze_no_input_returns_1(self, capsys):
        assert cli_main(["analyze", "--ticker", "7203"]) == 1
        captured = capsys.readouterr()
        assert "input-dir" in captured.err or "parsed-json" in captured.err

    def test_analyze_with_input_dir_stdout(self, capsys):
        with tempfile.TemporaryDirectory() as tmp:
            _create_zip(Path(tmp), "S100CLI1", SAMPLE_XBRL)
            ret = cli_main(["analyze", "--ticker", "7203", "--input-dir", tmp])
            assert ret == 0
            captured = capsys.readouterr()
            output = json.loads(captured.out)
            assert output["ticker"] == "7203"
            assert output["summary"]["total_risks"] > 0

    def test_analyze_with_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _create_zip(tmp_path, "S100CLI2", SAMPLE_XBRL)
            out_file = tmp_path / "output" / "result.json"
            ret = cli_main([
                "analyze", "--ticker", "9999",
                "--input-dir", str(tmp_path),
                "--output", str(out_file),
            ])
            assert ret == 0
            assert out_file.exists()
            data = json.loads(out_file.read_text(encoding="utf-8"))
            assert data["ticker"] == "9999"

    def test_analyze_with_parsed_json(self, capsys):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            raw_dir = tmp_path / "raw" / "edinet"
            raw_dir.mkdir(parents=True)
            parsed_dir = tmp_path / "parsed"
            parsed_dir.mkdir(parents=True)

            _create_zip(raw_dir, "S100CLIP", SAMPLE_XBRL)
            financials = {"ticker": "5555", "documents": []}
            json_path = parsed_dir / "financials.json"
            json_path.write_text(json.dumps(financials), encoding="utf-8")

            ret = cli_main(["analyze", "--ticker", "5555", "--parsed-json", str(json_path)])
            assert ret == 0

    def test_build_parser(self):
        p = build_parser()
        assert p is not None
