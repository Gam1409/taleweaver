"""Read one bounded UTF-8 file after session authorization, without asset writes."""

from collections.abc import AsyncGenerator
from pathlib import PurePosixPath
from typing import cast

from fastapi import HTTPException, Request
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from backend.engine.world_info import limits
from backend.engine.world_info.types import SourceFormat, validate_text

MAX_MULTIPART_BYTES = limits.MAX_SOURCE_BYTES + 16_384


class UploadTooLarge(MultiPartException):
    """The whole multipart stream exceeded its bounded envelope."""


async def _bounded_stream(request: Request) -> AsyncGenerator[bytes, None]:
    total = 0
    async for part in request.stream():
        total += len(part)
        if total > MAX_MULTIPART_BYTES:
            raise UploadTooLarge("World Info upload exceeds the file size limit.")
        yield part


def _filename(value: str | None) -> tuple[str, SourceFormat]:
    filename = PurePosixPath((value or "").replace("\\", "/")).name
    if not filename or len(filename) > 255:
        raise HTTPException(422, "Choose a filename with 1 to 255 characters.")
    validate_text(filename)
    extension = PurePosixPath(filename).suffix.lower().lstrip(".")
    if extension not in {"md", "json"}:
        raise HTTPException(422, "Upload a .md or .json file.")
    return filename, cast(SourceFormat, extension)


async def read_upload(request: Request, *, replacing: bool = False) -> dict:
    if not request.headers.get("content-type", "").lower().startswith("multipart/form-data;"):
        raise HTTPException(422, "Upload one file using multipart form data.")
    parser = MultiPartParser(
        request.headers, _bounded_stream(request), max_files=1, max_fields=1, max_part_size=1024
    )
    form = None
    try:
        form = await parser.parse()
        pairs = form.multi_items()
        allowed = {"file", "expected_version" if replacing else "title"}
        if len(pairs) != len(set(form.keys())) or set(form.keys()) - allowed:
            raise HTTPException(422, "Unexpected or repeated upload field.")
        file = form.get("file")
        if not isinstance(file, UploadFile):
            raise HTTPException(422, "Choose one .md or .json file.")
        filename, format = _filename(file.filename)
        data = await file.read(limits.MAX_SOURCE_BYTES + 1)
        if len(data) > limits.MAX_SOURCE_BYTES:
            raise HTTPException(413, "World Info file exceeds the size limit.")
        return _content_fields(form, data, filename, format, replacing)
    except UploadTooLarge:
        raise HTTPException(413, "World Info upload exceeds the size limit.") from None
    except (MultiPartException, UnicodeDecodeError):
        raise HTTPException(422, "Upload one valid UTF-8 .md or .json file.") from None
    finally:
        try:
            if form is not None:
                await form.close()
        finally:
            # Direct handles still close when asynchronous form cleanup is interrupted.
            for temporary_file in parser._files_to_close_on_error:
                temporary_file.close()


def _content_fields(
    form: FormData, data: bytes, filename: str, format: SourceFormat, replacing: bool
) -> dict:
    result: dict = {"filename": filename, "format": format, "content": data.decode("utf-8")}
    if not replacing:
        title = form.get("title")
        if title is not None and not isinstance(title, str):
            raise HTTPException(422, "Source title must be text.")
        return {**result, "title": title}
    expected = form.get("expected_version")
    if (
        not isinstance(expected, str)
        or not expected.isascii()
        or not expected.isdigit()
        or len(expected) > len(str(limits.MAX_COUNTER))
    ):
        raise HTTPException(422, "A positive source version is required.")
    if not 1 <= int(expected) < limits.MAX_COUNTER:
        raise HTTPException(422, "A positive source version is required.")
    return {**result, "expected_version": int(expected)}
