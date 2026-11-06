# Docker storage

Compose mounts three persistent directories independently:

| Host setting | Container directory | Contents |
| --- | --- | --- |
| `DOCKER_DATA_DIR` (default `./data-docker`) | `/app/data` | Images, uploaded adventures and other media |
| `DOCKER_SQLITE_DIR` (default `./sqlite-docker`) | `/app/sqlite` | `taleweaver.db`, WAL and SHM files |
| `DOCKER_MEMORY_DB_DIR` (default `./db`) | `/app/db` | RAG index in `lancedb/` |

Mount the SQLite **directory**, not just the database file: SQLite must persist
its WAL and SHM siblings on the same filesystem. Keep encryption/signing keys in
the deployment `.env`; back it up separately and protect it as a secret.
`DATABASE_URL` and `MEMORY_DB_DIR` inside Compose point at these mounts; optional
`DOCKER_DATABASE_URL` changes the database destination explicitly.

## Updating an existing installation

Old Compose installations placed SQLite in `DOCKER_DATA_DIR/taleweaver.db`.
The entrypoint refuses to create an empty replacement when it detects this old
file and the new target is absent. It leaves the original untouched. The RAG
host-directory default is unchanged; no index is moved or deleted automatically.

1. Stop TaleWeaver before copying: `docker compose down` (do not use `-v`).
2. Back up the old data directory, the RAG directory and the original `.env`.
3. Create the configured SQLite directory. Use SQLite's backup command, which
   includes committed WAL contents, for example with the host SQLite CLI:

   ```sh
   mkdir -p sqlite-docker
   sqlite3 data-docker/taleweaver.db '.backup sqlite-docker/taleweaver.db'
   sqlite3 sqlite-docker/taleweaver.db 'PRAGMA integrity_check;'
   ```

   Substitute your actual configured paths. If using a plain filesystem backup,
   copy the database and any `-wal`/`-shm` files together while all writers are
   stopped. Never copy only a live SQLite database file.

4. Keep the original keys and `DOCKER_MEMORY_DB_DIR`, then run
   `docker compose up -d --build`. Verify sessions and recall before retiring
   the old backup. A cache index is not a substitute for the authoritative SQLite
   history; preserve both for a complete rollback.

The existing Docker image can also use a custom `DATABASE_URL` directly. This
mount policy does not move a configured external database.
