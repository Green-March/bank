"""企業ホームページ コレクター.

EDINET 起点で企業公式サイトを特定し、企業概要・IR情報・ニュースを収集する。
"""

import csv
import importlib.util
import logging
import re
from pathlib import Path
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup

try:
    from .collector_base import BaseCollector, CollectorError, RobotsBlockedError
except ImportError:
    from collector_base import BaseCollector, CollectorError, RobotsBlockedError


def _import_ticker_resolver():
    """TickerResolver を動的にインポートする。

    ディレクトリ名が ticker-resolver (ハイフン) のため、
    標準 import 失敗時にファイルパスから直接ロードする。
    """
    # 1. 標準 import (パッケージとして sys.path に登録されている場合)
    try:
        from skills.ticker_resolver.scripts.resolver import TickerResolver
        return TickerResolver
    except ImportError:
        pass

    # 2. ファイルパスから直接ロード (ticker-resolver はハイフン付き)
    try:
        resolver_path = (
            Path(__file__).resolve().parents[2]
            / "ticker-resolver"
            / "scripts"
            / "resolver.py"
        )
        if resolver_path.exists():
            spec = importlib.util.spec_from_file_location(
                "ticker_resolver_scripts_resolver", resolver_path
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.TickerResolver
    except Exception:
        pass

    return None


TickerResolver = _import_ticker_resolver()

logger = logging.getLogger(__name__)

_EDINET_CSV_NAME = "EdinetcodeDlInfo.csv"

_IR_PATH_PATTERNS = re.compile(
    r"/(ir|investor|kabunushi|shareholders?|finance|ir_info)(/|$)", re.IGNORECASE
)


class HomepageCollector(BaseCollector):
    """EDINET 起点で企業公式サイトから情報を収集する。"""

    def __init__(self, config: dict | None = None, *, resolver=None, csv_path=None):
        super().__init__(config)
        if resolver is not None:
            self._resolver = resolver
        elif TickerResolver is not None:
            try:
                self._resolver = TickerResolver()
            except Exception:
                self._resolver = None
        else:
            self._resolver = None
        self._csv_path = Path(csv_path) if csv_path else None
        self.metadata: dict = {"accessed_domains": []}

    def collect(self, ticker: str) -> dict:
        """企業ホームページから情報を収集する。"""
        # 1. URL解決
        url = self._resolve_homepage_url(ticker)
        if not url:
            return {
                "url": None,
                "collected": False,
                "data": None,
                "error": "EDINET metadata にHP URL なし",
            }

        # 2. HTTPS強制
        url = self._ensure_https(url)

        # 3. EDINET起点ドメイン登録
        parsed = urlparse(url)
        domain = parsed.netloc
        if ":" in domain:
            domain = domain.split(":")[0]
        self._add_edinet_origin(domain)

        # 4. アクセスドメイン記録
        if domain not in self.metadata["accessed_domains"]:
            self.metadata["accessed_domains"].append(domain)

        # 5. robots.txt チェック + ページ取得
        try:
            response = self._fetch(url)
        except RobotsBlockedError:
            return {
                "url": url,
                "collected": False,
                "data": None,
                "error": "robots.txt denied",
            }
        except CollectorError:
            return {
                "url": url,
                "collected": False,
                "data": None,
                "error": "HTTPS接続失敗",
            }

        # 6. パース
        try:
            soup = BeautifulSoup(response.text, "html.parser")
            data = self._parse_homepage(soup, url)
        except Exception as exc:
            return {
                "url": url,
                "collected": False,
                "data": None,
                "error": f"パース失敗: {exc}",
            }

        return {
            "url": url,
            "collected": True,
            "data": data,
            "error": None,
        }

    # --- URL 解決 ---

    def _resolve_homepage_url(self, ticker: str) -> str | None:
        """TickerResolver + EDINET CSV からHP URLを取得する。"""
        if self._resolver is None:
            return None

        try:
            info = self._resolver.resolve(ticker)
        except Exception:
            return None

        edinet_code = info.get("edinet_code")
        if not edinet_code:
            return None

        return self._find_hp_in_csv(edinet_code)

    def _find_hp_in_csv(self, edinet_code: str) -> str | None:
        """EDINET CSV から HP URL を検索する。"""
        csv_path = self._csv_path
        if csv_path is None and self._resolver and hasattr(self._resolver, "_cache_dir"):
            csv_path = self._resolver._cache_dir / _EDINET_CSV_NAME
        if csv_path is None:
            return None
        if not csv_path.exists():
            return None

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row.get("ＥＤＩＮＥＴコード", "").strip()
                if code == edinet_code:
                    hp = row.get("HP", "").strip()
                    return hp if hp else None
        return None

    @staticmethod
    def _ensure_https(url: str) -> str:
        """http:// → https:// に昇格する。"""
        if url.startswith("http://"):
            return "https://" + url[7:]
        return url

    # --- HTML パース ---

    def _parse_homepage(self, soup: BeautifulSoup, base_url: str) -> dict:
        """Homepage HTML をパースして構造化データを返す。"""
        company_info = self._extract_company_info(soup)
        ir_page, ir_links = self._extract_ir_info(soup, base_url)
        news = self._extract_news(soup, base_url)

        return {
            "company_info": company_info,
            "ir_page": ir_page,
            "ir_links": ir_links,
            "news": news,
        }

    @staticmethod
    def _extract_company_info(soup: BeautifulSoup) -> dict:
        """企業概要を抽出する。"""
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else None

        meta_desc = soup.find("meta", attrs={"name": "description"})
        description = meta_desc.get("content", "").strip() if meta_desc else None

        og_name = soup.find("meta", attrs={"property": "og:site_name"})
        if og_name:
            company_name = og_name.get("content", "").strip()
        else:
            h1 = soup.find("h1")
            company_name = h1.get_text(strip=True) if h1 else title

        return {
            "title": title,
            "description": description,
            "company_name": company_name,
        }

    @staticmethod
    def _extract_ir_info(soup: BeautifulSoup, base_url: str) -> tuple[dict, list]:
        """IRページとIRリンクを検出・抽出する。"""
        ir_page = {"url": None, "detected": False}
        ir_links: list[dict] = []
        seen_urls: set[str] = set()

        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if _IR_PATH_PATTERNS.search(href):
                abs_url = urljoin(base_url, href)
                if not ir_page["detected"]:
                    ir_page = {"url": abs_url, "detected": True}
                if abs_url not in seen_urls:
                    seen_urls.add(abs_url)
                    link_title = a.get_text(strip=True) or href
                    link_type = _classify_link(href)
                    ir_links.append({
                        "title": link_title,
                        "url": abs_url,
                        "type": link_type,
                    })

        return ir_page, ir_links

    @staticmethod
    def _extract_news(soup: BeautifulSoup, base_url: str) -> list[dict]:
        """ニュースセクションを抽出する。"""
        news: list[dict] = []
        news_section = (
            soup.find("section", class_=re.compile(r"news|press|release", re.I))
            or soup.find("div", class_=re.compile(r"news|press|release", re.I))
            or soup.find("ul", class_=re.compile(r"news|press|release", re.I))
            or soup.find(id=re.compile(r"news|press|release", re.I))
        )
        if not news_section:
            return news

        items = news_section.find_all("li") or news_section.find_all("dl")
        for item in items:
            a = item.find("a")
            if not a:
                continue
            title = a.get_text(strip=True)
            link_url = urljoin(base_url, a.get("href", ""))
            date_el = (
                item.find("time")
                or item.find(class_=re.compile(r"date|time", re.I))
            )
            date = date_el.get_text(strip=True) if date_el else None
            news.append({"title": title, "url": link_url, "date": date})

        return news


def _classify_link(href: str) -> str:
    """リンクの種類を判定する。"""
    lower = href.lower()
    if lower.endswith(".pdf"):
        return "pdf"
    if lower.endswith((".html", ".htm", "/")) or "?" in lower:
        return "html"
    return "other"
