"""Explicit public-only fixtures; privacy classification has dedicated tests."""


def public_projection(payload):
    observers = list(payload["present_observers"])
    return {
        "fragments": {
            key: {"kind": "speech", "observers": observers, "engaged": observers[:1]}
            for key in payload["fragments"]
        }
    }
