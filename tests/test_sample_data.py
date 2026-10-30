import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from lorcana import rules as R
from lorcana.sample_data import SHOWCASE_SIZE, generate
from lorcana.storage import SqliteStore


class SampleDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, name: str, seed: int = 1) -> tuple[SqliteStore, Path]:
        path = Path(self.tmp.name) / f"{name}.db"
        store = SqliteStore(path)
        generate(store, seed=seed, weeks=3)
        return store, path

    def rows(self, path: Path, query: str):
        with closing(sqlite3.connect(path)) as db:
            return db.execute(query).fetchall()

    def test_showcase_and_live_demo(self):
        store, _ = self.make("a")
        records = {r.id: r.tournament for r in store.list()}
        demo = records.pop("livedemo")
        self.assertEqual((R.phase(demo), len(demo.players)), ("registration", 12))
        showcase = max(
            (t for t in records.values() if t.store == "Practice Store A"),
            key=lambda t: t.event_date,
        )
        self.assertEqual(len(showcase.players), SHOWCASE_SIZE)
        self.assertEqual(R.phase(showcase), "complete")
        self.assertEqual(showcase.top_cut.size, 8)

    def test_same_seed_same_data(self):
        query = "SELECT app_match_id, p1_wins, p2_wins, draws, reported_at FROM matches ORDER BY match_id"
        _, a = self.make("a", seed=7)
        _, b = self.make("b", seed=7)
        self.assertEqual(self.rows(a, query), self.rows(b, query))

    def test_data_is_complete_and_labeled(self):
        _, path = self.make("a")
        self.assertEqual(self.rows(path, "SELECT COUNT(*) FROM stores WHERE name NOT LIKE 'Practice Store %'"), [(0,)])
        # Every finished Swiss round has timestamps for pairing and every result.
        self.assertEqual(self.rows(path, "SELECT COUNT(*) FROM rounds WHERE paired_at IS NULL"), [(0,)])
        self.assertEqual(
            self.rows(path, "SELECT COUNT(*) FROM matches WHERE p1_wins IS NOT NULL AND reported_at IS NULL"), [(0,)]
        )
        # Players appear at more than one event, so cross-event SQL has something to find.
        (repeat,) = self.rows(path, "SELECT COUNT(*) FROM (SELECT person_id FROM registrations GROUP BY person_id HAVING COUNT(*) > 1)")
        self.assertGreater(repeat[0], 0)


if __name__ == "__main__":
    unittest.main()
