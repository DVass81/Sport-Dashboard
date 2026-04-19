import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(page_title='SAFE BUILD', layout='wide')

st.markdown("# SAFE BUILD — April 19, 2026")
st.caption("If you still see a heatmap or plotly error after deploying this file, Streamlit is not running this file.")

st.sidebar.header("Controls")
bankroll = st.sidebar.number_input("Bankroll", min_value=1.0, value=500.0, step=25.0)
min_bet = st.sidebar.number_input("Min bet", min_value=1.0, value=1.0, step=1.0)
max_bet = st.sidebar.number_input("Max bet", min_value=1.0, value=10.0, step=1.0)

sample = pd.DataFrame([
    {"Sport": "NBA", "Event": "Knicks @ Celtics", "Book": "FanDuel", "Pick": "Knicks ML", "Odds": "+118", "Stake": 4, "Status": "Bet"},
    {"Sport": "MLB", "Event": "Braves @ Phillies", "Book": "DraftKings", "Pick": "Over 8.5", "Odds": "-105", "Stake": 5, "Status": "Bet"},
    {"Sport": "NFL", "Event": "Chiefs @ Bills", "Book": "Bet365", "Pick": "Chiefs +2.5", "Odds": "-110", "Stake": 7, "Status": "Watch"},
])

k1, k2, k3, k4 = st.columns(4)
k1.metric("Bankroll", f"${bankroll:,.2f}")
k2.metric("Min Bet", f"${min_bet:.0f}")
k3.metric("Max Bet", f"${max_bet:.0f}")
k4.metric("Updated", datetime.now().strftime("%I:%M %p"))

tabs = st.tabs([
    "Overview", "Best Bets", "Compare Lines", "Quick Links",
    "DraftKings", "FanDuel", "Bet365", "PrizePicks",
    "AI Assistant", "Tracker", "Results", "Bankroll"
])

with tabs[0]:
    st.subheader("Overview")
    st.write("This is the safe build. No Plotly. No heatmaps. No auto-refresh.")
    st.dataframe(sample, use_container_width=True, hide_index=True)

with tabs[1]:
    st.subheader("Best Bets")
    st.dataframe(sample[sample["Status"] == "Bet"], use_container_width=True, hide_index=True)

with tabs[2]:
    st.subheader("Compare Lines")
    compare = sample[["Event", "Pick", "Book", "Odds", "Stake"]].copy()
    st.dataframe(compare, use_container_width=True, hide_index=True)

with tabs[3]:
    st.subheader("Quick Links")
    st.page_link("https://sportsbook.draftkings.com", label="DraftKings")
    st.page_link("https://sportsbook.fanduel.com", label="FanDuel")
    st.page_link("https://www.bet365.com", label="Bet365")
    st.page_link("https://app.prizepicks.com", label="PrizePicks")

for i, name in enumerate(["DraftKings", "FanDuel", "Bet365", "PrizePicks"], start=4):
    with tabs[i]:
        st.subheader(name)
        st.dataframe(sample[sample["Book"] == name], use_container_width=True, hide_index=True)

with tabs[8]:
    st.subheader("AI Assistant")
    st.write("AI tab placeholder.")
    prompt = st.text_input("Ask AI something", key="ask_ai_text")
    if prompt:
        st.info(f"You asked: {prompt}")

with tabs[9]:
    st.subheader("Tracker")
    st.selectbox("Select sample bet", sample["Pick"].tolist(), key="tracker_pick")
    st.radio("Result", ["Win", "Loss", "Push"], horizontal=True, key="tracker_result")

with tabs[10]:
    st.subheader("Results")
    results = pd.DataFrame([
        {"Metric": "Settled Bets", "Value": 12},
        {"Metric": "ROI", "Value": "8.4%"},
        {"Metric": "P/L", "Value": "$42.50"},
    ])
    st.dataframe(results, use_container_width=True, hide_index=True)

with tabs[11]:
    st.subheader("Bankroll")
    st.write(f"Starting bankroll: ${bankroll:,.2f}")
    st.write("No charts in this safe build.")
