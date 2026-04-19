import os
import uuid
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st


# -----------------------------
# PAGE CONFIG
# -----------------------------
st.set_page_config(
    page_title="Sports Betting Dashboard",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)

TARGET_BOOKS = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "bet365": "Bet365",
    "prizepicks": "PrizePicks",
}

BOOK_URLS = {
    "DraftKings": "https://sportsbook.draftkings.com/",
    "FanDuel": "https://sportsbook.fanduel.com/",
    "Bet365": "https://www.bet365.com/",
    "PrizePicks": "https://app.prizepicks.com/",
}

DEFAULT_LEAGUES = ["NBA", "NFL", "MLB", "NHL"]
BET_LOG_FILE = "bet_log.csv"
SNAPSHOT_FILE = "odds_snapshots.csv"

BET_LOG_COLUMNS = [
    "Bet ID",
    "Logged At",
    "Settled At",
    "Sport",
    "Event",
    "Event ID",
    "Odd ID",
    "Market Bucket",
    "Market",
    "Pick",
    "Sportsbook",
    "Odds",
    "Stake",
    "Implied Prob",
    "Model Prob",
    "Edge %",
    "Bet Score",
    "Confidence",
    "Reason",
    "Start Time",
    "Link",
    "Bet Status",
    "Result",
    "PNL",
]

SNAPSHOT_COLUMNS = [
    "Snapshot Key",
    "Event ID",
    "Odd ID",
    "Sportsbook",
    "First Seen At",
    "Last Seen At",
    "First Odds",
    "Prev Odds",
    "Current Odds",
    "First Implied Prob",
    "Prev Implied Prob",
    "Current Implied Prob",
]


# -----------------------------
# STYLING
# -----------------------------
st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(180deg, #eef4fb 0%, #e7eef8 100%);
        color: #0f172a;
    }

    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #f7fbff 0%, #edf4fc 100%);
        border-right: 1px solid rgba(15, 23, 42, 0.08);
    }

    .main-title {
        font-size: 2.4rem;
        font-weight: 900;
        color: #0f172a;
        margin-bottom: 0.15rem;
        letter-spacing: 0.2px;
    }

    .sub-title {
        font-size: 1rem;
        color: #334155;
        margin-bottom: 1rem;
    }

    .hero-box {
        background: linear-gradient(135deg, #e0efff 0%, #d9e9fb 100%);
        border: 1px solid rgba(37, 99, 235, 0.15);
        border-radius: 22px;
        padding: 18px 22px;
        margin-bottom: 18px;
        box-shadow: 0 12px 24px rgba(15, 23, 42, 0.08);
    }

    .soft-card {
        background: #ffffff;
        border: 1px solid rgba(15, 23, 42, 0.08);
        border-radius: 18px;
        padding: 16px 18px;
        box-shadow: 0 10px 20px rgba(15, 23, 42, 0.06);
        margin-bottom: 14px;
    }

    .bet-card {
        background: linear-gradient(135deg, #ffffff 0%, #f6fbff 100%);
        border: 1px solid rgba(37, 99, 235, 0.14);
        border-radius: 18px;
        padding: 16px 18px;
        box-shadow: 0 8px 18px rgba(37, 99, 235, 0.08);
        margin-bottom: 12px;
    }

    .section-title {
        font-size: 1.22rem;
        font-weight: 800;
        color: #0f172a;
        margin-top: 6px;
        margin-bottom: 10px;
    }

    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 12px;
        margin-bottom: 16px;
    }

    .kpi-card {
        background: #ffffff;
        border: 1px solid rgba(15, 23, 42, 0.08);
        border-radius: 16px;
        padding: 14px 16px;
        box-shadow: 0 8px 18px rgba(15, 23, 42, 0.05);
    }

    .kpi-label {
        color: #475569;
        font-size: 0.88rem;
        margin-bottom: 6px;
    }

    .kpi-value {
        color: #0f172a;
        font-size: 1.35rem;
        font-weight: 900;
    }

    .pill {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 999px;
        font-size: 0.78rem;
        font-weight: 700;
        margin-right: 6px;
        margin-bottom: 6px;
    }

    .pill-blue { background: #dbeafe; color: #1d4ed8; }
    .pill-green { background: #dcfce7; color: #15803d; }
    .pill-yellow { background: #fef3c7; color: #a16207; }
    .pill-red { background: #fee2e2; color: #b91c1c; }
    .pill-slate { background: #e2e8f0; color: #334155; }

    .quick-link-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 12px;
        margin-bottom: 12px;
    }

    .quick-link-card {
        background: #ffffff;
        border: 1px solid rgba(15, 23, 42, 0.08);
        border-radius: 18px;
        padding: 18px;
        box-shadow: 0 10px 20px rgba(15, 23, 42, 0.06);
        text-align: center;
    }

    .quick-link-card a {
        text-decoration: none;
        color: #0f172a;
        font-weight: 800;
    }

    div[data-baseweb="select"] > div,
    div[data-baseweb="base-input"] > div,
    div[data-baseweb="textarea"] > div {
        color: #0f172a !important;
        background: #ffffff !important;
    }

    div[data-baseweb="select"] input,
    div[data-baseweb="base-input"] input,
    textarea {
        color: #0f172a !important;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }

    .stTabs [data-baseweb="tab"] {
        background: rgba(255,255,255,0.75);
        border: 1px solid rgba(15, 23, 42, 0.08);
        border-radius: 12px;
        color: #0f172a;
        padding: 10px 14px;
    }

    .stTabs [aria-selected="true"] {
        background: #dbeafe !important;
        color: #1d4ed8 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# -----------------------------
# FILE HELPERS
# -----------------------------
def ensure_csv_file(path: str, columns: list[str]) -> None:
    if not os.path.exists(path):
        pd.DataFrame(columns=columns).to_csv(path, index=False)


def load_bet_log() -> pd.DataFrame:
    ensure_csv_file(BET_LOG_FILE, BET_LOG_COLUMNS)
    try:
        df = pd.read_csv(BET_LOG_FILE)
    except Exception:
        df = pd.DataFrame(columns=BET_LOG_COLUMNS)

    for col in ["Stake", "Implied Prob", "Model Prob", "Edge %", "Bet Score", "PNL"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return df


def save_bet_log(df: pd.DataFrame) -> None:
    df.to_csv(BET_LOG_FILE, index=False)


def load_snapshots() -> pd.DataFrame:
    ensure_csv_file(SNAPSHOT_FILE, SNAPSHOT_COLUMNS)
    try:
        df = pd.read_csv(SNAPSHOT_FILE)
    except Exception:
        df = pd.DataFrame(columns=SNAPSHOT_COLUMNS)
    for col in ["First Implied Prob", "Prev Implied Prob", "Current Implied Prob"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def save_snapshots(df: pd.DataFrame) -> None:
    df.to_csv(SNAPSHOT_FILE, index=False)


# -----------------------------
# BASIC HELPERS
# -----------------------------
def american_to_implied(odds_value):
    try:
        odds_str = str(odds_value).strip().replace("−", "-")
        odds = int(odds_str)
    except Exception:
        return None

    if odds > 0:
        return round(100 / (odds + 100) * 100, 2)
    return round(abs(odds) / (abs(odds) + 100) * 100, 2)


def american_profit(odds_value, stake):
    try:
        odds = int(str(odds_value).strip().replace("−", "-"))
        stake = float(stake)
    except Exception:
        return 0.0

    if odds > 0:
        return round(stake * (odds / 100), 2)
    return round(stake * (100 / abs(odds)), 2)


def safe_team_name(team_dict, fallback):
    if not isinstance(team_dict, dict):
        return fallback
    names = team_dict.get("names", {})
    return names.get("medium") or names.get("long") or names.get("short") or fallback


def safe_player_name(players, stat_entity_id):
    if not isinstance(players, dict):
        return str(stat_entity_id).replace("_", " ").title()
    player = players.get(stat_entity_id, {})
    return player.get("name") or str(stat_entity_id).replace("_", " ").title()


def parse_iso_datetime(value):
    if not value:
        return None
    try:
        txt = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def minutes_to_start(value):
    dt = parse_iso_datetime(value)
    if dt is None:
        return None
    now_utc = datetime.now(timezone.utc)
    return round((dt - now_utc).total_seconds() / 60, 1)


def format_pct(val):
    try:
        return f"{float(val):.2f}%"
    except Exception:
        return ""


def pill_class_for_confidence(value: str) -> str:
    mapping = {"Elite": "pill-blue", "High": "pill-green", "Medium": "pill-yellow", "Low": "pill-red"}
    return mapping.get(value, "pill-slate")


def pill_class_for_movement(value: str) -> str:
    mapping = {"Improving": "pill-green", "Worse": "pill-red", "Flat": "pill-slate", "New": "pill-blue"}
    return mapping.get(value, "pill-slate")


def pill_class_for_final_status(value: str) -> str:
    mapping = {"Bet": "pill-green", "Pass": "pill-yellow", "No Bet": "pill-red"}
    return mapping.get(value, "pill-slate")


def classify_market(market_name, pick, sportsbook):
    text = f"{market_name} {pick}".lower()
    if sportsbook == "PrizePicks":
        return "DFS Prop"
    if "moneyline" in text or text.strip() in {"ml", "winner"}:
        return "Moneyline"
    if "spread" in text or "run line" in text or "puck line" in text or "handicap" in text:
        return "Spread"
    if "total" in text or "over " in text or "under " in text:
        return "Total"
    if "team total" in text:
        return "Team Total"
    if "player" in text or "points" in text or "rebounds" in text or "assists" in text:
        return "Player Prop"
    return "Other"


def build_pick_label(odd, quote, home_name, away_name, players):
    side_id = str(odd.get("sideID", "") or "")
    stat_entity_id = str(odd.get("statEntityID", "") or "")
    market_name = str(odd.get("marketName", "") or "Market")
    simple_entities = {"all", "home", "away", "draw", "home+draw", "away+draw"}

    if quote.get("overUnder") is not None:
        line = quote.get("overUnder")
        if stat_entity_id not in simple_entities:
            player_name = safe_player_name(players, stat_entity_id)
            return f"{player_name} {side_id.title()} {line}"
        return f"{side_id.title()} {line}"

    if quote.get("spread") is not None:
        line = quote.get("spread")
        if stat_entity_id == "home" or side_id == "home":
            target = home_name
        elif stat_entity_id == "away" or side_id == "away":
            target = away_name
        else:
            target = stat_entity_id.replace("_", " ").title()
        return f"{target} {line}"

    if stat_entity_id == "home" or side_id == "home":
        return home_name
    if stat_entity_id == "away" or side_id == "away":
        return away_name
    if side_id == "draw":
        return "Draw"
    if side_id == "home+draw":
        return f"{home_name} or Draw"
    if side_id == "away+draw":
        return f"{away_name} or Draw"

    if stat_entity_id not in simple_entities:
        player_name = safe_player_name(players, stat_entity_id)
        if side_id in {"yes", "no"}:
            return f"{player_name} {side_id.title()}"
        return player_name

    if side_id in {"yes", "no"}:
        return side_id.title()

    return market_name


# -----------------------------
# LIVE ODDS FETCH
# -----------------------------
@st.cache_data(ttl=900, show_spinner="Loading live odds...")
def fetch_events(leagues):
    api_key = st.secrets.get("SPORTS_GAME_ODDS_API_KEY", "")
    if not api_key:
        return [], "Missing SPORTS_GAME_ODDS_API_KEY in Streamlit secrets."

    url = "https://api.sportsgameodds.com/v2/events/"
    headers = {"x-api-key": api_key}
    params = {
        "leagueID": ",".join(leagues),
        "oddsAvailable": "true",
        "limit": 100,
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=25)
        response.raise_for_status()
        payload = response.json()
        events = payload.get("data", []) if isinstance(payload, dict) else payload
        return events, ""
    except Exception as exc:
        return [], f"API error: {exc}"


def flatten_events_to_rows(events):
    rows = []
    for event in events:
        event_id = event.get("eventID", "")
        league_id = event.get("leagueID", "")
        sport_id = event.get("sportID", "")
        status = event.get("status", {}) or {}
        teams = event.get("teams", {}) or {}
        players = event.get("players", {}) or {}
        event_links = (event.get("links", {}) or {}).get("bookmakers", {}) or {}
        odds_map = event.get("odds", {}) or {}

        home_name = safe_team_name(teams.get("home", {}), "Home")
        away_name = safe_team_name(teams.get("away", {}), "Away")
        event_name = f"{away_name} @ {home_name}"
        starts_at = status.get("startsAt", "")

        for odd_id, odd in odds_map.items():
            by_bookmaker = odd.get("byBookmaker", {}) or {}
            market_name = odd.get("marketName", "") or "Market"

            for book_id, quote in by_bookmaker.items():
                if book_id not in TARGET_BOOKS:
                    continue
                if not isinstance(quote, dict):
                    continue
                if quote.get("available") is False:
                    continue

                odds_value = quote.get("odds")
                implied_prob = american_to_implied(odds_value)
                if implied_prob is None:
                    continue

                pick_label = build_pick_label(
                    odd=odd,
                    quote=quote,
                    home_name=home_name,
                    away_name=away_name,
                    players=players,
                )

                rows.append(
                    {
                        "Event ID": event_id,
                        "Odd ID": odd_id,
                        "Sport": league_id or sport_id,
                        "Event": event_name,
                        "Start Time": starts_at,
                        "Minutes To Start": minutes_to_start(starts_at),
                        "Market": market_name,
                        "Market Bucket": classify_market(market_name, pick_label, TARGET_BOOKS[book_id]),
                        "Pick": pick_label,
                        "Sportsbook": TARGET_BOOKS[book_id],
                        "Sportsbook ID": book_id,
                        "Odds": str(odds_value),
                        "Implied Prob": implied_prob,
                        "Line": quote.get("spread") or quote.get("overUnder") or "",
                        "Last Update": quote.get("lastUpdatedAt", ""),
                        "Link": quote.get("deeplink") or event_links.get(book_id, ""),
                    }
                )
    return pd.DataFrame(rows)


# -----------------------------
# SNAPSHOTS / LINE MOVEMENT
# -----------------------------
def update_snapshot_tracking(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    snapshots = load_snapshots()
    now_str = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")

    out = df.copy()
    first_odds_list = []
    prev_odds_list = []
    current_odds_list = []
    movement_label_list = []
    movement_delta_list = []

    for _, row in out.iterrows():
        snapshot_key = f"{row['Event ID']}|{row['Odd ID']}|{row['Sportsbook']}"
        implied = float(row["Implied Prob"])

        match = snapshots[snapshots["Snapshot Key"].astype(str) == snapshot_key]
        if match.empty:
            new_snapshot = {
                "Snapshot Key": snapshot_key,
                "Event ID": row["Event ID"],
                "Odd ID": row["Odd ID"],
                "Sportsbook": row["Sportsbook"],
                "First Seen At": now_str,
                "Last Seen At": now_str,
                "First Odds": row["Odds"],
                "Prev Odds": row["Odds"],
                "Current Odds": row["Odds"],
                "First Implied Prob": implied,
                "Prev Implied Prob": implied,
                "Current Implied Prob": implied,
            }
            snapshots = pd.concat([snapshots, pd.DataFrame([new_snapshot])], ignore_index=True)
            first_odds_list.append(row["Odds"])
            prev_odds_list.append(row["Odds"])
            current_odds_list.append(row["Odds"])
            movement_label_list.append("New")
            movement_delta_list.append(0.0)
        else:
            idx = match.index[0]
            prev_implied = snapshots.at[idx, "Current Implied Prob"]
            prev_odds = snapshots.at[idx, "Current Odds"]

            snapshots.at[idx, "Prev Odds"] = prev_odds
            snapshots.at[idx, "Prev Implied Prob"] = prev_implied
            snapshots.at[idx, "Current Odds"] = row["Odds"]
            snapshots.at[idx, "Current Implied Prob"] = implied
            snapshots.at[idx, "Last Seen At"] = now_str

            delta = round(float(prev_implied) - implied, 2)
            if delta > 0.15:
                movement = "Improving"
            elif delta < -0.15:
                movement = "Worse"
            else:
                movement = "Flat"

            first_odds_list.append(snapshots.at[idx, "First Odds"])
            prev_odds_list.append(prev_odds)
            current_odds_list.append(row["Odds"])
            movement_label_list.append(movement)
            movement_delta_list.append(delta)

    save_snapshots(snapshots)
    out["First Odds Seen"] = first_odds_list
    out["Previous Odds"] = prev_odds_list
    out["Current Odds"] = current_odds_list
    out["Movement"] = movement_label_list
    out["Movement Delta %"] = movement_delta_list
    return out


# -----------------------------
# SCORING
# -----------------------------
def confidence_from_score(score):
    if score >= 7:
        return "Elite"
    if score >= 5:
        return "High"
    if score >= 3:
        return "Medium"
    return "Low"


def market_weight(bucket):
    weights = {
        "Moneyline": 1.25,
        "Spread": 1.20,
        "Total": 1.10,
        "Team Total": 0.85,
        "Player Prop": 0.60,
        "DFS Prop": 0.35,
        "Other": 0.40,
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


def book_penalty(book_name):
    return -0.6 if book_name == "PrizePicks" else 0.0


def movement_bonus(label):
    mapping = {"Improving": 0.40, "Flat": 0.0, "Worse": -0.45, "New": 0.10}
    return mapping.get(label, 0.0)


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


def apply_smart_scoring(df: pd.DataFrame, min_bet: float, max_bet: float) -> pd.DataFrame:
    if df.empty:
        return df

    market_stats = (
        df.groupby(["Event ID", "Odd ID"])["Implied Prob"]
        .agg(["mean", "min", "max", "count", "std"])
        .reset_index()
        .rename(
            columns={
                "mean": "Consensus Prob",
                "min": "Best Price Prob",
                "max": "Worst Price Prob",
                "count": "Books Quoting",
                "std": "Prob StdDev",
            }
        )
    )

    scored = df.merge(market_stats, on=["Event ID", "Odd ID"], how="left")
    scored["Prob StdDev"] = scored["Prob StdDev"].fillna(0.0)
    scored["Model Prob"] = scored["Consensus Prob"].round(2)
    scored["Edge %"] = (scored["Consensus Prob"] - scored["Implied Prob"]).round(2)
    scored["Best Line Gap %"] = (scored["Worst Price Prob"] - scored["Implied Prob"]).round(2)
    scored["Is Best Price"] = scored["Implied Prob"] <= (scored["Best Price Prob"] + 0.0001)
    scored["Books Bonus"] = scored["Books Quoting"].apply(lambda x: min((x - 1) * 0.55, 2.20))
    scored["Market Weight"] = scored["Market Bucket"].apply(market_weight)
    scored["Time Penalty"] = scored["Minutes To Start"].apply(time_penalty)
    scored["Book Penalty"] = scored["Sportsbook"].apply(book_penalty)
    scored["Movement Bonus"] = scored["Movement"].apply(movement_bonus)

    scored["Bet Score"] = (
        scored["Edge %"] * 0.95
        + scored["Best Line Gap %"] * 0.35
        + scored["Books Bonus"]
        + scored["Market Weight"]
        + scored["Time Penalty"]
        + scored["Book Penalty"]
        + scored["Movement Bonus"]
    ).round(2)

    scored["Confidence"] = scored["Bet Score"].apply(confidence_from_score)
    scored["Recommended Bet"] = scored.apply(
        lambda row: bet_size_from_score(row["Edge %"], row["Bet Score"], min_bet, max_bet),
        axis=1,
    )
    scored["Status"] = scored["Recommended Bet"].apply(lambda x: "Bet" if x > 0 else "No Bet")

    def reason(row):
        parts = []
        if row["Is Best Price"]:
            parts.append(f"best current price across {int(row['Books Quoting'])} books")
        else:
            parts.append(f"positive edge vs {int(row['Books Quoting'])}-book consensus")
        parts.append(f"{row['Market Bucket'].lower()} market weight applied")
        if row["Movement"] == "Improving":
            parts.append("price moved in your favor")
        elif row["Movement"] == "Worse":
            parts.append("price moved against you")
        if row["Minutes To Start"] is not None and row["Minutes To Start"] < 60:
            parts.append("close to lock reduced confidence")
        if row["Sportsbook"] == "PrizePicks":
            parts.append("PrizePicks handled more conservatively")
        return " • ".join(parts)

    scored["Reason"] = scored.apply(reason, axis=1)
    return scored


# -----------------------------
# EXPOSURE + CORRELATION
# -----------------------------
def apply_risk_controls(
    df: pd.DataFrame,
    min_bet: float,
    max_total_exposure: float,
    max_sport_exposure: float,
    max_event_exposure: float,
    max_book_exposure: float,
    max_prop_exposure: float,
    max_event_props: int,
) -> pd.DataFrame:
    out = df.copy()
    out["Final Bet"] = 0
    out["Final Status"] = "No Bet"
    out["Allocation Status"] = "Not Qualified"
    out["Pass Reason"] = ""

    if out.empty:
        return out

    total_used = 0.0
    sport_used = {}
    event_used = {}
    book_used = {}
    prop_used = 0.0
    event_main_used = set()
    event_prop_counts = {}

    candidates = out[out["Status"] == "Bet"].sort_values(
        ["Bet Score", "Edge %", "Books Quoting"],
        ascending=[False, False, False],
    )

    for idx, row in candidates.iterrows():
        suggested = float(row["Recommended Bet"])
        if suggested < min_bet:
            out.at[idx, "Final Status"] = "Pass"
            out.at[idx, "Allocation Status"] = "Below Minimum"
            out.at[idx, "Pass Reason"] = "Recommended size below minimum"
            continue

        event_id = str(row["Event ID"])
        sport = str(row["Sport"])
        book = str(row["Sportsbook"])
        market_bucket = str(row["Market Bucket"])
        is_prop = market_bucket in {"Player Prop", "DFS Prop"}

        if total_used + min_bet > max_total_exposure:
            out.at[idx, "Final Status"] = "Pass"
            out.at[idx, "Allocation Status"] = "Exposure Cap"
            out.at[idx, "Pass Reason"] = "Max total exposure reached"
            continue

        if sport_used.get(sport, 0.0) + min_bet > max_sport_exposure:
            out.at[idx, "Final Status"] = "Pass"
            out.at[idx, "Allocation Status"] = "Sport Cap"
            out.at[idx, "Pass Reason"] = f"Max exposure reached for {sport}"
            continue

        if event_used.get(event_id, 0.0) + min_bet > max_event_exposure:
            out.at[idx, "Final Status"] = "Pass"
            out.at[idx, "Allocation Status"] = "Event Cap"
            out.at[idx, "Pass Reason"] = "Max exposure reached for this event"
            continue

        if book_used.get(book, 0.0) + min_bet > max_book_exposure:
            out.at[idx, "Final Status"] = "Pass"
            out.at[idx, "Allocation Status"] = "Book Cap"
            out.at[idx, "Pass Reason"] = f"Max exposure reached for {book}"
            continue

        if is_prop and prop_used + min_bet > max_prop_exposure:
            out.at[idx, "Final Status"] = "Pass"
            out.at[idx, "Allocation Status"] = "Prop Cap"
            out.at[idx, "Pass Reason"] = "Max prop exposure reached"
            continue

        if market_bucket in {"Moneyline", "Spread", "Total", "Team Total"}:
            if event_id in event_main_used:
                out.at[idx, "Final Status"] = "Pass"
                out.at[idx, "Allocation Status"] = "Correlation Pass"
                out.at[idx, "Pass Reason"] = "Correlated main-market bet already selected in this event"
                continue

        if is_prop and event_prop_counts.get(event_id, 0) >= max_event_props:
            out.at[idx, "Final Status"] = "Pass"
            out.at[idx, "Allocation Status"] = "Correlation Pass"
            out.at[idx, "Pass Reason"] = "Too many props already selected in this event"
            continue

        remaining_limits = [
            max_total_exposure - total_used,
            max_sport_exposure - sport_used.get(sport, 0.0),
            max_event_exposure - event_used.get(event_id, 0.0),
            max_book_exposure - book_used.get(book, 0.0),
        ]
        if is_prop:
            remaining_limits.append(max_prop_exposure - prop_used)

        final_size = int(min(suggested, *remaining_limits))
        if final_size < min_bet:
            out.at[idx, "Final Status"] = "Pass"
            out.at[idx, "Allocation Status"] = "Trimmed Out"
            out.at[idx, "Pass Reason"] = "Risk controls trimmed this bet below minimum size"
            continue

        out.at[idx, "Final Bet"] = final_size
        out.at[idx, "Final Status"] = "Bet"
        out.at[idx, "Allocation Status"] = "Trimmed" if final_size < suggested else "Approved"

        total_used += final_size
        sport_used[sport] = sport_used.get(sport, 0.0) + final_size
        event_used[event_id] = event_used.get(event_id, 0.0) + final_size
        book_used[book] = book_used.get(book, 0.0) + final_size
        if is_prop:
            prop_used += final_size
            event_prop_counts[event_id] = event_prop_counts.get(event_id, 0) + 1
        else:
            event_main_used.add(event_id)

    return out.sort_values(
        ["Final Status", "Bet Score", "Edge %"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


# -----------------------------
# COMPARE LINES
# -----------------------------
def build_compare_lines(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    group_cols = ["Event ID", "Odd ID", "Sport", "Event", "Market Bucket", "Market", "Pick"]

    pivot_df = (
        df.pivot_table(index=group_cols, columns="Sportsbook", values="Odds", aggfunc="first")
        .reset_index()
    )

    best_rows = df.loc[df.groupby(["Event ID", "Odd ID"])["Implied Prob"].idxmin()].copy()
    best_rows = best_rows.rename(
        columns={
            "Sportsbook": "Best Book",
            "Odds": "Best Odds",
            "Final Bet": "Best Final Bet",
            "Final Status": "Best Final Status",
            "Confidence": "Best Confidence",
            "Bet Score": "Best Score",
            "Link": "Best Link",
            "Reason": "Best Reason",
        }
    )[
        [
            "Event ID",
            "Odd ID",
            "Best Book",
            "Best Odds",
            "Best Final Bet",
            "Best Final Status",
            "Best Confidence",
            "Best Score",
            "Best Link",
            "Best Reason",
        ]
    ]

    price_stats = (
        df.groupby(group_cols)["Implied Prob"]
        .agg(["min", "max", "count"])
        .reset_index()
        .rename(columns={"min": "Best Price Prob", "max": "Worst Price Prob", "count": "Books Quoting"})
    )
    price_stats["Line Gap %"] = (price_stats["Worst Price Prob"] - price_stats["Best Price Prob"]).round(2)

    compare = pivot_df.merge(price_stats, on=group_cols, how="left").merge(best_rows, on=["Event ID", "Odd ID"], how="left")
    for book_name in BOOK_URLS:
        if book_name not in compare.columns:
            compare[book_name] = ""

    def shop_alert(row):
        if row["Books Quoting"] >= 3 and row["Line Gap %"] >= 4:
            return "Strong Shop"
        if row["Books Quoting"] >= 2 and row["Line Gap %"] >= 2:
            return "Good Shop"
        if row["Line Gap %"] > 0:
            return "Small Edge"
        return "Flat"

    compare["Shop Alert"] = compare.apply(shop_alert, axis=1)
    return compare.sort_values(["Best Score", "Line Gap %"], ascending=[False, False]).reset_index(drop=True)


# -----------------------------
# WATCHLIST
# -----------------------------
def apply_watchlist_labels(df: pd.DataFrame, watchlist_terms: list[str]) -> pd.DataFrame:
    out = df.copy()
    if not watchlist_terms:
        out["Watchlist Match"] = ""
        return out

    def match_row(row):
        haystack = f"{row['Sport']} {row['Event']} {row['Pick']} {row['Market']}".lower()
        matches = [term for term in watchlist_terms if term and term in haystack]
        return ", ".join(matches[:3])

    out["Watchlist Match"] = out.apply(match_row, axis=1)
    return out


# -----------------------------
# BET LOGGING
# -----------------------------
def log_bet_from_row(row: pd.Series):
    log_df = load_bet_log()
    duplicate_mask = (
        (log_df["Event"].astype(str) == str(row["Event"]))
        & (log_df["Pick"].astype(str) == str(row["Pick"]))
        & (log_df["Sportsbook"].astype(str) == str(row["Sportsbook"]))
        & (log_df["Odds"].astype(str) == str(row["Odds"]))
        & (log_df["Bet Status"].astype(str) == "Pending")
    )
    if duplicate_mask.any():
        return False, "That bet is already logged as pending."

    bet_id = str(uuid.uuid4())[:8].upper()
    new_row = {
        "Bet ID": bet_id,
        "Logged At": datetime.now().strftime("%Y-%m-%d %I:%M:%S %p"),
        "Settled At": "",
        "Sport": row["Sport"],
        "Event": row["Event"],
        "Event ID": row["Event ID"],
        "Odd ID": row["Odd ID"],
        "Market Bucket": row["Market Bucket"],
        "Market": row["Market"],
        "Pick": row["Pick"],
        "Sportsbook": row["Sportsbook"],
        "Odds": row["Odds"],
        "Stake": float(row["Final Bet"]),
        "Implied Prob": float(row["Implied Prob"]),
        "Model Prob": float(row["Model Prob"]),
        "Edge %": float(row["Edge %"]),
        "Bet Score": float(row["Bet Score"]),
        "Confidence": row["Confidence"],
        "Reason": row["Reason"],
        "Start Time": row["Start Time"],
        "Link": row["Link"],
        "Bet Status": "Pending",
        "Result": "",
        "PNL": 0.0,
    }
    log_df = pd.concat([log_df, pd.DataFrame([new_row])], ignore_index=True)
    save_bet_log(log_df)
    return True, f"Bet logged successfully. Bet ID: {bet_id}"


def settle_bet(bet_id: str, result: str):
    log_df = load_bet_log()
    if log_df.empty:
        return False, "No bet history found."

    mask = log_df["Bet ID"].astype(str) == str(bet_id)
    if not mask.any():
        return False, "Bet ID not found."

    idx = log_df.index[mask][0]
    stake = float(log_df.at[idx, "Stake"])
    odds = str(log_df.at[idx, "Odds"])

    if result == "Win":
        pnl = american_profit(odds, stake)
    elif result == "Loss":
        pnl = round(-stake, 2)
    else:
        pnl = 0.0

    log_df.at[idx, "Result"] = result
    log_df.at[idx, "PNL"] = pnl
    log_df.at[idx, "Bet Status"] = "Settled"
    log_df.at[idx, "Settled At"] = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
    save_bet_log(log_df)
    return True, f"Bet {bet_id} settled as {result}. PNL: ${pnl:,.2f}"


# -----------------------------
# OPENAI ASSISTANT
# -----------------------------
def call_openai_assistant(user_prompt: str, context_text: str) -> str:
    api_key = st.secrets.get("OPENAI_API_KEY", "")
    model = st.secrets.get("OPENAI_MODEL", "gpt-4.1-mini")

    if not api_key:
        return "Add OPENAI_API_KEY to Streamlit secrets to use the AI assistant."

    system_prompt = (
        "You are an assistant inside a sports betting dashboard. "
        "Be practical, concise, and risk-aware. Do not promise wins. "
        "Use the supplied dashboard context only. "
        "Explain edge, confidence, sportsbook value, and bankroll discipline clearly."
    )

    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"DASHBOARD CONTEXT:\n{context_text}\n\nUSER REQUEST:\n{user_prompt}"},
        ],
    }

    try:
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=45,
        )
        response.raise_for_status()
        data = response.json()

        if isinstance(data.get("output_text"), str) and data.get("output_text").strip():
            return data["output_text"].strip()

        pieces = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    pieces.append(content.get("text", ""))
        text = "\n".join(piece for piece in pieces if piece).strip()
        return text or "The AI assistant returned an empty response."
    except Exception as exc:
        return f"AI request failed: {exc}"


def summarize_dashboard_context(df: pd.DataFrame, compare_df: pd.DataFrame) -> str:
    if df.empty:
        return "No live rows are currently available."

    final_bets = df[df["Final Status"] == "Bet"].copy().head(8)
    lines = []
    lines.append(f"Total live rows: {len(df)}")
    lines.append(f"Final bets: {len(df[df['Final Status'] == 'Bet'])}")
    lines.append(f"Strong shop alerts: {len(compare_df[compare_df['Shop Alert'] == 'Strong Shop']) if not compare_df.empty else 0}")
    for _, row in final_bets.iterrows():
        lines.append(
            f"- {row['Sport']} | {row['Event']} | {row['Pick']} | {row['Sportsbook']} {row['Odds']} | "
            f"Edge {row['Edge %']:.2f}% | Score {row['Bet Score']:.2f} | Final Bet ${int(row['Final Bet'])} | "
            f"Movement {row['Movement']} | Reason: {row['Reason']}"
        )
    return "\n".join(lines)


# -----------------------------
# MAIN PIPELINE
# -----------------------------
st.markdown('<div class="main-title">Sports Betting Dashboard</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">Cleaner look, sharper controls, compare-lines workflow, tracking, results, bankroll, and optional AI help.</div>',
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### Controls")
    bankroll = st.number_input("Starting Bankroll", min_value=1.0, value=500.0, step=25.0, key="sb_bankroll")
    min_bet = st.number_input("Minimum Bet", min_value=1.0, value=1.0, step=1.0, key="sb_min_bet")
    max_bet = st.number_input("Maximum Bet", min_value=1.0, value=10.0, step=1.0, key="sb_max_bet")

    st.markdown("### Risk Controls")
    max_total_exposure = st.number_input("Max Total Exposure", min_value=1.0, value=40.0, step=5.0, key="sb_total_exp")
    max_sport_exposure = st.number_input("Max Exposure Per Sport", min_value=1.0, value=20.0, step=1.0, key="sb_sport_exp")
    max_event_exposure = st.number_input("Max Exposure Per Event", min_value=1.0, value=10.0, step=1.0, key="sb_event_exp")
    max_book_exposure = st.number_input("Max Exposure Per Sportsbook", min_value=1.0, value=15.0, step=1.0, key="sb_book_exp")
    max_prop_exposure = st.number_input("Max Prop Exposure", min_value=1.0, value=12.0, step=1.0, key="sb_prop_exp")
    max_event_props = st.number_input("Max Props Per Event", min_value=1, value=2, step=1, key="sb_event_props")

    st.markdown("### Filters")
    league_filter = st.multiselect("Leagues", options=DEFAULT_LEAGUES, default=DEFAULT_LEAGUES, key="sb_leagues")
    book_filter = st.multiselect(
        "Sportsbooks",
        options=list(BOOK_URLS.keys()),
        default=list(BOOK_URLS.keys()),
        key="sb_books",
    )
    market_filter = st.multiselect(
        "Market Types",
        options=["Moneyline", "Spread", "Total", "Team Total", "Player Prop", "DFS Prop", "Other"],
        default=["Moneyline", "Spread", "Total", "Team Total", "Player Prop", "DFS Prop", "Other"],
        key="sb_markets",
    )
    confidence_filter = st.multiselect(
        "Confidence",
        options=["Elite", "High", "Medium", "Low"],
        default=["Elite", "High", "Medium", "Low"],
        key="sb_conf",
    )
    watchlist_text = st.text_input(
        "Watchlist Terms",
        value="",
        help="Comma-separated teams, players, or keywords.",
        key="sb_watchlist_terms",
    )
    only_final_bets = st.toggle("Show final bets only", value=False, key="sb_only_final")
    if st.button("Refresh Data", key="sb_refresh"):
        st.cache_data.clear()
        st.rerun()

watchlist_terms = [term.strip().lower() for term in watchlist_text.split(",") if term.strip()]

events, fetch_error = fetch_events(league_filter)
if fetch_error:
    st.warning(fetch_error)
    st.stop()

raw_df = flatten_events_to_rows(events)
if raw_df.empty:
    st.warning("No live odds came back for the selected leagues.")
    st.stop()

tracked_df = update_snapshot_tracking(raw_df)
scored_df = apply_smart_scoring(tracked_df, min_bet=min_bet, max_bet=max_bet)

filtered_df = scored_df[
    scored_df["Sportsbook"].isin(book_filter)
    & scored_df["Market Bucket"].isin(market_filter)
    & scored_df["Confidence"].isin(confidence_filter)
].copy()

controlled_df = apply_risk_controls(
    filtered_df,
    min_bet=min_bet,
    max_total_exposure=max_total_exposure,
    max_sport_exposure=max_sport_exposure,
    max_event_exposure=max_event_exposure,
    max_book_exposure=max_book_exposure,
    max_prop_exposure=max_prop_exposure,
    max_event_props=max_event_props,
)

controlled_df = apply_watchlist_labels(controlled_df, watchlist_terms)

if only_final_bets:
    display_df = controlled_df[controlled_df["Final Status"] == "Bet"].copy()
else:
    display_df = controlled_df.copy()

display_df = display_df.reset_index(drop=True)
compare_df = build_compare_lines(controlled_df)

bet_log_df = load_bet_log()
pending_df = bet_log_df[bet_log_df["Bet Status"] == "Pending"].copy()
settled_df = bet_log_df[bet_log_df["Bet Status"] == "Settled"].copy()
graded_df = settled_df[settled_df["Result"].isin(["Win", "Loss"])].copy()

realized_pnl = float(settled_df["PNL"].sum()) if not settled_df.empty else 0.0
current_bankroll = bankroll + realized_pnl
open_logged_risk = float(pending_df["Stake"].sum()) if not pending_df.empty else 0.0
open_live_risk = float(controlled_df[controlled_df["Final Status"] == "Bet"]["Final Bet"].sum()) if not controlled_df.empty else 0.0
roi = (realized_pnl / float(settled_df["Stake"].sum()) * 100) if not settled_df.empty and float(settled_df["Stake"].sum()) > 0 else 0.0
win_rate = ((graded_df["Result"] == "Win").mean() * 100) if not graded_df.empty else 0.0
strong_shop_alerts = int((compare_df["Shop Alert"] == "Strong Shop").sum()) if not compare_df.empty else 0
final_bets_count = int((controlled_df["Final Status"] == "Bet").sum()) if not controlled_df.empty else 0
avg_edge = float(controlled_df[controlled_df["Final Status"] == "Bet"]["Edge %"].mean()) if final_bets_count else 0.0
avg_score = float(controlled_df[controlled_df["Final Status"] == "Bet"]["Bet Score"].mean()) if final_bets_count else 0.0

top_bet_row = None
top_bets_df = controlled_df[controlled_df["Final Status"] == "Bet"].copy()
if not top_bets_df.empty:
    top_bet_row = top_bets_df.sort_values(["Bet Score", "Edge %"], ascending=[False, False]).iloc[0]

kpi_html = f"""
<div class="kpi-grid">
  <div class="kpi-card"><div class="kpi-label">Current Bankroll</div><div class="kpi-value">${current_bankroll:,.2f}</div></div>
  <div class="kpi-card"><div class="kpi-label">Realized P/L</div><div class="kpi-value">${realized_pnl:,.2f}</div></div>
  <div class="kpi-card"><div class="kpi-label">ROI</div><div class="kpi-value">{roi:.1f}%</div></div>
  <div class="kpi-card"><div class="kpi-label">Win Rate</div><div class="kpi-value">{win_rate:.1f}%</div></div>
  <div class="kpi-card"><div class="kpi-label">Open Live Risk</div><div class="kpi-value">${open_live_risk:,.0f}</div></div>
  <div class="kpi-card"><div class="kpi-label">Final Bets</div><div class="kpi-value">{final_bets_count}</div></div>
  <div class="kpi-card"><div class="kpi-label">Strong Shop Alerts</div><div class="kpi-value">{strong_shop_alerts}</div></div>
  <div class="kpi-card"><div class="kpi-label">Average Edge / Score</div><div class="kpi-value">{avg_edge:.2f}% / {avg_score:.2f}</div></div>
</div>
"""
st.markdown(kpi_html, unsafe_allow_html=True)

st.markdown('<div class="hero-box">', unsafe_allow_html=True)
hero_left, hero_right = st.columns([2, 1])

with hero_left:
    st.markdown("### Current Top Bet")
    if top_bet_row is not None:
        st.markdown(
            f"""
            **{top_bet_row['Pick']}**  
            {top_bet_row['Event']} · {top_bet_row['Market']}  
            Book: **{top_bet_row['Sportsbook']}** · Odds: **{top_bet_row['Odds']}**  
            Edge: **{top_bet_row['Edge %']:.2f}%** · Score: **{top_bet_row['Bet Score']:.2f}** · Confidence: **{top_bet_row['Confidence']}**  
            Final Bet: **${int(top_bet_row['Final Bet'])}** · Movement: **{top_bet_row['Movement']}**  
            Reason: *{top_bet_row['Reason']}*
            """
        )
        if top_bet_row.get("Link"):
            st.markdown(f"[Open at sportsbook]({top_bet_row['Link']})")
    else:
        st.info("No final bets qualify under the current rules.")

with hero_right:
    st.markdown(
        """
        <div class="soft-card">
        <b>Quick sports links</b><br><br>
        <a href="https://sportsbook.draftkings.com/" target="_blank">DraftKings</a><br>
        <a href="https://sportsbook.fanduel.com/" target="_blank">FanDuel</a><br>
        <a href="https://www.bet365.com/" target="_blank">Bet365</a><br>
        <a href="https://app.prizepicks.com/" target="_blank">PrizePicks</a>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("</div>", unsafe_allow_html=True)

tabs = st.tabs(
    [
        "Overview",
        "Best Bets",
        "Compare Lines",
        "Quick Links",
        "DraftKings",
        "FanDuel",
        "Bet365",
        "PrizePicks",
        "AI Assistant",
        "Tracker",
        "Results",
        "Bankroll",
    ]
)

# -----------------------------
# OVERVIEW
# -----------------------------
with tabs[0]:
    col1, col2 = st.columns([1.25, 1])

    with col1:
        st.markdown('<div class="section-title">Top Final Bets</div>', unsafe_allow_html=True)
        top_cards = controlled_df[controlled_df["Final Status"] == "Bet"].head(5)
        if top_cards.empty:
            st.info("No final bets available right now.")
        else:
            for i, (_, row) in enumerate(top_cards.iterrows()):
                watch_html = ""
                if str(row.get("Watchlist Match", "")).strip():
                    watch_html = f'<span class="pill pill-blue">Watchlist: {row["Watchlist Match"]}</span>'
                st.markdown(
                    f"""
                    <div class="bet-card">
                      <div>
                        <span class="pill {pill_class_for_confidence(row['Confidence'])}">{row['Confidence']}</span>
                        <span class="pill {pill_class_for_movement(row['Movement'])}">{row['Movement']}</span>
                        <span class="pill {pill_class_for_final_status(row['Final Status'])}">{row['Final Status']}</span>
                        {watch_html}
                      </div>
                      <b>{row['Pick']}</b><br>
                      {row['Event']} · {row['Market']}<br>
                      {row['Sportsbook']} {row['Odds']} · Edge {row['Edge %']:.2f}% · Score {row['Bet Score']:.2f} · Final Bet ${int(row['Final Bet'])}<br>
                      <span style="color:#475569;">{row['Reason']}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    with col2:
        st.markdown('<div class="section-title">Charts</div>', unsafe_allow_html=True)

        chart_df = controlled_df[controlled_df["Final Status"] == "Bet"].copy()

        if chart_df.empty:
            st.info("No final bets to chart.")
        else:
            by_book = chart_df.groupby("Sportsbook")["Final Bet"].sum().sort_values(ascending=False)
            st.markdown("**Live risk by sportsbook**")
            st.bar_chart(by_book, height=220)

            by_sport = chart_df.groupby("Sport")["Final Bet"].sum().sort_values(ascending=False)
            st.markdown("**Live risk by sport**")
            st.bar_chart(by_sport, height=220)

            conf_mix = chart_df["Confidence"].value_counts()
            st.markdown("**Confidence mix**")
            st.bar_chart(conf_mix, height=200)

# -----------------------------
# BEST BETS
# -----------------------------
with tabs[1]:
    st.markdown('<div class="section-title">Best Bets Board</div>', unsafe_allow_html=True)

    board_df = display_df.copy()
    if board_df.empty:
        st.info("No rows match the current filters.")
    else:
        board_view = board_df[
            [
                "Sport",
                "Event",
                "Market Bucket",
                "Market",
                "Pick",
                "Sportsbook",
                "Odds",
                "Implied Prob",
                "Model Prob",
                "Edge %",
                "Bet Score",
                "Confidence",
                "Movement",
                "Recommended Bet",
                "Final Bet",
                "Final Status",
                "Allocation Status",
                "Pass Reason",
                "Watchlist Match",
                "Link",
            ]
        ]

        st.dataframe(
            board_view,
            use_container_width=True,
            hide_index=True,
            key="best_bets_table",
            column_config={
                "Implied Prob": st.column_config.NumberColumn(format="%.2f%%"),
                "Model Prob": st.column_config.NumberColumn(format="%.2f%%"),
                "Edge %": st.column_config.ProgressColumn("Edge %", min_value=-5.0, max_value=10.0, format="%.2f%%"),
                "Bet Score": st.column_config.ProgressColumn("Bet Score", min_value=0.0, max_value=10.0, format="%.2f"),
                "Recommended Bet": st.column_config.NumberColumn(format="$%d"),
                "Final Bet": st.column_config.NumberColumn(format="$%d"),
                "Link": st.column_config.LinkColumn("Open"),
            },
        )

        final_bets_only = board_df[board_df["Final Status"] == "Bet"].copy()
        st.markdown('<div class="section-title">Explain This Bet</div>', unsafe_allow_html=True)
        if final_bets_only.empty:
            st.info("No final bets available to explain.")
        else:
            final_bets_only["Explain Label"] = final_bets_only.apply(
                lambda row: f"{row['Event']} | {row['Pick']} | {row['Sportsbook']} {row['Odds']} | Score {row['Bet Score']:.2f}",
                axis=1,
            )
            selected_label = st.selectbox(
                "Choose a final bet to explain",
                options=final_bets_only["Explain Label"].tolist(),
                key="best_bets_explain_select",
            )
            selected_row = final_bets_only.loc[final_bets_only["Explain Label"] == selected_label].iloc[0]
            st.markdown(
                f"""
                <div class="soft-card">
                <b>{selected_row['Pick']}</b><br>
                {selected_row['Event']} · {selected_row['Market']}<br><br>
                <b>Why it made the board:</b><br>
                • Book: {selected_row['Sportsbook']} at {selected_row['Odds']}<br>
                • Edge: {selected_row['Edge %']:.2f}%<br>
                • Bet Score: {selected_row['Bet Score']:.2f}<br>
                • Confidence: {selected_row['Confidence']}<br>
                • Movement: {selected_row['Movement']}<br>
                • Final Bet: ${int(selected_row['Final Bet'])}<br>
                • Allocation Status: {selected_row['Allocation Status']}<br>
                • Logic: {selected_row['Reason']}<br>
                {f"• Watchlist Match: {selected_row['Watchlist Match']}<br>" if str(selected_row.get('Watchlist Match', '')).strip() else ""}
                </div>
                """,
                unsafe_allow_html=True,
            )

# -----------------------------
# COMPARE LINES
# -----------------------------
with tabs[2]:
    st.markdown('<div class="section-title">Compare Lines</div>', unsafe_allow_html=True)
    if compare_df.empty:
        st.info("No compare-lines rows available.")
    else:
        st.dataframe(
            compare_df[
                [
                    "Sport",
                    "Event",
                    "Market Bucket",
                    "Market",
                    "Pick",
                    "DraftKings",
                    "FanDuel",
                    "Bet365",
                    "PrizePicks",
                    "Best Book",
                    "Best Odds",
                    "Books Quoting",
                    "Line Gap %",
                    "Shop Alert",
                    "Best Confidence",
                    "Best Score",
                    "Best Final Bet",
                    "Best Final Status",
                    "Best Link",
                ]
            ],
            use_container_width=True,
            hide_index=True,
            key="compare_lines_table",
            column_config={
                "Line Gap %": st.column_config.ProgressColumn("Line Gap %", min_value=0.0, max_value=10.0, format="%.2f%%"),
                "Best Score": st.column_config.ProgressColumn("Best Score", min_value=0.0, max_value=10.0, format="%.2f"),
                "Best Final Bet": st.column_config.NumberColumn(format="$%d"),
                "Best Link": st.column_config.LinkColumn("Open"),
            },
        )

# -----------------------------
# QUICK LINKS
# -----------------------------
with tabs[3]:
    st.markdown('<div class="section-title">Quick Links</div>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="quick-link-grid">
          <div class="quick-link-card"><a href="https://sportsbook.draftkings.com/" target="_blank">Open DraftKings</a></div>
          <div class="quick-link-card"><a href="https://sportsbook.fanduel.com/" target="_blank">Open FanDuel</a></div>
          <div class="quick-link-card"><a href="https://www.bet365.com/" target="_blank">Open Bet365</a></div>
          <div class="quick-link-card"><a href="https://app.prizepicks.com/" target="_blank">Open PrizePicks</a></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# -----------------------------
# BOOK TABS
# -----------------------------
def render_book_tab(book_name: str, tab_key: str):
    st.markdown(f'<div class="section-title">{book_name} Opportunities</div>', unsafe_allow_html=True)
    book_df = controlled_df[controlled_df["Sportsbook"] == book_name].copy()
    if book_df.empty:
        st.info(f"No rows currently available for {book_name}.")
        return
    st.dataframe(
        book_df[
            [
                "Sport",
                "Event",
                "Market Bucket",
                "Market",
                "Pick",
                "Odds",
                "Edge %",
                "Bet Score",
                "Confidence",
                "Movement",
                "Final Bet",
                "Final Status",
                "Allocation Status",
                "Pass Reason",
                "Link",
            ]
        ],
        use_container_width=True,
        hide_index=True,
        key=f"{tab_key}_table",
        column_config={
            "Edge %": st.column_config.ProgressColumn("Edge %", min_value=-5.0, max_value=10.0, format="%.2f%%"),
            "Bet Score": st.column_config.ProgressColumn("Bet Score", min_value=0.0, max_value=10.0, format="%.2f"),
            "Final Bet": st.column_config.NumberColumn(format="$%d"),
            "Link": st.column_config.LinkColumn("Open"),
        },
    )

with tabs[4]:
    render_book_tab("DraftKings", "dk")
with tabs[5]:
    render_book_tab("FanDuel", "fd")
with tabs[6]:
    render_book_tab("Bet365", "b365")
with tabs[7]:
    render_book_tab("PrizePicks", "pp")

# -----------------------------
# AI ASSISTANT
# -----------------------------
with tabs[8]:
    st.markdown('<div class="section-title">AI Betting Assistant</div>', unsafe_allow_html=True)

    if "ai_history" not in st.session_state:
        st.session_state["ai_history"] = []

    preset_cols = st.columns(4)
    preset_prompts = [
        ("Safest bets today", "What are the safest bets on the board right now and why?"),
        ("Strongest edge", "Which current bets have the strongest edge and what makes them stand out?"),
        ("Overexposure check", "Where am I overexposed right now and what should I avoid?"),
        ("Book comparison", "Compare DraftKings and FanDuel for the best current opportunities."),
    ]

    for idx, (label, prompt) in enumerate(preset_prompts):
        with preset_cols[idx]:
            if st.button(label, key=f"ai_preset_{idx}"):
                context_text = summarize_dashboard_context(controlled_df, compare_df)
                answer = call_openai_assistant(prompt, context_text)
                st.session_state["ai_history"].append(("user", prompt))
                st.session_state["ai_history"].append(("assistant", answer))

    final_bets_ai = controlled_df[controlled_df["Final Status"] == "Bet"].copy()
    if not final_bets_ai.empty:
        final_bets_ai["AI Label"] = final_bets_ai.apply(
            lambda row: f"{row['Event']} | {row['Pick']} | {row['Sportsbook']} {row['Odds']}",
            axis=1,
        )
        selected_ai_bet = st.selectbox(
            "AI explain a specific final bet",
            options=["None"] + final_bets_ai["AI Label"].tolist(),
            key="ai_bet_select",
        )
        if selected_ai_bet != "None" and st.button("Explain selected bet with AI", key="ai_explain_btn"):
            row = final_bets_ai.loc[final_bets_ai["AI Label"] == selected_ai_bet].iloc[0]
            prompt = (
                f"Explain this bet clearly for a non-expert: {row['Pick']} in {row['Event']} at {row['Sportsbook']} {row['Odds']}. "
                f"Discuss edge, confidence, movement, and bankroll sizing."
            )
            context_text = summarize_dashboard_context(controlled_df, compare_df)
            answer = call_openai_assistant(prompt, context_text)
            st.session_state["ai_history"].append(("user", prompt))
            st.session_state["ai_history"].append(("assistant", answer))

    with st.form("ai_custom_form", clear_on_submit=False):
        custom_prompt = st.text_area(
            "Ask the dashboard AI a question",
            placeholder="Example: Which final bets are best for a cautious bettor today?",
            key="ai_custom_prompt",
        )
        submitted_ai = st.form_submit_button("Ask AI")
        if submitted_ai and custom_prompt.strip():
            context_text = summarize_dashboard_context(controlled_df, compare_df)
            answer = call_openai_assistant(custom_prompt.strip(), context_text)
            st.session_state["ai_history"].append(("user", custom_prompt.strip()))
            st.session_state["ai_history"].append(("assistant", answer))

    st.markdown("#### Conversation")
    if not st.session_state["ai_history"]:
        st.info("Use a preset prompt or type a custom question above.")
    else:
        for idx, (role, message) in enumerate(st.session_state["ai_history"][-12:]):
            if role == "user":
                st.markdown(f"**You:** {message}")
            else:
                st.markdown(
                    f"""
                    <div class="soft-card">
                    <b>AI Assistant:</b><br>
                    {message}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

# -----------------------------
# TRACKER
# -----------------------------
with tabs[9]:
    st.markdown('<div class="section-title">Tracker</div>', unsafe_allow_html=True)

    tracker_col1, tracker_col2 = st.columns(2)

    with tracker_col1:
        st.markdown("#### Log a final bet")
        tracker_candidates = controlled_df[controlled_df["Final Status"] == "Bet"].copy()
        if tracker_candidates.empty:
            st.info("No final bets available to log.")
        else:
            tracker_candidates["Log Label"] = tracker_candidates.apply(
                lambda row: f"{row['Event']} | {row['Pick']} | {row['Sportsbook']} {row['Odds']} | Final Bet ${int(row['Final Bet'])}",
                axis=1,
            )
            with st.form("log_bet_form_unique"):
                selected_log_label = st.selectbox(
                    "Choose a final bet",
                    options=tracker_candidates["Log Label"].tolist(),
                    key="tracker_log_select",
                )
                log_submit = st.form_submit_button("Log Selected Bet")
                if log_submit:
                    row = tracker_candidates.loc[tracker_candidates["Log Label"] == selected_log_label].iloc[0]
                    ok, msg = log_bet_from_row(row)
                    if ok:
                        st.success(msg)
                    else:
                        st.warning(msg)

    with tracker_col2:
        st.markdown("#### Settle a pending bet")
        pending_live = load_bet_log()
        pending_live = pending_live[pending_live["Bet Status"] == "Pending"].copy()
        if pending_live.empty:
            st.info("No pending bets to settle.")
        else:
            pending_live["Settle Label"] = pending_live.apply(
                lambda row: f"{row['Bet ID']} | {row['Event']} | {row['Pick']} | {row['Sportsbook']} {row['Odds']} | Stake ${row['Stake']:,.2f}",
                axis=1,
            )
            with st.form("settle_bet_form_unique"):
                selected_settle_label = st.selectbox(
                    "Choose a pending bet",
                    options=pending_live["Settle Label"].tolist(),
                    key="tracker_settle_select",
                )
                settle_result = st.radio("Result", ["Win", "Loss", "Push"], horizontal=True, key="tracker_settle_radio")
                settle_submit = st.form_submit_button("Settle Bet")
                if settle_submit:
                    bet_id = selected_settle_label.split(" | ")[0]
                    ok, msg = settle_bet(bet_id, settle_result)
                    if ok:
                        st.success(msg)
                    else:
                        st.warning(msg)

    st.markdown("#### Pending Bets")
    pending_view = load_bet_log()
    pending_view = pending_view[pending_view["Bet Status"] == "Pending"].copy()
    if pending_view.empty:
        st.info("No pending bets currently logged.")
    else:
        st.dataframe(
            pending_view[
                [
                    "Bet ID",
                    "Logged At",
                    "Sport",
                    "Event",
                    "Pick",
                    "Sportsbook",
                    "Odds",
                    "Stake",
                    "Confidence",
                    "Bet Score",
                    "Reason",
                ]
            ],
            use_container_width=True,
            hide_index=True,
            key="tracker_pending_table",
            column_config={
                "Stake": st.column_config.NumberColumn(format="$%.2f"),
                "Bet Score": st.column_config.NumberColumn(format="%.2f"),
            },
        )

# -----------------------------
# RESULTS
# -----------------------------
with tabs[10]:
    st.markdown('<div class="section-title">Results</div>', unsafe_allow_html=True)

    if settled_df.empty:
        st.info("No settled bets yet.")
    else:
        st.markdown(
            f"""
            <div class="soft-card">
            <b>Settled Bets:</b> {len(settled_df)} &nbsp;&nbsp; 
            <b>Win Rate:</b> {win_rate:.1f}% &nbsp;&nbsp; 
            <b>Profit / Loss:</b> ${realized_pnl:,.2f} &nbsp;&nbsp; 
            <b>ROI:</b> {roi:.1f}%
            </div>
            """,
            unsafe_allow_html=True,
        )

        results_col1, results_col2 = st.columns(2)

        with results_col1:
            st.markdown("**Profit by sportsbook**")
            book_profit = settled_df.groupby("Sportsbook")["PNL"].sum().sort_values(ascending=False)
            st.bar_chart(book_profit, height=240)

            st.markdown("**Profit by market type**")
            market_profit = settled_df.groupby("Market Bucket")["PNL"].sum().sort_values(ascending=False)
            st.bar_chart(market_profit, height=240)

        with results_col2:
            running = settled_df.copy()
            running["Sort Time"] = pd.to_datetime(running["Settled At"], errors="coerce")
            running = running.sort_values("Sort Time")
            running["Running Bankroll"] = bankroll + running["PNL"].cumsum()
            if not running.empty:
                st.markdown("**Bankroll curve**")
                st.line_chart(running.set_index("Sort Time")["Running Bankroll"], height=240)

            if not graded_df.empty:
                st.markdown("**Hit rate by confidence**")
                hit_rate_conf = (
                    graded_df.assign(WinFlag=(graded_df["Result"] == "Win").astype(int))
                    .groupby("Confidence")["WinFlag"]
                    .mean()
                    .mul(100)
                    .sort_values(ascending=False)
                )
                st.bar_chart(hit_rate_conf, height=240)

        st.markdown("#### Settled Bet History")
        st.dataframe(
            settled_df[
                [
                    "Bet ID",
                    "Logged At",
                    "Settled At",
                    "Sport",
                    "Event",
                    "Pick",
                    "Sportsbook",
                    "Odds",
                    "Stake",
                    "Result",
                    "PNL",
                    "Confidence",
                    "Bet Score",
                ]
            ].sort_values("Settled At", ascending=False),
            use_container_width=True,
            hide_index=True,
            key="results_history_table",
            column_config={
                "Stake": st.column_config.NumberColumn(format="$%.2f"),
                "PNL": st.column_config.NumberColumn(format="$%.2f"),
                "Bet Score": st.column_config.NumberColumn(format="%.2f"),
            },
        )

# -----------------------------
# BANKROLL
# -----------------------------
with tabs[11]:
    st.markdown('<div class="section-title">Bankroll</div>', unsafe_allow_html=True)

    bankroll_cards = f"""
    <div class="kpi-grid">
      <div class="kpi-card"><div class="kpi-label">Starting Bankroll</div><div class="kpi-value">${bankroll:,.2f}</div></div>
      <div class="kpi-card"><div class="kpi-label">Current Bankroll</div><div class="kpi-value">${current_bankroll:,.2f}</div></div>
      <div class="kpi-card"><div class="kpi-label">Logged Open Risk</div><div class="kpi-value">${open_logged_risk:,.2f}</div></div>
      <div class="kpi-card"><div class="kpi-label">Live Suggested Risk</div><div class="kpi-value">${open_live_risk:,.2f}</div></div>
    </div>
    """
    st.markdown(bankroll_cards, unsafe_allow_html=True)

    risk_df = pd.DataFrame(
        {
            "Cap": [
                "Total Exposure",
                "Per Sport",
                "Per Event",
                "Per Sportsbook",
                "Prop Exposure",
                "Max Props Per Event",
            ],
            "Setting": [
                max_total_exposure,
                max_sport_exposure,
                max_event_exposure,
                max_book_exposure,
                max_prop_exposure,
                max_event_props,
            ],
        }
    )
    st.markdown("#### Current Risk Settings")
    st.dataframe(risk_df, use_container_width=True, hide_index=True, key="bankroll_risk_table")

    live_final = controlled_df[controlled_df["Final Status"] == "Bet"].copy()
    if not live_final.empty:
        st.markdown("#### Live Risk Allocation")
        alloc_cols = st.columns(3)
        with alloc_cols[0]:
            st.markdown("**By sport**")
            st.bar_chart(live_final.groupby("Sport")["Final Bet"].sum().sort_values(ascending=False), height=220)
        with alloc_cols[1]:
            st.markdown("**By sportsbook**")
            st.bar_chart(live_final.groupby("Sportsbook")["Final Bet"].sum().sort_values(ascending=False), height=220)
        with alloc_cols[2]:
            st.markdown("**By market type**")
            st.bar_chart(live_final.groupby("Market Bucket")["Final Bet"].sum().sort_values(ascending=False), height=220)
