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
import requests
import pytz
from typing import Optional, Tuple

# --- ENHANCED CONFIGURATION & SESSION STATE MANAGEMENT ---
st.set_page_config(page_title="English Pro Elite", layout="wide", page_icon="🇬🇧", initial_sidebar_state="collapsed")

# --- STRUCTURED SESSION STATE INITIALIZATION ---
def initialize_session_state():
    session_defaults = {
        'df': None, 'file_sha': None, 'prev_level': 0,
        'saved_token': "", 'saved_repo': "", 'accent_color': "#00CC96",
        'zen_mode': False, 'milestone_reward': "Treat myself to coffee",
        'gemini_key': "", 'custom_skills': "", 'last_ai_rec': "",
        'offline_mode': False, 'pending_changes': [], 'last_sync_time': None,
        'connection_status': {'github': 'untested', 'gemini': 'untested'},
        'mobile_view': False, 'data_backup': None, 'error_log': []
    }
    CRED_FILE = "credentials.json"
    local_creds = {}
    if os.path.exists(CRED_FILE):
        try:
            with open(CRED_FILE, "r") as f:
                local_creds = json.load(f)
        except Exception as e:
            st.error(f"Credential load error: {str(e)}")
    for key, default in session_defaults.items():
        if key not in st.session_state:
            st.session_state[key] = local_creds.get(key, default) if key in ['saved_token', 'saved_repo', 'gemini_key'] else default
    # Mobile detection
    if any(x in st.query_params.get("user_agent", "").lower() for x in ['mobile', 'iphone', 'android']):
        st.session_state.mobile_view = True

initialize_session_state()

# --- ENHANCED ERROR HANDLING DECORATOR ---
def handle_api_errors(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except requests.exceptions.ConnectionError as e:
            st.session_state.connection_status['github'] = 'offline'
            st.session_state.offline_mode = True
            raise Exception(f"Connection error: {str(e)}")
        except Exception as e:
            if 'error_log' not in st.session_state:
                st.session_state.error_log = []
            st.session_state.error_log.append({'timestamp': datetime.now().isoformat(), 'function': func.__name__, 'error': str(e)})
            raise
    return wrapper

# --- CONNECTION HEALTH CHECK ---
@st.cache_data(ttl=60, show_spinner=False)
@handle_api_errors
def test_github_connection(token: str) -> Tuple[bool, str]:
    if not token: return False, "No token"
    try:
        g = Github(token)
        user = g.get_user()
        return True, f"Connected as {user.login}"
    except Exception as e:
        return False, str(e)

@st.cache_data(ttl=60, show_spinner=False)
@handle_api_errors
def test_gemini_connection(api_key: str) -> Tuple[bool, str]:
    if not api_key: return False, "No key"
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash-lite')
        model.generate_content("Test")
        return True, "OK"
    except Exception as e:
        return False, str(e)

# --- OFFLINE DATA MANAGEMENT ---
def save_local_backup(df: pd.DataFrame):
    try:
        with open("elite_tracker_backup.json", "w") as f:
            json.dump({'timestamp': datetime.now().isoformat(), 'data': df.to_dict('records')}, f)
    except Exception as e:
        st.error(f"Backup failed: {e}")

def load_local_backup() -> Optional[pd.DataFrame]:
    if os.path.exists("elite_tracker_backup.json"):
        try:
            with open("elite_tracker_backup.json", "r") as f:
                data = json.load(f)
            df = pd.DataFrame(data['data'])
            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'])
            if 'Time Spent' in df.columns:
                df['Time Spent'] = pd.to_numeric(df['Time Spent'], errors='coerce')
            return df
        except:
            return None
    return None

# --- MOBILE OPTIMIZATION UTILITIES ---
def responsive_columns(mobile_cols=1, desktop_cols=4):
    return st.columns(mobile_cols) if st.session_state.mobile_view else st.columns(desktop_cols)

def mobile_friendly_metric(label, value, help_text=""):
    st.metric(label, value, help=help_text, label_visibility="visible" if st.session_state.mobile_view else "collapsed")

# --- BACKGROUND (mobile-aware) ---
def set_background(png_file='background.jpg'):
    if os.path.exists(png_file):
        with open(png_file, 'rb') as f:
            bin_str = base64.b64encode(f.read()).decode()
        st.markdown(f'''
        <style>
        .stApp {{background-image: url("data:image/png;base64,{bin_str}"); background-size: cover; background-attachment: fixed;}}
        [data-testid="stSidebar"] {{background-color: rgba(0,0,0,0.7) !important; backdrop-filter: blur(10px);}}
        .stTabs [data-baseweb="tab-panel"] {{padding: {'10px' if st.session_state.mobile_view else '20px'};}}
        @media (max-width: 768px) {{.stTabs [data-baseweb="tab"] {{font-size: 0.9rem !important;}} .stDataFrame {{font-size: 0.9rem;}}}}
        </style>
        ''', unsafe_allow_html=True)

set_background()

# --- CREDENTIALS ---
CRED_FILE = "credentials.json"
def save_credentials_to_disk():
    try:
        with open(CRED_FILE, "w") as f:
            json.dump({"saved_token": st.session_state.saved_token, "saved_repo": st.session_state.saved_repo, "gemini_key": st.session_state.gemini_key}, f)
    except Exception as e:
        st.error(f"Save failed: {e}")

# --- ENHANCED AI (exact model preserved) ---
@handle_api_errors
def get_ai_recommendation(api_key, dataframe, current_date):
    if not api_key: return "No Gemini key."
    if not test_gemini_connection(api_key)[0]:
        st.session_state.offline_mode = True
        return f"AI offline. Last cached: {st.session_state.last_ai_rec or 'none'}"
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.5-flash-lite')
    summary = dataframe.groupby('Skill')['Time Spent'].sum().to_dict()
    prompt = f"""Expert English Coach. Data: {summary}. Focus neglect vs strength. 100 words max."""
    resp = model.generate_content(prompt)
    rec = resp.text
    st.session_state.last_ai_rec = rec
    return rec

# --- ENHANCED GITHUB FUNCTIONS ---
@st.cache_resource(show_spinner=False)
@handle_api_errors
def get_gh_client(token):
    return Github(token)

@st.cache_data(ttl=300, show_spinner=False)
@handle_api_errors
def load_data_from_github(token, repo_name, file_path):
    try:
        ok, msg = test_github_connection(token)
        if not ok:
            st.session_state.offline_mode = True
            df = load_local_backup()
            return (df, "local_backup", "offline") if df is not None else (None, None, msg)
        g = get_gh_client(token)
        repo = g.get_repo(repo_name)
        contents = repo.get_contents(file_path)
        df = pd.read_csv(io.StringIO(contents.decoded_content.decode()))
        # original cleaning preserved exactly
        df.columns = df.columns.str.strip()
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'], errors='coerce', dayfirst=True)
        if 'Skill' in df.columns:
            df['Skill'] = df['Skill'].astype(str).str.strip().ffill().fillna("Reading")
        if 'Time Spent' in df.columns:
            df['Time Spent'] = pd.to_numeric(df['Time Spent'], errors='coerce').fillna(0)
        if 'Notes' not in df.columns:
            df['Notes'] = ""
        save_local_backup(df)
        st.session_state.offline_mode = False
        return df, contents.sha, "success"
    except Exception as e:
        df = load_local_backup()
        return (df, "local_backup", "offline_fallback") if df is not None else (None, None, str(e))

@handle_api_errors
def save_to_github(token: str, repo_name: str, file_path: str, df: pd.DataFrame) -> Optional[str]:
    try:
        ok, msg = test_github_connection(token)
        if not ok:
            st.session_state.offline_mode = True
            st.session_state.pending_changes.append({'type': 'full_update', 'data': df.to_dict('records')})
            save_local_backup(df)
            st.warning("OFFLINE: Changes queued locally.")
            return None
        g = get_gh_client(token)
        repo = g.get_repo(repo_name)
        contents = repo.get_contents(file_path)
        latest_sha = contents.sha
        df_save = df.copy()
        df_save['Date'] = pd.to_datetime(df_save['Date']).dt.strftime("%Y-%m-%d")
        csv_buffer = io.StringIO()
        df_save.to_csv(csv_buffer, index=False)
        res = repo.update_file(path=file_path, message="Sync Elite Tracker", content=csv_buffer.getvalue(), sha=latest_sha)
        save_local_backup(df)
        st.session_state.connection_status['github'] = 'online'
        st.session_state.offline_mode = False
        return res['content'].sha
    except Exception as e:
        st.error(f"GitHub Sync Error: {e}")
        return None

# --- UI UTILITIES (original preserved) ---
def get_streak(df):
    if df is None or df.empty: return 0
    dates = sorted(df['Date'].dt.date.dropna().unique(), reverse=True)
    if not dates: return 0
    today = datetime.now().date()
    streak, curr = 0, today
    if dates[0] < today - timedelta(days=1): return 0
    for d in dates:
        if d == curr or d == curr - timedelta(days=1):
            streak += 1
            curr = d
        else: break
    return streak

@st.dialog("➕ Log New Study Session")
def log_session_dialog(current_date, available_skills, current_level):
    with st.form("new_entry", clear_on_submit=True):
        col_d, col_s = st.columns(2)
        d = col_d.date_input("Date", current_date)
        s = col_s.selectbox("Skill", available_skills)
        t = st.number_input("Minutes", 1, 600, 30)
        n = st.text_input("Notes")
        if st.form_submit_button("Log Entry", use_container_width=True):
            new_row = pd.DataFrame({"Date":[pd.to_datetime(d)], "Skill":[s], "Time Spent":[t], "Notes":[n]})
            updated_df = pd.concat([st.session_state.df, new_row], ignore_index=True)
            sha = save_to_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv", updated_df)
            if sha or st.session_state.offline_mode:
                st.session_state.df = updated_df
                st.session_state.file_sha = sha if sha else "local"
                st.rerun()

# --- SIDEBAR ---
with st.sidebar:
    st.header("🔑 Connection")
    st.text_input("GitHub Token", type="password", key="saved_token")
    st.text_input("Repo", key="saved_repo")
    st.text_input("Gemini API Key", type="password", key="gemini_key")
    if st.button("💾 Save Credentials", use_container_width=True):
        save_credentials_to_disk()
        st.success("Locked!")
    if st.button("🔄 Force Sync", use_container_width=True):
        load_data_from_github.clear()
        df, sha, status = load_data_from_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv")
        if status == "success" or "offline" in status:
            st.session_state.df = df
            st.session_state.file_sha = sha
            st.success("Synced!" if not st.session_state.offline_mode else "Offline backup loaded")
        else:
            st.error(status)
    st.divider()
    # Connection status banner
    st.caption(f"GitHub: {st.session_state.connection_status['github']} | Offline: {'YES' if st.session_state.offline_mode else 'NO'}")

    theme = st.selectbox("Theme", ["Emerald City", "Ocean Deep", "Sunset Orange", "Royal Purple"])
    theme_map = {"Emerald City": "#00CC96", "Ocean Deep": "#0099FF", "Sunset Orange": "#FF5733", "Royal Purple": "#8E44AD"}
    st.session_state.accent_color = theme_map[theme]
    st.slider("Weekly Goal (Hours)", 1, 40, 5, key="weekly_goal")
    st.slider("Yearly Goal (Hours)", 50, 1000, 200, step=10, key="yearly_goal")
    with st.expander("⚙️ Advanced Settings"):
        st.session_state.custom_skills = st.text_input("Custom Skills", value=st.session_state.custom_skills)

# --- MAIN UI ---
if st.session_state.df is not None:
    df = st.session_state.df.copy()
    now = datetime.now()
    all_skills = list(dict.fromkeys(["Listening", "Speaking", "Reading", "Writing", "Grammar", "Vocabulary"] + [s.strip() for s in st.session_state.custom_skills.split(',') if s.strip()] + df['Skill'].unique().tolist()))
    total_hrs = df['Time Spent'].sum() / 60
    level = int(total_hrs // 50) + 1
    xp_progress = (total_hrs % 50) / 50
    streak = get_streak(df)

    if level > st.session_state.prev_level > 0:
        st.balloons()
        st.session_state.prev_level = level
    elif st.session_state.prev_level == 0:
        st.session_state.prev_level = level

    this_week_min = df[df['Date'] >= (now - timedelta(days=now.weekday()))]['Time Spent'].sum()
    rem_min = max(0, (st.session_state.get('weekly_goal', 5) * 60) - this_week_min)

    c_title, c_btn = st.columns([3, 1])
    with c_title: st.title("🇬🇧 English Pro Elite")
    with c_btn:
        if st.button("➕ Log Study Time", type="primary", use_container_width=True):
            log_session_dialog(now, all_skills, level)

    m1, m2, m3, m4 = responsive_columns(2, 4) if st.session_state.mobile_view else st.columns(4)
    mobile_friendly_metric("Level", f"Lvl {level}")
    mobile_friendly_metric("Total", f"{total_hrs:.1f}h")
    mobile_friendly_metric("Streak", f"{streak} Days")
    mobile_friendly_metric("Pacer", f"{rem_min/60:.1f}h left")

    st.progress(xp_progress, text=f"XP to Level {level+1}")

    if not st.session_state.zen_mode:
        tab_dash, tab_trophy, tab_history, tab_share = st.tabs(["📈 Dashboard", "🏆 Trophies", "📝 History", "📸 Share Profile"])
        
        with tab_dash:
            c1, c2 = st.columns([2, 1])
            with c1:
                df_sorted = df.sort_values('Date')
                df_sorted['Cumulative_Hrs'] = df_sorted['Time Spent'].cumsum() / 60
                fig_mtn = px.area(df_sorted, x='Date', y='Cumulative_Hrs', title="Learning Mountain", color_discrete_sequence=[st.session_state.accent_color])
                fig_mtn.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color='white')
                st.plotly_chart(fig_mtn, use_container_width=True)
            with c2:
                diet = df.groupby('Skill')['Time Spent'].sum()
                fig_donut = px.pie(names=diet.index, values=diet.values, hole=0.5, title="Skill Diet")
                fig_donut.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color='white')
                st.plotly_chart(fig_donut, use_container_width=True)

        with tab_trophy:
            skill_sums = df.groupby('Skill')['Time Spent'].sum()
            badges = [("Scholar", "10h total", total_hrs >= 10), ("King", "30-day streak", streak >= 30), ("Specialist", "50h in one skill", any(skill_sums >= 3000))]
            cols = st.columns(3)
            for i, (n, d, u) in enumerate(badges):
                if u: cols[i].success(f"🌟 **{n}**\n\n{d}")
                else: cols[i].info(f"🔒 **{n}**\n\n{d}")

        with tab_history:
            edited = st.data_editor(df.sort_values("Date", ascending=False), column_config={"Date": st.column_config.DateColumn(), "Skill": st.column_config.SelectboxColumn(options=all_skills)}, use_container_width=True, hide_index=True)
            if st.button("🗑️ Commit Changes"):
                sha = save_to_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv", edited)
                if sha or st.session_state.offline_mode:
                    st.session_state.df = edited
                    st.session_state.file_sha = sha if sha else "local"
                    st.rerun()

        with tab_share:
            fav_skill = df.groupby('Skill')['Time Spent'].sum().idxmax() if not df.empty else "N/A"
            archetype_map = {"Reading": "The Sage", "Listening": "The Observer", "Speaking": "The Orator", "Writing": "The Scribe", "Grammar": "The Architect", "Vocabulary": "The Wordsmith"}
            archetype = archetype_map.get(fav_skill, "The Scholar")
            fig_share = go.Figure()
            fig_share.add_shape(type="rect", x0=0, y0=0, x1=1, y1=1, fillcolor="#111111", line_width=0)
            fig_share.add_annotation(text="ENGLISH PRO ELITE", x=0.5, y=0.9, showarrow=False, font=dict(size=16, color="#AAAAAA"))
            fig_share.add_annotation(text=f'<i>"{archetype}"</i>', x=0.5, y=0.75, showarrow=False, font=dict(size=32, color=st.session_state.accent_color, family="serif"))
            fig_share.add_annotation(text=f"<b>LEVEL {level}</b>", x=0.5, y=0.55, showarrow=False, font=dict(size=64, color="#FFFFFF"))
            fig_share.add_annotation(text=f"<b>{total_hrs:.1f}</b> HOURS STUDIED", x=0.5, y=0.35, showarrow=False, font=dict(size=18, color="#FFFFFF"))
            fig_share.add_annotation(text=f"<b>{streak}</b> DAY STREAK 🔥", x=0.5, y=0.25, showarrow=False, font=dict(size=18, color="#FFFFFF"))
            fig_share.update_layout(xaxis=dict(visible=False), yaxis=dict(visible=False), plot_bgcolor="#111111", paper_bgcolor="#111111", height=450)
            st.plotly_chart(fig_share, use_container_width=True, config={'displayModeBar': False})
            st.caption("Right-click → Save Image As")

else:
    st.info("👈 Enter Connection info in sidebar to begin.")

# --- Updated requirements.txt ---
"""
streamlit
pandas
PyGithub
plotly
google-generativeai
numpy
requests
pytz
"""
