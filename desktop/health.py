"""Readiness checks are local, bounded and tied to the supervised process."""

import http.client
import json
import re


def request(
    port: int,
    path: str,
    *,
    token: str = "",
    method: str = "GET",
    sample: bool = False,
    kind: str = "",
) -> bytes:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1.0)
    try:
        connection.request(method, path, headers={"X-TaleWeaver-Instance": token})
        response = connection.getresponse()
        content_type = response.getheader("Content-Type", "").split(";", 1)[0].lower()
        if kind == "html" and content_type != "text/html":
            raise ValueError("The local frontend is not HTML.")
        if kind == "script" and content_type not in {"application/javascript", "text/javascript"}:
            raise ValueError("The local frontend script is not JavaScript.")
        body = response.read(4096 if sample else 131073)
        if response.status != 200 or len(body) > 131072:
            raise ValueError("Local readiness response was rejected.")
        return body
    finally:
        connection.close()


def ready(port: int, token: str) -> bool:
    """A different server on this port, or a missing frontend, cannot turn green."""
    try:
        health = json.loads(request(port, "/_desktop/health"))
        if health != {"status": "ok", "instance": token}:
            return False
        index = request(port, "/", kind="html")
        if b'id="app"' not in index and b"id='app'" not in index:
            return False
        match = re.search(rb'<script[^>]+src=["\'](/assets/[^"\']+)["\']', index)
        if match is None:
            return False
        script = request(port, match[1].decode("ascii"), sample=True, kind="script")
        return bool(script) and not script.lstrip().lower().startswith((b"<!doctype", b"<html"))
    except (OSError, ValueError, http.client.HTTPException, UnicodeError):
        return False
