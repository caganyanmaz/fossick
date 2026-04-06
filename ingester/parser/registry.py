from __future__ import annotations

from ingester.parser.base import BaseParser
from ingester.parser.code import CodeParser
from ingester.parser.docling_parser import DoclingParser
from ingester.parser.image import ImageParser
from ingester.parser.spreadsheet import SpreadsheetParser
from ingester.parser.video import VideoParser

# Order matters: DoclingParser before CodeParser so .md/.html go to Docling.
_PARSERS: list[BaseParser] = [
    DoclingParser(),
    SpreadsheetParser(),
    ImageParser(),
    VideoParser(),
    CodeParser(),
]


def get_parser(path: str) -> BaseParser | None:
    for parser in _PARSERS:
        if parser.can_parse(path):
            return parser
    return None
