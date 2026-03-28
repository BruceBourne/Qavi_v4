import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
from utils.session import navigate, back_button
from utils.db import get_invoices_for_client, sb
from utils.crypto import inr, fmt_date, indian_format
import base64

FEE_TYPES = {
    "management":    "Management Fee",
    "performance":   "Performance Fee",
    "advisory":      "Advisory Fee",
    "retainer":      "Retainer Fee",
    "transaction":   "Transaction Fee",
    "flat":          "Flat Fee",
}

def render():
    user = st.session_state.get("user")
    if not user:
        navigate("login"); return
    if user["role"] not in ("client",):
        # Advisors/owners view invoices via the main invoices page
        navigate("invoices"); return

    back_button(fallback="dashboard", key="top")

    st.markdown('<div class="page-title">My Invoices</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-sub">Invoices issued to you by your advisor</div>',
                unsafe_allow_html=True)

    invoices = get_invoices_for_client(user["id"])

    if not invoices:
        st.info("No invoices have been issued to your account yet.")
        return

    # Summary metrics
    total_billed = sum(inv.get("amount", 0) for inv in invoices)
    total_paid   = sum(inv.get("amount", 0) for inv in invoices if inv.get("status") == "paid")
    total_unpaid = total_billed - total_paid

    m1, m2, m3 = st.columns(3)
    m1.metric("Total Billed",  inr(total_billed))
    m2.metric("Paid",          inr(total_paid))
    m3.metric("Outstanding",   inr(total_unpaid))

    st.markdown("<br>", unsafe_allow_html=True)

    STATUS_COLORS = {"paid":"#2ECC7A","unpaid":"#FF5A5A","draft":"#8892AA"}

    for inv in invoices:
        sc      = STATUS_COLORS.get(inv.get("status","draft"), "#8892AA")
        fee_lbl = FEE_TYPES.get(inv.get("fee_type",""), inv.get("fee_type","—"))

        with st.expander(
            f"#{inv['invoice_number']}  ·  {fmt_date(inv.get('invoice_date',''))}  ·  "
            f"₹{indian_format(inv.get('amount',0))}  ·  {inv.get('status','').upper()}"
        ):
            c1, c2, c3 = st.columns(3)
            c1.markdown(
                f"**Invoice #:** {inv['invoice_number']}<br>"
                f"**Date:** {fmt_date(inv.get('invoice_date',''))}<br>"
                f"**Due:** {fmt_date(inv.get('due_date',''))}",
                unsafe_allow_html=True)
            c2.markdown(
                f"**Fee Type:** {fee_lbl}<br>"
                f"**Amount:** ₹{indian_format(inv.get('amount',0))}<br>"
                f"**Status:** <span style='color:{sc};font-weight:600'>"
                f"{inv.get('status','').upper()}</span>",
                unsafe_allow_html=True)
            c3.markdown(
                f"**Period:** {fmt_date(inv.get('period_from',''))} – "
                f"{fmt_date(inv.get('period_to',''))}<br>"
                f"**Portfolio Value:** ₹{indian_format(inv.get('portfolio_value',0))}",
                unsafe_allow_html=True)

            # Download button — clients can download their own invoice
            if inv.get("status") != "draft":
                # Fetch advisor details for invoice HTML
                try:
                    adv_r = sb().table("users").select("full_name,email")\
                                .eq("id", inv["advisor_id"]).execute()
                    adv   = adv_r.data[0] if adv_r.data else {}
                except Exception:
                    adv = {}

                inv_html = _simple_invoice_html(inv, adv, user)
                b64      = base64.b64encode(inv_html.encode()).decode()
                st.markdown(
                    f'<a href="data:text/html;base64,{b64}" '
                    f'download="{inv["invoice_number"]}.html" '
                    f'style="display:inline-block;margin-top:.5rem;'
                    f'background:#161B27;color:#F0F4FF;padding:.38rem .9rem;'
                    f'border-radius:8px;border:1px solid #252D40;'
                    f'font-size:.82rem;text-decoration:none">📥 Download Invoice</a>',
                    unsafe_allow_html=True)

            st.markdown('<hr class="divider"/>', unsafe_allow_html=True)


def _simple_invoice_html(inv, advisor, client_user):
    """Minimal client-facing invoice HTML for download."""
    from utils.crypto import title_case
    adv_name  = title_case(advisor.get("full_name","") or advisor.get("email","Your Advisor"))
    cli_name  = title_case(client_user.get("full_name","") or client_user.get("email",""))
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
body{{font-family:'Segoe UI',Arial,sans-serif;font-size:13px;color:#1e293b;background:#fff;margin:0;padding:0}}
.page{{width:260mm;min-height:160mm;margin:14mm auto;padding:0}}
.hdr{{display:flex;justify-content:space-between;padding-bottom:10px;border-bottom:2px solid #1e293b;margin-bottom:14px}}
.brand{{font-size:1.8rem;font-weight:900;letter-spacing:.1em}}
.row{{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #e2e8f0;font-size:.87rem}}
.lbl{{color:#64748b}}.val{{font-weight:600}}
</style></head><body>
<div class="page">
  <div class="hdr">
    <div><div class="brand">◈ Qavi</div>
      <div style="font-size:.75rem;color:#64748b">{adv_name}</div></div>
    <div style="text-align:right">
      <div style="font-weight:700">{inv.get('invoice_number','')}</div>
      <div style="font-size:.8rem;color:#64748b">{inv.get('invoice_date','')}</div></div>
  </div>
  <div style="margin-bottom:12px;font-size:.85rem;color:#64748b">Billed to: <b style="color:#1e293b">{cli_name}</b></div>
  <div class="row"><span class="lbl">Fee Type</span><span class="val">{inv.get('fee_type','').title()}</span></div>
  <div class="row"><span class="lbl">Period</span><span class="val">{inv.get('period_from','')} – {inv.get('period_to','')}</span></div>
  <div class="row"><span class="lbl">Portfolio Value</span><span class="val">₹{indian_format(inv.get('portfolio_value',0))}</span></div>
  <div class="row" style="font-size:1rem;font-weight:700;border-bottom:2px solid #1e293b">
    <span>Amount Due</span><span>₹{indian_format(inv.get('amount',0))}</span></div>
  <div class="row"><span class="lbl">Due Date</span><span class="val">{inv.get('due_date','')}</span></div>
  <div class="row"><span class="lbl">Status</span>
    <span class="val" style="color:{'#16a34a' if inv.get('status')=='paid' else '#dc2626'}">{inv.get('status','').upper()}</span></div>
  <div style="margin-top:20px;font-size:.72rem;color:#94a3b8">
    Generated by Qavi · Portfolio intelligence platform · Not a SEBI registered advisor</div>
</div></body></html>"""
