import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate, back_button
from utils.db import (get_client_advisors, get_advisor_clients, get_portfolios_for_ac,
                      get_private_portfolios, get_portfolio_holdings, get_transactions,
                      get_portfolio_by_id, add_holding, remove_holding,
                      get_assets, get_mutual_funds, get_fixed_income, get_commodities,
                      get_asset_price, submit_pending_asset, get_pending_assets_for_user,
                      rpc_holdings_with_prices, sb)
from utils.crypto import inr, fmt_date, indian_format
from datetime import date

ASSET_CLASSES = {
    "Equity":        {"sub":["Large Cap","Mid Cap","Small Cap"],                                      "unit":"shares"},
    "Mutual Fund":   {"sub":["Large Cap","Mid Cap","Small Cap","Flexi Cap","ELSS","Hybrid","Debt","Index"],"unit":"units"},
    "ETF":           {"sub":["Index ETF","Gold ETF","Sectoral ETF","Commodity ETF","Liquid ETF"],     "unit":"units"},
    "Bond":          {"sub":["Government Bond","PSU Bond","Corporate NCD","Sovereign Gold Bond","Small Savings"],"unit":"units"},
    "Bank FD":       {"sub":["Bank FD","Corporate FD"],                                               "unit":"amount"},
    "Commodity":     {"sub":["Precious Metal","Commodity"],                                           "unit":"grams"},
    "Crypto":        {"sub":["Large Cap Crypto","Mid Cap Crypto","Stablecoin","DeFi Token"],          "unit":"units"},
    "Real Estate":   {"sub":["Residential","Commercial","REITs","Land"],                              "unit":"amount"},
    "Physical Gold": {"sub":["Coins","Bars","Jewellery"],                                             "unit":"grams"},
    "Alternatives":  {"sub":["Private Equity","Venture Capital","Hedge Fund","Angel Investment"],     "unit":"amount"},
}

INTEREST_CLASSES = {"Bond","Bank FD"}
MANUAL_ONLY      = {"Crypto","Real Estate","Physical Gold","Alternatives"}

# Per-class placeholder text for manual entry
MANUAL_PLACEHOLDERS = {
    "Equity":        {"sym":"e.g. RELIANCE",      "name":"e.g. Reliance Industries Ltd",   "isin":"e.g. INE002A01018"},
    "Mutual Fund":   {"sym":"e.g. INF200K01884",  "name":"e.g. Axis Bluechip Fund Direct", "isin":""},
    "ETF":           {"sym":"e.g. NIFTYBEES",     "name":"e.g. Nippon India ETF Nifty BeES","isin":"e.g. INF204K01EY3"},
    "Bond":          {"sym":"e.g. SGB2023NOV5",   "name":"e.g. Sovereign Gold Bond 2023",  "isin":"e.g. IN0020210030"},
    "Bank FD":       {"sym":"e.g. HDFC-FD-2024",  "name":"e.g. HDFC Bank FD 7.25% 1Y",    "isin":""},
    "Commodity":     {"sym":"e.g. GOLDM",         "name":"e.g. Gold Mini MCX",              "isin":""},
    "Crypto":        {"sym":"e.g. BTC",           "name":"e.g. Bitcoin",                    "isin":""},
    "Real Estate":   {"sym":"e.g. PROP-MUM-001",  "name":"e.g. 2BHK Andheri West Mumbai",  "isin":""},
    "Physical Gold": {"sym":"e.g. PHYGOLD-001",   "name":"e.g. 24K Coins 10g SBI",         "isin":""},
    "Alternatives":  {"sym":"e.g. STARTUP-XYZ",  "name":"e.g. Series A XYZ Technologies", "isin":""},
}

ALT_PLACEHOLDERS = {
    "Crypto":       ("e.g. BTC",          "e.g. Bitcoin"),
    "Real Estate":  ("e.g. PROP-MUM-001", "e.g. 2BHK Andheri West Mumbai"),
    "Physical Gold":("e.g. PHYGOLD-001",  "e.g. 24K Gold Coins 10g"),
    "Alternatives": ("e.g. STARTUP-XYZ", "e.g. Series A XYZ Technologies"),
}

def _all_assets(ac):
    if ac == "Equity":        return [(d["symbol"],d["name"],None,None)       for d in get_assets("Equity")]
    if ac == "ETF":           return [(d["symbol"],d["name"],None,None)       for d in get_assets("ETF")]
    if ac == "Mutual Fund":   return [(m["symbol"],m["name"],None,None)       for m in get_mutual_funds()]
    if ac in INTEREST_CLASSES:return [(f["symbol"],f["name"],f.get("interest_rate"),f.get("tenure_years"))
                                       for f in get_fixed_income(ac)]
    if ac == "Commodity":     return [(c["symbol"],c["name"],None,None)       for c in get_commodities()]
    return []

def _search(pairs, q):
    if not q.strip(): return pairs[:30]
    ql = q.lower()
    return [p for p in pairs if ql in p[0].lower() or ql in p[1].lower()][:40]

def _collect_portfolios(user):
    pfs = []
    if user["role"] in ("advisor","owner"):
        for cl in get_advisor_clients(user["id"]):
            for pf in get_portfolios_for_ac(cl["id"]):
                pf["_label"] = f"{pf['name']}  [{cl['client_name']}]"; pfs.append(pf)
    else:
        for ac in get_client_advisors(user["id"]):
            for pf in get_portfolios_for_ac(ac["id"]):
                if pf["visibility"]=="shared" or (pf["visibility"]=="private" and pf.get("owner_type")=="client"):
                    pf["_label"] = pf["name"]; pfs.append(pf)
        for pf in get_private_portfolios(user["id"]):
            pf["_label"] = f"{pf['name']} (private)"; pfs.append(pf)
    return pfs

def render():
    if not st.session_state.get("user"):
        navigate("login"); return
    back_button(fallback="portfolios", key="top")
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
    can_edit = user["role"] in ("advisor","owner") or (pf["visibility"]=="private" and pf.get("owner_type")=="client")

    inv = sum(h["quantity"]*h["avg_cost"] for h in holdings)
    cur = sum(h["quantity"]*(get_asset_price(h["symbol"])[0] or h["avg_cost"]) for h in holdings)
    pnl = cur - inv; pnl_pct = (pnl/inv*100) if inv else 0

    st.markdown(f'<div class="page-title">📁 {pf["name"]}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="page-sub">{"🟢 Shared" if pf["visibility"]=="shared" else "🔒 Private"}</div>', unsafe_allow_html=True)
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
        rpc_h = rpc_holdings_with_prices(pf_id)
        if not rpc_h:
            rpc_h = []
            for h in holdings:
                p, chg = get_asset_price(h["symbol"])
                bv = h["quantity"]*h["avg_cost"]; cv = h["quantity"]*(p or h["avg_cost"])
                rpc_h.append({**h,"close_price":p,"change_pct":chg,"buy_value":bv,"current_value":cv,
                               "pnl":cv-bv,"pnl_pct":((p-h["avg_cost"])/h["avg_cost"]*100) if h["avg_cost"] else 0})
        if not rpc_h:
            st.info("No holdings yet.")
        else:
            cols_w = [2.5,1.2,1.2,1.5,1.5,2,0.5] if can_edit else [2.5,1.2,1.2,1.5,1.5,2]
            hdr    = st.columns(cols_w)
            for col,lbl in zip(hdr,["Symbol","Asset","Qty","Buy Cost","Closing Price","P&L"]+([""]*1 if can_edit else [])):
                col.markdown(f"<div style='font-size:.76rem;color:#8892AA;font-weight:600'>{lbl}</div>", unsafe_allow_html=True)
            st.markdown('<hr class="divider"/>', unsafe_allow_html=True)
            for h in rpc_h:
                p=h.get("close_price",0); chg=h.get("change_pct",0)
                hpnl=h.get("pnl",0); hpct=h.get("pnl_pct",0)
                pc="#2ECC7A" if hpnl>=0 else "#FF5A5A"; cc="#2ECC7A" if chg>=0 else "#FF5A5A"
                flag="⚠️ " if h.get("is_manual") and not h.get("is_verified") else ""
                hc=st.columns(cols_w)
                hc[0].markdown(f"<div style='font-weight:600;font-size:.88rem'>{flag}{h['symbol']}</div><div style='font-size:.76rem;color:#8892AA'>{h.get('sub_class','')}</div>", unsafe_allow_html=True)
                hc[1].markdown(f"<span class='badge badge-{h['asset_class'][:2].lower()}'>{h['asset_class'][:3]}</span>", unsafe_allow_html=True)
                hc[2].markdown(f"<div style='font-size:.84rem'>{h['quantity']:g} {h.get('unit_type','')}</div>", unsafe_allow_html=True)
                hc[3].markdown(f"<div style='font-size:.84rem'>₹{indian_format(h['avg_cost'])}</div>", unsafe_allow_html=True)
                hc[4].markdown(f"<div style='font-size:.84rem'>₹{indian_format(p)}</div><div style='font-size:.7rem;color:{cc}'>{chg:+.2f}%</div>", unsafe_allow_html=True)
                hc[5].markdown(f"<div style='color:{pc};font-weight:600;font-size:.84rem'>₹{indian_format(abs(hpnl))} ({hpct:+.1f}%)</div>", unsafe_allow_html=True)
                if can_edit:
                    if hc[6].button("🗑",key=f"rh_{h['id']}",help="Remove"): remove_holding(h["id"]); st.rerun()
                st.markdown('<hr class="divider"/>', unsafe_allow_html=True)

    # ── TRANSACTIONS ──────────────────────────────────────────────────────
    with tabs[1]:
        txns = get_transactions(pf_id)
        if not txns: st.info("No transactions yet.")
        for t in txns[:50]:
            tc="#2ECC7A" if t["txn_type"] in ("BUY","SIP") else "#FF5A5A"
            rc=st.columns([1,2,1.5,1.5,2,2])
            rc[0].markdown(f"<span style='color:{tc};font-weight:700;font-size:.88rem'>{t['txn_type']}</span>", unsafe_allow_html=True)
            rc[1].markdown(f"<span style='font-weight:600;font-size:.84rem'>{t['symbol']}</span>", unsafe_allow_html=True)
            rc[2].markdown(f"<span style='font-size:.88rem'>{t['quantity']:g}</span>", unsafe_allow_html=True)
            rc[3].markdown(f"<span style='font-size:.88rem'>@ ₹{indian_format(t['price'])}</span>", unsafe_allow_html=True)
            rc[4].markdown(f"<span style='font-weight:600'>₹{indian_format(t['amount'])}</span>", unsafe_allow_html=True)
            rc[5].markdown(f"<span style='font-size:.78rem;color:#8892AA'>{fmt_date(t.get('txn_date',''))}</span>", unsafe_allow_html=True)
            st.markdown('<hr class="divider"/>', unsafe_allow_html=True)

    if not can_edit: return

    # ── ADD ASSET ─────────────────────────────────────────────────────────
    with tabs[2]:
        st.markdown('<h4 style="margin:.3rem 0 .6rem 0">Add Asset</h4>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        ac    = c1.selectbox("Asset Class", list(ASSET_CLASSES.keys()), key="add_ac")
        utype = ASSET_CLASSES[ac]["unit"]

        # ── Manual-only asset classes (no DB feed) ────────────────────────
        if ac in MANUAL_ONLY:
            ph_sym, ph_name = ALT_PLACEHOLDERS.get(ac, ("e.g. ASSET-001","e.g. Asset Name"))
            sub = c2.selectbox("Sub-Category", ASSET_CLASSES[ac]["sub"], key="add_sub_alt")
            st.info(f"No live market feed for {ac}. Enter details manually.")
            with st.form(f"add_alt_{ac}"):
                sym   = st.text_input("Symbol / Identifier *", placeholder=ph_sym)
                mn    = st.text_input("Full Name / Description", placeholder=ph_name)
                if utype == "amount":
                    qty   = st.number_input("Amount Invested (₹)", min_value=0.01,
                                            step=1000.0, format="%.2f")
                    cost  = 1.0   # not shown; avg_cost=1 so value = amount
                elif utype == "grams":
                    qty   = st.number_input("Weight (grams)", min_value=0.001,
                                            step=0.1, format="%.3f")
                    cost  = st.number_input("Price per gram (₹)", min_value=0.01,
                                            step=100.0, format="%.2f")
                else:
                    qty   = st.number_input("Quantity / Units", min_value=0.001,
                                            step=1.0, format="%.4f")
                    cost  = st.number_input("Purchase Price per Unit (₹)", min_value=0.01,
                                            step=100.0, format="%.2f")
                notes = st.text_input("Notes (optional)")
                if st.form_submit_button("Add to Portfolio", use_container_width=True):
                    if not sym.strip(): st.error("Identifier required.")
                    elif qty <= 0: st.error("Quantity must be > 0.")
                    elif utype != "amount" and cost <= 0: st.error("Price must be > 0.")
                    else:
                        sb().table("holdings").insert({
                            "portfolio_id":pf_id,"symbol":sym.strip().upper(),"asset_class":ac,
                            "sub_class":sub,"quantity":float(qty),"unit_type":utype,
                            "avg_cost":cost,"notes":notes,"is_manual":True,"investment_type":"lump_sum",
                        }).execute()
                        st.success(f"Added {sym.strip().upper()}."); st.rerun()

        # ── DB-backed asset classes ────────────────────────────────────────
        else:
            all_pairs = _all_assets(ac)
            search_q  = c2.text_input("Search by ticker or name",
                                      placeholder="e.g. RELIANCE" if ac=="Equity" else
                                                  "e.g. Axis Bluechip" if ac=="Mutual Fund" else
                                                  "e.g. NIFTYBEES" if ac=="ETF" else "Search…",
                                      key="asset_search")
            filtered  = _search(all_pairs, search_q)
            sub_opts  = ASSET_CLASSES[ac]["sub"]

            if not filtered:
                st.warning("No matches. Try Manual Entry tab.")
            else:
                sym_opts  = [s for s,_,_,_ in filtered]
                sym_names = {s:n for s,n,_,_ in filtered}
                sym_rates = {s:r for s,_,r,_ in filtered}
                sym_ten   = {s:t for s,_,_,t in filtered}
                symbol    = st.selectbox("Asset", sym_opts,
                                         format_func=lambda x:f"{x}  ·  {sym_names.get(x,x)}",
                                         key="add_symbol")

                # Info card outside form so it always shows
                if ac in INTEREST_CLASSES:
                    rate   = sym_rates.get(symbol) or 0
                    tenure = sym_ten.get(symbol)
                    if rate:
                        st.markdown(f"""<div style="background:#1E2535;border:1px solid #2ECC7A;
                            border-radius:8px;padding:.65rem 1rem;margin:.35rem 0;font-size:.88rem">
                            <span style="color:#8892AA">Interest Rate: </span>
                            <span style="color:#2ECC7A;font-weight:700">{rate:.2f}% p.a.</span>
                            {'&nbsp;·&nbsp;<span style="color:#8892AA">Tenure: </span><span>' + str(tenure) + ' yr</span>' if tenure else ''}
                        </div>""", unsafe_allow_html=True)
                else:
                    cur_p, chg = get_asset_price(symbol)
                    if cur_p:
                        cc="#2ECC7A" if chg>=0 else "#FF5A5A"
                        st.markdown(f"""<div style="background:#1E2535;border:1px solid #252D40;
                            border-radius:8px;padding:.65rem 1rem;margin:.35rem 0;font-size:.88rem">
                            <span style="color:#8892AA">Closing Price: </span>
                            <span style="font-weight:700">₹{indian_format(cur_p)}</span>
                            &nbsp;<span style="color:{cc};font-size:.77rem">{chg:+.2f}%</span>
                        </div>""", unsafe_allow_html=True)

                with st.form("add_holding_form"):
                    # ── Interest rate for FD/Bond ──────────────────────────
                    if ac in INTEREST_CLASSES:
                        rate_val      = sym_rates.get(symbol) or 0.0
                        interest_rate = st.number_input("Interest Rate (% p.a.)",
                                                        value=float(rate_val),
                                                        min_value=0.0, step=0.05, format="%.2f")
                    else:
                        interest_rate = None

                    # ── SIP for Mutual Fund ────────────────────────────────
                    sip_mode=False; sip_frequency=None; sip_amount_val=0.0; sip_start=None
                    if ac == "Mutual Fund":
                        inv_type = st.radio("Investment Type",
                                            ["Lump Sum","SIP (Systematic Investment Plan)"],
                                            horizontal=True, key="mf_inv_type")
                        sip_mode = (inv_type == "SIP (Systematic Investment Plan)")
                        if sip_mode:
                            s1,s2 = st.columns(2)
                            sip_frequency  = s1.selectbox("Frequency",
                                                          ["Daily","Weekly","Monthly","Quarterly","Annual"], index=2)
                            sip_amount_val = s2.number_input("SIP Amount (₹)", min_value=100.0, step=500.0, value=1000.0)
                            sip_start      = st.date_input("SIP Start Date")
                            st.caption("Enter total units accumulated and weighted average NAV below.")

                    # ── Quantity / Amount ─────────────────────────────────
                    # Bank FD: utype=="amount" — ONE field: Amount Invested
                    # Showing both a qty field AND a cost field for FD is wrong.
                    # For FD: invested amount IS the "quantity", avg_cost = 1.0 (used as face value)
                    if utype == "amount":
                        # Single field — only Amount Invested
                        qty = st.number_input("Amount Invested (₹)",
                                              min_value=100.0, step=1000.0, value=10000.0, format="%.2f")
                        cost = 1.0   # stored as avg_cost = 1 so current_value = qty × 1 = amount
                    elif utype == "shares":
                        qty  = float(st.number_input("Quantity (shares)", min_value=1, step=1, value=1, format="%d"))
                        cost = st.number_input("Buy Price (₹)", min_value=0.01, step=1.0, format="%.2f")
                    elif utype == "grams":
                        qty  = st.number_input("Quantity (grams)", min_value=0.001, step=0.1, format="%.3f")
                        cost = st.number_input("Price per gram (₹)", min_value=0.01, step=1.0, format="%.2f")
                    else:
                        # units — MF, ETF, Bond
                        label_qty  = "Total Units Accumulated" if sip_mode else "Units"
                        label_cost = "Average NAV (₹)" if ac=="Mutual Fund" else "Buy Price / NAV (₹)"
                        qty  = st.number_input(label_qty,  min_value=0.001, step=0.001, format="%.3f")
                        cost = st.number_input(label_cost, min_value=0.01,  step=1.0,   format="%.2f")

                    notes = st.text_input("Notes (optional)")

                    if st.form_submit_button("Add to Portfolio", use_container_width=True):
                        if qty <= 0: st.error("Quantity must be > 0.")
                        elif utype != "amount" and cost <= 0: st.error("Price must be > 0.")
                        else:
                            note_str = notes
                            if interest_rate and interest_rate > 0:
                                note_str = f"rate:{interest_rate:.2f}%" + (f" | {notes}" if notes else "")
                            if sip_mode and sip_frequency:
                                note_str = f"sip:{sip_frequency.lower()}:₹{sip_amount_val:g}" + (f" | {notes}" if notes else "")
                            sub = next((d.get("sub_class","") for d in get_assets(ac)
                                        if d["symbol"]==symbol), sub_opts[0]) or sub_opts[0]
                            sb().table("holdings").insert({
                                "portfolio_id":pf_id,"symbol":symbol,"asset_class":ac,"sub_class":sub,
                                "quantity":float(qty),"unit_type":utype,"avg_cost":cost,
                                "notes":note_str,"is_manual":False,"investment_type":"sip" if sip_mode else "lump_sum",
                                "sip_frequency":sip_frequency.lower() if sip_mode and sip_frequency else None,
                                "sip_amount":sip_amount_val if sip_mode else 0,
                                "sip_start_date":str(sip_start) if sip_mode and sip_start else None,
                            }).execute()
                            sb().table("transactions").insert({
                                "portfolio_id":pf_id,"symbol":symbol,
                                "txn_type":"SIP" if sip_mode else "BUY",
                                "quantity":float(qty),"price":cost,"amount":float(qty)*cost,
                                "txn_date":str(sip_start) if sip_mode and sip_start else str(date.today()),
                            }).execute()
                            st.success(f"Added {'SIP — ' if sip_mode else ''}{qty:g} of {symbol}"); st.rerun()

    # ── MANUAL ENTRY ──────────────────────────────────────────────────────
    with tabs[3]:
        st.markdown('<h4 style="margin:.3rem 0 .6rem 0">Add Asset Not in Database</h4>', unsafe_allow_html=True)
        st.caption("Submitted assets are verified within 24 hours. Shown with ⚠️ until then.")

        # Class selector outside form so placeholders update immediately
        mac    = st.selectbox("Asset Class", list(ASSET_CLASSES.keys()), key="mac")
        msc    = st.selectbox("Sub-Category", ASSET_CLASSES[mac]["sub"], key="msc")
        mutype = ASSET_CLASSES[mac]["unit"]
        ph     = MANUAL_PLACEHOLDERS.get(mac, {"sym":"e.g. SYMBOL","name":"e.g. Asset Name","isin":""})

        with st.form("manual_holding"):
            ms = st.text_input("Symbol / Ticker *",  placeholder=ph["sym"])
            mn = st.text_input("Asset Name *",        placeholder=ph["name"])
            mi = st.text_input("ISIN (optional)",     placeholder=ph.get("isin",""))

            # Asset-class-specific extra fields
            if mac in INTEREST_CLASSES:
                c1m,c2m = st.columns(2)
                m_rate     = c1m.number_input("Interest Rate (% p.a.)", min_value=0.0, step=0.05, format="%.2f")
                m_tenure   = c2m.number_input("Tenure (years)", min_value=0.0, step=0.5, format="%.1f")
                m_maturity = st.text_input("Maturity Date (DD-MM-YYYY, optional)")
            else:
                m_rate = m_tenure = m_maturity = None

            # Quantity and cost — adapted per class
            if mutype == "amount":
                # FD/Real Estate/Alternatives — single amount field
                mq   = st.number_input("Amount Invested (₹)", min_value=100.0, step=1000.0, format="%.2f")
                mc   = 1.0  # avg_cost = 1 for amount-type assets
            elif mutype == "shares":
                mq   = float(st.number_input("Quantity (shares)", min_value=1, step=1, value=1, format="%d"))
                mc   = st.number_input("Buy Price (₹)", min_value=0.01, step=1.0, format="%.2f")
            elif mutype == "grams":
                mq   = st.number_input("Quantity (grams)", min_value=0.001, step=0.1, format="%.3f")
                mc   = st.number_input("Price per gram (₹)", min_value=0.01, step=1.0, format="%.2f")
            else:
                mq   = st.number_input("Units", min_value=0.001, step=0.001, format="%.3f")
                mc   = st.number_input("Buy Price / NAV (₹)", min_value=0.01, step=1.0, format="%.2f")

            mnotes = st.text_input("Notes (optional)", key="mnotes")

            if st.form_submit_button("Submit for Verification", use_container_width=True):
                if not ms.strip() or not mn.strip(): st.error("Symbol and name required.")
                elif mq <= 0: st.error("Quantity must be > 0.")
                elif mutype != "amount" and mc <= 0: st.error("Price must be > 0.")
                else:
                    note_str = mnotes
                    if m_rate: note_str = f"rate:{m_rate:.2f}%,tenure:{m_tenure}yr" + (f" | {mnotes}" if mnotes else "")
                    submit_pending_asset(user["id"], ms.strip().upper(), mn.strip(), mac, msc, mi)
                    sb().table("holdings").insert({
                        "portfolio_id":pf_id,"symbol":ms.strip().upper(),"asset_class":mac,
                        "sub_class":msc,"quantity":float(mq),"unit_type":mutype,
                        "avg_cost":mc,"notes":note_str,"is_manual":True,"investment_type":"lump_sum",
                    }).execute()
                    st.success(f"{ms.upper()} added with ⚠️ pending verification."); st.rerun()

    # ── PENDING ───────────────────────────────────────────────────────────
    with tabs[4]:
        pending = get_pending_assets_for_user(user["id"])
        if not pending: st.info("No pending verifications.")
        for pa in pending:
            sc={"pending":"#F5B731","verified":"#2ECC7A","rejected":"#FF5A5A"}.get(pa["status"],"#8892AA")
            with st.expander(f"{pa['symbol']}  ·  {pa['name']}"):
                st.markdown(f"**Status:** <span style='color:{sc}'>{pa['status'].upper()}</span><br>"
                            f"**Submitted:** {fmt_date(str(pa.get('submitted_at',''))[:10])}",
                            unsafe_allow_html=True)
    back_button(fallback="portfolios", label="← Back", key="bot")
