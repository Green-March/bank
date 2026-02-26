"""株探 (Kabutan) コレクター.

kabutan.jp から株価・業績・指標・決算速報・ニュースを収集する。
"""

import logging
import re

from bs4 import BeautifulSoup, Tag

try:
    from .collector_base import BaseCollector, CollectorError, RobotsBlockedError
except ImportError:
    from collector_base import BaseCollector, CollectorError, RobotsBlockedError

logger = logging.getLogger(__name__)

_BASE_URL = "https://kabutan.jp/stock/?code={ticker}"


def _parse_number(text: str | None) -> float | int | None:
    """カンマ区切り・マイナス表記(▲含む)をパースする。"""
    if text is None:
        return None
    s = text.strip().replace("\xa0", "").replace(" ", "")
    if s in ("", "---", "－", "—", "N/A"):
        return None
    s = s.replace("▲", "-").replace("△", "")
    s = s.replace(",", "")
    # 末尾の「倍」「%」「円」「百万」を除去
    s = re.sub(r"[倍%円]$", "", s)
    try:
        if "." in s:
            return float(s)
        return int(s)
    except ValueError:
        return None


def _parse_market_cap(text: str | None) -> float | None:
    """時価総額文字列をパースする (例: '1兆2,345億円' → 1234500000000)。"""
    if text is None:
        return None
    s = text.strip().replace(",", "").replace(" ", "").replace("\xa0", "")
    if s in ("", "---", "－"):
        return None

    total = 0.0
    # 兆
    m = re.search(r"([\d.]+)兆", s)
    if m:
        total += float(m.group(1)) * 1e12
    # 億
    m = re.search(r"([\d.]+)億", s)
    if m:
        total += float(m.group(1)) * 1e8
    # 万
    m = re.search(r"([\d.]+)万", s)
    if m:
        total += float(m.group(1)) * 1e4

    if total > 0:
        return total

    # 単純数値フォールバック
    s = re.sub(r"[円]$", "", s)
    try:
        return float(s)
    except ValueError:
        return None


def _parse_table(table: Tag) -> list[dict]:
    """<table> 要素からヘッダー行とデータ行を読み取り list[dict] を返す。"""
    rows = table.find_all("tr")
    if not rows:
        return []

    # ヘッダー行: <th> を探す
    headers: list[str] = []
    data_rows_start = 0
    for i, row in enumerate(rows):
        ths = row.find_all("th")
        if ths:
            headers = [th.get_text(strip=True) for th in ths]
            data_rows_start = i + 1
            break

    if not headers:
        return []

    result: list[dict] = []
    for row in rows[data_rows_start:]:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        values = [c.get_text(strip=True) for c in cells]
        record: dict = {}
        for j, header in enumerate(headers):
            if j < len(values):
                record[header] = values[j]
        if record:
            result.append(record)
    return result


class KabutanCollector(BaseCollector):
    """株探から企業情報を収集する。"""

    def collect(self, ticker: str) -> dict:
        url = _BASE_URL.format(ticker=ticker)
        try:
            response = self._fetch(url)
        except RobotsBlockedError as exc:
            return {
                "url": url,
                "collected": False,
                "data": None,
                "error": str(exc),
            }
        except CollectorError as exc:
            return {
                "url": url,
                "collected": False,
                "data": None,
                "error": str(exc),
            }

        soup = BeautifulSoup(response.text, "html.parser")

        # 存在しないページ検出
        if self._is_not_found(soup):
            return {
                "url": url,
                "collected": False,
                "data": None,
                "error": f"銘柄が見つかりません: {ticker}",
            }

        data = {
            "stock_price": self._parse_stock_price(soup),
            "financials": self._parse_financials(soup),
            "indicators": self._parse_indicators(soup),
            "earnings_flash": self._parse_earnings_flash(soup),
            "news": self._parse_news(soup),
        }

        return {
            "url": url,
            "collected": True,
            "data": data,
            "error": None,
        }

    @staticmethod
    def _is_not_found(soup: BeautifulSoup) -> bool:
        """ページが「該当なし」かどうかを判定する。"""
        title = soup.find("title")
        if title and "該当なし" in title.get_text():
            return True
        # 「該当する銘柄はありません」メッセージ
        for tag in soup.find_all(["p", "div"]):
            text = tag.get_text(strip=True)
            if "該当する銘柄" in text and "ありません" in text:
                return True
        return False

    @staticmethod
    def _parse_stock_price(soup: BeautifulSoup) -> dict | None:
        """株価情報セクションをパースする。"""
        result: dict = {}

        # 現在値
        current_el = soup.select_one("#stockinfo_i1 .kabuka")
        if current_el:
            result["current"] = _parse_number(current_el.get_text())

        # 前日比
        change_el = soup.select_one("#stockinfo_i1 .change")
        if change_el:
            result["change"] = _parse_number(change_el.get_text())

        # 4 本値 + 出来高テーブル
        stock_table = soup.select_one("div#stockinfo_i2 table")
        if stock_table:
            rows = _parse_table(stock_table)
            mapping = {
                "前日終値": "prev_close",
                "始値": "open",
                "高値": "high",
                "安値": "low",
                "出来高": "volume",
            }
            for row in rows:
                for jp_key, en_key in mapping.items():
                    if jp_key in row:
                        result[en_key] = _parse_number(row[jp_key])

        if not result:
            return None
        return result

    @staticmethod
    def _parse_financials(soup: BeautifulSoup) -> list[dict]:
        """業績推移テーブルをパースする。"""
        fin_table = soup.select_one("div#financial_td table")
        if not fin_table:
            return []

        raw_rows = _parse_table(fin_table)
        financials: list[dict] = []
        for row in raw_rows:
            entry: dict = {}
            # 期間
            for key in ("決算期", "期"):
                if key in row:
                    entry["period"] = row[key]
                    break
            # 売上高
            for key in ("売上高", "売上"):
                if key in row:
                    entry["revenue"] = _parse_number(row[key])
                    break
            # 営業利益
            if "営業益" in row:
                entry["operating_income"] = _parse_number(row["営業益"])
            elif "営業利益" in row:
                entry["operating_income"] = _parse_number(row["営業利益"])
            # 経常利益
            if "経常益" in row:
                entry["ordinary_income"] = _parse_number(row["経常益"])
            elif "経常利益" in row:
                entry["ordinary_income"] = _parse_number(row["経常利益"])
            # 純利益
            if "最終益" in row:
                entry["net_income"] = _parse_number(row["最終益"])
            elif "純利益" in row:
                entry["net_income"] = _parse_number(row["純利益"])
            # EPS
            if "1株益" in row:
                entry["eps"] = _parse_number(row["1株益"])
            elif "EPS" in row:
                entry["eps"] = _parse_number(row["EPS"])

            if entry:
                financials.append(entry)
        return financials

    @staticmethod
    def _parse_indicators(soup: BeautifulSoup) -> dict | None:
        """財務指標(PER/PBR/利回り/時価総額)をパースする。"""
        result: dict = {}

        indicator_div = soup.select_one("div#stockinfo_i3")
        if not indicator_div:
            return None

        table = indicator_div.find("table")
        if table:
            rows = _parse_table(table)
            for row in rows:
                if "PER" in row:
                    result["per"] = _parse_number(row["PER"])
                if "PBR" in row:
                    result["pbr"] = _parse_number(row["PBR"])
                if "利回り" in row:
                    result["dividend_yield"] = _parse_number(row["利回り"])
                if "時価総額" in row:
                    result["market_cap"] = _parse_market_cap(row["時価総額"])

        if not result:
            return None
        return result

    @staticmethod
    def _parse_earnings_flash(soup: BeautifulSoup) -> dict | None:
        """決算速報をパースする。"""
        flash_div = soup.select_one("div#kessan_flash")
        if not flash_div:
            return None

        title_el = flash_div.find(["h3", "a", "span"], class_=re.compile(r"title|heading"))
        title = title_el.get_text(strip=True) if title_el else None
        if not title:
            first_a = flash_div.find("a")
            title = first_a.get_text(strip=True) if first_a else None

        date_el = flash_div.find("time") or flash_div.find(class_=re.compile(r"date"))
        date = date_el.get_text(strip=True) if date_el else None

        content_el = flash_div.find("p") or flash_div.find(class_=re.compile(r"content|body"))
        content = content_el.get_text(strip=True) if content_el else None

        if not title and not content:
            return None

        return {"title": title, "date": date, "content": content}

    @staticmethod
    def _parse_news(soup: BeautifulSoup) -> list[dict]:
        """ニュース一覧をパースする。"""
        news_div = soup.select_one("div#news_list") or soup.select_one("div.news_list")
        if not news_div:
            return []

        items: list[dict] = []
        for li in news_div.find_all("li"):
            a = li.find("a")
            if not a:
                continue
            title = a.get_text(strip=True)
            date_el = li.find("time") or li.find("span", class_=re.compile(r"date|time"))
            date = date_el.get_text(strip=True) if date_el else None
            items.append({"title": title, "date": date})
        return items
