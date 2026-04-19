import math
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import pandas as pd
import requests
import streamlit as st

# -----------------------------
# PAGE SETUP
# -----------------------------
st.set_page_config(
    page_title="Sports Dashboard",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -----------------------------
# CONSTANTS
# -----------------------------
BOOK_LINKS = {
    "DraftKings": "https://sportsbook.draftkings.com/",
    "FanDuel": "https://sportsbook.fanduel.com/",
    "Bet365": "https://www.bet365.com/",
    "PrizePicks": "https://app.prizepicks.com/",
}

BOOK_ID_MAP = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "bet365": "Bet365",
    "prizepicks": "PrizePicks",
}

DEFAULT_LEAGUES = ["NBA", "NFL", "MLB", "NHL"]
DEFAULT_BANKROLL = 500.0

# -----------------------------
# THEME / CSS
# -----------------------------
st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(180deg, #f6f9ff 0%, #edf4ff 100%);
        color: #111827;
    }
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #eff6ff 0%, #e0ecff 100%);
        border-right: 1px solid #d7e3f8;
    }
    .main-title {
        font-size: 2.4rem;
        font-weight: 800;
        color: #0f172a;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        color: #334155;
        font-size: 1rem;
        margin-bottom: 1rem;
    }
    .panel {
        background: #ffffff;
        border: 1px solid #dbe7f8;
        border-radius: 18px;
        padding: 18px;
        box-shadow: 0 8px 18px rgba(15, 23, 42, 0.05);
        margin-bottom: 16px;
    }
    .hero {
        background: linear-gradient(135deg, #e8f1ff 0%, #dcecff 100%);
        border: 1px solid #cadef8;
        border-radius: 20px;
        padding: 20px;
        box-shadow: 0 8px 18px rgba(15, 23, 42, 0.06);
        margin-bottom: 16px;
    }
    .kpi-card {
        background: #ffffff;
        border: 1px solid #dbe7f8;
        border-radius: 16px;
        padding: 14px 16px;
        box-shadow: 0 6px 14px rgba(15, 23, 42, 0.04);
        min-height: 104px;
    }
    .kpi-label {
        color: #334155;
        font-size: 0.86rem;
        font-weight: 700;
        margin-bottom: 6px;
    }
    .kpi-value {
        color: #0b3b91;
        font-size: 1.55rem;
        font-weight: 800;
        margin-bottom: 4px;
    }
    .kpi-sub {
        color: #475569;
        font-size: 0.82rem;
    }
    .section-title {
        color: #0f172a;
        font-size: 1.2rem;
        font-weight: 800;
        margin-top: 2px;
        margin-bottom: 10px;
    }
    .bet-card {
        background: #ffffff;
        border: 1px solid #dbe7f8;
        border-left: 6px solid #0b3b91;
        border-radius: 16px;
        padding: 16px;
        box-shadow: 0 6px 14px rgba(15, 23, 42, 0.04);
        margin-bottom: 12px;
        color: #111827;
    }
    .small-note {
        color: #475569;
        font-size: 0.9rem;
    }
    .pill {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 999px;
        font-size: 0.78rem;
        font-weight: 700;
        margin-right: 6px;
        margin-top: 4px;
    }
    .pill-high { background: #dcfce7; color: #166534; }
    .pill-medium { background: #fef3c7; color: #92400e; }
    .pill-low { background: #fee2e2; color: #991b1b; }
    .link-card {
        background: #ffffff;
        border: 1px solid #dbe7f8;
        border-radius: 16px;
        padding: 18px;
        text-align: center;
        box-shadow: 0 6px 14px rgba(15, 23, 42, 0.04);
        color: #111827;
    }
    .bar-wrap {
        margin-bottom: 10px;
    }
    .bar-label {
        color: #0f172a;
        font-size: 0.90rem;
        font-weight: 700;
        margin-bottom: 4px;
    }
    .bar-bg {
        width: 100%;
        background: #e8eef9;
        border-radius: 999px;
        height: 16px;
        overflow: hidden;
    }
    .bar-fill {
        background: linear-gradient(90deg, #0b3b91 0%, #2563eb 100%);
        height: 16px;
        border-radius: 999px;
    }
    .bar-fill-neg {
        background: linear-gradient(90deg, #991b1b 0%, #ef4444 100%);
        height: 16px;
        border-radius: 999px;
    }
    .bar-value {
        color: #334155;
        font-size: 0.82rem;
        margin-top: 3px;
    }
    .ai-box {
        background: #ffffff;
        border: 1px solid #dbe7f8;
        border-radius: 16px;
        padding: 16px;
        margin-bottom: 12px;
        color: #111827;
    }
    .ai-user {
        border-left: 5px solid #2563eb;
    }
    .ai-assistant {
        border-left: 5px solid #0f766e;
    }
    a {
        color: #0b3b91 !important;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        background: #ffffff;
        border-radius: 12px;
        border: 1px solid #dbe7f8;
        color: #0f172a;
        padding: 10px 14px;
    }
    .stTabs [aria-selected="true"] {
        background: #dcecff !important;
        border-color: #9dbcf6 !important;
    }
    div[data-baseweb="select"] > div,
    div[data-baseweb="base-input"] > div,
    textarea, input {
        color: #111827 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------
# STATE
# -----------------------------
if "bet_log" not in st.session_state:
    st.session_state.bet_log = []

if "ai_messages" not in st.session_state:
    st.session_state.ai_messages = [
        {
            "role": "assistant",
            "content": "Ask about today’s board, strongest bets, bankroll risk, or have me explain a selected bet."
        }
    ]

if "last_board_snapshot" not in st.session_state:
    st.session_state.last_board_snapshot = {}

if "ai_prompt_seed" not in st.session_state:
    st.session_state.ai_prompt_seed = ""

# -----------------------------
# HELPERS
# -----------------------------
def safe_int_from_odds(odds_value) -> int | None:
    try:
        return int(str(odds_value).strip().replace("−", "-"))
    except Exception:
        return None


def american_to_implied(odds_value) -> float | None:
    odds = safe_int_from_odds(odds_value)
    if odds is None:
        return None
    if odds > 0:
        return round(100 / (odds + 100) * 100, 2)
    return round(abs(odds) / (abs(odds) + 100) * 100, 2)


def american_profit(odds_value, stake: float) -> float:
    odds = safe_int_from_odds(odds_value)
    if odds is None:
        return 0.0
    if odds > 0:
        return round(stake * (odds / 100), 2)
    return round(stake * (100 / abs(odds)), 2)


def parse_time(value: str):
    if not value:
        return None
    try:
        txt = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def minutes_to_start(value: str) -> float | None:
    dt = parse_time(value)
    if dt is None:
        return None
    now_utc = datetime.now(timezone.utc)
    return round((dt - now_utc).total_seconds() / 60, 1)


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


def classify_market(market_name: str, pick: str, sportsbook: str) -> str:
    text = f"{market_name} {pick}".lower()
    if sportsbook == "PrizePicks":
        return "DFS Prop"
    if "moneyline" in text or "winner" in text:
        return "Moneyline"
    if "spread" in text or "handicap" in text or "run line" in text or "puck line" in text:
        return "Spread"
    if "total" in text or "over " in text or "under " in text:
        return "Total"
    if "team total" in text:
        return "Team Total"
    if any(term in text for term in ["points", "rebounds", "assists", "hits", "strikeouts", "player"]):
        return "Player Prop"
    return "Other"


def confidence_from_score(score: float) -> str:
    if score >= 7:
        return "Elite"
    if score >= 5:
        return "High"
    if score >= 3:
        return "Medium"
    return "Low"


def market_weight(bucket: str) -> float:
    weights = {
        "Moneyline": 1.2,
        "Spread": 1.15,
        "Total": 1.05,
        "Team Total": 0.8,
        "Player Prop": 0.55,
        "DFS Prop": 0.35,
        "Other": 0.4,
    }
    return weights.get(bucket, 0.4)


def time_penalty(mins: float | None) -> float:
    if mins is None:
        return 0.0
    if mins < 0:
        return -2.0
    if mins < 20:
        return -1.25
    if mins < 60:
        return -0.75
    if mins < 180:
        return -0.25
    return 0.0


def books_bonus(n_books: int) -> float:
    return min(max(n_books - 1, 0) * 0.55, 2.2)


def book_penalty(book: str) -> float:
    return -0.55 if book == "PrizePicks" else 0.0


def recommend_bet_size(edge: float, score: float, min_bet: float, max_bet: float) -> int:
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


def simple_sparkline(values: List[float]) -> str:
    if not values:
        return "—"
    bars = "▁▂▃▄▅▆▇█"
    minimum = min(values)
    maximum = max(values)
    if math.isclose(minimum, maximum):
        return bars[3] * min(len(values), 10)
    result = []
    for v in values[-10:]:
        idx = int((v - minimum) / (maximum - minimum) * (len(bars) - 1))
        result.append(bars[idx])
    return "".join(result)


def html_kpi_card(label: str, value: str, sub: str = ""):
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">{label}</div>
            <div class="kpi-value">{value}</div>
            <div class="kpi-sub">{sub}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_bar_panel(title: str, series: Dict[str, float], value_prefix: str = "", value_suffix: str = "", negative_ok: bool = False):
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)
    if not series:
        st.markdown('<div class="panel"><span class="small-note">No data yet.</span></div>', unsafe_allow_html=True)
        return
    max_abs = max(abs(v) for v in series.values()) or 1
    html = ['<div class="panel">']
    for k, v in series.items():
        width = max(int(abs(v) / max_abs * 100), 4)
        cls = "bar-fill-neg" if negative_ok and v < 0 else "bar-fill"
        html.append(
            f'''<div class="bar-wrap"><div class="bar-label">{k}</div><div class="bar-bg"><div class="{cls}" style="width:{width}%;"></div></div><div class="bar-value">{value_prefix}{v:,.2f}{value_suffix}</div></div>'''
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def to_display_df(df: pd.DataFrame, cols: List[str], key: str):
    if df.empty:
        st.info("No rows to show for the current filters.")
        return
    st.data_editor(
        df[cols],
        use_container_width=True,
        hide_index=True,
        disabled=True,
        key=key,
    )

# -----------------------------
# SAMPLE DATA FALLBACK
# -----------------------------
def sample_board() -> pd.DataFrame:
    rows = [
        {"Sport": "NBA", "Event": "Knicks @ Celtics", "Market": "Moneyline", "Pick": "Knicks", "Sportsbook": "FanDuel", "Odds": "+118", "Start Time": "2026-04-20T23:00:00+00:00", "Link": BOOK_LINKS["FanDuel"]},
        {"Sport": "NBA", "Event": "Knicks @ Celtics", "Market": "Moneyline", "Pick": "Knicks", "Sportsbook": "DraftKings", "Odds": "+112", "Start Time": "2026-04-20T23:00:00+00:00", "Link": BOOK_LINKS["DraftKings"]},
        {"Sport": "NBA", "Event": "Knicks @ Celtics", "Market": "Moneyline", "Pick": "Knicks", "Sportsbook": "Bet365", "Odds": "+120", "Start Time": "2026-04-20T23:00:00+00:00", "Link": BOOK_LINKS["Bet365"]},
        {"Sport": "MLB", "Event": "Braves @ Phillies", "Market": "Total Runs", "Pick": "Over 8.5", "Sportsbook": "DraftKings", "Odds": "-105", "Start Time": "2026-04-20T22:35:00+00:00", "Link": BOOK_LINKS["DraftKings"]},
        {"Sport": "MLB", "Event": "Braves @ Phillies", "Market": "Total Runs", "Pick": "Over 8.5", "Sportsbook": "FanDuel", "Odds": "-110", "Start Time": "2026-04-20T22:35:00+00:00", "Link": BOOK_LINKS["FanDuel"]},
        {"Sport": "NFL", "Event": "Chiefs @ Bills", "Market": "Spread", "Pick": "Chiefs +2.5", "Sportsbook": "DraftKings", "Odds": "-110", "Start Time": "2026-04-21T00:20:00+00:00", "Link": BOOK_LINKS["DraftKings"]},
        {"Sport": "NFL", "Event": "Chiefs @ Bills", "Market": "Spread", "Pick": "Chiefs +2.5", "Sportsbook": "FanDuel", "Odds": "-108", "Start Time": "2026-04-21T00:20:00+00:00", "Link": BOOK_LINKS["FanDuel"]},
        {"Sport": "NFL", "Event": "Chiefs @ Bills", "Market": "Spread", "Pick": "Chiefs +2.5", "Sportsbook": "Bet365", "Odds": "-105", "Start Time": "2026-04-21T00:20:00+00:00", "Link": BOOK_LINKS["Bet365"]},
        {"Sport": "NBA", "Event": "Lakers @ Suns", "Market": "Player Points", "Pick": "LeBron Over 26.5", "Sportsbook": "PrizePicks", "Odds": "-119", "Start Time": "2026-04-20T02:00:00+00:00", "Link": BOOK_LINKS["PrizePicks"]},
        {"Sport": "NBA", "Event": "Lakers @ Suns", "Market": "Player Points", "Pick": "LeBron Over 26.5", "Sportsbook": "FanDuel", "Odds": "-110", "Start Time": "2026-04-20T02:00:00+00:00", "Link": BOOK_LINKS["FanDuel"]},
        {"Sport": "NHL", "Event": "Rangers @ Devils", "Market": "Moneyline", "Pick": "Devils", "Sportsbook": "Bet365", "Odds": "+140", "Start Time": "2026-04-20T23:30:00+00:00", "Link": BOOK_LINKS["Bet365"]},
        {"Sport": "NHL", "Event": "Rangers @ Devils", "Market": "Moneyline", "Pick": "Devils", "Sportsbook": "DraftKings", "Odds": "+135", "Start Time": "2026-04-20T23:30:00+00:00", "Link": BOOK_LINKS["DraftKings"]},
    ]
    df = pd.DataFrame(rows)
    df["Market Bucket"] = df.apply(lambda r: classify_market(r["Market"], r["Pick"], r["Sportsbook"]), axis=1)
    df["Implied Prob"] = df["Odds"].apply(american_to_implied)
    df["Minutes To Start"] = df["Start Time"].apply(minutes_to_start)
    return df


@st.cache_data(ttl=300, show_spinner=False)
def fetch_live_events(selected_leagues: Tuple[str, ...]) -> Tuple[pd.DataFrame, str]:
    api_key = st.secrets.get("SPORTS_GAME_ODDS_API_KEY", "")
    if not api_key:
        return sample_board(), "Using built-in sample data because SPORTS_GAME_ODDS_API_KEY is not set."

    url = "https://api.sportsgameodds.com/v2/events/"
    headers = {"x-api-key": api_key}
    params = {"leagueID": ",".join(selected_leagues), "oddsAvailable": "true", "limit": 100}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=20)
        response.raise_for_status()
        payload = response.json()
        events = payload.get("data", []) if isinstance(payload, dict) else payload
        rows = []

        for event in events:
            league_id = event.get("leagueID", "") or event.get("sportID", "")
            status = event.get("status", {}) or {}
            teams = event.get("teams", {}) or {}
            players = event.get("players", {}) or {}
            event_links = (event.get("links", {}) or {}).get("bookmakers", {}) or {}
            odds_map = event.get("odds", {}) or {}
            event_id = event.get("eventID", "")
            home_name = safe_team_name(teams.get("home", {}), "Home")
            away_name = safe_team_name(teams.get("away", {}), "Away")
            event_name = f"{away_name} @ {home_name}"
            starts_at = status.get("startsAt", "")

            for odd_id, odd in odds_map.items():
                by_bookmaker = odd.get("byBookmaker", {}) or {}
                market_name = odd.get("marketName", "") or "Market"
                for book_id, quote in by_bookmaker.items():
                    if book_id not in BOOK_ID_MAP:
                        continue
                    if not isinstance(quote, dict):
                        continue
                    if quote.get("available") is False:
                        continue
                    odds_value = quote.get("odds")
                    implied_prob = american_to_implied(odds_value)
                    if implied_prob is None:
                        continue
                    sportsbook = BOOK_ID_MAP[book_id]
                    pick = build_pick_label(odd, quote, home_name, away_name, players)
                    link = quote.get("deeplink") or event_links.get(book_id, "") or BOOK_LINKS.get(sportsbook, "")
                    rows.append(
                        {
                            "Event ID": event_id,
                            "Odd ID": odd_id,
                            "Sport": league_id,
                            "Event": event_name,
                            "Market": market_name,
                            "Pick": pick,
                            "Sportsbook": sportsbook,
                            "Odds": str(odds_value),
                            "Implied Prob": implied_prob,
                            "Start Time": starts_at,
                            "Minutes To Start": minutes_to_start(starts_at),
                            "Link": link,
                        }
                    )

        if not rows:
            return sample_board(), "No live odds returned, so sample data is shown."
        df = pd.DataFrame(rows)
        df["Market Bucket"] = df.apply(lambda r: classify_market(r["Market"], r["Pick"], r["Sportsbook"]), axis=1)
        return df, ""
    except Exception as exc:
        return sample_board(), f"Using built-in sample data because the live feed failed: {exc}"


def score_board(raw_df: pd.DataFrame, min_bet: float, max_bet: float) -> pd.DataFrame:
    df = raw_df.copy()
    group_cols = ["Event", "Market", "Pick"]

    market_stats = (
        df.groupby(group_cols)["Implied Prob"]
        .agg(["mean", "min", "max", "count"])
        .reset_index()
        .rename(columns={"mean": "Consensus Prob", "min": "Best Price Prob", "max": "Worst Price Prob", "count": "Books Quoting"})
    )
    df = df.merge(market_stats, on=group_cols, how="left")
    df["Model Prob"] = df["Consensus Prob"].round(2)
    df["Edge %"] = (df["Consensus Prob"] - df["Implied Prob"]).round(2)
    df["Best Line Gap %"] = (df["Worst Price Prob"] - df["Implied Prob"]).round(2)
    df["Is Best Price"] = df["Implied Prob"] <= df["Best Price Prob"] + 0.0001

    df["Bet Score"] = (
        df["Edge %"] * 0.95
        + df["Best Line Gap %"] * 0.35
        + df["Books Quoting"].apply(books_bonus)
        + df["Market Bucket"].apply(market_weight)
        + df["Minutes To Start"].apply(time_penalty)
        + df["Sportsbook"].apply(book_penalty)
    ).round(2)

    df["Confidence"] = df["Bet Score"].apply(confidence_from_score)
    df["Recommended Bet"] = df.apply(lambda r: recommend_bet_size(r["Edge %"], r["Bet Score"], min_bet, max_bet), axis=1)
    df["Status"] = df["Recommended Bet"].apply(lambda x: "Bet" if x > 0 else "Pass")
    return df


def add_line_movement(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    movement = []
    snapshot_key = {}
    for _, row in df.iterrows():
        key = f"{row['Event']}|{row['Market']}|{row['Pick']}|{row['Sportsbook']}"
        current = safe_int_from_odds(row["Odds"])
        previous = st.session_state.last_board_snapshot.get(key)
        if current is None or previous is None:
            movement.append("Flat")
        else:
            if current > previous:
                movement.append("Better")
            elif current < previous:
                movement.append("Worse")
            else:
                movement.append("Flat")
        if current is not None:
            snapshot_key[key] = current
    st.session_state.last_board_snapshot = snapshot_key
    df["Line Move"] = movement
    return df


def apply_risk_controls(
    df: pd.DataFrame,
    min_bet: float,
    max_total_exposure: float,
    max_per_sport: float,
    max_per_event: float,
    max_per_book: float,
    max_props_exposure: float,
) -> pd.DataFrame:
    df = df.copy().sort_values(
        ["Bet Score", "Edge %", "Books Quoting", "Is Best Price"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)

    total_used = 0.0
    sport_used: Dict[str, float] = {}
    event_used: Dict[str, float] = {}
    book_used: Dict[str, float] = {}
    props_used = 0.0
    event_pick_used: set[str] = set()

    stakes = []
    final_status = []
    pass_reason = []

    for _, row in df.iterrows():
        suggested = float(row["Recommended Bet"])
        correlation_key = f"{row['Event']}|{row['Pick']}"

        if row["Status"] != "Bet":
            stakes.append(0)
            final_status.append("Pass")
            pass_reason.append("Score/edge too weak")
            continue

        if correlation_key in event_pick_used:
            stakes.append(0)
            final_status.append("Pass")
            pass_reason.append("Duplicate/correlated pick already selected")
            continue

        if total_used + suggested > max_total_exposure:
            stakes.append(0)
            final_status.append("Pass")
            pass_reason.append("Total exposure cap reached")
            continue

        if sport_used.get(row["Sport"], 0.0) + suggested > max_per_sport:
            stakes.append(0)
            final_status.append("Pass")
            pass_reason.append("Sport exposure cap reached")
            continue

        if event_used.get(row["Event"], 0.0) + suggested > max_per_event:
            stakes.append(0)
            final_status.append("Pass")
            pass_reason.append("Event exposure cap reached")
            continue

        if book_used.get(row["Sportsbook"], 0.0) + suggested > max_per_book:
            stakes.append(0)
            final_status.append("Pass")
            pass_reason.append("Sportsbook exposure cap reached")
            continue

        if row["Market Bucket"] in {"Player Prop", "DFS Prop"} and props_used + suggested > max_props_exposure:
            stakes.append(0)
            final_status.append("Pass")
            pass_reason.append("Props exposure cap reached")
            continue

        if suggested < min_bet:
            stakes.append(0)
            final_status.append("Pass")
            pass_reason.append("Below minimum bet")
            continue

        stakes.append(int(suggested))
        final_status.append("Bet")
        reason_parts = []
        if row["Is Best Price"]:
            reason_parts.append("best current price")
        else:
            reason_parts.append("positive edge")
        reason_parts.append(f"{row['Books Quoting']} books quoting")
        reason_parts.append(row["Market Bucket"].lower())
        if row["Line Move"] == "Better":
            reason_parts.append("line moving in your favor")
        elif row["Line Move"] == "Worse":
            reason_parts.append("line drifting against you")
        pass_reason.append(" • ".join(reason_parts))

        total_used += suggested
        sport_used[row["Sport"]] = sport_used.get(row["Sport"], 0.0) + suggested
        event_used[row["Event"]] = event_used.get(row["Event"], 0.0) + suggested
        book_used[row["Sportsbook"]] = book_used.get(row["Sportsbook"], 0.0) + suggested
        if row["Market Bucket"] in {"Player Prop", "DFS Prop"}:
            props_used += suggested
        event_pick_used.add(correlation_key)

    df["Stake To Bet"] = stakes
    df["Final Status"] = final_status
    df["Reason"] = pass_reason
    return df


def build_compare_lines(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    group_cols = ["Sport", "Event", "Market Bucket", "Market", "Pick"]
    compare = (
        df.pivot_table(index=group_cols, columns="Sportsbook", values="Odds", aggfunc="first")
        .reset_index()
    )
    best_rows = (
        df.sort_values(["Event", "Market", "Pick", "Implied Prob", "Bet Score"], ascending=[True, True, True, True, False])
        .groupby(["Event", "Market", "Pick"], as_index=False)
        .first()
    )
    compare = compare.merge(
        best_rows[["Sport", "Event", "Market Bucket", "Market", "Pick", "Sportsbook", "Odds", "Best Line Gap %", "Bet Score", "Confidence", "Stake To Bet", "Final Status", "Reason", "Link"]],
        on=["Sport", "Event", "Market Bucket", "Market", "Pick"],
        how="left",
        suffixes=("", "_best"),
    )
    compare = compare.rename(
        columns={
            "Sportsbook": "Best Sportsbook",
            "Odds": "Best Odds",
            "Best Line Gap %": "Line Gap %",
            "Bet Score": "Best Bet Score",
            "Confidence": "Best Confidence",
            "Reason": "Best Reason",
            "Link": "Best Link",
        }
    )
    compare["Shop Alert"] = compare["Line Gap %"].apply(
        lambda x: "Strong Shop" if x >= 4 else ("Good Shop" if x >= 2 else ("Small Edge" if x > 0 else "Flat"))
    )
    return compare.sort_values(["Best Bet Score", "Line Gap %"], ascending=[False, False]).reset_index(drop=True)


def log_bet(row: pd.Series):
    duplicate = any(
        x["Event"] == row["Event"]
        and x["Pick"] == row["Pick"]
        and x["Sportsbook"] == row["Sportsbook"]
        and x["Odds"] == row["Odds"]
        and x["Bet Status"] == "Pending"
        for x in st.session_state.bet_log
    )
    if duplicate:
        return False, "That bet is already in the tracker."
    st.session_state.bet_log.append(
        {
            "Bet ID": f"B{len(st.session_state.bet_log)+1:04d}",
            "Logged At": datetime.now().strftime("%Y-%m-%d %I:%M:%S %p"),
            "Settled At": "",
            "Sport": row["Sport"],
            "Event": row["Event"],
            "Market Bucket": row["Market Bucket"],
            "Market": row["Market"],
            "Pick": row["Pick"],
            "Sportsbook": row["Sportsbook"],
            "Odds": row["Odds"],
            "Stake": float(row["Stake To Bet"]),
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
    )
    return True, "Bet logged."


def settle_logged_bet(bet_id: str, result: str):
    for item in st.session_state.bet_log:
        if item["Bet ID"] == bet_id and item["Bet Status"] == "Pending":
            item["Result"] = result
            item["Bet Status"] = "Settled"
            item["Settled At"] = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
            if result == "Win":
                item["PNL"] = american_profit(item["Odds"], float(item["Stake"]))
            elif result == "Loss":
                item["PNL"] = -float(item["Stake"])
            else:
                item["PNL"] = 0.0
            return True, f"{bet_id} settled as {result}."
    return False, "Bet not found."


def get_log_df() -> pd.DataFrame:
    if not st.session_state.bet_log:
        return pd.DataFrame(columns=[
            "Bet ID","Logged At","Settled At","Sport","Event","Market Bucket","Market","Pick",
            "Sportsbook","Odds","Stake","Implied Prob","Model Prob","Edge %","Bet Score",
            "Confidence","Reason","Start Time","Link","Bet Status","Result","PNL"
        ])
    return pd.DataFrame(st.session_state.bet_log)


def build_ai_context(board_df: pd.DataFrame, compare_df: pd.DataFrame, log_df: pd.DataFrame, bankroll: float) -> str:
    final_bets = board_df[board_df["Final Status"] == "Bet"].copy()
    settled = log_df[log_df["Bet Status"] == "Settled"].copy() if not log_df.empty else pd.DataFrame()
    pending = log_df[log_df["Bet Status"] == "Pending"].copy() if not log_df.empty else pd.DataFrame()

    lines = [
        f"Bankroll: ${bankroll:,.2f}",
        f"Current final bets: {len(final_bets)}",
        f"Pending logged bets: {len(pending)}",
        f"Settled bets: {len(settled)}",
    ]
    if not final_bets.empty:
        lines.append("Top current bets:")
        for _, row in final_bets.head(8).iterrows():
            lines.append(
                f"- {row['Event']} | {row['Pick']} | {row['Sportsbook']} {row['Odds']} | "
                f"edge {row['Edge %']:.2f}% | score {row['Bet Score']:.2f} | stake ${int(row['Stake To Bet'])} | {row['Reason']}"
            )
    if not compare_df.empty:
        lines.append("Best shopping spots:")
        for _, row in compare_df.head(6).iterrows():
            lines.append(
                f"- {row['Event']} | {row['Pick']} | best at {row['Best Sportsbook']} {row['Best Odds']} | "
                f"line gap {row['Line Gap %']:.2f}% | {row['Shop Alert']}"
            )
    if not settled.empty:
        lines.append(f"Realized P/L: ${settled['PNL'].sum():,.2f}")
    return "\n".join(lines)


def local_ai_response(prompt: str, board_df: pd.DataFrame, compare_df: pd.DataFrame, log_df: pd.DataFrame, bankroll: float) -> str:
    text = prompt.lower()
    final_bets = board_df[board_df["Final Status"] == "Bet"].copy()
    settled = log_df[log_df["Bet Status"] == "Settled"].copy() if not log_df.empty else pd.DataFrame()
    pending = log_df[log_df["Bet Status"] == "Pending"].copy() if not log_df.empty else pd.DataFrame()

    if "safe" in text or "safest" in text:
        picks = final_bets.sort_values(["Bet Score", "Edge %"], ascending=[False, False]).head(3)
        if picks.empty:
            return "There are no final bets right now under the current rules."
        out = ["Safest current looks:"]
        for _, r in picks.iterrows():
            out.append(f"- {r['Pick']} in {r['Event']} at {r['Sportsbook']} {r['Odds']} | confidence {r['Confidence']} | stake ${int(r['Stake To Bet'])}")
        return "\n".join(out)

    if "overexposed" in text or "risk" in text:
        risk_by_sport = pending.groupby("Sport")["Stake"].sum().to_dict() if not pending.empty else {}
        total = pending["Stake"].sum() if not pending.empty else 0
        return f"Open logged risk is ${total:,.2f}. Risk by sport: {risk_by_sport if risk_by_sport else 'none yet'}."

    if "compare" in text and ("draftkings" in text or "fanduel" in text):
        subset = compare_df.head(5)
        if subset.empty:
            return "There are no comparison rows to review right now."
        out = ["Best shopping examples right now:"]
        for _, r in subset.iterrows():
            out.append(f"- {r['Pick']} in {r['Event']}: best at {r['Best Sportsbook']} {r['Best Odds']}; DK={r.get('DraftKings','')} FD={r.get('FanDuel','')}")
        return "\n".join(out)

    if "avoid" in text or "pass" in text:
        passes = board_df[board_df["Final Status"] == "Pass"].copy().head(5)
        if passes.empty:
            return "Nothing obvious to avoid from the current filtered board."
        out = ["Current pass examples and why:"]
        for _, r in passes.iterrows():
            out.append(f"- {r['Pick']} in {r['Event']}: {r['Reason']}")
        return "\n".join(out)

    if "bankroll" in text:
        realized = settled["PNL"].sum() if not settled.empty else 0
        current = bankroll + realized
        return f"Starting bankroll is ${bankroll:,.2f}. Realized P/L is ${realized:,.2f}. Current bankroll is ${current:,.2f}."

    if "best" in text or "strongest" in text:
        picks = final_bets.head(5)
        if picks.empty:
            return "No final bets qualify right now."
        out = ["Top bets right now:"]
        for _, r in picks.iterrows():
            out.append(f"- {r['Pick']} | {r['Event']} | {r['Sportsbook']} {r['Odds']} | score {r['Bet Score']:.2f} | stake ${int(r['Stake To Bet'])}")
        return "\n".join(out)

    return (
        "I can help with the live board, strongest bets, shopping differences, bankroll risk, or why a pick is recommended. "
        "Try asking 'What are today’s safest bets?' or 'Where am I overexposed right now?'"
    )


def call_openai(prompt: str, context_text: str) -> str:
    api_key = st.secrets.get("OPENAI_API_KEY", "")
    if not api_key:
        return ""
    model = st.secrets.get("OPENAI_MODEL", "gpt-4.1-mini")
    try:
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "input": [
                    {
                        "role": "system",
                        "content": (
                            "You are a sports-betting dashboard assistant. Keep answers concise, practical, and focused on "
                            "line-shopping, bankroll discipline, exposure, and the dashboard data provided."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"DASHBOARD DATA:\n{context_text}\n\nUSER QUESTION:\n{prompt}",
                    },
                ],
            },
            timeout=35,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
            return payload["output_text"].strip()

        output = payload.get("output", [])
        text_parts = []
        for item in output:
            for piece in item.get("content", []):
                txt = piece.get("text")
                if txt:
                    text_parts.append(txt)
        return "\n".join(text_parts).strip()
    except Exception:
        return ""


def explain_bet_text(row: pd.Series) -> str:
    parts = []
    parts.append(f"{row['Pick']} in {row['Event']} is priced at {row['Sportsbook']} {row['Odds']}.")
    parts.append(f"The board implies {row['Implied Prob']:.2f}% and the current consensus is {row['Model Prob']:.2f}%, creating an edge of {row['Edge %']:.2f}%.")
    parts.append(f"It is in the {row['Market Bucket'].lower()} bucket with a score of {row['Bet Score']:.2f} and {row['Confidence']} confidence.")
    parts.append(f"The suggested stake is ${int(row['Stake To Bet'])}.")
    parts.append(f"Why it survived the risk controls: {row['Reason']}.")
    return " ".join(parts)

# -----------------------------
# SIDEBAR CONTROLS
# -----------------------------
st.sidebar.markdown("## Dashboard Controls")

bankroll = st.sidebar.number_input("Starting Bankroll", min_value=1.0, value=DEFAULT_BANKROLL, step=25.0, key="sb_bankroll")
min_bet = st.sidebar.number_input("Minimum Bet", min_value=1.0, value=1.0, step=1.0, key="sb_min_bet")
max_bet = st.sidebar.number_input("Maximum Bet", min_value=1.0, value=10.0, step=1.0, key="sb_max_bet")
max_total_exposure = st.sidebar.number_input("Max Total Exposure", min_value=5.0, value=40.0, step=5.0, key="sb_max_total")
max_per_sport = st.sidebar.number_input("Max Per Sport", min_value=5.0, value=18.0, step=1.0, key="sb_max_sport")
max_per_event = st.sidebar.number_input("Max Per Event", min_value=5.0, value=12.0, step=1.0, key="sb_max_event")
max_per_book = st.sidebar.number_input("Max Per Sportsbook", min_value=5.0, value=16.0, step=1.0, key="sb_max_book")
max_props_exposure = st.sidebar.number_input("Max Props Exposure", min_value=2.0, value=10.0, step=1.0, key="sb_max_props")

league_filter = st.sidebar.multiselect("Leagues", DEFAULT_LEAGUES, default=DEFAULT_LEAGUES, key="sb_leagues")
book_filter = st.sidebar.multiselect("Sportsbooks", list(BOOK_LINKS.keys()), default=list(BOOK_LINKS.keys()), key="sb_books")
market_options = ["Moneyline", "Spread", "Total", "Team Total", "Player Prop", "DFS Prop", "Other"]
market_filter = st.sidebar.multiselect("Market Types", market_options, default=market_options, key="sb_markets")
confidence_options = ["Elite", "High", "Medium", "Low"]
confidence_filter = st.sidebar.multiselect("Confidence", confidence_options, default=confidence_options, key="sb_conf")
final_only = st.sidebar.toggle("Show final bets only", value=False, key="sb_final_only")

refresh_col1, refresh_col2 = st.sidebar.columns(2)
with refresh_col1:
    if st.button("Refresh Board", key="sb_refresh"):
        fetch_live_events.clear()
        st.rerun()
with refresh_col2:
    if st.button("Clear AI", key="sb_clear_ai"):
        st.session_state.ai_messages = [
            {
                "role": "assistant",
                "content": "Ask about today’s board, strongest bets, bankroll risk, or have me explain a selected bet."
            }
        ]
        st.rerun()

# -----------------------------
# BOARD BUILD
# -----------------------------
raw_df, board_note = fetch_live_events(tuple(league_filter))
scored_df = score_board(raw_df, min_bet=min_bet, max_bet=max_bet)
scored_df = add_line_movement(scored_df)

filtered_df = scored_df[
    scored_df["Sportsbook"].isin(book_filter)
    & scored_df["Market Bucket"].isin(market_filter)
    & scored_df["Confidence"].isin(confidence_filter)
].copy()

board_df = apply_risk_controls(
    filtered_df,
    min_bet=min_bet,
    max_total_exposure=max_total_exposure,
    max_per_sport=max_per_sport,
    max_per_event=max_per_event,
    max_per_book=max_per_book,
    max_props_exposure=max_props_exposure,
)

if final_only:
    board_df = board_df[board_df["Final Status"] == "Bet"].copy()

board_df = board_df.sort_values(
    ["Final Status", "Bet Score", "Edge %", "Books Quoting"],
    ascending=[False, False, False, False],
).reset_index(drop=True)

compare_df = build_compare_lines(board_df)
log_df = get_log_df()
pending_df = log_df[log_df["Bet Status"] == "Pending"].copy() if not log_df.empty else pd.DataFrame()
settled_df = log_df[log_df["Bet Status"] == "Settled"].copy() if not log_df.empty else pd.DataFrame()

# -----------------------------
# TOP HEADER
# -----------------------------
st.markdown('<div class="main-title">Sports Betting Dashboard</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">Clean, readable, tab-based rebuild with safer components, sportsbook links, AI help, compare lines, tracker, and bankroll controls.</div>',
    unsafe_allow_html=True,
)

if board_note:
    st.info(board_note)

final_bets_df = board_df[board_df["Final Status"] == "Bet"].copy()
realized_pnl = float(settled_df["PNL"].sum()) if not settled_df.empty else 0.0
open_logged_risk = float(pending_df["Stake"].sum()) if not pending_df.empty else 0.0
open_live_risk = float(final_bets_df["Stake To Bet"].sum()) if not final_bets_df.empty else 0.0
current_bankroll = bankroll + realized_pnl
roi = (realized_pnl / settled_df["Stake"].sum() * 100) if (not settled_df.empty and settled_df["Stake"].sum() > 0) else 0.0
strong_shop_alerts = int((compare_df["Shop Alert"] == "Strong Shop").sum()) if not compare_df.empty else 0
avg_edge = float(final_bets_df["Edge %"].mean()) if not final_bets_df.empty else 0.0
avg_score = float(final_bets_df["Bet Score"].mean()) if not final_bets_df.empty else 0.0

top_panel_left, top_panel_right = st.columns([2.0, 1.1])
with top_panel_left:
    st.markdown('<div class="hero">', unsafe_allow_html=True)
    if not final_bets_df.empty:
        best = final_bets_df.iloc[0]
        st.markdown("### Top Bet Right Now")
        st.markdown(
            f"""
            <div class="bet-card">
                <b>{best['Pick']}</b><br>
                {best['Event']} · {best['Market']}<br>
                Book: <b>{best['Sportsbook']}</b> · Odds: <b>{best['Odds']}</b><br>
                Edge: <b>{best['Edge %']:.2f}%</b> · Score: <b>{best['Bet Score']:.2f}</b> · Stake: <b>${int(best['Stake To Bet'])}</b><br>
                <span class="small-note">{best['Reason']}</span><br><br>
                <a href="{best['Link']}" target="_blank">Open this book</a>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown('<div class="small-note">No final bets passed the current filters and risk caps.</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

with top_panel_right:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown("### Quick Snapshot")
    st.markdown(
        f"""
        <div class="small-note">
        Starting bankroll: <b>${bankroll:,.2f}</b><br>
        Current bankroll: <b>${current_bankroll:,.2f}</b><br>
        Final bets on board: <b>{len(final_bets_df)}</b><br>
        Strong shop alerts: <b>{strong_shop_alerts}</b><br>
        Open live risk: <b>${open_live_risk:,.2f}</b><br>
        Logged open risk: <b>${open_logged_risk:,.2f}</b>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('</div>', unsafe_allow_html=True)

k1, k2, k3, k4, k5, k6 = st.columns(6)
with k1:
    html_kpi_card("Current Bankroll", f"${current_bankroll:,.2f}", f"Starting ${bankroll:,.2f}")
with k2:
    html_kpi_card("Realized P/L", f"${realized_pnl:,.2f}", f"ROI {roi:.1f}%")
with k3:
    html_kpi_card("Open Risk", f"${open_live_risk:,.2f}", f"Logged ${open_logged_risk:,.2f}")
with k4:
    html_kpi_card("Final Bets", f"{len(final_bets_df)}", f"Avg edge {avg_edge:.2f}%")
with k5:
    html_kpi_card("Shop Alerts", f"{strong_shop_alerts}", f"Avg score {avg_score:.2f}")
with k6:
    pnl_values = settled_df["PNL"].tolist() if not settled_df.empty else []
    html_kpi_card("P/L Spark", simple_sparkline(pnl_values), "Recent settled trend")

# -----------------------------
# TABS
# -----------------------------
tabs = st.tabs([
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
])

# -----------------------------
# OVERVIEW
# -----------------------------
with tabs[0]:
    left, right = st.columns([1.2, 1.0])

    with left:
        st.markdown('<div class="section-title">Top Final Bets</div>', unsafe_allow_html=True)
        if final_bets_df.empty:
            st.info("No final bets right now.")
        else:
            for _, row in final_bets_df.head(5).iterrows():
                pill_class = "pill-high" if row["Confidence"] in {"Elite", "High"} else ("pill-medium" if row["Confidence"] == "Medium" else "pill-low")
                st.markdown(
                    f"""
                    <div class="bet-card">
                        <b>{row['Pick']}</b><br>
                        {row['Event']} · {row['Market']}<br>
                        Book: <b>{row['Sportsbook']}</b> · Odds: <b>{row['Odds']}</b><br>
                        <span class="pill {pill_class}">{row['Confidence']}</span>
                        <span class="pill pill-medium">Edge {row['Edge %']:.2f}%</span>
                        <span class="pill pill-medium">Stake ${int(row['Stake To Bet'])}</span><br><br>
                        <span class="small-note">{row['Reason']}</span><br>
                        <a href="{row['Link']}" target="_blank">Open book</a>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    with right:
        exposure_by_sport = final_bets_df.groupby("Sport")["Stake To Bet"].sum().sort_values(ascending=False).to_dict() if not final_bets_df.empty else {}
        render_bar_panel("Open Exposure by Sport", exposure_by_sport, value_prefix="$")

        shop_by_book = compare_df.groupby("Best Sportsbook").size().sort_values(ascending=False).to_dict() if not compare_df.empty else {}
        render_bar_panel("Best Book Count", {k: float(v) for k, v in shop_by_book.items()})

    lower_left, lower_right = st.columns([1, 1])

    with lower_left:
        profit_by_book = settled_df.groupby("Sportsbook")["PNL"].sum().sort_values(ascending=False).to_dict() if not settled_df.empty else {}
        render_bar_panel("Profit / Loss by Sportsbook", profit_by_book, value_prefix="$", negative_ok=True)

    with lower_right:
        hit_rate = {}
        if not settled_df.empty:
            graded = settled_df[settled_df["Result"].isin(["Win", "Loss"])].copy()
            if not graded.empty:
                for conf, grp in graded.groupby("Confidence"):
                    hit_rate[conf] = round(grp["Result"].eq("Win").mean() * 100, 1)
        render_bar_panel("Hit Rate by Confidence", hit_rate, value_suffix="%", negative_ok=False)

# -----------------------------
# BEST BETS
# -----------------------------
with tabs[1]:
    st.markdown('<div class="section-title">Best Bets Board</div>', unsafe_allow_html=True)
    to_display_df(
        board_df,
        [
            "Sport", "Event", "Market Bucket", "Market", "Pick", "Sportsbook", "Odds",
            "Edge %", "Best Line Gap %", "Bet Score", "Confidence", "Stake To Bet",
            "Line Move", "Final Status", "Reason"
        ],
        key="best_bets_table",
    )

    st.markdown('<div class="section-title">Explain a Selected Final Bet</div>', unsafe_allow_html=True)
    explain_candidates = final_bets_df.copy()
    if explain_candidates.empty:
        st.info("No final bets available to explain.")
    else:
        explain_candidates["Explain Label"] = explain_candidates.apply(
            lambda r: f"{r['Event']} | {r['Pick']} | {r['Sportsbook']} {r['Odds']} | Stake ${int(r['Stake To Bet'])}",
            axis=1,
        )
        selected_label = st.selectbox(
            "Select a final bet",
            explain_candidates["Explain Label"].tolist(),
            key="explain_select",
        )
        if st.button("Explain This Bet", key="explain_bet_btn"):
            chosen = explain_candidates.loc[explain_candidates["Explain Label"] == selected_label].iloc[0]
            st.markdown(f'<div class="panel">{explain_bet_text(chosen)}</div>', unsafe_allow_html=True)

        if st.button("Log Selected Bet", key="log_selected_best_bet"):
            chosen = explain_candidates.loc[explain_candidates["Explain Label"] == selected_label].iloc[0]
            ok, msg = log_bet(chosen)
            if ok:
                st.success(msg)
            else:
                st.warning(msg)

# -----------------------------
# COMPARE LINES
# -----------------------------
with tabs[2]:
    st.markdown('<div class="section-title">Compare Lines / Best Book</div>', unsafe_allow_html=True)
    if compare_df.empty:
        st.info("No line comparison rows available.")
    else:
        to_display_df(
            compare_df,
            [
                "Sport", "Event", "Market Bucket", "Market", "Pick",
                "DraftKings", "FanDuel", "Bet365", "PrizePicks",
                "Best Sportsbook", "Best Odds", "Line Gap %", "Shop Alert",
                "Best Bet Score", "Best Confidence", "Stake To Bet", "Final Status"
            ],
            key="compare_lines_table",
        )

        leaderboard = compare_df.head(8)[["Event", "Pick", "Best Sportsbook", "Best Odds", "Line Gap %", "Shop Alert"]]
        st.markdown('<div class="section-title">Line Gap Leaderboard</div>', unsafe_allow_html=True)
        to_display_df(leaderboard, leaderboard.columns.tolist(), key="leaderboard_table")

# -----------------------------
# QUICK LINKS
# -----------------------------
with tabs[3]:
    st.markdown('<div class="section-title">Quick Links</div>', unsafe_allow_html=True)
    cols = st.columns(4)
    for i, (name, url) in enumerate(BOOK_LINKS.items()):
        with cols[i]:
            st.markdown(
                f"""
                <div class="link-card">
                    <h4 style="margin-bottom:8px;color:#0f172a;">{name}</h4>
                    <div class="small-note" style="margin-bottom:12px;">Jump straight to the book.</div>
                    <a href="{url}" target="_blank">Open {name}</a>
                </div>
                """,
                unsafe_allow_html=True,
            )

# -----------------------------
# SPORTSBOOK TABS
# -----------------------------
def render_book_tab(book_name: str, tab_key: str):
    st.markdown(f'<div class="section-title">{book_name} Board</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="panel"><a href="{BOOK_LINKS[book_name]}" target="_blank">Open {book_name}</a></div>', unsafe_allow_html=True)
    book_df = board_df[board_df["Sportsbook"] == book_name].copy()
    to_display_df(
        book_df,
        [
            "Sport", "Event", "Market Bucket", "Market", "Pick", "Odds",
            "Edge %", "Bet Score", "Confidence", "Stake To Bet",
            "Line Move", "Final Status", "Reason"
        ],
        key=tab_key,
    )

with tabs[4]:
    render_book_tab("DraftKings", "dk_table")
with tabs[5]:
    render_book_tab("FanDuel", "fd_table")
with tabs[6]:
    render_book_tab("Bet365", "b365_table")
with tabs[7]:
    render_book_tab("PrizePicks", "pp_table")

# -----------------------------
# AI ASSISTANT
# -----------------------------
with tabs[8]:
    st.markdown('<div class="section-title">AI Betting Assistant</div>', unsafe_allow_html=True)

    prompt_col1, prompt_col2, prompt_col3, prompt_col4 = st.columns(4)
    with prompt_col1:
        if st.button("Safest Bets", key="ai_preset_safe"):
            st.session_state.ai_prompt_seed = "What are today’s safest bets?"
    with prompt_col2:
        if st.button("Strongest Edges", key="ai_preset_edges"):
            st.session_state.ai_prompt_seed = "Which bets have the strongest edge right now?"
    with prompt_col3:
        if st.button("Risk Summary", key="ai_preset_risk"):
            st.session_state.ai_prompt_seed = "Where am I overexposed right now?"
    with prompt_col4:
        if st.button("Compare Books", key="ai_preset_compare"):
            st.session_state.ai_prompt_seed = "Compare DraftKings vs FanDuel for today."

    st.markdown('<div class="panel"><span class="small-note">If OPENAI_API_KEY is not set, the assistant falls back to a built-in rules-based helper.</span></div>', unsafe_allow_html=True)

    for msg in st.session_state.ai_messages:
        css_class = "ai-user" if msg["role"] == "user" else "ai-assistant"
        speaker = "You" if msg["role"] == "user" else "Assistant"
        st.markdown(
            f"""
            <div class="ai-box {css_class}">
                <b>{speaker}</b><br>
                {msg['content']}
            </div>
            """,
            unsafe_allow_html=True,
        )

    with st.form("ai_form"):
        user_prompt = st.text_area(
            "Ask the assistant",
            value=st.session_state.ai_prompt_seed,
            height=110,
            key="ai_prompt_text",
        )
        submitted_ai = st.form_submit_button("Send")
        if submitted_ai and user_prompt.strip():
            st.session_state.ai_messages.append({"role": "user", "content": user_prompt.strip()})
            context_text = build_ai_context(board_df, compare_df, log_df, bankroll)
            openai_answer = call_openai(user_prompt.strip(), context_text)
            if openai_answer:
                answer = openai_answer
            else:
                answer = local_ai_response(user_prompt.strip(), board_df, compare_df, log_df, bankroll)
            st.session_state.ai_messages.append({"role": "assistant", "content": answer})
            st.session_state.ai_prompt_seed = ""
            st.rerun()

# -----------------------------
# TRACKER
# -----------------------------
with tabs[9]:
    st.markdown('<div class="section-title">Bet Tracker</div>', unsafe_allow_html=True)

    left, right = st.columns(2)

    with left:
        st.markdown('<div class="panel"><b>Log a Final Bet</b><br><span class="small-note">Pick from the current board and save it to your tracker.</span></div>', unsafe_allow_html=True)
        log_choices = final_bets_df.copy()
        if log_choices.empty:
            st.info("No final bets available to log.")
        else:
            log_choices["Log Label"] = log_choices.apply(
                lambda r: f"{r['Event']} | {r['Pick']} | {r['Sportsbook']} {r['Odds']} | Stake ${int(r['Stake To Bet'])}",
                axis=1,
            )
            selected_log = st.selectbox("Choose a final bet", log_choices["Log Label"].tolist(), key="tracker_log_select")
            if st.button("Log Bet", key="tracker_log_btn"):
                chosen = log_choices.loc[log_choices["Log Label"] == selected_log].iloc[0]
                ok, msg = log_bet(chosen)
                if ok:
                    st.success(msg)
                else:
                    st.warning(msg)

    with right:
        st.markdown('<div class="panel"><b>Settle a Pending Bet</b><br><span class="small-note">Mark it as win, loss, or push.</span></div>', unsafe_allow_html=True)
        pending_choices = pending_df.copy()
        if pending_choices.empty:
            st.info("No pending bets yet.")
        else:
            pending_choices["Settle Label"] = pending_choices.apply(
                lambda r: f"{r['Bet ID']} | {r['Event']} | {r['Pick']} | {r['Sportsbook']} {r['Odds']} | Stake ${r['Stake']:,.2f}",
                axis=1,
            )
            selected_settle = st.selectbox("Choose a pending bet", pending_choices["Settle Label"].tolist(), key="tracker_settle_select")
            settle_result = st.radio("Result", ["Win", "Loss", "Push"], horizontal=True, key="tracker_settle_result")
            if st.button("Settle Bet", key="tracker_settle_btn"):
                bet_id = selected_settle.split(" | ")[0]
                ok, msg = settle_logged_bet(bet_id, settle_result)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.warning(msg)

    st.markdown('<div class="section-title">Pending Bets</div>', unsafe_allow_html=True)
    to_display_df(
        pending_df,
        ["Bet ID", "Logged At", "Sport", "Event", "Pick", "Sportsbook", "Odds", "Stake", "Confidence", "Bet Score", "Reason"],
        key="pending_table",
    )

# -----------------------------
# RESULTS
# -----------------------------
with tabs[10]:
    st.markdown('<div class="section-title">Results</div>', unsafe_allow_html=True)

    if settled_df.empty:
        st.info("No settled bets yet.")
    else:
        graded = settled_df[settled_df["Result"].isin(["Win", "Loss"])].copy()
        wins = int((settled_df["Result"] == "Win").sum())
        losses = int((settled_df["Result"] == "Loss").sum())
        pushes = int((settled_df["Result"] == "Push").sum())
        total_staked = float(settled_df["Stake"].sum())
        win_rate = (wins / len(graded) * 100) if len(graded) else 0.0

        a, b, c, d = st.columns(4)
        with a:
            html_kpi_card("Settled Bets", f"{len(settled_df)}", f"W-L-P {wins}-{losses}-{pushes}")
        with b:
            html_kpi_card("Win Rate", f"{win_rate:.1f}%", "")
        with c:
            html_kpi_card("Total Staked", f"${total_staked:,.2f}", "")
        with d:
            html_kpi_card("Realized P/L", f"${realized_pnl:,.2f}", f"ROI {roi:.1f}%")

        profit_by_market = settled_df.groupby("Market Bucket")["PNL"].sum().sort_values(ascending=False).to_dict()
        confidence_pnl = settled_df.groupby("Confidence")["PNL"].sum().sort_values(ascending=False).to_dict()
        running = list((bankroll + settled_df["PNL"].cumsum()).tolist()) if not settled_df.empty else []

        left, right = st.columns(2)
        with left:
            render_bar_panel("Profit / Loss by Market Type", profit_by_market, value_prefix="$", negative_ok=True)
        with right:
            render_bar_panel("Profit / Loss by Confidence", confidence_pnl, value_prefix="$", negative_ok=True)

        st.markdown('<div class="section-title">Running Bankroll Trend</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="panel"><span class="small-note">Sparkline: <b>{simple_sparkline(running)}</b></span></div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div class="section-title">Settled Bet History</div>', unsafe_allow_html=True)
    to_display_df(
        settled_df.sort_values("Settled At", ascending=False) if not settled_df.empty else settled_df,
        ["Bet ID", "Logged At", "Settled At", "Sport", "Event", "Pick", "Sportsbook", "Odds", "Stake", "Result", "PNL", "Confidence", "Bet Score"],
        key="settled_table",
    )

# -----------------------------
# BANKROLL
# -----------------------------
with tabs[11]:
    st.markdown('<div class="section-title">Bankroll</div>', unsafe_allow_html=True)

    sport_live_risk = final_bets_df.groupby("Sport")["Stake To Bet"].sum().sort_values(ascending=False).to_dict() if not final_bets_df.empty else {}
    book_live_risk = final_bets_df.groupby("Sportsbook")["Stake To Bet"].sum().sort_values(ascending=False).to_dict() if not final_bets_df.empty else {}

    a, b, c, d = st.columns(4)
    with a:
        html_kpi_card("Starting Bankroll", f"${bankroll:,.2f}")
    with b:
        html_kpi_card("Current Bankroll", f"${current_bankroll:,.2f}")
    with c:
        html_kpi_card("Open Live Risk", f"${open_live_risk:,.2f}")
    with d:
        html_kpi_card("Open Logged Risk", f"${open_logged_risk:,.2f}")

    left, right = st.columns(2)
    with left:
        render_bar_panel("Live Exposure by Sport", sport_live_risk, value_prefix="$")
    with right:
        render_bar_panel("Live Exposure by Sportsbook", book_live_risk, value_prefix="$")

    st.markdown(
        f"""
        <div class="panel">
            <b>Current risk rules</b><br>
            <span class="small-note">
            Max total exposure: ${max_total_exposure:,.2f}<br>
            Max per sport: ${max_per_sport:,.2f}<br>
            Max per event: ${max_per_event:,.2f}<br>
            Max per sportsbook: ${max_per_book:,.2f}<br>
            Max props exposure: ${max_props_exposure:,.2f}
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )
