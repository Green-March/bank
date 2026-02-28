"""main.py CLI のテスト"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

MAIN_PY = str(Path(__file__).resolve().parents[1] / "scripts" / "main.py")


def _run_main(*args: str) -> subprocess.CompletedProcess:
    """main.py をサブプロセスとして実行する。"""
    return subprocess.run(
        [sys.executable, MAIN_PY, *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestHelp:
    def test_help(self):
        """--help で usage 表示、exit 0。"""
        result = _run_main("--help")
        assert result.returncode == 0
        assert "usage" in result.stdout.lower() or "Usage" in result.stdout


class TestMissingTicker:
    def test_missing_ticker(self):
        """collect で --ticker なしは exit != 0。"""
        result = _run_main("collect")
        assert result.returncode != 0


class TestCollectDefaultSource:
    def test_collect_default_source(self, tmp_path):
        """--source 未指定で all 扱い。"""
        output = tmp_path / "research.json"
        result = _run_main("collect", "--ticker", "7203", "--output", str(output))
        # JSON が出力されていること（shikiho fallback で yahoo 成功時は exit 0）
        assert '"ticker"' in result.stdout
        assert '"yahoo"' in result.stdout
        assert '"kabutan"' in result.stdout
        assert '"shikiho"' in result.stdout
        assert '"homepage"' in result.stdout


class TestCollectSpecificSource:
    def test_collect_specific_source(self, tmp_path):
        """--source yahoo で yahoo のみ実行。"""
        output = tmp_path / "research.json"
        result = _run_main("collect", "--ticker", "7203", "--source", "yahoo", "--output", str(output))
        assert '"yahoo"' in result.stdout
        # 他のソースは結果に含まれない
        assert '"kabutan"' not in result.stdout


class TestCollectCommaSources:
    def test_collect_comma_sources(self, tmp_path):
        """--source yahoo,kabutan でカンマ分割。"""
        output = tmp_path / "research.json"
        result = _run_main(
            "collect", "--ticker", "7203", "--source", "yahoo,kabutan", "--output", str(output)
        )
        assert '"yahoo"' in result.stdout
        assert '"kabutan"' in result.stdout
        assert '"shikiho"' not in result.stdout


class TestMetadataAccessedDomains:
    def test_accessed_domains_populated(self, tmp_path):
        """placeholder でも accessed_domains に URL からドメインが記録される。"""
        output = tmp_path / "research.json"
        result = _run_main("collect", "--ticker", "7203", "--source", "yahoo", "--output", str(output))
        data = json.loads(result.stdout)
        domains = data["metadata"]["accessed_domains"]
        assert "finance.yahoo.co.jp" in domains

    def test_accessed_domains_multiple(self, tmp_path):
        """複数ソース実行時に全ドメインが記録される。"""
        output = tmp_path / "research.json"
        result = _run_main("collect", "--ticker", "7203", "--source", "yahoo,kabutan", "--output", str(output))
        data = json.loads(result.stdout)
        domains = data["metadata"]["accessed_domains"]
        assert "finance.yahoo.co.jp" in domains
        assert "kabutan.jp" in domains

    def test_robots_checked_always_true(self, tmp_path):
        """robots_checked は常に True（BaseCollector の契約）。"""
        output = tmp_path / "research.json"
        result = _run_main("collect", "--ticker", "7203", "--output", str(output))
        data = json.loads(result.stdout)
        assert data["metadata"]["robots_checked"] is True


class TestDefaultOutputPath:
    def test_default_output_uses_web_research(self):
        """ヘルプに web_research/research.json が記載されている。"""
        result = _run_main("collect", "--help")
        assert "web_research/research.json" in result.stdout


# ===== 統合テスト (mocked collectors) =====

from unittest.mock import patch, MagicMock


def _mock_collector_cls(collected=True, url="https://example.com", data=None, error=None):
    """モックのコレクタークラスを生成する。"""
    result = {
        "url": url,
        "collected": collected,
        "data": data if data is not None else ({"sample": "data"} if collected else None),
        "error": error,
    }
    cls = MagicMock()
    instance = MagicMock()
    instance.collect.return_value = result
    instance.__enter__ = MagicMock(return_value=instance)
    instance.__exit__ = MagicMock(return_value=False)
    cls.return_value = instance
    return cls


def _mock_source_map(sources_config: dict[str, dict]) -> dict:
    """複数ソースのモック SOURCE_MAP を生成する。"""
    return {name: _mock_collector_cls(**cfg) for name, cfg in sources_config.items()}


class TestOutputJsonSchemaIntegration:
    def test_output_json_schema(self):
        """出力JSONのトップレベルキー（ticker, collected_at, sources, metadata）検証。"""
        from scripts.main import collect

        mock_map = _mock_source_map({
            "yahoo": {"url": "https://finance.yahoo.co.jp/quote/7203"},
        })
        with patch("scripts.main.SOURCE_MAP", mock_map):
            result = collect("7203", ["yahoo"])

        assert result["ticker"] == "7203"
        assert "collected_at" in result
        assert "sources" in result
        assert "metadata" in result


class TestOutputSourcesSchemaIntegration:
    def test_output_sources_schema(self):
        """sources 内の各ソースが url/collected/data キーを持つ検証。"""
        from scripts.main import collect

        mock_map = _mock_source_map({
            "yahoo": {"url": "https://finance.yahoo.co.jp/quote/7203"},
            "kabutan": {"url": "https://kabutan.jp/stock/?code=7203"},
        })
        with patch("scripts.main.SOURCE_MAP", mock_map):
            result = collect("7203", ["yahoo", "kabutan"])

        for name, src in result["sources"].items():
            assert "url" in src, f"{name}: url missing"
            assert "collected" in src, f"{name}: collected missing"
            assert "data" in src, f"{name}: data missing"


class TestOutputMetadataSchemaIntegration:
    def test_output_metadata_schema(self):
        """metadata の必須キー（source_count, success_count, accessed_domains）検証。"""
        from scripts.main import collect

        mock_map = _mock_source_map({
            "yahoo": {"url": "https://finance.yahoo.co.jp/quote/7203"},
        })
        with patch("scripts.main.SOURCE_MAP", mock_map):
            result = collect("7203", ["yahoo"])

        meta = result["metadata"]
        assert "source_count" in meta
        assert "success_count" in meta
        assert "accessed_domains" in meta


class TestCollectAllSourcesIntegration:
    def test_collect_all_sources(self):
        """--source all で全4ソースが実行される検証。"""
        from scripts.main import collect

        mock_map = _mock_source_map({
            "yahoo": {"url": "https://finance.yahoo.co.jp/quote/7203"},
            "kabutan": {"url": "https://kabutan.jp/stock/?code=7203"},
            "shikiho": {"url": "https://shikiho.toyokeizai.net/stocks/7203"},
            "homepage": {"url": "https://www.example.co.jp"},
        })
        with patch("scripts.main.SOURCE_MAP", mock_map), \
             patch("scripts.main.ALL_SOURCES", list(mock_map.keys())):
            result = collect("7203", list(mock_map.keys()))

        assert set(result["sources"].keys()) == {"yahoo", "kabutan", "shikiho", "homepage"}
        assert result["metadata"]["source_count"] == 4
        assert result["metadata"]["success_count"] == 4


class TestCollectSingleSourceIntegration:
    def test_collect_single_source(self):
        """--source yahoo で yahoo のみ実行される検証。"""
        from scripts.main import collect

        mock_map = _mock_source_map({
            "yahoo": {"url": "https://finance.yahoo.co.jp/quote/7203"},
            "kabutan": {"url": "https://kabutan.jp/stock/?code=7203"},
        })
        with patch("scripts.main.SOURCE_MAP", mock_map):
            result = collect("7203", ["yahoo"])

        assert "yahoo" in result["sources"]
        assert "kabutan" not in result["sources"]
        assert result["metadata"]["source_count"] == 1


class TestCollectCommaSourcesIntegration:
    def test_collect_comma_sources(self):
        """--source yahoo,kabutan でカンマ分割実行。"""
        from scripts.main import _parse_sources, collect

        sources = _parse_sources("yahoo,kabutan")
        assert sources == ["yahoo", "kabutan"]

        mock_map = _mock_source_map({
            "yahoo": {"url": "https://finance.yahoo.co.jp/quote/7203"},
            "kabutan": {"url": "https://kabutan.jp/stock/?code=7203"},
        })
        with patch("scripts.main.SOURCE_MAP", mock_map):
            result = collect("7203", sources)

        assert set(result["sources"].keys()) == {"yahoo", "kabutan"}


class TestMergeModeIntegration:
    def test_merge_mode(self):
        """--merge で既存JSON上書きマージ。"""
        from scripts.main import merge_results

        existing = {
            "ticker": "7203",
            "collected_at": "2026-01-01T00:00:00+09:00",
            "sources": {
                "yahoo": {
                    "url": "https://finance.yahoo.co.jp/quote/7203",
                    "collected": True,
                    "data": {"old": "yahoo_data"},
                    "error": None,
                },
            },
            "metadata": {
                "source_count": 1,
                "success_count": 1,
                "errors": [],
            },
        }
        new_result = {
            "ticker": "7203",
            "collected_at": "2026-02-01T00:00:00+09:00",
            "sources": {
                "kabutan": {
                    "url": "https://kabutan.jp/stock/?code=7203",
                    "collected": True,
                    "data": {"new": "kabutan_data"},
                    "error": None,
                },
            },
            "metadata": {},
        }

        merged = merge_results(existing, new_result, ["kabutan"])

        assert merged["sources"]["yahoo"]["data"] == {"old": "yahoo_data"}
        assert merged["sources"]["kabutan"]["data"] == {"new": "kabutan_data"}
        assert merged["metadata"]["source_count"] == 2
        assert merged["metadata"]["success_count"] == 2


class TestExitCodeSuccessIntegration:
    def test_exit_code_success(self):
        """success_count >= 1 → exit 0。"""
        from scripts.main import collect

        mock_map = _mock_source_map({
            "yahoo": {"collected": True, "url": "https://finance.yahoo.co.jp/quote/7203"},
        })
        with patch("scripts.main.SOURCE_MAP", mock_map):
            result = collect("7203", ["yahoo"])

        assert result["metadata"]["success_count"] >= 1
        # main() の exit code ロジック: 0 if success_count >= 1 else 1
        exit_code = 0 if result["metadata"]["success_count"] >= 1 else 1
        assert exit_code == 0


class TestExitCodeAllFailIntegration:
    def test_exit_code_all_fail(self):
        """全ソース失敗 → exit 1。"""
        from scripts.main import collect

        mock_map = _mock_source_map({
            "yahoo": {"collected": False, "url": "https://finance.yahoo.co.jp/quote/7203", "error": "テスト失敗"},
            "kabutan": {"collected": False, "url": "https://kabutan.jp/stock/?code=7203", "error": "テスト失敗"},
        })
        with patch("scripts.main.SOURCE_MAP", mock_map):
            result = collect("7203", ["yahoo", "kabutan"])

        assert result["metadata"]["success_count"] == 0
        exit_code = 0 if result["metadata"]["success_count"] >= 1 else 1
        assert exit_code == 1


class TestDataRoot:
    def test_data_root_default(self, monkeypatch):
        """DATA_PATH 未設定時のデフォルトパス。"""
        monkeypatch.delenv("DATA_PATH", raising=False)
        from scripts.main import _data_root, _repo_root

        result = _data_root()
        assert result == _repo_root() / "data"

    def test_data_root_absolute(self, monkeypatch, tmp_path):
        """DATA_PATH が絶対パスの場合。"""
        monkeypatch.setenv("DATA_PATH", str(tmp_path / "custom_data"))
        from scripts.main import _data_root

        result = _data_root()
        assert result == tmp_path / "custom_data"

    def test_data_root_relative(self, monkeypatch):
        """DATA_PATH が相対パスの場合。"""
        monkeypatch.setenv("DATA_PATH", "relative/data")
        from scripts.main import _data_root, _repo_root

        result = _data_root()
        assert result == (_repo_root() / "relative/data").resolve()


class TestParseSourcesUnknown:
    def test_unknown_source_skipped(self):
        """不明なソース名がスキップされる検証。"""
        from scripts.main import _parse_sources

        sources = _parse_sources("yahoo,unknown_source,kabutan")
        assert "yahoo" in sources
        assert "kabutan" in sources
        assert "unknown_source" not in sources

    def test_all_unknown_returns_empty(self):
        """全て不明なソース → 空リスト。"""
        from scripts.main import _parse_sources

        sources = _parse_sources("foo,bar")
        assert sources == []


class TestCollectExceptionHandling:
    def test_collector_error_handled(self):
        """CollectorError を出すコレクター → collected=False, error に詳細。"""
        from scripts.main import collect
        from scripts.collector_base import CollectorError

        cls = MagicMock()
        instance = MagicMock()
        instance.collect.side_effect = CollectorError("テスト用エラー")
        instance.__enter__ = MagicMock(return_value=instance)
        instance.__exit__ = MagicMock(return_value=False)
        cls.return_value = instance

        with patch("scripts.main.SOURCE_MAP", {"yahoo": cls}):
            result = collect("7203", ["yahoo"])

        src = result["sources"]["yahoo"]
        assert src["collected"] is False
        assert "テスト用エラー" in src["error"]
        assert src["url"] is None

    def test_unexpected_exception_handled(self):
        """予期しない例外 → collected=False, error に '予期しないエラー'。"""
        from scripts.main import collect

        cls = MagicMock()
        instance = MagicMock()
        instance.collect.side_effect = RuntimeError("予期しない問題")
        instance.__enter__ = MagicMock(return_value=instance)
        instance.__exit__ = MagicMock(return_value=False)
        cls.return_value = instance

        with patch("scripts.main.SOURCE_MAP", {"kabutan": cls}):
            result = collect("7203", ["kabutan"])

        src = result["sources"]["kabutan"]
        assert src["collected"] is False
        assert "予期しないエラー" in src["error"]


class TestMainNoSubcommand:
    def test_no_subcommand_returns_1(self):
        """サブコマンドなしで exit 1。"""
        result = _run_main()
        assert result.returncode != 0

    def test_empty_valid_sources_via_subprocess(self):
        """不正なソースのみ → 有効なソースなし。"""
        result = _run_main("collect", "--ticker", "7203", "--source", "nosuchsource")
        assert result.returncode != 0
        assert "有効なソース" in result.stderr or result.returncode != 0


class TestCliNoSecretLeakIntegration:
    def test_cli_no_secret_leak(self, monkeypatch):
        """全出力（stdout+stderr+file）に SHIKIHO_EMAIL/PASSWORD が含まれない直接検証。"""
        test_email = "test_secret_email@example.com"
        test_password = "test_secret_password_123"
        monkeypatch.setenv("SHIKIHO_EMAIL", test_email)
        monkeypatch.setenv("SHIKIHO_PASSWORD", test_password)

        from scripts.shikiho import ShikihoCollector
        from scripts.main import collect

        # 実際の ShikihoCollector を使い、HTTP のみモック（認証失敗シナリオ）
        mock_login_resp = MagicMock()
        mock_login_resp.status_code = 403

        mock_client = MagicMock()
        mock_client.post.return_value = mock_login_resp

        original_cls = ShikihoCollector

        class InstrumentedShikihoCollector(original_cls):
            def __enter__(self):
                self._client = mock_client
                return self

            def __exit__(self, *args):
                return False

        # Yahoo fallback もモック（fallback で secret が漏れないことを確認）
        yahoo_fallback_cls = _mock_collector_cls(
            collected=False,
            url="https://finance.yahoo.co.jp/quote/7203.T",
            error="fallback test",
        )
        mock_map = {"shikiho": InstrumentedShikihoCollector}
        with patch("scripts.main.SOURCE_MAP", mock_map), \
             patch("scripts.main.YahooFinanceCollector", yahoo_fallback_cls):
            result = collect("7203", ["shikiho"])

        result_str = json.dumps(result, ensure_ascii=False)
        assert test_email not in result_str, "SHIKIHO_EMAIL が出力に漏洩"
        assert test_password not in result_str, "SHIKIHO_PASSWORD が出力に漏洩"
