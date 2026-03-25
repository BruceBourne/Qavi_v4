import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate, back_button
from utils.db import sb, clear_market_cache
from utils.crypto import fmt_date, indian_format
from datetime import date, timedelta

def render():
    if not st.session_state.get("user") or st.session_state.user["role"] not in ("advisor","owner"):
        navigate("login"); return

    back_button(fallback="profile", key="top")

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
    back_button(fallback="profile", label="← Back", key="bot")

