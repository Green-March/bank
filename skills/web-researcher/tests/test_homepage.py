"""HomepageCollector のテスト.

全テストで TickerResolver のモック + モック HTTP を使用（実リクエスト不使用）。
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from scripts.homepage import HomepageCollector
from scripts.collector_base import (
    CollectorError,
    RobotsBlockedError,
)

_EVIDENCE = Path(__file__).resolve().parent / "evidence"


def _load_html(filename: str) -> str:
    return (_EVIDENCE / filename).read_text(encoding="utf-8")


def _make_mock_response(html: str, status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = html
    resp.raise_for_status.return_value = None
    return resp


def _make_resolver_mock(edinet_code: str = "E02144"):
    """TickerResolver のモックを生成する。"""
    resolver = MagicMock()
    resolver.resolve.return_value = {
        "edinet_code": edinet_code,
        "company_name": "トヨタ自動車株式会社",
        "sec_code": "72030",
        "fye_month": 3,
    }
    resolver._cache_dir = _EVIDENCE  # テスト用CSV がここにある
    return resolver


class TestCollectSuccess:
    """test_collect_success: モックCSV → URL解決 → robots許可 → HTMLフェッチ → パース。"""

    def test_collect_success(self, mock_robots_allow):
        html = _load_html("homepage_sample.html")
        mock_response = _make_mock_response(html)
        resolver = _make_resolver_mock()

        config = {"request_interval_seconds": 0}
        collector = HomepageCollector(
            config=config, resolver=resolver, csv_path=_EVIDENCE / "edinet_mock.csv"
        )
        collector._client = MagicMock()
        collector._client.get.return_value = mock_response

        result = collector.collect("7203")

        assert result["collected"] is True
        assert result["error"] is None
        # http → https 昇格済み
        assert result["url"] == "https://www.toyota.co.jp/"

        data = result["data"]
        assert data is not None

        # 企業概要
        ci = data["company_info"]
        assert ci["title"] == "サンプル株式会社 | 公式サイト"
        assert "先端技術" in ci["description"]
        assert ci["company_name"] == "サンプル株式会社"

        # IR ページ検出
        assert data["ir_page"]["detected"] is True
        assert "/ir/" in data["ir_page"]["url"]

        # IR リンク
        assert len(data["ir_links"]) > 0
        types = [l["type"] for l in data["ir_links"]]
        assert "pdf" in types or "html" in types

        # ニュース
        assert len(data["news"]) == 3
        assert "第3四半期決算短信" in data["news"][0]["title"]


class TestUrlNotInEdinet:
    """test_url_not_in_edinet: EDINET CSV にHP URLなし → collected=False。"""

    def test_url_not_in_edinet(self):
        resolver = MagicMock()
        resolver.resolve.return_value = {
            "edinet_code": "E00001",
            "company_name": "テスト株式会社",
            "sec_code": "99990",
            "fye_month": 3,
        }
        resolver._cache_dir = _EVIDENCE

        config = {"request_interval_seconds": 0}
        collector = HomepageCollector(
            config=config, resolver=resolver, csv_path=_EVIDENCE / "edinet_mock.csv"
        )

        result = collector.collect("9999")

        assert result["collected"] is False
        assert result["url"] is None
        assert result["data"] is None
        assert "EDINET metadata にHP URL なし" in result["error"]


class TestRobotsDenied:
    """test_robots_denied: robots.txt 拒否 → collected=False + error。"""

    def test_robots_denied(self, mock_robots_deny):
        resolver = _make_resolver_mock()

        config = {"request_interval_seconds": 0}
        collector = HomepageCollector(
            config=config, resolver=resolver, csv_path=_EVIDENCE / "edinet_mock.csv"
        )
        collector._client = MagicMock()

        result = collector.collect("7203")

        assert result["collected"] is False
        assert result["data"] is None
        assert "robots.txt denied" in result["error"]


class TestHttpsUpgrade:
    """test_https_upgrade: http → https 自動昇格の検証。"""

    def test_https_upgrade(self, mock_robots_allow):
        html = _load_html("homepage_sample.html")
        mock_response = _make_mock_response(html)
        resolver = _make_resolver_mock()

        config = {"request_interval_seconds": 0}
        collector = HomepageCollector(
            config=config, resolver=resolver, csv_path=_EVIDENCE / "edinet_mock.csv"
        )
        collector._client = MagicMock()
        collector._client.get.return_value = mock_response

        result = collector.collect("7203")

        # EDINET CSV の URL は http://www.toyota.co.jp/ だが https に昇格
        assert result["url"].startswith("https://")
        assert result["collected"] is True


class TestHttpsUpgradeFailure:
    """test_https_upgrade_failure: https昇格後のアクセス失敗。"""

    def test_https_upgrade_failure(self, mock_robots_allow):
        resolver = _make_resolver_mock()

        config = {"request_interval_seconds": 0, "max_retries": 0}
        collector = HomepageCollector(
            config=config, resolver=resolver, csv_path=_EVIDENCE / "edinet_mock.csv"
        )
        collector._client = MagicMock()
        collector._client.get.side_effect = httpx.ConnectError("Connection refused")

        result = collector.collect("7203")

        assert result["collected"] is False
        assert result["url"].startswith("https://")
        assert "HTTPS接続失敗" in result["error"]


class TestIrPageDetection:
    """test_ir_page_detection: /ir/ リンクの検出。"""

    def test_ir_page_detection(self, mock_robots_allow):
        html = _load_html("homepage_sample.html")
        mock_response = _make_mock_response(html)
        resolver = _make_resolver_mock()

        config = {"request_interval_seconds": 0}
        collector = HomepageCollector(
            config=config, resolver=resolver, csv_path=_EVIDENCE / "edinet_mock.csv"
        )
        collector._client = MagicMock()
        collector._client.get.return_value = mock_response

        result = collector.collect("7203")
        data = result["data"]

        assert data["ir_page"]["detected"] is True
        assert "/ir/" in data["ir_page"]["url"]

        # /ir/ および /investor/ パス配下のリンクが検出されること
        ir_urls = [l["url"] for l in data["ir_links"]]
        assert any("/ir/" in u for u in ir_urls)
        assert any("/investor/" in u for u in ir_urls)


class TestIrPageNotFound:
    """test_ir_page_not_found: IR ページ未検出 → ir_links=[], detected=False。"""

    def test_ir_page_not_found(self, mock_robots_allow):
        html = """<!DOCTYPE html>
<html><head><title>シンプル会社</title></head>
<body><h1>シンプル会社</h1><p>IR情報はありません。</p></body></html>"""
        mock_response = _make_mock_response(html)
        resolver = _make_resolver_mock()

        config = {"request_interval_seconds": 0}
        collector = HomepageCollector(
            config=config, resolver=resolver, csv_path=_EVIDENCE / "edinet_mock.csv"
        )
        collector._client = MagicMock()
        collector._client.get.return_value = mock_response

        result = collector.collect("7203")
        data = result["data"]

        assert result["collected"] is True
        assert data["ir_page"]["detected"] is False
        assert data["ir_page"]["url"] is None
        assert data["ir_links"] == []


class TestNewsExtraction:
    """test_news_extraction: ニュースセクションの抽出。"""

    def test_news_extraction(self, mock_robots_allow):
        html = _load_html("homepage_sample.html")
        mock_response = _make_mock_response(html)
        resolver = _make_resolver_mock()

        config = {"request_interval_seconds": 0}
        collector = HomepageCollector(
            config=config, resolver=resolver, csv_path=_EVIDENCE / "edinet_mock.csv"
        )
        collector._client = MagicMock()
        collector._client.get.return_value = mock_response

        result = collector.collect("7203")
        news = result["data"]["news"]

        assert len(news) == 3
        assert news[0]["title"] == "2026年3月期 第3四半期決算短信を発表"
        assert news[0]["date"] == "2026.02.25"
        assert news[0]["url"].endswith(".html")
        assert news[2]["url"].endswith(".pdf")


class TestAccessedDomainsRecorded:
    """test_accessed_domains_recorded: ドメインが記録されること。"""

    def test_accessed_domains_recorded(self, mock_robots_allow):
        html = _load_html("homepage_sample.html")
        mock_response = _make_mock_response(html)
        resolver = _make_resolver_mock()

        config = {"request_interval_seconds": 0}
        collector = HomepageCollector(
            config=config, resolver=resolver, csv_path=_EVIDENCE / "edinet_mock.csv"
        )
        collector._client = MagicMock()
        collector._client.get.return_value = mock_response

        result = collector.collect("7203")

        assert result["collected"] is True
        assert "www.toyota.co.jp" in collector.metadata["accessed_domains"]


class TestResolverNotAvailable:
    """test_resolver_not_available: resolver 未設定時の graceful degradation。"""

    def test_resolver_none_explicit(self):
        """resolver=None 明示 → collected=False, エラーメッセージ。"""
        config = {"request_interval_seconds": 0}
        collector = HomepageCollector(config=config, resolver=None, csv_path=None)
        # TickerResolver auto-init をバイパスするため直接 None に設定
        collector._resolver = None

        result = collector.collect("7203")

        assert result["collected"] is False
        assert result["url"] is None
        assert "EDINET metadata にHP URL なし" in result["error"]

    def test_resolver_auto_init_import_fails(self):
        """TickerResolver import 失敗時 → collected=False。"""
        with patch("scripts.homepage.TickerResolver", None):
            config = {"request_interval_seconds": 0}
            collector = HomepageCollector(config=config)

            result = collector.collect("7203")

            assert result["collected"] is False
            assert "EDINET metadata にHP URL なし" in result["error"]

    def test_resolver_auto_init_exception(self):
        """TickerResolver 初期化で例外発生 → collected=False。"""
        mock_resolver_cls = MagicMock(side_effect=Exception("cache not found"))
        with patch("scripts.homepage.TickerResolver", mock_resolver_cls):
            config = {"request_interval_seconds": 0}
            collector = HomepageCollector(config=config)

            result = collector.collect("7203")

            assert result["collected"] is False
            assert "EDINET metadata にHP URL なし" in result["error"]


class TestEdinetCsvUrlExtraction:
    """EDINET CSV からの公式HP URL 抽出テスト。"""

    def test_csv_path_explicit(self):
        """csv_path 明示指定で正しい URL が取得できる。"""
        resolver = _make_resolver_mock()
        config = {"request_interval_seconds": 0}
        collector = HomepageCollector(
            config=config, resolver=resolver,
            csv_path=_EVIDENCE / "edinet_mock.csv",
        )
        url = collector._resolve_homepage_url("7203")
        assert url == "http://www.toyota.co.jp/"

    def test_csv_path_nonexistent(self):
        """存在しない CSV パス → None (graceful degradation)。"""
        resolver = _make_resolver_mock()
        config = {"request_interval_seconds": 0}
        collector = HomepageCollector(
            config=config, resolver=resolver,
            csv_path=Path("/nonexistent/path.csv"),
        )
        url = collector._resolve_homepage_url("7203")
        assert url is None

    def test_csv_edinet_code_not_found(self):
        """CSV 内に該当 EDINET コードがない → None。"""
        resolver = MagicMock()
        resolver.resolve.return_value = {
            "edinet_code": "E99999",
            "company_name": "存在しない会社",
        }
        config = {"request_interval_seconds": 0}
        collector = HomepageCollector(
            config=config, resolver=resolver,
            csv_path=_EVIDENCE / "edinet_mock.csv",
        )
        url = collector._resolve_homepage_url("9999")
        assert url is None

    def test_csv_hp_column_empty(self):
        """CSV の HP 列が空 → None。"""
        resolver = MagicMock()
        resolver.resolve.return_value = {
            "edinet_code": "E00001",
            "company_name": "テスト株式会社",
        }
        config = {"request_interval_seconds": 0}
        collector = HomepageCollector(
            config=config, resolver=resolver,
            csv_path=_EVIDENCE / "edinet_mock.csv",
        )
        url = collector._resolve_homepage_url("9999")
        assert url is None

    def test_csv_via_resolver_cache_dir(self):
        """csv_path 未指定 → resolver._cache_dir から EdinetcodeDlInfo.csv を参照。"""
        resolver = _make_resolver_mock()
        config = {"request_interval_seconds": 0}
        collector = HomepageCollector(config=config, resolver=resolver)
        # resolver._cache_dir = _EVIDENCE, there is EdinetcodeDlInfo.csv
        url = collector._resolve_homepage_url("7203")
        assert url == "http://www.toyota.co.jp/"

    def test_edinet_csv_cli_option_passthrough(self, mock_robots_allow):
        """main.collect の edinet_csv パラメータが HomepageCollector に渡される。"""
        from scripts.main import collect as main_collect

        html = _load_html("homepage_sample.html")
        mock_response = _make_mock_response(html)
        resolver = _make_resolver_mock()

        with patch("scripts.main._create_resolver", return_value=resolver):
            with patch("scripts.collector_base.httpx.Client") as mock_client_cls:
                mock_client = MagicMock()
                mock_client.get.return_value = mock_response
                mock_client_cls.return_value = mock_client

                result = main_collect(
                    "7203",
                    ["homepage"],
                    config={"request_interval_seconds": 0},
                    edinet_csv=str(_EVIDENCE / "edinet_mock.csv"),
                )

        hp = result["sources"]["homepage"]
        assert hp["collected"] is True
        assert hp["url"] == "https://www.toyota.co.jp/"


class TestMainCollectIntegration:
    """main.collect 経由で homepage → collected=True の最小統合テスト。"""

    def test_homepage_collected_true_via_main(self, mock_robots_allow):
        """main.collect で resolver 注入 + mock HTTP → collected=True。

        resolver mock の _cache_dir は evidence/ を指し、
        EdinetcodeDlInfo.csv (edinet_mock.csv と同内容) を参照する。
        """
        from scripts.main import collect as main_collect

        html = _load_html("homepage_sample.html")
        mock_response = _make_mock_response(html)
        # _cache_dir は evidence/ (EdinetcodeDlInfo.csv が存在する)
        resolver = _make_resolver_mock()

        with patch("scripts.main._create_resolver", return_value=resolver):
            with patch("scripts.collector_base.httpx.Client") as mock_client_cls:
                mock_client = MagicMock()
                mock_client.get.return_value = mock_response
                # BaseCollector.__enter__ は httpx.Client() を直接代入する (context managerではない)
                mock_client_cls.return_value = mock_client

                result = main_collect(
                    "7203",
                    ["homepage"],
                    config={"request_interval_seconds": 0},
                )

        hp = result["sources"]["homepage"]
        assert hp["collected"] is True
        assert hp["error"] is None
        assert hp["url"].startswith("https://")
        assert hp["data"]["company_info"]["company_name"] == "サンプル株式会社"
