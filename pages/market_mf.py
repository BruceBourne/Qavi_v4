import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate, back_button
from utils.db import sb, get_mutual_funds, clear_market_cache
from utils.crypto import indian_format
from collections import defaultdict

# ── SEBI CATEGORY TAXONOMY ────────────────────────────────────────────────
# Maps AMFI's raw scheme_category / sub_category strings → Qavi taxonomy.
# AMFI uses strings like "Equity Scheme - Large Cap Fund",
# "Debt Scheme - Liquid Fund", etc.
# We parse both the category group and sub-type.

SEBI_TAXONOMY = {
    # ── Equity India ──────────────────────────────────────────────────────
    "Equity": {
        "Large Cap Fund":                 ("Equity India", "Large Cap"),
        "Mid Cap Fund":                   ("Equity India", "Mid Cap"),
        "Small Cap Fund":                 ("Equity India", "Small Cap"),
        "Large & Mid Cap Fund":           ("Equity India", "Large & Mid Cap"),
        "Flexi Cap Fund":                 ("Equity India", "Flexi Cap"),
        "Multi Cap Fund":                 ("Equity India", "Multi Cap"),
        "Focused Fund":                   ("Equity India", "Focused Fund"),
        "ELSS":                           ("Equity India", "ELSS (Tax Saving)"),
        "Sectoral/Thematic":              ("Equity India", "Sectoral / Thematic"),
        "Dividend Yield Fund":            ("Equity India", "Dividend Yield"),
        "Value Fund":                     ("Equity India", "Value / Contra"),
        "Contra Fund":                    ("Equity India", "Value / Contra"),
    },
    # ── Debt ──────────────────────────────────────────────────────────────
    "Debt": {
        "Overnight Fund":                 ("Debt", "Overnight Fund"),
        "Liquid Fund":                    ("Debt", "Liquid Fund"),
        "Ultra Short Duration Fund":      ("Debt", "Ultra Short Duration"),
        "Low Duration Fund":              ("Debt", "Low Duration"),
        "Short Duration Fund":            ("Debt", "Short Duration"),
        "Medium Duration Fund":           ("Debt", "Medium Duration"),
        "Medium to Long Duration Fund":   ("Debt", "Medium to Long Duration"),
        "Long Duration Fund":             ("Debt", "Long Duration"),
        "Dynamic Bond":                   ("Debt", "Dynamic Bond"),
        "Money Market Fund":              ("Debt", "Money Market"),
        "Corporate Bond Fund":            ("Debt", "Corporate Bond"),
        "Banking and PSU Fund":           ("Debt", "Banking & PSU"),
        "Credit Risk Fund":               ("Debt", "Credit Risk"),
        "Floater Fund":                   ("Debt", "Floater"),
        "Gilt Fund":                      ("Debt", "Gilt"),
        "Gilt Fund with 10 year constant duration": ("Debt", "Gilt 10Y"),
    },
    # ── Hybrid ────────────────────────────────────────────────────────────
    "Hybrid": {
        "Aggressive Hybrid Fund":         ("Hybrid", "Aggressive Hybrid"),
        "Conservative Hybrid Fund":       ("Hybrid", "Conservative Hybrid"),
        "Balanced Advantage":             ("Hybrid", "Balanced Advantage (BAF)"),
        "Dynamic Asset Allocation":       ("Hybrid", "Balanced Advantage (BAF)"),
        "Multi Asset Allocation":         ("Hybrid", "Multi Asset Allocation"),
        "Arbitrage Fund":                 ("Hybrid", "Arbitrage Fund"),
        "Equity Savings":                 ("Hybrid", "Equity Savings"),
    },
    # ── International ─────────────────────────────────────────────────────
    "International": {
        "": ("International", "Global Diversified"),
    },
    # ── Solution Oriented ─────────────────────────────────────────────────
    "Solution Oriented": {
        "Retirement Fund":                ("Solution Oriented", "Retirement Fund"),
        "Children's Fund":                ("Solution Oriented", "Children's Fund"),
    },
    # ── Index / ETF / FOF (excluded from MF page) ─────────────────────────
    "Index Funds/ETFs": {
        "": ("Index / ETF", "Index Fund"),
    },
    "Other Scheme": {
        "Fund of Funds":                  ("Fund of Funds", "FOF"),
    },
}

# Strings that identify ETFs / FOFs that should NOT appear in MF list
ETF_FOF_KEYWORDS = [
    "etf", "exchange traded", "fund of fund", "fof", "index fund",
    "nifty 50 etf", "sensex etf",
]

def _classify(raw_category: str, raw_sub: str, name: str):
    """
    Returns (display_category, display_sub) for a fund.

    After the _sebi_normalise fix, stored values are:
      category    = "Equity" | "Debt" | "Hybrid" | "Solution Oriented" | "ETF" | "Fund of Funds"
      sub_category = "Large Cap Fund" | "Liquid Fund" | "Aggressive Hybrid Fund" | ...
                     (extracted from the " - " part of AMFI scheme_category string)

    This function maps those stored values to Qavi display taxonomy.
    Also handles old stored values like "Equity Scheme - Large Cap Fund" for backward
    compatibility with already-imported funds.
    """
    cat_lo  = raw_category.lower()
    sub_lo  = raw_sub.lower()
    name_lo = name.lower()

    # Exclude ETFs and FOFs — they belong in the ETF page
    if cat_lo in ("etf", "fund of funds"):
        return None, None
    if any(k in name_lo for k in ETF_FOF_KEYWORDS):
        return None, None
    if "etf" in cat_lo or "exchange traded" in cat_lo:
        return None, None
    if "fund of fund" in cat_lo or "fof" in sub_lo:
        return None, None

    # ── International / Overseas ─────────────────────────────────────────
    intl_kw = ("overseas", "international", "global", "us fund", "world", "foreign",
               "developed market", "emerging market", "nasdaq", "s&p 500", "hang seng")
    if any(k in name_lo or k in sub_lo for k in intl_kw):
        return "International", _intl_sub(name_lo)

    # ── Equity ───────────────────────────────────────────────────────────
    if "equity" in cat_lo:
        group_map = SEBI_TAXONOMY["Equity"]
        # sub_lo now contains "large cap fund", "mid cap fund" etc — match directly
        for key, (cat, sub) in group_map.items():
            if key.lower() in sub_lo:
                return cat, sub
        # Fallback: try name
        for key, (cat, sub) in group_map.items():
            if key.lower() in name_lo:
                return cat, sub
        return "Equity India", "Equity Other"

    # ── Debt ─────────────────────────────────────────────────────────────
    if "debt" in cat_lo:
        group_map = SEBI_TAXONOMY["Debt"]
        for key, (cat, sub) in group_map.items():
            if key.lower() in sub_lo:
                return cat, sub
        # Some debt fund names contain the sub-type
        for key, (cat, sub) in group_map.items():
            if key.lower() in name_lo:
                return cat, sub
        return "Debt", "Debt Other"

    # ── Hybrid ───────────────────────────────────────────────────────────
    if "hybrid" in cat_lo:
        group_map = SEBI_TAXONOMY["Hybrid"]
        for key, (cat, sub) in group_map.items():
            if key.lower() in sub_lo or key.lower() in name_lo:
                return cat, sub
        return "Hybrid", "Hybrid Other"

    # ── Solution Oriented ────────────────────────────────────────────────
    if "solution" in cat_lo:
        if "retire" in sub_lo or "retire" in name_lo: return "Solution Oriented", "Retirement Fund"
        if "child"  in sub_lo or "child"  in name_lo: return "Solution Oriented", "Children's Fund"
        return "Solution Oriented", "Other"

    # ── Other / catch-all ────────────────────────────────────────────────
    if "other" in cat_lo:
        return None, None

    # ── Backward compat: old raw AMFI strings still in DB ────────────────
    # e.g. category = "Equity Scheme - Large Cap Fund" (stored before the fix)
    if "equity scheme" in cat_lo:
        group_map = SEBI_TAXONOMY["Equity"]
        combined  = cat_lo + " " + sub_lo + " " + name_lo
        if any(k in name_lo or k in sub_lo for k in intl_kw):
            return "International", _intl_sub(name_lo)
        for key, (cat, sub) in group_map.items():
            if key.lower() in combined:
                return cat, sub
        return "Equity India", "Equity Other"
    if "debt scheme" in cat_lo:
        group_map = SEBI_TAXONOMY["Debt"]
        combined  = cat_lo + " " + sub_lo
        for key, (cat, sub) in group_map.items():
            if key.lower() in combined:
                return cat, sub
        return "Debt", "Debt Other"
    if "hybrid scheme" in cat_lo:
        group_map = SEBI_TAXONOMY["Hybrid"]
        combined  = cat_lo + " " + sub_lo + " " + name_lo
        for key, (cat, sub) in group_map.items():
            if key.lower() in combined:
                return cat, sub
        return "Hybrid", "Hybrid Other"

    return "Other", raw_sub or "Other"

def _intl_sub(name_lo):
    if "us" in name_lo or "america" in name_lo or "nasdaq" in name_lo or "s&p" in name_lo:
        return "US-focused"
    if "europe" in name_lo or "developed" in name_lo:
        return "Developed Markets"
    if "emerging" in name_lo or "asia" in name_lo or "china" in name_lo:
        return "Emerging Markets"
    if "tech" in name_lo or "ai" in name_lo or "digital" in name_lo:
        return "Global Thematic (Tech / AI)"
    if "energy" in name_lo or "clean" in name_lo or "esg" in name_lo:
        return "Global Thematic (ESG / Clean Energy)"
    return "Global Diversified"

def _is_direct(name: str) -> bool:
    return "direct" in name.lower()

def _plan_type(name: str) -> str:
    """IDCW / Growth — treat as plan type, not separate fund."""
    n = name.lower()
    if "idcw" in n or "dividend" in n: return "IDCW"
    return "Growth"

def _base_name(name: str) -> str:
    """
    Strip plan-type suffixes so IDCW and Growth variants show as one fund.
    'Axis Bluechip Fund - Direct Plan - IDCW' → 'Axis Bluechip Fund - Direct Plan'
    """
    import re
    n = re.sub(r"\s*[-–]\s*(idcw|dividend|growth|reinvestment|payout)\s*$",
               "", name, flags=re.IGNORECASE).strip()
    return n

def _deduplicate(funds: list) -> list:
    """
    Collapse IDCW and Growth variants into a single row per fund.
    Prefer Growth plan data; keep scheme_codes of both variants for reference.
    Priority: Direct > Regular, Growth > IDCW.
    """
    from collections import defaultdict
    groups: dict[str, list] = defaultdict(list)
    for f in funds:
        key = _base_name(f.get("name",""))
        groups[key].append(f)

    result = []
    for base_name, variants in groups.items():
        # Sort: Direct > Regular, Growth > IDCW
        def _priority(v):
            n = v.get("name","").lower()
            return (
                0 if "direct" in n else 1,
                0 if ("growth" in n and "idcw" not in n and "dividend" not in n) else 1,
            )
        variants.sort(key=_priority)
        chosen = variants[0]
        # Attach metadata about available variants
        chosen["_variants"] = [
            {"name": v["name"], "scheme_code": v.get("scheme_code",""),
             "plan_type": _plan_type(v["name"]),
             "is_direct": _is_direct(v["name"])}
            for v in variants
        ]
        chosen["_plan_type"]  = _plan_type(chosen["name"])
        chosen["_is_direct"]  = _is_direct(chosen["name"])
        result.append(chosen)
    return result

# ── DISPLAY HELPERS ───────────────────────────────────────────────────────
def _ret_cell(val, key):
    if val is None: return f"<div style='font-size:.82rem;color:#8892AA'>—</div>"
    c = "#2ECC7A" if val >= 0 else "#FF5A5A"
    return f"<div style='font-size:.84rem;font-weight:600;color:{c}'>{val:+.1f}%</div>"

def _risk_badge(rl):
    colors = {"Low":"#2ECC7A","Moderate":"#F5B731","High":"#FF5A5A",
              "Very High":"#DC2626","Low to Moderate":"#A3E635"}
    c = colors.get(rl,"#8892AA")
    return (f"<span style='font-size:.72rem;color:{c};font-weight:600;"
            f"background:{c}18;border-radius:4px;padding:.1rem .4rem'>{rl or '—'}</span>")

# ── RENDER ────────────────────────────────────────────────────────────────
def render():
    st.markdown('<div class="page-title">Mutual Funds</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">SEBI-categorised · NAVs from AMFI · Returns computed from history</div>',
                unsafe_allow_html=True)

    # Nav bar
    b1,b2,b3,b4,b5 = st.columns(5)
    if b1.button("Equities",         use_container_width=True): navigate("market_equities")
    if b2.button("Mutual Funds",      use_container_width=True): pass
    if b3.button("ETFs",              use_container_width=True): navigate("market_etf")
    if b4.button("Bonds",             use_container_width=True): navigate("market_bonds")
    if b5.button("FDs & Commodities", use_container_width=True): navigate("market_fd")
    st.markdown("<br>", unsafe_allow_html=True)

    # Filters — search + risk only (no plan/IDCW — market page shows Growth only)
    fc1, fc2 = st.columns([2.5, 1.5])
    search      = fc1.text_input("🔍 Search", placeholder="Fund name, AMC, or category…",
                                  label_visibility="collapsed", key="mf_search")
    risk_filter = fc2.selectbox("Risk", ["All","Low","Low to Moderate","Moderate","High","Very High"],
                                 key="mf_risk")

    benefit_filter   = "Growth"    # Market page always shows Growth plans
    idcw_freq_filter = None        # Not used

    # Load all MFs
    raw_funds = get_mutual_funds(search=search if search else None)

    # Classify, filter ETFs/FOFs, deduplicate plan variants
    classified = []
    for f in raw_funds:
        cat, sub = _classify(
            f.get("category",""), f.get("sub_category",""), f.get("name","")
        )
        if cat is None: continue   # ETF or FOF — skip
        f["_cat"] = cat
        f["_sub"] = sub
        classified.append(f)

    deduped = _deduplicate(classified)

    # Apply filters
    # Show both Direct and Regular — user chose during import
    # (Direct preferred during import, but don't hide regular if present)
    if risk_filter != "All":
        deduped = [f for f in deduped if f.get("risk_level","") == risk_filter]
    # Benefit option filter
    # Always filter to Growth only on market page — IDCW excluded
    deduped = [f for f in deduped
               if f.get("benefit_option","Growth") == "Growth"
               or (not f.get("benefit_option")
                   and "idcw" not in f.get("name","").lower()
                   and "dividend" not in f.get("name","").lower())]

    # Group by category → sub-category
    by_cat = defaultdict(lambda: defaultdict(list))
    for f in deduped:
        by_cat[f["_cat"]][f["_sub"]].append(f)

    # Category display order
    CAT_ORDER = [
        "Equity India", "International", "Debt", "Hybrid",
        "Solution Oriented", "Fund of Funds", "Other"
    ]
    cat_icons = {
        "Equity India":"📈", "International":"🌍", "Debt":"🏦",
        "Hybrid":"⚖️", "Solution Oriented":"🎯", "Other":"📋"
    }
    # Sub-category order within each category
    SUB_ORDER = {
        "Equity India": ["Large Cap","Mid Cap","Small Cap","Large & Mid Cap",
                         "Flexi Cap","Multi Cap","Focused Fund","ELSS (Tax Saving)",
                         "Sectoral / Thematic","Dividend Yield","Value / Contra","Equity Other"],
        "International":["US-focused","Developed Markets","Emerging Markets",
                          "Global Diversified","Global Thematic (Tech / AI)",
                          "Global Thematic (ESG / Clean Energy)"],
        "Debt":         ["Overnight Fund","Liquid Fund","Ultra Short Duration",
                         "Low Duration","Short Duration","Medium Duration",
                         "Medium to Long Duration","Long Duration","Dynamic Bond",
                         "Money Market","Corporate Bond","Banking & PSU",
                         "Credit Risk","Floater","Gilt","Gilt 10Y","Debt Other"],
        "Hybrid":       ["Aggressive Hybrid","Conservative Hybrid",
                         "Balanced Advantage (BAF)","Multi Asset Allocation",
                         "Arbitrage Fund","Equity Savings","Hybrid Other"],
    }

    PAGE_SIZE = 50
    total_shown = 0
    for cat in CAT_ORDER + [c for c in by_cat if c not in CAT_ORDER]:
        subs = by_cat.get(cat, {})
        if not subs: continue
        cat_total = sum(len(v) for v in subs.values())
        total_shown += cat_total
        icon = cat_icons.get(cat,"📋")

        with st.expander(f"{icon} **{cat}** — {cat_total} funds",
                         expanded=(cat == "Equity India" and not search)):

            sub_order = SUB_ORDER.get(cat, sorted(subs.keys()))
            for sub in sub_order + [s for s in subs if s not in sub_order]:
                items = subs.get(sub, [])
                if not items: continue

                # Sort alphabetically
                items_sorted = sorted(items, key=lambda x: x.get("name","").lower())
                n_pages      = max(1, (len(items_sorted) + PAGE_SIZE - 1) // PAGE_SIZE)
                page_key     = f"mf_pg_{cat[:6]}_{sub[:8]}"
                cur_page     = st.session_state.get(page_key, 0)
                cur_page     = max(0, min(cur_page, n_pages - 1))
                page_items   = items_sorted[cur_page*PAGE_SIZE : (cur_page+1)*PAGE_SIZE]
                start_n      = cur_page * PAGE_SIZE + 1
                end_n        = min((cur_page+1) * PAGE_SIZE, len(items_sorted))

                sub_label = (f'{sub} &nbsp;'
                             f'<span style="color:#4E5A70;font-weight:400">'
                             f'({len(items_sorted)} funds'
                             f'{f", page {cur_page+1}/{n_pages}" if n_pages>1 else ""})'
                             f'</span>')
                st.markdown(
                    f'<div style="font-size:.71rem;color:#A855F7;font-weight:700;'
                    f'letter-spacing:.08em;margin:.7rem 0 .3rem;text-transform:uppercase">'
                    f'{sub_label}</div>', unsafe_allow_html=True)

                # Table header
                hdr = st.columns([3.5, 1, 1.2, 1, 1, 1, 1, 0.5])
                for col,lbl in zip(hdr, ["Fund","Risk","NAV","1Y","3Y","5Y","TER",""]):
                    col.markdown(
                        f"<div style='font-size:.73rem;color:#8892AA;font-weight:600'>{lbl}</div>",
                        unsafe_allow_html=True)
                st.markdown('<hr class="divider"/>', unsafe_allow_html=True)

                for m in page_items:
                    aum    = m.get("aum",0) or 0
                    aum_s  = f"₹{indian_format(round(aum/1e7))} Cr" if aum >= 1e7 else ""
                    ter    = m.get("expense_ratio")
                    r1y    = m.get("return_1y")
                    r3y    = m.get("return_3y")
                    r5y    = m.get("return_5y")
                    nav    = m.get("nav",0)
                    chg    = m.get("change_pct",0)
                    chg_c  = "#2ECC7A" if chg >= 0 else "#FF5A5A"
                    rl     = m.get("risk_level","")

                    # Plan tag — Direct/Regular indicator
                    direct_tag = ('<span style="font-size:.66rem;background:#4F7EFF22;color:#4F7EFF;'
                                  'border-radius:3px;padding:.05rem .35rem;margin-right:.3rem">Direct</span>'
                                  if m.get("_is_direct") else
                                  '<span style="font-size:.66rem;background:#8892AA22;color:#8892AA;'
                                  'border-radius:3px;padding:.05rem .35rem;margin-right:.3rem">Regular</span>')
                    variants  = m.get("_variants",[])
                    var_hint  = (f'<span style="font-size:.64rem;color:#4E5A70"> +{len(variants)-1} variants</span>'
                                 if len(variants) > 1 else "")

                    hc = st.columns([3.5, 1, 1.2, 1, 1, 1, 1, 0.5])
                    hc[0].markdown(
                        f"<div style='font-weight:600;font-size:.86rem;line-height:1.4'>"
                        f"{m['name']}</div>"
                        f"<div style='font-size:.71rem;color:#8892AA;margin-top:.15rem'>"
                        f"{m.get('fund_house','')} "
                        f"{'· '+aum_s if aum_s else ''}"
                        f"</div>"
                        f"<div style='margin-top:.2rem'>{direct_tag}{var_hint}</div>",
                        unsafe_allow_html=True)
                    hc[1].markdown(_risk_badge(rl), unsafe_allow_html=True)
                    hc[2].markdown(
                        f"<div style='font-size:.9rem;font-weight:700'>₹{indian_format(nav)}</div>"
                        f"<div style='font-size:.69rem;color:{chg_c}'>{chg:+.4f}%</div>",
                        unsafe_allow_html=True)
                    hc[3].markdown(_ret_cell(r1y, "1y"), unsafe_allow_html=True)
                    hc[4].markdown(_ret_cell(r3y, "3y"), unsafe_allow_html=True)
                    hc[5].markdown(_ret_cell(r5y, "5y"), unsafe_allow_html=True)
                    hc[6].markdown(
                        f"<div style='font-size:.82rem;color:#F5B731'>"
                        f"{f'{ter:.2f}%' if ter else '—'}</div>",
                        unsafe_allow_html=True)
                    if hc[7].button("→", key=f"mfd_{m['symbol']}_{sub[:4]}_{cur_page}"):
                        st.session_state.selected_symbol = m["symbol"]
                        navigate("asset_detail")
                    st.markdown('<hr class="divider"/>', unsafe_allow_html=True)

                # Pagination controls
                if n_pages > 1:
                    pc1, pc2, pc3 = st.columns([1, 3, 1])
                    if pc1.button("← Prev", key=f"prev_{page_key}",
                                  disabled=(cur_page == 0), use_container_width=True):
                        st.session_state[page_key] = cur_page - 1; st.rerun()
                    pc2.markdown(
                        f'<div style="text-align:center;font-size:.79rem;color:#8892AA;padding:.5rem 0">'
                        f'{start_n}–{end_n} of {len(items_sorted)} funds'
                        f' &nbsp;·&nbsp; Page {cur_page+1} of {n_pages}</div>',
                        unsafe_allow_html=True)
                    if pc3.button("Next →", key=f"next_{page_key}",
                                  disabled=(cur_page >= n_pages-1), use_container_width=True):
                        st.session_state[page_key] = cur_page + 1; st.rerun()

    if total_shown == 0:
        st.info("No mutual funds found. Go to Profile → Market Data Upload → Auto Fetch to populate.")


