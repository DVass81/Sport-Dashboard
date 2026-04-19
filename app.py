"""Edge - Sports Betting Dashboard (Streamlit single-file app)

Tabs: Home | Odds Board | Best Bets | Bankroll

Required environment variables (or Streamlit secrets):
    SPORTS_GAME_ODDS_API_KEY   - https://sportsgameodds.com
    THESPORTSDB_API_KEY        - https://www.thesportsdb.com (optional; falls back)
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests
import streamlit as st

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

LEAGUES = [
    {"id": "NBA", "name": "NBA", "sport": "Basketball"},
    {"id": "MLB", "name": "MLB", "sport": "Baseball"},
    {"id": "NHL", "name": "NHL", "sport": "Hockey"},
    {"id": "NFL", "name": "NFL", "sport": "American Football"},
]

KNOWN_SPORTSBOOKS = [
    "draftkings", "fanduel", "betmgm", "caesars", "pointsbet",
    "betrivers", "wynnbet", "bet365", "pinnacle", "circa",
]

SGO_BASE = "https://api.sportsgameodds.com/v2"
TSDB_BASE = "https://www.thesportsdb.com/api/v1/json"

ALABAMA_FALLBACK = {
    "team": "Alabama Crimson Tide",
    "sport": "American Football",
    "league": "NCAA Football",
    "logoUrl": None,
    "badgeUrl": None,
    "bannerUrl": None,
    "stadium": "Bryant\u2013Denny Stadium",
    "description": None,
    "colors": ["#9E1B32", "#FFFFFF"],
}

CRIMSON = "#9E1B32"


def get_secret(name: str) -> str | None:
    val = os.environ.get(name)
    if val:
        return val
    try:
        return st.secrets.get(name)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Odds math
# ---------------------------------------------------------------------------

def american_to_decimal(american):
    a = float(american)
    return 1.0 + (a / 100.0 if a > 0 else 100.0 / abs(a))


def implied_prob(american):
    return 1.0 / american_to_decimal(american)


def format_american(odds):
    if odds is None:
        return "\u2014"
    o = int(round(float(odds)))
    return f"+{o}" if o > 0 else str(o)


def format_bps(bps):
    return f"{bps:+.0f} bps"


# ---------------------------------------------------------------------------
# TheSportsDB - Alabama branding
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_alabama_branding():
    key = get_secret("THESPORTSDB_API_KEY")
    if not key:
        return ALABAMA_FALLBACK
    try:
        r = requests.get(
            f"{TSDB_BASE}/{key}/searchteams.php",
            params={"t": "Alabama Crimson Tide"},
            timeout=10,
        )
        r.raise_for_status()
        teams = (r.json() or {}).get("teams") or []
        if not teams:
            return ALABAMA_FALLBACK
        t = teams[0]
        return {
            "team": t.get("strTeam") or "Alabama Crimson Tide",
            "sport": t.get("strSport") or "American Football",
            "league": t.get("strLeague") or "NCAA Football",
            "logoUrl": t.get("strTeamLogo"),
            "badgeUrl": t.get("strTeamBadge"),
            "bannerUrl": t.get("strTeamBanner") or t.get("strTeamFanart1"),
            "stadium": t.get("strStadium") or "Bryant\u2013Denny Stadium",
            "description": t.get("strDescriptionEN"),
            "colors": ["#9E1B32", "#FFFFFF"],
        }
    except Exception:
        return ALABAMA_FALLBACK


# ---------------------------------------------------------------------------
# SportsGameOdds - events + market parsing
# ---------------------------------------------------------------------------

@dataclass
class BookPrice:
    book: str
    price_american: float
    price_decimal: float


@dataclass
class Outcome:
    name: str
    point: float | None
    books: list
    best: BookPrice | None
    avg_decimal: float
    edge_bps: float


@dataclass
class Market:
    type: str
    outcomes: list


@dataclass
class GameEvent:
    event_id: str
    league: str
    start: str
    home: str
    away: str
    markets: list


@st.cache_data(ttl=60, show_spinner=False)
def fetch_events(league):
    key = get_secret("SPORTS_GAME_ODDS_API_KEY")
    if not key:
        return [], "SPORTS_GAME_ODDS_API_KEY is not configured."
    try:
        r = requests.get(
            f"{SGO_BASE}/events",
            params={
                "leagueID": league,
                "type": "match",
                "oddsAvailable": "true",
                "startsAfter": datetime.now(timezone.utc).isoformat(),
                "limit": 50,
            },
            headers={"x-api-key": key},
            timeout=15,
        )
        if r.status_code in (401, 403):
            return [], "SportsGameOdds rejected the API key."
        r.raise_for_status()
        data = r.json() or {}
        return data.get("data") or [], None
    except requests.RequestException as e:
        return [], f"Failed to reach SportsGameOdds: {e}"


def _team_name(ev, side):
    t = (ev.get("teams") or {}).get(side) or {}
    names = t.get("names") or {}
    return names.get("long") or names.get("short") or names.get("medium") or side.title()


def _build_outcome(name, point, books):
    if not books:
        return Outcome(name=name, point=point, books=[], best=None, avg_decimal=0.0, edge_bps=0.0)
    best = max(books, key=lambda b: b.price_decimal)
    avg = sum(b.price_decimal for b in books) / len(books)
    edge = (best.price_decimal / avg - 1.0) * 10000.0 if avg > 0 else 0.0
    return Outcome(name=name, point=point, books=books, best=best, avg_decimal=avg, edge_bps=edge)


def parse_event(ev, league, books_filter):
    odds = ev.get("odds") or {}
    if not odds:
        return None
    home = _team_name(ev, "home")
    away = _team_name(ev, "away")

    grouped = {
        "Moneyline": {"home": {}, "away": {}},
        "Spread": {"home": {}, "away": {}},
        "Total": {"over": {}, "under": {}},
    }

    for _odd_id, info in odds.items():
        if (info.get("periodID") or "").lower() != "game":
            continue
        bt = (info.get("betTypeID") or "").lower()
        side = (info.get("sideID") or "").lower()
        if bt == "ml" and side in ("home", "away"):
            mtype, key_side, point = "Moneyline", side, None
        elif bt == "sp" and side in ("home", "away"):
            mtype, key_side = "Spread", side
            try:
                point = float(info.get("spread") or info.get("overUnder") or 0)
            except (TypeError, ValueError):
                point = None
        elif bt == "ou" and side in ("over", "under"):
            mtype, key_side = "Total", side
            try:
                point = float(info.get("overUnder") or 0)
            except (TypeError, ValueError):
                point = None
        else:
            continue

        by_book = info.get("byBookmaker") or {}
        prices = []
        for book_id, b in by_book.items():
            if books_filter and book_id.lower() not in books_filter:
                continue
            if not b.get("available", True):
                continue
            am = b.get("odds")
            if am is None:
                continue
            try:
                am_f = float(am)
            except (TypeError, ValueError):
                continue
            prices.append(BookPrice(
                book=book_id,
                price_american=am_f,
                price_decimal=american_to_decimal(am_f),
            ))
        if not prices:
            continue
        grouped[mtype][key_side].setdefault(point, []).extend(prices)

    markets = []
    ml_outcomes = []
    for side_key, label in (("away", away), ("home", home)):
        bucket = grouped["Moneyline"][side_key].get(None, [])
        if bucket:
            ml_outcomes.append(_build_outcome(label, None, bucket))
    if ml_outcomes:
        markets.append(Market(type="Moneyline", outcomes=ml_outcomes))

    sp_outcomes = []
    for side_key, label in (("away", away), ("home", home)):
        for point, bucket in grouped["Spread"][side_key].items():
            sp_outcomes.append(_build_outcome(label, point, bucket))
    if sp_outcomes:
        markets.append(Market(type="Spread", outcomes=sp_outcomes))

    tot_outcomes = []
    for side_key, label in (("over", "Over"), ("under", "Under")):
        for point, bucket in grouped["Total"][side_key].items():
            tot_outcomes.append(_build_outcome(label, point, bucket))
    if tot_outcomes:
        markets.append(Market(type="Total", outcomes=tot_outcomes))

    if not markets:
        return None

    return GameEvent(
        event_id=ev.get("eventID") or ev.get("id") or "",
        league=league,
        start=ev.get("status", {}).get("startsAt") or ev.get("startsAt") or "",
        home=home,
        away=away,
        markets=markets,
    )


def get_board(league, books_filter):
    raw, warn = fetch_events(league)
    if warn:
        return [], warn
    events = []
    for ev in raw:
        parsed = parse_event(ev, league, books_filter)
        if parsed:
            events.append(parsed)
    return events, None


def compute_best_bets(books_filter, min_books=3):
    rows = []
    for lg in LEAGUES:
        events, _ = get_board(lg["id"], books_filter)
        for ev in events:
            for m in ev.markets:
                for oc in m.outcomes:
                    if len(oc.books) < min_books or oc.edge_bps <= 0:
                        continue
                    if oc.point is not None and m.type != "Total":
                        outcome_label = f"{oc.name} {oc.point:+g}"
                    elif oc.point is not None:
                        outcome_label = f"{oc.name} {oc.point:g}"
                    else:
                        outcome_label = oc.name
                    rows.append({
                        "league": lg["id"],
                        "matchup": f"{ev.away} @ {ev.home}",
                        "market": m.type,
                        "outcome": outcome_label,
                        "best_book": oc.best.book if oc.best else "",
                        "best_price": format_american(oc.best.price_american) if oc.best else "",
                        "books_count": len(oc.books),
                        "edge_bps": oc.edge_bps,
                        "start": ev.start,
                    })
    rows.sort(key=lambda r: r["edge_bps"], reverse=True)
    return rows


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Edge - Sports Betting Dashboard", page_icon="\U0001F3C8", layout="wide")

st.markdown(
    f"""
    <style>
    .edge-hero {{
        background: linear-gradient(135deg, {CRIMSON} 0%, #6b1322 100%);
        color: white; padding: 24px 28px; border-radius: 12px; margin-bottom: 16px;
    }}
    .edge-hero h1 {{ color: white; margin: 0 0 4px 0; }}
    .edge-hero p {{ color: rgba(255,255,255,0.85); margin: 0; }}
    .best-price {{ color: {CRIMSON}; font-weight: 700; }}
    .muted {{ color: #6b7280; font-size: 0.85rem; }}
    [data-testid="stMetricValue"] {{ font-variant-numeric: tabular-nums; }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Edge")
st.caption("Bloomberg terminal for sports odds")

tab_home, tab_board, tab_best, tab_bank = st.tabs(["Home", "Odds Board", "Best Bets", "Bankroll"])


# ----- Home -----
with tab_home:
    branding = fetch_alabama_branding()
    col_hero, col_logo = st.columns([3, 1])
    with col_hero:
        st.markdown(
            f"""
            <div class="edge-hero">
                <h1>{branding['team']}</h1>
                <p>{branding['league']} \u00b7 {branding['sport']} \u00b7 {branding['stadium']}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col_logo:
        if branding.get("badgeUrl"):
            st.image(branding["badgeUrl"], width=140)
        elif branding.get("logoUrl"):
            st.image(branding["logoUrl"], width=140)

    st.subheader("Today")
    summary_cols = st.columns(4)
    total_events = 0
    total_books = set()
    top_edge = 0.0
    leagues_live = 0
    for lg in LEAGUES:
        evs, _ = get_board(lg["id"], None)
        if evs:
            leagues_live += 1
        total_events += len(evs)
        for ev in evs:
            for m in ev.markets:
                for oc in m.outcomes:
                    for bp in oc.books:
                        total_books.add(bp.book)
                    if oc.edge_bps > top_edge:
                        top_edge = oc.edge_bps
    summary_cols[0].metric("Leagues live", leagues_live)
    summary_cols[1].metric("Events", total_events)
    summary_cols[2].metric("Sportsbooks", len(total_books))
    summary_cols[3].metric("Top edge", format_bps(top_edge))

    st.subheader("Top edges right now")
    best = compute_best_bets(None)[:5]
    if not best:
        st.info("No edges available yet. Add your API key or check back when games are on the board.")
    else:
        st.dataframe(
            [
                {
                    "League": r["league"],
                    "Matchup": r["matchup"],
                    "Market": r["market"],
                    "Pick": r["outcome"],
                    "Best book": r["best_book"],
                    "Price": r["best_price"],
                    "Books": r["books_count"],
                    "Edge": format_bps(r["edge_bps"]),
                }
                for r in best
            ],
            hide_index=True,
            use_container_width=True,
        )


# ----- Odds Board -----
with tab_board:
    c1, c2 = st.columns([1, 3])
    league_id = c1.selectbox("League", [lg["id"] for lg in LEAGUES], index=0)
    selected_books = c2.multiselect(
        "Sportsbooks",
        KNOWN_SPORTSBOOKS,
        default=[],
        help="Leave empty to include all books returned by the feed.",
    )
    books_filter = {b.lower() for b in selected_books} if selected_books else None

    events, warn = get_board(league_id, books_filter)
    if warn:
        st.warning(warn)
    if not events:
        st.info("No events on the board.")
    for ev in events:
        with st.container(border=True):
            st.markdown(f"**{ev.away} @ {ev.home}**  <span class='muted'>{ev.start}</span>", unsafe_allow_html=True)
            for m in ev.markets:
                st.caption(m.type)
                rows = []
                for oc in m.outcomes:
                    if oc.point is not None and m.type != "Total":
                        label = f"{oc.name} ({oc.point:+g})"
                    elif oc.point is not None:
                        label = f"{oc.name} {oc.point:g}"
                    else:
                        label = oc.name
                    best_str = (
                        f"<span class='best-price'>{format_american(oc.best.price_american)} @ {oc.best.book}</span>"
                        if oc.best else "\u2014"
                    )
                    rows.append({
                        "Outcome": label,
                        "Best": best_str,
                        "Books": len(oc.books),
                        "Edge": format_bps(oc.edge_bps),
                    })
                table_html = "<table style='width:100%; font-size:0.9rem;'><tr>" + "".join(
                    f"<th align='left'>{c}</th>" for c in ("Outcome", "Best", "Books", "Edge")
                ) + "</tr>" + "".join(
                    "<tr>" + "".join(f"<td>{r[c]}</td>" for c in ("Outcome", "Best", "Books", "Edge")) + "</tr>"
                    for r in rows
                ) + "</table>"
                st.markdown(table_html, unsafe_allow_html=True)


# ----- Best Bets -----
with tab_best:
    cc1, cc2 = st.columns([1, 3])
    min_books = cc1.slider("Minimum books", 2, 8, 3)
    selected_books_b = cc2.multiselect("Sportsbooks (optional)", KNOWN_SPORTSBOOKS, default=[], key="bb_books")
    bf = {b.lower() for b in selected_books_b} if selected_books_b else None

    rows = compute_best_bets(bf, min_books=min_books)
    if not rows:
        st.info("No positive-edge bets right now.")
    else:
        st.dataframe(
            [
                {
                    "Edge": format_bps(r["edge_bps"]),
                    "League": r["league"],
                    "Matchup": r["matchup"],
                    "Market": r["market"],
                    "Pick": r["outcome"],
                    "Best book": r["best_book"],
                    "Price": r["best_price"],
                    "Books": r["books_count"],
                    "Start": r["start"],
                }
                for r in rows
            ],
            hide_index=True,
            use_container_width=True,
        )


# ----- Bankroll -----
with tab_bank:
    if "bets" not in st.session_state:
        st.session_state.bets = []

    c1, c2, c3 = st.columns(3)
    bankroll = c1.number_input("Starting bankroll ($)", min_value=0.0, value=1000.0, step=50.0)
    unit_pct = c2.number_input("Unit size (% of bankroll)", min_value=0.1, max_value=10.0, value=1.0, step=0.1)
    max_exposure_pct = c3.number_input("Max daily exposure (% of bankroll)", min_value=1.0, max_value=100.0, value=20.0, step=1.0)

    unit_dollars = bankroll * unit_pct / 100.0
    max_exposure = bankroll * max_exposure_pct / 100.0

    m1, m2, m3 = st.columns(3)
    m1.metric("Unit", f"${unit_dollars:,.2f}")
    m2.metric("Max daily exposure", f"${max_exposure:,.2f}")
    today = datetime.now(timezone.utc).date().isoformat()
    today_exposure = sum(b["stake"] for b in st.session_state.bets if b.get("status") == "open" and b.get("date") == today)
    m3.metric("Today's exposure", f"${today_exposure:,.2f}", delta=f"${max_exposure - today_exposure:,.2f} left")

    st.subheader("Log a bet")
    with st.form("log_bet", clear_on_submit=True):
        f1, f2, f3, f4 = st.columns([2, 2, 1, 1])
        desc = f1.text_input("Description", placeholder="e.g. Lakers ML")
        book = f2.text_input("Book", placeholder="e.g. draftkings")
        odds = f3.number_input("American odds", value=-110, step=5)
        stake = f4.number_input("Stake ($)", min_value=0.0, value=unit_dollars, step=5.0)
        submit = st.form_submit_button("Add bet", type="primary")
        if submit and desc:
            st.session_state.bets.append({
                "id": str(time.time()),
                "date": today,
                "desc": desc,
                "book": book,
                "odds": int(odds),
                "stake": float(stake),
                "to_win": float(stake) * (american_to_decimal(int(odds)) - 1.0),
                "status": "open",
            })

    st.subheader("Active bets")
    open_bets = [b for b in st.session_state.bets if b["status"] == "open"]
    if not open_bets:
        st.caption("No open bets.")
    else:
        for b in open_bets:
            cols = st.columns([3, 2, 1, 1, 1, 1, 1])
            cols[0].write(f"**{b['desc']}**")
            cols[1].write(b["book"])
            cols[2].write(format_american(b["odds"]))
            cols[3].write(f"${b['stake']:,.2f}")
            cols[4].write(f"+${b['to_win']:,.2f}")
            if cols[5].button("Win", key=f"w{b['id']}"):
                b["status"] = "won"
                st.rerun()
            if cols[6].button("Loss", key=f"l{b['id']}"):
                b["status"] = "lost"
                st.rerun()

    settled = [b for b in st.session_state.bets if b["status"] != "open"]
    if settled:
        pnl = sum(b["to_win"] if b["status"] == "won" else -b["stake"] for b in settled)
        st.metric("Settled P&L", f"${pnl:,.2f}")
