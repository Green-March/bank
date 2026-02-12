"""disclosure-parser scripts package."""

from .parser import (
    ParsedDocument,
    ParserError,
    parse_edinet_directory,
    parse_edinet_zip,
    write_outputs,
)

__all__ = [
    "ParsedDocument",
    "ParserError",
    "parse_edinet_directory",
    "parse_edinet_zip",
    "write_outputs",
]
