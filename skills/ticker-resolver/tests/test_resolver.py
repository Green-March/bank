"""ticker-resolver: TickerResolver ユニットテスト

unittest.mock + tempfile でキャッシュディレクトリを隔離。
実 API は呼ばない。
"""

from __future__ import annotations

import csv
import io
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from resolver import (
    CACHE_CSV_NAME,
    CACHE_META_NAME,
    CACHE_TTL_DAYS,
    JQUANTS_CACHE_JSON_NAME,
    CacheExpiredError,
    NetworkError,
    TickerNotFoundError,
    TickerResolver,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# EDINET CSV ヘッダー (実データ準拠)
CSV_HEADER = [
    "ＥＤＩＮＥＴコード",
    "提出者種別",
    "上場区分",
    "連結の有無",
    "資本金",
    "決算日",
    "提出者名",
    "提出者名（英字）",
    "提出者名（ヨミ）",
    "所在地",
    "提出者業種",
    "証券コード",
    "提出者法人番号",
]


def _write_cache_csv(cache_dir: Path, rows: list[dict[str, str]]) -> None:
    """テスト用 CSV をキャッシュディレクトリに書き込む."""
    csv_path = cache_dir / CACHE_CSV_NAME
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_HEADER)
    writer.writeheader()
    for row in rows:
        full = {h: "" for h in CSV_HEADER}
        full.update(row)
        writer.writerow(full)
    csv_path.write_text(buf.getvalue(), encoding="utf-8")


def _write_cache_meta(cache_dir: Path, dt: datetime | None = None) -> None:
    """キャッシュ更新タイムスタンプを書き込む."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    meta_path = cache_dir / CACHE_META_NAME
    meta_path.write_text(dt.isoformat(), encoding="utf-8")


def _make_edinet_zip_bytes(csv_text: str) -> bytes:
    """EDINET API レスポンスを模した ZIP バイト列を生成（cp932 エンコード）."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("EdinetcodeDlInfo.csv", csv_text.encode("cp932"))
    return buf.getvalue()


TOYOTA_ROW = {
    "ＥＤＩＮＥＴコード": "E02144",
    "提出者名": "トヨタ自動車株式会社",
    "証券コード": "72030",
    "上場区分": "上場",
    "決算日": "3月31日",
}

SONY_ROW = {
    "ＥＤＩＮＥＴコード": "E01777",
    "提出者名": "ソニーグループ株式会社",
    "証券コード": "67580",
    "上場区分": "上場",
    "決算日": "3月31日",
}

UNLISTED_ROW = {
    "ＥＤＩＮＥＴコード": "E99999",
    "提出者名": "非上場テスト株式会社",
    "証券コード": "99990",
    "上場区分": "非上場",
    "決算日": "12月31日",
}

DECEMBER_ROW = {
    "ＥＤＩＮＥＴコード": "E00001",
    "提出者名": "12月決算テスト株式会社",
    "証券コード": "10000",
    "上場区分": "上場",
    "決算日": "12月31日",
}


# ---------------------------------------------------------------------------
# 正常系テスト
# ---------------------------------------------------------------------------


class TestResolveNormal:
    """resolve() 正常系."""

    def test_resolve_known_ticker(self, tmp_path: Path) -> None:
        """既知銘柄（トヨタ 7203）を正常に解決できる."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        _write_cache_csv(cache_dir, [TOYOTA_ROW, SONY_ROW, UNLISTED_ROW])
        _write_cache_meta(cache_dir)

        resolver = TickerResolver(cache_dir=cache_dir)
        result = resolver.resolve("7203")

        assert result["edinet_code"] == "E02144"
        assert result["company_name"] == "トヨタ自動車株式会社"
        assert result["sec_code"] == "72030"
        assert result["fye_month"] == 3

    def test_resolve_returns_expected_keys(self, tmp_path: Path) -> None:
        """返り値に必須キー4つが含まれる."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        _write_cache_csv(cache_dir, [TOYOTA_ROW])
        _write_cache_meta(cache_dir)

        resolver = TickerResolver(cache_dir=cache_dir)
        result = resolver.resolve("7203")

        assert set(result.keys()) == {
            "edinet_code",
            "company_name",
            "sec_code",
            "fye_month",
        }


class TestUpdateCacheNormal:
    """update_cache() 正常系."""

    def test_update_cache_success(self, tmp_path: Path) -> None:
        """モック HTTP レスポンスで CSV 取得成功."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        csv_text = io.StringIO()
        writer = csv.DictWriter(csv_text, fieldnames=CSV_HEADER)
        writer.writeheader()
        full = {h: "" for h in CSV_HEADER}
        full.update(TOYOTA_ROW)
        writer.writerow(full)
        zip_bytes = _make_edinet_zip_bytes(csv_text.getvalue())

        mock_resp = MagicMock()
        mock_resp.content = zip_bytes
        mock_resp.raise_for_status = MagicMock()

        with patch("resolver.requests.get", return_value=mock_resp):
            resolver = TickerResolver(cache_dir=cache_dir)
            count = resolver.update_cache(force=True)

        assert count == 1
        assert (cache_dir / CACHE_CSV_NAME).exists()
        assert (cache_dir / CACHE_META_NAME).exists()

    def test_update_cache_force_within_ttl(self, tmp_path: Path) -> None:
        """有効期限内でも force=True で強制更新."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        _write_cache_csv(cache_dir, [TOYOTA_ROW])
        _write_cache_meta(cache_dir)  # 今（TTL 内）

        csv_text = io.StringIO()
        writer = csv.DictWriter(csv_text, fieldnames=CSV_HEADER)
        writer.writeheader()
        full = {h: "" for h in CSV_HEADER}
        full.update(TOYOTA_ROW)
        writer.writerow(full)
        full2 = {h: "" for h in CSV_HEADER}
        full2.update(SONY_ROW)
        writer.writerow(full2)
        zip_bytes = _make_edinet_zip_bytes(csv_text.getvalue())

        mock_resp = MagicMock()
        mock_resp.content = zip_bytes
        mock_resp.raise_for_status = MagicMock()

        with patch("resolver.requests.get", return_value=mock_resp):
            resolver = TickerResolver(cache_dir=cache_dir)
            count = resolver.update_cache(force=True)

        assert count == 2


class TestListAllNormal:
    """list_all() 正常系."""

    def test_list_all(self, tmp_path: Path) -> None:
        """全銘柄リストを取得."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        _write_cache_csv(cache_dir, [TOYOTA_ROW, SONY_ROW, UNLISTED_ROW])
        _write_cache_meta(cache_dir)

        resolver = TickerResolver(cache_dir=cache_dir)
        entries = resolver.list_all()

        # 非上場は除外されるので 2 件
        assert len(entries) == 2
        tickers = [e["ticker"] for e in entries]
        assert "7203" in tickers
        assert "6758" in tickers

    def test_list_all_fye_month_filter(self, tmp_path: Path) -> None:
        """fye_month フィルタテスト."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        _write_cache_csv(
            cache_dir, [TOYOTA_ROW, SONY_ROW, DECEMBER_ROW, UNLISTED_ROW]
        )
        _write_cache_meta(cache_dir)

        resolver = TickerResolver(cache_dir=cache_dir)
        march = resolver.list_all(fye_month=3)
        december = resolver.list_all(fye_month=12)

        assert len(march) == 2  # トヨタ + ソニー
        assert len(december) == 1  # 12月決算テスト


class TestLoadCacheNormal:
    """_load_cache() 正常系."""

    def test_load_cache_filters_unlisted(self, tmp_path: Path) -> None:
        """上場企業のみがフィルタされる."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        _write_cache_csv(cache_dir, [TOYOTA_ROW, UNLISTED_ROW])
        _write_cache_meta(cache_dir)

        resolver = TickerResolver(cache_dir=cache_dir)
        assert len(resolver._data) == 1
        assert resolver._data[0]["edinet_code"] == "E02144"


# ---------------------------------------------------------------------------
# 異常系テスト
# ---------------------------------------------------------------------------


class TestResolveError:
    """resolve() 異常系."""

    def test_resolve_unknown_ticker(self, tmp_path: Path) -> None:
        """存在しない ticker → TickerNotFoundError."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        _write_cache_csv(cache_dir, [TOYOTA_ROW])
        _write_cache_meta(cache_dir)

        resolver = TickerResolver(cache_dir=cache_dir)
        with pytest.raises(TickerNotFoundError, match="9999"):
            resolver.resolve("9999")

    def test_resolve_no_cache(self, tmp_path: Path) -> None:
        """キャッシュ未取得時 → CacheExpiredError."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        # CSV も meta も書かない

        resolver = TickerResolver(cache_dir=cache_dir)
        with pytest.raises(CacheExpiredError):
            resolver.resolve("7203")


class TestUpdateCacheError:
    """update_cache() 異常系."""

    def test_update_cache_network_error(self, tmp_path: Path) -> None:
        """ネットワークエラー → NetworkError."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        import requests

        with patch(
            "resolver.requests.get",
            side_effect=requests.ConnectionError("connection refused"),
        ):
            resolver = TickerResolver(cache_dir=cache_dir)
            with pytest.raises(NetworkError, match="接続エラー"):
                resolver.update_cache(force=True)


class TestParseFyeMonth:
    """_parse_fye_month() テスト."""

    def test_parse_unknown_format(self) -> None:
        """未知形式 → None 返却."""
        assert TickerResolver._parse_fye_month("不明な形式") is None
        assert TickerResolver._parse_fye_month("") is None
        assert TickerResolver._parse_fye_month("abc") is None


# ---------------------------------------------------------------------------
# エッジケーステスト
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """エッジケース."""

    def test_resolve_short_ticker(self, tmp_path: Path) -> None:
        """3桁入力 → sec_code マッチしないので TickerNotFoundError."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        _write_cache_csv(cache_dir, [TOYOTA_ROW])
        _write_cache_meta(cache_dir)

        resolver = TickerResolver(cache_dir=cache_dir)
        with pytest.raises(TickerNotFoundError):
            resolver.resolve("720")  # 3桁 → "7200" で検索、マッチしない

    def test_update_cache_skip_within_ttl(self, tmp_path: Path) -> None:
        """TTL 内は update_cache() がスキップされ 0 を返す."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        _write_cache_csv(cache_dir, [TOYOTA_ROW])
        _write_cache_meta(cache_dir)  # 現在時刻（TTL 内）

        resolver = TickerResolver(cache_dir=cache_dir)
        count = resolver.update_cache()  # force=False

        assert count == 0

    def test_load_cache_empty_csv(self, tmp_path: Path) -> None:
        """空 CSV（ヘッダーのみ）→ データ0件."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        _write_cache_csv(cache_dir, [])
        _write_cache_meta(cache_dir)

        resolver = TickerResolver(cache_dir=cache_dir)
        assert len(resolver._data) == 0

    def test_load_cache_missing_sec_code(self, tmp_path: Path) -> None:
        """証券コード空欄の行はスキップされる."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        row_no_sec = {
            "ＥＤＩＮＥＴコード": "E99998",
            "提出者名": "証券コードなし株式会社",
            "証券コード": "",
            "上場区分": "上場",
            "決算日": "3月31日",
        }
        _write_cache_csv(cache_dir, [row_no_sec, TOYOTA_ROW])
        _write_cache_meta(cache_dir)

        resolver = TickerResolver(cache_dir=cache_dir)
        assert len(resolver._data) == 1  # 証券コードなしはスキップ


# ---------------------------------------------------------------------------
# J-Quants ソーステスト
# ---------------------------------------------------------------------------

# J-Quants listed/info 形式のサンプルデータ
JQUANTS_TOYOTA = {
    "Code": "72030",
    "CompanyName": "トヨタ自動車（株）",
    "CompanyNameEnglish": "TOYOTA MOTOR CORPORATION",
    "Sector17Code": "7",
    "Sector17CodeName": "自動車・輸送機",
    "Sector33Code": "3700",
    "Sector33CodeName": "輸送用機器",
    "ScaleCategory": "TOPIX Large70",
    "MarketCode": "0111",
    "MarketCodeName": "プライム",
}

JQUANTS_KEYENCE = {
    "Code": "68610",
    "CompanyName": "（株）キーエンス",
    "CompanyNameEnglish": "KEYENCE CORPORATION",
    "Sector17Code": "12",
    "Sector17CodeName": "電機・精密",
    "Sector33Code": "3650",
    "Sector33CodeName": "電気機器",
    "ScaleCategory": "TOPIX Large70",
    "MarketCode": "0111",
    "MarketCodeName": "プライム",
}


def _write_jquants_cache(cache_dir: Path, records: list[dict]) -> None:
    """テスト用 J-Quants JSON キャッシュを書き込む."""
    import json

    jquants_path = cache_dir / JQUANTS_CACHE_JSON_NAME
    jquants_path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# 逆引きテスト
# ---------------------------------------------------------------------------


class TestResolveByEdinetCode:
    """resolve_by_edinet_code() テスト."""

    def test_resolve_by_edinet_code_found(self, tmp_path: Path) -> None:
        """既知の EDINETコードから銘柄を逆引きできる."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        _write_cache_csv(cache_dir, [TOYOTA_ROW, SONY_ROW])
        _write_cache_meta(cache_dir)

        resolver = TickerResolver(cache_dir=cache_dir)
        result = resolver.resolve_by_edinet_code("E02144")

        assert result["ticker"] == "7203"
        assert result["edinet_code"] == "E02144"
        assert result["company_name"] == "トヨタ自動車株式会社"
        assert result["sec_code"] == "72030"
        assert result["fye_month"] == 3

    def test_resolve_by_edinet_code_not_found(self, tmp_path: Path) -> None:
        """存在しない EDINETコード → TickerNotFoundError."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        _write_cache_csv(cache_dir, [TOYOTA_ROW])
        _write_cache_meta(cache_dir)

        resolver = TickerResolver(cache_dir=cache_dir)
        with pytest.raises(TickerNotFoundError, match="E99999"):
            resolver.resolve_by_edinet_code("E99999")

    def test_resolve_by_edinet_code_no_cache(self, tmp_path: Path) -> None:
        """キャッシュ未取得時 → CacheExpiredError."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        resolver = TickerResolver(cache_dir=cache_dir)
        with pytest.raises(CacheExpiredError):
            resolver.resolve_by_edinet_code("E02144")


class TestResolveByCompanyName:
    """resolve_by_company_name() テスト."""

    def test_resolve_by_company_name_exact(self, tmp_path: Path) -> None:
        """完全一致で企業を逆引きできる."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        _write_cache_csv(cache_dir, [TOYOTA_ROW, SONY_ROW])
        _write_cache_meta(cache_dir)

        resolver = TickerResolver(cache_dir=cache_dir)
        results = resolver.resolve_by_company_name("トヨタ自動車株式会社")

        assert len(results) == 1
        assert results[0]["ticker"] == "7203"
        assert results[0]["company_name"] == "トヨタ自動車株式会社"

    def test_resolve_by_company_name_partial(self, tmp_path: Path) -> None:
        """部分一致で企業を逆引きできる."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        _write_cache_csv(cache_dir, [TOYOTA_ROW, SONY_ROW])
        _write_cache_meta(cache_dir)

        resolver = TickerResolver(cache_dir=cache_dir)
        results = resolver.resolve_by_company_name("トヨタ")

        assert len(results) == 1
        assert results[0]["ticker"] == "7203"

    def test_resolve_by_company_name_multiple(self, tmp_path: Path) -> None:
        """複数マッチ: 「株式会社」で全銘柄がマッチする."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        _write_cache_csv(cache_dir, [TOYOTA_ROW, SONY_ROW, DECEMBER_ROW])
        _write_cache_meta(cache_dir)

        resolver = TickerResolver(cache_dir=cache_dir)
        results = resolver.resolve_by_company_name("株式会社")

        assert len(results) == 3

    def test_resolve_by_company_name_no_match(self, tmp_path: Path) -> None:
        """マッチなし → 空リスト."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        _write_cache_csv(cache_dir, [TOYOTA_ROW])
        _write_cache_meta(cache_dir)

        resolver = TickerResolver(cache_dir=cache_dir)
        results = resolver.resolve_by_company_name("存在しない企業")

        assert results == []

    def test_resolve_by_company_name_case_insensitive(self, tmp_path: Path) -> None:
        """大文字小文字を区別しない（英字混在ケース）."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        _write_jquants_cache(cache_dir, [JQUANTS_KEYENCE])
        _write_cache_meta(cache_dir)

        resolver = TickerResolver(cache_dir=cache_dir)
        results = resolver.resolve_by_company_name("キーエンス")

        assert len(results) == 1
        assert results[0]["ticker"] == "6861"

    def test_resolve_by_company_name_no_cache(self, tmp_path: Path) -> None:
        """キャッシュ未取得時 → CacheExpiredError."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        resolver = TickerResolver(cache_dir=cache_dir)
        with pytest.raises(CacheExpiredError):
            resolver.resolve_by_company_name("トヨタ")


class TestJQuantsLoadCache:
    """J-Quants キャッシュ読み込みテスト."""

    def test_load_jquants_only(self, tmp_path: Path) -> None:
        """J-Quants JSON のみでキャッシュを読み込む."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        _write_jquants_cache(cache_dir, [JQUANTS_TOYOTA, JQUANTS_KEYENCE])
        _write_cache_meta(cache_dir)

        resolver = TickerResolver(cache_dir=cache_dir)
        assert len(resolver._data) == 2

        # J-Quants のみの場合、edinet_code は空、fye_month は None
        result = resolver.resolve("7203")
        assert result["company_name"] == "トヨタ自動車（株）"
        assert result["edinet_code"] == ""
        assert result["fye_month"] is None

    def test_load_jquants_merge_with_edinet(self, tmp_path: Path) -> None:
        """EDINET + J-Quants のマージ: EDINET 優先、J-Quants 固有銘柄も追加."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        _write_cache_csv(cache_dir, [TOYOTA_ROW, SONY_ROW])
        _write_jquants_cache(cache_dir, [JQUANTS_TOYOTA, JQUANTS_KEYENCE])
        _write_cache_meta(cache_dir)

        resolver = TickerResolver(cache_dir=cache_dir)
        # トヨタ(EDINET+J-Quants) + ソニー(EDINETのみ) + キーエンス(J-Quantsのみ)
        assert len(resolver._data) == 3

        # EDINET 側データが優先される
        toyota = resolver.resolve("7203")
        assert toyota["edinet_code"] == "E02144"
        assert toyota["company_name"] == "トヨタ自動車株式会社"  # EDINET側
        assert toyota["fye_month"] == 3

        # J-Quants のみの銘柄
        keyence = resolver.resolve("6861")
        assert keyence["edinet_code"] == ""
        assert keyence["company_name"] == "（株）キーエンス"
        assert keyence["fye_month"] is None

    def test_load_jquants_empty_code_skipped(self, tmp_path: Path) -> None:
        """Code が空の J-Quants レコードはスキップされる."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        _write_jquants_cache(
            cache_dir,
            [{"Code": "", "CompanyName": "テスト"}, JQUANTS_KEYENCE],
        )
        _write_cache_meta(cache_dir)

        resolver = TickerResolver(cache_dir=cache_dir)
        assert len(resolver._data) == 1

    def test_load_jquants_invalid_json(self, tmp_path: Path) -> None:
        """不正な JSON ファイルはスキップされる."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        jquants_path = cache_dir / JQUANTS_CACHE_JSON_NAME
        jquants_path.write_text("invalid json{{{", encoding="utf-8")
        _write_cache_meta(cache_dir)

        resolver = TickerResolver(cache_dir=cache_dir)
        assert len(resolver._data) == 0


class TestJQuantsUpdateCache:
    """update_cache() J-Quants ソーステスト."""

    def test_update_cache_jquants_source(self, tmp_path: Path) -> None:
        """source='jquants' で J-Quants API から取得成功."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        mock_jquants_resp = MagicMock()
        mock_jquants_resp.json.return_value = {
            "info": [JQUANTS_TOYOTA, JQUANTS_KEYENCE]
        }
        mock_jquants_resp.raise_for_status = MagicMock()

        with (
            patch(
                "resolver.TickerResolver._download_jquants_listed_info",
                return_value=[JQUANTS_TOYOTA, JQUANTS_KEYENCE],
            ),
        ):
            resolver = TickerResolver(cache_dir=cache_dir)
            count = resolver.update_cache(source="jquants", force=True)

        assert count == 2
        assert (cache_dir / JQUANTS_CACHE_JSON_NAME).exists()
        assert (cache_dir / CACHE_META_NAME).exists()

    def test_update_cache_jquants_auth_error(self, tmp_path: Path) -> None:
        """source='jquants' で認証エラー → NetworkError."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        with patch(
            "resolver.TickerResolver._download_jquants_listed_info",
            side_effect=NetworkError("J-Quants 認証エラー"),
        ):
            resolver = TickerResolver(cache_dir=cache_dir)
            with pytest.raises(NetworkError, match="認証エラー"):
                resolver.update_cache(source="jquants", force=True)

    def test_update_cache_all_jquants_failure_is_best_effort(
        self, tmp_path: Path
    ) -> None:
        """source='all' で J-Quants 失敗時は EDINET のみで成功する."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        csv_text = io.StringIO()
        writer = csv.DictWriter(csv_text, fieldnames=CSV_HEADER)
        writer.writeheader()
        full = {h: "" for h in CSV_HEADER}
        full.update(TOYOTA_ROW)
        writer.writerow(full)
        zip_bytes = _make_edinet_zip_bytes(csv_text.getvalue())

        mock_edinet_resp = MagicMock()
        mock_edinet_resp.content = zip_bytes
        mock_edinet_resp.raise_for_status = MagicMock()

        with (
            patch("resolver.requests.get", return_value=mock_edinet_resp),
            patch(
                "resolver.TickerResolver._download_jquants_listed_info",
                side_effect=NetworkError("J-Quants 認証エラー"),
            ),
        ):
            resolver = TickerResolver(cache_dir=cache_dir)
            count = resolver.update_cache(source="all", force=True)

        assert count == 1  # EDINET のみ
        assert (cache_dir / CACHE_CSV_NAME).exists()

    def test_update_cache_all_both_success(self, tmp_path: Path) -> None:
        """source='all' で EDINET + J-Quants 両方成功 → マージ結果."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        csv_text = io.StringIO()
        writer = csv.DictWriter(csv_text, fieldnames=CSV_HEADER)
        writer.writeheader()
        full = {h: "" for h in CSV_HEADER}
        full.update(TOYOTA_ROW)
        writer.writerow(full)
        zip_bytes = _make_edinet_zip_bytes(csv_text.getvalue())

        mock_edinet_resp = MagicMock()
        mock_edinet_resp.content = zip_bytes
        mock_edinet_resp.raise_for_status = MagicMock()

        with (
            patch("resolver.requests.get", return_value=mock_edinet_resp),
            patch(
                "resolver.TickerResolver._download_jquants_listed_info",
                return_value=[JQUANTS_TOYOTA, JQUANTS_KEYENCE],
            ),
        ):
            resolver = TickerResolver(cache_dir=cache_dir)
            count = resolver.update_cache(source="all", force=True)

        # トヨタ(マージ) + キーエンス(J-Quantsのみ) = 2
        assert count == 2
        assert (cache_dir / CACHE_CSV_NAME).exists()
        assert (cache_dir / JQUANTS_CACHE_JSON_NAME).exists()

    def test_update_cache_invalid_source(self, tmp_path: Path) -> None:
        """不正な source 値 → ValueError."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        resolver = TickerResolver(cache_dir=cache_dir)
        with pytest.raises(ValueError, match="不正な source"):
            resolver.update_cache(source="invalid", force=True)


class TestJQuantsDownload:
    """_download_jquants_listed_info() テスト."""

    def test_download_jquants_connection_error(self, tmp_path: Path) -> None:
        """J-Quants API 接続エラー → NetworkError."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        mock_auth_instance = MagicMock()
        mock_auth_instance.get_id_token.return_value = "test_token"

        with (
            patch(
                "resolver.TickerResolver._download_jquants_listed_info",
                side_effect=NetworkError("J-Quants API 接続エラー"),
            ),
        ):
            resolver = TickerResolver(cache_dir=cache_dir)
            with pytest.raises(NetworkError, match="接続エラー"):
                resolver.update_cache(source="jquants", force=True)

    def test_download_jquants_import_error(self, tmp_path: Path) -> None:
        """skills.common.auth がインポートできない → NetworkError."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        with patch(
            "resolver.TickerResolver._download_jquants_listed_info",
            side_effect=NetworkError("J-Quants 認証モジュールが利用できません"),
        ):
            resolver = TickerResolver(cache_dir=cache_dir)
            with pytest.raises(NetworkError, match="認証モジュール"):
                resolver.update_cache(source="jquants", force=True)
