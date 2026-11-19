"""Private, bounded provenance of an actor's own selected words; never world evidence."""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from backend.engine import turn_controls

Identifier = Annotated[str, Field(min_length=1, max_length=100)]


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("A selected phrase cannot be blank.")
    return value


Text = Annotated[str, Field(min_length=1, max_length=400), AfterValidator(_nonblank)]
PassageId = Literal["p0", "p1"]
NonEffect = Literal["offer", "past", "negated", "future", "incidental"]
Unresolved = Literal["ambiguous", "unsupported_effect", "unavailable_target"]


class SourceContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)


class Phrase(SourceContract):
    text: Text
    target_refs: tuple[Identifier, ...] = Field(default=(), max_length=4)

    @model_validator(mode="after")
    def meaningful(self) -> "Phrase":
        if not self.text.strip() or len(set(self.target_refs)) != len(self.target_refs):
            raise ValueError("Select nonempty own words and distinct observed references.")
        return self


Choice = Text | Phrase


class Passage(Phrase):
    passage_id: PassageId
    ordinal: int = Field(ge=0, le=1)
    start: int = Field(ge=0, le=400)
    end: int = Field(ge=1, le=400)

    @model_validator(mode="after")
    def exact_span(self) -> "Passage":
        if (self.passage_id, self.start, self.end) != (
            f"p{self.ordinal}",
            0,
            len(self.text),
        ):
            raise ValueError("A selected phrase must keep its exact host span and ordinal.")
        return self


class Selection(SourceContract):
    control: turn_controls.Operation
    passages: tuple[Passage, ...] = Field(min_length=1, max_length=2)
    source_scope: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def sealed(self) -> "Selection":
        if (
            self.control.tool != "resolve_selected_steps"
            or not self.control.actor_id
            or [row.ordinal for row in self.passages] != list(range(len(self.passages)))
            or self.source_scope != scope_hash(self.control, self.passages)
        ):
            raise ValueError("Selected phrases require their captured actor and source binding.")
        return self


def scope_hash(control: turn_controls.Operation, passages: tuple[Passage, ...]) -> str:
    return turn_controls.fingerprint(
        {"control": control.model_dump(), "passages": [row.model_dump() for row in passages]}
    )


def capture(control: dict, actor_id: str, choices: list[Choice]) -> Selection:
    if not 1 <= len(choices) <= 2:
        raise ValueError("Select one or two bounded own phrases.")
    operation = turn_controls.operation(control, "resolve_selected_steps", actor_id=actor_id)
    phrases = [Phrase(text=row) if isinstance(row, str) else row for row in choices]
    passages = tuple(
        Passage(
            **phrase.model_dump(),
            passage_id="p0" if index == 0 else "p1",
            ordinal=index,
            start=0,
            end=len(phrase.text),
        )
        for index, phrase in enumerate(phrases)
    )
    return Selection(
        control=operation, passages=passages, source_scope=scope_hash(operation, passages)
    )


class ActionSource(SourceContract):
    ordinal: int = Field(ge=0, le=1)
    operation_id: Identifier
    tool: Identifier
    depends_on: Identifier | None = None


class ResolutionSource(SourceContract):
    passage_id: PassageId
    disposition: Literal["action", "no_effect", "unresolved"]
    reason: NonEffect | Unresolved | None = None
    remainder: NonEffect | None = None
    actions: tuple[ActionSource, ...] = Field(default=(), max_length=2)

    @model_validator(mode="after")
    def disposition_matches(self) -> "ResolutionSource":
        if self.disposition == "action":
            if not self.actions or self.reason is not None:
                raise ValueError("An action source requires its issued operations only.")
            return self
        allowed = (
            {"offer", "past", "negated", "future", "incidental"}
            if self.disposition == "no_effect"
            else {"ambiguous", "unsupported_effect", "unavailable_target"}
        )
        if self.actions or self.remainder is not None or self.reason not in allowed:
            raise ValueError("A non-effect or unresolved source cannot certify an operation.")
        return self


class SelectionTrace(SourceContract):
    selection: Selection
    resolution_call_id: str | None = Field(default=None, max_length=128)
    resolutions: tuple[ResolutionSource, ...] = Field(default=(), max_length=2)

    @model_validator(mode="after")
    def source_order(self) -> "SelectionTrace":
        if self.resolutions and [row.passage_id for row in self.resolutions] != [
            row.passage_id for row in self.selection.passages
        ]:
            raise ValueError("Resolution provenance must account for each selected phrase once.")
        actions = [action for row in self.resolutions for action in row.actions]
        if len(actions) > 2 or [row.ordinal for row in actions] != list(range(len(actions))):
            raise ValueError("Resolved actions must keep their bounded host order.")
        if len({row.operation_id for row in actions}) != len(actions):
            raise ValueError("One operation cannot be borrowed by another source step.")
        dependencies = [None, *(row.operation_id for row in actions[:-1])]
        if [row.depends_on for row in actions] != dependencies[: len(actions)]:
            raise ValueError("A dependency must identify the immediately preceding operation.")
        return self


def for_context(trace: SelectionTrace) -> dict:
    """One request binding is retained on the host, not repeated in model history."""
    return {
        "source_scope": trace.selection.source_scope,
        "passages": [
            row.model_dump(include={"passage_id", "text"}) for row in trace.selection.passages
        ],
        "resolutions": [row.model_dump(exclude_none=True) for row in trace.resolutions],
    }
