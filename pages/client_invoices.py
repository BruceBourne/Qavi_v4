import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate, back_button
from utils.db import get_invoices_for_client, sb
from utils.crypto import inr, indian_format, fmt_date
import base64

def render():
    user = st.session_state.get("user")
    if not user:
        navigate("login"); return
    # Advisors/owners use the main invoices page
    if user["role"] in ("advisor", "owner"):
        navigate("invoices"); return

    back_button(fallback="dashboard", key="top")
    st.markdown('<div class="page-title">My Invoices</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Invoices issued to you by your advisor</div>',
                unsafe_allow_html=True)

    invoices = get_invoices_for_client(user["id"])

    if not invoices:
        st.markdown("""
        <div style="background:#161B27;border:1px solid #252D40;border-radius:12px;
            padding:2rem 2.2rem;text-align:center;margin-top:1rem">
            <div style="font-size:1.5rem;margin-bottom:.6rem;color:#4E5A70">🧾</div>
            <div style="font-size:.92rem;color:#C8D0E0;font-weight:600;margin-bottom:.4rem">
                No invoices yet
            </div>
            <div style="font-size:.81rem;color:#8892AA;line-height:1.75">
                Your advisor will issue invoices here when applicable.<br>
                This page will show all your billing history, amounts, and downloadable invoice PDFs.
            </div>
        </div>
        """, unsafe_allow_html=True)
        return

    # Summary metrics
    paid_invs   = [i for i in invoices if i.get("status") == "paid"]
    unpaid_invs = [i for i in invoices if i.get("status") != "paid" and i.get("status") != "draft"]
    total_billed = sum(i.get("amount", 0) for i in invoices if i.get("status") != "draft")
    total_paid   = sum(i.get("amount", 0) for i in paid_invs)
    total_unpaid = sum(i.get("amount", 0) for i in unpaid_invs)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Invoices", len(invoices))
    m2.metric("Total Billed",   inr(total_billed))
    m3.metric("Paid",           inr(total_paid))
    m4.metric("Outstanding",    inr(total_unpaid))

    st.markdown("<br>", unsafe_allow_html=True)

    STATUS_COLORS = {
        "paid":    "#2ECC7A",
        "unpaid":  "#FF5A5A",
        "overdue": "#FF8C00",
        "draft":   "#8892AA",
    }

    for inv in invoices:
        status  = inv.get("status", "draft")
        sc      = STATUS_COLORS.get(status, "#8892AA")
        amount  = inv.get("amount", 0)
        inv_num = inv.get("invoice_number", "—")
        inv_dt  = fmt_date(inv.get("invoice_date", ""))
        due_dt  = fmt_date(inv.get("due_date", ""))

        with st.expander(
            f"#{inv_num}  ·  {inv_dt}  ·  ₹{indian_format(amount)}  ·  "
            f"{status.upper()}"
        ):
            c1, c2, c3 = st.columns(3)
            c1.markdown(
                f"**Invoice:** {inv_num}<br>"
                f"**Date:** {inv_dt}<br>"
                f"**Due:** {due_dt}",
                unsafe_allow_html=True)
            c2.markdown(
                f"**Fee Type:** {inv.get('fee_type','—').title()}<br>"
                f"**Amount:** ₹{indian_format(amount)}<br>"
                f"**Status:** <span style='color:{sc};font-weight:700'>"
                f"{status.upper()}</span>",
                unsafe_allow_html=True)
            c3.markdown(
                f"**Period:** {fmt_date(inv.get('period_from',''))} – "
                f"{fmt_date(inv.get('period_to',''))}<br>"
                f"**Portfolio Value:** ₹{indian_format(inv.get('portfolio_value',0))}",
                unsafe_allow_html=True)

            # Download for non-draft invoices
            if status != "draft":
                try:
                    adv_r = sb().table("users").select("full_name,email")\
                                .eq("id", inv.get("advisor_id","")).execute()
                    adv = adv_r.data[0] if adv_r.data else {}
                except Exception:
                    adv = {}

                html = _invoice_html(inv, adv, user)
                b64  = base64.b64encode(html.encode()).decode()
                st.markdown(
                    f'<a href="data:text/html;base64,{b64}" '
                    f'download="{inv_num}.html" '
                    f'style="display:inline-block;margin-top:.6rem;'
                    f'background:#161B27;color:#F0F4FF;padding:.4rem 1rem;'
                    f'border-radius:8px;border:1px solid #252D40;'
                    f'font-size:.82rem;text-decoration:none">📥 Download Invoice</a>',
                    unsafe_allow_html=True)
            st.markdown('<hr class="divider"/>', unsafe_allow_html=True)


def _invoice_html(inv, advisor, client_user):
    from utils.crypto import title_case
    adv_name = title_case(advisor.get("full_name","") or advisor.get("email","Your Advisor"))
    cli_name = title_case(client_user.get("full_name","") or client_user.get("email",""))
    amt      = indian_format(inv.get("amount", 0))
    pv       = indian_format(inv.get("portfolio_value", 0))
    status   = inv.get("status","").upper()
    sc       = "#16a34a" if inv.get("status") == "paid" else "#dc2626"
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
body{{font-family:'Segoe UI',Arial,sans-serif;font-size:13px;color:#1e293b;background:#fff;margin:0}}
.page{{width:240mm;margin:14mm auto;padding:0}}
.hdr{{display:flex;justify-content:space-between;padding-bottom:10px;border-bottom:2px solid #1e293b;margin-bottom:14px}}
.brand{{font-style:italic;font-size:1.9rem;font-weight:700;letter-spacing:.08em;color:#1e293b}}
.row{{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #e2e8f0}}
.lbl{{color:#64748b;font-size:.87rem}}.val{{font-weight:600;font-size:.87rem}}
</style></head><body>
<div class="page">
  <div class="hdr">
    <div><div class="brand">◈ Qavi</div>
    <div style="font-size:.75rem;color:#64748b">{adv_name}</div></div>
    <div style="text-align:right">
      <div style="font-weight:700">{inv.get('invoice_number','')}</div>
      <div style="font-size:.8rem;color:#64748b">{inv.get('invoice_date','')}</div>
    </div>
  </div>
  <div style="margin-bottom:12px;font-size:.85rem;color:#64748b">
    Billed to: <b style="color:#1e293b">{cli_name}</b>
  </div>
  <div class="row"><span class="lbl">Fee Type</span><span class="val">{inv.get('fee_type','').title()}</span></div>
  <div class="row"><span class="lbl">Period</span><span class="val">{inv.get('period_from','')} – {inv.get('period_to','')}</span></div>
  <div class="row"><span class="lbl">Portfolio Value</span><span class="val">₹{pv}</span></div>
  <div class="row" style="font-size:1.05rem;font-weight:700;border-bottom:2px solid #1e293b">
    <span>Amount Due</span><span>₹{amt}</span></div>
  <div class="row"><span class="lbl">Due Date</span><span class="val">{inv.get('due_date','')}</span></div>
  <div class="row"><span class="lbl">Status</span>
    <span class="val" style="color:{sc}">{status}</span></div>
  <div style="margin-top:20px;font-size:.7rem;color:#94a3b8">
    Generated by Qavi · Portfolio intelligence platform · Not a SEBI registered advisor</div>
</div></body></html>"""
