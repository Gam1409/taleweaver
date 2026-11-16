"""Resource budgets and passive asset policy shared by portable archives."""

import shutil
import zipfile
from collections.abc import Callable, Sequence
from pathlib import PurePosixPath
from typing import BinaryIO, Protocol, cast

MEDIA_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".avif",
        ".svg",
        ".ico",
        ".mp3",
        ".wav",
        ".ogg",
        ".opus",
        ".flac",
        ".m4a",
        ".mp4",
        ".webm",
    }
)
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024
MAX_ENTRY_BYTES = 50 * 1024 * 1024
MAX_ENTRIES = 1000
MAX_COMPRESSION_RATIO = 100


class _ZipTrailerAPI(Protocol):
    _EndRecData: Callable[[BinaryIO], Sequence[object] | None]


def rewind_archive(source: BinaryIO) -> int:
    """Measure an already spooled upload without loading its bytes into memory."""
    source.seek(0, 2)
    size = source.tell()
    source.seek(0)
    if size > MAX_UPLOAD_BYTES:
        raise ValueError("Session archive exceeds the upload budget.")
    return size


def validate_archive_stream(source: BinaryIO) -> None:
    """Bound central-directory allocation before ZipFile reads its complete table."""
    rewind_archive(source)
    # The bounded stdlib parser supports ZIP64 but is absent from public stubs.
    trailer = cast(_ZipTrailerAPI, zipfile)._EndRecData(source)
    if trailer is None:
        raise ValueError("Session archive has no valid ZIP directory.")
    # The end-record layout stores total entries and directory bytes at 4 and 5.
    entries, directory_bytes = trailer[4], trailer[5]
    if not isinstance(entries, int) or not isinstance(directory_bytes, int):
        raise ValueError("Session archive has invalid ZIP directory metadata.")
    if entries > MAX_ENTRIES:
        raise ValueError("Archive contains too many entries.")
    # A 46-byte central header precedes three unsigned-16-bit metadata fields.
    metadata_bound = MAX_ENTRIES * (46 + 3 * zipfile.ZIP_MAX_COMMENT)
    if directory_bytes > metadata_bound:
        raise ValueError("Archive directory exceeds its metadata budget.")
    source.seek(0)


def validate_archive(archive: zipfile.ZipFile) -> None:
    infos = archive.infolist()
    if len(infos) > MAX_ENTRIES:
        raise ValueError("Archive contains too many entries.")
    names: set[str] = set()
    total = 0
    for info in infos:
        path = PurePosixPath(info.filename)
        if (
            info.filename in names
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in info.filename
        ):
            raise ValueError("Archive contains an unsafe or duplicate path.")
        names.add(info.filename)
        total += info.file_size
        if info.file_size > MAX_ENTRY_BYTES or total > MAX_UPLOAD_BYTES:
            raise ValueError("Archive exceeds the unpacked size budget.")
        if info.file_size > MAX_COMPRESSION_RATIO * max(1, info.compress_size):
            raise ValueError("Archive exceeds the compression ratio budget.")
        if (
            not info.is_dir()
            and info.filename.startswith("assets/")
            and path.suffix.lower() not in MEDIA_EXTENSIONS
        ):
            raise ValueError("Archive assets must be images, audio or video.")


def copy_asset(archive: zipfile.ZipFile, info: zipfile.ZipInfo, destination: str) -> None:
    """Copy in bounded chunks; ZipExtFile enforces the validated member size and CRC."""
    with archive.open(info) as source, open(destination, "wb") as target:
        shutil.copyfileobj(source, target, length=64 * 1024)
