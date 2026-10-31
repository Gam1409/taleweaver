"""Resource budgets and passive asset policy shared by portable archives."""

import shutil
import zipfile
from pathlib import PurePosixPath

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
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
MAX_ENTRY_BYTES = 50 * 1024 * 1024
MAX_ENTRIES = 1000
MAX_COMPRESSION_RATIO = 100


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
