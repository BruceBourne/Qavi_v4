import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.db import get_user_by_email, set_reset_token, record_login
from utils.crypto import verify_password, generate_reset_token, verify_advisor_key, hash_advisor_key
from utils.session import navigate, save_credentials_js, clear_credentials_js
from datetime import datetime, timedelta
import streamlit.components.v1 as components

def render():
    st.markdown('<div class="page-title">Welcome back</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Sign in to your Qavi account</div>', unsafe_allow_html=True)

    # ── Inactivity notice ────────────────────────────────────────────────
    if st.session_state.pop("_logout_reason", None) == "inactivity":
        st.warning("⏱ You were signed out after 1 hour of inactivity.")

    # ── Remember-me: read saved credentials from localStorage via JS ─────
    # We inject a JS snippet that posts saved credentials back as a hidden
    # query-param update so Streamlit can pre-populate the form fields.
    components.html("""
    <script>
    (function() {
        var saved = localStorage.getItem('qavi_remember');
        if (!saved) return;
        try {
            var creds = JSON.parse(saved);
            // Write into hidden elements that Streamlit URL sync picks up
            // Simpler: store in sessionStorage for this tab so the form
            // inputs can read them on next render via a JS-driven value.
            // We use a URL fragment approach: push to ?_rm=1 so Streamlit
            // triggers a rerun and we read from session_state flag.
            if (creds.email && !window.__qavi_autofilled) {
                window.__qavi_autofilled = true;
                // Dispatch to parent so st.query_params gets updated
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

    # ── Load saved credentials into session for pre-fill ────────────────
    # We store them in session_state["_saved_email"] / ["_saved_password"]
    # when the user checks "Remember me" and logs in.
    saved_email    = st.session_state.get("_saved_email", "")
    saved_password = st.session_state.get("_saved_password", "")

    col1, _ = st.columns([1, 1.4])
    with col1:
        tab_login, tab_reset = st.tabs(["  Sign In  ", "  Forgot Password  "])

        with tab_login:
            with st.form("login_form"):
                email    = st.text_input("Email Address", value=saved_email)
                password = st.text_input("Password", type="password",
                                         value=saved_password)
                remember = st.checkbox("Remember me", value=bool(saved_email),
                                       help="Saves your email and password on this device for quick sign-in.")
                submit   = st.form_submit_button("Sign In", use_container_width=True)

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
                                # Persist in session_state for same-tab autofill
                                st.session_state["_saved_email"]    = email
                                st.session_state["_saved_password"] = password
                                # Persist to localStorage for future sessions
                                save_credentials_js(email, password)
                            else:
                                # Clear any previously saved credentials
                                st.session_state.pop("_saved_email", None)
                                st.session_state.pop("_saved_password", None)
                                clear_credentials_js()

                            navigate("dashboard")
                        else:
                            st.error("Incorrect email or password.")

            # ── JS: autofill form from localStorage on page load ─────────
            components.html("""
            <script>
            (function() {
                var saved = localStorage.getItem('qavi_remember');
                if (!saved) return;
                try {
                    var creds = JSON.parse(saved);
                    if (!creds.email) return;
                    // Find Streamlit text inputs in parent frame and fill them
                    function fillInputs() {
                        var inputs = window.parent.document.querySelectorAll(
                            'input[type="text"], input[type="email"], input[type="password"]'
                        );
                        var filled = 0;
                        inputs.forEach(function(inp) {
                            var label = inp.closest('[data-testid="stTextInput"]');
                            if (!label) return;
                            var labelText = label.querySelector('label');
                            if (!labelText) return;
                            var lt = labelText.innerText.trim().toLowerCase();
                            if (lt === 'email address' && inp.value === '') {
                                inp.value = creds.email;
                                inp.dispatchEvent(new Event('input', {bubbles:true}));
                                filled++;
                            }
                            if ((lt === 'password') && inp.value === '') {
                                inp.value = creds.password;
                                inp.dispatchEvent(new Event('input', {bubbles:true}));
                                filled++;
                            }
                        });
                        return filled;
                    }
                    // Retry until inputs are rendered
                    var attempts = 0;
                    var iv = setInterval(function() {
                        if (fillInputs() >= 2 || attempts++ > 20) clearInterval(iv);
                    }, 200);
                } catch(e) {}
            })();
            </script>
            """, height=0)

            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("Create an account →", key="to_reg", use_container_width=True):
                navigate("register")

        with tab_reset:
            st.markdown('<p style="color:#8892AA;font-size:.83rem">Enter your registered email address and we\'ll generate a reset token you can use to set a new password.</p>', unsafe_allow_html=True)
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
                            st.info(f"Your reset token (valid 2 hours):\n\n`{token}`\n\nCopy this and use it in the 'Reset Password' tab.")
                            st.session_state["_reset_token"] = token
                        else:
                            st.success("If that email is registered, a reset token has been generated.")

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
