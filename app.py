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
import requests
import pytz
from typing import Dict, Any, Optional, Tuple

# --- ENHANCED CONFIGURATION & SESSION STATE MANAGEMENT ---
st.set_page_config(
    page_title="English Pro Elite",
    layout="wide",
    page_icon="🇬🇧",
    initial_sidebar_state="collapsed"  # Better for mobile
)

# --- STRUCTURED SESSION STATE INITIALIZATION ---
def initialize_session_state():
    """Centralized session state initialization with proper typing"""
    session_defaults = {
        'df': None,
        'file_sha': None,
        'prev_level': 0,
        'saved_token': "",
        'saved_repo': "",
        'accent_color': "#00CC96",
        'zen_mode': False,
        'milestone_reward': "Treat myself to coffee",
        'gemini_key': "",
        'custom_skills': "",
        'last_ai_rec': "",
        'offline_mode': False,
        'pending_changes': [],
        'last_sync_time': None,
        'connection_status': {'github': 'untested', 'gemini': 'untested'},
        'mobile_view': False,
        'data_backup': None
    }
    
    # Load saved credentials first
    CRED_FILE = "credentials.json"
    local_creds = {}
    if os.path.exists(CRED_FILE):
        try:
            with open(CRED_FILE, "r") as f:
                local_creds = json.load(f)
        except Exception as e:
            st.error(f"Credential load error: {str(e)}")
    
    # Initialize session states
    for key, default_value in session_defaults.items():
        if key not in st.session_state:
            # Use saved credentials if available
            if key in ['saved_token', 'saved_repo', 'gemini_key']:
                st.session_state[key] = local_creds.get(key, default_value)
            else:
                st.session_state[key] = default_value
    
    # Check for mobile device
    user_agent = st.query_params.get("user_agent", "")
    if any(device in user_agent.lower() for device in ['mobile', 'iphone', 'android']):
        st.session_state.mobile_view = True

# Initialize session state
initialize_session_state()

# --- ENHANCED ERROR HANDLING DECORATOR ---
def handle_api_errors(func):
    """Decorator for comprehensive error handling in API calls"""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except requests.exceptions.ConnectionError as e:
            st.session_state.connection_status['github'] = 'offline'
            st.session_state.offline_mode = True
            raise Exception(f"Connection error: Please check your internet connection. {str(e)}")
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            # Log error for debugging
            if 'error_log' not in st.session_state:
                st.session_state.error_log = []
            st.session_state.error_log.append({
                'timestamp': datetime.now().isoformat(),
                'function': func.__name__,
                'error_type': error_type,
                'error_msg': error_msg
            })
            raise Exception(f"{error_type} in {func.__name__}: {error_msg}")
    return wrapper

# --- CONNECTION HEALTH CHECK ---
@st.cache_data(ttl=60, show_spinner=False)
@handle_api_errors
def test_github_connection(token: str) -> Tuple[bool, str]:
    """Test GitHub connection with detailed feedback"""
    if not token:
        return False, "No token provided"
    
    try:
        g = Github(token)
        # Try to get authenticated user
        user = g.get_user()
        return True, f"Connected as {user.login}"
    except Exception as e:
        error_msg = str(e)
        if "Bad credentials" in error_msg:
            return False, "Invalid token"
        elif "rate limit" in error_msg.lower():
            return False, "Rate limit exceeded"
        else:
            return False, f"Connection failed: {error_msg}"

@st.cache_data(ttl=60, show_spinner=False)
@handle_api_errors
def test_gemini_connection(api_key: str) -> Tuple[bool, str]:
    """Test Gemini API connection"""
    if not api_key:
        return False, "No API key provided"
    
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash-lite')
        # Simple test prompt
        response = model.generate_content("Test connection", safety_settings={
            'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE',
            'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE',
            'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE',
            'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE'
        })
        return True, "Connection successful"
    except Exception as e:
        error_msg = str(e)
        if "API_KEY_INVALID" in error_msg:
            return False, "Invalid API key"
        elif "quota" in error_msg.lower():
            return False, "API quota exceeded"
        else:
            return False, f"Connection failed: {error_msg}"

# --- OFFLINE DATA MANAGEMENT ---
def save_local_backup(df: pd.DataFrame) -> None:
    """Save data locally for offline mode"""
    backup_file = "elite_tracker_backup.json"
    try:
        backup_data = {
            'timestamp': datetime.now().isoformat(),
            'data': df.to_dict('records'),
            'schema': list(df.columns)
        }
        with open(backup_file, 'w') as f:
            json.dump(backup_data, f)
        st.session_state.data_backup = backup_data
    except Exception as e:
        st.error(f"Backup failed: {str(e)}")

def load_local_backup() -> Optional[pd.DataFrame]:
    """Load data from local backup"""
    backup_file = "elite_tracker_backup.json"
    if os.path.exists(backup_file):
        try:
            with open(backup_file, 'r') as f:
                backup_data = json.load(f)
            df = pd.DataFrame(backup_data['data'])
            # Ensure proper column types
            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'])
            if 'Time Spent' in df.columns:
                df['Time Spent'] = pd.to_numeric(df['Time Spent'], errors='coerce')
            st.session_state.data_backup = backup_data
            return df
        except Exception as e:
            st.error(f"Backup load failed: {str(e)}")
    return None

def sync_pending_changes(token: str, repo_name: str, file_path: str) -> bool:
    """Sync any pending changes from offline mode"""
    if not st.session_state.pending_changes:
        return True
    
    try:
        df = st.session_state.df.copy()
        for change in st.session_state.pending_changes:
            if change['type'] == 'add':
                new_row = pd.DataFrame([change['data']])
                df = pd.concat([df, new_row], ignore_index=True)
        
        sha = save_to_github(token, repo_name, file_path, df)
        if sha:
            st.session_state.df = df
            st.session_state.file_sha = sha
            st.session_state.pending_changes = []
            st.session_state.last_sync_time = datetime.now()
            return True
    except Exception as e:
        st.error(f"Sync failed: {str(e)}")
    
    return False

# --- MOBILE OPTIMIZATION UTILITIES ---
def responsive_columns(mobile_cols: int = 1, desktop_cols: int = 4) -> list:
    """Create responsive column layout based on device"""
    if st.session_state.mobile_view:
        return st.columns(mobile_cols)
    return st.columns(desktop_cols)

def mobile_friendly_metric(label: str, value: str, help_text: str = "") -> None:
    """Display metric optimized for mobile"""
    if st.session_state.mobile_view:
        st.metric(label=label, value=value, help=help_text, label_visibility="visible")
    else:
        st.metric(label=label, value=value, help=help_text)

# --- BACKGROUND IMAGE HELPER ---
def get_base64_of_bin_file(bin_file):
    with open(bin_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()

def set_background(png_file):
    if os.path.exists(png_file):
        bin_str = get_base64_of_bin_file(png_file)
        page_bg_img = f'''
        <style>
        .stApp {{
            background-image: url("data:image/png;base64,{bin_str}");
            background-size: cover;
            background-attachment: fixed;
        }}
        
        /* Glassmorphism Effect for Containers */
        [data-testid="stSidebar"] {{
            background-color: rgba(0, 0, 0, 0.7) !important;
            backdrop-filter: blur(10px);
        }}
        
        .stTabs [data-baseweb="tab-panel"] {{
            background-color: rgba(20, 20, 20, 0.6) !important;
            padding: {'10px' if st.session_state.mobile_view else '20px'};
            border-radius: 15px;
            backdrop-filter: blur(5px);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }}

        [data-testid="stMetricValue"] {{
            color: white !important;
            font-size: {'1.5rem' if st.session_state.mobile_view else '2rem'} !important;
        }}
        
        h1, h2, h3, h4, p, span {{
            color: white !important;
        }}

        .stMarkdown div p {{
            color: white !important;
        }}
        
        /* Fix visibility for info boxes */
        .stAlert {{
            background-color: rgba(0, 0, 0, 0.4) !important;
            color: white !important;
            border: 1px solid rgba(255, 255, 255, 0.2) !important;
        }}
        
        /* Mobile optimizations */
        @media screen and (max-width: 768px) {{
            .stTabs [data-baseweb="tab-list"] {{
                flex-wrap: wrap !important;
            }}
            .stTabs [data-baseweb="tab"] {{
                padding: 8px 12px !important;
                font-size: 0.9rem !important;
            }}
            .stDataFrame {{
                font-size: 0.9rem !important;
            }}
        }}
        </style>
        '''
        st.markdown(page_bg_img, unsafe_allow_html=True)

# Apply the background
set_background('background.jpg')

# --- ENHANCED CREDENTIAL MANAGEMENT ---
CRED_FILE = "credentials.json"
def load_credentials():
    if os.path.exists(CRED_FILE):
        try:
            with open(CRED_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            st.error(f"Credential load error: {str(e)}")
            return {}
    return {}

def save_credentials_to_disk():
    try:
        creds = {
            "saved_token": st.session_state.saved_token,
            "saved_repo": st.session_state.saved_repo,
            "gemini_key": st.session_state.gemini_key
        }
        with open(CRED_FILE, "w") as f:
            json.dump(creds, f)
        return True
    except Exception as e:
        st.error(f"Credential save error: {str(e)}")
        return False

# --- ENHANCED AI COACH LOGIC WITH ERROR HANDLING ---
@handle_api_errors
def get_ai_recommendation(api_key: str, dataframe: pd.DataFrame, current_date: datetime) -> str:
    """Enhanced AI recommendation with better error handling"""
    if not api_key:
        return "Please provide a Gemini API key in the sidebar."
    
    # Test connection first
    connection_ok, message = test_gemini_connection(api_key)
    if not connection_ok:
        st.session_state.offline_mode = True
        return f"AI Coach offline: {message}. Using cached recommendation if available."
    
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash-lite')
        
        # Prepare data summaries
        all_time_summary = dataframe.groupby('Skill')['Time Spent'].sum().to_dict()
        last_7_days_df = dataframe[dataframe['Date'].dt.date >= (current_date.date() - timedelta(days=7))]
        recent_summary = last_7_days_df.groupby('Skill')['Time Spent'].sum().to_dict()
        
        # Enhanced prompt for better recommendations
        prompt = f"""Act as an expert English Study Coach. Analyze this study data:
        
        Total Study Time by Skill: {all_time_summary}
        Last 7 Days by Skill: {recent_summary}
        
        Provide specific, actionable recommendations focusing on:
        1. Which skill is being neglected and needs more attention
        2. Which skill is a strength that could be leveraged
        3. One specific exercise or activity to try today
        4. Estimated time needed to reach next level
        
        Keep response under 150 words, friendly and encouraging."""
        
        response = model.generate_content(
            prompt,
            safety_settings={
                'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE',
                'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE',
                'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE',
                'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE'
            }
        )
        
        recommendation = response.text
        st.session_state.last_ai_rec = recommendation
        return recommendation
        
    except Exception as e:
        error_msg = f"AI Error: {str(e)}"
        # Use cached recommendation if available
        if st.session_state.last_ai_rec:
            return f"{error_msg}\n\nUsing previous recommendation:\n\n{st.session_state.last_ai_rec}"
        return error_msg

# --- ENHANCED GITHUB HELPER FUNCTIONS ---
@st.cache_resource(show_spinner=False)
@handle_api_errors
def get_gh_client(token: str):
    return Github(token)

@st.cache_data(ttl=300, show_spinner=False)
@handle_api_errors
def load_data_from_github(_token: str, repo_name: str, file_path: str) -> Tuple[Optional[pd.DataFrame], Optional[str], str]:
    """Enhanced data loading with offline fallback"""
    try:
        # Test connection first
        connection_ok, message = test_github_connection(_token)
        if not connection_ok:
            st.session_state.connection_status['github'] = 'offline'
            st.session_state.offline_mode = True
            # Try to load from local backup
            local_df = load_local_backup()
            if local_df is not None:
                return local_df, "local_backup", "offline_mode"
            return None, None, f"Connection failed: {message}"
        
        # Proceed with GitHub load
        g = get_gh_client(_token)
        repo = g.get_repo(repo_name)
        contents = repo.get_contents(file_path)
        decoded_string = contents.decoded_content.decode('utf-8')
        df = pd.read_csv(io.StringIO(decoded_string))
        
        # Data cleaning and validation
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
        
        if 'Notes' not in df.columns:
            df['Notes'] = ""
        
        # Create local backup
        save_local_backup(df)
        st.session_state.connection_status['github'] = 'online'
        st.session_state.offline_mode = False
        
        return df, contents.sha, "success"
        
    except Exception as e:
        error_msg = str(e)
        # Try offline fallback
        local_df = load_local_backup()
        if local_df is not None:
            st.session_state.offline_mode = True
            return local_df, "local_backup", f"offline_fallback: {error_msg}"
        return None, None, f"Data load error: {error_msg}"

@handle_api_errors
def save_to_github(token: str, repo_name: str, file_path: str, df: pd.DataFrame) -> Optional[str]:
    """Save data to GitHub with enhanced error handling"""
    try:
        # Test connection first
        connection_ok, message = test_github_connection(token)
        if not connection_ok:
            st.session_state
