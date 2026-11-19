"""Diagnose bounded proposal grounds without granting knowledge or changing a choice."""

from copy import deepcopy

from pydantic import TypeAdapter, ValidationError

from backend.engine.chpm import appraisal, experience, motivation_diagnostics, proposal_references
from backend.engine.chpm.appraisal_context import Window
from backend.engine.chpm.appraisal_contracts import Assessment, FeltExperience, Reference, Revision
from backend.engine.chpm.core.errors import TransitionError
from backend.engine.chpm.errors import ChpmError, GroundingError
from backend.engine.chpm.host_state import Mind
from backend.engine.chpm.motivation import Catalogue
from backend.engine.chpm.proposal_references import Experience as WireExperience
from backend.engine.chpm.quote_references import References


def _issue(index: int, error: GroundingError) -> dict:
    return {
        "loc": ("experiences", index, error.field),
        "type": error.code,
        "msg": str(error),
        "category": error.category,
    }


def _proposal(raw: dict, references: References | None) -> FeltExperience:
    if references is None:
        return FeltExperience.model_validate(deepcopy(raw))
    wire = WireExperience.model_validate(deepcopy(raw))
    # Resolve through this prepared observer's table. A foreign/stale handle cannot
    # become a quotation merely because another response used the same alias.
    if any(c.fragment_id not in references.quotes for c in wire.citations):
        raise GroundingError(
            "experience_visible_source",
            "citations",
            "Use exact fragment IDs from this observer's current supplied window.",
            category="forbidden_knowledge",
        )
    return FeltExperience.model_validate(
        {
            **wire.model_dump(),
            "citations": [references.quote(c.fragment_id) for c in wire.citations],
        }
    )


def _experience(
    raw: dict,
    index: int,
    mind: Mind,
    window: Window,
    catalogue: Catalogue,
    references: References | None,
    message_id: str,
) -> list[dict]:
    try:
        proposal = _proposal(raw, references)
    except ValidationError:
        return _partial_experience(raw, index, mind, window, catalogue, references, message_id)
    except GroundingError as error:
        wire = WireExperience.model_validate(deepcopy(raw))
        personal = experience.personal_errors(
            mind, wire.about_id, wire.personal_motive_ids, window, catalogue
        )
        return [_issue(index, issue) for issue in [*personal, error]]
    errors = experience.grounding_errors(mind, proposal, window, catalogue, message_id, index=index)
    if errors:
        return [_issue(index, error) for error in errors]
    try:
        # The existing reducer also checks reused evidence roots. Work only on
        # its returned immutable snapshot; diagnosis never publishes an estimate.
        experience.accept(mind, [proposal], window, catalogue, message_id=message_id)
    except TransitionError:
        return [
            _issue(
                index,
                GroundingError(
                    "experience_transition",
                    "citations",
                    "Retain existing estimates or cite genuine new observed grounds; repeated roots are not a new trigger.",
                ),
            )
        ]
    return []


def _partial_experience(
    raw: dict,
    index: int,
    mind: Mind,
    window: Window,
    catalogue: Catalogue,
    references: References | None,
    message_id: str,
) -> list[dict]:
    # A malformed explanation must not hide independently valid source fields.
    # Validate each slice through the original field contract; never construct an
    # accepted proposal or reducer event from this diagnostic-only partial view.
    schema = WireExperience if references is not None else FeltExperience
    errors = []
    try:
        personal = TypeAdapter(
            schema.model_fields["personal_motive_ids"].rebuild_annotation()
        ).validate_python(raw.get("personal_motive_ids"))
        about = TypeAdapter(schema.model_fields["about_id"].rebuild_annotation()).validate_python(
            raw.get("about_id")
        )
        errors.extend(experience.personal_errors(mind, about, personal, window, catalogue))
    except ValidationError:
        pass
    try:
        citations = TypeAdapter(
            schema.model_fields["citations"].rebuild_annotation()
        ).validate_python(raw.get("citations"))
    except ValidationError:
        return [_issue(index, error) for error in errors]
    if references is not None:
        if any(c.fragment_id not in references.quotes for c in citations):
            return [
                *[_issue(index, error) for error in errors],
                _issue(
                    index,
                    GroundingError(
                        "experience_visible_source",
                        "citations",
                        "Use exact fragment IDs from this observer's current supplied window.",
                        category="forbidden_knowledge",
                    ),
                ),
            ]
        citations = tuple(
            Reference.model_validate(references.quote(c.fragment_id)) for c in citations
        )
    errors.extend(experience.citation_errors(mind, citations, window, message_id, index=index))
    return [_issue(index, error) for error in errors]


def _appraisal(
    field: str,
    index: int,
    row: dict,
    mind: Mind,
    window: Window,
    references: References | None,
    message_id: str,
) -> list[dict]:
    def issue(code: str, path: str, message: str, category: str = "forbidden_knowledge") -> dict:
        return {"loc": (field, index, path), "type": code, "msg": message, "category": category}

    try:
        raw = deepcopy(row)
        errors = []
        selected: (
            proposal_references.NewBelief | proposal_references.Revision | Assessment | Revision
        )
        if references is not None:
            schema = (
                proposal_references.NewBelief
                if field == "new_beliefs"
                else proposal_references.Revision
            )
            wire = schema.model_validate(raw)
            selected = wire
            if any(c.fragment_id not in references.quotes for c in wire.citations):
                errors.append(
                    issue(
                        "appraisal_visible_source",
                        "citations",
                        "Select evidence from this observer's current supplied window.",
                    )
                )
            else:
                raw["citations"] = [references.quote(c.fragment_id) for c in wire.citations]
        else:
            selected = (
                Assessment.model_validate(raw)
                if field == "new_beliefs"
                else Revision.model_validate(raw)
            )
        if (
            isinstance(selected, (proposal_references.Revision, Revision))
            and selected.belief_id not in window.beliefs
        ):
            errors.append(
                issue(
                    "appraisal_belief",
                    "belief_id",
                    "Select a belief supplied for this observer; unavailable memory grants no knowledge.",
                )
            )
        if (
            isinstance(selected, (proposal_references.NewBelief, Assessment))
            and selected.about_id not in window.subjects
        ):
            errors.append(
                issue(
                    "appraisal_subject",
                    "about_id",
                    "Select a subject supplied for this observer.",
                )
            )
        if errors:
            return errors
        proposal = (
            Assessment.model_validate(raw)
            if field == "new_beliefs"
            else Revision.model_validate(raw)
        )
    except ValidationError:
        return []
    try:
        appraisal.accept(mind, [proposal], window, message_id=message_id)
    except (ChpmError, TransitionError):
        return [
            issue(
                "appraisal_grounding",
                "citations",
                "Use exact available evidence without duplicating grounds or changing the retained proposition.",
                "formation",
            )
        ]
    return []


def _appraisals(
    candidate: dict, mind: Mind, window: Window, references: References | None, message_id: str
) -> list[dict]:
    errors = []
    for field in ("new_beliefs", "belief_revisions"):
        rows = candidate.get(field, [])
        if not isinstance(rows, list) or len(rows) > 2:
            continue
        valid = ((index, row) for index, row in enumerate(rows) if isinstance(row, dict))
        for index, row in valid:
            errors.extend(_appraisal(field, index, row, mind, window, references, message_id))
    return errors


def inspect(
    candidate: dict,
    catalogue: Catalogue,
    mind: Mind,
    window: Window,
    references: References | None,
    *,
    message_id: str,
) -> list[dict]:
    errors = [
        {
            **error,
            "category": "forbidden_knowledge"
            if error["type"] == "motive_unavailable"
            else "formation",
        }
        for error in motivation_diagnostics.inspect(candidate, catalogue)
    ]
    if references is not None and candidate.get("reference_scope") != references.scope:
        return [
            *errors,
            {
                "loc": ("reference_scope",),
                "type": "grounding_reference_scope",
                "msg": "Use this observer's current reference_scope; foreign source aliases grant no knowledge.",
                "category": "formation"
                if candidate.get("reference_scope") is None
                else "forbidden_knowledge",
            },
        ]
    errors.extend(_appraisals(candidate, mind, window, references, message_id))
    rows = candidate.get("experiences", [])
    if not isinstance(rows, list) or len(rows) > 2:
        return errors
    seen = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        errors.extend(_experience(row, index, mind, window, catalogue, references, message_id))
        key = tuple(row.get(field) for field in ("channel", "dimension", "about_id"))
        if not all(isinstance(value, str) and value for value in key[:2]) or (
            key[2] is not None and not isinstance(key[2], str)
        ):
            continue
        if key in seen:
            errors.append(
                _issue(
                    index,
                    GroundingError(
                        "experience_duplicate_dimension",
                        "dimension",
                        "CHPM repeats an affect/need dimension in one batch.",
                    ),
                )
            )
        seen.add(key)
    return errors
