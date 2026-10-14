import random
import time
import unittest

from lorcana import rules as R
from lorcana.rules import Match, Result, Round, Settings, Tournament, TournamentError

SWISS_RESULTS = [(2, 0), (2, 1), (0, 2), (1, 2), (1, 1)]
DECISIVE_RESULTS = SWISS_RESULTS[:4]


def tournament_with(n: int, **settings) -> Tournament:
    t = Tournament(settings=Settings(**settings))
    for i in range(1, n + 1):
        t = R.add_player(t, f"Player {i:03d}", player_id=f"p{i:03d}")
    return t


def play_round(t: Tournament, rng: random.Random, draws: bool = True) -> Tournament:
    for m in t.rounds[-1].matches:
        if m.result is None:
            t = R.report_result(t, m.id, *rng.choice(SWISS_RESULTS if draws else DECISIVE_RESULTS))
    return t


def run_swiss(n: int, rounds: int, seed: int, draws: bool = True) -> Tournament:
    rng = random.Random(seed)
    t = tournament_with(n)
    for _ in range(rounds):
        t = R.pair_next_swiss_round(t, rng)
        t = play_round(t, rng, draws)
    return t


def swiss_pairs(t: Tournament) -> list[frozenset]:
    return [frozenset((m.p1, m.p2)) for r in t.rounds if r.stage == "swiss" for m in r.matches if not m.is_bye]


def byes(t: Tournament) -> list[str]:
    return [m.p1 for r in t.rounds for m in r.matches if m.is_bye]


class ResultValidationTests(unittest.TestCase):
    def test_valid_best_of_three_results(self):
        for result in [(2, 0), (2, 1), (1, 2), (0, 2), (1, 1), (1, 0), (0, 0), (1, 0, 1), (2, 0, 1)]:
            self.assertIsNone(R.validate_result(*result), result)

    def test_invalid_results(self):
        for result in [(3, 0), (2, 2), (2, 1, 1), (-1, 0), (1.5, 0), (True, 0)]:
            self.assertIsNotNone(R.validate_result(*result), result)

    def test_top_cut_needs_a_winner(self):
        self.assertIsNotNone(R.validate_result(1, 1, allow_draw=False))
        self.assertIsNone(R.validate_result(2, 1, allow_draw=False))

    def test_bye_cannot_be_reported(self):
        t = R.pair_next_swiss_round(tournament_with(3), random.Random(1))
        with self.assertRaises(TournamentError):
            R.report_result(t, "r1-bye", 0, 2)


class SwissPairingTests(unittest.TestCase):
    def test_round_one_pairs_everyone_once_with_one_bye(self):
        t = R.pair_next_swiss_round(tournament_with(9), random.Random(1))
        matches = t.rounds[0].matches
        seated = [pid for m in matches for pid in (m.p1, m.p2) if pid]
        self.assertEqual(sorted(seated), sorted(p.id for p in t.players))
        self.assertEqual(len(byes(t)), 1)
        self.assertEqual(matches[-1].result, Result(2, 0, 0))

    def test_no_rematches_and_no_second_byes(self):
        for n in (5, 7, 8, 9, 16, 33):
            for seed in range(30):
                t = run_swiss(n, R.recommended_swiss_rounds(n), seed)
                pairs = swiss_pairs(t)
                self.assertEqual(len(pairs), len(set(pairs)), f"rematch: {n} players, seed {seed}")
                self.assertEqual(len(byes(t)), len(set(byes(t))), f"double bye: {n} players, seed {seed}")

    def test_pairs_within_point_groups(self):
        for seed in range(20):
            t = run_swiss(8, 1, seed, draws=False)
            t = R.pair_next_swiss_round(t, random.Random(seed))
            points = {s.player_id: s.match_points for s in R.compute_standings(t)}
            for m in t.rounds[-1].matches:
                self.assertEqual(points[m.p1], points[m.p2])

    def test_bye_goes_to_lowest_point_group(self):
        for seed in range(20):
            t = run_swiss(5, 1, seed=seed, draws=False)
            points = {s.player_id: s.match_points for s in R.compute_standings(t)}
            earlier_bye = byes(t)[0]
            t = R.pair_next_swiss_round(t, random.Random(seed))
            lowest = min(points[pid] for pid in points if pid != earlier_bye)
            self.assertEqual(points[byes(t)[-1]], lowest)

    def test_cannot_pair_while_round_incomplete(self):
        t = R.pair_next_swiss_round(tournament_with(8), random.Random(1))
        with self.assertRaises(TournamentError):
            R.pair_next_swiss_round(t)

    def test_dropped_players_are_not_paired(self):
        t = run_swiss(8, 1, seed=1)
        t = R.drop_player(t, "p001")
        t = R.pair_next_swiss_round(t, random.Random(1))
        seated = {pid for m in t.rounds[-1].matches for pid in (m.p1, m.p2)}
        self.assertNotIn("p001", seated)

    def test_late_player_takes_a_loss_for_missed_rounds(self):
        t = run_swiss(4, 1, seed=1)
        t = R.add_player(t, "Late Larry", player_id="late")
        late = next(s for s in R.compute_standings(t) if s.player_id == "late")
        self.assertEqual((late.losses, late.match_points, late.matches_played), (1, 0, 1))
        t = R.pair_next_swiss_round(t, random.Random(1))
        seated = {pid for m in t.rounds[-1].matches for pid in (m.p1, m.p2)}
        self.assertIn("late", seated)

    def test_large_event_is_fast(self):
        start = time.perf_counter()
        t = run_swiss(256, R.recommended_swiss_rounds(256), seed=7)
        self.assertLess(time.perf_counter() - start, 10)
        self.assertEqual(len(swiss_pairs(t)), len(set(swiss_pairs(t))))

    def test_recommended_rounds(self):
        self.assertEqual(
            [R.recommended_swiss_rounds(n) for n in (4, 8, 9, 16, 17, 32, 33, 64, 65)],
            [3, 3, 4, 4, 5, 5, 6, 6, 7],
        )


class StandingsTests(unittest.TestCase):
    def hand_built(self) -> Tournament:
        """A 2-0 (lost one game), C 1-1, B 1-1, D 0-2.

        R1: A beats B 2-0, C beats D 2-0.  R2: A beats C 2-1, B beats D 2-0.
        """
        t = tournament_with(0)
        for pid in "ABCD":
            t = R.add_player(t, pid, player_id=pid)
        t.rounds = [
            Round(1, "swiss", [Match("r1-t1", 1, "A", "B", Result(2, 0)), Match("r1-t2", 2, "C", "D", Result(2, 0))]),
            Round(2, "swiss", [Match("r2-t1", 1, "A", "C", Result(2, 1)), Match("r2-t2", 2, "B", "D", Result(2, 0))]),
        ]
        return t

    def test_hand_calculated_tiebreakers(self):
        s = {x.player_id: x for x in R.compute_standings(self.hand_built())}
        # B and C both have 3 points and the same OMW% (opponents 1.00 and floored 0.33),
        # so game win % decides it: C won 3 of 5 games (60%), B won 2 of 4 (50%).
        self.assertAlmostEqual(s["B"].opp_match_win_pct, (1 + 0.33) / 2)
        self.assertAlmostEqual(s["C"].opp_match_win_pct, (1 + 0.33) / 2)
        self.assertAlmostEqual(s["C"].game_win_pct, 0.6)
        self.assertAlmostEqual(s["B"].game_win_pct, 0.5)
        self.assertAlmostEqual(s["D"].game_win_pct, 0.33)  # 0% floored to 33%
        self.assertAlmostEqual(s["A"].opp_match_win_pct, 0.5)
        ranking = [x.player_id for x in R.compute_standings(self.hand_built())]
        self.assertEqual(ranking, ["A", "C", "B", "D"])

    def test_draw_is_worth_one_point(self):
        t = R.pair_next_swiss_round(tournament_with(2), random.Random(1))
        t = R.report_result(t, "r1-t1", 1, 1)
        self.assertEqual([s.match_points for s in R.compute_standings(t)], [1, 1])

    def test_bye_is_a_two_nil_win(self):
        t = R.pair_next_swiss_round(tournament_with(3), random.Random(1))
        rec = next(s for s in R.compute_standings(t) if s.player_id == byes(t)[0])
        self.assertEqual((rec.match_points, rec.byes, rec.game_win_pct), (3, 1, 1.0))
        self.assertEqual(rec.opponents, [])  # byes don't count toward OMW%

    def test_dropped_player_still_counts_as_opponent(self):
        before = {s.player_id: s for s in R.compute_standings(self.hand_built())}
        after = {s.player_id: s for s in R.compute_standings(R.drop_player(self.hand_built(), "D"))}
        self.assertAlmostEqual(before["C"].opp_match_win_pct, after["C"].opp_match_win_pct)
        self.assertTrue(after["D"].dropped)

    def test_correcting_an_earlier_round(self):
        t = run_swiss(8, 2, seed=1, draws=False)
        first = t.rounds[0].matches[0]
        t = R.report_result(t, first.id, 0, 2)
        self.assertEqual(t.rounds[0].matches[0].result, Result(0, 2, 0))

    def test_save_and_load_round_trip(self):
        t = run_swiss(9, 3, seed=2)
        self.assertEqual(Tournament.from_dict(t.to_dict()), t)

    def test_changes_do_not_modify_the_original(self):
        t = tournament_with(4)
        R.add_player(t, "Someone")
        R.pair_next_swiss_round(t)
        self.assertEqual((len(t.players), len(t.rounds)), (4, 0))


class SettingsTests(unittest.TestCase):
    def test_update_only_given_settings(self):
        t = R.update_settings(tournament_with(4), name="  Store Champs ", top_cut_size=8)
        self.assertEqual((t.name, t.settings.top_cut_size, t.settings.round_minutes), ("Store Champs", 8, 50))
        t = R.update_settings(t, swiss_rounds=None)
        self.assertIsNone(t.settings.swiss_rounds)

    def test_invalid_settings(self):
        t = tournament_with(4)
        for kwargs in ({"name": " "}, {"round_minutes": 0}, {"swiss_rounds": 0}, {"top_cut_size": 6}, {"top_cut_size": 1}):
            with self.assertRaises(TournamentError, msg=kwargs):
                R.update_settings(t, **kwargs)

    def test_cut_size_locked_once_cut_starts(self):
        t = R.start_top_cut(run_swiss(8, 3, seed=1), 4)
        with self.assertRaises(TournamentError):
            R.update_settings(t, top_cut_size=8)
        # The settings form re-sends the unchanged size; that must still work.
        renamed = R.update_settings(t, name="Renamed", top_cut_size=t.settings.top_cut_size)
        self.assertEqual(renamed.name, "Renamed")


class EventDataTests(unittest.TestCase):
    def test_store_and_date(self):
        t = R.update_settings(tournament_with(0), store="  Dragon's   Den ", event_date="2026-11-02")
        self.assertEqual((t.store, t.event_date), ("Dragon's Den", "2026-11-02"))
        with self.assertRaises(TournamentError):
            R.update_settings(t, event_date="next Tuesday")

    def test_inks(self):
        t = R.set_player_inks(tournament_with(1), "p001", ["steel", "Amber"])
        self.assertEqual(t.players[0].inks, ["Amber", "Steel"])  # proper case, standard order
        self.assertEqual(R.set_player_inks(t, "p001", []).players[0].inks, [])
        for bad in (["Purple"], ["Ruby", "Ruby"], ["Ruby", "Steel", "Amber"], "Ruby"):
            with self.assertRaises(TournamentError, msg=bad):
                R.set_player_inks(t, "p001", bad)

    def test_timestamps(self):
        t = R.pair_next_swiss_round(tournament_with(3), random.Random(1), now="2026-11-02T18:00:00+00:00")
        self.assertEqual(t.rounds[0].paired_at, "2026-11-02T18:00:00+00:00")
        bye = next(m for m in t.rounds[0].matches if m.is_bye)
        self.assertEqual(bye.reported_at, "2026-11-02T18:00:00+00:00")
        match = next(m for m in t.rounds[0].matches if not m.is_bye)
        t = R.report_result(t, match.id, 2, 1, now="2026-11-02T18:41:00+00:00")
        self.assertEqual(t.rounds[0].matches[0].reported_at, "2026-11-02T18:41:00+00:00")
        t = R.clear_result(t, match.id)
        self.assertIsNone(t.rounds[0].matches[0].reported_at)

    def test_timestamps_default_to_now_in_utc(self):
        t = R.pair_next_swiss_round(tournament_with(2), random.Random(1))
        self.assertTrue(t.rounds[0].paired_at.endswith("+00:00"))

    def test_files_from_before_these_fields_still_load(self):
        old = run_swiss(4, 1, seed=1).to_dict()
        for key in ("store", "event_date"):
            del old[key]
        for p in old["players"]:
            del p["inks"]
        for r in old["rounds"]:
            del r["paired_at"]
            for m in r["matches"]:
                del m["reported_at"]
        t = Tournament.from_dict(old)
        self.assertEqual((t.store, t.players[0].inks, t.rounds[0].paired_at), ("", [], None))


class TopCutTests(unittest.TestCase):
    def test_bracket_seed_order(self):
        self.assertEqual(R.bracket_seed_order(2), [1, 2])
        self.assertEqual(R.bracket_seed_order(4), [1, 4, 2, 3])
        self.assertEqual(R.bracket_seed_order(8), [1, 8, 4, 5, 2, 7, 3, 6])

    def test_full_top_eight(self):
        rng = random.Random(5)
        t = run_swiss(20, 5, seed=5)
        top = [s.player_id for s in R.compute_standings(t)[:8]]
        t = R.start_top_cut(t, 8)
        self.assertEqual(R.phase(t), "topcut")
        first = [(m.p1, m.p2) for m in t.rounds[-1].matches]
        seed = lambda n: top[n - 1]
        self.assertEqual(first, [(seed(1), seed(8)), (seed(4), seed(5)), (seed(2), seed(7)), (seed(3), seed(6))])

        for expected_matches in (2, 1):
            t = play_round(t, rng, draws=False)
            t = R.advance_top_cut(t)
            self.assertEqual(len(t.rounds[-1].matches), expected_matches)
            for m in t.rounds[-1].matches:
                self.assertLess(R.seed_of(t, m.p1), R.seed_of(t, m.p2))

        self.assertIsNone(R.champion(t))
        t = play_round(t, rng, draws=False)
        self.assertEqual(R.phase(t), "complete")
        self.assertEqual(R.champion(t), R.match_winner(t.rounds[-1].matches[0]))
        with self.assertRaises(TournamentError):
            R.advance_top_cut(t)

    def test_top_cut_rejects_draws(self):
        t = R.start_top_cut(run_swiss(8, 3, seed=1), 4)
        with self.assertRaises(TournamentError):
            R.report_result(t, t.rounds[-1].matches[0].id, 1, 1)

    def test_dropped_players_skip_the_cut(self):
        t = run_swiss(8, 3, seed=1)
        leader = R.compute_standings(t)[0].player_id
        t = R.start_top_cut(R.drop_player(t, leader), 4)
        self.assertNotIn(leader, t.top_cut.seeds)

    def test_swiss_is_locked_once_cut_starts(self):
        t = R.start_top_cut(run_swiss(8, 3, seed=1), 4)
        with self.assertRaises(TournamentError):
            R.report_result(t, t.rounds[0].matches[0].id, 2, 0)
        with self.assertRaises(TournamentError):
            R.pair_next_swiss_round(t)

    def test_invalid_cut_sizes(self):
        t = run_swiss(8, 3, seed=1)
        for size in (0, 3, 6, 16):
            with self.assertRaises(TournamentError):
                R.start_top_cut(t, size)


if __name__ == "__main__":
    unittest.main()
