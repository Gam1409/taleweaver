"""Validate history-backed garment proposals without changing canonical possessions."""

from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

from backend.engine.clothing.body_schema import WearSource
from backend.engine.clothing.recovery_contract import resolve_recovery_item
from backend.engine.clothing.recovery_evidence import evidence_issues, rejected_entry
from backend.engine.clothing.recovery_mentions import mention_checks
from backend.engine.clothing.recovery_placement import restore as restore_placement
from backend.engine.clothing.recovery_policy import classify_action, partition_rejections
from backend.engine.clothing.recovery_schema import RecoveryEntry, RecoveryProposal
from backend.engine.clothing.wear_provenance import stamp_profile
from backend.engine.narrated_items.apply import apply_actions
from backend.engine.narrated_items.errors import ItemFailure
from backend.engine.narrated_items.schema import ItemAction, ItemExtraction


def _source_error(source: dict, source_id: str, action: ItemAction, actor_id: str) -> str:
    if not source:
        return f"Source {source_id}: no matching assistant narration."
    if action.source_owner != actor_id or action.destination_owner != actor_id:
        return "Wrong owner: recovery only accepts the target NPC's own items."
    return ""


def evaluate(
    context: dict,
    proposal: RecoveryProposal,
    detailed: bool,
    session_id: str,
    *,
    diagnostics: list[dict] | None = None,
    selected_indices: set[int] | None = None,
) -> tuple:
    actor = context["actor"]
    actors = {actor["id"]: actor}
    snapshot = deepcopy(context["snapshot"])
    rejected_details = diagnostics if diagnostics is not None else []
    accepted: list[dict] = []
    errors = []
    skipped = []
    roles = {"assistant", "user"} if context.get("allow_player_sources") else {"assistant"}
    sources = {row["id"]: row for row in context["messages"] if row["role"] in roles}
    entries = [
        (index, entry)
        for index, entry in enumerate(proposal.entries)
        if selected_indices is None or index in selected_indices
    ]
    for index, entry in entries:
        action = classify_action(entry.action)
        label = action.new_item.name if action.new_item else str(action.item_id)
        source = sources.get(entry.source_message_id, {})
        source_error = _source_error(source, entry.source_message_id, action, actor["id"])
        if source_error:
            errors.append(f"{label}: {source_error}")
            rejected_details.append(rejected_entry(index, entry, label, [source_error]))
            continue
        try:
            garment = resolve_recovery_item(action, snapshot, actor["id"])
        except ValueError as exc:
            errors.append(str(exc))
            rejected_details.append(rejected_entry(index, entry, label, [str(exc)]))
            continue
        issues = evidence_issues(entry, action, source, garment)
        if issues:
            errors.extend(f"{label}: {reason}" for reason in issues)
            rejected_details.append(rejected_entry(index, entry, label, issues, garment))
            continue
        failures: list[ItemFailure] = []
        changed, additions, _ = apply_actions(
            ItemExtraction.model_validate({"actions": [action]}),
            actors,
            snapshot,
            source["content"],
            detailed=detailed,
            session_id=session_id,
            message_id=f"{entry.source_message_id}:wardrobe:{index}",
            failures=failures,
        )
        if not additions and not failures and garment is not None:
            changed, additions, failures = restore_placement(
                changed, entry, garment, snapshot, detailed
            )
        actors = changed
        blocking, omitted = partition_rejections(
            failures, detailed=detailed, age=actor.get("age_years")
        )
        errors.extend(blocking)
        if blocking:
            rejected_details.append(rejected_entry(index, entry, label, blocking, garment))
        skipped.extend(omitted)
        for addition in additions:
            addition["proposal_index"] = index
            _finish_addition(actors[actor["id"]], addition, entry, index, source)
            identifier = addition["item"]["id"]
            snapshot.items[identifier] = addition["item"]
            snapshot.owners[identifier] = actor["id"]
            snapshot.catalog[identifier] = addition["item"]
            accepted.append(addition)
    return actors, accepted, errors, list(dict.fromkeys(skipped))


def _finish_addition(
    actor: dict, addition: dict, entry: RecoveryEntry, index: int, source: dict
) -> None:
    text = source["content"]
    if source["role"] == "user":
        addition["source_role"] = "user"
    addition["source_message_id"] = entry.source_message_id
    addition["uncovered_regions"] = list(dict.fromkeys(entry.uncovered_regions))
    addition["placement_evidence"] = entry.placement_evidence
    if entry.action.attachment_slot:
        addition["attachment_slot"] = entry.action.attachment_slot
        actor["visual_profile"] = stamp_profile(
            actor.get("visual_profile"),
            f"{entry.source_message_id}:wardrobe:{index}",
            SimpleNamespace(id=entry.source_message_id, content=text, role=source["role"]),
        )
    if entry.uncovered_regions or entry.restore_coverage:
        _set_partial_wear(actor, addition, text)
    if entry.restore_coverage:
        addition["restore_coverage"] = True
    # Only newly recovered acquisitions use the synthetic evaluation source.
    # Placement updates retain the garment's original acquisition provenance.
    for key in ("item_origin", "clothing_origin"):
        origin = addition["item"].get(key)
        if isinstance(origin, dict) and origin.get("source_message_id") == (
            f"{entry.source_message_id}:wardrobe:{index}"
        ):
            origin["source_message_id"] = entry.source_message_id
            if source["role"] == "user":
                origin["source_role"] = "user"
    identifier = addition["item"]["id"]
    for field in ("inventory", "resolved_inventory"):
        actor[field] = [
            addition["item"] if isinstance(row, dict) and row.get("id") == identifier else row
            for row in actor[field]
        ]


def _set_partial_wear(actor: dict, addition: dict, text: str) -> None:
    for worn in actor["visual_profile"]["worn"]:
        if worn["item_id"] == addition["item"]["id"]:
            worn["uncovered_regions"] = addition["uncovered_regions"]
            if addition["uncovered_regions"]:
                worn["source"] = WearSource(
                    source_message_id=addition["source_message_id"],
                    content_hash=sha256(text.encode()).hexdigest(),
                    evidence=addition["placement_evidence"],
                    source_role=addition.get("source_role", "assistant"),
                ).model_dump()
            else:
                worn.pop("source", None)


def evaluated_preview(
    context: dict, proposal: RecoveryProposal, detailed: bool, session_id: str
) -> dict:
    diagnostics: list[dict] = []
    _, accepted, errors, skipped = evaluate(
        context, proposal, detailed, session_id, diagnostics=diagnostics
    )
    return {
        "proposal": proposal.model_dump(),
        "accepted": accepted,
        "errors": errors,
        "skipped": skipped,
        "rejected_entries": diagnostics,
        "mention_checks": mention_checks(context, proposal),
        "rejected_sources": {
            row["id"]: row["content"]
            for row in context["messages"]
            if row["role"]
            in ({"assistant", "user"} if context.get("allow_player_sources") else {"assistant"})
            and any(issue["source_message_id"] == row["id"] for issue in diagnostics)
        },
        "source_roles": {row["id"]: row["role"] for row in context["messages"]},
    }
