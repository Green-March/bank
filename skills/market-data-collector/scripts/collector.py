"""J-Quants API 株価・上場情報取得モジュール

daily_quotes API と listed/info API からデータを収集する。
"""

import logging
import random
import time

import httpx
from skills.common.auth import JQuantsAuth

logger = logging.getLogger(__name__)

BASE_URL = "https://api.jquants.com/v1"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0


def _is_retryable(exc: Exception) -> bool:
    """リトライ可能な例外かどうかを判定する。

    429 (レート制限)、タイムアウト、一時的ネットワーク障害をリトライ対象とする。
    """
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429
    if isinstance(exc, httpx.RequestError):
        return True
    return False


def _request_with_retry(
    client: httpx.Client,
    url: str,
    *,
    headers: dict | None = None,
    params: dict | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
) -> httpx.Response:
    """HTTP GETリクエストを exponential backoff with jitter でリトライ実行する。

    Args:
        client: httpx.Client インスタンス
        url: リクエスト先URL
        headers: HTTPヘッダー
        params: クエリパラメータ
        max_retries: 最大リトライ回数（デフォルト: 3）
        base_delay: 基本待機時間（秒、デフォルト: 1.0）
        max_delay: 最大待機時間（秒、デフォルト: 30.0）

    Returns:
        成功時の httpx.Response

    Raises:
        httpx.TimeoutException: リトライ上限後もタイムアウトした場合
        httpx.HTTPStatusError: リトライ上限後もHTTPエラーが返された場合
        httpx.RequestError: リトライ上限後もネットワークエラーが発生した場合
    """
    for attempt in range(max_retries + 1):
        try:
            response = client.get(url, headers=headers, params=params)
            response.raise_for_status()
            return response
        except (
            httpx.TimeoutException,
            httpx.HTTPStatusError,
            httpx.RequestError,
        ) as exc:
            if not _is_retryable(exc) or attempt >= max_retries:
                raise
            delay = min(base_delay * (2**attempt), max_delay)
            jitter = random.uniform(0, base_delay * 0.5)
            total_delay = delay + jitter
            logger.warning(
                "リトライ %d/%d (%.1f秒後): %s",
                attempt + 1,
                max_retries,
                total_delay,
                exc,
            )
            time.sleep(total_delay)
    raise RuntimeError("unreachable")  # pragma: no cover


class DailyQuotesError(Exception):
    """株価データ取得に関するエラー"""

    pass


class ListedInfoError(Exception):
    """上場情報取得に関するエラー"""

    pass


class DailyQuotesClient:
    """日次株価データを取得するクライアント"""

    def __init__(
        self,
        auth: JQuantsAuth,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
    ):
        self._auth = auth
        self._timeout = timeout
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay

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
                    response = _request_with_retry(
                        client,
                        url,
                        headers=headers,
                        params=params,
                        max_retries=self._max_retries,
                        base_delay=self._base_delay,
                        max_delay=self._max_delay,
                    )

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

    def __init__(
        self,
        auth: JQuantsAuth,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
    ):
        self._auth = auth
        self._timeout = timeout
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay

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
                response = _request_with_retry(
                    client,
                    url,
                    headers=headers,
                    params=params,
                    max_retries=self._max_retries,
                    base_delay=self._base_delay,
                    max_delay=self._max_delay,
                )
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
