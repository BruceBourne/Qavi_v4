import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate
from utils.db import update_user_profile, get_user_by_id, decrypt_user
from utils.crypto import fmt_date, title_case

def render():
    if not st.session_state.get("user"):
        navigate("login"); return
    user = decrypt_user(st.session_state.user)
    role = user["role"]

    st.markdown('<div class="page-title">Profile</div>', unsafe_allow_html=True)

    col1, col2 = st.columns([1, 1.6])
    with col1:
        icon  = "📋" if role == "advisor" else "👤"
        rlbl  = "Financial Advisor" if role == "advisor" else "Investor"
        risk  = user.get("risk_profile", "Moderate")
        rc    = {"Conservative":"#2ECC7A","Moderate":"#F5B731","Aggressive":"#FF5A5A"}.get(risk,"#8892AA")
        st.markdown(f"""
        <div class="card" style="text-align:center;padding:2rem">
            <div style="width:72px;height:72px;border-radius:50%;background:#1E2535;
                border:2px solid #4F7EFF;display:flex;align-items:center;justify-content:center;
                font-size:2rem;margin:0 auto 1rem">{icon}</div>
            <div style="font-family:'Playfair Display',serif;font-size:1.35rem;color:#F0F4FF">
                {title_case(user.get('full_name') or user.get('username',''))}</div>
            <div style="font-size:.8rem;color:#8892AA;margin-top:.25rem">{user['email']}</div>
            <div style="margin-top:.7rem">
                <span class="badge badge-{'eq' if role=='advisor' else 'mf'}">{rlbl}</span></div>
            <div style="margin-top:.5rem;font-size:.82rem;color:{rc};font-weight:600">Risk: {risk}</div>
        </div>
        <div class="card">
            <div style="font-size:.7rem;color:#8892AA;letter-spacing:.08em;text-transform:uppercase;margin-bottom:.4rem">Account Info</div>
            <div style="font-size:.83rem;color:#8892AA">Email</div>
            <div style="font-weight:600;margin-bottom:.6rem">{user['email']}</div>
            <div style="font-size:.83rem;color:#8892AA">Member Since</div>
            <div style="font-weight:600">{fmt_date(str(user.get('created_at',''))[:10])}</div>
        </div>
        """, unsafe_allow_html=True)

        if role == "advisor":
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("📊 Update Market Data",  use_container_width=True):
                navigate("market_upload")
            if st.button("🗄 Data Management",     use_container_width=True):
                navigate("data_management")
            if st.button("🔍 Stock Enrichment",      use_container_width=True):
                navigate("stock_enrichment")

    with col2:
        st.markdown("#### Edit Profile")
        with st.form("profile_form"):
            full_name = st.text_input("Full Name",   value=user.get("full_name",""))
            c1, c2    = st.columns(2)
            phone     = c1.text_input("Phone",       value=user.get("phone",""))
            dob       = c2.text_input("Date of Birth (DD-MM-YYYY)", value=user.get("dob",""))
            pan       = c1.text_input("PAN Number",  value=user.get("pan",""))
            risk_pf   = c2.selectbox("Risk Profile", ["Conservative","Moderate","Aggressive"],
                            index=["Conservative","Moderate","Aggressive"].index(
                                user.get("risk_profile","Moderate")))
            address   = st.text_area("Address", value=user.get("address",""), height=75)
            if st.form_submit_button("Save Changes", use_container_width=True):
                update_user_profile(user["id"], full_name, phone, pan, address, dob, risk_pf)
                updated = get_user_by_id(user["id"])
                st.session_state.user = updated
                st.success("Profile updated!"); st.rerun()
