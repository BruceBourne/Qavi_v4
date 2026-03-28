import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st

def inject_styles():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,600;1,400;1,600;1,700&family=Inter:wght@300;400;500;600&display=swap');
    /* Cormorant Garamond Italic = closest web font to Palatino Linotype italic */

    
    :root {
        --bg:#08090C; --bg2:#0F1117; --surface:#161B27; --surface2:#1E2535;
        --border:#252D40; --border2:#2E3850; --text:#F0F4FF; --text2:#8892AA;
        --text3:#4E5A70; --accent:#4F7EFF; --accent-glow:rgba(79,126,255,.14);
        --green:#2ECC7A; --red:#FF5A5A; --gold:#D4AF6A; --radius:14px; --radius-sm:8px;
    }
    html,body,[class*="css"]{font-family:'Inter',sans-serif!important;background:var(--bg)!important;color:var(--text)!important;}
    .stApp{background:var(--bg)!important;}
    /* Performance: contain heavy renders */
    .block-container{padding:1.2rem 2rem 4rem!important;max-width:1380px;contain:layout;}
    h1,h2,h3{font-family:'Cormorant Garamond','Palatino Linotype','Palatino','Book Antiqua',Georgia,serif!important;font-style:italic;letter-spacing:.02em;}

    /* Buttons — hardware-accelerated transitions only */
    .stButton>button{
        background:var(--surface)!important;color:var(--text)!important;
        border:1px solid var(--border)!important;border-radius:var(--radius-sm)!important;
        font-family:'Inter',sans-serif!important;font-size:.84rem!important;
        font-weight:500!important;padding:.42rem .9rem!important;
        transition:background .15s,border-color .15s,box-shadow .15s!important;
        will-change:background;
    }
    .stButton>button:hover{
        background:var(--accent)!important;border-color:var(--accent)!important;
        color:#fff!important;box-shadow:0 3px 16px var(--accent-glow)!important;
    }
    .stTextInput>div>div>input,.stSelectbox>div>div,.stNumberInput>div>div>input,
    .stTextArea>div>div>textarea,.stDateInput>div>div>input{
        background:var(--surface)!important;color:var(--text)!important;
        border:1px solid var(--border)!important;border-radius:var(--radius-sm)!important;
        font-family:'Inter',sans-serif!important;font-size:.88rem!important;
    }
    .stTextInput>div>div>input:focus,.stTextArea>div>div>textarea:focus{
        border-color:var(--accent)!important;box-shadow:0 0 0 2px var(--accent-glow)!important;
    }
    div[data-testid="metric-container"]{
        background:var(--surface)!important;border:1px solid var(--border)!important;
        border-radius:var(--radius)!important;padding:1rem 1.1rem!important;
    }
    div[data-testid="metric-container"] label{color:var(--text2)!important;font-size:.75rem!important;}
    div[data-testid="metric-container"] [data-testid="metric-value"]{color:var(--text)!important;font-weight:600!important;}
    .stTab [data-baseweb="tab"]{font-family:'Inter',sans-serif!important;font-weight:500!important;color:var(--text2)!important;font-size:.84rem!important;}

    /* ── GLOBAL TABLE / ROW STYLES ── */
    /* Streamlit native dataframes */
    .stDataFrame{font-size:.88rem!important;}
    .stDataFrame table{font-size:.88rem!important;}
    .stDataFrame th{font-size:.78rem!important;font-weight:600!important;
        color:var(--text2)!important;text-align:left!important;
        border-bottom:1px solid var(--border)!important;}
    .stDataFrame td{font-size:.86rem!important;color:var(--text)!important;
        vertical-align:middle!important;padding:.45rem .6rem!important;}
    /* Custom markdown table rows — header labels */
    .tbl-hdr{font-size:.78rem!important;color:var(--text2);font-weight:600;
        padding-bottom:.3rem;}
    /* Custom row data — increase from .82-.84rem to .88rem */
    .tbl-row{font-size:.88rem!important;color:var(--text);line-height:1.6;}
    .tbl-row-sub{font-size:.76rem!important;color:var(--text2);}
    /* Ensure custom columns align properly */
    [data-testid="column"]{display:flex;align-items:center;}
    .stTab [aria-selected="true"]{color:var(--accent)!important;}
    .stTab [data-baseweb="tab-border"]{background:var(--accent)!important;}
    .stExpander{border:1px solid var(--border)!important;border-radius:var(--radius)!important;background:var(--surface)!important;}
    .stForm{background:var(--surface)!important;border:1px solid var(--border)!important;border-radius:var(--radius)!important;padding:1.2rem!important;}
    .stAlert{border-radius:var(--radius-sm)!important;border-left-width:3px!important;}
    .stProgress>div>div{background:var(--surface2)!important;border-radius:99px!important;}
    .stProgress>div>div>div{background:var(--accent)!important;border-radius:99px!important;}
    .stRadio>div{gap:.5rem!important;}
    .stRadio [data-testid="stMarkdownContainer"] p{font-size:.88rem!important;}

    /* NAV brand — Palatino Linotype italic, gold gradient */
    .nav-brand{
        font-family:'Cormorant Garamond','Palatino Linotype','Palatino','Book Antiqua',Georgia,serif;
        font-style:italic;font-size:1.45rem;font-weight:700;
        letter-spacing:.06em;
        background:linear-gradient(120deg,#F8EDD4 20%,#D4AF6A 50%,#F8EDD4 80%);
        -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
    }
    .nav-divider{border:none;border-top:1px solid var(--border);margin:.3rem 0 1rem 0;}

    .card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
          padding:1.3rem 1.5rem;margin-bottom:.75rem;}
    .card-title{font-family:'Cormorant Garamond','Palatino Linotype','Palatino','Book Antiqua',Georgia,serif;font-style:italic;font-size:1rem;letter-spacing:.02em;color:var(--text);margin:0 0 .3rem 0;}
    .card-sub{font-size:.8rem;color:var(--text2);margin:0;line-height:1.5;}

    .page-title{font-family:'Cormorant Garamond','Palatino Linotype','Palatino','Book Antiqua',Georgia,serif;font-style:italic;font-size:1.7rem;letter-spacing:.02em;color:var(--text);margin-bottom:.15rem;}
    .page-sub{font-size:.84rem;color:var(--text2);margin-bottom:1.2rem;}
    .section-label{font-size:.68rem;font-weight:600;color:var(--text3);letter-spacing:.1em;text-transform:uppercase;margin-bottom:.6rem;}
    .divider{border:none;border-top:1px solid var(--border);margin:.4rem 0;}

    .badge{display:inline-block;padding:.15rem .55rem;border-radius:99px;font-size:.72rem;font-weight:600;letter-spacing:.03em;}
    .badge-eq{background:rgba(79,126,255,.12);color:#7BA3FF;}
    .badge-mf{background:rgba(168,85,247,.12);color:#C084FC;}
    .badge-etf{background:rgba(212,175,106,.12);color:#D4AF6A;}
    .badge-bo{background:rgba(46,204,122,.12);color:#2ECC7A;}
    .badge-fd{background:rgba(20,184,166,.12);color:#2DD4BF;}
    .badge-co{background:rgba(251,146,60,.12);color:#FB923C;}

    .up{color:var(--green);font-weight:600;} .down{color:var(--red);font-weight:600;} .neutral{color:var(--text2);}
    .idx-pill{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);padding:.7rem 1rem;text-align:center;}
    .idx-name{font-size:.72rem;color:var(--text2);margin-bottom:.15rem;letter-spacing:.04em;}
    .idx-val{font-size:1.1rem;font-weight:600;color:var(--text);line-height:1.2;}
    .idx-chg-u{font-size:.75rem;color:var(--green);}
    .idx-chg-d{font-size:.75rem;color:var(--red);}
    .stat-bar-wrap{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:1.2rem 1.4rem;}
    .stat-bar-row{margin-bottom:.85rem;}
    .stat-bar-label{display:flex;justify-content:space-between;margin-bottom:.3rem;}
    .stat-bar-bg{background:var(--surface2);border-radius:6px;height:10px;overflow:hidden;}
    .stat-bar-fill{height:100%;border-radius:6px;}

    #MainMenu,footer,header{visibility:hidden;}
    .stDeployButton,[data-testid="stToolbar"]{display:none;}
    </style>
    """, unsafe_allow_html=True)
