import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import requests
from datetime import datetime, date, timedelta
from utils.crypto import encrypt, decrypt, title_case, fmt_date

# ── SUPABASE CLIENT ───────────────────────────────────────────────────────

@st.cache_resource
def get_supabase():
    try:
        from supabase import create_client, ClientOptions
        url  = st.secrets["SUPABASE_URL"]
        key  = st.secrets["SUPABASE_KEY"]
        opts = ClientOptions(postgrest_client_timeout=20)
        return create_client(url, key, options=opts)
    except TypeError:
        try:
            from supabase import create_client
            return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
        except Exception as e:
            st.error(f"Supabase connection failed: {e}"); return None
    except Exception as e:
        st.error(f"Supabase connection failed: {e}"); return None

def sb():
    return get_supabase()

# ── CACHE CLEAR ───────────────────────────────────────────────────────────
# Called after any market data upload to force immediate refresh.
def clear_market_cache():
    """Clear all Streamlit data cache so market pages re-fetch from DB."""
    get_all_prices_map.clear()
    get_assets.clear()
    get_mutual_funds.clear()
    get_fixed_income.clear()
    get_commodities.clear()
    get_indices.clear()

# ── ADVISOR KEY ───────────────────────────────────────────────────────────

def get_advisor_key_hash() -> str:
    try:
        return st.secrets["ADVISOR_KEY_HASH"]
    except Exception:
        from utils.crypto import hash_advisor_key
        return hash_advisor_key(os.environ.get("ADVISOR_KEY", "QAVI-ADV-2025"))

# ── USER QUERIES ──────────────────────────────────────────────────────────

def get_user_by_email(email: str):
    r = sb().table("users").select("*").eq("email", email.lower().strip()).execute()
    return r.data[0] if r.data else None

def get_user_by_id(uid: str):
    r = sb().table("users").select("*").eq("id", uid).execute()
    return r.data[0] if r.data else None

def get_user_by_username(username: str):
    r = sb().table("users").select("*").eq("username", username.strip()).execute()
    return r.data[0] if r.data else None

def email_exists(email: str) -> bool:
    r = sb().table("users").select("id").eq("email", email.lower().strip()).execute()
    return bool(r.data)

def create_user(email, username, password_hash, role, full_name="", advisor_key_hash=None):
    data = {
        "email": email.lower().strip(), "username": username.strip(),
        "password_hash": password_hash, "role": role,
        "full_name": title_case(full_name), "advisor_key_hash": advisor_key_hash,
    }
    try:
        r = sb().table("users").insert(data).execute()
        return True, r.data[0] if r.data else None
    except Exception as e:
        return False, str(e)

def update_user_profile(uid, full_name, phone, pan, address, dob, risk_profile):
    sb().table("users").update({
        "full_name": title_case(full_name),
        "phone_enc": encrypt(phone), "pan_enc": encrypt(pan.upper() if pan else ""),
        "address_enc": encrypt(address), "dob": dob, "risk_profile": risk_profile,
    }).eq("id", uid).execute()

def set_reset_token(email, token, expiry_iso):
    sb().table("users").update({
        "reset_token": token, "reset_token_expiry": expiry_iso,
    }).eq("email", email.lower().strip()).execute()

def get_user_by_reset_token(token):
    r = sb().table("users").select("*").eq("reset_token", token).execute()
    return r.data[0] if r.data else None

def update_password(uid, new_hash):
    sb().table("users").update({
        "password_hash": new_hash, "reset_token": None, "reset_token_expiry": None,
    }).eq("id", uid).execute()

def decrypt_user(user: dict) -> dict:
    if not user: return {}
    out = dict(user)
    out["phone"]   = decrypt(user.get("phone_enc","")) or ""
    out["pan"]     = decrypt(user.get("pan_enc","")) or ""
    out["address"] = decrypt(user.get("address_enc","")) or ""
    return out

def get_all_advisors():
    r = sb().table("users").select("id,full_name,username,email").eq("role","advisor").execute()
    return r.data or []

# ── ADVISOR CLIENTS ───────────────────────────────────────────────────────

def get_advisor_clients(advisor_id):
    r = sb().table("advisor_clients").select("*").eq("advisor_id", advisor_id).order("client_name").execute()
    return r.data or []

def get_advisor_client(ac_id):
    r = sb().table("advisor_clients").select("*").eq("id", ac_id).execute()
    return r.data[0] if r.data else None

def get_client_advisors(user_id):
    r = sb().table("advisor_clients").select("*").eq("client_id", user_id).execute()
    return r.data or []

def create_advisor_client(advisor_id, name, email, phone, pan, risk, notes, fee_type, fee_value, fee_freq):
    sb().table("advisor_clients").insert({
        "advisor_id": advisor_id, "client_name": title_case(name),
        "client_email": email.strip(), "client_phone": phone.strip(),
        "client_pan": pan.upper().strip(), "risk_profile": risk, "notes": notes,
        "fee_type": fee_type, "fee_value": fee_value, "fee_frequency": fee_freq,
    }).execute()

def update_advisor_client(ac_id, name, email, phone, pan, risk, notes, fee_type, fee_value, fee_freq):
    sb().table("advisor_clients").update({
        "client_name": title_case(name), "client_email": email.strip(),
        "client_phone": phone.strip(), "client_pan": pan.upper().strip(),
        "risk_profile": risk, "notes": notes, "fee_type": fee_type,
        "fee_value": fee_value, "fee_frequency": fee_freq,
    }).eq("id", ac_id).execute()

def delete_advisor_client(ac_id):
    sb().table("advisor_clients").delete().eq("id", ac_id).execute()

def link_registered_client(advisor_id, client_email):
    r = sb().table("users").select("*").eq("email", client_email.lower().strip()).execute()
    if not r.data: return False, "No account found with this email."
    u = r.data[0]
    if u["role"] != "client": return False, "This account is not registered as an Investor."
    existing = sb().table("advisor_clients").select("id").eq("advisor_id", advisor_id).eq("client_id", u["id"]).execute()
    if existing.data: return False, "This client is already linked to your account."
    sb().table("advisor_clients").insert({
        "advisor_id": advisor_id, "client_name": u.get("full_name","") or u["username"],
        "client_email": u["email"], "client_id": u["id"], "is_registered": True,
        "fee_type": "management", "fee_value": 1.0, "fee_frequency": "annual",
    }).execute()
    return True, f"{u.get('full_name','Client')} linked successfully."

# ── PORTFOLIOS ────────────────────────────────────────────────────────────

def get_portfolios_for_ac(ac_id, visibility=None):
    q = sb().table("portfolios").select("*").eq("advisor_client_id", ac_id)
    if visibility: q = q.eq("visibility", visibility)
    r = q.order("created_at", desc=True).execute()
    return r.data or []

def get_private_portfolios(user_id):
    r = sb().table("portfolios").select("*").eq("owner_id", user_id).eq("owner_type","client").eq("visibility","private").execute()
    return r.data or []

def get_portfolio_by_id(pf_id):
    r = sb().table("portfolios").select("*").eq("id", pf_id).execute()
    return r.data[0] if r.data else None

def create_portfolio(ac_id, owner_id, owner_type, name, description, goal, target_amount, target_date, visibility, benchmark):
    sb().table("portfolios").insert({
        "advisor_client_id": ac_id, "owner_id": owner_id, "owner_type": owner_type,
        "name": name, "description": description, "goal": goal,
        "target_amount": target_amount, "target_date": target_date,
        "visibility": visibility, "benchmark": benchmark,
    }).execute()

def update_portfolio(pf_id, name, description, goal, target_amount, target_date, benchmark):
    sb().table("portfolios").update({
        "name": name, "description": description, "goal": goal,
        "target_amount": target_amount, "target_date": target_date, "benchmark": benchmark,
    }).eq("id", pf_id).execute()

def delete_portfolio(pf_id):
    sb().table("holdings").delete().eq("portfolio_id", pf_id).execute()
    sb().table("portfolios").delete().eq("id", pf_id).execute()

# ── HOLDINGS ──────────────────────────────────────────────────────────────

def get_portfolio_holdings(pf_id):
    r = sb().table("holdings").select("*").eq("portfolio_id", pf_id).execute()
    return r.data or []

def add_holding(pf_id, symbol, asset_class, sub_class, quantity, unit_type, avg_cost, notes="", is_manual=False):
    sb().table("holdings").insert({
        "portfolio_id": pf_id, "symbol": symbol.upper(),
        "asset_class": asset_class, "sub_class": sub_class,
        "quantity": quantity, "unit_type": unit_type,
        "avg_cost": avg_cost, "notes": notes, "is_manual": is_manual,
    }).execute()
    sb().table("transactions").insert({
        "portfolio_id": pf_id, "symbol": symbol.upper(),
        "txn_type": "BUY", "quantity": quantity,
        "price": avg_cost, "amount": quantity * avg_cost,
        "txn_date": str(date.today()),
    }).execute()

def remove_holding(holding_id):
    sb().table("holdings").delete().eq("id", holding_id).execute()

def get_transactions(pf_id):
    r = sb().table("transactions").select("*").eq("portfolio_id", pf_id).order("txn_date", desc=True).execute()
    return r.data or []

# ── PENDING ASSETS ────────────────────────────────────────────────────────

def submit_pending_asset(user_id, symbol, name, asset_class, sub_class, isin=""):
    try:
        sb().table("pending_assets").insert({
            "submitted_by": user_id, "symbol": symbol, "name": name,
            "asset_class": asset_class, "sub_class": sub_class, "isin": isin,
            "status": "pending",
        }).execute()
    except Exception:
        pass

def get_pending_assets_for_user(user_id):
    r = sb().table("pending_assets").select("*").eq("submitted_by", user_id).order("submitted_at", desc=True).execute()
    return r.data or []

# ── MEETINGS ──────────────────────────────────────────────────────────────

def get_meetings_for_advisor(advisor_id):
    r = sb().table("meetings").select("*").eq("advisor_id", advisor_id).order("meeting_date", desc=True).execute()
    return r.data or []

def get_meetings_for_client(client_user_id):
    r = sb().table("meetings").select("*").eq("client_user_id", client_user_id).order("meeting_date", desc=True).execute()
    return r.data or []

def get_meeting_count_completed(ac_id):
    r = sb().table("meetings").select("id").eq("advisor_client_id", ac_id).eq("status","completed").execute()
    return len(r.data or [])

def create_meeting(advisor_id, ac_id, client_user_id, title, meeting_date, meeting_time, duration_mins, meet_link, notes, requested_by):
    sb().table("meetings").insert({
        "advisor_id": advisor_id, "advisor_client_id": ac_id,
        "client_user_id": client_user_id, "title": title,
        "meeting_date": meeting_date, "meeting_time": meeting_time,
        "duration_mins": duration_mins, "meet_link": meet_link,
        "notes": notes, "requested_by": requested_by, "status": "scheduled",
    }).execute()

def update_meeting_status(meeting_id, status):
    sb().table("meetings").update({"status": status}).eq("id", meeting_id).execute()

def create_meeting_request(advisor_id, client_user_id, preferred_date, preferred_time, message):
    sb().table("meeting_requests").insert({
        "advisor_id": advisor_id, "client_user_id": client_user_id,
        "preferred_date": preferred_date, "preferred_time": preferred_time,
        "message": message,
    }).execute()

def get_pending_requests_for_advisor(advisor_id):
    r = sb().table("meeting_requests").select("*, users!meeting_requests_client_user_id_fkey(full_name,email)").eq("advisor_id", advisor_id).eq("status","pending").order("created_at", desc=True).execute()
    result = []
    for req in (r.data or []):
        req["client_name"] = req.get("users",{}).get("full_name","Client") if req.get("users") else "Client"
        result.append(req)
    return result

def approve_meeting_request(req_id, advisor_id, client_user_id, title, d, t, dur, link, notes):
    create_meeting(advisor_id, None, client_user_id, title, d, t, dur, link, notes, "client")
    sb().table("meeting_requests").update({"status":"approved"}).eq("id", req_id).execute()

def reject_meeting_request(req_id):
    sb().table("meeting_requests").update({"status":"rejected"}).eq("id", req_id).execute()

# ── INVOICES ──────────────────────────────────────────────────────────────

def _next_invoice_number() -> str:
    import secrets
    now    = datetime.now()
    suffix = secrets.token_hex(2).upper()
    return f"INV-{now.year}{now.month:02d}-{now.strftime('%d%H%M')}-{suffix}"

def create_invoice(advisor_id, ac_id, fee_type, fee_value, fee_frequency,
                   amount, portfolio_value=0, num_meetings=0,
                   period_from="", period_to="", notes="",
                   invoice_date=None, due_date=None):
    inv_num  = _next_invoice_number()
    inv_date = invoice_date or str(date.today())
    due      = due_date or str(date.today() + timedelta(days=15))
    sb().table("invoices").insert({
        "invoice_number": inv_num, "advisor_id": advisor_id, "advisor_client_id": ac_id,
        "invoice_date": inv_date, "due_date": due,
        "fee_type": fee_type, "fee_value": fee_value, "fee_frequency": fee_frequency,
        "amount": amount, "portfolio_value": portfolio_value, "num_meetings": num_meetings,
        "period_from": period_from, "period_to": period_to, "notes": notes,
    }).execute()
    return inv_num

def get_invoices_for_advisor(advisor_id):
    r = sb().table("invoices").select("*").eq("advisor_id", advisor_id).order("created_at", desc=True).execute()
    return r.data or []

def update_invoice_status(inv_id, status):
    sb().table("invoices").update({"status": status}).eq("id", inv_id).execute()

# ── MARKET DATA — short TTL so upload reflects quickly ────────────────────
# TTL = 300s (5 min). After upload, call clear_market_cache() for instant refresh.

@st.cache_data(ttl=300)
def get_indices():
    r = sb().table("indices").select("*").execute()
    return r.data or []

@st.cache_data(ttl=300)
def get_all_prices_map():
    """Returns {symbol: {close, change_pct, open, high, low, prev_close, volume, price_date}}"""
    r = sb().table("prices").select(
        "symbol,close,change_pct,open,high,low,prev_close,volume,price_date"
    ).order("price_date", desc=True).execute()
    seen = {}
    for row in (r.data or []):
        if row["symbol"] not in seen:
            seen[row["symbol"]] = row
    return seen

@st.cache_data(ttl=300)
def get_price_history(symbol: str, days: int = 365):
    cutoff = str(date.today() - timedelta(days=days))
    r = sb().table("prices").select("price_date,close,open,high,low,volume").eq("symbol", symbol).gte("price_date", cutoff).order("price_date").execute()
    return r.data or []

@st.cache_data(ttl=300)
def get_assets(asset_class=None, sub_class=None, search=None):
    q = sb().table("assets").select("*").eq("is_active", True)
    if asset_class: q = q.eq("asset_class", asset_class)
    if sub_class:   q = q.eq("sub_class", sub_class)
    data = q.order("symbol").execute().data or []
    if search:
        s = search.lower()
        data = [a for a in data if s in a["symbol"].lower() or s in a["name"].lower()]
    return data

@st.cache_data(ttl=300)
def get_mutual_funds(category=None, sub_category=None, search=None):
    q = sb().table("mutual_funds").select("*")
    if category:     q = q.eq("category", category)
    if sub_category: q = q.eq("sub_category", sub_category)
    data = q.execute().data or []
    if search:
        s = search.lower()
        data = [m for m in data if s in m["name"].lower() or s in m.get("fund_house","").lower()]
    return data

@st.cache_data(ttl=300)
def get_mf_by_symbol(symbol):
    r = sb().table("mutual_funds").select("*").eq("symbol", symbol).execute()
    return r.data[0] if r.data else None

@st.cache_data(ttl=300)
def get_fixed_income(asset_class=None):
    q = sb().table("fixed_income").select("*")
    if asset_class: q = q.eq("asset_class", asset_class)
    return q.execute().data or []

@st.cache_data(ttl=300)
def get_commodities():
    r = sb().table("commodities").select("*").execute()
    return r.data or []

def get_asset_price(symbol: str):
    prices = get_all_prices_map()
    if symbol in prices:
        p = prices[symbol]
        return p["close"], p.get("change_pct", 0)
    r = sb().table("mutual_funds").select("nav,change_pct").eq("symbol", symbol).execute()
    if r.data and r.data[0]["nav"]:
        return r.data[0]["nav"], r.data[0].get("change_pct", 0)
    r2 = sb().table("fixed_income").select("current_price").eq("symbol", symbol).execute()
    if r2.data and r2.data[0]["current_price"]:
        return r2.data[0]["current_price"], 0.0
    r3 = sb().table("commodities").select("price_per_unit,change_pct").eq("symbol", symbol).execute()
    if r3.data and r3.data[0]["price_per_unit"]:
        return r3.data[0]["price_per_unit"], r3.data[0].get("change_pct", 0)
    return 0.0, 0.0

def get_asset_info(symbol: str):
    r = sb().table("assets").select("*").eq("symbol", symbol).execute()
    if r.data: return r.data[0]
    r2 = sb().table("mutual_funds").select("*").eq("symbol", symbol).execute()
    if r2.data: return r2.data[0]
    r3 = sb().table("fixed_income").select("*").eq("symbol", symbol).execute()
    if r3.data: return r3.data[0]
    r4 = sb().table("commodities").select("*").eq("symbol", symbol).execute()
    if r4.data: return r4.data[0]
    return None

def verify_asset_exists_nse(symbol: str) -> bool:
    try:
        r = requests.get(f"https://www.nseindia.com/api/quote-equity?symbol={symbol}", timeout=5,
                         headers={"User-Agent":"Mozilla/5.0","Accept":"*/*"})
        return r.status_code == 200
    except Exception:
        return False
