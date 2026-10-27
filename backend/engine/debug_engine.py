from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.engine import debug_inspection, debug_mutations, debug_progression
from backend.models.adventure_template import AdventureTemplate
from backend.models.session_state import SessionState
from backend.models.user import User

_HANDLERS = {
    "szene": debug_inspection.debug_szene,
    "entities": debug_inspection.debug_entities,
    "plot": debug_inspection.debug_plot,
    "context": debug_inspection.debug_plot,
    "map": debug_inspection.debug_map,
    "session": debug_inspection.debug_session,
    "log": debug_mutations.debug_log,
    "on": debug_mutations.debug_on,
    "off": debug_mutations.debug_off,
    "npc": debug_mutations.debug_npc,
    "item": debug_mutations.debug_item,
    "award": debug_progression.debug_award,
    "awards": debug_progression.debug_award,
    "game_won": debug_progression.debug_game_won,
    "quest_finished": debug_progression.debug_quest_finished,
    "claim_awards": debug_progression.debug_claim_awards,
    "delete_item": debug_mutations.debug_delete_item,
    "heal": debug_mutations.debug_heal,
    "unhide": debug_mutations.debug_unhide,
    "npc_note": debug_mutations.debug_npc_note,
    "note": debug_mutations.debug_npc_note,
    "moveable": debug_mutations.debug_moveable,
    "open_exit": debug_mutations.debug_open_exit,
    "walkthrough": debug_mutations.debug_walkthrough,
    "game_over": debug_mutations.debug_game_over,
    "engine": debug_inspection.debug_engine,
    "exp": debug_progression.debug_exp,
    "scenes": debug_inspection.debug_scenes,
    "npcs": debug_inspection.debug_npcs,
    "items": debug_inspection.debug_items,
    "exits": debug_inspection.debug_exits,
    "reveal_map": debug_inspection.debug_reveal_map,
    "gen_item": debug_mutations.debug_gen_item,
}


class DebugEngine:
    @staticmethod
    async def handle_debug_command(
        db: AsyncSession,
        state: SessionState,
        args: str,
        user: Optional[User] = None,
        adventure: Optional[AdventureTemplate] = None,
        avatar: Optional[Any] = None,
    ) -> str:
        """Dispatch each debug command to its dedicated implementation."""
        sub = args.split(" ", maxsplit=1)[0].lower() if args else ""
        handler = _HANDLERS.get(sub)
        if handler is not None:
            result = await handler(db, state, args, user, adventure, avatar)
            if result is not None:
                return result
        return "DEBUG USAGE: /debug [on/off | npc drop_items | item dynamic on/off | session | szene | heal | scenes | npcs | items | exits | plot | context | map | reveal_map | log on/off | walkthrough | engine | award(s) | game_won | game_over | quest_finished | claim_awards | delete_item X | kill NPC | open_exit ID | gen_item PROMPT]"
