"""Embedding URL checks keep IPv4/IPv6 policy intact without opening real connections."""

import ipaddress

import pytest

from backend.core.config import settings
from backend.engine.memory_rag import embeddings
from backend.utils import path_security


@pytest.mark.parametrize(
    "addresses,allow_local,allowed",
    [
        (["127.0.0.1"], True, True),
        (["::1"], True, True),
        (["192.168.1.10"], True, True),
        (["127.0.0.1"], False, False),
        (["::1"], False, False),
        (["8.8.8.8", "2606:4700:4700::1111"], False, True),
        (["169.254.169.254"], True, False),
        (["100.100.100.200"], True, False),
        (["fd00:ec2::254"], True, False),
        (["8.8.8.8", "169.254.169.254"], True, False),
        ([], True, False),
    ],
)
def test_embedding_policy_checks_every_resolved_address(
    monkeypatch, addresses, allow_local, allowed
):
    resolved = [ipaddress.ip_address(address) for address in addresses]
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_NETWORK_MODELS", allow_local)
    monkeypatch.setattr(path_security, "_resolve_host_ips", lambda _: resolved)
    monkeypatch.setattr(embeddings, "_resolve_host_ips", lambda _: resolved)
    url = "http://embedding.example:11434"
    if allowed:
        assert embeddings.validate_embedding_url(url + "/") == url
    else:
        with pytest.raises(ValueError):
            embeddings.validate_embedding_url(url)
