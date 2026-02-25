"""ticker-resolver core: TickerResolver クラスと関連例外."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CACHE_TTL_DAYS = 30
EDINET_CODE_LIST_URL = "https://api.edinet-fsa.go.jp/api/v2/edinetcode/list"
JQUANTS_LISTED_INFO_URL = "https://api.jquants.com/v1/listed/info"
CACHE_CSV_NAME = "EdinetcodeDlInfo.csv"
JQUANTS_CACHE_JSON_NAME = "jquants_listed.json"
CACHE_META_NAME = ".cache_updated_at"
DEFAULT_CACHE_DIR = Path("data/.ticker_cache")

# ---------------------------------------------------------------------------
# Field mapping: EDINET CSV ↔ J-Quants listed/info ↔ Internal
# ---------------------------------------------------------------------------
#
# | EDINET CSV column      | J-Quants field   | Internal key   | Notes                    |
# |------------------------|------------------|----------------|--------------------------|
# | 証券コード (e.g. "72030") | Code ("72030")  | sec_code       | 5桁。両ソース共通キー       |
# | 提出者名               | CompanyName      | company_name   | EDINET優先 (all時)        |
# | ＥＤＩＮＥＴコード       | (なし)           | edinet_code    | EDINET固有                |
# | 決算日 → 月抽出         | (なし※)          | fye_month      | EDINET固有。J-Quants単独時はNone |
# | 上場区分               | MarketCode       | (フィルタ用)   | EDINET:"上場"/J-Quants:市場コード |
#
# ※ J-Quants /v1/listed/info には決算月フィールドがない。
#   source='all' マージ時は EDINET 側の fye_month を採用する。
#   J-Quants のみに存在する銘柄は fye_month=None となる。
#


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class TickerNotFoundError(Exception):
    """指定された銘柄コードがキャッシュに存在しない."""


class CacheExpiredError(Exception):
    """キャッシュの有効期限が切れている."""


class NetworkError(Exception):
    """EDINET API 接続エラー."""


# ---------------------------------------------------------------------------
# TickerResolver
# ---------------------------------------------------------------------------


class TickerResolver:
    """銘柄コード(4桁) → edinet_code, company_name, fye_month を解決する.

    Parameters
    ----------
    cache_dir : Path | None
        キャッシュファイルの格納ディレクトリ。
        None の場合はデフォルトパス (data/.ticker_cache/) を使用。
    """

    def __init__(self, cache_dir: Path | None = None) -> None:
        self._cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._data: list[dict[str, Any]] = []
        self._load_cache()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, ticker: str) -> dict[str, Any]:
        """銘柄コードから企業情報を解決する.

        Parameters
        ----------
        ticker : str
            銘柄コード（4桁、例: "7203"）

        Returns
        -------
        dict
            {"edinet_code", "company_name", "sec_code", "fye_month"}

        Raises
        ------
        CacheExpiredError
            キャッシュが未取得または有効期限切れの場合。
        TickerNotFoundError
            キャッシュに該当銘柄が存在しない場合。
        """
        if not self._data or self._is_cache_expired():
            raise CacheExpiredError(
                "キャッシュが未取得または期限切れです。update_cache() を実行してください。"
            )

        # 4桁 ticker → 5桁 sec_code (末尾0付き)
        sec_code_5 = ticker + "0"

        for entry in self._data:
            if entry.get("sec_code") == sec_code_5:
                return {
                    "edinet_code": entry["edinet_code"],
                    "company_name": entry["company_name"],
                    "sec_code": entry["sec_code"],
                    "fye_month": entry["fye_month"],
                }

        raise TickerNotFoundError(f"銘柄コード '{ticker}' が見つかりません。")

    def update_cache(self, source: str = "all", *, force: bool = False) -> int:
        """外部ソースからキャッシュを更新する.

        Parameters
        ----------
        source : str
            データソース ("edinet" / "jquants" / "all")
        force : bool
            True の場合、有効期限を無視して強制更新。

        Returns
        -------
        int
            更新された銘柄数。
        """
        if not force and not self._is_cache_expired():
            return 0

        if source not in ("edinet", "jquants", "all"):
            raise ValueError(
                f"不正な source: '{source}'。'edinet', 'jquants', 'all' のいずれかを指定してください。"
            )

        # EDINET ソース
        if source in ("edinet", "all"):
            csv_text = self._download_edinet_code_list()
            csv_path = self._cache_dir / CACHE_CSV_NAME
            csv_path.write_text(csv_text, encoding="utf-8")

        # J-Quants ソース
        # source='jquants' の場合は失敗時に例外を上げる（必須）。
        # source='all' の場合は best-effort（認証やAPI失敗時はスキップ）。
        if source in ("jquants", "all"):
            try:
                jquants_records = self._download_jquants_listed_info()
                jquants_path = self._cache_dir / JQUANTS_CACHE_JSON_NAME
                jquants_path.write_text(
                    json.dumps(jquants_records, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except NetworkError:
                if source == "jquants":
                    raise
                # source='all': J-Quants 取得失敗はスキップ（EDINET のみで続行）

        # 更新タイムスタンプを記録
        meta_path = self._cache_dir / CACHE_META_NAME
        meta_path.write_text(
            datetime.now(timezone.utc).isoformat(), encoding="utf-8"
        )

        # キャッシュ再読み込み（EDINET + J-Quants をマージ）
        self._load_cache()

        return len(self._data)

    def list_all(self, fye_month: int | None = None) -> list[dict[str, Any]]:
        """キャッシュ内の全銘柄を返す.

        Parameters
        ----------
        fye_month : int | None
            指定時、その決算月の銘柄のみフィルタ。

        Returns
        -------
        list[dict]
            銘柄情報のリスト。
            各要素: {edinet_code, company_name, sec_code, ticker, fye_month}
        """
        result: list[dict[str, Any]] = []
        for entry in self._data:
            if fye_month is not None and entry.get("fye_month") != fye_month:
                continue
            sec = entry.get("sec_code", "")
            result.append(
                {
                    "edinet_code": entry["edinet_code"],
                    "company_name": entry["company_name"],
                    "sec_code": sec,
                    "ticker": sec[:4] if len(sec) >= 4 else sec,
                    "fye_month": entry["fye_month"],
                }
            )
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_cache(self) -> None:
        """キャッシュファイルをディスクから読み込む.

        EDINET CSV と J-Quants JSON の両方を読み込み、
        sec_code をキーとしてマージして self._data に保持する。
        EDINET データが優先（edinet_code, fye_month は EDINET 固有）。
        """
        # sec_code → record のマッピング
        merged: dict[str, dict[str, Any]] = {}

        # 1) EDINET CSV を読み込み
        csv_path = self._cache_dir / CACHE_CSV_NAME
        if csv_path.exists():
            with open(csv_path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    listing = row.get("上場区分", "").strip()
                    if not listing or listing == "非上場":
                        continue

                    sec_code = row.get("証券コード", "").strip()
                    if not sec_code:
                        continue

                    edinet_code = row.get("ＥＤＩＮＥＴコード", "").strip()
                    company_name = row.get("提出者名", "").strip()
                    fye_date = row.get("決算日", "").strip()
                    fye_month = self._parse_fye_month(fye_date)

                    merged[sec_code] = {
                        "edinet_code": edinet_code,
                        "company_name": company_name,
                        "sec_code": sec_code,
                        "fye_month": fye_month,
                    }

        # 2) J-Quants JSON を読み込み・マージ
        jquants_path = self._cache_dir / JQUANTS_CACHE_JSON_NAME
        if jquants_path.exists():
            try:
                records = json.loads(jquants_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                records = []

            for rec in records:
                sec_code = rec.get("Code", "").strip()
                if not sec_code:
                    continue

                if sec_code in merged:
                    # EDINET に既存 → edinet_code / fye_month は EDINET 側を維持
                    pass
                else:
                    # J-Quants のみの銘柄を追加
                    merged[sec_code] = {
                        "edinet_code": "",
                        "company_name": rec.get("CompanyName", "").strip(),
                        "sec_code": sec_code,
                        "fye_month": None,
                    }

        self._data = list(merged.values())

    def _is_cache_expired(self) -> bool:
        """キャッシュの有効期限を確認する."""
        meta_path = self._cache_dir / CACHE_META_NAME
        if not meta_path.exists():
            return True

        try:
            ts_str = meta_path.read_text(encoding="utf-8").strip()
            cached_at = datetime.fromisoformat(ts_str)
            now = datetime.now(timezone.utc)
            return (now - cached_at).days >= CACHE_TTL_DAYS
        except (ValueError, OSError):
            return True

    def _download_jquants_listed_info(self) -> list[dict[str, Any]]:
        """J-Quants API から上場銘柄一覧を取得する.

        skills/common/auth.py の JQuantsAuth を使用して認証し、
        GET /v1/listed/info から銘柄情報の配列を返す。

        Returns
        -------
        list[dict]
            J-Quants API レスポンスの info 配列。

        Raises
        ------
        NetworkError
            認証エラーまたは API 接続に失敗した場合。
        """
        try:
            from skills.common.auth import JQuantsAuth, JQuantsAuthError
        except ImportError as e:
            raise NetworkError(
                f"J-Quants 認証モジュールが利用できません: {e}"
            ) from e

        try:
            auth = JQuantsAuth()
            id_token = auth.get_id_token()
        except JQuantsAuthError as e:
            raise NetworkError(f"J-Quants 認証エラー: {e}") from e

        try:
            resp = requests.get(
                JQUANTS_LISTED_INFO_URL,
                headers={"Authorization": f"Bearer {id_token}"},
                timeout=60,
            )
            resp.raise_for_status()
        except requests.ConnectionError as e:
            raise NetworkError(f"J-Quants API 接続エラー: {e}") from e
        except requests.Timeout as e:
            raise NetworkError(f"J-Quants API タイムアウト: {e}") from e
        except requests.RequestException as e:
            raise NetworkError(f"J-Quants API リクエストエラー: {e}") from e

        try:
            data = resp.json()
        except (ValueError, TypeError) as e:
            raise NetworkError(
                f"J-Quants API レスポンスの JSON 解析に失敗: {e}"
            ) from e

        info = data.get("info", []) if isinstance(data, dict) else []
        if not isinstance(info, list):
            raise NetworkError(
                "J-Quants API レスポンスの 'info' フィールドがリストではありません"
            )
        return info

    def _download_edinet_code_list(self) -> str:
        """EDINET API から EdinetcodeDlInfo.csv を ZIP 形式で取得し UTF-8 テキストで返す.

        Raises
        ------
        NetworkError
            API 接続・レスポンス処理に失敗した場合。
        """
        params: dict[str, str] = {"type": "2"}
        headers: dict[str, str] = {}

        api_key = os.environ.get("EDINET_API_KEY") or os.environ.get(
            "EDINET_SUBSCRIPTION_KEY"
        )
        if api_key:
            headers["Ocp-Apim-Subscription-Key"] = api_key

        try:
            resp = requests.get(
                EDINET_CODE_LIST_URL,
                params=params,
                headers=headers,
                timeout=60,
            )
            resp.raise_for_status()
        except requests.ConnectionError as e:
            raise NetworkError(f"EDINET API 接続エラー: {e}") from e
        except requests.Timeout as e:
            raise NetworkError(f"EDINET API タイムアウト: {e}") from e
        except requests.RequestException as e:
            raise NetworkError(f"EDINET API リクエストエラー: {e}") from e

        # ZIP を展開して CSV を取得
        try:
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
                if not csv_names:
                    raise NetworkError(
                        "EDINET API レスポンスの ZIP に CSV が含まれていません。"
                    )
                csv_bytes = zf.read(csv_names[0])
        except zipfile.BadZipFile as e:
            raise NetworkError(
                f"EDINET API レスポンスが不正な ZIP です: {e}"
            ) from e

        # Shift-JIS (cp932) → UTF-8 変換
        try:
            return csv_bytes.decode("cp932")
        except UnicodeDecodeError:
            return csv_bytes.decode("utf-8")

    @staticmethod
    def _parse_fye_month(fye_date: str) -> int | None:
        """決算日文字列から決算月を抽出する.

        対応形式: "3月31日", "3月", "12月31日", "03/31" など。
        """
        if not fye_date:
            return None
        # "M月D日" or "M月"
        m = re.search(r"(\d{1,2})月", fye_date)
        if m:
            return int(m.group(1))
        # "MM/DD"
        m = re.search(r"(\d{1,2})/\d{1,2}", fye_date)
        if m:
            return int(m.group(1))
        return None
