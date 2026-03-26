"""
market_auto_fetch.py — Automatic MF & ETF data sourcing

Sources used:
  1. AMFI India (mfapi.in)   — NAV, scheme details, historical NAV (FREE, official)
  2. NSE India APIs          — ETF prices, AUM, iNAV
  3. RapidAPI / Yahoo Finance — Returns (1m/3m/1y/3y/5y), AUM, expense ratio
     NOTE: yfinance .NS suffix works for ETFs; MF symbols use AMFI scheme codes

Priority:
  MF NAV   → mfapi.in (AMFI official, most reliable)
  MF meta  → mfapi.in scheme details
  ETF      → NSE + yfinance
  Returns  → computed from historical NAV (mfapi.in) or yfinance
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate, back_button
from utils.db import sb, clear_market_cache
from datetime import datetime, date, timedelta
import time, requests, json

# ── HELPERS ───────────────────────────────────────────────────────────────
def _get(url, timeout=12, headers=None, session=None):
    """Safe GET — returns (data_or_text, error_str)."""
    try:
        h = {"User-Agent": "Mozilla/5.0 (compatible; QaviBot/1.0)"}
        if headers: h.update(headers)
        fn = (session or requests).get
        r  = fn(url, headers=h, timeout=timeout)
        r.raise_for_status()
        return r, None
    except Exception as e:
        return None, str(e)

def _pct_change(new, old):
    if old and old != 0:
        return round((new - old) / old * 100, 4)
    return 0.0

# ── MF DATA FROM MFAPI.IN (AMFI Official) ────────────────────────────────
def fetch_mf_nav_amfi(scheme_code: str):
    """
    mfapi.in wraps AMFI official data.
    Returns dict with nav, nav_date, name, fund_house, historical NAVs.
    Completely free, no API key needed.
    """
    r, err = _get(f"https://api.mfapi.in/mf/{scheme_code}")
    if err: return None, err
    try:
        data  = r.json()
        meta  = data.get("meta", {})
        navs  = data.get("data", [])   # [{date, nav}, ...] newest first
        return {"meta": meta, "navs": navs}, None
    except Exception as e:
        return None, str(e)

def compute_returns_from_navs(navs: list):
    """
    navs: list of {date: 'DD-MM-YYYY', nav: '123.45'} — newest first.
    Returns dict of {return_1m, return_3m, return_6m, return_1y, return_3y, return_5y, return_10y}.
    """
    if not navs: return {}
    try:
        # Parse into (date, float_nav) sorted newest first
        parsed = []
        for item in navs:
            try:
                d   = datetime.strptime(item["date"], "%d-%m-%Y").date()
                nav = float(item["nav"])
                parsed.append((d, nav))
            except Exception:
                continue
        if not parsed: return {}
        parsed.sort(key=lambda x: x[0], reverse=True)
        current_nav  = parsed[0][1]
        current_date = parsed[0][0]

        def _ret(days):
            target = current_date - timedelta(days=days)
            # Find closest nav to target date
            closest = min(parsed, key=lambda x: abs((x[0] - target).days))
            if abs((closest[0] - target).days) > 15: return None  # too far
            return _pct_change(current_nav, closest[1])

        return {
            "return_1m":  _ret(30),
            "return_3m":  _ret(91),
            "return_6m":  _ret(182),
            "return_1y":  _ret(365),
            "return_3y":  _ret(365*3),
            "return_5y":  _ret(365*5),
            "return_10y": _ret(365*10),
        }
    except Exception:
        return {}

def fetch_all_amfi_schemes():
    """
    AMFI publishes a complete list of all MF schemes.
    Returns list of {scheme_code, name, fund_house, category, nav, nav_date}.
    """
    r, err = _get("https://api.mfapi.in/mf")
    if err: return None, err
    try:
        schemes = r.json()
        return schemes, None
    except Exception as e:
        return None, str(e)

# ── ETF DATA FROM NSE ─────────────────────────────────────────────────────
def _nse_session():
    sess = requests.Session()
    sess.headers.update({
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept":          "application/json,text/html,*/*",
        "Accept-Language": "en-IN,en;q=0.9",
        "Referer":         "https://www.nseindia.com/",
    })
    try: sess.get("https://www.nseindia.com/", timeout=8)
    except Exception: pass
    time.sleep(0.5)
    return sess

def fetch_etf_data_nse():
    """
    NSE ETF list with iNAV, price, AUM.
    Returns list of ETF dicts.
    """
    sess = _nse_session()
    r, err = _get(
        "https://www.nseindia.com/api/etf",
        session=sess,
        headers={"Referer": "https://www.nseindia.com/market-data/exchange-traded-funds-etf"}
    )
    if err: return None, err
    try:
        data = r.json()
        return data.get("data", []), None
    except Exception as e:
        return None, str(e)

# ── YFINANCE FOR RETURNS ──────────────────────────────────────────────────
def fetch_yf_returns(symbol_ns: str):
    """
    Fetch 5yr history from Yahoo Finance for return computation.
    symbol_ns: e.g. 'NIFTYBEES.NS'
    """
    try:
        import yfinance as yf
        tk   = yf.Ticker(symbol_ns)
        hist = tk.history(period="5y")
        if hist.empty: return {}
        prices = hist["Close"].dropna()
        cur    = float(prices.iloc[-1])
        now    = prices.index[-1]

        def _ret(days):
            target = now - timedelta(days=days)
            subset = prices[prices.index <= target]
            if subset.empty: return None
            old = float(subset.iloc[-1])
            return _pct_change(cur, old)

        info = {}
        try:
            info = tk.info or {}
        except Exception:
            pass

        return {
            "return_1m":     _ret(30),
            "return_3m":     _ret(91),
            "return_6m":     _ret(182),
            "return_1y":     _ret(365),
            "return_3y":     _ret(365*3),
            "return_5y":     _ret(365*5),
            "aum":           info.get("totalAssets", 0) or 0,
            "expense_ratio": round(info.get("annualReportExpenseRatio", 0) or 0, 4),
            "fund_manager":  info.get("fundFamily", ""),
            "benchmark":     info.get("category", ""),
        }
    except Exception as e:
        return {}

# ── PAGE ──────────────────────────────────────────────────────────────────
def render():
    if not st.session_state.get("user") or \
       st.session_state.user["role"] not in ("advisor", "owner"):
        navigate("login"); return

    back_button(fallback="market_upload", key="top")

    st.markdown('<div class="page-title">Auto Fetch MF & ETF Data</div>',
                unsafe_allow_html=True)
    st.markdown('<div class="page-sub">NAV · Returns · AUM · Holdings from AMFI, NSE, Yahoo Finance</div>',
                unsafe_allow_html=True)

    st.markdown("""
    <div style="background:#1E2535;border:1px solid #252D40;border-radius:8px;
        padding:.9rem 1.2rem;margin-bottom:1rem;font-size:.8rem;color:#C8D0E0;line-height:2">
        <b>Data sources:</b><br>
        🟢 <b>AMFI / mfapi.in</b> — Official NAV, scheme details, full historical NAV for all AMFI-registered MFs<br>
        🟢 <b>NSE API</b> — ETF iNAV, traded price, AUM<br>
        🟡 <b>Yahoo Finance</b> — Historical returns for ETFs (1m/3m/1y/3y/5y), expense ratio, fund family<br>
        Returns are <b>computed from historical NAV</b> data — not scraped, so always accurate.
    </div>
    """, unsafe_allow_html=True)

    tab_mf, tab_etf = st.tabs(["  🏦 Mutual Funds  ", "  💛 ETFs  "])

    # ══ MUTUAL FUNDS ══════════════════════════════════════════════════════
    with tab_mf:
        st.markdown("#### Mutual Fund Auto-Fetch")

        mode = st.radio("What to fetch",
                        ["Update NAV for existing MFs in DB",
                         "Fetch full details for specific scheme codes",
                         "Bulk import from AMFI scheme list"],
                        horizontal=False, key="mf_mode")

        # ── Mode 1: Update NAV for all existing MFs ────────────────────
        if mode == "Update NAV for existing MFs in DB":
            st.caption("Fetches latest NAV + computes 1m/1y/3y/5y returns from AMFI historical data.")
            st.caption("Only updates MFs already in your database. Use 'Bulk import' to add new ones.")

            include_returns = st.checkbox("Also compute historical returns (slower — ~0.5s per fund)", value=True)
            limit_n = st.number_input("Max funds to update (0 = all)", min_value=0, value=0, step=50)

            if st.button("🚀 Fetch NAVs from AMFI", use_container_width=True, key="do_mf_nav"):
                # Load existing MFs
                try:
                    existing = sb().table("mutual_funds")\
                                   .select("symbol,scheme_code,name")\
                                   .execute().data or []
                except Exception as e:
                    st.error(f"DB error: {e}"); return

                if not existing:
                    st.warning("No MFs in database. Use 'Bulk import' first."); return

                to_update = existing[:int(limit_n)] if limit_n > 0 else existing
                st.markdown(f"Updating **{len(to_update)}** funds…")

                prog   = st.progress(0.0)
                status = st.empty()
                ok = err = skipped = 0
                now = datetime.now().isoformat()

                for i, mf in enumerate(to_update):
                    code = mf.get("scheme_code","").strip()
                    if not code:
                        skipped += 1
                        continue

                    data, fetch_err = fetch_mf_nav_amfi(code)
                    if fetch_err or not data:
                        err += 1
                        time.sleep(0.1)
                        continue

                    navs    = data["navs"]
                    meta    = data["meta"]
                    latest  = navs[0] if navs else None
                    if not latest:
                        err += 1; continue

                    try:
                        cur_nav  = float(latest["nav"])
                        nav_date = latest["date"]
                    except Exception:
                        err += 1; continue

                    prev_nav = float(navs[1]["nav"]) if len(navs) > 1 else cur_nav
                    chg      = _pct_change(cur_nav, prev_nav)

                    upd = {
                        "nav":          cur_nav,
                        "prev_nav":     prev_nav,
                        "change_pct":   chg,
                        "nav_date":     nav_date,
                        "fund_house":   meta.get("fund_house", mf.get("fund_house","")),
                        "category":     meta.get("scheme_category", ""),
                        "sub_category": meta.get("scheme_type", ""),
                        "last_updated": now,
                    }

                    if include_returns:
                        returns = compute_returns_from_navs(navs)
                        upd.update({k: v for k, v in returns.items() if v is not None})

                    try:
                        sb().table("mutual_funds")\
                            .update(upd)\
                            .eq("scheme_code", code)\
                            .execute()
                        ok += 1
                    except Exception:
                        err += 1

                    frac = (i+1)/len(to_update)
                    prog.progress(frac, text=f"{i+1}/{len(to_update)}")
                    if (i+1) % 10 == 0:
                        status.markdown(
                            f'<span style="font-size:.8rem;color:#C8D0E0">'
                            f'✓ {ok} updated · {err} errors · {skipped} skipped</span>',
                            unsafe_allow_html=True)
                    time.sleep(0.05)

                prog.progress(1.0, text="Done ✓")
                clear_market_cache()
                st.success(f"✅ {ok} funds updated · {err} errors · {skipped} skipped (no scheme code)")

        # ── Mode 2: Specific scheme codes ─────────────────────────────
        elif mode == "Fetch full details for specific scheme codes":
            st.caption("Enter AMFI scheme codes (one per line). Find codes at mfapi.in or valueresearchonline.com")
            codes_input = st.text_area(
                "Scheme codes",
                placeholder="119598\n120503\n118989",
                height=120
            )
            include_holdings = st.checkbox("Fetch top holdings (requires yfinance)", value=False)

            if st.button("🔍 Fetch Details", use_container_width=True, key="do_mf_specific"):
                codes = [c.strip() for c in codes_input.strip().split("\n") if c.strip()]
                if not codes:
                    st.error("Enter at least one scheme code."); return

                prog = st.progress(0.0)
                inserted = updated = err = 0
                now = datetime.now().isoformat()

                for i, code in enumerate(codes):
                    data, fetch_err = fetch_mf_nav_amfi(code)
                    if fetch_err or not data:
                        st.warning(f"Scheme {code}: {fetch_err}")
                        err += 1; continue

                    navs   = data["navs"]
                    meta   = data["meta"]
                    latest = navs[0] if navs else None
                    if not latest: err += 1; continue

                    cur_nav  = float(latest["nav"])
                    prev_nav = float(navs[1]["nav"]) if len(navs) > 1 else cur_nav
                    returns  = compute_returns_from_navs(navs)

                    # Build scheme symbol from name
                    raw_name = meta.get("scheme_name", f"MF{code}")
                    symbol   = f"MF{code}"

                    row = {
                        "scheme_code":   code,
                        "symbol":        symbol,
                        "name":          raw_name,
                        "fund_house":    meta.get("fund_house", ""),
                        "category":      meta.get("scheme_category", ""),
                        "sub_category":  meta.get("scheme_type", ""),
                        "nav":           cur_nav,
                        "prev_nav":      prev_nav,
                        "change_pct":    _pct_change(cur_nav, prev_nav),
                        "nav_date":      latest["date"],
                        "last_updated":  now,
                    }
                    row.update({k: v for k, v in returns.items() if v is not None})

                    try:
                        existing = sb().table("mutual_funds")\
                                       .select("id")\
                                       .eq("scheme_code", code)\
                                       .execute().data
                        if existing:
                            sb().table("mutual_funds").update(row).eq("scheme_code", code).execute()
                            updated += 1
                        else:
                            sb().table("mutual_funds").insert(row).execute()
                            inserted += 1
                    except Exception as db_e:
                        st.warning(f"DB error for {code}: {db_e}")
                        err += 1

                    prog.progress((i+1)/len(codes), text=f"{i+1}/{len(codes)}")
                    time.sleep(0.1)

                prog.progress(1.0, text="Done ✓")
                clear_market_cache()
                st.success(f"✅ {inserted} added · {updated} updated · {err} errors")

        # ── Mode 3: Bulk import from AMFI ─────────────────────────────
        else:
            st.caption("Downloads the complete AMFI scheme list and imports all funds matching your filter.")
            st.warning("⚠️ This can import thousands of schemes. Filter carefully.", icon="⚠️")

            c1, c2 = st.columns(2)
            filter_house = c1.text_input("Filter by fund house (blank = all)",
                                          placeholder="e.g. SBI, HDFC, Mirae")
            filter_cat   = c2.text_input("Filter by category (blank = all)",
                                          placeholder="e.g. Equity, Debt, Hybrid")
            max_import   = st.number_input("Max schemes to import", min_value=1,
                                            max_value=5000, value=200, step=50)

            if st.button("📥 Fetch AMFI Scheme List", use_container_width=True, key="amfi_list"):
                with st.spinner("Fetching AMFI scheme list…"):
                    schemes, err = fetch_all_amfi_schemes()
                if err:
                    st.error(f"AMFI fetch failed: {err}"); return

                # Filter
                if filter_house.strip():
                    fh = filter_house.strip().lower()
                    schemes = [s for s in schemes
                               if fh in s.get("schemeName","").lower()]
                if filter_cat.strip():
                    fc = filter_cat.strip().lower()
                    schemes = [s for s in schemes
                               if fc in s.get("schemeName","").lower()]

                schemes = schemes[:max_import]
                st.markdown(f"**{len(schemes)} schemes** matched. Click Import to proceed.")

                # Preview
                if schemes[:5]:
                    preview = [{
                        "Scheme Code": s["schemeCode"],
                        "Name": s["schemeName"][:60],
                    } for s in schemes[:10]]
                    import pandas as pd
                    st.dataframe(pd.DataFrame(preview), use_container_width=True)

                st.session_state["_amfi_schemes"] = schemes

            if st.session_state.get("_amfi_schemes") and \
               st.button("⬆️ Import to Database", use_container_width=True, key="do_amfi_import"):
                schemes = st.session_state["_amfi_schemes"]
                prog    = st.progress(0.0)
                status  = st.empty()
                inserted = updated = err = 0
                now = datetime.now().isoformat()

                # Existing scheme codes
                try:
                    existing_codes = {
                        str(r["scheme_code"])
                        for r in sb().table("mutual_funds").select("scheme_code").execute().data or []
                    }
                except Exception:
                    existing_codes = set()

                for i, s in enumerate(schemes):
                    code     = str(s["schemeCode"])
                    raw_name = s.get("schemeName", f"MF{code}")
                    symbol   = f"MF{code}"

                    # Quick NAV fetch
                    data, ferr = fetch_mf_nav_amfi(code)
                    if ferr or not data:
                        err += 1
                        time.sleep(0.05)
                        continue

                    navs   = data["navs"]
                    meta   = data["meta"]
                    latest = navs[0] if navs else None
                    if not latest: err += 1; continue

                    cur_nav  = float(latest["nav"])
                    prev_nav = float(navs[1]["nav"]) if len(navs) > 1 else cur_nav
                    returns  = compute_returns_from_navs(navs)

                    row = {
                        "scheme_code":   code,
                        "symbol":        symbol,
                        "name":          raw_name,
                        "fund_house":    meta.get("fund_house", ""),
                        "category":      meta.get("scheme_category", ""),
                        "sub_category":  meta.get("scheme_type", ""),
                        "nav":           cur_nav,
                        "prev_nav":      prev_nav,
                        "change_pct":    _pct_change(cur_nav, prev_nav),
                        "nav_date":      latest["date"],
                        "last_updated":  now,
                    }
                    row.update({k: v for k, v in returns.items() if v is not None})

                    try:
                        if code in existing_codes:
                            sb().table("mutual_funds").update(row).eq("scheme_code", code).execute()
                            updated += 1
                        else:
                            sb().table("mutual_funds").insert(row).execute()
                            inserted += 1
                            existing_codes.add(code)
                    except Exception:
                        err += 1

                    frac = (i+1)/len(schemes)
                    prog.progress(frac, text=f"{i+1}/{len(schemes)}")
                    if (i+1) % 20 == 0:
                        status.markdown(
                            f'<span style="font-size:.8rem;color:#C8D0E0">'
                            f'✓ {inserted} added · {updated} updated · {err} errors</span>',
                            unsafe_allow_html=True)
                    time.sleep(0.08)

                prog.progress(1.0, text="Done ✓")
                clear_market_cache()
                st.session_state.pop("_amfi_schemes", None)
                st.success(f"✅ {inserted} new MFs added · {updated} updated · {err} errors")

    # ══ ETFs ══════════════════════════════════════════════════════════════
    with tab_etf:
        st.markdown("#### ETF Auto-Fetch")

        st.info("**Source:** NSE for prices/iNAV · Yahoo Finance for returns (1m/1y/3y/5y) and expense ratio.")

        etf_mode = st.radio("What to fetch",
                            ["Update prices for existing ETFs in DB",
                             "Fetch all ETFs from NSE (full list)"],
                            horizontal=False, key="etf_mode")
        include_yf = st.checkbox("Fetch returns from Yahoo Finance (slower)", value=True)

        if etf_mode == "Update prices for existing ETFs in DB":
            if st.button("🚀 Fetch ETF Prices from NSE", use_container_width=True, key="do_etf_nse"):
                with st.spinner("Connecting to NSE…"):
                    nse_etfs, err = fetch_etf_data_nse()
                if err:
                    st.warning(f"NSE fetch failed: {err}")
                    nse_etfs = []

                if not nse_etfs:
                    st.error("No ETF data from NSE. Try manual upload instead."); return

                # Build lookup: symbol → nse row
                nse_map = {e.get("symbol","").upper(): e for e in nse_etfs if e.get("symbol")}

                # Load existing ETFs from DB
                try:
                    existing = sb().table("assets")\
                                   .select("symbol,name")\
                                   .eq("asset_class","ETF")\
                                   .execute().data or []
                except Exception as e:
                    st.error(f"DB error: {e}"); return

                if not existing:
                    st.warning("No ETFs in database. Use 'Fetch all ETFs from NSE' first."); return

                prog   = st.progress(0.0)
                now    = datetime.now().isoformat()
                today  = str(date.today())
                ok = err = 0

                for i, etf in enumerate(existing):
                    sym    = etf["symbol"]
                    nse_r  = nse_map.get(sym)
                    if not nse_r:
                        # Try without suffix
                        nse_r = nse_map.get(sym.replace("BEES","BEES"))

                    close  = 0.0
                    inav   = 0.0
                    if nse_r:
                        try:
                            close = float(str(nse_r.get("lastPrice","0")).replace(",",""))
                            inav  = float(str(nse_r.get("iNavValue","0")).replace(",",""))
                        except Exception:
                            pass

                    if close <= 0 and not include_yf:
                        err += 1; continue

                    price_row = {
                        "symbol":       sym,
                        "price_date":   today,
                        "close":        close or inav,
                        "open":         close or inav,
                        "high":         close or inav,
                        "low":          close or inav,
                        "prev_close":   close or inav,
                        "change_pct":   0.0,
                        "volume":       0,
                        "last_updated": now,
                    }

                    try:
                        if nse_r:
                            try:
                                prev = float(str(nse_r.get("previousClose","0")).replace(",",""))
                                if prev > 0:
                                    price_row["prev_close"]  = prev
                                    price_row["change_pct"]  = _pct_change(close, prev)
                                chg_pct = float(str(nse_r.get("pChange","0")).replace(",",""))
                                price_row["change_pct"] = chg_pct
                            except Exception: pass

                        sb().table("prices")\
                            .upsert(price_row, on_conflict="symbol,price_date")\
                            .execute()
                        ok += 1
                    except Exception:
                        err += 1

                    # Yahoo Finance returns for ETF
                    if include_yf and (i % 5 == 0):  # rate-limit: every 5th ETF
                        yf_data = fetch_yf_returns(f"{sym}.NS")
                        if yf_data:
                            asset_upd = {}
                            for fld in ("return_1m","return_3m","return_6m",
                                        "return_1y","return_3y","return_5y"):
                                if yf_data.get(fld) is not None:
                                    asset_upd[fld] = yf_data[fld]
                            if yf_data.get("expense_ratio"):
                                asset_upd["expense_ratio"] = yf_data["expense_ratio"]
                            if asset_upd:
                                try:
                                    sb().table("assets").update(asset_upd).eq("symbol", sym).execute()
                                except Exception: pass

                    prog.progress((i+1)/len(existing), text=f"{i+1}/{len(existing)} ETFs")
                    time.sleep(0.05)

                prog.progress(1.0, text="Done ✓")
                clear_market_cache()
                st.success(f"✅ {ok} ETF prices updated · {err} skipped")

        else:  # Fetch all ETFs from NSE
            st.caption("Fetches the complete NSE ETF list and adds any new ones to your database.")
            if st.button("📥 Fetch All ETFs from NSE", use_container_width=True, key="do_etf_all"):
                with st.spinner("Fetching NSE ETF list…"):
                    nse_etfs, err = fetch_etf_data_nse()

                if err or not nse_etfs:
                    st.error(f"NSE ETF fetch failed: {err or 'No data'}"); return

                st.markdown(f"**{len(nse_etfs)} ETFs** found on NSE.")

                # Load existing
                try:
                    ex_syms = {r["symbol"] for r in
                               sb().table("assets").select("symbol")\
                               .eq("asset_class","ETF").execute().data or []}
                except Exception:
                    ex_syms = set()

                prog     = st.progress(0.0)
                now      = datetime.now().isoformat()
                today    = str(date.today())
                inserted = updated = err = 0

                # ETF sub-category classifier
                def _etf_sub(name):
                    n = name.upper()
                    if any(k in n for k in ("GOLD","SILVER","METAL","COMMODITY")): return "Commodity ETF"
                    if any(k in n for k in ("LIQUID","MONEY","OVERNIGHT")):         return "Liquid ETF"
                    if any(k in n for k in ("BANK","FIN","INFRA","IT","PHARMA","AUTO","SECTOR")): return "Sectoral ETF"
                    return "Index ETF"

                for i, e in enumerate(nse_etfs):
                    sym  = str(e.get("symbol","")).upper().strip()
                    name = e.get("companyName", sym)
                    if not sym: continue

                    try:
                        close = float(str(e.get("lastPrice","0")).replace(",",""))
                        prev  = float(str(e.get("previousClose","0")).replace(",",""))
                        chg   = float(str(e.get("pChange","0")).replace(",",""))
                        inav  = float(str(e.get("iNavValue","0")).replace(",",""))
                    except Exception:
                        close = prev = chg = inav = 0.0

                    # Upsert asset
                    asset_row = {
                        "symbol":      sym,
                        "name":        name,
                        "asset_class": "ETF",
                        "sub_class":   _etf_sub(name),
                        "exchange":    "NSE",
                        "is_active":   True,
                        "unit_type":   "units",
                    }
                    try:
                        sb().table("assets").upsert(asset_row, on_conflict="symbol").execute()
                        if sym in ex_syms: updated += 1
                        else: inserted += 1; ex_syms.add(sym)
                    except Exception: err += 1; continue

                    # Upsert price
                    if close > 0:
                        price_row = {
                            "symbol":       sym,
                            "price_date":   today,
                            "close":        close,
                            "open":         close,
                            "high":         close,
                            "low":          close,
                            "prev_close":   prev or close,
                            "change_pct":   chg,
                            "volume":       0,
                            "last_updated": now,
                        }
                        try:
                            sb().table("prices")\
                                .upsert(price_row, on_conflict="symbol,price_date")\
                                .execute()
                        except Exception: pass

                    prog.progress((i+1)/len(nse_etfs), text=f"{i+1}/{len(nse_etfs)}")
                    time.sleep(0.02)

                prog.progress(1.0, text="Done ✓")
                clear_market_cache()
                st.success(f"✅ {inserted} new ETFs added · {updated} updated · {err} errors")

    back_button(fallback="market_upload", label="← Back", key="bot")
