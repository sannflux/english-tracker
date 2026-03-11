import streamlit as st
import pandas as pd
from github import Github
from datetime import datetime, timedelta
import io
import plotly.express as px
import numpy as np

# --- CONFIGURATION & SESSION STATE ---
st.set_page_config(page_title="English Pro Tracker", layout="wide", page_icon="🇬🇧")

# Initialize session states safely
for key in ['df', 'file_sha', 'prev_level']:
    if key not in st.session_state:
        st.session_state[key] = None if key != 'prev_level' else 0

# --- SECRETS FALLBACK ---
try:
    DEFAULT_TOKEN = st.secrets.get("GH_TOKEN", "")
    DEFAULT_REPO = st.secrets.get("GH_REPO", "sannflux/english-tracker")
except FileNotFoundError:
    DEFAULT_TOKEN = ""
    DEFAULT_REPO = "sannflux/english-tracker"

# --- GITHUB HELPER FUNCTIONS ---
@st.cache_data(ttl=300, show_spinner=False)
def load_data_from_github(_token, repo_name, file_path):
    """Fetches data from GitHub and cleans it with aggressive human-readable support."""
    try:
        g = Github(_token)
        repo = g.get_repo(repo_name)
        contents = repo.get_contents(file_path)
        decoded_string = contents.decoded_content.decode('utf-8')
        df = pd.read_csv(io.StringIO(decoded_string))
        
        # 1. Clean Columns
        df.columns = df.columns.str.strip()
        
        # 2. Aggressive Date Parsing & Fill
        if 'Date' in df.columns:
            # Handle empty spaces/nulls
            df['Date'] = df['Date'].replace(r'^\s*$', np.nan, regex=True)
            df['Date'] = df['Date'].ffill() # Fill dates down from the first entry of the day
            
            # Remove "Wednesday, " etc. if present to help pandas parse
            def clean_date_str(val):
                if pd.isna(val): return val
                val = str(val)
                if ',' in val:
                    return val.split(',')[-1].strip()
                return val
            
            df['Date'] = df['Date'].apply(clean_date_str)
            df['Date'] = pd.to_datetime(df['Date'], errors='coerce', dayfirst=True)
            df['Date'] = df['Date'].ffill().bfill() # Final safety fill
            
        # 3. Skill Cleaning (Forward fill if user left it blank)
        if 'Skill' in df.columns:
            df['Skill'] = df['Skill'].replace(r'^\s*$', np.nan, regex=True)
            df['Skill'] = df['Skill'].ffill().fillna("Reading")
            
            valid_skills = ["Listening", "Speaking", "Reading", "Writing", "Grammar", "Vocabulary"]
            df['Skill'] = df['Skill'].apply(lambda x: x if x in valid_skills else "Reading")

        # 4. Numeric Cleaning
        if 'Time Spent' in df.columns:
            df['Time Spent'] = pd.to_numeric(df['Time Spent'], errors='coerce').fillna(0)
            
        # 5. Notes ensure
        if 'Notes' not in df.columns:
            df['Notes'] = ""
        df['Notes'] = df['Notes'].fillna("")
        
        return df, contents.sha, "success"
    except Exception as e:
        return None, None, str(e)

def save_to_github(token, repo_name, file_path, df, current_sha):
    """Saves data back to GitHub."""
    try:
        g = Github(token)
        repo = g.get_repo(repo_name)
        df_to_save = df.copy()
        
        # Standardize for storage
        df_to_save['Date'] = pd.to_datetime(df_to_save['Date']).dt.strftime("%Y-%m-%d")
        
        csv_buffer = io.StringIO()
        df_to_save.to_csv(csv_buffer, index=False)
        
        res = repo.update_file(
            path=file_path, 
            message="Sync study log", 
            content=csv_buffer.getvalue(), 
            sha=current_sha
        )
        return res['content'].sha 
    except Exception as e:
        st.error(f"Error saving: {e}")
        return None

# --- CALCULATION LOGIC ---
def get_streak(df):
    if df.empty: return 0
    # Use actual datetime objects
    dates = df['Date'].dt.date.dropna().unique()
    dates = sorted(dates, reverse=True)
    if not dates: return 0
    
    today = datetime.now().date()
    streak = 0
    curr = today
    
    # If last entry is older than yesterday, streak is broken
    if dates[0] < today - timedelta(days=1): return 0
    
    for d in dates:
        if d == curr or d == curr - timedelta(days=1):
            streak += 1
            curr = d
        else: break
    return streak

# --- DIALOGS ---
@st.dialog("➕ Log New Session")
def log_session_dialog():
    with st.form("entry_form"):
        n_date = st.date_input("Date", datetime.now())
        n_skill = st.selectbox("Skill", ["Listening", "Speaking", "Reading", "Writing", "Grammar", "Vocabulary"])
        n_time = st.number_input("Minutes", min_value=1, value=30)
        n_notes = st.text_input("Notes / Resources")
        
        if st.form_submit_button("Save Session"):
            new_row = pd.DataFrame({
                "Date": [pd.to_datetime(n_date)], 
                "Skill": [n_skill], 
                "Time Spent": [n_time],
                "Notes": [n_notes]
            })
            st.session_state.df = pd.concat([st.session_state.df, new_row], ignore_index=True)
            
            with st.spinner("Pushing to GitHub..."):
                new_sha = save_to_github(gh_token, gh_repo, "data.csv", st.session_state.df, st.session_state.file_sha)
                if new_sha:
                    st.session_state.file_sha = new_sha
                    st.toast("✅ Synced!")
                    st.rerun()

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
            st.success("Synced!")
        else: st.error(status)
                
    st.divider()
    weekly_goal_hrs = st.slider("Weekly Goal (Hours)", 1, 20, 5)

# --- MAIN APP ---
st.title("🇬🇧 English Learning Pro")

if st.session_state.df is not None:
    df = st.session_state.df
    
    # METRICS
    total_hrs = df['Time Spent'].sum() / 60
    streak = get_streak(df)
    level = int(total_hrs // 50) + 1
    xp_progress = (total_hrs % 50) / 50

    if st.session_state.prev_level > 0 and level > st.session_state.prev_level:
        st.balloons()
    st.session_state.prev_level = level

    # Calculations
    current_week = datetime.now().isocalendar().week
    df['Week_Num'] = df['Date'].dt.isocalendar().week
    current_week_hrs = df[df['Week_Num'] == current_week]['Time Spent'].sum() / 60

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Level", f"Lvl {level}")
    m2.metric("Total Hours", f"{total_hrs:.1f}h")
    m3.metric("Streak", f"{streak} Days 🔥")
    m4.metric("This Week", f"{current_week_hrs:.1f}h")
    
    st.write(f"**Progress to Level {level+1}**")
    st.progress(xp_progress)
    st.divider()

    # DASHBOARD
    col_act, col_viz = st.columns([1, 3])
    with col_act:
        if st.button("➕ Log Session", use_container_width=True, type="primary"):
            log_session_dialog()
        st.info("💡 Edit history directly in the table below and hit 'Save'.")

    with col_viz:
        tab_heat, tab_week, tab_skill = st.tabs(["Heatmap", "Weekly", "Skills"])
        
        with tab_heat:
            if not df.empty:
                hm_data = df.copy()
                hm_data['Weekday'] = hm_data['Date'].dt.day_name()
                hm_data['Week'] = "W" + hm_data['Date'].dt.isocalendar().week.astype(str).str.zfill(2)
                order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                pivot = hm_data.pivot_table(index='Weekday', columns='Week', values='Time Spent', aggfunc='sum').reindex(order).fillna(0)
                fig = px.imshow(pivot, color_continuous_scale='Greens', aspect="auto")
                st.plotly_chart(fig, use_container_width=True)

        with tab_week:
            weekly = df.groupby('Week_Num')['Time Spent'].sum().reset_index()
            weekly['Hours'] = weekly['Time Spent'] / 60
            fig2 = px.bar(weekly, x='Week_Num', y='Hours', color_discrete_sequence=['#00CC96'])
            st.plotly_chart(fig2, use_container_width=True)

        with tab_skill:
            skills = df.groupby('Skill')['Time Spent'].sum().reset_index()
            fig3 = px.pie(skills, values='Time Spent', names='Skill', hole=0.4)
            st.plotly_chart(fig3, use_container_width=True)

    # DATA EDITOR
    st.subheader("📝 History")
    display_df = df.copy()
    display_df['Date'] = display_df['Date'].dt.date
    display_df = display_df.sort_values("Date", ascending=False).reset_index(drop=True)
    
    edited_df = st.data_editor(
        display_df[['Date', 'Skill', 'Time Spent', 'Notes']],
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "Date": st.column_config.DateColumn(required=True),
            "Skill": st.column_config.SelectboxColumn(options=["Listening", "Speaking", "Reading", "Writing", "Grammar", "Vocabulary"], required=True),
            "Time Spent": st.column_config.NumberColumn("Min", min_value=1),
            "Notes": st.column_config.TextColumn(width="large")
        }
    )
    
    if not edited_df.equals(display_df[['Date', 'Skill', 'Time Spent', 'Notes']]):
        if st.button("💾 Save Changes"):
            new_sha = save_to_github(gh_token, gh_repo, "data.csv", edited_df, st.session_state.file_sha)
            if new_sha:
                st.session_state.file_sha = new_sha
                st.session_state.df = edited_df
                st.rerun()
else:
    st.info("👈 Enter token and Sync to start.")
