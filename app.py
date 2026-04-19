from datetime import datetime, timezone
from html import escape
from io import StringIO
import re
import time
import xml.etree.ElementTree as ET

import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="Vegas Odds Dashboard",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)

DEFAULT_LEAGUES = ["NBA", "NFL", "MLB", "NHL"]
VEGAS_URLS = {
    "NBA": "https://www.vegasinsider.com/nba/odds/las-vegas/",
    "NFL": "https://www.vegasinsider.com/nfl/odds/las-vegas/",
    "MLB": "https://www.vegasinsider.com/mlb/odds/las-vegas/",
    "NHL": "https://www.vegasinsider.com/nhl/odds/las-vegas/",
}
BOOK_COLUMNS = {
    "Bet365": "Bet365",
    "BetMGM": "BetMGM",
    "DraftKings": "DraftKings",
    "Caesars": "Caesars",
    "FanDuel": "FanDuel",
    "HardRock": "HardRock",
    "Fanatics": "Fanatics",
    "RiversCasino": "RiversCasino",
    "Consensus": "Consensus",
    "Open": "Open",
}
DISPLAY_BOOKS = [
    "Bet365",
    "BetMGM",
    "DraftKings",
    "Caesars",
    "FanDuel",
    "HardRock",
    "Fanatics",
    "RiversCasino",
    "Consensus",
]
BOOK_URLS = {
    "Bet365": "https://www.bet365.com/",
    "BetMGM": "https://sports.betmgm.com/",
    "DraftKings": "https://sportsbook.draftkings.com/",
    "Caesars": "https://www.caesars.com/sportsbook-and-casino",
    "FanDuel": "https://sportsbook.fanduel.com/",
    "HardRock": "https://www.hardrock.bet/",
    "Fanatics": "https://sportsbook.fanatics.com/",
    "RiversCasino": "https://www.betrivers.com/",
    "Consensus": "https://www.vegasinsider.com/",
}
NEWS_FEEDS = {
    "Top Headlines": "https://www.espn.com/espn/rss/news",
    "NFL": "https://www.espn.com/espn/rss/nfl/news",
    "NBA": "https://www.espn.com/espn/rss/nba/news",
    "MLB": "https://www.espn.com/espn/rss/mlb/news",
    "NHL": "https://www.espn.com/espn/rss/nhl/news",
}
LEAGUE_TO_NEWS = {
    "NFL": "NFL",
    "NBA": "NBA",
    "MLB": "MLB",
    "NHL": "NHL",
}
MAIN_MARKETS = {"Spread"}

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
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
        resp = requests.get(url, timeout=20, headers=REQUEST_HEADERS)
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


def market_sort_value(bucket):
    order = {"Spread": 1}
    return order.get(bucket, 9)


def strong_shop_alerts(df):
    if df.empty:
        return 0
    return int((df["Best Line Gap %"] >= 3.0).sum())


def make_link_markdown(url):
    if not url:
        return ""
    return f"[Open]({url})"


def confidence_from_score(score):
    if score >= 7.0:
        return "Elite"
    if score >= 5.0:
        return "High"
    if score >= 3.0:
        return "Medium"
    return "Low"


def market_weight(bucket):
    return {"Spread": 1.20}.get(bucket, 0.40)


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
    st.markdown('<div class="section-title">Quick Book Links</div>', unsafe_allow_html=True)
    cols = st.columns(5)
    books = [
        ("DraftKings", "🟩"),
        ("FanDuel", "🟦"),
        ("BetMGM", "🟨"),
        ("Caesars", "🟥"),
        ("Bet365", "🟢"),
    ]
    for col, (book, icon) in zip(cols, books):
        with col:
            st.markdown(
                f"""
                <div class="book-link-card">
                    <div class="book-link-title">{icon} {book}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            try:
                st.link_button(f"Open {book}", BOOK_URLS[book], use_container_width=True)
            except Exception:
                st.markdown(f"[Open {book}]({BOOK_URLS[book]})")


def has_odds_token(text):
    if not text:
        return False
    return bool(re.search(r"[+-]\d+(\.\d+)?", str(text)))


def extract_price(text):
    if not text:
        return None
    matches = re.findall(r"([+-]\d{3,4})", str(text).replace("−", "-"))
    if not matches:
        return None
    return matches[-1]


def extract_line_value(text):
    if not text:
        return None
    s = str(text).replace("−", "-")
    matches = re.findall(r"([+-]?\d+(?:\.\d+)?)", s)
    if not matches:
        return None

    # Try to avoid returning the price as the line
    line_candidates = []
    for m in matches:
        try:
            val = float(m)
            if abs(val) < 200:
                line_candidates.append(m)
        except Exception:
            pass

    if not line_candidates:
        return None

    return line_candidates[0]


def clean_team_name(text):
    s = str(text)
    s = re.sub(r"Image:", " ", s, flags=re.I)
    s = re.sub(r"Image", " ", s, flags=re.I)
    s = re.sub(r"\b\d{2,4}\b", " ", s)
    s = re.sub(r"[›•†]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()

    tokens = s.split()
    if not tokens:
        return ""

    # take the last 1-3 alphabetic-ish tokens as team name
    filtered = [t for t in tokens if re.search(r"[A-Za-z]", t)]
    if not filtered:
        return s

    if len(filtered) >= 3:
        return " ".join(filtered[-3:])
    if len(filtered) >= 2:
        return " ".join(filtered[-2:])
    return filtered[-1]


def flatten_columns(df):
    cols = []
    for col in df.columns:
        if isinstance(col, tuple):
            part = " ".join(str(x) for x in col if str(x) != "nan").strip()
            cols.append(part)
        else:
            cols.append(str(col))
    df.columns = cols
    return df


def normalize_header_name(name):
    n = str(name).strip()
    n = n.replace("Rivers Casino", "RiversCasino")
    n = re.sub(r"\s+", "", n)
    return n


def extract_time_from_table(df):
    joined_cols = " ".join(str(c) for c in df.columns)
    m = re.search(r"(\d{1,2}:\d{2}\s*[AP]M(?:\s*ET)?)", joined_cols, flags=re.I)
    if m:
        return m.group(1).upper().replace("  ", " ")
    return ""


def row_has_market_data(row, book_cols):
    for col in book_cols:
        if col in row and has_odds_token(row.get(col)):
            return True
    return False


def parse_vi_tables_to_rows(league, tables):
    rows = []

    for table_idx, df in enumerate(tables):
        try:
            df = flatten_columns(df.copy())
        except Exception:
            continue

        original_cols = list(df.columns)
        renamed = {}
        for col in original_cols:
            compact = normalize_header_name(col)
            if compact in BOOK_COLUMNS:
                renamed[col] = BOOK_COLUMNS[compact]
        df = df.rename(columns=renamed)

        usable_book_cols = [c for c in DISPLAY_BOOKS if c in df.columns]
        if "Consensus" not in df.columns or len(usable_book_cols) < 2:
            continue

        if df.empty:
            continue

        first_col = df.columns[0]
        game_time = extract_time_from_table(df)

        candidate_rows = []
        for _, row in df.iterrows():
            row_dict = row.to_dict()
            row_dict["_raw_first"] = str(row.get(first_col, ""))
            if row_has_market_data(row_dict, usable_book_cols):
                candidate_rows.append(row_dict)

        # team rows usually appear in pairs
        if len(candidate_rows) < 2:
            continue

        filtered_rows = []
        for r in candidate_rows:
            team = clean_team_name(r.get("_raw_first", ""))
            if team and team.lower() not in {"matchup", "view picks", "open", "consensus"}:
                r["_team"] = team
                filtered_rows.append(r)

        if len(filtered_rows) < 2:
            continue

        pair_index = 0
        for i in range(0, len(filtered_rows) - 1, 2):
            away = filtered_rows[i]
            home = filtered_rows[i + 1]

            away_team = away.get("_team", "").strip()
            home_team = home.get("_team", "").strip()
            if not away_team or not home_team or away_team == home_team:
                continue

            event_id = f"{league}|{table_idx}|{pair_index}|{away_team}|{home_team}"
            pair_index += 1

            for book in usable_book_cols:
                away_cell = str(away.get(book, "")).strip()
                home_cell = str(home.get(book, "")).strip()
                if not away_cell or not home_cell:
                    continue
                if not has_odds_token(away_cell) or not has_odds_token(home_cell):
                    continue

                for side, cell, team_name in [
                    ("away", away_cell, away_team),
                    ("home", home_cell, home_team),
                ]:
                    price = extract_price(cell)
                    implied_prob = american_to_implied(price)
                    if implied_prob is None:
                        continue

                    line_val = extract_line_value(cell)
                    line_text = line_val if line_val is not None else ""

                    row_key = f"{event_id}|{book}|{side}"

                    rows.append(
                        {
                            "Row Key": row_key,
                            "Event ID": event_id,
                            "Odd ID": f"{league}|spread|{pair_index}",
                            "Sport": league,
                            "Event": f"{away_team} @ {home_team}",
                            "Home Team": home_team,
                            "Away Team": away_team,
                            "Start Time": "",
                            "Display Time": game_time,
                            "Minutes To Start": None,
                            "Market": "Spread",
                            "Market Bucket": "Spread",
                            "Pick": team_name,
                            "Sportsbook": book,
                            "Sportsbook ID": book.lower(),
                            "Odds": str(price),
                            "Implied Prob": implied_prob,
                            "Line": str(line_text),
                            "Last Update": "",
                            "Link": BOOK_URLS.get(book, "https://www.vegasinsider.com/"),
                            "Source Detail": cell,
                        }
                    )

    return pd.DataFrame(rows)


@st.cache_data(ttl=900, show_spinner="Loading Vegas lines...")
def fetch_vegas_rows(leagues):
    all_rows = []
    messages = []

    for league in leagues:
        url = VEGAS_URLS.get(league)
        if not url:
            continue

        try:
            resp = requests.get(url, headers=REQUEST_HEADERS, timeout=25)
            resp.raise_for_status()
            html = resp.text

            tables = pd.read_html(StringIO(html))
            league_df = parse_vi_tables_to_rows(league, tables)

            if league_df.empty:
                messages.append(f"{league}: no active Vegas board found")
            else:
                all_rows.append(league_df)

            time.sleep(0.6)

        except Exception as exc:
            messages.append(f"{league}: {exc}")

    if all_rows:
        df = pd.concat(all_rows, ignore_index=True)
        if messages:
            return df, "Partial load: " + " | ".join(messages)
        return df, ""

    return pd.DataFrame(), "No Vegas lines could be parsed from the selected league pages."


def build_reason(row):
    parts = []

    if row["Is Best Price"]:
        parts.append(f"best current price across {int(row['Books Quoting'])} books")
    else:
        parts.append(f"positive price edge vs {int(row['Books Quoting'])} book consensus")

    parts.append("spread market carries stronger confidence")

    if row["Sportsbook"] == "Consensus":
        parts.append("consensus line is useful as a market anchor")

    return " • ".join(parts)


def apply_smart_scoring(df, min_bet, max_bet):
    if df.empty:
        return df

    market_stats = (
        df.groupby(["Event ID", "Pick"])["Implied Prob"]
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

    scored = df.merge(market_stats, on=["Event ID", "Pick"], how="left")
    scored["Prob StdDev"] = scored["Prob StdDev"].fillna(0.0)
    scored["Model Prob"] = scored["Consensus Prob"].round(2)
    scored["Edge %"] = (scored["Consensus Prob"] - scored["Implied Prob"]).round(2)
    scored["Best Line Gap %"] = (scored["Worst Price Prob"] - scored["Implied Prob"]).round(2)
    scored["Is Best Price"] = scored["Implied Prob"] <= (scored["Best Price Prob"] + 0.0001)

    scored["Market Weight"] = scored["Market Bucket"].apply(market_weight)
    scored["Time Penalty"] = scored["Minutes To Start"].apply(time_penalty)
    scored["Books Bonus"] = scored["Books Quoting"].apply(lambda x: min((x - 1) * 0.55, 2.20))

    scored["Bet Score"] = (
        scored["Edge %"] * 0.95
        + scored["Best Line Gap %"] * 0.35
        + scored["Books Bonus"]
        + scored["Market Weight"]
        + scored["Time Penalty"]
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
    scored["Context Tags"] = "Vegas web board"
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
    main_event_taken = set()

    candidates = controlled[controlled["Status"] == "Bet"].sort_values(
        ["Rank Score", "Edge %", "Books Quoting", "Market Rank"],
        ascending=[False, False, False, True],
    )

    for idx, row in candidates.iterrows():
        event_id = row["Event ID"]
        sport = row["Sport"]
        book = row["Sportsbook"]
        recommended = float(row["Recommended Bet"])
        note_parts = []

        if use_correlation_guard and event_id in main_event_taken:
            controlled.at[idx, "Final Status"] = "Pass"
            controlled.at[idx, "Allocation Status"] = "Correlation Pass"
            controlled.at[idx, "Pass Reason"] = build_allocation_note(row, "same-event side already selected")
            controlled.at[idx, "Correlation Flag"] = "Blocked"
            continue

        remaining_total = max_total_exposure - total_used
        remaining_sport = max_sport_exposure - sport_used.get(sport, 0.0)
        remaining_event = max_event_exposure - event_used.get(event_id, 0.0)
        remaining_book = max_book_exposure - book_used.get(book, 0.0)

        alloc = min(recommended, remaining_total, remaining_sport, remaining_event, remaining_book)
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
                reasons.append("book cap reached")
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
        main_event_taken.add(event_id)

        controlled.at[idx, "Pass Reason"] = build_allocation_note(row, " • ".join(note_parts))

    return controlled


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
    notes.append(f"**Vegas source detail:** {row.get('Source Detail', 'N/A')}")
    notes.append(f"**Risk controls:** {row.get('Allocation Status', '—')}. {row.get('Pass Reason', '') or 'No extra pass note; the play fits the current controls.'}")
    if not same.empty:
        best = same.iloc[0]
        line_gap = float(same["Implied Prob"].max() - same["Implied Prob"].min()) if len(same) > 1 else 0.0
        notes.append(
            f"**Best-book context:** best book is {best.get('Sportsbook', '—')} at {best.get('Odds', '—')} with a line gap of {line_gap:.2f}% across {len(same)} books."
        )
    return "\n\n".join(notes)


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
        margin-bottom: 1rem;
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

    div[data-baseweb="select"] > div,
    div[data-baseweb="base-input"] > div {
        color: black !important;
        background: #FFFFFF !important;
    }

    div[data-baseweb="select"] input,
    div[data-baseweb="base-input"] input {
        color: black !important;
    }

    .book-link-card {
        background: linear-gradient(135deg, #ffffff 0%, #f3f8ff 100%);
        border: 1px solid #cfe1f7;
        border-top: 5px solid #2b73d5;
        border-radius: 18px;
        padding: 14px 14px 12px 14px;
        box-shadow: 0 10px 22px rgba(22, 59, 104, 0.09);
        min-height: 70px;
        margin-bottom: 10px;
    }

    .book-link-title {
        color: #173b67;
        font-size: 1.05rem;
        font-weight: 900;
        margin-bottom: 6px;
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

st.sidebar.title("⚙️ Vegas Dashboard Controls")

bankroll = st.sidebar.number_input("Bankroll", min_value=1.0, value=500.0, step=25.0)
min_bet = st.sidebar.number_input("Minimum Bet", min_value=1.0, value=1.0, step=1.0)
max_bet = st.sidebar.number_input("Maximum Bet", min_value=1.0, value=10.0, step=1.0)

league_filter = st.sidebar.multiselect(
    "Leagues",
    options=DEFAULT_LEAGUES,
    default=["NBA", "MLB", "NHL"],
)

book_filter = st.sidebar.multiselect(
    "Books",
    options=DISPLAY_BOOKS,
    default=["DraftKings", "FanDuel", "BetMGM", "Bet365", "Caesars", "Consensus"],
)

max_total_exposure = st.sidebar.number_input("Max Total Exposure", min_value=1.0, value=30.0, step=1.0)
max_sport_exposure = st.sidebar.number_input("Max Exposure per Sport", min_value=1.0, value=12.0, step=1.0)
max_event_exposure = st.sidebar.number_input("Max Exposure per Event", min_value=1.0, value=8.0, step=1.0)
max_book_exposure = st.sidebar.number_input("Max Exposure per Book", min_value=1.0, value=12.0, step=1.0)
max_prop_exposure = st.sidebar.number_input("Max Exposure on Props", min_value=1.0, value=8.0, step=1.0)
correlation_guard = st.sidebar.toggle("Correlation Protection", value=True)
watchlist_query = st.sidebar.text_input("Watchlist filter", placeholder="Knicks, Celtics, totals...")
watchlist_only = st.sidebar.toggle("Show watchlist matches only", value=False)
only_final_bets = st.sidebar.toggle("Show final bets only", value=False)

if st.sidebar.button("Refresh now"):
    st.cache_data.clear()
    st.rerun()

st.markdown('<div class="main-title">🏈 Vegas Odds Dashboard</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">Public-web Vegas version using VegasInsider odds pages with 15-minute caching and manual refresh.</div>',
    unsafe_allow_html=True,
)

render_quick_links()


@st.fragment(run_every="15m")
def render_live_dashboard():
    raw_df, error_message = fetch_vegas_rows(league_filter)

    if error_message:
        st.warning(error_message)

    if raw_df.empty:
        st.warning("No Vegas lines came back for the leagues selected.")
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
            display_time = best_row.get("Display Time", "") or "Time not parsed"
            st.markdown(
                f"""
                **{best_row['Pick']}**  
                {best_row['Event']} · {best_row['Market']} · {display_time}  
                Book: **{best_row['Sportsbook']}** · Odds: **{best_row['Odds']}** · Previous: **{best_row['Prev Odds']}**  
                Edge: **{best_row['Edge %']:.2f}%** · Score: **{best_row['AI Score']:.2f}** · Final Bet: **${int(best_row['Final Bet'])}**  
                Line: **{best_row['Line']}** · Move: **{best_row['Line Move %']:+.2f}%**  
                Reason: *{best_row['Pass Reason'] or best_row['Reason']}*  
                {pills}
                """,
                unsafe_allow_html=True,
            )
            if best_row["Link"]:
                st.markdown(f"[Open book]({best_row['Link']})")
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
        "Books",
        "Bankroll",
    ])

    with tabs[0]:
        st.markdown('<div class="section-title">Top 3 Bets</div>', unsafe_allow_html=True)
        top_df = live_bets.head(3)
        if top_df.empty:
            st.warning("No final bets available right now.")
        else:
            for _, row in top_df.iterrows():
                st.markdown(
                    f"""
                    <div class="best-bet">
                        <b>{row['Pick']}</b><br>
                        {row['Event']} · {row['Market']} · {row.get('Display Time', 'Time not parsed')}<br>
                        Book: <b>{row['Sportsbook']}</b> · Odds: <b>{row['Odds']}</b> · Prev: <b>{row['Prev Odds']}</b><br>
                        Edge: <b>{row['Edge %']:.2f}%</b> · Score: <b>{row['AI Score']:.2f}</b> · Confidence: <b>{row['Confidence']}</b><br>
                        Final Bet: <b>${int(row['Final Bet'])}</b> · Line: <b>{row['Line']}</b> · Move: <b>{row['Line Move %']:+.2f}% ({row['Move Label']})</b><br>
                        Decision: <b>{row['Allocation Status']}</b> {row['Watchlist Label']}<br>
                        {build_badges_html(row)}<br>
                        Reason: <i>{row['Pass Reason'] or row['Reason']}</i>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        c1, c2 = st.columns(2)
        with c1:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown("**Score by Book**")
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

    with tabs[1]:
        st.markdown('<div class="section-title">Sports News</div>', unsafe_allow_html=True)
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
                "Display Time",
                "Market",
                "Pick",
                "Sportsbook",
                "Line",
                "Prev Odds",
                "Odds",
                "Watchlist Label",
                "Confidence Tag",
                "Move Tag",
                "Decision Tag",
                "Line Move %",
                "Implied Prob",
                "Model Prob",
                "Edge %",
                "Best Line Gap %",
                "Books Quoting",
                "Bet Score",
                "AI Score",
                "Recommended Bet",
                "Final Bet",
                "Allocation Status",
                "Final Status",
                "Pass Reason",
                "Source Detail",
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
                    "Edge %",
                    min_value=0.0,
                    max_value=max(float(max(display_df["Edge %"].max(), 1.0)), 1.0),
                    format="%.2f%%",
                ),
                "Best Line Gap %": st.column_config.NumberColumn(format="%.2f%%"),
                "Bet Score": st.column_config.ProgressColumn(
                    "Bet Score",
                    min_value=0.0,
                    max_value=max(float(max(display_df["Bet Score"].max(), 1.0)), 1.0),
                    format="%.2f",
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
            st.markdown(build_book_snapshot_html(explained_row, filtered_df), unsafe_allow_html=True)
            st.markdown(build_explain_bet_markdown(explained_row, filtered_df), unsafe_allow_html=False)

    with tabs[3]:
        st.markdown('<div class="section-title">By Book</div>', unsafe_allow_html=True)
        selected_book = st.selectbox("Choose book", options=book_filter, key="book_select")
        book_df = filtered_df[filtered_df["Sportsbook"] == selected_book].copy()

        if book_df.empty:
            st.warning(f"No rows currently available for {selected_book}.")
        else:
            book_df["Link"] = book_df["Link"].apply(make_link_markdown)
            book_df["Minutes To Start"] = book_df["Minutes To Start"].apply(format_minutes)
            st.dataframe(
                book_df[
                    [
                        "Sport",
                        "Event",
                        "Display Time",
                        "Pick",
                        "Line",
                        "Odds",
                        "Prev Odds",
                        "Edge %",
                        "Bet Score",
                        "AI Score",
                        "Final Bet",
                        "Allocation Status",
                        "Pass Reason",
                        "Link",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Edge %": st.column_config.NumberColumn(format="%.2f%%"),
                    "Final Bet": st.column_config.NumberColumn(format="$%d"),
                    "Link": st.column_config.LinkColumn("Open"),
                },
            )

    with tabs[4]:
        st.markdown('<div class="section-title">Bankroll + Exposure Rules</div>', unsafe_allow_html=True)
        caps_df = pd.DataFrame(
            {
                "Rule": [
                    "Per Sport",
                    "Per Event",
                    "Per Book",
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

        if not exposure_by_book.empty:
            st.markdown("**Current Open Exposure by Book**")
            st.bar_chart(exposure_by_book)


render_live_dashboard()
