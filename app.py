from datetime import datetime, timezone
from html import escape
import xml.etree.ElementTree as ET

import pandas as pd
import requests
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
BOOK_URLS = {
    "DraftKings": "https://sportsbook.draftkings.com/",
    "FanDuel": "https://sportsbook.fanduel.com/",
    "Bet365": "https://www.bet365.com/",
    "PrizePicks": "https://app.prizepicks.com/",
}
MAIN_MARKETS = {"Moneyline", "Spread", "Total"}
PROP_MARKETS = {"Player Prop", "DFS Prop", "Team Total"}
NEWS_FEEDS = {
    "Top Headlines": "https://www.espn.com/espn/rss/news",
    "NFL": "https://www.espn.com/espn/rss/nfl/news",
    "NBA": "https://www.espn.com/espn/rss/nba/news",
    "MLB": "https://www.espn.com/espn/rss/mlb/news",
    "NHL": "https://www.espn.com/espn/rss/nhl/news",
    "College Football": "https://www.espn.com/espn/rss/ncf/news",
}
LEAGUE_TO_NEWS = {
    "NFL": "NFL",
    "NBA": "NBA",
    "MLB": "MLB",
    "NHL": "NHL",
}


def get_news_feed_names(leagues):
    names = ["Top Headlines"]
    for league in leagues or []:
        mapped = LEAGUE_TO_NEWS.get(league)
        if mapped and mapped in NEWS_FEEDS and mapped not in names:
            names.append(mapped)
    return names


@st.cache_data(ttl=900, show_spinner=False)
def fetch_news_feed(feed_name, limit=12):
    url = NEWS_FEEDS.get(feed_name)
    if not url:
        return []
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        items = []
        for item in root.findall(".//item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            description = (item.findtext("description") or "").strip()
            items.append({
                "feed": feed_name,
                "title": title,
                "link": link,
                "pub_date": pub_date,
                "description": description,
            })
        return items
    except Exception:
        return []


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
        txt = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(txt)
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
    if "player" in text or "points" in text or "rebounds" in text or "assists" in text or "hits" in text:
        return "Player Prop"
    if "team total" in text:
        return "Team Total"
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


def make_link_markdown(url):
    if not url:
        return ""
    return f"[Open]({url})"


def format_minutes(value):
    if value is None or pd.isna(value):
        return "—"
    if value < 0:
        return "Live/Started"
    hours = int(value // 60)
    mins = int(value % 60)
    if hours == 0:
        return f"{mins}m"
    return f"{hours}h {mins}m"


def strong_shop_alerts(df):
    if df.empty:
        return 0
    return int((df["Best Line Gap %"] >= 3.0).sum())


def market_sort_value(bucket):
    order = {
        "Moneyline": 1,
        "Spread": 2,
        "Total": 3,
        "Team Total": 4,
        "Player Prop": 5,
        "DFS Prop": 6,
        "Other": 7,
    }
    return order.get(bucket, 8)


def make_badge_html(text, variant):
    return f'<span class="badge badge-{variant}">{text}</span>'


def confidence_badge_text(value):
    mapping = {
        "Elite": "🔵 Elite",
        "High": "🟢 High",
        "Medium": "🟡 Medium",
        "Low": "⚪ Low",
    }
    return mapping.get(value, str(value))


def move_badge_text(value):
    mapping = {
        "Improving": "📈 Improving",
        "Flat": "➖ Flat",
        "Worse": "📉 Worse",
        "New": "🆕 New",
    }
    return mapping.get(value, str(value))


def decision_badge_text(value):
    mapping = {
        "Within Limits": "✅ Within Limits",
        "Trimmed": "✂️ Trimmed",
        "Correlation Pass": "🚫 Correlation Pass",
        "Exposure Pass": "⛔ Exposure Pass",
        "Below Threshold": "⚪ Below Threshold",
        "Pending Review": "🕒 Pending Review",
    }
    return mapping.get(value, str(value))


def build_badges_html(row):
    conf_map = {"Elite": "elite", "High": "high", "Medium": "medium", "Low": "low"}
    move_map = {"Improving": "improving", "Flat": "flat", "Worse": "worse", "New": "new"}
    decision_value = row.get("Allocation Status", "")
    decision_map = {
        "Within Limits": "within",
        "Trimmed": "trimmed",
        "Correlation Pass": "blocked",
        "Exposure Pass": "blocked",
        "Below Threshold": "low",
        "Pending Review": "flat",
    }
    pieces = [
        make_badge_html(str(row.get("Confidence", "")), conf_map.get(row.get("Confidence", ""), "flat")),
        make_badge_html(str(row.get("Move Label", "")), move_map.get(row.get("Move Label", ""), "flat")),
        make_badge_html(str(decision_value), decision_map.get(decision_value, "flat")),
    ]
    return "".join(pieces)


def watchlist_match(row, query):
    if not query:
        return False
    q = str(query).strip().lower()
    if not q:
        return False
    haystack = " ".join([
        str(row.get("Event", "")),
        str(row.get("Pick", "")),
        str(row.get("Market", "")),
        str(row.get("Sportsbook", "")),
        str(row.get("Sport", "")),
    ]).lower()
    return q in haystack


def render_quick_links():
    st.markdown('<div class="section-title">Quick Sportsbook Links</div>', unsafe_allow_html=True)
    cols = st.columns(4)
    books = [
        ("DraftKings", "🟩", "Fastest major-book line check"),
        ("FanDuel", "🟦", "Popular market comparison book"),
        ("Bet365", "🟢", "Strong alt-line shopping option"),
        ("PrizePicks", "🟧", "DFS-style prop board access"),
    ]
    for col, (book, icon, sub) in zip(cols, books):
        with col:
            st.markdown(
                f"""
                <div class="book-link-card">
                    <div class="book-link-title">{icon} {book}</div>
                    <div class="book-link-sub">{sub}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            try:
                st.link_button(f"Open {book}", BOOK_URLS[book], use_container_width=True)
            except Exception:
                st.markdown(f"[Open {book}]({BOOK_URLS[book]})")


def get_same_pick_market_rows(df, row):
    if df is None or df.empty:
        return pd.DataFrame()
    same = df[
        (df["Event"] == row.get("Event"))
        & (df["Pick"] == row.get("Pick"))
        & (df["Market"] == row.get("Market"))
    ].copy()
    if same.empty:
        return same
    return same.sort_values(["Implied Prob", "Bet Score"], ascending=[True, False]).reset_index(drop=True)


def build_book_snapshot_html(row, compare_df=None):
    same = get_same_pick_market_rows(compare_df, row)
    if same.empty:
        return "<div class='mini-note'>Only one book is currently quoted for this pick.</div>"

    blocks = []
    top_book = str(same.iloc[0].get("Sportsbook", ""))
    for _, r in same.iterrows():
        is_best = str(r.get("Sportsbook", "")) == top_book
        status = "Best price" if is_best else "Quoted"
        extra = "book-best" if is_best else ""
        blocks.append(
            f"""
            <div class="book-quote-card {extra}">
                <div class="book-quote-top">{r.get('Sportsbook', 'Book')}</div>
                <div class="book-quote-odds">{r.get('Odds', '—')}</div>
                <div class="book-quote-sub">{status} · Imp {float(r.get('Implied Prob', 0)):.2f}%</div>
            </div>
            """
        )
    return "<div class='book-quote-grid'>" + "".join(blocks) + "</div>"


def build_explain_bet_markdown(row, compare_df=None):
    same = get_same_pick_market_rows(compare_df, row)
    notes = []
    notes.append(f"**Why the board likes it:** {row.get('Reason', 'No base reason provided.')}")
    notes.append(f"**Current price:** {row.get('Sportsbook', 'Book')} {row.get('Odds', '')} with implied probability {row.get('Implied Prob', 0):.2f}%.")
    notes.append(f"**Model vs market:** model probability {row.get('Model Prob', 0):.2f}% vs edge {row.get('Edge %', 0):.2f}%.")
    notes.append(f"**Score + sizing:** bet score {row.get('Bet Score', 0):.2f}, recommended ${int(row.get('Recommended Bet', 0))}, final allocation ${int(row.get('Final Bet', 0))}.")
    notes.append(f"**Line movement:** previous odds {row.get('Prev Odds', '—')} to current {row.get('Odds', '')}, labeled {row.get('Move Label', 'Flat')} ({row.get('Line Move %', 0):+.2f}%).")
    notes.append(f"**Risk controls:** {row.get('Allocation Status', '—')}. {row.get('Pass Reason', '') or 'No extra pass note; the play fits the current controls.'}")
    if not same.empty:
        best = same.iloc[0]
        line_gap = float(same["Implied Prob"].max() - same["Implied Prob"].min()) if len(same) > 1 else 0.0
        notes.append(
            f"**Best-book context:** best book is {best.get('Sportsbook', '—')} at {best.get('Odds', '—')} with a line gap of {line_gap:.2f}% across {len(same)} books."
        )
        if str(best.get('Sportsbook', '')) != str(row.get('Sportsbook', '')):
            notes.append(
                f"**Important:** this row is not the best live number right now. The best current price is at **{best.get('Sportsbook', '—')}**."
            )
    return "\n\n".join(notes)


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

                deep_link = quote.get("deeplink") or event_links.get(book_id, "")
                sportsbook_name = TARGET_BOOKS[book_id]
                market_bucket = classify_market(market_name, pick_label, sportsbook_name)
                row_key = f"{event_id}|{odd_id}|{book_id}"

                rows.append(
                    {
                        "Row Key": row_key,
                        "Event ID": event_id,
                        "Odd ID": odd_id,
                        "Sport": league_id or sport_id,
                        "Event": event_name,
                        "Home Team": home_name,
                        "Away Team": away_name,
                        "Start Time": starts_at,
                        "Minutes To Start": minutes_to_start(starts_at),
                        "Market": market_name,
                        "Market Bucket": market_bucket,
                        "Pick": pick_label,
                        "Sportsbook": sportsbook_name,
                        "Sportsbook ID": book_id,
                        "Odds": str(odds_value),
                        "Implied Prob": implied_prob,
                        "Line": quote.get("spread") or quote.get("overUnder") or "",
                        "Last Update": quote.get("lastUpdatedAt", ""),
                        "Link": deep_link,
                    }
                )

    return pd.DataFrame(rows)


def confidence_from_score(score):
    if score >= 7.0:
        return "Elite"
    if score >= 5.0:
        return "High"
    if score >= 3.0:
        return "Medium"
    return "Low"


def market_weight(bucket):
    weights = {
        "Moneyline": 1.25,
        "Spread": 1.20,
        "Total": 1.10,
        "Team Total": 0.85,
        "Player Prop": 0.55,
        "DFS Prop": 0.35,
        "Other": 0.40,
    }
    return weights.get(bucket, 0.40)


def time_penalty(minutes):
    if minutes is None:
        return 0.0
    if minutes < 0:
        return -2.0
    if minutes < 15:
        return -1.3
    if minutes < 60:
        return -0.8
    if minutes < 180:
        return -0.3
    return 0.0


def book_penalty(book_name):
    if book_name == "PrizePicks":
        return -0.6
    return 0.0


def bet_size_from_score(edge, score, min_bet, max_bet):
    if edge < 1.0 or score < 3.0:
        return 0
    if score < 4.0:
        return int(min_bet)
    if score < 5.0:
        return int(min(max_bet, max(min_bet, 3)))
    if score < 6.0:
        return int(min(max_bet, max(min_bet, 5)))
    if score < 7.0:
        return int(min(max_bet, max(min_bet, 7)))
    return int(min(max_bet, max(min_bet, 10)))


def build_reason(row):
    parts = []

    if row["Is Best Price"]:
        parts.append(f"best current price across {int(row['Books Quoting'])} books")
    else:
        parts.append(f"positive price edge vs {int(row['Books Quoting'])} book consensus")

    bucket = row["Market Bucket"]
    if bucket in MAIN_MARKETS:
        parts.append(f"{bucket.lower()} market carries stronger confidence")
    elif bucket in PROP_MARKETS:
        parts.append("prop market keeps stake more conservative")

    mins = row["Minutes To Start"]
    if mins is not None:
        if mins >= 180:
            parts.append("not too close to lock")
        elif mins >= 60:
            parts.append("moderate time before start")
        else:
            parts.append("close to start, so confidence is reduced")

    if row["Sportsbook"] == "PrizePicks":
        parts.append("PrizePicks lines are treated more cautiously")

    return " • ".join(parts)


def apply_smart_scoring(df, min_bet, max_bet):
    if df.empty:
        return df

    market_stats = (
        df.groupby(["Event ID", "Odd ID"])["Implied Prob"]
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

    scored = df.merge(market_stats, on=["Event ID", "Odd ID"], how="left")
    scored["Prob StdDev"] = scored["Prob StdDev"].fillna(0.0)
    scored["Model Prob"] = scored["Consensus Prob"].round(2)
    scored["Edge %"] = (scored["Consensus Prob"] - scored["Implied Prob"]).round(2)
    scored["Best Line Gap %"] = (scored["Worst Price Prob"] - scored["Implied Prob"]).round(2)
    scored["Is Best Price"] = scored["Implied Prob"] <= (scored["Best Price Prob"] + 0.0001)

    scored["Market Weight"] = scored["Market Bucket"].apply(market_weight)
    scored["Time Penalty"] = scored["Minutes To Start"].apply(time_penalty)
    scored["Book Penalty"] = scored["Sportsbook"].apply(book_penalty)
    scored["Books Bonus"] = scored["Books Quoting"].apply(lambda x: min((x - 1) * 0.55, 2.20))

    scored["Bet Score"] = (
        scored["Edge %"] * 0.95
        + scored["Best Line Gap %"] * 0.35
        + scored["Books Bonus"]
        + scored["Market Weight"]
        + scored["Time Penalty"]
        + scored["Book Penalty"]
    ).round(2)

    scored["AI Score"] = scored["Bet Score"]
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
    scored["Status"] = scored["Recommended Bet"].apply(lambda x: "Bet" if x > 0 else "No Bet")
    scored["Reason"] = scored.apply(build_reason, axis=1)
    scored["Market Rank"] = scored["Market Bucket"].apply(market_sort_value)
    scored["Rank Score"] = scored["Bet Score"]
    scored["Context Score"] = 0.0
    scored["Context Tags"] = "Core model only"
    return scored


def apply_line_movement(df):
    if df.empty:
        return df

    if "line_snapshots" not in st.session_state:
        st.session_state["line_snapshots"] = {}
    if "line_histories" not in st.session_state:
        st.session_state["line_histories"] = {}

    snapshots = st.session_state["line_snapshots"]
    histories = st.session_state["line_histories"]

    prev_odds = []
    prev_probs = []
    move_values = []
    move_labels = []

    for _, row in df.iterrows():
        key = row["Row Key"]
        current_odds = row["Odds"]
        current_prob = float(row["Implied Prob"])
        previous = snapshots.get(key)

        if previous is None:
            prev_odds.append("—")
            prev_probs.append(None)
            move_values.append(0.0)
            move_labels.append("New")
        else:
            prev_odds.append(previous.get("odds", "—"))
            prev_prob = float(previous.get("implied_prob", current_prob))
            prev_probs.append(prev_prob)
            move = round(prev_prob - current_prob, 2)
            move_values.append(move)
            if move >= 1.0:
                move_labels.append("Improving")
            elif move <= -1.0:
                move_labels.append("Worse")
            else:
                move_labels.append("Flat")

        hist = histories.get(key, [])
        hist = (hist + [current_prob])[-6:]
        histories[key] = hist
        snapshots[key] = {"odds": current_odds, "implied_prob": current_prob}

    moved = df.copy()
    moved["Prev Odds"] = prev_odds
    moved["Prev Implied Prob"] = prev_probs
    moved["Line Move %"] = move_values
    moved["Move Label"] = move_labels
    moved["Move Favorability"] = moved["Line Move %"].apply(
        lambda x: "Better Number" if x >= 1.0 else ("Worse Number" if x <= -1.0 else "Little Change")
    )
    return moved


def build_allocation_note(row, note):
    base_reason = row.get("Reason", "")
    if base_reason and note:
        return f"{base_reason} • {note}"
    return base_reason or note


def apply_risk_controls(
    df,
    min_bet,
    max_total_exposure,
    max_sport_exposure,
    max_event_exposure,
    max_book_exposure,
    max_prop_exposure,
    use_correlation_guard,
):
    if df.empty:
        return df

    controlled = df.copy()
    controlled["Final Bet"] = 0
    controlled["Final Status"] = controlled["Status"]
    controlled["Allocation Status"] = controlled["Status"].map({"No Bet": "Below Threshold", "Bet": "Pending Review"}).fillna("Below Threshold")
    controlled["Pass Reason"] = ""
    controlled["Correlation Flag"] = "Clear"

    total_used = 0.0
    sport_used = {}
    event_used = {}
    book_used = {}
    prop_used = 0.0
    main_event_taken = set()
    prop_event_counts = {}

    sort_score = "Rank Score" if "Rank Score" in controlled.columns else "Bet Score"
    candidates = controlled[controlled["Status"] == "Bet"].sort_values(
        [sort_score, "Edge %", "Books Quoting", "Market Rank"],
        ascending=[False, False, False, True],
    )

    for idx, row in candidates.iterrows():
        event_id = row["Event ID"]
        sport = row["Sport"]
        book = row["Sportsbook"]
        bucket = row["Market Bucket"]
        recommended = float(row["Recommended Bet"])
        note_parts = []

        if use_correlation_guard:
            if bucket in MAIN_MARKETS and event_id in main_event_taken:
                controlled.at[idx, "Final Status"] = "Pass"
                controlled.at[idx, "Allocation Status"] = "Correlation Pass"
                controlled.at[idx, "Pass Reason"] = build_allocation_note(row, "same-event main market already selected")
                controlled.at[idx, "Correlation Flag"] = "Blocked"
                continue

            if bucket in PROP_MARKETS and prop_event_counts.get(event_id, 0) >= 2:
                controlled.at[idx, "Final Status"] = "Pass"
                controlled.at[idx, "Allocation Status"] = "Correlation Pass"
                controlled.at[idx, "Pass Reason"] = build_allocation_note(row, "too many correlated props already selected in same event")
                controlled.at[idx, "Correlation Flag"] = "Blocked"
                continue

        remaining_total = max_total_exposure - total_used
        remaining_sport = max_sport_exposure - sport_used.get(sport, 0.0)
        remaining_event = max_event_exposure - event_used.get(event_id, 0.0)
        remaining_book = max_book_exposure - book_used.get(book, 0.0)
        remaining_prop = max_prop_exposure - prop_used if bucket in PROP_MARKETS else float("inf")

        alloc = min(recommended, remaining_total, remaining_sport, remaining_event, remaining_book, remaining_prop)
        alloc = int(max(0, alloc))

        if alloc < min_bet:
            controlled.at[idx, "Final Status"] = "Pass"
            controlled.at[idx, "Allocation Status"] = "Exposure Pass"
            reasons = []
            if remaining_total < min_bet:
                reasons.append("total exposure cap reached")
            if remaining_sport < min_bet:
                reasons.append("sport cap reached")
            if remaining_event < min_bet:
                reasons.append("event cap reached")
            if remaining_book < min_bet:
                reasons.append("sportsbook cap reached")
            if bucket in PROP_MARKETS and remaining_prop < min_bet:
                reasons.append("prop cap reached")
            reason_text = ", ".join(reasons) if reasons else "allocation rules blocked this play"
            controlled.at[idx, "Pass Reason"] = build_allocation_note(row, reason_text)
            continue

        controlled.at[idx, "Final Bet"] = alloc
        controlled.at[idx, "Final Status"] = "Bet"
        controlled.at[idx, "Allocation Status"] = "Trimmed" if alloc < recommended else "Within Limits"
        if alloc < recommended:
            note_parts.append("stake trimmed by exposure rules")

        total_used += alloc
        sport_used[sport] = sport_used.get(sport, 0.0) + alloc
        event_used[event_id] = event_used.get(event_id, 0.0) + alloc
        book_used[book] = book_used.get(book, 0.0) + alloc
        if bucket in PROP_MARKETS:
            prop_used += alloc
            prop_event_counts[event_id] = prop_event_counts.get(event_id, 0) + 1
        if bucket in MAIN_MARKETS:
            main_event_taken.add(event_id)

        controlled.at[idx, "Pass Reason"] = build_allocation_note(row, " • ".join(note_parts))

    return controlled


st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(180deg, #f5f8fc 0%, #edf3fb 100%);
        color: #142235;
    }

    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #edf5ff 0%, #e1ecfb 100%);
        border-right: 1px solid #c8d8ee;
    }

    .main-title {
        font-size: 2.8rem;
        font-weight: 800;
        color: #163b68;
        margin-bottom: 0.2rem;
    }

    .sub-title {
        font-size: 1rem;
        color: #476383;
        margin-bottom: 1.0rem;
    }

    .hero-box {
        background: linear-gradient(135deg, #ffffff 0%, #f6fbff 100%);
        border: 1px solid #cfe0f5;
        border-radius: 18px;
        padding: 20px 24px;
        margin-bottom: 18px;
        box-shadow: 0 10px 24px rgba(25, 60, 110, 0.10);
    }

    .card {
        background: #ffffff;
        border: 1px solid #d8e6f7;
        border-radius: 18px;
        padding: 18px;
        box-shadow: 0 8px 22px rgba(16, 46, 80, 0.08);
        margin-bottom: 16px;
    }

    .best-bet {
        background: linear-gradient(135deg, #f8fbff 0%, #eef6ff 100%);
        border: 1px solid #bdd5f1;
        border-left: 6px solid #2b73d5;
        border-radius: 18px;
        padding: 18px;
        box-shadow: 0 8px 22px rgba(16, 46, 80, 0.08);
        margin-bottom: 16px;
    }

    .section-title {
        font-size: 1.3rem;
        font-weight: 800;
        color: #173b67;
        margin-top: 8px;
        margin-bottom: 10px;
    }

    .small-label {
        color: #5e7898;
        font-size: 0.88rem;
        font-weight: 600;
    }

    .big-value {
        color: #173b67;
        font-size: 1.55rem;
        font-weight: 900;
    }

    .kpi-card {
        background: linear-gradient(180deg, #ffffff 0%, #f6fbff 100%);
        border: 1px solid #d8e6f7;
        border-top: 4px solid #2b73d5;
        border-radius: 16px;
        padding: 14px 16px;
        box-shadow: 0 8px 18px rgba(16, 46, 80, 0.07);
        margin-bottom: 8px;
    }

    .kpi-label {
        color: #5f7b9a;
        font-size: 0.82rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: .3px;
    }

    .kpi-value {
        color: #163b68;
        font-size: 1.35rem;
        font-weight: 900;
        margin-top: 6px;
    }

    div[data-baseweb="select"] > div,
    div[data-baseweb="base-input"] > div {
        color: black !important;
        background: #FFFFFF !important;
    }

    div[data-baseweb="select"] input,
    div[data-baseweb="base-input"] input {
        color: black !important;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }

    .stTabs [data-baseweb="tab"] {
        background: rgba(255,255,255,0.82);
        border: 1px solid #d5e4f5;
        border-radius: 12px;
        color: #173b67;
        padding: 10px 14px;
        font-weight: 700;
    }

    .stTabs [aria-selected="true"] {
        background: #dfeeff !important;
        color: #163b68 !important;
    }

    .book-link-card {
        background: linear-gradient(135deg, #ffffff 0%, #f3f8ff 100%);
        border: 1px solid #cfe1f7;
        border-top: 5px solid #2b73d5;
        border-radius: 18px;
        padding: 14px 14px 12px 14px;
        box-shadow: 0 10px 22px rgba(22, 59, 104, 0.09);
        min-height: 88px;
        margin-bottom: 10px;
    }

    .book-link-title {
        color: #173b67;
        font-size: 1.05rem;
        font-weight: 900;
        margin-bottom: 6px;
    }

    .book-link-sub {
        color: #5b7393;
        font-size: 0.86rem;
        font-weight: 600;
    }

    .badge {
        display: inline-block;
        padding: 5px 10px;
        border-radius: 999px;
        font-size: 0.78rem;
        font-weight: 800;
        margin: 6px 8px 4px 0;
        border: 1px solid transparent;
    }

    .badge-elite { background: #d9edff; color: #0f4d8a; border-color: #b7dafc; }
    .badge-high { background: #ddf7ea; color: #157347; border-color: #bde7d1; }
    .badge-medium { background: #fff4d8; color: #8a6100; border-color: #f2e0a8; }
    .badge-low { background: #eef3f8; color: #5b6f84; border-color: #d9e4ef; }
    .badge-improving { background: #dff7ea; color: #156f49; border-color: #bbe7cd; }
    .badge-flat { background: #edf3f9; color: #576f86; border-color: #d6e3ef; }
    .badge-worse { background: #fde6e8; color: #a53b47; border-color: #f6c5ca; }
    .badge-new { background: #e7edff; color: #415bb5; border-color: #cbd7ff; }
    .badge-within { background: #dff3ff; color: #155b9a; border-color: #b8ddfb; }
    .badge-trimmed { background: #fff1dd; color: #975d00; border-color: #f4dbb0; }
    .badge-blocked { background: #fde6e8; color: #a53b47; border-color: #f6c5ca; }

    .explain-hero {
        background: linear-gradient(135deg, #ffffff 0%, #f5f9ff 100%);
        border: 1px solid #d6e5f6;
        border-left: 6px solid #2b73d5;
        border-radius: 18px;
        padding: 16px 18px;
        box-shadow: 0 10px 22px rgba(22, 59, 104, 0.08);
        margin-bottom: 12px;
    }

    .mini-note {
        color: #59718f;
        font-size: 0.88rem;
        font-weight: 600;
        margin-top: 8px;
    }

    .book-quote-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 10px;
        margin-top: 10px;
        margin-bottom: 14px;
    }

    .book-quote-card {
        background: #ffffff;
        border: 1px solid #dbe7f5;
        border-radius: 14px;
        padding: 12px;
        box-shadow: 0 6px 16px rgba(22, 59, 104, 0.06);
    }

    .book-quote-card.book-best {
        border: 2px solid #2b73d5;
        background: #f2f8ff;
    }

    .book-quote-top {
        color: #173b67;
        font-size: 0.85rem;
        font-weight: 800;
    }

    .book-quote-odds {
        color: #0f345a;
        font-size: 1.1rem;
        font-weight: 900;
        margin-top: 6px;
    }

    .book-quote-sub {
        color: #5d7695;
        font-size: 0.78rem;
        font-weight: 700;
        margin-top: 6px;
    }

    .explain-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 10px;
        margin: 10px 0 12px 0;
    }

    .explain-stat {
        background: #ffffff;
        border: 1px solid #dbe7f5;
        border-radius: 14px;
        padding: 12px;
    }

    .explain-stat-label {
        color: #647d9a;
        font-size: 0.78rem;
        font-weight: 800;
        text-transform: uppercase;
    }

    .explain-stat-value {
        color: #14365c;
        font-size: 1.08rem;
        font-weight: 900;
        margin-top: 6px;
    }

    .hero-row-card {
        background: linear-gradient(145deg, #ffffff 0%, #eef5ff 100%);
        border: 1px solid #cfe0f7;
        border-radius: 22px;
        padding: 18px;
        min-height: 220px;
        box-shadow: 0 10px 22px rgba(16, 56, 102, 0.08);
        margin-bottom: 16px;
    }

    .hero-kicker {
        color: #355f91;
        font-size: 0.78rem;
        font-weight: 900;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 10px;
    }

    .hero-main {
        color: #102743;
        font-size: 1.28rem;
        font-weight: 900;
        line-height: 1.25;
    }

    .hero-meta {
        color: #486480;
        font-size: 0.94rem;
        margin-top: 8px;
    }

    .news-card {
        background: linear-gradient(135deg, #ffffff 0%, #f5f9ff 100%);
        border: 1px solid #d6e5f6;
        border-radius: 18px;
        padding: 16px 18px;
        box-shadow: 0 10px 20px rgba(22, 59, 104, 0.06);
        margin-bottom: 12px;
    }

    .news-feed-tag {
        display: inline-block;
        background: #e8f1ff;
        color: #1b4f89;
        border: 1px solid #c9dcfb;
        border-radius: 999px;
        font-size: 0.74rem;
        font-weight: 800;
        padding: 4px 9px;
        margin-bottom: 8px;
    }

    .news-title a {
        color: #133b67;
        font-size: 1.02rem;
        font-weight: 900;
        text-decoration: none;
    }

    .news-title a:hover {
        text-decoration: underline;
    }

    .news-meta {
        color: #607a99;
        font-size: 0.82rem;
        font-weight: 700;
        margin-top: 6px;
    }

    .news-desc {
        color: #334f70;
        font-size: 0.9rem;
        margin-top: 8px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

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

max_total_exposure = st.sidebar.number_input("Max Total Exposure", min_value=1.0, value=30.0, step=1.0)
max_sport_exposure = st.sidebar.number_input("Max Exposure per Sport", min_value=1.0, value=12.0, step=1.0)
max_event_exposure = st.sidebar.number_input("Max Exposure per Event", min_value=1.0, value=8.0, step=1.0)
max_book_exposure = st.sidebar.number_input("Max Exposure per Sportsbook", min_value=1.0, value=12.0, step=1.0)
max_prop_exposure = st.sidebar.number_input("Max Exposure on Props", min_value=1.0, value=8.0, step=1.0)
correlation_guard = st.sidebar.toggle("Correlation Protection", value=True)
watchlist_query = st.sidebar.text_input("Watchlist filter", placeholder="Knicks, LeBron, totals, Braves...")
watchlist_only = st.sidebar.toggle("Show watchlist matches only", value=False)
only_final_bets = st.sidebar.toggle("Show final bets only", value=False)

if st.sidebar.button("Refresh now"):
    st.cache_data.clear()
    st.rerun()

st.markdown('<div class="main-title">🏈 Sports Betting Dashboard</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">Stable core version with live odds, line movement, book comparison, and bankroll controls.</div>',
    unsafe_allow_html=True,
)

render_quick_links()


@st.fragment(run_every="15m")
def render_live_dashboard():
    events, error_message = fetch_events(league_filter)

    if error_message:
        st.warning(error_message)
        st.info("Add SPORTS_GAME_ODDS_API_KEY in Streamlit Secrets and click Refresh now.")
        return

    raw_df = flatten_events_to_rows(events)
    if raw_df.empty:
        st.warning("No live odds came back for the leagues selected.")
        return

    scored_df = apply_smart_scoring(raw_df, min_bet=min_bet, max_bet=max_bet)
    moved_df = apply_line_movement(scored_df)
    filtered_df = moved_df[moved_df["Sportsbook"].isin(book_filter)].copy()
    filtered_df = apply_risk_controls(
        filtered_df,
        min_bet=min_bet,
        max_total_exposure=max_total_exposure,
        max_sport_exposure=max_sport_exposure,
        max_event_exposure=max_event_exposure,
        max_book_exposure=max_book_exposure,
        max_prop_exposure=max_prop_exposure,
        use_correlation_guard=correlation_guard,
    )

    filtered_df["Watchlist Match"] = filtered_df.apply(lambda row: watchlist_match(row, watchlist_query), axis=1)
    filtered_df["Watchlist Label"] = filtered_df["Watchlist Match"].map({True: "⭐ Watchlist", False: ""})

    if watchlist_only and str(watchlist_query).strip():
        filtered_df = filtered_df[filtered_df["Watchlist Match"]].copy()

    if only_final_bets:
        filtered_df = filtered_df[filtered_df["Final Status"] == "Bet"].copy()

    status_order = {"Bet": 2, "Pass": 1, "No Bet": 0}
    filtered_df["Status Rank"] = filtered_df["Final Status"].map(status_order).fillna(0)
    filtered_df = filtered_df.sort_values(
        ["Status Rank", "AI Score", "Edge %", "Books Quoting", "Market Rank"],
        ascending=[False, False, False, False, True],
    )

    live_bets = filtered_df[filtered_df["Final Status"] == "Bet"].copy()
    best_row = live_bets.iloc[0] if not live_bets.empty else None
    best_edge = float(live_bets["Edge %"].max()) if not live_bets.empty else 0.0
    avg_edge = float(live_bets["Edge %"].mean()) if not live_bets.empty else 0.0
    avg_score = float(live_bets["AI Score"].mean()) if not live_bets.empty else 0.0
    open_risk = int(live_bets["Final Bet"].sum()) if not live_bets.empty else 0
    active_bets = int(len(live_bets))
    refresh_time = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
    strong_alerts = strong_shop_alerts(live_bets)
    avg_books = float(live_bets["Books Quoting"].mean()) if not live_bets.empty else 0.0
    improving_count = int((live_bets["Move Label"] == "Improving").sum()) if not live_bets.empty else 0
    watchlist_hits = int(filtered_df["Watchlist Match"].sum()) if "Watchlist Match" in filtered_df.columns else 0

    exposure_by_sport = live_bets.groupby("Sport")["Final Bet"].sum().sort_values(ascending=False) if not live_bets.empty else pd.Series(dtype=float)
    exposure_by_book = live_bets.groupby("Sportsbook")["Final Bet"].sum().sort_values(ascending=False) if not live_bets.empty else pd.Series(dtype=float)

    st.markdown('<div class="hero-box">', unsafe_allow_html=True)
    hero_left, hero_right = st.columns([2, 1])

    with hero_left:
        st.markdown("### Current Top Bet")
        if best_row is not None:
            pills = build_badges_html(best_row)
            st.markdown(
                f"""
                **{best_row['Pick']}**  
                {best_row['Event']} · {best_row['Market']}  
                Book: **{best_row['Sportsbook']}** · Odds: **{best_row['Odds']}** · Previous: **{best_row['Prev Odds']}**  
                Edge: **{best_row['Edge %']:.2f}%** · Score: **{best_row['AI Score']:.2f}** · Final Bet: **${int(best_row['Final Bet'])}**  
                Line Move: **{best_row['Line Move %']:+.2f}%** · Time To Start: **{format_minutes(best_row['Minutes To Start'])}**  
                Reason: *{best_row['Pass Reason'] or best_row['Reason']}*  
                {pills}
                """,
                unsafe_allow_html=True,
            )
            if best_row["Link"]:
                st.markdown(f"[Open bet page]({best_row['Link']})")
        else:
            st.info("No bets qualify right now under the current rules.")

    with hero_right:
        st.markdown('<div class="small-label">Current Bankroll</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="big-value">${bankroll:,.2f}</div>', unsafe_allow_html=True)
        st.markdown('<div class="small-label">Bet Range</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="big-value">${min_bet:.0f} - ${max_bet:.0f}</div>', unsafe_allow_html=True)
        st.markdown('<div class="small-label">Refresh</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="big-value" style="font-size:1.0rem;">{refresh_time}</div>', unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)

    def kpi_card(label, value):
        st.markdown(
            f'<div class="kpi-card"><div class="kpi-label">{label}</div><div class="kpi-value">{value}</div></div>',
            unsafe_allow_html=True,
        )

    k1, k2, k3, k4, k5, k6, k7, k8 = st.columns(8)
    with k1:
        kpi_card("Final Bets", active_bets)
    with k2:
        kpi_card("Best Edge", f"{best_edge:.2f}%")
    with k3:
        kpi_card("Average Edge", f"{avg_edge:.2f}%")
    with k4:
        kpi_card("Average Score", f"{avg_score:.2f}")
    with k5:
        kpi_card("Open Risk", f"${open_risk}")
    with k6:
        kpi_card("Strong Shop", strong_alerts)
    with k7:
        kpi_card("Improving Lines", improving_count)
    with k8:
        kpi_card("Watchlist Hits", watchlist_hits)

    tabs = st.tabs([
        "Home",
        "Sports News",
        "Best Bets",
        "DraftKings",
        "FanDuel",
        "Bet365",
        "PrizePicks",
        "Bankroll",
    ])

    with tabs[0]:
        st.markdown('<div class="section-title">Premium Top 3 Bets</div>', unsafe_allow_html=True)
        top_df = live_bets.head(3)
        hero_cols = st.columns(3)
        labels = ["Bet of the Day", "Best Value", "Safest Play"]
        if top_df.empty:
            st.warning("No final bets available right now.")
        else:
            for i, col in enumerate(hero_cols):
                with col:
                    if i < len(top_df):
                        row = top_df.iloc[i]
                        link_html = f'<br><a href="{row["Link"]}" target="_blank">Open bet page</a>' if row["Link"] else ""
                        st.markdown(
                            f"""
                            <div class="hero-row-card">
                                <div class="hero-kicker">{labels[i]}</div>
                                <div class="hero-main">{row['Pick']}</div>
                                <div class="hero-meta">{row['Event']} · {row['Market']}</div>
                                <div class="hero-meta">{row['Sportsbook']} {row['Odds']} · Final Bet ${int(row['Final Bet'])}</div>
                                <div class="hero-meta">Score {row['AI Score']:.2f} · Edge {row['Edge %']:.2f}%</div>
                                {build_badges_html(row)}
                                <div class="hero-meta">{row['Pass Reason'] or row['Reason']}</div>
                                {link_html}
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

        top_left, top_right = st.columns([1.25, 1])

        with top_left:
            st.markdown('<div class="section-title">Decision Center · Bet of the Day</div>', unsafe_allow_html=True)
            if top_df.empty:
                st.warning("No final bets available right now.")
            else:
                first = top_df.iloc[0]
                st.markdown(
                    f"""
                    <div class="decision-card">
                        <div class="decision-title">Featured Bet</div>
                        <div class="decision-big">{first['Pick']}</div>
                        <div class="decision-sub">{first['Event']} · {first['Market']} · {first['Sportsbook']} {first['Odds']}</div>
                        <div class="decision-sub">Score {first['AI Score']:.2f} · Edge {first['Edge %']:.2f}% · Final Bet ${int(first['Final Bet'])}</div>
                        <div class="decision-sub">{first['Pass Reason'] or first['Reason']}</div>
                        {build_badges_html(first)}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.markdown('<div class="section-title">Top Final Bets</div>', unsafe_allow_html=True)
                for _, row in top_df.iterrows():
                    link_html = f'<br><a href="{row["Link"]}" target="_blank">Open bet page</a>' if row["Link"] else ""
                    st.markdown(
                        f"""
                        <div class="best-bet">
                            <b>{row['Pick']}</b><br>
                            {row['Event']} · {row['Market']}<br>
                            Book: <b>{row['Sportsbook']}</b> · Odds: <b>{row['Odds']}</b> · Prev: <b>{row['Prev Odds']}</b><br>
                            Edge: <b>{row['Edge %']:.2f}%</b> · Score: <b>{row['AI Score']:.2f}</b> · Confidence: <b>{row['Confidence']}</b><br>
                            Final Bet: <b>${int(row['Final Bet'])}</b> · Move: <b>{row['Line Move %']:+.2f}% ({row['Move Label']})</b><br>
                            Decision: <b>{row['Allocation Status']}</b> {row['Watchlist Label']}<br>
                            {build_badges_html(row)}<br>
                            Reason: <i>{row['Pass Reason'] or row['Reason']}</i>
                            {link_html}
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

        with top_right:
            st.markdown('<div class="section-title">Board Snapshot</div>', unsafe_allow_html=True)
            st.markdown(
                f"""
                <div class="decision-card">
                    <div class="decision-title">Risk Gauge</div>
                    <div class="decision-sub">Open suggested exposure is <b>${open_risk}</b> against a max total cap of <b>${max_total_exposure:.0f}</b>.</div>
                    <div class="decision-sub">Average score on final bets is <b>{avg_score:.2f}</b> across <b>{active_bets}</b> bets.</div>
                    <div class="decision-sub">Average books quoting is <b>{avg_books:.2f}</b>. Improving lines on board: <b>{improving_count}</b>.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        c1, c2 = st.columns(2)
        with c1:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown("**Score by Sportsbook**")
            if live_bets.empty:
                st.info("No chart data available.")
            else:
                chart_df = live_bets.groupby("Sportsbook")["AI Score"].mean().sort_values(ascending=False)
                st.bar_chart(chart_df)
            st.markdown('</div>', unsafe_allow_html=True)

        with c2:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown("**Open Exposure by Sport**")
            if exposure_by_sport.empty:
                st.info("No chart data available.")
            else:
                st.bar_chart(exposure_by_sport)
            st.markdown('</div>', unsafe_allow_html=True)

        c3, c4 = st.columns(2)
        with c3:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown("**Line Movement Mix**")
            if live_bets.empty:
                st.info("No chart data available.")
            else:
                chart_df = live_bets["Move Label"].value_counts().reindex(["Improving", "Flat", "Worse", "New"]).fillna(0)
                st.bar_chart(chart_df)
            st.markdown('</div>', unsafe_allow_html=True)

        with c4:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown("**Score vs Edge Snapshot**")
            if live_bets.empty:
                st.info("No chart data available.")
            else:
                chart_df = live_bets[["Pick", "AI Score", "Edge %"]].head(8).set_index("Pick")
                st.line_chart(chart_df)
            st.markdown('</div>', unsafe_allow_html=True)

        c5, c6 = st.columns(2)
        with c5:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown("**Exposure by Sportsbook**")
            if exposure_by_book.empty:
                st.info("No chart data available.")
            else:
                st.bar_chart(exposure_by_book)
            st.markdown('</div>', unsafe_allow_html=True)

        with c6:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown("**Best Price Alerts**")
            if live_bets.empty:
                st.info("No chart data available.")
            else:
                chart_df = pd.Series({
                    "Strong Shop Alerts": strong_alerts,
                    "Improving Lines": improving_count,
                    "Watchlist Hits": watchlist_hits,
                })
                st.bar_chart(chart_df)
            st.markdown('</div>', unsafe_allow_html=True)

    with tabs[1]:
        st.markdown('<div class="section-title">Sports News</div>', unsafe_allow_html=True)
        news_col1, news_col2 = st.columns([1.5, 1])

        with news_col1:
            news_feed_choice = st.selectbox(
                "Choose a headline feed",
                options=get_news_feed_names(league_filter),
                key="sports_news_feed_select",
            )
            selected_news = fetch_news_feed(news_feed_choice, limit=12)
            if not selected_news:
                st.info("No headlines available right now.")
            else:
                for item in selected_news:
                    desc = item.get("description", "") or "Fresh headline feed from ESPN."
                    st.markdown(
                        f"""
                        <div class="news-card">
                            <div class="news-feed-tag">Provided by ESPN RSS · {escape(item.get('feed', 'News'))}</div>
                            <div class="news-title"><a href="{item.get('link', '#')}" target="_blank">{escape(item.get('title', 'Headline'))}</a></div>
                            <div class="news-meta">{escape(item.get('pub_date', ''))}</div>
                            <div class="news-desc">{escape(desc)}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

        with news_col2:
            st.markdown('<div class="section-title">Headline Snapshot</div>', unsafe_allow_html=True)
            st.markdown(
                """
                <div class="card">
                • Headlines are pulled from ESPN's official RSS feeds.<br>
                • This tab links straight to the source article.<br>
                • The feed list follows your selected leagues plus Top Headlines.
                </div>
                """,
                unsafe_allow_html=True,
            )

            if selected_news:
                feed_counts = pd.Series([item.get("feed", "News") for item in selected_news]).value_counts()
                st.markdown('<div class="section-title">Loaded Headlines by Feed</div>', unsafe_allow_html=True)
                st.bar_chart(feed_counts)
            else:
                st.info("No news chart data available.")

    with tabs[2]:
        st.markdown('<div class="section-title">Best Bets Board</div>', unsafe_allow_html=True)

        display_df = filtered_df.copy()
        display_df["Link"] = display_df["Link"].apply(make_link_markdown)
        display_df["Minutes To Start"] = display_df["Minutes To Start"].apply(format_minutes)
        display_df["Confidence Tag"] = display_df["Confidence"].apply(confidence_badge_text)
        display_df["Move Tag"] = display_df["Move Label"].apply(move_badge_text)
        display_df["Decision Tag"] = display_df["Allocation Status"].apply(decision_badge_text)
        display_df = display_df[
            [
                "Sport",
                "Event",
                "Market Bucket",
                "Market",
                "Pick",
                "Sportsbook",
                "Prev Odds",
                "Odds",
                "Watchlist Label",
                "Confidence Tag",
                "Move Tag",
                "Decision Tag",
                "Move Label",
                "Line Move %",
                "Implied Prob",
                "Model Prob",
                "Edge %",
                "Best Line Gap %",
                "Books Quoting",
                "Bet Score",
                "AI Score",
                "Confidence",
                "Recommended Bet",
                "Final Bet",
                "Allocation Status",
                "Minutes To Start",
                "Final Status",
                "Pass Reason",
                "Link",
            ]
        ]

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Implied Prob": st.column_config.NumberColumn(format="%.2f%%"),
                "Model Prob": st.column_config.NumberColumn(format="%.2f%%"),
                "Line Move %": st.column_config.NumberColumn(format="%.2f"),
                "Edge %": st.column_config.ProgressColumn(
                    "Edge %", min_value=0.0, max_value=max(float(max(display_df["Edge %"].max(), 1.0)), 1.0), format="%.2f%%"
                ),
                "Best Line Gap %": st.column_config.NumberColumn(format="%.2f%%"),
                "Bet Score": st.column_config.ProgressColumn(
                    "Bet Score", min_value=0.0, max_value=max(float(max(display_df["Bet Score"].max(), 1.0)), 1.0), format="%.2f"
                ),
                "Recommended Bet": st.column_config.NumberColumn(format="$%d"),
                "Final Bet": st.column_config.NumberColumn(format="$%d"),
                "Link": st.column_config.LinkColumn("Open"),
            },
        )

        st.markdown('<div class="section-title">Explain This Bet</div>', unsafe_allow_html=True)
        explain_candidates = filtered_df[filtered_df["Final Status"] == "Bet"].copy()
        if explain_candidates.empty:
            st.info("No final bets available to explain right now.")
        else:
            explain_candidates["Explain Label"] = explain_candidates.apply(
                lambda row: f"{row['Event']} | {row['Pick']} | {row['Sportsbook']} {row['Odds']} | ${int(row['Final Bet'])}",
                axis=1,
            )
            selected_label = st.selectbox(
                "Choose a final bet to explain",
                options=explain_candidates["Explain Label"].tolist(),
                key="explain_bet_select",
            )
            explained_row = explain_candidates.loc[explain_candidates["Explain Label"] == selected_label].iloc[0]
            same_pick_rows = get_same_pick_market_rows(filtered_df, explained_row)
            best_book = same_pick_rows.iloc[0]["Sportsbook"] if not same_pick_rows.empty else explained_row["Sportsbook"]
            line_gap = float(same_pick_rows["Implied Prob"].max() - same_pick_rows["Implied Prob"].min()) if len(same_pick_rows) > 1 else 0.0
            st.markdown(
                f"""
                <div class="explain-hero">
                    <b>{explained_row['Pick']}</b><br>
                    {explained_row['Event']} · {explained_row['Market']}<br>
                    {build_badges_html(explained_row)}
                    <div class="explain-grid">
                        <div class="explain-stat">
                            <div class="explain-stat-label">Best Book</div>
                            <div class="explain-stat-value">{best_book}</div>
                        </div>
                        <div class="explain-stat">
                            <div class="explain-stat-label">Edge</div>
                            <div class="explain-stat-value">{explained_row['Edge %']:.2f}%</div>
                        </div>
                        <div class="explain-stat">
                            <div class="explain-stat-label">Final Bet</div>
                            <div class="explain-stat-value">${int(explained_row['Final Bet'])}</div>
                        </div>
                        <div class="explain-stat">
                            <div class="explain-stat-label">Line Gap</div>
                            <div class="explain-stat-value">{line_gap:.2f}%</div>
                        </div>
                        <div class="explain-stat">
                            <div class="explain-stat-label">Score</div>
                            <div class="explain-stat-value">{explained_row['AI Score']:.2f}</div>
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown(build_book_snapshot_html(explained_row, filtered_df), unsafe_allow_html=True)
            st.markdown(build_explain_bet_markdown(explained_row, filtered_df), unsafe_allow_html=False)

    def sportsbook_section(book_name):
        book_df = filtered_df[filtered_df["Sportsbook"] == book_name].copy()
        bet_df = book_df[book_df["Final Status"] == "Bet"].copy()
        avg_edge_book = float(bet_df["Edge %"].mean()) if not bet_df.empty else 0.0
        avg_score_book = float(bet_df["Bet Score"].mean()) if not bet_df.empty else 0.0
        max_stake_book = int(bet_df["Final Bet"].max()) if not bet_df.empty else 0
        improving_book = int((bet_df["Move Label"] == "Improving").sum()) if not bet_df.empty else 0

        st.markdown(f'<div class="section-title">{book_name} Opportunities</div>', unsafe_allow_html=True)
        c1, c2 = st.columns([1.2, 1])

        with c1:
            st.markdown(
                f"""
                <div class="card">
                <b>{book_name}</b><br>
                This tab shows live lines from the selected leagues with line movement and risk controls applied.<br>
                It is focused on price edge, timing, and exposure rules.
                </div>
                """,
                unsafe_allow_html=True,
            )

        with c2:
            st.markdown(
                f"""
                <div class="card">
                Final Bets: <b>{len(bet_df)}</b><br>
                Avg Edge: <b>{avg_edge_book:.2f}%</b><br>
                Avg Score: <b>{avg_score_book:.2f}</b><br>
                Max Final Bet: <b>${max_stake_book}</b><br>
                Improving Lines: <b>{improving_book}</b>
                </div>
                """,
                unsafe_allow_html=True,
            )

        if book_df.empty:
            st.warning(f"No rows currently available for {book_name}.")
            return

        book_df["Link"] = book_df["Link"].apply(make_link_markdown)
        book_df["Minutes To Start"] = book_df["Minutes To Start"].apply(format_minutes)
        book_df["Confidence Tag"] = book_df["Confidence"].apply(confidence_badge_text)
        book_df["Move Tag"] = book_df["Move Label"].apply(move_badge_text)
        book_df["Decision Tag"] = book_df["Allocation Status"].apply(decision_badge_text)
        book_df = book_df[
            [
                "Sport",
                "Event",
                "Market Bucket",
                "Market",
                "Pick",
                "Prev Odds",
                "Odds",
                "Watchlist Label",
                "Confidence Tag",
                "Move Tag",
                "Decision Tag",
                "Move Label",
                "Line Move %",
                "Edge %",
                "Bet Score",
                "AI Score",
                "Confidence",
                "Recommended Bet",
                "Final Bet",
                "Allocation Status",
                "Final Status",
                "Minutes To Start",
                "Pass Reason",
                "Link",
            ]
        ]

        st.dataframe(
            book_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Line Move %": st.column_config.NumberColumn(format="%.2f"),
                "Edge %": st.column_config.ProgressColumn(
                    "Edge %", min_value=0.0, max_value=max(float(max(book_df["Edge %"].max(), 1.0)), 1.0), format="%.2f%%"
                ),
                "Bet Score": st.column_config.ProgressColumn(
                    "Bet Score", min_value=0.0, max_value=max(float(max(book_df["Bet Score"].max(), 1.0)), 1.0), format="%.2f"
                ),
                "Recommended Bet": st.column_config.NumberColumn(format="$%d"),
                "Final Bet": st.column_config.NumberColumn(format="$%d"),
                "Link": st.column_config.LinkColumn("Open"),
            },
        )

    with tabs[3]:
        sportsbook_section("DraftKings")

    with tabs[4]:
        sportsbook_section("FanDuel")

    with tabs[5]:
        sportsbook_section("Bet365")

    with tabs[6]:
        sportsbook_section("PrizePicks")

    with tabs[7]:
        st.markdown('<div class="section-title">Bankroll + Exposure Rules</div>', unsafe_allow_html=True)
        b1, b2, b3, b4 = st.columns(4)
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
                <div class="small-label">Open Suggested Risk</div>
                <div class="big-value">${open_risk:.0f}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with b3:
            st.markdown(
                f"""
                <div class="card">
                <div class="small-label">Max Total Exposure</div>
                <div class="big-value">${max_total_exposure:.0f}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with b4:
            st.markdown(
                f"""
                <div class="card">
                <div class="small-label">Correlation Guard</div>
                <div class="big-value">{'On' if correlation_guard else 'Off'}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        x1, x2 = st.columns(2)
        with x1:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown("**Exposure Caps**")
            caps_df = pd.DataFrame(
                {
                    "Rule": [
                        "Per Sport",
                        "Per Event",
                        "Per Sportsbook",
                        "Props Only",
                    ],
                    "Cap": [
                        f"${max_sport_exposure:.0f}",
                        f"${max_event_exposure:.0f}",
                        f"${max_book_exposure:.0f}",
                        f"${max_prop_exposure:.0f}",
                    ],
                }
            )
            st.dataframe(caps_df, use_container_width=True, hide_index=True)
            st.markdown('</div>', unsafe_allow_html=True)

        with x2:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown("**Current Open Exposure by Sport**")
            if exposure_by_sport.empty:
                st.info("No live exposure right now.")
            else:
                st.bar_chart(exposure_by_sport)
            st.markdown('</div>', unsafe_allow_html=True)


render_live_dashboard()
