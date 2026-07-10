import streamlit as st
import pandas as pd
from github import Github
from datetime import datetime, timedelta, timezone, date
import io
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import google.generativeai as genai
import json
import os
import re
import base64
import time
import hashlib
import uuid

# ═══════════════════════════════════════════════════════════════
# 🌏 TIMEZONE — WIB (UTC+7)
# ═══════════════════════════════════════════════════════════════
_WIB = timezone(timedelta(hours=7))

def now_wib() -> datetime:
    return datetime.now(_WIB)

def today_wib() -> date:
    return now_wib().date()

# ═══════════════════════════════════════════════════════════════
# ⚡ PERF INSTRUMENTATION
# ═══════════════════════════════════════════════════════════════
_APP_T0 = time.perf_counter()

def perf_log(label: str, t0: float) -> float:
    elapsed_ms = (time.perf_counter() - t0) * 1000
    if st.session_state.get("debug_perf", False):
        st.sidebar.caption(f"⏱ {label}: {elapsed_ms:.1f}ms")
    return elapsed_ms

# ═══════════════════════════════════════════════════════════════
# CONFIG & CONSTANTS
# ═══════════════════════════════════════════════════════════════
st.set_page_config(page_title="English Pro Elite", layout="wide", page_icon="🇬🇧")

CRED_FILE       = "credentials.json"
AI_MIN_INTERVAL = 12
AI_DAILY_CAP    = 18
SCHEMA_VERSION  = "v1"

SCHEDULE_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

SKILL_EMOJI = {
    "Listening":  "🎧",
    "Speaking":   "🗣️",
    "Reading":    "📖",
    "Writing":    "✍️",
    "Grammar":    "📝",
    "Vocabulary": "💬",
}

def add_emoji(skill: str) -> str:
    return f"{SKILL_EMOJI.get(skill, '📚')} {skill}"

ACHIEVEMENTS = [
    {"id": "first_hour",    "emoji": "⭐", "title": "First Hour",     "desc": "Log your first hour",         "check": lambda h, s, sk: h >= 1},
    {"id": "ten_hours",     "emoji": "🔟", "title": "Ten Hours",      "desc": "Accumulate 10 total hours",    "check": lambda h, s, sk: h >= 10},
    {"id": "fifty_hours",   "emoji": "🥈", "title": "Half Century",   "desc": "Reach 50 total hours",         "check": lambda h, s, sk: h >= 50},
    {"id": "hundred_hours", "emoji": "💯", "title": "Century Club",   "desc": "Reach 100 total hours",        "check": lambda h, s, sk: h >= 100},
    {"id": "streak_3",      "emoji": "🔥", "title": "On Fire",        "desc": "3-day streak",                 "check": lambda h, s, sk: s >= 3},
    {"id": "streak_7",      "emoji": "🗓️", "title": "Week Warrior",   "desc": "7-day streak",                 "check": lambda h, s, sk: s >= 7},
    {"id": "streak_30",     "emoji": "🏆", "title": "Monthly Master", "desc": "30-day streak",                "check": lambda h, s, sk: s >= 30},
    {"id": "polymath",      "emoji": "🎓", "title": "Polymath",       "desc": "Study 4+ different skills",    "check": lambda h, s, sk: sk >= 4},
    {"id": "level_5",       "emoji": "🚀", "title": "Level 5",        "desc": "Reach Level 5 (200h total)",   "check": lambda h, s, sk: h >= 200},
    {"id": "dedicated",     "emoji": "🦉", "title": "Dedicated",      "desc": "Study 500+ total minutes",     "check": lambda h, s, sk: h >= 8.34},
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
# BACKGROUND
# ═══════════════════════════════════════════════════════════════
@st.cache_resource(show_spinner=False)
def _load_bg_base64(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def set_background(png_file: str, light_mode: bool = False):
    bg           = _load_bg_base64(png_file)
    sidebar_bg   = "rgba(245,245,250,0.88)" if light_mode else "rgba(0,0,0,0.70)"
    tab_bg       = "rgba(255,255,255,0.85)" if light_mode else "rgba(20,20,20,0.60)"
    text_color   = "#0d0d0d"               if light_mode else "white"
    alert_bg     = "rgba(255,255,255,0.5)" if light_mode else "rgba(0,0,0,0.40)"
    alert_border = "rgba(0,0,0,0.15)"      if light_mode else "rgba(255,255,255,0.20)"

    # Light-mode specific overrides — fixes buttons, chat bubbles, inputs
    light_extra = """
    /* ── Buttons: dark text on light bg ── */
    .stButton > button {
        color: #0d0d0d !important;
        background-color: rgba(255,255,255,0.90) !important;
        border: 1px solid rgba(0,0,0,0.18) !important;
    }
    .stButton > button:hover {
        background-color: rgba(220,220,230,0.95) !important;
        border-color: rgba(0,0,0,0.30) !important;
    }
    /* Primary buttons keep accent colour but stay readable */
    .stButton > button[kind="primary"] {
        color: #ffffff !important;
    }
    /* ── Chat input ── */
    [data-testid="stChatInput"] textarea,
    [data-testid="stChatInput"] {
        background-color: rgba(255,255,255,0.92) !important;
        color: #0d0d0d !important;
        border: 1px solid rgba(0,0,0,0.20) !important;
    }
    /* ── Chat messages ── */
    [data-testid="stChatMessage"] {
        background-color: rgba(255,255,255,0.88) !important;
        border: 1px solid rgba(0,0,0,0.10) !important;
        border-radius: 12px !important;
    }
    [data-testid="stChatMessage"] p,
    [data-testid="stChatMessage"] span,
    [data-testid="stChatMessage"] div {
        color: #0d0d0d !important;
    }
    /* ── Suggestion chips / all secondary buttons in chat ── */
    [data-testid="stHorizontalBlock"] .stButton > button,
    .stColumn .stButton > button {
        color: #0d0d0d !important;
        background-color: rgba(255,255,255,0.92) !important;
        border: 1px solid rgba(0,0,0,0.20) !important;
    }
    /* ── Selectbox / dropdowns ── */
    [data-testid="stSelectbox"] > div > div {
        background-color: rgba(255,255,255,0.92) !important;
        color: #0d0d0d !important;
        border: 1px solid rgba(0,0,0,0.20) !important;
    }
    /* ── Number inputs ── */
    [data-testid="stNumberInput"] input {
        background-color: rgba(255,255,255,0.92) !important;
        color: #0d0d0d !important;
    }
    /* ── Text inputs ── */
    [data-testid="stTextInput"] input {
        background-color: rgba(255,255,255,0.92) !important;
        color: #0d0d0d !important;
        border: 1px solid rgba(0,0,0,0.20) !important;
    }
    /* ── Expanders ── */
    [data-testid="stExpander"] {
        background-color: rgba(255,255,255,0.80) !important;
        border: 1px solid rgba(0,0,0,0.12) !important;
    }
    [data-testid="stExpander"] summary span,
    [data-testid="stExpander"] p {
        color: #0d0d0d !important;
    }
    /* ── Metrics ── */
    [data-testid="stMetric"] {
        background-color: rgba(255,255,255,0.75) !important;
        border-radius: 10px !important;
        padding: 8px !important;
    }
    /* ── Tab labels ── */
    .stTabs [data-baseweb="tab"] span {
        color: #0d0d0d !important;
    }
    /* ── Caption / small text ── */
    .stCaption, small, caption {
        color: #444444 !important;
    }
    /* ── ai-card in light mode ── */
    .ai-card {
        background: rgba(0,0,0,0.05) !important;
        color: #0d0d0d !important;
    }
    /* ── XP bar track ── */
    .xp-bar-outer {
        background: rgba(0,0,0,0.10) !important;
        border: 1px solid rgba(0,0,0,0.15) !important;
    }
    """ if light_mode else ""

    bg_css = (
        f'.stApp {{background-image:url("data:image/png;base64,{bg}");'
        f'background-size:cover;background-attachment:fixed;}}'
        if bg else
        f'.stApp {{background-color:{"#f0f2f6" if light_mode else "#0d1117"};}}'
    )
    st.markdown(f"""
    <style>
    {bg_css}
    [data-testid="stSidebar"]{{background-color:{sidebar_bg}!important;backdrop-filter:blur(10px);}}
    .stTabs [data-baseweb="tab-panel"]{{background-color:{tab_bg}!important;padding:20px;
        border-radius:15px;backdrop-filter:blur(5px);border:1px solid rgba(0,0,0,0.08);}}
    [data-testid="stMetricValue"]{{color:{text_color}!important;}}
    h1,h2,h3,h4,p,span,label,.stMarkdown div p{{color:{text_color}!important;}}
    .stAlert{{background-color:{alert_bg}!important;color:{text_color}!important;
        border:1px solid {alert_border}!important;}}
    .badge-card{{background:rgba(255,255,255,0.10);border-radius:12px;padding:12px 8px;
        text-align:center;border:1px solid rgba(255,255,255,0.18);margin-bottom:8px;
        transition:transform 0.15s ease;}}
    .badge-card:hover{{transform:translateY(-2px);}}
    .badge-locked{{opacity:0.32;filter:grayscale(100%);}}
    .onboarding-card{{background:rgba(0,0,0,0.48);border-radius:16px;padding:28px 24px;
        border:1px solid rgba(255,255,255,0.14);margin:16px 0;}}
    .onboarding-step{{margin-bottom:14px;font-size:1.02rem;}}
    @keyframes xp-fill{{from{{width:0%;}}to{{width:var(--xp-target);}}}}
    .xp-bar-outer{{background:rgba(255,255,255,0.12);border-radius:999px;height:18px;
        overflow:hidden;margin:6px 0 2px 0;border:1px solid rgba(255,255,255,0.18);}}
    .xp-bar-inner{{height:100%;border-radius:999px;
        animation:xp-fill 1.1s cubic-bezier(.4,0,.2,1) forwards;}}
    .ai-card{{background:rgba(255,255,255,0.07);border-radius:10px;padding:10px 14px;
        margin:6px 0;border-left:3px solid var(--accent-col,#00CC96);}}
    .cooldown-label{{font-size:0.82rem;opacity:0.85;margin-bottom:2px;}}
    .sched-card{{
        background:rgba(255,255,255,0.06);
        border-radius:12px;padding:14px 18px;
        border:1px solid rgba(255,255,255,0.14);
        margin-bottom:6px;
    }}
    .sched-done{{
        background:rgba(0,204,150,0.12);
        border-color:rgba(0,204,150,0.35);
        opacity:0.65;
    }}
    .sched-header{{
        font-size:0.78rem;font-weight:600;letter-spacing:0.07em;
        text-transform:uppercase;opacity:0.6;margin-bottom:6px;
    }}
    {light_extra}
    </style>
    """, unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
# SESSION STATE DEFAULTS
# ═══════════════════════════════════════════════════════════════
_DEFAULTS = {
    "df": None, "file_sha": None, "prev_level": 0,
    "zen_mode": False, "theme_selector": "Emerald City",
    "weekly_goal": 5, "daily_goal_mins": 60,
    "ask_ai_auto": False, "light_mode": False,
    "saved_token": local_creds.get("saved_token", ""),
    "saved_repo":  local_creds.get("saved_repo",  ""),
    "gemini_key":  local_creds.get("gemini_key",  ""),
    "milestone_reward": "Treat myself to coffee",
    "milestone_claimed_date": "",
    "last_ai_rec": "", "last_ai_response": {}, "last_ai_time": None,
    "ai_calls_today": 0, "ai_call_date": "",
    "ai_history": [], "last_diet_hash": "", "last_diet_snapshot": {},
    "ai_target_skill": "All Skills", "last_monthly_review": "",
    "cached_all_skills": None, "cached_diet": None, "cached_this_week": None,
    "debug_perf": False, "accent_color": "#00CC96",
    "custom_skills": [],
    "eco_mode": False, "ai_daily_cap_setting": AI_DAILY_CAP,
    "mobile_mode": False, "prev_achievements": [],
    "study_schedule": [],
    "log_rows": None,
    "ai_chat_history": [],
    "edit_schedule_id": None,
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

set_background("background.jpg", light_mode=st.session_state.light_mode)

# ═══════════════════════════════════════════════════════════════
# DATE NORMALIZATION HELPERS
# ═══════════════════════════════════════════════════════════════
def _naive_dates(series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        try:
            if series.dt.tz is not None:
                return series.dt.tz_localize(None)
        except Exception:
            pass
    return series

def _naive_ts(d) -> pd.Timestamp:
    ts = pd.Timestamp(d)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ts

# ═══════════════════════════════════════════════════════════════
# GITHUB
# ═══════════════════════════════════════════════════════════════
@st.cache_resource(show_spinner=False)
def get_gh_client(token):
    return Github(token)

def _invalidate_derived_cache():
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
            try:
                if df["Date"].dt.tz is not None:
                    df["Date"] = df["Date"].dt.tz_localize(None)
            except Exception:
                pass
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
                "eco_mode":             st.session_state.eco_mode,
                "ai_daily_cap_setting": st.session_state.ai_daily_cap_setting,
                "mobile_mode":          st.session_state.mobile_mode,
                "study_schedule":       st.session_state.study_schedule,
            },
        )

def save_to_github(token: str, repo_name: str, file_path: str, df: pd.DataFrame):
    t0 = time.perf_counter()
    try:
        if pd.api.types.is_datetime64_any_dtype(df["Date"]):
            df_save = df.assign(Date=df["Date"].dt.strftime("%Y-%m-%d"))
        else:
            df_save = df
        buf = io.StringIO()
        df_save.to_csv(buf, index=False)
        content_str = buf.getvalue()

        g    = get_gh_client(token)
        repo = g.get_repo(repo_name)

        sha = st.session_state.get("file_sha") or repo.get_contents(file_path).sha

        try:
            res = repo.update_file(
                path=file_path, message="Sync Elite Tracker",
                content=content_str, sha=sha,
            )
        except Exception:
            sha = repo.get_contents(file_path).sha
            st.session_state.file_sha = sha
            res = repo.update_file(
                path=file_path, message="Sync Elite Tracker",
                content=content_str, sha=sha,
            )

        new_sha = res["content"].sha
        st.session_state.file_sha = new_sha
        perf_log("save_to_github", t0)
        return new_sha

    except Exception as e:
        st.session_state.file_sha = None
        st.error(f"❌ GitHub Sync Error: {e}")
        return None

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
        _invalidate_derived_cache()
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
            "study_schedule":       "study_schedule",
        }
        for cfg_key, ss_key in _cfg_map.items():
            if cfg_key in _remote_cfg:
                st.session_state[ss_key] = _remote_cfg[cfg_key]

# ═══════════════════════════════════════════════════════════════
# STREAK (vectorized)
# ═══════════════════════════════════════════════════════════════
def _compute_streak_vectorized(date_series: pd.Series) -> int:
    dates = _naive_dates(date_series).dt.date.dropna().unique()
    if len(dates) == 0:
        return 0
    today        = today_wib()
    dates_sorted = sorted(dates, reverse=True)
    if dates_sorted[0] not in (today, today - timedelta(days=1)):
        return 0
    ordinals = np.array([d.toordinal() for d in dates_sorted])
    diffs    = np.diff(ordinals)
    breaks   = np.where(diffs != -1)[0]
    return int(breaks[0]) + 1 if len(breaks) > 0 else len(dates_sorted)

# ═══════════════════════════════════════════════════════════════
# DASHBOARD STATS
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

    _today     = today_wib()
    week_start = _naive_ts(_today - timedelta(days=_today.weekday()))
    dates_col  = _naive_dates(df["Date"])
    this_week  = float(df.loc[dates_col >= week_start, "Time Spent"].sum()) / 60

    st.session_state.cached_all_skills = all_skills
    st.session_state.cached_diet       = diet
    st.session_state.cached_this_week  = this_week
    perf_log("get_or_compute_derived", t0)
    return all_skills, diet, this_week

# ═══════════════════════════════════════════════════════════════
# PLOTLY CHARTS
# ═══════════════════════════════════════════════════════════════
@st.cache_data(show_spinner=False)
def build_area_chart(df: pd.DataFrame, accent_color: str, title: str):
    daily = df.sort_values("Date").groupby("Date")["Time Spent"].sum().reset_index()
    daily["7d avg"]  = daily["Time Spent"].rolling(7,  min_periods=1).mean()
    daily["30d avg"] = daily["Time Spent"].rolling(30, min_periods=1).mean()
    fig = px.area(daily, x="Date", y="Time Spent", title=title,
                  color_discrete_sequence=[accent_color])
    fig.add_scatter(x=daily["Date"], y=daily["7d avg"],  mode="lines", name="7d avg",
                    line=dict(color="orange", width=1.5, dash="dot"))
    fig.add_scatter(x=daily["Date"], y=daily["30d avg"], mode="lines", name="30d avg",
                    line=dict(color="cyan",   width=1.5, dash="dash"))
    fig.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                      font_color="white", legend=dict(orientation="h", y=-0.22))
    return fig

@st.cache_data(show_spinner=False)
def build_pie_chart(skill_names: tuple, skill_values: tuple):
    emoji_names = tuple(add_emoji(s) for s in skill_names)
    fig = px.pie(names=emoji_names, values=skill_values, hole=0.5, title="Skill Diet")
    fig.update_layout(showlegend=False, plot_bgcolor="rgba(0,0,0,0)",
                      paper_bgcolor="rgba(0,0,0,0)", font_color="white")
    return fig

@st.cache_data(show_spinner=False)
def build_heatmap(df: pd.DataFrame, accent_color: str):
    cutoff    = _naive_ts(today_wib() - timedelta(days=90))
    dates_col = _naive_dates(df["Date"])
    daily = (
        df[dates_col >= cutoff]
        .groupby(dates_col.dt.date)["Time Spent"]
        .sum().reset_index()
    )
    daily.columns = ["Date", "Minutes"]
    daily["Date"] = pd.to_datetime(daily["Date"])
    daily["Week"] = daily["Date"].dt.isocalendar().week.astype(str)
    daily["DOW"]  = daily["Date"].dt.day_name()
    dow_order = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
    fig = px.density_heatmap(
        daily, x="Week", y="DOW", z="Minutes",
        category_orders={"DOW": dow_order},
        color_continuous_scale=["#111111", accent_color],
        title="90-Day Study Heatmap",
    )
    fig.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                      font_color="white", coloraxis_showscale=False,
                      yaxis=dict(categoryorder="array", categoryarray=dow_order))
    return fig

@st.cache_data(show_spinner=False)
def build_skill_bars(diet: pd.Series, accent_color: str):
    df_bar = diet.reset_index()
    df_bar.columns = ["Skill", "Minutes"]
    df_bar["Skill"] = df_bar["Skill"].apply(add_emoji)
    df_bar = df_bar.sort_values("Minutes", ascending=True)
    fig = px.bar(df_bar, x="Minutes", y="Skill", orientation="h",
                 title="Minutes Per Skill", color="Minutes",
                 color_continuous_scale=["#222222", accent_color])
    fig.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                      font_color="white", coloraxis_showscale=False, showlegend=False)
    return fig

@st.cache_data(show_spinner=False)
def build_daily_ring(today_mins: float, goal_mins: int, accent_color: str):
    ceiling = max(float(goal_mins), today_mins, 1.0)
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=today_mins,
        number={"suffix": " min", "font": {"color": "white", "size": 22}},
        title={"text": f"Today vs {goal_mins} min goal", "font": {"color": "white", "size": 13}},
        gauge={"axis": {"range": [0, ceiling], "tickcolor": "white"},
               "bar": {"color": accent_color}, "bgcolor": "rgba(0,0,0,0)",
               "bordercolor": "rgba(255,255,255,0.2)",
               "threshold": {"line": {"color": "white", "width": 2}, "value": goal_mins}},
    ))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_color="white",
                      height=220, margin=dict(t=40, b=10, l=20, r=20))
    return fig

# ═══════════════════════════════════════════════════════════════
# AI HELPERS
# ═══════════════════════════════════════════════════════════════
def _diet_hash(diet_dict: dict) -> str:
    return hashlib.md5(json.dumps(diet_dict, sort_keys=True).encode()).hexdigest()

def _check_ai_rate_limit() -> tuple:
    now       = now_wib()
    today_str = now.date().isoformat()
    cap       = int(st.session_state.get("ai_daily_cap_setting", AI_DAILY_CAP))
    if st.session_state.ai_call_date != today_str:
        st.session_state.ai_call_date   = today_str
        st.session_state.ai_calls_today = 0
    if st.session_state.ai_calls_today >= cap:
        midnight  = datetime.combine(now.date() + timedelta(days=1),
                                     datetime.min.time(), tzinfo=_WIB)
        secs_left = int((midnight - now).total_seconds())
        return False, f"Daily limit ({cap}/day). Resets in {secs_left//3600}h {(secs_left%3600)//60}m.", 0.0
    last = st.session_state.last_ai_time
    if last:
        last_aware = last if last.tzinfo else last.replace(tzinfo=_WIB)
        elapsed    = (now - last_aware).total_seconds()
        if elapsed < AI_MIN_INTERVAL:
            wait = AI_MIN_INTERVAL - elapsed
            return False, f"Cooling down — ready in {wait:.0f}s.", float(wait)
    return True, "", 0.0

def _eco_changed(diet_dict: dict, threshold_pct: float = 5.0) -> bool:
    old   = st.session_state.get("last_diet_snapshot", {})
    if not old:
        return True
    total = sum(diet_dict.values()) or 1
    delta = sum(abs(diet_dict.get(k, 0) - old.get(k, 0)) for k in set(diet_dict) | set(old))
    return (delta / total * 100) >= threshold_pct

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
# AI COACH
# ═══════════════════════════════════════════════════════════════
def get_ai_recommendation(api_key, skill_totals, target_skill="All Skills",
                          streak=0, level=1, last_tip="",
                          weekly_goal=5.0, this_week=0.0,
                          monthly_review=False) -> dict:
    if not api_key:
        return {"tip": "Please provide a Gemini API key.", "exercise": "", "resource": ""}
    try:
        genai.configure(api_key=api_key)
        model   = genai.GenerativeModel("gemini-2.5-flash-lite")
        compact = json.dumps(skill_totals, separators=(",", ":"))
        weakest = min(skill_totals, key=skill_totals.get) if skill_totals else "General"
        ctx_parts = [f"Skills(mins):{compact}"]
        if level > 1:     ctx_parts.append(f"Level:{level}")
        if streak > 0:    ctx_parts.append(f"Streak:{streak}d")
        if this_week > 0: ctx_parts.append(f"ThisWeek:{this_week:.1f}/{weekly_goal}h")
        if last_tip:      ctx_parts.append(f"PreviousTip(doNotRepeat):{last_tip[:80]}")
        ctx      = ". ".join(ctx_parts)
        json_fmt = 'Reply ONLY with valid JSON (no markdown): {"tip":"...","exercise":"...","resource":"..."}'
        if monthly_review:
            prompt = (f"English coach. {ctx}. Monthly review: celebrate strengths, "
                      f"focus on weakest skill ({weakest}), set 3 goals. ≤150 words. {json_fmt}")
        elif target_skill != "All Skills":
            prompt = (f"English coach. {ctx}. Weakest:{weakest}. "
                      f"Focus ONLY on '{target_skill}'. ONE tip. ≤60 words. {json_fmt}")
        else:
            prompt = (f"English coach. {ctx}. "
                      f"Target weakest:{weakest}. ONE tip. ≤60 words. {json_fmt}")
        result_text = model.generate_content(prompt).text
        st.session_state.last_ai_time    = now_wib()
        st.session_state.ai_calls_today += 1
        return _parse_ai_json(result_text)
    except Exception as e:
        return {"tip": f"AI Error: {str(e)}", "exercise": "", "resource": ""}

# ═══════════════════════════════════════════════════════════════
# ACHIEVEMENTS
# ═══════════════════════════════════════════════════════════════
def evaluate_achievements(total_hrs, streak, unique_skills) -> set:
    unlocked = set()
    for ach in ACHIEVEMENTS:
        try:
            if ach["check"](total_hrs, streak, unique_skills):
                unlocked.add(ach["id"])
        except Exception:
            pass
    return unlocked

# ═══════════════════════════════════════════════════════════════
# SCHEDULE DONE-STATE (persistent via CSV data)
# ═══════════════════════════════════════════════════════════════
def _get_schedule_done_from_data(today_items: list, today_date) -> set:
    """Return set of item_ids that have already been logged today."""
    df = st.session_state.df
    if df is None or df.empty:
        return set()
    dates_norm = _naive_dates(df["Date"])
    today_data = df[dates_norm.dt.date == today_date]
    if today_data.empty:
        return set()
    done_ids = set()
    for item in today_items:
        item_id = item.get("id", "")
        if not item_id:
            continue
        if today_data["Notes"].str.contains(item_id, na=False, regex=False).any():
            done_ids.add(item_id)
    return done_ids

# ═══════════════════════════════════════════════════════════════
# EDIT SCHEDULE DIALOG
# ═══════════════════════════════════════════════════════════════
@st.dialog("✏️ Edit Schedule Item")
def edit_schedule_dialog(item_id: str, all_skills: list):
    schedule = st.session_state.study_schedule
    item     = next((s for s in schedule if s.get("id") == item_id), None)

    if not item:
        st.error("Schedule item not found.")
        if st.button("Close"):
            st.rerun()
        return

    current_name  = item.get("name", "")
    current_day   = item.get("day", 0)
    current_skill = item.get("skill", all_skills[0] if all_skills else "Listening")
    current_mins  = item.get("minutes", 30)

    new_name = st.text_input(
        "Session Name (optional)",
        value=current_name,
        placeholder=f"e.g. Morning {current_skill} Practice",
        key="edit_sched_name",
    )
    new_day = st.selectbox(
        "Day", SCHEDULE_DAYS,
        index=current_day,
        key="edit_sched_day",
    )
    skill_idx = (all_skills.index(current_skill)
                 if current_skill in all_skills else 0)
    new_skill = st.selectbox(
        "Skill", all_skills,
        index=skill_idx,
        format_func=add_emoji,
        key="edit_sched_skill",
    )
    new_mins = st.number_input(
        "Minutes (planned)", min_value=5, max_value=300,
        value=current_mins,
        key="edit_sched_mins",
    )

    cs, cc = st.columns(2)
    with cs:
        if st.button("💾 Save", type="primary", use_container_width=True):
            for s in schedule:
                if s.get("id") == item_id:
                    s["name"]    = new_name.strip()
                    s["day"]     = SCHEDULE_DAYS.index(new_day)
                    s["skill"]   = new_skill
                    s["minutes"] = int(new_mins)
                    break
            st.session_state.study_schedule = schedule
            sync_config_to_github()
            display = new_name.strip() or add_emoji(new_skill)
            st.toast(f"✅ Updated: {display} on {new_day}", icon="📅")
            st.rerun()
    with cc:
        if st.button("Cancel", use_container_width=True):
            st.rerun()

# ═══════════════════════════════════════════════════════════════
# AI CHAT TRACKER CONTEXT BUILDER
# ═══════════════════════════════════════════════════════════════
def _build_tracker_context(diet_dict: dict, streak: int, level: int,
                            this_week: float, weekly_goal: float,
                            today_mins: float, daily_goal_mins: int) -> str:
    total_mins  = sum(diet_dict.values())
    total_hrs   = total_mins / 60
    xp_pct      = int((total_hrs % 50) / 50 * 100)
    top_skills  = sorted(diet_dict.items(), key=lambda x: x[1], reverse=True)[:3]
    top_str     = ", ".join(f"{k}={v}m" for k, v in top_skills) if top_skills else "none"
    weakest     = min(diet_dict, key=diet_dict.get) if diet_dict else "unknown"
    weak_mins   = diet_dict.get(weakest, 0)
    hrs_to_next = 50 - (total_hrs % 50)

    lines = [
        "English tracker data (use this to answer the user's question):",
        f"• Total: {total_hrs:.1f}h | Level {level} ({xp_pct}% to next, ~{hrs_to_next:.1f}h away)",
        f"• Streak: {streak} days",
        f"• This week: {this_week:.1f}/{weekly_goal}h",
        f"• Today: {today_mins:.0f}/{daily_goal_mins} min",
        f"• Top skills: {top_str}",
        f"• Weakest skill: {weakest} ({weak_mins}m total)",
        f"• Full breakdown (mins): {json.dumps(diet_dict, separators=(',', ':'))}",
    ]
    return "\n".join(lines)

# ═══════════════════════════════════════════════════════════════
# AI SCHEDULE SUGGESTION HELPERS
# ═══════════════════════════════════════════════════════════════
def _is_schedule_request(text: str) -> bool:
    """Return True when the user's message is asking for a study schedule."""
    keywords = [
        "schedule", "jadwal", "plan my week", "study plan", "timetable",
        "routine", "rencana", "buatkan jadwal", "weekly plan", "daily plan",
        "create a plan", "make a plan", "suggest a schedule", "buat jadwal",
    ]
    lower = text.lower()
    return any(k in lower for k in keywords)


def _extract_requested_minutes(text: str) -> tuple:
    """
    Parse duration from the user message.
    Returns (minutes: int|None, is_daily_total: bool).

    "1 jam per hari" / "1 hour per day"  → (60, True)   ← daily total
    "1 jam"          / "1 hour"           → (60, False)  ← per-session
    no match                              → (None, False)
    """
    lower = text.lower()
    time_pat = r'(\d+(?:[.,]\d+)?)\s*(jam|hour|hours|hr|hrs|menit|minutes|minute|mins|min)'
    daily_pat = time_pat + r'\s*(?:per|a|setiap|tiap|each)\s*(?:hari|day)\b'

    def _to_mins(val_str, unit):
        v = float(val_str.replace(",", "."))
        return int(round(v * 60)) if unit in ("jam","hour","hours","hr","hrs") else int(round(v))

    # Check daily-total pattern first ("1 jam per hari")
    m = re.search(daily_pat, lower)
    if m:
        return _to_mins(m.group(1), m.group(2)), True

    # Fallback: plain duration ("1 jam", "60 menit")
    m = re.search(time_pat, lower)
    if m:
        return _to_mins(m.group(1), m.group(2)), False

    return None, False


def _extract_sessions_per_day(text: str) -> tuple:
    """
    Parse how many sessions per day the user wants.
    Returns (count: int, was_explicit: bool).
    was_explicit=False when not stated — caller decides the default.
    """
    lower = text.lower()
    pattern = (
        r'(\d+)\s*'
        r'(?:sesi|sessions?|skills?|jadwal|materi)\s*'
        r'(?:per|a|setiap|tiap|each)\s*'
        r'(?:hari|day)'
    )
    m = re.search(pattern, lower)
    if m:
        return max(1, min(6, int(m.group(1)))), True
    return 3, False  # default 3, NOT explicit


def _build_schedule_ai_prompt(
    user_input: str,
    tracker_ctx: str,
    history_str: str,
    all_skills: list,
) -> str:
    """
    Build the Gemini prompt that returns structured schedule JSON.
    Key logic:
      - "1 jam"                   → 1 session × 60 min/day  (no explicit sessions = default 1)
      - "1 jam per hari"          → 1 session × 60 min/day  (daily total)
      - "3 sesi per hari, 30 min" → 3 sessions × 30 min/day (both explicit)
      - "3 sesi per hari"         → 3 sessions × 30 min/day (sessions explicit, duration default)
    """
    skills_json                          = json.dumps(all_skills)
    raw_mins, is_daily_total             = _extract_requested_minutes(user_input)
    _sessions_count, _sessions_explicit  = _extract_sessions_per_day(user_input)

    # ── Resolve sessions count and per-session minutes ────────
    if raw_mins and is_daily_total and _sessions_explicit:
        # "X jam per hari, N sesi" — divide total across explicit session count
        requested_sessions = _sessions_count
        session_mins       = max(10, raw_mins // requested_sessions)
        requested_mins     = session_mins
        duration_rule = (
            f"CRITICAL RULE: The user wants {raw_mins} minutes TOTAL per day "
            f"across {requested_sessions} session(s). "
            f"Each session MUST have \"minutes\": {session_mins}. Do NOT change this."
        )
        duration_example = str(session_mins)
        minutes_note = (
            f"each session = {session_mins} min "
            f"({requested_sessions} × {session_mins} = {raw_mins} min/day total)"
        )
    elif raw_mins and is_daily_total and not _sessions_explicit:
        # "1 jam per hari" without session count → 1 session of that duration
        requested_sessions = 1
        requested_mins     = raw_mins
        duration_rule = (
            f"CRITICAL RULE: The user wants {raw_mins} minutes per day (1 session). "
            f"Every session MUST have \"minutes\": {raw_mins}. Do NOT change this."
        )
        duration_example = str(raw_mins)
        minutes_note     = f"each session MUST be exactly {raw_mins} minutes"
    elif raw_mins and not _sessions_explicit:
        # "1 jam" with NO sessions count → 1 session of that duration per day
        requested_sessions = 1
        requested_mins     = raw_mins
        duration_rule = (
            f"CRITICAL RULE: The user wants 1 session of {raw_mins} minutes per day. "
            f"Every session MUST have \"minutes\": {raw_mins}. "
            "Do NOT add extra sessions beyond what the Rules say."
        )
        duration_example = str(raw_mins)
        minutes_note     = f"each session MUST be exactly {raw_mins} minutes"
    elif raw_mins and _sessions_explicit:
        # User gave BOTH sessions count AND duration per session
        requested_sessions = _sessions_count
        requested_mins     = raw_mins
        duration_rule = (
            f"CRITICAL RULE: The user requested {raw_mins}-minute sessions. "
            f"Every session MUST have \"minutes\": {raw_mins}. Do NOT change this."
        )
        duration_example = str(raw_mins)
        minutes_note     = f"each session MUST be exactly {raw_mins} minutes"
    else:
        # No duration specified at all
        requested_sessions = _sessions_count
        requested_mins     = None
        duration_rule      = "Use 20-45 min per session unless the user specified otherwise."
        duration_example   = "30"
        minutes_note       = "each session 20-45 min"

    return (
        "You are an English learning coach. The user wants a study schedule.\n\n"
        f"{tracker_ctx}\n\n"
        f"VALID SKILL NAMES — the \"skill\" field MUST be one of these exact strings: {skills_json}\n"
        "Do NOT invent names like \"Review\", \"Practice\", \"Mixed\", \"General\". "
        "Choose the single best matching skill from the list for every session.\n"
        "Day numbers: 0=Monday 1=Tuesday 2=Wednesday 3=Thursday "
        "4=Friday 5=Saturday 6=Sunday\n\n"
        f"{history_str}"
        f"User request: {user_input}\n\n"
        f"{duration_rule}\n\n"
        "Respond ONLY with valid JSON (no markdown fences, no text outside JSON):\n"
        '{"message":"2-sentence motivating intro","schedule":[' +
        f'{{"name":"e.g. Morning Listening","day":0,"skill":"Listening","minutes":{duration_example}}}' +
        "]}\n"
        f"Rules:\n"
        f"- Pick 5 active study days from Mon-Sun (skip 2 rest days)\n"
        f"- Each active day gets exactly {requested_sessions} session(s), each with a DIFFERENT skill\n"
        f"- Do NOT put the same skill twice on the same day\n"
        f"- Prioritise the weakest skill overall but spread all skills across the week\n"
        f"- {minutes_note}\n"
        f"- Only use skill names from the valid list above\n"
        f"- Total = 5 days × {requested_sessions} sessions = {5 * requested_sessions} sessions"
    )



def _parse_ai_schedule(text: str) -> tuple:
    """
    Parse Gemini response that may contain a schedule JSON.
    Returns (message_str, schedule_list).
    schedule_list is [] when the response is not schedule JSON.
    """
    candidates = [
        text.strip(),
        re.sub(r"^```json\s*|```\s*$", "", text.strip(), flags=re.M).strip(),
    ]
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict) and "schedule" in data:
                return str(data.get("message", "")), list(data["schedule"])
        except Exception:
            pass

    # Fallback: look for embedded JSON object containing "schedule"
    m = re.search(r'\{[^{}]*"schedule"\s*:\s*\[[\s\S]*?\]\s*\}', text)
    if m:
        try:
            data = json.loads(m.group())
            return str(data.get("message", "")), list(data.get("schedule", []))
        except Exception:
            pass

    return text.strip(), []


def _resolve_skill(raw: str, all_skills: list) -> str:
    """
    Map an AI-generated skill name to the closest valid entry in all_skills.
    Priority: exact → case-insensitive → substring → first-word → weighted char overlap.
    Never blindly returns all_skills[0].
    """
    if not all_skills:
        return "Listening"
    if raw in all_skills:
        return raw
    lower_raw = raw.lower()
    # Case-insensitive exact
    for s in all_skills:
        if s.lower() == lower_raw:
            return s
    # Valid skill contained in raw  e.g. "Vocabulary" in "Vocabulary & Review"
    for s in all_skills:
        if s.lower() in lower_raw:
            return s
    # Raw contained in a valid skill
    for s in all_skills:
        if lower_raw in s.lower():
            return s
    # First-word match
    raw_first = lower_raw.split()[0] if lower_raw.split() else ""
    for s in all_skills:
        if s.lower().startswith(raw_first):
            return s
    # Weighted character-set overlap — normalised by skill name length
    def _score(skill, text):
        s_chars = set(skill.lower().replace(" ", ""))
        t_chars = set(text.lower().replace(" ", ""))
        return len(s_chars & t_chars) / max(len(s_chars), 1)
    return max(all_skills, key=lambda s: _score(s, raw))


def _render_schedule_cards(schedule_items: list, all_skills: list, msg_idx: int):
    """
    Render AI-suggested schedule sessions grouped by day.
    Each day gets a header, then its sessions with individual ➕ buttons.
    A bulk Add All button appears at the bottom.
    """
    if not schedule_items:
        return

    accent = st.session_state.accent_color

    # ── Normalise & resolve all items first ───────────────────
    normalised = []
    for item in schedule_items:
        skill   = _resolve_skill(item.get("skill", "General"), all_skills)
        day_raw = item.get("day", 0)
        day_idx = (
            SCHEDULE_DAYS.index(day_raw)
            if isinstance(day_raw, str) and day_raw in SCHEDULE_DAYS
            else int(day_raw) % 7
        )
        normalised.append({
            "skill":   skill,
            "day":     day_idx,
            "minutes": int(item.get("minutes", 30)),
            "name":    item.get("name", "").strip(),
        })

    # ── Group by day, preserving Mon→Sun order ────────────────
    from collections import defaultdict
    by_day = defaultdict(list)
    for item in normalised:
        by_day[item["day"]].append(item)
    sorted_days = sorted(by_day.keys())   # 0=Mon … 6=Sun

    existing_schedule = st.session_state.study_schedule
    existing_keys = {
        (s.get("skill"), int(s.get("day", 0)), int(s.get("minutes", 0)))
        for s in existing_schedule
    }

    st.markdown(
        "<div style='margin-top:10px;font-size:0.8rem;opacity:0.65;"
        "font-weight:700;letter-spacing:0.07em;text-transform:uppercase;"
        "margin-bottom:8px'>📅 Suggested Schedule</div>",
        unsafe_allow_html=True,
    )

    # ── Render day-by-day ─────────────────────────────────────
    global_i = 0   # unique key counter across all days
    for day_idx in sorted_days:
        day_items = by_day[day_idx]
        day_name  = SCHEDULE_DAYS[day_idx]
        day_mins  = sum(it["minutes"] for it in day_items)

        # Day header
        st.markdown(
            f"<div style='font-size:0.82rem;font-weight:700;"
            f"opacity:0.9;margin:10px 0 4px 0;"
            f"border-bottom:1px solid {accent}44;padding-bottom:3px'>"
            f"📆 {day_name} "
            f"<span style='font-size:0.72rem;opacity:0.6;font-weight:400'>"
            f"— {len(day_items)} session(s) · {day_mins} min total</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        for item in day_items:
            skill   = item["skill"]
            mins    = item["minutes"]
            name    = item["name"]
            display = name or add_emoji(skill)
            already = (skill, day_idx, mins) in existing_keys

            col_card, col_btn = st.columns([5, 1])
            with col_card:
                added_badge = (
                    f"&nbsp;<span style='font-size:0.70rem;color:{accent}'>✅ Added</span>"
                    if already else ""
                )
                st.markdown(
                    f"<div style='background:rgba(255,255,255,0.06);"
                    f"border-radius:8px;padding:7px 12px;"
                    f"border-left:3px solid {accent};margin:2px 0'>"
                    f"<b>{display}</b>&nbsp;"
                    f"<span style='font-size:0.74rem;opacity:0.60'>"
                    f"{add_emoji(skill)} · {mins} min"
                    f"</span>{added_badge}</div>",
                    unsafe_allow_html=True,
                )
            with col_btn:
                if not already:
                    if st.button(
                        "➕",
                        key=f"sched_add_{msg_idx}_{global_i}",
                        use_container_width=True,
                        help=f"Add {display} on {day_name}",
                    ):
                        st.session_state.study_schedule.append({
                            "id":      str(uuid.uuid4())[:8],
                            "name":    name,
                            "day":     day_idx,
                            "skill":   skill,
                            "minutes": mins,
                        })
                        sync_config_to_github()
                        st.toast(f"✅ {display} added to {day_name}!", icon="📅")
                        st.rerun()
            global_i += 1

    # ── Add All button ────────────────────────────────────────
    addable = [
        item for item in normalised
        if (item["skill"], item["day"], item["minutes"]) not in existing_keys
    ]
    if len(addable) > 1:
        st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)
        if st.button(
            f"➕ Add All {len(addable)} Sessions to Schedule",
            key=f"sched_add_all_{msg_idx}",
            type="primary",
            use_container_width=True,
        ):
            for item in addable:
                st.session_state.study_schedule.append({
                    "id":      str(uuid.uuid4())[:8],
                    "name":    item["name"],
                    "day":     item["day"],
                    "skill":   item["skill"],
                    "minutes": item["minutes"],
                })
            sync_config_to_github()
            st.toast(f"✅ Added {len(addable)} sessions to your schedule!", icon="📅")
            st.rerun()


# ═══════════════════════════════════════════════════════════════
# FREE-FORM AI CHAT (with schedule detection)
# ═══════════════════════════════════════════════════════════════
@st.fragment
def render_ai_chat(diet_dict: dict, streak: int = 0, level: int = 1,
                   this_week: float = 0.0, today_mins: float = 0.0,
                   all_skills: list = None):
    accent      = st.session_state.accent_color
    _all_skills = all_skills or []

    hcol, bcol = st.columns([4, 1])
    with hcol:
        st.markdown("### 💬 Chat with Your AI Coach")
        st.caption(
            "Ask anything — or try *'Create a weekly schedule for me!'* "
            "to get a plan you can add directly. Your full tracker data is shared."
        )
    with bcol:
        if st.session_state.ai_chat_history:
            if st.button("🗑️ Clear", use_container_width=True,
                         help="Clear chat history"):
                st.session_state.ai_chat_history = []
                st.rerun()

    if not st.session_state.gemini_key:
        st.info("💡 Add your Gemini API key in the sidebar to use this feature.")
        return

    # ── Render existing history ───────────────────────────────
    for msg_idx, msg in enumerate(st.session_state.ai_chat_history):
        with st.chat_message(msg["role"],
                             avatar="🧑" if msg["role"] == "user" else "🤖"):
            st.markdown(msg["content"])
            # Re-render schedule cards so they survive page refreshes
            if msg["role"] == "assistant" and msg.get("schedule_data"):
                _render_schedule_cards(msg["schedule_data"], _all_skills, msg_idx)

    # ── Suggestion chips (shown only on empty history) ────────
    if not st.session_state.ai_chat_history:
        st.markdown(
            '<div style="opacity:0.6;font-size:0.84rem;margin-bottom:8px">'
            "💡 Try asking:</div>",
            unsafe_allow_html=True,
        )
        suggestions = [
            "What should I focus on this week?",
            "Create a weekly schedule for me",
            "How many hours until my next level?",
            "Why is my grammar weak and how do I fix it?",
        ]
        scols = st.columns(2)
        for i, s in enumerate(suggestions):
            if scols[i % 2].button(s, key=f"suggest_{i}", use_container_width=True):
                st.session_state["_chat_prefill"] = s
                st.rerun()

    # ── Chat input ────────────────────────────────────────────
    prefill    = st.session_state.pop("_chat_prefill", "")
    user_input = st.chat_input(
        "Ask your coach anything… e.g. 'Make me a weekly study schedule'",
        key="ai_chat_input",
    )
    if not user_input and prefill:
        user_input = prefill

    if not user_input:
        return

    allowed, reason, _ = _check_ai_rate_limit()
    if not allowed:
        st.toast(f"⏳ {reason}", icon="🚦")
        return

    st.session_state.ai_chat_history.append({"role": "user", "content": user_input})

    tracker_ctx = _build_tracker_context(
        diet_dict, streak, level, this_week,
        float(st.session_state.weekly_goal),
        today_mins, int(st.session_state.daily_goal_mins),
    )

    history_window = st.session_state.ai_chat_history[-9:-1]
    history_str = ""
    if history_window:
        history_str = "Previous conversation:\n" + "\n".join(
            f"{'User' if m['role'] == 'user' else 'Coach'}: {m['content']}"
            for m in history_window
        ) + "\n\n"

    # ── Route to schedule prompt or standard prompt ───────────
    is_sched_req = _is_schedule_request(user_input)

    if is_sched_req:
        full_prompt = _build_schedule_ai_prompt(
            user_input, tracker_ctx, history_str, _all_skills
        )
    else:
        full_prompt = (
            "You are a helpful English learning coach. "
            "Answer concisely (≤150 words unless a study plan is requested). "
            "Be encouraging and specific.\n\n"
            f"{tracker_ctx}\n\n"
            f"{history_str}"
            f"User: {user_input}\n"
            "Coach:"
        )

    schedule_data = []
    with st.chat_message("assistant", avatar="🤖"):
        with st.spinner("Thinking…"):
            try:
                genai.configure(api_key=st.session_state.gemini_key)
                model    = genai.GenerativeModel("gemini-2.5-flash-lite")
                response = model.generate_content(full_prompt)
                raw_text = response.text.strip()
                st.session_state.last_ai_time    = now_wib()
                st.session_state.ai_calls_today += 1

                if is_sched_req:
                    reply, schedule_data = _parse_ai_schedule(raw_text)
                    # If parse completely fails, fall back to raw text
                    if not reply and not schedule_data:
                        reply         = raw_text
                        schedule_data = []
                else:
                    reply         = raw_text
                    schedule_data = []

            except Exception as e:
                reply         = f"⚠️ Error: {e}"
                schedule_data = []

        st.markdown(reply)
        # Render cards for the brand-new assistant message
        if schedule_data:
            _render_schedule_cards(
                schedule_data,
                _all_skills,
                len(st.session_state.ai_chat_history),  # unique per-message index
            )

    st.session_state.ai_chat_history.append({
        "role":          "assistant",
        "content":       reply,
        "schedule_data": schedule_data,  # persisted so cards survive refresh
    })
    # Keep history window bounded
    st.session_state.ai_chat_history = st.session_state.ai_chat_history[-20:]
    st.rerun()

# ═══════════════════════════════════════════════════════════════
# MULTI-SKILL LOG DIALOG
# ═══════════════════════════════════════════════════════════════
@st.dialog("➕ Log New Study Session")
def log_session_dialog(available_skills):
    if st.session_state.log_rows is None:
        st.session_state.log_rows = [
            {"skill": available_skills[0], "minutes": 30}
        ]

    d = st.date_input("Date", today_wib())
    n = st.text_input("Notes (applies to all skills logged)", placeholder="e.g. Focused on past tense")

    st.markdown("**Skills to log:**")

    hc1, hc2, hc3 = st.columns([3, 2, 1])
    hc1.caption("Skill")
    hc2.caption("Minutes")
    hc3.caption("")

    rows       = st.session_state.log_rows
    delete_idx = None

    for i, row in enumerate(rows):
        c1, c2, c3 = st.columns([3, 2, 1])
        skill_idx = (available_skills.index(row["skill"])
                     if row["skill"] in available_skills else 0)
        with c1:
            st.selectbox(
                f"skill_{i}", available_skills,
                index=skill_idx,
                format_func=add_emoji,
                key=f"log_skill_{i}",
                label_visibility="collapsed",
            )
        with c2:
            st.number_input(
                f"mins_{i}", min_value=1, max_value=600,
                value=row["minutes"],
                key=f"log_mins_{i}",
                label_visibility="collapsed",
            )
        with c3:
            if len(rows) > 1:
                if st.button("🗑️", key=f"log_del_{i}", help="Remove this row"):
                    delete_idx = i

    if delete_idx is not None:
        st.session_state.log_rows.pop(delete_idx)
        st.rerun()

    ba, br, bs = st.columns([1, 1, 2])

    with ba:
        if st.button("➕ Add Skill", use_container_width=True):
            st.session_state.log_rows.append(
                {"skill": available_skills[0], "minutes": 30}
            )
            st.rerun()

    with br:
        if st.button("🔄 Reset", use_container_width=True):
            st.session_state.log_rows = [
                {"skill": available_skills[0], "minutes": 30}
            ]
            st.rerun()

    with bs:
        if st.button("💾 Log & Sync", type="primary", use_container_width=True):
            new_rows_data = []
            for i in range(len(st.session_state.log_rows)):
                skill   = st.session_state.get(f"log_skill_{i}", available_skills[0])
                minutes = int(st.session_state.get(f"log_mins_{i}", 30))
                new_rows_data.append({
                    "Date":       pd.Timestamp(d),
                    "Skill":      skill,
                    "Time Spent": minutes,
                    "Notes":      n,
                })

            new_df     = pd.DataFrame(new_rows_data)
            updated_df = pd.concat([st.session_state.df, new_df], ignore_index=True)

            with st.spinner("Saving to GitHub…"):
                sha = save_to_github(
                    st.session_state.saved_token,
                    st.session_state.saved_repo,
                    "data.csv",
                    updated_df,
                )

            if sha:
                st.session_state.df       = updated_df
                st.session_state.file_sha = sha
                st.session_state.log_rows = None
                _invalidate_derived_cache()
                load_data_from_github.clear()
                total_logged = sum(r["Time Spent"] for r in new_rows_data)
                summary = " · ".join(
                    f"{add_emoji(r['Skill'])} {r['Time Spent']}m"
                    for r in new_rows_data
                )
                st.toast(
                    f"✅ Logged {len(new_rows_data)} skill(s) · {total_logged} min total\n{summary}",
                    icon="📚",
                )
                st.rerun()
            else:
                st.warning("⚠️ Entry NOT saved. Fix the error above and try again.")

    if len(rows) > 1:
        total_preview = sum(
            int(st.session_state.get(f"log_mins_{i}", row["minutes"]))
            for i, row in enumerate(rows)
        )
        st.caption(f"📊 Total: **{total_preview} minutes** across {len(rows)} skills")

# ═══════════════════════════════════════════════════════════════
# STUDY SCHEDULE WIDGET
# ═══════════════════════════════════════════════════════════════
def render_schedule_widget(all_skills: list):
    schedule = st.session_state.study_schedule
    if not schedule:
        return

    today     = today_wib()
    today_day = today.weekday()  # 0=Mon … 6=Sun
    today_items = [item for item in schedule if item.get("day") == today_day]
    if not today_items:
        return

    done_ids   = _get_schedule_done_from_data(today_items, today)
    done_count = len(done_ids)
    accent     = st.session_state.accent_color

    with st.expander(
        f"📅 Today's Schedule — {SCHEDULE_DAYS[today_day]}  "
        f"({done_count}/{len(today_items)} done)",
        expanded=True,
    ):
        for item in today_items:
            item_id    = item.get("id", "")
            is_done    = item_id in done_ids
            skill_name = item.get("skill", "General")
            plan_mins  = item.get("minutes", 30)
            item_label = item.get("name", "").strip() or add_emoji(skill_name)

            if is_done:
                st.markdown(
                    f"<div style='opacity:0.55;text-decoration:line-through;"
                    f"padding:8px 4px;'>✅ {item_label} — {plan_mins} min</div>",
                    unsafe_allow_html=True,
                )
            else:
                col_chk, col_label, col_mins = st.columns([1, 5, 2])

                with col_chk:
                    checked = st.checkbox(
                        "",
                        value=False,
                        key=f"sched_chk_{item_id}",
                        label_visibility="collapsed",
                    )
                with col_label:
                    st.markdown(
                        f"**{item_label}**"
                        + (
                            f"  \n<span style='font-size:0.78rem;opacity:0.6'>"
                            f"{add_emoji(skill_name)}</span>"
                            if item.get("name") else ""
                        ),
                        unsafe_allow_html=True,
                    )
                with col_mins:
                    override_mins = st.number_input(
                        "min",
                        min_value=1,
                        max_value=600,
                        value=plan_mins,
                        key=f"sched_override_{item_id}",
                        label_visibility="collapsed",
                        help=f"Planned: {plan_mins} min — override for today only",
                    )

                if checked:
                    actual_mins = int(
                        st.session_state.get(f"sched_override_{item_id}", plan_mins)
                    )
                    new_row = pd.DataFrame({
                        "Date":       [pd.Timestamp(today)],
                        "Skill":      [skill_name],
                        "Time Spent": [actual_mins],
                        "Notes":      [f"📅 Auto-logged: {item_id}"],
                    })
                    updated_df = pd.concat(
                        [st.session_state.df, new_row], ignore_index=True
                    )
                    with st.spinner(f"Logging {item_label}…"):
                        sha = save_to_github(
                            st.session_state.saved_token,
                            st.session_state.saved_repo,
                            "data.csv",
                            updated_df,
                        )
                    if sha:
                        st.session_state.df       = updated_df
                        st.session_state.file_sha = sha
                        _invalidate_derived_cache()
                        load_data_from_github.clear()
                        diff_note = (
                            f" (override from {plan_mins} min)"
                            if actual_mins != plan_mins else ""
                        )
                        st.toast(
                            f"✅ {item_label} — {actual_mins} min logged!{diff_note}",
                            icon="📅",
                        )
                        st.rerun()
                    else:
                        st.error("❌ Failed to save. Check your GitHub settings.")

        # ── Progress bar ──────────────────────────────────────
        if today_items:
            prog = done_count / len(today_items)
            st.markdown(
                f"""<div style="margin-top:8px">
                <div style="font-size:0.78rem;opacity:0.7;margin-bottom:4px">
                    Schedule progress
                </div>
                <div style="background:rgba(255,255,255,0.12);border-radius:999px;
                            height:8px;overflow:hidden;">
                    <div style="width:{prog * 100:.0f}%;height:100%;
                                background:{accent};border-radius:999px;
                                transition:width 0.4s ease"></div>
                </div></div>""",
                unsafe_allow_html=True,
            )
            if done_count == len(today_items) and len(today_items) > 0:
                st.success("🎉 All done for today! Great work!")

# ═══════════════════════════════════════════════════════════════
# SIDEBAR
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

    st.toggle("☀️ Light Mode",        key="light_mode",      on_change=sync_config_to_github)
    st.slider("Weekly Goal (Hours)",  1, 40,  key="weekly_goal",      on_change=sync_config_to_github)
    st.slider("Daily Goal (Minutes)", 10, 300, key="daily_goal_mins", on_change=sync_config_to_github)
    st.checkbox("🧘 Zen Mode",         key="zen_mode")
    st.checkbox("🔄 Auto AI Coach",    key="ask_ai_auto",     on_change=sync_config_to_github)

    st.divider()

    _today_str    = today_wib().isoformat()
    _cap          = int(st.session_state.get("ai_daily_cap_setting", AI_DAILY_CAP))
    display_calls = (st.session_state.ai_calls_today
                     if st.session_state.ai_call_date == _today_str else 0)
    _ratio        = display_calls / _cap if _cap > 0 else 0
    _gauge_color, _gauge_icon = (
        ("#00CC96", "🟢") if _ratio < 0.5 else
        ("#FFA500", "🟡") if _ratio < 0.85 else
        ("#FF4B4B", "🔴")
    )
    st.markdown(f"**{_gauge_icon} AI Budget: {display_calls} / {_cap}**")
    st.markdown(f"""
    <div style="background:rgba(255,255,255,0.12);border-radius:999px;
                height:10px;overflow:hidden;margin-bottom:4px">
      <div style="width:{min(_ratio * 100, 100):.0f}%;height:100%;
                  background:{_gauge_color};border-radius:999px;
                  transition:width 0.4s ease"></div>
    </div>""", unsafe_allow_html=True)

    _now_sb      = now_wib()
    _midnight_sb = datetime.combine(_now_sb.date() + timedelta(days=1),
                                    datetime.min.time(), tzinfo=_WIB)
    _sl = int((_midnight_sb - _now_sb).total_seconds())
    st.caption(f"⏰ Resets in {_sl // 3600}h {(_sl % 3600) // 60}m (WIB)")
    if display_calls >= _cap:
        st.warning("Daily AI limit reached.")
    st.checkbox("🛠 Debug Timings", key="debug_perf")

# ═══════════════════════════════════════════════════════════════
# FRAGMENT: Metrics
# ═══════════════════════════════════════════════════════════════
@st.fragment
def render_metrics(total_hrs, level, xp, this_week, streak):
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Level",     f"Lvl {level}")
    m2.metric("Total",     f"{total_hrs:.1f}h")
    m3.metric("Streak",    f"{streak} Days")
    m4.metric("This Week", f"{this_week:.1f}/{st.session_state.weekly_goal}h")
    pct    = int(xp * 100)
    accent = st.session_state.accent_color
    st.markdown(f"""
    <style>:root{{--xp-target:{pct}%;}}</style>
    <div style="font-size:0.82rem;opacity:0.8;margin-top:8px">
        ✨ Progress to Level {level + 1} &nbsp;·&nbsp; {pct}%
    </div>
    <div class="xp-bar-outer">
        <div class="xp-bar-inner" style="width:{pct}%;background:{accent};"></div>
    </div>
    """, unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
# FRAGMENT: AI Coach (quick-tip panel, separate from chat)
# ═══════════════════════════════════════════════════════════════
@st.fragment
def render_ai_coach(diet_dict, all_skills, streak=0, level=1, this_week=0.0):
    _today_local  = today_wib().isoformat()
    _cap_local    = int(st.session_state.get("ai_daily_cap_setting", AI_DAILY_CAP))
    display_calls = (st.session_state.ai_calls_today
                     if st.session_state.ai_call_date == _today_local else 0)

    skill_options  = ["All Skills"] + all_skills
    current_target = st.session_state.ai_target_skill
    if current_target not in skill_options:
        current_target = "All Skills"
    st.session_state.ai_target_skill = st.selectbox(
        "🎯 Coach focus:", skill_options,
        index=skill_options.index(current_target),
        format_func=lambda x: x if x == "All Skills" else add_emoji(x),
        key="ai_skill_select",
    )

    def _fire_ai(monthly_review=False):
        last_tip = (st.session_state.last_ai_response.get("tip", "")
                    if st.session_state.last_ai_response else "")
        resp = get_ai_recommendation(
            api_key=st.session_state.gemini_key, skill_totals=diet_dict,
            target_skill=st.session_state.ai_target_skill,
            streak=streak, level=level, last_tip=last_tip,
            weekly_goal=float(st.session_state.weekly_goal),
            this_week=this_week, monthly_review=monthly_review,
        )
        st.session_state.last_ai_response   = resp
        st.session_state.last_ai_rec        = resp.get("tip", "")
        st.session_state.last_diet_hash     = _diet_hash(diet_dict)
        st.session_state.last_diet_snapshot = dict(diet_dict)
        if monthly_review:
            st.session_state.last_monthly_review = today_wib().isoformat()
        entry = {
            "time":     now_wib().strftime("%Y-%m-%d %H:%M WIB"),
            "skill":    st.session_state.ai_target_skill,
            "tip":      resp.get("tip", ""),
            "exercise": resp.get("exercise", ""),
            "resource": resp.get("resource", ""),
            "monthly":  monthly_review,
        }
        st.session_state.ai_history = ([entry] + st.session_state.ai_history)[:5]

    def _show_cooldown(wait_secs, reason):
        if wait_secs > 0:
            st.markdown(f'<div class="cooldown-label">⏳ {reason}</div>',
                        unsafe_allow_html=True)
            st.progress(
                max(0.0, min(1.0, 1.0 - (wait_secs / AI_MIN_INTERVAL))),
                text=f"Cooling down — {wait_secs:.0f}s",
            )
        else:
            st.caption(f"⏳ {reason}")

    if st.session_state.ask_ai_auto and st.session_state.gemini_key:
        current_hash = _diet_hash(diet_dict)
        data_changed = current_hash != st.session_state.last_diet_hash
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
                    st.toast(f"⏳ {reason}", icon="🤖")
                _show_cooldown(wait_secs, reason)
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
                    st.toast(f"⏳ {reason}", icon="🚦")
                    _show_cooldown(wait_secs, reason)
        with col_monthly:
            _last_mr    = st.session_state.get("last_monthly_review", "")
            _can_review = (not _last_mr) or (
                (today_wib() - datetime.fromisoformat(_last_mr).date()).days >= 30
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

    accent = st.session_state.accent_color
    resp   = st.session_state.last_ai_response
    if resp:
        tip        = resp.get("tip", "")
        exercise   = resp.get("exercise", "")
        resource   = resp.get("resource", "")
        is_monthly = (st.session_state.ai_history[0].get("monthly", False)
                      if st.session_state.ai_history else False)
        with st.expander(
            "📅 Monthly Review" if is_monthly else "💡 Coach's Insight",
            expanded=True,
        ):
            if tip:
                st.markdown(
                    f'<div class="ai-card" style="--accent-col:{accent}">'
                    f"💡 <strong>Tip</strong><br>{tip}</div>",
                    unsafe_allow_html=True,
                )
            if exercise:
                st.markdown(
                    f'<div class="ai-card" style="--accent-col:{accent}">'
                    f"🏋️ <strong>Exercise</strong><br>{exercise}</div>",
                    unsafe_allow_html=True,
                )
            if resource:
                st.markdown(
                    f'<div class="ai-card" style="--accent-col:{accent}">'
                    f"🔗 <strong>Resource</strong><br>{resource}</div>",
                    unsafe_allow_html=True,
                )
            if st.session_state.last_ai_time:
                st.caption(
                    f"🕐 {st.session_state.last_ai_time.strftime('%H:%M:%S')}"
                    f"  ·  Calls today: {display_calls}/{_cap_local}"
                )
    elif st.session_state.last_ai_rec:
        with st.expander("💡 Coach's Insight", expanded=True):
            st.write(st.session_state.last_ai_rec)

    if st.session_state.ai_history:
        with st.expander(
            f"📜 Coaching History ({len(st.session_state.ai_history)} tip(s))",
            expanded=False,
        ):
            for entry in st.session_state.ai_history:
                badge = " 📅 Monthly" if entry.get("monthly") else ""
                st.markdown(f"**{entry['time']}** · *{entry.get('skill', '?')}*{badge}")
                if entry.get("tip"):      st.write(f"💡 {entry['tip']}")
                if entry.get("exercise"): st.write(f"🏋️ {entry['exercise']}")
                if entry.get("resource"): st.write(f"🔗 {entry['resource']}")
                st.divider()

# ═══════════════════════════════════════════════════════════════
# FRAGMENT: Dashboard Tab
# ═══════════════════════════════════════════════════════════════
@st.fragment
def render_tab_dashboard(df, diet, accent_color, today_mins, daily_goal_mins):
    mobile = st.session_state.get("mobile_mode", False)
    if mobile:
        for fig in [
            build_area_chart(df, accent_color, "Study Mountain"),
            build_pie_chart(tuple(diet.index), tuple(diet.values)),
            build_heatmap(df, accent_color),
            build_daily_ring(today_mins, daily_goal_mins, accent_color),
            build_skill_bars(diet, accent_color),
        ]:
            st.plotly_chart(fig, use_container_width=True)
    else:
        c1, c2 = st.columns([2, 1])
        with c1:
            st.plotly_chart(
                build_area_chart(df, accent_color, "Study Mountain"),
                use_container_width=True,
            )
        with c2:
            st.plotly_chart(
                build_pie_chart(tuple(diet.index), tuple(diet.values)),
                use_container_width=True,
            )
        c3, c4 = st.columns([3, 1])
        with c3:
            st.plotly_chart(build_heatmap(df, accent_color), use_container_width=True)
        with c4:
            st.plotly_chart(
                build_daily_ring(today_mins, daily_goal_mins, accent_color),
                use_container_width=True,
            )
        st.plotly_chart(build_skill_bars(diet, accent_color), use_container_width=True)

# ═══════════════════════════════════════════════════════════════
# FRAGMENT: History Tab
# ═══════════════════════════════════════════════════════════════
@st.fragment
def render_tab_history(all_skills: list):
    current_df = st.session_state.df

    st.info("💡 Edit or delete rows, then press **💾 Save Changes** to sync to GitHub.")

    _date_col = (current_df["Date"].dt.strftime("%Y-%m-%d")
                 if pd.api.types.is_datetime64_any_dtype(current_df["Date"])
                 else current_df["Date"])
    csv_bytes = current_df.assign(Date=_date_col).to_csv(index=False).encode("utf-8")
    st.download_button(
        label="⬇️ Export CSV", data=csv_bytes,
        file_name=f"english_pro_{today_wib().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )

    edited_df = st.data_editor(
        current_df,
        column_config={
            "Date":  st.column_config.DateColumn(),
            "Skill": st.column_config.SelectboxColumn(options=all_skills),
        },
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        key="history_editor",
    )

    if st.button("💾 Save Changes to GitHub", type="primary", use_container_width=True):
        if "Date" in edited_df.columns:
            edited_df["Date"] = pd.to_datetime(edited_df["Date"], errors="coerce")
        if "Time Spent" in edited_df.columns:
            edited_df["Time Spent"] = (
                pd.to_numeric(edited_df["Time Spent"], errors="coerce")
                .fillna(0).astype(int)
            )
        edited_df = edited_df.dropna(subset=["Date"]).reset_index(drop=True)

        with st.spinner("Saving…"):
            sha = save_to_github(
                st.session_state.saved_token,
                st.session_state.saved_repo,
                "data.csv",
                edited_df,
            )
        if sha:
            st.session_state.df       = edited_df
            st.session_state.file_sha = sha
            _invalidate_derived_cache()
            load_data_from_github.clear()
            st.toast("✅ Changes saved to GitHub!", icon="💾")
            st.rerun()
        else:
            st.error("❌ Save failed. Check your GitHub token and repo in the sidebar.")

# ═══════════════════════════════════════════════════════════════
# FRAGMENT: Trophies Tab
# ═══════════════════════════════════════════════════════════════
@st.fragment
def render_tab_trophies(total_hrs, streak, unique_skills, level, accent_color):
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

    today_iso = today_wib().isoformat()
    if st.session_state.milestone_claimed_date != today_iso:
        if st.button(f"🎉 Claim: {st.session_state.milestone_reward}",
                     use_container_width=True):
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
            if is_unlocked else
            '<div style="font-size:0.65rem;opacity:0.5;margin-top:4px">🔒 Locked</div>'
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
# ═══════════════════════════════════════════════════════════════
@st.fragment
def render_tab_settings(all_skills: list):
    # ── AI Budget ─────────────────────────────────────────────
    st.subheader("🤖 AI Budget")
    st.slider(
        "Daily AI Call Limit", min_value=1, max_value=AI_DAILY_CAP,
        key="ai_daily_cap_setting",
        help=f"Hard ceiling is {AI_DAILY_CAP}/day (Gemini Free Tier).",
        on_change=sync_config_to_github,
    )
    st.toggle(
        "🌿 Eco Mode — only call AI when skill data changes by 5%+",
        key="eco_mode", on_change=sync_config_to_github,
    )
    if st.session_state.eco_mode:
        st.caption("Eco Mode ON · Skips calls when skill totals haven't shifted meaningfully.")

    st.divider()

    # ── Layout ────────────────────────────────────────────────
    st.subheader("📱 Layout")
    st.toggle(
        "📱 Mobile-Friendly Layout (single column)",
        key="mobile_mode", on_change=sync_config_to_github,
    )

    st.divider()

    # ── Custom Skills ─────────────────────────────────────────
    st.subheader("⚙️ Custom Skills Manager")
    st.caption("Add skills beyond the default six. Saved to your GitHub config.json.")

    custom = list(st.session_state.custom_skills or [])
    col_input, col_btn = st.columns([3, 1])
    with col_input:
        new_skill = st.text_input(
            "New skill name", placeholder="e.g. Pronunciation",
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
        "Always available: 🎧 Listening, 🗣️ Speaking, 📖 Reading, "
        "✍️ Writing, 📝 Grammar, 💬 Vocabulary."
    )

    # ── Study Schedule Manager ────────────────────────────────
    st.divider()
    st.subheader("📅 Study Schedule")
    st.caption(
        "Create your weekly study schedule. Each session appears as a checkbox on the "
        "dashboard — tick it to auto-log. You can also ask the AI in the Chat tab to "
        "generate a schedule and add sessions directly from there!"
    )

    schedule  = list(st.session_state.study_schedule)
    accent    = st.session_state.accent_color
    today_day = today_wib().weekday()

    # ── Add new session form ──────────────────────────────────
    st.markdown("**➕ Add new session:**")
    na, nb, nc, nd, ne = st.columns([2, 2, 2, 1, 1])
    with na:
        new_sched_name = st.text_input(
            "Session name",
            placeholder="e.g. Morning Practice",
            key="sched_new_name",
            label_visibility="collapsed",
        )
    with nb:
        new_day = st.selectbox(
            "Day", SCHEDULE_DAYS,
            key="sched_new_day",
            label_visibility="collapsed",
        )
    with nc:
        new_sched_skill = st.selectbox(
            "Skill", all_skills,
            key="sched_new_skill",
            format_func=add_emoji,
            label_visibility="collapsed",
        )
    with nd:
        new_sched_mins = st.number_input(
            "Min", min_value=5, max_value=300, value=30,
            key="sched_new_mins",
            label_visibility="collapsed",
        )
    with ne:
        if st.button("➕ Add", use_container_width=True, key="sched_add_btn"):
            new_item = {
                "id":      str(uuid.uuid4())[:8],
                "name":    new_sched_name.strip(),
                "day":     SCHEDULE_DAYS.index(new_day),
                "skill":   new_sched_skill,
                "minutes": int(new_sched_mins),
            }
            schedule.append(new_item)
            st.session_state.study_schedule = schedule
            sync_config_to_github()
            display = new_sched_name.strip() or add_emoji(new_sched_skill)
            st.toast(f"✅ Added: {display} on {new_day}", icon="📅")
            st.rerun()

    st.markdown("---")

    # ── Schedule grouped by day ───────────────────────────────
    if schedule:
        st.markdown("**Your weekly schedule:**")

        for day_idx, day_name in enumerate(SCHEDULE_DAYS):
            day_items = [item for item in schedule if item.get("day") == day_idx]
            if not day_items:
                continue

            today_badge = " 📍 *Today*" if day_idx == today_day else ""
            day_total   = sum(i.get("minutes", 0) for i in day_items)

            st.markdown(
                f"**{day_name}**{today_badge} "
                f"<span style='font-size:0.8rem;opacity:0.6'>"
                f"— {len(day_items)} session(s) · {day_total} min total</span>",
                unsafe_allow_html=True,
            )

            for item in day_items:
                item_name = item.get("name", "").strip()
                display   = item_name or add_emoji(item["skill"])
                sub_label = f"{add_emoji(item['skill'])} · {item['minutes']} min"

                ic1, ic2, ic3 = st.columns([6, 1, 1])
                with ic1:
                    st.markdown(
                        f"**{display}**  \n"
                        f"<span style='font-size:0.78rem;opacity:0.65'>{sub_label}</span>",
                        unsafe_allow_html=True,
                    )
                with ic2:
                    if st.button("✏️", key=f"edit_sched_{item['id']}",
                                 help="Edit this session"):
                        edit_schedule_dialog(item["id"], all_skills)
                with ic3:
                    if st.button("🗑️", key=f"del_sched_{item['id']}",
                                 help="Delete this session"):
                        schedule = [s for s in schedule if s.get("id") != item.get("id")]
                        st.session_state.study_schedule = schedule
                        sync_config_to_github()
                        st.rerun()

            # ── Copy day to another day ───────────────────────
            with st.expander(f"📋 Copy all {day_name} sessions to another day…",
                             expanded=False):
                copy_targets = [d for d in SCHEDULE_DAYS if d != day_name]
                cc1, cc2 = st.columns([3, 1])
                with cc1:
                    copy_target = st.selectbox(
                        "Copy to", copy_targets,
                        key=f"copy_target_{day_idx}",
                        label_visibility="collapsed",
                    )
                with cc2:
                    if st.button(
                        f"📋 Copy → {copy_target[:3]}",
                        key=f"copy_day_{day_idx}",
                        use_container_width=True,
                    ):
                        target_idx     = SCHEDULE_DAYS.index(copy_target)
                        already_exists = [
                            (s["skill"], s.get("minutes"), s.get("name", ""))
                            for s in schedule if s.get("day") == target_idx
                        ]
                        copied_count = 0
                        for src_item in day_items:
                            duplicate = any(
                                e[0] == src_item["skill"]
                                and e[1] == src_item.get("minutes")
                                and e[2] == src_item.get("name", "")
                                for e in already_exists
                            )
                            if duplicate:
                                continue
                            new_copy = {
                                "id":      str(uuid.uuid4())[:8],
                                "name":    src_item.get("name", ""),
                                "day":     target_idx,
                                "skill":   src_item["skill"],
                                "minutes": src_item["minutes"],
                            }
                            schedule.append(new_copy)
                            already_exists.append((
                                new_copy["skill"],
                                new_copy["minutes"],
                                new_copy.get("name", ""),
                            ))
                            copied_count += 1

                        st.session_state.study_schedule = schedule
                        sync_config_to_github()
                        if copied_count > 0:
                            st.toast(
                                f"✅ {copied_count} session(s) copied to {copy_target}",
                                icon="📋",
                            )
                        else:
                            st.info("All sessions already exist on that day — nothing copied.")
                        st.rerun()

            st.markdown("")  # spacer between days

    else:
        st.info("No schedule yet. Add your first session above ↑")

    # ── Week overview summary ─────────────────────────────────
    if schedule:
        st.markdown("**Week at a glance:**")
        week_data = []
        for day_idx, day_name in enumerate(SCHEDULE_DAYS):
            day_items = [item for item in schedule if item.get("day") == day_idx]
            total_min = sum(item.get("minutes", 0) for item in day_items)
            skills    = [add_emoji(item["skill"]) for item in day_items]
            week_data.append({
                "Day":      day_name[:3],
                "Sessions": len(day_items),
                "Minutes":  total_min,
                "Skills":   ", ".join(skills) if skills else "—",
            })
        st.dataframe(
            pd.DataFrame(week_data),
            use_container_width=True,
            hide_index=True,
        )

# ═══════════════════════════════════════════════════════════════
# ONBOARDING
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

    unique_skills    = int(df["Skill"].nunique())
    current_unlocked = evaluate_achievements(total_hrs, streak, unique_skills)
    prev_set         = set(st.session_state.prev_achievements)
    newly_unlocked   = current_unlocked - prev_set
    if newly_unlocked and prev_set:
        for _ach_id in newly_unlocked:
            _ach = next((a for a in ACHIEVEMENTS if a["id"] == _ach_id), None)
            if _ach:
                st.balloons()
                st.toast(f"{_ach['emoji']} Achievement Unlocked: **{_ach['title']}**!", icon="🏅")
    st.session_state.prev_achievements = list(current_unlocked)

    if level > st.session_state.prev_level > 0:
        st.balloons()
        st.toast(f"🚀 Level Up! You've reached **Level {level}**!", icon="🎉")
    if st.session_state.prev_level == 0 or level > st.session_state.prev_level:
        st.session_state.prev_level = level

    today_ts   = _naive_ts(today_wib())
    dates_norm = _naive_dates(df["Date"])
    today_mins = float(df.loc[dates_norm >= today_ts, "Time Spent"].sum())

    # ── Title row ─────────────────────────────────────────────
    c_title, c_btn = st.columns([3, 1])
    with c_title:
        st.title("🇬🇧 English Pro Elite")
    with c_btn:
        if st.button("➕ Log Time", type="primary", use_container_width=True):
            log_session_dialog(all_skills)

    render_metrics(total_hrs, level, xp, this_week, streak)
    render_schedule_widget(all_skills)
    render_ai_coach(diet.to_dict(), all_skills, streak=streak, level=level, this_week=this_week)

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
        tab_dash, tab_history, tab_trophy, tab_settings, tab_chat = st.tabs([
            "📈 Dashboard", "📝 History", "🏆 Trophies", "⚙️ Settings", "💬 Chat",
        ])
        with tab_dash:
            render_tab_dashboard(
                df, diet, st.session_state.accent_color,
                today_mins, st.session_state.daily_goal_mins,
            )
        with tab_history:
            render_tab_history(all_skills)
        with tab_trophy:
            render_tab_trophies(
                total_hrs, streak, unique_skills,
                level, st.session_state.accent_color,
            )
        with tab_settings:
            render_tab_settings(all_skills)
        with tab_chat:
            render_ai_chat(
                diet_dict=diet.to_dict(),
                streak=streak,
                level=level,
                this_week=this_week,
                today_mins=today_mins,
                all_skills=all_skills,   # ← required for schedule card validation
            )

    perf_log("full_main_render", t_main)

else:
    render_onboarding()
