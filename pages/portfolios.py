import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate
from utils.db import (get_advisor_clients, get_client_advisors, get_portfolios_for_ac,
                      get_private_portfolios, get_portfolio_holdings, get_asset_price,
                      create_portfolio, update_portfolio, delete_portfolio)
from utils.crypto import inr, fmt_date, title_case, indian_format
from datetime import date
from collections import defaultdict

def _stats(holdings):
    inv = cur = 0.0
    for h in holdings:
        p, _ = get_asset_price(h["symbol"])
        inv += h["quantity"] * h["avg_cost"]
        cur += h["quantity"] * (p or h["avg_cost"])
    return inv, cur

def _alloc_bars(holdings, total_cur):
    class_vals = defaultdict(float)
    for h in holdings:
        p, _ = get_asset_price(h["symbol"])
        class_vals[h["asset_class"]] += h["quantity"] * (p or h["avg_cost"])
    colors = {"Equity":"#4F7EFF","Mutual Fund":"#A855F7","ETF":"#F5B731",
              "Bond":"#2ECC7A","Bank FD":"#14B8A6","Commodity":"#F97316"}
    tv   = total_cur or 1
    html = ""
    for cls, val in sorted(class_vals.items(), key=lambda x: -x[1]):
        pct = val / tv * 100
        c   = colors.get(cls, "#8892AA")
        html += (
            f'<div style="margin-bottom:.55rem">'
            f'<div style="display:flex;justify-content:space-between;margin-bottom:.22rem">'
            f'<span style="font-size:.76rem;color:#C8D0E0">{cls}</span>'
            f'<span style="font-size:.76rem;color:{c};font-weight:600">{pct:.0f}% · ₹{indian_format(val)}</span>'
            f'</div><div style="background:#1E2535;border-radius:3px;height:5px">'
            f'<div style="background:{c};width:{pct:.1f}%;height:100%;border-radius:3px"></div></div></div>'
        )
    return html

def _pf_card(pf, key_sfx, show_edit=True):
    hs       = get_portfolio_holdings(pf["id"])
    inv, cur = _stats(hs)
    pnl      = cur - inv
    pnl_pct  = (pnl / inv * 100) if inv else 0
    vis      = "🟢 Shared" if pf.get("visibility") == "shared" else "🔒 Private"

    with st.expander(f"📁  {pf['name']}  ·  ₹{indian_format(cur)}  ·  {vis}"):
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Invested",      inr(inv))
        m2.metric("Current Value", inr(cur))
        m3.metric("P&L",           inr(pnl), f"{pnl_pct:+.2f}%")
        m4.metric("Holdings",      len(hs))

        if hs:
            st.markdown(_alloc_bars(hs, cur), unsafe_allow_html=True)

        btn_cols = st.columns(4 if show_edit else 2)
        if btn_cols[0].button("📋 Holdings", key=f"h_{pf['id']}_{key_sfx}", use_container_width=True):
            st.session_state.selected_pf_id = pf["id"]; navigate("holdings")
        if btn_cols[1].button("📊 Analysis", key=f"a_{pf['id']}_{key_sfx}", use_container_width=True):
            st.session_state.selected_pf_id = pf["id"]; navigate("analysis")

        if show_edit:
            if btn_cols[2].button("✏️ Edit",   key=f"ep_{pf['id']}_{key_sfx}", use_container_width=True):
                st.session_state[f"editpf_{pf['id']}"] = True; st.rerun()
            if btn_cols[3].button("🗑 Delete", key=f"dp_{pf['id']}_{key_sfx}", use_container_width=True):
                st.session_state[f"delpf_{pf['id']}"] = True; st.rerun()

            if st.session_state.get(f"delpf_{pf['id']}"):
                st.error("Delete this portfolio and all its holdings?")
                y, n = st.columns(2)
                if y.button("Yes", key=f"yd_{pf['id']}", use_container_width=True):
                    delete_portfolio(pf["id"]); st.rerun()
                if n.button("No",  key=f"nd_{pf['id']}", use_container_width=True):
                    st.session_state.pop(f"delpf_{pf['id']}", None); st.rerun()

            if st.session_state.get(f"editpf_{pf['id']}"):
                with st.form(f"epf_{pf['id']}"):
                    en  = st.text_input("Name",        value=pf["name"])
                    ed  = st.text_input("Description",  value=pf.get("description", ""))
                    eg  = st.text_input("Goal",         value=pf.get("goal", ""))
                    c1, c2 = st.columns(2)
                    et  = c1.number_input("Target Amount (₹)", value=float(pf.get("target_amount", 0)), min_value=0.0)
                    etd = c2.date_input("Target Date")
                    ev  = st.selectbox("Visibility", ["shared", "private"],
                                       format_func=lambda x: "🟢 Shared" if x == "shared" else "🔒 Private",
                                       index=0 if pf.get("visibility") == "shared" else 1)
                    if st.form_submit_button("Save", use_container_width=True):
                        update_portfolio(pf["id"], en, ed, eg, et, str(etd), "NIFTY50")
                        st.session_state.pop(f"editpf_{pf['id']}", None); st.success("Saved!"); st.rerun()
                if st.button("Cancel", key=f"cepf_{pf['id']}"):
                    st.session_state.pop(f"editpf_{pf['id']}", None); st.rerun()

def _new_pf_form(ac_id, owner_id, owner_type, vis_opts, key_sfx):
    with st.form(f"new_pf_{key_sfx}"):
        n  = st.text_input("Portfolio Name *")
        d  = st.text_input("Description (optional)")
        g  = st.text_input("Goal (optional)", placeholder="e.g. Retirement by 2045")
        c1, c2 = st.columns(2)
        ta = c1.number_input("Target Amount (₹)", min_value=0.0, step=10000.0)
        td = c2.date_input("Target Date", value=date.today().replace(year=date.today().year + 10))
        vis = st.selectbox("Visibility", vis_opts,
                           format_func=lambda x: "🟢 Shared — advisor can see" if x == "shared" else "🔒 Private — only you")
        if st.form_submit_button("Create Portfolio", use_container_width=True):
            if not n.strip(): st.error("Name required.")
            else:
                create_portfolio(ac_id, owner_id, owner_type, n, d, g, ta, str(td), vis, "NIFTY50")
                st.success(f"'{n}' created!"); st.rerun()

def render():
    if not st.session_state.get("user"):
        navigate("login"); return
    user = st.session_state.user
    role = user["role"]
    st.markdown('<div class="page-title">Portfolios</div>', unsafe_allow_html=True)

    # ── ADVISOR ────────────────────────────────────────────────────────────
    if role == "advisor":
        clients = get_advisor_clients(user["id"])
        if not clients:
            st.info("No clients yet.")
            if st.button("Add Clients"): navigate("clients")
            return
        ac_map  = {c["id"]: title_case(c["client_name"]) for c in clients}
        sel     = st.session_state.get("selected_ac_id")
        default = list(ac_map.keys()).index(sel) if sel and sel in ac_map else 0
        ac_id   = st.selectbox("Client", list(ac_map.keys()), format_func=lambda x: ac_map[x], index=default)
        st.session_state.selected_ac_id = ac_id
        pfs     = get_portfolios_for_ac(ac_id)
        tab1, tab2 = st.tabs([f"  📁 Portfolios ({len(pfs)})  ", "  ➕ New Portfolio  "])
        with tab1:
            if not pfs: st.info("No portfolios for this client yet.")
            for pf in pfs: _pf_card(pf, "adv")
        with tab2:
            _new_pf_form(ac_id, user["id"], "advisor", ["shared", "private"], "adv")

    # ── CLIENT ─────────────────────────────────────────────────────────────
    else:
        advisors = get_client_advisors(user["id"])
        shared_pfs = []
        for ac in advisors:
            for pf in get_portfolios_for_ac(ac["id"], visibility="shared"):
                pf["_ac_id"] = ac["id"]
                shared_pfs.append(pf)
        priv_pfs = get_private_portfolios(user["id"])
        all_pfs  = shared_pfs + priv_pfs

        tab1, tab2 = st.tabs([f"  💼 My Portfolios ({len(all_pfs)})  ", "  ➕ New Private Portfolio  "])
        with tab1:
            if not all_pfs:
                st.info("No portfolios yet. Create a private one below, or ask your advisor to share one.")
            for pf in all_pfs:
                is_own = pf.get("visibility") == "private" and pf.get("owner_type") == "client"
                _pf_card(pf, "cli", show_edit=is_own)
        with tab2:
            st.caption("Private portfolios are visible only to you.")
            # Client can always create — with or without an advisor
            if advisors:
                ac_opts = {a["id"]: a.get("advisor_name", "Advisor") for a in advisors}
                ac_sel  = st.selectbox("Under Advisor", list(ac_opts.keys()),
                                       format_func=lambda x: ac_opts[x])
            else:
                ac_sel = None
                st.info("You have no linked advisor yet — portfolio will be fully private.")
            _new_pf_form(ac_sel, user["id"], "client", ["private"], "cli")
