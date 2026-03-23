import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.db import create_user, email_exists, get_advisor_key_hash
from utils.crypto import hash_password, hash_advisor_key, title_case
from utils.session import navigate
import hashlib

def _owner_key_hash() -> str:
    try:    return st.secrets["OWNER_KEY_HASH"]
    except: return ""

def render():
    st.markdown('<div class="page-title">Create Account</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Join Qavi</div>', unsafe_allow_html=True)
    col1, _ = st.columns([1, 1.4])
    with col1:
        role_sel   = st.radio("Account type",
                              ["Investor", "Financial Advisor"],
                              horizontal=True)
        is_advisor = role_sel == "Financial Advisor"
        is_owner   = False
        role       = "advisor" if is_advisor else "client"

        with st.form("reg_form"):
            if is_advisor:
                st.markdown('<p style="color:#F5B731;font-size:.82rem;margin-bottom:.5rem">'
                            '🔐 Advisor registration requires an authorization key.</p>',
                            unsafe_allow_html=True)
                auth_key = st.text_input("Advisor Authorization Key", type="password")
            elif is_owner:
                st.markdown('<p style="color:#E84142;font-size:.82rem;margin-bottom:.5rem">'
                            '👑 Owner registration requires the platform owner key.</p>',
                            unsafe_allow_html=True)
                auth_key = st.text_input("Owner Key", type="password")
            else:
                auth_key = ""

            full_name = st.text_input("Full Name *")
            email     = st.text_input("Email Address *")
            pw        = st.text_input("Password *", type="password", help="Minimum 8 characters")
            pw2       = st.text_input("Confirm Password *", type="password")
            submit    = st.form_submit_button("Create Account", use_container_width=True)

            if submit:
                errors = []
                if is_advisor:
                    if hash_advisor_key(auth_key) != get_advisor_key_hash():
                        errors.append("Invalid advisor authorization key.")
                elif is_owner:
                    owner_hash = _owner_key_hash()
                    if not owner_hash:
                        errors.append("Owner key not configured. Set OWNER_KEY_HASH in Streamlit secrets.")
                    elif hashlib.sha256(auth_key.encode()).hexdigest() != owner_hash:
                        errors.append("Invalid owner key.")
                if not full_name.strip():                  errors.append("Full name is required.")
                if not email.strip() or "@" not in email:  errors.append("Valid email is required.")
                if len(pw) < 8:                            errors.append("Password must be at least 8 characters.")
                if pw != pw2:                              errors.append("Passwords do not match.")
                if errors:
                    for e in errors: st.error(e)
                elif email_exists(email):
                    st.error("An account with this email already exists.")
                else:
                    username    = email.strip().split("@")[0].lower().replace(".", "_")
                    adv_kh      = hash_advisor_key(auth_key) if is_advisor else None
                    ok, result  = create_user(
                        email=email.strip(), username=username,
                        password_hash=hash_password(pw), role=role,
                        full_name=full_name.strip(), advisor_key_hash=adv_kh,
                    )
                    if ok:
                        st.success("Account created! Please sign in.")
                        if is_owner:
                            st.info("👑 Owner account created. You have full platform access.")
                    else:
                        if "duplicate" in str(result).lower() or "unique" in str(result).lower():
                            st.error("An account with this email already exists.")
                        else:
                            st.error(f"Could not create account: {result}")

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Already have an account? Sign In", use_container_width=True):
            navigate("login")
