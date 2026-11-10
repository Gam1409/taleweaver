"""Keep optional-model failures separate from session and persistence failures."""


class ChpmError(ValueError):
    """The host cannot safely complete the requested CHPM operation."""


class RecoverableChpmError(ChpmError):
    """Optional analysis failed without authorizing psychological state changes."""


class InferenceUnavailableError(RecoverableChpmError):
    """A model request failed; shared inference admission still controls dispatch."""


class ProposalRejectedError(RecoverableChpmError):
    """A completed NPC proposal is invalid; shared transport and host state are intact."""
