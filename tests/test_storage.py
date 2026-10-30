import random
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from lorcana import rules as R
from lorcana.storage import NotFound, Record, SqliteStore, name_key
from tests.test_rules import play_round, tournament_with

TIMER = {"running": False, "ends_at": None, "remaining": 3000}


def full_event(seed: int = 3) -> R.Tournament:
    """An event using every feature: store, date, inks, late entry, drop, Swiss and top cut."""
    rng = random.Random(seed)
    t = R.update_settings(tournament_with(9), store="Dragon's Den", event_date="2026-11-02", top_cut_size=4)
    inks = list(R.INKS)
    for i, p in enumerate(t.players):
        t = R.set_player_inks(t, p.id, [inks[i % 6], inks[(i + 1) % 6]] if i % 4 else [])
    t = R.pair_next_swiss_round(t, rng)
    t = R.add_player(t, "Late Larry", player_id="late")
    t = play_round(t, rng)
    t = R.drop_player(t, "p002")
    for _ in range(2):
        t = R.pair_next_swiss_round(t, rng)
        t = play_round(t, rng)
    t = R.start_top_cut(t)
    t = play_round(t, rng, draws=False)
    return t


class SqliteStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "test.db"
        self.store = SqliteStore(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def sql(self, query, *params):
        with closing(sqlite3.connect(self.path)) as db, db:
            return db.execute(query, params).fetchall()

    def test_round_trip_is_exact(self):
        t = full_event()
        record = self.store.create(t, TIMER)
        record.history.append(R.Tournament().to_dict())
        self.store.save(record)
        loaded = self.store.get(record.id)
        self.assertEqual(loaded.tournament, t)
        self.assertEqual((loaded.timer, loaded.history), (TIMER, record.history))

    def test_saving_twice_does_not_duplicate_rows(self):
        record = self.store.create(full_event(), TIMER)
        counts = [self.sql(f"SELECT COUNT(*) FROM {table}")[0][0] for table in ("registrations", "rounds", "matches", "people")]
        self.store.save(record)
        self.assertEqual(counts, [self.sql(f"SELECT COUNT(*) FROM {table}")[0][0] for table in ("registrations", "rounds", "matches", "people")])

    def test_same_name_across_events_is_one_person(self):
        a = R.add_player(R.Tournament(), "Ariel Ocean")
        b = R.add_player(R.Tournament(), "  ariel   OCEAN ")
        self.store.create(a, TIMER)
        self.store.create(b, TIMER)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM people"), [(1,)])
        self.assertEqual(self.sql("SELECT COUNT(DISTINCT event_id) FROM registrations"), [(2,)])

    def test_same_name_twice_in_one_event_is_two_people(self):
        t = R.add_player(R.add_player(R.Tournament(), "Alex"), "Alex")
        self.store.create(t, TIMER)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM people"), [(2,)])

    def test_person_link_survives_resave_and_rename(self):
        t = R.add_player(R.Tournament(), "Belle", player_id="b")
        record = self.store.create(t, TIMER)
        (before,) = self.sql("SELECT person_id FROM registrations")
        self.store.save(record)
        self.assertEqual(self.sql("SELECT person_id FROM registrations"), [before])
        record.tournament = R.rename_player(record.tournament, "b", "Belle Reader")
        self.store.save(record)
        self.assertEqual(self.sql("SELECT display_name FROM people"), [("Belle Reader",)])  # old person cleaned up

    def test_soft_delete(self):
        record = self.store.create(R.Tournament(name="Gone"), TIMER)
        self.store.delete(record.id)
        self.assertEqual(self.store.list(), [])
        with self.assertRaises(NotFound):
            self.store.get(record.id)
        with self.assertRaises(NotFound):
            self.store.delete(record.id)
        self.assertEqual(self.sql("SELECT name FROM events WHERE deleted_at IS NOT NULL"), [("Gone",)])

    def test_list_newest_first(self):
        first = self.store.create(R.Tournament(name="First"), TIMER)
        self.store.create(R.Tournament(name="Second"), TIMER)
        first.updated_at = 0
        self.store.save(first)  # saving again makes it the most recent
        self.assertEqual([r.tournament.name for r in self.store.list()][0], "First")

    def test_list_sorted_by_event_date(self):
        for name, day in (("Middle", "2026-09-10"), ("Latest", "2026-10-01"), ("Earliest", "2026-08-05")):
            self.store.create(R.update_settings(R.Tournament(name=name), event_date=day), TIMER)
        self.assertEqual([r.tournament.name for r in self.store.list()], ["Latest", "Middle", "Earliest"])

    def test_database_rejects_impossible_scores(self):
        self.store.create(full_event(), TIMER)
        with self.assertRaises(sqlite3.IntegrityError):
            self.sql("UPDATE matches SET p1_wins = 2, p2_wins = 2 WHERE match_id = 1")
        with self.assertRaises(sqlite3.IntegrityError):
            self.sql("UPDATE matches SET p1_wins = 'two' WHERE match_id = 1")  # STRICT: wrong type

    def test_unknown_id(self):
        with self.assertRaises(NotFound):
            self.store.get("nope")

    def test_name_key(self):
        self.assertEqual(name_key("  Mickey   MOUSE "), "mickey mouse")


if __name__ == "__main__":
    unittest.main()
