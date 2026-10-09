import json
import random
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from lorcana.server import make_server


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = make_server(Path(self.tmp.name), port=8765)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def call(self, method, path, body=None, expect=200):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as res:
                status, payload = res.status, res.read()
        except urllib.error.HTTPError as err:
            with err:
                status, payload = err.code, err.read()
        self.assertEqual(status, expect, payload)
        return json.loads(payload)

    def act(self, tid, action, expect=200, **params):
        return self.call("POST", f"/api/tournaments/{tid}/actions", {"action": action, **params}, expect)

    def test_pages_are_served(self):
        for path in ("/", "/timer", "/static/app.js", "/static/common.js", "/static/style.css", "/static/timer.js"):
            with urllib.request.urlopen(self.base + path) as res:
                self.assertEqual(res.status, 200, path)

    def test_full_event(self):
        rng = random.Random(4)
        v = self.call("POST", "/api/tournaments", {"name": "Store Champs", "top_cut_size": 4}, expect=201)
        tid = v["id"]
        v = self.act(tid, "add_players", names="\n".join(f"Player {i}" for i in range(1, 10)))
        self.assertEqual((len(v["tournament"]["players"]), v["swiss_rounds_target"]), (9, 4))

        for _ in range(v["swiss_rounds_target"]):
            v = self.act(tid, "pair_next_round")
            self.assertFalse(v["timer"]["running"])
            for m in v["tournament"]["rounds"][-1]["matches"]:
                if m["result"] is None:
                    a, b = rng.choice([(2, 0), (2, 1), (1, 2), (0, 2), (1, 1)])
                    v = self.act(tid, "report_result", match_id=m["id"], p1_wins=a, p2_wins=b)

        v = self.act(tid, "start_top_cut")
        while v["phase"] != "complete":
            for m in v["tournament"]["rounds"][-1]["matches"]:
                v = self.act(tid, "report_result", match_id=m["id"], p1_wins=2, p2_wins=1)
            if v["phase"] != "complete":
                v = self.act(tid, "advance_top_cut")
        self.assertIsNotNone(v["champion"])

        # Undo steps back through the final result.
        v = self.act(tid, "undo")
        self.assertEqual(v["phase"], "topcut")

        # Export, then import as a new tournament.
        with urllib.request.urlopen(f"{self.base}/api/tournaments/{tid}/export") as res:
            exported = json.loads(res.read())
        imported = self.call("POST", "/api/import", exported, expect=201)
        self.assertNotEqual(imported["id"], tid)
        self.assertEqual(imported["tournament"], v["tournament"])

        listed = self.call("GET", "/api/tournaments")
        self.assertEqual(len(listed), 2)

    def test_rule_errors_come_back_as_messages(self):
        tid = self.call("POST", "/api/tournaments", {"name": "Test"}, expect=201)["id"]
        err = self.act(tid, "pair_next_round", expect=400)
        self.assertIn("2 active players", err["error"])
        err = self.act(tid, "report_result", expect=400, match_id="nope", p1_wins="2", p2_wins=0)
        self.assertIn("whole number", err["error"])
        self.assertEqual(self.act(tid, "undo", expect=400)["error"], "Nothing to undo.")
        self.call("GET", "/api/tournaments/doesnotexist", expect=404)
        self.call("GET", "/api/tournaments/../../etc", expect=404)

    def test_timer(self):
        tid = self.call("POST", "/api/tournaments", {"name": "Test", "round_minutes": 30}, expect=201)["id"]
        v = self.act(tid, "timer_start")
        self.assertTrue(v["timer"]["running"])
        v = self.act(tid, "timer_pause")
        self.assertFalse(v["timer"]["running"])
        self.assertLessEqual(v["timer"]["remaining"], 1800)
        v = self.act(tid, "timer_add", seconds=60)
        self.assertGreater(v["timer"]["remaining"], 1800)
        v = self.act(tid, "timer_reset")
        self.assertEqual(v["timer"]["remaining"], 1800)
        # Changing the round length updates an untouched timer.
        v = self.act(tid, "update_settings", round_minutes=45)
        self.assertEqual(v["timer"]["remaining"], 2700)

    def test_delete_moves_file_aside(self):
        tid = self.call("POST", "/api/tournaments", {"name": "Test"}, expect=201)["id"]
        self.call("DELETE", f"/api/tournaments/{tid}")
        self.assertTrue((Path(self.tmp.name) / "deleted" / f"{tid}.json").exists())
        self.call("GET", f"/api/tournaments/{tid}", expect=404)


if __name__ == "__main__":
    unittest.main()
