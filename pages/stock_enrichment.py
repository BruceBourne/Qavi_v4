import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate
from utils.db import sb, clear_market_cache
from datetime import datetime, date
import time
import requests

# ── NSE DATA FETCH ────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def _fetch_nse_equity_list():
    """NSE equity master CSV — symbol, company name, ISIN."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,*/*",
        "Referer": "https://www.nseindia.com/",
    }
    try:
        r = requests.get(
            "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
            headers=headers, timeout=20
        )
        r.raise_for_status()
        result = {}
        lines  = r.text.strip().split("\n")
        for line in lines[1:]:
            parts = [p.strip().strip('"') for p in line.split(",")]
            if len(parts) >= 3:
                sym = parts[0].upper()
                if sym:
                    result[sym] = {"name": parts[1], "isin": parts[2] if len(parts) > 2 else ""}
        return result, None
    except Exception as e:
        return {}, str(e)

@st.cache_data(ttl=3600)
def _fetch_sebi_classification():
    """
    SEBI cap classification via NSE market cap CSV.
    Top 100 = Large Cap, 101-250 = Mid Cap, 251+ = Small Cap.
    """
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nseindia.com/"}
    isin_to_cap = {}
    sym_to_cap  = {}
    try:
        r = requests.get(
            "https://nsearchives.nseindia.com/content/equities/MCAP.csv",
            headers=headers, timeout=20
        )
        r.raise_for_status()
        lines = r.text.strip().split("\n")
        for i, line in enumerate(lines[1:], 1):
            parts = [p.strip().strip('"') for p in line.split(",")]
            if len(parts) >= 2:
                sym  = parts[0].upper()
                isin = parts[1] if len(parts) > 1 else ""
                cap  = "Large Cap" if i <= 100 else "Mid Cap" if i <= 250 else "Small Cap"
                if sym:  sym_to_cap[sym]   = cap
                if isin: isin_to_cap[isin] = cap
        return sym_to_cap, isin_to_cap, None
    except Exception as e:
        return {}, {}, str(e)

@st.cache_data(ttl=86400)
def _fetch_sector_yf(symbol):
    """Fetch sector for one symbol from Yahoo Finance (.NS suffix for NSE)."""
    try:
        import yfinance as yf
        info = yf.Ticker(f"{symbol}.NS").info
        return (info.get("sector") or info.get("industryDisp") or "")
    except Exception:
        return ""

# Fallback hardcoded sectors for top stocks
MANUAL_SECTORS = {
    "RELIANCE":"Energy","TCS":"Technology","HDFCBANK":"Financial Services",
    "INFY":"Technology","HINDUNILVR":"Consumer Goods","ICICIBANK":"Financial Services",
    "KOTAKBANK":"Financial Services","SBIN":"Financial Services","BAJFINANCE":"Financial Services",
    "BHARTIARTL":"Telecom","ASIANPAINT":"Consumer Goods","MARUTI":"Automobile",
    "TITAN":"Consumer Goods","AXISBANK":"Financial Services","WIPRO":"Technology",
    "ULTRACEMCO":"Materials","NESTLEIND":"Consumer Goods","HCLTECH":"Technology",
    "SUNPHARMA":"Healthcare","POWERGRID":"Utilities","NTPC":"Utilities",
    "ONGC":"Energy","COALINDIA":"Energy","TATAMOTORS":"Automobile","TATASTEEL":"Materials",
    "JSWSTEEL":"Materials","ADANIENT":"Conglomerate","ADANIPORTS":"Infrastructure",
    "LT":"Capital Goods","M&M":"Automobile","BAJAJFINSV":"Financial Services",
    "TECHM":"Technology","DRREDDY":"Healthcare","CIPLA":"Healthcare",
    "EICHERMOT":"Automobile","HEROMOTOCO":"Automobile","APOLLOHOSP":"Healthcare",
    "DIVISLAB":"Healthcare","BRITANNIA":"Consumer Goods","TATACONSUM":"Consumer Goods",
    "PIDILITIND":"Materials","SIEMENS":"Capital Goods","HAVELLS":"Capital Goods",
    "INDUSINDBK":"Financial Services","BANKBARODA":"Financial Services",
    "PNB":"Financial Services","CANBK":"Financial Services",
}

# ── PAGE ──────────────────────────────────────────────────────────────────

def render():
    if not st.session_state.get("user") or st.session_state.user["role"] != "advisor":
        navigate("login"); return

    st.markdown('<div class="page-title">Stock Enrichment</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Populate company names, SEBI cap classification, and sectors</div>', unsafe_allow_html=True)

    # SEBI schedule reminder
    today = date.today()
    m, d  = today.month, today.day
    if (m == 1 and 1 <= d <= 7) or (m == 7 and 1 <= d <= 7):
        st.warning("⚠️ SEBI reclassification window — run this now to update Large/Mid/Small Cap classifications.")
    else:
        next_d = date(today.year, 7, 2) if today.month < 7 else date(today.year+1, 1, 2)
        st.info(f"Next SEBI reclassification: **{next_d.strftime('%d %b %Y')}** · Re-run this page then.")

    st.markdown("""
    <div style="background:#1E2535;border:1px solid #252D40;border-radius:8px;
        padding:.9rem 1.2rem;margin-bottom:1rem;font-size:.8rem;color:#C8D0E0;line-height:2">
        <b>What this does:</b><br>
        1. Fetches NSE equity master list → updates company names where name = ticker symbol<br>
        2. Fetches SEBI market cap ranking → assigns Large / Mid / Small Cap<br>
        3. Applies sector mapping for known stocks<br>
        4. Optionally fetches sectors from Yahoo Finance (slow, ~2500 API calls)
    </div>
    """, unsafe_allow_html=True)

    # Options
    c1, c2 = st.columns(2)
    do_names   = c1.checkbox("Update company names",         value=True)
    do_caps    = c1.checkbox("Update cap classification",    value=True)
    do_sectors = c2.checkbox("Apply known sector mapping",   value=True)
    do_yf      = c2.checkbox("Fetch sectors from Yahoo Finance (slow ~20 min)", value=False)

    limit = st.number_input("Max stocks to process (0 = all)", min_value=0, value=0, step=100)

    if not st.button("🚀 Run Enrichment", use_container_width=True):
        return

    # ── FETCH REFERENCE DATA ──────────────────────────────────────────────
    status = st.empty()
    prog   = st.progress(0.0)

    status.markdown("**Fetching NSE equity master list…**")
    nse_list, nse_err = _fetch_nse_equity_list()
    if nse_err:
        st.warning(f"NSE list fetch failed: {nse_err} — names may not update.")

    status.markdown("**Fetching SEBI market cap ranking…**")
    sym_to_cap, isin_to_cap, sebi_err = _fetch_sebi_classification()
    if sebi_err:
        st.warning(f"SEBI classification fetch failed: {sebi_err} — cap classification skipped.")

    # Build ISIN → cap using NSE list
    for sym, data in nse_list.items():
        isin = data.get("isin","")
        if isin and isin in isin_to_cap and sym not in sym_to_cap:
            sym_to_cap[sym] = isin_to_cap[isin]

    # ── LOAD ASSETS FROM DB ───────────────────────────────────────────────
    status.markdown("**Loading assets from database…**")
    all_assets = []
    page = 0
    while True:
        batch = sb().table("assets").select("symbol,name,isin,sub_class,sector,asset_class")\
                    .eq("asset_class","Equity")\
                    .range(page*1000, (page+1)*1000-1).execute().data or []
        all_assets.extend(batch)
        if len(batch) < 1000: break
        page += 1

    if not all_assets:
        st.error("No equity assets found. Upload bhavcopy data first."); return

    total = int(limit) if limit > 0 else len(all_assets)
    assets_to_process = all_assets[:total]
    st.markdown(f"Processing **{len(assets_to_process):,}** equity assets…")

    # ── PROCESS IN BATCHES ────────────────────────────────────────────────
    updated_names = 0
    updated_caps  = 0
    updated_sectors = 0
    yf_fetched    = 0
    errors        = 0
    batch_updates = []

    log_container = st.container()
    log_lines     = []

    for i, asset in enumerate(assets_to_process):
        sym     = asset["symbol"]
        upd     = {}

        # 1. Names
        if do_names and sym in nse_list:
            new_name = nse_list[sym]["name"]
            if new_name and (not asset["name"] or asset["name"] == sym):
                upd["name"] = new_name
                updated_names += 1
            # Also update ISIN if missing
            if not asset.get("isin") and nse_list[sym].get("isin"):
                upd["isin"] = nse_list[sym]["isin"]

        # 2. Cap classification
        if do_caps and sym in sym_to_cap:
            new_cap = sym_to_cap[sym]
            if new_cap and asset.get("sub_class","") in ("","Unclassified","Unknown",None):
                upd["sub_class"] = new_cap
                updated_caps += 1

        # 3. Sector — manual mapping first
        if do_sectors and not asset.get("sector") and sym in MANUAL_SECTORS:
            upd["sector"] = MANUAL_SECTORS[sym]
            updated_sectors += 1

        # 4. Yahoo Finance sector (slow path)
        if do_yf and not asset.get("sector") and sym not in MANUAL_SECTORS:
            sector = _fetch_sector_yf(sym)
            if sector:
                upd["sector"] = sector
                updated_sectors += 1
                yf_fetched += 1
            time.sleep(0.25)

        if upd:
            upd["last_updated"] = datetime.now().isoformat()
            batch_updates.append((sym, upd))

        # Flush every 100
        if len(batch_updates) >= 100:
            ok, err = _flush(batch_updates)
            errors += err
            batch_updates = []

        # Progress update every 50
        if (i+1) % 50 == 0 or i == len(assets_to_process)-1:
            frac = (i+1) / len(assets_to_process)
            prog.progress(frac, text=f"{i+1}/{len(assets_to_process)} processed")
            log_lines = [
                f"✓ Names updated:  {updated_names}",
                f"✓ Cap classified: {updated_caps}",
                f"✓ Sectors mapped: {updated_sectors}",
                f"{'✓' if yf_fetched==0 else '●'} YF sectors:     {yf_fetched}",
                f"⚠ Errors:         {errors}",
            ]
            log_container.markdown(
                '<div style="background:#0F1117;border:1px solid #252D40;border-radius:8px;'
                'padding:.8rem 1rem;font-family:monospace;font-size:.78rem;color:#C8D0E0;line-height:2">'
                + "<br>".join(log_lines) + "</div>",
                unsafe_allow_html=True
            )

    # Final flush
    if batch_updates:
        ok, err = _flush(batch_updates)
        errors += err

    clear_market_cache()
    prog.progress(1.0, text="Complete ✓")

    # Summary
    st.success(f"""
    ✅ Enrichment complete!
    - **{updated_names}** company names updated
    - **{updated_caps}** stocks cap-classified (Large/Mid/Small)
    - **{updated_sectors}** sectors assigned
    - **{yf_fetched}** sectors from Yahoo Finance
    - **{errors}** errors
    """)

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
