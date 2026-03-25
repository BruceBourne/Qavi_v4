import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate, back_button
from utils.db import sb, clear_market_cache, get_all_advisors, delete_user_account, decrypt_user
from utils.crypto import fmt_date, title_case, indian_format
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
_IST = ZoneInfo("Asia/Kolkata")
from collections import defaultdict

def _is_owner():
    u = st.session_state.get("user", {})
    return u.get("role") == "owner"

def _get_feedback(status_filter=None):
    q = sb().table("feedback").select("*").order("created_at", desc=True)
    if status_filter and status_filter != "all":
        q = q.eq("status", status_filter)
    return q.limit(200).execute().data or []

def _get_all_users():
    data = []
    page = 0
    while True:
        batch = (sb().table("users")
                 .select("id,email,full_name,role,is_active,created_at,last_login,phone_enc,dob,risk_profile")
                 .order("created_at", desc=True)
                 .range(page * 1000, (page + 1) * 1000 - 1)
                 .execute().data or [])
        data.extend(batch)
        if len(batch) < 1000:
            break
        page += 1
    return data

def _get_table_count(tbl):
    try:
        r = sb().table(tbl).select("id", count="exact").execute()
        return r.count if hasattr(r, "count") and r.count else len(r.data or [])
    except Exception:
        return 0

def _get_platform_stats(all_users):
    """Derive activity stats from users + DB counts."""
    now = datetime.now(_IST)

    total        = len(all_users)
    active_count = sum(1 for u in all_users if u.get("is_active", True))
    roles        = defaultdict(int)
    for u in all_users:
        roles[u.get("role", "unknown")] += 1

    # New users this month
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    new_this_month = sum(
        1 for u in all_users
        if u.get("created_at") and u["created_at"][:7] == now.strftime("%Y-%m")
    )

    # Login hour distribution (preferred login time)
    hour_counts = defaultdict(int)
    for u in all_users:
        ll = u.get("last_login")
        if ll:
            try:
                dt = datetime.fromisoformat(ll.replace("Z", "+00:00")).astimezone(_IST)
                hour_counts[dt.hour] += 1
            except Exception:
                pass

    # Users active in last 7 / 30 days
    cutoff_7  = (now - timedelta(days=7)).isoformat()
    cutoff_30 = (now - timedelta(days=30)).isoformat()
    active_7d  = sum(1 for u in all_users
                     if u.get("last_login") and u["last_login"] >= cutoff_7)
    active_30d = sum(1 for u in all_users
                     if u.get("last_login") and u["last_login"] >= cutoff_30)

    # User growth by month (last 6 months)
    month_growth = defaultdict(int)
    for u in all_users:
        ca = u.get("created_at", "")
        if ca:
            month_growth[ca[:7]] += 1

    return {
        "total": total,
        "active": active_count,
        "roles": dict(roles),
        "new_this_month": new_this_month,
        "active_7d": active_7d,
        "active_30d": active_30d,
        "hour_counts": dict(hour_counts),
        "month_growth": dict(sorted(month_growth.items())[-6:]),
    }

def _bar(label, value, max_val, color="#4F7EFF", width_px=260):
    pct = int(value / max(max_val, 1) * 100)
    return (
        f'<div style="display:flex;align-items:center;gap:.6rem;margin:.25rem 0">'
        f'<div style="font-size:.78rem;color:#C8D0E0;width:60px;text-align:right">{label}</div>'
        f'<div style="flex:1;background:#1A2030;border-radius:4px;height:14px;max-width:{width_px}px">'
        f'<div style="width:{pct}%;background:{color};height:14px;border-radius:4px"></div></div>'
        f'<div style="font-size:.78rem;color:#8892AA;min-width:28px">{value}</div>'
        f'</div>'
    )

def _metric(label, value, sub=None, color="#C8D0E0"):
    sub_html = f'<div style="font-size:.72rem;color:#8892AA;margin-top:.15rem">{sub}</div>' if sub else ""
    return (
        f'<div style="background:#161B27;border:1px solid #252D40;border-radius:10px;'
        f'padding:.9rem 1.1rem">'
        f'<div style="font-size:.7rem;color:#8892AA;text-transform:uppercase;letter-spacing:.07em">{label}</div>'
        f'<div style="font-size:1.5rem;font-weight:700;color:{color};margin-top:.25rem">{value}</div>'
        f'{sub_html}</div>'
    )

def render():
    if not _is_owner():
        navigate("login"); return

    back_button(fallback="profile", key="top")

    user = st.session_state.user
    st.markdown('<div class="page-title">👑 Owner Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Platform administration · Activity · Users · Data · Config</div>', unsafe_allow_html=True)

    tabs = st.tabs(["  📊 Activity  ", "  👥 Users  ", "  💬 Feedback  ",
                    "  🗄 Data Tools  ", "  ⚙️ Platform  "])
    t_act, t_usr, t_fb, t_data, t_plat = tabs

    # ── ACTIVITY ──────────────────────────────────────────────────────────
    with t_act:
        all_users = _get_all_users()
        stats     = _get_platform_stats(all_users)

        # Top row counts
        portfolios_n  = _get_table_count("portfolios")
        holdings_n    = _get_table_count("holdings")
        invoices_n    = _get_table_count("invoices")
        assets_n      = _get_table_count("assets")
        prices_n      = _get_table_count("prices")
        feedback_n    = _get_table_count("feedback")

        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(_metric("Total Users",    stats["total"],
                             f"{stats['roles'].get('advisor',0)} advisors · "
                             f"{stats['roles'].get('client',0)} clients"), unsafe_allow_html=True)
        c2.markdown(_metric("Active (30d)",   stats["active_30d"],
                             f"{stats['active_7d']} in last 7 days", "#2ECC7A"), unsafe_allow_html=True)
        c3.markdown(_metric("Portfolios",     f"{portfolios_n:,}",
                             f"{holdings_n:,} holdings"), unsafe_allow_html=True)
        c4.markdown(_metric("New This Month", stats["new_this_month"],
                             f"{stats['active']} accounts active", "#F5B731"), unsafe_allow_html=True)

        st.markdown("")
        c5, c6, c7, c8 = st.columns(4)
        c5.markdown(_metric("Stocks in DB",  f"{assets_n:,}"),    unsafe_allow_html=True)
        c6.markdown(_metric("Price Records", f"{prices_n:,}"),    unsafe_allow_html=True)
        c7.markdown(_metric("Invoices",      f"{invoices_n:,}"),  unsafe_allow_html=True)
        c8.markdown(_metric("Open Feedback", f"{feedback_n:,}"),  unsafe_allow_html=True)

        st.markdown("")
        left, right = st.columns(2)

        # Preferred login time — hour distribution
        with left:
            st.markdown("**Preferred Login Hours** *(IST)*")
            hc = stats["hour_counts"]
            if hc:
                max_h = max(hc.values()) if hc else 1
                # Show all 24h, group into readable labels
                st.markdown(
                    '<div style="background:#0F1117;border:1px solid #252D40;'
                    'border-radius:10px;padding:.9rem 1.1rem">',
                    unsafe_allow_html=True
                )
                for hour in range(24):
                    count = hc.get(hour, 0)
                    if count == 0:
                        continue
                    label = f"{hour:02d}:00"
                    st.markdown(_bar(label, count, max_h, "#4F7EFF"), unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)
            else:
                st.info("No login data yet — populates as users sign in.")

        # User growth by month
        with right:
            st.markdown("**New Users by Month** *(last 6 months)*")
            mg = stats["month_growth"]
            if mg:
                max_m = max(mg.values()) if mg else 1
                st.markdown(
                    '<div style="background:#0F1117;border:1px solid #252D40;'
                    'border-radius:10px;padding:.9rem 1.1rem">',
                    unsafe_allow_html=True
                )
                for month, count in mg.items():
                    try:
                        label = datetime.strptime(month, "%Y-%m").strftime("%b %Y")
                    except Exception:
                        label = month
                    st.markdown(_bar(label, count, max_m, "#2ECC7A", 220), unsafe_allow_html=True)
                st.markdown('</div>', unsafe_allow_html=True)
            else:
                st.info("No growth data yet.")

        # Role breakdown
        st.markdown("**User Roles**")
        rc = stats["roles"]
        ROLE_COLORS = {"owner": "#E84142", "advisor": "#4F7EFF", "client": "#2ECC7A"}
        max_r = max(rc.values()) if rc else 1
        st.markdown(
            '<div style="background:#0F1117;border:1px solid #252D40;'
            'border-radius:10px;padding:.9rem 1.1rem;display:inline-block;min-width:320px">',
            unsafe_allow_html=True
        )
        for role, count in sorted(rc.items(), key=lambda x: -x[1]):
            st.markdown(_bar(role.capitalize(), count, max_r,
                             ROLE_COLORS.get(role, "#8892AA"), 200), unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # Quick links
        st.markdown("")
        b1, b2, b3, b4 = st.columns(4)
        if b1.button("📊 Market Upload",   use_container_width=True): navigate("market_upload")
        if b2.button("🔍 Stock Enrichment", use_container_width=True): navigate("stock_enrichment")
        if b3.button("🗄 Data Mgmt",        use_container_width=True): navigate("data_management")
        if b4.button("📋 RPC Setup", use_container_width=True):
            st.info("Run rpc_functions.sql in Supabase SQL Editor to set up server-side calculations.")

    # ── USERS ─────────────────────────────────────────────────────────────
    with t_usr:
        st.markdown("#### All Platform Users")
        all_users_tab = _get_all_users()

        c_role, c_search = st.columns([1, 2])
        role_filter = c_role.selectbox("Role", ["all", "owner", "advisor", "client"], key="usr_role")
        search_u    = c_search.text_input("Search name or email", key="usr_search")

        shown = [u for u in all_users_tab
                 if (role_filter == "all" or u["role"] == role_filter)
                 and (not search_u
                      or search_u.lower() in u.get("email", "").lower()
                      or search_u.lower() in (u.get("full_name", "") or "").lower())]

        st.caption(f"{len(shown)} users")

        ROLE_COLORS = {"owner": "#E84142", "advisor": "#4F7EFF", "client": "#2ECC7A"}

        for u in shown[:150]:
            role_val   = u["role"]
            role_color = ROLE_COLORS.get(role_val, "#8892AA")
            active     = u.get("is_active", True)
            last_login = u.get("last_login", "")
            ll_fmt     = last_login[:10] if last_login else "Never"

            with st.expander(
                f"{title_case(u.get('full_name',''))}  ·  {u.get('email','')}  "
                f"·  {role_val.upper()}  ·  Last login: {ll_fmt}"
            ):
                # Profile details
                dc1, dc2, dc3 = st.columns(3)
                dc1.markdown(
                    f"<div style='font-size:.78rem;color:#8892AA'>Joined</div>"
                    f"<div style='font-size:.84rem'>{fmt_date(str(u.get('created_at',''))[:10])}</div>",
                    unsafe_allow_html=True)
                dc2.markdown(
                    f"<div style='font-size:.78rem;color:#8892AA'>Status</div>"
                    f"<div style='color:{'#2ECC7A' if active else '#FF5A5A'};font-size:.84rem;font-weight:600'>"
                    f"{'✓ Active' if active else '✗ Inactive'}</div>",
                    unsafe_allow_html=True)
                dc3.markdown(
                    f"<div style='font-size:.78rem;color:#8892AA'>Role</div>"
                    f"<div style='color:{role_color};font-weight:600;font-size:.84rem'>{role_val.upper()}</div>",
                    unsafe_allow_html=True)

                # Risk profile & DOB if available
                if u.get("risk_profile") or u.get("dob"):
                    dc4, dc5 = st.columns(2)
                    if u.get("risk_profile"):
                        dc4.markdown(
                            f"<div style='font-size:.78rem;color:#8892AA'>Risk Profile</div>"
                            f"<div style='font-size:.84rem'>{u['risk_profile']}</div>",
                            unsafe_allow_html=True)
                    if u.get("dob"):
                        dc5.markdown(
                            f"<div style='font-size:.78rem;color:#8892AA'>DOB</div>"
                            f"<div style='font-size:.84rem'>{u['dob']}</div>",
                            unsafe_allow_html=True)

                st.markdown("")

                # Actions row
                if u["id"] != user["id"]:
                    ac1, ac2, ac3 = st.columns(3)

                    # Toggle active
                    toggle_label = "✗ Deactivate" if active else "✓ Activate"
                    if ac1.button(toggle_label, key=f"tog_{u['id']}", use_container_width=True):
                        sb().table("users").update({"is_active": not active}).eq("id", u["id"]).execute()
                        st.rerun()

                    # Change role (not for other owners)
                    if role_val != "owner":
                        new_role = "advisor" if role_val == "client" else "client"
                        if ac2.button(f"→ Make {new_role.capitalize()}",
                                      key=f"role_{u['id']}", use_container_width=True):
                            sb().table("users").update({"role": new_role}).eq("id", u["id"]).execute()
                            st.rerun()
                    else:
                        ac2.empty()

                    # Delete with confirmation
                    confirm_key = f"_confirm_del_user_{u['id']}"
                    if not st.session_state.get(confirm_key):
                        if ac3.button("🗑 Delete", key=f"del_{u['id']}", use_container_width=True):
                            st.session_state[confirm_key] = True
                            st.rerun()
                    else:
                        st.error(
                            f"⚠️ Delete **{u.get('full_name','this user')}** "
                            f"and ALL their data? This cannot be undone."
                        )
                        cy, cn = st.columns(2)
                        if cy.button("Yes, Delete", key=f"yes_del_{u['id']}", use_container_width=True):
                            delete_user_account(u["id"])
                            st.session_state.pop(confirm_key, None)
                            st.success("User deleted.")
                            st.rerun()
                        if cn.button("Cancel", key=f"no_del_{u['id']}", use_container_width=True):
                            st.session_state.pop(confirm_key, None)
                            st.rerun()
                else:
                    st.caption("This is your account — cannot modify self.")

            st.markdown('<hr class="divider"/>', unsafe_allow_html=True)

        if len(shown) > 150:
            st.caption(f"Showing first 150 of {len(shown)}. Use search to narrow.")

    # ── FEEDBACK ──────────────────────────────────────────────────────────
    with t_fb:
        st.markdown("#### Client Feedback & Issues")
        f_filter = st.selectbox("Status", ["open", "acknowledged", "resolved", "all"], key="fb_fil")
        feedback  = _get_feedback(f_filter)

        if not feedback:
            st.info("No feedback in this category.")
        else:
            CAT_COLORS = {"bug": "#FF5A5A", "access": "#F5B731",
                          "unexpected": "#A855F7", "general": "#4F7EFF"}
            ST_COLORS  = {"open": "#FF5A5A", "acknowledged": "#F5B731", "resolved": "#2ECC7A"}

            for fb in feedback:
                sc = ST_COLORS.get(fb["status"], "#8892AA")
                cc = CAT_COLORS.get(fb["category"], "#8892AA")
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
                    b1, b2, b3 = st.columns(3)
                    if b1.button("✓ Acknowledge", key=f"ack_{fb['id']}", use_container_width=True):
                        sb().table("feedback").update({"status": "acknowledged"}).eq("id", fb["id"]).execute()
                        st.rerun()
                    if b2.button("✅ Resolve", key=f"res_{fb['id']}", use_container_width=True):
                        sb().table("feedback").update({"status": "resolved"}).eq("id", fb["id"]).execute()
                        st.rerun()
                    if b3.button("🗑 Delete", key=f"del_fb_{fb['id']}", use_container_width=True):
                        sb().table("feedback").delete().eq("id", fb["id"]).execute()
                        st.rerun()

    # ── DATA TOOLS ────────────────────────────────────────────────────────
    with t_data:
        st.markdown("#### Platform Data Tools")
        st.caption("All actions below affect ALL advisors and clients on the platform.")

        with st.expander("🗑 Delete Advisor & All Their Data"):
            advisors_list = get_all_advisors()
            if advisors_list:
                adv_sel = st.selectbox(
                    "Select Advisor to delete",
                    [a["id"] for a in advisors_list],
                    format_func=lambda x: next(
                        f"{a.get('full_name','?')} ({a['email']})"
                        for a in advisors_list if a["id"] == x))
                st.error("⚠️ This deletes the advisor and ALL their clients, portfolios, holdings, invoices.")
                if st.button("Delete Advisor Account", use_container_width=True, key="del_adv"):
                    st.session_state["confirm_del_adv"] = adv_sel
                    st.rerun()
                if st.session_state.get("confirm_del_adv") == adv_sel:
                    st.error("Are you absolutely sure? This cannot be undone.")
                    y, n = st.columns(2)
                    if y.button("Yes, Delete", use_container_width=True, key="yes_del_adv"):
                        sb().table("users").delete().eq("id", adv_sel).execute()
                        st.session_state.pop("confirm_del_adv", None)
                        st.success("Advisor deleted.")
                        st.rerun()
                    if n.button("Cancel", use_container_width=True, key="no_del_adv"):
                        st.session_state.pop("confirm_del_adv", None)
                        st.rerun()

        with st.expander("🔄 Clear All Market Cache"):
            st.caption("Forces all market data to refresh from database on next page load.")
            if st.button("Clear Cache", use_container_width=True, key="clr_cache"):
                clear_market_cache()
                st.success("Cache cleared.")

        with st.expander("📊 Bulk Sub-Class Fix"):
            st.caption("Sets all assets with empty sub_class to 'Unclassified'.")
            if st.button("Run Fix", use_container_width=True, key="fix_sub"):
                try:
                    sb().table("assets").update({"sub_class": "Unclassified"}) \
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

        st.markdown("")
        st.markdown("#### Supabase RLS Notice")
        st.info(
            "If Supabase flags **rls_disabled_in_public** on your tables, enable Row Level Security "
            "on each table in your Supabase dashboard: **Table Editor → [table] → RLS → Enable**. "
            "Then add a policy allowing authenticated users to read/write their own rows. "
            "This is a Supabase project setting — no changes are needed in this app."
        )


    st.markdown("<br>", unsafe_allow_html=True)
    back_button(fallback="profile", label="← Back", key="bot")
