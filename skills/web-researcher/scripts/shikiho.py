"""四季報オンライン コレクター（認証付き）.

環境変数 SHIKIHO_EMAIL / SHIKIHO_PASSWORD で認証し、
四季報オンラインから企業情報を収集する。
"""

import logging
import os
import time

import httpx
from bs4 import BeautifulSoup

try:
    from .collector_base import (
        AuthenticationError,
        BaseCollector,
        CollectorError,
        RobotsBlockedError,
        _sanitize_log,
    )
except ImportError:
    from collector_base import (
        AuthenticationError,
        BaseCollector,
        CollectorError,
        RobotsBlockedError,
        _sanitize_log,
    )

logger = logging.getLogger(__name__)

_LOGIN_URL = "https://shikiho.toyokeizai.net/login"
_LOGOUT_URL = "https://shikiho.toyokeizai.net/logout"
_STOCK_URL = "https://shikiho.toyokeizai.net/stocks/{ticker}"


class ShikihoCollector(BaseCollector):
    """四季報オンラインから企業情報を収集する。"""

    def collect(self, ticker: str) -> dict:
        url = _STOCK_URL.format(ticker=ticker)
        email = os.environ.get("SHIKIHO_EMAIL")
        password = os.environ.get("SHIKIHO_PASSWORD")

        # 両方未設定 → 自動スキップ
        if not email and not password:
            raise AuthenticationError(
                "SHIKIHO_EMAIL/SHIKIHO_PASSWORD 未設定",
                error_code="AUTH_ENV_MISSING",
            )

        # 片方のみ設定 → graceful degradation
        if not email or not password:
            logger.warning(
                "認証情報が不完全です: %s",
                _sanitize_log({"email": email or "", "password": password or ""}),
            )
            raise AuthenticationError(
                "認証情報が不完全です（SHIKIHO_EMAIL/SHIKIHO_PASSWORD の両方を設定してください）",
                error_code="AUTH_ENV_MISSING",
            )

        # robots.txt 事前チェック（認証前に確認）— RobotsBlockedError をそのまま伝播
        self._check_robots(url)

        # 認証→取得→パースは try-finally で logout guarantee
        try:
            self._authenticate(email, password)

            response = self._fetch(url)

            # SESSION_EXPIRED 検知: リダイレクト先がログインページの場合
            response_url = str(getattr(response, "url", ""))
            if _LOGIN_URL in response_url:
                raise AuthenticationError(
                    "セッション期限切れ（ログインページへリダイレクト）",
                    error_code="SESSION_EXPIRED",
                )

            data = self._parse_page(response.text)
        except (CollectorError, Exception) as exc:
            # CollectorError (AuthenticationError 含む) はそのまま re-raise
            if isinstance(exc, CollectorError):
                raise
            # 予期しない例外は CollectorError でラップ
            raise CollectorError(f"予期しないエラー: {exc}") from exc
        finally:
            self._logout()

        return {
            "url": url,
            "collected": True,
            "data": data,
            "error": None,
        }

    def _authenticate(self, email: str, password: str) -> None:
        """ログインエンドポイントへ POST してセッション Cookie を取得する。

        ネットワークエラー/タイムアウト時はリトライする。
        """
        for attempt in range(self._max_retries + 1):
            self._wait_interval()
            self._last_request_time = time.time()
            try:
                response = self._client.post(
                    _LOGIN_URL,
                    data={"email": email, "password": password},
                )
                if response.status_code != 200:
                    raise AuthenticationError(
                        f"認証失敗: {response.status_code}",
                        error_code="AUTH_HTTP_ERROR",
                    )
                return
            except AuthenticationError:
                raise
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                if attempt < self._max_retries:
                    self._backoff_sleep(attempt)
                    continue
                raise AuthenticationError(
                    f"認証ネットワークエラー: {exc}",
                    error_code="AUTH_NETWORK_ERROR",
                ) from exc

    def _logout(self) -> None:
        """ログアウトしてセッションをクリアする（ベストエフォート）。"""
        try:
            self._client.post(_LOGOUT_URL)
        except Exception:
            logger.debug("ログアウト失敗（無視）")

    def _parse_page(self, html: str) -> dict:
        """BeautifulSoup で四季報ページをパースする。"""
        soup = BeautifulSoup(html, "html.parser")
        return {
            "company_overview": self._parse_company_overview(soup),
            "earnings_forecast": self._parse_earnings_forecast(soup),
            "consensus": self._parse_consensus(soup),
            "shareholders": self._parse_shareholders(soup),
            "indicators": self._parse_indicators(soup),
        }

    @staticmethod
    def _parse_company_overview(soup: BeautifulSoup) -> dict | None:
        section = soup.select_one("[data-section='company-overview']")
        if not section:
            return None
        return {
            "name": _text_or_none(section, ".company-name"),
            "industry": _text_or_none(section, ".industry"),
            "feature": _text_or_none(section, ".feature"),
        }

    @staticmethod
    def _parse_earnings_forecast(soup: BeautifulSoup) -> dict | None:
        section = soup.select_one("[data-section='earnings-forecast']")
        if not section:
            return None
        rows = section.select("tr")
        result = {}
        for row in rows:
            th = row.select_one("th")
            td = row.select_one("td")
            if th and td:
                result[th.get_text(strip=True)] = td.get_text(strip=True)
        return result or None

    @staticmethod
    def _parse_consensus(soup: BeautifulSoup) -> dict | None:
        section = soup.select_one("[data-section='consensus']")
        if not section:
            return None
        rows = section.select("tr")
        result = {}
        for row in rows:
            th = row.select_one("th")
            td = row.select_one("td")
            if th and td:
                result[th.get_text(strip=True)] = td.get_text(strip=True)
        return result or None

    @staticmethod
    def _parse_shareholders(soup: BeautifulSoup) -> list | None:
        section = soup.select_one("[data-section='shareholders']")
        if not section:
            return None
        rows = section.select("tr")
        result = []
        for row in rows:
            tds = row.select("td")
            if len(tds) >= 2:
                result.append({
                    "name": tds[0].get_text(strip=True),
                    "ratio": tds[1].get_text(strip=True),
                })
        return result or None

    @staticmethod
    def _parse_indicators(soup: BeautifulSoup) -> dict | None:
        section = soup.select_one("[data-section='indicators']")
        if not section:
            return None
        return {
            "PER": _text_or_none(section, ".per"),
            "PBR": _text_or_none(section, ".pbr"),
            "dividend_yield": _text_or_none(section, ".dividend-yield"),
        }


def _text_or_none(parent, selector: str) -> str | None:
    """CSS セレクタでテキストを取得。見つからなければ None。"""
    el = parent.select_one(selector)
    return el.get_text(strip=True) if el else None


def _safe_error_message(msg: str, email: str, password: str) -> str:
    """エラーメッセージから秘密情報を除去する。"""
    result = msg
    if email:
        result = result.replace(email, "***")
    if password:
        result = result.replace(password, "***")
    return result
