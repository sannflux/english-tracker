import streamlit as st
import pandas as pd
from github import Github, GithubException
from datetime import datetime
import io

# --- CONFIGURATION & SESSION STATE ---
st.set_page_config(page_title="English Learning Tracker", layout="wide")

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
        
        # Read the raw CSV
        decoded_string = contents.decoded_content.decode('utf-8')
        df = pd.read_csv(io.StringIO(decoded_string))
        
        # --- DATA CLEANING LOGIC ---
        # 1. Strip whitespace from headers and string columns
        df.columns = df.columns.str.strip()
        if 'Date' in df.columns:
            df['Date'] = df['Date'].astype(str).str.strip()
        
        # 2. Replace empty strings/nan with pd.NA so forward fill works
        df['Date'] = df['Date'].replace('', pd.NA).replace('nan', pd.NA).replace('NaT', pd.NA)
        
        # 3. Forward fill: If a date is missing, take the one from the row above
        df['Date'] = df['Date'].ffill()
        
        # 4. Parse dates based on your specific format, falling back to mixed if it fails
        try:
            df['Date'] = pd.to_datetime(df['Date'], format="%A, %d %B %Y")
        except ValueError:
            # Fallback if there are mixed formats or weird strings left
            df['Date'] = pd.to_datetime(df['Date'], format='mixed', dayfirst=True, errors='coerce')
        
        # 5. Drop rows where Time Spent is empty (if any)
        if 'Time Spent' in df.columns:
            df = df.dropna(subset=['Time Spent'])
        
        return df, contents.sha, "success"
        
    except GithubException as e:
        if e.status == 401:
            return None, None, "401 Bad Credentials: The GitHub token is invalid or expired."
        elif e.status == 404:
            return None, None, "404 Not Found: Check if the repository name is correct and the file 'data.csv' exists."
        return None, None, f"GitHub API Error: {e.data.get('message', str(e))}"
    except Exception as e:
        return None, None, f"Data Parsing Error: {str(e)}"

def save_to_github(token, repo_name, file_path, df, sha):
    try:
        g = Github(token)
        repo = g.get_repo(repo_name)
        
        # Prepare CSV string (Convert dates back to your preferred string format for saving)
        df_to_save = df.copy()
        df_to_save['Date'] = df_to_save['Date'].dt.strftime("%A, %d %B %Y")
        csv_buffer = io.StringIO()
        df_to_save.to_csv(csv_buffer, index=False)
        
        repo.update_file(
            path=file_path,
            message="Update English learning log via Streamlit",
            content=csv_buffer.getvalue(),
            sha=sha
        )
        return True
    except Exception as e:
        st.error(f"Error saving to GitHub: {e}")
        return False

# --- UI: SIDEBAR ---
with st.sidebar:
    st.header("⚙️ GitHub Settings")
    gh_token = st.text_input("GitHub Personal Access Token", type="password", help="Requires 'repo' scope")
    gh_repo = st.text_input("Repository Name", value="sannflux/english-tracker")
    gh_path = "data.csv"
    
    if st.button("Connect & Load Data"):
        if gh_token and gh_repo:
            with st.spinner("Connecting..."):
                df, sha, status = load_data_from_github(gh_token, gh_repo, gh_path)
                if status == "success":
                    st.session_state.df = df
                    st.session_state.file_sha = sha
                    st.success("Successfully connected and cleaned data!")
                else:
                    st.error(status)
        else:
            st.warning("Please enter both a Token and Repository Name.")

# --- UI: MAIN APP ---
st.title("📚 English Progress Tracker")

if st.session_state.df is not None:
    df = st.session_state.df
    
    # --- STATISTICS SECTION ---
    col1, col2, col3 = st.columns(3)
    
    total_minutes = df['Time Spent'].sum() if not df.empty else 0
    total_hours = total_minutes / 60
    total_days = total_hours / 24
    
    col1.metric("Total Time (Hours)", f"{total_hours:.1f}")
    col2.metric("Total Time (Days)", f"{total_days:.2f}")
    col3.metric("Total Entries", len(df))

    # --- INPUT FORM ---
    with st.expander("➕ Add New Entry", expanded=True):
        with st.form("entry_form", clear_on_submit=True):
            new_date = st.date_input("Date", datetime.now())
            new_skill = st.selectbox("Skill", ["Listening", "Speaking", "Reading", "Writing", "Grammar", "Vocabulary", "Other"])
            new_time = st.number_input("Time Spent (Minutes)", min_value=1, step=1, value=30)
            
            submit = st.form_submit_button("Add to Log & Save to GitHub")
            
            if submit:
                # Add new row to dataframe
                new_row = pd.DataFrame({
                    "Date": [pd.to_datetime(new_date)],
                    "Skill": [new_skill],
                    "Time Spent": [new_time]
                })
                st.session_state.df = pd.concat([st.session_state.df, new_row], ignore_index=True)
                
                # Immediately push to GitHub
                with st.spinner("Saving to GitHub..."):
                    success = save_to_github(gh_token, gh_repo, gh_path, st.session_state.df, st.session_state.file_sha)
                    if success:
                        st.success("Entry added and saved to GitHub!")
                        # Reload to get the new SHA so subsequent saves don't fail
                        _, st.session_state.file_sha, _ = load_data_from_github(gh_token, gh_repo, gh_path)
                        st.rerun()

    # --- WEEKLY SUMMARY ---
    st.subheader("📊 Weekly Summary")
    
    if not df.empty and df['Date'].notna().any():
        # Replicate Excel "Minggu" grouping
        start_date = df['Date'].min()
        df_weekly = df.copy()
        # Calculate week number relative to the first study date
        df_weekly['Week Num'] = df_weekly['Date'].apply(lambda x: ((x - start_date).days // 7) + 1 if pd.notna(x) else 0)
        
        weekly_summary = df_weekly.groupby('Week Num')['Time Spent'].sum().reset_index()
        weekly_summary['Hours'] = (weekly_summary['Time Spent'] / 60).round(2)
        weekly_summary['Week Label'] = weekly_summary['Week Num'].apply(lambda x: f"Minggu {int(x)}")
        
        st.table(weekly_summary[['Week Label', 'Hours']].rename(columns={'Hours': 'Total Waktu (Jam)'}))
    else:
        st.info("Not enough data to generate weekly summary.")

    # --- DATA TABLE ---
    st.subheader("📝 Raw Logs")
    if not df.empty:
        # Format dates nicely for display
        display_df = df.copy()
        display_df['Date'] = display_df['Date'].dt.strftime("%A, %d %b %Y")
        st.dataframe(display_df.sort_values(by="Date", ascending=False), use_container_width=True)

else:
    st.info("👈 Please enter your GitHub credentials in the sidebar and click 'Connect' to load your data.")
