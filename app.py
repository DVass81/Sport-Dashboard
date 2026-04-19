import streamlit as st
import pandas as pd

# MUST be the first Streamlit command
st.set_page_config(
    page_title="Sports Betting Dashboard",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -----------------------------
# SAMPLE DATA
# -----------------------------
sample_bets = pd.DataFrame(
    [
        {
            "Sport": "NBA",
            "Event": "Knicks vs Celtics",
            "Market": "Moneyline",
            "Pick": "Knicks",
            "Sportsbook": "FanDuel",
            "Odds": "+118",
            "Implied Prob": 45.9,
            "Model Prob": 49.4,
            "Edge %": 3.5,
            "Confidence": "Medium",
            "Recommended Bet": 4,
            "Status": "Bet",
        },
        {
            "Sport": "MLB",
            "Event": "Braves vs Phillies",
            "Market": "Total Runs",
            "Pick": "Over 8.5",
            "Sportsbook": "DraftKings",
            "Odds": "-105",
            "Implied Prob": 51.2,
            "Model Prob": 55.8,
            "Edge %": 4.6,
            "Confidence": "High",
            "Recommended Bet": 7,
            "Status": "Bet",
        },
        {
            "Sport": "NHL",
            "Event": "Rangers vs Devils",
            "Market": "Moneyline",
            "Pick": "Devils",
            "Sportsbook": "Bet365",
            "Odds": "+140",
            "Implied Prob": 41.7,
            "Model Prob": 39.9,
            "Edge %": -1.8,
            "Confidence": "Low",
            "Recommended Bet": 0,
            "Status": "No Bet",
        },
        {
            "Sport": "NBA",
            "Event": "Lakers vs Suns",
            "Market": "Player Prop",
            "Pick": "LeBron Over 26.5 Points",
            "Sportsbook": "PrizePicks",
            "Odds": "N/A",
            "Implied Prob": 50.0,
            "Model Prob": 53.2,
            "Edge %": 3.2,
            "Confidence": "Medium",
            "Recommended Bet": 3,
            "Status": "Bet",
        },
        {
            "Sport": "NFL",
            "Event": "Chiefs vs Bills",
            "Market": "Spread",
            "Pick": "Chiefs +2.5",
            "Sportsbook": "DraftKings",
            "Odds": "-110",
            "Implied Prob": 52.4,
            "Model Prob": 57.1,
            "Edge %": 4.7,
            "Confidence": "High",
            "Recommended Bet": 8,
            "Status": "Bet",
        },
    ]
)

# -----------------------------
# SIDEBAR
# -----------------------------
st.sidebar.title("⚙️ Dashboard Controls")
bankroll = st.sidebar.number_input("Bankroll", min_value=1.0, value=500.0, step=25.0)
min_bet = st.sidebar.number_input("Minimum Bet", min_value=1.0, value=1.0, step=1.0)
max_bet = st.sidebar.number_input("Maximum Bet", min_value=1.0, value=10.0, step=1.0)

sport_filter = st.sidebar.multiselect(
    "Filter Sports",
    options=sorted(sample_bets["Sport"].unique()),
    default=sorted(sample_bets["Sport"].unique()),
)

book_filter = st.sidebar.multiselect(
    "Filter Sportsbooks",
    options=["DraftKings", "FanDuel", "Bet365", "PrizePicks"],
    default=["DraftKings", "FanDuel", "Bet365", "PrizePicks"],
)

filtered_df = sample_bets[
    sample_bets["Sport"].isin(sport_filter) &
    sample_bets["Sportsbook"].isin(book_filter)
].copy()

live_bets = filtered_df[filtered_df["Status"] == "Bet"].copy()

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
# HEADER
# -----------------------------
st.markdown('<div class="main-title">🏈 Sports Betting Dashboard</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">Track opportunities, compare books, and size bets by risk.</div>',
    unsafe_allow_html=True,
)

best_edge = live_bets["Edge %"].max() if not live_bets.empty else 0
best_bet_row = live_bets.loc[live_bets["Edge %"].idxmax()] if not live_bets.empty else None
active_bets = len(live_bets)
avg_edge = round(live_bets["Edge %"].mean(), 2) if not live_bets.empty else 0
open_risk = live_bets["Recommended Bet"].sum() if not live_bets.empty else 0

st.markdown('<div class="hero-box">', unsafe_allow_html=True)
hero_left, hero_right = st.columns([2, 1])

with hero_left:
    st.markdown("### Today’s Top Setup")
    if best_bet_row is not None:
        st.markdown(
            f"""
            **{best_bet_row['Pick']}**  
            {best_bet_row['Event']} · {best_bet_row['Market']}  
            Book: **{best_bet_row['Sportsbook']}** · Odds: **{best_bet_row['Odds']}**  
            Edge: **{best_bet_row['Edge %']:.1f}%** · Confidence: **{best_bet_row['Confidence']}**  
            Recommended Bet: **${best_bet_row['Recommended Bet']}**
            """
        )
    else:
        st.info("No qualified bets right now.")

with hero_right:
    st.markdown('<div class="small-label">Current Bankroll</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="big-value">${bankroll:,.2f}</div>', unsafe_allow_html=True)
    st.markdown('<div class="small-label">Risk Range</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="big-value">${min_bet:.0f} - ${max_bet:.0f}</div>', unsafe_allow_html=True)

st.markdown("</div>", unsafe_allow_html=True)

# -----------------------------
# KPI ROW
# -----------------------------
k1, k2, k3, k4 = st.columns(4)

with k1:
    st.metric("Active Bets", active_bets)
with k2:
    st.metric("Best Edge", f"{best_edge:.1f}%")
with k3:
    st.metric("Average Edge", f"{avg_edge:.1f}%")
with k4:
    st.metric("Open Risk", f"${open_risk:.0f}")

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
        st.markdown('<div class="section-title">Top Recommended Bets</div>', unsafe_allow_html=True)
        top_df = live_bets.sort_values("Edge %", ascending=False).head(3)

        if top_df.empty:
            st.warning("No recommended bets available.")
        else:
            for _, row in top_df.iterrows():
                st.markdown(
                    f"""
                    <div class="best-bet">
                        <b>{row['Pick']}</b><br>
                        {row['Event']} · {row['Market']}<br>
                        Book: <b>{row['Sportsbook']}</b> · Odds: <b>{row['Odds']}</b><br>
                        Edge: <b>{row['Edge %']:.1f}%</b> · Confidence: <b>{row['Confidence']}</b><br>
                        Suggested Stake: <b>${row['Recommended Bet']}</b>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    with right:
        st.markdown('<div class="section-title">Dashboard Notes</div>', unsafe_allow_html=True)
        st.markdown(
            """
            <div class="card">
            • This is the first dashboard shell.<br>
            • Data is placeholder data right now.<br>
            • Next we will connect live odds APIs.<br>
            • Then we will add model scoring and 15-minute refresh.
            </div>
            """,
            unsafe_allow_html=True,
        )

# -----------------------------
# BEST BETS TAB
# -----------------------------
with tabs[1]:
    st.markdown('<div class="section-title">Best Bets Board</div>', unsafe_allow_html=True)

    display_df = filtered_df.sort_values(["Status", "Edge %"], ascending=[False, False]).copy()

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Implied Prob": st.column_config.NumberColumn(format="%.1f%%"),
            "Model Prob": st.column_config.NumberColumn(format="%.1f%%"),
            "Edge %": st.column_config.NumberColumn(format="%.1f%%"),
            "Recommended Bet": st.column_config.NumberColumn(format="$%d"),
        },
    )

# -----------------------------
# SPORTSBOOK TABS
# -----------------------------
def sportsbook_section(book_name: str):
    book_df = filtered_df[filtered_df["Sportsbook"] == book_name].copy()

    st.markdown(f'<div class="section-title">{book_name} Opportunities</div>', unsafe_allow_html=True)

    col1, col2 = st.columns([1.2, 1])
    with col1:
        st.markdown(
            f"""
            <div class="card">
            <b>{book_name}</b> tab will eventually show:
            <br>• Live odds
            <br>• Best available lines
            <br>• Recommendation ranking
            <br>• Direct sportsbook links
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f"""
            <div class="card">
            Qualified Bets: <b>{len(book_df[book_df['Status'] == 'Bet'])}</b><br>
            Avg Edge: <b>{book_df['Edge %'].mean():.1f}%</b><br>
            Max Stake: <b>${book_df['Recommended Bet'].max() if not book_df.empty else 0}</b>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.dataframe(
        book_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Implied Prob": st.column_config.NumberColumn(format="%.1f%%"),
            "Model Prob": st.column_config.NumberColumn(format="%.1f%%"),
            "Edge %": st.column_config.NumberColumn(format="%.1f%%"),
            "Recommended Bet": st.column_config.NumberColumn(format="$%d"),
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

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            f"""
            <div class="card">
            <div class="small-label">Starting Bankroll</div>
            <div class="big-value">${bankroll:,.2f}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f"""
            <div class="card">
            <div class="small-label">Minimum Bet</div>
            <div class="big-value">${min_bet:.0f}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c3:
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
        <b>Current bankroll rules:</b><br>
        • No bet when edge is negative<br>
        • Smaller bets for weaker confidence<br>
        • Larger bets for stronger edge and lower risk<br>
        • Hard cap at your max bet amount
        </div>
        """,
        unsafe_allow_html=True,
    )
