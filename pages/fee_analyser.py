import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate, back_button
from utils.db import get_advisor_clients, get_portfolios_for_ac, get_portfolio_holdings, get_all_prices_map, get_invoices_for_advisor
from utils.crypto import inr, indian_format
from collections import defaultdict

FEE_FREQS = {"annual":"Annual","quarterly":"Quarterly","monthly":"Monthly","daily":"Daily"}

def _aum(ac_id, pmap):
    total = 0.0
    for pf in get_portfolios_for_ac(ac_id):
        for h in get_portfolio_holdings(pf["id"]):
            r = pmap.get(h["symbol"])
            p = r["close"] if r else 0.0
            total += h["quantity"] * (p or h["avg_cost"])
    return total

def _bar(label, val, max_val, color):
    pct = (val/max_val*100) if max_val else 0
    return f'<div style="margin-bottom:.9rem"><div style="display:flex;justify-content:space-between;margin-bottom:.3rem"><span style="font-size:.84rem;color:#F0F4FF">{label}</span><span style="font-size:.88rem;font-weight:700;color:{color}">₹{indian_format(val)}</span></div><div style="background:#1E2535;border-radius:5px;height:12px"><div style="background:{color};width:{pct:.1f}%;height:100%;border-radius:5px"></div></div></div>'

def render():
    if not st.session_state.get("user") or st.session_state.user["role"] not in ("advisor","owner"):
        navigate("login"); return
    back_button(fallback="profile", key="top")
    user = st.session_state.user
    clients  = get_advisor_clients(user["id"])
    invoices = get_invoices_for_advisor(user["id"])
    pmap     = get_all_prices_map()   # fetch once

    st.markdown('<div class="page-title">Fee Strategy Analyser</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Compare which fee model earns you the most</div>', unsafe_allow_html=True)

    if not clients:
        st.info("No clients yet."); return

    tab1, tab2 = st.tabs(["  📊 Model Comparison  ", "  💰 Actual Revenue  "])

    with tab1:
        st.markdown("#### Simulate All Three Fee Models Against Your Clients")
        st.caption("Adjust the assumptions below to project annual revenue.")
        c1,c2,c3 = st.columns(3)
        ot_fee    = c1.number_input("One-Time Fee per Client (₹)", value=25000.0, step=1000.0)
        cons_fee  = c2.number_input("Consultation Fee per Meeting (₹)", value=5000.0, step=500.0)
        avg_mtgs  = c2.number_input("Avg Meetings / Client / Year", value=4, min_value=1)
        mgmt_rate = c3.number_input("AUM Rate (% per annum)", value=1.0, step=0.1, format="%.2f")
        mgmt_freq = c3.selectbox("Applied As", list(FEE_FREQS.keys()), format_func=lambda x: FEE_FREQS[x])

        # Per-client data
        rows = []
        for cl in clients:
            aum   = _aum(cl["id"], pmap)
            ot    = ot_fee
            cons  = cons_fee * avg_mtgs
            freq_map = {"annual":1,"quarterly":4,"monthly":12,"daily":365}
            periods  = freq_map.get(mgmt_freq,12)
            rate_per = (mgmt_rate/100) / periods
            mgmt  = aum * rate_per * periods  # annualised
            rows.append({"id":cl["id"],"client":cl["client_name"],"aum":aum,
                          "ot":ot,"cons":cons,"mgmt":mgmt,
                          "best":max(ot,cons,mgmt),
                          "best_type":["ot","cons","mgmt"][[ot,cons,mgmt].index(max(ot,cons,mgmt))]})

        tot_ot   = sum(r["ot"]   for r in rows)
        tot_cons = sum(r["cons"] for r in rows)
        tot_mgmt = sum(r["mgmt"] for r in rows)
        tot_aum  = sum(r["aum"]  for r in rows)

        m1,m2,m3,m4 = st.columns(4)
        m1.metric("Total Client AUM", inr(tot_aum))
        m2.metric("One-Time (total)", inr(tot_ot))
        m3.metric("Consultation (annual)", inr(tot_cons))
        m4.metric("Management (annual)", inr(tot_mgmt))

        best_lbl = ["One-Time","Consultation","Management"][[tot_ot,tot_cons,tot_mgmt].index(max(tot_ot,tot_cons,tot_mgmt))]
        best_val = max(tot_ot, tot_cons, tot_mgmt)
        st.markdown(f"""
        <div style="background:linear-gradient(135deg,#161B27,#1E2535);border:1px solid #4F7EFF;border-radius:14px;padding:1.4rem;text-align:center;margin:1.2rem 0">
            <div style="font-size:.7rem;color:#8892AA;letter-spacing:.1em;text-transform:uppercase;margin-bottom:.4rem">Recommended Model</div>
            <div style="font-family:'Playfair Display',serif;font-size:1.8rem;color:#7BA3FF;margin-bottom:.3rem">{best_lbl}</div>
            <div style="font-size:1.2rem;font-weight:700;color:#2ECC7A">₹{indian_format(best_val)} projected annual revenue</div>
        </div>""", unsafe_allow_html=True)

        max_v = max(tot_ot, tot_cons, tot_mgmt) or 1
        st.markdown('<div style="background:#161B27;border:1px solid #252D40;border-radius:12px;padding:1.3rem 1.5rem;margin-bottom:1.5rem">', unsafe_allow_html=True)
        st.markdown(_bar("One-Time (non-recurring)",              tot_ot,   max_v, "#4F7EFF"), unsafe_allow_html=True)
        st.markdown(_bar(f"Consultation ({avg_mtgs} meetings/yr)", tot_cons, max_v, "#A855F7"), unsafe_allow_html=True)
        st.markdown(_bar(f"Management @ {mgmt_rate}% {FEE_FREQS[mgmt_freq]}", tot_mgmt, max_v, "#2ECC7A"), unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # Per-client table
        st.markdown("#### Per-Client Breakdown")
        hdr = st.columns([2.5,2,1.5,1.5,1.5,2])
        for col,lbl in zip(hdr,["Client","AUM","One-Time","Consultation","Management","Best Model"]):
            col.markdown(f"<div style='font-size:.76rem;color:#8892AA;font-weight:600'>{lbl}</div>", unsafe_allow_html=True)
        st.markdown('<hr class="divider"/>', unsafe_allow_html=True)
        type_colors = {"ot":"#4F7EFF","cons":"#A855F7","mgmt":"#2ECC7A"}
        type_labels = {"ot":"One-Time","cons":"Consultation","mgmt":"Management"}
        for r in sorted(rows, key=lambda x:-x["aum"]):
            rc = st.columns([2.5,2,1.5,1.5,1.5,2])
            rc[0].markdown(f"<div style='font-weight:600;font-size:.9rem'>{r['client']}</div>", unsafe_allow_html=True)
            rc[1].markdown(f"<div style='font-size:.84rem'>₹{indian_format(r['aum'])}</div>", unsafe_allow_html=True)
            rc[2].markdown(f"<div style='font-size:.84rem;color:#4F7EFF'>₹{indian_format(r['ot'])}</div>", unsafe_allow_html=True)
            rc[3].markdown(f"<div style='font-size:.84rem;color:#A855F7'>₹{indian_format(r['cons'])}</div>", unsafe_allow_html=True)
            rc[4].markdown(f"<div style='font-size:.84rem;color:#2ECC7A'>₹{indian_format(r['mgmt'])}</div>", unsafe_allow_html=True)
            bc = type_colors[r["best_type"]]; bl = type_labels[r["best_type"]]
            rc[5].markdown(f"<div style='color:{bc};font-weight:700;font-size:.84rem'>★ {bl}</div>", unsafe_allow_html=True)
            st.markdown('<hr class="divider"/>', unsafe_allow_html=True)

        # Insights
        st.markdown("#### Key Insights")
        if tot_mgmt >= max(tot_ot, tot_cons):
            st.markdown(f'<div class="card"><div class="card-title">📈 Management fees lead</div><p class="card-sub">At {mgmt_rate}% annual on ₹{indian_format(tot_aum)} AUM, management fees generate ₹{indian_format(tot_mgmt)}/year — the strongest model for your current book.</p></div>', unsafe_allow_html=True)
        elif tot_cons >= max(tot_ot, tot_mgmt):
            st.markdown(f'<div class="card"><div class="card-title">🤝 Consultation fees lead</div><p class="card-sub">{avg_mtgs} meetings/client/year at ₹{indian_format(cons_fee)}/meeting generates ₹{indian_format(tot_cons)}/year. Increase meeting frequency to grow revenue.</p></div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="card"><div class="card-title">💰 One-time fees total ₹{indian_format(tot_ot)}</div><p class="card-sub">Consider converting clients to recurring models for more sustainable income as AUM grows.</p></div>', unsafe_allow_html=True)

    with tab2:
        if not invoices: st.info("No invoices generated yet."); return
        by_type   = defaultdict(float)
        by_client = defaultdict(float)
        total_paid = total_unpaid = 0.0
        for inv in invoices:
            if inv["status"]=="paid":
                by_type[inv["fee_type"]] += inv["amount"]
                by_client[inv.get("client_name","Unknown")] += inv["amount"]
                total_paid += inv["amount"]
            else:
                total_unpaid += inv["amount"]

        m1,m2,m3 = st.columns(3)
        m1.metric("Collected", inr(total_paid))
        m2.metric("Outstanding", inr(total_unpaid))
        m3.metric("Total Invoiced", inr(total_paid+total_unpaid))

        type_labels = {"one_time":"One-Time","consultation":"Consultation","management":"Management"}
        type_colors = {"one_time":"#4F7EFF","consultation":"#A855F7","management":"#2ECC7A"}
        if by_type:
            st.markdown(""); st.markdown("**Collected by Fee Type**")
            mv = max(by_type.values()) or 1
            st.markdown('<div style="background:#161B27;border:1px solid #252D40;border-radius:12px;padding:1.2rem 1.4rem">', unsafe_allow_html=True)
            for k,v in sorted(by_type.items(), key=lambda x:-x[1]):
                st.markdown(_bar(type_labels.get(k,k), v, mv, type_colors.get(k,"#8892AA")), unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
        if by_client:
            st.markdown(""); st.markdown("**Collected by Client**")
            mv = max(by_client.values()) or 1
            st.markdown('<div style="background:#161B27;border:1px solid #252D40;border-radius:12px;padding:1.2rem 1.4rem">', unsafe_allow_html=True)
            for name,v in sorted(by_client.items(), key=lambda x:-x[1]):
                st.markdown(_bar(name, v, mv, "#4F7EFF"), unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
    back_button(fallback="profile", label="← Back", key="bot")
