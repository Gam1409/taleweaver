"""Safe provider failures without response bodies, URLs or credentials."""


class ImageProviderError(ValueError):
    def __init__(self, provider: str, status: int) -> None:
        reason = {
            401: "authentication failed; check the API key",
            403: "access denied; check provider permissions",
            429: "quota or rate limit reached; retry later",
        }.get(
            status, "service request failed; retry later" if status >= 500 else "request rejected"
        )
        self.status = status
        self.retriable = status == 429 or status >= 500
        super().__init__(f"{provider}: {reason} (HTTP {status}).")
