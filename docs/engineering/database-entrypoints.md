# Database and legacy utility entrypoints

Use `poetry run alembic upgrade head` to initialize or update a database.
Normal application startup does the same through the shared migration helper.
Use the [read-only state inspector](../../scripts/inspect_state.py) to inspect a
configured installation before diagnosing state or import problems:

```sh
poetry run python scripts/inspect_state.py list-adventures
poetry run python scripts/inspect_state.py list-sessions
poetry run python scripts/inspect_state.py show-session SESSION_ID
```

Keep original keys and a consistent backup before applying migrations or changing
deployment storage; see [Docker storage](../docker-storage.md) and
[desktop profiles](../desktop.md).

The historical `python -m backend.init_db` command is retained, but delegates
to Alembic; it no longer creates an unversioned schema with `create_all`.

The unused generic CRUD factories and stale `scripts/migrate_data.py` URL-rewrite
utility were removed. The latter searched obsolete database locations and
performed broad asset-path replacements outside the migration/import lifecycle.
Use supported adventure import/export and session asset repair instead of running
that historical script against a current database. Keep a backup and original keys.

Profile read models remain at `backend.engine.profile`; the old
`backend.crud.crud_profile` import is a compatibility facade. Normal endpoint
behavior and profile response contracts are unchanged.

Synchronous LLM methods remain compatibility APIs covered by their existing
tests. Application routes and workers use the asynchronous methods. The absence
of a production synchronous caller is not sufficient reason to remove a tested
interface during an unrelated maintenance release.
