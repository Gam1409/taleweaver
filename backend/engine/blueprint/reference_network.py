"""Public-only reference connections with DNS pinning and normal TLS hostname validation."""

import asyncio
from ipaddress import IPv6Address
from typing import Any

import httpcore

from backend.engine.blueprint.brief import public_address
from backend.utils.path_security import _resolve_host_ips


class PublicReferenceBackend(httpcore.AsyncNetworkBackend):
    """Resolve once and connect to that IP; a second DNS answer cannot reach the LAN."""

    def __init__(self) -> None:
        self.backend = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        if port not in {80, 443}:
            raise ValueError("Only public HTTP(S) reference ports are allowed.")
        addresses = await asyncio.wait_for(asyncio.to_thread(_resolve_host_ips, host), timeout=5)
        if not addresses or any(not public_address(address) for address in addresses):
            raise ValueError("Reference hostname must resolve exclusively to public addresses.")
        address = addresses[0]
        mapped = address.ipv4_mapped if isinstance(address, IPv6Address) else None
        if mapped is not None and not mapped.is_global:
            raise ValueError("Private IPv4-mapped references are forbidden.")
        # httpcore still owns the original origin hostname and uses it for TLS/SNI.
        return await self.backend.connect_tcp(
            str(address), port, timeout, local_address, socket_options
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        raise ValueError("Unix sockets are not reference sources.")

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
