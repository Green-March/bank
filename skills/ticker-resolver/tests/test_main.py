"""ticker-resolver: CLI (main.py) 統合テスト

subprocess.run で main.py を直接実行し、exit code / stdout / stderr を検証する。
update サブコマンドのモックテストは一時ラッパースクリプト経由で実行。
"""

from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
import textwrap
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
MAIN_PY = SCRIPT_DIR / "main.py"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# EDINET CSV ヘッダー
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

DECEMBER_ROW = {
    "ＥＤＩＮＥＴコード": "E00001",
    "提出者名": "12月決算テスト株式会社",
    "証券コード": "10000",
    "上場区分": "上場",
    "決算日": "12月31日",
}


def _write_cache_csv(cache_dir: Path, rows: list[dict[str, str]]) -> None:
    """テスト用 CSV をキャッシュディレクトリに書き込む."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_HEADER)
    writer.writeheader()
    for row in rows:
        full = {h: "" for h in CSV_HEADER}
        full.update(row)
        writer.writerow(full)
    (cache_dir / "EdinetcodeDlInfo.csv").write_text(
        buf.getvalue(), encoding="utf-8"
    )


def _write_cache_meta(cache_dir: Path) -> None:
    """キャッシュ更新タイムスタンプを書き込む（現在時刻 = TTL 内）."""
    (cache_dir / ".cache_updated_at").write_text(
        datetime.now(timezone.utc).isoformat(), encoding="utf-8"
    )


def _setup_cache(tmp_path: Path, rows: list[dict[str, str]]) -> Path:
    """テスト用キャッシュディレクトリを準備して返す."""
    cache_dir = tmp_path / ".ticker_cache"
    cache_dir.mkdir(parents=True)
    _write_cache_csv(cache_dir, rows)
    _write_cache_meta(cache_dir)
    return cache_dir


def _run_main(
    args: list[str],
    *,
    data_path: str | None = None,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """main.py を subprocess で実行."""
    env = os.environ.copy()
    if data_path:
        env["DATA_PATH"] = data_path
    if env_extra:
        env.update(env_extra)

    return subprocess.run(
        [sys.executable, str(MAIN_PY)] + args,
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=30,
    )


def _make_edinet_zip_bytes(csv_text: str) -> bytes:
    """EDINET API レスポンスを模した ZIP バイト列を生成（cp932 エンコード）."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("EdinetcodeDlInfo.csv", csv_text.encode("cp932"))
    return buf.getvalue()


def _make_csv_text(rows: list[dict[str, str]]) -> str:
    """テスト行リストから CSV テキストを生成."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_HEADER)
    writer.writeheader()
    for row in rows:
        full = {h: "" for h in CSV_HEADER}
        full.update(row)
        writer.writerow(full)
    return buf.getvalue()


def _run_with_mock(
    tmp_path: Path,
    cli_args: list[str],
    *,
    mock_zip_bytes: bytes | None = None,
    mock_error: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """一時ラッパースクリプトを介して main.py をモック付きで実行.

    subprocess 内でネットワークモックを適用するために、
    一時 Python スクリプトを生成して実行する。
    """
    script_dir_str = str(SCRIPT_DIR).replace("\\", "\\\\")

    main_py_str = str(MAIN_PY).replace("\\", "\\\\")

    lines = [
        "import sys, os, runpy",
        f'sys.path.insert(0, r"{script_dir_str}")',
        f'os.environ["DATA_PATH"] = r"{str(tmp_path)}"',
        "import resolver",  # pre-import to enable patching
    ]

    if mock_zip_bytes is not None:
        import base64

        zip_b64 = base64.b64encode(mock_zip_bytes).decode("ascii")
        lines += [
            "import base64",
            "from unittest.mock import MagicMock, patch",
            "mock_resp = MagicMock()",
            f'mock_resp.content = base64.b64decode("{zip_b64}")',
            "mock_resp.raise_for_status = MagicMock()",
            'patcher = patch("resolver.requests.get", return_value=mock_resp)',
            "patcher.start()",
        ]
    elif mock_error is not None:
        lines += [
            "import requests",
            "from unittest.mock import patch",
            "patcher = patch(",
            '    "resolver.requests.get",',
            f'    side_effect=requests.ConnectionError("{mock_error}"),',
            ")",
            "patcher.start()",
        ]

    lines += [
        f'runpy.run_path(r"{main_py_str}", run_name="__main__")',
    ]

    wrapper_path = tmp_path / "_test_wrapper.py"
    wrapper_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return subprocess.run(
        [sys.executable, str(wrapper_path)] + cli_args,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# resolve サブコマンド
# ---------------------------------------------------------------------------


class TestResolveSubcommand:
    """resolve サブコマンドのテスト."""

    def test_resolve_json_output(self, tmp_path: Path) -> None:
        """正常系: resolve 7203 → JSON 出力."""
        _setup_cache(tmp_path, [TOYOTA_ROW])
        result = _run_main(["resolve", "7203"], data_path=str(tmp_path))

        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["edinet_code"] == "E02144"
        assert data["company_name"] == "トヨタ自動車株式会社"
        assert data["sec_code"] == "72030"
        assert data["fye_month"] == 3

    def test_resolve_text_output(self, tmp_path: Path) -> None:
        """--format text: テキスト形式出力確認."""
        _setup_cache(tmp_path, [TOYOTA_ROW])
        result = _run_main(
            ["resolve", "7203", "--format", "text"], data_path=str(tmp_path)
        )

        assert result.returncode == 0
        assert "トヨタ自動車株式会社" in result.stdout
        assert "E02144" in result.stdout
        assert "3月" in result.stdout

    def test_resolve_unknown_ticker(self, tmp_path: Path) -> None:
        """異常系: 存在しない ticker → exit code 1 + stderr メッセージ."""
        _setup_cache(tmp_path, [TOYOTA_ROW])
        result = _run_main(["resolve", "9999"], data_path=str(tmp_path))

        assert result.returncode == 1
        assert "エラー" in result.stderr

    def test_resolve_no_cache(self, tmp_path: Path) -> None:
        """異常系: キャッシュなし → exit code 1 + CacheExpiredError メッセージ."""
        empty_data = tmp_path / "empty"
        empty_data.mkdir()
        result = _run_main(["resolve", "7203"], data_path=str(empty_data))

        assert result.returncode == 1
        assert "キャッシュ" in result.stderr or "エラー" in result.stderr


# ---------------------------------------------------------------------------
# update サブコマンド
# ---------------------------------------------------------------------------


class TestUpdateSubcommand:
    """update サブコマンドのテスト."""

    def test_update_success(self, tmp_path: Path) -> None:
        """正常系: update → 成功メッセージ + exit code 0."""
        zip_bytes = _make_edinet_zip_bytes(_make_csv_text([TOYOTA_ROW]))
        result = _run_with_mock(
            tmp_path,
            ["update", "--force"],
            mock_zip_bytes=zip_bytes,
        )

        assert result.returncode == 0
        assert "更新しました" in result.stdout

    def test_update_force(self, tmp_path: Path) -> None:
        """--force: 有効期限内でも強制更新."""
        _setup_cache(tmp_path, [TOYOTA_ROW])
        zip_bytes = _make_edinet_zip_bytes(
            _make_csv_text([TOYOTA_ROW, SONY_ROW])
        )
        result = _run_with_mock(
            tmp_path,
            ["update", "--force"],
            mock_zip_bytes=zip_bytes,
        )

        assert result.returncode == 0
        assert "更新しました" in result.stdout

    def test_update_network_error(self, tmp_path: Path) -> None:
        """異常系: ネットワークエラー → exit code 1."""
        result = _run_with_mock(
            tmp_path,
            ["update", "--force"],
            mock_error="connection refused",
        )

        assert result.returncode == 1
        assert "エラー" in result.stderr


# ---------------------------------------------------------------------------
# list サブコマンド
# ---------------------------------------------------------------------------


class TestListSubcommand:
    """list サブコマンドのテスト."""

    def test_list_text_output(self, tmp_path: Path) -> None:
        """正常系: list → テーブル風出力."""
        _setup_cache(tmp_path, [TOYOTA_ROW, SONY_ROW])
        result = _run_main(["list"], data_path=str(tmp_path))

        assert result.returncode == 0
        assert "7203" in result.stdout
        assert "6758" in result.stdout
        assert "合計" in result.stdout

    def test_list_json_output(self, tmp_path: Path) -> None:
        """--format json: JSON 配列出力確認."""
        _setup_cache(tmp_path, [TOYOTA_ROW, SONY_ROW])
        result = _run_main(
            ["list", "--format", "json"], data_path=str(tmp_path)
        )

        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) == 2

    def test_list_fye_month_filter(self, tmp_path: Path) -> None:
        """--fye-month 3: 決算月フィルタ動作確認."""
        _setup_cache(tmp_path, [TOYOTA_ROW, DECEMBER_ROW])
        result = _run_main(
            ["list", "--format", "json", "--fye-month", "3"],
            data_path=str(tmp_path),
        )

        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert len(data) == 1
        assert data[0]["fye_month"] == 3


# ---------------------------------------------------------------------------
# その他
# ---------------------------------------------------------------------------


class TestCLIMisc:
    """CLI その他テスト."""

    def test_no_args_shows_error(self) -> None:
        """引数なし実行時 → exit code != 0."""
        result = _run_main([])
        assert result.returncode != 0

    def test_invalid_subcommand(self) -> None:
        """不正サブコマンド → exit code != 0."""
        result = _run_main(["invalid_command"])
        assert result.returncode != 0
