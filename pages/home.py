import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate
import base64

def _b64(path):
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except Exception:
        return None

def render():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    vid  = _b64(os.path.join(base, "assets", "hero_video.mp4"))
    img  = _b64(os.path.join(base, "assets", "hero_bg.png"))

    if vid:
        bg = f"""<video autoplay muted loop playsinline
            style="position:absolute;top:0;left:0;width:100%;height:100%;object-fit:cover;z-index:0;">
            <source src="data:video/mp4;base64,{vid}" type="video/mp4"/>
        </video>"""
    elif img:
        bg = f"""<div style="position:absolute;inset:0;z-index:0;
            background:url('data:image/png;base64,{img}') center/cover no-repeat;"></div>"""
    else:
        bg = """<div style="position:absolute;inset:0;z-index:0;
            background:linear-gradient(160deg,#0C0F13,#1a1f2e,#0C0F13);"></div>"""

    st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700;900&family=Cinzel+Decorative:wght@400;700&family=Inter:wght@300;400;500;600&display=swap');
    @keyframes fadeUp  {{ from{{opacity:0;transform:translateY(28px)}} to{{opacity:1;transform:translateY(0)}} }}
    @keyframes shimmer {{ 0%{{background-position:-300% center}} 100%{{background-position:300% center}} }}
    @keyframes glow    {{ 0%,100%{{opacity:.85}} 50%{{opacity:1}} }}

    .hw{{position:relative;width:calc(100% + 4rem);margin-left:-2rem;margin-top:-1.5rem;
         height:540px;display:flex;align-items:center;justify-content:center;overflow:hidden;
         border-bottom:1px solid rgba(255,255,255,.05);}}
    .ho{{position:absolute;inset:0;z-index:1;
         background:linear-gradient(to bottom,rgba(8,9,12,.5) 0%,rgba(8,9,12,.35) 40%,
         rgba(8,9,12,.75) 85%,rgba(8,9,12,1) 100%);}}
    .hc{{position:relative;z-index:2;text-align:center;padding:0 1rem;animation:fadeUp .9s ease both;}}

    .qw{{font-family:'Cinzel Decorative','Cinzel',serif;font-weight:700;
         font-size:clamp(4.5rem,14vw,10rem);line-height:1;letter-spacing:.1em;
         background:linear-gradient(135deg,#F8EDD4 0%,#D4AF6A 28%,#F8EDD4 50%,#C5922E 72%,#F8EDD4 100%);
         background-size:300% auto;-webkit-background-clip:text;-webkit-text-fill-color:transparent;
         background-clip:text;animation:shimmer 5s linear infinite,glow 3s ease-in-out infinite;
         display:block;margin-bottom:.6rem;}}
    .qt{{font-family:'Inter',sans-serif;font-size:.7rem;font-weight:600;letter-spacing:.34em;
         color:rgba(248,237,212,.55);text-transform:uppercase;margin-bottom:1.6rem;
         animation:fadeUp .9s ease .25s both;}}
    .qd{{font-family:'Inter',sans-serif;font-size:1rem;color:rgba(248,237,212,.7);
         max-width:500px;margin:0 auto 0;line-height:1.85;animation:fadeUp .9s ease .45s both;}}

    .feats{{display:grid;grid-template-columns:repeat(3,1fr);gap:1.1rem;
            margin:3rem 0 1.5rem;animation:fadeUp 1s ease .65s both;}}
    @media(max-width:760px){{.feats{{grid-template-columns:1fr;}}}}
    .fc{{background:linear-gradient(145deg,#0F1117,#161B27);border:1px solid #1E2535;
         border-radius:14px;padding:1.6rem;transition:border-color .2s,transform .2s;}}
    .fc:hover{{border-color:#D4AF6A;transform:translateY(-2px);}}
    .fi{{font-size:1.5rem;margin-bottom:.65rem;}}
    .ft2{{font-family:'Cinzel',serif;font-size:.88rem;letter-spacing:.07em;
          color:#F8EDD4;margin-bottom:.3rem;font-weight:600;}}
    .fd{{font-size:.8rem;color:#6B778E;line-height:1.7;}}
    </style>

    <div class="hw">
        {bg}
        <div class="ho"></div>
        <div class="hc">
            <span class="qw">QAVI</span>
            <div class="qt">Your Wealth &nbsp;·&nbsp; Made Clear</div>
            <p class="qd">Every investment you own — equities, mutual funds, bonds,
            gold, fixed deposits — tracked, analysed, and presented with complete clarity.</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    _, c1, c2, _ = st.columns([1.6, 0.8, 0.8, 1.6])
    if c1.button("Sign In",     use_container_width=True, key="h_login"):    navigate("login")
    if c2.button("Get Started", use_container_width=True, key="h_register"): navigate("register")

    st.markdown("""
    <div class="feats">
        <div class="fc"><div class="fi">📊</div>
            <div class="ft2">Complete Coverage</div>
            <p class="fd">Equities, mutual funds, ETFs, bonds, government schemes, bank FDs, gold and silver — everything in one view.</p></div>
        <div class="fc"><div class="fi">🔬</div>
            <div class="ft2">Deep Analytics</div>
            <p class="fd">P&L per holding, allocation breakdowns, 1D to 5Y return history, Sharpe ratio and key performance ratios.</p></div>
        <div class="fc"><div class="fi">🔒</div>
            <div class="ft2">Private by Design</div>
            <p class="fd">Your data is encrypted end-to-end. Invite-only platform. Private portfolios visible only to you.</p></div>
    </div>
    """, unsafe_allow_html=True)

    # Disclaimer at bottom of home page
    st.markdown("""
    <div style="margin-top:3rem;padding:1.2rem 1.5rem;background:#0D1117;
        border-top:1px solid #1A2030;border-radius:0 0 12px 12px">
        <div style="font-size:.72rem;color:#4E5A70;line-height:2">
            <b style="color:#5A6880">Disclaimer</b> &nbsp;·&nbsp;
            Qavi is a portfolio analytics and intelligence platform designed to help users
            understand their investments across asset classes. Qavi does not provide investment
            advice, recommendations or execution services, and is not a registered investment
            advisor with SEBI. All analytics, risk metrics and scenario models are for
            informational purposes only. Past performance is not indicative of future results.
        </div>
    </div>
    """, unsafe_allow_html=True)
