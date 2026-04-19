import html
import os
import uuid
from collections import defaultdict
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

st.set_page_config(
    page_title="Sports Betting Dashboard",
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
MAIN_MARKET_BUCKETS = {"Moneyline", "Spread", "Total", "Team Total"}
PROP_MARKET_BUCKETS = {"Player Prop", "DFS Prop"}

BET_LOG_FILE = "bet_log.csv"
SNAPSHOT_FILE = "odds_snapshot_history.csv"

BET_LOG_COLUMNS = [
    "Bet ID",
    "Logged At",
    "Settled At",
    "Event ID",
    "Odd ID",
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

SNAPSHOT_COLUMNS = [
    "Snapshot At",
    "Event ID",
    "Odd ID",
    "Sport",
    "Event",
    "Market Bucket",
    "Market",
    "Pick",
    "Sportsbook",
    "Odds",
    "Implied Prob",
    "Line",
    "Last Update",
    "Start Time",
]

# -----------------------------
# FILE HELPERS
# -----------------------------
def ensure_csv_with_columns(filepath, columns):
    if not os.path.exists(filepath):
        pd.DataFrame(columns=columns).to_csv(filepath, index=False)
        return

    try:
        df = pd.read_csv(filepath)
    except Exception:
        df = pd.DataFrame(columns=columns)

    changed = False
    for col in columns:
        if col not in df.columns:
            df[col] = ""
            changed = True

    if changed:
        df = df[columns]
        df.to_csv(filepath, index=False)


def ensure_files():
    ensure_csv_with_columns(BET_LOG_FILE, BET_LOG_COLUMNS)
    ensure_csv_with_columns(SNAPSHOT_FILE, SNAPSHOT_COLUMNS)


def load_bet_log():
    ensure_files()
    try:
        df = pd.read_csv(BET_LOG_FILE)
    except Exception:
        df = pd.DataFrame(columns=BET_LOG_COLUMNS)

    for col in BET_LOG_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    for col in ["Stake", "Implied Prob", "Model Prob", "Edge %", "Bet Score", "PNL"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    return df[BET_LOG_COLUMNS]


def save_bet_log(df):
    df = df.copy()
    for col in BET_LOG_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df[BET_LOG_COLUMNS].to_csv(BET_LOG_FILE, index=False)


def load_snapshot_history():
    ensure_files()
    try:
        df = pd.read_csv(SNAPSHOT_FILE)
    except Exception:
        df = pd.DataFrame(columns=SNAPSHOT_COLUMNS)

    for col in SNAPSHOT_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    for col in ["Implied Prob", "Line"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df[SNAPSHOT_COLUMNS]


def save_snapshot_history(df):
    df = df.copy()
    for col in SNAPSHOT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df[SNAPSHOT_COLUMNS].to_csv(SNAPSHOT_FILE, index=False)


def american_profit(odds_value, stake):
    try:
        odds = int(str(odds_value).strip().replace("−", "-"))
    except Exception:
        return 0.0

    stake = float(stake)
    if odds > 0:
        return round(stake * (odds / 100), 2)
    return round(stake * (100 / abs(odds)), 2)


# -----------------------------
# BASIC HELPERS
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
    return names.get("medium") or names.get("long") or names.get("short") or fallback


def safe_player_name(players, stat_entity_id):
    if not isinstance(players, dict):
        return str(stat_entity_id).replace("_", " ").title()
    player = players.get(stat_entity_id, {})
    return player.get("name") or str(stat_entity_id).replace("_", " ").title()


def parse_iso_datetime(value):
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
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
    if "team total" in text:
        return "Team Total"
    if "player" in text or "points" in text or "rebounds" in text or "assists" in text:
        return "Player Prop"
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
# LIVE ODDS FETCH
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

                sportsbook_name = TARGET_BOOKS[book_id]
                market_bucket = classify_market(market_name, pick_label, sportsbook_name)
                deep_link = quote.get("deeplink") or event_links.get(book_id, "")

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
                        "Line": quote.get("spread") if quote.get("spread") is not None else quote.get("overUnder"),
                        "Last Update": quote.get("lastUpdatedAt", ""),
                        "Link": deep_link,
                    }
                )

    return pd.DataFrame(rows)


# -----------------------------
# SNAPSHOT / LINE-MOVEMENT HELPERS
# -----------------------------
def update_snapshot_history(all_rows):
    if all_rows.empty:
        return

    history = load_snapshot_history()

    snapshot_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    snap = all_rows[
        [
            "Event ID",
            "Odd ID",
            "Sport",
            "Event",
            "Market Bucket",
            "Market",
            "Pick",
            "Sportsbook",
            "Odds",
            "Implied Prob",
            "Line",
            "Last Update",
            "Start Time",
        ]
    ].copy()
    snap["Snapshot At"] = snapshot_time
    snap = snap[SNAPSHOT_COLUMNS]

    combined = pd.concat([history, snap], ignore_index=True)
    combined["Dedup Key"] = (
        combined["Event ID"].astype(str) + "||"
        + combined["Odd ID"].astype(str) + "||"
        + combined["Sportsbook"].astype(str) + "||"
        + combined["Last Update"].astype(str) + "||"
        + combined["Odds"].astype(str)
    )
    combined = combined.drop_duplicates(subset=["Dedup Key"], keep="last").drop(columns=["Dedup Key"])
    save_snapshot_history(combined)


def attach_line_history(all_rows):
    if all_rows.empty:
        all_rows["Opening Odds"] = ""
        all_rows["Opening Implied Prob"] = 0.0
        all_rows["Line Move %"] = 0.0
        all_rows["Line Trend"] = "New"
        return all_rows

    history = load_snapshot_history()
    if history.empty:
        all_rows = all_rows.copy()
        all_rows["Opening Odds"] = all_rows["Odds"]
        all_rows["Opening Implied Prob"] = all_rows["Implied Prob"]
        all_rows["Line Move %"] = 0.0
        all_rows["Line Trend"] = "New"
        return all_rows

    history = history.copy()
    history["Snapshot At Parsed"] = pd.to_datetime(history["Snapshot At"], errors="coerce")
    history = history.sort_values("Snapshot At Parsed")

    first_seen = history.groupby(["Event ID", "Odd ID", "Sportsbook"], as_index=False).first()
    first_seen = first_seen.rename(
        columns={
            "Odds": "Opening Odds",
            "Implied Prob": "Opening Implied Prob",
        }
    )

    enriched = all_rows.merge(
        first_seen[["Event ID", "Odd ID", "Sportsbook", "Opening Odds", "Opening Implied Prob"]],
        on=["Event ID", "Odd ID", "Sportsbook"],
        how="left",
    )
    enriched["Opening Odds"] = enriched["Opening Odds"].fillna(enriched["Odds"])
    enriched["Opening Implied Prob"] = pd.to_numeric(enriched["Opening Implied Prob"], errors="coerce").fillna(
        enriched["Implied Prob"]
    )
    enriched["Line Move %"] = (enriched["Implied Prob"] - enriched["Opening Implied Prob"]).round(2)

    def line_trend_label(change):
        if change >= 1.5:
            return "Worse Now"
        if change <= -1.5:
            return "Improving"
        return "Stable"

    enriched["Line Trend"] = enriched["Line Move %"].apply(line_trend_label)
    return enriched


# -----------------------------
# SCORING ENGINE
# -----------------------------
def confidence_from_score(score):
    if score >= 7.5:
        return "Elite"
    if score >= 5.5:
        return "High"
    if score >= 3.5:
        return "Medium"
    return "Low"


def market_weight(bucket):
    return {
        "Moneyline": 1.35,
        "Spread": 1.25,
        "Total": 1.15,
        "Team Total": 0.85,
        "Player Prop": 0.55,
        "DFS Prop": 0.35,
        "Other": 0.40,
    }.get(bucket, 0.40)


def time_penalty(minutes):
    if minutes is None:
        return 0.0
    if minutes < 0:
        return -2.5
    if minutes < 15:
        return -1.5
    if minutes < 60:
        return -0.9
    if minutes < 180:
        return -0.4
    return 0.0


def book_penalty(book_name):
    return -0.6 if book_name == "PrizePicks" else 0.0


def line_trend_adjustment(label):
    if label == "Improving":
        return 0.15
    if label == "Worse Now":
        return -0.15
    return 0.0


def bet_size_from_score(edge, score, min_bet, max_bet):
    if edge < 1.0 or score < 3.5:
        return 0
    if score < 4.5:
        return int(min_bet)
    if score < 5.5:
        return int(min(max_bet, max(min_bet, 3)))
    if score < 6.5:
        return int(min(max_bet, max(min_bet, 5)))
    if score < 7.5:
        return int(min(max_bet, max(min_bet, 7)))
    return int(min(max_bet, max(min_bet, 10)))


def build_reason(row):
    parts = []

    if row["Is Best Book For Pick"]:
        parts.append(f"best current number across {int(row['Books Quoting'])} books")
    else:
        parts.append("not the best book for this outcome")

    if row["Edge %"] >= 3:
        parts.append("healthy edge vs consensus")
    elif row["Edge %"] >= 1:
        parts.append("small but positive edge")

    bucket = row["Market Bucket"]
    if bucket in MAIN_MARKET_BUCKETS:
        parts.append(f"{bucket.lower()} market gets stronger weighting")
    elif bucket in PROP_MARKET_BUCKETS:
        parts.append("prop market gets a smaller weight")

    minutes = row["Minutes To Start"]
    if minutes is not None:
        if minutes >= 180:
            parts.append("not too close to lock")
        elif minutes >= 60:
            parts.append("moderate time before start")
        else:
            parts.append("close to lock so confidence is trimmed")

    if row["Line Trend"] == "Improving":
        parts.append("current price is better than earliest seen")
    elif row["Line Trend"] == "Worse Now":
        parts.append("market has moved against this number")

    if row["Sportsbook"] == "PrizePicks":
        parts.append("PrizePicks is handled more conservatively")

    return " • ".join(parts)


def apply_smart_scoring(all_rows, min_bet, max_bet):
    if all_rows.empty:
        return all_rows

    scored = all_rows.copy()

    market_stats = (
        scored.groupby(["Event ID", "Odd ID"])["Implied Prob"]
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

    scored = scored.merge(market_stats, on=["Event ID", "Odd ID"], how="left")
    scored["Prob StdDev"] = scored["Prob StdDev"].fillna(0.0)
    scored["Model Prob"] = scored["Consensus Prob"].round(2)
    scored["Edge %"] = (scored["Consensus Prob"] - scored["Implied Prob"]).round(2)
    scored["Best Line Gap %"] = (scored["Worst Price Prob"] - scored["Implied Prob"]).round(2)

    scored = scored.sort_values(
        ["Event ID", "Odd ID", "Implied Prob", "Bet Score"] if "Bet Score" in scored.columns else ["Event ID", "Odd ID", "Implied Prob"],
        ascending=True,
    )

    # provisional best-book flag before score exists
    scored["Sort Rank"] = scored.groupby(["Event ID", "Odd ID"]).cumcount() + 1
    scored["Is Best Book For Pick"] = scored["Sort Rank"] == 1
    scored = scored.drop(columns=["Sort Rank"])

    scored["Market Weight"] = scored["Market Bucket"].apply(market_weight)
    scored["Time Penalty"] = scored["Minutes To Start"].apply(time_penalty)
    scored["Book Penalty"] = scored["Sportsbook"].apply(book_penalty)
    scored["Books Bonus"] = scored["Books Quoting"].apply(lambda x: min((x - 1) * 0.55, 2.20))
    scored["Line Trend Bonus"] = scored["Line Trend"].apply(line_trend_adjustment)

    scored["Bet Score"] = (
        scored["Edge %"] * 0.95
        + scored["Best Line Gap %"] * 0.40
        + scored["Books Bonus"]
        + scored["Market Weight"]
        + scored["Time Penalty"]
        + scored["Book Penalty"]
        + scored["Line Trend Bonus"]
    ).round(2)

    # re-pick best book using price first, then score
    scored = scored.sort_values(
        ["Event ID", "Odd ID", "Implied Prob", "Bet Score"],
        ascending=[True, True, True, False],
    )
    scored["Row Rank"] = scored.groupby(["Event ID", "Odd ID"]).cumcount() + 1
    scored["Is Best Book For Pick"] = scored["Row Rank"] == 1
    scored = scored.drop(columns=["Row Rank"])

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
    scored["Preliminary Status"] = scored["Recommended Bet"].apply(lambda x: "Bet" if x > 0 else "No Bet")
    scored["Reason"] = scored.apply(build_reason, axis=1)
    return scored


def apply_advanced_risk_controls(
    candidate_rows,
    min_bet,
    max_total_exposure,
    max_sport_exposure,
    max_event_exposure,
    max_book_exposure,
    max_prop_exposure,
    min_books_quoting,
    min_edge_pct,
    min_score,
    min_minutes_to_start,
    max_bets_per_event,
    limit_main_markets_per_event,
):
    candidates = candidate_rows.copy()

    candidates["Stake To Bet"] = 0
    candidates["Exposure Status"] = "No Bet"
    candidates["Final Status"] = "No Bet"
    candidates["Allocation Notes"] = ""
    candidates["Correlation Flag"] = ""

    total_used = 0.0
    sport_used = defaultdict(float)
    event_used = defaultdict(float)
    book_used = defaultdict(float)
    prop_used = 0.0
    event_bets_count = defaultdict(int)
    event_main_bet_taken = defaultdict(bool)
    event_bucket_taken = defaultdict(set)

    ordered_idx = candidates.sort_values(
        ["Bet Score", "Edge %", "Books Quoting"],
        ascending=[False, False, False],
    ).index

    for idx in ordered_idx:
        row = candidates.loc[idx]
        notes = []
        final_status = "Bet"
        correlation_flag = ""

        if row["Preliminary Status"] != "Bet":
            final_status = "No Bet"
            notes.append("score or edge not strong enough")
        elif row["Books Quoting"] < min_books_quoting:
            final_status = "Pass"
            notes.append(f"only {int(row['Books Quoting'])} books quoting")
        elif row["Edge %"] < min_edge_pct:
            final_status = "Pass"
            notes.append(f"edge below {min_edge_pct:.1f}% threshold")
        elif row["Bet Score"] < min_score:
            final_status = "Pass"
            notes.append(f"score below {min_score:.1f}")
        elif row["Minutes To Start"] is not None and row["Minutes To Start"] < min_minutes_to_start:
            final_status = "Pass"
            notes.append(f"inside {int(min_minutes_to_start)} minutes to start")
        elif event_bets_count[row["Event"]] >= max_bets_per_event:
            final_status = "Pass"
            correlation_flag = "Event Cap"
            notes.append("event bet count cap reached")
        elif row["Market Bucket"] in event_bucket_taken[row["Event"]]:
            final_status = "Pass"
            correlation_flag = "Duplicate Bucket"
            notes.append("same event/market bucket already selected")
        elif (
            limit_main_markets_per_event
            and row["Market Bucket"] in MAIN_MARKET_BUCKETS
            and event_main_bet_taken[row["Event"]]
        ):
            final_status = "Pass"
            correlation_flag = "Main-Market Correlation"
            notes.append("main market on this event already selected")

        if final_status == "Bet":
            remaining_total = max_total_exposure - total_used
            remaining_sport = max_sport_exposure - sport_used[row["Sport"]]
            remaining_event = max_event_exposure - event_used[row["Event"]]
            remaining_book = max_book_exposure - book_used[row["Sportsbook"]]
            remaining_prop = max_prop_exposure - prop_used if row["Market Bucket"] in PROP_MARKET_BUCKETS else row["Recommended Bet"]

            allowed = min(
                float(row["Recommended Bet"]),
                float(remaining_total),
                float(remaining_sport),
                float(remaining_event),
                float(remaining_book),
                float(remaining_prop),
            )

            if allowed < float(min_bet):
                final_status = "Pass"
                notes.append("trimmed below minimum by exposure caps")
            else:
                stake = int(allowed)
                candidates.at[idx, "Stake To Bet"] = stake
                total_used += stake
                sport_used[row["Sport"]] += stake
                event_used[row["Event"]] += stake
                book_used[row["Sportsbook"]] += stake
                if row["Market Bucket"] in PROP_MARKET_BUCKETS:
                    prop_used += stake
                event_bets_count[row["Event"]] += 1
                event_bucket_taken[row["Event"]].add(row["Market Bucket"])
                if row["Market Bucket"] in MAIN_MARKET_BUCKETS:
                    event_main_bet_taken[row["Event"]] = True

                if stake < float(row["Recommended Bet"]):
                    notes.append("stake trimmed by exposure caps")
                    candidates.at[idx, "Exposure Status"] = "Trimmed To Fit Cap"
                else:
                    candidates.at[idx, "Exposure Status"] = "Within Cap"

        if final_status != "Bet":
            candidates.at[idx, "Stake To Bet"] = 0
            if any(term in " ".join(notes) for term in ["cap", "trimmed", "exposure"]):
                candidates.at[idx, "Exposure Status"] = "Exposure Cap Reached"
            elif correlation_flag:
                candidates.at[idx, "Exposure Status"] = "Correlation Pass"
            else:
                candidates.at[idx, "Exposure Status"] = "No Bet"

        candidates.at[idx, "Final Status"] = final_status
        candidates.at[idx, "Allocation Notes"] = " • ".join(notes)
        candidates.at[idx, "Correlation Flag"] = correlation_flag

    return candidates


def merge_candidate_statuses(all_rows, candidates):
    if all_rows.empty:
        return all_rows

    merged = all_rows.copy()
    merged["Stake To Bet"] = 0
    merged["Exposure Status"] = "No Bet"
    merged["Final Status"] = "No Bet"
    merged["Allocation Notes"] = ""
    merged["Correlation Flag"] = ""

    candidate_cols = [
        "Event ID",
        "Odd ID",
        "Sportsbook",
        "Stake To Bet",
        "Exposure Status",
        "Final Status",
        "Allocation Notes",
        "Correlation Flag",
    ]
    if not candidates.empty:
        merged = merged.merge(
            candidates[candidate_cols],
            on=["Event ID", "Odd ID", "Sportsbook"],
            how="left",
            suffixes=("", "_cand"),
        )
        for col in ["Stake To Bet", "Exposure Status", "Final Status", "Allocation Notes", "Correlation Flag"]:
            merged[col] = merged[f"{col}_cand"].combine_first(merged[col])
            merged = merged.drop(columns=[f"{col}_cand"])

    # rows that are not best book but belong to an outcome where another book is the final bet
    final_outcomes = set(
        zip(
            candidates.loc[candidates["Final Status"] == "Bet", "Event ID"],
            candidates.loc[candidates["Final Status"] == "Bet", "Odd ID"],
        )
    ) if not candidates.empty else set()

    def other_book_status(row):
        if row["Is Best Book For Pick"]:
            return row["Final Status"]
        key = (row["Event ID"], row["Odd ID"])
        if key in final_outcomes:
            return "Shop Better Book"
        return "No Bet"

    merged["Display Status"] = merged.apply(other_book_status, axis=1)
    return merged


def build_factor_text(row):
    pieces = [
        f"Edge {row['Edge %']:.2f}%",
        f"Line gap {row['Best Line Gap %']:.2f}%",
        f"Books bonus {row['Books Bonus']:.2f}",
        f"Market weight {row['Market Weight']:.2f}",
        f"Time penalty {row['Time Penalty']:.2f}",
        f"Book penalty {row['Book Penalty']:.2f}",
        f"Trend adj {row['Line Trend Bonus']:.2f}",
    ]
    return " | ".join(pieces)


def build_compare_table(all_rows, candidates):
    if all_rows.empty:
        return pd.DataFrame()

    group_cols = ["Event ID", "Odd ID", "Sport", "Event", "Start Time", "Market Bucket", "Market", "Pick"]

    odds_pivot = all_rows.pivot_table(
        index=group_cols,
        columns="Sportsbook",
        values="Odds",
        aggfunc="first",
    ).reset_index()

    prob_pivot = all_rows.pivot_table(
        index=group_cols,
        columns="Sportsbook",
        values="Implied Prob",
        aggfunc="first",
    ).reset_index()

    prob_pivot.columns = [c if isinstance(c, str) else c for c in prob_pivot.columns]

    gap_stats = (
        all_rows.groupby(group_cols)["Implied Prob"]
        .agg(["min", "max", "count"])
        .reset_index()
        .rename(columns={"min": "Best Implied Prob", "max": "Worst Implied Prob", "count": "Books Quoting"})
    )
    gap_stats["Line Gap %"] = (gap_stats["Worst Implied Prob"] - gap_stats["Best Implied Prob"]).round(2)

    best_book_rows = all_rows[all_rows["Is Best Book For Pick"]].copy()
    if not candidates.empty:
        best_book_rows = best_book_rows.merge(
            candidates[
                [
                    "Event ID",
                    "Odd ID",
                    "Sportsbook",
                    "Stake To Bet",
                    "Final Status",
                    "Exposure Status",
                    "Allocation Notes",
                    "Correlation Flag",
                ]
            ],
            on=["Event ID", "Odd ID", "Sportsbook"],
            how="left",
        )
    else:
        best_book_rows["Stake To Bet"] = 0
        best_book_rows["Final Status"] = "No Bet"
        best_book_rows["Exposure Status"] = "No Bet"
        best_book_rows["Allocation Notes"] = ""
        best_book_rows["Correlation Flag"] = ""

    best_book_rows = best_book_rows.rename(
        columns={
            "Sportsbook": "Best Sportsbook",
            "Odds": "Best Odds",
            "Edge %": "Best Edge %",
            "Bet Score": "Best Bet Score",
            "Confidence": "Best Confidence",
            "Reason": "Best Reason",
            "Link": "Best Link",
            "Line Trend": "Best Line Trend",
            "Line Move %": "Best Line Move %",
        }
    )

    compare = odds_pivot.merge(gap_stats, on=group_cols, how="left")
    compare = compare.merge(
        best_book_rows[
            [
                "Event ID",
                "Odd ID",
                "Best Sportsbook",
                "Best Odds",
                "Best Edge %",
                "Best Bet Score",
                "Best Confidence",
                "Stake To Bet",
                "Final Status",
                "Exposure Status",
                "Allocation Notes",
                "Correlation Flag",
                "Best Reason",
                "Best Link",
                "Best Line Trend",
                "Best Line Move %",
                "Books Bonus",
                "Opening Odds",
            ]
        ],
        on=["Event ID", "Odd ID"],
        how="left",
    )

    for col in ["DraftKings", "FanDuel", "Bet365", "PrizePicks"]:
        if col not in compare.columns:
            compare[col] = ""

    def shop_alert(row):
        gap = row["Line Gap %"]
        books = row["Books Quoting"]
        if books >= 3 and gap >= 4:
            return "Strong Shop"
        if books >= 2 and gap >= 2:
            return "Good Shop"
        if gap > 0:
            return "Small Edge"
        return "Flat"

    compare["Shop Alert"] = compare.apply(shop_alert, axis=1)
    compare["Status Rank"] = compare["Final Status"].map({"Bet": 3, "Pass": 2, "No Bet": 1}).fillna(0)

    return compare.sort_values(
        ["Status Rank", "Best Bet Score", "Line Gap %"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def attach_observed_clv(bet_log):
    if bet_log.empty:
        bet_log["Latest Odds Seen"] = ""
        bet_log["Latest Implied Prob"] = 0.0
        bet_log["Observed CLV %"] = 0.0
        bet_log["CLV Label"] = "No Data"
        return bet_log

    history = load_snapshot_history()
    if history.empty:
        bet_log = bet_log.copy()
        bet_log["Latest Odds Seen"] = ""
        bet_log["Latest Implied Prob"] = 0.0
        bet_log["Observed CLV %"] = 0.0
        bet_log["CLV Label"] = "No Data"
        return bet_log

    history = history.copy()
    history["Snapshot At Parsed"] = pd.to_datetime(history["Snapshot At"], errors="coerce")
    history = history.sort_values("Snapshot At Parsed")
    latest = history.groupby(["Event ID", "Odd ID", "Sportsbook"], as_index=False).last()
    latest = latest.rename(
        columns={
            "Odds": "Latest Odds Seen",
            "Implied Prob": "Latest Implied Prob",
        }
    )

    enriched = bet_log.merge(
        latest[["Event ID", "Odd ID", "Sportsbook", "Latest Odds Seen", "Latest Implied Prob"]],
        on=["Event ID", "Odd ID", "Sportsbook"],
        how="left",
    )
    enriched["Latest Implied Prob"] = pd.to_numeric(enriched["Latest Implied Prob"], errors="coerce").fillna(0.0)
    enriched["Observed CLV %"] = (enriched["Latest Implied Prob"] - enriched["Implied Prob"]).round(2)

    def clv_label(value):
        if value >= 1.5:
            return "Beating Market"
        if value >= 0.5:
            return "Ahead"
        if value > -0.5:
            return "Flat"
        if value > -1.5:
            return "Behind"
        return "Losing Market"

    enriched["CLV Label"] = enriched["Observed CLV %"].apply(clv_label)
    return enriched


def get_live_board(
    leagues,
    sportsbooks,
    market_buckets,
    confidence_levels,
    min_bet,
    max_bet,
    max_total_exposure,
    max_sport_exposure,
    max_event_exposure,
    max_book_exposure,
    max_prop_exposure,
    min_books_quoting,
    min_edge_pct,
    min_score,
    min_minutes_to_start,
    max_bets_per_event,
    limit_main_markets_per_event,
    only_final_bets=False,
):
    events, error_message = fetch_events(leagues)
    if error_message:
        return pd.DataFrame(), pd.DataFrame(), error_message

    raw_rows = flatten_events_to_rows(events)
    if raw_rows.empty:
        return pd.DataFrame(), pd.DataFrame(), "No live odds came back for the selected leagues."

    update_snapshot_history(raw_rows)
    enriched_rows = attach_line_history(raw_rows)
    scored = apply_smart_scoring(enriched_rows, min_bet=min_bet, max_bet=max_bet)

    filtered = scored[
        scored["Sportsbook"].isin(sportsbooks)
        & scored["Market Bucket"].isin(market_buckets)
        & scored["Confidence"].isin(confidence_levels)
    ].copy()

    candidates = filtered[filtered["Is Best Book For Pick"]].copy()
    candidates = apply_advanced_risk_controls(
        candidates,
        min_bet=min_bet,
        max_total_exposure=max_total_exposure,
        max_sport_exposure=max_sport_exposure,
        max_event_exposure=max_event_exposure,
        max_book_exposure=max_book_exposure,
        max_prop_exposure=max_prop_exposure,
        min_books_quoting=min_books_quoting,
        min_edge_pct=min_edge_pct,
        min_score=min_score,
        min_minutes_to_start=min_minutes_to_start,
        max_bets_per_event=max_bets_per_event,
        limit_main_markets_per_event=limit_main_markets_per_event,
    )

    final_rows = merge_candidate_statuses(filtered, candidates)
    compare = build_compare_table(filtered, candidates)

    if only_final_bets:
        final_rows = final_rows[final_rows["Final Status"] == "Bet"].copy()

    final_rows["Status Rank"] = final_rows["Display Status"].map(
        {"Bet": 4, "Pass": 3, "Shop Better Book": 2, "No Bet": 1}
    ).fillna(0)

    final_rows = final_rows.sort_values(
        ["Status Rank", "Bet Score", "Edge %", "Books Quoting"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)

    return final_rows, compare, ""


# -----------------------------
# TRACKER HELPERS
# -----------------------------
def log_bet_from_row(row):
    df = load_bet_log()

    duplicate_mask = (
        (df["Event ID"].astype(str) == str(row["Event ID"]))
        & (df["Odd ID"].astype(str) == str(row["Odd ID"]))
        & (df["Sportsbook"].astype(str) == str(row["Sportsbook"]))
        & (df["Bet Status"].astype(str) == "Pending")
    )
    if duplicate_mask.any():
        return False, "That bet is already logged as pending."

    stake_value = float(row.get("Stake To Bet", row.get("Recommended Bet", 0)))
    if stake_value <= 0:
        return False, "This row does not have a positive stake to log."

    new_row = {
        "Bet ID": str(uuid.uuid4())[:8].upper(),
        "Logged At": datetime.now().strftime("%Y-%m-%d %I:%M:%S %p"),
        "Settled At": "",
        "Event ID": row["Event ID"],
        "Odd ID": row["Odd ID"],
        "Sport": row["Sport"],
        "Event": row["Event"],
        "Market Bucket": row["Market Bucket"],
        "Market": row["Market"],
        "Pick": row["Pick"],
        "Sportsbook": row["Sportsbook"],
        "Odds": row["Odds"],
        "Stake": float(stake_value),
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
    return True, f"Bet logged successfully. Bet ID: {new_row['Bet ID']}"


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
# CHART HELPERS
# -----------------------------
def style_figure(fig, height=350):
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(255,255,255,0)",
        plot_bgcolor="#F7F9FC",
        font=dict(color="#0B2545"),
        margin=dict(l=30, r=20, t=50, b=30),
        height=height,
        title_font=dict(color="#0B2545", size=18),
    )
    fig.update_xaxes(showgrid=True, gridcolor="rgba(11,37,69,0.08)", zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor="rgba(11,37,69,0.08)", zeroline=False)
    return fig


def render_kpi_card(label, value, delta=None, note=None):
    label = html.escape(str(label))
    value = html.escape(str(value))
    delta_html = f'<div class="kpi-card-delta">{html.escape(str(delta))}</div>' if delta not in (None, "") else ''
    note_html = f'<div class="kpi-card-note">{html.escape(str(note))}</div>' if note not in (None, "") else ''
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-card-label">{label}</div>
            <div class="kpi-card-value">{value}</div>
            {delta_html}
            {note_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


# -----------------------------
# SAFE CHART RENDERING
# -----------------------------
def safe_plotly_chart(fig, name, use_container_width=True):
    if fig is None:
        return
    if "_plotly_render_nonce" not in st.session_state:
        st.session_state["_plotly_render_nonce"] = 0
    st.session_state["_plotly_render_nonce"] += 1
    unique_key = f"{name}_{st.session_state['_plotly_render_nonce']}"
    st.plotly_chart(fig, use_container_width=use_container_width, key=unique_key)

def plot_bankroll_curve(settled_df, starting_bankroll):
    if settled_df.empty:
        return None

    df = settled_df.copy()
    df["Sort Time"] = pd.to_datetime(df["Settled At"], errors="coerce")
    df = df.dropna(subset=["Sort Time"]).sort_values("Sort Time")
    if df.empty:
        return None

    df["Running Bankroll"] = float(starting_bankroll) + df["PNL"].cumsum()
    fig = px.line(df, x="Sort Time", y="Running Bankroll", title="Bankroll Curve", markers=True)
    fig.update_traces(line=dict(color="#0B2545", width=3), marker=dict(color="#1D4E89", size=7))
    return style_figure(fig)


def plot_profit_by_sportsbook(settled_df):
    if settled_df.empty:
        return None
    summary = settled_df.groupby("Sportsbook", as_index=False)["PNL"].sum().sort_values("PNL", ascending=False)
    fig = px.bar(summary, x="Sportsbook", y="PNL", title="Profit / Loss by Sportsbook")
    fig.update_traces(marker_color="#1D4E89")
    return style_figure(fig)


def plot_profit_by_market(settled_df):
    if settled_df.empty:
        return None
    summary = settled_df.groupby("Market Bucket", as_index=False)["PNL"].sum().sort_values("PNL", ascending=False)
    fig = px.bar(summary, x="Market Bucket", y="PNL", title="Profit / Loss by Market Type")
    fig.update_traces(marker_color="#5FA8D3")
    fig.update_xaxes(tickangle=-30)
    return style_figure(fig)


def plot_hit_rate_by_confidence(settled_df):
    graded = settled_df[settled_df["Result"].isin(["Win", "Loss"])].copy()
    if graded.empty:
        return None
    graded["Win Flag"] = graded["Result"].eq("Win").astype(int) * 100
    summary = graded.groupby("Confidence", as_index=False)["Win Flag"].mean()
    order = ["Elite", "High", "Medium", "Low"]
    summary["Confidence"] = pd.Categorical(summary["Confidence"], categories=order, ordered=True)
    summary = summary.sort_values("Confidence")
    fig = px.bar(summary, x="Confidence", y="Win Flag", title="Hit Rate by Confidence")
    fig.update_traces(marker_color="#1D4E89")
    fig.update_yaxes(title="Win Rate %")
    return style_figure(fig)


def plot_exposure_by_sport(final_bets):
    if final_bets.empty:
        return None
    summary = final_bets.groupby("Sport", as_index=False)["Stake To Bet"].sum().sort_values("Stake To Bet", ascending=False)
    fig = px.bar(summary, x="Sport", y="Stake To Bet", title="Open Suggested Exposure by Sport")
    fig.update_traces(marker_color="#5FA8D3")
    return style_figure(fig)


def plot_exposure_by_book(final_bets):
    if final_bets.empty:
        return None
    summary = final_bets.groupby("Sportsbook", as_index=False)["Stake To Bet"].sum().sort_values("Stake To Bet", ascending=False)
    fig = px.pie(summary, names="Sportsbook", values="Stake To Bet", title="Open Suggested Exposure by Sportsbook", hole=0.45)
    fig.update_traces(textinfo="label+percent", marker=dict(colors=["#1D4E89", "#5FA8D3", "#0B2545", "#5FA8D3"]))
    return style_figure(fig)


def plot_edge_distribution(current_rows):
    bets = current_rows[current_rows["Final Status"] == "Bet"].copy()
    if bets.empty:
        return None
    fig = px.histogram(bets, x="Edge %", nbins=15, title="Edge Distribution of Final Bets")
    fig.update_traces(marker_color="#1D4E89")
    return style_figure(fig)


def plot_score_vs_pnl(settled_df):
    graded = settled_df[settled_df["Result"].isin(["Win", "Loss"])].copy()
    if graded.empty:
        return None
    fig = px.scatter(
        graded,
        x="Bet Score",
        y="PNL",
        color="Result",
        hover_data=["Event", "Pick", "Sportsbook", "Confidence"],
        title="Bet Score vs Result P/L",
        color_discrete_map={"Win": "#1D4E89", "Loss": "#5FA8D3"},
    )
    return style_figure(fig)


def plot_line_gap_leaderboard(compare_df):
    if compare_df.empty:
        return None
    top = compare_df.head(12).copy()
    top["Label"] = top["Pick"] + " | " + top["Best Sportsbook"].fillna("")
    fig = px.bar(top, x="Line Gap %", y="Label", orientation="h", title="Top Line-Gap Shopping Opportunities")
    fig.update_traces(marker_color="#1D4E89")
    fig.update_yaxes(categoryorder="total ascending")
    return style_figure(fig, height=450)


def plot_line_heatmap(all_rows, compare_df):
    return None

def plot_observed_clv(settled_or_pending_log):
    if settled_or_pending_log.empty:
        return None
    usable = settled_or_pending_log[settled_or_pending_log["Latest Odds Seen"].astype(str) != ""].copy()
    if usable.empty:
        return None
    summary = usable.groupby("CLV Label", as_index=False)["Observed CLV %"].mean().sort_values("Observed CLV %", ascending=False)
    fig = px.bar(summary, x="CLV Label", y="Observed CLV %", title="Observed CLV by Market Position")
    fig.update_traces(marker_color="#1D4E89")
    return style_figure(fig)


def build_explain_bet_prompt(row):
    return (
        f"Explain this bet in plain English for me: {row['Pick']} in {row['Event']} at {row['Sportsbook']} {row['Odds']}. "
        f"Use the dashboard logic only. Cover the edge ({row['Edge %']:.2f}%), bet score ({row['Bet Score']:.2f}), "
        f"confidence ({row['Confidence']}), line trend ({row['Line Trend']}), line move ({row['Line Move %']:.2f}%), "
        f"books quoting ({int(row['Books Quoting'])}), recommended stake (${int(row['Stake To Bet'])}), and any allocation or correlation notes. "
        f"Finish with a clear bottom-line verdict on why it is a bet or why I should still be cautious."
    )


def build_dashboard_context(current_df, compare_df, pending_log, settled_log, bankroll, max_total_exposure):
    final_bets = current_df[current_df["Final Status"] == "Bet"].copy().head(8)
    passes = current_df[current_df["Final Status"] == "Pass"].copy().head(6)
    compare_top = compare_df.copy().head(8)

    realized_pnl = float(settled_log["PNL"].sum()) if not settled_log.empty else 0.0
    current_bankroll = float(bankroll) + realized_pnl
    total_settled_stake = float(settled_log["Stake"].sum()) if not settled_log.empty else 0.0
    roi = (realized_pnl / total_settled_stake * 100) if total_settled_stake > 0 else 0.0
    open_logged_risk = float(pending_log["Stake"].sum()) if not pending_log.empty else 0.0
    open_live_risk = float(final_bets["Stake To Bet"].sum()) if not final_bets.empty else 0.0

    context_sections = [
        f"Starting bankroll: ${float(bankroll):,.2f}",
        f"Current bankroll: ${current_bankroll:,.2f}",
        f"Realized P/L: ${realized_pnl:,.2f}",
        f"ROI: {roi:.2f}%",
        f"Open logged risk: ${open_logged_risk:,.2f}",
        f"Open suggested live risk: ${open_live_risk:,.2f}",
        f"Exposure cap: ${float(max_total_exposure):,.2f}",
    ]

    if not final_bets.empty:
        context_sections.append("\nTop final bets:\n" + final_bets[[
            "Sport", "Event", "Market Bucket", "Market", "Pick", "Sportsbook",
            "Odds", "Edge %", "Bet Score", "Confidence", "Stake To Bet", "Reason"
        ]].to_csv(index=False))

    if not compare_top.empty:
        context_sections.append("\nTop comparison rows:\n" + compare_top[[
            "Sport", "Event", "Market Bucket", "Pick", "Best Sportsbook", "Best Odds",
            "Line Gap %", "Shop Alert", "Best Bet Score", "Best Confidence"
        ]].to_csv(index=False))

    if not pending_log.empty:
        context_sections.append("\nPending logged bets:\n" + pending_log[[
            "Sport", "Event", "Pick", "Sportsbook", "Odds", "Stake", "Confidence", "Bet Score"
        ]].head(8).to_csv(index=False))

    if not settled_log.empty:
        recent_settled = settled_log.sort_values("Settled At", ascending=False).head(8)
        context_sections.append("\nRecent settled bets:\n" + recent_settled[[
            "Sport", "Event", "Pick", "Sportsbook", "Odds", "Stake", "Result", "PNL", "Confidence"
        ]].to_csv(index=False))

    if not passes.empty:
        context_sections.append("\nRecent pass rows:\n" + passes[[
            "Sport", "Event", "Pick", "Sportsbook", "Display Status", "Allocation Notes"
        ]].to_csv(index=False))

    return "\n".join(context_sections)


def extract_response_text(payload):
    if not isinstance(payload, dict):
        return "No response returned."
    if payload.get("output_text"):
        return payload.get("output_text")

    texts = []
    for item in payload.get("output", []) or []:
        for content in item.get("content", []) or []:
            ctype = content.get("type")
            if ctype in {"output_text", "text"}:
                text_value = content.get("text")
                if isinstance(text_value, dict):
                    text_value = text_value.get("value", "")
                if text_value:
                    texts.append(str(text_value))
    if texts:
        return "\n".join(texts).strip()

    error = payload.get("error") or {}
    if isinstance(error, dict) and error.get("message"):
        return error.get("message")
    return "No text response returned from OpenAI."


def call_openai_assistant(user_prompt, current_df, compare_df, pending_log, settled_log, bankroll, max_total_exposure):
    api_key = st.secrets.get("OPENAI_API_KEY", "")
    if not api_key:
        return None, "Add OPENAI_API_KEY to Streamlit Secrets to use the AI assistant."

    model = st.secrets.get("OPENAI_MODEL", "gpt-4.1-mini")
    context_block = build_dashboard_context(current_df, compare_df, pending_log, settled_log, bankroll, max_total_exposure)

    system_prompt = (
        "You are an assistant inside a sports betting dashboard. "
        "Answer using the provided dashboard data first. "
        "Be practical, concise, and transparent about uncertainty. "
        "Do not promise wins. Use bullets sparingly. "
        "Focus on line shopping, bankroll risk, exposure, and the current board."
    )

    payload = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": [
                    {"type": "input_text", "text": system_prompt}
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": f"Dashboard context:\n{context_block}\n\nQuestion:\n{user_prompt}"}
                ],
            },
        ],
        "temperature": 0.3,
        "max_output_tokens": 700,
    }

    try:
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return extract_response_text(data), ""
    except Exception as exc:
        return None, f"OpenAI request failed: {exc}"


def render_quick_link_card(title, description, url):
    st.markdown(
        f"""
        <div class="link-card">
            <div class="link-title">{title}</div>
            <div class="link-desc">{description}</div>
            <a class="link-button" href="{url}" target="_blank">Open {title}</a>
        </div>
        """,
        unsafe_allow_html=True,
    )


def run_ai_prompt(prompt, current_df, compare_df, pending_log, settled_log, bankroll, max_total_exposure):
    prompt = (prompt or "").strip()
    if not prompt:
        return

    if "ai_messages" not in st.session_state:
        st.session_state.ai_messages = []

    st.session_state.ai_messages.append({"role": "user", "content": prompt})
    answer, error = call_openai_assistant(
        prompt,
        current_df=current_df,
        compare_df=compare_df,
        pending_log=pending_log,
        settled_log=settled_log,
        bankroll=bankroll,
        max_total_exposure=max_total_exposure,
    )
    st.session_state.ai_messages.append({
        "role": "assistant",
        "content": error or answer or "No response returned.",
    })


# -----------------------------
# STYLING
# -----------------------------
st.markdown(
    """
    <style>
    .stApp {
        background:
            radial-gradient(circle at top left, rgba(95,168,211,0.16), transparent 26%),
            radial-gradient(circle at top right, rgba(29,78,137,0.10), transparent 22%),
            linear-gradient(180deg, #F7F9FC 0%, #EEF4FA 52%, #E7F0F8 100%);
        color: #111827;
    }

    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #FFFFFF 0%, #F4F8FC 100%);
        border-right: 2px solid rgba(29,78,137,0.12);
    }

    section[data-testid="stSidebar"] * {
        color: #0B2545 !important;
    }

    .main-title {
        display: inline-block;
        font-size: 3.0rem;
        font-weight: 900;
        color: #0B2545;
        background: rgba(255,255,255,0.97);
        border-left: 8px solid #1D4E89;
        border-radius: 16px;
        padding: 12px 18px;
        margin-bottom: 0.35rem;
        letter-spacing: 0.5px;
        box-shadow: 0 10px 24px rgba(11, 37, 69, 0.10);
    }

    .sub-title {
        display: inline-block;
        font-size: 1.02rem;
        color: #0B2545;
        background: rgba(255,255,255,0.95);
        border-radius: 14px;
        padding: 8px 14px;
        margin-bottom: 1rem;
        box-shadow: 0 8px 18px rgba(11, 37, 69, 0.08);
    }

    .theme-banner,
    .hero-box,
    .card,
    .best-bet,
    .note-box,
    .link-card {
        color: #111827;
    }

    .theme-banner {
        background: linear-gradient(180deg, #FFFFFF 0%, #F4F8FC 100%);
        border: 1px solid rgba(11,37,69,0.08);
        border-left: 6px solid #1D4E89;
        border-radius: 16px;
        padding: 12px 16px;
        margin-bottom: 18px;
        box-shadow: 0 10px 20px rgba(11, 37, 69, 0.08);
    }

    .hero-box {
        background: linear-gradient(180deg, #FFFFFF 0%, #F5F8FD 100%);
        border: 2px solid rgba(29,78,137,0.14);
        border-radius: 22px;
        padding: 20px 24px;
        margin-bottom: 18px;
        box-shadow: 0 12px 28px rgba(11, 37, 69, 0.10);
    }

    .card {
        background: rgba(255, 255, 255, 0.97);
        border: 1px solid rgba(11, 37, 69, 0.08);
        border-radius: 18px;
        padding: 18px;
        box-shadow: 0 8px 20px rgba(11,37,69,0.08);
        margin-bottom: 16px;
    }

    .best-bet {
        background: linear-gradient(180deg, #FFFFFF 0%, #F5F8FD 100%);
        border: 2px solid rgba(29,78,137,0.16);
        border-left: 8px solid #1D4E89;
        border-radius: 18px;
        padding: 18px;
        box-shadow: 0 10px 22px rgba(11, 37, 69, 0.09);
        margin-bottom: 16px;
    }

    .section-title {
        font-size: 1.30rem;
        font-weight: 900;
        color: #0B2545;
        margin-top: 8px;
        margin-bottom: 10px;
    }

    .small-label {
        color: #1D4E89;
        font-size: 0.90rem;
        font-weight: 700;
    }

    .big-value {
        color: #0B2545;
        font-size: 1.55rem;
        font-weight: 900;
    }

    .note-box {
        background: rgba(255,255,255,0.95);
        border-left: 6px solid #1D4E89;
        border-radius: 12px;
        padding: 12px 14px;
        margin: 14px 0;
        box-shadow: 0 8px 18px rgba(11,37,69,0.08);
    }

    .kpi-note {
        font-size: 0.82rem;
        color: #1D4E89;
        margin-top: -8px;
        margin-bottom: 8px;
        font-weight: 600;
    }

    .kpi-card {
        background: rgba(255,255,255,0.98);
        border: 1px solid rgba(11,37,69,0.10);
        border-radius: 16px;
        padding: 14px 16px;
        box-shadow: 0 8px 16px rgba(11,37,69,0.08);
        min-height: 118px;
        margin-bottom: 10px;
    }

    .kpi-card-label {
        color: #1D4E89;
        font-size: 0.88rem;
        font-weight: 800;
        margin-bottom: 8px;
    }

    .kpi-card-value {
        color: #0B2545;
        font-size: 1.55rem;
        font-weight: 900;
        line-height: 1.2;
        margin-bottom: 6px;
    }

    .kpi-card-delta {
        color: #1D4E89;
        font-size: 0.92rem;
        font-weight: 700;
        margin-bottom: 4px;
    }

    .kpi-card-note {
        color: #486581;
        font-size: 0.80rem;
        font-weight: 600;
    }

    .stMetric {
        background: rgba(255,255,255,0.97);
        border: 1px solid rgba(11,37,69,0.08);
        border-radius: 16px;
        padding: 8px 10px;
        box-shadow: 0 8px 16px rgba(11,37,69,0.08);
    }

    [data-testid="stMetricValue"],
    [data-testid="stMetricLabel"],
    [data-testid="stMetricDelta"] {
        color: #0B2545 !important;
    }

    div[data-baseweb="select"] > div,
    div[data-baseweb="base-input"] > div,
    div[data-baseweb="textarea"] > div {
        color: #0B2545 !important;
        background: #FFFFFF !important;
        border: 1px solid rgba(11,37,69,0.12) !important;
    }

    div[data-baseweb="select"] input,
    div[data-baseweb="base-input"] input,
    div[data-baseweb="textarea"] textarea {
        color: #0B2545 !important;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }

    .stTabs [data-baseweb="tab"] {
        background: rgba(255,255,255,0.92);
        border: 1px solid rgba(11,37,69,0.10);
        border-radius: 12px;
        color: #0B2545 !important;
        padding: 10px 14px;
        font-weight: 700;
    }

    .stTabs [aria-selected="true"] {
        background: #EAF1FB !important;
        border-color: rgba(29,78,137,0.30) !important;
        color: #0B2545 !important;
    }

    .factor-chip {
        display: inline-block;
        background: rgba(29,78,137,0.08);
        border: 1px solid rgba(29,78,137,0.16);
        border-radius: 999px;
        padding: 4px 10px;
        margin: 2px 4px 2px 0;
        font-size: 0.80rem;
        color: #0B2545;
    }

    .link-card {
        background: linear-gradient(180deg, #FFFFFF 0%, #F5F8FD 100%);
        border: 1px solid rgba(11,37,69,0.10);
        border-left: 8px solid #1D4E89;
        border-radius: 18px;
        padding: 20px;
        box-shadow: 0 10px 22px rgba(11,37,69,0.08);
        min-height: 185px;
        margin-bottom: 14px;
    }

    .link-title {
        font-size: 1.35rem;
        font-weight: 900;
        color: #0B2545;
        margin-bottom: 8px;
    }

    .link-desc {
        font-size: 0.96rem;
        color: #1D4E89;
        margin-bottom: 16px;
        line-height: 1.45;
    }

    .link-button {
        display: inline-block;
        padding: 10px 16px;
        border-radius: 999px;
        background: #EAF1FB;
        color: #0B2545 !important;
        font-weight: 800;
        text-decoration: none;
        border: 1px solid rgba(29,78,137,0.18);
    }

    .link-button:hover {
        background: #D9E8FA;
    }

    [data-testid="stChatMessage"] {
        background: rgba(255,255,255,0.94);
        border: 1px solid rgba(11,37,69,0.08);
        border-radius: 16px;
        padding: 6px 8px;
    }

    [data-testid="stChatMessageContent"],
    [data-testid="stChatMessageContent"] p,
    [data-testid="stChatMessageContent"] li {
        color: #0B2545 !important;
    }

    .stButton > button,
    .stDownloadButton > button,
    .stFormSubmitButton > button {
        background: #F5F8FD !important;
        color: #0B2545 !important;
        border: 1px solid rgba(11,37,69,0.12) !important;
        border-radius: 999px !important;
        font-weight: 800 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# -----------------------------
# SIDEBAR CONTROLS
# -----------------------------
st.sidebar.title("🎯 Dashboard Controls")

bankroll = st.sidebar.number_input("Starting Bankroll", min_value=1.0, value=500.0, step=25.0)
min_bet = st.sidebar.number_input("Minimum Bet", min_value=1.0, value=1.0, step=1.0)
max_bet = st.sidebar.number_input("Maximum Bet", min_value=1.0, value=10.0, step=1.0)

st.sidebar.markdown("### Exposure Rules")
max_total_exposure = st.sidebar.number_input("Max Total Exposure", min_value=1.0, value=40.0, step=5.0)
max_sport_exposure = st.sidebar.number_input("Max Exposure Per Sport", min_value=1.0, value=20.0, step=5.0)
max_event_exposure = st.sidebar.number_input("Max Exposure Per Event", min_value=1.0, value=10.0, step=1.0)
max_book_exposure = st.sidebar.number_input("Max Exposure Per Sportsbook", min_value=1.0, value=15.0, step=1.0)
max_prop_exposure = st.sidebar.number_input("Max Prop Exposure", min_value=1.0, value=12.0, step=1.0)

st.sidebar.markdown("### Logic Thresholds")
min_books_quoting = st.sidebar.number_input("Minimum Books Quoting", min_value=1, value=2, step=1)
min_edge_pct = st.sidebar.number_input("Minimum Edge %", min_value=0.0, value=1.0, step=0.5)
min_score = st.sidebar.number_input("Minimum Bet Score", min_value=0.0, value=3.5, step=0.5)
min_minutes_to_start = st.sidebar.number_input("Minimum Minutes To Start", min_value=0, value=15, step=5)
max_bets_per_event = st.sidebar.number_input("Max Bets Per Event", min_value=1, value=2, step=1)
limit_main_markets_per_event = st.sidebar.toggle("Limit To One Main Market Per Event", value=True)

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

only_final_bets = st.sidebar.toggle("Show final bets only", value=False)

if st.sidebar.button("Refresh now"):
    st.cache_data.clear()
    st.rerun()

# -----------------------------
# HEADER
# -----------------------------
st.markdown('<div class="main-title">🎯 Sports Betting Dashboard</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">KPI-first betting terminal with line shopping, exposure control, charts, tracked performance, and cleaner high-contrast styling.</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="theme-banner"><b>Layout update:</b> light blue/white theme, darker readable text, sportsbook quick links, AI bet explanations, KPI ribbon, chart-first layout, line-gap leaderboard, exposure caps, line movement tracking, observed CLV, and correlation controls.</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="note-box"><b>Storage note:</b> bet history and line snapshots are still stored locally in CSV files. That works for now, but Streamlit Cloud can wipe local files on restart, so permanent storage should be the next infrastructure upgrade later.</div>',
    unsafe_allow_html=True,
)

# -----------------------------
# LIVE AUTO-REFRESH HERO
# -----------------------------
def render_live_snapshot():
    current_rows, compare_rows, error_message = get_live_board(
        leagues=league_filter,
        sportsbooks=book_filter,
        market_buckets=market_bucket_filter,
        confidence_levels=confidence_filter,
        min_bet=min_bet,
        max_bet=max_bet,
        max_total_exposure=max_total_exposure,
        max_sport_exposure=max_sport_exposure,
        max_event_exposure=max_event_exposure,
        max_book_exposure=max_book_exposure,
        max_prop_exposure=max_prop_exposure,
        min_books_quoting=min_books_quoting,
        min_edge_pct=min_edge_pct,
        min_score=min_score,
        min_minutes_to_start=min_minutes_to_start,
        max_bets_per_event=max_bets_per_event,
        limit_main_markets_per_event=limit_main_markets_per_event,
        only_final_bets=only_final_bets,
    )

    if error_message:
        st.warning(error_message)
        return

    final_bets = current_rows[current_rows["Final Status"] == "Bet"].copy()
    best_row = final_bets.iloc[0] if not final_bets.empty else None
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
                Best Book: **{best_row['Sportsbook']}** · Odds: **{best_row['Odds']}**  
                Edge: **{best_row['Edge %']:.2f}%** · Score: **{best_row['Bet Score']:.2f}** · Confidence: **{best_row['Confidence']}**  
                Stake To Bet: **${int(best_row['Stake To Bet'])}** · Trend: **{best_row['Line Trend']}**  
                Reason: *{best_row['Reason']}*
                """
            )
            if best_row["Link"]:
                st.markdown(f"[Open bet page]({best_row['Link']})")
        else:
            st.info("No bets qualify right now under the current rules.")

    with hero_right:
        st.markdown('<div class="small-label">Bet Range</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="big-value">${min_bet:.0f} - ${max_bet:.0f}</div>', unsafe_allow_html=True)
        st.markdown('<div class="small-label">Exposure Cap</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="big-value">${max_total_exposure:,.0f}</div>', unsafe_allow_html=True)
        st.markdown('<div class="small-label">Refresh Cadence</div>', unsafe_allow_html=True)
        st.markdown('<div class="big-value">15 min</div>', unsafe_allow_html=True)
        st.markdown('<div class="small-label">Last Refresh</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="big-value" style="font-size:1.0rem;">{refresh_time}</div>', unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


render_live_snapshot()

current_df, compare_df, live_error = get_live_board(
    leagues=league_filter,
    sportsbooks=book_filter,
    market_buckets=market_bucket_filter,
    confidence_levels=confidence_filter,
    min_bet=min_bet,
    max_bet=max_bet,
    max_total_exposure=max_total_exposure,
    max_sport_exposure=max_sport_exposure,
    max_event_exposure=max_event_exposure,
    max_book_exposure=max_book_exposure,
    max_prop_exposure=max_prop_exposure,
    min_books_quoting=min_books_quoting,
    min_edge_pct=min_edge_pct,
    min_score=min_score,
    min_minutes_to_start=min_minutes_to_start,
    max_bets_per_event=max_bets_per_event,
    limit_main_markets_per_event=limit_main_markets_per_event,
    only_final_bets=only_final_bets,
)

if live_error:
    st.warning(live_error)
    st.info("Add SPORTS_GAME_ODDS_API_KEY in Streamlit Secrets, then click Refresh now.")
    st.stop()

bet_log = attach_observed_clv(load_bet_log())
pending_log = bet_log[bet_log["Bet Status"] == "Pending"].copy()
settled_log = bet_log[bet_log["Bet Status"] == "Settled"].copy()
final_bets_live = current_df[current_df["Final Status"] == "Bet"].copy()
pass_bets_live = current_df[current_df["Final Status"] == "Pass"].copy()

if "ai_messages" not in st.session_state:
    st.session_state.ai_messages = [
        {
            "role": "assistant",
            "content": "Ask about the current board, bankroll risk, sportsbook comparisons, or why a bet ranks highly.",
        }
    ]
if "ai_text_input" not in st.session_state:
    st.session_state.ai_text_input = ""

# -----------------------------
# KPI RIBBON
# -----------------------------
realized_pnl = float(settled_log["PNL"].sum()) if not settled_log.empty else 0.0
current_bankroll = float(bankroll) + realized_pnl
total_settled_stake = float(settled_log["Stake"].sum()) if not settled_log.empty else 0.0
roi = (realized_pnl / total_settled_stake * 100) if total_settled_stake > 0 else 0.0
graded = settled_log[settled_log["Result"].isin(["Win", "Loss"])].copy()
win_rate = (graded["Result"].eq("Win").mean() * 100) if not graded.empty else 0.0
open_suggested_risk = float(final_bets_live["Stake To Bet"].sum()) if not final_bets_live.empty else 0.0
open_logged_risk = float(pending_log["Stake"].sum()) if not pending_log.empty else 0.0
strong_shop_alerts = int((compare_df["Shop Alert"] == "Strong Shop").sum()) if not compare_df.empty else 0
avg_edge_live = float(final_bets_live["Edge %"].mean()) if not final_bets_live.empty else 0.0
avg_score_live = float(final_bets_live["Bet Score"].mean()) if not final_bets_live.empty else 0.0
avg_observed_clv = float(bet_log["Observed CLV %"].mean()) if not bet_log.empty else 0.0
beat_market_count = int((bet_log["Observed CLV %"] > 0).sum()) if not bet_log.empty else 0

k1, k2, k3, k4 = st.columns(4)
with k1:
    render_kpi_card("Current Bankroll", f"${current_bankroll:,.2f}", delta=f"${realized_pnl:,.2f}", note="delta = realized P/L")
with k2:
    render_kpi_card("ROI", f"{roi:.1f}%", delta=f"Win rate {win_rate:.1f}%", note="settled bets only")
with k3:
    render_kpi_card("Live Final Bets", int(len(final_bets_live)), delta=f"Avg score {avg_score_live:.2f}", note="ranked after all filters and caps")
with k4:
    exposure_delta = f"{(open_suggested_risk / max_total_exposure * 100):.0f}% of cap" if max_total_exposure > 0 else "0% of cap"
    render_kpi_card("Open Suggested Risk", f"${open_suggested_risk:,.0f}", delta=exposure_delta, note="live board exposure, not logged tickets")

k5, k6, k7, k8 = st.columns(4)
with k5:
    render_kpi_card("Strong Shop Alerts", strong_shop_alerts, delta=f"Avg edge {avg_edge_live:.2f}%", note="bigger line gaps across books")
with k6:
    render_kpi_card("Pending Logged Risk", f"${open_logged_risk:,.2f}", delta=f"{len(pending_log)} pending", note="from tracked bets only")
with k7:
    render_kpi_card("Observed CLV", f"{avg_observed_clv:.2f}%", delta=f"{beat_market_count} beating market", note="latest seen line vs logged price")
with k8:
    render_kpi_card("Passes / Correlation", int(len(pass_bets_live)), delta="risk controls active", note="filtered out by logic or exposure")

# -----------------------------
# TABS
# -----------------------------
tabs = st.tabs(
    [
        "Overview",
        "Best Bets",
        "Compare Lines",
        "Quick Links",
        "DraftKings",
        "FanDuel",
        "Bet365",
        "PrizePicks",
        "AI Assistant",
        "Tracker",
        "Results",
        "Bankroll",
    ]
)

# -----------------------------
# OVERVIEW TAB
# -----------------------------
with tabs[0]:
    row1_left, row1_right = st.columns(2)
    with row1_left:
        fig = plot_bankroll_curve(settled_log, bankroll)
        if fig:
            safe_plotly_chart(fig, "overview_bankroll_curve")
        else:
            st.info("Settle a few bets to unlock the bankroll curve.")
    with row1_right:
        fig = plot_profit_by_sportsbook(settled_log)
        if fig:
            safe_plotly_chart(fig, "overview_profit_by_sportsbook")
        else:
            st.info("No sportsbook profit chart yet.")

    row2_left, row2_right = st.columns(2)
    with row2_left:
        fig = plot_exposure_by_sport(final_bets_live)
        if fig:
            safe_plotly_chart(fig, "overview_exposure_by_sport")
        else:
            st.info("No current live exposure to chart.")
    with row2_right:
        fig = plot_hit_rate_by_confidence(settled_log)
        if fig:
            safe_plotly_chart(fig, "overview_hit_rate_by_confidence")
        else:
            st.info("Need wins/losses to chart hit rate by confidence.")

    row3_left, row3_right = st.columns(2)
    with row3_left:
        fig = plot_edge_distribution(current_df)
        if fig:
            safe_plotly_chart(fig, "overview_edge_distribution")
        else:
            st.info("No final bets available for edge distribution.")
    with row3_right:
        fig = plot_line_gap_leaderboard(compare_df)
        if fig:
            safe_plotly_chart(fig, "overview_line_gap_leaderboard")
        else:
            st.info("No comparison rows available for line-gap leaderboard.")

    row4_left, row4_right = st.columns(2)
    with row4_left:
        fig = plot_observed_clv(bet_log)
        if fig:
            safe_plotly_chart(fig, "overview_observed_clv")
        else:
            st.info("No CLV chart available yet. Log bets and let odds update over time.")
    with row4_right:
        fig = plot_exposure_by_book(final_bets_live)
        if fig:
            safe_plotly_chart(fig, "overview_exposure_by_book")
        else:
            st.info("No sportsbook exposure chart available.")

    st.markdown('<div class="section-title">Top Final Bets</div>', unsafe_allow_html=True)
    if final_bets_live.empty:
        st.warning("No final bets available right now.")
    else:
        top_cards = final_bets_live.head(5).copy()
        for _, row in top_cards.iterrows():
            link_html = f'<br><a href="{row["Link"]}" target="_blank">Open bet page</a>' if row["Link"] else ""
            st.markdown(
                f"""
                <div class="best-bet">
                    <b>{row['Pick']}</b><br>
                    {row['Event']} · {row['Market']}<br>
                    Best Book: <b>{row['Sportsbook']}</b> · Odds: <b>{row['Odds']}</b><br>
                    Edge: <b>{row['Edge %']:.2f}%</b> · Score: <b>{row['Bet Score']:.2f}</b> · Confidence: <b>{row['Confidence']}</b><br>
                    Stake To Bet: <b>${int(row['Stake To Bet'])}</b> · Trend: <b>{row['Line Trend']}</b> · Exposure: <b>{row['Exposure Status']}</b><br>
                    Reason: <i>{row['Reason']}</i>
                    {link_html}
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown('<div class="section-title">Why the Top Bets Rank Here</div>', unsafe_allow_html=True)
    explain_rows = final_bets_live.head(3).copy()
    if explain_rows.empty:
        st.info("No final bets available for factor breakdown.")
    else:
        for i, row in explain_rows.iterrows():
            with st.expander(f"{row['Pick']} | {row['Sportsbook']} {row['Odds']} | Score {row['Bet Score']:.2f}", expanded=(i == explain_rows.index[0])):
                chip_html = (
                    f'<span class="factor-chip">Edge {row["Edge %"]:.2f}%</span>'
                    f'<span class="factor-chip">Line Gap {row["Best Line Gap %"]:.2f}%</span>'
                    f'<span class="factor-chip">Books {int(row["Books Quoting"])}</span>'
                    f'<span class="factor-chip">Trend {row["Line Trend"]}</span>'
                    f'<span class="factor-chip">Move {row["Line Move %"]:.2f}%</span>'
                    f'<span class="factor-chip">Stake ${int(row["Stake To Bet"])}</span>'
                )
                st.markdown(chip_html, unsafe_allow_html=True)
                st.write(f"**Core reasoning:** {row['Reason']}")
                st.write(f"**Factor math:** {build_factor_text(row)}")
                if row["Allocation Notes"]:
                    st.write(f"**Allocation note:** {row['Allocation Notes']}")
                if row["Correlation Flag"]:
                    st.write(f"**Correlation flag:** {row['Correlation Flag']}")
                if row["Opening Odds"]:
                    st.write(
                        f"**Line history:** opened at {row['Opening Odds']} and is now {row['Odds']} ({row['Line Trend']}, {row['Line Move %']:.2f}% implied-probability move)."
                    )

# -----------------------------
# BEST BETS TAB
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
            "Opening Odds",
            "Line Trend",
            "Line Move %",
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
            "Display Status",
            "Allocation Notes",
            "Reason",
            "Link",
        ]
    ]
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Line Move %": st.column_config.NumberColumn(format="%.2f%%"),
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


    st.markdown('<div class="section-title">Explain a Selected Final Bet</div>', unsafe_allow_html=True)
    explain_candidates = final_bets_live.copy()
    if explain_candidates.empty:
        st.info("No final bets available to explain right now.")
    else:
        explain_candidates["Explain Label"] = explain_candidates.apply(
            lambda row: f"{row['Event']} | {row['Pick']} | {row['Sportsbook']} {row['Odds']} | Score {row['Bet Score']:.2f}",
            axis=1,
        )
        selected_explain_label = st.selectbox(
            "Choose a final bet to break down",
            options=explain_candidates["Explain Label"].tolist(),
            key="best_bets_explain_select",
        )
        selected_explain_row = explain_candidates.loc[
            explain_candidates["Explain Label"] == selected_explain_label
        ].iloc[0]

        st.markdown(
            f"""
            <div class="card">
            <b>{selected_explain_row['Pick']}</b><br>
            {selected_explain_row['Event']} · {selected_explain_row['Market']}<br>
            Sportsbook: <b>{selected_explain_row['Sportsbook']}</b> · Odds: <b>{selected_explain_row['Odds']}</b><br>
            Edge: <b>{selected_explain_row['Edge %']:.2f}%</b> · Score: <b>{selected_explain_row['Bet Score']:.2f}</b> · Confidence: <b>{selected_explain_row['Confidence']}</b><br>
            Stake To Bet: <b>${int(selected_explain_row['Stake To Bet'])}</b> · Status: <b>{selected_explain_row['Display Status']}</b>
            </div>
            """,
            unsafe_allow_html=True,
        )
        explain_chip_html = (
            f'<span class="factor-chip">Edge {selected_explain_row["Edge %"]:.2f}%</span>'
            f'<span class="factor-chip">Line Gap {selected_explain_row["Best Line Gap %"]:.2f}%</span>'
            f'<span class="factor-chip">Books {int(selected_explain_row["Books Quoting"])}</span>'
            f'<span class="factor-chip">Trend {selected_explain_row["Line Trend"]}</span>'
            f'<span class="factor-chip">Move {selected_explain_row["Line Move %"]:.2f}%</span>'
            f'<span class="factor-chip">Stake ${int(selected_explain_row["Stake To Bet"])}</span>'
        )
        st.markdown(explain_chip_html, unsafe_allow_html=True)
        st.write(f"**Reason:** {selected_explain_row['Reason']}")
        st.write(f"**Factor math:** {build_factor_text(selected_explain_row)}")
        if selected_explain_row["Allocation Notes"]:
            st.write(f"**Allocation note:** {selected_explain_row['Allocation Notes']}")
        if selected_explain_row["Correlation Flag"]:
            st.write(f"**Correlation flag:** {selected_explain_row['Correlation Flag']}")
        if selected_explain_row["Opening Odds"]:
            st.write(
                f"**Line history:** opened at {selected_explain_row['Opening Odds']} and is now {selected_explain_row['Odds']} ({selected_explain_row['Line Trend']}, {selected_explain_row['Line Move %']:.2f}% implied-probability move)."
            )

# -----------------------------
# COMPARE LINES TAB
# -----------------------------
with tabs[2]:
    st.markdown('<div class="section-title">Compare Lines / Best Book</div>', unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        render_kpi_card("Strong Shop Alerts", strong_shop_alerts)
    with c2:
        good_shop = int((compare_df["Shop Alert"] == "Good Shop").sum()) if not compare_df.empty else 0
        render_kpi_card("Good Shop Alerts", good_shop)
    with c3:
        final_compare_bets = int((compare_df["Final Status"] == "Bet").sum()) if not compare_df.empty else 0
        render_kpi_card("Best-Book Final Bets", final_compare_bets)
    with c4:
        avg_gap = float(compare_df["Line Gap %"].mean()) if not compare_df.empty else 0.0
        render_kpi_card("Average Line Gap", f"{avg_gap:.2f}%")

    st.markdown(
        """
        <div class="card">
        This screen is focused on clean side-by-side price comparison across books.
        The heatmap has been removed to keep the layout simpler and easier to read.
        </div>
        """,
        unsafe_allow_html=True,
    )

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
                "Opening Odds",
                "Best Line Trend",
                "Best Line Move %",
                "Books Quoting",
                "Line Gap %",
                "Shop Alert",
                "Best Bet Score",
                "Best Confidence",
                "Stake To Bet",
                "Exposure Status",
                "Final Status",
                "Allocation Notes",
                "Best Reason",
                "Best Link",
            ]
        ],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Best Line Move %": st.column_config.NumberColumn(format="%.2f%%"),
            "Line Gap %": st.column_config.NumberColumn(format="%.2f%%"),
            "Best Bet Score": st.column_config.NumberColumn(format="%.2f"),
            "Stake To Bet": st.column_config.NumberColumn(format="$%d"),
            "Best Link": st.column_config.LinkColumn("Open"),
        },
    )

# -----------------------------
# QUICK LINKS TAB
# -----------------------------
with tabs[3]:
    st.markdown('<div class="section-title">Quick Links</div>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="card">
        Jump straight to each sportsbook from one place. Keep the comparison tab open in another browser tab and use these links to move faster.
        </div>
        """,
        unsafe_allow_html=True,
    )

    q1, q2 = st.columns(2)
    with q1:
        render_quick_link_card(
            "DraftKings",
            "Open DraftKings Sportsbook quickly after reviewing your line-shopping and final bet tabs.",
            "https://sportsbook.draftkings.com/",
        )
        render_quick_link_card(
            "Bet365",
            "Use this when the comparison board shows Bet365 holding the best current number.",
            "https://www.bet365.com/",
        )
    with q2:
        render_quick_link_card(
            "FanDuel",
            "Jump to FanDuel fast when it wins the best-book comparison for your preferred pick.",
            "https://sportsbook.fanduel.com/",
        )
        render_quick_link_card(
            "PrizePicks",
            "Open PrizePicks directly for prop and DFS-style plays that survive your risk controls.",
            "https://app.prizepicks.com/",
        )

    st.markdown('<div class="section-title">Fast Workflow</div>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="card">
        1. Use <b>Compare Lines</b> to find the best number.<br>
        2. Check <b>Best Bets</b> for the final approved stake.<br>
        3. Open the sportsbook from this page.<br>
        4. Log the ticket in <b>Tracker</b> after you place it.
        </div>
        """,
        unsafe_allow_html=True,
    )

# -----------------------------
# BOOK TABS
# -----------------------------
def render_book_tab(book_name):
    book_df = current_df[current_df["Sportsbook"] == book_name].copy()
    book_final = book_df[book_df["Final Status"] == "Bet"].copy()

    st.markdown(f'<div class="section-title">{book_name} Opportunities</div>', unsafe_allow_html=True)

    bx1, bx2, bx3 = st.columns(3)
    with bx1:
        render_kpi_card(f"{book_name} Final Bets", int(len(book_final)))
    with bx2:
        avg_edge_book = float(book_final["Edge %"].mean()) if not book_final.empty else 0.0
        render_kpi_card(f"{book_name} Average Edge", f"{avg_edge_book:.2f}%")
    with bx3:
        open_book_risk = float(book_final["Stake To Bet"].sum()) if not book_final.empty else 0.0
        render_kpi_card(f"{book_name} Open Risk", f"${open_book_risk:,.0f}")

    if book_df.empty:
        st.warning(f"No rows currently available for {book_name}.")
        return

    st.dataframe(
        book_df[
            [
                "Sport",
                "Event",
                "Market Bucket",
                "Market",
                "Pick",
                "Odds",
                "Opening Odds",
                "Line Trend",
                "Line Move %",
                "Edge %",
                "Bet Score",
                "Confidence",
                "Stake To Bet",
                "Exposure Status",
                "Display Status",
                "Reason",
                "Link",
            ]
        ],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Line Move %": st.column_config.NumberColumn(format="%.2f%%"),
            "Edge %": st.column_config.NumberColumn(format="%.2f%%"),
            "Bet Score": st.column_config.NumberColumn(format="%.2f"),
            "Stake To Bet": st.column_config.NumberColumn(format="$%d"),
            "Link": st.column_config.LinkColumn("Open"),
        },
    )

with tabs[4]:
    render_book_tab("DraftKings")

with tabs[5]:
    render_book_tab("FanDuel")

with tabs[6]:
    render_book_tab("Bet365")

with tabs[7]:
    render_book_tab("PrizePicks")

# -----------------------------
# AI ASSISTANT TAB
# -----------------------------
with tabs[8]:
    st.markdown('<div class="section-title">OpenAI Betting Assistant</div>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="card">
        Use preset prompts or ask your own question. The assistant answers using your current live board, comparison table, bankroll data, and tracked bet history.
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="section-title">Explain a Bet with AI</div>', unsafe_allow_html=True)
    ai_explain_candidates = final_bets_live.copy()
    if ai_explain_candidates.empty:
        st.info("No final bets are available for AI explanation right now.")
    else:
        ai_explain_candidates["Explain Label"] = ai_explain_candidates.apply(
            lambda row: f"{row['Event']} | {row['Pick']} | {row['Sportsbook']} {row['Odds']} | Score {row['Bet Score']:.2f}",
            axis=1,
        )
        ex1, ex2 = st.columns([3, 1])
        with ex1:
            selected_ai_explain_label = st.selectbox(
                "Pick a final bet for AI to explain",
                options=ai_explain_candidates["Explain Label"].tolist(),
                key="ai_explain_select",
            )
        with ex2:
            st.write("")
            st.write("")
            if st.button("Explain selected bet with AI", key="ai_explain_button"):
                selected_ai_row = ai_explain_candidates.loc[
                    ai_explain_candidates["Explain Label"] == selected_ai_explain_label
                ].iloc[0]
                run_ai_prompt(
                    build_explain_bet_prompt(selected_ai_row),
                    current_df=current_df,
                    compare_df=compare_df,
                    pending_log=pending_log,
                    settled_log=settled_log,
                    bankroll=bankroll,
                    max_total_exposure=max_total_exposure,
                )
                st.rerun()

    preset_prompts = {
        "Safest bets now": "What are the safest bets on the board right now and why?",
        "Strongest edge": "Which current bets have the strongest edge and best line-shopping value?",
        "Risk check": "Where am I overexposed right now, and what should I avoid stacking?",
        "Book compare": "Compare DraftKings, FanDuel, Bet365, and PrizePicks for today's best opportunities.",
        "Avoid list": "Which bets should I avoid right now and why?",
        "Bankroll summary": "Summarize my bankroll risk and tell me how aggressive I should be right now.",
        "Explain top bet": "Explain the top-ranked final bet in plain English and tell me the main reasons it is ahead of the others.",
    }

    pcols = st.columns(3)
    clicked_prompt = None
    for idx, (label, prompt_value) in enumerate(preset_prompts.items()):
        with pcols[idx % 3]:
            if st.button(label, key=f"ai_preset_{idx}"):
                clicked_prompt = prompt_value

    if clicked_prompt:
        run_ai_prompt(
            clicked_prompt,
            current_df=current_df,
            compare_df=compare_df,
            pending_log=pending_log,
            settled_log=settled_log,
            bankroll=bankroll,
            max_total_exposure=max_total_exposure,
        )
        st.rerun()

    for msg in st.session_state.ai_messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    with st.form("ai_chat_form"):
        ai_prompt = st.text_input(
            "Ask AI about today's board, bankroll, comparisons, or pass reasons",
            key="ai_text_input",
            placeholder="Example: Why is the top bet ranked above the others right now?",
        )
        submitted_ai = st.form_submit_button("Ask AI")

    if submitted_ai and ai_prompt.strip():
        with st.spinner("Reviewing the live board..."):
            run_ai_prompt(
                ai_prompt,
                current_df=current_df,
                compare_df=compare_df,
                pending_log=pending_log,
                settled_log=settled_log,
                bankroll=bankroll,
                max_total_exposure=max_total_exposure,
            )
        st.session_state.ai_text_input = ""
        st.rerun()

    if not st.secrets.get("OPENAI_API_KEY", ""):
        st.info("Add OPENAI_API_KEY to Streamlit Secrets to activate the assistant. You can also optionally set OPENAI_MODEL.")

# -----------------------------
# TRACKER TAB
# -----------------------------
with tabs[9]:
    st.markdown('<div class="section-title">Bet Tracker</div>', unsafe_allow_html=True)

    log_col, settle_col = st.columns(2)

    with log_col:
        st.markdown(
            """
            <div class="card">
            <b>Log Final Bet</b><br>
            Only the fully approved final bets appear here, after shopping and exposure rules are applied.
            </div>
            """,
            unsafe_allow_html=True,
        )

        log_candidates = final_bets_live.copy()
        if log_candidates.empty:
            st.warning("No final bets available to log.")
        else:
            log_candidates["Log Label"] = log_candidates.apply(
                lambda row: f"{row['Event']} | {row['Pick']} | {row['Sportsbook']} {row['Odds']} | Stake ${int(row['Stake To Bet'])} | Score {row['Bet Score']:.2f}",
                axis=1,
            )

            with st.form("log_bet_form"):
                selected_log_label = st.selectbox("Choose a final bet", options=log_candidates["Log Label"].tolist())
                submitted_log = st.form_submit_button("Log Selected Bet")
                if submitted_log:
                    selected_row = log_candidates.loc[log_candidates["Log Label"] == selected_log_label].iloc[0]
                    ok, msg = log_bet_from_row(selected_row)
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.warning(msg)

    with settle_col:
        st.markdown(
            """
            <div class="card">
            <b>Settle Pending Bet</b><br>
            Mark a pending bet as Win, Loss, or Push to update bankroll, ROI, and results charts.
            </div>
            """,
            unsafe_allow_html=True,
        )

        pending_now = attach_observed_clv(load_bet_log())
        pending_now = pending_now[pending_now["Bet Status"] == "Pending"].copy()

        if pending_now.empty:
            st.info("No pending bets to settle.")
        else:
            pending_now["Settle Label"] = pending_now.apply(
                lambda row: f"{row['Bet ID']} | {row['Event']} | {row['Pick']} | {row['Sportsbook']} {row['Odds']} | Stake ${row['Stake']:,.2f}",
                axis=1,
            )

            with st.form("settle_bet_form"):
                selected_settle_label = st.selectbox("Choose a pending bet", options=pending_now["Settle Label"].tolist())
                settle_result = st.radio("Result", ["Win", "Loss", "Push"], horizontal=True)
                submitted_settle = st.form_submit_button("Settle Bet")
                if submitted_settle:
                    selected_bet_id = selected_settle_label.split(" | ")[0]
                    ok, msg = settle_bet(selected_bet_id, settle_result)
                    if ok:
                        st.success(msg)
                        st.rerun()
                    else:
                        st.warning(msg)

    st.markdown('<div class="section-title">Pending Bet Log</div>', unsafe_allow_html=True)
    pending_view = attach_observed_clv(load_bet_log())
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
                    "Observed CLV %",
                    "CLV Label",
                    "Reason",
                ]
            ],
            use_container_width=True,
            hide_index=True,
            column_config={
                "Stake": st.column_config.NumberColumn(format="$%.2f"),
                "Bet Score": st.column_config.NumberColumn(format="%.2f"),
                "Observed CLV %": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )

# -----------------------------
# RESULTS TAB
# -----------------------------
with tabs[10]:
    st.markdown('<div class="section-title">Performance Results</div>', unsafe_allow_html=True)

    if settled_log.empty:
        st.info("No settled bets yet. Log and settle a few bets to unlock the full performance dashboard.")
    else:
        results_top1, results_top2 = st.columns(2)
        with results_top1:
            fig = plot_profit_by_market(settled_log)
            if fig:
                safe_plotly_chart(fig, "results_profit_by_market")
        with results_top2:
            fig = plot_score_vs_pnl(settled_log)
            if fig:
                safe_plotly_chart(fig, "results_score_vs_pnl")

        results_bottom1, results_bottom2 = st.columns(2)
        with results_bottom1:
            fig = plot_hit_rate_by_confidence(settled_log)
            if fig:
                safe_plotly_chart(fig, "results_hit_rate_by_confidence")
        with results_bottom2:
            fig = plot_observed_clv(bet_log)
            if fig:
                safe_plotly_chart(fig, "results_observed_clv")

        st.markdown("#### Settled Bet History")
        st.dataframe(
            settled_log[
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
                    "Observed CLV %",
                    "CLV Label",
                ]
            ].sort_values("Settled At", ascending=False),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Stake": st.column_config.NumberColumn(format="$%.2f"),
                "PNL": st.column_config.NumberColumn(format="$%.2f"),
                "Bet Score": st.column_config.NumberColumn(format="%.2f"),
                "Observed CLV %": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )

# -----------------------------
# BANKROLL TAB
# -----------------------------
with tabs[11]:
    st.markdown('<div class="section-title">Bankroll and Risk Controls</div>', unsafe_allow_html=True)

    b1, b2, b3, b4 = st.columns(4)
    with b1:
        render_kpi_card("Starting Bankroll", f"${bankroll:,.2f}")
    with b2:
        render_kpi_card("Current Bankroll", f"${current_bankroll:,.2f}", delta=f"${realized_pnl:,.2f}")
    with b3:
        render_kpi_card("Logged Open Risk", f"${open_logged_risk:,.2f}")
    with b4:
        render_kpi_card("Live Suggested Risk", f"${open_suggested_risk:,.2f}", delta=f"{(open_suggested_risk / max_total_exposure * 100):.0f}% of cap" if max_total_exposure > 0 else "0% of cap")

    risk_left, risk_right = st.columns(2)
    with risk_left:
        st.markdown(
            f"""
            <div class="card">
            <b>Live risk policy</b><br>
            • Bet sizes stay between ${min_bet:.0f} and ${max_bet:.0f}<br>
            • Total exposure cap: ${max_total_exposure:,.0f}<br>
            • Per-sport cap: ${max_sport_exposure:,.0f}<br>
            • Per-event cap: ${max_event_exposure:,.0f}<br>
            • Per-book cap: ${max_book_exposure:,.0f}<br>
            • Prop cap: ${max_prop_exposure:,.0f}
            </div>
            """,
            unsafe_allow_html=True,
        )
    with risk_right:
        st.markdown(
            f"""
            <div class="card">
            <b>Logic filters</b><br>
            • Minimum books quoting: {int(min_books_quoting)}<br>
            • Minimum edge: {min_edge_pct:.1f}%<br>
            • Minimum score: {min_score:.1f}<br>
            • Minimum minutes to start: {int(min_minutes_to_start)}<br>
            • Max bets per event: {int(max_bets_per_event)}<br>
            • One main market per event: {"On" if limit_main_markets_per_event else "Off"}
            </div>
            """,
            unsafe_allow_html=True,
        )

        if not pass_bets_live.empty:
            st.markdown("#### Why the app passed on some bets")
            st.dataframe(
                pass_bets_live[
                    [
                        "Event",
                        "Pick",
                        "Sportsbook",
                        "Edge %",
                        "Bet Score",
                        "Exposure Status",
                        "Allocation Notes",
                        "Correlation Flag",
                    ]
                ].head(20),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Edge %": st.column_config.NumberColumn(format="%.2f%%"),
                    "Bet Score": st.column_config.NumberColumn(format="%.2f"),
                },
            )
