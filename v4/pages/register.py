import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.db import create_user, email_exists, get_advisor_key_hash
from utils.crypto import hash_password, hash_advisor_key, title_case
from utils.session import navigate

def render():
    st.markdown('<div class="page-title">Create Account</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Join Qavi</div>', unsafe_allow_html=True)
    col1, _ = st.columns([1, 1.4])
    with col1:
        role_sel  = st.radio("Account type", ["Investor", "Financial Advisor"], horizontal=True)
        is_advisor = role_sel == "Financial Advisor"
        role       = "advisor" if is_advisor else "client"
        with st.form("reg_form"):
            if is_advisor:
                st.markdown('<p style="color:#F5B731;font-size:.82rem;margin-bottom:.5rem">🔐 Advisor registration requires an authorization key.</p>', unsafe_allow_html=True)
                adv_key = st.text_input("Authorization Key", type="password")
            full_name = st.text_input("Full Name *")
            email     = st.text_input("Email Address *")
            pw        = st.text_input("Password *", type="password", help="Minimum 8 characters")
            pw2       = st.text_input("Confirm Password *", type="password")
            submit    = st.form_submit_button("Create Account", use_container_width=True)
            if submit:
                errors = []
                if is_advisor:
                    stored_hash = get_advisor_key_hash()
                    if hash_advisor_key(adv_key) != stored_hash:
                        errors.append("Invalid authorization key.")
                if not full_name.strip():              errors.append("Full name is required.")
                if not email.strip() or "@" not in email: errors.append("Valid email is required.")
                if len(pw) < 8:                        errors.append("Password must be at least 8 characters.")
                if pw != pw2:                          errors.append("Passwords do not match.")
                if errors:
                    for e in errors: st.error(e)
                elif email_exists(email):
                    st.error("An account with this email already exists.")
                else:
                    username     = email.strip().split("@")[0].lower().replace(".", "_")
                    adv_key_hash = hash_advisor_key(adv_key) if is_advisor else None
                    ok, result   = create_user(
                        email=email.strip(), username=username,
                        password_hash=hash_password(pw), role=role,
                        full_name=full_name.strip(), advisor_key_hash=adv_key_hash,
                    )
                    if ok:
                        st.success("Account created! Please sign in.")
                    else:
                        if "duplicate" in str(result).lower() or "unique" in str(result).lower():
                            st.error("An account with this email already exists.")
                        else:
                            st.error("Could not create account. Please try again.")
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Already have an account? Sign In", use_container_width=True):
            navigate("login")
