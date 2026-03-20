import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.db import (get_advisor_clients, get_advisor_client, get_invoices_for_advisor,
                      create_invoice, update_invoice_status, get_portfolios_for_ac,
                      get_portfolio_holdings, get_asset_price, get_meeting_count_completed,
                      get_user_by_id, sb, decrypt_user, get_fixed_income)
from utils.crypto import inr, indian_format, fmt_date, title_case
from utils.session import navigate
from utils.market import is_market_open
from datetime import date, timedelta
import base64

FEE_TYPES = {"one_time":"One-Time Fixed Fee","consultation":"Per Consultation","management":"AUM Management"}
FEE_FREQS = {"annual":"Annual","quarterly":"Quarterly","monthly":"Monthly","daily":"Daily"}

# ── DEBT ASSET DETECTION ─────────────────────────────────────────────────
DEBT_ASSET_CLASSES = {"Bond", "Bank FD"}

def _is_debt(asset_class: str) -> bool:
    return asset_class in DEBT_ASSET_CLASSES

# ── PERIOD COUNTING ───────────────────────────────────────────────────────
def _next_boundary(d: date, frequency: str) -> date:
    if frequency == "monthly":
        m = d.month + 1; y = d.year + (m - 1) // 12; m = ((m - 1) % 12) + 1
        return d.replace(year=y, month=m, day=1)
    elif frequency == "quarterly":
        m = d.month + 3; y = d.year + (m - 1) // 12; m = ((m - 1) % 12) + 1
        return d.replace(year=y, month=m, day=1)
    elif frequency == "annual":
        return d.replace(year=d.year + 1, month=1, day=1)
    return d + timedelta(days=1)

def _count_periods(d_from: date, d_to: date, frequency: str) -> int:
    if d_from >= d_to: return 0
    if frequency == "daily": return (d_to - d_from).days
    count = 0; cursor = d_from
    while cursor < d_to:
        count += 1; cursor = _next_boundary(cursor, frequency)
    return count

def _rate_per_period(annual_pct: float, frequency: str) -> float:
    return annual_pct / 100.0 / {"annual":1,"quarterly":4,"monthly":12,"daily":365}.get(frequency, 12)

# ── FEE CALCULATION ───────────────────────────────────────────────────────
def calc_amount(fee_type, fee_value, frequency, portfolio_value,
                num_meetings, d_from: date, d_to: date,
                holdings=None) -> float:
    """
    For management fees:
    - Debt assets (Bond/Bank FD): daily accrual only — AUM × (rate/365) × days
      limited to earlier of exit or maturity.
    - All other assets: whole-period billing per frequency.
    If holdings list provided, split and calc separately then sum.
    """
    if fee_type == "one_time":
        return round(float(fee_value), 2)
    elif fee_type == "consultation":
        return round(float(fee_value) * int(num_meetings), 2)
    elif fee_type == "management":
        if holdings is not None:
            # Split holdings into debt vs non-debt
            debt_val     = 0.0
            non_debt_val = 0.0
            for h in holdings:
                p, _ = get_asset_price(h["symbol"])
                val  = h["quantity"] * (p or h["avg_cost"])
                if _is_debt(h.get("asset_class","")):
                    debt_val += val
                else:
                    non_debt_val += val

            # Debt: always daily accrual
            days      = (d_to - d_from).days
            debt_fee  = round(debt_val * (float(fee_value)/100.0/365) * days, 2)

            # Non-debt: whole-period billing
            n         = _count_periods(d_from, d_to, frequency)
            rate_p    = _rate_per_period(float(fee_value), frequency)
            nd_fee    = round(non_debt_val * rate_p * n, 2)

            return round(debt_fee + nd_fee, 2)
        else:
            # Fallback: single calculation on full portfolio value
            n      = _count_periods(d_from, d_to, frequency)
            rate_p = _rate_per_period(float(fee_value), frequency)
            return round(float(portfolio_value) * rate_p * n, 2)
    return 0.0

def _pf_value_and_holdings(ac_id):
    total = 0.0
    all_holdings = []
    for pf in get_portfolios_for_ac(ac_id):
        for h in get_portfolio_holdings(pf["id"]):
            p, _ = get_asset_price(h["symbol"])
            total += h["quantity"] * (p or h["avg_cost"])
            all_holdings.append(h)
    return total, all_holdings

# ── INVOICE HTML ──────────────────────────────────────────────────────────
def _invoice_html(inv, adv_user, client):
    adv_name  = title_case(adv_user.get("full_name") or adv_user.get("username",""))
    dec_adv   = decrypt_user(adv_user) if adv_user else {}
    adv_phone = dec_adv.get("phone","") or "—"
    adv_addr  = dec_adv.get("address","") or "—"
    cl_name   = title_case(client.get("client_name",""))
    cl_phone  = client.get("client_phone","") or "—"
    cl_addr   = "—"

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
            rows_html += (
                f"<tr>"
                f"<td class='tl fw'>{h['symbol']}</td>"
                f"<td class='tl gr'>{h['asset_class']}</td>"
                f"<td class='tc'>{h['quantity']:g}</td>"
                f"<td class='tr'>₹{indian_format(h['avg_cost'])}</td>"
                f"<td class='tr'>₹{indian_format(p)}</td>"
                f"<td class='tr' style='color:{pc};font-weight:600'>"
                f"₹{indian_format(abs(pnl))}&nbsp;"
                f"<span class='sm'>{sign}{pnl_pct:.1f}%</span></td>"
                f"</tr>"
            )
    total_pnl = total_cur - total_buy
    total_pct = (total_pnl / total_buy * 100) if total_buy else 0
    tpc       = "#15803d" if total_pnl >= 0 else "#b91c1c"
    tsign     = "+" if total_pnl >= 0 else ""

    fee_type = inv["fee_type"]
    fee_val  = inv["fee_value"]
    fee_freq = FEE_FREQS.get(inv.get("fee_frequency","annual"),"Annual")
    pf_val   = inv.get("portfolio_value",0)

    period_row = ""
    if inv.get("period_from") and inv.get("period_to"):
        period_row = (f"<tr><td class='lbl'>Period</td>"
                      f"<td>{fmt_date(inv['period_from'])} to {fmt_date(inv['period_to'])}</td></tr>")

    if fee_type == "management":
        fee_detail = (
            f"<tr><td class='lbl'>Fee Type</td><td>{FEE_TYPES['management']}</td></tr>"
            f"<tr><td class='lbl'>Annual Rate</td><td>{fee_val}%</td></tr>"
            f"<tr><td class='lbl'>Billing Frequency</td><td>{fee_freq}</td></tr>"
            f"<tr><td class='lbl'>Portfolio Value</td><td>₹{indian_format(pf_val)}</td></tr>"
            f"{period_row}"
        )
    elif fee_type == "consultation":
        fee_detail = (
            f"<tr><td class='lbl'>Fee Type</td><td>{FEE_TYPES['consultation']}</td></tr>"
            f"<tr><td class='lbl'>Rate per Meeting</td><td>₹{indian_format(fee_val)}</td></tr>"
            f"<tr><td class='lbl'>Meetings Billed</td><td>{inv.get('num_meetings',0)}</td></tr>"
            f"{period_row}"
        )
    else:
        fee_detail = (
            f"<tr><td class='lbl'>Fee Type</td><td>{FEE_TYPES['one_time']}</td></tr>"
            f"{period_row}"
        )

    notes_html = (f"<p style='margin-top:.5rem;font-size:.74rem;color:#64748b'>{inv['notes']}</p>"
                  if inv.get("notes") else "")

    # Doubled margins: 36mm top/bottom, 48mm left/right
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"/>
<style>
@page {{ size:A4 landscape; margin:36mm 48mm 36mm 48mm; }}
*{{ margin:0; padding:0; box-sizing:border-box; }}
body{{ font-family:'Segoe UI',Arial,sans-serif; font-size:11px; color:#1e293b; background:#fff; line-height:1.55; }}

.hdr{{ display:flex; justify-content:space-between; align-items:flex-start;
       padding-bottom:12px; border-bottom:2.5px solid #1e293b; margin-bottom:16px; }}
.brand{{ font-size:2.2rem; font-weight:900; letter-spacing:.12em; line-height:1; font-variant:small-caps; }}
.brand-sub{{ font-size:.58rem; color:#94a3b8; letter-spacing:.2em; text-transform:uppercase; margin-top:.2rem; }}
.inv-meta{{ text-align:right; }}
.inv-num{{ font-size:.9rem; font-weight:700; margin-bottom:.4rem; }}
.dt{{ border-collapse:collapse; float:right; }}
.dt td{{ padding:1.5px 0; font-size:.73rem; color:#64748b; }}
.dt td.dl{{ text-align:right; padding-right:4px; white-space:nowrap; }}
.dt td.dv{{ text-align:right; white-space:nowrap; }}

.two{{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:14px; }}
.party{{ background:#f8fafc; border-radius:6px; padding:10px 14px; border:1px solid #e2e8f0; }}
.plbl{{ font-size:.56rem; font-weight:700; color:#94a3b8; letter-spacing:.14em; text-transform:uppercase; margin-bottom:4px; }}
.pname{{ font-size:.88rem; font-weight:700; margin-bottom:3px; }}
.pdet{{ font-size:.73rem; color:#64748b; line-height:1.7; }}

.amt-box{{ background:linear-gradient(135deg,#1e293b,#2d4060); color:#fff;
           border-radius:9px; padding:13px 20px; margin-bottom:14px;
           display:flex; justify-content:space-between; align-items:center; }}
.amt-lbl{{ font-size:.6rem; opacity:.68; letter-spacing:.12em; text-transform:uppercase; margin-bottom:.18rem; }}
.amt-val{{ font-size:1.85rem; font-weight:800; letter-spacing:-.01em; }}
.amt-due{{ font-size:.7rem; opacity:.58; margin-top:.18rem; }}
.amt-right{{ text-align:right; font-size:.74rem; opacity:.8; line-height:1.8; }}

.sec{{ font-size:.58rem; font-weight:700; color:#94a3b8; letter-spacing:.12em;
       text-transform:uppercase; margin-bottom:6px; padding-bottom:3px;
       border-bottom:1px solid #e2e8f0; }}

.ft{{ width:100%; border-collapse:collapse; font-size:.78rem; }}
.ft td{{ padding:3.5px 0; border-bottom:1px solid #f1f5f9; vertical-align:top; }}
.lbl{{ color:#94a3b8; width:42%; }}

table.ht{{ width:100%; border-collapse:collapse; font-size:.75rem; margin-top:5px; }}
table.ht thead tr{{ background:#1e293b; color:#fff; }}
table.ht th{{ padding:6px 9px; font-weight:600; font-size:.63rem;
              letter-spacing:.05em; text-align:center; }}
table.ht th.hl{{ text-align:left; }}
table.ht td{{ padding:5.5px 9px; border-bottom:1px solid #f1f5f9; vertical-align:middle; }}
table.ht tr:nth-child(even){{ background:#f8fafc; }}
.tl{{ text-align:left; }} .tc{{ text-align:center; }} .tr{{ text-align:right; }}
.fw{{ font-weight:600; }} .gr{{ color:#64748b; }}
.sm{{ font-size:.68rem; display:inline-block; margin-left:2px; }}
.tot td{{ background:#eff6ff!important; font-weight:700; color:#1e293b; font-size:.76rem; }}

.ftr{{ margin-top:12px; padding-top:9px; border-top:1px solid #e2e8f0;
       display:flex; justify-content:space-between; align-items:center; }}
.ftr-brand{{ font-size:.88rem; font-weight:900; letter-spacing:.1em; color:#94a3b8; font-variant:small-caps; }}
.ftr-note{{ font-size:.62rem; color:#cbd5e1; text-align:right; line-height:1.6; }}
</style>
</head>
<body>
<div class="hdr">
  <div><div class="brand">QAVI</div><div class="brand-sub">Wealth Management</div></div>
  <div class="inv-meta">
    <div class="inv-num">{inv['invoice_number']}</div>
    <table class="dt">
      <tr><td class="dl">Date</td><td style="padding:0 4px;color:#64748b;font-size:.73rem">:</td><td class="dv">{fmt_date(inv['invoice_date'])}</td></tr>
      <tr><td class="dl">Payment Due</td><td style="padding:0 4px;color:#64748b;font-size:.73rem">:</td><td class="dv">{fmt_date(inv['due_date'])}</td></tr>
    </table>
  </div>
</div>
<div class="two">
  <div class="party">
    <div class="plbl">From</div><div class="pname">{adv_name}</div>
    <div class="pdet">Phone: {adv_phone}<br>Address: {adv_addr}</div>
  </div>
  <div class="party">
    <div class="plbl">Bill To</div><div class="pname">{cl_name}</div>
    <div class="pdet">Phone: {cl_phone}<br>Address: {cl_addr}</div>
  </div>
</div>
<div class="amt-box">
  <div>
    <div class="amt-lbl">Amount Due</div>
    <div class="amt-val">₹{indian_format(inv['amount'])}</div>
    <div class="amt-due">Due by {fmt_date(inv['due_date'])}</div>
  </div>
  <div class="amt-right">{FEE_TYPES.get(fee_type,'')}<br>
    <span style="opacity:.65">{fee_freq if fee_type=='management' else ''}</span></div>
</div>
<div class="two">
  <div>
    <div class="sec">Fee Details</div>
    <table class="ft"><tbody>{fee_detail}</tbody></table>
    {notes_html}
  </div>
  <div>
    <div class="sec">Portfolio Summary</div>
    <table class="ft"><tbody>
      <tr><td class="lbl">Purchase Cost</td><td>₹{indian_format(total_buy)}</td></tr>
      <tr><td class="lbl">Closing Value</td><td>₹{indian_format(total_cur)}</td></tr>
      <tr><td class="lbl">Overall P&amp;L</td>
          <td style="color:{tpc};font-weight:600">₹{indian_format(abs(total_pnl))} ({tsign}{total_pct:.2f}%)</td></tr>
    </tbody></table>
  </div>
</div>
<div class="sec" style="margin-top:5px">Holdings as of {fmt_date(str(date.today()))}</div>
<table class="ht">
  <thead><tr>
    <th class="hl" style="text-align:left">Symbol</th>
    <th class="hl" style="text-align:left">Asset Class</th>
    <th>Qty</th><th>Purchase Cost</th><th>Closing Price</th><th>P&amp;L</th>
  </tr></thead>
  <tbody>
    {rows_html}
    <tr class="tot">
      <td class="tl" colspan="2"><strong>Total Portfolio</strong></td>
      <td class="tc">—</td>
      <td class="tr">₹{indian_format(total_buy)}</td>
      <td class="tr">₹{indian_format(total_cur)}</td>
      <td class="tr" style="color:{tpc}">₹{indian_format(abs(total_pnl))}&nbsp;({tsign}{total_pct:.2f}%)</td>
    </tr>
  </tbody>
</table>
<div class="ftr">
  <div><div class="ftr-brand">◈ QAVI</div>
    <div style="font-size:.6rem;color:#cbd5e1">Generated {fmt_date(str(date.today()))}</div></div>
  <div class="ftr-note">Computer generated document.<br>For queries contact your advisor.</div>
</div>
</body></html>"""

# ── RENDER ────────────────────────────────────────────────────────────────
def render():
    if not st.session_state.get("user") or st.session_state.user["role"] != "advisor":
        navigate("login"); return

    user     = st.session_state.user
    advisor  = get_user_by_id(user["id"])
    clients  = get_advisor_clients(user["id"])
    invoices = get_invoices_for_advisor(user["id"])

    st.markdown('<div class="page-title">Invoices</div>', unsafe_allow_html=True)

    if is_market_open():
        st.warning("⚠️ Market open (closes 15:30 IST). Invoice will use yesterday's closing prices.")

    tab1, tab2 = st.tabs([f"  🧾 All Invoices ({len(invoices)})  ", "  ➕ Generate Invoice  "])

    with tab1:
        if not invoices:
            st.info("No invoices yet.")
        else:
            paid   = sum(i["amount"] for i in invoices if i["status"]=="paid")
            unpaid = sum(i["amount"] for i in invoices if i["status"]=="unpaid")
            m1,m2,m3 = st.columns(3)
            m1.metric("Total", len(invoices))
            m2.metric("Collected", inr(paid))
            m3.metric("Outstanding", inr(unpaid))
            st.markdown("<br>", unsafe_allow_html=True)

            for inv in invoices:
                client = get_advisor_client(inv["advisor_client_id"])
                if not client: continue
                sc = "#2ECC7A" if inv["status"]=="paid" else "#F5B731"
                with st.expander(
                    f"🧾  {inv['invoice_number']}  ·  {title_case(client['client_name'])}"
                    f"  ·  ₹{indian_format(inv['amount'])}  ·  {fmt_date(inv['invoice_date'])}"
                ):
                    c1,c2,c3 = st.columns(3)
                    c1.markdown(f"**Invoice #:** {inv['invoice_number']}<br>**Date:** {fmt_date(inv['invoice_date'])}<br>**Due:** {fmt_date(inv['due_date'])}", unsafe_allow_html=True)
                    c2.markdown(f"**Fee Type:** {FEE_TYPES.get(inv['fee_type'],'—')}<br>**Amount:** ₹{indian_format(inv['amount'])}<br>**Status:** <span style='color:{sc};font-weight:600'>{inv['status'].upper()}</span>", unsafe_allow_html=True)
                    c3.markdown(f"**Portfolio Value:** ₹{indian_format(inv.get('portfolio_value',0))}<br>**Meetings:** {inv.get('num_meetings',0)}<br>**Period:** {fmt_date(inv.get('period_from',''))} – {fmt_date(inv.get('period_to',''))}", unsafe_allow_html=True)

                    b1,b2,b3,b4 = st.columns(4)
                    if inv["status"]=="unpaid":
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
                            try: sb().table("invoices").delete().eq("id", inv["id"]).execute()
                            except: sb().table("invoices").delete().eq("invoice_number", inv["invoice_number"]).execute()
                            st.session_state.pop(f"del_{inv['id']}", None); st.rerun()
                        if dn.button("No",  key=f"ndi_{inv['id']}", use_container_width=True):
                            st.session_state.pop(f"del_{inv['id']}", None); st.rerun()

    with tab2:
        if not clients:
            st.info("No clients yet."); return

        cl_id = st.selectbox("Client", [c["id"] for c in clients],
                             format_func=lambda x: title_case(next(c["client_name"] for c in clients if c["id"]==x)))
        client  = next(c for c in clients if c["id"]==cl_id)
        pf_val, pf_holdings = _pf_value_and_holdings(cl_id)
        num_mtg = get_meeting_count_completed(cl_id)

        # Show debt vs non-debt split
        debt_val    = sum(h["quantity"]*(get_asset_price(h["symbol"])[0] or h["avg_cost"])
                         for h in pf_holdings if _is_debt(h.get("asset_class","")))
        non_debt_val = pf_val - debt_val
        if debt_val > 0:
            st.markdown(
                f'<p style="font-size:.82rem;color:#8892AA">'
                f'Total AUM: ₹{indian_format(pf_val)}  ·  '
                f'Debt (daily accrual): ₹{indian_format(debt_val)}  ·  '
                f'Other (period billing): ₹{indian_format(non_debt_val)}'
                f'  ·  Completed Meetings: {num_mtg}</p>',
                unsafe_allow_html=True)
        else:
            st.markdown(
                f'<p style="font-size:.82rem;color:#8892AA">'
                f'Portfolio Value: ₹{indian_format(pf_val)}  ·  Completed Meetings: {num_mtg}</p>',
                unsafe_allow_html=True)

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
            freq = fc2.selectbox("Billing Frequency (non-debt assets)", list(FEE_FREQS.keys()),
                                  format_func=lambda x: FEE_FREQS[x])
            if debt_val > 0:
                st.caption("Debt assets (Bonds/FDs) always use daily accrual regardless of billing frequency.")
        else:
            fc2.empty()

        n_meetings = int(st.number_input("Meetings to Bill", min_value=0, value=num_mtg, step=1)) \
                     if fee_type=="consultation" else num_mtg

        st.markdown("---")

        if st.button("🧮 Calculate Fee", use_container_width=True):
            amount = calc_amount(fee_type, fee_value, freq, pf_val,
                                 n_meetings, pf_from, pf_to,
                                 holdings=pf_holdings if fee_type=="management" else None)
            n = _count_periods(pf_from, pf_to, freq) if fee_type=="management" else 0
            st.session_state["_inv_calc"] = {
                "amount":amount,"fee_type":fee_type,"fee_value":fee_value,
                "freq":freq,"pf_val":pf_val,"n_meetings":n_meetings,
                "pf_from":str(pf_from),"pf_to":str(pf_to),"n":n,
                "debt_val":debt_val,"non_debt_val":non_debt_val,
            }
            st.rerun()

        calc = st.session_state.get("_inv_calc")
        if calc:
            amount     = calc["amount"]
            fee_type_c = calc["fee_type"]
            if fee_type_c == "management":
                days   = (pf_to - pf_from).days
                n      = int(calc["n"])
                dv     = calc.get("debt_val",0)
                ndv    = calc.get("non_debt_val",0)
                detail_parts = []
                if dv > 0:
                    debt_fee = round(dv * (calc["fee_value"]/100/365) * days, 2)
                    detail_parts.append(f"Debt ₹{indian_format(dv)} × {calc['fee_value']}%÷365 × {days}d = ₹{indian_format(debt_fee)}")
                if ndv > 0:
                    div_map = {"annual":1,"quarterly":4,"monthly":12,"daily":365}
                    div     = div_map.get(calc["freq"],12)
                    freq_l  = FEE_FREQS[calc["freq"]].lower()
                    nd_fee  = round(ndv * (calc["fee_value"]/100/div) * n, 2)
                    detail_parts.append(f"Other ₹{indian_format(ndv)} × {calc['fee_value']}%÷{div} × {n} {freq_l}(s) = ₹{indian_format(nd_fee)}")
                if not detail_parts:
                    div_map = {"annual":1,"quarterly":4,"monthly":12}
                    div     = div_map.get(calc["freq"],12) if calc["freq"]!="daily" else 365
                    detail_parts.append(f"₹{indian_format(calc['pf_val'])} × {calc['fee_value']}%÷{div} × {n if calc['freq']!='daily' else days}")
                detail = " + ".join(detail_parts)
            elif fee_type_c == "consultation":
                detail = f"{calc['n_meetings']} meetings × ₹{indian_format(calc['fee_value'])}"
            else:
                detail = "Fixed one-time fee"

            st.markdown(f"""
            <div style="background:#1E2535;border:1px solid #2ECC7A;border-radius:10px;
                padding:1rem 1.2rem;margin:.4rem 0">
                <div style="font-size:.76rem;color:#8892AA;margin-bottom:.3rem">{detail}</div>
                <div style="font-size:1.5rem;font-weight:700;color:#2ECC7A">= ₹{indian_format(amount)}</div>
            </div>""", unsafe_allow_html=True)

            notes = st.text_input("Notes (optional)", key="inv_notes_field")
            if st.button("✅ Generate Invoice", use_container_width=True):
                due_date = str(pay_basis + timedelta(days=15))
                try:
                    inv_num = create_invoice(
                        advisor_id=user["id"], ac_id=cl_id,
                        fee_type=fee_type, fee_value=fee_value, fee_frequency=freq,
                        amount=amount, portfolio_value=pf_val, num_meetings=n_meetings,
                        period_from=str(pf_from), period_to=str(pf_to), notes=notes,
                        invoice_date=str(inv_date), due_date=due_date,
                    )
                    st.session_state.pop("_inv_calc", None)
                    st.success(f"Invoice {inv_num} created!"); st.rerun()
                except Exception as e:
                    if "duplicate" in str(e).lower() or "23505" in str(e):
                        st.warning("Invoice number collision — retrying…")
                        import time; time.sleep(0.5)
                        try:
                            inv_num = create_invoice(
                                advisor_id=user["id"], ac_id=cl_id,
                                fee_type=fee_type, fee_value=fee_value, fee_frequency=freq,
                                amount=amount, portfolio_value=pf_val, num_meetings=n_meetings,
                                period_from=str(pf_from), period_to=str(pf_to), notes=notes,
                                invoice_date=str(inv_date), due_date=due_date,
                            )
                            st.session_state.pop("_inv_calc", None)
                            st.success(f"Invoice {inv_num} created!"); st.rerun()
                        except Exception as e2:
                            st.error(f"Could not generate invoice: {e2}")
                    else:
                        st.error(f"Could not generate invoice: {e}")
        else:
            st.info("Configure fee above then click **Calculate Fee** to preview before generating.")
