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
        
        prompt = f"""
        Act as an expert English Study Coach. Here is my study data:
        - All-Time Totals (Minutes): {all_time_summary}
        - Last 7 Days (Minutes): {recent_summary}
        
        Based on my recent habits vs my all-time strengths, identify what I need to focus on right now. 
        Suggest a specific 30-minute activity I should do today to improve. Keep it under 100 words.
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI Error: {str(e)}"

# --- GITHUB HELPER FUNCTIONS ---
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
        if 'Skill' in df.columns:
            df['Skill'] = df['Skill'].astype(str).str.strip().ffill().fillna("Reading")
        if 'Time Spent' in df.columns:
            df['Time Spent'] = pd.to_numeric(df['Time Spent'], errors='coerce').fillna(0)
        if 'Notes' not in df.columns: df['Notes'] = ""
        df['Notes'] = df['Notes'].fillna("")
        
        return df, contents.sha, "success"
    except Exception as e:
        return None, None, str(e)

def save_to_github(token, repo_name, file_path, df):
    try:
        g = get_gh_client(token)
        repo = g.get_repo(repo_name)
        latest_contents = repo.get_contents(file_path)
        latest_sha = latest_contents.sha
        
        df_save = df.copy()
        df_save['Date'] = pd.to_datetime(df_save['Date']).dt.strftime("%Y-%m-%d")
        csv_buffer = io.StringIO()
        df_save.to_csv(csv_buffer, index=False)
        
        res = repo.update_file(
            path=file_path, 
            message="Sync Elite Tracker Update", 
            content=csv_buffer.getvalue(), 
            sha=latest_sha
        )
        return res['content'].sha 
    except Exception as e:
        st.error(f"GitHub Sync Error: {e}")
        return None

# --- UI UTILITIES ---
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
        st.write("Record your progress below:")
        col_d, col_s = st.columns(2)
        d = col_d.date_input("Date", current_date)
        s = col_s.selectbox("Skill", available_skills)
        t = st.number_input("Minutes Spent", 1, 600, 30)
        n = st.text_input("Session Notes (Optional)")
        
        if st.form_submit_button("Log Entry", use_container_width=True):
            new_row = pd.DataFrame({"Date":[pd.to_datetime(d)], "Skill":[s], "Time Spent":[t], "Notes":[n]})
            updated_df = pd.concat([st.session_state.df, new_row], ignore_index=True)
            
            new_sha = save_to_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv", updated_df)
            if new_sha:
                st.session_state.df = updated_df
                st.session_state.file_sha = new_sha
                st.session_state.prev_level = current_level 
                st.rerun()

# --- SIDEBAR ---
with st.sidebar:
    st.header("🔑 Connection")
    st.text_input("GitHub Token", type="password", key="saved_token")
    st.text_input("Repo", key="saved_repo")
    st.text_input("Gemini API Key", type="password", key="gemini_key")
    
    if st.button("💾 Save Credentials", use_container_width=True):
        save_credentials_to_disk()
        st.success("Credentials locked persistently!")
    
    if st.button("🔄 Force Sync", use_container_width=True):
        load_data_from_github.clear()
        df, sha, status = load_data_from_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv")
        if status == "success":
            st.session_state.df, st.session_state.file_sha = df, sha
            st.success("Synced!")
        else: st.error(status)
                
    st.divider()
    
    can_undo = st.session_state.df is not None and len(st.session_state.df) > 1
    if st.button("↩️ Undo Last Log", use_container_width=True, disabled=not can_undo):
        undo_df = st.session_state.df.iloc[:-1]
        new_sha = save_to_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv", undo_df)
        if new_sha:
            st.session_state.df = undo_df
            st.session_state.file_sha = new_sha
            st.toast("Reverted last log!")
            st.rerun()

    if st.session_state.df is not None:
        st.header("🤖 AI Study Coach")
        if st.button("Ask Coach"):
            with st.spinner("Analyzing history..."):
                now = datetime.now()
                st.session_state.last_ai_rec = get_ai_recommendation(st.session_state.gemini_key, st.session_state.df, now)
        if st.session_state.last_ai_rec:
            st.info(st.session_state.last_ai_rec)

    st.divider()
    st.session_state.zen_mode = st.toggle("🧘 Zen Mode", value=st.session_state.zen_mode)
    
    theme = st.selectbox("Theme", ["Emerald City", "Ocean Deep", "Sunset Orange", "Royal Purple"])
    theme_map = {"Emerald City": "#00CC96", "Ocean Deep": "#0099FF", "Sunset Orange": "#FF5733", "Royal Purple": "#8E44AD"}
    st.session_state.accent_color = theme_map[theme]
    
    weekly_goal = st.slider("Weekly Goal (Hours)", 1, 40, 5)
    yearly_goal = st.slider("Yearly Goal (Hours)", 50, 1000, 200, step=10)

    with st.expander("⚙️ Advanced Settings"):
        st.session_state.custom_skills = st.text_input("Custom Skills (comma separated)", value=st.session_state.custom_skills)
        
        if st.session_state.df is not None:
            st.divider()
            st.markdown("🛠️ **Skill Renaming Tool**")
            current_skills = sorted(st.session_state.df['Skill'].unique().tolist())
            old_skill = st.selectbox("Select Skill to Rename", options=current_skills)
            new_skill_name = st.text_input("Enter New Name", placeholder="e.g., Reading Analysis")
            
            if st.button("🚀 Bulk Rename & Sync", use_container_width=True):
                if new_skill_name.strip():
                    with st.spinner("Refactoring data..."):
                        updated_df = st.session_state.df.copy()
                        updated_df['Skill'] = updated_df['Skill'].replace(old_skill, new_skill_name.strip())
                        success_sha = save_to_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv", updated_df)
                        if success_sha:
                            st.session_state.df = updated_df
                            st.session_state.file_sha = success_sha
                            st.success(f"Renamed '{old_skill}' to '{new_skill_name}'!")
                            st.rerun()

# --- MAIN UI ---
if st.session_state.df is not None:
    df = st.session_state.df.copy()
    now = datetime.now()
    
    base_skills = ["Listening", "Speaking", "Reading", "Writing", "Grammar", "Vocabulary"]
    extra_skills = [s.strip() for s in st.session_state.custom_skills.split(',') if s.strip()]
    historical_skills = df['Skill'].dropna().unique().tolist()
    all_skills = list(dict.fromkeys(base_skills + extra_skills + historical_skills))
    
    total_hrs = df['Time Spent'].sum() / 60
    level = int(total_hrs // 50) + 1
    xp_progress = (total_hrs % 50) / 50
    streak = get_streak(df)

    if level > st.session_state.prev_level and st.session_state.prev_level != 0:
        st.balloons()
        st.session_state.prev_level = level
    elif st.session_state.prev_level == 0:
        st.session_state.prev_level = level

    this_week_min = df[df['Date'] >= (now - timedelta(days=now.weekday()))]['Time Spent'].sum()
    remaining_min = max(0, (weekly_goal * 60) - this_week_min)
    days_left = 7 - now.weekday()
    pace = remaining_min / days_left if days_left > 0 else remaining_min

    c_title, c_btn = st.columns([3, 1])
    with c_title:
        st.title("🇬🇧 English Pro Elite")
    with c_btn:
        st.write("") 
        if st.button("➕ Log Study Time", type="primary", use_container_width=True):
            log_session_dialog(now, all_skills, level)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Level", f"Lvl {level}")
    m2.metric("Total", f"{total_hrs:.1f}h")
    m3.metric("Streak", f"{streak} Days")
    m4.metric("Pacer", f"{remaining_min/60:.1f}h left", f"{pace:.0f}m / day")
    st.progress(xp_progress, text=f"XP to Level {level+1}")

    if not st.session_state.zen_mode:
        st.divider()
        tab_dash, tab_insights, tab_trophy, tab_history, tab_share = st.tabs(["📈 Dashboard", "🧠 Insights", "🏆 Trophies", "📝 History", "📸 Share Profile"])

        with tab_dash:
            c1, c2 = st.columns([2, 1])
            with c1:
                st.subheader("🗓️ Study Intensity")
                df_2026 = df[df['Date'].dt.year == now.year].copy()
                if not df_2026.empty:
                    df_2026['Day'] = df_2026['Date'].dt.day_name()
                    df_2026['Week_Num'] = df_2026['Date'].dt.isocalendar().week
                    day_map = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                    hm_pivot = df_2026.pivot_table(index='Day', columns='Week_Num', values='Time Spent', aggfunc='sum').reindex(day_map).fillna(0)
                    fig_gh = px.imshow(hm_pivot, color_continuous_scale='Greens', aspect="auto")
                    fig_gh.update_layout(height=250, margin=dict(l=0,r=0,t=0,b=0), coloraxis_showscale=False)
                    st.plotly_chart(fig_gh, use_container_width=True)
                
                df_sorted = df.sort_values('Date')
                df_sorted['Cumulative_Hrs'] = df_sorted['Time Spent'].cumsum() / 60
                fig_mtn = px.area(df_sorted, x='Date', y='Cumulative_Hrs', title="Learning Mountain", color_discrete_sequence=[st.session_state.accent_color])
                st.plotly_chart(fig_mtn, use_container_width=True)
                
            with c2:
                st.subheader("Skill Diet")
                if not df.empty:
                    diet_data = df.groupby('Skill')['Time Spent'].sum()
                    fig_donut = px.pie(names=diet_data.index, values=diet_data.values, hole=0.5)
                    fig_donut.update_traces(textinfo='label+percent', textposition='inside')
                    fig_donut.update_layout(showlegend=False, height=250, margin=dict(l=20,r=20,t=20,b=20))
                    st.plotly_chart(fig_donut, use_container_width=True)

                    radar_data = diet_data.reindex(all_skills).fillna(0)
                    fig_radar = go.Figure(data=go.Scatterpolar(r=radar_data.values, theta=all_skills, fill='toself', line_color=st.session_state.accent_color))
                    fig_radar.update_layout(polar=dict(radialaxis=dict(visible=False)), showlegend=False, height=250)
                    st.plotly_chart(fig_radar, use_container_width=True)

        with tab_trophy:
            st.subheader("🏆 Dynamic Trophy Room")
            badges = [("Scholar", "10h total", total_hrs >= 10), ("Elite", "Level 10", level >= 10), ("King", "30-day streak", streak >= 30)]
            cols = st.columns(3)
            for i, (name, desc, unlocked) in enumerate(badges):
                if unlocked: cols[i].success(f"🌟 **{name}**\n\n{desc}")
                else: cols[i].info(f"🔒 **{name}**\n\n{desc}")

        with tab_history:
            display_df = df.copy().sort_values("Date", ascending=False)
            display_df['Delete'] = False
            edited_hist = st.data_editor(display_df[['Delete', 'Date', 'Skill', 'Time Spent', 'Notes']], use_container_width=True, hide_index=True)
            if st.button("🗑️ Commit Changes", type="primary"):
                filtered_save = edited_hist[edited_hist['Delete'] == False].drop(columns=['Delete'])
                new_sha = save_to_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv", filtered_save)
                if new_sha: st.session_state.df = filtered_save; st.rerun()

        with tab_share:
            st.subheader("📸 Your Scholar Profile Card")
            
            # Archetype Logic
            fav_skill = df.groupby('Skill')['Time Spent'].sum().idxmax() if not df.empty else "N/A"
            archetype_map = {
                "Reading": "The Sage", "Listening": "The Observer", 
                "Speaking": "The Orator", "Writing": "The Scribe",
                "Grammar": "The Architect", "Vocabulary": "The Wordsmith"
            }
            archetype = archetype_map.get(fav_skill, "The Scholar")
            
            # --- COMPOSITE CARD DESIGN ---
            fig_share = go.Figure()

            # Background Color / Tint
            fig_share.add_shape(type="rect", x0=0, y0=0, x1=1, y1=1, xref="paper", yref="paper", 
                               fillcolor=st.session_state.accent_color, opacity=0.05, line_width=0)

            # Archetype & Header
            fig_share.add_annotation(text="ENGLISH PRO ELITE", xref="paper", yref="paper", x=0.5, y=0.92, showarrow=False, 
                                     font=dict(size=16, color="gray", variant="small-caps"))
            fig_share.add_annotation(text=archetype, xref="paper", yref="paper", x=0.5, y=0.8, showarrow=False, 
                                     font=dict(size=38, color=st.session_state.accent_color, family="serif", weight="bold"))

            # Level Circle Visual (Simulated with text)
            fig_share.add_annotation(text=f"LEVEL", xref="paper", yref="paper", x=0.5, y=0.62, showarrow=False, font=dict(size=14, color="gray"))
            fig_share.add_annotation(text=str(level), xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False, font=dict(size=90, weight="bold"))

            # Stats Row
            fig_share.add_annotation(text=f"<b>{total_hrs:.1f}</b> Hours Total  •  <b>{streak}</b> Day Streak", 
                                     xref="paper", yref="paper", x=0.5, y=0.32, showarrow=False, font=dict(size=22))

            # Progress Bar on Card
            fig_share.add_shape(type="rect", x0=0.2, y0=0.2, x1=0.8, y1=0.24, xref="paper", yref="paper", line_color="lightgray", fillcolor="white")
            fig_share.add_shape(type="rect", x0=0.2, y0=0.2, x1=0.2 + (0.6 * xp_progress), y1=0.24, xref="paper", yref="paper", fillcolor=st.session_state.accent_color, line_width=0)
            fig_share.add_annotation(text="XP to Next Level", xref="paper", yref="paper", x=0.5, y=0.15, showarrow=False, font=dict(size=12, color="gray"))

            fig_share.update_layout(xaxis=dict(visible=False), yaxis=dict(visible=False), plot_bgcolor="white", 
                                  margin=dict(l=0, r=0, t=0, b=0), height=550)
            
            st.plotly_chart(fig_share, use_container_width=True, config={'displayModeBar': False})
            st.info("💡 **Tip:** Right-click the image to 'Save Image As' and share your progress!")

else:
    st.info("👈 Enter Connection info in sidebar to begin.")
