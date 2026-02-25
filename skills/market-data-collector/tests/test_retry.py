"""リトライ機能のユニットテスト

_is_retryable, _request_with_retry, および両クライアントのリトライ統合テスト。
"""

from unittest.mock import MagicMock, call, patch

import httpx
import pytest

from collector import (
    DailyQuotesClient,
    DailyQuotesError,
    ListedInfoClient,
    ListedInfoError,
    _is_retryable,
    _request_with_retry,
)


def _mock_auth() -> MagicMock:
    auth = MagicMock()
    auth.get_id_token.return_value = "test-token"
    return auth


def _make_response(
    status_code: int = 200, json_data: dict | None = None
) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(spec=httpx.Request),
            response=resp,
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


# ============================================================
# _is_retryable
# ============================================================


class TestIsRetryable:
    """リトライ可能判定のテスト"""

    def test_timeout_is_retryable(self):
        exc = httpx.ReadTimeout("timeout")
        assert _is_retryable(exc) is True

    def test_429_is_retryable(self):
        resp = _make_response(status_code=429)
        exc = httpx.HTTPStatusError(
            message="429",
            request=MagicMock(spec=httpx.Request),
            response=resp,
        )
        assert _is_retryable(exc) is True

    def test_500_is_not_retryable(self):
        resp = _make_response(status_code=500)
        exc = httpx.HTTPStatusError(
            message="500",
            request=MagicMock(spec=httpx.Request),
            response=resp,
        )
        assert _is_retryable(exc) is False

    def test_404_is_not_retryable(self):
        resp = _make_response(status_code=404)
        exc = httpx.HTTPStatusError(
            message="404",
            request=MagicMock(spec=httpx.Request),
            response=resp,
        )
        assert _is_retryable(exc) is False

    def test_network_error_is_retryable(self):
        exc = httpx.ConnectError("connection refused")
        assert _is_retryable(exc) is True

    def test_non_httpx_exception_not_retryable(self):
        exc = ValueError("unrelated")
        assert _is_retryable(exc) is False


# ============================================================
# _request_with_retry
# ============================================================


class TestRequestWithRetrySuccess:
    """リトライ後に成功するケース"""

    @patch("collector.time.sleep")
    def test_retry_after_429_then_success(self, mock_sleep):
        resp_429 = _make_response(status_code=429)
        resp_ok = _make_response(
            json_data={"daily_quotes": [{"Close": 100}]}
        )

        mock_client = MagicMock()
        mock_client.get.side_effect = [resp_429, resp_ok]

        result = _request_with_retry(
            mock_client,
            "https://example.com/api",
            headers={"Authorization": "Bearer token"},
            max_retries=3,
            base_delay=1.0,
        )

        assert result == resp_ok
        assert mock_client.get.call_count == 2
        assert mock_sleep.call_count == 1

    @patch("collector.time.sleep")
    def test_retry_after_timeout_then_success(self, mock_sleep):
        resp_ok = _make_response(json_data={"info": [{"Code": "7203"}]})

        mock_client = MagicMock()
        mock_client.get.side_effect = [
            httpx.ReadTimeout("timeout"),
            resp_ok,
        ]

        result = _request_with_retry(
            mock_client,
            "https://example.com/api",
            max_retries=3,
            base_delay=1.0,
        )

        assert result == resp_ok
        assert mock_client.get.call_count == 2
        assert mock_sleep.call_count == 1

    @patch("collector.time.sleep")
    def test_retry_after_network_error_then_success(self, mock_sleep):
        resp_ok = _make_response(json_data={"data": "ok"})

        mock_client = MagicMock()
        mock_client.get.side_effect = [
            httpx.ConnectError("connection refused"),
            resp_ok,
        ]

        result = _request_with_retry(
            mock_client,
            "https://example.com/api",
            max_retries=3,
            base_delay=1.0,
        )

        assert result == resp_ok
        assert mock_client.get.call_count == 2


class TestRequestWithRetryExhausted:
    """最大リトライ回数超過のケース"""

    @patch("collector.time.sleep")
    def test_429_exhausts_retries(self, mock_sleep):
        resp_429 = _make_response(status_code=429)

        mock_client = MagicMock()
        mock_client.get.return_value = resp_429

        with pytest.raises(httpx.HTTPStatusError):
            _request_with_retry(
                mock_client,
                "https://example.com/api",
                max_retries=2,
                base_delay=1.0,
            )

        # 1 initial + 2 retries = 3 attempts
        assert mock_client.get.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("collector.time.sleep")
    def test_timeout_exhausts_retries(self, mock_sleep):
        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.ReadTimeout("timeout")

        with pytest.raises(httpx.TimeoutException):
            _request_with_retry(
                mock_client,
                "https://example.com/api",
                max_retries=1,
                base_delay=1.0,
            )

        assert mock_client.get.call_count == 2
        assert mock_sleep.call_count == 1


class TestRequestWithRetryNoRetry:
    """リトライ対象外のエラーは即座に送出するケース"""

    @patch("collector.time.sleep")
    def test_404_not_retried(self, mock_sleep):
        resp_404 = _make_response(status_code=404)

        mock_client = MagicMock()
        mock_client.get.return_value = resp_404

        with pytest.raises(httpx.HTTPStatusError):
            _request_with_retry(
                mock_client,
                "https://example.com/api",
                max_retries=3,
                base_delay=1.0,
            )

        assert mock_client.get.call_count == 1
        mock_sleep.assert_not_called()

    @patch("collector.time.sleep")
    def test_500_not_retried(self, mock_sleep):
        resp_500 = _make_response(status_code=500)

        mock_client = MagicMock()
        mock_client.get.return_value = resp_500

        with pytest.raises(httpx.HTTPStatusError):
            _request_with_retry(
                mock_client,
                "https://example.com/api",
                max_retries=3,
                base_delay=1.0,
            )

        assert mock_client.get.call_count == 1
        mock_sleep.assert_not_called()


class TestRequestWithRetryZeroRetries:
    """max_retries=0 の場合はリトライしないケース"""

    @patch("collector.time.sleep")
    def test_no_retry_on_429(self, mock_sleep):
        resp_429 = _make_response(status_code=429)

        mock_client = MagicMock()
        mock_client.get.return_value = resp_429

        with pytest.raises(httpx.HTTPStatusError):
            _request_with_retry(
                mock_client,
                "https://example.com/api",
                max_retries=0,
                base_delay=1.0,
            )

        assert mock_client.get.call_count == 1
        mock_sleep.assert_not_called()


class TestRequestWithRetryBackoff:
    """Exponential backoff と jitter の挙動テスト"""

    @patch("collector.random.uniform", return_value=0.25)
    @patch("collector.time.sleep")
    def test_exponential_backoff_delays(self, mock_sleep, mock_uniform):
        resp_429 = _make_response(status_code=429)

        mock_client = MagicMock()
        mock_client.get.return_value = resp_429

        with pytest.raises(httpx.HTTPStatusError):
            _request_with_retry(
                mock_client,
                "https://example.com/api",
                max_retries=3,
                base_delay=1.0,
                max_delay=30.0,
            )

        # jitter fixed at 0.25 (uniform(0, 0.5))
        # attempt 0: delay = 1.0 * 2^0 + 0.25 = 1.25
        # attempt 1: delay = 1.0 * 2^1 + 0.25 = 2.25
        # attempt 2: delay = 1.0 * 2^2 + 0.25 = 4.25
        assert mock_sleep.call_count == 3
        assert mock_sleep.call_args_list == [
            call(1.25),
            call(2.25),
            call(4.25),
        ]

    @patch("collector.random.uniform", return_value=0.0)
    @patch("collector.time.sleep")
    def test_max_delay_cap(self, mock_sleep, mock_uniform):
        resp_429 = _make_response(status_code=429)

        mock_client = MagicMock()
        mock_client.get.return_value = resp_429

        with pytest.raises(httpx.HTTPStatusError):
            _request_with_retry(
                mock_client,
                "https://example.com/api",
                max_retries=3,
                base_delay=10.0,
                max_delay=15.0,
            )

        # jitter fixed at 0.0
        # attempt 0: min(10*2^0, 15) + 0 = 10.0
        # attempt 1: min(10*2^1, 15) + 0 = 15.0  (capped)
        # attempt 2: min(10*2^2, 15) + 0 = 15.0  (capped)
        assert mock_sleep.call_args_list == [
            call(10.0),
            call(15.0),
            call(15.0),
        ]

    @patch("collector.time.sleep")
    def test_jitter_within_range(self, mock_sleep):
        """jitter が [0, base_delay * 0.5] の範囲内であることを確認"""
        resp_429 = _make_response(status_code=429)
        resp_ok = _make_response(json_data={"data": "ok"})

        mock_client = MagicMock()
        mock_client.get.side_effect = [resp_429, resp_ok]

        base_delay = 2.0
        _request_with_retry(
            mock_client,
            "https://example.com/api",
            max_retries=1,
            base_delay=base_delay,
        )

        actual_delay = mock_sleep.call_args[0][0]
        # delay = base_delay * 2^0 + jitter = 2.0 + [0, 1.0]
        assert 2.0 <= actual_delay <= 3.0


# ============================================================
# DailyQuotesClient リトライ統合テスト
# ============================================================


class TestDailyQuotesClientRetry:
    """DailyQuotesClient のリトライ統合テスト"""

    @patch("collector.time.sleep")
    @patch("collector.httpx.Client")
    def test_retry_429_then_success(self, mock_client_cls, mock_sleep):
        resp_429 = _make_response(status_code=429)
        records = [{"Date": "2025-01-01", "Close": 2500}]
        resp_ok = _make_response(json_data={"daily_quotes": records})

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = [resp_429, resp_ok]
        mock_client_cls.return_value = mock_client

        client = DailyQuotesClient(_mock_auth(), max_retries=3, base_delay=1.0)
        result = client.fetch("7203", "2025-01-01", "2025-01-31")

        assert result == records
        assert mock_client.get.call_count == 2
        assert mock_sleep.call_count == 1

    @patch("collector.time.sleep")
    @patch("collector.httpx.Client")
    def test_retry_exhausted_raises_domain_error(
        self, mock_client_cls, mock_sleep
    ):
        resp_429 = _make_response(status_code=429)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = resp_429
        mock_client_cls.return_value = mock_client

        client = DailyQuotesClient(_mock_auth(), max_retries=2, base_delay=1.0)
        with pytest.raises(DailyQuotesError, match="レート制限"):
            client.fetch("7203", "2025-01-01", "2025-01-31")

        assert mock_client.get.call_count == 3

    @patch("collector.time.sleep")
    @patch("collector.httpx.Client")
    def test_custom_retry_params(self, mock_client_cls, mock_sleep):
        resp_429 = _make_response(status_code=429)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = resp_429
        mock_client_cls.return_value = mock_client

        client = DailyQuotesClient(
            _mock_auth(), max_retries=1, base_delay=0.5, max_delay=5.0
        )
        with pytest.raises(DailyQuotesError):
            client.fetch("7203", "2025-01-01", "2025-01-31")

        # 1 initial + 1 retry = 2 attempts
        assert mock_client.get.call_count == 2
        assert mock_sleep.call_count == 1


# ============================================================
# ListedInfoClient リトライ統合テスト
# ============================================================


class TestListedInfoClientRetry:
    """ListedInfoClient のリトライ統合テスト"""

    @patch("collector.time.sleep")
    @patch("collector.httpx.Client")
    def test_retry_timeout_then_success(self, mock_client_cls, mock_sleep):
        info = [{"Code": "7203", "CompanyName": "トヨタ自動車"}]
        resp_ok = _make_response(json_data={"info": info})

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = [
            httpx.ReadTimeout("timeout"),
            resp_ok,
        ]
        mock_client_cls.return_value = mock_client

        client = ListedInfoClient(_mock_auth(), max_retries=3, base_delay=1.0)
        result = client.fetch("7203")

        assert result == info
        assert mock_client.get.call_count == 2
        assert mock_sleep.call_count == 1

    @patch("collector.time.sleep")
    @patch("collector.httpx.Client")
    def test_retry_network_error_then_success(
        self, mock_client_cls, mock_sleep
    ):
        info = [{"Code": "6758", "CompanyName": "ソニーグループ"}]
        resp_ok = _make_response(json_data={"info": info})

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = [
            httpx.ConnectError("connection refused"),
            resp_ok,
        ]
        mock_client_cls.return_value = mock_client

        client = ListedInfoClient(_mock_auth(), max_retries=2, base_delay=1.0)
        result = client.fetch("6758")

        assert result == info
        assert mock_client.get.call_count == 2

    @patch("collector.time.sleep")
    @patch("collector.httpx.Client")
    def test_retry_exhausted_raises_domain_error(
        self, mock_client_cls, mock_sleep
    ):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ReadTimeout("timeout")
        mock_client_cls.return_value = mock_client

        client = ListedInfoClient(_mock_auth(), max_retries=2, base_delay=1.0)
        with pytest.raises(ListedInfoError, match="タイムアウト"):
            client.fetch("7203")

        assert mock_client.get.call_count == 3
