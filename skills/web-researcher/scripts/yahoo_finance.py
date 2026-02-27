"""Yahoo ファイナンス コレクター.

finance.yahoo.co.jp から株価・業績・指標・ニュースを収集する。
ページ内の window.__PRELOADED_STATE__ JSON からデータを抽出する。
"""

import json
import logging
import re

from bs4 import BeautifulSoup

try:
    from .collector_base import BaseCollector, CollectorError, RobotsBlockedError
except ImportError:
    from collector_base import BaseCollector, CollectorError, RobotsBlockedError

logger = logging.getLogger(__name__)

# --- 日本語数値パーサー ---

_UNIT_MAP = {
    "兆": 1_000_000_000_000,
    "億": 100_000_000,
    "万": 10_000,
}


def _parse_japanese_number(text: str) -> float | None:
    """日本語フォーマットの数値文字列を float に変換する。

    対応フォーマット:
    - "1,234.56" → 1234.56
    - "1,234億5,678万円" → 123456780000.0
    - "△1,234" → -1234.0
    - "%", "倍", "円", "株" 等の単位を除去
    - "---" 等の非数値 → None
    """
    if text is None:
        return None
    text = str(text).strip()
    if not text or text == "---" or text == "--":
        return None

    negative = False
    if text.startswith("△") or text.startswith("▲"):
        negative = True
        text = text[1:]
    elif text.startswith("-") or text.startswith("−") or text.startswith("ー"):
        negative = True
        text = text[1:]

    # 単位サフィックスを除去
    text = re.sub(r"[%％倍円株]$", "", text.strip())
    text = text.strip()

    if not text:
        return None

    # 兆/億/万 を含む場合: "1,234億5,678万" → 計算
    has_unit = any(u in text for u in _UNIT_MAP)
    if has_unit:
        total = 0.0
        remaining = text
        for unit_char, multiplier in _UNIT_MAP.items():
            if unit_char in remaining:
                parts = remaining.split(unit_char, 1)
                num_str = parts[0].replace(",", "").strip()
                if num_str:
                    try:
                        total += float(num_str) * multiplier
                    except ValueError:
                        return None
                remaining = parts[1] if len(parts) > 1 else ""
        # 残余部分（単位なしの端数）
        remaining = remaining.replace(",", "").strip()
        remaining = re.sub(r"[%％倍円株]$", "", remaining).strip()
        if remaining:
            try:
                total += float(remaining)
            except ValueError:
                pass
        return -total if negative else total

    # 通常の数値: カンマ除去
    text = text.replace(",", "")
    try:
        value = float(text)
        return -value if negative else value
    except ValueError:
        return None


# --- YahooFinanceCollector ---


class YahooFinanceCollector(BaseCollector):
    """Yahoo ファイナンスから企業情報を収集する。"""

    BASE_URL = "https://finance.yahoo.co.jp/quote/{ticker}.T"

    def collect(self, ticker: str) -> dict:
        url = self.BASE_URL.format(ticker=ticker)
        try:
            response = self._fetch(url)
        except RobotsBlockedError as exc:
            return {
                "url": url,
                "collected": False,
                "data": None,
                "error": f"robots.txt 拒否: {exc}",
            }
        except CollectorError as exc:
            return {
                "url": url,
                "collected": False,
                "data": None,
                "error": str(exc),
            }

        html = response.text
        preloaded = self._extract_preloaded_state(html)
        if preloaded is None:
            return {
                "url": url,
                "collected": False,
                "data": None,
                "error": "ページデータの抽出に失敗しました",
            }

        data = {
            "stock_price": self._extract_stock_price(preloaded),
            "financials": self._extract_financials(preloaded),
            "indicators": self._extract_indicators(preloaded),
            "news": self._extract_news(preloaded),
        }

        return {
            "url": url,
            "collected": True,
            "data": data,
            "error": None,
        }

    @staticmethod
    def _extract_preloaded_state(html: str) -> dict | None:
        """HTML から window.__PRELOADED_STATE__ の JSON を抽出する。"""
        soup = BeautifulSoup(html, "html.parser")
        for script in soup.find_all("script"):
            text = script.string or ""
            if "window.__PRELOADED_STATE__" in text:
                match = re.search(
                    r"window\.__PRELOADED_STATE__\s*=\s*({.+?})\s*;?\s*(?:</script>|$)",
                    text,
                    re.DOTALL,
                )
                if match:
                    try:
                        return json.loads(match.group(1))
                    except json.JSONDecodeError:
                        logger.warning("__PRELOADED_STATE__ の JSON パースに失敗")
                        return None
        return None

    @staticmethod
    def _extract_stock_price(state: dict) -> dict:
        """株価情報を抽出する。"""
        board = state.get("mainStocksPriceBoard", {})
        detail = state.get("mainStocksDetail", {}).get("detail", {})

        price_raw = board.get("price")
        # price が "---" の場合は savePrice (前日終値) を使う
        current = _parse_japanese_number(price_raw)
        if current is None:
            current = _parse_japanese_number(board.get("savePrice"))

        change = _parse_japanese_number(board.get("priceChange"))
        change_percent = _parse_japanese_number(board.get("priceChangeRate"))
        volume = _parse_japanese_number(detail.get("volume"))
        turnover = _parse_japanese_number(detail.get("tradingValue"))

        return {
            "current": current,
            "change": change,
            "change_percent": change_percent,
            "volume": int(volume) if volume is not None else None,
            "turnover": turnover,
        }

    @staticmethod
    def _extract_financials(state: dict) -> list:
        """業績情報を抽出する。"""
        perf = state.get("stockPerformance", {})
        chart_info = perf.get("chartInfo", [])
        if not chart_info:
            return []

        results = []
        for item in chart_info:
            period = item.get("date", "")
            # date は "202303" 形式 → "2023-03" に変換
            if len(period) == 6:
                period = f"{period[:4]}-{period[4:]}"
            revenue = item.get("amount")
            profit_margin = item.get("profitMargin")
            # amount は売上高（百万円）、profitMargin から営業利益を概算
            operating_income = None
            if revenue is not None and profit_margin is not None:
                operating_income = round(revenue * profit_margin / 100)
            results.append({
                "period": period,
                "revenue": float(revenue) if revenue is not None else None,
                "operating_income": float(operating_income) if operating_income is not None else None,
                "ordinary_income": None,
                "net_income": None,
            })
        return results

    @staticmethod
    def _extract_indicators(state: dict) -> dict:
        """指標情報を抽出する。"""
        board = state.get("mainStocksPriceBoard", {})
        ref = state.get("mainStocksDetail", {}).get("referenceIndex", {})

        per = _parse_japanese_number(ref.get("per"))
        pbr = _parse_japanese_number(ref.get("pbr"))
        dividend_yield = _parse_japanese_number(ref.get("shareDividendYield"))
        if dividend_yield is None:
            dividend_yield = _parse_japanese_number(board.get("shareDividendYield"))
        market_cap = _parse_japanese_number(ref.get("totalPrice"))
        # totalPrice は百万円単位 → 円に変換
        if market_cap is not None:
            market_cap = market_cap * 1_000_000
        shares = _parse_japanese_number(ref.get("sharesIssued"))

        return {
            "per": per,
            "pbr": pbr,
            "dividend_yield": dividend_yield,
            "market_cap": market_cap,
            "shares_outstanding": int(shares) if shares is not None else None,
        }

    @staticmethod
    def _extract_news(state: dict) -> list:
        """ニュース一覧を抽出する。"""
        results = []

        # mainStocksNews から取得を試みる
        news_data = state.get("mainStocksNews", {})
        articles = news_data.get("articles", [])
        for article in articles:
            results.append({
                "title": article.get("title", ""),
                "url": article.get("url", ""),
                "date": article.get("date", ""),
            })

        # symbolTopics からも補完
        if not results:
            topics = state.get("symbolTopics", {})
            topic_list = topics.get("topics", [])
            for topic in topic_list:
                sources = topic.get("sources", [])
                for src in sources:
                    title = src.get("title", "")
                    url = src.get("url", "")
                    if title and url:
                        results.append({
                            "title": title,
                            "url": url,
                            "date": src.get("date", topic.get("date", "")),
                        })
        return results
