"""Bound remote image bodies before decoding or persisting them."""

import time

import requests

MAX_IMAGE_BYTES = 32 * 1024 * 1024


def download_image(url: str) -> bytes:
    deadline = time.monotonic() + 60
    with requests.get(url, timeout=(10, 30), stream=True) as response:
        response.raise_for_status()
        length = response.headers.get("Content-Length", "")
        if length.isdigit() and int(length) > MAX_IMAGE_BYTES:
            raise ValueError("Image exceeds the 32 MiB download limit.")
        content = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            if time.monotonic() > deadline:
                raise TimeoutError("Image download exceeded its time limit.")
            if len(content) + len(chunk) > MAX_IMAGE_BYTES:
                raise ValueError("Image exceeds the 32 MiB download limit.")
            content.extend(chunk)
        return bytes(content)
