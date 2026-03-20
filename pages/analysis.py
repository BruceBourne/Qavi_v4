import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate
from utils.db import (get_advisor_clients, get_client_advisors, get_portfolios_for_ac,
                      get_private_portfolios, get_portfolio_holdings, get_asset_price, get_indices)
from utils.crypto import inr, indian_format
from collections import defaultdict
import math

def _stats(holdings):
    inv = cur = 0.0
    for h in holdings:
        p, _ = get_asset_price(h["symbol"])
        inv += h["quantity"] * h["avg_cost"]
        cur += h["quantity"] * (p or h["avg_cost"])
    return inv, cur

def _bar(label, val, total, color="#4F7EFF", show_val=True):
    pct = (val/total*100) if total else 0
    val_str = f"₹{indian_format(val)} · {pct:.1f}%" if show_val else f"{pct:.1f}%"
    return f"""<div class="stat-bar-row">
      <div class="stat-bar-label">
        <span style="font-size:.82rem;color:#F0F4FF">{label}</span>
        <span style="font-size:.82rem;color:{color};font-weight:600">{val_str}</span>
      </div>
      <div class="stat-bar-bg"><div class="stat-bar-fill" style="background:{color};width:{pct:.1f}%"></div></div>
    </div>"""

def render():
    if not st.session_state.get("user"):
        navigate("login"); return
    user = st.session_state.user
    role = user["role"]
    indices = get_indices()

    st.markdown('<div class="page-title">Analysis</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Portfolio analytics — allocation, P&L, benchmarks</div>', unsafe_allow_html=True)

    # Collect portfolios
    all_pfs = []
    if role == "advisor":
        clients = get_advisor_clients(user["id"])
        if not clients: st.info("No clients yet."); return
        ac_map  = {c["id"]: c["client_name"] for c in clients}
        sel_ac  = st.session_state.get("selected_ac_id")
        default = list(ac_map.keys()).index(sel_ac) if sel_ac and sel_ac in ac_map else 0
        ac_id   = st.selectbox("Client", list(ac_map.keys()), format_func=lambda x: ac_map[x], index=default)
        st.session_state.selected_ac_id = ac_id
        all_pfs = get_portfolios_for_ac(ac_id)
    else:
        for ac in get_client_advisors(user["id"]):
            for pf in get_portfolios_for_ac(ac["id"]):
                if pf["visibility"]=="shared" or (pf["visibility"]=="private" and pf.get("owner_type")=="client"):
                    all_pfs.append(pf)
        for pf in get_private_portfolios(user["id"]):
            all_pfs.append(pf)

    if not all_pfs: st.info("No portfolios found."); return

    pf_opts  = [("all","📊 All Portfolios Combined")] + [(p["id"],p["name"]) for p in all_pfs]
    sel_pf   = st.selectbox("Portfolio", [x[0] for x in pf_opts], format_func=lambda x: dict(pf_opts)[x])

    holdings = []
    bench_sym = "NIFTY50"
    if sel_pf == "all":
        for pf in all_pfs:
            holdings.extend(get_portfolio_holdings(pf["id"]))
    else:
        holdings = get_portfolio_holdings(sel_pf)
        pf_obj   = next((p for p in all_pfs if p["id"]==sel_pf), None)
        if pf_obj: bench_sym = pf_obj.get("benchmark","NIFTY50")

    if not holdings: st.info("No holdings in this selection."); return

    inv, cur = _stats(holdings)
    pnl = cur - inv; pnl_pct = (pnl/inv*100) if inv else 0

    m1,m2,m3,m4 = st.columns(4)
    m1.metric("Invested",      inr(inv))
    m2.metric("Current Value", inr(cur))
    m3.metric("P&L",           inr(pnl), f"{pnl_pct:+.2f}%")
    bench = next((i for i in indices if i["symbol"]==bench_sym), None)
    if bench:
        m4.metric(f"Benchmark · {bench['name']}", f"{bench['value']:,.2f}", f"{bench['change_pct']:+.2f}%")

    st.markdown("<br>", unsafe_allow_html=True)
    tab1,tab2,tab3,tab4 = st.tabs(["  🥧 Allocation  ","  📋 Holdings P&L  ","  📈 Benchmark  ","  🔀 Cross-Portfolio  "])

    colors = {"Equity":"#4F7EFF","Mutual Fund":"#A855F7","ETF":"#F5B731",
              "Bond":"#2ECC7A","Bank FD":"#14B8A6","Commodity":"#F97316"}

    with tab1:
        class_vals  = defaultdict(float)
        sector_vals = defaultdict(float)
        for h in holdings:
            p,_ = get_asset_price(h["symbol"])
            v   = h["quantity"]*(p or h["avg_cost"])
            class_vals[h["asset_class"]]       += v
            sector_vals[h.get("sub_class","?")] += v

        st.markdown("#### By Asset Class")
        st.markdown('<div class="stat-bar-wrap">', unsafe_allow_html=True)
        for cls, val in sorted(class_vals.items(), key=lambda x:-x[1]):
            st.markdown(_bar(cls, val, cur, colors.get(cls,"#8892AA")), unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<br>#### By Sub-Category")
        st.markdown('<div class="stat-bar-wrap">', unsafe_allow_html=True)
        for sub, val in sorted(sector_vals.items(), key=lambda x:-x[1])[:12]:
            st.markdown(_bar(sub, val, cur, "#4F7EFF"), unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with tab2:
        hdr = st.columns([2.5,1.5,1.2,1.5,1.5,2,1.5])
        for col,lbl in zip(hdr,["Symbol","Asset","Qty","Avg Cost","LTP","P&L","Weight"]):
            col.markdown(f"<div style='font-size:.7rem;color:#8892AA;font-weight:600'>{lbl}</div>", unsafe_allow_html=True)
        st.markdown('<hr class="divider"/>', unsafe_allow_html=True)
        for h in sorted(holdings, key=lambda x:-(get_asset_price(x["symbol"])[0]*x["quantity"])):
            p, chg = get_asset_price(h["symbol"])
            val    = h["quantity"]*(p or h["avg_cost"])
            hpnl   = (p-h["avg_cost"])*h["quantity"]
            hpct   = ((p-h["avg_cost"])/h["avg_cost"]*100) if h["avg_cost"] else 0
            weight = (val/cur*100) if cur else 0
            pc     = "#2ECC7A" if hpnl>=0 else "#FF5A5A"
            cc     = "#2ECC7A" if chg>=0  else "#FF5A5A"
            hc = st.columns([2.5,1.5,1.2,1.5,1.5,2,1.5])
            hc[0].markdown(f"<div style='font-weight:600;font-size:.87rem'>{h['symbol']}</div><div style='font-size:.7rem;color:#8892AA'>{h.get('sub_class','')}</div>", unsafe_allow_html=True)
            hc[1].markdown(f"<span class='badge badge-{h['asset_class'][:2].lower()}'>{h['asset_class'][:3]}</span>", unsafe_allow_html=True)
            hc[2].markdown(f"<div style='font-size:.83rem'>{h['quantity']:g}</div>", unsafe_allow_html=True)
            hc[3].markdown(f"<div style='font-size:.83rem'>₹{indian_format(h['avg_cost'])}</div>", unsafe_allow_html=True)
            hc[4].markdown(f"<div style='font-size:.83rem'>₹{indian_format(p)}</div><div style='font-size:.7rem;color:{cc}'>{chg:+.2f}%</div>", unsafe_allow_html=True)
            hc[5].markdown(f"<div style='color:{pc};font-weight:600;font-size:.83rem'>₹{indian_format(abs(hpnl))} ({hpct:+.1f}%)</div>", unsafe_allow_html=True)
            hc[6].markdown(f"<div style='font-size:.83rem;color:#8892AA'>{weight:.1f}%</div>", unsafe_allow_html=True)
            if st.button(f"Detail →", key=f"det_{h['symbol']}", help=f"View {h['symbol']} detail page"):
                st.session_state.selected_symbol = h["symbol"]
                navigate("asset_detail")
            st.markdown('<hr class="divider"/>', unsafe_allow_html=True)

    with tab3:
        show_idx = [i for i in indices if i["symbol"]!="INDIA_VIX"]
        st.markdown('<div class="stat-bar-wrap">', unsafe_allow_html=True)
        for idx in show_idx:
            cc = "#2ECC7A" if idx["change_pct"]>=0 else "#FF5A5A"
            sign = "▲" if idx["change_pct"]>=0 else "▼"
            st.markdown(f'<div style="display:flex;justify-content:space-between;padding:.5rem 0;border-bottom:1px solid #1E2535"><span style="font-weight:600;font-size:.85rem">{idx["name"]}</span><span style="font-size:.85rem">{idx["value"]:,.2f}</span><span style="color:{cc};font-weight:700">{sign} {abs(idx["change_pct"]):.2f}%</span></div>', unsafe_allow_html=True)
        pf_cc = "#2ECC7A" if pnl_pct>=0 else "#FF5A5A"
        sign  = "▲" if pnl_pct>=0 else "▼"
        st.markdown(f'<div style="display:flex;justify-content:space-between;padding:.5rem 0;border-top:2px solid #4F7EFF;margin-top:.4rem"><span style="font-weight:700;color:#7BA3FF">📁 This Portfolio</span><span>₹{indian_format(cur)}</span><span style="color:{pf_cc};font-weight:700">{sign} {abs(pnl_pct):.2f}%</span></div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    with tab4:
        if role != "advisor":
            st.info("Cross-portfolio comparison is available for advisors.")
            return
        rows = []
        for cl in get_advisor_clients(user["id"]):
            for pf in get_portfolios_for_ac(cl["id"]):
                hs  = get_portfolio_holdings(pf["id"])
                pi, pv = _stats(hs)
                pp  = pv-pi; ppc = (pp/pi*100) if pi else 0
                rows.append({"Client":cl["client_name"],"Portfolio":pf["name"],"Invested":pi,"Value":pv,"PnL":pp,"Ret%":ppc,"N":len(hs)})
        if not rows: st.info("No data."); return
        hdr = st.columns([2,2.5,2,2,2,1.5,1])
        for col,lbl in zip(hdr,["Client","Portfolio","Invested","Value","P&L","Return","Holdings"]):
            col.markdown(f"<div style='font-size:.7rem;color:#8892AA;font-weight:600'>{lbl}</div>", unsafe_allow_html=True)
        st.markdown('<hr class="divider"/>', unsafe_allow_html=True)
        for r in sorted(rows, key=lambda x:-x["Ret%"]):
            pc = "#2ECC7A" if r["Ret%"]>=0 else "#FF5A5A"
            rc = st.columns([2,2.5,2,2,2,1.5,1])
            rc[0].markdown(f"<div style='font-size:.82rem;color:#8892AA'>{r['Client']}</div>", unsafe_allow_html=True)
            rc[1].markdown(f"<div style='font-weight:600;font-size:.87rem'>{r['Portfolio']}</div>", unsafe_allow_html=True)
            rc[2].markdown(f"<div style='font-size:.83rem'>₹{indian_format(r['Invested'])}</div>", unsafe_allow_html=True)
            rc[3].markdown(f"<div style='font-size:.83rem'>₹{indian_format(r['Value'])}</div>", unsafe_allow_html=True)
            rc[4].markdown(f"<div style='color:{pc};font-weight:600;font-size:.83rem'>₹{indian_format(abs(r['PnL']))}</div>", unsafe_allow_html=True)
            rc[5].markdown(f"<div style='color:{pc};font-weight:700;font-size:.87rem'>{r['Ret%']:+.1f}%</div>", unsafe_allow_html=True)
            rc[6].markdown(f"<div style='font-size:.83rem;color:#8892AA'>{r['N']}</div>", unsafe_allow_html=True)
            st.markdown('<hr class="divider"/>', unsafe_allow_html=True)
