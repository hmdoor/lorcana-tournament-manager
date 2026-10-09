"""Lorcana tournament rules: results, Swiss pairings, standings and top cut.

Everything here is plain Python with no web or database code, so the same
module can sit behind a local app now and a hosted server later.

Functions that change a tournament never modify the one passed in; they return
an updated copy. That makes undo easy and keeps saved data intact if a change
is rejected.

Scoring: match win 3, draw 1, loss 0. A bye counts as a 2-0 match win.
Tiebreakers, in order: match points, opponents' match win % (OMW%),
game win % (GW%), opponents' game win % (OGW%). Percentages have a 33% floor
so one weak opponent doesn't sink your tiebreakers.
"""

from __future__ import annotations

import copy
import math
import random
import uuid
from dataclasses import asdict, dataclass, field
from typing import Literal

POINTS_WIN = 3
POINTS_DRAW = 1
POINTS_LOSS = 0
PERCENT_FLOOR = 0.33
MAX_GAME_WINS = 2  # best of 3
MAX_GAMES = 3
PAIRING_SEARCH_LIMIT = 50_000

Stage = Literal["swiss", "topcut"]
Phase = Literal["registration", "swiss", "topcut", "complete"]


class TournamentError(ValueError):
    """Raised when an action breaks the tournament rules (shown to the TO as-is)."""


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class Result:
    p1_wins: int
    p2_wins: int
    draws: int = 0


@dataclass
class Match:
    id: str
    table: int | None
    p1: str
    p2: str | None  # None means p1 has a bye
    result: Result | None = None

    @property
    def is_bye(self) -> bool:
        return self.p2 is None


@dataclass
class Round:
    number: int
    stage: Stage
    matches: list[Match]


@dataclass
class Player:
    id: str
    name: str
    dropped: bool = False
    dropped_after_round: int | None = None
    joined_round: int = 1  # rounds before this count as match losses


@dataclass
class Settings:
    round_minutes: int = 50
    swiss_rounds: int | None = None
    top_cut_size: int = 0


@dataclass
class TopCut:
    size: int
    seeds: list[str]  # seeds[0] is the 1st seed


@dataclass
class Tournament:
    name: str = "Lorcana Tournament"
    settings: Settings = field(default_factory=Settings)
    players: list[Player] = field(default_factory=list)
    rounds: list[Round] = field(default_factory=list)
    top_cut: TopCut | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Tournament:
        return cls(
            name=data["name"],
            settings=Settings(**data["settings"]),
            players=[Player(**p) for p in data["players"]],
            rounds=[
                Round(
                    number=r["number"],
                    stage=r["stage"],
                    matches=[
                        Match(**{**m, "result": Result(**m["result"]) if m["result"] else None})
                        for m in r["matches"]
                    ],
                )
                for r in data["rounds"]
            ],
            top_cut=TopCut(**data["top_cut"]) if data["top_cut"] else None,
        )


@dataclass
class Standing:
    player_id: str
    name: str
    dropped: bool
    match_points: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    byes: int = 0
    matches_played: int = 0
    game_points: int = 0
    games_played: int = 0
    opponents: list[str] = field(default_factory=list)
    match_win_pct: float = 0.0
    game_win_pct: float = 0.0
    opp_match_win_pct: float = 0.0
    opp_game_win_pct: float = 0.0
    rank: int = 0


# ---------------------------------------------------------------------------
# Tournament overview
# ---------------------------------------------------------------------------


def recommended_swiss_rounds(player_count: int) -> int:
    """Enough rounds for one undefeated player: log2(players), minimum 3."""
    if player_count < 2:
        return 0
    return max(3, math.ceil(math.log2(player_count)))


_UNSET = object()


def update_settings(
    t: Tournament,
    *,
    name=_UNSET,
    round_minutes=_UNSET,
    swiss_rounds=_UNSET,
    top_cut_size=_UNSET,
) -> Tournament:
    """Changes event settings. Only the arguments you pass are changed.

    swiss_rounds=None means "use the recommended number for the player count".
    """
    new = copy.deepcopy(t)
    if name is not _UNSET:
        new.name = _clean_name(name, "Tournament name")
    if round_minutes is not _UNSET:
        if not _is_int(round_minutes) or not 1 <= round_minutes <= 240:
            raise TournamentError("Round length must be between 1 and 240 minutes.")
        new.settings.round_minutes = round_minutes
    if swiss_rounds is not _UNSET:
        if swiss_rounds is not None and (not _is_int(swiss_rounds) or swiss_rounds < 1):
            raise TournamentError("Swiss rounds must be 1 or more, or automatic.")
        new.settings.swiss_rounds = swiss_rounds
    if top_cut_size is not _UNSET and top_cut_size != t.settings.top_cut_size:
        if t.top_cut:
            raise TournamentError("The top cut has already started.")
        if not _is_int(top_cut_size) or (top_cut_size != 0 and (top_cut_size < 2 or top_cut_size & (top_cut_size - 1))):
            raise TournamentError("Top cut must be none, or 2, 4, 8, 16, ... players.")
        new.settings.top_cut_size = top_cut_size
    return new


def phase(t: Tournament) -> Phase:
    if not t.rounds:
        return "registration"
    last = t.rounds[-1]
    if last.stage == "swiss":
        return "swiss"
    return "complete" if len(last.matches) == 1 and is_round_complete(last) else "topcut"


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------


def add_player(t: Tournament, name: str, player_id: str | None = None) -> Tournament:
    """Adds a player. Joining after round 1 is paired means a loss for each missed round."""
    clean = _clean_name(name)
    if t.top_cut:
        raise TournamentError("Players cannot join after the top cut has started.")
    existing = {p.id for p in t.players}
    if player_id is None:
        player_id = _new_id(existing)
    elif player_id in existing:
        raise TournamentError(f'A player with id "{player_id}" already exists.')

    new = copy.deepcopy(t)
    new.players.append(Player(id=player_id, name=clean, joined_round=len(_swiss_rounds(new)) + 1))
    return new


def remove_player(t: Tournament, player_id: str) -> Tournament:
    """Deletes a player entirely. Only allowed before they have been paired."""
    _find_player(t, player_id)
    if any(player_id in (m.p1, m.p2) for r in t.rounds for m in r.matches):
        raise TournamentError("This player has already been paired. Drop them instead.")
    new = copy.deepcopy(t)
    new.players = [p for p in new.players if p.id != player_id]
    return new


def rename_player(t: Tournament, player_id: str, name: str) -> Tournament:
    clean = _clean_name(name)
    new = copy.deepcopy(t)
    _find_player(new, player_id).name = clean
    return new


def drop_player(t: Tournament, player_id: str) -> Tournament:
    """Drops a player: no more pairings, but they still count as an opponent in tiebreakers."""
    new = copy.deepcopy(t)
    player = _find_player(new, player_id)
    player.dropped = True
    player.dropped_after_round = len(new.rounds)
    return new


def reinstate_player(t: Tournament, player_id: str) -> Tournament:
    """Undoes a drop (e.g. dropped by mistake)."""
    new = copy.deepcopy(t)
    player = _find_player(new, player_id)
    player.dropped = False
    player.dropped_after_round = None
    return new


# ---------------------------------------------------------------------------
# Match results
# ---------------------------------------------------------------------------


def validate_result(p1_wins: int, p2_wins: int, draws: int = 0, allow_draw: bool = True) -> str | None:
    """Returns an error message, or None if the best-of-3 result is valid."""
    for label, value in (("Player 1 wins", p1_wins), ("Player 2 wins", p2_wins), ("Drawn games", draws)):
        if not _is_int(value) or value < 0:
            return f"{label} must be a whole number of 0 or more."
    if p1_wins > MAX_GAME_WINS or p2_wins > MAX_GAME_WINS:
        return "A player can win at most 2 games in a best-of-3 match."
    if p1_wins == MAX_GAME_WINS and p2_wins == MAX_GAME_WINS:
        return "Both players cannot win 2 games."
    if p1_wins + p2_wins + draws > MAX_GAMES:
        return "A best-of-3 match has at most 3 games."
    if not allow_draw and p1_wins == p2_wins:
        return "Top cut matches must have a winner."
    return None


def match_outcome(result: Result) -> Literal["p1", "p2", "draw"]:
    """Whoever won more games wins the match."""
    if result.p1_wins > result.p2_wins:
        return "p1"
    if result.p2_wins > result.p1_wins:
        return "p2"
    return "draw"


def match_winner(match: Match) -> str | None:
    if match.result is None:
        return None
    outcome = match_outcome(match.result)
    return match.p1 if outcome == "p1" else match.p2 if outcome == "p2" else None


def report_result(t: Tournament, match_id: str, p1_wins: int, p2_wins: int, draws: int = 0) -> Tournament:
    """Records a result.

    Results in the current round can always be changed. Earlier Swiss results can be
    corrected until the top cut starts; that updates standings but never re-pairs
    rounds that already exist.
    """
    new = copy.deepcopy(t)
    rnd, match = _find_match(new, match_id)
    if match.is_bye:
        raise TournamentError("Byes are recorded automatically.")
    _assert_editable(new, rnd)
    error = validate_result(p1_wins, p2_wins, draws, allow_draw=rnd.stage == "swiss")
    if error:
        raise TournamentError(error)
    match.result = Result(p1_wins, p2_wins, draws)
    return new


def clear_result(t: Tournament, match_id: str) -> Tournament:
    new = copy.deepcopy(t)
    rnd, match = _find_match(new, match_id)
    if match.is_bye:
        raise TournamentError("Byes cannot be cleared.")
    _assert_editable(new, rnd)
    match.result = None
    return new


def is_round_complete(rnd: Round) -> bool:
    return all(m.result is not None for m in rnd.matches)


# ---------------------------------------------------------------------------
# Standings
# ---------------------------------------------------------------------------


def compute_standings(t: Tournament) -> list[Standing]:
    """Swiss standings, best first. Only reported matches count."""
    records = {p.id: Standing(player_id=p.id, name=p.name, dropped=p.dropped) for p in t.players}

    for rnd in _swiss_rounds(t):
        # Late arrivals take a 0-2 match loss for each round they missed.
        for p in t.players:
            if rnd.number < p.joined_round:
                _apply_games(records[p.id], None, 0, 2, 0)
        for m in rnd.matches:
            if m.result is None:
                continue
            if m.is_bye:
                records[m.p1].byes += 1
                _apply_games(records[m.p1], None, 2, 0, 0)
                continue
            r = m.result
            _apply_games(records[m.p1], m.p2, r.p1_wins, r.p2_wins, r.draws)
            _apply_games(records[m.p2], m.p1, r.p2_wins, r.p1_wins, r.draws)

    for rec in records.values():
        rec.match_win_pct = _pct(rec.match_points, rec.matches_played)
        rec.game_win_pct = _pct(rec.game_points, rec.games_played)
    for rec in records.values():
        opps = [records[o] for o in rec.opponents]
        rec.opp_match_win_pct = _average([o.match_win_pct for o in opps])
        rec.opp_game_win_pct = _average([o.game_win_pct for o in opps])

    standings = sorted(
        records.values(),
        key=lambda s: (
            -s.match_points,
            -round(s.opp_match_win_pct, 9),
            -round(s.game_win_pct, 9),
            -round(s.opp_game_win_pct, 9),
            s.name.casefold(),
        ),
    )
    for i, s in enumerate(standings, start=1):
        s.rank = i
    return standings


def _apply_games(rec: Standing, opponent_id: str | None, my_wins: int, opp_wins: int, drawn: int) -> None:
    if opponent_id is not None:
        rec.opponents.append(opponent_id)
    rec.matches_played += 1
    if my_wins > opp_wins:
        rec.wins += 1
        rec.match_points += POINTS_WIN
    elif opp_wins > my_wins:
        rec.losses += 1
        rec.match_points += POINTS_LOSS
    else:
        rec.draws += 1
        rec.match_points += POINTS_DRAW
    rec.game_points += my_wins * POINTS_WIN + drawn * POINTS_DRAW
    rec.games_played += my_wins + opp_wins + drawn


def _pct(points: int, played: int) -> float:
    if played == 0:
        return PERCENT_FLOOR
    return max(PERCENT_FLOOR, points / (POINTS_WIN * played))


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


# ---------------------------------------------------------------------------
# Swiss pairings
# ---------------------------------------------------------------------------


def pair_next_swiss_round(t: Tournament, rng: random.Random | None = None) -> Tournament:
    """Pairs the next Swiss round.

    Players are paired within their match-point group (random order inside the
    group), avoiding rematches. With an odd number of players, the lowest-ranked
    player who hasn't had a bye gets one. If no rematch-free pairing exists
    (only possible in very small events), rematches are allowed.
    """
    rng = rng or random.Random()
    if t.top_cut:
        raise TournamentError("The top cut has started; no more Swiss rounds can be paired.")
    if t.rounds and not is_round_complete(t.rounds[-1]):
        raise TournamentError(f"Round {t.rounds[-1].number} still has unreported matches.")
    active = [p.id for p in t.players if not p.dropped]
    if len(active) < 2:
        raise TournamentError("At least 2 active players are needed to pair a round.")

    points = {s.player_id: s.match_points for s in compute_standings(t)}
    order = active[:]
    rng.shuffle(order)
    order.sort(key=lambda pid: -points[pid])  # stable sort: random order within each point group

    played: set[frozenset[str]] = set()
    had_bye: set[str] = set()
    for rnd in _swiss_rounds(t):
        for m in rnd.matches:
            if m.is_bye:
                had_bye.add(m.p1)
            else:
                played.add(frozenset((m.p1, m.p2)))

    bye_player = None
    if len(order) % 2 == 0:
        pairs = _find_pairings(order, played)
        if pairs is None:
            pairs = _find_pairings(order, None)
    else:
        lowest_first = order[::-1]
        candidates = [pid for pid in lowest_first if pid not in had_bye] or lowest_first
        pairs = None
        for pid in candidates:
            pairs = _find_pairings([x for x in order if x != pid], played)
            if pairs is not None:
                bye_player = pid
                break
        if pairs is None:
            bye_player = candidates[0]
            pairs = _find_pairings([x for x in order if x != bye_player], None)

    number = len(t.rounds) + 1
    matches = [
        Match(id=f"r{number}-t{i}", table=i, p1=p1, p2=p2)
        for i, (p1, p2) in enumerate(pairs, start=1)
    ]
    if bye_player is not None:
        matches.append(Match(id=f"r{number}-bye", table=None, p1=bye_player, p2=None, result=Result(2, 0, 0)))

    new = copy.deepcopy(t)
    new.rounds.append(Round(number=number, stage="swiss", matches=matches))
    return new


def _find_pairings(ids: list[str], played: set[frozenset[str]] | None) -> list[tuple[str, str]] | None:
    """Depth-first search for a full pairing.

    `ids` is in pairing order, so each player tries the closest-ranked opponents
    first. `played` holds pairs to avoid, or None to allow rematches.
    """
    budget = PAIRING_SEARCH_LIMIT

    def solve(remaining: list[str]) -> list[tuple[str, str]] | None:
        nonlocal budget
        if not remaining:
            return []
        budget -= 1
        if budget < 0:
            return None
        first, rest = remaining[0], remaining[1:]
        for i, opp in enumerate(rest):
            if played is not None and frozenset((first, opp)) in played:
                continue
            sub = solve(rest[:i] + rest[i + 1 :])
            if sub is not None:
                return [(first, opp), *sub]
            if budget < 0:
                return None
        return None

    return solve(ids)


# ---------------------------------------------------------------------------
# Top cut (single elimination)
# ---------------------------------------------------------------------------


def bracket_seed_order(size: int) -> list[int]:
    """Bracket order so seeds 1 and 2 can only meet in the final: 8 -> [1,8,4,5,2,7,3,6]."""
    order = [1]
    while len(order) < size:
        n = len(order) * 2
        order = [s for seed in order for s in (seed, n + 1 - seed)]
    return order


def start_top_cut(t: Tournament, size: int | None = None) -> Tournament:
    """Seeds the top `size` non-dropped players from the final Swiss standings."""
    size = t.settings.top_cut_size if size is None else size
    if size < 2 or size & (size - 1):
        raise TournamentError("Top cut size must be a power of 2 (2, 4, 8, 16, ...).")
    if t.top_cut:
        raise TournamentError("The top cut has already started.")
    if not t.rounds:
        raise TournamentError("Play at least one Swiss round before the top cut.")
    if not is_round_complete(t.rounds[-1]):
        raise TournamentError(f"Round {t.rounds[-1].number} still has unreported matches.")

    eligible = [s for s in compute_standings(t) if not s.dropped]
    if len(eligible) < size:
        raise TournamentError(f"Only {len(eligible)} active players; cannot cut to {size}.")

    seeds = [s.player_id for s in eligible[:size]]
    order = bracket_seed_order(size)
    number = len(t.rounds) + 1
    matches = [
        Match(id=f"r{number}-m{table}", table=table, p1=seeds[order[i] - 1], p2=seeds[order[i + 1] - 1])
        for table, i in enumerate(range(0, size, 2), start=1)
    ]

    new = copy.deepcopy(t)
    new.top_cut = TopCut(size=size, seeds=seeds)
    new.rounds.append(Round(number=number, stage="topcut", matches=matches))
    return new


def advance_top_cut(t: Tournament) -> Tournament:
    """Pairs the winners of the current top cut round. The better seed is player 1."""
    if not t.rounds or t.rounds[-1].stage != "topcut":
        raise TournamentError("The top cut has not started.")
    last = t.rounds[-1]
    if not is_round_complete(last):
        raise TournamentError(f"Round {last.number} still has unreported matches.")
    if len(last.matches) == 1:
        raise TournamentError("The top cut is finished.")

    winners = [match_winner(m) for m in last.matches]
    number = len(t.rounds) + 1
    matches = []
    for table, i in enumerate(range(0, len(winners), 2), start=1):
        p1, p2 = sorted(winners[i : i + 2], key=lambda pid: seed_of(t, pid))
        matches.append(Match(id=f"r{number}-m{table}", table=table, p1=p1, p2=p2))

    new = copy.deepcopy(t)
    new.rounds.append(Round(number=number, stage="topcut", matches=matches))
    return new


def seed_of(t: Tournament, player_id: str) -> int | None:
    """1-based top cut seed, or None if the player isn't in the cut."""
    if not t.top_cut or player_id not in t.top_cut.seeds:
        return None
    return t.top_cut.seeds.index(player_id) + 1


def champion(t: Tournament) -> str | None:
    if phase(t) != "complete":
        return None
    return match_winner(t.rounds[-1].matches[0])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _swiss_rounds(t: Tournament) -> list[Round]:
    return [r for r in t.rounds if r.stage == "swiss"]


def _find_player(t: Tournament, player_id: str) -> Player:
    for p in t.players:
        if p.id == player_id:
            return p
    raise TournamentError(f'No player with id "{player_id}".')


def _find_match(t: Tournament, match_id: str) -> tuple[Round, Match]:
    for rnd in t.rounds:
        for m in rnd.matches:
            if m.id == match_id:
                return rnd, m
    raise TournamentError(f'No match with id "{match_id}".')


def _assert_editable(t: Tournament, rnd: Round) -> None:
    if rnd is t.rounds[-1]:
        return
    if rnd.stage == "swiss" and not t.top_cut:
        return
    raise TournamentError(f"Round {rnd.number} is locked; later rounds have already been paired.")


def _clean_name(name: str, label: str = "Player name") -> str:
    clean = name.strip() if isinstance(name, str) else ""
    if not clean:
        raise TournamentError(f"{label} is required.")
    return clean


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _new_id(existing: set[str]) -> str:
    while True:
        new_id = uuid.uuid4().hex[:8]
        if new_id not in existing:
            return new_id
