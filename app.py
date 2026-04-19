from datetime import datetime, timezone
from html import escape
import requests
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Sports Command Dashboard",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -----------------------------
# CONFIG
# -----------------------------
API_KEY = st.secrets.get("THESPORTSDB_API_KEY", "")

V1_BASE = "https://www.thesportsdb.com/api/v1/json"
V2_BASE = "https://www.thesportsdb.com/api/v2/json"

LEAGUES = {
    "NBA": {"id": "4387", "sport": "Basketball"},
    "NFL": {"id": "4391", "sport": "American Football"},
    "MLB": {"id": "4424", "sport": "Baseball"},
    "NHL": {"id": "4380", "sport": "Ice Hockey"},
}

BOOKMARKED_TEAM_NAME = "Alabama Crimson Tide"

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# -----------------------------
# API HELPERS
# -----------------------------
def has_key() -> bool:
    return bool(str(API_KEY).strip())


@st.cache_data(ttl=300, show_spinner=False)
def tsdb_v1_get(endpoint: str, params: dict | None = None) -> dict:
    if not has_key():
        return {}
    url = f"{V1_BASE}/{API_KEY}/{endpoint}"
    try:
        resp = requests.get(url, params=params or {}, headers=REQUEST_HEADERS, timeout=25)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


@st.cache_data(ttl=120, show_spinner=False)
def tsdb_v2_get(endpoint: str, params: dict | None = None) -> dict:
    if not has_key():
        return {}
    url = f"{V2_BASE}/{endpoint}"
    try:
        resp = requests.get(
            url,
            params=params or {},
            headers={**REQUEST_HEADERS, "X-API-KEY": API_KEY},
            timeout=25,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


def first_nonempty(*values):
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return ""


def normalize_events_payload(payload: dict) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    for key in ["events", "event", "livescore", "results"]:
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def parse_dt(date_str: str, time_str: str) -> datetime | None:
    if not date_str:
        return None
    raw_time = (time_str or "00:00:00").replace("Z", "").strip()
    if len(raw_time) == 5:
        raw_time = f"{raw_time}:00"
    try:
        dt = datetime.fromisoformat(f"{date_str}T{raw_time}")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def display_event_time(date_str: str, time_str: str) -> str:
    dt = parse_dt(date_str, time_str)
    if dt is None:
        return first_nonempty(date_str, "TBD")
    return dt.astimezone().strftime("%Y-%m-%d %I:%M %p")


def format_score(home_score, away_score) -> str:
    hs = "" if home_score in (None, "") else str(home_score)
    aw = "" if away_score in (None, "") else str(away_score)
    if hs == "" and aw == "":
        return "—"
    return f"{aw} - {hs}"


def event_status_label(row: dict) -> str:
    return first_nonempty(
        row.get("strStatus"),
        row.get("strProgress"),
        row.get("strTimeLocal"),
        "Scheduled",
    )


# -----------------------------
# THE SPORTS DB LOADERS
# -----------------------------
@st.cache_data(ttl=1800, show_spinner=False)
def fetch_alabama_team():
    payload = tsdb_v1_get("searchteams.php", {"t": BOOKMARKED_TEAM_NAME})
    teams = payload.get("teams") if isinstance(payload, dict) else None
    if not isinstance(teams, list):
        return {}

    exact = None
    for team in teams:
        name = str(team.get("strTeam", "")).lower()
        if BOOKMARKED_TEAM_NAME.lower() in name:
            exact = team
            break

    return exact or (teams[0] if teams else {})


@st.cache_data(ttl=600, show_spinner="Loading live scores...")
def fetch_live_scores(selected_leagues: tuple[str, ...]) -> pd.DataFrame:
    rows = []
    for league_name in selected_leagues:
        league = LEAGUES.get(league_name)
        if not league:
            continue

        payload = tsdb_v2_get("livescore.php", {"l": league["id"]})
        events = normalize_events_payload(payload)

        for item in events:
            rows.append(
                {
                    "League": league_name,
                    "Event": f"{first_nonempty(item.get('strAwayTeam'), 'Away')} @ {first_nonempty(item.get('strHomeTeam'), 'Home')}",
                    "Home Team": first_nonempty(item.get("strHomeTeam")),
                    "Away Team": first_nonempty(item.get("strAwayTeam")),
                    "Home Badge": first_nonempty(item.get("strHomeTeamBadge")),
                    "Away Badge": first_nonempty(item.get("strAwayTeamBadge")),
                    "Date": first_nonempty(item.get("dateEvent")),
                    "Time": first_nonempty(item.get("strEventTime"), item.get("strTime")),
                    "Status": event_status_label(item),
                    "Score": format_score(item.get("intHomeScore"), item.get("intAwayScore")),
                    "Venue": first_nonempty(item.get("strVenue")),
                    "Round": first_nonempty(item.get("intRound")),
                    "Event ID": first_nonempty(item.get("idEvent")),
                }
            )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    return df.sort_values(["League", "Event"]).reset_index(drop=True)


@st.cache_data(ttl=1800, show_spinner="Loading upcoming games...")
def fetch_upcoming_events(selected_leagues: tuple[str, ...]) -> pd.DataFrame:
    rows = []
    for league_name in selected_leagues:
        league = LEAGUES.get(league_name)
        if not league:
            continue

        payload = tsdb_v1_get("eventsnextleague.php", {"id": league["id"]})
        events = normalize_events_payload(payload)

        for item in events:
            rows.append(
                {
                    "League": league_name,
                    "Event": f"{first_nonempty(item.get('strAwayTeam'), 'Away')} @ {first_nonempty(item.get('strHomeTeam'), 'Home')}",
                    "Home Team": first_nonempty(item.get("strHomeTeam")),
                    "Away Team": first_nonempty(item.get("strAwayTeam")),
                    "Date": first_nonempty(item.get("dateEvent")),
                    "Time": first_nonempty(item.get("strTime")),
                    "Display Time": display_event_time(item.get("dateEvent"), item.get("strTime")),
                    "Venue": first_nonempty(item.get("strVenue")),
                    "Season": first_nonempty(item.get("strSeason")),
                    "Round": first_nonempty(item.get("intRound")),
                    "Event ID": first_nonempty(item.get("idEvent")),
                    "Banner": first_nonempty(item.get("strBanner")),
                    "Thumb": first_nonempty(item.get("strThumb")),
                }
            )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    return df.sort_values(["League", "Date", "Time", "Event"]).reset_index(drop=True)


@st.cache_data(ttl=1800, show_spinner="Loading recent results...")
def fetch_recent_results(selected_leagues: tuple[str, ...]) -> pd.DataFrame:
    rows = []
    for league_name in selected_leagues:
        league = LEAGUES.get(league_name)
        if not league:
            continue

        payload = tsdb_v1_get("eventspastleague.php", {"id": league["id"]})
        events = normalize_events_payload(payload)

        for item in events:
            rows.append(
                {
                    "League": league_name,
                    "Event": f"{first_nonempty(item.get('strAwayTeam'), 'Away')} @ {first_nonempty(item.get('strHomeTeam'), 'Home')}",
                    "Home Team": first_nonempty(item.get("strHomeTeam")),
                    "Away Team": first_nonempty(item.get("strAwayTeam")),
                    "Date": first_nonempty(item.get("dateEvent")),
                    "Time": first_nonempty(item.get("strTime")),
                    "Display Time": display_event_time(item.get("dateEvent"), item.get("strTime")),
                    "Score": format_score(item.get("intHomeScore"), item.get("intAwayScore")),
                    "Status": event_status_label(item),
                    "Venue": first_nonempty(item.get("strVenue")),
                    "Season": first_nonempty(item.get("strSeason")),
                    "Round": first_nonempty(item.get("intRound")),
                    "Event ID": first_nonempty(item.get("idEvent")),
                    "Thumb": first_nonempty(item.get("strThumb")),
                }
            )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    return df.sort_values(["League", "Date", "Time", "Event"], ascending=[True, False, False, True]).reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner="Loading league teams...")
def fetch_league_teams(selected_leagues: tuple[str, ...]) -> pd.DataFrame:
    rows = []
    for league_name in selected_leagues:
        payload = tsdb_v1_get("search_all_teams.php", {"l": league_name})
        teams = payload.get("teams") if isinstance(payload, dict) else None
        if not isinstance(teams, list):
            continue

        for item in teams:
            rows.append(
                {
                    "League": league_name,
                    "Team": first_nonempty(item.get("strTeam")),
                    "Short Name": first_nonempty(item.get("strTeamShort")),
                    "Stadium": first_nonempty(item.get("strStadium")),
                    "Location": first_nonempty(item.get("strLocation")),
                    "Badge": first_nonempty(item.get("strBadge")),
                    "Banner": first_nonempty(item.get("strBanner")),
                    "Logo": first_nonempty(item.get("strLogo")),
                    "Website": first_nonempty(item.get("strWebsite")),
                    "Description": first_nonempty(item.get("strDescriptionEN")),
                }
            )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    return df.sort_values(["League", "Team"]).reset_index(drop=True)


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
        font-size: 2.7rem;
        font-weight: 900;
        color: #163b68;
        margin-bottom: 0.15rem;
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

    .section-title {
        font-size: 1.2rem;
        font-weight: 800;
        color: #173b67;
        margin-top: 8px;
        margin-bottom: 10px;
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

    .alabama-card {
        background: linear-gradient(135deg, #ffffff 0%, #fff8fa 100%);
        border: 1px solid #eed4dd;
        border-left: 6px solid #9e1b32;
        border-radius: 18px;
        padding: 18px;
        box-shadow: 0 8px 20px rgba(60, 20, 30, 0.08);
        margin-bottom: 16px;
    }

    .mini-note {
        color: #5f7896;
        font-size: 0.88rem;
        font-weight: 600;
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
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------
# SIDEBAR
# -----------------------------
st.sidebar.title("⚙️ Dashboard Controls")

selected_leagues = st.sidebar.multiselect(
    "Leagues",
    options=list(LEAGUES.keys()),
    default=["NBA", "NFL", "MLB", "NHL"],
)

show_live = st.sidebar.toggle("Show live score tab", value=True)
show_upcoming = st.sidebar.toggle("Show upcoming games tab", value=True)
show_recent = st.sidebar.toggle("Show recent results tab", value=True)
show_teams = st.sidebar.toggle("Show teams tab", value=True)

if st.sidebar.button("Refresh now"):
    st.cache_data.clear()
    st.rerun()

if not has_key():
    st.error("Missing THESPORTSDB_API_KEY in Streamlit secrets.")
    st.stop()

# -----------------------------
# HEADER
# -----------------------------
st.markdown('<div class="main-title">🏈 Sports Command Dashboard</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-title">Rebuilt on TheSportsDB for schedules, live scores, results, teams, and branding. Odds can plug in later.</div>',
    unsafe_allow_html=True,
)

# -----------------------------
# LOAD DATA
# -----------------------------
league_tuple = tuple(selected_leagues)

live_df = fetch_live_scores(league_tuple) if show_live else pd.DataFrame()
upcoming_df = fetch_upcoming_events(league_tuple) if show_upcoming else pd.DataFrame()
recent_df = fetch_recent_results(league_tuple) if show_recent else pd.DataFrame()
teams_df = fetch_league_teams(league_tuple) if show_teams else pd.DataFrame()
alabama = fetch_alabama_team()

# -----------------------------
# HERO
# -----------------------------
st.markdown('<div class="hero-box">', unsafe_allow_html=True)
left, right = st.columns([2, 1])

with left:
    st.markdown("### Dashboard Snapshot")
    st.markdown(
        f"""
        This version is built for **sports data reliability** first.
        
        - Live games found: **{len(live_df)}**
        - Upcoming games found: **{len(upcoming_df)}**
        - Recent results loaded: **{len(recent_df)}**
        - Teams loaded: **{len(teams_df)}**
        """
    )

with right:
    refresh_time = datetime.now().astimezone().strftime("%Y-%m-%d %I:%M:%S %p")
    st.markdown("**Last refresh**")
    st.markdown(refresh_time)
    st.markdown("**Data source**")
    st.markdown("TheSportsDB Premium")

st.markdown("</div>", unsafe_allow_html=True)

# -----------------------------
# ALABAMA BRANDING
# -----------------------------
st.markdown('<div class="section-title">Featured Program</div>', unsafe_allow_html=True)
c1, c2 = st.columns([1, 3])

with c1:
    badge = first_nonempty(alabama.get("strBadge"), alabama.get("strLogo"), alabama.get("strTeamBadge"))
    if badge:
        st.image(badge, use_container_width=True)
    else:
        st.info("Alabama logo not returned yet.")

with c2:
    st.markdown('<div class="alabama-card">', unsafe_allow_html=True)
    st.markdown(f"### {first_nonempty(alabama.get('strTeam'), BOOKMARKED_TEAM_NAME)}")
    st.markdown(
        f"""
        **League:** {first_nonempty(alabama.get('strLeague'), 'NCAA')}  
        **Stadium:** {first_nonempty(alabama.get('strStadium'), '—')}  
        **Location:** {first_nonempty(alabama.get('strLocation'), '—')}
        """
    )
    description = first_nonempty(alabama.get("strDescriptionEN"))
    if description:
        st.markdown(description[:500] + ("..." if len(description) > 500 else ""))
    else:
        st.markdown("Alabama branding card is active and ready.")
    st.markdown('</div>', unsafe_allow_html=True)

# -----------------------------
# KPIS
# -----------------------------
def kpi_card(label, value):
    st.markdown(
        f'<div class="kpi-card"><div class="kpi-label">{label}</div><div class="kpi-value">{value}</div></div>',
        unsafe_allow_html=True,
    )

k1, k2, k3, k4 = st.columns(4)
with k1:
    kpi_card("Live Games", len(live_df))
with k2:
    kpi_card("Upcoming Games", len(upcoming_df))
with k3:
    kpi_card("Recent Results", len(recent_df))
with k4:
    kpi_card("Teams Loaded", len(teams_df))

# -----------------------------
# TABS
# -----------------------------
tab_names = ["Home"]
if show_live:
    tab_names.append("Live Scores")
if show_upcoming:
    tab_names.append("Upcoming")
if show_recent:
    tab_names.append("Recent Results")
if show_teams:
    tab_names.append("Teams")
tab_names.append("Odds Module")

tabs = st.tabs(tab_names)

tab_lookup = {name: tab for name, tab in zip(tab_names, tabs)}

with tab_lookup["Home"]:
    st.markdown('<div class="section-title">Overview</div>', unsafe_allow_html=True)

    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("**Upcoming by league**")
        if upcoming_df.empty:
            st.info("No upcoming games loaded.")
        else:
            st.bar_chart(upcoming_df["League"].value_counts())
        st.markdown("</div>", unsafe_allow_html=True)

    with col_b:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown("**Recent results by league**")
        if recent_df.empty:
            st.info("No recent results loaded.")
        else:
            st.bar_chart(recent_df["League"].value_counts())
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("**What this version does well right now**")
    st.markdown(
        """
        - stable sports-data shell
        - live score support
        - upcoming schedule cards
        - recent results board
        - team/logo data
        - Alabama Crimson Tide branding
        
        The next clean step is plugging a dedicated odds API into the Odds Module tab.
        """
    )
    st.markdown("</div>", unsafe_allow_html=True)

if "Live Scores" in tab_lookup:
    with tab_lookup["Live Scores"]:
        st.markdown('<div class="section-title">Live Scores</div>', unsafe_allow_html=True)
        if live_df.empty:
            st.info("No live games returned right now.")
        else:
            st.dataframe(
                live_df[
                    [
                        "League",
                        "Event",
                        "Score",
                        "Status",
                        "Venue",
                        "Date",
                        "Time",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )

if "Upcoming" in tab_lookup:
    with tab_lookup["Upcoming"]:
        st.markdown('<div class="section-title">Upcoming Games</div>', unsafe_allow_html=True)
        if upcoming_df.empty:
            st.info("No upcoming games returned right now.")
        else:
            st.dataframe(
                upcoming_df[
                    [
                        "League",
                        "Event",
                        "Display Time",
                        "Venue",
                        "Season",
                        "Round",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )

if "Recent Results" in tab_lookup:
    with tab_lookup["Recent Results"]:
        st.markdown('<div class="section-title">Recent Results</div>', unsafe_allow_html=True)
        if recent_df.empty:
            st.info("No recent results returned right now.")
        else:
            st.dataframe(
                recent_df[
                    [
                        "League",
                        "Event",
                        "Score",
                        "Status",
                        "Display Time",
                        "Venue",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )

if "Teams" in tab_lookup:
    with tab_lookup["Teams"]:
        st.markdown('<div class="section-title">Teams</div>', unsafe_allow_html=True)
        if teams_df.empty:
            st.info("No team data returned right now.")
        else:
            team_choice = st.selectbox(
                "Choose a team",
                options=teams_df["Team"].dropna().tolist(),
                index=0,
            )
            team_row = teams_df[teams_df["Team"] == team_choice].iloc[0]

            c_left, c_right = st.columns([1, 2])
            with c_left:
                badge = first_nonempty(team_row.get("Badge"), team_row.get("Logo"), team_row.get("Banner"))
                if badge:
                    st.image(badge, use_container_width=True)

            with c_right:
                st.markdown(f"### {team_row['Team']}")
                st.markdown(
                    f"""
                    **League:** {team_row['League']}  
                    **Stadium:** {team_row['Stadium'] or '—'}  
                    **Location:** {team_row['Location'] or '—'}
                    """
                )
                desc = str(team_row.get("Description") or "")
                if desc:
                    st.markdown(desc[:900] + ("..." if len(desc) > 900 else ""))

            st.markdown('<div class="section-title">All teams loaded</div>', unsafe_allow_html=True)
            st.dataframe(
                teams_df[["League", "Team", "Stadium", "Location"]],
                use_container_width=True,
                hide_index=True,
            )

with tab_lookup["Odds Module"]:
    st.markdown('<div class="section-title">Odds Module</div>', unsafe_allow_html=True)
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown(
        """
        **Current status:** no dedicated odds provider connected in this rebuild.
        
        This dashboard is now stable on TheSportsDB for:
        - events
        - live scores
        - schedules
        - team branding
        
        The next step is to connect a real odds API here.
        """
    )
    st.markdown("</div>", unsafe_allow_html=True)
