import streamlit as st
import pandas as pd
from github import Github
from datetime import datetime
import io

# --- CONFIGURATION ---
# Replace these with your details or use Streamlit Secrets
GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN", "YOUR_GITHUB_TOKEN")
REPO_NAME = "sannflux/english-tracker"
FILE_PATH = "data.csv"

st.set_page_config(page_title="English Learning Tracker", layout="wide")

# --- GITHUB HELPER FUNCTIONS ---
def load_data_from_github():
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(REPO_NAME)
        contents = repo.get_contents(FILE_PATH)
        df = pd.read_csv(io.StringIO(contents.decoded_content.decode()))
        
        # CLEANING LOGIC: Fix the "unconverted data" error
        # 1. Strip whitespace from headers and strings
        df.columns = df.columns.str.strip()
        df['Date'] = df['Date'].astype(str).str.strip()
        
        # 2. Replace empty strings with NaN so we can forward fill
        df['Date'] = df['Date'].replace('', pd.NA).replace('nan', pd.NA)
        
        # 3. Forward fill: If a date is missing, take the one from the row above
        df['Date'] = df['Date'].ffill()
        
        # 4. Convert to datetime (Handling your specific format)
        df['Date'] = pd.to_datetime(df['Date'], format="%A, %d %B %Y", errors='coerce')
        
        # 5. Drop rows where Time Spent is empty (if any)
        df = df.dropna(subset=['Time Spent'])
        
        return df, contents.sha
    except Exception as e:
        st.error(f"Error connecting to GitHub: {e}")
        return pd.DataFrame(columns=["Date", "Skill", "Time Spent"]), None

def save_to_github(df, sha):
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(REPO_NAME)
        
        # Prepare CSV string (Convert dates back to your preferred string format)
        df_to_save = df.copy()
        df_to_save['Date'] = df_to_save['Date'].dt.strftime("%A, %d %B %Y")
        csv_buffer = io.StringIO()
        df_to_save.to_csv(csv_buffer, index=False)
        
        repo.update_file(
            path=FILE_PATH,
            message="Update English learning log",
            content=csv_buffer.getvalue(),
            sha=sha
        )
        st.success("Data successfully saved to GitHub!")
    except Exception as e:
        st.error(f"Error saving to GitHub: {e}")

# --- APP UI ---
st.title("📚 English Progress Tracker")

# Load Data
df, file_sha = load_data_from_github()

if not df.empty:
    # --- STATISTICS SECTION ---
    col1, col2, col3 = st.columns(3)
    
    total_minutes = df['Time Spent'].sum()
    total_hours = total_minutes / 60
    total_days = total_hours / 24
    
    col1.metric("Total Time (Hours)", f"{total_hours:.1f}")
    col2.metric("Total Time (Days)", f"{total_days:.2f}")
    col3.metric("Entries", len(df))

    # --- INPUT FORM ---
    with st.expander("➕ Add New Entry", expanded=True):
        with st.form("entry_form"):
            new_date = st.date_input("Date", datetime.now())
            new_skill = st.text_input("Skill (e.g., Listening, Speaking)")
            new_time = st.number_input("Time Spent (Minutes)", min_value=1, step=1)
            
            submit = st.form_submit_button("Add to Log")
            
            if submit:
                # Format the new date to match your style
                new_row = pd.DataFrame({
                    "Date": [pd.to_datetime(new_date)],
                    "Skill": [new_skill],
                    "Time Spent": [new_time]
                })
                df = pd.concat([df, new_row], ignore_index=True)
                save_to_github(df, file_sha)
                st.rerun()

    # --- WEEKLY SUMMARY (Like your screenshot) ---
    st.subheader("📊 Weekly Summary")
    
    # Calculate Week Number based on the first entry
    if not df.empty:
        start_date = df['Date'].min()
        df['Week Num'] = df['Date'].apply(lambda x: ((x - start_date).days // 7) + 1)
        weekly_summary = df.groupby('Week Num')['Time Spent'].sum().reset_index()
        weekly_summary['Hours'] = weekly_summary['Time Spent'] / 60
        weekly_summary['Week Label'] = weekly_summary['Week Num'].apply(lambda x: f"Minggu {int(x)}")
        
        st.table(weekly_summary[['Week Label', 'Hours']].rename(columns={'Hours': 'Total Waktu (Jam)'}))

    # --- DATA TABLE ---
    st.subheader("📝 Raw Logs")
    st.dataframe(df[['Date', 'Skill', 'Time Spent']].sort_values(by="Date", ascending=False), use_container_width=True)

else:
    st.info("No data found or still loading...")
