"""IBlobService — contract for original-file storage in Azure Blob."""

from typing import AsyncIterator, Protocol


class IBlobService(Protocol):
    """
    Stores original bid PDFs. `stream` yields chunks for the PDF proxy endpoint
    so the API never buffers a whole file in memory.
    """

    async def upload(self, blob_path: str, content_bytes: bytes, content_type: str) -> str: ...

    async def stream(self, blob_path: str) -> AsyncIterator[bytes]: ...

    async def download(self, blob_path: str) -> bytes: ...
