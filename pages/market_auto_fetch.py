"""
market_auto_fetch.py — Automatic MF & ETF data sourcing

Sources used (all free, no API key required):
  1. mfapi.in/mf/{code}           — NAV, historical NAV, fund meta       [PRIMARY]
  2. mfapi.in/mf/{code}/details   — AUM, expense ratio, exit load,
                                    min investment, lock-in, risk         [EXTENDED META]
  3. mfapi.in/mf/{code}/portfolio — Top 10 holdings with % allocation    [HOLDINGS]
  4. amfiindia.com NAVAll.txt     — Active scheme detection              [FILTER]
  5. NSE API /etf                 — ETF prices, iNAV                     [ETF]
  6. Yahoo Finance (yfinance)     — ETF historical returns, expense ratio [ETF RETURNS]

Active scheme logic:
  A scheme is ACTIVE if it appears in AMFI NAVAll.txt with a NAV date
  within the last 10 trading days and is not a Segregated Portfolio,
  FMP, or Interval Fund.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate, back_button
from utils.db import sb, clear_market_cache
from datetime import datetime, date, timedelta
import time, requests

# ── CONSTANTS ─────────────────────────────────────────────────────────────
MFAPI_BASE  = "https://api.mfapi.in/mf"
AMFI_NAVALL = "https://www.amfiindia.com/spages/NAVAll.txt"

# ── SCHEME EXCLUSION LIST ─────────────────────────────────────────────────
# All strings are matched as substrings of the LOWER-CASED scheme name.
# Covers every closed-ended / matured / unwanted scheme type in the Indian
# MF industry as defined by SEBI / AMFI regulations.

# CLOSED-ENDED FUNDS — fixed tenure, not redeemable before maturity
_CLOSED_ENDED = [
    "fixed maturity plan", "fmp",          # Fixed Maturity Plans (FMPs)
    "capital protection", "capital protect",# Capital Protection Oriented Schemes
    "infrastructure debt fund",             # Infrastructure Debt Funds (IDF)
    "real estate",                          # Real Estate MFs (REIT-adjacent)
    " cef ",                                # Closed-Ended Fund abbreviation
]

# INTERVAL FUNDS — redeemable only during specified windows
_INTERVAL_FUNDS = [
    "interval fund", "interval plan",
    "interval scheme",
]

# SEGREGATED PORTFOLIOS — side-pocketed distressed assets
_SEGREGATED = [
    "segregated portfolio", "segregated fund",
    "side pocket",
]

# OTHER UNWANTED
_OTHER_UNWANTED = [
    "matured scheme",                        # explicitly matured / wound-up
    "wound up",
    "under suspension",
    "fund of funds - overseas",              # FOF-Overseas have RBI/SEBI limits
]

# Combined — used in active scheme filter
_EXCLUDE_KEYWORDS = (
    _CLOSED_ENDED + _INTERVAL_FUNDS + _SEGREGATED + _OTHER_UNWANTED
)

# ── INDIAN MF PLAN / BENEFIT / PAYMENT TAXONOMY ───────────────────────────
#
# SEBI MF regulations define two orthogonal axes for every scheme:
#
# 1. PLAN TYPE (distribution channel)
#    • Direct Plan  — investor buys directly from AMC, no distributor commission
#    • Regular Plan — bought via distributor/broker, higher TER
#
# 2. OPTION TYPE (what happens to dividends/income declared by the fund)
#    a) GROWTH Option
#       • No payouts — all gains reinvested, NAV grows over time
#       • Ideal for long-term wealth creation
#
#    b) IDCW Option (Income Distribution cum Capital Withdrawal)
#       Previously called "Dividend" — renamed by SEBI in 2021
#       Sub-options by PAYOUT FREQUENCY:
#         • Daily IDCW       — very rare, only liquid/overnight funds
#         • Weekly IDCW      — liquid / money market funds
#         • Fortnightly IDCW — rare
#         • Monthly IDCW     — debt / MIP / balanced advantage funds
#         • Quarterly IDCW   — debt / hybrid funds
#         • Half-Yearly IDCW — debt funds
#         • Annual IDCW      — equity / hybrid (mostly regular plans)
#         • Flexi IDCW       — declared at fund manager discretion
#       Sub-options by PAYOUT METHOD:
#         • Payout           — cash paid to investor's bank account
#         • Reinvestment     — IDCW amount used to buy more units at NAV
#         • Transfer (IDCW-T)— transferred to another scheme (rare)
#
#    c) BONUS Option — bonus units issued (mostly legacy, phased out)
#
# 3. PAYMENT / INVESTMENT MODE (how the investor invests — NOT part of scheme name)
#    • Lump Sum (One-time)
#    • SIP — Systematic Investment Plan
#        Frequencies: Daily / Weekly / Fortnightly / Monthly / Quarterly / Annual
#    • STP — Systematic Transfer Plan (from one fund to another)
#    • SWP — Systematic Withdrawal Plan
#
# For DB storage: we store plan_type (Direct/Regular), benefit_option (Growth/IDCW/Bonus),
# idcw_frequency (Monthly/Quarterly/etc.), idcw_method (Payout/Reinvestment).
# Payment mode (SIP/Lump Sum) is stored at the holdings level, not the fund level.
#
# FILTER STRATEGY (for auto-fetch):
# By default import only: Direct + Growth plans.
# This gives one clean row per fund — the most commonly preferred option.
# Regular and IDCW variants are available via their own scheme codes if needed.

def _parse_plan(name: str) -> dict:
    """
    Parse an AMFI scheme name to extract:
      plan_type     : "Direct" | "Regular"
      benefit_option: "Growth" | "IDCW" | "Bonus" | "Unknown"
      idcw_frequency: "Daily" | "Weekly" | "Fortnightly" | "Monthly" |
                      "Quarterly" | "Half-Yearly" | "Annual" | "Flexi" | ""
      idcw_method   : "Payout" | "Reinvestment" | "Transfer" | ""
    """
    n = name.lower()

    # Plan type
    plan_type = "Direct" if "direct" in n else "Regular"

    # Benefit option — check IDCW first (more specific)
    idcw_freq   = ""
    idcw_method = ""

    is_idcw = (
        "idcw" in n or
        ("dividend" in n and "yield" not in n)  # "dividend yield fund" ≠ IDCW
    )
    is_bonus = "bonus" in n

    if is_idcw:
        benefit_option = "IDCW"
        # Frequency detection
        for freq, kws in [
            ("Daily",       ("daily",)),
            ("Weekly",      ("weekly",)),
            ("Fortnightly", ("fortnightly", "bi-weekly", "biweekly")),
            ("Monthly",     ("monthly",)),
            ("Quarterly",   ("quarterly",)),
            ("Half-Yearly", ("half-yearly", "halfyearly", "half yearly", "bi-annual", "biannual")),
            ("Annual",      ("annual", "yearly")),
            ("Flexi",       ("flexi",)),
        ]:
            if any(k in n for k in kws):
                idcw_freq = freq
                break

        # Method detection
        if "reinvest" in n:
            idcw_method = "Reinvestment"
        elif "transfer" in n:
            idcw_method = "Transfer"
        elif "payout" in n or "pay out" in n:
            idcw_method = "Payout"
        else:
            idcw_method = "Payout"   # AMFI default when not specified

    elif is_bonus:
        benefit_option = "Bonus"
    elif "growth" in n:
        benefit_option = "Growth"
    else:
        # Fallback: if no keyword, AMFI default for modern schemes is Growth
        benefit_option = "Growth"

    return {
        "plan_type":      plan_type,
        "benefit_option": benefit_option,
        "idcw_frequency": idcw_freq,
        "idcw_method":    idcw_method,
    }

def _is_direct_growth(name: str) -> bool:
    """True only for Direct + Growth plans — the preferred import filter."""
    p = _parse_plan(name)
    return p["plan_type"] == "Direct" and p["benefit_option"] == "Growth"

def _is_regular_growth(name: str) -> bool:
    p = _parse_plan(name)
    return p["plan_type"] == "Regular" and p["benefit_option"] == "Growth"

# ── HELPERS ───────────────────────────────────────────────────────────────
def _get(url, timeout=15, headers=None, session=None):
    try:
        h = {"User-Agent": "Mozilla/5.0 (compatible; QaviBot/1.0)"}
        if headers: h.update(headers)
        fn = (session or requests).get
        r  = fn(url, headers=h, timeout=timeout)
        r.raise_for_status()
        return r, None
    except Exception as e:
        return None, str(e)

def _pct(new, old):
    if old and old != 0:
        return round((new - old) / old * 100, 4)
    return 0.0

def _f(v, d=0.0):
    try: return float(str(v).replace(",","").strip())
    except: return d

# ── ACTIVE SCHEME DETECTION ───────────────────────────────────────────────
@st.cache_data(ttl=3600)
def fetch_active_scheme_codes():
    """
    Returns (set_of_active_codes, status_message).
    Downloads AMFI NAVAll.txt — only open-ended live schemes appear here.
    Filters to schemes with NAV date within last 10 days.
    NAVAll.txt columns (semicolon-separated):
      Code ; ISIN1 ; ISIN2 ; Scheme Name ; NAV ; Date
    """
    r, err = _get(AMFI_NAVALL, timeout=20)
    if err or not r:
        return set(), f"AMFI NAVAll fetch failed: {err}"

    active  = set()
    cutoff  = date.today() - timedelta(days=10)
    skipped = 0

    for line in r.text.strip().split("\n"):
        line = line.strip()
        if not line or ";" not in line or line.startswith("Scheme Code"):
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 6:
            continue
        try:
            code     = parts[0]
            name_low = parts[3].lower()
            nav_str  = parts[5].strip()
            if any(kw in name_low for kw in _EXCLUDE_KEYWORDS):
                skipped += 1; continue
            for fmt in ("%d-%b-%Y", "%d-%m-%Y"):
                try:
                    if datetime.strptime(nav_str, fmt).date() >= cutoff:
                        active.add(code)
                    break
                except ValueError:
                    continue
        except Exception:
            continue

    return active, f"{len(active)} active schemes (cutoff {cutoff}, {skipped} excluded)"

# ── MFAPI ENDPOINTS ───────────────────────────────────────────────────────
def fetch_mf_nav(code):
    """Returns (meta_dict, navs_list, error)."""
    r, err = _get(f"{MFAPI_BASE}/{code}", timeout=12)
    if err: return None, None, err
    try:
        d = r.json()
        return d.get("meta", {}), d.get("data", []), None
    except Exception as e:
        return None, None, str(e)

def fetch_mf_details(code):
    """
    /details endpoint: expenseRatio, exitLoad, aum, minInvestment,
    minAdditionalInvestment, riskLevel, fundManager, launchDate, lockInPeriod.
    Returns (dict, error).
    """
    r, err = _get(f"{MFAPI_BASE}/{code}/details", timeout=12)
    if err: return {}, err
    try: return r.json(), None
    except Exception as e: return {}, str(e)

def fetch_mf_portfolio(code):
    """
    /portfolio endpoint: top holdings.
    Returns (list_of_holdings, error).
    Each holding: {company, isin, percentage, sector}
    """
    r, err = _get(f"{MFAPI_BASE}/{code}/portfolio", timeout=12)
    if err: return [], err
    try:
        items = r.json().get("data", [])
        return [
            {
                "company":    h.get("company", h.get("name", "")),
                "isin":       h.get("isin", ""),
                "percentage": _f(h.get("percentage", 0)),
                "sector":     h.get("sector", ""),
            }
            for h in items[:10]
        ], None
    except Exception as e:
        return [], str(e)

def fetch_all_amfi_schemes():
    r, err = _get(MFAPI_BASE, timeout=15)
    if err: return None, err
    try: return r.json(), None
    except Exception as e: return None, str(e)

def compute_returns(navs):
    """Compute point-to-point returns from [{date, nav}] list (newest first)."""
    if not navs: return {}
    try:
        parsed = []
        for item in navs:
            try:
                d = datetime.strptime(item["date"], "%d-%m-%Y").date()
                parsed.append((d, float(item["nav"])))
            except: continue
        if not parsed: return {}
        parsed.sort(key=lambda x: x[0], reverse=True)
        cur, cur_dt = parsed[0]

        def _ret(days):
            tgt = cur_dt - timedelta(days=days)
            cl  = min(parsed, key=lambda x: abs((x[0]-tgt).days))
            return _pct(cur, cl[1]) if abs((cl[0]-tgt).days) <= 15 else None

        return {k: v for k, v in {
            "return_1m":  _ret(30),
            "return_3m":  _ret(91),
            "return_6m":  _ret(182),
            "return_1y":  _ret(365),
            "return_3y":  _ret(365*3),
            "return_5y":  _ret(365*5),
            "return_10y": _ret(365*10),
        }.items() if v is not None}
    except: return {}

def _build_row(code, meta, navs, details, include_returns=True):
    """Build complete mutual_funds table row from all sources."""
    if not navs: return None
    try:
        cur  = float(navs[0]["nav"])
        prev = float(navs[1]["nav"]) if len(navs) > 1 else cur
    except: return None

    row = {
        "scheme_code":   code,
        "symbol":        f"MF{code}",
        "name":          meta.get("scheme_name", f"MF{code}"),
        "fund_house":    meta.get("fund_house", ""),
        **dict(zip(("category","sub_category"),
                   _sebi_normalise(
                       meta.get("scheme_category",""),
                       meta.get("scheme_type",""),
                       meta.get("scheme_name","")))),
        "nav":           cur,
        "prev_nav":      prev,
        "change_pct":    _pct(cur, prev),
        "nav_date":      navs[0].get("date", ""),
        "last_updated":  datetime.now().isoformat(),
    }
    # Parse and store plan/benefit/payment classification from scheme name
    scheme_name = meta.get("scheme_name", "")
    _plan = _parse_plan(scheme_name)
    row["plan_type"]      = _plan["plan_type"]
    row["benefit_option"] = _plan["benefit_option"]
    row["idcw_frequency"] = _plan["idcw_frequency"]
    row["idcw_method"]    = _plan["idcw_method"]
    if details:
        if details.get("expenseRatio")           is not None: row["expense_ratio"]         = _f(details["expenseRatio"])
        if details.get("exitLoad")               is not None: row["exit_load"]             = str(details["exitLoad"])
        if details.get("aum")                    is not None: row["aum"]                   = _f(details["aum"])
        if details.get("minInvestment")          is not None: row["min_investment"]        = _f(details["minInvestment"])
        if details.get("minAdditionalInvestment")is not None: row["min_additional_invest"] = _f(details["minAdditionalInvestment"])
        if details.get("riskLevel"):                          row["risk_level"]            = str(details["riskLevel"])
        if details.get("fundManager"):                        row["fund_manager"]          = str(details["fundManager"])
        if details.get("launchDate"):                         row["launch_date"]           = str(details["launchDate"])
        if details.get("lockInPeriod") is not None:          row["lock_in_period"]        = str(details["lockInPeriod"])

    if include_returns:
        row.update(compute_returns(navs))
    return row


def _sebi_normalise(raw_category: str, raw_sub: str, name: str):
    """
    Map AMFI scheme_category + scheme_type → (category, sub_category) for DB storage.

    mfapi.in returns:
      meta.scheme_category = "Equity Scheme - Large Cap Fund"  ← full AMFI string
      meta.scheme_type     = "Open Ended Schemes"               ← not useful for sub-type
      meta.scheme_name     = "Axis Bluechip Fund - Direct Plan - Growth"

    The sub-category MUST be extracted from the scheme_category string (after the " - ").
    Using scheme_type for sub_category was the bug that sent everything to "Other".
    """
    import re
    cat_lo  = raw_category.lower()
    name_lo = name.lower()

    # ── Tag ETFs / FOFs first ─────────────────────────────────────────────
    etf_kw = ("etf", "exchange traded", "index fund")
    fof_kw = ("fund of fund", "fof - domestic", "fof - overseas", "other scheme - fund of funds")
    if any(k in name_lo or k in cat_lo for k in etf_kw):
        return "ETF", "Index ETF"
    if any(k in cat_lo for k in fof_kw):
        return "Fund of Funds", "FOF"

    # ── Extract sub-type from the scheme_category string ─────────────────
    # AMFI format: "Equity Scheme - Large Cap Fund"
    #              "Debt Scheme - Liquid Fund"
    #              "Hybrid Scheme - Aggressive Hybrid Fund"
    # The part after " - " is the actual SEBI sub-category.
    sub_from_cat = ""
    if " - " in raw_category:
        sub_from_cat = raw_category.split(" - ", 1)[1].strip()
    elif "–" in raw_category:
        sub_from_cat = raw_category.split("–", 1)[1].strip()

    # Also strip any trailing plan keywords that may have leaked in
    sub_from_cat = re.sub(
        r"\s*[-–]?\s*(idcw|dividend|growth|reinvestment|payout|direct|regular)$",
        "", sub_from_cat, flags=re.IGNORECASE
    ).strip()

    # ── SEBI category → (category, sub_category) ─────────────────────────
    # Full list of AMFI scheme_category prefixes:
    if "equity scheme" in cat_lo:
        return "Equity", sub_from_cat or "Equity Other"

    if "debt scheme" in cat_lo:
        return "Debt", sub_from_cat or "Debt Other"

    if "hybrid scheme" in cat_lo:
        return "Hybrid", sub_from_cat or "Hybrid Other"

    if "solution oriented" in cat_lo:
        return "Solution Oriented", sub_from_cat or "Solution Oriented"

    if "index fund" in cat_lo:
        return "ETF", "Index Fund"   # index funds → ETF page

    if "other scheme" in cat_lo:
        # "Other Scheme - Fund of Funds (Domestic)" etc.
        if "fund of fund" in cat_lo:
            return "Fund of Funds", sub_from_cat or "FOF"
        return "Other", sub_from_cat or "Other"

    # Fallback — try to classify from fund name when category is unhelpful
    if not raw_category or raw_category.lower() in ("other", ""):
        return _classify_mf_from_name(name), _classify_mf_sub_from_name(name)
    return raw_category or "Other", sub_from_cat or raw_sub or "Other"


def _classify_mf_from_name(name: str) -> str:
    """Classify MF category purely from fund name when scheme_category is absent."""
    n = name.lower()
    if any(k in n for k in ("liquid", "overnight", "ultra short", "low duration",
                             "short duration", "medium duration", "long duration",
                             "dynamic bond", "corporate bond", "banking and psu",
                             "banking & psu", "credit risk", "gilt", "floater",
                             "money market")):
        return "Debt"
    if any(k in n for k in ("aggressive hybrid", "conservative hybrid",
                             "balanced advantage", "multi asset", "arbitrage",
                             "equity savings", "hybrid")):
        return "Hybrid"
    if any(k in n for k in ("fund of fund", " fof", "overseas fund")):
        return "Fund of Funds"
    if any(k in n for k in ("retirement", "children", "child care")):
        return "Solution Oriented"
    if any(k in n for k in ("etf", "exchange traded", "index fund")):
        return "ETF"
    # Default to Equity for unmatched (most funds are equity)
    return "Equity"


def _classify_mf_sub_from_name(name: str) -> str:
    """Classify MF sub-category purely from fund name."""
    n = name.lower()
    # Equity subs
    if "large cap" in n or "bluechip" in n or "blue chip" in n or "large-cap" in n:
        return "Large Cap Fund"
    if "mid cap" in n or "midcap" in n or "mid-cap" in n:
        return "Mid Cap Fund"
    if "small cap" in n or "smallcap" in n or "small-cap" in n:
        return "Small Cap Fund"
    if "large & mid" in n or "large and mid" in n:
        return "Large & Mid Cap Fund"
    if "flexi cap" in n or "flexicap" in n or "flexi-cap" in n:
        return "Flexi Cap Fund"
    if "multi cap" in n or "multicap" in n:
        return "Multi Cap Fund"
    if "elss" in n or "tax sav" in n or "tax-sav" in n:
        return "ELSS"
    if "focused" in n:
        return "Focused Fund"
    if "dividend yield" in n:
        return "Dividend Yield Fund"
    if "value fund" in n:
        return "Value Fund"
    if "contra" in n:
        return "Contra Fund"
    if "sector" in n or "thematic" in n or "psu" in n or "infra" in n or "pharma" in n:
        return "Sectoral/Thematic"
    if "international" in n or "global" in n or "overseas" in n or "us fund" in n:
        return "International"
    # Debt subs
    if "liquid" in n:           return "Liquid Fund"
    if "overnight" in n:        return "Overnight Fund"
    if "ultra short" in n:      return "Ultra Short Duration Fund"
    if "low duration" in n:     return "Low Duration Fund"
    if "short duration" in n:   return "Short Duration Fund"
    if "medium duration" in n:  return "Medium Duration Fund"
    if "long duration" in n:    return "Long Duration Fund"
    if "dynamic bond" in n:     return "Dynamic Bond"
    if "corporate bond" in n:   return "Corporate Bond Fund"
    if "banking and psu" in n or "banking & psu" in n: return "Banking and PSU Fund"
    if "credit risk" in n:      return "Credit Risk Fund"
    if "gilt" in n:             return "Gilt Fund"
    if "floater" in n:          return "Floater Fund"
    if "money market" in n:     return "Money Market Fund"
    # Hybrid subs
    if "aggressive hybrid" in n:    return "Aggressive Hybrid Fund"
    if "conservative hybrid" in n:  return "Conservative Hybrid Fund"
    if "balanced advantage" in n:   return "Balanced Advantage"
    if "multi asset" in n:          return "Multi Asset Allocation"
    if "arbitrage" in n:            return "Arbitrage Fund"
    if "equity savings" in n:       return "Equity Savings"
    return ""

# ── ETF HELPERS ───────────────────────────────────────────────────────────
def _nse_session():
    """
    NSE requires a proper cookie chain: homepage → market page → API call.
    Without cookies from prior page visits the API returns 401/403.
    """
    sess = requests.Session()
    base_headers = {
        "User-Agent":      ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"),
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
    }
    sess.headers.update(base_headers)
    # Step 1: homepage — establishes initial cookies
    try:
        sess.get("https://www.nseindia.com/", timeout=10)
    except Exception:
        pass
    time.sleep(1.0)
    # Step 2: market data page — NSE validates cookie chain from this page
    try:
        sess.get("https://www.nseindia.com/market-data/exchange-traded-funds-etf", timeout=10)
    except Exception:
        pass
    time.sleep(0.8)
    return sess

def fetch_etf_data_nse():
    """
    Fetch ETF list from NSE.
    Falls back to a curated static list if NSE API is unavailable (common
    outside Indian market hours or after NSE header changes).
    """
    sess = _nse_session()
    api_headers = {
        "Accept":           "application/json, text/plain, */*",
        "Referer":          "https://www.nseindia.com/market-data/exchange-traded-funds-etf",
        "X-Requested-With": "XMLHttpRequest",
        "sec-fetch-dest":   "empty",
        "sec-fetch-mode":   "cors",
        "sec-fetch-site":   "same-origin",
    }
    r, err = _get(
        "https://www.nseindia.com/api/etf",
        session=sess,
        headers=api_headers,
        timeout=15,
    )
    if err or not r:
        return None, f"NSE API error: {err}"
    try:
        data = r.json()
        if isinstance(data, dict) and "data" in data:
            return data["data"], None
        # Some NSE responses return the list directly
        if isinstance(data, list):
            return data, None
        return None, f"Unexpected NSE response format: {str(data)[:100]}"
    except Exception as e:
        return None, str(e)

def fetch_yf_returns(symbol_ns):
    try:
        import yfinance as yf
        tk    = yf.Ticker(symbol_ns)
        hist  = tk.history(period="5y")
        if hist.empty: return {}
        prices = hist["Close"].dropna()
        cur    = float(prices.iloc[-1])
        now_dt = prices.index[-1]

        def _ret(days):
            subset = prices[prices.index <= now_dt - timedelta(days=days)]
            return _pct(cur, float(subset.iloc[-1])) if not subset.empty else None

        info = {}
        try: info = tk.info or {}
        except: pass
        return {k: v for k, v in {
            "return_1m":     _ret(30),  "return_3m":     _ret(91),
            "return_6m":     _ret(182), "return_1y":     _ret(365),
            "return_3y":     _ret(365*3),"return_5y":    _ret(365*5),
            "aum":           _f(info.get("totalAssets", 0)),
            "expense_ratio": round(_f(info.get("annualReportExpenseRatio", 0)), 4),
            "fund_manager":  info.get("fundFamily", ""),
            "benchmark":     info.get("category", ""),
        }.items() if v}
    except: return {}

def fetch_mf_yf_details(symbol_yf: str) -> dict:
    """
    Fetch extended MF data from Yahoo Finance using the .BO (BSE) or
    fund symbol. Returns AUM, expense ratio, top holdings, sector breakdown.
    symbol_yf examples: "0P0000XVEK.BO", "0P00005SFK.BO" (Yahoo's own MF codes)
    or scheme_name-based lookup.
    """
    try:
        import yfinance as yf
        tk   = yf.Ticker(symbol_yf)
        info = tk.info or {}
        if not info:
            return {}

        result = {}
        if info.get("totalAssets"):
            result["aum"] = float(info["totalAssets"])
        if info.get("annualReportExpenseRatio") is not None:
            result["expense_ratio"] = round(float(info["annualReportExpenseRatio"]), 4)
        if info.get("fundFamily"):
            result["fund_house"] = str(info["fundFamily"])

        # Top holdings from Yahoo Finance
        holdings_data = []
        try:
            holdings = tk.get_institutional_holders()
            if holdings is not None and not holdings.empty:
                for _, row in holdings.head(10).iterrows():
                    holdings_data.append({
                        "company":    str(row.get("Holder", "")),
                        "percentage": float(row.get("% Out", 0) or 0) * 100,
                        "sector":     "",
                    })
        except Exception:
            pass

        # Alternatively use fund holdings if available
        try:
            fund_holdings = tk.funds_data
            if fund_holdings and hasattr(fund_holdings, "top_holdings"):
                top_h = fund_holdings.top_holdings
                if top_h is not None and not top_h.empty:
                    holdings_data = []
                    for _, row in top_h.head(10).iterrows():
                        holdings_data.append({
                            "company":    str(row.get("Symbol", row.get("Name", ""))),
                            "percentage": float(row.get("Holding Percent", 0) or 0),
                            "sector":     str(row.get("Sector", "")),
                        })
        except Exception:
            pass

        if holdings_data:
            import json
            result["top_holdings"] = json.dumps(holdings_data)

        # Sector breakdown
        try:
            fund_data = tk.funds_data
            if fund_data and hasattr(fund_data, "sector_weightings"):
                sectors = fund_data.sector_weightings
                if sectors:
                    result["sector_breakdown"] = json.dumps(
                        {k: round(v * 100, 2) for k, v in sectors.items() if v}
                    )
        except Exception:
            pass

        # Market cap breakdown (Large/Mid/Small)
        try:
            if fund_data and hasattr(fund_data, "equity_holdings"):
                eq = fund_data.equity_holdings
                if eq:
                    result["cap_breakdown"] = json.dumps({
                        "large_cap": round(float(eq.get("priceToEarnings", 0)), 2),
                    })
        except Exception:
            pass

        return result
    except Exception:
        return {}


def _etf_sub(name):
    n = name.upper()
    if any(k in n for k in ("GOLD","SILVER","METAL","COMMODITY")): return "Commodity ETF"
    if any(k in n for k in ("LIQUID","MONEY","OVERNIGHT")):         return "Liquid ETF"
    if any(k in n for k in ("BANK","FIN","INFRA","IT","PHARMA","AUTO","SECTOR")): return "Sectoral ETF"
    return "Index ETF"

# ── PAGE ──────────────────────────────────────────────────────────────────
def render():
    if not st.session_state.get("user") or \
       st.session_state.user["role"] not in ("advisor","owner"):
        navigate("login"); return

    back_button(fallback="market_upload", key="top")

    st.markdown('<div class="page-title">Auto Fetch MF & ETF Data</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">NAV · AUM · Expense Ratio · Exit Load · Top Holdings · Returns</div>', unsafe_allow_html=True)

    st.markdown("""
    <div style="background:#1E2535;border:1px solid #252D40;border-radius:8px;
        padding:.9rem 1.2rem;margin-bottom:1rem;font-size:.8rem;color:#C8D0E0;line-height:2">
        <b>Data sources (all free, no API key needed):</b><br>
        🟢 <b>mfapi.in</b> — NAV, full historical NAV, fund meta (AMFI official)<br>
        🟢 <b>mfapi.in/details</b> — AUM, expense ratio (TER), exit load, min investment, risk level, fund manager<br>
        🟢 <b>mfapi.in/portfolio</b> — Top 10 holdings with % allocation and sector<br>
        🟢 <b>AMFI NAVAll.txt</b> — Active scheme detection (only live open-ended schemes)<br>
        🟢 <b>NSE API</b> — ETF live prices, iNAV, volume<br>
        🟡 <b>Yahoo Finance</b> — ETF returns, expense ratio, AUM (requires yfinance package)
    </div>
    """, unsafe_allow_html=True)

    tab_mf, tab_etf = st.tabs(["  🏦 Mutual Funds  ", "  💛 ETFs  "])

    # ══ MUTUAL FUNDS ══════════════════════════════════════════════════════
    with tab_mf:
        st.markdown("#### Mutual Fund Auto-Fetch")
        mode = st.radio("What to fetch", [
            "Update NAV + details for existing MFs in DB",
            "Fetch full details for specific scheme codes",
            "Bulk import from AMFI (active schemes only)",
        ], horizontal=False, key="mf_mode")

        # ── Mode 1: Update existing ────────────────────────────────────
        if mode == "Update NAV + details for existing MFs in DB":
            st.caption("Fetches latest NAV, AUM, expense ratio, exit load and returns for all MFs already in your DB.")
            c1, c2 = st.columns(2)
            inc_ret  = c1.checkbox("Compute historical returns", value=True, key="u_ret")
            inc_det  = c1.checkbox("Fetch AUM / expense ratio / exit load", value=True, key="u_det")
            inc_hld  = c2.checkbox("Fetch top 10 holdings", value=False,
                                    help="~1 extra call per fund — use selectively", key="u_hld")
            limit_n  = c2.number_input("Max funds (0 = all)", min_value=0, value=0, step=50, key="u_lim")

            # Plan filter — what to update (only affects _build_row classification, not filtering existing DB)
            st.caption("ℹ️ Plan classification (Direct/Regular, Growth/IDCW) is re-parsed from scheme name on every fetch.")

            if st.button("🚀 Fetch from AMFI", use_container_width=True, key="do_mf_nav"):
                try:
                    existing = sb().table("mutual_funds").select("symbol,scheme_code,name").execute().data or []
                except Exception as e:
                    st.error(f"DB error: {e}"); return

                if not existing:
                    st.warning("No MFs in database. Use Bulk import first."); return

                to_update = existing[:int(limit_n)] if limit_n > 0 else existing
                prog = st.progress(0.0); status = st.empty()
                ok = err = skipped = 0

                for i, mf in enumerate(to_update):
                    code = str(mf.get("scheme_code","")).strip()
                    if not code: skipped += 1; continue

                    meta, navs, ferr = fetch_mf_nav(code)
                    if ferr or not navs: err += 1; time.sleep(0.1); continue

                    details = {}
                    if inc_det:
                        details, _ = fetch_mf_details(code)
                        time.sleep(0.05)

                    row = _build_row(code, meta, navs, details, inc_ret)
                    if not row: err += 1; continue

                    if inc_hld:
                        holdings, _ = fetch_mf_portfolio(code)
                        if holdings:
                            import json
                            row["top_holdings"] = json.dumps(holdings)
                        time.sleep(0.08)

                    # Yahoo Finance extended data (sector, cap breakdown, holdings by stock)
                    if inc_yf_mf:
                        # Build Yahoo symbol: try scheme_code as Yahoo MF code with suffix
                        # Yahoo MF codes for India are like "0P0000XVEK" — not numeric AMFI codes
                        # Best effort: try fund name-based lookup or skip if no match
                        yf_sym = code + yf_symbol_input.strip()
                        yf_ext = fetch_mf_yf_details(yf_sym)
                        if yf_ext:
                            # Only update fields that YF found and that mfapi didn't already provide
                            for fld in ("aum","expense_ratio","top_holdings","sector_breakdown"):
                                if fld in yf_ext and fld not in row:
                                    row[fld] = yf_ext[fld]
                        time.sleep(0.3)

                    try:
                        sb().table("mutual_funds").update(row).eq("scheme_code", code).execute()
                        ok += 1
                    except: err += 1

                    prog.progress((i+1)/len(to_update), text=f"{i+1}/{len(to_update)}")
                    if (i+1) % 10 == 0:
                        status.markdown(f'<span style="font-size:.8rem;color:#C8D0E0">✓ {ok} updated · {err} errors · {skipped} skipped</span>', unsafe_allow_html=True)
                    time.sleep(0.05)

                prog.progress(1.0, text="Done ✓")
                clear_market_cache()
                st.success(f"✅ {ok} updated · {err} errors · {skipped} skipped (no scheme code)")

        # ── Mode 2: Specific codes ─────────────────────────────────────
        elif mode == "Fetch full details for specific scheme codes":
            st.caption("Enter AMFI scheme codes (one per line). Find codes at mfapi.in or valueresearchonline.com")
            codes_raw = st.text_area("Scheme codes", placeholder="119598\n120503\n118989", height=120)
            c1, c2 = st.columns(2)
            inc_ret2 = c1.checkbox("Compute returns", value=True, key="s_ret")
            inc_det2 = c1.checkbox("Fetch AUM / expense / exit load", value=True, key="s_det")
            inc_hld2 = c2.checkbox("Fetch top 10 holdings", value=True, key="s_hld")

            st.caption("ℹ️ Plan type (Direct/Regular/Growth/IDCW) is auto-detected from the scheme name and stored.")
            if st.button("🔍 Fetch Details", use_container_width=True, key="do_mf_specific"):
                codes = [c.strip() for c in codes_raw.strip().split("\n") if c.strip()]
                if not codes: st.error("Enter at least one scheme code."); return

                prog = st.progress(0.0); inserted = updated = err = 0

                for i, code in enumerate(codes):
                    meta, navs, ferr = fetch_mf_nav(code)
                    if ferr or not navs:
                        st.warning(f"Scheme {code}: {ferr or 'No NAV data'}")
                        err += 1; continue

                    details = {}
                    if inc_det2:
                        details, _ = fetch_mf_details(code); time.sleep(0.05)

                    row = _build_row(code, meta, navs, details, inc_ret2)
                    if not row: err += 1; continue

                    if inc_hld2:
                        holdings, _ = fetch_mf_portfolio(code)
                        if holdings:
                            import json; row["top_holdings"] = json.dumps(holdings)
                        time.sleep(0.08)

                    try:
                        if sb().table("mutual_funds").select("id").eq("scheme_code", code).execute().data:
                            sb().table("mutual_funds").update(row).eq("scheme_code", code).execute(); updated += 1
                        else:
                            sb().table("mutual_funds").insert(row).execute(); inserted += 1
                    except Exception as db_e:
                        st.warning(f"DB error {code}: {db_e}"); err += 1

                    prog.progress((i+1)/len(codes), text=f"{i+1}/{len(codes)}")
                    time.sleep(0.1)

                prog.progress(1.0, text="Done ✓")
                clear_market_cache()
                st.success(f"✅ {inserted} added · {updated} updated · {err} errors")

        # ── Mode 3: Bulk import active only ───────────────────────────
        else:
            st.caption("Downloads AMFI's full list, filters to **active open-ended schemes** only, then imports.")

            with st.expander("ℹ️ What counts as active / excluded?"):
                st.markdown("""
                **Active** = listed in AMFI NAVAll.txt with NAV date within last 10 trading days.

                **Default settings fetch Growth plans only** — no IDCW, no sub-annual distribution,
            no FMPs, no closed-ended funds. This gives you long-term compounding funds suitable
            for portfolio tracking. Change filters below only if you specifically need income funds.

            **Always excluded** (regardless of filters below):
                - Fixed Maturity Plans (FMP) — closed-ended, fixed tenure
                - Capital Protection Oriented Schemes — closed-ended
                - Interval Funds / Interval Plans — limited redemption windows
                - Segregated Portfolios / Side Pockets — distressed assets
                - Infrastructure Debt Funds
                - Matured / Wound-up schemes
                """)

            st.markdown("**Step 1 — Scheme Type Filters**")
            fe1, fe2, fe3 = st.columns(3)
            exc_fof      = fe1.checkbox("Exclude Fund of Funds (FOF)", value=False,
                                         help="FOF-Domestic can be useful; FOF-Overseas have SEBI limits")
            exc_overseas = fe2.checkbox("Exclude FOF-Overseas", value=True,
                                         help="Subject to $7B industry-wide SEBI limit — often suspended")
            exc_etf_idx  = fe3.checkbox("Exclude ETF/Index Funds", value=True,
                                         help="These belong in the ETF page, not MF NAV list")

            st.markdown("**Step 2 — Plan Type**")
            pc1, pc2 = st.columns(2)
            want_direct  = pc1.checkbox("Direct Plans",  value=True,
                                         help="No distributor commission — lower TER")
            want_regular = pc2.checkbox("Regular Plans", value=False,
                                         help="Higher TER due to distributor trail commission")
            if not want_direct and not want_regular:
                st.warning("Select at least one plan type.")

            st.markdown("**Step 3 — Benefit Option**")
            bc1, bc2, bc3 = st.columns(3)
            want_growth = bc1.checkbox("Growth",  value=True,
                                        help="NAV compounds — ideal for long-term wealth creation")
            want_idcw   = bc2.checkbox("IDCW",    value=False,
                                        help="Income Distribution cum Capital Withdrawal (formerly Dividend)")
            want_bonus  = bc3.checkbox("Bonus",   value=False,
                                        help="Legacy bonus-unit option — mostly phased out")

            # IDCW frequency sub-filter (only shown when IDCW is ticked)
            idcw_freqs_wanted = set()
            if want_idcw:
                st.markdown("↳ **IDCW Frequencies to include:**")
                if1,if2,if3,if4,if5,if6,if7,if8 = st.columns(8)
                if if1.checkbox("Daily",        value=False, key="idf_daily"):   idcw_freqs_wanted.add("Daily")
                if if2.checkbox("Weekly",       value=False, key="idf_weekly"):  idcw_freqs_wanted.add("Weekly")
                if if3.checkbox("Fortnightly",  value=False, key="idf_ftly"):   idcw_freqs_wanted.add("Fortnightly")
                if if4.checkbox("Monthly",      value=True,  key="idf_mth"):    idcw_freqs_wanted.add("Monthly")
                if if5.checkbox("Quarterly",    value=True,  key="idf_qtr"):    idcw_freqs_wanted.add("Quarterly")
                if if6.checkbox("Half-Yearly",  value=False, key="idf_half"):   idcw_freqs_wanted.add("Half-Yearly")
                if if7.checkbox("Annual",       value=False, key="idf_ann"):    idcw_freqs_wanted.add("Annual")
                if if8.checkbox("Flexi/Other",  value=True,  key="idf_flexi"):  idcw_freqs_wanted.add("Flexi")
                if not idcw_freqs_wanted:
                    st.warning("Select at least one IDCW frequency.")

            st.markdown("**Step 4 — Additional Filters**")
            c1, c2 = st.columns(2)
            filt_house = c1.text_input("Filter by AMC name (optional)", placeholder="SBI, HDFC, Mirae…", key="bl_amc")
            filt_cat   = c2.text_input("Filter by category keyword (optional)", placeholder="Equity, Debt, Hybrid…", key="bl_cat")
            c3, c4 = st.columns(2)
            inc_det3 = c3.checkbox("Fetch AUM / expense ratio / exit load", value=True, key="bl_det")
            inc_ret3 = c4.checkbox("Compute returns from NAV history", value=True, key="bl_ret")
            max_imp  = st.number_input("Max schemes to import", min_value=1, max_value=5000, value=300, step=50)

            if st.button("📋 Load & Preview Filtered Scheme List", use_container_width=True, key="amfi_load"):
                with st.spinner("Fetching active codes from AMFI…"):
                    active_codes, active_msg = fetch_active_scheme_codes()
                st.info(f"AMFI active filter: {active_msg}")

                with st.spinner("Fetching full scheme list from mfapi…"):
                    all_schemes, serr = fetch_all_amfi_schemes()
                if serr:
                    st.error(f"mfapi error: {serr}"); return

                total_raw = len(all_schemes)

                # ── Step 1: Active only
                schemes = [s for s in all_schemes
                           if str(s.get("schemeCode","")) in active_codes]
                n_after_active = len(schemes)

                # ── Step 1b: Closed-ended / always-excluded
                def _is_excluded(name):
                    n = name.lower()
                    return any(kw in n for kw in _EXCLUDE_KEYWORDS)

                schemes = [s for s in schemes if not _is_excluded(s.get("schemeName",""))]
                n_after_excl = len(schemes)

                # ── Step 2: Type filters
                def _is_fof(name):
                    n = name.lower()
                    return "fund of fund" in n or " fof " in n or n.endswith(" fof")
                def _is_overseas(name):
                    n = name.lower()
                    return "overseas" in n or "foreign" in n
                def _is_etf_idx(name):
                    n = name.lower()
                    return any(k in n for k in ("etf","exchange traded","index fund","nifty etf","sensex etf"))

                if exc_overseas:
                    schemes = [s for s in schemes
                               if not (_is_fof(s.get("schemeName","")) and _is_overseas(s.get("schemeName","")))]
                if exc_fof:
                    schemes = [s for s in schemes if not _is_fof(s.get("schemeName",""))]
                if exc_etf_idx:
                    schemes = [s for s in schemes if not _is_etf_idx(s.get("schemeName",""))]
                n_after_type = len(schemes)

                # ── Step 3: Plan type filter
                plan_filtered = []
                for s in schemes:
                    p = _parse_plan(s.get("schemeName",""))
                    if p["plan_type"] == "Direct"  and want_direct:  plan_filtered.append(s)
                    elif p["plan_type"] == "Regular" and want_regular: plan_filtered.append(s)
                schemes = plan_filtered
                n_after_plan = len(schemes)

                # ── Step 4: Benefit option filter
                benefit_filtered = []
                for s in schemes:
                    p = _parse_plan(s.get("schemeName",""))
                    bo = p["benefit_option"]
                    if bo == "Growth" and want_growth:
                        benefit_filtered.append(s)
                    elif bo == "IDCW" and want_idcw:
                        # Apply IDCW frequency sub-filter if any freqs selected
                        if idcw_freqs_wanted:
                            freq = p["idcw_frequency"] or "Flexi"
                            if freq in idcw_freqs_wanted:
                                benefit_filtered.append(s)
                        else:
                            benefit_filtered.append(s)
                    elif bo == "Bonus" and want_bonus:
                        benefit_filtered.append(s)
                schemes = benefit_filtered
                n_after_benefit = len(schemes)

                # ── Step 5: Text filters
                if filt_house.strip():
                    fh = filt_house.strip().lower()
                    schemes = [s for s in schemes if fh in s.get("schemeName","").lower()]
                if filt_cat.strip():
                    fc = filt_cat.strip().lower()
                    schemes = [s for s in schemes if fc in s.get("schemeName","").lower()]
                schemes = schemes[:max_imp]

                # Show filter funnel summary
                st.markdown(f"""
                <div style="background:#0F1117;border:1px solid #252D40;border-radius:8px;
                    padding:.8rem 1.1rem;margin:.6rem 0;font-size:.8rem;color:#C8D0E0;line-height:2">
                    <b>Filter funnel:</b><br>
                    All AMFI schemes: <b>{total_raw:,}</b><br>
                    → Active (NAV within 10 days): <b>{n_after_active:,}</b><br>
                    → After closed-ended exclusions: <b>{n_after_excl:,}</b><br>
                    → After type filters (FOF/ETF): <b>{n_after_type:,}</b><br>
                    → After plan filter (Direct/Regular): <b>{n_after_plan:,}</b><br>
                    → After benefit filter (Growth/IDCW): <b>{n_after_benefit:,}</b><br>
                    → After text + max filters: <b style="color:#2ECC7A">{len(schemes):,} schemes ready</b>
                </div>
                """, unsafe_allow_html=True)

                if schemes:
                    import pandas as pd
                    # Show richer preview with plan info
                    preview_rows = []
                    for s in schemes[:15]:
                        p = _parse_plan(s.get("schemeName",""))
                        preview_rows.append({
                            "Code": s["schemeCode"],
                            "Name": s["schemeName"][:65],
                            "Plan": p["plan_type"],
                            "Option": p["benefit_option"] + (f" {p['idcw_frequency']}" if p["idcw_frequency"] else ""),
                        })
                    st.dataframe(pd.DataFrame(preview_rows), use_container_width=True)
                    if len(schemes) > 15:
                        st.caption(f"…and {len(schemes)-15} more")
                elif want_direct or want_regular:
                    st.warning("No schemes matched. Adjust filters above.")

                st.session_state["_amfi_schemes"] = schemes

            if st.session_state.get("_amfi_schemes"):
                schemes = st.session_state["_amfi_schemes"]

                if st.button(f"⬆️ Import {len(schemes)} Schemes", use_container_width=True, key="do_amfi_import"):
                    prog = st.progress(0.0); status = st.empty()
                    inserted = updated = err = 0
                    try:
                        existing_codes = {str(r["scheme_code"]) for r in
                                          sb().table("mutual_funds").select("scheme_code").execute().data or []}
                    except: existing_codes = set()

                    for i, s in enumerate(schemes):
                        code = str(s["schemeCode"])
                        meta, navs, ferr = fetch_mf_nav(code)
                        if ferr or not navs: err += 1; time.sleep(0.05); continue

                        details = {}
                        if inc_det3:
                            details, _ = fetch_mf_details(code); time.sleep(0.05)

                        row = _build_row(code, meta, navs, details, inc_ret3)
                        if not row: err += 1; continue

                        try:
                            if code in existing_codes:
                                sb().table("mutual_funds").update(row).eq("scheme_code", code).execute(); updated += 1
                            else:
                                sb().table("mutual_funds").insert(row).execute(); inserted += 1; existing_codes.add(code)
                        except: err += 1

                        prog.progress((i+1)/len(schemes), text=f"{i+1}/{len(schemes)}")
                        if (i+1) % 20 == 0:
                            status.markdown(f'<span style="font-size:.8rem;color:#C8D0E0">✓ {inserted} added · {updated} updated · {err} errors</span>', unsafe_allow_html=True)
                        time.sleep(0.08)

                    prog.progress(1.0, text="Done ✓")
                    clear_market_cache()
                    st.session_state.pop("_amfi_schemes", None)
                    st.success(f"✅ {inserted} new MFs added · {updated} updated · {err} errors")

    # ══ ETFs ══════════════════════════════════════════════════════════════
    with tab_etf:
        st.markdown("#### ETF Auto-Fetch")
        st.info("**Sources:** NSE for live prices / iNAV · Yahoo Finance for returns, AUM, expense ratio.")

        etf_mode = st.radio("What to fetch", [
            "Update prices for existing ETFs in DB",
            "Fetch all ETFs from NSE (full list)",
        ], horizontal=False, key="etf_mode")
        inc_yf = st.checkbox("Include Yahoo Finance data (returns, expense ratio, AUM)", value=True, key="etf_yf")

        if etf_mode == "Update prices for existing ETFs in DB":
            if st.button("🚀 Fetch ETF Prices from NSE", use_container_width=True, key="do_etf_nse"):
                with st.spinner("Connecting to NSE…"):
                    nse_etfs, err = fetch_etf_data_nse()
                if err: st.warning(f"NSE: {err}"); nse_etfs = []
                if not nse_etfs: st.error("No ETF data from NSE."); return

                nse_map = {e.get("symbol","").upper(): e for e in nse_etfs if e.get("symbol")}
                try:
                    existing = sb().table("assets").select("symbol,name").eq("asset_class","ETF").execute().data or []
                except Exception as e: st.error(f"DB: {e}"); return
                if not existing: st.warning("No ETFs in DB. Use Fetch all first."); return

                prog = st.progress(0.0); now = datetime.now().isoformat(); today = str(date.today()); ok = err = 0

                for i, etf in enumerate(existing):
                    sym = etf["symbol"]; nse_r = nse_map.get(sym)
                    close = _f(nse_r.get("lastPrice",0)) if nse_r else 0
                    inav  = _f(nse_r.get("iNavValue",0)) if nse_r else 0
                    prev  = _f(nse_r.get("previousClose",0)) if nse_r else 0
                    chg   = _f(nse_r.get("pChange",0)) if nse_r else 0
                    vol   = int(_f(nse_r.get("totalTradedVolume",0))) if nse_r else 0
                    price = close or inav
                    if price > 0:
                        try:
                            sb().table("prices").upsert({
                                "symbol": sym, "price_date": today,
                                "close": price, "open": _f(nse_r.get("open",price)) if nse_r else price,
                                "high": _f(nse_r.get("dayHigh",price)) if nse_r else price,
                                "low":  _f(nse_r.get("dayLow",price))  if nse_r else price,
                                "prev_close": prev or price, "change_pct": chg,
                                "volume": vol, "last_updated": now,
                            }, on_conflict="symbol,price_date").execute()
                            ok += 1
                        except: err += 1
                    if inc_yf:
                        yf = fetch_yf_returns(f"{sym}.NS")
                        if yf:
                            upd = {k: yf[k] for k in ("return_1m","return_3m","return_6m","return_1y","return_3y","return_5y","expense_ratio","aum","fund_manager","benchmark") if yf.get(k)}
                            if upd:
                                try: sb().table("assets").update(upd).eq("symbol", sym).execute()
                                except: pass
                        time.sleep(0.3)
                    prog.progress((i+1)/len(existing), text=f"{i+1}/{len(existing)}")
                    time.sleep(0.05)

                prog.progress(1.0, text="Done ✓"); clear_market_cache()
                st.success(f"✅ {ok} ETF prices updated · {err} skipped")

        else:
            st.caption("Fetches the complete NSE ETF list and adds any new ones to your database.")
            if st.button("📥 Fetch All ETFs from NSE", use_container_width=True, key="do_etf_all"):
                with st.spinner("Fetching NSE ETF list…"):
                    nse_etfs, err = fetch_etf_data_nse()
                if err or not nse_etfs: st.error(f"NSE fetch failed: {err or 'No data'}"); return

                st.markdown(f"**{len(nse_etfs)} ETFs** found on NSE.")
                try:
                    ex_syms = {r["symbol"] for r in sb().table("assets").select("symbol").eq("asset_class","ETF").execute().data or []}
                except: ex_syms = set()

                prog = st.progress(0.0); now = datetime.now().isoformat(); today = str(date.today())
                inserted = updated = err = 0

                for i, e in enumerate(nse_etfs):
                    sym  = str(e.get("symbol","")).upper().strip()
                    name = e.get("companyName", sym)
                    if not sym: continue

                    close = _f(e.get("lastPrice",0)); prev = _f(e.get("previousClose",0))
                    chg   = _f(e.get("pChange",0));   inav = _f(e.get("iNavValue",0))
                    vol   = int(_f(e.get("totalTradedVolume",0)))

                    try:
                        sb().table("assets").upsert({
                            "symbol": sym, "name": name, "asset_class": "ETF",
                            "sub_class": _etf_sub(name), "exchange": "NSE",
                            "is_active": True, "unit_type": "units",
                        }, on_conflict="symbol").execute()
                        updated += 1 if sym in ex_syms else None
                        if sym not in ex_syms: inserted += 1; ex_syms.add(sym)
                    except: err += 1; continue

                    price = close or inav
                    if price > 0:
                        try:
                            sb().table("prices").upsert({
                                "symbol": sym, "price_date": today,
                                "close": price, "open": _f(e.get("open",price)),
                                "high": _f(e.get("dayHigh",price)), "low": _f(e.get("dayLow",price)),
                                "prev_close": prev or price, "change_pct": chg,
                                "volume": vol, "last_updated": now,
                            }, on_conflict="symbol,price_date").execute()
                        except: pass

                    if inc_yf:
                        yf = fetch_yf_returns(f"{sym}.NS")
                        if yf:
                            upd = {k: yf[k] for k in ("return_1m","return_3m","return_6m","return_1y","return_3y","return_5y","expense_ratio","aum","fund_manager","benchmark") if yf.get(k)}
                            if upd:
                                try: sb().table("assets").update(upd).eq("symbol", sym).execute()
                                except: pass
                        time.sleep(0.3)

                    prog.progress((i+1)/len(nse_etfs), text=f"{i+1}/{len(nse_etfs)}")
                    time.sleep(0.02)

                prog.progress(1.0, text="Done ✓"); clear_market_cache()
                st.success(f"✅ {inserted} new ETFs added · {updated} updated · {err} errors")

    back_button(fallback="market_upload", label="← Back", key="bot")
