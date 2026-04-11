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
    import smtplib
    from email.mime.text import MIMEText
    try:
        host = st.secrets["EMAIL_HOST"]
        port = int(st.secrets.get("EMAIL_PORT", 587))
        usr  = st.secrets["EMAIL_USER"]
        pwd  = st.secrets["EMAIL_PASS"]
    except KeyError as e:
        return False, f"Missing secret: {e}. Add EMAIL_HOST, EMAIL_PORT, EMAIL_USER, EMAIL_PASS to Streamlit secrets."

    body = (
        f"Hello {to_name or 'there'},\n\n"
        "You requested a password reset for your Qavi account.\n\n"
        f"Your reset token (valid for 2 hours):\n\n    {token}\n\n"
        "Go to the Qavi login page → Forgot Password tab, "
        "paste this token, and set your new password.\n\n"
        "If you did not request this, ignore this email — your password is unchanged.\n\n"
        "— Qavi Platform"
    )
    msg            = MIMEText(body, "plain")
    msg["Subject"] = "Qavi — Password Reset Token"
    msg["From"]    = f"Qavi <{usr}>"
    msg["To"]      = to_email
    try:
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.ehlo(); s.starttls(); s.login(usr, pwd)
            s.send_message(msg)
        return True, "Token sent."
    except smtplib.SMTPAuthenticationError:
        return False, (
            "Gmail rejected the password. EMAIL_PASS must be a Gmail App Password (16 chars, no spaces), "
            "not your Gmail login password. Generate at: Google Account → Security → "
            "2-Step Verification → App Passwords → select Mail + Other."
        )
    except smtplib.SMTPConnectError:
        return False, f"Cannot connect to {host}:{port}. Check EMAIL_HOST and EMAIL_PORT."
    except smtplib.SMTPException as e:
        return False, f"SMTP error: {e}"
    except Exception as e:
        return False, f"Unexpected error: {e}"

# ── FEATURE CARD DATA ─────────────────────────────────────────────────────
_BF = "'Palatino Linotype','Book Antiqua',Palatino,serif"

CARDS = [
    ("#4F7EFF", "rgba(79,126,126,.1)", "rgba(79,126,255,.22)",
     '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><polyline points="22,7 13.5,15.5 8.5,10.5 2,17" stroke="#4F7EFF" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><polyline points="16,7 22,7 22,13" stroke="#4F7EFF" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
     "Unified View", "All your assets — equities, MFs, ETFs, bonds, gold — in one clear place."),
    ("#2ECC7A", "rgba(46,204,46,.08)", "rgba(46,204,122,.2)",
     '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="#2ECC7A" stroke-width="1.8"/><path d="M12 7v5l3.5 2" stroke="#2ECC7A" stroke-width="1.8" stroke-linecap="round"/></svg>',
     "Deep Analytics", "P&L, Sharpe ratio, drawdown and return history per holding."),
    ("#D4AF6A", "rgba(212,120,.08)", "rgba(212,175,106,.22)",
     '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><rect x="3" y="11" width="18" height="11" rx="2" stroke="#D4AF6A" stroke-width="1.8"/><path d="M7 11V7a5 5 0 0 1 10 0v4" stroke="#D4AF6A" stroke-width="1.8" stroke-linecap="round"/><circle cx="12" cy="16" r="1.4" fill="#D4AF6A"/></svg>',
     "Private & Secure", "Fully encrypted. Invite-only. Complete control in your hands."),
    ("#A855F7", "rgba(168,85,120,.08)", "rgba(168,85,247,.2)",
     '<svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M12 2L2 7l10 5 10-5-10-5z" stroke="#A855F7" stroke-width="1.8" stroke-linejoin="round"/><path d="M2 17l10 5 10-5M2 12l10 5 10-5" stroke="#A855F7" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
     "Goal Planning", "Structure your wealth around your ambitions and timelines."),
]

def _fcard(color, bg, border, svg, title, text):
    return (
        f'<div style="position:relative;overflow:hidden;background:#060A14;'
        f'border:1px solid {border};border-radius:16px;padding:1.25rem 1.2rem 1.3rem;'
        f'transition:transform .2s,box-shadow .2s;">'
        f'<div style="position:absolute;top:0;left:8%;right:8%;height:1px;'
        f'background:linear-gradient(90deg,transparent,{color},transparent);opacity:.5;"></div>'
        f'<div style="width:38px;height:38px;border-radius:10px;display:flex;'
        f'align-items:center;justify-content:center;margin-bottom:.85rem;'
        f'background:{bg};border:1px solid {border};">{svg}</div>'
        f'<div style="font-family:\'Cinzel\',serif;font-size:.76rem;letter-spacing:.07em;'
        f'color:#D0C8BA;margin-bottom:.4rem;font-weight:600">{title}</div>'
        f'<div style="font-size:.77rem;color:rgba(110,122,148,.9);line-height:1.8">{text}</div>'
        f'</div>'
    )

# ── PAGE ──────────────────────────────────────────────────────────────────
def render():
    if st.session_state.get("user"):
        navigate("dashboard"); return

    if st.session_state.pop("_logout_reason", None) == "inactivity":
        st.warning("⏱ Signed out after 1 hour of inactivity.")

    saved_email = st.session_state.get("_saved_email", "")
    saved_pw    = st.session_state.get("_saved_password", "")

    st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700&family=Inter:wght@300;400;500;600&display=swap');
</style>
<div style="margin-bottom:2rem">
    <div style="font-family:{_BF};font-style:italic;font-size:2.5rem;font-weight:400;
        letter-spacing:.07em;line-height:1;margin-bottom:.3rem;
        background:linear-gradient(120deg,#FDF4E4 15%,#D4AF6A 48%,#F8EDD4 82%);
        -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;">
        ◈ Qavi</div>
    <div style="font-size:.7rem;color:#2E3A52;letter-spacing:.16em;text-transform:uppercase">
        Portfolio Intelligence Platform</div>
</div>
""", unsafe_allow_html=True)

    left_col, right_col = st.columns([1, 1.65], gap="large")

    # ══ LEFT: sign-in ══
    with left_col:
        st.markdown(
            f'<div style="font-family:{_BF};font-style:italic;font-size:1.45rem;'
            f'color:#EDE8DF;margin-bottom:.08rem;line-height:1.2">Welcome back</div>'
            f'<div style="font-size:.78rem;color:#4A5568;margin-bottom:1.1rem">'
            f'Sign in to your Qavi account</div>',
            unsafe_allow_html=True)

        tab_login, tab_reset = st.tabs(["  Sign In  ", "  Forgot Password  "])

        # ── Sign In tab ──
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
            components.html("""<script>
(function(){
  var s=localStorage.getItem('qavi_remember');
  if(!s)return;
  try{
    var c=JSON.parse(s);if(!c.email)return;
    function fill(){
      var ins=window.parent.document.querySelectorAll(
        'input[type="text"],input[type="email"],input[type="password"]');
      var n=0;
      ins.forEach(function(i){
        var w=i.closest('[data-testid="stTextInput"]');if(!w)return;
        var l=w.querySelector('label');if(!l)return;
        var t=l.innerText.trim().toLowerCase();
        if((t==='email address'||t==='email')&&!i.value){i.value=c.email;i.dispatchEvent(new Event('input',{bubbles:true}));n++;}
        if(t==='password'&&!i.value){i.value=c.password;i.dispatchEvent(new Event('input',{bubbles:true}));n++;}
      });return n;
    }
    var a=0,iv=setInterval(function(){if(fill()>=2||a++>20)clearInterval(iv);},200);
  }catch(e){}
})();
</script>""", height=0)

            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Create an account →", key="to_reg", use_container_width=True):
                navigate("register")

        # ── Forgot Password tab ──
        with tab_reset:
            st.markdown(
                '<p style="font-size:.8rem;color:#4A5568;margin-bottom:.9rem;line-height:1.7">'
                'Enter your registered email. A reset token will be sent '
                '<b style="color:#8892AA">privately to that email only</b> — '
                'never shown here.</p>',
                unsafe_allow_html=True)

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
                            ok, msg = _send_reset_email(req_email.strip(),
                                                        found.get("full_name",""), token)
                            if ok:
                                st.success("✅ Token sent — check your inbox and spam folder.")
                                st.session_state["_reset_sent"] = True
                                st.rerun()
                            else:
                                st.error(f"❌ {msg}")
                                st.markdown("""
                                <div style="background:#0D1220;border-left:3px solid #F5B731;
                                    padding:.7rem 1rem;border-radius:0 8px 8px 0;
                                    font-size:.78rem;color:#8892AA;margin-top:.5rem;line-height:1.9">
                                    <b style="color:#F5B731">Gmail fix:</b> EMAIL_PASS must be a
                                    <b>16-char App Password</b>, not your login password.<br>
                                    Google Account → Security → 2-Step Verification → App Passwords
                                    → Mail + Other → Generate → paste into Streamlit secrets.
                                </div>""", unsafe_allow_html=True)
                        else:
                            st.success("If that email is registered, a token has been sent.")
                            st.session_state["_reset_sent"] = True
                            st.rerun()
            else:
                st.info("📧 Check your email for the reset token, then enter it below.")
                if st.button("← Request again", key="reset_back"):
                    st.session_state.pop("_reset_sent", None); st.rerun()

                with st.form("do_reset"):
                    token_in = st.text_input("Reset Token (from email)")
                    new_pw   = st.text_input("New Password",     type="password")
                    conf_pw  = st.text_input("Confirm Password", type="password")
                    r_btn    = st.form_submit_button("Set New Password", use_container_width=True)
                    if r_btn:
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
                                expiry = u.get("password_reset_expiry","")
                                if expiry and datetime.fromisoformat(expiry) < datetime.utcnow():
                                    st.error("Token expired. Request a new one.")
                                else:
                                    update_password(u["id"], hash_password(new_pw))
                                    st.session_state.pop("_reset_sent", None)
                                    st.success("✅ Password updated. Please sign in.")

    # ══ RIGHT: feature cards ══
    with right_col:
        st.markdown(
            '<div style="font-size:.64rem;color:#2A3548;letter-spacing:.14em;'
            'text-transform:uppercase;margin-bottom:.9rem;margin-top:.15rem">'
            'What Qavi does for you</div>',
            unsafe_allow_html=True)

        r1a, r1b = st.columns(2, gap="small")
        r2a, r2b = st.columns(2, gap="small")
        for col, (color, bg, border, svg, title, text) in zip(
            [r1a, r1b, r2a, r2b], CARDS
        ):
            col.markdown(_fcard(color, bg, border, svg, title, text), unsafe_allow_html=True)

        # Hero / pitch card
        st.markdown(f"""
<div style="position:relative;overflow:hidden;
    background:linear-gradient(145deg,#070D1C 0%,#050A16 100%);
    border:1px solid rgba(255,255,255,.08);border-radius:16px;
    padding:1.7rem 2rem;margin-top:.75rem;">
    <div style="position:absolute;top:0;left:0;right:0;height:2px;
        background:linear-gradient(90deg,transparent 5%,#C5922E 30%,#D4AF6A 50%,#4F7EFF 70%,transparent 95%);
        opacity:.65;"></div>
    <div style="display:flex;gap:2rem;align-items:flex-start;">
        <div style="text-align:center;flex-shrink:0;">
            <div style="font-family:{_BF};font-style:italic;font-size:2.1rem;
                background:linear-gradient(135deg,#F8EDD4,#D4AF6A);
                -webkit-background-clip:text;-webkit-text-fill-color:transparent;
                background-clip:text;line-height:1;margin-bottom:.15rem;">6+</div>
            <div style="font-size:.63rem;color:#2E3A52;letter-spacing:.1em;text-transform:uppercase">Asset Classes</div>
            <div style="font-family:{_BF};font-style:italic;font-size:2.1rem;
                background:linear-gradient(135deg,#F8EDD4,#D4AF6A);
                -webkit-background-clip:text;-webkit-text-fill-color:transparent;
                background-clip:text;line-height:1;margin-bottom:.15rem;margin-top:1rem;">∞</div>
            <div style="font-size:.63rem;color:#2E3A52;letter-spacing:.1em;text-transform:uppercase">Portfolios</div>
        </div>
        <div style="width:1px;background:rgba(255,255,255,.06);align-self:stretch;flex-shrink:0;"></div>
        <div>
            <div style="font-family:'Cinzel',serif;font-size:.87rem;letter-spacing:.07em;
                color:#C8BEA8;margin-bottom:.55rem;font-weight:600">
                More than tracking. It&rsquo;s understanding.</div>
            <div style="font-size:.78rem;color:rgba(100,112,138,.9);line-height:1.9">
                Most platforms show you what you own. Qavi helps you understand what it means.
                <br><br>Combining multi-asset tracking with intelligent analytics — a clear picture
                of where you stand and where you&rsquo;re headed.</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)
