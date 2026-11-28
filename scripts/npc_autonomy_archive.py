"""Build a disposable full-text index of a structured world pack before the pilot."""

import argparse
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path


def build(source, target):
    raw = source.read_bytes()
    pack = json.loads(raw.decode("utf-8-sig"))
    records = pack["records"]
    if len({r["id"] for r in records}) != len(records) or len(records) != pack["record_count"]:
        raise ValueError("World pack count or record identity mismatch")
    with closing(sqlite3.connect(target)) as db, db:
        db.execute("BEGIN")
        db.execute("DROP TABLE IF EXISTS entries")
        db.execute(
            "CREATE VIRTUAL TABLE entries USING fts5(id,category,title,location,terms,text,"
            "visibility UNINDEXED,record UNINDEXED)"
        )
        db.executemany(
            "INSERT INTO entries VALUES (?,?,?,?,?,?,?,?)",
            (
                (
                    r["id"],
                    r["category"],
                    r["title"],
                    r["location"],
                    " ".join([*r["tags"], *r["entities"]]),
                    r["text"],
                    r["visibility"],
                    json.dumps(r, ensure_ascii=False),
                )
                for r in records
            ),
        )
        db.execute("CREATE TABLE IF NOT EXISTS source (filename TEXT, digest TEXT, premise TEXT)")
        db.execute("DELETE FROM source")
        context = pack["world_context"]
        premise = {
            k: context[k] for k in ("setting", "catastrophe", "geography", "knowledge_boundary")
        }
        db.execute(
            "INSERT INTO source VALUES (?,?,?)",
            (source.name, hashlib.sha256(raw).hexdigest(), json.dumps(premise, ensure_ascii=False)),
        )
    return len(records)


class Archive:
    def __init__(self, path):
        self.uri = path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(self.uri, uri=True)) as db:
            self.filename, self.digest, premise = db.execute("SELECT * FROM source").fetchone()
            self.premise = json.loads(premise)
            self.catalog = [
                row[0]
                for row in db.execute(
                    "SELECT DISTINCT category FROM entries WHERE visibility='public' ORDER BY category"
                )
            ]

    def lookup(self, query):
        terms = re.findall(r"\w+", query)[:8]
        if not terms:
            return []
        with closing(sqlite3.connect(self.uri, uri=True)) as db:
            if re.fullmatch(r"LMW-\d+", query, re.I):
                rows = db.execute(
                    "SELECT record FROM entries WHERE visibility='public' AND id=?",
                    (query.upper(),),
                )
            else:
                rows = db.execute(
                    "SELECT record FROM entries WHERE visibility='public' AND "
                    "entries MATCH ? ORDER BY rank, rowid LIMIT 2",
                    (" OR ".join(f'"{term}"*' for term in terms),),
                )
            return [json.loads(row[0]) for row in rows]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("index", type=Path)
    args = parser.parse_args()
    print(f"Indexed {build(args.source, args.index)} records")
