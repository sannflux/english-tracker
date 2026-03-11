import streamlit as st
import pandas as pd
from github import Github
from datetime import datetime, timedelta
import io
import plotly.express as px
import plotly.graph_objects as go
import numpy as np

# --- CONFIGURATION & SESSION STATE ---
st.set_page_config(page_title="English Pro Tracker", layout="wide", page_icon="🇬🇧")

# Initialize Session States
for key in ['df', 'file_sha', 'prev_level', 'saved_token', 'saved_repo']:
    if key not in st.session_state:
        st.session_state[key] = None if key not in ['prev_level'] else 0
        if key in ['saved_token', 'saved_repo']: st.session_state[key] = ""

# --- SECRETS FALLBACK ---
try:
    DEFAULT_TOKEN = st.secrets.get("GH_TOKEN", "")
    DEFAULT_REPO = st.secrets.get("GH_REPO", "sannflux/english-tracker")
except Exception:
    DEFAULT_TOKEN = ""
    DEFAULT_REPO = "sannflux/english-tracker"

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
            df['Skill'] = df['Skill'].astype(str).str.strip().ffill().fillna("Unspecified")

        if 'Time Spent' in df.columns:
            df['Time Spent'] = pd.to_numeric(df['Time Spent'], errors='coerce').fillna(0)
            
        if 'Notes' not in df.columns:
            df['Notes'] = ""
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
        res = repo.update_file(path=file_path, message="Sync Study Log", content=csv_buffer.getvalue(), sha=current_sha)
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
    tags = ""
    note_l = note.lower()
    if any(w in note_l for w in ['podcast', 'listening', 'audio', 'bbc']): tags += "🎧 "
    if any(w in note_l for w in ['book', 'read', 'article', 'novel']): tags += "📖 "
    if any(w in note_l for w in ['video', 'youtube', 'movie', 'netflix']): tags += "📺 "
    if any(w in note_l for w in ['write', 'essay', 'diary']): tags += "✍️ "
    return f"{tags}{note}"

# --- SIDEBAR ---
with st.sidebar:
    st.header("🔑 Connection")
    init_token = st.session_state.saved_token or DEFAULT_TOKEN
    init_repo = st.session_state.saved_repo or DEFAULT_REPO
    gh_token = st.text_input("GitHub Token", type="password", value=init_token)
    gh_repo = st.text_input("Repo", value=init_repo)
    
    if st.checkbox("Remember Credentials", value=bool(st.session_state.saved_token)):
        st.session_state.saved_token, st.session_state.saved_repo = gh_token, gh_repo
    
    if st.button("🔄 Force Sync", use_container_width=True):
        load_data_from_github.clear()
        df, sha, status = load_data_from_github(gh_token, gh_repo, "data.csv")
        if status == "success":
            st.session_state.df, st.session_state.file_sha = df, sha
            st.success("Data Loaded!")
        else: st.error(status)
                
    st.divider()
    weekly_goal = st.slider("Weekly Goal (Hours)", 1, 30, 5)

# --- MAIN UI ---
st.title("🇬🇧 English Learning Pro")

if st.session_state.df is not None:
    df = st.session_state.df.copy()
    
    # 1. ENHANCED CALCULATIONS
    total_hrs = df['Time Spent'].sum() / 60
    streak = get_streak(df)
    level = int(total_hrs // 50) + 1
    xp_progress = (total_hrs % 50) / 50
    
    start_date = df['Date'].min()
    df['Study_Week'] = ((df['Date'] - start_date).dt.days // 7) + 1
    df['Week_Label'] = "Week " + df['Study_Week'].astype(str).str.zfill(2)
    
    now = datetime.now()
    curr_week_num = ((now - start_date).days // 7) + 1
    curr_week_label = "Week " + str(curr_week_num).zfill(2)
    this_week_hrs = df[df['Week_Label'] == curr_week_label]['Time Spent'].sum() / 60

    if level > st.session_state.prev_level and st.session_state.prev_level != 0:
        st.balloons()
    st.session_state.prev_level = level

    # 2. METRICS ROW
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Current Level", f"Lvl {level}")
    m2.metric("Total Study", f"{total_hrs:.1f}h")
    m3.metric("Daily Streak", f"{streak} Days 🔥")
    m4.metric("This Week", f"{this_week_hrs:.1f}h", f"{this_week_hrs - weekly_goal:.1f}h vs Goal")
    st.progress(xp_progress, text=f"XP to Level {level+1}")

    st.divider()

    col_in, col_viz = st.columns([1, 2.5])
    
    with col_in:
        # FEATURE 1: Quick-Log Sprint Buttons
        st.subheader("⚡ Quick Log")
        q1, q2, q3 = st.columns(3)
        quick_data = None
        if q1.button("15m"): quick_data = (15, "Quick 15m Sprint")
        if q2.button("30m"): quick_data = (30, "Standard 30m Session")
        if q3.button("60m"): quick_data = (60, "Deep 60m Study")
        
        if quick_data:
            new_row = pd.DataFrame({"Date":[pd.to_datetime(now.date())], "Skill":["Reading"], "Time Spent":[quick_data[0]], "Notes":[quick_data[1]]})
            st.session_state.df = pd.concat([st.session_state.df, new_row], ignore_index=True)
            new_sha = save_to_github(gh_token, gh_repo, "data.csv", st.session_state.df, st.session_state.file_sha)
            if new_sha:
                st.session_state.file_sha = new_sha
                st.toast(f"Logged {quick_data[0]}m instantly!")
                st.rerun()

        st.subheader("➕ Custom Session")
        with st.form("new_entry", clear_on_submit=True):
            d = st.date_input("Date", now)
            s = st.selectbox("Skill", ["Listening", "Speaking", "Reading", "Writing", "Grammar", "Vocabulary", "Listening dan writing"])
            t = st.number_input("Minutes", 1, 600, 30)
            n = st.text_input("Notes", placeholder="e.g., Finished BBC Article")
            if st.form_submit_button("Push to GitHub", use_container_width=True):
                if not n.strip(): st.error("Please add a note!")
                else:
                    new_row = pd.DataFrame({"Date":[pd.to_datetime(d)], "Skill":[s], "Time Spent":[t], "Notes":[n]})
                    st.session_state.df = pd.concat([st.session_state.df, new_row], ignore_index=True)
                    new_sha = save_to_github(gh_token, gh_repo, "data.csv", st.session_state.df, st.session_state.file_sha)
                    if new_sha:
                        st.session_state.file_sha = new_sha
                        st.success("Synced!")
                        st.rerun()

    with col_viz:
        st.subheader("📊 Performance Analytics")
        tab_week, tab_skill, tab_heat = st.tabs(["Weekly Momentum", "Skill Mix", "Activity Heatmap"])
        
        with tab_week:
            # FEATURE 8: Bar Chart with Moving Average Trend
            weekly_df = df.groupby('Week_Label')['Time Spent'].sum().reset_index()
            weekly_df['Hours'] = weekly_df['Time Spent'] / 60
            weekly_df = weekly_df.sort_values('Week_Label')
            weekly_df['Moving_Avg'] = weekly_df['Hours'].rolling(window=3, min_periods=1).mean()
            
            fig = go.Figure()
            fig.add_trace(go.Bar(x=weekly_df['Week_Label'], y=weekly_df['Hours'], name="Weekly Hours", marker_color='#00CC96'))
            fig.add_trace(go.Scatter(x=weekly_df['Week_Label'], y=weekly_df['Moving_Avg'], name="Trend (3wk Avg)", line=dict(color='#FFA15A', width=3)))
            fig.update_layout(margin=dict(l=0,r=0,t=20,b=0), height=350, legend=dict(orientation="h", yanchor="bottom", y=1.02))
            st.plotly_chart(fig, use_container_width=True)
            
        with tab_skill:
            skill_df = df.groupby('Skill')['Time Spent'].sum().reset_index()
            fig2 = px.pie(skill_df, values='Time Spent', names='Skill', hole=0.5, color_discrete_sequence=px.colors.qualitative.Pastel)
            fig2.update_layout(margin=dict(l=0,r=0,t=0,b=0), height=350)
            st.plotly_chart(fig2, use_container_width=True)

        with tab_heat:
            # FEATURE 7: GitHub Style Heatmap (Simplified for Journey)
            df['Day'] = df['Date'].dt.day_name()
            heatmap_data = df.pivot_table(index='Day', columns='Week_Label', values='Time Spent', aggfunc='sum').fillna(0)
            day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            heatmap_data = heatmap_data.reindex(day_order)
            fig3 = px.imshow(heatmap_data, color_continuous_scale='Greens', title="Daily Intensity Heatmap")
            fig3.update_layout(height=350, margin=dict(l=0,r=0,t=30,b=0))
            st.plotly_chart(fig3, use_container_width=True)

    st.subheader("📝 Study History")
    display_df = st.session_state.df.copy()
    
    # FEATURE 11: Auto-Tagging Notes
    display_df['Notes'] = display_df['Notes'].apply(add_visual_tags)
    display_df['Date'] = display_df['Date'].dt.date
    display_df = display_df.sort_values("Date", ascending=False).reset_index(drop=True)
    
    edited = st.data_editor(
        display_df[['Date', 'Skill', 'Time Spent', 'Notes']],
        use_container_width=True,
        num_rows="dynamic",
        column_config={
            "Date": st.column_config.DateColumn(required=True),
            "Skill": st.column_config.TextColumn("Skill", required=True),
            "Time Spent": st.column_config.NumberColumn("Min", min_value=1),
            "Notes": st.column_config.TextColumn("Study Notes & Tags", width="large")
        }
    )
    
    if not edited.equals(display_df[['Date', 'Skill', 'Time Spent', 'Notes']]):
        if st.button("💾 Save All Changes", type="primary"):
            save_df = edited.copy()
            save_df['Date'] = pd.to_datetime(save_df['Date'])
            # Clean visual tags before saving back to CSV
            save_df['Notes'] = save_df['Notes'].str.replace('🎧 ', '').str.replace('📖 ', '').str.replace('📺 ', '').str.replace('✍️ ', '')
            new_sha = save_to_github(gh_token, gh_repo, "data.csv", save_df, st.session_state.file_sha)
            if new_sha:
                st.session_state.file_sha = new_sha
                st.session_state.df = save_df
                st.success("Database Updated!")
                st.rerun()
                
    csv_report = display_df.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Export Full Report (CSV)", csv_report, f"English_Report_{now.date()}.csv", "text/csv", use_container_width=True)

else:
    st.info("👈 Enter Token and click Force Sync to start.")
