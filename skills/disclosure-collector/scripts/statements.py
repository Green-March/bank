"""J-Quants API 決算短信データ取得モジュール"""

from __future__ import annotations

import httpx
from skills.common.auth import JQuantsAuth

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


# -- 数値型正規化 --------------------------------------------------------

# 金額フィールド: string → int
_INT_FIELDS: set[str] = {
    "NetSales",
    "OperatingProfit",
    "OrdinaryProfit",
    "Profit",
    "TotalAssets",
    "Equity",
    "CashFlowsFromOperatingActivities",
    "CashFlowsFromInvestingActivities",
}

# 比率フィールド: string → float
_FLOAT_FIELDS: set[str] = {
    "EarningsPerShare",
    "BookValuePerShare",
}

# 無効値とみなす文字列
_NULL_STRINGS: set[str] = {"", "-", "--", "N/A", "n/a", "null", "None"}


def _to_int(value: object) -> int | None:
    """J-Quants の金額文字列を int に変換する。

    整数文字列のみ許容する。小数点を含む文字列 ("1000.9" 等) は
    切り捨てによる金額歪みを防ぐため None を返す。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value:  # NaN
            return None
        if value == float("inf") or value == float("-inf"):
            return None
        if not value.is_integer():
            return None
        return int(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        if cleaned in _NULL_STRINGS:
            return None
        # 小数点を含む文字列は拒否 (切り捨て防止)
        if "." in cleaned:
            return None
        try:
            return int(cleaned)
        except (ValueError, OverflowError):
            return None
    return None


def _to_float(value: object) -> float | None:
    """J-Quants の比率文字列を float に変換する。

    NaN, Inf は無効値として None を返す。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if value != value:  # NaN
            return None
        if value == float("inf") or value == float("-inf"):
            return None
        return value
    if isinstance(value, int):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        if cleaned in _NULL_STRINGS:
            return None
        try:
            result = float(cleaned)
        except (ValueError, OverflowError):
            return None
        if result != result or result == float("inf") or result == float("-inf"):
            return None
        return result
    return None


def normalize_numeric_fields(record: dict) -> dict:
    """J-Quants API レスポンスの 1 レコードを数値正規化する。

    元の dict は変更せず、新しい dict を返す。
    """
    out = dict(record)
    for key in _INT_FIELDS:
        if key in out:
            out[key] = _to_int(out[key])
    for key in _FLOAT_FIELDS:
        if key in out:
            out[key] = _to_float(out[key])
    return out
