"""CLI 引数パースのユニットテスト"""

from datetime import date, timedelta

import pytest

from scripts.main import build_parser, _parse_iso_date


# ============================================================
# CLI 引数パーステスト
# ============================================================


class TestBuildParser:
    """--ticker, --from-date, --to-date, --output-dir のパーステスト"""

    def test_all_args(self):
        parser = build_parser()
        args = parser.parse_args(
            ["--ticker", "7203", "--from-date", "2025-01-01",
             "--to-date", "2025-06-30", "--output-dir", "/tmp/out"]
        )
        assert args.ticker == "7203"
        assert args.from_date == date(2025, 1, 1)
        assert args.to_date == date(2025, 6, 30)
        assert args.output_dir == "/tmp/out"

    def test_ticker_only(self):
        parser = build_parser()
        args = parser.parse_args(["--ticker", "6758"])
        assert args.ticker == "6758"
        assert args.from_date is None
        assert args.to_date is None
        assert args.output_dir is None


class TestDefaultValues:
    """デフォルト値テスト（from-date=1年前, to-date=今日）"""

    def test_defaults_applied_in_main(self):
        parser = build_parser()
        args = parser.parse_args(["--ticker", "7203"])

        today = date.today()
        from_date = args.from_date if args.from_date else today - timedelta(days=365)
        to_date = args.to_date if args.to_date else today

        assert from_date == today - timedelta(days=365)
        assert to_date == today


class TestInvalidArgs:
    """不正引数テスト"""

    def test_missing_ticker(self):
        parser = build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args([])
        assert exc_info.value.code == 2

    def test_invalid_from_date_format(self):
        parser = build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--ticker", "7203", "--from-date", "2025/01/01"])
        assert exc_info.value.code == 2

    def test_invalid_to_date_format(self):
        parser = build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--ticker", "7203", "--to-date", "not-a-date"])
        assert exc_info.value.code == 2


class TestParseIsoDate:
    """_parse_iso_date ヘルパーのテスト"""

    def test_valid_date(self):
        assert _parse_iso_date("2025-06-15") == date(2025, 6, 15)

    def test_invalid_date(self):
        import argparse
        with pytest.raises(argparse.ArgumentTypeError, match="日付形式が不正"):
            _parse_iso_date("not-a-date")
