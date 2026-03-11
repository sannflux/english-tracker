import streamlit as st
import pandas as pd
from github import Github
from datetime import datetime
import os

# --- CONFIGURATION ---
# Set these up in Streamlit Secrets for security
# GITHUB_TOKEN: Your Personal Access Token
# GITHUB_REPO: "your-username/your-repo-name"
GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN", "")
GITHUB_REPO = st.secrets.get("GITHUB_REPO", "")
DATA_FILE = "data.csv"

st.set_page_config(page_title="English Study Tracker", layout="wide")

# --- FUNCTIONS ---
def load_data():
    """Load data from GitHub or local cache."""
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        file_content = repo.get_contents(DATA_FILE)
        df = pd.read_csv(file_content.download_url)
        # Convert date column to datetime objects
        df['date'] = pd.to_datetime(df['date'])
        return df, file_content.sha
    except Exception as e:
        # Return empty df if file doesn't exist yet
        return pd.DataFrame(columns=['date', 'skill', 'minutes']), None

def save_to_github(df, sha):
    """Save the updated dataframe back to GitHub."""
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(GITHUB_REPO)
        csv_content = df.to_csv(index=False)
        repo.update_file(DATA_FILE, "Update study data", csv_content, sha)
        st.success("✅ Data saved to GitHub!")
    except Exception as e:
        st.error(f"❌ Error saving to GitHub: {e}")

def get_relative_week(date, start_date):
    """Calculates 'Week X' based on the study start date."""
    days_diff = (date - start_date).days
    week_num = (days_diff // 7) + 1
    return f"Minggu {int(week_num)}"

# --- APP UI ---
st.title("🇬🇧 English Learning Tracker")

# 1. Load Data
df, file_sha = load_data()

# 2. Sidebar Input Form
with st.sidebar:
    st.header("Add New Session")
    new_date = st.date_input("Date", datetime.now())
    new_skill = st.selectbox("Skill", ["Speaking", "Listening", "Reading", "Writing", "Grammar", "Vocabulary"])
    new_minutes = st.number_input("Time Spent (Minutes)", min_value=1, value=30)
    
    if st.button("Add to Log"):
        new_entry = pd.DataFrame([[pd.to_datetime(new_date), new_skill, new_minutes]], 
                                 columns=['date', 'skill', 'minutes'])
        df = pd.concat([df, new_entry], ignore_index=True)
        save_to_github(df, file_sha)
        st.rerun()

# 3. Calculations & Logic
if not df.empty:
    # Sort by date
    df = df.sort_values(by='date', ascending=False)
    
    # Calculate Relative Weeks
    start_date = df['date'].min()
    df['Week'] = df['date'].apply(lambda x: get_relative_week(x, start_date))

    # Metric Totals
    total_min = df['minutes'].sum()
    total_hours = round(total_min / 60, 1)
    total_days = round(total_hours / 24, 1)

    # UI Layout
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Waktu (Menit)", f"{total_min}")
    col2.metric("Total Jam", f"{total_hours}")
    col3.metric("Total Hari", f"{total_days}")

    # 4. Summary Table (Like the Excel screenshot)
    st.subheader("Summary per Minggu")
    # Group by Week and sum hours
    weekly_summary = df.copy()
    weekly_summary['hours'] = weekly_summary['minutes'] / 60
    summary_table = weekly_summary.groupby('Week')['hours'].sum().reset_index()
    
    # Sort "Minggu X" numerically
    summary_table['week_num'] = summary_table['Week'].str.extract('(\d+)').astype(int)
    summary_table = summary_table.sort_values('week_num', ascending=False).drop(columns=['week_num'])
    
    st.table(summary_table.style.format({"hours": "{:.1f}"}))

    # 5. Raw Data Logs
    st.subheader("Detail Log")
    # Format date for display like "Friday, 12 September 2025"
    display_df = df.copy()
    display_df['date'] = display_df['date'].dt.strftime('%A, %d %B %Y')
    st.dataframe(display_df, use_container_width=True)

else:
    st.info("No data found. Add your first study session in the sidebar!")

# 6. CSV Import (Optional feature to migrate old data)
with st.expander("Import Previous Data (CSV)"):
    uploaded_file = st.file_uploader("Upload your current data.csv", type="csv")
    if uploaded_file is not None:
        imported_df = pd.read_csv(uploaded_file)
        if st.button("Confirm Import and Overwrite"):
            save_to_github(imported_df, file_sha)
            st.rerun()
