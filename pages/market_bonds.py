import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate, back_button
from utils.db import get_fixed_income
from utils.crypto import indian_format, fmt_date
from collections import defaultdict

def render():
    st.markdown('<div class="page-title">Bonds & Fixed Income</div>', unsafe_allow_html=True)
    back_button(fallback="market_equities", key="top")
    st.markdown('<div class="page-sub">Government securities, PSU bonds, NCDs, and savings schemes</div>', unsafe_allow_html=True)

    b1,b2,b3,b4,b5 = st.columns(5)
    if b1.button("Equities", use_container_width=True): navigate("market_equities")
    if b2.button("Mutual Funds", use_container_width=True): navigate("market_mf")
    if b3.button("ETFs", use_container_width=True): navigate("market_etf")
    if b4.button("Bonds", use_container_width=True): pass
    if b5.button("FDs & Commodities", use_container_width=True): navigate("market_fd")
    st.markdown("<br>", unsafe_allow_html=True)

    bonds  = get_fixed_income("Bond")
    by_sub = defaultdict(list)
    for b in bonds: by_sub[b.get("sub_class","Other")].append(b)

    def _row(b):
        rc  = "#2ECC7A" if b.get("rating") in ["SOV","AAA"] else "#F5B731" if b.get("rating") in ["AA+","AA"] else "#FF5A5A"
        hc  = st.columns([2.8,1.5,1.2,1.5,1.2,1.5,1.2])
        hc[0].markdown(f"<div style='font-weight:600;font-size:.87rem'>{b['name']}</div>", unsafe_allow_html=True)
        hc[1].markdown(f"<div style='font-size:.78rem;color:#8892AA'>{b.get('issuer','')}</div>", unsafe_allow_html=True)
        hc[2].markdown(f"<div style='font-size:.9rem;font-weight:700;color:#2ECC7A'>{b.get('interest_rate',0):.2f}%</div>", unsafe_allow_html=True)
        hc[3].markdown(f"<div style='font-size:.83rem'>{b.get('tenure_years',0):.0f} yr</div>", unsafe_allow_html=True)
        cp = b.get("current_price",0) or b.get("face_value",0)
        hc[4].markdown(f"<div style='font-size:.83rem'>₹{indian_format(cp)}</div>", unsafe_allow_html=True)
        hc[5].markdown(f"<div style='color:{rc};font-weight:700;font-size:.85rem'>{b.get('rating','')}</div>", unsafe_allow_html=True)
        hc[6].markdown(f"<div style='font-size:.78rem;color:#8892AA'>Min ₹{indian_format(b.get('min_investment',0))}</div>", unsafe_allow_html=True)
        st.markdown('<hr class="divider"/>', unsafe_allow_html=True)

    for sub in ["Government Bond","PSU Bond","Corporate NCD","Sovereign Gold Bond","Small Savings"]:
        items = by_sub.get(sub,[])
        if not items: continue
        with st.expander(f"**{sub}** — {len(items)}", expanded=True):
            hdr = st.columns([2.8,1.5,1.2,1.5,1.2,1.5,1.2])
            for col,lbl in zip(hdr,["Name","Issuer","Rate","Tenure","Price","Rating","Min Invest"]):
                col.markdown(f"<div style='font-size:.7rem;color:#8892AA;font-weight:600'>{lbl}</div>", unsafe_allow_html=True)
            st.markdown('<hr class="divider"/>', unsafe_allow_html=True)
            for b in items: _row(b)
    back_button(fallback="market_equities", label="← Back", key="bot")
