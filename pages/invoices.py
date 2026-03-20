import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.db import (get_advisor_clients, get_advisor_client, get_invoices_for_advisor,
                      create_invoice, update_invoice_status, get_portfolios_for_ac,
                      get_portfolio_holdings, get_asset_price, get_meeting_count_completed,
                      get_user_by_id, sb, decrypt_user)
from utils.crypto import inr, indian_format, fmt_date, title_case
from utils.session import navigate
from utils.market import is_market_open
from datetime import date, timedelta
import base64
import math

FEE_TYPES = {"one_time":"One-Time Fixed Fee","consultation":"Per Consultation","management":"AUM Management"}
FEE_FREQS = {"annual":"Annual","quarterly":"Quarterly","monthly":"Monthly","daily":"Daily"}

# ─────────────────────────────────────────────────────────────────────────────
# CORRECT FEE FORMULA
# Daily   : AUM × (rate/365) × days                    (pro-rata)
# Monthly : AUM × (rate/12)  × whole_months_charged    (full period)
# Qtrly   : AUM × (rate/4)   × whole_quarters_charged  (full period)
# Annual  : AUM × rate       × whole_years_charged      (full period)
#   "Any activity during a period = full billing unit"
# ─────────────────────────────────────────────────────────────────────────────

def _count_periods(d_from: date, d_to: date, frequency: str) -> float:
    """
    Daily  → exact day count (pro-rata).
    Others → count whole periods; any partial period at end = 1 full unit.
    """
    if d_from >= d_to:
        return 0.0
    if frequency == "daily":
        return float((d_to - d_from).days)

    # Walk forward period-by-period from d_from
    count   = 0
    cursor  = d_from
    while cursor < d_to:
        count += 1
        if frequency == "monthly":
            # Advance one calendar month
            m = cursor.month + 1
            y = cursor.year + (m - 1) // 12
            m = ((m - 1) % 12) + 1
            try:    cursor = cursor.replace(year=y, month=m)
            except: cursor = cursor.replace(year=y, month=m, day=28)
        elif frequency == "quarterly":
            m = cursor.month + 3
            y = cursor.year + (m - 1) // 12
            m = ((m - 1) % 12) + 1
            try:    cursor = cursor.replace(year=y, month=m)
            except: cursor = cursor.replace(year=y, month=m, day=28)
        elif frequency == "annual":
            try:    cursor = cursor.replace(year=cursor.year + 1)
            except: cursor = cursor.replace(year=cursor.year + 1, day=28)
    return float(count)

def _rate_per_period(annual_pct: float, frequency: str) -> float:
    divisors = {"annual": 1, "quarterly": 4, "monthly": 12, "daily": 365}
    return annual_pct / 100.0 / divisors.get(frequency, 12)

def calc_amount(fee_type, fee_value, frequency, portfolio_value,
                num_meetings, d_from: date, d_to: date) -> float:
    if fee_type == "one_time":
        return round(float(fee_value), 2)
    elif fee_type == "consultation":
        return round(float(fee_value) * int(num_meetings), 2)
    elif fee_type == "management":
        n      = _count_periods(d_from, d_to, frequency)
        rate_p = _rate_per_period(float(fee_value), frequency)
        return round(float(portfolio_value) * rate_p * n, 2)
    return 0.0

def _calc_detail(fee_value, frequency, portfolio_value, d_from, d_to):
    """Human-readable breakdown string."""
    n      = _count_periods(d_from, d_to, frequency)
    rate_p = _rate_per_period(fee_value, frequency)
    freq_l = FEE_FREQS[frequency].lower()
    if frequency == "daily":
        return (f"₹{indian_format(portfolio_value)} × {fee_value}% ÷ 365 × "
                f"{int(n)} day(s) = ₹{indian_format(portfolio_value * rate_p * n)}")
    else:
        div_map = {"annual":1,"quarterly":4,"monthly":12}
        div     = div_map.get(frequency, 12)
        return (f"₹{indian_format(portfolio_value)} × {fee_value}% ÷ {div} × "
                f"{int(n)} {freq_l}(s) = ₹{indian_format(portfolio_value * rate_p * n)}")

def _pf_value(ac_id) -> float:
    total = 0.0
    for pf in get_portfolios_for_ac(ac_id):
        for h in get_portfolio_holdings(pf["id"]):
            p, _ = get_asset_price(h["symbol"])
            total += h["quantity"] * (p or h["avg_cost"])
    return total

# ─────────────────────────────────────────────────────────────────────────────
# INVOICE HTML  — landscape A4, proper margins, address/phone, fixed alignment
# ─────────────────────────────────────────────────────────────────────────────

def _invoice_html(inv, adv_user, client):
    """Build HTML invoice. adv_user = full user dict, client = advisor_client dict."""
    # Advisor contact
    adv_name  = title_case(adv_user.get("full_name") or adv_user.get("username",""))
    adv_phone = decrypt_user(adv_user).get("phone","") or "—"
    adv_addr  = decrypt_user(adv_user).get("address","") or "—"

    # Client contact
    cl_name   = title_case(client.get("client_name",""))
    cl_phone  = client.get("client_phone","") or "—"
    cl_addr   = "—"  # offline clients don't have address stored separately

    # Holdings
    rows_html = ""
    total_buy = total_cur = 0.0
    for pf in get_portfolios_for_ac(inv["advisor_client_id"]):
        for h in get_portfolio_holdings(pf["id"]):
            p, _    = get_asset_price(h["symbol"])
            buy_val = h["quantity"] * h["avg_cost"]
            cur_val = h["quantity"] * (p or h["avg_cost"])
            pnl     = cur_val - buy_val
            pnl_pct = ((p - h["avg_cost"]) / h["avg_cost"] * 100) if h["avg_cost"] else 0
            total_buy += buy_val; total_cur += cur_val
            pc   = "#15803d" if pnl >= 0 else "#b91c1c"
            sign = "+" if pnl >= 0 else ""
            # Proper column alignment — no inline style conflicts with heading
            rows_html += (
                f"<tr>"
                f"<td class='sym'>{h['symbol']}</td>"
                f"<td class='cls'>{h['asset_class']}</td>"
                f"<td class='num'>{h['quantity']:g}</td>"
                f"<td class='num'>₹{indian_format(h['avg_cost'])}</td>"
                f"<td class='num'>₹{indian_format(p)}</td>"
                f"<td class='pnl' style='color:{pc}'>"
                f"₹{indian_format(abs(pnl))} "
                f"<span class='pct'>{sign}{pnl_pct:.1f}%</span></td>"
                f"</tr>"
            )
    total_pnl = total_cur - total_buy
    total_pct = (total_pnl / total_buy * 100) if total_buy else 0
    tpc       = "#15803d" if total_pnl >= 0 else "#b91c1c"
    tsign     = "+" if total_pnl >= 0 else ""

    # Fee detail rows
    fee_type  = inv["fee_type"]
    fee_val   = inv["fee_value"]
    fee_freq  = FEE_FREQS.get(inv.get("fee_frequency","annual"),"Annual")
    pf_val    = inv.get("portfolio_value",0)

    period_row = ""
    if inv.get("period_from") and inv.get("period_to"):
        period_row = (f"<tr><td class='fl'>Period</td>"
                      f"<td>{fmt_date(inv['period_from'])} to {fmt_date(inv['period_to'])}</td></tr>")

    if fee_type == "management":
        fee_detail = (
            f"<tr><td class='fl'>Fee Type</td><td>{FEE_TYPES['management']}</td></tr>"
            f"<tr><td class='fl'>Annual Rate</td><td>{fee_val}%</td></tr>"
            f"<tr><td class='fl'>Billing Frequency</td><td>{fee_freq}</td></tr>"
            f"<tr><td class='fl'>Portfolio Value</td><td>₹{indian_format(pf_val)}</td></tr>"
            f"{period_row}"
        )
    elif fee_type == "consultation":
        fee_detail = (
            f"<tr><td class='fl'>Fee Type</td><td>{FEE_TYPES['consultation']}</td></tr>"
            f"<tr><td class='fl'>Rate per Meeting</td><td>₹{indian_format(fee_val)}</td></tr>"
            f"<tr><td class='fl'>Meetings Billed</td><td>{inv.get('num_meetings',0)}</td></tr>"
            f"{period_row}"
        )
    else:
        fee_detail = (
            f"<tr><td class='fl'>Fee Type</td><td>{FEE_TYPES['one_time']}</td></tr>"
            f"{period_row}"
        )

    notes_html = (f"<p style='margin-top:.5rem;font-size:.75rem;color:#64748b;'>"
                  f"{inv['notes']}</p>") if inv.get("notes") else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"/>
<style>
@page {{ size:A4 landscape; margin:16mm 20mm; }}
*{{ margin:0; padding:0; box-sizing:border-box; }}
body{{ font-family:'Segoe UI',Arial,sans-serif; font-size:11.5px; color:#1e293b; background:#fff; line-height:1.5; }}

/* HEADER */
.hdr{{ display:flex; justify-content:space-between; align-items:flex-start;
       padding-bottom:14px; border-bottom:2px solid #1e293b; margin-bottom:18px; }}
.brand{{ font-size:2.4rem; font-weight:900; letter-spacing:.12em;
         color:#1e293b; line-height:1; font-variant:small-caps; }}
.brand-sub{{ font-size:.6rem; color:#94a3b8; letter-spacing:.2em;
             text-transform:uppercase; margin-top:.25rem; }}
.inv-meta{{ text-align:right; }}
.inv-num{{ font-size:.9rem; font-weight:700; color:#1e293b; }}
.inv-dates{{ font-size:.75rem; color:#64748b; line-height:2; margin-top:.2rem; }}

/* PARTIES */
.two{{ display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-bottom:16px; }}
.party{{ background:#f8fafc; border-radius:6px; padding:11px 15px; border:1px solid #e2e8f0; }}
.plbl{{ font-size:.58rem; font-weight:700; color:#94a3b8; letter-spacing:.14em;
        text-transform:uppercase; margin-bottom:5px; }}
.pname{{ font-size:.9rem; font-weight:700; color:#1e293b; margin-bottom:3px; }}
.pdet{{ font-size:.76rem; color:#64748b; line-height:1.7; }}

/* AMOUNT */
.amt-box{{ background:linear-gradient(135deg,#1e293b,#2d4060); color:#fff;
           border-radius:10px; padding:14px 22px; margin-bottom:16px;
           display:flex; justify-content:space-between; align-items:center; }}
.amt-lbl{{ font-size:.62rem; opacity:.7; letter-spacing:.12em; text-transform:uppercase; margin-bottom:.2rem; }}
.amt-val{{ font-size:1.9rem; font-weight:800; letter-spacing:-.01em; }}
.amt-due{{ font-size:.72rem; opacity:.6; margin-top:.2rem; }}

/* SECTIONS */
.sec-ttl{{ font-size:.6rem; font-weight:700; color:#94a3b8; letter-spacing:.12em;
           text-transform:uppercase; margin-bottom:7px; padding-bottom:4px;
           border-bottom:1px solid #e2e8f0; }}

/* FEE TABLE */
.ft{{ width:100%; border-collapse:collapse; font-size:.8rem; }}
.ft td{{ padding:4px 0; border-bottom:1px solid #f1f5f9; vertical-align:top; }}
.fl{{ color:#94a3b8; width:44%; }}

/* HOLDINGS TABLE */
table.ht{{ width:100%; border-collapse:collapse; font-size:.77rem; }}
table.ht thead tr{{ background:#1e293b; color:#fff; }}
table.ht th{{ padding:7px 10px; font-weight:600; font-size:.65rem;
              letter-spacing:.05em; text-align:left; }}
table.ht th.num,table.ht td.num{{ text-align:right; }}
table.ht th.pnl,table.ht td.pnl{{ text-align:right; min-width:90px; }}
table.ht td{{ padding:6px 10px; border-bottom:1px solid #f1f5f9; vertical-align:middle; }}
table.ht td.sym{{ font-weight:600; }}
table.ht td.cls{{ color:#64748b; }}
table.ht tr:nth-child(even){{ background:#f8fafc; }}
.tot td{{ background:#eff6ff!important; font-weight:700; color:#1e293b; font-size:.78rem; }}
.pct{{ font-size:.7rem; display:inline-block; margin-left:2px; }}

/* FOOTER */
.ftr{{ margin-top:14px; padding-top:10px; border-top:1px solid #e2e8f0;
       display:flex; justify-content:space-between; align-items:center; }}
.ftr-brand{{ font-size:.9rem; font-weight:900; letter-spacing:.1em; color:#94a3b8; font-variant:small-caps; }}
.ftr-note{{ font-size:.64rem; color:#cbd5e1; text-align:right; line-height:1.6; }}
</style>
</head>
<body>

<div class="hdr">
  <div>
    <div class="brand">QAVI</div>
    <div class="brand-sub">Wealth Management</div>
  </div>
  <div class="inv-meta">
    <div class="inv-num">{inv['invoice_number']}</div>
    <div class="inv-dates">
      Date:&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{fmt_date(inv['invoice_date'])}<br>
      Payment Due:&nbsp;{fmt_date(inv['due_date'])}
    </div>
  </div>
</div>

<div class="two">
  <div class="party">
    <div class="plbl">From</div>
    <div class="pname">{adv_name}</div>
    <div class="pdet">
      Phone: {adv_phone}<br>
      Address: {adv_addr}
    </div>
  </div>
  <div class="party">
    <div class="plbl">Bill To</div>
    <div class="pname">{cl_name}</div>
    <div class="pdet">
      Phone: {cl_phone}<br>
      Address: {cl_addr}
    </div>
  </div>
</div>

<div class="amt-box">
  <div>
    <div class="amt-lbl">Amount Due</div>
    <div class="amt-val">₹{indian_format(inv['amount'])}</div>
    <div class="amt-due">Due by {fmt_date(inv['due_date'])}</div>
  </div>
  <div style="text-align:right;opacity:.8;font-size:.76rem;line-height:1.8;">
    {FEE_TYPES.get(fee_type,'')}<br>
    <span style="opacity:.65">{fee_freq if fee_type=='management' else ''}</span>
  </div>
</div>

<div class="two">
  <div>
    <div class="sec-ttl">Fee Details</div>
    <table class="ft"><tbody>
      {fee_detail}
    </tbody></table>
    {notes_html}
  </div>
  <div>
    <div class="sec-ttl">Portfolio Summary</div>
    <table class="ft"><tbody>
      <tr><td class="fl">Purchase Cost</td><td>₹{indian_format(total_buy)}</td></tr>
      <tr><td class="fl">Current Value</td><td>₹{indian_format(total_cur)}</td></tr>
      <tr><td class="fl">Overall P&amp;L</td>
          <td style="color:{tpc};font-weight:600">
            ₹{indian_format(abs(total_pnl))} ({tsign}{total_pct:.2f}%)
          </td></tr>
    </tbody></table>
  </div>
</div>

<div class="sec-ttl" style="margin-top:6px;">Holdings as of {fmt_date(str(date.today()))}</div>
<table class="ht">
  <thead><tr>
    <th>Symbol</th>
    <th>Asset Class</th>
    <th class="num">Qty</th>
    <th class="num">Purchase Cost</th>
    <th class="num">Current Price</th>
    <th class="pnl">P&amp;L</th>
  </tr></thead>
  <tbody>
    {rows_html}
    <tr class="tot">
      <td colspan="3"><strong>Total Portfolio</strong></td>
      <td class="num">₹{indian_format(total_buy)}</td>
      <td class="num">₹{indian_format(total_cur)}</td>
      <td class="pnl" style="color:{tpc}">
        ₹{indian_format(abs(total_pnl))}&nbsp;({tsign}{total_pct:.2f}%)
      </td>
    </tr>
  </tbody>
</table>

<div class="ftr">
  <div>
    <div class="ftr-brand">◈ QAVI</div>
    <div style="font-size:.62rem;color:#cbd5e1;">Generated {fmt_date(str(date.today()))}</div>
  </div>
  <div class="ftr-note">
    Computer generated document.<br>
    For queries contact your advisor.
  </div>
</div>

</body></html>"""

# ─────────────────────────────────────────────────────────────────────────────
# RENDER
# ─────────────────────────────────────────────────────────────────────────────

def render():
    if not st.session_state.get("user") or st.session_state.user["role"] != "advisor":
        navigate("login"); return

    user     = st.session_state.user
    advisor  = get_user_by_id(user["id"])
    clients  = get_advisor_clients(user["id"])
    invoices = get_invoices_for_advisor(user["id"])

    st.markdown('<div class="page-title">Invoices</div>', unsafe_allow_html=True)

    if is_market_open():
        st.warning("⚠️ Market is open — invoice will use yesterday's closing prices.")

    tab1, tab2 = st.tabs([f"  🧾 All Invoices ({len(invoices)})  ", "  ➕ Generate Invoice  "])

    # ── ALL INVOICES ──────────────────────────────────────────────────────
    with tab1:
        if not invoices:
            st.info("No invoices yet.")
        else:
            total_paid   = sum(i["amount"] for i in invoices if i["status"] == "paid")
            total_unpaid = sum(i["amount"] for i in invoices if i["status"] == "unpaid")
            m1,m2,m3 = st.columns(3)
            m1.metric("Total", len(invoices))
            m2.metric("Collected", inr(total_paid))
            m3.metric("Outstanding", inr(total_unpaid))
            st.markdown("<br>", unsafe_allow_html=True)

            for inv in invoices:
                client = get_advisor_client(inv["advisor_client_id"])
                if not client: continue
                sc = "#2ECC7A" if inv["status"] == "paid" else "#F5B731"
                with st.expander(
                    f"🧾  {inv['invoice_number']}  ·  {title_case(client['client_name'])}"
                    f"  ·  ₹{indian_format(inv['amount'])}  ·  {fmt_date(inv['invoice_date'])}"
                ):
                    c1,c2,c3 = st.columns(3)
                    c1.markdown(f"**Invoice #:** {inv['invoice_number']}<br>**Date:** {fmt_date(inv['invoice_date'])}<br>**Due:** {fmt_date(inv['due_date'])}", unsafe_allow_html=True)
                    c2.markdown(f"**Fee Type:** {FEE_TYPES.get(inv['fee_type'],'—')}<br>**Amount:** ₹{indian_format(inv['amount'])}<br>**Status:** <span style='color:{sc};font-weight:600'>{inv['status'].upper()}</span>", unsafe_allow_html=True)
                    c3.markdown(f"**Portfolio Value:** ₹{indian_format(inv.get('portfolio_value',0))}<br>**Meetings:** {inv.get('num_meetings',0)}<br>**Period:** {fmt_date(inv.get('period_from',''))} – {fmt_date(inv.get('period_to',''))}", unsafe_allow_html=True)

                    b1,b2,b3,b4 = st.columns(4)
                    if inv["status"] == "unpaid":
                        if b1.button("✅ Mark Paid",  key=f"mp_{inv['id']}", use_container_width=True): update_invoice_status(inv["id"],"paid"); st.rerun()
                    else:
                        if b1.button("↩ Unpaid",     key=f"mu_{inv['id']}", use_container_width=True): update_invoice_status(inv["id"],"unpaid"); st.rerun()

                    html_c = _invoice_html(inv, advisor or {}, client)
                    b64    = base64.b64encode(html_c.encode()).decode()
                    b2.markdown(f'<a href="data:text/html;base64,{b64}" download="{inv["invoice_number"]}.html" style="display:block;text-align:center;background:#161B27;color:#F0F4FF;padding:.42rem .9rem;border-radius:8px;border:1px solid #252D40;font-size:.84rem;text-decoration:none">📥 Download</a>', unsafe_allow_html=True)
                    b3.markdown(f'<a href="data:text/html;base64,{b64}" target="_blank" style="display:block;text-align:center;background:#161B27;color:#F0F4FF;padding:.42rem .9rem;border-radius:8px;border:1px solid #252D40;font-size:.84rem;text-decoration:none">🔍 Preview</a>', unsafe_allow_html=True)

                    if b4.button("🗑 Delete", key=f"dinv_{inv['id']}", use_container_width=True):
                        st.session_state[f"del_{inv['id']}"] = True; st.rerun()
                    if st.session_state.get(f"del_{inv['id']}"):
                        st.error("Delete this invoice permanently?")
                        dy,dn = st.columns(2)
                        if dy.button("Yes", key=f"ydi_{inv['id']}", use_container_width=True):
                            sb().table("invoices").delete().eq("id",inv["id"]).execute()
                            st.session_state.pop(f"del_{inv['id']}",None); st.rerun()
                        if dn.button("No",  key=f"ndi_{inv['id']}", use_container_width=True):
                            st.session_state.pop(f"del_{inv['id']}",None); st.rerun()

    # ── GENERATE INVOICE ─────────────────────────────────────────────────
    with tab2:
        if not clients:
            st.info("No clients yet."); return

        cl_id = st.selectbox("Client", [c["id"] for c in clients],
                             format_func=lambda x: title_case(next(c["client_name"] for c in clients if c["id"]==x)))
        client  = next(c for c in clients if c["id"] == cl_id)
        pf_val  = _pf_value(cl_id)
        num_mtg = get_meeting_count_completed(cl_id)

        st.markdown(f'<p style="font-size:.82rem;color:#8892AA">Portfolio Value: ₹{indian_format(pf_val)}  ·  Completed Meetings: {num_mtg}</p>', unsafe_allow_html=True)

        st.markdown("#### Dates")
        dc1,dc2 = st.columns(2)
        inv_date  = dc1.date_input("Invoice Date",       value=date.today())
        pay_basis = dc2.date_input("Payment Date Basis", value=date.today(),
                                    help="Due date = 15 days from this date")
        pc1,pc2 = st.columns(2)
        pf_from = pc1.date_input("Period From", value=date.today().replace(day=1))
        pf_to   = pc2.date_input("Period To",   value=date.today())

        st.markdown("#### Fee")
        fee_type  = st.selectbox("Fee Type", list(FEE_TYPES.keys()), format_func=lambda x: FEE_TYPES[x])
        fc1,fc2   = st.columns(2)
        fee_value = fc1.number_input("Fee Value (₹ or % p.a.)",
                                      value=float(client.get("fee_value",0)), min_value=0.0, step=100.0)
        freq = "annual"
        if fee_type == "management":
            freq = fc2.selectbox("Billing Frequency", list(FEE_FREQS.keys()), format_func=lambda x: FEE_FREQS[x])
        else:
            fc2.empty()

        n_meetings = int(st.number_input("Meetings to Bill", min_value=0, value=num_mtg, step=1)) \
                     if fee_type == "consultation" else num_mtg

        st.markdown("---")

        if st.button("🧮 Calculate Fee", use_container_width=True):
            amount = calc_amount(fee_type, fee_value, freq, pf_val, n_meetings, pf_from, pf_to)
            n      = _count_periods(pf_from, pf_to, freq) if fee_type=="management" else 0
            rate_p = _rate_per_period(fee_value, freq) if fee_type=="management" else 0
            st.session_state["_inv_calc"] = {
                "amount":amount,"fee_type":fee_type,"fee_value":fee_value,
                "freq":freq,"pf_val":pf_val,"n_meetings":n_meetings,
                "pf_from":str(pf_from),"pf_to":str(pf_to),"n":n,"rate_p":rate_p,
            }
            st.rerun()

        calc = st.session_state.get("_inv_calc")
        if calc:
            amount   = calc["amount"]
            fee_type_c = calc["fee_type"]
            if fee_type_c == "management":
                n      = calc["n"]; rate_p = calc["rate_p"]
                freq_l = FEE_FREQS[calc["freq"]].lower()
                if calc["freq"] == "daily":
                    detail = (f"₹{indian_format(calc['pf_val'])} × {calc['fee_value']}% ÷ 365"
                              f" × {int(n)} day(s)")
                else:
                    div    = {"annual":1,"quarterly":4,"monthly":12}.get(calc["freq"],12)
                    detail = (f"₹{indian_format(calc['pf_val'])} × {calc['fee_value']}% ÷ {div}"
                              f" × {int(n)} {freq_l}(s)")
            elif fee_type_c == "consultation":
                detail = f"{calc['n_meetings']} meetings × ₹{indian_format(calc['fee_value'])}"
            else:
                detail = "Fixed one-time fee"

            st.markdown(f"""
            <div style="background:#1E2535;border:1px solid #2ECC7A;border-radius:10px;padding:1rem 1.2rem;margin:.4rem 0">
                <div style="font-size:.76rem;color:#8892AA;margin-bottom:.3rem">{detail}</div>
                <div style="font-size:1.5rem;font-weight:700;color:#2ECC7A">= ₹{indian_format(amount)}</div>
            </div>""", unsafe_allow_html=True)

            notes = st.text_input("Notes (optional)", key="inv_notes_field")
            if st.button("✅ Generate Invoice", use_container_width=True):
                due_date = str(pay_basis + timedelta(days=15))
                inv_num  = create_invoice(
                    advisor_id=user["id"], ac_id=cl_id,
                    fee_type=fee_type, fee_value=fee_value, fee_frequency=freq,
                    amount=amount, portfolio_value=pf_val, num_meetings=n_meetings,
                    period_from=str(pf_from), period_to=str(pf_to), notes=notes,
                    invoice_date=str(inv_date), due_date=due_date,
                )
                st.session_state.pop("_inv_calc", None)
                st.success(f"Invoice {inv_num} created!"); st.rerun()
        else:
            st.info("Configure fee above then click **Calculate Fee** to preview before generating.")
