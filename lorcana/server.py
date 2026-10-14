"""Local web server for the Lorcana tournament app.

Serves the browser screens from lorcana/static and a small JSON API. All
tournament logic lives in rules.py and all saving lives in storage.py.
"""

from __future__ import annotations

import json
import re
import threading
import time
import traceback
import webbrowser
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import rules as R
from .storage import NotFound, Record, SqliteStore, migrate_json_files

DB_FILENAME = "lorcana.db"

STATIC_DIR = Path(__file__).parent / "static"
PAGES = {"/": "index.html", "/timer": "timer.html"}
STATIC_FILE = re.compile(r"^/static/([a-z0-9_-]+\.(?:js|css|svg))$")
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
}
TOURNAMENT_PATH = re.compile(r"^/api/tournaments/([a-z0-9]+)(/actions|/export)?$")
EXPORT_FORMAT = "lorcana-tournament"
HISTORY_LIMIT = 50
MAX_BODY_BYTES = 5_000_000
NEW_ROUND_ACTIONS = {"pair_next_round", "start_top_cut", "advance_top_cut"}
TIMER_ACTIONS = {"timer_start", "timer_pause", "timer_reset", "timer_add"}


class BadRequest(Exception):
    """The browser sent something malformed (not a rules problem)."""


# ---------------------------------------------------------------------------
# What the browser sees
# ---------------------------------------------------------------------------


def view(record: Record) -> dict:
    t = record.tournament
    recommended = R.recommended_swiss_rounds(len(t.players))
    return {
        "id": record.id,
        "tournament": t.to_dict(),
        "phase": R.phase(t),
        "standings": [asdict(s) for s in R.compute_standings(t)],
        "inks": R.INKS,
        "recommended_swiss_rounds": recommended,
        "swiss_rounds_target": t.settings.swiss_rounds or recommended,
        "swiss_rounds_played": sum(1 for r in t.rounds if r.stage == "swiss"),
        "champion": R.champion(t),
        "timer": record.timer,
        "can_undo": bool(record.history),
        "server_now": time.time(),
    }


def summary(record: Record) -> dict:
    t = record.tournament
    return {
        "id": record.id,
        "name": t.name,
        "store": t.store,
        "event_date": t.event_date,
        "phase": R.phase(t),
        "players": len(t.players),
        "updated_at": record.updated_at,
    }


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def run_action(record: Record, action: str, params: dict) -> None:
    """Applies one change to a record. Tournament changes can be undone; timer changes can't."""
    if action == "undo":
        if not record.history:
            raise R.TournamentError("Nothing to undo.")
        record.tournament = R.Tournament.from_dict(record.history.pop())
        return
    if action in TIMER_ACTIONS:
        update_timer(record, action, params)
        return

    old = record.tournament
    record.tournament = tournament_action(old, action, params)
    record.history.append(old.to_dict())
    del record.history[:-HISTORY_LIMIT]

    if action in NEW_ROUND_ACTIONS:
        record.timer = new_timer(record.tournament.settings.round_minutes)
    elif action == "update_settings" and timer_untouched(record.timer, old.settings.round_minutes):
        record.timer = new_timer(record.tournament.settings.round_minutes)


def tournament_action(t: R.Tournament, action: str, p: dict) -> R.Tournament:
    match action:
        case "add_player":
            return R.add_player(t, _str(p, "name"))
        case "add_players":
            names = [n for n in _str(p, "names").splitlines() if n.strip()]
            if not names:
                raise R.TournamentError("Enter at least one name.")
            for name in names:
                t = R.add_player(t, name)
            return t
        case "set_player_inks":
            return R.set_player_inks(t, _str(p, "player_id"), p.get("inks"))
        case "rename_player":
            return R.rename_player(t, _str(p, "player_id"), _str(p, "name"))
        case "remove_player" | "drop_player" | "reinstate_player":
            return getattr(R, action)(t, _str(p, "player_id"))
        case "report_result":
            return R.report_result(
                t, _str(p, "match_id"), _int(p, "p1_wins"), _int(p, "p2_wins"), _int(p, "draws", 0)
            )
        case "clear_result":
            return R.clear_result(t, _str(p, "match_id"))
        case "pair_next_round":
            return R.pair_next_swiss_round(t)
        case "start_top_cut":
            return R.start_top_cut(t)
        case "advance_top_cut":
            return R.advance_top_cut(t)
        case "update_settings":
            keys = ("name", "store", "event_date", "round_minutes", "swiss_rounds", "top_cut_size")
            return R.update_settings(t, **{k: p[k] for k in keys if k in p})
        case _:
            raise BadRequest(f"Unknown action: {action}")


def new_timer(minutes: int) -> dict:
    return {"running": False, "ends_at": None, "remaining": minutes * 60}


def timer_untouched(timer: dict, minutes: int) -> bool:
    return not timer["running"] and timer["remaining"] == minutes * 60


def update_timer(record: Record, action: str, p: dict) -> None:
    timer, now = record.timer, time.time()
    if action == "timer_start" and not timer["running"]:
        timer.update(running=True, ends_at=now + timer["remaining"])
    elif action == "timer_pause" and timer["running"]:
        timer.update(running=False, remaining=max(0.0, timer["ends_at"] - now), ends_at=None)
    elif action == "timer_reset":
        record.timer = new_timer(record.tournament.settings.round_minutes)
    elif action == "timer_add":
        seconds = _int(p, "seconds")
        if timer["running"]:
            timer["ends_at"] = max(now, timer["ends_at"] + seconds)
        else:
            timer["remaining"] = max(0, timer["remaining"] + seconds)


def new_tournament(body: dict) -> R.Tournament:
    keys = ("store", "event_date", "round_minutes", "swiss_rounds", "top_cut_size")
    settings = {k: body[k] for k in keys if k in body}
    name = body.get("name") if isinstance(body.get("name"), str) and body["name"].strip() else "Lorcana Tournament"
    return R.update_settings(R.Tournament(), name=name, **settings)


def import_tournament(body: dict) -> R.Tournament:
    if body.get("format") != EXPORT_FORMAT:
        raise BadRequest("That file isn't a Lorcana tournament export.")
    try:
        return R.Tournament.from_dict(body["tournament"])
    except (KeyError, TypeError, AttributeError) as exc:
        raise BadRequest("That tournament file is damaged or from an unsupported version.") from exc


def _str(p: dict, key: str) -> str:
    value = p.get(key)
    if not isinstance(value, str):
        raise BadRequest(f'"{key}" must be text.')
    return value


def _int(p: dict, key: str, default: int | None = None) -> int:
    value = p.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise BadRequest(f'"{key}" must be a whole number.')
    return value


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    store: SqliteStore  # set by make_server
    lock = threading.Lock()  # one change at a time keeps saves consistent

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def log_message(self, format, *args):
        pass  # the timer page polls constantly; keep the terminal quiet

    def _dispatch(self, method: str) -> None:
        path = urlparse(self.path).path
        try:
            with self.lock:
                self._route(method, path)
        except R.TournamentError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except BadRequest as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except NotFound:
            self._json({"error": "Tournament not found."}, HTTPStatus.NOT_FOUND)
        except Exception:
            traceback.print_exc()
            self._json({"error": "Something went wrong. Check the terminal window for details."}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _route(self, method: str, path: str) -> None:
        if method == "GET" and path in PAGES:
            return self._file(PAGES[path])
        if method == "GET" and (m := STATIC_FILE.match(path)):
            return self._file(m.group(1))

        if path == "/api/tournaments":
            if method == "GET":
                return self._json([summary(r) for r in self.store.list()])
            if method == "POST":
                t = new_tournament(self._body())
                record = self.store.create(t, new_timer(t.settings.round_minutes))
                return self._json(view(record), HTTPStatus.CREATED)

        if path == "/api/import" and method == "POST":
            t = import_tournament(self._body())
            record = self.store.create(t, new_timer(t.settings.round_minutes))
            return self._json(view(record), HTTPStatus.CREATED)

        if m := TOURNAMENT_PATH.match(path):
            tournament_id, sub = m.groups()
            record = self.store.get(tournament_id)
            if sub is None and method == "GET":
                return self._json(view(record))
            if sub is None and method == "DELETE":
                self.store.delete(tournament_id)
                return self._json({"ok": True})
            if sub == "/actions" and method == "POST":
                body = self._body()
                run_action(record, _str(body, "action"), body)
                self.store.save(record)
                return self._json(view(record))
            if sub == "/export" and method == "GET":
                data = {"format": EXPORT_FORMAT, "version": 1, "tournament": record.tournament.to_dict()}
                filename = re.sub(r"[^A-Za-z0-9_-]+", "-", record.tournament.name).strip("-") or "tournament"
                return self._send(
                    json.dumps(data, indent=1).encode(),
                    "application/json",
                    {"Content-Disposition": f'attachment; filename="{filename}.json"'},
                )

        self._json({"error": "Not found."}, HTTPStatus.NOT_FOUND)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            raise BadRequest("Request is too large.")
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as exc:
            raise BadRequest("Request body isn't valid JSON.") from exc
        if not isinstance(data, dict):
            raise BadRequest("Request body must be a JSON object.")
        return data

    def _file(self, name: str) -> None:
        path = STATIC_DIR / name
        if not path.is_file():
            return self._json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
        self._send(path.read_bytes(), CONTENT_TYPES[path.suffix])

    def _json(self, data, status: HTTPStatus = HTTPStatus.OK) -> None:
        self._send(json.dumps(data).encode(), "application/json", status=status)

    def _send(self, body: bytes, content_type: str, headers: dict | None = None, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


def make_server(data_dir: Path, port: int, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    """Starts on `port`, or the next free port if it's taken.

    Events saved as JSON files by the earlier version are imported into the database first.
    """
    store = SqliteStore(Path(data_dir) / DB_FILENAME)
    migrated = migrate_json_files(data_dir, store)
    if migrated:
        print(f"Imported {migrated} tournament(s) from JSON files into the database.")
    handler = type("BoundHandler", (Handler,), {"store": store})
    for candidate in range(port, port + 20):
        try:
            return ThreadingHTTPServer((host, candidate), handler)
        except OSError:
            continue
    raise OSError(f"No free port between {port} and {port + 19}.")


def serve(data_dir: Path, port: int = 8000, open_browser: bool = True) -> None:
    server = make_server(data_dir, port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Lorcana tournament app running at {url}")
    print(f"Saving tournaments in {(Path(data_dir) / DB_FILENAME).resolve()}")
    print("Keep this window open during the event. Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
