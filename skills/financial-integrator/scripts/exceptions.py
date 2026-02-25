# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class IntegrationError(Exception):
    """financial-integrator の基底例外クラス."""


class MissingEdinetFileError(IntegrationError):
    """必須の EDINET ファイルが見つからない."""


class InvalidFinancialsFormatError(IntegrationError):
    """財務データのフォーマットが不正."""
