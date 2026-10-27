from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm.attributes import flag_modified

from backend.api.routes.adventures.gameplay_logic import (
    WALKTHROUGH_REVEAL_COST,
)
from backend.core.awards import SPOILER_SEEKER_AWARD


async def reveal_walkthrough(self, command):
    self.avatar.exp = (self.avatar.exp or 0) - WALKTHROUGH_REVEAL_COST
    self.state.is_walkthrough_revealed = True
    flag_modified(self.avatar, "exp")
    flag_modified(self.state, "is_walkthrough_revealed")

    # Grant universal negative award
    award_key = SPOILER_SEEKER_AWARD["key"]
    now = datetime.utcnow().isoformat()
    user_awards = list(self.user.earned_awards or [])
    adv_id = (
        self.manager.adventure.id
        if (hasattr(self.manager, "adventure") and self.manager.adventure)
        else (getattr(self.avatar, "template_id", None) or self.state.template_id or "")
    )
    adv_title = (
        self.manager.adventure.title
        if (hasattr(self.manager, "adventure") and self.manager.adventure)
        else "Adventure"
    )
    already_earned = any(
        ea.get("key") == award_key
        and (ea.get("adventure_id") == adv_id or ea.get("session_id") == self.state.session_id)
        for ea in user_awards
    )
    if not already_earned:
        user_awards.append(
            {
                "key": award_key,
                "title": SPOILER_SEEKER_AWARD["title"],
                "description": SPOILER_SEEKER_AWARD["description"],
                "tier": SPOILER_SEEKER_AWARD["tier"],
                "requirement": SPOILER_SEEKER_AWARD["requirement"],
                "template_id": adv_id,
                "adventure_id": adv_id,
                "adventure_title": adv_title,
                "session_id": self.state.session_id,
                "earned_at": now,
            }
        )
        self.user.earned_awards = user_awards
        flag_modified(self.user, "earned_awards")
        await self.manager._save_chat_message(
            "system",
            f"Negative award received: {SPOILER_SEEKER_AWARD['title']} (-{WALKTHROUGH_REVEAL_COST} XP)",
        )

    command.response = f"Walkthrough unlocked! (-{WALKTHROUGH_REVEAL_COST} XP) You can view the walkthrough permanently via the menu."
