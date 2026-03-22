import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate
from utils.db import (get_advisor_clients, rpc_advisor_dashboard,
                      rpc_client_dashboard, get_pending_requests_for_advisor)
from utils.crypto import inr, indian_format, fmt_date, title_case
from utils.market import is_market_open

def render():
    if not st.session_state.get("user"):
        navigate("login"); return

    user  = st.session_state.user
    role  = user["role"]
    name  = user.get("full_name") or user.get("username","")
    first = title_case(name.split()[0]) if name else "there"

    open_badge = (
        '<span style="color:#2ECC7A;font-size:.72rem;font-weight:600">● MARKET OPEN</span>'
        if is_market_open() else
        '<span style="color:#4E5A70;font-size:.72rem;font-weight:600">● MARKET CLOSED</span>'
    )
    st.markdown(f'<div class="page-title">Hello, {first}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="page-sub">Your wealth overview &nbsp;&nbsp;{open_badge}</div>', unsafe_allow_html=True)

    # ── ADVISOR ───────────────────────────────────────────────────────────
    if role == "advisor":
        # Single RPC call replaces all client+portfolio+holdings+price loops
        with st.spinner("Loading dashboard…"):
            rows    = rpc_advisor_dashboard(user["id"])
            pending = get_pending_requests_for_advisor(user["id"])

        total_aum = sum(r.get("total_aum",0) for r in rows)
        total_pfs = sum(r.get("portfolio_count",0) for r in rows)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Clients",                  len(rows))
        m2.metric("Total AUM",                inr(total_aum))
        m3.metric("Portfolios Managed",        total_pfs)
        m4.metric("Pending Meeting Requests",  len(pending))

        if pending:
            st.markdown("<br>", unsafe_allow_html=True)
            st.warning(f"🔔 {len(pending)} pending meeting request(s). Go to **Meetings** to respond.")

        st.markdown("<br>", unsafe_allow_html=True)
        b1, b2, b3, b4, b5 = st.columns(5)
        if b1.button("👥 Clients",   use_container_width=True): navigate("clients")
        if b2.button("📁 Portfolios",use_container_width=True): navigate("portfolios")
        if b3.button("📊 Analysis",  use_container_width=True): navigate("analysis")
        if b4.button("🗓 Meetings",  use_container_width=True): navigate("meetings")
        if b5.button("🧾 Invoices",  use_container_width=True): navigate("invoices")

        st.markdown("<br>", unsafe_allow_html=True)
        if rows:
            st.markdown('<div class="section-label">Clients</div>', unsafe_allow_html=True)
            hdr = st.columns([3, 2, 1.5, 2, 0.8])
            for col, lbl in zip(hdr, ["Client","Risk","Portfolios","AUM",""]):
                col.markdown(f"<div style='font-size:.7rem;color:#8892AA;font-weight:600'>{lbl}</div>", unsafe_allow_html=True)
            st.markdown('<hr class="divider"/>', unsafe_allow_html=True)
            for r in rows:
                pc = "#2ECC7A" if r.get("total_pnl",0)>=0 else "#FF5A5A"
                c1,c2,c3,c4,c5 = st.columns([3,2,1.5,2,0.8])
                c1.markdown(f"<div style='font-weight:600'>{title_case(r['client_name'])}</div><div style='font-size:.75rem;color:#8892AA'>{r.get('client_email','')}</div>", unsafe_allow_html=True)
                c2.markdown(f"<div style='font-size:.82rem;color:#8892AA;padding-top:.35rem'>{r.get('risk_profile','Moderate')}</div>", unsafe_allow_html=True)
                c3.markdown(f"<div style='font-size:.82rem;padding-top:.35rem'>{r.get('portfolio_count',0)}</div>", unsafe_allow_html=True)
                c4.markdown(f"<div style='font-weight:600;padding-top:.3rem'>{inr(r.get('total_aum',0))}</div><div style='font-size:.75rem;color:{pc}'>{inr(r.get('total_pnl',0))}</div>", unsafe_allow_html=True)
                if c5.button("→", key=f"dc_{r['client_id']}"):
                    st.session_state.selected_ac_id = r["client_id"]; navigate("portfolios")
                st.markdown('<hr class="divider"/>', unsafe_allow_html=True)
        else:
            st.info("No clients yet. Go to **Clients** to add your first client.")

    # ── CLIENT ────────────────────────────────────────────────────────────
    else:
        with st.spinner("Loading portfolio…"):
            rows = rpc_client_dashboard(user["id"])

        total_inv = sum(r.get("total_invested",0) for r in rows)
        total_cur = sum(r.get("total_current", 0) for r in rows)
        total_pnl = total_cur - total_inv
        total_pct = (total_pnl/total_inv*100) if total_inv else 0

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Invested",     inr(total_inv))
        m2.metric("Current Value",inr(total_cur))
        m3.metric("Total P&L",    inr(total_pnl), f"{total_pct:+.2f}%")
        m4.metric("Portfolios",   len(rows))

        st.markdown("<br>", unsafe_allow_html=True)
        b1, b2, b3 = st.columns(3)
        if b1.button("💼 My Portfolios", use_container_width=True): navigate("portfolios")
        if b2.button("📊 Markets",       use_container_width=True): navigate("market_equities")
        if b3.button("🗓 Meetings",      use_container_width=True): navigate("meetings")

        st.markdown("<br>", unsafe_allow_html=True)
        if rows:
            st.markdown('<div class="section-label">Portfolio Summary</div>', unsafe_allow_html=True)
            for r in rows:
                pf_pnl = r.get("total_pnl", 0)
                pf_pct = r.get("pnl_pct",   0)
                pc     = "#2ECC7A" if pf_pnl>=0 else "#FF5A5A"
                vis    = "🟢" if r.get("visibility")=="shared" else "🔒"
                c1, c2, c3, c4 = st.columns([3, 2, 2, 0.8])
                c1.markdown(f"<div style='font-weight:600'>{vis} {r['portfolio_name']}</div><div style='font-size:.75rem;color:#8892AA'>{r.get('holding_count',0)} holdings</div>", unsafe_allow_html=True)
                c2.markdown(f"<div style='padding-top:.3rem'>{inr(r.get('total_current',0))}</div>", unsafe_allow_html=True)
                c3.markdown(f"<div style='color:{pc};font-weight:600;padding-top:.3rem'>{inr(pf_pnl)} ({pf_pct:+.1f}%)</div>", unsafe_allow_html=True)
                if c4.button("→", key=f"dpf_{r['portfolio_id']}"):
                    st.session_state.selected_pf_id = r["portfolio_id"]; navigate("holdings")
                st.markdown('<hr class="divider"/>', unsafe_allow_html=True)
        elif not rows:
            st.info("No portfolios yet. Your advisor will share portfolios with you, or create a private one from the Portfolios page.")
