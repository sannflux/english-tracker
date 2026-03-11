import streamlit as st
import pandas as pd
from github import Github
from datetime import datetime, timedelta
import plotly.express as px

# --- CONFIGURATION & SESSION STATE ---
st.set_page_config(page_title="English Learning Tracker", layout="wide")

if 'df' not in st.session_state:
    st.session_state.df = None

# --- GITHUB INTEGRATION FUNCTIONS ---
def load_data_from_github(token, repo_name, file_path):
    try:
        g = Github(token)
        repo = g.get_user().get_repo(repo_name)
        file_content = repo.get_contents(file_path)
        decoded_content = file_content.decoded_content.decode()
        df = pd.read_csv(pd.compat.StringIO(decoded_content))
        # Ensure date column is datetime objects
        df['Date'] = pd.to_datetime(df['Date'], format='%A, %d %B %Y')
        return df, file_content.sha
    except Exception as e:
        return None, None

def save_data_to_github(token, repo_name, file_path, df, sha):
    try:
        g = Github(token)
        repo = g.get_user().get_repo(repo_name)
        # Convert datetime back to the specific string format for saving
        df_to_save = df.copy()
        df_to_save['Date'] = df_to_save['Date'].dt.strftime('%A, %d %B %Y')
        csv_content = df_to_save.to_csv(index=False)
        
        if sha:
            repo.update_file(file_path, "Update study logs", csv_content, sha)
        else:
            repo.create_file(file_path, "Initial study logs", csv_content)
        return True
    except Exception as e:
        st.error(f"Error saving to GitHub: {e}")
        return False

# --- LOGIC FUNCTIONS ---
def calculate_streak(df):
    if df.empty:
        return 0
    dates = pd.to_datetime(df['Date']).dt.date.unique()
    dates = sorted(dates, reverse=True)
    today = datetime.now().date()
    
    streak = 0
    current_date = today
    
    # Check if last entry was today or yesterday to continue streak
    if dates[0] < today - timedelta(days=1):
        return 0
        
    for date in dates:
        if date == current_date or date == current_date - timedelta(days=1):
            streak += 1
            current_date = date
        else:
            break
    return streak

# --- UI LAYOUT ---
st.title("🇬🇧 English Learning Tracker")

# Sidebar for GitHub Settings
with st.sidebar:
    st.header("Settings & Sync")
    gh_token = st.text_input("GitHub Personal Access Token", type="password")
    gh_repo = st.text_input("Repository Name (e.g., 'user/english-tracker')")
    gh_path = "data.csv"
    
    if st.button("Connect & Sync Data"):
        if gh_token and gh_repo:
            df, sha = load_data_from_github(gh_token, gh_repo, gh_path)
            if df is not None:
                st.session_state.df = df
                st.session_state.sha = sha
                st.success("Data synced from GitHub!")
            else:
                st.warning("No file found. Starting with a fresh dataset.")
                st.session_state.df = pd.DataFrame(columns=['Date', 'Skill', 'Time Spent'])
                st.session_state.sha = None
        else:
            st.error("Please provide Token and Repo name.")

# Main Form
if st.session_state.df is not None:
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Log New Session")
        with st.form("input_form", clear_on_submit=True):
            date_input = st.date_input("Date", datetime.now())
            skill_input = st.selectbox("Skill", ["Speaking", "Listening", "Reading", "Writing", "Grammar", "Vocabulary"])
            minutes_input = st.number_input("Time Spent (Minutes)", min_value=1, value=30)
            
            submit = st.form_submit_button("Add to Log")
            
            if submit:
                # Create a new row
                new_row = pd.DataFrame({
                    'Date': [pd.to_datetime(date_input)],
                    'Skill': [skill_input],
                    'Time Spent': [minutes_input]
                })
                # Add to dataframe
                st.session_state.df = pd.concat([st.session_state.df, new_row], ignore_index=True)
                st.success("Entry added locally!")

        if st.button("🚀 Push to GitHub"):
            success = save_data_to_github(gh_token, gh_repo, gh_path, st.session_state.df, st.session_state.sha)
            if success:
                st.success("Saved to GitHub!")
                # Refresh SHA
                _, st.session_state.sha = load_data_from_github(gh_token, gh_repo, gh_path)

    with col2:
        # --- CALCULATIONS ---
        df = st.session_state.df
        total_mins = df['Time Spent'].sum()
        total_hours = total_mins / 60
        streak = calculate_streak(df)
        
        # Dashboard Metrics
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Hours", f"{total_hours:.1f}h")
        m2.metric("Days Studied", len(df['Date'].unique()))
        m3.metric("Current Streak", f"{streak} Days 🔥")

        # Milestone Progress Bar
        goal_hours = 500
        progress = min(total_hours / goal_hours, 1.0)
        st.write(f"**Progress to {goal_hours} Hours Goal**")
        st.progress(progress)
        st.caption(f"{total_hours:.1f} / {goal_hours} hours completed")

    # --- DATA TABLE & WEEKLY SUMMARY ---
    st.divider()
    tab1, tab2, tab3 = st.tabs(["Recent Logs", "Weekly Summary", "Skill Distribution"])
    
    with tab1:
        st.dataframe(df.sort_values(by='Date', ascending=False), use_container_width=True)
    
    with tab2:
        if not df.empty:
            # Replicate the Excel "Minggu" Logic
            df_weekly = df.copy()
            df_weekly['Week'] = df_weekly['Date'].dt.isocalendar().week
            df_weekly['Year'] = df_weekly['Date'].dt.year
            weekly_summary = df_weekly.groupby(['Year', 'Week'])['Time Spent'].sum().reset_index()
            weekly_summary['Hours'] = weekly_summary['Time Spent'] / 60
            weekly_summary['Week Label'] = "Minggu " + weekly_summary['Week'].astype(str)
            
            st.table(weekly_summary[['Week Label', 'Hours']])
            
            fig = px.bar(weekly_summary, x='Week Label', y='Hours', title="Weekly Progress")
            st.plotly_chart(fig, use_container_width=True)

    with tab3:
        if not df.empty:
            skill_summary = df.groupby('Skill')['Time Spent'].sum().reset_index()
            fig_pie = px.pie(skill_summary, values='Time Spent', names='Skill', title="Time by Skill")
            st.plotly_chart(fig_pie, use_container_width=True)

else:
    st.info("Please connect to your GitHub repository in the sidebar to load your data or start a new log.")


