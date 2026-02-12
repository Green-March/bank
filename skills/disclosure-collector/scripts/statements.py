"""J-Quants API 決算短信データ取得モジュール"""

import httpx

try:
    from .auth import JQuantsAuth
except ImportError:
    from auth import JQuantsAuth

BASE_URL = "https://api.jquants.com/v1"
DEFAULT_TIMEOUT = 30.0


class StatementsError(Exception):
    """決算短信データ取得に関するエラー"""

    pass


class StatementsClient:
    """決算短信データを取得するクライアント"""

    def __init__(self, auth: JQuantsAuth, timeout: float = DEFAULT_TIMEOUT):
        """
        Args:
            auth: JQuantsAuth インスタンス（認証済みトークンを提供）
            timeout: HTTPリクエストのタイムアウト秒数
        """
        self._auth = auth
        self._timeout = timeout

    def fetch(self, code: str) -> list[dict]:
        """銘柄コードを指定して決算短信データを取得

        Args:
            code: 銘柄コード（例: "7203"）

        Returns:
            決算短信データのリスト

        Raises:
            StatementsError: API通信またはレスポンス解析に失敗した場合
        """
        url = f"{BASE_URL}/fins/statements"
        headers = {"Authorization": f"Bearer {self._auth.get_id_token()}"}
        params = {"code": code}

        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.get(url, headers=headers, params=params)
                response.raise_for_status()
        except httpx.TimeoutException as e:
            raise StatementsError(f"APIリクエストがタイムアウトしました: {e}") from e
        except httpx.HTTPStatusError as e:
            raise StatementsError(
                f"APIがエラーを返しました (status={e.response.status_code}): {e}"
            ) from e
        except httpx.RequestError as e:
            raise StatementsError(f"APIリクエストに失敗しました: {e}") from e

        try:
            data = response.json()
        except ValueError as e:
            raise StatementsError(f"レスポンスのJSON解析に失敗しました: {e}") from e

        if "statements" not in data:
            raise StatementsError(
                f"レスポンスに 'statements' キーがありません: {list(data.keys())}"
            )

        return data["statements"]
