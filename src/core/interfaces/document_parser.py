"""IDocumentParser — contract for Azure Document Intelligence parsing."""

from typing import Protocol

from src.core.models.parsed_document import ParsedDocument


class IDocumentParser(Protocol):
    """Parses raw attachment bytes into structured text + tables."""

    async def parse(self, filename: str, content_bytes: bytes) -> ParsedDocument: ...
