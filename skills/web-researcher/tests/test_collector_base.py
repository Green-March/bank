"""BaseCollector のテスト"""

import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from scripts.collector_base import (
    BaseCollector,
    CollectorError,
    DomainNotAllowedError,
    RobotsBlockedError,
    _sanitize_log,
)


class ConcreteCollector(BaseCollector):
    """テスト用の BaseCollector 具象実装。"""

    def collect(self, ticker: str) -> dict:
        return {"url": "https://example.com", "collected": True, "data": {}, "error": None}


class TestCheckRobots:
    def test_check_robots_allowed(self, mock_robots_allow):
        """robots.txt 許可時に True を返す。"""
        collector = ConcreteCollector()
        result = collector._check_robots("https://finance.yahoo.co.jp/quote/7203")
        assert result is True
        mock_robots_allow.can_fetch.assert_called_once()

    def test_check_robots_denied(self, mock_robots_deny):
        """robots.txt 拒否時に RobotsBlockedError を送出する。"""
        collector = ConcreteCollector()
        with pytest.raises(RobotsBlockedError, match="robots.txt"):
            collector._check_robots("https://finance.yahoo.co.jp/quote/7203")


class TestDomainValidation:
    def test_domain_validation_static_allowed(self):
        """静的許可ドメインが通過する。"""
        collector = ConcreteCollector()
        # 例外が発生しなければ OK
        collector._validate_domain("https://finance.yahoo.co.jp/quote/7203")
        collector._validate_domain("https://kabutan.jp/stock/?code=7203")
        collector._validate_domain("https://shikiho.toyokeizai.net/stocks/7203")

    def test_domain_validation_denied(self):
        """未許可ドメインで DomainNotAllowedError を送出する。"""
        collector = ConcreteCollector()
        with pytest.raises(DomainNotAllowedError, match="許可されていないドメイン"):
            collector._validate_domain("https://evil.example.com/test")


class TestRateLimit:
    def test_rate_limit(self, default_config):
        """リクエスト間隔が config 値以上であること。"""
        config = {**default_config, "request_interval_seconds": 0.1}
        collector = ConcreteCollector(config=config)

        collector._last_request_time = time.time()
        start = time.time()
        collector._wait_interval()
        elapsed = time.time() - start

        assert elapsed >= 0.05  # 少なくとも間隔の半分以上待つ


class TestBackoffRetry:
    def test_backoff_retry(self, mock_robots_allow):
        """429 → リトライ → 成功のフロー。"""
        config = {
            "request_interval_seconds": 0,
            "max_retries": 2,
            "backoff_base_seconds": 0.01,
            "backoff_max_seconds": 0.1,
        }
        collector = ConcreteCollector(config=config)

        mock_response_429 = MagicMock()
        mock_response_429.status_code = 429
        mock_response_429.raise_for_status.side_effect = httpx.HTTPStatusError(
            "429", request=MagicMock(), response=mock_response_429
        )

        mock_response_ok = MagicMock()
        mock_response_ok.status_code = 200
        mock_response_ok.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.get.side_effect = [mock_response_429, mock_response_ok]

        collector._client = mock_client
        result = collector._fetch("https://finance.yahoo.co.jp/test")
        assert result == mock_response_ok
        assert mock_client.get.call_count == 2


class TestSanitizeLog:
    def test_sanitize_log_masks_email(self):
        """email パターンがマスクされる。"""
        data = {"contact": "user@example.com is the admin"}
        result = _sanitize_log(data)
        assert "user@example.com" not in result["contact"]
        assert "***" in result["contact"]

    def test_sanitize_log_masks_password(self):
        """password パターンがマスクされる。"""
        data = {"config": "password: secret123"}
        result = _sanitize_log(data)
        assert "secret123" not in result["config"]
        assert "***" in result["config"]


class TestUserAgent:
    def test_user_agent(self):
        """User-Agent ヘッダーが正しく設定される。"""
        collector = ConcreteCollector()
        assert collector._user_agent == "BANK-WebResearcher/1.0"

        custom = ConcreteCollector(config={"user_agent": "Custom/2.0"})
        assert custom._user_agent == "Custom/2.0"


class TestEdinetOrigin:
    def test_add_and_check_edinet_origin(self):
        """EDINET 起点ドメインの追加と判定。"""
        collector = ConcreteCollector()
        assert collector._is_edinet_origin("https://www.example.co.jp/ir") is False
        collector._add_edinet_origin("www.example.co.jp")
        assert collector._is_edinet_origin("https://www.example.co.jp/ir") is True

    def test_edinet_origin_allows_fetch(self, mock_robots_allow):
        """EDINET 起点ドメインが _validate_domain を通過する。"""
        collector = ConcreteCollector()
        collector._add_edinet_origin("www.toyota.co.jp")
        # DomainNotAllowedError が発生しなければ OK
        collector._validate_domain("https://www.toyota.co.jp/ir/library/")


class TestDomainWithPort:
    def test_domain_with_port(self):
        """ポート付き URL のドメインバリデーション。"""
        collector = ConcreteCollector()
        with pytest.raises(DomainNotAllowedError):
            collector._validate_domain("https://evil.example.com:8080/test")


class TestCheckRobotsReadFailure:
    def test_robots_read_failure_allows_access(self):
        """robots.txt 読み取り失敗時はアクセスを許可する。"""
        with patch("scripts.collector_base.urllib.robotparser.RobotFileParser") as mock_cls:
            mock_rp = MagicMock()
            mock_rp.read.side_effect = Exception("ネットワークエラー")
            mock_cls.return_value = mock_rp
            collector = ConcreteCollector()
            result = collector._check_robots("https://finance.yahoo.co.jp/test")
            assert result is True


class TestFetchTimeoutAndRequestError:
    def test_fetch_timeout_exhausted(self, mock_robots_allow):
        """タイムアウトでリトライ枯渇 → CollectorError。"""
        config = {
            "request_interval_seconds": 0,
            "max_retries": 1,
            "backoff_base_seconds": 0.01,
            "backoff_max_seconds": 0.01,
        }
        collector = ConcreteCollector(config=config)
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.TimeoutException("timeout")
        collector._client = mock_client
        with pytest.raises(CollectorError, match="タイムアウト"):
            collector._fetch("https://finance.yahoo.co.jp/test")

    def test_fetch_request_error_exhausted(self, mock_robots_allow):
        """リクエストエラーでリトライ枯渇 → CollectorError。"""
        config = {
            "request_interval_seconds": 0,
            "max_retries": 1,
            "backoff_base_seconds": 0.01,
            "backoff_max_seconds": 0.01,
        }
        collector = ConcreteCollector(config=config)
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.RequestError("connection failed")
        collector._client = mock_client
        with pytest.raises(CollectorError, match="リクエストエラー"):
            collector._fetch("https://finance.yahoo.co.jp/test")

    def test_fetch_http_error_non_retryable(self, mock_robots_allow):
        """401/403 → AuthenticationError（リトライなし）。"""
        from scripts.collector_base import AuthenticationError

        config = {"request_interval_seconds": 0, "max_retries": 2}
        collector = ConcreteCollector(config=config)

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401", request=MagicMock(), response=mock_response
        )
        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        collector._client = mock_client

        with pytest.raises(AuthenticationError, match="認証/権限エラー"):
            collector._fetch("https://finance.yahoo.co.jp/test")
        assert mock_client.get.call_count == 1  # リトライなし


class TestSanitizeLogNonString:
    def test_sanitize_non_string_values(self):
        """非文字列値はそのまま保持される。"""
        data = {"count": 42, "active": True, "items": [1, 2, 3]}
        result = _sanitize_log(data)
        assert result["count"] == 42
        assert result["active"] is True
        assert result["items"] == [1, 2, 3]


class TestLoadDefaultConfigMissing:
    def test_missing_config_returns_empty(self):
        """config ファイルが存在しない場合は空辞書を返す。"""
        from scripts.collector_base import _load_default_config

        with patch("scripts.collector_base._DEFAULT_CONFIG_PATH") as mock_path:
            mock_path.exists.return_value = False
            result = _load_default_config()
            assert result == {}
