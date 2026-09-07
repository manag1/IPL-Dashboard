import json
import logging
import os
import sqlite3
import traceback
import re
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, render_template
from google import genai
from google.genai import types

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get(
    "CRICKET_DB_PATH",
    str(BASE_DIR.parent / "database" / "ipl.db"),
)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AQ.Ab8RN6Lo28KmP59Q1TpK5xq6qheJx5jB3N5qUjAYH4GHsycofA")
GEMINI_MODEL = "gemini-3.5-flash-lite"

app = Flask(__name__, static_folder="static", static_url_path="/static")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = app.logger

# Franchise identity is deliberately separated from the name stored in the source data.
# Historical names are treated as the same franchise wherever appropriate.
FRANCHISE_DISPLAY = {
    "Chennai Super Kings": "Chennai Super Kings",
    "Mumbai Indians": "Mumbai Indians",
    "Kolkata Knight Riders": "Kolkata Knight Riders",
    "Royal Challengers Bangalore": "Royal Challengers Bengaluru",
    "Royal Challengers Bengaluru": "Royal Challengers Bengaluru",
    "Sunrisers Hyderabad": "Sunrisers Hyderabad",
    "Kings XI Punjab": "Punjab Kings",
    "Punjab Kings": "Punjab Kings",
    "Delhi Daredevils": "Delhi Capitals",
    "Delhi Capitals": "Delhi Capitals",
    "Deccan Chargers": "Deccan Chargers",
    "Gujarat Titans": "Gujarat Titans",
    "Lucknow Super Giants": "Lucknow Super Giants",
    "Rajasthan Royals": "Rajasthan Royals",
    "Gujarat Lions": "Gujarat Lions",
    "Rising Pune Supergiant": "Rising Pune Supergiant",
    "Rising Pune Supergiants": "Rising Pune Supergiant",
    "Kochi Tuskers Kerala": "Kochi Tuskers Kerala",
    "Pune Warriors": "Pune Warriors India",
    "Pune Warriors India": "Pune Warriors India",
}

IPL_FRANCHISES = [
    "Chennai Super Kings",
    "Mumbai Indians",
    "Kolkata Knight Riders",
    "Royal Challengers Bengaluru",
    "Sunrisers Hyderabad",
    "Punjab Kings",
    "Delhi Capitals",
    "Deccan Chargers",
    "Gujarat Titans",
    "Lucknow Super Giants",
    "Rajasthan Royals",
    "Gujarat Lions",
    "Rising Pune Supergiant",
    "Kochi Tuskers Kerala",
    "Pune Warriors India",
]


def canonical_team(name):
    return FRANCHISE_DISPLAY.get(name, name)


def canonical_team_sql(alias):
    """CASE expression mapping source team names to franchise identity."""
    cases = []
    for source, display in FRANCHISE_DISPLAY.items():
        cases.append(f"WHEN {alias}.team_name={json.dumps(source)} THEN {json.dumps(display)}")
    return "CASE " + " ".join(cases) + f" ELSE {alias}.team_name END"


# Venue identity is also canonicalized so source naming variants such as
# "Wankhede Stadium" and "Wankhede Stadium, Mumbai" are treated as one stadium.
VENUE_DISPLAY = {
    "Arun Jaitley Stadium": "Arun Jaitley Stadium, Delhi",
    "Brabourne Stadium": "Brabourne Stadium, Mumbai",
    "Dr DY Patil Sports Academy": "Dr DY Patil Sports Academy, Mumbai",
    "Dr. Y.S. Rajasekhara Reddy ACA-VDCA Cricket Stadium": "Dr. Y.S. Rajasekhara Reddy ACA-VDCA Cricket Stadium, Visakhapatnam",
    "Eden Gardens": "Eden Gardens, Kolkata",
    "Himachal Pradesh Cricket Association Stadium": "Himachal Pradesh Cricket Association Stadium, Dharamsala",
    "M Chinnaswamy Stadium": "M Chinnaswamy Stadium, Bengaluru",
    "M.Chinnaswamy Stadium": "M Chinnaswamy Stadium, Bengaluru",
    "MA Chidambaram Stadium": "MA Chidambaram Stadium, Chepauk, Chennai",
    "MA Chidambaram Stadium, Chepauk": "MA Chidambaram Stadium, Chepauk, Chennai",
    "Maharaja Yadavindra Singh International Cricket Stadium, Mullanpur": "Maharaja Yadavindra Singh International Cricket Stadium, New Chandigarh",
    "Maharashtra Cricket Association Stadium": "Maharashtra Cricket Association Stadium, Pune",
    "Punjab Cricket Association IS Bindra Stadium": "Punjab Cricket Association IS Bindra Stadium, Mohali, Chandigarh",
    "Punjab Cricket Association IS Bindra Stadium, Mohali": "Punjab Cricket Association IS Bindra Stadium, Mohali, Chandigarh",
    "Punjab Cricket Association Stadium, Mohali": "Punjab Cricket Association IS Bindra Stadium, Mohali, Chandigarh",
    "Rajiv Gandhi International Stadium": "Rajiv Gandhi International Stadium, Uppal, Hyderabad",
    "Rajiv Gandhi International Stadium, Uppal": "Rajiv Gandhi International Stadium, Uppal, Hyderabad",
    "Sawai Mansingh Stadium": "Sawai Mansingh Stadium, Jaipur",
    "Shaheed Veer Narayan Singh International Stadium": "Shaheed Veer Narayan Singh International Stadium, Raipur",
    "Wankhede Stadium": "Wankhede Stadium, Mumbai",
}

def canonical_venue(name):
    return VENUE_DISPLAY.get(name, name)


gemini_client = None
if genai and GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        log.info("Gemini client configured with model %s", GEMINI_MODEL)
    except Exception:
        log.exception("Unable to initialise Gemini client")
else:
    if not GEMINI_API_KEY:
        log.warning("GEMINI_API_KEY is not configured. AI analysis will be unavailable.")
    elif not genai:
        log.warning("google-genai is not installed. AI analysis will be unavailable.")


if not Path(DB_PATH).exists():
    log.warning("CRICKET_DB_PATH does not exist: %s", DB_PATH)


def _ensure_match_result_schema(c):
    """Self-heal older databases that predate match-result columns."""
    existing = {r[1] for r in c.execute("PRAGMA table_info(matches)")}
    columns = {
        "winner_team_id": "INTEGER",
        "result_type": "TEXT",
        "result_margin": "INTEGER",
        "result_method": "TEXT",
        "result_margin_type": "TEXT",
    }
    changed = False
    for col, definition in columns.items():
        if col not in existing:
            c.execute(f"ALTER TABLE matches ADD COLUMN {col} {definition}")
            changed = True

    # Populate result fields from the original Cricsheet JSON only when the
    # database is missing them. This makes an older local DB compatible with
    # the current dashboard without requiring a manual SQL migration.
    needs_data = c.execute(
        "SELECT 1 FROM matches WHERE result_type IS NULL LIMIT 1"
    ).fetchone() is not None
    json_folder = BASE_DIR.parent / "ipl_json"
    if needs_data and json_folder.exists():
        for path in json_folder.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    info = json.load(f).get("info", {})
                outcome = info.get("outcome") or {}
                winner_name = outcome.get("winner")
                winner_id = None
                if winner_name:
                    row = c.execute(
                        "SELECT team_id FROM teams WHERE team_name=?", (winner_name,)
                    ).fetchone()
                    if row:
                        winner_id = row[0]
                result = outcome.get("result")
                if result == "tie" and outcome.get("eliminator"):
                    row = c.execute(
                        "SELECT team_id FROM teams WHERE team_name=?",
                        (outcome.get("eliminator"),),
                    ).fetchone()
                    if row:
                        winner_id = row[0]
                    result_type = "super_over"
                elif winner_id is not None:
                    result_type = "win"
                elif result == "tie":
                    result_type = "tie"
                elif result in ("no result", "abandoned"):
                    result_type = "no_result"
                else:
                    result_type = None
                by = outcome.get("by") or {}
                if "runs" in by:
                    margin, margin_type = by.get("runs"), "runs"
                elif "wickets" in by:
                    margin, margin_type = by.get("wickets"), "wickets"
                else:
                    margin, margin_type = None, None
                c.execute("""
                    UPDATE matches
                    SET winner_team_id=?, result_type=?, result_margin=?,
                        result_method=?, result_margin_type=?
                    WHERE source_match_id=?
                """, (winner_id, result_type, margin, outcome.get("method"),
                      margin_type, path.stem))
            except Exception:
                log.exception("Unable to migrate match result from %s", path.name)
        changed = True
    if changed:
        c.commit()


def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    _ensure_match_result_schema(c)
    return c


def rows(rs):
    return [dict(r) for r in rs]


def _selected_values(param_name, all_label):
    values = [v.strip() for v in request.args.getlist(param_name) if v and v.strip()]
    if not values or all_label in values:
        return []
    # Preserve order while removing duplicates.
    return list(dict.fromkeys(values))


def filters_from_request():
    return (
        _selected_values("year", "All Years"),
        _selected_values("opponent", "All Teams"),
        _selected_values("venue", "All Venues"),
    )


def canonical_venue_sql(alias):
    cases = []
    for source, display in VENUE_DISPLAY.items():
        cases.append(f"WHEN {alias}.venue={json.dumps(source)} THEN {json.dumps(display)}")
    return "CASE " + " ".join(cases) + f" ELSE {alias}.venue END"


def _in_clause(values):
    return ",".join("?" for _ in values)


def player_batting_filter_sql(alias="ib"):
    years, opponents, venues = filters_from_request()
    clauses = [f"{alias}.is_super_over=0"]
    params = []
    if years:
        clauses.append(f"{alias}.year IN ({_in_clause(years)})")
        params.extend(years)
    if opponents:
        clauses.append(
            f"EXISTS (SELECT 1 FROM teams otf WHERE otf.team_id={alias}.opposition_team_id "
            f"AND {canonical_team_sql('otf')} IN ({_in_clause(opponents)}))"
        )
        params.extend(opponents)
    if venues:
        clauses.append(f"{canonical_venue_sql(alias)} IN ({_in_clause(venues)})")
        params.extend(venues)
    return " AND ".join(clauses), params


def get_player(c, player_id):
    return c.execute(
        "SELECT player_id,player_name,registry_id FROM players WHERE player_id=?",
        (player_id,),
    ).fetchone()


def get_phase_summary(c, player_id):
    years, opponents, venues = filters_from_request()
    clauses = ["d.batter_id=?", "i.is_super_over=0"]
    params = [player_id]

    if years:
        clauses.append(f"m.year IN ({_in_clause(years)})")
        params.extend(years)
    if opponents:
        clauses.append(
            "EXISTS (SELECT 1 FROM teams ot WHERE ot.team_id=i.bowling_team_id "
            f"AND {canonical_team_sql('ot')} IN ({_in_clause(opponents)}))"
        )
        params.extend(opponents)
    if venues:
        clauses.append(f"{canonical_venue_sql('m')} IN ({_in_clause(venues)})")
        params.extend(venues)

    rs = c.execute(
        f"""
        SELECT CASE
                   WHEN d.over_number < 6 THEN 'Powerplay (1-6)'
                   WHEN d.over_number < 15 THEN 'Middle (7-15)'
                   ELSE 'Death (16-20)'
               END phase,
               SUM(d.counts_as_faced) balls,
               SUM(d.batter_runs) runs,
               SUM(d.is_four) fours,
               SUM(d.is_six) sixes,
               SUM(CASE WHEN d.is_dot=1 AND d.is_legal_delivery=1 THEN 1 ELSE 0 END) dots,
               COUNT(DISTINCT CASE
                   WHEN w.player_out_id=? AND LOWER(COALESCE(w.wicket_kind,''))<>'retired hurt'
                   THEN w.wicket_id END) dismissals
        FROM deliveries d
        JOIN innings i ON i.innings_id=d.innings_id
        JOIN matches m ON m.match_id=i.match_id
        LEFT JOIN wickets w ON w.delivery_id=d.delivery_id
        WHERE {' AND '.join(clauses)}
        GROUP BY phase
        ORDER BY CASE phase
                     WHEN 'Powerplay (1-6)' THEN 1
                     WHEN 'Middle (7-15)' THEN 2
                     ELSE 3
                 END
        """,
        [player_id, *params],
    ).fetchall()

    out = []
    for r in rows(rs):
        r["strike_rate"] = round(100 * r["runs"] / r["balls"], 2) if r["balls"] else None
        r["average"] = round(r["runs"] / r["dismissals"], 2) if r["dismissals"] else None
        r["dot_ball_percentage"] = round(100 * r["dots"] / r["balls"], 2) if r["balls"] else None
        out.append(r)
    return out



def _table_columns(c, table):
    try:
        return {r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
    except sqlite3.Error:
        return set()


def _extract_names(value):
    """Extract player-name-like strings from common fielder/MoM storage formats."""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if parsed != text:
                return _extract_names(parsed)
        except Exception:
            pass
        return [text]
    if isinstance(value, dict):
        out = []
        for key in ("name", "player", "player_name", "fielder", "fielder_name"):
            if key in value:
                out.extend(_extract_names(value[key]))
        for key in ("fielders", "players", "players_of_match"):
            if key in value:
                out.extend(_extract_names(value[key]))
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            out.extend(_extract_names(item))
        return out
    return []


def _name_matches(names, player_name):
    target = str(player_name or "").strip().casefold()
    if not target:
        return False
    return any(str(n).strip().casefold() == target for n in names)


def _award_and_fielding_stats(c, player_id, player_name, match_ids):
    """Return MoM, catches and stumpings from the normalized database.

    Fielding credits are valid only for legal, non-Super-Over deliveries.
    The event rows remain in the database for auditability, but only qualifying
    events contribute to player statistics.
    """
    match_ids = {int(x) for x in match_ids if x is not None}
    if not match_ids:
        return {"mom": 0, "catches": 0, "stumpings": 0}

    placeholders = ",".join("?" * len(match_ids))
    ids = list(match_ids)

    # MoM is normalized in match_player_of_match.
    mom = int(c.execute(
        f"""
        SELECT COUNT(*)
        FROM match_player_of_match
        WHERE player_id=? AND match_id IN ({placeholders})
        """,
        [player_id, *ids],
    ).fetchone()[0] or 0)

    # Fielding credits are normalized in wicket_fielders.  Exclude:
    #   - Super Over innings
    #   - illegal deliveries (wides/no-balls)
    # and count only actual catch/stumping credits.
    field = c.execute(
        f"""
        SELECT
            COALESCE(SUM(
                CASE WHEN LOWER(COALESCE(w.wicket_kind,'')) IN
                     ('caught','caught and bowled') THEN 1 ELSE 0 END
            ),0) AS catches,
            COALESCE(SUM(
                CASE WHEN LOWER(COALESCE(w.wicket_kind,''))='stumped'
                     THEN 1 ELSE 0 END
            ),0) AS stumpings
        FROM wicket_fielders wf
        JOIN wickets w ON w.wicket_id=wf.wicket_id
        JOIN deliveries d ON d.delivery_id=w.delivery_id
        JOIN innings i ON i.innings_id=d.innings_id
        WHERE wf.player_id=?
          AND i.match_id IN ({placeholders})
          AND i.is_super_over=0
          AND d.is_legal_delivery=1
        """,
        [player_id, *ids],
    ).fetchone()

    catches = int(field["catches"] or 0)
    stumpings = int(field["stumpings"] or 0)

    return {
        "mom": mom,
        "catches": catches,
        "stumpings": stumpings,
    }

def get_overview_data(c, player_id):
    years, opponents, venues = filters_from_request()
    where, params = player_batting_filter_sql("ib")

    match_clauses = ["mp.player_id=?"]
    match_params = [player_id]
    if years:
        match_clauses.append(f"m.year IN ({_in_clause(years)})")
        match_params.extend(years)
    if venues:
        match_clauses.append(f"{canonical_venue_sql('m')} IN ({_in_clause(venues)})")
        match_params.extend(venues)
    if opponents:
        match_clauses.append(
            "EXISTS (SELECT 1 FROM teams ot "
            "WHERE ot.team_id=CASE WHEN mp.team_id=m.team1_id THEN m.team2_id ELSE m.team1_id END "
            f"AND {canonical_team_sql('ot')} IN ({_in_clause(opponents)}))"
        )
        match_params.extend(opponents)

    match_count = c.execute(
        f"""
        SELECT COUNT(DISTINCT mp.match_id)
        FROM match_players mp
        JOIN matches m ON m.match_id=mp.match_id
        JOIN teams pt ON pt.team_id=mp.team_id
        WHERE {' AND '.join(match_clauses)}
        """,
        match_params,
    ).fetchone()[0]

    innings = rows(c.execute(
        f"""
        SELECT ib.*, m.match_date, m.venue,
               m.winner_team_id, m.result_type, m.result_margin,
               m.result_margin_type, m.result_method,
               bt.team_name batting_team_raw,
               ot.team_name opposition_raw,
               CASE WHEN ib.is_out=0 THEN CAST(ib.runs AS TEXT)||'*'
                    ELSE CAST(ib.runs AS TEXT) END score,
               ROUND(100.0*ib.runs/NULLIF(ib.balls_faced,0),2) strike_rate,
               CASE WHEN EXISTS (
                   SELECT 1 FROM match_player_of_match pom
                   WHERE pom.player_id=ib.player_id AND pom.match_id=ib.match_id
               ) THEN 1 ELSE 0 END is_mom
        FROM v_innings_batting ib
        JOIN matches m ON m.match_id=ib.match_id
        LEFT JOIN teams bt ON bt.team_id=ib.team_id
        LEFT JOIN teams ot ON ot.team_id=ib.opposition_team_id
        WHERE ib.player_id=? AND {where}
        ORDER BY date(m.match_date) DESC, m.match_id DESC, ib.innings_id DESC
        """,
        (player_id, *params),
    ).fetchall())

    for x in innings:
        x["batting_team"] = canonical_team(x.pop("batting_team_raw", None))
        x["opposition"] = canonical_team(x.pop("opposition_raw", None))
        x["year"] = x.get("year") or (str(x["match_date"])[:4] if x.get("match_date") else None)
        x["match_date"] = x.get("match_date") or "—"

        result_type = x.get("result_type")
        if result_type == "no_result":
            x["result"] = "No Result"
        elif result_type == "tie":
            x["result"] = "Tied"
        elif result_type == "super_over":
            x["result"] = "Won (Super Over)" if x.get("team_id") == x.get("winner_team_id") else "Lost (Super Over)"
        elif result_type == "win":
            won = x.get("team_id") == x.get("winner_team_id")
            verb = "Won" if won else "Lost"
            margin = x.get("result_margin")
            margin_type = x.get("result_margin_type")
            method = f" ({x['result_method']})" if x.get("result_method") else ""
            x["result"] = f"{verb} by {margin} {margin_type}{method}" if margin else verb
        else:
            x["result"] = "—"

    runs = sum(x["runs"] or 0 for x in innings)
    balls = sum(x["balls_faced"] or 0 for x in innings)
    not_outs = sum(1 for x in innings if x["is_out"] == 0)
    outs = len(innings) - not_outs
    highest = max((x["runs"] or 0 for x in innings), default=0)
    highest_not_out = any((x["runs"] or 0) == highest and x["is_out"] == 0 for x in innings)

    stats = {
        "matches": match_count,
        "innings": len(innings),
        "not_outs": not_outs,
        "highest": f"{highest}{'*' if highest_not_out else ''}",
        "runs": runs,
        "average": round(runs / outs, 2) if outs else None,
        "balls": balls,
        "strike_rate": round(100 * runs / balls, 2) if balls else None,
        "30s": sum(30 <= (x["runs"] or 0) < 50 for x in innings),
        "50s": sum(50 <= (x["runs"] or 0) < 100 for x in innings),
        "100s": sum((x["runs"] or 0) >= 100 for x in innings),
        "fours": sum(x["fours"] or 0 for x in innings),
        "sixes": sum(x["sixes"] or 0 for x in innings),
    }

    selected_match_rows = c.execute(
        f"""
        SELECT DISTINCT mp.match_id
        FROM match_players mp
        JOIN matches m ON m.match_id=mp.match_id
        WHERE {' AND '.join(match_clauses)}
        """,
        match_params,
    ).fetchall()

    fielding = _award_and_fielding_stats(
        c,
        player_id,
        get_player(c, player_id)["player_name"],
        [r["match_id"] for r in selected_match_rows],
    )
    stats["mom"] = fielding["mom"]
    stats["catches"] = fielding["catches"]
    stats["stumpings"] = fielding["stumpings"]

    year_rows = rows(c.execute(
        f"""
        SELECT ib.year,
               SUM(ib.runs) runs,
               SUM(ib.balls_faced) balls,
               ROUND(100.0*SUM(ib.runs)/NULLIF(SUM(ib.balls_faced),0),2) strike_rate,
               COUNT(*) innings,
               SUM(CASE WHEN ib.is_out=1 THEN 1 ELSE 0 END) outs,
               SUM(ib.fours) fours,
               SUM(ib.sixes) sixes,
               SUM(CASE WHEN ib.runs >= 50 AND ib.runs < 100 THEN 1 ELSE 0 END) "50s",
               SUM(CASE WHEN ib.runs >= 100 THEN 1 ELSE 0 END) "100s"
        FROM v_innings_batting ib
        WHERE ib.player_id=? AND {where}
        GROUP BY ib.year
        ORDER BY CAST(ib.year AS INTEGER)
        """,
        (player_id, *params),
    ).fetchall())
    for x in year_rows:
        # Batting average is runs divided by dismissals, not innings.
        x["average"] = round(x["runs"] / x["outs"], 2) if x["outs"] else None

    distribution = rows(c.execute(
        f"""
        SELECT CASE
                 WHEN ib.runs BETWEEN 0 AND 25 THEN '0 - 25'
                 WHEN ib.runs BETWEEN 26 AND 50 THEN '26 - 50'
                 WHEN ib.runs BETWEEN 51 AND 75 THEN '51 - 75'
                 WHEN ib.runs BETWEEN 76 AND 100 THEN '76 - 100'
                 ELSE '100+'
               END bucket,
               SUM(ib.runs) runs
        FROM v_innings_batting ib
        WHERE ib.player_id=? AND {where}
        GROUP BY bucket
        ORDER BY CASE bucket
                   WHEN '0 - 25' THEN 1 WHEN '26 - 50' THEN 2 WHEN '51 - 75' THEN 3
                   WHEN '76 - 100' THEN 4 ELSE 5 END
        """,
        (player_id, *params),
    ).fetchall())

    raw_opps = rows(c.execute(
        f"""
        SELECT {canonical_team_sql('ot')} opposition,
               COUNT(*) innings,
               SUM(ib.runs) runs,
               SUM(ib.balls_faced) balls,
               SUM(CASE WHEN ib.is_out=0 THEN 1 ELSE 0 END) not_outs,
               SUM(CASE WHEN ib.runs >= 50 AND ib.runs < 100 THEN 1 ELSE 0 END) "50s",
               SUM(CASE WHEN ib.runs >= 100 THEN 1 ELSE 0 END) "100s",
               SUM(ib.fours) fours,
               SUM(ib.sixes) sixes
        FROM v_innings_batting ib
        JOIN teams ot ON ot.team_id=ib.opposition_team_id
        WHERE ib.player_id=? AND {where}
        GROUP BY {canonical_team_sql('ot')}
        ORDER BY runs DESC
        """,
        (player_id, *params),
    ).fetchall())
    oppositions = []
    for x in raw_opps:
        dismissals = x["innings"] - x["not_outs"]
        x["average"] = round(x["runs"] / dismissals, 2) if dismissals else None
        x["strike_rate"] = round(100 * x["runs"] / x["balls"], 2) if x["balls"] else None
        oppositions.append(x)

    teams = build_player_team_history(c, player_id)

    # Build matchup statistics from the exact same filtered batting innings used
    # everywhere else on the Overview page. Keeping the filtered innings in a
    # CTE prevents matchup data from falling back to the player's full career.
    matchup_where, matchup_params = player_batting_filter_sql("fib")
    matchups = rows(c.execute(
        f"""
        WITH filtered_innings AS (
            SELECT fib.innings_id
            FROM v_innings_batting fib
            WHERE fib.player_id=? AND {matchup_where}
        )
        SELECT p.player_name bowler,
               SUM(d.counts_as_faced) balls,
               SUM(d.batter_runs) runs,
               SUM(d.is_four) fours,
               SUM(d.is_six) sixes,
               SUM(CASE WHEN d.is_dot=1 AND d.counts_as_faced=1 THEN 1 ELSE 0 END) dots,
               COUNT(DISTINCT CASE
                   WHEN w.player_out_id=? AND LOWER(COALESCE(w.wicket_kind,''))<>'retired hurt'
                   THEN w.wicket_id END) dismissals
        FROM filtered_innings fi
        JOIN deliveries d ON d.innings_id=fi.innings_id
        JOIN players p ON p.player_id=d.bowler_id
        LEFT JOIN wickets w ON w.delivery_id=d.delivery_id
        WHERE d.batter_id=?
        GROUP BY d.bowler_id,p.player_name
        ORDER BY runs DESC, dismissals DESC
        """,
        [player_id, *matchup_params, player_id, player_id],
    ).fetchall())
    for x in matchups:
        x["strike_rate"] = round(100 * x["runs"] / x["balls"], 2) if x["balls"] else None
        x["average"] = round(x["runs"] / x["dismissals"], 2) if x["dismissals"] else None
        x["dot_percentage"] = round(100 * x["dots"] / x["balls"], 2) if x["balls"] else None

    # Dismissal breakdown must reconcile exactly with the batting innings used
    # for the selected filters. Count one dismissal per batting innings, not
    # raw wicket rows, so every filter combination agrees with stats.outs.
    dismissals = rows(c.execute(
        f"""
        WITH selected_innings AS (
            SELECT ib.innings_id, ib.is_out, ib.wicket_kind
            FROM v_innings_batting ib
            WHERE ib.player_id=? AND {where}
        ), dismissal_events AS (
            SELECT DISTINCT innings_id,
                   CASE
                     WHEN LOWER(COALESCE(wicket_kind,'')) IN ('caught','caught and bowled') THEN 'Caught'
                     WHEN LOWER(COALESCE(wicket_kind,''))='bowled' THEN 'Bowled'
                     WHEN LOWER(COALESCE(wicket_kind,''))='lbw' THEN 'LBW'
                     WHEN LOWER(COALESCE(wicket_kind,''))='run out' THEN 'Run Out'
                     WHEN LOWER(COALESCE(wicket_kind,''))='stumped' THEN 'Stumped'
                     ELSE 'Other'
                   END AS kind
            FROM selected_innings
            WHERE is_out=1
              AND LOWER(COALESCE(wicket_kind,'')) <> 'retired hurt'
        )
        SELECT kind, COUNT(*) n
        FROM dismissal_events
        GROUP BY kind
        ORDER BY n DESC, kind
        """,
        (player_id, *params),
    ).fetchall())


    phase_summary = get_phase_summary(c, player_id)

    return {
        "player": dict(get_player(c, player_id)),
        "stats": stats,
        "teams": teams,
        "year": year_rows,
        "distribution": distribution,
        "matches": innings,
        "oppositions": oppositions,
        "matchups": matchups,
        "dismissals": dismissals,
        "phase_summary": phase_summary,
        "filters": {"years": years, "opponents": opponents, "venues": venues},
    }



def build_player_team_history(c, player_id):
    raw=rows(c.execute("""
        SELECT m.match_id,m.year,m.match_date,t.team_name
        FROM match_players mp
        JOIN matches m ON m.match_id=mp.match_id
        JOIN teams t ON t.team_id=mp.team_id
        WHERE mp.player_id=?
        ORDER BY date(m.match_date) ASC,m.match_id ASC
    """,(player_id,)).fetchall())
    stints=[]
    for r in raw:
        team=canonical_team(r.get('team_name'))
        year=int(r['year']) if r.get('year') not in (None,'') and str(r['year']).isdigit() else None
        if not team or year is None: continue
        if not stints or stints[-1]['team_name']!=team:
            stints.append({'team_name':team,'years':[],'matches':0})
        stints[-1]['years'].append(year); stints[-1]['matches']+=1
    result=[]
    for stint in stints:
        years=sorted(set(stint['years']))
        if years:
            start,end=years[0],years[-1]
            result.append({'team_name':stint['team_name'],'start_year':start,'end_year':end,'period':str(start) if start==end else f"{start} - {end}",'matches':stint['matches']})
    return list(reversed(result))

def build_ai_payload(data):
    # Intentionally compact: no delivery-level data is sent from the Overview page.
    return {
        "page": "player_overview",
        "filters": data["filters"],
        "player": {
            "name": data["player"]["player_name"],
        },
        "overview_stats": data["stats"],
        "yearly_stats": data["year"],
        "team_history": data["teams"],
        "opposition_stats": data["oppositions"],
        "bowler_matchups": data["matchups"],
        "dismissal_breakdown": data["dismissals"],
        "phase_summary": data["phase_summary"],
    }

def generate_ai_analysis(payload):

    if not gemini_client:
        return {
            "status": "unavailable",
            "message": "GEMINI_API_KEY is not configured."
        }

    system_instruction = """
You are an expert IPL cricket analyst working for a professional
cricket analytics dashboard.

Analyse ONLY the statistics provided in the JSON.

Do NOT invent:
- matches
- scores
- trends
- player roles
- venues
- opposition results
- bowling styles
- batting positions
- match results

If the data does not support a conclusion, say that it cannot
be determined.

Look specifically for interesting, non-obvious trends such as:

1. Year-on-year performance changes
2. Strike-rate changes
3. Consistency vs volatility
4. Boundary dependency
5. Dot-ball pressure
6. Strong and weak opposition matchups
7. Specific bowler matchups
8. Dismissal patterns
9. High-score conversion
10. Powerplay vs middle-over vs death-over performance
11. Recent-form patterns
12. Unusual statistical patterns

Do not simply repeat the KPI cards.

Generate extremely concise, useful analysis suitable for a compact IPL
analytics dashboard. Every insight must be one short sentence (preferably
under 18 words) and contain a concrete statistical takeaway. Strengths and
watchouts must each be short, single-sentence bullets (preferably under 14
words). Avoid generic praise, repetition of KPI cards, and filler.

Return ONLY valid JSON in this exact structure:

{
  "profile": "One concise sentence describing the player's style or statistical profile, only if supported by data",
  "headline": "One sentence describing the most interesting overall finding",
  "insights": [
    {
      "title": "Short insight title",
      "text": "2-4 sentence analytical explanation"
    }
  ],
  "strengths": [
    "Strength 1",
    "Strength 2"
  ],
  "watchouts": [
    "Watchout 1",
    "Watchout 2"
  ]
}

Return between 3 and 5 insights, at most 3 strengths, and at most 3 watchouts.
"""

    payload_json = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":")
    )

    prompt = f"""
{system_instruction}

Here is the player analytics data:

{payload_json}
"""

    try:

        interaction = gemini_client.interactions.create(
            model=GEMINI_MODEL,
            input=prompt
        )

        text = interaction.output_text.strip()

        # Handle accidental markdown JSON fences
        if text.startswith("```"):
            text = text.strip("`")

            if text.startswith("json"):
                text = text[4:].strip()

        return json.loads(text)

    except Exception as e:

        log.exception("Gemini analysis failed")

        return {
            "status": "error",
            "message": str(e)
        }

@app.errorhandler(Exception)
def handle_any_error(e):
    log.error("Unhandled exception on %s", request.path)
    traceback.print_exc()
    return jsonify({"error": str(e), "type": type(e).__name__}), 500


# IPL RAG chatbot (uses the existing Gemini File Search store created by the RAG indexer).
RAG_STORE_NAME = os.environ.get("RAG_STORE_NAME", "").strip()
if not RAG_STORE_NAME:
    _rag_store_file = BASE_DIR / "rag_data" / "store_name.txt"
    if _rag_store_file.exists():
        RAG_STORE_NAME = _rag_store_file.read_text(encoding="utf-8").strip()

def query_rag_chat(question, player_name=""):
    if not gemini_client:
        raise RuntimeError("Gemini is not configured. Set GEMINI_API_KEY in the dashboard environment.")
    if not RAG_STORE_NAME:
        raise RuntimeError("RAG store is not configured. Set RAG_STORE_NAME or add rag_data/store_name.txt.")
    context = f"\nCurrent dashboard player: {player_name}\n" if player_name and player_name != "Select a Player" else ""
    prompt = f"""You are the IPL Dashboard chatbot. Answer using the IPL documents retrieved from the Gemini File Search knowledge base.
Rules: prefer retrieved IPL data; do not invent facts; if the answer is not present, say so clearly; combine documents carefully; perform calculations carefully; answer concisely but with enough detail.
{context}
User question:
{question}"""
    interaction = gemini_client.interactions.create(
        model=GEMINI_MODEL,
        input=prompt,
        tools=[{"type":"file_search","file_search_store_names":[RAG_STORE_NAME]}],
    )
    text=[]
    for step in getattr(interaction,"steps",[]) or []:
        if getattr(step,"type",None)!="model_output": continue
        for block in getattr(step,"content",[]) or []:
            if getattr(block,"type",None)=="text" and getattr(block,"text",None): text.append(block.text)
    if not text and getattr(interaction,"output_text",None): text=[interaction.output_text]
    return "\n".join(text).strip()


@app.get("/")
@app.get("/batters")
def index():
    return render_template("stats.html", dashboard_type="batter", page_title="Batter Stats", loading_subject="player", loading_detail="statistics, charts and match context", search_placeholder="Search Player, Team, or Match...", empty_player_label="Select a Player", default_team="—", empty_profile_text="Select a player to generate profile details.")


@app.post("/api/chat")
def chatbot():
    try:
        data=request.get_json(silent=True) or {}
        question=str(data.get("question","")).strip()
        if not question:
            return jsonify({"success":False,"error":"Enter a question."}),400
        answer=query_rag_chat(question, str(data.get("player_name","")).strip())
        return jsonify({"success":True,"answer":answer})
    except Exception as e:
        log.exception("RAG chatbot error")
        return jsonify({"success":False,"error":str(e)}),500


@app.get("/api/bowlers/search")
def bowler_search():
    q=request.args.get("q","").strip()
    if not q:
        return jsonify([])
    c=db()
    try:
        rs=c.execute("""SELECT p.player_id,p.player_name,SUM(d.bowler_wickets) wickets
                        FROM players p
                        JOIN deliveries d ON d.bowler_id=p.player_id
                        JOIN innings i ON i.innings_id=d.innings_id
                        WHERE i.is_super_over=0 AND p.player_name LIKE ? COLLATE NOCASE
                        GROUP BY p.player_id,p.player_name
                        ORDER BY CASE WHEN p.player_name LIKE ? COLLATE NOCASE THEN 0 ELSE 1 END,wickets DESC,p.player_name
                        LIMIT 12""",(f"%{q}%",f"{q}%")).fetchall()
        return jsonify(rows(rs))
    finally:
        c.close()


@app.get("/api/players")
def player_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    c = db()
    try:
        rs = c.execute(
            """SELECT player_id,player_name,registry_id FROM players
               WHERE player_name LIKE ? COLLATE NOCASE
               ORDER BY CASE WHEN player_name LIKE ? COLLATE NOCASE THEN 0 ELSE 1 END,player_name
               LIMIT 12""",
            (f"%{q}%", f"{q}%"),
        ).fetchall()
        return jsonify(rows(rs))
    finally:
        c.close()



@app.get("/api/player/<int:player_id>/filters")
def player_filter_values(player_id):
    c = db()
    try:
        if not get_player(c, player_id):
            return jsonify({"error": "Player not found"}), 404
        rs = c.execute(
            f"""SELECT DISTINCT m.year, {canonical_venue_sql('m')} venue,
                       {canonical_team_sql('ot')} opponent
                FROM deliveries d
                JOIN innings i ON i.innings_id=d.innings_id
                JOIN matches m ON m.match_id=i.match_id
                JOIN teams ot ON ot.team_id=i.bowling_team_id
                WHERE d.batter_id=? AND i.is_super_over=0""", (player_id,)
        ).fetchall()
        years = sorted({str(r['year']) for r in rs if r['year'] not in (None,'')}, key=lambda x:int(x), reverse=True)
        teams = sorted({r['opponent'] for r in rs if r['opponent']})
        venues = sorted({r['venue'] for r in rs if r['venue']})
        return jsonify({"years": years, "teams": teams, "venues": venues})
    finally:
        c.close()

@app.get("/api/filters")
def filter_values():
    c = db()
    try:
        years = c.execute(
            """SELECT DISTINCT year FROM matches
               WHERE year IS NOT NULL AND year<>''
               ORDER BY CAST(year AS INTEGER) DESC"""
        ).fetchall()
        venues = c.execute(
            """SELECT DISTINCT venue FROM matches
               WHERE venue IS NOT NULL AND venue<>'' ORDER BY venue"""
        ).fetchall()
        venue_names = sorted({canonical_venue(r[0]) for r in venues})
        return jsonify({
            "years": [r[0] for r in years],
            "teams": IPL_FRANCHISES,
            "venues": venue_names,
        })
    finally:
        c.close()


@app.get("/api/player/<int:player_id>/overview")
def overview(player_id):
    years, opponents, venues = filters_from_request()
    log.info("overview player_id=%s years=%r opponents=%r venues=%r", player_id, years, opponents, venues)
    c = db()
    try:
        if not get_player(c, player_id):
            return jsonify({"error": "Player not found"}), 404
        return jsonify(get_overview_data(c, player_id))
    except sqlite3.Error as e:
        log.exception("SQLite error for player_id=%s", player_id)
        return jsonify({"error": str(e)}), 500
    finally:
        c.close()


@app.get("/api/player/<int:player_id>/ai-analysis")
def ai_analysis(player_id):
    years, opponents, venues = filters_from_request()
    log.info("AI analysis player_id=%s years=%r opponents=%r venues=%r", player_id, years, opponents, venues)
    c = db()
    try:
        if not get_player(c, player_id):
            return jsonify({"error": "Player not found"}), 404
        data = get_overview_data(c, player_id)
        payload = build_ai_payload(data)
        analysis = generate_ai_analysis(payload)
        return jsonify({"model": GEMINI_MODEL, "payload": payload, "analysis": analysis})
    except sqlite3.Error as e:
        log.exception("SQLite error during AI analysis player_id=%s", player_id)
        return jsonify({"error": str(e)}), 500
    finally:
        c.close()


@app.get("/bowlers")
def bowlers_page():
    return render_template("stats.html", dashboard_type="bowler", page_title="Bowler Stats", loading_subject="bowling", loading_detail="bowling statistics and match context", search_placeholder="Search Bowler...", empty_player_label="Select a Bowler", default_team="IPL", empty_profile_text="Search for a player to generate bowling analytics.")


@app.get("/scorecards")
def scorecards_page():
    return render_template("scorecards.html")


@app.get("/api/scorecards/seasons")
def scorecard_seasons():
    c = db()
    try:
        seasons = set(str(y) for y in range(2008, 2027))
        raw = c.execute("SELECT DISTINCT season, year FROM matches WHERE season IS NOT NULL OR year IS NOT NULL").fetchall()
        for r in raw:
            for value in (r["season"], r["year"]):
                m = re.search(r"\b(20\d{2})\b", str(value or ""))
                if m:
                    year = int(m.group(1))
                    if 2008 <= year <= 2026:
                        seasons.add(str(year))
        return jsonify(sorted(seasons, key=lambda x: int(x), reverse=True))
    finally:
        c.close()


def _scorecard_season_where(season):
    return "(CAST(substr(m.season,1,4) AS INTEGER)=? OR CAST(m.year AS INTEGER)=?)", [int(season), int(season)]


def _knockout_count_for_season(season):
    try:
        return 3 if int(season) <= 2010 else 4
    except Exception:
        return 4


def _season_match_ids(c, season, league_only=False):
    where, params = _scorecard_season_where(season)
    rows_ = c.execute(f"SELECT m.match_id FROM matches m WHERE {where} ORDER BY m.match_date ASC, m.match_id ASC", params).fetchall()
    ids = [r["match_id"] for r in rows_]
    if league_only:
        knockout_count = _knockout_count_for_season(season)
        if len(ids) > knockout_count:
            ids = ids[:-knockout_count]
    return ids


def _cricket_overs_from_balls(balls):
    balls = max(0, int(balls or 0))
    return f"{balls // 6}.{balls % 6}"


def _scorecard_match_label(season, index, total):
    knockout_count = _knockout_count_for_season(season)
    knockout_start = total - knockout_count
    if index >= knockout_start:
        if int(season) <= 2010:
            names = ["Semi Final 1", "Semi Final 2", "Final"]
        else:
            names = ["Qualifier 1", "Eliminator", "Qualifier 2", "Final"]
        return names[index - knockout_start]
    n = index + 1
    suffix = "th" if 10 <= n % 100 <= 20 else {1:"st",2:"nd",3:"rd"}.get(n % 10, "th")
    return f"{n}{suffix} Match"


@app.get("/api/scorecards")
def scorecards_data():
    season = request.args.get("season", "").strip()
    if not re.fullmatch(r"20\d{2}", season):
        return jsonify([])
    c = db()
    try:
        where, params = _scorecard_season_where(season)
        rows_ = c.execute(f"""
            SELECT m.match_id, m.season, m.match_date, m.venue, m.result_type, m.result_margin,
                   m.result_margin_type, m.result_method,
                   t1.team_name AS team1, t2.team_name AS team2, tw.team_name AS winner,
                   i.innings_number, i.batting_team_id, SUM(d.total_runs) AS runs,
                   SUM(CASE WHEN d.is_wicket=1 THEN 1 ELSE 0 END) AS wickets,
                   SUM(CASE WHEN d.is_legal_delivery=1 THEN 1 ELSE 0 END) AS legal_balls
            FROM matches m
            JOIN teams t1 ON t1.team_id=m.team1_id
            JOIN teams t2 ON t2.team_id=m.team2_id
            LEFT JOIN teams tw ON tw.team_id=m.winner_team_id
            LEFT JOIN innings i ON i.match_id=m.match_id AND i.is_super_over=0
            LEFT JOIN deliveries d ON d.innings_id=i.innings_id
            WHERE {where}
            GROUP BY m.match_id, i.innings_id
            ORDER BY m.match_date ASC, m.match_id ASC, i.innings_number ASC
        """, params).fetchall()

        matches = {}
        for r in rows_:
            mid = r["match_id"]
            if mid not in matches:
                matches[mid] = {
                    "match_id": mid, "season": season, "date": r["match_date"],
                    "venue": canonical_venue(r["venue"]),
                    "team1": canonical_team(r["team1"]), "team2": canonical_team(r["team2"]),
                    "winner": canonical_team(r["winner"]) if r["winner"] else None,
                    "result_type": r["result_type"], "margin": r["result_margin"],
                    "margin_type": r["result_margin_type"], "result_method": r["result_method"],
                    "innings": []
                }
            if r["innings_number"] is not None:
                balls = int(r["legal_balls"] or 0)
                overs = _cricket_overs_from_balls(balls)
                team_row = c.execute("SELECT team_name FROM teams WHERE team_id=?", (r["batting_team_id"],)).fetchone()
                team_name = canonical_team(team_row[0]) if team_row else "Unknown"
                matches[mid]["innings"].append({
                    "team": team_name, "runs": int(r["runs"] or 0),
                    "wickets": int(r["wickets"] or 0), "overs": overs, "balls": balls
                })

        out = []
        for index, m in enumerate(matches.values()):
            innings_by_team = {i["team"]: i for i in m["innings"]}
            # Keep both teams visible even when a match is abandoned before the other side bats.
            for team in (m["team1"], m["team2"]):
                if team not in innings_by_team:
                    m["innings"].append({"team": team, "runs": None, "wickets": None, "overs": None, "balls": 0, "did_not_bat": True})

            method = str(m.get("result_method") or "").strip()
            is_dl = method.upper() in {"D/L", "DL", "DLS", "D/L/S"}
            if m["winner"] and m["margin"] is not None:
                unit = "runs" if m["margin_type"] == "runs" else "wickets" if m["margin_type"] == "wickets" else ""
                base = f'{m["winner"]} won by {m["margin"]} {unit}'.strip()
                if is_dl:
                    second = m["innings"][-1] if len(m["innings"]) >= 2 else None
                    overs_note = f"{second['overs']} overs game due to rain" if second and second.get("overs") else "rain-shortened game"
                    target_note = ""
                    if second and m["margin_type"] == "runs":
                        par = int(second.get("runs") or 0) + int(m["margin"] or 0)
                        target_note = f", D/L target {par + 1}"
                    elif second and m["margin_type"] == "wickets":
                        target_note = f", D/L target {int(second.get('runs') or 0)}"
                    m["result"] = f"{base} ({overs_note}{target_note})"
                else:
                    m["result"] = base
            elif m["result_type"] in ("tie", "draw"):
                m["result"] = (m["result_type"] or "Result").title()
            else:
                m["result"] = "No result"
            m["match_label"] = _scorecard_match_label(season, index, len(matches))
            out.append(m)
        return jsonify(out)
    finally:
        c.close()


def _add_nrr_entry(table, team_id, runs, balls, is_for=True):
    if team_id not in table or runs is None or balls is None or balls <= 0:
        return
    if is_for:
        table[team_id]["runs_for"] += int(runs)
        table[team_id]["balls_faced"] += int(balls)
    else:
        table[team_id]["runs_against"] += int(runs)
        table[team_id]["balls_bowled"] += int(balls)


@app.get("/api/scorecards/points-table")
def scorecard_points_table():
    season = request.args.get("season", "").strip()
    if not re.fullmatch(r"20\d{2}", season):
        return jsonify([])
    c = db()
    try:
        league_ids = _season_match_ids(c, season, league_only=True)
        if not league_ids:
            return jsonify([])
        placeholders = ",".join("?" for _ in league_ids)
        match_rows = c.execute(f"""
            SELECT m.match_id,m.match_date,m.result_type,m.result_method,m.result_margin,m.result_margin_type,
                   m.winner_team_id,m.team1_id,m.team2_id
            FROM matches m WHERE m.match_id IN ({placeholders}) ORDER BY m.match_date,m.match_id
        """, league_ids).fetchall()
        innings_rows = c.execute(f"""
            SELECT i.match_id,i.innings_number,i.batting_team_id,
                   SUM(d.total_runs) AS runs,
                   SUM(CASE WHEN d.is_legal_delivery=1 THEN 1 ELSE 0 END) AS balls,
                   SUM(CASE WHEN d.is_wicket=1 THEN 1 ELSE 0 END) AS wickets
            FROM innings i
            LEFT JOIN deliveries d ON d.innings_id=i.innings_id
            WHERE i.match_id IN ({placeholders}) AND i.is_super_over=0
            GROUP BY i.match_id,i.innings_id
            ORDER BY i.match_id,i.innings_number
        """, league_ids).fetchall()
        by_match = {}
        for r in innings_rows:
            by_match.setdefault(r["match_id"], []).append(r)

        names = {r["team_id"]: canonical_team(r["team_name"]) for r in c.execute("SELECT team_id,team_name FROM teams").fetchall()}
        table = {}
        history = {}
        previous_nrr = {}

        def ensure(tid):
            if tid is not None and tid not in table:
                table[tid] = {"matches":0,"wins":0,"losses":0,"no_results":0,"points":0,
                              "runs_for":0,"balls_faced":0,"runs_against":0,"balls_bowled":0}
                history[tid] = []
                previous_nrr[tid] = 0.0

        def add_nrr(tid, runs, balls, is_for=True):
            if tid is None or runs is None or not balls or balls <= 0:
                return
            if is_for:
                table[tid]["runs_for"] += int(runs); table[tid]["balls_faced"] += int(balls)
            else:
                table[tid]["runs_against"] += int(runs); table[tid]["balls_bowled"] += int(balls)

        def current_nrr(tid):
            v = table[tid]
            rf = (v["runs_for"] / v["balls_faced"] * 6) if v["balls_faced"] else 0
            ra = (v["runs_against"] / v["balls_bowled"] * 6) if v["balls_bowled"] else 0
            return rf - ra

        for match_no, m in enumerate(match_rows, 1):
            t1, t2 = m["team1_id"], m["team2_id"]
            ensure(t1); ensure(t2)
            if t1 is None or t2 is None:
                continue
            for tid in (t1, t2):
                table[tid]["matches"] += 1
            result = str(m["result_type"] or "").lower()
            result_text = "No result"
            if result in ("no_result", "no result", "abandoned", "cancelled"):
                for tid in (t1, t2):
                    table[tid]["no_results"] += 1; table[tid]["points"] += 1
            elif result in ("tie", "draw"):
                table[t1]["points"] += 1; table[t2]["points"] += 1
                result_text = "Tie"
            elif result in ("win", "super_over") and m["winner_team_id"] in (t1, t2):
                winner = m["winner_team_id"]; loser = t2 if winner == t1 else t1
                table[winner]["wins"] += 1; table[winner]["points"] += 2; table[loser]["losses"] += 1
            else:
                for tid in (t1, t2):
                    table[tid]["no_results"] += 1; table[tid]["points"] += 1

            # NR games never affect NRR. All other league games do.
            if result not in ("no_result", "no result", "abandoned", "cancelled"):
                innings = by_match.get(m["match_id"], [])
                is_dl = str(m["result_method"] or "").upper() in {"D/L", "DL", "DLS", "D/L/S"}
                if is_dl and len(innings) >= 2:
                    first, second = innings[0], innings[1]
                    adjusted_balls = int(second["balls"] or 0)
                    second_runs = int(second["runs"] or 0)
                    margin = int(m["result_margin"] or 0)
                    margin_type = str(m["result_margin_type"] or "").lower()
                    if margin_type == "runs":
                        if m["winner_team_id"] == second["batting_team_id"]:
                            par_score = max(0, second_runs - margin)
                        else:
                            par_score = second_runs + margin
                    elif margin_type == "wickets" and m["winner_team_id"] == second["batting_team_id"]:
                        par_score = max(0, second_runs - 1)
                    else:
                        par_score = int(first["runs"] or 0)
                    if adjusted_balls > 0:
                        add_nrr(first["batting_team_id"], par_score, adjusted_balls, True)
                        add_nrr(second["batting_team_id"], par_score, adjusted_balls, False)
                        add_nrr(second["batting_team_id"], second_runs, adjusted_balls, True)
                        add_nrr(first["batting_team_id"], second_runs, adjusted_balls, False)
                else:
                    for r in innings:
                        tid = r["batting_team_id"]
                        runs = int(r["runs"] or 0); balls = int(r["balls"] or 0); wickets = int(r["wickets"] or 0)
                        effective_balls = 120 if wickets >= 10 and balls < 120 else balls
                        add_nrr(tid, runs, effective_balls, True)
                        opp = t2 if tid == t1 else t1
                        add_nrr(opp, runs, effective_balls, False)

            for tid, opp in ((t1,t2),(t2,t1)):
                cumulative = current_nrr(tid)
                change = cumulative - previous_nrr.get(tid, 0.0)
                previous_nrr[tid] = cumulative
                history[tid].append({
                    "opposition": names.get(opp,"Unknown"), "match": _scorecard_match_label(season, match_no-1, len(match_rows)),
                    "date": m["match_date"], "result": result_text if result in ("no_result", "no result", "abandoned", "cancelled", "tie", "draw") else ("Won" if m["winner_team_id"] == tid else "Lost"),
                    "nrr_change": round(change, 3), "nrr": round(cumulative, 3)
                })

        out = []
        for tid, v in table.items():
            out.append({"team":names.get(tid,"Unknown"),"matches":v["matches"],"wins":v["wins"],
                        "losses":v["losses"],"no_results":v["no_results"],"points":v["points"],
                        "nrr":round(current_nrr(tid),3),"history":history.get(tid,[])})
        out.sort(key=lambda x:(-x["points"],-x["wins"],-x["nrr"],x["team"]))
        for i, row in enumerate(out):
            row["status"] = "Q" if i < 4 else "E"
        return jsonify(out)
    finally:
        c.close()


@app.get("/rankings")
def rankings_page():
    return render_template("rankings.html")


@app.get("/records")
def records_page():
    return render_template("section.html", TITLE="Records")


def bowler_filter_sql(alias="ib"):
    years, opponents, venues = filters_from_request()
    clauses=[f"{alias}.is_super_over=0"]
    params=[]
    if years:
        clauses.append(f"{alias}.year IN ({_in_clause(years)})"); params.extend(years)
    if opponents:
        clauses.append(f"EXISTS (SELECT 1 FROM teams ot WHERE ot.team_id={alias}.opposition_team_id AND {canonical_team_sql('ot')} IN ({_in_clause(opponents)}))"); params.extend(opponents)
    if venues:
        clauses.append(f"{canonical_venue_sql(alias)} IN ({_in_clause(venues)})"); params.extend(venues)
    return " AND ".join(clauses),params


def bowling_result(row):
    if row.get("result_type")=="no_result": return "No Result"
    if row.get("result_type")=="tie": return "Tied"
    if row.get("result_type")=="super_over": return "Won (Super Over)" if row.get("team_id")==row.get("winner_team_id") else "Lost (Super Over)"
    if row.get("result_type")=="win":
        won=row.get("team_id")==row.get("winner_team_id"); margin=row.get("result_margin"); typ=row.get("result_margin_type")
        return ("Won" if won else "Lost")+(f" by {margin} {typ}" if margin else "")
    return "—"


def get_bowler_overview_data(c, player_id):
    where,params=bowler_filter_sql("ib")
    player=get_player(c,player_id)
    match_ids=c.execute(f"SELECT DISTINCT ib.match_id FROM v_innings_bowling ib WHERE ib.player_id=? AND {where}",[player_id,*params]).fetchall()
    match_ids=[r[0] for r in match_ids]
    match_clauses=["mp.player_id=?"]; match_params=[player_id]
    years,opponents,venues=filters_from_request()
    if years: match_clauses.append(f"m.year IN ({_in_clause(years)})"); match_params.extend(years)
    if venues: match_clauses.append(f"{canonical_venue_sql('m')} IN ({_in_clause(venues)})"); match_params.extend(venues)
    if opponents:
        match_clauses.append("EXISTS (SELECT 1 FROM teams ot WHERE ot.team_id=CASE WHEN mp.team_id=m.team1_id THEN m.team2_id ELSE m.team1_id END "+f"AND {canonical_team_sql('ot')} IN ({_in_clause(opponents)}))"); match_params.extend(opponents)
    matches_played=c.execute(f"SELECT COUNT(DISTINCT mp.match_id) FROM match_players mp JOIN matches m ON m.match_id=mp.match_id WHERE {' AND '.join(match_clauses)}",match_params).fetchone()[0] or 0
    innings=rows(c.execute(f"""SELECT ib.*,m.match_date,m.winner_team_id,m.result_type,m.result_margin,m.result_margin_type,bt.team_name team_raw,ot.team_name opp_raw,(SELECT COUNT(*) FROM (SELECT d2.over_number FROM deliveries d2 WHERE d2.innings_id=ib.innings_id AND d2.bowler_id=ib.player_id GROUP BY d2.over_number HAVING SUM(d2.bowler_runs_conceded)=0)) maidens,CASE WHEN EXISTS (SELECT 1 FROM match_player_of_match pom WHERE pom.player_id=ib.player_id AND pom.match_id=ib.match_id) THEN 1 ELSE 0 END is_mom FROM v_innings_bowling ib JOIN matches m ON m.match_id=ib.match_id LEFT JOIN teams bt ON bt.team_id=ib.team_id LEFT JOIN teams ot ON ot.team_id=ib.opposition_team_id WHERE ib.player_id=? AND {where} ORDER BY date(m.match_date) DESC,ib.innings_id DESC""",[player_id,*params]).fetchall())
    for r in innings:
        r['team']=canonical_team(r.pop('team_raw',None)); r['opposition']=canonical_team(r.pop('opp_raw',None)); r['overs']=f"{int(r['balls_bowled'])//6}.{int(r['balls_bowled'])%6}"; r['economy']=round(6*r['runs_conceded']/r['balls_bowled'],2) if r['balls_bowled'] else None; r['strike_rate']=round(r['balls_bowled']/r['wickets'],2) if r['wickets'] else None; r['average']=round(r['runs_conceded']/r['wickets'],2) if r['wickets'] else None; r['result']=bowling_result(r)
    balls=sum(int(r['balls_bowled'] or 0) for r in innings); runs=sum(int(r['runs_conceded'] or 0) for r in innings); wickets=sum(int(r['wickets'] or 0) for r in innings); dots=sum(int(r['dot_balls'] or 0) for r in innings)
    best=max(innings,key=lambda r:(int(r['wickets'] or 0),-int(r['runs_conceded'] or 0)),default=None)
    season=rows(c.execute(f"""SELECT ib.year,COUNT(*) innings,SUM(ib.balls_bowled) balls,SUM(ib.runs_conceded) runs,SUM(ib.wickets) wickets,SUM(ib.dot_balls) dots FROM v_innings_bowling ib WHERE ib.player_id=? AND {where} GROUP BY ib.year ORDER BY CAST(ib.year AS INTEGER)""",[player_id,*params]).fetchall())
    for r in season: r['economy']=round(6*r['runs']/r['balls'],2) if r['balls'] else None; r['average']=round(r['runs']/r['wickets'],2) if r['wickets'] else None; r['strike_rate']=round(r['balls']/r['wickets'],2) if r['wickets'] else None
    career=list(reversed(innings))
    for idx,r in enumerate(career,1): r['sequence']=idx; r['figures']=f"{r['wickets']}/{r['runs_conceded']}"
    opps=rows(c.execute(f"""SELECT {canonical_team_sql('ot')} opponent,SUM(ib.balls_bowled) balls,SUM(ib.runs_conceded) runs,SUM(ib.wickets) wickets,SUM(ib.dot_balls) dots FROM v_innings_bowling ib JOIN teams ot ON ot.team_id=ib.opposition_team_id WHERE ib.player_id=? AND {where} GROUP BY {canonical_team_sql('ot')} ORDER BY wickets DESC,runs ASC""",[player_id,*params]).fetchall())
    for r in opps: r['economy']=round(6*r['runs']/r['balls'],2) if r['balls'] else None; r['average']=round(r['runs']/r['wickets'],2) if r['wickets'] else None
    phases=rows(c.execute(f"""SELECT CASE WHEN d.over_number<6 THEN 'Powerplay (1-6)' WHEN d.over_number<15 THEN 'Middle (7-15)' ELSE 'Death (16-20)' END phase,SUM(d.is_legal_delivery) balls,SUM(d.bowler_runs_conceded) runs,SUM(d.bowler_wickets) wickets,SUM(CASE WHEN d.is_dot=1 AND d.is_legal_delivery=1 THEN 1 ELSE 0 END) dots FROM deliveries d JOIN innings i ON i.innings_id=d.innings_id JOIN matches m ON m.match_id=i.match_id JOIN teams ot ON ot.team_id=i.batting_team_id WHERE d.bowler_id=? AND i.is_super_over=0 {'AND m.year IN ('+_in_clause(years)+')' if years else ''} {'AND '+canonical_venue_sql('m')+' IN ('+_in_clause(venues)+')' if venues else ''} {'AND '+canonical_team_sql('ot')+' IN ('+_in_clause(opponents)+')' if opponents else ''} GROUP BY phase ORDER BY CASE phase WHEN 'Powerplay (1-6)' THEN 1 WHEN 'Middle (7-15)' THEN 2 ELSE 3 END""",[player_id,*years,*venues,*opponents]).fetchall())
    for r in phases: r['economy']=round(6*r['runs']/r['balls'],2) if r['balls'] else None
    dismissals=rows(c.execute(f"""SELECT w.wicket_kind kind,COUNT(*) count FROM wickets w JOIN deliveries d ON d.delivery_id=w.delivery_id JOIN innings i ON i.innings_id=d.innings_id JOIN matches m ON m.match_id=i.match_id JOIN teams ot ON ot.team_id=i.batting_team_id WHERE d.bowler_id=? AND d.bowler_wickets=1 AND i.is_super_over=0 {'AND m.year IN ('+_in_clause(years)+')' if years else ''} {'AND '+canonical_venue_sql('m')+' IN ('+_in_clause(venues)+')' if venues else ''} {'AND '+canonical_team_sql('ot')+' IN ('+_in_clause(opponents)+')' if opponents else ''} GROUP BY w.wicket_kind ORDER BY count DESC""",[player_id,*years,*venues,*opponents]).fetchall())
    history=build_player_team_history(c, player_id)
    matchups=rows(c.execute(f"""SELECT p.player_name batter,SUM(d.counts_as_faced) balls,SUM(d.batter_runs) runs,SUM(d.is_four) fours,SUM(d.is_six) sixes,SUM(CASE WHEN d.is_dot=1 AND d.is_legal_delivery=1 THEN 1 ELSE 0 END) dots,SUM(d.bowler_wickets) wickets FROM deliveries d JOIN innings i ON i.innings_id=d.innings_id JOIN matches m ON m.match_id=i.match_id JOIN players p ON p.player_id=d.batter_id JOIN teams ot ON ot.team_id=i.batting_team_id WHERE d.bowler_id=? AND i.is_super_over=0 {'AND m.year IN ('+_in_clause(years)+')' if years else ''} {'AND '+canonical_venue_sql('m')+' IN ('+_in_clause(venues)+')' if venues else ''} {'AND '+canonical_team_sql('ot')+' IN ('+_in_clause(opponents)+')' if opponents else ''} GROUP BY d.batter_id,p.player_name ORDER BY wickets DESC,runs DESC""",[player_id,*years,*venues,*opponents]).fetchall())
    for r in matchups: r['average']=round(r['runs']/r['wickets'],2) if r['wickets'] else None; r['strike_rate']=round(100*r['runs']/r['balls'],2) if r['balls'] else None; r['dot_percentage']=round(100*r['dots']/r['balls'],2) if r['balls'] else None
    three_w=sum(1 for r in innings if (r['wickets'] or 0)>=3)
    four_w=sum(1 for r in innings if (r['wickets'] or 0)>=4)
    five_w=sum(1 for r in innings if (r['wickets'] or 0)>=5)
    return {'player':dict(player),'summary':{'matches':matches_played,'innings':len(innings),'wickets':wickets,'balls':balls,'runs_conceded':runs,'overs':f"{balls//6}.{balls%6}",'average':round(runs/wickets,2) if wickets else None,'economy':round(6*runs/balls,2) if balls else None,'strike_rate':round(balls/wickets,2) if wickets else None,'best':f"{best['wickets']}/{best['runs_conceded']}" if best else '—','three_w':three_w,'four_w':four_w,'five_w':five_w,'dot_percentage':round(100*dots/balls,2) if balls else None},'season':season,'career':career,'matches':innings,'oppositions':opps,'phases':phases,'dismissals':dismissals,'history':history,'matchups':matchups}

@app.get('/api/bowler/<int:player_id>/filters')
def bowler_filter_values(player_id):
    c=db()
    try:
        rs=c.execute(f"SELECT DISTINCT ib.year,{canonical_venue_sql('ib')} venue,{canonical_team_sql('ot')} opponent FROM v_innings_bowling ib JOIN teams ot ON ot.team_id=ib.opposition_team_id WHERE ib.player_id=? AND ib.is_super_over=0",[player_id]).fetchall()
        return jsonify({'years':sorted({str(r['year']) for r in rs if r['year'] not in (None,'')},key=lambda x:int(x),reverse=True),'teams':sorted({r['opponent'] for r in rs if r['opponent']}),'venues':sorted({r['venue'] for r in rs if r['venue']})})
    finally: c.close()

@app.get('/api/bowler/<int:player_id>/overview')
def bowler_overview(player_id):
    c=db()
    try:
        if not get_player(c,player_id): return jsonify({'error':'Player not found'}),404
        return jsonify(get_bowler_overview_data(c,player_id))
    except sqlite3.Error as e:
        log.exception('Bowler overview error'); return jsonify({'error':str(e)}),500
    finally: c.close()

@app.get('/api/bowler/<int:player_id>/ai-analysis')
def bowler_ai(player_id):
    c=db()
    try:
        data=get_bowler_overview_data(c,player_id); s=data['summary']; p=data['player']['player_name']
        insights=[]
        if s['wickets']: insights.append(f"{p} has taken {s['wickets']} wickets at an average of {s['average']} and economy of {s['economy']} in the selected sample.")
        if data['phases']:
            best=max(data['phases'],key=lambda x:x['wickets'] or 0); insights.append(f"His strongest wicket-taking phase is {best['phase']} with {best['wickets']} wickets.")
        if data['oppositions']:
            best=max(data['oppositions'],key=lambda x:x['wickets'] or 0); insights.append(f"His most productive opposition is {best['opponent']} with {best['wickets']} wickets.")
        return jsonify({'model':'Database Analysis','analysis':{'insights':insights,'strengths':['Wicket-taking impact' if s['wickets'] else 'Limited bowling sample'],'watchouts':['Interpret rankings with workload and sample size in mind.']}})
    finally: c.close()


# IPL Intelligence Rankings: transparent, ICC-inspired rating engine. The official ICC formula is proprietary;
# this model follows the publicly described principles using only the scorecard/ball-by-ball database.
from collections import defaultdict
import math

RANKING_CACHE = {}


def _ranking_years(c):
    return [r[0] for r in c.execute("SELECT DISTINCT year FROM matches WHERE year IS NOT NULL AND year<>'' ORDER BY CAST(year AS INTEGER) DESC")]


def _safe_float(v, default=0.0):
    try: return float(v)
    except (TypeError, ValueError): return default


def _clamp(v, lo=0.0, hi=1000.0):
    return max(lo, min(hi, v))


def _recent_form(values, good='W'):
    if not values: return '—'
    return ' '.join(values[-5:])


def _load_ranking_data(c):
    matches=rows(c.execute("""
        SELECT m.match_id,m.year,m.season,m.match_date,m.winner_team_id,m.result_type,m.result_margin,m.result_margin_type,
               m.team1_id,m.team2_id,t1.team_name team1,t2.team_name team2
        FROM matches m LEFT JOIN teams t1 ON t1.team_id=m.team1_id LEFT JOIN teams t2 ON t2.team_id=m.team2_id
        ORDER BY COALESCE(m.match_date,''),m.match_id
    """))
    team_names={r['team1_id']:r['team1'] for r in matches if r['team1_id'] is not None}
    team_names.update({r['team2_id']:r['team2'] for r in matches if r['team2_id'] is not None})
    players={r['player_id']:r['player_name'] for r in c.execute('SELECT player_id,player_name FROM players')}
    bat=rows(c.execute("""
        SELECT ib.match_id,ib.innings_id,ib.player_id,ib.team_id,ib.opposition_team_id,ib.runs,ib.balls_faced,ib.is_out
        FROM v_innings_batting ib WHERE ib.is_super_over=0
    """))
    bowl=rows(c.execute("""
        SELECT match_id,innings_id,player_id,team_id,opposition_team_id,balls_bowled,runs_conceded,wickets
        FROM v_innings_bowling WHERE is_super_over=0 AND player_id IS NOT NULL
    """))
    team_totals=rows(c.execute("""
        SELECT i.match_id,i.innings_id,i.batting_team_id team_id,SUM(d.total_runs) runs
        FROM innings i JOIN deliveries d ON d.innings_id=i.innings_id
        WHERE i.is_super_over=0 GROUP BY i.match_id,i.innings_id,i.batting_team_id
    """))
    faced=rows(c.execute("""
        SELECT i.match_id,d.batter_id,d.bowler_id,SUM(d.batter_runs) runs
        FROM deliveries d JOIN innings i ON i.innings_id=d.innings_id
        WHERE i.is_super_over=0 AND d.batter_id IS NOT NULL AND d.bowler_id IS NOT NULL
        GROUP BY i.match_id,d.batter_id,d.bowler_id
    """))
    dismissed=rows(c.execute("""
        SELECT i.match_id,d.bowler_id,w.player_out_id batter_id
        FROM wickets w JOIN deliveries d ON d.delivery_id=w.delivery_id JOIN innings i ON i.innings_id=d.innings_id
        WHERE i.is_super_over=0 AND d.bowler_wickets=1 AND d.bowler_id IS NOT NULL AND w.player_out_id IS NOT NULL
    """))
    appearances=rows(c.execute("SELECT match_id,player_id,team_id FROM match_players"))
    return matches,players,team_names,bat,bowl,team_totals, faced,dismissed,appearances


def _knockout_match_ids(matches):
    by_year=defaultdict(list)
    for m in matches:
        if m['year']: by_year[str(m['year'])].append(m)
    out=set()
    for year,ms in by_year.items():
        # Full IPL seasons normally have 50+ matches; final four chronological matches are playoffs/final.
        if len(ms)>=50: out.update(m['match_id'] for m in ms[-4:])
    return out


def _season_champions(matches, team_key):
    by_year=defaultdict(list)
    for m in matches:
        if m.get('year'): by_year[str(m['year'])].append(m)
    champion_match_ids=set(); titles=defaultdict(list)
    for year,ms in by_year.items():
        final=ms[-1]
        winner_id=final.get('winner_team_id')
        if winner_id is None: continue
        champion=team_key.get(winner_id)
        if not champion: continue
        champion_match_ids.add(final['match_id'])
        titles[champion].append(year)
    return champion_match_ids,{team:sorted(years,key=lambda y:int(y) if str(y).isdigit() else str(y)) for team,years in titles.items()}


def _calculate_rankings(c, selected_years=None, selected_teams=None):
    selected_years=tuple(sorted({str(y) for y in (selected_years or []) if str(y).strip()}))
    selected_teams=tuple(sorted({canonical_team(t) for t in (selected_teams or []) if str(t).strip()}))
    stamp=str(Path(DB_PATH).stat().st_mtime_ns) if Path(DB_PATH).exists() else 'none'
    cache_key=(stamp,selected_years or ('all',))
    cached=RANKING_CACHE.get(cache_key)
    if cached: return cached
    selected_team_set=set(selected_teams)
    matches,players,team_names,bat_rows,bowl_rows,total_rows,face_rows,dismiss_rows,appearance_rows=_load_ranking_data(c)
    # Ratings are always replayed continuously from the beginning of IPL history up to the end
    # of the selected period. A season filter therefore means an end-of-period rating snapshot,
    # not a fresh rating calculation that starts from the base value.
    all_year_values=sorted({str(m.get('year') or '') for m in matches if str(m.get('year') or '').isdigit()}, key=lambda x:int(x))
    snapshot_year=max(selected_years,key=lambda x:int(x)) if selected_years else (all_year_values[-1] if all_year_values else None)
    matches=[m for m in matches if snapshot_year is None or (str(m.get('year') or '').isdigit() and int(str(m.get('year')))<=int(snapshot_year))]
    match_ids={m['match_id'] for m in matches}
    team_key={tid:canonical_team(name) for tid,name in team_names.items()}
    canonical_teams=sorted(set(team_key.values()))
    match_year={m['match_id']:str(m.get('year') or '') for m in matches}
    season_env=defaultdict(lambda:{'runs_per_ball':1.25,'bat_avg':20.0,'econ':7.5,'wkts_per_ball':0.045,'innings_score':160.0})
    season_acc=defaultdict(lambda:defaultdict(float))
    for r in bat_rows:
        y=match_year.get(r['match_id'],'')
        if r['match_id'] in match_ids:
            season_acc[y]['runs']+=_safe_float(r['runs']); season_acc[y]['balls']+=_safe_float(r['balls_faced']); season_acc[y]['outs']+=_safe_float(r['is_out']); season_acc[y]['bat_innings']+=1
    for r in bowl_rows:
        y=match_year.get(r['match_id'],'')
        if r['match_id'] in match_ids:
            season_acc[y]['bowl_runs']+=_safe_float(r['runs_conceded']); season_acc[y]['bowl_balls']+=_safe_float(r['balls_bowled']); season_acc[y]['wkts']+=_safe_float(r['wickets'])
    for r in total_rows:
        y=match_year.get(r['match_id'],'')
        if r['match_id'] in match_ids:
            season_acc[y]['innings_runs']+=_safe_float(r['runs']); season_acc[y]['innings_count']+=1
    for y,a in season_acc.items():
        balls=max(a['balls'],1); outs=max(a['outs'],1); bowl_balls=max(a['bowl_balls'],1);
        season_env[y]={
            'runs_per_ball':a['runs']/balls,
            'bat_avg':a['runs']/outs,
            'econ':6*a['bowl_runs']/bowl_balls,
            'wkts_per_ball':a['wkts']/bowl_balls,
            'innings_score':a['innings_runs']/max(a['innings_count'],1)
        }
    by_match_bat=defaultdict(list); by_match_bowl=defaultdict(list); by_match_total=defaultdict(list)
    by_match_face=defaultdict(list); by_match_dismiss=defaultdict(list); by_match_appearance=defaultdict(set); by_match_player_team=defaultdict(dict)
    for r in bat_rows:
        if r['match_id'] in match_ids: by_match_bat[r['match_id']].append(r)
    for r in bowl_rows:
        if r['match_id'] in match_ids: by_match_bowl[r['match_id']].append(r)
    for r in total_rows:
        if r['match_id'] in match_ids: by_match_total[r['match_id']].append(r)
    for r in face_rows:
        if r['match_id'] in match_ids: by_match_face[r['match_id']].append(r)
    for r in dismiss_rows:
        if r['match_id'] in match_ids: by_match_dismiss[r['match_id']].append(r)
    for r in appearance_rows:
        if r['match_id'] in match_ids:
            player_team=team_key.get(r['team_id'],'Unknown')
            by_match_appearance[r['match_id']].add(r['player_id'])
            by_match_player_team[r['match_id']][r['player_id']]=player_team
    knockout_ids=_knockout_match_ids(matches)
    champion_match_ids,title_years=_season_champions(matches,team_key)
    bat_rating=defaultdict(lambda:350.0); bowl_rating=defaultdict(lambda:350.0); team_rating=defaultdict(lambda:500.0)
    team_bat_rating=defaultdict(lambda:500.0); team_bowl_rating=defaultdict(lambda:500.0)
    bat_apps=defaultdict(int); bowl_apps=defaultdict(int)
    stats_all=defaultdict(lambda:defaultdict(float)); team_stats_all=defaultdict(lambda:defaultdict(float))
    form_all=defaultdict(list); team_form_all=defaultdict(list); player_latest_team={}; player_team_history=defaultdict(set)
    rating_events=[]; season_snapshots={}
    current_year=None
    for idx,m in enumerate(matches):
        if current_year is not None and str(m.get('year') or '')!=current_year:
            season_snapshots[current_year]={'bat':dict(bat_rating),'bowl':dict(bowl_rating),'team':dict(team_rating),'team_bat':dict(team_bat_rating),'team_bowl':dict(team_bowl_rating)}
        current_year=str(m.get('year') or '')
        mid=m['match_id']; year=str(m['year'] or '')
        if not year: continue
        for pid in by_match_appearance[mid]:
            stats_all[pid]['matches']+=1
            player_team=by_match_player_team[mid].get(pid,player_latest_team.get(pid,'Unknown')); player_latest_team[pid]=player_team; player_team_history[pid].add(player_team)
        innings_totals=[r['runs'] for r in by_match_total[mid]]
        season_baseline=season_env.get(year,{'runs_per_ball':1.25,'bat_avg':20.0,'econ':7.5,'wkts_per_ball':0.045,'innings_score':160.0})
        env=sum(innings_totals)/len(innings_totals) if innings_totals else season_baseline['innings_score']
        env_factor=_clamp(season_baseline['innings_score']/max(env,1),0.72,1.35)
        face_map=defaultdict(lambda:defaultdict(float))
        for r in by_match_face[mid]: face_map[r['batter_id']][r['bowler_id']]+=r['runs']
        dismiss_map=defaultdict(list)
        for r in by_match_dismiss[mid]: dismiss_map[r['bowler_id']].append(r['batter_id'])
        is_knockout=mid in knockout_ids
        for r in by_match_bat[mid]:
            pid=r['player_id']; runs=_safe_float(r['runs']); balls=_safe_float(r['balls_faced']); sr=(100*runs/balls) if balls else 0
            faced_quality=350.0
            if face_map.get(pid):
                weighted=sum(v*bowl_rating[bid] for bid,v in face_map[pid].items())
                faced_quality=weighted/max(sum(face_map[pid].values()),1)
            attack_ids=[x['player_id'] for x in by_match_bowl[mid] if x['team_id']==r['opposition_team_id']]
            attack_quality=sum(bowl_rating[x] for x in attack_ids)/len(attack_ids) if attack_ids else 350.0
            quality=((faced_quality+attack_quality)/2-350)/650
            season_sr=100*season_baseline['runs_per_ball']
            relative_sr=(sr/max(season_sr,1)) if balls else 0
            relative_volume=(runs/max(season_baseline['bat_avg'],1))
            speed=0 if balls==0 else _clamp(relative_sr-1,-0.55,0.75)
            volume_factor=_clamp(0.80+0.20*relative_volume,0.72,1.35)
            perf=(260+runs*7.0*volume_factor+runs*85*speed/100+env_factor*45+quality*70)
            if runs>=30: perf+=15
            if not r['is_out']: perf+=18
            won=m['winner_team_id']==r['team_id']; team=team_key.get(r['team_id'],'Unknown'); opp=team_key.get(r['opposition_team_id'],'Unknown')
            if won: perf+=38+max(0,(team_rating[opp]-team_rating[team]))/35
            elif m['result_type'] in ('tie','no_result'): perf+=8
            if is_knockout: perf*=1.08
            perf=_clamp(perf); bat_apps[pid]+=1; alpha=0.20 if bat_apps[pid]<=12 else 0.14
            prior=bat_rating[pid]; bat_rating[pid]=(1-alpha)*prior+alpha*perf
            st=stats_all[pid]; st['runs']+=runs; st['balls']+=balls; st['innings']+=1
            if r['is_out']: st['outs']+=1
            form_all[pid].append('+' if perf>=prior else '−')
            rating_events.append({'type':'bat','match_id':mid,'player_id':pid,'team':team,'perf':perf,'runs':runs,'balls':balls,'innings':1,'outs':1 if r['is_out'] else 0})
        for r in by_match_bowl[mid]:
            pid=r['player_id']; balls=_safe_float(r['balls_bowled']); runs=_safe_float(r['runs_conceded']); wkts=_safe_float(r['wickets']); overs=balls/6; econ=runs/overs if overs else 99
            opp_ids=[x['player_id'] for x in by_match_bat[mid] if x['team_id']==r['opposition_team_id']]
            attack_quality=sum(bat_rating[x] for x in opp_ids)/len(opp_ids) if opp_ids else 350.0
            dismissed_quality=sum(bat_rating[x] for x in dismiss_map.get(pid,[]))/len(dismiss_map[pid]) if dismiss_map.get(pid) else 350.0
            quality=((attack_quality+dismissed_quality)/2-350)/650
            relative_econ=season_baseline['econ']/max(econ,0.1)
            relative_wicket_rate=(wkts/max(balls,1))/max(season_baseline['wkts_per_ball'],0.001)
            econ_score=_clamp((relative_econ-1)*150,-80,190); workload=min(55,balls*1.8)
            wicket_score=wkts*145*_clamp(0.80+0.20*relative_wicket_rate,0.70,1.45)
            perf=255+wicket_score+econ_score+workload+env_factor*35+quality*65
            won=m['winner_team_id']==r['team_id']; team=team_key.get(r['team_id'],'Unknown'); opp=team_key.get(r['opposition_team_id'],'Unknown')
            if won: perf+=36+max(0,(team_rating[opp]-team_rating[team]))/38
            elif m['result_type'] in ('tie','no_result'): perf+=8
            if is_knockout: perf*=1.08
            perf=_clamp(perf); bowl_apps[pid]+=1; alpha=0.21 if bowl_apps[pid]<=12 else 0.15
            prior=bowl_rating[pid]; bowl_rating[pid]=(1-alpha)*prior+alpha*perf
            st=stats_all[pid]; st['wickets']+=wkts; st['bowl_runs']+=runs; st['bowl_balls']+=balls
            form_all[pid].append('+' if perf>=prior else '−')
            rating_events.append({'type':'bowl','match_id':mid,'player_id':pid,'team':team,'perf':perf,'wickets':wkts,'bowl_runs':runs,'bowl_balls':balls})
        for tid in (m['team1_id'],m['team2_id']):
            team=team_key.get(tid,'Unknown')
            team_bat_rows=[r for r in by_match_bat[mid] if r['team_id']==tid]
            team_bowl_rows=[r for r in by_match_bowl[mid] if r['team_id']==tid]
            if team_bat_rows:
                player_score=sum(bat_rating[r['player_id']] for r in team_bat_rows)/len(team_bat_rows)
                truns=sum(_safe_float(r['runs']) for r in team_bat_rows); tballs=sum(_safe_float(r['balls_faced']) for r in team_bat_rows)
                team_rpb=truns/max(tballs,1); era_attack=500*_clamp(team_rpb/max(season_baseline['runs_per_ball'],0.01),0.70,1.45)
                score=0.65*player_score+0.35*era_attack
                team_bat_rating[team]=0.84*team_bat_rating[team]+0.16*score
            if team_bowl_rows:
                player_score=sum(bowl_rating[r['player_id']] for r in team_bowl_rows)/len(team_bowl_rows)
                truns=sum(_safe_float(r['runs_conceded']) for r in team_bowl_rows); tballs=sum(_safe_float(r['balls_bowled']) for r in team_bowl_rows)
                team_econ=6*truns/max(tballs,1); era_defence=500*_clamp(season_baseline['econ']/max(team_econ,0.1),0.70,1.45)
                score=0.65*player_score+0.35*era_defence
                team_bowl_rating[team]=0.84*team_bowl_rating[team]+0.16*score
        if m['team1_id'] and m['team2_id']:
            a=team_key.get(m['team1_id'],'Unknown'); b=team_key.get(m['team2_id'],'Unknown')
            if a!=b:
                ra,rb=team_rating[a],team_rating[b]; ea=1/(1+10**((rb-ra)/400)); eb=1-ea
                winner=team_key.get(m['winner_team_id']) if m['winner_team_id'] else None
                if winner==a: sa,sb=1,0
                elif winner==b: sa,sb=0,1
                else: sa,sb=.5,.5
                margin_bonus=min(0.15,_safe_float(m['result_margin'])/100) if m['result_margin'] else 0
                k=26*(1.12 if is_knockout else 1.0)*(1+margin_bonus)
                team_rating[a]=_clamp(ra+k*(sa-ea)); team_rating[b]=_clamp(rb+k*(sb-eb))
                if mid in champion_match_ids and winner in (a,b):
                    team_rating[winner]=_clamp(team_rating[winner]+24)
                for tid,res in [(a,sa),(b,sb)]:
                    st=team_stats_all[tid]; st['matches']+=1
                    if res==1: st['wins']+=1; f='W'
                    elif res==0: st['losses']+=1; f='L'
                    else: st['ties']+=1; f='T'
                    team_form_all[tid].append(f)
    if current_year is not None:
        season_snapshots[current_year]={'bat':dict(bat_rating),'bowl':dict(bowl_rating),'team':dict(team_rating),'team_bat':dict(team_bat_rating),'team_bowl':dict(team_bowl_rating)}
    # Team filters are display-only: ratings are never recalculated for a selected franchise.
    team_season_participation=defaultdict(set)
    for m in matches:
        y=str(m.get('year') or '')
        for tid in (m.get('team1_id'),m.get('team2_id')):
            if tid in team_key and y: team_season_participation[team_key[tid]].add(y)
    player_team_seasons=defaultdict(lambda:defaultdict(set))
    for r in appearance_rows:
        if r['match_id'] in match_ids:
            y=match_year.get(r['match_id'],'')
            team=team_key.get(r['team_id'],'Unknown')
            if y: player_team_seasons[r['player_id']][team].add(y)
    result={'years':list(selected_years) if selected_years else _ranking_years(c), 'snapshot_year':snapshot_year, 'season_snapshots':season_snapshots, 'all':{'bat':dict(bat_rating),'bowl':dict(bowl_rating),'team':dict(team_rating),'team_bat':dict(team_bat_rating),'team_bowl':dict(team_bowl_rating),'stats':stats_all,'team_stats':team_stats_all,'form':form_all,'team_form':team_form_all,'titles':title_years}, 'players':players,'player_teams':player_latest_team,'player_team_history':{pid:sorted(teams) for pid,teams in player_team_history.items()},'player_team_seasons':{pid:{team:sorted(years,key=lambda x:int(x) if x.isdigit() else 0) for team,years in teams.items()} for pid,teams in player_team_seasons.items()},'teams':{name:name for name in canonical_teams},'team_season_participation':{k:sorted(v,key=lambda x:int(x) if x.isdigit() else 0) for k,v in team_season_participation.items()},'selected_teams':list(selected_teams)}
    RANKING_CACHE[cache_key]=result
    return result

def _rank_payload(engine, ranking_type, years=None, selected_teams=None, rank_engine=None, active_latest_players=None):
    selected=engine['all']; player_names=engine['players']; out=[]; selected_teams=set(selected_teams or [])
    rank_engine=rank_engine or engine
    if ranking_type in ('batters','bowlers','allrounders'):
        bat=selected['bat']; bowl=selected['bowl']; stats=selected['stats']; form=selected['form']
        for pid,st in stats.items():
            player_team_set=set(engine.get('player_team_history',{}).get(pid,[]))
            if selected_teams:
                team_seasons=engine.get('player_team_seasons',{}).get(pid,{})
                eligible_years=set(str(y) for y in (years or engine.get('years',[])))
                if years:
                    played_for_selected=any(set(team_seasons.get(team,[])) & eligible_years for team in selected_teams)
                else:
                    latest_year=str(engine.get('snapshot_year') or '')
                    played_for_selected=any(latest_year in set(team_seasons.get(team,[])) for team in selected_teams)
                if not played_for_selected: continue
            matches=int(st.get('matches',0)); sample=min(1.0,matches/8)
            if ranking_type=='batters':
                if matches<5 or st.get('innings',0)<4: continue
                rating=round(bat.get(pid,350)*sample+250*(1-sample)); avg=st.get('runs',0)/st.get('outs',1) if st.get('outs',0) else st.get('runs',0); sr=100*st.get('runs',0)/st.get('balls',1) if st.get('balls',0) else 0
                out.append({'player_id':pid,'name':player_names.get(pid,'Unknown'),'team':engine.get('player_teams',{}).get(pid,'Unknown'),'rating':rating,'matches':matches,'runs':int(st.get('runs',0)),'average':round(avg,2),'strike_rate':round(sr,2),'recent_form':_recent_form(form.get(pid,[]))})
            elif ranking_type=='bowlers':
                if matches<5 or st.get('bowl_balls',0)<48: continue
                rating=round(bowl.get(pid,350)*sample+250*(1-sample)); avg=st.get('bowl_runs',0)/st.get('wickets',1) if st.get('wickets',0) else 0; econ=st.get('bowl_runs',0)/(st.get('bowl_balls',0)/6) if st.get('bowl_balls',0) else 0
                out.append({'player_id':pid,'name':player_names.get(pid,'Unknown'),'team':engine.get('player_teams',{}).get(pid,'Unknown'),'rating':rating,'matches':matches,'wickets':int(st.get('wickets',0)),'average':round(avg,2),'economy':round(econ,2),'recent_form':_recent_form(form.get(pid,[]))})
            else:
                if matches<6 or st.get('innings',0)<3 or st.get('bowl_balls',0)<30: continue
                br=bat.get(pid,350); bor=bowl.get(pid,350); rating=round((br*bor/1000)*sample+80*(1-sample))
                out.append({'player_id':pid,'name':player_names.get(pid,'Unknown'),'team':engine.get('player_teams',{}).get(pid,'Unknown'),'rating':rating,'matches':matches,'runs':int(st.get('runs',0)),'wickets':int(st.get('wickets',0)),'batting_rating':round(br),'bowling_rating':round(bor)})
    else:
        stats=selected['team_stats']; ratings=selected['team']; team_bat=selected.get('team_bat',{}); team_bowl=selected.get('team_bowl',{}); titles=selected.get('titles',{})
        hidden_all_time={'Rising Pune Supergiant','Kochi Tuskers Kerala','Gujarat Lions','Deccan Chargers','Pune Warriors India'}
        eligible_teams=_display_eligibility_teams_from_engine(engine,years)
        for team,st in stats.items():
            if team not in eligible_teams: continue
            if selected_teams and team not in selected_teams: continue
            if st.get('matches',0)<5: continue
            if not years and team in hidden_all_time: continue
            won_years=titles.get(team,[])
            out.append({'name':team,'rating':round(ratings.get(team,500)),'batting_rating':round(team_bat.get(team,500)),'bowling_rating':round(team_bowl.get(team,500)),'matches':int(st.get('matches',0)),'wins':int(st.get('wins',0)),'losses':int(st.get('losses',0)),'win_pct':round(100*st.get('wins',0)/st.get('matches',1),1),'titles':len(won_years),'title_years':won_years})
    if ranking_type in ('batters','bowlers','allrounders') and active_latest_players is not None:
        out=[r for r in out if r.get('player_id') in active_latest_players]
    out.sort(key=lambda x:(-x['rating'],x['name']))
    if rank_engine is not engine or selected_teams:
        rank_source=rank_engine['all']; rank_stats=rank_source['stats']; rank_rows=[]
        if ranking_type=='batters':
            for pid,st in rank_stats.items():
                matches=int(st.get('matches',0)); sample=min(1.0,matches/8)
                if matches>=5 and st.get('innings',0)>=4: rank_rows.append((pid,round(rank_source['bat'].get(pid,350)*sample+250*(1-sample)),player_names.get(pid,'Unknown')))
        elif ranking_type=='bowlers':
            for pid,st in rank_stats.items():
                matches=int(st.get('matches',0)); sample=min(1.0,matches/8)
                if matches>=5 and st.get('bowl_balls',0)>=48: rank_rows.append((pid,round(rank_source['bowl'].get(pid,350)*sample+250*(1-sample)),player_names.get(pid,'Unknown')))
        elif ranking_type=='allrounders':
            for pid,st in rank_stats.items():
                matches=int(st.get('matches',0)); sample=min(1.0,matches/8)
                if matches>=6 and st.get('innings',0)>=3 and st.get('bowl_balls',0)>=30:
                    br=rank_source['bat'].get(pid,350); bor=rank_source['bowl'].get(pid,350); rank_rows.append((pid,round((br*bor/1000)*sample+80*(1-sample)),player_names.get(pid,'Unknown')))
        else:
            rank_eligible_teams=_display_eligibility_teams_from_engine(rank_engine,years)
            rank_rows=[(team,round(rank_source['team'].get(team,500)),team) for team,st in rank_source['team_stats'].items() if st.get('matches',0)>=5 and team in rank_eligible_teams]
        rank_rows.sort(key=lambda x:(-x[1],x[2]))
        rank_map={key:i for i,(key,_,_) in enumerate(rank_rows,1)}
        if ranking_type=='teams':
            for r in out: r['rank']=rank_map.get(r['name'])
        else:
            # Preserve the season-wide actual rank position while showing team-scoped contributions.
            for r in out: r['rank']=rank_map.get(r.get('player_id'))
        out.sort(key=lambda x:(x.get('rank') if x.get('rank') is not None else 999999,x['name']))
    else:
        for i,r in enumerate(out,1): r['rank']=i
    years=years or []
    label='all' if not years else ','.join(years)
    return {'type':ranking_type,'year':label,'years':years,'snapshot_year':engine.get('snapshot_year'),'eligible_count':len(out),'rankings':out[:100]}




def _display_eligibility_teams_from_engine(engine, years):
    selected={str(y) for y in (years or []) if str(y).strip()}
    if not selected:
        selected={str(engine.get('snapshot_year') or '')}
    matches,_,team_names,*_= _load_ranking_data(get_db()) if False else (None,None,None)
    # Team participation is retained in the engine's match history through team_stats only cumulatively,
    # so derive season participation directly from the cached source data attached to the engine when available.
    participation=engine.get('team_season_participation',{})
    return {team for team,seasons in participation.items() if set(map(str,seasons)) & selected}

def _latest_completed_ranking_season(c):
    years=[str(y) for y in _ranking_years(c)]
    return max(years,key=lambda x:int(x)) if years else None

def _display_eligibility_players(c, years):
    available=[str(y) for y in _ranking_years(c)]
    if not available: return set(),None
    selected=[str(y) for y in years] if years else [max(available,key=lambda x:int(x))]
    placeholders=','.join('?' for _ in selected)
    q=f"SELECT DISTINCT mp.player_id FROM match_players mp JOIN matches m ON m.match_id=mp.match_id WHERE CAST(m.year AS TEXT) IN ({placeholders})"
    return {r['player_id'] for r in rows(c.execute(q,tuple(selected)))},', '.join(selected)


@app.get('/api/rankings/player-search')
def rankings_player_search():
    ranking_type=request.args.get('type','batters').lower()
    q=request.args.get('q','').strip().lower()
    raw_years=request.args.get('years','all')
    raw_teams=request.args.get('teams','all')
    if ranking_type not in ('batters','bowlers','allrounders') or not q:
        return jsonify({'players':[]})
    requested=[] if raw_years in ('','all',None) else [y.strip() for y in str(raw_years).split(',') if y.strip()]
    requested_teams=[] if raw_teams in ('','all',None) else [canonical_team(t.strip()) for t in str(raw_teams).split(',') if t.strip()]
    c=db()
    try:
        valid={str(y) for y in _ranking_years(c)}
        years=[y for y in requested if y in valid]
        engine=_calculate_rankings(c,years,requested_teams if requested_teams else None)
        payload=_rank_payload(engine,ranking_type,years,requested_teams,rank_engine=_calculate_rankings(c,years),active_latest_players=_display_eligibility_players(c,years)[0])
        hits=[r for r in payload['rankings'] if q in r.get('name','').lower()][:10]
        return jsonify({'players':hits})
    finally: c.close()

@app.get('/api/rankings/filters')
def rankings_filters():
    c=db()
    try:
        team_rows=rows(c.execute("SELECT team_name FROM teams ORDER BY team_name"))
        teams=sorted({canonical_team(r['team_name']) for r in team_rows if r.get('team_name')})
        return jsonify({'years':_ranking_years(c),'teams':teams})
    finally: c.close()


@app.get('/api/rankings')
def rankings_api():
    ranking_type=request.args.get('type','batters').lower()
    raw=request.args.get('years',request.args.get('year','all'))
    raw_teams=request.args.get('teams','all')
    requested=[] if raw in ('','all',None) else [y.strip() for y in str(raw).split(',') if y.strip()]
    requested_teams=[] if raw_teams in ('','all',None) else [canonical_team(t.strip()) for t in str(raw_teams).split(',') if t.strip()]
    if ranking_type not in ('batters','bowlers','allrounders','teams'):
        return jsonify({'error':'Invalid ranking type'}),400
    c=db()
    try:
        valid={str(y) for y in _ranking_years(c)}
        valid_teams={canonical_team(r['team_name']) for r in rows(c.execute("SELECT team_name FROM teams")) if r.get('team_name')}
        years=[y for y in requested if y in valid]
        teams=[t for t in requested_teams if t in valid_teams]
        # Season filter defines the ranking universe. Team filter changes the player/team contribution scope without renumbering the season-wide rank positions.
        rank_engine=_calculate_rankings(c,years)
        active_latest_players=_display_eligibility_players(c,years)[0] if ranking_type in ('batters','bowlers','allrounders') else None
        # The ranking number is always the continuous end-of-period snapshot. Team filters only
        # constrain which rows are displayed; they never restart or distort the rating universe.
        return jsonify(_rank_payload(rank_engine,ranking_type,years,teams,rank_engine=rank_engine,active_latest_players=active_latest_players))
    except Exception as e:
        log.exception('Ranking engine error')
        return jsonify({'error':str(e)}),500
    finally: c.close()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
