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

# --- CONFIGURATION & SESSION STATE ---
st.set_page_config(page_title="English Pro Elite", layout="wide", page_icon="🇬🇧")

# Persistent Credential Loader
CRED_FILE = "credentials.json"
def load_credentials():
    if os.path.exists(CRED_FILE):
        try:
            with open(CRED_FILE, "r") as f:
                return json.load(f)
        except: return {}
    return {}

def save_credentials_to_disk():
    creds = {
        "saved_token": st.session_state.saved_token,
        "saved_repo": st.session_state.saved_repo,
        "gemini_key": st.session_state.gemini_key
    }
    with open(CRED_FILE, "w") as f:
        json.dump(creds, f)

local_creds = load_credentials()

# Initialize Session States
for key in ['df', 'file_sha', 'prev_level', 'saved_token', 'saved_repo', 'accent_color', 'zen_mode', 'milestone_reward', 'gemini_key', 'custom_skills', 'last_ai_rec']:
    if key not in st.session_state:
        st.session_state[key] = None if key not in ['prev_level'] else 0
        if key == 'accent_color': st.session_state[key] = "#00CC96"
        if key == 'zen_mode': st.session_state[key] = False
        if key == 'milestone_reward': st.session_state[key] = "Treat myself to coffee"
        if key == 'custom_skills': st.session_state[key] = ""
        if key == 'last_ai_rec': st.session_state[key] = ""
        
        if key in ['saved_token', 'saved_repo', 'gemini_key']:
            st.session_state[key] = local_creds.get(key, "")

# --- AI COACH LOGIC (GEMINI) ---
def get_ai_recommendation(api_key, dataframe, current_date):
    if not api_key: return "Please provide a Gemini API key in the sidebar."
    try:
        genai.configure(api_key=api_key)
        # STRICT MODEL LOCK
        model = genai.GenerativeModel('gemini-2.5-flash-lite')
        all_time_summary = dataframe.groupby('Skill')['Time Spent'].sum().to_dict()
        last_7_days_df = dataframe[dataframe['Date'].dt.date >= (current_date.date() - timedelta(days=7))]
        recent_summary = last_7_days_df.groupby('Skill')['Time Spent'].sum().to_dict()
        prompt = f"Act as an expert English Study Coach. Here is my data: All-Time: {all_time_summary}, Last 7 Days: {recent_summary}. Focus on current neglect vs all-time strength. 100 words max."
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI Error: {str(e)}"

# --- GITHUB HELPER ---
@st.cache_resource(show_spinner=False)
def get_gh_client(token):
    return Github(token)

@st.cache_data(ttl=300, show_spinner=False)
def load_data_from_github(_token, repo_name, file_path):
    try:
        g = get_gh_client(_token)
        repo = g.get_repo(repo_name)
        contents = repo.get_contents(file_path)
        decoded_string = contents.decoded_content.decode('utf-8')
        df = pd.read_csv(io.StringIO(decoded_string))
        df.columns = df.columns.str.strip()
        df.replace(r'^\s*$', np.nan, regex=True, inplace=True)
        if 'Date' in df.columns:
            df['Date'] = df['Date'].apply(lambda x: str(x).split(',')[-1].strip() if ',' in str(x) else x)
            df['Date'] = pd.to_datetime(df['Date'], format='mixed', errors='coerce', dayfirst=True)
            df['Date'] = df['Date'].ffill().bfill()
        if 'Skill' in df.columns: df['Skill'] = df['Skill'].astype(str).str.strip().ffill().fillna("Reading")
        if 'Time Spent' in df.columns: df['Time Spent'] = pd.to_numeric(df['Time Spent'], errors='coerce').fillna(0)
        if 'Notes' not in df.columns: df['Notes'] = ""
        return df, contents.sha, "success"
    except Exception as e: return None, None, str(e)

def save_to_github(token, repo_name, file_path, df):
    try:
        g = get_gh_client(token)
        repo = g.get_repo(repo_name)
        latest_sha = repo.get_contents(file_path).sha
        df_save = df.copy()
        df_save['Date'] = pd.to_datetime(df_save['Date']).dt.strftime("%Y-%m-%d")
        csv_buffer = io.StringIO()
        df_save.to_csv(csv_buffer, index=False)
        res = repo.update_file(path=file_path, message="Sync Elite Tracker", content=csv_buffer.getvalue(), sha=latest_sha)
        return res['content'].sha 
    except Exception as e:
        st.error(f"GitHub Sync Error: {e}")
        return None

# --- UI UTILITIES ---
def get_streak(df):
    if df is None or df.empty: return 0
    dates = sorted(df['Date'].dt.date.dropna().unique(), reverse=True)
    if not dates: return 0
    today, streak, curr = datetime.now().date(), 0, datetime.now().date()
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
        t = st.number_input("Minutes Spent", 1, 600, 30)
        n = st.text_input("Notes")
        if st.form_submit_button("Log Entry", use_container_width=True):
            new_row = pd.DataFrame({"Date":[pd.to_datetime(d)], "Skill":[s], "Time Spent":[t], "Notes":[n]})
            updated_df = pd.concat([st.session_state.df, new_row], ignore_index=True)
            new_sha = save_to_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv", updated_df)
            if new_sha:
                st.session_state.df, st.session_state.file_sha = updated_df, new_sha
                st.session_state.prev_level = current_level 
                st.rerun()

# --- SIDEBAR ---
with st.sidebar:
    st.header("🔑 Connection")
    st.text_input("GitHub Token", type="password", key="saved_token")
    st.text_input("Repo", key="saved_repo")
    st.text_input("Gemini API Key", type="password", key="gemini_key")
    if st.button("💾 Save Credentials", use_container_width=True): save_credentials_to_disk(); st.success("Locked!")
    if st.button("🔄 Force Sync", use_container_width=True):
        load_data_from_github.clear()
        df, sha, status = load_data_from_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv")
        if status == "success": st.session_state.df, st.session_state.file_sha = df, sha; st.success("Synced!")
        else: st.error(status)
    st.divider()
    theme = st.selectbox("Theme", ["Emerald City", "Ocean Deep", "Sunset Orange", "Royal Purple"])
    theme_map = {"Emerald City": "#00CC96", "Ocean Deep": "#0099FF", "Sunset Orange": "#FF5733", "Royal Purple": "#8E44AD"}
    st.session_state.accent_color = theme_map[theme]
    weekly_goal = st.slider("Weekly Goal (Hours)", 1, 40, 5)
    yearly_goal = st.slider("Yearly Goal (Hours)", 50, 1000, 200, step=10)
    with st.expander("⚙️ Advanced Settings"):
        st.session_state.custom_skills = st.text_input("Custom Skills", value=st.session_state.custom_skills)
        if st.session_state.df is not None:
            st.divider()
            old_sk = st.selectbox("Rename Skill", options=sorted(st.session_state.df['Skill'].unique().tolist()))
            new_sk = st.text_input("New Name")
            if st.button("🚀 Bulk Rename"):
                if new_sk.strip():
                    up_df = st.session_state.df.copy()
                    up_df['Skill'] = up_df['Skill'].replace(old_sk, new_sk.strip())
                    sha = save_to_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv", up_df)
                    if sha: st.session_state.df, st.session_state.file_sha = up_df, sha; st.rerun()

# --- MAIN UI ---
if st.session_state.df is not None:
    df, now = st.session_state.df.copy(), datetime.now()
    all_skills = list(dict.fromkeys(["Listening", "Speaking", "Reading", "Writing", "Grammar", "Vocabulary"] + [s.strip() for s in st.session_state.custom_skills.split(',') if s.strip()] + df['Skill'].unique().tolist()))
    total_hrs = df['Time Spent'].sum() / 60
    level = int(total_hrs // 50) + 1
    xp_progress = (total_hrs % 50) / 50
    streak = get_streak(df)

    if level > st.session_state.prev_level > 0: st.balloons(); st.session_state.prev_level = level
    elif st.session_state.prev_level == 0: st.session_state.prev_level = level

    this_week_min = df[df['Date'] >= (now - timedelta(days=now.weekday()))]['Time Spent'].sum()
    rem_min = max(0, (weekly_goal * 60) - this_week_min)
    
    c_title, c_btn = st.columns([3, 1])
    c_title.title("🇬🇧 English Pro Elite")
    if c_btn.button("➕ Log Study Time", type="primary", use_container_width=True): log_session_dialog(now, all_skills, level)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Level", f"Lvl {level}"); m2.metric("Total", f"{total_hrs:.1f}h"); m3.metric("Streak", f"{streak} Days"); m4.metric("Pacer", f"{rem_min/60:.1f}h left")
    st.progress(xp_progress, text=f"XP to Level {level+1}")

    if not st.session_state.zen_mode:
        tab_dash, tab_trophy, tab_history, tab_share = st.tabs(["📈 Dashboard", "🏆 Trophies", "📝 History", "📸 Share Profile"])
        
        with tab_dash:
            c1, c2 = st.columns([2, 1])
            with c1:
                df_sorted = df.sort_values('Date')
                df_sorted['Cumulative_Hrs'] = df_sorted['Time Spent'].cumsum() / 60
                st.plotly_chart(px.area(df_sorted, x='Date', y='Cumulative_Hrs', title="Learning Mountain", color_discrete_sequence=[st.session_state.accent_color]), use_container_width=True)
            with c2:
                diet = df.groupby('Skill')['Time Spent'].sum()
                fig_donut = px.pie(names=diet.index, values=diet.values, hole=0.5, title="Skill Diet")
                fig_donut.update_traces(textinfo='label+percent', textposition='inside'); fig_donut.update_layout(showlegend=False)
                st.plotly_chart(fig_donut, use_container_width=True)

        with tab_trophy:
            skill_sums = df.groupby('Skill')['Time Spent'].sum()
            badges = [("Elite Scholar", "Level 10 reached", level >= 10), ("Streak King", "30-day streak", streak >= 30), ("Specialist", "50h in one skill", any(skill_sums >= 3000))]
            cols = st.columns(3)
            for i, (n, d, u) in enumerate(badges):
                if u: cols[i].success(f"🌟 **{n}**\n\n{d}")
                else: cols[i].info(f"🔒 **{n}**\n\n{d}")

        with tab_history:
            edited = st.data_editor(df.sort_values("Date", ascending=False), column_config={"Date": st.column_config.DateColumn(), "Skill": st.column_config.SelectboxColumn(options=all_skills)}, use_container_width=True, hide_index=True)
            if st.button("🗑️ Commit Changes"):
                sha = save_to_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv", edited)
                if sha: st.session_state.df = edited; st.rerun()

        with tab_share:
            st.subheader("📸 Your Elite Scholar Profile")
            # --- COMPOSITE SHARE CARD ---
            fav_skill = df.groupby('Skill')['Time Spent'].sum().idxmax() if not df.empty else "None"
            archetype_map = {"Reading": "The Sage", "Listening": "The Observer", "Speaking": "The Orator", "Writing": "The Scribe", "Grammar": "The Architect", "Vocabulary": "The Wordsmith"}
            archetype = archetype_map.get(fav_skill, "The Generalist")
            
            fig_share = go.Figure()
            # Background Gradient
            fig_share.add_shape(type="rect", x0=0, y0=0, x1=1, y1=1, xref="paper", yref="paper", fillcolor=st.session_state.accent_color, opacity=0.1, line_width=0)
            # Texts
            fig_share.add_annotation(text="ENGLISH PRO ELITE", xref="paper", yref="paper", x=0.5, y=0.9, showarrow=False, font=dict(size=18, color="gray", variant="small-caps"))
            fig_share.add_annotation(text=archetype, xref="paper", yref="paper", x=0.5, y=0.75, showarrow=False, font=dict(size=42, color=st.session_state.accent_color, family="serif"))
            fig_share.add_annotation(text=f"Level {level}", xref="paper", yref="paper", x=0.5, y=0.55, showarrow=False, font=dict(size=80, weight="bold"))
            fig_share.add_annotation(text=f"{total_hrs:.1f} Total Hours  •  {streak} Day Streak", xref="paper", yref="paper", x=0.5, y=0.35, showarrow=False, font=dict(size=24))
            # XP Bar visual on card
            fig_share.add_shape(type="rect", x0=0.2, y0=0.2, x1=0.8, y1=0.25, xref="paper", yref="paper", line_color="lightgray", fillcolor="white")
            fig_share.add_shape(type="rect", x0=0.2, y0=0.2, x1=0.2 + (0.6 * xp_progress), y1=0.25, xref="paper", yref="paper", fillcolor=st.session_state.accent_color, line_width=0)
            
            fig_share.update_layout(xaxis=dict(visible=False), yaxis=dict(visible=False), plot_bgcolor="white", margin=dict(l=0,r=0,t=0,b=0), height=500)
            st.plotly_chart(fig_share, use_container_width=True, config={'displayModeBar': False})
            st.caption("Tip: Use the browser screenshot tool or right-click to save your profile card.")

else: st.info("👈 Enter Connection info in sidebar to begin.")
