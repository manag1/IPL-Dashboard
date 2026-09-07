import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

JSON_FOLDER = r"C:\Users\rsrik\Desktop\My Programs\IPL\IPL\ipl_json"
DB_FOLDER = r"C:\Users\rsrik\Desktop\My Programs\IPL\IPL\database"
DB_NAME = "ipl.db"
BACKUP_BEFORE_UPDATE = True
DB_PATH = Path(DB_FOLDER) / DB_NAME
JSON_PATH = Path(JSON_FOLDER)
BOWLER_WICKET_KINDS = {"bowled", "caught", "caught and bowled", "lbw", "stumped", "hit wicket"}
CATCH_KINDS = {"caught", "caught and bowled"}
STUMPING_KINDS = {"stumped"}

def create_schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS teams (
        team_id     INTEGER PRIMARY KEY AUTOINCREMENT,
        team_name   TEXT NOT NULL UNIQUE
    );
    CREATE TABLE IF NOT EXISTS players (
        player_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        player_name  TEXT NOT NULL,
        registry_id  TEXT UNIQUE
    );
    CREATE TABLE IF NOT EXISTS matches (
        match_id         INTEGER PRIMARY KEY AUTOINCREMENT,
        source_match_id  TEXT NOT NULL UNIQUE,
        season           TEXT,
        year             TEXT,
        match_date       TEXT,
        venue            TEXT,
        team1_id         INTEGER REFERENCES teams(team_id),
        team2_id         INTEGER REFERENCES teams(team_id),
        winner_team_id   INTEGER REFERENCES teams(team_id),
        result_type      TEXT,
        result_margin    INTEGER,
        result_method    TEXT,
        result_margin_type TEXT
    );
    CREATE TABLE IF NOT EXISTS innings (
        innings_id       INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id         INTEGER NOT NULL REFERENCES matches(match_id),
        innings_number   INTEGER NOT NULL,
        batting_team_id  INTEGER REFERENCES teams(team_id),
        bowling_team_id  INTEGER REFERENCES teams(team_id),
        is_super_over    INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS deliveries (
        delivery_id            INTEGER PRIMARY KEY AUTOINCREMENT,
        innings_id             INTEGER NOT NULL REFERENCES innings(innings_id),
        over_number             INTEGER NOT NULL,
        delivery_index          INTEGER NOT NULL,
        batter_id                INTEGER REFERENCES players(player_id),
        non_striker_id           INTEGER REFERENCES players(player_id),
        bowler_id                INTEGER REFERENCES players(player_id),
        batter_runs               INTEGER NOT NULL DEFAULT 0,
        extras_runs                INTEGER NOT NULL DEFAULT 0,
        total_runs                  INTEGER NOT NULL DEFAULT 0,
        is_four                      INTEGER NOT NULL DEFAULT 0,
        is_six                        INTEGER NOT NULL DEFAULT 0,
        is_dot                         INTEGER NOT NULL DEFAULT 0,
        is_wicket                       INTEGER NOT NULL DEFAULT 0,
        wide_runs                        INTEGER NOT NULL DEFAULT 0,
        noball_runs                       INTEGER NOT NULL DEFAULT 0,
        bye_runs                          INTEGER NOT NULL DEFAULT 0,
        legbye_runs                        INTEGER NOT NULL DEFAULT 0,
        penalty_runs                        INTEGER NOT NULL DEFAULT 0,
        is_legal_delivery                    INTEGER NOT NULL DEFAULT 1,
        bowler_runs_conceded                  INTEGER NOT NULL DEFAULT 0,
        bowler_wickets                         INTEGER NOT NULL DEFAULT 0,
        counts_as_faced                         INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS wickets (
        wicket_id       INTEGER PRIMARY KEY AUTOINCREMENT,
        delivery_id     INTEGER NOT NULL REFERENCES deliveries(delivery_id),
        player_out_id   INTEGER REFERENCES players(player_id),
        wicket_kind     TEXT
    );
    CREATE TABLE IF NOT EXISTS wicket_fielders (
        wicket_id   INTEGER NOT NULL REFERENCES wickets(wicket_id),
        player_id   INTEGER NOT NULL REFERENCES players(player_id)
    );
    CREATE TABLE IF NOT EXISTS delivery_extras (
        delivery_id   INTEGER NOT NULL REFERENCES deliveries(delivery_id),
        extra_type    TEXT NOT NULL,
        runs          INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS match_players (
        match_id    INTEGER NOT NULL REFERENCES matches(match_id),
        team_id     INTEGER NOT NULL REFERENCES teams(team_id),
        player_id   INTEGER NOT NULL REFERENCES players(player_id),
        UNIQUE(match_id, team_id, player_id)
    );
    CREATE TABLE IF NOT EXISTS match_player_of_match (
        match_id    INTEGER NOT NULL REFERENCES matches(match_id),
        player_id   INTEGER NOT NULL REFERENCES players(player_id),
        UNIQUE(match_id, player_id)
    );
    CREATE INDEX IF NOT EXISTS idx_deliveries_innings ON deliveries(innings_id);
    CREATE INDEX IF NOT EXISTS idx_deliveries_batter ON deliveries(batter_id);
    CREATE INDEX IF NOT EXISTS idx_deliveries_nonstriker ON deliveries(non_striker_id);
    CREATE INDEX IF NOT EXISTS idx_deliveries_bowler ON deliveries(bowler_id);
    CREATE INDEX IF NOT EXISTS idx_innings_match ON innings(match_id);
    CREATE INDEX IF NOT EXISTS idx_matches_year ON matches(year);
    CREATE INDEX IF NOT EXISTS idx_matches_venue ON matches(venue);
    CREATE INDEX IF NOT EXISTS idx_wickets_delivery ON wickets(delivery_id);
    CREATE INDEX IF NOT EXISTS idx_wicket_fielders_wicket ON wicket_fielders(wicket_id);
    CREATE INDEX IF NOT EXISTS idx_match_players_player ON match_players(player_id);
    """)


def add_derived_columns(conn):
    """Upgrade an older DB to the current schema and recompute derived columns."""
    deliveries_existing = {r[1] for r in conn.execute("PRAGMA table_info(deliveries)")}
    delivery_columns = {
        "wide_runs": "INTEGER NOT NULL DEFAULT 0",
        "noball_runs": "INTEGER NOT NULL DEFAULT 0",
        "bye_runs": "INTEGER NOT NULL DEFAULT 0",
        "legbye_runs": "INTEGER NOT NULL DEFAULT 0",
        "penalty_runs": "INTEGER NOT NULL DEFAULT 0",
        "is_legal_delivery": "INTEGER NOT NULL DEFAULT 1",
        "bowler_runs_conceded": "INTEGER NOT NULL DEFAULT 0",
        "bowler_wickets": "INTEGER NOT NULL DEFAULT 0",
        "counts_as_faced": "INTEGER NOT NULL DEFAULT 1",
        "is_dot": "INTEGER NOT NULL DEFAULT 0",
        "is_four": "INTEGER NOT NULL DEFAULT 0",
        "is_six": "INTEGER NOT NULL DEFAULT 0",
    }
    for col, definition in delivery_columns.items():
        if col not in deliveries_existing:
            conn.execute(f"ALTER TABLE deliveries ADD COLUMN {col} {definition}")
    conn.execute("""
        UPDATE deliveries
        SET
            counts_as_faced = CASE WHEN wide_runs > 0 THEN 0 ELSE 1 END,
            is_legal_delivery = CASE WHEN wide_runs > 0 OR noball_runs > 0 THEN 0 ELSE 1 END,
            bowler_runs_conceded = batter_runs + wide_runs + noball_runs,
            is_dot = CASE WHEN total_runs = 0 THEN 1 ELSE 0 END
    """)
    innings_existing = {r[1] for r in conn.execute("PRAGMA table_info(innings)")}
    if "is_super_over" not in innings_existing:
        conn.execute("ALTER TABLE innings ADD COLUMN is_super_over INTEGER NOT NULL DEFAULT 0")
    if "bowling_team_id" not in innings_existing:
        conn.execute("ALTER TABLE innings ADD COLUMN bowling_team_id INTEGER REFERENCES teams(team_id)")
        conn.execute("""
            UPDATE innings
            SET bowling_team_id = (
                SELECT CASE WHEN innings.batting_team_id = m.team1_id THEN m.team2_id ELSE m.team1_id END
                FROM matches m WHERE m.match_id = innings.match_id
            )
        """)
    matches_existing = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
    match_columns = {
        "year": "TEXT",
        "winner_team_id": "INTEGER REFERENCES teams(team_id)",
        "result_type": "TEXT",
        "result_margin": "INTEGER",
        "result_method": "TEXT",
        "result_margin_type": "TEXT",
    }
    for col, definition in match_columns.items():
        if col not in matches_existing:
            conn.execute(f"ALTER TABLE matches ADD COLUMN {col} {definition}")
    conn.execute("UPDATE matches SET year = substr(match_date, 1, 4) WHERE year IS NULL AND match_date IS NOT NULL")


def get_or_create_team(conn, name):
    row = conn.execute("SELECT team_id FROM teams WHERE team_name = ?", (name,)).fetchone()
    if row:
        return row[0]
    return conn.execute("INSERT INTO teams(team_name) VALUES (?)", (name,)).lastrowid


def get_or_create_player(conn, name, registry_id=None):
    if registry_id:
        row = conn.execute("SELECT player_id FROM players WHERE registry_id = ?", (registry_id,)).fetchone()
        if row:
            return row[0]
    row = conn.execute("""
        SELECT player_id, registry_id FROM players WHERE player_name = ?
        ORDER BY CASE WHEN registry_id IS NULL THEN 0 ELSE 1 END, player_id LIMIT 1
    """, (name,)).fetchone()
    if row:
        player_id, existing_registry = row
        if registry_id and existing_registry is None:
            conn.execute("UPDATE players SET registry_id = ? WHERE player_id = ?", (registry_id, player_id))
        return player_id
    return conn.execute(
        "INSERT INTO players(player_name, registry_id) VALUES (?, ?)", (name, registry_id)
    ).lastrowid


def player_registry(info):
    return info.get("registry", {}).get("people", {})


def _match_result_fields(info, team1_id, team2_id, conn):
    outcome = info.get("outcome") or {}
    winner_name = outcome.get("winner")
    winner_id = None
    if winner_name:
        winner_id = get_or_create_team(conn, winner_name)
    by = outcome.get("by") or {}
    margin = None
    margin_type = None
    if "runs" in by:
        margin, margin_type = by.get("runs"), "runs"
    elif "wickets" in by:
        margin, margin_type = by.get("wickets"), "wickets"
    method = outcome.get("method")
    result = outcome.get("result")
    if winner_id is not None:
        result_type = "win"
    elif result == "tie" and outcome.get("eliminator"):
        winner_id = get_or_create_team(conn, outcome.get("eliminator"))
        result_type = "super_over"
    elif result == "tie":
        result_type = "tie"
    elif result in ("no result", "abandoned"):
        result_type = "no_result"
    else:
        result_type = None
    return winner_id, result_type, margin, method, margin_type


def get_or_create_match(conn, match_id, info, team1_id, team2_id):
    existing = conn.execute(
        "SELECT match_id FROM matches WHERE source_match_id = ?", (match_id,)
    ).fetchone()
    dates = info.get("dates", [])
    match_date = dates[0] if dates else None
    season = info.get("season")
    venue = info.get("venue")
    year = match_date[:4] if match_date else (str(season)[:4] if season else None)
    winner_id, result_type, margin, method, margin_type = _match_result_fields(info, team1_id, team2_id, conn)
    if existing:
        conn.execute("""
            UPDATE matches
            SET season=?, year=?, match_date=?, venue=?, team1_id=?, team2_id=?,
                winner_team_id=?, result_type=?, result_margin=?, result_method=?, result_margin_type=?
            WHERE match_id=?
        """, (str(season) if season is not None else None, year, match_date, venue, team1_id, team2_id,
              winner_id, result_type, margin, method, margin_type, existing[0]))
        return existing[0], False
    cur = conn.execute("""
        INSERT INTO matches (source_match_id, season, year, match_date, venue, team1_id, team2_id,
                             winner_team_id, result_type, result_margin, result_method, result_margin_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (str(match_id), str(season) if season is not None else None, year,
          match_date, venue, team1_id, team2_id, winner_id, result_type, margin, method, margin_type))
    return cur.lastrowid, True


def insert_match_players(conn, match_db_id, info, team_ids):
    registry = player_registry(info)
    for team_name, players in info.get("players", {}).items():
        team_id = team_ids.get(team_name)
        if not team_id:
            continue
        for name in players:
            player_id = get_or_create_player(conn, name, registry.get(name))
            conn.execute("""
                INSERT OR IGNORE INTO match_players(match_id, team_id, player_id) VALUES (?, ?, ?)
            """, (match_db_id, team_id, player_id))


def insert_player_of_match(conn, match_db_id, info):
    registry = player_registry(info)
    for name in info.get("player_of_match", []):
        player_id = get_or_create_player(conn, name, registry.get(name))
        conn.execute("""
            INSERT OR IGNORE INTO match_player_of_match(match_id, player_id) VALUES (?, ?)
        """, (match_db_id, player_id))


def ensure_match_player_rows(conn, match_db_id, info, team_ids):
    """Backfill match participation rows for existing matches.

    This is important when an older database already contains the match but
    did not have all match_players rows needed by Player-of-the-Match views.
    """
    insert_match_players(conn, match_db_id, info, team_ids)


def backfill_match_metadata(conn, json_path):
    """Backfill Player-of-the-Match and fielding-related metadata.

    Existing matches are normally skipped by import_match(). This function
    deliberately processes them so that adding this script to an older DB
    can recover missing Player-of-the-Match rows and match participation
    needed to resolve award/team dimensions.

    Catches and stumpings are already stored at event level in:
      wickets -> wicket_fielders
    and are exposed through v_fielding_events. We do not store fragile
    aggregate totals; they are recomputed from the underlying events.
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    info = data.get("info", {})
    source_match_id = json_path.stem
    match_row = conn.execute(
        "SELECT match_id, team1_id, team2_id FROM matches WHERE source_match_id = ?",
        (source_match_id,)
    ).fetchone()
    if not match_row:
        return False

    match_db_id, team1_id, team2_id = match_row
    teams = info.get("teams", [])
    team_ids = {teams[0]: team1_id, teams[1]: team2_id} if len(teams) >= 2 else {}

    ensure_match_player_rows(conn, match_db_id, info, team_ids)
    insert_player_of_match(conn, match_db_id, info)

    registry = player_registry(info)

    # If an older DB has no deliveries for this match, import the complete
    # innings. Otherwise retain the existing delivery IDs and reconcile only
    # missing fielding credits below.
    existing_delivery_count = conn.execute("""
        SELECT COUNT(*)
        FROM deliveries d
        JOIN innings i ON i.innings_id = d.innings_id
        WHERE i.match_id = ?
    """, (match_db_id,)).fetchone()[0]

    if existing_delivery_count == 0:
        for innings_number, innings_data in enumerate(data.get("innings", []), start=1):
            batting_team_name = innings_data.get("team")
            if not batting_team_name:
                continue
            batting_team_id = team_ids.get(batting_team_name) or get_or_create_team(conn, batting_team_name)
            bowling_team_id = team2_id if batting_team_id == team1_id else team1_id
            is_super_over = 1 if innings_data.get("super_over") else 0
            cur = conn.execute("""
                INSERT INTO innings (
                    match_id, innings_number, batting_team_id, bowling_team_id, is_super_over
                ) VALUES (?, ?, ?, ?, ?)
            """, (match_db_id, innings_number, batting_team_id, bowling_team_id, is_super_over))
            innings_id = cur.lastrowid
            delivery_index = 0
            for over in innings_data.get("overs", []):
                over_number = over.get("over", 0)
                for delivery in over.get("deliveries", []):
                    delivery_index += 1
                    insert_delivery(
                        conn, innings_id, over_number, delivery_index, delivery, registry
                    )
    else:
        # Reconcile missing fielder credits against the source JSON.
        # The existing importer uses one delivery_index sequence per innings,
        # so (innings_number, over_number, delivery_index) is a stable bridge.
        for innings_number, innings_data in enumerate(data.get("innings", []), start=1):
            innings_row = conn.execute("""
                SELECT innings_id
                FROM innings
                WHERE match_id = ? AND innings_number = ?
            """, (match_db_id, innings_number)).fetchone()
            if not innings_row:
                continue

            innings_id = innings_row[0]
            delivery_index = 0

            for over in innings_data.get("overs", []):
                over_number = over.get("over", 0)
                for delivery in over.get("deliveries", []):
                    delivery_index += 1
                    wickets = delivery.get("wickets", [])
                    if not wickets:
                        continue

                    drow = conn.execute("""
                        SELECT delivery_id
                        FROM deliveries
                        WHERE innings_id = ?
                          AND over_number = ?
                          AND delivery_index = ?
                    """, (innings_id, over_number, delivery_index)).fetchone()
                    if not drow:
                        continue

                    delivery_id = drow[0]
                    db_wickets = conn.execute("""
                        SELECT wicket_id, wicket_kind
                        FROM wickets
                        WHERE delivery_id = ?
                        ORDER BY wicket_id
                    """, (delivery_id,)).fetchall()

                    for idx, wicket in enumerate(wickets):
                        if idx >= len(db_wickets):
                            continue

                        wicket_id, db_kind = db_wickets[idx]
                        source_kind = wicket.get("kind")
                        if db_kind != source_kind:
                            continue

                        for fielder in wicket.get("fielders", []):
                            fielder_name = (
                                fielder.get("name")
                                if isinstance(fielder, dict) else fielder
                            )
                            if not fielder_name:
                                continue

                            fielder_id = get_or_create_player(
                                conn, fielder_name, registry.get(fielder_name)
                            )
                            conn.execute("""
                                INSERT OR IGNORE INTO wicket_fielders(wicket_id, player_id)
                                VALUES (?, ?)
                            """, (wicket_id, fielder_id))

    return True


def insert_delivery(conn, innings_id, over_number, delivery_index, delivery, registry):
    batter_name = delivery.get("batter")
    non_striker_name = delivery.get("non_striker")
    bowler_name = delivery.get("bowler")
    batter_id = get_or_create_player(conn, batter_name, registry.get(batter_name))
    non_striker_id = get_or_create_player(conn, non_striker_name, registry.get(non_striker_name))
    bowler_id = get_or_create_player(conn, bowler_name, registry.get(bowler_name))
    runs = delivery.get("runs", {})
    extras = delivery.get("extras", {})
    batter_runs = int(runs.get("batter", 0))
    extras_runs = int(runs.get("extras", 0))
    total_runs = int(runs.get("total", batter_runs + extras_runs))
    wide_runs = int(extras.get("wides", 0))
    noball_runs = int(extras.get("noballs", 0))
    bye_runs = int(extras.get("byes", 0))
    legbye_runs = int(extras.get("legbyes", 0))
    penalty_runs = int(extras.get("penalty", 0))
    is_legal_delivery = 0 if (wide_runs > 0 or noball_runs > 0) else 1
    counts_as_faced = 0 if wide_runs > 0 else 1
    bowler_runs_conceded = batter_runs + wide_runs + noball_runs
    is_dot = 1 if total_runs == 0 else 0
    non_boundary = bool(runs.get("non_boundary", False))
    wickets = delivery.get("wickets", [])
    bowler_wickets = sum(1 for w in wickets if w.get("kind") in BOWLER_WICKET_KINDS)
    is_four = 1 if batter_runs == 4 and not non_boundary else 0
    is_six = 1 if batter_runs == 6 and not non_boundary else 0
    cur = conn.execute("""
        INSERT INTO deliveries (
            innings_id, over_number, delivery_index, batter_id, non_striker_id, bowler_id,
            batter_runs, extras_runs, total_runs, is_four, is_six, is_dot, is_wicket,
            wide_runs, noball_runs, bye_runs, legbye_runs, penalty_runs,
            is_legal_delivery, bowler_runs_conceded, bowler_wickets, counts_as_faced
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        innings_id, over_number, delivery_index, batter_id, non_striker_id, bowler_id,
        batter_runs, extras_runs, total_runs, is_four, is_six, is_dot, 1 if wickets else 0,
        wide_runs, noball_runs, bye_runs, legbye_runs, penalty_runs,
        is_legal_delivery, bowler_runs_conceded, bowler_wickets, counts_as_faced
    ))
    delivery_id = cur.lastrowid
    for extra_type, extra_runs in extras.items():
        conn.execute("""
            INSERT INTO delivery_extras(delivery_id, extra_type, runs) VALUES (?, ?, ?)
        """, (delivery_id, extra_type, int(extra_runs)))
    for wicket in wickets:
        player_out = wicket.get("player_out")
        player_out_id = get_or_create_player(conn, player_out, registry.get(player_out)) if player_out else None
        wcur = conn.execute("""
            INSERT INTO wickets (delivery_id, player_out_id, wicket_kind) VALUES (?, ?, ?)
        """, (delivery_id, player_out_id, wicket.get("kind")))
        wicket_id = wcur.lastrowid
        for fielder in wicket.get("fielders", []):
            fielder_name = fielder.get("name") if isinstance(fielder, dict) else fielder
            if not fielder_name:
                continue
            fielder_id = get_or_create_player(conn, fielder_name, registry.get(fielder_name))
            conn.execute("""
                INSERT INTO wicket_fielders(wicket_id, player_id) VALUES (?, ?)
            """, (wicket_id, fielder_id))


def import_match(conn, json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    info = data.get("info", {})
    source_match_id = json_path.stem
    teams = info.get("teams", [])
    if len(teams) < 2:
        raise ValueError(f"{json_path.name}: fewer than two teams")
    team1_id = get_or_create_team(conn, teams[0])
    team2_id = get_or_create_team(conn, teams[1])
    match_db_id, is_new = get_or_create_match(conn, source_match_id, info, team1_id, team2_id)
    team_ids = {teams[0]: team1_id, teams[1]: team2_id}
    if not is_new:
        # Existing matches still need metadata backfilled. In particular,
        # older DBs may be missing Player-of-the-Match rows.
        backfill_match_metadata(conn, json_path)
        return False
    registry = player_registry(info)
    insert_match_players(conn, match_db_id, info, team_ids)
    insert_player_of_match(conn, match_db_id, info)
    for innings_number, innings_data in enumerate(data.get("innings", []), start=1):
        batting_team_name = innings_data.get("team")
        batting_team_id = get_or_create_team(conn, batting_team_name)
        bowling_team_id = team2_id if batting_team_id == team1_id else team1_id
        is_super_over = 1 if innings_data.get("super_over") else 0
        cur = conn.execute("""
            INSERT INTO innings (match_id, innings_number, batting_team_id, bowling_team_id, is_super_over)
            VALUES (?, ?, ?, ?, ?)
        """, (match_db_id, innings_number, batting_team_id, bowling_team_id, is_super_over))
        innings_id = cur.lastrowid
        delivery_index = 0
        for over in innings_data.get("overs", []):
            over_number = over.get("over", 0)
            for delivery in over.get("deliveries", []):
                delivery_index += 1
                insert_delivery(conn, innings_id, over_number, delivery_index, delivery, registry)
    return True


def create_views(conn):
    conn.executescript("""
    DROP VIEW IF EXISTS v_innings_batting_raw;
    DROP VIEW IF EXISTS v_innings_batting;
    DROP VIEW IF EXISTS v_innings_bowling;
    DROP VIEW IF EXISTS v_fielding_events;
    DROP VIEW IF EXISTS v_matches_played;
    DROP VIEW IF EXISTS v_player_of_match_events;
    DROP VIEW IF EXISTS v_delivery_facts;
    -- One row per delivery with every dimension attached (deepest granularity).
    CREATE VIEW v_delivery_facts AS
    SELECT
        d.*, i.match_id, i.batting_team_id, i.bowling_team_id, i.is_super_over,
        m.season, m.year, m.venue, m.match_date, m.team1_id, m.team2_id
    FROM deliveries d
    JOIN innings i ON i.innings_id = d.innings_id
    JOIN matches m ON m.match_id = i.match_id;
    -- Per player, per innings batting line (includes players out for 0 who never faced,
    -- e.g. run out at the non-striker's end).
    CREATE VIEW v_innings_batting_raw AS
    WITH participants AS (
        SELECT innings_id, batter_id AS player_id FROM deliveries
        UNION
        SELECT innings_id, non_striker_id AS player_id FROM deliveries
    ),
    batting_agg AS (
        SELECT innings_id, batter_id AS player_id,
               SUM(batter_runs) AS runs, SUM(counts_as_faced) AS balls_faced,
               SUM(is_four) AS fours, SUM(is_six) AS sixes,
               SUM(CASE WHEN is_dot=1 AND counts_as_faced=1 THEN 1 ELSE 0 END) AS dots
        FROM deliveries GROUP BY innings_id, batter_id
    ),
    dismissals AS (
        SELECT del.innings_id, w.player_out_id AS player_id, w.wicket_kind
        FROM wickets w JOIN deliveries del ON del.delivery_id = w.delivery_id
        WHERE w.player_out_id IS NOT NULL
    )
    SELECT p.innings_id, p.player_id,
           COALESCE(b.runs, 0) AS runs, COALESCE(b.balls_faced, 0) AS balls_faced,
           COALESCE(b.fours, 0) AS fours, COALESCE(b.sixes, 0) AS sixes,
           COALESCE(b.dots, 0) AS dots,
           CASE WHEN dis.player_id IS NOT NULL THEN 1 ELSE 0 END AS is_out,
           dis.wicket_kind
    FROM participants p
    LEFT JOIN batting_agg b ON b.innings_id = p.innings_id AND b.player_id = p.player_id
    LEFT JOIN dismissals dis ON dis.innings_id = p.innings_id AND dis.player_id = p.player_id;
    CREATE VIEW v_innings_batting AS
    SELECT ib.*, i.match_id, i.batting_team_id AS team_id, i.bowling_team_id AS opposition_team_id,
           i.is_super_over, m.season, m.year, m.venue, m.match_date
    FROM v_innings_batting_raw ib
    JOIN innings i ON i.innings_id = ib.innings_id
    JOIN matches m ON m.match_id = i.match_id;
    -- Per player, per innings bowling line.
    CREATE VIEW v_innings_bowling AS
    SELECT d.innings_id, d.bowler_id AS player_id,
           SUM(d.is_legal_delivery) AS balls_bowled,
           SUM(d.bowler_runs_conceded) AS runs_conceded,
           SUM(d.bowler_wickets) AS wickets,
           SUM(CASE WHEN d.is_dot=1 AND d.is_legal_delivery=1 THEN 1 ELSE 0 END) AS dot_balls,
           i.match_id, i.bowling_team_id AS team_id, i.batting_team_id AS opposition_team_id,
           i.is_super_over, m.season, m.year, m.venue, m.match_date
    FROM deliveries d
    JOIN innings i ON i.innings_id = d.innings_id
    JOIN matches m ON m.match_id = i.match_id
    GROUP BY d.innings_id, d.bowler_id;
    -- Catches and stumpings, one row per fielding credit.
    CREATE VIEW v_fielding_events AS
    SELECT wf.player_id, w.wicket_kind,
           CASE WHEN w.wicket_kind IN ('caught','caught and bowled') THEN 1 ELSE 0 END AS is_catch,
           CASE WHEN w.wicket_kind = 'stumped' THEN 1 ELSE 0 END AS is_stumping,
           del.innings_id, i.match_id, i.bowling_team_id AS team_id, i.batting_team_id AS opposition_team_id,
           i.is_super_over, m.season, m.year, m.venue, m.match_date
    FROM wicket_fielders wf
    JOIN wickets w ON w.wicket_id = wf.wicket_id
    JOIN deliveries del ON del.delivery_id = w.delivery_id
    JOIN innings i ON i.innings_id = del.innings_id
    JOIN matches m ON m.match_id = i.match_id;
    -- Match participation, with per-player opposition/team/venue/year dims.
    CREATE VIEW v_matches_played AS
    SELECT mp.match_id, mp.player_id, mp.team_id,
           CASE WHEN mp.team_id = m.team1_id THEN m.team2_id ELSE m.team1_id END AS opposition_team_id,
           m.season, m.year, m.venue, m.match_date
    FROM match_players mp
    JOIN matches m ON m.match_id = mp.match_id;
    -- Player of the match, with matching dims.
    CREATE VIEW v_player_of_match_events AS
    SELECT pom.match_id, pom.player_id, mp.team_id,
           CASE WHEN mp.team_id = m.team1_id THEN m.team2_id ELSE m.team1_id END AS opposition_team_id,
           m.season, m.year, m.venue, m.match_date
    FROM match_player_of_match pom
    JOIN match_players mp ON mp.match_id = pom.match_id AND mp.player_id = pom.player_id
    JOIN matches m ON m.match_id = pom.match_id;
    """)


def _build_filter(filters):
    """filters keys: year, venue, team, opposition (all optional, all exact-match)."""
    filters = filters or {}
    clauses, params = [], []
    if filters.get("year"):
        clauses.append("year = ?")
        params.append(str(filters["year"]))
    if filters.get("venue"):
        clauses.append("venue = ?")
        params.append(filters["venue"])
    if filters.get("team"):
        clauses.append("team_id = (SELECT team_id FROM teams WHERE team_name = ?)")
        params.append(filters["team"])
    if filters.get("opposition"):
        clauses.append("opposition_team_id = (SELECT team_id FROM teams WHERE team_name = ?)")
        params.append(filters["opposition"])
    where = (" AND " + " AND ".join(clauses)) if clauses else ""
    return where, params


def resolve_player_id(conn, player_name):
    row = conn.execute("SELECT player_id FROM players WHERE player_name = ?", (player_name,)).fetchone()
    return row[0] if row else None


def get_player_stats(conn, player_name, filters=None):
    """
    Returns the full stat sheet for a player, optionally filtered by any
    combination of: year, venue, team (playing for), opposition.
    Nothing here is pre-stored -- every number is computed on demand from
    the filterable views above.
    """
    pid = resolve_player_id(conn, player_name)
    if pid is None:
        return None
    where, params = _build_filter(filters)
    args = [pid] + params
    matches = conn.execute(
        f"SELECT COUNT(DISTINCT match_id) FROM v_matches_played WHERE player_id = ?{where}", args
    ).fetchone()[0]
    bat = conn.execute(f"""
        SELECT runs, balls_faced, fours, sixes, dots, is_out
        FROM v_innings_batting WHERE player_id = ?{where} AND is_super_over = 0
    """, args).fetchall()
    innings = len(bat)
    not_outs = sum(1 for r in bat if r[5] == 0)
    runs = sum(r[0] for r in bat)
    balls_faced = sum(r[1] for r in bat)
    fours = sum(r[2] for r in bat)
    sixes = sum(r[3] for r in bat)
    dots = sum(r[4] for r in bat)
    highest_score, highest_not_out = None, False
    if bat:
        highest_score = max(r[0] for r in bat)
        highest_not_out = any(r[0] == highest_score and r[5] == 0 for r in bat)
    avg_denom = innings - not_outs
    average = round(runs / avg_denom, 2) if avg_denom > 0 else None
    strike_rate = round(100.0 * runs / balls_faced, 2) if balls_faced else None
    dot_pct = round(100.0 * dots / balls_faced, 2) if balls_faced else None
    thirties = sum(1 for r in bat if 30 <= r[0] < 50)
    fifties = sum(1 for r in bat if 50 <= r[0] < 70)
    seventies = sum(1 for r in bat if 70 <= r[0] < 100)
    hundreds = sum(1 for r in bat if r[0] >= 100)
    bowl = conn.execute(f"""
        SELECT balls_bowled, runs_conceded, wickets, dot_balls
        FROM v_innings_bowling WHERE player_id = ?{where} AND is_super_over = 0
    """, args).fetchall()
    balls_bowled = sum(r[0] for r in bowl)
    runs_conceded = sum(r[1] for r in bowl)
    wickets = sum(r[2] for r in bowl)
    bowl_dots = sum(r[3] for r in bowl)
    bowling_average = round(runs_conceded / wickets, 2) if wickets else None
    bowling_sr = round(balls_bowled / wickets, 2) if wickets else None
    economy = round(6.0 * runs_conceded / balls_bowled, 2) if balls_bowled else None
    bowl_dot_pct = round(100.0 * bowl_dots / balls_bowled, 2) if balls_bowled else None
    three_w = sum(1 for r in bowl if r[2] == 3)
    four_w = sum(1 for r in bowl if r[2] == 4)
    five_w = sum(1 for r in bowl if r[2] >= 5)
    best = conn.execute(f"""
        SELECT wickets, runs_conceded FROM v_innings_bowling
        WHERE player_id = ?{where} AND is_super_over = 0
        ORDER BY wickets DESC, runs_conceded ASC LIMIT 1
    """, args).fetchone()
    best_bowling = f"{best[0]}/{best[1]}" if best else None
    field = conn.execute(f"""
        SELECT COALESCE(SUM(is_catch),0), COALESCE(SUM(is_stumping),0)
        FROM v_fielding_events WHERE player_id = ?{where}
    """, args).fetchone()
    catches, stumpings = field
    mom = conn.execute(
        f"SELECT COUNT(*) FROM v_player_of_match_events WHERE player_id = ?{where}", args
    ).fetchone()[0]
    return {
        "player": player_name,
        "matches": matches,
        "innings_batted": innings,
        "not_outs": not_outs,
        "runs": runs,
        "balls_faced": balls_faced,
        "highest_score": (f"{highest_score}*" if highest_not_out else highest_score),
        "average": average,
        "strike_rate": strike_rate,
        "30s": thirties, "50s": fifties, "70s": seventies, "100s": hundreds,
        "fours": fours, "sixes": sixes,
        "dot_ball_pct": dot_pct,
        "player_of_match_awards": mom,
        "balls_bowled": balls_bowled,
        "wickets": wickets,
        "bowling_average": bowling_average,
        "bowling_strike_rate": bowling_sr,
        "economy": economy,
        "bowling_dot_ball_pct": bowl_dot_pct,
        "3w_hauls": three_w, "4w_hauls": four_w, "5w_hauls": five_w,
        "best_bowling": best_bowling,
        "catches": catches,
        "stumpings": stumpings,
    }


def main():
    json_folder = JSON_PATH
    db_path = DB_PATH
    if not json_folder.exists():
        raise SystemExit(f"JSON folder not found: {json_folder}")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_is_new = not db_path.exists()
    if not db_is_new and BACKUP_BEFORE_UPDATE:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = db_path.with_name(f"{db_path.stem}_backup_{stamp}{db_path.suffix}")
        shutil.copy2(db_path, backup_path)
        print(f"Backup created: {backup_path}")
    json_files = sorted(json_folder.glob("*.json"))
    if not json_files:
        raise SystemExit("No JSON files found.")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            if db_is_new:
                print(f"Creating database at:\n{db_path}")
                create_schema(conn)
            else:
                print(f"Updating existing database at:\n{db_path}")
            add_derived_columns(conn)
            imported = skipped = failed = 0
            for path in json_files:
                try:
                    if import_match(conn, path):
                        imported += 1
                        print(f"IMPORTED: {path.name}")
                    else:
                        skipped += 1
                except Exception as e:
                    failed += 1
                    print(f"FAILED: {path.name} -> {e}")
            create_views(conn)
            # Recreate the views after all imports/backfills and report the
            # fielding/award event totals that will feed the dashboard.
            pom_count = conn.execute(
                "SELECT COUNT(*) FROM match_player_of_match"
            ).fetchone()[0]
            fielding_count = conn.execute(
                "SELECT COUNT(*) FROM wicket_fielders"
            ).fetchone()[0]
            catch_count = conn.execute("""
                SELECT COUNT(*)
                FROM wickets
                WHERE wicket_kind IN ('caught', 'caught and bowled')
            """).fetchone()[0]
            stumping_count = conn.execute("""
                SELECT COUNT(*)
                FROM wickets
                WHERE wicket_kind = 'stumped'
            """).fetchone()[0]
        print()
        print("=" * 60)
        print("UPDATE COMPLETE")
        print("=" * 60)
        print(f"New matches imported : {imported}")
        print(f"Already present      : {skipped}")
        print(f"Failed               : {failed}")
        print(f"Player-of-match rows : {pom_count}")
        print(f"Fielding credits     : {fielding_count}")
        print(f"Catch dismissals     : {catch_count}")
        print(f"Stumping dismissals  : {stumping_count}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
