from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from backend.engine.switch_service import SwitchService
from backend.models.world_entity import WorldEntity, WorldExit


class SwitchInteractions:
    @staticmethod
    def _is_switch_entity(entity: WorldEntity | dict[str, Any] | None) -> bool:
        if not entity:
            return False
        if isinstance(entity, dict):
            item_type = str(entity.get("item_type") or "").upper()
            metadata_json = entity.get("metadata_json")
        else:
            item_type = str(getattr(entity, "item_type", "") or "").upper()
            metadata_json = getattr(entity, "metadata_json", None)

        if item_type == "SWITCH":
            return True
        return isinstance(metadata_json, dict) and isinstance(metadata_json.get("switch"), dict)

    @staticmethod
    def _switch_config(entity: WorldEntity) -> dict[str, Any]:
        metadata_json = dict(getattr(entity, "metadata_json", None) or {})
        config = metadata_json.get("switch")
        return config if isinstance(config, dict) else {}

    @staticmethod
    def _parse_switch_args(raw_args: str) -> tuple[str, str, str | None] | None:
        raw = (raw_args or "").strip()
        if not raw:
            return None

        quoted = re.match(r'^\s*"(?P<target>.+?)"\s+(?P<state>\S+)(?:\s+(?P<code>\S+))?\s*$', raw)
        if quoted:
            target = quoted.group("target").strip()
            state = quoted.group("state").strip().upper()
            code = quoted.group("code")
            return target, state, (code.strip() if code else None)

        parts = raw.split()
        if len(parts) < 2:
            return None

        target = parts[0].strip()
        state = parts[1].strip().upper()
        code = parts[2].strip() if len(parts) >= 3 else None
        return target, state, code

    async def _resolve_scene_switch(self, target_hint: str) -> WorldEntity | None:
        hint = (target_hint or "").strip().lower()
        if not hint:
            return None

        ent_res = await self.db.execute(
            select(WorldEntity).where(
                WorldEntity.session_id == self.game_id,
                WorldEntity.entity_type == "OBJECT",
            )
        )
        candidates = ent_res.scalars().all()
        states = self.state.entity_states or {}

        best: tuple[int, WorldEntity] | None = None
        for ent in candidates:
            if not self._is_switch_entity(ent):
                continue

            override = states.get(ent.id, {}) if isinstance(states, dict) else {}
            current_scene_id = override.get("current_scene_id", ent.current_scene_id)
            is_hidden = bool(override.get("is_hidden", ent.is_hidden))
            is_in_inventory = bool(override.get("is_in_inventory", ent.is_in_inventory))
            if current_scene_id != self.state.current_scene_id or is_hidden or is_in_inventory:
                continue

            token = self._switch_match_token(ent, hint)

            if not token:
                continue

            candidate = (len(token), ent)
            if best is None or candidate[0] > best[0]:
                best = candidate

        return best[1] if best else None

    def _switch_story_flags(self) -> dict[str, bool]:
        states = self.state.entity_states or {}
        raw = states.get("__switch_story_flags__")
        if not isinstance(raw, dict):
            return {}
        return {str(k): bool(v) for k, v in raw.items()}

    def _set_switch_story_flag(self, key: str) -> None:
        key_clean = str(key or "").strip()
        if not key_clean:
            return
        states = dict(self.state.entity_states or {})
        flags = states.get("__switch_story_flags__")
        if not isinstance(flags, dict):
            flags = {}
        flags[key_clean] = True
        states["__switch_story_flags__"] = flags
        self.state.entity_states = states
        flag_modified(self.state, "entity_states")

    def _avatar_inventory_ids(self) -> set[str]:
        ids: set[str] = set()
        for item in self.avatar.inventory or []:
            if not isinstance(item, dict):
                continue
            raw_id = str(item.get("id") or "").strip().upper()
            if raw_id:
                ids.add(raw_id)
        return ids

    async def _apply_switch_outcomes(self, outcomes: list[Any], on_state: str) -> list[str]:
        messages: list[str] = []
        for outcome in outcomes:
            if not isinstance(outcome, dict):
                continue
            if str(outcome.get("on_state") or "").strip().upper() != on_state.upper():
                continue
            effects = outcome.get("effects")
            if not isinstance(effects, list):
                continue
            for effect in effects:
                messages.extend(await self._apply_switch_effect(effect))
        return messages

    async def _execute_switch_command(self, switch_args: str) -> str:
        parsed = self._parse_switch_args(switch_args)
        if not parsed:
            return "Usage: /switch <target> <state> [code] (quote target if it contains spaces)."

        target_hint, target_state, provided_code = parsed
        switch_entity = await self._resolve_scene_switch(target_hint)
        if not switch_entity:
            return f"No switch named '{target_hint}' was found in the current scene."

        config = self._switch_config(switch_entity)
        allowed_states, error = self._validate_switch_states(
            config, target_state, switch_entity.name
        )
        if error:
            return error

        session_states = dict(self.state.entity_states or {})
        entry = dict(session_states.get(switch_entity.id) or {})
        configured_current = str(config.get("initial_state") or allowed_states[0]).strip().upper()
        current_state = str(entry.get("switch_state") or configured_current).strip().upper()
        if current_state == target_state:
            return f"{switch_entity.name} is already set to {target_state}."

        transition = SwitchService.resolve_transition(config, current_state, target_state)
        script_context = await self.manager._build_script_context()
        runner = self.manager._get_script_runner()

        if transition is not None:
            allowed, fail_msg = SwitchService.evaluate_transition_gates(
                transition=transition,
                context=script_context,
                provided_code=provided_code,
                avatar_inventory_ids=self._avatar_inventory_ids(),
                story_flags=self._switch_story_flags(),
                switch_name=switch_entity.name,
            )
            if not allowed:
                SwitchService.execute_transition_triggers(
                    runner=runner,
                    config=config,
                    transition=transition,
                    success=False,
                    context=script_context,
                    switch_id=switch_entity.id,
                )
                await self.manager._apply_script_changeset(script_context.changeset)
                return fail_msg or f"{switch_entity.name} does not move."

        entry["switch_state"] = target_state
        session_states[switch_entity.id] = entry
        self.state.entity_states = session_states
        flag_modified(self.state, "entity_states")

        SwitchService.execute_transition_triggers(
            runner=runner,
            config=config,
            transition=transition,
            success=True,
            context=script_context,
            switch_id=switch_entity.id,
        )
        script_messages = await self.manager._apply_script_changeset(script_context.changeset)

        narration = config.get("narration") if isinstance(config.get("narration"), dict) else {}
        state_change_notes = (
            narration.get("on_state_change")
            if isinstance(narration.get("on_state_change"), dict)
            else {}
        )
        state_note = str(state_change_notes.get(target_state) or "").strip()
        trans_success_msg = (
            str(transition.get("success_message") or "").strip() if transition else ""
        )

        outcome_notes = await self._apply_switch_outcomes(
            config.get("outcomes") if isinstance(config.get("outcomes"), list) else [], target_state
        )
        return self._switch_result_message(
            switch_entity.name,
            target_state,
            trans_success_msg,
            state_note,
            outcome_notes,
            script_messages,
        )

    @staticmethod
    def _switch_match_token(ent, hint):
        id_token = str(ent.id or "").strip().lower()
        name_token = str(ent.name or "").strip().lower()
        token = ""
        if id_token and id_token == hint:
            token = id_token
        elif name_token and name_token == hint:
            token = name_token
        elif id_token and id_token in hint:
            token = id_token
        elif name_token and name_token in hint:
            token = name_token

        return token

    async def _apply_switch_effect(self, effect):
        messages = []
        if not isinstance(effect, dict):
            return []
        effect_type = str(effect.get("type") or "").strip().lower()
        if effect_type == "story_flag":
            key = str(effect.get("key") or "").strip()
            if key:
                self._set_switch_story_flag(key)
                messages.append(f"Story flag set: {key}.")
        elif effect_type == "unlock_exit":
            target_id = str(effect.get("target_id") or "").strip()
            if not target_id:
                return []
            exit_res = await self.db.execute(
                select(WorldExit).where(
                    WorldExit.session_id == self.state.session_id,
                    WorldExit.id == target_id,
                )
            )
            ex = exit_res.scalars().first()
            if ex and ex.is_locked:
                ex.is_locked = False
                messages.append(f"Exit unlocked: {ex.label or ex.id}.")
        elif effect_type == "unlock_container":
            target_id = str(effect.get("target_id") or "").strip()
            if not target_id:
                return []
            states = dict(self.state.entity_states or {})
            entry = dict(states.get(target_id) or {})
            entry["locked"] = False
            states[target_id] = entry
            self.state.entity_states = states
            flag_modified(self.state, "entity_states")
            messages.append(f"Container unlocked: {target_id}.")
        return messages

    @staticmethod
    def _validate_switch_states(config, target_state, switch_name):
        states = config.get("states")
        if not isinstance(states, list) or len(states) < 2:
            return [], f"{switch_name} has no valid switch configuration."
        allowed_states = [str(state).strip().upper() for state in states if str(state).strip()]
        if target_state not in allowed_states:
            return (
                [],
                f"Invalid state '{target_state}'. Allowed states: {', '.join(allowed_states)}.",
            )
        return allowed_states, None

    @staticmethod
    def _switch_result_message(
        switch_name, target_state, trans_success_msg, state_note, outcome_notes, script_messages
    ):
        message = f"{switch_name} set to {target_state}."
        if trans_success_msg:
            message = f"{message} {trans_success_msg}"
        if state_note:
            message = f"{message} {state_note}"
        if outcome_notes:
            message = f"{message} {' '.join(outcome_notes)}"
        if script_messages:
            user_script_messages = [
                str(m) for m in script_messages if not str(m).strip().startswith("[DEBUG")
            ]
            if user_script_messages:
                message = f"{message} {' '.join(user_script_messages)}"
        return message
