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
        bg = (f'<video autoplay muted loop playsinline '
              f'style="position:absolute;top:0;left:0;width:100%;height:100%;'
              f'object-fit:cover;z-index:0;">'
              f'<source src="data:video/mp4;base64,{vid}" type="video/mp4"/></video>')
    elif img:
        bg = (f'<div style="position:absolute;inset:0;z-index:0;'
              f'background:url(\'data:image/png;base64,{img}\') center/cover no-repeat;"></div>')
    else:
        bg = ('<div style="position:absolute;inset:0;z-index:0;'
              'background:radial-gradient(ellipse at 60% 40%,#0D1628 0%,#080B12 60%,#050710 100%);'
              'background-image:radial-gradient(ellipse at 60% 40%,#0D1628 0%,#080B12 60%,#050710 100%),'
              'radial-gradient(ellipse at 20% 80%,rgba(79,126,255,.06) 0%,transparent 60%),'
              'radial-gradient(ellipse at 85% 15%,rgba(212,175,106,.05) 0%,transparent 50%);"></div>')

    st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700&family=Inter:wght@300;400;500;600&display=swap');
@keyframes fadeUp  {{from{{opacity:0;transform:translateY(24px)}}to{{opacity:1;transform:translateY(0)}}}}
@keyframes shimmer {{0%{{background-position:-300% center}}100%{{background-position:300% center}}}}
@keyframes glow    {{0%,100%{{opacity:.82}}50%{{opacity:1}}}}
@keyframes borderPulse {{0%,100%{{opacity:.4}}50%{{opacity:.9}}}}

.hw{{position:relative;width:calc(100% + 4rem);margin-left:-2rem;margin-top:-1.5rem;
     height:520px;display:flex;align-items:center;justify-content:center;overflow:hidden;
     border-bottom:1px solid rgba(255,255,255,.04);}}
.ho{{position:absolute;inset:0;z-index:1;
     background:linear-gradient(to bottom,rgba(5,7,16,.4) 0%,rgba(5,7,16,.2) 35%,
     rgba(5,7,16,.7) 80%,rgba(5,7,16,1) 100%);}}
.hc{{position:relative;z-index:2;text-align:center;padding:0 1.5rem;animation:fadeUp .8s ease both;}}

.qw{{font-family:'Palatino Linotype','Book Antiqua',Palatino,Georgia,serif;
     font-style:italic;font-weight:400;
     font-size:clamp(4rem,13vw,9.5rem);line-height:1;letter-spacing:.08em;
     background:linear-gradient(135deg,#FDF6E8 0%,#E8C97A 25%,#F8EDD4 50%,#C5922E 75%,#F8EDD4 100%);
     background-size:300% auto;-webkit-background-clip:text;-webkit-text-fill-color:transparent;
     background-clip:text;animation:shimmer 6s linear infinite,glow 3.5s ease-in-out infinite;
     display:block;margin-bottom:.5rem;}}
.qt{{font-family:'Inter',sans-serif;font-size:.68rem;font-weight:500;letter-spacing:.36em;
     color:rgba(248,237,212,.45);text-transform:uppercase;margin-bottom:1.4rem;
     animation:fadeUp .8s ease .2s both;}}
.qd{{font-family:'Inter',sans-serif;font-size:.97rem;color:rgba(240,230,210,.62);
     max-width:480px;margin:0 auto;line-height:1.9;animation:fadeUp .8s ease .4s both;}}

/* ── FEATURE CARDS ── */
.feats{{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem;
        margin:2.8rem 0 1rem;animation:fadeUp .9s ease .55s both;}}
@media(max-width:900px){{.feats{{grid-template-columns:repeat(2,1fr);}}}}
@media(max-width:540px){{.feats{{grid-template-columns:1fr;}}}}

.fc{{
    position:relative;overflow:hidden;
    background:#070B14;
    border:1px solid rgba(255,255,255,.07);
    border-radius:18px;padding:1.6rem 1.4rem 1.5rem;
    transition:transform .25s ease,border-color .25s ease,box-shadow .25s ease;
    cursor:default;
}}
.fc::before{{
    content:'';position:absolute;inset:0;border-radius:18px;
    background:radial-gradient(ellipse at top left,var(--card-glow,rgba(79,126,255,.07)) 0%,transparent 65%);
    pointer-events:none;
}}
.fc::after{{
    content:'';position:absolute;top:0;left:10%;right:10%;height:1px;
    background:linear-gradient(90deg,transparent,var(--card-line,rgba(79,126,255,.4)),transparent);
    animation:borderPulse 3s ease-in-out infinite;
}}
.fc:hover{{
    transform:translateY(-4px);
    border-color:rgba(255,255,255,.14);
    box-shadow:0 16px 48px rgba(0,0,0,.5),0 0 0 1px rgba(255,255,255,.06);
}}

.fi-ring{{
    width:46px;height:46px;border-radius:13px;
    display:flex;align-items:center;justify-content:center;
    margin-bottom:1rem;position:relative;
    border:1px solid var(--ring-border,rgba(79,126,255,.25));
    background:var(--ring-bg,rgba(79,126,255,.08));
}}
.ft{{font-family:'Cinzel',serif;font-size:.79rem;letter-spacing:.07em;
      color:#D8CEBC;margin-bottom:.5rem;font-weight:600;line-height:1.3;}}
.fd{{font-size:.78rem;color:rgba(120,132,155,.85);line-height:1.8;}}

/* ── HERO CARD ── */
.fhero{{
    position:relative;overflow:hidden;
    background:linear-gradient(145deg,#08111F 0%,#060D18 60%,#040A14 100%);
    border:1px solid rgba(255,255,255,.08);
    border-radius:18px;padding:2rem 2.4rem;
    margin:1rem 0 1.5rem;animation:fadeUp .9s ease .7s both;
}}
.fhero::before{{
    content:'';position:absolute;top:0;left:0;right:0;height:2px;
    background:linear-gradient(90deg,transparent 5%,#C5922E 30%,#D4AF6A 50%,#4F7EFF 70%,transparent 95%);
    opacity:.7;
}}
.fhero::after{{
    content:'';position:absolute;bottom:-80px;right:-80px;
    width:220px;height:220px;border-radius:50%;
    background:radial-gradient(circle,rgba(79,126,255,.05),transparent 70%);
}}
.fhero-body{{display:flex;gap:2.5rem;align-items:flex-start;}}
.fhero-stat{{text-align:center;flex-shrink:0;}}
.fhero-num{{font-family:'Palatino Linotype','Book Antiqua',Palatino,serif;
            font-style:italic;font-size:2.4rem;font-weight:400;
            background:linear-gradient(135deg,#F8EDD4,#D4AF6A);
            -webkit-background-clip:text;-webkit-text-fill-color:transparent;
            background-clip:text;line-height:1;margin-bottom:.2rem;}}
.fhero-stat-lbl{{font-size:.68rem;color:rgba(120,132,155,.7);letter-spacing:.1em;text-transform:uppercase;}}
.fhero-divider{{width:1px;background:rgba(255,255,255,.07);flex-shrink:0;align-self:stretch;}}
.fhero-text-wrap{{flex:1;}}
.fhero-title{{font-family:'Cinzel',serif;font-size:.92rem;letter-spacing:.07em;
              color:#D8CEBC;margin-bottom:.6rem;font-weight:600;}}
.fhero-text{{font-size:.8rem;color:rgba(110,122,145,.9);line-height:1.95;}}
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
    _, c1, c2, _ = st.columns([1.8, 0.75, 0.75, 1.8])
    if c1.button("Sign In",     use_container_width=True, key="h_login"):    navigate("login")
    if c2.button("Get Started", use_container_width=True, key="h_register"): navigate("register")

    # Feature cards — 4 columns
    st.markdown("""
<div class="feats">
    <div class="fc" style="--card-glow:rgba(79,126,255,.09);--card-line:rgba(79,126,255,.5);">
        <div class="fi-ring" style="--ring-bg:rgba(79,126,255,.09);--ring-border:rgba(79,126,255,.22);">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <polyline points="22,7 13.5,15.5 8.5,10.5 2,17" stroke="#4F7EFF" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
              <polyline points="16,7 22,7 22,13" stroke="#4F7EFF" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
        </div>
        <div class="ft">Unified Wealth View</div>
        <p class="fd">Equities, mutual funds, ETFs, bonds, gold and FDs — every asset class in one intelligent view. See your true net worth instantly.</p>
    </div>
    <div class="fc" style="--card-glow:rgba(46,204,122,.07);--card-line:rgba(46,204,122,.4);">
        <div class="fi-ring" style="--ring-bg:rgba(46,204,122,.08);--ring-border:rgba(46,204,122,.2);">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <circle cx="12" cy="12" r="9" stroke="#2ECC7A" stroke-width="1.8"/>
              <path d="M12 7v5l3.5 2" stroke="#2ECC7A" stroke-width="1.8" stroke-linecap="round"/>
            </svg>
        </div>
        <div class="ft">Performance Analytics</div>
        <p class="fd">P&amp;L per holding, Sharpe ratio, drawdown analysis and return history — built to show how your portfolio behaves in real conditions.</p>
    </div>
    <div class="fc" style="--card-glow:rgba(212,175,106,.07);--card-line:rgba(212,175,106,.4);">
        <div class="fi-ring" style="--ring-bg:rgba(212,175,106,.08);--ring-border:rgba(212,175,106,.22);">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <rect x="3" y="11" width="18" height="11" rx="2" stroke="#D4AF6A" stroke-width="1.8"/>
              <path d="M7 11V7a5 5 0 0 1 10 0v4" stroke="#D4AF6A" stroke-width="1.8" stroke-linecap="round"/>
              <circle cx="12" cy="16" r="1.4" fill="#D4AF6A"/>
            </svg>
        </div>
        <div class="ft">Private by Design</div>
        <p class="fd">Your financial data stays fully encrypted and visible only to you. Invite-only access with complete control in your hands.</p>
    </div>
    <div class="fc" style="--card-glow:rgba(168,85,247,.07);--card-line:rgba(168,85,247,.38);">
        <div class="fi-ring" style="--ring-bg:rgba(168,85,247,.08);--ring-border:rgba(168,85,247,.2);">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path d="M12 2L2 7l10 5 10-5-10-5z" stroke="#A855F7" stroke-width="1.8" stroke-linejoin="round"/>
              <path d="M2 17l10 5 10-5M2 12l10 5 10-5" stroke="#A855F7" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
        </div>
        <div class="ft">Goal-Aligned Planning</div>
        <p class="fd">Structure your portfolio around your ambitions. Understand how your assets support long-term goals and where adjustments may help.</p>
    </div>
</div>

<div class="fhero">
    <div class="fhero-body">
        <div>
            <div class="fhero-stat">
                <div class="fhero-num">6+</div>
                <div class="fhero-stat-lbl">Asset Classes</div>
            </div>
            <div style="margin-top:1.2rem" class="fhero-stat">
                <div class="fhero-num">∞</div>
                <div class="fhero-stat-lbl">Portfolios</div>
            </div>
        </div>
        <div class="fhero-divider"></div>
        <div class="fhero-text-wrap">
            <div class="fhero-title">More than tracking. It&rsquo;s understanding.</div>
            <div class="fhero-text">Most platforms show you what you own. Qavi helps you understand what it means.<br><br>
            By combining multi-asset tracking with intelligent analytics, Qavi gives you a clear picture
            of where you stand — and a structured view of where you&rsquo;re headed.</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

    st.markdown("""
<div style="padding:1.1rem 1.4rem;background:rgba(5,8,16,.6);
    border-top:1px solid rgba(255,255,255,.05)">
    <div style="font-size:.72rem;color:#2E3850;line-height:2">
        Qavi is a portfolio analytics and intelligence platform. We do not provide investment
        advice, recommendations or execution services, and are not a registered investment advisor
        with SEBI. All insights are informational and should not be construed as financial advice.
    </div>
</div>
""", unsafe_allow_html=True)
