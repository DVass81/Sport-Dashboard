"""Edge - Sports Betting Dashboard (Streamlit)"""
from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import prod

import altair as alt
import pandas as pd
import requests
import streamlit as st

LEAGUES = [
    {"id": "NBA", "name": "NBA"},
    {"id": "MLB", "name": "MLB"},
    {"id": "NHL", "name": "NHL"},
    {"id": "NFL", "name": "NFL"},
]

TARGET_BOOKS = {"draftkings", "fanduel", "bet365"}

SPORTSBOOK_LINKS = [
    {"name": "DraftKings", "url": "https://sportsbook.draftkings.com/", "color": "#53D337"},
    {"name": "FanDuel",    "url": "https://sportsbook.fanduel.com/",   "color": "#1493FF"},
    {"name": "Bet365",     "url": "https://www.bet365.com/",           "color": "#F2C100"},
    {"name": "PrizePicks", "url": "https://app.prizepicks.com/",       "color": "#7B43F4"},
]

SGO_BASE = "https://api.sportsgameodds.com/v2"
DB_PATH = os.environ.get("EDGE_DB_PATH", "edge_bets.db")

CRIMSON = "#9E1B32"
BG = "#0B1220"
PANEL = "#121A2B"
GREEN = "#22C55E"
AMBER = "#F59E0B"
RED = "#EF4444"
MUTED = "#94A3B8"

TIER_COLORS = {
    "High confidence":   GREEN,
    "Medium confidence": AMBER,
    "Low confidence":    AMBER,
    "Speculative":       MUTED,
    "Pass":              RED,
}


def db_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS bets (
            id TEXT PRIMARY KEY,
            date TEXT,
            description TEXT,
            book TEXT,
            odds INTEGER,
            stake REAL,
            to_win REAL,
            status TEXT,
            kind TEXT,
            legs TEXT,
            created_at TEXT,
            settled_at TEXT
        )"""
    )
    conn.commit()
    return conn


def db_load_bets():
    conn = db_conn()
    rows = conn.execute(
        "SELECT * FROM bets ORDER BY created_at ASC"
    ).fetchall()
    return [dict(r) for r in rows]


def db_insert_bet(bet):
    conn = db_conn()
    conn.execute(
        """INSERT INTO bets
        (id, date, description, book, odds, stake, to_win, status, kind, legs,
         created_at, settled_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            bet["id"], bet["date"], bet["description"], bet["book"],
            int(bet["odds"]), float(bet["stake"]), float(bet["to_win"]),
            bet["status"], bet.get("kind", "single"), bet.get("legs"),
            bet["created_at"], bet.get("settled_at"),
        ),
    )
    conn.commit()


def db_settle_bet(bet_id, status):
    conn = db_conn()
    conn.execute(
        "UPDATE bets SET status=?, settled_at=? WHERE id=?",
        (status, datetime.now(timezone.utc).isoformat(), bet_id),
    )
    conn.commit()


def db_delete_bet(bet_id):
    conn = db_conn()
    conn.execute("DELETE FROM bets WHERE id=?", (bet_id,))
    conn.commit()


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


def decimal_to_american(dec):
    if dec >= 2.0:
        return int(round((dec - 1.0) * 100))
    return int(round(-100.0 / (dec - 1.0)))


def format_american(odds):
    if odds is None:
        return "-"
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


def kpi(label, value, color="#F8FAFC"):
    return (
        "<div class='kpi'>"
        f"<div class='label'>{label}</div>"
        f"<div class='value' style='color:{color}'>{value}</div>"
        "</div>"
    )


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
    return (
        names.get("long")
        or names.get("short")
        or names.get("medium")
        or side.title()
    )


def _build_outcome(name, point, books, player=None, stat=None):
    if not books:
        return Outcome(name=name, point=point)
    best = max(books, key=lambda b: b.price_decimal)
    avg = sum(b.price_decimal for b in books) / len(books)
    edge = (best.price_decimal / avg - 1.0) * 10000.0 if avg > 0 else 0.0
    return Outcome(
        name=name, point=point, books=books, best=best,
        avg_decimal=avg, edge_bps=edge, player=player, stat=stat,
    )


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
        bt = (info.get("betTypeID") or "").lower()
        side = (info.get("sideID") or "").lower()
        player_id = info.get("playerID")
        stat_id = (info.get("statID") or info.get("statEntityID") or "").lower()

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

        if player_id:
            try:
                point = float(info.get("overUnder") or info.get("spread") or 0)
            except (TypeError, ValueError):
                point = 0.0
            if side not in ("over", "under"):
                continue
            player_name = (
                players_dir.get(player_id, {}).get("name")
                or players_dir.get(player_id, {}).get("nameFull")
                or player_id
            )
            key_t = (player_name, stat_id or "stat", point, side)
            prop_buckets.setdefault(key_t, []).extend(prices)
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
                        "stat": oc.stat,
                        "side": side,
                        "line": oc.point,
                        "book": oc.best.book,
                        "price": oc.best.price_american,
                        "books_count": len(oc.books),
                        "edge_bps": oc.edge_bps,
                        "start": ev.start,
                    })
    rows.sort(key=lambda r: r["edge_bps"], reverse=True)
    return rows


st.set_page_config(
    page_title="Edge - Sports Betting Dashboard",
    page_icon="🏈",
    layout="wide",
)

CSS = """
<style>
:root { color-scheme: dark; }
.stApp { background: radial-gradient(ellipse at top, #15203a 0%, __BG__ 60%); }
.block-container { padding-top: 1.4rem; }
h1, h2, h3, h4 { color: #F8FAFC !important; letter-spacing: -0.01em; }
section[data-testid="stSidebar"] { background: __PANEL__; }
.edge-header {
    display:flex; align-items:center; justify-content:space-between;
    padding: 18px 22px; border-radius: 14px; margin-bottom: 18px;
    background: linear-gradient(135deg, __CRIMSON__ 0%, #4A0C18 100%);
    box-shadow: 0 10px 30px rgba(158,27,50,.25);
}
.edge-header h1 { margin:0; font-size: 1.6rem; }
.edge-header .tag { color: rgba(255,255,255,.85); font-size:.85rem; }
.book-bar { display:flex; gap:10px; flex-wrap:wrap; margin-bottom: 14px; }
.book-link {
    display:inline-block; padding: 10px 16px; border-radius: 10px;
    color: white !important; font-weight: 700; text-decoration: none !important;
    border: 1px solid rgba(255,255,255,.08);
    box-shadow: 0 6px 20px rgba(0,0,0,.35);
}
.pick-card {
    background: __PANEL__; border-radius: 14px; padding: 16px 18px; margin-bottom: 12px;
    border: 1px solid rgba(255,255,255,.06);
}
.pick-row { display:flex; justify-content:space-between; align-items:center; gap:12px; }
.pick-title { font-size: 1.05rem; color:#F1F5F9; font-weight:700; }
.pick-sub { color:__MUTED__; font-size:.85rem; }
.pill {
    display:inline-block; padding: 4px 10px; border-radius: 999px;
    font-size:.8rem; font-weight:700; color:#0B1220;
}
.kpi {
    background:__PANEL__; padding:14px 16px; border-radius:12px;
    border:1px solid rgba(255,255,255,.06);
}
.kpi .label { color:__MUTED__; font-size:.8rem; text-transform:uppercase; letter-spacing:.05em; }
.kpi .value { color:#F8FAFC; font-size:1.5rem; font-weight:700; font-variant-numeric: tabular-nums; }
.muted { color:__MUTED__; }
table { color: #E2E8F0; }
.stTabs [data-baseweb="tab-list"] { gap: 6px; }
.stTabs [data-baseweb="tab"] {
    background: __PANEL__; padding: 10px 16px; border-radius: 10px 10px 0 0;
    color: #CBD5E1;
}
.stTabs [aria-selected="true"] { background: __CRIMSON__ !important; color: white !important; }
</style>
"""
CSS = (
    CSS.replace("__BG__", BG)
       .replace("__PANEL__", PANEL)
       .replace("__CRIMSON__", CRIMSON)
       .replace("__MUTED__", MUTED)
)
st.markdown(CSS, unsafe_allow_html=True)

now_str = datetime.now().strftime("%I:%M %p")
header_html = (
    "<div class='edge-header'>"
    "<div>"
    "<h1>EDGE - Sports Betting Terminal</h1>"
    "<div class='tag'>Risk-tiered picks across DraftKings, FanDuel, Bet365 - "
    "PrizePicks player-prop candidates</div>"
    "</div>"
    f"<div class='tag'>Updated {now_str}</div>"
    "</div>"
)
st.markdown(header_html, unsafe_allow_html=True)

links_html = "<div class='book-bar'>"
for b in SPORTSBOOK_LINKS:
    links_html += (
        f"<a class='book-link' style='background:{b['color']}' "
        f"href='{b['url']}' target='_blank' rel='noopener'>"
        f"Open {b['name']}</a>"
    )
links_html += "</div>"
st.markdown(links_html, unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### Bankroll")
    bankroll = st.number_input("Bankroll ($)", min_value=10.0, value=500.0, step=10.0)
    min_bet = st.number_input("Min bet ($)", min_value=1.0, value=1.0, step=1.0)
    max_bet = st.number_input(
        "Max bet ($)", min_value=min_bet, value=max(10.0, min_bet), step=1.0,
    )
    daily_cap_pct = st.slider("Daily exposure cap (% of bankroll)", 5, 100, 20)
    st.caption("Sizing: $1 speculative -> $10 high-confidence. 'Pass' when no edge.")
    st.markdown("---")
    st.markdown("### Filters")
    book_choice = st.multiselect(
        "Books to compare",
        ["draftkings", "fanduel", "bet365"],
        default=["draftkings", "fanduel", "bet365"],
    )

books_filter = set(book_choice) if book_choice else TARGET_BOOKS
daily_cap = bankroll * daily_cap_pct / 100.0

tab_picks, tab_props, tab_parlay, tab_board, tab_bank = st.tabs(
    ["Suggested Picks", "PrizePicks Picks", "Parlay Builder", "Odds Board", "Bankroll"]
)

with tab_picks:
    st.subheader("Today's Suggested Bets")
    rows = all_picks(books_filter, kind="team")

    if rows:
        sized = [
            (r, *recommend_stake(r["edge_bps"], r["books_count"], min_bet, max_bet))
            for r in rows
        ]
        playable = [s for s in sized if s[1] > 0]
        total_stake = sum(s[1] for s in playable)
        top_edge = max((r["edge_bps"] for r in rows), default=0.0)
    else:
        sized, playable, total_stake, top_edge = [], [], 0.0, 0.0

    kc = st.columns(4)
    kc[0].markdown(kpi("Bankroll", f"${bankroll:,.0f}"), unsafe_allow_html=True)
    kc[1].markdown(kpi("Playable picks", str(len(playable))), unsafe_allow_html=True)
    kc[2].markdown(
        kpi("Suggested stake", f"${min(total_stake, daily_cap):,.2f}"),
        unsafe_allow_html=True,
    )
    kc[3].markdown(kpi("Top edge", format_bps(top_edge)), unsafe_allow_html=True)
    st.markdown("&nbsp;", unsafe_allow_html=True)

    if sized:
        tier_counts = {}
        for _, _, tier, _ in sized:
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
        donut_df = pd.DataFrame([
            {"Tier": t, "Count": c} for t, c in tier_counts.items()
        ])
        order = ["High confidence", "Medium confidence", "Low confidence",
                 "Speculative", "Pass"]
        donut = (
            alt.Chart(donut_df)
            .mark_arc(innerRadius=60, outerRadius=110, stroke=BG, strokeWidth=2)
            .encode(
                theta=alt.Theta("Count:Q"),
                color=alt.Color(
                    "Tier:N",
                    scale=alt.Scale(
                        domain=order,
                        range=[GREEN, AMBER, "#D97706", MUTED, RED],
                    ),
                    legend=alt.Legend(title="Confidence", labelColor="#E2E8F0",
                                      titleColor="#F8FAFC"),
                ),
                tooltip=["Tier", "Count"],
            )
            .properties(height=240, background=PANEL, title=alt.TitleParams(
                "Confidence breakdown", color="#F8FAFC", anchor="start",
            ))
        )
        ch_col, sp_col = st.columns([1, 2])
        ch_col.altair_chart(donut, use_container_width=True)
        with sp_col:
            st.markdown("&nbsp;", unsafe_allow_html=True)

    if not rows:
        st.info("No bets to suggest right now. Check that your API key is set.")
    else:
        running = 0.0
        for r, stake, tier, color in sized[:25]:
            capped = stake
            if running + stake > daily_cap and stake > 0:
                capped = max(0.0, daily_cap - running)
            running += capped
            stake_txt = f"${capped:,.2f}" if capped > 0 else "Pass"
            stake_color = color if capped > 0 else RED
            card = (
                "<div class='pick-card'><div class='pick-row'>"
                "<div>"
                f"<div class='pick-title'>{r['matchup']} - "
                f"<span class='muted'>{r['league']} - {r['market']}</span></div>"
                f"<div class='pick-sub'>Pick: <b style='color:#F8FAFC'>{r['pick']}</b> "
                f"@ {format_american(r['price'])} on <b>{r['book']}</b> - "
                f"{r['books_count']} books compared</div>"
                "</div>"
                "<div style='text-align:right;'>"
                f"<span class='pill' style='background:{color}'>{tier}</span>"
                f"<div style='font-size:1.3rem; font-weight:800; color:{stake_color}; "
                f"margin-top:6px;'>{stake_txt}</div>"
                f"<div class='pick-sub'>{format_bps(r['edge_bps'])} edge</div>"
                "</div></div></div>"
            )
            st.markdown(card, unsafe_allow_html=True)
        if running >= daily_cap:
            st.caption(
                f"Daily cap of ${daily_cap:,.2f} reached. Remaining picks shown as Pass."
            )

with tab_props:
    st.subheader("PrizePicks-Style Player Picks")
    st.caption(
        "PrizePicks doesn't publish a public API. These are player props from "
        "sportsbook feeds, ranked by edge - use them as a shortlist for PrizePicks."
    )
    prop_rows = all_picks(books_filter, kind="player")
    if not prop_rows:
        st.info("No player props are coming through the feed right now.")
    else:
        for r in prop_rows[:25]:
            stake, tier, color = recommend_stake(
                r["edge_bps"], r["books_count"], min_bet, max_bet
            )
            stake_txt = f"${stake:,.2f}" if stake > 0 else "Pass"
            card = (
                "<div class='pick-card'><div class='pick-row'>"
                "<div>"
                f"<div class='pick-title'>{r['player']} - "
                f"<span class='muted'>{r['stat']} {r['side']} {r['line']:g}</span></div>"
                f"<div class='pick-sub'>{r['matchup']} - {r['league']} - "
                f"best @ {format_american(r['price'])} on {r['book']} - "
                f"{r['books_count']} books</div>"
                "</div>"
                "<div style='text-align:right;'>"
                f"<span class='pill' style='background:{color}'>{tier}</span>"
                f"<div style='font-size:1.2rem; font-weight:800; color:{color}; "
                f"margin-top:6px;'>{stake_txt}</div>"
                f"<div class='pick-sub'>{format_bps(r['edge_bps'])} edge</div>"
                "</div></div></div>"
            )
            st.markdown(card, unsafe_allow_html=True)

with tab_parlay:
    st.subheader("Parlay Builder")
    st.caption(
        "Combine 2+ picks into a parlay. Combined odds, payout, and the "
        "implied break-even win rate are calculated from the best line per leg."
    )
    pool = all_picks(books_filter, kind="team")
    if not pool:
        st.info("No picks available to build a parlay.")
    else:
        labels = [
            f"{r['matchup']} - {r['market']}: {r['pick']} "
            f"({format_american(r['price'])} @ {r['book']}) "
            f"[{format_bps(r['edge_bps'])}]"
            for r in pool
        ]
        chosen = st.multiselect(
            "Select 2 or more legs",
            options=list(range(len(labels))),
            format_func=lambda i: labels[i],
        )
        stake_p = st.number_input(
            "Parlay stake ($)", min_value=1.0,
            value=float(min_bet), step=1.0, key="parlay_stake",
        )
        legs = [pool[i] for i in chosen]
        if len(legs) >= 2:
            decimals = [american_to_decimal(l["price"]) for l in legs]
            combined_dec = prod(decimals)
            combined_am = decimal_to_american(combined_dec)
            payout = stake_p * combined_dec
            profit = payout - stake_p
            implied = 1.0 / combined_dec
            avg_edge = sum(l["edge_bps"] for l in legs) / len(legs)

            cols = st.columns(5)
            cols[0].markdown(kpi("Legs", str(len(legs))), unsafe_allow_html=True)
            cols[1].markdown(
                kpi("Combined odds", format_american(combined_am)),
                unsafe_allow_html=True,
            )
            cols[2].markdown(
                kpi("Payout", f"${payout:,.2f}"), unsafe_allow_html=True,
            )
            cols[3].markdown(
                kpi("Profit", f"${profit:,.2f}", color=GREEN),
                unsafe_allow_html=True,
            )
            cols[4].markdown(
                kpi("Break-even win rate", f"{implied*100:,.1f}%"),
                unsafe_allow_html=True,
            )
            st.caption(
                f"Average leg edge: {format_bps(avg_edge)}. "
                "Note: parlays multiply book edge against you, so the real "
                "edge is usually less than the average shown."
            )

            if st.button("Log this parlay", type="primary"):
                desc = " + ".join(
                    f"{l['matchup'][:18]} {l['pick']}" for l in legs
                )
                bet = {
                    "id": str(time.time()),
                    "date": datetime.now(timezone.utc).date().isoformat(),
                    "description": f"Parlay: {desc}",
                    "book": ", ".join({l["book"] for l in legs}),
                    "odds": combined_am,
                    "stake": stake_p,
                    "to_win": profit,
                    "status": "open",
                    "kind": "parlay",
                    "legs": "; ".join(
                        f"{l['matchup']} | {l['market']} | {l['pick']} | "
                        f"{format_american(l['price'])} @ {l['book']}"
                        for l in legs
                    ),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                db_insert_bet(bet)
                st.success("Parlay logged. See the Bankroll tab.")
                st.rerun()
        elif chosen:
            st.info("Select at least 2 legs to build a parlay.")

with tab_board:
    league_id = st.selectbox("League", [lg["id"] for lg in LEAGUES], index=0)
    events, warn = get_board(league_id, books_filter)
    if warn:
        st.warning(warn)
    if not events:
        st.info("No events on the board.")
    for ev in events:
        with st.container(border=True):
            title = (
                f"### {ev.away} @ {ev.home}  "
                f"<span class='muted' style='font-size:.8rem'>{ev.start}</span>"
            )
            st.markdown(title, unsafe_allow_html=True)
            for m in ev.markets:
                st.caption(m.type)
                rows_t = []
                for oc in m.outcomes:
                    label = _pick_label(oc, m.type)
                    if oc.best:
                        best = (
                            f"<b style='color:{GREEN}'>"
                            f"{format_american(oc.best.price_american)}</b> "
                            f"@ {oc.best.book}"
                        )
                    else:
                        best = "-"
                    rows_t.append({
                        "Outcome": label,
                        "Best": best,
                        "Books": len(oc.books),
                        "Edge": format_bps(oc.edge_bps),
                    })
                if not rows_t:
                    continue
                html = "<table style='width:100%; font-size:.92rem;'><tr>"
                for c in rows_t[0].keys():
                    html += f"<th align='left'>{c}</th>"
                html += "</tr>"
                for row in rows_t:
                    html += "<tr>"
                    for c in row.keys():
                        html += f"<td>{row[c]}</td>"
                    html += "</tr>"
                html += "</table>"
                st.markdown(html, unsafe_allow_html=True)

with tab_bank:
    bets = db_load_bets()

    today = datetime.now(timezone.utc).date().isoformat()
    today_open = [
        b for b in bets if b["status"] == "open" and b["date"] == today
    ]
    today_exposure = sum(b["stake"] for b in today_open)

    settled = [b for b in bets if b["status"] != "open"]
    pnl = sum(
        b["to_win"] if b["status"] == "won" else -b["stake"]
        for b in settled
    )
    equity = bankroll + pnl
    pnl_color = GREEN if pnl >= 0 else RED

    c = st.columns(5)
    c[0].markdown(
        kpi("Starting bankroll", f"${bankroll:,.2f}"), unsafe_allow_html=True,
    )
    c[1].markdown(
        kpi("Current equity", f"${equity:,.2f}"), unsafe_allow_html=True,
    )
    c[2].markdown(
        kpi("Settled P&L", f"${pnl:,.2f}", color=pnl_color),
        unsafe_allow_html=True,
    )
    c[3].markdown(
        kpi("Today exposure", f"${today_exposure:,.2f}"),
        unsafe_allow_html=True,
    )
    remaining = max(daily_cap - today_exposure, 0)
    c[4].markdown(
        kpi("Remaining today", f"${remaining:,.2f}"), unsafe_allow_html=True,
    )
    st.markdown("&nbsp;", unsafe_allow_html=True)

    if settled:
        sorted_settled = sorted(
            settled,
            key=lambda b: b.get("settled_at") or b.get("created_at") or "",
        )
        running = bankroll
        points = [{"Time": "Start", "Equity": bankroll, "Idx": 0}]
        for i, b in enumerate(sorted_settled, start=1):
            delta = b["to_win"] if b["status"] == "won" else -b["stake"]
            running += delta
            ts = b.get("settled_at") or b.get("created_at") or ""
            points.append({"Time": ts, "Equity": running, "Idx": i})
        eq_df = pd.DataFrame(points)
        line_color = GREEN if running >= bankroll else RED
        eq_chart = (
            alt.Chart(eq_df)
            .mark_line(point=True, strokeWidth=3, color=line_color)
            .encode(
                x=alt.X("Idx:Q", title="Settled bet #",
                        axis=alt.Axis(labelColor="#94A3B8", titleColor="#E2E8F0")),
                y=alt.Y("Equity:Q", title="Equity ($)",
                        scale=alt.Scale(zero=False),
                        axis=alt.Axis(labelColor="#94A3B8", titleColor="#E2E8F0",
                                      format="$,.0f")),
                tooltip=["Idx", "Time", alt.Tooltip("Equity:Q", format="$,.2f")],
            )
            .properties(height=260, background=PANEL, title=alt.TitleParams(
                "Bankroll equity curve", color="#F8FAFC", anchor="start",
            ))
        )
        st.altair_chart(eq_chart, use_container_width=True)
    else:
        st.caption("Settle some bets to see your equity curve.")

    st.subheader("Log a single bet")
    with st.form("log_bet", clear_on_submit=True):
        f = st.columns([2, 2, 1, 1, 1])
        desc = f[0].text_input("Description", placeholder="e.g. Lakers ML")
        book = f[1].text_input("Book", placeholder="draftkings / fanduel / bet365")
        odds = f[2].number_input("American odds", value=-110, step=5)
        stake = f[3].number_input(
            "Stake ($)", min_value=0.0, value=min_bet, step=1.0,
        )
        submit = f[4].form_submit_button("Add bet", type="primary")
        if submit and desc:
            bet = {
                "id": str(time.time()),
                "date": today,
                "description": desc,
                "book": book,
                "odds": int(odds),
                "stake": float(stake),
                "to_win": float(stake) * (american_to_decimal(int(odds)) - 1.0),
                "status": "open",
                "kind": "single",
                "legs": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            db_insert_bet(bet)
            st.rerun()

    st.subheader("Active bets")
    open_bets = [b for b in bets if b["status"] == "open"]
    if not open_bets:
        st.caption("No open bets.")
    for b in open_bets:
        cols = st.columns([3, 2, 1, 1, 1, 1, 1, 1])
        cols[0].write(f"**{b['description']}**")
        cols[1].write(b["book"])
        cols[2].write(format_american(b["odds"]))
        cols[3].write(f"${b['stake']:,.2f}")
        cols[4].write(f"+${b['to_win']:,.2f}")
        if cols[5].button("Win", key=f"w{b['id']}"):
            db_settle_bet(b["id"], "won")
            st.rerun()
        if cols[6].button("Loss", key=f"l{b['id']}"):
            db_settle_bet(b["id"], "lost")
            st.rerun()
        if cols[7].button("Del", key=f"d{b['id']}"):
            db_delete_bet(b["id"])
            st.rerun()

    if settled:
        st.subheader("Recent settled bets")
        for b in sorted(
            settled,
            key=lambda x: x.get("settled_at") or "",
            reverse=True,
        )[:15]:
            mark = "W" if b["status"] == "won" else "L"
            color = GREEN if b["status"] == "won" else RED
            delta = b["to_win"] if b["status"] == "won" else -b["stake"]
            st.markdown(
                f"<div class='pick-card'><b style='color:{color}'>{mark}</b> "
                f"&nbsp; {b['description']} "
                f"<span class='muted'>({format_american(b['odds'])} @ "
                f"{b['book']}, ${b['stake']:,.2f})</span> "
                f"<span style='float:right; color:{color}; font-weight:700'>"
                f"${delta:+,.2f}</span></div>",
                unsafe_allow_html=True,
            )
