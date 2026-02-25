"""financial-integrator 例外クラスのテスト

対象: IntegrationError, MissingEdinetFileError, InvalidFinancialsFormatError
"""

import json
import sys
from pathlib import Path

import pytest

_scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from exceptions import (
    IntegrationError,
    InvalidFinancialsFormatError,
    MissingEdinetFileError,
)
from integrator import integrate


# ==================================================================
# 継承関係
# ==================================================================

class TestExceptionHierarchy:
    """例外クラスの継承関係を検証する。"""

    def test_integration_error_is_exception(self):
        assert issubclass(IntegrationError, Exception)

    def test_missing_edinet_file_inherits_integration_error(self):
        assert issubclass(MissingEdinetFileError, IntegrationError)

    def test_invalid_financials_format_inherits_integration_error(self):
        assert issubclass(InvalidFinancialsFormatError, IntegrationError)

    def test_catch_by_base_class(self):
        """IntegrationError でサブクラスをキャッチできる。"""
        with pytest.raises(IntegrationError):
            raise MissingEdinetFileError("test")

        with pytest.raises(IntegrationError):
            raise InvalidFinancialsFormatError("test")


# ==================================================================
# メッセージ内容
# ==================================================================

class TestExceptionMessages:
    """例外メッセージが正しく伝搬されること。"""

    def test_missing_edinet_file_message(self):
        msg = "EDINET ファイルが見つかりません: /path/to/file"
        exc = MissingEdinetFileError(msg)
        assert str(exc) == msg

    def test_invalid_financials_format_message(self):
        msg = "JSON が不正です"
        exc = InvalidFinancialsFormatError(msg)
        assert str(exc) == msg

    def test_integration_error_message(self):
        msg = "統合処理エラー"
        exc = IntegrationError(msg)
        assert str(exc) == msg


# ==================================================================
# integrate() での発生条件
# ==================================================================

class TestIntegrateExceptions:
    """integrate() が適切なカスタム例外を発生させること。"""

    def test_missing_edinet_file(self, tmp_path):
        """EDINET ファイルが存在しない場合 MissingEdinetFileError。"""
        output_path = tmp_path / "output.json"
        with pytest.raises(MissingEdinetFileError, match="EDINET ファイルが見つかりません"):
            integrate(
                ticker="9999",
                fye_month=3,
                parsed_dir=tmp_path,
                output_path=output_path,
            )

    def test_invalid_json_format(self, tmp_path):
        """EDINET ファイルの JSON が壊れている場合 InvalidFinancialsFormatError。"""
        edinet_file = tmp_path / "financials.json"
        edinet_file.write_text("{invalid json", encoding="utf-8")
        output_path = tmp_path / "output.json"
        with pytest.raises(InvalidFinancialsFormatError, match="JSON が不正"):
            integrate(
                ticker="9999",
                fye_month=3,
                parsed_dir=tmp_path,
                output_path=output_path,
            )

    def test_missing_documents_key(self, tmp_path):
        """EDINET ファイルに 'documents' キーがない場合 InvalidFinancialsFormatError。"""
        edinet_file = tmp_path / "financials.json"
        edinet_file.write_text(
            json.dumps({"ticker": "9999"}),
            encoding="utf-8",
        )
        output_path = tmp_path / "output.json"
        with pytest.raises(
            InvalidFinancialsFormatError, match="'documents' キーがありません"
        ):
            integrate(
                ticker="9999",
                fye_month=3,
                parsed_dir=tmp_path,
                output_path=output_path,
            )

    def test_catch_all_with_integration_error(self, tmp_path):
        """IntegrationError でサブクラスを統一キャッチできること。"""
        output_path = tmp_path / "output.json"
        with pytest.raises(IntegrationError):
            integrate(
                ticker="9999",
                fye_month=3,
                parsed_dir=tmp_path,
                output_path=output_path,
            )

    def test_exception_chaining_json_decode(self, tmp_path):
        """JSONDecodeError が __cause__ として保持されること。"""
        edinet_file = tmp_path / "financials.json"
        edinet_file.write_text("not json", encoding="utf-8")
        output_path = tmp_path / "output.json"
        with pytest.raises(InvalidFinancialsFormatError) as exc_info:
            integrate(
                ticker="9999",
                fye_month=3,
                parsed_dir=tmp_path,
                output_path=output_path,
            )
        assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)
