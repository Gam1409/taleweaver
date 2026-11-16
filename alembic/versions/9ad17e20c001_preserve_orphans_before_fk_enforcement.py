"""Preserve legacy orphan rows before enforcing SQLite foreign keys.

Orphans are retained verbatim in referential_repair_archive for operator recovery.
"""

import json

import sqlalchemy as sa

from alembic import op

revision = "9ad17e20c001"
down_revision = "c7e9a1b3d524"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name != "sqlite":
        return
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS referential_repair_archive "
        "(id INTEGER PRIMARY KEY, source_table TEXT NOT NULL, source_rowid INTEGER NOT NULL, "
        "payload TEXT NOT NULL, reason TEXT NOT NULL)"
    )
    while True:
        violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if not violations:
            break
        for table, rowid, parent, _constraint in violations:
            reflected = sa.Table(table, sa.MetaData(), autoload_with=connection)
            predicate = sa.literal_column("rowid") == rowid
            row = connection.execute(sa.select(reflected).where(predicate)).mappings().first()
            if row is None:
                continue
            connection.exec_driver_sql(
                "INSERT INTO referential_repair_archive (source_table, source_rowid, payload, reason) "
                "VALUES (?, ?, ?, ?)",
                (table, rowid, json.dumps(dict(row), default=str), "Missing parent: " + parent),
            )
            connection.execute(reflected.delete().where(predicate))


def downgrade():
    # Do not destroy the recovery archive or blindly restore inconsistent rows.
    pass
