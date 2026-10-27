import logging
from typing import Any, Optional

from sqlalchemy.orm.attributes import flag_modified

from backend.models.avatar import Avatar
from backend.models.session_state import SessionState

logger = logging.getLogger(__name__)


def evaluate_sequence_progress(
    adventure: Any,
    state: SessionState,
    avatar: Avatar,
    new_inventory_items: Optional[list[Any]] = None,
    new_scene_id: Optional[str] = None,
    updated_entities: Optional[list[Any]] = None,
    force_complete: bool = False,
    script_context: Optional[Any] = None,
) -> list[str]:
    """Evaluates whether current active sequence hard rules (or forced completion) are met.

    If conditions are met, awards XP to the avatar, advances state.active_sequence_id,
    and returns descriptive system messages.
    """
    if not adventure or not getattr(adventure, "sequences", None):
        return []
    raw_sequences = adventure.sequences
    if not isinstance(raw_sequences, list) or len(raw_sequences) == 0:
        return []

    sequences = sorted(
        [s for s in raw_sequences if isinstance(s, dict)],
        key=lambda x: x.get("order", 1),
    )
    if not sequences:
        return []

    active_seq_id = getattr(state, "active_sequence_id", None)
    current_seq_idx = -1
    for i, seq in enumerate(sequences):
        if seq.get("id") == active_seq_id or (not active_seq_id and i == 0):
            current_seq_idx = i
            break

    if current_seq_idx < 0:
        return []

    current_seq = sequences[current_seq_idx]
    from backend.engine.hard_rule_evaluator import HardRuleEvaluator

    if HardRuleEvaluator.has_hard_rules(current_seq):
        is_met, _ = HardRuleEvaluator.evaluate_hard_rules(
            current_seq,
            avatar,
            state,
            new_inventory_items=new_inventory_items,
            new_scene_id=new_scene_id,
            updated_entities=updated_entities,
            script_context=script_context,
        )
        sequence_completed = is_met
    else:
        sequence_completed = force_complete

    if not sequence_completed:
        return []

    return _complete_sequence(sequences, current_seq_idx, state, avatar)


def _complete_sequence(sequences, current_seq_idx, state, avatar):
    current_seq = sequences[current_seq_idx]
    system_messages: list[str] = []
    seq_title = (
        current_seq.get("title") or current_seq.get("id") or f"Chapter {current_seq_idx + 1}"
    )
    xp_reward = int(current_seq.get("exp_reward") or 0)
    if xp_reward > 0:
        avatar.exp = (getattr(avatar, "exp", 0) or 0) + xp_reward
        try:
            flag_modified(avatar, "exp")
        except Exception:
            logger.debug("Could not flag sequence progress as modified.", exc_info=True)
        xp_msg = f"Sequence completed: {seq_title} (+{xp_reward} XP)"
    else:
        xp_msg = f"Sequence completed: {seq_title}"
    system_messages.append(xp_msg)

    next_seq_idx = current_seq_idx + 1
    if next_seq_idx < len(sequences):
        next_seq = sequences[next_seq_idx]
        state.active_sequence_id = next_seq.get("id")
        state.active_sequence_order = next_seq.get("order", next_seq_idx + 1)
        try:
            flag_modified(state, "active_sequence_id")
            flag_modified(state, "active_sequence_order")
        except Exception:
            logger.debug("Could not flag sequence progress as modified.", exc_info=True)
        next_title = next_seq.get("title") or next_seq.get("id")
        next_msg = f"New Sequence unlocked: {next_title}"
        system_messages.append(next_msg)
    elif hasattr(state, "is_completed"):
        state.is_completed = True
        try:
            flag_modified(state, "is_completed")
        except Exception:
            logger.debug("Could not flag sequence progress as modified.", exc_info=True)

    return system_messages
