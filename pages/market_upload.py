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
    """Read CSV or Excel, trying multiple encodings for bhavcopy files."""
    for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
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
    return None, "Cannot decode file. Try saving as UTF-8 CSV."

def _norm(df):
    df.columns = [
        str(c).strip().lower()
           .replace(" ","_").replace("-","_")
           .replace(".","_").replace("/","_")
        for c in df.columns
    ]
    return df

def _col(df, *names):
    for n in names:
        if n in df.columns:
            return df[n]
    return None

def _f(v, d=0.0):
    try:    return float(str(v).replace(",","").replace(" ","").strip() or d)
    except: return d

def _i(v, d=0):
    try:    return int(float(str(v).replace(",","").strip()))
    except: return d

def _batch_upsert(rows, table, conflict):
    """Upsert rows in batches of 500. Returns count of rows attempted."""
    if not rows: return 0
    total = 0
    BATCH = 500
    for i in range(0, len(rows), BATCH):
        chunk = rows[i : i + BATCH]
        try:
            sb().table(table).upsert(chunk, on_conflict=conflict).execute()
            total += len(chunk)
        except Exception as e:
            st.warning(f"Batch {i//BATCH+1} error: {e}")
    return total

def _ensure_asset(sym, name, asset_class, sub_class="", exchange="NSE"):
    """Insert into assets table if not already there — so new tickers appear in market pages."""
    try:
        existing = sb().table("assets").select("symbol").eq("symbol", sym).execute()
        if not existing.data:
            sb().table("assets").insert({
                "symbol": sym, "name": name or sym,
                "asset_class": asset_class,
                "sub_class": sub_class or "",
                "exchange": exchange,
                "is_active": True,
                "unit_type": "shares" if asset_class == "Equity" else "units",
            }).execute()
    except Exception:
        pass  # Don't fail the whole upload over one asset insert

def _date_picker(key, label="Data date for this upload"):
    return st.date_input(
        label, value=date.today(), key=key,
        help="Default is today. Change this to point to historical data without overwriting other dates."
    )

def _col_hint(body):
    st.markdown(
        f'<div style="background:#0F1117;border:1px solid #252D40;border-radius:8px;'
        f'padding:.85rem 1rem;margin-bottom:.9rem;font-size:.77rem;'
        f'color:#C8D0E0;line-height:1.95">{body}</div>',
        unsafe_allow_html=True)

# ── PAGE ──────────────────────────────────────────────────────────────────

def render():
    if not st.session_state.get("user") or st.session_state.user["role"] != "advisor":
        navigate("login"); return

    st.markdown('<div class="page-title">Market Data Upload</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="page-sub">Bulk upload prices, NAVs, FD rates and bond prices · '
        'Batched 500 rows at a time · New tickers auto-registered</div>',
        unsafe_allow_html=True)

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "  📈 Equities  ",
        "  💛 ETFs  ",
        "  🏦 MF NAVs  ",
        "  💰 FD Rates  ",
        "  📄 Bonds  ",
    ])

    # ── EQUITIES ──────────────────────────────────────────────────────────
    with tab1:
        st.markdown("#### Equity Prices — NSE / BSE Bhavcopy")
        _col_hint(
            "<b>Symbol:</b> <code>symbol, sc_code, trading_symbol, ticker</code><br>"
            "<b>Close/LTP:</b> <code>close, ltp, last_price, closing_price, closeprice</code><br>"
            "<b>Open/High/Low:</b> <code>open, high, low</code> &nbsp; "
            "<b>Prev Close:</b> <code>prev_close, prevclose, previous_close</code><br>"
            "<b>Volume:</b> <code>volume, total_traded_qty, tottrdqty</code><br>"
            "<b>Name (optional):</b> <code>name, company_name, sc_name</code><br>"
            "<span style='color:#F5B731'>New symbols not yet in the database are auto-added.</span>"
        )
        upload_date = _date_picker("eq_date")
        eq_file = st.file_uploader("Upload CSV / Excel", type=["csv","xlsx","xls"], key="eq_up")

        if eq_file:
            df, err = _read(eq_file)
            if err:
                st.error(err)
            else:
                df = _norm(df)
                st.markdown(f"**{len(df):,} rows** — Preview:")
                st.dataframe(df.head(8), use_container_width=True)

                sym_c = _col(df, "symbol","sc_code","trading_symbol","ticker")
                cl_c  = _col(df, "close","ltp","last_price","closing_price","close_price","closeprice")

                if sym_c is None or cl_c is None:
                    st.error("❌ Cannot find symbol or close/LTP column.")
                elif st.button("⬆️ Upload Equity Prices", use_container_width=True, key="do_eq"):
                    now        = datetime.now().isoformat()
                    price_date = str(upload_date)
                    o_c   = _col(df, "open","open_price","openprice")
                    h_c   = _col(df, "high","high_price","highprice")
                    lo_c  = _col(df, "low","low_price","lowprice")
                    pc_c  = _col(df, "prev_close","previous_close","prevclose","prev_close_price")
                    vol_c = _col(df, "volume","total_traded_qty","tottrdqty","traded_quantity")
                    chg_c = _col(df, "change_pct","pchange","net_chng_pct")
                    nm_c  = _col(df, "name","company_name","sc_name","isin_name")

                    price_rows  = []
                    asset_rows  = []  # new tickers to register
                    for i in range(len(df)):
                        sym = str(sym_c.iloc[i]).strip().upper()
                        cl  = _f(cl_c.iloc[i])
                        if not sym or sym in ("", "NAN", "SYMBOL") or cl <= 0:
                            continue
                        pc  = _f(pc_c.iloc[i], cl)  if pc_c  is not None else cl
                        chg = _f(chg_c.iloc[i])     if chg_c is not None else (((cl-pc)/pc*100) if pc else 0)
                        price_rows.append({
                            "symbol": sym, "price_date": price_date,
                            "open":  _f(o_c.iloc[i],  cl) if o_c  is not None else cl,
                            "high":  _f(h_c.iloc[i],  cl) if h_c  is not None else cl,
                            "low":   _f(lo_c.iloc[i], cl) if lo_c is not None else cl,
                            "close": cl, "prev_close": pc,
                            "change_pct": round(chg, 4),
                            "volume": _i(vol_c.iloc[i]) if vol_c is not None else 0,
                            "last_updated": now,
                        })
                        name = str(nm_c.iloc[i]).strip() if nm_c is not None else sym
                        asset_rows.append((sym, name))

                    prog = st.progress(0.0, text="Uploading prices…")
                    with st.spinner(f"Uploading {len(price_rows):,} rows…"):
                        count = _batch_upsert(price_rows, "prices", "symbol,price_date")
                    prog.progress(0.7, text="Registering new tickers…")

                    # Register any new symbols into assets table
                    new_count = 0
                    for sym, name in asset_rows:
                        try:
                            ex = sb().table("assets").select("symbol").eq("symbol", sym).execute()
                            if not ex.data:
                                sb().table("assets").insert({
                                    "symbol": sym, "name": name,
                                    "asset_class": "Equity", "sub_class": "",
                                    "exchange": "NSE", "is_active": True, "unit_type": "shares",
                                }).execute()
                                new_count += 1
                        except Exception:
                            pass
                    prog.progress(1.0, text="Done")
                    try: st.cache_data.clear()
                    except: pass
                    st.success(
                        f"✅ {count:,} prices updated for {price_date}. "
                        f"{f'{new_count} new tickers registered.' if new_count else 'No new tickers.'}"
                    )

    # ── ETFs ──────────────────────────────────────────────────────────────
    with tab2:
        st.markdown("#### ETF Prices")
        _col_hint(
            "<b>Symbol:</b> <code>symbol, sc_code, trading_symbol, ticker</code><br>"
            "<b>Close/LTP:</b> <code>close, ltp, last_price, closeprice</code><br>"
            "<b>Open/High/Low/Prev Close/Volume</b> same as equities<br>"
            "<span style='color:#F5B731'>New ETF symbols are auto-added to ETF asset class.</span>"
        )
        etf_date = _date_picker("etf_date")
        etf_file = st.file_uploader("Upload CSV / Excel", type=["csv","xlsx","xls"], key="etf_up")
        if etf_file:
            df, err = _read(etf_file)
            if err: st.error(err)
            else:
                df    = _norm(df)
                sym_c = _col(df, "symbol","sc_code","trading_symbol","ticker")
                cl_c  = _col(df, "close","ltp","last_price","closing_price","closeprice")
                st.dataframe(df.head(8), use_container_width=True)
                if sym_c is None or cl_c is None:
                    st.error("❌ Cannot find symbol or close column.")
                elif st.button("⬆️ Upload ETF Prices", use_container_width=True, key="do_etf"):
                    now        = datetime.now().isoformat()
                    price_date = str(etf_date)
                    o_c   = _col(df,"open","open_price")
                    h_c   = _col(df,"high","high_price")
                    lo_c  = _col(df,"low","low_price")
                    pc_c  = _col(df,"prev_close","previous_close","prevclose")
                    vol_c = _col(df,"volume","total_traded_qty","tottrdqty")
                    nm_c  = _col(df,"name","company_name","sc_name")
                    rows  = []
                    new_count = 0
                    for i in range(len(df)):
                        sym = str(sym_c.iloc[i]).strip().upper()
                        cl  = _f(cl_c.iloc[i])
                        if not sym or cl <= 0: continue
                        pc  = _f(pc_c.iloc[i], cl) if pc_c is not None else cl
                        rows.append({
                            "symbol": sym, "price_date": price_date,
                            "open":  _f(o_c.iloc[i],  cl) if o_c  is not None else cl,
                            "high":  _f(h_c.iloc[i],  cl) if h_c  is not None else cl,
                            "low":   _f(lo_c.iloc[i], cl) if lo_c is not None else cl,
                            "close": cl, "prev_close": pc,
                            "change_pct": round(((cl-pc)/pc*100) if pc else 0, 4),
                            "volume": _i(vol_c.iloc[i]) if vol_c is not None else 0,
                            "last_updated": now,
                        })
                        try:
                            ex = sb().table("assets").select("symbol").eq("symbol",sym).execute()
                            if not ex.data:
                                nm = str(nm_c.iloc[i]).strip() if nm_c is not None else sym
                                sb().table("assets").insert({
                                    "symbol":sym,"name":nm,"asset_class":"ETF",
                                    "sub_class":"","exchange":"NSE","is_active":True,"unit_type":"units",
                                }).execute()
                                new_count += 1
                        except Exception: pass
                    with st.spinner(f"Uploading {len(rows):,} rows…"):
                        count = _batch_upsert(rows, "prices", "symbol,price_date")
                    try: st.cache_data.clear()
                    except: pass
                    st.success(f"✅ {count:,} ETF prices updated. {f'{new_count} new tickers added.' if new_count else ''}")

    # ── MF NAVs ───────────────────────────────────────────────────────────
    with tab3:
        st.markdown("#### Mutual Fund NAVs")
        _col_hint(
            "<b>Symbol:</b> <code>symbol, scheme_code, amfi_code</code><br>"
            "<b>NAV:</b> <code>nav, net_asset_value, nav_value</code><br>"
            "<b>Prev NAV (optional):</b> <code>prev_nav, previous_nav</code>"
        )
        mf_date = _date_picker("mf_date")
        mf_file = st.file_uploader("Upload CSV / Excel", type=["csv","xlsx","xls"], key="mf_up")
        if mf_file:
            df, err = _read(mf_file)
            if err: st.error(err)
            else:
                df     = _norm(df)
                sym_c  = _col(df,"symbol","scheme_code","amfi_code")
                nav_c  = _col(df,"nav","net_asset_value","nav_value")
                prev_c = _col(df,"prev_nav","previous_nav")
                st.dataframe(df.head(8), use_container_width=True)
                if sym_c is None or nav_c is None:
                    st.error("❌ Cannot find symbol or NAV column.")
                elif st.button("⬆️ Upload MF NAVs", use_container_width=True, key="do_mf"):
                    now      = datetime.now().isoformat()
                    nav_date = str(mf_date)
                    count = errs = 0
                    prog  = st.progress(0.0)
                    total_r = len(df)
                    for i in range(total_r):
                        sym = str(sym_c.iloc[i]).strip().upper()
                        nav = _f(nav_c.iloc[i])
                        if not sym or nav <= 0: continue
                        try:
                            ex   = sb().table("mutual_funds").select("nav").eq("symbol",sym).execute()
                            prev = _f(prev_c.iloc[i], nav) if prev_c is not None else (
                                   ex.data[0]["nav"] if ex.data else nav)
                            chg  = round(((nav-prev)/prev*100), 4) if prev else 0
                            sb().table("mutual_funds").update({
                                "nav":nav,"prev_nav":prev,"change_pct":chg,
                                "nav_date":nav_date,"last_updated":now,
                            }).eq("symbol",sym).execute()
                            count += 1
                        except: errs += 1
                        if i % 25 == 0: prog.progress(min((i+1)/total_r, 1.0))
                    prog.progress(1.0)
                    try: st.cache_data.clear()
                    except: pass
                    st.success(f"✅ {count} MF NAVs updated. {f'({errs} skipped)' if errs else ''}")

    # ── FD RATES ─────────────────────────────────────────────────────────
    with tab4:
        st.markdown("#### FD Interest Rates")
        _col_hint(
            "<b>Symbol:</b> <code>symbol</code><br>"
            "<b>Rate:</b> <code>interest_rate, rate, fd_rate</code><br>"
            "<b>Tenure (optional):</b> <code>tenure_years, tenure, years</code>"
        )
        fd_file = st.file_uploader("Upload CSV / Excel", type=["csv","xlsx","xls"], key="fd_up")
        if fd_file:
            df, err = _read(fd_file)
            if err: st.error(err)
            else:
                df    = _norm(df)
                sym_c = _col(df,"symbol")
                rt_c  = _col(df,"interest_rate","rate","fd_rate")
                tn_c  = _col(df,"tenure_years","tenure","years")
                st.dataframe(df.head(8), use_container_width=True)
                if sym_c is None or rt_c is None:
                    st.error("❌ Need symbol and interest_rate columns.")
                elif st.button("⬆️ Upload FD Rates", use_container_width=True, key="do_fd"):
                    now   = datetime.now().isoformat()
                    count = 0
                    for i in range(len(df)):
                        sym  = str(sym_c.iloc[i]).strip().upper()
                        rate = _f(rt_c.iloc[i])
                        if not sym or rate <= 0: continue
                        upd  = {"interest_rate":rate,"last_updated":now}
                        if tn_c is not None:
                            t = _f(tn_c.iloc[i])
                            if t > 0: upd["tenure_years"] = t
                        try: sb().table("fixed_income").update(upd).eq("symbol",sym).execute(); count += 1
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
                cur_rate = float(next((f["interest_rate"] for f in fds if f["symbol"]==fd_sym), 0))
                new_rate = st.number_input("New Rate (%)", value=cur_rate, min_value=0.0, step=0.05, format="%.2f")
                if st.form_submit_button("Update", use_container_width=True):
                    sb().table("fixed_income").update({
                        "interest_rate":new_rate,"last_updated":datetime.now().isoformat()
                    }).eq("symbol",fd_sym).execute()
                    try: st.cache_data.clear()
                    except: pass
                    st.success(f"Updated {fd_sym} → {new_rate}%")
            else:
                st.info("No FDs in database.")

    # ── BONDS ─────────────────────────────────────────────────────────────
    with tab5:
        st.markdown("#### Bond Prices & Yields")
        _col_hint(
            "<b>Symbol:</b> <code>symbol, isin</code><br>"
            "<b>Price:</b> <code>current_price, price, close, ltp</code><br>"
            "<b>Yield/Rate (optional):</b> <code>yield, interest_rate, coupon_rate</code>"
        )
        bond_file = st.file_uploader("Upload CSV / Excel", type=["csv","xlsx","xls"], key="bond_up")
        if bond_file:
            df, err = _read(bond_file)
            if err: st.error(err)
            else:
                df      = _norm(df)
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
                        price = _f(price_c.iloc[i])
                        if not sym or price <= 0: continue
                        upd   = {"current_price":price,"last_updated":now}
                        if yield_c is not None:
                            y = _f(yield_c.iloc[i])
                            if y > 0: upd["interest_rate"] = y
                        try: sb().table("fixed_income").update(upd).eq("symbol",sym).execute(); count += 1
                        except: pass
                    try: st.cache_data.clear()
                    except: pass
                    st.success(f"✅ {count} bond prices updated.")

    st.markdown("---")
    if st.button("← Back to Profile"):
        navigate("profile")
