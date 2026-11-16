"""Versioned renderers over one bilingual-source, English realization plan.

The LLM supplies alternative surfaces, never compiler capabilities or source maps.
All variants retain the same source bindings; compilation selects actual surfaces
without another language-model rewrite.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .visual_plan import MAX_ATOMS, Atom, Proposal, Unit, assemble

NORMALIZATION_VERSION = 1
COMPILER_VERSION = 1


class Surface(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(default="", max_length=2000)
    disposition: Literal["", "best_effort", "tag_binding", "implicit_count"] = ""


class Realization(BaseModel):
    model_config = ConfigDict(extra="forbid")
    atom_id: str = Field(max_length=100)
    subject: str = Field(max_length=200)
    predicate: str = Field(max_length=80)
    target: str = Field(default="", max_length=200)
    value_hash: str = Field(min_length=64, max_length=64)
    description: Surface
    tags: Surface


class EnglishPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    facts: list[Realization] = Field(max_length=MAX_ATOMS)


class Capabilities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: int = COMPILER_VERSION
    family: Literal["generic-english"] = "generic-english"
    format: Literal["description", "tags", "hybrid"]
    actor_binding: Literal["prose", "global_tags", "mixed"]


def capabilities(output_format: str) -> Capabilities:
    bindings = {"description": "prose", "tags": "global_tags", "hybrid": "mixed"}
    if output_format not in bindings:
        raise ValueError("This prompt format has no supported visual-plan compiler.")
    return Capabilities.model_validate(
        {"format": output_format, "actor_binding": bindings[output_format]}
    )


def _unit(fact: Realization, section: Literal["description", "tags"]) -> Unit:
    surface = getattr(fact, section)
    return Unit(
        **fact.model_dump(exclude={"description", "tags"}), **surface.model_dump(), section=section
    )


def validate_plan(atoms: list[Atom], plan: EnglishPlan) -> None:
    """Validate even unused variants before they can enter the reusable cache."""
    for section in ("description", "tags"):
        proposal = Proposal(units=[_unit(fact, section) for fact in plan.facts])
        assemble(atoms, proposal, section)


def _description(atoms: list[Atom], facts: dict[str, Realization]) -> Proposal:
    return Proposal(units=[_unit(facts[a.id], "description") for a in atoms])


def _tags(atoms: list[Atom], facts: dict[str, Realization]) -> Proposal:
    return Proposal(units=[_unit(facts[a.id], "tags") for a in atoms])


def _hybrid(atoms: list[Atom], facts: dict[str, Realization]) -> Proposal:
    # Preserve required bindings in prose, use tags for optional appearance/mood.
    # Missing optional tags may use an available prose realization instead.
    units = []
    for atom in atoms:
        fact = facts[atom.id]
        section: Literal["description", "tags"] = "description"
        if not atom.required and fact.tags.text.strip():
            section = "tags"
        units.append(_unit(fact, section))
    return Proposal(units=units)


def compile_plan(atoms: list[Atom], plan: EnglishPlan, output_format: str) -> dict:
    profile = capabilities(output_format)
    validate_plan(atoms, plan)
    facts = {fact.atom_id: fact for fact in plan.facts}
    renderer = {"description": _description, "tags": _tags, "hybrid": _hybrid}[output_format]
    proposal = renderer(atoms, facts)
    body, limits = assemble(atoms, proposal, output_format)
    return {
        "body": body,
        "proposal": proposal,
        "limitations": limits,
        "capabilities": profile.model_dump(),
        "source_map": source_map(proposal, body),
    }


def source_map(proposal: Proposal, body: str) -> list[dict]:
    """Code-point offsets into actual emitted body; omissions remain in the map."""
    entries = []
    built = ""
    for section in ("description", "tags"):
        selected = [unit for unit in proposal.units if unit.section == section]
        chunk, mapped = _map_section(selected, len(built), bool(built))
        built += chunk
        entries.extend(mapped)
    if built != body:
        raise ValueError("The compiled prompt and its source map disagree.")
    return entries


def _map_section(units: list[Unit], offset: int, previous: bool) -> tuple[str, list[dict]]:
    chunk = ""
    entries = []
    emitted = False
    for unit in units:
        entry: dict[str, Any] = {
            "atom_id": unit.atom_id,
            "subject": unit.subject,
            "predicate": unit.predicate,
            "target": unit.target,
            "value_hash": unit.value_hash,
            "section": unit.section,
            "disposition": unit.disposition,
            "start": None,
            "end": None,
        }
        text = unit.text.strip()
        if text:
            separator = (
                (", " if unit.section == "tags" else " ") if emitted else ("\n" if previous else "")
            )
            chunk += separator
            entry.update(start=offset + len(chunk), end=offset + len(chunk) + len(text))
            chunk += text
            emitted = True
        entries.append(entry)
    return chunk, entries


def final_source_map(body: str, positive: str, mapping: list[dict]) -> dict:
    """Never guess offsets when provider assembly trims or duplicates the body."""
    start = positive.find(body)
    unique = start >= 0 and positive.find(body, start + 1) == -1
    spans = []
    for entry in mapping:
        emitted = unique and entry["start"] is not None
        spans.append(
            {
                **entry,
                "positive_start": start + entry["start"] if emitted else None,
                "positive_end": start + entry["end"] if emitted else None,
            }
        )
    return {
        "offset_unit": "unicode_code_points",
        "final_mapping": "exact" if unique else "unavailable",
        "facts": spans,
    }
