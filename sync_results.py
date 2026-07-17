"""
Automatic result sync for the Tipovačka Premier League app.
 
Fetches finished Premier League matches from football-data.org (free tier)
and writes the final scores into the "Fixtures" tab of the Google Sheet —
the same sheet the Streamlit app reads. The app then recomputes points on
its own; nothing else needs to change.
 
Safety rules:
  * Only rows whose home_score AND away_score are still empty are touched.
    Anything the organiser entered by hand is never overwritten.
  * A fixture is matched to an API result by the (home, away) team pair,
    which is unique within one season, plus a kickoff-date sanity check
    (±3 days) so a wrong-season result can never slip in.
  * Unknown team names are logged, never guessed.
 
Environment variables (all required):
  FOOTBALL_DATA_TOKEN   free API token from https://www.football-data.org/client/register
  GCP_SERVICE_ACCOUNT_JSON  the full service-account JSON (same one the app uses)
  SPREADSHEET_ID        the Google Sheet ID (same as in the app's secrets)
 
Optional:
  FD_SEASON             season start year for the API query (default: 2026)
  DRY_RUN               set to "1" to log what would change without writing
"""
 
import json
import os
import sys
import tomllib
import unicodedata
from datetime import datetime, timedelta, timezone
 
import requests
import gspread
from google.oauth2.service_account import Credentials
 
API_BASE = "https://api.football-data.org/v4"
COMPETITION = "PL"  # Premier League
 
FIXTURES_HEADERS = ["round", "match_id", "kickoff", "home", "away", "home_score", "away_score"]
 
# ---------------------------------------------------------------------------
# Team-name mapping: sheet name  ->  aliases that may appear in the API
# (API "name", "shortName" and "tla" are all accepted, case-insensitively.)
# If the log reports an unmatched team, add its API name here.
# ---------------------------------------------------------------------------
TEAM_ALIASES = {
    "Arsenal":         {"arsenal fc", "arsenal", "ars"},
    "Aston Villa":     {"aston villa fc", "aston villa", "avl"},
    "Bournemouth":     {"afc bournemouth", "bournemouth", "bou"},
    "Brentford":       {"brentford fc", "brentford", "bre"},
    "Brighton":        {"brighton & hove albion fc", "brighton hove", "brighton", "bha"},
    "Chelsea":         {"chelsea fc", "chelsea", "che"},
    "Coventry":        {"coventry city fc", "coventry city", "coventry", "cov"},
    "Crystal Palace":  {"crystal palace fc", "crystal palace", "cry"},
    "Everton":         {"everton fc", "everton", "eve"},
    "Fulham":          {"fulham fc", "fulham", "ful"},
    "Hull":            {"hull city afc", "hull city", "hull", "hul"},
    "Ipswich":         {"ipswich town fc", "ipswich town", "ipswich", "ips"},
    "Leeds":           {"leeds united fc", "leeds united", "leeds", "lee"},
    "Liverpool":       {"liverpool fc", "liverpool", "liv"},
    "Manchester City": {"manchester city fc", "man city", "manchester city", "mci"},
    "Manchester Utd":  {"manchester united fc", "man united", "man utd", "manchester united", "mun"},
    "Newcastle":       {"newcastle united fc", "newcastle", "new"},
    "Nottingham":      {"nottingham forest fc", "nottingham forest", "nottingham", "nfo", "not"},
    "Sunderland":      {"sunderland afc", "sunderland", "sun"},
    "Tottenham":       {"tottenham hotspur fc", "tottenham", "tot"},
}
 
 
def norm(s):
    """Lowercase, trim, strip accents — tolerant comparison key."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())
 
 
# alias (normalised) -> canonical sheet name
ALIAS_TO_SHEET = {}
for sheet_name, aliases in TEAM_ALIASES.items():
    ALIAS_TO_SHEET[norm(sheet_name)] = sheet_name
    for a in aliases:
        ALIAS_TO_SHEET[norm(a)] = sheet_name
 
 
def sheet_team(api_team):
    """Map an API team object to the sheet's team name, or None."""
    for key in ("name", "shortName", "tla"):
        v = api_team.get(key)
        if v and norm(v) in ALIAS_TO_SHEET:
            return ALIAS_TO_SHEET[norm(v)]
    return None
 
 
def fetch_finished_matches(token, season):
    """All FINISHED PL matches of the season. One API call."""
    r = requests.get(
        f"{API_BASE}/competitions/{COMPETITION}/matches",
        headers={"X-Auth-Token": token},
        params={"status": "FINISHED", "season": season},
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("matches", [])
 
 
def parse_kickoff(s):
    """Parse the sheet's 'YYYY-MM-DDTHH:MM' kickoff (naive, Prague local)."""
    try:
        return datetime.strptime(str(s).strip(), "%Y-%m-%dT%H:%M")
    except ValueError:
        return None
 
 
def parse_service_account(raw):
    """
    Accept the service-account credentials as either:
      * plain JSON  — the .json key file from Google Cloud, or
      * TOML        — the [gcp_service_account] block copied from Streamlit secrets.
    """
    raw = raw.strip()
    if not raw:
        sys.exit("GCP_SERVICE_ACCOUNT_JSON secret is empty.")
    # 1) JSON key file
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # 2) Streamlit-style TOML
    try:
        data = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as e:
        sys.exit(
            "GCP_SERVICE_ACCOUNT_JSON secret is neither valid JSON nor valid TOML.\n"
            f"TOML parser said: {e}\n"
            "Paste either the .json key file content or the [gcp_service_account] "
            "block from Streamlit secrets."
        )
    # unwrap [gcp_service_account] (or any single section) if present
    if "gcp_service_account" in data:
        data = data["gcp_service_account"]
    elif "type" not in data and len(data) == 1 and isinstance(next(iter(data.values())), dict):
        data = next(iter(data.values()))
    if data.get("type") != "service_account":
        sys.exit("Parsed credentials don't look like a service account "
                 "(missing type='service_account').")
    return data
 
 
def main():
    token = os.environ["FOOTBALL_DATA_TOKEN"]
    sa_info = parse_service_account(os.environ["GCP_SERVICE_ACCOUNT_JSON"])
    spreadsheet_id = os.environ["SPREADSHEET_ID"]
    season = int(os.environ.get("FD_SEASON", "2026"))
    dry_run = os.environ.get("DRY_RUN") == "1"
 
    # --- API: finished matches, keyed by (home, away) sheet names ----------
    results = {}
    unmatched = set()
    for m in fetch_finished_matches(token, season):
        home = sheet_team(m.get("homeTeam", {}))
        away = sheet_team(m.get("awayTeam", {}))
        if not home or not away:
            if not home:
                unmatched.add(m.get("homeTeam", {}).get("name", "?"))
            if not away:
                unmatched.add(m.get("awayTeam", {}).get("name", "?"))
            continue
        ft = (m.get("score") or {}).get("fullTime") or {}
        hs, as_ = ft.get("home"), ft.get("away")
        if hs is None or as_ is None:
            continue
        utc = m.get("utcDate", "")
        try:
            ko = datetime.fromisoformat(utc.replace("Z", "+00:00"))
        except ValueError:
            ko = None
        results[(home, away)] = {"hs": int(hs), "as": int(as_), "utc": ko}
 
    if unmatched:
        print(f"NOTE: unknown API team names (extend TEAM_ALIASES): {sorted(unmatched)}")
    print(f"API: {len(results)} finished matches with usable scores.")
 
    # --- Sheet ------------------------------------------------------------
    creds = Credentials.from_service_account_info(
        sa_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    ws = gspread.authorize(creds).open_by_key(spreadsheet_id).worksheet("Fixtures")
    values = ws.get_all_values()
    if not values:
        sys.exit("Fixtures sheet is empty — nothing to do.")
 
    header = values[0]
    idx = {h: header.index(h) for h in FIXTURES_HEADERS if h in header}
    for req in ("home", "away", "home_score", "away_score", "kickoff"):
        if req not in idx:
            sys.exit(f"Fixtures sheet is missing the '{req}' column.")
 
    updates = []  # gspread Cell batch
    filled = []
    for row_no, row in enumerate(values[1:], start=2):  # 1-based, skip header
        def cell(col):
            i = idx[col]
            return row[i] if i < len(row) else ""
 
        if str(cell("home_score")).strip() != "" or str(cell("away_score")).strip() != "":
            continue  # already entered — never overwrite
 
        key = (str(cell("home")).strip(), str(cell("away")).strip())
        res = results.get(key)
        if not res:
            continue  # not played yet, or not in this API season
 
        # Sanity: sheet kickoff and API kickoff within 3 days of each other.
        sheet_ko = parse_kickoff(cell("kickoff"))
        if sheet_ko and res["utc"]:
            api_ko_naive = res["utc"].astimezone(timezone.utc).replace(tzinfo=None)
            if abs(api_ko_naive - sheet_ko) > timedelta(days=3):
                print(f"SKIP row {row_no} {key}: kickoff dates differ too much "
                      f"(sheet {sheet_ko}, API {api_ko_naive} UTC).")
                continue
 
        updates.append(gspread.cell.Cell(row_no, idx["home_score"] + 1, res["hs"]))
        updates.append(gspread.cell.Cell(row_no, idx["away_score"] + 1, res["as"]))
        filled.append(f"{key[0]} {res['hs']}:{res['as']} {key[1]} (row {row_no})")
 
    if not updates:
        print("Nothing new to write — all finished matches already have scores.")
        return
 
    for line in filled:
        print("WRITE:", line)
    if dry_run:
        print(f"DRY RUN — {len(filled)} results NOT written.")
        return
 
    ws.update_cells(updates, value_input_option="USER_ENTERED")
    print(f"Done: wrote {len(filled)} results.")
 
 
if __name__ == "__main__":
    main()
