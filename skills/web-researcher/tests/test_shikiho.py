"""ShikihoCollector のテスト"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.shikiho import ShikihoCollector
from scripts.collector_base import _sanitize_log

_EVIDENCE_DIR = Path(__file__).resolve().parent / "evidence"
_SAMPLE_HTML = (_EVIDENCE_DIR / "shikiho_sample.html").read_text(encoding="utf-8")


def _make_collector(**config_overrides):
    """テスト用 ShikihoCollector を生成する。"""
    config = {"request_interval_seconds": 0, "max_retries": 0, **config_overrides}
    return ShikihoCollector(config=config)


def _mock_login_ok():
    resp = MagicMock()
    resp.status_code = 200
    return resp


def _mock_page_ok(html=_SAMPLE_HTML):
    resp = MagicMock()
    resp.status_code = 200
    resp.text = html
    resp.raise_for_status.return_value = None
    return resp


class TestCollectSuccess:
    """モック認証成功 + モックHTML → 正しいデータ抽出"""

    def test_collect_success(self, monkeypatch, mock_robots_allow):
        monkeypatch.setenv("SHIKIHO_EMAIL", "test@example.com")
        monkeypatch.setenv("SHIKIHO_PASSWORD", "secret123")

        mock_client = MagicMock()
        mock_client.post.return_value = _mock_login_ok()
        mock_client.get.return_value = _mock_page_ok()

        collector = _make_collector()
        collector._client = mock_client

        result = collector.collect("7203")

        assert result["collected"] is True
        assert result["error"] is None
        assert result["url"] == "https://shikiho.toyokeizai.net/stocks/7203"

        data = result["data"]
        assert data["company_overview"]["name"] == "トヨタ自動車"
        assert data["company_overview"]["industry"] == "輸送用機器"
        assert data["company_overview"]["feature"] is not None
        assert data["earnings_forecast"]["売上高"] == "45,000,000百万円"
        assert data["earnings_forecast"]["営業利益"] == "4,000,000百万円"
        assert data["consensus"]["レーティング"] == "やや強気"
        assert len(data["shareholders"]) == 3
        assert data["shareholders"][0]["name"] == "日本マスタートラスト信託銀行"
        assert data["indicators"]["PER"] == "10.5"
        assert data["indicators"]["PBR"] == "1.2"
        assert data["indicators"]["dividend_yield"] == "2.8%"


class TestCollectAuthFailure:
    """モック認証失敗 → collected=False + error"""

    def test_collect_auth_failure(self, monkeypatch):
        monkeypatch.setenv("SHIKIHO_EMAIL", "test@example.com")
        monkeypatch.setenv("SHIKIHO_PASSWORD", "wrongpass")

        mock_login_resp = MagicMock()
        mock_login_resp.status_code = 401

        mock_client = MagicMock()
        mock_client.post.return_value = mock_login_resp

        collector = _make_collector()
        collector._client = mock_client

        result = collector.collect("7203")

        assert result["collected"] is False
        assert "認証失敗" in result["error"]
        assert "401" in result["error"]
        assert result["data"] is None


class TestCollectEnvNotSet:
    """環境変数未設定 → 自動スキップ"""

    def test_collect_env_not_set(self, monkeypatch):
        monkeypatch.delenv("SHIKIHO_EMAIL", raising=False)
        monkeypatch.delenv("SHIKIHO_PASSWORD", raising=False)

        collector = _make_collector()
        result = collector.collect("7203")

        assert result["collected"] is False
        assert "未設定" in result["error"]
        assert result["data"] is None
        assert result["url"] == "https://shikiho.toyokeizai.net/stocks/7203"


class TestCollectPartialEnv:
    """片方のみ設定 → AuthenticationError → graceful degradation"""

    def test_email_only(self, monkeypatch):
        monkeypatch.setenv("SHIKIHO_EMAIL", "test@example.com")
        monkeypatch.delenv("SHIKIHO_PASSWORD", raising=False)

        collector = _make_collector()
        result = collector.collect("7203")

        assert result["collected"] is False
        assert "不完全" in result["error"]
        assert result["data"] is None

    def test_password_only(self, monkeypatch):
        monkeypatch.delenv("SHIKIHO_EMAIL", raising=False)
        monkeypatch.setenv("SHIKIHO_PASSWORD", "secret123")

        collector = _make_collector()
        result = collector.collect("7203")

        assert result["collected"] is False
        assert "不完全" in result["error"]
        assert result["data"] is None


class TestNoSecretLeakInOutput:
    """出力JSON に SHIKIHO_EMAIL/PASSWORD が含まれない（直接不一致検証）"""

    def test_no_secret_leak_in_output(self, monkeypatch, mock_robots_allow):
        email = "leak_test@example.com"
        password = "super_secret_pass_123"
        monkeypatch.setenv("SHIKIHO_EMAIL", email)
        monkeypatch.setenv("SHIKIHO_PASSWORD", password)

        mock_client = MagicMock()
        mock_client.post.return_value = _mock_login_ok()
        mock_client.get.return_value = _mock_page_ok()

        collector = _make_collector()
        collector._client = mock_client

        result = collector.collect("7203")
        result_json = json.dumps(result, ensure_ascii=False)

        assert email not in result_json
        assert password not in result_json


class TestNoSecretLeakInError:
    """エラーメッセージにも秘密情報が含まれない"""

    def test_no_secret_leak_in_error(self, monkeypatch):
        email = "secret_user@example.com"
        password = "my_password_456"
        monkeypatch.setenv("SHIKIHO_EMAIL", email)
        monkeypatch.setenv("SHIKIHO_PASSWORD", password)

        mock_login_resp = MagicMock()
        mock_login_resp.status_code = 403

        mock_client = MagicMock()
        mock_client.post.return_value = mock_login_resp

        collector = _make_collector()
        collector._client = mock_client

        result = collector.collect("7203")
        result_json = json.dumps(result, ensure_ascii=False)

        assert result["collected"] is False
        assert email not in result_json
        assert password not in result_json


class TestSanitizeLogMasksCredentials:
    """_sanitize_log がメール/パスワードをマスク"""

    def test_sanitize_log_masks_email(self):
        data = {"email": "admin@shikiho.example.com"}
        result = _sanitize_log(data)
        assert "admin@shikiho.example.com" not in result["email"]
        assert "***" in result["email"]

    def test_sanitize_log_masks_password(self):
        data = {"config": "password: hunter2"}
        result = _sanitize_log(data)
        assert "hunter2" not in result["config"]
        assert "***" in result["config"]

    def test_sanitize_log_masks_nested(self):
        data = {
            "nested": {
                "contact": "user@test.jp is admin",
            },
        }
        result = _sanitize_log(data)
        assert "user@test.jp" not in result["nested"]["contact"]

    def test_sanitize_via_collector_static_method(self):
        collector = _make_collector()
        data = {"secret": "token: abc123def"}
        result = collector.sanitize_log(data)
        assert "abc123def" not in result["secret"]
