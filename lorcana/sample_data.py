"""Generates fictional sample data for demos, screenshots and SQL practice (LTM-47).

    python3 -m lorcana.sample_data            # writes sample-data/lorcana.db
    python3 -m lorcana --data sample-data     # opens the app on it

Everything is invented: player names, "Practice Store" names and every result.
Never present it as real event data. The same seed always produces the same data.
"""

from __future__ import annotations

import argparse
import itertools
import math
import random
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from . import rules as R
from .server import DB_FILENAME, new_timer
from .storage import Record, SqliteStore

REAL_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "sample-data"
LAST_WEEK_START = date(2026, 10, 23)  # first day of the final simulated week
WEEKS = 13
PLAYER_COUNT = 60
SHOWCASE_SIZE = 24
LIVE_DEMO_SIZE = 12
MIN_PLAYERS = 6

FIRST_NAMES = [
    "Avery", "Blake", "Casey", "Dana", "Eli", "Finley", "Gray", "Harper", "Indy", "Jordan",
    "Kai", "Logan", "Morgan", "Noel", "Oakley", "Parker", "Quinn", "Riley", "Sage", "Taylor",
    "Uma", "Val", "Wren", "Xavi", "Yara", "Zion", "Ari", "Bea", "Cole", "Dev",
]
LAST_NAMES = [
    "Alder", "Brook", "Calloway", "Dunmore", "Ellery", "Fairbanks", "Garrow", "Hollis", "Ivers", "Jessup",
    "Kenning", "Larkin", "Marlow", "Norcross", "Oakes", "Pemberton", "Quill", "Rowan", "Sutter", "Thorne",
]


@dataclass(frozen=True)
class StoreSpec:
    name: str
    day_offset: int  # day of the simulated week the store runs its event
    popularity: float  # multiplies each regular's chance of coming
    start_hour_utc: int


STORES = (
    StoreSpec("Practice Store A", 0, 0.9, 23),
    StoreSpec("Practice Store B", 1, 0.85, 18),
    StoreSpec("Practice Store C", 5, 0.8, 23),
)
HOME_STORE_WEIGHTS = (0.45, 0.3, 0.25)


@dataclass
class Profile:
    """A fictional player's habits. The app only ever sees the name; the rest drives the simulation."""

    id: str
    name: str
    home: int
    skill: float
    deck: tuple[str, str]
    attendance: float
    first_week: int
    last_week: int


class World:
    """The fixed facts of the simulation: deck strengths, matchups and players."""

    def __init__(self, rng: random.Random):
        self.pairs = list(itertools.combinations(R.INKS, 2))
        self.strength = {pair: rng.gauss(0, 0.25) for pair in self.pairs}
        self.matchup = {}
        for a, b in itertools.combinations(self.pairs, 2):
            edge = rng.gauss(0, 0.25)
            self.matchup[(a, b)], self.matchup[(b, a)] = edge, -edge
        # Players tend to pick strong decks, like a real meta.
        popularity = [math.exp(2 * self.strength[p]) + 0.3 for p in self.pairs]
        names = rng.sample([f"{f} {l}" for f in FIRST_NAMES for l in LAST_NAMES], PLAYER_COUNT)
        self.profiles = {}
        for name in names:
            first = 0 if rng.random() < 0.6 else rng.randint(1, WEEKS - 2)
            last = WEEKS - 1 if rng.random() < 0.8 else rng.randint(first + 1, WEEKS - 1)
            pid = name.lower().replace(" ", "")
            self.profiles[pid] = Profile(
                id=pid,
                name=name,
                home=rng.choices(range(len(STORES)), HOME_STORE_WEIGHTS)[0],
                skill=rng.gauss(0, 1),
                deck=rng.choices(self.pairs, popularity)[0],
                attendance=rng.uniform(0.35, 0.9),
                first_week=first,
                last_week=last,
            )

    def score(self, rng, a: Profile, deck_a, b: Profile, deck_b, allow_draw: bool) -> tuple[int, int, int]:
        edge = 0.5 * (a.skill - b.skill) + self.strength[deck_a] - self.strength[deck_b] + self.matchup.get((deck_a, deck_b), 0)
        if allow_draw and rng.random() < 0.05:
            return (1, 1, 0)
        a_wins = rng.random() < 1 / (1 + math.exp(-edge))
        if rng.random() < 0.05:
            w, l = 1, 0  # time called mid-match
        else:
            w, l = (2, 1) if rng.random() < 0.4 else (2, 0)
        return (w, l, 0) if a_wins else (l, w, 0)


def generate(store: SqliteStore, seed: int = 2026, weeks: int = WEEKS) -> dict:
    """Simulates `weeks` weeks of events at the practice stores and saves them. Returns counts."""
    rng = random.Random(seed)
    world = World(rng)
    first_week_start = LAST_WEEK_START - timedelta(weeks=weeks - 1)
    week_offset = WEEKS - weeks  # keep player join/leave weeks aligned with the final week
    events = []

    for week in range(weeks):
        sim_week = week + week_offset
        for index, spec in enumerate(STORES):
            day = first_week_start + timedelta(weeks=week, days=spec.day_offset)
            active = [p for p in world.profiles.values() if p.first_week <= sim_week <= p.last_week]
            attendees = [
                p for p in active
                if rng.random() < (p.attendance * spec.popularity if p.home == index else 0.05)
            ]
            showcase = week == weeks - 1 and index == 0
            if showcase:
                for p in sorted(active, key=lambda p: -p.attendance):
                    if len(attendees) >= SHOWCASE_SIZE:
                        break
                    if p not in attendees:
                        attendees.append(p)
            if len(attendees) < MIN_PLAYERS:
                continue  # a quiet night: the event didn't fire
            rng.shuffle(attendees)
            others = [p for p in active if p not in attendees]
            late = rng.choice(others) if others and not showcase and rng.random() < 0.3 else None
            events.append(simulate_event(rng, world, spec, day, attendees, late))

    for n, t in enumerate(sorted(events, key=lambda t: t.event_date), start=1):
        store.save(Record(id=f"sample{n:03d}", tournament=t, timer=new_timer(t.settings.round_minutes)))

    demo = live_demo_event(rng, world, LAST_WEEK_START + timedelta(weeks=1))
    store.save(Record(id="livedemo", tournament=demo, timer=new_timer(demo.settings.round_minutes)))
    return {
        "events": len(events) + 1,
        "players": len(world.profiles),
        "matches": sum(len(r.matches) for t in events for r in t.rounds),
    }


def simulate_event(rng, world: World, spec: StoreSpec, day: date, attendees: list[Profile], late: Profile | None) -> R.Tournament:
    count = len(attendees) + (1 if late else 0)
    cut = 8 if count >= 17 else 4 if count >= 12 else 0
    t = R.Tournament(name=f"{day:%A} Lorcana", store=spec.name, event_date=day.isoformat(),
                     settings=R.Settings(top_cut_size=cut))
    decks = {}

    def register(t: R.Tournament, p: Profile) -> R.Tournament:
        t = R.add_player(t, p.name, player_id=p.id)
        decks[p.id] = p.deck if rng.random() > 0.1 else rng.choice(world.pairs)  # occasional deck switch
        if rng.random() < 0.85:  # some players don't share their deck
            t = R.set_player_inks(t, p.id, list(decks[p.id]))
        return t

    for p in attendees:
        t = register(t, p)
    clock = datetime.combine(day, time(spec.start_hour_utc), timezone.utc) + timedelta(minutes=rng.uniform(0, 10))
    rounds = R.recommended_swiss_rounds(count)
    for number in range(1, rounds + 1):
        t = R.pair_next_swiss_round(t, rng, now=_iso(clock))
        if number == 1 and late:
            t = register(t, late)  # arrives after round 1 is paired: takes a round 1 loss
        t, last = play_round(rng, world, t, decks, clock, allow_draw=True)
        if number < rounds:
            t = random_drops(rng, t)
        clock = last + timedelta(minutes=rng.uniform(3, 9))

    if cut and sum(not p.dropped for p in t.players) < cut:
        t = R.update_settings(t, top_cut_size=0)  # too many drops for the cut: finish as Swiss only
    elif cut:
        t = R.start_top_cut(t, now=_iso(clock))
        while True:
            t, last = play_round(rng, world, t, decks, clock, allow_draw=False)
            if R.phase(t) == "complete":
                break
            clock = last + timedelta(minutes=rng.uniform(3, 8))
            t = R.advance_top_cut(t, now=_iso(clock))
    return t


def play_round(rng, world: World, t: R.Tournament, decks: dict, paired_at: datetime, allow_draw: bool):
    last = paired_at
    for m in t.rounds[-1].matches:
        if m.result is not None:
            continue  # bye
        score = world.score(rng, world.profiles[m.p1], decks[m.p1], world.profiles[m.p2], decks[m.p2], allow_draw)
        went_to_time = score[0] + score[1] + score[2] == 1
        minutes = t.settings.round_minutes + rng.uniform(1, 5) if went_to_time else rng.uniform(20, 48)
        reported = paired_at + timedelta(minutes=minutes)
        last = max(last, reported)
        t = R.report_result(t, m.id, *score, now=_iso(reported))
    return t, last


def random_drops(rng, t: R.Tournament) -> R.Tournament:
    for s in R.compute_standings(t):
        if s.dropped:
            continue
        winless = s.matches_played >= 2 and s.wins == 0 and s.draws == 0
        if rng.random() < (0.25 if winless else 0.02):
            t = R.drop_player(t, s.player_id)
    return t


def live_demo_event(rng, world: World, day: date) -> R.Tournament:
    """A registered-but-not-started event for recording a demo of pairing and scoring."""
    t = R.Tournament(name="Live Demo Night", store=STORES[0].name, event_date=day.isoformat(),
                     settings=R.Settings(top_cut_size=4))
    regulars = sorted(world.profiles.values(), key=lambda p: -p.attendance)[:LIVE_DEMO_SIZE]
    for p in sorted(regulars, key=lambda p: p.name):
        t = R.add_player(t, p.name, player_id=p.id)
        t = R.set_player_inks(t, p.id, list(p.deck))
    return t


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python3 -m lorcana.sample_data", description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="folder for the sample database (default: sample-data)")
    parser.add_argument("--seed", type=int, default=2026, help="same seed = same data (default 2026)")
    parser.add_argument("--replace", action="store_true", help="replace an existing sample database")
    args = parser.parse_args()

    if args.out.resolve() == REAL_DATA_DIR:
        sys.exit("Refusing to write sample data into the real data folder. Choose another --out folder.")
    db = args.out / DB_FILENAME
    if db.exists():
        if not args.replace:
            sys.exit(f"{db} already exists. Add --replace to regenerate it.")
        db.unlink()
    counts = generate(SqliteStore(db), seed=args.seed)
    print(f"Created {db}: {counts['events']} events, {counts['players']} players, {counts['matches']} matches.")
    print("All names, stores and results are fictional sample data.")
    print(f"Open it with: python3 -m lorcana --data {args.out}")


if __name__ == "__main__":
    main()
