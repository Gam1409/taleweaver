"""Stable failure contract shared by pure transition modules."""


class TransitionError(ValueError):
    """Reject the whole transition; the caller retains the previous snapshot."""
