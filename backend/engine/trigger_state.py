"""Persist the specific state changes supported by transition trigger scripts."""

from sqlalchemy.orm.attributes import flag_modified

from backend.models.session_state import SessionState


def apply_trigger_changes(state: SessionState, changeset) -> None:
    """Apply variable, entity and exit updates in the original trigger order."""
    if not (changeset.var_updates or changeset.entity_updates or changeset.exit_updates):
        return
    _apply_trigger_entity_changes(state, changeset)
    if changeset.exit_updates:
        _apply_trigger_exit_changes(state, changeset.exit_updates)


def _apply_trigger_entity_changes(state: SessionState, changeset) -> None:
    cur_states = dict(state.entity_states or {})
    if changeset.var_updates:
        sv = dict(cur_states.get("__script_vars__", {}))
        sv.update(changeset.var_updates)
        cur_states["__script_vars__"] = sv
    for upd in changeset.entity_updates:
        eid = upd.get("entity_id")
        if not eid:
            continue
        st = dict(cur_states.get(eid, {}))
        st.update({key: value for key, value in upd.items() if key != "entity_id"})
        cur_states[eid] = st
    state.entity_states = cur_states
    flag_modified(state, "entity_states")


def _apply_trigger_exit_changes(state: SessionState, updates: list[dict]) -> None:
    exit_states = dict(state.exit_states or {})
    for update in updates:
        key = f"{update['from_scene_id']}:{update['to_scene_id']}"
        item = dict(exit_states.get(key, {}))
        item["is_locked"] = update["is_locked"]
        if "lock_description" in update:
            item["lock_description"] = update["lock_description"]
        exit_states[key] = item
    state.exit_states = exit_states
    flag_modified(state, "exit_states")
