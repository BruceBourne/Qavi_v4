import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate
from utils.db import sb
from utils.crypto import fmt_date, indian_format
from datetime import date, datetime
import pandas as pd

def render():
    if not st.session_state.get("user") or st.session_state.user["role"] != "advisor":
        navigate("login"); return

    st.markdown('<div class="page-title">Market Data Upload</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Update market prices, NAVs, FD rates and bond prices from CSV / Excel</div>', unsafe_allow_html=True)

    tab1, tab2, tab3, tab4 = st.tabs([
        "  📈 Equities & ETFs  ",
        "  🏦 Mutual Fund NAVs  ",
        "  💰 FD Rates  ",
        "  📄 Bonds  ",
    ])

    def _read_file(f):
        try:
            if f.name.lower().endswith(".csv"):
                # Try multiple encodings for bhavcopy files
                for enc in ("utf-8","latin-1","cp1252"):
                    try:
                        f.seek(0)
                        df = pd.read_csv(f, encoding=enc)
                        return df, None
                    except UnicodeDecodeError:
                        continue
                return None, "Could not decode file. Try saving as CSV UTF-8."
            else:
                f.seek(0)
                return pd.read_excel(f), None
        except Exception as e:
            return None, str(e)

    def _norm_cols(df):
        df.columns = [str(c).strip().lower().replace(" ","_").replace("-","_") for c in df.columns]
        return df

    def _col(df, *candidates):
        """Return first matching column value series from list of candidate names."""
        for c in candidates:
            if c in df.columns:
                return df[c]
        return None

    # ── EQUITIES & ETFs ───────────────────────────────────────────────────
    with tab1:
        st.markdown("#### Upload Equity / ETF Prices")
        st.markdown("""
        <div style="background:#0F1117;border:1px solid #252D40;border-radius:10px;padding:1rem 1.2rem;margin-bottom:1rem">
            <div style="font-size:.74rem;color:#8892AA;font-weight:600;margin-bottom:.4rem">Accepted column names (any of these work)</div>
            <div style="font-size:.8rem;color:#C8D0E0;line-height:1.9">
                <b>Symbol:</b> <code>symbol, sc_code, trading_symbol, ticker</code><br>
                <b>Close/LTP:</b> <code>close, ltp, last_price, closing_price, close_price</code><br>
                <b>Open:</b> <code>open, open_price</code>  &nbsp; <b>High:</b> <code>high, high_price</code><br>
                <b>Low:</b> <code>low, low_price</code>  &nbsp; <b>Prev Close:</b> <code>prev_close, previous_close, prevclose</code><br>
                <b>Volume:</b> <code>volume, total_traded_qty, tottrdqty</code>
            </div>
            <div style="font-size:.75rem;color:#4E5A70;margin-top:.5rem">
                NSE Bhavcopy and BSE Bhavcopy formats are supported. One row per symbol.
            </div>
        </div>
        """, unsafe_allow_html=True)

        eq_file = st.file_uploader("Upload file", type=["csv","xlsx","xls"], key="eq_up")
        if eq_file:
            df, err = _read_file(eq_file)
            if err: st.error(err)
            else:
                df = _norm_cols(df)
                st.markdown(f"**{len(df)} rows detected** — Preview:")
                st.dataframe(df.head(8), use_container_width=True)

                if st.button("⬆️ Upload & Update Prices", use_container_width=True, key="do_eq"):
                    now   = datetime.now().isoformat()
                    today = str(date.today())
                    count = errors = 0

                    sym_col  = _col(df, "symbol","sc_code","trading_symbol","ticker","series")
                    cl_col   = _col(df, "close","ltp","last_price","closing_price","close_price","closeprice")
                    o_col    = _col(df, "open","open_price","openprice")
                    h_col    = _col(df, "high","high_price","highprice")
                    l_col    = _col(df, "low","low_price","lowprice")
                    pc_col   = _col(df, "prev_close","previous_close","prevclose","prev_close_price")
                    vol_col  = _col(df, "volume","total_traded_qty","tottrdqty","traded_quantity")
                    chg_col  = _col(df, "change_pct","pchange","net_chng_pct")

                    if sym_col is None or cl_col is None:
                        st.error("Could not find symbol or close/LTP column. Check column names.")
                    else:
                        for i in range(len(df)):
                            try:
                                sym = str(sym_col.iloc[i]).strip().upper()
                                cl  = float(str(cl_col.iloc[i]).replace(",","").strip() or 0)
                                if not sym or cl <= 0: continue
                                pc  = float(str(pc_col.iloc[i]).replace(",","").strip()) if pc_col is not None else cl
                                o   = float(str(o_col.iloc[i]).replace(",","").strip()) if o_col is not None else cl
                                h   = float(str(h_col.iloc[i]).replace(",","").strip()) if h_col is not None else cl
                                lo  = float(str(l_col.iloc[i]).replace(",","").strip()) if l_col is not None else cl
                                chg = float(str(chg_col.iloc[i]).replace(",","").strip()) if chg_col is not None else (((cl-pc)/pc*100) if pc else 0)
                                vol = int(float(str(vol_col.iloc[i]).replace(",","").strip())) if vol_col is not None else 0
                                sb().table("prices").upsert({
                                    "symbol":sym,"price_date":today,
                                    "open":o,"high":h,"low":lo,"close":cl,
                                    "prev_close":pc,"change_pct":round(chg,4),
                                    "volume":vol,"last_updated":now,
                                }, on_conflict="symbol,price_date").execute()
                                count += 1
                            except Exception:
                                errors += 1
                        try: st.cache_data.clear()
                        except: pass
                        st.success(f"✅ Updated {count} symbols. {f'({errors} skipped due to errors)' if errors else ''}")

    # ── MUTUAL FUND NAVs ──────────────────────────────────────────────────
    with tab2:
        st.markdown("#### Upload Mutual Fund NAVs")
        st.markdown("""
        <div style="background:#0F1117;border:1px solid #252D40;border-radius:10px;padding:1rem 1.2rem;margin-bottom:1rem">
            <div style="font-size:.74rem;color:#8892AA;font-weight:600;margin-bottom:.4rem">Accepted column names</div>
            <div style="font-size:.8rem;color:#C8D0E0;line-height:1.9">
                <b>Symbol:</b> <code>symbol, scheme_code, amfi_code</code><br>
                <b>NAV:</b> <code>nav, net_asset_value, nav_value</code><br>
                <b>Prev NAV:</b> <code>prev_nav, previous_nav</code> (optional)
            </div>
        </div>
        """, unsafe_allow_html=True)

        mf_file = st.file_uploader("Upload file", type=["csv","xlsx","xls"], key="mf_up")
        if mf_file:
            df, err = _read_file(mf_file)
            if err: st.error(err)
            else:
                df = _norm_cols(df)
                st.dataframe(df.head(8), use_container_width=True)
                if st.button("⬆️ Upload & Update NAVs", use_container_width=True, key="do_mf"):
                    now   = datetime.now().isoformat()
                    today = str(date.today())
                    count = errors = 0

                    sym_col  = _col(df,"symbol","scheme_code","amfi_code")
                    nav_col  = _col(df,"nav","net_asset_value","nav_value")
                    prev_col = _col(df,"prev_nav","previous_nav")

                    if sym_col is None or nav_col is None:
                        st.error("Could not find symbol or NAV column.")
                    else:
                        for i in range(len(df)):
                            try:
                                sym  = str(sym_col.iloc[i]).strip().upper()
                                nav  = float(str(nav_col.iloc[i]).replace(",","").strip() or 0)
                                if not sym or nav <= 0: continue
                                # Get existing NAV as prev
                                existing = sb().table("mutual_funds").select("nav").eq("symbol",sym).execute()
                                prev     = float(str(prev_col.iloc[i]).replace(",","").strip()) if prev_col is not None else (existing.data[0]["nav"] if existing.data else nav)
                                chg      = round(((nav-prev)/prev*100),4) if prev else 0
                                sb().table("mutual_funds").update({
                                    "nav":nav,"prev_nav":prev,"change_pct":chg,
                                    "nav_date":today,"last_updated":now,
                                }).eq("symbol",sym).execute()
                                count += 1
                            except Exception:
                                errors += 1
                        try: st.cache_data.clear()
                        except: pass
                        st.success(f"✅ Updated {count} funds. {f'({errors} skipped)' if errors else ''}")

    # ── FD RATES ─────────────────────────────────────────────────────────
    with tab3:
        st.markdown("#### Upload / Update FD Interest Rates")
        st.markdown("""
        <div style="background:#0F1117;border:1px solid #252D40;border-radius:10px;padding:1rem 1.2rem;margin-bottom:1rem">
            <div style="font-size:.74rem;color:#8892AA;font-weight:600;margin-bottom:.4rem">Accepted column names</div>
            <div style="font-size:.8rem;color:#C8D0E0;line-height:1.9">
                <b>Symbol:</b> <code>symbol</code>  &nbsp; <b>Rate:</b> <code>interest_rate, rate, fd_rate</code><br>
                <b>Tenure:</b> <code>tenure_years, tenure, years</code> (optional)<br>
                <b>Or update manually below</b>
            </div>
        </div>
        """, unsafe_allow_html=True)

        fd_file = st.file_uploader("Upload file", type=["csv","xlsx","xls"], key="fd_up")
        if fd_file:
            df, err = _read_file(fd_file)
            if err: st.error(err)
            else:
                df = _norm_cols(df)
                st.dataframe(df.head(8), use_container_width=True)
                if st.button("⬆️ Upload & Update FD Rates", use_container_width=True, key="do_fd"):
                    now   = datetime.now().isoformat()
                    count = errors = 0
                    sym_col  = _col(df,"symbol")
                    rate_col = _col(df,"interest_rate","rate","fd_rate")
                    ten_col  = _col(df,"tenure_years","tenure","years")
                    if sym_col is None or rate_col is None:
                        st.error("Need symbol and interest_rate columns.")
                    else:
                        for i in range(len(df)):
                            try:
                                sym  = str(sym_col.iloc[i]).strip().upper()
                                rate = float(str(rate_col.iloc[i]).replace(",","").strip() or 0)
                                if not sym or rate <= 0: continue
                                upd  = {"interest_rate":rate,"last_updated":now}
                                if ten_col is not None:
                                    upd["tenure_years"] = float(str(ten_col.iloc[i]).replace(",",""))
                                sb().table("fixed_income").update(upd).eq("symbol",sym).execute()
                                count += 1
                            except Exception:
                                errors += 1
                        try: st.cache_data.clear()
                        except: pass
                        st.success(f"✅ Updated {count} FD rates.")

        st.markdown("<br>**Or update a single FD rate manually:**")
        with st.form("manual_fd"):
            # Load existing FDs
            try:
                fds = sb().table("fixed_income").select("symbol,name,interest_rate").eq("asset_class","Bank FD").order("symbol").execute().data or []
            except:
                fds = []
            if fds:
                fd_sym  = st.selectbox("FD", [f["symbol"] for f in fds],
                                       format_func=lambda x: f"{x} — {next(f['name'] for f in fds if f['symbol']==x)}")
                new_rate = st.number_input("New Interest Rate (%)", min_value=0.0, step=0.05, format="%.2f",
                                           value=float(next((f["interest_rate"] for f in fds if f["symbol"]==fd_sym),0)))
                if st.form_submit_button("Update Rate", use_container_width=True):
                    sb().table("fixed_income").update({
                        "interest_rate":new_rate,"last_updated":datetime.now().isoformat()
                    }).eq("symbol",fd_sym).execute()
                    try: st.cache_data.clear()
                    except: pass
                    st.success(f"Updated {fd_sym} to {new_rate}%")
            else:
                st.info("No FDs found in database.")

    # ── BONDS ─────────────────────────────────────────────────────────────
    with tab4:
        st.markdown("#### Upload / Update Bond Prices")
        st.markdown("""
        <div style="background:#0F1117;border:1px solid #252D40;border-radius:10px;padding:1rem 1.2rem;margin-bottom:1rem">
            <div style="font-size:.74rem;color:#8892AA;font-weight:600;margin-bottom:.4rem">Accepted column names</div>
            <div style="font-size:.8rem;color:#C8D0E0;line-height:1.9">
                <b>Symbol:</b> <code>symbol, isin</code><br>
                <b>Price:</b> <code>current_price, price, close, ltp</code><br>
                <b>Yield/Rate:</b> <code>yield, interest_rate, coupon_rate</code> (optional)
            </div>
        </div>
        """, unsafe_allow_html=True)

        bond_file = st.file_uploader("Upload file", type=["csv","xlsx","xls"], key="bond_up")
        if bond_file:
            df, err = _read_file(bond_file)
            if err: st.error(err)
            else:
                df = _norm_cols(df)
                st.dataframe(df.head(8), use_container_width=True)
                if st.button("⬆️ Upload & Update Bond Prices", use_container_width=True, key="do_bond"):
                    now   = datetime.now().isoformat()
                    count = errors = 0
                    sym_col    = _col(df,"symbol","isin")
                    price_col  = _col(df,"current_price","price","close","ltp")
                    yield_col  = _col(df,"yield","interest_rate","coupon_rate","rate")
                    if sym_col is None or price_col is None:
                        st.error("Need symbol and price columns.")
                    else:
                        for i in range(len(df)):
                            try:
                                sym   = str(sym_col.iloc[i]).strip().upper()
                                price = float(str(price_col.iloc[i]).replace(",","").strip() or 0)
                                if not sym or price <= 0: continue
                                upd   = {"current_price":price,"last_updated":now}
                                if yield_col is not None:
                                    try: upd["interest_rate"] = float(str(yield_col.iloc[i]).replace(",",""))
                                    except: pass
                                sb().table("fixed_income").update(upd).eq("symbol",sym).execute()
                                count += 1
                            except Exception:
                                errors += 1
                        try: st.cache_data.clear()
                        except: pass
                        st.success(f"✅ Updated {count} bonds. {f'({errors} skipped)' if errors else ''}")

    st.markdown("---")
    if st.button("← Back to Profile"):
        navigate("profile")
