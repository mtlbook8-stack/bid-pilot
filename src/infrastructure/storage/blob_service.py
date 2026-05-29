"""AzureBlobService — IBlobService backed by Azure Blob Storage."""

from typing import AsyncIterator

from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob import ContentSettings
from azure.storage.blob.aio import BlobServiceClient

from src.api.config import Settings
from src.core.errors.app_error import AppError


class AzureBlobService:
    """
    Azure Blob Storage implementation of `IBlobService`.

    Stores the original bid PDFs. Authentication is managed-identity only
    (`DefaultAzureCredential` against `Settings.blob_endpoint`) — no account keys
    or connection strings ever touch code or config (build doc — keyless access).

    `stream` is the load-bearing method: the PDF proxy endpoint pipes its chunks
    straight to the browser so the API never buffers a whole file in memory.

    Blob paths are addressed as `<container>/<blob_path>` where the container is
    `Settings.blob_bids_container`; callers pass only the per-bid blob path. The
    client and credential allocate transport resources, so the composition root
    owns one instance and calls `close()` on shutdown (Rule 3 — injected Settings,
    one place wires it). Every SDK call is wrapped and re-raised as an AppError
    (Rule 8); the service never logs.
    """

    def __init__(self, settings: Settings) -> None:
        """
        Store config and build the async client.

        The credential and `BlobServiceClient` are created here from injected
        Settings rather than self-discovered, keeping construction the single
        wiring point while the endpoint/container come entirely from config.
        """
        self._settings = settings
        self._credential = DefaultAzureCredential()
        self._client = BlobServiceClient(
            account_url=settings.blob_endpoint,
            credential=self._credential,
        )
        self._container_name = settings.blob_bids_container

    def _blob_client(self, blob_path: str):
        """
        Resolve a blob client for a path within the bids container.

        Centralized (Rule 5) so every operation derives its blob client the same
        way and only the container name lives in one place.
        """
        return self._client.get_blob_client(
            container=self._container_name, blob=blob_path
        )

    async def upload(
        self, blob_path: str, content_bytes: bytes, content_type: str
    ) -> str:
        """
        Upload bytes to a blob and return its path.

        `overwrite=True` keeps ingestion idempotent: re-processing the same
        attachment (deterministic blob path) replaces rather than conflicts. The
        content type is set so the PDF proxy serves the correct MIME type later.
        """
        try:
            blob = self._blob_client(blob_path)
            await blob.upload_blob(
                content_bytes,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type),
            )
            return blob_path
        except Exception as e:
            raise AppError(
                code="BLOB_UPLOAD",
                message="Failed to upload blob",
                context={"blob_path": blob_path, "content_type": content_type},
                cause=e,
            )

    async def download(self, blob_path: str) -> bytes:
        """
        Download a whole blob into memory.

        Used where the full bytes are genuinely needed (re-parsing); the proxy
        path uses `stream` instead to avoid buffering.
        """
        try:
            blob = self._blob_client(blob_path)
            downloader = await blob.download_blob()
            return await downloader.readall()
        except Exception as e:
            raise AppError(
                code="BLOB_DOWNLOAD",
                message="Failed to download blob",
                context={"blob_path": blob_path},
                cause=e,
            )

    async def stream(self, blob_path: str) -> AsyncIterator[bytes]:
        """
        Yield a blob's content in chunks for streaming to the browser.

        Why a generator: the PDF proxy must not hold an entire PDF in memory; it
        forwards each chunk as it arrives. The `download_blob()` call is awaited
        and its async `chunks()` iterator is consumed lazily. The await is wrapped
        for context, but the per-chunk iteration runs outside the try/except so we
        do not swallow a `GeneratorExit` (raised when the consumer closes the
        stream early) by treating it as an SDK failure.
        """
        try:
            blob = self._blob_client(blob_path)
            downloader = await blob.download_blob()
        except Exception as e:
            raise AppError(
                code="BLOB_STREAM_OPEN",
                message="Failed to open blob stream",
                context={"blob_path": blob_path},
                cause=e,
            )
        async for chunk in downloader.chunks():
            yield chunk

    async def close(self) -> None:
        """
        Close the client and credential transports on app shutdown.

        Wrapped so a shutdown-time failure surfaces with context instead of
        escaping as a raw SDK error.
        """
        try:
            await self._client.close()
            await self._credential.close()
        except Exception as e:
            raise AppError(
                code="BLOB_CLOSE",
                message="Failed to close the blob service client",
                context={},
                cause=e,
            )
