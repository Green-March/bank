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
