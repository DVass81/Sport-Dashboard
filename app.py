from datetime import datetime, timedelta, timezone
from html import escape
import requests
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Sports Odds Command Center",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================================================
# CONFIG
# =========================================================
THESPORTSDB_API_KEY = st.secrets.get("THESPORTSDB_API_KEY", "")
SPORTSDATAIO_API_KEY = st.secrets.get("SPORTSDATAIO_API_KEY", "")

THESPORTSDB_V1_BASE = "https://www.thesportsdb.com/api/v1/json"
SPORTSDATAIO_BASE = "https://api.sportsdata.io/v3"

DEFAULT_LEAGUES = ["NBA", "MLB", "NHL"]
LEAGUE_CONFIG = {
    "NBA": {
        "sport_path": "nba",
        "display": "NBA",
    },
    "MLB": {
        "sport_path": "mlb",
        "display": "MLB",
    },
    "NHL": {
        "sport_path": "nhl",
        "display": "NHL",
    },
}

BOOK_URLS = {
    "DraftKings": "https://sportsbook.draftkings.com/",
    "FanDuel": "https://sportsbook.fanduel.com/",
    "BetMGM": "https://sports.betmgm.com/",
    "Caesars": "https://www.caesars.com/sportsbook-and-casino",
    "Bet365": "https://www.bet365.com/",
    "ESPN BET": "https://espnbet.com/",
    "Fanatics": "https://sportsbook.fanatics.com/",
    "Hard Rock": "https://www.hardrock.bet/",
    "betRivers": "https://www.betrivers.com/",
    "Consensus": "https://sportsdata.io/",
}

ALABAMA_SEARCH_NAME = "Alabama Crimson Tide"

# =========================================================
# REQUEST HELPERS
# =========================================================
def make_sdio_headers():
    return {
        "Ocp-Apim-Subscription-Key": SPORTSDATAIO_API_KEY,
        "User-Agent": "Mozilla/5.0",
    }


def make_basic_headers():
    return {
        "User-Agent": "Mozilla/5.0",
    }


def fmt_date(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


def safe_float(value):
    try:
        if value in (None, "", "None"):
            return None
        return float(value)
    except Exception:
        return None


def safe_int(value):
    try:
        if value in (None, "", "None"):
            return None
        return int(float(value))
    except Exception:
        return None


def first_nonempty(*values):
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return ""


def american_to_implied(odds_value):
    try:
        odds = int(float(odds_value))
    except Exception:
        return None

    if odds > 0:
        return round(100 / (odds + 100) * 100, 2)
    return round(abs(odds) / (abs(odds) + 100) * 100, 2)


def format_american_odds(odds):
    val = safe_int(odds)
    if val is None:
        return "—"
    return f"+{val}" if val > 0 else str(val)


def format_line_value(val):
    num = safe_float(val)
    if num is None:
        return "—"
    if num > 0:
        return f"+{num:g}"
    return f"{num:g}"


def make_link_markdown(url):
    if not url:
        return ""
    return f"[Open]({url})"


def confidence_from_score(score):
    if score >= 7.0:
        return "Elite"
    if score >= 5.0:
        return "High"
    if score >= 3.0:
        return "Medium"
    return "Low"


def confidence_badge_text(value):
    mapping = {
        "Elite": "🔵 Elite",
        "High": "🟢 High",
        "Medium": "🟡 Medium",
        "Low": "⚪ Low",
    }
    return mapping.get(value, str(value))


def move_badge_text(value):
    mapping = {
        "Improving": "📈 Improving",
        "Flat": "➖ Flat",
        "Worse": "📉 Worse",
        "New": "🆕 New",
    }
    return mapping.get(value, str(value))


def decision_badge_text(value):
    mapping = {
        "Within Limits": "✅ Within Limits",
        "Trimmed": "✂️ Trimmed",
        "Correlation Pass": "🚫 Correlation Pass",
        "Exposure Pass": "⛔ Exposure Pass",
        "Below Threshold": "⚪ Below Threshold",
        "Pending Review": "🕒 Pending Review",
    }
    return mapping.get(value, str(value))


def make_badge_html(text, variant):
    return f'<span class="badge badge-{variant}">{text}</span>'


def build_badges_html(row):
    conf_map = {"Elite": "elite", "High": "high", "Medium": "medium", "Low": "low"}
    move_map = {"Improving": "improving", "Flat": "flat", "Worse": "worse", "New": "new"}
    decision_map = {
        "Within Limits": "within",
        "Trimmed": "trimmed",
        "Correlation Pass": "blocked",
        "Exposure Pass": "blocked",
        "Below Threshold": "low",
        "Pending Review": "flat",
    }
    pieces = [
        make_badge_html(str(row.get("Confidence", "")), conf_map.get(row.get("Confidence", ""), "flat")),
        make_badge_html(str(row.get("Move Label", "")), move_map.get(row.get("Move Label", ""), "flat")),
        make_badge_html(str(row.get("Allocation Status", "")), decision_map.get(row.get("Allocation Status", ""), "flat")),
    ]
    return "".join(pieces)


def parse_game_datetime(game):
    date_candidates = [
        game.get("DateTime"),
        game.get("DateTimeUTC"),
        game.get("Day"),
    ]
    for raw in date_candidates:
        if not raw:
            continue
        try:
            txt = str(raw).replace("Z", "+00:00")
            dt = datetime.fromisoformat(txt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    return None


def display_game_time(dt):
    if dt is None:
        return "TBD"
    return dt.astimezone().strftime("%Y-%m-%d %I:%M %p")


def minutes_to_start(dt):
    if dt is None:
        return None
    now_utc = datetime.now(timezone.utc)
    return round((dt - now_utc).total_seconds() / 60, 1)


def format_minutes(value):
    if value is None or pd.isna(value):
        return "—"
    if value < 0:
        return "Live/Started"
    hours = int(value // 60)
    mins = int(value % 60)
    if hours == 0:
        return f"{mins}m"
    return f"{hours}h {mins}m"


def normalize_team_name(name):
    return str(name or "").strip().lower()


def watchlist_match(row, query):
    if not query:
        return False
    q = str(query).strip().lower()
    if not q:
        return False
    haystack = " ".join([
        str(row.get("Event", "")),
        str(row.get("Pick", "")),
        str(row.get("Market", "")),
        str(row.get("Sportsbook", "")),
        str(row.get("League", "")),
    ]).lower()
    return q in haystack


# =========================================================
# THESPORTSDB - ALABAMA BRANDING
# =========================================================
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_alabama_team():
    if not THESPORTSDB_API_KEY:
        return {}

    url = f"{THESPORTSDB_V1_BASE}/{THESPORTSDB_API_KEY}/searchteams.php"
    try:
        resp = requests.get(
            url,
            params={"t": ALABAMA_SEARCH_NAME},
            headers=make_basic_headers(),
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        teams = payload.get("teams") or []
        if not teams:
            return {}
        for team in teams:
            if "alabama" in str(team.get("strTeam", "")).lower():
                return team
        return teams[0]
    except Exception:
        return {}


# =========================================================
# SPORTSDATAIO - GAME + ODDS LOADERS
# =========================================================
@st.cache_data(ttl=300, show_spinner="Loading SportsDataIO odds...")
def fetch_games_for_league(league_name, date_str):
    cfg = LEAGUE_CONFIG.get(league_name)
    if not cfg or not SPORTSDATAIO_API_KEY:
        return []

    # Standard SportsDataIO score feed pattern
    url = f"{SPORTSDATAIO_BASE}/{cfg['sport_path']}/scores/json/GamesByDate/{date_str}"

    try:
        resp = requests.get(url, headers=make_sdio_headers(), timeout=25)
        resp.raise_for_status()
        payload = resp.json()
        return payload if isinstance(payload, list) else []
    except Exception:
        return []


@st.cache_data(ttl=300, show_spinner=False)
def fetch_games_window(selected_leagues, days_back=0, days_forward=2):
    all_games = []
    today = datetime.now().date()

    for league_name in selected_leagues:
        for offset in range(-days_back, days_forward + 1):
            target = datetime.combine(today + timedelta(days=offset), datetime.min.time())
            games = fetch_games_for_league(league_name, fmt_date(target))
            for game in games:
                game["_league"] = league_name
                all_games.append(game)

    return all_games


def sportsbook_name_from_odd(odd):
    return first_nonempty(
        odd.get("Sportsbook"),
        odd.get("SportsbookName"),
        odd.get("SportsbookOperator"),
        odd.get("Operator"),
        odd.get("BettingOperator"),
        "Sportsbook",
    )


def sportsbook_url(name):
    clean = str(name or "").strip()
    for key, url in BOOK_URLS.items():
        if clean.lower() == key.lower():
            return url
    return ""


def pick_game_status(game):
    return first_nonempty(
        game.get("Status"),
        game.get("GameStatus"),
        "Scheduled",
    )


def build_event_label(game):
    away = first_nonempty(game.get("AwayTeamName"), game.get("AwayTeam"), "Away")
    home = first_nonempty(game.get("HomeTeamName"), game.get("HomeTeam"), "Home")
    return f"{away} @ {home}"


def parse_odds_rows_from_game(game):
    rows = []

    league_name = game.get("_league", "")
    game_id = first_nonempty(game.get("GameID"), game.get("GlobalGameID"), game.get("GameId"))
    if not game_id:
        return rows

    event = build_event_label(game)
    away_team = first_nonempty(game.get("AwayTeamName"), game.get("AwayTeam"), "Away")
    home_team = first_nonempty(game.get("HomeTeamName"), game.get("HomeTeam"), "Home")
    dt = parse_game_datetime(game)
    start_display = display_game_time(dt)
    mins_to_start = minutes_to_start(dt)

    pregame_odds = game.get("PregameOdds") or []
    live_odds = game.get("LiveOdds") or []

    odds_sets = []
    if isinstance(pregame_odds, list):
        odds_sets.extend([("Pregame", odd) for odd in pregame_odds if isinstance(odd, dict)])
    if isinstance(live_odds, list):
        odds_sets.extend([("Live", odd) for odd in live_odds if isinstance(odd, dict)])

    for odds_kind, odd in odds_sets:
        sportsbook = sportsbook_name_from_odd(odd)
        book_url = sportsbook_url(sportsbook)

        away_ml = first_nonempty(odd.get("AwayMoneyLine"), odd.get("AwayMoneyline"))
        home_ml = first_nonempty(odd.get("HomeMoneyLine"), odd.get("HomeMoneyline"))

        away_spread = first_nonempty(odd.get("AwayPointSpread"), odd.get("AwaySpread"))
        home_spread = first_nonempty(odd.get("HomePointSpread"), odd.get("HomeSpread"))
        away_spread_price = first_nonempty(
            odd.get("AwayPointSpreadPayout"),
            odd.get("AwaySpreadPayout"),
            odd.get("AwayPointSpreadMoneyLine"),
        )
        home_spread_price = first_nonempty(
            odd.get("HomePointSpreadPayout"),
            odd.get("HomeSpreadPayout"),
            odd.get("HomePointSpreadMoneyLine"),
        )

        total = first_nonempty(odd.get("OverUnder"), odd.get("Total"))
        over_price = first_nonempty(odd.get("OverPayout"), odd.get("OverMoneyLine"))
        under_price = first_nonempty(odd.get("UnderPayout"), odd.get("UnderMoneyLine"))

        # Moneyline - away
        if safe_int(away_ml) is not None:
            rows.append({
                "Row Key": f"{game_id}|{sportsbook}|Moneyline|away|{odds_kind}",
                "Game ID": game_id,
                "League": league_name,
                "Event": event,
                "Home Team": home_team,
                "Away Team": away_team,
                "Start Time": start_display,
                "Minutes To Start": mins_to_start,
                "Status": pick_game_status(game),
                "Market": "Moneyline",
                "Market Bucket": "Moneyline",
                "Pick": away_team,
                "Sportsbook": sportsbook,
                "Odds": format_american_odds(away_ml),
                "American Odds Raw": safe_int(away_ml),
                "Line": "ML",
                "Implied Prob": american_to_implied(away_ml),
                "Odds Kind": odds_kind,
                "Link": book_url,
            })

        # Moneyline - home
        if safe_int(home_ml) is not None:
            rows.append({
                "Row Key": f"{game_id}|{sportsbook}|Moneyline|home|{odds_kind}",
                "Game ID": game_id,
                "League": league_name,
                "Event": event,
                "Home Team": home_team,
                "Away Team": away_team,
                "Start Time": start_display,
                "Minutes To Start": mins_to_start,
                "Status": pick_game_status(game),
                "Market": "Moneyline",
                "Market Bucket": "Moneyline",
                "Pick": home_team,
                "Sportsbook": sportsbook,
                "Odds": format_american_odds(home_ml),
                "American Odds Raw": safe_int(home_ml),
                "Line": "ML",
                "Implied Prob": american_to_implied(home_ml),
                "Odds Kind": odds_kind,
                "Link": book_url,
            })

        # Spread - away
        if safe_float(away_spread) is not None and safe_int(away_spread_price) is not None:
            rows.append({
                "Row Key": f"{game_id}|{sportsbook}|Spread|away|{odds_kind}",
                "Game ID": game_id,
                "League": league_name,
                "Event": event,
                "Home Team": home_team,
                "Away Team": away_team,
                "Start Time": start_display,
                "Minutes To Start": mins_to_start,
                "Status": pick_game_status(game),
                "Market": "Spread",
                "Market Bucket": "Spread",
                "Pick": away_team,
                "Sportsbook": sportsbook,
                "Odds": format_american_odds(away_spread_price),
                "American Odds Raw": safe_int(away_spread_price),
                "Line": format_line_value(away_spread),
                "Implied Prob": american_to_implied(away_spread_price),
                "Odds Kind": odds_kind,
                "Link": book_url,
            })

        # Spread - home
        if safe_float(home_spread) is not None and safe_int(home_spread_price) is not None:
            rows.append({
                "Row Key": f"{game_id}|{sportsbook}|Spread|home|{odds_kind}",
                "Game ID": game_id,
                "League": league_name,
                "Event": event,
                "Home Team": home_team,
                "Away Team": away_team,
                "Start Time": start_display,
                "Minutes To Start": mins_to_start,
                "Status": pick_game_status(game),
                "Market": "Spread",
                "Market Bucket": "Spread",
                "Pick": home_team,
                "Sportsbook": sportsbook,
                "Odds": format_american_odds(home_spread_price),
                "American Odds Raw": safe_int(home_spread_price),
                "Line": format_line_value(home_spread),
                "Implied Prob": american_to_implied(home_spread_price),
                "Odds Kind": odds_kind,
                "Link": book_url,
            })

        # Total - Over
        if safe_float(total) is not None and safe_int(over_price) is not None:
            rows.append({
                "Row Key": f"{game_id}|{sportsbook}|Total|over|{odds_kind}",
                "Game ID": game_id,
                "League": league_name,
                "Event": event,
                "Home Team": home_team,
                "Away Team": away_team,
                "Start Time": start_display,
                "Minutes To Start": mins_to_start,
                "Status": pick_game_status(game),
                "Market": "Total",
                "Market Bucket": "Total",
                "Pick": f"Over {format_line_value(total)}",
                "Sportsbook": sportsbook,
                "Odds": format_american_odds(over_price),
                "American Odds Raw": safe_int(over_price),
                "Line": format_line_value(total),
                "Implied Prob": american_to_implied(over_price),
                "Odds Kind": odds_kind,
                "Link": book_url,
            })

        # Total - Under
        if safe_float(total) is not None and safe_int(under_price) is not None:
            rows.append({
                "Row Key": f"{game_id}|{sportsbook}|Total|under|{odds_kind}",
                "Game ID": game_id,
                "League": league_name,
                "Event": event,
                "Home Team": home_team,
                "Away Team": away_team,
                "Start Time": start_display,
                "Minutes To Start": mins_to_start,
                "Status": pick_game_status(game),
                "Market": "Total",
                "Market Bucket": "Total",
                "Pick": f"Under {format_line_value(total)}",
                "Sportsbook": sportsbook,
                "Odds": format_american_odds(under_price),
                "American Odds Raw": safe_int(under_price),
                "Line": format_line_value(total),
                "Implied Prob": american_to_implied(under_price),
                "Odds Kind": odds_kind,
                "Link": book_url,
            })

    return rows


@st.cache_data(ttl=300, show_spinner=False)
def fetch_odds_board(selected_leagues):
    games = fetch_games_window(tuple(selected_leagues), days_back=0, days_forward=2)
    rows = []
    for game in games:
        rows.extend(parse_odds_rows_from_game(game))
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset=["Row Key"]).reset_index(drop=True)
    return df


# =========================================================
# SCORING + RISK
# =========================================================
def market_sort_value(bucket):
    order = {
        "Moneyline": 1,
        "Spread": 2,
        "Total": 3,
    }
    return order.get(bucket, 9)


def market_weight(bucket):
    weights = {
        "Moneyline": 1.25,
        "Spread": 1.20,
        "Total": 1.10,
    }
    return weights.get(bucket, 0.40)


def time_penalty(minutes):
    if minutes is None:
        return 0.0
    if minutes < 0:
        return -2.0
    if minutes < 15:
        return -1.3
    if minutes < 60:
        return -0.8
    if minutes < 180:
        return -0.3
    return 0.0


def bet_size_from_score(edge, score, min_bet, max_bet):
    if edge < 1.0 or score < 3.0:
        return 0
    if score < 4.0:
        return int(min_bet)
    if score < 5.0:
        return int(min(max_bet, max(min_bet, 3)))
    if score < 6.0:
        return int(min(max_bet, max(min_bet, 5)))
    if score < 7.0:
        return int(min(max_bet, max(min_bet, 7)))
    return int(min(max_bet, max(min_bet, 10)))


def build_reason(row):
    parts = []

    if row["Is Best Price"]:
        parts.append(f"best current price across {int(row['Books Quoting'])} books")
    else:
        parts.append(f"positive price edge vs {int(row['Books Quoting'])} book consensus")

    bucket = row["Market Bucket"]
    if bucket == "Moneyline":
        parts.append("moneyline market")
    elif bucket == "Spread":
        parts.append("spread market carries stronger confidence")
    elif bucket == "Total":
        parts.append("total market in board comparison")

    mins = row["Minutes To Start"]
    if mins is not None:
        if mins >= 180:
            parts.append("not too close to lock")
        elif mins >= 60:
            parts.append("moderate time before start")
        else:
            parts.append("close to start, so confidence is reduced")

    if row.get("Odds Kind") == "Live":
        parts.append("live odds feed")

    return " • ".join(parts)


def apply_smart_scoring(df, min_bet, max_bet):
    if df.empty:
        return df

    market_stats = (
        df.groupby(["Game ID", "Market", "Pick", "Line"])["Implied Prob"]
        .agg(["mean", "min", "max", "count", "std"])
        .reset_index()
        .rename(columns={
            "mean": "Consensus Prob",
            "min": "Best Price Prob",
            "max": "Worst Price Prob",
            "count": "Books Quoting",
            "std": "Prob StdDev",
        })
    )

    scored = df.merge(market_stats, on=["Game ID", "Market", "Pick", "Line"], how="left")
    scored["Prob StdDev"] = scored["Prob StdDev"].fillna(0.0)
    scored["Model Prob"] = scored["Consensus Prob"].round(2)
    scored["Edge %"] = (scored["Consensus Prob"] - scored["Implied Prob"]).round(2)
    scored["Best Line Gap %"] = (scored["Worst Price Prob"] - scored["Implied Prob"]).round(2)
    scored["Is Best Price"] = scored["Implied Prob"] <= (scored["Best Price Prob"] + 0.0001)

    scored["Market Weight"] = scored["Market Bucket"].apply(market_weight)
    scored["Time Penalty"] = scored["Minutes To Start"].apply(time_penalty)
    scored["Books Bonus"] = scored["Books Quoting"].apply(lambda x: min((x - 1) * 0.55, 2.20))

    scored["Bet Score"] = (
        scored["Edge %"] * 0.95
        + scored["Best Line Gap %"] * 0.35
        + scored["Books Bonus"]
        + scored["Market Weight"]
        + scored["Time Penalty"]
    ).round(2)

    scored["AI Score"] = scored["Bet Score"]
    scored["Confidence"] = scored["Bet Score"].apply(confidence_from_score)
    scored["Recommended Bet"] = scored.apply(
        lambda row: bet_size_from_score(row["Edge %"], row["Bet Score"], min_bet, max_bet),
        axis=1,
    )
    scored["Status"] = scored["Recommended Bet"].apply(lambda x: "Bet" if x > 0 else "No Bet")
    scored["Reason"] = scored.apply(build_reason, axis=1)
    scored["Market Rank"] = scored["Market Bucket"].apply(market_sort_value)
    scored["Rank Score"] = scored["Bet Score"]
    return scored


def apply_line_movement(df):
    if df.empty:
        return df

    if "line_snapshots" not in st.session_state:
        st.session_state["line_snapshots"] = {}

    snapshots = st.session_state["line_snapshots"]
    prev_odds = []
    move_values = []
    move_labels = []

    for _, row in df.iterrows():
        key = row["Row Key"]
        current_prob = float(row["Implied Prob"])
        current_odds = row["Odds"]
        previous = snapshots.get(key)

        if previous is None:
            prev_odds.append("—")
            move_values.append(0.0)
            move_labels.append("New")
        else:
            prev_odds.append(previous.get("odds", "—"))
            prev_prob = float(previous.get("implied_prob", current_prob))
            move = round(prev_prob - current_prob, 2)
            move_values.append(move)
            if move >= 1.0:
                move_labels.append("Improving")
            elif move <= -1.0:
                move_labels.append("Worse")
            else:
                move_labels.append("Flat")

        snapshots[key] = {
            "odds": current_odds,
            "implied_prob": current_prob,
        }

    moved = df.copy()
    moved["Prev Odds"] = prev_odds
    moved["Line Move %"] = move_values
    moved["Move Label"] = move_labels
    return moved


def build_allocation_note(row, note):
    base_reason = row.get("Reason", "")
    if base_reason and note:
        return f"{base_reason} • {note}"
    return base_reason or note


def apply_risk_controls(
    df,
    min_bet,
    max_total_exposure,
    max_league_exposure,
    max_event_exposure,
    max_book_exposure,
    use_correlation_guard,
):
    if df.empty:
        return df

    controlled = df.copy()
    controlled["Final Bet"] = 0
    controlled["Final Status"] = controlled["Status"]
    controlled["Allocation Status"] = controlled["Status"].map({"No Bet": "Below Threshold", "Bet": "Pending Review"}).fillna("Below Threshold")
    controlled["Pass Reason"] = ""

    total_used = 0.0
    league_used = {}
    event_used = {}
    book_used = {}
    selected_main = set()

    candidates = controlled[controlled["Status"] == "Bet"].sort_values(
        ["Rank Score", "Edge %", "Books Quoting", "Market Rank"],
        ascending=[False, False, False, True],
    )

    for idx, row in candidates.iterrows():
        event_key = f"{row['Game ID']}|{row['Market']}"
        if use_correlation_guard and event_key in selected_main:
            controlled.at[idx, "Final Status"] = "Pass"
            controlled.at[idx, "Allocation Status"] = "Correlation Pass"
            controlled.at[idx, "Pass Reason"] = build_allocation_note(row, "same-event market already selected")
            continue

        league = row["League"]
        book = row["Sportsbook"]
        game_id = row["Game ID"]
        recommended = float(row["Recommended Bet"])

        remaining_total = max_total_exposure - total_used
        remaining_league = max_league_exposure - league_used.get(league, 0.0)
        remaining_event = max_event_exposure - event_used.get(game_id, 0.0)
        remaining_book = max_book_exposure - book_used.get(book, 0.0)

        alloc = min(recommended, remaining_total, remaining_league, remaining_event, remaining_book)
        alloc = int(max(0, alloc))

        if alloc < min_bet:
            controlled.at[idx, "Final Status"] = "Pass"
            controlled.at[idx, "Allocation Status"] = "Exposure Pass"
            reasons = []
            if remaining_total < min_bet:
                reasons.append("total exposure cap reached")
            if remaining_league < min_bet:
                reasons.append("league cap reached")
            if remaining_event < min_bet:
                reasons.append("event cap reached")
            if remaining_book < min_bet:
                reasons.append("book cap reached")
            controlled.at[idx, "Pass Reason"] = build_allocation_note(row, ", ".join(reasons) if reasons else "allocation rules blocked this play")
            continue

        controlled.at[idx, "Final Bet"] = alloc
        controlled.at[idx, "Final Status"] = "Bet"
        controlled.at[idx, "Allocation Status"] = "Trimmed" if alloc < recommended else "Within Limits"
        controlled.at[idx, "Pass Reason"] = build_allocation_note(row, "stake trimmed by exposure rules" if alloc < recommended else "")

        total_used += alloc
        league_used[league] = league_used.get(league, 0.0) + alloc
        event_used[game_id] = event_used.get(game_id, 0.0) + alloc
        book_used[book] = book_used.get(book, 0.0) + alloc
        selected_main.add(event_key)

    return controlled


# =========================================================
# UI STYLING
# =========================================================
st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(180deg, #f5f8fc 0%, #edf3fb 100%);
        color: #142235;
    }

    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #edf5ff 0%, #e1ecfb 100%);
        border-right: 1px solid #c8d8ee;
    }

    .main-title {
        font-size: 2.8rem;
        font-weight: 900;
        color: #163b68;
        margin-bottom: 0.15rem;
    }

    .sub-title {
        font-size: 1rem;
        color: #476383;
        margin-bottom: 1rem;
    }

    .hero-box {
        background: linear-gradient(135deg, #ffffff 0%, #f6fbff 100%);
        border: 1px solid #cfe0f5;
        border-radius: 18px;
        padding: 20px 24px;
        margin-bottom: 18px;
        box-shadow: 0 10px 24px rgba(25, 60, 110, 0.10);
    }

    .alabama-card {
        background: linear-gradient(135deg, #ffffff 0%, #fff8fa 100%);
        border: 1px solid #eed4dd;
        border-left: 6px solid #9e1b32;
        border-radius: 18px;
        padding: 18px;
        box-shadow: 0 8px 20px rgba(60, 20, 30, 0.08);
        margin-bottom: 16px;
    }

    .card {
        background: #ffffff;
        border: 1px solid #d8e6f7;
        border-radius: 18px;
        padding: 18px;
        box-shadow: 0 8px 22px rgba(16, 46, 80, 0.08);
        margin-bottom: 16px;
    }

    .best-bet {
        background: linear-gradient(135deg, #f8fbff 0%, #eef6ff 100%);
        border: 1px solid #bdd5f1;
        border-left: 6px solid #2b73d5;
        border-radius: 18px;
        padding: 18px;
        box-shadow: 0 8px 22px rgba(16, 46, 80, 0.08);
        margin-bottom: 16px;
    }

    .section-title {
        font-size: 1.2rem;
        font-weight: 800;
        color: #173b67;
        margin-top: 8px;
        margin-bottom: 10px;
    }

    .kpi-card {
        background: linear-gradient(180deg, #ffffff 0%, #f6fbff 100%);
        border: 1px solid #d8e6f7;
        border-top: 4px solid #2b73d5;
        border-radius: 16px;
        padding: 14px 16px;
        box-shadow: 0 8px 18px rgba(16, 46, 80, 0.07);
        margin-bottom: 8px;
    }

    .kpi-label {
        color: #5f7b9a;
        font-size: 0.82rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: .3px;
    }

    .kpi-value {
        color: #163b68;
        font-size: 1.35rem;
        font-weight: 900;
        margin-top: 6px;
    }

    .book-link-card {
        background: linear-gradient(135deg, #ffffff 0%, #f3f8ff 100%);
        border: 1px solid #cfe1f7;
        border-top: 5px solid #2b73d5;
        border-radius: 18px;
        padding: 14px 14px 12px 14px;
        box-shadow: 0 10px 22px rgba(22, 59, 104, 0.09);
        min-height: 84px;
        margin-bottom: 10px;
    }

    .book-link-title {
        color: #173b67;
        font-size: 1rem;
        font-weight: 900;
        margin-bottom: 6px;
    }

    .book-link-sub {
        color: #5b7393;
        font-size: 0.86rem;
        font-weight: 600;
    }

    .badge {
        display: inline-block;
        padding: 5px 10px;
        border-radius: 999px;
        font-size: 0.78rem;
        font-weight: 800;
        margin: 6px 8px 4px 0;
        border: 1px solid transparent;
    }

    .badge-elite { background: #d9edff; color: #0f4d8a; border-color: #b7dafc; }
    .badge-high { background: #ddf7ea; color: #157347; border-color: #bde7d1; }
    .badge-medium { background: #fff4d8; color: #8a6100; border-color: #f2e0a8; }
    .badge-low { background: #eef3f8; color: #5b6f84; border-color: #d9e4ef; }
    .badge-improving { background: #dff7ea; color: #156f49; border-color: #bbe7cd; }
    .badge-flat { background: #edf3f9; color: #576f86; border-color: #d6e3ef; }
    .badge-worse { background: #fde6e8; color: #a53b47; border-color: #f6c5ca; }
    .badge-new { background: #e7edff; color: #415bb5; border-color: #cbd7ff; }
    .badge-within { background: #dff3ff; color: #155b9a; border-color: #b8ddfb; }
    .badge-trimmed { background: #fff1dd; color: #975d00; border-color: #f4dbb0; }
    .badge-blocked { background: #fde6e8; color: #a53b47; border-color: #f6c5ca; }

    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }

    .stTabs [data-baseweb="tab"] {
        background: rgba(255,255,255,0.82);
        border: 1px solid #d5e4f5;
        border-radius: 12px;
        color: #173b67;
        padding: 10px 14px;
        font-weight: 700;
    }

    .stTabs [aria-selected="true"] {
        background: #dfeeff !important;
        color: #163b68 !important;
    }

    div[data-baseweb="select"] > div,
    div[data-baseweb="base-input"] > div {
        color: black !important;
        background: #FFFFFF !important;
    }

    div[data-baseweb="select"] input,
    div[data-baseweb="base-input"] input {
        color: black !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================================================
# SIDEBAR
# =========================================================
st.sidebar.title("⚙️ Odds Controls")

bankroll = st.sidebar.number_input("Bankroll", min_value=1.0, value=500.0, step=25.0)
min_bet = st.sidebar.number_input("Minimum Bet", min_value=1.0, value=1.0, step=1.0)
max_bet = st.sidebar.number_input("Maximum Bet", min_value=1.0, value=10.0, step=1.0)

league_filter = st.sidebar.multiselect(
    "Leagues",
    options=DEFAULT_LEAGUES,
    default=DEFAULT_LEAGUES,
)

max_total_exposure = st.sidebar.number_input("Max Total Exposure", min_value=1.0, value=30.0, step=1.0)
max_league_exposure = st.sidebar.number_input("Max Exposure per League", min_value=1.0, value=12.0, step=1.0)
max_event_exposure = st.sidebar.number_input("Max Exposure per Event", min_value=1.0, value=8.0, step=1.0)
max_book_exposure = st.sidebar.number_input("Max Exposure per Sportsbook", min_value=1.0, value=12.0, step=1.0)
correlation_guard = st.sidebar.toggle("Correlation Protection", value=True)
watchlist_query = st.sidebar.text_input("Watchlist filter", placeholder="Lakers, Yankees, totals...")
watchlist_only = st.sidebar.toggle("Show watchlist matches only", value=False)
only_final_bets = st.sidebar.toggle("Show final bets only", value=False)

if st.sidebar.button("Refresh now"):
    st.cache_data.clear()
    st.rerun()

# =========================================================
# HEADER
# =========================================================
if not SPORTSDATAIO_API_KEY:
    st.error("Missing SPORTSDATAIO_API_KEY in Streamlit secrets.")
    st.stop()

st.markdown('<div class="main-title">🏈 Sports Odds Command Center</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">Build 1: SportsDataIO odds integration with Alabama branding restored at the top.</div>',
    unsafe_allow_html=True,
)

# Alabama hero
alabama = fetch_alabama_team()
c1, c2 = st.columns([1, 3])

with c1:
    alabama_badge = first_nonempty(alabama.get("strBadge"), alabama.get("strLogo"))
    if alabama_badge:
        st.image(alabama_badge, use_container_width=True)

with c2:
    st.markdown('<div class="alabama-card">', unsafe_allow_html=True)
    st.markdown(f"### {first_nonempty(alabama.get('strTeam'), 'Alabama Crimson Tide')}")
    st.markdown(
        f"""
        **Featured Program Card**  
        League: {first_nonempty(alabama.get('strLeague'), 'NCAA')}  
        Stadium: {first_nonempty(alabama.get('strStadium'), '—')}  
        Location: {first_nonempty(alabama.get('strLocation'), 'Tuscaloosa, Alabama')}
        """
    )
    desc = str(first_nonempty(alabama.get("strDescriptionEN"), ""))
    if desc:
        st.markdown(desc[:320] + ("..." if len(desc) > 320 else ""))
    else:
        st.markdown("Alabama branding is live. Next look build can make this section much more premium.")
    st.markdown('</div>', unsafe_allow_html=True)

# Quick links
st.markdown('<div class="section-title">Quick Sportsbook Links</div>', unsafe_allow_html=True)
link_cols = st.columns(5)
quick_books = [
    ("DraftKings", "🟩", "Major-book price check"),
    ("FanDuel", "🟦", "Sharp public comparison"),
    ("BetMGM", "🟨", "National book"),
    ("Caesars", "🟥", "Book comparison"),
    ("Bet365", "🟢", "Alt-line option"),
]
for col, (book, icon, sub) in zip(link_cols, quick_books):
    with col:
        st.markdown(
            f"""
            <div class="book-link-card">
                <div class="book-link-title">{icon} {book}</div>
                <div class="book-link-sub">{sub}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        try:
            st.link_button(f"Open {book}", BOOK_URLS[book], use_container_width=True)
        except Exception:
            st.markdown(f"[Open {book}]({BOOK_URLS[book]})")

# =========================================================
# DATA PIPELINE
# =========================================================
raw_df = fetch_odds_board(league_filter)

if raw_df.empty:
    st.warning("No SportsDataIO odds came back for the selected leagues.")
    st.info("First thing to check: confirm your SportsDataIO package includes the odds feeds for those leagues.")
    st.stop()

book_options = sorted([b for b in raw_df["Sportsbook"].dropna().unique().tolist() if str(b).strip()])
default_books = [b for b in ["DraftKings", "FanDuel", "BetMGM", "Bet365", "Caesars"] if b in book_options]
if not default_books:
    default_books = book_options[:5] if len(book_options) >= 5 else book_options

book_filter = st.sidebar.multiselect(
    "Sportsbooks",
    options=book_options,
    default=default_books,
)

scored_df = apply_smart_scoring(raw_df, min_bet=min_bet, max_bet=max_bet)
moved_df = apply_line_movement(scored_df)

filtered_df = moved_df[moved_df["Sportsbook"].isin(book_filter)].copy()
filtered_df = apply_risk_controls(
    filtered_df,
    min_bet=min_bet,
    max_total_exposure=max_total_exposure,
    max_league_exposure=max_league_exposure,
    max_event_exposure=max_event_exposure,
    max_book_exposure=max_book_exposure,
    use_correlation_guard=correlation_guard,
)

filtered_df["Watchlist Match"] = filtered_df.apply(lambda row: watchlist_match(row, watchlist_query), axis=1)
filtered_df["Watchlist Label"] = filtered_df["Watchlist Match"].map({True: "⭐ Watchlist", False: ""})

if watchlist_only and str(watchlist_query).strip():
    filtered_df = filtered_df[filtered_df["Watchlist Match"]].copy()

if only_final_bets:
    filtered_df = filtered_df[filtered_df["Final Status"] == "Bet"].copy()

status_order = {"Bet": 2, "Pass": 1, "No Bet": 0}
filtered_df["Status Rank"] = filtered_df["Final Status"].map(status_order).fillna(0)
filtered_df = filtered_df.sort_values(
    ["Status Rank", "AI Score", "Edge %", "Books Quoting", "Market Rank"],
    ascending=[False, False, False, False, True],
)

live_bets = filtered_df[filtered_df["Final Status"] == "Bet"].copy()
best_row = live_bets.iloc[0] if not live_bets.empty else None

best_edge = float(live_bets["Edge %"].max()) if not live_bets.empty else 0.0
avg_edge = float(live_bets["Edge %"].mean()) if not live_bets.empty else 0.0
avg_score = float(live_bets["AI Score"].mean()) if not live_bets.empty else 0.0
open_risk = int(live_bets["Final Bet"].sum()) if not live_bets.empty else 0
active_bets = int(len(live_bets))
refresh_time = datetime.now().astimezone().strftime("%Y-%m-%d %I:%M:%S %p")
improving_count = int((live_bets["Move Label"] == "Improving").sum()) if not live_bets.empty else 0
watchlist_hits = int(filtered_df["Watchlist Match"].sum()) if "Watchlist Match" in filtered_df.columns else 0
strong_shop = int((live_bets["Best Line Gap %"] >= 3.0).sum()) if not live_bets.empty else 0
exposure_by_league = live_bets.groupby("League")["Final Bet"].sum().sort_values(ascending=False) if not live_bets.empty else pd.Series(dtype=float)

# =========================================================
# HERO + KPI
# =========================================================
st.markdown('<div class="hero-box">', unsafe_allow_html=True)
hero_left, hero_right = st.columns([2, 1])

with hero_left:
    st.markdown("### Current Top Bet")
    if best_row is not None:
        st.markdown(
            f"""
            **{best_row['Pick']}**  
            {best_row['Event']} · {best_row['Market']} · {best_row['Start Time']}  
            Book: **{best_row['Sportsbook']}** · Odds: **{best_row['Odds']}** · Previous: **{best_row['Prev Odds']}**  
            Edge: **{best_row['Edge %']:.2f}%** · Score: **{best_row['AI Score']:.2f}** · Final Bet: **${int(best_row['Final Bet'])}**  
            Line: **{best_row['Line']}** · Move: **{best_row['Line Move %']:+.2f}%**  
            Reason: *{best_row['Pass Reason'] or best_row['Reason']}*
            """,
            unsafe_allow_html=False,
        )
        st.markdown(build_badges_html(best_row), unsafe_allow_html=True)
        if best_row["Link"]:
            st.markdown(f"[Open book]({best_row['Link']})")
    else:
        st.info("No bets qualify right now under the current rules.")

with hero_right:
    st.markdown("**Refresh**")
    st.markdown(refresh_time)
    st.markdown("**Loaded leagues**")
    st.markdown(", ".join(league_filter))
    st.markdown("**Books loaded**")
    st.markdown(str(len(book_options)))

st.markdown("</div>", unsafe_allow_html=True)

def kpi_card(label, value):
    st.markdown(
        f'<div class="kpi-card"><div class="kpi-label">{label}</div><div class="kpi-value">{value}</div></div>',
        unsafe_allow_html=True,
    )

k1, k2, k3, k4, k5, k6, k7, k8 = st.columns(8)
with k1:
    kpi_card("Final Bets", active_bets)
with k2:
    kpi_card("Best Edge", f"{best_edge:.2f}%")
with k3:
    kpi_card("Average Edge", f"{avg_edge:.2f}%")
with k4:
    kpi_card("Average Score", f"{avg_score:.2f}")
with k5:
    kpi_card("Open Risk", f"${open_risk}")
with k6:
    kpi_card("Strong Shop", strong_shop)
with k7:
    kpi_card("Improving", improving_count)
with k8:
    kpi_card("Watchlist Hits", watchlist_hits)

# =========================================================
# TABS
# =========================================================
tabs = st.tabs(["Home", "Odds Board", "Best Bets", "Game Slate", "Bankroll"])

with tabs[0]:
    st.markdown('<div class="section-title">Build 1 Snapshot</div>', unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("**Average AI score by sportsbook**")
        if live_bets.empty:
            st.info("No chart data available.")
        else:
            st.bar_chart(live_bets.groupby("Sportsbook")["AI Score"].mean().sort_values(ascending=False))
        st.markdown('</div>', unsafe_allow_html=True)

    with c2:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("**Open exposure by league**")
        if exposure_by_league.empty:
            st.info("No chart data available.")
        else:
            st.bar_chart(exposure_by_league)
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown(
        """
        **What this build restores**
        - real sportsbook odds feed
        - moneyline, spread, and total markets
        - best-price comparison by market
        - bet ranking and exposure rules
        - Alabama Crimson Tide branding at the top
        
        **Next look build**
        - make the Alabama hero section premium
        - upgrade the best-bet cards
        - add team logos on game rows
        - clean up spacing and visual hierarchy
        """
    )
    st.markdown('</div>', unsafe_allow_html=True)

with tabs[1]:
    st.markdown('<div class="section-title">Odds Board</div>', unsafe_allow_html=True)

    display_df = filtered_df.copy()
    display_df["Link"] = display_df["Link"].apply(make_link_markdown)
    display_df["Minutes To Start"] = display_df["Minutes To Start"].apply(format_minutes)
    display_df["Confidence Tag"] = display_df["Confidence"].apply(confidence_badge_text)
    display_df["Move Tag"] = display_df["Move Label"].apply(move_badge_text)
    display_df["Decision Tag"] = display_df["Allocation Status"].apply(decision_badge_text)

    display_df = display_df[
        [
            "League",
            "Event",
            "Start Time",
            "Status",
            "Market",
            "Pick",
            "Sportsbook",
            "Line",
            "Prev Odds",
            "Odds",
            "Odds Kind",
            "Watchlist Label",
            "Confidence Tag",
            "Move Tag",
            "Decision Tag",
            "Line Move %",
            "Implied Prob",
            "Model Prob",
            "Edge %",
            "Best Line Gap %",
            "Books Quoting",
            "Bet Score",
            "AI Score",
            "Recommended Bet",
            "Final Bet",
            "Allocation Status",
            "Final Status",
            "Pass Reason",
            "Link",
        ]
    ]

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Implied Prob": st.column_config.NumberColumn(format="%.2f%%"),
            "Model Prob": st.column_config.NumberColumn(format="%.2f%%"),
            "Line Move %": st.column_config.NumberColumn(format="%.2f"),
            "Edge %": st.column_config.NumberColumn(format="%.2f%%"),
            "Best Line Gap %": st.column_config.NumberColumn(format="%.2f%%"),
            "Bet Score": st.column_config.NumberColumn(format="%.2f"),
            "AI Score": st.column_config.NumberColumn(format="%.2f"),
            "Recommended Bet": st.column_config.NumberColumn(format="$%d"),
            "Final Bet": st.column_config.NumberColumn(format="$%d"),
            "Link": st.column_config.LinkColumn("Open"),
        },
    )

with tabs[2]:
    st.markdown('<div class="section-title">Best Bets</div>', unsafe_allow_html=True)

    top_df = live_bets.head(5)
    if top_df.empty:
        st.info("No final bets available right now.")
    else:
        for _, row in top_df.iterrows():
            st.markdown(
                f"""
                <div class="best-bet">
                    <b>{row['Pick']}</b><br>
                    {row['Event']} · {row['Market']} · {row['Start Time']}<br>
                    Book: <b>{row['Sportsbook']}</b> · Odds: <b>{row['Odds']}</b> · Prev: <b>{row['Prev Odds']}</b><br>
                    Edge: <b>{row['Edge %']:.2f}%</b> · Score: <b>{row['AI Score']:.2f}</b> · Confidence: <b>{row['Confidence']}</b><br>
                    Final Bet: <b>${int(row['Final Bet'])}</b> · Line: <b>{row['Line']}</b> · Move: <b>{row['Line Move %']:+.2f}% ({row['Move Label']})</b><br>
                    Decision: <b>{row['Allocation Status']}</b> {row['Watchlist Label']}<br>
                    {build_badges_html(row)}<br>
                    Reason: <i>{row['Pass Reason'] or row['Reason']}</i>
                </div>
                """,
                unsafe_allow_html=True,
            )

with tabs[3]:
    st.markdown('<div class="section-title">Game Slate</div>', unsafe_allow_html=True)

    slate = (
        raw_df[["League", "Event", "Start Time", "Status", "Sportsbook"]]
        .drop_duplicates(subset=["League", "Event", "Start Time", "Status"])
        .sort_values(["League", "Start Time", "Event"])
        .reset_index(drop=True)
    )
    st.dataframe(slate, use_container_width=True, hide_index=True)

with tabs[4]:
    st.markdown('<div class="section-title">Bankroll + Exposure Rules</div>', unsafe_allow_html=True)

    caps_df = pd.DataFrame(
        {
            "Rule": [
                "Total Exposure",
                "Per League",
                "Per Event",
                "Per Sportsbook",
            ],
            "Cap": [
                f"${max_total_exposure:.0f}",
                f"${max_league_exposure:.0f}",
                f"${max_event_exposure:.0f}",
                f"${max_book_exposure:.0f}",
            ],
        }
    )
    st.dataframe(caps_df, use_container_width=True, hide_index=True)

    if not exposure_by_league.empty:
        st.markdown("**Current open exposure by league**")
        st.bar_chart(exposure_by_league)
