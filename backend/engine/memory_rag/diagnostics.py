"""Fixed, content-free diagnostics for the embedding connection test."""

import httpx

_PRIVATE_URL_ERROR = (
    "URL points to a private/loopback address. Set "
    "ALLOW_PRIVATE_NETWORK_MODELS=true to allow local providers."
)


def embedding_test_diagnostic(error: Exception) -> str:
    """Inspect chained failures without exposing URLs, credentials or response bodies."""
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        message = _known_failure(current)
        if message:
            return message
        current = current.__cause__ or current.__context__
    return "Embedding test failed. Check the endpoint, model and server logs."


def _known_failure(error: BaseException) -> str | None:
    if isinstance(error, (TimeoutError, httpx.TimeoutException)):
        return (
            "The embeddings request timed out. The model may still be loading or the server "
            "may be busy. Increase Request timeout and retry after the model has loaded."
        )
    if isinstance(error, httpx.HTTPStatusError):
        return _http_failure(error.response.status_code)
    if isinstance(error, httpx.RequestError):
        return (
            "The TaleWeaver backend could not communicate with the embeddings server. "
            "Check its URL, port, tunnel and proxy settings from the backend computer. "
            "127.0.0.1 refers to the backend's own computer or container."
        )
    if isinstance(error, ValueError) and str(error) == _PRIVATE_URL_ERROR:
        return (
            "Local provider connections are disabled. For your intended local Ollama, set "
            "ALLOW_PRIVATE_NETWORK_MODELS=true in .env and restart the backend."
        )
    return None


def _http_failure(status: int) -> str:
    if status in {401, 403}:
        return "The embeddings server denied access. Check the API key or proxy authentication."
    if status == 404:
        return (
            "The embeddings server returned HTTP 404. Check the base URL and that the selected "
            "model is installed on this server. Ollama must support /api/embed."
        )
    if status == 429:
        return "The embeddings server is rate-limiting requests. Wait and retry."
    if status in {400, 405, 422}:
        return (
            "The embeddings server rejected the request. Check the provider selection, API "
            "endpoint and that the selected model supports embeddings."
        )
    return (
        "The embeddings server returned an HTTP error. Check the server logs for model "
        "loading, memory or proxy failures."
    )
