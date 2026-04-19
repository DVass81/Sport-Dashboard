import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="Sports Dashboard",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -----------------------------
# CONFIG
# -----------------------------
TARGET_BOOKS = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "bet365": "Bet365",
    "prizepicks": "PrizePicks",
}
DEFAULT_LEAGUES = ["NBA", "NFL", "MLB", "NHL"]
BET_LOG_FILE = "bet_log.csv"
AI_HISTORY_KEY = "ai_chat_history"

BET_LOG_COLUMNS = [
    "Bet ID",
    "Logged At",
    "Settled At",
    "Sport",
    "Event",
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

# -----------------------------
# STYLING
# -----------------------------
st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(180deg, #f5f9ff 0%, #eaf2ff 100%);
        color: #111827;
    }
    section[data-testid="stSidebar"] {
        background: #f8fbff;
        border-right: 1px solid #d7e3f4;
    }
    .title-main {
        font-size: 2.4rem;
        font-weight: 800;
        color: #0f172a;
        margin-bottom: 0.2rem;
    }
    .subtitle-main {
        font-size: 1rem;
        color: #1d4ed8;
        margin-bottom: 1.2rem;
        font-weight: 600;
    }
    .panel {
        background: white;
        border: 1px solid #dbe8f8;
        border-radius: 18px;
        padding: 16px 18px;
        margin-bottom: 16px;
        box-shadow: 0 8px 22px rgba(15, 23, 42, 0.06);
        color: #111827;
    }
    .hero {
        background: linear-gradient(135deg, #ffffff 0%, #eff6ff 100%);
        border: 1px solid #cfe1fb;
        border-radius: 20px;
        padding: 20px 22px;
        margin-bottom: 16px;
        box-shadow: 0 10px 24px rgba(29, 78, 216, 0.08);
        color: #111827;
    }
    .kpi-card {
        background: white;
        border: 1px solid #dbe8f8;
        border-radius: 16px;
        padding: 14px 16px;
        box-shadow: 0 6px 16px rgba(15, 23, 42, 0.05);
        min-height: 94px;
        color: #111827;
    }
    .kpi-label {
        color: #1d4ed8;
        font-weight: 700;
        font-size: 0.86rem;
        margin-bottom: 6px;
    }
    .kpi-value {
        color: #0f172a;
        font-weight: 800;
        font-size: 1.45rem;
        line-height: 1.2;
    }
    .mini-note {
        color: #334155;
        font-size: 0.86rem;
        margin-top: 4px;
    }
    .bet-card {
        background: white;
        border-left: 6px solid #2563eb;
        border-radius: 16px;
        padding: 14px 16px;
        border-top: 1px solid #dbe8f8;
        border-right: 1px solid #dbe8f8;
        border-bottom: 1px solid #dbe8f8;
        margin-bottom: 12px;
        color: #111827;
    }
    .shop-good { border-left-color: #16a34a; }
    .shop-medium { border-left-color: #f59e0b; }
    .shop-low { border-left-color: #2563eb; }
    .section-title {
        color: #0f172a;
        font-weight: 800;
        font-size: 1.2rem;
        margin: 6px 0 12px 0;
    }
    .small-chip {
        display: inline-block;
        padding: 5px 9px;
        border-radius: 999px;
        background: #dbeafe;
        color: #1e3a8a;
        font-weight: 700;
        font-size: 0.8rem;
        margin-right: 6px;
        margin-bottom: 6px;
    }
    .quick-link {
        display:block;
        text-decoration:none;
        background:white;
        border:1px solid #dbe8f8;
        border-radius:16px;
        padding:18px;
        color:#0f172a !important;
        font-weight:800;
        text-align:center;
        box-shadow: 0 6px 16px rgba(15, 23, 42, 0.05);
    }
    .quick-link:hover { border-color:#93c5fd; box-shadow:0 8px 20px rgba(29,78,216,0.10); }
    .reason-box {
        background: #f8fbff;
        border: 1px solid #dbe8f8;
        border-radius: 12px;
        padding: 12px 14px;
        color: #111827;
    }
    div[data-baseweb="select"] > div,
    div[data-baseweb="base-input"] > div {
        background: white !important;
        color: #111827 !important;
    }
    div[data-baseweb="select"] input,
    div[data-baseweb="base-input"] input {
        color: #111827 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------
# HELPERS
# -----------------------------
def safe_int_from_odds(odds_value) -> Optional[int]:
    try:
        return int(str(odds_value).strip().replace("−", "-"))
    except Exception:
        return None


def american_to_implied(odds_value) -> Optional[float]:
    odds = safe_int_from_odds(odds_value)
    if odds is None:
        return None
    if odds > 0:
        return round(100 / (odds + 100) * 100, 2)
    return round(abs(odds) / (abs(odds) + 100) * 100, 2)


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


def classify_market(market_name, pick, sportsbook):
    text = f"{market_name} {pick}".lower()
    if sportsbook == "PrizePicks":
        return "DFS Prop"
    if "moneyline" in text or text.strip() in {"ml", "winner"}:
        return "Moneyline"
    if "spread" in text or "run line" in text or "puck line" in text or "handicap" in text:
        return "Spread"
    if "team total" in text:
        return "Team Total"
    if "total" in text or "over " in text or "under " in text:
        return "Total"
    if any(word in text for word in ["points", "rebounds", "assists", "player", "threes"]):
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
            return f"{safe_player_name(players, stat_entity_id)} {side_id.title()} {line}"
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

    if stat_entity_id not in simple_entities:
        player_name = safe_player_name(players, stat_entity_id)
        if side_id in {"yes", "no"}:
            return f"{player_name} {side_id.title()}"
        return player_name

    return market_name


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
        "Player Prop": 0.55,
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
    if bucket in {"Moneyline", "Spread", "Total"}:
        parts.append(f"{bucket.lower()} market ranks stronger")
    elif bucket in {"Player Prop", "DFS Prop"}:
        parts.append("prop market keeps sizing conservative")

    mins = row["Minutes To Start"]
    if mins is not None:
        if mins >= 180:
            parts.append("plenty of time before start")
        elif mins >= 60:
            parts.append("moderate time before lock")
        else:
            parts.append("close to lock, so confidence is reduced")

    if row["Sportsbook"] == "PrizePicks":
        parts.append("PrizePicks is treated more cautiously")

    return " • ".join(parts)


def shop_alert_from_gap(gap, books):
    if books >= 3 and gap >= 4:
        return "Strong Shop"
    if books >= 2 and gap >= 2:
        return "Good Shop"
    if gap > 0:
        return "Small Edge"
    return "Flat"


def kpi_card(label, value, note=""):
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">{label}</div>
            <div class="kpi-value">{value}</div>
            <div class="mini-note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_bet_card(row, css_class="shop-low"):
    link_html = f'<br><a href="{row["Link"]}" target="_blank">Open bet page</a>' if row.get("Link") else ""
    st.markdown(
        f"""
        <div class="bet-card {css_class}">
            <b>{row['Pick']}</b><br>
            {row['Event']} · {row['Market']}<br>
            Book: <b>{row['Sportsbook']}</b> · Odds: <b>{row['Odds']}</b><br>
            Edge: <b>{row['Edge %']:.2f}%</b> · Score: <b>{row['Bet Score']:.2f}</b> · Confidence: <b>{row['Confidence']}</b><br>
            Stake: <b>${int(row['Stake To Bet'])}</b> · Status: <b>{row['Final Status']}</b><br>
            Reason: <i>{row['Reason']}</i>
            {link_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


# -----------------------------
# BET LOG STORAGE
# -----------------------------
def ensure_bet_log_file():
    if not os.path.exists(BET_LOG_FILE):
        pd.DataFrame(columns=BET_LOG_COLUMNS).to_csv(BET_LOG_FILE, index=False)


def load_bet_log():
    ensure_bet_log_file()
    try:
        df = pd.read_csv(BET_LOG_FILE)
    except Exception:
        df = pd.DataFrame(columns=BET_LOG_COLUMNS)

    for col in ["Stake", "Implied Prob", "Model Prob", "Edge %", "Bet Score", "PNL"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return df


def save_bet_log(df):
    df.to_csv(BET_LOG_FILE, index=False)


def american_profit(odds_value, stake):
    odds = safe_int_from_odds(odds_value)
    if odds is None:
        return 0.0
    stake = float(stake)
    if odds > 0:
        return round(stake * (odds / 100), 2)
    return round(stake * (100 / abs(odds)), 2)


def log_bet_from_row(row):
    df = load_bet_log()
    duplicate_mask = (
        (df["Event"].astype(str) == str(row["Event"]))
        & (df["Pick"].astype(str) == str(row["Pick"]))
        & (df["Sportsbook"].astype(str) == str(row["Sportsbook"]))
        & (df["Odds"].astype(str) == str(row["Odds"]))
        & (df["Bet Status"].astype(str) == "Pending")
    )
    if duplicate_mask.any():
        return False, "That bet is already logged as pending."

    stake_value = float(row.get("Stake To Bet", row.get("Recommended Bet", 0)))
    bet_id = str(uuid.uuid4())[:8].upper()
    new_row = {
        "Bet ID": bet_id,
        "Logged At": datetime.now().strftime("%Y-%m-%d %I:%M:%S %p"),
        "Settled At": "",
        "Sport": row["Sport"],
        "Event": row["Event"],
        "Market Bucket": row["Market Bucket"],
        "Market": row["Market"],
        "Pick": row["Pick"],
        "Sportsbook": row["Sportsbook"],
        "Odds": row["Odds"],
        "Stake": stake_value,
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
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    save_bet_log(df)
    return True, f"Bet logged successfully. Bet ID: {bet_id}"


def settle_bet(bet_id, result):
    df = load_bet_log()
    if df.empty:
        return False, "No bet history found."
    mask = df["Bet ID"].astype(str) == str(bet_id)
    if not mask.any():
        return False, "Bet ID not found."
    idx = df.index[mask][0]
    stake = float(df.loc[idx, "Stake"])
    odds = str(df.loc[idx, "Odds"])
    if result == "Win":
        pnl = american_profit(odds, stake)
    elif result == "Loss":
        pnl = round(-stake, 2)
    else:
        pnl = 0.0
    df.loc[idx, "Result"] = result
    df.loc[idx, "PNL"] = pnl
    df.loc[idx, "Bet Status"] = "Settled"
    df.loc[idx, "Settled At"] = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
    save_bet_log(df)
    return True, f"Bet {bet_id} settled as {result}. PNL: ${pnl:,.2f}"


# -----------------------------
# LIVE ODDS
# -----------------------------
@st.cache_data(ttl=900, show_spinner="Loading live odds...")
def fetch_events(leagues):
    api_key = st.secrets.get("SPORTS_GAME_ODDS_API_KEY", "")
    if not api_key:
        return [], "Missing SPORTS_GAME_ODDS_API_KEY in Streamlit secrets."

    url = "https://api.sportsgameodds.com/v2/events/"
    headers = {"x-api-key": api_key}
    params = {"leagueID": ",".join(leagues), "oddsAvailable": "true", "limit": 100}

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
                deep_link = quote.get("deeplink") or event_links.get(book_id, "")
                sportsbook_name = TARGET_BOOKS[book_id]
                market_bucket = classify_market(market_name, pick_label, sportsbook_name)

                rows.append(
                    {
                        "Event ID": event_id,
                        "Odd ID": odd_id,
                        "Sport": league_id or sport_id,
                        "Event": event_name,
                        "Start Time": starts_at,
                        "Minutes To Start": minutes_to_start(starts_at),
                        "Market": market_name,
                        "Market Bucket": market_bucket,
                        "Pick": pick_label,
                        "Sportsbook": sportsbook_name,
                        "Sportsbook ID": book_id,
                        "Odds": str(odds_value),
                        "Implied Prob": implied_prob,
                        "Line": quote.get("spread") or quote.get("overUnder") or "",
                        "Last Update": quote.get("lastUpdatedAt", ""),
                        "Link": deep_link,
                    }
                )
    return pd.DataFrame(rows)


def apply_scoring(df, min_bet, max_bet):
    if df.empty:
        return df

    market_stats = (
        df.groupby(["Event ID", "Odd ID"])["Implied Prob"]
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
    scored = df.merge(market_stats, on=["Event ID", "Odd ID"], how="left")
    scored["Prob StdDev"] = scored["Prob StdDev"].fillna(0.0)
    scored["Model Prob"] = scored["Consensus Prob"].round(2)
    scored["Edge %"] = (scored["Consensus Prob"] - scored["Implied Prob"]).round(2)
    scored["Best Line Gap %"] = (scored["Worst Price Prob"] - scored["Implied Prob"]).round(2)
    scored["Is Best Price"] = scored["Implied Prob"] <= (scored["Best Price Prob"] + 0.0001)
    scored["Market Weight"] = scored["Market Bucket"].apply(market_weight)
    scored["Time Penalty"] = scored["Minutes To Start"].apply(time_penalty)
    scored["Book Penalty"] = scored["Sportsbook"].apply(book_penalty)
    scored["Books Bonus"] = scored["Books Quoting"].apply(lambda x: min((x - 1) * 0.55, 2.20))
    scored["Bet Score"] = (
        scored["Edge %"] * 0.95
        + scored["Best Line Gap %"] * 0.35
        + scored["Books Bonus"]
        + scored["Market Weight"]
        + scored["Time Penalty"]
        + scored["Book Penalty"]
    ).round(2)
    scored["Confidence"] = scored["Bet Score"].apply(confidence_from_score)
    scored["Recommended Bet"] = scored.apply(
        lambda row: bet_size_from_score(row["Edge %"], row["Bet Score"], min_bet, max_bet),
        axis=1,
    )
    scored["Status"] = scored["Recommended Bet"].apply(lambda x: "Bet" if x > 0 else "No Bet")
    scored["Reason"] = scored.apply(build_reason, axis=1)
    return scored


def apply_exposure_cap(df, max_total_exposure, min_bet, max_event_exposure, max_book_exposure, max_prop_exposure):
    df = df.copy()
    df["Stake To Bet"] = 0
    df["Exposure Status"] = "No Bet"
    df["Final Status"] = "No Bet"

    total_remaining = float(max_total_exposure)
    event_used = {}
    book_used = {}
    prop_used = 0.0

    candidate_idx = df[df["Status"] == "Bet"].sort_values(
        ["Bet Score", "Edge %", "Books Quoting"], ascending=[False, False, False]
    ).index

    for idx in candidate_idx:
        if total_remaining < float(min_bet):
            df.at[idx, "Exposure Status"] = "Exposure Cap Reached"
            df.at[idx, "Final Status"] = "Pass"
            continue

        event_key = str(df.at[idx, "Event ID"])
        book_key = str(df.at[idx, "Sportsbook"])
        market_bucket = str(df.at[idx, "Market Bucket"])
        suggested = float(df.at[idx, "Recommended Bet"])

        remaining_by_event = max(0.0, float(max_event_exposure) - event_used.get(event_key, 0.0))
        remaining_by_book = max(0.0, float(max_book_exposure) - book_used.get(book_key, 0.0))
        remaining_by_prop = float("inf")
        if market_bucket in {"Player Prop", "DFS Prop"}:
            remaining_by_prop = max(0.0, float(max_prop_exposure) - prop_used)

        allocation = min(suggested, total_remaining, remaining_by_event, remaining_by_book, remaining_by_prop)
        allocation = int(allocation)

        if allocation < float(min_bet):
            reasons = []
            if remaining_by_event < float(min_bet):
                reasons.append("Event Cap Reached")
            if remaining_by_book < float(min_bet):
                reasons.append("Book Cap Reached")
            if market_bucket in {"Player Prop", "DFS Prop"} and remaining_by_prop < float(min_bet):
                reasons.append("Prop Cap Reached")
            if not reasons:
                reasons.append("Exposure Cap Reached")
            df.at[idx, "Exposure Status"] = " / ".join(reasons)
            df.at[idx, "Final Status"] = "Pass"
            continue

        df.at[idx, "Stake To Bet"] = allocation
        df.at[idx, "Final Status"] = "Bet"
        if allocation < suggested:
            df.at[idx, "Exposure Status"] = "Trimmed To Fit Cap"
        else:
            df.at[idx, "Exposure Status"] = "Within Cap"

        total_remaining -= allocation
        event_used[event_key] = event_used.get(event_key, 0.0) + allocation
        book_used[book_key] = book_used.get(book_key, 0.0) + allocation
        if market_bucket in {"Player Prop", "DFS Prop"}:
            prop_used += allocation

    return df


def build_compare_table(df):
    if df.empty:
        return pd.DataFrame()

    group_cols = ["Event ID", "Odd ID", "Sport", "Event", "Market Bucket", "Market", "Pick"]
    price_stats = (
        df.groupby(group_cols)
        .agg(
            Books_Quoting=("Sportsbook", "nunique"),
            Best_Implied_Prob=("Implied Prob", "min"),
            Worst_Implied_Prob=("Implied Prob", "max"),
        )
        .reset_index()
    )
    price_stats["Line Gap %"] = (price_stats["Worst_Implied_Prob"] - price_stats["Best_Implied_Prob"]).round(2)

    idx_best = df.groupby(["Event ID", "Odd ID"])["Implied Prob"].idxmin()
    best_rows = df.loc[idx_best, [
        "Event ID", "Odd ID", "Sportsbook", "Odds", "Edge %", "Bet Score", "Confidence",
        "Stake To Bet", "Final Status", "Exposure Status", "Reason", "Link"
    ]].copy().rename(columns={
        "Sportsbook": "Best Sportsbook",
        "Odds": "Best Odds",
        "Edge %": "Best Edge %",
        "Bet Score": "Best Bet Score",
        "Confidence": "Best Confidence",
        "Reason": "Best Reason",
        "Link": "Best Link",
    })

    pivot = df.pivot_table(index=group_cols, columns="Sportsbook", values="Odds", aggfunc="first").reset_index()
    compare = pivot.merge(price_stats, on=group_cols, how="left").merge(best_rows, on=["Event ID", "Odd ID"], how="left")

    for col in ["DraftKings", "FanDuel", "Bet365", "PrizePicks"]:
        if col not in compare.columns:
            compare[col] = ""

    compare["Shop Alert"] = compare.apply(lambda row: shop_alert_from_gap(row["Line Gap %"], row["Books_Quoting"]), axis=1)
    return compare.sort_values(["Best Bet Score", "Line Gap %"], ascending=[False, False]).reset_index(drop=True)


def compute_clv_table(pending_log, current_df):
    if pending_log.empty or current_df.empty:
        return pd.DataFrame()
    rows = []
    for _, bet in pending_log.iterrows():
        matches = current_df[
            (current_df["Event"] == bet["Event"])
            & (current_df["Pick"] == bet["Pick"])
            & (current_df["Sportsbook"] == bet["Sportsbook"])
        ]
        if matches.empty:
            continue
        cur = matches.iloc[0]
        logged_ip = american_to_implied(bet["Odds"])
        current_ip = cur["Implied Prob"]
        if logged_ip is None:
            continue
        clv = round(logged_ip - current_ip, 2)
        rows.append({
            "Bet ID": bet["Bet ID"],
            "Event": bet["Event"],
            "Pick": bet["Pick"],
            "Sportsbook": bet["Sportsbook"],
            "Logged Odds": bet["Odds"],
            "Current Odds": cur["Odds"],
            "Observed CLV %": clv,
            "Signal": "Beat Market" if clv > 0 else ("Behind Market" if clv < 0 else "Flat"),
        })
    return pd.DataFrame(rows)


def get_live_board(leagues, sportsbooks, market_buckets, confidence_levels, min_bet, max_bet,
                   max_total_exposure, max_event_exposure, max_book_exposure, max_prop_exposure, only_bets=False):
    events, error_message = fetch_events(leagues)
    if error_message:
        return pd.DataFrame(), pd.DataFrame(), error_message
    raw_df = flatten_events_to_rows(events)
    if raw_df.empty:
        return pd.DataFrame(), pd.DataFrame(), "No live odds came back for the leagues selected."

    scored_df = apply_scoring(raw_df, min_bet=min_bet, max_bet=max_bet)
    filtered_df = scored_df[
        scored_df["Sportsbook"].isin(sportsbooks)
        & scored_df["Market Bucket"].isin(market_buckets)
        & scored_df["Confidence"].isin(confidence_levels)
    ].copy()

    filtered_df = apply_exposure_cap(
        filtered_df,
        max_total_exposure=max_total_exposure,
        min_bet=min_bet,
        max_event_exposure=max_event_exposure,
        max_book_exposure=max_book_exposure,
        max_prop_exposure=max_prop_exposure,
    )

    if only_bets:
        filtered_df = filtered_df[filtered_df["Final Status"] == "Bet"].copy()

    filtered_df = filtered_df.sort_values(["Bet Score", "Edge %", "Books Quoting"], ascending=[False, False, False]).reset_index(drop=True)
    compare_df = build_compare_table(filtered_df)
    return filtered_df, compare_df, ""


# -----------------------------
# AI
# -----------------------------
def call_openai_assistant(prompt: str, context: str = "") -> str:
    api_key = st.secrets.get("OPENAI_API_KEY", "")
    model = st.secrets.get("OPENAI_MODEL", "gpt-4.1-mini")
    if not api_key:
        return "Add OPENAI_API_KEY to Streamlit Secrets to use the AI Assistant tab."

    system_text = (
        "You are a sports betting dashboard assistant. Use the provided dashboard context. "
        "Be practical, concise, and explain risk clearly. Do not claim certainty."
    )
    user_text = f"Dashboard context:\n{context}\n\nUser request:\n{prompt}"

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
                    {"role": "system", "content": [{"type": "text", "text": system_text}]},
                    {"role": "user", "content": [{"type": "text", "text": user_text}]},
                ],
            },
            timeout=45,
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data.get("output_text"), str) and data.get("output_text"):
            return data["output_text"]
        # fallback parse
        outputs = data.get("output", [])
        texts = []
        for item in outputs:
            for part in item.get("content", []):
                if part.get("type") == "output_text":
                    texts.append(part.get("text", ""))
        return "\n".join([t for t in texts if t]) or "No response returned."
    except Exception as exc:
        return f"AI request failed: {exc}"


# -----------------------------
# HEADER & SIDEBAR
# -----------------------------
st.markdown('<div class="title-main">Sports Betting Dashboard</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle-main">Clean layout, readable text, sportsbook tabs, tracking, compare lines, and AI help.</div>', unsafe_allow_html=True)

st.sidebar.title("Dashboard Controls")
bankroll = st.sidebar.number_input("Starting Bankroll", min_value=1.0, value=500.0, step=25.0, key="sb_bankroll")
min_bet = st.sidebar.number_input("Minimum Bet", min_value=1.0, value=1.0, step=1.0, key="sb_min_bet")
max_bet = st.sidebar.number_input("Maximum Bet", min_value=1.0, value=10.0, step=1.0, key="sb_max_bet")
max_total_exposure = st.sidebar.number_input("Max Total Exposure", min_value=1.0, value=40.0, step=5.0, key="sb_total_exp")
max_event_exposure = st.sidebar.number_input("Max Exposure Per Event", min_value=1.0, value=10.0, step=1.0, key="sb_event_exp")
max_book_exposure = st.sidebar.number_input("Max Exposure Per Sportsbook", min_value=1.0, value=15.0, step=1.0, key="sb_book_exp")
max_prop_exposure = st.sidebar.number_input("Max Exposure On Props", min_value=1.0, value=12.0, step=1.0, key="sb_prop_exp")

league_filter = st.sidebar.multiselect("Leagues", options=DEFAULT_LEAGUES, default=DEFAULT_LEAGUES, key="sb_leagues")
book_filter = st.sidebar.multiselect("Sportsbooks", options=list(TARGET_BOOKS.values()), default=list(TARGET_BOOKS.values()), key="sb_books")
market_bucket_options = ["Moneyline", "Spread", "Total", "Team Total", "Player Prop", "DFS Prop", "Other"]
market_bucket_filter = st.sidebar.multiselect("Market Types", options=market_bucket_options, default=market_bucket_options, key="sb_markets")
confidence_options = ["Elite", "High", "Medium", "Low"]
confidence_filter = st.sidebar.multiselect("Confidence Levels", options=confidence_options, default=confidence_options, key="sb_conf")
only_bets = st.sidebar.toggle("Show final bets only", value=False, key="sb_only_bets")

if st.sidebar.button("Refresh now", key="sb_refresh"):
    st.cache_data.clear()
    st.rerun()

current_df, compare_df, live_error = get_live_board(
    leagues=league_filter,
    sportsbooks=book_filter,
    market_buckets=market_bucket_filter,
    confidence_levels=confidence_filter,
    min_bet=min_bet,
    max_bet=max_bet,
    max_total_exposure=max_total_exposure,
    max_event_exposure=max_event_exposure,
    max_book_exposure=max_book_exposure,
    max_prop_exposure=max_prop_exposure,
    only_bets=only_bets,
)

if live_error:
    st.warning(live_error)
    st.info("Add SPORTS_GAME_ODDS_API_KEY in Streamlit Secrets, then click Refresh now.")
    st.stop()

bet_log = load_bet_log()
pending_df = bet_log[bet_log["Bet Status"] == "Pending"].copy()
settled_df = bet_log[bet_log["Bet Status"] == "Settled"].copy()
clv_df = compute_clv_table(pending_df, current_df)

live_bets = current_df[current_df["Final Status"] == "Bet"].copy()
strong_shop_count = int((compare_df["Shop Alert"] == "Strong Shop").sum()) if not compare_df.empty else 0
open_suggested_risk = float(live_bets["Stake To Bet"].sum()) if not live_bets.empty else 0.0
realized_pnl = float(settled_df["PNL"].sum()) if not settled_df.empty else 0.0
current_bankroll = bankroll + realized_pnl
roi = (realized_pnl / float(settled_df["Stake"].sum()) * 100) if not settled_df.empty and float(settled_df["Stake"].sum()) > 0 else 0.0
avg_edge = float(live_bets["Edge %"].mean()) if not live_bets.empty else 0.0
avg_score = float(live_bets["Bet Score"].mean()) if not live_bets.empty else 0.0

# -----------------------------
# KPI RIBBON
# -----------------------------
k1, k2, k3, k4, k5, k6 = st.columns(6)
with k1:
    kpi_card("Current Bankroll", f"${current_bankroll:,.2f}", f"Started at ${bankroll:,.2f}")
with k2:
    kpi_card("Realized P/L", f"${realized_pnl:,.2f}", f"ROI {roi:.1f}%")
with k3:
    kpi_card("Open Suggested Risk", f"${open_suggested_risk:,.0f}", f"Cap ${max_total_exposure:,.0f}")
with k4:
    kpi_card("Final Bets", f"{len(live_bets)}", f"Avg edge {avg_edge:.2f}%")
with k5:
    kpi_card("Strong Shop Alerts", f"{strong_shop_count}", f"Avg score {avg_score:.2f}")
with k6:
    kpi_card("Pending Logged Bets", f"{len(pending_df)}", f"Settled {len(settled_df)}")

# -----------------------------
# HERO
# -----------------------------
best_row = live_bets.iloc[0] if not live_bets.empty else None
hero_left, hero_right = st.columns([2, 1])
with hero_left:
    st.markdown('<div class="hero">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Top Live Bet</div>', unsafe_allow_html=True)
    if best_row is not None:
        render_bet_card(best_row, "shop-good" if best_row["Edge %"] >= 3 else "shop-medium")
    else:
        st.info("No bets qualify right now under the current rules.")
    st.markdown('</div>', unsafe_allow_html=True)
with hero_right:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Live Notes</div>', unsafe_allow_html=True)
    st.markdown(
        f"""
        <span class="small-chip">Readable light theme</span>
        <span class="small-chip">No heatmaps</span>
        <span class="small-chip">No Plotly</span>
        <span class="small-chip">Tabs preserved</span>
        <span class="small-chip">AI Assistant</span>
        <span class="small-chip">Quick Links</span>
        <div style="margin-top:10px;color:#334155;">
        Data is cached for 15 minutes. Use the refresh button in the sidebar if you want a manual refresh.
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('</div>', unsafe_allow_html=True)

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

# Overview
with tabs[0]:
    left, right = st.columns([1.3, 1])
    with left:
        st.markdown('<div class="section-title">Top Final Bets</div>', unsafe_allow_html=True)
        if live_bets.empty:
            st.info("No final bets right now.")
        else:
            for _, row in live_bets.head(5).iterrows():
                css_class = "shop-good" if row["Edge %"] >= 3 else ("shop-medium" if row["Edge %"] >= 1.5 else "shop-low")
                render_bet_card(row, css_class)

    with right:
        st.markdown('<div class="section-title">What To Watch</div>', unsafe_allow_html=True)
        exposure_by_book = live_bets.groupby("Sportsbook")["Stake To Bet"].sum().reset_index().sort_values("Stake To Bet", ascending=False) if not live_bets.empty else pd.DataFrame(columns=["Sportsbook", "Stake To Bet"])
        exposure_by_sport = live_bets.groupby("Sport")["Stake To Bet"].sum().reset_index().sort_values("Stake To Bet", ascending=False) if not live_bets.empty else pd.DataFrame(columns=["Sport", "Stake To Bet"])
        if not exposure_by_book.empty:
            st.markdown('<div class="panel"><b>Exposure by Sportsbook</b></div>', unsafe_allow_html=True)
            st.dataframe(exposure_by_book, use_container_width=True, hide_index=True)
        if not exposure_by_sport.empty:
            st.markdown('<div class="panel"><b>Exposure by Sport</b></div>', unsafe_allow_html=True)
            st.dataframe(exposure_by_sport, use_container_width=True, hide_index=True)
        if not clv_df.empty:
            st.markdown('<div class="panel"><b>Observed CLV Snapshot</b></div>', unsafe_allow_html=True)
            st.dataframe(clv_df.head(8), use_container_width=True, hide_index=True)

# Best Bets
with tabs[1]:
    st.markdown('<div class="section-title">Best Bets Board</div>', unsafe_allow_html=True)
    if current_df.empty:
        st.info("No rows available.")
    else:
        display_df = current_df[[
            "Sport", "Event", "Market Bucket", "Market", "Pick", "Sportsbook", "Odds",
            "Implied Prob", "Model Prob", "Edge %", "Best Line Gap %", "Books Quoting",
            "Bet Score", "Confidence", "Recommended Bet", "Stake To Bet", "Exposure Status",
            "Final Status", "Reason", "Link"
        ]].copy()
        st.dataframe(display_df, use_container_width=True, hide_index=True)

        final_candidates = current_df[current_df["Final Status"] == "Bet"].copy()
        st.markdown('<div class="section-title">Explain A Selected Final Bet</div>', unsafe_allow_html=True)
        if final_candidates.empty:
            st.info("No final bets available to explain.")
        else:
            final_candidates["Explain Label"] = final_candidates.apply(
                lambda row: f"{row['Event']} | {row['Pick']} | {row['Sportsbook']} {row['Odds']} | Score {row['Bet Score']:.2f}", axis=1
            )
            selected_label = st.selectbox("Choose a final bet to explain", options=final_candidates["Explain Label"].tolist(), key="best_bets_explain_select")
            selected_row = final_candidates.loc[final_candidates["Explain Label"] == selected_label].iloc[0]
            st.markdown(
                f"""
                <div class="reason-box">
                <b>Why the dashboard likes this bet:</b><br><br>
                Event: <b>{selected_row['Event']}</b><br>
                Pick: <b>{selected_row['Pick']}</b><br>
                Sportsbook: <b>{selected_row['Sportsbook']}</b><br>
                Edge: <b>{selected_row['Edge %']:.2f}%</b><br>
                Bet Score: <b>{selected_row['Bet Score']:.2f}</b><br>
                Confidence: <b>{selected_row['Confidence']}</b><br>
                Stake To Bet: <b>${int(selected_row['Stake To Bet'])}</b><br>
                Exposure Status: <b>{selected_row['Exposure Status']}</b><br><br>
                <b>Reason:</b> {selected_row['Reason']}
                </div>
                """,
                unsafe_allow_html=True,
            )

# Compare Lines
with tabs[2]:
    st.markdown('<div class="section-title">Compare Lines / Best Book</div>', unsafe_allow_html=True)
    if compare_df.empty:
        st.info("No comparison rows available for the current filters.")
    else:
        compare_display = compare_df[[
            "Sport", "Event", "Market Bucket", "Market", "Pick",
            "DraftKings", "FanDuel", "Bet365", "PrizePicks",
            "Best Sportsbook", "Best Odds", "Books_Quoting", "Line Gap %",
            "Shop Alert", "Best Bet Score", "Best Confidence", "Stake To Bet",
            "Exposure Status", "Final Status", "Best Reason", "Best Link"
        ]].copy()
        st.dataframe(compare_display, use_container_width=True, hide_index=True)

        st.markdown('<div class="section-title">Top Shopping Opportunities</div>', unsafe_allow_html=True)
        for _, row in compare_df.head(5).iterrows():
            css = "shop-good" if row["Shop Alert"] == "Strong Shop" else ("shop-medium" if row["Shop Alert"] == "Good Shop" else "shop-low")
            st.markdown(
                f"""
                <div class="bet-card {css}">
                    <b>{row['Pick']}</b><br>
                    {row['Event']} · {row['Market']}<br>
                    Best Book: <b>{row['Best Sportsbook']}</b> at <b>{row['Best Odds']}</b><br>
                    DraftKings: <b>{row.get('DraftKings','')}</b> · FanDuel: <b>{row.get('FanDuel','')}</b> · Bet365: <b>{row.get('Bet365','')}</b> · PrizePicks: <b>{row.get('PrizePicks','')}</b><br>
                    Line Gap: <b>{row['Line Gap %']:.2f}%</b> · Shop Alert: <b>{row['Shop Alert']}</b> · Final Status: <b>{row['Final Status']}</b><br>
                    Reason: <i>{row['Best Reason']}</i>
                </div>
                """,
                unsafe_allow_html=True,
            )

# Quick Links
with tabs[3]:
    st.markdown('<div class="section-title">Quick Links</div>', unsafe_allow_html=True)
    q1, q2, q3, q4 = st.columns(4)
    with q1:
        st.markdown('<a class="quick-link" target="_blank" href="https://sportsbook.draftkings.com/">DraftKings</a>', unsafe_allow_html=True)
    with q2:
        st.markdown('<a class="quick-link" target="_blank" href="https://sportsbook.fanduel.com/">FanDuel</a>', unsafe_allow_html=True)
    with q3:
        st.markdown('<a class="quick-link" target="_blank" href="https://www.bet365.com/">Bet365</a>', unsafe_allow_html=True)
    with q4:
        st.markdown('<a class="quick-link" target="_blank" href="https://app.prizepicks.com/">PrizePicks</a>', unsafe_allow_html=True)

    st.markdown('<div class="section-title">Quick Notes</div>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="panel">
        Use this tab when you already know the book you want. The sportsbook tabs are still better for filtering the dashboard's current opportunities by book.
        </div>
        """,
        unsafe_allow_html=True,
    )

# Sportsbook tab helper

def sportsbook_tab(book_name, key_prefix):
    st.markdown(f'<div class="section-title">{book_name} Opportunities</div>', unsafe_allow_html=True)
    book_df = current_df[current_df["Sportsbook"] == book_name].copy()
    if book_df.empty:
        st.info(f"No rows available for {book_name}.")
        return
    summary = book_df[book_df["Final Status"] == "Bet"]
    c1, c2, c3 = st.columns(3)
    with c1:
        kpi_card("Final Bets", f"{len(summary)}", "Rows passing all current rules")
    with c2:
        avg_e = float(summary["Edge %"].mean()) if not summary.empty else 0.0
        kpi_card("Avg Edge", f"{avg_e:.2f}%", "Only final bets")
    with c3:
        max_s = int(summary["Stake To Bet"].max()) if not summary.empty else 0
        kpi_card("Max Stake", f"${max_s}", "Current cap-adjusted size")

    st.dataframe(book_df[[
        "Sport", "Event", "Market Bucket", "Market", "Pick", "Odds", "Edge %",
        "Bet Score", "Confidence", "Stake To Bet", "Exposure Status", "Final Status", "Reason", "Link"
    ]], use_container_width=True, hide_index=True)

    explain_candidates = book_df[book_df["Final Status"] == "Bet"].copy()
    if not explain_candidates.empty:
        explain_candidates["Label"] = explain_candidates.apply(
            lambda row: f"{row['Event']} | {row['Pick']} | {row['Odds']} | Score {row['Bet Score']:.2f}", axis=1
        )
        chosen = st.selectbox(f"Explain a {book_name} bet", explain_candidates["Label"].tolist(), key=f"{key_prefix}_explain")
        row = explain_candidates.loc[explain_candidates["Label"] == chosen].iloc[0]
        st.markdown(f'<div class="reason-box"><b>Reason:</b> {row["Reason"]}</div>', unsafe_allow_html=True)

with tabs[4]:
    sportsbook_tab("DraftKings", "dk")
with tabs[5]:
    sportsbook_tab("FanDuel", "fd")
with tabs[6]:
    sportsbook_tab("Bet365", "b365")
with tabs[7]:
    sportsbook_tab("PrizePicks", "pp")

# AI Assistant
with tabs[8]:
    st.markdown('<div class="section-title">AI Betting Assistant</div>', unsafe_allow_html=True)
    if AI_HISTORY_KEY not in st.session_state:
        st.session_state[AI_HISTORY_KEY] = []

    preset_col1, preset_col2, preset_col3, preset_col4 = st.columns(4)
    presets = {
        "ai_safe": "What are the safest bets on the board right now?",
        "ai_edge": "Which bets have the strongest edge right now?",
        "ai_exposure": "Where am I overexposed right now?",
        "ai_compare": "Compare DraftKings and FanDuel based on the current board.",
    }
    with preset_col1:
        if st.button("Safest Bets", key="ai_btn_safe"):
            st.session_state["ai_preset_prompt"] = presets["ai_safe"]
    with preset_col2:
        if st.button("Strongest Edge", key="ai_btn_edge"):
            st.session_state["ai_preset_prompt"] = presets["ai_edge"]
    with preset_col3:
        if st.button("Exposure Check", key="ai_btn_exposure"):
            st.session_state["ai_preset_prompt"] = presets["ai_exposure"]
    with preset_col4:
        if st.button("Compare Books", key="ai_btn_compare"):
            st.session_state["ai_preset_prompt"] = presets["ai_compare"]

    context_rows = current_df.head(20)[[
        "Sport", "Event", "Market", "Pick", "Sportsbook", "Odds", "Edge %", "Bet Score", "Confidence", "Stake To Bet", "Reason"
    ]].to_dict("records") if not current_df.empty else []
    context_text = f"Top board rows: {context_rows}\nPending bets: {pending_df.head(10).to_dict('records')}\nSettled bets summary: total={len(settled_df)}, realized_pnl={realized_pnl}"

    for msg in st.session_state[AI_HISTORY_KEY]:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    preset_prompt = st.session_state.pop("ai_preset_prompt", None)
    user_prompt = preset_prompt or st.chat_input("Ask the AI about today’s board", key="ai_chat_input")

    if user_prompt:
        st.session_state[AI_HISTORY_KEY].append({"role": "user", "content": user_prompt})
        with st.chat_message("user"):
            st.write(user_prompt)
        answer = call_openai_assistant(user_prompt, context_text)
        st.session_state[AI_HISTORY_KEY].append({"role": "assistant", "content": answer})
        with st.chat_message("assistant"):
            st.write(answer)

    ai_candidates = current_df[current_df["Final Status"] == "Bet"].copy()
    st.markdown('<div class="section-title">Explain Selected Bet With AI</div>', unsafe_allow_html=True)
    if ai_candidates.empty:
        st.info("No final bets available to send to AI.")
    else:
        ai_candidates["AI Label"] = ai_candidates.apply(
            lambda row: f"{row['Event']} | {row['Pick']} | {row['Sportsbook']} {row['Odds']}", axis=1
        )
        ai_pick = st.selectbox("Choose a final bet", ai_candidates["AI Label"].tolist(), key="ai_bet_select")
        if st.button("Explain selected bet with AI", key="ai_explain_bet"):
            chosen = ai_candidates.loc[ai_candidates["AI Label"] == ai_pick].iloc[0]
            prompt = (
                f"Explain this bet in plain English and tell me the good, the bad, the risk level, and whether the stake size makes sense: {chosen.to_dict()}"
            )
            answer = call_openai_assistant(prompt, context_text)
            st.markdown(f'<div class="reason-box">{answer}</div>', unsafe_allow_html=True)

# Tracker
with tabs[9]:
    st.markdown('<div class="section-title">Bet Tracker</div>', unsafe_allow_html=True)
    log_col, settle_col = st.columns(2)

    with log_col:
        st.markdown('<div class="panel"><b>Log Final Bet</b><br>Pick a current final bet and save it to your tracked history.</div>', unsafe_allow_html=True)
        log_candidates = current_df[current_df["Final Status"] == "Bet"].copy()
        if log_candidates.empty:
            st.info("No final bets available to log.")
        else:
            log_candidates["Log Label"] = log_candidates.apply(
                lambda row: f"{row['Event']} | {row['Pick']} | {row['Sportsbook']} {row['Odds']} | Stake ${int(row['Stake To Bet'])}", axis=1
            )
            with st.form("log_bet_form_safe"):
                selected_log = st.selectbox("Choose a final bet", log_candidates["Log Label"].tolist(), key="tracker_log_select")
                submitted_log = st.form_submit_button("Log Selected Bet")
                if submitted_log:
                    selected_row = log_candidates.loc[log_candidates["Log Label"] == selected_log].iloc[0]
                    ok, msg = log_bet_from_row(selected_row)
                    if ok:
                        st.success(msg)
                    else:
                        st.warning(msg)

    with settle_col:
        st.markdown('<div class="panel"><b>Settle Pending Bet</b><br>Mark a logged bet as Win, Loss, or Push.</div>', unsafe_allow_html=True)
        pending_live = load_bet_log()
        pending_live = pending_live[pending_live["Bet Status"] == "Pending"].copy()
        if pending_live.empty:
            st.info("No pending bets to settle.")
        else:
            pending_live["Settle Label"] = pending_live.apply(
                lambda row: f"{row['Bet ID']} | {row['Event']} | {row['Pick']} | {row['Sportsbook']} {row['Odds']} | Stake ${row['Stake']:,.2f}", axis=1
            )
            with st.form("settle_bet_form_safe"):
                selected_settle = st.selectbox("Choose a pending bet", pending_live["Settle Label"].tolist(), key="tracker_settle_select")
                settle_result = st.radio("Result", ["Win", "Loss", "Push"], horizontal=True, key="tracker_settle_radio")
                submitted_settle = st.form_submit_button("Settle Bet")
                if submitted_settle:
                    bet_id = selected_settle.split(" | ")[0]
                    ok, msg = settle_bet(bet_id, settle_result)
                    if ok:
                        st.success(msg)
                    else:
                        st.warning(msg)

    st.markdown('<div class="section-title">Pending Bets</div>', unsafe_allow_html=True)
    pending_view = load_bet_log()
    pending_view = pending_view[pending_view["Bet Status"] == "Pending"].copy()
    if pending_view.empty:
        st.info("No pending bets currently logged.")
    else:
        st.dataframe(pending_view[[
            "Bet ID", "Logged At", "Sport", "Event", "Pick", "Sportsbook", "Odds", "Stake", "Confidence", "Bet Score", "Reason"
        ]], use_container_width=True, hide_index=True)

# Results
with tabs[10]:
    st.markdown('<div class="section-title">Results</div>', unsafe_allow_html=True)
    results_df = load_bet_log()
    settled_results = results_df[results_df["Bet Status"] == "Settled"].copy()
    if settled_results.empty:
        st.info("No settled bets yet. Log and settle a few bets to build the results page.")
    else:
        graded = settled_results[settled_results["Result"].isin(["Win", "Loss"])].copy()
        wins = int((settled_results["Result"] == "Win").sum())
        losses = int((settled_results["Result"] == "Loss").sum())
        pushes = int((settled_results["Result"] == "Push").sum())
        total_profit = float(settled_results["PNL"].sum())
        total_staked = float(settled_results["Stake"].sum())
        res_roi = (total_profit / total_staked * 100) if total_staked > 0 else 0.0
        win_rate = ((wins / len(graded)) * 100) if len(graded) > 0 else 0.0

        r1, r2, r3, r4, r5 = st.columns(5)
        with r1:
            kpi_card("Settled Bets", f"{len(settled_results)}", "Tracked history")
        with r2:
            kpi_card("Win Rate", f"{win_rate:.1f}%", f"W-L-P {wins}-{losses}-{pushes}")
        with r3:
            kpi_card("Profit / Loss", f"${total_profit:,.2f}", f"ROI {res_roi:.1f}%")
        with r4:
            avg_stake = float(settled_results["Stake"].mean()) if not settled_results.empty else 0.0
            kpi_card("Average Stake", f"${avg_stake:,.2f}", "Across settled bets")
        with r5:
            avg_score_set = float(settled_results["Bet Score"].mean()) if not settled_results.empty else 0.0
            kpi_card("Average Score", f"{avg_score_set:.2f}", "Across settled bets")

        by_book = settled_results.groupby("Sportsbook").agg(Total_PNL=("PNL", "sum"), Bets=("Bet ID", "count")).reset_index().sort_values("Total_PNL", ascending=False)
        by_market = settled_results.groupby("Market Bucket").agg(Total_PNL=("PNL", "sum"), Bets=("Bet ID", "count")).reset_index().sort_values("Total_PNL", ascending=False)
        by_conf = graded.assign(WinFlag=graded["Result"].eq("Win").astype(int)).groupby("Confidence").agg(Hit_Rate=("WinFlag", "mean"), Bets=("Bet ID", "count")).reset_index()
        by_conf["Hit_Rate"] = (by_conf["Hit_Rate"] * 100).round(1)

        c1, c2 = st.columns(2)
        with c1:
            st.markdown('<div class="panel"><b>Profit by Sportsbook</b></div>', unsafe_allow_html=True)
            st.dataframe(by_book, use_container_width=True, hide_index=True)
            st.markdown('<div class="panel"><b>Hit Rate by Confidence</b></div>', unsafe_allow_html=True)
            st.dataframe(by_conf, use_container_width=True, hide_index=True)
        with c2:
            st.markdown('<div class="panel"><b>Profit by Market Type</b></div>', unsafe_allow_html=True)
            st.dataframe(by_market, use_container_width=True, hide_index=True)
            if not clv_df.empty:
                st.markdown('<div class="panel"><b>Observed CLV on Pending Bets</b></div>', unsafe_allow_html=True)
                st.dataframe(clv_df, use_container_width=True, hide_index=True)

        st.markdown('<div class="section-title">Settled Bet History</div>', unsafe_allow_html=True)
        st.dataframe(settled_results[[
            "Bet ID", "Logged At", "Settled At", "Sport", "Event", "Pick", "Sportsbook", "Odds", "Stake", "Result", "PNL", "Confidence", "Bet Score"
        ]].sort_values("Settled At", ascending=False), use_container_width=True, hide_index=True)

# Bankroll
with tabs[11]:
    st.markdown('<div class="section-title">Bankroll</div>', unsafe_allow_html=True)
    pending_bank = bet_log[bet_log["Bet Status"] == "Pending"].copy()
    settled_bank = bet_log[bet_log["Bet Status"] == "Settled"].copy()
    open_risk_logged = float(pending_bank["Stake"].sum()) if not pending_bank.empty else 0.0
    realized_bank_pnl = float(settled_bank["PNL"].sum()) if not settled_bank.empty else 0.0
    live_suggested = float(live_bets["Stake To Bet"].sum()) if not live_bets.empty else 0.0
    bankroll_now = bankroll + realized_bank_pnl

    b1, b2, b3, b4 = st.columns(4)
    with b1:
        kpi_card("Starting Bankroll", f"${bankroll:,.2f}", "Manual setting")
    with b2:
        kpi_card("Current Bankroll", f"${bankroll_now:,.2f}", "Start + realized P/L")
    with b3:
        kpi_card("Logged Open Risk", f"${open_risk_logged:,.2f}", "From pending tracked bets")
    with b4:
        kpi_card("Live Suggested Risk", f"${live_suggested:,.2f}", f"Live cap ${max_total_exposure:,.0f}")

    exposure_by_sport = live_bets.groupby("Sport")["Stake To Bet"].sum().reset_index().sort_values("Stake To Bet", ascending=False) if not live_bets.empty else pd.DataFrame(columns=["Sport", "Stake To Bet"])
    exposure_by_event = live_bets.groupby("Event")["Stake To Bet"].sum().reset_index().sort_values("Stake To Bet", ascending=False) if not live_bets.empty else pd.DataFrame(columns=["Event", "Stake To Bet"])

    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="panel"><b>Exposure by Sport</b></div>', unsafe_allow_html=True)
        st.dataframe(exposure_by_sport, use_container_width=True, hide_index=True)
    with c2:
        st.markdown('<div class="panel"><b>Exposure by Event</b></div>', unsafe_allow_html=True)
        st.dataframe(exposure_by_event, use_container_width=True, hide_index=True)

    st.markdown(
        f"""
        <div class="panel">
        <b>Current bankroll rules</b><br>
        • Individual stake sizes stay between ${min_bet:.0f} and ${max_bet:.0f}<br>
        • Total live suggested exposure is capped at ${max_total_exposure:,.0f}<br>
        • Per-event exposure is capped at ${max_event_exposure:,.0f}<br>
        • Per-sportsbook exposure is capped at ${max_book_exposure:,.0f}<br>
        • Prop exposure is capped at ${max_prop_exposure:,.0f}
        </div>
        """,
        unsafe_allow_html=True,
    )
