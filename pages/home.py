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
    @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700&family=Cinzel+Decorative:wght@400;700&family=Inter:wght@300;400;500;600&display=swap');
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

    .qw{{font-family:'Palatino Linotype','Book Antiqua',Palatino,Georgia,serif;
         font-style:italic;font-weight:400;
         font-size:clamp(4.5rem,14vw,10rem);line-height:1;letter-spacing:.08em;
         background:linear-gradient(135deg,#F8EDD4 0%,#D4AF6A 28%,#F8EDD4 50%,#C5922E 72%,#F8EDD4 100%);
         background-size:300% auto;-webkit-background-clip:text;-webkit-text-fill-color:transparent;
         background-clip:text;animation:shimmer 5s linear infinite,glow 3s ease-in-out infinite;
         display:block;margin-bottom:.6rem;}}
    .qt{{font-family:'Inter',sans-serif;font-size:.7rem;font-weight:600;letter-spacing:.34em;
         color:rgba(248,237,212,.55);text-transform:uppercase;margin-bottom:1.6rem;
         animation:fadeUp .9s ease .25s both;}}
    .qd{{font-family:'Inter',sans-serif;font-size:1rem;color:rgba(248,237,212,.7);
         max-width:500px;margin:0 auto 0;line-height:1.85;animation:fadeUp .9s ease .45s both;}}

    .feats{{display:grid;grid-template-columns:repeat(2,1fr);gap:1.2rem;
            margin:3rem 0 1rem;animation:fadeUp 1s ease .65s both;}}
    @media(max-width:760px){{.feats{{grid-template-columns:1fr;}}}}
    .fc{{
        background:linear-gradient(145deg,#0C1018,#131825);
        border:1px solid #1E2535;border-radius:16px;padding:1.7rem 1.6rem;
        transition:border-color .25s,transform .25s,box-shadow .25s;
        position:relative;overflow:hidden;
    }}
    .fc::before{{
        content:'';position:absolute;top:0;left:0;right:0;height:1px;
        background:linear-gradient(90deg,transparent,rgba(212,175,106,.3),transparent);
    }}
    .fc:hover{{border-color:#D4AF6A40;transform:translateY(-3px);
               box-shadow:0 12px 40px rgba(0,0,0,.4);}}
    .fi-wrap{{
        width:44px;height:44px;border-radius:12px;
        display:flex;align-items:center;justify-content:center;
        margin-bottom:.9rem;font-size:1.25rem;
    }}
    .ft2{{font-family:'Cinzel',serif;font-size:.84rem;letter-spacing:.06em;
          color:#E8DFC8;margin-bottom:.45rem;font-weight:600;}}
    .fd{{font-size:.79rem;color:#5A677E;line-height:1.75;}}
    .fhero{{
        background:linear-gradient(135deg,#0A0E1A 0%,#080C16 60%,#060A12 100%);
        border:1px solid #1E2840;border-radius:16px;padding:2.2rem 2.4rem;
        margin-top:.8rem;margin-bottom:1.5rem;position:relative;overflow:hidden;
        animation:fadeUp 1s ease .8s both;
    }}
    .fhero::before{{content:'';position:absolute;top:0;left:0;right:0;height:2px;
            background:linear-gradient(90deg,transparent,#D4AF6A 30%,#4F7EFF 65%,transparent);}}
    .fhero::after{{
        content:'';position:absolute;bottom:-60px;right:-60px;
        width:180px;height:180px;border-radius:50%;
        background:radial-gradient(circle,rgba(79,126,255,.06),transparent 70%);
    }}
    .fhero-title{{font-family:'Cinzel',serif;font-size:1.08rem;letter-spacing:.06em;
            color:#E8DFC8;margin-bottom:.8rem;font-weight:600;}}
    .fhero-text{{font-size:.83rem;color:#5A677E;line-height:1.9;}}
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
        <div class="fc">
            <div class="fi-wrap" style="background:linear-gradient(135deg,#1a2340,#0f1628);border:1px solid #2a3a60">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <polyline points="22,7 13.5,15.5 8.5,10.5 2,17" stroke="#4F7EFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                  <polyline points="16,7 22,7 22,13" stroke="#4F7EFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            </div>
            <div class="ft2">Unified Wealth View</div>
            <p class="fd">Equities, mutual funds, ETFs, bonds, gold and fixed deposits — every asset in one intelligent view. See your true net worth across all asset classes.</p>
        </div>
        <div class="fc">
            <div class="fi-wrap" style="background:linear-gradient(135deg,#1a2a1a,#0f1a0f);border:1px solid #2a4a2a">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <circle cx="12" cy="12" r="10" stroke="#2ECC7A" stroke-width="1.8"/>
                  <path d="M12 6v6l4 2" stroke="#2ECC7A" stroke-width="1.8" stroke-linecap="round"/>
                  <path d="M7 9.5 C8 7 10 6 12 6" stroke="#2ECC7A" stroke-width="1.8" stroke-linecap="round"/>
                </svg>
            </div>
            <div class="ft2">Performance Analytics</div>
            <p class="fd">P&amp;L per holding, Sharpe ratio, drawdown scenarios and allocation insights — built to show how your portfolio behaves in real conditions.</p>
        </div>
        <div class="fc">
            <div class="fi-wrap" style="background:linear-gradient(135deg,#2a1a0a,#1a0f05);border:1px solid #5a3a10">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <rect x="3" y="11" width="18" height="11" rx="2" stroke="#D4AF6A" stroke-width="1.8"/>
                  <path d="M7 11V7a5 5 0 0 1 10 0v4" stroke="#D4AF6A" stroke-width="1.8" stroke-linecap="round"/>
                  <circle cx="12" cy="16" r="1.5" fill="#D4AF6A"/>
                </svg>
            </div>
            <div class="ft2">Private by Design</div>
            <p class="fd">Your financial data stays fully encrypted and accessible only to you. Invite-only, with complete control in your hands.</p>
        </div>
        <div class="fc">
            <div class="fi-wrap" style="background:linear-gradient(135deg,#1a1028,#100a1e);border:1px solid #3a2060">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M12 2L2 7l10 5 10-5-10-5z" stroke="#A855F7" stroke-width="1.8" stroke-linejoin="round"/>
                  <path d="M2 17l10 5 10-5" stroke="#A855F7" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                  <path d="M2 12l10 5 10-5" stroke="#A855F7" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
            </div>
            <div class="ft2">Goal-Aligned Planning</div>
            <p class="fd">Your portfolio structured around your ambitions. Understand how your assets support long-term goals and where adjustments may be needed.</p>
        </div>
    </div>
    <div class="fhero">
        <div class="fhero-title">More than tracking. It&rsquo;s understanding.</div>
        <div class="fhero-text">Most platforms show you what you own. Qavi helps you understand what it means.<br><br>By combining multi-asset tracking with intelligent analytics, Qavi gives you a clear picture of where you stand &mdash; and where you&rsquo;re headed.</div>
    </div>
    """, unsafe_allow_html=True)

    # Full SEBI disclaimer at bottom of home/landing page
    st.markdown("""
    <div style="margin-top:3rem;padding:1.2rem 1.5rem;background:#0D1117;
        border-top:1px solid #1A2030">
        <div style="font-size:.75rem;color:#4E5A70;line-height:2">
            Qavi is a portfolio analytics and intelligence platform designed to help users
            understand their investments across asset classes. We do not provide investment
            advice, recommendations or execution services, and are not a registered investment
            advisor with the Securities and Exchange Board of India (SEBI). All insights are
            informational in nature and should not be construed as financial advice.
        </div>
    </div>
    """, unsafe_allow_html=True)
