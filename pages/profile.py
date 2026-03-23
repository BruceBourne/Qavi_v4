import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate
from utils.db import update_user_profile, get_user_by_id, decrypt_user, upgrade_to_owner, delete_user_account
from utils.crypto import fmt_date, title_case
import hashlib

def _owner_key_hash():
    try:    return st.secrets["OWNER_KEY_HASH"]
    except: return ""

def render():
    if not st.session_state.get("user"):
        navigate("login"); return
    user = decrypt_user(st.session_state.user)
    role = user["role"]

    st.markdown('<div class="page-title">Profile</div>', unsafe_allow_html=True)

    col1, col2 = st.columns([1, 1.6])
    with col1:
        # Role display
        icon_map = {"owner":"👑","advisor":"📋","client":"👤"}
        rlbl_map = {"owner":"Platform Owner","advisor":"Financial Advisor","client":"Investor"}
        badge_map= {"owner":"eq","advisor":"eq","client":"mf"}
        icon = icon_map.get(role,"👤")
        rlbl = rlbl_map.get(role,"User")
        risk = user.get("risk_profile","Moderate")
        rc   = {"Conservative":"#2ECC7A","Moderate":"#F5B731","Aggressive":"#FF5A5A"}.get(risk,"#8892AA")
        owner_color = "#E84142" if role=="owner" else ("#4F7EFF" if role=="advisor" else "#2ECC7A")

        st.markdown(f"""
        <div class="card" style="text-align:center;padding:2rem">
            <div style="width:72px;height:72px;border-radius:50%;background:#1E2535;
                border:2px solid {owner_color};display:flex;align-items:center;justify-content:center;
                font-size:2rem;margin:0 auto 1rem">{icon}</div>
            <div style="font-family:'Playfair Display',serif;font-size:1.35rem;color:#F0F4FF">
                {title_case(user.get('full_name') or user.get('username',''))}</div>
            <div style="font-size:.8rem;color:#8892AA;margin-top:.25rem">{user['email']}</div>
            <div style="margin-top:.7rem">
                <span style="background:{owner_color}22;color:{owner_color};border:1px solid {owner_color}44;
                    border-radius:4px;padding:.2rem .6rem;font-size:.75rem;font-weight:600">{rlbl}</span>
            </div>
            <div style="margin-top:.5rem;font-size:.82rem;color:{rc};font-weight:600">Risk: {risk}</div>
        </div>
        <div class="card">
            <div style="font-size:.7rem;color:#8892AA;letter-spacing:.08em;text-transform:uppercase;margin-bottom:.4rem">Account Info</div>
            <div style="font-size:.83rem;color:#8892AA">Email</div>
            <div style="font-weight:600;margin-bottom:.6rem">{user['email']}</div>
            <div style="font-size:.83rem;color:#8892AA">Member Since</div>
            <div style="font-weight:600">{fmt_date(str(user.get('created_at',''))[:10])}</div>
        </div>
        """, unsafe_allow_html=True)

        # ── Tool buttons by role ──────────────────────────────────────────
        if role in ("advisor","owner"):
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("📊 Update Market Data",  use_container_width=True):
                navigate("market_upload")
            if st.button("🗄 Data Management",     use_container_width=True):
                navigate("data_management")
            if st.button("🔍 Stock Enrichment",    use_container_width=True):
                navigate("stock_enrichment")
        if role == "owner":
            if st.button("👑 Owner Dashboard",     use_container_width=True):
                navigate("owner")

        # ── Upgrade to owner (advisor only, not already owner) ────────────
        if role in ("advisor","owner"):
            st.markdown("<br>", unsafe_allow_html=True)
            with st.expander("🔑 Upgrade to Platform Owner"):
                st.caption("Enter the owner key to upgrade your account.")
                with st.form("upgrade_form"):
                    owner_key_input = st.text_input("Owner Key", type="password")
                    if st.form_submit_button("Upgrade Account", use_container_width=True):
                        stored = _owner_key_hash()
                        if not stored:
                            st.error("OWNER_KEY_HASH not set in Streamlit secrets.")
                        elif hashlib.sha256(owner_key_input.encode()).hexdigest() != stored:
                            st.error("Invalid owner key.")
                        else:
                            upgrade_to_owner(user["id"])
                            updated = get_user_by_id(user["id"])
                            st.session_state.user = updated
                            st.success("✅ Account upgraded to Platform Owner!"); st.rerun()

        # ── Delete account ────────────────────────────────────────────────
        st.markdown("<br>", unsafe_allow_html=True)
        with st.expander("⚠️ Delete Account"):
            st.markdown(
                '<div style="font-size:.8rem;color:#FF5A5A;margin-bottom:.5rem">'
                'Permanently deletes your account and all associated data. '
                'This cannot be undone.</div>',
                unsafe_allow_html=True)
            if role in ("advisor","owner"):
                st.caption("All your clients, portfolios, holdings and invoices will also be deleted.")
            if role == "owner":
                st.caption("Owner accounts cannot be self-deleted. Use another owner account or contact the database admin.")

            if role != "owner":
                with st.form("delete_account_form"):
                    confirm_email = st.text_input("Type your email to confirm",
                                                  placeholder=user["email"])
                    if st.form_submit_button("🗑 Delete My Account", use_container_width=True):
                        if confirm_email.strip().lower() != user["email"].lower():
                            st.error("Email doesn't match.")
                        else:
                            delete_user_account(user["id"])
                            st.session_state.clear()
                            st.success("Account deleted.")
                            navigate("home"); st.rerun()

    with col2:
        st.markdown("#### Edit Profile")
        with st.form("profile_form"):
            full_name = st.text_input("Full Name",   value=user.get("full_name",""))
            c1, c2    = st.columns(2)
            phone     = c1.text_input("Phone",       value=user.get("phone",""))
            dob       = c2.text_input("Date of Birth (DD-MM-YYYY)", value=user.get("dob",""))
            pan       = c1.text_input("PAN Number",  value=user.get("pan",""))
            risk_pf   = c2.selectbox("Risk Profile", ["Conservative","Moderate","Aggressive"],
                            index=["Conservative","Moderate","Aggressive"].index(
                                user.get("risk_profile","Moderate")))
            address   = st.text_area("Address", value=user.get("address",""), height=75)
            if st.form_submit_button("Save Changes", use_container_width=True):
                update_user_profile(user["id"], full_name, phone, pan, address, dob, risk_pf)
                updated = get_user_by_id(user["id"])
                st.session_state.user = updated
                st.success("Profile updated!"); st.rerun()

        # ── Change password ───────────────────────────────────────────────
        st.markdown("<br>#### Change Password")
        with st.form("pw_form"):
            from utils.crypto import hash_password
            from utils.db import sb
            cur_pw  = st.text_input("Current Password", type="password")
            new_pw  = st.text_input("New Password",     type="password",
                                     help="Minimum 8 characters")
            new_pw2 = st.text_input("Confirm New Password", type="password")
            if st.form_submit_button("Update Password", use_container_width=True):
                from utils.crypto import verify_password
                if not verify_password(cur_pw, user.get("password_hash","")):
                    st.error("Current password is incorrect.")
                elif len(new_pw) < 8:
                    st.error("New password must be at least 8 characters.")
                elif new_pw != new_pw2:
                    st.error("Passwords don't match.")
                else:
                    from utils.db import update_password
                    update_password(user["id"], hash_password(new_pw))
                    st.success("Password updated successfully.")
