"""DailyQuotesClient / ListedInfoClient のユニットテスト"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from collector import (
    DailyQuotesClient,
    DailyQuotesError,
    ListedInfoClient,
    ListedInfoError,
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
# DailyQuotesClient
# ============================================================


class TestDailyQuotesClientNormal:
    """正常取得テスト（単一ページレスポンス）"""

    @patch("collector.httpx.Client")
    def test_single_page(self, mock_client_cls):
        records = [{"Date": "2025-01-01", "Close": 2500}]
        resp = _make_response(json_data={"daily_quotes": records})

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = resp
        mock_client_cls.return_value = mock_client

        client = DailyQuotesClient(_mock_auth())
        result = client.fetch("7203", "2025-01-01", "2025-01-31")

        assert result == records
        mock_client.get.assert_called_once()


class TestDailyQuotesClientPagination:
    """ページネーション複数ページテスト"""

    @patch("collector.httpx.Client")
    def test_multiple_pages(self, mock_client_cls):
        page1 = [{"Date": "2025-01-01", "Close": 2500}]
        page2 = [{"Date": "2025-01-02", "Close": 2600}]

        resp1 = _make_response(
            json_data={"daily_quotes": page1, "pagination_key": "abc123"}
        )
        resp2 = _make_response(json_data={"daily_quotes": page2})

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = [resp1, resp2]
        mock_client_cls.return_value = mock_client

        client = DailyQuotesClient(_mock_auth())
        result = client.fetch("7203", "2025-01-01", "2025-01-31")

        assert result == page1 + page2
        assert mock_client.get.call_count == 2


class TestDailyQuotesClientErrors:
    """API エラーハンドリングテスト"""

    @pytest.mark.parametrize("status_code", [400, 401, 403, 500])
    @patch("collector.httpx.Client")
    def test_http_errors(self, mock_client_cls, status_code):
        resp = _make_response(status_code=status_code)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = resp
        mock_client_cls.return_value = mock_client

        client = DailyQuotesClient(_mock_auth())
        with pytest.raises(DailyQuotesError):
            client.fetch("7203", "2025-01-01", "2025-01-31")

    @patch("collector.httpx.Client")
    def test_rate_limit_429(self, mock_client_cls):
        resp = _make_response(status_code=429)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = resp
        mock_client_cls.return_value = mock_client

        client = DailyQuotesClient(_mock_auth())
        with pytest.raises(DailyQuotesError, match="レート制限"):
            client.fetch("7203", "2025-01-01", "2025-01-31")

    @patch("collector.httpx.Client")
    def test_timeout(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("timeout")
        mock_client_cls.return_value = mock_client

        client = DailyQuotesClient(_mock_auth())
        with pytest.raises(DailyQuotesError, match="タイムアウト"):
            client.fetch("7203", "2025-01-01", "2025-01-31")

    @patch("collector.httpx.Client")
    def test_empty_response(self, mock_client_cls):
        resp = _make_response(json_data={"daily_quotes": []})

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = resp
        mock_client_cls.return_value = mock_client

        client = DailyQuotesClient(_mock_auth())
        with pytest.raises(DailyQuotesError, match="銘柄が見つかりません"):
            client.fetch("9999", "2025-01-01", "2025-01-31")


# ============================================================
# ListedInfoClient
# ============================================================


class TestListedInfoClientNormal:
    """正常取得テスト"""

    @patch("collector.httpx.Client")
    def test_fetch_success(self, mock_client_cls):
        info = [{"Code": "7203", "CompanyName": "トヨタ自動車"}]
        resp = _make_response(json_data={"info": info})

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = resp
        mock_client_cls.return_value = mock_client

        client = ListedInfoClient(_mock_auth())
        result = client.fetch("7203")

        assert result == info
        mock_client.get.assert_called_once()


class TestListedInfoClientEmpty:
    """銘柄未存在テスト（空リスト → ListedInfoError）"""

    @patch("collector.httpx.Client")
    def test_empty_info(self, mock_client_cls):
        resp = _make_response(json_data={"info": []})

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = resp
        mock_client_cls.return_value = mock_client

        client = ListedInfoClient(_mock_auth())
        with pytest.raises(ListedInfoError, match="銘柄が見つかりません"):
            client.fetch("0000")


class TestListedInfoClientErrors:
    """API エラーハンドリングテスト"""

    @pytest.mark.parametrize("status_code", [400, 401, 403, 429, 500])
    @patch("collector.httpx.Client")
    def test_http_errors(self, mock_client_cls, status_code):
        resp = _make_response(status_code=status_code)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = resp
        mock_client_cls.return_value = mock_client

        client = ListedInfoClient(_mock_auth())
        with pytest.raises(ListedInfoError):
            client.fetch("7203")

    @patch("collector.httpx.Client")
    def test_timeout(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("timeout")
        mock_client_cls.return_value = mock_client

        client = ListedInfoClient(_mock_auth())
        with pytest.raises(ListedInfoError, match="タイムアウト"):
            client.fetch("7203")
