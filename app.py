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

# --- CONFIGURATION & SESSION STATE ---
st.set_page_config(page_title="English Pro Elite", layout="wide", page_icon="🇬🇧")

# Persistent Credential Loader
CRED_FILE = "credentials.json"
def load_credentials():
    if os.path.exists(CRED_FILE):
        try:
            with open(CRED_FILE, "r") as f:
                return json.load(f)
        except: return {}
    return {}

def save_credentials_to_disk():
    creds = {
        "saved_token": st.session_state.saved_token,
        "saved_repo": st.session_state.saved_repo,
        "gemini_key": st.session_state.gemini_key
    }
    with open(CRED_FILE, "w") as f:
        json.dump(creds, f)

local_creds = load_credentials()

# Initialize Session States
for key in ['df', 'file_sha', 'prev_level', 'saved_token', 'saved_repo', 'accent_color', 'zen_mode', 'milestone_reward', 'gemini_key', 'custom_skills', 'last_ai_rec']:
    if key not in st.session_state:
        st.session_state[key] = None if key not in ['prev_level'] else 0
        if key == 'accent_color': st.session_state[key] = "#00CC96"
        if key == 'zen_mode': st.session_state[key] = False
        if key == 'milestone_reward': st.session_state[key] = "Treat myself to coffee"
        if key == 'custom_skills': st.session_state[key] = ""
        if key == 'last_ai_rec': st.session_state[key] = ""
        
        if key in ['saved_token', 'saved_repo', 'gemini_key']:
            st.session_state[key] = local_creds.get(key, "")

# --- AI COACH LOGIC (GEMINI) ---
def get_ai_recommendation(api_key, dataframe, current_date):
    if not api_key: return "Please provide a Gemini API key in the sidebar."
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash-lite')
        
        all_time_summary = dataframe.groupby('Skill')['Time Spent'].sum().to_dict()
        last_7_days_df = dataframe[dataframe['Date'].dt.date >= (current_date.date() - timedelta(days=7))]
        recent_summary = last_7_days_df.groupby('Skill')['Time Spent'].sum().to_dict()
        
        prompt = f"""
        Act as an expert English Study Coach. Here is my study data:
        - All-Time Totals (Minutes): {all_time_summary}
        - Last 7 Days (Minutes): {recent_summary}
        
        Based on my recent habits vs my all-time strengths, identify what I need to focus on right now. 
        Suggest a specific 30-minute activity I should do today to improve. Keep it under 100 words.
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

def save_to_github(token, repo_name, file_path, df):
    try:
        g = get_gh_client(token)
        repo = g.get_repo(repo_name)
        latest_contents = repo.get_contents(file_path)
        latest_sha = latest_contents.sha
        
        df_save = df.copy()
        df_save['Date'] = pd.to_datetime(df_save['Date']).dt.strftime("%Y-%m-%d")
        csv_buffer = io.StringIO()
        df_save.to_csv(csv_buffer, index=False)
        
        res = repo.update_file(
            path=file_path, 
            message="Sync Elite Tracker Update", 
            content=csv_buffer.getvalue(), 
            sha=latest_sha
        )
        return res['content'].sha 
    except Exception as e:
        st.error(f"GitHub Sync Error: {e}")
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

@st.dialog("➕ Log New Study Session")
def log_session_dialog(current_date, available_skills, current_level):
    with st.form("new_entry", clear_on_submit=True):
        st.write("Record your progress below:")
        col_d, col_s = st.columns(2)
        d = col_d.date_input("Date", current_date)
        s = col_s.selectbox("Skill", available_skills)
        t = st.number_input("Minutes Spent", 1, 600, 30)
        n = st.text_input("Session Notes (Optional)")
        
        if st.form_submit_button("Log Entry", use_container_width=True):
            new_row = pd.DataFrame({"Date":[pd.to_datetime(d)], "Skill":[s], "Time Spent":[t], "Notes":[n]})
            updated_df = pd.concat([st.session_state.df, new_row], ignore_index=True)
            
            new_sha = save_to_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv", updated_df)
            if new_sha:
                st.session_state.df = updated_df
                st.session_state.file_sha = new_sha
                st.session_state.prev_level = current_level 
                st.rerun()

# --- SIDEBAR ---
with st.sidebar:
    st.header("🔑 Connection")
    st.text_input("GitHub Token", type="password", key="saved_token")
    st.text_input("Repo", key="saved_repo")
    st.text_input("Gemini API Key", type="password", key="gemini_key")
    
    if st.button("💾 Save Credentials", use_container_width=True):
        save_credentials_to_disk()
        st.success("Credentials locked persistently!")
    
    if st.button("🔄 Force Sync", use_container_width=True):
        load_data_from_github.clear()
        df, sha, status = load_data_from_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv")
        if status == "success":
            st.session_state.df, st.session_state.file_sha = df, sha
            st.success("Synced!")
        else: st.error(status)
                
    st.divider()
    
    can_undo = st.session_state.df is not None and len(st.session_state.df) > 1
    if st.button("↩️ Undo Last Log", use_container_width=True, disabled=not can_undo):
        undo_df = st.session_state.df.iloc[:-1]
        new_sha = save_to_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv", undo_df)
        if new_sha:
            st.session_state.df = undo_df
            st.session_state.file_sha = new_sha
            st.toast("Reverted last log!")
            st.rerun()

    if st.session_state.df is not None:
        st.header("🤖 AI Study Coach")
        if st.button("Ask Coach"):
            with st.spinner("Analyzing history..."):
                now = datetime.now()
                st.session_state.last_ai_rec = get_ai_recommendation(st.session_state.gemini_key, st.session_state.df, now)
        if st.session_state.last_ai_rec:
            st.info(st.session_state.last_ai_rec)

    st.divider()
    st.session_state.zen_mode = st.toggle("🧘 Zen Mode", value=st.session_state.zen_mode)
    
    theme = st.selectbox("Theme", ["Emerald City", "Ocean Deep", "Sunset Orange", "Royal Purple"])
    theme_map = {"Emerald City": "#00CC96", "Ocean Deep": "#0099FF", "Sunset Orange": "#FF5733", "Royal Purple": "#8E44AD"}
    st.session_state.accent_color = theme_map[theme]
    
    weekly_goal = st.slider("Weekly Goal (Hours)", 1, 40, 5)
    yearly_goal = st.slider("Yearly Goal (Hours)", 50, 1000, 200, step=10)

    with st.expander("⚙️ Advanced Settings"):
        st.session_state.custom_skills = st.text_input("Custom Skills (comma separated)", value=st.session_state.custom_skills)
        
        if st.session_state.df is not None:
            st.divider()
            st.markdown("🛠️ **Skill Renaming Tool**")
            current_skills = sorted(st.session_state.df['Skill'].unique().tolist())
            old_skill = st.selectbox("Select Skill to Rename", options=current_skills)
            new_skill_name = st.text_input("Enter New Name", placeholder="e.g., Reading Analysis")
            
            if st.button("🚀 Bulk Rename & Sync", use_container_width=True):
                if new_skill_name.strip():
                    with st.spinner("Refactoring data..."):
                        updated_df = st.session_state.df.copy()
                        updated_df['Skill'] = updated_df['Skill'].replace(old_skill, new_skill_name.strip())
                        
                        success_sha = save_to_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv", updated_df)
                        if success_sha:
                            st.session_state.df = updated_df
                            st.session_state.file_sha = success_sha
                            st.success(f"Renamed '{old_skill}' to '{new_skill_name}'!")
                            st.rerun()
                else:
                    st.warning("Please enter a valid new name.")

# --- MAIN UI ---
if st.session_state.df is not None:
    df = st.session_state.df.copy()
    now = datetime.now()
    
    base_skills = ["Listening", "Speaking", "Reading", "Writing", "Grammar", "Vocabulary"]
    extra_skills = [s.strip() for s in st.session_state.custom_skills.split(',') if s.strip()]
    historical_skills = df['Skill'].dropna().unique().tolist()
    all_skills = list(dict.fromkeys(base_skills + extra_skills + historical_skills))
    
    total_hrs = df['Time Spent'].sum() / 60
    level = int(total_hrs // 50) + 1
    xp_progress = (total_hrs % 50) / 50
    streak = get_streak(df)

    if level > st.session_state.prev_level and st.session_state.prev_level != 0:
        st.balloons()
        st.session_state.prev_level = level
    elif st.session_state.prev_level == 0:
        st.session_state.prev_level = level

    this_week_min = df[df['Date'] >= (now - timedelta(days=now.weekday()))]['Time Spent'].sum()
    remaining_min = max(0, (weekly_goal * 60) - this_week_min)
    days_left = 7 - now.weekday()
    pace = remaining_min / days_left if days_left > 0 else remaining_min

    c_title, c_btn = st.columns([3, 1])
    with c_title:
        st.title("🇬🇧 English Pro Elite")
    with c_btn:
        st.write("") 
        if st.button("➕ Log Study Time", type="primary", use_container_width=True):
            log_session_dialog(now, all_skills, level)

    with st.expander(f"🎁 Level Reward: {st.session_state.milestone_reward}", expanded=False):
        st.session_state.milestone_reward = st.text_input("Reward", value=st.session_state.milestone_reward)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Level", f"Lvl {level}")
    m2.metric("Total", f"{total_hrs:.1f}h")
    m3.metric("Streak", f"{streak} Days")
    m4.metric("Pacer", f"{remaining_min/60:.1f}h left", f"{pace:.0f}m / day")
    st.progress(xp_progress, text=f"XP to Level {level+1}")

    if not st.session_state.zen_mode:
        st.divider()
        tab_dash, tab_insights, tab_trophy, tab_history, tab_share = st.tabs(["📈 Dashboard", "🧠 Deep Insights", "🏆 Trophies", "📝 History", "📸 Share Profile"])

        with tab_dash:
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
                fig_mtn = px.area(df_sorted, x='Date', y='Cumulative_Hrs', title="Learning Mountain", color_discrete_sequence=[st.session_state.accent_color])
                
                start_of_year = pd.to_datetime(f"{now.year}-01-01")
                end_of_year = pd.to_datetime(f"{now.year}-12-31")
                cum_last_year = df[df['Date'].dt.year < now.year]['Time Spent'].sum() / 60
                fig_mtn.add_trace(go.Scatter(
                    x=[start_of_year, end_of_year], 
                    y=[cum_last_year, cum_last_year + yearly_goal], 
                    mode='lines', line=dict(color='gray', dash='dash'), name=f'{now.year} Pace Goal'
                ))
                st.plotly_chart(fig_mtn, use_container_width=True)
                
            with c2:
                st.subheader("Skill Diet")
                if not df.empty:
                    diet_data = df.groupby('Skill')['Time Spent'].sum()
                    fig_donut = px.pie(names=diet_data.index, values=diet_data.values, hole=0.5, color_discrete_sequence=px.colors.qualitative.Pastel)
                    fig_donut.update_traces(textinfo='label+percent', textposition='inside')
                    fig_donut.update_layout(showlegend=False, height=250, margin=dict(l=20,r=20,t=20,b=20))
                    st.plotly_chart(fig_donut, use_container_width=True)

                    radar_data = diet_data.reindex(all_skills).fillna(0)
                    fig_radar = go.Figure(data=go.Scatterpolar(r=radar_data.values, theta=all_skills, fill='toself', line_color=st.session_state.accent_color))
                    fig_radar.update_layout(polar=dict(radialaxis=dict(visible=False)), showlegend=False, height=250)
                    st.plotly_chart(fig_radar, use_container_width=True)
                    
                    st.markdown("##### ⚔️ RPG Skill Mastery (1 Lvl = 10h)")
                    skill_levels = (diet_data / 600).astype(int) + 1 
                    sk_cols = st.columns(3)
                    for idx, (skill, sk_lvl) in enumerate(skill_levels.items()):
                        sk_cols[idx % 3].metric(skill, f"Lvl {sk_lvl}")

        with tab_insights:
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
            st.subheader("🏆 Dynamic Trophy Room")
            skill_sums_min = df.groupby('Skill')['Time Spent'].sum()
            has_specialist = any(skill_sums_min >= 3000) 
            has_generalist = sum([1 for s in base_skills if skill_sums_min.get(s, 0) >= 600]) == len(base_skills) 
            has_weekend = any(df['Date'].dt.dayofweek >= 5) 
            
            badges = [
                ("First Step", "Log your 1st session", total_hrs > 0), 
                ("Novice Scholar", "Reach 10h total", total_hrs >= 10), 
                ("Dedication", "Reach 100h total", total_hrs >= 100),
                ("Halfway There", "Reach Level 5", level >= 5),
                ("Master Scholar", "Reach Level 10", level >= 10),
                ("Streak Initiate", "Hit a 7-day streak", streak >= 7),
                ("Streak Master", "Hit a 30-day streak", streak >= 30),
                ("Weekend Warrior", "Log a session on a weekend", has_weekend),
                ("The Specialist", "Spend 50 hours on a single skill", has_specialist),
                ("The Generalist", "Spend 10 hours on every core skill", has_generalist)
            ]
            
            cols = st.columns(3)
            for i, (name, desc, unlocked) in enumerate(badges):
                if unlocked: 
                    cols[i % 3].success(f"🌟 **{name}**\n\n{desc}")
                else: 
                    cols[i % 3].info(f"🔒 **{name}**\n\n{desc}")

        with tab_history:
            col_title, col_btn = st.columns([3, 1])
            col_title.subheader("📝 Session History")
            if col_btn.button("🧹 Merge Duplicate Days"):
                with st.spinner("Merging..."):
                    merge_df = df.copy()
                    merge_df['Date_Str'] = merge_df['Date'].dt.strftime('%Y-%m-%d')
                    grouped = merge_df.groupby(['Date_Str', 'Skill']).agg({
                        'Time Spent': 'sum',
                        'Notes': lambda x: ' | '.join(set([str(i) for i in x if str(i).strip()]))
                    }).reset_index()
                    grouped['Date'] = pd.to_datetime(grouped['Date_Str'])
                    grouped = grouped.drop(columns=['Date_Str']).sort_values('Date', ascending=False)
                    new_sha = save_to_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv", grouped)
                    if new_sha:
                        st.session_state.df = grouped
                        st.session_state.file_sha = new_sha
                        st.success("Duplicates Merged!")
                        st.rerun()

            display_df = df.copy().sort_values("Date", ascending=False)
            display_df['Delete'] = False
            
            edited_hist = st.data_editor(
                display_df[['Delete', 'Date', 'Skill', 'Time Spent', 'Notes']],
                column_config={
                    "Date": st.column_config.DateColumn("Date", required=True),
                    "Skill": st.column_config.SelectboxColumn("Skill", options=all_skills, required=True),
                    "Time Spent": st.column_config.NumberColumn("Min", min_value=1),
                    "Delete": st.column_config.CheckboxColumn("🗑️")
                },
                use_container_width=True,
                hide_index=True
            )
            
            if st.button("🗑️ Commit Changes", type="primary"):
                filtered_save = edited_hist[edited_hist['Delete'] == False].drop(columns=['Delete'])
                new_sha = save_to_github(st.session_state.saved_token, st.session_state.saved_repo, "data.csv", filtered_save)
                if new_sha: 
                    st.session_state.df = filtered_save
                    st.rerun()

        with tab_share:
            c1, c2 = st.columns([1, 1])
            with c1:
                st.subheader("📸 Your Share Card")
                
                # --- NEW DARK GLASS SHARE CARD ---
                fav_skill = df.groupby('Skill')['Time Spent'].sum().idxmax() if not df.empty else "N/A"
                archetype_map = {
                    "Reading": "The Sage", "Listening": "The Observer", 
                    "Speaking": "The Orator", "Writing": "The Scribe",
                    "Grammar": "The Architect", "Vocabulary": "The Wordsmith"
                }
                archetype = archetype_map.get(fav_skill, "The Scholar")
                
                fig_share = go.Figure()
                
                # Dark Glass Background
                fig_share.add_shape(type="rect", x0=0, y0=0, x1=1, y1=1, xref="paper", yref="paper", fillcolor="#111111", line_width=0)
                
                # Subtle Center Glow (using accent color)
                fig_share.add_trace(go.Scatter(x=[0.5], y=[0.55], mode="markers", 
                                             marker=dict(size=250, color=st.session_state.accent_color, opacity=0.15), 
                                             hoverinfo="skip"))
                
                # Typography Layer using safe HTML tags for styling
                fig_share.add_annotation(text="ENGLISH PRO ELITE", xref="paper", yref="paper", x=0.5, y=0.9, showarrow=False, 
                                         font=dict(size=16, color="#AAAAAA"))
                
                fig_share.add_annotation(text=f'<i>"{archetype}"</i>', xref="paper", yref="paper", x=0.5, y=0.75, showarrow=False, 
                                         font=dict(size=32, color=st.session_state.accent_color, family="serif"))
                
                fig_share.add_annotation(text=f"<b>LEVEL {level}</b>", xref="paper", yref="paper", x=0.5, y=0.55, showarrow=False, 
                                         font=dict(size=64, color="#FFFFFF"))
                
                fig_share.add_annotation(text=f"<b>{total_hrs:.1f}</b> HOURS STUDIED", xref="paper", yref="paper", x=0.5, y=0.35, showarrow=False, 
                                         font=dict(size=18, color="#FFFFFF"))
                fig_share.add_annotation(text=f"<b>{streak}</b> DAY STREAK 🔥", xref="paper", yref="paper", x=0.5, y=0.25, showarrow=False, 
                                         font=dict(size=18, color="#FFFFFF"))
                
                # XP Bar Background & Fill
                fig_share.add_shape(type="rect", x0=0.15, y0=0.1, x1=0.85, y1=0.12, xref="paper", yref="paper", fillcolor="#333333", line_width=0)
                fig_share.add_shape(type="rect", x0=0.15, y0=0.1, x1=0.15 + (0.7 * xp_progress), y1=0.12, xref="paper", yref="paper", fillcolor=st.session_state.accent_color, line_width=0)

                # Layout Cleanup
                fig_share.update_layout(xaxis=dict(visible=False, range=[0,1]), yaxis=dict(visible=False, range=[0,1]), 
                                      plot_bgcolor="#111111", paper_bgcolor="#111111",
                                      margin=dict(l=10, r=10, t=10, b=10), height=450, showlegend=False)
                
                st.plotly_chart(fig_share, use_container_width=True, config={'displayModeBar': False})
                st.caption("Right-click the image above and select 'Save Image As' to share!")

            with c2:
                st.subheader(f"🎧 Your {now.year} Wrapped")
                if st.button("✨ Reveal My Wrapped ✨", use_container_width=True):
                    st.balloons()
                    df_year = df[df['Date'].dt.year == now.year]
                    if df_year.empty:
                        st.warning(f"No data logged yet for {now.year}!")
                    else:
                        tot_min = df_year['Time Spent'].sum()
                        top_month = df_year['Date'].dt.month_name().mode()[0]
                        active_days = df_year['Date'].nunique()
                        best_skill = df_year.groupby('Skill')['Time Spent'].sum().idxmax()
                        st.success(f"### 🎉 The {now.year} Wrap-Up\n> *\"Consistency is the key to mastery.\"*\n* ⏳ **Time Invested:** You spent **{tot_min:,.0f} minutes** ({tot_min/60:.1f} hours) learning English!\n* 🏆 **The Obsession:** Your most practiced skill was **{best_skill}**.\n* 📅 **The Prime Time:** Your busiest study month was **{top_month}**.\n* 🔥 **The Grind:** You showed up and studied on **{active_days} different days**.\n\n**You are crushing it. Bring on {now.year + 1}!** 🚀")

else:
    st.info("👈 Enter Connection info in sidebar to begin.")
