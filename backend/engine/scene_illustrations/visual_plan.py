"""Deterministic, language-independent inventory of frozen public scene facts."""

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

VERSION = 1
MAX_ATOMS = 160


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


class Atom(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    subject: str
    predicate: str
    target: str = ""
    value: Any
    required: bool = True


class Unit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    atom_id: str = Field(max_length=100)
    subject: str = Field(max_length=200)
    predicate: str = Field(max_length=80)
    target: str = Field(default="", max_length=200)
    value_hash: str = Field(min_length=64, max_length=64)
    text: str = Field(default="", max_length=2000)
    section: Literal["description", "tags"]
    disposition: Literal["", "best_effort", "tag_binding", "implicit_count"] = ""


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    units: list[Unit] = Field(max_length=MAX_ATOMS)


class Issue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    atom_id: str = Field(max_length=100)
    reason: Literal["omission", "translation", "contradiction", "unsupported", "uncertain"]


class Audit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["passed", "failed", "inconclusive"]
    issues: list[Issue] = Field(default_factory=list, max_length=MAX_ATOMS)


def _atom(
    path: str, subject: str, predicate: str, value: Any, *, target: str = "", required: bool = True
) -> Atom:
    return Atom(
        id="f_" + fingerprint(path)[:24],
        subject=subject,
        predicate=predicate,
        target=target,
        value=value,
        required=required,
    )


def _character(person: dict, index: int, known: set[str]) -> list[Atom]:
    subject = str(person.get("id") or f"local:characters/{index}")
    path = f"/characters/{index}"
    atoms = [_atom(path, subject, "present", person.get("name") or "")]
    for key in ("posture", "position", "appearance", "clothing"):
        if person.get(key):
            atoms.append(
                _atom(
                    f"{path}/{key}",
                    subject,
                    key,
                    person[key],
                    required=key in {"posture", "position"},
                )
            )
    tokens = person.get("clothing_tokens") or []
    if not isinstance(tokens, list) or any(not isinstance(t, str) for t in tokens):
        raise ValueError("The saved clothing tokens are malformed.")
    for i, token in enumerate(tokens):
        atoms.append(_atom(f"{path}/clothing_tokens/{i}", subject, "worn", token))
    placement = person.get("placement")
    if isinstance(placement, dict) and placement.get("relation") not in (None, "unknown"):
        target = str(placement.get("target") or "")
        if placement.get("target_kind") == "character" and target not in known:
            raise ValueError("The saved scene has an unresolved character placement.")
        if placement.get("target_kind") == "scene_object":
            target = "local:" + path + "/placement/target"
        atoms.append(_atom(path + "/placement", subject, "placement", placement, target=target))
    if person.get("managed_clothing") and not person.get("clothing_tokens"):
        atoms.append(_atom(path + "/clothing_unknown", subject, "clothing_unknown", True))
    return atoms


def inventory(facts: dict) -> list[Atom]:
    """No passage extraction, tokenization, translation or live-world lookups."""
    if not isinstance(facts, dict):
        raise ValueError("The saved scene has no usable visual facts.")
    people = facts.get("characters")
    if people is not None and not isinstance(people, list):
        raise ValueError("The saved cast is malformed.")
    people = people or []
    if any(not isinstance(person, dict) for person in people):
        raise ValueError("The saved cast is malformed.")
    ids = [str(person.get("id") or f"local:characters/{i}") for i, person in enumerate(people)]
    if len(ids) != len(set(ids)):
        raise ValueError("The saved scene has ambiguous character identifiers.")
    atoms = (
        [_atom("/characters/count", "scene", "cast_count", len(people))]
        if "characters" in facts
        else []
    )
    for index, person in enumerate(people):
        atoms.extend(_character(person, index, set(ids)))
    atoms.extend(_props(facts.get("props") or []))
    for key in ("setting", "lighting", "visible_action"):
        if facts.get(key):
            atoms.append(_atom("/" + key, "scene", key, facts[key], required=False))
    if not atoms or len(atoms) > MAX_ATOMS:
        raise ValueError(
            "The saved visual facts exceed plan limits or are unavailable. Use Legacy preparation."
        )
    return atoms


def _props(items: list) -> list[Atom]:
    if not isinstance(items, list):
        raise ValueError("The saved props are malformed.")
    atoms = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError("The saved scene has a malformed prop.")
        subject = str(item.get("item_id") or f"local:props/{index}")
        path = f"/props/{index}"
        atoms.append(
            _atom(
                path,
                subject,
                "prop",
                item.get("name") or "",
                target=str(item.get("owner_id") or ""),
            )
        )
        if item.get("spatial_position"):
            atoms.append(
                _atom(path + "/position", subject, "prop_position", item["spatial_position"])
            )
    return atoms


def assemble(atoms: list[Atom], proposal: Proposal, output_format: str) -> tuple[str, list[dict]]:
    known = {atom.id: atom for atom in atoms}
    units = {unit.atom_id: unit for unit in proposal.units}
    if len(units) != len(proposal.units) or units.keys() != known.keys():
        raise ValueError("Every saved fact needs exactly one output unit or permitted limitation.")
    limitations = []
    sections: dict[str, list[str]] = {"description": [], "tags": []}
    cast_size = next((a.value for a in atoms if a.predicate == "cast_count"), None)
    for atom in atoms:
        unit = units[atom.id]
        _validate_unit(atom, unit, output_format)
        if unit.disposition:
            limitations.append({"atom_id": atom.id, "reason": unit.disposition})
        elif unit.text:
            sections[unit.section].append(unit.text.strip())
        if (
            unit.section == "tags"
            and cast_size != 1
            and atom.predicate in {"worn", "posture", "placement"}
        ):
            limitations.append({"atom_id": atom.id, "reason": "global_tag_binding"})
    body = " ".join(sections["description"])
    body = "\n".join(part for part in (body, ", ".join(sections["tags"])) if part)
    if not body or len(body) > 12000:
        raise ValueError("The visual plan produced an empty or oversized prompt.")
    return body, limitations


def _validate_unit(atom: Atom, unit: Unit, output_format: str) -> None:
    if unit.value_hash != fingerprint(atom.value):
        raise ValueError("A visual unit changed its source value binding.")
    if (unit.subject, unit.predicate, unit.target) != (atom.subject, atom.predicate, atom.target):
        raise ValueError("A visual unit changed a saved subject, object or relation binding.")
    if output_format not in {"hybrid", unit.section}:
        raise ValueError("A visual unit does not match the selected prompt format.")
    allowed = {""}
    if not atom.required:
        allowed.add("best_effort")
    if atom.predicate == "cast_count":
        allowed.add("implicit_count")
    if output_format == "tags" and atom.predicate in {"placement", "prop_position"}:
        allowed.add("tag_binding")
    if unit.disposition not in allowed or bool(unit.text.strip()) == bool(unit.disposition):
        raise ValueError("A saved fact was omitted without an admissible limitation.")
