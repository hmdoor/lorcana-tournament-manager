"""Saves tournaments in a SQLite database.

The server only uses the methods on SqliteStore (list, get, create, save, delete),
so a hosted version can swap in a PostgreSQL-backed class with the same methods.

The tables are normalized (see schema.sql and docs/data/erd.md) so the data can be
analyzed with SQL across events. migrate_json_files() imports events saved by the
earlier one-JSON-file-per-event version.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .rules import INKS, Match, Player, Result, Round, Settings, TopCut, Tournament, phase

SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
INK_IDS = {name: i for i, name in enumerate(INKS, start=1)}  # matches the inks table
_ID = re.compile(r"^[a-z0-9]{1,64}$")


class NotFound(KeyError):
    """No tournament with that id."""


@dataclass
class Record:
    """A saved tournament plus the app state that isn't tournament rules."""

    id: str
    tournament: Tournament
    timer: dict
    history: list[dict] = field(default_factory=list)  # earlier versions for undo, newest last
    updated_at: float = 0.0


def name_key(name: str) -> str:
    """How people are matched across events: same name, ignoring capitals and spacing (see LTM-48)."""
    return " ".join(name.split()).casefold()


class SqliteStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as db:
            db.executescript(SCHEMA)

    # ----- Public interface -----

    def list(self) -> list[Record]:
        with self._transaction() as db:
            rows = db.execute("SELECT event_id FROM events WHERE deleted_at IS NULL ORDER BY updated_at DESC").fetchall()
            return [self._load(db, row["event_id"]) for row in rows]

    def get(self, tournament_id: str) -> Record:
        with self._transaction() as db:
            row = db.execute(
                "SELECT 1 FROM events WHERE event_id = ? AND deleted_at IS NULL", (tournament_id,)
            ).fetchone()
            if row is None:
                raise NotFound(tournament_id)
            return self._load(db, tournament_id)

    def create(self, tournament: Tournament, timer: dict) -> Record:
        record = Record(id=uuid.uuid4().hex[:12], tournament=tournament, timer=timer)
        self.save(record)
        return record

    def save(self, record: Record) -> None:
        """Writes the whole event in one transaction: either everything saves or nothing does."""
        if not _ID.match(record.id):
            raise NotFound(record.id)
        record.updated_at = time.time()
        now = _iso(record.updated_at)
        t = record.tournament
        with self._transaction() as db:
            store_id = self._store_id(db, t.store)
            event = (t.name, store_id, t.event_date, t.settings.round_minutes, t.settings.swiss_rounds,
                     t.settings.top_cut_size, phase(t), now, record.id)
            if db.execute("SELECT 1 FROM events WHERE event_id = ?", (record.id,)).fetchone():
                db.execute(
                    """UPDATE events SET name = ?, store_id = ?, event_date = ?, round_minutes = ?,
                       swiss_rounds = ?, top_cut_size = ?, status = ?, updated_at = ?
                       WHERE event_id = ?""",
                    event,
                )
            else:
                db.execute(
                    """INSERT INTO events (name, store_id, event_date, round_minutes, swiss_rounds,
                       top_cut_size, status, updated_at, event_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (*event, now),
                )

            # Replace this event's players, rounds and matches with the current state,
            # keeping each player linked to the same person as before where possible.
            previous = {
                row["app_player_id"]: (row["person_id"], row["name_key"])
                for row in db.execute(
                    """SELECT r.app_player_id, r.person_id, p.name_key
                       FROM registrations r JOIN people p USING (person_id)
                       WHERE r.event_id = ?""",
                    (record.id,),
                )
            }
            db.execute("DELETE FROM rounds WHERE event_id = ?", (record.id,))  # cascades to matches
            db.execute("DELETE FROM registrations WHERE event_id = ?", (record.id,))

            seeds = {pid: i for i, pid in enumerate(t.top_cut.seeds, start=1)} if t.top_cut else {}
            registration_ids = {}
            for position, p in enumerate(t.players):
                person_id = self._person_id(db, p.name, record.id, previous.get(p.id))
                inks = [INK_IDS[i] for i in p.inks] + [None, None]
                cursor = db.execute(
                    """INSERT INTO registrations (event_id, person_id, app_player_id, name_at_event,
                       joined_round, dropped_after_round, ink_1_id, ink_2_id, top_cut_seed, position)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (record.id, person_id, p.id, p.name, p.joined_round,
                     p.dropped_after_round if p.dropped else None, inks[0], inks[1], seeds.get(p.id), position),
                )
                registration_ids[p.id] = cursor.lastrowid

            for rnd in t.rounds:
                round_id = db.execute(
                    "INSERT INTO rounds (event_id, round_number, stage, paired_at) VALUES (?, ?, ?, ?)",
                    (record.id, rnd.number, rnd.stage, rnd.paired_at),
                ).lastrowid
                db.executemany(
                    """INSERT INTO matches (round_id, app_match_id, table_number, player1_id, player2_id,
                       p1_wins, p2_wins, draws, reported_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (round_id, m.id, m.table, registration_ids[m.p1],
                         registration_ids[m.p2] if m.p2 else None,
                         *((m.result.p1_wins, m.result.p2_wins, m.result.draws) if m.result else (None, None, None)),
                         m.reported_at)
                        for m in rnd.matches
                    ],
                )

            db.execute(
                """INSERT INTO event_app_state (event_id, timer_json, history_json) VALUES (?, ?, ?)
                   ON CONFLICT (event_id) DO UPDATE SET timer_json = excluded.timer_json,
                                                        history_json = excluded.history_json""",
                (record.id, json.dumps(record.timer), json.dumps(record.history)),
            )
            # People left with no registrations (e.g. after a rename or removal) are removed.
            db.execute("DELETE FROM people WHERE person_id NOT IN (SELECT person_id FROM registrations)")

    def delete(self, tournament_id: str) -> None:
        """Soft delete: the event disappears from the app but its data stays in the database."""
        with self._transaction() as db:
            cursor = db.execute(
                "UPDATE events SET deleted_at = ? WHERE event_id = ? AND deleted_at IS NULL",
                (_iso(time.time()), tournament_id),
            )
            if cursor.rowcount == 0:
                raise NotFound(tournament_id)

    # ----- Internals -----

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:  # commits on success, rolls back on any error
                yield db
        finally:
            db.close()

    def _store_id(self, db: sqlite3.Connection, name: str) -> int | None:
        if not name:
            return None
        db.execute("INSERT OR IGNORE INTO stores (name) VALUES (?)", (name,))
        return db.execute("SELECT store_id FROM stores WHERE name = ?", (name,)).fetchone()["store_id"]

    def _person_id(self, db: sqlite3.Connection, name: str, event_id: str, previous: tuple | None) -> int:
        key = name_key(name)
        if previous and previous[1] == key:
            return previous[0]
        # Same name as someone from another event = same person, unless that person
        # is already playing in this event (two different people who share a name).
        row = db.execute(
            """SELECT person_id FROM people
               WHERE name_key = ?
                 AND person_id NOT IN (SELECT person_id FROM registrations WHERE event_id = ?)
               ORDER BY person_id LIMIT 1""",
            (key, event_id),
        ).fetchone()
        if row:
            return row["person_id"]
        return db.execute("INSERT INTO people (display_name, name_key) VALUES (?, ?)", (name, key)).lastrowid

    def _load(self, db: sqlite3.Connection, event_id: str) -> Record:
        event = db.execute(
            """SELECT e.*, s.name AS store_name, a.timer_json, a.history_json
               FROM events e
               LEFT JOIN stores s USING (store_id)
               JOIN event_app_state a USING (event_id)
               WHERE e.event_id = ?""",
            (event_id,),
        ).fetchone()
        registrations = db.execute(
            """SELECT r.*, i1.name AS ink_1, i2.name AS ink_2
               FROM registrations r
               LEFT JOIN inks i1 ON i1.ink_id = r.ink_1_id
               LEFT JOIN inks i2 ON i2.ink_id = r.ink_2_id
               WHERE r.event_id = ?
               ORDER BY r.position""",
            (event_id,),
        ).fetchall()
        app_ids = {r["registration_id"]: r["app_player_id"] for r in registrations}

        players = [
            Player(
                id=r["app_player_id"],
                name=r["name_at_event"],
                dropped=r["dropped_after_round"] is not None,
                dropped_after_round=r["dropped_after_round"],
                joined_round=r["joined_round"],
                inks=[ink for ink in (r["ink_1"], r["ink_2"]) if ink],
            )
            for r in registrations
        ]
        rounds = []
        for rnd in db.execute(
            "SELECT * FROM rounds WHERE event_id = ? ORDER BY round_number", (event_id,)
        ).fetchall():
            matches = [
                Match(
                    id=m["app_match_id"],
                    table=m["table_number"],
                    p1=app_ids[m["player1_id"]],
                    p2=app_ids[m["player2_id"]] if m["player2_id"] is not None else None,
                    result=Result(m["p1_wins"], m["p2_wins"], m["draws"]) if m["p1_wins"] is not None else None,
                    reported_at=m["reported_at"],
                )
                for m in db.execute("SELECT * FROM matches WHERE round_id = ? ORDER BY match_id", (rnd["round_id"],))
            ]
            rounds.append(Round(number=rnd["round_number"], stage=rnd["stage"], matches=matches, paired_at=rnd["paired_at"]))

        seeded = sorted((r for r in registrations if r["top_cut_seed"] is not None), key=lambda r: r["top_cut_seed"])
        tournament = Tournament(
            name=event["name"],
            store=event["store_name"] or "",
            event_date=event["event_date"],
            settings=Settings(
                round_minutes=event["round_minutes"],
                swiss_rounds=event["swiss_rounds"],
                top_cut_size=event["top_cut_size"],
            ),
            players=players,
            rounds=rounds,
            top_cut=TopCut(size=len(seeded), seeds=[r["app_player_id"] for r in seeded]) if seeded else None,
        )
        return Record(
            id=event_id,
            tournament=tournament,
            timer=json.loads(event["timer_json"]),
            history=json.loads(event["history_json"]),
            updated_at=datetime.fromisoformat(event["updated_at"]).timestamp(),
        )


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Importing events saved by the earlier JSON-file version
# ---------------------------------------------------------------------------


def migrate_json_files(folder: Path, store: SqliteStore) -> int:
    """Imports *.json tournaments from `folder` into the database, once.

    Each imported file is moved to `folder/migrated-json/`, never deleted. Files that
    can't be read are left where they are. Returns how many were imported.
    """
    folder = Path(folder)
    files = sorted(folder.glob("*.json"))
    if not files:
        return 0
    done = folder / "migrated-json"
    done.mkdir(exist_ok=True)
    count = 0
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            record = Record(
                id=data["id"],
                tournament=Tournament.from_dict(data["tournament"]),
                timer=data["timer"],
                history=data.get("history", []),
            )
        except (OSError, ValueError, KeyError, TypeError):
            continue
        store.save(record)
        os.replace(path, done / path.name)
        count += 1
    return count
