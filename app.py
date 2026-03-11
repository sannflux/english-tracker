import streamlit as st
import pandas as pd
from github import Github
from datetime import datetime, timedelta
import io
import plotly.express as px
import numpy as np

# --- CONFIGURATION & SESSION STATE ---
st.set_page_config(page_title="English Pro Tracker", layout="wide", page_icon="🇬🇧")

if 'df' not in st.session_state:
    st.session_state.df = None
if 'file_sha' not in st.session_state:
    st.session_state.file_sha = None
if 'prev_level' not in st.session_state:
    st.session_state.prev_level = 0

# --- SECRETS FALLBACK ---
try:
    DEFAULT_TOKEN = st.secrets.get("GH_TOKEN", "")
    DEFAULT_REPO = st.secrets.get("GH_REPO", "sannflux/english-tracker")
except Exception:
    DEFAULT_TOKEN = ""
    DEFAULT_REPO = "sannflux/english-tracker"

# --- GITHUB HELPER FUNCTIONS ---
@st.cache_data(ttl=300, show_spinner=False)
def load_data_from_github(_token, repo_name, file_path):
    try:
        g = Github(_token)
        repo = g.get_repo(repo_name)
        contents = repo.get_contents(file_path)
        decoded_string = contents.decoded_content.decode('utf-8')
        df = pd.read_csv(io.StringIO(decoded_string))
        
        # 1. Clean Column Names
        df.columns = df.columns.str.strip()
        
        # Globally replace empty strings or spaces with real NaNs for ffill to work
        df.replace(r'^\s*$', np.nan, regex=True, inplace=True)
        
        # 2. FIX BLANK DATES
        if 'Date' in df.columns:
            df['Date'] = df['Date'].ffill() 
            
            def clean_dt(val):
                if pd.isna(val): return val
                val = str(val)
                return val.split(',')[-1].strip() if ',' in val else val
            
            df['Date'] = df['Date'].apply(clean_dt)
            df['Date'] = pd.to_datetime(df['Date'], format='mixed', errors='coerce')
            df['Date'] = df['Date'].ffill().bfill()

        # 3. Clean Skills (ffill to cover the blank rows)
        if 'Skill' in df.columns:
            df['Skill'] = df['Skill'].astype(str).str.strip()
            df['Skill'] = df['Skill'].replace({'nan': np.nan, 'None': np.nan})
            df['Skill'] = df['Skill'].ffill().fillna("Unspecified")

        # 4. Clean Time Spent
        if 'Time Spent' in df.columns:
            df['Time Spent'] = pd.to_numeric(df['Time Spent'], errors='coerce').fillna(0)
            
        if 'Notes' not in df.columns:
            df['Notes'] = ""
            
        return df, contents.sha, "success"
    except Exception as e:
        return None, None, str(e)

def save_to_github(token, repo_name, file_path, df, current_sha):
    try:
        g = Github(token)
        repo = g.get_repo(repo_name)
        df_save = df.copy()
        
        # Format date back to a clean string for CSV
        df_save['Date'] = pd.to_datetime(df_save['Date']).dt.strftime("%A, %d %B %Y")
        
        csv_buffer = io.StringIO()
        df_save.to_csv(csv_buffer, index=False)
        res = repo.update_file(path=file_path, message="Sync from Streamlit App", content=csv_buffer.getvalue(), sha=current_sha)
        return res['content'].sha 
    except Exception as e:
        st.error(f"Save Error: {e}")
        return None

# --- STREAK LOGIC ---
def get_streak(df):
    if df is None or df.empty: return 0
    dates = df['Date'].dt.date.dropna().unique()
    dates = sorted(dates, reverse=True)
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

# --- SIDEBAR ---
with st.sidebar:
    st.header("🔑 Connection")
    gh_token = st.text_input("GitHub Token", type="password", value=DEFAULT_TOKEN)
    gh_repo = st.text_input("Repo", value=DEFAULT_REPO)
    
    if st.button("🔄 Force Sync", use_container_width=True):
        load_data_from_github.clear()
        df, sha, status = load_data_from_github(gh_token, gh_repo, "data.csv")
        if status == "success":
            st.session_state.df, st.session_state.file_sha = df, sha
            st.success("Data Loaded!")
        else: st.error(status)
                
    st.divider()
    weekly_goal = st.slider("Weekly Goal (Hours)", 1, 20, 5)

# --- MAIN UI ---
st.title("🇬🇧 English Learning Pro")

if st.session_state.df is not None:
    df = st.session_state.df.copy()
    
    # CALCULATIONS
    total_hrs = df['Time Spent'].sum() / 60
    streak = get_streak(df)
    level = int(total_hrs // 50) + 1
    xp_progress = (total_hrs % 50) / 50
    
    # Fix: Use YYYY-Wxx format for guaranteed chronological sorting
    df['Week_Label'] = df['Date'].dt.strftime('%Y-W%W')
    current_week_label = datetime.now().strftime('%Y-W%W')
    this_week_hrs = df[df['Week_Label'] == current_week_label]['Time Spent'].sum() / 60

    if level > st.session_state.prev_level and st.session_state.prev_level != 0:
        st.balloons()
    st.session_state.prev_level = level

    # METRICS
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Level", f"Lvl {level}")
    m2.metric("Total Time", f"{total_hrs:.1f}h")
    m3.metric("Streak", f"{streak} Days 🔥")
    m4.metric("This Week", f"{this_week_hrs:.1f}h")
    st.progress(xp_progress)

    st.divider()

    col_in, col_viz = st.columns([1, 2])
    with col_in:
        st.subheader("➕ Add Session")
        with st.form("new_entry", clear_on_submit=True):
            d = st.date_input("Date", datetime.now())
            # Expanded options to cover your custom inputs, or user can type anything in the data editor later
            s = st.selectbox("Skill", ["Listening", "Speaking", "Reading", "Writing", "Grammar", "Vocabulary", "Listening dan writing"])
            t = st.number_input("Minutes", 1, 300, 30)
            n = st.text_input("Notes")
            if st.form_submit_button("Push to GitHub"):
                new_row = pd.DataFrame({"Date":[pd.to_datetime(d)], "Skill":[s], "Time Spent":[t], "Notes":[n]})
                st.session_state.df = pd.concat([st.session_state.df, new_row], ignore_index=True)
                new_sha = save_to_github(gh_token, gh_repo, "data.csv", st.session_state.df, st.session_state.file_sha)
                if new_sha:
                    st.session_state.file_sha = new_sha
                    st.success("Synced!")
                    st.rerun()

    with col_viz:
        st.subheader("📊 Analysis")
        t1, t2 = st.tabs(["Weekly Progress", "Skill Distribution"])
        with t1:
            weekly_df = df.groupby('Week_Label')['Time Spent'].sum().reset_index()
            weekly_df['Hours'] = weekly_df['Time Spent'] / 60
            weekly_df = weekly_df.sort_values('Week_Label') # Explicit sort
            fig = px.bar(weekly_df, x='Week_Label', y='Hours', color_discrete_sequence=['#00CC96'])
            fig.update_xaxes(type='category', categoryorder='category ascending')
            st.plotly_chart(fig, use_container_width=True)
        with t2:
            skill_df = df.groupby('Skill')['Time Spent'].sum().reset_index()
            fig2 = px.pie(skill_df, values='Time Spent', names='Skill', hole=0.4)
            st.plotly_chart(fig2, use_container_width=True)

    st.subheader("📝 History")
    display_df = st.session_state.df.copy()
    display_df['Date'] = display_df['Date'].dt.date
    display_df = display_df.sort_values("Date", ascending=False).reset_index(drop=True)
    
    # Fix: Changed Skill to TextColumn so custom entries like "Listening dan writing" don't turn blank
    edited = st.data_editor(
        display_df[['Date', 'Skill', 'Time Spent', 'Notes']],
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "Date": st.column_config.DateColumn(required=True),
            "Skill": st.column_config.TextColumn("Skill", required=True),
            "Time Spent": st.column_config.NumberColumn("Minutes", min_value=1)
        }
    )
    
    if not edited.equals(display_df[['Date', 'Skill', 'Time Spent', 'Notes']]):
        if st.button("💾 Save Edits"):
            # Convert dates back to datetime before saving
            edited['Date'] = pd.to_datetime(edited['Date'])
            new_sha = save_to_github(gh_token, gh_repo, "data.csv", edited, st.session_state.file_sha)
            if new_sha:
                st.session_state.file_sha = new_sha
                st.session_state.df = edited
                st.success("Saved!")
                st.rerun()
else:
    st.info("👈 Enter Token and click Force Sync to start.")
