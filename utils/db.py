import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import requests
from datetime import datetime, date, timedelta
from utils.crypto import encrypt, decrypt, title_case, fmt_date

# ── SUPABASE CLIENT ───────────────────────────────────────────────────────
# Set in Streamlit secrets:
#   SUPABASE_URL = "https://xxxx.supabase.co"
#   SUPABASE_KEY = "your-anon-public-key"

@st.cache_resource
def get_supabase():
    try:
        from supabase import create_client, ClientOptions
        url  = st.secrets["SUPABASE_URL"]
        key  = st.secrets["SUPABASE_KEY"]
        # Use connection pooling via Supabase's pgbouncer port when available
        opts = ClientOptions(postgrest_client_timeout=15)
        return create_client(url, key, options=opts)
    except TypeError:
        # Older supabase-py without ClientOptions
        try:
            from supabase import create_client
            url = st.secrets["SUPABASE_URL"]
            key = st.secrets["SUPABASE_KEY"]
            return create_client(url, key)
        except Exception as e:
            st.error(f"Supabase connection failed: {e}")
            return None
    except Exception as e:
        st.error(f"Supabase connection failed: {e}")
        return None

def sb():
    return get_supabase()

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
        "email": email.lower().strip(),
        "username": username.strip(),
        "password_hash": password_hash,
        "role": role,
        "full_name": title_case(full_name),
        "advisor_key_hash": advisor_key_hash,
    }
    try:
        r = sb().table("users").insert(data).execute()
        return True, r.data[0] if r.data else None
    except Exception as e:
        return False, str(e)

def update_user_profile(uid, full_name, phone, pan, address, dob, risk_profile):
    sb().table("users").update({
        "full_name": title_case(full_name),
        "phone_enc": encrypt(phone),
        "pan_enc": encrypt(pan.upper() if pan else ""),
        "address_enc": encrypt(address),
        "dob": dob,
        "risk_profile": risk_profile,
    }).eq("id", uid).execute()

def set_reset_token(email, token, expiry_iso):
    sb().table("users").update({
        "password_reset_token": token,
        "password_reset_expiry": expiry_iso,
    }).eq("email", email.lower()).execute()

def get_user_by_reset_token(token):
    r = sb().table("users").select("*").eq("password_reset_token", token).execute()
    return r.data[0] if r.data else None

def update_password(uid, new_hash):
    sb().table("users").update({
        "password_hash": new_hash,
        "password_reset_token": None,
        "password_reset_expiry": None,
    }).eq("id", uid).execute()

def get_all_advisors():
    r = sb().table("users").select("id,username,full_name,email").eq("role", "advisor").execute()
    return r.data or []

def decrypt_user(user: dict) -> dict:
    """Return a copy of user dict with decrypted PII fields."""
    if not user:
        return {}
    u = dict(user)
    u["phone"] = decrypt(u.get("phone_enc", ""))
    u["pan"] = decrypt(u.get("pan_enc", ""))
    u["address"] = decrypt(u.get("address_enc", ""))
    return u

# ── ADVISOR-CLIENT ────────────────────────────────────────────────────────

def get_advisor_clients(advisor_id):
    r = sb().table("advisor_clients").select("*").eq("advisor_id", advisor_id).execute()
    result = []
    for ac in (r.data or []):
        ac["client_email"] = decrypt(ac.get("client_email_enc", ""))
        ac["client_phone"] = decrypt(ac.get("client_phone_enc", ""))
        ac["client_pan"] = decrypt(ac.get("client_pan_enc", ""))
        ac["notes"] = decrypt(ac.get("notes_enc", ""))
        result.append(ac)
    return result

def get_advisor_client(ac_id):
    r = sb().table("advisor_clients").select("*").eq("id", ac_id).execute()
    if not r.data:
        return None
    ac = r.data[0]
    ac["client_email"] = decrypt(ac.get("client_email_enc", ""))
    ac["client_phone"] = decrypt(ac.get("client_phone_enc", ""))
    ac["client_pan"] = decrypt(ac.get("client_pan_enc", ""))
    ac["notes"] = decrypt(ac.get("notes_enc", ""))
    return ac

def create_advisor_client(advisor_id, client_name, email="", phone="", pan="",
                          risk_profile="Moderate", notes="", fee_type="one_time",
                          fee_value=0, fee_frequency="annual"):
    sb().table("advisor_clients").insert({
        "advisor_id": advisor_id,
        "client_name": title_case(client_name),
        "client_email_enc": encrypt(email.lower()),
        "client_phone_enc": encrypt(phone),
        "client_pan_enc": encrypt(pan.upper() if pan else ""),
        "risk_profile": risk_profile,
        "notes_enc": encrypt(notes),
        "fee_type": fee_type,
        "fee_value": fee_value,
        "fee_frequency": fee_frequency,
        "is_registered": False,
    }).execute()

def link_registered_client(advisor_id, email):
    user = get_user_by_email(email)
    if not user or user["role"] != "client":
        return False, "No client account found with that email."
    already = sb().table("advisor_clients").select("id").eq("advisor_id", advisor_id).eq("client_id", user["id"]).execute()
    if already.data:
        return False, "Client already linked."
    sb().table("advisor_clients").insert({
        "advisor_id": advisor_id,
        "client_id": user["id"],
        "client_name": user.get("full_name", ""),
        "client_email_enc": encrypt(user.get("email", "")),
        "client_phone_enc": encrypt(decrypt(user.get("phone_enc", ""))),
        "risk_profile": user.get("risk_profile", "Moderate"),
        "is_registered": True,
    }).execute()
    return True, "Client linked successfully."

def update_advisor_client(ac_id, client_name, email, phone, pan,
                          risk_profile, notes, fee_type, fee_value, fee_frequency):
    sb().table("advisor_clients").update({
        "client_name": title_case(client_name),
        "client_email_enc": encrypt(email.lower()),
        "client_phone_enc": encrypt(phone),
        "client_pan_enc": encrypt(pan.upper() if pan else ""),
        "risk_profile": risk_profile,
        "notes_enc": encrypt(notes),
        "fee_type": fee_type,
        "fee_value": fee_value,
        "fee_frequency": fee_frequency,
    }).eq("id", ac_id).execute()

def delete_advisor_client(ac_id):
    # Cascade handled by DB foreign keys
    sb().table("advisor_clients").delete().eq("id", ac_id).execute()

def get_client_advisors(client_user_id):
    r = sb().table("advisor_clients").select("*, users!advisor_clients_advisor_id_fkey(full_name,email,phone_enc)").eq("client_id", client_user_id).execute()
    result = []
    for ac in (r.data or []):
        ac["advisor_name"] = ac.get("users", {}).get("full_name", "Advisor") if ac.get("users") else "Advisor"
        ac["advisor_email"] = ac.get("users", {}).get("email", "") if ac.get("users") else ""
        ac["client_email"] = decrypt(ac.get("client_email_enc", ""))
        result.append(ac)
    return result

# ── PORTFOLIOS ────────────────────────────────────────────────────────────

def get_portfolios_for_ac(ac_id, visibility=None):
    q = sb().table("portfolios").select("*").eq("advisor_client_id", ac_id)
    if visibility:
        q = q.eq("visibility", visibility)
    return q.execute().data or []

def get_private_portfolios(owner_id):
    r = sb().table("portfolios").select("*").eq("owner_id", owner_id).eq("visibility", "private").execute()
    return r.data or []

def get_portfolio_by_id(pf_id):
    r = sb().table("portfolios").select("*").eq("id", pf_id).execute()
    return r.data[0] if r.data else None

def create_portfolio(ac_id, owner_id, owner_type, name, description="", goal="",
                     target_amount=0, target_date="", visibility="shared", benchmark="NIFTY50"):
    sb().table("portfolios").insert({
        "advisor_client_id": ac_id,
        "owner_id": owner_id,
        "owner_type": owner_type,
        "name": name,
        "description": description,
        "goal": goal,
        "target_amount": target_amount,
        "target_date": target_date,
        "visibility": visibility,
        "benchmark": benchmark,
    }).execute()

def update_portfolio(pf_id, name, description, goal, target_amount, target_date, benchmark):
    sb().table("portfolios").update({
        "name": name, "description": description, "goal": goal,
        "target_amount": target_amount, "target_date": target_date, "benchmark": benchmark,
    }).eq("id", pf_id).execute()

def delete_portfolio(pf_id):
    sb().table("portfolios").delete().eq("id", pf_id).execute()

# ── HOLDINGS ──────────────────────────────────────────────────────────────

def get_portfolio_holdings(portfolio_id):
    r = sb().table("holdings").select("*").eq("portfolio_id", portfolio_id).execute()
    return r.data or []

def add_holding(portfolio_id, symbol, asset_class, sub_class, quantity,
                unit_type, avg_cost, notes="", is_manual=False):
    # Check existing
    existing = sb().table("holdings").select("id,quantity,avg_cost").eq("portfolio_id", portfolio_id).eq("symbol", symbol).execute()
    if existing.data:
        h = existing.data[0]
        old_qty = h["quantity"]; old_cost = h["avg_cost"]
        new_qty = old_qty + quantity
        new_avg = ((old_qty * old_cost) + (quantity * avg_cost)) / new_qty
        sb().table("holdings").update({"quantity": new_qty, "avg_cost": new_avg}).eq("id", h["id"]).execute()
    else:
        sb().table("holdings").insert({
            "portfolio_id": portfolio_id, "symbol": symbol,
            "asset_class": asset_class, "sub_class": sub_class,
            "quantity": quantity, "unit_type": unit_type,
            "avg_cost": avg_cost, "notes": notes,
            "buy_date": str(date.today()),
            "is_manual": is_manual,
            "is_verified": not is_manual,
        }).execute()
    # Log transaction
    sb().table("transactions").insert({
        "portfolio_id": portfolio_id, "symbol": symbol,
        "txn_type": "BUY", "quantity": quantity,
        "price": avg_cost, "amount": quantity * avg_cost,
        "txn_date": str(date.today()), "notes": notes,
    }).execute()

def remove_holding(holding_id):
    h = sb().table("holdings").select("*").eq("id", holding_id).execute()
    if h.data:
        hd = h.data[0]
        sb().table("transactions").insert({
            "portfolio_id": hd["portfolio_id"], "symbol": hd["symbol"],
            "txn_type": "SELL", "quantity": hd["quantity"],
            "price": hd["avg_cost"], "amount": hd["quantity"] * hd["avg_cost"],
            "txn_date": str(date.today()),
        }).execute()
    sb().table("holdings").delete().eq("id", holding_id).execute()

def get_transactions(portfolio_id):
    r = sb().table("transactions").select("*").eq("portfolio_id", portfolio_id).order("created_at", desc=True).execute()
    return r.data or []

# ── PENDING ASSETS (manual verification) ─────────────────────────────────

def submit_pending_asset(user_id, symbol, name, asset_class, sub_class="", isin="", notes=""):
    sb().table("pending_assets").insert({
        "submitted_by": user_id, "symbol": symbol.upper(),
        "name": name, "asset_class": asset_class,
        "sub_class": sub_class, "isin": isin, "notes": notes,
    }).execute()

def get_pending_assets_for_user(user_id):
    r = sb().table("pending_assets").select("*").eq("submitted_by", user_id).order("submitted_at", desc=True).execute()
    return r.data or []

def verify_asset_exists_nse(symbol: str) -> bool:
    """Quick check against NSE API if a symbol exists."""
    try:
        url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol.upper()}"
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json",
                   "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.nseindia.com"}
        r = requests.get(url, headers=headers, timeout=5)
        return r.status_code == 200 and "info" in r.json()
    except Exception:
        return False

# ── MEETINGS ──────────────────────────────────────────────────────────────

def create_meeting(advisor_id, ac_id, client_user_id, title, meeting_date,
                   meeting_time, duration_mins=60, meet_link="", notes="", requested_by="advisor"):
    sb().table("meetings").insert({
        "advisor_id": advisor_id, "advisor_client_id": ac_id,
        "client_user_id": client_user_id,
        "title": title, "meeting_date": meeting_date,
        "meeting_time": meeting_time, "duration_mins": duration_mins,
        "meet_link": meet_link, "notes": notes, "requested_by": requested_by,
    }).execute()

def get_meetings_for_advisor(advisor_id):
    r = sb().table("meetings").select("*").eq("advisor_id", advisor_id).order("meeting_date", desc=True).execute()
    return r.data or []

def get_meetings_for_client(client_user_id):
    r = sb().table("meetings").select("*").eq("client_user_id", client_user_id).order("meeting_date", desc=True).execute()
    return r.data or []

def get_meeting_count_completed(ac_id):
    r = sb().table("meetings").select("id").eq("advisor_client_id", ac_id).eq("status", "completed").execute()
    return len(r.data or [])

def update_meeting_status(meeting_id, status):
    sb().table("meetings").update({"status": status}).eq("id", meeting_id).execute()

def create_meeting_request(advisor_id, client_user_id, preferred_date, preferred_time, message=""):
    sb().table("meeting_requests").insert({
        "advisor_id": advisor_id, "client_user_id": client_user_id,
        "preferred_date": preferred_date, "preferred_time": preferred_time,
        "message": message,
    }).execute()

def get_pending_requests_for_advisor(advisor_id):
    r = sb().table("meeting_requests").select("*, users!meeting_requests_client_user_id_fkey(full_name,email)").eq("advisor_id", advisor_id).eq("status", "pending").order("created_at", desc=True).execute()
    result = []
    for req in (r.data or []):
        req["client_name"] = req.get("users", {}).get("full_name", "Client") if req.get("users") else "Client"
        result.append(req)
    return result

def approve_meeting_request(req_id, advisor_id, client_user_id, title, d, t, dur, link, notes):
    create_meeting(advisor_id, None, client_user_id, title, d, t, dur, link, notes, "client")
    sb().table("meeting_requests").update({"status": "approved"}).eq("id", req_id).execute()

def reject_meeting_request(req_id):
    sb().table("meeting_requests").update({"status": "rejected"}).eq("id", req_id).execute()

# ── INVOICES ──────────────────────────────────────────────────────────────

def _next_invoice_number() -> str:
    """Generate collision-proof invoice number using timestamp + random suffix."""
    import uuid, secrets
    now    = datetime.now()
    suffix = secrets.token_hex(2).upper()          # 4-char random hex
    return f"INV-{now.year}{now.month:02d}-{now.strftime('%d%H%M')}-{suffix}"

def create_invoice(advisor_id, ac_id, fee_type, fee_value, fee_frequency,
                   amount, portfolio_value=0, num_meetings=0,
                   period_from="", period_to="", notes="",
                   invoice_date=None, due_date=None):
    inv_num  = _next_invoice_number()
    inv_date = invoice_date or str(date.today())
    due      = due_date     or str(date.today() + timedelta(days=15))
    sb().table("invoices").insert({
        "invoice_number": inv_num,
        "advisor_id": advisor_id, "advisor_client_id": ac_id,
        "invoice_date": inv_date, "due_date": due,
        "fee_type": fee_type, "fee_value": fee_value,
        "fee_frequency": fee_frequency, "amount": amount,
        "portfolio_value": portfolio_value, "num_meetings": num_meetings,
        "period_from": period_from, "period_to": period_to, "notes": notes,
    }).execute()
    return inv_num

# ── CSV/EXCEL MARKET DATA UPLOAD ──────────────────────────────────────────
# Called with a special upload key to let advisor populate market data

def upsert_prices_from_df(df):
    """
    df columns required: symbol, close
    optional: open, high, low, prev_close, change_pct, volume
    """
    now   = datetime.now().isoformat()
    today = str(date.today())
    count = 0
    for _, row in df.iterrows():
        sym = str(row.get("symbol","")).strip().upper()
        if not sym: continue
        cl  = float(row.get("close", row.get("ltp", row.get("last_price", 0))) or 0)
        if cl <= 0: continue
        prev = float(row.get("prev_close", row.get("previous_close", cl)) or cl)
        chg  = float(row.get("change_pct", row.get("pchange", ((cl-prev)/prev*100) if prev else 0)) or 0)
        try:
            sb().table("prices").upsert({
                "symbol": sym, "price_date": today,
                "open":   float(row.get("open",   cl) or cl),
                "high":   float(row.get("high",   cl) or cl),
                "low":    float(row.get("low",    cl) or cl),
                "close":  cl, "prev_close": prev,
                "change_pct": round(chg, 4),
                "volume": int(row.get("volume", 0) or 0),
                "last_updated": now,
            }, on_conflict="symbol,price_date").execute()
            count += 1
        except Exception:
            pass
    # Clear cache so new prices show immediately
    try:
        st.cache_data.clear()
    except Exception:
        pass
    return count

def upsert_navs_from_df(df):
    """
    df columns required: symbol, nav
    optional: prev_nav, change_pct, fund_house, scheme_code
    """
    now   = datetime.now().isoformat()
    today = str(date.today())
    count = 0
    for _, row in df.iterrows():
        sym = str(row.get("symbol","")).strip().upper()
        if not sym: continue
        nav  = float(row.get("nav", row.get("NAV", 0)) or 0)
        if nav <= 0: continue
        prev = float(row.get("prev_nav", nav) or nav)
        chg  = float(row.get("change_pct", ((nav-prev)/prev*100) if prev else 0) or 0)
        try:
            sb().table("mutual_funds").update({
                "nav": nav, "prev_nav": prev,
                "change_pct": round(chg, 4),
                "nav_date": today, "last_updated": now,
            }).eq("symbol", sym).execute()
            count += 1
        except Exception:
            pass
    try:
        st.cache_data.clear()
    except Exception:
        pass
    return count

def get_invoices_for_advisor(advisor_id):
    r = sb().table("invoices").select("*").eq("advisor_id", advisor_id).order("created_at", desc=True).execute()
    return r.data or []

def update_invoice_status(inv_id, status):
    sb().table("invoices").update({"status": status}).eq("id", inv_id).execute()

# ── MARKET DATA ───────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)  # cache 1 hour
def get_indices():
    r = sb().table("indices").select("*").execute()
    return r.data or []

@st.cache_data(ttl=3600)
def get_all_prices_map():
    r = sb().table("prices").select("symbol,close,change_pct,change_amt,open,high,low,prev_close,volume,price_date").order("price_date", desc=True).execute()
    seen = {}
    for row in (r.data or []):
        if row["symbol"] not in seen:
            seen[row["symbol"]] = row
    return seen

@st.cache_data(ttl=3600)
def get_price_history(symbol: str, days: int = 365):
    cutoff = str(date.today() - timedelta(days=days))
    r = sb().table("prices").select("price_date,close,open,high,low,volume").eq("symbol", symbol).gte("price_date", cutoff).order("price_date").execute()
    return r.data or []

@st.cache_data(ttl=3600)
def get_assets(asset_class=None, sub_class=None, search=None):
    q = sb().table("assets").select("*").eq("is_active", True)
    if asset_class:
        q = q.eq("asset_class", asset_class)
    if sub_class:
        q = q.eq("sub_class", sub_class)
    data = q.execute().data or []
    if search:
        s = search.lower()
        data = [a for a in data if s in a["symbol"].lower() or s in a["name"].lower()]
    return data

@st.cache_data(ttl=3600)
def get_mutual_funds(category=None, sub_category=None, search=None):
    q = sb().table("mutual_funds").select("*")
    if category:
        q = q.eq("category", category)
    if sub_category:
        q = q.eq("sub_category", sub_category)
    data = q.execute().data or []
    if search:
        s = search.lower()
        data = [m for m in data if s in m["name"].lower() or s in m.get("fund_house","").lower()]
    return data

@st.cache_data(ttl=3600)
def get_mf_by_symbol(symbol):
    r = sb().table("mutual_funds").select("*").eq("symbol", symbol).execute()
    return r.data[0] if r.data else None

@st.cache_data(ttl=3600)
def get_fixed_income(asset_class=None):
    q = sb().table("fixed_income").select("*")
    if asset_class:
        q = q.eq("asset_class", asset_class)
    return q.execute().data or []

@st.cache_data(ttl=3600)
def get_commodities():
    r = sb().table("commodities").select("*").execute()
    return r.data or []

def get_asset_price(symbol: str):
    """Universal price lookup. Returns (price, change_pct)."""
    prices = get_all_prices_map()
    if symbol in prices:
        p = prices[symbol]
        return p["close"], p.get("change_pct", 0)
    # MF NAV
    r = sb().table("mutual_funds").select("nav,change_pct").eq("symbol", symbol).execute()
    if r.data and r.data[0]["nav"]:
        return r.data[0]["nav"], r.data[0].get("change_pct", 0)
    # Fixed income
    r2 = sb().table("fixed_income").select("current_price").eq("symbol", symbol).execute()
    if r2.data and r2.data[0]["current_price"]:
        return r2.data[0]["current_price"], 0.0
    # Commodity
    r3 = sb().table("commodities").select("price_per_unit,change_pct").eq("symbol", symbol).execute()
    if r3.data and r3.data[0]["price_per_unit"]:
        return r3.data[0]["price_per_unit"], r3.data[0].get("change_pct", 0)
    return 0.0, 0.0

def get_asset_info(symbol: str):
    """Get asset master info from any table."""
    r = sb().table("assets").select("*").eq("symbol", symbol).execute()
    if r.data:
        return r.data[0]
    r2 = sb().table("mutual_funds").select("*").eq("symbol", symbol).execute()
    if r2.data:
        return r2.data[0]
    r3 = sb().table("fixed_income").select("*").eq("symbol", symbol).execute()
    if r3.data:
        return r3.data[0]
    r4 = sb().table("commodities").select("*").eq("symbol", symbol).execute()
    if r4.data:
        return r4.data[0]
    return None
