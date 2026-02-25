"""J-Quants API 株価・上場情報取得モジュール

daily_quotes API と listed/info API からデータを収集する。
"""

import sys
from pathlib import Path

import httpx

# disclosure-collector の JQuantsAuth を再利用
_repo_root = Path(__file__).resolve().parents[3]
_auth_dir = str(_repo_root / "skills" / "disclosure-collector" / "scripts")
if _auth_dir not in sys.path:
    sys.path.insert(0, _auth_dir)

from auth import JQuantsAuth  # noqa: E402

BASE_URL = "https://api.jquants.com/v1"
DEFAULT_TIMEOUT = 30.0


class DailyQuotesError(Exception):
    """株価データ取得に関するエラー"""

    pass


class ListedInfoError(Exception):
    """上場情報取得に関するエラー"""

    pass


class DailyQuotesClient:
    """日次株価データを取得するクライアント"""

    def __init__(self, auth: JQuantsAuth, timeout: float = DEFAULT_TIMEOUT):
        self._auth = auth
        self._timeout = timeout

    def fetch(self, code: str, from_date: str, to_date: str) -> list[dict]:
        """銘柄コードと期間を指定して日次株価データを取得

        Args:
            code: 銘柄コード（例: "7203"）
            from_date: 開始日（YYYY-MM-DD）
            to_date: 終了日（YYYY-MM-DD）

        Returns:
            日次株価データのリスト

        Raises:
            DailyQuotesError: API通信またはレスポンス解析に失敗した場合
        """
        url = f"{BASE_URL}/prices/daily_quotes"
        all_records: list[dict] = []
        params: dict = {"code": code, "from": from_date, "to": to_date}

        try:
            with httpx.Client(timeout=self._timeout) as client:
                while True:
                    headers = {
                        "Authorization": f"Bearer {self._auth.get_id_token()}"
                    }
                    response = client.get(url, headers=headers, params=params)
                    response.raise_for_status()

                    try:
                        data = response.json()
                    except ValueError as e:
                        raise DailyQuotesError(
                            f"レスポンスのJSON解析に失敗しました: {e}"
                        ) from e

                    if "daily_quotes" not in data:
                        raise DailyQuotesError(
                            f"レスポンスに 'daily_quotes' キーがありません: "
                            f"{list(data.keys())}"
                        )

                    all_records.extend(data["daily_quotes"])

                    pagination_key = data.get("pagination_key")
                    if not pagination_key:
                        break
                    params["pagination_key"] = pagination_key

        except httpx.TimeoutException as e:
            raise DailyQuotesError(
                f"APIリクエストがタイムアウトしました: {e}"
            ) from e
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 404:
                raise DailyQuotesError(
                    f"銘柄が見つかりません (code={code})。銘柄コードを確認してください。"
                ) from e
            if status == 429:
                raise DailyQuotesError(
                    "APIレート制限に達しました (429)。時間をおいて再試行してください。"
                ) from e
            raise DailyQuotesError(
                f"APIがエラーを返しました (status={status}): {e}"
            ) from e
        except httpx.RequestError as e:
            raise DailyQuotesError(
                f"APIリクエストに失敗しました: {e}"
            ) from e

        if not all_records:
            raise DailyQuotesError(
                f"銘柄が見つかりません (code={code})。"
                "指定期間の株価データが空です。銘柄コードと期間を確認してください。"
            )

        return all_records


class ListedInfoClient:
    """上場銘柄情報を取得するクライアント"""

    def __init__(self, auth: JQuantsAuth, timeout: float = DEFAULT_TIMEOUT):
        self._auth = auth
        self._timeout = timeout

    def fetch(self, code: str) -> list[dict]:
        """銘柄コードを指定して上場情報を取得

        Args:
            code: 銘柄コード（例: "7203"）

        Returns:
            上場情報のリスト

        Raises:
            ListedInfoError: API通信またはレスポンス解析に失敗した場合
        """
        url = f"{BASE_URL}/listed/info"
        headers = {"Authorization": f"Bearer {self._auth.get_id_token()}"}
        params = {"code": code}

        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.get(url, headers=headers, params=params)
                response.raise_for_status()
        except httpx.TimeoutException as e:
            raise ListedInfoError(
                f"APIリクエストがタイムアウトしました: {e}"
            ) from e
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 404:
                raise ListedInfoError(
                    f"銘柄が見つかりません (code={code})。銘柄コードを確認してください。"
                ) from e
            if status == 429:
                raise ListedInfoError(
                    "APIレート制限に達しました (429)。時間をおいて再試行してください。"
                ) from e
            raise ListedInfoError(
                f"APIがエラーを返しました (status={status}): {e}"
            ) from e
        except httpx.RequestError as e:
            raise ListedInfoError(
                f"APIリクエストに失敗しました: {e}"
            ) from e

        try:
            data = response.json()
        except ValueError as e:
            raise ListedInfoError(
                f"レスポンスのJSON解析に失敗しました: {e}"
            ) from e

        if "info" not in data:
            raise ListedInfoError(
                f"レスポンスに 'info' キーがありません: {list(data.keys())}"
            )

        info = data["info"]
        if not info:
            raise ListedInfoError(
                f"銘柄が見つかりません (code={code})。"
                "上場銘柄情報が空です。銘柄コードを確認してください。"
            )

        return info
