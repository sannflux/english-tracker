import streamlit as st
import pandas as pd
from github import Github
from datetime import datetime, timedelta
import io
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import google.generativeai as genai
import json
import os
import base64

st.set_page_config(page_title="English Pro Elite", layout="wide", page_icon="🇬🇧")

# --- BACKGROUND (LAZY CACHED - unchanged) ---
@st.cache_resource(show_spinner=False)
def get_base64_of_bin_file(bin_file):
    if not os.path.exists(bin_file):
        return ""
    with open(bin_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()

def set_background(png_file):
    if 'bg_base64' not in st.session_state:
        st.session_state.bg_base64 = get_base64_of_bin_file(png_file)
    if st.session_state.bg_base64:
        page_bg_img = f'''
        <style>
        .stApp {{background-image: url("data:image/png;base64,{st.session_state.bg_base64}"); background-size: cover; background-attachment: fixed;}}
        [data-testid="stSidebar"] {{background-color: rgba(0,0,0,0.7) !important; backdrop-filter: blur(10px);}}
        .stTabs [data-baseweb="tab-panel"] {{background-color: rgba(20,20,20,0.6) !important; padding: 20px; border-radius: 15px; backdrop-filter: blur(5px); border: 1px solid rgba(255,255,255,0.1);}}
        [data-testid="stMetricValue"] {{color: white !important;}}
        h1, h2, h3, h4, p, span, .stMarkdown div p {{color: white !important;}}
        .stAlert {{background-color: rgba(0,0,0,0.4) !important; color: white !important; border: 1px solid rgba(255,255,255,0.2) !important;}}
        </style>
        '''
        st.markdown(page_bg_img, unsafe_allow_html=True)

set_background('background.jpg')

# --- CREDENTIALS & SESSION STATE (unchanged + new toggle key) ---
CRED_FILE = "credentials.json"
def load_credentials():
    if os.path.exists(CRED_FILE):
        try:
            with open(CRED_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_credentials_to_disk():
    creds = {"saved_token": st.session_state.saved_token, "saved_repo": st.session_state.saved_repo, "gemini_key": st.session_state.gemini_key}
    with open(CRED_FILE, "w") as f:
        json.dump(creds, f)

local_creds = load_credentials()

for key in ['df', 'file_sha', 'prev_level', 'saved_token', 'saved_repo', 'accent_color', 'zen_mode', 'milestone_reward', 'gemini_key', 'custom_skills', 'last_ai_rec', 'last_ai_time', 'ask_ai_auto', 'milestone_claimed_date']:
    if key not in st.session_state:
        st.session_state[key] = None if key not in ['prev_level'] else 0
        if key == 'accent_color': st.session_state[key] = "#00CC96"
        if key == 'zen_mode': st.session_state[key] = False
        if key == 'milestone_reward': st.session_state[key] = "Treat myself to coffee"
        if key == 'custom_skills': st.session_state[key] = ""
        if key == 'last_ai_rec': st.session_state[key] = ""
        if key == 'last_ai_time': st.session_state[key] = None
        if key == 'ask_ai_auto': st.session_state[key] = False  # YOUR REQUEST: default OFF, no auto on open
        if key == 'milestone_claimed_date': st.session_state[key] = ""
        if key in ['saved_token', 'saved_repo', 'gemini_key']:
            st.session_state[key] = local_creds.get(key, "")

# --- AI COACH (EXACT SAME - now gated by YOUR TOGGLE) ---
def get_ai_recommendation(api_key, dataframe, current_date):
    if not api_key: return "Please provide a Gemini API key in the sidebar."
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash-lite')
        all_time_summary = dataframe.groupby('Skill')['Time Spent'].sum().to_dict()
        last_7_days_df = dataframe[dataframe['Date'].dt.date >= (current_date.date() - timedelta(days=7))]
        recent_summary = last_7_days_df.groupby('Skill')['Time Spent'].sum().to_dict()
        prompt = f"""Act as an expert English Study Coach. Here is my data: Totals: {all_time_summary}, Recent: {recent_summary}. Focus on neglect vs strength. 100 words max."""
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI Error: {str(e)}"

# --- CACHED HELPERS (unchanged) ---
@st.cache_data(ttl=300, show_spinner=False)
def cached_get_streak(_df):
    if _df is None or _df.empty: return 0
    dates = sorted(_df['Date'].dt.date.dropna().unique(), reverse=True)
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

@st.cache_data(ttl=60)
def cached_mountain(df_sorted, accent_color):
    df_sorted['Cumulative_Hrs'] = df_sorted['Time Spent'].cumsum() / 60
    fig = px.area(df_sorted, x='Date', y='Cumulative_Hrs', title="Learning Mountain", color_discrete_sequence=[accent_color])
    fig.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color='white')
    return fig

@st.cache_data(ttl=60)
def cached_donut(diet, accent_color):
    fig = px.pie(names=diet.index, values=diet.values, hole=0.5, title="Skill Diet")
    fig.update_traces(textinfo='label+percent', textposition='inside')
    fig.update_layout(showlegend=False, plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', font_color='white')
    return fig

# --- GITHUB (enhanced with validation - chosen idea) ---
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
            df['Date'] = df['Date'].apply(lambda x: str(x).split(',')[-1].strip() if ',' in str(x) else x)
            df['Date'] = pd.to_datetime(df['Date'], format='mixed', errors='coerce', dayfirst=True)
            df['Date'] = df['Date'].ffill().bfill()
        if 'Skill' in df.columns: df['Skill'] = df['Skill'].astype(str).str.strip().ffill().fillna("Reading")
        if 'Time Spent' in df.columns: df['Time Spent'] = pd.to_numeric(df['Time Spent'], errors='coerce').fillna(0)
        if 'Notes' not in df.columns: df['Notes'] = ""
        return df, contents.sha, "success"
    except Exception as e: return None, None, str(e)

def save_to_github(token, repo_name, file_path, df):
    try:
        # AUTO-VALIDATION (chosen idea)
        df_save = df.copy()
        required_cols = ['Date', 'Skill', 'Time Spent', 'Notes']
        for col in required_cols:
            if col not in df_save.columns:
                df_save[col] = "" if col == "Notes" else 0 if col == "Time Spent" else pd.to_datetime("today")
        df_save = df_save[required_cols]
        df_save['Date'] = pd.to_datetime(df_save['Date']).dt.strftime("%Y-%m-%d")
        csv_buffer = io.StringIO()
        df_save.to_csv(csv_buffer, index=False)
        g = get_gh_client(token)
        repo = g.get_repo(repo_name)
        latest_sha = repo.get_contents(file_path).sha
        res = repo.update_file(path=file_path, message="Sync Elite Tracker", content=csv_buffer.getvalue(), sha=latest_sha)
        return res['content'].sha 
    except Exception as e:
        st.error(f"GitHub Sync Error: {e}")
        return None

# --- UI UTILITIES ---
@st.dialog("➕ Log New Study Session")
def log_session_dialog(current_date, available_skills, current_level):
    with st.form("new_entry", clear_on_submit=True):
        st.write("Record your progress:")
        col_d, col_s = st.columns(2)
        d = col_d.date_input("Date", current_date)
        s = col_s.selectbox("Skill", available_skills)
        t = st.number_input("Minutes", 1, 600, 30)
        n = st.text_input("Notes")
        if st.form_submit_button("Log Entry", use_container_width=True):
            new_row = pd.DataFrame({"Date":[pd.to_datetime(d)], "Skill":[s], "Time Spent":[t], "Notes":[n]})
            updated_df = pd.concat([st.session_state.df, new_row], ignore_index=True)
            sha = save_to_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv", updated_df)
            if sha:
                st.session_state.df, st.session_state.file_sha = updated_df, sha
                st.session_state.prev_level = current_level 
                st.rerun()

# --- SIDEBAR ---
with st.sidebar:
    st.header("🔑 Connection")
    st.text_input("GitHub Token", type="password", key="saved_token")
    st.text_input("Repo", key="saved_repo")
    st.text_input("Gemini API Key", type="password", key="gemini_key")
    if st.button("💾 Save Credentials", use_container_width=True):
        save_credentials_to_disk(); st.success("Locked!")
    if st.button("🔄 Force Sync", use_container_width=True):
        load_data_from_github.clear()
        df, sha, status = load_data_from_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv")
        if status == "success": st.session_state.df, st.session_state.file_sha = df, sha; st.success("Synced!")
        else: st.error(status)
    st.divider()
    theme = st.selectbox("Theme", ["Emerald City", "Ocean Deep", "Sunset Orange", "Royal Purple"])
    theme_map = {"Emerald City": "#00CC96", "Ocean Deep": "#0099FF", "Sunset Orange": "#FF5733", "Royal Purple": "#8E44AD"}
    st.session_state.accent_color = theme_map[theme]
    weekly_goal = st.slider("Weekly Goal (Hours)", 1, 40, 5)
    yearly_goal = st.slider("Yearly Goal (Hours)", 50, 1000, 200, step=10)
    st.checkbox("🧘 Zen Mode (full focus)", value=st.session_state.zen_mode, key="zen_mode")
    st.checkbox("🔄 Ask AI Coach Automatically", value=st.session_state.ask_ai_auto, key="ask_ai_auto")  # YOUR EXACT REQUEST
    with st.expander("⚙️ Advanced Settings"):
        st.session_state.custom_skills = st.text_input("Custom Skills", value=st.session_state.custom_skills)
        if st.session_state.df is not None:
            old_sk = st.selectbox("Select Skill to Rename", options=sorted(st.session_state.df['Skill'].unique().tolist()))
            new_sk = st.text_input("Enter New Name")
            if st.button("🚀 Bulk Rename"):
                if new_sk.strip():
                    up_df = st.session_state.df.copy()
                    up_df['Skill'] = up_df['Skill'].replace(old_sk, new_sk.strip())
                    sha = save_to_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv", up_df)
                    if sha: st.session_state.df, st.session_state.file_sha = up_df, sha; st.rerun()

# --- MAIN UI ---
if st.session_state.df is not None:
    df, now = st.session_state.df.copy(), datetime.now()
    all_skills = list(dict.fromkeys(["Listening", "Speaking", "Reading", "Writing", "Grammar", "Vocabulary"] + [s.strip() for s in st.session_state.custom_skills.split(',') if s.strip()] + df['Skill'].unique().tolist()))
    total_hrs = df['Time Spent'].sum() / 60
    level = int(total_hrs // 50) + 1
    xp_progress = (total_hrs % 50) / 50
    streak = cached_get_streak(df)

    if level > st.session_state.prev_level > 0: st.balloons(); st.session_state.prev_level = level
    elif st.session_state.prev_level == 0: st.session_state.prev_level = level

    this_week_min = df[df['Date'] >= (now - timedelta(days=now.weekday()))]['Time Spent'].sum()
    rem_min = max(0, (weekly_goal * 60) - this_week_min)

    c_title, c_btn = st.columns([3, 1])
    with c_title: st.title("🇬🇧 English Pro Elite")
    with c_btn: 
        if st.button("➕ Log Study Time", type="primary", use_container_width=True):
            log_session_dialog(now, all_skills, level)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Level", f"Lvl {level}"); m2.metric("Total", f"{total_hrs:.1f}h"); m3.metric("Streak", f"{streak} Days"); m4.metric("Pacer", f"{rem_min/60:.1f}h left")
    st.progress(xp_progress, text=f"XP to Level {level+1}")

    # AI COACH - YOUR TOGGLE GATES THE AUTO (no longer fires on open)
    if st.session_state.ask_ai_auto and st.session_state.gemini_key and (st.session_state.last_ai_rec == "" or (st.session_state.last_ai_time and (now - st.session_state.last_ai_time).seconds > 3600)):
        st.session_state.last_ai_rec = get_ai_recommendation(st.session_state.gemini_key, df, now)
        st.session_state.last_ai_time = now
    if st.session_state.last_ai_rec:
        st.info(f"**Coach's Corner** 💡\n\n{st.session_state.last_ai_rec}\n\n*Last updated just now*")
        if st.button("🔄 Ask Coach Now"):
            st.session_state.last_ai_rec = get_ai_recommendation(st.session_state.gemini_key, df, now)
            st.session_state.last_ai_time = now
            st.rerun()

    # ZEN MODE (now truly full-screen)
    if st.session_state.zen_mode:
        st.set_page_config(initial_sidebar_state="collapsed", page_title="English Pro Elite - Zen")
        df_sorted = df.sort_values('Date')
        st.plotly_chart(cached_mountain(df_sorted, st.session_state.accent_color), use_container_width=True)
        diet = df.groupby('Skill')['Time Spent'].sum()
        st.plotly_chart(cached_donut(diet, st.session_state.accent_color), use_container_width=True)
    else:
        tab_dash, tab_trophy, tab_history, tab_share = st.tabs(["📈 Dashboard", "🏆 Trophies", "📝 History", "📸 Share Profile"])
        
        with tab_dash:
            c1, c2 = st.columns([2, 1])
            with c1:
                df_sorted = df.sort_values('Date')
                st.plotly_chart(cached_mountain(df_sorted, st.session_state.accent_color), use_container_width=True)
            with c2:
                diet = df.groupby('Skill')['Time Spent'].sum()
                st.plotly_chart(cached_donut(diet, st.session_state.accent_color), use_container_width=True)

        with tab_trophy:
            skill_sums = df.groupby('Skill')['Time Spent'].sum()
            badges = [("Scholar", "10h total", total_hrs >= 10), ("King", "30-day streak", streak >= 30), ("Specialist", "50h in one skill", any(skill_sums >= 3000))]
            cols = st.columns(3)
            for i, (n, d, u) in enumerate(badges):
                if u: cols[i].success(f"🌟 **{n}**\n\n{d}")
                else: cols[i].info(f"🔒 **{n}**\n\n{d}")
            
            # MILESTONE REWARD (persisted + daily reset - chosen idea)
            st.subheader("🎁 Milestone Reward")
            today_str = now.date().isoformat()
            if st.session_state.milestone_claimed_date != today_str:
                claimed = st.checkbox("Claim today's reward", value=False)
                if claimed:
                    st.success(f"🎉 {st.session_state.milestone_reward} unlocked!")
                    st.balloons()
                    st.session_state.milestone_claimed_date = today_str
            else:
                st.success(f"🎉 {st.session_state.milestone_reward} already claimed today!")

        with tab_history:
            edited = st.data_editor(df.sort_values("Date", ascending=False), column_config={"Date": st.column_config.DateColumn(), "Skill": st.column_config.SelectboxColumn(options=all_skills)}, use_container_width=True, hide_index=True)
            if st.button("🗑️ Commit Changes"):
                sha = save_to_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv", edited)
                if sha: st.session_state.df, st.session_state.file_sha = edited, sha; st.rerun()

        with tab_share:
            fav_skill = df.groupby('Skill')['Time Spent'].sum().idxmax() if not df.empty else "N/A"
            archetype_map = {"Reading": "The Sage", "Listening": "The Observer", "Speaking": "The Orator", "Writing": "The Scribe", "Grammar": "The Architect", "Vocabulary": "The Wordsmith"}
            archetype = archetype_map.get(fav_skill, "The Scholar")
            fig_share = go.Figure()
            fig_share.add_shape(type="rect", x0=0, y0=0, x1=1, y1=1, xref="paper", yref="paper", fillcolor="#111111", line_width=0)
            fig_share.add_trace(go.Scatter(x=[0.5], y=[0.55], mode="markers", marker=dict(size=250, color=st.session_state.accent_color, opacity=0.15), hoverinfo="skip"))
            fig_share.add_annotation(text="ENGLISH PRO ELITE", xref="paper", yref="paper", x=0.5, y=0.9, showarrow=False, font=dict(size=16, color="#AAAAAA"))
            fig_share.add_annotation(text=f'<i>"{archetype}"</i>', xref="paper", yref="paper", x=0.5, y=0.75, showarrow=False, font=dict(size=32, color=st.session_state.accent_color, family="serif"))
            fig_share.add_annotation(text=f"<b>LEVEL {level}</b>", xref="paper", yref="paper", x=0.5, y=0.55, showarrow=False, font=dict(size=64, color="#FFFFFF"))
            fig_share.add_annotation(text=f"<b>{total_hrs:.1f}</b> HOURS STUDIED", xref="paper", yref="paper", x=0.5, y=0.35, showarrow=False, font=dict(size=18, color="#FFFFFF"))
            fig_share.add_annotation(text=f"<b>{streak}</b> DAY STREAK 🔥", xref="paper", yref="paper", x=0.5, y=0.25, showarrow=False, font=dict(size=18, color="#FFFFFF"))
            fig_share.add_shape(type="rect", x0=0.15, y0=0.1, x1=0.85, y1=0.12, xref="paper", yref="paper", fillcolor="#333333", line_width=0)
            fig_share.add_shape(type="rect", x0=0.15, y0=0.1, x1=0.15 + (0.7 * xp_progress), y1=0.12, xref="paper", yref="paper", fillcolor=st.session_state.accent_color, line_width=0)
            fig_share.update_layout(xaxis=dict(visible=False, range=[0,1]), yaxis=dict(visible=False, range=[0,1]), plot_bgcolor="#111111", paper_bgcolor="#111111", margin=dict(l=10, r=10, t=10, b=10), height=450, showlegend=False)
            st.plotly_chart(fig_share, use_container_width=True, config={'displayModeBar': False})
            
            # ONE-CLICK EXPORT (chosen idea)
            col_exp1, col_exp2 = st.columns(2)
            with col_exp1:
                if st.button("📥 Download Certificate PNG", use_container_width=True):
                    fig_share.write_image("certificate.png")
                    with open("certificate.png", "rb") as f:
                        st.download_button("Click to save PNG", f, file_name="english_pro_elite_certificate.png", mime="image/png")
            with col_exp2:
                if st.button("📥 Download Raw CSV", use_container_width=True):
                    csv = df.to_csv(index=False)
                    st.download_button("Click to save CSV", csv, file_name="study_data.csv", mime="text/csv")

else: 
    st.info("👈 Enter Connection info in sidebar to begin.")