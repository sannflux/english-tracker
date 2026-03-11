import streamlit as st
import pandas as pd
from github import Github, GithubException
from datetime import datetime, timedelta
import io
import plotly.express as px

# --- CONFIGURATION & SESSION STATE ---
st.set_page_config(page_title="English Pro Tracker", layout="wide", page_icon="🇬🇧")

if 'df' not in st.session_state:
    st.session_state.df = None
if 'file_sha' not in st.session_state:
    st.session_state.file_sha = None

# --- GITHUB HELPER FUNCTIONS ---
def load_data_from_github(token, repo_name, file_path):
    try:
        g = Github(token)
        repo = g.get_repo(repo_name)
        contents = repo.get_contents(file_path)
        decoded_string = contents.decoded_content.decode('utf-8')
        df = pd.read_csv(io.StringIO(decoded_string))
        
        # DATA CLEANING
        df.columns = df.columns.str.strip()
        if 'Date' in df.columns:
            df['Date'] = df['Date'].astype(str).str.strip()
        df['Date'] = df['Date'].replace('', pd.NA).replace('nan', pd.NA).replace('NaT', pd.NA)
        df['Date'] = df['Date'].ffill()
        
        try:
            df['Date'] = pd.to_datetime(df['Date'], format="%A, %d %B %Y")
        except ValueError:
            df['Date'] = pd.to_datetime(df['Date'], format='mixed', dayfirst=True, errors='coerce')
        
        if 'Time Spent' in df.columns:
            df = df.dropna(subset=['Time Spent'])
            df['Time Spent'] = pd.to_numeric(df['Time Spent'], errors='coerce').fillna(0)
        
        return df, contents.sha, "success"
    except Exception as e:
        return None, None, str(e)

def save_to_github(token, repo_name, file_path, df, sha):
    try:
        g = Github(token)
        repo = g.get_repo(repo_name)
        df_to_save = df.copy()
        df_to_save['Date'] = df_to_save['Date'].dt.strftime("%A, %d %B %Y")
        csv_buffer = io.StringIO()
        df_to_save.to_csv(csv_buffer, index=False)
        repo.update_file(path=file_path, message="Sync study log", content=csv_buffer.getvalue(), sha=sha)
        return True
    except Exception as e:
        st.error(f"Error saving: {e}")
        return False

# --- CALCULATION LOGIC ---
def get_streak(df):
    if df.empty: return 0
    dates = pd.to_datetime(df['Date']).dt.date.unique()
    dates = sorted(dates, reverse=True)
    today = datetime.now().date()
    streak = 0
    curr = today
    if dates[0] < today - timedelta(days=1): return 0
    for d in dates:
        if d == curr or d == curr - timedelta(days=1):
            streak += 1
            curr = d
        else: break
    return streak

# --- UI: SIDEBAR ---
with st.sidebar:
    st.header("🔑 Connection")
    gh_token = st.text_input("GitHub Token", type="password")
    gh_repo = st.text_input("Repo", value="sannflux/english-tracker")
    
    if st.button("🔄 Sync with GitHub"):
        df, sha, status = load_data_from_github(gh_token, gh_repo, "data.csv")
        if status == "success":
            st.session_state.df, st.session_state.file_sha = df, sha
            st.success("Data Synced!")
        else: st.error(status)

# --- UI: MAIN APP ---
st.title("🇬🇧 English Learning Pro")

if st.session_state.df is not None:
    df = st.session_state.df
    
    # 1. GAMIFIED METRICS
    total_hrs = df['Time Spent'].sum() / 60
    streak = get_streak(df)
    level = int(total_hrs // 50) + 1
    xp_progress = (total_hrs % 50) / 50

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Current Level", f"Lvl {level}")
    m2.metric("Total Hours", f"{total_hrs:.1f}h")
    m3.metric("Daily Streak", f"{streak} Days 🔥")
    m4.metric("Total Sessions", len(df))
    
    st.write(f"**Progress to Level {level + 1}**")
    st.progress(xp_progress)

    # 2. INPUT & ACTIONS
    col_in, col_viz = st.columns([1, 2])
    
    with col_in:
        st.subheader("➕ Log Session")
        with st.form("entry_form", clear_on_submit=True):
            n_date = st.date_input("Date", datetime.now())
            n_skill = st.selectbox("Skill", ["Listening", "Speaking", "Reading", "Writing", "Grammar", "Vocabulary"])
            n_time = st.number_input("Minutes", min_value=1, value=30)
            if st.form_submit_button("Add & Push"):
                new_row = pd.DataFrame({"Date": [pd.to_datetime(n_date)], "Skill": [n_skill], "Time Spent": [n_time]})
                st.session_state.df = pd.concat([st.session_state.df, new_row], ignore_index=True)
                save_to_github(gh_token, gh_repo, "data.csv", st.session_state.df, st.session_state.file_sha)
                _, st.session_state.file_sha, _ = load_data_from_github(gh_token, gh_repo, "data.csv")
                st.rerun()
        
        if st.button("🗑️ Delete Last Entry"):
            st.session_state.df = st.session_state.df[:-1]
            save_to_github(gh_token, gh_repo, "data.csv", st.session_state.df, st.session_state.file_sha)
            _, st.session_state.file_sha, _ = load_data_from_github(gh_token, gh_repo, "data.csv")
            st.rerun()

    with col_viz:
        st.subheader("📊 Activity Analysis")
        tab_week, tab_skill = st.tabs(["Weekly Progress", "Skill Breakdown"])
        
        with tab_week:
            if not df.empty:
                df['Week'] = df['Date'].dt.isocalendar().week
                weekly = df.groupby('Week')['Time Spent'].sum().reset_index()
                weekly['Hours'] = weekly['Time Spent'] / 60
                fig = px.bar(weekly, x='Week', y='Hours', title="Hours per Week", color_discrete_sequence=['#00CC96'])
                st.plotly_chart(fig, use_container_width=True)

        with tab_skill:
            if not df.empty:
                skill_dist = df.groupby('Skill')['Time Spent'].sum().reset_index()
                fig2 = px.pie(skill_dist, values='Time Spent', names='Skill', hole=0.4)
                st.plotly_chart(fig2, use_container_width=True)

    # 3. DATA TABLE
    st.subheader("📝 History")
    display_df = df.copy()
    display_df['Date'] = display_df['Date'].dt.strftime("%A, %d %b %Y")
    st.dataframe(display_df.sort_values(by="Date", ascending=False), use_container_width=True)

else:
    st.info("👈 Enter your token and click Sync in the sidebar to start.")
