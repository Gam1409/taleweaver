from copy import deepcopy
from datetime import datetime

from sqlalchemy.orm.attributes import flag_modified


async def debug_award(db, state, args, user=None, adventure=None, avatar=None):
    if adventure is None or user is None:
        return "DEBUG ERROR: Award command requires adventure and user context."

    all_awards = adventure.awards or []
    if not all_awards:
        return "DEBUG: This adventure has no awards defined."

    updated_awards = deepcopy(all_awards)
    granted: list[str] = []
    now = datetime.utcnow().isoformat()

    for award in updated_awards:
        if award.get("is_earned"):
            continue  # already earned — skip

        award["is_earned"] = True
        a_key = award.get("key", "")
        granted.append(f"  [{award.get('tier', '?').upper()}] {award.get('title', a_key)}")

        # Persist to user profile (deduplicated)
        user_awards = list(user.earned_awards or [])
        title = award.get("title") or a_key or "Unknown Award"
        dedupe_key = a_key or title
        if not any(
            (ea.get("key") or ea.get("title")) == dedupe_key
            and ea.get("adventure_id") == adventure.id
            for ea in user_awards
        ):
            user_awards.append(
                {
                    "key": dedupe_key,
                    "title": title,
                    "description": award.get("description"),
                    "tier": award.get("tier"),
                    "adventure_id": adventure.id,
                    "adventure_title": adventure.title,
                    "session_id": state.id,
                    "earned_at": now,
                }
            )
            user.earned_awards = user_awards
            flag_modified(user, "earned_awards")

    if not granted:
        return "DEBUG: All awards are already earned."

    adventure.awards = updated_awards
    flag_modified(adventure, "awards")

    lines = ["[DEBUG] All adventure awards granted:"] + granted
    return "\n".join(lines)


async def debug_game_won(db, state, args, user=None, adventure=None, avatar=None):
    if state.quests:
        new_quests = deepcopy(state.quests)
        for q in new_quests:
            if q.get("is_main"):
                q["status"] = "completed"
        state.quests = new_quests
        flag_modified(state, "quests")
    return "[TRIGGER_GAME_COMPLETED] Debug: Manual victory trigger."


async def debug_quest_finished(db, state, args, user=None, adventure=None, avatar=None):
    if not state.quests:
        return "DEBUG: No quests found in session state."
    new_quests = deepcopy(state.quests)
    target = next((q for q in new_quests if q.get("status") == "open"), None)
    if target:
        target["status"] = "completed"
        state.quests = new_quests
        flag_modified(state, "quests")
        return f"DEBUG: Quest '{target.get('title') or target.get('id')}' marked as completed."
    return "DEBUG: No open quests found to finish."


async def debug_claim_awards(db, state, args, user=None, adventure=None, avatar=None):
    return await debug_award(db, state, "awards", user, adventure, avatar)


async def debug_exp(db, state, args, user=None, adventure=None, avatar=None):
    parts = args.split(" ")
    if len(parts) < 2:
        return "DEBUG ERROR: Usage: /debug exp [AMOUNT]"
    try:
        amount = int(parts[1])
    except ValueError:
        return "DEBUG ERROR: Amount must be an integer."

    if not avatar:
        return "DEBUG ERROR: Avatar context missing."
    avatar.exp = (avatar.exp or 0) + amount
    return f"DEBUG: Granted {amount} XP to {avatar.name}. New total: {avatar.exp}"
