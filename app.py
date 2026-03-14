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

# --- CONFIG & PERFORMANCE PROTOCOLS ---
st.set_page_config(page_title="English Pro Elite", layout="wide", page_icon="🇬🇧")

@st.cache_resource(show_spinner=False)
def get_base64_of_bin_file(bin_file):
    if not os.path.exists(bin_file): return ""
    with open(bin_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()

def set_background(png_file):
    if 'bg_base64' not in st.session_state:
        st.session_state.bg_base64 = get_base64_of_bin_file(png_file)
    if st.session_state.bg_base64:
        st.markdown(f'''
        <style>
        .stApp {{background-image: url("data:image/png;base64,{st.session_state.bg_base64}"); background-size: cover; background-attachment: fixed;}}
        [data-testid="stSidebar"] {{background-color: rgba(0,0,0,0.7) !important; backdrop-filter: blur(10px);}}
        .stTabs [data-baseweb="tab-panel"] {{background-color: rgba(20,20,20,0.6) !important; padding: 20px; border-radius: 15px; backdrop-filter: blur(5px); border: 1px solid rgba(255,255,255,0.1);}}
        [data-testid="stMetricValue"] {{color: white !important;}}
        h1, h2, h3, h4, p, span, .stMarkdown div p {{color: white !important;}}
        .stAlert {{background-color: rgba(0,0,0,0.4) !important; color: white !important; border: 1px solid rgba(255,255,255,0.2) !important;}}
        </style>
        ''', unsafe_allow_html=True)

set_background('background.jpg')

# --- DATA STATE ENGINE ---
CRED_FILE = "credentials.json"

def load_credentials():
    creds = {}
    using_secrets = False
    try:
        if "GITHUB_TOKEN" in st.secrets:
            creds["saved_token"] = st.secrets["GITHUB_TOKEN"]
            creds["saved_repo"] = st.secrets["GITHUB_REPO"]
            creds["gemini_key"] = st.secrets["GEMINI_API_KEY"]
            creds["weekly_goal"] = st.secrets.get("WEEKLY_GOAL", 5)
            return creds, True
    except: pass
    if os.path.exists(CRED_FILE):
        try:
            with open(CRED_FILE, "r") as f: return json.load(f), False
        except: pass
    return {}, False

local_creds, using_secrets = load_credentials()

# Initialize State Keys
for key, val in {
    'df': None, 'file_sha': None, 'prev_level': 0, 'accent_color': "#00CC96",
    'zen_mode': False, 'milestone_reward': "Treat myself to coffee",
    'custom_skills': "", 'last_ai_rec': "", 'last_ai_time': None,
    'ask_ai_auto': False, 'milestone_claimed_date': "",
    'saved_token': local_creds.get('saved_token', ""),
    'saved_repo': local_creds.get('saved_repo', ""),
    'gemini_key': local_creds.get('gemini_key', ""),
    'weekly_goal': local_creds.get('weekly_goal', 5)
}.items():
    if key not in st.session_state: st.session_state[key] = val

def save_credentials_to_disk():
    creds = {
        "saved_token": st.session_state.saved_token, 
        "saved_repo": st.session_state.saved_repo, 
        "gemini_key": st.session_state.gemini_key,
        "weekly_goal": st.session_state.weekly_goal
    }
    with open(CRED_FILE, "w") as f: json.dump(creds, f)

# --- GITHUB LOGIC (HIGH PERFORMANCE) ---
@st.cache_resource(show_spinner=False)
def get_gh_client(token): return Github(token)

def save_to_github(token, repo_name, file_path, df):
    try:
        df_save = df.copy()
        df_save['Date'] = pd.to_datetime(df_save['Date']).dt.strftime("%Y-%m-%d")
        csv_buffer = io.StringIO()
        df_save.to_csv(csv_buffer, index=False)
        g = get_gh_client(token)
        repo = g.get_repo(repo_name)
        latest_sha = repo.get_contents(file_path).sha
        res = repo.update_file(path=file_path, message="Sync Elite Tracker", content=csv_buffer.getvalue(), sha=latest_sha)
        return res['content'].sha 
    except Exception as e:
        st.error(f"GitHub Sync Error: {e}")
        return None

@st.cache_data(ttl=300, show_spinner="Fetching data...")
def load_data_from_github(_token, repo_name, file_path):
    try:
        g = get_gh_client(_token)
        repo = g.get_repo(repo_name)
        contents = repo.get_contents(file_path)
        df = pd.read_csv(io.StringIO(contents.decoded_content.decode('utf-8')))
        df.columns = df.columns.str.strip()
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
            df['Date'] = df['Date'].ffill().bfill()
        df['Time Spent'] = pd.to_numeric(df['Time Spent'], errors='coerce').fillna(0)
        if 'Notes' not in df.columns: df['Notes'] = ""
        if 'Skill' not in df.columns: df['Skill'] = "General"
        return df, contents.sha, "success"
    except Exception as e: return None, None, str(e)

# --- AUTO-SYNC HANDLER ---
def handle_editor_change():
    """Triggered automatically when the data editor is edited."""
    if "editor_key" in st.session_state:
        changes = st.session_state["editor_key"]
        if changes['edited_rows'] or changes['added_rows'] or changes['deleted_rows']:
            sha = save_to_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv", st.session_state.df)
            if sha: st.session_state.file_sha = sha

# --- AUTO-LOAD TRIGGER ---
if st.session_state.df is None and st.session_state.saved_token and st.session_state.saved_repo:
    df, sha, status = load_data_from_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv")
    if status == "success":
        st.session_state.df, st.session_state.file_sha = df, sha

# --- AI COACH (STASIS MAINTAINED) ---
def get_ai_recommendation(api_key, dataframe, current_date):
    if not api_key: return "Please provide a Gemini API key."
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash-lite')
        all_time = dataframe.groupby('Skill')['Time Spent'].sum().to_dict()
        prompt = f"Expert English Coach. Totals: {all_time}. Provide one specific insight. 60 words max."
        return model.generate_content(prompt).text
    except Exception as e: return f"AI Error: {str(e)}"

# --- CALCULATED STATS ---
def get_dashboard_stats(df):
    if df is None or df.empty: return 0, 1, 0, 0
    total_hrs = df['Time Spent'].sum() / 60
    level = int(total_hrs // 50) + 1
    xp = (total_hrs % 50) / 50
    dates = sorted(df['Date'].dt.date.dropna().unique(), reverse=True)
    streak, today = 0, datetime.now().date()
    if dates and (dates[0] == today or dates[0] == today - timedelta(days=1)):
        curr = dates[0]
        for d in dates:
            if d == curr: streak += 1; curr -= timedelta(days=1)
            else: break
    return total_hrs, level, xp, streak

# --- UI DIALOGS ---
@st.dialog("➕ Log New Study Session")
def log_session_dialog(available_skills):
    with st.form("new_entry", clear_on_submit=True):
        d = st.date_input("Date", datetime.now())
        s = st.selectbox("Skill", available_skills)
        t = st.number_input("Minutes", 1, 600, 30)
        n = st.text_input("Notes")
        if st.form_submit_button("Log & Sync", use_container_width=True):
            new_row = pd.DataFrame({"Date":[pd.to_datetime(d)], "Skill":[s], "Time Spent":[t], "Notes":[n]})
            st.session_state.df = pd.concat([st.session_state.df, new_row], ignore_index=True)
            sha = save_to_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv", st.session_state.df)
            if sha: st.session_state.file_sha = sha; st.rerun()

# --- SIDEBAR ---
with st.sidebar:
    st.header("🔑 Connection")
    st.text_input("GitHub Token", type="password", key="saved_token", disabled=using_secrets)
    st.text_input("Repo", key="saved_repo", disabled=using_secrets)
    st.text_input("Gemini API Key", type="password", key="gemini_key", disabled=using_secrets)
    
    if not using_secrets:
        if st.button("💾 Save Settings Locally", use_container_width=True):
            save_credentials_to_disk()
            st.success("Saved!")

    if st.button("🔄 Refresh Data", use_container_width=True):
        load_data_from_github.clear()
        st.rerun()
        
    st.divider()
    theme = st.selectbox("Theme", ["Emerald City", "Ocean Deep", "Sunset Orange", "Royal Purple"])
    theme_map = {"Emerald City": "#00CC96", "Ocean Deep": "#0099FF", "Sunset Orange": "#FF5733", "Royal Purple": "#8E44AD"}
    st.session_state.accent_color = theme_map[theme]
    
    # FIXED: Added key="weekly_goal" for state persistence
    st.slider("Weekly Goal (Hours)", 1, 40, key="weekly_goal")
    
    st.checkbox("🧘 Zen Mode", key="zen_mode")
    st.checkbox("🔄 Auto AI Coach", key="ask_ai_auto")

# --- MAIN UI ---
if st.session_state.df is not None:
    total_hrs, level, xp, streak = get_dashboard_stats(st.session_state.df)
    all_skills = list(dict.fromkeys(["Listening", "Speaking", "Reading", "Writing", "Grammar", "Vocabulary"] + st.session_state.df['Skill'].unique().tolist()))
    
    if level > st.session_state.prev_level > 0: st.balloons(); st.session_state.prev_level = level
    elif st.session_state.prev_level == 0: st.session_state.prev_level = level

    c_title, c_btn = st.columns([3, 1])
    with c_title: st.title("🇬🇧 English Pro Elite")
    with c_btn: 
        if st.button("➕ Log Time", type="primary", use_container_width=True):
            log_session_dialog(all_skills)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Level", f"Lvl {level}")
    m2.metric("Total", f"{total_hrs:.1f}h")
    m3.metric("Streak", f"{streak} Days")
    this_week = st.session_state.df[st.session_state.df['Date'] >= (datetime.now() - timedelta(days=datetime.now().weekday()))]['Time Spent'].sum() / 60
    m4.metric("This Week", f"{this_week:.1f}/{st.session_state.weekly_goal}h")
    st.progress(xp, text=f"Progress to Level {level+1}")

    if st.session_state.ask_ai_auto and st.session_state.gemini_key:
        if not st.session_state.last_ai_time or (datetime.now() - st.session_state.last_ai_time).seconds > 3600:
            st.session_state.last_ai_rec = get_ai_recommendation(st.session_state.gemini_key, st.session_state.df, datetime.now())
            st.session_state.last_ai_time = datetime.now()
    
    if st.session_state.last_ai_rec:
        with st.expander("💡 Coach's Insight", expanded=True):
            st.write(st.session_state.last_ai_rec)

    if st.session_state.zen_mode:
        st.markdown("<style>[data-testid='stSidebar'] {display: none;} header {display: none;}</style>", unsafe_allow_html=True)
        if st.button("❌ Exit Zen"): st.session_state.zen_mode = False; st.rerun()
        st.plotly_chart(px.area(st.session_state.df.sort_values('Date'), x='Date', y='Time Spent', title="Learning Curve", color_discrete_sequence=[st.session_state.accent_color]).update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color='white'), use_container_width=True)
    else:
        tab_dash, tab_history, tab_trophy = st.tabs(["📈 Dashboard", "📝 History", "🏆 Trophies"])
        
        with tab_dash:
            c1, c2 = st.columns([2, 1])
            with c1:
                st.plotly_chart(px.area(st.session_state.df.sort_values('Date'), x='Date', y='Time Spent', title="Study Mountain", color_discrete_sequence=[st.session_state.accent_color]).update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color='white'), use_container_width=True)
            with c2:
                diet = st.session_state.df.groupby('Skill')['Time Spent'].sum()
                st.plotly_chart(px.pie(names=diet.index, values=diet.values, hole=0.5, title="Skill Diet").update_layout(showlegend=False, plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color='white'), use_container_width=True)

        with tab_history:
            st.info("💡 Changes made below are auto-synced to GitHub.")
            st.session_state.df = st.data_editor(
                st.session_state.df.sort_values("Date", ascending=False),
                column_config={"Date": st.column_config.DateColumn(), "Skill": st.column_config.SelectboxColumn(options=all_skills)},
                use_container_width=True,
                hide_index=True,
                key="editor_key",
                on_change=handle_editor_change
            )

        with tab_trophy:
            st.subheader("🎁 Today's Milestone Reward")
            if st.session_state.milestone_claimed_date != datetime.now().date().isoformat():
                if st.button(f"Claim: {st.session_state.milestone_reward}"):
                    st.success("Claimed!")
                    st.session_state.milestone_claimed_date = datetime.now().date().isoformat()
                    st.balloons()
            else: st.success("Reward claimed for today!")
else:
    st.warning("👈 Provide GitHub credentials in the sidebar to auto-load your data.")
