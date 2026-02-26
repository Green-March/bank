"""KabutanCollector のテスト.

全テストでモック HTTP を使用（実リクエスト不使用）。
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from bs4 import BeautifulSoup

from scripts.kabutan import KabutanCollector, _parse_number, _parse_table, _parse_market_cap
from scripts.collector_base import RobotsBlockedError

_EVIDENCE = Path(__file__).resolve().parent / "evidence"


def _load_html(filename: str) -> str:
    return (_EVIDENCE / filename).read_text(encoding="utf-8")


def _make_mock_response(html: str, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = html
    resp.raise_for_status.return_value = None
    return resp


class TestCollectSuccess:
    """test_collect_success: モックHTML → 正しいデータ抽出。"""

    def test_collect_success(self, mock_robots_allow):
        html = _load_html("kabutan_7203.html")
        mock_response = _make_mock_response(html)

        config = {"request_interval_seconds": 0}
        collector = KabutanCollector(config=config)
        collector._client = MagicMock()
        collector._client.get.return_value = mock_response

        result = collector.collect("7203")

        assert result["collected"] is True
        assert result["error"] is None
        assert result["url"] == "https://kabutan.jp/stock/?code=7203"

        data = result["data"]
        assert data is not None

        # 株価情報
        sp = data["stock_price"]
        assert sp["current"] == 8450
        assert sp["change"] == 120
        assert sp["prev_close"] == 8330
        assert sp["open"] == 8350
        assert sp["high"] == 8500
        assert sp["low"] == 8300
        assert sp["volume"] == 12345678

        # 業績推移
        fin = data["financials"]
        assert len(fin) == 3
        assert fin[0]["period"] == "2024.03"
        assert fin[0]["revenue"] == 45095325
        assert fin[0]["operating_income"] == 5352934
        assert fin[0]["eps"] == 358.9

        # 財務指標
        ind = data["indicators"]
        assert ind["per"] == 10.5
        assert ind["pbr"] == 1.2
        assert ind["dividend_yield"] == 2.8
        assert ind["market_cap"] == 3.5e12

        # 決算速報
        ef = data["earnings_flash"]
        assert ef is not None
        assert "第3四半期" in ef["title"]
        assert ef["date"] == "2026/02/05"

        # ニュース
        news = data["news"]
        assert len(news) == 3
        assert news[0]["title"] == "トヨタ、新型EV発表"
        assert news[0]["date"] == "02/25"


class TestParseTable:
    """test_parse_table: テーブルパースの検証。"""

    def test_parse_table_header_data(self):
        html = """
        <table>
          <tr><th>名前</th><th>値</th></tr>
          <tr><td>A</td><td>100</td></tr>
          <tr><td>B</td><td>200</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        rows = _parse_table(table)

        assert len(rows) == 2
        assert rows[0] == {"名前": "A", "値": "100"}
        assert rows[1] == {"名前": "B", "値": "200"}

    def test_parse_table_empty(self):
        html = "<table></table>"
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        rows = _parse_table(table)
        assert rows == []


class TestParseFinancialsTable:
    """test_parse_financials_table: 業績テーブルの複数期分パース。"""

    def test_multi_period_financials(self, mock_robots_allow):
        html = _load_html("kabutan_7203.html")
        mock_response = _make_mock_response(html)

        config = {"request_interval_seconds": 0}
        collector = KabutanCollector(config=config)
        collector._client = MagicMock()
        collector._client.get.return_value = mock_response

        result = collector.collect("7203")
        financials = result["data"]["financials"]

        assert len(financials) == 3
        periods = [f["period"] for f in financials]
        assert "2024.03" in periods
        assert "2025.03" in periods
        assert "2026.03予" in periods

        # 各期の数値が正しいこと
        f2025 = [f for f in financials if f["period"] == "2025.03"][0]
        assert f2025["revenue"] == 46200000
        assert f2025["operating_income"] == 5500000
        assert f2025["ordinary_income"] == 5800000
        assert f2025["net_income"] == 5100000
        assert f2025["eps"] == 370.2


class TestCollectPageNotFound:
    """test_collect_page_not_found: 存在しない銘柄 → collected=False + error。"""

    def test_page_not_found(self, mock_robots_allow):
        html = _load_html("kabutan_not_found.html")
        mock_response = _make_mock_response(html)

        config = {"request_interval_seconds": 0}
        collector = KabutanCollector(config=config)
        collector._client = MagicMock()
        collector._client.get.return_value = mock_response

        result = collector.collect("9999")

        assert result["collected"] is False
        assert result["data"] is None
        assert "銘柄が見つかりません" in result["error"]


class TestCollectRobotsBlocked:
    """test_collect_robots_blocked: robots.txt 拒否 → collected=False + error。"""

    def test_robots_blocked(self, mock_robots_deny):
        config = {"request_interval_seconds": 0}
        collector = KabutanCollector(config=config)
        collector._client = MagicMock()

        result = collector.collect("7203")

        assert result["collected"] is False
        assert result["data"] is None
        assert "robots.txt" in result["error"]


class TestNumberFormatParsing:
    """test_number_format_parsing: カンマ区切り、マイナス表記のパース。"""

    def test_comma_separated(self):
        assert _parse_number("1,234,567") == 1234567

    def test_negative_hyphen(self):
        assert _parse_number("-1,234") == -1234

    def test_negative_triangle(self):
        assert _parse_number("▲1,234") == -1234

    def test_float_value(self):
        assert _parse_number("12.5") == 12.5

    def test_with_unit_suffix(self):
        assert _parse_number("10.5倍") == 10.5
        assert _parse_number("2.8%") == 2.8

    def test_empty_and_dash(self):
        assert _parse_number("") is None
        assert _parse_number("---") is None
        assert _parse_number(None) is None

    def test_market_cap_oku(self):
        assert _parse_market_cap("5,000億円") == 5e11

    def test_market_cap_cho_oku(self):
        assert _parse_market_cap("3兆5,000億円") == 3.5e12

    def test_market_cap_empty(self):
        assert _parse_market_cap("---") is None
        assert _parse_market_cap(None) is None
