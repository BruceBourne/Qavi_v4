import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate
from utils.db import (get_advisor_clients, create_advisor_client, update_advisor_client,
                      delete_advisor_client, link_registered_client)
from utils.crypto import fmt_date, title_case

FEE_TYPES = {"one_time": "One-Time Fixed Fee", "consultation": "Per Consultation", "management": "AUM Management %"}
FEE_FREQS = {"annual": "Annual", "quarterly": "Quarterly", "monthly": "Monthly", "daily": "Daily"}
RISK_OPTS = ["Conservative", "Moderate", "Aggressive"]

def render():
    if not st.session_state.get("user") or st.session_state.user["role"] not in ("advisor","owner"):
        navigate("login"); return
    user = st.session_state.user
    clients = get_advisor_clients(user["id"])

    st.markdown('<div class="page-title">Clients</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Manage your client relationships</div>', unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs(["  👥 All Clients  ", "  ➕ Add Offline Client  ", "  🔗 Link Registered User  "])

    with tab1:
        if not clients:
            st.info("No clients yet. Use the tabs above to add one.")
        else:
            search = st.text_input("Search clients", placeholder="Name or email…", label_visibility="collapsed")
            shown = [c for c in clients if not search or
                     search.lower() in c["client_name"].lower() or
                     search.lower() in c.get("client_email", "").lower()]
            for cl in shown:
                fee_label = FEE_TYPES.get(cl.get("fee_type", "one_time"), "—")
                reg_dot   = "🟢" if cl.get("is_registered") else "⚪"
                with st.expander(f"{reg_dot}  {title_case(cl['client_name'])}  ·  {fee_label}"):
                    c1, c2 = st.columns(2)
                    c1.markdown(
                        f"**Email:** {cl.get('client_email','—')}<br>**Phone:** {cl.get('client_phone','—')}<br>"
                        f"**PAN:** {cl.get('client_pan','—').upper() if cl.get('client_pan') else '—'}<br>"
                        f"**Risk:** {cl.get('risk_profile','Moderate')}", unsafe_allow_html=True)
                    fee_val = cl.get("fee_value", 0)
                    freq    = FEE_FREQS.get(cl.get("fee_frequency", "annual"), "Annual")
                    c2.markdown(
                        f"**Fee:** {fee_label} · {'%' if cl.get('fee_type')=='management' else '₹'}{fee_val:g} ({freq})<br>"
                        f"**Platform User:** {'Yes ✅' if cl.get('is_registered') else 'No (offline)'}<br>"
                        f"**Added:** {fmt_date(str(cl.get('created_at',''))[:10])}", unsafe_allow_html=True)
                    if cl.get("notes"):
                        st.caption(f"Notes: {cl['notes']}")

                    b1, b2, b3, b4 = st.columns(4)
                    if b1.button("📁 Portfolios", key=f"p_{cl['id']}", use_container_width=True):
                        st.session_state.selected_ac_id = cl["id"]; navigate("portfolios")
                    if b2.button("📊 Analysis", key=f"an_{cl['id']}", use_container_width=True):
                        st.session_state.selected_ac_id = cl["id"]; navigate("analysis")

                    if b3.button("✏️ Edit", key=f"e_{cl['id']}", use_container_width=True):
                        st.session_state[f"edit_{cl['id']}"] = True; st.rerun()
                    if b4.button("🗑 Delete", key=f"d_{cl['id']}", use_container_width=True):
                        st.session_state[f"del_{cl['id']}"] = True; st.rerun()

                    if st.session_state.get(f"del_{cl['id']}"):
                        st.error(f"Delete **{title_case(cl['client_name'])}** and ALL their data permanently?")
                        y, n = st.columns(2)
                        if y.button("Yes, Delete", key=f"yd_{cl['id']}", use_container_width=True):
                            delete_advisor_client(cl["id"]); st.rerun()
                        if n.button("Cancel", key=f"nd_{cl['id']}", use_container_width=True):
                            st.session_state.pop(f"del_{cl['id']}", None); st.rerun()

                    if st.session_state.get(f"edit_{cl['id']}"):
                        st.markdown("---")
                        with st.form(f"ef_{cl['id']}"):
                            en = st.text_input("Name", value=cl["client_name"])
                            ec1, ec2 = st.columns(2)
                            ee   = ec1.text_input("Email", value=cl.get("client_email",""))
                            ep   = ec2.text_input("Phone", value=cl.get("client_phone",""))
                            epan = ec1.text_input("PAN",   value=cl.get("client_pan",""))
                            er   = ec2.selectbox("Risk Profile", RISK_OPTS,
                                                 index=RISK_OPTS.index(cl.get("risk_profile","Moderate")))
                            enotes = st.text_area("Notes", value=cl.get("notes",""), height=60)
                            eft  = st.selectbox("Fee Type", list(FEE_TYPES.keys()),
                                                format_func=lambda x: FEE_TYPES[x],
                                                index=list(FEE_TYPES.keys()).index(cl.get("fee_type","one_time")))
                            ef1, ef2 = st.columns(2)
                            efv  = ef1.number_input("Fee Value", value=float(cl.get("fee_value",0)), min_value=0.0)
                            eff  = ef2.selectbox("Frequency", list(FEE_FREQS.keys()),
                                                 format_func=lambda x: FEE_FREQS[x]) if eft == "management" else "annual"
                            if st.form_submit_button("Save", use_container_width=True):
                                update_advisor_client(cl["id"], en, ee, ep, epan, er, enotes, eft, efv, eff)
                                st.session_state.pop(f"edit_{cl['id']}", None); st.success("Saved!"); st.rerun()
                        if st.button("Cancel", key=f"ce_{cl['id']}"):
                            st.session_state.pop(f"edit_{cl['id']}", None); st.rerun()

    with tab2:
        st.markdown("#### Add Offline Client")
        st.caption("For clients who don't have a Qavi account. You manage their portfolios on their behalf.")
        with st.form("add_offline"):
            cn = st.text_input("Full Name *")
            c1, c2 = st.columns(2)
            ce = c1.text_input("Email"); cp = c2.text_input("Phone")
            cpan = c1.text_input("PAN Number"); cr = c2.selectbox("Risk Profile", RISK_OPTS, index=1)
            cft = st.selectbox("Fee Type", list(FEE_TYPES.keys()), format_func=lambda x: FEE_TYPES[x])
            cf1, cf2 = st.columns(2)
            cfv = cf1.number_input("Fee Value (₹ or %)", min_value=0.0, step=100.0)
            cff = cf2.selectbox("Frequency", list(FEE_FREQS.keys()), format_func=lambda x: FEE_FREQS[x]) if cft == "management" else "annual"
            cnotes = st.text_area("Notes (optional)", height=60)
            if st.form_submit_button("Add Client", use_container_width=True):
                if not cn.strip(): st.error("Name required.")
                else:
                    create_advisor_client(user["id"], cn, ce, cp, cpan, cr, cnotes, cft, cfv, cff)
                    st.success(f"{title_case(cn)} added!"); st.rerun()

    with tab3:
        st.markdown("#### Link a Registered Qavi Investor")
        st.caption("The client must already have a Qavi Investor account. Enter their registered email address.")
        with st.form("link_form"):
            lu = st.text_input("Client's Registered Email")
            if st.form_submit_button("Link Client", use_container_width=True):
                if not lu.strip(): st.error("Enter an email.")
                else:
                    ok, msg = link_registered_client(user["id"], lu.strip())
                    if ok: st.success(msg); st.rerun()
                    else: st.error(msg)
