import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate
from utils.db import get_mutual_funds
from utils.crypto import indian_format
from collections import defaultdict

def render():
    st.markdown('<div class="page-title">Mutual Funds</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">NAVs updated daily from mfapi.in</div>', unsafe_allow_html=True)

    b1,b2,b3,b4,b5 = st.columns(5)
    if b1.button("Equities", use_container_width=True): navigate("market_equities")
    if b2.button("Mutual Funds", use_container_width=True): pass
    if b3.button("ETFs", use_container_width=True): navigate("market_etf")
    if b4.button("Bonds", use_container_width=True): navigate("market_bonds")
    if b5.button("FDs & Commodities", use_container_width=True): navigate("market_fd")
    st.markdown("<br>", unsafe_allow_html=True)

    search = st.text_input("🔍 Search funds", placeholder="Fund name or AMC…", label_visibility="collapsed")
    mfs    = get_mutual_funds(search=search if search else None)

    by_cat = defaultdict(list)
    for m in mfs: by_cat[m.get("category","Other")].append(m)

    for cat in ["Equity","ELSS","Hybrid","Index","Debt"] + [c for c in by_cat if c not in ["Equity","ELSS","Hybrid","Index","Debt"]]:
        items = by_cat.get(cat,[])
        if not items: continue
        by_sub = defaultdict(list)
        for m in items: by_sub[m.get("sub_category","Other")].append(m)
        with st.expander(f"**{cat}** — {len(items)} funds", expanded=(cat=="Equity")):
            for sub, sub_mfs in sorted(by_sub.items()):
                st.markdown(f'<div style="font-size:.72rem;color:#A855F7;font-weight:700;letter-spacing:.08em;margin:.6rem 0 .3rem;text-transform:uppercase">{sub}</div>', unsafe_allow_html=True)
                hdr = st.columns([3,1.2,1,1.2,1.1,1.1,1.1,0.55])
                for col,lbl in zip(hdr,["Fund","AMC","Risk","NAV","1Y Ret","3Y Ret","TER",""]):
                    col.markdown(f"<div style='font-size:.7rem;color:#8892AA;font-weight:600'>{lbl}</div>", unsafe_allow_html=True)
                st.markdown('<hr class="divider"/>', unsafe_allow_html=True)
                for m in sub_mfs:
                    chg = m.get("change_pct",0)
                    cc  = "#2ECC7A" if chg>=0 else "#FF5A5A"
                    rl  = m.get("risk_level","—")
                    rc  = {"Low":"#2ECC7A","Moderate":"#F5B731","High":"#FF5A5A","Very High":"#DC2626"}.get(rl,"#8892AA")
                    r1y = m.get("return_1y"); r3y = m.get("return_3y")
                    ter = m.get("expense_ratio")
                    aum = m.get("aum",0)
                    aum_str = f"₹{indian_format(aum/1e7)}.Cr" if aum and aum > 1e7 else (f"₹{indian_format(aum)}" if aum else "")
                    hc  = st.columns([3,1.2,1,1.2,1.1,1.1,1.1,0.55])
                    hc[0].markdown(
                        f"<div style='font-weight:600;font-size:.84rem'>{m['name']}</div>"
                        f"<div style='font-size:.72rem;color:#8892AA'>{m.get('fund_house','')} {(' · AUM '+aum_str) if aum_str else ''}</div>",
                        unsafe_allow_html=True)
                    hc[1].markdown(f"<div style='font-size:.76rem;color:#8892AA'>{m.get('fund_house','')[:14]}</div>", unsafe_allow_html=True)
                    hc[2].markdown(f"<div style='font-size:.76rem;color:{rc};font-weight:600'>{rl}</div>", unsafe_allow_html=True)
                    hc[3].markdown(f"<div style='font-size:.9rem;font-weight:700'>₹{indian_format(m.get('nav',0))}</div>"
                                   f"<div style='font-size:.7rem;color:{cc}'>{'+' if chg>=0 else ''}{chg:.4f}%</div>", unsafe_allow_html=True)
                    hc[4].markdown(f"<div style='font-size:.84rem;font-weight:600;color:{'#2ECC7A' if r1y and r1y>=0 else '#FF5A5A'}'>{f'{r1y:+.1f}%' if r1y is not None else '—'}</div>", unsafe_allow_html=True)
                    hc[5].markdown(f"<div style='font-size:.84rem;font-weight:600;color:{'#2ECC7A' if r3y and r3y>=0 else '#FF5A5A'}'>{f'{r3y:+.1f}%' if r3y is not None else '—'}</div>", unsafe_allow_html=True)
                    hc[6].markdown(f"<div style='font-size:.82rem;color:#F5B731'>{f'{ter:.2f}%' if ter else '—'}</div>", unsafe_allow_html=True)
                    if hc[7].button("→", key=f"mfd_{m['symbol']}"):
                        st.session_state.selected_symbol = m["symbol"]; navigate("asset_detail")
                    st.markdown('<hr class="divider"/>', unsafe_allow_html=True)
