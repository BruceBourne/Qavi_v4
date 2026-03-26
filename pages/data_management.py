import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate
from utils.db import sb, clear_market_cache
from utils.crypto import fmt_date, indian_format
from datetime import date, timedelta

def render():
    if not st.session_state.get("user") or st.session_state.user["role"] not in ("advisor","owner"):
        navigate("login"); return

    st.markdown('<div class="page-title">Data Management</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Storage, historical data cleanup, row counts</div>', unsafe_allow_html=True)

    # ── STORAGE INFO ──────────────────────────────────────────────────────
    st.markdown("""
    <div style="background:#1E2535;border-left:3px solid #F5B731;border-radius:0 8px 8px 0;
        padding:.9rem 1.2rem;margin-bottom:1.2rem">
        <div style="font-size:.8rem;font-weight:600;color:#F5B731;margin-bottom:.4rem">
            Supabase Free Tier Storage Limits
        </div>
        <div style="font-size:.8rem;color:#C8D0E0;line-height:2">
            <b>Database:</b> 500 MB total row storage<br>
            <b>Estimated capacity at current schema:</b><br>
            &nbsp;· Prices table: ~200 bytes/row → <b>~2.5 million price rows</b> before limit<br>
            &nbsp;· Assets table: ~300 bytes/row → <b>~1.6 million asset records</b><br>
            &nbsp;· At 2,500 stocks × 250 trading days/year = 625,000 price rows/year<br>
            &nbsp;· <b>Free tier lasts ~4 years</b> of daily bhavcopy uploads at current scale<br>
            <b>Recommendation:</b> Delete price history older than 1 year to stay well within limits.
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── ROW COUNTS ────────────────────────────────────────────────────────
    tab1, tab2 = st.tabs(["  📊 Row Counts & Storage  ", "  🗑 Delete Historical Data  "])

    with tab1:
        if st.button("🔄 Refresh Counts", use_container_width=False):
            st.rerun()

        tables = ["assets","prices","mutual_funds","fixed_income",
                  "commodities","holdings","invoices","transactions"]
        st.markdown("#### Current Row Counts")
        for tbl in tables:
            try:
                # Use count=exact for accurate count
                r = sb().table(tbl).select("id", count="exact").execute()
                n = r.count if hasattr(r, "count") and r.count is not None else len(r.data or [])
                bar_pct = min(n / 10000 * 100, 100)
                color   = "#2ECC7A" if n < 5000 else "#F5B731" if n < 50000 else "#FF5A5A"
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:.8rem;margin-bottom:.5rem">'
                    f'<div style="width:110px;font-size:.82rem;color:#C8D0E0">{tbl}</div>'
                    f'<div style="flex:1;background:#1E2535;border-radius:4px;height:8px">'
                    f'<div style="background:{color};width:{bar_pct:.1f}%;height:100%;border-radius:4px"></div></div>'
                    f'<div style="width:70px;text-align:right;font-size:.82rem;font-weight:600;color:{color}">'
                    f'{n:,}</div></div>',
                    unsafe_allow_html=True)
            except Exception as e:
                st.caption(f"{tbl}: error — {e}")

        # Prices by date range
        st.markdown(""); st.markdown("#### Price Data Coverage")
        try:
            r = sb().table("prices").select("price_date").order("price_date").limit(1).execute()
            oldest = r.data[0]["price_date"] if r.data else "—"
            r2 = sb().table("prices").select("price_date").order("price_date", desc=True).limit(1).execute()
            newest = r2.data[0]["price_date"] if r2.data else "—"
            st.markdown(f"""
            <div style="background:#161B27;border:1px solid #252D40;border-radius:8px;padding:.8rem 1rem">
                <span style="color:#8892AA;font-size:.8rem">Oldest: </span>
                <span style="font-weight:600">{fmt_date(oldest)}</span>
                &nbsp;&nbsp;
                <span style="color:#8892AA;font-size:.8rem">Newest: </span>
                <span style="font-weight:600">{fmt_date(newest)}</span>
            </div>""", unsafe_allow_html=True)
        except Exception as e:
            st.caption(f"Price range error: {e}")

    with tab2:
        st.markdown("#### Delete Historical Price Data")
        st.markdown("""
        <div style="background:#0F1117;border:1px solid #FF5A5A;border-radius:8px;
            padding:.75rem 1rem;margin-bottom:1rem;font-size:.8rem;color:#C8D0E0">
            ⚠️ Deletion is permanent. Holdings and portfolio data are not affected.
            Only the historical price records are removed. Current prices are preserved.
        </div>
        """, unsafe_allow_html=True)

        one_year_ago = date.today() - timedelta(days=365)
        c1, c2 = st.columns(2)
        del_from = c1.date_input("Delete prices FROM",
                                  value=date(2020, 1, 1),
                                  help="Start of range to delete")
        del_to   = c2.date_input("Delete prices TO",
                                  value=one_year_ago,
                                  help="End of range to delete — recommended: 1 year ago")

        if del_from >= del_to:
            st.error("'From' date must be before 'To' date.")
        else:
            # Preview count
            try:
                r = sb().table("prices").select("id", count="exact")\
                    .gte("price_date", str(del_from))\
                    .lte("price_date", str(del_to)).execute()
                count_to_del = r.count if hasattr(r,"count") and r.count else 0
            except Exception:
                count_to_del = 0

            st.markdown(f"""
            <div style="background:#1E2535;border-radius:8px;padding:.8rem 1rem;margin:.5rem 0">
                <span style="color:#8892AA;font-size:.82rem">Rows in selected range: </span>
                <span style="font-size:.95rem;font-weight:700;color:{'#FF5A5A' if count_to_del > 0 else '#8892AA'}">
                    {count_to_del:,}
                </span>
            </div>""", unsafe_allow_html=True)

            if count_to_del > 0:
                confirm_key = "del_hist_confirm"
                if not st.session_state.get(confirm_key):
                    if st.button(f"🗑 Delete {count_to_del:,} price rows ({fmt_date(str(del_from))} to {fmt_date(str(del_to))})",
                                 use_container_width=True):
                        st.session_state[confirm_key] = True; st.rerun()
                else:
                    st.error(f"Permanently delete **{count_to_del:,}** price rows between {fmt_date(str(del_from))} and {fmt_date(str(del_to))}?")
                    y, n = st.columns(2)
                    if y.button("Yes, Delete Permanently", use_container_width=True):
                        try:
                            # Delete in batches of 1000 to avoid timeout
                            deleted = 0
                            while True:
                                ids_r = sb().table("prices").select("id")\
                                    .gte("price_date", str(del_from))\
                                    .lte("price_date", str(del_to))\
                                    .limit(1000).execute()
                                ids = [r["id"] for r in (ids_r.data or [])]
                                if not ids: break
                                for chunk_start in range(0, len(ids), 100):
                                    chunk = ids[chunk_start:chunk_start+100]
                                    sb().table("prices").delete().in_("id", chunk).execute()
                                    deleted += len(chunk)
                            clear_market_cache()
                            st.session_state.pop(confirm_key, None)
                            st.success(f"✅ Deleted {deleted:,} price rows."); st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
                    if n.button("Cancel", use_container_width=True):
                        st.session_state.pop(confirm_key, None); st.rerun()
            else:
                st.info("No price rows found in this date range.")
    render_asset_delete_section()


# ── ASSET CLASS DATA DELETE ───────────────────────────────────────────────
# Injected as additional tab — appended to existing render() via a separate function

def render_asset_delete_section():
    """Call this at end of render() to add per-asset-class delete controls."""
    st.markdown(""); st.markdown("#### Delete Market Data by Asset Class")
    st.markdown(
        '<div style="font-size:.79rem;color:#FF5A5A;margin-bottom:.6rem">'
        '⚠️ These actions permanently delete asset and price records. '
        'Holdings in portfolios are NOT deleted — only the market data tables.</div>',
        unsafe_allow_html=True)

    ASSET_CLASSES = [
        ("Equity",       "assets",       "asset_class = 'Equity'",       "prices via assets"),
        ("Mutual Funds", "mutual_funds",  "all rows",                      "mutual_funds table"),
        ("ETF",          "assets",        "asset_class = 'ETF'",          "prices via assets"),
        ("Bonds",        "fixed_income",  "asset_class = 'Bond'",         "fixed_income table"),
        ("Bank FD",      "fixed_income",  "asset_class = 'Bank FD'",      "fixed_income table"),
        ("Commodities",  "commodities",   "all rows",                      "commodities table"),
        ("Crypto",       "assets",        "asset_class = 'Crypto'",       "prices via assets"),
        ("Real Estate",  "assets",        "asset_class = 'Real Estate'",  "assets only"),
        ("Physical Gold","assets",        "asset_class = 'Physical Gold'","assets only"),
    ]

    for ac_label, table, condition, note in ASSET_CLASSES:
        with st.expander(f"🗑 Delete {ac_label} data"):
            st.caption(f"Affects: {note} · Condition: {condition}")

            # Count rows
            try:
                if table == "assets":
                    cls = ac_label if ac_label not in ("Crypto","Real Estate","Physical Gold") else ac_label
                    cnt_r = sb().table("assets").select("id", count="exact")\
                                .eq("asset_class", cls).execute()
                    count = cnt_r.count or 0
                elif table == "mutual_funds":
                    cnt_r = sb().table("mutual_funds").select("id", count="exact").execute()
                    count = cnt_r.count or 0
                elif table == "fixed_income":
                    ac_map = {"Bonds":"Bond","Bank FD":"Bank FD"}
                    cnt_r = sb().table("fixed_income").select("id", count="exact")\
                                .eq("asset_class", ac_map.get(ac_label, ac_label)).execute()
                    count = cnt_r.count or 0
                elif table == "commodities":
                    cnt_r = sb().table("commodities").select("id", count="exact").execute()
                    count = cnt_r.count or 0
                else:
                    count = 0
            except Exception:
                count = 0

            also_prices = table == "assets" and ac_label in ("Equity","ETF","Crypto")
            price_note  = " (+ all associated price records)" if also_prices else ""
            st.markdown(
                f"<b>{count:,}</b> records found{price_note}",
                unsafe_allow_html=True)

            confirm_key = f"confirm_del_{ac_label.replace(' ','_')}"
            if st.button(f"Delete all {ac_label} data", key=f"del_btn_{ac_label}",
                         use_container_width=True):
                st.session_state[confirm_key] = True; st.rerun()

            if st.session_state.get(confirm_key):
                st.error(f"Delete ALL {ac_label} data permanently?")
                cy, cn = st.columns(2)
                if cy.button("Yes, delete", key=f"yes_{ac_label}", use_container_width=True):
                    try:
                        if table == "assets":
                            # Get symbols first, then delete prices, then assets
                            syms_r = sb().table("assets").select("symbol")\
                                         .eq("asset_class", ac_label).execute().data or []
                            syms   = [r["symbol"] for r in syms_r]
                            if syms and also_prices:
                                # Delete prices in batches
                                for i in range(0, len(syms), 500):
                                    sb().table("prices").delete()\
                                        .in_("symbol", syms[i:i+500]).execute()
                            sb().table("assets").delete()\
                                .eq("asset_class", ac_label).execute()
                        elif table == "mutual_funds":
                            sb().table("mutual_funds").delete()\
                                .neq("id", "00000000-0000-0000-0000-000000000000")\
                                .execute()
                        elif table == "fixed_income":
                            ac_map = {"Bonds":"Bond","Bank FD":"Bank FD"}
                            sb().table("fixed_income").delete()\
                                .eq("asset_class", ac_map.get(ac_label, ac_label)).execute()
                        elif table == "commodities":
                            sb().table("commodities").delete()\
                                .neq("id","00000000-0000-0000-0000-000000000000").execute()
                        clear_market_cache()
                        st.session_state.pop(confirm_key, None)
                        st.success(f"✅ {ac_label} data deleted.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
                if cn.button("Cancel", key=f"no_{ac_label}", use_container_width=True):
                    st.session_state.pop(confirm_key, None); st.rerun()
