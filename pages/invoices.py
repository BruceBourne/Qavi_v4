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

# ── ASSET CLASS CATEGORISATION ────────────────────────────────────────────
EQUITY_CLASSES = {"Equity","ETF","Mutual Fund","Commodity"}   # price-based holdings
DEBT_CLASSES   = {"Bond","Bank FD"}                           # interest/maturity-based

def _is_debt(asset_class: str) -> bool:
    return asset_class in DEBT_CLASSES

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
                num_meetings, d_from: date, d_to: date, holdings=None) -> float:
    if fee_type == "one_time":
        return round(float(fee_value), 2)
    elif fee_type == "consultation":
        return round(float(fee_value) * int(num_meetings), 2)
    elif fee_type == "management":
        if holdings is not None:
            debt_val = non_debt_val = 0.0
            for h in holdings:
                p, _ = get_asset_price(h["symbol"])
                val  = h["quantity"] * (p or h["avg_cost"])
                if _is_debt(h.get("asset_class","")): debt_val += val
                else:                                  non_debt_val += val
            days     = (d_to - d_from).days
            debt_fee = round(debt_val * (float(fee_value)/100.0/365) * days, 2)
            n        = _count_periods(d_from, d_to, frequency)
            rate_p   = _rate_per_period(float(fee_value), frequency)
            nd_fee   = round(non_debt_val * rate_p * n, 2)
            return round(debt_fee + nd_fee, 2)
        else:
            n      = _count_periods(d_from, d_to, frequency)
            rate_p = _rate_per_period(float(fee_value), frequency)
            return round(float(portfolio_value) * rate_p * n, 2)
    return 0.0

def _pf_value_and_holdings(ac_id):
    total, all_h = 0.0, []
    for pf in get_portfolios_for_ac(ac_id):
        for h in get_portfolio_holdings(pf["id"]):
            p, _ = get_asset_price(h["symbol"])
            total += h["quantity"] * (p or h["avg_cost"])
            all_h.append(h)
    return total, all_h

# ── DEBT INSTRUMENT DETAILS ───────────────────────────────────────────────
def _get_debt_info(symbol: str) -> dict:
    """Fetch maturity, interest rate for a Bond/FD symbol."""
    try:
        fi = get_fixed_income()
        for row in fi:
            if row["symbol"] == symbol:
                return {
                    "rate":     row.get("interest_rate", 0),
                    "maturity": row.get("maturity_date", "—"),
                    "tenure":   row.get("tenure_years", "—"),
                    "issuer":   row.get("issuer", "—"),
                    "rating":   row.get("rating", "—"),
                }
    except Exception:
        pass
    return {"rate":0,"maturity":"—","tenure":"—","issuer":"—","rating":"—"}

# ── HOLDING NOTE PARSING (to get stored interest rate) ────────────────────
def _note_rate(notes: str) -> float | None:
    """Extract rate:X.XX% from holding notes if advisor stored it."""
    if not notes: return None
    for part in notes.split("|"):
        part = part.strip()
        if part.startswith("rate:"):
            try: return float(part[5:].replace("%","").strip())
            except: pass
    return None

# ── INVOICE HTML ──────────────────────────────────────────────────────────
def _invoice_html(inv, adv_user, client):
    # Contact info
    adv_name  = title_case(adv_user.get("full_name") or adv_user.get("username",""))
    dec_adv   = decrypt_user(adv_user) if adv_user else {}
    adv_phone = dec_adv.get("phone","") or "—"
    adv_addr  = dec_adv.get("address","") or "—"
    cl_name   = title_case(client.get("client_name",""))
    cl_phone  = client.get("client_phone","") or "—"
    cl_addr   = "—"

    # Collect all holdings split by equity vs debt
    eq_holdings   = []   # (symbol, asset_class, qty, buy_cost, cur_price, pnl, pnl_pct)
    debt_holdings = []   # (symbol, asset_class, qty, face_val, interest_rate, maturity)
    total_eq_buy = total_eq_cur = 0.0
    total_debt_buy = total_debt_cur = 0.0

    for pf in get_portfolios_for_ac(inv["advisor_client_id"]):
        for h in get_portfolio_holdings(pf["id"]):
            p, _    = get_asset_price(h["symbol"])
            cur_p   = p or h["avg_cost"]
            buy_val = h["quantity"] * h["avg_cost"]
            cur_val = h["quantity"] * cur_p
            pnl     = cur_val - buy_val
            pnl_pct = ((cur_p - h["avg_cost"]) / h["avg_cost"] * 100) if h["avg_cost"] else 0
            ac      = h.get("asset_class","")

            if _is_debt(ac):
                total_debt_buy += buy_val
                total_debt_cur += cur_val
                di   = _get_debt_info(h["symbol"])
                rate = _note_rate(h.get("notes","")) or di["rate"]
                debt_holdings.append({
                    "symbol":   h["symbol"],
                    "ac":       ac,
                    "qty":      h["quantity"],
                    "invested": buy_val,
                    "cur_val":  cur_val,
                    "rate":     rate,
                    "maturity": di["maturity"],
                    "issuer":   di["issuer"],
                    "rating":   di["rating"],
                })
            else:
                total_eq_buy += buy_val
                total_eq_cur += cur_val
                eq_holdings.append({
                    "symbol":  h["symbol"],
                    "ac":      ac,
                    "qty":     h["quantity"],
                    "buy":     h["avg_cost"],
                    "cur":     cur_p,
                    "pnl":     pnl,
                    "pnl_pct": pnl_pct,
                    "buy_val": buy_val,
                    "cur_val": cur_val,
                })

    has_equity = len(eq_holdings) > 0
    has_debt   = len(debt_holdings) > 0
    show_combined = has_equity and has_debt

    # ── EQUITY TABLE ──────────────────────────────────────────────────────
    eq_table_html = ""
    if has_equity:
        eq_rows = ""
        for h in sorted(eq_holdings, key=lambda x: -x["cur_val"]):
            pc   = "#15803d" if h["pnl"] >= 0 else "#b91c1c"
            sign = "+" if h["pnl"] >= 0 else ""
            eq_rows += (
                f"<tr>"
                f"<td class='tl fw'>{h['symbol']}</td>"
                f"<td class='tl gr'>{h['ac']}</td>"
                f"<td class='tc'>{h['qty']:g}</td>"
                f"<td class='tr'>₹{indian_format(h['buy'])}</td>"
                f"<td class='tr'>₹{indian_format(h['cur'])}</td>"
                f"<td class='tr' style='color:{pc};font-weight:600'>"
                f"₹{indian_format(abs(h['pnl']))}&nbsp;"
                f"<span class='sm'>{sign}{h['pnl_pct']:.1f}%</span></td>"
                f"</tr>"
            )
        eq_pnl  = total_eq_cur - total_eq_buy
        eq_pct  = (eq_pnl/total_eq_buy*100) if total_eq_buy else 0
        tpc_eq  = "#15803d" if eq_pnl >= 0 else "#b91c1c"
        tsign_eq = "+" if eq_pnl >= 0 else ""
        eq_table_html = f"""
        <div class="sec" style="margin-top:10px">
            Equity &amp; Market Holdings &nbsp;·&nbsp;
            <span style="font-weight:600">₹{indian_format(total_eq_cur)}</span>
        </div>
        <table class="ht">
          <thead><tr>
            <th class="hl">Symbol</th>
            <th class="hl">Asset Class</th>
            <th>Qty</th>
            <th>Purchase Cost</th>
            <th>Closing Price</th>
            <th>P&amp;L</th>
          </tr></thead>
          <tbody>
            {eq_rows}
            <tr class="tot">
              <td class="tl" colspan="2"><strong>Equity / Market Total</strong></td>
              <td class="tc">—</td>
              <td class="tr">₹{indian_format(total_eq_buy)}</td>
              <td class="tr">₹{indian_format(total_eq_cur)}</td>
              <td class="tr" style="color:{tpc_eq}">
                ₹{indian_format(abs(eq_pnl))}&nbsp;({tsign_eq}{eq_pct:.2f}%)
              </td>
            </tr>
          </tbody>
        </table>"""

    # ── DEBT TABLE ────────────────────────────────────────────────────────
    debt_table_html = ""
    if has_debt:
        d_rows = ""
        for h in sorted(debt_holdings, key=lambda x: -x["cur_val"]):
            mat = fmt_date(h["maturity"]) if h["maturity"] and h["maturity"] not in ("—","N/A","") else "—"
            d_rows += (
                f"<tr>"
                f"<td class='tl fw'>{h['symbol']}</td>"
                f"<td class='tl gr'>{h['ac']}</td>"
                f"<td class='tc'>{h['qty']:g}</td>"
                f"<td class='tr'>₹{indian_format(h['invested'])}</td>"
                f"<td class='tr' style='color:#15803d;font-weight:600'>{h['rate']:.2f}% p.a.</td>"
                f"<td class='tr'>{h['issuer']}</td>"
                f"<td class='tc' style='color:#64748b'>{h['rating']}</td>"
                f"<td class='tr'>{mat}</td>"
                f"</tr>"
            )
        debt_table_html = f"""
        <div class="sec" style="margin-top:10px">
            Debt &amp; Fixed Income Holdings &nbsp;·&nbsp;
            <span style="font-weight:600">₹{indian_format(total_debt_cur)}</span>
        </div>
        <table class="ht">
          <thead><tr>
            <th class="hl">Symbol</th>
            <th class="hl">Type</th>
            <th>Qty / Amount</th>
            <th>Invested</th>
            <th>Interest Rate</th>
            <th>Issuer</th>
            <th>Rating</th>
            <th>Maturity</th>
          </tr></thead>
          <tbody>
            {d_rows}
            <tr class="tot">
              <td class="tl" colspan="3"><strong>Debt / Fixed Income Total</strong></td>
              <td class="tr">₹{indian_format(total_debt_buy)}</td>
              <td colspan="4" class="tl" style="color:#64748b;font-size:.7rem">
                See fee details for debt accrual calculation
              </td>
            </tr>
          </tbody>
        </table>"""

    # ── COMBINED SUMMARY (only when both types present) ───────────────────
    combined_html = ""
    if show_combined:
        grand_buy = total_eq_buy + total_debt_buy
        grand_cur = total_eq_cur + total_debt_cur
        grand_pnl = grand_cur - grand_buy
        grand_pct = (grand_pnl/grand_buy*100) if grand_buy else 0
        tpc_g     = "#15803d" if grand_pnl >= 0 else "#b91c1c"
        tsign_g   = "+" if grand_pnl >= 0 else ""
        combined_html = f"""
        <div class="sec" style="margin-top:10px">Portfolio Total</div>
        <table class="ht">
          <thead><tr>
            <th class="hl">Category</th>
            <th>Invested</th>
            <th>Current Value</th>
            <th>P&amp;L / Return</th>
          </tr></thead>
          <tbody>
            <tr>
              <td class="tl fw">Equity &amp; Market</td>
              <td class="tr">₹{indian_format(total_eq_buy)}</td>
              <td class="tr">₹{indian_format(total_eq_cur)}</td>
              <td class="tr" style="color:{("#15803d" if total_eq_cur>=total_eq_buy else "#b91c1c")};font-weight:600">
                ₹{indian_format(abs(total_eq_cur-total_eq_buy))}
                &nbsp;({("+" if total_eq_cur>=total_eq_buy else "")}{((total_eq_cur-total_eq_buy)/total_eq_buy*100 if total_eq_buy else 0):.2f}%)
              </td>
            </tr>
            <tr>
              <td class="tl fw">Debt &amp; Fixed Income</td>
              <td class="tr">₹{indian_format(total_debt_buy)}</td>
              <td class="tr">₹{indian_format(total_debt_cur)}</td>
              <td class="tr" style="color:#64748b">Interest accruing</td>
            </tr>
            <tr class="tot">
              <td class="tl"><strong>Grand Total</strong></td>
              <td class="tr">₹{indian_format(grand_buy)}</td>
              <td class="tr">₹{indian_format(grand_cur)}</td>
              <td class="tr" style="color:{tpc_g}">
                ₹{indian_format(abs(grand_pnl))}&nbsp;({tsign_g}{grand_pct:.2f}%)
              </td>
            </tr>
          </tbody>
        </table>"""

    # ── PORTFOLIO SUMMARY BOX ─────────────────────────────────────────────
    total_buy = total_eq_buy + total_debt_buy
    total_cur = total_eq_cur + total_debt_cur
    total_pnl = total_cur - total_buy
    total_pct = (total_pnl/total_buy*100) if total_buy else 0
    tpc  = "#15803d" if total_pnl >= 0 else "#b91c1c"
    tsign = "+" if total_pnl >= 0 else ""

    # ── FEE DETAIL ROWS ───────────────────────────────────────────────────
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
    notes_html = (f"<p style='margin-top:.45rem;font-size:.73rem;color:#64748b'>{inv['notes']}</p>"
                  if inv.get("notes") else "")

    # ── FULL HTML ─────────────────────────────────────────────────────────
    # @page: A4 landscape = 297mm × 210mm
    # Normal print margins: 12mm all sides — matches Word/PDF defaults
    # Body max-width constraint keeps content from stretching on screen too
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{inv['invoice_number']}</title>
<style>
/* ── PRINT SETUP ── */
@page {{
  size: A4 landscape;
  margin: 12mm 14mm 12mm 14mm;   /* top right bottom left — normal print margins */
}}

/* ── RESET ── */
*, *::before, *::after {{ margin:0; padding:0; box-sizing:border-box; }}

/* ── BASE ── */
body {{
  font-family: 'Segoe UI', Arial, Helvetica, sans-serif;
  font-size: 11px;
  color: #1e293b;
  background: #fff;
  line-height: 1.5;
}}

/* Screen wrapper — keeps it readable in browser too */
.page {{
  max-width: 260mm;              /* ~A4 landscape content width at 12mm margins */
  margin: 0 auto;
  padding: 10mm;                 /* breathing room in browser, ignored in print */
  background: #fff;
}}

@media print {{
  .page {{ padding: 0; max-width: 100%; }}
}}

/* ── HEADER ── */
.hdr {{
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding-bottom: 10px;
  border-bottom: 2px solid #1e293b;
  margin-bottom: 14px;
}}
.brand {{ font-size: 2rem; font-weight: 900; letter-spacing: .1em; line-height: 1; font-variant: small-caps; }}
.brand-sub {{ font-size: .58rem; color: #94a3b8; letter-spacing: .18em; text-transform: uppercase; margin-top: .18rem; }}
.inv-meta {{ text-align: right; }}
.inv-num {{ font-size: .9rem; font-weight: 700; margin-bottom: .35rem; }}
.dt {{ border-collapse: collapse; }}
.dt td {{ padding: 1.5px 0; font-size: .72rem; color: #64748b; }}
.dl {{ text-align: right; padding-right: 4px; white-space: nowrap; }}
.dv {{ text-align: right; white-space: nowrap; font-weight: 500; color: #1e293b; }}

/* ── TWO COLUMN GRID ── */
.two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px; }}

/* ── PARTY CARDS ── */
.party {{
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 5px;
  padding: 8px 12px;
}}
.plbl {{ font-size: .55rem; font-weight: 700; color: #94a3b8; letter-spacing: .14em; text-transform: uppercase; margin-bottom: 3px; }}
.pname {{ font-size: .87rem; font-weight: 700; margin-bottom: 2px; }}
.pdet {{ font-size: .72rem; color: #64748b; line-height: 1.65; }}

/* ── AMOUNT BOX ── */
.amt-box {{
  background: linear-gradient(135deg, #1e293b, #2d4060);
  color: #fff;
  border-radius: 7px;
  padding: 11px 18px;
  margin-bottom: 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}}
.amt-lbl {{ font-size: .58rem; opacity: .68; letter-spacing: .12em; text-transform: uppercase; margin-bottom: .15rem; }}
.amt-val {{ font-size: 1.75rem; font-weight: 800; letter-spacing: -.01em; }}
.amt-due {{ font-size: .68rem; opacity: .58; margin-top: .15rem; }}
.amt-right {{ text-align: right; font-size: .72rem; opacity: .82; line-height: 1.75; }}

/* ── SECTION TITLE ── */
.sec {{
  font-size: .57rem;
  font-weight: 700;
  color: #94a3b8;
  letter-spacing: .1em;
  text-transform: uppercase;
  margin-bottom: 5px;
  padding-bottom: 3px;
  border-bottom: 1px solid #e2e8f0;
}}

/* ── FEE / META TABLE ── */
.ft {{ width: 100%; border-collapse: collapse; font-size: .77rem; }}
.ft td {{ padding: 3px 0; border-bottom: 1px solid #f1f5f9; vertical-align: top; }}
.lbl {{ color: #94a3b8; width: 40%; padding-right: 8px; }}

/* ── HOLDINGS TABLE ── */
table.ht {{
  width: 100%;
  border-collapse: collapse;
  font-size: .74rem;
  margin-top: 4px;
  margin-bottom: 8px;
}}
table.ht thead tr {{ background: #1e293b; color: #fff; }}
table.ht th {{
  padding: 5px 8px;
  font-weight: 600;
  font-size: .61rem;
  letter-spacing: .04em;
  text-align: center;
}}
table.ht th.hl {{ text-align: left; }}
table.ht td {{
  padding: 5px 8px;
  border-bottom: 1px solid #f1f5f9;
  vertical-align: middle;
}}
table.ht tr:nth-child(even) {{ background: #f8fafc; }}
table.ht tr:hover {{ background: #f0f9ff; }}

/* TD alignment helpers */
.tl {{ text-align: left; }}
.tc {{ text-align: center; }}
.tr {{ text-align: right; }}
.fw {{ font-weight: 600; }}
.gr {{ color: #64748b; }}
.sm {{ font-size: .67rem; display: inline-block; margin-left: 2px; }}

/* Total rows */
.tot td {{
  background: #eff6ff !important;
  font-weight: 700;
  color: #1e293b;
  font-size: .75rem;
  border-top: 1.5px solid #bfdbfe;
}}

/* ── FOOTER ── */
.ftr {{
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}}
.ftr-brand {{ font-size: .87rem; font-weight: 900; letter-spacing: .1em; color: #94a3b8; font-variant: small-caps; }}
.ftr-note {{ font-size: .61rem; color: #cbd5e1; text-align: right; line-height: 1.6; }}

/* ── PRINT HELPERS ── */
@media print {{
  table.ht {{ page-break-inside: avoid; }}
  .amt-box {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  table.ht thead tr {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
}}
</style>
</head>
<body>
<div class="page">

<!-- HEADER -->
<div class="hdr">
  <div>
    <div class="brand">QAVI</div>
    <div class="brand-sub">Wealth Management</div>
  </div>
  <div class="inv-meta">
    <div class="inv-num">{inv['invoice_number']}</div>
    <table class="dt">
      <tr>
        <td class="dl">Date</td>
        <td style="padding:0 5px;color:#94a3b8">:</td>
        <td class="dv">{fmt_date(inv['invoice_date'])}</td>
      </tr>
      <tr>
        <td class="dl">Payment Due</td>
        <td style="padding:0 5px;color:#94a3b8">:</td>
        <td class="dv">{fmt_date(inv['due_date'])}</td>
      </tr>
    </table>
  </div>
</div>

<!-- PARTIES -->
<div class="two">
  <div class="party">
    <div class="plbl">From</div>
    <div class="pname">{adv_name}</div>
    <div class="pdet">
      Phone: {adv_phone}<br>
      {adv_addr}
    </div>
  </div>
  <div class="party">
    <div class="plbl">Bill To</div>
    <div class="pname">{cl_name}</div>
    <div class="pdet">
      Phone: {cl_phone}<br>
      {cl_addr}
    </div>
  </div>
</div>

<!-- AMOUNT BOX -->
<div class="amt-box">
  <div>
    <div class="amt-lbl">Amount Due</div>
    <div class="amt-val">₹{indian_format(inv['amount'])}</div>
    <div class="amt-due">Due by {fmt_date(inv['due_date'])}</div>
  </div>
  <div class="amt-right">
    {FEE_TYPES.get(fee_type,'')}<br>
    <span style="opacity:.65">{fee_freq if fee_type=='management' else ''}</span>
  </div>
</div>

<!-- FEE + PORTFOLIO SUMMARY -->
<div class="two">
  <div>
    <div class="sec">Fee Details</div>
    <table class="ft">
      <tbody>{fee_detail}</tbody>
    </table>
    {notes_html}
  </div>
  <div>
    <div class="sec">Portfolio Summary</div>
    <table class="ft">
      <tbody>
        <tr><td class="lbl">Total Invested</td><td>₹{indian_format(total_buy)}</td></tr>
        <tr><td class="lbl">Current Value</td><td>₹{indian_format(total_cur)}</td></tr>
        <tr>
          <td class="lbl">Overall P&amp;L</td>
          <td style="color:{tpc};font-weight:600">
            ₹{indian_format(abs(total_pnl))} ({tsign}{total_pct:.2f}%)
          </td>
        </tr>
        {"<tr><td class='lbl'>Equity Value</td><td>₹" + indian_format(total_eq_cur) + "</td></tr>" if show_combined else ""}
        {"<tr><td class='lbl'>Debt Value</td><td>₹" + indian_format(total_debt_cur) + "</td></tr>" if show_combined else ""}
      </tbody>
    </table>
  </div>
</div>

<!-- HOLDINGS — as of date -->
<p style="font-size:.6rem;color:#94a3b8;margin:2px 0 4px;letter-spacing:.05em">
  HOLDINGS AS OF {fmt_date(str(date.today())).upper()}
</p>

{eq_table_html}
{debt_table_html}
{combined_html}

<!-- FOOTER -->
<div class="ftr">
  <div>
    <div class="ftr-brand">◈ QAVI</div>
    <div style="font-size:.6rem;color:#cbd5e1">Generated {fmt_date(str(date.today()))}</div>
  </div>
  <div class="ftr-note">
    Computer generated document.<br>
    For queries contact your advisor.
  </div>
</div>

</div><!-- /page -->
</body>
</html>"""

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
        st.warning("⚠️ Market open (closes 15:30 IST) — invoice uses yesterday's closing prices.")

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
                            try: sb().table("invoices").delete().eq("id",inv["id"]).execute()
                            except: sb().table("invoices").delete().eq("invoice_number",inv["invoice_number"]).execute()
                            st.session_state.pop(f"del_{inv['id']}",None); st.rerun()
                        if dn.button("No", key=f"ndi_{inv['id']}", use_container_width=True):
                            st.session_state.pop(f"del_{inv['id']}",None); st.rerun()

    with tab2:
        if not clients:
            st.info("No clients yet."); return

        cl_id = st.selectbox("Client", [c["id"] for c in clients],
                             format_func=lambda x: title_case(next(c["client_name"] for c in clients if c["id"]==x)))
        client  = next(c for c in clients if c["id"]==cl_id)
        pf_val, pf_holdings = _pf_value_and_holdings(cl_id)
        num_mtg = get_meeting_count_completed(cl_id)

        debt_val     = sum(h["quantity"]*(get_asset_price(h["symbol"])[0] or h["avg_cost"])
                          for h in pf_holdings if _is_debt(h.get("asset_class","")))
        non_debt_val = pf_val - debt_val

        info_parts = [f"Total AUM: ₹{indian_format(pf_val)}"]
        if debt_val > 0: info_parts.append(f"Debt: ₹{indian_format(debt_val)}")
        if non_debt_val > 0: info_parts.append(f"Market: ₹{indian_format(non_debt_val)}")
        info_parts.append(f"Meetings: {num_mtg}")
        st.markdown(f'<p style="font-size:.82rem;color:#8892AA">{" · ".join(info_parts)}</p>', unsafe_allow_html=True)

        st.markdown("#### Dates")
        dc1,dc2 = st.columns(2)
        inv_date  = dc1.date_input("Invoice Date",       value=date.today())
        pay_basis = dc2.date_input("Payment Date Basis", value=date.today(),
                                    help="Due date = 15 days from this date")
        pc1,pc2   = st.columns(2)
        pf_from   = pc1.date_input("Period From", value=date.today().replace(day=1))
        pf_to     = pc2.date_input("Period To",   value=date.today())

        st.markdown("#### Fee")
        fee_type  = st.selectbox("Fee Type", list(FEE_TYPES.keys()), format_func=lambda x: FEE_TYPES[x])
        fc1,fc2   = st.columns(2)
        fee_value = fc1.number_input("Fee Value (₹ or % p.a.)",
                                      value=float(client.get("fee_value",0)), min_value=0.0, step=100.0)
        freq = "annual"
        if fee_type == "management":
            freq = fc2.selectbox("Billing Frequency", list(FEE_FREQS.keys()), format_func=lambda x: FEE_FREQS[x])
            if debt_val > 0:
                st.caption("Debt assets always use daily accrual. Frequency applies to market holdings only.")
        else:
            fc2.empty()

        n_meetings = int(st.number_input("Meetings to Bill", min_value=0, value=num_mtg, step=1)) \
                     if fee_type=="consultation" else num_mtg

        st.markdown("---")
        if st.button("🧮 Calculate Fee", use_container_width=True):
            amount = calc_amount(fee_type, fee_value, freq, pf_val, n_meetings,
                                 pf_from, pf_to, holdings=pf_holdings if fee_type=="management" else None)
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
            amount = calc["amount"]
            if calc["fee_type"]=="management":
                days  = (pf_to - pf_from).days
                n     = int(calc["n"])
                parts = []
                dv    = calc.get("debt_val",0)
                ndv   = calc.get("non_debt_val",0)
                if dv > 0:
                    df = round(dv*(calc["fee_value"]/100/365)*days,2)
                    parts.append(f"Debt ₹{indian_format(dv)} × {calc['fee_value']}%÷365 × {days}d = ₹{indian_format(df)}")
                if ndv > 0:
                    div = {"annual":1,"quarterly":4,"monthly":12}.get(calc["freq"],12)
                    nf  = round(ndv*(calc["fee_value"]/100/div)*n,2)
                    parts.append(f"Market ₹{indian_format(ndv)} × {calc['fee_value']}%÷{div} × {n} period(s) = ₹{indian_format(nf)}")
                if not parts:
                    div = {"annual":1,"quarterly":4,"monthly":12,"daily":365}.get(calc["freq"],12)
                    parts.append(f"₹{indian_format(calc['pf_val'])} × {calc['fee_value']}%÷{div} × {n or days}")
                detail = " + ".join(parts)
            elif calc["fee_type"]=="consultation":
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
                    st.session_state.pop("_inv_calc",None)
                    st.success(f"Invoice {inv_num} created!"); st.rerun()
                except Exception as e:
                    if "duplicate" in str(e).lower() or "23505" in str(e):
                        import time; time.sleep(0.5)
                        try:
                            inv_num = create_invoice(
                                advisor_id=user["id"], ac_id=cl_id,
                                fee_type=fee_type, fee_value=fee_value, fee_frequency=freq,
                                amount=amount, portfolio_value=pf_val, num_meetings=n_meetings,
                                period_from=str(pf_from), period_to=str(pf_to), notes=notes,
                                invoice_date=str(inv_date), due_date=due_date,
                            )
                            st.session_state.pop("_inv_calc",None)
                            st.success(f"Invoice {inv_num} created!"); st.rerun()
                        except Exception as e2: st.error(f"Could not generate invoice: {e2}")
                    else:
                        st.error(f"Could not generate invoice: {e}")
        else:
            st.info("Configure fee above then click **Calculate Fee** to preview before generating.")
