import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st

DEFAULTS = {
    "page": "home",
    "user": None,
    "page_history": [],
    "selected_ac_id": None,
    "selected_pf_id": None,
    "selected_symbol": None,
    "selected_asset_class": None,
}

def init_session():
    for k, v in DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v

def navigate(page: str, **kwargs):
    current = st.session_state.get("page", "home")
    if current != page:
        history = st.session_state.get("page_history", [])
        history.append(current)
        st.session_state.page_history = history
    st.session_state.page = page
    for k, v in kwargs.items():
        st.session_state[k] = v
    st.rerun()

def go_back(fallback="home"):
    history = st.session_state.get("page_history", [])
    if history:
        prev = history.pop()
        st.session_state.page_history = history
        st.session_state.page = prev
    else:
        st.session_state.page = fallback
    st.rerun()
