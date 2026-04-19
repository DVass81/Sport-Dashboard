from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from html import escape
import re
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
HEADLINE_POSITIVE_WORDS = {"streak", "streaking", "hot", "surge", "rolling", "dominant", "dominance", "healthy", "returns", "returning", "breakout", "heater", "homer", "home run", "wins", "winning"}
HEADLINE_NEGATIVE_WORDS = {"injury", "injured", "out", "questionable", "doubtful", "miss", "missing", "slump", "cold", "struggle", "struggling", "scratch", "sits", "ruled out", "day-to-day"}
HEADLINE_WEATHER_WORDS = {"rain", "wind", "snow", "weather", "storm", "cold", "heat"}
HEADLINE_SURFACE_WORDS = {"turf", "grass", "surface"}
HEADLINE_TIME_WORDS = {"morning", "afternoon", "night", "early", "late", "matinee"}
HEADLINE_STREAK_WORDS = {"streak", "streaking", "heater", "homer", "home run", "hit streak", "hot"}
EVENT_STOPWORDS = {"vs", "at", "the", "and", "for", "with", "from", "new", "los", "angeles", "san", "city", "york", "las", "vegas"}
OUTDOOR_SPORTS = {"NFL", "MLB"}
INDOOR_SPORTS = {"NBA", "NHL"}
TEAM_ENV = {
    "Cardinals": {"lat": 33.5275, "lon": -112.2626, "venue_type": "roofed", "surface": "grass"},
    "Falcons": {"lat": 33.7554, "lon": -84.4011, "venue_type": "roofed", "surface": "turf"},
    "Ravens": {"lat": 39.2780, "lon": -76.6227, "venue_type": "outdoor", "surface": "grass"},
    "Bills": {"lat": 42.7738, "lon": -78.7868, "venue_type": "outdoor", "surface": "grass"},
    "Panthers": {"lat": 35.2258, "lon": -80.8528, "venue_type": "outdoor", "surface": "grass"},
    "Bears": {"lat": 41.8623, "lon": -87.6167, "venue_type": "outdoor", "surface": "grass"},
    "Bengals": {"lat": 39.0954, "lon": -84.5160, "venue_type": "outdoor", "surface": "turf"},
    "Browns": {"lat": 41.5061, "lon": -81.6995, "venue_type": "outdoor", "surface": "grass"},
    "Cowboys": {"lat": 32.7473, "lon": -97.0945, "venue_type": "roofed", "surface": "turf"},
    "Broncos": {"lat": 39.7439, "lon": -105.0201, "venue_type": "outdoor", "surface": "grass"},
    "Lions": {"lat": 42.3400, "lon": -83.0456, "venue_type": "indoor", "surface": "turf"},
    "Packers": {"lat": 44.5013, "lon": -88.0622, "venue_type": "outdoor", "surface": "grass"},
    "Texans": {"lat": 29.6847, "lon": -95.4107, "venue_type": "roofed", "surface": "grass"},
    "Colts": {"lat": 39.7601, "lon": -86.1639, "venue_type": "roofed", "surface": "turf"},
    "Jaguars": {"lat": 30.3239, "lon": -81.6373, "venue_type": "outdoor", "surface": "grass"},
    "Chiefs": {"lat": 39.0489, "lon": -94.4839, "venue_type": "outdoor", "surface": "grass"},
    "Raiders": {"lat": 36.0908, "lon": -115.1830, "venue_type": "roofed", "surface": "grass"},
    "Chargers": {"lat": 33.9535, "lon": -118.3392, "venue_type": "roofed", "surface": "turf"},
    "Rams": {"lat": 33.9535, "lon": -118.3392, "venue_type": "roofed", "surface": "turf"},
    "Dolphins": {"lat": 25.9580, "lon": -80.2389, "venue_type": "outdoor", "surface": "grass"},
    "Vikings": {"lat": 44.9737, "lon": -93.2575, "venue_type": "indoor", "surface": "turf"},
    "Patriots": {"lat": 42.0909, "lon": -71.2643, "venue_type": "outdoor", "surface": "turf"},
    "Saints": {"lat": 29.9511, "lon": -90.0812, "venue_type": "roofed", "surface": "turf"},
    "Giants": {"lat": 40.8135, "lon": -74.0745, "venue_type": "outdoor", "surface": "turf"},
    "Jets": {"lat": 40.8135, "lon": -74.0745, "venue_type": "outdoor", "surface": "turf"},
    "Eagles": {"lat": 39.9008, "lon": -75.1675, "venue_type": "outdoor", "surface": "grass"},
    "Steelers": {"lat": 40.4468, "lon": -80.0158, "venue_type": "outdoor", "surface": "grass"},
    "49ers": {"lat": 37.4030, "lon": -121.9700, "venue_type": "outdoor", "surface": "grass"},
    "Seahawks": {"lat": 47.5952, "lon": -122.3316, "venue_type": "outdoor", "surface": "turf"},
    "Buccaneers": {"lat": 27.9759, "lon": -82.5033, "venue_type": "outdoor", "surface": "grass"},
    "Titans": {"lat": 36.1665, "lon": -86.7713, "venue_type": "outdoor", "surface": "grass"},
    "Commanders": {"lat": 38.9078, "lon": -76.8644, "venue_type": "outdoor", "surface": "grass"},
    "Diamondbacks": {"lat": 33.4453, "lon": -112.0667, "venue_type": "roofed", "surface": "grass"},
    "Braves": {"lat": 33.8908, "lon": -84.4677, "venue_type": "outdoor", "surface": "grass"},
    "Orioles": {"lat": 39.2840, "lon": -76.6217, "venue_type": "outdoor", "surface": "grass"},
    "Red Sox": {"lat": 42.3467, "lon": -71.0972, "venue_type": "outdoor", "surface": "grass"},
    "Cubs": {"lat": 41.9484, "lon": -87.6553, "venue_type": "outdoor", "surface": "grass"},
    "White Sox": {"lat": 41.8300, "lon": -87.6338, "venue_type": "outdoor", "surface": "grass"},
    "Reds": {"lat": 39.0979, "lon": -84.5082, "venue_type": "outdoor", "surface": "grass"},
    "Guardians": {"lat": 41.4962, "lon": -81.6852, "venue_type": "outdoor", "surface": "grass"},
    "Rockies": {"lat": 39.7559, "lon": -104.9942, "venue_type": "outdoor", "surface": "grass"},
    "Tigers": {"lat": 42.3390, "lon": -83.0485, "venue_type": "outdoor", "surface": "grass"},
    "Astros": {"lat": 29.7573, "lon": -95.3555, "venue_type": "roofed", "surface": "grass"},
    "Royals": {"lat": 39.0517, "lon": -94.4803, "venue_type": "outdoor", "surface": "grass"},
    "Angels": {"lat": 33.8003, "lon": -117.8827, "venue_type": "outdoor", "surface": "grass"},
    "Dodgers": {"lat": 34.0739, "lon": -118.2400, "venue_type": "outdoor", "surface": "grass"},
    "Marlins": {"lat": 25.7781, "lon": -80.2197, "venue_type": "roofed", "surface": "grass"},
    "Brewers": {"lat": 43.0280, "lon": -87.9712, "venue_type": "roofed", "surface": "grass"},
    "Twins": {"lat": 44.9817, "lon": -93.2775, "venue_type": "outdoor", "surface": "grass"},
    "Mets": {"lat": 40.7571, "lon": -73.8458, "venue_type": "outdoor", "surface": "grass"},
    "Yankees": {"lat": 40.8296, "lon": -73.9262, "venue_type": "outdoor", "surface": "grass"},
    "Athletics": {"lat": 36.0668, "lon": -115.1780, "venue_type": "outdoor", "surface": "grass"},
    "Phillies": {"lat": 39.9061, "lon": -75.1665, "venue_type": "outdoor", "surface": "grass"},
    "Pirates": {"lat": 40.4469, "lon": -80.0057, "venue_type": "outdoor", "surface": "grass"},
    "Padres": {"lat": 32.7073, "lon": -117.1573, "venue_type": "outdoor", "surface": "grass"},
    "Mariners": {"lat": 47.5914, "lon": -122.3325, "venue_type": "roofed", "surface": "grass"},
    "Rays": {"lat": 27.7682, "lon": -82.6534, "venue_type": "indoor", "surface": "turf"},
    "Rangers": {"lat": 32.7473, "lon": -97.0847, "venue_type": "roofed", "surface": "turf"},
    "Blue Jays": {"lat": 43.6414, "lon": -79.3894, "venue_type": "roofed", "surface": "turf"},
    "Nationals": {"lat": 38.8730, "lon": -77.0074, "venue_type": "outdoor", "surface": "grass"},
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


@st.cache_data(ttl=900, show_spinner=False)
def fetch_news_items_for_leagues(leagues, per_feed=5):
    items = []
    for feed_name in get_news_feed_names(leagues):
        items.extend(fetch_news_feed(feed_name, limit=per_feed))
    return items


def event_terms_from_row(row):
    event_text = str(row.get("Event", "")).replace("@", " ")
    tokens = []
    for part in re.split(r"[^A-Za-z0-9]+", event_text.lower()):
        part = part.strip()
        if len(part) >= 3 and part not in EVENT_STOPWORDS:
            tokens.append(part)
    return list(dict.fromkeys(tokens))[:8]


def daypart_from_start(value):
    dt = parse_iso_datetime(value)
    if dt is None:
        return "Unknown"
    eastern = dt.astimezone(ZoneInfo("America/New_York"))
    hour = eastern.hour
    if 5 <= hour < 11:
        return "Morning"
    if 11 <= hour < 16:
        return "Afternoon"
    if 16 <= hour < 21:
        return "Evening"
    return "Night"


def build_headline_context(row, news_items):
    terms = event_terms_from_row(row)
    matched = []
    for item in news_items or []:
        haystack = f"{item.get('title', '')} {item.get('description', '')}".lower()
        if any(term in haystack for term in terms):
            matched.append(haystack)

    joined = " || ".join(matched)
    positive_hits = sum(1 for word in HEADLINE_POSITIVE_WORDS if word in joined)
    negative_hits = sum(1 for word in HEADLINE_NEGATIVE_WORDS if word in joined)
    weather_hits = sum(1 for word in HEADLINE_WEATHER_WORDS if word in joined)
    surface_hits = sum(1 for word in HEADLINE_SURFACE_WORDS if word in joined)
    streak_hits = sum(1 for word in HEADLINE_STREAK_WORDS if word in joined)
    time_hits = sum(1 for word in HEADLINE_TIME_WORDS if word in joined)

    tags = []
    if positive_hits:
        tags.append("Positive News")
    if negative_hits:
        tags.append("Injury / Risk News")
    if weather_hits:
        tags.append("Weather Watch")
    if surface_hits:
        tags.append("Surface Note")
    if streak_hits:
        tags.append("Streak Signal")
    if time_hits:
        tags.append("Timing Angle")

    return {
        "headline_matches": len(matched),
        "positive_hits": positive_hits,
        "negative_hits": negative_hits,
        "weather_hits": weather_hits,
        "surface_hits": surface_hits,
        "streak_hits": streak_hits,
        "time_hits": time_hits,
        "tags": tags,
    }


def default_team_env(row):
    sport = str(row.get("Sport", ""))
    if sport in INDOOR_SPORTS:
        return {"venue_type": "indoor", "surface": "hardcourt" if sport == "NBA" else "ice"}
    return {"venue_type": "outdoor", "surface": "grass"}


def team_environment(row):
    home_team = str(row.get("Home Team", ""))
    env = TEAM_ENV.get(home_team)
    return env if env else default_team_env(row)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_weather_snapshot(lat, lon, start_time):
    if lat is None or lon is None or not start_time:
        return {}
    dt = parse_iso_datetime(start_time)
    if dt is None:
        return {}
    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m,precipitation_probability,precipitation,wind_speed_10m",
                "forecast_days": 7,
                "timezone": "UTC",
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        if not times:
            return {}
        target = dt.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:00")
        if target in times:
            idx = times.index(target)
        else:
            target_ts = int(dt.timestamp())
            def hour_ts(t):
                return int(datetime.fromisoformat(t).replace(tzinfo=timezone.utc).timestamp())
            idx = min(range(len(times)), key=lambda i: abs(hour_ts(times[i]) - target_ts))
        temp_c = hourly.get("temperature_2m", [None])[idx]
        precip_prob = hourly.get("precipitation_probability", [None])[idx]
        precip = hourly.get("precipitation", [None])[idx]
        wind_kph = hourly.get("wind_speed_10m", [None])[idx]
        return {
            "temp_f": None if temp_c is None else round((temp_c * 9 / 5) + 32, 1),
            "precip_prob": precip_prob,
            "precip_mm": precip,
            "wind_mph": None if wind_kph is None else round(wind_kph / 1.60934, 1),
        }
    except Exception:
        return {}


def weather_summary_from_metrics(row):
    venue = row.get("Venue Type", "Unknown")
    if venue in {"Indoor", "Roofed"}:
        return f"{venue} venue"
    parts = []
    if pd.notna(row.get("Temp F")):
        parts.append(f"{row['Temp F']:.0f}°F")
    if pd.notna(row.get("Wind MPH")):
        parts.append(f"{row['Wind MPH']:.0f} mph wind")
    if pd.notna(row.get("Precip Prob")) and row.get("Precip Prob", 0) > 0:
        parts.append(f"{row['Precip Prob']:.0f}% rain chance")
    return " • ".join(parts) if parts else "Outdoor conditions unavailable"


def apply_weather_context(df):
    if df.empty:
        return df
    rows = []
    for _, row in df.iterrows():
        env = team_environment(row)
        venue_type = str(env.get("venue_type", "outdoor")).title()
        surface = str(env.get("surface", "grass")).title()
        lat = env.get("lat")
        lon = env.get("lon")
        snapshot = fetch_weather_snapshot(lat, lon, row.get("Start Time")) if venue_type == "Outdoor" and lat is not None and lon is not None else {}
        temp_f = snapshot.get("temp_f")
        precip_prob = snapshot.get("precip_prob")
        precip_mm = snapshot.get("precip_mm")
        wind_mph = snapshot.get("wind_mph")
        score = 0.0
        bucket = row.get("Market Bucket")
        if venue_type in {"Indoor", "Roofed"}:
            if bucket in {"Moneyline", "Spread", "Total"}:
                score += 0.10
        else:
            if wind_mph is not None and wind_mph >= 15:
                if bucket in {"Total", "Player Prop", "DFS Prop", "Team Total"}:
                    score -= 0.45
                else:
                    score += 0.10
            if precip_prob is not None and precip_prob >= 45:
                if bucket in {"Total", "Player Prop", "DFS Prop", "Team Total"}:
                    score -= 0.35
                else:
                    score -= 0.10
            if temp_f is not None and temp_f <= 40 and bucket in {"Total", "Player Prop", "DFS Prop"}:
                score -= 0.15
        if surface == "Turf" and bucket in {"Spread", "Moneyline"}:
            score += 0.10
        if surface == "Grass" and bucket in {"Total", "Player Prop", "DFS Prop"}:
            score -= 0.05
        rows.append({
            "Venue Type": venue_type,
            "Surface Type": surface,
            "Temp F": temp_f,
            "Wind MPH": wind_mph,
            "Precip Prob": precip_prob,
            "Precip MM": precip_mm,
            "Weather Score": round(score, 2),
        })
    weather_df = pd.DataFrame(rows)
    enriched = pd.concat([df.reset_index(drop=True), weather_df.reset_index(drop=True)], axis=1)
    enriched["Weather Summary"] = enriched.apply(weather_summary_from_metrics, axis=1)
    enriched["Weather Flag"] = enriched.apply(
        lambda row: "Wind/Rain Risk" if ((pd.notna(row.get("Wind MPH")) and row.get("Wind MPH", 0) >= 15) or (pd.notna(row.get("Precip Prob")) and row.get("Precip Prob", 0) >= 45))
        else ("Indoor / Stable" if row.get("Venue Type") in {"Indoor", "Roofed"} else "Weather Neutral"),
        axis=1,
    )
    return enriched


def build_context_reason(row):
    parts = []
    if row.get("Headline Matches", 0) > 0:
        parts.append(f"{int(row['Headline Matches'])} related headline hits")
    if row.get("Positive News Hits", 0) > 0:
        parts.append("positive headline tone")
    if row.get("Negative News Hits", 0) > 0:
        parts.append("injury/risk headline tone")
    if row.get("Weather Hits", 0) > 0:
        parts.append("weather mention in related news")
    if row.get("Surface Hits", 0) > 0:
        parts.append("surface mention in related news")
    if row.get("Streak Hits", 0) > 0:
        parts.append("recent streak angle detected")
    if row.get("Move Label") == "Improving":
        parts.append("line is moving in your favor")
    if row.get("Move Label") == "Worse":
        parts.append("line moved against you")
    if row.get("Venue Type"):
        parts.append(f"{str(row.get('Venue Type')).lower()} venue")
    if row.get("Surface Type") and str(row.get("Surface Type")).lower() not in {"hardcourt", "ice"}:
        parts.append(f"{str(row.get('Surface Type')).lower()} surface")
    if row.get("Weather Flag") and row.get("Weather Flag") not in {"Weather Neutral", "Indoor / Stable"}:
        parts.append(str(row.get("Weather Flag")).lower())
    daypart = row.get("Daypart", "")
    if daypart and daypart != "Unknown":
        parts.append(f"{daypart.lower()} game window")
    return " • ".join(parts)


def apply_context_ai(df, news_items, min_bet, max_bet):
    if df.empty:
        return df

    contexts = [build_headline_context(row, news_items) for _, row in df.iterrows()]
    ctx_df = pd.DataFrame(contexts)
    enriched = pd.concat([df.reset_index(drop=True), ctx_df.reset_index(drop=True)], axis=1)
    enriched["Daypart"] = enriched["Start Time"].apply(daypart_from_start)

    enriched["Headline Matches"] = enriched["headline_matches"].fillna(0).astype(int)
    enriched["Positive News Hits"] = enriched["positive_hits"].fillna(0).astype(int)
    enriched["Negative News Hits"] = enriched["negative_hits"].fillna(0).astype(int)
    enriched["Weather Hits"] = enriched["weather_hits"].fillna(0).astype(int)
    enriched["Surface Hits"] = enriched["surface_hits"].fillna(0).astype(int)
    enriched["Streak Hits"] = enriched["streak_hits"].fillna(0).astype(int)
    enriched["Time News Hits"] = enriched["time_hits"].fillna(0).astype(int)
    enriched["Context Tags"] = enriched["tags"].apply(lambda vals: ", ".join(vals[:3]) if vals else "No major context flags")

    move_bonus = enriched["Move Label"].map({"Improving": 0.60, "Flat": 0.00, "Worse": -0.60, "New": 0.10}).fillna(0.0)
    positive_bonus = (enriched["Positive News Hits"].clip(upper=2) * 0.35)
    negative_penalty = (enriched["Negative News Hits"].clip(upper=3) * -0.45)
    weather_penalty = enriched.apply(lambda row: -0.30 if row["Weather Hits"] > 0 and row["Market Bucket"] in {"Total", "Player Prop", "DFS Prop"} else (-0.10 if row["Weather Hits"] > 0 else 0.0), axis=1)
    surface_bonus = enriched.apply(lambda row: 0.20 if row["Surface Hits"] > 0 and row["Market Bucket"] in {"Spread", "Total"} else 0.0, axis=1)
    streak_bonus = enriched.apply(lambda row: 0.35 if row["Streak Hits"] > 0 and row["Market Bucket"] in {"Player Prop", "DFS Prop", "Moneyline"} else 0.15 if row["Streak Hits"] > 0 else 0.0, axis=1)
    books_bonus = enriched["Books Quoting"].apply(lambda x: 0.15 if x >= 3 else 0.0)
    real_weather = enriched.get("Weather Score", pd.Series([0.0] * len(enriched)))

    enriched["Context Score"] = (move_bonus + positive_bonus + negative_penalty + weather_penalty + surface_bonus + streak_bonus + books_bonus + real_weather).round(2)
    enriched["AI Score"] = (enriched["Bet Score"] + enriched["Context Score"]).round(2)
    enriched["AI Tier"] = enriched["AI Score"].apply(lambda x: "Bet of the Day" if x >= 8 else ("Best Value" if x >= 6 else ("Safest Play" if x >= 5 else "Board Play")))
    enriched["Confidence"] = enriched["AI Score"].apply(confidence_from_score)
    enriched["Recommended Bet"] = enriched.apply(
        lambda row: bet_size_from_score(
            edge=row["Edge %"],
            score=row["AI Score"],
            min_bet=min_bet,
            max_bet=max_bet,
        ),
        axis=1,
    )
    enriched["Status"] = enriched["Recommended Bet"].apply(lambda x: "Bet" if x > 0 else "No Bet")
    enriched["AI Reason"] = enriched.apply(build_context_reason, axis=1)
    enriched["Reason"] = enriched.apply(
        lambda row: row["Reason"] + (" • " + row["AI Reason"] if row["AI Reason"] else ""),
        axis=1,
    )
    enriched["Rank Score"] = enriched["AI Score"]
    return enriched


def build_decision_center_insight(live_bets):
    if live_bets is None or live_bets.empty:
        return "No final bets qualify right now. The board is waiting for a stronger edge or cleaner context setup."
    top = live_bets.iloc[0]
    tags = top.get("Context Tags", "No major context flags")
    return (
        f"Top board lean is {top['Pick']} at {top['Sportsbook']} because the AI score is {top['AI Score']:.2f}, "
        f"the market edge is {top['Edge %']:.2f}%, the weather read is {str(top.get('Weather Flag', 'Weather Neutral')).lower()}, and the context lens is seeing {tags.lower()}."
    )


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
    notes.append(f"**Conditions:** {row.get('Weather Summary', 'No weather note')} · venue {row.get('Venue Type', 'Unknown')} · surface {row.get('Surface Type', 'Unknown')}.")
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


# -----------------------------
# LIVE FETCH
# -----------------------------
# -----------------------------
# LIVE FETCH
# -----------------------------
def _get_cached_events_fallback(cache_key):
    if "last_good_events" not in st.session_state:
        st.session_state["last_good_events"] = {}
    return st.session_state["last_good_events"].get(cache_key, [])


def _set_cached_events_fallback(cache_key, events):
    if "last_good_events" not in st.session_state:
        st.session_state["last_good_events"] = {}
    st.session_state["last_good_events"][cache_key] = events


def _fetch_events_for_single_league(api_key, league):
    url = "https://api.sportsgameodds.com/v2/events/"
    headers = {"x-api-key": api_key}
    params = {
        "leagueID": league,
        "oddsAvailable": "true",
        "limit": 35,
    }

    backoff_seconds = [1, 2, 4]

    for attempt, wait_time in enumerate(backoff_seconds, start=1):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=25)

            if response.status_code == 429:
                if attempt < len(backoff_seconds):
                    time.sleep(wait_time)
                    continue
                return [], f"Rate limit reached for {league}. The API returned 429 Too Many Requests."

            if response.status_code in (401, 403):
                return [], "SportsGameOdds API key is missing, invalid, or does not have access to this endpoint."

            response.raise_for_status()
            payload = response.json()
            events = payload.get("data", []) if isinstance(payload, dict) else payload
            return events, ""

        except requests.exceptions.Timeout:
            if attempt < len(backoff_seconds):
                time.sleep(wait_time)
                continue
            return [], f"Timed out while loading {league} odds."
        except requests.exceptions.RequestException as exc:
            return [], f"API request failed for {league}: {exc}"
        except Exception as exc:
            return [], f"Unexpected error while loading {league}: {exc}"

    return [], f"Could not load {league} after multiple attempts."


@st.cache_data(ttl=1800, show_spinner="Loading live odds...")
def fetch_events(leagues):
    api_key = st.secrets.get("SPORTS_GAME_ODDS_API_KEY", "")
    if not api_key:
        return [], "Missing SPORTS_GAME_ODDS_API_KEY in Streamlit secrets.", False

    selected_leagues = list(leagues or [])
    if not selected_leagues:
        return [], "Please select at least one league.", False

    cache_key = "|".join(sorted(selected_leagues))
    all_events = []
    messages = []
    had_429 = False

    for league in selected_leagues:
        league_events, league_error = _fetch_events_for_single_league(api_key, league)

        if league_error:
            messages.append(league_error)
            if "429" in league_error or "Rate limit" in league_error:
                had_429 = True
            continue

        all_events.extend(league_events)
        time.sleep(0.35)

    if all_events:
        _set_cached_events_fallback(cache_key, all_events)
        if messages:
            return all_events, "Loaded with partial warnings: " + " | ".join(messages), False
        return all_events, "", False

    fallback_events = _get_cached_events_fallback(cache_key)
    if fallback_events:
        if had_429:
            return fallback_events, "SportsGameOdds rate limit hit. Showing last successful cached board.", True
        return fallback_events, "Live API failed. Showing last successful cached board.", True

    if had_429:
        return [], "SportsGameOdds rate limit hit. Wait a few minutes, then click Refresh now.", False

    return [], " | ".join(messages) if messages else "No live odds could be loaded.", False

# -----------------------------
# SCORING
# -----------------------------
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
    return scored


# -----------------------------
# LINE MOVEMENT + RISK CONTROLS
# -----------------------------
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


# -----------------------------
# STYLING
# -----------------------------
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

    .pill {
        display: inline-block;
        background: #eaf3ff;
        color: #174272;
        border: 1px solid #c6dbf4;
        border-radius: 999px;
        padding: 4px 10px;
        font-size: 0.8rem;
        font-weight: 700;
        margin-right: 6px;
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

    .ticker-wrap {
        display: flex;
        align-items: center;
        gap: 14px;
        background: linear-gradient(135deg, #ffffff 0%, #eef5ff 100%);
        border: 1px solid #d3e4fa;
        border-radius: 18px;
        padding: 12px 16px;
        box-shadow: 0 8px 18px rgba(22, 59, 104, 0.07);
        margin: 12px 0 16px 0;
        overflow: hidden;
    }

    .ticker-label {
        flex: 0 0 auto;
        color: #173b67;
        font-size: 0.82rem;
        font-weight: 900;
        letter-spacing: 0.06em;
        background: #dcecff;
        border: 1px solid #bdd7fa;
        border-radius: 999px;
        padding: 7px 12px;
    }

    .ticker-track {
        position: relative;
        overflow: hidden;
        white-space: nowrap;
        width: 100%;
    }

    .ticker-move {
        display: inline-block;
        white-space: nowrap;
        color: #153457;
        font-size: 0.95rem;
        font-weight: 700;
        padding-left: 100%;
        animation: ticker-slide 34s linear infinite;
    }

    @keyframes ticker-slide {
        0% { transform: translateX(0); }
        100% { transform: translateX(-100%); }
    }

    .decision-card {
        background: linear-gradient(135deg, #ffffff 0%, #f5f9ff 100%);
        border: 1px solid #d6e4f5;
        border-radius: 18px;
        padding: 18px;
        box-shadow: 0 8px 20px rgba(22, 59, 104, 0.07);
        margin-bottom: 16px;
    }

    .decision-title {
        color: #163b68;
        font-size: 1.1rem;
        font-weight: 800;
        margin-bottom: 8px;
    }

    .decision-big {
        color: #0f2745;
        font-size: 1.4rem;
        font-weight: 900;
        line-height: 1.25;
    }

    .decision-sub {
        color: #49627f;
        font-size: 0.95rem;
        margin-top: 8px;
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

    .context-list {
        margin: 0;
        padding-left: 18px;
        color: #294866;
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


# -----------------------------
# SIDEBAR
# -----------------------------
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
    '<div class="sub-title">Lighter look, sharper controls, line movement tracking, and smarter risk allocation built on your stable version.</div>',
    unsafe_allow_html=True,
)

render_quick_links()

# -----------------------------
# LIVE DASHBOARD
# -----------------------------
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

    news_items = fetch_news_items_for_leagues(league_filter, per_feed=4)
    scored_df = apply_smart_scoring(raw_df, min_bet=min_bet, max_bet=max_bet)
    moved_df = apply_line_movement(scored_df)
    weather_df = apply_weather_context(moved_df)
    ai_df = apply_context_ai(weather_df, news_items=news_items, min_bet=min_bet, max_bet=max_bet)
    filtered_df = ai_df[ai_df["Sportsbook"].isin(book_filter)].copy()
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
                Edge: **{best_row['Edge %']:.2f}%** · AI Score: **{best_row['AI Score']:.2f}** · Final Bet: **${int(best_row['Final Bet'])}**  
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
                                <div class="hero-meta">AI Score {row['AI Score']:.2f} · Edge {row['Edge %']:.2f}% · {row['Weather Flag']}</div>
                                <div class="hero-meta">{row['Weather Summary']}</div>
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
                        <div class="decision-sub">AI Score {first['AI Score']:.2f} · Edge {first['Edge %']:.2f}% · Final Bet ${int(first['Final Bet'])}</div>
                        <div class="decision-sub">Weather: {first['Weather Summary']} · Surface: {first['Surface Type']} · Venue: {first['Venue Type']}</div>
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
                            Edge: <b>{row['Edge %']:.2f}%</b> · AI Score: <b>{row['AI Score']:.2f}</b> · Confidence: <b>{row['Confidence']}</b><br>
                            Final Bet: <b>${int(row['Final Bet'])}</b> · Move: <b>{row['Line Move %']:+.2f}% ({row['Move Label']})</b><br>
                            Weather: <b>{row['Weather Summary']}</b> · Surface: <b>{row['Surface Type']}</b><br>
                            Decision: <b>{row['Allocation Status']}</b> {row['Watchlist Label']}<br>
                            {build_badges_html(row)}<br>
                            Context: <b>{row['Context Tags']}</b><br>
                            Reason: <i>{row['Pass Reason'] or row['Reason']}</i>
                            {link_html}
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

        with top_right:
            st.markdown('<div class="section-title">Decision Center · AI Insight</div>', unsafe_allow_html=True)
            st.markdown(
                f"""
                <div class="decision-card">
                    <div class="decision-title">Insight of the Day</div>
                    <div class="decision-sub">{build_decision_center_insight(live_bets)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            context_watch = live_bets.head(5) if not live_bets.empty else pd.DataFrame()
            injury_flags = int((context_watch['Negative News Hits'] > 0).sum()) if not context_watch.empty else 0
            weather_flags = int((context_watch['Weather Flag'] != 'Weather Neutral').sum()) if not context_watch.empty else 0
            streak_flags = int((context_watch['Streak Hits'] > 0).sum()) if not context_watch.empty else 0
            st.markdown(
                f"""
                <div class="decision-card">
                    <div class="decision-title">Context Watch</div>
                    <ul class="context-list">
                        <li>Headline-linked bets on board: <b>{int((live_bets['Headline Matches'] > 0).sum()) if not live_bets.empty else 0}</b></li>
                        <li>Injury / risk news flags: <b>{injury_flags}</b></li>
                        <li>Weather / venue flags: <b>{weather_flags}</b></li>
                        <li>Streak signals: <b>{streak_flags}</b></li>
                        <li>Improving lines: <b>{improving_count}</b></li>
                    </ul>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown(
                f"""
                <div class="decision-card">
                    <div class="decision-title">Risk Gauge</div>
                    <div class="decision-sub">Open suggested exposure is <b>${open_risk}</b> against a max total cap of <b>${max_total_exposure:.0f}</b>.</div>
                    <div class="decision-sub">Average AI score on final bets is <b>{avg_score:.2f}</b> across <b>{active_bets}</b> bets.</div>
                    <div class="decision-sub">Average books quoting is <b>{avg_books:.2f}</b>. Outdoor weather-sensitive bets on board: <b>{int((live_bets['Venue Type'] == 'Outdoor').sum()) if not live_bets.empty else 0}</b>.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        c1, c2 = st.columns(2)
        with c1:
            st.markdown('<div class="card">', unsafe_allow_html=True)
            st.markdown("**AI Score by Sportsbook**")
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
            st.markdown("**Context Flags on Final Bets**")
            if live_bets.empty:
                st.info("No chart data available.")
            else:
                chart_df = pd.Series({
                    "Headline Hits": int((live_bets["Headline Matches"] > 0).sum()),
                    "Injury News": int((live_bets["Negative News Hits"] > 0).sum()),
                    "Weather News": int((live_bets["Weather Hits"] > 0).sum()),
                    "Weather/Venue": int((live_bets["Weather Flag"] != "Weather Neutral").sum()),
                    "Streaks": int((live_bets["Streak Hits"] > 0).sum()),
                })
                st.bar_chart(chart_df)
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
            st.markdown("**AI Score vs Edge Snapshot**")
            if live_bets.empty:
                st.info("No chart data available.")
            else:
                chart_df = live_bets[["Pick", "AI Score", "Edge %"]].head(8).set_index("Pick")
                st.line_chart(chart_df)
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
                • The ticker above rotates the freshest loaded headlines.<br>
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
                "Context Score",
                "Context Tags",
                "Weather Flag",
                "Weather Summary",
                "Surface Type",
                "Venue Type",
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
                            <div class="explain-stat-label">AI Score</div>
                            <div class="explain-stat-value">{explained_row['AI Score']:.2f}</div>
                        </div>
                        <div class="explain-stat">
                            <div class="explain-stat-label">Context</div>
                            <div class="explain-stat-value">{explained_row['Context Tags']}</div>
                        </div>
                        <div class="explain-stat">
                            <div class="explain-stat-label">Weather</div>
                            <div class="explain-stat-value">{explained_row['Weather Flag']}</div>
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
                It is no longer just best price — it is best price after timing, correlation, and exposure rules.
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
                "Context Score",
                "Context Tags",
                "Weather Flag",
                "Weather Summary",
                "Surface Type",
                "Venue Type",
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

        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown(
            """
            <b>What makes it pop more from here:</b><br>
            • add sportsbook logo images beside each tab card<br>
            • add row highlight badges for Elite / Improving / Trimmed<br>
            • add a compact quick-links ribbon at the top for one-click sportsbook jumps<br>
            • add watchlist filters for favorite teams or market types
            """,
            unsafe_allow_html=True,
        )
        st.markdown('</div>', unsafe_allow_html=True)


render_live_dashboard()
