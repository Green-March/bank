"""skills.common.auth 共有認証モジュールのテスト

skills/common/auth.py が正しくインポート可能であること、
および disclosure-collector / market-data-collector の両方から
同一クラスを参照できることを検証する。
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from skills.common.auth import JQuantsAuth, JQuantsAuthError, TokenCache


# ---------------------------------------------------------------------------
# インポート検証
# ---------------------------------------------------------------------------


def test_import_from_skills_common():
    """skills.common.auth からクラスがインポートできること"""
    assert JQuantsAuth is not None
    assert JQuantsAuthError is not None
    assert TokenCache is not None


def test_import_from_skills_common_init():
    """skills.common.__init__ からもリエクスポートされていること"""
    from skills.common import JQuantsAuth as Auth
    from skills.common import JQuantsAuthError as AuthError
    from skills.common import TokenCache as Cache

    assert Auth is JQuantsAuth
    assert AuthError is JQuantsAuthError
    assert Cache is TokenCache


def test_disclosure_collector_reexport():
    """disclosure-collector の auth.py がリエクスポートとして機能すること"""
    import sys
    from pathlib import Path

    scripts_dir = str(Path(__file__).resolve().parents[2] / "disclosure-collector" / "scripts")
    if scripts_dir not in sys.path:
        sys.path.append(scripts_dir)

    from auth import JQuantsAuth as DcAuth
    assert DcAuth is JQuantsAuth


# ---------------------------------------------------------------------------
# 基本機能テスト（共有モジュールとしての動作確認）
# ---------------------------------------------------------------------------


def test_constructor_with_env(monkeypatch):
    """環境変数からトークンを取得"""
    monkeypatch.setenv("JQUANTS_REFRESH_TOKEN", "test-token")
    auth = JQuantsAuth()
    assert auth._refresh_token == "test-token"


def test_constructor_with_explicit_token(monkeypatch):
    """明示的トークンが環境変数より優先"""
    monkeypatch.setenv("JQUANTS_REFRESH_TOKEN", "env-token")
    auth = JQuantsAuth(refresh_token="explicit-token")
    assert auth._refresh_token == "explicit-token"


def test_constructor_missing_token_raises(monkeypatch):
    """トークン未設定でエラー"""
    monkeypatch.delenv("JQUANTS_REFRESH_TOKEN", raising=False)
    with patch("skills.common.auth.load_dotenv"):
        with pytest.raises(JQuantsAuthError, match="リフレッシュトークンが見つかりません"):
            JQuantsAuth()


def test_cached_token_returned(monkeypatch):
    """有効なキャッシュがあればAPIを呼ばない"""
    monkeypatch.setenv("JQUANTS_REFRESH_TOKEN", "test-token")
    auth = JQuantsAuth()
    auth._cache = TokenCache(
        id_token="cached-token",
        expires_at=time.time() + 3600,
    )
    assert auth.get_id_token() == "cached-token"


def test_expired_token_refetched(monkeypatch):
    """キャッシュ期限切れで新規取得"""
    monkeypatch.setenv("JQUANTS_REFRESH_TOKEN", "test-token")
    auth = JQuantsAuth()
    auth._cache = TokenCache(
        id_token="old-token",
        expires_at=time.time() - 100,
    )

    mock = MagicMock()
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"idToken": "new-token", "expiresIn": 3600}
    resp.raise_for_status = MagicMock()
    mock.post = MagicMock(return_value=resp)

    with patch("httpx.Client", return_value=mock):
        token = auth.get_id_token()
    assert token == "new-token"


def test_token_cache_dataclass():
    """TokenCache のフィールドが正しいこと"""
    cache = TokenCache(id_token="token-123", expires_at=1700000000.0)
    assert cache.id_token == "token-123"
    assert cache.expires_at == 1700000000.0
