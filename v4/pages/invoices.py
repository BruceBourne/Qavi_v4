import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.db import (get_advisor_clients, get_advisor_client, get_invoices_for_advisor,
                      create_invoice, update_invoice_status, get_portfolios_for_ac,
                      get_portfolio_holdings, get_asset_price, get_meeting_count_completed,
                      get_user_by_id, sb)
from utils.crypto import inr, indian_format, fmt_date, title_case
from utils.session import navigate
from utils.market import is_market_open
from datetime import date, timedelta
import base64

FEE_TYPES = {"one_time":"One-Time Fixed Fee","consultation":"Per Consultation","management":"AUM Management"}
FEE_FREQS = {"annual":"Annual","quarterly":"Quarterly","monthly":"Monthly","daily":"Daily"}

# ── FEE CALCULATION ───────────────────────────────────────────────────────

def _period_units(d_from: date, d_to: date, frequency: str) -> float:
    if d_from >= d_to: return 0.0
    days = (d_to - d_from).days
    return {"annual": days/365.0, "quarterly": days/91.25,
            "monthly": days/30.4375, "daily": float(days)}.get(frequency, days/30.4375)

def _rate_per_period(annual_pct: float, frequency: str) -> float:
    return annual_pct / 100.0 / {"annual":1,"quarterly":4,"monthly":12,"daily":365}.get(frequency, 12)

def calc_amount(fee_type, fee_value, frequency, portfolio_value,
                num_meetings, d_from: date, d_to: date) -> float:
    if fee_type == "one_time":
        return float(fee_value)
    elif fee_type == "consultation":
        return round(float(fee_value) * int(num_meetings), 2)
    elif fee_type == "management":
        n      = _period_units(d_from, d_to, frequency)
        rate_p = _rate_per_period(float(fee_value), frequency)
        return round(float(portfolio_value) * rate_p * n, 2)
    return 0.0

def _pf_value(ac_id) -> float:
    total = 0.0
    for pf in get_portfolios_for_ac(ac_id):
        for h in get_portfolio_holdings(pf["id"]):
            p, _ = get_asset_price(h["symbol"])
            total += h["quantity"] * (p or h["avg_cost"])
    return total

# ── INVOICE HTML (landscape A4) ───────────────────────────────────────────

def _invoice_html(inv, adv_name, cl_name):
    rows_html    = ""
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
                f"<tr><td>{h['symbol']}</td>"
                f"<td style='color:#64748b'>{h['asset_class']}</td>"
                f"<td class='r'>{h['quantity']:g}</td>"
                f"<td class='r'>₹{indian_format(h['avg_cost'])}</td>"
                f"<td class='r'>₹{indian_format(p)}</td>"
                f"<td class='r' style='color:{pc};font-weight:600'>"
                f"₹{indian_format(abs(pnl))} "
                f"<span style='font-size:.7rem'>{sign}{pnl_pct:.1f}%</span></td></tr>"
            )
    total_pnl  = total_cur - total_buy
    total_pct  = (total_pnl / total_buy * 100) if total_buy else 0
    tpc        = "#15803d" if total_pnl >= 0 else "#b91c1c"
    tsign      = "+" if total_pnl >= 0 else ""

    fee_type  = inv["fee_type"]
    fee_val   = inv["fee_value"]
    fee_freq  = FEE_FREQS.get(inv.get("fee_frequency","annual"),"Annual")
    period_ln = ""
    if inv.get("period_from") and inv.get("period_to"):
        period_ln = f"<tr><td>Period</td><td>{fmt_date(inv['period_from'])} to {fmt_date(inv['period_to'])}</td></tr>"

    if fee_type == "management":
        fee_detail = (
            f"<tr><td>Fee Type</td><td>{FEE_TYPES['management']}</td></tr>"
            f"<tr><td>Rate Applied</td><td>{fee_val}% p.a. · {fee_freq}</td></tr>"
            f"<tr><td>Portfolio Value</td><td>₹{indian_format(inv.get('portfolio_value',0))}</td></tr>"
            f"{period_ln}"
        )
    elif fee_type == "consultation":
        fee_detail = (
            f"<tr><td>Fee Type</td><td>{FEE_TYPES['consultation']}</td></tr>"
            f"<tr><td>Rate per Meeting</td><td>₹{indian_format(fee_val)}</td></tr>"
            f"<tr><td>Meetings Billed</td><td>{inv.get('num_meetings',0)}</td></tr>"
            f"{period_ln}"
        )
    else:
        fee_detail = (
            f"<tr><td>Fee Type</td><td>{FEE_TYPES['one_time']}</td></tr>"
            f"{period_ln}"
        )

    notes_html = f"<p style='margin-top:.4rem;font-size:.75rem;color:#94a3b8'>{inv['notes']}</p>" if inv.get("notes") else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"/>
<style>
@page{{size:A4 landscape;margin:12mm 16mm;}}
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:'Segoe UI',Arial,sans-serif;font-size:11.5px;color:#1e293b;background:#fff;}}
.hdr{{display:flex;justify-content:space-between;align-items:flex-start;padding-bottom:12px;border-bottom:2.5px solid #1e293b;margin-bottom:16px;}}
.brand{{font-size:2.6rem;font-style:italic;font-weight:700;color:#1e293b;letter-spacing:-.04em;line-height:1;}}
.brand-sub{{font-size:.62rem;color:#94a3b8;letter-spacing:.14em;text-transform:uppercase;margin-top:.15rem;}}
.inv-meta{{text-align:right;}}
.inv-num{{font-size:.9rem;font-weight:700;}}
.inv-dates{{font-size:.75rem;color:#64748b;line-height:1.9;margin-top:.25rem;}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px;}}
.party{{background:#f8fafc;border-radius:6px;padding:10px 14px;border:1px solid #e2e8f0;}}
.party-lbl{{font-size:.6rem;font-weight:700;color:#94a3b8;letter-spacing:.1em;text-transform:uppercase;margin-bottom:4px;}}
.party-name{{font-size:.88rem;font-weight:700;}}
.amt-box{{background:linear-gradient(135deg,#1e293b,#334155);color:#fff;border-radius:9px;padding:12px 20px;margin-bottom:14px;display:flex;justify-content:space-between;align-items:center;}}
.amt-lbl{{font-size:.63rem;opacity:.72;letter-spacing:.1em;text-transform:uppercase;margin-bottom:.18rem;}}
.amt-val{{font-size:1.9rem;font-weight:700;letter-spacing:-.02em;}}
.amt-due{{font-size:.72rem;opacity:.62;margin-top:.18rem;}}
.sec-ttl{{font-size:.6rem;font-weight:700;color:#94a3b8;letter-spacing:.1em;text-transform:uppercase;margin-bottom:6px;padding-bottom:4px;border-bottom:1px solid #e2e8f0;}}
.ft{{width:100%;border-collapse:collapse;font-size:.79rem;}}
.ft td{{padding:3.5px 0;border-bottom:1px solid #f1f5f9;}}
.ft td:first-child{{color:#94a3b8;width:42%;}}
table.ht{{width:100%;border-collapse:collapse;font-size:.76rem;margin-top:6px;}}
table.ht th{{background:#1e293b;color:#fff;padding:6px 8px;font-weight:600;font-size:.65rem;letter-spacing:.04em;}}
table.ht td{{padding:5px 8px;border-bottom:1px solid #f1f5f9;vertical-align:middle;}}
table.ht tr:nth-child(even){{background:#f8fafc;}}
.r{{text-align:right;}}
.tot td{{background:#eff6ff!important;font-weight:700;font-size:.77rem;}}
.ftr{{margin-top:12px;padding-top:9px;border-top:1px solid #e2e8f0;display:flex;justify-content:space-between;align-items:center;}}
.ftr-brand{{font-size:.9rem;font-style:italic;font-weight:700;color:#94a3b8;}}
.ftr-note{{font-size:.65rem;color:#cbd5e1;text-align:right;}}
</style>
</head>
<body>
<div class="hdr">
  <div><div class="brand">Qavi</div><div class="brand-sub">Wealth Management</div></div>
  <div class="inv-meta">
    <div class="inv-num">{inv['invoice_number']}</div>
    <div class="inv-dates">Date: {fmt_date(inv['invoice_date'])}<br>Payment Due: {fmt_date(inv['due_date'])}</div>
  </div>
</div>
<div class="two">
  <div class="party"><div class="party-lbl">From</div><div class="party-name">{title_case(adv_name)}</div></div>
  <div class="party"><div class="party-lbl">Bill To</div><div class="party-name">{title_case(cl_name)}</div></div>
</div>
<div class="amt-box">
  <div>
    <div class="amt-lbl">Amount Due</div>
    <div class="amt-val">₹{indian_format(inv['amount'])}</div>
    <div class="amt-due">Due by {fmt_date(inv['due_date'])}</div>
  </div>
  <div style="text-align:right;opacity:.8;font-size:.75rem">{FEE_TYPES.get(fee_type,'')}</div>
</div>
<div class="two">
  <div>
    <div class="sec-ttl">Fee Details</div>
    <table class="ft"><tbody>{fee_detail}</tbody></table>
    {notes_html}
  </div>
  <div>
    <div class="sec-ttl">Portfolio Summary</div>
    <table class="ft"><tbody>
      <tr><td>Purchase Cost</td><td>₹{indian_format(total_buy)}</td></tr>
      <tr><td>Current Value</td><td>₹{indian_format(total_cur)}</td></tr>
      <tr><td>Overall P&amp;L</td>
          <td style="color:{tpc};font-weight:600">₹{indian_format(abs(total_pnl))} ({tsign}{total_pct:.2f}%)</td></tr>
    </tbody></table>
  </div>
</div>
<div class="sec-ttl" style="margin-top:4px">Holdings as of {fmt_date(str(date.today()))}</div>
<table class="ht">
  <thead><tr>
    <th>Symbol</th><th>Asset Class</th>
    <th class="r">Qty</th><th class="r">Purchase Cost</th>
    <th class="r">Current Price</th><th class="r">P&amp;L</th>
  </tr></thead>
  <tbody>
    {rows_html}
    <tr class="tot">
      <td colspan="3"><strong>Total Portfolio</strong></td>
      <td class="r">₹{indian_format(total_buy)}</td>
      <td class="r">₹{indian_format(total_cur)}</td>
      <td class="r" style="color:{tpc}">₹{indian_format(abs(total_pnl))} ({tsign}{total_pct:.2f}%)</td>
    </tr>
  </tbody>
</table>
<div class="ftr">
  <div><div class="ftr-brand">◈ Qavi</div><div style="font-size:.63rem;color:#cbd5e1">Generated {fmt_date(str(date.today()))}</div></div>
  <div class="ftr-note">Computer generated document.<br>For queries contact your advisor.</div>
</div>
</body></html>"""

# ── RENDER ────────────────────────────────────────────────────────────────

def render():
    if not st.session_state.get("user") or st.session_state.user["role"] != "advisor":
        navigate("login"); return

    user     = st.session_state.user
    advisor  = get_user_by_id(user["id"])
    adv_name = (advisor.get("full_name") or advisor.get("username","Advisor")) if advisor else "Advisor"
    clients  = get_advisor_clients(user["id"])
    invoices = get_invoices_for_advisor(user["id"])

    st.markdown('<div class="page-title">Invoices</div>', unsafe_allow_html=True)

    if is_market_open():
        st.warning("⚠️ Market is open. Invoice will use **yesterday's closing prices**.")

    tab1, tab2 = st.tabs([f"  🧾 All Invoices ({len(invoices)})  ", "  ➕ Generate Invoice  "])

    # ── ALL INVOICES ───────────────────────────────────────────────────────
    with tab1:
        if not invoices:
            st.info("No invoices yet.")
        else:
            total_paid   = sum(i["amount"] for i in invoices if i["status"] == "paid")
            total_unpaid = sum(i["amount"] for i in invoices if i["status"] == "unpaid")
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Invoices", len(invoices))
            m2.metric("Collected",      inr(total_paid))
            m3.metric("Outstanding",    inr(total_unpaid))
            st.markdown("<br>", unsafe_allow_html=True)

            for inv in invoices:
                client  = get_advisor_client(inv["advisor_client_id"])
                if not client: continue
                cl_name = title_case(client["client_name"])
                sc      = "#2ECC7A" if inv["status"] == "paid" else "#F5B731"

                with st.expander(
                    f"🧾  {inv['invoice_number']}  ·  {cl_name}  ·  "
                    f"₹{indian_format(inv['amount'])}  ·  {fmt_date(inv['invoice_date'])}"
                ):
                    c1, c2, c3 = st.columns(3)
                    c1.markdown(
                        f"**Invoice #:** {inv['invoice_number']}<br>"
                        f"**Date:** {fmt_date(inv['invoice_date'])}<br>"
                        f"**Due:** {fmt_date(inv['due_date'])}",
                        unsafe_allow_html=True)
                    c2.markdown(
                        f"**Fee Type:** {FEE_TYPES.get(inv['fee_type'],'—')}<br>"
                        f"**Amount:** ₹{indian_format(inv['amount'])}<br>"
                        f"**Status:** <span style='color:{sc};font-weight:600'>{inv['status'].upper()}</span>",
                        unsafe_allow_html=True)
                    c3.markdown(
                        f"**Portfolio Value:** ₹{indian_format(inv.get('portfolio_value',0))}<br>"
                        f"**Meetings:** {inv.get('num_meetings',0)}<br>"
                        f"**Period:** {fmt_date(inv.get('period_from',''))} – {fmt_date(inv.get('period_to',''))}",
                        unsafe_allow_html=True)

                    b1, b2, b3, b4 = st.columns(4)

                    if inv["status"] == "unpaid":
                        if b1.button("✅ Mark Paid",   key=f"mp_{inv['id']}", use_container_width=True):
                            update_invoice_status(inv["id"], "paid"); st.rerun()
                    else:
                        if b1.button("↩ Mark Unpaid", key=f"mu_{inv['id']}", use_container_width=True):
                            update_invoice_status(inv["id"], "unpaid"); st.rerun()

                    html_c = _invoice_html(inv, adv_name, client["client_name"])
                    b64    = base64.b64encode(html_c.encode()).decode()
                    b2.markdown(
                        f'<a href="data:text/html;base64,{b64}" download="{inv["invoice_number"]}.html" '
                        f'style="display:block;text-align:center;background:#161B27;color:#F0F4FF;'
                        f'padding:.42rem .9rem;border-radius:8px;border:1px solid #252D40;'
                        f'font-size:.84rem;text-decoration:none">📥 Download</a>',
                        unsafe_allow_html=True)
                    b3.markdown(
                        f'<a href="data:text/html;base64,{b64}" target="_blank" '
                        f'style="display:block;text-align:center;background:#161B27;color:#F0F4FF;'
                        f'padding:.42rem .9rem;border-radius:8px;border:1px solid #252D40;'
                        f'font-size:.84rem;text-decoration:none">🔍 Preview</a>',
                        unsafe_allow_html=True)

                    if b4.button("🗑 Delete", key=f"dinv_{inv['id']}", use_container_width=True):
                        st.session_state[f"del_inv_{inv['id']}"] = True; st.rerun()

                    if st.session_state.get(f"del_inv_{inv['id']}"):
                        st.error("Delete this invoice permanently?")
                        dy, dn = st.columns(2)
                        if dy.button("Yes, Delete", key=f"ydinv_{inv['id']}", use_container_width=True):
                            sb().table("invoices").delete().eq("id", inv["id"]).execute()
                            st.session_state.pop(f"del_inv_{inv['id']}", None); st.rerun()
                        if dn.button("Cancel", key=f"ndinv_{inv['id']}", use_container_width=True):
                            st.session_state.pop(f"del_inv_{inv['id']}", None); st.rerun()

    # ── GENERATE INVOICE ──────────────────────────────────────────────────
    with tab2:
        if not clients:
            st.info("No clients yet."); return

        cl_id = st.selectbox(
            "Client",
            [c["id"] for c in clients],
            format_func=lambda x: title_case(next(c["client_name"] for c in clients if c["id"] == x))
        )
        client  = next(c for c in clients if c["id"] == cl_id)
        pf_val  = _pf_value(cl_id)
        num_mtg = get_meeting_count_completed(cl_id)

        st.markdown(
            f'<p style="font-size:.82rem;color:#8892AA">'
            f'Portfolio Value: ₹{indian_format(pf_val)}  ·  Completed Meetings: {num_mtg}</p>',
            unsafe_allow_html=True)

        st.markdown("#### Dates")
        dc1, dc2 = st.columns(2)
        inv_date  = dc1.date_input("Invoice Date",        value=date.today())
        pay_basis = dc2.date_input("Payment Date Basis",  value=date.today(),
                                    help="Due date = 15 days from this date")

        pc1, pc2 = st.columns(2)
        pf_from  = pc1.date_input("Period From", value=date.today().replace(day=1))
        pf_to    = pc2.date_input("Period To",   value=date.today())

        st.markdown("#### Fee")
        fee_type  = st.selectbox("Fee Type", list(FEE_TYPES.keys()), format_func=lambda x: FEE_TYPES[x])
        fc1, fc2  = st.columns(2)
        fee_value = fc1.number_input(
            "Fee Value (₹ or % p.a.)",
            value=float(client.get("fee_value", 0)), min_value=0.0, step=100.0
        )
        freq = "annual"
        if fee_type == "management":
            freq = fc2.selectbox("Frequency", list(FEE_FREQS.keys()), format_func=lambda x: FEE_FREQS[x])
        else:
            fc2.empty()

        n_meetings = int(st.number_input("Meetings to Bill", min_value=0, value=num_mtg, step=1)) \
                     if fee_type == "consultation" else num_mtg

        st.markdown("---")

        # Calculate button
        if st.button("🧮 Calculate Fee", use_container_width=True):
            amount = calc_amount(fee_type, fee_value, freq, pf_val, n_meetings, pf_from, pf_to)
            st.session_state["_inv_calc"] = {
                "amount": amount, "fee_type": fee_type, "fee_value": fee_value,
                "freq": freq, "pf_val": pf_val, "n_meetings": n_meetings,
                "pf_from": str(pf_from), "pf_to": str(pf_to),
            }
            st.rerun()

        calc = st.session_state.get("_inv_calc")
        if calc:
            amount = calc["amount"]
            # Show breakdown
            if calc["fee_type"] == "management":
                n_u    = _period_units(
                    date.fromisoformat(calc["pf_from"]),
                    date.fromisoformat(calc["pf_to"]),
                    calc["freq"]
                )
                rate_p = _rate_per_period(calc["fee_value"], calc["freq"])
                detail = (f"₹{indian_format(calc['pf_val'])} × "
                          f"{rate_p*100:.6f}% × {n_u:.4f} {FEE_FREQS[calc['freq']].lower()}(s)")
            elif calc["fee_type"] == "consultation":
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
                    advisor_id    = user["id"],
                    ac_id         = cl_id,
                    fee_type      = fee_type,
                    fee_value     = fee_value,
                    fee_frequency = freq,
                    amount        = amount,
                    portfolio_value = pf_val,
                    num_meetings  = n_meetings,
                    period_from   = str(pf_from),
                    period_to     = str(pf_to),
                    notes         = notes,
                    invoice_date  = str(inv_date),
                    due_date      = due_date,
                )
                st.session_state.pop("_inv_calc", None)
                st.success(f"Invoice {inv_num} created!"); st.rerun()
        else:
            st.info("Configure the fee above, then click **Calculate Fee** to preview before generating.")
