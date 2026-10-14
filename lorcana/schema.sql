-- Lorcana Tournament Manager database schema (SQLite).
--
-- Diagram and design notes: docs/data/erd.md
--
-- Tables are STRICT, so SQLite rejects values of the wrong type (e.g. text in an
-- INTEGER column) instead of silently storing them.
-- Times are UTC ISO 8601 text (2026-10-14T19:05:12+00:00) so they sort correctly
-- and work with SQLite's date functions. Dates are YYYY-MM-DD.

PRAGMA foreign_keys = ON;

-- The six Lorcana inks. A lookup table, so deck data can only use real inks.
CREATE TABLE IF NOT EXISTS inks (
    ink_id  INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE
) STRICT;

INSERT OR IGNORE INTO inks (ink_id, name) VALUES
    (1, 'Amber'), (2, 'Amethyst'), (3, 'Emerald'), (4, 'Ruby'), (5, 'Sapphire'), (6, 'Steel');

-- Stores that host events. Matched by name, ignoring capitals.
CREATE TABLE IF NOT EXISTS stores (
    store_id  INTEGER PRIMARY KEY,
    name      TEXT NOT NULL UNIQUE COLLATE NOCASE
) STRICT;

-- Real people, across all events. One person can have many registrations.
-- name_key is the matching rule: lower case, single spaces. See LTM-48.
CREATE TABLE IF NOT EXISTS people (
    person_id     INTEGER PRIMARY KEY,
    display_name  TEXT NOT NULL,
    name_key      TEXT NOT NULL
) STRICT;

CREATE INDEX IF NOT EXISTS people_name_key ON people (name_key);

-- One row per tournament.
CREATE TABLE IF NOT EXISTS events (
    event_id       TEXT PRIMARY KEY,                -- the app's tournament id
    name           TEXT NOT NULL,
    store_id       INTEGER REFERENCES stores (store_id),
    event_date     TEXT NOT NULL,                   -- YYYY-MM-DD
    round_minutes  INTEGER NOT NULL,
    swiss_rounds   INTEGER,                         -- NULL = automatic
    top_cut_size   INTEGER NOT NULL DEFAULT 0,      -- 0 = no top cut
    status         TEXT NOT NULL
                   CHECK (status IN ('registration', 'swiss', 'topcut', 'complete')),
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    deleted_at     TEXT                             -- NULL = not deleted ("soft delete")
) STRICT;

-- A person playing in one event, with their deck for that event.
CREATE TABLE IF NOT EXISTS registrations (
    registration_id      INTEGER PRIMARY KEY,
    event_id             TEXT NOT NULL REFERENCES events (event_id) ON DELETE CASCADE,
    person_id            INTEGER NOT NULL REFERENCES people (person_id),
    app_player_id        TEXT NOT NULL,             -- the app's player id within this event
    name_at_event        TEXT NOT NULL,             -- name as entered for this event
    joined_round         INTEGER NOT NULL DEFAULT 1, -- > 1 means a late entry
    dropped_after_round  INTEGER,                   -- NULL = did not drop
    ink_1_id             INTEGER REFERENCES inks (ink_id),
    ink_2_id             INTEGER REFERENCES inks (ink_id),
    top_cut_seed         INTEGER,                   -- NULL = did not make the cut
    position             INTEGER NOT NULL,          -- registration order
    UNIQUE (event_id, app_player_id),
    UNIQUE (event_id, person_id),
    CHECK (ink_2_id IS NULL OR (ink_1_id IS NOT NULL AND ink_2_id <> ink_1_id))
) STRICT;

-- Rounds of an event, Swiss and top cut, in order.
CREATE TABLE IF NOT EXISTS rounds (
    round_id      INTEGER PRIMARY KEY,
    event_id      TEXT NOT NULL REFERENCES events (event_id) ON DELETE CASCADE,
    round_number  INTEGER NOT NULL,
    stage         TEXT NOT NULL CHECK (stage IN ('swiss', 'topcut')),
    paired_at     TEXT,
    UNIQUE (event_id, round_number)
) STRICT;

-- Matches in a round. player2_id is NULL for a bye.
-- Game scores are NULL until the result is reported.
CREATE TABLE IF NOT EXISTS matches (
    match_id      INTEGER PRIMARY KEY,
    round_id      INTEGER NOT NULL REFERENCES rounds (round_id) ON DELETE CASCADE,
    app_match_id  TEXT NOT NULL,                    -- e.g. r3-t5, r3-bye, r5-m1
    table_number  INTEGER,                          -- NULL for a bye
    player1_id    INTEGER NOT NULL REFERENCES registrations (registration_id),
    player2_id    INTEGER REFERENCES registrations (registration_id),
    p1_wins       INTEGER,
    p2_wins       INTEGER,
    draws         INTEGER,
    reported_at   TEXT,
    UNIQUE (round_id, app_match_id),
    -- Best of 3: nobody wins more than 2 games, and at most 3 games are played.
    CHECK (p1_wins BETWEEN 0 AND 2 AND p2_wins BETWEEN 0 AND 2 AND draws >= 0),
    CHECK (NOT (p1_wins = 2 AND p2_wins = 2)),
    CHECK (p1_wins + p2_wins + draws <= 3),
    CHECK (player2_id IS NULL OR player2_id <> player1_id)
) STRICT;

-- App state that isn't tournament data: the round timer and the undo history.
-- Stored as JSON because it is only ever read whole by the app, never queried.
CREATE TABLE IF NOT EXISTS event_app_state (
    event_id      TEXT PRIMARY KEY REFERENCES events (event_id) ON DELETE CASCADE,
    timer_json    TEXT NOT NULL,
    history_json  TEXT NOT NULL
) STRICT;
