"""CLI entrypoint for disclosure-parser."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

if __package__ in {None, ""}:
    _script_dir = Path(__file__).resolve().parent
    if str(_script_dir) not in sys.path:
        sys.path.insert(0, str(_script_dir))
    from parser import (
        ParserError,
        build_period_index,
        parse_edinet_directory,
        write_outputs,
        BS_KEYS,
        PL_KEYS,
        CF_KEYS,
    )
    from pdf_parser import parse_pdf_directory
else:
    from .parser import (
        ParserError,
        build_period_index,
        parse_edinet_directory,
        write_outputs,
        BS_KEYS,
        PL_KEYS,
        CF_KEYS,
    )
    from .pdf_parser import parse_pdf_directory

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


def resolve_code(code: str | None, ticker: str | None) -> str:
    """Return a code value from `--code` and `--ticker` arguments."""
    if code and ticker and code != ticker:
        raise ParserError("--code and --ticker are both provided but differ.")
    resolved = code or ticker
    if not resolved:
        raise ParserError("Either --code or --ticker is required.")
    return resolved


def _detect_input_mode(input_dir: Path) -> str | None:
    """Auto-detect input mode from file extensions in input_dir.

    Returns "pdf", "xbrl", or None (mixed/empty).
    """
    if not input_dir.is_dir():
        return None

    has_pdf = any(input_dir.glob("*.pdf"))
    has_zip = any(input_dir.glob("*.zip"))

    if has_pdf and not has_zip:
        return "pdf"
    if has_zip and not has_pdf:
        return "xbrl"
    return None  # mixed or empty


def _write_pdf_outputs(
    documents: list,
    metadata_list: list,
    output_dir: Path,
    ticker: str,
) -> dict[str, str]:
    """Write per-document JSON and aggregate financials.json for PDF parsing."""
    output_dir.mkdir(parents=True, exist_ok=True)

    saved_files: dict[str, str] = {}
    for document, meta in zip(documents, metadata_list):
        doc_dict = document.to_dict()
        doc_dict["pdf_metadata"] = asdict(meta)
        path = output_dir / f"{document.document_id}.json"
        with path.open("w", encoding="utf-8") as file:
            json.dump(doc_dict, file, ensure_ascii=False, indent=2)
        saved_files[document.document_id] = str(path)

    aggregate_path = output_dir / "financials.json"
    aggregate = {
        "ticker": ticker,
        "generated_at": datetime.now(UTC).isoformat(),
        "document_count": len(documents),
        "source_format": "pdf",
        "documents": [document.to_dict() for document in documents],
        "period_index": build_period_index(documents),
        "schema": {
            "bs": list(BS_KEYS),
            "pl": list(PL_KEYS),
            "cf": list(CF_KEYS),
        },
    }
    with aggregate_path.open("w", encoding="utf-8") as file:
        json.dump(aggregate, file, ensure_ascii=False, indent=2)
    saved_files["financials"] = str(aggregate_path)

    return saved_files


def main() -> int:
    """Run parser CLI."""
    parser = argparse.ArgumentParser(
        description="Parse EDINET XBRL zip files or PDF securities reports into normalized BS/PL/CF JSON."
    )
    parser.add_argument("--code", type=str, default=None, help="Stock code (e.g. 2780).")
    parser.add_argument(
        "--ticker",
        type=str,
        default=None,
        help="Ticker alias for code (e.g. 2780).",
    )
    parser.add_argument(
        "--input-dir",
        type=str,
        default=None,
        help="Input directory containing EDINET zip files or PDF reports.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory for parsed JSON files.",
    )
    parser.add_argument(
        "--pdf",
        action="store_true",
        default=False,
        help="Force PDF parsing mode (uses pdf_parser.py instead of parser.py).",
    )
    args = parser.parse_args()

    try:
        code = resolve_code(args.code, args.ticker)
        data_root = _data_root()
        input_dir = (
            Path(args.input_dir)
            if args.input_dir
            else data_root / code / "raw" / "edinet"
        )
        output_dir = (
            Path(args.output_dir)
            if args.output_dir
            else data_root / code / "parsed"
        )

        # Determine mode: explicit --pdf flag, or auto-detect from files
        use_pdf = args.pdf
        if not use_pdf:
            detected = _detect_input_mode(input_dir)
            if detected == "pdf":
                use_pdf = True

        if use_pdf:
            documents, metadata_list = parse_pdf_directory(
                input_path=input_dir, ticker=code,
            )
            saved_files = _write_pdf_outputs(
                documents=documents,
                metadata_list=metadata_list,
                output_dir=output_dir,
                ticker=code,
            )
            print(f"Parsed {len(documents)} PDF document(s).")
        else:
            documents = parse_edinet_directory(input_dir=input_dir, ticker=code)
            saved_files = write_outputs(
                documents=documents, output_dir=output_dir, ticker=code,
            )
            print(f"Parsed {len(documents)} XBRL document(s).")

        print(f"Aggregate: {saved_files['financials']}")
        return 0
    except ParserError as exc:
        print(f"Parser error: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"File not found: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"I/O error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
