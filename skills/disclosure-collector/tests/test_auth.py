"""J-Quants認証モジュールのユニットテスト

httpxモック使用。実APIは呼ばない。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from auth import JQuantsAuth, JQuantsAuthError, TokenCache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, json_data: dict | None = None, text: str = ""):
    """テスト用のhttpxレスポンスモックを生成"""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.return_value = {}
    if status_code >= 400:
        request = httpx.Request("POST", "https://api.jquants.com/test")
        error = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=request,
            response=resp,
        )
        resp.raise_for_status.side_effect = error
    else:
        resp.raise_for_status = MagicMock()
    return resp


def _mock_client(*responses):
    """httpx.Client コンテキストマネージャのモック。post()が順番にレスポンスを返す。"""
    mock = MagicMock()
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    mock.post = MagicMock(side_effect=list(responses))
    return mock


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


def test_constructor_with_explicit_token(monkeypatch):
    """明示的なトークン指定が環境変数より優先される"""
    monkeypatch.setenv("JQUANTS_REFRESH_TOKEN", "env-token")
    auth = JQuantsAuth(refresh_token="explicit-token")
    assert auth._refresh_token == "explicit-token"


def test_constructor_from_env(monkeypatch):
    """環境変数からトークンを取得"""
    monkeypatch.setenv("JQUANTS_REFRESH_TOKEN", "env-token")
    auth = JQuantsAuth()
    assert auth._refresh_token == "env-token"


def test_constructor_missing_token_raises(monkeypatch):
    """トークン未設定でエラー"""
    monkeypatch.delenv("JQUANTS_REFRESH_TOKEN", raising=False)
    with patch("auth.load_dotenv"):  # 実.envからの再読込を防止
        with pytest.raises(JQuantsAuthError, match="リフレッシュトークンが見つかりません"):
            JQuantsAuth()


# ---------------------------------------------------------------------------
# Cache behavior
# ---------------------------------------------------------------------------


def test_get_id_token_returns_cached(monkeypatch):
    """有効なキャッシュがあればAPIを呼ばない"""
    monkeypatch.setenv("JQUANTS_REFRESH_TOKEN", "test-token")
    auth = JQuantsAuth()
    auth._cache = TokenCache(
        id_token="cached-token",
        expires_at=time.time() + 3600,
    )
    assert auth.get_id_token() == "cached-token"


def test_get_id_token_fetches_when_expired(monkeypatch):
    """キャッシュ期限切れでAPIを呼ぶ"""
    monkeypatch.setenv("JQUANTS_REFRESH_TOKEN", "test-token")
    auth = JQuantsAuth()
    auth._cache = TokenCache(
        id_token="old-token",
        expires_at=time.time() - 100,
    )

    mock = _mock_client(
        _mock_response(200, {"idToken": "new-token", "expiresIn": 3600})
    )
    with patch("httpx.Client", return_value=mock):
        token = auth.get_id_token()
    assert token == "new-token"


# ---------------------------------------------------------------------------
# Normal fetch
# ---------------------------------------------------------------------------


def test_fetch_id_token_success(monkeypatch):
    """正常なIDトークン取得"""
    monkeypatch.setenv("JQUANTS_REFRESH_TOKEN", "test-refresh")
    mock = _mock_client(
        _mock_response(200, {"idToken": "test-id-token", "expiresIn": 86400})
    )

    with patch("httpx.Client", return_value=mock):
        auth = JQuantsAuth()
        token = auth.get_id_token()

    assert token == "test-id-token"
    assert auth._cache is not None
    assert auth._cache.id_token == "test-id-token"


def test_fetch_id_token_missing_id_token_in_response(monkeypatch):
    """レスポンスにidTokenがない場合エラー"""
    monkeypatch.setenv("JQUANTS_REFRESH_TOKEN", "test-refresh")
    mock = _mock_client(
        _mock_response(200, {"something": "else"})
    )

    with patch("httpx.Client", return_value=mock):
        auth = JQuantsAuth()
        with pytest.raises(JQuantsAuthError, match="idTokenが含まれていません"):
            auth.get_id_token()


def test_fetch_id_token_network_error(monkeypatch):
    """ネットワークエラー時"""
    monkeypatch.setenv("JQUANTS_REFRESH_TOKEN", "test-refresh")
    mock = MagicMock()
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    mock.post.side_effect = httpx.RequestError(
        "connection failed", request=httpx.Request("POST", "https://example.com")
    )

    with patch("httpx.Client", return_value=mock):
        auth = JQuantsAuth()
        with pytest.raises(JQuantsAuthError, match="リクエスト失敗"):
            auth.get_id_token()


# ---------------------------------------------------------------------------
# Retry on 400/401 (refresh token auto-renewal)
# ---------------------------------------------------------------------------


def test_fetch_id_token_retries_on_400(monkeypatch, tmp_path):
    """HTTP 400でリフレッシュトークンを自動更新しリトライする"""
    monkeypatch.setenv("JQUANTS_REFRESH_TOKEN", "old-refresh")
    monkeypatch.setenv("JQUANTS_EMAIL", "test@example.com")
    monkeypatch.setenv("JQUANTS_PASSWORD", "test-pass")

    env_file = tmp_path / ".env"
    env_file.write_text("JQUANTS_REFRESH_TOKEN=old-refresh\n")

    # Responses in order:
    # 1. auth_refresh → 400 (token expired)
    # 2. auth_user → 200 (new refresh token)
    # 3. auth_refresh → 200 (success with new token)
    mock = _mock_client(
        _mock_response(400, text="token expired"),
        _mock_response(200, {"refreshToken": "new-refresh"}),
        _mock_response(200, {"idToken": "new-id-token", "expiresIn": 3600}),
    )

    with patch("httpx.Client", return_value=mock):
        with patch("auth.find_dotenv", return_value=str(env_file)):
            auth = JQuantsAuth(refresh_token="old-refresh")
            token = auth.get_id_token()

    assert token == "new-id-token"
    assert auth._refresh_token == "new-refresh"
    assert "JQUANTS_REFRESH_TOKEN=new-refresh" in env_file.read_text()


def test_fetch_id_token_retries_on_401(monkeypatch, tmp_path):
    """HTTP 401でリフレッシュトークンを自動更新しリトライする"""
    monkeypatch.setenv("JQUANTS_REFRESH_TOKEN", "old-refresh")
    monkeypatch.setenv("JQUANTS_EMAIL", "test@example.com")
    monkeypatch.setenv("JQUANTS_PASSWORD", "test-pass")

    env_file = tmp_path / ".env"
    env_file.write_text("JQUANTS_REFRESH_TOKEN=old-refresh\n")

    mock = _mock_client(
        _mock_response(401, text="unauthorized"),
        _mock_response(200, {"refreshToken": "new-refresh"}),
        _mock_response(200, {"idToken": "new-id-token", "expiresIn": 3600}),
    )

    with patch("httpx.Client", return_value=mock):
        with patch("auth.find_dotenv", return_value=str(env_file)):
            auth = JQuantsAuth(refresh_token="old-refresh")
            token = auth.get_id_token()

    assert token == "new-id-token"


def test_fetch_id_token_no_infinite_loop(monkeypatch, tmp_path):
    """リトライ後も400ならエラーを投げる（無限ループ防止）"""
    monkeypatch.setenv("JQUANTS_REFRESH_TOKEN", "old-refresh")
    monkeypatch.setenv("JQUANTS_EMAIL", "test@example.com")
    monkeypatch.setenv("JQUANTS_PASSWORD", "test-pass")

    env_file = tmp_path / ".env"
    env_file.write_text("JQUANTS_REFRESH_TOKEN=old-refresh\n")

    mock = _mock_client(
        _mock_response(400, text="token expired"),
        _mock_response(200, {"refreshToken": "new-refresh"}),
        _mock_response(400, text="still expired"),  # 2nd attempt also fails
    )

    with patch("httpx.Client", return_value=mock):
        with patch("auth.find_dotenv", return_value=str(env_file)):
            auth = JQuantsAuth(refresh_token="old-refresh")
            with pytest.raises(JQuantsAuthError, match="認証APIエラー"):
                auth.get_id_token()

    # Verify post was called exactly 3 times (no more retries)
    assert mock.post.call_count == 3


def test_fetch_id_token_500_no_retry(monkeypatch):
    """HTTP 500ではリトライしない"""
    monkeypatch.setenv("JQUANTS_REFRESH_TOKEN", "test-refresh")
    mock = _mock_client(
        _mock_response(500, text="server error"),
    )

    with patch("httpx.Client", return_value=mock):
        auth = JQuantsAuth()
        with pytest.raises(JQuantsAuthError, match="認証APIエラー.*500"):
            auth.get_id_token()

    assert mock.post.call_count == 1


# ---------------------------------------------------------------------------
# Missing credentials
# ---------------------------------------------------------------------------


def test_refresh_missing_credentials(monkeypatch):
    """email/passwordが未設定でエラー"""
    monkeypatch.setenv("JQUANTS_REFRESH_TOKEN", "test-token")
    monkeypatch.delenv("JQUANTS_EMAIL", raising=False)
    monkeypatch.delenv("JQUANTS_PASSWORD", raising=False)

    mock = _mock_client(
        _mock_response(400, text="token expired"),
    )

    with patch("httpx.Client", return_value=mock):
        with patch("auth.load_dotenv"):  # 実.envからの再読込を防止
            auth = JQuantsAuth(refresh_token="test-token")
            with pytest.raises(JQuantsAuthError, match="JQUANTS_EMAIL.*JQUANTS_PASSWORD"):
                auth.get_id_token()


def test_refresh_missing_email_only(monkeypatch):
    """emailのみ未設定でもエラー"""
    monkeypatch.setenv("JQUANTS_REFRESH_TOKEN", "test-token")
    monkeypatch.delenv("JQUANTS_EMAIL", raising=False)
    monkeypatch.setenv("JQUANTS_PASSWORD", "pass")

    mock = _mock_client(
        _mock_response(400, text="token expired"),
    )

    with patch("httpx.Client", return_value=mock):
        with patch("auth.load_dotenv"):  # 実.envからの再読込を防止
            auth = JQuantsAuth(refresh_token="test-token")
            with pytest.raises(JQuantsAuthError, match="JQUANTS_EMAIL.*JQUANTS_PASSWORD"):
                auth.get_id_token()


# ---------------------------------------------------------------------------
# .env persistence
# ---------------------------------------------------------------------------


def test_persist_refresh_token_updates_existing(monkeypatch, tmp_path):
    """既存の.envファイルのトークンを更新"""
    monkeypatch.setenv("JQUANTS_REFRESH_TOKEN", "test-token")

    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATA_PATH=./data\n"
        "JQUANTS_REFRESH_TOKEN=old-token\n"
        "EDINET_API_KEY=test-key\n"
    )

    with patch("auth.find_dotenv", return_value=str(env_file)):
        auth = JQuantsAuth(refresh_token="test-token")
        auth._persist_refresh_token("new-token")

    content = env_file.read_text()
    assert "JQUANTS_REFRESH_TOKEN=new-token" in content
    assert "DATA_PATH=./data" in content
    assert "EDINET_API_KEY=test-key" in content
    assert "old-token" not in content


def test_persist_refresh_token_appends_if_missing(monkeypatch, tmp_path):
    """トークンキーが.envにない場合は追記"""
    monkeypatch.setenv("JQUANTS_REFRESH_TOKEN", "test-token")

    env_file = tmp_path / ".env"
    env_file.write_text("DATA_PATH=./data\n")

    with patch("auth.find_dotenv", return_value=str(env_file)):
        auth = JQuantsAuth(refresh_token="test-token")
        auth._persist_refresh_token("new-token")

    content = env_file.read_text()
    assert "JQUANTS_REFRESH_TOKEN=new-token" in content
    assert "DATA_PATH=./data" in content


def test_persist_refresh_token_no_env_file(monkeypatch):
    """.envファイルが見つからない場合はスキップ（エラーにしない）"""
    monkeypatch.setenv("JQUANTS_REFRESH_TOKEN", "test-token")

    with patch("auth.find_dotenv", return_value=""):
        auth = JQuantsAuth(refresh_token="test-token")
        # Should not raise
        auth._persist_refresh_token("new-token")


# ---------------------------------------------------------------------------
# _refresh_refresh_token direct tests
# ---------------------------------------------------------------------------


def test_refresh_refresh_token_api_error(monkeypatch, tmp_path):
    """auth_user APIがエラーを返した場合"""
    monkeypatch.setenv("JQUANTS_REFRESH_TOKEN", "test-token")
    monkeypatch.setenv("JQUANTS_EMAIL", "test@example.com")
    monkeypatch.setenv("JQUANTS_PASSWORD", "test-pass")

    mock = _mock_client(
        _mock_response(403, text="forbidden"),
    )

    with patch("httpx.Client", return_value=mock):
        auth = JQuantsAuth(refresh_token="test-token")
        with pytest.raises(JQuantsAuthError, match="リフレッシュトークン更新APIエラー"):
            auth._refresh_refresh_token()


def test_refresh_refresh_token_missing_token_in_response(monkeypatch):
    """auth_userレスポンスにrefreshTokenがない場合"""
    monkeypatch.setenv("JQUANTS_REFRESH_TOKEN", "test-token")
    monkeypatch.setenv("JQUANTS_EMAIL", "test@example.com")
    monkeypatch.setenv("JQUANTS_PASSWORD", "test-pass")

    mock = _mock_client(
        _mock_response(200, {"something": "else"}),
    )

    with patch("httpx.Client", return_value=mock):
        auth = JQuantsAuth(refresh_token="test-token")
        with pytest.raises(JQuantsAuthError, match="refreshTokenが含まれていません"):
            auth._refresh_refresh_token()
