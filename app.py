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
    """Fetches data from GitHub and cleans it."""
    try:
        g = Github(_token)
        repo = g.get_repo(repo_name)
        contents = repo.get_contents(file_path)
        decoded_string = contents.decoded_content.decode('utf-8')
        df = pd.read_csv(io.StringIO(decoded_string))
        
        # DATA CLEANING & SCHEMA ENFORCEMENT
        df.columns = df.columns.str.strip()
        
        # Ensure 'Notes' column exists
        if 'Notes' not in df.columns:
            df['Notes'] = ""
        df['Notes'] = df['Notes'].fillna("")
        
        # 1. FIX: Aggressive Date Cleaning & Forward Fill
        if 'Date' in df.columns:
            # Convert to string and explicitly replace all variants of empty/null with pd.NA
            df['Date'] = df['Date'].astype(str).str.strip()
            df['Date'] = df['Date'].replace(r'^(nan|NaN|NaT|None|)$', pd.NA, regex=True)
            df['Date'] = df['Date'].ffill() # Forward fill down the blanks
            
            # Parse dates: Try original long format first, then coerce standard formats
            try:
                df['Date'] = pd.to_datetime(df['Date'], format="%A, %d %B %Y")
            except ValueError:
                df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        
        # 2. FIX: Skill Cleaning & Fallback
        if 'Skill' in df.columns:
            df['Skill'] = df['Skill'].astype(str).str.strip()
            df['Skill'] = df['Skill'].replace(r'^(nan|NaN|NaT|None|)$', pd.NA, regex=True)
            df['Skill'] = df['Skill'].ffill().fillna("Reading") 
            
            # Ensure only valid options remain for the data editor
            valid_skills = ["Listening", "Speaking", "Reading", "Writing", "Grammar", "Vocabulary"]
            df.loc[~df['Skill'].isin(valid_skills), 'Skill'] = "Reading"
        
        # 3. Numeric parsing without dropping rows
        if 'Time Spent' in df.columns:
            df['Time Spent'] = pd.to_numeric(df['Time Spent'], errors='coerce').fillna(0)
        
        return df, contents.sha, "success"
    except Exception as e:
        return None, None, str(e)

def save_to_github(token, repo_name, file_path, df, current_sha):
    """Optimized: Saves to GitHub and returns the new SHA directly."""
    try:
        g = Github(token)
        repo = g.get_repo(repo_name)
        df_to_save = df.copy()
        
        # Standardize date format for safety when saving
        df_to_save['Date'] = pd.to_datetime(df_to_save['Date']).dt.strftime("%Y-%m-%d")
        
        csv_buffer = io.StringIO()
        df_to_save.to_csv(csv_buffer, index=False)
        
        # Update file and extract the new SHA directly from the response
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
    dates = pd.to_datetime(df['Date']).dt.date.dropna().unique()
    dates = sorted(dates, reverse=True)
    today = datetime.now().date()
    streak = 0
    curr = today
    if not dates or dates[0] < today - timedelta(days=1): return 0
    for d in dates:
        if d == curr or d == curr - timedelta(days=1):
            streak += 1
            curr = d
        else: break
    return streak

# --- DIALOGS (FLOATING UI) ---
@st.dialog("➕ Log New Session")
def log_session_dialog():
    with st.form("entry_form"):
        n_date = st.date_input("Date", datetime.now())
        n_skill = st.selectbox("Skill", ["Listening", "Speaking", "Reading", "Writing", "Grammar", "Vocabulary"])
        n_time = st.number_input("Minutes", min_value=1, value=30)
        n_notes = st.text_input("Notes / Resources", placeholder="e.g., BBC News podcast")
        
        if st.form_submit_button("Save Session"):
            new_row = pd.DataFrame({
                "Date": [pd.to_datetime(n_date)], 
                "Skill": [n_skill], 
                "Time Spent": [n_time],
                "Notes": [n_notes]
            })
            # Update state
            st.session_state.df = pd.concat([st.session_state.df, new_row], ignore_index=True)
            
            with st.spinner("Pushing to GitHub..."):
                new_sha = save_to_github(gh_token, gh_repo, "data.csv", st.session_state.df, st.session_state.file_sha)
                if new_sha:
                    st.session_state.file_sha = new_sha
                    st.toast("✅ Session logged and synced!")
                    st.rerun()

# --- UI: SIDEBAR ---
with st.sidebar:
    st.header("🔑 Connection")
    gh_token = st.text_input("GitHub Token", type="password", value=DEFAULT_TOKEN)
    gh_repo = st.text_input("Repo", value=DEFAULT_REPO)
    
    if st.button("🔄 Force Sync", use_container_width=True):
        if not gh_token:
            st.warning("Please provide a token.")
        else:
            load_data_from_github.clear() # Clear cache
            df, sha, status = load_data_from_github(gh_token, gh_repo, "data.csv")
            if status == "success":
                st.session_state.df, st.session_state.file_sha = df, sha
                st.success("Data Synced!")
            else: 
                st.error(status)
                
    st.divider()
    st.header("🎯 Target Tracker")
    weekly_goal_hrs = st.slider("Weekly Goal (Hours)", min_value=1, max_value=20, value=5)

# --- UI: MAIN APP ---
st.title("🇬🇧 English Learning Pro")

if st.session_state.df is not None:
    df = st.session_state.df
    
    # --- 1. GAMIFIED METRICS & CALCULATIONS ---
    total_hrs = df['Time Spent'].sum() / 60
    streak = get_streak(df)
    level = int(total_hrs // 50) + 1
    xp_progress = (total_hrs % 50) / 50

    # Level Up Celebration Logic
    if st.session_state.prev_level > 0 and level > st.session_state.prev_level:
        st.balloons()
        st.toast(f"🎉 Congratulations! You reached Level {level}!", icon="🏆")
    st.session_state.prev_level = level

    # Advanced Metrics Calculations
    rolling_7d = 0
    best_day_str = "N/A"
    current_week_hrs = 0
    
    if not df.empty and df['Date'].notna().any():
        valid_df = df.dropna(subset=['Date']).copy()
        
        # 7-Day Rolling Average
        daily_totals = valid_df.groupby('Date')['Time Spent'].sum().reset_index().set_index('Date').resample('D').sum().fillna(0)
        if len(daily_totals) >= 7:
            rolling_7d = daily_totals['Time Spent'].rolling(7).mean().iloc[-1]
        elif len(daily_totals) > 0:
            rolling_7d = daily_totals['Time Spent'].mean()
            
        # Best Day Insight
        day_avg = valid_df.groupby(valid_df['Date'].dt.day_name())['Time Spent'].mean()
        if not day_avg.empty:
            best_day = day_avg.idxmax()
            best_day_str = f"{best_day[:3]} ({day_avg.max():.0f}m avg)"
            
        # Current Week Target
        current_week = datetime.now().isocalendar().week
        valid_df['Week'] = valid_df['Date'].dt.isocalendar().week
        current_week_hrs = valid_df[valid_df['Week'] == current_week]['Time Spent'].sum() / 60

    # Render Metric Cards
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Current Level", f"Lvl {level}")
    m2.metric("Total Hours", f"{total_hrs:.1f}h")
    m3.metric("Daily Streak", f"{streak} Days 🔥")
    m4.metric("7-Day Avg", f"{rolling_7d:.0f}m / day")
    m5.metric("Best Day", best_day_str)
    m6.metric("Sessions", len(df))
    
    # Progress Bars
    p1, p2 = st.columns(2)
    with p1:
        st.write(f"**XP Progress to Level {level + 1}**")
        st.progress(xp_progress)
    with p2:
        st.write(f"**Weekly Goal:** {current_week_hrs:.1f}h / {weekly_goal_hrs}h")
        goal_pct = min(current_week_hrs / weekly_goal_hrs, 1.0)
        st.progress(goal_pct)

    st.divider()

    # --- 2. LAYOUT & ACTIONS ---
    col_act, col_viz = st.columns([1, 3])
    
    with col_act:
        if st.button("➕ Log Session", use_container_width=True, type="primary"):
            log_session_dialog()
            
        st.info("💡 **Tip:** Edit or delete rows directly in the Data History table below, then click 'Save Changes'.")

    with col_viz:
        st.subheader("📊 Analytics Dashboard")
        tab_heat, tab_week, tab_skill = st.tabs(["Activity Heatmap", "Weekly Progress", "Skill Breakdown"])
        
        with tab_heat:
            if not df.empty and df['Date'].notna().any():
                # Prepare Heatmap Data
                hm_data = df.dropna(subset=['Date']).copy()
                hm_data['Weekday'] = hm_data['Date'].dt.day_name()
                
                # FIX: Force Week to be a strict categorical String (e.g. "W52") to prevent plotly float axes
                hm_data['Week'] = "W" + hm_data['Date'].dt.isocalendar().week.astype(str)
                
                weekdays_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                pivot_df = hm_data.pivot_table(index='Weekday', columns='Week', values='Time Spent', aggfunc='sum').reindex(weekdays_order).fillna(0)
                
                fig_heat = px.imshow(pivot_df, color_continuous_scale='Greens', title="Time Spent per Week/Day", aspect="auto")
                fig_heat.update_layout(margin=dict(l=0, r=0, t=30, b=0))
                # Explicitly tell Plotly the X-axis is categorical
                fig_heat.update_xaxes(type='category') 
                st.plotly_chart(fig_heat, use_container_width=True)
            else:
                st.write("Not enough data for heatmap.")

        with tab_week:
            if not df.empty and df['Date'].notna().any():
                week_data = df.dropna(subset=['Date']).copy()
                # FIX: Force Week to be a strict string here too
                week_data['Week_Str'] = "W" + week_data['Date'].dt.isocalendar().week.astype(str)
                weekly = week_data.groupby('Week_Str')['Time Spent'].sum().reset_index()
                weekly['Hours'] = weekly['Time Spent'] / 60
                
                fig_week = px.bar(weekly, x='Week_Str', y='Hours', title="Hours per Week", color_discrete_sequence=['#00CC96'])
                fig_week.update_xaxes(type='category', categoryorder='category ascending')
                st.plotly_chart(fig_week, use_container_width=True)

        with tab_skill:
            if not df.empty:
                skill_dist = df.groupby('Skill')['Time Spent'].sum().reset_index()
                fig_skill = px.pie(skill_dist, values='Time Spent', names='Skill', hole=0.4)
                st.plotly_chart(fig_skill, use_container_width=True)

    # --- 3. INTERACTIVE DATA TABLE (ST.DATA_EDITOR) ---
    st.subheader("📝 Editable Data History")
    
    display_df = df.copy()
    # Safely convert to date for UI rendering
    display_df['Date'] = pd.to_datetime(display_df['Date']).dt.date 
    display_df = display_df.sort_values(by="Date", ascending=False, na_position='last').reset_index(drop=True)
    
    max_time = df['Time Spent'].max() if not df.empty else 120
    
    edited_df = st.data_editor(
        display_df,
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "Date": st.column_config.DateColumn("Date", required=True),
            "Skill": st.column_config.SelectboxColumn("Skill", options=["Listening", "Speaking", "Reading", "Writing", "Grammar", "Vocabulary"], required=True),
            "Time Spent": st.column_config.ProgressColumn("Time Spent (m)", format="%f", min_value=0, max_value=max(float(max_time), 120.0)),
            "Notes": st.column_config.TextColumn("Notes", max_chars=200),
            "Week": None # Hide calculated columns if they exist
        }
    )
    
    # Check if data was modified
    if not edited_df.equals(display_df):
        if st.button("💾 Save History Changes", type="primary"):
            with st.spinner("Syncing changes..."):
                new_sha = save_to_github(gh_token, gh_repo, "data.csv", edited_df, st.session_state.file_sha)
                if new_sha:
                    st.session_state.file_sha = new_sha
                    st.session_state.df = edited_df
                    st.success("History updated successfully!")
                    st.rerun()

else:
    st.info("👈 Enter your token and click 'Force Sync' in the sidebar to load your data.")
