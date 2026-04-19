import os
import uuid
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="Crimson Sports Dashboard",
    page_icon="🐘",
    layout="wide",
    initial_sidebar_state="expanded",
)

TARGET_BOOKS = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "bet365": "Bet365",
    "prizepicks": "PrizePicks",
}

DEFAULT_LEAGUES = ["NBA", "NFL", "MLB", "NHL"]
BET_LOG_FILE = "bet_log.csv"

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
# FILE HELPERS
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
    try:
        odds = int(str(odds_value).strip().replace("−", "-"))
    except Exception:
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
# ODDS / MODEL HELPERS
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


def safe_team_name(team_dict, fallback):
    if not isinstance(team_dict, dict):
        return fallback
    names = team_dict.get("names", {})
    return (
        names.get("medium")
        or names.get("long")
        or names.get("short")
        or fallback
    )


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
    if "total" in text or "over " in text or "under " in text:
        return "Total"
    if "player" in text or "points" in text or "rebounds" in text or "assists" in text:
        return "Player Prop"
    if "team total" in text:
        return "Team Total"
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
# LIVE FETCH
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


# -----------------------------
# SCORING ENGINE
# -----------------------------
def confidence_from_score(score):
    if score >= 7.0:
        return "Elite"
    if score >= 5.0:
        return "High"
    if score >= 3.0:
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
    if book_name == "PrizePicks":
        return -0.6
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


def apply_smart_scoring(df, min_bet, max_bet):
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
        lambda row: bet_size_from_score(
            edge=row["Edge %"],
            score=row["Bet Score"],
            min_bet=min_bet,
            max_bet=max_bet,
        ),
        axis=1,
    )
    scored["Status"] = scored["Recommended Bet"].apply(lambda x: "Bet" if x > 0 else "No Bet")
    scored["Reason"] = scored.apply(build_reason, axis=1)
    return scored


def apply_exposure_cap(df, max_total_exposure, min_bet):
    df = df.copy()
    df["Stake To Bet"] = 0
    df["Exposure Status"] = "No Bet"
    df["Final Status"] = "No Bet"

    if df.empty:
        return df

    df.loc[df["Status"] == "No Bet", "Exposure Status"] = "No Bet"
    df.loc[df["Status"] == "No Bet", "Final Status"] = "No Bet"

    remaining = float(max_total_exposure)

    candidate_idx = df[df["Status"] == "Bet"].sort_values(
        ["Bet Score", "Edge %", "Books Quoting"],
        ascending=[False, False, False],
    ).index

    for idx in candidate_idx:
        if remaining < float(min_bet):
            df.at[idx, "Stake To Bet"] = 0
            df.at[idx, "Exposure Status"] = "Exposure Cap Reached"
            df.at[idx, "Final Status"] = "Pass"
            continue

        suggested = float(df.at[idx, "Recommended Bet"])
        allocation = int(min(suggested, remaining))

        if allocation < float(min_bet):
            df.at[idx, "Stake To Bet"] = 0
            df.at[idx, "Exposure Status"] = "Exposure Cap Reached"
            df.at[idx, "Final Status"] = "Pass"
            continue

        df.at[idx, "Stake To Bet"] = allocation
        df.at[idx, "Final Status"] = "Bet"

        if allocation < suggested:
            df.at[idx, "Exposure Status"] = "Trimmed To Fit Cap"
        else:
            df.at[idx, "Exposure Status"] = "Within Cap"

        remaining -= allocation

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
        "Event ID",
        "Odd ID",
        "Sportsbook",
        "Odds",
        "Edge %",
        "Bet Score",
        "Confidence",
        "Stake To Bet",
        "Final Status",
        "Exposure Status",
        "Reason",
        "Link",
    ]].copy()

    best_rows = best_rows.rename(columns={
        "Sportsbook": "Best Sportsbook",
        "Odds": "Best Odds",
        "Edge %": "Best Edge %",
        "Bet Score": "Best Bet Score",
        "Confidence": "Best Confidence",
        "Stake To Bet": "Stake To Bet",
        "Final Status": "Final Status",
        "Exposure Status": "Exposure Status",
        "Reason": "Best Reason",
        "Link": "Best Link",
    })

    pivot = df.pivot_table(
        index=group_cols,
        columns="Sportsbook",
        values="Odds",
        aggfunc="first",
    ).reset_index()

    compare = pivot.merge(price_stats, on=group_cols, how="left")
    compare = compare.merge(best_rows, on=["Event ID", "Odd ID"], how="left")

    for col in ["DraftKings", "FanDuel", "Bet365", "PrizePicks"]:
        if col not in compare.columns:
            compare[col] = ""

    def shop_alert(row):
        gap = row["Line Gap %"]
        books = row["Books_Quoting"]
        if books >= 3 and gap >= 4:
            return "Strong Shop"
        if books >= 2 and gap >= 2:
            return "Good Shop"
        if gap > 0:
            return "Small Edge"
        return "Flat"

    compare["Shop Alert"] = compare.apply(shop_alert, axis=1)
    compare["Status Rank"] = compare["Final Status"].map({"Bet": 2, "Pass": 1, "No Bet": 0}).fillna(0)

    compare = compare.sort_values(
        ["Status Rank", "Best Bet Score", "Line Gap %"],
        ascending=[False, False, False],
    ).reset_index(drop=True)

    return compare


def get_live_board(
    leagues,
    sportsbooks,
    market_buckets,
    confidence_levels,
    min_bet,
    max_bet,
    max_total_exposure,
    only_bets=False,
):
    events, error_message = fetch_events(leagues)
    if error_message:
        return pd.DataFrame(), pd.DataFrame(), error_message

    raw_df = flatten_events_to_rows(events)
    if raw_df.empty:
        return pd.DataFrame(), pd.DataFrame(), "No live odds came back for the leagues selected."

    scored_df = apply_smart_scoring(raw_df, min_bet=min_bet, max_bet=max_bet)

    filtered_df = scored_df[
        scored_df["Sportsbook"].isin(sportsbooks)
        & scored_df["Market Bucket"].isin(market_buckets)
        & scored_df["Confidence"].isin(confidence_levels)
    ].copy()

    filtered_df = apply_exposure_cap(
        filtered_df,
        max_total_exposure=max_total_exposure,
        min_bet=min_bet,
    )

    filtered_df["Status Rank"] = filtered_df["Final Status"].map({"Bet": 2, "Pass": 1, "No Bet": 0}).fillna(0)

    if only_bets:
        filtered_df = filtered_df[filtered_df["Final Status"] == "Bet"].copy()

    filtered_df = filtered_df.sort_values(
        ["Status Rank", "Bet Score", "Edge %", "Books Quoting"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)

    compare_df = build_compare_table(filtered_df)
    return filtered_df, compare_df, ""


# -----------------------------
# STYLING - CRIMSON FOOTBALL THEME
# -----------------------------
st.markdown(
    """
    <style>
    .stApp {
        background:
            radial-gradient(circle at top left, rgba(158,27,50,0.35), transparent 28%),
            radial-gradient(circle at top right, rgba(255,255,255,0.10), transparent 18%),
            linear-gradient(180deg, #19070B 0%, #3A0E18 35%, #5C1021 100%);
        color: #F8F8F8;
    }

    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #2B0B13 0%, #4F0F1D 100%);
        border-right: 1px solid rgba(255,255,255,0.08);
    }

    .main-title {
        font-size: 2.9rem;
        font-weight: 900;
        color: #FFFFFF;
        margin-bottom: 0.15rem;
        letter-spacing: 0.5px;
    }

    .sub-title {
        font-size: 1rem;
        color: #F0EAEA;
        margin-bottom: 1.0rem;
    }

    .theme-banner {
        background: repeating-linear-gradient(
            90deg,
            rgba(255,255,255,0.06) 0px,
            rgba(255,255,255,0.06) 18px,
            rgba(255,255,255,0.00) 18px,
            rgba(255,255,255,0.00) 36px
        );
        border: 1px solid rgba(255,255,255,0.10);
        border-radius: 16px;
        padding: 10px 16px;
        margin-bottom: 18px;
    }

    .hero-box {
        background: linear-gradient(135deg, rgba(91,16,33,0.96) 0%, rgba(158,27,50,0.96) 100%);
        border: 1px solid rgba(255,255,255,0.16);
        border-radius: 20px;
        padding: 20px 24px;
        margin-bottom: 18px;
        box-shadow: 0 10px 28px rgba(0, 0, 0, 0.28);
    }

    .card {
        background: rgba(255, 255, 255, 0.07);
        border: 1px solid rgba(255, 255, 255, 0.10);
        border-radius: 18px;
        padding: 18px;
        box-shadow: 0 8px 20px rgba(0,0,0,0.20);
        margin-bottom: 16px;
    }

    .best-bet {
        background: linear-gradient(135deg, rgba(125,18,40,0.95) 0%, rgba(186,40,68,0.95) 100%);
        border: 1px solid rgba(255,255,255,0.20);
        border-radius: 18px;
        padding: 18px;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.24);
        margin-bottom: 16px;
    }

    .section-title {
        font-size: 1.28rem;
        font-weight: 800;
        color: #FFFFFF;
        margin-top: 8px;
        margin-bottom: 10px;
    }

    .small-label {
        color: #F2DDE2;
        font-size: 0.90rem;
    }

    .big-value {
        color: #FFFFFF;
        font-size: 1.55rem;
        font-weight: 900;
    }

    .note-box {
        background: rgba(255,255,255,0.07);
        border-left: 5px solid #FFFFFF;
        border-radius: 12px;
        padding: 12px 14px;
        margin: 14px 0;
    }

    .stMetric {
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 16px;
        padding: 8px 10px;
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

    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }

    .stTabs [data-baseweb="tab"] {
        background: rgba(255,255,255,0.08);
        border-radius: 12px;
        color: #FFFFFF;
        padding: 10px 14px;
    }

    .stTabs [aria-selected="true"] {
        background: rgba(255,255,255,0.20) !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# -----------------------------
# SIDEBAR
# -----------------------------
st.sidebar.title("🐘 Crimson Controls")

bankroll = st.sidebar.number_input("Starting Bankroll", min_value=1.0, value=500.0, step=25.0)
min_bet = st.sidebar.number_input("Minimum Bet", min_value=1.0, value=1.0, step=1.0)
max_bet = st.sidebar.number_input("Maximum Bet", min_value=1.0, value=10.0, step=1.0)
max_total_exposure = st.sidebar.number_input("Max Total Exposure", min_value=1.0, value=40.0, step=5.0)

league_filter = st.sidebar.multiselect(
    "Leagues",
    options=DEFAULT_LEAGUES,
    default=DEFAULT_LEAGUES,
)

book_filter = st.sidebar.multiselect(
    "Sportsbooks",
    options=["DraftKings", "FanDuel", "Bet365", "PrizePicks"],
    default=["DraftKings", "FanDuel", "Bet365", "PrizePicks"],
)

market_bucket_options = ["Moneyline", "Spread", "Total", "Team Total", "Player Prop", "DFS Prop", "Other"]
market_bucket_filter = st.sidebar.multiselect(
    "Market Types",
    options=market_bucket_options,
    default=market_bucket_options,
)

confidence_options = ["Elite", "High", "Medium", "Low"]
confidence_filter = st.sidebar.multiselect(
    "Confidence Levels",
    options=confidence_options,
    default=confidence_options,
)

only_bets = st.sidebar.toggle("Show final bets only", value=False)

if st.sidebar.button("Refresh now"):
    st.cache_data.clear()
    st.rerun()

st.markdown('<div class="main-title">🐘 Crimson Sports Betting Dashboard</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">Best-book comparison, stake sizing, and tracked performance with a Saturday-in-Tuscaloosa feel.</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="theme-banner"><b>New in this version:</b> compare lines across books, best-book detection, and total exposure caps.</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="note-box"><b>Tracker note:</b> this version still saves bet history to a local CSV. That is fine for now, but it can be wiped if the app restarts on Streamlit Cloud.</div>',
    unsafe_allow_html=True,
)


# -----------------------------
# LIVE HERO SECTION (AUTO REFRESH)
# -----------------------------
@st.fragment(run_every="15m")
def render_live_snapshot():
    live_df, compare_df, error_message = get_live_board(
        leagues=league_filter,
        sportsbooks=book_filter,
        market_buckets=market_bucket_filter,
        confidence_levels=confidence_filter,
        min_bet=min_bet,
        max_bet=max_bet,
        max_total_exposure=max_total_exposure,
        only_bets=only_bets,
    )

    if error_message:
        st.warning(error_message)
        return

    live_bets = live_df[live_df["Final Status"] == "Bet"].copy()
    best_row = live_bets.iloc[0] if not live_bets.empty else None
    best_edge = float(live_bets["Edge %"].max()) if not live_bets.empty else 0.0
    avg_edge = float(live_bets["Edge %"].mean()) if not live_bets.empty else 0.0
    avg_score = float(live_bets["Bet Score"].mean()) if not live_bets.empty else 0.0
    open_risk = float(live_bets["Stake To Bet"].sum()) if not live_bets.empty else 0.0
    active_bets = int(len(live_bets))
    strong_shop_count = int((compare_df["Shop Alert"] == "Strong Shop").sum()) if not compare_df.empty else 0
    refresh_time = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")

    st.markdown('<div class="hero-box">', unsafe_allow_html=True)
    hero_left, hero_right = st.columns([2, 1])

    with hero_left:
        st.markdown("### Top Live Bet")
        if best_row is not None:
            st.markdown(
                f"""
                **{best_row['Pick']}**  
                {best_row['Event']} · {best_row['Market']}  
                Book: **{best_row['Sportsbook']}** · Odds: **{best_row['Odds']}**  
                Edge: **{best_row['Edge %']:.2f}%** · Score: **{best_row['Bet Score']:.2f}** · Confidence: **{best_row['Confidence']}**  
                Stake To Bet: **${int(best_row['Stake To Bet'])}**  
                Reason: *{best_row['Reason']}*
                """
            )
            if best_row["Link"]:
                st.markdown(f"[Open bet page]({best_row['Link']})")
        else:
            st.info("No bets qualify right now under the current rules.")

    with hero_right:
        st.markdown('<div class="small-label">Starting Bankroll</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="big-value">${bankroll:,.2f}</div>', unsafe_allow_html=True)
        st.markdown('<div class="small-label">Bet Range</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="big-value">${min_bet:.0f} - ${max_bet:.0f}</div>', unsafe_allow_html=True)
        st.markdown('<div class="small-label">Exposure Cap</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="big-value">${max_total_exposure:,.0f}</div>', unsafe_allow_html=True)
        st.markdown('<div class="small-label">Last Refresh</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="big-value" style="font-size:1.0rem;">{refresh_time}</div>', unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    with k1:
        st.metric("Final Bets", active_bets)
    with k2:
        st.metric("Best Edge", f"{best_edge:.2f}%")
    with k3:
        st.metric("Average Edge", f"{avg_edge:.2f}%")
    with k4:
        st.metric("Average Score", f"{avg_score:.2f}")
    with k5:
        st.metric("Open Suggested Risk", f"${open_risk:,.0f}")
    with k6:
        st.metric("Strong Shop Alerts", strong_shop_count)


render_live_snapshot()

current_df, compare_df, live_error = get_live_board(
    leagues=league_filter,
    sportsbooks=book_filter,
    market_buckets=market_bucket_filter,
    confidence_levels=confidence_filter,
    min_bet=min_bet,
    max_bet=max_bet,
    max_total_exposure=max_total_exposure,
    only_bets=only_bets,
)

if live_error:
    st.warning(live_error)
    st.info("Add SPORTS_GAME_ODDS_API_KEY in Streamlit Secrets, then click Refresh now.")
    st.stop()

bet_log = load_bet_log()
pending_df = bet_log[bet_log["Bet Status"] == "Pending"].copy()
settled_df = bet_log[bet_log["Bet Status"] == "Settled"].copy()

tabs = st.tabs(
    [
        "Home",
        "Best Bets",
        "Compare Lines",
        "DraftKings",
        "FanDuel",
        "Bet365",
        "PrizePicks",
        "Tracker",
        "Results",
        "Bankroll",
    ]
)

# -----------------------------
# HOME
# -----------------------------
with tabs[0]:
    left, right = st.columns([1.35, 1])

    live_bets = current_df[current_df["Final Status"] == "Bet"].copy().head(5)

    with left:
        st.markdown('<div class="section-title">Top Final Bets</div>', unsafe_allow_html=True)
        if live_bets.empty:
            st.warning("No final bets available right now.")
        else:
            for _, row in live_bets.iterrows():
                link_html = f'<br><a href="{row["Link"]}" target="_blank">Open bet page</a>' if row["Link"] else ""
                st.markdown(
                    f"""
                    <div class="best-bet">
                        <b>{row['Pick']}</b><br>
                        {row['Event']} · {row['Market']}<br>
                        Book: <b>{row['Sportsbook']}</b> · Odds: <b>{row['Odds']}</b><br>
                        Edge: <b>{row['Edge %']:.2f}%</b> · Score: <b>{row['Bet Score']:.2f}</b> · Confidence: <b>{row['Confidence']}</b><br>
                        Stake To Bet: <b>${int(row['Stake To Bet'])}</b> · Exposure: <b>{row['Exposure Status']}</b><br>
                        Reason: <i>{row['Reason']}</i>
                        {link_html}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    with right:
        st.markdown('<div class="section-title">Shopping Snapshot</div>', unsafe_allow_html=True)
        strong_shop = int((compare_df["Shop Alert"] == "Strong Shop").sum()) if not compare_df.empty else 0
        good_shop = int((compare_df["Shop Alert"] == "Good Shop").sum()) if not compare_df.empty else 0
        open_risk = pending_df["Stake"].sum() if not pending_df.empty else 0.0
        settled_profit = settled_df["PNL"].sum() if not settled_df.empty else 0.0
        current_bankroll = bankroll + settled_profit

        st.markdown(
            f"""
            <div class="card">
            Strong Shop Alerts: <b>{strong_shop}</b><br>
            Good Shop Alerts: <b>{good_shop}</b><br>
            Pending Bets: <b>{len(pending_df)}</b><br>
            Open Logged Risk: <b>${open_risk:,.2f}</b><br>
            Realized P/L: <b>${settled_profit:,.2f}</b><br>
            Current Bankroll: <b>${current_bankroll:,.2f}</b>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            """
            <div class="card">
            <b>What changed in this version:</b><br>
            • Compare the same outcome across books<br>
            • See the best current book for that bet<br>
            • Limit total suggested risk with an exposure cap<br>
            • Keep full bet tracking and results tabs
            </div>
            """,
            unsafe_allow_html=True,
        )

# -----------------------------
# BEST BETS
# -----------------------------
with tabs[1]:
    st.markdown('<div class="section-title">Best Bets Board</div>', unsafe_allow_html=True)

    display_df = current_df.copy()
    display_df = display_df[
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
            "Best Line Gap %",
            "Books Quoting",
            "Bet Score",
            "Confidence",
            "Recommended Bet",
            "Stake To Bet",
            "Exposure Status",
            "Final Status",
            "Reason",
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
            "Edge %": st.column_config.NumberColumn(format="%.2f%%"),
            "Best Line Gap %": st.column_config.NumberColumn(format="%.2f%%"),
            "Bet Score": st.column_config.NumberColumn(format="%.2f"),
            "Recommended Bet": st.column_config.NumberColumn(format="$%d"),
            "Stake To Bet": st.column_config.NumberColumn(format="$%d"),
            "Link": st.column_config.LinkColumn("Open"),
        },
    )

# -----------------------------
# COMPARE LINES
# -----------------------------
with tabs[2]:
    st.markdown('<div class="section-title">Compare Lines / Best Book</div>', unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        strong_shop = int((compare_df["Shop Alert"] == "Strong Shop").sum()) if not compare_df.empty else 0
        st.metric("Strong Shop Alerts", strong_shop)
    with c2:
        good_shop = int((compare_df["Shop Alert"] == "Good Shop").sum()) if not compare_df.empty else 0
        st.metric("Good Shop Alerts", good_shop)
    with c3:
        final_compare_bets = int((compare_df["Final Status"] == "Bet").sum()) if not compare_df.empty else 0
        st.metric("Best-Book Final Bets", final_compare_bets)

    st.markdown(
        """
        <div class="card">
        This screen groups the same exact outcome across books so you can see where the best number sits.
        Lower implied probability means a better price for you.
        </div>
        """,
        unsafe_allow_html=True,
    )

    if compare_df.empty:
        st.info("No comparison rows available for the current filters.")
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
                    "Best Sportsbook",
                    "Best Odds",
                    "Books_Quoting",
                    "Line Gap %",
                    "Shop Alert",
                    "Best Bet Score",
                    "Best Confidence",
                    "Stake To Bet",
                    "Exposure Status",
                    "Final Status",
                    "Best Reason",
                    "Best Link",
                ]
            ],
            use_container_width=True,
            hide_index=True,
            column_config={
                "Line Gap %": st.column_config.NumberColumn(format="%.2f%%"),
                "Best Bet Score": st.column_config.NumberColumn(format="%.2f"),
                "Stake To Bet": st.column_config.NumberColumn(format="$%d"),
                "Best Link": st.column_config.LinkColumn("Open"),
            },
        )

# -----------------------------
# SPORTSBOOK TABS
# -----------------------------
def sportsbook_tab(book_name):
    book_df = current_df[current_df["Sportsbook"] == book_name].copy()
    bet_df = book_df[book_df["Final Status"] == "Bet"].copy()
    avg_edge_book = float(bet_df["Edge %"].mean()) if not bet_df.empty else 0.0
    avg_score_book = float(bet_df["Bet Score"].mean()) if not bet_df.empty else 0.0
    max_stake_book = int(bet_df["Stake To Bet"].max()) if not bet_df.empty else 0

    st.markdown(f'<div class="section-title">{book_name} Opportunities</div>', unsafe_allow_html=True)

    a1, a2 = st.columns([1.2, 1])

    with a1:
        st.markdown(
            f"""
            <div class="card">
            <b>{book_name}</b><br>
            This tab shows only the rows from {book_name}, after applying the same scoring and exposure-cap rules.
            </div>
            """,
            unsafe_allow_html=True,
        )

    with a2:
        st.markdown(
            f"""
            <div class="card">
            Final Bets: <b>{len(bet_df)}</b><br>
            Avg Edge: <b>{avg_edge_book:.2f}%</b><br>
            Avg Score: <b>{avg_score_book:.2f}</b><br>
            Max Stake To Bet: <b>${max_stake_book}</b>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if book_df.empty:
        st.warning(f"No rows currently available for {book_name}.")
        return

    book_df = book_df[
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
            "Recommended Bet",
            "Stake To Bet",
            "Exposure Status",
            "Final Status",
            "Reason",
            "Link",
        ]
    ]

    st.dataframe(
        book_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Edge %": st.column_config.NumberColumn(format="%.2f%%"),
            "Bet Score": st.column_config.NumberColumn(format="%.2f"),
            "Recommended Bet": st.column_config.NumberColumn(format="$%d"),
            "Stake To Bet": st.column_config.NumberColumn(format="$%d"),
            "Link": st.column_config.LinkColumn("Open"),
        },
    )


with tabs[3]:
    sportsbook_tab("DraftKings")

with tabs[4]:
    sportsbook_tab("FanDuel")

with tabs[5]:
    sportsbook_tab("Bet365")

with tabs[6]:
    sportsbook_tab("PrizePicks")

# -----------------------------
# TRACKER
# -----------------------------
with tabs[7]:
    st.markdown('<div class="section-title">Bet Tracker</div>', unsafe_allow_html=True)

    col_log, col_settle = st.columns(2)

    with col_log:
        st.markdown(
            """
            <div class="card">
            <b>Log Final Bet</b><br>
            Pick one of the current final bets and save it to your tracked history.
            </div>
            """,
            unsafe_allow_html=True,
        )

        log_candidates = current_df[current_df["Final Status"] == "Bet"].copy()

        if log_candidates.empty:
            st.warning("No final bets available to log.")
        else:
            log_candidates["Log Label"] = log_candidates.apply(
                lambda row: f"{row['Event']} | {row['Pick']} | {row['Sportsbook']} {row['Odds']} | Score {row['Bet Score']:.2f} | Stake ${int(row['Stake To Bet'])}",
                axis=1,
            )

            with st.form("log_bet_form"):
                selected_log_label = st.selectbox(
                    "Choose a final bet",
                    options=log_candidates["Log Label"].tolist(),
                )
                submitted_log = st.form_submit_button("Log Selected Bet")

                if submitted_log:
                    selected_row = log_candidates.loc[
                        log_candidates["Log Label"] == selected_log_label
                    ].iloc[0]
                    ok, msg = log_bet_from_row(selected_row)
                    if ok:
                        st.success(msg)
                    else:
                        st.warning(msg)

    with col_settle:
        st.markdown(
            """
            <div class="card">
            <b>Settle Pending Bet</b><br>
            Mark a logged bet as Win, Loss, or Push to update results and bankroll.
            </div>
            """,
            unsafe_allow_html=True,
        )

        pending_df_live = load_bet_log()
        pending_df_live = pending_df_live[pending_df_live["Bet Status"] == "Pending"].copy()

        if pending_df_live.empty:
            st.info("No pending bets to settle.")
        else:
            pending_df_live["Settle Label"] = pending_df_live.apply(
                lambda row: f"{row['Bet ID']} | {row['Event']} | {row['Pick']} | {row['Sportsbook']} {row['Odds']} | Stake ${row['Stake']:,.2f}",
                axis=1,
            )

            with st.form("settle_bet_form"):
                selected_settle_label = st.selectbox(
                    "Choose a pending bet",
                    options=pending_df_live["Settle Label"].tolist(),
                )
                settle_result = st.radio("Result", ["Win", "Loss", "Push"], horizontal=True)
                submitted_settle = st.form_submit_button("Settle Bet")

                if submitted_settle:
                    selected_bet_id = selected_settle_label.split(" | ")[0]
                    ok, msg = settle_bet(selected_bet_id, settle_result)
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
            column_config={
                "Stake": st.column_config.NumberColumn(format="$%.2f"),
                "Bet Score": st.column_config.NumberColumn(format="%.2f"),
            },
        )

# -----------------------------
# RESULTS
# -----------------------------
with tabs[8]:
    st.markdown('<div class="section-title">Performance Results</div>', unsafe_allow_html=True)

    results_df = load_bet_log()
    settled_results = results_df[results_df["Bet Status"] == "Settled"].copy()

    if settled_results.empty:
        st.info("No settled bets yet. Log and settle a few bets to build the results dashboard.")
    else:
        graded = settled_results[settled_results["Result"].isin(["Win", "Loss"])].copy()

        total_settled = len(settled_results)
        wins = int((settled_results["Result"] == "Win").sum())
        losses = int((settled_results["Result"] == "Loss").sum())
        pushes = int((settled_results["Result"] == "Push").sum())
        total_profit = float(settled_results["PNL"].sum())
        total_staked = float(settled_results["Stake"].sum())
        roi = (total_profit / total_staked * 100) if total_staked > 0 else 0.0
        win_rate = ((wins / len(graded)) * 100) if len(graded) > 0 else 0.0

        r1, r2, r3, r4, r5 = st.columns(5)
        with r1:
            st.metric("Settled Bets", total_settled)
        with r2:
            st.metric("Win Rate", f"{win_rate:.1f}%")
        with r3:
            st.metric("Profit / Loss", f"${total_profit:,.2f}")
        with r4:
            st.metric("ROI", f"{roi:.1f}%")
        with r5:
            st.metric("W-L-P", f"{wins}-{losses}-{pushes}")

        chart_col1, chart_col2 = st.columns(2)

        with chart_col1:
            st.markdown("#### Profit by Sportsbook")
            profit_by_book = settled_results.groupby("Sportsbook")["PNL"].sum().sort_values(ascending=False)
            st.bar_chart(profit_by_book)

            st.markdown("#### Profit by Market Type")
            profit_by_market = settled_results.groupby("Market Bucket")["PNL"].sum().sort_values(ascending=False)
            st.bar_chart(profit_by_market)

        with chart_col2:
            st.markdown("#### Running Bankroll")
            running = settled_results.copy()
            running["Sort Time"] = pd.to_datetime(running["Settled At"], errors="coerce")
            running = running.sort_values("Sort Time")
            running["Running Bankroll"] = bankroll + running["PNL"].cumsum()
            if not running.empty:
                line_df = running[["Sort Time", "Running Bankroll"]].dropna()
                if not line_df.empty:
                    st.line_chart(line_df.set_index("Sort Time"))

            st.markdown("#### Hit Rate by Confidence")
            if len(graded) > 0:
                hit_rate_conf = (
                    graded.assign(WinFlag=graded["Result"].eq("Win").astype(int))
                    .groupby("Confidence")["WinFlag"]
                    .mean()
                    .mul(100)
                    .sort_values(ascending=False)
                )
                st.bar_chart(hit_rate_conf)

        st.markdown("#### Settled Bet History")
        st.dataframe(
            settled_results[
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
            column_config={
                "Stake": st.column_config.NumberColumn(format="$%.2f"),
                "PNL": st.column_config.NumberColumn(format="$%.2f"),
                "Bet Score": st.column_config.NumberColumn(format="%.2f"),
            },
        )

# -----------------------------
# BANKROLL
# -----------------------------
with tabs[9]:
    st.markdown('<div class="section-title">Bankroll Management</div>', unsafe_allow_html=True)

    bank_df = load_bet_log()
    pending_bank = bank_df[bank_df["Bet Status"] == "Pending"].copy()
    settled_bank = bank_df[bank_df["Bet Status"] == "Settled"].copy()
    live_final_bets = current_df[current_df["Final Status"] == "Bet"].copy()

    open_risk_logged = float(pending_bank["Stake"].sum()) if not pending_bank.empty else 0.0
    open_risk_live = float(live_final_bets["Stake To Bet"].sum()) if not live_final_bets.empty else 0.0
    realized_pnl = float(settled_bank["PNL"].sum()) if not settled_bank.empty else 0.0
    current_bankroll = bankroll + realized_pnl

    b1, b2, b3, b4 = st.columns(4)
    with b1:
        st.markdown(
            f"""
            <div class="card">
            <div class="small-label">Starting Bankroll</div>
            <div class="big-value">${bankroll:,.2f}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with b2:
        st.markdown(
            f"""
            <div class="card">
            <div class="small-label">Current Bankroll</div>
            <div class="big-value">${current_bankroll:,.2f}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with b3:
        st.markdown(
            f"""
            <div class="card">
            <div class="small-label">Logged Open Risk</div>
            <div class="big-value">${open_risk_logged:,.2f}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with b4:
        st.markdown(
            f"""
            <div class="card">
            <div class="small-label">Live Suggested Risk</div>
            <div class="big-value">${open_risk_live:,.2f}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        f"""
        <div class="card">
        <b>Current bankroll rules:</b><br>
        • Individual suggested stakes still stay between ${min_bet:.0f} and ${max_bet:.0f}<br>
        • Total live suggested exposure is capped at ${max_total_exposure:,.0f}<br>
        • Lower-ranked plays can be trimmed or passed once the cap is reached<br>
        • Logged and settled bets continue to drive realized P/L and bankroll history
        </div>
        """,
        unsafe_allow_html=True,
    )
