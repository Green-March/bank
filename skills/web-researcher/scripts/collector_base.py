"""web-researcher BaseCollector — 抽象基底クラス.

robots.txt チェック、ドメインバリデーション、exponential backoff with jitter、
リクエスト間隔制御、ログサニタイズを提供する。
"""

import abc
import logging
import random
import re
import time
import urllib.robotparser
from urllib.parse import urlparse

import httpx
import yaml
from pathlib import Path

logger = logging.getLogger(__name__)

# --- 例外階層 ---


class CollectorError(Exception):
    """コレクター基底例外"""
    pass


class RobotsBlockedError(CollectorError):
    """robots.txt によりアクセスが拒否された"""
    pass


class AuthenticationError(CollectorError):
    """認証エラー"""
    pass


class DomainNotAllowedError(CollectorError):
    """許可されていないドメインへのアクセス"""
    pass


# --- デフォルト設定 ---

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "references" / "default_config.yaml"

STATIC_ALLOWED_DOMAINS = [
    "finance.yahoo.co.jp",
    "kabutan.jp",
    "shikiho.toyokeizai.net",
]


def _load_default_config() -> dict:
    if _DEFAULT_CONFIG_PATH.exists():
        with open(_DEFAULT_CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


# --- ログサニタイズ ---

_SENSITIVE_PATTERNS = [
    (re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"), "***"),
    (re.compile(r"(?i)(password|passwd|secret|token)\s*[:=]\s*\S+"), "***"),
]


def _sanitize_log(data: dict) -> dict:
    """email/password パターンをマスクしたコピーを返す。"""
    sanitized = {}
    for key, value in data.items():
        if isinstance(value, str):
            result = value
            for pattern, replacement in _SENSITIVE_PATTERNS:
                result = pattern.sub(replacement, result)
            sanitized[key] = result
        elif isinstance(value, dict):
            sanitized[key] = _sanitize_log(value)
        else:
            sanitized[key] = value
    return sanitized


# --- BaseCollector ---


class BaseCollector(abc.ABC):
    """Web情報収集の抽象基底クラス。

    サブクラスは collect(ticker) を実装する。
    """

    def __init__(self, config: dict | None = None):
        defaults = _load_default_config()
        if config:
            defaults.update(config)
        self._config = defaults

        self._interval = self._config.get("request_interval_seconds", 2)
        self._max_retries = self._config.get("max_retries", 3)
        self._backoff_base = self._config.get("backoff_base_seconds", 2)
        self._backoff_max = self._config.get("backoff_max_seconds", 30)
        self._user_agent = self._config.get("user_agent", "BANK-WebResearcher/1.0")
        self._timeout = self._config.get("timeout_seconds", 30)
        self._allowed_domains = list(
            self._config.get("allowed_domains", STATIC_ALLOWED_DOMAINS)
        )
        self._edinet_origins: set[str] = set()
        self._last_request_time: float = 0.0

    # --- Context manager (httpx.Client) ---

    def __enter__(self):
        self._client = httpx.Client(
            timeout=self._timeout,
            headers={"User-Agent": self._user_agent},
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self, "_client"):
            self._client.close()
        return False

    # --- robots.txt チェック ---

    def _check_robots(self, url: str) -> bool:
        """robots.txt を確認し、アクセス可否を返す。拒否時は RobotsBlockedError。"""
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        try:
            rp.read()
        except Exception:
            logger.warning("robots.txt の取得に失敗: %s (アクセスを許可)", robots_url)
            return True

        if rp.can_fetch(self._user_agent, url):
            return True
        raise RobotsBlockedError(f"robots.txt によりアクセスが拒否されました: {url}")

    # --- ドメインバリデーション ---

    def _validate_domain(self, url: str) -> None:
        """URL のドメインが許可リストに含まれるか検証する。"""
        parsed = urlparse(url)
        domain = parsed.netloc
        if ":" in domain:
            domain = domain.split(":")[0]

        if domain in self._allowed_domains:
            return
        if domain in self._edinet_origins:
            return
        raise DomainNotAllowedError(
            f"許可されていないドメインです: {domain} (許可: {self._allowed_domains})"
        )

    def _is_edinet_origin(self, url: str) -> bool:
        """EDINET 起点の URL かどうかを判定する（HomepageCollector が設定）。"""
        parsed = urlparse(url)
        domain = parsed.netloc
        if ":" in domain:
            domain = domain.split(":")[0]
        return domain in self._edinet_origins

    def _add_edinet_origin(self, domain: str) -> None:
        """EDINET 起点ドメインを許可リストに追加する。"""
        self._edinet_origins.add(domain)

    # --- リクエスト間隔制御 ---

    def _wait_interval(self) -> None:
        """前回リクエストからの間隔を確保する。"""
        if self._last_request_time > 0:
            elapsed = time.time() - self._last_request_time
            remaining = self._interval - elapsed
            if remaining > 0:
                time.sleep(remaining)

    # --- Exponential backoff + jitter ---

    def _fetch(self, url: str) -> httpx.Response:
        """URL からコンテンツを取得する。robots.txt/ドメイン検証/リトライ付き。"""
        self._validate_domain(url)
        self._check_robots(url)

        for attempt in range(self._max_retries + 1):
            self._wait_interval()
            try:
                self._last_request_time = time.time()
                response = self._client.get(url)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 401 or status == 403:
                    raise AuthenticationError(
                        f"認証/権限エラー (status={status}): {url}"
                    ) from exc
                if (status == 429 or status >= 500) and attempt < self._max_retries:
                    self._backoff_sleep(attempt)
                    continue
                raise CollectorError(
                    f"HTTP エラー (status={status}): {url}"
                ) from exc
            except httpx.TimeoutException as exc:
                if attempt < self._max_retries:
                    self._backoff_sleep(attempt)
                    continue
                raise CollectorError(f"タイムアウト: {url}") from exc
            except httpx.RequestError as exc:
                if attempt < self._max_retries:
                    self._backoff_sleep(attempt)
                    continue
                raise CollectorError(f"リクエストエラー: {url}") from exc

        raise CollectorError(f"最大リトライ回数超過: {url}")  # pragma: no cover

    def _backoff_sleep(self, attempt: int) -> None:
        delay = min(self._backoff_base * (2 ** attempt), self._backoff_max)
        jitter = random.uniform(0, self._backoff_base * 0.5)
        total = delay + jitter
        logger.warning("リトライ %d/%d (%.1f秒後)", attempt + 1, self._max_retries, total)
        time.sleep(total)

    # --- sanitize ---

    @staticmethod
    def sanitize_log(data: dict) -> dict:
        return _sanitize_log(data)

    # --- 抽象メソッド ---

    @abc.abstractmethod
    def collect(self, ticker: str) -> dict:
        """銘柄情報を収集する。サブクラスで実装する。"""
        ...
