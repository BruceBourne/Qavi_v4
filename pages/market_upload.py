import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate
from utils.db import sb, clear_market_cache
from datetime import date, datetime
import pandas as pd
import time

# ── SUB-CATEGORY AUTO-CLASSIFICATION ─────────────────────────────────────
# Maps known NSE sector/index/series codes to Qavi sub-categories

EQ_SUBCATEGORY_RULES = [
    # (keywords_in_name_or_series, sub_category)
    (["NIFTY 50","NIFTY50","SENSEX","LARGE","BLUECHIP","BLUE CHIP","TOP 100","TOP100"], "Large Cap"),
    (["MIDCAP","MID CAP","MID-CAP","NIFTY MID","MIDSEL"],                               "Mid Cap"),
    (["SMALLCAP","SMALL CAP","SMALL-CAP","NIFTY SMALL","SMLSEL"],                       "Small Cap"),
]

ETF_SUBCATEGORY_RULES = [
    (["GOLD","SILVER","COMMODITY","METAL"],                 "Commodity ETF"),
    (["LIQUID","MONEY","OVERNIGHT"],                        "Liquid ETF"),
    (["BANK","FIN","FINANCIAL","INFRA","IT","PHARMA","AUTO","SECTOR"], "Sectoral ETF"),
    (["NIFTY","SENSEX","INDEX","INDICES","500","200","100"], "Index ETF"),
]

def _classify_equity(name: str) -> str:
    n = name.upper()
    for keywords, sub in EQ_SUBCATEGORY_RULES:
        if any(k in n for k in keywords):
            return sub
    return "Large Cap"  # safe default

def _classify_etf(name: str) -> str:
    n = name.upper()
    for keywords, sub in ETF_SUBCATEGORY_RULES:
        if any(k in n for k in keywords):
            return sub
    return "Index ETF"

# ── FILE READING ──────────────────────────────────────────────────────────

def _read(f):
    for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            f.seek(0)
            if f.name.lower().endswith(".csv"):
                return pd.read_csv(f, encoding=enc, low_memory=False), None
            else:
                f.seek(0)
                return pd.read_excel(f, engine="openpyxl"), None
        except UnicodeDecodeError:
            continue
        except Exception as e:
            return None, str(e)
    return None, "Cannot decode file encoding."

def _norm(df):
    df.columns = [
        str(c).strip().lower()
          .replace(" ","_").replace("-","_").replace(".","_").replace("/","_")
        for c in df.columns
    ]
    return df

def _col(df, *names):
    for n in names:
        if n in df.columns: return df[n]
    return None

def _f(v, d=0.0):
    try:    return float(str(v).replace(",","").replace(" ","").strip() or d)
    except: return d

def _i(v):
    try:    return int(float(str(v).replace(",","").strip()))
    except: return 0

# ── BATCH UPSERT ─────────────────────────────────────────────────────────
# Supabase free tier handles ~500 rows/request reliably.
# For 2500 rows: 5 batches × ~1.5s each ≈ 8–10 seconds total.
# Streamlit Cloud has a 60s request timeout — 2500 rows fits comfortably.
# Beyond ~5000 rows may hit the timeout; split large files if needed.

BATCH = 500

def _upsert_batched(rows, table, conflict, prog_start, prog_end, prog_bar, label):
    if not rows: return 0
    count   = 0
    n_batch = max(1, len(rows) // BATCH + (1 if len(rows) % BATCH else 0))
    for idx in range(0, len(rows), BATCH):
        chunk     = rows[idx : idx + BATCH]
        batch_num = idx // BATCH + 1
        frac      = prog_start + (prog_end - prog_start) * (batch_num / n_batch)
        prog_bar.progress(frac, text=f"{label} — batch {batch_num}/{n_batch} ({min(idx+BATCH,len(rows))}/{len(rows)} rows)")
        try:
            sb().table(table).upsert(chunk, on_conflict=conflict).execute()
            count += len(chunk)
        except Exception as e:
            st.warning(f"Batch {batch_num} error: {e}")
        time.sleep(0.05)   # tiny breathing room between batches
    return count


# ── PAGE ──────────────────────────────────────────────────────────────────

def render():
    if not st.session_state.get("user") or st.session_state.user["role"] not in ("advisor","owner"):
        navigate("login"); return

    st.markdown('<div class="page-title">Market Data Upload</div>', unsafe_allow_html=True)

    # Capacity notice — compact, no jargon
    st.markdown("""
    <div style="background:#1E2535;border-left:3px solid #F5B731;border-radius:0 8px 8px 0;
        padding:.7rem 1rem;margin-bottom:1rem;font-size:.8rem;color:#C8D0E0">
        <b style="color:#F5B731">Upload capacity:</b>
        Up to <b>2,500 rows</b> per file reliably (~10 seconds).
        For larger files, split into multiple uploads of ≤2,500 rows each.
        NSE / BSE Bhavcopy CSV formats are directly supported.
    </div>
    """, unsafe_allow_html=True)

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "  📈 Equities  ",
        "  💛 ETFs  ",
        "  🏦 MF NAVs  ",
        "  💰 FD Rates  ",
        "  📄 Bonds  ",
    ])

    def _hint(body):
        st.markdown(
            f'<div style="background:#0F1117;border:1px solid #252D40;border-radius:7px;'
            f'padding:.75rem 1rem;margin-bottom:.9rem;font-size:.77rem;'
            f'color:#C8D0E0;line-height:1.95">{body}</div>',
            unsafe_allow_html=True)

    def _date_pick(key):
        return st.date_input(
            "Data date", value=date.today(), key=key,
            help="Change this to upload historical data without overwriting other dates."
        )

    # ── EQUITIES ──────────────────────────────────────────────────────────
    with tab1:
        st.markdown("#### Equity Prices")
        _hint(
            "<b>Symbol:</b> <code>symbol, sc_code, trading_symbol, ticker</code><br>"
            "<b>Close/LTP:</b> <code>close, ltp, last_price, closeprice</code><br>"
            "<b>Open/High/Low:</b> <code>open, high, low</code> &nbsp;"
            "<b>Prev Close:</b> <code>prev_close, prevclose</code><br>"
            "<b>Volume:</b> <code>volume, tottrdqty</code> &nbsp;"
            "<b>Company name (optional):</b> <code>name, company_name, sc_name</code>"
        )
        eq_date = _date_pick("eq_date")
        eq_file = st.file_uploader("CSV / Excel", type=["csv","xlsx","xls"], key="eq_up")

        if eq_file:
            df, err = _read(eq_file)
            if err: st.error(err)
            else:
                df    = _norm(df)
                sym_c = _col(df,"symbol","sc_code","trading_symbol","ticker")
                cl_c  = _col(df,"close","ltp","last_price","closing_price","close_price","closeprice")

                if sym_c is None or cl_c is None:
                    st.error("❌ Symbol or close/LTP column not found.")
                else:
                    st.caption(f"{len(df):,} rows detected")
                    st.dataframe(df.head(5), use_container_width=True)

                    if st.button("⬆️ Upload", use_container_width=True, key="do_eq"):
                        now   = datetime.now().isoformat()
                        pd_s  = str(eq_date)
                        o_c   = _col(df,"open","open_price","openprice")
                        h_c   = _col(df,"high","high_price","highprice")
                        lo_c  = _col(df,"low","low_price","lowprice")
                        pc_c  = _col(df,"prev_close","previous_close","prevclose")
                        vol_c = _col(df,"volume","total_traded_qty","tottrdqty")
                        nm_c  = _col(df,"name","company_name","sc_name","isin_name")

                        price_rows = []
                        asset_rows = []
                        for i in range(len(df)):
                            sym = str(sym_c.iloc[i]).strip().upper()
                            cl  = _f(cl_c.iloc[i])
                            if not sym or sym in ("NAN","SYMBOL","") or cl <= 0: continue
                            pc  = _f(pc_c.iloc[i], cl) if pc_c is not None else cl
                            chg = _f(_col(df,"change_pct","pchange").iloc[i] if _col(df,"change_pct","pchange") is not None else "0")
                            if chg == 0 and pc: chg = round((cl-pc)/pc*100, 4)
                            price_rows.append({
                                "symbol":sym,"price_date":pd_s,
                                "open":  _f(o_c.iloc[i],  cl) if o_c  is not None else cl,
                                "high":  _f(h_c.iloc[i],  cl) if h_c  is not None else cl,
                                "low":   _f(lo_c.iloc[i], cl) if lo_c is not None else cl,
                                "close":cl,"prev_close":pc,"change_pct":round(chg,4),
                                "volume":_i(vol_c.iloc[i]) if vol_c is not None else 0,
                                "last_updated":now,
                            })
                            nm = str(nm_c.iloc[i]).strip() if nm_c is not None else sym
                            asset_rows.append((sym, nm))

                        prog = st.progress(0.0, text="Starting upload…")
                        count = _upsert_batched(price_rows, "prices", "symbol,price_date",
                                                0.0, 0.8, prog, "Uploading equity prices")

                        prog.progress(0.82, text="Registering new tickers…")
                        new_count = 0
                        # Batch-check existing symbols to avoid N×1 queries
                        try:
                            # Paginate to get ALL existing symbols past 1000-row limit
                            ex_syms = set()
                            _pg = 0
                            while True:
                                _batch = sb().table("assets").select("symbol").range(_pg*1000,(_pg+1)*1000-1).execute().data or []
                                ex_syms.update(r["symbol"] for r in _batch)
                                if len(_batch) < 1000: break
                                _pg += 1
                            # Name enrichment: if name == symbol (ticker only), use proper name from df
                            # NSE bhavcopy columns: SYMBOL, SERIES, ISIN, COMPANY (varies by format)
                            name_lookup = {}
                            for sym_n, nm_n in asset_rows:
                                if nm_n and nm_n != sym_n:
                                    name_lookup[sym_n] = nm_n
                            # Also check bhavcopy for company name columns
                            for col_name in ["company","company_name","sc_name","isin_name",
                                             "symbol_description","long_name"]:
                                col_series = _col(df, col_name)
                                if col_series is not None:
                                    for i in range(len(df)):
                                        sym_r = str(sym_c.iloc[i]).strip().upper()
                                        val   = str(col_series.iloc[i]).strip()
                                        if val and val != sym_r and val.lower() != "nan":
                                            name_lookup[sym_r] = val
                                    break
                            new_assets = []
                            for sym_n, nm_n in asset_rows:
                                if sym_n not in ex_syms:
                                    final_name = name_lookup.get(sym_n, nm_n)
                                    # If name still equals symbol, mark as needing enrichment
                                    if final_name == sym_n:
                                        final_name = sym_n  # keep as-is, admin can enrich later
                                    new_assets.append({
                                        "symbol": sym_n,
                                        "name": final_name,
                                        "asset_class": "Equity",
                                        "sub_class": _classify_equity(final_name),
                                        "exchange": "NSE",
                                        "is_active": True,
                                        "unit_type": "shares",
                                    })
                            # Also update name for existing assets that have symbol==name
                            update_names = [
                                (sym_n, name_lookup[sym_n])
                                for sym_n, nm_n in asset_rows
                                if sym_n in ex_syms and sym_n in name_lookup
                            ]
                            if new_assets:
                                for j in range(0, len(new_assets), 200):
                                    sb().table("assets").upsert(new_assets[j:j+200], on_conflict="symbol").execute()
                                new_count = len(new_assets)
                            if update_names:
                                for sym_n, nm_n in update_names[:500]:  # cap at 500 updates
                                    try:
                                        sb().table("assets").update({"name": nm_n}).eq("symbol", sym_n).eq("name", sym_n).execute()
                                    except Exception: pass
                            # Fix empty sub_class for existing assets from this upload
                            sb().table("assets").update({"sub_class":"Unclassified"})                                .eq("sub_class","").eq("asset_class","Equity").execute()
                        except Exception as e:
                            st.warning(f"Ticker registration: {e}")

                        prog.progress(1.0, text="Done ✓")
                        clear_market_cache()
                        st.success(
                            f"✅ {count:,} prices saved for {pd_s}. "
                            f"{f'{new_count} new tickers added.' if new_count else ''}"
                        )

    # ── ETFs ──────────────────────────────────────────────────────────────
    with tab2:
        st.markdown("#### ETF Prices")
        _hint(
            "<b>Symbol:</b> <code>symbol, sc_code, trading_symbol</code><br>"
            "<b>Close/LTP:</b> <code>close, ltp, last_price, closeprice</code><br>"
            "<b>Open/High/Low/Prev Close/Volume</b> same as equities"
        )
        etf_date = _date_pick("etf_date")
        etf_file = st.file_uploader("CSV / Excel", type=["csv","xlsx","xls"], key="etf_up")
        if etf_file:
            df, err = _read(etf_file)
            if err: st.error(err)
            else:
                df    = _norm(df)
                sym_c = _col(df,"symbol","sc_code","trading_symbol","ticker")
                cl_c  = _col(df,"close","ltp","last_price","closeprice")
                if sym_c is None or cl_c is None:
                    st.error("❌ Symbol or close column not found.")
                else:
                    st.caption(f"{len(df):,} rows detected")
                    st.dataframe(df.head(5), use_container_width=True)
                    if st.button("⬆️ Upload", use_container_width=True, key="do_etf"):
                        now   = datetime.now().isoformat()
                        pd_s  = str(etf_date)
                        o_c  = _col(df,"open","open_price")
                        h_c  = _col(df,"high","high_price")
                        lo_c = _col(df,"low","low_price")
                        pc_c = _col(df,"prev_close","prevclose","previous_close")
                        vol_c= _col(df,"volume","tottrdqty")
                        nm_c = _col(df,"name","company_name","sc_name")
                        rows  = []
                        new_assets = []
                        try:
                            # Paginate to get ALL existing symbols past 1000-row limit
                            ex_syms = set()
                            _pg = 0
                            while True:
                                _batch = sb().table("assets").select("symbol").range(_pg*1000,(_pg+1)*1000-1).execute().data or []
                                ex_syms.update(r["symbol"] for r in _batch)
                                if len(_batch) < 1000: break
                                _pg += 1
                        except: ex_syms = set()
                        for i in range(len(df)):
                            sym = str(sym_c.iloc[i]).strip().upper()
                            cl  = _f(cl_c.iloc[i])
                            if not sym or cl <= 0: continue
                            pc  = _f(pc_c.iloc[i], cl) if pc_c is not None else cl
                            rows.append({
                                "symbol":sym,"price_date":pd_s,
                                "open":  _f(o_c.iloc[i],  cl) if o_c  is not None else cl,
                                "high":  _f(h_c.iloc[i],  cl) if h_c  is not None else cl,
                                "low":   _f(lo_c.iloc[i], cl) if lo_c is not None else cl,
                                "close":cl,"prev_close":pc,
                                "change_pct":round(((cl-pc)/pc*100) if pc else 0, 4),
                                "volume":_i(vol_c.iloc[i]) if vol_c is not None else 0,
                                "last_updated":now,
                            })
                            if sym not in ex_syms:
                                nm = str(nm_c.iloc[i]).strip() if nm_c is not None else sym
                                new_assets.append({
                                    "symbol":sym,"name":nm,"asset_class":"ETF",
                                    "sub_class":_classify_etf(nm),"exchange":"NSE",
                                    "is_active":True,"unit_type":"units"
                                })
                        prog = st.progress(0.0, text="Uploading ETF prices…")
                        count = _upsert_batched(rows, "prices", "symbol,price_date", 0.0, 0.85, prog, "ETF prices")
                        if new_assets:
                            prog.progress(0.88, text="Adding new ETFs…")
                            for j in range(0, len(new_assets), 200):
                                sb().table("assets").upsert(new_assets[j:j+200], on_conflict="symbol").execute()
                        prog.progress(1.0, text="Done ✓")
                        clear_market_cache()
                        st.success(f"✅ {count:,} ETF prices saved. {f'{len(new_assets)} new tickers.' if new_assets else ''}")

    # ── MF NAVs ───────────────────────────────────────────────────────────
    with tab3:
        st.markdown("#### Mutual Fund NAVs")
        _hint(
            "<b>Symbol:</b> <code>symbol, scheme_code, amfi_code</code><br>"
            "<b>NAV:</b> <code>nav, net_asset_value</code><br>"
            "<b>Prev NAV (optional):</b> <code>prev_nav, previous_nav</code>"
        )
        mf_date = _date_pick("mf_date")
        mf_file = st.file_uploader("CSV / Excel", type=["csv","xlsx","xls"], key="mf_up")
        if mf_file:
            df, err = _read(mf_file)
            if err: st.error(err)
            else:
                df    = _norm(df)
                sym_c = _col(df,"symbol","scheme_code","amfi_code")
                nav_c = _col(df,"nav","net_asset_value","nav_value")
                prev_c= _col(df,"prev_nav","previous_nav")
                if sym_c is None or nav_c is None:
                    st.error("❌ Symbol or NAV column not found.")
                else:
                    st.caption(f"{len(df):,} rows detected")
                    st.dataframe(df.head(5), use_container_width=True)
                    if st.button("⬆️ Upload", use_container_width=True, key="do_mf"):
                        now     = datetime.now().isoformat()
                        nav_dt  = str(mf_date)
                        count = errs = 0
                        prog  = st.progress(0.0, text="Uploading MF NAVs…")
                        total_r = len(df)
                        # MFs use update (not upsert) so must loop — but batch the DB reads
                        # First: get all existing NAVs in one query
                        try:
                            existing = {r["symbol"]:r["nav"]
                                       for r in sb().table("mutual_funds").select("symbol,nav").execute().data or []}
                        except: existing = {}
                        update_rows = []
                        for i in range(total_r):
                            sym = str(sym_c.iloc[i]).strip().upper()
                            nav = _f(nav_c.iloc[i])
                            if not sym or nav <= 0: continue
                            prev = _f(prev_c.iloc[i], nav) if prev_c is not None else existing.get(sym, nav)
                            chg  = round(((nav-prev)/prev*100),4) if prev else 0
                            update_rows.append((sym, nav, prev, chg))
                        # Execute updates in groups of 50 to show progress
                        GROUP = 50
                        for gi, start in enumerate(range(0, len(update_rows), GROUP)):
                            chunk = update_rows[start:start+GROUP]
                            for sym, nav, prev, chg in chunk:
                                try:
                                    sb().table("mutual_funds").update({
                                        "nav":nav,"prev_nav":prev,"change_pct":chg,
                                        "nav_date":nav_dt,"last_updated":now,
                                    }).eq("symbol",sym).execute()
                                    count += 1
                                except: errs += 1
                            frac = min((start+GROUP)/max(len(update_rows),1), 1.0)
                            prog.progress(frac, text=f"MF NAVs — {min(start+GROUP,len(update_rows))}/{len(update_rows)}")
                        prog.progress(1.0, text="Done ✓")
                        clear_market_cache()
                        st.success(f"✅ {count} MF NAVs updated. {f'({errs} skipped)' if errs else ''}")

    # ── FD RATES ─────────────────────────────────────────────────────────
    with tab4:
        st.markdown("#### FD Interest Rates")
        _hint(
            "<b>Symbol:</b> <code>symbol</code><br>"
            "<b>Rate:</b> <code>interest_rate, rate, fd_rate</code><br>"
            "<b>Tenure (optional):</b> <code>tenure_years, tenure</code>"
        )
        fd_file = st.file_uploader("CSV / Excel", type=["csv","xlsx","xls"], key="fd_up")
        if fd_file:
            df, err = _read(fd_file)
            if err: st.error(err)
            else:
                df    = _norm(df)
                sym_c = _col(df,"symbol")
                rt_c  = _col(df,"interest_rate","rate","fd_rate")
                tn_c  = _col(df,"tenure_years","tenure","years")
                st.dataframe(df.head(5), use_container_width=True)
                if sym_c is None or rt_c is None:
                    st.error("❌ Need symbol and interest_rate columns.")
                elif st.button("⬆️ Upload", use_container_width=True, key="do_fd"):
                    now = datetime.now().isoformat()
                    count = 0
                    prog  = st.progress(0.0, text="Updating FD rates…")
                    total_r = len(df)
                    for i in range(total_r):
                        sym  = str(sym_c.iloc[i]).strip().upper()
                        rate = _f(rt_c.iloc[i])
                        if not sym or rate <= 0: continue
                        upd = {"interest_rate":rate,"last_updated":now}
                        if tn_c is not None:
                            t = _f(tn_c.iloc[i])
                            if t > 0: upd["tenure_years"] = t
                        try: sb().table("fixed_income").update(upd).eq("symbol",sym).execute(); count += 1
                        except: pass
                        if i % 10 == 0: prog.progress(min((i+1)/total_r, 1.0), text=f"FD rates — {i+1}/{total_r}")
                    prog.progress(1.0, text="Done ✓")
                    clear_market_cache()
                    st.success(f"✅ {count} FD rates updated.")

        st.markdown(""); st.markdown("**Manual update:**")
        with st.form("manual_fd"):
            try:
                fds = sb().table("fixed_income").select("symbol,name,interest_rate").eq("asset_class","Bank FD").order("symbol").execute().data or []
            except: fds = []
            if fds:
                fd_sym   = st.selectbox("FD", [f["symbol"] for f in fds],
                                        format_func=lambda x: f"{x} — {next(f['name'] for f in fds if f['symbol']==x)}")
                cur_rate = float(next((f["interest_rate"] for f in fds if f["symbol"]==fd_sym),0))
                new_rate = st.number_input("New Rate (%)", value=cur_rate, min_value=0.0, step=0.05, format="%.2f")
                if st.form_submit_button("Update", use_container_width=True):
                    sb().table("fixed_income").update({
                        "interest_rate":new_rate,"last_updated":datetime.now().isoformat()
                    }).eq("symbol",fd_sym).execute()
                    clear_market_cache()
                    st.success(f"Updated {fd_sym} → {new_rate}%")
            else:
                st.info("No FDs in database.")

    # ── BONDS ─────────────────────────────────────────────────────────────
    with tab5:
        st.markdown("#### Bond Prices")
        _hint(
            "<b>Symbol:</b> <code>symbol, isin</code><br>"
            "<b>Price:</b> <code>current_price, price, close, ltp</code><br>"
            "<b>Yield/Rate (optional):</b> <code>yield, interest_rate, coupon_rate</code>"
        )
        bond_file = st.file_uploader("CSV / Excel", type=["csv","xlsx","xls"], key="bond_up")
        if bond_file:
            df, err = _read(bond_file)
            if err: st.error(err)
            else:
                df      = _norm(df)
                sym_c   = _col(df,"symbol","isin")
                price_c = _col(df,"current_price","price","close","ltp")
                yield_c = _col(df,"yield","interest_rate","coupon_rate","rate")
                st.dataframe(df.head(5), use_container_width=True)
                if sym_c is None or price_c is None:
                    st.error("❌ Need symbol and price columns.")
                elif st.button("⬆️ Upload", use_container_width=True, key="do_bond"):
                    now   = datetime.now().isoformat()
                    count = 0
                    prog  = st.progress(0.0, text="Updating bond prices…")
                    total_r = len(df)
                    for i in range(total_r):
                        sym   = str(sym_c.iloc[i]).strip().upper()
                        price = _f(price_c.iloc[i])
                        if not sym or price <= 0: continue
                        upd   = {"current_price":price,"last_updated":now}
                        if yield_c is not None:
                            y = _f(yield_c.iloc[i])
                            if y > 0: upd["interest_rate"] = y
                        try: sb().table("fixed_income").update(upd).eq("symbol",sym).execute(); count += 1
                        except: pass
                        if i % 10 == 0: prog.progress(min((i+1)/total_r,1.0))
                    prog.progress(1.0, text="Done ✓")
                    clear_market_cache()
                    st.success(f"✅ {count} bond prices updated.")

    st.markdown("---")
    if st.button("← Back"):
        navigate("profile")
