import streamlit as st
import pandas as pd
from github import Github
from datetime import datetime, timedelta
import io
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import google.generativeai as genai

# --- CONFIGURATION & SESSION STATE ---
st.set_page_config(page_title="English Pro Elite", layout="wide", page_icon="🇬🇧")

# Initialize Session States
for key in ['df', 'file_sha', 'prev_level', 'saved_token', 'saved_repo', 'accent_color', 'zen_mode', 'milestone_reward', 'gemini_key', 'custom_skills']:
    if key not in st.session_state:
        st.session_state[key] = None if key not in ['prev_level'] else 0
        if key == 'accent_color': st.session_state[key] = "#00CC96"
        if key == 'zen_mode': st.session_state[key] = False
        if key == 'milestone_reward': st.session_state[key] = "Treat myself to coffee"
        if key in ['saved_token', 'saved_repo', 'gemini_key', 'custom_skills']: st.session_state[key] = ""

# --- AI COACH LOGIC (GEMINI) ---
def get_ai_recommendation(api_key, dataframe):
    if not api_key: return "Please provide a Gemini API key in the sidebar."
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash-lite')
        summary = dataframe.groupby('Skill')['Time Spent'].sum().to_dict()
        prompt = f"Act as an English Coach. Here is my data: {summary}. Suggest one 30m activity for today. Under 80 words."
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI Error: {str(e)}"

# --- GITHUB HELPER ---
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
            df['Skill'] = df['Skill'].astype(str).str.strip().ffill().fillna("Reading")
        if 'Time Spent' in df.columns:
            df['Time Spent'] = pd.to_numeric(df['Time Spent'], errors='coerce').fillna(0)
        if 'Notes' not in df.columns: df['Notes'] = ""
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
        res = repo.update_file(path=file_path, message="Sync Elite Tracker", content=csv_buffer.getvalue(), sha=current_sha)
        return res['content'].sha 
    except Exception as e:
        st.error(f"Save Error: {e}")
        return None

# --- HELPERS ---
def get_streak(df):
    if df is None or df.empty: return 0
    dates = sorted(df['Date'].dt.date.dropna().unique(), reverse=True)
    if not dates or dates[0] < datetime.now().date() - timedelta(days=1): return 0
    streak, curr = 0, datetime.now().date()
    for d in dates:
        if d == curr or d == curr - timedelta(days=1):
            streak += 1
            curr = d
        else: break
    return streak

# --- SIDEBAR ---
with st.sidebar:
    st.header("🔑 Connection")
    gh_token = st.text_input("GitHub Token", type="password", value=st.session_state.saved_token)
    gh_repo = st.text_input("Repo", value=st.session_state.saved_repo)
    st.session_state.gemini_key = st.text_input("Gemini API Key", type="password", value=st.session_state.gemini_key)
    
    if st.checkbox("Remember Credentials", value=bool(st.session_state.saved_token)):
        st.session_state.saved_token, st.session_state.saved_repo = gh_token, gh_repo
    
    if st.button("🔄 Sync Data", use_container_width=True):
        load_data_from_github.clear()
        df, sha, status = load_data_from_github(gh_token, gh_repo, "data.csv")
        if status == "success":
            st.session_state.df, st.session_state.file_sha = df, sha
            st.success("Synced!")
        else: st.error(status)
                
    st.divider()
    
    if st.session_state.df is not None and st.button("↩️ Undo Last", use_container_width=True):
        undo_df = st.session_state.df.iloc[:-1]
        new_sha = save_to_github(gh_token, gh_repo, "data.csv", undo_df, st.session_state.file_sha)
        if new_sha:
            st.session_state.df, st.session_state.file_sha = undo_df, new_sha
            st.toast("Reverted!")
            st.rerun()

    if st.session_state.df is not None:
        st.header("🤖 AI Coach")
        if st.button("Get Advice"):
            rec = get_ai_recommendation(st.session_state.gemini_key, st.session_state.df)
            st.info(rec)

    st.divider()
    st.session_state.zen_mode = st.toggle("🧘 Zen Mode", value=st.session_state.zen_mode)
    theme = st.selectbox("Theme", ["Emerald City", "Ocean Deep", "Sunset Orange", "Royal Purple"])
    theme_map = {"Emerald City": "#00CC96", "Ocean Deep": "#0099FF", "Sunset Orange": "#FF5733", "Royal Purple": "#8E44AD"}
    st.session_state.accent_color = theme_map[theme]
    
    weekly_goal = st.slider("Weekly Goal (Hrs)", 1, 40, 5)
    yearly_goal = st.slider("Yearly Goal (Hrs)", 50, 1000, 200, step=10)
    with st.expander("⚙️ Settings"):
        st.session_state.custom_skills = st.text_input("Custom Skills", value=st.session_state.custom_skills)

# --- MAIN UI ---
if st.session_state.df is not None:
    df = st.session_state.df.copy()
    now = datetime.now()
    
    # CALCULATIONS
    start_date = df['Date'].min()
    total_hrs = df['Time Spent'].sum() / 60
    current_level = int(total_hrs // 50) + 1
    
    # FEATURE 6: Level-Up Confetti System
    if st.session_state.prev_level != 0 and current_level > st.session_state.prev_level:
        st.snow()
        st.balloons()
        st.success(f"🎊 LEVEL UP! You reached Level {current_level}!")
        st.success(f"🎁 Reward Unlocked: {st.session_state.milestone_reward}")
    st.session_state.prev_level = current_level

    streak = get_streak(df)
    df['Week_Label'] = "Week " + (((df['Date'] - start_date).dt.days // 7) + 1).astype(str).str.zfill(2)
    curr_week_label = "Week " + str(((now - start_date).days // 7) + 1).zfill(2)
    this_week_min = df[df['Week_Label'] == curr_week_label]['Time Spent'].sum()
    remaining_min = max(0, (weekly_goal * 60) - this_week_min)

    st.title("🇬🇧 English Pro Elite")
    
    # Mobile Metrics Row
    m1, m2, m3, m4 = st.columns([1,1,1,1])
    m1.metric("Lvl", current_level)
    m2.metric("Hrs", f"{total_hrs:.1f}")
    m3.metric("Streak", f"{streak}d")
    m4.metric("Goal", f"{remaining_min/60:.1f}h")
    st.progress((total_hrs % 50) / 50)

    if not st.session_state.zen_mode:
        tab_dash, tab_ins, tab_hist, tab_share = st.tabs(["📊 Dash", "🧠 Insights", "📝 Hist", "📸 Share"])

        with tab_dash:
            c1, c2 = st.columns([2, 1])
            with c1:
                # Intensity Heatmap
                df_year = df[df['Date'].dt.year == now.year].copy()
                if not df_year.empty:
                    st.subheader("🗓️ Activity")
                    df_year['Day'] = df_year['Date'].dt.day_name()
                    df_year['Wk'] = df_year['Date'].dt.isocalendar().week
                    hm = df_year.pivot_table(index='Day', columns='Wk', values='Time Spent', aggfunc='sum').reindex(['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']).fillna(0)
                    st.plotly_chart(px.imshow(hm, color_continuous_scale='Greens', height=200), use_container_width=True)
                
                # FEATURE 2: Ghost Pacer on Mountain
                st.subheader("🏔️ Mountain")
                df_sorted = df.sort_values('Date')
                df_sorted['Cumulative'] = df_sorted['Time Spent'].cumsum() / 60
                fig_mtn = px.area(df_sorted, x='Date', y='Cumulative', color_discrete_sequence=[st.session_state.accent_color])
                
                # Ghost Pacer Line
                start_yr = pd.to_datetime(f"{now.year}-01-01")
                end_yr = pd.to_datetime(f"{now.year}-12-31")
                base_hrs = df[df['Date'].dt.year < now.year]['Time Spent'].sum() / 60
                fig_mtn.add_trace(go.Scatter(x=[start_yr, end_yr], y=[base_hrs, base_hrs + yearly_goal], mode='lines', line=dict(color='gray', dash='dash'), name='Goal Pace'))
                st.plotly_chart(fig_mtn, use_container_width=True)

            with c2:
                st.subheader("🎯 Skills")
                base_skills = ["Listening", "Speaking", "Reading", "Writing", "Grammar", "Vocabulary"]
                extra = [s.strip() for s in st.session_state.custom_skills.split(',') if s.strip()]
                all_s = list(dict.fromkeys(base_skills + extra + df['Skill'].unique().tolist()))
                radar_data = df.groupby('Skill')['Time Spent'].sum().reindex(all_s).fillna(0)
                fig_radar = go.Figure(data=go.Scatterpolar(r=radar_data.values, theta=all_s, fill='toself', line_color=st.session_state.accent_color))
                fig_radar.update_layout(polar=dict(radialaxis=dict(visible=False)), height=300, margin=dict(l=20,r=20,t=20,b=20))
                st.plotly_chart(fig_radar, use_container_width=True)

        with tab_ins:
            # Future Predictor
            df_14 = df[df['Date'].dt.date >= (now.date() - timedelta(days=14))]
            avg_d = (df_14['Time Spent'].sum() / 60) / 14
            if avg_d > 0:
                days_to_lvl = int(((current_level * 50) - total_hrs) / avg_d)
                target = now.date() + timedelta(days=days_to_lvl)
                st.success(f"🔮 Level {current_level+1} prediction: **{target.strftime('%d %b %Y')}**")

        with tab_hist:
            # FEATURE 6: Merge & Manage
            if st.button("🧹 Clean Duplicates"):
                m_df = df.copy()
                m_df['D'] = m_df['Date'].dt.date
                m_df = m_df.groupby(['D', 'Skill']).agg({'Time Spent':'sum', 'Notes': lambda x: ' | '.join(set(map(str, x)))}).reset_index().rename(columns={'D':'Date'})
                new_sha = save_to_github(gh_token, gh_repo, "data.csv", m_df, st.session_state.file_sha)
                if new_sha: st.rerun()
            
            display_df = df.copy().sort_values("Date", ascending=False)
            display_df['Del'] = False
            display_df['Date'] = display_df['Date'].dt.date
            edited = st.data_editor(display_df[['Del', 'Date', 'Skill', 'Time Spent', 'Notes']], use_container_width=True)
            if st.button("💾 Save Changes"):
                final = edited[edited['Del'] == False].drop(columns=['Del'])
                final['Date'] = pd.to_datetime(final['Date'])
                save_to_github(gh_token, gh_repo, "data.csv", final, st.session_state.file_sha)
                st.rerun()

        with tab_share:
            if st.button("✨ Reveal Wrapped"):
                st.balloons()
                df_y = df[df['Date'].dt.year == now.year]
                st.success(f"📝 {now.year} Summary: {df_y['Time Spent'].sum():,.0f} mins | Top Skill: {df_y.groupby('Skill')['Time Spent'].sum().idxmax()}")

    # LOG SESSION - FEATURE 2: Mobile Stacked Form
    st.divider()
    with st.expander("➕ Log Session", expanded=True):
        with st.form("new_entry", clear_on_submit=True):
            # Stacked for Mobile
            d = st.date_input("Date", now)
            base_skills = ["Listening", "Speaking", "Reading", "Writing", "Grammar", "Vocabulary"]
            extra = [s.strip() for s in st.session_state.custom_skills.split(',') if s.strip()]
            all_s = list(dict.fromkeys(base_skills + extra + df['Skill'].unique().tolist()))
            s = st.selectbox("Skill", all_s)
            t = st.number_input("Minutes", 1, 600, 30)
            n = st.text_input("Notes")
            if st.form_submit_button("Submit", use_container_width=True):
                new_row = pd.DataFrame({"Date":[pd.to_datetime(d)], "Skill":[s], "Time Spent":[t], "Notes":[n]})
                st.session_state.df = pd.concat([st.session_state.df, new_row], ignore_index=True)
                save_to_github(gh_token, gh_repo, "data.csv", st.session_state.df, st.session_state.file_sha)
                st.rerun()
else:
    st.info("👈 Enter connection info to start.")
