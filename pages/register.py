import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.db import create_user, email_exists, get_advisor_key_hash
from utils.crypto import hash_password, hash_advisor_key
from utils.session import navigate

# Full legal text shown in the T&C expander
LEGAL_TEXT = """
### Terms & Conditions and Privacy Policy

**Platform Description**

Qavi is a portfolio analytics and intelligence platform designed to help users understand their investments across asset classes.

**Not Investment Advice**

Qavi does not provide investment advice, recommendations or execution services, and is not a registered investment advisor with the Securities and Exchange Board of India (SEBI). All insights, analytics, risk metrics and scenario models provided through the platform are for informational purposes only and should not be construed as financial advice.

Users should consult a SEBI-registered investment advisor before making any investment decisions. Past performance indicators shown on the platform are not indicative of future results.

**Data & Privacy**

- Your personal information (name, email, PAN, address) is encrypted at rest using AES-128 encryption.
- Your portfolio data is stored securely in our database and is visible only to you and the advisor you explicitly share access with.
- We do not sell, share or transfer your personal data to third parties.
- Your data may be used in anonymised, aggregated form for platform improvement.
- You may request deletion of your account and all associated data at any time from your Profile page.

**Platform Access**

- Access to Qavi is by invitation only.
- You are responsible for maintaining the confidentiality of your login credentials.
- Qavi reserves the right to suspend or terminate accounts that violate these terms.

**Limitation of Liability**

Qavi and its operators shall not be liable for any investment losses, financial decisions or outcomes arising from use of the platform. The platform is provided as-is for informational purposes.

**Governing Law**

These terms are governed by the laws of India. Any disputes shall be subject to the jurisdiction of courts in India.

*Last updated: 2025*
"""

def render():
    st.markdown('<div class="page-title">Create Account</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Join Qavi</div>', unsafe_allow_html=True)

    col1, _ = st.columns([1, 1.4])
    with col1:
        role_sel   = st.radio("Account type",
                              ["Investor", "Financial Advisor"],
                              horizontal=True)
        is_advisor = role_sel == "Financial Advisor"
        role       = "advisor" if is_advisor else "client"

        with st.form("reg_form"):
            if is_advisor:
                st.markdown(
                    '<p style="color:#F5B731;font-size:.82rem;margin-bottom:.5rem">'
                    '🔐 Advisor registration requires an authorization key.</p>',
                    unsafe_allow_html=True)
                auth_key = st.text_input("Advisor Authorization Key", type="password")
            else:
                auth_key = ""

            full_name = st.text_input("Full Name *")
            email     = st.text_input("Email Address *")
            pw        = st.text_input("Password *", type="password",
                                       help="Minimum 8 characters")
            pw2       = st.text_input("Confirm Password *", type="password")

            # T&C checkbox — required before registering
            agree = st.checkbox(
                "I have read and agree to the Terms & Conditions and Privacy Policy")

            submit = st.form_submit_button("Create Account", use_container_width=True)

            if submit:
                errors = []
                if is_advisor:
                    if hash_advisor_key(auth_key) != get_advisor_key_hash():
                        errors.append("Invalid advisor authorization key.")
                if not full_name.strip():
                    errors.append("Full name is required.")
                if not email.strip() or "@" not in email:
                    errors.append("Valid email is required.")
                if len(pw) < 8:
                    errors.append("Password must be at least 8 characters.")
                if pw != pw2:
                    errors.append("Passwords do not match.")
                if not agree:
                    errors.append("You must agree to the Terms & Conditions to continue.")

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
                    else:
                        if "duplicate" in str(result).lower() or "unique" in str(result).lower():
                            st.error("An account with this email already exists.")
                        else:
                            st.error(f"Could not create account: {result}")

        # T&C full text expandable below the form
        with st.expander("📋 Terms & Conditions & Privacy Policy"):
            st.markdown(LEGAL_TEXT)

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Already have an account? Sign In", use_container_width=True):
            navigate("login")
