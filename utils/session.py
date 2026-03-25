import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from datetime import datetime, timezone

INACTIVITY_SECONDS = 3600   # 1 hour

DEFAULTS = {
    "page": "home",
    "user": None,
    "page_history": [],
    "selected_ac_id": None,
    "selected_pf_id": None,
    "selected_symbol": None,
    "selected_asset_class": None,
}

# ── INACTIVITY TIMEOUT ────────────────────────────────────────────────────
def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()

def _touch_activity():
    """Record the current time as last activity."""
    st.session_state["_last_active"] = _now_ts()

def _check_inactivity():
    """Log out if user has been inactive for more than INACTIVITY_SECONDS."""
    if not st.session_state.get("user"):
        return
    last = st.session_state.get("_last_active")
    if last is None:
        _touch_activity()
        return
    if (_now_ts() - last) > INACTIVITY_SECONDS:
        _do_logout(reason="inactivity")

def _do_logout(reason=None):
    """Clear session and redirect to home."""
    for k in ["user", "page_history", "selected_ac_id", "selected_pf_id",
              "selected_symbol", "_upload_auth", "_inv_calc", "_last_active"]:
        st.session_state[k] = None if k != "page_history" else []
    st.session_state["page"] = "login"
    if reason == "inactivity":
        st.session_state["_logout_reason"] = "inactivity"
    st.rerun()

# ── REMEMBERED CREDENTIALS (stored in st.session_state, persisted via
#    Streamlit's built-in localStorage bridge through query_params is not
#    available, so we use a server-side session key that survives reruns
#    within the same browser tab.  For true cross-session persistence the
#    credentials are stored in st.session_state["_remembered"] which is
#    populated from the browser's localStorage via a tiny JS snippet
#    injected at init time.) ─────────────────────────────────────────────

def _inject_remember_me_js():
    """
    Inject JS that reads saved credentials from localStorage and writes
    them into hidden Streamlit text inputs via a custom component trick.
    We expose them as st.session_state keys directly by writing a hidden
    div with data attributes that we read back with st.components.
    Simpler approach: just store in st.session_state["_remembered"] and
    rely on Streamlit's session persistence across reruns (same tab).
    Actual localStorage bridge uses st.components.v1.html with postMessage.
    """
    import streamlit.components.v1 as components
    components.html("""
    <script>
    (function() {
        // Read saved credentials from localStorage
        var saved = localStorage.getItem('qavi_remember');
        if (saved) {
            try {
                var creds = JSON.parse(saved);
                // Post to parent Streamlit frame
                window.parent.postMessage({
                    type: 'qavi_autofill',
                    email: creds.email || '',
                    password: creds.password || ''
                }, '*');
            } catch(e) {}
        }
    })();
    </script>
    """, height=0)

def save_credentials_js(email: str, password: str):
    """Inject JS to save credentials to localStorage."""
    import streamlit.components.v1 as components
    import json
    creds = json.dumps({"email": email, "password": password})
    components.html(f"""
    <script>
    localStorage.setItem('qavi_remember', {json.dumps(creds)});
    </script>
    """, height=0)

def clear_credentials_js():
    """Inject JS to remove saved credentials from localStorage."""
    import streamlit.components.v1 as components
    components.html("""
    <script>
    localStorage.removeItem('qavi_remember');
    </script>
    """, height=0)

# ── CORE SESSION ──────────────────────────────────────────────────────────
def init_session():
    for k, v in DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v
    # Touch activity on every page load / rerun while logged in
    if st.session_state.get("user"):
        _check_inactivity()
        _touch_activity()

def navigate(page: str, **kwargs):
    current = st.session_state.get("page", "home")
    if current != page:
        history = st.session_state.get("page_history", [])
        history.append(current)
        st.session_state.page_history = history
    st.session_state.page = page
    for k, v in kwargs.items():
        st.session_state[k] = v
    _touch_activity()
    st.rerun()

def go_back(fallback="home"):
    history = st.session_state.get("page_history", [])
    if history:
        prev = history.pop()
        st.session_state.page_history = history
        st.session_state.page = prev
    else:
        st.session_state.page = fallback
    _touch_activity()
    st.rerun()

# ── BACK BUTTON WIDGET ────────────────────────────────────────────────────
# Pages call back_button() at both top and bottom of render().
# `key` must be unique — pass "top" or "bot" to avoid duplicate widget IDs.

def back_button(fallback: str = "home", label: str = "← Back", key: str = "top"):
    if st.button(label, key=f"_back_{key}_{st.session_state.get('page','x')}"):
        go_back(fallback=fallback)
