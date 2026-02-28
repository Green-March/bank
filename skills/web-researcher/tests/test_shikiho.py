"""ShikihoCollector のテスト"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import httpx
import pytest

from scripts.shikiho import ShikihoCollector, _LOGOUT_URL, _LOGIN_URL
from scripts.collector_base import (
    AuthenticationError,
    CollectorError,
    RobotsBlockedError,
    _sanitize_log,
)

_EVIDENCE_DIR = Path(__file__).resolve().parent / "evidence"
_SAMPLE_HTML = (_EVIDENCE_DIR / "shikiho_sample.html").read_text(encoding="utf-8")


def _make_collector(**config_overrides):
    """テスト用 ShikihoCollector を生成する。"""
    config = {"request_interval_seconds": 0, "max_retries": 0, **config_overrides}
    return ShikihoCollector(config=config)


def _mock_login_ok():
    resp = MagicMock()
    resp.status_code = 200
    return resp


def _mock_page_ok(html=_SAMPLE_HTML):
    resp = MagicMock()
    resp.status_code = 200
    resp.text = html
    resp.raise_for_status.return_value = None
    # url 属性 (SESSION_EXPIRED 検知で参照)
    resp.url = "https://shikiho.toyokeizai.net/stocks/7203"
    return resp


class TestCollectSuccess:
    """モック認証成功 + モックHTML → 正しいデータ抽出"""

    def test_collect_success(self, monkeypatch, mock_robots_allow):
        monkeypatch.setenv("SHIKIHO_EMAIL", "test@example.com")
        monkeypatch.setenv("SHIKIHO_PASSWORD", "secret123")

        mock_client = MagicMock()
        mock_client.post.return_value = _mock_login_ok()
        mock_client.get.return_value = _mock_page_ok()

        collector = _make_collector()
        collector._client = mock_client

        result = collector.collect("7203")

        assert result["collected"] is True
        assert result["error"] is None
        assert result["url"] == "https://shikiho.toyokeizai.net/stocks/7203"

        data = result["data"]
        assert data["company_overview"]["name"] == "トヨタ自動車"
        assert data["company_overview"]["industry"] == "輸送用機器"
        assert data["company_overview"]["feature"] is not None
        assert data["earnings_forecast"]["売上高"] == "45,000,000百万円"
        assert data["earnings_forecast"]["営業利益"] == "4,000,000百万円"
        assert data["consensus"]["レーティング"] == "やや強気"
        assert len(data["shareholders"]) == 3
        assert data["shareholders"][0]["name"] == "日本マスタートラスト信託銀行"
        assert data["indicators"]["PER"] == "10.5"
        assert data["indicators"]["PBR"] == "1.2"
        assert data["indicators"]["dividend_yield"] == "2.8%"


class TestCollectAuthFailure:
    """モック認証失敗 → AuthenticationError with error_code"""

    def test_collect_auth_failure(self, monkeypatch, mock_robots_allow):
        monkeypatch.setenv("SHIKIHO_EMAIL", "test@example.com")
        monkeypatch.setenv("SHIKIHO_PASSWORD", "wrongpass")

        mock_login_resp = MagicMock()
        mock_login_resp.status_code = 401

        mock_client = MagicMock()
        mock_client.post.return_value = mock_login_resp

        collector = _make_collector()
        collector._client = mock_client

        with pytest.raises(AuthenticationError) as exc_info:
            collector.collect("7203")

        assert exc_info.value.error_code == "AUTH_HTTP_ERROR"
        assert "認証失敗" in str(exc_info.value)
        assert "401" in str(exc_info.value)


class TestCollectEnvNotSet:
    """環境変数未設定 → AuthenticationError(AUTH_ENV_MISSING)"""

    def test_collect_env_not_set(self, monkeypatch):
        monkeypatch.delenv("SHIKIHO_EMAIL", raising=False)
        monkeypatch.delenv("SHIKIHO_PASSWORD", raising=False)

        collector = _make_collector()

        with pytest.raises(AuthenticationError) as exc_info:
            collector.collect("7203")

        assert exc_info.value.error_code == "AUTH_ENV_MISSING"
        assert "未設定" in str(exc_info.value)


class TestCollectPartialEnv:
    """片方のみ設定 → AuthenticationError(AUTH_ENV_MISSING)"""

    def test_email_only(self, monkeypatch):
        monkeypatch.setenv("SHIKIHO_EMAIL", "test@example.com")
        monkeypatch.delenv("SHIKIHO_PASSWORD", raising=False)

        collector = _make_collector()

        with pytest.raises(AuthenticationError) as exc_info:
            collector.collect("7203")

        assert exc_info.value.error_code == "AUTH_ENV_MISSING"
        assert "不完全" in str(exc_info.value)

    def test_password_only(self, monkeypatch):
        monkeypatch.delenv("SHIKIHO_EMAIL", raising=False)
        monkeypatch.setenv("SHIKIHO_PASSWORD", "secret123")

        collector = _make_collector()

        with pytest.raises(AuthenticationError) as exc_info:
            collector.collect("7203")

        assert exc_info.value.error_code == "AUTH_ENV_MISSING"
        assert "不完全" in str(exc_info.value)


class TestNoSecretLeakInOutput:
    """出力JSON に SHIKIHO_EMAIL/PASSWORD が含まれない（直接不一致検証）"""

    def test_no_secret_leak_in_output(self, monkeypatch, mock_robots_allow):
        email = "leak_test@example.com"
        password = "super_secret_pass_123"
        monkeypatch.setenv("SHIKIHO_EMAIL", email)
        monkeypatch.setenv("SHIKIHO_PASSWORD", password)

        mock_client = MagicMock()
        mock_client.post.return_value = _mock_login_ok()
        mock_client.get.return_value = _mock_page_ok()

        collector = _make_collector()
        collector._client = mock_client

        result = collector.collect("7203")
        result_json = json.dumps(result, ensure_ascii=False)

        assert email not in result_json
        assert password not in result_json


class TestNoSecretLeakInError:
    """エラーメッセージにも秘密情報が含まれない"""

    def test_no_secret_leak_in_error(self, monkeypatch, mock_robots_allow):
        email = "secret_user@example.com"
        password = "my_password_456"
        monkeypatch.setenv("SHIKIHO_EMAIL", email)
        monkeypatch.setenv("SHIKIHO_PASSWORD", password)

        mock_login_resp = MagicMock()
        mock_login_resp.status_code = 403

        mock_client = MagicMock()
        mock_client.post.return_value = mock_login_resp

        collector = _make_collector()
        collector._client = mock_client

        with pytest.raises(AuthenticationError) as exc_info:
            collector.collect("7203")

        error_str = str(exc_info.value)
        assert email not in error_str
        assert password not in error_str


class TestSanitizeLogMasksCredentials:
    """_sanitize_log がメール/パスワードをマスク"""

    def test_sanitize_log_masks_email(self):
        data = {"email": "admin@shikiho.example.com"}
        result = _sanitize_log(data)
        assert "admin@shikiho.example.com" not in result["email"]
        assert "***" in result["email"]

    def test_sanitize_log_masks_password(self):
        data = {"config": "password: hunter2"}
        result = _sanitize_log(data)
        assert "hunter2" not in result["config"]
        assert "***" in result["config"]

    def test_sanitize_log_masks_nested(self):
        data = {
            "nested": {
                "contact": "user@test.jp is admin",
            },
        }
        result = _sanitize_log(data)
        assert "user@test.jp" not in result["nested"]["contact"]

    def test_sanitize_via_collector_static_method(self):
        collector = _make_collector()
        data = {"secret": "token: abc123def"}
        result = collector.sanitize_log(data)
        assert "abc123def" not in result["secret"]


class TestLogoutCalledOnSuccess:
    """成功時にログアウトが呼ばれる"""

    def test_logout_called_after_success(self, monkeypatch, mock_robots_allow):
        monkeypatch.setenv("SHIKIHO_EMAIL", "test@example.com")
        monkeypatch.setenv("SHIKIHO_PASSWORD", "secret123")

        mock_client = MagicMock()
        mock_client.post.return_value = _mock_login_ok()
        mock_client.get.return_value = _mock_page_ok()

        collector = _make_collector()
        collector._client = mock_client

        result = collector.collect("7203")

        assert result["collected"] is True
        # post は login + logout の2回呼ばれる
        post_calls = mock_client.post.call_args_list
        assert len(post_calls) == 2
        assert post_calls[1] == call(_LOGOUT_URL)


class TestLogoutCalledOnFetchError:
    """ページ取得失敗時にもログアウトが呼ばれる"""

    def test_logout_on_fetch_error(self, monkeypatch, mock_robots_allow):
        monkeypatch.setenv("SHIKIHO_EMAIL", "test@example.com")
        monkeypatch.setenv("SHIKIHO_PASSWORD", "secret123")

        mock_client = MagicMock()
        mock_client.post.return_value = _mock_login_ok()

        # _fetch がエラーを投げる
        mock_client.get.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock(status_code=500)
        )

        collector = _make_collector()
        collector._client = mock_client

        with pytest.raises(CollectorError):
            collector.collect("7203")

        # post は login + logout の2回
        post_calls = mock_client.post.call_args_list
        assert len(post_calls) == 2
        assert post_calls[1] == call(_LOGOUT_URL)


class TestLogoutCalledOnParseError:
    """パース失敗時にもログアウトが呼ばれる"""

    def test_logout_on_parse_error(self, monkeypatch, mock_robots_allow):
        monkeypatch.setenv("SHIKIHO_EMAIL", "test@example.com")
        monkeypatch.setenv("SHIKIHO_PASSWORD", "secret123")

        # 壊れた HTML でパース例外を起こす
        broken_resp = MagicMock()
        broken_resp.status_code = 200
        broken_resp.text = "<html></html>"
        broken_resp.raise_for_status.return_value = None
        broken_resp.url = "https://shikiho.toyokeizai.net/stocks/7203"

        mock_client = MagicMock()
        mock_client.post.return_value = _mock_login_ok()
        mock_client.get.return_value = broken_resp

        collector = _make_collector()
        collector._client = mock_client

        # _parse_page を強制例外に
        collector._parse_page = MagicMock(side_effect=ValueError("bad html"))

        with pytest.raises(CollectorError):
            collector.collect("7203")

        # post は login + logout の2回
        post_calls = mock_client.post.call_args_list
        assert len(post_calls) == 2
        assert post_calls[1] == call(_LOGOUT_URL)


class TestLogoutBestEffort:
    """ログアウト失敗しても例外にならない"""

    def test_logout_failure_ignored(self, monkeypatch, mock_robots_allow):
        monkeypatch.setenv("SHIKIHO_EMAIL", "test@example.com")
        monkeypatch.setenv("SHIKIHO_PASSWORD", "secret123")

        login_resp = _mock_login_ok()
        page_resp = _mock_page_ok()

        call_count = {"n": 0}

        def post_side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return login_resp  # login OK
            raise ConnectionError("logout failed")  # logout fails

        mock_client = MagicMock()
        mock_client.post.side_effect = post_side_effect
        mock_client.get.return_value = page_resp

        collector = _make_collector()
        collector._client = mock_client

        result = collector.collect("7203")

        # ログアウト失敗しても collect は成功
        assert result["collected"] is True
        assert result["error"] is None


class TestRobotsDenied:
    """robots.txt 拒否時に RobotsBlockedError が伝播"""

    def test_robots_denied_raises(self, monkeypatch, mock_robots_deny):
        monkeypatch.setenv("SHIKIHO_EMAIL", "test@example.com")
        monkeypatch.setenv("SHIKIHO_PASSWORD", "secret123")

        mock_client = MagicMock()
        collector = _make_collector()
        collector._client = mock_client

        with pytest.raises(RobotsBlockedError) as exc_info:
            collector.collect("7203")

        assert exc_info.value.error_code == "ROBOTS_BLOCKED"
        # 認証 POST は一切呼ばれない
        mock_client.post.assert_not_called()


class TestAuthNetworkErrorRetry:
    """認証時のネットワークエラーでリトライ"""

    def test_auth_timeout_retries(self, monkeypatch, mock_robots_allow):
        monkeypatch.setenv("SHIKIHO_EMAIL", "test@example.com")
        monkeypatch.setenv("SHIKIHO_PASSWORD", "secret123")

        mock_client = MagicMock()
        # 1回目タイムアウト → 2回目成功
        mock_client.post.side_effect = [
            httpx.TimeoutException("timeout"),
            _mock_login_ok(),
            MagicMock(),  # logout
        ]
        mock_client.get.return_value = _mock_page_ok()

        collector = _make_collector(max_retries=2, backoff_base_seconds=0)
        collector._client = mock_client

        result = collector.collect("7203")

        assert result["collected"] is True
        # post: attempt1(timeout) + attempt2(login ok) + logout = 3回
        assert mock_client.post.call_count == 3

    def test_auth_network_error_exhausted(self, monkeypatch, mock_robots_allow):
        monkeypatch.setenv("SHIKIHO_EMAIL", "test@example.com")
        monkeypatch.setenv("SHIKIHO_PASSWORD", "secret123")

        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.ConnectError("connection refused")

        collector = _make_collector(max_retries=1, backoff_base_seconds=0)
        collector._client = mock_client

        with pytest.raises(AuthenticationError) as exc_info:
            collector.collect("7203")

        assert exc_info.value.error_code == "AUTH_NETWORK_ERROR"
        assert "ネットワークエラー" in str(exc_info.value)

    def test_auth_request_error_retries_then_succeeds(self, monkeypatch, mock_robots_allow):
        monkeypatch.setenv("SHIKIHO_EMAIL", "test@example.com")
        monkeypatch.setenv("SHIKIHO_PASSWORD", "secret123")

        mock_client = MagicMock()
        mock_client.post.side_effect = [
            httpx.ConnectError("refused"),
            httpx.ConnectError("refused"),
            _mock_login_ok(),
            MagicMock(),  # logout
        ]
        mock_client.get.return_value = _mock_page_ok()

        collector = _make_collector(max_retries=3, backoff_base_seconds=0)
        collector._client = mock_client

        result = collector.collect("7203")

        assert result["collected"] is True


class TestAuthStatusNotRetried:
    """認証失敗（4xx）はリトライせず即エラー"""

    def test_auth_401_no_retry(self, monkeypatch, mock_robots_allow):
        monkeypatch.setenv("SHIKIHO_EMAIL", "test@example.com")
        monkeypatch.setenv("SHIKIHO_PASSWORD", "wrong")

        mock_login_resp = MagicMock()
        mock_login_resp.status_code = 401

        mock_client = MagicMock()
        mock_client.post.return_value = mock_login_resp

        collector = _make_collector(max_retries=3)
        collector._client = mock_client

        with pytest.raises(AuthenticationError) as exc_info:
            collector.collect("7203")

        assert exc_info.value.error_code == "AUTH_HTTP_ERROR"
        assert "認証失敗" in str(exc_info.value)
        # リトライせず1回のみ (+ logout)
        assert mock_client.post.call_count == 2  # login attempt + logout


class TestSessionExpired:
    """SESSION_EXPIRED: 認証後ページ取得でログイン URL にリダイレクトされた場合"""

    def test_session_expired_detected(self, monkeypatch, mock_robots_allow):
        monkeypatch.setenv("SHIKIHO_EMAIL", "test@example.com")
        monkeypatch.setenv("SHIKIHO_PASSWORD", "secret123")

        # ページ取得時にログイン URL にリダイレクト
        redirect_resp = MagicMock()
        redirect_resp.status_code = 200
        redirect_resp.text = "<html>login page</html>"
        redirect_resp.raise_for_status.return_value = None
        redirect_resp.url = _LOGIN_URL + "?redirect=/stocks/7203"

        mock_client = MagicMock()
        mock_client.post.return_value = _mock_login_ok()
        mock_client.get.return_value = redirect_resp

        collector = _make_collector()
        collector._client = mock_client

        with pytest.raises(AuthenticationError) as exc_info:
            collector.collect("7203")

        assert exc_info.value.error_code == "SESSION_EXPIRED"
        assert "セッション期限切れ" in str(exc_info.value)

        # logout が呼ばれている
        post_calls = mock_client.post.call_args_list
        assert any(c == call(_LOGOUT_URL) for c in post_calls)


class TestErrorCodeAttributes:
    """各条件コードが正しく設定される"""

    def test_auth_env_missing_error_code(self, monkeypatch):
        monkeypatch.delenv("SHIKIHO_EMAIL", raising=False)
        monkeypatch.delenv("SHIKIHO_PASSWORD", raising=False)

        collector = _make_collector()
        with pytest.raises(AuthenticationError) as exc_info:
            collector.collect("7203")
        assert exc_info.value.error_code == "AUTH_ENV_MISSING"

    def test_auth_http_error_code(self, monkeypatch, mock_robots_allow):
        monkeypatch.setenv("SHIKIHO_EMAIL", "test@example.com")
        monkeypatch.setenv("SHIKIHO_PASSWORD", "wrong")

        mock_client = MagicMock()
        mock_login_resp = MagicMock()
        mock_login_resp.status_code = 403
        mock_client.post.return_value = mock_login_resp

        collector = _make_collector()
        collector._client = mock_client

        with pytest.raises(AuthenticationError) as exc_info:
            collector.collect("7203")
        assert exc_info.value.error_code == "AUTH_HTTP_ERROR"

    def test_auth_network_error_code(self, monkeypatch, mock_robots_allow):
        monkeypatch.setenv("SHIKIHO_EMAIL", "test@example.com")
        monkeypatch.setenv("SHIKIHO_PASSWORD", "secret123")

        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.ConnectError("refused")

        collector = _make_collector(max_retries=0)
        collector._client = mock_client

        with pytest.raises(AuthenticationError) as exc_info:
            collector.collect("7203")
        assert exc_info.value.error_code == "AUTH_NETWORK_ERROR"

    def test_robots_blocked_error_code(self, monkeypatch, mock_robots_deny):
        monkeypatch.setenv("SHIKIHO_EMAIL", "test@example.com")
        monkeypatch.setenv("SHIKIHO_PASSWORD", "secret123")

        collector = _make_collector()
        collector._client = MagicMock()

        with pytest.raises(RobotsBlockedError) as exc_info:
            collector.collect("7203")
        assert exc_info.value.error_code == "ROBOTS_BLOCKED"
