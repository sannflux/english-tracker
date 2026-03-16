import streamlit as st
import pandas as pd
from github import Github
from datetime import datetime, timedelta
import io
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import google.generativeai as genai
import json
import os
import base64
import time
import hashlib

# ═══════════════════════════════════════════════════════════════
# ⚡ PERF INSTRUMENTATION
# ═══════════════════════════════════════════════════════════════
_APP_T0 = time.perf_counter()

def perf_log(label: str, t0: float) -> float:
    """Logs elapsed ms to sidebar when debug mode is ON."""
    elapsed_ms = (time.perf_counter() - t0) * 1000
    if st.session_state.get("debug_perf", False):
        st.sidebar.caption(f"⏱ {label}: {elapsed_ms:.1f}ms")
    return elapsed_ms

# ═══════════════════════════════════════════════════════════════
# CONFIG & CONSTANTS
# ═══════════════════════════════════════════════════════════════
st.set_page_config(page_title="English Pro Elite", layout="wide", page_icon="🇬🇧")

CRED_FILE       = "credentials.json"
AI_MIN_INTERVAL = 12        # seconds — 5 RPM = 1 call per 12 s
AI_DAILY_CAP    = 18        # hard ceiling — 2-call buffer below 20 RPD
SCHEMA_VERSION  = "v1"      # bump to force cache invalidation

# ── D7: Skill emoji map ──────────────────────────────────────
SKILL_EMOJI = {
    "Listening":  "🎧",
    "Speaking":   "🗣️",
    "Reading":    "📖",
    "Writing":    "✍️",
    "Grammar":    "📝",
    "Vocabulary": "💬",
}

def add_emoji(skill: str) -> str:
    """Prefix a skill name with its emoji. Falls back to 📚."""
    return f"{SKILL_EMOJI.get(skill, '📚')} {skill}"

# ── Achievements ─────────────────────────────────────────────
ACHIEVEMENTS = [
    {"id": "first_hour",    "emoji": "⭐", "title": "First Hour",     "desc": "Log your first hour of study",            "check": lambda h, s, sk: h >= 1},
    {"id": "ten_hours",     "emoji": "🔟", "title": "Ten Hours",      "desc": "Accumulate 10 total hours",                "check": lambda h, s, sk: h >= 10},
    {"id": "fifty_hours",   "emoji": "🥈", "title": "Half Century",   "desc": "Reach 50 total hours",                     "check": lambda h, s, sk: h >= 50},
    {"id": "hundred_hours", "emoji": "💯", "title": "Century Club",   "desc": "Reach 100 total hours",                    "check": lambda h, s, sk: h >= 100},
    {"id": "streak_3",      "emoji": "🔥", "title": "On Fire",        "desc": "Maintain a 3-day streak",                  "check": lambda h, s, sk: s >= 3},
    {"id": "streak_7",      "emoji": "🗓️", "title": "Week Warrior",   "desc": "Maintain a 7-day streak",                  "check": lambda h, s, sk: s >= 7},
    {"id": "streak_30",     "emoji": "🏆", "title": "Monthly Master", "desc": "Maintain a 30-day streak",                 "check": lambda h, s, sk: s >= 30},
    {"id": "polymath",      "emoji": "🎓", "title": "Polymath",       "desc": "Study 4+ different skills",                "check": lambda h, s, sk: sk >= 4},
    {"id": "level_5",       "emoji": "🚀", "title": "Level 5",        "desc": "Reach Level 5 (200 h total)",              "check": lambda h, s, sk: h >= 200},
    {"id": "dedicated",     "emoji": "🦉", "title": "Dedicated",      "desc": "Study 500+ total minutes in any skill",    "check": lambda h, s, sk: h >= 8.34},
]

# ═══════════════════════════════════════════════════════════════
# CREDENTIALS
# ═══════════════════════════════════════════════════════════════
@st.cache_resource(show_spinner=False)
def load_credentials():
    try:
        if "GITHUB_TOKEN" in st.secrets:
            return {
                "saved_token": st.secrets["GITHUB_TOKEN"],
                "saved_repo":  st.secrets["GITHUB_REPO"],
                "gemini_key":  st.secrets["GEMINI_API_KEY"],
            }, True
    except Exception:
        pass
    if os.path.exists(CRED_FILE):
        try:
            with open(CRED_FILE, "r") as f:
                return json.load(f), False
        except Exception:
            pass
    return {}, False

local_creds, using_secrets = load_credentials()

# ═══════════════════════════════════════════════════════════════
# BACKGROUND  (E4 dark/light preserved)
# ═══════════════════════════════════════════════════════════════
@st.cache_resource(show_spinner=False)
def _load_bg_base64(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def set_background(png_file: str, light_mode: bool = False):
    bg = _load_bg_base64(png_file)

    sidebar_bg   = "rgba(245,245,250,0.88)" if light_mode else "rgba(0,0,0,0.70)"
    tab_bg       = "rgba(255,255,255,0.72)" if light_mode else "rgba(20,20,20,0.60)"
    text_color   = "#0d0d0d"               if light_mode else "white"
    alert_bg     = "rgba(255,255,255,0.5)" if light_mode else "rgba(0,0,0,0.40)"
    alert_border = "rgba(0,0,0,0.15)"      if light_mode else "rgba(255,255,255,0.20)"

    if bg:
        bg_css = f"""
        .stApp {{
            background-image: url("data:image/png;base64,{bg}");
            background-size: cover;
            background-attachment: fixed;
        }}"""
    else:
        fallback = "#f0f2f6" if light_mode else "#0d1117"
        bg_css   = f".stApp {{ background-color: {fallback}; }}"

    st.markdown(f"""
    <style>
    {bg_css}
    [data-testid="stSidebar"] {{
        background-color: {sidebar_bg} !important;
        backdrop-filter: blur(10px);
    }}
    .stTabs [data-baseweb="tab-panel"] {{
        background-color: {tab_bg} !important;
        padding: 20px;
        border-radius: 15px;
        backdrop-filter: blur(5px);
        border: 1px solid rgba(255,255,255,0.1);
    }}
    [data-testid="stMetricValue"] {{ color: {text_color} !important; }}
    h1, h2, h3, h4, p, span, .stMarkdown div p {{ color: {text_color} !important; }}
    .stAlert {{
        background-color: {alert_bg} !important;
        color: {text_color} !important;
        border: 1px solid {alert_border} !important;
    }}
    /* Badge cards */
    .badge-card {{
        background: rgba(255,255,255,0.10);
        border-radius: 12px;
        padding: 12px 8px;
        text-align: center;
        border: 1px solid rgba(255,255,255,0.18);
        margin-bottom: 8px;
        transition: transform 0.15s ease;
    }}
    .badge-card:hover {{ transform: translateY(-2px); }}
    .badge-locked {{ opacity: 0.32; filter: grayscale(100%); }}
    /* Onboarding */
    .onboarding-card {{
        background: rgba(0,0,0,0.48);
        border-radius: 16px;
        padding: 28px 24px;
        border: 1px solid rgba(255,255,255,0.14);
        margin: 16px 0;
    }}
    .onboarding-step {{ margin-bottom: 14px; font-size: 1.02rem; }}
    /* D2: Animated XP bar */
    @keyframes xp-fill {{
        from {{ width: 0%; }}
        to   {{ width: var(--xp-target); }}
    }}
    .xp-bar-outer {{
        background: rgba(255,255,255,0.12);
        border-radius: 999px;
        height: 18px;
        overflow: hidden;
        margin: 6px 0 2px 0;
        border: 1px solid rgba(255,255,255,0.18);
    }}
    .xp-bar-inner {{
        height: 100%;
        border-radius: 999px;
        animation: xp-fill 1.1s cubic-bezier(.4,0,.2,1) forwards;
    }}
    /* C7: Structured AI response cards */
    .ai-card {{
        background: rgba(255,255,255,0.07);
        border-radius: 10px;
        padding: 10px 14px;
        margin: 6px 0;
        border-left: 3px solid var(--accent-col, #00CC96);
    }}
    /* A1: Cooldown bar label */
    .cooldown-label {{
        font-size: 0.82rem;
        opacity: 0.85;
        margin-bottom: 2px;
    }}
    </style>
    """, unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
# SESSION STATE DEFAULTS
# ═══════════════════════════════════════════════════════════════
_DEFAULTS = {
    # Core data
    "df":                    None,
    "file_sha":              None,
    "prev_level":            0,
    # UI toggles
    "zen_mode":              False,
    "theme_selector":        "Emerald City",
    "weekly_goal":           5,
    "daily_goal_mins":       60,
    "ask_ai_auto":           False,
    "light_mode":            False,
    # Credentials
    "saved_token":           local_creds.get("saved_token", ""),
    "saved_repo":            local_creds.get("saved_repo", ""),
    "gemini_key":            local_creds.get("gemini_key", ""),
    # Gamification
    "milestone_reward":      "Treat myself to coffee",
    "milestone_claimed_date": "",
    # AI state
    "last_ai_rec":           "",
    "last_ai_response":      {},          # C7: structured dict
    "last_ai_time":          None,
    "ai_calls_today":        0,
    "ai_call_date":          "",
    "ai_history":            [],
    "last_diet_hash":        "",
    "last_diet_snapshot":    {},          # A9: eco-mode snapshot
    "ai_target_skill":       "All Skills",
    "last_monthly_review":   "",          # C10
    # Derived cache
    "cached_all_skills":     None,
    "cached_diet":           None,
    "cached_this_week":      None,
    # Perf
    "debug_perf":            False,
    "accent_color":          "#00CC96",
    # Custom skills
    "custom_skills":         [],
    # ── NEW FEATURES ──────────────────────────────────────
    "eco_mode":              False,       # A9
    "ai_daily_cap_setting":  AI_DAILY_CAP,  # A7
    "mobile_mode":           False,       # D1
    "prev_achievements":     [],          # D3: list of unlocked IDs
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

set_background("background.jpg", light_mode=st.session_state.light_mode)

# ═══════════════════════════════════════════════════════════════
# GITHUB — CLIENT, LOAD, SAVE
# ═══════════════════════════════════════════════════════════════
@st.cache_resource(show_spinner=False)
def get_gh_client(token):
    return Github(token)

def _invalidate_derived_cache():
    """Call whenever df changes so derived values are recomputed."""
    st.session_state.cached_all_skills = None
    st.session_state.cached_diet       = None
    st.session_state.cached_this_week  = None

@st.cache_data(ttl=300, show_spinner="Fetching data...")
def load_data_from_github(_token, repo_name, file_path, _schema_ver=SCHEMA_VERSION):
    t0 = time.perf_counter()
    try:
        g    = get_gh_client(_token)
        repo = g.get_repo(repo_name)
        cont = repo.get_contents(file_path)
        df   = pd.read_csv(io.StringIO(cont.decoded_content.decode("utf-8")))
        df.columns = df.columns.str.strip()
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
            df["Date"] = df["Date"].ffill().bfill()
        df["Time Spent"] = pd.to_numeric(df["Time Spent"], errors="coerce").fillna(0)
        if "Notes" not in df.columns: df["Notes"] = ""
        if "Skill" not in df.columns: df["Skill"] = "General"
        df = df.sort_values("Date", ascending=False).reset_index(drop=True)
        perf_log("load_data_from_github", t0)
        return df, cont.sha, "success"
    except Exception as e:
        return None, None, str(e)

@st.cache_data(ttl=300, show_spinner=False)
def load_config_from_github(_token, repo_name, file_path="config.json"):
    try:
        g    = get_gh_client(_token)
        repo = g.get_repo(repo_name)
        cont = repo.get_contents(file_path)
        return json.loads(cont.decoded_content.decode("utf-8"))
    except Exception:
        return {}

def save_config_to_github(token, repo_name, config_dict, file_path="config.json"):
    try:
        g           = get_gh_client(token)
        repo        = g.get_repo(repo_name)
        content_str = json.dumps(config_dict, indent=4)
        try:
            cont = repo.get_contents(file_path)
            repo.update_file(file_path, "Update Settings", content_str, cont.sha)
        except Exception:
            repo.create_file(file_path, "Init Settings", content_str)
    except Exception as e:
        st.sidebar.error(f"Config Save Error: {e}")

def sync_config_to_github():
    """Push all user-configurable settings to config.json on GitHub."""
    if st.session_state.saved_token and st.session_state.saved_repo:
        save_config_to_github(
            st.session_state.saved_token,
            st.session_state.saved_repo,
            {
                "weekly_goal":          st.session_state.weekly_goal,
                "daily_goal_mins":      st.session_state.daily_goal_mins,
                "theme":                st.session_state.theme_selector,
                "ask_ai_auto":          st.session_state.ask_ai_auto,
                "light_mode":           st.session_state.light_mode,
                "milestone_reward":     st.session_state.milestone_reward,
                "custom_skills":        st.session_state.custom_skills,
                # New persisted settings
                "eco_mode":             st.session_state.eco_mode,
                "ai_daily_cap_setting": st.session_state.ai_daily_cap_setting,
                "mobile_mode":          st.session_state.mobile_mode,
            },
        )

def save_to_github(token, repo_name, file_path, df):
    t0 = time.perf_counter()
    try:
        if pd.api.types.is_datetime64_any_dtype(df["Date"]):
            df_save = df.assign(Date=df["Date"].dt.strftime("%Y-%m-%d"))
        else:
            df_save = df

        csv_buffer = io.StringIO()
        df_save.to_csv(csv_buffer, index=False)
        g    = get_gh_client(token)
        repo = g.get_repo(repo_name)
        sha  = st.session_state.get("file_sha") or repo.get_contents(file_path).sha
        res  = repo.update_file(
            path    = file_path,
            message = "Sync Elite Tracker",
            content = csv_buffer.getvalue(),
            sha     = sha,
        )
        perf_log("save_to_github", t0)
        return res["content"].sha
    except Exception as e:
        st.error(f"GitHub Sync Error: {e}")
        return None

# ═══════════════════════════════════════════════════════════════
# EDITOR CHANGE HANDLER
# ═══════════════════════════════════════════════════════════════
def handle_editor_change():
    if "editor_key" not in st.session_state:
        return
    changes = st.session_state["editor_key"]
    if not (changes["edited_rows"] or changes["added_rows"] or changes["deleted_rows"]):
        return

    working_df = st.session_state.df.copy()

    for idx_str, col_changes in changes["edited_rows"].items():
        idx = int(idx_str)
        for col, val in col_changes.items():
            working_df.at[idx, col] = val

    if changes["added_rows"]:
        new_rows   = pd.DataFrame(changes["added_rows"])
        working_df = pd.concat([working_df, new_rows], ignore_index=True)

    if changes["deleted_rows"]:
        working_df = working_df.drop(index=changes["deleted_rows"]).reset_index(drop=True)

    if "Date" in working_df.columns:
        working_df["Date"] = pd.to_datetime(working_df["Date"], errors="coerce")
    if "Time Spent" in working_df.columns:
        working_df["Time Spent"] = pd.to_numeric(
            working_df["Time Spent"], errors="coerce"
        ).fillna(0)

    st.session_state.df = working_df
    _invalidate_derived_cache()

    sha = save_to_github(
        st.session_state.saved_token,
        st.session_state.saved_repo,
        "data.csv",
        working_df,
    )
    if sha:
        st.session_state.file_sha = sha

# ═══════════════════════════════════════════════════════════════
# GHOST AUTO-LOAD
# ═══════════════════════════════════════════════════════════════
if (
    st.session_state.df is None
    and st.session_state.saved_token
    and st.session_state.saved_repo
):
    _df, _sha, _status = load_data_from_github(
        st.session_state.saved_token,
        st.session_state.saved_repo,
        "data.csv",
    )
    _remote_cfg = load_config_from_github(
        st.session_state.saved_token,
        st.session_state.saved_repo,
    )
    if _status == "success":
        st.session_state.df       = _df
        st.session_state.file_sha = _sha
        _cfg_map = {
            "weekly_goal":          "weekly_goal",
            "daily_goal_mins":      "daily_goal_mins",
            "theme":                "theme_selector",
            "ask_ai_auto":          "ask_ai_auto",
            "light_mode":           "light_mode",
            "milestone_reward":     "milestone_reward",
            "custom_skills":        "custom_skills",
            "eco_mode":             "eco_mode",
            "ai_daily_cap_setting": "ai_daily_cap_setting",
            "mobile_mode":          "mobile_mode",
        }
        for cfg_key, ss_key in _cfg_map.items():
            if cfg_key in _remote_cfg:
                st.session_state[ss_key] = _remote_cfg[cfg_key]

# ═══════════════════════════════════════════════════════════════
# STREAK (vectorized)
# ═══════════════════════════════════════════════════════════════
def _compute_streak_vectorized(date_series: pd.Series) -> int:
    dates = date_series.dt.date.dropna().unique()
    if len(dates) == 0:
        return 0
    today        = datetime.now().date()
    dates_sorted = sorted(dates, reverse=True)
    if dates_sorted[0] not in (today, today - timedelta(days=1)):
        return 0
    ordinals = np.array([d.toordinal() for d in dates_sorted])
    diffs    = np.diff(ordinals)
    breaks   = np.where(diffs != -1)[0]
    return int(breaks[0]) + 1 if len(breaks) > 0 else len(dates_sorted)

# ═══════════════════════════════════════════════════════════════
# DASHBOARD STATS (cached)
# ═══════════════════════════════════════════════════════════════
@st.cache_data(show_spinner=False)
def get_dashboard_stats(df: pd.DataFrame):
    t0 = time.perf_counter()
    if df is None or df.empty:
        return 0.0, 1, 0.0, 0
    total_hrs = df["Time Spent"].sum() / 60
    level     = int(total_hrs // 50) + 1
    xp        = (total_hrs % 50) / 50
    streak    = _compute_streak_vectorized(df["Date"])
    perf_log("get_dashboard_stats", t0)
    return total_hrs, level, xp, streak

# ═══════════════════════════════════════════════════════════════
# DERIVED STATE CACHE
# ═══════════════════════════════════════════════════════════════
def get_or_compute_derived(df: pd.DataFrame):
    if st.session_state.cached_all_skills is not None:
        return (
            st.session_state.cached_all_skills,
            st.session_state.cached_diet,
            st.session_state.cached_this_week,
        )
    t0 = time.perf_counter()

    base_skills = ["Listening", "Speaking", "Reading", "Writing", "Grammar", "Vocabulary"]
    extra       = pd.unique(df["Skill"].dropna().values).tolist()
    custom      = st.session_state.get("custom_skills", [])
    all_skills  = list(dict.fromkeys(base_skills + extra + custom))

    diet = df.groupby("Skill")["Time Spent"].sum()

    week_start = pd.Timestamp(datetime.now() - timedelta(days=datetime.now().weekday()))
    this_week  = df.loc[df["Date"] >= week_start, "Time Spent"].sum() / 60

    st.session_state.cached_all_skills = all_skills
    st.session_state.cached_diet       = diet
    st.session_state.cached_this_week  = this_week
    perf_log("get_or_compute_derived", t0)
    return all_skills, diet, this_week

# ═══════════════════════════════════════════════════════════════
# PLOTLY CHARTS (cached)
# D7 emojis applied inside each chart builder
# ═══════════════════════════════════════════════════════════════
@st.cache_data(show_spinner=False)
def build_area_chart(df: pd.DataFrame, accent_color: str, title: str):
    daily = (
        df.sort_values("Date")
        .groupby("Date")["Time Spent"]
        .sum()
        .reset_index()
    )
    daily["7d avg"]  = daily["Time Spent"].rolling(7,  min_periods=1).mean()
    daily["30d avg"] = daily["Time Spent"].rolling(30, min_periods=1).mean()

    fig = px.area(daily, x="Date", y="Time Spent", title=title,
                  color_discrete_sequence=[accent_color])
    fig.add_scatter(x=daily["Date"], y=daily["7d avg"],  mode="lines", name="7d avg",
                    line=dict(color="orange", width=1.5, dash="dot"))
    fig.add_scatter(x=daily["Date"], y=daily["30d avg"], mode="lines", name="30d avg",
                    line=dict(color="cyan",   width=1.5, dash="dash"))
    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font_color="white", legend=dict(orientation="h", y=-0.22),
    )
    return fig

@st.cache_data(show_spinner=False)
def build_pie_chart(skill_names: tuple, skill_values: tuple):
    # D7: show emojis in pie labels
    emoji_names = tuple(add_emoji(s) for s in skill_names)
    fig = px.pie(names=emoji_names, values=skill_values, hole=0.5, title="Skill Diet")
    fig.update_layout(
        showlegend=False, plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)", font_color="white",
    )
    return fig

@st.cache_data(show_spinner=False)
def build_heatmap(df: pd.DataFrame, accent_color: str):
    cutoff = pd.Timestamp(datetime.now() - timedelta(days=90))
    daily  = (
        df[df["Date"] >= cutoff]
        .groupby(df["Date"].dt.date)["Time Spent"]
        .sum()
        .reset_index()
    )
    daily.columns = ["Date", "Minutes"]
    daily["Date"] = pd.to_datetime(daily["Date"])
    daily["Week"] = daily["Date"].dt.isocalendar().week.astype(str)
    daily["DOW"]  = daily["Date"].dt.day_name()

    dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    fig = px.density_heatmap(
        daily, x="Week", y="DOW", z="Minutes",
        category_orders={"DOW": dow_order},
        color_continuous_scale=["#111111", accent_color],
        title="90-Day Study Heatmap",
    )
    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font_color="white", coloraxis_showscale=False,
        yaxis=dict(categoryorder="array", categoryarray=dow_order),
    )
    return fig

@st.cache_data(show_spinner=False)
def build_skill_bars(diet: pd.Series, accent_color: str):
    df_bar = diet.reset_index()
    df_bar.columns = ["Skill", "Minutes"]
    df_bar["Skill"] = df_bar["Skill"].apply(add_emoji)   # D7
    df_bar = df_bar.sort_values("Minutes", ascending=True)
    fig = px.bar(
        df_bar, x="Minutes", y="Skill", orientation="h",
        title="Minutes Per Skill", color="Minutes",
        color_continuous_scale=["#222222", accent_color],
    )
    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font_color="white", coloraxis_showscale=False, showlegend=False,
    )
    return fig

@st.cache_data(show_spinner=False)
def build_daily_ring(today_mins: float, goal_mins: int, accent_color: str):
    ceiling = max(float(goal_mins), today_mins, 1.0)
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=today_mins,
        number={"suffix": " min", "font": {"color": "white", "size": 22}},
        title={"text": f"Today vs {goal_mins} min goal", "font": {"color": "white", "size": 13}},
        gauge={
            "axis":        {"range": [0, ceiling], "tickcolor": "white"},
            "bar":         {"color": accent_color},
            "bgcolor":     "rgba(0,0,0,0)",
            "bordercolor": "rgba(255,255,255,0.2)",
            "threshold":   {"line": {"color": "white", "width": 2}, "value": goal_mins},
        },
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", font_color="white",
        height=220, margin=dict(t=40, b=10, l=20, r=20),
    )
    return fig

# ═══════════════════════════════════════════════════════════════
# AI HELPERS
# ═══════════════════════════════════════════════════════════════
def _diet_hash(diet_dict: dict) -> str:
    return hashlib.md5(json.dumps(diet_dict, sort_keys=True).encode()).hexdigest()

def _check_ai_rate_limit() -> tuple:
    """Returns (allowed: bool, reason: str, wait_secs: float).
    A7: uses session-state cap instead of hard constant."""
    now       = datetime.now()
    today_str = now.date().isoformat()
    cap       = int(st.session_state.get("ai_daily_cap_setting", AI_DAILY_CAP))

    if st.session_state.ai_call_date != today_str:
        st.session_state.ai_call_date   = today_str
        st.session_state.ai_calls_today = 0

    if st.session_state.ai_calls_today >= cap:
        # A4: exact reset countdown
        midnight  = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
        secs_left = int((midnight - now).total_seconds())
        hrs       = secs_left // 3600
        mins      = (secs_left % 3600) // 60
        return False, f"Daily limit reached ({cap}/day). Resets in {hrs}h {mins}m.", 0.0

    last = st.session_state.last_ai_time
    if last and (now - last).total_seconds() < AI_MIN_INTERVAL:
        wait = AI_MIN_INTERVAL - (now - last).total_seconds()
        return False, f"Cooling down — ready in {wait:.0f}s.", float(wait)

    return True, "", 0.0

# A9: Eco-mode change detection
def _eco_changed(diet_dict: dict, threshold_pct: float = 5.0) -> bool:
    """True when skill totals have shifted enough to warrant a new AI call."""
    old = st.session_state.get("last_diet_snapshot", {})
    if not old:
        return True
    total = sum(diet_dict.values()) or 1
    delta = sum(
        abs(diet_dict.get(k, 0) - old.get(k, 0))
        for k in set(diet_dict) | set(old)
    )
    return (delta / total * 100) >= threshold_pct

# C7: Robust JSON parser — handles markdown code fences from AI
def _parse_ai_json(text: str) -> dict:
    for candidate in [
        text.strip(),
        text.strip().lstrip("```json").lstrip("```").rstrip("```").strip(),
    ]:
        try:
            result = json.loads(candidate)
            if isinstance(result, dict):
                return result
        except Exception:
            pass
    return {"tip": text.strip(), "exercise": "", "resource": ""}

# ═══════════════════════════════════════════════════════════════
# AI COACH  ── MODEL STASIS LOCKED: gemini-2.5-flash-lite ──
# C1 Weakness-first  C2 Streak-aware  C3 Level-aware
# C4 Last-tip context  C5 Goal-aligned
# C7 JSON structured response  C10 Monthly review
# ═══════════════════════════════════════════════════════════════
def get_ai_recommendation(
    api_key:        str,
    skill_totals:   dict,
    target_skill:   str   = "All Skills",
    streak:         int   = 0,
    level:          int   = 1,
    last_tip:       str   = "",
    weekly_goal:    float = 5.0,
    this_week:      float = 0.0,
    monthly_review: bool  = False,
) -> dict:
    if not api_key:
        return {"tip": "Please provide a Gemini API key.", "exercise": "", "resource": ""}
    try:
        genai.configure(api_key=api_key)
        model   = genai.GenerativeModel("gemini-2.5-flash-lite")  # ← MODEL STASIS LOCKED
        compact = json.dumps(skill_totals, separators=(",", ":"))

        # C1: identify weakest skill
        weakest = min(skill_totals, key=skill_totals.get) if skill_totals else "General"

        # Build enriched context (C2 / C3 / C4 / C5)
        ctx_parts = [f"Skills(mins):{compact}"]
        if level > 1:    ctx_parts.append(f"Level:{level}")            # C3
        if streak > 0:   ctx_parts.append(f"Streak:{streak}d")         # C2
        if this_week > 0:
            ctx_parts.append(f"ThisWeek:{this_week:.1f}/{weekly_goal}h")  # C5
        if last_tip:
            ctx_parts.append(f"PreviousTip(doNotRepeat):{last_tip[:80]}")  # C4
        ctx = ". ".join(ctx_parts)

        json_fmt = 'Reply ONLY with valid JSON (no markdown): {"tip":"...","exercise":"...","resource":"..."}'

        if monthly_review:                                             # C10
            prompt = (
                f"English coach. {ctx}. "
                f"Write a comprehensive monthly review: celebrate strengths, focus on "
                f"weakest skill ({weakest}), set 3 concrete goals for next month. "
                f"≤150 words. {json_fmt}"
            )
        elif target_skill != "All Skills":
            prompt = (
                f"English coach. {ctx}. Weakest overall: {weakest}. "
                f"Focus ONLY on '{target_skill}'. ONE actionable tip. ≤60 words. {json_fmt}"
            )
        else:
            # C1: weakest skill always drives the advice
            prompt = (
                f"English coach. {ctx}. "
                f"Target the weakest skill: {weakest}. ONE actionable tip. ≤60 words. {json_fmt}"
            )

        result_text = model.generate_content(prompt).text
        st.session_state.last_ai_time    = datetime.now()
        st.session_state.ai_calls_today += 1
        return _parse_ai_json(result_text)
    except Exception as e:
        return {"tip": f"AI Error: {str(e)}", "exercise": "", "resource": ""}

# ═══════════════════════════════════════════════════════════════
# ACHIEVEMENTS
# ═══════════════════════════════════════════════════════════════
def evaluate_achievements(total_hrs: float, streak: int, unique_skills: int) -> set:
    unlocked = set()
    for ach in ACHIEVEMENTS:
        try:
            if ach["check"](total_hrs, streak, unique_skills):
                unlocked.add(ach["id"])
        except Exception:
            pass
    return unlocked

# ═══════════════════════════════════════════════════════════════
# LOG DIALOG
# BUG FIX: st.rerun() always fires; cache cleared on success.
# D7: format_func shows emoji without saving it into the data.
# ═══════════════════════════════════════════════════════════════
@st.dialog("➕ Log New Study Session")
def log_session_dialog(available_skills):
    with st.form("new_entry", clear_on_submit=True):
        d = st.date_input("Date", datetime.now())
        # D7: emoji displayed in dropdown but plain name saved to CSV
        s = st.selectbox("Skill", available_skills, format_func=add_emoji)
        t = st.number_input("Minutes", min_value=1, max_value=600, value=30)
        n = st.text_input("Notes")

        if st.form_submit_button("💾 Log & Sync", use_container_width=True):
            new_row = pd.DataFrame({
                "Date":       [pd.to_datetime(d)],
                "Skill":      [s],           # ← plain name, no emoji
                "Time Spent": [t],
                "Notes":      [n],
            })
            # Append to in-memory dataframe first
            st.session_state.df = pd.concat(
                [st.session_state.df, new_row], ignore_index=True
            )
            _invalidate_derived_cache()

            # Push to GitHub
            sha = save_to_github(
                st.session_state.saved_token,
                st.session_state.saved_repo,
                "data.csv",
                st.session_state.df,
            )
            if sha:
                st.session_state.file_sha = sha
                load_data_from_github.clear()   # ← BUG FIX: bust stale cache
                st.toast(f"✅ {t} min of {add_emoji(s)} logged!", icon="📚")
            else:
                st.toast(
                    "⚠️ Saved to memory but GitHub sync failed. "
                    "Your data is safe — try Refresh.",
                    icon="⚠️",
                )
            # BUG FIX: rerun unconditionally so the UI always updates
            st.rerun()

# ═══════════════════════════════════════════════════════════════
# SIDEBAR
# A2: Fuel gauge  A4: Reset countdown
# ═══════════════════════════════════════════════════════════════
with st.sidebar:
    st.header("🔑 Connection")
    st.text_input("GitHub Token",   type="password", key="saved_token",  disabled=using_secrets)
    st.text_input("Repo",                            key="saved_repo",   disabled=using_secrets)
    st.text_input("Gemini API Key", type="password", key="gemini_key",   disabled=using_secrets)

    if st.button("🔄 Refresh Application", use_container_width=True):
        load_data_from_github.clear()
        load_config_from_github.clear()
        _invalidate_derived_cache()
        st.rerun()

    st.divider()

    theme_map = {
        "Emerald City":  "#00CC96",
        "Ocean Deep":    "#0099FF",
        "Sunset Orange": "#FF5733",
        "Royal Purple":  "#8E44AD",
    }
    st.selectbox("Theme", list(theme_map.keys()), key="theme_selector",
                 on_change=sync_config_to_github)
    st.session_state.accent_color = theme_map[st.session_state.theme_selector]

    st.toggle("☀️ Light Mode",      key="light_mode",   on_change=sync_config_to_github)
    st.slider("Weekly Goal (Hours)", 1, 40, key="weekly_goal", on_change=sync_config_to_github)
    st.slider("Daily Goal (Minutes)", 10, 300, key="daily_goal_mins", on_change=sync_config_to_github)
    st.checkbox("🧘 Zen Mode",       key="zen_mode")
    st.checkbox("🔄 Auto AI Coach",  key="ask_ai_auto",  on_change=sync_config_to_github)

    st.divider()

    # ── A2: Fuel Gauge ──────────────────────────────────────
    _today_str    = datetime.now().date().isoformat()
    _cap          = int(st.session_state.get("ai_daily_cap_setting", AI_DAILY_CAP))
    display_calls = (
        st.session_state.ai_calls_today
        if st.session_state.ai_call_date == _today_str
        else 0
    )
    _ratio = display_calls / _cap if _cap > 0 else 0

    if _ratio < 0.5:
        _gauge_color, _gauge_icon = "#00CC96", "🟢"
    elif _ratio < 0.85:
        _gauge_color, _gauge_icon = "#FFA500", "🟡"
    else:
        _gauge_color, _gauge_icon = "#FF4B4B", "🔴"

    st.markdown(f"**{_gauge_icon} AI Budget: {display_calls} / {_cap}**")
    st.markdown(f"""
    <div style="background:rgba(255,255,255,0.12);border-radius:999px;
                height:10px;overflow:hidden;margin-bottom:4px">
      <div style="width:{min(_ratio*100,100):.0f}%;height:100%;
                  background:{_gauge_color};border-radius:999px;
                  transition:width 0.4s ease"></div>
    </div>""", unsafe_allow_html=True)

    # ── A4: Reset countdown ──────────────────────────────────
    _now_sb      = datetime.now()
    _midnight_sb = datetime.combine(_now_sb.date() + timedelta(days=1), datetime.min.time())
    _sl          = int((_midnight_sb - _now_sb).total_seconds())
    st.caption(f"⏰ Resets in {_sl // 3600}h {(_sl % 3600) // 60}m")

    if display_calls >= _cap:
        st.warning("Daily AI limit reached.")

    st.checkbox("🛠 Debug Timings", key="debug_perf")

# ═══════════════════════════════════════════════════════════════
# FRAGMENT: Metrics  (D2 animated XP bar)
# ═══════════════════════════════════════════════════════════════
@st.fragment
def render_metrics(total_hrs: float, level: int, xp: float, this_week: float, streak: int):
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Level",     f"Lvl {level}")
    m2.metric("Total",     f"{total_hrs:.1f}h")
    m3.metric("Streak",    f"{streak} Days")
    m4.metric("This Week", f"{this_week:.1f}/{st.session_state.weekly_goal}h")

    # D2: Animated XP bar — CSS keyframe driven, no st.progress flash
    pct    = int(xp * 100)
    accent = st.session_state.accent_color
    st.markdown(f"""
    <style>:root {{ --xp-target: {pct}%; }}</style>
    <div style="font-size:0.82rem;opacity:0.8;margin-top:8px">
        ✨ Progress to Level {level + 1} &nbsp;·&nbsp; {pct}%
    </div>
    <div class="xp-bar-outer">
        <div class="xp-bar-inner"
             style="width:{pct}%; background:{accent};">
        </div>
    </div>
    """, unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
# FRAGMENT: AI Coach
# All C-series improvements + A1 countdown + A3 toast + A9 eco
# ═══════════════════════════════════════════════════════════════
@st.fragment
def render_ai_coach(
    diet_dict:  dict,
    all_skills: list,
    streak:     int   = 0,
    level:      int   = 1,
    this_week:  float = 0.0,
):
    _today_local  = datetime.now().date().isoformat()
    _cap_local    = int(st.session_state.get("ai_daily_cap_setting", AI_DAILY_CAP))
    display_calls = (
        st.session_state.ai_calls_today
        if st.session_state.ai_call_date == _today_local
        else 0
    )

    # Skill target selector (D7 emoji via format_func)
    skill_options  = ["All Skills"] + all_skills
    current_target = st.session_state.ai_target_skill
    if current_target not in skill_options:
        current_target = "All Skills"
    st.session_state.ai_target_skill = st.selectbox(
        "🎯 Coach focus:",
        skill_options,
        index=skill_options.index(current_target),
        format_func=lambda x: x if x == "All Skills" else add_emoji(x),
        key="ai_skill_select",
    )

    # ── Internal fire-and-store helper ──────────────────────
    def _fire_ai(monthly_review: bool = False):
        last_tip = (
            st.session_state.last_ai_response.get("tip", "")
            if st.session_state.last_ai_response
            else ""
        )
        resp = get_ai_recommendation(
            api_key        = st.session_state.gemini_key,
            skill_totals   = diet_dict,
            target_skill   = st.session_state.ai_target_skill,
            streak         = streak,
            level          = level,
            last_tip       = last_tip,
            weekly_goal    = float(st.session_state.weekly_goal),
            this_week      = this_week,
            monthly_review = monthly_review,
        )
        st.session_state.last_ai_response   = resp
        st.session_state.last_ai_rec        = resp.get("tip", "")
        st.session_state.last_diet_hash     = _diet_hash(diet_dict)
        st.session_state.last_diet_snapshot = dict(diet_dict)   # A9 snapshot

        if monthly_review:
            st.session_state.last_monthly_review = datetime.now().date().isoformat()

        entry = {
            "time":     datetime.now().strftime("%Y-%m-%d %H:%M"),
            "skill":    st.session_state.ai_target_skill,
            "tip":      resp.get("tip", ""),
            "exercise": resp.get("exercise", ""),
            "resource": resp.get("resource", ""),
            "monthly":  monthly_review,
        }
        st.session_state.ai_history = ([entry] + st.session_state.ai_history)[:5]

    # ── A1: Visual countdown helper ──────────────────────────
    def _show_cooldown(wait_secs: float, reason: str):
        if wait_secs > 0:
            progress_val = max(0.0, min(1.0, 1.0 - (wait_secs / AI_MIN_INTERVAL)))
            st.markdown(f'<div class="cooldown-label">⏳ {reason}</div>', unsafe_allow_html=True)
            st.progress(progress_val, text=f"Cooling down — {wait_secs:.0f}s")
        else:
            st.caption(f"⏳ {reason}")

    # ── Auto mode ────────────────────────────────────────────
    if st.session_state.ask_ai_auto and st.session_state.gemini_key:
        current_hash = _diet_hash(diet_dict)
        data_changed = current_hash != st.session_state.last_diet_hash

        # A9: Eco gate — skip if change is too small
        if st.session_state.get("eco_mode", False):
            data_changed = data_changed and _eco_changed(diet_dict)

        if data_changed:
            allowed, reason, wait_secs = _check_ai_rate_limit()
            if allowed:
                with st.status("🤖 Coach is thinking...", expanded=False) as _s:
                    _fire_ai()
                    _s.update(label="✅ Coach ready", state="complete")
            else:
                if not st.session_state.last_ai_rec:
                    # A3: Toast instead of silent fail
                    st.toast(f"⏳ {reason}", icon="🤖")
                _show_cooldown(wait_secs, reason)

    # ── Manual mode ──────────────────────────────────────────
    else:
        col_ask, col_monthly = st.columns([2, 1])

        with col_ask:
            if st.button("💬 Ask Coach", use_container_width=True):
                allowed, reason, wait_secs = _check_ai_rate_limit()
                if allowed:
                    with st.status("🤖 Thinking...", expanded=False) as _s:
                        _fire_ai()
                        _s.update(label="✅ Done", state="complete")
                else:
                    st.toast(f"⏳ {reason}", icon="🚦")   # A3
                    _show_cooldown(wait_secs, reason)       # A1

        # C10: Monthly Review button
        with col_monthly:
            _last_mr   = st.session_state.get("last_monthly_review", "")
            _can_review = (not _last_mr) or (
                (datetime.now().date()
                 - datetime.fromisoformat(_last_mr).date()).days >= 30
            )
            if st.button(
                "📅 Monthly Review" if _can_review else "✅ Done this month",
                use_container_width=True,
                disabled=not _can_review,
            ):
                allowed, reason, wait_secs = _check_ai_rate_limit()
                if allowed:
                    with st.status("📅 Preparing monthly review...", expanded=False) as _s:
                        _fire_ai(monthly_review=True)
                        _s.update(label="✅ Review ready", state="complete")
                else:
                    st.toast(f"⏳ {reason}", icon="🚦")
                    _show_cooldown(wait_secs, reason)

    # ── C7: Display structured response ─────────────────────
    accent = st.session_state.accent_color
    resp   = st.session_state.last_ai_response

    if resp:
        tip      = resp.get("tip", "")
        exercise = resp.get("exercise", "")
        resource = resp.get("resource", "")
        is_monthly = (
            st.session_state.ai_history[0].get("monthly", False)
            if st.session_state.ai_history else False
        )
        expander_label = "📅 Monthly Review" if is_monthly else "💡 Coach's Insight"

        with st.expander(expander_label, expanded=True):
            if tip:
                st.markdown(
                    f'<div class="ai-card" style="--accent-col:{accent}">'
                    f'💡 <strong>Tip</strong><br>{tip}</div>',
                    unsafe_allow_html=True,
                )
            if exercise:
                st.markdown(
                    f'<div class="ai-card" style="--accent-col:{accent}">'
                    f'🏋️ <strong>Exercise</strong><br>{exercise}</div>',
                    unsafe_allow_html=True,
                )
            if resource:
                st.markdown(
                    f'<div class="ai-card" style="--accent-col:{accent}">'
                    f'🔗 <strong>Resource</strong><br>{resource}</div>',
                    unsafe_allow_html=True,
                )
            if st.session_state.last_ai_time:
                st.caption(
                    f"🕐 {st.session_state.last_ai_time.strftime('%H:%M:%S')}"
                    f"  ·  Calls today: {display_calls}/{_cap_local}"
                )
    elif st.session_state.last_ai_rec:
        # Graceful fallback for old plain-text entries
        with st.expander("💡 Coach's Insight", expanded=True):
            st.write(st.session_state.last_ai_rec)

    # History log
    if st.session_state.ai_history:
        with st.expander(
            f"📜 Coaching History ({len(st.session_state.ai_history)} tip(s))",
            expanded=False,
        ):
            for entry in st.session_state.ai_history:
                badge = " 📅 Monthly" if entry.get("monthly") else ""
                st.markdown(f"**{entry['time']}** · *{entry.get('skill','?')}*{badge}")
                if entry.get("tip"):      st.write(f"💡 {entry['tip']}")
                if entry.get("exercise"): st.write(f"🏋️ {entry['exercise']}")
                if entry.get("resource"): st.write(f"🔗 {entry['resource']}")
                st.divider()

# ═══════════════════════════════════════════════════════════════
# FRAGMENT: Dashboard Tab  (D1 mobile layout)
# ═══════════════════════════════════════════════════════════════
@st.fragment
def render_tab_dashboard(
    df: pd.DataFrame,
    diet: pd.Series,
    accent_color: str,
    today_mins: float,
    daily_goal_mins: int,
):
    mobile = st.session_state.get("mobile_mode", False)

    if mobile:
        # D1: single-column stack for narrow screens
        st.plotly_chart(build_area_chart(df, accent_color, "Study Mountain"), use_container_width=True)
        st.plotly_chart(build_pie_chart(tuple(diet.index), tuple(diet.values)),  use_container_width=True)
        st.plotly_chart(build_heatmap(df, accent_color),                         use_container_width=True)
        st.plotly_chart(build_daily_ring(today_mins, daily_goal_mins, accent_color), use_container_width=True)
        st.plotly_chart(build_skill_bars(diet, accent_color),                    use_container_width=True)
    else:
        c1, c2 = st.columns([2, 1])
        with c1:
            st.plotly_chart(build_area_chart(df, accent_color, "Study Mountain"), use_container_width=True)
        with c2:
            st.plotly_chart(build_pie_chart(tuple(diet.index), tuple(diet.values)),  use_container_width=True)

        c3, c4 = st.columns([3, 1])
        with c3:
            st.plotly_chart(build_heatmap(df, accent_color), use_container_width=True)
        with c4:
            st.plotly_chart(build_daily_ring(today_mins, daily_goal_mins, accent_color), use_container_width=True)

        st.plotly_chart(build_skill_bars(diet, accent_color), use_container_width=True)

# ═══════════════════════════════════════════════════════════════
# FRAGMENT: History Tab
# ═══════════════════════════════════════════════════════════════
@st.fragment
def render_tab_history(df: pd.DataFrame, all_skills: list):
    st.info("💡 Changes made below are auto-synced to GitHub.")

    _date_col = (
        df["Date"].dt.strftime("%Y-%m-%d")
        if pd.api.types.is_datetime64_any_dtype(df["Date"])
        else df["Date"]
    )
    csv_bytes = df.assign(Date=_date_col).to_csv(index=False).encode("utf-8")
    st.download_button(
        label="⬇️ Export CSV",
        data=csv_bytes,
        file_name=f"english_pro_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )

    st.session_state.df = st.data_editor(
        df,
        column_config={
            "Date":  st.column_config.DateColumn(),
            "Skill": st.column_config.SelectboxColumn(options=all_skills),
        },
        use_container_width=True,
        hide_index=True,
        key="editor_key",
        on_change=handle_editor_change,
    )

# ═══════════════════════════════════════════════════════════════
# FRAGMENT: Trophies Tab
# ═══════════════════════════════════════════════════════════════
@st.fragment
def render_tab_trophies(
    total_hrs: float,
    streak: int,
    unique_skills: int,
    level: int,
    accent_color: str,
):
    if level >= 2:
        st.success(
            f"🚀 You are **Level {level}**! "
            f"Next level unlocks at **{level * 50:.0f} hours** total."
        )

    st.subheader("🎁 Today's Milestone Reward")
    new_reward = st.text_input(
        "Your personal reward",
        value=st.session_state.milestone_reward,
        key="reward_input",
        placeholder="e.g. Treat myself to coffee",
    )
    if new_reward != st.session_state.milestone_reward:
        st.session_state.milestone_reward = new_reward
        sync_config_to_github()

    today_iso = datetime.now().date().isoformat()
    if st.session_state.milestone_claimed_date != today_iso:
        if st.button(f"🎉 Claim: {st.session_state.milestone_reward}", use_container_width=True):
            st.success("Claimed! Enjoy your reward. 🎊")
            st.session_state.milestone_claimed_date = today_iso
            st.balloons()
    else:
        st.success("✅ Reward claimed for today — see you tomorrow!")

    st.divider()
    st.subheader("🏅 Achievements")
    unlocked   = evaluate_achievements(total_hrs, streak, unique_skills)
    n_unlocked = len(unlocked)
    st.caption(f"{n_unlocked} / {len(ACHIEVEMENTS)} unlocked")

    cols = st.columns(5)
    for i, ach in enumerate(ACHIEVEMENTS):
        is_unlocked = ach["id"] in unlocked
        lock_cls    = "" if is_unlocked else "badge-locked"
        status_html = (
            f'<div style="font-size:0.65rem;color:{accent_color};margin-top:4px">✅ Unlocked</div>'
            if is_unlocked
            else '<div style="font-size:0.65rem;opacity:0.5;margin-top:4px">🔒 Locked</div>'
        )
        with cols[i % 5]:
            st.markdown(
                f"""<div class="badge-card {lock_cls}">
                    <div style="font-size:2rem">{ach["emoji"]}</div>
                    <div style="font-size:0.75rem;font-weight:bold;margin-top:4px">{ach["title"]}</div>
                    <div style="font-size:0.65rem;opacity:0.8">{ach["desc"]}</div>
                    {status_html}
                </div>""",
                unsafe_allow_html=True,
            )

# ═══════════════════════════════════════════════════════════════
# FRAGMENT: Settings Tab
# A7 daily cap slider  A9 eco mode  D1 mobile toggle
# ═══════════════════════════════════════════════════════════════
@st.fragment
def render_tab_settings():
    # ── A7: AI budget cap ────────────────────────────────────
    st.subheader("🤖 AI Budget")
    st.slider(
        "Daily AI Call Limit",
        min_value=1,
        max_value=AI_DAILY_CAP,
        key="ai_daily_cap_setting",
        help=f"Hard ceiling is {AI_DAILY_CAP}/day (Gemini Free Tier). "
             "Lower this to be extra conservative.",
        on_change=sync_config_to_github,
    )

    # ── A9: Eco mode ─────────────────────────────────────────
    st.toggle(
        "🌿 Eco Mode — only call AI when skill data changes by 5 %+",
        key="eco_mode",
        on_change=sync_config_to_github,
    )
    if st.session_state.eco_mode:
        st.caption(
            "Eco Mode ON · The AI coach skips calls when your "
            "skill totals haven't shifted meaningfully."
        )

    st.divider()

    # ── D1: Mobile layout ────────────────────────────────────
    st.subheader("📱 Layout")
    st.toggle(
        "📱 Mobile-Friendly Layout (single column)",
        key="mobile_mode",
        on_change=sync_config_to_github,
    )

    st.divider()

    # ── Custom Skills Manager (preserved) ────────────────────
    st.subheader("⚙️ Custom Skills Manager")
    st.caption(
        "Add skills beyond the default six. "
        "They appear in the Log dialog, History editor, and AI focus selector. "
        "Saved to your GitHub config.json."
    )

    custom = list(st.session_state.custom_skills or [])

    col_input, col_btn = st.columns([3, 1])
    with col_input:
        new_skill = st.text_input(
            "New skill name",
            placeholder="e.g. Pronunciation",
            label_visibility="collapsed",
        )
    with col_btn:
        add_clicked = st.button("➕ Add", use_container_width=True)

    if add_clicked:
        stripped = new_skill.strip()
        if not stripped:
            st.warning("Enter a skill name first.")
        elif stripped in custom:
            st.warning(f"'{stripped}' already exists.")
        else:
            custom.append(stripped)
            st.session_state.custom_skills = custom
            _invalidate_derived_cache()
            sync_config_to_github()
            st.success(f"Added: {stripped}")
            st.rerun()

    if custom:
        st.markdown("**Your custom skills:**")
        for skill in list(custom):
            sc1, sc2 = st.columns([5, 1])
            sc1.write(f"• {skill}")
            if sc2.button("🗑️", key=f"del_{skill}", help=f"Remove {skill}"):
                custom.remove(skill)
                st.session_state.custom_skills = custom
                _invalidate_derived_cache()
                sync_config_to_github()
                st.rerun()
    else:
        st.info("No custom skills added yet.")

    st.divider()
    st.subheader("🗃️ Default Skills")
    st.caption(
        "Always available: "
        "🎧 Listening, 🗣️ Speaking, 📖 Reading, "
        "✍️ Writing, 📝 Grammar, 💬 Vocabulary."
    )

# ═══════════════════════════════════════════════════════════════
# ONBOARDING WIZARD (E3 preserved)
# ═══════════════════════════════════════════════════════════════
def render_onboarding():
    st.title("🇬🇧 English Pro Elite")
    st.markdown("### Welcome! Complete 3 quick steps to get started.")

    has_token = bool(st.session_state.saved_token)
    has_repo  = bool(st.session_state.saved_repo)
    has_key   = bool(st.session_state.gemini_key)

    steps = [
        ("1️⃣ GitHub Token",   has_token, "Paste your Personal Access Token in the **Connection** panel on the left."),
        ("2️⃣ Repository",     has_repo,  "Enter your repo name (e.g. `username/english-tracker`)."),
        ("3️⃣ Gemini API Key", has_key,   "Optional — add your key to unlock the AI coach feature."),
    ]
    completed = sum(1 for _, done, _ in steps if done)

    st.markdown('<div class="onboarding-card">', unsafe_allow_html=True)
    for label, done, hint in steps:
        icon = "✅" if done else "⏳"
        st.markdown(
            f'<div class="onboarding-step">{icon} <strong>{label}</strong><br>'
            f'<span style="font-size:0.88rem;opacity:0.8">{hint}</span></div>',
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)
    st.progress(completed / 3, text=f"Setup: {completed}/3 complete")

    if completed == 3:
        st.success("🎉 All set! Click **🔄 Refresh Application** in the sidebar to load your data.")
    else:
        st.info(f"👈 Complete **{3 - completed} more step(s)** in the sidebar to continue.")

# ═══════════════════════════════════════════════════════════════
# MAIN UI
# ═══════════════════════════════════════════════════════════════
if st.session_state.df is not None:
    t_main = time.perf_counter()
    df     = st.session_state.df

    total_hrs, level, xp, streak = get_dashboard_stats(df)
    all_skills, diet, this_week  = get_or_compute_derived(df)

    # ── D3: Achievement unlock detection ────────────────────
    unique_skills     = int(df["Skill"].nunique())
    current_unlocked  = evaluate_achievements(total_hrs, streak, unique_skills)
    prev_set          = set(st.session_state.prev_achievements)
    newly_unlocked    = current_unlocked - prev_set
    # Only celebrate when we have a prior baseline (not on first load)
    if newly_unlocked and prev_set:
        for _ach_id in newly_unlocked:
            _ach = next((a for a in ACHIEVEMENTS if a["id"] == _ach_id), None)
            if _ach:
                st.balloons()
                st.toast(
                    f"{_ach['emoji']} Achievement Unlocked: **{_ach['title']}**!",
                    icon="🏅",
                )
    st.session_state.prev_achievements = list(current_unlocked)

    # D3 / level-up detection
    if level > st.session_state.prev_level > 0:
        st.balloons()
        st.toast(f"🚀 Level Up! You've reached **Level {level}**!", icon="🎉")
    if st.session_state.prev_level == 0 or level > st.session_state.prev_level:
        st.session_state.prev_level = level

    today_date = pd.Timestamp(datetime.now().date())
    today_mins = float(df.loc[df["Date"] >= today_date, "Time Spent"].sum())

    # Title row
    c_title, c_btn = st.columns([3, 1])
    with c_title:
        st.title("🇬🇧 English Pro Elite")
    with c_btn:
        if st.button("➕ Log Time", type="primary", use_container_width=True):
            log_session_dialog(all_skills)

    render_metrics(total_hrs, level, xp, this_week, streak)
    render_ai_coach(
        diet.to_dict(),
        all_skills,
        streak=streak,
        level=level,
        this_week=this_week,
    )

    if st.session_state.zen_mode:
        st.markdown(
            "<style>[data-testid='stSidebar']{display:none;} header{display:none;}</style>",
            unsafe_allow_html=True,
        )
        if st.button("❌ Exit Zen"):
            st.session_state.zen_mode = False
            st.rerun()
        st.plotly_chart(
            build_area_chart(df, st.session_state.accent_color, "Learning Curve"),
            use_container_width=True,
        )
    else:
        tab_dash, tab_history, tab_trophy, tab_settings = st.tabs([
            "📈 Dashboard",
            "📝 History",
            "🏆 Trophies",
            "⚙️ Settings",
        ])
        with tab_dash:
            render_tab_dashboard(
                df, diet,
                st.session_state.accent_color,
                today_mins,
                st.session_state.daily_goal_mins,
            )
        with tab_history:
            render_tab_history(df, all_skills)
        with tab_trophy:
            render_tab_trophies(
                total_hrs, streak, unique_skills,
                level, st.session_state.accent_color,
            )
        with tab_settings:
            render_tab_settings()

    perf_log("full_main_render", t_main)

else:
    render_onboarding()
