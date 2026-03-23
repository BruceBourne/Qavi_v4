import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate
from utils.db import (get_advisor_clients, get_client_advisors, get_portfolios_for_ac,
                      get_private_portfolios, get_portfolio_holdings, get_all_prices_map,
                      get_price_history, get_indices, get_assets_map)
from utils.crypto import inr, indian_format
from collections import defaultdict
from datetime import date, timedelta
import math

# ── PRICE HELPERS ─────────────────────────────────────────────────────────
def _p(sym, pmap):
    r = pmap.get(sym)
    return (r["close"], r.get("change_pct", 0)) if r else (0.0, 0.0)

def _stats(holdings, pmap):
    inv = cur = 0.0
    for h in holdings:
        p, _ = _p(h["symbol"], pmap)
        inv += h["quantity"] * h["avg_cost"]
        cur += h["quantity"] * (p or h["avg_cost"])
    return inv, cur

# ── PERFORMANCE CALCULATIONS ──────────────────────────────────────────────
def _cagr(invested, current, years):
    """Compound Annual Growth Rate."""
    if invested <= 0 or years <= 0: return 0.0
    return ((current / invested) ** (1.0 / years) - 1) * 100

def _xirr(cashflows):
    """
    XIRR — Internal Rate of Return for irregular cashflows.
    cashflows: list of (date, amount) — negative = outflow, positive = inflow.
    Uses Newton-Raphson. Returns annual rate as decimal.
    """
    if len(cashflows) < 2: return 0.0
    dates   = [cf[0] for cf in cashflows]
    amounts = [cf[1] for cf in cashflows]
    t0      = dates[0]
    years   = [(d - t0).days / 365.0 for d in dates]
    def npv(rate):
        try: return sum(a / (1 + rate) ** t for a, t in zip(amounts, years))
        except (ZeroDivisionError, OverflowError): return float("inf")
    def dnpv(rate):
        try: return sum(-t * a / (1 + rate) ** (t + 1) for a, t in zip(amounts, years))
        except (ZeroDivisionError, OverflowError): return float("inf")
    rate = 0.1
    for _ in range(100):
        f  = npv(rate); df = dnpv(rate)
        if abs(df) < 1e-12: break
        rate -= f / df
        if rate <= -1: rate = -0.9999
    return round(rate * 100, 2)

def _volatility(returns):
    """Annualised volatility from daily returns list."""
    if len(returns) < 5: return 0.0
    n   = len(returns)
    mu  = sum(returns) / n
    var = sum((r - mu) ** 2 for r in returns) / (n - 1)
    return math.sqrt(var) * math.sqrt(252) * 100  # annualised %

def _sharpe(returns, risk_free_annual=6.5):
    """Sharpe ratio — excess return over risk-free (India 10Y GSec ~6.5%)."""
    if len(returns) < 5: return 0.0
    mu     = sum(returns) / len(returns) * 252  # annualised mean daily return %
    rf_daily = risk_free_annual / 252
    std    = _volatility(returns)
    if std == 0: return 0.0
    return (mu - risk_free_annual) / std

def _get_portfolio_returns(holdings, days=252):
    """
    Compute portfolio daily returns from price history.
    Weight each asset by current value. Returns list of daily % returns.
    """
    pmap = get_all_prices_map()
    weights = {}; total_val = 0.0
    for h in holdings:
        p, _ = _p(h["symbol"], pmap)
        v    = h["quantity"] * (p or h["avg_cost"])
        weights[h["symbol"]] = weights.get(h["symbol"], 0) + v
        total_val += v
    if total_val == 0: return []
    for s in weights: weights[s] /= total_val

    # Get price history for each symbol
    hist = {}
    for sym in weights:
        data = get_price_history(sym, days=days)
        if data: hist[sym] = {d["price_date"]: d["close"] for d in data}

    if not hist: return []

    # Find common dates
    date_sets = [set(v.keys()) for v in hist.values()]
    common    = sorted(set.intersection(*date_sets)) if date_sets else []
    if len(common) < 5: return []

    # Compute weighted daily returns
    port_returns = []
    for i in range(1, len(common)):
        d_prev = common[i-1]; d_cur = common[i]
        pr = 0.0
        for sym, w in weights.items():
            if sym in hist and d_prev in hist[sym] and d_cur in hist[sym]:
                p_prev = hist[sym][d_prev]; p_cur = hist[sym][d_cur]
                if p_prev > 0:
                    pr += w * ((p_cur - p_prev) / p_prev * 100)
        port_returns.append(pr)
    return port_returns

# ── ASSET CLASS BETAS ─────────────────────────────────────────────────────
# Sensible defaults for Indian market based on asset behaviour.
# Beta_rates = sensitivity to 1% interest rate change (negative = price falls when rates rise).
# Duration used for bond price sensitivity.
ASSET_BETAS = {
    # asset_class: {equity, rates, oil, inflation, fx, duration_years, convexity}
    "Equity":        {"equity":1.0,  "rates":-0.4, "oil":-0.2, "inflation":-0.3, "fx":-0.1, "duration":0,    "convexity":0},
    "Mutual Fund":   {"equity":0.85, "rates":-0.35,"oil":-0.15,"inflation":-0.25,"fx":-0.1, "duration":0,    "convexity":0},
    "ETF":           {"equity":0.9,  "rates":-0.3, "oil":-0.1, "inflation":-0.2, "fx":-0.1, "duration":0,    "convexity":0},
    "Bond":          {"equity":0.1,  "rates":-0.8, "oil":0.0,  "inflation":-0.5, "fx":0.1,  "duration":7.0,  "convexity":0.6},
    "Bank FD":       {"equity":0.0,  "rates":0.2,  "oil":0.0,  "inflation":-0.2, "fx":0.0,  "duration":2.0,  "convexity":0.05},
    "Commodity":     {"equity":0.3,  "rates":-0.2, "oil":0.8,  "inflation":0.6,  "fx":-0.4, "duration":0,    "convexity":0},
    "Physical Gold": {"equity":-0.1, "rates":-0.3, "oil":0.2,  "inflation":0.7,  "fx":-0.5, "duration":0,    "convexity":0},
    "Crypto":        {"equity":0.6,  "rates":-0.5, "oil":0.1,  "inflation":-0.1, "fx":-0.3, "duration":0,    "convexity":0},
    "Real Estate":   {"equity":0.4,  "rates":-0.6, "oil":0.1,  "inflation":0.4,  "fx":0.0,  "duration":10.0, "convexity":0.8},
    "Alternatives":  {"equity":0.7,  "rates":-0.3, "oil":0.1,  "inflation":0.1,  "fx":-0.2, "duration":0,    "convexity":0},
}

DEFAULT_BETA = {"equity":0.5,"rates":-0.3,"oil":0.0,"inflation":0.0,"fx":0.0,"duration":0,"convexity":0}

def _beta(ac): return ASSET_BETAS.get(ac, DEFAULT_BETA)

# ── DISPLAY HELPERS ───────────────────────────────────────────────────────
def _bar(label, val, total, color="#4F7EFF", show_val=True):
    pct     = (val / total * 100) if total else 0
    val_str = f"₹{indian_format(val)} · {pct:.1f}%" if show_val else f"{pct:.1f}%"
    return f"""<div class="stat-bar-row">
      <div class="stat-bar-label">
        <span style="font-size:.82rem;color:#F0F4FF">{label}</span>
        <span style="font-size:.82rem;color:{color};font-weight:600">{val_str}</span>
      </div>
      <div class="stat-bar-bg">
        <div class="stat-bar-fill" style="background:{color};width:{pct:.1f}%"></div>
      </div>
    </div>"""

def _metric_card(label, value, sub=None, color="#F0F4FF"):
    return (f'<div style="background:#161B27;border:1px solid #252D40;border-radius:9px;'
            f'padding:.85rem 1.1rem;margin-bottom:.6rem">'
            f'<div style="font-size:.62rem;color:#8892AA;letter-spacing:.08em;text-transform:uppercase;margin-bottom:.3rem">{label}</div>'
            f'<div style="font-size:1.25rem;font-weight:700;color:{color}">{value}</div>'
            f'{"<div style=font-size:.72rem;color:#8892AA;margin-top:.2rem>" + sub + "</div>" if sub else ""}'
            f'</div>')

# ── MAIN RENDER ───────────────────────────────────────────────────────────
def render():
    if not st.session_state.get("user"):
        navigate("login"); return
    user    = st.session_state.user
    role    = user["role"]
    indices = get_indices()
    pmap    = get_all_prices_map()
    amap    = get_assets_map()   # symbol → {name, sector, sub_class}

    st.markdown('<div class="page-title">Analysis</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Allocation · Performance · Risk · Scenarios</div>', unsafe_allow_html=True)

    # ── Portfolio selection ────────────────────────────────────────────────
    all_pfs = []
    if role in ("advisor","owner"):
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

    pf_opts = [("all","📊 All Portfolios Combined")] + [(p["id"], p["name"]) for p in all_pfs]
    sel_pf  = st.selectbox("Portfolio", [x[0] for x in pf_opts], format_func=lambda x: dict(pf_opts)[x])

    holdings = []
    bench_sym = "NIFTY50"
    if sel_pf == "all":
        for pf in all_pfs: holdings.extend(get_portfolio_holdings(pf["id"]))
    else:
        holdings = get_portfolio_holdings(sel_pf)
        pf_obj   = next((p for p in all_pfs if p["id"]==sel_pf), None)
        if pf_obj: bench_sym = pf_obj.get("benchmark","NIFTY50")

    if not holdings: st.info("No holdings in this selection."); return

    inv, cur = _stats(holdings, pmap)
    pnl      = cur - inv
    pnl_pct  = (pnl / inv * 100) if inv else 0

    m1,m2,m3,m4 = st.columns(4)
    m1.metric("Invested",      inr(inv))
    m2.metric("Current Value", inr(cur))
    m3.metric("P&L",           inr(pnl), f"{pnl_pct:+.2f}%")
    bench = next((i for i in indices if i["symbol"]==bench_sym), None)
    if bench:
        m4.metric(f"{bench['name']}", f"{bench['value']:,.2f}", f"{bench['change_pct']:+.2f}%")

    st.markdown("<br>", unsafe_allow_html=True)

    # Tab list — some tabs advisor-only
    if role in ("advisor","owner"):
        tabs = st.tabs(["  🥧 Allocation  ","  📈 Performance  ","  ⚠️ Risk  ",
                         "  📉 Rate Sensitivity  ","  🎯 Scenarios  ",
                         "  🔗 Correlation  ","  📊 VaR  ","  🔀 Cross-Portfolio  "])
        t_alloc, t_perf, t_risk, t_rate, t_scen, t_corr, t_var, t_cross = tabs
    else:
        tabs = st.tabs(["  🥧 Allocation  ","  📈 Performance  ","  ⚠️ Risk  "])
        t_alloc, t_perf, t_risk = tabs
        t_rate = t_scen = t_corr = t_var = t_cross = None

    colors = {"Equity":"#4F7EFF","Mutual Fund":"#A855F7","ETF":"#F5B731",
              "Bond":"#2ECC7A","Bank FD":"#14B8A6","Commodity":"#F97316",
              "Crypto":"#E84142","Real Estate":"#8B5CF6","Physical Gold":"#F59E0B",
              "Alternatives":"#6366F1"}

    # ── ALLOCATION ────────────────────────────────────────────────────────
    with t_alloc:
        class_vals  = defaultdict(float)
        sector_vals = defaultdict(float)
        sub_vals    = defaultdict(float)
        for h in holdings:
            p, _ = _p(h["symbol"], pmap)
            v    = h["quantity"] * (p or h["avg_cost"])
            ac   = h["asset_class"]
            class_vals[ac] += v

            # Use real sector from assets table; fall back to sub_class
            asset_info = amap.get(h["symbol"], {})
            sector     = (asset_info.get("sector") or "").strip()
            if sector:
                sector_vals[sector] += v
            else:
                sector_vals[h.get("sub_class","Unknown") or "Unknown"] += v

            sub_vals[h.get("sub_class","Other") or "Other"] += v

        st.markdown("#### By Asset Class")
        st.markdown('<div class="stat-bar-wrap">', unsafe_allow_html=True)
        for cls, val in sorted(class_vals.items(), key=lambda x:-x[1]):
            st.markdown(_bar(cls, val, cur, colors.get(cls,"#8892AA")), unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # Sector breakdown — only show if any sectors are populated
        has_sectors = any(k not in ("Unknown","Other","","Unclassified")
                          for k in sector_vals)
        if has_sectors:
            st.markdown("<br>#### By Sector", unsafe_allow_html=True)
            st.markdown('<div class="stat-bar-wrap">', unsafe_allow_html=True)
            for sec, val in sorted(sector_vals.items(), key=lambda x:-x[1])[:15]:
                st.markdown(_bar(sec, val, cur, "#A855F7"), unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.markdown(""); st.markdown("""<div style="background:#0F1117;border:1px solid #252D40;
                border-radius:8px;padding:.7rem 1rem;font-size:.77rem;color:#8892AA">
                Sector breakdown not available yet. Go to <b>Profile → Stock Enrichment</b>
                to populate sectors for your holdings.
            </div>""", unsafe_allow_html=True)

        st.markdown("<br>#### By Cap / Sub-Category", unsafe_allow_html=True)
        st.markdown('<div class="stat-bar-wrap">', unsafe_allow_html=True)
        for sub, val in sorted(sub_vals.items(), key=lambda x:-x[1])[:15]:
            st.markdown(_bar(sub, val, cur, "#4F7EFF"), unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # Holdings table with weight
        st.markdown("<br>#### Holdings Detail", unsafe_allow_html=True)
        hdr = st.columns([2.5,1.5,1.2,1.5,1.5,2,1.5])
        for col,lbl in zip(hdr,["Symbol","Asset","Qty","Avg Cost","LTP","P&L","Weight"]):
            col.markdown(f"<div style='font-size:.7rem;color:#8892AA;font-weight:600'>{lbl}</div>", unsafe_allow_html=True)
        st.markdown('<hr class="divider"/>', unsafe_allow_html=True)
        for h in sorted(holdings, key=lambda x:-(_p(x["symbol"],pmap)[0]*x["quantity"])):
            p, chg = _p(h["symbol"], pmap)
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
            st.markdown('<hr class="divider"/>', unsafe_allow_html=True)

    # ── PERFORMANCE ───────────────────────────────────────────────────────
    with t_perf:
        invest_dates = []
        for h in holdings:
            # Use today minus 1 year as proxy if no transaction date tracked
            invest_dates.append(date.today() - timedelta(days=365))
        first_invest = min(invest_dates) if invest_dates else date.today() - timedelta(days=365)
        years_held   = max((date.today() - first_invest).days / 365.0, 1/365)

        abs_ret  = pnl_pct
        cagr_val = _cagr(inv, cur, years_held)

        # XIRR — treat each holding as a cashflow at avg cost (buy), current value (sell today)
        cf = []
        for h in holdings:
            cf.append((date.today() - timedelta(days=int(years_held*365)), -h["quantity"]*h["avg_cost"]))
        cf.append((date.today(), cur))
        xirr_val = _xirr(cf) if len(cf) >= 2 else 0.0

        c1, c2, c3 = st.columns(3)
        c1.markdown(_metric_card("Absolute Return", f"{abs_ret:+.2f}%",
                                 f"₹{indian_format(abs(pnl))} {'profit' if pnl>=0 else 'loss'}",
                                 "#2ECC7A" if pnl>=0 else "#FF5A5A"), unsafe_allow_html=True)
        c2.markdown(_metric_card("CAGR", f"{cagr_val:+.2f}%",
                                 f"Over {years_held:.1f} year(s)",
                                 "#2ECC7A" if cagr_val>=0 else "#FF5A5A"), unsafe_allow_html=True)
        c3.markdown(_metric_card("XIRR", f"{xirr_val:+.2f}%",
                                 "Internal rate of return",
                                 "#2ECC7A" if xirr_val>=0 else "#FF5A5A"), unsafe_allow_html=True)

        # Benchmark comparison
        st.markdown("<br>#### Benchmark Comparison", unsafe_allow_html=True)
        bench_rows = [(i["name"], i["change_pct"]) for i in indices if i["symbol"] not in ("INDIA_VIX",)]
        bench_rows = [("📁 This Portfolio", pnl_pct)] + bench_rows[:6]
        for name, chg in bench_rows:
            pc   = "#2ECC7A" if chg>=0 else "#FF5A5A"
            sign = "▲" if chg>=0 else "▼"
            is_pf = name.startswith("📁")
            border = "2px solid #4F7EFF" if is_pf else "1px solid #252D40"
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;align-items:center;'
                f'background:#161B27;border:{border};border-radius:7px;'
                f'padding:.6rem 1rem;margin-bottom:.4rem">'
                f'<span style="font-size:.84rem;{"font-weight:700;color:#7BA3FF" if is_pf else "color:#C8D0E0"}">{name}</span>'
                f'<span style="color:{pc};font-weight:700;font-size:.9rem">{sign} {abs(chg):.2f}%</span></div>',
                unsafe_allow_html=True)

    # ── RISK ──────────────────────────────────────────────────────────────
    with t_risk:
        port_returns = _get_portfolio_returns(holdings, days=252)

        if len(port_returns) >= 20:
            vol      = _volatility(port_returns)
            sharpe   = _sharpe(port_returns)
            n        = len(port_returns)
            mu_daily = sum(port_returns) / n
            worst_1d = min(port_returns)
            best_1d  = max(port_returns)
            # Max drawdown
            peak    = 100.0; trough = 100.0; max_dd = 0.0; running = 100.0
            for r in port_returns:
                running *= (1 + r/100)
                if running > peak: peak = running
                dd = (peak - running) / peak * 100
                if dd > max_dd: max_dd = dd
        else:
            vol = sharpe = max_dd = worst_1d = best_1d = mu_daily = 0.0
            if len(port_returns) < 20:
                st.info("Less than 20 days of price history available. Upload more historical prices for accurate risk metrics.")

        c1, c2, c3 = st.columns(3)
        c1.markdown(_metric_card("Annual Volatility",
                                 f"{vol:.2f}%" if vol else "—",
                                 "Std dev of daily returns × √252",
                                 "#F5B731"), unsafe_allow_html=True)
        c2.markdown(_metric_card("Sharpe Ratio",
                                 f"{sharpe:.2f}" if sharpe else "—",
                                 "Risk-free rate: 6.5% (India 10Y GSec)",
                                 "#2ECC7A" if sharpe>=1 else "#F5B731" if sharpe>=0 else "#FF5A5A"),
                    unsafe_allow_html=True)
        c3.markdown(_metric_card("Max Drawdown",
                                 f"-{max_dd:.2f}%" if max_dd else "—",
                                 "Largest peak-to-trough decline",
                                 "#FF5A5A"), unsafe_allow_html=True)

        if port_returns:
            c4, c5 = st.columns(2)
            c4.markdown(_metric_card("Best Day",
                                     f"+{best_1d:.2f}%", None, "#2ECC7A"), unsafe_allow_html=True)
            c5.markdown(_metric_card("Worst Day",
                                     f"{worst_1d:.2f}%", None, "#FF5A5A"), unsafe_allow_html=True)

        st.markdown("""
        <div style="background:#0F1117;border:1px solid #252D40;border-radius:8px;
            padding:.8rem 1rem;margin-top:.6rem;font-size:.75rem;color:#8892AA;line-height:1.8">
            <b style="color:#C8D0E0">Interpretation guide</b><br>
            Volatility &lt; 10%: Low risk · 10–20%: Moderate · &gt; 20%: High<br>
            Sharpe &gt; 1.0: Good · &gt; 2.0: Excellent · &lt; 0: Underperforming risk-free rate<br>
            Sharpe ratio uses 6.5% as India 10-Year G-Sec risk-free benchmark
        </div>""", unsafe_allow_html=True)

    # ── INTEREST RATE SENSITIVITY (advisor only) ──────────────────────────
    if t_rate:
        with t_rate:
            st.markdown('<h4 style="margin:.3rem 0 .5rem 0;font-size:.95rem;color:#F0F4FF">Interest Rate Sensitivity</h4>', unsafe_allow_html=True)
            st.markdown("""
            <div style="font-size:.78rem;color:#8892AA;margin-bottom:.8rem;line-height:1.8">
                Shows how portfolio value changes with a shift in India's 10-Year G-Sec yield.<br>
                Formula: ΔV = −V × D × Δy + 0.5 × V × C × Δy²
            </div>""", unsafe_allow_html=True)

            # Portfolio duration and convexity
            port_duration  = 0.0
            port_convexity = 0.0
            for h in holdings:
                p, _  = _p(h["symbol"], pmap)
                val   = h["quantity"] * (p or h["avg_cost"])
                w     = val / cur if cur else 0
                b     = _beta(h["asset_class"])
                port_duration  += w * b["duration"]
                port_convexity += w * b["convexity"]

            c1, c2 = st.columns(2)
            c1.markdown(_metric_card("Portfolio Duration",
                                     f"{port_duration:.2f} years",
                                     "Value-weighted avg duration"), unsafe_allow_html=True)
            c2.markdown(_metric_card("Portfolio Convexity",
                                     f"{port_convexity:.2f}",
                                     "Curvature of price-yield relationship"), unsafe_allow_html=True)

            # Manual range controls
            st.markdown('<h4 style="margin:.8rem 0 .3rem 0;font-size:.95rem;color:#F0F4FF">Custom Rate Range</h4>', unsafe_allow_html=True)
            cr1, cr2 = st.columns(2)
            rate_min = cr1.slider("Min yield change (%)", min_value=-5.0, max_value=0.0,
                                   value=-2.0, step=0.1, key="rate_min")
            rate_max = cr2.slider("Max yield change (%)", min_value=0.0, max_value=5.0,
                                   value=2.0, step=0.1, key="rate_max")
            rate_steps = st.select_slider("Number of steps",
                                           options=[4, 6, 8, 10, 12, 16, 20],
                                           value=6, key="rate_steps")

            import numpy as np
            dy_range  = np.linspace(rate_min/100, rate_max/100, int(rate_steps))
            scenarios = [(f"{v*100:+.2f}%", float(v)) for v in dy_range]

            st.markdown('<h4 style="margin:.8rem 0 .3rem 0;font-size:.95rem;color:#F0F4FF">Sensitivity Table</h4>', unsafe_allow_html=True)
            hdr = st.columns([2,2,2,2])
            for col,lbl in zip(hdr,["Yield Change","ΔPortfolio Value","New Portfolio Value","Impact"]):
                col.markdown(f"<div style='font-size:.7rem;color:#8892AA;font-weight:600'>{lbl}</div>", unsafe_allow_html=True)
            st.markdown('<hr class="divider"/>', unsafe_allow_html=True)
            for label, dy in scenarios:
                delta_v = (- cur * port_duration * dy
                           + 0.5 * cur * port_convexity * dy**2)
                new_v   = cur + delta_v
                pct_chg = (delta_v / cur * 100) if cur else 0
                pc      = "#2ECC7A" if delta_v >= 0 else "#FF5A5A"
                rc = st.columns([2,2,2,2])
                rc[0].markdown(f"<div style='font-weight:600;font-size:.84rem'>{label}</div>", unsafe_allow_html=True)
                rc[1].markdown(f"<div style='color:{pc};font-weight:600;font-size:.84rem'>{'+'if delta_v>=0 else ''}₹{indian_format(abs(delta_v))}</div>", unsafe_allow_html=True)
                rc[2].markdown(f"<div style='font-size:.84rem'>₹{indian_format(new_v)}</div>", unsafe_allow_html=True)
                rc[3].markdown(f"<div style='color:{pc};font-size:.84rem'>{pct_chg:+.2f}%</div>", unsafe_allow_html=True)
                st.markdown('<hr class="divider"/>', unsafe_allow_html=True)

    # ── SCENARIO ANALYSIS (advisor only) ──────────────────────────────────
    if t_scen:
        with t_scen:
            st.markdown("#### Scenario Analysis")
            st.markdown('<div style="font-size:.78rem;color:#8892AA;margin-bottom:.8rem">Define macro shocks. Each asset responds differently based on its class betas. Add 2–10 factors.</div>', unsafe_allow_html=True)

            # Preset scenarios
            PRESETS = {
                "Custom": {},
                "Market Crash": {"equity":-20,"rates":1.0,"oil":-10,"inflation":-1,"fx":0},
                "Rate Hike +1%": {"equity":-5,"rates":1.0,"oil":0,"inflation":0.5,"fx":2},
                "Inflation Spike": {"equity":-8,"rates":2.0,"oil":20,"inflation":5,"fx":-3},
                "Crypto Crash -50%": {"equity":-3,"rates":0,"oil":0,"inflation":0,"fx":0,"crypto":-50},
                "Oil Shock +30%": {"equity":-5,"rates":0.5,"oil":30,"inflation":3,"fx":-2},
                "Weak Rupee -10%": {"equity":-3,"rates":1.0,"oil":10,"inflation":2,"fx":-10},
            }
            preset = st.selectbox("Quick Preset", list(PRESETS.keys()))
            pvals  = PRESETS[preset]

            factors = ["equity","rates","oil","inflation","fx"]
            factor_labels = {"equity":"Equity Markets (%)","rates":"Interest Rates (% pt)",
                             "oil":"Crude Oil (%)","inflation":"Inflation (% pt)","fx":"INR vs USD (%)"}
            shocks = {}
            cols   = st.columns(len(factors))
            for i, f in enumerate(factors):
                default_v = float(pvals.get(f, 0))
                shocks[f] = cols[i].number_input(factor_labels[f],
                                                  value=default_v, step=0.5, format="%.1f",
                                                  key=f"shock_{f}")

            # Optional extra factors (up to 5 more)
            with st.expander("➕ Add more factors (optional)"):
                extra_factors = {}
                ex_cols = st.columns(2)
                extra_names = ["crypto","real_estate","gold","private_equity","bond_spread"]
                extra_labels = {"crypto":"Crypto (%)","real_estate":"Real Estate (%)","gold":"Gold (%)",
                                "private_equity":"Private Equity (%)","bond_spread":"Bond Spread (bps)"}
                for i, ef in enumerate(extra_names[:5]):
                    default_v = float(pvals.get(ef, 0))
                    extra_factors[ef] = ex_cols[i%2].number_input(extra_labels[ef],
                                                                    value=default_v, step=1.0,
                                                                    key=f"shock_{ef}")
            shocks.update(extra_factors)

            if st.button("▶ Run Scenario", use_container_width=True):
                # Compute scenario return for each holding
                total_scenario_pnl = 0.0
                holding_results = []
                for h in holdings:
                    p, _  = _p(h["symbol"], pmap)
                    val   = h["quantity"] * (p or h["avg_cost"])
                    w     = val / cur if cur else 0
                    b     = _beta(h["asset_class"])
                    # Scenario return for this holding (%)
                    scen_ret = (b["equity"]    * shocks.get("equity", 0) +
                                b["rates"]     * shocks.get("rates", 0) +
                                b["oil"]       * shocks.get("oil", 0) +
                                b["inflation"] * shocks.get("inflation", 0) +
                                b["fx"]        * shocks.get("fx", 0))
                    # Crypto holding gets full crypto shock
                    if h["asset_class"] == "Crypto":
                        scen_ret += shocks.get("crypto", 0)
                    elif h["asset_class"] == "Physical Gold":
                        scen_ret += shocks.get("gold", 0) * 0.8
                    scen_pnl = val * scen_ret / 100
                    total_scenario_pnl += scen_pnl
                    holding_results.append((h["symbol"], h["asset_class"], val, w*100, scen_ret, scen_pnl))

                total_pct  = (total_scenario_pnl / cur * 100) if cur else 0
                pc         = "#2ECC7A" if total_scenario_pnl>=0 else "#FF5A5A"
                st.markdown(f"""
                <div style="background:#1E2535;border:2px solid {pc};border-radius:10px;
                    padding:1.2rem 1.5rem;margin:.8rem 0;text-align:center">
                    <div style="font-size:.7rem;color:#8892AA;letter-spacing:.1em;text-transform:uppercase;margin-bottom:.3rem">
                        Scenario Portfolio Impact
                    </div>
                    <div style="font-size:2rem;font-weight:800;color:{pc}">
                        {'+'if total_scenario_pnl>=0 else ''}₹{indian_format(abs(total_scenario_pnl))}
                        &nbsp;<span style="font-size:1.2rem">({total_pct:+.2f}%)</span>
                    </div>
                    <div style="font-size:.75rem;color:#8892AA;margin-top:.3rem">
                        New Portfolio Value: ₹{indian_format(cur + total_scenario_pnl)}
                    </div>
                </div>""", unsafe_allow_html=True)

                # Per-holding breakdown
                st.markdown("#### Per-Holding Impact")
                hdr = st.columns([2,1.5,1.5,1.5,1.5])
                for col,lbl in zip(hdr,["Symbol","Asset Class","Value","Scenario Return","P&L Impact"]):
                    col.markdown(f"<div style='font-size:.7rem;color:#8892AA;font-weight:600'>{lbl}</div>", unsafe_allow_html=True)
                st.markdown('<hr class="divider"/>', unsafe_allow_html=True)
                for sym, ac, val, w, sret, spnl in sorted(holding_results, key=lambda x:-abs(x[5])):
                    pc = "#2ECC7A" if spnl>=0 else "#FF5A5A"
                    rc = st.columns([2,1.5,1.5,1.5,1.5])
                    rc[0].markdown(f"<div style='font-weight:600;font-size:.85rem'>{sym}</div>", unsafe_allow_html=True)
                    rc[1].markdown(f"<div style='font-size:.8rem;color:#8892AA'>{ac}</div>", unsafe_allow_html=True)
                    rc[2].markdown(f"<div style='font-size:.83rem'>₹{indian_format(val)}</div>", unsafe_allow_html=True)
                    rc[3].markdown(f"<div style='color:{pc};font-size:.83rem'>{sret:+.2f}%</div>", unsafe_allow_html=True)
                    rc[4].markdown(f"<div style='color:{pc};font-weight:600;font-size:.83rem'>₹{indian_format(abs(spnl))}</div>", unsafe_allow_html=True)
                    st.markdown('<hr class="divider"/>', unsafe_allow_html=True)

    # ── CORRELATION MATRIX (advisor only) ────────────────────────────────
    if t_corr:
        with t_corr:
            st.markdown("#### Asset Class Correlation Matrix")
            st.markdown('<div style="font-size:.78rem;color:#8892AA;margin-bottom:.8rem">Pearson correlation of daily returns across asset classes. Based on available price history. Values closer to +1 = move together, −1 = move opposite, 0 = no relationship.</div>', unsafe_allow_html=True)

            # Build asset-class level daily returns from holdings
            ac_returns = defaultdict(list)
            date_returns = defaultdict(lambda: defaultdict(float))
            date_weights = defaultdict(lambda: defaultdict(float))

            for h in holdings:
                p, _ = _p(h["symbol"], pmap)
                val  = h["quantity"] * (p or h["avg_cost"])
                data = get_price_history(h["symbol"], days=252)
                if not data or len(data) < 5: continue
                ac = h["asset_class"]
                for i in range(1, len(data)):
                    d      = data[i]["price_date"]
                    p_prev = data[i-1]["close"]; p_cur = data[i]["close"]
                    if p_prev > 0:
                        ret = (p_cur - p_prev) / p_prev * 100
                        date_returns[d][ac] += ret * val
                        date_weights[d][ac] += val

            # Normalize to weighted average return per asset class per day
            ac_daily = defaultdict(dict)
            for d, ac_map_d in date_returns.items():
                for ac, wtd_ret in ac_map_d.items():
                    w = date_weights[d][ac]
                    if w > 0:
                        ac_daily[ac][d] = wtd_ret / w

            # Common dates across asset classes
            acs = sorted(ac_daily.keys())
            if len(acs) < 2:
                st.info("Need at least 2 asset classes with price history for correlation. Upload more price data.")
            else:
                date_sets   = [set(ac_daily[a].keys()) for a in acs]
                common_dates = sorted(set.intersection(*date_sets))
                if len(common_dates) < 10:
                    st.info(f"Only {len(common_dates)} common trading days found. Need at least 10.")
                else:
                    ret_matrix = {a: [ac_daily[a][d] for d in common_dates] for a in acs}
                    means = {a: sum(ret_matrix[a])/len(ret_matrix[a]) for a in acs}
                    n     = len(common_dates)

                    def cov(a, b):
                        return sum((ret_matrix[a][i]-means[a])*(ret_matrix[b][i]-means[b]) for i in range(n)) / (n-1)
                    def std(a):
                        return math.sqrt(cov(a, a))
                    def corr(a, b):
                        sa = std(a); sb = std(b)
                        return cov(a, b)/(sa*sb) if sa>0 and sb>0 else 0

                    # Render matrix
                    header_cols = st.columns([2] + [1.2]*len(acs))
                    header_cols[0].markdown("", unsafe_allow_html=True)
                    for i, ac in enumerate(acs):
                        header_cols[i+1].markdown(f"<div style='font-size:.7rem;color:#8892AA;font-weight:600;text-align:center'>{ac[:8]}</div>", unsafe_allow_html=True)

                    for a in acs:
                        row_cols = st.columns([2] + [1.2]*len(acs))
                        row_cols[0].markdown(f"<div style='font-size:.8rem;font-weight:600;padding:.3rem 0'>{a[:12]}</div>", unsafe_allow_html=True)
                        for i, b in enumerate(acs):
                            c_val = corr(a, b)
                            if a == b:
                                cell_c = "#4F7EFF"; cell_bg = "#1A2040"
                            elif c_val > 0.5:
                                cell_c = "#FF5A5A"; cell_bg = "#2A1515"
                            elif c_val < -0.3:
                                cell_c = "#2ECC7A"; cell_bg = "#152A1E"
                            else:
                                cell_c = "#C8D0E0"; cell_bg = "#161B27"
                            row_cols[i+1].markdown(
                                f'<div style="background:{cell_bg};border-radius:5px;padding:.3rem;'
                                f'text-align:center;font-weight:600;font-size:.82rem;color:{cell_c}">'
                                f'{c_val:.2f}</div>',
                                unsafe_allow_html=True)

                    st.caption(f"Based on {len(common_dates)} trading days. Red = high correlation (>0.5), green = negative correlation (<−0.3).")

    # ── VALUE AT RISK (advisor only) ──────────────────────────────────────
    if t_var:
        with t_var:
            st.markdown("#### Value at Risk (VaR)")
            st.markdown('<div style="font-size:.78rem;color:#8892AA;margin-bottom:.8rem">Estimates the maximum expected loss at a given confidence level. Uses Historical Simulation (most reliable for non-normal distributions common in Indian markets).</div>', unsafe_allow_html=True)

            port_returns_var = _get_portfolio_returns(holdings, days=504)  # 2 years preferred

            if len(port_returns_var) < 30:
                st.info("Need at least 30 days of price history for VaR. Upload more historical bhavcopy data.")
            else:
                sorted_rets = sorted(port_returns_var)
                n           = len(sorted_rets)

                # Historical VaR at multiple confidence levels
                var_levels = [(90, 0.10), (95, 0.05), (99, 0.01)]
                c1, c2, c3 = st.columns(3)
                cols_var    = [c1, c2, c3]
                for col, (conf, alpha) in zip(cols_var, var_levels):
                    idx      = max(0, int(alpha * n) - 1)
                    var_pct  = abs(sorted_rets[idx])
                    var_amt  = cur * var_pct / 100
                    col.markdown(_metric_card(f"VaR {conf}% (1-day)",
                                              f"−{var_pct:.2f}%",
                                              f"₹{indian_format(var_amt)}",
                                              "#FF5A5A"), unsafe_allow_html=True)

                # CVaR / Expected Shortfall at 95%
                cutoff    = max(0, int(0.05 * n))
                cvar_pct  = abs(sum(sorted_rets[:cutoff]) / max(cutoff, 1))
                cvar_amt  = cur * cvar_pct / 100
                st.markdown(_metric_card("CVaR / Expected Shortfall (95%)",
                                         f"−{cvar_pct:.2f}%",
                                         f"Average loss beyond VaR: ₹{indian_format(cvar_amt)}",
                                         "#FF5A5A"), unsafe_allow_html=True)

                # Annualised VaR
                var_95_daily = abs(sorted_rets[max(0, int(0.05*n)-1)])
                var_annual   = var_95_daily * math.sqrt(252)
                var_annual_amt = cur * var_annual / 100
                st.markdown(_metric_card("Annualised VaR (95%)",
                                         f"−{var_annual:.2f}%",
                                         f"₹{indian_format(var_annual_amt)} · √252 scaling",
                                         "#FF5A5A"), unsafe_allow_html=True)

                st.markdown(f"""
                <div style="background:#0F1117;border:1px solid #252D40;border-radius:8px;
                    padding:.8rem 1rem;margin-top:.6rem;font-size:.75rem;color:#8892AA;line-height:1.8">
                    <b style="color:#C8D0E0">Interpretation</b><br>
                    VaR 95% = On any given day, there is a 5% chance of losing more than {var_95_daily:.2f}% (₹{indian_format(cur*var_95_daily/100)}).<br>
                    CVaR = When losses exceed VaR, the average loss is {cvar_pct:.2f}%.<br>
                    Based on {len(port_returns_var)} trading days of historical data.
                </div>""", unsafe_allow_html=True)

    # ── CROSS-PORTFOLIO (advisor only) ────────────────────────────────────
    if t_cross:
        with t_cross:
            if role not in ("advisor","owner"):
                st.info("Advisor only."); return
            rows = []
            for cl in get_advisor_clients(user["id"]):
                for pf in get_portfolios_for_ac(cl["id"]):
                    hs          = get_portfolio_holdings(pf["id"])
                    pi, pv      = _stats(hs, pmap)
                    pp          = pv - pi
                    ppc         = (pp/pi*100) if pi else 0
                    rows.append({"Client":cl["client_name"],"Portfolio":pf["name"],
                                 "Invested":pi,"Value":pv,"PnL":pp,"Ret%":ppc,"N":len(hs)})
            if not rows: st.info("No data."); return

            total_aum = sum(r["Value"] for r in rows)
            st.markdown(f'<div style="font-size:.82rem;color:#8892AA;margin-bottom:.5rem">Total AUM across all portfolios: <b style="color:#F0F4FF">₹{indian_format(total_aum)}</b></div>', unsafe_allow_html=True)

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
