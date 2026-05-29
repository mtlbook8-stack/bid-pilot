"""
Structured output of Azure Document Intelligence parsing.

Lives in core so both the ingestion layer (which produces it) and the agents
(which consume document text + tables) depend on the same shape without either
knowing about the Azure SDK.
"""

from pydantic import Field

from src.core.models.base import CamelModel


class ParsedTable(CamelModel):
    """A single table extracted from a document, flattened to rows of cells."""

    page_number: int = Field(..., ge=1)
    row_count: int = Field(..., ge=0)
    column_count: int = Field(..., ge=0)
    # Row-major cell text. Outer list = rows, inner list = cells in that row.
    rows: list[list[str]] = Field(default_factory=list)

    @property
    def headers(self) -> list[str]:
        """First row, treated as headers. Empty if the table has no rows."""
        return self.rows[0] if self.rows else []

    def to_markdown(self) -> str:
        """
        Render the table as GitHub-flavored markdown for inclusion in agent
        prompts. Agents read tables far more reliably as markdown than as JSON.
        """
        if not self.rows:
            return ""
        header = "| " + " | ".join(self.headers) + " |"
        separator = "| " + " | ".join("---" for _ in self.headers) + " |"
        body = [
            "| " + " | ".join(cell for cell in row) + " |"
            for row in self.rows[1:]
        ]
        return "\n".join([header, separator, *body])


class ParsedPage(CamelModel):
    """Text content of a single page."""

    page_number: int = Field(..., ge=1)
    text: str = ""


class ParsedDocument(CamelModel):
    """
    Full parsed representation of one attachment.

    `full_text` is the concatenation of all page text; agents that only need a
    prefix slice it via `text_prefix`. Tables are kept separately because they
    carry the pricing structure agents reason over.
    """

    source_filename: str
    page_count: int = Field(..., ge=0)
    full_text: str = ""
    pages: list[ParsedPage] = Field(default_factory=list)
    tables: list[ParsedTable] = Field(default_factory=list)

    def text_prefix(self, max_chars: int) -> str:
        """First `max_chars` of the document text — used to cap agent context."""
        return self.full_text[:max_chars]

    def table_headers_summary(self) -> str:
        """
        One-line-per-table summary of headers for the QuoteValidator prompt,
        which only needs to know table shape, not full contents.
        """
        if not self.tables:
            return "(no tables found)"
        return "; ".join(
            f"Table {i + 1}: {', '.join(t.headers)}" for i, t in enumerate(self.tables)
        )

    def tables_as_markdown(self) -> str:
        """All tables rendered as markdown blocks for the heavy comparison agents."""
        if not self.tables:
            return "(no tables found)"
        return "\n\n".join(t.to_markdown() for t in self.tables)
