import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import streamlit as st
from datetime import datetime, date, timedelta
from utils.db import sb

# NSE top 50 symbols to track
NSE_SYMBOLS = [
    "RELIANCE","TCS","HDFCBANK","ICICIBANK","INFY","HINDUNILVR","ITC","BHARTIARTL",
    "KOTAKBANK","LT","AXISBANK","BAJFINANCE","MARUTI","TITAN","ASIANPAINT","WIPRO",
    "NESTLEIND","ULTRACEMCO","SUNPHARMA","DRREDDY","HCLTECH","POWERGRID","NTPC",
    "ONGC","SBIN","BAJAJFINSV","TATAMOTORS","ADANIENT","JSWSTEEL","TATASTEEL",
    "MUTHOOTFIN","PERSISTENT","COFORGE","LTIM","MAXHEALTH","APOLLOHOSP","PIDILITIND",
    "HAVELLS","VOLTAS","MPHASIS","IRFC","RVNL","RAILTEL","KALYANKJIL","HAPPSTMNDS",
]

ETF_SYMBOLS = [
    "NIFTYBEES","GOLDBEES","BANKBEES","JUNIORBEES","ICICIB22","LIQUIDBEES",
    "ITBEES","SETFNIF50","MOM100","SILVERBEES","HDFCNIFTY","CPSEETF",
]

# mfapi.in scheme codes for top MFs
MF_SCHEME_CODES = {
    "HDFC_TOP100": "120503", "SBI_BLUECHIP": "125497", "ICICI_BLUECHIP": "120586",
    "MIRAE_LARGECAP": "118825", "AXIS_MIDCAP": "120843", "DSP_MIDCAP": "107064",
    "HDFC_MIDCAP": "118989", "KOTAK_SMALLCAP": "131597", "NIPPON_SMALLCAP": "118778",
    "SBI_SMALLCAP": "125354", "PARAG_FLEXI": "122639", "CANARA_FLEXI": "101735",
    "AXIS_ELSS": "120503", "SBI_ELSS": "119598", "MIRAE_ELSS": "135781",
    "ICICI_BALANCED": "120716", "HDFC_HYBRID": "107064", "HDFC_LIQUID": "119062",
    "ICICI_LIQUID": "120505", "UTI_NIFTY50": "120503", "HDFC_NIFTY50": "118989",
}

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.nseindia.com/",
}

def _nse_session():
    """Create a requests session with NSE cookies."""
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    try:
        session.get("https://www.nseindia.com", timeout=8)
    except Exception:
        pass
    return session

def fetch_nse_quote(session, symbol: str) -> dict | None:
    """Fetch a single NSE equity quote."""
    try:
        url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol}"
        r = session.get(url, timeout=8)
        if r.status_code == 200:
            data = r.json()
            pd = data.get("priceInfo", {})
            return {
                "symbol": symbol,
                "close": pd.get("lastPrice", 0),
                "open": pd.get("open", 0),
                "high": pd.get("intraDayHighLow", {}).get("max", 0),
                "low": pd.get("intraDayHighLow", {}).get("min", 0),
                "prev_close": pd.get("previousClose", 0),
                "change_amt": pd.get("change", 0),
                "change_pct": pd.get("pChange", 0),
                "volume": data.get("marketDeptOrderBook", {}).get("tradeInfo", {}).get("totalTradedVolume", 0),
                "price_date": str(date.today()),
            }
    except Exception:
        pass
    return None

def fetch_nse_index(session, index_name: str) -> dict | None:
    """Fetch an NSE index value."""
    try:
        url = "https://www.nseindia.com/api/allIndices"
        r = session.get(url, timeout=8)
        if r.status_code == 200:
            for idx in r.json().get("data", []):
                if idx.get("index") == index_name:
                    return {
                        "value": idx.get("last", 0),
                        "prev_value": idx.get("previousClose", 0),
                        "change_pct": idx.get("percentChange", 0),
                    }
    except Exception:
        pass
    return None

def fetch_mf_nav(scheme_code: str) -> float | None:
    """Fetch latest NAV from mfapi.in."""
    try:
        r = requests.get(f"https://api.mfapi.in/mf/{scheme_code}/latest", timeout=5)
        if r.status_code == 200:
            data = r.json()
            if data.get("data"):
                return float(data["data"][0]["nav"])
    except Exception:
        pass
    return None

def fetch_mf_history(scheme_code: str, days: int = 365) -> list:
    """Fetch MF NAV history from mfapi.in."""
    try:
        r = requests.get(f"https://api.mfapi.in/mf/{scheme_code}", timeout=10)
        if r.status_code == 200:
            return r.json().get("data", [])[:days]
    except Exception:
        pass
    return []

def refresh_equity_prices():
    """Fetch and upsert latest NSE equity prices."""
    session = _nse_session()
    updated = 0
    now = datetime.now().isoformat()
    today = str(date.today())

    for symbol in NSE_SYMBOLS + ETF_SYMBOLS:
        q = fetch_nse_quote(session, symbol)
        if q and q["close"] > 0:
            try:
                sb().table("prices").upsert({
                    "symbol": symbol,
                    "price_date": today,
                    "open": q["open"],
                    "high": q["high"],
                    "low": q["low"],
                    "close": q["close"],
                    "prev_close": q["prev_close"],
                    "change_amt": q["change_amt"],
                    "change_pct": q["change_pct"],
                    "volume": q["volume"],
                    "last_updated": now,
                }, on_conflict="symbol,price_date").execute()
                updated += 1
            except Exception:
                pass

    _log_refresh("equity_prices", updated)
    return updated

def refresh_mf_navs():
    """Fetch and upsert latest MF NAVs from mfapi.in."""
    updated = 0
    now = datetime.now().isoformat()

    for symbol, code in MF_SCHEME_CODES.items():
        nav = fetch_mf_nav(code)
        if nav and nav > 0:
            # Get prev NAV
            r = sb().table("mutual_funds").select("nav").eq("symbol", symbol).execute()
            prev = r.data[0]["nav"] if r.data else nav
            chg = round(((nav - prev) / prev) * 100, 4) if prev else 0
            try:
                sb().table("mutual_funds").update({
                    "nav": nav,
                    "prev_nav": prev,
                    "change_pct": chg,
                    "nav_date": str(date.today()),
                    "last_updated": now,
                }).eq("symbol", symbol).execute()
                updated += 1
            except Exception:
                pass

    _log_refresh("mf_navs", updated)
    return updated

def refresh_indices():
    """Fetch NSE indices."""
    session = _nse_session()
    index_map = {
        "Nifty 50": "NIFTY50",
        "Nifty Bank": "NIFTYBANK",
        "Nifty Midcap 100": "NIFTYMIDCAP",
        "Nifty Smallcap 100": "NIFTYSMALLCAP",
        "Nifty IT": "NIFTYIT",
        "Nifty Pharma": "NIFTYPHARMA",
        "India VIX": "INDIA_VIX",
    }
    updated = 0
    now = datetime.now().isoformat()
    try:
        r = session.get("https://www.nseindia.com/api/allIndices", timeout=8)
        if r.status_code == 200:
            for idx in r.json().get("data", []):
                name = idx.get("index", "")
                if name in index_map:
                    sym = index_map[name]
                    sb().table("indices").upsert({
                        "symbol": sym,
                        "name": name,
                        "value": idx.get("last", 0),
                        "prev_value": idx.get("previousClose", 0),
                        "change_pct": idx.get("percentChange", 0),
                        "last_updated": now,
                    }, on_conflict="symbol").execute()
                    updated += 1
    except Exception:
        pass
    # Also try Sensex via BSE
    try:
        r2 = requests.get("https://api.bseindia.com/BseIndiaAPI/api/getScripHeaderData/w?Productcode=13&code=0&scripcode=&sttype=&series=&ISIN=", timeout=5)
        if r2.status_code == 200:
            d = r2.json()
            sensex_val = float(d.get("CurrRate", 0))
            sensex_prev = float(d.get("PrevClose", 0))
            if sensex_val > 0:
                chg = round(((sensex_val - sensex_prev) / sensex_prev) * 100, 2) if sensex_prev else 0
                sb().table("indices").upsert({
                    "symbol": "SENSEX", "name": "BSE Sensex",
                    "value": sensex_val, "prev_value": sensex_prev,
                    "change_pct": chg, "last_updated": now,
                }, on_conflict="symbol").execute()
                updated += 1
    except Exception:
        pass
    _log_refresh("indices", updated)
    return updated

def should_refresh() -> bool:
    """Check if market data is stale (>1hr old or from prev day)."""
    try:
        r = sb().table("market_refresh_log").select("refreshed_at").order("refreshed_at", desc=True).limit(1).execute()
        if not r.data:
            return True
        last = datetime.fromisoformat(r.data[0]["refreshed_at"].replace("Z", "+00:00"))
        age_mins = (datetime.now().astimezone() - last).total_seconds() / 60
        # Refresh if >60 mins old and market hours (9:15–15:30 IST Mon-Fri)
        now = datetime.now()
        is_weekday = now.weekday() < 5
        market_open = 9 * 60 + 15
        market_close = 15 * 60 + 30
        current_mins = now.hour * 60 + now.minute
        in_market_hours = market_open <= current_mins <= market_close
        return age_mins > 60 and is_weekday and in_market_hours
    except Exception:
        return False

def is_market_open() -> bool:
    now = datetime.now()
    is_weekday = now.weekday() < 5
    current_mins = now.hour * 60 + now.minute
    return is_weekday and 9 * 60 + 15 <= current_mins <= 15 * 60 + 30

def auto_refresh_if_needed():
    """Called on app boot — refreshes if stale."""
    if should_refresh():
        try:
            refresh_equity_prices()
            refresh_mf_navs()
            refresh_indices()
            # Clear Streamlit cache so new data shows
            st.cache_data.clear()
        except Exception:
            pass

def _log_refresh(refresh_type, count):
    try:
        sb().table("market_refresh_log").insert({
            "refresh_type": refresh_type,
            "records_updated": count,
            "status": "success",
        }).execute()
    except Exception:
        pass
