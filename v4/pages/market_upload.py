import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate
from utils.db import upsert_prices_from_df, upsert_navs_from_df
from utils.crypto import hash_advisor_key, fmt_date
from utils.db import get_advisor_key_hash
from datetime import date
import io

def render():
    if not st.session_state.get("user") or st.session_state.user["role"] != "advisor":
        navigate("login"); return

    st.markdown('<div class="page-title">Market Data Upload</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Upload CSV or Excel to update equity prices or MF NAVs</div>', unsafe_allow_html=True)

    # Gate with upload key
    if not st.session_state.get("_upload_auth"):
        st.markdown("""
        <div style="background:#1E2535;border:1px solid #F5B731;border-radius:12px;padding:1.4rem;max-width:420px">
            <div style="font-size:.8rem;color:#F5B731;font-weight:600;margin-bottom:.6rem">🔐 Upload Key Required</div>
            <div style="font-size:.82rem;color:#8892AA">This area requires the advisor authorization key to prevent accidental data overwrites.</div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        key_in = st.text_input("Enter Advisor Authorization Key", type="password")
        if st.button("Unlock", use_container_width=False):
            if hash_advisor_key(key_in) == get_advisor_key_hash():
                st.session_state["_upload_auth"] = True
                st.rerun()
            else:
                st.error("Incorrect key.")
        return

    st.success("✅ Authenticated. Upload access granted.")
    st.markdown("<br>", unsafe_allow_html=True)

    tab1, tab2 = st.tabs(["  📈 Equity / ETF Prices  ", "  🏦 Mutual Fund NAVs  "])

    with tab1:
        st.markdown("#### Upload Equity or ETF Prices")
        st.markdown("""
        <div style="background:#161B27;border:1px solid #252D40;border-radius:10px;padding:1rem 1.2rem;margin-bottom:1rem">
            <div style="font-size:.75rem;color:#8892AA;font-weight:600;margin-bottom:.5rem">Required CSV columns</div>
            <div style="font-size:.82rem;color:#C8D0E0"><code>symbol, close</code></div>
            <div style="font-size:.78rem;color:#8892AA;margin-top:.4rem">
                Optional: <code>open, high, low, prev_close, change_pct, volume</code><br>
                Symbol must match NSE ticker (e.g. RELIANCE, TCS, HDFCBANK)<br>
                Prices should be in ₹. One row per symbol.
            </div>
        </div>
        """, unsafe_allow_html=True)

        eq_file = st.file_uploader("Upload CSV or Excel", type=["csv","xlsx","xls"], key="eq_upload")
        if eq_file:
            try:
                import pandas as pd
                if eq_file.name.endswith(".csv"):
                    df = pd.read_csv(eq_file)
                else:
                    df = pd.read_excel(eq_file)

                df.columns = [c.strip().lower().replace(" ","_") for c in df.columns]
                st.markdown(f"**Preview** — {len(df)} rows")
                st.dataframe(df.head(10), use_container_width=True)

                if st.button("⬆️ Upload & Update Prices", use_container_width=True, key="do_eq_upload"):
                    count = upsert_prices_from_df(df)
                    st.success(f"✅ Updated prices for {count} symbols. Data is now live.")
            except Exception as e:
                st.error(f"Error reading file: {e}")

    with tab2:
        st.markdown("#### Upload Mutual Fund NAVs")
        st.markdown("""
        <div style="background:#161B27;border:1px solid #252D40;border-radius:10px;padding:1rem 1.2rem;margin-bottom:1rem">
            <div style="font-size:.75rem;color:#8892AA;font-weight:600;margin-bottom:.5rem">Required CSV columns</div>
            <div style="font-size:.82rem;color:#C8D0E0"><code>symbol, nav</code></div>
            <div style="font-size:.78rem;color:#8892AA;margin-top:.4rem">
                Optional: <code>prev_nav, change_pct</code><br>
                Symbol must match exactly as stored in Qavi (e.g. HDFC_TOP100, SBI_BLUECHIP)<br>
                NAV should be in ₹.
            </div>
        </div>
        """, unsafe_allow_html=True)

        mf_file = st.file_uploader("Upload CSV or Excel", type=["csv","xlsx","xls"], key="mf_upload")
        if mf_file:
            try:
                import pandas as pd
                if mf_file.name.endswith(".csv"):
                    df = pd.read_csv(mf_file)
                else:
                    df = pd.read_excel(mf_file)

                df.columns = [c.strip().lower().replace(" ","_") for c in df.columns]
                st.markdown(f"**Preview** — {len(df)} rows")
                st.dataframe(df.head(10), use_container_width=True)

                if st.button("⬆️ Upload & Update NAVs", use_container_width=True, key="do_mf_upload"):
                    count = upsert_navs_from_df(df)
                    st.success(f"✅ Updated NAVs for {count} funds. Data is now live.")
            except Exception as e:
                st.error(f"Error reading file: {e}")

    st.markdown("---")
    st.markdown(f'<p style="font-size:.75rem;color:#4E5A70">Today: {fmt_date(str(date.today()))}</p>', unsafe_allow_html=True)
    if st.button("🔒 Lock Upload Area"):
        st.session_state.pop("_upload_auth", None); st.rerun()
