import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.db import get_user_by_email, set_reset_token, record_login
from utils.crypto import verify_password, generate_reset_token
from utils.session import navigate, save_credentials_js, clear_credentials_js
from datetime import datetime, timedelta
import streamlit.components.v1 as components

# ── FEATURE CARD CONTENT ──────────────────────────────────────────────────
FEATURE_CARDS = [
    {
        "icon": "&#9672;",
        "title": "Unified Wealth View",
        "text": (
            "From equities and mutual funds to real estate, gold, and fixed deposits \u2014 "
            "track every asset in one place and see your true net worth without fragmentation."
        ),
    },
    {
        "icon": "&#9676;",
        "title": "Intelligence, Not Just Data",
        "text": (
            "Go beyond charts with allocation insights, risk exposure, drawdown scenarios, "
            "and performance analytics \u2014 built to help you understand how your portfolio "
            "behaves in real conditions."
        ),
    },
    {
        "icon": "&#9633;",
        "title": "Private. Secure. Yours.",
        "text": (
            "Your financial data stays fully encrypted and accessible only to you. "
            "Qavi is built as a private, invite-only platform with complete control "
            "in your hands."
        ),
    },
    {
        "icon": "&#9677;",
        "title": "Goal-Aligned Wealth Planning",
        "text": (
            "Your portfolio isn\u2019t just tracked \u2014 it\u2019s structured around your ambitions. "
            "Understand how your assets support your long-term goals and where "
            "adjustments may be needed."
        ),
    },
]

HERO_CARD = {
    "title": "More than tracking. It\u2019s understanding.",
    "text": (
        "Most platforms show you what you own. Qavi helps you understand what it means."
        "<br><br>"
        "By combining multi-asset tracking with intelligent analytics, Qavi gives you "
        "a clear picture of where you stand \u2014 and where you\u2019re headed."
    ),
}

_BF = "'Palatino Linotype','Palatino','Book Antiqua','URW Palladio L',Georgia,serif"


def _fcard(icon, title, text):
    return (
        '<div style="background:linear-gradient(145deg,#161B27,#0F1421);'
        'border:1px solid #252D40;border-radius:14px;padding:1.4rem 1.5rem;'
        'min-height:190px;box-sizing:border-box;display:flex;flex-direction:column;gap:.5rem">'
        f'<div style="font-size:1.1rem;color:#D4AF6A;line-height:1">{icon}</div>'
        f'<div style="font-family:{_BF};font-style:italic;font-size:1rem;'
        f'font-weight:600;color:#F0F4FF;line-height:1.3">{title}</div>'
        f'<div style="font-size:.8rem;color:#8892AA;line-height:1.75;flex:1">{text}</div>'
        '</div>'
    )


def _hcard(title, text):
    return (
        '<div style="background:linear-gradient(135deg,#12172B 0%,#0D1220 50%,#0A0F1A 100%);'
        'border:1px solid #2E3850;border-radius:14px;padding:1.8rem 2rem;'
        'margin-top:.6rem;position:relative;overflow:hidden">'
        '<div style="position:absolute;top:0;left:0;right:0;height:2px;'
        'background:linear-gradient(90deg,transparent,#D4AF6A 40%,#4F7EFF 70%,transparent)"></div>'
        f'<div style="font-family:{_BF};font-style:italic;font-size:1.15rem;'
        f'font-weight:600;color:#F0F4FF;margin-bottom:.75rem;line-height:1.3">{title}</div>'
        f'<div style="font-size:.83rem;color:#8892AA;line-height:1.85">{text}</div>'
        '</div>'
    )


def render():
    # ── Inactivity notice ────────────────────────────────────────────────
    if st.session_state.pop("_logout_reason", None) == "inactivity":
        st.warning("\u23f1 You were signed out after 1 hour of inactivity.")

    # ── Remember-me: URL param flag ───────────────────────────────────────
    components.html("""
    <script>
    (function() {
        var saved = localStorage.getItem('qavi_remember');
        if (!saved) return;
        try {
            var creds = JSON.parse(saved);
            if (creds.email && !window.__qavi_autofilled) {
                window.__qavi_autofilled = true;
                var url = new URL(window.parent.location.href);
                if (!url.searchParams.get('_rm')) {
                    url.searchParams.set('_rm', '1');
                    window.parent.history.replaceState({}, '', url.toString());
                }
            }
        } catch(e) {}
    })();
    </script>
    """, height=0)

    saved_email    = st.session_state.get("_saved_email", "")
    saved_password = st.session_state.get("_saved_password", "")

    # ── Brand header ──────────────────────────────────────────────────────
    st.markdown(
        f'<div style="margin-bottom:1.5rem">'
        f'<div style="font-family:{_BF};font-style:italic;font-size:2rem;font-weight:700;'
        'letter-spacing:.06em;'
        'background:linear-gradient(120deg,#F8EDD4 20%,#D4AF6A 50%,#F8EDD4 80%);'
        '-webkit-background-clip:text;-webkit-text-fill-color:transparent;'
        'background-clip:text;line-height:1.1;margin-bottom:.25rem">&#9672; Qavi</div>'
        '<div style="font-size:.78rem;color:#4E5A70;letter-spacing:.12em;text-transform:uppercase">'
        'Private Wealth Intelligence</div></div>',
        unsafe_allow_html=True,
    )

    # ── Two-column layout ─────────────────────────────────────────────────
    left_col, right_col = st.columns([1, 1.55], gap="large")

    # ════════════ LEFT: Sign-in ════════════
    with left_col:
        st.markdown(
            f'<div style="font-family:{_BF};font-style:italic;font-size:1.45rem;'
            'color:#F0F4FF;margin-bottom:.12rem;line-height:1.2">Welcome back</div>'
            '<div style="font-size:.8rem;color:#8892AA;margin-bottom:1rem">'
            'Sign in to your Qavi account</div>',
            unsafe_allow_html=True,
        )

        tab_login, tab_reset = st.tabs(["  Sign In  ", "  Forgot Password  "])

        with tab_login:
            with st.form("login_form"):
                email    = st.text_input("Email Address", value=saved_email)
                password = st.text_input("Password", type="password", value=saved_password)
                remember = st.checkbox(
                    "Remember me", value=bool(saved_email),
                    help="Saves your email and password on this device for quick sign-in.",
                )
                submit = st.form_submit_button("Sign In", use_container_width=True)

                if submit:
                    if not email or not password:
                        st.error("Please enter your email and password.")
                    else:
                        user = get_user_by_email(email)
                        if user and verify_password(password, user["password_hash"]):
                            st.session_state.user         = user
                            st.session_state.page_history = []
                            record_login(user["id"])
                            if remember:
                                st.session_state["_saved_email"]    = email
                                st.session_state["_saved_password"] = password
                                save_credentials_js(email, password)
                            else:
                                st.session_state.pop("_saved_email", None)
                                st.session_state.pop("_saved_password", None)
                                clear_credentials_js()
                            navigate("dashboard")
                        else:
                            st.error("Incorrect email or password.")

            # Autofill from localStorage
            components.html("""
            <script>
            (function() {
                var saved = localStorage.getItem('qavi_remember');
                if (!saved) return;
                try {
                    var creds = JSON.parse(saved);
                    if (!creds.email) return;
                    function fill() {
                        var inputs = window.parent.document.querySelectorAll(
                            'input[type="text"],input[type="email"],input[type="password"]');
                        var n = 0;
                        inputs.forEach(function(inp) {
                            var wrap = inp.closest('[data-testid="stTextInput"]');
                            if (!wrap) return;
                            var lbl = wrap.querySelector('label');
                            if (!lbl) return;
                            var t = lbl.innerText.trim().toLowerCase();
                            if (t === 'email address' && !inp.value) {
                                inp.value = creds.email;
                                inp.dispatchEvent(new Event('input',{bubbles:true})); n++;
                            }
                            if (t === 'password' && !inp.value) {
                                inp.value = creds.password;
                                inp.dispatchEvent(new Event('input',{bubbles:true})); n++;
                            }
                        });
                        return n;
                    }
                    var att = 0, iv = setInterval(function(){
                        if(fill()>=2||att++>20) clearInterval(iv);
                    },200);
                } catch(e){}
            })();
            </script>
            """, height=0)

            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Create an account \u2192", key="to_reg", use_container_width=True):
                navigate("register")

        with tab_reset:
            st.markdown(
                '<p style="color:#8892AA;font-size:.82rem">Enter your registered email '
                "address and we'll generate a reset token you can use to set a new password.</p>",
                unsafe_allow_html=True,
            )
            with st.form("reset_form"):
                reset_email  = st.text_input("Your Email Address")
                submit_reset = st.form_submit_button("Send Reset Token", use_container_width=True)
                if submit_reset:
                    if not reset_email:
                        st.error("Enter your email.")
                    else:
                        user = get_user_by_email(reset_email)
                        if user:
                            token  = generate_reset_token()
                            expiry = (datetime.utcnow() + timedelta(hours=2)).isoformat()
                            set_reset_token(reset_email, token, expiry)
                            st.success("Reset token generated.")
                            st.info(
                                f"Your reset token (valid 2 hours):\n\n`{token}`\n\n"
                                "Copy this and use it in the \u2018Reset Password\u2019 tab."
                            )
                            st.session_state["_reset_token"] = token
                        else:
                            st.success(
                                "If that email is registered, a reset token has been generated."
                            )

            if st.session_state.get("_reset_token"):
                st.markdown("---")
                with st.form("do_reset_form"):
                    token_in = st.text_input("Paste Reset Token")
                    new_pw   = st.text_input("New Password", type="password")
                    conf_pw  = st.text_input("Confirm New Password", type="password")
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

    # ════════════ RIGHT: Feature cards ════════════
    with right_col:
        st.markdown(
            '<div style="font-size:.68rem;color:#4E5A70;letter-spacing:.12em;'
            'text-transform:uppercase;margin-bottom:.85rem;margin-top:.25rem">'
            'What Qavi does for you</div>',
            unsafe_allow_html=True,
        )

        # 2 × 2 grid of feature cards
        r1a, r1b = st.columns(2, gap="small")
        r2a, r2b = st.columns(2, gap="small")

        for col, card in zip([r1a, r1b, r2a, r2b], FEATURE_CARDS):
            with col:
                st.markdown(
                    _fcard(card["icon"], card["title"], card["text"]),
                    unsafe_allow_html=True,
                )

        # Wide hero card spanning full right column width
        st.markdown(
            _hcard(HERO_CARD["title"], HERO_CARD["text"]),
            unsafe_allow_html=True,
        )
