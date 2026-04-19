"""Edge - Sports Betting Dashboard (Streamlit)"""
from __future__ import annotations

import os
import smtplib
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
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
BOOK_COLOR = {
    "draftkings": "#53D337",
    "fanduel":    "#1493FF",
    "bet365":     "#F2C100",
}
BOOK_LABEL = {
    "draftkings": "DK",
    "fanduel":    "FD",
    "bet365":     "B365",
}

# PrizePicks Power Play payout multipliers (entry x mult on full hit)
PP_PAYOUTS = {2: 3, 3: 5, 4: 10, 5: 20, 6: 25}

TEAM_PALETTE = [
    "#9E1B32", "#1493FF", "#F59E0B", "#22C55E", "#7B43F4",
    "#EC4899", "#06B6D4", "#F97316", "#84CC16", "#A855F7",
    "#EF4444", "#14B8A6", "#EAB308", "#3B82F6", "#D946EF",
]


def team_initials(name):
    if not name:
        return "?"
    words = [w for w in name.replace("-", " ").split() if w]
    if not words:
        return name[:2].upper()
    if len(words) == 1:
        return words[0][:3].upper()
    return "".join(w[0] for w in words[:3]).upper()


def team_color(name):
    if not name:
        return CRIMSON
    return TEAM_PALETTE[sum(ord(c) for c in name) % len(TEAM_PALETTE)]


def team_badge(name):
    initials = team_initials(name)
    color = team_color(name)
    return (
        f"<span class='team-badge' style='background:{color}'>"
        f"{initials}</span>"
    )


def book_badge(book):
    key = (book or "").lower()
    color = BOOK_COLOR.get(key, MUTED)
    label = BOOK_LABEL.get(key, (book or "?")[:4].upper())
    return (
        f"<span class='book-badge' style='background:{color}'>{label}</span>"
    )


def matchup_badges(matchup):
    if " @ " not in matchup:
        return matchup
    away, home = matchup.split(" @ ", 1)
    return (
        f"{team_badge(away)} <span class='muted'>{away}</span> "
        f"<span class='muted'>@</span> "
        f"{team_badge(home)} <span style='color:#F1F5F9'>{home}</span>"
    )

SGO_BASE = "https://api.sportsgameodds.com/v2"
DB_PATH = os.environ.get("EDGE_DB_PATH", "edge_bets.db")

CRIMSON = "#9E1B32"
BG = "#0B1220"
PANEL = "#121A2B"
GREEN = "#22C55E"
AMBER = "#F59E0B"
RED = "#EF4444"
MUTED = "#94A3B8"


try:
    import psycopg2
    import psycopg2.extras  # noqa: F401
    HAS_PG = True
except ImportError:
    HAS_PG = False


def _pg_url():
    val = os.environ.get("DATABASE_URL")
    if val:
        return val
    try:
        return st.secrets.get("DATABASE_URL")
    except Exception:
        return None


def _use_pg():
    return HAS_PG and bool(_pg_url())


def storage_label():
    if _use_pg():
        return "Postgres (Supabase)"
    if not HAS_PG and _pg_url():
        return "SQLite (psycopg2 missing)"
    return "SQLite (ephemeral)"


def db_conn():
    if _use_pg():
        return psycopg2.connect(_pg_url())
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _q(sql):
    return sql.replace("?", "%s") if _use_pg() else sql


def db_init():
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(
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
    cur.execute(
        """CREATE TABLE IF NOT EXISTS odds_history (
            pick_key TEXT,
            ts TEXT,
            best_dec REAL,
            best_american INTEGER
        )"""
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_odds_key_ts "
        "ON odds_history(pick_key, ts)"
    )
    conn.commit()
    conn.close()


@st.cache_resource(show_spinner=False)
def _ensure_schema():
    db_init()
    return True


def db_load_bets():
    _ensure_schema()
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM bets ORDER BY created_at ASC")
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return rows


def db_insert_bet(bet):
    _ensure_schema()
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(
        _q("""INSERT INTO bets
        (id, date, description, book, odds, stake, to_win, status, kind, legs,
         created_at, settled_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"""),
        (
            bet["id"], bet["date"], bet["description"], bet["book"],
            int(bet["odds"]), float(bet["stake"]), float(bet["to_win"]),
            bet["status"], bet.get("kind", "single"), bet.get("legs"),
            bet["created_at"], bet.get("settled_at"),
        ),
    )
    conn.commit()
    conn.close()


def db_settle_bet(bet_id, status):
    _ensure_schema()
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(
        _q("UPDATE bets SET status=?, settled_at=? WHERE id=?"),
        (status, datetime.now(timezone.utc).isoformat(), bet_id),
    )
    conn.commit()
    conn.close()


def db_delete_bet(bet_id):
    _ensure_schema()
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(_q("DELETE FROM bets WHERE id=?"), (bet_id,))
    conn.commit()
    conn.close()


def pick_key_team(r):
    return f"team|{r['league']}|{r['matchup']}|{r['market']}|{r['pick']}"


def pick_key_prop(r):
    return (
        f"prop|{r['league']}|{r['matchup']}|{r['player']}|"
        f"{r['stat']}|{r['line']:g}|{r['side']}"
    )


def db_snapshot(rows, kind):
    if not rows:
        return
    _ensure_schema()
    ts = datetime.now(timezone.utc).isoformat()
    data = []
    for r in rows:
        key = pick_key_team(r) if kind == "team" else pick_key_prop(r)
        try:
            data.append((key, ts, float(r["best_dec"]), int(round(r["price"]))))
        except (TypeError, ValueError):
            continue
    if not data:
        return
    conn = db_conn()
    cur = conn.cursor()
    cur.executemany(
        _q("INSERT INTO odds_history(pick_key, ts, best_dec, best_american) "
           "VALUES (?,?,?,?)"),
        data,
    )
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    cur.execute(_q("DELETE FROM odds_history WHERE ts < ?"), (cutoff,))
    conn.commit()
    conn.close()


def db_history(key, limit=30):
    _ensure_schema()
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(
        _q("SELECT best_dec FROM odds_history WHERE pick_key=? "
           "ORDER BY ts DESC LIMIT ?"),
        (key, limit),
    )
    vals = [r[0] for r in cur.fetchall()]
    conn.close()
    return list(reversed(vals))


def svg_sparkline(values, w=120, h=28):
    if len(values) < 2:
        return ""
    vmin, vmax = min(values), max(values)
    span = (vmax - vmin) or 1.0
    pts = []
    for i, v in enumerate(values):
        x = (i / (len(values) - 1)) * w
        y = h - ((v - vmin) / span) * (h - 4) - 2
        pts.append(f"{x:.1f},{y:.1f}")
    color = GREEN if values[-1] >= values[0] else RED
    return (
        f"<svg width='{w}' height='{h}' "
        "style='vertical-align:middle; margin-left:6px;'>"
        f"<polyline fill='none' stroke='{color}' stroke-width='1.8' "
        f"points='{' '.join(pts)}'/></svg>"
    )


def get_secret(name):
    val = os.environ.get(name)
    if val:
        return val
    try:
        return st.secrets.get(name)
    except Exception:
        return None


def send_recap_email():
    """Send today's recap via SMTP. Returns (ok: bool, msg: str)."""
    smtp_host = get_secret("SMTP_HOST")
    smtp_user = get_secret("SMTP_USER")
    smtp_pass = get_secret("SMTP_PASSWORD")
    smtp_to = get_secret("SMTP_TO") or smtp_user
    try:
        smtp_port = int(get_secret("SMTP_PORT") or 587)
    except (TypeError, ValueError):
        smtp_port = 587

    if not (smtp_host and smtp_user and smtp_pass):
        return False, "SMTP not configured. Add SMTP_* secrets in Streamlit Cloud."

    bets = db_load_bets()
    today = datetime.now(timezone.utc).date().isoformat()
    placed_today = [b for b in bets if (b.get("created_at") or "").startswith(today)]
    settled_today = [
        b for b in bets
        if b["status"] != "open"
        and (b.get("settled_at") or "").startswith(today)
    ]
    wins = sum(1 for b in settled_today if b["status"] == "won")
    losses = sum(1 for b in settled_today if b["status"] == "lost")
    pnl = sum(
        b["to_win"] if b["status"] == "won" else -b["stake"]
        for b in settled_today
    )
    open_count = sum(1 for b in bets if b["status"] == "open")
    all_settled = [b for b in bets if b["status"] != "open"]
    total_pnl = sum(
        b["to_win"] if b["status"] == "won" else -b["stake"]
        for b in all_settled
    )

    lines = [
        f"EDGE Daily Recap - {today}",
        "",
        f"Bets placed today: {len(placed_today)}",
        f"Settled today: {wins}-{losses} ({wins + losses} total)",
        f"Today's P&L: ${pnl:+,.2f}",
        f"Open bets carrying over: {open_count}",
        f"All-time settled P&L: ${total_pnl:+,.2f}",
        "",
        "Today's settled bets:",
    ]
    for b in settled_today[-15:]:
        mark = "W" if b["status"] == "won" else "L"
        delta = b["to_win"] if b["status"] == "won" else -b["stake"]
        lines.append(
            f"  [{mark}] {b['description']} ({b['book']}, "
            f"{b['odds']:+d}, ${b['stake']:,.2f}) {delta:+,.2f}"
        )
    if not settled_today:
        lines.append("  (none yet)")

    msg = EmailMessage()
    msg["Subject"] = f"EDGE Recap {today} - P&L ${pnl:+,.2f}"
    msg["From"] = smtp_user
    msg["To"] = smtp_to
    msg.set_content("\n".join(lines))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as srv:
            srv.starttls()
            srv.login(smtp_user, smtp_pass)
            srv.send_message(msg)
        return True, f"Recap sent to {smtp_to}"
    except Exception as e:
        return False, f"Send failed: {e}"


def prop_trend_chip(key):
    hist = db_history(key, limit=5)
    if len(hist) < 2:
        return ""
    delta = (hist[-1] - hist[0]) * 100  # cents of decimal odds
    n = len(hist)
    if delta >= 1:
        return (
            f"<span class='trend-chip trend-up'>"
            f"&#8599; +{delta:.0f}c / {n} reads</span>"
        )
    if delta <= -1:
        return (
            f"<span class='trend-chip trend-down'>"
            f"&#8600; {delta:.0f}c / {n} reads</span>"
        )
    return f"<span class='trend-chip trend-flat'>flat / {n} reads</span>"


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


def tier_label(edge_bps, books_count):
    if edge_bps <= 0 or books_count < 2:
        return "Pass", RED
    if edge_bps >= 150 and books_count >= 5:
        return "High confidence", GREEN
    if edge_bps >= 75 and books_count >= 4:
        return "Medium confidence", AMBER
    if edge_bps >= 25 and books_count >= 3:
        return "Low confidence", "#D97706"
    if edge_bps >= 10:
        return "Speculative", MUTED
    return "Pass", RED


def recommend_stake_tier(edge_bps, books_count, min_bet, max_bet):
    tier, color = tier_label(edge_bps, books_count)
    if tier == "Pass":
        return 0.0, tier, color
    if tier == "High confidence":
        return max_bet, tier, color
    if tier == "Medium confidence":
        return round(min_bet + (max_bet - min_bet) * 0.6, 2), tier, color
    if tier == "Low confidence":
        return round(min_bet + (max_bet - min_bet) * 0.25, 2), tier, color
    return min_bet, tier, color


def kelly_stake(edge_bps, books_count, best_dec, avg_dec, bankroll,
                min_bet, max_bet, kelly_mult):
    tier, color = tier_label(edge_bps, books_count)
    if tier == "Pass" or avg_dec <= 1.0 or best_dec <= 1.0:
        return 0.0, "Pass", RED
    p = 1.0 / avg_dec
    b = best_dec - 1.0
    q = 1.0 - p
    f = (p * b - q) / b
    if f <= 0:
        return 0.0, "Pass", RED
    raw = bankroll * f * kelly_mult
    stake = max(min_bet, min(max_bet, raw))
    if stake < min_bet:
        return 0.0, "Pass", RED
    return round(stake, 2), tier, color


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


@st.cache_data(ttl=7200, show_spinner=False)
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
        names.get("long") or names.get("short")
        or names.get("medium") or side.title()
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
                book=book_id, price_american=am_f,
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
            prop_buckets.setdefault(
                (player_name, stat_id or "stat", point, side), []
            ).extend(prices)
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


def all_picks(books_filter, kind, leagues_filter=None):
    rows = []
    leagues_iter = [
        lg for lg in LEAGUES
        if leagues_filter is None or lg["id"] in leagues_filter
    ]
    for lg in leagues_iter:
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
                            "best_dec": oc.best.price_decimal,
                            "avg_dec": oc.avg_decimal,
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
                        "best_dec": oc.best.price_decimal,
                        "avg_dec": oc.avg_decimal,
                        "books_count": len(oc.books),
                        "edge_bps": oc.edge_bps,
                        "start": ev.start,
                    })
    rows.sort(key=lambda r: r["edge_bps"], reverse=True)
    return rows


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

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
    padding: 18px 22px; border-radius: 14px; margin-bottom: 12px;
    background: linear-gradient(135deg, __CRIMSON__ 0%, #4A0C18 100%);
    box-shadow: 0 10px 30px rgba(158,27,50,.25);
}
.edge-header h1 { margin:0; font-size: 1.6rem; }
.edge-header .tag { color: rgba(255,255,255,.85); font-size:.85rem; }
.alert-banner {
    background: linear-gradient(135deg, rgba(245,158,11,.18) 0%, rgba(158,27,50,.18) 100%);
    border: 1px solid rgba(245,158,11,.5);
    border-radius: 12px; padding: 12px 16px; margin-bottom: 12px;
    color: #FDE68A; font-weight: 600;
}
.alert-banner .pill {
    background: __AMBER__; color:#0B1220;
    padding:2px 10px; border-radius:999px; font-size:.78rem;
    margin-right:6px;
}
.ticker-wrap {
    background: linear-gradient(90deg,#0F172A 0%,__PANEL__ 50%,#0F172A 100%);
    border-radius: 10px;
    border: 1px solid rgba(158,27,50,.35);
    overflow: hidden; margin-bottom: 14px; padding: 10px 0;
    position: relative;
    box-shadow: 0 0 24px rgba(158,27,50,.15) inset;
}
.ticker-wrap::before, .ticker-wrap::after {
    content: ""; position: absolute; top: 0; bottom: 0; width: 80px; z-index: 2;
    pointer-events: none;
}
.ticker-wrap::before { left: 0; background: linear-gradient(90deg,#0F172A,transparent); }
.ticker-wrap::after  { right: 0; background: linear-gradient(-90deg,#0F172A,transparent); }
.live-tag {
    position:absolute; left:10px; top:50%; transform:translateY(-50%);
    background:__CRIMSON__; color:#FFF; font-weight:800; font-size:.72rem;
    padding:3px 9px; border-radius:4px; letter-spacing:.08em; z-index:3;
    display:flex; align-items:center; gap:6px;
}
.live-tag .dot {
    width:6px; height:6px; border-radius:50%; background:#FFF;
    animation: live-pulse 1.2s ease-in-out infinite;
}
@keyframes live-pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.4;transform:scale(.7)} }
.ticker {
    display: inline-block; white-space: nowrap; padding-left: 100%;
    animation: ticker-scroll 45s linear infinite;
    font-variant-numeric: tabular-nums;
}
.ticker:hover { animation-play-state: paused; }
.ticker .item { display:inline-block; padding: 0 28px; color:#E2E8F0; font-weight:600; }
.ticker .edge { color: __GREEN__; margin-left:8px; font-weight:800; }
.ticker .sep  { color: __MUTED__; margin: 0 6px; }
@keyframes ticker-scroll {
    from { transform: translateX(0); }
    to   { transform: translateX(-100%); }
}
.spotlight {
    position: relative;
    background: linear-gradient(135deg, var(--spot-c1) 0%, var(--spot-c2) 60%, #0B1220 100%);
    border-radius: 18px; padding: 22px 26px; margin-bottom: 18px;
    border: 1px solid rgba(255,255,255,.10);
    overflow: hidden;
    box-shadow: 0 16px 50px rgba(0,0,0,.45),
                0 0 60px var(--spot-glow) inset;
}
.spotlight::before {
    content:""; position:absolute; inset:0;
    background: radial-gradient(circle at 80% 20%, var(--spot-glow) 0%, transparent 55%);
    pointer-events:none; opacity:.55;
}
.spotlight .label {
    display:inline-block; background:rgba(0,0,0,.45); color:#FDE68A;
    padding:4px 12px; border-radius:999px; font-size:.72rem;
    font-weight:800; letter-spacing:.12em; text-transform:uppercase;
    margin-bottom:10px; backdrop-filter: blur(4px);
}
.spotlight .matchup { color:#F8FAFC; font-size:1.4rem; font-weight:800; margin-bottom:6px; }
.spotlight .pick { color:#FDE68A; font-size:1.85rem; font-weight:900; margin:6px 0 4px; line-height:1.1; }
.spotlight .meta { color:#E2E8F0; font-size:.95rem; opacity:.9; }
.spotlight .conf-ring {
    position:relative; width:120px; height:120px;
}
.spotlight .conf-ring svg { transform: rotate(-90deg); }
.spotlight .conf-ring .ring-bg { stroke: rgba(255,255,255,.12); }
.spotlight .conf-ring .ring-fg { stroke: __GREEN__; transition: stroke-dashoffset 1s ease; }
.spotlight .conf-ring .conf-text {
    position:absolute; inset:0; display:flex; flex-direction:column;
    align-items:center; justify-content:center;
}
.spotlight .conf-text .pct { color:#F8FAFC; font-size:1.5rem; font-weight:800; }
.spotlight .conf-text .lbl { color:#94A3B8; font-size:.7rem; text-transform:uppercase; letter-spacing:.08em; }
.trend-chip {
    display:inline-block; padding:2px 8px; border-radius:6px;
    font-size:.72rem; font-weight:700; margin-left:6px;
    font-variant-numeric: tabular-nums;
}
.trend-up   { background:rgba(34,197,94,.18); color:__GREEN__; border:1px solid rgba(34,197,94,.4); }
.trend-down { background:rgba(239,68,68,.18); color:__RED__; border:1px solid rgba(239,68,68,.4); }
.trend-flat { background:rgba(148,163,184,.18); color:__MUTED__; border:1px solid rgba(148,163,184,.3); }
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
.team-badge {
    display:inline-block; min-width: 34px; padding: 3px 8px;
    border-radius: 6px; font-weight: 800; font-size: .72rem;
    color: #0B1220; text-align: center; letter-spacing: .04em;
    margin-right: 4px; vertical-align: middle;
}
.book-badge {
    display:inline-block; min-width: 28px; padding: 2px 7px;
    border-radius: 5px; font-weight: 800; font-size: .7rem;
    color: #0B1220; text-align: center; margin: 0 2px;
    vertical-align: middle;
}
.refresh-bar {
    display:flex; align-items:center; gap:10px; margin-bottom: 10px;
    color: __MUTED__; font-size: .85rem;
}
.cache-chip {
    background: __PANEL__; border: 1px solid rgba(255,255,255,.08);
    border-radius: 999px; padding: 4px 12px; color:#E2E8F0;
    font-variant-numeric: tabular-nums;
}
.cache-chip.stale { color: __AMBER__; border-color: rgba(245,158,11,.5); }
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
       .replace("__GREEN__", GREEN)
       .replace("__AMBER__", AMBER)
       .replace("__RED__", RED)
)
st.markdown(CSS, unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### Bankroll")
    bankroll = st.number_input("Bankroll ($)", min_value=10.0, value=500.0, step=10.0)
    min_bet = st.number_input("Min bet ($)", min_value=1.0, value=1.0, step=1.0)
    max_bet = st.number_input(
        "Max bet ($)", min_value=min_bet, value=max(10.0, min_bet), step=1.0,
    )
    daily_cap_pct = st.slider("Daily exposure cap (% of bankroll)", 5, 100, 20)

    st.markdown("---")
    st.markdown("### Sizing model")
    sizing_mode = st.radio(
        "Mode", ["Tier ($1-$10)", "Fractional Kelly"], index=0,
    )
    kelly_mult = 0.25
    if sizing_mode == "Fractional Kelly":
        kelly_mult = st.slider(
            "Kelly fraction", 0.05, 1.0, 0.25, 0.05,
            help="0.25 = quarter Kelly. Lower = safer.",
        )
        st.caption(
            "Uses consensus probability across books as the 'true' "
            "probability. Bet capped at min/max."
        )
    else:
        st.caption("Tiers: $1 speculative -> $10 high-confidence. Pass when no edge.")

    st.markdown("---")
    st.markdown("### Alerts")
    alert_threshold = st.number_input(
        "Flag picks above (bps)", min_value=0, value=200, step=25,
        help="Picks with edge above this threshold get a banner at the top.",
    )

    st.markdown("---")
    st.markdown("### Filters")
    book_choice = st.multiselect(
        "Books to compare",
        ["draftkings", "fanduel", "bet365"],
        default=["draftkings", "fanduel", "bet365"],
    )
    st.caption("Active leagues")
    league_toggle = {}
    lg_cols = st.columns(2)
    for i, lg in enumerate(LEAGUES):
        with lg_cols[i % 2]:
            league_toggle[lg["id"]] = st.checkbox(
                lg["id"], value=True, key=f"lg_{lg['id']}",
            )

    st.markdown("---")
    st.caption(f"Storage: {storage_label()}")

books_filter = set(book_choice) if book_choice else TARGET_BOOKS
leagues_filter = {k for k, v in league_toggle.items() if v}
if not leagues_filter:
    leagues_filter = {lg["id"] for lg in LEAGUES}
daily_cap = bankroll * daily_cap_pct / 100.0


def size_pick(r):
    if sizing_mode == "Fractional Kelly":
        return kelly_stake(
            r["edge_bps"], r["books_count"], r["best_dec"], r["avg_dec"],
            bankroll, min_bet, max_bet, kelly_mult,
        )
    return recommend_stake_tier(
        r["edge_bps"], r["books_count"], min_bet, max_bet,
    )


if "last_refresh" not in st.session_state:
    st.session_state["last_refresh"] = datetime.now(timezone.utc)

last_refresh = st.session_state["last_refresh"]
age_min = (datetime.now(timezone.utc) - last_refresh).total_seconds() / 60.0
age_label = f"{age_min:.0f} min" if age_min >= 1 else "just now"
chip_cls = "cache-chip stale" if age_min >= 120 else "cache-chip"
last_str = last_refresh.astimezone().strftime("%I:%M %p")

header_html = (
    "<div class='edge-header'>"
    "<div>"
    "<h1>EDGE - Sports Betting Terminal</h1>"
    "<div class='tag'>Risk-tiered picks across DraftKings, FanDuel, Bet365 - "
    "PrizePicks player-prop candidates</div>"
    "</div>"
    f"<div class='tag'>Last refresh {last_str}</div>"
    "</div>"
)
st.markdown(header_html, unsafe_allow_html=True)

rb_left, rb_right = st.columns([5, 1])
with rb_left:
    st.markdown(
        "<div class='refresh-bar'>"
        f"<span class='{chip_cls}'>Data {age_label} old</span>"
        "<span class='muted'>Cache holds odds for 2 hours - "
        "click Refresh to pull fresh data from SportsGameOdds.</span>"
        "</div>",
        unsafe_allow_html=True,
    )
with rb_right:
    if st.button("Refresh now", use_container_width=True, type="primary"):
        fetch_events.clear()
        st.session_state["last_refresh"] = datetime.now(timezone.utc)
        st.rerun()

all_team_picks = all_picks(books_filter, kind="team", leagues_filter=leagues_filter)
all_prop_picks = all_picks(books_filter, kind="player", leagues_filter=leagues_filter)
db_snapshot(all_team_picks, "team")
db_snapshot(all_prop_picks, "player")

# Alerts banner
alerted = [
    r for r in all_team_picks
    if alert_threshold > 0 and r["edge_bps"] >= alert_threshold
][:6]
if alerted:
    chips = ""
    for r in alerted:
        chips += (
            f"<span class='pill'>{format_bps(r['edge_bps'])}</span>"
            f"{r['matchup']} - <b>{r['pick']}</b> "
            f"({format_american(r['price'])} on {r['book']})"
            "<br/>"
        )
    banner = (
        "<div class='alert-banner'>"
        f"&#9888; {len(alerted)} pick(s) above {alert_threshold} bps<br/>"
        f"{chips}"
        "</div>"
    )
    st.markdown(banner, unsafe_allow_html=True)

# Live ticker
top_for_ticker = [r for r in all_team_picks if r["edge_bps"] > 0][:8]
if top_for_ticker:
    items = ""
    for r in top_for_ticker:
        items += (
            "<span class='item'>"
            f"{r['league']} <span class='sep'>|</span> "
            f"{r['matchup']} <span class='sep'>|</span> "
            f"{r['pick']} {format_american(r['price'])} ({r['book']})"
            f"<span class='edge'>{format_bps(r['edge_bps'])}</span>"
            "</span>"
        )
    ticker_html = (
        "<div class='ticker-wrap'>"
        "<div class='live-tag'><span class='dot'></span>LIVE</div>"
        f"<div class='ticker'>{items}{items}</div>"
        "</div>"
    )
    st.markdown(ticker_html, unsafe_allow_html=True)

# Sportsbook quick-launch
links_html = "<div class='book-bar'>"
for b in SPORTSBOOK_LINKS:
    links_html += (
        f"<a class='book-link' style='background:{b['color']}' "
        f"href='{b['url']}' target='_blank' rel='noopener'>"
        f"Open {b['name']}</a>"
    )
links_html += "</div>"
st.markdown(links_html, unsafe_allow_html=True)

tab_picks, tab_props, tab_pp_board, tab_parlay, tab_board, tab_bank = st.tabs(
    ["Suggested Picks", "PrizePicks Picks", "PrizePicks Board",
     "Parlay Builder", "Odds Board", "Bankroll"]
)

with tab_picks:
    st.subheader("Today's Suggested Bets")

    spotlight_pool = []
    for r in all_team_picks:
        spotlight_pool.append({
            "kind": "team", "edge": r["edge_bps"], "matchup": r["matchup"],
            "league": r["league"], "pick": r["pick"], "book": r["book"],
            "price": r["price"], "books_count": r["books_count"], "row": r,
        })
    for r in all_prop_picks:
        spotlight_pool.append({
            "kind": "prop", "edge": r["edge_bps"], "matchup": r["matchup"],
            "league": r["league"],
            "pick": f"{r['player']} {r['side']} {r['line']:g} {r['stat']}",
            "book": r["book"], "price": r["price"],
            "books_count": r["books_count"], "row": r,
        })
    spotlight_pool.sort(key=lambda x: x["edge"], reverse=True)
    if spotlight_pool and spotlight_pool[0]["edge"] > 0:
        sp = spotlight_pool[0]
        away = sp["matchup"].split(" @ ")[0] if " @ " in sp["matchup"] else sp["matchup"]
        home = sp["matchup"].split(" @ ")[-1]
        c1 = team_color(away)
        c2 = team_color(home)
        glow = c1 + "55"  # alpha
        try:
            stake_v, tier_v, color_v = size_pick(sp["row"])
        except Exception:
            stake_v, tier_v, color_v = 0.0, "Pass", MUTED
        # Confidence: scale edge to 0-100% (250bps = 100%)
        conf = max(0.0, min(1.0, sp["edge"] / 250.0))
        circ = 2 * 3.14159 * 50
        dash_off = circ * (1.0 - conf)
        ring_color = GREEN if conf > 0.6 else (AMBER if conf > 0.3 else RED)
        kind_label = "PLAYER PROP" if sp["kind"] == "prop" else "TEAM PICK"
        spotlight_html = (
            f"<div class='spotlight' style='--spot-c1:{c1}; --spot-c2:{c2}; "
            f"--spot-glow:{glow};'>"
            "<div style='display:flex; justify-content:space-between; "
            "align-items:center; gap:24px; position:relative; z-index:1;'>"
            "<div>"
            f"<div class='label'>&#11088; PICK OF THE DAY &middot; {kind_label}</div>"
            f"<div class='matchup'>{matchup_badges(sp['matchup'])} "
            f"<span class='muted' style='font-size:.85rem; margin-left:8px;'>"
            f"{sp['league']}</span></div>"
            f"<div class='pick'>{sp['pick']}</div>"
            f"<div class='meta'>{format_american(sp['price'])} on "
            f"{book_badge(sp['book'])} &middot; "
            f"{sp['books_count']} books &middot; "
            f"<b style='color:{GREEN};'>{format_bps(sp['edge'])} edge</b> "
            f"&middot; suggested stake "
            f"<b style='color:{color_v};'>${stake_v:,.2f}</b> "
            f"<span class='muted'>({tier_v})</span></div>"
            "</div>"
            "<div class='conf-ring'>"
            "<svg width='120' height='120' viewBox='0 0 120 120'>"
            "<circle class='ring-bg' cx='60' cy='60' r='50' "
            "fill='none' stroke-width='10'/>"
            f"<circle class='ring-fg' cx='60' cy='60' r='50' fill='none' "
            f"stroke-width='10' stroke-linecap='round' stroke='{ring_color}' "
            f"stroke-dasharray='{circ:.1f}' "
            f"stroke-dashoffset='{dash_off:.1f}'/>"
            "</svg>"
            "<div class='conf-text'>"
            f"<div class='pct'>{int(conf * 100)}%</div>"
            "<div class='lbl'>confidence</div>"
            "</div>"
            "</div>"
            "</div>"
            "</div>"
        )
        st.markdown(spotlight_html, unsafe_allow_html=True)

    rows = all_team_picks

    if rows:
        sized = [(r, *size_pick(r)) for r in rows]
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
        # Confidence donut
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
            .mark_arc(innerRadius=50, outerRadius=95, stroke=BG, strokeWidth=2)
            .encode(
                theta=alt.Theta("Count:Q"),
                color=alt.Color(
                    "Tier:N",
                    scale=alt.Scale(
                        domain=order,
                        range=[GREEN, AMBER, "#D97706", MUTED, RED],
                    ),
                    legend=alt.Legend(
                        title="Confidence",
                        labelColor="#E2E8F0", titleColor="#F8FAFC",
                    ),
                ),
                tooltip=["Tier", "Count"],
            )
            .properties(
                height=240, background=PANEL,
                title=alt.TitleParams(
                    "Confidence breakdown", color="#F8FAFC", anchor="start",
                ),
            )
        )

        # Edge histogram
        edge_df = pd.DataFrame([{"Edge_bps": r["edge_bps"]} for r in rows])
        hist = (
            alt.Chart(edge_df)
            .mark_bar(color=CRIMSON, stroke=BG, strokeWidth=1)
            .encode(
                x=alt.X(
                    "Edge_bps:Q", bin=alt.Bin(maxbins=24),
                    title="Edge (bps)",
                    axis=alt.Axis(labelColor="#94A3B8", titleColor="#E2E8F0"),
                ),
                y=alt.Y(
                    "count():Q", title="Picks",
                    axis=alt.Axis(labelColor="#94A3B8", titleColor="#E2E8F0"),
                ),
                tooltip=[alt.Tooltip("count():Q", title="Picks")],
            )
            .properties(
                height=240, background=PANEL,
                title=alt.TitleParams(
                    "Edge distribution", color="#F8FAFC", anchor="start",
                ),
            )
        )

        # Sportsbook scorecard
        book_counts = {}
        for r in rows:
            if r["edge_bps"] > 0:
                b = r["book"].lower()
                book_counts[b] = book_counts.get(b, 0) + 1
        if book_counts:
            sb_df = pd.DataFrame([
                {"Book": b, "Best price wins": c}
                for b, c in book_counts.items()
            ]).sort_values("Best price wins", ascending=False)
            books_order = sb_df["Book"].tolist()
            color_range = [BOOK_COLOR.get(b, CRIMSON) for b in books_order]
            sb_chart = (
                alt.Chart(sb_df)
                .mark_bar(stroke=BG, strokeWidth=1, cornerRadiusEnd=4)
                .encode(
                    x=alt.X(
                        "Book:N", sort=books_order, title=None,
                        axis=alt.Axis(
                            labelColor="#E2E8F0", labelAngle=0,
                            titleColor="#F8FAFC",
                        ),
                    ),
                    y=alt.Y(
                        "Best price wins:Q", title="Times best",
                        axis=alt.Axis(
                            labelColor="#94A3B8", titleColor="#E2E8F0",
                        ),
                    ),
                    color=alt.Color(
                        "Book:N",
                        scale=alt.Scale(domain=books_order, range=color_range),
                        legend=None,
                    ),
                    tooltip=["Book", "Best price wins"],
                )
                .properties(
                    height=240, background=PANEL,
                    title=alt.TitleParams(
                        "Sportsbook scorecard",
                        color="#F8FAFC", anchor="start",
                    ),
                )
            )
        else:
            sb_chart = None

        ch1, ch2, ch3 = st.columns(3)
        ch1.altair_chart(donut, use_container_width=True)
        ch2.altair_chart(hist, use_container_width=True)
        if sb_chart is not None:
            ch3.altair_chart(sb_chart, use_container_width=True)
        else:
            ch3.info("No book wins yet.")

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
            spark = svg_sparkline(db_history(pick_key_team(r)))
            spark_html = (
                f"<span class='pick-sub' style='margin-right:6px;'>line</span>{spark}"
                if spark else ""
            )
            card = (
                "<div class='pick-card'><div class='pick-row'>"
                "<div>"
                f"<div class='pick-title'>{matchup_badges(r['matchup'])} "
                f"<span class='muted' style='font-size:.85rem;'>"
                f"&nbsp;&nbsp;{r['league']} - {r['market']}</span></div>"
                f"<div class='pick-sub' style='margin-top:4px;'>Pick: "
                f"<b style='color:#F8FAFC'>{r['pick']}</b> "
                f"@ {format_american(r['price'])} on {book_badge(r['book'])} - "
                f"{r['books_count']} books compared</div>"
                f"<div style='margin-top:6px;'>{spark_html}</div>"
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
    search_q = st.text_input(
        "Search player", placeholder="e.g. LeBron, Mahomes, Judge...",
        key="prop_search",
    ).strip().lower()

    prop_rows = all_prop_picks
    if search_q:
        prop_rows = [
            r for r in prop_rows
            if r.get("player") and search_q in r["player"].lower()
        ]
        st.caption(f"{len(prop_rows)} match(es) for '{search_q}'.")

    if not prop_rows:
        if search_q:
            st.info("No matching players in the current feed.")
        else:
            st.info("No player props are coming through the feed right now.")
    else:
        for r in prop_rows[:25]:
            stake, tier, color = size_pick(r)
            stake_txt = f"${stake:,.2f}" if stake > 0 else "Pass"
            prop_key = pick_key_prop(r)
            spark = svg_sparkline(db_history(prop_key))
            spark_html = (
                f"<span class='pick-sub' style='margin-right:6px;'>line</span>{spark}"
                if spark else ""
            )
            trend_html = prop_trend_chip(prop_key)
            card = (
                "<div class='pick-card'><div class='pick-row'>"
                "<div>"
                f"<div class='pick-title'>{r['player']} - "
                f"<span class='muted'>{r['stat']} {r['side']} {r['line']:g}</span>"
                f"{trend_html}</div>"
                f"<div class='pick-sub' style='margin-top:4px;'>"
                f"{matchup_badges(r['matchup'])}"
                f"<span style='margin:0 8px;' class='muted'>{r['league']}</span>"
                f"best @ {format_american(r['price'])} on {book_badge(r['book'])} - "
                f"{r['books_count']} books</div>"
                f"<div style='margin-top:6px;'>{spark_html}</div>"
                "</div>"
                "<div style='text-align:right;'>"
                f"<span class='pill' style='background:{color}'>{tier}</span>"
                f"<div style='font-size:1.2rem; font-weight:800; color:{color}; "
                f"margin-top:6px;'>{stake_txt}</div>"
                f"<div class='pick-sub'>{format_bps(r['edge_bps'])} edge</div>"
                "</div></div></div>"
            )
            st.markdown(card, unsafe_allow_html=True)

with tab_pp_board:
    st.subheader("PrizePicks Board Builder")
    st.caption(
        "PrizePicks 'Power Play' boards: pick 2-6 props that all must hit. "
        "Payout = entry x multiplier (2:3x, 3:5x, 4:10x, 5:20x, 6:25x). "
        "Hit probability uses consensus probability across books per leg."
    )
    if not all_prop_picks:
        st.info("No player props available right now.")
    else:
        pp_pool = all_prop_picks[:60]
        pp_labels = [
            f"[{format_bps(r['edge_bps'])}] {r['player']} {r['side']} "
            f"{r['line']:g} {r['stat']} ({r['matchup']}, {r['league']}) "
            f"@ {format_american(r['price'])} on {r['book']}"
            for r in pp_pool
        ]
        chosen = st.multiselect(
            "Pick 2-6 props (sorted by edge)",
            options=list(range(len(pp_labels))),
            format_func=lambda i: pp_labels[i],
            max_selections=6,
            key="pp_board_picks",
        )
        entry = st.number_input(
            "Entry ($)", min_value=1.0, value=5.0, step=1.0, key="pp_entry",
        )

        if 2 <= len(chosen) <= 6:
            legs = [pp_pool[i] for i in chosen]
            probs = [
                1.0 / l["avg_dec"] if l["avg_dec"] > 0 else 0.0 for l in legs
            ]
            hit_prob = prod(probs) if all(p > 0 for p in probs) else 0.0
            mult = PP_PAYOUTS[len(chosen)]
            payout = entry * mult
            ev = hit_prob * payout - entry
            ev_color = GREEN if ev > 0 else RED
            be_prob = 1.0 / mult

            cols = st.columns(5)
            cols[0].markdown(kpi("Legs", str(len(legs))), unsafe_allow_html=True)
            cols[1].markdown(
                kpi("Multiplier", f"{mult}x"), unsafe_allow_html=True,
            )
            cols[2].markdown(
                kpi("Hit prob", f"{hit_prob*100:,.1f}%"),
                unsafe_allow_html=True,
            )
            cols[3].markdown(
                kpi("Break-even", f"{be_prob*100:,.1f}%"),
                unsafe_allow_html=True,
            )
            cols[4].markdown(
                kpi("Expected value", f"${ev:+,.2f}", color=ev_color),
                unsafe_allow_html=True,
            )

            if ev > 0:
                st.success(
                    f"Positive EV board: hit probability ({hit_prob*100:.1f}%) "
                    f"beats break-even ({be_prob*100:.1f}%). "
                    f"Potential payout ${payout:,.2f} for ${entry:,.2f} entry."
                )
            else:
                edge_needed = (be_prob - hit_prob) * 100
                st.warning(
                    f"Negative EV: you need {edge_needed:.1f}% more hit "
                    f"probability to break even. Drop the weakest leg or "
                    f"swap it for higher-edge picks."
                )

            st.markdown("**Legs in this board:**")
            for l, p in zip(legs, probs):
                st.markdown(
                    "<div class='pick-card' style='padding:10px 14px;'>"
                    f"<b>{l['player']}</b> "
                    f"<span class='muted'>{l['side']} {l['line']:g} "
                    f"{l['stat']}</span> &mdash; "
                    f"{matchup_badges(l['matchup'])} "
                    f"<span class='muted'>{l['league']}</span> &mdash; "
                    f"hit {p*100:.1f}% &mdash; "
                    f"{format_bps(l['edge_bps'])} edge"
                    "</div>",
                    unsafe_allow_html=True,
                )

            if st.button("Log this board as a parlay", key="pp_log"):
                desc = " + ".join(
                    f"{l['player']} {l['side']} {l['line']:g}" for l in legs
                )
                bet = {
                    "id": str(time.time()),
                    "date": datetime.now(timezone.utc).date().isoformat(),
                    "description": f"PrizePicks {len(legs)}-leg: {desc}",
                    "book": "prizepicks",
                    "odds": decimal_to_american(float(mult)),
                    "stake": float(entry),
                    "to_win": float(payout - entry),
                    "status": "open",
                    "kind": "prizepicks",
                    "legs": "; ".join(
                        f"{l['player']} {l['side']} {l['line']:g} "
                        f"{l['stat']} ({l['matchup']})"
                        for l in legs
                    ),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                db_insert_bet(bet)
                st.success("Board logged. See the Bankroll tab.")
                st.rerun()
        elif chosen:
            st.info("Pick at least 2 props.")

with tab_parlay:
    st.subheader("Parlay Builder")
    st.caption(
        "Combine 2+ picks into a parlay. Combined odds, payout, and the "
        "implied break-even win rate are calculated from the best line per leg."
    )
    pool = all_team_picks
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
                f"Average leg edge: {format_bps(avg_edge)}. Note: parlays "
                "multiply book edge against you, so the real edge is usually "
                "less than the average shown."
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
                        "Outcome": label, "Best": best,
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

    fx = st.session_state.pop("fx", None)
    if fx == "win":
        st.balloons()
        st.markdown(
            "<div style='background:rgba(34,197,94,.18);border:1px solid "
            f"{GREEN};color:{GREEN};padding:10px 14px;border-radius:10px;"
            "font-weight:700;animation:winflash .9s ease-out forwards;'>"
            "WIN booked - bankroll updated</div>"
            "<style>@keyframes winflash{0%{transform:scale(.97);opacity:.4}"
            "100%{transform:scale(1);opacity:1}}</style>",
            unsafe_allow_html=True,
        )
    elif fx == "loss":
        st.markdown(
            "<div id='lossfx' style='position:fixed;top:0;left:0;right:0;"
            "bottom:0;background:rgba(239,68,68,.35);z-index:9998;"
            "pointer-events:none;animation:lossflash .8s ease-out forwards;'>"
            "</div>"
            f"<div style='background:rgba(239,68,68,.18);border:1px solid "
            f"{RED};color:{RED};padding:10px 14px;border-radius:10px;"
            "font-weight:700;'>LOSS recorded - keep your discipline</div>"
            "<style>@keyframes lossflash{0%{opacity:1}100%{opacity:0;"
            "visibility:hidden}}</style>",
            unsafe_allow_html=True,
        )

    prev_eq = st.session_state.get("prev_equity", equity)
    st.session_state["prev_equity"] = equity

    c = st.columns(5)
    c[0].markdown(kpi("Starting bankroll", f"${bankroll:,.2f}"), unsafe_allow_html=True)
    with c[1]:
        st.components.v1.html(
            f"""
            <style>
              body {{margin:0;padding:0;background:transparent;
                     font-family:-apple-system,Segoe UI,Roboto,sans-serif;}}
              .kpi {{background:{PANEL};padding:14px 16px;border-radius:12px;
                     border:1px solid rgba(255,255,255,.06);}}
              .label {{color:{MUTED};font-size:.75rem;text-transform:uppercase;
                       letter-spacing:.05em;margin-bottom:6px;}}
              .value {{color:#F8FAFC;font-size:1.5rem;font-weight:700;
                       font-variant-numeric:tabular-nums;}}
            </style>
            <div class='kpi'>
              <div class='label'>Current equity</div>
              <div class='value' id='eq'>${prev_eq:,.2f}</div>
            </div>
            <script>
              (function(){{
                var el=document.getElementById('eq');
                var s={prev_eq},e={equity},dur=900,t0=performance.now();
                function f(t){{
                  var p=Math.min((t-t0)/dur,1);
                  var k=1-Math.pow(1-p,3);
                  var v=s+(e-s)*k;
                  el.textContent='$'+v.toLocaleString('en-US',
                    {{minimumFractionDigits:2,maximumFractionDigits:2}});
                  if(p<1)requestAnimationFrame(f);
                }}
                requestAnimationFrame(f);
              }})();
            </script>
            """,
            height=92,
        )
    c[2].markdown(
        kpi("Settled P&L", f"${pnl:,.2f}", color=pnl_color),
        unsafe_allow_html=True,
    )
    c[3].markdown(
        kpi("Today exposure", f"${today_exposure:,.2f}"), unsafe_allow_html=True,
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
                x=alt.X(
                    "Idx:Q", title="Settled bet #",
                    axis=alt.Axis(labelColor="#94A3B8", titleColor="#E2E8F0"),
                ),
                y=alt.Y(
                    "Equity:Q", title="Equity ($)",
                    scale=alt.Scale(zero=False),
                    axis=alt.Axis(
                        labelColor="#94A3B8", titleColor="#E2E8F0", format="$,.0f",
                    ),
                ),
                tooltip=["Idx", "Time", alt.Tooltip("Equity:Q", format="$,.2f")],
            )
            .properties(
                height=260, background=PANEL,
                title=alt.TitleParams(
                    "Bankroll equity curve", color="#F8FAFC", anchor="start",
                ),
            )
        )
        st.altair_chart(eq_chart, use_container_width=True)
    else:
        st.caption("Settle some bets to see your equity curve.")

    # Daily P&L heat-map (last 12 weeks, GitHub-style)
    daily_pnl = {}
    for b in settled:
        ts = b.get("settled_at") or b.get("created_at") or ""
        day = ts[:10]
        if not day:
            continue
        delta = b["to_win"] if b["status"] == "won" else -b["stake"]
        daily_pnl[day] = daily_pnl.get(day, 0.0) + delta

    today_d = datetime.now(timezone.utc).date()
    weeks_back = 12
    total_days = weeks_back * 7
    grid = []
    for i in range(total_days - 1, -1, -1):
        d = today_d - timedelta(days=i)
        weeks_ago = (today_d - d).days // 7
        grid.append({
            "date": d.isoformat(),
            "weekday": d.strftime("%a"),
            "weekday_num": d.weekday(),
            "weeks_ago": weeks_ago,
            "pnl": daily_pnl.get(d.isoformat(), 0.0),
        })
    heat_df = pd.DataFrame(grid)
    abs_max = max(20.0, heat_df["pnl"].abs().max())
    weekday_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    heat = (
        alt.Chart(heat_df)
        .mark_rect(stroke=BG, strokeWidth=3, cornerRadius=3)
        .encode(
            x=alt.X(
                "weeks_ago:O", sort="descending", title=None,
                axis=alt.Axis(labels=False, ticks=False),
            ),
            y=alt.Y(
                "weekday:O", sort=weekday_order, title=None,
                axis=alt.Axis(
                    labelColor="#94A3B8", ticks=False,
                    domain=False, labelFontSize=10,
                ),
            ),
            color=alt.Color(
                "pnl:Q",
                scale=alt.Scale(
                    domain=[-abs_max, 0, abs_max],
                    range=[RED, "#1F2937", GREEN],
                ),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("date:N", title="Date"),
                alt.Tooltip("pnl:Q", title="P&L", format="$,.2f"),
            ],
        )
        .properties(
            height=170, background=PANEL,
            title=alt.TitleParams(
                f"Daily P&L heat-map (last {weeks_back} weeks)",
                color="#F8FAFC", anchor="start",
            ),
        )
    )
    st.altair_chart(heat, use_container_width=True)

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

    st.subheader("Daily Recap Email")
    smtp_ok = bool(
        get_secret("SMTP_HOST")
        and get_secret("SMTP_USER")
        and get_secret("SMTP_PASSWORD")
    )
    em_l, em_r = st.columns([3, 1])
    with em_l:
        if smtp_ok:
            recipient = get_secret("SMTP_TO") or get_secret("SMTP_USER")
            st.caption(
                f"SMTP configured - recap will go to **{recipient}**"
            )
        else:
            st.caption(
                "SMTP not configured. Add the secrets below in Streamlit Cloud "
                "(Manage app -> Settings -> Secrets), reboot, then come back."
            )
            with st.expander("Setup instructions (Gmail example)"):
                st.markdown(
                    "1. Turn on 2-Step Verification on your Google account.\n"
                    "2. Visit **myaccount.google.com/apppasswords** -> "
                    "create an app password called 'EDGE'.\n"
                    "3. In Streamlit Cloud Secrets, add:\n"
                    "```\n"
                    "SMTP_HOST = \"smtp.gmail.com\"\n"
                    "SMTP_PORT = \"587\"\n"
                    "SMTP_USER = \"you@gmail.com\"\n"
                    "SMTP_PASSWORD = \"xxxx xxxx xxxx xxxx\"\n"
                    "SMTP_TO = \"you@gmail.com\"\n"
                    "```\n"
                    "4. Save, reboot the app, click **Send recap now**.\n\n"
                    "Other providers: Outlook uses `smtp.office365.com`, "
                    "Yahoo `smtp.mail.yahoo.com`, port 587 + STARTTLS for all."
                )
    with em_r:
        if st.button(
            "Send recap now", use_container_width=True,
            disabled=not smtp_ok, type="primary",
        ):
            with st.spinner("Sending..."):
                ok, msg = send_recap_email()
            (st.success if ok else st.error)(msg)
    st.markdown("&nbsp;", unsafe_allow_html=True)

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
            st.session_state["fx"] = "win"
            st.rerun()
        if cols[6].button("Loss", key=f"l{b['id']}"):
            db_settle_bet(b["id"], "lost")
            st.session_state["fx"] = "loss"
            st.rerun()
        if cols[7].button("Del", key=f"d{b['id']}"):
            db_delete_bet(b["id"])
            st.rerun()

    if settled:
        st.subheader("Recent settled bets")
        for b in sorted(
            settled, key=lambda x: x.get("settled_at") or "", reverse=True,
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
