"""Disk-backed ADS transfers with bounded reads and cancellation-safe ownership."""

import tempfile
from collections.abc import AsyncIterator
from contextlib import ExitStack
from typing import BinaryIO

from fastapi import HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import Receive, Scope, Send

from backend.engine import archive_safety
from backend.engine.session_exporter import SessionExporter
from backend.engine.session_importer import SessionImporter
from backend.utils.async_files import run_file_operation
from backend.utils.download_headers import attachment_disposition

TRANSFER_CHUNK_BYTES = 64 * 1024


class SessionArchiveResponse(StreamingResponse):
    """Keep the temporary archive alive until streaming ends or disconnects."""

    def __init__(self, archive: BinaryIO, size: int, session_id: str) -> None:
        self.archive = archive
        self.cleanup = ExitStack()
        self.cleanup.callback(archive.close)
        super().__init__(
            self._chunks(),
            media_type="application/zip",
            headers={
                "Content-Disposition": attachment_disposition(f"session_{session_id}.ads"),
                "Content-Length": str(size),
            },
        )

    async def _chunks(self) -> AsyncIterator[bytes]:
        while chunk := await run_file_operation(self.archive.read, TRANSFER_CHUNK_BYTES):
            yield chunk

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await run_file_operation(self.cleanup.close)


async def export_archive_response(db: AsyncSession, session_id: str) -> SessionArchiveResponse:
    with ExitStack() as cleanup:
        archive = cleanup.enter_context(tempfile.TemporaryFile(mode="w+b"))
        await SessionExporter.export_ads_to(db, session_id, archive)
        size = await run_file_operation(archive_safety.rewind_archive, archive)
        response = SessionArchiveResponse(archive, size, session_id)
        cleanup.pop_all()
        return response


async def import_uploaded_archive(
    db: AsyncSession, upload: UploadFile, owner_id: str
) -> str | None:
    """Use Starlette's spooled multipart file directly instead of reading the ZIP."""
    try:
        if upload.size is not None and upload.size > archive_safety.MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Session archive exceeds the upload budget.")
        try:
            await run_file_operation(archive_safety.rewind_archive, upload.file)
        except ValueError as exc:
            raise HTTPException(413, str(exc)) from None
        return await SessionImporter.import_ads_from(db, upload.file, owner_id)
    finally:
        await run_file_operation(upload.file.close)
