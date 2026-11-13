"""Separate malformed structured output from request and inference availability errors."""


class StructuredOutputError(ValueError):
    """A completed model response failed the existing structured output contract."""
