"""J-Quants API認証モジュール

リフレッシュトークンからIDトークンを取得し、キャッシュを管理する。
"""

import os
import time
from dataclasses import dataclass

import httpx
from dotenv import find_dotenv, load_dotenv


@dataclass
class TokenCache:
    """IDトークンとその有効期限を保持"""
    id_token: str
    expires_at: float  # Unix timestamp


class JQuantsAuthError(Exception):
    """J-Quants認証エラー"""
    pass


class JQuantsAuth:
    """J-Quants API認証クライアント

    リフレッシュトークンを使用してIDトークンを取得・管理する。
    IDトークンは有効期限内であればキャッシュから返す。
    """

    AUTH_ENDPOINT = "https://api.jquants.com/v1/token/auth_refresh"
    AUTH_USER_ENDPOINT = "https://api.jquants.com/v1/token/auth_user"
    DEFAULT_TOKEN_LIFETIME_SECONDS = 24 * 60 * 60  # フォールバック: 24時間
    REFRESH_MARGIN_SECONDS = 60  # 有効期限の1分前に再取得

    def __init__(self, refresh_token: str | None = None):
        """初期化

        Args:
            refresh_token: J-Quantsリフレッシュトークン。
                          省略時は環境変数 JQUANTS_REFRESH_TOKEN から取得。

        Raises:
            JQuantsAuthError: リフレッシュトークンが見つからない場合
        """
        load_dotenv()

        self._refresh_token = refresh_token or os.environ.get("JQUANTS_REFRESH_TOKEN")
        if not self._refresh_token:
            raise JQuantsAuthError(
                "リフレッシュトークンが見つかりません。"
                "引数で指定するか、環境変数 JQUANTS_REFRESH_TOKEN を設定してください。"
            )

        self._cache: TokenCache | None = None

    def get_id_token(self) -> str:
        """有効なIDトークンを返す

        キャッシュに有効なトークンがあればそれを返す。
        有効期限切れまたはキャッシュがない場合は新規取得する。

        Returns:
            IDトークン文字列

        Raises:
            JQuantsAuthError: トークン取得に失敗した場合
        """
        if self._is_token_valid():
            return self._cache.id_token

        return self._fetch_id_token()

    def _is_token_valid(self) -> bool:
        """キャッシュされたトークンが有効か判定"""
        if self._cache is None:
            return False

        # 有効期限の1分前を過ぎていたら無効とみなす
        return time.time() < (self._cache.expires_at - self.REFRESH_MARGIN_SECONDS)

    def _fetch_id_token(self, _retried: bool = False) -> str:
        """APIからIDトークンを取得してキャッシュ

        HTTP 400/401エラー時はリフレッシュトークンの自動更新を試み、
        1回だけリトライする（無限ループ防止）。
        """
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    self.AUTH_ENDPOINT,
                    params={"refreshtoken": self._refresh_token}
                )
                response.raise_for_status()

                try:
                    data = response.json()
                except ValueError as e:
                    raise JQuantsAuthError(
                        f"APIレスポンスのJSON解析に失敗: {response.text[:200]}"
                    ) from e

                id_token = data.get("idToken")
                if not id_token:
                    raise JQuantsAuthError(
                        f"APIレスポンスにidTokenが含まれていません: {data}"
                    )

                # APIレスポンスに有効期限があれば使用、なければデフォルト値
                expires_in = data.get("expiresIn", self.DEFAULT_TOKEN_LIFETIME_SECONDS)
                try:
                    expires_in = int(expires_in)
                except (TypeError, ValueError):
                    expires_in = self.DEFAULT_TOKEN_LIFETIME_SECONDS

                self._cache = TokenCache(
                    id_token=id_token,
                    expires_at=time.time() + expires_in
                )

                return id_token

        except httpx.HTTPStatusError as e:
            if e.response.status_code in (400, 401) and not _retried:
                self._refresh_refresh_token()
                return self._fetch_id_token(_retried=True)
            raise JQuantsAuthError(
                f"認証APIエラー (HTTP {e.response.status_code}): {e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise JQuantsAuthError(f"認証APIリクエスト失敗: {e}") from e

    def _refresh_refresh_token(self) -> str:
        """email/passwordでリフレッシュトークンを再取得し、.envに永続化する

        Returns:
            新しいリフレッシュトークン

        Raises:
            JQuantsAuthError: 認証情報が不足、またはAPI呼び出しに失敗した場合
        """
        email = os.environ.get("JQUANTS_EMAIL")
        password = os.environ.get("JQUANTS_PASSWORD")
        if not email or not password:
            raise JQuantsAuthError(
                "リフレッシュトークンの自動更新には環境変数 JQUANTS_EMAIL と "
                "JQUANTS_PASSWORD の設定が必要です。\n"
                "J-Quantsアカウントのメールアドレスとパスワードを .env に設定してください:\n"
                "  JQUANTS_EMAIL=your_email@example.com\n"
                "  JQUANTS_PASSWORD=your_password"
            )

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    self.AUTH_USER_ENDPOINT,
                    json={"mailaddress": email, "password": password},
                )
                response.raise_for_status()

                data = response.json()
                new_refresh_token = data.get("refreshToken")
                if not new_refresh_token:
                    raise JQuantsAuthError(
                        f"auth_userレスポンスにrefreshTokenが含まれていません: {data}"
                    )

                self._refresh_token = new_refresh_token
                self._persist_refresh_token(new_refresh_token)
                return new_refresh_token

        except httpx.HTTPStatusError as e:
            raise JQuantsAuthError(
                f"リフレッシュトークン更新APIエラー (HTTP {e.response.status_code}): "
                f"{e.response.text}"
            ) from e
        except httpx.RequestError as e:
            raise JQuantsAuthError(
                f"リフレッシュトークン更新APIリクエスト失敗: {e}"
            ) from e

    def _persist_refresh_token(self, new_token: str) -> None:
        """新しいリフレッシュトークンを.envファイルに書き込む"""
        env_path = find_dotenv()
        if not env_path:
            return

        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        updated = False
        for i, line in enumerate(lines):
            if line.startswith("JQUANTS_REFRESH_TOKEN="):
                lines[i] = f"JQUANTS_REFRESH_TOKEN={new_token}\n"
                updated = True
                break

        if not updated:
            lines.append(f"JQUANTS_REFRESH_TOKEN={new_token}\n")

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
