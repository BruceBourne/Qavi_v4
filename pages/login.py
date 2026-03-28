import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate, save_credentials_js
from utils.db import (get_user_by_email, set_reset_token, record_login,
                      get_user_by_reset_token, update_password)
from utils.crypto import verify_password, generate_reset_token, hash_password
from datetime import datetime, timedelta

# ── SEND RESET EMAIL ──────────────────────────────────────────────────────
def _send_reset_email(to_email: str, to_name: str, token: str):
    """Returns (success: bool, message: str)."""
    try:
        host = st.secrets.get("EMAIL_HOST", "")
        port = int(st.secrets.get("EMAIL_PORT", 587))
        usr  = st.secrets.get("EMAIL_USER", "")
        pwd  = st.secrets.get("EMAIL_PASS", "")
        if not all([host, usr, pwd]):
            return False, "Email not configured (EMAIL_HOST/USER/PASS missing in secrets)."
        import smtplib
        from email.mime.text import MIMEText
        body = (
            f"Hello {to_name or 'there'},\n\n"
            f"A password reset was requested for your Qavi account.\n\n"
            f"Reset token (valid 2 hours):\n\n    {token}\n\n"
            f"Enter this on the Qavi login page → Forgot Password tab.\n\n"
            f"If you did not request this, ignore this email.\n\n— Qavi Platform"
        )
        msg            = MIMEText(body, "plain")
        msg["Subject"] = "Qavi — Password Reset Token"
        msg["From"]    = f"Qavi <{usr}>"
        msg["To"]      = to_email
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.ehlo(); s.starttls(); s.login(usr, pwd); s.send_message(msg)
        return True, "Token sent to your email."
    except smtplib.SMTPAuthenticationError:
        return False, "Email authentication failed — check EMAIL_PASS in secrets."
    except Exception as e:
        return False, f"Could not send email: {e}"

# ── PAGE ──────────────────────────────────────────────────────────────────
def render():
    if st.session_state.get("user"):
        navigate("dashboard"); return

    saved_email = st.session_state.get("_saved_email", "")
    saved_pw    = st.session_state.get("_saved_password", "")

    # Centred brand header
    st.markdown("""
    <div class="login-wrap">
      <div class="login-brand">◈ Qavi</div>
      <div class="login-tagline">Portfolio Intelligence Platform</div>
    </div>
    """, unsafe_allow_html=True)

    # Card wrapper
    st.markdown('<div style="display:flex;justify-content:center">'
                '<div class="login-card">', unsafe_allow_html=True)

    tab_login, tab_reset = st.tabs(["  Sign In  ", "  Forgot Password  "])

    # ── SIGN IN ───────────────────────────────────────────────────────────
    with tab_login:
        with st.form("login_form"):
            email    = st.text_input("Email Address", value=saved_email,
                                     placeholder="you@example.com")
            password = st.text_input("Password", type="password",
                                     value=saved_pw)
            remember = st.checkbox("Remember me on this device",
                                    value=bool(saved_email))
            submit   = st.form_submit_button("Sign In", use_container_width=True)

            if submit:
                if not email or not password:
                    st.error("Enter your email and password.")
                else:
                    user = get_user_by_email(email.strip())
                    if user and verify_password(password, user["password_hash"]):
                        if not user.get("is_active", True):
                            st.error("Account inactive. Contact your advisor.")
                        else:
                            st.session_state.user         = user
                            st.session_state._last_active = __import__("time").time()
                            try: record_login(user["id"])
                            except Exception: pass
                            if remember:
                                st.session_state["_saved_email"]    = email.strip()
                                st.session_state["_saved_password"] = password
                                save_credentials_js(email.strip(), password)
                            else:
                                st.session_state.pop("_saved_email",    None)
                                st.session_state.pop("_saved_password", None)
                            navigate("dashboard")
                    else:
                        st.error("Incorrect email or password.")

        st.markdown('<div style="text-align:center;margin-top:.8rem">', unsafe_allow_html=True)
        if st.button("Create new account", use_container_width=True, key="go_reg"):
            navigate("register")
        st.markdown('</div>', unsafe_allow_html=True)

        # Auto-fill from localStorage
        st.markdown("""<script>
(function(){
  const c=JSON.parse(localStorage.getItem('qavi_creds')||'null');
  if(!c)return;
  const ins=window.parent.document.querySelectorAll(
    'input[type="text"],input[type="email"],input[type="password"]');
  ins.forEach(i=>{
    if((i.type==='text'||i.type==='email')&&i.value==='')i.value=c.email;
    if(i.type==='password'&&i.value==='')i.value=c.password;
  });
})();
</script>""", unsafe_allow_html=True)

    # ── FORGOT PASSWORD ───────────────────────────────────────────────────
    with tab_reset:
        st.markdown(
            '<p style="font-size:.82rem;color:#8892AA;margin-bottom:.8rem">'
            'Enter your registered email. A reset token will be sent privately '
            'to that address — it will not appear on this page.</p>',
            unsafe_allow_html=True)

        with st.form("reset_req"):
            req_email = st.text_input("Registered Email Address",
                                       placeholder="you@example.com")
            send_btn  = st.form_submit_button("Send Reset Token",
                                               use_container_width=True)
            if send_btn:
                if not req_email.strip():
                    st.error("Enter your email address.")
                else:
                    found = get_user_by_email(req_email.strip())
                    if found:
                        token  = generate_reset_token()
                        expiry = (datetime.utcnow() + timedelta(hours=2)).isoformat()
                        set_reset_token(req_email.strip(), token, expiry)
                        ok, msg = _send_reset_email(
                            req_email.strip(),
                            found.get("full_name", ""),
                            token
                        )
                        if ok:
                            st.success("✅ Reset token sent — check your inbox (and spam folder).")
                            st.session_state["_reset_req"] = True
                        else:
                            st.error(f"Email error: {msg}")
                            st.info("Contact your advisor to reset your password.")
                    else:
                        # Same message — don't reveal whether email exists
                        st.success("If that email is registered, a token has been sent.")
                        st.session_state["_reset_req"] = True

        if st.session_state.get("_reset_req"):
            st.markdown("---")
            st.markdown('<p style="font-size:.82rem;color:#C8D0E0">Enter the token from your email:</p>',
                        unsafe_allow_html=True)
            with st.form("do_reset"):
                token_in = st.text_input("Reset Token", placeholder="Paste token from email")
                new_pw   = st.text_input("New Password",     type="password")
                conf_pw  = st.text_input("Confirm Password", type="password")
                reset_btn = st.form_submit_button("Set New Password", use_container_width=True)
                if reset_btn:
                    if not token_in.strip():
                        st.error("Paste the token from your email.")
                    elif len(new_pw) < 8:
                        st.error("Password must be at least 8 characters.")
                    elif new_pw != conf_pw:
                        st.error("Passwords don't match.")
                    else:
                        u = get_user_by_reset_token(token_in.strip())
                        if not u:
                            st.error("Invalid or expired token. Request a new one.")
                        else:
                            expiry = u.get("password_reset_expiry", "")
                            if expiry and datetime.fromisoformat(expiry) < datetime.utcnow():
                                st.error("Token expired. Request a new one.")
                            else:
                                update_password(u["id"], hash_password(new_pw))
                                st.session_state.pop("_reset_req", None)
                                st.success("✅ Password updated! Please sign in.")

    st.markdown('</div></div>', unsafe_allow_html=True)
