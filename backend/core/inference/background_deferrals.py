"""Keep background jobs dormant while their exact admission blocker still exists."""

from collections import OrderedDict

from backend.core.inference import admission
from backend.core.inference.registry import InferenceUncertainError

_blocked: OrderedDict[tuple[str, str], str] = OrderedDict()


def remember(kind: str, session_id: str, error: InferenceUncertainError) -> bool:
    token = error.blocking_reservation_id
    if token is None:
        return False
    key = kind, session_id
    _blocked[key] = token
    _blocked.move_to_end(key)
    if len(_blocked) > 1024:
        _blocked.popitem(last=False)
    return True


def waiting(kind: str, session_id: str) -> bool:
    key = kind, session_id
    token = _blocked.get(key)
    if token is None:
        return False
    if admission.registry().is_unresolved(token):
        return True
    _blocked.pop(key, None)
    return False
