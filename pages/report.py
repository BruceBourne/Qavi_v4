"""
report.py — Portfolio Report Generator for Qavi
Generates a multi-page HTML report downloadable as a file.
Covers: summary, performance, allocation, holdings, sector, 
        diversification, projections, risk (optional), 
        scenarios/stress test (optional).
Access-controlled: client sees their portfolios only,
advisor sees selected client, owner sees any.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from utils.session import navigate, back_button
from utils.db import (
    get_advisor_clients, get_client_advisors,
    get_portfolios_for_ac, get_private_portfolios,
    get_portfolio_holdings, get_all_prices_map,
    get_transactions, get_price_history, get_assets_map,
    get_mutual_funds
)
from utils.crypto import indian_format, inr, fmt_date, title_case
from datetime import date, datetime, timedelta
from collections import defaultdict
import math, base64, json

# ── HELPERS ───────────────────────────────────────────────────────────────

def _f(v, d=0.0):
    try: return float(v or d)
    except: return d

def _price(sym, pmap):
    r = pmap.get(sym)
    return (_f(r.get("close")), _f(r.get("change_pct"))) if r else (0.0, 0.0)

def _pct_change(new, old):
    if old and old != 0: return round((new - old) / old * 100, 2)
    return 0.0

def _annualised(total_pct, days):
    if days <= 0: return 0.0
    try: return round(((1 + total_pct/100) ** (365/days) - 1) * 100, 2)
    except: return 0.0

def _sharpe(daily_returns, risk_free_annual=0.07):
    if len(daily_returns) < 10: return None
    avg = sum(daily_returns) / len(daily_returns)
    var = sum((r - avg)**2 for r in daily_returns) / len(daily_returns)
    std = math.sqrt(var) if var > 0 else 0
    if std == 0: return None
    ann_ret = avg * 252
    ann_std = std * math.sqrt(252)
    rf_daily = risk_free_annual / 252
    return round((ann_ret - risk_free_annual) / ann_std, 3)

def _max_drawdown(prices):
    if not prices: return 0.0
    peak = prices[0]; mdd = 0.0
    for p in prices:
        peak = max(peak, p)
        dd = (p - peak) / peak * 100 if peak > 0 else 0
        mdd = min(mdd, dd)
    return round(mdd, 2)

def _volatility_ann(daily_returns):
    if len(daily_returns) < 5: return 0.0
    avg = sum(daily_returns) / len(daily_returns)
    var = sum((r-avg)**2 for r in daily_returns) / len(daily_returns)
    return round(math.sqrt(var) * math.sqrt(252) * 100, 2)

def _collect_portfolio_data(pf_ids, pmap, assets_map, period_days):
    """
    Aggregates all holdings data across given portfolio IDs.
    Returns a rich dict used by all report sections.
    """
    all_holdings = []
    for pf_id in pf_ids:
        for h in get_portfolio_holdings(pf_id):
            h["_pf_id"] = pf_id
            all_holdings.append(h)

    total_inv = total_cur = 0.0
    by_class  = defaultdict(lambda: {"inv":0.0,"cur":0.0,"count":0})
    by_sector = defaultdict(lambda: {"inv":0.0,"cur":0.0,"count":0})
    by_sub    = defaultdict(lambda: {"inv":0.0,"cur":0.0,"count":0})
    holdings_detail = []

    for h in all_holdings:
        sym  = h["symbol"]
        qty  = _f(h.get("quantity"))
        cost = _f(h.get("avg_cost"))
        inv  = qty * cost
        pr, chg = _price(sym, pmap)
        cur  = qty * (pr or cost)
        pnl  = cur - inv
        pnl_pct = _pct_change(cur, inv)
        ac   = h.get("asset_class", "Other")
        ai   = assets_map.get(sym, {})
        sector = ai.get("sector", "") or "Other"
        sub    = h.get("sub_class","") or ai.get("sub_class","") or ac

        total_inv += inv
        total_cur += cur
        by_class[ac]["inv"] += inv;  by_class[ac]["cur"] += cur;  by_class[ac]["count"] += 1
        by_sector[sector]["inv"] += inv; by_sector[sector]["cur"] += cur; by_sector[sector]["count"] += 1
        by_sub[sub]["inv"] += inv;   by_sub[sub]["cur"] += cur;   by_sub[sub]["count"] += 1

        holdings_detail.append({
            "symbol": sym,
            "name":   ai.get("name", sym),
            "asset_class": ac,
            "sub_class":   sub,
            "sector":      sector,
            "quantity":    qty,
            "avg_cost":    cost,
            "current_price": pr,
            "invested":    inv,
            "current":     cur,
            "pnl":         pnl,
            "pnl_pct":     pnl_pct,
            "change_pct":  chg,
            "weight":      0.0,  # filled below
        })

    # Weights
    for h in holdings_detail:
        h["weight"] = round(h["current"] / total_cur * 100, 2) if total_cur else 0.0

    total_pnl     = total_cur - total_inv
    total_pnl_pct = _pct_change(total_cur, total_inv)

    # Period performance: collect price history for top holdings
    period_start = date.today() - timedelta(days=period_days)
    period_perf  = []
    for h in sorted(holdings_detail, key=lambda x: -x["current"])[:15]:
        hist = get_price_history(h["symbol"], days=max(period_days+30, 365))
        if not hist: continue
        hist = [r for r in hist if r.get("price_date","") >= str(period_start)]
        if len(hist) < 2: continue
        first_p = _f(hist[0].get("close"))
        last_p  = _f(hist[-1].get("close"))
        if first_p <= 0: continue
        p_pct = _pct_change(last_p, first_p)
        period_perf.append({"symbol": h["symbol"], "name": h["name"],
                             "period_return": p_pct, "weight": h["weight"]})

    # Weighted portfolio period return
    period_return = sum(p["period_return"] * p["weight"] / 100
                        for p in period_perf) if period_perf else 0.0

    # Risk metrics from largest holding's price history
    daily_rets = []
    if holdings_detail:
        top_sym  = holdings_detail[0]["symbol"]
        hist_all = get_price_history(top_sym, days=365)
        prices_l = [_f(r.get("close")) for r in hist_all if r.get("close")]
        if len(prices_l) > 2:
            daily_rets = [_pct_change(prices_l[i], prices_l[i-1])/100
                          for i in range(1, len(prices_l))]

    # Diversification score (0-100)
    n_classes  = len([v for v in by_class.values()  if v["cur"] > 0])
    n_sectors  = len([v for v in by_sector.values() if v["cur"] > 0])
    n_holdings = len(holdings_detail)
    # Herfindahl index (concentration)
    hhi = sum((h["weight"]/100)**2 for h in holdings_detail) if holdings_detail else 1.0
    div_score = round(min(100, max(0,
        (n_classes  / 6  * 25) +
        (n_sectors  / 10 * 25) +
        (min(n_holdings, 20) / 20 * 25) +
        ((1 - hhi) * 25)
    )), 1)

    return {
        "holdings":        holdings_detail,
        "total_inv":       total_inv,
        "total_cur":       total_cur,
        "total_pnl":       total_pnl,
        "total_pnl_pct":   total_pnl_pct,
        "by_class":        dict(by_class),
        "by_sector":       dict(by_sector),
        "by_sub":          dict(by_sub),
        "period_return":   round(period_return, 2),
        "period_perf":     period_perf,
        "daily_rets":      daily_rets,
        "sharpe":          _sharpe(daily_rets),
        "max_dd":          _max_drawdown([_f(r.get("close")) for r in
                            get_price_history(
                                holdings_detail[0]["symbol"], 365
                            )] if holdings_detail else []),
        "volatility":      _volatility_ann(daily_rets),
        "div_score":       div_score,
        "n_holdings":      n_holdings,
        "n_classes":       n_classes,
        "n_sectors":       n_sectors,
    }


# ── PROJECTION HELPER ─────────────────────────────────────────────────────
def _projection_rows(current, annual_rates, years=10):
    rows = []
    for yr in range(1, years+1):
        row = {"year": yr}
        for label, rate in annual_rates.items():
            row[label] = round(current * (1 + rate/100)**yr)
        rows.append(row)
    return rows


# ── SCENARIO / STRESS TEST ────────────────────────────────────────────────
SCENARIOS = {
    "Bull Market (+30%)":           +30,
    "Moderate Growth (+15%)":       +15,
    "Flat Market (0%)":              0,
    "Mild Correction (-10%)":       -10,
    "Bear Market (-30%)":           -30,
    "2008-style Crash (-50%)":      -50,
    "COVID Drop (Mar 2020, -38%)":  -38,
    "Rate Hike Shock (-20%)":       -20,
}


# ── HTML REPORT BUILDER ───────────────────────────────────────────────────
def _css():
    return """
<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700&family=Inter:wght@300;400;500;600&display=swap');
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:'Inter',Arial,sans-serif;font-size:13px;color:#1e293b;
     background:#f8fafc;line-height:1.6;}
.page{width:210mm;min-height:290mm;margin:0 auto;padding:14mm 16mm;
      background:#fff;page-break-after:always;position:relative;}
.page:last-child{page-break-after:auto;}
@media print{
  .page{margin:0;padding:14mm 16mm;box-shadow:none;}
  body{background:#fff;}
}

/* Header */
.report-header{display:flex;justify-content:space-between;align-items:flex-start;
  padding-bottom:10px;border-bottom:2px solid #1e293b;margin-bottom:18px;}
.brand{font-family:'Cinzel',serif;font-size:1.5rem;font-weight:700;
  letter-spacing:.06em;color:#1e293b;}
.brand span{font-style:italic;font-size:.85rem;font-weight:400;
  color:#64748b;display:block;letter-spacing:.12em;margin-top:2px;}
.report-meta{text-align:right;font-size:.75rem;color:#64748b;}
.report-meta b{color:#1e293b;display:block;font-size:.85rem;margin-bottom:2px;}

/* Section title */
.sec{font-family:'Cinzel',serif;font-size:.82rem;font-weight:600;
  letter-spacing:.1em;text-transform:uppercase;color:#64748b;
  margin:18px 0 10px;padding-bottom:5px;border-bottom:1px solid #e2e8f0;}

/* Metric cards */
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:14px;}
.metric{background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;
  padding:12px 14px;}
.metric .lbl{font-size:.68rem;color:#94a3b8;text-transform:uppercase;
  letter-spacing:.08em;margin-bottom:4px;}
.metric .val{font-size:1.15rem;font-weight:700;color:#1e293b;line-height:1.2;}
.metric .sub{font-size:.72rem;margin-top:3px;}
.up{color:#16a34a;} .dn{color:#dc2626;} .neu{color:#94a3b8;}

/* Tables */
table{width:100%;border-collapse:collapse;font-size:.8rem;margin-bottom:12px;}
th{background:#f1f5f9;color:#64748b;font-weight:600;font-size:.72rem;
  text-transform:uppercase;letter-spacing:.06em;padding:7px 10px;
  text-align:left;border-bottom:1px solid #e2e8f0;}
td{padding:6px 10px;border-bottom:1px solid #f1f5f9;color:#1e293b;
  vertical-align:middle;}
tr:last-child td{border-bottom:none;}
tr:hover td{background:#f8fafc;}

/* Bar chart */
.bar-row{margin-bottom:8px;}
.bar-label{display:flex;justify-content:space-between;margin-bottom:3px;
  font-size:.76rem;color:#475569;}
.bar-bg{background:#e2e8f0;border-radius:4px;height:8px;}
.bar-fill{height:100%;border-radius:4px;}

/* Score ring */
.score-wrap{display:flex;align-items:center;gap:14px;margin-bottom:12px;}
.score-ring{width:70px;height:70px;border-radius:50%;display:flex;
  align-items:center;justify-content:center;font-size:1.3rem;font-weight:700;
  border:4px solid;}
.score-desc{font-size:.8rem;color:#475569;line-height:1.7;}

/* Scenario table */
.scenario-pos{color:#16a34a;font-weight:600;}
.scenario-neg{color:#dc2626;font-weight:600;}

/* Page number */
.pgnum{position:absolute;bottom:10mm;right:16mm;font-size:.68rem;color:#cbd5e1;}

/* Cover page */
.cover{display:flex;flex-direction:column;justify-content:center;min-height:270mm;}
.cover-brand{font-family:'Cinzel',serif;font-size:2.2rem;font-weight:700;
  letter-spacing:.1em;color:#1e293b;margin-bottom:.3rem;}
.cover-title{font-family:'Cinzel',serif;font-size:1.3rem;font-weight:400;
  color:#475569;letter-spacing:.06em;margin-bottom:2rem;}
.cover-line{height:2px;background:linear-gradient(90deg,#1e293b,#94a3b8,transparent);
  margin-bottom:2rem;}
.cover-info{font-size:.88rem;color:#475569;line-height:2.2;}
.cover-info b{color:#1e293b;}
.cover-disc{margin-top:3rem;font-size:.72rem;color:#94a3b8;line-height:1.8;
  border-top:1px solid #e2e8f0;padding-top:1rem;}
</style>"""

def _header(page_title, client_name, report_date, page_num, total_pages):
    return f"""
<div class="report-header">
  <div>
    <div class="brand">◈ QAVI <span>Portfolio Intelligence</span></div>
  </div>
  <div class="report-meta">
    <b>{page_title}</b>
    {client_name}<br>{report_date}
  </div>
</div>
<div class="pgnum">Page {page_num} of {total_pages}</div>"""

def _bar(label, value, total, color, suffix=""):
    pct = min(value/total*100, 100) if total else 0
    val_s = f"₹{indian_format(value)}{suffix}"
    return (f'<div class="bar-row">'
            f'<div class="bar-label"><span>{label}</span><span>{val_s} ({pct:.1f}%)</span></div>'
            f'<div class="bar-bg"><div class="bar-fill" style="width:{pct:.1f}%;background:{color}"></div></div>'
            f'</div>')

CLASS_COLORS = {
    "Equity":"#3b82f6","Mutual Fund":"#8b5cf6","ETF":"#f59e0b",
    "Bond":"#10b981","Bank FD":"#14b8a6","Commodity":"#f97316",
    "Real Estate":"#ec4899","Crypto":"#6366f1","Other":"#94a3b8",
}

def _div_color(score):
    if score >= 70: return ("#16a34a","border-color:#16a34a")
    if score >= 45: return ("#d97706","border-color:#d97706")
    return ("#dc2626","border-color:#dc2626")

def _div_label(score):
    if score >= 70: return "Well Diversified"
    if score >= 45: return "Moderately Diversified"
    return "Concentrated — consider diversifying"


def build_report_html(
    data, client_name, period_label, report_date,
    include_risk, include_scenarios, include_stress,
    include_projections, portfolio_names
):
    """
    Assembles all report pages into one HTML string.
    Returns complete HTML document.
    """
    pages = []
    TOTAL = (1 +   # cover
             1 +   # executive summary
             1 +   # holdings detail
             1 +   # allocation & sector
             1 +   # period performance
             (1 if include_risk else 0) +
             (1 if include_scenarios or include_stress else 0) +
             (1 if include_projections else 0))

    rdate = report_date
    pnl_c = "up" if data["total_pnl"] >= 0 else "dn"
    pnl_s = "▲" if data["total_pnl"] >= 0 else "▼"
    pr_c  = "up" if data["period_return"] >= 0 else "dn"
    pr_s  = "▲" if data["period_return"] >= 0 else "▼"

    # ── PAGE 1: COVER ──────────────────────────────────────────────────────
    pf_list = "<br>".join(f"&nbsp;·&nbsp; {p}" for p in portfolio_names) if portfolio_names else ""
    pages.append(f"""
<div class="page">
  <div class="cover">
    <div class="cover-brand">◈ QAVI</div>
    <div class="cover-title">Portfolio Performance Report</div>
    <div class="cover-line"></div>
    <div class="cover-info">
      <b>Prepared for:</b> {client_name}<br>
      <b>Report Period:</b> {period_label}<br>
      <b>Report Date:</b> {rdate}<br>
      <b>Portfolios Covered:</b><br>{pf_list}<br>
      <b>Total Holdings:</b> {data['n_holdings']}<br>
      <b>Asset Classes:</b> {data['n_classes']}<br>
      <b>Sectors Covered:</b> {data['n_sectors']}
    </div>
    <div class="cover-disc">
      This report is generated by Qavi, a portfolio analytics platform. It is for informational
      purposes only and does not constitute investment advice. Qavi is not a SEBI-registered
      investment advisor. Past performance is not indicative of future results. All values are
      based on the latest available market data and are subject to change.
    </div>
  </div>
  <div class="pgnum">Page 1 of {TOTAL}</div>
</div>""")

    # ── PAGE 2: EXECUTIVE SUMMARY ──────────────────────────────────────────
    ann = _annualised(data["total_pnl_pct"],
                      365 if period_label == "All Time" else int(period_label.split()[0])*30
                      if "Month" in period_label else 365)
    pages.append(f"""
<div class="page">
  {_header("Executive Summary", client_name, rdate, 2, TOTAL)}
  <div class="sec">Portfolio Snapshot</div>
  <div class="metrics">
    <div class="metric">
      <div class="lbl">Total Invested</div>
      <div class="val">₹{indian_format(data['total_inv'])}</div>
    </div>
    <div class="metric">
      <div class="lbl">Current Value</div>
      <div class="val">₹{indian_format(data['total_cur'])}</div>
    </div>
    <div class="metric">
      <div class="lbl">Total P&L</div>
      <div class="val class='{pnl_c}'">₹{indian_format(abs(data['total_pnl']))}</div>
      <div class="sub {pnl_c}">{pnl_s} {abs(data['total_pnl_pct']):.2f}%</div>
    </div>
    <div class="metric">
      <div class="lbl">Period Return ({period_label})</div>
      <div class="val {pr_c}">{pr_s} {abs(data['period_return']):.2f}%</div>
    </div>
  </div>
  <div class="metrics">
    <div class="metric">
      <div class="lbl">Holdings</div>
      <div class="val">{data['n_holdings']}</div>
    </div>
    <div class="metric">
      <div class="lbl">Asset Classes</div>
      <div class="val">{data['n_classes']}</div>
    </div>
    <div class="metric">
      <div class="lbl">Sectors</div>
      <div class="val">{data['n_sectors']}</div>
    </div>
    <div class="metric">
      <div class="lbl">Diversification</div>
      <div class="val">{data['div_score']}/100</div>
      <div class="sub neu">{_div_label(data['div_score'])}</div>
    </div>
  </div>

  <div class="sec">Asset Allocation</div>
  {''.join(_bar(k, v['cur'], data['total_cur'], CLASS_COLORS.get(k,"#94a3b8"))
            for k,v in sorted(data['by_class'].items(), key=lambda x:-x[1]['cur']))}

  <div class="sec">Top 5 Holdings by Weight</div>
  <table>
    <tr><th>Symbol</th><th>Name</th><th>Class</th><th>Invested</th><th>Current</th><th>P&L</th><th>Weight</th></tr>
    {''.join(f"""<tr>
      <td><b>{h['symbol']}</b></td>
      <td>{h['name'][:28]}</td>
      <td>{h['asset_class']}</td>
      <td>₹{indian_format(h['invested'])}</td>
      <td>₹{indian_format(h['current'])}</td>
      <td class="{'up' if h['pnl']>=0 else 'dn'}">{'▲' if h['pnl']>=0 else '▼'} ₹{indian_format(abs(h['pnl']))} ({abs(h['pnl_pct']):.1f}%)</td>
      <td>{h['weight']:.1f}%</td>
    </tr>""" for h in sorted(data['holdings'], key=lambda x:-x['weight'])[:5])}
  </table>
</div>""")

    # ── PAGE 3: COMPLETE HOLDINGS ──────────────────────────────────────────
    rows = sorted(data["holdings"], key=lambda x: -x["current"])
    pages.append(f"""
<div class="page">
  {_header("Holdings Detail", client_name, rdate, 3, TOTAL)}
  <div class="sec">All Holdings</div>
  <table>
    <tr><th>Symbol</th><th>Name</th><th>Class</th><th>Qty</th>
        <th>Avg Cost</th><th>Price</th><th>Invested</th><th>Current</th>
        <th>P&L</th><th>%</th></tr>
    {''.join(f"""<tr>
      <td><b>{h['symbol']}</b></td>
      <td style="max-width:80px;overflow:hidden">{h['name'][:22]}</td>
      <td>{h['asset_class'][:8]}</td>
      <td>{h['quantity']:,.3f}</td>
      <td>₹{indian_format(h['avg_cost'])}</td>
      <td>₹{indian_format(h['current_price'])}</td>
      <td>₹{indian_format(h['invested'])}</td>
      <td>₹{indian_format(h['current'])}</td>
      <td class="{'up' if h['pnl']>=0 else 'dn'}">{'▲' if h['pnl']>=0 else '▼'} ₹{indian_format(abs(h['pnl']))}</td>
      <td class="{'up' if h['pnl_pct']>=0 else 'dn'}">{h['pnl_pct']:+.1f}%</td>
    </tr>""" for h in rows)}
  </table>
</div>""")

    # ── PAGE 4: ALLOCATION + SECTOR ────────────────────────────────────────
    div_col, div_style = _div_color(data["div_score"])
    pages.append(f"""
<div class="page">
  {_header("Allocation & Sector Analysis", client_name, rdate, 4, TOTAL)}

  <div class="sec">By Asset Class</div>
  <table>
    <tr><th>Asset Class</th><th>Holdings</th><th>Invested</th><th>Current</th><th>P&L</th><th>Weight</th></tr>
    {''.join(f"""<tr>
      <td><b>{k}</b></td><td>{v['count']}</td>
      <td>₹{indian_format(v['inv'])}</td>
      <td>₹{indian_format(v['cur'])}</td>
      <td class="{'up' if v['cur']>=v['inv'] else 'dn'}">{'▲' if v['cur']>=v['inv'] else '▼'} ₹{indian_format(abs(v['cur']-v['inv']))}</td>
      <td>{v['cur']/data['total_cur']*100:.1f}%</td>
    </tr>""" for k,v in sorted(data['by_class'].items(),key=lambda x:-x[1]['cur']))}
  </table>

  <div class="sec">By Sector</div>
  <table>
    <tr><th>Sector</th><th>Holdings</th><th>Current Value</th><th>Weight</th></tr>
    {''.join(f"""<tr>
      <td><b>{k}</b></td><td>{v['count']}</td>
      <td>₹{indian_format(v['cur'])}</td>
      <td>{v['cur']/data['total_cur']*100:.1f}%</td>
    </tr>""" for k,v in sorted(data['by_sector'].items(),key=lambda x:-x[1]['cur'])[:12])}
  </table>

  <div class="sec">Diversification Assessment</div>
  <div class="score-wrap">
    <div class="score-ring" style="color:{div_col};{div_style}">{data['div_score']}</div>
    <div class="score-desc">
      <b>{_div_label(data['div_score'])}</b><br>
      Across <b>{data['n_classes']}</b> asset classes and <b>{data['n_sectors']}</b> sectors
      with <b>{data['n_holdings']}</b> holdings.<br>
      Score factors: class spread (25%), sector spread (25%), holding count (25%), concentration (25%).
    </div>
  </div>
  {''.join(_bar(k, v['cur'], data['total_cur'], CLASS_COLORS.get(k.split()[0] if k else "","#94a3b8"))
            for k,v in sorted(data['by_sub'].items(),key=lambda x:-x[1]['cur'])[:10])}
</div>""")

    # ── PAGE 5: PERIOD PERFORMANCE ─────────────────────────────────────────
    pages.append(f"""
<div class="page">
  {_header("Period Performance", client_name, rdate, 5, TOTAL)}
  <div class="sec">Performance — {period_label}</div>
  <div class="metrics">
    <div class="metric">
      <div class="lbl">Period Return</div>
      <div class="val {pr_c}">{pr_s} {abs(data['period_return']):.2f}%</div>
    </div>
    <div class="metric">
      <div class="lbl">All-Time P&L</div>
      <div class="val {pnl_c}">{pnl_s} ₹{indian_format(abs(data['total_pnl']))}</div>
      <div class="sub {pnl_c}">{data['total_pnl_pct']:+.2f}%</div>
    </div>
    <div class="metric">
      <div class="lbl">Annualised Return</div>
      <div class="val {'up' if ann>=0 else 'dn'}">{ann:+.2f}%</div>
    </div>
    <div class="metric">
      <div class="lbl">Best Performer</div>
      <div class="val up" style="font-size:.9rem">
        {max(data['holdings'],key=lambda x:x['pnl_pct'])['symbol'] if data['holdings'] else '—'}
      </div>
      <div class="sub up">
        {max(data['holdings'],key=lambda x:x['pnl_pct'])['pnl_pct']:+.1f}% if data['holdings'] else ''
      </div>
    </div>
  </div>

  <div class="sec">Individual Holding Returns ({period_label})</div>
  <table>
    <tr><th>Symbol</th><th>Name</th><th>Period Return</th><th>Weight</th></tr>
    {''.join(f"""<tr>
      <td><b>{p['symbol']}</b></td>
      <td>{p['name'][:30]}</td>
      <td class="{'up' if p['period_return']>=0 else 'dn'}">{p['period_return']:+.2f}%</td>
      <td>{p['weight']:.1f}%</td>
    </tr>""" for p in sorted(data['period_perf'],key=lambda x:-x['period_return']))}
  </table>

  <div class="sec">All-Time Top & Bottom Performers</div>
  <table>
    <tr><th>Symbol</th><th>Name</th><th>Class</th><th>All-Time P&L</th><th>Return %</th></tr>
    {''.join(f"""<tr>
      <td><b>{h['symbol']}</b></td><td>{h['name'][:28]}</td>
      <td>{h['asset_class']}</td>
      <td class="{'up' if h['pnl']>=0 else 'dn'}">₹{indian_format(abs(h['pnl']))}</td>
      <td class="{'up' if h['pnl_pct']>=0 else 'dn'}">{h['pnl_pct']:+.1f}%</td>
    </tr>""" for h in sorted(data['holdings'],key=lambda x:-x['pnl_pct'])[:5])}
    <tr><td colspan="5" style="background:#f1f5f9;color:#94a3b8;font-size:.72rem;padding:4px 10px">Worst Performers</td></tr>
    {''.join(f"""<tr>
      <td><b>{h['symbol']}</b></td><td>{h['name'][:28]}</td>
      <td>{h['asset_class']}</td>
      <td class="dn">₹{indian_format(abs(h['pnl']))}</td>
      <td class="dn">{h['pnl_pct']:+.1f}%</td>
    </tr>""" for h in sorted(data['holdings'],key=lambda x:x['pnl_pct'])[:3])}
  </table>
</div>""")

    # ── RISK PAGE (optional) ───────────────────────────────────────────────
    if include_risk:
        pg = len(pages)+1
        sh = data["sharpe"]
        sh_color = "up" if sh and sh>1 else ("neu" if sh and sh>0 else "dn")
        sh_label = ("Excellent" if sh and sh>2 else "Good" if sh and sh>1
                    else "Acceptable" if sh and sh>0 else "Poor" if sh else "Insufficient data")
        pages.append(f"""
<div class="page">
  {_header("Risk Assessment", client_name, rdate, pg, TOTAL)}
  <div class="sec">Risk Metrics</div>
  <div class="metrics">
    <div class="metric">
      <div class="lbl">Sharpe Ratio</div>
      <div class="val {sh_color}">{sh:.3f if sh else '—'}</div>
      <div class="sub neu">{sh_label}</div>
    </div>
    <div class="metric">
      <div class="lbl">Annualised Volatility</div>
      <div class="val">{data['volatility']:.2f}%</div>
      <div class="sub neu">{'Low' if data['volatility']<10 else 'Moderate' if data['volatility']<20 else 'High'}</div>
    </div>
    <div class="metric">
      <div class="lbl">Max Drawdown (1Y)</div>
      <div class="val dn">{data['max_dd']:.2f}%</div>
    </div>
    <div class="metric">
      <div class="lbl">Diversification</div>
      <div class="val">{data['div_score']}/100</div>
    </div>
  </div>
  <div class="sec">Risk by Asset Class</div>
  <table>
    <tr><th>Asset Class</th><th>Weight</th><th>Risk Level</th><th>Notes</th></tr>
    {''.join(f"""<tr>
      <td><b>{k}</b></td>
      <td>{v['cur']/data['total_cur']*100:.1f}%</td>
      <td class="{'dn' if k in ('Equity','Crypto') else 'neu' if k in ('Mutual Fund','ETF') else 'up'}">
        {'High' if k in ('Equity','Crypto') else 'Moderate' if k in ('Mutual Fund','ETF','Commodity') else 'Low'}
      </td>
      <td style="color:#64748b;font-size:.75rem">
        {'Market risk, price volatility' if k=='Equity'
         else 'Fund NAV risk, manager risk' if k=='Mutual Fund'
         else 'Market + liquidity risk' if k=='ETF'
         else 'Interest rate + credit risk' if k=='Bond'
         else 'Interest rate risk (low)' if k=='Bank FD'
         else 'Commodity price volatility' if k=='Commodity'
         else 'Very high volatility' if k=='Crypto'
         else 'Market risk'}
      </td>
    </tr>""" for k,v in sorted(data['by_class'].items(),key=lambda x:-x[1]['cur']))}
  </table>
  <div class="sec">Concentration Risk</div>
  <p style="font-size:.8rem;color:#475569;margin-bottom:8px">Top 5 holdings by weight — 
  concentrated positions increase single-stock risk.</p>
  <table>
    <tr><th>Symbol</th><th>Name</th><th>Weight</th><th>Risk Note</th></tr>
    {''.join(f"""<tr>
      <td><b>{h['symbol']}</b></td><td>{h['name'][:28]}</td>
      <td class="{'dn' if h['weight']>20 else 'neu' if h['weight']>10 else ''}">{h['weight']:.1f}%</td>
      <td style="font-size:.75rem;color:#64748b">
        {'⚠ High concentration — consider trimming' if h['weight']>20
         else '⚡ Moderate concentration' if h['weight']>10 else 'Acceptable weight'}
      </td>
    </tr>""" for h in sorted(data['holdings'],key=lambda x:-x['weight'])[:5])}
  </table>
</div>""")

    # ── SCENARIOS / STRESS PAGE (optional) ────────────────────────────────
    if include_scenarios or include_stress:
        pg = len(pages)+1
        cur = data["total_cur"]
        scenarios_to_show = SCENARIOS if include_stress else {
            k:v for k,v in SCENARIOS.items()
            if v in (30, 15, 0, -10, -30)
        }
        pages.append(f"""
<div class="page">
  {_header("Scenario & Stress Testing", client_name, rdate, pg, TOTAL)}
  <div class="sec">Market Scenario Analysis</div>
  <p style="font-size:.8rem;color:#475569;margin-bottom:10px">
    Estimated portfolio value under different market conditions,
    applied uniformly across all holdings. Actual impact varies by asset class.
  </p>
  <table>
    <tr><th>Scenario</th><th>Market Move</th><th>Estimated Value</th><th>Change</th></tr>
    {''.join(f"""<tr>
      <td><b>{name}</b></td>
      <td class="{'scenario-pos' if chg>=0 else 'scenario-neg'}">{'+' if chg>=0 else ''}{chg}%</td>
      <td>₹{indian_format(cur*(1+chg/100))}</td>
      <td class="{'scenario-pos' if chg>=0 else 'scenario-neg'}">
        {'▲' if chg>=0 else '▼'} ₹{indian_format(abs(cur*chg/100))}
      </td>
    </tr>""" for name,chg in scenarios_to_show.items())}
  </table>
  {'<div class="sec">Equity Stress Test</div><p style="font-size:.8rem;color:#475569;margin-bottom:10px">Equity holdings typically bear the brunt of market crashes. This shows impact on equity portion specifically.</p><table><tr><th>Scenario</th><th>Equity Impact</th><th>Portfolio Impact</th></tr>' + "".join(f"""<tr>
      <td>{name}</td>
      <td class="scenario-neg">₹{indian_format(abs(data['by_class'].get('Equity',{{}}).get('cur',0)*chg/100))}</td>
      <td class="scenario-neg">{abs(data['by_class'].get('Equity',{{}}).get('cur',0)/cur*chg):.1f}% of total</td>
    </tr>""" for name,chg in list(SCENARIOS.items()) if chg < 0) + "</table>" if include_stress and "Equity" in data["by_class"] else ""}
</div>""")

    # ── PROJECTIONS PAGE (optional) ────────────────────────────────────────
    if include_projections:
        pg   = len(pages)+1
        proj = _projection_rows(data["total_cur"], {
            "Conservative (8%)": 8,
            "Moderate (12%)":    12,
            "Optimistic (15%)":  15,
        }, years=10)
        pages.append(f"""
<div class="page">
  {_header("Projections", client_name, rdate, pg, TOTAL)}
  <div class="sec">10-Year Portfolio Projection</div>
  <p style="font-size:.8rem;color:#475569;margin-bottom:10px">
    Based on current value of ₹{indian_format(data['total_cur'])}.
    Projections assume no additional investments or withdrawals.
    For illustrative purposes only — not a guarantee of returns.
  </p>
  <table>
    <tr><th>Year</th><th>Conservative (8% p.a.)</th><th>Moderate (12% p.a.)</th><th>Optimistic (15% p.a.)</th></tr>
    {''.join(f"""<tr>
      <td><b>Year {r['year']}</b></td>
      <td>₹{indian_format(r['Conservative (8%)'])}</td>
      <td>₹{indian_format(r['Moderate (12%)'])}</td>
      <td>₹{indian_format(r['Optimistic (15%)'])}</td>
    </tr>""" for r in proj)}
  </table>
  <p style="font-size:.72rem;color:#94a3b8;margin-top:10px">
    These projections use compound annual growth rates (CAGR) and are for reference only.
    Actual returns depend on market conditions, asset allocation changes and investor behaviour.
    Past performance does not guarantee future results.
  </p>
</div>""")

    # Assemble full document
    return (f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<title>Qavi Report — {client_name}</title>"
            f"{_css()}</head><body>"
            + "\n".join(pages)
            + "</body></html>")


# ── STREAMLIT PAGE ────────────────────────────────────────────────────────
def render():
    user = st.session_state.get("user")
    if not user:
        navigate("login"); return

    role = user["role"]
    back_button(fallback="dashboard", key="top")

    st.markdown('<div class="page-title">Portfolio Report</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Generate a downloadable PDF-ready report</div>',
                unsafe_allow_html=True)

    pmap      = get_all_prices_map()
    assets_map = get_assets_map()

    # ── SELECT CLIENT / PORTFOLIOS ────────────────────────────────────────
    if role in ("advisor", "owner"):
        clients = get_advisor_clients(user["id"])
        if not clients:
            st.info("No clients linked yet."); return
        ac_map = {c["id"]: title_case(c["client_name"]) for c in clients}
        ac_id  = st.selectbox("Client", list(ac_map.keys()),
                               format_func=lambda x: ac_map[x])
        client_name = ac_map[ac_id]
        all_pfs = get_portfolios_for_ac(ac_id)
    else:
        # Client: own portfolios
        advisors = get_client_advisors(user["id"])
        all_pfs  = []
        for ac in advisors:
            for pf in get_portfolios_for_ac(ac["id"], visibility="shared"):
                all_pfs.append(pf)
        all_pfs += get_private_portfolios(user["id"])
        client_name = title_case(user.get("full_name","") or user.get("username",""))
        ac_id = None

    if not all_pfs:
        st.info("No portfolios found."); return

    pf_options = {pf["id"]: pf["name"] for pf in all_pfs}
    sel_pfs    = st.multiselect("Include Portfolios",
                                 list(pf_options.keys()),
                                 default=list(pf_options.keys()),
                                 format_func=lambda x: pf_options[x])
    if not sel_pfs:
        st.warning("Select at least one portfolio."); return

    # ── REPORT OPTIONS ─────────────────────────────────────────────────────
    st.markdown("#### Report Period")
    period_opts = {
        "1 Month":   30,
        "3 Months":  91,
        "6 Months":  182,
        "1 Year":    365,
        "3 Years":   365*3,
        "All Time":  365*10,
    }
    period_label = st.select_slider("Period",
                                     options=list(period_opts.keys()),
                                     value="1 Year")
    period_days  = period_opts[period_label]

    st.markdown("#### Optional Sections")
    c1, c2, c3, c4 = st.columns(4)
    include_risk        = c1.checkbox("Risk Assessment",    value=True)
    include_scenarios   = c2.checkbox("Scenario Analysis",  value=True)
    include_stress      = c3.checkbox("Stress Testing",     value=False)
    include_projections = c4.checkbox("10Y Projections",    value=True)

    st.markdown("""
    <div style="background:#1E2535;border-left:3px solid #4F7EFF;border-radius:0 8px 8px 0;
        padding:.65rem 1rem;font-size:.79rem;color:#C8D0E0;margin:.8rem 0">
        <b style="color:#4F7EFF">Always included:</b>
        Cover page · Executive summary · Full holdings table ·
        Asset allocation · Sector breakdown · Diversification score · Period performance
    </div>
    """, unsafe_allow_html=True)

    # ── GENERATE ──────────────────────────────────────────────────────────
    if st.button("📄 Generate Report", use_container_width=True, type="primary"):
        with st.spinner("Building report — fetching data and computing metrics…"):
            try:
                data = _collect_portfolio_data(sel_pfs, pmap, assets_map, period_days)
            except Exception as e:
                st.error(f"Data error: {e}"); return

            if data["n_holdings"] == 0:
                st.warning("Selected portfolios have no holdings."); return

            pf_names   = [pf_options[p] for p in sel_pfs]
            report_dt  = datetime.now().strftime("%d %b %Y, %I:%M %p")
            html       = build_report_html(
                data, client_name, period_label, report_dt,
                include_risk, include_scenarios, include_stress,
                include_projections, pf_names
            )

            b64      = base64.b64encode(html.encode("utf-8")).decode()
            fname    = f"Qavi_Report_{client_name.replace(' ','_')}_{date.today()}.html"

        st.success(f"✅ Report ready — {data['n_holdings']} holdings across {data['n_classes']} asset classes")

        # Preview metrics
        m1, m2, m3, m4 = st.columns(4)
        pnl_sign = "▲" if data["total_pnl"] >= 0 else "▼"
        m1.metric("Invested",      f"₹{indian_format(data['total_inv'])}")
        m2.metric("Current",       f"₹{indian_format(data['total_cur'])}")
        m3.metric("P&L",           f"{pnl_sign} ₹{indian_format(abs(data['total_pnl']))}",
                   f"{data['total_pnl_pct']:+.2f}%")
        m4.metric(f"{period_label} Return", f"{data['period_return']:+.2f}%")

        st.markdown(
            f'<a href="data:text/html;base64,{b64}" download="{fname}" '
            f'style="display:block;text-align:center;width:100%;'
            f'background:#4F7EFF;color:#fff;padding:.75rem 1rem;'
            f'border-radius:10px;font-size:.9rem;font-weight:600;'
            f'text-decoration:none;margin-top:.8rem">'
            f'⬇️ Download Report ({fname})</a>',
            unsafe_allow_html=True)

        st.caption("Open the downloaded .html file in any browser and use File → Print → Save as PDF to get a PDF.")
