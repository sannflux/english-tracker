import streamlit as st
import pandas as pd
from github import Github, GithubException
from datetime import datetime, timedelta
import plotly.express as px
import io

# --- CONFIGURATION & SESSION STATE ---
st.set_page_config(page_title="English Learning Tracker", layout="wide")

if 'df' not in st.session_state:
    st.session_state.df = None
if 'sha' not in st.session_state:
    st.session_state.sha = None

# --- GITHUB INTEGRATION FUNCTIONS ---
def load_data_from_github(token, repo_name, file_path):
    try:
        g = Github(token)
        # Fix: Use get_repo directly for "username/repo" format
        repo = g.get_repo(repo_name) 
        
        try:
            file_content = repo.get_contents(file_path)
            decoded_content = file_content.decoded_content.decode()
            df = pd.read_csv(io.StringIO(decoded_content))
            # Ensure date column is datetime objects
            df['Date'] = pd.to_datetime(df['Date'], format='%A, %d %B %Y')
            return df, file_content.sha, "success"
        except GithubException as e:
            if e.status == 404:
                return None, None, "file_not_found"
            return None, None, f"GitHub Error: {e.data.get('message', str(e))}"
            
    except GithubException as e:
        if e.status == 401:
            return None, None, "Invalid GitHub Token."
        elif e.status == 404:
            return None, None, "Repository not found. Check the name."
        return None, None, f"Connection Error: {e.data.get('message', str(e))}"
    except Exception as e:
        return None, None, str(e)

def save_data_to_github(token, repo_name, file_path, df, sha):
    try:
        g = Github(token)
        repo = g.get_repo(repo_name)
        
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
    if not dates or dates[0] < today - timedelta(days=1):
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
    gh_repo = st.text_input("Repository Name", value="sannflux/english-tracker")
    gh_path = "data.csv"
    
    if st.button("Connect & Sync Data"):
        if gh_token and gh_repo:
            df, sha, status = load_data_from_github(gh_token, gh_repo, gh_path)
            
            if status == "success":
                st.session_state.df = df
                st.session_state.sha = sha
                st.success("Data synced from GitHub!")
            elif status == "file_not_found":
                st.warning("Connected to repo, but 'data.csv' not found. Starting fresh.")
                st.session_state.df = pd.DataFrame(columns=['Date', 'Skill', 'Time Spent'])
                st.session_state.sha = None
            else:
                st.error(f"Failed to connect: {status}")
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
                st.success("Entry added locally! Don't forget to push to GitHub.")

        if st.button("🚀 Push to GitHub", type="primary"):
            success = save_data_to_github(gh_token, gh_repo, gh_path, st.session_state.df, st.session_state.sha)
            if success:
                st.success("Successfully saved to GitHub!")
                # Refresh SHA after creating/updating the file
                _, st.session_state.sha, _ = load_data_from_github(gh_token, gh_repo, gh_path)

    with col2:
        # --- CALCULATIONS ---
        df = st.session_state.df
        total_mins = df['Time Spent'].sum() if not df.empty else 0
        total_hours = total_mins / 60
        streak = calculate_streak(df)
        
        # Dashboard Metrics
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Hours", f"{total_hours:.1f}h")
        m2.metric("Days Studied", len(df['Date'].unique()) if not df.empty else 0)
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
        if not df.empty:
            st.dataframe(df.sort_values(by='Date', ascending=False), use_container_width=True)
        else:
            st.info("No logs yet. Add your first session above!")
    
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
        else:
            st.info("Log some data to see weekly summaries.")

    with tab3:
        if not df.empty:
            skill_summary = df.groupby('Skill')['Time Spent'].sum().reset_index()
            fig_pie = px.pie(skill_summary, values='Time Spent', names='Skill', title="Time by Skill")
            st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.info("Log some data to see skill distribution.")

else:
    st.info("👈 Please connect to your GitHub repository in the sidebar. Once connected, you can add logs and save them directly to GitHub.")
