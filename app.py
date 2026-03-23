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
import base64
import time
import hashlib

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

# ── ① JS HEARTBEAT ────────────────────────────────────────────
# Fires a synthetic mousemove every 25 s to keep the WebSocket
# alive for users who leave the tab open but don't interact.
def inject_keepalive(interval_ms: int = 25_000):
    st.markdown(
        f"""
        <script>
        (function keepAlive() {{
            setInterval(() => {{
                const el = window.parent.document.querySelector(
                    '[data-testid="stApp"]'
                );
                if (el) el.dispatchEvent(new Event('mousemove', {{bubbles: true}}));
            }}, {interval_ms});
        }})();
        </script>
        """,
        unsafe_allow_html=True,
    )

inject_keepalive(interval_ms=25_000)

CRED_FILE       = "credentials.json"
AI_MIN_INTERVAL = 12
AI_DAILY_CAP    = 18
SCHEMA_VERSION  = "v1"

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
    tab_bg       = "rgba(255,255,255,0.72)" if light_mode else "rgba(20,20,20,0.60)"
    text_color   = "#0d0d0d"               if light_mode else "white"
    alert_bg     = "rgba(255,255,255,0.5)" if light_mode else "rgba(0,0,0,0.40)"
    alert_border = "rgba(0,0,0,0.15)"      if light_mode else "rgba(255,255,255,0.20)"
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
        border-radius:15px;backdrop-filter:blur(5px);border:1px solid rgba(255,255,255,0.1);}}
    [data-testid="stMetricValue"]{{color:{text_color}!important;}}
    h1,h2,h3,h4,p,span,.stMarkdown div p{{color:{text_color}!important;}}
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
    delta = sum(abs(diet_dict.get(k,0)-old.get(k,0)) for k in set(diet_dict)|set(old))
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
# AI COACH  ── MODEL STASIS LOCKED: gemini-2.5-flash-lite ──
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
# LOG DIALOG
# ═══════════════════════════════════════════════════════════════
@st.dialog("➕ Log New Study Session")
def log_session_dialog(available_skills):
    with st.form("new_entry", clear_on_submit=False):
        d = st.date_input("Date", today_wib())
        s = st.selectbox("Skill", available_skills, format_func=add_emoji)
        t = st.number_input("Minutes", min_value=1, max_value=600, value=30)
        n = st.text_input("Notes")
        submitted = st.form_submit_button("💾 Log & Sync", use_container_width=True)

    if submitted:
        new_row    = pd.DataFrame({
            "Date":       [pd.Timestamp(d)],
            "Skill":      [s],
            "Time Spent": [int(t)],
            "Notes":      [n],
        })
        updated_df = pd.concat([st.session_state.df, new_row], ignore_index=True)

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
            _invalidate_derived_cache()
            load_data_from_github.clear()
            st.toast(f"✅ {int(t)} min of {add_emoji(s)} logged!", icon="📚")
            st.rerun()
        else:
            st.warning("⚠️ Entry NOT saved. Fix the error above and try again.")

# ═══════════════════════════════════════════════════════════════
# ② KEEP-ALIVE STATUS FRAGMENT
# run_every="60s" re-renders this fragment every 60 seconds,
# keeping the server-side session alive and refreshing the clock.
# This is lightweight — only this fragment re-runs, not the page.
# ═══════════════════════════════════════════════════════════════
@st.fragment(run_every="60s")
def render_keepalive_status():
    st.sidebar.caption(
        f"🟢 Live · {now_wib().strftime('%H:%M:%S')} WIB"
    )

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

    # ── ② Live clock / keep-alive indicator ──────────────────
    render_keepalive_status()

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
    _ratio = display_calls / _cap if _cap > 0 else 0
    _gauge_color, _gauge_icon = (
        ("#00CC96","🟢") if _ratio < 0.5 else
        ("#FFA500","🟡") if _ratio < 0.85 else
        ("#FF4B4B","🔴")
    )
    st.markdown(f"**{_gauge_icon} AI Budget: {display_calls} / {_cap}**")
    st.markdown(f"""
    <div style="background:rgba(255,255,255,0.12);border-radius:999px;
                height:10px;overflow:hidden;margin-bottom:4px">
      <div style="width:{min(_ratio*100,100):.0f}%;height:100%;
                  background:{_gauge_color};border-radius:999px;
                  transition:width 0.4s ease"></div>
    </div>""", unsafe_allow_html=True)

    _now_sb      = now_wib()
    _midnight_sb = datetime.combine(_now_sb.date() + timedelta(days=1),
                                    datetime.min.time(), tzinfo=_WIB)
    _sl = int((_midnight_sb - _now_sb).total_seconds())
    st.caption(f"⏰ Resets in {_sl//3600}h {(_sl%3600)//60}m (WIB)")
    if display_calls >= _cap:
        st.warning("Daily AI limit reached.")

    # ── ③ External ping reminder (shown once, dismissible) ───
    if not st.session_state.get("ping_tip_dismissed", False):
        with st.expander("💡 Keep app awake on Cloud", expanded=False):
            st.caption(
                "To prevent Streamlit Cloud from sleeping this app, "
                "add your app URL to a free ping service:\n\n"
                "• [UptimeRobot](https://uptimerobot.com) — set interval **5 min**\n"
                "• [cron-job.org](https://cron-job.org) — free, no sign-in required"
            )
            if st.button("✅ Got it, hide this", use_container_width=True):
                st.session_state.ping_tip_dismissed = True
                st.rerun()

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
        ✨ Progress to Level {level+1} &nbsp;·&nbsp; {pct}%
    </div>
    <div class="xp-bar-outer">
        <div class="xp-bar-inner" style="width:{pct}%;background:{accent};"></div>
    </div>
    """, unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════
# FRAGMENT: AI Coach
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
        last_tip = (st.session_state.last_ai_response.get("tip","")
                    if st.session_state.last_ai_response else "")
        resp = get_ai_recommendation(
            api_key=st.session_state.gemini_key, skill_totals=diet_dict,
            target_skill=st.session_state.ai_target_skill,
            streak=streak, level=level, last_tip=last_tip,
            weekly_goal=float(st.session_state.weekly_goal),
            this_week=this_week, monthly_review=monthly_review,
        )
        st.session_state.last_ai_response   = resp
        st.session_state.last_ai_rec        = resp.get("tip","")
        st.session_state.last_diet_hash     = _diet_hash(diet_dict)
        st.session_state.last_diet_snapshot = dict(diet_dict)
        if monthly_review:
            st.session_state.last_monthly_review = today_wib().isoformat()
        entry = {
            "time":     now_wib().strftime("%Y-%m-%d %H:%M WIB"),
            "skill":    st.session_state.ai_target_skill,
            "tip":      resp.get("tip",""),
            "exercise": resp.get("exercise",""),
            "resource": resp.get("resource",""),
            "monthly":  monthly_review,
        }
        st.session_state.ai_history = ([entry] + st.session_state.ai_history)[:5]

    def _show_cooldown(wait_secs, reason):
        if wait_secs > 0:
            st.markdown(f'<div class="cooldown-label">⏳ {reason}</div>', unsafe_allow_html=True)
            st.progress(max(0.0, min(1.0, 1.0-(wait_secs/AI_MIN_INTERVAL))),
                        text=f"Cooling down — {wait_secs:.0f}s")
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
        col_ask, col_monthly = st.columns([2,1])
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
            _last_mr    = st.session_state.get("last_monthly_review","")
            _can_review = (not _last_mr) or (
                (today_wib() - datetime.fromisoformat(_last_mr).date()).days >= 30)
            if st.button("📅 Monthly Review" if _can_review else "✅ Done this month",
                         use_container_width=True, disabled=not _can_review):
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
        tip      = resp.get("tip","")
        exercise = resp.get("exercise","")
        resource = resp.get("resource","")
        is_monthly = (st.session_state.ai_history[0].get("monthly",False)
                      if st.session_state.ai_history else False)
        with st.expander("📅 Monthly Review" if is_monthly else "💡 Coach's Insight",
                         expanded=True):
            if tip:
                st.markdown(f'<div class="ai-card" style="--accent-col:{accent}">'
                            f'💡 <strong>Tip</strong><br>{tip}</div>', unsafe_allow_html=True)
            if exercise:
                st.markdown(f'<div class="ai-card" style="--accent-col:{accent}">'
                            f'🏋️ <strong>Exercise</strong><br>{exercise}</div>',
                            unsafe_allow_html=True)
            if resource:
                st.markdown(f'<div class="ai-card" style="--accent-col:{accent}">'
                            f'🔗 <strong>Resource</strong><br>{resource}</div>',
                            unsafe_allow_html=True)
            if st.session_state.last_ai_time:
                st.caption(f"🕐 {st.session_state.last_ai_time.strftime('%H:%M:%S')}"
                           f"  ·  Calls today: {display_calls}/{_cap_local}")
    elif st.session_state.last_ai_rec:
        with st.expander("💡 Coach's Insight", expanded=True):
            st.write(st.session_state.last_ai_rec)

    if st.session_state.ai_history:
        with st.expander(f"📜 Coaching History ({len(st.session_state.ai_history)} tip(s))",
                         expanded=False):
            for entry in st.session_state.ai_history:
                badge = " 📅 Monthly" if entry.get("monthly") else ""
                st.markdown(f"**{entry['time']}** · *{entry.get('skill','?')}*{badge}")
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
        c1, c2 = st.columns([2,1])
        with c1:
            st.plotly_chart(build_area_chart(df, accent_color, "Study Mountain"),
                            use_container_width=True)
        with c2:
            st.plotly_chart(build_pie_chart(tuple(diet.index), tuple(diet.values)),
                            use_container_width=True)
        c3, c4 = st.columns([3,1])
        with c3:
            st.plotly_chart(build_heatmap(df, accent_color), use_container_width=True)
        with c4:
            st.plotly_chart(build_daily_ring(today_mins, daily_goal_mins, accent_color),
                            use_container_width=True)
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
        st.success(f"🚀 You are **Level {level}**! "
                   f"Next level unlocks at **{level*50:.0f} hours** total.")

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
def render_tab_settings():
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
    st.subheader("📱 Layout")
    st.toggle(
        "📱 Mobile-Friendly Layout (single column)",
        key="mobile_mode", on_change=sync_config_to_github,
    )

    st.divider()
    st.subheader("⚙️ Custom Skills Manager")
    st.caption("Add skills beyond the default six. Saved to your GitHub config.json.")

    custom = list(st.session_state.custom_skills or [])
    col_input, col_btn = st.columns([3,1])
    with col_input:
        new_skill = st.text_input("New skill name", placeholder="e.g. Pronunciation",
                                  label_visibility="collapsed")
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
            sc1, sc2 = st.columns([5,1])
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
    st.caption("Always available: 🎧 Listening, 🗣️ Speaking, 📖 Reading, "
               "✍️ Writing, 📝 Grammar, 💬 Vocabulary.")

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
        st.info(f"👈 Complete **{3-completed} more step(s)** in the sidebar to continue.")

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

    c_title, c_btn = st.columns([3,1])
    with c_title:
        st.title("🇬🇧 English Pro Elite")
    with c_btn:
        if st.button("➕ Log Time", type="primary", use_container_width=True):
            log_session_dialog(all_skills)

    render_metrics(total_hrs, level, xp, this_week, streak)
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
        tab_dash, tab_history, tab_trophy, tab_settings = st.tabs([
            "📈 Dashboard", "📝 History", "🏆 Trophies", "⚙️ Settings"
        ])
        with tab_dash:
            render_tab_dashboard(df, diet, st.session_state.accent_color,
                                 today_mins, st.session_state.daily_goal_mins)
        with tab_history:
            render_tab_history(all_skills)
        with tab_trophy:
            render_tab_trophies(total_hrs, streak, unique_skills,
                                level, st.session_state.accent_color)
        with tab_settings:
            render_tab_settings()

    perf_log("full_main_render", t_main)

else:
    render_onboarding()
