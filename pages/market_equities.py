import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate
from utils.db import get_assets, get_all_prices_map
from utils.crypto import indian_format
from collections import defaultdict

PAGE_SIZE = 100

def _row(a, prices, key_sfx):
    p    = prices.get(a["symbol"], {})
    cl   = p.get("close", 0); chg = p.get("change_pct", 0)
    cc   = "#2ECC7A" if chg >= 0 else "#FF5A5A"
    sign = "▲" if chg >= 0 else "▼"
    sector = a.get("sector","") or "—"
    hc   = st.columns([2.5, 1.8, 1.2, 1.2, 1.5, 1.8, 0.6])
    hc[0].markdown(
        f"<div style='font-weight:600;font-size:.9rem'>{a['symbol']}</div>"
        f"<div style='font-size:.7rem;color:#8892AA'>{a['name']}</div>",
        unsafe_allow_html=True)
    hc[1].markdown(
        f"<div style='font-size:.76rem;color:#8892AA'>{sector}</div>",
        unsafe_allow_html=True)
    hc[2].markdown(f"<div style='font-size:.88rem'>₹{indian_format(p.get('open',0))}</div>", unsafe_allow_html=True)
    hc[3].markdown(
        f"<div style='font-size:.78rem;color:#2ECC7A'>₹{indian_format(p.get('high',0))}</div>"
        f"<div style='font-size:.75rem;color:#FF5A5A'>₹{indian_format(p.get('low',0))}</div>",
        unsafe_allow_html=True)
    hc[4].markdown(f"<div style='font-size:.95rem;font-weight:700'>₹{indian_format(cl)}</div>", unsafe_allow_html=True)
    hc[5].markdown(f"<div style='color:{cc};font-weight:700;font-size:.9rem'>{sign} {abs(chg):.2f}%</div>", unsafe_allow_html=True)
    if hc[6].button("→", key=f"det_{a['symbol']}_{key_sfx}"):
        st.session_state.selected_symbol = a["symbol"]; navigate("asset_detail")
    st.markdown('<hr class="divider"/>', unsafe_allow_html=True)

def render():
    st.markdown('<div class="page-title">Equities</div>', unsafe_allow_html=True)

    b1, b2, b3, b4, b5 = st.columns(5)
    if b1.button("Equities",         use_container_width=True): pass
    if b2.button("Mutual Funds",      use_container_width=True): navigate("market_mf")
    if b3.button("ETFs",              use_container_width=True): navigate("market_etf")
    if b4.button("Bonds",             use_container_width=True): navigate("market_bonds")
    if b5.button("FDs & Commodities", use_container_width=True): navigate("market_fd")
    st.markdown("<br>", unsafe_allow_html=True)

    search = st.text_input("🔍 Search", placeholder="Symbol, company name or sector…",
                            label_visibility="collapsed", key="eq_search")

    prices = get_all_prices_map()
    assets = get_assets("Equity", search=search if search else None)

    # Also filter by sector if search matches a sector name
    if search:
        sq = search.lower()
        # Include assets where sector matches even if symbol/name don't
        sector_matches = [a for a in get_assets("Equity")
                          if sq in (a.get("sector","") or "").lower()
                          and a not in assets]
        assets = assets + sector_matches

    by_sub = defaultdict(list)
    for a in assets:
        sub = a.get("sub_class","") or "Other"
        by_sub[sub].append(a)

    known_order = ["Large Cap","Mid Cap","Small Cap"]
    extra       = sorted(k for k in by_sub if k not in known_order)
    all_subs    = [s for s in known_order if s in by_sub] + extra

    if not assets:
        st.info("No equities found. Upload bhavcopy data from Profile → Update Market Data.")
        return

    hdr = st.columns([2.5, 1.8, 1.2, 1.2, 1.5, 1.8, 0.6])
    for col, lbl in zip(hdr, ["Symbol", "Sector", "Open", "High / Low", "LTP", "Change", ""]):
        col.markdown(f"<div style='font-size:.76rem;color:#8892AA;font-weight:600'>{lbl}</div>",
                     unsafe_allow_html=True)
    st.markdown('<hr class="divider"/>', unsafe_allow_html=True)

    for sub in all_subs:
        items = by_sub.get(sub, [])
        if not items: continue

        page_key  = f"eq_page_{sub}"
        if page_key not in st.session_state:
            st.session_state[page_key] = 0
        cur_page   = st.session_state[page_key]
        n_pages    = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
        page_items = items[cur_page * PAGE_SIZE : (cur_page + 1) * PAGE_SIZE]

        with st.expander(
            f"**{sub}** — {len(items):,} stocks  "
            f"(showing {cur_page*PAGE_SIZE+1}–{min((cur_page+1)*PAGE_SIZE,len(items))})",
            expanded=(sub == "Large Cap" and not search)
        ):
            for a in page_items:
                _row(a, prices, f"{sub}_{cur_page}")

            if n_pages > 1:
                pc1, pc2, pc3 = st.columns([1, 3, 1])
                if pc1.button("← Prev", key=f"prev_{sub}", disabled=(cur_page==0),
                              use_container_width=True):
                    st.session_state[page_key] = cur_page - 1; st.rerun()
                pc2.markdown(
                    f'<div style="text-align:center;font-size:.8rem;color:#8892AA;padding:.5rem 0">'
                    f'Page {cur_page+1} of {n_pages}</div>',
                    unsafe_allow_html=True)
                if pc3.button("Next →", key=f"next_{sub}", disabled=(cur_page>=n_pages-1),
                              use_container_width=True):
                    st.session_state[page_key] = cur_page + 1; st.rerun()
