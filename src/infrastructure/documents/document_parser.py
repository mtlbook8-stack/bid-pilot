"""
AzureDocumentParser — IDocumentParser backed by Azure Document Intelligence.

Runs an attachment's bytes through the `prebuilt-layout` model and flattens the
SDK result into the framework-agnostic ParsedDocument shape (pages of text +
row-major tables) so agents and stores depend only on `core.models`, never on
the Azure SDK (build doc 8.1, model "prebuilt-layout").

Authentication is managed-identity only via `DefaultAzureCredential` against
`Settings.doc_intelligence_endpoint` — no key ever touches code or config.
"""

import logging

from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from azure.identity.aio import DefaultAzureCredential

from src.api.config import Settings
from src.core.errors.app_error import AppError
from src.core.models.parsed_document import (
    ParsedDocument,
    ParsedPage,
    ParsedTable,
)

logger = logging.getLogger(__name__)

# Layout model: extracts text lines plus table structure (rows/columns/cells),
# which is exactly what the comparison agents reason over. No OCR-only model
# would give us the table geometry we need for pricing tables.
_LAYOUT_MODEL_ID = "prebuilt-layout"


class AzureDocumentParser:
    """
    IDocumentParser implementation over Azure Document Intelligence.

    Why a dedicated wrapper: the SDK's analyze-document result is a deeply nested,
    optional-heavy object. Centralizing the mapping here (Rule 2/Rule 5) means
    every caller gets the same defensively-parsed ParsedDocument and the SDK
    shape lives in exactly one place.

    Dependencies are injected (Rule 3): the credential and Settings arrive
    through the constructor; the composition root owns the single client and
    calls `close()` on shutdown. Every external call is wrapped and re-raised as
    AppError "DOC_PARSE" (Rules 7/8); the parser never logs.
    """

    def __init__(
        self,
        credential: DefaultAzureCredential,
        settings: Settings,
    ) -> None:
        self._credential = credential
        self._settings = settings
        self._client = DocumentIntelligenceClient(
            endpoint=settings.doc_intelligence_endpoint,
            credential=credential,
        )

    async def parse(self, filename: str, content_bytes: bytes) -> ParsedDocument:
        """
        Analyze raw attachment bytes into structured text + tables.

        Submits the bytes to the layout model, awaits the long-running operation,
        then maps the result. Mapping is fully defensive — any of pages, lines,
        tables, or cells may be absent on a given document (e.g. an image-only
        page yields no table) and a missing section must produce an empty list,
        never a crash.

        `full_text` is the page texts joined with blank lines between pages so a
        prefix slice (used to cap agent context) reads naturally across pages.
        """
        try:
            poller = await self._client.begin_analyze_document(
                model_id=_LAYOUT_MODEL_ID,
                body=AnalyzeDocumentRequest(bytes_source=content_bytes),
            )
            result = await poller.result()
        except Exception as exc:
            raise AppError(
                code="DOC_PARSE",
                message="Azure Document Intelligence analyze failed",
                context={"filename": filename, "model": _LAYOUT_MODEL_ID},
                cause=exc,
            )

        # The network/operation work is done; mapping is pure but still wrapped
        # because an unexpected result shape should surface as a typed error with
        # the filename for debugging rather than an opaque AttributeError.
        try:
            return self._map_result(filename, result)
        except Exception as exc:
            raise AppError(
                code="DOC_PARSE",
                message="Failed to map Document Intelligence result",
                context={"filename": filename, "model": _LAYOUT_MODEL_ID},
                cause=exc,
            )

    def _map_result(self, filename: str, result: object) -> ParsedDocument:
        """
        Flatten the SDK AnalyzeResult into a ParsedDocument.

        Pages and tables are read through `getattr` with safe defaults because
        the SDK uses optional attributes; treating any missing piece as empty
        keeps a partially-parseable document usable instead of failing the whole
        ingest.
        """
        raw_pages = getattr(result, "pages", None) or []
        raw_tables = getattr(result, "tables", None) or []

        pages = [self._map_page(p) for p in raw_pages]
        tables = [self._map_table(t) for t in raw_tables]

        # Concatenate page text with a blank-line separator so downstream prefix
        # slicing does not run two pages' words together.
        full_text = "\n\n".join(page.text for page in pages if page.text)

        return ParsedDocument(
            source_filename=filename,
            page_count=len(pages),
            full_text=full_text,
            pages=pages,
            tables=tables,
        )

    @staticmethod
    def _map_page(page: object) -> ParsedPage:
        """
        Map one SDK page to a ParsedPage.

        Page text is the page's `lines` joined by newlines (the layout model
        exposes text as line objects, each with a `content` string). The page
        number falls back to 1 because ParsedPage requires `page_number >= 1`
        and a document always has at least one page.
        """
        page_number = int(getattr(page, "page_number", None) or 1)
        lines = getattr(page, "lines", None) or []
        text = "\n".join(
            (getattr(line, "content", None) or "") for line in lines
        ).strip()
        return ParsedPage(page_number=page_number, text=text)

    @staticmethod
    def _map_table(table: object) -> ParsedTable:
        """
        Map one SDK table to a row-major ParsedTable.

        The SDK gives a flat list of cells each carrying `row_index` /
        `column_index`; we place each cell's `content` into a pre-sized grid so
        the output is true row-major (outer = rows, inner = cells). Row/column
        counts come from the SDK when present and otherwise are derived from the
        max indices seen, so a table with a missing count still maps correctly.

        The page number is taken from the table's first bounding region; absent
        that, it defaults to 1 to satisfy the model's `>= 1` constraint.
        """
        cells = getattr(table, "cells", None) or []

        # Determine grid dimensions defensively: prefer the SDK-reported counts,
        # fall back to one past the largest index observed in the cells.
        row_count = int(getattr(table, "row_count", None) or 0)
        column_count = int(getattr(table, "column_count", None) or 0)
        for cell in cells:
            r = int(getattr(cell, "row_index", 0) or 0)
            c = int(getattr(cell, "column_index", 0) or 0)
            row_count = max(row_count, r + 1)
            column_count = max(column_count, c + 1)

        # Pre-size a blank grid, then drop each cell's content into place. Cells
        # whose indices fall outside the computed grid are skipped rather than
        # raising, since the grid is sized from those same indices.
        grid: list[list[str]] = [
            ["" for _ in range(column_count)] for _ in range(row_count)
        ]
        for cell in cells:
            r = int(getattr(cell, "row_index", 0) or 0)
            c = int(getattr(cell, "column_index", 0) or 0)
            if 0 <= r < row_count and 0 <= c < column_count:
                grid[r][c] = (getattr(cell, "content", None) or "").strip()

        page_number = AzureDocumentParser._table_page_number(table)

        return ParsedTable(
            page_number=page_number,
            row_count=row_count,
            column_count=column_count,
            rows=grid,
        )

    @staticmethod
    def _table_page_number(table: object) -> int:
        """
        Resolve the page a table sits on from its bounding regions.

        Bounding regions are optional; when absent (or malformed) we default to
        page 1 so ParsedTable's `page_number >= 1` invariant always holds.
        """
        regions = getattr(table, "bounding_regions", None) or []
        if regions:
            page_number = getattr(regions[0], "page_number", None)
            if page_number:
                return int(page_number)
        return 1

    async def close(self) -> None:
        """
        Close the client and credential transports on app shutdown.

        Wrapped so a shutdown-time failure surfaces with context instead of
        escaping as a raw SDK error.
        """
        try:
            await self._client.close()
            await self._credential.close()
        except Exception as exc:
            raise AppError(
                code="DOC_PARSE",
                message="Failed to close the Document Intelligence client",
                context={},
                cause=exc,
            )
