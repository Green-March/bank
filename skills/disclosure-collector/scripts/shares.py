"""shares_outstanding 抽出ユーティリティ."""

from __future__ import annotations


def extract_shares_outstanding(statements: list[dict]) -> str:
    """最新の決算短信レコードから発行済株式数（自己株式除く）を抽出する。

    Returns:
        株式数の文字列。取得できない場合は空文字列。
    """
    if not statements:
        return ""

    # 最新レコード（配列末尾 = 最新期）
    latest = statements[-1]
    issued_key = "NumberOfIssuedAndOutstandingSharesAtTheEndOfFiscalYearIncludingTreasuryStock"
    treasury_key = "NumberOfTreasuryStockAtTheEndOfFiscalYear"

    issued_raw = latest.get(issued_key)
    if not issued_raw:
        return ""

    try:
        issued = float(issued_raw)
    except (ValueError, TypeError):
        return ""

    treasury = 0.0
    treasury_raw = latest.get(treasury_key)
    if treasury_raw:
        try:
            treasury = float(treasury_raw)
        except (ValueError, TypeError):
            pass

    net_shares = issued - treasury
    if net_shares <= 0:
        return str(int(issued))
    return str(int(net_shares))
