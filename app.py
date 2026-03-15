import streamlit as st
import pandas as pd
from github import Github
from datetime import datetime, timedelta
import io
import plotly.express as px
import numpy as np
import google.generativeai as genai
import json
import os
import base64
import time

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
AI_MIN_INTERVAL = 12    # seconds — 5 RPM = 1 call per 12s (OPT C1)
AI_DAILY_CAP    = 18    # hard cap, 2-call buffer below 20 RPD (OPT C5)
SCHEMA_VERSION  = "v1"  # bump this string to force cache invalidation (OPT D4)

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

def set_background(png_file: str):
    bg = _load_bg_base64(png_file)
    if not bg:
        return
    st.markdown(f"""
    <style>
    .stApp {{
        background-image: url("data:image/png;base64,{bg}");
        background-size: cover;
        background-attachment: fixed;
    }}
    [data-testid="stSidebar"] {{
        background-color: rgba(0,0,0,0.7) !important;
        backdrop-filter: blur(10px);
    }}
    .stTabs [data-baseweb="tab-panel"] {{
        background-color: rgba(20,20,20,0.6) !important;
        padding: 20px;
        border-radius: 15px;
        backdrop-filter: blur(5px);
        border: 1px solid rgba(255,255,255,0.1);
    }}
    [data-testid="stMetricValue"] {{ color: white !important; }}
    h1, h2, h3, h4, p, span, .stMarkdown div p {{ color: white !important; }}
    .stAlert {{
        background-color: rgba(0,0,0,0.4) !important;
        color: white !important;
        border: 1px solid rgba(255,255,255,0.2) !important;
    }}
    </style>
    """, unsafe_allow_html=True)

set_background("background.jpg")

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
    "ask_ai_auto":           False,
    # Credentials
    "saved_token":           local_creds.get("saved_token", ""),
    "saved_repo":            local_creds.get("saved_repo", ""),
    "gemini_key":            local_creds.get("gemini_key", ""),
    # Gamification
    "milestone_reward":      "Treat myself to coffee",
    "milestone_claimed_date":"",
    # AI state
    "last_ai_rec":           "",
    "last_ai_time":          None,
    "ai_calls_today":        0,
    "ai_call_date":          "",
    # OPT A5 — Derived state cache (invalidated on data change)
    "cached_all_skills":     None,
    "cached_diet":           None,
    "cached_this_week":      None,
    # Perf
    "debug_perf":            False,
    "accent_color":          "#00CC96",
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

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
        # OPT B1 — Pre-sort once on load, stored sorted forever
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
        g            = get_gh_client(token)
        repo         = g.get_repo(repo_name)
        content_str  = json.dumps(config_dict, indent=4)
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
                "weekly_goal":  st.session_state.weekly_goal,
                "theme":        st.session_state.theme_selector,
                "ask_ai_auto":  st.session_state.ask_ai_auto,
            },
        )

def save_to_github(token, repo_name, file_path, df):
    t0 = time.perf_counter()
    try:
        # OPT B5 — Conditional copy: only create new df if Date needs re-encoding
        if pd.api.types.is_datetime64_any_dtype(df["Date"]):
            df_save = df.assign(Date=df["Date"].dt.strftime("%Y-%m-%d"))
        else:
            df_save = df  # already strings, no copy needed

        csv_buffer = io.StringIO()
        df_save.to_csv(csv_buffer, index=False)
        g          = get_gh_client(token)
        repo       = g.get_repo(repo_name)
        latest_sha = repo.get_contents(file_path).sha
        res        = repo.update_file(
            path=file_path,
            message="Sync Elite Tracker",
            content=csv_buffer.getvalue(),
            sha=latest_sha,
        )
        perf_log("save_to_github", t0)
        return res["content"].sha
    except Exception as e:
        st.error(f"GitHub Sync Error: {e}")
        return None

# ═══════════════════════════════════════════════════════════════
# AUTO-SYNC HANDLER
# ═══════════════════════════════════════════════════════════════
def handle_editor_change():
    if "editor_key" in st.session_state:
        changes = st.session_state["editor_key"]
        if changes["edited_rows"] or changes["added_rows"] or changes["deleted_rows"]:
            sha = save_to_github(
                st.session_state.saved_token,
                st.session_state.saved_repo,
                "data.csv",
                st.session_state.df,
            )
            if sha:
                st.session_state.file_sha = sha
                _invalidate_derived_cache()

# ═══════════════════════════════════════════════════════════════
# GHOST AUTO-LOAD
# ═══════════════════════════════════════════════════════════════
if (st.session_state.df is None
        and st.session_state.saved_token
        and st.session_state.saved_repo):
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
        if "weekly_goal" in remote_cfg: st.session_state.weekly_goal    = remote_cfg["weekly_goal"]
        if "theme"       in remote_cfg: st.session_state.theme_selector = remote_cfg["theme"]
        if "ask_ai_auto" in remote_cfg: st.session_state.ask_ai_auto    = remote_cfg["ask_ai_auto"]

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
    all_skills  = list(dict.fromkeys(base_skills + extra))

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
@st.cache_data(show_spinner=False)
def build_area_chart(df: pd.DataFrame, accent_color: str, title: str):
    fig = px.area(
        df.sort_values("Date"),
        x="Date", y="Time Spent",
        title=title,
        color_discrete_sequence=[accent_color],
    )
    fig.update_layout(
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font_color="white",
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
# OPT C3 — TOKEN-COMPACT AI COACH
# ═══════════════════════════════════════════════════════════════
def get_ai_recommendation(api_key: str, skill_totals: dict) -> str:
    if not api_key:
        return "Please provide a Gemini API key."
    try:
        genai.configure(api_key=api_key)
        model   = genai.GenerativeModel("gemini-2.5-flash-lite")  # MODEL STASIS LOCKED
        compact = json.dumps(skill_totals, separators=(",", ":"))
        prompt  = f"English coach. Skills(mins):{compact}. One specific tip. ≤60 words."
        result  = model.generate_content(prompt).text
        st.session_state.last_ai_time   = datetime.now()
        st.session_state.ai_calls_today += 1
        return result
    except Exception as e:
        return f"AI Error: {str(e)}"

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
    st.slider("Weekly Goal (Hours)", 1, 40, key="weekly_goal", on_change=sync_config_to_github)
    st.checkbox("🧘 Zen Mode",      key="zen_mode")
    st.checkbox("🔄 Auto AI Coach", key="ask_ai_auto", on_change=sync_config_to_github)

    st.divider()

    today_str     = datetime.now().date().isoformat()
    display_calls = (
        st.session_state.ai_calls_today
        if st.session_state.ai_call_date == today_str
        else 0
    )
    st.caption(f"🤖 AI Calls Today: {display_calls} / {AI_DAILY_CAP}")
    if display_calls >= AI_DAILY_CAP:
        st.warning("Daily AI limit reached. Resets at midnight.")

    st.checkbox("🛠 Debug Timings", key="debug_perf")

# ═══════════════════════════════════════════════════════════════
# FRAGMENT: Metrics Row (OPT A1)
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
# FRAGMENT: AI Coach (OPT A2 + C2)
# ═══════════════════════════════════════════════════════════════
@st.fragment
def render_ai_coach(diet_dict: dict):
    if st.session_state.ask_ai_auto and st.session_state.gemini_key:
        allowed, reason = _check_ai_rate_limit()
        if allowed:
            with st.status("🤖 Coach is thinking...", expanded=False) as status:
                rec = get_ai_recommendation(st.session_state.gemini_key, diet_dict)
                st.session_state.last_ai_rec = rec
                status.update(label="✅ Coach ready", state="complete")
        else:
            if not st.session_state.last_ai_rec:
                st.caption(f"⏳ {reason}")

    if st.session_state.last_ai_rec:
        with st.expander("💡 Coach's Insight", expanded=True):
            st.write(st.session_state.last_ai_rec)
            if st.session_state.last_ai_time:
                st.caption(
                    f"🕐 Last updated: {st.session_state.last_ai_time.strftime('%H:%M:%S')}  "
                    f"· Calls today: {display_calls}/{AI_DAILY_CAP}"
                )

# ═══════════════════════════════════════════════════════════════
# FRAGMENT: Dashboard Tab (OPT A3)
# ═══════════════════════════════════════════════════════════════
@st.fragment
def render_tab_dashboard(df: pd.DataFrame, diet: pd.Series, accent_color: str):
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

# ═══════════════════════════════════════════════════════════════
# FRAGMENT: History Tab (OPT A3)
# ═══════════════════════════════════════════════════════════════
@st.fragment
def render_tab_history(df: pd.DataFrame, all_skills: list):
    st.info("💡 Changes made below are auto-synced to GitHub.")
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
# FRAGMENT: Trophy Tab (OPT A3)
# ═══════════════════════════════════════════════════════════════
@st.fragment
def render_tab_trophies():
    st.subheader("🎁 Today's Milestone Reward")
    today_iso = datetime.now().date().isoformat()
    if st.session_state.milestone_claimed_date != today_iso:
        if st.button(f"Claim: {st.session_state.milestone_reward}"):
            st.success("Claimed!")
            st.session_state.milestone_claimed_date = today_iso
            st.balloons()
    else:
        st.success("Reward claimed for today!")

# ═══════════════════════════════════════════════════════════════
# MAIN UI
# ═══════════════════════════════════════════════════════════════
if st.session_state.df is not None:
    t_main = time.perf_counter()
    df     = st.session_state.df

    total_hrs, level, xp, streak = get_dashboard_stats(df)
    all_skills, diet, this_week  = get_or_compute_derived(df)

    if level > st.session_state.prev_level > 0:
        st.balloons()
        st.session_state.prev_level = level
    elif st.session_state.prev_level == 0:
        st.session_state.prev_level = level

    c_title, c_btn = st.columns([3, 1])
    with c_title:
        st.title("🇬🇧 English Pro Elite")
    with c_btn:
        if st.button("➕ Log Time", type="primary", use_container_width=True):
            log_session_dialog(all_skills)

    render_metrics(total_hrs, level, xp, this_week, streak)
    render_ai_coach(diet.to_dict())

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
        tab_dash, tab_history, tab_trophy = st.tabs(["📈 Dashboard", "📝 History", "🏆 Trophies"])
        with tab_dash:
            render_tab_dashboard(df, diet, st.session_state.accent_color)
        with tab_history:
            render_tab_history(df, all_skills)
        with tab_trophy:
            render_tab_trophies()

    perf_log("full_main_render", t_main)

else:
    st.warning("👈 Provide GitHub credentials in the sidebar to auto-load your data.")
