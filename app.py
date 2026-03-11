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
for key in ['df', 'file_sha', 'prev_level', 'saved_token', 'saved_repo', 'accent_color', 'zen_mode', 'milestone_reward']:
    if key not in st.session_state:
        st.session_state[key] = None if key not in ['prev_level'] else 0
        if key == 'accent_color': st.session_state[key] = "#00CC96"
        if key == 'zen_mode': st.session_state[key] = False
        if key == 'milestone_reward': st.session_state[key] = "Treat myself to coffee"
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

def add_visual_tags(note):
    mapping = {'podcast':"🎧 ", 'listening':"🎧 ", 'bbc':"🎧 ", 'book':"📖 ", 'read':"📖 ", 'video':"📺 ", 'youtube':"📺 ", 'write':"✍️ "}
    for word, emoji in mapping.items():
        if word in str(note).lower(): return f"{emoji}{note}"
    return note

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
    # FEATURE 7: Zen Mode Toggle
    st.session_state.zen_mode = st.toggle("🧘 Zen Mode (Focus)", value=st.session_state.zen_mode)
    
    # FEATURE 3: Study Routine Templates
    st.header("📋 Routines")
    if st.button("☀️ Morning Sprint (15m Reading)"):
        new_r = pd.DataFrame({"Date":[pd.to_datetime(datetime.now().date())], "Skill":["Reading"], "Time Spent":[15], "Notes":["Morning Routine"]})
        st.session_state.df = pd.concat([st.session_state.df, new_r], ignore_index=True)
        save_to_github(gh_token, gh_repo, "data.csv", st.session_state.df, st.session_state.file_sha)
        st.rerun()

    st.divider()
    st.header("🎨 Styling")
    theme = st.selectbox("Accent Theme", ["Emerald City", "Ocean Deep", "Sunset Orange", "Royal Purple"])
    theme_map = {"Emerald City": "#00CC96", "Ocean Deep": "#0099FF", "Sunset Orange": "#FF5733", "Royal Purple": "#8E44AD"}
    st.session_state.accent_color = theme_map[theme]
    
    weekly_goal = st.slider("Weekly Goal (Hours)", 1, 40, 5)

# --- MAIN UI ---
if st.session_state.df is not None:
    df = st.session_state.df.copy()
    now = datetime.now()
    all_skills = ["Listening", "Speaking", "Reading", "Writing", "Grammar", "Vocabulary"]
    
    # CALCULATIONS
    start_date = df['Date'].min()
    df['Study_Week'] = ((df['Date'] - start_date).dt.days // 7) + 1
    df['Week_Label'] = "Week " + df['Study_Week'].astype(str).str.zfill(2)
    total_hrs = df['Time Spent'].sum() / 60
    level = int(total_hrs // 50) + 1
    xp_progress = (total_hrs % 50) / 50
    streak = get_streak(df)

    # FEATURE 2: Weekly Pacer
    curr_week_label = "Week " + str(((now - start_date).days // 7) + 1).zfill(2)
    this_week_min = df[df['Week_Label'] == curr_week_label]['Time Spent'].sum()
    remaining_min = max(0, (weekly_goal * 60) - this_week_min)
    days_left = 7 - now.weekday()
    pace = remaining_min / days_left if days_left > 0 else remaining_min

    # FEATURE 5: Burnout Predictor
    daily_sum = df.groupby(df['Date'].dt.date)['Time Spent'].sum()
    burnout = (daily_sum.tail(4) > 180).all()

    # HEADER & REWARD
    st.title("🇬🇧 English Pro Elite")
    # FEATURE 8: Milestone Reward
    with st.expander(f"🎁 Next Level Reward: {st.session_state.milestone_reward}", expanded=False):
        st.session_state.milestone_reward = st.text_input("Edit Reward", value=st.session_state.milestone_reward)

    if burnout: st.warning("⚠️ **Burnout Warning:** You've studied heavily for 4 days. Consider a 'Lite' 15m day to protect your health!")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Current Level", f"Lvl {level}")
    m2.metric("Total Study", f"{total_hrs:.1f}h")
    m3.metric("Daily Streak", f"{streak} Days")
    m4.metric("Weekly Pacer", f"{remaining_min/60:.1f}h left", f"{pace:.0f}m / day needed", delta_color="inverse")
    st.progress(xp_progress, text=f"XP Progress to Level {level+1}")

    if not st.session_state.zen_mode:
        st.divider()
        tab_dash, tab_insights, tab_trophy, tab_history = st.tabs(["📈 Dashboard", "🧠 Deep Insights", "🏆 Trophies", "📝 History"])

        with tab_dash:
            c1, c2 = st.columns([2, 1])
            with c1:
                # Cumulative Mountain
                df_sorted = df.sort_values('Date')
                df_sorted['Cumulative_Hrs'] = df_sorted['Time Spent'].cumsum() / 60
                st.plotly_chart(px.area(df_sorted, x='Date', y='Cumulative_Hrs', title="The Learning Mountain", color_discrete_sequence=[st.session_state.accent_color]), use_container_width=True)
            with c2:
                # FEATURE 1: Target Skill Balancer
                radar_data = df.groupby('Skill')['Time Spent'].sum().reindex(all_skills).fillna(0)
                fig_radar = go.Figure(data=go.Scatterpolar(r=radar_data.values, theta=all_skills, fill='toself', line_color=st.session_state.accent_color))
                fig_radar.add_trace(go.Scatterpolar(r=[total_hrs/6]*6, theta=all_skills, fill='none', name='Ideal Balance', line=dict(dash='dash', color='gray')))
                fig_radar.update_layout(polar=dict(radialaxis=dict(visible=False)), showlegend=False, title="Skill Diet Balancer")
                st.plotly_chart(fig_radar, use_container_width=True)

        with tab_insights:
            i1, i2 = st.columns(2)
            with i1:
                # FEATURE 4: On This Day
                target_past = (now - timedelta(days=30)).date()
                past_data = df[df['Date'].dt.date == target_past]
                st.subheader("🕰️ Time Machine (30 Days Ago)")
                if not past_data.empty:
                    st.info(f"On {target_past}, you studied **{past_data['Time Spent'].sum()}m**. Notes: *{past_data['Notes'].iloc[0]}*")
                else: st.write("No data for this day last month. Start logging to build history!")
            with i2:
                # FEATURE 6: Skill Pairing Heatmap
                df['Date_Only'] = df['Date'].dt.date
                pivot = df.groupby(['Date_Only', 'Skill']).size().unstack(fill_value=0)
                corr = pivot.corr().fillna(0)
                st.plotly_chart(px.imshow(corr, text_auto=True, title="Skill Pairing (What do you study together?)", color_continuous_scale="Purples"), use_container_width=True)

        with tab_trophy:
            badges = [("First Step", "Logged 1st session", total_hrs > 0), ("Novice", "10 total hours", total_hrs >= 10), ("Master", "Level 10", level >= 10)]
            cols = st.columns(3)
            for i, (name, desc, unlocked) in enumerate(badges):
                if unlocked: cols[i].success(f"🌟 **{name}**\n\n{desc}")
                else: cols[i].info(f"🔒 **{name}**\n\n{desc}")

        with tab_history:
            # FEATURE 9: Interactive Deletion
            display_df = df.copy().sort_values("Date", ascending=False)
            display_df['Delete'] = False
            display_df['Date'] = display_df['Date'].dt.date
            
            edited_hist = st.data_editor(display_df[['Delete', 'Date', 'Skill', 'Time Spent', 'Notes']], use_container_width=True)
            
            if st.button("🗑️ Delete Selected / Save Changes", type="primary"):
                filtered_save = edited_hist[edited_hist['Delete'] == False].drop(columns=['Delete'])
                filtered_save['Date'] = pd.to_datetime(filtered_save['Date'])
                new_sha = save_to_github(gh_token, gh_repo, "data.csv", filtered_save, st.session_state.file_sha)
                if new_sha: st.rerun()

    # LOG SESSION
    st.divider()
    with st.expander("➕ Log New Session", expanded=True):
        with st.form("new_entry", clear_on_submit=True):
            col_d, col_s, col_t = st.columns(3)
            d = col_d.date_input("Date", now)
            s = col_s.selectbox("Skill", all_skills)
            t = col_t.number_input("Minutes", 1, 600, 30)
            n = st.text_input("Notes")
            if st.form_submit_button("Log Entry", use_container_width=True):
                new_row = pd.DataFrame({"Date":[pd.to_datetime(d)], "Skill":[s], "Time Spent":[t], "Notes":[n]})
                st.session_state.df = pd.concat([st.session_state.df, new_row], ignore_index=True)
                save_to_github(gh_token, gh_repo, "data.csv", st.session_state.df, st.session_state.file_sha)
                st.rerun()
else:
    st.info("👈 Connect your GitHub Token in the sidebar to begin.")
