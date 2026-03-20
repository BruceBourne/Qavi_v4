import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate
from utils.db import sb
from utils.crypto import fmt_date
from datetime import date, datetime
import pandas as pd

# ── HELPERS ───────────────────────────────────────────────────────────────

def _read(f):
    for enc in ("utf-8","latin-1","cp1252","utf-8-sig"):
        try:
            f.seek(0)
            if f.name.lower().endswith(".csv"):
                return pd.read_csv(f, encoding=enc), None
            else:
                f.seek(0)
                return pd.read_excel(f), None
        except UnicodeDecodeError:
            continue
        except Exception as e:
            return None, str(e)
    return None, "Could not decode file encoding."

def _norm(df):
    df.columns = [str(c).strip().lower().replace(" ","_").replace("-","_").replace(".","_") for c in df.columns]
    return df

def _col(df, *names):
    for n in names:
        if n in df.columns: return df[n]
    return None

def _safe_float(v, default=0.0):
    try: return float(str(v).replace(",","").replace(" ","").strip())
    except: return default

def _safe_int(v, default=0):
    try: return int(float(str(v).replace(",","").strip()))
    except: return default

def _batch_upsert_prices(rows: list, table="prices", conflict="symbol,price_date"):
    """Upsert in batches of 500 for speed — Supabase handles bulk well."""
    if not rows: return 0
    total  = 0
    BATCH  = 500
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i+BATCH]
        try:
            sb().table(table).upsert(chunk, on_conflict=conflict).execute()
            total += len(chunk)
        except Exception as e:
            st.warning(f"Batch {i//BATCH+1} had errors: {e}")
    return total

# ── PAGE ──────────────────────────────────────────────────────────────────

def render():
    if not st.session_state.get("user") or st.session_state.user["role"] != "advisor":
        navigate("login"); return

    st.markdown('<div class="page-title">Market Data Upload</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Update prices, NAVs, FD rates and bond prices · Bulk batch upload for speed</div>', unsafe_allow_html=True)

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "  📈 Equities  ",
        "  💛 ETFs  ",
        "  🏦 MF NAVs  ",
        "  💰 FD Rates  ",
        "  📄 Bonds  ",
    ])

    def _date_selector(key):
        """Returns selected upload date — defaults to today, can be changed."""
        upload_date = st.date_input(
            "Data Date (the date this price data belongs to)",
            value=date.today(), key=key,
            help="Default is today. Change this if uploading historical or yesterday's bhavcopy."
        )
        return upload_date

    def _col_guide(extra=""):
        return f"""
        <div style="background:#0F1117;border:1px solid #252D40;border-radius:9px;
            padding:.9rem 1.1rem;margin-bottom:1rem;font-size:.78rem;color:#C8D0E0;line-height:1.9">
            <b>Symbol:</b> <code>symbol, sc_code, trading_symbol, ticker, series</code><br>
            <b>Close/LTP:</b> <code>close, ltp, last_price, closing_price, close_price, closeprice</code><br>
            <b>Open:</b> <code>open, open_price</code> &nbsp;
            <b>High:</b> <code>high, high_price</code> &nbsp;
            <b>Low:</b> <code>low, low_price</code><br>
            <b>Prev Close:</b> <code>prev_close, previous_close, prevclose</code><br>
            <b>Volume:</b> <code>volume, total_traded_qty, tottrdqty</code>
            {extra}
        </div>"""

    # ── EQUITIES ──────────────────────────────────────────────────────────
    with tab1:
        st.markdown("#### Upload Equity Prices (NSE/BSE Bhavcopy supported)")
        st.markdown(_col_guide(), unsafe_allow_html=True)

        upload_date_eq = _date_selector("eq_date")
        eq_file = st.file_uploader("Upload CSV / Excel", type=["csv","xlsx","xls"], key="eq_up")
        if eq_file:
            df, err = _read(eq_file)
            if err: st.error(err)
            else:
                df = _norm(df)
                st.markdown(f"**{len(df):,} rows detected** — Preview (first 8):")
                st.dataframe(df.head(8), use_container_width=True)

                sym_c  = _col(df,"symbol","sc_code","trading_symbol","ticker","series")
                cl_c   = _col(df,"close","ltp","last_price","closing_price","close_price","closeprice")

                if sym_c is None or cl_c is None:
                    st.error("❌ Could not find symbol or close/LTP column. Check column names above.")
                elif st.button("⬆️ Upload Equity Prices", use_container_width=True, key="do_eq"):
                    now = datetime.now().isoformat()
                    price_date = str(upload_date_eq)
                    o_c   = _col(df,"open","open_price","openprice")
                    h_c   = _col(df,"high","high_price","highprice")
                    lo_c  = _col(df,"low","low_price","lowprice")
                    pc_c  = _col(df,"prev_close","previous_close","prevclose","prev_close_price")
                    vol_c = _col(df,"volume","total_traded_qty","tottrdqty","traded_quantity")
                    chg_c = _col(df,"change_pct","pchange","net_chng_pct")

                    rows = []
                    for i in range(len(df)):
                        sym = str(sym_c.iloc[i]).strip().upper()
                        cl  = _safe_float(cl_c.iloc[i])
                        if not sym or cl <= 0: continue
                        pc  = _safe_float(pc_c.iloc[i], cl) if pc_c is not None else cl
                        chg = _safe_float(chg_c.iloc[i]) if chg_c is not None else (((cl-pc)/pc*100) if pc else 0)
                        rows.append({
                            "symbol": sym, "price_date": price_date,
                            "open":       _safe_float(o_c.iloc[i],  cl) if o_c  is not None else cl,
                            "high":       _safe_float(h_c.iloc[i],  cl) if h_c  is not None else cl,
                            "low":        _safe_float(lo_c.iloc[i], cl) if lo_c is not None else cl,
                            "close": cl, "prev_close": pc,
                            "change_pct": round(chg, 4),
                            "volume":     _safe_int(vol_c.iloc[i]) if vol_c is not None else 0,
                            "last_updated": now,
                        })

                    with st.spinner(f"Uploading {len(rows):,} rows in batches…"):
                        count = _batch_upsert_prices(rows)
                    try: st.cache_data.clear()
                    except: pass
                    st.success(f"✅ {count:,} equity prices updated for {price_date}")

    # ── ETFs ──────────────────────────────────────────────────────────────
    with tab2:
        st.markdown("#### Upload ETF Prices")
        st.markdown(_col_guide(), unsafe_allow_html=True)
        upload_date_etf = _date_selector("etf_date")
        etf_file = st.file_uploader("Upload CSV / Excel", type=["csv","xlsx","xls"], key="etf_up")
        if etf_file:
            df, err = _read(etf_file)
            if err: st.error(err)
            else:
                df = _norm(df)
                sym_c = _col(df,"symbol","sc_code","trading_symbol","ticker")
                cl_c  = _col(df,"close","ltp","last_price","closing_price","close_price","closeprice")
                st.dataframe(df.head(8), use_container_width=True)
                if sym_c is None or cl_c is None:
                    st.error("❌ Could not identify symbol or close column.")
                elif st.button("⬆️ Upload ETF Prices", use_container_width=True, key="do_etf"):
                    now = datetime.now().isoformat()
                    price_date = str(upload_date_etf)
                    o_c  = _col(df,"open","open_price")
                    h_c  = _col(df,"high","high_price")
                    lo_c = _col(df,"low","low_price")
                    pc_c = _col(df,"prev_close","previous_close","prevclose")
                    vol_c= _col(df,"volume","total_traded_qty","tottrdqty")
                    rows = []
                    for i in range(len(df)):
                        sym = str(sym_c.iloc[i]).strip().upper()
                        cl  = _safe_float(cl_c.iloc[i])
                        if not sym or cl <= 0: continue
                        pc  = _safe_float(pc_c.iloc[i], cl) if pc_c is not None else cl
                        chg = ((cl-pc)/pc*100) if pc else 0
                        rows.append({
                            "symbol": sym, "price_date": price_date,
                            "open":  _safe_float(o_c.iloc[i],  cl) if o_c  is not None else cl,
                            "high":  _safe_float(h_c.iloc[i],  cl) if h_c  is not None else cl,
                            "low":   _safe_float(lo_c.iloc[i], cl) if lo_c is not None else cl,
                            "close": cl, "prev_close": pc,
                            "change_pct": round(chg, 4),
                            "volume": _safe_int(vol_c.iloc[i]) if vol_c is not None else 0,
                            "last_updated": now,
                        })
                    with st.spinner(f"Uploading {len(rows):,} ETF rows…"):
                        count = _batch_upsert_prices(rows)
                    try: st.cache_data.clear()
                    except: pass
                    st.success(f"✅ {count:,} ETF prices updated for {price_date}")

    # ── MF NAVs ───────────────────────────────────────────────────────────
    with tab3:
        st.markdown("#### Upload Mutual Fund NAVs")
        st.markdown("""
        <div style="background:#0F1117;border:1px solid #252D40;border-radius:9px;
            padding:.9rem 1.1rem;margin-bottom:1rem;font-size:.78rem;color:#C8D0E0;line-height:1.9">
            <b>Symbol:</b> <code>symbol, scheme_code, amfi_code</code><br>
            <b>NAV:</b> <code>nav, net_asset_value, nav_value</code><br>
            <b>Prev NAV (optional):</b> <code>prev_nav, previous_nav</code>
        </div>""", unsafe_allow_html=True)
        upload_date_mf = _date_selector("mf_date")
        mf_file = st.file_uploader("Upload CSV / Excel", type=["csv","xlsx","xls"], key="mf_up")
        if mf_file:
            df, err = _read(mf_file)
            if err: st.error(err)
            else:
                df = _norm(df)
                sym_c  = _col(df,"symbol","scheme_code","amfi_code")
                nav_c  = _col(df,"nav","net_asset_value","nav_value")
                prev_c = _col(df,"prev_nav","previous_nav")
                st.dataframe(df.head(8), use_container_width=True)
                if sym_c is None or nav_c is None:
                    st.error("❌ Could not find symbol or NAV column.")
                elif st.button("⬆️ Upload MF NAVs", use_container_width=True, key="do_mf"):
                    now        = datetime.now().isoformat()
                    nav_date   = str(upload_date_mf)
                    count = errs = 0
                    # MF table doesn't have a date PK so we update individually — batching via loop
                    prog = st.progress(0)
                    total_rows = len(df)
                    for i in range(total_rows):
                        sym = str(sym_c.iloc[i]).strip().upper()
                        nav = _safe_float(nav_c.iloc[i])
                        if not sym or nav <= 0: continue
                        try:
                            existing = sb().table("mutual_funds").select("nav").eq("symbol",sym).execute()
                            prev     = _safe_float(prev_c.iloc[i], nav) if prev_c is not None else (
                                       existing.data[0]["nav"] if existing.data else nav)
                            chg      = round(((nav-prev)/prev*100),4) if prev else 0
                            sb().table("mutual_funds").update({
                                "nav":nav,"prev_nav":prev,"change_pct":chg,
                                "nav_date":nav_date,"last_updated":now,
                            }).eq("symbol",sym).execute()
                            count += 1
                        except: errs += 1
                        if i % 20 == 0: prog.progress(min((i+1)/total_rows,1.0))
                    prog.progress(1.0)
                    try: st.cache_data.clear()
                    except: pass
                    st.success(f"✅ {count} MF NAVs updated. {f'({errs} skipped)' if errs else ''}")

    # ── FD RATES ─────────────────────────────────────────────────────────
    with tab4:
        st.markdown("#### Update FD Interest Rates")
        st.markdown("""
        <div style="background:#0F1117;border:1px solid #252D40;border-radius:9px;
            padding:.9rem 1.1rem;margin-bottom:1rem;font-size:.78rem;color:#C8D0E0;line-height:1.9">
            <b>Symbol:</b> <code>symbol</code> &nbsp;
            <b>Rate:</b> <code>interest_rate, rate, fd_rate</code><br>
            <b>Tenure (optional):</b> <code>tenure_years, tenure, years</code>
        </div>""", unsafe_allow_html=True)

        fd_file = st.file_uploader("Upload CSV / Excel", type=["csv","xlsx","xls"], key="fd_up")
        if fd_file:
            df, err = _read(fd_file)
            if err: st.error(err)
            else:
                df = _norm(df)
                sym_c  = _col(df,"symbol")
                rate_c = _col(df,"interest_rate","rate","fd_rate")
                ten_c  = _col(df,"tenure_years","tenure","years")
                st.dataframe(df.head(8), use_container_width=True)
                if sym_c is None or rate_c is None:
                    st.error("❌ Need symbol and interest_rate columns.")
                elif st.button("⬆️ Upload FD Rates", use_container_width=True, key="do_fd"):
                    now   = datetime.now().isoformat()
                    count = 0
                    rows_to_upsert = []
                    for i in range(len(df)):
                        sym  = str(sym_c.iloc[i]).strip().upper()
                        rate = _safe_float(rate_c.iloc[i])
                        if not sym or rate <= 0: continue
                        upd = {"interest_rate": rate, "last_updated": now}
                        if ten_c is not None:
                            t = _safe_float(ten_c.iloc[i])
                            if t > 0: upd["tenure_years"] = t
                        try:
                            sb().table("fixed_income").update(upd).eq("symbol",sym).execute()
                            count += 1
                        except: pass
                    try: st.cache_data.clear()
                    except: pass
                    st.success(f"✅ {count} FD rates updated.")

        st.markdown("<br>**Manual single update:**")
        with st.form("manual_fd"):
            try:
                fds = sb().table("fixed_income").select("symbol,name,interest_rate").eq("asset_class","Bank FD").order("symbol").execute().data or []
            except: fds = []
            if fds:
                fd_sym   = st.selectbox("FD", [f["symbol"] for f in fds],
                                        format_func=lambda x: f"{x} — {next(f['name'] for f in fds if f['symbol']==x)}")
                cur_rate = float(next((f["interest_rate"] for f in fds if f["symbol"]==fd_sym),0))
                new_rate = st.number_input("New Interest Rate (%)", value=cur_rate,
                                           min_value=0.0, step=0.05, format="%.2f")
                if st.form_submit_button("Update", use_container_width=True):
                    sb().table("fixed_income").update({
                        "interest_rate": new_rate,
                        "last_updated": datetime.now().isoformat()
                    }).eq("symbol", fd_sym).execute()
                    try: st.cache_data.clear()
                    except: pass
                    st.success(f"Updated {fd_sym} → {new_rate}%")

    # ── BONDS ─────────────────────────────────────────────────────────────
    with tab5:
        st.markdown("#### Update Bond Prices")
        st.markdown("""
        <div style="background:#0F1117;border:1px solid #252D40;border-radius:9px;
            padding:.9rem 1.1rem;margin-bottom:1rem;font-size:.78rem;color:#C8D0E0;line-height:1.9">
            <b>Symbol:</b> <code>symbol, isin</code><br>
            <b>Price:</b> <code>current_price, price, close, ltp</code><br>
            <b>Yield/Rate (optional):</b> <code>yield, interest_rate, coupon_rate</code>
        </div>""", unsafe_allow_html=True)

        bond_file = st.file_uploader("Upload CSV / Excel", type=["csv","xlsx","xls"], key="bond_up")
        if bond_file:
            df, err = _read(bond_file)
            if err: st.error(err)
            else:
                df = _norm(df)
                sym_c   = _col(df,"symbol","isin")
                price_c = _col(df,"current_price","price","close","ltp")
                yield_c = _col(df,"yield","interest_rate","coupon_rate","rate")
                st.dataframe(df.head(8), use_container_width=True)
                if sym_c is None or price_c is None:
                    st.error("❌ Need symbol and price columns.")
                elif st.button("⬆️ Upload Bond Prices", use_container_width=True, key="do_bond"):
                    now   = datetime.now().isoformat()
                    count = 0
                    for i in range(len(df)):
                        sym   = str(sym_c.iloc[i]).strip().upper()
                        price = _safe_float(price_c.iloc[i])
                        if not sym or price <= 0: continue
                        upd   = {"current_price": price, "last_updated": now}
                        if yield_c is not None:
                            y = _safe_float(yield_c.iloc[i])
                            if y > 0: upd["interest_rate"] = y
                        try:
                            sb().table("fixed_income").update(upd).eq("symbol",sym).execute()
                            count += 1
                        except: pass
                    try: st.cache_data.clear()
                    except: pass
                    st.success(f"✅ {count} bond prices updated.")

    st.markdown("---")
    if st.button("← Back to Profile"):
        navigate("profile")
