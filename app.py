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
AI_MIN_INTERVAL = 12        # seconds — 5 RPM = 1 call per 12s
AI_DAILY_CAP    = 18        # hard cap, 2-call buffer below 20 RPD
SCHEMA_VERSION  = "v1"      # bump to force cache invalidation

# D2: Achievement definitions — evaluated against live stats
ACHIEVEMENTS = [
    {
        "id": "first_hour",
        "emoji": "⭐",
        "title": "First Hour",
        "desc": "Log your first hour of study",
        "check": lambda hrs, streak, skills: hrs >= 1,
    },
    {
        "id": "ten_hours",
        "emoji": "🔟",
        "title": "Ten Hours",
        "desc": "Accumulate 10 total hours",
        "check": lambda hrs, streak, skills: hrs >= 10,
    },
    {
        "id": "fifty_hours",
        "emoji": "🥈",
        "title": "Half Century",
        "desc": "Reach 50 total hours",
        "check": lambda hrs, streak, skills: hrs >= 50,
    },
    {
        "id": "hundred_hours",
        "emoji": "💯",
        "title": "Century Club",
        "desc": "Reach 100 total hours",
        "check": lambda hrs, streak, skills: hrs >= 100,
    },
    {
        "id": "streak_3",
        "emoji": "🔥",
        "title": "On Fire",
        "desc": "Maintain a 3-day streak",
        "check": lambda hrs, streak, skills: streak >= 3,
    },
    {
        "id": "streak_7",
        "emoji": "🗓️",
        "title": "Week Warrior",
        "desc": "Maintain a 7-day streak",
        "check": lambda hrs, streak, skills: streak >= 7,
    },
    {
        "id": "streak_30",
        "emoji": "🏆",
        "title": "Monthly Master",
        "desc": "Maintain a 30-day streak",
        "check": lambda hrs, streak, skills: streak >= 30,
    },
    {
        "id": "polymath",
        "emoji": "🎓",
        "title": "Polymath",
        "desc": "Study 4+ different skills",
        "check": lambda hrs, streak, skills: skills >= 4,
    },
    {
        "id": "level_5",
        "emoji": "🚀",
        "title": "Level 5",
        "desc": "Reach Level 5 (200h total)",
        "check": lambda hrs, streak, skills: hrs >= 200,
    },
    {
        "id": "dedicated",
        "emoji": "🦉",
        "title": "Dedicated",
        "desc": "Study for 500+ total minutes in any skill",
        "check": lambda hrs, streak, skills: hrs >= 8.34,
    },
]

# ═══════════════════════════════════════════════════════════════
# OPT D5 — CACHE RESOURCE: Credentials (disk I/O once per server lifetime)
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
# OPT A4 — CACHE RESOURCE: Background image (once per server, not per session)
# ═══════════════════════════════════════════════════════════════
@st.cache_resource(show_spinner=False)
def _load_bg_base64(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

# E4: Extended set_background with dark/light mode toggle
def set_background(png_file: str, light_mode: bool = False):
    bg = _load_bg_base64(png_file)

    # E4: CSS variables shift based on light/dark preference
    sidebar_bg    = "rgba(245,245,250,0.88)" if light_mode else "rgba(0,0,0,0.70)"
    tab_bg        = "rgba(255,255,255,0.72)" if light_mode else "rgba(20,20,20,0.60)"
    text_color    = "#0d0d0d"               if light_mode else "white"
    alert_bg      = "rgba(255,255,255,0.5)" if light_mode else "rgba(0,0,0,0.40)"
    alert_border  = "rgba(0,0,0,0.15)"      if light_mode else "rgba(255,255,255,0.20)"

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
    /* D2: Badge card styles */
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
    /* E3: Onboarding card */
    .onboarding-card {{
        background: rgba(0,0,0,0.48);
        border-radius: 16px;
        padding: 28px 24px;
        border: 1px solid rgba(255,255,255,0.14);
        margin: 16px 0;
    }}
    .onboarding-step {{ margin-bottom: 14px; font-size: 1.02rem; }}
    </style>
    """, unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
# SESSION STATE INIT
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
    "daily_goal_mins":       60,          # B4: daily ring target
    "ask_ai_auto":           False,
    "light_mode":            False,        # E4: dark/light toggle
    # Credentials
    "saved_token":           local_creds.get("saved_token", ""),
    "saved_repo":            local_creds.get("saved_repo", ""),
    "gemini_key":            local_creds.get("gemini_key", ""),
    # Gamification
    "milestone_reward":      "Treat myself to coffee",   # D1: user-editable
    "milestone_claimed_date":"",
    # AI state
    "last_ai_rec":           "",
    "last_ai_time":          None,
    "ai_calls_today":        0,
    "ai_call_date":          "",
    "ai_history":            [],           # C2: last-5 coach log
    "last_diet_hash":        "",           # C1: change-detection hash
    "ai_target_skill":       "All Skills", # C3: skill-specific prompt
    # OPT A5 — Derived state cache (invalidated on data change)
    "cached_all_skills":     None,
    "cached_diet":           None,
    "cached_this_week":      None,
    # Perf
    "debug_perf":            False,
    "accent_color":          "#00CC96",
    # E1: user-defined custom skills
    "custom_skills":         [],
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# Apply background after session_state is initialised (light_mode is now available)
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

# OPT D4 — SCHEMA_VERSION in cache key forces cache bust on schema changes
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
        # OPT B1 — Pre-sort once on load
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
                "weekly_goal":       st.session_state.weekly_goal,
                "daily_goal_mins":   st.session_state.daily_goal_mins,
                "theme":             st.session_state.theme_selector,
                "ask_ai_auto":       st.session_state.ask_ai_auto,
                "light_mode":        st.session_state.light_mode,      # E4
                "milestone_reward":  st.session_state.milestone_reward, # D1
                "custom_skills":     st.session_state.custom_skills,    # E1
            },
        )

# A3 FIX: Use cached file_sha instead of an extra API round-trip
def save_to_github(token, repo_name, file_path, df):
    t0 = time.perf_counter()
    try:
        # OPT B5 — Conditional copy: only re-encode Date if needed
        if pd.api.types.is_datetime64_any_dtype(df["Date"]):
            df_save = df.assign(Date=df["Date"].dt.strftime("%Y-%m-%d"))
        else:
            df_save = df  # already strings, no copy needed

        csv_buffer = io.StringIO()
        df_save.to_csv(csv_buffer, index=False)
        g    = get_gh_client(token)
        repo = g.get_repo(repo_name)

        # A3: prefer cached sha — fall back to fresh fetch only when sha is absent
        sha = st.session_state.get("file_sha") or repo.get_contents(file_path).sha

        res = repo.update_file(
            path=file_path,
            message="Sync Elite Tracker",
            content=csv_buffer.getvalue(),
            sha=sha,
        )
        perf_log("save_to_github", t0)
        return res["content"].sha
    except Exception as e:
        st.error(f"GitHub Sync Error: {e}")
        return None

# ═══════════════════════════════════════════════════════════════
# A2 FIX: Apply editor changes to a working copy BEFORE saving
# ═══════════════════════════════════════════════════════════════
def handle_editor_change():
    if "editor_key" not in st.session_state:
        return
    changes = st.session_state["editor_key"]
    if not (changes["edited_rows"] or changes["added_rows"] or changes["deleted_rows"]):
        return

    # Build a working copy so the save always contains the latest state
    working_df = st.session_state.df.copy()

    # Apply inline edits
    for idx_str, col_changes in changes["edited_rows"].items():
        idx = int(idx_str)
        for col, val in col_changes.items():
            working_df.at[idx, col] = val

    # Append new rows
    if changes["added_rows"]:
        new_rows   = pd.DataFrame(changes["added_rows"])
        working_df = pd.concat([working_df, new_rows], ignore_index=True)

    # Remove deleted rows
    if changes["deleted_rows"]:
        working_df = working_df.drop(index=changes["deleted_rows"]).reset_index(drop=True)

    # Coerce types after mutations
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
    df, sha, status = load_data_from_github(
        st.session_state.saved_token,
        st.session_state.saved_repo,
        "data.csv",
    )
    remote_cfg = load_config_from_github(
        st.session_state.saved_token,
        st.session_state.saved_repo,
    )
    if status == "success":
        st.session_state.df       = df
        st.session_state.file_sha = sha
        # Map config keys → session-state keys (covers all persisted settings)
        _cfg_map = {
            "weekly_goal":      "weekly_goal",
            "daily_goal_mins":  "daily_goal_mins",
            "theme":            "theme_selector",
            "ask_ai_auto":      "ask_ai_auto",
            "light_mode":       "light_mode",
            "milestone_reward": "milestone_reward",
            "custom_skills":    "custom_skills",
        }
        for cfg_key, ss_key in _cfg_map.items():
            if cfg_key in remote_cfg:
                st.session_state[ss_key] = remote_cfg[cfg_key]

# ═══════════════════════════════════════════════════════════════
# OPT B3 — VECTORIZED STREAK via np.diff (replaces for-loop)
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
# OPT B2 — CACHED DASHBOARD STATS
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
# OPT A5 + B4 + D1 + D2 — DERIVED STATE CACHE
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
    # E1: merge user-defined custom skills into the canonical list
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
# OPT D3 — CACHED PLOTLY FIGURES
# ═══════════════════════════════════════════════════════════════

# B3: Area chart now includes 7-day & 30-day rolling average overlays
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

    fig = px.area(
        daily,
        x="Date",
        y="Time Spent",
        title=title,
        color_discrete_sequence=[accent_color],
    )
    fig.add_scatter(
        x=daily["Date"], y=daily["7d avg"],
        mode="lines", name="7d avg",
        line=dict(color="orange", width=1.5, dash="dot"),
    )
    fig.add_scatter(
        x=daily["Date"], y=daily["30d avg"],
        mode="lines", name="30d avg",
        line=dict(color="cyan", width=1.5, dash="dash"),
    )
    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font_color="white",
        legend=dict(orientation="h", y=-0.22),
    )
    return fig

@st.cache_data(show_spinner=False)
def build_pie_chart(skill_names: tuple, skill_values: tuple):
    fig = px.pie(names=skill_names, values=skill_values, hole=0.5, title="Skill Diet")
    fig.update_layout(
        showlegend=False,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font_color="white",
    )
    return fig

# B1: 90-day GitHub-style study heatmap
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
        daily,
        x="Week",
        y="DOW",
        z="Minutes",
        category_orders={"DOW": dow_order},
        color_continuous_scale=["#111111", accent_color],
        title="90-Day Study Heatmap",
    )
    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font_color="white",
        coloraxis_showscale=False,
        yaxis=dict(categoryorder="array", categoryarray=dow_order),
    )
    return fig

# B2: Per-skill horizontal progress bars
@st.cache_data(show_spinner=False)
def build_skill_bars(diet: pd.Series, accent_color: str):
    df_bar = diet.reset_index()
    df_bar.columns = ["Skill", "Minutes"]
    df_bar = df_bar.sort_values("Minutes", ascending=True)
    fig = px.bar(
        df_bar,
        x="Minutes",
        y="Skill",
        orientation="h",
        title="Minutes Per Skill",
        color="Minutes",
        color_continuous_scale=["#222222", accent_color],
    )
    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font_color="white",
        coloraxis_showscale=False,
        showlegend=False,
    )
    return fig

# B4: Daily goal completion ring (Plotly gauge indicator)
@st.cache_data(show_spinner=False)
def build_daily_ring(today_mins: float, goal_mins: int, accent_color: str):
    ceiling = max(float(goal_mins), today_mins, 1.0)
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=today_mins,
            number={"suffix": " min", "font": {"color": "white", "size": 22}},
            title={"text": f"Today vs {goal_mins} min goal", "font": {"color": "white", "size": 13}},
            gauge={
                "axis":        {"range": [0, ceiling], "tickcolor": "white"},
                "bar":         {"color": accent_color},
                "bgcolor":     "rgba(0,0,0,0)",
                "bordercolor": "rgba(255,255,255,0.2)",
                "threshold": {
                    "line":  {"color": "white", "width": 2},
                    "value": goal_mins,
                },
            },
        )
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        font_color="white",
        height=220,
        margin=dict(t=40, b=10, l=20, r=20),
    )
    return fig

# ═══════════════════════════════════════════════════════════════
# C1: Hash-based AI change detection helper
# ═══════════════════════════════════════════════════════════════
def _diet_hash(diet_dict: dict) -> str:
    return hashlib.md5(
        json.dumps(diet_dict, sort_keys=True).encode()
    ).hexdigest()

# ═══════════════════════════════════════════════════════════════
# OPT C1 + C4 + C5 — SMART RATE-LIMIT GUARD
# ═══════════════════════════════════════════════════════════════
def _check_ai_rate_limit() -> tuple:
    """Returns (allowed: bool, reason: str)."""
    now       = datetime.now()
    today_str = now.date().isoformat()

    if st.session_state.ai_call_date != today_str:
        st.session_state.ai_call_date   = today_str
        st.session_state.ai_calls_today = 0

    if st.session_state.ai_calls_today >= AI_DAILY_CAP:
        return False, f"Daily AI limit reached ({AI_DAILY_CAP}/day). Resets at midnight."

    last = st.session_state.last_ai_time
    if last and (now - last).total_seconds() < AI_MIN_INTERVAL:
        wait = AI_MIN_INTERVAL - (now - last).total_seconds()
        return False, f"Rate limit: {wait:.0f}s until next AI call."

    return True, ""

# ═══════════════════════════════════════════════════════════════
# OPT C3 — TOKEN-COMPACT AI COACH  [MODEL STASIS LOCKED]
# ═══════════════════════════════════════════════════════════════
def get_ai_recommendation(
    api_key: str,
    skill_totals: dict,
    target_skill: str = "All Skills",
) -> str:
    if not api_key:
        return "Please provide a Gemini API key."
    try:
        genai.configure(api_key=api_key)
        model   = genai.GenerativeModel("gemini-2.5-flash-lite")  # MODEL STASIS LOCKED
        compact = json.dumps(skill_totals, separators=(",", ":"))
        # C3: skill-specific prompt path
        if target_skill and target_skill != "All Skills":
            prompt = (
                f"English coach. Skills(mins):{compact}. "
                f"Give ONE specific tip ONLY for '{target_skill}'. ≤60 words."
            )
        else:
            prompt = f"English coach. Skills(mins):{compact}. One specific tip. ≤60 words."
        result = model.generate_content(prompt).text
        st.session_state.last_ai_time    = datetime.now()
        st.session_state.ai_calls_today += 1
        return result
    except Exception as e:
        return f"AI Error: {str(e)}"

# ═══════════════════════════════════════════════════════════════
# D2: Achievement evaluator
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
# DIALOG
# ═══════════════════════════════════════════════════════════════
@st.dialog("➕ Log New Study Session")
def log_session_dialog(available_skills):
    with st.form("new_entry", clear_on_submit=True):
        d = st.date_input("Date", datetime.now())
        s = st.selectbox("Skill", available_skills)
        t = st.number_input("Minutes", 1, 600, 30)
        n = st.text_input("Notes")
        if st.form_submit_button("Log & Sync", use_container_width=True):
            new_row = pd.DataFrame({
                "Date":       [pd.to_datetime(d)],
                "Skill":      [s],
                "Time Spent": [t],
                "Notes":      [n],
            })
            st.session_state.df = pd.concat(
                [st.session_state.df, new_row], ignore_index=True
            )
            _invalidate_derived_cache()
            sha = save_to_github(
                st.session_state.saved_token,
                st.session_state.saved_repo,
                "data.csv",
                st.session_state.df,
            )
            if sha:
                st.session_state.file_sha = sha
                st.rerun()

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
    st.selectbox(
        "Theme",
        list(theme_map.keys()),
        key="theme_selector",
        on_change=sync_config_to_github,
    )
    st.session_state.accent_color = theme_map[st.session_state.theme_selector]

    # E4: Dark / Light mode toggle — synced to config.json
    st.toggle(
        "☀️ Light Mode",
        key="light_mode",
        on_change=sync_config_to_github,
    )

    st.slider(
        "Weekly Goal (Hours)", 1, 40,
        key="weekly_goal",
        on_change=sync_config_to_github,
    )
    # B4: configurable daily target
    st.slider(
        "Daily Goal (Minutes)", 10, 300,
        key="daily_goal_mins",
        on_change=sync_config_to_github,
    )
    st.checkbox("🧘 Zen Mode",      key="zen_mode")
    st.checkbox("🔄 Auto AI Coach", key="ask_ai_auto", on_change=sync_config_to_github)

    st.divider()

    _today_str    = datetime.now().date().isoformat()
    display_calls = (
        st.session_state.ai_calls_today
        if st.session_state.ai_call_date == _today_str
        else 0
    )
    st.caption(f"🤖 AI Calls Today: {display_calls} / {AI_DAILY_CAP}")
    if display_calls >= AI_DAILY_CAP:
        st.warning("Daily AI limit reached. Resets at midnight.")

    st.checkbox("🛠 Debug Timings", key="debug_perf")

# ═══════════════════════════════════════════════════════════════
# FRAGMENT: Metrics Row
# ═══════════════════════════════════════════════════════════════
@st.fragment
def render_metrics(total_hrs: float, level: int, xp: float, this_week: float, streak: int):
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Level",     f"Lvl {level}")
    m2.metric("Total",     f"{total_hrs:.1f}h")
    m3.metric("Streak",    f"{streak} Days")
    m4.metric("This Week", f"{this_week:.1f}/{st.session_state.weekly_goal}h")
    st.progress(xp, text=f"Progress to Level {level + 1}")

# ═══════════════════════════════════════════════════════════════
# FRAGMENT: AI Coach
# A1 FIX  — display_calls computed from session_state (no outer-scope dependency)
# C1 FIX  — hash-guard prevents wasteful calls on pure UI events
# C2 FEAT — coaching history log (last 5 tips)
# C3 FEAT — skill-specific coach prompt selectbox
# ═══════════════════════════════════════════════════════════════
@st.fragment
def render_ai_coach(diet_dict: dict, all_skills: list):
    # A1 FIX: derive display_calls entirely from session_state
    _today_local  = datetime.now().date().isoformat()
    display_calls = (
        st.session_state.ai_calls_today
        if st.session_state.ai_call_date == _today_local
        else 0
    )

    # C3: Skill target selector (shown whether auto-mode is on or off)
    skill_options = ["All Skills"] + all_skills
    current_target = st.session_state.ai_target_skill
    if current_target not in skill_options:
        current_target = "All Skills"
    st.session_state.ai_target_skill = st.selectbox(
        "🎯 Coach focus:",
        skill_options,
        index=skill_options.index(current_target),
        key="ai_skill_select",
    )

    if st.session_state.ask_ai_auto and st.session_state.gemini_key:
        # C1: Only fire the AI when the data has actually changed
        current_hash = _diet_hash(diet_dict)
        if current_hash != st.session_state.last_diet_hash:
            allowed, reason = _check_ai_rate_limit()
            if allowed:
                with st.status("🤖 Coach is thinking...", expanded=False) as status:
                    rec = get_ai_recommendation(
                        st.session_state.gemini_key,
                        diet_dict,
                        st.session_state.ai_target_skill,
                    )
                    st.session_state.last_ai_rec    = rec
                    st.session_state.last_diet_hash = current_hash
                    # C2: prepend to history, keep last 5
                    st.session_state.ai_history = ([{
                        "time":  datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "skill": st.session_state.ai_target_skill,
                        "tip":   rec,
                    }] + st.session_state.ai_history)[:5]
                    status.update(label="✅ Coach ready", state="complete")
            else:
                if not st.session_state.last_ai_rec:
                    st.caption(f"⏳ {reason}")
    else:
        # Manual trigger when auto-mode is off
        if st.button("💬 Ask Coach", use_container_width=True):
            allowed, reason = _check_ai_rate_limit()
            if allowed:
                with st.status("🤖 Thinking...", expanded=False) as status:
                    rec = get_ai_recommendation(
                        st.session_state.gemini_key,
                        diet_dict,
                        st.session_state.ai_target_skill,
                    )
                    st.session_state.last_ai_rec    = rec
                    st.session_state.last_diet_hash = _diet_hash(diet_dict)
                    st.session_state.ai_history = ([{
                        "time":  datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "skill": st.session_state.ai_target_skill,
                        "tip":   rec,
                    }] + st.session_state.ai_history)[:5]
                    status.update(label="✅ Done", state="complete")
            else:
                st.warning(reason)

    if st.session_state.last_ai_rec:
        with st.expander("💡 Coach's Insight", expanded=True):
            st.write(st.session_state.last_ai_rec)
            if st.session_state.last_ai_time:
                st.caption(
                    f"🕐 Last updated: {st.session_state.last_ai_time.strftime('%H:%M:%S')}"
                    f"  ·  Calls today: {display_calls}/{AI_DAILY_CAP}"
                )

    # C2: Coaching history log
    if st.session_state.ai_history:
        with st.expander(
            f"📜 Coaching History ({len(st.session_state.ai_history)} tip(s))",
            expanded=False,
        ):
            for entry in st.session_state.ai_history:
                st.markdown(f"**{entry['time']}** · *{entry['skill']}*")
                st.write(entry["tip"])
                st.divider()

# ═══════════════════════════════════════════════════════════════
# FRAGMENT: Dashboard Tab
# New: B1 heatmap, B2 skill bars, B3 rolling averages, B4 daily ring
# ═══════════════════════════════════════════════════════════════
@st.fragment
def render_tab_dashboard(
    df: pd.DataFrame,
    diet: pd.Series,
    accent_color: str,
    today_mins: float,
    daily_goal_mins: int,
):
    # Row 1: area chart + pie
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

    # Row 2: B1 heatmap + B4 daily ring
    c3, c4 = st.columns([3, 1])
    with c3:
        st.plotly_chart(
            build_heatmap(df, accent_color),
            use_container_width=True,
        )
    with c4:
        st.plotly_chart(
            build_daily_ring(today_mins, daily_goal_mins, accent_color),
            use_container_width=True,
        )

    # Row 3: B2 per-skill bars (full width)
    st.plotly_chart(
        build_skill_bars(diet, accent_color),
        use_container_width=True,
    )

# ═══════════════════════════════════════════════════════════════
# FRAGMENT: History Tab
# New: E2 CSV export button, A2 fix applied via handle_editor_change
# ═══════════════════════════════════════════════════════════════
@st.fragment
def render_tab_history(df: pd.DataFrame, all_skills: list):
    st.info("💡 Changes made below are auto-synced to GitHub.")

    # E2: One-click CSV export
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
# FRAGMENT: Trophy Tab
# D1: editable milestone reward
# D2: achievement badge grid
# D3: level-up announcement card
# ═══════════════════════════════════════════════════════════════
@st.fragment
def render_tab_trophies(
    total_hrs: float,
    streak: int,
    unique_skills: int,
    level: int,
    accent_color: str,
):
    # D3: Styled level-up announcement card
    if level >= 2:
        st.success(
            f"🚀 You are **Level {level}**! "
            f"Next level unlocks at **{level * 50:.0f} hours** total."
        )

    # D1: User-editable milestone reward (persisted to config.json)
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
        if st.button(
            f"🎉 Claim: {st.session_state.milestone_reward}",
            use_container_width=True,
        ):
            st.success("Claimed! Enjoy your reward. 🎊")
            st.session_state.milestone_claimed_date = today_iso
            st.balloons()
    else:
        st.success("✅ Reward claimed for today — see you tomorrow!")

    st.divider()

    # D2: Achievement badge grid
    st.subheader("🏅 Achievements")
    unlocked = evaluate_achievements(total_hrs, streak, unique_skills)
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
# FRAGMENT: Settings Tab — E1 custom skills manager
# ═══════════════════════════════════════════════════════════════
@st.fragment
def render_tab_settings():
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
        "These are always available: "
        "Listening, Speaking, Reading, Writing, Grammar, Vocabulary."
    )

# ═══════════════════════════════════════════════════════════════
# E3: ONBOARDING WIZARD — replaces bare st.warning on first run
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
        st.success(
            "🎉 All set! Click **🔄 Refresh Application** in the sidebar to load your data."
        )
    else:
        remaining = 3 - completed
        st.info(f"👈 Complete **{remaining} more step(s)** in the sidebar to continue.")

# ═══════════════════════════════════════════════════════════════
# MAIN UI
# ═══════════════════════════════════════════════════════════════
if st.session_state.df is not None:
    t_main = time.perf_counter()
    df     = st.session_state.df

    total_hrs, level, xp, streak = get_dashboard_stats(df)
    all_skills, diet, this_week  = get_or_compute_derived(df)

    # D3: Level-up detection with toast notification
    if level > st.session_state.prev_level > 0:
        st.balloons()
        st.toast(f"🚀 Level Up! You've reached **Level {level}**!", icon="🎉")
    if st.session_state.prev_level == 0 or level > st.session_state.prev_level:
        st.session_state.prev_level = level

    # Derive today's totals for the B4 daily ring
    today_date    = pd.Timestamp(datetime.now().date())
    today_mins    = float(df.loc[df["Date"] >= today_date, "Time Spent"].sum())
    unique_skills = int(df["Skill"].nunique())

    # Title row + quick-log button
    c_title, c_btn = st.columns([3, 1])
    with c_title:
        st.title("🇬🇧 English Pro Elite")
    with c_btn:
        if st.button("➕ Log Time", type="primary", use_container_width=True):
            log_session_dialog(all_skills)

    render_metrics(total_hrs, level, xp, this_week, streak)
    render_ai_coach(diet.to_dict(), all_skills)

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
                df,
                diet,
                st.session_state.accent_color,
                today_mins,
                st.session_state.daily_goal_mins,
            )
        with tab_history:
            render_tab_history(df, all_skills)
        with tab_trophy:
            render_tab_trophies(
                total_hrs,
                streak,
                unique_skills,
                level,
                st.session_state.accent_color,
            )
        with tab_settings:
            render_tab_settings()

    perf_log("full_main_render", t_main)

else:
    # E3: Onboarding wizard replaces the bare st.warning
    render_onboarding()
