"""Edge - Sports Betting Dashboard (Streamlit)"""
from __future__ import annotations

import os
import smtplib
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from math import prod

import altair as alt
import hashlib
import json
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
HALO = "#15203a"
THEMES = {
    "Bloomberg":         {"bg": "#0B1220", "panel": "#121A2B", "accent": "#9E1B32", "halo": "#15203a"},
    "Alabama Crimson Tide": {"bg": "#160305", "panel": "#26090E", "accent": "#9E1B32", "halo": "#4A0D18"},
    "Tennessee Volunteers": {"bg": "#180C00", "panel": "#27160A", "accent": "#FF8200", "halo": "#4A2300"},
    "Vegas Gold":        {"bg": "#1A0420", "panel": "#2A0F30", "accent": "#FFD700", "halo": "#3E1450"},
    "Matrix":            {"bg": "#000000", "panel": "#0A1A0A", "accent": "#00FF41", "halo": "#0F2A14"},
    "Miami Sunset":      {"bg": "#0E1B3A", "panel": "#1A2C4A", "accent": "#FF2E93", "halo": "#1F3A6E"},
}
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
    cur.execute(
        """CREATE TABLE IF NOT EXISTS kv (
            k TEXT PRIMARY KEY,
            v TEXT
        )"""
    )
    conn.commit()
    conn.close()


def db_get_kv(key, default=None):
    _ensure_schema()
    scoped = f"{_current_user()}::{key}"
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(_q("SELECT v FROM kv WHERE k=?"), (scoped,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return default
    return row[0]


def db_set_kv(key, value):
    _ensure_schema()
    scoped = f"{_current_user()}::{key}"
    conn = db_conn()
    cur = conn.cursor()
    if _use_pg():
        cur.execute(
            _q(
                "INSERT INTO kv (k,v) VALUES (?,?) "
                "ON CONFLICT (k) DO UPDATE SET v=EXCLUDED.v"
            ),
            (scoped, str(value)),
        )
    else:
        cur.execute(
            "INSERT OR REPLACE INTO kv (k,v) VALUES (?,?)",
            (scoped, str(value)),
        )
    conn.commit()
    conn.close()


def _current_user():
    return st.session_state.get("edge_user", "default")


def _user_pin_hash(pin):
    return hashlib.sha1(("edge:" + str(pin)).encode()).hexdigest()[:12]


@st.cache_resource(show_spinner=False)
def _ensure_schema():
    db_init()
    conn = db_conn()
    cur = conn.cursor()
    if _use_pg():
        try:
            cur.execute(
                'ALTER TABLE bets ADD COLUMN IF NOT EXISTS usr TEXT DEFAULT \'default\''
            )
        except Exception:
            pass
    else:
        try:
            cur.execute(
                "ALTER TABLE bets ADD COLUMN usr TEXT DEFAULT 'default'"
            )
        except Exception:
            pass
    conn.commit()
    conn.close()
    return True


def db_load_bets():
    _ensure_schema()
    usr = _current_user()
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(
        _q("SELECT * FROM bets WHERE usr=? ORDER BY created_at ASC"),
        (usr,),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return rows


def db_insert_bet(bet):
    _ensure_schema()
    usr = _current_user()
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(
        _q("""INSERT INTO bets
        (id, date, description, book, odds, stake, to_win, status, kind, legs,
         created_at, settled_at, usr)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"""),
        (
            bet["id"], bet["date"], bet["description"], bet["book"],
            int(bet["odds"]), float(bet["stake"]), float(bet["to_win"]),
            bet["status"], bet.get("kind", "single"), bet.get("legs"),
            bet["created_at"], bet.get("settled_at"), usr,
        ),
    )
    conn.commit()
    conn.close()


def db_settle_bet(bet_id, status):
    _ensure_schema()
    usr = _current_user()
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(
        _q("UPDATE bets SET status=?, settled_at=? WHERE id=? AND usr=?"),
        (status, datetime.now(timezone.utc).isoformat(), bet_id, usr),
    )
    conn.commit()
    conn.close()


def db_delete_bet(bet_id):
    _ensure_schema()
    usr = _current_user()
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(_q("DELETE FROM bets WHERE id=? AND usr=?"), (bet_id, usr))
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
    usr = _current_user()
    data = []
    for r in rows:
        key = pick_key_team(r) if kind == "team" else pick_key_prop(r)
        scoped = f"{usr}::{key}"
        try:
            data.append((scoped, ts, float(r["best_dec"]), int(round(r["price"]))))
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
    scoped = f"{_current_user()}::{key}"
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(
        _q("SELECT best_dec FROM odds_history WHERE pick_key=? "
           "ORDER BY ts DESC LIMIT ?"),
        (scoped, limit),
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


def player_avatar(player_name, team_hint=""):
    name = (player_name or "?").strip()
    parts = [p for p in name.split() if p]
    if not parts:
        initials = "?"
    elif len(parts) == 1:
        initials = parts[0][:2].upper()
    else:
        initials = (parts[0][0] + parts[-1][0]).upper()
    color = team_color(team_hint or name)
    return (
        f"<span class='player-av' style='background:linear-gradient(135deg,"
        f"{color} 0%, #0B1220 140%);'>{initials}</span>"
    )


def bankroll_thermometer(equity, start_bankroll, goal):
    goal = max(goal, start_bankroll + 1)
    pct = max(0.0, min(1.0, (equity - start_bankroll) / (goal - start_bankroll)))
    pct_label = f"{pct * 100:.0f}%"
    fill_color = GREEN if equity >= start_bankroll else RED
    return (
        "<div class='thermo-wrap'>"
        f"<div class='thermo-row'><span class='thermo-lbl'>Goal progress</span>"
        f"<span class='thermo-pct'>{pct_label}</span></div>"
        "<div class='thermo-track'>"
        f"<div class='thermo-fill' style='width:{pct * 100:.1f}%; "
        f"background:linear-gradient(90deg,{fill_color},#FDE68A);'></div>"
        "</div>"
        f"<div class='thermo-row'><span class='thermo-end'>"
        f"${start_bankroll:,.0f}</span>"
        f"<span class='thermo-now'>${equity:,.2f}</span>"
        f"<span class='thermo-end'>${goal:,.0f}</span></div>"
        "</div>"
    )


_ESPN_LEAGUE_MAP = {
    "NBA": ("basketball", "nba"),
    "NFL": ("football", "nfl"),
    "MLB": ("baseball", "mlb"),
    "NHL": ("hockey", "nhl"),
    "NCAAF": ("football", "college-football"),
    "NCAAB": ("basketball", "mens-college-basketball"),
}


@st.cache_data(ttl=900, show_spinner=False)
def fetch_injuries(league_id):
    mapping = _ESPN_LEAGUE_MAP.get(league_id)
    if not mapping:
        return {}
    sport, lg = mapping
    url = (
        f"https://site.web.api.espn.com/apis/site/v2/sports/"
        f"{sport}/{lg}/injuries"
    )
    out = {}
    try:
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            return {}
        data = resp.json() or {}
        for team_block in data.get("injuries", []):
            tname = (team_block.get("team") or {}).get("displayName", "")
            if not tname:
                continue
            items = []
            for inj in team_block.get("injuries", []):
                ath = inj.get("athlete") or {}
                pname = ath.get("displayName", "?")
                pos = (ath.get("position") or {}).get("abbreviation", "")
                status = inj.get("status", "?")
                detail = (inj.get("type") or {}).get(
                    "description"
                ) or inj.get("shortComment") or ""
                items.append({
                    "player": pname, "pos": pos,
                    "status": status, "detail": detail[:90],
                })
            if items:
                out[tname.lower()] = items
    except Exception:
        return {}
    return out


def _injury_status_color(status):
    s = (status or "").lower()
    if "out" in s or "ir" in s or "suspend" in s:
        return RED
    if "doubt" in s:
        return "#F59E0B"
    if "question" in s or "day" in s:
        return "#EAB308"
    return MUTED


def render_injuries_for_game(league_id, away, home):
    inj = fetch_injuries(league_id)
    if not inj:
        return ""
    rows = []
    for team in (away, home):
        key = (team or "").lower()
        match_key = next(
            (k for k in inj if key and (key in k or k in key)), None,
        )
        if not match_key:
            continue
        for item in inj[match_key][:6]:
            color = _injury_status_color(item["status"])
            rows.append(
                f"<div class='inj-row'>"
                f"<span class='inj-team'>{team}</span>"
                f"<span class='inj-player'>{item['player']}</span>"
                f"<span class='muted'>{item['pos']}</span>"
                f"<span class='inj-status' style='background:{color}'>"
                f"{item['status']}</span>"
                f"<span class='muted inj-detail'>{item['detail']}</span>"
                f"</div>"
            )
    if not rows:
        return ""
    return (
        "<div class='inj-wrap'>"
        "<div class='inj-head'>INJURY REPORT</div>"
        + "".join(rows) +
        "</div>"
    )


def weekly_report_card(bets, start_bankroll):
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    week = []
    for b in bets:
        if b["status"] == "open":
            continue
        try:
            ts = datetime.fromisoformat(
                (b.get("created_at") or "").replace("Z", "+00:00")
            )
        except Exception:
            continue
        if ts >= cutoff:
            week.append(b)
    if not week:
        return (
            "<div class='report-card'><div class='report-head'>"
            "WEEKLY REPORT CARD</div>"
            "<div class='muted' style='padding:14px;'>"
            "No settled bets in the last 7 days.</div></div>"
        )
    wins = sum(1 for b in week if b["status"] == "won")
    losses = sum(1 for b in week if b["status"] == "lost")
    pushes = sum(1 for b in week if b["status"] == "push")
    total = wins + losses
    hit = (wins / total * 100) if total else 0.0
    pnl = sum(
        b["to_win"] if b["status"] == "won"
        else (-b["stake"] if b["status"] == "lost" else 0.0)
        for b in week
    )
    staked = sum(b["stake"] for b in week)
    roi = (pnl / staked * 100) if staked else 0.0
    by_day = {}
    for b in week:
        d = b.get("date") or b.get("created_at", "")[:10]
        by_day[d] = by_day.get(d, 0.0) + (
            b["to_win"] if b["status"] == "won"
            else (-b["stake"] if b["status"] == "lost" else 0.0)
        )
    best_day = max(by_day.items(), key=lambda x: x[1]) if by_day else (None, 0)
    worst_day = min(by_day.items(), key=lambda x: x[1]) if by_day else (None, 0)
    by_lg = {}
    for b in week:
        lg = b.get("league") or "?"
        d = by_lg.setdefault(lg, {"w": 0, "l": 0, "p": 0.0})
        if b["status"] == "won":
            d["w"] += 1
            d["p"] += b["to_win"]
        elif b["status"] == "lost":
            d["l"] += 1
            d["p"] -= b["stake"]
    lg_rows = "".join(
        f"<tr><td>{lg}</td><td>{d['w']}-{d['l']}</td>"
        f"<td style='color:{GREEN if d['p'] >= 0 else RED}'>"
        f"${d['p']:+.2f}</td></tr>"
        for lg, d in sorted(by_lg.items(), key=lambda x: -x[1]["p"])
    )
    pnl_color = GREEN if pnl >= 0 else RED
    grade = (
        "A" if roi >= 10 else "B" if roi >= 3 else "C" if roi >= -3
        else "D" if roi >= -10 else "F"
    )
    grade_color = {
        "A": GREEN, "B": "#84CC16", "C": "#EAB308",
        "D": "#F59E0B", "F": RED,
    }[grade]
    best_html = (
        f"<div><span class='muted'>Best day</span><br>"
        f"<b>{best_day[0] or '-'}</b> "
        f"<span style='color:{GREEN}'>${best_day[1]:+.2f}</span></div>"
    )
    worst_html = (
        f"<div><span class='muted'>Worst day</span><br>"
        f"<b>{worst_day[0] or '-'}</b> "
        f"<span style='color:{RED}'>${worst_day[1]:+.2f}</span></div>"
    )
    return (
        "<div class='report-card'>"
        "<div class='report-head'>WEEKLY REPORT CARD <span class='muted'"
        " style='font-weight:400;font-size:.7rem;'>last 7 days</span></div>"
        "<div class='report-grid'>"
        f"<div class='report-grade' style='color:{grade_color};"
        f"border-color:{grade_color};'>{grade}</div>"
        f"<div><span class='muted'>P&amp;L</span><br>"
        f"<b style='color:{pnl_color}; font-size:1.3rem;'>"
        f"${pnl:+,.2f}</b></div>"
        f"<div><span class='muted'>ROI</span><br>"
        f"<b style='font-size:1.2rem; color:{pnl_color};'>{roi:+.1f}%</b></div>"
        f"<div><span class='muted'>Record</span><br>"
        f"<b>{wins}-{losses}{('-' + str(pushes)) if pushes else ''}</b><br>"
        f"<span class='muted'>{hit:.0f}% hit</span></div>"
        f"{best_html}{worst_html}"
        "</div>"
        + (
            "<table class='report-tbl'><tr><th>League</th><th>Record</th>"
            "<th>P&amp;L</th></tr>" + lg_rows + "</table>"
            if lg_rows else ""
        ) +
        "</div>"
    )


def tick_class_for(key, current_dec):
    last = st.session_state.get("last_dec", {})
    prev = last.get(key)
    cls = ""
    if prev is not None:
        if current_dec > prev + 0.005:
            cls = "tick-up"
        elif current_dec < prev - 0.005:
            cls = "tick-down"
    last[key] = current_dec
    st.session_state["last_dec"] = last
    return cls


def play_sound(kind):
    if not st.session_state.get("sfx_on"):
        return
    if kind == "win":
        notes = "[523.25, 659.25, 783.99]"
    elif kind == "loss":
        notes = "[440, 349.23, 261.63]"
    elif kind == "ath":
        notes = "[523.25, 659.25, 783.99, 1046.5]"
    else:
        return
    js = f"""
<script>
(function(){{
  try {{
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const notes = {notes};
    const now = ctx.currentTime;
    notes.forEach((f, i) => {{
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.type = 'sine'; o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, now + i*0.14);
      g.gain.exponentialRampToValueAtTime(0.18, now + i*0.14 + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, now + i*0.14 + 0.30);
      o.connect(g); g.connect(ctx.destination);
      o.start(now + i*0.14); o.stop(now + i*0.14 + 0.32);
    }});
  }} catch(e) {{}}
}})();
</script>
"""
    st.markdown(js, unsafe_allow_html=True)


def monte_carlo_forecast(bets, start_equity, current_equity,
                         days_ahead=60, sims=600):
    settled = [b for b in bets if b["status"] in ("won", "lost")]
    if len(settled) < 5:
        return None
    pnls = [
        b["to_win"] if b["status"] == "won" else -b["stake"]
        for b in settled
    ]
    mean_pnl = sum(pnls) / len(pnls)
    var = sum((p - mean_pnl) ** 2 for p in pnls) / max(1, len(pnls) - 1)
    sd = var ** 0.5
    if not settled:
        bets_per_day = 2.0
    else:
        try:
            first = datetime.fromisoformat(
                (settled[0].get("created_at") or "").replace("Z", "+00:00")
            )
            last = datetime.fromisoformat(
                (settled[-1].get("created_at") or "").replace("Z", "+00:00")
            )
            span_days = max(1.0, (last - first).total_seconds() / 86400)
        except Exception:
            span_days = max(1.0, len(settled) / 2.0)
        bets_per_day = max(0.5, min(20.0, len(settled) / span_days))
    import random
    paths = []
    for _ in range(sims):
        eq = current_equity
        path = [eq]
        for _d in range(days_ahead):
            n = max(1, int(round(random.gauss(bets_per_day, 1.0))))
            for _b in range(n):
                eq += random.gauss(mean_pnl, sd)
            path.append(eq)
        paths.append(path)
    days = list(range(days_ahead + 1))
    rows = []
    for d in days:
        col = sorted(p[d] for p in paths)
        p10 = col[int(len(col) * 0.10)]
        p50 = col[int(len(col) * 0.50)]
        p90 = col[int(len(col) * 0.90)]
        rows.append({
            "day": d, "p10": p10, "p50": p50, "p90": p90,
        })
    final = sorted(p[-1] for p in paths)
    return {
        "rows": rows,
        "p10": final[int(len(final) * 0.10)],
        "p50": final[int(len(final) * 0.50)],
        "p90": final[int(len(final) * 0.90)],
        "edge_per_bet": mean_pnl,
        "bets_per_day": bets_per_day,
        "sample_size": len(settled),
    }


def ai_chat(prompt, context_text):
    api_key = get_secret("OPENAI_API_KEY")
    if not api_key:
        return (
            "OpenAI key not configured. Add OPENAI_API_KEY to your "
            "Streamlit Cloud secrets to enable Ask Edge."
        )
    try:
        from openai import OpenAI
    except Exception:
        return (
            "openai package not installed. Add `openai>=1.40` to "
            "requirements.txt and reboot the app."
        )
    try:
        client = OpenAI(api_key=api_key)
        sys = (
            "You are EDGE, a sharp sports-betting analyst. The user "
            "operates on a $500 bankroll, $1-$10 stakes. Be concise, "
            "tactical, and reference the specific picks/numbers in the "
            "context when answering. Never recommend illegal activity. "
            "When suggesting bets, always include book, line, price, "
            "and stake suggestion. Output in tight markdown."
        )
        rsp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": sys},
                {"role": "user",
                 "content": f"CONTEXT:\n{context_text}\n\nQUESTION: {prompt}"},
            ],
            temperature=0.4,
            max_tokens=700,
        )
        return rsp.choices[0].message.content or "(empty response)"
    except Exception as e:
        return f"AI error: {e}"


@st.cache_data(ttl=60, show_spinner=False)
def fetch_live_scoreboard(league_id):
    mapping = _GRADE_LEAGUE_MAP.get(league_id)
    if not mapping:
        return []
    sport, lg = mapping
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/"
        f"{sport}/{lg}/scoreboard"
    )
    out = []
    try:
        r = requests.get(url, timeout=8)
        if r.status_code != 200:
            return []
        data = r.json() or {}
        for ev in data.get("events", []):
            comp = (ev.get("competitions") or [{}])[0]
            status = ((comp.get("status") or {}).get("type") or {})
            state = status.get("state", "")
            cps = comp.get("competitors") or []
            if len(cps) != 2:
                continue
            teams = []
            for c in cps:
                tname = ((c.get("team") or {}).get("displayName") or "")
                shortn = ((c.get("team") or {}).get("shortDisplayName") or "")
                abbr = ((c.get("team") or {}).get("abbreviation") or "")
                try:
                    score = int(float(c.get("score") or 0))
                except Exception:
                    score = 0
                teams.append({
                    "name": tname, "short": shortn, "abbr": abbr,
                    "score": score, "home": c.get("homeAway") == "home",
                })
            out.append({
                "state": state,
                "detail": status.get("shortDetail", ""),
                "teams": teams,
            })
    except Exception:
        return []
    return out


def war_room_banner(open_bets, league_filter):
    if not open_bets:
        return ""
    all_games = []
    for lg in league_filter:
        for g in fetch_live_scoreboard(lg):
            all_games.append(g)
    if not all_games:
        return ""
    matched = []
    for b in open_bets:
        d = (b.get("description") or "").lower()
        if not d:
            continue
        for g in all_games:
            hit = False
            for t in g["teams"]:
                names = [
                    t["name"].lower(), t["short"].lower(),
                    t["abbr"].lower(),
                ]
                names = [n for n in names if n and len(n) > 2]
                if any(n in d for n in names):
                    hit = True
                    break
            if hit:
                matched.append((b, g))
                break
    if not matched:
        return ""
    rows = []
    for b, g in matched[:6]:
        t1, t2 = g["teams"][0], g["teams"][1]
        if g["state"] == "in":
            live, live_color = "LIVE", RED
        elif g["state"] == "post":
            live, live_color = "FINAL", GREEN
        else:
            live, live_color = "PRE", MUTED
        score = (
            f"<b style='color:#F8FAFC'>{t1['abbr'] or t1['short']} "
            f"{t1['score']}</b> "
            f"<span style='color:{MUTED}'>vs</span> "
            f"<b style='color:#F8FAFC'>{t2['abbr'] or t2['short']} "
            f"{t2['score']}</b>"
        )
        bet_summary = (b.get("description") or "")[:50]
        rows.append(
            f"<div class='wr-row'>"
            f"<span class='wr-tag' style='background:{live_color}'>"
            f"{live}</span>"
            f"<span class='wr-score'>{score}</span>"
            f"<span class='wr-detail'>{g['detail']}</span>"
            f"<span class='wr-bet'>{bet_summary} "
            f"(${b['stake']:.0f} → ${b['to_win']:.0f})</span>"
            f"</div>"
        )
    return (
        "<div class='war-room'>"
        "<div class='wr-head'>"
        "<span class='wr-pulse'></span>WAR ROOM - YOUR OPEN BETS LIVE"
        "</div>"
        + "".join(rows) + "</div>"
    )


def compute_achievements(bets, equity, bankroll, ath):
    settled = [b for b in bets if b["status"] in ("won", "lost")]
    wins = [b for b in settled if b["status"] == "won"]
    profit = sum(
        b["to_win"] if b["status"] == "won" else -b["stake"]
        for b in settled
    )
    streak = 0
    for b in sorted(
        settled, key=lambda x: x.get("settled_at") or "", reverse=True,
    ):
        if b["status"] == "won":
            streak += 1
        else:
            break
    win_rate = (len(wins) / len(settled)) if settled else 0.0
    return [
        ("First Blood",   "1st settled bet",                len(settled) >= 1),
        ("Money Maker",   "+$100 lifetime profit",          profit >= 100),
        ("Big Money",     "+$500 lifetime profit",          profit >= 500),
        ("Whale",         "+$1,000 lifetime profit",        profit >= 1000),
        ("Hot Hand",      "3 wins in a row",                streak >= 3),
        ("On Fire",       "5 wins in a row",                streak >= 5),
        ("Sharp",         "60%+ win rate (20+ bets)",
         win_rate >= 0.6 and len(settled) >= 20),
        ("Grinder",       "50 bets logged",                 len(settled) >= 50),
        ("Centurion",     "100 bets logged",                len(settled) >= 100),
        ("ATH Club",      "Set a new all-time high",        ath > bankroll),
        ("Comeback Kid",  "Recovered from -10% drawdown",
         ath > equity * 1.1 and equity >= bankroll),
        ("Diversified",   "Bets across 3+ books",
         len({(b.get("book") or "").lower()
              for b in settled if b.get("book")}) >= 3),
    ]


def achievements_html(badges):
    chips = []
    earned_count = sum(1 for _, _, e in badges if e)
    for name, desc, earned in badges:
        if earned:
            style = (
                "background:linear-gradient(135deg,#FDE68A 0%,#F59E0B 100%);"
                "color:#1A1306;border:1px solid #92400E;"
                "box-shadow:0 0 14px rgba(245,158,11,.45);"
            )
            mark = "✓"
        else:
            style = (
                "background:rgba(255,255,255,.03);color:#64748B;"
                "border:1px dashed rgba(255,255,255,.1);"
            )
            mark = "○"
        chips.append(
            f"<div class='ach-chip' style='{style}'>"
            f"<div class='ach-name'><span class='ach-mark'>{mark}</span> "
            f"{name}</div>"
            f"<div class='ach-desc'>{desc}</div></div>"
        )
    return (
        "<div class='ach-wrap'>"
        f"<div class='edge-trophy-head'>"
        f"<span class='sparkle'>&#10022;</span>"
        f"TROPHY CASE - {earned_count}/{len(badges)}"
        f"<span class='sparkle'>&#10022;</span>"
        f"</div>"
        f"<div class='ach-grid edge-trophy-case'>{''.join(chips)}</div>"
        "</div>"
    )


def card_style_for_pick(matchup):
    if " @ " in (matchup or ""):
        away, home = matchup.split(" @ ", 1)
        c1, c2 = team_color(away), team_color(home)
    else:
        c1 = team_color(matchup or "default")
        c2 = c1
    return (
        f"border-left:5px solid {c1}; "
        f"background:linear-gradient(135deg,{c1}26 0%,#0F172A 65%,{c2}1F 100%);"
    )


def queue_prefill_bet(desc, book, odds, stake):
    st.session_state["prefill"] = {
        "desc": desc, "book": book,
        "odds": int(odds), "stake": float(stake or 0.0),
    }
    st.toast(f"Queued: {desc[:60]} - open Bankroll to confirm.", icon="🔒")


_GRADE_LEAGUE_MAP = {
    "NBA": ("basketball", "nba"),
    "NFL": ("football", "nfl"),
    "MLB": ("baseball", "mlb"),
    "NHL": ("hockey", "nhl"),
    "NCAAF": ("football", "college-football"),
    "NCAAB": ("basketball", "mens-college-basketball"),
}


@st.cache_data(ttl=300, show_spinner=False)
def fetch_finals(league_id, date_iso):
    mapping = _GRADE_LEAGUE_MAP.get(league_id)
    if not mapping:
        return []
    sport, lg = mapping
    yyyymmdd = date_iso.replace("-", "")
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/"
        f"{sport}/{lg}/scoreboard?dates={yyyymmdd}"
    )
    out = []
    try:
        r = requests.get(url, timeout=8)
        if r.status_code != 200:
            return []
        data = r.json() or {}
        for ev in data.get("events", []):
            comp = (ev.get("competitions") or [{}])[0]
            status = ((comp.get("status") or {}).get("type") or {})
            state = status.get("state", "")
            if state != "post":
                continue
            cps = comp.get("competitors") or []
            if len(cps) != 2:
                continue
            game = {"teams": {}, "total": 0.0}
            for c in cps:
                tname = ((c.get("team") or {}).get("displayName") or "").lower()
                shortn = ((c.get("team") or {}).get("shortDisplayName")
                          or "").lower()
                abbr = ((c.get("team") or {}).get("abbreviation")
                        or "").lower()
                try:
                    score = float(c.get("score") or 0)
                except Exception:
                    score = 0.0
                game["teams"][tname] = {
                    "score": score, "won": c.get("winner", False),
                    "short": shortn, "abbr": abbr,
                }
                game["total"] += score
            out.append(game)
    except Exception:
        return []
    return out


def _grade_one(desc, finals):
    d = (desc or "").lower()
    if not d or not finals:
        return None
    total_match = re.search(r"\b(over|under)\s+(\d+(?:\.\d+)?)", d)
    if total_match:
        side = total_match.group(1)
        line = float(total_match.group(2))
        for g in finals:
            for tname in g["teams"]:
                if tname and tname.split()[-1] in d:
                    if side == "over":
                        return "won" if g["total"] > line else (
                            "push" if g["total"] == line else "lost"
                        )
                    return "won" if g["total"] < line else (
                        "push" if g["total"] == line else "lost"
                    )
    spread_match = re.search(
        r"([\-\+]\d+(?:\.\d+)?)", desc or ""
    )
    if spread_match:
        spread = float(spread_match.group(1))
        for g in finals:
            for tname, info in g["teams"].items():
                if not tname:
                    continue
                if tname.split()[-1] in d or info["short"] in d \
                        or (info["abbr"] and info["abbr"] in d.split()):
                    other = next(
                        (v for k, v in g["teams"].items() if k != tname), None,
                    )
                    if not other:
                        continue
                    diff = info["score"] - other["score"] + spread
                    if diff > 0:
                        return "won"
                    if diff < 0:
                        return "lost"
                    return "push"
    if " ml" in f" {d} " or "moneyline" in d:
        for g in finals:
            for tname, info in g["teams"].items():
                if tname and tname.split()[-1] in d:
                    return "won" if info["won"] else "lost"
    return None


def auto_grade_open_bets(open_bets, active_leagues):
    graded = {"won": 0, "lost": 0, "push": 0, "skipped": 0, "total": 0}
    finals_by_lg = {}
    dates_by_lg = {}
    for b in open_bets:
        date = b.get("date")
        if not date:
            graded["skipped"] += 1
            continue
        for lg in active_leagues:
            dates_by_lg.setdefault(lg, set()).add(date)
    for lg, dates in dates_by_lg.items():
        finals_by_lg[lg] = []
        for d in dates:
            finals_by_lg[lg].extend(fetch_finals(lg, d))
    for b in open_bets:
        graded["total"] += 1
        result = None
        for lg in active_leagues:
            result = _grade_one(b.get("description"), finals_by_lg.get(lg, []))
            if result:
                break
        if result:
            db_settle_bet(b["id"], result)
            graded[result] += 1
        else:
            graded["skipped"] += 1
    return graded


# ---------------- Player prop auto-grader (#76) ----------------
@st.cache_data(ttl=600, show_spinner=False)
def fetch_player_boxscore(league, date_iso):
    """Return list of {player, team, stats:{pts,reb,ast,...}} for a date."""
    espn_lg = {
        "NBA": "basketball/nba", "WNBA": "basketball/wnba",
        "NFL": "football/nfl", "NCAAF": "football/college-football",
        "MLB": "baseball/mlb", "NHL": "hockey/nhl",
        "MLS": "soccer/usa.1", "EPL": "soccer/eng.1",
    }
    path = espn_lg.get(league)
    if not path:
        return []
    try:
        ymd = date_iso.replace("-", "")
        url = (
            f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard"
            f"?dates={ymd}"
        )
        r = requests.get(url, timeout=8)
        if r.status_code != 200:
            return []
        events = (r.json() or {}).get("events") or []
    except Exception:
        return []
    out = []
    for ev in events:
        ev_id = ev.get("id")
        if not ev_id:
            continue
        try:
            sr = requests.get(
                f"https://site.api.espn.com/apis/site/v2/sports/{path}/summary"
                f"?event={ev_id}",
                timeout=8,
            )
            if sr.status_code != 200:
                continue
            box = (sr.json() or {}).get("boxscore") or {}
            for team in box.get("players") or []:
                team_name = (team.get("team") or {}).get("displayName") or ""
                for stat_block in team.get("statistics") or []:
                    keys = [
                        (k or "").lower()
                        for k in (stat_block.get("keys") or [])
                    ]
                    for ath in stat_block.get("athletes") or []:
                        a = ath.get("athlete") or {}
                        name = a.get("displayName") or ""
                        vals = ath.get("stats") or []
                        stats = {}
                        for k, v in zip(keys, vals):
                            try:
                                stats[k] = float(str(v).split("-")[0])
                            except Exception:
                                continue
                        if name and stats:
                            out.append(
                                {"player": name, "team": team_name, "stats": stats}
                            )
        except Exception:
            continue
    return out


_PROP_STAT_ALIASES = {
    "points": ["points", "pts"],
    "pts": ["points", "pts"],
    "rebounds": ["rebounds", "reb", "totreb"],
    "reb": ["rebounds", "reb", "totreb"],
    "assists": ["assists", "ast"],
    "ast": ["assists", "ast"],
    "threes": ["3pm", "threepointfieldgoalsmade", "3ptm"],
    "3pm": ["3pm", "threepointfieldgoalsmade"],
    "steals": ["steals", "stl"],
    "blocks": ["blocks", "blk"],
    "pra": ["pra"],
    "passing yards": ["passingyards", "passyds"],
    "rushing yards": ["rushingyards", "rushyds"],
    "receiving yards": ["receivingyards", "recyds"],
    "receptions": ["receptions", "rec"],
    "passing tds": ["passingtouchdowns", "passtd"],
    "hits": ["hits", "h"],
    "strikeouts": ["strikeouts", "k", "so"],
    "shots": ["shots", "sog", "shotsongoal"],
    "goals": ["goals", "g"],
}


def _stat_value(stats, label):
    label_low = (label or "").lower().strip()
    aliases = _PROP_STAT_ALIASES.get(label_low, [label_low.replace(" ", "")])
    for a in aliases:
        if a in stats:
            return stats[a]
    for k, v in stats.items():
        if any(a in k for a in aliases):
            return v
    return None


def _grade_prop(desc, all_box):
    """Parse 'Player Name OVER 24.5 points' style and return won/lost/push/None."""
    if not desc:
        return None
    txt = " ".join(str(desc).split())
    low = txt.lower()
    side = None
    if " over " in low or low.startswith("over "):
        side = "over"
    elif " under " in low or low.startswith("under "):
        side = "under"
    else:
        return None
    parts = low.split(f" {side} ", 1) if f" {side} " in low else low.split(side + " ", 1)
    if len(parts) != 2:
        return None
    name_raw = parts[0].strip(" :-")
    rest = parts[1].strip()
    tok = rest.split()
    if not tok:
        return None
    try:
        line = float(tok[0])
    except Exception:
        return None
    stat = " ".join(tok[1:]).strip(" .,;:")
    if not stat:
        return None
    name_norm = name_raw.lower()
    best = None
    for row in all_box:
        pn = (row.get("player") or "").lower()
        if not pn:
            continue
        if name_norm in pn or pn in name_norm or all(
            w in pn for w in name_norm.split() if len(w) > 2
        ):
            v = _stat_value(row.get("stats") or {}, stat)
            if v is not None:
                best = v
                break
    if best is None:
        return None
    if abs(best - line) < 1e-6:
        return "push"
    if side == "over":
        return "won" if best > line else "lost"
    return "won" if best < line else "lost"


_NBA_REF_TILT = {
    "scott foster": ("under", "Slow whistle, low FT rate, road-team grim"),
    "tony brothers": ("under", "Tight, tech-happy, slows pace"),
    "marc davis": ("over", "Lets game flow, more possessions"),
    "james capers": ("under", "Tight on physicality, bonus quick"),
    "eric lewis": ("over", "Loose, plenty of and-ones"),
    "sean wright": ("over", "Hitter-friendly equivalent - high FT"),
    "tyler ford": ("over", "Above-avg pace, FT rate up"),
    "zach zarba": ("under", "Veteran tight crew chief"),
    "ed malloy": ("under", "Slows offense, tech-prone"),
    "kane fitzgerald": ("over", "Calls heavy contact - FT spike"),
    "courtney kirkland": ("over", "Lets bigs play, scoring up"),
    "tre maddox": ("over", "Generous on perimeter contact"),
    "david guthrie": ("under", "Veteran, suppresses pace slightly"),
    "josh tiven": ("under", "Tight grip, runs cap"),
    "mark lindsay": ("over", "Above-avg total bias"),
}

_NFL_REF_TILT = {
    "carl cheffers": ("under", "Low penalty rate, clock keeps moving"),
    "brad allen": ("over", "Flag-happy crew, drives extended"),
    "shawn hochuli": ("under", "Tight DPI calls but few overall flags"),
    "bill vinovich": ("over", "Pass-friendly, scoring above avg"),
    "clete blakeman": ("over", "Lots of yardage penalties"),
    "ron torbert": ("under", "Low-flag crew, defense-leaning"),
    "tony corrente": ("over", "High flags, drives extended"),
    "jerome boger": ("over", "Above-avg penalty yardage"),
    "alex kemp": ("under", "Lower penalty rate, totals lean under"),
    "scott novak": ("under", "Quick whistles on offense"),
    "land clark": ("over", "Loose holding/PI standard"),
    "craig wrolstad": ("under", "Veteran tight crew"),
    "adrian hill": ("over", "Defensive holding heavy"),
    "shawn smith": ("under", "Low-flag, defense-leaning"),
    "brad rogers": ("over", "Above avg flags, drives extended"),
}


@st.cache_data(ttl=900, show_spinner=False)
def fetch_ref_crew(league, date_iso, away, home):
    """Return (ref_name, tilt, note) or None. league in {NBA, NFL}."""
    espn_lg = {
        "NBA": "basketball/nba",
        "NFL": "football/nfl",
    }
    path = espn_lg.get(league)
    if not path:
        return None
    try:
        ymd = date_iso.replace("-", "")
        url = (
            f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard"
            f"?dates={ymd}"
        )
        r = requests.get(url, timeout=8)
        if r.status_code != 200:
            return None
        events = (r.json() or {}).get("events") or []
    except Exception:
        return None
    target = None
    aw_l = (away or "").lower()
    hm_l = (home or "").lower()
    for ev in events:
        nm = (ev.get("shortName") or "").lower()
        if (aw_l and aw_l in nm) or (hm_l and hm_l in nm):
            target = ev
            break
    if not target:
        return None
    try:
        sr = requests.get(
            f"https://site.api.espn.com/apis/site/v2/sports/{path}/summary"
            f"?event={target.get('id')}",
            timeout=8,
        )
        if sr.status_code != 200:
            return None
        gi = (sr.json() or {}).get("gameInfo") or {}
        tilt_dict = _NBA_REF_TILT if league == "NBA" else _NFL_REF_TILT
        chief = None
        for off in gi.get("officials") or []:
            pos = (
                (off.get("position") or {}).get("displayName") or ""
            ).lower()
            nm_full = off.get("displayName") or off.get("fullName") or ""
            if league == "NFL" and "referee" in pos:
                chief = nm_full
                break
            if league == "NBA" and ("crew chief" in pos or "chief" in pos):
                chief = nm_full
                break
            if not chief and nm_full:
                chief = nm_full
        if not chief:
            return None
        tilt = tilt_dict.get(chief.lower())
        if tilt:
            return (chief, tilt[0], tilt[1])
        return (chief, "neutral", "No strong historical tilt logged")
    except Exception:
        return None


_NBA_PACE_2024 = {
    "MEM": 103.5, "WAS": 103.0, "ATL": 102.6, "IND": 102.4, "CHI": 102.0,
    "OKC": 101.9, "SAS": 101.7, "DET": 101.4, "MIL": 101.0, "GSW": 100.8,
    "HOU": 100.7, "LAL": 100.5, "SAC": 100.3, "UTA": 100.1, "POR": 99.8,
    "MIN": 99.5, "BOS": 99.2, "PHI": 99.0, "TOR": 98.7, "DAL": 98.5,
    "NOP": 98.3, "BKN": 98.0, "ORL": 97.6, "PHX": 97.3, "CHA": 97.0,
    "MIA": 96.7, "LAC": 96.4, "CLE": 96.0, "DEN": 95.6, "NYK": 95.0,
}
_NBA_LEAGUE_PACE_AVG = 99.5


def _nba_pace_for(team_name):
    if not team_name:
        return None
    t = team_name.upper()
    if t in _NBA_PACE_2024:
        return _NBA_PACE_2024[t]
    aliases = {
        "LAKERS": "LAL", "WARRIORS": "GSW", "CELTICS": "BOS",
        "KNICKS": "NYK", "NETS": "BKN", "76ERS": "PHI", "SIXERS": "PHI",
        "BUCKS": "MIL", "BULLS": "CHI", "HAWKS": "ATL", "HEAT": "MIA",
        "MAGIC": "ORL", "PACERS": "IND", "PISTONS": "DET", "RAPTORS": "TOR",
        "WIZARDS": "WAS", "CAVS": "CLE", "CAVALIERS": "CLE",
        "HORNETS": "CHA", "GRIZZLIES": "MEM", "MAVS": "DAL",
        "MAVERICKS": "DAL", "ROCKETS": "HOU", "SPURS": "SAS",
        "PELICANS": "NOP", "NUGGETS": "DEN", "JAZZ": "UTA",
        "TIMBERWOLVES": "MIN", "WOLVES": "MIN", "THUNDER": "OKC",
        "BLAZERS": "POR", "TRAIL BLAZERS": "POR", "KINGS": "SAC",
        "SUNS": "PHX", "CLIPPERS": "LAC",
    }
    for k, v in aliases.items():
        if k in t:
            return _NBA_PACE_2024.get(v)
    return None


_MLB_UMP_TILT = {
    "angel hernandez": ("under", "Tight zone, walks-heavy, runs scarce"),
    "country joe west": ("under", "Old-school wide zone but slow pace, runs cap"),
    "joe west": ("under", "Old-school wide zone but slow pace, runs cap"),
    "phil cuzzi": ("over", "Inconsistent zone, walks + offense inflate"),
    "ron kulpa": ("over", "Hitter-friendly bottom of zone"),
    "doug eddings": ("over", "Wide horizontal zone, more contact + scoring"),
    "laz diaz": ("over", "Generous zone but high BB% on edges"),
    "lance barksdale": ("under", "Pitcher-friendly, suppresses runs"),
    "dan iassogna": ("under", "Tight, consistent - low-scoring lean"),
    "alfonso marquez": ("over", "Slightly hitter-friendly zone"),
    "jordan baker": ("under", "Big strike zone vs RHB, runs down"),
    "mark wegner": ("over", "Smaller zone, more walks, more runs"),
    "tripp gibson": ("over", "Above-avg run environment"),
    "bill miller": ("under", "Veteran tight zone, low BB%"),
    "ted barrett": ("under", "Crew chief, pitcher-tilt"),
    "carlos torres": ("over", "Newer ump, generous low strike misses"),
    "pat hoberg": ("under", "Most accurate ump in MLB - books price it true"),
    "edwin moscoso": ("over", "Inconsistent low zone, walks up"),
    "junior valentine": ("over", "Wide zone but high BB%"),
    "ryan additon": ("under", "Tight, low-error - runs suppressed"),
    "nick mahrley": ("over", "Wider zone but inconsistent edges"),
    "chris segal": ("under", "Pitcher-friendly outside corner"),
    "adam hamari": ("over", "Slight hitter tilt"),
    "vic carapazza": ("under", "Tight low strike, runs cap"),
    "mike estabrook": ("over", "Above-avg run env, especially totals"),
}


@st.cache_data(ttl=900, show_spinner=False)
def fetch_mlb_ump(date_iso, away_abbr, home_abbr):
    """Return (ump_name, tilt, note) or None if unavailable."""
    try:
        ymd = date_iso.replace("-", "")
        url = (
            "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/"
            f"scoreboard?dates={ymd}"
        )
        r = requests.get(url, timeout=8)
        if r.status_code != 200:
            return None
        events = (r.json() or {}).get("events") or []
    except Exception:
        return None
    target = None
    away_l = (away_abbr or "").lower()
    home_l = (home_abbr or "").lower()
    for ev in events:
        names = (ev.get("shortName") or "").lower()
        if (away_l and away_l in names) or (home_l and home_l in names):
            target = ev
            break
    if not target:
        return None
    try:
        sr = requests.get(
            "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/"
            f"summary?event={target.get('id')}",
            timeout=8,
        )
        if sr.status_code != 200:
            return None
        gi = (sr.json() or {}).get("gameInfo") or {}
        for off in gi.get("officials") or []:
            pos = ((off.get("position") or {}).get("displayName") or "").lower()
            if "home" in pos or "plate" in pos:
                nm = off.get("displayName") or off.get("fullName") or ""
                if nm:
                    tilt = _MLB_UMP_TILT.get(nm.lower())
                    if tilt:
                        return (nm, tilt[0], tilt[1])
                    return (nm, "neutral", "No strong historical tilt")
    except Exception:
        return None
    return None


def auto_grade_prop_bets(open_bets, active_leagues):
    graded = {"won": 0, "lost": 0, "push": 0, "skipped": 0, "total": 0}
    box_by_lg_date = {}
    for b in open_bets:
        graded["total"] += 1
        date = b.get("date")
        if not date:
            graded["skipped"] += 1
            continue
        result = None
        for lg in active_leagues:
            key = (lg, date)
            if key not in box_by_lg_date:
                box_by_lg_date[key] = fetch_player_boxscore(lg, date)
            box = box_by_lg_date[key]
            if not box:
                continue
            result = _grade_prop(b.get("description"), box)
            if result:
                break
        if result:
            db_settle_bet(b["id"], result)
            graded[result] += 1
        else:
            graded["skipped"] += 1
    return graded


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
                point = float(
                    info.get("overUnder")
                    or info.get("bookOverUnder")
                    or info.get("fairOverUnder")
                    or info.get("spread")
                    or info.get("bookSpread")
                    or info.get("fairSpread")
                    or 0
                )
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
                point = float(
                    info.get("spread")
                    or info.get("bookSpread")
                    or info.get("fairSpread")
                    or info.get("overUnder")
                    or 0
                )
            except (TypeError, ValueError):
                point = None
            grouped["Spread"][side].setdefault(point, []).extend(prices)
        elif bt == "ou" and side in ("over", "under"):
            try:
                point = float(
                    info.get("overUnder")
                    or info.get("bookOverUnder")
                    or info.get("fairOverUnder")
                    or 0
                )
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


_RAW_EVENT_CACHE = {}


def get_board(league, books_filter):
    raw, warn = fetch_events(league)
    if warn:
        return [], warn
    events = []
    for ev in raw:
        parsed = parse_event(ev, league, books_filter)
        if parsed:
            events.append(parsed)
            _eid = ev.get("eventID") or ev.get("id") or ""
            if _eid:
                _RAW_EVENT_CACHE[_eid] = ev
                _RAW_EVENT_CACHE[(parsed.away, parsed.home, league)] = ev
    return events, None


def _alt_lines_for_event(raw_ev, books_filter, league):
    """Return {'spread':[(point, side, best_book, best_am, n_books)],
              'total': [...]}."""
    if not raw_ev:
        return {"spread": [], "total": []}
    odds = raw_ev.get("odds") or {}
    home = _team_name(raw_ev, "home")
    away = _team_name(raw_ev, "away")
    by_market = {"spread": {}, "total": {}}
    for _odd_id, info in odds.items():
        if (info.get("periodID") or "").lower() != "game":
            continue
        bt = (info.get("betTypeID") or "").lower()
        if bt not in ("sp", "spread", "ou", "total"):
            continue
        market_key = "spread" if bt in ("sp", "spread") else "total"
        side = (info.get("sideID") or "").lower()
        try:
            point = float(info.get("bookSpread") or info.get("bookOverUnder")
                          or info.get("fairSpread") or info.get("fairOverUnder")
                          or info.get("point") or 0)
        except Exception:
            continue
        if point == 0 and bt in ("sp", "spread"):
            continue
        prices = []
        for book_id, b in (info.get("byBookmaker") or {}).items():
            if books_filter and book_id.lower() not in books_filter:
                continue
            if not b.get("available", True):
                continue
            am = b.get("odds")
            if am is None:
                continue
            try:
                ai = int(round(float(am)))
                prices.append((book_id, ai))
            except Exception:
                continue
        if not prices:
            continue
        best = max(prices, key=lambda x: american_to_decimal(x[1]))
        side_label = side
        if market_key == "spread":
            if side == "home":
                side_label = home
                signed_pt = +point if point > 0 else point
            elif side == "away":
                side_label = away
                signed_pt = -point if point > 0 else point
            else:
                signed_pt = point
        else:
            side_label = side.capitalize()
            signed_pt = point
        bucket = by_market[market_key].setdefault(
            (round(signed_pt, 2), side_label), [],
        )
        bucket.append((best[0], best[1], len(prices)))
    out = {"spread": [], "total": []}
    for (pt, sd), entries in by_market["spread"].items():
        if not entries:
            continue
        b = max(entries, key=lambda e: american_to_decimal(e[1]))
        out["spread"].append((pt, sd, b[0], b[1], b[2]))
    for (pt, sd), entries in by_market["total"].items():
        if not entries:
            continue
        b = max(entries, key=lambda e: american_to_decimal(e[1]))
        out["total"].append((pt, sd, b[0], b[1], b[2]))
    out["spread"].sort(key=lambda r: (r[1], r[0]))
    out["total"].sort(key=lambda r: (r[1], r[0]))
    return out


@st.cache_data(ttl=120, show_spinner=False)
def fetch_pga_leaderboard():
    """Pull current PGA leaderboard from ESPN (free)."""
    try:
        r = requests.get(
            "https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard",
            timeout=8,
        )
        if r.status_code != 200:
            return None, None
        data = r.json() or {}
        events = data.get("events") or []
        if not events:
            return None, None
        ev = events[0]
        name = ev.get("name") or "PGA event"
        comp = (ev.get("competitions") or [{}])[0]
        status = (comp.get("status") or {}).get("type") or {}
        rd = status.get("description") or status.get("name") or ""
        rows = []
        for c in comp.get("competitors") or []:
            ath = c.get("athlete") or {}
            try:
                pos = c.get("status", {}).get("position", {}).get("displayName") or c.get("statusText") or ""
                score = c.get("score") or c.get("status", {}).get("totalScore") or "E"
                thru = c.get("status", {}).get("displayValue") or ""
            except Exception:
                pos, score, thru = "", "", ""
            rows.append({
                "pos": pos[:4] if pos else "-",
                "name": ath.get("displayName") or "-",
                "score": str(score),
                "thru": str(thru)[:6] if thru else "",
            })
        return {"name": name, "round": rd, "rows": rows[:18]}, None
    except Exception as e:
        return None, str(e)


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
.stApp { background: radial-gradient(ellipse at top, __HALO__ 0%, __BG__ 60%); }
#edge-splash {
    position:fixed; inset:0; z-index:999999;
    background: radial-gradient(circle at center, __HALO__ 0%, __BG__ 75%);
    display:flex; align-items:center; justify-content:center;
    animation: splashfade 1.7s ease-out forwards;
}
.edge-splash-logo {
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-weight: 900; letter-spacing: .35em;
    font-size: clamp(48px, 12vw, 160px); color: __CRIMSON__;
    text-shadow: 0 0 40px __CRIMSON__, 0 0 80px __CRIMSON__;
    animation: splashpulse 1.6s cubic-bezier(.2,.9,.2,1) forwards;
}
.edge-splash-tag {
    position:absolute; bottom: 22%; color: __MUTED__;
    font-family: ui-monospace, monospace; letter-spacing:.4em;
    font-size:.75rem; opacity:0; animation: splashtag 1.6s .35s ease-out forwards;
}
@keyframes splashfade {
    0%,68% {opacity:1; pointer-events:auto;}
    100% {opacity:0; pointer-events:none; visibility:hidden;}
}
@keyframes splashpulse {
    0%   {transform: scale(.55); filter: blur(24px); opacity:0;}
    55%  {transform: scale(1.07); filter: blur(0); opacity:1;}
    100% {transform: scale(1);    filter: blur(0); opacity:1;}
}
@keyframes splashtag {
    0%   {opacity:0; transform: translateY(8px);}
    100% {opacity:.9; transform: translateY(0);}
}
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
    animation: ticker-scroll 60s linear infinite;
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
.trend-flat { background:rgba(148,163,184,.15); color:__MUTED__; border:1px solid rgba(148,163,184,.3); padding:1px 8px; border-radius:10px; font-size:.7rem; margin-left:8px; font-weight:600; }
.player-av { display:inline-flex; align-items:center; justify-content:center; width:26px; height:26px; border-radius:50%; font-size:.7rem; font-weight:800; color:#FFF; margin-right:8px; vertical-align:middle; box-shadow:0 1px 4px rgba(0,0,0,.4); border:1px solid rgba(255,255,255,.18); }
.thermo-wrap { background:linear-gradient(135deg,#0F172A 0%, __PANEL__ 100%); border:1px solid rgba(255,255,255,.06); border-radius:12px; padding:14px 16px; margin:8px 0 14px; }
.thermo-row { display:flex; justify-content:space-between; align-items:center; font-size:.78rem; color:#94A3B8; margin:2px 0; }
.thermo-lbl { text-transform:uppercase; letter-spacing:.08em; font-weight:700; color:#CBD5E1; }
.thermo-pct { color:__GREEN__; font-weight:800; font-size:.95rem; }
.thermo-track { background:rgba(255,255,255,.06); border-radius:8px; height:14px; overflow:hidden; margin:6px 0 8px; box-shadow:inset 0 1px 3px rgba(0,0,0,.4); }
.thermo-fill { height:100%; border-radius:8px; transition:width 1.2s cubic-bezier(.4,0,.2,1); box-shadow:0 0 12px rgba(34,197,94,.5); }
.thermo-now { color:#FDE68A; font-weight:800; font-size:.95rem; }
.thermo-end { color:#94A3B8; font-weight:600; }
.inj-wrap { background:rgba(239,68,68,.06); border-left:3px solid __RED__; border-radius:6px; padding:10px 14px; margin:8px 0; }
.inj-head { font-size:.7rem; letter-spacing:.12em; color:__RED__; font-weight:800; margin-bottom:6px; }
.inj-row { display:flex; align-items:center; gap:10px; font-size:.85rem; padding:3px 0; flex-wrap:wrap; }
.inj-team { font-weight:700; color:#CBD5E1; min-width:90px; font-size:.75rem; text-transform:uppercase; letter-spacing:.04em; }
.inj-player { color:#F8FAFC; font-weight:600; }
.inj-status { color:#FFF; font-size:.65rem; padding:1px 7px; border-radius:8px; font-weight:700; text-transform:uppercase; letter-spacing:.04em; }
.inj-detail { font-size:.78rem; flex:1; min-width:200px; }
.report-card { background:linear-gradient(135deg, #1E293B 0%, __PANEL__ 100%); border:1px solid rgba(245,158,11,.25); border-radius:14px; padding:16px 20px; margin-bottom:18px; box-shadow:0 4px 18px rgba(0,0,0,.3); }
.report-head { font-size:.75rem; letter-spacing:.14em; color:#F59E0B; font-weight:800; margin-bottom:12px; }
.report-grid { display:grid; grid-template-columns:auto repeat(5,1fr); gap:18px; align-items:center; font-size:.85rem; }
.report-grade { font-size:2.5rem; font-weight:900; width:64px; height:64px; border:3px solid; border-radius:12px; display:flex; align-items:center; justify-content:center; line-height:1; }
.report-tbl { width:100%; margin-top:14px; font-size:.85rem; border-collapse:collapse; }
.report-tbl th { text-align:left; color:#94A3B8; font-weight:600; font-size:.72rem; text-transform:uppercase; letter-spacing:.06em; padding:6px 8px; border-bottom:1px solid rgba(255,255,255,.08); }
.report-tbl td { padding:6px 8px; border-bottom:1px solid rgba(255,255,255,.04); }
.tick-up   { animation: tickFlashUp 1.6s ease-out 1; padding:0 4px; border-radius:4px; }
.tick-down { animation: tickFlashDown 1.6s ease-out 1; padding:0 4px; border-radius:4px; }
@keyframes tickFlashUp {
    0%   { background:rgba(34,197,94,.85); color:#0B1220; box-shadow:0 0 12px rgba(34,197,94,.7); }
    100% { background:transparent; color:inherit; box-shadow:none; }
}
@keyframes tickFlashDown {
    0%   { background:rgba(239,68,68,.85); color:#0B1220; box-shadow:0 0 12px rgba(239,68,68,.7); }
    100% { background:transparent; color:inherit; box-shadow:none; }
}
.ai-prompt-btn { font-size:.85rem !important; }
.ath-cannon {
    background:linear-gradient(90deg,#FDE68A 0%,__GREEN__ 50%,#FDE68A 100%);
    background-size:200% 100%;
    color:#0B1220; font-weight:900; text-align:center;
    padding:14px 18px; border-radius:14px; margin:14px 0 18px;
    font-size:1.2rem; letter-spacing:.06em; text-transform:uppercase;
    box-shadow:0 4px 30px rgba(34,197,94,.5),0 0 60px rgba(253,230,138,.4);
    animation: athPulse 1.6s ease-in-out infinite, athShine 3s linear infinite;
    position:relative; overflow:hidden;
}
.ath-cannon::before, .ath-cannon::after {
    content:''; position:absolute; top:50%; width:8px; height:8px;
    background:#F59E0B; border-radius:50%;
    animation: athConfetti 2s linear infinite;
}
.ath-cannon::before { left:6%; animation-delay:0s; }
.ath-cannon::after { right:6%; animation-delay:.5s; background:__GREEN__; }
.ath-prev { font-size:.7rem; opacity:.7; font-weight:600; margin-left:10px; }
@keyframes athPulse {
    0%,100% { transform:scale(1); }
    50% { transform:scale(1.02); }
}
@keyframes athShine {
    0% { background-position:0% 50%; }
    100% { background-position:200% 50%; }
}
@keyframes athConfetti {
    0% { transform:translateY(-30px) scale(0); opacity:0; }
    20% { opacity:1; }
    100% { transform:translateY(50px) scale(1.2) rotate(360deg); opacity:0; }
}
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

.war-room {
    background: linear-gradient(90deg, #1a0a10 0%, __PANEL__ 50%, #1a0a10 100%);
    border: 1px solid rgba(239,68,68,.35); border-radius: 12px;
    padding: 12px 16px; margin: 6px 0 16px;
    box-shadow: 0 0 22px rgba(239,68,68,.18);
}
.wr-head {
    font-size:.72rem; letter-spacing:.18em; color:#FCA5A5;
    font-weight:800; margin-bottom:8px; display:flex; align-items:center;
}
.wr-pulse {
    width:8px; height:8px; background:__RED__; border-radius:50%;
    margin-right:8px; animation: wrpulse 1.4s infinite;
    box-shadow:0 0 10px __RED__;
}
@keyframes wrpulse {
    0%,100% { opacity:1; transform: scale(1); }
    50%     { opacity:.4; transform: scale(.7); }
}
.wr-row {
    display:flex; align-items:center; gap:14px; padding:6px 0;
    border-top:1px dashed rgba(255,255,255,.06); font-size:.85rem;
    color:#CBD5E1; flex-wrap:wrap;
}
.wr-row:first-of-type { border-top:none; }
.wr-tag {
    color:#fff; font-weight:800; font-size:.66rem; letter-spacing:.1em;
    padding:2px 8px; border-radius:6px;
}
.wr-score { font-family:ui-monospace,monospace; font-size:.95rem; }
.wr-detail { color:__MUTED__; font-size:.78rem; }
.wr-bet { color:__MUTED__; font-size:.78rem; margin-left:auto;
          font-style:italic; max-width:50%; text-align:right; }

.ach-wrap {
    background: linear-gradient(135deg, #1E293B 0%, __PANEL__ 100%);
    border: 1px solid rgba(245,158,11,.25); border-radius: 14px;
    padding: 14px 18px; margin: 10px 0 16px;
}
.ach-head {
    font-size:.72rem; letter-spacing:.18em; color:#FDE68A;
    font-weight:800; margin-bottom:10px;
}
.ach-count {
    background: rgba(245,158,11,.2); color:#FDE68A;
    padding:2px 8px; border-radius:8px; font-size:.7rem;
    margin-left:6px;
}
.ach-grid {
    display:grid; grid-template-columns: repeat(auto-fill,minmax(170px,1fr));
    gap: 8px;
}
.ach-chip {
    border-radius:10px; padding:8px 12px; font-size:.78rem; font-weight:700;
    transition: transform .2s;
}
.ach-chip:hover { transform: translateY(-2px); }
.ach-name { font-size:.85rem; }
.ach-mark { font-weight:900; margin-right:4px; }
.ach-desc { font-size:.68rem; opacity:.85; font-weight:500;
            margin-top:2px; }

.followup-pill {
    display:inline-block; background:rgba(158,27,50,.12);
    color:#FCA5A5; border:1px solid rgba(158,27,50,.4);
    padding:4px 10px; margin:4px 6px 0 0; border-radius:14px;
    font-size:.75rem; font-weight:600;
}
</style>
"""
if "_pending_theme" in st.session_state:
    st.session_state["theme_choice"] = st.session_state.pop("_pending_theme")
_theme_name = st.sidebar.selectbox(
    "Theme", list(THEMES.keys()), index=0, key="theme_choice",
    help="Color palette for the dashboard.",
)
_theme = THEMES[_theme_name]
CRIMSON = _theme["accent"]
BG = _theme["bg"]
PANEL = _theme["panel"]
HALO = _theme["halo"]

CSS = (
    CSS.replace("__BG__", _theme["bg"])
       .replace("__PANEL__", _theme["panel"])
       .replace("__CRIMSON__", _theme["accent"])
       .replace("__HALO__", _theme["halo"])
       .replace("__MUTED__", MUTED)
       .replace("__GREEN__", GREEN)
       .replace("__AMBER__", AMBER)
       .replace("__RED__", RED)
)
st.markdown(CSS, unsafe_allow_html=True)

# ---- Team theme override (recolor hard-coded reds across all components) ----
def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

if _theme_name in ("Alabama Crimson Tide", "Tennessee Volunteers"):
    _ac = _theme["accent"]
    _ar, _ag, _ab = _hex_to_rgb(_ac)
    _rgb = f"{_ar},{_ag},{_ab}"
    st.markdown(
        f"""
<style>
/* Re-skin hard-coded crimson surfaces to match team accent */
.edge-fight-card {{
  border-color: {_ac} !important;
  background:
    radial-gradient(circle at 50% 0%, rgba({_rgb},.28), rgba(0,0,0,0) 60%),
    linear-gradient(180deg, rgba({_rgb},.10), #0a0a0a) !important;
  box-shadow:
    0 0 40px rgba({_rgb},.18) inset,
    0 12px 30px rgba(0,0,0,.5) !important;
}}
.edge-fight-banner {{ background: {_ac} !important; }}
.edge-fight-vs    {{ color: {_ac} !important;
                    text-shadow: 0 0 18px rgba({_rgb},.6) !important; }}
.edge-ticker {{
  border-top-color: rgba({_rgb},.4) !important;
  border-bottom-color: rgba({_rgb},.4) !important;
  box-shadow: 0 0 30px rgba({_rgb},.18) !important;
}}
.edge-ticker-item .sep {{ color: {_ac} !important; }}
.edge-card-hover:hover {{
  box-shadow: 0 14px 40px rgba(0,0,0,.55), 0 0 22px rgba({_rgb},.22) !important;
  border-color: rgba({_rgb},.45) !important;
}}
.edge-score-card {{
  background: linear-gradient(180deg, rgba({_rgb},.10), rgba(0,0,0,.20)) !important;
}}
.edge-pace.slow         {{ color: {_ac} !important;
                           border-color: rgba({_rgb},.4) !important; }}
.edge-ump .tilt-under   {{ color: {_ac} !important; }}
.edge-pga td.score-up   {{ color: {_ac} !important; }}
.edge-mobar-cell .v.red {{ color: {_ac} !important; }}
#edge-music-btn         {{ border-color: rgba({_rgb},.4) !important; }}
#edge-music-btn.on      {{ background: {_ac} !important;
                           border-color: {_ac} !important;
                           box-shadow: 0 0 14px rgba({_rgb},.45) !important; }}
.book-link, .edge-pill, .edge-badge,
.stTabs [aria-selected="true"] {{
  /* tab + chip accent */
}}
.stTabs [aria-selected="true"] {{
  color: {_ac} !important;
  border-bottom-color: {_ac} !important;
}}
button[kind="primary"] {{
  background-color: {_ac} !important;
  border-color: {_ac} !important;
}}
/* Splash fog tint */
#edge-splash::before {{
  background:
    radial-gradient(closest-side at 25% 35%, rgba({_rgb},.20), transparent 60%),
    radial-gradient(closest-side at 70% 60%, rgba(255,255,255,.08), transparent 65%),
    radial-gradient(closest-side at 50% 80%, rgba({_rgb},.14), transparent 70%),
    radial-gradient(closest-side at 80% 20%, rgba(255,255,255,.06), transparent 60%) !important;
}}
#edge-splash::after {{
  background:
    radial-gradient(closest-side at 60% 25%, rgba(255,255,255,.06), transparent 55%),
    radial-gradient(closest-side at 30% 70%, rgba({_rgb},.12), transparent 60%),
    radial-gradient(closest-side at 75% 75%, rgba(255,255,255,.05), transparent 60%) !important;
}}
/* Tour modal accent */
#edge-tour-ov + * {{}}
</style>
        """,
        unsafe_allow_html=True,
    )
    # Team mascot ribbon under the title
    if _theme_name == "Alabama Crimson Tide":
        _mascot_text = "ROLL TIDE - HOUNDSTOOTH SHARP"
        _mascot_icon = (
            "<svg viewBox='0 0 80 60' width='34' height='26' "
            "style='vertical-align:middle;margin:0 10px -6px'>"
            "<path d='M10 38 Q10 12 40 12 Q66 12 70 32 L70 44 "
            "Q70 52 60 52 L20 52 Q10 52 10 44 Z' "
            "fill='#9E1B32' stroke='#000' stroke-width='1.5'/>"
            "<path d='M22 14 Q40 8 62 16 L62 20 Q40 14 22 18 Z' "
            "fill='#fff' opacity='.85'/>"
            "<path d='M8 36 L26 36 M8 42 L24 42' stroke='#bbb' "
            "stroke-width='2' fill='none'/>"
            "<text x='48' y='38' font-family='Bebas Neue,sans-serif' "
            "font-size='18' font-weight='900' fill='#fff' "
            "text-anchor='middle'>A</text></svg>"
        )
    else:
        _mascot_text = "VOL NAVY - GO BIG ORANGE"
        _mascot_icon = (
            "<svg viewBox='0 0 80 60' width='34' height='26' "
            "style='vertical-align:middle;margin:0 10px -6px'>"
            "<path d='M10 38 Q10 12 40 12 Q66 12 70 32 L70 44 "
            "Q70 52 60 52 L20 52 Q10 52 10 44 Z' "
            "fill='#FF8200' stroke='#000' stroke-width='1.5'/>"
            "<path d='M22 14 Q40 8 62 16 L62 20 Q40 14 22 18 Z' "
            "fill='#fff' opacity='.85'/>"
            "<path d='M8 36 L26 36 M8 42 L24 42' stroke='#bbb' "
            "stroke-width='2' fill='none'/>"
            "<text x='48' y='38' font-family='Bebas Neue,sans-serif' "
            "font-size='18' font-weight='900' fill='#fff' "
            "text-anchor='middle'>T</text></svg>"
        )
    _mascot = f"{_mascot_icon}{_mascot_text}{_mascot_icon}"
    st.markdown(
        f"""
<div style="
  text-align:center; padding:6px 12px; margin:-6px 0 10px;
  background: linear-gradient(90deg, transparent, rgba({_rgb},.18), transparent);
  border-top: 1px solid rgba({_rgb},.35);
  border-bottom: 1px solid rgba({_rgb},.35);
  font-family: 'Bebas Neue','Oswald',sans-serif;
  letter-spacing: .25em; font-size: .82rem; color:{_ac};
  text-shadow: 0 0 10px rgba({_rgb},.5);
">{_mascot}</div>
        """,
        unsafe_allow_html=True,
    )

st.markdown(
    """
<style>
.edge-card-hover {
  transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
  border-radius: 12px;
  border: 1px solid rgba(255,255,255,.06);
  padding: 10px 12px;
}
.edge-card-hover:hover {
  transform: translateY(-3px) scale(1.012);
  box-shadow: 0 14px 40px rgba(0,0,0,.55), 0 0 22px rgba(220,38,38,.18);
  border-color: rgba(220,38,38,.45);
}
.edge-scorestrip {
  display:flex; gap:10px; overflow-x:auto; padding:8px 2px 14px;
  scrollbar-width: thin;
}
.edge-score-card {
  flex: 0 0 auto;
  min-width: 180px;
  background: linear-gradient(180deg, rgba(220,38,38,.10), rgba(0,0,0,.20));
  border: 1px solid rgba(255,255,255,.07);
  border-radius: 10px;
  padding: 8px 12px;
  font-size: .82rem;
}
.edge-score-card .lg { color:#9CA3AF; font-size:.7rem; letter-spacing:.08em; text-transform:uppercase; }
.edge-score-card .row { display:flex; justify-content:space-between; padding:1px 0; }
.edge-score-card .row .sc { font-weight:700; font-variant-numeric:tabular-nums; }
.edge-score-card .st { color:#F59E0B; font-size:.7rem; margin-top:3px; }
.edge-score-card.live { border-color: rgba(16,185,129,.55); }
.edge-score-card.live .st { color:#10B981; }

/* ---- Money rain (#2) ---- */
.edge-money-rain {
  position: fixed; inset: 0; pointer-events: none; z-index: 9998;
  overflow: hidden;
}
.edge-money-rain .bill {
  position: absolute; top: -60px; font-size: 32px;
  animation: edgeFall linear forwards;
  filter: drop-shadow(0 4px 6px rgba(0,0,0,.4));
}
@keyframes edgeFall {
  0%   { transform: translateY(-60px) rotate(0deg); opacity: 0; }
  10%  { opacity: 1; }
  90%  { opacity: 1; }
  100% { transform: translateY(110vh) rotate(540deg); opacity: 0; }
}
.edge-money-banner {
  position: fixed; top: 22%; left: 50%; transform: translateX(-50%);
  z-index: 9999; pointer-events: none;
  font-family: "Bebas Neue", "Oswald", sans-serif;
  font-size: 56px; letter-spacing: .12em; color: #10B981;
  text-shadow: 0 0 30px rgba(16,185,129,.7), 0 4px 14px rgba(0,0,0,.6);
  animation: edgeBannerPop 2.6s ease-out forwards;
}
@keyframes edgeBannerPop {
  0%   { transform: translate(-50%, -20px) scale(.6); opacity: 0; }
  20%  { transform: translate(-50%, 0) scale(1.05); opacity: 1; }
  85%  { transform: translate(-50%, 0) scale(1); opacity: 1; }
  100% { transform: translate(-50%, -10px) scale(.95); opacity: 0; }
}

/* ---- Fight card (#4) ---- */
.edge-fight-card {
  position: relative;
  background: radial-gradient(circle at 50% 0%, rgba(220,38,38,.28), rgba(0,0,0,0) 60%),
              linear-gradient(180deg, #1a0a0a, #0a0a0a);
  border: 2px solid #DC2626;
  border-radius: 14px;
  padding: 18px 20px 16px;
  margin: 8px 0 18px;
  box-shadow: 0 0 40px rgba(220,38,38,.18) inset, 0 12px 30px rgba(0,0,0,.5);
}
.edge-fight-banner {
  position: absolute; top: -12px; left: 50%; transform: translateX(-50%);
  background: #DC2626; color: #fff;
  font-family: "Bebas Neue", "Oswald", sans-serif;
  letter-spacing: .25em; font-size: .8rem;
  padding: 4px 14px; border-radius: 4px;
}
.edge-fight-grid {
  display: grid; grid-template-columns: 1fr auto 1fr; gap: 14px;
  align-items: center; margin-top: 10px;
}
.edge-fight-side { text-align: center; }
.edge-fight-side .nm {
  font-family: "Bebas Neue", "Oswald", sans-serif;
  font-size: 1.9rem; letter-spacing: .06em; color:#F3F4F6;
  text-shadow: 0 2px 0 rgba(0,0,0,.6);
}
.edge-fight-side .rec { color:#9CA3AF; font-size:.78rem; margin-top:2px; }
.edge-fight-side .ml { color:#F59E0B; font-weight:700; margin-top:6px;
  font-variant-numeric: tabular-nums; }
.edge-fight-vs {
  font-family: "Bebas Neue", "Oswald", sans-serif;
  font-size: 2.6rem; color:#DC2626;
  text-shadow: 0 0 18px rgba(220,38,38,.6);
}
.edge-fight-tot {
  text-align:center; color:#9CA3AF; margin-top:10px;
  font-size:.78rem; letter-spacing:.08em; text-transform:uppercase;
}

/* ---- Smoke / fog layer over splash (#2) ---- */
#edge-splash::before, #edge-splash::after {
  content: "";
  position: absolute; inset: -20%;
  pointer-events: none; z-index: 1;
  background:
    radial-gradient(closest-side at 25% 35%, rgba(220,38,38,.18), transparent 60%),
    radial-gradient(closest-side at 70% 60%, rgba(255,255,255,.08), transparent 65%),
    radial-gradient(closest-side at 50% 80%, rgba(220,38,38,.12), transparent 70%),
    radial-gradient(closest-side at 80% 20%, rgba(255,255,255,.06), transparent 60%);
  filter: blur(40px);
  animation: edgeFog1 18s ease-in-out infinite alternate;
  opacity: .9;
}
#edge-splash::after {
  background:
    radial-gradient(closest-side at 60% 25%, rgba(255,255,255,.06), transparent 55%),
    radial-gradient(closest-side at 30% 70%, rgba(220,38,38,.10), transparent 60%),
    radial-gradient(closest-side at 75% 75%, rgba(255,255,255,.05), transparent 60%);
  animation: edgeFog2 24s ease-in-out infinite alternate;
  filter: blur(55px);
  opacity: .8;
}
#edge-splash > * { position: relative; z-index: 2; }
@keyframes edgeFog1 {
  0%   { transform: translate(-3%, -2%) scale(1);    }
  50%  { transform: translate( 4%,  3%) scale(1.08); }
  100% { transform: translate(-2%,  4%) scale(1.05); }
}
@keyframes edgeFog2 {
  0%   { transform: translate( 2%,  3%) scale(1.05); }
  50%  { transform: translate(-4%, -2%) scale(.97);  }
  100% { transform: translate( 3%, -3%) scale(1.1);  }
}

/* ---- Stock ticker scrolling strip (#19) ---- */
.edge-ticker {
  background: linear-gradient(90deg, #000 0%, #0a0a0a 50%, #000 100%);
  border-top: 1px solid rgba(220,38,38,.4);
  border-bottom: 1px solid rgba(220,38,38,.4);
  padding: 7px 0; overflow: hidden; position: relative;
  font-family: "JetBrains Mono", "IBM Plex Mono", monospace;
  font-size: .82rem; letter-spacing: .04em;
  margin: -8px 0 14px;
  box-shadow: 0 0 30px rgba(220,38,38,.18);
}
.edge-ticker::before, .edge-ticker::after {
  content: ""; position: absolute; top: 0; bottom: 0; width: 60px;
  z-index: 2; pointer-events: none;
}
.edge-ticker::before { left: 0;
  background: linear-gradient(90deg, #000 30%, transparent); }
.edge-ticker::after  { right: 0;
  background: linear-gradient(270deg, #000 30%, transparent); }
.edge-ticker-track {
  display: inline-block; white-space: nowrap;
  animation: edgeTick 80s linear infinite;
  padding-left: 100%;
}
.edge-ticker-track:hover { animation-play-state: paused; }
.edge-ticker-item { display: inline-block; padding: 0 28px; color: #D1D5DB; }
.edge-ticker-item .lg  { color: #9CA3AF; font-weight: 700; margin-right: 6px; }
.edge-ticker-item .pk  { color: #F3F4F6; }
.edge-ticker-item .pr  { color: #10B981; font-weight: 700; margin-left: 8px; }
.edge-ticker-item .eb  { color: #FBBF24; margin-left: 8px; }
.edge-ticker-item .bk  { color: #6B7280; margin-left: 6px; font-size: .72rem; }
.edge-ticker-item .sep { color: #DC2626; margin: 0 4px; }
@keyframes edgeTick {
  0%   { transform: translateX(0); }
  100% { transform: translateX(-100%); }
}

/* ---- Trophy case (#44) ---- */
.edge-trophy-case {
  background:
    linear-gradient(180deg, rgba(245,158,11,.06), rgba(0,0,0,.4)) !important,
    radial-gradient(ellipse at 50% -20%, rgba(245,158,11,.18), transparent 60%);
  border: 1px solid rgba(245,158,11,.25) !important;
  border-radius: 14px !important;
  padding: 18px 16px !important;
  box-shadow:
    inset 0 0 40px rgba(245,158,11,.06),
    0 0 30px rgba(245,158,11,.08);
  position: relative;
}
.edge-trophy-case::before {
  content: ""; position: absolute; left: 4%; right: 4%;
  height: 3px; bottom: 28%;
  background: linear-gradient(90deg,
    transparent, rgba(245,158,11,.45), transparent);
  box-shadow: 0 1px 6px rgba(245,158,11,.4);
}
.edge-trophy-case::after {
  content: ""; position: absolute; left: 4%; right: 4%;
  height: 3px; bottom: 4%;
  background: linear-gradient(90deg,
    transparent, rgba(245,158,11,.35), transparent);
  box-shadow: 0 1px 6px rgba(245,158,11,.3);
}
.edge-trophy-head {
  text-align: center;
  font-family: "Bebas Neue", "Oswald", sans-serif;
  letter-spacing: .25em; font-size: 1.05rem;
  color: #F59E0B; margin-bottom: 12px;
  text-shadow: 0 0 14px rgba(245,158,11,.45);
}
.edge-trophy-head .sparkle {
  display: inline-block; margin: 0 8px;
  animation: edgeSparkle 2.4s ease-in-out infinite;
}
@keyframes edgeSparkle {
  0%, 100% { opacity: .35; transform: scale(.85); }
  50%      { opacity: 1;   transform: scale(1.15); }
}

/* ---- Slot-machine shuffle on best-price flips (#3) ---- */
b[style*="#10B981"] {
  animation: edgeShuffle 0.65s ease-out 1;
  display: inline-block;
}
@keyframes edgeShuffle {
  0%   { opacity: 0; transform: translateY(-10px) scale(.85); filter: blur(2px); }
  35%  { opacity: 1; transform: translateY(4px) scale(1.08); filter: blur(0); }
  70%  { transform: translateY(-1px) scale(.98); }
  100% { transform: translateY(0) scale(1); }
}

/* ---- Mobile bottom status bar (#4) ---- */
.edge-mobar {
  position: fixed; bottom: 0; left: 0; right: 0; z-index: 9990;
  display: none;
  background: linear-gradient(180deg, rgba(15,15,15,.85), rgba(0,0,0,.96));
  backdrop-filter: blur(14px);
  border-top: 1px solid rgba(220,38,38,.4);
  padding: 8px 12px 10px;
  font-family: "Bebas Neue", "Oswald", sans-serif;
}
.edge-mobar-row {
  display: grid; grid-template-columns: 1fr 1fr 1fr 1fr;
  gap: 8px; align-items: center; text-align: center;
}
.edge-mobar-cell { color: #9CA3AF; font-size: .65rem; letter-spacing: .12em; }
.edge-mobar-cell .v {
  display: block; font-size: 1.1rem; color: #F3F4F6;
  font-variant-numeric: tabular-nums; letter-spacing: .04em;
}
.edge-mobar-cell .v.green { color: #10B981; }
.edge-mobar-cell .v.red   { color: #DC2626; }
@media (max-width: 760px) {
  .edge-mobar { display: block; }
  section[data-testid="stMain"] { padding-bottom: 96px !important; }
}

/* ---- Alt-line shopper table (#29) ---- */
.edge-altwrap { font-size: .82rem; }
.edge-altwrap table { width: 100%; border-collapse: collapse; }
.edge-altwrap th, .edge-altwrap td {
  padding: 5px 8px; border-bottom: 1px solid rgba(255,255,255,.05);
  text-align: left;
}
.edge-altwrap th { color: #9CA3AF; font-weight: 600; font-size: .72rem;
  letter-spacing: .08em; text-transform: uppercase; }
.edge-altwrap td.num { font-variant-numeric: tabular-nums; }
.edge-altwrap td.best { color: #10B981; font-weight: 700; }

/* ---- SGP builder (#30) ---- */
.edge-sgp-warn {
  background: rgba(220,38,38,.08);
  border: 1px solid rgba(220,38,38,.3);
  border-radius: 8px; padding: 8px 12px; font-size: .85rem; color: #F3F4F6;
  margin: 8px 0;
}

/* ---- PGA leaderboard (#38) ---- */
.edge-pga {
  background: linear-gradient(180deg, rgba(16,185,129,.06), rgba(0,0,0,.2));
  border: 1px solid rgba(16,185,129,.25);
  border-radius: 10px; padding: 10px 14px;
}
.edge-pga h4 { color:#10B981; margin: 0 0 6px;
  font-family: "Bebas Neue", "Oswald", sans-serif; letter-spacing: .14em; }
.edge-pga table { width: 100%; border-collapse: collapse; font-size: .85rem; }
.edge-pga th, .edge-pga td {
  padding: 4px 8px; border-bottom: 1px solid rgba(255,255,255,.04);
}
.edge-pga th { color: #9CA3AF; font-size: .7rem; text-align: left;
  letter-spacing: .08em; text-transform: uppercase; }
.edge-pga td.score-up { color: #DC2626; font-weight: 700; }
.edge-pga td.score-dn { color: #10B981; font-weight: 700; }

/* ---- Siri shortcut card (#75) ---- */
.edge-siri {
  background: rgba(59,130,246,.08);
  border: 1px solid rgba(59,130,246,.3);
  border-radius: 8px; padding: 10px 12px; font-size: .82rem;
  color: #DBEAFE; margin: 6px 0;
}
.edge-siri code {
  display:block; word-break: break-all;
  background: rgba(0,0,0,.4); padding: 6px 8px; border-radius: 6px;
  margin-top: 6px; font-size: .72rem; color:#F3F4F6;
}

/* ---- Lava lamp blobs (#22) ---- */
.edge-lava {
  position: fixed; inset: 0; z-index: -1; pointer-events: none;
  overflow: hidden; filter: blur(48px) saturate(140%);
  opacity: .55;
}
.edge-lava .blob {
  position: absolute; border-radius: 50%;
  mix-blend-mode: screen;
  animation: edgeLava 22s ease-in-out infinite;
}
.edge-lava .b1 { width: 520px; height: 520px; top: -120px; left: -80px;
  animation-duration: 26s; }
.edge-lava .b2 { width: 420px; height: 420px; top: 30%; left: 55%;
  animation-duration: 32s; animation-delay: -7s; }
.edge-lava .b3 { width: 360px; height: 360px; top: 65%; left: 8%;
  animation-duration: 38s; animation-delay: -14s; }
.edge-lava .b4 { width: 300px; height: 300px; top: 8%; left: 70%;
  animation-duration: 30s; animation-delay: -3s; }
@keyframes edgeLava {
  0%   { transform: translate(0,0) scale(1); }
  33%  { transform: translate(40vw, 12vh) scale(1.15); }
  66%  { transform: translate(-12vw, 30vh) scale(.85); }
  100% { transform: translate(0,0) scale(1); }
}

/* ---- Lottery ball tumbler (#21) ---- */
.edge-tumbler-wrap {
  position: fixed; inset: 0; z-index: 9997; pointer-events: none;
  display: flex; align-items: center; justify-content: center;
  background: radial-gradient(circle at center, rgba(0,0,0,.55), rgba(0,0,0,.85));
  animation: edgeTumblerFade 3.4s ease-out forwards;
}
@keyframes edgeTumblerFade {
  0% { opacity: 0; }
  10% { opacity: 1; }
  85% { opacity: 1; }
  100% { opacity: 0; }
}
.edge-tumbler {
  position: relative; width: 360px; height: 360px;
  border-radius: 50%;
  border: 6px solid rgba(220,38,38,.5);
  background: radial-gradient(circle at 30% 30%, rgba(255,255,255,.06), rgba(0,0,0,.7));
  box-shadow: 0 0 60px rgba(220,38,38,.4), inset 0 0 40px rgba(0,0,0,.6);
  overflow: hidden;
}
.edge-tumbler .ball {
  position: absolute; width: 56px; height: 56px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-family: "Bebas Neue", "Oswald", sans-serif;
  font-size: 1.2rem; color: #1a0a0a;
  box-shadow: inset -6px -6px 12px rgba(0,0,0,.35), 0 4px 8px rgba(0,0,0,.5);
  animation: edgeBall 2.6s ease-in-out infinite;
}
.edge-tumbler .ball.b-red    { background: radial-gradient(circle at 30% 30%, #ff7e7e, #DC2626); color:#fff; }
.edge-tumbler .ball.b-amber  { background: radial-gradient(circle at 30% 30%, #ffd680, #F59E0B); }
.edge-tumbler .ball.b-green  { background: radial-gradient(circle at 30% 30%, #8af0c2, #10B981); color:#fff; }
.edge-tumbler .ball.b-blue   { background: radial-gradient(circle at 30% 30%, #aac6ff, #3B82F6); color:#fff; }
.edge-tumbler .ball.b-white  { background: radial-gradient(circle at 30% 30%, #ffffff, #d1d5db); }
@keyframes edgeBall {
  0%   { transform: translate(120px, 120px) rotate(0deg); }
  25%  { transform: translate(40px, 240px) rotate(180deg); }
  50%  { transform: translate(220px, 200px) rotate(360deg); }
  75%  { transform: translate(220px, 60px) rotate(540deg); }
  100% { transform: translate(120px, 120px) rotate(720deg); }
}
.edge-tumbler-label {
  position: absolute; bottom: -54px; left: 50%; transform: translateX(-50%);
  font-family: "Bebas Neue", "Oswald", sans-serif;
  font-size: 1.5rem; letter-spacing: .15em; color: #F59E0B;
  text-shadow: 0 0 18px rgba(245,158,11,.7);
}

/* ---- Ref crew + pace pills (#68 #70) ---- */
.edge-ref {
  display:inline-flex; align-items:center; gap:8px;
  background: rgba(59,130,246,.08);
  border: 1px solid rgba(59,130,246,.3);
  padding: 4px 10px; border-radius: 999px;
  font-size: .76rem; color:#3B82F6; margin: 4px 6px 4px 0;
}
.edge-pace {
  display:inline-flex; align-items:center; gap:6px;
  background: rgba(16,185,129,.08);
  border: 1px solid rgba(16,185,129,.3);
  padding: 4px 10px; border-radius: 999px;
  font-size: .76rem; color:#10B981; margin: 4px 6px 4px 0;
}
.edge-pace.fast { color:#10B981; border-color: rgba(16,185,129,.5); }
.edge-pace.slow { color:#DC2626; border-color: rgba(220,38,38,.4);
  background: rgba(220,38,38,.07); }
.edge-pace.avg  { color:#9CA3AF; border-color: rgba(156,163,175,.3);
  background: rgba(156,163,175,.06); }
.edge-pace .bar {
  display:inline-block; width:60px; height:5px; border-radius:3px;
  background: linear-gradient(90deg,#DC2626,#F59E0B,#10B981);
  position: relative;
}
.edge-pace .bar::after {
  content:''; position:absolute; top:-3px; width:3px; height:11px;
  background:#F3F4F6; border-radius:2px;
}

/* ---- Ump factor (#67) ---- */
.edge-ump {
  display:inline-flex; align-items:center; gap:8px;
  background: rgba(245,158,11,.08);
  border: 1px solid rgba(245,158,11,.3);
  padding: 4px 10px; border-radius: 999px;
  font-size: .76rem; color:#F59E0B; margin: 4px 0;
}
.edge-ump .tilt-over  { color:#10B981; font-weight:700; }
.edge-ump .tilt-under { color:#DC2626; font-weight:700; }
.edge-ump .tilt-neut  { color:#9CA3AF; font-weight:700; }
</style>
""",
    unsafe_allow_html=True,
)

# ---------------- Multi-user PIN gate ----------------
if not st.session_state.get("edge_user"):
    sp = st.empty()
    with sp.container():
        st.markdown("## Edge - Sign in")
        st.caption(
            "Enter a username and 4+ digit PIN. Your bets, badges and notes are "
            "stored under this user. Use the same combo to log back in."
        )
        cu1, cu2 = st.columns(2)
        u_name = cu1.text_input("Username", key="pin_user_input", max_chars=24)
        u_pin = cu2.text_input(
            "PIN", key="pin_pin_input", type="password", max_chars=12,
        )
        cb1, cb2 = st.columns([1, 3])
        if cb1.button("Sign in", type="primary", use_container_width=True):
            uname = (u_name or "").strip().lower()
            if not uname or len(u_pin or "") < 4:
                st.error("Need a username and 4+ digit PIN.")
                st.stop()
            uid = f"{uname}-{_user_pin_hash(u_pin)}"
            st.session_state["edge_user"] = uid
            st.session_state["edge_user_label"] = uname
            st.rerun()
        cb2.caption(
            "Tip: PINs are hashed before being used as a key suffix. Pick "
            "something only you know - lose the PIN, lose access to that book."
        )
    st.stop()

# ---- Lava lamp background (#22) ----
_pulse = float(st.session_state.get("edge_pulse", 0.0))
if _pulse >= 150:
    _lava_palette = ("#10B981", "#34D399", "#F59E0B", "#DC2626")
elif _pulse >= 50:
    _lava_palette = ("#F59E0B", "#DC2626", "#3B82F6", "#10B981")
elif _pulse <= -25:
    _lava_palette = ("#7F1D1D", "#DC2626", "#1F2937", "#1F2937")
else:
    _lava_palette = ("#1F2937", "#374151", "#1F2937", "#3B82F6")
st.markdown(
    f"<div class='edge-lava'>"
    f"<div class='blob b1' style='background:{_lava_palette[0]}'></div>"
    f"<div class='blob b2' style='background:{_lava_palette[1]}'></div>"
    f"<div class='blob b3' style='background:{_lava_palette[2]}'></div>"
    f"<div class='blob b4' style='background:{_lava_palette[3]}'></div>"
    f"</div>",
    unsafe_allow_html=True,
)

# ---- Lottery ball tumbler renderer (#21) ----
if st.session_state.pop("tumbler", False):
    import random as _trng
    _legs_lbl = st.session_state.pop("tumbler_labels", []) or []
    _odds_lbl = st.session_state.pop("tumbler_odds", "")
    _colors = ["b-red", "b-amber", "b-green", "b-blue", "b-white"]
    _balls = []
    for i, lbl in enumerate(_legs_lbl[:8]):
        _c = _colors[i % len(_colors)]
        _delay = round(-_trng.uniform(0, 2.4), 2)
        _initial_x = _trng.randint(40, 260)
        _initial_y = _trng.randint(40, 260)
        _balls.append(
            f"<div class='ball {_c}' style='top:{_initial_y}px;"
            f"left:{_initial_x}px;animation-delay:{_delay}s'>"
            f"{(lbl or '?')[:3].upper()}</div>"
        )
    if _balls:
        st.markdown(
            f"<div class='edge-tumbler-wrap'>"
            f"<div class='edge-tumbler'>" + "".join(_balls) + "</div>"
            f"<div class='edge-tumbler-label'>{_odds_lbl}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

# ---- Money rain renderer (#2) ----
if st.session_state.pop("money_rain", False):
    import random as _rng
    _bills = []
    for i in range(34):
        _left = _rng.randint(0, 100)
        _dur = round(_rng.uniform(2.4, 4.4), 2)
        _delay = round(_rng.uniform(0, 1.6), 2)
        _emoji = _rng.choice(["💵", "💰", "💸", "🤑", "💵", "💵"])
        _bills.append(
            f"<div class='bill' style='left:{_left}vw;"
            f"animation-duration:{_dur}s;animation-delay:{_delay}s'>"
            f"{_emoji}</div>"
        )
    _label = st.session_state.pop("money_rain_label", "BIG WIN")
    st.markdown(
        f"<div class='edge-money-banner'>{_label}</div>"
        f"<div class='edge-money-rain'>" + "".join(_bills) + "</div>",
        unsafe_allow_html=True,
    )

if not st.session_state.get("splash_shown"):
    st.session_state["splash_shown"] = True
    st.markdown(
        "<div id='edge-splash'>"
        "<div class='edge-splash-logo'>EDGE</div>"
        "<div class='edge-splash-tag'>SHARP. FAST. RUTHLESS.</div>"
        "</div>",
        unsafe_allow_html=True,
    )

# ---- iOS Siri / URL deeplink prefill (#75) ----
try:
    _qp = dict(st.query_params)
except Exception:
    _qp = {}
if _qp.get("addBet") or _qp.get("desc"):
    try:
        _d_desc = _qp.get("addBet") or _qp.get("desc") or ""
        _d_book = _qp.get("book") or "DraftKings"
        _d_odds = int(float(_qp.get("odds") or -110))
        _d_stake = float(_qp.get("stake") or 5)
        queue_prefill_bet(_d_desc, _d_book, _d_odds, _d_stake)
        try:
            st.query_params.clear()
        except Exception:
            pass
        st.toast("Bet prefilled from shortcut - check the Bankroll tab.")
    except Exception:
        pass

with st.sidebar:
    _ulabel = st.session_state.get("edge_user_label", "default")
    st.markdown(
        f"<div style='font-size:.78rem;color:#9CA3AF;margin-bottom:4px'>"
        f"Signed in as <b style='color:#F3F4F6'>{_ulabel}</b></div>",
        unsafe_allow_html=True,
    )
    if st.button("Sign out", key="signout_btn", use_container_width=True):
        for _k in ("edge_user", "edge_user_label", "splash_shown"):
            st.session_state.pop(_k, None)
        st.rerun()

    # ---- iOS Siri shortcut card (#75) ----
    with st.expander("iOS Siri shortcut", expanded=False):
        _app_url = ""
        try:
            _app_url = (st.context.headers.get("origin")
                        or st.context.headers.get("host") or "")
            if _app_url and not _app_url.startswith("http"):
                _app_url = "https://" + _app_url
        except Exception:
            pass
        if not _app_url:
            _app_url = "https://YOUR-APP.streamlit.app"
        _siri_url = (
            f"{_app_url}/?addBet=Lakers+ML"
            f"&book=DraftKings&odds=-110&stake=5"
        )
        st.markdown(
            f"""<div class='edge-siri'>
Tell Siri "Hey Siri, log a bet" and it pre-fills the Add Bet form.
<br><br><b>Setup once on iPhone:</b><br>
1. Open <b>Shortcuts</b> app, tap the <b>+</b><br>
2. Add action: <b>Open URLs</b><br>
3. Paste this URL template (edit the bet text before saving, or use
   "Ask Each Time" tokens for prompt-on-run):
<code>{_siri_url}</code>
4. Tap <b>Add to Siri</b>, name it "Log a bet". Done.<br><br>
Tapping the shortcut opens this app and auto-fills the Add Bet form on the
Bankroll tab. Params: <code>addBet</code>, <code>book</code>,
<code>odds</code>, <code>stake</code>.
</div>""",
            unsafe_allow_html=True,
        )
    # ---- Game-day theme music (#85) - YouTube + DB + localStorage ----
    with st.expander("Game-day theme music", expanded=False):
        # Default = the user-picked YouTube video for each team's fight song.
        _DEFAULTS = {
            "Alabama Crimson Tide": (
                "Yea Alabama - Fight Song",
                "yea+alabama+million+dollar+band+fight+song",
                "5BxxbTPoWWY",
            ),
            "Tennessee Volunteers": (
                "Rocky Top - Fight Song",
                "rocky+top+pride+of+the+southland+band+fight+song",
                "K6jImkLDzlY",
            ),
        }
        _default_label, _search_q, _default_vid = _DEFAULTS.get(
            _theme_name,
            ("Lo-fi sports trading beats", "lofi+sports+trading",
             "jfKfPfyJRdk"),
        )
        _search_url = (
            f"https://www.youtube.com/results?search_query={_search_q}"
        )
        _default_embed = f"https://www.youtube.com/embed/{_default_vid}"

        # Persistence key (per theme)
        _db_key = f"music_url::{_theme_name}"

        # Bootstrap from query-param (set by localStorage JS below)
        # so we can hydrate DB the first time after a fresh login.
        try:
            _qp = st.query_params
            _seed = _qp.get("edge_seed_music")
            if _seed:
                if not db_get_kv(_db_key):
                    db_set_kv(_db_key, _seed)
                try:
                    del st.query_params["edge_seed_music"]
                except Exception:
                    pass
        except Exception:
            pass

        # Saved URL from DB (per-user via _current_user scope)
        _saved_url = db_get_kv(_db_key, "") or ""

        def _save_music_url():
            _v = (st.session_state.get(
                f"music_input_{_theme_name}", "") or ""
            ).strip()
            try:
                db_set_kv(_db_key, _v)
            except Exception:
                pass

        st.caption(
            f"Default for this theme: **{_default_label}**. "
            "Paste any YouTube link below and it sticks - saved to your "
            "account *and* mirrored to your browser, so it survives "
            "sign-out, refresh, even closing the tab."
        )

        _user_url = st.text_input(
            "YouTube URL (optional)",
            value=_saved_url,
            key=f"music_input_{_theme_name}",
            placeholder="https://www.youtube.com/watch?v=...",
            on_change=_save_music_url,
            help="Press Enter or click away to save.",
        )

        def _yt_id(url):
            import re as _re
            if not url:
                return None
            m = _re.search(
                r"(?:v=|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})",
                url,
            )
            return m.group(1) if m else None

        _vid = _yt_id(_user_url)
        _base_embed = (
            f"https://www.youtube.com/embed/{_vid}" if _vid
            else _default_embed
        )
        # Autoplay when on a team theme; loop for ambience
        _ap_id = _vid or _default_vid
        _sep = "&" if "?" in _base_embed else "?"
        _embed_src = (
            f"{_base_embed}{_sep}autoplay=1&playsinline=1"
            f"&loop=1&playlist={_ap_id}"
            if _theme_name in ("Alabama Crimson Tide",
                               "Tennessee Volunteers")
            else _base_embed
        )
        st.markdown(
            f"<iframe width='100%' height='200' "
            f"src='{_embed_src}' "
            f"title='EDGE theme music' frameborder='0' "
            f"allow='accelerometer; autoplay; clipboard-write; "
            f"encrypted-media; gyroscope; picture-in-picture' "
            f"allowfullscreen "
            f"style='border-radius:10px;border:1px solid "
            f"rgba(255,255,255,.08);'></iframe>",
            unsafe_allow_html=True,
        )

        # Status pill so user knows where it's persisted
        _is_pinned = st.session_state.get("edge_user", "default") != "default"
        _status = (
            "Saved to your account + this browser"
            if _is_pinned and _saved_url
            else ("Saved to this browser (sign in with PIN to sync "
                  "across devices)" if _saved_url
                  else "Using default - paste a URL to save")
        )
        st.caption(f":material/save: {_status}")
        st.caption(
            f"[Browse {_default_label} on YouTube]({_search_url}) - "
            "find your favorite version, copy the URL, paste it above."
        )

        # ---- localStorage mirror + bootstrap ----
        # 1. On every load: if URL is set, write to localStorage.
        # 2. If DB has nothing AND localStorage has a saved URL,
        #    push it back via query param so Python rehydrates the DB.
        from streamlit.components.v1 import html as _ls_html
        import json as _json
        _ls_html(
            f"""
<script>
(function() {{
  try {{
    const KEY = "edge_music_url::{_theme_name}";
    const SAVED = {_json.dumps(_saved_url)};
    if (SAVED) {{
      localStorage.setItem(KEY, SAVED);
    }} else {{
      const fromLS = localStorage.getItem(KEY);
      if (fromLS) {{
        const url = new URL(window.parent.location.href);
        if (!url.searchParams.has("edge_seed_music")) {{
          url.searchParams.set("edge_seed_music", fromLS);
          window.parent.location.replace(url.toString());
        }}
      }}
    }}
  }} catch(e) {{}}
}})();
</script>
            """,
            height=0,
        )
    st.markdown("---")
    st.markdown("### Bankroll")

    def _kv_float(key, default):
        try:
            return float(db_get_kv(key, str(default)) or default)
        except Exception:
            return float(default)

    def _kv_int(key, default):
        try:
            return int(float(db_get_kv(key, str(default)) or default))
        except Exception:
            return int(default)

    _saved_bk = _kv_float("cfg_bankroll", 500.0)
    _saved_min = _kv_float("cfg_min_bet", 1.0)
    _saved_max = _kv_float("cfg_max_bet", max(10.0, _saved_min))
    _saved_cap = _kv_int("cfg_daily_cap_pct", 20)
    _saved_goal = _kv_float(
        "cfg_bankroll_goal", max(1000.0, _saved_bk * 2.0)
    )

    bankroll = st.number_input(
        "Bankroll ($)", min_value=10.0, value=_saved_bk, step=10.0,
    )
    min_bet = st.number_input(
        "Min bet ($)", min_value=1.0, value=_saved_min, step=1.0,
    )
    max_bet = st.number_input(
        "Max bet ($)", min_value=min_bet,
        value=max(min_bet, _saved_max), step=1.0,
    )
    daily_cap_pct = st.slider(
        "Daily exposure cap (% of bankroll)", 5, 100, _saved_cap,
    )
    bankroll_goal = st.number_input(
        "Bankroll goal ($)", min_value=float(bankroll) + 1.0,
        value=max(float(bankroll) + 1.0, _saved_goal), step=50.0,
        help="Used by the Goal Progress thermometer on the Bankroll tab.",
    )

    # Persist any change so it survives sign-out / new session
    try:
        if abs(bankroll - _saved_bk) > 1e-6:
            db_set_kv("cfg_bankroll", str(bankroll))
        if abs(min_bet - _saved_min) > 1e-6:
            db_set_kv("cfg_min_bet", str(min_bet))
        if abs(max_bet - _saved_max) > 1e-6:
            db_set_kv("cfg_max_bet", str(max_bet))
        if int(daily_cap_pct) != _saved_cap:
            db_set_kv("cfg_daily_cap_pct", str(int(daily_cap_pct)))
        if abs(bankroll_goal - _saved_goal) > 1e-6:
            db_set_kv("cfg_bankroll_goal", str(bankroll_goal))
    except Exception:
        pass

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
    sfx_on = st.checkbox(
        "Sound effects",
        value=st.session_state.get("sfx_on", False),
        help="Plays a quick chime on win / loss / new all-time high.",
    )
    st.session_state["sfx_on"] = sfx_on

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

# ---- Big team-theme toggle bar (above EDGE title) ----
st.markdown(
    """
<style>
.edge-theme-row { margin: 4px 0 6px; }
.edge-theme-row .stButton > button {
  width: 100%; padding: 10px 4px; border-radius: 10px;
  font-family: "Bebas Neue","Oswald",sans-serif;
  letter-spacing: .14em; font-size: .95rem;
  border: 1px solid rgba(255,255,255,.10);
  transition: transform .12s ease, box-shadow .15s ease;
}
.edge-theme-row .stButton > button:hover { transform: translateY(-2px); }
.edge-theme-default  .stButton > button { background:#0F0F0F; color:#F3F4F6;
  border-color: rgba(158,27,50,.5); }
.edge-theme-bama     .stButton > button { background:#9E1B32; color:#fff;
  border-color:#9E1B32; box-shadow: 0 0 14px rgba(158,27,50,.5); }
.edge-theme-vols     .stButton > button { background:#FF8200; color:#1a0d00;
  border-color:#FF8200; box-shadow: 0 0 14px rgba(255,130,0,.5);
  font-weight: 800; }
.edge-theme-active   .stButton > button {
  outline: 2px solid #fff; outline-offset: 2px;
}
</style>
    """,
    unsafe_allow_html=True,
)
st.markdown("<div class='edge-theme-row'></div>", unsafe_allow_html=True)
_tcol1, _tcol2, _tcol3 = st.columns(3)
def _helmet_svg(body, stripe, letter, letter_color):
    return (
        "<svg viewBox='0 0 80 60' width='56' height='42' "
        "style='display:block;margin:0 auto 4px'>"
        # Helmet shell
        f"<path d='M10 38 Q10 12 40 12 Q66 12 70 32 L70 44 "
        f"Q70 52 60 52 L20 52 Q10 52 10 44 Z' "
        f"fill='{body}' stroke='#000' stroke-width='1.5'/>"
        # Center stripe
        f"<path d='M22 14 Q40 8 62 16 L62 20 Q40 14 22 18 Z' "
        f"fill='{stripe}' opacity='.85'/>"
        # Facemask
        "<path d='M8 36 L26 36 M8 42 L24 42 M8 48 L24 48' "
        "stroke='#bbb' stroke-width='2' fill='none'/>"
        "<path d='M26 32 L26 52' stroke='#bbb' stroke-width='2'/>"
        # Earhole
        "<circle cx='34' cy='38' r='3' fill='#000' opacity='.55'/>"
        # Letter logo
        f"<text x='48' y='38' font-family='Bebas Neue,Oswald,sans-serif' "
        f"font-size='18' font-weight='900' fill='{letter_color}' "
        f"text-anchor='middle' style='letter-spacing:.04em'>{letter}</text>"
        "</svg>"
    )

_helmet_default = (
    "<svg viewBox='0 0 80 60' width='56' height='42' "
    "style='display:block;margin:0 auto 4px'>"
    "<rect x='14' y='18' width='52' height='28' rx='4' "
    "fill='#0F0F0F' stroke='#9E1B32' stroke-width='2'/>"
    "<text x='40' y='38' font-family='Bebas Neue,Oswald,sans-serif' "
    "font-size='16' font-weight='900' fill='#9E1B32' "
    "text-anchor='middle'>EDGE</text>"
    "</svg>"
)
_helmet_bama = _helmet_svg("#9E1B32", "#FFFFFF", "A", "#FFFFFF")
_helmet_vols = _helmet_svg("#FF8200", "#FFFFFF", "T", "#FFFFFF")

_btn_specs = [
    (_tcol1, "Bloomberg",            "DEFAULT",        "edge-theme-default", _helmet_default),
    (_tcol2, "Alabama Crimson Tide", "ROLL TIDE",      "edge-theme-bama",    _helmet_bama),
    (_tcol3, "Tennessee Volunteers", "GO BIG ORANGE",  "edge-theme-vols",    _helmet_vols),
]
for _col, _theme_id, _label, _cls, _helmet in _btn_specs:
    with _col:
        _active = (_theme_name == _theme_id)
        st.markdown(
            f"<div class='{_cls} "
            f"{'edge-theme-active' if _active else ''}'>"
            f"{_helmet}",
            unsafe_allow_html=True,
        )
        if st.button(
            ("ACTIVE - " if _active else "") + _label,
            key=f"theme_pill_{_theme_id}",
            use_container_width=True,
        ):
            st.session_state["_pending_theme"] = _theme_id
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

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


@st.cache_data(ttl=120, show_spinner=False)
def _ticker_picks():
    rows = []
    try:
        rows = all_picks(
            None, "team",
            leagues_filter=("NBA", "NFL", "MLB", "NHL"),
        )
    except Exception:
        return []
    rows.sort(key=lambda r: r.get("edge_bps") or 0, reverse=True)
    return rows[:12]


# ---- Stock-ticker line-move strip (#19) ----
try:
    _tk = _ticker_picks()
except Exception:
    _tk = []
_tk_items = []
if _tk:
    for r in _tk:
        try:
            _pk = (
                f"{r.get('matchup','')} {r.get('market','')} "
                f"{r.get('pick','')}"
            )
            _pr = format_american(int(r.get("price") or -110))
            _eb = format_bps(r.get("edge_bps") or 0)
            _bk = r.get("book", "")
            _lg = r.get("league", "")
            _tk_items.append(
                f"<span class='edge-ticker-item'>"
                f"<span class='lg'>{_lg}</span>"
                f"<span class='pk'>{_pk}</span>"
                f"<span class='pr'>{_pr}</span>"
                f"<span class='eb'>{_eb}</span>"
                f"<span class='bk'>{_bk}</span>"
                f"<span class='sep'>|</span>"
                f"</span>"
            )
        except Exception:
            continue
if not _tk_items:
    for _msg in (
        "EDGE LIVE", "SHARP MONEY", "BEST PRICE LOCKED",
        "DRAFTKINGS / FANDUEL / BET365",
        "PROPS GRADED AUTOMATICALLY",
        "ASK EDGE - YOUR AI BETTING DESK",
    ):
        _tk_items.append(
            f"<span class='edge-ticker-item'>"
            f"<span class='pk'>{_msg}</span>"
            f"<span class='sep'>|</span></span>"
        )
_track_html = "".join(_tk_items * 2)
st.markdown(
    f"<div class='edge-ticker'>"
    f"<div class='edge-ticker-track'>{_track_html}</div>"
    f"</div>",
    unsafe_allow_html=True,
)

(
    tab_picks, tab_props, tab_pp_board, tab_parlay,
    tab_board, tab_bank, tab_ai,
) = st.tabs(
    ["Suggested Picks", "PrizePicks Picks", "PrizePicks Board",
     "Parlay Builder", "Odds Board", "Bankroll", "Ask Edge"]
)

with tab_picks:
    _wr_open = [b for b in db_load_bets() if b["status"] == "open"]
    _wr_html = war_room_banner(_wr_open, leagues_filter)
    if _wr_html:
        st.markdown(_wr_html, unsafe_allow_html=True)

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
            card_style = card_style_for_pick(r["matchup"])
            card = (
                f"<div class='pick-card' style=\"{card_style}\">"
                "<div class='pick-row'>"
                "<div>"
                f"<div class='pick-title'>{matchup_badges(r['matchup'])} "
                f"<span class='muted' style='font-size:.85rem;'>"
                f"&nbsp;&nbsp;{r['league']} - {r['market']}</span></div>"
                f"<div class='pick-sub' style='margin-top:4px;'>Pick: "
                f"<b style='color:#F8FAFC'>{r['pick']}</b> "
                f"@ <span class='{tick_class_for(pick_key_team(r), r['best_dec'])}'>"
                f"{format_american(r['price'])}</span> on {book_badge(r['book'])} - "
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
            if capped > 0:
                lock_key = f"lock_team_{r['league']}_{r['matchup']}_{r['pick']}"
                why_key = f"why_team_{r['league']}_{r['matchup']}_{r['pick']}"
                bcols = st.columns([1, 1, 5])
                if bcols[0].button(
                    "Lock it in", key=lock_key, type="secondary",
                ):
                    queue_prefill_bet(
                        f"{r['pick']} ({r['market']}) - "
                        f"{r['matchup']} {r['league']}",
                        r["book"], r["price"], capped,
                    )
                if bcols[1].button(
                    "Why?", key=f"btn_{why_key}", type="secondary",
                    help="Ask Edge AI to explain this pick",
                ):
                    with st.spinner("Edge is analyzing..."):
                        st.session_state[why_key] = ai_chat(
                            f"In 3-4 short sentences, explain the EDGE on this "
                            f"pick: {r['pick']} ({r['market']}) for "
                            f"{r['matchup']} ({r['league']}) at "
                            f"{format_american(r['price'])} on {r['book']}. "
                            f"Edge: {format_bps(r['edge_bps'])}, "
                            f"{r['books_count']} books in consensus. "
                            f"Suggested stake ${capped:.2f} on "
                            f"${bankroll:.2f} bankroll. Be concrete about "
                            f"why the price is mispriced and what would "
                            f"have to go right.",
                            "",
                        )
                if st.session_state.get(why_key):
                    st.info(st.session_state[why_key])
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
            card_style = card_style_for_pick(r.get("matchup", ""))
            card = (
                f"<div class='pick-card' style=\"{card_style}\">"
                "<div class='pick-row'>"
                "<div>"
                f"<div class='pick-title'>"
                f"{player_avatar(r['player'], r.get('matchup', ''))}"
                f"{r['player']} - "
                f"<span class='muted'>{r['stat']} {r['side']} {r['line']:g}</span>"
                f"{trend_html}</div>"
                f"<div class='pick-sub' style='margin-top:4px;'>"
                f"{matchup_badges(r['matchup'])}"
                f"<span style='margin:0 8px;' class='muted'>{r['league']}</span>"
                f"best @ <span class='{tick_class_for(prop_key, r['best_dec'])}'>"
                f"{format_american(r['price'])}</span> on {book_badge(r['book'])} - "
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
            if stake > 0:
                lock_key = f"lock_prop_{prop_key}"
                why_key = f"why_prop_{prop_key}"
                bcols = st.columns([1, 1, 5])
                if bcols[0].button(
                    "Lock it in", key=lock_key, type="secondary",
                ):
                    queue_prefill_bet(
                        f"{r['player']} {r['stat']} {r['side']} "
                        f"{r['line']:g} - {r['matchup']} {r['league']}",
                        r["book"], r["price"], stake,
                    )
                if bcols[1].button(
                    "Why?", key=f"btn_{why_key}", type="secondary",
                    help="Ask Edge AI to explain this prop",
                ):
                    with st.spinner("Edge is analyzing..."):
                        st.session_state[why_key] = ai_chat(
                            f"In 3-4 short sentences, explain the EDGE on "
                            f"this player prop: {r['player']} {r['stat']} "
                            f"{r['side']} {r['line']:g} in {r['matchup']} "
                            f"({r['league']}) at "
                            f"{format_american(r['price'])} on {r['book']}. "
                            f"Edge: {format_bps(r['edge_bps'])} across "
                            f"{r['books_count']} books. Suggested stake "
                            f"${stake:.2f}. Be concrete about usage rate, "
                            f"matchup, recent form, or line shopping.",
                            "",
                        )
                if st.session_state.get(why_key):
                    st.info(st.session_state[why_key])

    # ---- Same-Game Parlay (SGP) builder (#30) ----
    st.markdown("---")
    st.subheader("Same-Game Parlay builder")
    st.caption(
        "Pick 2-4 props from the SAME game. Books treat them as one ticket. "
        "Combined odds shown assume independence - real SGP prices are "
        "shorter because legs in one game are correlated."
    )
    if not prop_rows:
        st.info("Run a board scan above to populate props.")
    else:
        _games = sorted({r["matchup"] for r in prop_rows})
        _sgp_game = st.selectbox(
            "Game", _games, key="sgp_game_pick",
        )
        _sgp_pool = [r for r in prop_rows if r["matchup"] == _sgp_game]
        _sgp_labels = [
            f"{r['player']} {r['stat']} {r['side']} {r['line']:g} "
            f"@ {format_american(r['price'])} ({r['book']})"
            for r in _sgp_pool
        ]
        _sgp_choices = st.multiselect(
            "Pick 2-4 legs", _sgp_labels,
            max_selections=4, key="sgp_legs_pick",
        )
        if len(_sgp_choices) >= 2:
            _picked = [
                _sgp_pool[i] for i, lb in enumerate(_sgp_labels)
                if lb in _sgp_choices
            ]
            _decs = [american_to_decimal(int(r["price"])) for r in _picked]
            _combined = 1.0
            for d in _decs:
                _combined *= d
            if _combined > 2:
                _combined_am = int(round((_combined - 1) * 100))
                _combined_am_str = f"+{_combined_am}"
            else:
                _combined_am = int(round(-100 / max(0.001, _combined - 1)))
                _combined_am_str = f"{_combined_am}"
            _sgp_stake = st.number_input(
                "SGP stake ($)", min_value=float(min_bet),
                max_value=float(max_bet), value=float(min_bet),
                step=1.0, key="sgp_stake_in",
            )
            _to_win = _sgp_stake * (_combined - 1.0)
            _book_set = {r["book"] for r in _picked}
            st.markdown(
                f"<div style='font-size:.95rem;margin:8px 0'>"
                f"Combined (independence): "
                f"<b style='color:#10B981'>{_combined_am_str}</b> "
                f"&middot; Decimal <b>{_combined:.2f}</b> "
                f"&middot; Stake ${_sgp_stake:.2f} -> "
                f"To win <b style='color:#10B981'>${_to_win:.2f}</b>"
                f"</div>",
                unsafe_allow_html=True,
            )
            if len(_book_set) > 1:
                st.markdown(
                    "<div class='edge-sgp-warn'>WARNING: legs span "
                    f"<b>{len(_book_set)}</b> different books "
                    f"({', '.join(sorted(_book_set))}). A real Same-Game "
                    "Parlay must be built at one sportsbook - re-pick all "
                    "legs from the same book to actually place this.</div>",
                    unsafe_allow_html=True,
                )
            st.markdown(
                "<div class='edge-sgp-warn'>Correlation warning: "
                "props on the same game are correlated (e.g. QB pass yds "
                "OVER + WR rec yds OVER). Books shorten SGP prices to "
                "account for this. Expected real payout is "
                "<b>10-35% lower</b> than the independence number above.</div>",
                unsafe_allow_html=True,
            )
            _sgp_desc = "SGP: " + " + ".join([
                f"{r['player']} {r['stat']} {r['side']} {r['line']:g}"
                for r in _picked
            ]) + f" - {_sgp_game}"
            if st.button(
                "Lock in SGP", key="sgp_lock_btn", type="secondary",
            ):
                _book_for_log = (
                    list(_book_set)[0] if len(_book_set) == 1
                    else "DraftKings"
                )
                queue_prefill_bet(
                    _sgp_desc, _book_for_log, _combined_am, _sgp_stake,
                )
        elif _sgp_choices:
            st.info("Pick at least 2 legs.")

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
                st.session_state["tumbler"] = True
                st.session_state["tumbler_labels"] = [
                    (l.get("pick") or l.get("matchup") or "?")[:3]
                    for l in legs
                ]
                st.session_state["tumbler_odds"] = (
                    f"{format_american(combined_am)} - "
                    f"PAYS ${profit:,.0f}"
                )
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

    # ---- PGA leaderboard (#38) ----
    with st.expander("PGA leaderboard (live)", expanded=False):
        _pga, _pga_err = fetch_pga_leaderboard()
        if _pga_err:
            st.caption(f"Could not reach ESPN golf feed: {_pga_err}")
        elif not _pga or not _pga.get("rows"):
            st.caption("No active PGA tournament right now.")
        else:
            _rows_html = ""
            for r in _pga["rows"]:
                _sc = (r.get("score") or "E").strip()
                _cls = "score-up" if _sc.startswith("+") else (
                    "score-dn" if _sc.startswith("-") else ""
                )
                _rows_html += (
                    f"<tr><td>{r.get('pos','-')}</td>"
                    f"<td>{r.get('name','-')}</td>"
                    f"<td class='{_cls}'>{_sc}</td>"
                    f"<td>{r.get('thru','')}</td></tr>"
                )
            st.markdown(
                f"<div class='edge-pga'>"
                f"<h4>{_pga['name']} &middot; {_pga.get('round','')}</h4>"
                f"<table>"
                f"<tr><th>Pos</th><th>Player</th>"
                f"<th>Score</th><th>Thru</th></tr>"
                f"{_rows_html}"
                f"</table>"
                f"</div>",
                unsafe_allow_html=True,
            )
            st.caption(
                "Live from ESPN free golf feed. Cross-reference with "
                "outright winner / top-5 / top-10 markets in your sportsbook. "
                "DraftKings/FanDuel daily-fantasy salaries are not exposed via "
                "a public API; use this leaderboard alongside their lobby."
            )

    # ---- Live scoreboard strip (#33) ----
    try:
        _today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _live = fetch_finals(league_id, _today_iso) or []
    except Exception:
        _live = []
    if _live:
        _cards = []
        for _g in _live[:24]:
            try:
                _away = str(_g.get("away") or "AWAY")[:14]
                _home = str(_g.get("home") or "HOME")[:14]
                _as = _g.get("away_score")
                _hs = _g.get("home_score")
                _stt = (_g.get("status") or "").upper()
                _live_cls = "live" if any(
                    k in _stt for k in ("IN", "LIVE", "Q", "HALF", "PROGRESS")
                ) else ""
                _cards.append(
                    f"<div class='edge-score-card {_live_cls}'>"
                    f"<div class='lg'>{league_id}</div>"
                    f"<div class='row'><span>{_away}</span>"
                    f"<span class='sc'>{_as if _as is not None else '-'}</span></div>"
                    f"<div class='row'><span>{_home}</span>"
                    f"<span class='sc'>{_hs if _hs is not None else '-'}</span></div>"
                    f"<div class='st'>{_stt or 'SCHEDULED'}</div>"
                    f"</div>"
                )
            except Exception:
                continue
        if _cards:
            st.markdown(
                "<div class='edge-scorestrip'>" + "".join(_cards) + "</div>",
                unsafe_allow_html=True,
            )

    events, warn = get_board(league_id, books_filter)
    if warn:
        st.warning(warn)
    if not events:
        st.info("No events on the board.")

    # ---- Update lava-lamp pulse from current best edge (#22) ----
    try:
        _max_e = max(
            (
                _oc.edge_bps for _ev in (events or [])
                for _m in _ev.markets for _oc in _m.outcomes
                if _oc.edge_bps is not None
            ),
            default=0,
        )
        st.session_state["edge_pulse"] = float(_max_e)
    except Exception:
        pass

    # ---- Fight Card: highest-edge marquee matchup (#4) ----
    _best_ev = None
    _best_edge = -1e9
    _best_pick_label = ""
    _best_price = None
    _best_total = None
    for _ev in events or []:
        for _m in _ev.markets:
            for _oc in _m.outcomes:
                if _oc.edge_bps is not None and _oc.edge_bps > _best_edge:
                    _best_edge = _oc.edge_bps
                    _best_ev = _ev
                    _best_pick_label = _pick_label(_oc, _m.type)
                    _best_price = _oc.best.price_american if _oc.best else None
                if "total" in (_m.type or "").lower() and _oc.best:
                    try:
                        _line = getattr(_oc, "line", None) or getattr(_oc, "point", None)
                        if _line:
                            _best_total = _line
                    except Exception:
                        pass
    if _best_ev and _best_edge > 0:
        _ml_a = _ml_h = "-"
        for _m in _best_ev.markets:
            if "moneyline" in (_m.type or "").lower() or _m.type.lower() == "h2h":
                for _oc in _m.outcomes:
                    if _oc.best:
                        nm = (_oc.name or "").lower()
                        if (_best_ev.away or "").lower() in nm:
                            _ml_a = format_american(_oc.best.price_american)
                        elif (_best_ev.home or "").lower() in nm:
                            _ml_h = format_american(_oc.best.price_american)
        _tot_html = (
            f"Total {_best_total} &nbsp;&middot;&nbsp; "
            if _best_total else ""
        )
        _price_html = (
            format_american(_best_price) if _best_price is not None else "-"
        )
        st.markdown(
            f"""
<div class='edge-fight-card'>
  <div class='edge-fight-banner'>MARQUEE - TONIGHT</div>
  <div class='edge-fight-grid'>
    <div class='edge-fight-side'>
      <div class='nm'>{_best_ev.away}</div>
      <div class='rec'>AWAY</div>
      <div class='ml'>ML {_ml_a}</div>
    </div>
    <div class='edge-fight-vs'>VS</div>
    <div class='edge-fight-side'>
      <div class='nm'>{_best_ev.home}</div>
      <div class='rec'>HOME</div>
      <div class='ml'>ML {_ml_h}</div>
    </div>
  </div>
  <div class='edge-fight-tot'>
    {_tot_html}Edge play: <b style='color:#10B981'>{_best_pick_label}</b>
    @ {_price_html} &nbsp;&middot;&nbsp; {format_bps(_best_edge)}
  </div>
</div>
""",
            unsafe_allow_html=True,
        )
    for ev in events:
        with st.container(border=True):
            title = (
                f"### {ev.away} @ {ev.home}  "
                f"<span class='muted' style='font-size:.8rem'>{ev.start}</span>"
            )
            st.markdown(title, unsafe_allow_html=True)
            inj_html = render_injuries_for_game(league_id, ev.away, ev.home)
            if inj_html:
                st.markdown(inj_html, unsafe_allow_html=True)
            _meta_pills = []
            if league_id in ("NBA", "NFL"):
                try:
                    _rc_date = (ev.start or "")[:10] or datetime.now(
                        timezone.utc
                    ).strftime("%Y-%m-%d")
                    _ref = fetch_ref_crew(
                        league_id, _rc_date, ev.away, ev.home,
                    )
                except Exception:
                    _ref = None
                if _ref:
                    _rn, _rt, _rnote = _ref
                    _t_cls = {
                        "over": "tilt-over", "under": "tilt-under",
                    }.get(_rt, "tilt-neut")
                    _t_label = {
                        "over": "OVER tilt", "under": "UNDER tilt",
                    }.get(_rt, "Neutral")
                    _meta_pills.append(
                        f"<span class='edge-ref'>"
                        f"{'Ref' if league_id == 'NFL' else 'Crew Chief'} "
                        f"<b>{_rn}</b> &middot; "
                        f"<span class='{_t_cls}'>{_t_label}</span> &middot; "
                        f"<span style='color:#9CA3AF'>{_rnote}</span>"
                        f"</span>"
                    )
            if league_id == "NBA":
                _pa = _nba_pace_for(ev.away)
                _ph = _nba_pace_for(ev.home)
                if _pa and _ph:
                    _combined = (_pa + _ph) / 2.0
                    _delta = _combined - _NBA_LEAGUE_PACE_AVG
                    if _delta >= 1.5:
                        _pcls, _plbl = "fast", "FAST pace"
                    elif _delta <= -1.5:
                        _pcls, _plbl = "slow", "SLOW pace"
                    else:
                        _pcls, _plbl = "avg", "Avg pace"
                    _meta_pills.append(
                        f"<span class='edge-pace {_pcls}'>"
                        f"{_plbl} &middot; "
                        f"<b>{_combined:.1f}</b> poss/g "
                        f"({_delta:+.1f} vs lg) &middot; "
                        f"<span class='bar'></span>"
                        f"</span>"
                    )
            if _meta_pills:
                st.markdown(
                    "<div>" + "".join(_meta_pills) + "</div>",
                    unsafe_allow_html=True,
                )
            if league_id == "MLB":
                try:
                    _ump_date = (ev.start or "")[:10] or datetime.now(
                        timezone.utc
                    ).strftime("%Y-%m-%d")
                    _ump = fetch_mlb_ump(_ump_date, ev.away, ev.home)
                except Exception:
                    _ump = None
                if _ump:
                    _nm, _tilt, _note = _ump
                    _t_cls = {
                        "over": "tilt-over",
                        "under": "tilt-under",
                    }.get(_tilt, "tilt-neut")
                    _t_label = {
                        "over": "OVER tilt",
                        "under": "UNDER tilt",
                    }.get(_tilt, "Neutral")
                    st.markdown(
                        f"<div class='edge-ump'>HP Ump <b>{_nm}</b> "
                        f"&middot; <span class='{_t_cls}'>{_t_label}</span> "
                        f"&middot; <span style='color:#9CA3AF'>{_note}</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
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

            # ---- Alt-line shopper (#29) ----
            with st.expander("Alt lines (spreads & totals)", expanded=False):
                _raw_ev = (
                    _RAW_EVENT_CACHE.get((ev.away, ev.home, league_id))
                )
                _alts = _alt_lines_for_event(_raw_ev, books_filter, league_id)
                if not _alts["spread"] and not _alts["total"]:
                    st.caption(
                        "No alt-spread or alt-total markets returned from "
                        "your selected sportsbooks for this game."
                    )
                else:
                    if _alts["spread"]:
                        st.caption("Alt spreads")
                        _h = (
                            "<div class='edge-altwrap'><table>"
                            "<tr><th>Side</th><th>Line</th>"
                            "<th>Best book</th><th>Best price</th>"
                            "<th>Books</th></tr>"
                        )
                        for pt, sd, bk, am, n in _alts["spread"][:30]:
                            _line_str = f"{pt:+g}"
                            _h += (
                                f"<tr><td>{sd}</td>"
                                f"<td class='num'>{_line_str}</td>"
                                f"<td>{bk}</td>"
                                f"<td class='num best'>"
                                f"{format_american(am)}</td>"
                                f"<td class='num'>{n}</td></tr>"
                            )
                        _h += "</table></div>"
                        st.markdown(_h, unsafe_allow_html=True)
                    if _alts["total"]:
                        st.caption("Alt totals")
                        _h = (
                            "<div class='edge-altwrap'><table>"
                            "<tr><th>Side</th><th>Line</th>"
                            "<th>Best book</th><th>Best price</th>"
                            "<th>Books</th></tr>"
                        )
                        for pt, sd, bk, am, n in _alts["total"][:30]:
                            _h += (
                                f"<tr><td>{sd}</td>"
                                f"<td class='num'>{pt:g}</td>"
                                f"<td>{bk}</td>"
                                f"<td class='num best'>"
                                f"{format_american(am)}</td>"
                                f"<td class='num'>{n}</td></tr>"
                            )
                        _h += "</table></div>"
                        st.markdown(_h, unsafe_allow_html=True)

@st.cache_data(ttl=120, show_spinner=False)
def _h2h_leaderboard():
    """Query unscoped bets to compute per-user ROI / win% / streak."""
    _ensure_schema()
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT usr, status, stake, to_win, settled_at FROM bets "
        "WHERE status IN ('won','lost','push')"
    )
    rows = cur.fetchall()
    conn.close()
    by_user = {}
    for usr, status, stake, to_win, settled_at in rows:
        u = usr or "default"
        d = by_user.setdefault(
            u, {"won": 0, "lost": 0, "push": 0, "wagered": 0.0, "pnl": 0.0,
                 "events": []},
        )
        d[status] = d.get(status, 0) + 1
        try:
            stk = float(stake or 0)
            tw = float(to_win or 0)
        except Exception:
            stk = tw = 0
        d["wagered"] += stk
        if status == "won":
            d["pnl"] += tw
        elif status == "lost":
            d["pnl"] -= stk
        d["events"].append((settled_at or "", status))
    out = []
    for u, d in by_user.items():
        total = d["won"] + d["lost"] + d["push"]
        if total < 3:
            continue
        hit = (d["won"] / max(1, d["won"] + d["lost"])) * 100
        roi = (d["pnl"] / d["wagered"] * 100) if d["wagered"] > 0 else 0
        d["events"].sort(key=lambda x: x[0], reverse=True)
        streak_kind = streak_n = None
        for _, st_ in d["events"]:
            if st_ == "push":
                continue
            if streak_kind is None:
                streak_kind = st_
                streak_n = 1
            elif st_ == streak_kind:
                streak_n += 1
            else:
                break
        name = u.split("-")[0] if "-" in u else u
        out.append({
            "user": name, "uid": u, "total": total, "hit_pct": hit,
            "pnl": d["pnl"], "roi": roi, "wagered": d["wagered"],
            "streak": (streak_kind or "-", streak_n or 0),
        })
    out.sort(key=lambda r: r["roi"], reverse=True)
    return out


with tab_bank:
    bets = db_load_bets()
    today = datetime.now(timezone.utc).date().isoformat()

    # ---- Auto-grade open bets on tab load (throttled 5 min) ----
    try:
        import time as _time_ag
        _last_ag = float(st.session_state.get("_last_autograde_ts", 0) or 0)
        _open_for_ag = [b for b in bets if b["status"] == "open"]
        if _open_for_ag and (_time_ag.time() - _last_ag) > 300:
            st.session_state["_last_autograde_ts"] = _time_ag.time()
            with st.spinner("Auto-grading open bets from final scores..."):
                _ag_team = auto_grade_open_bets(_open_for_ag, leagues_filter)
                _open_for_ag2 = [
                    b for b in db_load_bets() if b["status"] == "open"
                ]
                _ag_prop = (
                    auto_grade_prop_bets(_open_for_ag2, leagues_filter)
                    if _open_for_ag2 else
                    {"won": 0, "lost": 0, "push": 0}
                )
            _ag_settled = (
                _ag_team["won"] + _ag_team["lost"] + _ag_team["push"]
                + _ag_prop["won"] + _ag_prop["lost"] + _ag_prop["push"]
            )
            if _ag_settled:
                st.toast(
                    f"Auto-graded {_ag_settled} bet(s) from final scores.",
                    icon="✅",
                )
                bets = db_load_bets()
    except Exception as _ag_err:
        st.caption(f"(Auto-grade skipped: {_ag_err})")

    # ---- H2H Leaderboard (#27) ----
    with st.expander("Leaderboard - all users on this book", expanded=False):
        lb = _h2h_leaderboard()
        if not lb:
            st.info(
                "Need at least 3 settled bets per user to rank. Settle some "
                "and refresh."
            )
        else:
            _me_uid = _current_user()
            html_rows = [
                "<table style='width:100%;font-size:.92rem;border-collapse:collapse'>"
                "<tr style='color:#9CA3AF;text-align:left;border-bottom:"
                "1px solid rgba(255,255,255,.08)'>"
                "<th style='padding:6px 8px'>#</th>"
                "<th style='padding:6px 8px'>User</th>"
                "<th style='padding:6px 8px'>Bets</th>"
                "<th style='padding:6px 8px'>Hit %</th>"
                "<th style='padding:6px 8px'>P&amp;L</th>"
                "<th style='padding:6px 8px'>ROI</th>"
                "<th style='padding:6px 8px'>Streak</th>"
                "</tr>"
            ]
            for i, r in enumerate(lb[:25], 1):
                pnl_color = (
                    GREEN if r["pnl"] > 0
                    else (RED if r["pnl"] < 0 else MUTED)
                )
                roi_color = (
                    GREEN if r["roi"] > 0
                    else (RED if r["roi"] < 0 else MUTED)
                )
                me = r["uid"] == _me_uid
                row_bg = (
                    "background:rgba(220,38,38,.08);" if me else ""
                )
                me_tag = (
                    " <span style='color:#DC2626;font-size:.7rem'>YOU</span>"
                    if me else ""
                )
                sk_kind, sk_n = r["streak"]
                sk_color = GREEN if sk_kind == "won" else (
                    RED if sk_kind == "lost" else MUTED
                )
                sk_label = (
                    f"<span style='color:{sk_color};font-weight:700'>"
                    f"{sk_n}{(sk_kind or '')[0].upper()}</span>"
                    if sk_kind and sk_kind != "-"
                    else "<span style='color:#6B7280'>-</span>"
                )
                html_rows.append(
                    f"<tr style='{row_bg}border-bottom:1px solid "
                    f"rgba(255,255,255,.04)'>"
                    f"<td style='padding:6px 8px;color:#9CA3AF'>{i}</td>"
                    f"<td style='padding:6px 8px'><b>{r['user']}</b>{me_tag}</td>"
                    f"<td style='padding:6px 8px'>{r['total']}</td>"
                    f"<td style='padding:6px 8px'>{r['hit_pct']:.1f}%</td>"
                    f"<td style='padding:6px 8px;color:{pnl_color};"
                    f"font-variant-numeric:tabular-nums'>"
                    f"${r['pnl']:+,.2f}</td>"
                    f"<td style='padding:6px 8px;color:{roi_color}'>"
                    f"{r['roi']:+.1f}%</td>"
                    f"<td style='padding:6px 8px'>{sk_label}</td>"
                    f"</tr>"
                )
            html_rows.append("</table>")
            st.markdown("".join(html_rows), unsafe_allow_html=True)
            st.caption(
                "Leaderboard ranks by ROI (min 3 settled bets). "
                "Streaks ignore pushes."
            )
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

    st.markdown(
        bankroll_thermometer(equity, bankroll, bankroll_goal),
        unsafe_allow_html=True,
    )
    st.markdown(
        weekly_report_card(bets, bankroll), unsafe_allow_html=True,
    )

    try:
        _ach_ath = float(db_get_kv("ath", str(bankroll)) or bankroll)
    except Exception:
        _ach_ath = bankroll
    st.markdown(
        achievements_html(
            compute_achievements(bets, equity, bankroll, _ach_ath)
        ),
        unsafe_allow_html=True,
    )

    # ---- Daily P&L waterfall (#25) ----
    with st.expander("Daily P&L waterfall (last 21 days)", expanded=True):
        try:
            import plotly.graph_objects as _go
            _daily = {}
            for _b in settled:
                _d = (_b.get("settled_at") or _b.get("date") or "")[:10]
                if not _d:
                    continue
                if _b["status"] == "won":
                    _delta = float(_b.get("to_win") or 0)
                elif _b["status"] == "lost":
                    _delta = -float(_b.get("stake") or 0)
                else:
                    _delta = 0.0
                _daily[_d] = _daily.get(_d, 0.0) + _delta
            if not _daily:
                st.caption("Settle some bets to see your daily P&L break out.")
            else:
                _days = sorted(_daily.keys())[-21:]
                _vals = [_daily[d] for d in _days]
                _running = 0.0
                _hover = []
                for v in _vals:
                    _running += v
                    _hover.append(
                        f"Day P&L: ${v:+.2f}<br>Running: ${_running:+.2f}"
                    )
                _fig = _go.Figure(_go.Waterfall(
                    x=_days, y=_vals,
                    measure=["relative"] * len(_vals),
                    text=[f"${v:+.0f}" for v in _vals],
                    textposition="outside",
                    hovertext=_hover, hoverinfo="text+x",
                    increasing={"marker": {"color": "#10B981"}},
                    decreasing={"marker": {"color": "#DC2626"}},
                    totals={"marker": {"color": "#F59E0B"}},
                    connector={"line": {
                        "color": "rgba(255,255,255,.18)", "width": 1,
                    }},
                ))
                _fig.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#F3F4F6", family="Inter, system-ui"),
                    height=380,
                    margin=dict(l=10, r=10, t=20, b=40),
                    xaxis=dict(
                        gridcolor="rgba(255,255,255,.04)",
                        tickfont=dict(size=10, color="#9CA3AF"),
                    ),
                    yaxis=dict(
                        gridcolor="rgba(255,255,255,.06)",
                        tickfont=dict(size=11, color="#9CA3AF"),
                        zerolinecolor="rgba(220,38,38,.4)", zerolinewidth=1,
                        tickprefix="$",
                    ),
                    showlegend=False,
                )
                st.plotly_chart(
                    _fig, use_container_width=True,
                    config={"displayModeBar": False},
                )
                st.caption(
                    f"Cumulative over window: "
                    f"${sum(_vals):+,.2f} across {len(_days)} days. "
                    "Green bars = winning days, red = losing days."
                )
        except ImportError:
            st.caption(
                "Add `plotly>=5.18` to requirements.txt to render the "
                "waterfall chart."
            )
        except Exception as _e:
            st.caption(f"Waterfall unavailable: {_e}")

    with st.expander("Bankroll forecaster (Monte-Carlo, 60 days)"):
        forecast_days = st.slider(
            "Days to project", 14, 120, 60, 7, key="forecast_days",
        )
        fc = monte_carlo_forecast(
            bets, bankroll, equity, days_ahead=forecast_days,
        )
        if not fc:
            st.info(
                "Need at least 5 settled bets to forecast. Keep grinding."
            )
        else:
            fc_df = pd.DataFrame(fc["rows"])
            band = (
                alt.Chart(fc_df)
                .mark_area(opacity=0.25, color=GREEN)
                .encode(
                    x=alt.X("day:Q", title="Days from today"),
                    y=alt.Y("p10:Q", title="Equity ($)"),
                    y2="p90:Q",
                )
            )
            median_line = (
                alt.Chart(fc_df).mark_line(color="#FDE68A", strokeWidth=2)
                .encode(x="day:Q", y="p50:Q")
            )
            st.altair_chart(
                (band + median_line)
                .properties(height=220, background=PANEL),
                use_container_width=True,
            )
            f1, f2, f3, f4 = st.columns(4)
            f1.metric("Median (p50)", f"${fc['p50']:,.0f}",
                      delta=f"{((fc['p50'] - equity) / equity * 100):+.1f}%"
                      if equity else None)
            f2.metric("Pessimistic (p10)", f"${fc['p10']:,.0f}")
            f3.metric("Optimistic (p90)", f"${fc['p90']:,.0f}")
            f4.metric(
                "Edge / bet", f"${fc['edge_per_bet']:+.2f}",
                help=f"From {fc['sample_size']} settled bets, "
                f"~{fc['bets_per_day']:.1f} bets/day",
            )
            st.caption(
                "Simulates 600 random futures using your historical "
                "bet sizes and pacing. Wider band = more variance."
            )

    try:
        prev_ath = float(db_get_kv("ath", str(bankroll)) or bankroll)
    except Exception:
        prev_ath = bankroll
    if equity > prev_ath and equity > bankroll:
        db_set_kv("ath", f"{equity:.2f}")
        if not st.session_state.get("ath_seen") == round(equity, 2):
            st.session_state["ath_seen"] = round(equity, 2)
            st.balloons()
            st.markdown(
                f"<div class='ath-cannon'>NEW ALL-TIME HIGH "
                f"${equity:,.2f} <span class='ath-prev'>prev "
                f"${prev_ath:,.2f}</span></div>",
                unsafe_allow_html=True,
            )
            play_sound("ath")

    fx = st.session_state.pop("fx", None)
    if fx == "win":
        st.balloons()
        play_sound("win")
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
        play_sound("loss")
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
    pre = st.session_state.get("prefill", {})
    if pre:
        st.info(
            f"Pick queued from a Lock-it-in button. Review and click Add bet.",
            icon="🔒",
        )
    with st.form("log_bet", clear_on_submit=True):
        f = st.columns([2, 2, 1, 1, 1])
        desc = f[0].text_input(
            "Description", value=pre.get("desc", ""),
            placeholder="e.g. Lakers ML",
        )
        book = f[1].text_input(
            "Book", value=pre.get("book", ""),
            placeholder="draftkings / fanduel / bet365",
        )
        odds = f[2].number_input(
            "American odds", value=int(pre.get("odds", -110)), step=5,
        )
        stake = f[3].number_input(
            "Stake ($)", min_value=0.0,
            value=float(pre.get("stake", min_bet)), step=1.0,
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
            st.session_state.pop("prefill", None)
            st.rerun()

    st.subheader("Auto-grade open bets")
    ag_l, ag_r1, ag_r2 = st.columns([3, 1, 1])
    with ag_l:
        st.caption(
            "Team grader pulls final scores from ESPN for moneylines / spreads "
            "/ totals. Prop grader pulls player box scores and reads "
            "'Name OVER/UNDER 24.5 points' style descriptions."
        )
    with ag_r1:
        if st.button(
            "Grade teams", use_container_width=True, type="primary",
            key="auto_grade_btn",
        ):
            open_bets_for_grade = [b for b in bets if b["status"] == "open"]
            if not open_bets_for_grade:
                st.info("No open bets to grade.")
            else:
                with st.spinner("Fetching final scores..."):
                    res = auto_grade_open_bets(
                        open_bets_for_grade, leagues_filter,
                    )
                st.success(
                    f"Graded {res['won'] + res['lost'] + res['push']} of "
                    f"{res['total']} - won {res['won']}, lost {res['lost']}, "
                    f"push {res['push']}, skipped {res['skipped']}."
                )
                st.rerun()
    with ag_r2:
        if st.button(
            "Grade props", use_container_width=True,
            key="auto_grade_prop_btn",
        ):
            open_bets_for_grade = [b for b in bets if b["status"] == "open"]
            if not open_bets_for_grade:
                st.info("No open bets to grade.")
            else:
                with st.spinner("Pulling player box scores..."):
                    res = auto_grade_prop_bets(
                        open_bets_for_grade, leagues_filter,
                    )
                st.success(
                    f"Props: graded {res['won'] + res['lost'] + res['push']} "
                    f"of {res['total']} - won {res['won']}, lost {res['lost']}, "
                    f"push {res['push']}, skipped {res['skipped']}."
                )
                st.rerun()
    st.markdown("&nbsp;", unsafe_allow_html=True)

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
            try:
                if float(b.get("to_win", 0)) >= 3.0 * float(min_bet):
                    st.session_state["money_rain"] = True
                    st.session_state["money_rain_label"] = (
                        f"+${float(b['to_win']):,.0f} CASHED"
                    )
            except Exception:
                pass
            st.rerun()
        if cols[6].button("Loss", key=f"l{b['id']}"):
            db_settle_bet(b["id"], "lost")
            st.session_state["fx"] = "loss"
            st.rerun()
        if cols[7].button("Del", key=f"d{b['id']}"):
            db_delete_bet(b["id"])
            st.rerun()

    if settled:
        st.subheader("Bet history")
        hist_q = st.text_input(
            "Search description / book / status",
            placeholder="e.g. lebron, draftkings, won, lakers ml",
            key="hist_search",
        ).strip().lower()
        sorted_settled = sorted(
            settled, key=lambda x: x.get("settled_at") or "", reverse=True,
        )
        if hist_q:
            tokens = [t for t in hist_q.split() if t]
            filtered = [
                b for b in sorted_settled
                if all(
                    tok in (
                        f"{b.get('description', '')} {b.get('book', '')} "
                        f"{b.get('status', '')} {b.get('date', '')}"
                    ).lower()
                    for tok in tokens
                )
            ]
            st.caption(f"{len(filtered)} of {len(sorted_settled)} match.")
            shown = filtered[:50]
        else:
            shown = sorted_settled[:15]
        for b in shown:
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

with tab_ai:
    st.subheader("Ask Edge")
    st.caption(
        "Talk to a sharp-betting AI that can see today's picks, your "
        "bankroll, and your recent bets. Powered by OpenAI."
    )

    if not get_secret("OPENAI_API_KEY"):
        st.warning(
            "Add `OPENAI_API_KEY` to your Streamlit Cloud secrets to enable "
            "Ask Edge. (Manage app -> Settings -> Secrets, then reboot.)"
        )

    with st.expander("Voice mode (tap mic, speak, paste into chat)"):
        st.components.v1.html(
            """
<div style="font-family:ui-monospace,monospace;color:#E2E8F0;">
  <button id="edge-mic" style="
    background:#9E1B32;color:#fff;border:none;border-radius:999px;
    padding:14px 22px;font-weight:800;font-size:.95rem;cursor:pointer;
    box-shadow:0 0 18px rgba(158,27,50,.6);">
    TAP TO SPEAK
  </button>
  <span id="edge-mic-status" style="margin-left:14px;color:#94A3B8;
    font-size:.85rem;">Mic idle.</span>
  <div id="edge-mic-out" style="margin-top:14px;padding:12px 14px;
    background:#0F172A;border:1px solid rgba(255,255,255,.08);
    border-radius:10px;min-height:48px;color:#FDE68A;font-size:.95rem;">
    Your transcript will appear here.
  </div>
  <div style="margin-top:8px;color:#94A3B8;font-size:.78rem;">
    Auto-copied to clipboard. Paste into the chat box below with Cmd/Ctrl+V.
  </div>
</div>
<script>
(function(){
  const btn = document.getElementById('edge-mic');
  const status = document.getElementById('edge-mic-status');
  const out = document.getElementById('edge-mic-out');
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    btn.disabled = true;
    btn.style.opacity = .5;
    status.textContent = 'Speech recognition not supported in this browser. Try Chrome.';
    return;
  }
  let rec = null, listening = false, finalText = '';
  btn.addEventListener('click', () => {
    if (listening) { rec && rec.stop(); return; }
    finalText = '';
    rec = new SR();
    rec.lang = 'en-US';
    rec.continuous = true;
    rec.interimResults = true;
    rec.onstart = () => {
      listening = true;
      btn.textContent = 'STOP';
      btn.style.background = '#EF4444';
      status.textContent = 'Listening...';
    };
    rec.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalText += t + ' ';
        else interim += t;
      }
      out.textContent = (finalText + interim).trim() || 'Listening...';
    };
    rec.onerror = (e) => {
      status.textContent = 'Error: ' + e.error;
    };
    rec.onend = () => {
      listening = false;
      btn.textContent = 'TAP TO SPEAK';
      btn.style.background = '#9E1B32';
      const text = finalText.trim();
      if (text) {
        navigator.clipboard.writeText(text).then(
          () => status.textContent = 'Captured & copied. Paste below ->',
          () => status.textContent = 'Captured. (Clipboard blocked - select & copy manually.)'
        );
      } else {
        status.textContent = 'No speech captured.';
      }
    };
    rec.start();
  });
})();
</script>
            """,
            height=240,
        )

    if "ai_chat" not in st.session_state:
        st.session_state["ai_chat"] = []

    canned = [
        ("Top 3 risk-reward picks today", "Of the picks in CONTEXT, give me the 3 best risk/reward plays for a $500 bankroll, $1-$10 stakes. For each, give book, line, price, suggested stake, and a one-sentence why."),
        ("Build me a 3-leg PrizePicks Power Play", "Using the player props in CONTEXT, suggest a correlated 3-leg PrizePicks Power Play with the highest hit probability. Show each leg, combined probability, and EV vs the 5x payout."),
        ("Biggest leak in my recent bets", "Look at my recent bets in CONTEXT and tell me my biggest leak (sport, market, side, stake size, or book). Be specific and quantitative."),
        ("Should I tilt-fade today?", "Given my recent results in CONTEXT, am I on tilt? Should I lower my stakes today, take a break, or stay the course? Tactical answer."),
        ("Hedge any open bets?", "Look at the open bets in CONTEXT and the current odds. Recommend any hedges with stake amounts that lock in profit or cut variance."),
        ("What single pick should I make right now?", "Pick exactly one bet from CONTEXT for me to fire right now. Justify with edge, book, and stake. No hedging - one pick."),
    ]
    pcols = st.columns(3)
    canned_clicked = None
    for i, (label, prompt) in enumerate(canned):
        if pcols[i % 3].button(label, key=f"canned_{i}", use_container_width=True):
            canned_clicked = prompt

    for msg in st.session_state["ai_chat"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_input = st.chat_input("Ask anything about today's slate or your bets")

    pending = st.session_state.pop("pending_followup", None)
    prompt_to_send = pending or canned_clicked or user_input
    if prompt_to_send:
        ctx_lines = []
        ctx_lines.append(f"Bankroll: ${bankroll:,.2f}, equity: ${equity:,.2f}, daily exposure: ${today_exposure:,.2f} of ${daily_cap:,.2f} cap.")
        ctx_lines.append(f"Active leagues: {', '.join(sorted(leagues_filter))}. Books: {', '.join(sorted(books_filter))}.")
        ctx_lines.append("\nTOP TEAM PICKS (top 12 by edge):")
        for r in all_team_picks[:12]:
            ctx_lines.append(
                f"- {r['matchup']} ({r['league']}) {r['market']}: {r['pick']} "
                f"@ {format_american(r['price'])} on {r['book']} - "
                f"edge {format_bps(r['edge_bps'])}, {r['books_count']} books"
            )
        ctx_lines.append("\nTOP PROP PICKS (top 12 by edge):")
        for r in all_prop_picks[:12]:
            ctx_lines.append(
                f"- {r['player']} {r['stat']} {r['side']} {r['line']:g} "
                f"({r['matchup']}, {r['league']}) @ "
                f"{format_american(r['price'])} on {r['book']} - "
                f"edge {format_bps(r['edge_bps'])}"
            )
        open_b = [b for b in bets if b["status"] == "open"][:10]
        if open_b:
            ctx_lines.append("\nOPEN BETS:")
            for b in open_b:
                ctx_lines.append(
                    f"- {b['description']} @ {format_american(b['odds'])} "
                    f"on {b['book']}, ${b['stake']:.2f} -> "
                    f"${b['to_win']:.2f} potential"
                )
        recent = sorted(
            [b for b in bets if b["status"] in ("won", "lost")],
            key=lambda x: x.get("settled_at") or "", reverse=True,
        )[:15]
        if recent:
            ctx_lines.append("\nRECENT SETTLED BETS:")
            for b in recent:
                d = b["to_win"] if b["status"] == "won" else -b["stake"]
                ctx_lines.append(
                    f"- [{b['status'].upper()}] {b['description']} "
                    f"({b.get('book', '?')}, ${b['stake']:.2f}) "
                    f"P&L ${d:+.2f}"
                )
        context_text = "\n".join(ctx_lines)

        st.session_state["ai_chat"].append(
            {"role": "user", "content": prompt_to_send}
        )
        with st.chat_message("user"):
            st.markdown(prompt_to_send)
        with st.chat_message("assistant"):
            with st.spinner("Edge is thinking..."):
                reply = ai_chat(prompt_to_send, context_text)
            st.markdown(reply)
        st.session_state["ai_chat"].append(
            {"role": "assistant", "content": reply}
        )
        st.session_state["last_reply"] = reply
        st.session_state["last_prompt"] = prompt_to_send

    last_reply = st.session_state.get("last_reply")
    if last_reply:
        st.markdown("---")
        ttcols = st.columns([1, 5])
        with ttcols[0]:
            tts_payload = json.dumps(last_reply)
            st.components.v1.html(
                f"""
<button id="edge-tts" style="
  background:#0F172A;color:#FDE68A;border:1px solid rgba(245,158,11,.4);
  border-radius:999px;padding:8px 16px;font-weight:700;font-size:.85rem;
  cursor:pointer;font-family:ui-monospace,monospace;">
  ▶ Read aloud
</button>
<script>
(function(){{
  const text = {tts_payload};
  const btn = document.getElementById('edge-tts');
  if (!('speechSynthesis' in window)) {{
    btn.disabled = true; btn.style.opacity = .5;
    btn.textContent = 'TTS not supported'; return;
  }}
  let speaking = false;
  btn.addEventListener('click', () => {{
    if (speaking) {{ speechSynthesis.cancel(); speaking = false;
      btn.textContent = '▶ Read aloud'; return; }}
    const clean = text.replace(/[#*_`>]/g,'').replace(/\\[(.*?)\\]\\(.*?\\)/g,'$1');
    const u = new SpeechSynthesisUtterance(clean);
    u.rate = 1.05; u.pitch = 1.0; u.volume = 1.0;
    const voices = speechSynthesis.getVoices();
    const v = voices.find(x => /en-US/i.test(x.lang) && /male|daniel|alex/i.test(x.name)) ||
              voices.find(x => /en-US/i.test(x.lang)) || voices[0];
    if (v) u.voice = v;
    u.onend = () => {{ speaking = false; btn.textContent = '▶ Read aloud'; }};
    speechSynthesis.speak(u);
    speaking = true; btn.textContent = '■ Stop';
  }});
}})();
</script>
                """,
                height=46,
            )
        with ttcols[1]:
            st.caption("Suggested follow-ups:")
        followups = [
            ("Dig deeper", "Dig deeper on your last answer. Add more specific numbers, books, and concrete reasoning."),
            ("Build me a parlay", "Take your last suggestion and turn it into a 2-3 leg parlay with combined odds, hit probability, and EV. Include stake."),
            ("What's the hedge?", "What's the optimal hedge on your last suggestion? Give book, line, stake, and locked-in profit/loss range."),
            ("Stake size?", "Recommend the exact stake size for your last suggestion on a $500 bankroll using fractional Kelly. Explain why."),
            ("What are the risks?", "List the top 3 risks of your last suggestion - injuries, line moves, weather, refs, anything I should know."),
            ("Alternative pick", "Give me one alternative to your last suggestion that I'd be smart to consider. Why is it different?"),
        ]
        fcols = st.columns(3)
        for i, (label, prompt) in enumerate(followups):
            if fcols[i % 3].button(
                label, key=f"fu_{i}", use_container_width=True,
            ):
                st.session_state["pending_followup"] = prompt
                st.rerun()

    if st.session_state["ai_chat"]:
        if st.button("Clear chat", key="clear_ai"):
            st.session_state["ai_chat"] = []
            st.session_state.pop("last_reply", None)
            st.rerun()

# ---- Mobile bottom status bar (#4) ----
try:
    _mob_bets = db_load_bets()
    _today_iso = datetime.now(timezone.utc).date().isoformat()
    _mob_open = [b for b in _mob_bets if b["status"] == "open"]
    _mob_today_open = [b for b in _mob_open if b["date"] == _today_iso]
    _mob_settled = [b for b in _mob_bets if b["status"] != "open"]
    _mob_today_settled = [
        b for b in _mob_settled
        if (b.get("settled_at") or b.get("date") or "").startswith(_today_iso)
    ]
    _mob_today_pnl = sum(
        b["to_win"] if b["status"] == "won" else -b["stake"]
        for b in _mob_today_settled
    )
    _mob_pnl = sum(
        b["to_win"] if b["status"] == "won" else -b["stake"]
        for b in _mob_settled
    )
    _mob_equity = float(bankroll) + _mob_pnl
    _streak_kind = None
    _streak_n = 0
    for b in sorted(
        _mob_settled,
        key=lambda x: x.get("settled_at") or x.get("date") or "",
        reverse=True,
    ):
        if b["status"] == "push":
            continue
        if _streak_kind is None:
            _streak_kind = b["status"]
            _streak_n = 1
        elif b["status"] == _streak_kind:
            _streak_n += 1
        else:
            break
    _streak_label = (
        f"{_streak_n}{(_streak_kind or '')[0].upper()}"
        if _streak_kind else "-"
    )
    _streak_cls = (
        "green" if _streak_kind == "won"
        else ("red" if _streak_kind == "lost" else "")
    )
    _today_cls = (
        "green" if _mob_today_pnl > 0
        else ("red" if _mob_today_pnl < 0 else "")
    )
    _eq_cls = "green" if _mob_equity >= float(bankroll) else "red"
    st.markdown(
        f"""<div class='edge-mobar'>
<div class='edge-mobar-row'>
  <div class='edge-mobar-cell'>BANK
    <span class='v {_eq_cls}'>${_mob_equity:,.0f}</span></div>
  <div class='edge-mobar-cell'>TODAY
    <span class='v {_today_cls}'>${_mob_today_pnl:+,.0f}</span></div>
  <div class='edge-mobar-cell'>OPEN
    <span class='v'>{len(_mob_open)}</span></div>
  <div class='edge-mobar-cell'>STREAK
    <span class='v {_streak_cls}'>{_streak_label}</span></div>
</div>
</div>""",
        unsafe_allow_html=True,
    )
except Exception:
    pass

# ---- Always-on backlight (Wake Lock) + first-run tour (#41) ----
try:
    from streamlit.components.v1 import html as _wake_html
    _wake_html(
        """
<script>
(async function(){
  // ---- Wake Lock: keep the screen on while EDGE is open ----
  let wl = null;
  async function acquire(){
    try {
      if ('wakeLock' in navigator) {
        wl = await navigator.wakeLock.request('screen');
        wl.addEventListener('release', () => {});
      }
    } catch(e){}
  }
  acquire();
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') acquire();
  });

  // ---- First-run guided tour ----
  let pdoc;
  try { pdoc = window.parent.document; } catch(e) { pdoc = document; }
  let seen = false;
  try { seen = !!localStorage.getItem('edge_tour_seen_v1'); } catch(e){}
  if (seen) return;
  if (pdoc.getElementById('edge-tour-ov')) return;

  const steps = [
    {t:'Welcome to EDGE',
     b:'Sharp. Fast. Ruthless. 60-second tour - then you are off.'},
    {t:'1) The Board',
     b:'Live odds across DraftKings, FanDuel, Bet365. Best price highlighted in green. Open Alt-lines to shop spreads & totals.'},
    {t:'2) Suggested Picks',
     b:'Highest-edge picks with auto-sized stakes ($1-$10). Tap "Lock it in" to log instantly.'},
    {t:'3) Player Props',
     b:'PrizePicks-style player props with edge math. Build a same-game parlay at the bottom of the tab.'},
    {t:'4) Bankroll',
     b:'Auto-graded settles, ROI, streaks, equity curve, daily P&L waterfall, trophy case, leaderboard.'},
    {t:'5) Ask Edge',
     b:'AI sidekick: voice mode, "why this pick", post-bet critiques. Have fun.'},
  ];
  let i = 0;

  const ov = pdoc.createElement('div');
  ov.id = 'edge-tour-ov';
  ov.style.cssText =
    'position:fixed;inset:0;background:rgba(0,0,0,.82);' +
    'z-index:99999;display:flex;align-items:center;justify-content:center;' +
    'backdrop-filter:blur(12px);' +
    'font-family:Inter,system-ui,sans-serif;';

  const card = pdoc.createElement('div');
  card.style.cssText =
    'max-width:460px;width:90%;padding:30px 28px;border-radius:16px;' +
    'background:linear-gradient(180deg,#0F0F0F,#000);' +
    'border:1px solid rgba(220,38,38,.5);' +
    'box-shadow:0 0 60px rgba(220,38,38,.35);' +
    'color:#F3F4F6;position:relative;';

  const t = pdoc.createElement('div');
  t.style.cssText =
    'font-family:"Bebas Neue","Oswald",sans-serif;' +
    'font-size:1.7rem;letter-spacing:.14em;color:#DC2626;' +
    'margin-bottom:10px;text-shadow:0 0 18px rgba(220,38,38,.4);';

  const b = pdoc.createElement('div');
  b.style.cssText =
    'font-size:.96rem;line-height:1.55;color:#D1D5DB;' +
    'margin-bottom:22px;min-height:80px;';

  const dots = pdoc.createElement('div');
  dots.style.cssText =
    'display:flex;gap:7px;justify-content:center;margin-bottom:20px;';

  const ctrl = pdoc.createElement('div');
  ctrl.style.cssText = 'display:flex;gap:10px;justify-content:flex-end;';

  const skip = pdoc.createElement('button');
  skip.textContent = 'Skip';
  skip.style.cssText =
    'background:transparent;color:#9CA3AF;border:1px solid #374151;' +
    'padding:9px 20px;border-radius:8px;cursor:pointer;' +
    'font-family:inherit;font-size:.85rem;letter-spacing:.06em;';

  const next = pdoc.createElement('button');
  next.style.cssText =
    'background:#DC2626;color:#fff;border:0;padding:9px 24px;' +
    'border-radius:8px;cursor:pointer;font-weight:700;' +
    'letter-spacing:.08em;font-family:inherit;font-size:.85rem;' +
    'box-shadow:0 0 16px rgba(220,38,38,.4);';

  function render(){
    t.textContent = steps[i].t;
    b.textContent = steps[i].b;
    next.textContent = (i === steps.length - 1) ? "LET'S GO" : 'NEXT';
    dots.innerHTML = '';
    steps.forEach(function(_, k){
      const d = pdoc.createElement('span');
      d.style.cssText =
        'width:9px;height:9px;border-radius:50%;background:' +
        (k === i ? '#DC2626' : '#374151') + ';' +
        'transition:all .25s;' +
        (k === i ? 'box-shadow:0 0 8px rgba(220,38,38,.6);' : '');
      dots.appendChild(d);
    });
  }
  function dismiss(){
    try { localStorage.setItem('edge_tour_seen_v1','1'); } catch(e){}
    ov.remove();
  }
  next.addEventListener('click', function(){
    if (i < steps.length - 1) { i++; render(); } else { dismiss(); }
  });
  skip.addEventListener('click', dismiss);

  card.appendChild(t); card.appendChild(b); card.appendChild(dots);
  ctrl.appendChild(skip); ctrl.appendChild(next); card.appendChild(ctrl);
  ov.appendChild(card); pdoc.body.appendChild(ov);
  render();
})();
</script>
        """,
        height=0,
    )
except Exception:
    pass
