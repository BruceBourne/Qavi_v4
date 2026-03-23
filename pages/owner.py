import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate
from utils.db import sb, clear_market_cache, get_all_advisors
from utils.crypto import fmt_date, title_case, indian_format
from datetime import datetime

def _is_owner():
    u = st.session_state.get("user",{})
    return u.get("role") == "owner"

def _get_feedback(status_filter=None):
    q = sb().table("feedback").select("*").order("created_at", desc=True)
    if status_filter and status_filter != "all":
        q = q.eq("status", status_filter)
    return q.limit(200).execute().data or []

def _get_users():
    data = []
    page = 0
    while True:
        batch = sb().table("users").select(
            "id,email,full_name,role,is_active,created_at"
        ).order("created_at", desc=True).range(page*1000,(page+1)*1000-1).execute().data or []
        data.extend(batch)
        if len(batch) < 1000: break
        page += 1
    return data

def _get_stats():
    stats = {}
    for tbl in ["users","advisor_clients","portfolios","holdings","invoices","prices","assets","feedback"]:
        try:
            r = sb().table(tbl).select("id", count="exact").execute()
            stats[tbl] = r.count if hasattr(r,"count") and r.count else len(r.data or [])
        except Exception:
            stats[tbl] = "—"
    return stats

def render():
    if not _is_owner():
        navigate("login"); return

    user = st.session_state.user
    st.markdown('<div class="page-title">👑 Owner Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Platform administration · Data · Users · Feedback</div>',
                unsafe_allow_html=True)

    tabs = st.tabs(["  📊 Overview  ","  👥 Users  ","  💬 Feedback  ",
                     "  🗄 Data Tools  ","  ⚙️ Platform  "])
    t_ov, t_usr, t_fb, t_data, t_plat = tabs

    # ── OVERVIEW ──────────────────────────────────────────────────────────
    with t_ov:
        stats = _get_stats()
        advisors = stats.get("users","—")

        cols = st.columns(4)
        for col, (lbl, key) in zip(cols, [
            ("Total Users","users"),("Portfolios","portfolios"),
            ("Holdings","holdings"),("Invoices","invoices")
        ]):
            col.metric(lbl, f"{stats.get(key,'—'):,}" if isinstance(stats.get(key),int) else "—")

        st.markdown("<br>", unsafe_allow_html=True)
        cols2 = st.columns(4)
        for col, (lbl, key) in zip(cols2, [
            ("Stocks in DB","assets"),("Price Records","prices"),
            ("Open Feedback","feedback"),("Clients","advisor_clients")
        ]):
            v = stats.get(key,"—")
            col.metric(lbl, f"{v:,}" if isinstance(v,int) else "—")

        # Quick links
        st.markdown("")
        b1,b2,b3,b4 = st.columns(4)
        if b1.button("📊 Market Upload",  use_container_width=True): navigate("market_upload")
        if b2.button("🔍 Stock Enrichment",use_container_width=True): navigate("stock_enrichment")
        if b3.button("🗄 Data Mgmt",      use_container_width=True): navigate("data_management")
        if b4.button("📋 Rpc Setup",       use_container_width=True):
            st.info("Run rpc_functions.sql in Supabase SQL Editor to set up server-side calculations.")

    # ── USERS ─────────────────────────────────────────────────────────────
    with t_usr:
        st.markdown("#### All Platform Users")
        users = _get_users()
        role_filter = st.selectbox("Filter by role", ["all","owner","advisor","client"])
        search_u    = st.text_input("Search name or email", key="usr_search")

        shown = [u for u in users
                 if (role_filter == "all" or u["role"] == role_filter)
                 and (not search_u or search_u.lower() in u.get("email","").lower()
                      or search_u.lower() in (u.get("full_name","") or "").lower())]

        st.caption(f"{len(shown)} users")
        hdr = st.columns([3,2,1.5,1.5,1])
        for col,lbl in zip(hdr,["Name / Email","Role","Joined","Active",""]):
            col.markdown(f"<div style='font-size:.7rem;color:#8892AA;font-weight:600'>{lbl}</div>",
                         unsafe_allow_html=True)
        st.markdown('<hr class="divider"/>', unsafe_allow_html=True)

        ROLE_COLORS = {"owner":"#E84142","advisor":"#4F7EFF","client":"#2ECC7A"}
        for u in shown[:100]:
            rc = st.columns([3,2,1.5,1.5,1])
            rc[0].markdown(
                f"<div style='font-weight:600;font-size:.85rem'>{title_case(u.get('full_name',''))}</div>"
                f"<div style='font-size:.73rem;color:#8892AA'>{u.get('email','')}</div>",
                unsafe_allow_html=True)
            role_val   = u["role"]
            role_color = ROLE_COLORS.get(role_val, "#8892AA")
            rc[1].markdown(
                f"<span style='color:{role_color};font-weight:600;font-size:.82rem'>"
                f"{role_val.upper()}</span>", unsafe_allow_html=True)
            rc[2].markdown(
                f"<div style='font-size:.79rem;color:#8892AA'>"
                f"{fmt_date(str(u.get('created_at',''))[:10])}</div>",
                unsafe_allow_html=True)
            active = u.get("is_active", True)
            rc[3].markdown(
                f"<span style='color:{'#2ECC7A' if active else '#FF5A5A'};font-size:.82rem'>"
                f"{'✓ Active' if active else '✗ Inactive'}</span>", unsafe_allow_html=True)

            # Toggle active status (not self)
            if u["id"] != user["id"]:
                if rc[4].button("Toggle", key=f"tog_{u['id']}", use_container_width=True):
                    sb().table("users").update({"is_active": not active}).eq("id",u["id"]).execute()
                    st.rerun()
            st.markdown('<hr class="divider"/>', unsafe_allow_html=True)

        if len(shown) > 100:
            st.caption(f"Showing first 100 of {len(shown)}. Use search to narrow.")

    # ── FEEDBACK ──────────────────────────────────────────────────────────
    with t_fb:
        st.markdown("#### Client Feedback & Issues")
        f_filter = st.selectbox("Status", ["open","acknowledged","resolved","all"], key="fb_fil")
        feedback  = _get_feedback(f_filter)

        if not feedback:
            st.info("No feedback in this category.")
        else:
            CAT_COLORS = {"bug":"#FF5A5A","access":"#F5B731",
                          "unexpected":"#A855F7","general":"#4F7EFF"}
            ST_COLORS  = {"open":"#FF5A5A","acknowledged":"#F5B731","resolved":"#2ECC7A"}

            for fb in feedback:
                sc = ST_COLORS.get(fb["status"],"#8892AA")
                cc = CAT_COLORS.get(fb["category"],"#8892AA")
                with st.expander(
                    f"[{fb['category'].upper()}]  {fb.get('user_name','Anonymous')}"
                    f"  ·  {fmt_date(str(fb.get('created_at',''))[:10])}"
                    f"  ·  {fb['status'].upper()}"
                ):
                    st.markdown(
                        f"<div style='font-size:.8rem;color:#8892AA'>"
                        f"From: <b>{fb.get('user_name','')} &lt;{fb.get('user_email','')}&gt;</b>"
                        f"  ·  Role: {fb.get('role','')}</div>",
                        unsafe_allow_html=True)
                    st.markdown(
                        f"<div style='background:#0F1117;border-radius:8px;padding:.8rem 1rem;"
                        f"margin:.5rem 0;font-size:.84rem;color:#C8D0E0'>{fb['message']}</div>",
                        unsafe_allow_html=True)
                    b1,b2,b3 = st.columns(3)
                    if b1.button("✓ Acknowledge", key=f"ack_{fb['id']}", use_container_width=True):
                        sb().table("feedback").update({"status":"acknowledged"}).eq("id",fb["id"]).execute()
                        st.rerun()
                    if b2.button("✅ Resolve",    key=f"res_{fb['id']}", use_container_width=True):
                        sb().table("feedback").update({"status":"resolved"}).eq("id",fb["id"]).execute()
                        st.rerun()
                    if b3.button("🗑 Delete",     key=f"del_{fb['id']}", use_container_width=True):
                        sb().table("feedback").delete().eq("id",fb["id"]).execute()
                        st.rerun()

    # ── DATA TOOLS ────────────────────────────────────────────────────────
    with t_data:
        st.markdown("#### Platform Data Tools")
        st.caption("All actions below affect ALL advisors and clients on the platform.")

        with st.expander("🗑 Delete Advisor & All Their Data"):
            advisors_list = get_all_advisors()
            if advisors_list:
                adv_sel = st.selectbox("Select Advisor to delete",
                                       [a["id"] for a in advisors_list],
                                       format_func=lambda x: next(
                                           f"{a.get('full_name','?')} ({a['email']})"
                                           for a in advisors_list if a["id"]==x))
                st.error("⚠️ This deletes the advisor and ALL their clients, portfolios, holdings, invoices.")
                if st.button("Delete Advisor Account", use_container_width=True, key="del_adv"):
                    st.session_state["confirm_del_adv"] = adv_sel; st.rerun()
                if st.session_state.get("confirm_del_adv") == adv_sel:
                    st.error("Are you absolutely sure? This cannot be undone.")
                    y,n = st.columns(2)
                    if y.button("Yes, Delete", use_container_width=True, key="yes_del_adv"):
                        sb().table("users").delete().eq("id",adv_sel).execute()
                        st.session_state.pop("confirm_del_adv",None)
                        st.success("Advisor deleted."); st.rerun()
                    if n.button("Cancel", use_container_width=True, key="no_del_adv"):
                        st.session_state.pop("confirm_del_adv",None); st.rerun()

        with st.expander("🔄 Clear All Market Cache"):
            st.caption("Forces all market data to refresh from database on next page load.")
            if st.button("Clear Cache", use_container_width=True, key="clr_cache"):
                clear_market_cache()
                st.success("Cache cleared.")

        with st.expander("📊 Bulk Sub-Class Fix"):
            st.caption("Sets all assets with empty sub_class to 'Unclassified'.")
            if st.button("Run Fix", use_container_width=True, key="fix_sub"):
                try:
                    sb().table("assets").update({"sub_class":"Unclassified"})\
                        .or_("sub_class.eq.,sub_class.is.null").execute()
                    clear_market_cache()
                    st.success("Done.")
                except Exception as e:
                    st.error(str(e))

    # ── PLATFORM ──────────────────────────────────────────────────────────
    with t_plat:
        st.markdown("#### Platform Configuration")
        st.markdown("""
        <div style="background:#0F1117;border:1px solid #252D40;border-radius:8px;
            padding:.9rem 1.2rem;font-size:.8rem;color:#C8D0E0;line-height:2">
            <b>Streamlit Secrets required (Settings → Secrets in Streamlit Cloud):</b><br>
            <code>SUPABASE_URL</code> = your Supabase project URL<br>
            <code>SUPABASE_KEY</code> = Supabase anon public key<br>
            <code>QAVI_ENCRYPT_KEY</code> = encryption passphrase (32+ chars)<br>
            <code>ADVISOR_KEY_HASH</code> = SHA-256 of advisor auth key<br>
            <code>OWNER_KEY_HASH</code> = SHA-256 of owner key<br>
            <code>EMAIL_HOST</code> = SMTP host e.g. smtp.gmail.com<br>
            <code>EMAIL_PORT</code> = 587<br>
            <code>EMAIL_USER</code> = sender email address<br>
            <code>EMAIL_PASS</code> = app password (not login password)<br>
            <code>FEEDBACK_EMAIL</code> = your email to receive feedback notifications<br>
        </div>
        """, unsafe_allow_html=True)

        st.markdown(""); st.markdown("#### Generate Key Hashes")
        raw_key = st.text_input("Enter a key to hash (for secrets setup)", type="password")
        if raw_key:
            import hashlib
            h = hashlib.sha256(raw_key.encode()).hexdigest()
            st.code(h, language=None)
            st.caption("Copy this into ADVISOR_KEY_HASH or OWNER_KEY_HASH in Streamlit secrets.")
