import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate
from utils.db import sb
from utils.crypto import title_case
from datetime import datetime

def _notify_owner(user_name, category, message):
    """Send notification email to owner when feedback is submitted."""
    try:
        import smtplib
        from email.mime.text import MIMEText
        host  = st.secrets.get("EMAIL_HOST","")
        port  = int(st.secrets.get("EMAIL_PORT", 587))
        usr   = st.secrets.get("EMAIL_USER","")
        pwd   = st.secrets.get("EMAIL_PASS","")
        owner = st.secrets.get("FEEDBACK_EMAIL", usr)
        if not all([host, usr, pwd, owner]): return
        body  = f"New feedback from {user_name}\nCategory: {category}\n\n{message}"
        msg   = MIMEText(body)
        msg["Subject"] = f"[Qavi Feedback] {category.title()} — {user_name}"
        msg["From"]    = usr
        msg["To"]      = owner
        with smtplib.SMTP(host, port) as smtp:
            smtp.starttls()
            smtp.login(usr, pwd)
            smtp.send_message(msg)
    except Exception:
        pass   # notification is best-effort — don't fail the submission

def render():
    user = st.session_state.get("user")

    st.markdown('<div class="page-title">Feedback & Support</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Report issues, bugs, or share suggestions</div>',
                unsafe_allow_html=True)

    st.markdown("""
    <div style="background:#1E2535;border:1px solid #252D40;border-radius:8px;
        padding:.85rem 1.1rem;margin-bottom:1rem;font-size:.8rem;color:#C8D0E0;line-height:1.9">
        Your message goes directly to the platform owner and is reviewed personally.
        We aim to respond within 24 hours for access issues and 48 hours for other feedback.
    </div>
    """, unsafe_allow_html=True)

    with st.form("feedback_form"):
        # Pre-fill if logged in
        if user:
            name_val  = user.get("full_name") or user.get("username","")
            email_val = user.get("email","")
        else:
            name_val = email_val = ""

        c1, c2 = st.columns(2)
        name  = c1.text_input("Your Name", value=name_val)
        email = c2.text_input("Your Email", value=email_val,
                              help="So we can get back to you")
        category = st.selectbox("Category", [
            "Bug / Error",
            "Can't access my account",
            "Unexpected result / wrong data",
            "Feature suggestion",
            "General feedback",
        ])
        message = st.text_area("Describe the issue or feedback *",
                               placeholder="Please include what you were doing when the issue occurred, "
                                           "what you expected, and what actually happened.",
                               height=150)
        submitted = st.form_submit_button("📩 Send Feedback", use_container_width=True)

    if submitted:
        if not message.strip():
            st.error("Please describe your issue or feedback.")
        elif not email.strip() or "@" not in email:
            st.error("A valid email is required so we can respond.")
        else:
            cat_map = {
                "Bug / Error":                 "bug",
                "Can't access my account":     "access",
                "Unexpected result / wrong data":"unexpected",
                "Feature suggestion":          "suggestion",
                "General feedback":            "general",
            }
            cat_key = cat_map.get(category, "general")
            try:
                sb().table("feedback").insert({
                    "user_id":    user["id"] if user else None,
                    "user_name":  name.strip() or "Anonymous",
                    "user_email": email.strip(),
                    "role":       user["role"] if user else "anonymous",
                    "category":   cat_key,
                    "message":    message.strip(),
                    "status":     "open",
                }).execute()
                _notify_owner(name.strip() or "Anonymous", cat_key, message.strip())
                st.success("✅ Feedback submitted. We'll get back to you shortly.")
            except Exception as e:
                st.error(f"Could not submit feedback: {e}")

    st.markdown("")
    if st.button("← Back", use_container_width=False):
        navigate("dashboard" if user else "home")
