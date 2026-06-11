from __future__ import annotations

from docagent.parser.base import ParserBackend
from docagent.parser.mineru_backend import MinerUParserBackend


def build_parser_backend(name: str = "mineru", *, mode: str = "parse_existing", command: str = "mineru") -> ParserBackend:
    if name != "mineru":
        raise ValueError(f"unsupported parser backend: {name}")
    return MinerUParserBackend(mode=mode, command=command)
