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
for key in ['df', 'file_sha', 'prev_level', 'saved_token', 'saved_repo', 'accent_color', 'zen_mode', 'milestone_reward', 'gemini_key']:
    if key not in st.session_state:
        st.session_state[key] = None if key not in ['prev_level'] else 0
        if key == 'accent_color': st.session_state[key] = "#00CC96"
        if key == 'zen_mode': st.session_state[key] = False
        if key == 'milestone_reward': st.session_state[key] = "Treat myself to coffee"
        if key in ['saved_token', 'saved_repo', 'gemini_key']: st.session_state[key] = ""

# --- AI COACH LOGIC (GEMINI) ---
def get_ai_recommendation(api_key, dataframe):
    if not api_key: return "Please provide a Gemini API key in the sidebar."
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash-lite')
        
        summary = dataframe.groupby('Skill')['Time Spent'].sum().to_dict()
        prompt = f"""
        Act as an expert English Study Coach. Here is my study data (Skill: Total Minutes): {summary}.
        Based on these hours, identify which skill I am neglecting most and suggest a specific 30-minute 
        activity I should do today to improve. Keep it under 100 words.
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI Error: {str(e)}"

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

# --- SIDEBAR ---
with st.sidebar:
    st.header("🔑 Connection")
    gh_token = st.text_input("GitHub Token", type="password", value=st.session_state.saved_token)
    gh_repo = st.text_input("Repo", value=st.session_state.saved_repo)
    st.session_state.gemini_key = st.text_input("Gemini API Key", type="password", value=st.session_state.gemini_key)
    
    if st.checkbox("Remember Credentials", value=bool(st.session_state.saved_token)):
        st.session_state.saved_token, st.session_state.saved_repo = gh_token, gh_repo
    
    if st.button("🔄 Force Sync", use_container_width=True):
        load_data_from_github.clear()
        df, sha, status = load_data_from_github(gh_token, gh_repo, "data.csv")
        if status == "success":
            st.session_state.df, st.session_state.file_sha = df, sha
            st.success("Synced!")
        else: st.error(status)
                
    st.divider()
    
    if st.session_state.df is not None and st.button("↩️ Undo Last Log", use_container_width=True):
        undo_df = st.session_state.df.iloc[:-1]
        new_sha = save_to_github(gh_token, gh_repo, "data.csv", undo_df, st.session_state.file_sha)
        if new_sha:
            st.session_state.df = undo_df
            st.session_state.file_sha = new_sha
            st.toast("Reverted last log!")
            st.rerun()

    if st.session_state.df is not None:
        st.header("🤖 AI Study Coach")
        if st.button("Ask Coach"):
            with st.spinner("Analyzing history..."):
                rec = get_ai_recommendation(st.session_state.gemini_key, st.session_state.df)
                st.write(rec)

    st.divider()
    st.session_state.zen_mode = st.toggle("🧘 Zen Mode", value=st.session_state.zen_mode)
    
    theme = st.selectbox("Theme", ["Emerald City", "Ocean Deep", "Sunset Orange", "Royal Purple"])
    theme_map = {"Emerald City": "#00CC96", "Ocean Deep": "#0099FF", "Sunset Orange": "#FF5733", "Royal Purple": "#8E44AD"}
    st.session_state.accent_color = theme_map[theme]
    
    weekly_goal = st.slider("Weekly Goal (Hours)", 1, 40, 5)
    yearly_goal = st.slider("Yearly Goal (Hours)", 50, 1000, 200, step=10) # FEATURE 5 Setup

# --- MAIN UI ---
if st.session_state.df is not None:
    df = st.session_state.df.copy()
    now = datetime.now()
    all_skills = ["Listening", "Speaking", "Reading", "Writing", "Grammar", "Vocabulary"]
    
    # CALCULATIONS
    start_date = df['Date'].min()
    df['Study_Week'] = ((df['Date'] - start_date).dt.days // 7) + 1
    df['Week_Label'] = "Week " + df['Study_Week'].astype(str).str.zfill(2)
    total_hrs = df['Time Spent'].sum() / 60
    level = int(total_hrs // 50) + 1
    xp_progress = (total_hrs % 50) / 50
    streak = get_streak(df)

    curr_week_label = "Week " + str(((now - start_date).days // 7) + 1).zfill(2)
    this_week_min = df[df['Week_Label'] == curr_week_label]['Time Spent'].sum()
    remaining_min = max(0, (weekly_goal * 60) - this_week_min)
    days_left = 7 - now.weekday()
    pace = remaining_min / days_left if days_left > 0 else remaining_min

    st.title("🇬🇧 English Pro Elite")
    with st.expander(f"🎁 Level Reward: {st.session_state.milestone_reward}", expanded=False):
        st.session_state.milestone_reward = st.text_input("Reward", value=st.session_state.milestone_reward)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Level", f"Lvl {level}")
    m2.metric("Total", f"{total_hrs:.1f}h")
    m3.metric("Streak", f"{streak} Days")
    m4.metric("Pacer", f"{remaining_min/60:.1f}h left", f"{pace:.0f}m / day")
    st.progress(xp_progress)

    if not st.session_state.zen_mode:
        st.divider()
        tab_dash, tab_insights, tab_trophy, tab_history, tab_share = st.tabs(["📈 Dashboard", "🧠 Deep Insights", "🏆 Trophies", "📝 History", "📸 Share"])

        with tab_dash:
            # FEATURE 5: Macro-Goals (Yearly Tracking)
            df_year = df[df['Date'].dt.year == now.year]
            ytd_hrs = df_year['Time Spent'].sum() / 60
            day_of_year = now.timetuple().tm_yday
            expected_ytd = (yearly_goal / 365) * day_of_year
            diff = ytd_hrs - expected_ytd
            
            st.info(f"📅 **Yearly Goal Pacing:** You have studied {ytd_hrs:.1f}h out of your {yearly_goal}h goal for the year. "
                    f"At this point in the year, you should be at {expected_ytd:.1f}h. "
                    f"**({'+' if diff >= 0 else ''}{diff:.1f}h {'ahead of' if diff >= 0 else 'behind'} schedule)**")

            c1, c2 = st.columns([2, 1])
            with c1:
                st.subheader("🗓️ Study Intensity (GitHub Style)")
                df_2026 = df[df['Date'].dt.year == now.year].copy()
                if not df_2026.empty:
                    df_2026['Day'] = df_2026['Date'].dt.day_name()
                    df_2026['Week_Num'] = df_2026['Date'].dt.isocalendar().week
                    day_map = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                    hm_pivot = df_2026.pivot_table(index='Day', columns='Week_Num', values='Time Spent', aggfunc='sum').reindex(day_map).fillna(0)
                    fig_gh = px.imshow(hm_pivot, color_continuous_scale='Greens', aspect="auto")
                    fig_gh.update_layout(height=250, margin=dict(l=0,r=0,t=0,b=0), coloraxis_showscale=False)
                    st.plotly_chart(fig_gh, use_container_width=True)
                
                df_sorted = df.sort_values('Date')
                df_sorted['Cumulative_Hrs'] = df_sorted['Time Spent'].cumsum() / 60
                st.plotly_chart(px.area(df_sorted, x='Date', y='Cumulative_Hrs', title="Learning Mountain", color_discrete_sequence=[st.session_state.accent_color]), use_container_width=True)
            with c2:
                radar_data = df.groupby('Skill')['Time Spent'].sum().reindex(all_skills).fillna(0)
                fig_radar = go.Figure(data=go.Scatterpolar(r=radar_data.values, theta=all_skills, fill='toself', line_color=st.session_state.accent_color))
                fig_radar.update_layout(polar=dict(radialaxis=dict(visible=False)), showlegend=False, title="Skill Diet Balancer", height=350)
                st.plotly_chart(fig_radar, use_container_width=True)

        with tab_insights:
            # FEATURE 6: Future Self Predictor
            st.subheader("🔮 The 'Future Self' Predictor")
            last_14 = now.date() - timedelta(days=14)
            df_14 = df[df['Date'].dt.date >= last_14]
            avg_14_daily = (df_14['Time Spent'].sum() / 60) / 14
            next_level_hrs = level * 50
            hrs_needed = next_level_hrs - total_hrs
            
            if avg_14_daily > 0:
                days_needed = int(hrs_needed / avg_14_daily)
                target_date = now.date() + timedelta(days=days_needed)
                st.success(f"Based on your recent 14-day average ({avg_14_daily:.1f} hours/day), you will reach **Level {level+1}** on **{target_date.strftime('%B %d, %Y')}**!")
            else:
                st.warning("Study more in the last 14 days to generate a projection for your next level!")

            st.divider()
            
            i1, i2 = st.columns(2)
            with i1:
                target_past = (now - timedelta(days=30)).date()
                past_data = df[df['Date'].dt.date == target_past]
                st.subheader("🕰️ Time Machine")
                if not past_data.empty:
                    st.info(f"30 Days ago you studied **{past_data['Time Spent'].sum()}m**. Notes: *{past_data['Notes'].iloc[0]}*")
                else: st.write("No data found for exactly 30 days ago.")
            with i2:
                df['Date_Only'] = df['Date'].dt.date
                pivot = df.groupby(['Date_Only', 'Skill']).size().unstack(fill_value=0)
                st.plotly_chart(px.imshow(pivot.corr().fillna(0), text_auto=True, title="Skill Pairing", color_continuous_scale="Purples"), use_container_width=True)

        with tab_trophy:
            badges = [("First Step", "Logged 1st session", total_hrs > 0), ("Novice", "10h total", total_hrs >= 10), ("Master", "Level 10", level >= 10)]
            cols = st.columns(3)
            for i, (name, desc, unlocked) in enumerate(badges):
                if unlocked: cols[i].success(f"🌟 **{name}**\n\n{desc}")
                else: cols[i].info(f"🔒 **{name}**\n\n{desc}")

        with tab_history:
            display_df = df.copy().sort_values("Date", ascending=False)
            display_df['Delete'] = False
            display_df['Date'] = display_df['Date'].dt.date
            edited_hist = st.data_editor(display_df[['Delete', 'Date', 'Skill', 'Time Spent', 'Notes']], use_container_width=True)
            if st.button("🗑️ Commit Changes", type="primary"):
                filtered_save = edited_hist[edited_hist['Delete'] == False].drop(columns=['Delete'])
                filtered_save['Date'] = pd.to_datetime(filtered_save['Date'])
                new_sha = save_to_github(gh_token, gh_repo, "data.csv", filtered_save, st.session_state.file_sha)
                if new_sha: st.rerun()
                
        with tab_share:
            # FEATURE 7: Plotly Share Card
            st.subheader("📸 Your Share Card")
            st.write("Hover over the image below and click the 📷 icon in the top right corner to download this as a PNG for social media!")
            
            fig_share = go.Figure()
            # Add decorative background elements
            fig_share.add_trace(go.Scatter(x=[0, 10], y=[0, 10], mode="markers", marker=dict(size=0.1, color="rgba(0,0,0,0)"), hoverinfo="none"))
            
            # Text Annotations for the Card
            fig_share.add_annotation(text="🇬🇧 English Learning Journey", x=5, y=9, font=dict(size=24, color="gray"), showarrow=False)
            fig_share.add_annotation(text=f"Level {level} Scholar", x=5, y=7.5, font=dict(size=36, color=st.session_state.accent_color, weight="bold"), showarrow=False)
            fig_share.add_annotation(text=f"{total_hrs:.1f} Total Hours", x=5, y=5.5, font=dict(size=28), showarrow=False)
            fig_share.add_annotation(text=f"{streak} Day Streak 🔥", x=5, y=3.5, font=dict(size=28), showarrow=False)
            fig_share.add_annotation(text=f"Favorite Skill: {df.groupby('Skill')['Time Spent'].sum().idxmax()}", x=5, y=1.5, font=dict(size=20, color="gray"), showarrow=False)
            
            fig_share.update_layout(
                xaxis=dict(visible=False, range=[0, 10]), 
                yaxis=dict(visible=False, range=[0, 10]),
                plot_bgcolor="white" if st.session_state.accent_color in ["#00CC96", "#0099FF"] else "#1E1E1E",
                margin=dict(l=10, r=10, t=10, b=10),
                height=500,
                width=500
            )
            st.plotly_chart(fig_share, config={'displayModeBar': True, 'displaylogo': False})

    # LOG SESSION
    st.divider()
    with st.expander("➕ Log New Session", expanded=True):
        with st.form("new_entry", clear_on_submit=True):
            col_d, col_s, col_t = st.columns(3)
            d = col_d.date_input("Date", now)
            s = col_s.selectbox("Skill", all_skills)
            t = col_t.number_input("Minutes", 1, 600, 30)
            n = st.text_input("Notes")
            if st.form_submit_button("Log Entry", use_container_width=True):
                new_row = pd.DataFrame({"Date":[pd.to_datetime(d)], "Skill":[s], "Time Spent":[t], "Notes":[n]})
                st.session_state.df = pd.concat([st.session_state.df, new_row], ignore_index=True)
                new_sha = save_to_github(gh_token, gh_repo, "data.csv", st.session_state.df, st.session_state.file_sha)
                if new_sha:
                    st.session_state.file_sha = new_sha
                    st.rerun()
else:
    st.info("👈 Enter Connection info in sidebar to begin.")
