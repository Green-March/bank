"""Shikiho → Yahoo fallback テスト.

main.py の _shikiho_fallback() と collect() 内の fallback 連携をテストする。
"""

from unittest.mock import MagicMock, patch

import pytest

from scripts.collector_base import (
    AuthenticationError,
    CollectorError,
    RobotsBlockedError,
)
from scripts.main import collect, _shikiho_fallback


def _mock_collector_cls(collected=True, url="https://example.com", data=None, error=None):
    """モックのコレクタークラスを生成する。"""
    result = {
        "url": url,
        "collected": collected,
        "data": data if data is not None else ({"sample": "data"} if collected else None),
        "error": error,
    }
    cls = MagicMock()
    instance = MagicMock()
    instance.collect.return_value = result
    instance.__enter__ = MagicMock(return_value=instance)
    instance.__exit__ = MagicMock(return_value=False)
    cls.return_value = instance
    return cls


def _mock_shikiho_cls(error):
    """shikiho が例外を raise するモッククラス。"""
    cls = MagicMock()
    instance = MagicMock()
    instance.collect.side_effect = error
    instance.__enter__ = MagicMock(return_value=instance)
    instance.__exit__ = MagicMock(return_value=False)
    cls.return_value = instance
    return cls


class TestShikihoFailYahooFallback:
    """shikiho失敗 + yahoo未収集 → yahoo fallback テスト"""

    def test_shikiho_auth_fail_yahoo_fallback_succeeds(self):
        """shikiho AUTH_ENV_MISSING → yahoo fallback で収集成功"""
        shikiho_error = AuthenticationError(
            "SHIKIHO_EMAIL/SHIKIHO_PASSWORD 未設定",
            error_code="AUTH_ENV_MISSING",
        )
        yahoo_cls = _mock_collector_cls(
            collected=True,
            url="https://finance.yahoo.co.jp/quote/7203.T",
            data={"stock_price": {"current": 2500}},
        )
        shikiho_cls = _mock_shikiho_cls(shikiho_error)

        mock_map = {"shikiho": shikiho_cls, "yahoo": yahoo_cls}
        with patch("scripts.main.SOURCE_MAP", mock_map), \
             patch("scripts.main.YahooFinanceCollector", yahoo_cls):
            result = collect("7203", ["shikiho"])

        shikiho_src = result["sources"]["shikiho"]
        assert shikiho_src["collected"] is True
        assert shikiho_src["fallback"]["fallback_source"] == "yahoo"
        assert shikiho_src["fallback"]["fallback_reason"] == "AUTH_ENV_MISSING"
        assert shikiho_src["fallback"]["fallback_reused"] is False
        assert result["metadata"]["success_count"] == 1

    def test_shikiho_http_error_yahoo_fallback(self):
        """shikiho AUTH_HTTP_ERROR → yahoo fallback で収集成功"""
        shikiho_error = AuthenticationError(
            "認証失敗: 401",
            error_code="AUTH_HTTP_ERROR",
        )
        yahoo_cls = _mock_collector_cls(
            collected=True,
            url="https://finance.yahoo.co.jp/quote/7203.T",
            data={"stock_price": {"current": 2500}},
        )
        shikiho_cls = _mock_shikiho_cls(shikiho_error)

        mock_map = {"shikiho": shikiho_cls, "yahoo": yahoo_cls}
        with patch("scripts.main.SOURCE_MAP", mock_map), \
             patch("scripts.main.YahooFinanceCollector", yahoo_cls):
            result = collect("7203", ["shikiho"])

        shikiho_src = result["sources"]["shikiho"]
        assert shikiho_src["collected"] is True
        assert shikiho_src["fallback"]["fallback_reason"] == "AUTH_HTTP_ERROR"


class TestShikihoFailYahooReuse:
    """shikiho失敗 + yahoo収集済み → yahoo 再利用テスト"""

    def test_yahoo_data_reused(self):
        """shikiho 失敗、yahoo 先に収集済み → データ再利用"""
        shikiho_error = AuthenticationError(
            "SHIKIHO_EMAIL/SHIKIHO_PASSWORD 未設定",
            error_code="AUTH_ENV_MISSING",
        )
        yahoo_cls = _mock_collector_cls(
            collected=True,
            url="https://finance.yahoo.co.jp/quote/7203.T",
            data={"stock_price": {"current": 3000}},
        )
        shikiho_cls = _mock_shikiho_cls(shikiho_error)

        mock_map = {"yahoo": yahoo_cls, "shikiho": shikiho_cls}
        with patch("scripts.main.SOURCE_MAP", mock_map):
            # yahoo → shikiho の順で実行 (yahoo が先に収集済み)
            result = collect("7203", ["yahoo", "shikiho"])

        shikiho_src = result["sources"]["shikiho"]
        assert shikiho_src["collected"] is True
        assert shikiho_src["fallback"]["fallback_reused"] is True
        assert shikiho_src["fallback"]["fallback_source"] == "yahoo"
        assert shikiho_src["data"]["stock_price"]["current"] == 3000
        assert result["metadata"]["success_count"] == 2


class TestShikihoSuccess:
    """shikiho成功 → fallback なしテスト"""

    def test_no_fallback_on_success(self):
        """shikiho 収集成功時は fallback なし"""
        shikiho_cls = _mock_collector_cls(
            collected=True,
            url="https://shikiho.toyokeizai.net/stocks/7203",
            data={"company_overview": {"name": "テスト"}},
        )

        mock_map = {"shikiho": shikiho_cls}
        with patch("scripts.main.SOURCE_MAP", mock_map):
            result = collect("7203", ["shikiho"])

        shikiho_src = result["sources"]["shikiho"]
        assert shikiho_src["collected"] is True
        assert "fallback" not in shikiho_src
        assert result["metadata"]["success_count"] == 1


class TestShikihoFailYahooFallbackAlsoFails:
    """shikiho失敗 + yahoo fallback も失敗 → collected=false テスト"""

    def test_both_fail(self):
        """shikiho 失敗、yahoo fallback も失敗 → collected=False"""
        shikiho_error = AuthenticationError(
            "SHIKIHO_EMAIL/SHIKIHO_PASSWORD 未設定",
            error_code="AUTH_ENV_MISSING",
        )
        yahoo_cls = _mock_collector_cls(
            collected=False,
            url="https://finance.yahoo.co.jp/quote/7203.T",
            error="ページデータの抽出に失敗しました",
        )
        shikiho_cls = _mock_shikiho_cls(shikiho_error)

        mock_map = {"shikiho": shikiho_cls, "yahoo": yahoo_cls}
        with patch("scripts.main.SOURCE_MAP", mock_map), \
             patch("scripts.main.YahooFinanceCollector", yahoo_cls):
            result = collect("7203", ["shikiho"])

        shikiho_src = result["sources"]["shikiho"]
        assert shikiho_src["collected"] is False
        assert "shikiho:" in shikiho_src["error"]
        assert "yahoo fallback:" in shikiho_src["error"]
        assert result["metadata"]["success_count"] == 0

    def test_yahoo_fallback_raises_exception(self):
        """shikiho 失敗、yahoo fallback で例外 → collected=False"""
        shikiho_error = AuthenticationError(
            "認証失敗: 403",
            error_code="AUTH_HTTP_ERROR",
        )
        yahoo_cls = MagicMock()
        yahoo_instance = MagicMock()
        yahoo_instance.collect.side_effect = CollectorError("yahoo接続エラー")
        yahoo_instance.__enter__ = MagicMock(return_value=yahoo_instance)
        yahoo_instance.__exit__ = MagicMock(return_value=False)
        yahoo_cls.return_value = yahoo_instance
        shikiho_cls = _mock_shikiho_cls(shikiho_error)

        mock_map = {"shikiho": shikiho_cls}
        with patch("scripts.main.SOURCE_MAP", mock_map), \
             patch("scripts.main.YahooFinanceCollector", yahoo_cls):
            result = collect("7203", ["shikiho"])

        shikiho_src = result["sources"]["shikiho"]
        assert shikiho_src["collected"] is False
        assert "yahoo fallback:" in shikiho_src["error"]


class TestSuccessCountAccuracy:
    """success_count/source_count 正確性テスト"""

    def test_success_count_with_fallback(self):
        """yahoo + shikiho(fallback) の success_count が正しい"""
        yahoo_cls = _mock_collector_cls(
            collected=True,
            url="https://finance.yahoo.co.jp/quote/7203.T",
            data={"stock_price": {"current": 2500}},
        )
        shikiho_error = AuthenticationError(
            "未設定", error_code="AUTH_ENV_MISSING",
        )
        shikiho_cls = _mock_shikiho_cls(shikiho_error)

        mock_map = {"yahoo": yahoo_cls, "shikiho": shikiho_cls}
        with patch("scripts.main.SOURCE_MAP", mock_map):
            result = collect("7203", ["yahoo", "shikiho"])

        # yahoo: collected=True, shikiho: fallback reuse yahoo → collected=True
        assert result["metadata"]["source_count"] == 2
        assert result["metadata"]["success_count"] == 2

    def test_source_count_unchanged_with_fallback(self):
        """fallback しても source_count は元のソース数を反映"""
        shikiho_error = AuthenticationError(
            "未設定", error_code="AUTH_ENV_MISSING",
        )
        yahoo_cls = _mock_collector_cls(
            collected=True,
            url="https://finance.yahoo.co.jp/quote/7203.T",
        )
        shikiho_cls = _mock_shikiho_cls(shikiho_error)

        mock_map = {"shikiho": shikiho_cls, "yahoo": yahoo_cls}
        with patch("scripts.main.SOURCE_MAP", mock_map), \
             patch("scripts.main.YahooFinanceCollector", yahoo_cls):
            result = collect("7203", ["shikiho"])

        # shikiho のみ指定→source_count は 1
        assert result["metadata"]["source_count"] == 1


class TestShikihoFallbackUnit:
    """_shikiho_fallback 関数の単体テスト"""

    def test_fallback_with_yahoo_already_collected(self):
        """yahoo 収集済みの場合はデータ再利用"""
        error = AuthenticationError("test", error_code="AUTH_ENV_MISSING")
        source_results = {
            "yahoo": {
                "url": "https://finance.yahoo.co.jp/quote/7203.T",
                "collected": True,
                "data": {"test": "data"},
                "error": None,
            },
        }
        result = _shikiho_fallback("7203", error, source_results, None)

        assert result["collected"] is True
        assert result["fallback"]["fallback_reused"] is True
        assert result["data"]["test"] == "data"

    def test_fallback_without_yahoo(self):
        """yahoo 未収集の場合は新規 YahooFinanceCollector 実行"""
        error = AuthenticationError("test", error_code="AUTH_HTTP_ERROR")
        source_results = {}

        yahoo_cls = _mock_collector_cls(
            collected=True,
            url="https://finance.yahoo.co.jp/quote/7203.T",
            data={"yahoo": "fresh_data"},
        )
        with patch("scripts.main.YahooFinanceCollector", yahoo_cls):
            result = _shikiho_fallback("7203", error, source_results, None)

        assert result["collected"] is True
        assert result["fallback"]["fallback_reused"] is False
        assert result["fallback"]["fallback_reason"] == "AUTH_HTTP_ERROR"

    def test_fallback_session_expired_reason(self):
        """SESSION_EXPIRED の error_code が fallback_reason に記録される"""
        error = AuthenticationError("expired", error_code="SESSION_EXPIRED")
        source_results = {}

        yahoo_cls = _mock_collector_cls(collected=True, url="https://finance.yahoo.co.jp/quote/7203.T")
        with patch("scripts.main.YahooFinanceCollector", yahoo_cls):
            result = _shikiho_fallback("7203", error, source_results, None)

        assert result["fallback"]["fallback_reason"] == "SESSION_EXPIRED"


class TestNonShikihoErrorNoFallback:
    """shikiho 以外のソースの CollectorError では fallback しない"""

    def test_kabutan_error_no_fallback(self):
        """kabutan エラーでは fallback なし"""
        kabutan_cls = MagicMock()
        instance = MagicMock()
        instance.collect.side_effect = RobotsBlockedError("robots blocked")
        instance.__enter__ = MagicMock(return_value=instance)
        instance.__exit__ = MagicMock(return_value=False)
        kabutan_cls.return_value = instance

        mock_map = {"kabutan": kabutan_cls}
        with patch("scripts.main.SOURCE_MAP", mock_map):
            result = collect("7203", ["kabutan"])

        kabutan_src = result["sources"]["kabutan"]
        assert kabutan_src["collected"] is False
        assert "fallback" not in kabutan_src
