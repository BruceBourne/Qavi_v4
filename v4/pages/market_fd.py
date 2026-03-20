import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate
from utils.db import get_fixed_income, get_commodities
from utils.crypto import indian_format
from collections import defaultdict

def render():
    st.markdown('<div class="page-title">Bank FDs & Commodities</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Fixed deposit rates and commodity spot prices</div>', unsafe_allow_html=True)

    b1,b2,b3,b4,b5 = st.columns(5)
    if b1.button("Equities", use_container_width=True): navigate("market_equities")
    if b2.button("Mutual Funds", use_container_width=True): navigate("market_mf")
    if b3.button("ETFs", use_container_width=True): navigate("market_etf")
    if b4.button("Bonds", use_container_width=True): navigate("market_bonds")
    if b5.button("FDs & Commodities", use_container_width=True): pass
    st.markdown("<br>", unsafe_allow_html=True)

    tab1, tab2 = st.tabs(["  🏦 Bank & Corporate FDs  ", "  🥇 Commodities  "])

    with tab1:
        fds    = get_fixed_income("Bank FD")
        by_sub = defaultdict(list)
        for f in fds: by_sub[f.get("sub_class","Other")].append(f)

        for sub in ["Bank FD","Corporate FD"]:
            items = by_sub.get(sub,[])
            if not items: continue
            with st.expander(f"**{sub}** — {len(items)}", expanded=True):
                hdr = st.columns([3,1.5,1.5,1.5,1.5,1.5])
                for col,lbl in zip(hdr,["Bank / Scheme","Issuer","Interest Rate","Tenure","Rating","Min Invest"]):
                    col.markdown(f"<div style='font-size:.7rem;color:#8892AA;font-weight:600'>{lbl}</div>", unsafe_allow_html=True)
                st.markdown('<hr class="divider"/>', unsafe_allow_html=True)
                for f in sorted(items, key=lambda x: -x.get("interest_rate",0)):
                    rc  = "#2ECC7A" if f.get("rating") in ["SOV","AAA"] else "#F5B731"
                    hc  = st.columns([3,1.5,1.5,1.5,1.5,1.5])
                    hc[0].markdown(f"<div style='font-weight:600;font-size:.87rem'>{f['name']}</div>", unsafe_allow_html=True)
                    hc[1].markdown(f"<div style='font-size:.78rem;color:#8892AA'>{f.get('issuer','')}</div>", unsafe_allow_html=True)
                    hc[2].markdown(f"<div style='font-size:1rem;font-weight:700;color:#2ECC7A'>{f.get('interest_rate',0):.2f}%</div>", unsafe_allow_html=True)
                    hc[3].markdown(f"<div style='font-size:.83rem'>{f.get('tenure_years',0):.0f} yr</div>", unsafe_allow_html=True)
                    hc[4].markdown(f"<div style='color:{rc};font-weight:600;font-size:.85rem'>{f.get('rating','')}</div>", unsafe_allow_html=True)
                    hc[5].markdown(f"<div style='font-size:.82rem;color:#8892AA'>₹{indian_format(f.get('min_investment',0))}</div>", unsafe_allow_html=True)
                    st.markdown('<hr class="divider"/>', unsafe_allow_html=True)

    with tab2:
        comms = get_commodities()
        if not comms:
            st.info("Commodity data loading…"); return
        hdr = st.columns([2.5,1.5,1.5,1.8,1.8,1.5])
        for col,lbl in zip(hdr,["Commodity","Sub-Class","Unit","Price","Change","Exchange"]):
            col.markdown(f"<div style='font-size:.7rem;color:#8892AA;font-weight:600'>{lbl}</div>", unsafe_allow_html=True)
        st.markdown('<hr class="divider"/>', unsafe_allow_html=True)
        for c in comms:
            chg = c.get("change_pct",0)
            cc  = "#2ECC7A" if chg>=0 else "#FF5A5A"; sign = "▲" if chg>=0 else "▼"
            hc  = st.columns([2.5,1.5,1.5,1.8,1.8,1.5])
            hc[0].markdown(f"<div style='font-weight:600;font-size:.87rem'>{c['name']}</div>", unsafe_allow_html=True)
            hc[1].markdown(f"<div style='font-size:.78rem;color:#8892AA'>{c.get('sub_class','')}</div>", unsafe_allow_html=True)
            hc[2].markdown(f"<div style='font-size:.82rem'>per {c.get('unit','unit')}</div>", unsafe_allow_html=True)
            hc[3].markdown(f"<div style='font-size:.95rem;font-weight:700'>₹{indian_format(c.get('price_per_unit',0))}</div>", unsafe_allow_html=True)
            hc[4].markdown(f"<div style='color:{cc};font-weight:700'>{sign} {abs(chg):.2f}%</div>", unsafe_allow_html=True)
            hc[5].markdown(f"<div style='font-size:.8rem;color:#8892AA'>{c.get('exchange','')}</div>", unsafe_allow_html=True)
            st.markdown('<hr class="divider"/>', unsafe_allow_html=True)
