import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate, save_credentials_js, clear_credentials_js
from utils.db import (get_user_by_email, set_reset_token, record_login,
                      get_user_by_reset_token, update_password)
from utils.crypto import verify_password, generate_reset_token, hash_password
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# ── SEND RESET EMAIL ──────────────────────────────────────────────────────
def _send_reset_email(to_email: str, to_name: str, token: str):
    """Send reset token via SMTP. Returns (success, message)."""
    try:
        host = st.secrets.get("EMAIL_HOST", "")
        port = int(st.secrets.get("EMAIL_PORT", 587))
        usr  = st.secrets.get("EMAIL_USER", "")
        pwd  = st.secrets.get("EMAIL_PASS", "")
        if not all([host, usr, pwd]):
            return False, "Email not configured in secrets (EMAIL_HOST / EMAIL_USER / EMAIL_PASS)."
        import smtplib
        from email.mime.text import MIMEText
        body = (
            f"Hello {to_name or 'there'},\n\n"
            "You requested a password reset for your Qavi account.\n\n"
            f"Your reset token (valid for 2 hours):\n\n    {token}\n\n"
            "Go to the Qavi login page → Forgot Password tab, "
            "paste this token and set your new password.\n\n"
            "If you did not request this, ignore this email.\n\n"
            "— Qavi Platform"
        )
        msg            = MIMEText(body, "plain")
        msg["Subject"] = "Qavi — Password Reset Token"
        msg["From"]    = f"Qavi <{usr}>"
        msg["To"]      = to_email
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.ehlo(); s.starttls(); s.login(usr, pwd)
            s.send_message(msg)
        return True, "Token sent."
    except smtplib.SMTPAuthenticationError:
        return False, "SMTP authentication failed — check EMAIL_PASS in secrets."
    except Exception as e:
        return False, str(e)

# ── HELPERS ───────────────────────────────────────────────────────────────
_BF = "'Palatino Linotype','Book Antiqua',Palatino,serif"

def _fcard(icon, title, text):
    return (
        f'<div style="background:linear-gradient(145deg,#161B27,#0F1421);'
        f'border:1px solid #252D40;border-radius:14px;padding:1.4rem 1.5rem;'
        f'min-height:190px;box-sizing:border-box;display:flex;flex-direction:column;gap:.5rem">'
        f'<div style="font-size:1.1rem;color:#D4AF6A">{icon}</div>'
        f'<div style="font-family:{_BF};font-style:italic;font-size:1rem;'
        f'font-weight:400;color:#F0F4FF;line-height:1.3">{title}</div>'
        f'<div style="font-size:.8rem;color:#8892AA;line-height:1.75;flex:1">{text}</div>'
        f'</div>'
    )

CARDS = [
    ("◆", "Unified Wealth View",
     "Equities, mutual funds, ETFs, bonds, gold and fixed deposits — every asset in one clear view."),
    ("◇", "Intelligence, Not Just Data",
     "Allocation insights, risk exposure, drawdown scenarios and performance analytics built for real conditions."),
    ("◈", "Private. Secure. Yours.",
     "Your data stays fully encrypted and accessible only to you. Invite-only, complete control."),
    ("○", "Goal-Aligned Planning",
     "Understand how your assets support your long-term goals and where adjustments may help."),
]

# ── PAGE ──────────────────────────────────────────────────────────────────
def render():
    if st.session_state.get("user"):
        navigate("dashboard"); return

    if st.session_state.pop("_logout_reason", None) == "inactivity":
        st.warning("⏱ Signed out after 1 hour of inactivity.")

    saved_email = st.session_state.get("_saved_email", "")
    saved_pw    = st.session_state.get("_saved_password", "")

    # Brand header — Palatino Linotype Italic
    st.markdown(
        f'<div style="margin-bottom:1.8rem">'
        f'<div style="font-family:{_BF};font-style:italic;font-size:2.4rem;'
        f'font-weight:400;letter-spacing:.06em;'
        f'background:linear-gradient(120deg,#F8EDD4 20%,#D4AF6A 50%,#F8EDD4 80%);'
        f'-webkit-background-clip:text;-webkit-text-fill-color:transparent;'
        f'background-clip:text;line-height:1;margin-bottom:.3rem">◈ Qavi</div>'
        f'<div style="font-size:.73rem;color:#4E5A70;letter-spacing:.14em;'
        f'text-transform:uppercase">Portfolio Intelligence Platform</div></div>',
        unsafe_allow_html=True)

    left_col, right_col = st.columns([1, 1.6], gap="large")

    # ══ LEFT: sign-in card ══
    with left_col:
        st.markdown(
            f'<div style="font-family:{_BF};font-style:italic;font-size:1.4rem;'
            f'color:#F0F4FF;margin-bottom:.1rem">Welcome back</div>'
            f'<div style="font-size:.8rem;color:#8892AA;margin-bottom:1.1rem">'
            f'Sign in to your Qavi account</div>',
            unsafe_allow_html=True)

        tab_login, tab_reset = st.tabs(["  Sign In  ", "  Forgot Password  "])

        # ── Sign In ──
        with tab_login:
            with st.form("login_form"):
                email    = st.text_input("Email Address", value=saved_email)
                password = st.text_input("Password", type="password", value=saved_pw)
                remember = st.checkbox("Remember me on this device", value=bool(saved_email),
                                        help="Saves credentials in your browser for quick sign-in.")
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
                                st.session_state.page_history = []
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
                                    clear_credentials_js()
                                navigate("dashboard")
                        else:
                            st.error("Incorrect email or password.")

            # Auto-fill from localStorage
            components.html("""
<script>
(function(){
  var saved=localStorage.getItem('qavi_remember');
  if(!saved)return;
  try{
    var c=JSON.parse(saved);
    if(!c.email)return;
    function fill(){
      var ins=window.parent.document.querySelectorAll(
        'input[type="text"],input[type="email"],input[type="password"]');
      var n=0;
      ins.forEach(function(inp){
        var wrap=inp.closest('[data-testid="stTextInput"]');
        if(!wrap)return;
        var lbl=wrap.querySelector('label');
        if(!lbl)return;
        var t=lbl.innerText.trim().toLowerCase();
        if((t==='email address'||t==='email')&&!inp.value){inp.value=c.email;inp.dispatchEvent(new Event('input',{bubbles:true}));n++;}
        if(t==='password'&&!inp.value){inp.value=c.password;inp.dispatchEvent(new Event('input',{bubbles:true}));n++;}
      });
      return n;
    }
    var att=0,iv=setInterval(function(){if(fill()>=2||att++>20)clearInterval(iv);},200);
  }catch(e){}
})();
</script>""", height=0)

            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Create an account →", key="to_reg", use_container_width=True):
                navigate("register")

        # ── Forgot Password ──
        with tab_reset:

            # Step 1: request
            if not st.session_state.get("_reset_sent"):
                with st.form("reset_req"):
                    req_email = st.text_input("Your Registered Email Address")
                    send_btn  = st.form_submit_button("Send Reset Token to Email",
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
                                token          # sent via email — NOT stored in session or shown
                            )
                            if ok:
                                st.success("✅ Reset token sent to your email. "
                                           "Check your inbox and spam folder.")
                                st.session_state["_reset_sent"] = True
                                st.rerun()
                            else:
                                st.error(f"Could not send email: {msg}")
                                st.info("Contact your advisor or platform owner to reset your password.")
                        else:
                            # Same message regardless — prevent email enumeration
                            st.success("If that email is registered, a token has been sent.")
                            st.session_state["_reset_sent"] = True
                            st.rerun()

            # Step 2: paste token and set new password
            else:
                if st.button("← Use a different email", key="reset_back"):
                    st.session_state.pop("_reset_sent", None); st.rerun()

                with st.form("do_reset"):
                    token_in  = st.text_input("Reset Token (from your email)")
                    new_pw    = st.text_input("New Password",     type="password")
                    conf_pw   = st.text_input("Confirm Password", type="password")
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
                                    st.session_state.pop("_reset_sent", None)
                                    st.success("✅ Password updated. Please sign in.")

    # ══ RIGHT: concise platform overview ══
    with right_col:
        st.markdown(f"""
<div style="padding:.4rem 0 1.6rem 0">
  <div style="font-size:.67rem;color:#4E5A70;letter-spacing:.14em;text-transform:uppercase;margin-bottom:1.4rem">
    Portfolio Intelligence Platform
  </div>

  <div style="font-family:{_BF};font-style:italic;font-size:1.55rem;
    color:#F0F4FF;line-height:1.3;margin-bottom:.8rem;font-weight:400">
    Every asset. One place.<br>Complete clarity.
  </div>

  <div style="font-size:.84rem;color:#8892AA;line-height:1.9;margin-bottom:2rem;max-width:440px">
    Qavi brings together equities, mutual funds, ETFs, bonds, gold and fixed
    deposits into a single intelligent view — with P&L, allocation insights,
    and performance analytics built for real investors.
  </div>

  <div style="display:flex;flex-direction:column;gap:.7rem">
    <div style="display:flex;align-items:flex-start;gap:1rem">
      <div style="width:32px;height:32px;border-radius:8px;background:#4F7EFF18;
        border:1px solid #4F7EFF30;display:flex;align-items:center;justify-content:center;
        flex-shrink:0;font-size:.9rem">◈</div>
      <div>
        <div style="font-size:.84rem;color:#C8D0E0;font-weight:600;margin-bottom:.15rem">Multi-asset tracking</div>
        <div style="font-size:.78rem;color:#8892AA;line-height:1.6">Equities, MF, ETF, bonds, gold, FD — all in one portfolio view</div>
      </div>
    </div>
    <div style="display:flex;align-items:flex-start;gap:1rem">
      <div style="width:32px;height:32px;border-radius:8px;background:#2ECC7A18;
        border:1px solid #2ECC7A30;display:flex;align-items:center;justify-content:center;
        flex-shrink:0;font-size:.9rem">◎</div>
      <div>
        <div style="font-size:.84rem;color:#C8D0E0;font-weight:600;margin-bottom:.15rem">Intelligent analytics</div>
        <div style="font-size:.78rem;color:#8892AA;line-height:1.6">Risk exposure, drawdown, Sharpe ratio, sector allocation</div>
      </div>
    </div>
    <div style="display:flex;align-items:flex-start;gap:1rem">
      <div style="width:32px;height:32px;border-radius:8px;background:#D4AF6A18;
        border:1px solid #D4AF6A30;display:flex;align-items:center;justify-content:center;
        flex-shrink:0;font-size:.9rem">⊡</div>
      <div>
        <div style="font-size:.84rem;color:#C8D0E0;font-weight:600;margin-bottom:.15rem">Private by design</div>
        <div style="font-size:.78rem;color:#8892AA;line-height:1.6">Encrypted, invite-only, fully in your control</div>
      </div>
    </div>
  </div>

  <div style="margin-top:2rem;padding:1.2rem 1.4rem;
    background:linear-gradient(135deg,#0D1220,#0A0F1A);
    border:1px solid #2E3850;border-radius:12px;position:relative;overflow:hidden">
    <div style="position:absolute;top:0;left:0;right:0;height:1.5px;
      background:linear-gradient(90deg,transparent,#D4AF6A 50%,transparent)"></div>
    <div style="font-family:{_BF};font-style:italic;font-size:.98rem;
      color:#D4AF6A;margin-bottom:.4rem">Invite-only platform</div>
    <div style="font-size:.78rem;color:#8892AA;line-height:1.65">
      Access is by invitation. Contact the platform owner or your advisor to request access.
    </div>
  </div>
</div>
""", unsafe_allow_html=True)
