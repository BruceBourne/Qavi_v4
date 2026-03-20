import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st

def inject_styles():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,600;0,700;1,400;1,600;1,700&family=Playfair+Display:ital,wght@0,400;0,600;0,700;1,400;1,600&family=Inter:wght@300;400;500;600&display=swap');

    :root {
        --bg: #08090C;
        --bg2: #0F1117;
        --surface: #161B27;
        --surface2: #1E2535;
        --border: #252D40;
        --border2: #2E3850;
        --text: #F0F4FF;
        --text2: #8892AA;
        --text3: #4E5A70;
        --accent: #4F7EFF;
        --accent-glow: rgba(79,126,255,0.15);
        --green: #2ECC7A;
        --red: #FF5A5A;
        --gold: #F5B731;
        --radius: 14px;
        --radius-sm: 8px;
    }

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif !important;
        background: var(--bg) !important;
        color: var(--text) !important;
    }

    .stApp { background: var(--bg) !important; }
    .block-container { padding: 1.2rem 2rem 4rem !important; max-width: 1380px; }

    /* Typography */
    h1,h2,h3 { font-family: 'Playfair Display', serif !important; letter-spacing: -0.02em; }

    /* Buttons */
    .stButton > button {
        background: var(--surface) !important;
        color: var(--text) !important;
        border: 1px solid var(--border) !important;
        border-radius: var(--radius-sm) !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 0.84rem !important;
        font-weight: 500 !important;
        padding: 0.42rem 0.9rem !important;
        transition: all 0.18s ease !important;
        letter-spacing: 0.01em;
    }
    .stButton > button:hover {
        background: var(--accent) !important;
        border-color: var(--accent) !important;
        color: white !important;
        transform: translateY(-1px);
        box-shadow: 0 4px 20px var(--accent-glow) !important;
    }

    /* Inputs */
    .stTextInput > div > div > input,
    .stSelectbox > div > div,
    .stNumberInput > div > div > input,
    .stTextArea > div > div > textarea,
    .stDateInput > div > div > input {
        background: var(--surface) !important;
        color: var(--text) !important;
        border: 1px solid var(--border) !important;
        border-radius: var(--radius-sm) !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 0.88rem !important;
    }
    .stTextInput > div > div > input:focus,
    .stTextArea > div > div > textarea:focus {
        border-color: var(--accent) !important;
        box-shadow: 0 0 0 3px var(--accent-glow) !important;
        outline: none !important;
    }

    /* Metrics */
    div[data-testid="metric-container"] {
        background: var(--surface) !important;
        border: 1px solid var(--border) !important;
        border-radius: var(--radius) !important;
        padding: 1rem 1.1rem !important;
        transition: border-color 0.2s;
    }
    div[data-testid="metric-container"]:hover { border-color: var(--accent) !important; }
    div[data-testid="metric-container"] label { color: var(--text2) !important; font-size: 0.75rem !important; }
    div[data-testid="metric-container"] [data-testid="metric-value"] { color: var(--text) !important; font-weight: 600 !important; }

    /* Tabs */
    .stTab [data-baseweb="tab"] { font-family: 'Inter', sans-serif !important; font-weight: 500 !important; color: var(--text2) !important; font-size: 0.84rem !important; }
    .stTab [aria-selected="true"] { color: var(--accent) !important; }
    .stTab [data-baseweb="tab-border"] { background: var(--accent) !important; }

    /* Expander */
    .stExpander { border: 1px solid var(--border) !important; border-radius: var(--radius) !important; background: var(--surface) !important; }

    /* Forms */
    .stForm { background: var(--surface) !important; border: 1px solid var(--border) !important; border-radius: var(--radius) !important; padding: 1.2rem !important; }

    /* Alerts */
    .stAlert { border-radius: var(--radius-sm) !important; border-left-width: 3px !important; }

    /* Progress bar */
    .stProgress > div > div { background: var(--surface2) !important; border-radius: 99px !important; }
    .stProgress > div > div > div { background: var(--accent) !important; border-radius: 99px !important; }

    /* Radio */
    .stRadio > div { gap: 0.5rem !important; }
    .stRadio [data-testid="stMarkdownContainer"] p { font-size: 0.88rem !important; }

    /* Custom components */
    .nav-brand {
        font-family: 'Cormorant Garamond', serif;
        font-size: 1.55rem;
        font-style: italic;
        font-weight: 700;
        background: linear-gradient(120deg, #F0F4FF 30%, #4F7EFF 70%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        letter-spacing: -0.02em;
    }
    .nav-divider { border: none; border-top: 1px solid var(--border); margin: 0.3rem 0 1rem 0; }

    .card {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        padding: 1.3rem 1.5rem;
        margin-bottom: 0.75rem;
        transition: border-color 0.18s, box-shadow 0.18s;
    }
    .card:hover { border-color: var(--border2); box-shadow: 0 4px 24px rgba(0,0,0,0.3); }
    .card-title { font-family: 'Playfair Display', serif; font-size: 1.05rem; color: var(--text); margin: 0 0 0.3rem 0; }
    .card-sub { font-size: 0.8rem; color: var(--text2); margin: 0; line-height: 1.5; }

    .page-title { font-family: 'Playfair Display', serif; font-size: 1.9rem; color: var(--text); margin-bottom: 0.15rem; letter-spacing: -0.02em; }
    .page-sub { font-size: 0.84rem; color: var(--text2); margin-bottom: 1.2rem; }
    .section-label { font-size: 0.7rem; font-weight: 600; color: var(--text3); letter-spacing: 0.1em; text-transform: uppercase; margin-bottom: 0.6rem; }
    .divider { border: none; border-top: 1px solid var(--border); margin: 0.4rem 0; }

    .badge { display: inline-block; padding: 0.15rem 0.55rem; border-radius: 99px; font-size: 0.72rem; font-weight: 600; letter-spacing: 0.03em; }
    .badge-eq  { background: rgba(79,126,255,0.12); color: #7BA3FF; }
    .badge-mf  { background: rgba(168,85,247,0.12); color: #C084FC; }
    .badge-etf { background: rgba(245,183,49,0.12); color: #F5B731; }
    .badge-bo  { background: rgba(46,204,122,0.12); color: #2ECC7A; }
    .badge-fd  { background: rgba(20,184,166,0.12); color: #2DD4BF; }
    .badge-co  { background: rgba(251,146,60,0.12); color: #FB923C; }

    .up   { color: var(--green); font-weight: 600; }
    .down { color: var(--red);   font-weight: 600; }
    .neutral { color: var(--text2); }

    .idx-pill { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 0.7rem 1rem; text-align: center; }
    .idx-name  { font-size: 0.72rem; color: var(--text2); margin-bottom: 0.15rem; letter-spacing: 0.04em; }
    .idx-val   { font-size: 1.1rem; font-weight: 600; color: var(--text); line-height: 1.2; }
    .idx-chg-u { font-size: 0.75rem; color: var(--green); }
    .idx-chg-d { font-size: 0.75rem; color: var(--red); }

    .stat-bar-wrap { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 1.2rem 1.4rem; }
    .stat-bar-row { margin-bottom: 0.85rem; }
    .stat-bar-label { display: flex; justify-content: space-between; margin-bottom: 0.3rem; }
    .stat-bar-bg { background: var(--surface2); border-radius: 6px; height: 10px; overflow: hidden; }
    .stat-bar-fill { height: 100%; border-radius: 6px; transition: width 0.4s ease; }

    #MainMenu, footer, header { visibility: hidden; }
    .stDeployButton { display: none; }
    [data-testid="stToolbar"] { display: none; }
    </style>
    """, unsafe_allow_html=True)
