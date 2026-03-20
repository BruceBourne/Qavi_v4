import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate

def render():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,600;1,400;1,600;1,700&family=Inter:wght@300;400;500;600&display=swap');
    @keyframes fadeIn  { from{opacity:0;transform:translateY(18px)} to{opacity:1;transform:translateY(0)} }
    @keyframes shimmer { 0%{background-position:-300% center} 100%{background-position:300% center} }
    @keyframes pulse   { 0%,100%{opacity:.06} 50%{opacity:.13} }
    .hero{text-align:center;padding:5.5rem 1rem 2rem;position:relative;overflow:hidden;}
    .hero-glow{
        position:absolute;width:700px;height:700px;border-radius:50%;
        background:radial-gradient(circle,rgba(79,126,255,.1),transparent 65%);
        top:-250px;left:50%;transform:translateX(-50%);
        animation:pulse 6s ease-in-out infinite;pointer-events:none;
    }
    .qavi-logo{
        font-family:'Cormorant Garamond',serif;
        font-style:italic;font-weight:700;
        font-size:clamp(6rem,18vw,12rem);
        line-height:.95;letter-spacing:-.02em;display:block;
        background:linear-gradient(130deg,#E8EEFF 15%,#6B9FFF 42%,#B8CFFF 58%,#E8EEFF 82%);
        background-size:300% auto;
        -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
        animation:shimmer 6s linear infinite,fadeIn .9s ease both;
        margin-bottom:.5rem;
    }
    .hero-line{
        font-family:'Inter',sans-serif;font-size:.72rem;font-weight:600;
        letter-spacing:.28em;color:#3D4A60;text-transform:uppercase;
        animation:fadeIn .9s ease .3s both;
    }
    .hero-desc{
        font-size:1rem;color:#7A8499;max-width:480px;margin:1.4rem auto 2.5rem;
        line-height:1.8;animation:fadeIn .9s ease .5s both;
    }
    .features{
        display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;
        margin:3.5rem 0 1.5rem;animation:fadeIn 1s ease .9s both;
    }
    @media(max-width:768px){.features{grid-template-columns:1fr;}}
    .feat-card{
        background:linear-gradient(145deg,#0F1117,#161B27);
        border:1px solid #1E2535;border-radius:14px;padding:1.6rem;
        transition:border-color .2s,transform .2s;
    }
    .feat-card:hover{border-color:#4F7EFF;transform:translateY(-2px);}
    .feat-icon{font-size:1.6rem;margin-bottom:.7rem;}
    .feat-title{font-family:'Cormorant Garamond',serif;font-size:1.1rem;font-style:italic;color:#E8EEFF;margin-bottom:.35rem;}
    .feat-text{font-size:.81rem;color:#6B778E;line-height:1.7;}
    </style>
    <div class="hero">
        <div class="hero-glow"></div>
        <span class="qavi-logo">Qavi</span>
        <div class="hero-line">Your Wealth, Made Clear</div>
        <p class="hero-desc">
            Every investment you own — equities, mutual funds, bonds,
            gold, fixed deposits — tracked, analysed, and presented
            with complete clarity.
        </p>
    </div>
    """, unsafe_allow_html=True)

    _, c1, c2, _ = st.columns([1.5, 0.85, 0.85, 1.5])
    if c1.button("Sign In",     use_container_width=True, key="h_login"):    navigate("login")
    if c2.button("Get Started", use_container_width=True, key="h_register"): navigate("register")

    st.markdown("""
    <div style="max-width:860px;margin:2.8rem auto 0;border-radius:18px;overflow:hidden;
        border:1px solid #1E2535;box-shadow:0 24px 80px rgba(0,0,0,.55);">
        <img src="https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?w=1200&q=80&auto=format&fit=crop"
            style="width:100%;display:block;height:320px;object-fit:cover;object-position:center;"
            alt="Wealth management"/>
    </div>
    <div class="features">
        <div class="feat-card">
            <div class="feat-icon">📊</div>
            <div class="feat-title">Complete Asset Coverage</div>
            <p class="feat-text">Equities, mutual funds, ETFs, bonds, government schemes, bank FDs, gold and silver — everything in one view.</p>
        </div>
        <div class="feat-card">
            <div class="feat-icon">🔬</div>
            <div class="feat-title">Deep Analytics</div>
            <p class="feat-text">P&L per holding, allocation breakdowns, 1D to 5Y return history, Sharpe ratio and key performance ratios.</p>
        </div>
        <div class="feat-card">
            <div class="feat-icon">🔒</div>
            <div class="feat-title">Private by Design</div>
            <p class="feat-text">Your data is encrypted end-to-end. Invite-only platform. Private portfolios visible only to you.</p>
        </div>
    </div>
    """, unsafe_allow_html=True)
