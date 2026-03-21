import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate
from utils.db import (get_client_advisors, get_advisor_clients, get_portfolios_for_ac,
                      get_private_portfolios, get_portfolio_holdings, get_transactions,
                      get_portfolio_by_id, add_holding, remove_holding,
                      get_assets, get_mutual_funds, get_fixed_income, get_commodities,
                      get_asset_price, submit_pending_asset, get_pending_assets_for_user)
from utils.crypto import inr, fmt_date, indian_format

ASSET_CLASSES = {
    "Equity":      {"sub":["Large Cap","Mid Cap","Small Cap"],                                     "unit":"shares"},
    "Mutual Fund": {"sub":["Large Cap","Mid Cap","Small Cap","Flexi Cap","ELSS","Hybrid","Debt","Index"],"unit":"units"},
    "ETF":         {"sub":["Index ETF","Gold ETF","Sectoral ETF","Commodity ETF","Liquid ETF"],    "unit":"units"},
    "Bond":        {"sub":["Government Bond","PSU Bond","Corporate NCD","Sovereign Gold Bond","Small Savings"],"unit":"units"},
    "Bank FD":     {"sub":["Bank FD","Corporate FD"],                                              "unit":"amount"},
    "Commodity":   {"sub":["Precious Metal","Commodity"],                                          "unit":"grams"},
}

def _all_assets_for_class(ac):
    """Return list of (symbol, name, interest_rate, tenure) for an asset class."""
    if ac == "Equity":
        return [(d["symbol"], d["name"], None, None) for d in get_assets("Equity")]
    if ac == "ETF":
        return [(d["symbol"], d["name"], None, None) for d in get_assets("ETF")]
    if ac == "Mutual Fund":
        return [(m["symbol"], m["name"], None, None) for m in get_mutual_funds()]
    if ac in ("Bond","Bank FD"):
        return [(f["symbol"], f["name"], f.get("interest_rate"), f.get("tenure_years"))
                for f in get_fixed_income(ac)]
    if ac == "Commodity":
        return [(c["symbol"], c["name"], None, None) for c in get_commodities()]
    return []

def _search_assets(pairs, query):
    """Filter (sym, name, rate, ten) list by query matching symbol or name."""
    q = query.strip().lower()
    if not q: return pairs[:30]          # show first 30 when empty
    return [p for p in pairs if q in p[0].lower() or q in p[1].lower()][:40]

def _collect_portfolios(user):
    pfs = []
    if user["role"] == "advisor":
        for cl in get_advisor_clients(user["id"]):
            for pf in get_portfolios_for_ac(cl["id"]):
                pf["_label"] = f"{pf['name']}  [{cl['client_name']}]"
                pfs.append(pf)
    else:
        for ac in get_client_advisors(user["id"]):
            for pf in get_portfolios_for_ac(ac["id"]):
                if pf["visibility"]=="shared" or (pf["visibility"]=="private" and pf.get("owner_type")=="client"):
                    pf["_label"] = pf["name"]
                    pfs.append(pf)
        for pf in get_private_portfolios(user["id"]):
            pf["_label"] = f"{pf['name']} (private)"
            pfs.append(pf)
    return pfs

def render():
    if not st.session_state.get("user"):
        navigate("login"); return
    user = st.session_state.user

    pfs = _collect_portfolios(user)
    if not pfs:
        st.info("No portfolios found.")
        if st.button("← Back"): navigate("portfolios")
        return

    pf_map  = {p["id"]: p.get("_label", p["name"]) for p in pfs}
    sel_id  = st.session_state.get("selected_pf_id")
    default = list(pf_map.keys()).index(sel_id) if sel_id and sel_id in pf_map else 0
    pf_id   = st.selectbox("Portfolio", list(pf_map.keys()), format_func=lambda x: pf_map[x], index=default)
    st.session_state.selected_pf_id = pf_id

    pf = get_portfolio_by_id(pf_id)
    if not pf: st.error("Portfolio not found."); return
    holdings = get_portfolio_holdings(pf_id)
    can_edit = user["role"]=="advisor" or (pf["visibility"]=="private" and pf.get("owner_type")=="client")

    inv = sum(h["quantity"]*h["avg_cost"] for h in holdings)
    cur = sum(h["quantity"]*(get_asset_price(h["symbol"])[0] or h["avg_cost"]) for h in holdings)
    pnl = cur - inv; pnl_pct = (pnl/inv*100) if inv else 0

    st.markdown(f'<div class="page-title">📁 {pf["name"]}</div>', unsafe_allow_html=True)
    vis = "🟢 Shared" if pf["visibility"]=="shared" else "🔒 Private"
    st.markdown(f'<div class="page-sub">{vis}</div>', unsafe_allow_html=True)

    m1,m2,m3,m4 = st.columns(4)
    m1.metric("Invested",      inr(inv))
    m2.metric("Current Value", inr(cur))
    m3.metric("P&L",           inr(pnl), f"{pnl_pct:+.2f}%")
    m4.metric("Holdings",      len(holdings))

    tabs_list = ["  📋 Holdings  ","  📜 Transactions  "]
    if can_edit: tabs_list += ["  ➕ Add Asset  ","  🔧 Manual Entry  ","  ⏳ Pending  "]
    tabs = st.tabs(tabs_list)

    # ── HOLDINGS ──────────────────────────────────────────────────────────
    with tabs[0]:
        if not holdings:
            st.info("No holdings yet.")
        else:
            hdr = st.columns([2.5,1.2,1.2,1.5,1.5,2,0.5] if can_edit else [2.5,1.2,1.2,1.5,1.5,2])
            for col,lbl in zip(hdr,["Symbol","Asset","Qty","Buy Cost","Closing Price","P&L"]+([""]*1 if can_edit else [])):
                col.markdown(f"<div style='font-size:.7rem;color:#8892AA;font-weight:600'>{lbl}</div>", unsafe_allow_html=True)
            st.markdown('<hr class="divider"/>', unsafe_allow_html=True)
            for h in sorted(holdings, key=lambda x: -(get_asset_price(x["symbol"])[0]*x["quantity"])):
                p, chg = get_asset_price(h["symbol"])
                hpnl   = (p-h["avg_cost"])*h["quantity"]
                hpct   = ((p-h["avg_cost"])/h["avg_cost"]*100) if h["avg_cost"] else 0
                pc     = "#2ECC7A" if hpnl>=0 else "#FF5A5A"
                cc     = "#2ECC7A" if chg>=0  else "#FF5A5A"
                flag   = "⚠️ " if h.get("is_manual") and not h.get("is_verified") else ""
                hc = st.columns([2.5,1.2,1.2,1.5,1.5,2,0.5] if can_edit else [2.5,1.2,1.2,1.5,1.5,2])
                hc[0].markdown(f"<div style='font-weight:600;font-size:.88rem'>{flag}{h['symbol']}</div><div style='font-size:.72rem;color:#8892AA'>{h.get('sub_class','')}</div>", unsafe_allow_html=True)
                hc[1].markdown(f"<span class='badge badge-{h['asset_class'][:2].lower()}'>{h['asset_class'][:3]}</span>", unsafe_allow_html=True)
                hc[2].markdown(f"<div style='font-size:.84rem'>{h['quantity']:g} {h.get('unit_type','')}</div>", unsafe_allow_html=True)
                hc[3].markdown(f"<div style='font-size:.84rem'>₹{indian_format(h['avg_cost'])}</div>", unsafe_allow_html=True)
                hc[4].markdown(f"<div style='font-size:.84rem'>₹{indian_format(p)}</div><div style='font-size:.7rem;color:{cc}'>{chg:+.2f}%</div>", unsafe_allow_html=True)
                hc[5].markdown(f"<div style='color:{pc};font-weight:600;font-size:.84rem'>₹{indian_format(abs(hpnl))} ({hpct:+.1f}%)</div>", unsafe_allow_html=True)
                if can_edit:
                    if hc[6].button("🗑", key=f"rh_{h['id']}", help="Remove"): remove_holding(h["id"]); st.rerun()
                st.markdown('<hr class="divider"/>', unsafe_allow_html=True)

    # ── TRANSACTIONS ──────────────────────────────────────────────────────
    with tabs[1]:
        txns = get_transactions(pf_id)
        if not txns: st.info("No transactions yet.")
        for t in txns[:50]:
            tc = "#2ECC7A" if t["txn_type"]=="BUY" else "#FF5A5A"
            rc = st.columns([1,2,1.5,1.5,2,2])
            rc[0].markdown(f"<span style='color:{tc};font-weight:700;font-size:.82rem'>{t['txn_type']}</span>", unsafe_allow_html=True)
            rc[1].markdown(f"<span style='font-weight:600;font-size:.84rem'>{t['symbol']}</span>", unsafe_allow_html=True)
            rc[2].markdown(f"<span style='font-size:.82rem'>{t['quantity']:g} units</span>", unsafe_allow_html=True)
            rc[3].markdown(f"<span style='font-size:.82rem'>@ ₹{indian_format(t['price'])}</span>", unsafe_allow_html=True)
            rc[4].markdown(f"<span style='font-weight:600'>₹{indian_format(t['amount'])}</span>", unsafe_allow_html=True)
            rc[5].markdown(f"<span style='font-size:.78rem;color:#8892AA'>{fmt_date(t.get('txn_date',''))}</span>", unsafe_allow_html=True)
            st.markdown('<hr class="divider"/>', unsafe_allow_html=True)

    if not can_edit: return

    # ── ADD ASSET ─────────────────────────────────────────────────────────
    # Asset class and search are OUTSIDE the form — refresh immediately on change
    with tabs[2]:
        st.markdown("#### Add Asset")

        c1, c2 = st.columns(2)
        ac   = c1.selectbox("Asset Class", list(ASSET_CLASSES.keys()), key="add_ac")
        utype = ASSET_CLASSES[ac]["unit"]

        # All assets for chosen class
        all_pairs = _all_assets_for_class(ac)

        # Searchable text input — matches ticker AND company name
        search_q = c2.text_input(
            "Search by ticker or name",
            placeholder="e.g. RELIANCE or Tata Motors",
            key="asset_search"
        )
        filtered = _search_assets(all_pairs, search_q)

        if not filtered:
            st.warning("No matches. Try a different search term, or use Manual Entry.")
        else:
            sym_opts  = [s for s,_,_,_ in filtered]
            sym_names = {s:n for s,n,_,_ in filtered}
            sym_rates = {s:r for s,_,r,_ in filtered}
            sym_ten   = {s:t for s,_,_,t in filtered}

            symbol = st.selectbox(
                "Select Asset",
                sym_opts,
                format_func=lambda x: f"{x}  ·  {sym_names.get(x,x)}",
                key="add_symbol"
            )

            # Show price / interest rate info OUTSIDE form so it's always visible
            if ac in ("Bond","Bank FD"):
                rate   = sym_rates.get(symbol)
                tenure = sym_ten.get(symbol)
                if rate:
                    st.markdown(f"""
                    <div style="background:#1E2535;border:1px solid #2ECC7A;border-radius:8px;
                        padding:.65rem 1rem;margin:.35rem 0;font-size:.82rem">
                        <span style="color:#8892AA">Interest Rate: </span>
                        <span style="color:#2ECC7A;font-weight:700">{rate:.2f}% p.a.</span>
                        {'&nbsp;·&nbsp;<span style="color:#8892AA">Tenure: </span><span style="color:#F0F4FF">' + str(tenure) + ' yr</span>' if tenure else ''}
                    </div>""", unsafe_allow_html=True)
            else:
                cur_p, chg = get_asset_price(symbol)
                if cur_p:
                    cc = "#2ECC7A" if chg>=0 else "#FF5A5A"
                    st.markdown(f"""
                    <div style="background:#1E2535;border:1px solid #252D40;border-radius:8px;
                        padding:.65rem 1rem;margin:.35rem 0;font-size:.82rem">
                        <span style="color:#8892AA">Closing Price: </span>
                        <span style="font-weight:700">₹{indian_format(cur_p)}</span>
                        &nbsp;<span style="color:{cc};font-size:.77rem">{chg:+.2f}%</span>
                    </div>""", unsafe_allow_html=True)

            with st.form("add_holding_form"):
                if ac in ("Bond","Bank FD"):
                    rate_val = sym_rates.get(symbol) or 0.0
                    interest_rate = st.number_input(
                        "Interest Rate (% p.a.)",
                        value=float(rate_val), min_value=0.0, step=0.05, format="%.2f"
                    )
                else:
                    interest_rate = None

                if utype == "shares":
                    qty = float(st.number_input("Quantity (shares)", min_value=1, step=1, value=1, format="%d"))
                elif utype == "amount":
                    qty = st.number_input("Amount Invested (₹)", min_value=100.0, step=500.0)
                elif utype == "grams":
                    qty = st.number_input("Quantity (grams)", min_value=0.01, step=0.1, format="%.2f")
                else:
                    qty = st.number_input("Units", min_value=0.001, step=0.001, format="%.3f")

                avg_cost = st.number_input(
                    "Investment Amount (₹)" if utype=="amount" else "Buy Price / NAV (₹)",
                    min_value=0.01, step=1.0, format="%.2f"
                )
                notes = st.text_input("Notes (optional)")

                if st.form_submit_button("Add to Portfolio", use_container_width=True):
                    if qty <= 0 or avg_cost <= 0:
                        st.error("Quantity and price must be positive.")
                    else:
                        note_str = notes
                        if interest_rate is not None and interest_rate > 0:
                            note_str = f"rate:{interest_rate:.2f}%" + (f" | {notes}" if notes else "")
                        # Use sub-category from the selected asset
                        sub = next((d.get("sub_class","") for d in get_assets(ac) if d["symbol"]==symbol), ASSET_CLASSES[ac]["sub"][0])
                        add_holding(pf_id, symbol, ac, sub, float(qty), utype, avg_cost, note_str)
                        st.success(f"Added {qty:g} of {symbol}"); st.rerun()

    # ── MANUAL ENTRY ──────────────────────────────────────────────────────
    with tabs[3]:
        st.markdown("#### Add Asset Not in Database")
        with st.form("manual_holding"):
            ms  = st.text_input("Symbol / Ticker *")
            mn  = st.text_input("Asset Name *")
            mac = st.selectbox("Asset Class", list(ASSET_CLASSES.keys()), key="mac")
            msc = st.selectbox("Sub-Category", ASSET_CLASSES[mac]["sub"], key="msc")
            mi  = st.text_input("ISIN (optional)")
            mut = ASSET_CLASSES[mac]["unit"]
            if mut == "shares":
                mq = float(st.number_input("Shares", min_value=1, step=1, value=1, format="%d", key="mq"))
            elif mut == "amount":
                mq = st.number_input("Amount (₹)", min_value=100.0, step=500.0, key="mq")
            elif mut == "grams":
                mq = st.number_input("Grams", min_value=0.01, step=0.1, format="%.2f", key="mq")
            else:
                mq = st.number_input("Units", min_value=0.001, step=0.001, format="%.3f", key="mq")
            mc_price = st.number_input("Buy Price (₹)", min_value=0.01, step=1.0, format="%.2f")
            mnotes   = st.text_input("Notes (optional)", key="mnotes")
            if st.form_submit_button("Submit for Verification", use_container_width=True):
                if not ms.strip() or not mn.strip():
                    st.error("Symbol and name required.")
                elif mq <= 0 or mc_price <= 0:
                    st.error("Quantity and price must be positive.")
                else:
                    submit_pending_asset(user["id"], ms.strip().upper(), mn.strip(), mac, msc, mi)
                    add_holding(pf_id, ms.strip().upper(), mac, msc, float(mq), mut, mc_price, mnotes, is_manual=True)
                    st.success(f"{ms.upper()} added with ⚠️ — pending verification."); st.rerun()

    # ── PENDING ───────────────────────────────────────────────────────────
    with tabs[4]:
        pending = get_pending_assets_for_user(user["id"])
        if not pending: st.info("No pending verifications.")
        for pa in pending:
            sc = {"pending":"#F5B731","verified":"#2ECC7A","rejected":"#FF5A5A"}.get(pa["status"],"#8892AA")
            with st.expander(f"{pa['symbol']}  ·  {pa['name']}"):
                st.markdown(f"**Status:** <span style='color:{sc}'>{pa['status'].upper()}</span><br>**Submitted:** {fmt_date(str(pa.get('submitted_at',''))[:10])}", unsafe_allow_html=True)
