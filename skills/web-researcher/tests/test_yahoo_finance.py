"""YahooFinanceCollector のテスト.

全テストでモック HTTP を使用（実リクエスト不使用）。
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from scripts.collector_base import CollectorError, RobotsBlockedError
from scripts.yahoo_finance import YahooFinanceCollector, _parse_japanese_number

_EVIDENCE_DIR = Path(__file__).resolve().parent / "evidence"


def _load_evidence(filename: str) -> str:
    return (_EVIDENCE_DIR / filename).read_text(encoding="utf-8")


def _make_mock_response(html: str, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = html
    resp.raise_for_status.return_value = None
    return resp


# --- test_collect_success ---


class TestCollectSuccess:
    def test_collect_success(self, mock_robots_allow):
        """モックHTML → 正しいデータ抽出。"""
        html = _load_evidence("yahoo_finance_7203.html")
        mock_response = _make_mock_response(html)

        collector = YahooFinanceCollector(config={"request_interval_seconds": 0})
        collector._client = MagicMock()
        collector._client.get.return_value = mock_response

        result = collector.collect("7203")

        assert result["collected"] is True
        assert result["error"] is None
        assert result["url"] == "https://finance.yahoo.co.jp/quote/7203"

        # 株価情報
        sp = result["data"]["stock_price"]
        assert sp["current"] == 3750.0
        assert sp["change"] == 30.0
        assert sp["change_percent"] == 0.81
        assert sp["volume"] == 24220000
        assert sp["turnover"] == 90825000000.0

        # 業績情報
        fin = result["data"]["financials"]
        assert len(fin) == 3
        assert fin[0]["period"] == "2022-03"
        assert fin[0]["revenue"] == 31379507.0
        assert fin[2]["period"] == "2024-03"
        assert fin[2]["revenue"] == 45095325.0

        # 指標
        ind = result["data"]["indicators"]
        assert ind["per"] == 13.58
        assert ind["pbr"] == 1.24
        assert ind["dividend_yield"] == 2.55
        assert ind["market_cap"] == 58757353000000.0
        assert ind["shares_outstanding"] == 15794987460

        # ニュース
        news = result["data"]["news"]
        assert len(news) == 3
        assert news[0]["title"] == "トヨタ、EV戦略を加速"
        assert "abc123" in news[0]["url"]


# --- test_parse_japanese_number ---


class TestParseJapaneseNumber:
    def test_comma_separated(self):
        assert _parse_japanese_number("1,234.56") == 1234.56
        assert _parse_japanese_number("1,234") == 1234.0

    def test_oku_man(self):
        """億/万 単位の変換。"""
        assert _parse_japanese_number("1,234億5,678万") == 123456780000.0

    def test_cho(self):
        """兆 単位の変換。"""
        assert _parse_japanese_number("1兆2,345億") == 1234500000000.0

    def test_single_unit(self):
        assert _parse_japanese_number("5万") == 50000.0
        assert _parse_japanese_number("1億") == 100000000.0
        assert _parse_japanese_number("1兆") == 1000000000000.0

    def test_suffix_removal(self):
        """単位サフィックス(倍, %, 円)の除去。"""
        assert _parse_japanese_number("13.58倍") == 13.58
        assert _parse_japanese_number("2.55%") == 2.55
        assert _parse_japanese_number("3,720円") == 3720.0

    def test_plain_number(self):
        assert _parse_japanese_number("58,757,353") == 58757353.0

    def test_none_empty(self):
        assert _parse_japanese_number(None) is None
        assert _parse_japanese_number("") is None
        assert _parse_japanese_number("---") is None
        assert _parse_japanese_number("--") is None


# --- test_parse_negative_number ---


class TestParseNegativeNumber:
    def test_triangle_negative(self):
        """△ 記号のマイナス。"""
        assert _parse_japanese_number("△1,234") == -1234.0

    def test_black_triangle_negative(self):
        """▲ 記号のマイナス。"""
        assert _parse_japanese_number("▲500") == -500.0

    def test_minus_sign(self):
        """通常のマイナス記号。"""
        assert _parse_japanese_number("-1,234") == -1234.0

    def test_negative_with_unit(self):
        """マイナス＋単位。"""
        assert _parse_japanese_number("△5億") == -500000000.0


# --- test_collect_page_not_found ---


class TestCollectPageNotFound:
    def test_collect_page_not_found(self, mock_robots_allow):
        """存在しない銘柄 → collected=False + error。"""
        html = _load_evidence("yahoo_finance_not_found.html")
        mock_response = _make_mock_response(html)

        collector = YahooFinanceCollector(config={"request_interval_seconds": 0})
        collector._client = MagicMock()
        collector._client.get.return_value = mock_response

        result = collector.collect("0000")

        assert result["collected"] is False
        assert result["data"] is None
        assert result["error"] is not None
        assert "抽出に失敗" in result["error"]

    def test_collect_http_404(self, mock_robots_allow):
        """HTTP 404 → collected=False + error。"""
        collector = YahooFinanceCollector(
            config={"request_interval_seconds": 0, "max_retries": 0}
        )
        mock_client = MagicMock()
        mock_resp_404 = MagicMock()
        mock_resp_404.status_code = 404
        mock_client.get.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=mock_resp_404
        )
        collector._client = mock_client

        result = collector.collect("0000")

        assert result["collected"] is False
        assert result["error"] is not None


# --- test_collect_robots_blocked ---


class TestCollectRobotsBlocked:
    def test_collect_robots_blocked(self, mock_robots_deny):
        """robots.txt 拒否 → collected=False + error。"""
        collector = YahooFinanceCollector(config={"request_interval_seconds": 0})
        collector._client = MagicMock()

        result = collector.collect("7203")

        assert result["collected"] is False
        assert result["data"] is None
        assert "robots.txt" in result["error"]


# --- test_news_extraction ---


class TestNewsExtraction:
    def test_news_from_articles(self, mock_robots_allow):
        """mainStocksNews.articles からのニュース抽出。"""
        html = _load_evidence("yahoo_finance_7203.html")
        mock_response = _make_mock_response(html)

        collector = YahooFinanceCollector(config={"request_interval_seconds": 0})
        collector._client = MagicMock()
        collector._client.get.return_value = mock_response

        result = collector.collect("7203")
        news = result["data"]["news"]

        assert len(news) == 3
        assert news[0]["title"] == "トヨタ、EV戦略を加速"
        assert news[1]["title"] == "トヨタ、北米販売好調"
        assert news[2]["title"] == "自動車業界の動向分析"
        for item in news:
            assert item["url"].startswith("https://")
            assert item["date"] != ""

    def test_news_from_symbol_topics(self, mock_robots_allow):
        """mainStocksNews が空の場合、symbolTopics からニュース抽出。"""
        html = _load_evidence("yahoo_finance_news_from_topics.html")
        mock_response = _make_mock_response(html)

        collector = YahooFinanceCollector(config={"request_interval_seconds": 0})
        collector._client = MagicMock()
        collector._client.get.return_value = mock_response

        result = collector.collect("9999")
        news = result["data"]["news"]

        assert len(news) == 2
        assert news[0]["title"] == "テスト企業、新製品発表"
        assert news[1]["title"] == "テスト企業、決算発表"
