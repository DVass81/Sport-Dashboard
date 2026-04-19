"""Edge - Sports Betting Dashboard (Streamlit)

A stock-screener-style dashboard for sports bets. Pulls odds from
SportsGameOdds across DraftKings, FanDuel, and Bet365, then ranks
opportunities by edge and recommends a bet size from your bankroll.

PrizePicks does not expose a public API; the "PrizePicks Picks" tab
shows player-prop candidates from the same odds feed so you can look
them up manually on PrizePicks.

Required env var (or Streamlit secret):
    SPORTS_GAME_ODDS_API_KEY
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import requests
import streamlit as st

LEAGUES = [
    {"id": "NBA", "name": "NBA", "sport": "Basketball"},
    {"id": "MLB", "name": "MLB", "sport": "Baseball"},
    {"id": "NHL", "name": "NHL", "sport": "Hockey"},
    {"id": "NFL", "name": "NFL", "sport": "American Football"},
]

TARGET_BOOKS = {"draftkings", "fanduel", "bet365"}

SPORTSBOOK_LINKS = [
    {"name": "DraftKings",  "url": "https://sportsbook.draftkings.com/", "color": "#53D337"},
    {"name": "FanDuel",     "url": "https://sportsbook.fanduel.com/",   "color": "#1493FF"},
    {"name": "Bet365",      "url": "https://www.bet365.com/",           "color": "#F2C100"},
    {"name": "PrizePicks",  "url": "https://app.prizepicks.com/",       "color": "#7B43F4"},
]

SGO_BASE = "https://api.sportsgameodds.com/v2"

CRIMSON = "#9E1B32"
BG = "#0B1220"
PANEL = "#121A2B"
GREEN = "#22C55E"
AMBER = "#F59E0B"
RED   = "#EF4444"
MUTED = "#94A3B8"


def get_secret(name):
    val = os.environ.get(name)
    if val:
        return val
    try:
        return st.secrets.get(name)
    except Exception:
        return None


def american_to_decimal(american):
    a = float(american)
    return 1.0 + (a / 100.0 if a > 0 else 100.0 / abs(a))


def format_american(odds):
    if odds is None:
        return "—"
    o = int(round(float(odds)))
    return f"+{o}" if o > 0 else str(o)


def format_bps(bps):
    return f"{bps:+.0f} bps"


def recommend_stake(edge_bps, books_count, min_bet, max_bet):
    if edge_bps <= 0 or books_count < 2:
        return 0.0, "Pass", RED
    if edge_bps >= 150 and books_count >= 5:
        return max_bet, "High confidence", GREEN
    if edge_bps >= 75 and books_count >= 4:
        return round(min_bet + (max_bet - min_bet) * 0.6, 2), "Medium confidence", AMBER
    if edge_bps >= 25 and books_count >= 3:
        return round(min_bet + (max_bet - min_bet) * 0.25, 2), "Low confidence", AMBER
    if edge_bps >= 10:
        return min_bet, "Speculative", MUTED
    return 0.0, "Pass", RED


@dataclass
class BookPrice:
    book: str
    price_american: float
    price_decimal: float


@dataclass
class Outcome:
    name: str
    point: float | None
    books: list = field(default_factory=list)
    best: BookPrice | None = None
    avg_decimal: float = 0.0
    edge_bps: float = 0.0
    player: str | None = None
    stat: str | None = None


@dataclass
class Market:
    type: str
    outcomes: list = field(default_factory=list)


@dataclass
class GameEvent:
    event_id: str
    league: str
    start: str
    home: str
    away: str
    markets: list = field(default_factory=list)
    player_props: list = field(default_factory=list)


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
        return (r.json() or {}).get("data") or [], None
    except requests.RequestException as e:
        return [], f"Failed to reach SportsGameOdds: {e}"


def _team_name(ev, side):
    t = (ev.get("teams") or {}).get(side) or {}
    names = t.get("names") or {}
    return names.get("long") or names.get("short") or names.get("medium") or side.title()


def _build_outcome(name, point, books, player=None, stat=None):
    if not books:
        return Outcome(name=name, point=point)
    best = max(books, key=lambda b: b.price_decimal)
    avg = sum(b.price_decimal for b in books) / len(books)
    edge = (best.price_decimal / avg - 1.0) * 10000.0 if avg > 0 else 0.0
    return Outcome(name=name, point=point, books=books, best=best,
                   avg_decimal=avg, edge_bps=edge, player=player, stat=stat)


def parse_event(ev, league, books_filter):
    odds = ev.get("odds") or {}
    if not odds:
        return None
    home = _team_name(ev, "home")
    away = _team_name(ev, "away")

    grouped = {
        "Moneyline": {"home": {}, "away": {}},
        "Spread":    {"home": {}, "away": {}},
        "Total":     {"over": {}, "under": {}},
    }
    prop_buckets = {}
    players_dir = ev.get("players") or {}

    for _odd_id, info in odds.items():
        if (info.get("periodID") or "").lower() != "game":
            continue
        bt   = (info.get("betTypeID") or "").lower()
        side = (info.get("sideID")    or "").lower()
        player_id = info.get("playerID")
        stat_id   = (info.get("statID") or info.get("statEntityID") or "").lower()

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
            prices.append(BookPrice(book=book_id, price_american=am_f,
                                    price_decimal=american_to_decimal(am_f)))
        if not prices:
            continue

        if player_id:
            try:
                point = float(info.get("overUnder") or info.get("spread") or 0)
            except (TypeError, ValueError):
                point = 0.0
            if side not in ("over", "under"):
                continue
            player_name = (players_dir.get(player_id, {}).get("name")
                           or players_dir.get(player_id, {}).get("nameFull")
                           or player_id)
            prop_buckets.setdefault((player_name, stat_id or "stat", point, side), []).extend(prices)
            continue

        if bt == "ml" and side in ("home", "away"):
            grouped["Moneyline"][side].setdefault(None, []).extend(prices)
        elif bt == "sp" and side in ("home", "away"):
            try:
                point = float(info.get("spread") or info.get("overUnder") or 0)
            except (TypeError, ValueError):
                point = None
            grouped["Spread"][side].setdefault(point, []).extend(prices)
        elif bt == "ou" and side in ("over", "under"):
            try:
                point = float(info.get("overUnder") or 0)
            except (TypeError, ValueError):
                point = None
            grouped["Total"][side].setdefault(point, []).extend(prices)

    markets = []
    ml = []
    for side_key, label in (("away", away), ("home", home)):
        bucket = grouped["Moneyline"][side_key].get(None, [])
        if bucket:
            ml.append(_build_outcome(label, None, bucket))
    if ml:
        markets.append(Market("Moneyline", ml))

    sp = []
    for side_key, label in (("away", away), ("home", home)):
        for point, bucket in grouped["Spread"][side_key].items():
            sp.append(_build_outcome(label, point, bucket))
    if sp:
        markets.append(Market("Spread", sp))

    tot = []
    for side_key, label in (("over", "Over"), ("under", "Under")):
        for point, bucket in grouped["Total"][side_key].items():
            tot.append(_build_outcome(label, point, bucket))
    if tot:
        markets.append(Market("Total", tot))

    props = []
    for (player_name, stat, point, side), bucket in prop_buckets.items():
        label = f"{side.capitalize()} {point:g} {stat}"
        props.append(_build_outcome(label, point, bucket, player=player_name, stat=stat))

    if not markets and not props:
        return None

    return GameEvent(
        event_id=ev.get("eventID") or ev.get("id") or "",
        league=league,
        start=ev.get("status", {}).get("startsAt") or ev.get("startsAt") or "",
        home=home, away=away, markets=markets, player_props=props,
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


def _pick_label(oc, market_type):
    if oc.point is None:
        return oc.name
    if market_type == "Total":
        return f"{oc.name} {oc.point:g}"
    return f"{oc.name} {oc.point:+g}"


def all_picks(books_filter, kind):
    rows = []
    for lg in LEAGUES:
        events, _ = get_board(lg["id"], books_filter)
        for ev in events:
            if kind == "team":
                for m in ev.markets:
                    for oc in m.outcomes:
                        if not oc.best:
                            continue
                        rows.append({
                            "league": lg["id"],
                            "matchup": f"{ev.away} @ {ev.home}",
                            "market": m.type,
                            "pick": _pick_label(oc, m.type),
                            "book": oc.best.book,
                            "price": oc.best.price_american,
                            "books_count": len(oc.books),
                            "edge_bps": oc.edge_bps,
                            "start": ev.start,
                        })
            else:
                for oc in ev.player_props:
                    if not oc.best:
                        continue
                    side = "Over" if oc.name.startswith("Over") else "Under"
                    rows.append({
                        "league": lg["id"],
                        "matchup": f"{ev.away} @ {ev.home}",
                        "player": oc.player,
                        "stat":  oc.stat,
                        "side":  side,
                        "line":  oc.point,
                        "book":  oc.best.book,
                        "price": oc.best.price_american,
                        "books_count": len(oc.books),
                        "edge_bps": oc.edge_bps,
                        "start": ev.start,
                    })
    rows.sort(key=lambda r: r["edge_bps"], reverse=True)
    return rows


st.set_page_config(page_title="Edge — Sports Betting Dashboard", page_icon="🏈", layout="wide")

st.markdown(f"""
<style>
:root {{ color-scheme: dark; }}
.stApp {{ background: radial-gradient(ellipse at top, #15203a 0%, {BG} 60%); }}
.block-container {{ padding-top: 1.4rem; }}
h1, h2, h3, h4 {{ color: #F8FAFC !important; letter-spacing: -0.01em; }}
section[data-testid="stSidebar"] {{ background: {PANEL}; }}
.edge-header {{
    display:flex; align-items:center; justify-content:space-between;
    padding: 18px 22px; border-radius: 14px; margin-bottom: 18px;
    background: linear-gradient(135deg, {CRIMSON} 0%, #4A0C18 100%);
    box-shadow: 0 10px 30px rgba(158,27,50,.25);
}}
.edge-header h1 {{ margin:0; font-size: 1.6rem; }}
.edge-header .tag {{ color: rgba(255,255,255,.85); font-size:.85rem; }}
.book-bar {{ display:flex; gap:10px; flex-wrap:wrap; margin-bottom: 14px; }}
.book-link {{
    display:inline-block; padding: 10px 16px; border-radius: 10px;
    color: white !important; font-weight: 700; text-decoration: none !important;
    border: 1px solid rgba(255,255,255,.08);
    box-shadow: 0 6px 20px rgba(0,0,0,.35);
}}
.pick-card {{
    background: {PANEL}; border-radius: 14px; padding: 16px 18px; margin-bottom: 12px;
    border: 1px solid rgba(255,255,255,.06);
}}
.pick-row {{ display:flex; justify-content:space-between; align-items:center; gap:12px; }}
.pick-title {{ font-size: 1.05rem; color:#F1F5F9; font-weight:700; }}
.pick-sub   {{ color:{MUTED}; font-size:.85rem; }}
.pill {{
    display:inline-block; padding: 4px 10px; border-radius: 999px;
    font-size:.8rem; font-weight:700; color:#0B1220;
}}
.kpi {{
    background:{PANEL}; padding:14px 16px; border-radius:12px;
    border:1px solid rgba(255,255,255,.06);
}}
.kpi .label {{ color:{MUTED}; font-size:.8rem; text-transform:uppercase; letter-spacing:.05em; }}
.kpi .value {{ color:#F8FAFC; font-size:1.5rem; font-weight:700; font-variant-numeric: tabular-nums; }}
.muted {{ color:{MUTED}; }}
table {{ color: #E2E8F0; }}
.stTabs [data-baseweb="tab-list"] {{ gap: 6px; }}
.stTabs [data-baseweb="tab"] {{
    background: {PANEL}; padding: 10px 16px; border-radius: 10px 10px 0 0;
    color: #CBD5E1;
}}
.stTabs [aria-selected="true"] {{ background: {CRIMSON} !important; color: white !important; }}
</style>
""", unsafe_allow_html=True)

st.markdown(f"""
<div class="edge-header">
  <div>
    <h1>EDGE · Sports Betting Terminal</h1>
    <div class="tag">Risk-tiered picks across DraftKings, FanDuel, Bet365 · PrizePicks player-prop candidates</div>
  </div>
  <div class="tag">Updated {datetime.now().strftime("%I:%M %p")}</div>
</div>
""", unsafe_allow_html=True)

links_html = "<div class='book-bar'>" + "".join(
    f"<a class='book-link' style='background:{b['color']}' href='{b['url']}' target='_blank' rel='noopener'>Open {b['name']}</a>"
    for b in SPORTSBOOK_LINKS
) + "</div>"
st.markdown(links_html, unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### Bankroll")
    bankroll = st.number_input("Bankroll ($)", min_value=10.0, value=500.0, step=10.0)
    min_bet  = st.number_input("Min bet ($)",  min_value=1.0,  value=1.0,   step=1.0)
    max_bet  = st.number_input("Max bet ($)",  min_value=min_bet, value=max(10.0, min_bet), step=1.0)
    daily_cap_pct = st.slider("Daily exposure cap (% of bankroll)", 5, 100, 20)
    st.caption("Sizing tiers: $1 speculative → $10 high-confidence. 'Pass' when no edge.")
    st.markdown("---")
    st.markdown("### Filters")
    book_choice = st.multiselect(
        "Books to compare",
        ["draftkings", "fanduel", "bet365"],
        default=["draftkings", "fanduel", "bet365"],
    )

books_filter = set(book_choice) if book_choice else TARGET_BOOKS
daily_cap = bankroll * daily_cap_pct / 100.0

tab_picks, tab_props, tab_board, tab_bank = st.tabs(
    ["🎯 Suggested Picks", "🏀 PrizePicks Picks", "📊 Odds Board", "💰 Bankroll"]
)

with tab_picks:
    st.subheader("Today's Suggested Bets")
    rows = all_picks(books_filter, kind="team")

    if rows:
        sized = [(r, *recommend_stake(r["edge_bps"], r["books_count"], min_bet, max_bet)) for r in rows]
        playable = [s for s in sized if s[1] > 0]
        total_stake = sum(s[1] for s in playable)
        top_edge = max((r["edge_bps"] for r in rows), default=0.0)
    else:
        sized, playable, total_stake, top_edge = [], [], 0.0, 0.0

    kc = st.columns(4)
    kc[0].markdown(f"<div class='kpi'>
