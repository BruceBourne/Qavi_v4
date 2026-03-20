import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.db import get_user_by_email, set_reset_token
from utils.crypto import verify_password, generate_reset_token, verify_advisor_key, hash_advisor_key
from utils.session import navigate
from datetime import datetime, timedelta

def render():
    st.markdown('<div class="page-title">Welcome back</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Sign in to your Qavi account</div>', unsafe_allow_html=True)

    col1, _ = st.columns([1, 1.4])
    with col1:
        tab_login, tab_reset = st.tabs(["  Sign In  ", "  Forgot Password  "])

        with tab_login:
            with st.form("login_form"):
                email = st.text_input("Email Address")
                password = st.text_input("Password", type="password")
                submit = st.form_submit_button("Sign In", use_container_width=True)

                if submit:
                    if not email or not password:
                        st.error("Please enter your email and password.")
                    else:
                        user = get_user_by_email(email)
                        if user and verify_password(password, user["password_hash"]):
                            st.session_state.user = user
                            st.session_state.page_history = []
                            navigate("dashboard")
                        else:
                            st.error("Incorrect email or password.")

            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Create an account →", key="to_reg", use_container_width=True):
                navigate("register")

        with tab_reset:
            st.markdown('<p style="color:#8892AA;font-size:.83rem">Enter your registered email address and we\'ll generate a reset token you can use to set a new password.</p>', unsafe_allow_html=True)
            with st.form("reset_form"):
                reset_email = st.text_input("Your Email Address")
                submit_reset = st.form_submit_button("Send Reset Token", use_container_width=True)
                if submit_reset:
                    if not reset_email:
                        st.error("Enter your email.")
                    else:
                        user = get_user_by_email(reset_email)
                        if user:
                            token = generate_reset_token()
                            expiry = (datetime.utcnow() + timedelta(hours=2)).isoformat()
                            set_reset_token(reset_email, token, expiry)
                            st.success("Reset token generated.")
                            st.info(f"Your reset token (valid 2 hours):\n\n`{token}`\n\nCopy this and use it in the 'Reset Password' tab.")
                            st.session_state["_reset_token"] = token
                        else:
                            # Don't reveal if email exists
                            st.success("If that email is registered, a reset token has been generated.")

            if st.session_state.get("_reset_token"):
                st.markdown("---")
                with st.form("do_reset_form"):
                    token_in = st.text_input("Paste Reset Token")
                    new_pw = st.text_input("New Password", type="password")
                    conf_pw = st.text_input("Confirm New Password", type="password")
                    do_reset = st.form_submit_button("Set New Password", use_container_width=True)
                    if do_reset:
                        from utils.db import get_user_by_reset_token, update_password
                        from utils.crypto import hash_password
                        u = get_user_by_reset_token(token_in)
                        if not u:
                            st.error("Invalid or expired token.")
                        elif new_pw != conf_pw:
                            st.error("Passwords do not match.")
                        elif len(new_pw) < 8:
                            st.error("Password must be at least 8 characters.")
                        else:
                            expiry = u.get("password_reset_expiry", "")
                            if expiry and datetime.fromisoformat(expiry) < datetime.utcnow():
                                st.error("Token has expired. Request a new one.")
                            else:
                                update_password(u["id"], hash_password(new_pw))
                                st.session_state.pop("_reset_token", None)
                                st.success("Password updated! Please sign in.")
