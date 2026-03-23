import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate
from utils.db import sb, clear_market_cache
from datetime import datetime, date
import time, requests

# ── NSE SESSION (required to avoid 403/404) ───────────────────────────────
def _nse_session():
    """NSE blocks requests without a valid cookie from the homepage."""
    sess = requests.Session()
    sess.headers.update({
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
        "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
    })
    try:
        sess.get("https://www.nseindia.com/", timeout=10)
        time.sleep(1)
    except Exception:
        pass
    return sess

# ── EQUITY MASTER LIST ────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def _fetch_nse_equity_list():
    sess = _nse_session()
    try:
        r = sess.get(
            "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
            headers={"Referer":"https://www.nseindia.com/"}, timeout=20
        )
        r.raise_for_status()
        result = {}
        for line in r.text.strip().split("\n")[1:]:
            parts = [p.strip().strip('"') for p in line.split(",")]
            if len(parts) >= 3 and parts[0]:
                result[parts[0].upper()] = {"name": parts[1], "isin": parts[2]}
        return result, None
    except Exception as e:
        return {}, str(e)

# ── SEBI CAP CLASSIFICATION — multiple fallback sources ──────────────────
@st.cache_data(ttl=3600)
def _fetch_sebi_classification():
    """
    Try three sources in order:
    1. NSE MCAP.csv (the correct path changes periodically)
    2. NSE index constituent files — Nifty100 / Nifty200 / Nifty500
    3. Hardcoded Nifty 50 + known large-caps as absolute fallback
    """
    sess = _nse_session()
    sym_to_cap = {}

    # ── Source 1: NSE MCAP CSV (try multiple known paths) ─────────────────
    mcap_urls = [
        "https://nsearchives.nseindia.com/content/equities/MCAP.csv",
        "https://nsearchives.nseindia.com/content/equities/mcap.csv",
        "https://www.nseindia.com/content/equities/MCAP.csv",
    ]
    for url in mcap_urls:
        try:
            r = sess.get(url, headers={"Referer":"https://www.nseindia.com/"}, timeout=15)
            if r.status_code == 200 and len(r.content) > 1000:
                lines      = r.text.strip().split("\n")
                seen_syms  = set()
                rank       = 0
                local_caps = {}
                for line in lines[1:]:
                    parts = [p.strip().strip('"') for p in line.split(",")]
                    sym   = parts[0].upper() if parts else ""
                    if not sym or sym in seen_syms:
                        continue        # skip blank and duplicate series rows
                    seen_syms.add(sym)
                    rank += 1           # rank by unique symbol, not raw CSV row
                    local_caps[sym] = ("Large Cap" if rank <= 100
                                       else "Mid Cap" if rank <= 250
                                       else "Small Cap")
                # Sanity: expect at least 500 classified stocks
                if len(local_caps) >= 500:
                    return local_caps, f"MCAP.csv — {len(local_caps)} unique symbols (Large:100, Mid:150, Small:{len(local_caps)-250})"
                # Too few rows — file was malformed or too small, try next URL
        except Exception:
            continue

    # ── Source 2: NSE Index Constituent APIs ──────────────────────────────
    # SEBI rules: top 100 by market cap = Large Cap, 101-250 = Mid Cap, 251+ = Small Cap.
    # We fetch Nifty 100 (Large), Nifty Next 50 (101-150), Nifty Midcap 150 (101-250).
    # Everything NOT in these indices = Small Cap by elimination.
    index_apis = [
        ("https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20100",        "Large Cap"),
        ("https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20NEXT%2050",  "Mid Cap"),
        ("https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20MIDCAP%20150","Mid Cap"),
    ]
    api_success = 0
    for api_url, cap_label in index_apis:
        try:
            r = sess.get(api_url, headers={"Referer":"https://www.nseindia.com/"}, timeout=10)
            if r.status_code == 200:
                data = r.json()
                for item in data.get("data", []):
                    sym = item.get("symbol","").upper()
                    if not sym: continue
                    existing = sym_to_cap.get(sym)
                    # Priority: Large > Mid > Small — never downgrade
                    if existing != "Large Cap":
                        sym_to_cap[sym] = cap_label
                api_success += 1
        except Exception:
            continue

    if api_success > 0 and sym_to_cap:
        # All stocks in DB that are NOT in Large/Mid → Small Cap
        # This is done during enrichment apply step (see below)
        counts = {c: sum(1 for v in sym_to_cap.values() if v==c)
                  for c in ("Large Cap","Mid Cap")}
        total_classified = sum(counts.values())
        return (sym_to_cap,
                f"NSE Index APIs — Large:≤100, Mid:101-250, all others→Small Cap "
                f"({api_success}/3 APIs, {total_classified} explicitly classified)")

    # ── Source 3: Hardcoded fallback — Nifty 50 + known categorisation ────
    LARGE_CAP = {
        "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR","KOTAKBANK",
        "SBIN","BHARTIARTL","BAJFINANCE","ASIANPAINT","MARUTI","TITAN","AXISBANK",
        "WIPRO","ULTRACEMCO","NESTLEIND","HCLTECH","SUNPHARMA","POWERGRID","NTPC",
        "ONGC","COALINDIA","TATAMOTORS","TATASTEEL","JSWSTEEL","ADANIENT",
        "ADANIPORTS","LT","M&M","BAJAJFINSV","TECHM","DRREDDY","CIPLA",
        "EICHERMOT","HEROMOTOCO","APOLLOHOSP","DIVISLAB","BRITANNIA","TATACONSUM",
        "PIDILITIND","SIEMENS","HAVELLS","INDUSINDBK","BANKBARODA","GRASIM",
        "HINDZINC","VEDL","BPCL","IOC","HDFCLIFE","SBILIFE","ICICIPRULI",
        "HDFC","DABUR","BERGEPAINT","MARICO","GODREJCP","COLPAL","MCDOWELL-N",
        "UBL","ITC","HINDPETRO","BPCL","GAIL","TORNTPHARM","LUPIN","BIOCON",
    }
    MID_CAP = {
        "MPHASIS","PERSISTENT","COFORGE","LTIM","OFSS","KPITTECH","TATAELXSI",
        "CROMPTON","VOLTAS","WHIRLPOOL","BLUESTARCO","SYMPHONY","CEAT","MRF",
        "APOLLOTYRE","BALKRISIND","ESCORTS","TVSMOTOR","BAJAJ-AUTO","ASHOKLEY",
        "MOTHERSON","SUNDRMFAST","EXIDEIND","AMARAJABAT","AMNSIND","SAIL",
        "NMDC","NATIONALUM","HINDALCO","WELCORP","ISPATIND",
    }
    for s in LARGE_CAP: sym_to_cap[s] = "Large Cap"
    for s in MID_CAP:   sym_to_cap[s] = "Mid Cap"
    return sym_to_cap, f"Hardcoded fallback ({len(sym_to_cap)} known stocks)"

# ── SECTOR MAPPING ────────────────────────────────────────────────────────
MANUAL_SECTORS = {
    "RELIANCE":"Energy","TCS":"Technology","HDFCBANK":"Financial Services",
    "INFY":"Technology","HINDUNILVR":"Consumer Goods","ICICIBANK":"Financial Services",
    "KOTAKBANK":"Financial Services","SBIN":"Financial Services","BAJFINANCE":"Financial Services",
    "BHARTIARTL":"Telecom","ASIANPAINT":"Consumer Goods","MARUTI":"Automobile",
    "TITAN":"Consumer Goods","AXISBANK":"Financial Services","WIPRO":"Technology",
    "ULTRACEMCO":"Materials","NESTLEIND":"Consumer Goods","HCLTECH":"Technology",
    "SUNPHARMA":"Healthcare","POWERGRID":"Utilities","NTPC":"Utilities",
    "ONGC":"Energy","COALINDIA":"Energy","TATAMOTORS":"Automobile",
    "TATASTEEL":"Materials","JSWSTEEL":"Materials","ADANIENT":"Conglomerate",
    "ADANIPORTS":"Infrastructure","LT":"Capital Goods","M&M":"Automobile",
    "BAJAJFINSV":"Financial Services","TECHM":"Technology","DRREDDY":"Healthcare",
    "CIPLA":"Healthcare","EICHERMOT":"Automobile","HEROMOTOCO":"Automobile",
    "APOLLOHOSP":"Healthcare","DIVISLAB":"Healthcare","BRITANNIA":"Consumer Goods",
    "TATACONSUM":"Consumer Goods","PIDILITIND":"Materials","SIEMENS":"Capital Goods",
    "HAVELLS":"Capital Goods","INDUSINDBK":"Financial Services","BANKBARODA":"Financial Services",
    "ITC":"Consumer Goods","GAIL":"Energy","BPCL":"Energy","IOC":"Energy",
    "HINDPETRO":"Energy","HDFCLIFE":"Financial Services","SBILIFE":"Financial Services",
    "ICICIPRULI":"Financial Services","DABUR":"Consumer Goods","MARICO":"Consumer Goods",
    "GODREJCP":"Consumer Goods","COLPAL":"Consumer Goods","MPHASIS":"Technology",
    "PERSISTENT":"Technology","COFORGE":"Technology","LTIM":"Technology",
    "TATAELXSI":"Technology","KPITTECH":"Technology","OFSS":"Technology",
    "MRF":"Automobile","BALKRISIND":"Automobile","APOLLOTYRE":"Automobile",
    "TVSMOTOR":"Automobile","ASHOKLEY":"Automobile","ESCORTS":"Automobile",
    "NMDC":"Materials","HINDALCO":"Materials","VEDL":"Materials","SAIL":"Materials",
    "CEAT":"Automobile","CROMPTON":"Consumer Goods","VOLTAS":"Capital Goods",
    "WHIRLPOOL":"Consumer Goods","LUPIN":"Healthcare","BIOCON":"Healthcare",
    "TORNTPHARM":"Healthcare","GRASIM":"Materials","HINDZINC":"Materials",
    "EXIDEIND":"Capital Goods","PNB":"Financial Services","CANBK":"Financial Services",
}

@st.cache_data(ttl=86400)
def _fetch_sector_yf(symbol):
    try:
        import yfinance as yf
        info = yf.Ticker(f"{symbol}.NS").info
        return info.get("sector") or info.get("industryDisp") or ""
    except Exception:
        return ""

# ── MAIN PAGE ─────────────────────────────────────────────────────────────
def render():
    if not st.session_state.get("user") or st.session_state.user["role"] != "advisor":
        navigate("login"); return

    st.markdown('<div class="page-title">Stock Enrichment</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Update company names · SEBI cap classification · Sectors</div>',
                unsafe_allow_html=True)

    # SEBI schedule reminder
    today = date.today()
    m, d  = today.month, today.day
    if (m == 1 and 1 <= d <= 7) or (m == 7 and 1 <= d <= 7):
        st.warning("⚠️ SEBI reclassification window — run now to update Large/Mid/Small Cap.")
    else:
        next_d = date(today.year, 7, 2) if today.month < 7 else date(today.year+1, 1, 2)
        st.info(f"Next SEBI reclassification: **{next_d.strftime('%d %b %Y')}**  ·  Re-run this page then.")

    st.markdown("""
    <div style="background:#1E2535;border:1px solid #252D40;border-radius:8px;
        padding:.9rem 1.2rem;margin-bottom:1rem;font-size:.8rem;color:#C8D0E0;line-height:2">
        <b>Sources and priority order (each stock uses only one source):</b><br>
        1. NSE EQUITY_L.csv → company names + ISINs (authoritative)<br>
        2. NSE MCAP.csv or Index API → SEBI Large/Mid/Small Cap classification<br>
        3. Built-in map (~70 major stocks) → sectors, instant, highest priority<br>
        4. Yahoo Finance → sectors for all remaining stocks (optional, slow ~20 min)<br>
        <span style="color:#F5B731">Sectors are never overwritten once set.
        Run YF only once — re-running just fills any remaining gaps.</span>
    </div>
    """, unsafe_allow_html=True)

    c1, c2  = st.columns(2)
    do_names    = c1.checkbox("Update company names",          value=True)
    do_caps     = c1.checkbox("Update cap classification",     value=True)
    do_sectors  = c2.checkbox("Apply known sector mapping",    value=True)
    do_yf       = c2.checkbox("Yahoo Finance sectors (slow)", value=False)
    limit       = st.number_input("Max stocks to process (0 = all)", min_value=0, value=0, step=100)

    # ── MANUAL CAP UPLOAD ─────────────────────────────────────────────────
    with st.expander("📂 Manual Cap Classification Upload (if automatic fetch fails)"):
        st.markdown("""
        <div style="font-size:.79rem;color:#C8D0E0;line-height:1.9">
            Upload a CSV with two columns: <code>symbol</code> and <code>cap</code>
            (values: <code>Large Cap</code>, <code>Mid Cap</code>, <code>Small Cap</code>).<br>
            Download MCAP.csv from
            <a href="https://www.nseindia.com/market-data/securities-available-for-trading"
               target="_blank" style="color:#4F7EFF">NSE Securities page</a>
            or use any ranking list with symbol + rank columns.
        </div>
        """, unsafe_allow_html=True)
        cap_file = st.file_uploader("Upload cap CSV", type=["csv"], key="cap_upload")
        if cap_file:
            try:
                import pandas as pd
                cap_df = pd.read_csv(cap_file)
                cap_df.columns = [c.strip().lower() for c in cap_df.columns]

                # Accept symbol+cap OR symbol+rank columns
                sym_col = next((c for c in cap_df.columns if c in ("symbol","ticker","sym")), None)
                cap_col = next((c for c in cap_df.columns if c in ("cap","category","sub_class","classification")), None)
                rank_col= next((c for c in cap_df.columns if c in ("rank","sr","serial","mcap_rank","no")), None)

                if sym_col and (cap_col or rank_col):
                    manual_caps = {}
                    seen = set()
                    for i, row in cap_df.iterrows():
                        sym = str(row[sym_col]).strip().upper()
                        if not sym or sym in seen: continue
                        seen.add(sym)
                        if cap_col:
                            val = str(row[cap_col]).strip()
                            if val in ("Large Cap","Mid Cap","Small Cap"):
                                manual_caps[sym] = val
                        elif rank_col:
                            try:
                                rank = int(float(str(row[rank_col])))
                                manual_caps[sym] = ("Large Cap" if rank<=100
                                                    else "Mid Cap" if rank<=250
                                                    else "Small Cap")
                            except ValueError:
                                pass

                    if manual_caps:
                        counts = {c: sum(1 for v in manual_caps.values() if v==c)
                                  for c in ("Large Cap","Mid Cap","Small Cap")}
                        st.success(f"✅ {len(manual_caps)} stocks parsed — "
                                   f"Large: {counts['Large Cap']}, "
                                   f"Mid: {counts['Mid Cap']}, "
                                   f"Small: {counts['Small Cap']}")
                        if st.button("Apply this cap data to database", use_container_width=True,
                                     key="apply_manual_caps"):
                            ok = err = 0
                            prog_m = st.progress(0.0)
                            items  = list(manual_caps.items())
                            for i, (sym, cap) in enumerate(items):
                                try:
                                    sb().table("assets").update({"sub_class":cap}).eq("symbol",sym).execute()
                                    ok += 1
                                except Exception:
                                    err += 1
                                if (i+1) % 20 == 0:
                                    prog_m.progress((i+1)/len(items))
                            prog_m.progress(1.0)
                            clear_market_cache()
                            st.success(f"Updated {ok} stocks. {f'{err} errors.' if err else ''}")
                    else:
                        st.warning("No valid cap values found. Ensure 'cap' column has 'Large Cap'/'Mid Cap'/'Small Cap'.")
                else:
                    st.error("Need columns: 'symbol' + ('cap' or 'rank'). "
                             f"Found: {list(cap_df.columns)}")
            except Exception as e:
                st.error(f"File error: {e}")

    if not st.button("🚀 Run Enrichment", use_container_width=True):
        return

    status = st.empty()
    prog   = st.progress(0.0)
    log    = st.empty()

    # ── FETCH REFERENCE DATA ──────────────────────────────────────────────
    status.markdown("**Step 1/3 — Fetching NSE equity master list…**")
    nse_list, nse_err = _fetch_nse_equity_list()
    if nse_err:
        st.warning(f"NSE name list: {nse_err}")
    else:
        st.markdown(f"<span style='color:#2ECC7A;font-size:.8rem'>✓ NSE list: {len(nse_list):,} symbols</span>", unsafe_allow_html=True)

    status.markdown("**Step 2/3 — Fetching SEBI classification…**")
    sym_to_cap, cap_source = _fetch_sebi_classification()
    cap_color = "#2ECC7A" if "MCAP" in cap_source or "API" in cap_source else "#F5B731"
    st.markdown(f"<span style='color:{cap_color};font-size:.8rem'>✓ Cap data: {cap_source}</span>", unsafe_allow_html=True)

    # Build ISIN→cap bridge using NSE equity list
    isin_to_cap = {}
    for sym, data in nse_list.items():
        if sym in sym_to_cap and data.get("isin"):
            isin_to_cap[data["isin"]] = sym_to_cap[sym]

    status.markdown("**Step 3/3 — Loading assets from database…**")
    all_assets = []
    page = 0
    while True:
        batch = (sb().table("assets").select("symbol,name,isin,sub_class,sector,asset_class")
                 .eq("asset_class","Equity")
                 .range(page*1000, (page+1)*1000-1).execute().data or [])
        all_assets.extend(batch)
        if len(batch) < 1000: break
        page += 1

    if not all_assets:
        st.error("No equity assets in database. Upload bhavcopy first."); return

    to_process = all_assets[:int(limit)] if limit > 0 else all_assets
    st.markdown(f"<span style='font-size:.82rem;color:#8892AA'>Processing <b>{len(to_process):,}</b> equity assets</span>", unsafe_allow_html=True)

    # ── PROCESS ───────────────────────────────────────────────────────────
    updated_names = updated_caps = updated_sectors = yf_count = errors = 0
    batch_upd = []

    for i, asset in enumerate(to_process):
        sym = asset["symbol"]
        upd = {}

        if do_names and sym in nse_list:
            new_name = nse_list[sym]["name"]
            if new_name and new_name != sym and (not asset["name"] or asset["name"] == sym):
                upd["name"] = new_name
                updated_names += 1
            if not asset.get("isin") and nse_list[sym].get("isin"):
                upd["isin"] = nse_list[sym]["isin"]

        if do_caps:
            new_cap = sym_to_cap.get(sym)
            # Try ISIN lookup as fallback
            if not new_cap:
                isin    = asset.get("isin") or nse_list.get(sym, {}).get("isin","")
                new_cap = isin_to_cap.get(isin)
            # If still not found AND we had API success → this stock is Small Cap by elimination
            if not new_cap and sym_to_cap:
                new_cap = "Small Cap"
            if new_cap and asset.get("sub_class","") in ("","Unclassified","Unknown",None):
                upd["sub_class"] = new_cap
                updated_caps += 1

        if do_sectors and sym in MANUAL_SECTORS:
            # Manual mapping takes absolute priority — only apply if no sector yet
            if not asset.get("sector"):
                upd["sector"] = MANUAL_SECTORS[sym]
                updated_sectors += 1

        if do_yf and not asset.get("sector") and sym not in MANUAL_SECTORS:
            # Yahoo Finance fills gaps ONLY — never touches stocks already in manual map
            # and never overwrites an existing sector value from a previous run
            sec = _fetch_sector_yf(sym)
            if sec:
                upd["sector"] = sec
                updated_sectors += 1
                yf_count += 1
            time.sleep(0.25)

        if upd:
            upd["last_updated"] = datetime.now().isoformat()
            batch_upd.append((sym, upd))

        if len(batch_upd) >= 100:
            ok, err = _flush(batch_upd); errors += err; batch_upd = []

        if (i+1) % 50 == 0 or i == len(to_process)-1:
            frac = (i+1)/len(to_process)
            prog.progress(frac, text=f"{i+1}/{len(to_process)}")
            log.markdown(
                f'<div style="background:#0F1117;border:1px solid #252D40;border-radius:8px;'
                f'padding:.7rem 1rem;font-size:.79rem;color:#C8D0E0;line-height:2;font-family:monospace">'
                f'Names updated:    {updated_names}<br>'
                f'Cap classified:   {updated_caps}<br>'
                f'Sectors mapped:   {updated_sectors}'
                f'{"<br>YF sectors: " + str(yf_count) if do_yf else ""}'
                f'{"<br><span style=color:#FF5A5A>Errors: " + str(errors) + "</span>" if errors else ""}'
                f'</div>',
                unsafe_allow_html=True)

    if batch_upd:
        ok, err = _flush(batch_upd); errors += err

    clear_market_cache()
    prog.progress(1.0, text="Complete ✓")
    status.empty()

    result_color = "#2ECC7A" if errors == 0 else "#F5B731"
    st.markdown(f"""
    <div style="background:#1E2535;border:2px solid {result_color};border-radius:10px;
        padding:1rem 1.3rem;margin:.8rem 0">
        <div style="font-size:.7rem;color:#8892AA;text-transform:uppercase;letter-spacing:.08em;margin-bottom:.5rem">
            Enrichment Complete
        </div>
        <div style="font-size:.85rem;color:#C8D0E0;line-height:2">
            ✓ Company names updated: <b>{updated_names}</b><br>
            ✓ Cap classified: <b>{updated_caps}</b><br>
            ✓ Sectors assigned: <b>{updated_sectors}</b>
            {"<br>● Yahoo Finance sectors: <b>" + str(yf_count) + "</b>" if do_yf else ""}
            {"<br><span style=color:#FF5A5A>⚠ Errors: " + str(errors) + "</span>" if errors else ""}
        </div>
    </div>
    """, unsafe_allow_html=True)

    if st.button("← Back to Profile"):
        navigate("profile")

def _flush(batch):
    ok = err = 0
    for sym, upd in batch:
        try:
            sb().table("assets").update(upd).eq("symbol", sym).execute()
            ok += 1
        except Exception:
            err += 1
    return ok, err
