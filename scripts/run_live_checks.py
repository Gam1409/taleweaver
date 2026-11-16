"""Plan or explicitly run isolated state, NPC tool, emotion and initiative checks."""

if __package__:
    from .live_checks.cli import main
else:
    from live_checks.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
