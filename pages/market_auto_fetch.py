"""
market_auto_fetch.py — Automatic MF & ETF data sourcing

Sources used (all free, no API key required):
  1. mfapi.in/mf/{code}           — NAV, historical NAV, fund meta       [PRIMARY]
  2. mfapi.in/mf/{code}/details   — AUM, expense ratio, exit load,
                                    min investment, lock-in, risk         [EXTENDED META]
  3. mfapi.in/mf/{code}/portfolio — Top 10 holdings with % allocation    [HOLDINGS]
  4. amfiindia.com NAVAll.txt     — Active scheme detection              [FILTER]
  5. NSE API /etf                 — ETF prices, iNAV                     [ETF]
  6. Yahoo Finance (yfinance)     — ETF historical returns, expense ratio [ETF RETURNS]

Active scheme logic:
  A scheme is ACTIVE if it appears in AMFI NAVAll.txt with a NAV date
  within the last 10 trading days and is not a Segregated Portfolio,
  FMP, or Interval Fund.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate, back_button
from utils.db import sb, clear_market_cache
from datetime import datetime, date, timedelta
import time, requests

# ── CONSTANTS ─────────────────────────────────────────────────────────────
MFAPI_BASE  = "https://api.mfapi.in/mf"
AMFI_NAVALL = "https://www.amfiindia.com/spages/NAVAll.txt"

_EXCLUDE_KEYWORDS = [
    "segregated portfolio", "segregated fund",
    "fmp", "fixed maturity plan",
    "interval fund", "interval plan",
]

# ── HELPERS ───────────────────────────────────────────────────────────────
def _get(url, timeout=15, headers=None, session=None):
    try:
        h = {"User-Agent": "Mozilla/5.0 (compatible; QaviBot/1.0)"}
        if headers: h.update(headers)
        fn = (session or requests).get
        r  = fn(url, headers=h, timeout=timeout)
        r.raise_for_status()
        return r, None
    except Exception as e:
        return None, str(e)

def _pct(new, old):
    if old and old != 0:
        return round((new - old) / old * 100, 4)
    return 0.0

def _f(v, d=0.0):
    try: return float(str(v).replace(",","").strip())
    except: return d

# ── ACTIVE SCHEME DETECTION ───────────────────────────────────────────────
@st.cache_data(ttl=3600)
def fetch_active_scheme_codes():
    """
    Returns (set_of_active_codes, status_message).
    Downloads AMFI NAVAll.txt — only open-ended live schemes appear here.
    Filters to schemes with NAV date within last 10 days.
    NAVAll.txt columns (semicolon-separated):
      Code ; ISIN1 ; ISIN2 ; Scheme Name ; NAV ; Date
    """
    r, err = _get(AMFI_NAVALL, timeout=20)
    if err or not r:
        return set(), f"AMFI NAVAll fetch failed: {err}"

    active  = set()
    cutoff  = date.today() - timedelta(days=10)
    skipped = 0

    for line in r.text.strip().split("\n"):
        line = line.strip()
        if not line or ";" not in line or line.startswith("Scheme Code"):
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 6:
            continue
        try:
            code     = parts[0]
            name_low = parts[3].lower()
            nav_str  = parts[5].strip()
            if any(kw in name_low for kw in _EXCLUDE_KEYWORDS):
                skipped += 1; continue
            for fmt in ("%d-%b-%Y", "%d-%m-%Y"):
                try:
                    if datetime.strptime(nav_str, fmt).date() >= cutoff:
                        active.add(code)
                    break
                except ValueError:
                    continue
        except Exception:
            continue

    return active, f"{len(active)} active schemes (cutoff {cutoff}, {skipped} excluded)"

# ── MFAPI ENDPOINTS ───────────────────────────────────────────────────────
def fetch_mf_nav(code):
    """Returns (meta_dict, navs_list, error)."""
    r, err = _get(f"{MFAPI_BASE}/{code}", timeout=12)
    if err: return None, None, err
    try:
        d = r.json()
        return d.get("meta", {}), d.get("data", []), None
    except Exception as e:
        return None, None, str(e)

def fetch_mf_details(code):
    """
    /details endpoint: expenseRatio, exitLoad, aum, minInvestment,
    minAdditionalInvestment, riskLevel, fundManager, launchDate, lockInPeriod.
    Returns (dict, error).
    """
    r, err = _get(f"{MFAPI_BASE}/{code}/details", timeout=12)
    if err: return {}, err
    try: return r.json(), None
    except Exception as e: return {}, str(e)

def fetch_mf_portfolio(code):
    """
    /portfolio endpoint: top holdings.
    Returns (list_of_holdings, error).
    Each holding: {company, isin, percentage, sector}
    """
    r, err = _get(f"{MFAPI_BASE}/{code}/portfolio", timeout=12)
    if err: return [], err
    try:
        items = r.json().get("data", [])
        return [
            {
                "company":    h.get("company", h.get("name", "")),
                "isin":       h.get("isin", ""),
                "percentage": _f(h.get("percentage", 0)),
                "sector":     h.get("sector", ""),
            }
            for h in items[:10]
        ], None
    except Exception as e:
        return [], str(e)

def fetch_all_amfi_schemes():
    r, err = _get(MFAPI_BASE, timeout=15)
    if err: return None, err
    try: return r.json(), None
    except Exception as e: return None, str(e)

def compute_returns(navs):
    """Compute point-to-point returns from [{date, nav}] list (newest first)."""
    if not navs: return {}
    try:
        parsed = []
        for item in navs:
            try:
                d = datetime.strptime(item["date"], "%d-%m-%Y").date()
                parsed.append((d, float(item["nav"])))
            except: continue
        if not parsed: return {}
        parsed.sort(key=lambda x: x[0], reverse=True)
        cur, cur_dt = parsed[0]

        def _ret(days):
            tgt = cur_dt - timedelta(days=days)
            cl  = min(parsed, key=lambda x: abs((x[0]-tgt).days))
            return _pct(cur, cl[1]) if abs((cl[0]-tgt).days) <= 15 else None

        return {k: v for k, v in {
            "return_1m":  _ret(30),
            "return_3m":  _ret(91),
            "return_6m":  _ret(182),
            "return_1y":  _ret(365),
            "return_3y":  _ret(365*3),
            "return_5y":  _ret(365*5),
            "return_10y": _ret(365*10),
        }.items() if v is not None}
    except: return {}

def _build_row(code, meta, navs, details, include_returns=True):
    """Build complete mutual_funds table row from all sources."""
    if not navs: return None
    try:
        cur  = float(navs[0]["nav"])
        prev = float(navs[1]["nav"]) if len(navs) > 1 else cur
    except: return None

    row = {
        "scheme_code":   code,
        "symbol":        f"MF{code}",
        "name":          meta.get("scheme_name", f"MF{code}"),
        "fund_house":    meta.get("fund_house", ""),
        "category":      meta.get("scheme_category", ""),
        "sub_category":  meta.get("scheme_type", ""),
        "nav":           cur,
        "prev_nav":      prev,
        "change_pct":    _pct(cur, prev),
        "nav_date":      navs[0].get("date", ""),
        "last_updated":  datetime.now().isoformat(),
    }
    if details:
        if details.get("expenseRatio")           is not None: row["expense_ratio"]         = _f(details["expenseRatio"])
        if details.get("exitLoad")               is not None: row["exit_load"]             = str(details["exitLoad"])
        if details.get("aum")                    is not None: row["aum"]                   = _f(details["aum"])
        if details.get("minInvestment")          is not None: row["min_investment"]        = _f(details["minInvestment"])
        if details.get("minAdditionalInvestment")is not None: row["min_additional_invest"] = _f(details["minAdditionalInvestment"])
        if details.get("riskLevel"):                          row["risk_level"]            = str(details["riskLevel"])
        if details.get("fundManager"):                        row["fund_manager"]          = str(details["fundManager"])
        if details.get("launchDate"):                         row["launch_date"]           = str(details["launchDate"])
        if details.get("lockInPeriod") is not None:          row["lock_in_period"]        = str(details["lockInPeriod"])

    if include_returns:
        row.update(compute_returns(navs))
    return row

# ── ETF HELPERS ───────────────────────────────────────────────────────────
def _nse_session():
    sess = requests.Session()
    sess.headers.update({
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept":          "application/json,text/html,*/*",
        "Accept-Language": "en-IN,en;q=0.9",
        "Referer":         "https://www.nseindia.com/",
    })
    try: sess.get("https://www.nseindia.com/", timeout=8)
    except: pass
    time.sleep(0.5)
    return sess

def fetch_etf_data_nse():
    sess = _nse_session()
    r, err = _get(
        "https://www.nseindia.com/api/etf", session=sess,
        headers={"Referer": "https://www.nseindia.com/market-data/exchange-traded-funds-etf"},
    )
    if err: return None, err
    try: return r.json().get("data", []), None
    except Exception as e: return None, str(e)

def fetch_yf_returns(symbol_ns):
    try:
        import yfinance as yf
        tk    = yf.Ticker(symbol_ns)
        hist  = tk.history(period="5y")
        if hist.empty: return {}
        prices = hist["Close"].dropna()
        cur    = float(prices.iloc[-1])
        now_dt = prices.index[-1]

        def _ret(days):
            subset = prices[prices.index <= now_dt - timedelta(days=days)]
            return _pct(cur, float(subset.iloc[-1])) if not subset.empty else None

        info = {}
        try: info = tk.info or {}
        except: pass
        return {k: v for k, v in {
            "return_1m":     _ret(30),  "return_3m":     _ret(91),
            "return_6m":     _ret(182), "return_1y":     _ret(365),
            "return_3y":     _ret(365*3),"return_5y":    _ret(365*5),
            "aum":           _f(info.get("totalAssets", 0)),
            "expense_ratio": round(_f(info.get("annualReportExpenseRatio", 0)), 4),
            "fund_manager":  info.get("fundFamily", ""),
            "benchmark":     info.get("category", ""),
        }.items() if v}
    except: return {}

def _etf_sub(name):
    n = name.upper()
    if any(k in n for k in ("GOLD","SILVER","METAL","COMMODITY")): return "Commodity ETF"
    if any(k in n for k in ("LIQUID","MONEY","OVERNIGHT")):         return "Liquid ETF"
    if any(k in n for k in ("BANK","FIN","INFRA","IT","PHARMA","AUTO","SECTOR")): return "Sectoral ETF"
    return "Index ETF"

# ── PAGE ──────────────────────────────────────────────────────────────────
def render():
    if not st.session_state.get("user") or \
       st.session_state.user["role"] not in ("advisor","owner"):
        navigate("login"); return

    back_button(fallback="market_upload", key="top")

    st.markdown('<div class="page-title">Auto Fetch MF & ETF Data</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">NAV · AUM · Expense Ratio · Exit Load · Top Holdings · Returns</div>', unsafe_allow_html=True)

    st.markdown("""
    <div style="background:#1E2535;border:1px solid #252D40;border-radius:8px;
        padding:.9rem 1.2rem;margin-bottom:1rem;font-size:.8rem;color:#C8D0E0;line-height:2">
        <b>Data sources (all free, no API key needed):</b><br>
        🟢 <b>mfapi.in</b> — NAV, full historical NAV, fund meta (AMFI official)<br>
        🟢 <b>mfapi.in/details</b> — AUM, expense ratio (TER), exit load, min investment, risk level, fund manager<br>
        🟢 <b>mfapi.in/portfolio</b> — Top 10 holdings with % allocation and sector<br>
        🟢 <b>AMFI NAVAll.txt</b> — Active scheme detection (only live open-ended schemes)<br>
        🟢 <b>NSE API</b> — ETF live prices, iNAV, volume<br>
        🟡 <b>Yahoo Finance</b> — ETF returns, expense ratio, AUM (requires yfinance package)
    </div>
    """, unsafe_allow_html=True)

    tab_mf, tab_etf = st.tabs(["  🏦 Mutual Funds  ", "  💛 ETFs  "])

    # ══ MUTUAL FUNDS ══════════════════════════════════════════════════════
    with tab_mf:
        st.markdown("#### Mutual Fund Auto-Fetch")
        mode = st.radio("What to fetch", [
            "Update NAV + details for existing MFs in DB",
            "Fetch full details for specific scheme codes",
            "Bulk import from AMFI (active schemes only)",
        ], horizontal=False, key="mf_mode")

        # ── Mode 1: Update existing ────────────────────────────────────
        if mode == "Update NAV + details for existing MFs in DB":
            st.caption("Fetches latest NAV, AUM, expense ratio, exit load and returns for all MFs already in your DB.")
            c1, c2 = st.columns(2)
            inc_ret  = c1.checkbox("Compute historical returns", value=True, key="u_ret")
            inc_det  = c1.checkbox("Fetch AUM / expense ratio / exit load", value=True, key="u_det")
            inc_hld  = c2.checkbox("Fetch top 10 holdings", value=False,
                                    help="~1 extra call per fund — use selectively", key="u_hld")
            limit_n  = c2.number_input("Max funds (0 = all)", min_value=0, value=0, step=50, key="u_lim")

            if st.button("🚀 Fetch from AMFI", use_container_width=True, key="do_mf_nav"):
                try:
                    existing = sb().table("mutual_funds").select("symbol,scheme_code,name").execute().data or []
                except Exception as e:
                    st.error(f"DB error: {e}"); return

                if not existing:
                    st.warning("No MFs in database. Use Bulk import first."); return

                to_update = existing[:int(limit_n)] if limit_n > 0 else existing
                prog = st.progress(0.0); status = st.empty()
                ok = err = skipped = 0

                for i, mf in enumerate(to_update):
                    code = str(mf.get("scheme_code","")).strip()
                    if not code: skipped += 1; continue

                    meta, navs, ferr = fetch_mf_nav(code)
                    if ferr or not navs: err += 1; time.sleep(0.1); continue

                    details = {}
                    if inc_det:
                        details, _ = fetch_mf_details(code)
                        time.sleep(0.05)

                    row = _build_row(code, meta, navs, details, inc_ret)
                    if not row: err += 1; continue

                    if inc_hld:
                        holdings, _ = fetch_mf_portfolio(code)
                        if holdings:
                            import json
                            row["top_holdings"] = json.dumps(holdings)
                        time.sleep(0.08)

                    try:
                        sb().table("mutual_funds").update(row).eq("scheme_code", code).execute()
                        ok += 1
                    except: err += 1

                    prog.progress((i+1)/len(to_update), text=f"{i+1}/{len(to_update)}")
                    if (i+1) % 10 == 0:
                        status.markdown(f'<span style="font-size:.8rem;color:#C8D0E0">✓ {ok} updated · {err} errors · {skipped} skipped</span>', unsafe_allow_html=True)
                    time.sleep(0.05)

                prog.progress(1.0, text="Done ✓")
                clear_market_cache()
                st.success(f"✅ {ok} updated · {err} errors · {skipped} skipped (no scheme code)")

        # ── Mode 2: Specific codes ─────────────────────────────────────
        elif mode == "Fetch full details for specific scheme codes":
            st.caption("Enter AMFI scheme codes (one per line). Find codes at mfapi.in or valueresearchonline.com")
            codes_raw = st.text_area("Scheme codes", placeholder="119598\n120503\n118989", height=120)
            c1, c2 = st.columns(2)
            inc_ret2 = c1.checkbox("Compute returns", value=True, key="s_ret")
            inc_det2 = c1.checkbox("Fetch AUM / expense / exit load", value=True, key="s_det")
            inc_hld2 = c2.checkbox("Fetch top 10 holdings", value=True, key="s_hld")

            if st.button("🔍 Fetch Details", use_container_width=True, key="do_mf_specific"):
                codes = [c.strip() for c in codes_raw.strip().split("\n") if c.strip()]
                if not codes: st.error("Enter at least one scheme code."); return

                prog = st.progress(0.0); inserted = updated = err = 0

                for i, code in enumerate(codes):
                    meta, navs, ferr = fetch_mf_nav(code)
                    if ferr or not navs:
                        st.warning(f"Scheme {code}: {ferr or 'No NAV data'}")
                        err += 1; continue

                    details = {}
                    if inc_det2:
                        details, _ = fetch_mf_details(code); time.sleep(0.05)

                    row = _build_row(code, meta, navs, details, inc_ret2)
                    if not row: err += 1; continue

                    if inc_hld2:
                        holdings, _ = fetch_mf_portfolio(code)
                        if holdings:
                            import json; row["top_holdings"] = json.dumps(holdings)
                        time.sleep(0.08)

                    try:
                        if sb().table("mutual_funds").select("id").eq("scheme_code", code).execute().data:
                            sb().table("mutual_funds").update(row).eq("scheme_code", code).execute(); updated += 1
                        else:
                            sb().table("mutual_funds").insert(row).execute(); inserted += 1
                    except Exception as db_e:
                        st.warning(f"DB error {code}: {db_e}"); err += 1

                    prog.progress((i+1)/len(codes), text=f"{i+1}/{len(codes)}")
                    time.sleep(0.1)

                prog.progress(1.0, text="Done ✓")
                clear_market_cache()
                st.success(f"✅ {inserted} added · {updated} updated · {err} errors")

        # ── Mode 3: Bulk import active only ───────────────────────────
        else:
            st.caption("Downloads AMFI's full list, filters to **active open-ended schemes** only, then imports.")
            with st.expander("ℹ️ What counts as active?"):
                st.markdown("""
                - Listed in AMFI NAVAll.txt (live reporting schemes only)
                - NAV date within last **10 trading days**
                - Not Segregated Portfolio, FMP, or Interval Fund
                """)
            c1, c2 = st.columns(2)
            filt_house = c1.text_input("Filter by AMC", placeholder="SBI, HDFC…", key="bl_amc")
            filt_cat   = c2.text_input("Filter by category", placeholder="Equity, Debt…", key="bl_cat")
            c3, c4 = st.columns(2)
            inc_det3 = c3.checkbox("Fetch AUM / expense / exit load", value=True, key="bl_det")
            inc_ret3 = c4.checkbox("Compute returns from history", value=True, key="bl_ret")
            max_imp  = st.number_input("Max schemes", min_value=1, max_value=5000, value=300, step=50)

            if st.button("📋 Load Active Scheme List", use_container_width=True, key="amfi_load"):
                with st.spinner("Fetching active codes from AMFI…"):
                    active_codes, active_msg = fetch_active_scheme_codes()
                st.info(f"AMFI filter: {active_msg}")

                with st.spinner("Fetching scheme list from mfapi…"):
                    all_schemes, serr = fetch_all_amfi_schemes()
                if serr: st.error(f"mfapi error: {serr}"); return

                schemes = [s for s in all_schemes if str(s.get("schemeCode","")) in active_codes]
                if filt_house.strip():
                    fh = filt_house.strip().lower()
                    schemes = [s for s in schemes if fh in s.get("schemeName","").lower()]
                if filt_cat.strip():
                    fc = filt_cat.strip().lower()
                    schemes = [s for s in schemes if fc in s.get("schemeName","").lower()]
                schemes = schemes[:max_imp]

                st.success(f"**{len(schemes)} active schemes** matched.")
                if schemes:
                    import pandas as pd
                    st.dataframe(pd.DataFrame([
                        {"Code": s["schemeCode"], "Name": s["schemeName"][:70]}
                        for s in schemes[:10]
                    ]), use_container_width=True)
                    if len(schemes) > 10: st.caption(f"…and {len(schemes)-10} more")
                st.session_state["_amfi_schemes"] = schemes

            if st.session_state.get("_amfi_schemes"):
                schemes = st.session_state["_amfi_schemes"]
                if st.button(f"⬆️ Import {len(schemes)} Schemes", use_container_width=True, key="do_amfi_import"):
                    prog = st.progress(0.0); status = st.empty()
                    inserted = updated = err = 0
                    try:
                        existing_codes = {str(r["scheme_code"]) for r in
                                          sb().table("mutual_funds").select("scheme_code").execute().data or []}
                    except: existing_codes = set()

                    for i, s in enumerate(schemes):
                        code = str(s["schemeCode"])
                        meta, navs, ferr = fetch_mf_nav(code)
                        if ferr or not navs: err += 1; time.sleep(0.05); continue

                        details = {}
                        if inc_det3:
                            details, _ = fetch_mf_details(code); time.sleep(0.05)

                        row = _build_row(code, meta, navs, details, inc_ret3)
                        if not row: err += 1; continue

                        try:
                            if code in existing_codes:
                                sb().table("mutual_funds").update(row).eq("scheme_code", code).execute(); updated += 1
                            else:
                                sb().table("mutual_funds").insert(row).execute(); inserted += 1; existing_codes.add(code)
                        except: err += 1

                        prog.progress((i+1)/len(schemes), text=f"{i+1}/{len(schemes)}")
                        if (i+1) % 20 == 0:
                            status.markdown(f'<span style="font-size:.8rem;color:#C8D0E0">✓ {inserted} added · {updated} updated · {err} errors</span>', unsafe_allow_html=True)
                        time.sleep(0.08)

                    prog.progress(1.0, text="Done ✓")
                    clear_market_cache()
                    st.session_state.pop("_amfi_schemes", None)
                    st.success(f"✅ {inserted} new MFs added · {updated} updated · {err} errors")

    # ══ ETFs ══════════════════════════════════════════════════════════════
    with tab_etf:
        st.markdown("#### ETF Auto-Fetch")
        st.info("**Sources:** NSE for live prices / iNAV · Yahoo Finance for returns, AUM, expense ratio.")

        etf_mode = st.radio("What to fetch", [
            "Update prices for existing ETFs in DB",
            "Fetch all ETFs from NSE (full list)",
        ], horizontal=False, key="etf_mode")
        inc_yf = st.checkbox("Include Yahoo Finance data (returns, expense ratio, AUM)", value=True, key="etf_yf")

        if etf_mode == "Update prices for existing ETFs in DB":
            if st.button("🚀 Fetch ETF Prices from NSE", use_container_width=True, key="do_etf_nse"):
                with st.spinner("Connecting to NSE…"):
                    nse_etfs, err = fetch_etf_data_nse()
                if err: st.warning(f"NSE: {err}"); nse_etfs = []
                if not nse_etfs: st.error("No ETF data from NSE."); return

                nse_map = {e.get("symbol","").upper(): e for e in nse_etfs if e.get("symbol")}
                try:
                    existing = sb().table("assets").select("symbol,name").eq("asset_class","ETF").execute().data or []
                except Exception as e: st.error(f"DB: {e}"); return
                if not existing: st.warning("No ETFs in DB. Use Fetch all first."); return

                prog = st.progress(0.0); now = datetime.now().isoformat(); today = str(date.today()); ok = err = 0

                for i, etf in enumerate(existing):
                    sym = etf["symbol"]; nse_r = nse_map.get(sym)
                    close = _f(nse_r.get("lastPrice",0)) if nse_r else 0
                    inav  = _f(nse_r.get("iNavValue",0)) if nse_r else 0
                    prev  = _f(nse_r.get("previousClose",0)) if nse_r else 0
                    chg   = _f(nse_r.get("pChange",0)) if nse_r else 0
                    vol   = int(_f(nse_r.get("totalTradedVolume",0))) if nse_r else 0
                    price = close or inav
                    if price > 0:
                        try:
                            sb().table("prices").upsert({
                                "symbol": sym, "price_date": today,
                                "close": price, "open": _f(nse_r.get("open",price)) if nse_r else price,
                                "high": _f(nse_r.get("dayHigh",price)) if nse_r else price,
                                "low":  _f(nse_r.get("dayLow",price))  if nse_r else price,
                                "prev_close": prev or price, "change_pct": chg,
                                "volume": vol, "last_updated": now,
                            }, on_conflict="symbol,price_date").execute()
                            ok += 1
                        except: err += 1
                    if inc_yf:
                        yf = fetch_yf_returns(f"{sym}.NS")
                        if yf:
                            upd = {k: yf[k] for k in ("return_1m","return_3m","return_6m","return_1y","return_3y","return_5y","expense_ratio","aum","fund_manager","benchmark") if yf.get(k)}
                            if upd:
                                try: sb().table("assets").update(upd).eq("symbol", sym).execute()
                                except: pass
                        time.sleep(0.3)
                    prog.progress((i+1)/len(existing), text=f"{i+1}/{len(existing)}")
                    time.sleep(0.05)

                prog.progress(1.0, text="Done ✓"); clear_market_cache()
                st.success(f"✅ {ok} ETF prices updated · {err} skipped")

        else:
            st.caption("Fetches the complete NSE ETF list and adds any new ones to your database.")
            if st.button("📥 Fetch All ETFs from NSE", use_container_width=True, key="do_etf_all"):
                with st.spinner("Fetching NSE ETF list…"):
                    nse_etfs, err = fetch_etf_data_nse()
                if err or not nse_etfs: st.error(f"NSE fetch failed: {err or 'No data'}"); return

                st.markdown(f"**{len(nse_etfs)} ETFs** found on NSE.")
                try:
                    ex_syms = {r["symbol"] for r in sb().table("assets").select("symbol").eq("asset_class","ETF").execute().data or []}
                except: ex_syms = set()

                prog = st.progress(0.0); now = datetime.now().isoformat(); today = str(date.today())
                inserted = updated = err = 0

                for i, e in enumerate(nse_etfs):
                    sym  = str(e.get("symbol","")).upper().strip()
                    name = e.get("companyName", sym)
                    if not sym: continue

                    close = _f(e.get("lastPrice",0)); prev = _f(e.get("previousClose",0))
                    chg   = _f(e.get("pChange",0));   inav = _f(e.get("iNavValue",0))
                    vol   = int(_f(e.get("totalTradedVolume",0)))

                    try:
                        sb().table("assets").upsert({
                            "symbol": sym, "name": name, "asset_class": "ETF",
                            "sub_class": _etf_sub(name), "exchange": "NSE",
                            "is_active": True, "unit_type": "units",
                        }, on_conflict="symbol").execute()
                        updated += 1 if sym in ex_syms else None
                        if sym not in ex_syms: inserted += 1; ex_syms.add(sym)
                    except: err += 1; continue

                    price = close or inav
                    if price > 0:
                        try:
                            sb().table("prices").upsert({
                                "symbol": sym, "price_date": today,
                                "close": price, "open": _f(e.get("open",price)),
                                "high": _f(e.get("dayHigh",price)), "low": _f(e.get("dayLow",price)),
                                "prev_close": prev or price, "change_pct": chg,
                                "volume": vol, "last_updated": now,
                            }, on_conflict="symbol,price_date").execute()
                        except: pass

                    if inc_yf:
                        yf = fetch_yf_returns(f"{sym}.NS")
                        if yf:
                            upd = {k: yf[k] for k in ("return_1m","return_3m","return_6m","return_1y","return_3y","return_5y","expense_ratio","aum","fund_manager","benchmark") if yf.get(k)}
                            if upd:
                                try: sb().table("assets").update(upd).eq("symbol", sym).execute()
                                except: pass
                        time.sleep(0.3)

                    prog.progress((i+1)/len(nse_etfs), text=f"{i+1}/{len(nse_etfs)}")
                    time.sleep(0.02)

                prog.progress(1.0, text="Done ✓"); clear_market_cache()
                st.success(f"✅ {inserted} new ETFs added · {updated} updated · {err} errors")

    back_button(fallback="market_upload", label="← Back", key="bot")
