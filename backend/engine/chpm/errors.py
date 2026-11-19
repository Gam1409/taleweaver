"""Keep optional-model failures separate from session and persistence failures."""


class ChpmError(ValueError):
    """The host cannot safely complete the requested CHPM operation."""


class RecoverableChpmError(ChpmError):
    """Optional analysis failed without authorizing psychological state changes."""


class InferenceUnavailableError(RecoverableChpmError):
    """A model request failed; shared inference admission still controls dispatch."""


class ProposalRejectedError(RecoverableChpmError):
    """A completed NPC proposal is invalid; shared transport and host state are intact."""

    failure_stage = "proposal_formation"

    def __init__(self, message: str, *, grounding_issues: list[dict] | tuple = ()) -> None:
        super().__init__(message)
        self.grounding_issues = tuple(grounding_issues)
        self.failure_categories = tuple(
            sorted(
                {"formation", *(issue.get("category", "formation") for issue in grounding_issues)}
            )
        )


class GroundingError(ChpmError):
    """A typed cognitive-source failure, distinct from a physical owner rejection."""

    def __init__(self, code: str, field: str, message: str, *, category: str = "formation") -> None:
        super().__init__(message)
        self.code = code
        self.field = field
        self.category = category


class StaleControlError(RuntimeError):
    """An expired host attempt cannot be repaired by another model request."""
