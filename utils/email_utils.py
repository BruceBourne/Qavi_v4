"""
Email utility for Qavi.
Uses SMTP (works with Gmail, Outlook, any SMTP provider).

Streamlit secrets needed:
    EMAIL_HOST = "smtp.gmail.com"
    EMAIL_PORT = 587
    EMAIL_USER = "yourapp@gmail.com"
    EMAIL_PASS = "your-app-password"   # Gmail: use App Password, not login password

For Gmail App Password:
    Google Account → Security → 2-Step Verification → App Passwords → Generate
"""
import streamlit as st
import smtplib, base64
from email.mime.multipart import MIMEMultipart
from email.mime.text      import MIMEText
from email.mime.base      import MIMEBase
from email                import encoders

def _smtp_config():
    """Return (host, port, user, password) from Streamlit secrets."""
    try:
        return (
            st.secrets["EMAIL_HOST"],
            int(st.secrets.get("EMAIL_PORT", 587)),
            st.secrets["EMAIL_USER"],
            st.secrets["EMAIL_PASS"],
        )
    except KeyError as e:
        raise RuntimeError(f"Missing email secret: {e}. "
                           f"Add EMAIL_HOST, EMAIL_PORT, EMAIL_USER, EMAIL_PASS to Streamlit secrets.")

def send_invoice_email(
    to_email: str,
    to_name:  str,
    advisor_name: str,
    invoice_number: str,
    amount: float,
    due_date: str,
    html_content: str,
) -> tuple[bool, str]:
    """
    Send invoice as an HTML email attachment.
    Returns (success: bool, message: str).
    """
    try:
        host, port, usr, pwd = _smtp_config()
    except RuntimeError as e:
        return False, str(e)

    try:
        msg = MIMEMultipart("mixed")
        msg["Subject"] = f"Invoice {invoice_number} from {advisor_name} — ₹{amount:,.2f} due {due_date}"
        msg["From"]    = f"{advisor_name} via Qavi <{usr}>"
        msg["To"]      = f"{to_name} <{to_email}>"

        # Plain text body
        plain = (f"Dear {to_name},\n\n"
                 f"Please find your invoice {invoice_number} attached.\n\n"
                 f"Amount Due: ₹{amount:,.2f}\n"
                 f"Payment Due By: {due_date}\n\n"
                 f"To view the invoice, open the attached HTML file in any browser.\n\n"
                 f"Regards,\n{advisor_name}\n\nSent via Qavi Wealth Management Platform")

        alt_part = MIMEMultipart("alternative")
        alt_part.attach(MIMEText(plain, "plain"))
        msg.attach(alt_part)

        # HTML attachment
        att = MIMEBase("text", "html")
        att.set_payload(html_content.encode("utf-8"))
        encoders.encode_base64(att)
        att.add_header("Content-Disposition", "attachment",
                       filename=f"{invoice_number}.html")
        msg.attach(att)

        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(usr, pwd)
            smtp.send_message(msg)

        return True, f"Invoice sent to {to_email}"

    except smtplib.SMTPAuthenticationError:
        return False, ("SMTP authentication failed. For Gmail, use an App Password "
                       "(not your login password). Generate at: Google Account → Security → "
                       "2-Step Verification → App Passwords.")
    except smtplib.SMTPException as e:
        return False, f"SMTP error: {e}"
    except Exception as e:
        return False, f"Could not send email: {e}"


def send_feedback_notification(owner_email: str, user_name: str,
                                category: str, message: str) -> bool:
    """Notify owner of new feedback. Returns True if sent."""
    try:
        host, port, usr, pwd = _smtp_config()
        msg = MIMEText(
            f"New feedback on Qavi\n\nFrom: {user_name}\nCategory: {category}\n\n{message}",
            "plain")
        msg["Subject"] = f"[Qavi] {category.title()} from {user_name}"
        msg["From"]    = usr
        msg["To"]      = owner_email
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.starttls(); smtp.login(usr, pwd); smtp.send_message(msg)
        return True
    except Exception:
        return False
