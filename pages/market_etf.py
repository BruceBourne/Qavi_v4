import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate, back_button
from utils.db import get_assets, get_all_prices_map
from utils.crypto import indian_format
from collections import defaultdict

def render():
    st.markdown('<div class="page-title">ETFs</div>', unsafe_allow_html=True)
    back_button(fallback="market_equities", key="top")
    st.markdown('<div class="page-sub">Exchange Traded Funds listed on NSE</div>', unsafe_allow_html=True)

    b1,b2,b3,b4,b5 = st.columns(5)
    if b1.button("Equities", use_container_width=True): navigate("market_equities")
    if b2.button("Mutual Funds", use_container_width=True): navigate("market_mf")
    if b3.button("ETFs", use_container_width=True): pass
    if b4.button("Bonds", use_container_width=True): navigate("market_bonds")
    if b5.button("FDs & Commodities", use_container_width=True): navigate("market_fd")
    st.markdown("<br>", unsafe_allow_html=True)

    prices = get_all_prices_map()
    etfs   = get_assets("ETF")
    by_sub = defaultdict(list)
    for e in etfs: by_sub[e.get("sub_class","Other")].append(e)

    for sub, items in sorted(by_sub.items()):
        with st.expander(f"**{sub}** — {len(items)}", expanded=True):
            hdr = st.columns([2.5,1.5,1.2,1.2,1.5,1.8,0.6])
            for col,lbl in zip(hdr,["Symbol","Sector","Open","H/L","LTP","Change",""]):
                col.markdown(f"<div style='font-size:.7rem;color:#8892AA;font-weight:600'>{lbl}</div>", unsafe_allow_html=True)
            st.markdown('<hr class="divider"/>', unsafe_allow_html=True)
            for a in items:
                p   = prices.get(a["symbol"],{})
                cl  = p.get("close",0); chg = p.get("change_pct",0)
                cc  = "#2ECC7A" if chg>=0 else "#FF5A5A"; sign = "▲" if chg>=0 else "▼"
                hc  = st.columns([2.5,1.5,1.2,1.2,1.5,1.8,0.6])
                hc[0].markdown(f"<div style='font-weight:600;font-size:.87rem'>{a['symbol']}</div><div style='font-size:.7rem;color:#8892AA'>{a['name']}</div>", unsafe_allow_html=True)
                hc[1].markdown(f"<div style='font-size:.78rem;color:#8892AA'>{a.get('sector','')}</div>", unsafe_allow_html=True)
                hc[2].markdown(f"<div style='font-size:.83rem'>₹{indian_format(p.get('open',0))}</div>", unsafe_allow_html=True)
                hc[3].markdown(f"<div style='font-size:.78rem;color:#2ECC7A'>₹{indian_format(p.get('high',0))}</div><div style='font-size:.74rem;color:#FF5A5A'>₹{indian_format(p.get('low',0))}</div>", unsafe_allow_html=True)
                hc[4].markdown(f"<div style='font-size:.95rem;font-weight:700'>₹{indian_format(cl)}</div>", unsafe_allow_html=True)
                hc[5].markdown(f"<div style='color:{cc};font-weight:700'>{sign} {abs(chg):.2f}%</div>", unsafe_allow_html=True)
                if hc[6].button("→", key=f"etfdet_{a['symbol']}"):
                    st.session_state.selected_symbol = a["symbol"]; navigate("asset_detail")
                st.markdown('<hr class="divider"/>', unsafe_allow_html=True)
    back_button(fallback="market_equities", label="← Back", key="bot")
