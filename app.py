import sys, os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import streamlit as st
st.set_page_config(
    page_title="Qavi",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

from utils.session import init_session, navigate
from utils.styles import inject_styles
from utils.market import auto_refresh_if_needed

import pages.home             as home
import pages.login            as login
import pages.register         as register
import pages.reset_password   as reset_pw
import pages.dashboard        as dashboard
import pages.portfolios       as portfolios
import pages.holdings         as holdings
import pages.asset_detail     as asset_detail
import pages.market_equities  as mkt_eq
import pages.market_mf        as mkt_mf
import pages.market_etf       as mkt_etf
import pages.market_bonds     as mkt_bonds
import pages.market_fd        as mkt_fd
import pages.market_commodities as mkt_comm
import pages.meetings         as meetings
import pages.invoices         as invoices
import pages.fee_analyser     as fee_analyser
import pages.analysis         as analysis
import pages.profile          as profile
import pages.clients          as clients
import pages.market_upload    as market_upload
import pages.market_auto_fetch as market_auto_fetch
import pages.data_management  as data_management
import pages.stock_enrichment as stock_enrichment
import pages.owner            as owner
import pages.feedback         as feedback
import pages.client_invoices  as client_invoices

init_session()
inject_styles()
auto_refresh_if_needed()

user = st.session_state.get("user")
role = user["role"] if user else None

# ── HELPER: owner has all advisor capabilities ─────────────────────────────
def _is_adv():
    return role in ("advisor", "owner")

# ── NAVIGATION BAR ────────────────────────────────────────────────────────
if user:
    nc = st.columns([1.6, 0.8, 0.7, 0.7, 0.7, 0.7, 0.7, 0.7, 0.55])
    nc[0].markdown('<span class="nav-brand">◈ Qavi</span>', unsafe_allow_html=True)
    if nc[1].button("Home",     use_container_width=True, key="n_home"): navigate("dashboard")
    if nc[2].button("Markets",  use_container_width=True, key="n_mkt"):  navigate("market_equities")
    if nc[3].button("Portfolio",use_container_width=True, key="n_pf"):   navigate("portfolios")
    if nc[4].button("Meetings", use_container_width=True, key="n_mt"):   navigate("meetings")

    if _is_adv():
        if nc[5].button("Clients",  use_container_width=True, key="n_cl"):  navigate("clients")
        if nc[6].button("Invoices", use_container_width=True, key="n_inv"): navigate("invoices")
        if nc[7].button("Profile",  use_container_width=True, key="n_pr"):  navigate("profile")
    else:  # client
        if nc[5].button("Analysis", use_container_width=True, key="n_an"):  navigate("analysis")
        nc[6].empty()
        if nc[7].button("Profile",  use_container_width=True, key="n_pr"):  navigate("profile")

    if nc[8].button("⏏", use_container_width=True, key="n_out", help="Sign Out"):
        from utils.session import clear_credentials_js
        clear_credentials_js()
        for k in ["user","page_history","selected_ac_id","selected_pf_id",
                  "selected_symbol","_upload_auth","_inv_calc",
                  "_saved_email","_saved_password","_last_active"]:
            st.session_state[k] = None if k != "page_history" else []
        navigate("home")

    st.markdown('<hr class="nav-divider"/>', unsafe_allow_html=True)

# ── ROUTER ────────────────────────────────────────────────────────────────
PAGES = {
    "home":               home,
    "login":              login,
    "register":           register,
    "reset_password":     reset_pw,
    "dashboard":          dashboard,
    "portfolios":         portfolios,
    "holdings":           holdings,
    "asset_detail":       asset_detail,
    "market_equities":    mkt_eq,
    "market_mf":          mkt_mf,
    "market_etf":         mkt_etf,
    "market_bonds":       mkt_bonds,
    "market_fd":          mkt_fd,
    "market_commodities": mkt_comm,
    "market_upload":      market_upload,
    "market_auto_fetch":  market_auto_fetch,
    "data_management":    data_management,
    "stock_enrichment":   stock_enrichment,
    "owner":              owner,
    "feedback":           feedback,
    "client_invoices":    client_invoices,
    "meetings":           meetings,
    "invoices":           invoices,
    "fee_analyser":       fee_analyser,
    "analysis":           analysis,
    "profile":            profile,
    "clients":            clients,
}

page = st.session_state.get("page", "home")
PAGES.get(page, home).render()

# ── FOOTER — varies by page ───────────────────────────────────────────────
current_page = st.session_state.get("page","home")

# No footer on login/register/home (home has its own full disclaimer)
if current_page in ("login","register","reset_password","home"):
    pass

# Dashboard and profile get full disclaimer (handled inside those pages)
elif current_page in ("dashboard","profile"):
    pass  # full disclaimer injected by the page itself

else:
    # All other pages — short two-liner, no SEBI mention
    st.markdown("""
    <div style="margin-top:2.5rem;padding:.5rem 0;border-top:1px solid #1A2030;
        display:flex;justify-content:space-between;align-items:center;
        font-size:.66rem;color:#3A4560">
        <span>◈ Qavi &nbsp;·&nbsp; Portfolio intelligence platform &nbsp;·&nbsp;
        All insights are informational in nature and should not be construed as financial advice.</span>
        <span>© 2025 Qavi</span>
    </div>
    """, unsafe_allow_html=True)
