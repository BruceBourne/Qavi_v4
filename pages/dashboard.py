import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate
from utils.db import (get_advisor_clients, get_client_advisors, get_portfolios_for_ac,
                      get_portfolio_holdings, get_asset_price, get_indices,
                      get_pending_requests_for_advisor)
from utils.crypto import inr, fmt_date
from utils.market import is_market_open

def _aum(clients):
    total = 0.0
    for cl in clients:
        for pf in get_portfolios_for_ac(cl["id"]):
            for h in get_portfolio_holdings(pf["id"]):
                p, _ = get_asset_price(h["symbol"])
                total += h["quantity"] * (p or h["avg_cost"])
    return total

def render():
    if not st.session_state.get("user"):
        navigate("login"); return

    user = st.session_state.user
    role = user["role"]
    name = user.get("full_name") or user["username"]
    first = name.split()[0] if name else "there"
    indices = get_indices()

    # Market status badge
    open_badge = '<span style="color:#2ECC7A;font-size:.72rem;font-weight:600">● MARKET OPEN</span>' if is_market_open() else '<span style="color:#4E5A70;font-size:.72rem;font-weight:600">● MARKET CLOSED</span>'
    st.markdown(f'<div class="page-title">Hello, {title_case(first)}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="page-sub">Your wealth overview &nbsp;&nbsp;{open_badge}</div>', unsafe_allow_html=True)

    # ── INDEX STRIP ──────────────────────────────────────────────────────
    if indices:
        show = [i for i in indices if i["symbol"] not in ("INDIA_VIX",)][:5]
        ic = st.columns(len(show))
        for i, idx in enumerate(show):
            sign = "▲" if idx["change_pct"] >= 0 else "▼"
            cc = "idx-chg-u" if idx["change_pct"] >= 0 else "idx-chg-d"
            ic[i].markdown(f'<div class="idx-pill"><div class="idx-name">{idx["name"]}</div><div class="idx-val">{idx["value"]:,.2f}</div><div class="{cc}">{sign} {abs(idx["change_pct"]):.2f}%</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── ADVISOR VIEW ──────────────────────────────────────────────────────
    if role == "advisor":
        clients = get_advisor_clients(user["id"])
        pending = get_pending_requests_for_advisor(user["id"])
        total_aum = _aum(clients)
        total_pfs = sum(len(get_portfolios_for_ac(c["id"])) for c in clients)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Clients", len(clients))
        m2.metric("Total AUM", inr(total_aum))
        m3.metric("Portfolios Managed", total_pfs)
        m4.metric("Pending Meeting Requests", len(pending))

        if pending:
            st.markdown("<br>", unsafe_allow_html=True)
            st.warning(f"🔔 {len(pending)} pending meeting request(s). Go to **Meetings** to respond.")

        st.markdown("<br>", unsafe_allow_html=True)
        b1,b2,b3,b4,b5 = st.columns(5)
        if b1.button("👥 Clients", use_container_width=True): navigate("clients")
        if b2.button("📁 Portfolios", use_container_width=True): navigate("portfolios")
        if b3.button("📊 Analysis", use_container_width=True): navigate("analysis")
        if b4.button("🗓 Meetings", use_container_width=True): navigate("meetings")
        if b5.button("🧾 Invoices", use_container_width=True): navigate("invoices")

        st.markdown("<br>", unsafe_allow_html=True)
        if clients:
            st.markdown('<div class="section-label">Recent Clients</div>', unsafe_allow_html=True)
            for cl in clients[:5]:
                pfs = get_portfolios_for_ac(cl["id"])
                cl_val = 0.0
                for pf in pfs:
                    for h in get_portfolio_holdings(pf["id"]):
                        p, _ = get_asset_price(h["symbol"])
                        cl_val += h["quantity"] * (p or h["avg_cost"])
                c1,c2,c3,c4,c5 = st.columns([3,2,1.5,2,0.8])
                c1.markdown(f"<div style='font-weight:600'>{cl['client_name']}</div><div style='font-size:.75rem;color:#8892AA'>{cl.get('client_email','')}</div>", unsafe_allow_html=True)
                c2.markdown(f"<div style='font-size:.82rem;color:#8892AA;padding-top:.35rem'>{cl.get('risk_profile','Moderate')}</div>", unsafe_allow_html=True)
                c3.markdown(f"<div style='font-size:.82rem;color:#8892AA;padding-top:.35rem'>{len(pfs)} pf</div>", unsafe_allow_html=True)
                c4.markdown(f"<div style='font-weight:600;padding-top:.3rem'>{inr(cl_val)}</div>", unsafe_allow_html=True)
                if c5.button("→", key=f"dc_{cl['id']}"):
                    st.session_state.selected_ac_id = cl["id"]
                    navigate("portfolios")
                st.markdown('<hr class="divider"/>', unsafe_allow_html=True)
        else:
            st.info("No clients yet. Go to **Clients** to add your first client.")

    # ── CLIENT VIEW ───────────────────────────────────────────────────────
    else:
        advisors = get_client_advisors(user["id"])
        all_pfs = []
        total_inv = total_cur = 0.0
        for ac in advisors:
            for pf in get_portfolios_for_ac(ac["id"]):
                if pf["visibility"] == "shared" or (pf["visibility"] == "private" and pf.get("owner_type") == "client"):
                    pf["_ac"] = ac
                    all_pfs.append(pf)
                    for h in get_portfolio_holdings(pf["id"]):
                        p, _ = get_asset_price(h["symbol"])
                        total_inv += h["quantity"] * h["avg_cost"]
                        total_cur += h["quantity"] * (p or h["avg_cost"])

        total_pnl = total_cur - total_inv
        total_pnl_pct = (total_pnl / total_inv * 100) if total_inv else 0
        pnl_delta = f"{total_pnl_pct:+.2f}%"

        m1,m2,m3,m4 = st.columns(4)
        m1.metric("Invested", inr(total_inv))
        m2.metric("Current Value", inr(total_cur))
        m3.metric("Total P&L", inr(total_pnl), pnl_delta)
        m4.metric("Portfolios", len(all_pfs))

        st.markdown("<br>", unsafe_allow_html=True)
        b1,b2,b3 = st.columns(3)
        if b1.button("💼 My Portfolios", use_container_width=True): navigate("portfolios")
        if b2.button("📊 Markets", use_container_width=True): navigate("market_equities")
        if b3.button("🗓 Meetings", use_container_width=True): navigate("meetings")

        st.markdown("<br>", unsafe_allow_html=True)
        if all_pfs:
            st.markdown('<div class="section-label">Portfolio Summary</div>', unsafe_allow_html=True)
            for pf in all_pfs:
                hs = get_portfolio_holdings(pf["id"])
                pf_inv = sum(h["quantity"]*h["avg_cost"] for h in hs)
                pf_cur = sum(h["quantity"]*(get_asset_price(h["symbol"])[0] or h["avg_cost"]) for h in hs)
                pf_pnl = pf_cur - pf_inv
                pf_pct = (pf_pnl/pf_inv*100) if pf_inv else 0
                pc = "#2ECC7A" if pf_pnl >= 0 else "#FF5A5A"
                vis = "🟢" if pf["visibility"] == "shared" else "🔒"
                c1,c2,c3,c4 = st.columns([3,2,2,0.8])
                c1.markdown(f"<div style='font-weight:600'>{vis} {pf['name']}</div><div style='font-size:.75rem;color:#8892AA'>{len(hs)} holdings</div>", unsafe_allow_html=True)
                c2.markdown(f"<div style='padding-top:.3rem'>{inr(pf_cur)}</div>", unsafe_allow_html=True)
                c3.markdown(f"<div style='color:{pc};font-weight:600;padding-top:.3rem'>{inr(pf_pnl, show_sign=True)} ({pf_pct:+.1f}%)</div>", unsafe_allow_html=True)
                if c4.button("→", key=f"dpf_{pf['id']}"):
                    st.session_state.selected_pf_id = pf["id"]
                    navigate("holdings")
                st.markdown('<hr class="divider"/>', unsafe_allow_html=True)
        elif not advisors:
            st.info("You haven't been linked to an advisor yet. You can request a meeting with any registered advisor from the Meetings page.")

def title_case(s):
    return " ".join(w.capitalize() for w in (s or "").split())
