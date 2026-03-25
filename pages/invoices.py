import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.db import (get_advisor_clients, get_advisor_client, get_invoices_for_advisor,
                      create_invoice, update_invoice_status, get_portfolios_for_ac,
                      get_portfolio_holdings, get_asset_price, get_meeting_count_completed,
                      get_user_by_id, sb, decrypt_user, get_fixed_income,
                      rpc_calc_invoice)
from utils.crypto import inr, indian_format, fmt_date, title_case
from utils.session import navigate, back_button
from utils.market import is_market_open
from datetime import date, timedelta
import base64

FEE_TYPES = {"one_time":"One-Time Fixed Fee","consultation":"Per Consultation","management":"AUM Management"}
FEE_FREQS = {"annual":"Annual","quarterly":"Quarterly","monthly":"Monthly","daily":"Daily"}
DEBT_CLASSES = {"Bond","Bank FD"}

def _is_debt(ac): return ac in DEBT_CLASSES

# ── PERIOD COUNTING ───────────────────────────────────────────────────────
def _next_boundary(d, freq):
    if freq == "monthly":
        m = d.month+1; y = d.year+(m-1)//12; m = ((m-1)%12)+1
        return d.replace(year=y, month=m, day=1)
    elif freq == "quarterly":
        m = d.month+3; y = d.year+(m-1)//12; m = ((m-1)%12)+1
        return d.replace(year=y, month=m, day=1)
    elif freq == "annual":
        return d.replace(year=d.year+1, month=1, day=1)
    return d + timedelta(days=1)

def _count_periods(d_from, d_to, freq):
    if d_from >= d_to: return 0
    if freq == "daily": return (d_to-d_from).days
    count=0; cursor=d_from
    while cursor < d_to: count+=1; cursor=_next_boundary(cursor,freq)
    return count

def _rate_per_period(pct, freq):
    return pct/100.0/{"annual":1,"quarterly":4,"monthly":12,"daily":365}.get(freq,12)

# ── FEE CALCULATION ───────────────────────────────────────────────────────
def calc_amount(fee_type, fee_value, freq, pf_value, num_meetings,
                d_from, d_to, holdings=None):
    if fee_type == "one_time":   return round(float(fee_value), 2)
    if fee_type == "consultation": return round(float(fee_value)*int(num_meetings), 2)
    if fee_type == "management":
        if holdings:
            dv = ndv = 0.0
            for h in holdings:
                p,_ = get_asset_price(h["symbol"])
                v   = h["quantity"]*(p or h["avg_cost"])
                if _is_debt(h.get("asset_class","")): dv += v
                else: ndv += v
            days   = (d_to-d_from).days
            df     = round(dv*(float(fee_value)/100.0/365)*days, 2)
            n      = _count_periods(d_from, d_to, freq)
            rp     = _rate_per_period(float(fee_value), freq)
            ndf    = round(ndv*rp*n, 2)
            return round(df+ndf, 2)
        n  = _count_periods(d_from, d_to, freq)
        rp = _rate_per_period(float(fee_value), freq)
        return round(float(pf_value)*rp*n, 2)
    return 0.0

def _pf_value_and_holdings(ac_id):
    total, all_h = 0.0, []
    for pf in get_portfolios_for_ac(ac_id):
        for h in get_portfolio_holdings(pf["id"]):
            p,_ = get_asset_price(h["symbol"])
            total += h["quantity"]*(p or h["avg_cost"])
            all_h.append(h)
    return total, all_h

def _note_rate(notes):
    if not notes: return None
    for part in notes.split("|"):
        p = part.strip()
        if p.startswith("rate:"):
            try: return float(p[5:].replace("%","").strip())
            except: pass
    return None

def _get_fi_info(symbol):
    try:
        for row in get_fixed_income():
            if row["symbol"] == symbol:
                return row.get("interest_rate",0), row.get("maturity_date","—"), row.get("tenure_years","—")
    except: pass
    return 0, "—", "—"

# ── INVOICE HTML ──────────────────────────────────────────────────────────
# Single consistent margin used BOTH in browser and in print: 14mm all sides on A4 landscape.
# The .page div mirrors that margin so browser view looks identical to print.

def _invoice_html(inv, adv_user, client, rpc_rows=None):
    adv_name  = title_case(adv_user.get("full_name") or adv_user.get("username",""))
    dec_adv   = decrypt_user(adv_user) if adv_user else {}
    adv_phone = dec_adv.get("phone","") or "—"
    adv_addr  = dec_adv.get("address","") or "—"
    cl_name   = title_case(client.get("client_name",""))
    cl_phone  = client.get("client_phone","") or "—"

    eq_h, debt_h = [], []
    total_eq_buy = total_eq_cur = 0.0
    total_db_buy = total_db_cur = 0.0

    if rpc_rows:
        # Use pre-calculated data from RPC — zero extra DB calls
        for r in rpc_rows:
            ac   = r.get("holding_ac","")
            bv   = r.get("holding_buy_val", 0)
            cv   = r.get("holding_cur_val", 0)
            pnl  = r.get("holding_pnl", 0)
            ppct = r.get("holding_pnl_pct", 0)
            if _is_debt(ac):
                total_db_buy += bv; total_db_cur += cv
                rate  = r.get("fi_interest_rate", 0) or 0
                mat_r = r.get("fi_maturity","—") or "—"
                mat_s = fmt_date(mat_r) if mat_r not in ("—","N/A","") else "—"
                debt_h.append((r["holding_symbol"], ac, r["holding_qty"], bv, rate, mat_s))
            else:
                total_eq_buy += bv; total_eq_cur += cv
                eq_h.append((r["holding_symbol"], ac, r["holding_qty"],
                              r["holding_avg_cost"], r["holding_close"], pnl, ppct, bv, cv))
    else:
        # Fallback: query DB directly (used when viewing old invoices without cached RPC data)
        for pf in get_portfolios_for_ac(inv["advisor_client_id"]):
            for h in get_portfolio_holdings(pf["id"]):
                p,_   = get_asset_price(h["symbol"])
                cp    = p or h["avg_cost"]
                bv    = h["quantity"] * h["avg_cost"]
                cv    = h["quantity"] * cp
                pnl   = cv - bv
                ppct  = ((cp-h["avg_cost"])/h["avg_cost"]*100) if h["avg_cost"] else 0
                ac    = h.get("asset_class","")
                if _is_debt(ac):
                    total_db_buy += bv; total_db_cur += cv
                    rate, mat, _ = _get_fi_info(h["symbol"])
                    rate = _note_rate(h.get("notes","")) or rate
                    mat_s = fmt_date(mat) if mat and mat not in ("—","N/A","") else "—"
                    debt_h.append((h["symbol"], ac, h["quantity"], bv, rate, mat_s))
                else:
                    total_eq_buy += bv; total_eq_cur += cv
                    eq_h.append((h["symbol"], ac, h["quantity"], h["avg_cost"], cp, pnl, ppct, bv, cv))

    has_eq   = bool(eq_h)
    has_debt = bool(debt_h)
    both     = has_eq and has_debt

    # Build equity table HTML
    eq_tbl = ""
    if has_eq:
        rows = ""
        for sym,ac,qty,buy,cur,pnl,ppct,bv,cv in sorted(eq_h, key=lambda x:-x[8]):
            pc   = "#15803d" if pnl>=0 else "#b91c1c"
            sign = "+" if pnl>=0 else ""
            rows += (f"<tr>"
                     f"<td class='tl fw'>{sym}</td><td class='tl gr'>{ac}</td>"
                     f"<td class='tc'>{qty:g}</td>"
                     f"<td class='tr'>₹{indian_format(buy)}</td>"
                     f"<td class='tr'>₹{indian_format(cur)}</td>"
                     f"<td class='tr' style='color:{pc};font-weight:600'>"
                     f"₹{indian_format(abs(pnl))}&nbsp;<span class='sm'>{sign}{ppct:.1f}%</span></td>"
                     f"</tr>")
        ep    = total_eq_cur - total_eq_buy
        epct  = (ep/total_eq_buy*100) if total_eq_buy else 0
        tpc_e = "#15803d" if ep>=0 else "#b91c1c"
        tsg_e = "+" if ep>=0 else ""
        eq_tbl = (f'<p class="sec-lbl">Equity &amp; Market Holdings</p>'
                  f'<table class="ht"><thead><tr>'
                  f'<th class="hl">Symbol</th><th class="hl">Asset Class</th>'
                  f'<th>Qty</th><th>Purchase Cost</th><th>Closing Price</th><th>P&amp;L</th>'
                  f'</tr></thead><tbody>{rows}'
                  f'<tr class="tot"><td class="tl" colspan="2"><b>Equity Total</b></td>'
                  f'<td class="tc">—</td>'
                  f'<td class="tr">₹{indian_format(total_eq_buy)}</td>'
                  f'<td class="tr">₹{indian_format(total_eq_cur)}</td>'
                  f'<td class="tr" style="color:{tpc_e}">₹{indian_format(abs(ep))}&nbsp;({tsg_e}{epct:.2f}%)</td>'
                  f'</tr></tbody></table>')

    # Build debt table HTML — no rating or issuer columns
    debt_tbl = ""
    if has_debt:
        rows = ""
        for sym,ac,qty,invested,rate,mat in sorted(debt_h, key=lambda x:-x[3]):
            rows += (f"<tr>"
                     f"<td class='tl fw'>{sym}</td><td class='tl gr'>{ac}</td>"
                     f"<td class='tc'>{qty:g}</td>"
                     f"<td class='tr'>₹{indian_format(invested)}</td>"
                     f"<td class='tr' style='color:#15803d;font-weight:600'>{rate:.2f}% p.a.</td>"
                     f"<td class='tc'>{mat}</td>"
                     f"</tr>")
        debt_tbl = (f'<p class="sec-lbl">Debt &amp; Fixed Income Holdings</p>'
                    f'<table class="ht"><thead><tr>'
                    f'<th class="hl">Symbol</th><th class="hl">Type</th>'
                    f'<th>Qty / Amount</th><th>Invested</th>'
                    f'<th>Interest Rate</th><th>Maturity</th>'
                    f'</tr></thead><tbody>{rows}'
                    f'<tr class="tot"><td class="tl" colspan="3"><b>Debt Total</b></td>'
                    f'<td class="tr">₹{indian_format(total_db_buy)}</td>'
                    f'<td colspan="2" class="tl" style="color:#94a3b8;font-size:.7rem">'
                    f'Interest accruing daily</td>'
                    f'</tr></tbody></table>')

    # Combined summary — only when both present
    combined_tbl = ""
    if both:
        grand_b = total_eq_buy + total_db_buy
        grand_c = total_eq_cur + total_db_cur
        grand_p = grand_c - grand_b
        gpct    = (grand_p/grand_b*100) if grand_b else 0
        tpc_g   = "#15803d" if grand_p>=0 else "#b91c1c"
        tsg_g   = "+" if grand_p>=0 else ""
        eq_p    = total_eq_cur - total_eq_buy
        eq_pct  = (eq_p/total_eq_buy*100) if total_eq_buy else 0
        tpc_eq  = "#15803d" if eq_p>=0 else "#b91c1c"
        tsg_eq  = "+" if eq_p>=0 else ""
        combined_tbl = (
            f'<p class="sec-lbl">Portfolio Total</p>'
            f'<table class="ht"><thead><tr>'
            f'<th class="hl">Category</th><th>Invested</th><th>Current Value</th><th>P&amp;L / Return</th>'
            f'</tr></thead><tbody>'
            f'<tr><td class="tl fw">Equity &amp; Market</td>'
            f'<td class="tr">₹{indian_format(total_eq_buy)}</td>'
            f'<td class="tr">₹{indian_format(total_eq_cur)}</td>'
            f'<td class="tr" style="color:{tpc_eq};font-weight:600">₹{indian_format(abs(eq_p))}&nbsp;({tsg_eq}{eq_pct:.2f}%)</td>'
            f'</tr>'
            f'<tr><td class="tl fw">Debt &amp; Fixed Income</td>'
            f'<td class="tr">₹{indian_format(total_db_buy)}</td>'
            f'<td class="tr">₹{indian_format(total_db_cur)}</td>'
            f'<td class="tr" style="color:#64748b">Interest accruing</td>'
            f'</tr>'
            f'<tr class="tot"><td class="tl"><b>Grand Total</b></td>'
            f'<td class="tr">₹{indian_format(grand_b)}</td>'
            f'<td class="tr">₹{indian_format(grand_c)}</td>'
            f'<td class="tr" style="color:{tpc_g}">₹{indian_format(abs(grand_p))}&nbsp;({tsg_g}{gpct:.2f}%)</td>'
            f'</tr></tbody></table>'
        )

    # Portfolio summary box
    total_buy = total_eq_buy + total_db_buy
    total_cur = total_eq_cur + total_db_cur
    total_pnl = total_cur - total_buy
    total_pct = (total_pnl/total_buy*100) if total_buy else 0
    tpc  = "#15803d" if total_pnl>=0 else "#b91c1c"
    tsign = "+" if total_pnl>=0 else ""

    # Fee detail
    fee_type = inv["fee_type"]
    fee_val  = inv["fee_value"]
    fee_freq = FEE_FREQS.get(inv.get("fee_frequency","annual"),"Annual")
    pf_val   = inv.get("portfolio_value",0)
    period_r = ""
    if inv.get("period_from") and inv.get("period_to"):
        period_r = (f"<tr><td class='lbl'>Period</td>"
                    f"<td>{fmt_date(inv['period_from'])} to {fmt_date(inv['period_to'])}</td></tr>")
    if fee_type == "management":
        fee_rows = (f"<tr><td class='lbl'>Fee Type</td><td>{FEE_TYPES['management']}</td></tr>"
                    f"<tr><td class='lbl'>Annual Rate</td><td>{fee_val}%</td></tr>"
                    f"<tr><td class='lbl'>Billing Frequency</td><td>{fee_freq}</td></tr>"
                    f"<tr><td class='lbl'>Portfolio Value</td><td>₹{indian_format(pf_val)}</td></tr>"
                    f"{period_r}")
    elif fee_type == "consultation":
        fee_rows = (f"<tr><td class='lbl'>Fee Type</td><td>{FEE_TYPES['consultation']}</td></tr>"
                    f"<tr><td class='lbl'>Rate per Meeting</td><td>₹{indian_format(fee_val)}</td></tr>"
                    f"<tr><td class='lbl'>Meetings Billed</td><td>{inv.get('num_meetings',0)}</td></tr>"
                    f"{period_r}")
    else:
        fee_rows = (f"<tr><td class='lbl'>Fee Type</td><td>{FEE_TYPES['one_time']}</td></tr>"
                    f"{period_r}")
    notes_html = (f"<p style='margin-top:.4rem;font-size:.72rem;color:#64748b'>{inv['notes']}</p>"
                  if inv.get("notes") else "")

    # MARGIN NOTE:
    # @page margin = 14mm all sides on A4 landscape (297×210mm).
    # .page padding = 14mm mirrors this exactly so browser view matches print.
    # No separate screen vs print sizing — what you see is what prints.
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<title>{inv['invoice_number']}</title>
<style>
@page {{
  size: A4 landscape;
  margin: 14mm;
}}
*, *::before, *::after {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  font-family: 'Segoe UI', Arial, sans-serif;
  font-size: 11px;
  color: #1e293b;
  background: #fff;
  line-height: 1.5;
}}
/* .page: A4 landscape content area — identical in browser and print */
.page {{
  width: 269mm;          /* 297mm minus 2×14mm margins */
  min-height: 175mm;     /* 210mm minus 2×14mm — landscape A4 height */
  margin: 14mm auto;
  padding: 0;
  background: #fff;
  box-shadow: 0 2px 20px rgba(0,0,0,.12);   /* visible shadow in browser */
}}
/* Landscape hint for browser — rotate viewport feel */
html {{
  background: #e2e8f0;   /* grey outside the page — like a PDF viewer */
  min-height: 100%;
}}
@media print {{
  html  {{ background: #fff; }}
  .page {{ width:100%; margin:0; box-shadow:none; }}
  body  {{ margin:0; }}
}}

/* HEADER */
.hdr {{ display:flex; justify-content:space-between; align-items:flex-start;
        padding-bottom:10px; border-bottom:2px solid #1e293b; margin-bottom:13px; }}
.brand {{ font-size:2rem; font-weight:900; letter-spacing:.1em; line-height:1; font-variant:small-caps; }}
.brand-sub {{ font-size:.57rem; color:#94a3b8; letter-spacing:.18em; text-transform:uppercase; margin-top:.18rem; }}
.inv-meta {{ text-align:right; }}
.inv-num {{ font-size:.88rem; font-weight:700; margin-bottom:.3rem; }}
.dt {{ border-collapse:collapse; }}
.dt td {{ padding:1.5px 0; font-size:.71rem; color:#64748b; }}
.dl {{ text-align:right; padding-right:4px; white-space:nowrap; }}
.dv {{ text-align:right; white-space:nowrap; font-weight:500; color:#1e293b; }}

/* GRID */
.two {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:12px; }}

/* PARTY */
.party {{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:5px; padding:8px 12px; }}
.plbl {{ font-size:.54rem; font-weight:700; color:#94a3b8; letter-spacing:.13em; text-transform:uppercase; margin-bottom:3px; }}
.pname {{ font-size:.86rem; font-weight:700; margin-bottom:2px; }}
.pdet {{ font-size:.71rem; color:#64748b; line-height:1.65; }}

/* AMOUNT BOX */
.amt-box {{ background:linear-gradient(135deg,#1e293b,#2d4060); color:#fff;
            border-radius:7px; padding:11px 18px; margin-bottom:12px;
            display:flex; justify-content:space-between; align-items:center; }}
.amt-lbl {{ font-size:.57rem; opacity:.68; letter-spacing:.12em; text-transform:uppercase; margin-bottom:.14rem; }}
.amt-val {{ font-size:1.75rem; font-weight:800; }}
.amt-due {{ font-size:.68rem; opacity:.58; margin-top:.14rem; }}
.amt-right {{ text-align:right; font-size:.71rem; opacity:.82; line-height:1.7; }}

/* SECTION LABEL */
.sec-lbl {{
  font-size:.57rem; font-weight:700; color:#94a3b8; letter-spacing:.1em;
  text-transform:uppercase; margin:10px 0 5px 0; padding-bottom:3px;
  border-bottom:1px solid #e2e8f0;
}}

/* FEE TABLE */
.ft {{ width:100%; border-collapse:collapse; font-size:.76rem; }}
.ft td {{ padding:3px 0; border-bottom:1px solid #f1f5f9; vertical-align:top; }}
.lbl {{ color:#94a3b8; width:40%; padding-right:8px; }}

/* HOLDINGS TABLE */
table.ht {{ width:100%; border-collapse:collapse; font-size:.73rem; margin-bottom:8px; }}
table.ht thead tr {{ background:#1e293b; color:#fff; -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
table.ht th {{ padding:5px 8px; font-weight:600; font-size:.61rem; letter-spacing:.04em; text-align:center; }}
table.ht th.hl {{ text-align:left; }}
table.ht td {{ padding:5px 8px; border-bottom:1px solid #f1f5f9; vertical-align:middle; }}
table.ht tr:nth-child(even) {{ background:#f8fafc; }}
.tl {{ text-align:left; }} .tc {{ text-align:center; }} .tr {{ text-align:right; }}
.fw {{ font-weight:600; }} .gr {{ color:#64748b; }} .sm {{ font-size:.66rem; margin-left:2px; }}
.tot td {{ background:#eff6ff!important; font-weight:700; color:#1e293b; font-size:.74rem;
           border-top:1.5px solid #bfdbfe; -webkit-print-color-adjust:exact; print-color-adjust:exact; }}

/* FOOTER */
.ftr {{ margin-top:10px; padding-top:8px; border-top:1px solid #e2e8f0;
        display:flex; justify-content:space-between; align-items:center; }}
.ftr-brand {{ font-size:.86rem; font-weight:900; letter-spacing:.1em; color:#94a3b8; font-variant:small-caps; }}
.ftr-note {{ font-size:.6rem; color:#cbd5e1; text-align:right; line-height:1.6; }}
</style>
</head>
<body>
<div class="page">

<div class="hdr">
  <div><div class="brand">QAVI</div><div class="brand-sub">Wealth Management</div></div>
  <div class="inv-meta">
    <div class="inv-num">{inv['invoice_number']}</div>
    <table class="dt">
      <tr><td class="dl">Date</td><td style="padding:0 5px;color:#94a3b8">:</td><td class="dv">{fmt_date(inv['invoice_date'])}</td></tr>
      <tr><td class="dl">Payment Due</td><td style="padding:0 5px;color:#94a3b8">:</td><td class="dv">{fmt_date(inv['due_date'])}</td></tr>
    </table>
  </div>
</div>

<div class="two">
  <div class="party">
    <div class="plbl">From</div><div class="pname">{adv_name}</div>
    <div class="pdet">Phone: {adv_phone}<br>{adv_addr}</div>
  </div>
  <div class="party">
    <div class="plbl">Bill To</div><div class="pname">{cl_name}</div>
    <div class="pdet">Phone: {cl_phone}</div>
  </div>
</div>

<div class="amt-box">
  <div>
    <div class="amt-lbl">Amount Due</div>
    <div class="amt-val">₹{indian_format(inv['amount'])}</div>
    <div class="amt-due">Due by {fmt_date(inv['due_date'])}</div>
  </div>
  <div class="amt-right">{FEE_TYPES.get(fee_type,'')}<br>
    <span style="opacity:.65">{fee_freq if fee_type=='management' else ''}</span>
  </div>
</div>

<div class="two">
  <div>
    <p class="sec-lbl" style="margin-top:0">Fee Details</p>
    <table class="ft"><tbody>{fee_rows}</tbody></table>
    {notes_html}
  </div>
  <div>
    <p class="sec-lbl" style="margin-top:0">Portfolio Summary</p>
    <table class="ft"><tbody>
      <tr><td class="lbl">Total Invested</td><td>₹{indian_format(total_buy)}</td></tr>
      <tr><td class="lbl">Current Value</td><td>₹{indian_format(total_cur)}</td></tr>
      <tr><td class="lbl">Overall P&amp;L</td>
          <td style="color:{tpc};font-weight:600">₹{indian_format(abs(total_pnl))} ({tsign}{total_pct:.2f}%)</td></tr>
      {"<tr><td class='lbl'>Equity Value</td><td>₹" + indian_format(total_eq_cur) + "</td></tr>" if both else ""}
      {"<tr><td class='lbl'>Debt Value</td><td>₹" + indian_format(total_db_cur) + "</td></tr>" if both else ""}
    </tbody></table>
  </div>
</div>

<p style="font-size:.58rem;color:#94a3b8;letter-spacing:.05em;margin:2px 0 0 0">
  HOLDINGS AS OF {fmt_date(str(date.today())).upper()}
</p>

{eq_tbl}
{debt_tbl}
{combined_tbl}

<div class="ftr">
  <div><div class="ftr-brand">◈ QAVI</div>
    <div style="font-size:.59rem;color:#cbd5e1">Generated {fmt_date(str(date.today()))}</div>
  </div>
  <div class="ftr-note">Computer generated document.<br>For queries contact your advisor.</div>
</div>

</div>
</body>
</html>"""

# ── RENDER ────────────────────────────────────────────────────────────────
def render():
    if not st.session_state.get("user") or st.session_state.user["role"] not in ("advisor","owner"):
        navigate("login"); return
    back_button(fallback="profile", key="top")

    user     = st.session_state.user
    advisor  = get_user_by_id(user["id"])
    clients  = get_advisor_clients(user["id"])
    invoices = get_invoices_for_advisor(user["id"])

    st.markdown('<div class="page-title">Invoices</div>', unsafe_allow_html=True)

    if is_market_open():
        st.warning("⚠️ Market open (closes 15:30 IST) — invoice uses yesterday's closing prices.")

    tab1, tab2 = st.tabs([f"  🧾 All Invoices ({len(invoices)})  ", "  ➕ Generate Invoice  "])

    with tab1:
        if not invoices:
            st.info("No invoices yet.")
        else:
            paid   = sum(i["amount"] for i in invoices if i["status"]=="paid")
            unpaid = sum(i["amount"] for i in invoices if i["status"]=="unpaid")
            m1,m2,m3 = st.columns(3)
            m1.metric("Total",       len(invoices))
            m2.metric("Collected",   inr(paid))
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

                    b1,b2,b3,b4,b5 = st.columns(5)
                    if inv["status"]=="unpaid":
                        if b1.button("✅ Mark Paid",  key=f"mp_{inv['id']}", use_container_width=True):
                            update_invoice_status(inv["id"],"paid"); st.rerun()
                    else:
                        if b1.button("↩ Unpaid",     key=f"mu_{inv['id']}", use_container_width=True):
                            update_invoice_status(inv["id"],"unpaid"); st.rerun()

                    html_c = _invoice_html(inv, advisor or {}, client,
                                           rpc_rows=rpc_calc_invoice(
                                               inv["advisor_client_id"],
                                               inv.get("period_from", str(date.today().replace(day=1))),
                                               inv.get("period_to",   str(date.today())),
                                               inv.get("fee_value",1), inv.get("fee_frequency","annual"),
                                               inv.get("fee_type","management"), inv.get("num_meetings",0)
                                           ))
                    b64 = base64.b64encode(html_c.encode()).decode()

                    # Download
                    b2.markdown(
                        f'<a href="data:text/html;base64,{b64}" '
                        f'download="{inv["invoice_number"]}.html" '
                        f'style="display:block;text-align:center;background:#161B27;color:#F0F4FF;'
                        f'padding:.42rem .9rem;border-radius:8px;border:1px solid #252D40;'
                        f'font-size:.84rem;text-decoration:none">📥 Download</a>',
                        unsafe_allow_html=True)

                    # Preview
                    if b3.button("🔍 Preview", key=f"prev_{inv['id']}", use_container_width=True):
                        st.session_state[f"show_prev_{inv['id']}"] = \
                            not st.session_state.get(f"show_prev_{inv['id']}", False)
                    if st.session_state.get(f"show_prev_{inv['id']}", False):
                        import streamlit.components.v1 as components
                        st.markdown("---")
                        components.html(html_c, height=620, scrolling=True)

                    # Email invoice to client
                    if b4.button("📧 Email", key=f"em_{inv['id']}", use_container_width=True):
                        st.session_state[f"show_email_{inv['id']}"] = \
                            not st.session_state.get(f"show_email_{inv['id']}", False)
                    if st.session_state.get(f"show_email_{inv['id']}", False):
                        with st.form(f"email_form_{inv['id']}"):
                            client_email = client.get("client_email","")
                            to_email = st.text_input("Send to email",
                                                     value=client_email,
                                                     key=f"to_{inv['id']}")
                            to_name  = st.text_input("Recipient name",
                                                     value=title_case(client.get("client_name","")),
                                                     key=f"tn_{inv['id']}")
                            if st.form_submit_button("📤 Send Invoice", use_container_width=True):
                                if not to_email or "@" not in to_email:
                                    st.error("Valid email required.")
                                else:
                                    from utils.email_utils import send_invoice_email
                                    adv_name = title_case(advisor.get("full_name","") or
                                                           advisor.get("username","Advisor"))
                                    ok, msg = send_invoice_email(
                                        to_email=to_email.strip(),
                                        to_name=to_name.strip(),
                                        advisor_name=adv_name,
                                        invoice_number=inv["invoice_number"],
                                        amount=inv["amount"],
                                        due_date=fmt_date(inv["due_date"]),
                                        html_content=html_c,
                                    )
                                    if ok:
                                        # Log the send
                                        try:
                                            sb().table("invoice_emails").insert({
                                                "invoice_id":      inv["id"],
                                                "invoice_number":  inv["invoice_number"],
                                                "recipient_email": to_email.strip(),
                                                "status": "sent",
                                            }).execute()
                                        except Exception:
                                            pass
                                        st.success(f"✅ {msg}")
                                        st.session_state.pop(f"show_email_{inv['id']}", None)
                                    else:
                                        st.error(msg)

                    if b5.button("🗑 Delete", key=f"dinv_{inv['id']}", use_container_width=True):
                        st.session_state[f"del_{inv['id']}"] = True; st.rerun()
                    if st.session_state.get(f"del_{inv['id']}"):
                        st.error("Delete this invoice permanently?")
                        dy,dn = st.columns(2)
                        if dy.button("Yes", key=f"ydi_{inv['id']}", use_container_width=True):
                            try: sb().table("invoices").delete().eq("id",inv["id"]).execute()
                            except: sb().table("invoices").delete().eq("invoice_number",inv["invoice_number"]).execute()
                            st.session_state.pop(f"del_{inv['id']}",None); st.rerun()
                        if dn.button("No", key=f"ndi_{inv['id']}", use_container_width=True):
                            st.session_state.pop(f"del_{inv['id']}",None); st.rerun()

    with tab2:
        if not clients:
            st.info("No clients yet."); return

        cl_id  = st.selectbox("Client", [c["id"] for c in clients],
                              format_func=lambda x: title_case(next(c["client_name"] for c in clients if c["id"]==x)))
        client = next(c for c in clients if c["id"]==cl_id)
        num_mtg = get_meeting_count_completed(cl_id)

        st.markdown("#### Dates")
        dc1,dc2 = st.columns(2)
        inv_date  = dc1.date_input("Invoice Date",       value=date.today())
        pay_basis = dc2.date_input("Payment Date Basis", value=date.today(), help="Due = 15 days from this")
        pc1,pc2  = st.columns(2)
        pf_from  = pc1.date_input("Period From", value=date.today().replace(day=1))
        pf_to    = pc2.date_input("Period To",   value=date.today())

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

        n_mtg = int(st.number_input("Meetings to Bill", min_value=0, value=num_mtg, step=1)) \
                if fee_type=="consultation" else num_mtg

        st.markdown("---")
        if st.button("🧮 Calculate Fee", use_container_width=True):
            with st.spinner("Calculating…"):
                # Single RPC call — all arithmetic done in Postgres
                rows = rpc_calc_invoice(cl_id, pf_from, pf_to,
                                        fee_value, freq, fee_type, n_mtg)

            if rows:
                r0       = rows[0]  # fee summary is same on every row
                amount   = r0.get("fee_amount", 0)
                dv       = r0.get("debt_aum", 0)
                ndv      = r0.get("non_debt_aum", 0)
                pf_val   = r0.get("total_aum", 0)
                df       = r0.get("debt_fee", 0)
                ndf      = r0.get("non_debt_fee", 0)
            else:
                # RPC not yet deployed — fall back to Python
                pf_val, pf_h = _pf_value_and_holdings(cl_id)
                dv  = sum(h["quantity"]*(get_asset_price(h["symbol"])[0] or h["avg_cost"])
                          for h in pf_h if _is_debt(h.get("asset_class","")))
                ndv = pf_val - dv
                amount = calc_amount(fee_type, fee_value, freq, pf_val, n_mtg,
                                     pf_from, pf_to, holdings=pf_h if fee_type=="management" else None)
                df = ndf = 0

            # Build breakdown string
            days    = (pf_to - pf_from).days
            if fee_type == "management":
                parts_c = []
                if dv > 0:
                    parts_c.append(f"Debt ₹{indian_format(dv)} × {fee_value}%÷365 × {days}d = ₹{indian_format(df)}")
                if ndv > 0:
                    div_map = {"annual":1,"quarterly":4,"monthly":12,"daily":365}
                    div     = div_map.get(freq, 12)
                    parts_c.append(f"Market ₹{indian_format(ndv)} × {fee_value}%÷{div} = ₹{indian_format(ndf)}")
                if not parts_c:
                    parts_c.append(f"₹{indian_format(pf_val)} × {fee_value}%")
                detail = " + ".join(parts_c)
            elif fee_type == "consultation":
                detail = f"{n_mtg} meetings × ₹{indian_format(fee_value)}"
            else:
                detail = "Fixed one-time fee"

            # AUM info line
            info_parts = [f"Total AUM: ₹{indian_format(pf_val)}"]
            if dv > 0:  info_parts.append(f"Debt: ₹{indian_format(dv)}")
            if ndv > 0: info_parts.append(f"Market: ₹{indian_format(ndv)}")
            st.markdown(f'<p style="font-size:.82rem;color:#8892AA">{" · ".join(info_parts)}</p>', unsafe_allow_html=True)

            st.session_state["_inv_calc"] = {
                "amount": amount, "fee_type": fee_type, "fee_value": fee_value,
                "freq": freq, "pf_val": pf_val, "n_meetings": n_mtg,
                "pf_from": str(pf_from), "pf_to": str(pf_to),
                "dv": dv, "ndv": ndv, "detail": detail,
                "rpc_rows": rows,   # store for invoice HTML generation
            }
            st.rerun()

        calc = st.session_state.get("_inv_calc")
        if calc:
            amount    = calc["amount"]
            detail    = calc.get("detail", "")
            # Read all values from session state — not outer widget scope
            # (outer scope variables are undefined after st.rerun())
            _fee_type  = calc["fee_type"]
            _fee_value = calc["fee_value"]
            _freq      = calc["freq"]
            _pf_val    = calc["pf_val"]
            _n_mtg     = calc["n_meetings"]
            _pf_from   = calc["pf_from"]
            _pf_to     = calc["pf_to"]

            st.markdown(f"""
            <div style="background:#1E2535;border:1px solid #2ECC7A;border-radius:10px;
                padding:1rem 1.2rem;margin:.4rem 0">
                <div style="font-size:.76rem;color:#8892AA;margin-bottom:.3rem">{detail}</div>
                <div style="font-size:1.5rem;font-weight:700;color:#2ECC7A">= ₹{indian_format(amount)}</div>
            </div>""", unsafe_allow_html=True)

            notes = st.text_input("Notes (optional)", key="inv_notes")
            if st.button("✅ Generate Invoice", use_container_width=True):
                due = str(pay_basis + timedelta(days=15))
                try:
                    inv_num = create_invoice(
                        advisor_id=user["id"], ac_id=cl_id,
                        fee_type=_fee_type, fee_value=_fee_value, fee_frequency=_freq,
                        amount=amount, portfolio_value=_pf_val, num_meetings=_n_mtg,
                        period_from=_pf_from, period_to=_pf_to, notes=notes,
                        invoice_date=str(inv_date), due_date=due,
                    )
                    st.session_state.pop("_inv_calc", None)
                    st.success(f"Invoice {inv_num} created!"); st.rerun()
                except Exception as e:
                    if "duplicate" in str(e).lower() or "23505" in str(e):
                        import time; time.sleep(0.5)
                        try:
                            inv_num = create_invoice(
                                advisor_id=user["id"], ac_id=cl_id,
                                fee_type=_fee_type, fee_value=_fee_value, fee_frequency=_freq,
                                amount=amount, portfolio_value=_pf_val, num_meetings=_n_mtg,
                                period_from=_pf_from, period_to=_pf_to, notes=notes,
                                invoice_date=str(inv_date), due_date=due,
                            )
                            st.session_state.pop("_inv_calc", None)
                            st.success(f"Invoice {inv_num} created!"); st.rerun()
                        except Exception as e2:
                            st.error(f"Error: {e2}")
                    else:
                        st.error(f"Error: {e}")
        else:
            st.info("Configure fee above then click **Calculate Fee** before generating.")
    back_button(fallback="profile", label="← Back", key="bot")
