"""web-data-harmonizer: harmonizer.py のユニットテスト。

テスト対象:
- _parse_japanese_number
- _infer_period_end / _infer_fiscal_year
- _harmonize_yahoo / _harmonize_kabutan / _harmonize_shikiho
- _extract_indicators / _extract_qualitative
- _merge_periods
- harmonize (E2E)
"""

import copy

import pytest

from harmonizer import (
    _extract_indicators,
    _extract_qualitative,
    _harmonize_kabutan,
    _harmonize_shikiho,
    _harmonize_yahoo,
    _infer_fiscal_year,
    _infer_period_end,
    _merge_periods,
    _parse_japanese_number,
    harmonize,
)


# ============================================================
# _parse_japanese_number
# ============================================================
class TestParseJapaneseNumber:
    def test_comma_separated(self):
        assert _parse_japanese_number("1,234") == 1234.0

    def test_hyakuman_en(self):
        assert _parse_japanese_number("1,234百万円") == 1234000000.0

    def test_oku(self):
        assert _parse_japanese_number("5億") == 500000000.0

    def test_cho(self):
        assert _parse_japanese_number("1.5兆") == 1500000000000.0

    def test_man(self):
        assert _parse_japanese_number("3万") == 30000.0

    def test_negative_triangle(self):
        assert _parse_japanese_number("△1,234") == -1234.0

    def test_negative_filled_triangle(self):
        assert _parse_japanese_number("▲1,234") == -1234.0

    def test_none_input(self):
        assert _parse_japanese_number(None) is None

    def test_empty_string(self):
        assert _parse_japanese_number("") is None

    def test_dash(self):
        assert _parse_japanese_number("---") is None

    def test_na(self):
        assert _parse_japanese_number("N/A") is None

    def test_percent_strip(self):
        assert _parse_japanese_number("2.3%") == pytest.approx(2.3)

    def test_numeric_passthrough_int(self):
        assert _parse_japanese_number(42) == 42.0

    def test_numeric_passthrough_float(self):
        assert _parse_japanese_number(3.14) == pytest.approx(3.14)


# ============================================================
# _infer_period_end
# ============================================================
class TestInferPeriodEnd:
    def test_yahoo_format(self):
        assert _infer_period_end("2024-03", "yahoo") == "2024-03-31"

    def test_kabutan_format(self):
        assert _infer_period_end("2024.03", "kabutan") == "2024-03-31"

    def test_february_leap(self):
        assert _infer_period_end("2024-02", "yahoo") == "2024-02-29"

    def test_february_non_leap(self):
        assert _infer_period_end("2023-02", "yahoo") == "2023-02-28"

    def test_invalid_format(self):
        assert _infer_period_end("invalid", "yahoo") is None

    def test_none_input(self):
        assert _infer_period_end(None, "yahoo") is None

    def test_december(self):
        assert _infer_period_end("2024-12", "yahoo") == "2024-12-31"

    def test_june(self):
        assert _infer_period_end("2024-06", "kabutan") == "2024-06-30"


# ============================================================
# _infer_fiscal_year
# ============================================================
class TestInferFiscalYear:
    def test_normal(self):
        assert _infer_fiscal_year("2024-03-31") == 2024

    def test_none(self):
        assert _infer_fiscal_year(None) is None

    def test_invalid(self):
        assert _infer_fiscal_year("invalid") is None

    def test_december(self):
        assert _infer_fiscal_year("2024-12-31") == 2024


# ============================================================
# _harmonize_yahoo
# ============================================================
class TestHarmonizeYahoo:
    def test_normal_data(self, sample_web_research):
        data = sample_web_research["sources"]["yahoo"]["data"]
        result = _harmonize_yahoo(data)
        assert len(result) == 3
        entry = result[0]
        assert entry["period_end"] == "2024-03-31"
        assert entry["fiscal_year"] == 2024
        assert entry["quarter"] == "FY"
        assert entry["source"] == "web:yahoo"
        assert entry["pl"]["revenue"] == 180000.0
        assert entry["pl"]["operating_income"] == 12000.0
        assert entry["pl"]["ordinary_income"] is None
        assert entry["bs"]["total_assets"] is None
        assert entry["cf"]["operating_cf"] is None

    def test_empty_financials(self):
        data = {"financials": [], "indicators": {}}
        result = _harmonize_yahoo(data)
        assert result == []

    def test_null_data(self):
        result = _harmonize_yahoo(None)
        assert result == []

    def test_partial_missing(self, sample_web_research):
        data = copy.deepcopy(sample_web_research["sources"]["yahoo"]["data"])
        data["financials"][0]["revenue"] = None
        result = _harmonize_yahoo(data)
        assert result[0]["pl"]["revenue"] is None
        assert result[0]["pl"]["operating_income"] == 12000.0

    def test_bs_cf_are_null(self, sample_web_research):
        data = sample_web_research["sources"]["yahoo"]["data"]
        result = _harmonize_yahoo(data)
        for entry in result:
            for k in ("total_assets", "current_assets", "noncurrent_assets",
                       "total_liabilities", "current_liabilities",
                       "noncurrent_liabilities", "total_equity", "net_assets"):
                assert entry["bs"][k] is None
            for k in ("operating_cf", "investing_cf", "financing_cf", "free_cash_flow"):
                assert entry["cf"][k] is None


# ============================================================
# _harmonize_kabutan
# ============================================================
class TestHarmonizeKabutan:
    def test_normal_data(self, sample_web_research):
        data = sample_web_research["sources"]["kabutan"]["data"]
        result = _harmonize_kabutan(data)
        assert len(result) == 3
        entry = result[0]
        assert entry["period_end"] == "2024-03-31"
        assert entry["source"] == "web:kabutan"
        assert entry["pl"]["revenue"] == 180000
        assert entry["pl"]["ordinary_income"] == 11500
        assert entry["pl"]["net_income"] == 7800

    def test_empty_financials(self):
        data = {"financials": []}
        result = _harmonize_kabutan(data)
        assert result == []

    def test_null_data(self):
        result = _harmonize_kabutan(None)
        assert result == []

    def test_eps_value(self, sample_web_research):
        data = sample_web_research["sources"]["kabutan"]["data"]
        result = _harmonize_kabutan(data)
        # eps は pl 内または annual エントリ直下に格納される
        entry = result[0]
        eps_val = entry["pl"].get("eps") or entry.get("eps")
        assert eps_val == pytest.approx(585.0)

    def test_partial_missing(self):
        data = {"financials": [
            {"period": "2024.03", "revenue": 100000, "operating_income": None,
             "ordinary_income": None, "net_income": None, "eps": None}
        ]}
        result = _harmonize_kabutan(data)
        assert len(result) == 1
        assert result[0]["pl"]["revenue"] == 100000
        assert result[0]["pl"]["operating_income"] is None


# ============================================================
# _harmonize_shikiho
# ============================================================
class TestHarmonizeShikiho:
    def test_string_to_number(self, sample_web_research):
        data = sample_web_research["sources"]["shikiho"]["data"]
        result = _harmonize_shikiho(data)
        assert len(result) >= 1
        entry = result[0]
        assert entry["pl"]["revenue"] == pytest.approx(200000000000.0)
        assert entry["pl"]["operating_income"] == pytest.approx(14000000000.0)

    def test_empty_forecast(self):
        data = {"earnings_forecast": None, "company_overview": {}}
        result = _harmonize_shikiho(data)
        assert result == []

    def test_partial_forecast(self):
        data = {
            "earnings_forecast": {"売上高": "100百万円"},
            "company_overview": {},
        }
        result = _harmonize_shikiho(data)
        assert len(result) == 1
        assert result[0]["pl"]["revenue"] == pytest.approx(100000000.0)

    def test_all_unparseable(self):
        data = {
            "earnings_forecast": {"売上高": "非開示", "営業利益": "---", "経常利益": "N/A", "純利益": ""},
            "company_overview": {},
        }
        result = _harmonize_shikiho(data)
        if len(result) > 0:
            entry = result[0]
            assert entry["pl"]["revenue"] is None
            assert entry["pl"]["operating_income"] is None
            assert entry["pl"]["ordinary_income"] is None
            assert entry["pl"]["net_income"] is None


# ============================================================
# _extract_indicators
# ============================================================
class TestExtractIndicators:
    def test_merge_kabutan_priority(self, sample_web_research):
        sources = sample_web_research["sources"]
        result = _extract_indicators(sources)
        assert result["per"] == 15.0
        assert result["pbr"] == 1.7
        assert result["dividend_yield"] == 2.2

    def test_yahoo_only(self, sample_web_research):
        sources = copy.deepcopy(sample_web_research["sources"])
        del sources["kabutan"]
        del sources["shikiho"]
        result = _extract_indicators(sources)
        assert result["per"] == 15.2
        assert result["pbr"] == 1.8
        assert result["shares_outstanding"] == 13333333

    def test_both_null(self):
        sources = {}
        result = _extract_indicators(sources)
        assert result["per"] is None
        assert result["pbr"] is None

    def test_shikiho_string_parse(self):
        sources = {
            "shikiho": {
                "collected": True,
                "data": {
                    "indicators": {"PER": "14.8", "PBR": "1.6", "dividend_yield": "2.3%"}
                },
            }
        }
        result = _extract_indicators(sources)
        assert result["per"] == pytest.approx(14.8)
        assert result["pbr"] == pytest.approx(1.6)
        assert result["dividend_yield"] == pytest.approx(2.3)


# ============================================================
# _extract_qualitative
# ============================================================
class TestExtractQualitative:
    def test_full_sources(self, sample_web_research):
        sources = sample_web_research["sources"]
        result = _extract_qualitative(sources)
        assert "company_overview" in result
        assert result["company_overview"]["name"] == "コメ兵ホールディングス"
        assert "consensus" in result
        assert "earnings_flash" in result
        assert "ir_links" in result

    def test_partial(self, sample_web_research):
        sources = copy.deepcopy(sample_web_research["sources"])
        del sources["shikiho"]
        del sources["homepage"]
        result = _extract_qualitative(sources)
        assert result.get("company_overview") is None or result.get("company_overview") == {}
        assert "earnings_flash" in result

    def test_none(self):
        result = _extract_qualitative({})
        assert isinstance(result, dict)


# ============================================================
# _merge_periods
# ============================================================
class TestMergePeriods:
    def _make_entry(self, period_end, source, revenue=None, ordinary_income=None):
        return {
            "period_end": period_end,
            "fiscal_year": int(period_end[:4]) if period_end else None,
            "quarter": "FY",
            "source": source,
            "statement_type": None,
            "bs": {"total_assets": None, "current_assets": None,
                    "noncurrent_assets": None, "total_liabilities": None,
                    "current_liabilities": None, "noncurrent_liabilities": None,
                    "total_equity": None, "net_assets": None},
            "pl": {"revenue": revenue, "operating_income": None,
                    "ordinary_income": ordinary_income, "net_income": None,
                    "gross_profit": None},
            "cf": {"operating_cf": None, "investing_cf": None,
                    "financing_cf": None, "free_cash_flow": None},
        }

    def test_same_period_merge(self):
        yahoo = [self._make_entry("2024-03-31", "web:yahoo", revenue=180000.0)]
        kabutan = [self._make_entry("2024-03-31", "web:kabutan", revenue=180000, ordinary_income=11500)]
        result = _merge_periods([yahoo, kabutan])
        assert len(result) == 1
        assert result[0]["pl"]["ordinary_income"] == 11500

    def test_different_periods(self):
        yahoo = [self._make_entry("2024-03-31", "web:yahoo", revenue=180000.0)]
        kabutan = [self._make_entry("2023-03-31", "web:kabutan", revenue=160000)]
        result = _merge_periods([yahoo, kabutan])
        assert len(result) == 2

    def test_source_attribution(self):
        yahoo = [self._make_entry("2024-03-31", "web:yahoo", revenue=180000.0)]
        kabutan = [self._make_entry("2024-03-31", "web:kabutan", revenue=180000)]
        result = _merge_periods([yahoo, kabutan])
        source = result[0]["source"]
        assert "yahoo" in source
        assert "kabutan" in source

    def test_sort_order(self):
        entries1 = [self._make_entry("2022-03-31", "web:yahoo")]
        entries2 = [self._make_entry("2024-03-31", "web:kabutan")]
        entries3 = [self._make_entry("2023-03-31", "web:yahoo")]
        result = _merge_periods([entries1, entries2, entries3])
        assert result[0]["period_end"] == "2024-03-31"
        assert result[1]["period_end"] == "2023-03-31"
        assert result[2]["period_end"] == "2022-03-31"


# ============================================================
# harmonize (E2E)
# ============================================================
class TestHarmonize:
    def test_e2e_all_sources(self, sample_web_research):
        result = harmonize(sample_web_research)
        assert result["ticker"] == "2780"
        assert "generated_at" in result
        assert "annual" in result
        assert len(result["annual"]) >= 3
        assert "indicators" in result
        assert "qualitative" in result

    def test_source_filter_single(self, sample_web_research):
        result = harmonize(sample_web_research, source_filter="yahoo")
        meta = result["harmonization_metadata"]
        assert "yahoo" in meta["sources_used"]
        assert "kabutan" not in meta["sources_used"]

    def test_source_filter_multi(self, sample_web_research):
        result = harmonize(sample_web_research, source_filter="yahoo,kabutan")
        meta = result["harmonization_metadata"]
        assert "yahoo" in meta["sources_used"]
        assert "kabutan" in meta["sources_used"]
        assert "shikiho" not in meta["sources_used"]

    def test_output_schema(self, sample_web_research):
        result = harmonize(sample_web_research)
        required_keys = {"ticker", "company_name", "generated_at",
                         "harmonization_metadata", "annual", "indicators", "qualitative"}
        assert required_keys.issubset(result.keys())
        meta = result["harmonization_metadata"]
        assert "input_sources" in meta
        assert "sources_used" in meta
        assert "source_priority" in meta

    def test_financial_record_compatible(self, sample_web_research):
        result = harmonize(sample_web_research)
        for entry in result["annual"]:
            assert "period_end" in entry
            assert "fiscal_year" in entry
            assert "bs" in entry
            assert "pl" in entry
            assert "cf" in entry
            for v in entry["pl"].values():
                assert v is None or isinstance(v, (int, float))
            for v in entry["bs"].values():
                assert v is None or isinstance(v, (int, float))
            for v in entry["cf"].values():
                assert v is None or isinstance(v, (int, float))

    def test_sources_skipped_in_metadata(self, sample_web_research):
        result = harmonize(sample_web_research, source_filter="yahoo")
        meta = result["harmonization_metadata"]
        assert "sources_skipped" in meta
        assert "kabutan" in meta["sources_skipped"]
        assert "shikiho" in meta["sources_skipped"]
        assert "yahoo" not in meta["sources_skipped"]

    def test_source_priority_in_metadata(self, sample_web_research):
        result = harmonize(sample_web_research)
        meta = result["harmonization_metadata"]
        assert "source_priority" in meta
        assert isinstance(meta["source_priority"], str)
        assert "kabutan" in meta["source_priority"]

    def test_input_sources_booleans(self, sample_web_research):
        result = harmonize(sample_web_research)
        meta = result["harmonization_metadata"]
        input_sources = meta["input_sources"]
        assert input_sources["yahoo"] is True
        assert input_sources["kabutan"] is True
        assert input_sources["shikiho"] is True
        assert input_sources["homepage"] is True

    def test_input_sources_missing_source(self):
        data = {
            "ticker": "9999",
            "company_name": None,
            "sources": {
                "yahoo": {
                    "url": "https://finance.yahoo.co.jp/quote/9999",
                    "collected": True,
                    "data": {"financials": [], "indicators": {}},
                    "error": None,
                },
            },
            "metadata": {},
        }
        result = harmonize(data)
        meta = result["harmonization_metadata"]
        assert meta["input_sources"]["yahoo"] is True
        assert meta["input_sources"].get("kabutan", False) is False
        assert meta["input_sources"].get("shikiho", False) is False


# ============================================================
# 欠測・collected:false ケース
# ============================================================
class TestCollectedFalse:
    """ソースが collected:false の場合のハンドリング。"""

    def _make_uncollected_source(self, name, url="https://example.com"):
        return {
            "url": url,
            "collected": False,
            "data": None,
            "error": "Connection timeout",
        }

    def test_yahoo_collected_false(self):
        data = {
            "ticker": "1234",
            "company_name": None,
            "sources": {
                "yahoo": self._make_uncollected_source("yahoo"),
                "kabutan": {
                    "url": "https://kabutan.jp/stock/?code=1234",
                    "collected": True,
                    "data": {
                        "financials": [
                            {"period": "2024.03", "revenue": 50000,
                             "operating_income": 3000, "ordinary_income": 2800,
                             "net_income": 1900, "eps": 100.0}
                        ],
                        "indicators": {"per": 10.0, "pbr": 1.0},
                    },
                    "error": None,
                },
            },
            "metadata": {},
        }
        result = harmonize(data, source_filter="all")
        meta = result["harmonization_metadata"]
        assert "yahoo" not in meta["sources_used"]
        assert len(result["annual"]) >= 1
        assert result["annual"][0]["source"] == "web:kabutan"

    def test_kabutan_collected_false(self, sample_web_research):
        data = copy.deepcopy(sample_web_research)
        data["sources"]["kabutan"]["collected"] = False
        data["sources"]["kabutan"]["data"] = None
        data["sources"]["kabutan"]["error"] = "HTTP 503"
        result = harmonize(data, source_filter="all")
        meta = result["harmonization_metadata"]
        assert "kabutan" not in meta["sources_used"]
        assert "yahoo" in meta["sources_used"]

    def test_shikiho_collected_false(self, sample_web_research):
        data = copy.deepcopy(sample_web_research)
        data["sources"]["shikiho"]["collected"] = False
        data["sources"]["shikiho"]["data"] = None
        result = harmonize(data, source_filter="all")
        meta = result["harmonization_metadata"]
        assert "shikiho" not in meta["sources_used"]

    def test_homepage_collected_false(self, sample_web_research):
        data = copy.deepcopy(sample_web_research)
        data["sources"]["homepage"]["collected"] = False
        data["sources"]["homepage"]["data"] = None
        result = harmonize(data, source_filter="all")
        qual = result["qualitative"]
        assert qual.get("ir_links") is None or qual.get("ir_links") == []

    def test_all_sources_collected_false(self):
        data = {
            "ticker": "0000",
            "company_name": None,
            "sources": {
                "yahoo": {"url": "u", "collected": False, "data": None, "error": "err"},
                "kabutan": {"url": "u", "collected": False, "data": None, "error": "err"},
                "shikiho": {"url": "u", "collected": False, "data": None, "error": "err"},
                "homepage": {"url": "u", "collected": False, "data": None, "error": "err"},
            },
            "metadata": {},
        }
        result = harmonize(data)
        assert result["ticker"] == "0000"
        assert result["annual"] == []
        meta = result["harmonization_metadata"]
        assert meta["sources_used"] == []

    def test_source_filter_excludes_uncollected(self):
        data = {
            "ticker": "5555",
            "company_name": None,
            "sources": {
                "yahoo": {"url": "u", "collected": False, "data": None, "error": "err"},
                "kabutan": {
                    "url": "u", "collected": True,
                    "data": {"financials": [{"period": "2024.03", "revenue": 10000,
                             "operating_income": 500, "ordinary_income": 400,
                             "net_income": 300, "eps": 20.0}],
                             "indicators": {}},
                    "error": None,
                },
            },
            "metadata": {},
        }
        result = harmonize(data, source_filter="yahoo")
        meta = result["harmonization_metadata"]
        assert "yahoo" not in meta["sources_used"]
        assert result["annual"] == []

    def test_collected_false_skipped_in_metadata(self, sample_web_research):
        data = copy.deepcopy(sample_web_research)
        data["sources"]["kabutan"]["collected"] = False
        data["sources"]["kabutan"]["data"] = None
        result = harmonize(data, source_filter="all")
        meta = result["harmonization_metadata"]
        assert "kabutan" in meta["sources_skipped"] or "kabutan" not in meta["sources_used"]


# ============================================================
# ソース欠損（キー自体が存在しない）ケース
# ============================================================
class TestMissingSourceKeys:
    """sources 辞書にソースキーが存在しない場合。"""

    def test_only_yahoo(self):
        data = {
            "ticker": "7777",
            "company_name": None,
            "sources": {
                "yahoo": {
                    "url": "u", "collected": True,
                    "data": {
                        "financials": [{"period": "2024-03", "revenue": 90000.0,
                                        "operating_income": 5000.0,
                                        "ordinary_income": None, "net_income": None}],
                        "indicators": {"per": 12.0, "pbr": 0.9},
                    },
                    "error": None,
                },
            },
            "metadata": {},
        }
        result = harmonize(data)
        assert len(result["annual"]) == 1
        assert result["annual"][0]["source"] == "web:yahoo"
        meta = result["harmonization_metadata"]
        assert "yahoo" in meta["sources_used"]
        assert meta["input_sources"].get("kabutan", False) is False

    def test_empty_sources(self):
        data = {
            "ticker": "0001",
            "company_name": None,
            "sources": {},
            "metadata": {},
        }
        result = harmonize(data)
        assert result["annual"] == []
        assert result["indicators"]["per"] is None
