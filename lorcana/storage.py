"""Saves tournaments as JSON files, one file per event.

The server only uses the methods on JsonFileStore, so a hosted version can swap
in a database-backed class with the same methods.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .rules import Tournament

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


class JsonFileStore:
    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[Record]:
        records = []
        for path in self.folder.glob("*.json"):
            try:
                records.append(self._read(path))
            except (OSError, ValueError, KeyError, TypeError):
                continue  # skip files that aren't readable tournaments
        return sorted(records, key=lambda r: r.updated_at, reverse=True)

    def get(self, tournament_id: str) -> Record:
        path = self._path(tournament_id)
        if not path.exists():
            raise NotFound(tournament_id)
        return self._read(path)

    def create(self, tournament: Tournament, timer: dict) -> Record:
        record = Record(id=uuid.uuid4().hex[:12], tournament=tournament, timer=timer)
        self.save(record)
        return record

    def save(self, record: Record) -> None:
        record.updated_at = time.time()
        data = {
            "id": record.id,
            "updated_at": record.updated_at,
            "tournament": record.tournament.to_dict(),
            "timer": record.timer,
            "history": record.history,
        }
        path = self._path(record.id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, path)  # atomic: a crash mid-save never leaves a half-written file

    def delete(self, tournament_id: str) -> None:
        """Moves the file into a 'deleted' folder rather than erasing it."""
        path = self._path(tournament_id)
        if not path.exists():
            raise NotFound(tournament_id)
        trash = self.folder / "deleted"
        trash.mkdir(exist_ok=True)
        os.replace(path, trash / path.name)

    def _path(self, tournament_id: str) -> Path:
        if not _ID.match(tournament_id):
            raise NotFound(tournament_id)
        return self.folder / f"{tournament_id}.json"

    def _read(self, path: Path) -> Record:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Record(
            id=data["id"],
            tournament=Tournament.from_dict(data["tournament"]),
            timer=data["timer"],
            history=data.get("history", []),
            updated_at=data.get("updated_at", 0.0),
        )
