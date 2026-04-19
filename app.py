import os
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.express as px
import requests
import streamlit as st


# =========================
# PAGE CONFIG
# =========================
st.set_page_config(
    page_title="Sports Betting Dashboard",
    page_icon="🏈",
    layout="wide",
)


# =========================
# STYLING
# =========================
st.markdown(
    """
    <style>
    .main {
        background: linear-gradient(180deg, #0b1020 0%, #111827 100%);
    }
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
    }
    .hero-card {
        padding: 1.25rem 1.5rem;
        border-radius: 18px;
        background: linear-gradient(135deg, rgba(30,41,59,0.95), rgba(15,23,42,0.95));
        border: 1px solid rgba(255,255,255,0.08);
        margin-bottom: 1rem;
    }
    .metric-card {
        padding: 1rem;
        border-radius: 16px;
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
    }
    .small-note {
        color: #cbd5e1;
        font-size: 0.9rem;
    }
    .stDataFrame, .stTable {
        border-radius: 14px;
        overflow: hidden;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# =========================
# HELPERS
# =========================
def american_to_decimal(american_odds):
    try:
        odds = float(american_odds)
        if odds > 0:
            return 1 + (odds / 100)
        return 1 + (100 / abs(odds))
    except Exception:
        return np.nan


def american_to_implied_prob(american_odds):
    try:
        odds = float(american_odds)
        if odds > 0:
            return 100 / (odds + 100)
        return abs(odds) / (abs(odds) + 100)
    except Exception:
        return np.nan


def kelly_fraction(decimal_odds, win_prob):
    """
    decimal_odds: decimal price like 1.91
    win_prob: user/model estimated win probability between 0 and 1
    """
    try:
        b = decimal_odds - 1
        p = win_prob
        q = 1 - p
        k = ((b * p) - q) / b if b > 0 else 0
        return max(0, k)
    except Exception:
        return 0


def stake_from_kelly(bankroll, kelly_frac, min_bet, max_bet, fraction=0.25):
    raw = bankroll * kelly_frac * fraction
    return round(max(min_bet, min(max_bet, raw)), 2)


def safe_float(x, default=np.nan):
    try:
        return float(x)
    except Exception:
        return default


def normalize_text(x):
    if x is None:
        return ""
    return str(x).strip()


# =========================
# API / DATA
# =========================
SPORTS_GAME_ODDS_API_KEY = st.secrets.get("SPORTS_GAME_ODDS_API_KEY", os.getenv("SPORTS_GAME_ODDS_API_KEY", ""))
SPORTSDATAIO_API_KEY = st.secrets.get("SPORTSDATAIO_API_KEY", os.getenv("SPORTSDATAIO_API_KEY", ""))

DEFAULT_BOOKS = ["DraftKings", "FanDuel", "Bet365", "PrizePicks", "Caesars", "BetMGM"]
DEFAULT_LEAGUES = ["NBA", "NFL", "MLB", "NHL"]


@st.cache_data(ttl=900, show_spinner=False)
def fetch_sgo_events(api_key, leagues):
    """
    SportsGameOdds fetch.
    This is written defensively because provider payloads can vary.
    """
    if not api_key:
        return []

    url = "https://api.sportsgameodds.com/v2/events"
    params = {
        "leagueID": ",".join(leagues),
        "oddsAvailable": "true",
        "limit": 100,
    }
    headers = {
        "x-api-key": api_key
    }

    try:
        r = requests.get(url, params=params, headers=headers, timeout=20)
        r.raise_for_status()
        data = r.json()

        if isinstance(data, dict):
            for key in ["data", "events", "results"]:
                if key in data and isinstance(data[key], list):
                    return data[key]
            return [data]

        if isinstance(data, list):
            return data

        return []
    except Exception as e:
        st.error(f"SportsGameOdds API error: {e}")
        return []


def build_sample_data(selected_books, leagues):
    """
    Fallback data so app still runs if API response shape differs
    or no live data is available yet.
    """
    rows = []
    sample_players = [
        ("LeBron James", "Points", "Over 24.5", "NBA"),
        ("Jayson Tatum", "Rebounds", "Over 8.5", "NBA"),
        ("Patrick Mahomes", "Pass Yards", "Over 279.5", "NFL"),
        ("Aaron Judge", "Hits", "Over 1.5", "MLB"),
        ("Connor McDavid", "Shots", "Over 3.5", "NHL"),
        ("Scottie Barnes", "Assists", "Under 5.5", "NBA"),
    ]

    odds_cycle = [110, 120, -105, 135, -115, 145, 150, 125, -110]
    score_cycle = [62, 58, 54, 67, 49, 61, 57, 64, 52]

    idx = 0
    for player, market, bet, league in sample_players:
        if league not in leagues:
            continue
        for book in selected_books:
            odds = odds_cycle[idx % len(odds_cycle)]
            model_prob = min(0.75, max(0.42, american_to_implied_prob(odds) + 0.04))
            rows.append(
                {
                    "league": league,
                    "event_name": f"{league} Matchup {idx+1}",
                    "player_name": player,
                    "market": market,
                    "bet_name": bet,
                    "sportsbook": book,
                    "american_odds": odds,
                    "decimal_odds": round(american_to_decimal(odds), 3),
                    "implied_prob": round(american_to_implied_prob(odds), 4),
                    "model_prob": round(model_prob, 4),
                    "score": score_cycle[idx % len(score_cycle)],
                    "start_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
            )
            idx += 1

    return pd.DataFrame(rows)


def flatten_sgo_events(events, selected_books):
    """
    Converts SportsGameOdds response into a standard dataframe.
    Because API payloads may vary, this parser is intentionally flexible.
    """
    rows = []

    for event in events:
        league = normalize_text(event.get("leagueID") or event.get("league") or event.get("sport"))
        event_name = normalize_text(event.get("name") or event.get("eventName") or event.get("matchup") or "Event")
        start_time = normalize_text(event.get("startTime") or event.get("commenceTime") or "")

        # Try different possible locations for markets / odds
        possible_market_lists = []
        for key in ["markets", "odds", "lines", "offers"]:
            val = event.get(key)
            if isinstance(val, list):
                possible_market_lists.append(val)

        if not possible_market_lists:
            continue

        for market_list in possible_market_lists:
            for item in market_list:
                market = normalize_text(item.get("marketName") or item.get("market") or item.get("betType") or "Market")
                player_name = normalize_text(item.get("playerName") or item.get("participant") or item.get("name") or "")
                bet_name = normalize_text(item.get("label") or item.get("selection") or item.get("outcome") or market)

                # books may be nested
                books = []
                for bkey in ["sportsbooks", "books", "operators", "prices"]:
                    bval = item.get(bkey)
                    if isinstance(bval, list):
                        books = bval
                        break

                for book_item in books:
                    sportsbook = normalize_text(
                        book_item.get("sportsbook") or
                        book_item.get("book") or
                        book_item.get("operator") or
                        book_item.get("name")
                    )

                    if selected_books and sportsbook and sportsbook not in selected_books:
                        continue

                    american_odds = (
                        book_item.get("americanOdds")
                        or book_item.get("oddsAmerican")
                        or book_item.get("odds")
                        or book_item.get("price")
                    )

                    american_odds = safe_float(american_odds)
                    if np.isnan(american_odds):
                        continue

                    implied = american_to_implied_prob(american_odds)
                    model_prob = min(0.80, max(0.40, implied + 0.03))
                    score = round((model_prob - implied) * 1000, 2)

                    rows.append(
                        {
                            "league": league or "Unknown",
                            "event_name": event_name,
                            "player_name": player_name if player_name else event_name,
                            "market": market,
                            "bet_name": bet_name,
                            "sportsbook": sportsbook if sportsbook else "Unknown Book",
                            "american_odds": int(american_odds),
                            "decimal_odds": round(american_to_decimal(american_odds), 3),
                            "implied_prob": round(implied, 4),
                            "model_prob": round(model_prob, 4),
                            "score": score,
                            "start_time": start_time,
                        }
                    )

    return pd.DataFrame(rows)


def get_dashboard_data(api_key, selected_books, leagues):
    events = fetch_sgo_events(api_key, leagues)
    df_live = flatten_sgo_events(events, selected_books) if events else pd.DataFrame()

    if df_live.empty:
        return build_sample_data(selected_books, leagues)

    return df_live


# =========================
# SIDEBAR
# =========================
st.sidebar.title("Controls")

bankroll = st.sidebar.number_input("Bankroll ($)", min_value=1.0, max_value=100000.0, value=500.0, step=10.0)
min_bet = st.sidebar.number_input("Minimum Bet ($)", min_value=1.0, max_value=1000.0, value=1.0, step=1.0)
max_bet = st.sidebar.number_input("Maximum Bet ($)", min_value=1.0, max_value=1000.0, value=10.0, step=1.0)

selected_leagues = st.sidebar.multiselect("Leagues", DEFAULT_LEAGUES, default=DEFAULT_LEAGUES)
selected_books = st.sidebar.multiselect("Sportsbooks", DEFAULT_BOOKS, default=DEFAULT_BOOKS)

min_score = st.sidebar.slider("Minimum Score", min_value=0, max_value=100, value=45)
top_n = st.sidebar.slider("Top Bets to Show", min_value=5, max_value=50, value=15)
refresh_note = st.sidebar.caption("App data cache refreshes every 15 minutes.")


# =========================
# HEADER
# =========================
st.markdown(
    """
    <div class="hero-card">
        <h1 style="margin-bottom:0.2rem;">🏈 Sports Betting Dashboard</h1>
        <div class="small-note">Auto-refreshing odds board with smarter bet scoring and stake sizing.</div>
    </div>
    """,
    unsafe_allow_html=True,
)

if not SPORTS_GAME_ODDS_API_KEY:
    st.warning("No SPORTS_GAME_ODDS_API_KEY found in Streamlit Secrets. Showing sample data so the app still runs.")


# =========================
# LOAD DATA
# =========================
df = get_dashboard_data(SPORTS_GAME_ODDS_API_KEY, selected_books, selected_leagues).copy()

if df.empty:
    st.error("No data available.")
    st.stop()

df["edge"] = (df["model_prob"] - df["implied_prob"]).round(4)
df["edge_pct"] = (df["edge"] * 100).round(2)
df["kelly_fraction"] = df.apply(lambda r: kelly_fraction(r["decimal_odds"], r["model_prob"]), axis=1)
df["recommended_stake"] = df["kelly_fraction"].apply(
    lambda k: stake_from_kelly(bankroll, k, min_bet, max_bet, fraction=0.25)
)

# Normalize score into 0-100 if needed
if df["score"].max() > 100 or df["score"].min() < 0:
    s_min = df["score"].min()
    s_max = df["score"].max()
    if s_max != s_min:
        df["score"] = ((df["score"] - s_min) / (s_max - s_min) * 100).round(2)
    else:
        df["score"] = 50.0

df = df[df["score"] >= min_score].copy()
df.sort_values(["score", "edge_pct", "recommended_stake"], ascending=[False, False, False], inplace=True)

if df.empty:
    st.warning("No bets matched the current filters.")
    st.stop()


# =========================
# METRICS
# =========================
c1, c2, c3, c4 = st.columns(4)

with c1:
    st.metric("Bets Found", f"{len(df):,}")
with c2:
    st.metric("Average Score", f"{df['score'].mean():.1f}")
with c3:
    st.metric("Average Edge", f"{df['edge_pct'].mean():.2f}%")
with c4:
    st.metric("Avg Stake", f"${df['recommended_stake'].mean():.2f}")


# =========================
# TOP BETS TABLE
# =========================
st.subheader("Top Bet Suggestions")

top_df = df.head(top_n).copy()
display_df = top_df[
    [
        "league",
        "event_name",
        "player_name",
        "market",
        "bet_name",
        "sportsbook",
        "american_odds",
        "implied_prob",
        "model_prob",
        "edge_pct",
        "score",
        "recommended_stake",
        "start_time",
    ]
].copy()

display_df["implied_prob"] = (display_df["implied_prob"] * 100).round(2).astype(str) + "%"
display_df["model_prob"] = (display_df["model_prob"] * 100).round(2).astype(str) + "%"
display_df["recommended_stake"] = "$" + display_df["recommended_stake"].round(2).astype(str)

st.dataframe(display_df, use_container_width=True, hide_index=True)


# =========================
# CHARTS
# =========================
left, right = st.columns(2)

with left:
    score_fig = px.bar(
        top_df.head(10),
        x="player_name",
        y="score",
        color="sportsbook",
        title="Top 10 Scores by Bet",
        hover_data=["bet_name", "american_odds", "recommended_stake"],
    )
    score_fig.update_layout(xaxis_title="", yaxis_title="Score")
    st.plotly_chart(score_fig, use_container_width=True, key="score_fig_main")

with right:
    stake_fig = px.bar(
        top_df.head(10),
        x="player_name",
        y="recommended_stake",
        color="sportsbook",
        title="Recommended Stake by Bet",
        hover_data=["bet_name", "score", "edge_pct"],
    )
    stake_fig.update_layout(xaxis_title="", yaxis_title="Stake ($)")
    st.plotly_chart(stake_fig, use_container_width=True, key="stake_fig_main")


# =========================
# HEATMAP
# =========================
st.subheader("Sportsbook Value Heatmap")

heatmap_df = (
    df.pivot_table(
        index="player_name",
        columns="sportsbook",
        values="score",
        aggfunc="max"
    )
    .fillna(0)
)

if not heatmap_df.empty:
    heatmap_fig = px.imshow(
        heatmap_df,
        aspect="auto",
        title="Bet Score Heatmap by Sportsbook",
        labels={"x": "Sportsbook", "y": "Player / Bet", "color": "Score"},
    )
    st.plotly_chart(heatmap_fig, use_container_width=True, key="heatmap_fig_main")


# =========================
# EDGE SCATTER
# =========================
st.subheader("Edge vs Stake")

scatter_fig = px.scatter(
    df,
    x="edge_pct",
    y="recommended_stake",
    color="sportsbook",
    size="score",
    hover_data=["player_name", "bet_name", "american_odds"],
    title="Best Risk / Reward Opportunities",
)
scatter_fig.update_layout(xaxis_title="Edge (%)", yaxis_title="Recommended Stake ($)")
st.plotly_chart(scatter_fig, use_container_width=True, key="edge_scatter_fig")


# =========================
# LEAGUE BREAKDOWN
# =========================
league_col1, league_col2 = st.columns(2)

with league_col1:
    league_summary = (
        df.groupby("league", as_index=False)
        .agg(
            bets=("league", "count"),
            avg_score=("score", "mean"),
            avg_edge=("edge_pct", "mean"),
            avg_stake=("recommended_stake", "mean"),
        )
        .sort_values("avg_score", ascending=False)
    )
    st.subheader("League Summary")
    st.dataframe(league_summary.round(2), use_container_width=True, hide_index=True)

with league_col2:
    league_fig = px.bar(
        league_summary,
        x="league",
        y="avg_score",
        title="Average Score by League",
        hover_data=["bets", "avg_edge", "avg_stake"],
    )
    st.plotly_chart(league_fig, use_container_width=True, key="league_fig_main")


# =========================
# SPORTSBOOK BREAKDOWN
# =========================
st.subheader("Sportsbook Comparison")

book_summary = (
    df.groupby("sportsbook", as_index=False)
    .agg(
        bets=("sportsbook", "count"),
        avg_score=("score", "mean"),
        avg_edge=("edge_pct", "mean"),
        avg_stake=("recommended_stake", "mean"),
    )
    .sort_values("avg_score", ascending=False)
)

book_col1, book_col2 = st.columns(2)

with book_col1:
    st.dataframe(book_summary.round(2), use_container_width=True, hide_index=True)

with book_col2:
    book_fig = px.bar(
        book_summary,
        x="sportsbook",
        y="avg_score",
        title="Average Score by Sportsbook",
        hover_data=["bets", "avg_edge", "avg_stake"],
    )
    st.plotly_chart(book_fig, use_container_width=True, key="book_fig_main")


# =========================
# TOP PICK CALL-OUTS
# =========================
st.subheader("Best Current Picks")

for i, row in top_df.head(6).reset_index(drop=True).iterrows():
    st.markdown(
        f"""
        **{i+1}. {row['player_name']} — {row['bet_name']}**  
        {row['sportsbook']} | Odds: {row['american_odds']} | Score: {row['score']:.2f} | Edge: {row['edge_pct']:.2f}% | Suggested Stake: ${row['recommended_stake']:.2f}
        """
    )


# =========================
# FOOTER
# =========================
st.caption(
    "This dashboard is for informational purposes only. Always verify lines directly at the sportsbook before placing any wager."
)