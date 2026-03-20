import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate
from utils.db import get_asset_info, get_asset_price, get_price_history, get_mf_by_symbol
from utils.crypto import inr, indian_format, fmt_date
from utils.market import fetch_mf_history, MF_SCHEME_CODES
import math

def _safe_float(v, default=0.0):
    try: return float(v)
    except: return default

def _returns_table(history, current_price):
    """Calculate returns for 1D, 1M, 3M, 6M, 1Y, 3Y, 5Y."""
    if not history or not current_price: return {}
    from datetime import date, timedelta
    today = date.today()
    periods = {"1D":1,"1M":30,"3M":90,"6M":180,"1Y":365,"3Y":1095,"5Y":1825}
    result = {}
    for label, days in periods.items():
        cutoff = today - timedelta(days=days)
        # Find the closest price on or before cutoff
        older = [h for h in history if h.get("price_date","") <= str(cutoff) or h.get("date","") <= str(cutoff)]
        if older:
            past_price = _safe_float(older[-1].get("close") or older[-1].get("nav", 0))
            if past_price > 0:
                ret = ((current_price - past_price) / past_price) * 100
                result[label] = ret
    return result

def render():
    symbol = st.session_state.get("selected_symbol")
    if not symbol:
        st.warning("No asset selected.")
        if st.button("← Back"): navigate("analysis")
        return

    price, chg = get_asset_price(symbol)
    info  = get_asset_info(symbol)
    mf    = get_mf_by_symbol(symbol)

    name  = (info or {}).get("name", symbol) if info else (mf or {}).get("name", symbol) if mf else symbol

    st.markdown(f'<div class="page-title">{symbol}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="page-sub">{name}</div>', unsafe_allow_html=True)
    if st.button("← Back to Analysis"): navigate("analysis")

    # Price header
    chg_c = "#2ECC7A" if chg >= 0 else "#FF5A5A"
    sign  = "▲" if chg >= 0 else "▼"
    st.markdown(f"""
    <div style="background:#161B27;border:1px solid #252D40;border-radius:14px;padding:1.4rem 1.8rem;margin:1rem 0;display:flex;justify-content:space-between;align-items:center">
        <div>
            <div style="font-size:.72rem;color:#8892AA;letter-spacing:.1em;text-transform:uppercase;margin-bottom:.3rem">Current Price</div>
            <div style="font-family:'Playfair Display',serif;font-size:2.4rem;font-weight:700;color:#F0F4FF">₹{indian_format(price)}</div>
        </div>
        <div style="text-align:right">
            <div style="font-size:1.5rem;font-weight:700;color:{chg_c}">{sign} {abs(chg):.2f}%</div>
            <div style="font-size:.78rem;color:#8892AA;margin-top:.2rem">Today's change</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs(["  📈 Returns  ", "  📊 Details  ", "  📋 Key Ratios  "])

    with tab1:
        # Price history
        history = get_price_history(symbol, days=1825)
        if not history and mf:
            code = MF_SCHEME_CODES.get(symbol)
            if code:
                raw = fetch_mf_history(code, days=1825)
                history = [{"price_date": d.get("date",""), "close": _safe_float(d.get("nav",0))} for d in raw if d.get("nav")]
                history.reverse()

        returns = _returns_table(history, price)

        if returns:
            st.markdown("#### Historical Returns")
            cols = st.columns(len(returns))
            for i, (label, ret) in enumerate(returns.items()):
                rc = "#2ECC7A" if ret >= 0 else "#FF5A5A"
                sign_r = "+" if ret >= 0 else ""
                cols[i].markdown(f"""
                <div style="text-align:center;background:#161B27;border:1px solid #252D40;border-radius:10px;padding:.9rem .5rem">
                    <div style="font-size:.7rem;color:#8892AA;margin-bottom:.3rem">{label}</div>
                    <div style="font-size:1.1rem;font-weight:700;color:{rc}">{sign_r}{ret:.1f}%</div>
                </div>""", unsafe_allow_html=True)

        # Simple price chart using ASCII-style HTML bars
        if history:
            st.markdown("<br>#### Price History (Last 60 Days)")
            recent = history[-60:] if len(history) > 60 else history
            if recent:
                prices_list = [_safe_float(h.get("close") or h.get("nav",0)) for h in recent]
                min_p = min(p for p in prices_list if p>0)
                max_p = max(prices_list)
                rng   = max_p - min_p or 1

                bar_html = '<div style="display:flex;align-items:flex-end;gap:2px;height:80px;background:#0F1117;border-radius:8px;padding:8px">'
                for p_val in prices_list[-40:]:
                    h_pct = ((p_val - min_p) / rng) * 100
                    bar_h  = max(4, int(h_pct * 0.64))
                    c      = "#4F7EFF"
                    bar_html += f'<div style="flex:1;height:{bar_h}px;background:{c};border-radius:2px 2px 0 0;opacity:0.8;min-width:3px"></div>'
                bar_html += '</div>'
                st.markdown(bar_html, unsafe_allow_html=True)
                st.caption(f"₹{indian_format(min_p)} – ₹{indian_format(max_p)} · Last 40 data points")
        else:
            st.info("Historical price data not yet available for this asset.")

    with tab2:
        if info:
            fields = [
                ("Symbol",       info.get("symbol","")),
                ("Name",         info.get("name","")),
                ("Asset Class",  info.get("asset_class","")),
                ("Sub-Category", info.get("sub_class","")),
                ("Sector",       info.get("sector","")),
                ("Exchange",     info.get("exchange","")),
                ("ISIN",         info.get("isin","")),
                ("Market Cap",   info.get("market_cap_category","")),
                ("Unit Type",    info.get("unit_type","")),
            ]
            st.markdown('<div style="background:#161B27;border:1px solid #252D40;border-radius:12px;padding:1.2rem 1.4rem">', unsafe_allow_html=True)
            for label, val in fields:
                if val:
                    st.markdown(f'<div style="display:flex;justify-content:space-between;padding:.45rem 0;border-bottom:1px solid #1E2535"><span style="font-size:.83rem;color:#8892AA">{label}</span><span style="font-size:.83rem;color:#F0F4FF;font-weight:500">{val}</span></div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
        elif mf:
            fields = [
                ("Fund Name",     mf.get("name","")),
                ("Fund House",    mf.get("fund_house","")),
                ("Category",      mf.get("category","")),
                ("Sub-Category",  mf.get("sub_category","")),
                ("Risk Level",    mf.get("risk_level","")),
                ("NAV",          f"₹{indian_format(mf.get('nav',0))}"),
                ("Prev NAV",     f"₹{indian_format(mf.get('prev_nav',0))}"),
                ("Change",       f"{mf.get('change_pct',0):+.4f}%"),
                ("Min Invest",   f"₹{indian_format(mf.get('min_investment',0))}"),
                ("Scheme Code",   mf.get("scheme_code","")),
            ]
            st.markdown('<div style="background:#161B27;border:1px solid #252D40;border-radius:12px;padding:1.2rem 1.4rem">', unsafe_allow_html=True)
            for label, val in fields:
                if val:
                    st.markdown(f'<div style="display:flex;justify-content:space-between;padding:.45rem 0;border-bottom:1px solid #1E2535"><span style="font-size:.83rem;color:#8892AA">{label}</span><span style="font-size:.83rem;color:#F0F4FF;font-weight:500">{val}</span></div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.info("Detailed information not available for this asset.")

    with tab3:
        if not history or len(history) < 30:
            st.info("Not enough historical data to calculate ratios. Need at least 30 data points.")
            return

        prices_list = [_safe_float(h.get("close") or h.get("nav",0)) for h in history if (h.get("close") or h.get("nav",0))]
        if len(prices_list) < 30:
            st.info("Insufficient price data for ratio calculations.")
            return

        # Daily returns
        daily_ret = [(prices_list[i]-prices_list[i-1])/prices_list[i-1] for i in range(1,len(prices_list)) if prices_list[i-1]>0]
        if not daily_ret:
            st.info("Cannot calculate ratios."); return

        avg_ret  = sum(daily_ret)/len(daily_ret)
        variance = sum((r-avg_ret)**2 for r in daily_ret)/len(daily_ret)
        std_dev  = math.sqrt(variance) if variance>0 else 0
        ann_ret  = avg_ret*252
        ann_std  = std_dev*math.sqrt(252)
        sharpe   = (ann_ret - 0.07) / ann_std if ann_std>0 else 0  # 7% risk-free rate
        max_dd   = 0.0
        peak     = prices_list[0]
        for p_v in prices_list:
            peak  = max(peak, p_v)
            dd    = (p_v-peak)/peak*100 if peak>0 else 0
            max_dd = min(max_dd, dd)

        ratios = [
            ("Annualised Return",   f"{ann_ret*100:+.2f}%"),
            ("Annualised Volatility", f"{ann_std*100:.2f}%"),
            ("Sharpe Ratio",        f"{sharpe:.3f}"),
            ("Max Drawdown",        f"{max_dd:.2f}%"),
            ("Daily Avg Return",    f"{avg_ret*100:+.4f}%"),
            ("Data Points",         str(len(prices_list))),
        ]
        if mf:
            ratios.append(("Expense Ratio", f"{mf.get('expense_ratio',0):.2f}%"))

        st.markdown('<div style="background:#161B27;border:1px solid #252D40;border-radius:12px;padding:1.2rem 1.4rem">', unsafe_allow_html=True)
        st.markdown('<div style="font-size:.7rem;color:#8892AA;letter-spacing:.1em;text-transform:uppercase;margin-bottom:.6rem">Calculated from available history</div>', unsafe_allow_html=True)
        for label, val in ratios:
            color = "#F0F4FF"
            if "Return" in label or "Sharpe" in label:
                try:
                    num = float(val.replace("%","").replace("+",""))
                    color = "#2ECC7A" if num > 0 else "#FF5A5A"
                except: pass
            if "Drawdown" in label:
                color = "#FF5A5A"
            st.markdown(f'<div style="display:flex;justify-content:space-between;padding:.5rem 0;border-bottom:1px solid #1E2535"><span style="font-size:.83rem;color:#8892AA">{label}</span><span style="font-size:.88rem;color:{color};font-weight:600">{val}</span></div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
        st.caption("Sharpe ratio uses 7% annual risk-free rate. Beta calculation requires benchmark history — coming soon.")
