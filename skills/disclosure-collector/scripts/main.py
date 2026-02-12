"""disclosure-collector メインスクリプト.

J-Quants API と EDINET API の収集を提供する。
"""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

# スクリプト直接実行とパッケージインポートの両方に対応
if __name__ == "__main__":
    # 直接実行時はパッケージルートをパスに追加
    _script_dir = Path(__file__).resolve().parent
    if str(_script_dir) not in sys.path:
        sys.path.insert(0, str(_script_dir))
    from auth import JQuantsAuth, JQuantsAuthError
    from edinet import EdinetError, collect_edinet_pdfs, collect_edinet_reports
    from statements import StatementsClient, StatementsError
else:
    from .auth import JQuantsAuth, JQuantsAuthError
    from .edinet import EdinetError, collect_edinet_pdfs, collect_edinet_reports
    from .statements import StatementsClient, StatementsError

load_dotenv()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _data_root() -> Path:
    configured = os.environ.get("DATA_PATH")
    if not configured:
        return _repo_root() / "data"
    path = Path(configured).expanduser()
    if path.is_absolute():
        return path
    return (_repo_root() / path).resolve()


def collect_jquants(code: str, output_dir: str | None = None) -> dict:
    """
    銘柄コードの決算短信データを収集して保存

    Args:
        code: 銘柄コード（例: "7203"）
        output_dir: 出力先（省略時は data/{code}/raw/jquants/）

    Returns:
        {"saved_path": str, "record_count": int}

    Raises:
        JQuantsAuthError: 認証に失敗した場合
        StatementsError: データ取得に失敗した場合
        OSError: ファイル書き込みに失敗した場合
    """
    if output_dir is None:
        output_path = _data_root() / code / "raw" / "jquants"
    else:
        output_path = Path(output_dir)

    output_path.mkdir(parents=True, exist_ok=True)

    auth = JQuantsAuth()
    client = StatementsClient(auth)
    statements = client.fetch(code)

    today = date.today().isoformat()
    filename = f"statements_{today}.json"
    save_path = output_path / filename

    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(statements, f, ensure_ascii=False, indent=2)

    return {
        "saved_path": str(save_path),
        "record_count": len(statements) if isinstance(statements, list) else 0,
    }


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"日付形式が不正です: {value} (YYYY-MM-DD を指定してください)"
        ) from e


def _default_code_for_edinet_output(
    ticker: str | None,
    security_code: str | None,
    edinet_code: str,
) -> str:
    if ticker:
        return ticker
    if security_code:
        normalized = security_code.strip()
        if len(normalized) == 5 and normalized.endswith("0"):
            return normalized[:4]
        return normalized
    return edinet_code


def collect_edinet(
    edinet_code: str,
    ticker: str | None,
    security_code: str | None,
    output_dir: str | None,
    start_date: date | None,
    end_date: date | None,
    report_keyword: str,
    form_codes: list[str] | None,
    pdf: bool = False,
    doc_type_codes: list[str] | None = None,
) -> dict:
    """EDINET API から有価証券報告書を収集する。"""
    if output_dir is None:
        code_for_dir = _default_code_for_edinet_output(
            ticker=ticker,
            security_code=security_code,
            edinet_code=edinet_code,
        )
        output_path = _data_root() / code_for_dir / "raw" / "edinet"
    else:
        output_path = Path(output_dir)

    allowed_form_codes = set(form_codes) if form_codes else None
    allowed_doc_type_codes = set(doc_type_codes) if doc_type_codes else None

    if pdf:
        return collect_edinet_pdfs(
            edinet_code=edinet_code,
            output_dir=output_path,
            start_date=start_date,
            end_date=end_date,
            report_keyword=report_keyword,
            allowed_form_codes=allowed_form_codes,
            security_code=security_code,
            ticker=ticker,
            allowed_doc_type_codes=allowed_doc_type_codes,
        )

    return collect_edinet_reports(
        edinet_code=edinet_code,
        output_dir=output_path,
        start_date=start_date,
        end_date=end_date,
        report_keyword=report_keyword,
        allowed_form_codes=allowed_form_codes,
        security_code=security_code,
        allowed_doc_type_codes=allowed_doc_type_codes,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="J-Quants / EDINET から開示データを収集"
    )
    subparsers = parser.add_subparsers(dest="command")

    parser_jq = subparsers.add_parser(
        "jquants",
        help="J-Quants APIから決算短信データを収集",
    )
    parser_jq.add_argument(
        "code",
        type=str,
        help="銘柄コード（例: 7203）",
    )
    parser_jq.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="出力先ディレクトリ（省略時: data/{code}/raw/jquants/）",
    )

    parser_ed = subparsers.add_parser(
        "edinet",
        help="EDINET APIから有価証券報告書とXBRLを収集",
    )
    parser_ed.add_argument(
        "edinet_code",
        type=str,
        help="EDINETコード（例: E03416）",
    )
    parser_ed.add_argument(
        "--ticker",
        type=str,
        default=None,
        help="出力先ディレクトリに使う銘柄コード（例: 2780）",
    )
    parser_ed.add_argument(
        "--security-code",
        type=str,
        default=None,
        help="EDINET一覧の secCode で絞り込む（例: 27800）",
    )
    parser_ed.add_argument(
        "--start-date",
        type=_parse_iso_date,
        default=None,
        help="一覧取得開始日（YYYY-MM-DD）",
    )
    parser_ed.add_argument(
        "--end-date",
        type=_parse_iso_date,
        default=None,
        help="一覧取得終了日（YYYY-MM-DD、省略時は当日）",
    )
    parser_ed.add_argument(
        "--report-keyword",
        type=str,
        default="有価証券報告書",
        help="docDescription のフィルタ文字列",
    )
    parser_ed.add_argument(
        "--form-code",
        action="append",
        default=None,
        help="formCode で追加絞り込み（複数指定可）",
    )
    parser_ed.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="出力先ディレクトリ（省略時: data/{ticker_or_code}/raw/edinet/）",
    )
    parser_ed.add_argument(
        "--pdf",
        action="store_true",
        default=False,
        help="PDF形式でダウンロード（type=2）。ZIPを展開してPDFを保存する",
    )
    parser_ed.add_argument(
        "--doc-type-code",
        action="append",
        default=None,
        help="docTypeCode で絞り込み（複数指定可、例: --doc-type-code 120 --doc-type-code 130）",
    )

    return parser


def main() -> int:
    """CLIエントリーポイント

    Returns:
        終了コード（0: 成功, 1: エラー）
    """
    parser = build_parser()
    raw_argv = sys.argv[1:]

    # 後方互換: `main.py 7203` は `main.py jquants 7203` と同義
    if raw_argv and raw_argv[0] not in {"jquants", "edinet"} and not raw_argv[0].startswith("-"):
        raw_argv = ["jquants", *raw_argv]

    args = parser.parse_args(raw_argv)

    try:
        if args.command == "jquants":
            result = collect_jquants(args.code, args.output_dir)
            print(f"保存完了: {result['saved_path']}")
            print(f"レコード数: {result['record_count']}")
            return 0

        if args.command == "edinet":
            result = collect_edinet(
                edinet_code=args.edinet_code,
                ticker=args.ticker,
                security_code=args.security_code,
                output_dir=args.output_dir,
                start_date=args.start_date,
                end_date=args.end_date,
                report_keyword=args.report_keyword,
                form_codes=args.form_code,
                pdf=args.pdf,
                doc_type_codes=args.doc_type_code,
            )
            print(f"保存完了: {result['output_dir']}")
            print(f"manifest: {result['manifest_path']}")
            print(f"一致 docID 件数: {result['matched_doc_count']}")
            print(f"DL成功: {result['downloaded_count']}")
            print(f"既存スキップ: {result['skipped_existing_count']}")
            print(f"DL失敗: {result['failed_count']}")
            return 0

        parser.print_help()
        return 1
    except argparse.ArgumentTypeError as e:
        print(f"引数エラー: {e}", file=sys.stderr)
        return 1
    except EdinetError as e:
        print(f"EDINET処理エラー: {e}", file=sys.stderr)
        return 1
    except JQuantsAuthError as e:
        print(f"認証エラー: {e}", file=sys.stderr)
        return 1
    except StatementsError as e:
        print(f"データ取得エラー: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"値エラー: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"ファイル書き込みエラー: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
