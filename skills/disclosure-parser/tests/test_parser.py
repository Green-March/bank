from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import parser as disclosure_parser


SAMPLE_XBRL = """<?xml version="1.0" encoding="UTF-8"?>
<xbrl
  xmlns="http://www.xbrl.org/2003/instance"
  xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
  xmlns:jpdei_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jpdei/2023-03-31/jpdei_cor"
  xmlns:jppfs_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jppfs/2023-03-31/jppfs_cor">
  <context id="CurrentYearInstant_ConsolidatedMember">
    <entity>
      <identifier scheme="http://disclosure.edinet-fsa.go.jp">E03416</identifier>
    </entity>
    <period>
      <instant>2024-03-31</instant>
    </period>
  </context>
  <context id="CurrentYearDuration_ConsolidatedMember">
    <entity>
      <identifier scheme="http://disclosure.edinet-fsa.go.jp">E03416</identifier>
    </entity>
    <period>
      <startDate>2023-04-01</startDate>
      <endDate>2024-03-31</endDate>
    </period>
  </context>
  <unit id="JPY">
    <measure>iso4217:JPY</measure>
  </unit>

  <jpdei_cor:FilerNameInJapaneseDEI contextRef="CurrentYearInstant_ConsolidatedMember">株式会社コメ兵ホールディングス</jpdei_cor:FilerNameInJapaneseDEI>

  <jppfs_cor:TotalAssets contextRef="CurrentYearInstant_ConsolidatedMember" unitRef="JPY">1000</jppfs_cor:TotalAssets>
  <jppfs_cor:CurrentAssets contextRef="CurrentYearInstant_ConsolidatedMember" unitRef="JPY">600</jppfs_cor:CurrentAssets>
  <jppfs_cor:TotalLiabilities contextRef="CurrentYearInstant_ConsolidatedMember" unitRef="JPY">400</jppfs_cor:TotalLiabilities>
  <jppfs_cor:NetAssets contextRef="CurrentYearInstant_ConsolidatedMember" unitRef="JPY">600</jppfs_cor:NetAssets>
  <jppfs_cor:NetSales contextRef="CurrentYearDuration_ConsolidatedMember" unitRef="JPY">1200</jppfs_cor:NetSales>
  <jppfs_cor:OperatingIncome contextRef="CurrentYearDuration_ConsolidatedMember" unitRef="JPY">100</jppfs_cor:OperatingIncome>
  <jppfs_cor:OrdinaryIncome contextRef="CurrentYearDuration_ConsolidatedMember" unitRef="JPY">90</jppfs_cor:OrdinaryIncome>
  <jppfs_cor:ProfitLoss contextRef="CurrentYearDuration_ConsolidatedMember" unitRef="JPY">50</jppfs_cor:ProfitLoss>
  <jppfs_cor:NetCashProvidedByUsedInOperatingActivities contextRef="CurrentYearDuration_ConsolidatedMember" unitRef="JPY">140</jppfs_cor:NetCashProvidedByUsedInOperatingActivities>
  <jppfs_cor:NetCashProvidedByUsedInInvestingActivities contextRef="CurrentYearDuration_ConsolidatedMember" unitRef="JPY" sign="-">30</jppfs_cor:NetCashProvidedByUsedInInvestingActivities>
  <jppfs_cor:NetCashProvidedByUsedInFinancingActivities contextRef="CurrentYearDuration_ConsolidatedMember" unitRef="JPY">-20</jppfs_cor:NetCashProvidedByUsedInFinancingActivities>
</xbrl>
"""


SAMPLE_XBRL_WITH_NONCURRENT_ONLY = """<?xml version="1.0" encoding="UTF-8"?>
<xbrl
  xmlns="http://www.xbrl.org/2003/instance"
  xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
  xmlns:jppfs_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jppfs/2023-03-31/jppfs_cor">
  <context id="CurrentYearInstant_ConsolidatedMember">
    <entity>
      <identifier scheme="http://disclosure.edinet-fsa.go.jp">E03416</identifier>
    </entity>
    <period>
      <instant>2024-03-31</instant>
    </period>
  </context>
  <unit id="JPY">
    <measure>iso4217:JPY</measure>
  </unit>
  <jppfs_cor:NonCurrentAssets contextRef="CurrentYearInstant_ConsolidatedMember" unitRef="JPY">700</jppfs_cor:NonCurrentAssets>
  <jppfs_cor:NonCurrentLiabilities contextRef="CurrentYearInstant_ConsolidatedMember" unitRef="JPY">200</jppfs_cor:NonCurrentLiabilities>
  <jppfs_cor:TotalAssets contextRef="CurrentYearInstant_ConsolidatedMember" unitRef="JPY">1000</jppfs_cor:TotalAssets>
  <jppfs_cor:TotalLiabilities contextRef="CurrentYearInstant_ConsolidatedMember" unitRef="JPY">500</jppfs_cor:TotalLiabilities>
</xbrl>
"""


def _create_sample_zip(zip_path: Path, xbrl_body: str = SAMPLE_XBRL) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("XBRL/PublicDoc/sample.xbrl", xbrl_body)


class DisclosureParserTests(unittest.TestCase):
    def test_parse_edinet_zip_extracts_normalized_statements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "S100TEST.zip"
            _create_sample_zip(zip_path)

            parsed = disclosure_parser.parse_edinet_zip(zip_path, ticker="2780")

            self.assertEqual(parsed.document_id, "S100TEST")
            self.assertEqual(parsed.company_name, "株式会社コメ兵ホールディングス")
            self.assertEqual(len(parsed.periods), 1)

            period = parsed.periods[0]
            self.assertEqual(period.period_end, "2024-03-31")
            self.assertEqual(period.period_start, "2023-04-01")
            self.assertEqual(period.period_type, "mixed")
            self.assertEqual(period.bs["total_assets"], 1000)
            self.assertEqual(period.bs["total_liabilities"], 400)
            self.assertEqual(period.pl["revenue"], 1200)
            self.assertEqual(period.pl["operating_income"], 100)
            self.assertEqual(period.cf["operating_cf"], 140)
            self.assertEqual(period.cf["investing_cf"], -30)
            self.assertEqual(period.cf["free_cash_flow"], 110)
            self.assertIsNone(period.bs["total_equity"])

    def test_write_outputs_creates_document_and_aggregate_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            input_dir = base / "raw" / "edinet"
            output_dir = base / "parsed"
            _create_sample_zip(input_dir / "S100TEST.zip")

            documents = disclosure_parser.parse_edinet_directory(
                input_dir=input_dir,
                ticker="2780",
            )
            saved = disclosure_parser.write_outputs(
                documents=documents,
                output_dir=output_dir,
                ticker="2780",
            )

            self.assertIn("S100TEST", saved)
            self.assertIn("financials", saved)

            aggregate_path = Path(saved["financials"])
            payload = json.loads(aggregate_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["ticker"], "2780")
            self.assertEqual(payload["document_count"], 1)
            self.assertEqual(payload["period_index"][0]["pl"]["net_income"], 50)

    def test_non_current_concepts_do_not_map_to_current_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "S100NONCURRENT.zip"
            _create_sample_zip(zip_path, xbrl_body=SAMPLE_XBRL_WITH_NONCURRENT_ONLY)

            parsed = disclosure_parser.parse_edinet_zip(zip_path, ticker="2780")
            self.assertEqual(len(parsed.periods), 1)
            period = parsed.periods[0]

            self.assertEqual(period.bs["total_assets"], 1000)
            self.assertEqual(period.bs["total_liabilities"], 500)
            self.assertIsNone(period.bs["current_assets"])
            self.assertIsNone(period.bs["current_liabilities"])

    def test_invalid_zip_raises_parser_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            invalid_zip = Path(tmp) / "broken.zip"
            invalid_zip.write_text("not a zip file", encoding="utf-8")
            with self.assertRaises(disclosure_parser.ParserError):
                disclosure_parser.parse_edinet_zip(invalid_zip, ticker="2780")

    def test_invalid_xml_raises_parser_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "S100BROKEN.zip"
            _create_sample_zip(zip_path, xbrl_body="<xbrl><broken></xbrl>")
            with self.assertRaises(disclosure_parser.ParserError):
                disclosure_parser.parse_edinet_zip(zip_path, ticker="2780")

    def test_cli_accepts_ticker_and_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            input_dir = base / "data" / "2780" / "raw" / "edinet"
            output_dir = base / "data" / "2780" / "parsed"
            _create_sample_zip(input_dir / "S100TEST.zip")

            main_py = SCRIPT_DIR / "main.py"
            result = subprocess.run(
                [
                    sys.executable,
                    str(main_py),
                    "--ticker",
                    "2780",
                    "--input-dir",
                    str(input_dir),
                    "--output-dir",
                    str(output_dir),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue((output_dir / "S100TEST.json").exists())
            self.assertTrue((output_dir / "financials.json").exists())

    def test_cli_rejects_mismatched_code_and_ticker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            main_py = SCRIPT_DIR / "main.py"
            result = subprocess.run(
                [
                    sys.executable,
                    str(main_py),
                    "--code",
                    "2780",
                    "--ticker",
                    "9999",
                    "--input-dir",
                    tmp,
                    "--output-dir",
                    tmp,
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("differ", result.stderr)


if __name__ == "__main__":
    unittest.main()
