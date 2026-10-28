"""Merge memory fragment and session playtime migrations."""

revision = "1c8a6f3e7b20"
down_revision = ("8f4c2a9d10be", "8f8c06e00a80")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Both parent revisions already contain their independent schema changes."""


def downgrade() -> None:
    """No additional schema changes are introduced by this merge."""
