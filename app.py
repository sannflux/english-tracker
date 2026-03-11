import streamlit as st
import pandas as pd
from github import Github
from datetime import datetime, timedelta
import io
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

# --- CONFIGURATION & SESSION STATE ---
st.set_page_config(page_title="English Pro Elite", layout="wide", page_icon="🇬🇧")

# Initialize Session States
for key in ['df', 'file_sha', 'prev_level', 'saved_token', 'saved_repo', 'accent_color']:
    if key not in st.session_state:
        st.session_state[key] = None if key not in ['prev_level'] else 0
        if key == 'accent_color': st.session_state[key] = "#00CC96"
        if key in ['saved_token', 'saved_repo']: st.session_state[key] = ""

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
            df['Date'] = df['Date'].ffill() 
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

def save_to_github(token, repo_name, file_path, df, current_sha):
    try:
        g = get_gh_client(token)
        repo = g.get_repo(repo_name)
        df_save = df.copy()
        df_save['Date'] = pd.to_datetime(df_save['Date']).dt.strftime("%A, %d %B %Y")
        csv_buffer = io.StringIO()
        df_save.to_csv(csv_buffer, index=False)
        res = repo.update_file(path=file_path, message="Sync Elite Tracker", content=csv_buffer.getvalue(), sha=current_sha)
        return res['content'].sha 
    except Exception as e:
        st.error(f"Save Error: {e}")
        return None

# --- LOGIC UTILITIES ---
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

def add_visual_tags(note):
    tags = ""
    note_l = note.lower()
    mapping = {'podcast':"🎧 ", 'listening':"🎧 ", 'audio':"🎧 ", 'bbc':"🎧 ", 
               'book':"📖 ", 'read':"📖 ", 'article':"📖 ", 'video':"📺 ", 
               'youtube':"📺 ", 'movie':"📺 ", 'write':"✍️ ", 'essay':"✍️ "}
    for word, emoji in mapping.items():
        if word in note_l: 
            tags += emoji
            break # One emoji per note is cleaner
    return f"{tags}{note}"

# --- SIDEBAR ---
with st.sidebar:
    st.header("🔑 Connection")
    gh_token = st.text_input("GitHub Token", type="password", value=st.session_state.saved_token)
    gh_repo = st.text_input("Repo", value=st.session_state.saved_repo)
    if st.checkbox("Remember Me", value=bool(st.session_state.saved_token)):
        st.session_state.saved_token, st.session_state.saved_repo = gh_token, gh_repo
    
    if st.button("🔄 Force Sync", use_container_width=True):
        load_data_from_github.clear()
        df, sha, status = load_data_from_github(gh_token, gh_repo, "data.csv")
        if status == "success":
            st.session_state.df, st.session_state.file_sha = df, sha
            st.success("Synced!")
        else: st.error(status)
                
    st.divider()
    # FEATURE 3: Theme Selector
    st.header("🎨 Styling")
    theme = st.selectbox("Accent Theme", ["Emerald City", "Ocean Deep", "Sunset Orange", "Royal Purple"])
    theme_map = {"Emerald City": "#00CC96", "Ocean Deep": "#0099FF", "Sunset Orange": "#FF5733", "Royal Purple": "#8E44AD"}
    st.session_state.accent_color = theme_map[theme]
    
    weekly_goal = st.slider("Weekly Goal (Hours)", 1, 40, 5)

# --- MAIN UI ---
if st.session_state.df is not None:
    df = st.session_state.df.copy()
    now = datetime.now()
    
    # 1. CORE CALCULATIONS & JOURNEY DATES
    start_date = df['Date'].min()
    df['Study_Week'] = ((df['Date'] - start_date).dt.days // 7) + 1
    df['Week_Label'] = "Week " + df['Study_Week'].astype(str).str.zfill(2)
    
    total_hrs = df['Time Spent'].sum() / 60
    level = int(total_hrs // 50) + 1
    xp_progress = (total_hrs % 50) / 50
    streak = get_streak(df)

    # FEATURE 2: Metrics with Deltas (vs Last Week)
    curr_week_label = "Week " + str(((now - start_date).days // 7) + 1).zfill(2)
    prev_week_label = "Week " + str(((now - start_date).days // 7)).zfill(2)
    
    this_week_hrs = df[df['Week_Label'] == curr_week_label]['Time Spent'].sum() / 60
    last_week_hrs = df[df['Week_Label'] == prev_week_label]['Time Spent'].sum() / 60
    delta_hrs = this_week_hrs - last_week_hrs

    # FEATURE 6: Motivational Coach
    st.title("🇬🇧 English Pro Elite")
    coach_placeholder = st.empty()
    if streak > 5: coach_placeholder.info(f"🔥 **Coach:** You've studied {streak} days in a row! You are becoming unstoppable.")
    elif this_week_hrs >= weekly_goal: coach_placeholder.success(f"🎯 **Coach:** Weekly goal achieved! You're in the elite 1% of learners.")
    else: coach_placeholder.warning("🚀 **Coach:** Every minute counts. Log a quick session to build momentum!")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Current Level", f"Lvl {level}")
    m2.metric("Total Study", f"{total_hrs:.1f}h")
    m3.metric("Daily Streak", f"{streak} Days", delta="Keep it up!" if streak > 0 else "Start today!")
    m4.metric("This Week", f"{this_week_hrs:.1f}h", delta=f"{delta_hrs:+.1f}h vs last week")
    st.progress(xp_progress, text=f"XP Progress to Level {level+1}")

    # FEATURE 5: Skill-Specific XP Bars
    with st.expander("📊 Detailed Skill Mastery", expanded=False):
        skill_cols = st.columns(3)
        all_skills = ["Listening", "Speaking", "Reading", "Writing", "Grammar", "Vocabulary"]
        for i, sk in enumerate(all_skills):
            sk_hrs = df[df['Skill'] == sk]['Time Spent'].sum() / 60
            sk_lvl = int(sk_hrs // 10) + 1
            sk_xp = (sk_hrs % 10) / 10
            skill_cols[i % 3].write(f"**{sk}** (Lvl {sk_lvl})")
            skill_cols[i % 3].progress(sk_xp)

    st.divider()

    # 2. ANALYSIS TABS
    tab_dashboard, tab_trophy, tab_history = st.tabs(["📈 Advanced Analytics", "🏆 Trophy Room", "📝 History Explorer"])

    with tab_dashboard:
        c1, c2 = st.columns([2, 1])
        with c1:
            # FEATURE 8: Cumulative Mountain Chart
            df_sorted = df.sort_values('Date')
            df_sorted['Cumulative_Hrs'] = df_sorted['Time Spent'].cumsum() / 60
            fig_mtn = px.area(df_sorted, x='Date', y='Cumulative_Hrs', title="The Learning Mountain (Total Hours)", color_discrete_sequence=[st.session_state.accent_color])
            st.plotly_chart(fig_mtn, use_container_width=True)
            
            # FEATURE 9: Best Day Analysis
            df['Day_Name'] = df['Date'].dt.day_name()
            day_avg = df.groupby('Day_Name')['Time Spent'].mean().reindex(['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']).fillna(0)
            fig_day = px.bar(x=day_avg.index, y=day_avg.values, title="Average Session Length by Day", color_discrete_sequence=[st.session_state.accent_color])
            st.plotly_chart(fig_day, use_container_width=True)

        with c2:
            # FEATURE 7: Skill Balance Radar
            radar_data = df.groupby('Skill')['Time Spent'].sum().reindex(all_skills).fillna(0)
            fig_radar = go.Figure(data=go.Scatterpolar(r=radar_data.values, theta=all_skills, fill='toself', line_color=st.session_state.accent_color))
            fig_radar.update_layout(polar=dict(radialaxis=dict(visible=False)), showlegend=False, title="Skill Balance Radar")
            st.plotly_chart(fig_radar, use_container_width=True)
            
            # Skill Mix Pie
            fig_pie = px.pie(df, values='Time Spent', names='Skill', hole=0.5, title="Practice Mix")
            st.plotly_chart(fig_pie, use_container_width=True)

    with tab_trophy:
        # FEATURE 4: Trophy Room Milestones
        st.subheader("🏅 Your Achievements")
        badges = [
            ("First Step", "Logged 1st session", total_hrs > 0),
            ("Novice", "Reached 10 total hours", total_hrs >= 10),
            ("Habit Builder", "Achieved 3-day streak", streak >= 3),
            ("Polymath", "Practiced all 6 skills", df['Skill'].nunique() >= 6),
            ("Deep Work", "Logged a 2hr+ session", (df['Time Spent'] >= 120).any()),
            ("Consistent", "Reached 25 total hours", total_hrs >= 25),
            ("Master", "Reached Level 10", level >= 10),
            ("Centurion", "Reached 100 total hours", total_hrs >= 100)
        ]
        cols = st.columns(4)
        for i, (name, desc, unlocked) in enumerate(badges):
            if unlocked: cols[i % 4].success(f"🌟 **{name}**\n\n{desc}")
            else: cols[i % 4].info(f"🔒 **{name}**\n\n{desc}")

    with tab_history:
        # FEATURE 1: Filtering & History
        st.subheader("🔍 Filter & Edit")
        f1, f2 = st.columns(2)
        with f1: date_range = st.date_input("Date Range", [df['Date'].min(), now])
        with f2: skill_filter = st.multiselect("Filter Skills", all_skills, default=all_skills)
        
        filtered_df = df[(df['Date'].dt.date >= date_range[0]) & 
                         (df['Date'].dt.date <= (date_range[1] if len(date_range)>1 else date_range[0])) &
                         (df['Skill'].isin(skill_filter))]
        
        display_df = filtered_df.copy().sort_values("Date", ascending=False)
        display_df['Notes'] = display_df['Notes'].apply(add_visual_tags)
        display_df['Date'] = display_df['Date'].dt.date

        edited = st.data_editor(display_df[['Date', 'Skill', 'Time Spent', 'Notes']], use_container_width=True, num_rows="dynamic")
        
        if st.button("💾 Commit History Changes", type="primary"):
            save_df = edited.copy()
            save_df['Date'] = pd.to_datetime(save_df['Date'])
            save_df['Notes'] = save_df['Notes'].str.replace('🎧 ','').str.replace('📖 ','').str.replace('📺 ','').str.replace('✍️ ','')
            new_sha = save_to_github(gh_token, gh_repo, "data.csv", save_df, st.session_state.file_sha)
            if new_sha: st.rerun()

    # FEATURE 10: Social Share Generator
    st.divider()
    share_text = f"🇬🇧 My English Study Progress:\n📊 Level: {level}\n🔥 Streak: {streak} Days\n⏱️ Total: {total_hrs:.1f} Hours\n🎯 This Week: {this_week_hrs:.1f} Hours\n#EnglishLearning #LearningTracker"
    st.code(share_text, language="markdown")
    st.button("📋 Copy Stats to Clipboard (Simulated)", on_click=lambda: st.toast("Stats copied to clipboard!"))

    # Log New Session (Original functionality preserved)
    st.divider()
    with st.expander("➕ Log New Session", expanded=False):
        with st.form("new_entry"):
            d = st.date_input("Date", now)
            s = st.selectbox("Skill", all_skills)
            t = st.number_input("Minutes", 1, 600, 30)
            n = st.text_input("Notes")
            if st.form_submit_button("Log Entry"):
                new_row = pd.DataFrame({"Date":[pd.to_datetime(d)], "Skill":[s], "Time Spent":[t], "Notes":[n]})
                st.session_state.df = pd.concat([st.session_state.df, new_row], ignore_index=True)
                save_to_github(gh_token, gh_repo, "data.csv", st.session_state.df, st.session_state.file_sha)
                st.rerun()

else:
    st.info("👈 Connect your GitHub Token and Repo in the sidebar to begin.")
