import requests
import pandas as pd
import streamlit as st

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

DEFAULT_LEAGUES = ["NBA", "NFL", "MLB", "NHL"]


def american_to_implied(odds_value):
    """Convert American odds string like +120 / -110 to implied probability %."""
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


def build_pick_label(odd, quote, home_name, away_name, players):
    side_id = str(odd.get("sideID", "") or "")
    stat_entity_id = str(odd.get("statEntityID", "") or "")
    market_name = str(odd.get("marketName", "") or "Market")

    simple_entities = {"all", "home", "away", "draw", "home+draw", "away+draw"}

    # Totals / props with lines
    if quote.get("overUnder") is not None:
        line = quote.get("overUnder")
        if stat_entity_id not in simple_entities:
            player_name = safe_player_name(players, stat_entity_id)
            return f"{player_name} {side_id.title()} {line}"
        return f"{side_id.title()} {line}"

    # Spreads / handicaps
    if quote.get("spread") is not None:
        line = quote.get("spread")
        if stat_entity_id == "home" or side_id == "home":
            target = home_name
        elif stat_entity_id == "away" or side_id == "away":
            target = away_name
        else:
            target = stat_entity_id.replace("_", " ").title()
        return f"{target} {line}"

    # Standard team-side markets
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

    # Player yes/no props
    if stat_entity_id not in simple_entities:
        player_name = safe_player_name(players, stat_entity_id)
        if side_id in {"yes", "no"}:
            return f"{player_name} {side_id.title()}"
        return player_name

    if side_id in {"yes", "no"}:
        return side_id.title()

    return market_name


@st.cache_data(ttl=900, show_spinner="Loading live odds...")
def fetch_events(leagues):
    """Fetch live/upcoming events with odds from SportsGameOdds."""
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

                rows.append(
                    {
                        "Event ID": event_id,
                        "Odd ID": odd_id,
                        "Sport": league_id or sport_id,
                        "Event": event_name,
                        "Start Time": starts_at,
                        "Market": market_name,
                        "Pick": pick_label,
                        "Sportsbook": TARGET_BOOKS[book_id],
                        "Sportsbook ID": book_id,
                        "Odds": str(odds_value),
                        "Implied Prob": implied_prob,
                        "Line": quote.get("spread") or quote.get("overUnder") or "",
                        "Last Update": quote.get("lastUpdatedAt", ""),
                        "Link": deep_link,
                    }
                )

    return pd.DataFrame(rows)


def apply_provisional_scoring(df, min_bet, max_bet):
    """
    Provisional scoring only:
    compares each book's price to the average implied probability for the same odd.
    Lower implied probability = better price for the bettor.
    """
    if df.empty:
        df["Model Prob"] = []
        df["Edge %"] = []
        df["Confidence"] = []
        df["Recommended Bet"] = []
        df["Status"] = []
        return df

    market_consensus = (
        df.groupby(["Event ID", "Odd ID"])["Implied Prob"]
        .agg(["mean", "count"])
        .reset_index()
        .rename(columns={"mean": "Consensus Prob", "count": "Books Quoting"})
    )

    scored = df.merge(market_consensus, on=["Event ID", "Odd ID"], how="left")
    scored["Model Prob"] = scored["Consensus Prob"].round(2)
    scored["Edge %"] = (scored["Consensus Prob"] - scored["Implied Prob"]).round(2)

    def confidence_label(row):
        edge = row["Edge %"]
        books = row["Books Quoting"]
        if books >= 3 and edge >= 3:
            return "High"
        if books >= 2 and edge >= 1.5:
            return "Medium"
        return "Low"

    def bet_size(row):
        edge = row["Edge %"]
        books = row["Books Quoting"]
        if books < 2 or edge < 1.5:
            return 0
        if edge < 3:
            return int(min_bet)
        if edge < 5:
            return int(min(max_bet, min_bet + 1))
        return int(min(max_bet, min_bet + 2))

    scored["Confidence"] = scored.apply(confidence_label, axis=1)
    scored["Recommended Bet"] = scored.apply(bet_size, axis=1)
    scored["Status"] = scored["Recommended Bet"].apply(
        lambda x: "Value Look" if x > 0 else "Watch"
    )

    return scored


def make_link_markdown(url):
    if not url:
        return ""
    return f"[Open]({url})"


# -----------------------------
# SIDEBAR
# -----------------------------
st.sidebar.title("⚙️ Dashboard Controls")

bankroll = st.sidebar.number_input("Bankroll", min_value=1.0, value=500.0, step=25.0)
min_bet = st.sidebar.number_input("Minimum Bet", min_value=1.0, value=1.0, step=1.0)
max_bet = st.sidebar.number_input("Maximum Bet", min_value=1.0, value=10.0, step=1.0)

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

if st.sidebar.button("Refresh now"):
    st.cache_data.clear()
    st.rerun()

# -----------------------------
# STYLING
# -----------------------------
st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(180deg, #08111f 0%, #0d1b2a 100%);
        color: #f5f7fa;
    }

    .main-title {
        font-size: 2.8rem;
        font-weight: 800;
        color: #ffffff;
        margin-bottom: 0.2rem;
    }

    .sub-title {
        font-size: 1rem;
        color: #b8c4d6;
        margin-bottom: 1.5rem;
    }

    .hero-box {
        background: linear-gradient(135deg, #0f172a 0%, #10253e 100%);
        border: 1px solid rgba(0, 255, 170, 0.25);
        border-radius: 18px;
        padding: 20px 24px;
        margin-bottom: 18px;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.28);
    }

    .card {
        background: rgba(255, 255, 255, 0.04);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 18px;
        padding: 18px;
        box-shadow: 0 8px 20px rgba(0,0,0,0.20);
        margin-bottom: 16px;
    }

    .best-bet {
        background: linear-gradient(135deg, #052e2b 0%, #0b3d2e 100%);
        border: 1px solid rgba(0, 255, 170, 0.45);
        border-radius: 18px;
        padding: 18px;
        box-shadow: 0 8px 24px rgba(0, 255, 170, 0.10);
        margin-bottom: 16px;
    }

    .section-title {
        font-size: 1.3rem;
        font-weight: 700;
        color: #ffffff;
        margin-top: 10px;
        margin-bottom: 10px;
    }

    .small-label {
        color: #92a3b8;
        font-size: 0.90rem;
    }

    .big-value {
        color: #00f5b4;
        font-size: 1.6rem;
        font-weight: 800;
    }

    div[data-baseweb="select"] > div {
        color: black !important;
    }

    div[data-baseweb="select"] input {
        color: black !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------
# LOAD DATA
# -----------------------------
events, error_message = fetch_events(league_filter)

st.markdown('<div class="main-title">🏈 Sports Betting Dashboard</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">Live odds board, line shopping, and provisional value looks.</div>',
    unsafe_allow_html=True,
)

if error_message:
    st.warning(error_message)
    st.info("Add your API key in Streamlit app settings → Secrets, then click Refresh now.")
    st.stop()

raw_df = flatten_events_to_rows(events)

if raw_df.empty:
    st.warning("No live odds came back for the leagues selected.")
    st.stop()

scored_df = apply_provisional_scoring(raw_df, min_bet=min_bet, max_bet=max_bet)
filtered_df = scored_df[scored_df["Sportsbook"].isin(book_filter)].copy()

live_value_df = filtered_df[filtered_df["Status"] == "Value Look"].copy()
live_value_df = live_value_df.sort_values(["Edge %", "Books Quoting"], ascending=[False, False])

best_row = live_value_df.iloc[0] if not live_value_df.empty else None
best_edge = float(live_value_df["Edge %"].max()) if not live_value_df.empty else 0.0
avg_edge = float(live_value_df["Edge %"].mean()) if not live_value_df.empty else 0.0
open_risk = int(live_value_df["Recommended Bet"].sum()) if not live_value_df.empty else 0
active_bets = int(len(live_value_df))

# -----------------------------
# HEADER / HERO
# -----------------------------
st.markdown('<div class="hero-box">', unsafe_allow_html=True)
hero_left, hero_right = st.columns([2, 1])

with hero_left:
    st.markdown("### Current Top Value Look")
    if best_row is not None:
        st.markdown(
            f"""
            **{best_row['Pick']}**  
            {best_row['Event']} · {best_row['Market']}  
            Book: **{best_row['Sportsbook']}** · Odds: **{best_row['Odds']}**  
            Price Edge: **{best_row['Edge %']:.2f}%** · Confidence: **{best_row['Confidence']}**  
            Provisional Stake: **${best_row['Recommended Bet']}**
            """
        )
        if best_row["Link"]:
            st.markdown(f"[Open bet page]({best_row['Link']})")
    else:
        st.info("No provisional value looks right now. The board is still live below.")

with hero_right:
    st.markdown('<div class="small-label">Current Bankroll</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="big-value">${bankroll:,.2f}</div>', unsafe_allow_html=True)
    st.markdown('<div class="small-label">Bet Range</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="big-value">${min_bet:.0f} - ${max_bet:.0f}</div>', unsafe_allow_html=True)
    st.markdown('<div class="small-label">Events Loaded</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="big-value">{len(events)}</div>', unsafe_allow_html=True)

st.markdown("</div>", unsafe_allow_html=True)

# -----------------------------
# KPI ROW
# -----------------------------
k1, k2, k3, k4 = st.columns(4)
with k1:
    st.metric("Value Looks", active_bets)
with k2:
    st.metric("Best Edge", f"{best_edge:.2f}%")
with k3:
    st.metric("Average Edge", f"{avg_edge:.2f}%")
with k4:
    st.metric("Open Risk", f"${open_risk}")

st.info(
    "Current recommendations are provisional. This step is line-shopping only: it flags books posting a better price than the average of the selected books for the same exact outcome."
)

# -----------------------------
# TABS
# -----------------------------
tabs = st.tabs(
    [
        "Home",
        "Best Bets",
        "DraftKings",
        "FanDuel",
        "Bet365",
        "PrizePicks",
        "Bankroll",
    ]
)

# -----------------------------
# HOME TAB
# -----------------------------
with tabs[0]:
    left, right = st.columns([1.4, 1])

    with left:
        st.markdown('<div class="section-title">Top Value Looks</div>', unsafe_allow_html=True)
        top_df = live_value_df.head(5)

        if top_df.empty:
            st.warning("No value looks available at this moment.")
        else:
            for _, row in top_df.iterrows():
                link_html = f'<br><a href="{row["Link"]}" target="_blank">Open bet page</a>' if row["Link"] else ""
                st.markdown(
                    f"""
                    <div class="best-bet">
                        <b>{row['Pick']}</b><br>
                        {row['Event']} · {row['Market']}<br>
                        Book: <b>{row['Sportsbook']}</b> · Odds: <b>{row['Odds']}</b><br>
                        Edge: <b>{row['Edge %']:.2f}%</b> · Confidence: <b>{row['Confidence']}</b><br>
                        Suggested Stake: <b>${row['Recommended Bet']}</b>
                        {link_html}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    with right:
        st.markdown('<div class="section-title">What this step does</div>', unsafe_allow_html=True)
        st.markdown(
            """
            <div class="card">
            • Pulls live odds from SportsGameOdds<br>
            • Filters to DraftKings, FanDuel, Bet365, and PrizePicks<br>
            • Compares the same exact market across books<br>
            • Flags books showing the best current price<br>
            • Keeps data fresh with a 15-minute cache
            </div>
            """,
            unsafe_allow_html=True,
        )

# -----------------------------
# BEST BETS TAB
# -----------------------------
with tabs[1]:
    st.markdown('<div class="section-title">Live Best Bets Board</div>', unsafe_allow_html=True)

    display_df = filtered_df.copy()
    display_df["Link"] = display_df["Link"].apply(make_link_markdown)
    display_df = display_df[
        [
            "Sport",
            "Event",
            "Market",
            "Pick",
            "Sportsbook",
            "Odds",
            "Implied Prob",
            "Model Prob",
            "Edge %",
            "Confidence",
            "Recommended Bet",
            "Status",
            "Link",
        ]
    ].sort_values(["Status", "Edge %"], ascending=[False, False])

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Implied Prob": st.column_config.NumberColumn(format="%.2f%%"),
            "Model Prob": st.column_config.NumberColumn(format="%.2f%%"),
            "Edge %": st.column_config.NumberColumn(format="%.2f%%"),
            "Recommended Bet": st.column_config.NumberColumn(format="$%d"),
            "Link": st.column_config.LinkColumn("Open"),
        },
    )

# -----------------------------
# SPORTSBOOK TABS
# -----------------------------
def sportsbook_section(book_name):
    book_df = filtered_df[filtered_df["Sportsbook"] == book_name].copy()
    value_df = book_df[book_df["Status"] == "Value Look"].copy()
    avg_edge_book = float(value_df["Edge %"].mean()) if not value_df.empty else 0.0
    max_stake_book = int(value_df["Recommended Bet"].max()) if not value_df.empty else 0

    st.markdown(f'<div class="section-title">{book_name} Opportunities</div>', unsafe_allow_html=True)

    c1, c2 = st.columns([1.2, 1])

    with c1:
        st.markdown(
            f"""
            <div class="card">
            <b>{book_name}</b><br>
            Live lines from the selected leagues are shown below.<br>
            Right now this page is ranking price discrepancies only.<br>
            The full sports-data betting model comes next.
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c2:
        st.markdown(
            f"""
            <div class="card">
            Value Looks: <b>{len(value_df)}</b><br>
            Avg Edge: <b>{avg_edge_book:.2f}%</b><br>
            Max Stake: <b>${max_stake_book}</b>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if book_df.empty:
        st.warning(f"No rows currently available for {book_name}.")
        return

    book_df["Link"] = book_df["Link"].apply(make_link_markdown)
    book_df = book_df[
        [
            "Sport",
            "Event",
            "Market",
            "Pick",
            "Odds",
            "Implied Prob",
            "Model Prob",
            "Edge %",
            "Confidence",
            "Recommended Bet",
            "Status",
            "Link",
        ]
    ].sort_values(["Status", "Edge %"], ascending=[False, False])

    st.dataframe(
        book_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Implied Prob": st.column_config.NumberColumn(format="%.2f%%"),
            "Model Prob": st.column_config.NumberColumn(format="%.2f%%"),
            "Edge %": st.column_config.NumberColumn(format="%.2f%%"),
            "Recommended Bet": st.column_config.NumberColumn(format="$%d"),
            "Link": st.column_config.LinkColumn("Open"),
        },
    )


with tabs[2]:
    sportsbook_section("DraftKings")

with tabs[3]:
    sportsbook_section("FanDuel")

with tabs[4]:
    sportsbook_section("Bet365")

with tabs[5]:
    sportsbook_section("PrizePicks")

# -----------------------------
# BANKROLL TAB
# -----------------------------
with tabs[6]:
    st.markdown('<div class="section-title">Bankroll Management</div>', unsafe_allow_html=True)

    b1, b2, b3 = st.columns(3)
    with b1:
        st.markdown(
            f"""
            <div class="card">
            <div class="small-label">Current Bankroll</div>
            <div class="big-value">${bankroll:,.2f}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with b2:
        st.markdown(
            f"""
            <div class="card">
            <div class="small-label">Minimum Bet</div>
            <div class="big-value">${min_bet:.0f}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with b3:
        st.markdown(
            f"""
            <div class="card">
            <div class="small-label">Maximum Bet</div>
            <div class="big-value">${max_bet:.0f}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        """
        <div class="card">
        <b>Current logic:</b><br>
        • This step is still price-shopping only<br>
        • No provisional stake unless the line is meaningfully better than the group average<br>
        • Stakes stay small until the full probability model is added<br>
        • Next version will use sports stats/injuries/form, not just price differences
        </div>
        """,
        unsafe_allow_html=True,
    )
